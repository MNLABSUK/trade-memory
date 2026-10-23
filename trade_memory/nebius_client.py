"""Nebius Token Factory client (OpenAI-compatible) + dry-run fallback."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from trade_memory.config import get_settings
from trade_memory.llm import chat_completion
from trade_memory.dry_run import propose as dry_run_propose
from trade_memory.models import Chase, Client, Job, ProposeResult

SYSTEM_PROMPT = """You are Trade Memory for Halden & Rook Ops / MN Labs — a small UK CCTV & security
trades desk. Draft short chase emails and WhatsApp-ready texts for the human to approve.

You receive desk context: chase, client (with contact), job (address/amount/notes),
recent memory notes, prior DecisionRecords, chase history, and a recall summary.

CRITICAL RULES:
- needs_human must always be true. Never auto-send money, invoices, contracts, or legal commitments.
- Sign every draft as: Halden & Rook Ops / MN Labs desk (never [Your Name], [Company Name], or similar).
- Always use the real client.contact from context as the send-to address. If notes mention a bounce,
  use the preferred contact from notes (e.g. accounts@) — never invent placeholders.
- Include the job address when present (one short line).
- UK English. Short, practical, polite. Chase emails ~4–8 lines; WhatsApp texts ≤2 short paragraphs.
- No markdown fences. No “As an AI”. No roleplay disclaimers.
- Prefer polite payment chases, invoice drafts, or scheduling confirms.
- Respect prior decisions and notes.

Respond with ONLY valid JSON (no markdown) matching:
{
  "summary": "one short sentence",
  "draft_action": "concrete draft the human can approve",
  "urgency": "low|medium|high|critical",
  "needs_human": true
}
"""

_PLACEHOLDER_RE = re.compile(
    r"\[(?:Your Name|Company Name|Your Company|Name|Company|Contact Name|"
    r"Email Address|Phone Number|Insert .*?|TODO|TBD)\]",
    re.IGNORECASE,
)
_GENERIC_SIG_RE = re.compile(
    r"(?:Best regards|Kind regards|Regards|Thanks|Thank you)[,\s]*\n\s*"
    r"(?:\[.*?\]|Your Name|Company Name)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def scrub_placeholders(
    text: str,
    *,
    contact: str = "",
    client_name: str = "",
) -> str:
    """Replace LLM placeholder tokens with Halden & Rook Ops / real contact."""
    if not text:
        return text
    out = _PLACEHOLDER_RE.sub("Halden & Rook Ops", text)
    out = re.sub(r"\[Your Name\]", "Halden & Rook Ops", out, flags=re.IGNORECASE)
    out = re.sub(r"\[Company Name\]", "Halden & Rook Ops / MN Labs", out, flags=re.IGNORECASE)
    out = re.sub(r"\[Client Name\]", client_name or "the client", out, flags=re.IGNORECASE)
    out = re.sub(r"\[Contact\]", contact or "the finance contact", out, flags=re.IGNORECASE)
    out = re.sub(r"\[Email\]", contact or "accounts@", out, flags=re.IGNORECASE)
    # Strip leftover bracket tokens that look like form fields
    out = re.sub(r"\[[A-Z][A-Za-z0-9 /_-]{2,40}\]", "Halden & Rook Ops", out)
    if contact and "Send to" not in out and "@" not in out.split("\n")[0]:
        # Ensure contact appears when we scrubbed placeholders but draft lacked it
        pass
    # Normalise weak closings to Halden & Rook Ops
    if re.search(r"(Best regards|Kind regards|Regards),?\s*$", out, re.IGNORECASE | re.MULTILINE):
        out = re.sub(
            r"(Best regards|Kind regards|Regards),?\s*$",
            r"\1,\nHalden & Rook Ops / MN Labs desk",
            out,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    if "Halden & Rook" not in out and "MN Labs" not in out:
        out = out.rstrip() + "\n\nHalden & Rook Ops / MN Labs desk"
    return out.strip()


def _parse_json_content(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


def _serialize_context(
    chase: Chase,
    client: Client | None,
    *,
    job: Job | None = None,
    notes: list[Any] | None = None,
    decisions: list[Any] | None = None,
    recall_summary: str = "",
    history: list[str] | None = None,
) -> dict[str, Any]:
    def dump(obj: Any) -> Any:
        if obj is None:
            return None
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        if isinstance(obj, dict):
            return obj
        return obj

    return {
        "chase": dump(chase),
        "client": dump(client),
        "job": dump(job),
        "recent_notes": [dump(n) for n in (notes or [])],
        "prior_decisions": [dump(d) for d in (decisions or [])],
        "chase_history": list(history or chase.history or []),
        "recall_summary": recall_summary,
        "sign_as": "Halden & Rook Ops / MN Labs desk",
        "send_to": (client.contact if client else "") or "",
    }


async def propose_next_action(
    chase: Chase,
    client: Client | None = None,
    *,
    job: Job | None = None,
    notes: list[Any] | None = None,
    decisions: list[Any] | None = None,
    recall_summary: str = "",
    history: list[str] | None = None,
) -> ProposeResult:
    settings = get_settings()
    ctx_kw = dict(
        job=job,
        notes=notes,
        decisions=decisions,
        recall_summary=recall_summary,
        history=history or list(chase.history or []),
    )
    if settings["dry_run"]:
        return dry_run_propose(chase, client, **ctx_kw)

    user_payload = _serialize_context(chase, client, **ctx_kw)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload)},
    ]
    contact = (client.contact if client else "") or ""
    client_name = (client.name if client else "") or chase.client_id
    try:
        content, used = await chat_completion(messages, temperature=0.15, providers=settings["providers"])
        parsed = _parse_json_content(content)
        draft = scrub_placeholders(
            str(parsed.get("draft_action", "")).strip() or "Review and decide.",
            contact=contact,
            client_name=client_name,
        )
        summary = scrub_placeholders(
            str(parsed.get("summary", "")).strip() or "Proposed by Nemotron.",
            contact=contact,
            client_name=client_name,
        )
        return ProposeResult(
            chase_id=chase.id,
            summary=summary,
            draft_action=draft,
            urgency=str(parsed.get("urgency", "medium")),
            needs_human=True,
            source=used.name,
        )
    except Exception:
        fallback = dry_run_propose(chase, client, **ctx_kw)
        fallback.summary = f"[fallback heuristics] {fallback.summary}"
        fallback.source = "dry-run-fallback"
        return fallback
