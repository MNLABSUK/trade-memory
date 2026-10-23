"""H-MEM (Meterless Engine) persistent memory for Trade Memory.

A small Python implementation of the H-MEM memory-record contract
(github.com/Meterless/Meterless/tree/main/engines/hmem, docs/memory-record.md):
layers short_term / working / long_term, mandatory `source` and `confidence`,
provenance with an origin, entities, supersedes, and recall ranked by
relevance x confidence x recency x access. Records are append-only JSONL files
per layer on local disk, so it runs fully offline with no key.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

LAYERS = ("short_term", "working", "long_term")
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "hmem"
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "for", "on", "in", "is", "we", "what", "were", "it"}


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall((text or "").lower()) if t not in _STOP and len(t) > 1}


@dataclass
class Memory:
    id: str
    content: str
    type: str  # personal | factual | preference | general
    layer: str  # short_term | working | long_term
    timestamp: int
    last_accessed: int
    access_count: int
    confidence: float
    source: str
    tags: list[str] = field(default_factory=list)
    domain: Optional[str] = None
    namespace: Optional[str] = None
    entities: list[dict[str, str]] = field(default_factory=list)
    related_to: list[str] = field(default_factory=list)
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    derived_from: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    score: Optional[float] = None


class HMem:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or os.getenv("HMEM_DIR") or DEFAULT_DIR)
        self._lock = threading.Lock()

    def _file(self, layer: str) -> Path:
        return self.root / f"{layer}.jsonl"

    def all(self) -> list[Memory]:
        out: list[Memory] = []
        for layer in LAYERS:
            f = self._file(layer)
            if f.exists():
                for line in f.read_text().splitlines():
                    if line.strip():
                        out.append(Memory(**json.loads(line)))
        # latest row per id wins (append-only updates)
        latest: dict[str, Memory] = {}
        for m in out:
            latest[m.id] = m
        return list(latest.values())

    def remember(
        self,
        content: str,
        *,
        source: str,
        confidence: float,
        origin: str = "decision",
        label: str = "",
        layer: str = "working",
        type: str = "factual",
        tags: list[str] | None = None,
        entities: list[dict[str, str]] | None = None,
        namespace: str | None = None,
        supersedes: str | None = None,
        refs: dict[str, Any] | None = None,
    ) -> Memory:
        if not source:
            raise ValueError("H-MEM record requires a source")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if layer not in LAYERS:
            raise ValueError(f"bad layer {layer}")
        now = int(time.time() * 1000)
        m = Memory(
            id=f"mem_{uuid.uuid4().hex[:12]}",
            content=content,
            type=type,
            layer=layer,
            timestamp=now,
            last_accessed=now,
            access_count=0,
            confidence=confidence,
            source=source,
            tags=tags or [],
            domain="trade-memory",
            namespace=namespace,
            entities=entities or [],
            supersedes=supersedes,
            provenance={"origin": origin, "learnedAt": now, "label": label or origin, "refs": refs or {}},
        )
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            if supersedes:
                old = next((x for x in self.all() if x.id == supersedes), None)
                if old:
                    old.superseded_by = m.id
                    self._append(old)
            self._append(m)
        return m

    def _append(self, m: Memory) -> None:
        d = asdict(m)
        d.pop("score", None)
        with self._file(m.layer).open("a") as f:
            f.write(json.dumps(d) + "\n")

    def recall(self, query: str, *, namespace: str | None = None, k: int = 5) -> list[Memory]:
        q = _tokens(query)
        now = int(time.time() * 1000)
        scored: list[Memory] = []
        for m in self.all():
            if namespace and m.namespace != namespace:
                continue
            text = m.content + " " + " ".join(m.tags) + " " + " ".join(e.get("name", "") for e in m.entities)
            overlap = len(q & _tokens(text))
            if q and not overlap and not (namespace and m.namespace == namespace):
                continue
            rel = overlap / max(len(q), 1) if q else 0.5
            age_days = (now - m.timestamp) / 86_400_000
            recency = 1.0 / (1.0 + age_days / 7.0)
            access = min(m.access_count, 10) / 10.0
            penalty = 0.3 if m.superseded_by else 1.0
            m.score = round((0.5 * rel + 0.15 + 0.2 * recency + 0.1 * access) * m.confidence * penalty, 4)
            scored.append(m)
        scored.sort(key=lambda x: x.score or 0, reverse=True)
        top = scored[:k]
        with self._lock:
            for m in top:  # reinforce on access (episodic -> durable signal)
                m.access_count += 1
                m.last_accessed = now
                if m.layer == "working" and m.access_count >= 3:
                    m.layer = "long_term"
                self._append(m)
        return top

    def summary(self, query: str, *, namespace: str | None = None, k: int = 3) -> str:
        hits = self.recall(query, namespace=namespace, k=k)
        if not hits:
            return ""
        return "H-MEM recall: " + " | ".join(f"{h.content} (src {h.source}, conf {h.confidence:.2f})" for h in hits)


hmem = HMem()
