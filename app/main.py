"""Web app: Google sign-in, upload, job controls, library and downloads."""

from __future__ import annotations

import errno
from contextlib import asynccontextmanager
import shutil
from pathlib import Path

import pymupdf
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from engine.options import LABELS, Options

from . import backup_api, config, db, files, worker

HERE = Path(__file__).parent
config.check()

@asynccontextmanager
async def lifespan(_app):
    db.connect()
    config.FILES_DIR.mkdir(parents=True, exist_ok=True)
    worker.start()
    yield


app = FastAPI(title="PDF 轉 Word", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET or "local-dev-only",
    max_age=config.SESSION_DAYS * 24 * 3600,
    https_only=config.ON_RAILWAY,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

oauth = OAuth()
oauth.register(
    name="google",
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# ── Sign-in (FR1) ─────────────────────────────────────────────────────────

def current_user(request: Request) -> str | None:
    if config.AUTH_DISABLED:
        return "local@dev"
    email = request.session.get("email")
    return email if email and email == config.ALLOWED_EMAIL else None


def require_user(request: Request) -> str:
    email = current_user(request)
    if not email:
        raise HTTPException(status_code=401, detail="請先登入。")
    return email


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/")
    return templates.TemplateResponse(request, "login.html", {})


@app.get("/auth/google")
async def auth_google(request: Request):
    redirect_uri = (config.APP_BASE_URL or str(request.base_url).rstrip("/")) + "/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse("/login")
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not info.get("email_verified") or email != config.ALLOWED_EMAIL:
        request.session.clear()
        return templates.TemplateResponse(request, "denied.html", {"email": email}, status_code=403)
    request.session["email"] = email
    return RedirectResponse("/")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


# ── Pages ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not current_user(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "index.html", {
        "labels": LABELS, "max_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024), "max_pages": config.MAX_PAGES,
    })


@app.get("/library", response_class=HTMLResponse)
def library(request: Request):
    if not current_user(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "library.html", {"backup": backup_api.enabled()})


@app.get("/health")
def health():
    return {"status": "ok" if worker.alive() else "degraded", "worker": worker.alive()}


# ── API ───────────────────────────────────────────────────────────────────

def _public(job: dict) -> dict:
    opts = Options.from_dict(job["settings"]) if job["settings"] else None
    return {
        **job,
        "settings_label": opts.label() if opts else None,
        "has_result": files.result(job["id"]).exists(),
        "has_api_result": files.api_result(job["id"]).exists(),
    }


@app.get("/api/jobs")
def list_jobs(_: str = Depends(require_user)):
    return {"jobs": [_public(j) for j in db.list_all()], "backup": backup_api.enabled()}


@app.get("/api/storage")
def storage(_: str = Depends(require_user)):
    usage = shutil.disk_usage(config.DATA_DIR)
    used = sum(p.stat().st_size for p in config.FILES_DIR.rglob("*") if p.is_file())
    return {"used_bytes": used, "free_bytes": usage.free, "total_bytes": usage.total}


@app.get("/api/settings/last")
def last_settings(_: str = Depends(require_user)):
    return db.kv_get("last_settings", Options().to_dict())


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), _: str = Depends(require_user)):
    name = Path(file.filename or "document.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "只接受 PDF 檔案。")
    job = db.create(name, None, 0, status="uploading")
    dest = files.source(job["id"])
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with open(dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"檔案超過 {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB 上限。")
                out.write(chunk)
        try:
            doc = pymupdf.open(dest)
        except Exception:
            raise HTTPException(400, "檔案不是有效的 PDF，或已損毀。")
        if not doc.is_pdf:
            raise HTTPException(400, "檔案不是 PDF。")
        locked = doc.needs_pass
        pages = doc.page_count
        doc.close()
        if not locked and pages > config.MAX_PAGES:
            raise HTTPException(413, f"檔案有 {pages} 頁，超過 {config.MAX_PAGES} 頁上限。")
    except HTTPException:
        files.remove(job["id"])
        db.delete(job["id"])
        raise
    except OSError as exc:
        files.remove(job["id"])
        db.delete(job["id"])
        if exc.errno == errno.ENOSPC:
            raise HTTPException(507, "儲存空間已滿，請先在檔案庫刪除一些檔案。")
        raise
    db.update(job["id"], size_bytes=size, pages=None if locked else pages,
              status="needs_password" if locked else "uploaded")
    return _public(db.get(job["id"]))


class StartBody(BaseModel):
    choices: list[str] = ["auto"]
    furigana: str = "brackets"


def _job_or_404(job_id: str) -> dict:
    job = db.get(job_id)
    if not job:
        raise HTTPException(404, "找不到這個檔案。")
    return job


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: str, body: StartBody, _: str = Depends(require_user)):
    job = _job_or_404(job_id)
    opts = Options.from_dict(body.model_dump())
    db.kv_set("last_settings", opts.to_dict())
    if job["status"] == "paused":
        # Resume with the settings the finished pages were made with.
        db.set_status_if(job_id, ("paused",), status="queued")
    elif job["status"] in ("uploaded", "stopped", "failed"):
        files.clear_work(job_id)
        db.set_status_if(job_id, ("uploaded", "stopped", "failed"), status="queued", settings=opts.to_dict(),
                         progress_page=0, error=None, warnings=None)
    else:
        raise HTTPException(409, "這個檔案目前無法開始。")
    worker.wake()
    return _public(db.get(job_id))


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str, _: str = Depends(require_user)):
    _job_or_404(job_id)
    if not db.set_status_if(job_id, ("queued", "converting"), status="paused"):
        raise HTTPException(409, "這個檔案目前無法暫停。")
    return _public(db.get(job_id))


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str, _: str = Depends(require_user)):
    job = _job_or_404(job_id)
    if not db.set_status_if(job_id, ("queued", "converting", "paused"), status="stopped", progress_page=0):
        raise HTTPException(409, "這個檔案目前無法停止。")
    if job["status"] != "converting":
        files.clear_work(job_id)  # a running job clears its own work when it stops
    return _public(db.get(job_id))


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, _: str = Depends(require_user)):
    """Back to the settings panel, so the owner can change the choices (D13)."""
    _job_or_404(job_id)
    if not db.set_status_if(job_id, ("done", "failed", "stopped"), status="uploaded", progress_page=0,
                            error=None, warnings=None, finished_at=None):
        raise HTTPException(409, "這個檔案目前無法重試。")
    files.clear_work(job_id)
    return _public(db.get(job_id))


