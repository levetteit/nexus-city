// StarNet Space Station: the 2D Command Board. Same data as the 3D station; every workflow lives here.
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v) => (v == null ? "—" : (v < 0 ? "−$" : "$") + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const ago = (iso) => {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
};
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const STAGE_PILL = { research: "", validate: "cyan", approved: "cyan", build: "cyan", launch: "gold", operate: "green", measure: "green",
  optimize: "green", scale: "green", paused: "red", killed: "red" };
let S = null;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast.h);
  toast.h = setTimeout(() => t.classList.add("hidden"), 3200);
}
async function act(fn, ok) {
  try { await fn(); if (ok) toast(ok); await load(); } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ tabs
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
function show(tab) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("on", s.id === tab));
  history.replaceState(null, "", `#/${tab}`);
  if (tab === "log") loadReports();
}

// ------------------------------------------------------------------ data
async function load() {
  try { S = await api("/api/station"); } catch (e) { $("#coord").textContent = `Station offline: ${e.message}`; return; }
  render();
}

function render() {
  const c = $("#coord");
  c.textContent = `ULTRON · ${S.coordinating}` + (S.ai_enabled ? "" : " · research off (no API key)");
  c.classList.toggle("busy", S.coordinating !== "Watching the portfolio");
  const waiting = S.approvals.length + S.owner_tasks.length;
  $("#n-approvals").textContent = waiting || "";
  renderCommand(); renderApprovals(); renderVentures(); renderIntel(); renderTreasury(); renderCrew(); renderEvents();
}

function stat(k, v, s = "", cls = "") {
  return `<div class="stat"><div class="k">${esc(k)}</div><div class="v ${cls}">${v}</div><div class="s">${esc(s)}</div></div>`;
}

function renderCommand() {
  const m = S.mission || {}, t = S.treasury;
  $("#mission-name").textContent = m.name || "—";
  $("#mission-goal").textContent = m.goal || "";
  $("#mission-flags").innerHTML = [
    m.first_dollar_at ? `<span class="pill green">First dollar ${esc(ago(m.first_dollar_at))}</span>` : `<span class="pill gold">First dollar: not yet</span>`,
    ...t.goals.map((g) => `<span class="pill ${g.funded ? "green" : ""}">${esc(g.name)} · ${Math.round(g.progress * 100)}%</span>`),
  ].join("");
  const live = S.ventures.filter((v) => !["paused", "killed"].includes(v.stage));
  const working = S.agents.filter((a) => ["WORKING", "THINKING"].includes(a.status)).length;
  $("#stats").innerHTML =
    stat("Treasury pool", money(t.pool), `runway ${t.runway_months ?? "—"} months`, t.pool < 0 ? "neg" : "") +
    stat("Active ventures", live.length, `${S.ventures.length} total`) +
    stat("Agents working", working, `${S.agents.length} on the roster`) +
    stat("Waiting for you", S.approvals.length + S.owner_tasks.length, "approvals + tasks", (S.approvals.length + S.owner_tasks.length) ? "neg" : "") +
    stat("AI spend (month)", money(t.ai.spent_month), `cap ${money(t.ai.budget)}`);
  $("#cmd-waiting").innerHTML = waitingList(5) || `<div class="empty">Nothing waiting for you.</div>`;
  $("#cmd-alerts").innerHTML = S.alerts.length ? S.alerts.slice(0, 6).map(evRow).join("") : `<div class="empty">All quiet.</div>`;
  $("#cmd-ventures").innerHTML = S.ventures.map(ventureCard).join("");
  const q = S.queue.slice(0, 8);
  $("#cmd-queue").innerHTML = q.length ? q.map(taskRow).join("") : `<div class="empty">No open tasks. Approve a venture to put the crew to work.</div>`;
  if (S.error) $("#cmd-alerts").insertAdjacentHTML("afterbegin", `<div class="item"><div class="t"><span class="neg">${esc(S.error)}</span></div></div>`);
}

