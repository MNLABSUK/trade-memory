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
    """Primary provider first (Nightshift), then Nebius; dry-run when none."""
    from trade_memory.llm import configured_providers

    providers = configured_providers()
    primary = providers[0] if providers else None
    return {
        "providers": providers,
        "provider": primary.name if primary else "dry-run",
        "base_url": primary.base_url if primary else "",
        "model": primary.model if primary else ((os.getenv("NIGHTSHIFT_MODEL") or "").strip() or "dry-run"),
        "dry_run": primary is None,
        "memory_path": str(MEMORY_PATH),
    }
