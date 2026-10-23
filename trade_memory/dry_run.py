"""Deterministic next-action proposals when no Nebius key."""

from __future__ import annotations

import re
from typing import Any

from trade_memory.models import Chase, Client, Job, ProposeResult

SIGN_OFF = "Tom Rook, Halden & Rook Electrical"


def _note_text(n: Any) -> str:
    return getattr(n, "text", n.get("text", "") if isinstance(n, dict) else str(n))


def _preferred_contact(client: Client | None, notes: list[Any] | None) -> str:
    """Use client.contact; if bounce noted, prefer accounts@ / note-specified address."""
    contact = (client.contact if client else "") or ""
    blob = " ".join(_note_text(n) for n in (notes or [])).lower()
    hist_blob = ""
    # Prefer explicit emails mentioned alongside bounce / prefer
    emails = re.findall(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", blob)
    if "bounce" in blob or "bounced" in blob or "do not use" in blob:
        for em in emails:
            if em != contact.lower() or "accounts@" in em:
                # Prefer accounts@ style
                if "accounts@" in em:
                    return em
        for em in emails:
            if "owner@" not in em:
                return em
        if contact:
            return contact
        if emails:
            return emails[0]
    return contact


def propose(
    chase: Chase,
    client: Client | None = None,
    *,
    job: Job | None = None,
    notes: list[Any] | None = None,
    decisions: list[Any] | None = None,
    recall_summary: str = "",
    history: list[str] | None = None,
) -> ProposeResult:
    name = client.name if client else chase.client_id
    contact = _preferred_contact(client, notes)
    amt = f"£{chase.amount:.2f}" if chase.amount is not None else "the balance"
    addr = (job.address if job else "") or ""
    text = f"{chase.summary} {chase.invoice_ref} {chase.last_action} {' '.join(history or [])}".lower()
    note_blob = " ".join(_note_text(n) for n in (notes or [])).lower()
    prior = ""
    if decisions:
        last = decisions[0]
        d_dec = getattr(last, "decision", None) or (last.get("decision") if isinstance(last, dict) else "")
        d_note = getattr(last, "note", None) or (last.get("note") if isinstance(last, dict) else "")
        prior = f" Prior decision on file: {d_dec}" + (f" ({d_note})" if d_note else "") + "."

    mem_hint = ""
    if recall_summary:
        mem_hint = f"\n\n[Memory] {recall_summary[:220]}"

    bounced = "bounce" in note_blob or "bounced" in note_blob or "bounce" in text
    if bounced and contact:
        contact_line = f"Send to {contact} (prior bounce — use this contact)."
    elif contact:
        contact_line = f"Send to {contact}."
    else:
        contact_line = "Confirm the right finance / site contact before send."

    site_line = f"\nJob site: {addr}." if addr else ""
    whatsapp = (
        f"Hi — gentle chase on {chase.invoice_ref or 'your invoice'} ({amt})"
        f"{', ' + addr if addr else ''}. Can you confirm remittance or the right finance contact? — {SIGN_OFF}"
    )

    if chase.days_overdue >= 14 or "overdue" in text or (
        chase.invoice_ref.startswith("INV") and chase.days_overdue > 0
    ):
        urgency = "critical" if chase.days_overdue >= 30 else "high"
        draft = (
            f"Hi {name},\n\n"
            f"Friendly chase on {chase.invoice_ref or 'your invoice'} for {amt}. "
            f"It looks about {chase.days_overdue} day(s) overdue.{site_line}\n"
            f"{contact_line}\n\n"
            "Could you confirm remittance advice or the right finance contact?\n\n"
            f"Thanks,\n{SIGN_OFF}\n"
            "(Human must Approve before send.)\n\n"
            f"WhatsApp-ready:\n{whatsapp}"
            f"{mem_hint}"
        )
        return ProposeResult(
            chase_id=chase.id,
            summary=f"Overdue chase for {name} — {chase.invoice_ref or 'invoice'} {amt}.{prior}",
            draft_action=draft.strip(),
            urgency=urgency,
            needs_human=True,
            source="dry-run",
        )

    if "invoice" in text or "ready to" in text or chase.invoice_ref == "INV-next":
        labour = ""
        if job and job.notes:
            labour = " Notes: " + "; ".join(job.notes[:2]) + "."
        draft = (
            f"Hi {name},\n\n"
            f"Draft invoice ready for {amt}.{site_line}{labour}\n"
            f"{contact_line}\n\n"
            f"Please Approve before we send.\n\n"
            f"Thanks,\n{SIGN_OFF}"
            f"{mem_hint}"
        )
        return ProposeResult(
            chase_id=chase.id,
            summary=f"Job complete — raise invoice for {name} ({amt}).{prior}",
            draft_action=draft.strip(),
            urgency="high",
            needs_human=True,
            source="dry-run",
        )

    if "quote" in text or "ballpark" in text:
        draft = (
            f"Hi {name},\n\n"
            f"Ballpark for the electrical works (supply + install)."
            f"{site_line}\n"
            "Happy to refine once we confirm the scope on site.\n\n"
            f"Thanks,\n{SIGN_OFF}\n"
            "(Hold for human Approve before sending.)"
            f"{mem_hint}"
        )
        return ProposeResult(
            chase_id=chase.id,
            summary=f"Quote request from {name} — draft ballpark.{prior}",
            draft_action=draft.strip(),
            urgency="medium",
            needs_human=True,
            source="dry-run",
        )

    if "call-out" in text or "offline" in text or "fault" in text:
        draft = (
            f"Hi {name},\n\n"
            f"Confirming tomorrow morning call-out slot.{site_line}\n"
            f"{contact_line}\n\n"
            f"Thanks,\n{SIGN_OFF}\n"
            "(Human Approve before send.)"
            f"{mem_hint}"
        )
        return ProposeResult(
            chase_id=chase.id,
            summary=f"Urgent call-out for {name}.{prior}",
            draft_action=draft.strip(),
            urgency="high",
            needs_human=True,
            source="dry-run",
        )

    return ProposeResult(
        chase_id=chase.id,
        summary=(chase.summary or f"Review chase {chase.id}") + prior,
        draft_action=(
            f"Hi {name},\n\n"
            f"Re: {chase.summary or chase.id}.{site_line}\n"
            f"{contact_line}\n\n"
            f"Edit this draft, then Approve / Leave it / Later.\n\n"
            f"Thanks,\n{SIGN_OFF}"
            f"{mem_hint}"
        ).strip(),
        urgency="medium",
        needs_human=True,
        source="dry-run",
    )
