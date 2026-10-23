"""Deepen tests: recall search, propose context, decide→persist→recall, reopen, health."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trade_memory.app import app
from trade_memory.memory import MemoryStore


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


def test_health_ok(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["dry_run"] is True
    assert data["open_chases"] >= 1
    assert "later_count" in data
    assert "decisions_today" in data


def test_recall_search_larkfield(client: TestClient):
    r = client.post("/api/recall", json={"query": "Larkfield"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("focus")
    assert body["focus"]["id"] == "ch-001"
    names = [c["name"] for c in body.get("matched_clients", [])]
    assert any("Larkfield" in n for n in names)
    assert "answer" in body


def test_recall_overdue(client: TestClient):
    r = client.post("/api/recall", json={"query": "what's overdue?"})
    assert r.status_code == 200
    body = r.json()
    assert "overdue" in body["answer"].lower() or body.get("focus")


def test_propose_dry_run_with_context(client: TestClient):
    r = client.post("/api/propose", json={"chase_id": "ch-001"})
    assert r.status_code == 200
    body = r.json()
    prop = body["proposal"]
    assert prop["needs_human"] is True
    assert prop["draft_action"]
    assert prop["source"] in ("dry-run", "dry-run-fallback")
    assert body.get("job") is not None
    assert "recall_summary" in body
    assert isinstance(body.get("notes"), list)


def test_decide_persist_recall(client: TestClient, tmp_store: MemoryStore):
    r = client.post("/api/propose", json={"chase_id": "ch-002"})
    assert r.status_code == 200
    draft = r.json()["proposal"]["draft_action"]

    r2 = client.post(
        "/api/decide",
        json={
            "chase_id": "ch-002",
            "decision": "later",
            "draft_text": draft,
            "note": "park for tomorrow",
            "snooze_until": "2026-09-20T09:00:00+01:00",
        },
    )
    assert r2.status_code == 200
    chase = r2.json()["chase"]
    assert chase["decision"] == "later"
    assert chase["status"] == "later"
    assert chase.get("snooze_until")

    # persist on disk
    raw = json.loads(tmp_store.path.read_text())
    hit = next(c for c in raw["chases"] if c["id"] == "ch-002")
    assert hit["status"] == "later"
    assert any(d["chase_id"] == "ch-002" for d in raw["decisions"])

    # recall still answers
    r3 = client.get("/api/recall", params={"q": "what were we chasing?"})
    assert r3.status_code == 200
    assert r3.json()["answer"]


def test_reopen_chase(client: TestClient):
    # ch-007 is closed in seed
    r = client.post("/api/chases/ch-007/reopen", json={"note": "demo reopen"})
    assert r.status_code == 200
    assert r.json()["chase"]["status"] == "open"

    r2 = client.get("/api/chases", params={"open_only": True})
    ids = [c["id"] for c in r2.json()["chases"]]
    assert "ch-007" in ids


def test_followup_overdue_and_who(client: TestClient):
    r = client.post("/api/followup", json={"message": "what's overdue?"})
    assert r.status_code == 200
    assert r.json()["kind"] == "overdue"
    assert r.json()["focus_chase_id"]

    r2 = client.post("/api/followup", json={"message": "who is Larkfield?"})
    assert r2.status_code == 200
    assert r2.json()["kind"] == "who"
    assert "Larkfield" in r2.json()["reply"]


def test_followup_draft_kestrel(client: TestClient):
    r = client.post("/api/followup", json={"message": "draft chase for Kestrel"})
    assert r.status_code == 200
    assert r.json()["kind"] == "draft"
    assert r.json()["draft"]
    assert r.json()["focus_chase_id"] == "ch-003"


def test_client_and_jobs_endpoints(client: TestClient):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert len(r.json()["jobs"]) >= 6

    r2 = client.get("/api/clients/cli-moss")
    assert r2.status_code == 200
    body = r2.json()
    assert body["client"]["name"]
    assert len(body["jobs"]) >= 1
    assert len(body["chases"]) >= 1


def test_activity_stats(client: TestClient):
    r = client.get("/api/activity")
    assert r.status_code == 200
    body = r.json()
    assert "activity" in body
    assert "decisions_today" in body["stats"]
    assert "later_count" in body["stats"]


def test_memory_persists_note(tmp_path: Path):
    path = tmp_path / "memory.json"
    s1 = MemoryStore(path=path)
    s1.add_note("PERSISTENCE_PROOF deepen note", related_job_id="job-507")
    raw = json.loads(path.read_text())
    assert any("PERSISTENCE_PROOF" in n["text"] for n in raw["notes"])
    assert any(n.get("related_job_id") == "job-507" for n in raw["notes"])

    s2 = MemoryStore(path=path)
    assert any("PERSISTENCE_PROOF" in n.text for n in s2.list_notes())
