"""Runtime configuration for Trade Memory."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
# Prefer 30B if set in .env; Nano-9B is the safe default when unset.
DEFAULT_MODEL = "nvidia/NVIDIA-Nemotron-Nano-9B-v2"
PREFERRED_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MEMORY_PATH = DATA_DIR / "memory.json"


@lru_cache
def get_settings() -> dict:
    api_key = (os.getenv("NEBIUS_API_KEY") or "").strip()
    model = (os.getenv("NEBIUS_MODEL") or "").strip() or DEFAULT_MODEL
    return {
        "api_key": api_key,
        "base_url": (os.getenv("NEBIUS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        "model": model,
        "dry_run": not bool(api_key),
        "memory_path": str(MEMORY_PATH),
    }
