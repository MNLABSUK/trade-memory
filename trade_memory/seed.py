"""Seed Halden & Rook / Larch–style UK trade memory (deepened narrative)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_memory.models import Chase, Client, DecisionRecord, Job, MemoryNote, SessionState

NOW = datetime.now(timezone.utc)


def seed_payload() -> dict:
    clients = [
        Client(
            id="cli-fernhill",
            name="Fernhill School",
            trade="CCTV service",
            contact="accounts@fernhill.example",
            notes=["Finance contact changed last term", "Prefer email over phone"],
        ),
        Client(
            id="cli-quayside",
            name="Quayside Bistro",
            trade="Camera clean + recable",
            contact="accounts@quaysidebistro.example",
            notes=["Previous chase bounced — try accounts@", "Owner rarely answers mobile"],
        ),
        Client(
            id="cli-elm",
            name="Elm Court Flats",
            trade="Camera realign + HDD",
            contact="site@elmcourt.example",
            notes=["Signed off on site — ready to invoice"],
        ),
        Client(
            id="cli-birchlea",
            name="Birch Lea Care Home",
            trade="Call-out / lobby camera",
            contact="manager@birchlea.example",
            notes=["Lobby cam 2 flaky", "Install crew tomorrow morning"],
        ),
        Client(
            id="cli-northgate",
            name="Northgate Logistics (Unit 12)",
            trade="New install quote",
            contact="jo.hart@northgatelogistics.example",
            notes=["Wants Hikvision or equivalent", "Ballpark this week"],
        ),
        Client(
            id="cli-larch",
            name="Larch Workshop (MN Labs demo)",
            trade="Access control + NVR",
            contact="ops@larch.example",
            notes=[
                "Demo client for Open Agent track",
                "Persistent memory narrative — restart and ask what we were chasing",
            ],
        ),
    ]

    jobs = [
        Job(
            id="job-2841",
            client_id="cli-fernhill",
            title="Fernhill School CCTV service visit",
            status="invoiced",
            address="Fernhill Rd, Leeds",
            amount=480.0,
            notes=["INV-2841 raised", "30 days past due"],
        ),
        Job(
            id="job-2790",
            client_id="cli-quayside",
            title="Quayside Bistro camera clean + recable",
            status="invoiced",
            address="Quayside Wharf",
            amount=210.0,
            notes=["INV-2790", "14 days past due", "Prior email bounced"],
        ),
        Job(
            id="job-oak",
            client_id="cli-elm",
            title="Elm Court flats realign + HDD swap",
            status="complete",
            address="Elm Court",
            amount=322.5,
            notes=["Labour 3.5h @ £65 + parts £95", "Ready to raise invoice"],
        ),
        Job(
            id="job-ash",
            client_id="cli-birchlea",
            title="Birch Lea lobby camera call-out",
            status="scheduled",
            address="Birch Lea Care Home",
            amount=None,
            notes=["Slot before install crew"],
        ),
        Job(
            id="job-metro",
            client_id="cli-northgate",
            title="Unit 12 warehouse — 4x IP + NVR quote",
            status="quoting",
            address="Unit 12, Northgate Logistics",
            amount=None,
            notes=["4 outdoor IP + 8ch NVR"],
        ),
        Job(
            id="job-larch",
            client_id="cli-larch",
            title="Larch workshop NVR commissioning",
            status="open",
            address="Larch workshop bay",
            amount=890.0,
            notes=["Deposit received", "Final commissioning chase pending", "Balance INV-Q-118"],
        ),
        Job(
            id="job-larch-access",
            client_id="cli-larch",
            title="Larch workshop access reader install",
            status="closed",
            address="Larch workshop bay — side door",
            amount=320.0,
            notes=["Completed last month", "Paid — closed chase ch-007"],
        ),
    ]

    chases = [
        Chase(
            id="ch-001",
            client_id="cli-fernhill",
            job_id="job-2841",
            invoice_ref="INV-2841",
            amount=480.0,
            days_overdue=30,
            status="open",
            summary="Fernhill School INV-2841 £480 — 30 days past due",
            last_action="Accounts reminder logged",
            history=[
                f"{(NOW - timedelta(days=30)).date().isoformat()}: INV-2841 issued",
                f"{(NOW - timedelta(days=14)).date().isoformat()}: polite reminder emailed",
                f"{(NOW - timedelta(days=3)).date().isoformat()}: finance said 'with accounts'",
            ],
        ),
        Chase(
            id="ch-002",
            client_id="cli-quayside",
            job_id="job-2790",
            invoice_ref="INV-2790",
            amount=210.0,
            days_overdue=14,
            status="open",
            summary="Quayside Bistro INV-2790 £210 — 14 days past due; prior email bounced",
            last_action="Bounce noted — try accounts@",
            history=[
                f"{(NOW - timedelta(days=14)).date().isoformat()}: INV-2790 issued",
                f"{(NOW - timedelta(days=7)).date().isoformat()}: chase to owner@ bounced",
                f"{(NOW - timedelta(days=1)).date().isoformat()}: switched target to accounts@",
            ],
        ),
        Chase(
            id="ch-003",
            client_id="cli-elm",
            job_id="job-oak",
            invoice_ref="INV-next",
            amount=322.5,
            days_overdue=0,
            status="open",
            summary="Elm Court job complete — raise & send invoice £322.50",
            last_action="Site signed off",
            history=[
                f"{(NOW - timedelta(days=2)).date().isoformat()}: labour + HDD swap complete",
                f"{(NOW - timedelta(days=1)).date().isoformat()}: site signed off — ready to invoice",
            ],
        ),
        Chase(
            id="ch-004",
            client_id="cli-birchlea",
            job_id="job-ash",
            invoice_ref="",
            amount=None,
            days_overdue=0,
            status="open",
            summary="Birch Lea lobby camera offline — confirm tomorrow AM slot",
            last_action="Call-out requested",
            history=[
                f"{(NOW - timedelta(hours=18)).isoformat()}: manager reported lobby cam 2 offline",
                f"{(NOW - timedelta(hours=6)).isoformat()}: offered tomorrow AM before install crew",
            ],
        ),
        Chase(
            id="ch-005",
            client_id="cli-northgate",
            job_id="job-metro",
            invoice_ref="",
            amount=None,
            days_overdue=0,
            status="waiting",
            summary="Northgate Logistics quote request — ballpark due this week",
            last_action="Lead received",
            history=[
                f"{(NOW - timedelta(days=4)).date().isoformat()}: Jo asked for Hikvision ballpark",
                f"{(NOW - timedelta(days=1)).date().isoformat()}: waiting on site photos from Jo",
            ],
        ),
        Chase(
            id="ch-006",
            client_id="cli-larch",
            job_id="job-larch",
            invoice_ref="INV-Q-118",
            amount=445.0,
            days_overdue=7,
            status="open",
            summary="Larch workshop balance INV-Q-118 £445 — 7 days overdue",
            last_action="Friendly reminder drafted last week — not sent",
            history=[
                f"{(NOW - timedelta(days=21)).date().isoformat()}: deposit received; NVR installed",
                f"{(NOW - timedelta(days=7)).date().isoformat()}: INV-Q-118 balance raised £445",
                f"{(NOW - timedelta(days=2)).date().isoformat()}: drafted friendly chase — parked for human gate",
                f"{(NOW - timedelta(hours=2)).isoformat()}: demo thread — ask memory after restart",
            ],
        ),
        # Closed chase with prior decision (reopen demo)
        Chase(
            id="ch-007",
            client_id="cli-larch",
            job_id="job-larch-access",
            invoice_ref="INV-Q-102",
            amount=320.0,
            days_overdue=0,
            status="closed",
            summary="Larch access reader INV-Q-102 £320 — paid & closed",
            last_action="Approved: thank-you + receipt sent",
            decision="approve",
            decision_note="Paid same day — closed for demo history",
            decided_at=NOW - timedelta(days=12),
            draft_action=(
                "Hi Larch Workshop,\n\nThanks — INV-Q-102 £320 received. "
                "Receipt attached.\n\nHalden & Rook / MN Labs"
            ),
            history=[
                f"{(NOW - timedelta(days=20)).date().isoformat()}: access reader installed",
                f"{(NOW - timedelta(days=15)).date().isoformat()}: INV-Q-102 issued",
                f"{(NOW - timedelta(days=12)).date().isoformat()}: payment received — Approve thank-you",
            ],
        ),
    ]

    notes = [
        MemoryNote(
            id="note-001",
            text="Session seed: Halden & Rook desk + Larch demo client loaded for Open Agent hackathon.",
            created_at=NOW - timedelta(hours=1),
        ),
        MemoryNote(
            id="note-002",
            text="Priority: Fernhill (30d) then Quayside (bounce) then Larch balance.",
            related_client_id="cli-fernhill",
            related_chase_id="ch-001",
            related_job_id="job-2841",
            created_at=NOW - timedelta(minutes=40),
        ),
        MemoryNote(
            id="note-003",
            text="Larch demo thread: after restart, ask “what were we chasing?” — should land on Fernhill or last session focus.",
            related_client_id="cli-larch",
            related_chase_id="ch-006",
            related_job_id="job-larch",
            created_at=NOW - timedelta(minutes=25),
        ),
        MemoryNote(
            id="note-004",
            text="Quayside: do not use owner@ — bounce. Prefer accounts@quaysidebistro.example.",
            related_client_id="cli-quayside",
            related_chase_id="ch-002",
            related_job_id="job-2790",
            created_at=NOW - timedelta(minutes=15),
        ),
    ]

    decisions = [
        DecisionRecord(
            id="dec-0001",
            chase_id="ch-007",
            decision="approve",
            draft_text=(
                "Hi Larch Workshop,\n\nThanks — INV-Q-102 £320 received. "
                "Receipt attached.\n\nHalden & Rook / MN Labs"
            ),
            note="Paid same day — closed for demo history",
            at=NOW - timedelta(days=12),
        ),
    ]

    session = SessionState(
        last_chase_id="ch-001",
        last_client_id="cli-fernhill",
        last_kind="chase",
        last_question="what were we chasing?",
        pending=None,
    )

    return {
        "version": 2,
        "updated_at": NOW.isoformat(),
        "clients": [c.model_dump(mode="json") for c in clients],
        "jobs": [j.model_dump(mode="json") for j in jobs],
        "chases": [c.model_dump(mode="json") for c in chases],
        "notes": [n.model_dump(mode="json") for n in notes],
        "decisions": [d.model_dump(mode="json") for d in decisions],
        "session": session.model_dump(mode="json"),
        "activity": [
            {
                "id": "act-0001",
                "action": "seeded",
                "detail": "Loaded Halden & Rook / Larch trade memory seed (deepen v2)",
                "at": (NOW - timedelta(hours=1)).isoformat(),
            },
            {
                "id": "act-0002",
                "action": "approved",
                "chase_id": "ch-007",
                "detail": "Paid same day — closed for demo history",
                "draft_text": "Thank-you + receipt for INV-Q-102",
                "at": (NOW - timedelta(days=12)).isoformat(),
            },
            {
                "id": "act-0003",
                "action": "note",
                "chase_id": "ch-006",
                "detail": "Larch demo thread primed for persistent memory story",
                "at": (NOW - timedelta(minutes=25)).isoformat(),
            },
        ],
    }
