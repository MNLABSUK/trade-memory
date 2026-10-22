"""Pydantic models for Trade Memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Decision = Literal["approve", "leave", "later"]
ChaseStatus = Literal["open", "waiting", "closed", "later"]


class Client(BaseModel):
    id: str
    name: str
    trade: str = "CCTV / security"
    contact: str = ""
    notes: list[str] = Field(default_factory=list)


class Job(BaseModel):
    id: str
    client_id: str
    title: str
    status: str = "open"
    address: str = ""
    amount: Optional[float] = None
    currency: str = "GBP"
    notes: list[str] = Field(default_factory=list)


class Chase(BaseModel):
    id: str
    client_id: str
    job_id: Optional[str] = None
    invoice_ref: str = ""
    amount: Optional[float] = None
    currency: str = "GBP"
    days_overdue: int = 0
    status: ChaseStatus = "open"
    summary: str = ""
    last_action: str = ""
    history: list[str] = Field(default_factory=list)
    draft_action: Optional[str] = None
    decision: Optional[Decision] = None
    decision_note: Optional[str] = None
    decided_at: Optional[datetime] = None
    snooze_until: Optional[str] = None


class MemoryNote(BaseModel):
    id: str
    text: str
    related_client_id: Optional[str] = None
    related_chase_id: Optional[str] = None
    related_job_id: Optional[str] = None
    created_at: datetime


class DecisionRecord(BaseModel):
    id: str
    chase_id: str
    decision: Decision
    draft_text: str = ""
    note: str = ""
    snooze_until: Optional[str] = None
    at: datetime


class SessionState(BaseModel):
    last_chase_id: Optional[str] = None
    last_client_id: Optional[str] = None
    last_kind: Optional[str] = None
    pending: Optional[dict[str, Any]] = None
    last_question: Optional[str] = None


class ProposeRequest(BaseModel):
    chase_id: Optional[str] = None
    question: Optional[str] = None


class ProposeResult(BaseModel):
    chase_id: str
    summary: str
    draft_action: str
    urgency: str = "medium"
    needs_human: bool = True
    source: str = "dry-run"


class DecideRequest(BaseModel):
    chase_id: str
    decision: Decision
    note: Optional[str] = None
    draft_text: Optional[str] = None
    snooze_until: Optional[str] = None


class NoteRequest(BaseModel):
    text: str = Field(..., min_length=1)
    related_client_id: Optional[str] = None
    related_chase_id: Optional[str] = None
    related_job_id: Optional[str] = None


class RecallRequest(BaseModel):
    query: str = Field(default="what were we chasing?")


class FollowupRequest(BaseModel):
    message: str = Field(..., min_length=1)
    chase_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    dry_run: bool
    model: str
    provider: str
    memory_path: str
    clients: int
    jobs: int
    open_chases: int
    notes: int
    later_count: int = 0
    decisions_today: int = 0
