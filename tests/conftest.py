import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etsy_engine.config import load_config  # noqa: E402
from etsy_engine.db import Database  # noqa: E402


@pytest.fixture
def demo_cfg(tmp_path):
    return load_config(demo=True, root=tmp_path)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    for key in ("ETSY_API_KEY", "PINTEREST_APP_ID", "GEMINI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    c = load_config(root=tmp_path)
    c.data["site"]["base_url"] = "https://example.github.io/pins"
    return c


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    yield d
    d.close()
