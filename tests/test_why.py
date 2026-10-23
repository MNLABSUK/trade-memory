"""Why cards: Zetaris evidence, H-MEM trail, and the human approval gate."""

import json

import pytest
from fastapi.testclient import TestClient

from trade_memory import why as why_mod
from trade_memory import zetaris_client as zc
from trade_memory.hmem import HMem


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETARIS_PASSWORD", "")
    client = zc.ZetarisClient(url="http://127.0.0.1:9", user="", password="")
    eng = why_mod.WhyEngine(client=client, mem=HMem(tmp_path / "hmem"), outbox=tmp_path / "outbox.jsonl")
    monkeypatch.setattr(why_mod, "engine", eng)
    return eng


def _ids(card):
    return {r["id"] for r in card["evidence"]}


def test_cards_cite_rows_and_totals(engine):
    out = engine.cards()
    assert out["totals"]["outstanding_gbp"] == pytest.approx(24686)
    cards = {c["pid"]: c for c in out["cards"]}
    assert set(cards) == {"P1", "P2", "P3", "P4", "P5"}
    assert {"INV-1043", "BL-0078", "C-010"} <= _ids(cards["P1"])
    assert {"C-001", "C-002"} <= _ids(cards["P2"])
    assert "JS-216" in _ids(cards["P3"])
    assert "JOB-518" in _ids(cards["P4"])
    assert "PO-MAT-77412" in json.dumps(cards["P4"]["evidence"])
    assert {"MSG-0011", "MSG-0012"} <= _ids(cards["P5"])
    for c in cards.values():
        assert c["action"]["needs_human"] is True
        assert 0 < c["confidence"] <= 1
        assert c["queries"] and c["reasoning"]
        assert c["memories_used"], c["pid"]


def test_outbox_empty_until_approve(engine):
    assert engine.outbox_items() == []
    c = engine.card("P1")
    res = engine.decide("P1", "approve", c["action"]["id"], note="ok")
    assert res["queued"] and len(engine.outbox_items()) == 1
    nxt = res["card"]
    assert nxt["action"]["id"] != c["action"]["id"]
    assert nxt["status"] == "next_step"


def test_reject_revises_and_lowers_confidence(engine):
    c = engine.card("P5")
    res = engine.decide("P5", "reject", c["action"]["id"], note="he never answers the phone")
    n = res["card"]
    assert n["action"]["id"] != c["action"]["id"] and n["status"] == "revised"
    assert n["confidence"] < c["confidence"]
    assert any("Rejected" in m["content"] for m in n["memories_used"])
    assert engine.outbox_items() == []


def test_stale_action_rejected(engine):
    with pytest.raises(LookupError):
        engine.decide("P2", "approve", "not-the-current-action")


def test_api_gate(engine):
    from trade_memory.app import app

    t = TestClient(app)
    assert t.get("/api/outbox").json()["items"] == []
    card = t.get("/api/why/p3").json()
    assert t.post("/api/why/P3/decide", json={"decision": "approve", "action_id": "nope"}).status_code == 409
    assert t.post("/api/why/P3/decide", json={"decision": "maybe", "action_id": card["action"]["id"]}).status_code == 400
    r = t.post("/api/why/P3/decide", json={"decision": "approve", "action_id": card["action"]["id"],
                                          "draft_text": "edited by Tom"})
    assert r.status_code == 200
    items = t.get("/api/outbox").json()["items"]
    assert len(items) == 1 and items[0]["body"] == "edited by Tom"
    json.dumps(t.get("/api/why").json())
    assert t.get("/api/why/P9").status_code == 404
