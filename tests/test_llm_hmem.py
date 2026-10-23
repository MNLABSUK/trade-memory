import json

import httpx
import pytest

from trade_memory import llm
from trade_memory.hmem import HMem


def test_normalize_base_url():
    assert llm.normalize_base_url("127.0.0.1:8088") == "http://127.0.0.1:8088/v1"
    assert llm.normalize_base_url("http://h:8088/v1/chat/completions") == "http://h:8088/v1"
    assert llm.normalize_base_url("http://h:8088/v1/") == "http://h:8088/v1"


def test_provider_order_and_dry_run(monkeypatch):
    monkeypatch.delenv("TRADE_MEMORY_DRY_RUN", raising=False)
    for v in ("NIGHTSHIFT_FALLBACK_MODEL", "NIGHTSHIFT_TOKEN_FILE", "NIGHTSHIFT_BASE_URL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("NIGHTSHIFT_API_KEY", "ns-test")
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test")
    names = [p.name for p in llm.configured_providers()]
    assert names == ["nightshift", "nebius"]
    ns = llm.configured_providers()[0]
    assert ns.base_url == "http://127.0.0.1:8088/v1"
    assert ns.headers()["meterless-scope"] == "user"
    assert "ns-test" not in repr(ns)
    monkeypatch.setenv("NIGHTSHIFT_API_KEY", "rt-local")  # placeholder is rejected
    assert [p.name for p in llm.configured_providers()] == ["nebius"]
    monkeypatch.setenv("TRADE_MEMORY_DRY_RUN", "1")
    assert llm.configured_providers() == []


async def test_fallback_to_nebius():
    def handler(req: httpx.Request) -> httpx.Response:
        if "8088" in str(req.url):
            return httpx.Response(503)
        assert req.headers["authorization"] == "Bearer nb"
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    ps = [
        llm.Provider("nightshift", "http://127.0.0.1:8088/v1", "ns", "meterless/auto"),
        llm.Provider("nebius", "https://nebius.test/v1", "nb", "m"),
    ]
    content, used = await llm.chat_completion([{"role": "user", "content": "x"}], providers=ps,
                                              transport=httpx.MockTransport(handler))
    assert (content, used.name) == ("hi", "nebius")


async def test_all_fail_raises():
    ps = [llm.Provider("nightshift", "http://x/v1", "k", "m")]
    with pytest.raises(llm.LLMUnavailable):
        await llm.chat_completion([], providers=ps, transport=httpx.MockTransport(lambda r: httpx.Response(500)))


def test_hmem_contract_and_recall(tmp_path):
    h = HMem(tmp_path)
    with pytest.raises(ValueError):
        h.remember("x", source="", confidence=0.5)
    a = h.remember("Kestrel prefer email to accounts, not phone", source="decision:c1",
                   confidence=0.9, namespace="client:kss", tags=["kestrel"])
    h.remember("Kirkgate Bakery pays on Fridays", source="note:n1", confidence=0.6, namespace="client:kirk")
    hits = h.recall("how do we chase Kestrel?")
    assert hits and hits[0].id == a.id
    b = h.remember("Kestrel now want phone calls", source="decision:c2", confidence=0.9,
                   namespace="client:kss", supersedes=a.id)
    hits = h.recall("Kestrel chase", namespace="client:kss")
    assert hits[0].id == b.id
    # persisted across instances (append-only JSONL per layer)
    assert {m.id for m in HMem(tmp_path).all()} >= {a.id, b.id}
    for line in (tmp_path / "working.jsonl").read_text().splitlines():
        assert json.loads(line)["source"]


def test_decide_writes_hmem_and_propose_recalls():
    from fastapi.testclient import TestClient

    from trade_memory.app import app
    from trade_memory.hmem import hmem
    from trade_memory.memory import store

    c = TestClient(app)
    chase = store.list_chases(open_only=True)[0]
    r = c.post("/api/decide", json={"chase_id": chase.id, "decision": "later",
                                     "note": "client asked to wait for PO number"})
    assert r.status_code == 200
    assert any("PO number" in m.content for m in hmem.all())
    c.post(f"/api/chases/{chase.id}/reopen", json={})
    p = c.post("/api/propose", json={"chase_id": chase.id})
    assert p.status_code == 200
    assert "H-MEM recall" in p.json()["recall_summary"]
    assert c.get("/api/health").json()["provider"] == "dry-run"
