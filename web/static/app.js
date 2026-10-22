(() => {
  let allChases = [];
  let clients = {};
  let jobs = {};
  let notes = [];
  let activity = [];
  let decisions = [];
  let decisionsByChase = {};
  let selectedId = null;
  let showClosed = false;
  let lastApproved = null;
  let lastDigest = null;

  const $ = (id) => document.getElementById(id);

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!res.ok) throw new Error((await res.text()) || res.statusText);
    return res.json();
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function money(n) {
    const v = Number(n);
    if (!Number.isFinite(v)) return "£—";
    try {
      return new Intl.NumberFormat("en-GB", {
        style: "currency",
        currency: "GBP",
        maximumFractionDigits: v % 1 === 0 ? 0 : 2,
      }).format(v);
    } catch {
      return "£" + v;
    }
  }

  function toast(msg, kind) {
    const el = $("toast");
    el.textContent = msg;
    el.className = "toast " + (kind === "err" ? "err" : kind === "ok" ? "ok" : "");
    el.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.add("hidden"), 3200);
  }

  function setBusy(on, label) {
    $("ambientWrap").classList.toggle("busy", on);
    $("pulseLabel").textContent = on ? label || "Working…" : "Ready";
    [
      "proposeBtn", "approveBtn", "leaveBtn", "laterBtn", "recallGo", "noteBtn",
      "recallBtn", "reopenBtn", "digestBtn",
    ].forEach((id) => {
      const el = $(id);
      if (el) el.disabled = on;
    });
  }

  function clientName(id) {
    return (clients[id] && clients[id].name) || id || "—";
  }

  function urgency(c) {
    const d = c.days_overdue || 0;
    if (d >= 30) return "critical";
    if (d >= 7) return "high";
    if (d > 0) return "medium";
    return "low";
  }

  function renderStats(stats) {
    $("statOverdue").textContent = money(stats.overdue_gbp);
    $("statOpen").textContent = String(stats.open_chases ?? "—");
    $("statLater").textContent = String(stats.later_count ?? "—");
    $("statNotes").textContent = String(stats.notes ?? "—");
    $("statClients").textContent = String(stats.clients ?? "—");
    $("statDecisions").textContent = String(stats.decisions_today ?? "—");
  }

  function renderApprovedStrip() {
    const strip = $("approvedStrip");
    const body = $("approvedBody");
    // Prefer in-session approve; else latest approve from decisions
    let draft = lastApproved;
    if (!draft) {
      const hit = decisions.find((d) => d.decision === "approve" && d.draft_text);
      if (hit) {
        draft = {
          chase_id: hit.chase_id,
          draft_text: hit.draft_text,
          at: hit.at,
        };
      }
    }
    if (!draft || !draft.draft_text) {
      strip.classList.add("hidden");
      return;
    }
    const when = String(draft.at || "").replace("T", " ").slice(0, 16);
    body.textContent =
      (draft.chase_id ? draft.chase_id + " · " : "") +
      (when ? when + "\n" : "") +
      draft.draft_text;
    strip.classList.remove("hidden");
  }

  function renderDigestPanel(digest) {
    const el = $("digestPanel");
    if (!digest) {
      el.classList.add("hidden");
      el.innerHTML = "";
      return;
    }
    const lines = (digest.work_order || [])
      .map((l) => `<li>${esc(l.replace(/^\d+\.\s*/, "").replace(/^•\s*/, ""))}</li>`)
      .join("");
    el.innerHTML = `
      <h3>${esc(digest.headline || "Morning digest")}</h3>
      <div>Total overdue: <span class="digest-total">${esc(money(digest.total_gbp))}</span>
        · ${esc(String(digest.overdue_count ?? 0))} chase(s)</div>
      <ol>${lines || "<li>Nothing overdue</li>"}</ol>
      <p class="digest-recall">${esc(digest.memory_recall || "")}</p>`;
    el.classList.remove("hidden");
  }

  function visibleChases() {
    if (showClosed) {
      return allChases.filter((c) => c.status === "closed" || c.status === "later");
    }
    return allChases.filter((c) =>
      c.status === "open" || c.status === "waiting" || c.status === "later"
    );
  }

  function renderChases() {
    const list = $("chaseList");
    const items = visibleChases();
    $("chaseCount").textContent = items.length ? String(items.length) : "";
    if (!items.length) {
      list.innerHTML = `<div class="empty-state">${showClosed ? "No closed/later chases." : "No open chases."}</div>`;
      return;
    }
    list.innerHTML = items
      .map((c) => {
        const active = c.id === selectedId ? " active" : "";
        const odClass = (c.days_overdue || 0) > 0 ? " overdue" : "";
        const od = c.days_overdue > 0 ? `${c.days_overdue}d overdue` : c.status;
        const amt = c.amount != null ? money(c.amount) : "";
        const urg = urgency(c);
        return `<div class="chase-card${active}${odClass}" data-id="${esc(c.id)}" tabindex="0">
          <div class="cid">${esc(c.id)} · ${esc(c.invoice_ref || "—")}</div>
          <h3>${esc(c.summary || c.id)}</h3>
          <p class="sub">${esc(clientName(c.client_id))} · ${esc(od)}${amt ? " · " + amt : ""}</p>
          <div class="badge-row">
            <span class="urgency ${urg}">${urg}</span>
            <span class="pill ${esc(c.status)}">${esc(c.status)}</span>
          </div>
        </div>`;
      })
      .join("");
    list.querySelectorAll(".chase-card").forEach((el) => {
      el.addEventListener("click", () => selectChase(el.dataset.id));
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectChase(el.dataset.id);
        }
      });
    });
  }

  function renderNotes() {
    const el = $("notesList");
    if (!notes.length) {
      el.innerHTML = '<div class="empty-state">No notes yet.</div>';
      return;
    }
    el.innerHTML = notes
      .slice(0, 14)
      .map(
        (n) => `<div class="note-item">
        <div>${esc(n.text)}</div>
        <div class="note-meta">${esc(n.id)}${n.related_chase_id ? " · " + esc(n.related_chase_id) : ""}${n.related_job_id ? " · " + esc(n.related_job_id) : ""}</div>
      </div>`
      )
      .join("");
  }

  function renderJobsClients() {
    const el = $("jobsClientsList");
    const rows = [];
    Object.values(clients).forEach((c) => {
      rows.push(`<div class="mini-item" data-client="${esc(c.id)}">
        <strong>${esc(c.name)}</strong>
        <div class="sub">${esc(c.contact || c.trade || "")}</div>
      </div>`);
    });
    Object.values(jobs)
      .slice(0, 8)
      .forEach((j) => {
        rows.push(`<div class="mini-item" data-job="${esc(j.id)}">
          <strong>${esc(j.title)}</strong>
          <div class="sub">${esc(j.address || j.status)} · ${esc(clientName(j.client_id))}</div>
        </div>`);
      });
    el.innerHTML = rows.join("") || '<div class="empty-state">No clients/jobs.</div>';
    el.querySelectorAll("[data-client]").forEach((node) => {
      node.addEventListener("click", () => {
        const cid = node.dataset.client;
        const hit =
          allChases.find(
            (c) =>
              c.client_id === cid &&
              (c.status === "open" || c.status === "waiting" || c.status === "later")
          ) || allChases.find((c) => c.client_id === cid);
        if (hit) selectChase(hit.id);
        doRecall(clients[cid]?.name || cid);
      });
    });
  }

  function renderActivity() {
    const el = $("activityList");
    if (!activity.length) {
      el.innerHTML = '<div class="empty-state">No activity yet.</div>';
      return;
    }
    el.innerHTML = activity
      .slice(0, 24)
      .map((a) => {
        const when = String(a.at || "").replace("T", " ").slice(0, 16);
        const clickable = a.chase_id ? " clickable" : "";
        return `<div class="activity-row${clickable}" data-chase="${esc(a.chase_id || "")}">
          <div class="activity-top">
            <span class="activity-action">${esc(a.action || "")}</span>
            <span class="activity-time">${esc(when)}</span>
          </div>
          <p class="activity-detail">${esc(a.detail || "")}</p>
        </div>`;
      })
      .join("");
    el.querySelectorAll(".activity-row").forEach((node) => {
      if (node.dataset.chase) {
        node.addEventListener("click", () => selectChase(node.dataset.chase));
      }
    });
  }

  function selectChase(id, { keepDigest } = {}) {
    selectedId = id;
    const c = allChases.find((x) => x.id === id);
    renderChases();
    if (!c) {
      $("emptyState").classList.remove("hidden");
      $("detail").classList.add("hidden");
      return;
    }
    $("emptyState").classList.add("hidden");
    $("detail").classList.remove("hidden");
    if (!keepDigest) renderDigestPanel(null);
    else if (lastDigest) renderDigestPanel(lastDigest);

    const cl = clients[c.client_id];
    const job = c.job_id ? jobs[c.job_id] : null;
    const urg = urgency(c);

    $("detailSubject").textContent = c.summary || c.id;
    $("detailFrom").textContent = clientName(c.client_id);
    $("detailMeta").textContent = [
      c.invoice_ref || null,
      c.days_overdue ? c.days_overdue + " days overdue" : null,
      "status " + c.status,
      c.last_action || null,
      c.snooze_until ? "snooze " + c.snooze_until : null,
    ]
      .filter(Boolean)
      .join(" · ");
    $("detailContact").textContent = cl
      ? `Contact: ${cl.contact || "—"} · ${cl.trade || ""}`
      : "";
    $("detailAddress").textContent = job
      ? `Job: ${job.title} · ${job.address || "—"}`
      : c.job_id
        ? `Job: ${c.job_id}`
        : "";
    $("detailBody").textContent = [
      c.summary,
      c.history && c.history.length ? "\n\nHistory:\n- " + c.history.join("\n- ") : "",
      c.draft_action ? "\n\nLast draft:\n" + c.draft_action : "",
      c.decision
        ? "\n\nDecision: " + c.decision + (c.decision_note ? " — " + c.decision_note : "")
        : "",
    ].join("");

    $("detailStatus").textContent = c.status;
    $("detailStatus").className = "pill " + c.status;
    if (c.amount != null) {
      $("detailMoney").textContent = money(c.amount);
      $("detailMoney").classList.remove("hidden");
    } else {
      $("detailMoney").classList.add("hidden");
    }
    $("detailUrgency").textContent = urg;
    $("detailUrgency").className = "urgency " + urg;
    $("draftArea").value = c.draft_action || "";
    $("agentSummary").textContent = c.summary || "";
    $("triageState").textContent = c.draft_action ? "Draft ready" : "Not proposed yet";

    const closed = c.status === "closed" || c.status === "later";
    $("reopenBtn").classList.toggle("hidden", !closed);
    $("approveBtn").disabled = c.status === "closed";
    $("leaveBtn").disabled = c.status === "closed";
    $("laterBtn").disabled = c.status === "closed";

    const priors = decisionsByChase[c.id] || [];
    if (priors.length) {
      $("priorDecisions").classList.remove("hidden");
      $("priorList").innerHTML = priors
        .slice(0, 6)
        .map(
          (d) =>
            `<li><strong>${esc(d.decision)}</strong> — ${esc(d.note || d.draft_text || "—")} <span class="muted">${esc(String(d.at || "").slice(0, 16))}</span></li>`
        )
        .join("");
    } else {
      $("priorDecisions").classList.add("hidden");
      $("priorList").innerHTML = "";
    }
  }

  function clearSelection() {
    selectedId = null;
    lastDigest = null;
    renderChases();
    renderDigestPanel(null);
    $("emptyState").classList.remove("hidden");
    $("detail").classList.add("hidden");
  }

  function setFailOpen(open) {
    $("failDrawer").classList.toggle("hidden", !open);
    $("failBackdrop").classList.toggle("hidden", !open);
    $("failBackdrop").setAttribute("aria-hidden", open ? "false" : "true");
  }

  async function refresh() {
    const [health, mem, closed, act] = await Promise.all([
      api("/api/health"),
      api("/api/memory"),
      api("/api/chases?open_only=false"),
      api("/api/activity"),
    ]);
    $("dryBadge").classList.toggle("hidden", !health.dry_run);
    $("providerLine").textContent = `${health.provider} · ${(health.model || "").split("/").pop()}`;

    const stats = { ...(mem.stats || {}), ...(act.stats || {}) };
    renderStats(stats);

    clients = {};
    (mem.clients || []).forEach((c) => {
      clients[c.id] = c;
    });
    jobs = {};
    (mem.jobs || []).forEach((j) => {
      jobs[j.id] = j;
    });
    allChases = closed.chases || mem.chases || [];
    notes = mem.notes || [];
    activity = act.activity || [];
    decisions = mem.decisions || [];
    decisionsByChase = {};
    decisions.forEach((d) => {
      if (!decisionsByChase[d.chase_id]) decisionsByChase[d.chase_id] = [];
      decisionsByChase[d.chase_id].push(d);
    });

    renderChases();
    renderNotes();
    renderJobsClients();
    renderActivity();
    renderApprovedStrip();

    if (selectedId) selectChase(selectedId, { keepDigest: !!lastDigest });
    else if (mem.session && mem.session.last_chase_id) selectChase(mem.session.last_chase_id);
  }

  async function doRecall(q) {
    setBusy(true, "Recalling…");
    try {
      const data = await api("/api/recall", {
        method: "POST",
        body: JSON.stringify({ query: q || "what were we chasing?" }),
      });
      $("recallAnswer").textContent = data.answer || "—";
      if (data.focus && data.focus.id) {
        if (data.focus.status === "closed") {
          showClosed = true;
          $("showClosed").classList.add("active-toggle");
          $("showOpen").classList.remove("active-toggle");
        }
        await refresh();
        selectChase(data.focus.id);
      } else {
        await refresh();
      }
      toast("Memory recalled", "ok");
    } catch (e) {
      $("recallAnswer").textContent = "Recall failed: " + e.message;
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function doDigest() {
    setBusy(true, "Digest…");
    try {
      const data = await api("/api/digest");
      lastDigest = data;
      $("recallAnswer").textContent = data.memory_recall || data.headline || "—";
      showClosed = false;
      $("showOpen").classList.add("active-toggle");
      $("showClosed").classList.remove("active-toggle");
      await refresh();
      if (data.top_chase_id) {
        selectChase(data.top_chase_id, { keepDigest: true });
      }
      renderDigestPanel(data);
      toast("Morning digest ready", "ok");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function doPropose() {
    if (!selectedId) return;
    setBusy(true, "Proposing…");
    $("thinkingPanel").classList.remove("hidden");
    try {
      const data = await api("/api/propose", {
        method: "POST",
        body: JSON.stringify({ chase_id: selectedId }),
      });
      $("draftArea").value = (data.proposal && data.proposal.draft_action) || "";
      $("agentSummary").textContent = (data.proposal && data.proposal.summary) || "";
      $("triageState").textContent =
        "Proposed · " + ((data.proposal && data.proposal.source) || "");
      await refresh();
      selectChase(selectedId, { keepDigest: !!lastDigest });
      toast("Proposal ready — human gate", "ok");
    } catch (e) {
      toast(e.message, "err");
      showBoot(e.message);
    } finally {
      $("thinkingPanel").classList.add("hidden");
      setBusy(false);
    }
  }

  async function doDecide(decision) {
    if (!selectedId) return;
    const draftText = $("draftArea").value;
    const chaseId = selectedId;
    setBusy(true, "Recording…");
    try {
      const body = {
        chase_id: chaseId,
        decision,
        draft_text: draftText,
      };
      if (decision === "later") {
        body.snooze_until = new Date(Date.now() + 86400000).toISOString();
        body.note = "Snoozed +1 day from desk";
      }
      await api("/api/decide", { method: "POST", body: JSON.stringify(body) });
      if (decision === "approve") {
        lastApproved = {
          chase_id: chaseId,
          draft_text: draftText,
          at: new Date().toISOString(),
        };
      }
      toast(
        decision === "approve"
          ? "Approved — logged"
          : decision === "leave"
            ? "Left it"
            : "Parked for later",
        "ok"
      );
      selectedId = null;
      lastDigest = null;
      await refresh();
      $("emptyState").classList.remove("hidden");
      $("detail").classList.add("hidden");
      renderApprovedStrip();
      await doRecall("what were we chasing?");
    } catch (e) {
      toast(e.message, "err");
      showBoot(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function doReopen() {
    if (!selectedId) return;
    setBusy(true, "Reopening…");
    try {
      await api(`/api/chases/${selectedId}/reopen`, {
        method: "POST",
        body: JSON.stringify({ note: "Reopened from desk" }),
      });
      showClosed = false;
      $("showClosed").classList.remove("active-toggle");
      $("showOpen").classList.add("active-toggle");
      await refresh();
      selectChase(selectedId);
      toast("Chase reopened", "ok");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function doAddNote() {
    const text = ($("noteInput").value || "").trim();
    if (!text) return;
    setBusy(true, "Saving note…");
    try {
      const c = allChases.find((x) => x.id === selectedId);
      await api("/api/notes", {
        method: "POST",
        body: JSON.stringify({
          text,
          related_chase_id: selectedId || null,
          related_client_id: c ? c.client_id : null,
          related_job_id: c ? c.job_id : null,
        }),
      });
      $("noteInput").value = "";
      await refresh();
      toast("Note saved to memory", "ok");
    } catch (e) {
      toast(e.message, "err");
      showBoot(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function doFollowup(message) {
    const msg = (message || "").trim();
    if (!msg) return;
    setBusy(true, "Follow-up…");
    try {
      const data = await api("/api/followup", {
        method: "POST",
        body: JSON.stringify({ message: msg, chase_id: selectedId || null }),
      });
      $("recallAnswer").textContent = data.reply || "—";
      if (data.draft) $("draftArea").value = data.draft;
      await refresh();
      if (data.focus_chase_id) selectChase(data.focus_chase_id);
      toast(data.kind ? `Follow-up · ${data.kind}` : "Follow-up done", "ok");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  function showBoot(msg) {
    const el = $("bootError");
    el.textContent = msg || "";
    el.classList.toggle("hidden", !msg);
  }

  $("recallBtn").addEventListener("click", () => doRecall("what were we chasing?"));
  $("recallGo").addEventListener("click", () => doRecall($("recallInput").value));
  $("recallInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doRecall($("recallInput").value);
  });
  $("proposeBtn").addEventListener("click", doPropose);
  $("approveBtn").addEventListener("click", () => doDecide("approve"));
  $("leaveBtn").addEventListener("click", () => doDecide("leave"));
  $("laterBtn").addEventListener("click", () => doDecide("later"));
  $("reopenBtn").addEventListener("click", doReopen);
  $("noteBtn").addEventListener("click", doAddNote);
  $("noteInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doAddNote();
  });
  $("digestBtn").addEventListener("click", doDigest);
  $("failBtn").addEventListener("click", () => setFailOpen(true));
  $("failClose").addEventListener("click", () => setFailOpen(false));
  $("failBackdrop").addEventListener("click", () => setFailOpen(false));
  $("showOpen").addEventListener("click", () => {
    showClosed = false;
    $("showOpen").classList.add("active-toggle");
    $("showClosed").classList.remove("active-toggle");
    renderChases();
  });
  $("showClosed").addEventListener("click", () => {
    showClosed = true;
    $("showClosed").classList.add("active-toggle");
    $("showOpen").classList.remove("active-toggle");
    renderChases();
  });
  $("suggestChips").querySelectorAll(".chip-btn").forEach((b) => {
    b.addEventListener("click", () => {
      if (b.dataset.action === "digest") {
        doDigest();
        return;
      }
      const q = b.dataset.q;
      $("recallInput").value = q;
      if (/overdue|who\s/i.test(q) || q.toLowerCase().startsWith("who")) doFollowup(q);
      else doRecall(q);
    });
  });
  $("followupForm").addEventListener("submit", (e) => {
    e.preventDefault();
    doFollowup($("followupInput").value);
    $("followupInput").value = "";
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!$("failDrawer").classList.contains("hidden")) setFailOpen(false);
      else clearSelection();
    }
  });

  refresh()
    .then(() => doRecall("what were we chasing?"))
    .catch((e) => showBoot("Boot failed: " + e.message));
})();