function waitingList(limit) {
  const rows = [
    ...S.approvals.map((a) => `<div class="item wait" data-open="approvals:${a.id}"><div class="t"><span>${esc(a.action)}</span><span class="pill gold">DECIDE</span></div>
      <div class="m">${esc(a.requesting_agent)} · ${a.cost ? money(a.cost) : "$0"} · ${esc(ago(a.requested_at))}</div></div>`),
    ...S.owner_tasks.map((t) => `<div class="item wait" data-open="tasks:${t.id}"><div class="t"><span>${esc(t.title)}</span><span class="pill gold">YOUR TASK</span></div>
      <div class="m">${esc(t.venture)} · ${esc(t.instructions).slice(0, 120)}</div></div>`),
  ];
  return rows.slice(0, limit).join("");
}

function ventureCard(v) {
  const tk = v.tasks || {};
  return `<div class="item" data-open="ventures:${v.id}">
    <div class="t"><span>${esc(v.name)}</span><span class="pill ${STAGE_PILL[v.stage] || ""}">${esc(v.stage)}</span></div>
    <div class="m">${esc(v.id)} · net ${money(v.pnl.net)} · ${tk.done || 0} done · ${tk.waiting_owner || 0} waiting on you · ${tk.queued || 0} queued</div>
    <div class="health"><i style="width:${v.health}%"></i></div></div>`;
}

function taskRow(t) {
  const pill = { waiting_owner: ["gold", "WAITING FOR OWNER"], running: ["green", "working"], blocked: ["", "blocked"], failed: ["red", "failed"],
    queued: ["cyan", "queued"] }[t.status] || ["", t.status];
  return `<div class="item ${t.status === "waiting_owner" ? "wait" : ""}" data-open="tasks:${t.id}">
    <div class="t"><span>${esc(t.title)}</span><span class="pill ${pill[0]}">${esc(pill[1])}</span></div>
    <div class="m">${esc(t.id)} · ${esc(t.venture)} · ${esc(t.assigned_agent === "OWNER" ? "you" : agentName(t.assigned_agent))} · P${t.priority ?? "-"}</div></div>`;
}

function agentName(id) { return (S.agents.find((a) => a.id === id) || {}).name || id; }

