import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import make_samples  # noqa: E402


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    if not shutil.which("soffice"):
        pytest.skip("LibreOffice (soffice) is needed to build the sample PDFs")
    return make_samples.build(tmp_path_factory.mktemp("samples"))
