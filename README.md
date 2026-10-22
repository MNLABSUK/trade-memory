# Trade Memory

**Persistent chase memory** for small UK trades / contractors (Halden & Rook–style CCTV ops + Larch workshop demo).

Primary track: **Real-World Industry Agents** (Open Agent Hackathon 2026 / GenAI.Works).  
Secondary narrative: **Persistent Memory Agents**.

> Small contractors lose context between WhatsApp, emails, and open invoices.  
> Trade Memory remembers jobs, clients, and chase state **across sessions**, proposes real next actions, and always stops at a **human gate** (Approve / Leave it / Later).

This is **not** a Desk Gate clone. Desk Gate is an inbox triage desk; Trade Memory’s star is the **persistent JSON memory store** (clients · jobs · chases · notes · decisions) that survives process restart.

## Finalist (v0.3)

- **Agent drafts** — Halden & Rook Ops / MN Labs sign-off; real `client.contact` + job address; bounce-aware preferred contact; placeholder scrub; temp 0.15
- **Morning digest** — `GET/POST /api/digest` ranks overdue £, suggested work order, one-line memory recall; UI chip selects top chase
- **Visual polish** — Desk Gate cream/navy DNA on 3-col desk (sticky blur topbar, paper cards, urgency pills, Approve-primary decide bar, elevated follow-up, toast)
- **Failure modes** — topbar drawer + README section (submission req 6.3)
- **Approved this session** strip — surfaces last Approve draft from decisions
- **Microcopy** — “Remembers the chase. You approve the send.” + 3-step empty state

## Deepen features (v0.2)

- **Richer propose context** — related job, recent notes, prior decisions, recall summary fed into Nebius / dry-run
- **Broad recall** — substring search across clients, jobs, chases, notes, invoice refs; returns matched_* + focus
- **Chase lifecycle** — reopen closed/later chases; optional `snooze_until` on Later; activity filter by chase
- **Follow-up chat** — `/api/followup` for “what’s overdue?”, “who is Fernhill?”, “draft chase for Oak”
- **Activity stats** — `decisions_today`, `later_count` on `/api/activity` + health
- **3-column cream/navy desk** — Memory | Chases | Detail+Activity, follow-up bar, demo chips, Esc clears selection
- **Seed v2** — chase history strings, closed Larch chase with prior decision, demo memory thread

## Quick start

```bash
cd trade-memory
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Optional: copy Nebius key from Desk Gate for live mode
# cp ../Nebius-NVIDIA/desk-gate/.env .env   # if present — never commit

# macOS double-click launcher:
open start-trade-memory.command

# Or manually:
export PYTHONPATH=.
uvicorn trade_memory.app:app --host 127.0.0.1 --port 43151
```

- UI: http://127.0.0.1:43151/
- Health: http://127.0.0.1:43151/api/health

Without `NEBIUS_API_KEY`, the app runs in **dry-run** (deterministic heuristics). With a key, it uses Nebius Token Factory.

## Demo walkthrough (~2 minutes)

1. Open http://127.0.0.1:43151/ — stats strip shows overdue £, open, later, notes, clients.
2. Click **Morning digest** — ranked overdue + £ total; top chase selected; recall filled.
3. Or ask **What were we chasing?** — recall focuses Fernhill; center list highlights the chase.
4. Click **Propose next** — draft appears with job address / contact context (dry-run or Nebius).
5. Edit draft → **Later** (or Approve / Leave it) — activity trail updates; chase moves to Closed/Later.
6. Restart the server → ask recall again — same focus / notes prove **persistence**. Try follow-up: “who’s Larch?” / “draft chase for Oak” / **Reopen** on a closed chase.

## What persists

File: `data/memory.json` (gitignored at runtime)

| Entity | Purpose |
|--------|---------|
| clients | Who you work for + contact notes |
| jobs | Field / install work + address |
| chases | Open invoices & follow-ups (+ history, snooze) |
| notes | Free-form memory (optional job/chase/client link) |
| decisions | Approve / Leave / Later audit |
| session | Last chase + pending draft — continues after restart |
| activity | Desk trail for the Activity pane |

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | ok + dry_run + counts + later_count + decisions_today |
| GET | `/api/memory` | Full memory snapshot |
| GET/POST | `/api/recall` | Broad “what were we chasing?” search |
| POST | `/api/notes` | Add persistent note |
| GET | `/api/chases` | List chases (`open_only`) |
| GET | `/api/jobs` | List jobs |
| GET | `/api/clients/{id}` | Client + jobs + chases + notes |
| POST | `/api/propose` | LLM / dry-run next action (full memory context) |
| POST | `/api/decide` | approve \| leave \| later (+ optional snooze_until) |
| POST | `/api/chases/{id}/reopen` | Reopen closed/later chase |
| POST | `/api/followup` | Desk chat (overdue / who / draft) |
| GET | `/api/activity` | Activity feed + stats |
| POST | `/api/reset-seed` | Re-seed demo memory |

## Tests

```bash
pytest -q
```

## Ports

| App | Port |
|-----|------|
| Desk Gate | 43149 |
| Yard Desk | 43150 |
| **Trade Memory** | **43151** |



## Failure modes (honest)

| Mode | What happens | Mitigation |
|------|----------------|------------|
| Bad / stale contacts | Owner mobiles bounce; finance emails change | Prefer `accounts@` from notes; show contact on desk |
| LLM placeholder drafts | Nebius may emit `[Your Name]` / `[Company Name]` | SYSTEM_PROMPT + scrub → Halden & Rook Ops + real contact; dry-run fallback |
| Memory conflict | Concurrent sessions race on JSON flush | Last write wins; single-desk demo assumed |
| Dry-run fallback | No API key or Nebius error | Deterministic heuristics; still needs Approve |
| Human gate necessity | Agent must not auto-send money/invoices | `needs_human` always true; Approve / Leave / Later only |

## License

MIT — see `LICENSE`.
