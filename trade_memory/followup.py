"""Follow-up chat: dry-run rules + optional Nebius JSON answers."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from trade_memory.config import get_settings
from trade_memory.memory import MemoryStore
from trade_memory.nebius_client import _parse_json_content

FOLLOWUP_SYSTEM = """You are Trade Memory desk chat for a UK trades contractor.
Answer briefly from the provided memory JSON. You may suggest focusing a chase
or returning a draft email. Never claim you sent anything.
Respond ONLY with JSON:
{
  "reply": "short answer for the human",
  "focus_chase_id": "ch-xxx or null",
  "draft": "optional draft text or null",
  "kind": "answer|overdue|who|draft|recall"
}
"""


def _find_client_by_name(store: MemoryStore, text: str):
    low = text.lower()
    # Longer / more specific names first
    clients = sorted(store.list_clients(), key=lambda c: len(c.name), reverse=True)
    for c in clients:
        if c.name.lower() in low:
            return c
    for c in clients:
        first = c.name.lower().split()[0]
        if len(first) > 2 and first in low:
            return c
    return None


def _open_chase_for_client(store: MemoryStore, client_id: str):
    open_hit = None
    any_hit = None
    for ch in store.list_chases(open_only=False):
        if ch.client_id != client_id:
            continue
        any_hit = ch
        if ch.status in ("open", "waiting", "later"):
            open_hit = ch
            break
    return open_hit or any_hit


def _dry_followup(store: MemoryStore, message: str, chase_id: str | None = None) -> dict[str, Any]:
    msg = (message or "").strip()
    low = msg.lower()
    recall = store.recall(msg)
    focus = recall.get("focus")
    focus_id = (focus or {}).get("id") if focus else chase_id

    # overdue
    if any(k in low for k in ("overdue", "past due", "what's late", "whats late", "late invoices", "what's overdue", "whats overdue")):
        open_c = store.list_chases(open_only=True)
        overdue = [c for c in open_c if (c.days_overdue or 0) > 0]
        if not overdue:
            return {
                "reply": "Nothing overdue in open chases right now.",
                "focus_chase_id": focus_id,
                "draft": None,
                "kind": "overdue",
                "source": "dry-run",
                "recall": recall,
            }
        lines = [
            f"• {c.id} {c.invoice_ref or ''} — £{c.amount or 0:.0f}, {c.days_overdue}d "
            f"({(store.get_client(c.client_id).name if store.get_client(c.client_id) else c.client_id)})"
            for c in overdue[:6]
        ]
        top = overdue[0]
        return {
            "reply": f"Overdue ({len(overdue)}):\n" + "\n".join(lines),
            "focus_chase_id": top.id,
            "draft": None,
            "kind": "overdue",
            "source": "dry-run",
            "recall": recall,
        }

    # draft chase for X — before who, so "draft … Kestrel" is not treated as who
    draft_m = re.search(r"draft\s+(?:a\s+)?(?:chase|email|invoice|quote)\s+(?:for\s+)?(.+)", low)
    if draft_m or ("draft" in low and any(x in low for x in ("larkfield", "brindle", "kestrel", "mosswood", "copperbeech"))):
        client = _find_client_by_name(store, draft_m.group(1) if draft_m else msg)
        ch_obj = _open_chase_for_client(store, client.id) if client else None
        ch = ch_obj.model_dump(mode="json") if ch_obj else (recall.get("focus") or None)
        if ch:
            client = client or store.get_client(ch.get("client_id", ""))
            name = client.name if client else ch.get("client_id", "client")
            amt = ch.get("amount")
            amt_s = f"£{amt:.2f}" if isinstance(amt, (int, float)) else "the balance"
            draft = (
                f"Hi {name},\n\n"
                f"Following up on {ch.get('invoice_ref') or 'the open item'} for {amt_s}. "
                f"{ch.get('summary') or ''}\n\n"
                "Thanks — Halden & Rook Electrical\n"
                "(Human must Approve before send.)"
            )
            target_recall = store.recall(name) if client else recall
            return {
                "reply": f"Draft ready for {name} ({ch.get('id')}). Edit on the desk, then Approve / Leave / Later.",
                "focus_chase_id": ch.get("id"),
                "draft": draft,
                "kind": "draft",
                "source": "dry-run",
                "recall": target_recall,
            }

    # who is X
    who_m = re.search(r"who\s+is\s+(.+?)[\?\.]?$", low)
    if "draft" not in low and (
        who_m
        or low.startswith("who is ")
        or any(name in low for name in ("larkfield", "brindle", "kestrel", "mosswood", "copperbeech"))
    ):
        client = _find_client_by_name(store, who_m.group(1) if who_m else msg)
        if client:
            c = client.model_dump(mode="json")
            bundle_notes = "; ".join((c.get("notes") or [])[:2])
            reply = (
                f"{c.get('name')} — {c.get('trade') or 'client'}. "
                f"Contact: {c.get('contact') or '—'}. "
                f"{bundle_notes}"
            ).strip()
            ch_obj = _open_chase_for_client(store, client.id)
            if ch_obj:
                focus_id = ch_obj.id
            return {
                "reply": reply,
                "focus_chase_id": focus_id,
                "draft": None,
                "kind": "who",
                "source": "dry-run",
                "recall": recall,
            }

    # default: recall answer
    return {
        "reply": recall.get("answer") or "I checked memory — ask about overdue, a client name, or draft a chase.",
        "focus_chase_id": focus_id,
        "draft": None,
        "kind": "recall",
        "source": "dry-run",
        "recall": recall,
    }


async def handle_followup(
    store: MemoryStore,
    message: str,
    *,
    chase_id: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if settings["dry_run"]:
        result = _dry_followup(store, message, chase_id=chase_id)
    else:
        recall = store.recall(message)
        snap = {
            "message": message,
            "chase_id": chase_id,
            "recall": {
                "answer": recall.get("answer"),
                "focus": recall.get("focus"),
                "matched_clients": recall.get("matched_clients"),
                "matched_chases": recall.get("matched_chases"),
            },
            "stats": store.stats(),
            "open_chases": [
                c.model_dump(mode="json") for c in store.list_chases(open_only=True)[:8]
            ],
            "clients": [c.model_dump(mode="json") for c in store.list_clients()],
        }
        url = f"{settings['base_url'].rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        }
        body = {
            "model": settings["model"],
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": FOLLOWUP_SYSTEM},
                {"role": "user", "content": json.dumps(snap)},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as http:
                resp = await http.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
            parsed = _parse_json_content(data["choices"][0]["message"]["content"])
            result = {
                "reply": str(parsed.get("reply") or "").strip() or recall.get("answer"),
                "focus_chase_id": parsed.get("focus_chase_id") or (recall.get("focus") or {}).get("id"),
                "draft": parsed.get("draft"),
                "kind": parsed.get("kind") or "answer",
                "source": "nebius",
                "recall": recall,
            }
        except Exception:
            result = _dry_followup(store, message, chase_id=chase_id)
            result["source"] = "dry-run-fallback"

    # apply session focus if suggested
    fid = result.get("focus_chase_id")
    if fid:
        ch = store.get_chase(fid)
        if ch:
            pending = None
            if result.get("draft"):
                pending = {
                    "chase_id": fid,
                    "prompt": "Follow-up draft — edit then Approve / Leave / Later.",
                    "draft_text": result["draft"],
                }
                store.update_chase_draft(fid, result["draft"])
            store.touch_session(
                chase_id=fid,
                client_id=ch.client_id,
                kind="followup",
                pending=pending,
                question=message,
            )
    else:
        store.touch_session(question=message)

    store.add_activity(
        "followup",
        chase_id=fid,
        detail=(result.get("reply") or "")[:160],
        draft_text=(result.get("draft") or "")[:200],
    )
    return result
