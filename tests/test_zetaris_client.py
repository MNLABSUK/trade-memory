"""Offline tests for trade_memory.zetaris_client (no network, uses demo_data CSVs)."""
import os
import pytest
from trade_memory.zetaris_client import ZetarisClient, solve_all


@pytest.fixture()
def c():
    return ZetarisClient(offline=True)


def test_counts(c):
    for t, n in {"tm_ops.jobs": 22, "tm_ops.invoices": 22, "tm_ops.job_sheets": 19,
                 "tm_files.bank_lines": 83, "tm_files.contacts": 10, "tm_files.inbox": 15}.items():
        assert c.query(f"SELECT count(*) AS n FROM {t}")[0]["n"] == n


def test_puzzles(c):
    r = solve_all(c)
    p1 = r["P1"]
    assert p1["verdict"] == "do_not_chase"
    assert [m["bank_line_id"] for m in p1["matches"]] == ["BL-0078"]
    assert [x["contact_id"] for x in p1["payer_contacts"]] == ["C-010"]
    assert [x["contact_id"] for x in r["P2"]["bounced"]] == ["C-001"]
    assert r["P2"]["bounce_messages"] == ["MSG-0002", "MSG-0004", "MSG-0006"]
    assert [x["contact_id"] for x in r["P2"]["resend_to"]] == ["C-002"]
    assert [x["job_sheet_id"] for x in r["P3"]["closed_snags"]] == ["JS-216"]
    assert r["P3"]["balance_gbp"] == 9200
    assert [(x["invoice_id"], x["job_po"]) for x in r["P4"]["reissue"]] == [("INV-1018", "PO-MAT-77412")]
    assert [m["message_id"] for m in r["P5"]["broken_promises"]] == ["MSG-0011", "MSG-0012"]
    assert r["P5"]["bank_credits"] == []


def test_unreachable_falls_back(monkeypatch):
    cl = ZetarisClient(url="http://127.0.0.1:9", user="u", password="s3cret-xyz", timeout=2)
    assert cl.mode == "zetaris"
    assert cl.query("SELECT count(*) AS n FROM tm_ops.invoices")[0]["n"] == 22
    assert cl.mode == "offline"
    assert "s3cret-xyz" not in repr(cl)


@pytest.mark.skipif(not os.environ.get("ZETARIS_PASSWORD"), reason="live Zetaris not configured")
def test_live_p1():
    cl = ZetarisClient()
    r = cl.query("SELECT i.invoice_id, b.bank_line_id FROM tm_ops.invoices i JOIN tm_files.bank_lines b "
                 "ON CAST(b.amount_gbp AS DECIMAL(10,2)) = i.total_gbp AND b.direction = 'credit' "
                 "WHERE i.invoice_id = 'INV-1043'")
    assert cl.mode == "zetaris" and {"invoice_id": "INV-1043", "bank_line_id": "BL-0078"} in r
