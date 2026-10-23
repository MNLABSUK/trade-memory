"""Trade Memory FastAPI application — persistent chase memory + human gate."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from trade_memory import __version__
from trade_memory.config import get_settings
from trade_memory.followup import handle_followup
from trade_memory.hmem import hmem
from trade_memory.memory import store
from trade_memory.models import (
    DecideRequest,
    FollowupRequest,
    HealthResponse,
    NoteRequest,
    ProposeRequest,
    RecallRequest,
)
from trade_memory.nebius_client import clean_draft, propose_next_action
from trade_memory import why as why_mod

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"

app = FastAPI(title="Trade Memory", version=__version__)


class ReopenRequest(BaseModel):
    note: Optional[str] = None


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = get_settings()
    st = store.stats()
    return HealthResponse(
        status="ok",
        dry_run=s["dry_run"],
        model=s["model"],
        provider=s["provider"],
        memory_path=s["memory_path"],
        clients=st["clients"],
        jobs=st["jobs"],
        open_chases=st["open_chases"],
        notes=st["notes"],
        later_count=st.get("later_count", 0),
        decisions_today=st.get("decisions_today", 0),
    )


@app.get("/api/memory")
def memory_snapshot():
    snap = store.snapshot()
    return {
        "clients": snap.get("clients", []),
        "jobs": snap.get("jobs", []),
        "chases": snap.get("chases", []),
        "notes": snap.get("notes", []),
        "decisions": snap.get("decisions", []),
        "session": snap.get("session", {}),
        "stats": store.stats(),
    }


@app.get("/api/stats")
def stats():
    return store.stats()


@app.get("/api/chases")
def chases(open_only: bool = True):
    items = store.list_chases(open_only=open_only)
    return {"chases": [c.model_dump(mode="json") for c in items], "count": len(items)}


@app.get("/api/jobs")
def jobs():
    return {"jobs": [j.model_dump(mode="json") for j in store.list_jobs()]}


@app.get("/api/clients")
def clients():
    return {"clients": [c.model_dump(mode="json") for c in store.list_clients()]}


@app.get("/api/clients/{client_id}")
def client_detail(client_id: str):
    bundle = store.get_client_bundle(client_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Client not found: {client_id}")
    return bundle


@app.get("/api/notes")
def notes(limit: int = 50):
    return {"notes": [n.model_dump(mode="json") for n in store.list_notes(limit=limit)]}


@app.get("/api/activity")
def activity(
    limit: int = 50,
    chase_id: Optional[str] = Query(default=None),
):
    acts = store.list_activity(limit=limit, chase_id=chase_id)
    st = store.stats()
    return {
        "activity": acts,
        "stats": {
            "decisions_today": st.get("decisions_today", 0),
            "later_count": st.get("later_count", 0),
            "open_chases": st.get("open_chases", 0),
            "notes": st.get("notes", 0),
        },
    }


@app.get("/api/session")
def session():
    return {"session": store.get_session()}


@app.post("/api/recall")
def recall(req: RecallRequest):
    result = store.recall(req.query)
    focus = result.get("focus") or {}
    store.touch_session(
        question=req.query,
        chase_id=focus.get("id"),
        client_id=focus.get("client_id"),
        kind="recall",
    )
    return result


@app.get("/api/recall")
def recall_get(q: str = "what were we chasing?"):
    result = store.recall(q)
    focus = result.get("focus") or {}
    store.touch_session(
        question=q,
        chase_id=focus.get("id"),
        client_id=focus.get("client_id"),
        kind="recall",
    )
    return result



@app.get("/api/digest")
def digest_get():
    """Morning digest: overdue ranked, total £, suggested work order, memory recall."""
    result = store.morning_digest()
    top = result.get("top_chase_id")
    if top:
        chase = store.get_chase(top)
        store.touch_session(
            chase_id=top,
            client_id=chase.client_id if chase else None,
            kind="digest",
            question="morning digest",
        )
    return result


@app.post("/api/digest")
def digest_post():
    """Same as GET — optional POST for clients that prefer POST."""
    return digest_get()


@app.post("/api/notes")

def add_note(req: NoteRequest):
    note = store.add_note(
        req.text,
        related_client_id=req.related_client_id,
        related_chase_id=req.related_chase_id,
        related_job_id=req.related_job_id,
    )
    return {"note": note.model_dump(mode="json"), "session": store.get_session()}


@app.post("/api/propose")
async def propose(req: ProposeRequest):
    chase_id = req.chase_id
    if not chase_id:
        recalled = store.recall(req.question or "what were we chasing?")
        focus = recalled.get("focus") or {}
        chase_id = focus.get("id")
    if not chase_id:
        open_chases = store.list_chases(open_only=True)
        if not open_chases:
            raise HTTPException(status_code=404, detail="No open chases in memory")
        chase_id = open_chases[0].id

    chase = store.get_chase(chase_id)
    if chase is None:
        raise HTTPException(status_code=404, detail=f"Chase not found: {chase_id}")

    ctx = store.build_propose_context(chase)
    client = ctx["client"]
    # Meterless H-MEM: inject durable memories for this client into the prompt.
    hq = " ".join(filter(None, [client.name if client else chase.client_id, chase.invoice_ref, chase.summary]))
    hmem_summary = hmem.summary(hq, namespace=f"client:{chase.client_id}")
    if hmem_summary:
        ctx["recall_summary"] = (ctx["recall_summary"] + "\n" + hmem_summary).strip()
    result = await propose_next_action(
        chase,
        client,
        job=ctx["job"],
        notes=ctx["notes"],
        decisions=ctx["decisions"],
        recall_summary=ctx["recall_summary"],
        history=ctx["history"],
    )
    store.update_chase_draft(chase.id, result.draft_action, summary=result.summary)
    store.touch_session(
        chase_id=chase.id,
        client_id=chase.client_id,
        kind="chase",
        pending={
            "chase_id": chase.id,
            "prompt": "Edit the draft, then Approve / Leave it / Later.",
            "draft_text": result.draft_action,
        },
        question=req.question,
    )
    store.add_activity(
        "proposed",
        chase_id=chase.id,
        detail=result.summary,
        draft_text=result.draft_action,
    )

    refreshed = store.get_chase(chase.id)
    return {
        "chase": refreshed.model_dump(mode="json") if refreshed else chase.model_dump(mode="json"),
        "proposal": result.model_dump(),
        "client": client.model_dump(mode="json") if client else None,
        "job": ctx["job"].model_dump(mode="json") if ctx["job"] else None,
        "notes": [n.model_dump(mode="json") for n in ctx["notes"]],
        "decisions": [d.model_dump(mode="json") for d in ctx["decisions"]],
        "recall_summary": ctx["recall_summary"],
        "session": store.get_session(),
    }


@app.post("/api/decide")
def decide(req: DecideRequest):
    if req.decision not in ("approve", "leave", "later"):
        raise HTTPException(status_code=400, detail="Invalid decision")
    draft = (req.draft_text or "").strip()
    chase = store.record_decision(
        req.chase_id,
        req.decision,
        req.note,
        draft_text=draft,
        snooze_until=req.snooze_until,
    )
    if chase is None:
        raise HTTPException(status_code=404, detail=f"Chase not found: {req.chase_id}")
    # Meterless H-MEM: every human gate decision becomes a sourced, durable memory.
    parts = [f"{req.decision} on {chase.invoice_ref or chase.id}"]
    if req.note:
        parts.append(f"note: {req.note}")
    if draft and req.decision == "approve":
        parts.append(f"sent: {draft[:200]}")
    hmem.remember(
        "; ".join(parts),
        source=f"decision:{chase.id}",
        confidence=0.95 if req.note else 0.8,
        origin="decision",
        label="human gate decision",
        namespace=f"client:{chase.client_id}",
        tags=[req.decision, chase.invoice_ref] if chase.invoice_ref else [req.decision],
        entities=[{"name": chase.client_id, "type": "client"}],
        refs={"decisionId": chase.id},
    )
    return {"chase": chase.model_dump(mode="json"), "session": store.get_session()}


@app.post("/api/chases/{chase_id}/reopen")
def reopen(chase_id: str, req: Optional[ReopenRequest] = None):
    note = req.note if req else None
    chase = store.reopen_chase(chase_id, note=note)
    if chase is None:
        raise HTTPException(status_code=404, detail=f"Chase not found: {chase_id}")
    return {"chase": chase.model_dump(mode="json"), "session": store.get_session()}


@app.post("/api/followup")
async def followup(req: FollowupRequest):
    result = await handle_followup(store, req.message, chase_id=req.chase_id)
    return {
        **result,
        "session": store.get_session(),
        "stats": store.stats(),
    }


@app.post("/api/reset-seed")
def reset_seed():
    """Demo helper: re-seed memory (does not delete .env)."""
    store.reset_to_seed()
    return {"ok": True, "stats": store.stats()}


# ---- Why cards: Zetaris evidence -> reasoning -> human gate (Track 02) -----------------------
class WhyDecideRequest(BaseModel):
    decision: str
    action_id: str
    note: str = ""
    draft_text: str = ""


@app.get("/api/why")
def why_cards():
    """All five cards plus outstanding totals, computed from Zetaris rows."""
    return why_mod.engine.cards()


@app.get("/api/why/{pid}")
def why_card(pid: str):
    try:
        return why_mod.engine.card(pid.upper())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown puzzle {pid}")


@app.post("/api/why/{pid}/decide")
def why_decide(pid: str, req: WhyDecideRequest):
    """The human gate: nothing is queued to send without decision=approve."""
    try:
        return why_mod.engine.decide(pid.upper(), req.decision, req.action_id, req.note, req.draft_text)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown puzzle {pid}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/why/{pid}/polish")
async def why_polish(pid: str):
    """Optional: Nemotron (via Nightshift) rewrites the draft; facts and the gate are unchanged."""
    from trade_memory.llm import LLMUnavailable, chat_completion

    try:
        card = why_mod.engine.card(pid.upper())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown puzzle {pid}")
    a = card["action"]
    if not a or a["channel"] in ("ledger", "crm", "portal"):
        return {"draft": a["draft"] if a else "", "source": "rules", "model": None}
    msgs = [{"role": "system", "content": "Rewrite this UK trade-business message to be short, warm and firm. "
             "Keep every invoice number, amount, date and name exactly. Reply with the message only."},
            {"role": "user", "content": a["draft"]}]
    try:
        content, prov = await chat_completion(msgs)
    except LLMUnavailable:
        return {"draft": a["draft"], "source": "rules", "model": None}
    import re

    new = clean_draft(content)
    facts = set(re.findall(r"INV-\d+|JS-\d+|PO-[A-Z]+-\d+|£[\d,]+(?:\.\d\d)?", a["draft"]))
    missing = sorted(f for f in facts if f not in new)
    if missing:  # citation check: the rewrite dropped or changed a cited fact
        return {"draft": a["draft"], "source": "rules", "model": prov.model, "rejected_rewrite_missing": missing}
    return {"draft": new, "source": prov.name, "model": prov.model}


@app.get("/api/outbox")
def outbox():
    return {"items": why_mod.engine.outbox_items()}


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="UI not found")
    return FileResponse(index_path)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
