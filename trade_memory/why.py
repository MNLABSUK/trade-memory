"""Evidence-cited "Why" cards for the five Halden & Rook puzzles, with a human approval gate.

Flow: Zetaris rows (zetaris_client; offline CSV fallback) -> puzzle solver -> card with
source rows, reasoning steps, confidence, H-MEM memories used -> Approve / Reject.
A decision is written to H-MEM (namespace case:<P>) and the next proposal for that case
is derived from the decision trail: approve advances to the follow-up step, reject switches
to the alternative action (with lower confidence). Nothing is ever sent automatically;
"approved" means queued in data/outbox.jsonl for the human to send — no email leaves this app.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from trade_memory import zetaris_client as zc
from trade_memory.hmem import HMem, hmem as default_hmem

SIGN_OFF = "Tom Rook\nHalden & Rook Electrical Ltd, Leeds"
TODAY = "2026-10-22"
OUTBOX = Path(__file__).resolve().parent.parent / "data" / "outbox.jsonl"


class RecordingClient:
    """Wraps a ZetarisClient and keeps every SQL statement it ran (shown on the card)."""

    def __init__(self, inner: zc.ZetarisClient):
        self.inner, self.queries = inner, []

    @property
    def mode(self) -> str:
        return self.inner.mode

    def query(self, sql: str, limit: int = 1000) -> list[dict]:
        t = time.time()
        rows = [_norm(r) for r in self.inner.query(sql, limit)]
        self.queries.append({"sql": " ".join(sql.split()), "rows": len(rows),
                             "ms": round((time.time() - t) * 1000), "mode": self.inner.mode})
        return rows


_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _norm(row: dict) -> dict:
    """Live Zetaris returns DECIMALs as strings; offline SQLite returns floats. Make money numeric."""
    out = {}
    for k, v in row.items():
        k = k.split(".")[-1].lower() if isinstance(k, str) else k
        if isinstance(v, str) and ("gbp" in k or "amount" in k) and _NUM.match(v.strip()):
            v = float(v)
        out[k] = v
    return out


def _gbp(v: float) -> str:
    return f"£{v:,.0f}" if float(v).is_integer() else f"£{v:,.2f}"


def _row(table: str, rid: str, **fields: Any) -> dict:
    return {"table": table, "id": rid, "fields": {k: v for k, v in fields.items() if v not in (None, "")}}


def totals(c) -> dict:
    rows = c.query("SELECT invoice_id, client_name, total_gbp, amount_paid_gbp, status FROM tm_ops.invoices "
                   "WHERE status <> 'paid'")
    by: dict[str, float] = {}
    for r in rows:
        by[r["client_name"]] = by.get(r["client_name"], 0) + zc._num(r["total_gbp"]) - zc._num(r["amount_paid_gbp"])
    out = round(sum(by.values()), 2)
    return {"outstanding_gbp": out, "by_client": {k: round(v, 2) for k, v in by.items()},
            "invoices": [r["invoice_id"] for r in rows]}


# ---- per-puzzle builders: return (base card, actions) -------------------------------------
# action: {id, title, channel, to, draft, confidence, next, alt}

def _p1(c) -> tuple[dict, dict]:
    r = zc.p1_unmatched_receipt(c)
    m, payer = r["matches"][0], (r["payer_contacts"] or [{}])[0]
    ev = [_row("tm_ops.invoices", m["invoice_id"], client=m["client_code"], total_gbp=m["total_gbp"],
               issued=m["issue_date"], status="sent (unpaid in ledger)"),
          _row("tm_files.bank_lines", m["bank_line_id"], date=m["date"], amount_gbp=m["amount_gbp"],
               counterparty=m["counterparty"], reference=m["reference"]),
          _row("tm_files.contacts", payer.get("contact_id", ""), name=payer.get("name"), role=payer.get("role"),
               email=payer.get("email"), notes=payer.get("notes"))]
    amt = _gbp(m["total_gbp"])
    steps = [f"{m['invoice_id']} ({amt}) is unpaid in the ledger, issued {m['issue_date']}.",
             f"Bank line {m['bank_line_id']} on {m['date']} is a credit of exactly {_gbp(m['amount_gbp'])}, after the issue date.",
             f"Payer is {m['counterparty']} with reference {m['reference']} — not an invoice number, so auto-matching missed it.",
             f"{payer.get('contact_id')} says the parent company pays supplier invoices with its own run numbers.",
             "Conclusion: Kestrel has paid. Chasing would be wrong; allocate the receipt instead."]
    acts = {
        "allocate": dict(title=f"Don't chase — allocate {m['bank_line_id']} to {m['invoice_id']} and mark paid",
                         channel="ledger", to="ledger (internal)", confidence=0.93, next="thanks", alt="confirm",
                         draft=f"Ledger note: allocate {m['bank_line_id']} {amt} ({m['counterparty']}, ref {m['reference']}) "
                               f"to {m['invoice_id']}; mark paid {m['date']}. Cancel the chase to Asha."),
        "thanks": dict(title=f"Thank {payer.get('name')} and ask them to quote invoice numbers", channel="email",
                       to=payer.get("email"), confidence=0.85, next=None, alt=None,
                       draft=f"Hi KSS Operations,\n\nThank you — your payment run {m['reference']} for {amt} on {m['date']} "
                             f"has been allocated to {m['invoice_id']}. Could future remittances quote our invoice "
                             f"number so we can match them first time?\n\n{SIGN_OFF}"),
        "confirm": dict(title=f"Ask {payer.get('name')} to confirm run {m['reference']} covers {m['invoice_id']}",
                        channel="email", to=payer.get("email"), confidence=0.78, next="allocate_after", alt=None,
                        draft=f"Hi KSS Operations,\n\nWe received {amt} on {m['date']} (your ref {m['reference']}). "
                              f"Can you confirm it settles our {m['invoice_id']}? Thanks.\n\n{SIGN_OFF}"),
        "allocate_after": dict(title=f"Allocate {m['bank_line_id']} to {m['invoice_id']} (payer confirmed)",
                               channel="ledger", to="ledger (internal)", confidence=0.95, next=None, alt=None,
                               draft=f"Ledger note: allocate {m['bank_line_id']} to {m['invoice_id']}; confirmed by KSS."),
    }
    return dict(client="Kestrel Self Storage", client_code="KEST", headline="Paid — but the bank reference doesn't match",
                amount_gbp=m["total_gbp"], evidence=ev, steps=steps, start="allocate"), acts


def _p2(c) -> tuple[dict, dict]:
    r = zc.p2_bounced_contact(c)
    bad, alt = r["bounced"][0], r["resend_to"][0]
    inv = c.query("SELECT invoice_id, total_gbp, due_date FROM tm_ops.invoices "
                  "WHERE client_code = 'LARK' AND status <> 'paid' ORDER BY invoice_id")
    owed = round(sum(zc._num(i["total_gbp"]) for i in inv), 2)
    ids = f"{inv[0]['invoice_id']}–{inv[-1]['invoice_id']}"
    ev = [_row("tm_files.contacts", bad["contact_id"], email=bad["email"], bounced=True, since=bad["bounce_since"]),
          _row("tm_files.contacts", alt["contact_id"], name=alt["name"], email=alt["email"], bounced=False)]
    ev += [_row("tm_files.inbox", mid, bounce=True) for mid in r["bounce_messages"]]
    ev.append(_row("tm_ops.invoices", ids, count=len(inv), outstanding_gbp=owed))
    steps = [f"{len(inv)} Larkfield invoices ({ids}) are unpaid: {_gbp(owed)}.",
             f"All {len(r['bounce_messages'])} chases went to {bad['email']} and bounced ({', '.join(r['bounce_messages'])}).",
             f"CRM flags {bad['contact_id']} bounced since {bad['bounce_since']}; {alt['contact_id']} {alt['name']} took over AP.",
             f"So Larkfield has never actually seen a chase. Resend once to {alt['email']}."]
    acts = {
        "email": dict(title=f"Resend the statement to {alt['name']} at finance@", channel="email", to=alt["email"],
                      confidence=0.9, next="crm", alt="phone",
                      draft=f"Hi Nadia,\n\nOur reminders went to {bad['email']}, which has been bouncing since "
                            f"{bad['bounce_since']}, so apologies if this is the first you've seen of them. "
                            f"{len(inv)} invoices ({ids}) are open, {_gbp(owed)} in total — statement attached. "
                            f"Could you let me know when they're scheduled?\n\n{SIGN_OFF}"),
        "crm": dict(title=f"Retire {bad['email']} in the CRM; make finance@ the AP contact", channel="crm",
                    to="CRM (internal)", confidence=0.9, next=None, alt=None,
                    draft=f"CRM change: {bad['contact_id']} inactive (550 since {bad['bounce_since']}); "
                          f"{alt['contact_id']} {alt['name']} = Larkfield AP contact."),
        "phone": dict(title=f"Phone {alt['name']} instead (0113 496 0102)", channel="phone", to="0113 496 0102",
                      confidence=0.72, next=None, alt=None,
                      draft=f"Call script: Nadia, it's Tom at Halden & Rook. Our chases went to a dead mailbox — "
                            f"{len(inv)} invoices, {_gbp(owed)}. Can I email the statement to finance@?"),
    }
    return dict(client="Larkfield Lettings", client_code="LARK", headline="They never got the chases — mailbox bounces",
                amount_gbp=owed, evidence=ev, steps=steps, start="email"), acts


def _p3(c) -> tuple[dict, dict]:
    r = zc.p3_dispute_vs_jobsheet(c)
    s = r["closed_snags"][0]
    msg = c.query("SELECT message_id, timestamp, summary FROM tm_files.inbox WHERE client_code = 'COPP'")
    bal = r["balance_gbp"]
    ev = [_row("tm_ops.invoices", s["invoice_id"], total_gbp=s["total_gbp"], paid_gbp=s["amount_paid_gbp"],
               balance_gbp=bal),
          _row("tm_ops.job_sheets", s["job_sheet_id"], snag_status=s["snag_status"], closed=s["snag_closed_date"],
               photo=s["photo_ref"], signed_off_by=s["signed_off_by"]),
          _row("tm_files.contacts", "C-005", name="Simon Arkwright", email="finance@copperbeech-dental.example",
               notes="Holding balance pending snag")]
    ev += [_row("tm_files.inbox", m["message_id"], at=zc._s(m["timestamp"])[:10], summary=m["summary"]) for m in msg]
    steps = [f"{s['invoice_id']} is {_gbp(s['total_gbp'])}; {_gbp(s['amount_paid_gbp'])} paid, {_gbp(bal)} held.",
             "Finance says the balance is held pending the surgery 3 snag.",
             f"Job sheet {s['job_sheet_id']} closed that snag on {s['snag_closed_date']} with a photo, "
             f"signed off by {s['signed_off_by']}.",
             "The job sheet is newer and signed — evidence beats the email. Chase the balance with the proof."]
    acts = {
        "email": dict(title=f"Chase the {_gbp(bal)} balance with {s['job_sheet_id']} attached", channel="email",
                      to="finance@copperbeech-dental.example", confidence=0.88, next=None, alt="ruth",
                      draft=f"Hi Simon,\n\nThe surgery 3 snag was closed on {s['snag_closed_date']} — job sheet "
                            f"{s['job_sheet_id']} (photo attached) was signed off by Ruth Okonjo. That clears the hold, "
                            f"so the {_gbp(bal)} balance on {s['invoice_id']} is now due. Could you release it in "
                            f"your next payment run?\n\n{SIGN_OFF}"),
        "ruth": dict(title=f"Send {s['job_sheet_id']} to Ruth Okonjo first and ask her to tell finance", channel="email",
                     to="ruth.okonjo@copperbeech-dental.example", confidence=0.75, next=None, alt=None,
                     draft=f"Hi Ruth,\n\nAttached is job sheet {s['job_sheet_id']} you signed on {s['snag_closed_date']} "
                           f"for the surgery 3 RCBO. Finance are still holding {_gbp(bal)} for it — could you let "
                           f"Simon know it's closed?\n\n{SIGN_OFF}"),
    }
    return dict(client="Copperbeech Dental Group", client_code="COPP", headline="Dispute already resolved on site",
                amount_gbp=bal, evidence=ev, steps=steps, start="email"), acts


def _p4(c) -> tuple[dict, dict]:
    r = zc.p4_missing_po(c)
    x = r["reissue"][0]
    amt = c.query(f"SELECT total_gbp FROM tm_ops.invoices WHERE invoice_id = '{x['invoice_id']}'")[0]["total_gbp"]
    ap = next(a for a in r["ap_contacts"] if a["contact_id"] == "C-006")
    ev = [_row("tm_ops.invoices", x["invoice_id"], total_gbp=amt, status=x["status"], po_number="(blank)",
               notes=x["notes"]),
          _row("tm_ops.jobs", x["job_id"], po_number=x["job_po"]),
          _row("tm_files.contacts", ap["contact_id"], channel=ap["preferred_channel"], notes=ap["notes"]),
          _row("tm_files.inbox", "MSG-0009", summary="Trust AP portal rejected INV-1018")]
    steps = [f"{x['invoice_id']} ({_gbp(amt)}) was rejected: {x['notes']}.",
             f"The job it bills, {x['job_id']}, carries {x['job_po']}.",
             f"{ap['contact_id']} (Trust AP) requires a PO and portal upload — chasing by email won't work.",
             f"Reissue with {x['job_po']} and upload to the portal."]
    acts = {
        "reissue": dict(title=f"Reissue {x['invoice_id']} with {x['job_po']} via the trust portal", channel="portal",
                        to="Mosswood supplier portal (C-006)", confidence=0.92, next=None, alt="confirm",
                        draft=f"Portal upload: {x['invoice_id']} rev A, {_gbp(amt)}, PO {x['job_po']} "
                              f"(job {x['job_id']}, LED upgrade sports hall). Note: 'Reissued with PO — original "
                              f"rejected 2026-09-08.'"),
        "confirm": dict(title=f"Ask Helen Pike to confirm {x['job_po']} is the right PO", channel="email",
                        to="h.pike@mosswood-trust.example", confidence=0.7, next="reissue_after", alt=None,
                        draft=f"Hi Helen,\n\nYour AP portal rejected {x['invoice_id']} for missing a PO. Our job record "
                              f"for the sports hall LEDs has {x['job_po']} — can you confirm that's right?\n\n{SIGN_OFF}"),
        "reissue_after": dict(title=f"Reissue {x['invoice_id']} with the confirmed PO", channel="portal",
                              to="Mosswood supplier portal (C-006)", confidence=0.95, next=None, alt=None,
                              draft=f"Portal upload: {x['invoice_id']} rev A with {x['job_po']} (confirmed)."),
    }
    return dict(client="Mosswood Academy Trust", client_code="MOSS", headline="Rejected for a missing PO we already have",
                amount_gbp=amt, evidence=ev, steps=steps, start="reissue"), acts


def _p5(c) -> tuple[dict, dict]:
    r = zc.p5_broken_promises(c, today=TODAY)
    inv, ct = r["invoices"][0], r["contact"][0]
    ev = [_row("tm_ops.invoices", inv["invoice_id"], total_gbp=inv["total_gbp"], paid_gbp=inv["amount_paid_gbp"]),
          _row("tm_files.contacts", ct["contact_id"], name=ct["name"], phone=ct["phone"],
               channel=ct["preferred_channel"], notes=ct["notes"])]
    ev += [_row("tm_files.inbox", m["message_id"], at=zc._s(m["timestamp"])[:10], promise=m["promise"])
           for m in r["broken_promises"]]
    ev.append(_row("tm_files.bank_lines", "no match", matching_credit=f"no credit of {_gbp(inv['total_gbp'])} since first promise"))
    steps = [f"{inv['invoice_id']} ({_gbp(inv['total_gbp'])}) is unpaid.",
             f"{len(r['broken_promises'])} WhatsApp promises passed: "
             + "; ".join(f"{m['message_id']} '{m['promise']}'" for m in r["broken_promises"]) + ".",
             f"No matching credit in the bank feed after the first promise.",
             f"CRM: {ct['name']} {ct['notes'].lower().rstrip('.')}. Two more emails would be ignored — phone."]
    acts = {
        "phone": dict(title=f"Phone {ct['name']} today ({ct['phone']})", channel="phone", to=ct["phone"],
                      confidence=0.86, next=None, alt="final",
                      draft=f"Call script: Jonty, it's Tom at Halden & Rook about {inv['invoice_id']}, "
                            f"{_gbp(inv['total_gbp'])} for the oven supply. It was promised for 2 Oct and 16 Oct. "
                            f"Can you pay it now by bank transfer while we're on the phone?"),
        "final": dict(title="Send a final notice by WhatsApp with a 7-day deadline", channel="whatsapp",
                      to=ct["phone"], confidence=0.7, next=None, alt=None,
                      draft=f"Hi Jonty, {inv['invoice_id']} for {_gbp(inv['total_gbp'])} is now 5 weeks overdue and "
                            f"two payment dates have passed. Please pay by 29 Oct, or we'll have to pause work "
                            f"and add statutory late-payment interest. Tom, Halden & Rook"),
    }
    return dict(client="Brindle & Oak Cafés", client_code="BRIN", headline="Two broken promises — he pays when phoned",
                amount_gbp=inv["total_gbp"], evidence=ev, steps=steps, start="phone"), acts


# Durable client facts learned from past threads (episodic/semantic), each citing its source rows.
SEED_MEMORIES = [
    ("KEST", "Kestrel's parent KSS Operations pays supplier invoices on its own payment-run numbers.", "crm:C-010"),
    ("LARK", "Larkfield: accounts@ bounces since 3 Sep; Nadia Ferrow (finance@) took over AP.", "crm:C-001,C-002"),
    ("LARK", "Larkfield usually pays in batches on a ~45-day habit, remittance refs LL-PAY-xxxx.", "inbox:MSG-0007"),
    ("COPP", "Copperbeech finance (Simon) holds balances until the practice manager signs off snags.", "inbox:MSG-0008"),
    ("MOSS", "Mosswood Trust AP rejects any invoice without a PO; upload via supplier portal.", "inbox:MSG-0009"),
    ("BRIN", "Jonty promised to pay INV-1020 by 2 Oct (MSG-0011) and by 16 Oct (MSG-0012); neither landed.",
     "inbox:MSG-0011,MSG-0012"),
    ("BRIN", "Brindle & Oak paid INV-1021 the same day after a phone call (24 Jul) — email gets ignored.",
     "ops_db:INV-1021"),
]

BUILDERS: dict[str, Callable] = {"P1": _p1, "P2": _p2, "P3": _p3, "P4": _p4, "P5": _p5}


class WhyEngine:
    def __init__(self, client: zc.ZetarisClient | None = None, mem: HMem | None = None,
                 outbox: Path | None = None):
        self._zc = client
        self.mem = mem or default_hmem
        self.outbox = Path(outbox or OUTBOX)

    def _client(self) -> RecordingClient:
        if self._zc is None:
            self._zc = zc.ZetarisClient()
        return RecordingClient(self._zc)

    def ensure_seed_memories(self) -> None:
        have = {m.content for m in self.mem.all()}
        for code, text, src in SEED_MEMORIES:
            if text not in have:
                self.mem.remember(text, source=f"seed:{src}", confidence=0.85, origin="seed",
                                  label="client fact from past threads", layer="long_term",
                                  namespace=f"client:{code}", tags=[code], refs={"rows": src})

    def _decisions(self, pid: str) -> list:
        ds = [m for m in self.mem.all() if m.namespace == f"case:{pid}" and m.provenance.get("origin") == "approval"]
        return sorted(ds, key=lambda m: m.timestamp)

    def card(self, pid: str) -> dict:
        if pid not in BUILDERS:
            raise KeyError(pid)
        self.ensure_seed_memories()
        c = self._client()
        base, acts = BUILDERS[pid](c)
        trail, cur, rejections = [], base.pop("start"), 0
        for d in self._decisions(pid):
            refs = d.provenance.get("refs", {})
            if refs.get("action") != cur:
                continue  # stale decision for a superseded action
            trail.append({"action": cur, "decision": refs.get("decision"), "note": refs.get("note", ""),
                          "at": d.timestamp, "memory_id": d.id})
            if refs.get("decision") == "approve":
                cur = acts[cur]["next"]
            else:
                rejections += 1
                cur = acts[cur]["alt"]
            if cur is None:
                break
        q = f"{base['client']} {base['client_code']} {' '.join(e['id'] for e in base['evidence'])}"
        mems = self.mem.recall(q, namespace=f"case:{pid}", k=3) + \
            self.mem.recall(q, namespace=f"client:{base['client_code']}", k=3)
        used = [{"id": m.id, "content": m.content, "source": m.source, "layer": m.layer,
                 "confidence": m.confidence, "label": m.provenance.get("label")} for m in mems]
        steps = list(base.pop("steps"))
        for t in trail:
            steps.append(f"H-MEM: you {'approved' if t['decision'] == 'approve' else 'rejected'} "
                         f"'{acts[t['action']]['title']}'" + (f" — “{t['note']}”" if t['note'] else "") + ".")
        action = None
        if cur:
            a = acts[cur]
            conf = round(a["confidence"] * (0.9 ** rejections), 2)
            action = {"id": cur, "title": a["title"], "channel": a["channel"], "to": a["to"],
                      "draft": a["draft"], "confidence": conf, "needs_human": True}
            if trail:
                last = trail[-1]
                steps.append(f"So next: {a['title']} ("
                             + ("follow-up after approval" if last["decision"] == "approve"
                                else "alternative after rejection — confidence lowered") + ").")
        status = "done" if cur is None else ("pending" if not trail else
                                             ("revised" if trail[-1]["decision"] == "reject" else "next_step"))
        return {"id": pid, "pid": pid, **base, "reasoning": steps, "action": action, "status": status, "trail": trail,
                "memories_used": used, "queries": c.queries, "data_mode": c.mode,
                "confidence": action["confidence"] if action else None}

    def cards(self) -> dict:
        c = self._client()
        return {"cards": [self.card(p) for p in BUILDERS], "totals": totals(c), "data_mode": c.mode}

    def decide(self, pid: str, decision: str, action_id: str, note: str = "", draft: str = "") -> dict:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        card = self.card(pid)
        if not card["action"] or card["action"]["id"] != action_id:
            raise LookupError("stale card: refresh and decide on the current action")
        a = card["action"]
        text = (f"{'Approved' if decision == 'approve' else 'Rejected'} '{a['title']}' for {card['client']}" + (f" — note: {note}" if note else "")
                + f" [evidence: {', '.join(e['id'] for e in card['evidence'][:4])}]")
        m = self.mem.remember(
            text, source=f"approval:{pid}:{action_id}", confidence=0.95, origin="approval",
            label="human gate decision", namespace=f"case:{pid}", tags=[decision, card["client_code"], action_id],
            entities=[{"name": card["client"], "type": "client"}],
            refs={"decision": decision, "action": action_id, "note": note, "puzzle": pid})
        sent = None
        if decision == "approve":
            sent = {"at": int(time.time() * 1000), "puzzle": pid, "action": action_id, "channel": a["channel"],
                    "to": a["to"], "body": (draft or a["draft"]).strip(), "memory_id": m.id,
                    "note": "queued for Tom to send — this demo never sends email"}
            self.outbox.parent.mkdir(parents=True, exist_ok=True)
            with self.outbox.open("a") as f:
                f.write(json.dumps(sent) + "\n")
        return {"memory": {"id": m.id, "content": m.content}, "queued": sent, "card": self.card(pid)}

    def outbox_items(self) -> list[dict]:
        if not self.outbox.exists():
            return []
        return [json.loads(l) for l in self.outbox.read_text().splitlines() if l.strip()]


engine = WhyEngine()
