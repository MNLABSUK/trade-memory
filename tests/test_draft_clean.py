from trade_memory.nebius_client import _parse_json_content, clean_draft, strip_reasoning
from trade_memory import llm


def test_strip_reasoning_nemotron():
    assert strip_reasoning('The user wants OK.</think>\n\nOK') == "OK"


def test_clean_draft_preamble_and_escapes():
    raw = 'Here are the short chase emails:\n\n**Email**\n"Hi Larkfield Lettings,\\n\\nChase on INV-1007 for \\u00a32,166.00."'
    out = clean_draft(raw)
    assert out.startswith("Email")
    assert "£2,166.00" in out and "\\n" not in out and "\\u00a3" not in out
    assert "Here are" not in out and "**" not in out


def test_parse_json_inside_prose_and_think():
    d = _parse_json_content('thinking</think>Sure: {"draft_action": "x", "urgency": "low"} done')
    assert d["draft_action"] == "x"


def test_nightshift_fallback_model(monkeypatch):
    monkeypatch.delenv("TRADE_MEMORY_DRY_RUN", raising=False)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setenv("NIGHTSHIFT_API_KEY", "test-token")
    monkeypatch.setenv("NIGHTSHIFT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    monkeypatch.setenv("NIGHTSHIFT_FALLBACK_MODEL", "webllm/Qwen2.5-3B-Instruct-q4f16_1-MLC")
    ps = llm.configured_providers()
    assert [(p.name, p.model) for p in ps] == [
        ("nightshift", "nvidia/nemotron-3-ultra-550b-a55b"),
        ("nightshift", "webllm/Qwen2.5-3B-Instruct-q4f16_1-MLC"),
    ]
