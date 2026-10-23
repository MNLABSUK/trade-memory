"""Seed Halden & Rook Electrical Ltd (Leeds) trade memory — fictional, mirrors demo_data/.

Open chases match the five demo puzzles (P1–P5) and the unpaid rows in
demo_data/ops_db/invoices.csv: £2,166 + £2,940 + £2,160 + £8,220 + £9,200 = £24,686.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_memory.models import Chase, Client, DecisionRecord, Job, MemoryNote, SessionState

NOW = datetime.now(timezone.utc)
SIGN_OFF = "Tom Rook, Halden & Rook Electrical"


def _d(days: int) -> str:
    return (NOW - timedelta(days=days)).date().isoformat()


def seed_payload() -> dict:
    clients = [
        Client(
            id="cli-lark",
            name="Larkfield Lettings",
            trade="Landlord EICRs + remedials",
            contact="finance@larkfield-lettings.example",
            notes=[
                "accounts@larkfield-lettings.example bouncing (550) since 3 Sep — C-001",
                "Nadia Ferrow took over AP Sept 2026 — use finance@ (C-002)",
            ],
        ),
        Client(
            id="cli-brin",
            name="Brindle & Oak Cafés",
            trade="Kitchen circuits + oven supply",
            contact="jonty@brindleandoak.example",
            notes=["Jonty Brindle rarely reads email; pays same day when phoned (07700 900401)"],
        ),
        Client(
            id="cli-kest",
            name="Kestrel Self Storage",
            trade="Gate access + yard floodlights",
            contact="ap@kss-operations.example",
            notes=["Parent co. KSS Operations pays supplier invoices with its own run numbers (C-010)"],
        ),
        Client(
            id="cli-moss",
            name="Mosswood Academy Trust",
            trade="LED lighting + PAT testing",
            contact="ap@mosswood-trust.example",
            notes=["Invoices must quote PO number; upload via supplier portal (C-006)"],
        ),
        Client(
            id="cli-copp",
            name="Copperbeech Dental Group",
            trade="Full rewire + emergency lighting",
            contact="finance@copperbeech-dental.example",
            notes=["Simon Arkwright holding balance pending surgery 3 snag (C-005)"],
        ),
    ]

    jobs = [
        Job(id="job-507", client_id="cli-lark", title="Larkfield smoke alarm swap (+7 more invoices)",
            status="invoiced", address="18 Armley Lane, Leeds", amount=462.0,
            notes=["INV-1007–INV-1014 unpaid, £2,166 total", "Chases to accounts@ bounced 3x"]),
        Job(id="job-514", client_id="cli-lark", title="Larkfield landlord EICR remedials",
            status="invoiced", address="22 Moortown Crescent, Leeds", amount=174.0,
            notes=["INV-1014 £174 due 24 Oct"]),
        Job(id="job-520", client_id="cli-brin", title="Brindle & Oak kitchen circuits + oven supply",
            status="invoiced", address="Brindle & Oak, 12 Call Lane, Leeds", amount=2940.0,
            notes=["INV-1020 £2,940 due 14 Sep", "Two WhatsApp promises missed"]),
        Job(id="job-522", client_id="cli-kest", title="Kestrel gate access + yard floodlights",
            status="invoiced", address="Kestrel Self Storage, Unit 4 Stourton Ind Est, Leeds", amount=2160.0,
            notes=["INV-1043 £2,160", "Possible receipt BL-0078 ref 7781 from KSS OPERATIONS LTD"]),
        Job(id="job-518", client_id="cli-moss", title="Mosswood sports hall LED upgrade",
            status="invoiced", address="Mosswood Academy, Stonegate Lane, Leeds", amount=8220.0,
            notes=["INV-1018 rejected by AP portal: no PO", "Job carries PO-MAT-77412"]),
        Job(id="job-515", client_id="cli-copp", title="Copperbeech Chapeltown practice full rewire",
            status="invoiced", address="Copperbeech Dental, 88 Harehills Road, Leeds", amount=18400.0,
            notes=["INV-1015 £18,400; £9,200 stage payment received", "Snag closed JS-216 on 2 Oct"]),
        Job(id="job-519", client_id="cli-moss", title="Mosswood PAT testing, main block",
            status="closed", address="Mosswood Academy, Stonegate Lane, Leeds", amount=1128.0,
            notes=["INV-1019 paid with PO-MAT-76980 — closed chase ch-007"]),
    ]

    chases = [
        Chase(id="ch-001", client_id="cli-lark", job_id="job-507", invoice_ref="INV-1007",
              amount=2166.0, days_overdue=41, status="open",
              summary="Larkfield Lettings INV-1007–INV-1014 £2,166 — 41 days past due; accounts@ bounced",
              last_action="Third chase to accounts@ bounced (MSG-0006)",
              history=[f"{_d(43)}: chase to accounts@ bounced (MSG-0002)",
                       f"{_d(29)}: chase to accounts@ bounced (MSG-0004)",
                       f"{_d(15)}: chase to accounts@ bounced (MSG-0006) — switch to finance@"]),
        Chase(id="ch-002", client_id="cli-brin", job_id="job-520", invoice_ref="INV-1020",
              amount=2940.0, days_overdue=38, status="open",
              summary="Brindle & Oak INV-1020 £2,940 — 38 days past due; two broken promises",
              last_action="Second email reminder, no reply (MSG-0013)",
              history=[f"{_d(29)}: 'will pay Friday' (MSG-0011, by 2 Oct) — no credit",
                       f"{_d(15)}: 'definitely this Friday' (MSG-0012, by 16 Oct) — no credit"]),
        Chase(id="ch-003", client_id="cli-kest", job_id="job-522", invoice_ref="INV-1043",
              amount=2160.0, days_overdue=12, status="open",
              summary="Kestrel Self Storage INV-1043 £2,160 — check BL-0078 before chasing",
              last_action="Asha: parent company pays (MSG-0015)",
              history=[f"{_d(18)}: BL-0078 £2,160 ref 7781 from KSS OPERATIONS LTD",
                       f"{_d(12)}: chase sent to site manager (MSG-0014)"]),
        Chase(id="ch-004", client_id="cli-moss", job_id="job-518", invoice_ref="INV-1018",
              amount=8220.0, days_overdue=21, status="open",
              summary="Mosswood Academy INV-1018 £8,220 — rejected: no PO (job has PO-MAT-77412)",
              last_action="AP portal rejection (MSG-0009)",
              history=[f"{_d(44)}: rejected by trust AP portal — no PO"]),
        Chase(id="ch-005", client_id="cli-copp", job_id="job-515", invoice_ref="INV-1015",
              amount=9200.0, days_overdue=3, status="waiting",
              summary="Copperbeech Dental INV-1015 balance £9,200 — held for snag, closed JS-216",
              last_action="Simon: balance held pending snag (MSG-0008)",
              history=[f"{_d(20)}: snag closed JS-216, photo + sign-off R. Okonjo",
                       f"{_d(17)}: finance says balance held pending snag"]),
        Chase(id="ch-007", client_id="cli-moss", job_id="job-519", invoice_ref="INV-1019",
              amount=1128.0, days_overdue=0, status="closed",
              summary="Mosswood PAT testing INV-1019 £1,128 — paid & closed",
              last_action="Approved: thank-you + receipt sent",
              decision="approve", decision_note="Paid with PO-MAT-76980 — closed for demo history",
              decided_at=NOW - timedelta(days=60),
              draft_action=f"Hi Mosswood AP,\n\nThanks — INV-1019 £1,128 received. Receipt attached.\n\n{SIGN_OFF}",
              history=[f"{_d(68)}: INV-1019 issued with PO-MAT-76980", f"{_d(60)}: paid — Approve thank-you"]),
    ]

    notes = [
        MemoryNote(id="note-001", text="Session seed: Halden & Rook Electrical desk (Leeds) loaded for Open Agent hackathon.",
                   created_at=NOW - timedelta(hours=1)),
        MemoryNote(id="note-002", text="Priority: Larkfield (41d, bounced) then Brindle & Oak (broken promises) then Mosswood PO.",
                   related_client_id="cli-lark", related_chase_id="ch-001", related_job_id="job-507",
                   created_at=NOW - timedelta(minutes=40)),
        MemoryNote(id="note-003", text="Kestrel: do not chase until BL-0078 is checked against INV-1043.",
                   related_client_id="cli-kest", related_chase_id="ch-003", related_job_id="job-522",
                   created_at=NOW - timedelta(minutes=25)),
        MemoryNote(id="note-004", text="Larkfield: do not use accounts@ — bounce. Prefer finance@larkfield-lettings.example.",
                   related_client_id="cli-lark", related_chase_id="ch-001", related_job_id="job-507",
                   created_at=NOW - timedelta(minutes=15)),
    ]

    decisions = [
        DecisionRecord(id="dec-0001", chase_id="ch-007", decision="approve",
                       draft_text=f"Hi Mosswood AP,\n\nThanks — INV-1019 £1,128 received. Receipt attached.\n\n{SIGN_OFF}",
                       note="Paid with PO-MAT-76980 — closed for demo history", at=NOW - timedelta(days=60)),
    ]

    session = SessionState(last_chase_id="ch-001", last_client_id="cli-lark", last_kind="chase",
                           last_question="what were we chasing?", pending=None)

    return {
        "version": 3,
        "updated_at": NOW.isoformat(),
        "clients": [c.model_dump(mode="json") for c in clients],
        "jobs": [j.model_dump(mode="json") for j in jobs],
        "chases": [c.model_dump(mode="json") for c in chases],
        "notes": [n.model_dump(mode="json") for n in notes],
        "decisions": [d.model_dump(mode="json") for d in decisions],
        "session": session.model_dump(mode="json"),
        "activity": [
            {"id": "act-0001", "action": "seeded",
             "detail": "Loaded Halden & Rook Electrical trade memory seed (v3, matches demo_data)",
             "at": (NOW - timedelta(hours=1)).isoformat()},
            {"id": "act-0002", "action": "approved", "chase_id": "ch-007",
             "detail": "Paid with PO-MAT-76980 — closed for demo history",
             "draft_text": "Thank-you + receipt for INV-1019", "at": (NOW - timedelta(days=60)).isoformat()},
        ],
    }
