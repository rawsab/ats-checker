import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import make_fixtures


@pytest.fixture(scope="session")
def pdfs(tmp_path_factory) -> dict[str, Path]:
    return make_fixtures.build(tmp_path_factory.mktemp("pdfs"))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ATS_CHECKER_HOME", str(tmp_path / "home"))
