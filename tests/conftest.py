"""Hermetic tests: never call a real LLM, never touch the real H-MEM store."""

import os
import tempfile

# Must run before trade_memory.config imports (load_dotenv won't override set vars).
os.environ["TRADE_MEMORY_DRY_RUN"] = "1"
os.environ.setdefault("HMEM_DIR", tempfile.mkdtemp(prefix="hmem-test-"))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _dry_run_settings():
    from trade_memory.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
