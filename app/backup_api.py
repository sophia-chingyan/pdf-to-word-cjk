"""Backup conversion through ConvertAPI (spec FR6). Runs only when the owner
presses the button, and only when CONVERT_API_KEY is set."""

from __future__ import annotations

import base64
import threading

import httpx

from . import config, db, files

ENDPOINT = "https://v2.convertapi.com/convert/pdf/to/docx"


def enabled() -> bool:
    return bool(config.CONVERT_API_KEY)


def _convert(job_id: str) -> None:
    try:
        with open(files.source(job_id), "rb") as fh:
            resp = httpx.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {config.CONVERT_API_KEY}"},
                files={"File": ("source.pdf", fh, "application/pdf")},
                data={"StoreFile": "false"},
                timeout=600,
            )
        if resp.status_code != 200:
            try:
                detail = resp.json().get("Message") or resp.text
            except ValueError:
                detail = resp.text
            raise RuntimeError(f"ConvertAPI {resp.status_code}: {detail[:300]}")
        data = resp.json()["Files"][0]["FileData"]
        files.api_result(job_id).write_bytes(base64.b64decode(data))
        db.update(job_id, api_status="done", api_error=None)
    except Exception as exc:
        db.update(job_id, api_status="failed", api_error=str(exc)[:500])


def start(job_id: str) -> None:
    db.update(job_id, api_status="converting", api_error=None)
    threading.Thread(target=_convert, args=(job_id,), name=f"api-{job_id}", daemon=True).start()