class PasswordBody(BaseModel):
    password: str


@app.post("/api/jobs/{job_id}/password")
def unlock_job(job_id: str, body: PasswordBody, _: str = Depends(require_user)):
    job = _job_or_404(job_id)
    if job["status"] != "needs_password":
        raise HTTPException(409, "這個檔案不需要密碼。")
    doc = pymupdf.open(files.source(job_id))
    ok = doc.authenticate(body.password)
    pages = doc.page_count
    doc.close()
    if not ok:
        raise HTTPException(400, "密碼不正確。")
    if pages > config.MAX_PAGES:
        raise HTTPException(413, f"檔案有 {pages} 頁，超過 {config.MAX_PAGES} 頁上限。")
    worker.passwords[job_id] = body.password  # memory only, never written to disk
    previous = "queued" if job["settings"] else "uploaded"
    db.update(job_id, status=previous, pages=pages)
    worker.wake()
    return _public(db.get(job_id))


def _delete(job_id: str) -> None:
    db.delete(job_id)
    worker.passwords.pop(job_id, None)
    files.remove(job_id)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, _: str = Depends(require_user)):
    _job_or_404(job_id)
    _delete(job_id)
    return {"ok": True}


class DeleteBody(BaseModel):
    ids: list[str]


@app.post("/api/jobs/delete")
def delete_many(body: DeleteBody, _: str = Depends(require_user)):
    for job_id in body.ids:
        if db.get(job_id):
            _delete(job_id)
    return {"ok": True}


@app.post("/api/jobs/delete-all")
def delete_all(_: str = Depends(require_user)):
    for job in db.list_all():
        _delete(job["id"])
    return {"ok": True}


@app.post("/api/jobs/{job_id}/backup")
def backup(job_id: str, _: str = Depends(require_user)):
    job = _job_or_404(job_id)
    if not backup_api.enabled():
        raise HTTPException(400, "尚未設定商業服務的 API 金鑰（CONVERT_API_KEY）。")
    if job["status"] == "needs_password":
        raise HTTPException(409, "請先輸入 PDF 密碼。")
    if job["api_status"] == "converting":
        raise HTTPException(409, "商業服務正在轉換中。")
    backup_api.start(job_id)
    return _public(db.get(job_id))


@app.get("/api/download/{job_id}/{kind}")
def download(job_id: str, kind: str, _: str = Depends(require_user)):
    job = _job_or_404(job_id)
    stem = Path(job["file_name"]).stem
    if kind == "docx":
        path, name = files.result(job_id), f"{stem}.docx"
    elif kind == "api":
        path, name = files.api_result(job_id), f"{stem}_商業服務.docx"
    elif kind == "pdf":
        path, name = files.source(job_id), job["file_name"]
    else:
        raise HTTPException(404, "找不到檔案。")
    if not path.exists():
        raise HTTPException(404, "找不到檔案。")
    return FileResponse(path, filename=name)


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    if exc.status_code == 401 and not request.url.path.startswith("/api/"):
        return RedirectResponse("/login")
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


