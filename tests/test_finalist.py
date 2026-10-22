"""Finalist tests: digest, placeholder scrub, dry-run contact, version."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trade_memory import __version__
from trade_memory.app import app
from trade_memory.dry_run import propose as dry_run_propose
from trade_memory.memory import MemoryStore
from trade_memory.models import Chase, Client, Job
from trade_memory.nebius_client import scrub_placeholders


@pytest.fixture()
def tmp_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MemoryStore:
    path = tmp_path / "memory.json"
    store = MemoryStore(path=path)
    import trade_memory.app as app_mod
    import trade_memory.memory as mem_mod

    monkeypatch.setattr(mem_mod, "store", store)
    monkeypatch.setattr(app_mod, "store", store)
    return store


@pytest.fixture()
def client(tmp_store: MemoryStore) -> TestClient:
    return TestClient(app)


def test_version_bumped():
    assert __version__ == "0.3.0"


def test_digest_get(client: TestClient):
    r = client.get("/api/digest")
    assert r.status_code == 200
    body = r.json()
    assert "headline" in body
    assert "total_gbp" in body
    assert "ranked" in body
    assert "suggested_order" in body
    assert "memory_recall" in body
    assert body["overdue_count"] >= 1
    assert body["total_gbp"] > 0
    assert body["top_chase_id"]
    # Fernhill 30d should rank first
    assert body["ranked"][0]["chase_id"] == "ch-001"


def test_digest_post(client: TestClient):
    r = client.post("/api/digest")
    assert r.status_code == 200
    assert r.json()["headline"]


def test_scrub_placeholders():
    raw = (
        "Hi there,\n\nPlease pay.\n\nBest regards,\n[Your Name]\n[Company Name]\n"
        "Contact: [Email]"
    )
    out = scrub_placeholders(
        raw, contact="accounts@fernhill.example", client_name="Fernhill School"
    )
    assert "[Your Name]" not in out
    assert "[Company Name]" not in out
    assert "Halden & Rook Ops" in out
    assert "MN Labs" in out or "Halden & Rook" in out


def test_scrub_bracket_fields():
    out = scrub_placeholders("Signed by [Insert Name] at [Company]")
    assert "[" not in out
    assert "Halden & Rook Ops" in out


def test_dry_run_uses_contact():
    chase = Chase(
        id="ch-test",
        client_id="cli-quayside",
        invoice_ref="INV-2790",
        amount=210.0,
        days_overdue=14,
        summary="Quayside Bistro INV-2790 overdue",
        last_action="Bounce noted",
        history=["chase to owner@ bounced"],
    )
    client = Client(
        id="cli-quayside",
        name="Quayside Bistro",
        contact="accounts@quaysidebistro.example",
        notes=["Previous chase bounced — try accounts@"],
    )
    job = Job(
        id="job-h",
        client_id="cli-quayside",
        title="Camera clean",
        address="Quayside Wharf, Brighton",
    )
    notes = [
        type("N", (), {"text": "Quayside: do not use owner@ — bounce. Prefer accounts@quaysidebistro.example."})()
    ]
    result = dry_run_propose(chase, client, job=job, notes=notes)
    assert result.needs_human is True
    assert "Halden & Rook Ops" in result.draft_action
    assert "accounts@quaysidebistro.example" in result.draft_action
    assert "[Your Name]" not in result.draft_action
    assert "[Company Name]" not in result.draft_action
    assert "Quayside Wharf" in result.draft_action


def test_propose_dry_run_no_placeholders(client: TestClient):
    r = client.post("/api/propose", json={"chase_id": "ch-002"})
    assert r.status_code == 200
    draft = r.json()["proposal"]["draft_action"]
    assert "Halden & Rook Ops" in draft
    assert "accounts@quaysidebistro.example" in draft
    assert "[Your Name]" not in draft
    assert "[Company Name]" not in draft


def test_approve_surfaces_decision(client: TestClient):
    r = client.post("/api/propose", json={"chase_id": "ch-003"})
    draft = r.json()["proposal"]["draft_action"]
    r2 = client.post(
        "/api/decide",
        json={"chase_id": "ch-003", "decision": "approve", "draft_text": draft},
    )
    assert r2.status_code == 200
    mem = client.get("/api/memory").json()
    approved = [d for d in mem["decisions"] if d["decision"] == "approve" and d["chase_id"] == "ch-003"]
    assert approved
    assert approved[0]["draft_text"]