function renderApprovals() {
  $("#ap-list").innerHTML = S.approvals.length ? S.approvals.map((a) => `<div class="glass">
      <div class="t row" style="justify-content:space-between"><b>${esc(a.action)}</b><span class="pill gold">WAITING FOR OWNER</span></div>
      <p>${esc(a.reason)}</p>
      <div class="kv"><div>Requested by</div><div>${esc(agentName(a.requesting_agent))}</div>
        <div>Cost</div><div>${a.cost ? money(a.cost) + (a.kind === "fund_goal" ? " / month" : "") : "$0"}</div>
        <div>Reversible</div><div>${a.reversible ? "Yes" : "No"}</div>
        <div>Risk</div><div>${esc(a.risk || "—")}</div>
        ${a.payload?.owner_actions?.length ? `<div>You'll need to</div><div>${a.payload.owner_actions.map(esc).join("<br>")}</div>` : ""}</div>
      ${a.payload?.opportunity ? `<button class="btn" data-open="opportunities:${a.payload.opportunity}">See the research</button>` : ""}
      <div class="actions"><button class="btn primary" data-decide="${a.id}:approve">Approve</button>
        <button class="btn" data-decide="${a.id}:changes">Request changes</button>
        <button class="btn danger" data-decide="${a.id}:reject">Reject</button></div></div>`).join("")
    : `<div class="empty">No decisions waiting.</div>`;
  $("#ot-list").innerHTML = S.owner_tasks.length ? S.owner_tasks.map(taskRow).join("") : `<div class="empty">No tasks waiting on you.</div>`;
}

function renderVentures() {
  const order = ["operate", "scale", "optimize", "measure", "launch", "build", "approved", "validate", "research", "paused", "killed"];
  const vs = [...S.ventures].sort((a, b) => order.indexOf(a.stage) - order.indexOf(b.stage));
  $("#pipeline").innerHTML = vs.map((v) => `<div class="glass" data-open="ventures:${v.id}" style="cursor:pointer">
      <div class="row" style="justify-content:space-between"><b>${esc(v.name)}</b><span class="pill ${STAGE_PILL[v.stage] || ""}">${esc(v.stage)}</span></div>
      <p class="muted small">${esc(v.offer || v.next_action || "")}</p>
      <div class="kv"><div>Income</div><div class="pos">${money(v.pnl.income)}</div><div>Costs</div><div>${money(v.pnl.costs)}</div>
        <div>Net</div><div class="${v.pnl.net < 0 ? "neg" : "pos"}">${money(v.pnl.net)}</div><div>Health</div><div>${v.health}/100</div>
        <div>Next</div><div>${esc(v.next_action || "—")}</div></div>
      <div class="health"><i style="width:${v.health}%"></i></div></div>`).join("");
}

function renderIntel() {
  $("#routines").innerHTML = S.routines.map((r) => `<div class="item" style="cursor:default">
      <div class="t"><span>${esc(r.name)}</span><button class="btn" data-run="${r.id}" ${S.ai_enabled ? "" : "disabled"}>Run now</button></div>
      <div class="m">${r.days.map((d) => DAYS[d]).join("/")} ${esc(r.at)} ET · last run ${esc(ago(r.last_run))} · ${r.runs || 0} runs${r.last_error ? ` · <span class="neg">${esc(r.last_error)}</span>` : ""}</div>
      ${r.last_pick ? `<div class="m">Last pick: ${esc(r.last_pick)}</div>` : ""}</div>`).join("");
  $("#opps").innerHTML = S.opportunities.length ? S.opportunities.map((o) => `<div class="item" data-open="opportunities:${o.id}">
      <div class="t"><span>${esc(o.title)}</span><span class="pill ${o.startup_cost_usd === 0 ? "green" : "gold"}">${o.startup_cost_usd === 0 ? "$0 to start" : money(o.startup_cost_usd)}</span></div>
      <div class="m">Score ${o.score} · ${esc(o.platform)} · first $ in ~${o.days_to_first_dollar}d · ${esc(o.price_point)} · ${esc(o.recommendation.replace("_", " "))}</div></div>`).join("")
    : `<div class="empty">${S.ai_enabled ? "The Market Radar is researching. Opportunities land here." : "Research starts once ANTHROPIC_API_KEY is set on the server."}</div>`;
}

function renderTreasury() {
  const t = S.treasury;
  $("#t-stats").innerHTML = stat("Pool", money(t.pool), "real money only", t.pool < 0 ? "neg" : "") +
    stat("Monthly bills", money(t.monthly_bills), `reserve ${money(t.reserve)}`) +
    stat("Runway", t.runway_months == null ? "—" : `${t.runway_months} mo`, "pool ÷ bills") +
    stat("Paper P&L (City)", money(t.paper_pnl), "not real: never counted");
  const unit = (n, u) => `<div class="item" style="cursor:default"><div class="t"><span>${n}</span><span class="${u.net < 0 ? "neg" : "pos"}">${money(u.net)}</span></div>
    <div class="m">income ${money(u.income)} · costs ${money(u.costs)} (AI ${money(u.ai_costs)})</div></div>`;
  $("#t-units").innerHTML = unit("Trading City", t.city) + unit("Space Station", t.station) +
    `<p class="muted small">${t.carrying ? `The ${t.carrying === "city" ? "City" : "Station"} is carrying the economy right now.` : "Nobody has earned yet: first dollar wins."}</p>`;
  $("#t-goals").innerHTML = t.goals.map((g) => `<div><b>${esc(g.name)}</b> <span class="muted small">${money(g.monthly)}/mo × ${g.months}</span>
      <div class="bar"><i style="width:${Math.round(g.progress * 100)}%"></i></div>
      <div class="muted small">${g.funded ? "Funded: ULTRON has asked you to approve it." : `${money(g.need)} needed on top of a month of bills`}</div></div>`).join("");
  $("#t-bills").innerHTML = t.bills.map((b) => `<div class="item" style="cursor:default"><div class="t"><span>${esc(b.name)}</span><span>${money(b.monthly)}</span></div><div class="m">${esc(b.unit)}</div></div>`).join("");
  $("#t-ledger").innerHTML = t.recent.length ? t.recent.map((e) => `<div class="ev"><div class="when">${esc(ago(e.at))}</div>
      <div><span class="${["income", "lucid_payout"].includes(e.kind) ? "pos" : ""}">${["income", "lucid_payout"].includes(e.kind) ? "+" : "−"}${money(e.amount)}</span>
      ${esc(e.unit)} · ${esc(e.kind.replace("_", " "))} · ${esc(e.note)}</div></div>`).join("") : `<div class="empty">No money in or out yet.</div>`;
  const sel = $("#money select[name=venture]");
  const cur = sel.value;
  sel.innerHTML = `<option value="">No venture</option>` + S.ventures.map((v) => `<option value="${v.id}">${esc(v.id)} ${esc(v.name).slice(0, 30)}</option>`).join("");
  sel.value = cur;
}

function renderCrew() {
  const pod = (a) => `<div class="pod ${a.id === "A-001" ? "ultron" : a.kind === "bot" ? "bot" : ""}" data-open="agents:${a.id}">
      <div class="face">${esc((a.name || "?")[0])}</div><div class="n">${esc(a.name)}</div>
      <div class="muted small">${esc(a.role)}</div><div class="small st-${esc(a.status.replace(" ", "."))}">${esc(a.status)}</div>
      <div class="muted small">${esc(a.current_task || a.last_output || "")}</div></div>`;
  const lounge = S.agents.filter((a) => a.status === "ON BREAK" || a.status === "BENCHED");
  const duty = S.agents.filter((a) => !lounge.includes(a));
  $("#crew-duty").innerHTML = duty.map(pod).join("") || `<div class="empty">Everyone's in the lounge.</div>`;
  $("#crew-lounge").innerHTML = lounge.map(pod).join("") || `<div class="empty">Nobody on break.</div>`;
  const board = [...S.agents].filter((a) => a.kind === "ai").sort((a, b) => (b.tasks_done || 0) - (a.tasks_done || 0));
  $("#crew-board").innerHTML = board.map((a, i) => `<div class="ev"><div class="when">#${i + 1}</div><div>${esc(a.name)} · ${a.tasks_done || 0} tasks delivered</div></div>`).join("");
}

function evRow(e) {
  return `<div class="ev"><div class="when">${esc(ago(e.at))}</div><div><span class="sev-${esc(e.severity.split(" ")[0])}">${e.severity !== "INFO" ? esc(e.severity) + " · " : ""}</span>
    ${esc(e.summary)} <span class="muted small">${esc(e.by)}${e.ref ? " · " + esc(e.ref) : ""}</span></div></div>`;
}
function renderEvents() { $("#events").innerHTML = S.events.map(evRow).join("") || `<div class="empty">No events yet.</div>`; }

async function loadReports() {
  try {
    const reps = await api("/api/station/reports");
    $("#reports").innerHTML = reps.length ? reps.map((r) => `<div class="item" style="cursor:default"><div class="t"><span>${esc(r.date)}</span>
        <span>${money(r.treasury.pool)}</span></div><ul class="tight">${r.recommendations.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        <div class="m">${r.last_24h.opportunities_filed} opportunities · ${r.last_24h.tasks_completed} tasks · ${r.last_24h.failures} failures</div></div>`).join("")
      : `<div class="empty">The first report lands at 08:30 ET.</div>`;
  } catch (e) { $("#reports").textContent = e.message; }
}

// ------------------------------------------------------------------ detail sheet
function sheet(html) { $("#sheet-body").innerHTML = html; $("#sheet").classList.remove("hidden"); }
$("#sheet-x").addEventListener("click", () => $("#sheet").classList.add("hidden"));
$("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") $("#sheet").classList.add("hidden"); });

