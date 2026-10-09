"""Background worker: converts one queued job at a time (spec FR3)."""

from __future__ import annotations

import logging
import threading
import time

from engine.convert import ConversionError, convert
from engine.options import Options

from . import db, files

log = logging.getLogger("worker")

# Passwords for protected PDFs, kept in memory only until the job ends.
passwords: dict[str, str] = {}
_wake = threading.Event()
_thread: threading.Thread | None = None


def wake() -> None:
    _wake.set()


def _run(job: dict) -> None:
    job_id = job["id"]
    options = Options.from_dict(job["settings"])

    def progress(done: int, total: int) -> None:
        db.update(job_id, progress_page=done, pages=total)

    def should_stop() -> bool:
        current = db.get(job_id)
        return current is None or current["status"] != "converting"

    try:
        summary = convert(files.source(job_id), files.result(job_id), options, files.workdir(job_id),
                          password=passwords.get(job_id), progress=progress, should_stop=should_stop)
    except InterruptedError:
        current = db.get(job_id)
        if current and current["status"] == "stopped":
            files.clear_work(job_id)
        return
    except ConversionError as exc:
        if str(exc) == "needs_password":
            passwords.pop(job_id, None)
            db.set_status_if(job_id, ("converting",), status="needs_password")
        else:
            db.set_status_if(job_id, ("converting",), status="failed", error=str(exc), finished_at=time.time())
        return
    except Exception as exc:  # keep the worker alive; show the error on the job
        log.exception("conversion %s failed", job_id)
        db.set_status_if(job_id, ("converting",), status="failed", error=f"轉換失敗：{exc}",
                         finished_at=time.time())
        return
    passwords.pop(job_id, None)
    db.set_status_if(job_id, ("converting",), status="done", error=None, finished_at=time.time(),
                     warnings=summary["warnings"], languages=summary["languages"],
                     directions=summary["directions"])


def _loop() -> None:
    while True:
        job = db.next_queued()
        if job is None:
            _wake.wait(timeout=5)
            _wake.clear()
            continue
        if db.set_status_if(job["id"], ("queued",), status="converting", error=None):
            _run(db.get(job["id"]) or job)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    db.requeue_interrupted()
    _thread = threading.Thread(target=_loop, name="worker", daemon=True)
    _thread.start()


def alive() -> bool:
    return bool(_thread and _thread.is_alive())
