"""Provider layer: Meterless Nightshift first (Nemotron via the Meterless
Runtime's OpenAI-compatible endpoint), Nebius Token Factory as fallback,
deterministic dry-run when neither is configured.

Nightshift contract (Meterless Runtime provider contract v4, meterless.ai/engines.html):
  * base URL default http://127.0.0.1:8088/v1 (OpenAI-compatible)
  * Authorization: Bearer <token>  (runtime writes it to <stateDir>/proxy-token;
    the placeholder "rt-local" is rejected by the runtime)
  * headers meterless-app: <app id>, meterless-scope: user on chat
  * model ids are routing modes (meterless/auto|fast|deep|cheap|local|fusion) or
    any id listed by GET /v1/models, e.g. an installed Nemotron model
  * 180 s timeout (model loads can take minutes)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

NIGHTSHIFT_DEFAULT_BASE_URL = "http://127.0.0.1:8088/v1"
NIGHTSHIFT_DEFAULT_MODEL = "meterless/auto"
NEBIUS_DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
NEBIUS_DEFAULT_MODEL = "nvidia/NVIDIA-Nemotron-Nano-9B-v2"


@dataclass
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    timeout: float = 60.0
    extra_headers: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:  # never leak the key
        return f"Provider(name={self.name!r}, base_url={self.base_url!r}, model={self.model!r})"

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }


def normalize_base_url(url: str) -> str:
    """Accept host, host:port, .../v1, .../v1/chat/completions, /v1/models, /healthz."""
    u = (url or "").strip()
    if not u:
        return u
    if "://" not in u:
        u = "http://" + u
    u = u.rstrip("/")
    for suffix in ("/chat/completions", "/models", "/healthz"):
        if u.endswith(suffix):
            u = u[: -len(suffix)]
    u = u.rstrip("/")
    if not u.endswith("/v1"):
        u += "/v1"
    return u


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _nightshift_token() -> str:
    tok = _env("NIGHTSHIFT_API_KEY")
    if not tok:
        path = _env("NIGHTSHIFT_TOKEN_FILE")
        if path and Path(path).expanduser().is_file():
            tok = Path(path).expanduser().read_text().strip()
    return "" if tok == "rt-local" else tok


def configured_providers() -> list[Provider]:
    """Ordered list: Nightshift (primary), Nebius (fallback). Empty => dry-run."""
    if _env("TRADE_MEMORY_DRY_RUN").lower() in ("1", "true", "yes"):
        return []
    out: list[Provider] = []
    ns_key = _nightshift_token()
    if ns_key:
        out.append(
            Provider(
                name="nightshift",
                base_url=normalize_base_url(_env("NIGHTSHIFT_BASE_URL") or NIGHTSHIFT_DEFAULT_BASE_URL),
                api_key=ns_key,
                model=_env("NIGHTSHIFT_MODEL") or NIGHTSHIFT_DEFAULT_MODEL,
                timeout=180.0,
                extra_headers={
                    "meterless-app": _env("NIGHTSHIFT_APP") or "trade-memory",
                    "meterless-scope": "user",
                },
            )
        )
    nb_key = _env("NEBIUS_API_KEY")
    if nb_key:
        out.append(
            Provider(
                name="nebius",
                base_url=(_env("NEBIUS_BASE_URL") or NEBIUS_DEFAULT_BASE_URL).rstrip("/"),
                api_key=nb_key,
                model=_env("NEBIUS_MODEL") or NEBIUS_DEFAULT_MODEL,
            )
        )
    return out


class LLMUnavailable(RuntimeError):
    pass


async def chat_completion(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.15,
    providers: list[Provider] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, Provider]:
    """Try each provider in order; return (content, provider_used)."""
    providers = configured_providers() if providers is None else providers
    if not providers:
        raise LLMUnavailable("no provider configured (dry-run)")
    errors: list[str] = []
    for p in providers:
        body = {"model": p.model, "temperature": temperature, "messages": messages}
        try:
            async with httpx.AsyncClient(timeout=p.timeout, transport=transport) as http:
                resp = await http.post(f"{p.base_url}/chat/completions", headers=p.headers(), json=body)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
            return content, p
        except Exception as exc:  # fall through to next provider
            errors.append(f"{p.name}: {type(exc).__name__}")
    raise LLMUnavailable("; ".join(errors))