const list = (xs) => (xs && xs.length ? `<ul class="tight">${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "—");

async function openRecord(col, id) {
  let r;
  try { r = await api(`/api/station/${col}/${id}`); } catch (e) { return toast(e.message); }
  if (col === "opportunities") {
    sheet(`<div class="label">OPPORTUNITY ${esc(r.id)} · ${esc(r.status)}</div><h1>${esc(r.title)}</h1><p>${esc(r.summary)}</p>
      <div class="kv"><div>Score</div><div>${r.score}/100 · ${esc(r.recommendation)}</div><div>Platform</div><div>${esc(r.platform)}</div>
      <div>Startup cost</div><div>${money(r.startup_cost_usd)} (+${money(r.monthly_cost_usd)}/mo)</div><div>Start today</div><div>${r.can_start_today ? "Yes" : "No"}</div>
      <div>First dollar</div><div>~${r.days_to_first_dollar} days</div><div>Price</div><div>${esc(r.price_point)}</div>
      <div>Demand / competition</div><div>${r.demand}/10 · ${r.competition}/10</div><div>Automation</div><div>${r.automation_potential}/10</div>
      <div>Platform rules</div><div>${esc(r.platform_restrictions)}</div></div>
      <h2>Evidence</h2>${list(r.evidence)}<h2>What you'd do</h2>${list(r.owner_actions)}<h2>First 7 days</h2>${list(r.plan_7_day)}
      <h2>Risks</h2>${list(r.risks)}<div class="kv"><div>Success</div><div>${esc(r.success_criteria)}</div><div>Kill</div><div>${esc(r.kill_criteria)}</div></div>
      <h2>Sources</h2>${(r.sources || []).map((s) => `<div><a href="${esc(s.url)}" target="_blank" rel="noopener" style="color:var(--cyan)">${esc(s.title)}</a></div>`).join("") || "—"}
      ${r.status === "open" ? `<div class="actions"><button class="btn primary" data-promote="${r.id}">Promote to venture</button><button class="btn danger" data-dismiss="${r.id}">Dismiss</button></div>` : ""}`);
  } else if (col === "ventures") {
    sheet(`<div class="label">VENTURE ${esc(r.id)} · ${esc(r.stage)} · health ${r.health}</div><h1>${esc(r.name)}</h1>
      <div class="kv"><div>Offer</div><div>${esc(r.offer || "—")}</div><div>Objective</div><div>${esc(r.objective || "—")}</div>
      <div>Income / costs</div><div>${money(r.pnl.income)} / ${money(r.pnl.costs)}</div><div>Success</div><div>${esc(r.success_criteria || "—")}</div>
      <div>Kill</div><div>${esc(r.kill_criteria || "—")}</div><div>Validation</div><div>${esc(r.validation ? r.validation.verdict + ": " + r.validation.why : "—")}</div></div>
      <h2>Tasks</h2>${(r.task_list || []).map(taskRow).join("") || `<div class="empty">No tasks yet.</div>`}
      ${r.id !== "V-001" ? `<h2>Move it</h2><div class="actions">${["launch", "operate", "scale", "paused", "killed"].map((s) => `<button class="btn ${s === "killed" ? "danger" : ""}" data-stage="${r.id}:${s}">${s}</button>`).join("")}</div>` : ""}`);
  } else if (col === "tasks") {
    const deps = await Promise.all((r.depends_on || []).map((d) => api(`/api/station/tasks/${d}`).catch(() => null)));
    const out = r.output && r.output.deliverable;
    sheet(`<div class="label">TASK ${esc(r.id)} · ${esc(r.status.replace("_", " "))}</div><h1>${esc(r.title)}</h1>
      <div class="kv"><div>Venture</div><div>${esc(r.venture)}</div><div>Owner</div><div>${esc(r.assigned_agent === "OWNER" ? "You" : agentName(r.assigned_agent))}</div>
      <div>Why / how</div><div>${esc(r.instructions)}</div><div>Expected</div><div>${esc(r.expected_output)}</div>
      <div>Success</div><div>${esc(r.success_criteria)}</div>${r.escalate_if ? `<div>Escalate if</div><div>${esc(r.escalate_if)}</div>` : ""}
      ${r.error ? `<div>Error</div><div class="neg">${esc(r.error)}</div>` : ""}</div>
      ${deps.filter((d) => d && d.output).map((d) => `<h2>Input: ${esc(d.title)}</h2><pre class="deliver">${esc(d.output.deliverable)}</pre>
        <button class="btn" data-copy="${esc(d.id)}">Copy</button>`).join("")}
      ${out ? `<h2>Deliverable</h2><pre class="deliver">${esc(out)}</pre><button class="btn" data-copy="${esc(r.id)}">Copy</button>
        ${r.output.notes ? `<p class="muted small">${esc(r.output.notes)}</p>` : ""}${r.output.owner_next?.length ? `<h2>You do next</h2>${list(r.output.owner_next)}` : ""}` : ""}
      ${r.kind === "owner" && r.status !== "done" ? `<div class="actions"><input id="done-note" placeholder="Note (optional): e.g. gig link" />
        <button class="btn primary" data-done="${r.id}">Mark done</button></div>` : ""}`);
    sheet.copy = Object.fromEntries([r, ...deps].filter((d) => d && d.output).map((d) => [d.id, d.output.deliverable]));
  } else if (col === "agents") {
    sheet(`<div class="label">AGENT ${esc(r.id)} · ${esc(r.status)}</div><h1>${esc(r.name)}</h1>
      <div class="kv"><div>Role</div><div>${esc(r.role)}</div><div>Department</div><div>${esc(r.department)}</div><div>Specialty</div><div>${esc(r.specialty)}</div>
      <div>Current task</div><div>${esc(r.current_task || "—")}</div><div>Delivered</div><div>${r.tasks_done || 0} tasks</div>
      <div>Cost to run</div><div>${money(r.pnl.ai_costs)} AI</div></div><h2>Work</h2>${(r.task_list || []).map(taskRow).join("") || `<div class="empty">No tasks.</div>`}`);
  } else if (col === "approvals") {
    show("approvals");
  }
}

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-open],[data-decide],[data-promote],[data-dismiss],[data-run],[data-done],[data-stage],[data-copy]");
  if (!el) return;
  const d = el.dataset;
  if (d.decide) {
    const [id, decision] = d.decide.split(":");
    const note = decision === "approve" ? "" : prompt(decision === "reject" ? "Why not? (optional)" : "What should change?") ?? null;
    if (note === null) return;
    return act(() => api(`/api/station/approvals/${id}`, { decision, note }), decision === "approve" ? "Approved. ULTRON is on it." : "Sent back.");
  }
  if (d.promote) return act(() => api(`/api/station/opportunities/${d.promote}/promote`, {}), "Promoted. The Validation Agent is planning it.").then(() => $("#sheet").classList.add("hidden"));
  if (d.dismiss) return act(() => api(`/api/station/opportunities/${d.dismiss}/dismiss`, {}), "Dismissed.").then(() => $("#sheet").classList.add("hidden"));
  if (d.run) return act(() => api(`/api/station/routines/${d.run}/run`, {}), "Routine started.");
  if (d.done) return act(() => api(`/api/station/tasks/${d.done}/done`, { note: ($("#done-note") || {}).value || "" }), "Done. Next tasks are unblocked.").then(() => $("#sheet").classList.add("hidden"));
  if (d.stage) {
    const [id, stage] = d.stage.split(":");
    if (stage === "killed" && !confirm("Kill this venture?")) return;
    return act(() => api(`/api/station/ventures/${id}/stage`, { stage }), `Moved to ${stage}.`).then(() => openRecord("ventures", id));
  }
  if (d.copy) return navigator.clipboard.writeText((sheet.copy || {})[d.copy] || "").then(() => toast("Copied"), () => toast("Copy failed"));
  if (d.open) { const [col, id] = d.open.split(":"); openRecord(col, id); }
});

$("#money").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  act(() => api("/api/station/money", { ...f, amount: parseFloat(f.amount) }), "Recorded.").then(() => e.target.reset());
});

const fromHash = () => {
  const tab = location.hash.replace(/^#\/?/, "");
  show(document.getElementById(tab)?.classList.contains("tab") ? tab : "command");
};
addEventListener("hashchange", fromHash);
fromHash();
load();
setInterval(load, 10000);
