#!/usr/bin/env python3
"""Generate fictional demo data for Halden & Rook Electrical Ltd (Leeds).

All businesses, people, addresses and emails are invented (MN Labs demo).
Deterministic: fixed RNG seed and fixed reference date, so re-runs are identical.

Outputs (under demo_data/, one folder per Zetaris source):
  ops_db/        schema.sql, seed.sql (Postgres) + invoices.csv, jobs.csv, job_sheets.csv
  bank_feed/     bank_lines.csv  (90 days, messy references)
  crm_contacts/  contacts.csv
  inbox_export/  inbox.jsonl
  puzzles.json   the five planted puzzles with expected answers + evidence ids

Usage: python3 scripts/make_demo_data.py [--out demo_data]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20261022
TODAY = date(2026, 10, 22)  # demo "today" (Thursday); Friday chase is 23 Oct
FIRM = "Halden & Rook Electrical Ltd"

CLIENTS = {
    "LARK": "Larkfield Lettings",
    "COPP": "Copperbeech Dental Group",
    "MOSS": "Mosswood Academy Trust",
    "BRIN": "Brindle & Oak Cafés",
    "KEST": "Kestrel Self Storage",
}
ELECTRICIANS = ["Dan Ashby", "Rhys Calder", "Imogen Teale", "Wes Okafor", "Lena Marsh", "Callum Pryor"]

rng = random.Random(SEED)
d = lambda s: date.fromisoformat(s)


def build():
    jobs, invoices, sheets, bank, contacts, inbox = [], [], [], [], [], []
    inv_no = [1000]
    job_no = [500]
    js_no = [200]

    def add_job(client, title, site, start, done, value, po=None):
        job_no[0] += 1
        jid = f"JOB-{job_no[0]}"
        jobs.append(dict(job_id=jid, client_code=client, client_name=CLIENTS[client], title=title, site_address=site,
                         lead_electrician=rng.choice(ELECTRICIANS), start_date=start.isoformat(),
                         completed_date=done.isoformat() if done else "", quoted_value_gbp=f"{value:.2f}",
                         po_number=po or ""))
        return jid

    def add_sheet(jid, visit, kind, notes, snag_status="", snag_closed="", photo="", signed_by=""):
        js_no[0] += 1
        sid = f"JS-{js_no[0]}"
        sheets.append(dict(job_sheet_id=sid, job_id=jid, visit_date=visit.isoformat(), sheet_type=kind,
                           electrician=next(j["lead_electrician"] for j in jobs if j["job_id"] == jid),
                           notes=notes, snag_status=snag_status, snag_closed_date=snag_closed,
                           photo_ref=photo, signed_off_by=signed_by))
        return sid

    def add_inv(client, jid, issued, net, terms=30, po_on_invoice="", status="sent", paid=0.0, ref_note=""):
        inv_no[0] += 1
        iid = f"INV-{inv_no[0]}"
        vat = round(net * 0.2, 2)
        invoices.append(dict(invoice_id=iid, client_code=client, client_name=CLIENTS[client], job_id=jid,
                             issue_date=issued.isoformat(), due_date=(issued + timedelta(days=terms)).isoformat(),
                             net_gbp=f"{net:.2f}", vat_gbp=f"{vat:.2f}", total_gbp=f"{net + vat:.2f}",
                             amount_paid_gbp=f"{paid:.2f}", status=status, po_number=po_on_invoice, notes=ref_note))
        return iid

    # --- 1. Larkfield Lettings: 14 small jobs, batch payments w/ own remittance ref, accounts@ bounces
    lark_sites = ["14 Brudenell Mount", "3 Kirkstall Rise", "27 Headingley Grove", "9 Meanwood Walk",
                  "41 Chapel Allerton Row", "6 Burley Terrace", "18 Armley Lane", "2 Hyde Park Close",
                  "55 Roundhay View", "11 Woodhouse Court", "7 Beeston Hill", "30 Horsforth Gate",
                  "16 Otley Road Flat 2", "22 Moortown Crescent"]
        
    lark_tasks = ["EICR", "Smoke alarm swap", "Consumer unit fault", "Extractor fan fit", "Socket repair",
                  "Outside light", "Landlord EICR remedials"]
    lark_invs = []
    for i, site in enumerate(lark_sites):
        start = d("2026-07-06") + timedelta(days=i * 6 + rng.randint(0, 2))
        net = rng.choice([145, 180, 210, 240, 265, 320, 385])
        jid = add_job("LARK", rng.choice(lark_tasks), site + ", Leeds", start, start, net)
        add_sheet(jid, start, "completion", "Work complete, tenant present", signed_by="Tenant")
        lark_invs.append(add_inv("LARK", jid, start + timedelta(days=1), net))
    # first 6 paid in one batch ~45 days later with Larkfield's own remittance ref
    batch1 = lark_invs[:6]
    tot1 = sum(float(i["total_gbp"]) for i in invoices if i["invoice_id"] in batch1)
    for i in invoices:
        if i["invoice_id"] in batch1:
            i["status"], i["amount_paid_gbp"] = "paid", i["total_gbp"]
    bank.append(dict(date="2026-09-04", description="FPS CR LARKFIELD LETT REMIT LL-PAY-0931", amount_gbp=f"{tot1:.2f}",
                     direction="credit", counterparty="LARKFIELD LETTINGS LT", reference="LL-PAY-0931"))
    lark_unpaid = lark_invs[6:]

    # --- 2. Copperbeech: £18,400 rewire, 50% paid, balance disputed over a snag closed 2 Oct
    cj = add_job("COPP", "Full rewire, Chapeltown practice", "Copperbeech Dental, 88 Harehills Road, Leeds",
                 d("2026-08-10"), d("2026-09-18"), 18400)
    add_sheet(cj, d("2026-09-18"), "completion", "Rewire complete; snag: surgery 3 dental chair spur not on dedicated RCBO",
              snag_status="open", signed_by="Practice manager")
    copp_snag = add_sheet(cj, d("2026-10-02"), "snag", "Surgery 3 chair spur moved to dedicated RCBO, tested, cert updated",
                          snag_status="closed", snag_closed="2026-10-02", photo="photos/JS-snag-surgery3-rcbo.jpg",
                          signed_by="R. Okonjo (practice manager)")
    copp_inv = add_inv("COPP", cj, d("2026-09-19"), 18400 / 1.2, status="part_paid", paid=9200.00,
                       ref_note="Total incl VAT £18,400; 50% stage payment received")
    bank.append(dict(date="2026-08-14", description="BACS CR COPPERBEECH DENTAL STAGE1", amount_gbp="9200.00",
                     direction="credit", counterparty="COPPERBEECH DENTAL GR", reference="STAGE1 REWIRE"))
    # two smaller paid jobs
    for site, net in [("Copperbeech Dental, 4 Roundhay Parade, Leeds", 420), ("Copperbeech Dental, 19 Otley Old Rd, Leeds", 610)]:
        s = d("2026-07-20") + timedelta(days=rng.randint(0, 20))
        jid = add_job("COPP", "Emergency lighting test", site, s, s, net)
        iid = add_inv("COPP", jid, s, net, status="paid", paid=net * 1.2)
        bank.append(dict(date=(s + timedelta(days=28)).isoformat(), description=f"BACS CR COPPERBEECH {iid}",
                         amount_gbp=f"{net * 1.2:.2f}", direction="credit", counterparty="COPPERBEECH DENTAL GR", reference=iid))

    # --- 3. Mosswood Academy Trust: PO-driven; invoice rejected, PO missing on invoice
    mj = add_job("MOSS", "LED lighting upgrade, sports hall", "Mosswood Academy, Stonegate Lane, Leeds",
                 d("2026-08-24"), d("2026-08-28"), 6850, po="PO-MAT-77412")
    add_sheet(mj, d("2026-08-28"), "completion", "48 high-bay LEDs fitted, emergency circuit tested", signed_by="Site manager")
    moss_inv = add_inv("MOSS", mj, d("2026-09-01"), 6850, status="rejected", po_on_invoice="",
                       ref_note="Rejected by trust AP portal 2026-09-08: no PO on invoice")
    mj2 = add_job("MOSS", "PAT testing, main block", "Mosswood Academy, Stonegate Lane, Leeds",
                  d("2026-07-14"), d("2026-07-15"), 940, po="PO-MAT-76980")
    mi2 = add_inv("MOSS", mj2, d("2026-07-16"), 940, po_on_invoice="PO-MAT-76980", status="paid", paid=1128.00)
    bank.append(dict(date="2026-08-13", description="BACS CR MOSSWOOD ACAD TRUST PO-MAT-76980", amount_gbp="1128.00",
                     direction="credit", counterparty="MOSSWOOD ACADEMY TR", reference="PO-MAT-76980"))

    # --- 4. Brindle & Oak Cafés: pays when phoned, ignores email; broke two "Friday" promises
    bj = add_job("BRIN", "Kitchen circuits + new commercial oven supply", "Brindle & Oak, 12 Call Lane, Leeds",
                 d("2026-08-27"), d("2026-08-28"), 2450)
    add_sheet(bj, d("2026-08-28"), "completion", "Oven supply 32A radial installed and tested", signed_by="Owner")
    brin_inv = add_inv("BRIN", bj, d("2026-08-31"), 2450, terms=14)
    bj0 = add_job("BRIN", "Fault find, café lighting", "Brindle & Oak, 3 Kirkgate, Leeds", d("2026-06-30"), d("2026-06-30"), 290)
    bi0 = add_inv("BRIN", bj0, d("2026-07-01"), 290, terms=14, status="paid", paid=348.00,
                  ref_note="Paid after phone call 2026-07-24")
    bank.append(dict(date="2026-07-24", description="CARD CR BRINDLE OAK", amount_gbp="348.00", direction="credit",
                     counterparty="BRINDLE AND OAK", reference="CAFE"))

    # --- 5. Kestrel Self Storage: paid £2,160 but reference doesn't match the invoice
    kj = add_job("KEST", "Gate access + yard floodlights", "Kestrel Self Storage, Unit 4 Stourton Ind Est, Leeds",
                 d("2026-09-07"), d("2026-09-09"), 1800)
    add_sheet(kj, d("2026-09-09"), "completion", "2 floodlights + gate supply; signed off", signed_by="Site manager")
    while inv_no[0] < 1042:
        inv_no[0] += 1  # keep the plan's INV-1043 id for the demo script
    kest_inv = add_inv("KEST", kj, d("2026-09-10"), 1800, status="sent")
    bank.append(dict(date="2026-10-06", description="FPS CR KSS LTD STORAGE PMT 7781", amount_gbp="2160.00",
                     direction="credit", counterparty="KSS OPERATIONS LTD", reference="7781"))

    # --- noise bank lines (debits + unrelated credits), 90 days back from TODAY
    start = TODAY - timedelta(days=90)
    debit_payees = [("CEF LEEDS", "TRADE ACC"), ("SCREWFIX", "CARD"), ("EDMUNDSON ELEC", "ACC 4471"),
                    ("BP FUEL", "CARD"), ("HMRC VAT", "VAT Q3"), ("VAN LEASE CO", "DD"), ("NAPIT", "SUBS")]
    for n in range(70):
        day = start + timedelta(days=rng.randint(0, 89))
        payee, ref = rng.choice(debit_payees)
        amt = round(rng.uniform(18, 1400), 2)
        bank.append(dict(date=day.isoformat(), description=f"{'DD' if ref == 'DD' else 'CARD'} {payee} {ref}",
                         amount_gbp=f"-{amt:.2f}", direction="debit", counterparty=payee, reference=ref))
    for n in range(6):  # cash/walk-in credits not tied to these clients
        day = start + timedelta(days=rng.randint(0, 89))
        amt = rng.choice([85, 120, 150, 195])
        bank.append(dict(date=day.isoformat(), description=f"FPS CR {rng.choice(['J SMITHSON', 'A KHAN', 'P DOYLE', 'M RILEY'])} ELEC WORK",
                         amount_gbp=f"{amt:.2f}", direction="credit", counterparty="PRIVATE", reference="ELEC WORK"))
    bank.sort(key=lambda r: r["date"])
    bal = 38250.00
    for i, r in enumerate(bank, 1):
        bal += float(r["amount_gbp"])
        r["bank_line_id"] = f"BL-{i:04d}"
        r["running_balance_gbp"] = f"{bal:.2f}"

    # --- CRM contacts
    def c(cid, client, name, role, email, phone, channel, bounced="false", bounce_since="", notes=""):
        contacts.append(dict(contact_id=cid, client_code=client, client_name=CLIENTS[client], name=name, role=role,
                             email=email, phone=phone, preferred_channel=channel, email_bounced=bounced,
                             bounce_since=bounce_since, notes=notes))
    c("C-001", "LARK", "Accounts team", "Accounts payable", "accounts@larkfield-lettings.example", "0113 496 0101",
      "email", "true", "2026-09-03", "Shared mailbox; returning 550 since early Sept")
    c("C-002", "LARK", "Nadia Ferrow", "Finance officer", "finance@larkfield-lettings.example", "0113 496 0102",
      "email", notes="Took over AP Sept 2026; remittance refs LL-PAY-xxxx")
    c("C-003", "LARK", "Gareth Lowe", "Property manager", "gareth@larkfield-lettings.example", "07700 900101", "phone")
    c("C-004", "COPP", "Ruth Okonjo", "Practice manager", "ruth.okonjo@copperbeech-dental.example", "0113 496 0201", "email")
    c("C-005", "COPP", "Simon Arkwright", "Group finance", "finance@copperbeech-dental.example", "0113 496 0202", "email",
      notes="Holding balance pending snag")
    c("C-006", "MOSS", "Trust AP", "Accounts payable", "ap@mosswood-trust.example", "0113 496 0301", "portal",
      notes="Invoices must quote PO number; upload via supplier portal")
    c("C-007", "MOSS", "Helen Pike", "Site manager", "h.pike@mosswood-trust.example", "0113 496 0302", "email")
    c("C-008", "BRIN", "Jonty Brindle", "Owner", "jonty@brindleandoak.example", "07700 900401", "phone",
      notes="Rarely reads email; pays same day when phoned")
    c("C-009", "KEST", "Asha Merriman", "Site manager", "asha@kestrel-storage.example", "07700 900501", "email")
    c("C-010", "KEST", "KSS Operations accounts", "Accounts payable (parent co.)", "ap@kss-operations.example",
      "0113 496 0502", "email", notes="Parent company pays supplier invoices; uses own payment run numbers")

    # --- inbox export
    def m(when, ch, client, frm, to, subj, summary, **extra):
        inbox.append(dict(message_id=f"MSG-{len(inbox) + 1:04d}", timestamp=when, channel=ch, client_code=client,
                          from_addr=frm, to_addr=to, subject=subj, summary=summary, **extra))
    tom = "tom@haldenrook.example"
    first_lark = lark_unpaid[0]
    for when in ["2026-09-11T15:20:00+01:00", "2026-09-25T15:05:00+01:00", "2026-10-09T15:40:00+01:00"]:
        m(when, "email", "LARK", tom, "accounts@larkfield-lettings.example", f"Overdue: {first_lark} and others",
          "Friday chase for unpaid Larkfield invoices", promise=None, related_invoices=lark_unpaid)
        m(when.replace(":00+", ":30+", 1), "email", "LARK", "mailer-daemon@haldenrook.example", tom,
          "Undeliverable: Overdue", "Delivery failed: 550 mailbox unavailable accounts@larkfield-lettings.example",
          bounce=True, related_invoices=lark_unpaid)
    m("2026-09-04T10:12:00+01:00", "email", "LARK", "finance@larkfield-lettings.example", tom,
      "Remittance LL-PAY-0931", "Nadia: payment run LL-PAY-0931 covers six invoices; please use finance@ going forward",
      related_invoices=batch1)
    m("2026-10-05T09:31:00+01:00", "email", "COPP", "finance@copperbeech-dental.example", tom,
      f"RE: {copp_inv} balance", "Simon: balance on hold until surgery 3 chair spur snag is fixed", claim="snag_open",
      related_invoices=[copp_inv])
    m("2026-09-08T11:02:00+01:00", "email", "MOSS", "ap@mosswood-trust.example", tom, f"Invoice {moss_inv} rejected",
      "Trust AP portal rejected invoice: no purchase order number quoted", related_invoices=[moss_inv])
    m("2026-09-18T15:10:00+01:00", "email", "BRIN", tom, "jonty@brindleandoak.example", f"{brin_inv} overdue",
      "Reminder email, no reply", related_invoices=[brin_inv])
    m("2026-09-25T16:02:00+01:00", "whatsapp", "BRIN", "07700 900401", tom, "",
      "Jonty: sorry, will pay Friday", promise="pay by 2026-10-02", related_invoices=[brin_inv])
    m("2026-10-09T15:48:00+01:00", "whatsapp", "BRIN", "07700 900401", tom, "",
      "Jonty: mad week, definitely this Friday", promise="pay by 2026-10-16", related_invoices=[brin_inv])
    m("2026-10-16T16:30:00+01:00", "email", "BRIN", tom, "jonty@brindleandoak.example", f"{brin_inv} still unpaid",
      "Second email reminder after missed promise, no reply", related_invoices=[brin_inv])
    m("2026-10-12T14:00:00+01:00", "email", "KEST", tom, "asha@kestrel-storage.example", f"{kest_inv} overdue",
      "Chase sent to site manager", related_invoices=[kest_inv])
    m("2026-10-12T16:45:00+01:00", "email", "KEST", "asha@kestrel-storage.example", tom, f"RE: {kest_inv} overdue",
      "Asha: our parent co. KSS Operations pays suppliers, think it went last week", related_invoices=[kest_inv])
    inbox.sort(key=lambda r: r["timestamp"])

    kest_bl = next(b["bank_line_id"] for b in bank if b["reference"] == "7781")
    puzzles = [
        dict(id="P1", client="Kestrel Self Storage", title="Unmatched £2,160 receipt",
             sources=["bank_feed", "ops_db", "crm_contacts"],
             expected=f"Do not chase: {kest_bl} (£2,160, ref 7781, KSS OPERATIONS LTD) matches {kest_inv} total £2,160 "
                      "by amount within date window; KSS Operations is Kestrel's paying parent (C-010).",
             evidence=[kest_bl, kest_inv, "C-010"]),
        dict(id="P2", client="Larkfield Lettings", title="Bounced accounts@ contact",
             sources=["crm_contacts", "inbox_export"],
             expected="accounts@ has bounced 3x since Sept; re-send chase for unpaid invoices to finance@ (Nadia Ferrow).",
             evidence=["C-001", "C-002"] + [x["message_id"] for x in inbox if x.get("bounce")]),
        dict(id="P3", client="Copperbeech Dental Group", title="Dispute vs job sheet evidence",
             sources=["ops_db.job_sheets", "ops_db.invoices", "inbox_export"],
             expected=f"Email (5 Oct) claims snag open, but {copp_snag} closed it 2 Oct with photo and sign-off; "
                      f"chase £9,200 balance on {copp_inv} citing {copp_snag}.",
             evidence=[copp_snag, copp_inv]),
        dict(id="P4", client="Mosswood Academy Trust", title="Missing PO on invoice",
             sources=["ops_db.invoices", "ops_db.jobs", "crm_contacts"],
             expected=f"{moss_inv} rejected for no PO; job {mj} carries PO-MAT-77412; reissue with PO via portal.",
             evidence=[moss_inv, mj, "C-006"]),
        dict(id="P5", client="Brindle & Oak Cafés", title="Broken 'Friday' promises",
             sources=["inbox_export", "crm_contacts", "bank_feed"],
             expected=f"Two missed 'Friday' promises (2 Oct, 16 Oct), emails ignored, no bank credit; phone Jonty, don't email.",
             evidence=[brin_inv, "C-008"] + [x["message_id"] for x in inbox if x.get("promise")]),
    ]
    return dict(jobs=jobs, invoices=invoices, job_sheets=sheets, bank=bank, contacts=contacts, inbox=inbox,
                puzzles=puzzles)


def write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


SCHEMA = """-- Halden & Rook Electrical demo ops_db (fictional)
DROP TABLE IF EXISTS job_sheets; DROP TABLE IF EXISTS invoices; DROP TABLE IF EXISTS jobs;
CREATE TABLE jobs (job_id text PRIMARY KEY, client_code text, client_name text, title text, site_address text,
  lead_electrician text, start_date date, completed_date date, quoted_value_gbp numeric(10,2), po_number text);
