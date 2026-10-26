# Presence of this file puts the repo root on sys.path for the tests.
# The tmp_path override below works around the Windows sandbox: pytest's
# built-in tmp dirs are created with mode 0o700, which the sandbox token
# cannot read back, so tests using tmp_path error out before they run.
import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path():
    base = Path(__file__).resolve().parent / ".tmp-test-work"
    base.mkdir(exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir()
    yield path
    shutil.rmtree(path, ignore_errors=True)
