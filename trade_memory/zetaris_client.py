"""Zetaris client for the Halden & Rook demo data (fictional).

Talks to the Zetaris REST API through the UI proxy:
  POST {ZETARIS_URL}/api/auth/login              -> JWT + orgId
  POST {ZETARIS_URL}/api/proxy/sql-editor/sqls/run -> {"headers": [...], "data": [[...]]}

Env vars: ZETARIS_URL (default http://localhost:3000), ZETARIS_USER, ZETARIS_PASSWORD.
On the hackathon server the UI listens on 127.0.0.1:3000 only, so tunnel first:
  ssh -L 3000:127.0.0.1:3000 root@<server>

Registered sources: tm_ops.{jobs,invoices,job_sheets} (Postgres JDBC datasource) and
tm_files.{bank_lines,contacts,inbox} (Lightning CSV filestore tables).

If Zetaris is unreachable (or ZETARIS_OFFLINE=1), the same SQL runs against the local
demo_data CSVs loaded into in-memory SQLite, with tm_ops.x / tm_files.x mapped to tables.
Keep puzzle SQL portable (plain joins, string compares); booleans/dates are normalised in Python.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo_data"

LOCAL_TABLES = {
    "tm_ops.jobs": "ops_db/jobs.csv",
    "tm_ops.invoices": "ops_db/invoices.csv",
    "tm_ops.job_sheets": "ops_db/job_sheets.csv",
    "tm_files.bank_lines": "bank_feed/bank_lines.csv",
    "tm_files.contacts": "crm_contacts/contacts.csv",
    "tm_files.inbox": "inbox_export/inbox.jsonl",
}
NUMERIC_COLS = {"net_gbp", "vat_gbp", "total_gbp", "amount_paid_gbp", "quoted_value_gbp",
                "amount_gbp", "running_balance_gbp"}


class ZetarisError(RuntimeError):
    pass


class ZetarisClient:
    def __init__(self, url: str | None = None, user: str | None = None,
                 password: str | None = None, offline: bool | None = None,
                 demo_dir: Path | None = None, timeout: float = 120):
        self.url = (url or os.environ.get("ZETARIS_URL", "http://localhost:3000")).rstrip("/")
        self.user = user or os.environ.get("ZETARIS_USER", "")
        self._password = password or os.environ.get("ZETARIS_PASSWORD", "")
        self.demo_dir = Path(demo_dir or DEMO_DIR)
        self.timeout = timeout
        self._token: str | None = None
        self._org: str | None = None
        self._db: sqlite3.Connection | None = None
        if offline is None:
            offline = os.environ.get("ZETARIS_OFFLINE") == "1" or not (self.user and self._password)
        self.mode = "offline" if offline else "zetaris"

    def __repr__(self) -> str:  # never show the password
        return f"ZetarisClient(url={self.url!r}, user={self.user!r}, mode={self.mode!r})"

    # ---- REST ----------------------------------------------------------------------
    def _post(self, path: str, body: dict, headers: dict | None = None) -> Any:
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            raise ZetarisError(f"HTTP {e.code} on {path}: {e.read().decode(errors='replace')[:300]}") from e

    def login(self) -> None:
        out = self._post("/api/auth/login", {"username": self.user, "password": self._password})
        text = json.dumps(out)
        tok = re.search(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", text)
        org = re.search(r'"orgId"\s*:\s*"?(\d+)', text)
        if not tok or not org:
            raise ZetarisError("login returned no token/orgId")
        self._token, self._org = tok.group(0), org.group(1)

    def _remote(self, sql: str, limit: int) -> list[dict]:
        if not self._token:
            self.login()
        body = {"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit}
        hdr = lambda: {"Authorization": f"Bearer {self._token}", "X-Org-ID": str(self._org),
                       "X-Request-ID": str(uuid.uuid4())}
        try:
            out = self._post("/api/proxy/sql-editor/sqls/run", body, hdr())
        except ZetarisError as e:
            if "HTTP 401" not in str(e):
                raise
            self.login()
            out = self._post("/api/proxy/sql-editor/sqls/run", body, hdr())
        if not isinstance(out, dict) or "data" not in out:
            raise ZetarisError(f"query failed: {str(out)[:300]}")
        cols = out.get("headers") or []
        return [dict(zip(cols, row)) for row in out["data"]]

    # ---- offline -------------------------------------------------------------------
    def _local_db(self) -> sqlite3.Connection:
        if self._db:
            return self._db
        db = sqlite3.connect(":memory:", check_same_thread=False)  # read-only, used from FastAPI threadpool
        for name, rel in LOCAL_TABLES.items():
            p = self.demo_dir / rel
            if p.suffix == ".jsonl":
                rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
                cols: list[str] = []
                for r in rows:
                    cols += [k for k in r if k not in cols]
                rows = [{k: (";".join(v) if isinstance(v, list) else
                             (str(v).lower() if isinstance(v, bool) else v)) for k, v in r.items()}
                        for r in rows]
            else:
                with p.open(newline="") as f:
                    rd = csv.DictReader(f)
                    cols, rows = list(rd.fieldnames or []), list(rd)
            t = name.replace(".", "_")
            db.execute(f'CREATE TABLE {t} ({", ".join(f"{c} {"REAL" if c in NUMERIC_COLS else "TEXT"}" for c in cols)})')
            db.executemany(f'INSERT INTO {t} VALUES ({",".join("?" * len(cols))})',
                           [[(r.get(c) if r.get(c) != "" else None) for c in cols] for r in rows])
        self._db = db
        return db

    def _offline(self, sql: str, limit: int) -> list[dict]:
        cur = self._local_db().execute(re.sub(r"\btm_(ops|files)\.", r"tm_\1_", sql))
        cols = [d[0] for d in cur.description or []]
        return [dict(zip(cols, r)) for r in cur.fetchmany(limit)]

    # ---- public --------------------------------------------------------------------
    def query(self, sql: str, limit: int = 1000) -> list[dict]:
        if self.mode == "zetaris":
            try:
                return self._remote(sql, limit)
            except (urllib.error.URLError, OSError) as e:
                if isinstance(e, urllib.error.HTTPError):
                    raise
                self.mode = "offline"  # Zetaris unreachable: fall back to local CSVs
        return self._offline(sql, limit)


def _s(v: Any) -> str:
    return "" if v is None else str(v)


def _true(v: Any) -> bool:
    return _s(v).strip().lower() in {"true", "1", "t", "yes"}


def _num(v: Any) -> float:
    return float(v) if v not in (None, "") else 0.0


# ---- the five demo puzzles ---------------------------------------------------------
def p1_unmatched_receipt(c: ZetarisClient, invoice_id: str = "INV-1043") -> dict:
    """P1 (Kestrel): match an unpaid invoice to a bank credit by amount, plus the payer contact."""
    rows = c.query(f"""
        SELECT i.invoice_id, i.client_code, i.total_gbp, i.issue_date, b.bank_line_id, b.date,
               b.amount_gbp, b.counterparty, b.reference
        FROM tm_ops.invoices i JOIN tm_files.bank_lines b
          ON CAST(b.amount_gbp AS DECIMAL(10,2)) = CAST(i.total_gbp AS DECIMAL(10,2))
         AND b.direction = 'credit'
        WHERE i.invoice_id = '{invoice_id}'""")
    rows = [r for r in rows if _s(r["date"])[:10] >= _s(r["issue_date"])[:10]]
    payer = c.query("SELECT contact_id, name, role, email, notes FROM tm_files.contacts "
                    f"WHERE client_code = '{rows[0]['client_code']}'") if rows else []
    parent = [p for p in payer if "parent" in _s(p["role"]).lower() or "parent" in _s(p["notes"]).lower()]
    return {"puzzle": "P1", "matches": rows, "payer_contacts": parent,
            "verdict": "do_not_chase" if rows else "chase"}


def p2_bounced_contact(c: ZetarisClient, client_code: str = "LARK") -> dict:
    """P2 (Larkfield): bounced contact + bounce messages, and the live alternative."""
    contacts = c.query(f"SELECT contact_id, name, email, email_bounced, bounce_since FROM tm_files.contacts "
                       f"WHERE client_code = '{client_code}'")
    bounced = [x for x in contacts if _true(x["email_bounced"])]
    alt = [x for x in contacts if not _true(x["email_bounced"]) and _s(x["email"]).startswith("finance@")]
    msgs = c.query(f"SELECT message_id, timestamp, summary, bounce FROM tm_files.inbox "
                   f"WHERE client_code = '{client_code}' ORDER BY message_id")
    bounces = [m["message_id"] for m in msgs if _true(m["bounce"])]
    return {"puzzle": "P2", "bounced": bounced, "bounce_messages": bounces, "resend_to": alt}


def p3_dispute_vs_jobsheet(c: ZetarisClient, invoice_id: str = "INV-1015") -> dict:
    """P3 (Copperbeech): closed snag job sheets for the invoiced job, and the balance outstanding."""
    rows = c.query(f"""
        SELECT i.invoice_id, i.total_gbp, i.amount_paid_gbp, s.job_sheet_id, s.snag_status,
               s.snag_closed_date, s.photo_ref, s.signed_off_by
        FROM tm_ops.invoices i JOIN tm_ops.job_sheets s ON s.job_id = i.job_id
        WHERE i.invoice_id = '{invoice_id}' AND s.sheet_type = 'snag'""")
    closed = [r for r in rows if _s(r["snag_status"]) == "closed" and r["photo_ref"]]
    bal = _num(rows[0]["total_gbp"]) - _num(rows[0]["amount_paid_gbp"]) if rows else None
    return {"puzzle": "P3", "closed_snags": closed, "balance_gbp": bal}


def p4_missing_po(c: ZetarisClient) -> dict:
    """P4 (Mosswood): invoices without a PO whose job carries one."""
    rows = c.query("""
        SELECT i.invoice_id, i.status, i.notes, j.job_id, j.po_number AS job_po
        FROM tm_ops.invoices i JOIN tm_ops.jobs j ON j.job_id = i.job_id
        WHERE (i.po_number IS NULL OR i.po_number = '') AND j.po_number IS NOT NULL AND j.po_number <> ''""")
    ap = c.query("SELECT contact_id, preferred_channel, notes FROM tm_files.contacts WHERE role = 'Accounts payable'")
    return {"puzzle": "P4", "reissue": rows, "ap_contacts": ap}


def p5_broken_promises(c: ZetarisClient, client_code: str = "BRIN", today: str = "2026-10-22") -> dict:
    """P5 (Brindle & Oak): promised dates that passed with no matching bank credit."""
    msgs = c.query(f"SELECT message_id, timestamp, promise, related_invoices FROM tm_files.inbox "
                   f"WHERE client_code = '{client_code}' ORDER BY message_id")
    promises = [m for m in msgs if _s(m["promise"]).strip() not in ("", "None", "null")]
    inv_ids = sorted({i for m in promises for i in _s(m["related_invoices"]).split(";") if i})
    invs = c.query("SELECT invoice_id, total_gbp, amount_paid_gbp FROM tm_ops.invoices WHERE invoice_id IN ("
                   + ",".join(f"'{i}'" for i in inv_ids) + ")") if inv_ids else []
    credits = c.query("SELECT bank_line_id, date, amount_gbp FROM tm_files.bank_lines WHERE direction = 'credit'")
    totals = {round(_num(i["total_gbp"]), 2) for i in invs}
    first = min((_s(m["timestamp"])[:10] for m in promises), default=today)
    paid = [b for b in credits if round(_num(b["amount_gbp"]), 2) in totals and _s(b["date"])[:10] >= first]
    broken = [m for m in promises if re.search(r"\d{4}-\d{2}-\d{2}", _s(m["promise"]))
              and re.search(r"\d{4}-\d{2}-\d{2}", _s(m["promise"])).group(0) < today]
    contact = c.query(f"SELECT contact_id, name, phone, preferred_channel, notes FROM tm_files.contacts "
                      f"WHERE client_code = '{client_code}'")
    return {"puzzle": "P5", "broken_promises": broken if not paid else [], "invoices": invs,
            "bank_credits": paid, "contact": contact}


PUZZLES = {"P1": p1_unmatched_receipt, "P2": p2_bounced_contact, "P3": p3_dispute_vs_jobsheet,
           "P4": p4_missing_po, "P5": p5_broken_promises}


def solve_all(c: ZetarisClient | None = None) -> dict:
    c = c or ZetarisClient()
    return {k: f(c) for k, f in PUZZLES.items()}


def query(sql: str, limit: int = 1000) -> list[dict]:
    """Module-level convenience: run SQL with env-configured client (falls back offline)."""
    return ZetarisClient().query(sql, limit)


if __name__ == "__main__":
    import sys
    cl = ZetarisClient()
    if len(sys.argv) > 1:
        print(json.dumps(cl.query(" ".join(sys.argv[1:])), indent=2, default=str))
    else:
        print(json.dumps(solve_all(cl), indent=2, default=str))
    print(f"# mode: {cl.mode}", file=sys.stderr)