CREATE TABLE invoices (invoice_id text PRIMARY KEY, client_code text, client_name text, job_id text REFERENCES jobs,
  issue_date date, due_date date, net_gbp numeric(10,2), vat_gbp numeric(10,2), total_gbp numeric(10,2),
  amount_paid_gbp numeric(10,2), status text, po_number text, notes text);
CREATE TABLE job_sheets (job_sheet_id text PRIMARY KEY, job_id text REFERENCES jobs, visit_date date, sheet_type text,
  electrician text, notes text, snag_status text, snag_closed_date date, photo_ref text, signed_off_by text);
"""


def sql_val(v):
    if v == "" or v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo_data")
    out = Path(ap.parse_args().out)
    data = build()
    write_csv(out / "ops_db/jobs.csv", data["jobs"])
    write_csv(out / "ops_db/invoices.csv", data["invoices"])
    write_csv(out / "ops_db/job_sheets.csv", data["job_sheets"])
    (out / "ops_db/schema.sql").write_text(SCHEMA, encoding="utf-8")
    lines = ["BEGIN;"]
    for table in ("jobs", "invoices", "job_sheets"):
        for r in data[table]:
            lines.append(f"INSERT INTO {table} ({', '.join(r)}) VALUES ({', '.join(sql_val(v) for v in r.values())});")
    lines.append("COMMIT;")
    (out / "ops_db/seed.sql").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cols = ["bank_line_id", "date", "description", "amount_gbp", "direction", "counterparty", "reference", "running_balance_gbp"]
    write_csv(out / "bank_feed/bank_lines.csv", [{k: r[k] for k in cols} for r in data["bank"]])
    write_csv(out / "crm_contacts/contacts.csv", data["contacts"])
    (out / "inbox_export").mkdir(parents=True, exist_ok=True)
    with (out / "inbox_export/inbox.jsonl").open("w", encoding="utf-8") as f:
        for r in data["inbox"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "puzzles.json").write_text(json.dumps(dict(firm=FIRM, today=TODAY.isoformat(), seed=SEED,
                                                      puzzles=data["puzzles"]), indent=2, ensure_ascii=False) + "\n")
    for k in ("jobs", "invoices", "job_sheets", "bank", "contacts", "inbox"):
        print(f"{k}: {len(data[k])}")


if __name__ == "__main__":
    main()
