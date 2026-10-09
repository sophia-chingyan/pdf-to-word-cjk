"""Where each conversion's files live on the volume."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import config


def job_dir(job_id: str) -> Path:
    return config.FILES_DIR / job_id


def source(job_id: str) -> Path:
    return job_dir(job_id) / "source.pdf"


def result(job_id: str) -> Path:
    return job_dir(job_id) / "result.docx"


def api_result(job_id: str) -> Path:
    return job_dir(job_id) / "result_api.docx"


def workdir(job_id: str) -> Path:
    return job_dir(job_id) / "work"


def clear_work(job_id: str) -> None:
    shutil.rmtree(workdir(job_id), ignore_errors=True)
    result(job_id).unlink(missing_ok=True)


def remove(job_id: str) -> None:
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
