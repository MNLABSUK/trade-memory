// Why desk: every proposed action shows the Zetaris rows, reasoning, confidence and H-MEM memories behind it.
// Nothing is sent: Approve only queues the item in the outbox for Tom to send.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const gbp = (n) => "£" + Number(n || 0).toLocaleString("en-GB", {maximumFractionDigits: 0});
const STATUS = {pending: "awaiting approval", revised: "revised after rejection", next_step: "next step", done: "done"};
let cards = [], current = new URLSearchParams(location.search).get("case") || "P1";

function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.remove("hidden"); setTimeout(() => t.classList.add("hidden"), 2600); }
async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

function renderTotals(t) {
  $("#totalOut").textContent = gbp(t.outstanding_gbp);
  $("#totalSub").textContent = `across ${t.invoices.length} invoices · computed from tm_ops.invoices`;
  $("#byClient").innerHTML = Object.entries(t.by_client).sort((a, b) => b[1] - a[1])
    .map(([n, v]) => `<div class="bc"><b>${gbp(v)}</b><span>${esc(n)}</span></div>`).join("");
}

function renderList() {
  $("#caseList").innerHTML = cards.map((c) => `
    <button class="case ${c.id === current ? "active" : ""}" data-id="${c.id}">
      <span class="amt">${gbp(c.amount_gbp)}</span><div class="p">${c.id}</div>
      <div class="n">${esc(c.client)}</div><div class="h">${esc(c.headline)}</div>
      <span class="st ${c.status}">${STATUS[c.status] || c.status}</span></button>`).join("");
  document.querySelectorAll(".case").forEach((b) => b.onclick = () => { current = b.dataset.id; renderList(); renderCard(); });
}

function renderCard() {
  const c = cards.find((x) => x.id === current) || cards[0];
  if (!c) return;
  const a = c.action;
  const conf = Math.round((c.confidence || 0) * 100);
  const ev = c.evidence.map((r) => `<tr><td class="tbl">${esc(r.table)}</td><td class="rid">${esc(r.id)}</td>
      <td class="fields">${Object.entries(r.fields).map(([k, v]) => `<span><i>${esc(k)}:</i> ${esc(v)}</span>`).join("")}</td></tr>`).join("");
  const steps = c.reasoning.map((s) => `<li class="${/^H-MEM/.test(s) ? "mem" : ""}">${esc(s)}</li>`).join("");
  const mems = c.memories_used.length ? c.memories_used.map((m) => `<div class="mem">${esc(m.content)}
      <small>${esc(m.label || m.layer)} · ${esc(m.source)} · conf ${m.confidence}</small></div>`).join("") : `<p class="muted">No memories yet.</p>`;
  const qs = c.queries.map((q) => `${q.mode} · ${q.rows} rows · ${q.ms} ms\n${q.sql.trim()}`).join("\n\n");
  const trail = c.trail.length ? `<p class="trail">Decisions so far: ${c.trail.map((t) => esc(`${t.decision} ${t.action}`)).join(" → ")}</p>` : "";
  const act = a ? `
    <div class="sec action">
      <div class="t">${esc(a.title)}</div>
      <div class="ch">Channel: ${esc(a.channel)}${a.to ? " · to " + esc(a.to) : ""}</div>
      <textarea id="draft">${esc(a.draft)}</textarea>
      <input class="note" id="note" placeholder="Note for memory (why you approve or reject)…" />
      <div class="btns">
        <button class="b approve" id="approveBtn">Approve → outbox</button>
        <button class="b reject" id="rejectBtn">Reject, suggest another</button>
        <button class="b polish" id="polishBtn" title="Optional rewrite by Nemotron; cited facts are checked">Polish wording</button>
      </div></div>` : `<div class="sec action"><div class="t">Case closed — nothing left to do.</div></div>`;
  $("#card").innerHTML = `
    <h2>${esc(c.headline)}</h2><p class="client">${esc(c.client)} · ${c.id} · ${gbp(c.amount_gbp)} · ${STATUS[c.status] || c.status}</p>
    <div class="conf ${conf < 75 ? "lowc" : ""}"><b>Confidence ${conf}%</b><div class="bar"><i style="width:${conf}%"></i></div></div>
    ${trail}
    <div class="sec"><h4>Evidence — Zetaris rows</h4><table class="ev">${ev}</table></div>
    <div class="sec"><h4>Reasoning</h4><ol class="steps">${steps}</ol></div>
    <div class="sec"><h4>H-MEM memories used</h4>${mems}</div>
    ${act}
    <div class="sec"><details class="q"><summary>${c.queries.length} federated queries (${esc(c.data_mode)})</summary><pre>${esc(qs)}</pre></details></div>`;
  if (!a) return;
  const decide = async (decision) => {
    try {
      const r = await api(`/api/why/${c.id}/decide`, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({decision, action_id: a.id, note: $("#note").value, draft_text: $("#draft").value})});
      toast(decision === "approve" ? "Approved and queued — not sent" : "Rejected; stored in H-MEM, card revised");
      cards = cards.map((x) => x.id === c.id ? r.card : x);
      renderList(); renderCard(); loadOutbox();
    } catch (e) { toast(e.message); }
  };
  $("#approveBtn").onclick = () => decide("approve");
  $("#rejectBtn").onclick = () => decide("reject");
  $("#polishBtn").onclick = async () => {
    $("#polishBtn").textContent = "Polishing…";
    try {
      const r = await api(`/api/why/${c.id}/polish`, {method: "POST"});
      $("#draft").value = r.draft;
      toast(r.source === "rules" ? (r.rejected_rewrite_missing ? "Rewrite dropped a fact — kept original" : "LLM offline — kept rules draft") : `Polished by ${r.model}`);
    } catch (e) { toast(e.message); }
    $("#polishBtn").textContent = "Polish wording";
  };
}

async function loadOutbox() {
  const {items} = await api("/api/outbox");
  $("#outbox").innerHTML = items.length ? items.slice().reverse().map((i) => `<div class="ob"><b>${esc(i.puzzle)} · ${esc(i.channel)}</b>
     ${i.to ? "→ " + esc(i.to) : ""}<p>${esc(i.body)}</p><span class="muted">${esc(i.note)}</span></div>`).join("")
    : `<p class="muted">Empty. Nothing is queued until you click Approve.</p>`;
}

async function boot() {
  try {
    const d = await api("/api/why");
    cards = d.cards; renderTotals(d.totals);
    const mode = cards[0]?.data_mode || "offline";
    const chip = $("#modeChip");
    chip.textContent = mode === "live" ? "Zetaris: live federated" : "Zetaris: offline replica (same SQL over demo_data)";
    chip.classList.add(mode === "live" ? "live" : "offline");
    renderList(); renderCard(); loadOutbox();
  } catch (e) { $("#card").innerHTML = `<p>Could not load: ${esc(e.message)}</p>`; }
}
boot();
