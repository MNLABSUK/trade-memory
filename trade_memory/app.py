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
from trade_memory.memory import store
from trade_memory.models import (
    DecideRequest,
    FollowupRequest,
    HealthResponse,
    NoteRequest,
    ProposeRequest,
    RecallRequest,
)
from trade_memory.nebius_client import propose_next_action

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
        provider="dry-run" if s["dry_run"] else "nebius-token-factory",
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


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="UI not found")
    return FileResponse(index_path)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
