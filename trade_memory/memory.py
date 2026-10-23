"""Persistent JSON memory store — survives process restart."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trade_memory.config import DATA_DIR, MEMORY_PATH
from trade_memory.models import (
    Chase,
    Client,
    DecisionRecord,
    Job,
    MemoryNote,
)
from trade_memory.seed import seed_payload


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _today_utc() -> str:
    return _now().date().isoformat()


class MemoryStore:
    """Thread-safe persistent memory for clients, jobs, chases, notes, decisions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else MEMORY_PATH
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self.load_or_seed()

    def load_or_seed(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = raw
        else:
            self._data = seed_payload()
            self._flush_unlocked()

    def _flush_unlocked(self) -> None:
        self._data["updated_at"] = _now_iso()
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def save(self) -> None:
        with self._lock:
            self._flush_unlocked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            chases = self._data.get("chases", [])
            open_c = [c for c in chases if c.get("status") in ("open", "waiting", "later")]
            later_c = [c for c in chases if c.get("status") == "later"]
            overdue_gbp = sum(
                float(c.get("amount") or 0) for c in open_c if int(c.get("days_overdue") or 0) > 0
            )
            today = _today_utc()
            decisions_today = 0
            for d in self._data.get("decisions", []):
                at = str(d.get("at") or "")
                if at.startswith(today):
                    decisions_today += 1
            return {
                "clients": len(self._data.get("clients", [])),
                "jobs": len(self._data.get("jobs", [])),
                "open_chases": len(open_c),
                "later_count": len(later_c),
                "notes": len(self._data.get("notes", [])),
                "decisions": len(self._data.get("decisions", [])),
                "decisions_today": decisions_today,
                "overdue_gbp": round(overdue_gbp, 2),
                "updated_at": self._data.get("updated_at"),
            }

    # --- lists ---

    def list_clients(self) -> list[Client]:
        with self._lock:
            return [Client.model_validate(c) for c in self._data.get("clients", [])]

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return [Job.model_validate(j) for j in self._data.get("jobs", [])]

    def list_chases(self, open_only: bool = False) -> list[Chase]:
        with self._lock:
            items = [Chase.model_validate(c) for c in self._data.get("chases", [])]
        if open_only:
            items = [c for c in items if c.status in ("open", "waiting", "later")]

        def rank(c: Chase) -> tuple:
            return (-(c.days_overdue or 0), -(c.amount or 0))

        return sorted(items, key=rank)

    def list_notes(self, limit: int = 50) -> list[MemoryNote]:
        with self._lock:
            notes = [MemoryNote.model_validate(n) for n in self._data.get("notes", [])]
        notes = sorted(notes, key=lambda n: n.created_at, reverse=True)
        return notes[: max(1, min(limit, 200))]

    def list_decisions(
        self,
        *,
        chase_id: str | None = None,
        client_id: str | None = None,
        limit: int = 50,
    ) -> list[DecisionRecord]:
        with self._lock:
            raw = list(self._data.get("decisions", []))
            chases_by_id = {c.get("id"): c for c in self._data.get("chases", [])}
        items = [DecisionRecord.model_validate(d) for d in raw]
        if chase_id:
            items = [d for d in items if d.chase_id == chase_id]
        if client_id:
            allowed = {
                cid
                for cid, c in chases_by_id.items()
                if c.get("client_id") == client_id
            }
            items = [d for d in items if d.chase_id in allowed]
        items = sorted(items, key=lambda d: d.at, reverse=True)
        return items[: max(1, min(limit, 100))]

    def list_activity(
        self,
        limit: int = 50,
        *,
        chase_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            acts = list(reversed(self._data.get("activity", [])))
        if chase_id:
            acts = [a for a in acts if a.get("chase_id") == chase_id]
        return deepcopy(acts[: max(1, min(limit, 100))])

    def get_chase(self, chase_id: str) -> Chase | None:
        with self._lock:
            for c in self._data.get("chases", []):
                if c.get("id") == chase_id:
                    return Chase.model_validate(c)
        return None

    def get_client(self, client_id: str) -> Client | None:
        with self._lock:
            for c in self._data.get("clients", []):
                if c.get("id") == client_id:
                    return Client.model_validate(c)
        return None

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            for j in self._data.get("jobs", []):
                if j.get("id") == job_id:
                    return Job.model_validate(j)
        return None

    def get_client_bundle(self, client_id: str) -> dict[str, Any] | None:
        client = self.get_client(client_id)
        if client is None:
            return None
        jobs = [j for j in self.list_jobs() if j.client_id == client_id]
        chases = [c for c in self.list_chases(open_only=False) if c.client_id == client_id]
        notes = [
            n
            for n in self.list_notes(limit=100)
            if n.related_client_id == client_id
            or (n.related_chase_id and any(c.id == n.related_chase_id for c in chases))
        ]
        return {
            "client": client.model_dump(mode="json"),
            "jobs": [j.model_dump(mode="json") for j in jobs],
            "chases": [c.model_dump(mode="json") for c in chases],
            "notes": [n.model_dump(mode="json") for n in notes],
            "decisions": [
                d.model_dump(mode="json")
                for d in self.list_decisions(client_id=client_id, limit=30)
            ],
        }

    def get_session(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data.get("session") or {})

    def touch_session(
        self,
        *,
        chase_id: str | None = None,
        client_id: str | None = None,
        kind: str | None = None,
        pending: dict[str, Any] | None = None,
        question: str | None = None,
    ) -> None:
        with self._lock:
            sess = self._data.setdefault("session", {})
            if chase_id is not None:
                sess["last_chase_id"] = chase_id
            if client_id is not None:
                sess["last_client_id"] = client_id
            if kind is not None:
                sess["last_kind"] = kind
            if pending is not None:
                sess["pending"] = deepcopy(pending)
            if question is not None:
                sess["last_question"] = question
            self._flush_unlocked()

    def add_note(
        self,
        text: str,
        *,
        related_client_id: str | None = None,
        related_chase_id: str | None = None,
        related_job_id: str | None = None,
    ) -> MemoryNote:
        with self._lock:
            notes = self._data.setdefault("notes", [])
            note = MemoryNote(
                id=f"note-{len(notes) + 1:04d}",
                text=text.strip(),
                related_client_id=related_client_id,
                related_chase_id=related_chase_id,
                related_job_id=related_job_id,
                created_at=_now(),
            )
            notes.append(note.model_dump(mode="json"))
            self._data.setdefault("activity", []).append(
                {
                    "id": f"act-{len(self._data['activity']) + 1:04d}",
                    "action": "note",
                    "detail": note.text[:160],
                    "chase_id": related_chase_id,
                    "at": _now_iso(),
                }
            )
            self._flush_unlocked()
            return note

    def update_chase_draft(self, chase_id: str, draft: str, summary: str | None = None) -> Chase | None:
        with self._lock:
            for c in self._data.get("chases", []):
                if c.get("id") == chase_id:
                    c["draft_action"] = draft
                    if summary:
                        c["summary"] = summary
                    self._flush_unlocked()
                    return Chase.model_validate(c)
        return None

    def record_decision(
        self,
        chase_id: str,
        decision: str,
        note: str | None = None,
        *,
        draft_text: str = "",
        snooze_until: str | None = None,
    ) -> Chase | None:
        with self._lock:
            chase_raw = None
            for c in self._data.get("chases", []):
                if c.get("id") == chase_id:
                    chase_raw = c
                    break
            if chase_raw is None:
                return None

            chase_raw["decision"] = decision
            chase_raw["decision_note"] = note
            chase_raw["decided_at"] = _now_iso()
            if draft_text:
                chase_raw["draft_action"] = draft_text
            if decision == "approve":
                chase_raw["status"] = "closed"
                chase_raw["last_action"] = f"Approved: {(draft_text or '')[:80]}"
                chase_raw["snooze_until"] = None
            elif decision == "leave":
                chase_raw["status"] = "closed"
                chase_raw["last_action"] = "Left it"
                chase_raw["snooze_until"] = None
            else:
                chase_raw["status"] = "later"
                chase_raw["last_action"] = "Parked for later"
                if snooze_until:
                    chase_raw["snooze_until"] = snooze_until

            hist = chase_raw.setdefault("history", [])
            hist.append(
                f"{_now_iso()}: decision={decision}"
                + (f" note={note}" if note else "")
                + (f" snooze={snooze_until}" if snooze_until and decision == "later" else "")
            )

            decs = self._data.setdefault("decisions", [])
            rec = DecisionRecord(
                id=f"dec-{len(decs) + 1:04d}",
                chase_id=chase_id,
                decision=decision,  # type: ignore[arg-type]
                draft_text=draft_text if decision == "approve" else "",
                note=note or "",
                snooze_until=snooze_until if decision == "later" else None,
                at=_now(),
            )
            decs.append(rec.model_dump(mode="json"))

            action_map = {"approve": "approved", "leave": "left", "later": "later"}
            self._data.setdefault("activity", []).append(
                {
                    "id": f"act-{len(self._data['activity']) + 1:04d}",
                    "action": action_map.get(decision, decision),
                    "chase_id": chase_id,
                    "detail": note or f"{decision} on {chase_id}",
                    "draft_text": draft_text if decision == "approve" else "",
                    "snooze_until": snooze_until if decision == "later" else None,
                    "at": _now_iso(),
                }
            )
            sess = self._data.setdefault("session", {})
            sess["pending"] = None
            sess["last_chase_id"] = chase_id
            self._flush_unlocked()
            return Chase.model_validate(chase_raw)

    def reopen_chase(self, chase_id: str, note: str | None = None) -> Chase | None:
        with self._lock:
            chase_raw = None
            for c in self._data.get("chases", []):
                if c.get("id") == chase_id:
                    chase_raw = c
                    break
            if chase_raw is None:
                return None
            prev = chase_raw.get("status")
            chase_raw["status"] = "open"
            chase_raw["decision"] = None
            chase_raw["decision_note"] = note
            chase_raw["decided_at"] = None
            chase_raw["snooze_until"] = None
            chase_raw["last_action"] = f"Reopened (was {prev})"
            hist = chase_raw.setdefault("history", [])
            hist.append(f"{_now_iso()}: reopened from {prev}" + (f" — {note}" if note else ""))
            self._data.setdefault("activity", []).append(
                {
                    "id": f"act-{len(self._data['activity']) + 1:04d}",
                    "action": "reopened",
                    "chase_id": chase_id,
                    "detail": note or f"Reopened {chase_id} (was {prev})",
                    "at": _now_iso(),
                }
            )
            sess = self._data.setdefault("session", {})
            sess["last_chase_id"] = chase_id
            sess["last_client_id"] = chase_raw.get("client_id")
            self._flush_unlocked()
            return Chase.model_validate(chase_raw)

    def build_propose_context(self, chase: Chase) -> dict[str, Any]:
        """Rich memory context for propose / followup."""
        client = self.get_client(chase.client_id)
        job = self.get_job(chase.job_id) if chase.job_id else None
        notes = []
        for n in self.list_notes(limit=40):
            if (
                n.related_chase_id == chase.id
                or n.related_client_id == chase.client_id
                or (chase.job_id and n.related_job_id == chase.job_id)
            ):
                notes.append(n)
            if len(notes) >= 8:
                break
        decisions = self.list_decisions(chase_id=chase.id, limit=8)
        client_decs = self.list_decisions(client_id=chase.client_id, limit=6)
        # merge unique by id, chase-first
        seen = {d.id for d in decisions}
        for d in client_decs:
            if d.id not in seen:
                decisions.append(d)
                seen.add(d.id)
        recall = self.recall("what were we chasing?")
        recall_summary = (recall.get("answer") or "")[:400]
        return {
            "chase": chase,
            "client": client,
            "job": job,
            "notes": notes,
            "decisions": decisions[:10],
            "recall_summary": recall_summary,
            "history": list(chase.history or []),
        }

    def recall(self, query: str = "") -> dict[str, Any]:
        """Broad substring recall across clients/jobs/chases/notes/invoices."""
        q = (query or "").strip().lower()
        sess = self.get_session()
        open_chases = self.list_chases(open_only=True)
        all_chases = self.list_chases(open_only=False)
        clients = self.list_clients()
        jobs = self.list_jobs()
        notes_all = self.list_notes(limit=100)

        matched_clients: list[Client] = []
        matched_jobs: list[Job] = []
        matched_chases: list[Chase] = []
        matched_notes: list[MemoryNote] = []

        if q and q not in ("what were we chasing?", "what were we chasing", "whats overdue?", "what's overdue?", "overdue"):
            for c in clients:
                blob = f"{c.id} {c.name} {c.trade} {c.contact} {' '.join(c.notes)}".lower()
                if q in blob or any(tok and tok in blob for tok in q.split() if len(tok) > 2):
                    matched_clients.append(c)
            for j in jobs:
                blob = f"{j.id} {j.title} {j.address} {j.status} {' '.join(j.notes)}".lower()
                if q in blob or any(tok and tok in blob for tok in q.split() if len(tok) > 2):
                    matched_jobs.append(j)
            for ch in all_chases:
                blob = (
                    f"{ch.id} {ch.invoice_ref} {ch.summary} {ch.last_action} "
                    f"{' '.join(ch.history or [])}"
                ).lower()
                if q in blob or any(tok and tok in blob for tok in q.split() if len(tok) > 2):
                    matched_chases.append(ch)
            for n in notes_all:
                if q in (n.text or "").lower() or any(
                    tok and tok in (n.text or "").lower() for tok in q.split() if len(tok) > 2
                ):
                    matched_notes.append(n)

        # overdue focus
        overdue_q = "overdue" in q or "past due" in q
        if overdue_q:
            matched_chases = [c for c in open_chases if (c.days_overdue or 0) > 0] or matched_chases

        last_id = sess.get("last_chase_id")
        last = self.get_chase(last_id) if last_id else None
        if last is None and open_chases:
            last = open_chases[0]

        # soft named focus (also covered by substring, but keep demo-stable)
        focus: Chase | None = None
        if matched_chases:
            # prefer open matched
            open_matched = [c for c in matched_chases if c.status in ("open", "waiting", "later")]
            focus = open_matched[0] if open_matched else matched_chases[0]
        elif matched_clients:
            cid = matched_clients[0].id
            for c in open_chases:
                if c.client_id == cid:
                    focus = c
                    break
            if focus is None:
                for c in all_chases:
                    if c.client_id == cid:
                        focus = c
                        break
        elif "larkfield" in q:
            focus = self.get_chase("ch-001")
        elif "brindle" in q:
            focus = self.get_chase("ch-002")
        elif "mosswood" in q:
            focus = self.get_chase("ch-004")
        elif "kestrel" in q:
            focus = self.get_chase("ch-003")
        elif overdue_q and open_chases:
            overdue = [c for c in open_chases if (c.days_overdue or 0) > 0]
            focus = overdue[0] if overdue else open_chases[0]
        else:
            focus = last

        lines: list[str] = []
        if focus:
            client = self.get_client(focus.client_id)
            cname = client.name if client else focus.client_id
            lines.append(
                f"Focus: {focus.summary or focus.id} ({cname}). "
                f"Status={focus.status}; last_action={focus.last_action or '—'}."
            )
        elif last:
            client = self.get_client(last.client_id)
            cname = client.name if client else last.client_id
            lines.append(
                f"Last focus: {last.summary or last.id} ({cname}). "
                f"Status={last.status}; last_action={last.last_action or '—'}."
            )

        if matched_clients:
            lines.append(
                "Matched clients: "
                + "; ".join(f"{c.name} ({c.contact or c.id})" for c in matched_clients[:4])
            )
        if matched_jobs:
            lines.append(
                "Matched jobs: "
                + "; ".join(f"{j.title} @ {j.address or '—'}" for j in matched_jobs[:4])
            )
        if matched_chases and not focus:
            lines.append(
                "Matched chases: "
                + "; ".join(f"{c.id} {c.invoice_ref or ''} {c.summary[:60]}" for c in matched_chases[:4])
            )

        if overdue_q:
            overdue = [c for c in open_chases if (c.days_overdue or 0) > 0]
            if overdue:
                bullets = "; ".join(
                    f"{c.id} {c.invoice_ref or ''} £{c.amount or 0:.0f} ({c.days_overdue}d)".strip()
                    for c in overdue[:5]
                )
                lines.append(f"Overdue ({len(overdue)}): {bullets}")

        if open_chases and not overdue_q:
            top = open_chases[:4]
            bullets = "; ".join(
                f"{c.id} {c.invoice_ref or ''} £{c.amount or 0:.0f} ({c.days_overdue}d)".strip()
                for c in top
            )
            lines.append(f"Open chases ({len(open_chases)}): {bullets}")

        recent_notes = notes_all[:3]
        if matched_notes:
            lines.append("Matched notes: " + " | ".join(n.text[:80] for n in matched_notes[:3]))
        elif recent_notes:
            lines.append("Recent notes: " + " | ".join(n.text[:80] for n in recent_notes))

        if not lines:
            lines.append("Memory is empty — seed data missing.")

        return {
            "query": query or "what were we chasing?",
            "answer": " ".join(lines),
            "session": sess,
            "focus": focus.model_dump(mode="json") if focus else None,
            "matched_clients": [c.model_dump(mode="json") for c in matched_clients[:8]],
            "matched_jobs": [j.model_dump(mode="json") for j in matched_jobs[:8]],
            "matched_chases": [c.model_dump(mode="json") for c in matched_chases[:8]],
            "matched_notes": [n.model_dump(mode="json") for n in matched_notes[:8]],
            "open_chases": [c.model_dump(mode="json") for c in open_chases],
            "notes": [n.model_dump(mode="json") for n in recent_notes],
        }

    def add_activity(
        self,
        action: str,
        *,
        chase_id: str | None = None,
        detail: str = "",
        draft_text: str = "",
    ) -> dict:
        with self._lock:
            entry = {
                "id": f"act-{len(self._data.get('activity', [])) + 1:04d}",
                "action": action,
                "chase_id": chase_id,
                "detail": detail,
                "draft_text": draft_text,
                "at": _now_iso(),
            }
            self._data.setdefault("activity", []).append(entry)
            self._flush_unlocked()
            return deepcopy(entry)


    def morning_digest(self) -> dict[str, Any]:
        """Overdue chases ranked, total £, suggested work order, one-line recall."""
        open_chases = self.list_chases(open_only=True)
        overdue = [c for c in open_chases if (c.days_overdue or 0) > 0]
        overdue = sorted(
            overdue,
            key=lambda c: (-(c.days_overdue or 0), -(c.amount or 0)),
        )
        total = round(sum(float(c.amount or 0) for c in overdue), 2)
        clients = {c.id: c for c in self.list_clients()}
        jobs = {j.id: j for j in self.list_jobs()}
        ranked = []
        for i, c in enumerate(overdue, start=1):
            cl = clients.get(c.client_id)
            job = jobs.get(c.job_id) if c.job_id else None
            ranked.append(
                {
                    "rank": i,
                    "chase_id": c.id,
                    "client": cl.name if cl else c.client_id,
                    "contact": (cl.contact if cl else "") or "",
                    "invoice_ref": c.invoice_ref,
                    "amount": c.amount,
                    "days_overdue": c.days_overdue,
                    "summary": c.summary,
                    "address": (job.address if job else "") or "",
                    "why": (
                        f"{c.days_overdue}d overdue · £{c.amount or 0:.0f}"
                        + (f" · bounce risk" if "bounce" in (c.last_action or "").lower() else "")
                    ),
                }
            )
        order = [r["chase_id"] for r in ranked]
        # one-line memory recall
        recall = self.recall("what were we chasing?")
        focus = recall.get("focus") or {}
        one_line = recall.get("answer", "")
        if len(one_line) > 220:
            one_line = one_line[:217] + "…"
        # also include high-priority non-overdue open (invoice ready etc) after overdue
        extras = [
            c
            for c in open_chases
            if (c.days_overdue or 0) <= 0
            and c.id not in order
            and ("invoice" in (c.summary or "").lower() or "ready" in (c.summary or "").lower())
        ][:3]
        suggested_order = order + [c.id for c in extras]
        work_lines = []
        for r in ranked[:6]:
            work_lines.append(
                f"{r['rank']}. {r['client']} {r['invoice_ref'] or r['chase_id']} "
                f"£{r['amount'] or 0:.0f} ({r['days_overdue']}d)"
            )
        for c in extras:
            cl = clients.get(c.client_id)
            work_lines.append(
                f"• {cl.name if cl else c.client_id}: {c.summary or c.id} (not overdue — invoice/ready)"
            )
        headline = (
            f"Morning digest: {len(overdue)} overdue · £{total:,.2f} to chase"
            if overdue
            else "Morning digest: no overdue chases — clear the ready-to-invoice queue."
        )
        return {
            "headline": headline,
            "overdue_count": len(overdue),
            "total_gbp": total,
            "ranked": ranked,
            "suggested_order": suggested_order,
            "work_order": work_lines,
            "memory_recall": one_line,
            "top_chase_id": suggested_order[0] if suggested_order else (focus.get("id") if focus else None),
            "focus": focus or None,
        }

    def reset_to_seed(self) -> None:

        with self._lock:
            self._data = seed_payload()
            self._flush_unlocked()


store = MemoryStore()
