"""Smoke tests for Trade Memory persistent store + API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trade_memory.memory import MemoryStore
from trade_memory.app import app


@pytest.fixture()
def tmp_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MemoryStore:
    path = tmp_path / "memory.json"
    store = MemoryStore(path=path)
    # Point module singleton used by app at this temp store
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


def test_memory_persists_note_across_reload(tmp_path: Path):
    path = tmp_path / "memory.json"
    s1 = MemoryStore(path=path)
    s1.add_note("Persistence proof note for Trade Memory")
    assert path.exists()
    raw = json.loads(path.read_text())
    assert any("Persistence proof" in n["text"] for n in raw["notes"])

    s2 = MemoryStore(path=path)
    notes = s2.list_notes()
    assert any("Persistence proof" in n.text for n in notes)
    recall = s2.recall("what were we chasing?")
    assert "Open chases" in recall["answer"] or "Last focus" in recall["answer"]


def test_propose_and_decide_dry_run(client: TestClient):
    r = client.post("/api/propose", json={"chase_id": "ch-001"})
    assert r.status_code == 200
    body = r.json()
    assert body["proposal"]["needs_human"] is True
    assert body["proposal"]["draft_action"]

    r2 = client.post(
        "/api/decide",
        json={
            "chase_id": "ch-001",
            "decision": "later",
            "draft_text": body["proposal"]["draft_action"],
            "note": "park for tomorrow",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["chase"]["decision"] == "later"


def test_recall_endpoint(client: TestClient):
    r = client.get("/api/recall", params={"q": "what were we chasing?"})
    assert r.status_code == 200
    assert "answer" in r.json()
