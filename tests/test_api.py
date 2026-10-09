import importlib
import time

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTH_DISABLED", "1")
    for var in ("RAILWAY_ENVIRONMENT", "RAILWAY_PUBLIC_DOMAIN", "CONVERT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    from app import config, db
    importlib.reload(config)
    db._conn = None
    import app.files
    import app.worker
    import app.backup_api
    import app.main
    for mod in (app.files, app.worker, app.backup_api, app.main):
        importlib.reload(mod)
    from fastapi.testclient import TestClient
    with TestClient(app.main.app) as c:
        yield c
    db._conn = None


def wait_for(client, job_id, statuses, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = next(j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == job_id)
        if job["status"] in statuses:
            return job
        time.sleep(0.2)
    raise AssertionError(f"job stuck in {job['status']}")


def test_upload_convert_download_delete(client, samples):
    with open(samples["ja_vertical_ruby"], "rb") as fh:
        r = client.post("/api/upload", files={"file": ("小説.pdf", fh, "application/pdf")})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "uploaded"

    r = client.post(f"/api/jobs/{job['id']}/start", json={"choices": ["ja_v"], "furigana": "brackets"})
    assert r.status_code == 200
    done = wait_for(client, job["id"], {"done", "failed"})
    assert done["status"] == "done", done["error"]
    assert done["directions"] == ["v"] and done["settings_label"].startswith("日文（直排")

    r = client.get(f"/api/download/{job['id']}/docx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert "filename*=utf-8''%E5%B0%8F%E8%AA%AC.docx" in r.headers["content-disposition"]

    assert client.get("/api/settings/last").json()["choices"] == ["ja_v"]

    r = client.post(f"/api/jobs/{job['id']}/retry")
    assert r.json()["status"] == "uploaded"
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert client.get("/api/jobs").json()["jobs"] == []


def test_rejects_non_pdf_and_oversize(client):
    r = client.post("/api/upload", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    r = client.post("/api/upload", files={"file": ("a.pdf", b"not a pdf at all", "application/pdf")})
    assert r.status_code == 400
    assert client.get("/api/jobs").json()["jobs"] == []


def test_password_protected_pdf(client, samples, tmp_path):
    import pymupdf
    locked = tmp_path / "locked.pdf"
    doc = pymupdf.open(samples["ko_horizontal"])
    doc.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    with open(locked, "rb") as fh:
        job = client.post("/api/upload", files={"file": ("locked.pdf", fh, "application/pdf")}).json()
    assert job["status"] == "needs_password"
    assert client.post(f"/api/jobs/{job['id']}/password", json={"password": "wrong"}).status_code == 400
    r = client.post(f"/api/jobs/{job['id']}/password", json={"password": "secret"})
    assert r.json()["status"] == "uploaded"
    client.post(f"/api/jobs/{job['id']}/start", json={"choices": ["auto"]})
    assert wait_for(client, job["id"], {"done", "failed"})["status"] == "done"


def test_pages_require_sign_in_when_auth_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    for var, val in (("GOOGLE_CLIENT_ID", "x"), ("GOOGLE_CLIENT_SECRET", "y"),
                     ("ALLOWED_EMAIL", "me@example.com"), ("SESSION_SECRET", "s")):
        monkeypatch.setenv(var, val)
    from app import config, db
    importlib.reload(config)
    db._conn = None
    import app.main
    importlib.reload(app.main)
    from fastapi.testclient import TestClient
    with TestClient(app.main.app, follow_redirects=False) as c:
        assert c.get("/").headers["location"] == "/login"
        assert c.get("/library").headers["location"] == "/login"
        assert c.get("/api/jobs").status_code == 401
        assert c.get("/login").status_code == 200
        assert c.get("/health").status_code == 200
    db._conn = None
