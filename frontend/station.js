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
  if (tab === "treasury") loadFinance();
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
  $("#n-outbox").textContent = (S.outbox.manual.length + S.outbox.waiting_owner.length) || "";
  renderCommand(); renderApprovals(); renderVentures(); renderIntel(); renderTreasury(); renderCrew(); renderEvents();
  renderOutbound(); renderMarketing(); renderWarRoom(); renderLegal();
}

function stat(k, v, s = "", cls = "") {
  return `<div class="stat"><div class="k">${esc(k)}</div><div class="v ${cls}">${v}</div><div class="s">${esc(s)}</div></div>`;
}

function renderCredits() {
  const c = S.credits;
  if (!c) return;
  const el = $("#credits");
  el.className = `glass credits ${c.state}`;
  const big = c.state === "empty" ? "Empty" : c.remaining == null ? "Not recorded" : money(c.remaining);
  const why = {
    empty: "Anthropic says the balance is used up. The agents wait and try again every 20 minutes.",
    low: "Running low: top up in the Anthropic Console, then record it here.",
    ok: "The agents can work.",
    unknown: "Record what you added in the Anthropic Console so the station can count down from it.",
  }[c.state] || "";
  el.innerHTML = `<div class="label">CLAUDE CREDITS LEFT</div><div class="big">${big}</div>
    <div class="muted small">${esc(why)}</div>
    <div class="muted small" style="margin-top:6px">Added ${money(c.added)} · used ${money(c.used)} since ${c.since ? esc(ago(c.since)) : "—"} · today ${money(c.today)} · ${money(c.per_day_7d)}/day this week${c.days_left ? ` · about ${c.days_left} days left` : ""}${c.reported != null ? ` · Anthropic's report ${money(c.reported)}` : c.admin_key ? "" : " · add ANTHROPIC_ADMIN_KEY to check against Anthropic's own report"}</div>
    <div class="row"><input id="cr-amount" type="number" min="1" step="1" placeholder="$ added" inputmode="decimal" /><button class="btn primary" id="cr-add">I added credits</button>
      <a class="btn" href="https://console.anthropic.com/settings/billing" target="_blank" rel="noopener">Anthropic billing</a></div>`;
  $("#cr-add").onclick = () => {
    const amount = parseFloat($("#cr-amount").value);
    if (!(amount > 0)) return;
    act(() => api("/api/station/credits", { amount }), `Recorded ${money(amount)} of credits.`);
  };
}

function renderCommand() {
  renderCredits();
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
    stat("Leads (7 days)", (S.leads || []).filter((l) => Date.now() - new Date(l.created_at) < 7 * 864e5).length,
      `${(S.leads || []).filter((l) => l.status === "won").length} won all-time`) +
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

// An owner's Etsy scan task, done by the server through the Etsy API (backend/station/etsyscan.py)
function scanBox(r, info) {
  const sc = r.scan || {};
  if (sc.state === "running") return `<h2>Etsy scan</h2><p class="muted small">Running through the Etsy API since ${ago(sc.at)}. The task closes itself with the results.</p>`;
  if (r.status === "done" && sc.csv) return `<p class="small"><a href="${esc(sc.csv)}" download>Download the full scan (CSV)</a></p>`;
  if (!info) return "";
  if (!info.etsy) return `<h2>Etsy scan</h2><p class="muted small">Connect Etsy (Marketing) and the station can run this scan for you.</p>`;
  const text = info.terms.map((t, i) => `${t} | ${i < 2 ? 20 : 5}`).join("\n");
  return `<h2>Let the station run it</h2>
    <p class="muted small">The server reads Etsy through its API: real prices, review counts, shop sales and favorites for the top digital listings per phrase. The API can't see ads, Bestseller badges or sale prices, so those are marked NS. Pinterest isn't covered. One phrase per line, with how many listings to capture.</p>
    ${sc.state === "failed" ? `<p class="neg small">Last try failed: ${esc(sc.error || "")}</p>` : ""}
    <textarea id="scan-terms" rows="8" style="width:100%">${esc(text)}</textarea>
    <div class="actions"><button class="btn primary" data-scan="${r.id}">Run the scan with the Etsy API</button></div>`;
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

// ------------------------------------------------------------------ outbound, marketing, war room, legal, finance
const KIND = { "social.post": "Post", "outreach.email": "Email", "stripe.payment_link": "Checkout" };
function actionRow(a) {
  const p = a.payload || {};
  const label = a.kind === "social.post" ? `${p.platform}: ${p.text}` : a.kind === "outreach.email" ? `${p.company}: ${p.subject}`
    : `${p.name} · ${money(p.price_usd)}`;
  return `<div class="item ${["manual", "waiting_owner"].includes(a.status) ? "wait" : ""}" data-open="actions:${a.id}">
    <div class="t"><span>${esc(label).slice(0, 110)}</span><span class="pill ${a.status === "sent" ? "green" : a.status === "rejected" ? "red" : "gold"}">${esc(KIND[a.kind] || a.kind)}</span></div>
    <div class="m">${esc(a.id)} · ${esc(a.venture || "")} · ${esc(a.status.replace("_", " "))}${a.manual_reason ? " · " + esc(a.manual_reason) : ""}${metricsText((a.result || {}).metrics)}</div></div>`;
}

const SRC = { dm: "DM", whatsapp: "WhatsApp", call: "Llamada", comment: "Comentario", referral: "Referido", other: "Otro" };
function metricsText(m) {
  if (!m) return "";
  return " · " + Object.entries(m).map(([k, v]) => `${v} ${k}`).join(", ");
}
function leadRow(l) {
  const pill = { new: "cyan", quoted: "gold", won: "green", lost: "red" }[l.status];
  return `<div class="item" style="cursor:default"><div class="t"><span>${esc(SRC[l.source] || l.source)}${l.note ? " · " + esc(l.note) : ""}</span>
    <span class="pill ${pill}">${esc(l.status)}${l.status === "won" ? " " + money(l.amount) : ""}</span></div>
    <div class="m">${esc(l.id)} · ${esc(ago(l.created_at))}${l.action ? " · from post " + esc(l.action) : ""}</div>
    ${["new", "quoted"].includes(l.status) ? `<div class="actions">${l.status === "new" ? `<button class="btn" data-lead="${l.id}:quoted">Quoted</button>` : ""}
      <button class="btn primary" data-lead="${l.id}:won">Won</button><button class="btn danger" data-lead="${l.id}:lost">Lost</button></div>` : ""}</div>`;
}

function renderOutbound() {
  const box = $(".outbound");
  box.classList.toggle("off", !S.outbound);
  $("#ob-text").textContent = S.outbound ? `on · ${S.outbox.in_qa} in QA · ${S.outbox.sent.length} sent recently` : "STOPPED: nothing leaves the station";
  $("#ob-toggle").textContent = S.outbound ? "Stop all outbound" : "Turn outbound on";
  $("#ob-toggle").className = S.outbound ? "btn danger" : "btn primary";
}
$("#ob-toggle").addEventListener("click", () => {
  if (S.outbound && !confirm("Stop every outgoing post, email and Stripe change now?")) return;
  act(() => api("/api/station/outbound", { on: !S.outbound }), S.outbound ? "Outbound stopped." : "Outbound on.");
});

const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
function shopSection(sh) {
  const item = (x, extra) => `<div class="row" style="display:flex;gap:10px;align-items:center">${x.image ? `<img src="/media/${esc(x.image)}" alt="" style="width:48px;height:56px;object-fit:contain;background:${x.ink === "light" ? "#1d1d22" : "#f3efe6"};border-radius:6px;flex:none">` : ""}<div><b>${esc(x.title)}</b><div class="muted small">${extra}</div></div></div>`;
  return `<h2>The shop</h2><div class="kv"><div>Etsy via Printify</div><div>${sh.connected ? "connected" : "waiting for PRINTIFY_API_TOKEN on Render"}</div>
    <div>Orders (30 days)</div><div>${plural(sh.orders_30d, "order")}, ${plural(sh.units_30d, "unit")} · ${money(sh.retail_30d)} retail, ${money(sh.cost_30d)} product cost</div>
    <div>New listings</div><div>up to ${sh.per_day} a day ($0.20 each on Etsy)</div></div>
    <p class="muted small">Etsy deposits aren't booked automatically: record them in Finance when they land.</p>
    <h2>Live listings</h2>${sh.live.map((x) => item(x, `${esc(x.type)} · ${x.price_cents ? money(x.price_cents[0] / 100) : ""} · ${plural(x.orders, "order")}`)).join("") || `<div class="empty">Nothing listed yet.</div>`}
    <h2>In the works</h2>${sh.drafts.map((x) => item(x, `${esc(x.status)} · ${esc(x.niche || "")} · ${money(x.price_usd)}`)).join("") || `<div class="empty">The next best-seller scan fills this.</div>`}`;
}

function connectRow(name, service, state) {
  const on = String(state || "").startsWith("connected");
  const btn = state === "press Connect" || on ? `<a class="btn small" href="/api/station/connect/${service}">${on ? "Reconnect" : "Connect"}</a>` : "";
  return `<div class="conn"><span>${esc(name)}</span><span class="${on ? "pos" : "muted"}">${esc(state || "")} ${btn}</span></div>`;
}

function productsSection(sf, ventureId) {
  const mine = sf.products.filter((p) => p.venture === ventureId), works = sf.in_works.filter((p) => p.venture === ventureId);
  const item = (x, extra) => `<div class="row" style="display:flex;gap:10px;align-items:center">${x.cover ? `<img src="/media/${esc(x.cover)}" alt="" style="width:46px;height:69px;object-fit:cover;border-radius:6px;flex:none">` : ""}<div><b>${esc(x.title)}</b><div class="muted small">${extra}</div></div></div>`;
  return `<h2>Products</h2><p class="muted small">Runs on its own: the Product Designer makes a product every day (up to 6), QA checks it, it goes on sale on the storefront${sf.rails.etsy_digital ? ", Etsy" : ""}${sf.rails.pinterest ? " and Pinterest" : ""}. It closes itself after 21 days with no sale.</p>
    ${mine.map((x) => item(x, `${money(x.price_usd)} · ${plural(x.sales, "sale")} · ${x.active ? `<a href="${esc(x.url)}" target="_blank" rel="noopener" style="color:var(--cyan)">page</a>` : "off sale"}${x.etsy ? ` · <a href="${esc(x.etsy)}" target="_blank" rel="noopener" style="color:var(--cyan)">Etsy</a>` : ""}${x.pinned ? " · pinned" : ""}`)).join("") || `<div class="empty">Nothing on sale yet.</div>`}
    ${works.length ? `<h2>In the works</h2>${works.map((x) => item(x, `${esc(x.status)} · ${money(x.price_usd)}`)).join("")}` : ""}`;
}

// Owner-made products that ship with the app (backend/station/kits.py): publish = the owner's go
function kitCard(k) {
  const p = k.product, r = k.rails || {};
  const gallery = k.images.map((im) => `<img src="/media/${esc(im)}" alt="" style="height:64px;border-radius:6px">`).join(" ");
  const live = p ? `<p class="small">${p.active ? "On sale" : "Off sale"} at ${money(p.price_usd)}: <a href="${esc(p.url)}" target="_blank" rel="noopener" style="color:var(--cyan)">storefront page</a>`
    + `${p.etsy ? ` · <a href="${esc(p.etsy)}" target="_blank" rel="noopener" style="color:var(--cyan)">Etsy listing</a>` : ""}`
    + ` · ${p.pins_left ? `${plural(p.pins_left, "pin")} left to post${r.pinterest ? " (one a day)" : " when Pinterest connects"}` : "all pins posted"}</p>` : "";
  const form = p && p.active ? "" : k.shelved
    ? `<p class="muted small">Shelved: venture ${esc(k.venture)} was killed, so this can't be published. The files stay on the server; move the venture back from killed to sell it.</p>`
    : `<div class="actions"><input id="kit-price-${esc(k.id)}" type="number" step="0.01" min="3" max="97" placeholder="Price, e.g. 12.99" style="width:150px" />
      ${k.venture ? "" : `<input id="kit-venture-${esc(k.id)}" placeholder="Venture id, e.g. V-006" style="width:150px" />`}
      <button class="btn primary" data-kit="${esc(k.id)}">Publish</button></div>
      <p class="muted small">Publishing is the go decision. It puts the product on the storefront (Stripe checkout, both PDFs delivered after payment)${r.etsy_digital ? ", lists it on Etsy with all ${k.images.length} images and both files (Etsy charges its listing fee)" : ""}${r.pinterest ? " and posts the first pin" : ""}. ${r.storefront ? "" : "<b>Needs Stripe and STARNET_PUBLIC_URL first.</b>"}</p>`;
  return `<div class="item" style="display:block"><div class="t"><span><b>${esc(k.name)}</b></span><span class="pill ${p && p.active ? "green" : k.shelved ? "" : "gold"}">${p && p.active ? "ON SALE" : k.shelved ? "SHELVED" : "READY"}</span></div>
    <p class="muted small">${k.pages} pages · ${k.files.join(" + ")} · ${k.images.length} listing images · ${k.pins} pins · venture ${esc(k.venture || "not set")}</p>
    <p class="small">Etsy title: ${esc(k.etsy_title)}</p><div style="overflow-x:auto;white-space:nowrap">${gallery}</div>${live}${form}</div>`;
}

function renderMarketing() {
  const c = S.connectors;
  const row = (name, on, how) => `<div class="conn"><span>${esc(name)}</span><span class="${on === true ? "pos" : "muted"}">${on === true ? "connected" : esc(on || how)}</span></div>`;
  $("#conn").innerHTML = row("Stripe (checkout links)", c.stripe, "not connected") + row("Stripe sales → treasury", c.stripe_webhook, "no webhook yet") +
    row("Email outreach", c.email, "not connected") +
    row("Replies inbox (opt-outs + leads)", c.inbox && c.inbox.configured ? (c.inbox.error ? `error: ${c.inbox.error}` : c.inbox.checked_at ? true : "connected, first check soon") : "connects with email") + row("Facebook Page", c.social.includes("facebook"), "not connected") +
    row("Instagram", c.social.includes("instagram"), "not connected") + row("LinkedIn", c.social.includes("linkedin"), "off") +
    row("TikTok", c.tiktok) +
    row("Fiverr", c.fiverr) + row("Etsy (via Printify)", c.printify === true ? true : c.etsy) +
    row("Storefront (/shop)", c.rails && c.rails.storefront ? true : "needs Stripe + STARNET_PUBLIC_URL") +
    connectRow("Etsy digital downloads", "etsy", c.etsy_digital) + connectRow("Pinterest", "pinterest", c.pinterest);
  if ($("#kits")) $("#kits").innerHTML = (S.kits || []).map(kitCard).join("") || `<div class="empty">No finished products waiting.</div>`;
  $("#ob-manual").innerHTML = S.outbox.manual.map(actionRow).join("") || `<div class="empty">Nothing to post by hand.</div>`;
  $("#ob-wait").innerHTML = S.outbox.waiting_owner.map(actionRow).join("") || `<div class="empty">Nothing waiting.</div>`;
  $("#ob-sent").innerHTML = S.outbox.sent.map(actionRow).join("") || `<div class="empty">Nothing sent yet.</div>`;
  $("#ob-rejected").innerHTML = S.outbox.rejected.map(actionRow).join("") || `<div class="empty">QA hasn't stopped anything.</div>`;
}
$("#optout").addEventListener("submit", (e) => {
  e.preventDefault();
  act(() => api("/api/station/optout", { email: e.target.email.value }), "They'll never be contacted.").then(() => e.target.reset());
});

function renderWarRoom() {
  const w = S.warroom;
  $("#wr-latest").innerHTML = w ? `<p class="muted small">${esc(ago(w.at))}</p><p>${esc(w.summary)}</p>` +
    w.verdicts.map((v) => `<div class="item" data-open="ventures:${esc(v.venture)}"><div class="t"><span>${esc(v.venture)}</span>
      <span class="pill ${["kill", "pause", "pivot"].includes(v.verdict) ? "red" : v.verdict === "double_down" ? "green" : "cyan"}">${esc(v.verdict.replace("_", " "))}</span></div>
      <div class="m">${esc(v.why)}</div></div>`).join("") + (S.research_focus ? `<p class="muted small">Research focus: ${esc(S.research_focus)}</p>` : "")
    : `<div class="empty">No session yet. It meets Sundays 17:00 ET, or as soon as 8 new results come in.</div>`;
  $("#wr-stop").innerHTML = w ? list(w.stop_doing) : "—";
  $("#wr-start").innerHTML = w ? list(w.start_doing) : "—";
  $("#wr-lessons").innerHTML = S.lessons.length ? S.lessons.map((l) => `<div class="ev"><div class="when">${esc(l.applies_to)}</div>
    <div>${esc(l.lesson)} <span class="muted small">${esc(l.evidence)}</span></div></div>`).join("") : `<div class="empty">No lessons yet: they come from results.</div>`;
  const sel = $("#feedback select[name=ref]"), cur = sel.value;
  sel.innerHTML = `<option value="">About the station</option>` + S.ventures.map((v) => `<option value="${v.id}">${esc(v.id)} ${esc(v.name).slice(0, 30)}</option>`).join("");
  sel.value = cur;
}
$("#wr-now").addEventListener("click", () => act(() => api("/api/station/warroom", {}), "War Room convening."));
$("#feedback").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  act(() => api("/api/station/feedback", f), "The War Room will read it.").then(() => e.target.reset());
});

function renderLegal() {
  const qa = S.events.filter((e) => e.kind.startsWith("action.qa_"));
  $("#qa-stats").innerHTML = stat("In QA now", S.outbox.in_qa) + stat("Stopped by QA", S.outbox.rejected.length) +
    stat("Passed & sent", S.outbox.sent.length) + stat("Outbound", S.outbound ? "ON" : "OFF", "", S.outbound ? "pos" : "neg");
  api("/api/station/agents/A-010").then((a) => {
    $("#legal-docs").innerHTML = (a.task_list || []).map(taskRow).join("") || `<div class="empty">No documents yet. Legal Counsel drafts terms and refund policies when a venture sells through its own checkout.</div>`;
  }).catch(() => {});
  $("#qa-log").innerHTML = qa.map(evRow).join("") || `<div class="empty">No QA calls yet.</div>`;
}

async function loadFinance() {
  try {
    const f = await api("/api/station/finance");
    const st = f.statement;
    $("#f-statement").innerHTML = `<div class="kv">${Object.entries(st.units).map(([u, x]) => `<div>${esc(u)}</div><div>in ${money(x.income)} · out ${money(x.expenses + x.ai)} · <b class="${x.net < 0 ? "neg" : "pos"}">${money(x.net)}</b></div>`).join("")}
      <div>Net (${esc(st.month)})</div><div><b>${money(st.net)}</b></div><div>Tax set-aside</div><div>${money(st.tax_set_aside)} <span class="muted small">(${Math.round(st.tax_rate * 100)}%, an estimate)</span></div></div>`;
    const a = f.audit;
    $("#f-audit").innerHTML = `<div class="kv"><div>Ledger chain</div><div class="${f.chain.intact ? "pos" : "neg"}">${f.chain.intact ? "intact" : "BROKEN"} · ${f.chain.entries} entries</div>
      <div>Last audit</div><div>${a ? esc(ago(a.at)) : "not yet (07:00 ET daily)"}</div></div>` +
      (a && a.findings.length ? a.findings.map((x) => `<div class="item"><div class="t"><span>${esc(x.finding)}</span><span class="pill red">${esc(x.severity)}</span></div></div>`).join("")
        : `<div class="empty">${a ? "Clean." : ""}</div>`);
  } catch (e) { $("#f-statement").textContent = e.message; }
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
      ${r.autonomous && S.storefront ? productsSection(S.storefront, r.id) : r.agent_run && S.shop ? shopSection(S.shop) : ""}
      ${(S.kits || []).filter((k) => k.venture === r.id).length ? `<h2>Your finished product</h2>${S.kits.filter((k) => k.venture === r.id).map(kitCard).join("")}` : ""}
      <h2>Tasks</h2>${(r.task_list || []).map(taskRow).join("") || `<div class="empty">No tasks yet.</div>`}
      ${r.autonomous ? "" : `<h2>Where customers buy</h2>${Object.entries(r.links || {}).map(([k, u]) => `<div><span class="muted">${esc(k)}</span> <a href="${esc(u)}" target="_blank" rel="noopener" style="color:var(--cyan)">${esc(u)}</a></div>`).join("") || `<div class="empty">No link yet: marketing starts once there is one.</div>`}
      <div class="row" style="margin-top:8px"><input id="link-name" placeholder="fiverr" style="max-width:110px" /><input id="link-url" placeholder="https://…" />
        <button class="btn" data-link="${r.id}">Save link</button></div>`}
      ${r.id !== "V-001" && !r.agent_run ? `<h2>Leads</h2><p class="muted small">Got a message? Log it in one tap. The War Room uses this to learn which posts work.</p>
        <div class="row"><select id="lead-post" style="flex:1"><option value="">From which post? (optional)</option>
          ${S.outbox.sent.filter((a) => a.venture === r.id).map((a) => `<option value="${a.id}">${esc(a.payload.platform)}: ${esc((a.payload.text || "").slice(0, 50))}</option>`).join("")}</select></div>
        <input id="lead-note" placeholder="Note (optional): e.g. casa en Bayamón, quiere baterías" style="margin:8px 0" />
        <div class="actions" style="margin-top:0">${["dm", "whatsapp", "call", "comment", "referral"].map((x) => `<button class="btn" data-addlead="${r.id}:${x}">+ ${SRC[x]}</button>`).join("")}</div>
        ${(S.leads || []).filter((l) => l.venture === r.id).slice(0, 12).map(leadRow).join("") || `<div class="empty">No leads logged yet.</div>`}
        ${r.results ? `<h2>Last 30 days</h2><div class="kv"><div>Leads</div><div>${r.results.leads} ${Object.entries(r.results.by_source).map(([k, v]) => `· ${v} ${SRC[k] || k}`).join(" ")}</div>
          <div>Won</div><div>${r.results.by_status.won || 0} · ${money(r.results.won_value)}</div><div>Posts sent</div><div>${r.results.posts_sent}</div></div>
          ${r.results.best_posts.length ? `<h2>Best posts</h2>${r.results.best_posts.map((p) => `<div class="ev"><div class="when">${p.leads} leads</div><div>${esc(p.platform)}: ${esc(p.text)}${metricsText(p.metrics)}</div></div>`).join("")}` : ""}` : ""}` : ""}
      ${r.agent_run ? "" : `<h2>Outreach</h2><div class="row"><span class="muted small" style="flex:1">${r.outreach_allowed ? "The Outreach Agent may email businesses for this venture." : "Off: no one is contacted for this venture."}</span>
        <button class="btn ${r.outreach_allowed ? "danger" : ""}" data-outreach="${r.id}:${r.outreach_allowed ? "off" : "on"}">${r.outreach_allowed ? "Turn off" : "Allow outreach"}</button></div>`}
      ${r.marketing_plan && r.marketing_plan.channels ? `<h2>Channel plan</h2><p class="muted small">${esc(r.marketing_plan.audience || "")}</p>${list(r.marketing_plan.channels.map((c) => `${c.platform}: ${c.why}`))}` : ""}
      ${r.id !== "V-001" ? `<h2>Move it</h2><div class="actions">${["launch", "operate", "scale", "paused", "killed"].filter((x) => !(r.owner_business && x === "killed")).map((s) => `<button class="btn ${s === "killed" ? "danger" : ""}" data-stage="${r.id}:${s}">${s}</button>`).join("")}</div>` : ""}`);
  } else if (col === "tasks") {
    const deps = await Promise.all((r.depends_on || []).map((d) => api(`/api/station/tasks/${d}`).catch(() => null)));
    const out = r.output && r.output.deliverable;
    const scanInfo = r.kind === "owner" && r.status !== "done" && /scan/i.test(r.title)
      ? await api(`/api/station/tasks/${r.id}/scan-terms`).catch(() => null) : null;
    sheet(`<div class="label">TASK ${esc(r.id)} · ${esc(r.status.replace("_", " "))}</div><h1>${esc(r.title)}</h1>
      <div class="kv"><div>Venture</div><div>${esc(r.venture)}</div><div>Owner</div><div>${esc(r.assigned_agent === "OWNER" ? "You" : agentName(r.assigned_agent))}</div>
      <div>Why / how</div><div>${esc(r.instructions)}</div><div>Expected</div><div>${esc(r.expected_output)}</div>
      <div>Success</div><div>${esc(r.success_criteria)}</div>${r.escalate_if ? `<div>Escalate if</div><div>${esc(r.escalate_if)}</div>` : ""}
      ${r.error ? `<div>Error</div><div class="neg">${esc(r.error)}</div>` : ""}</div>
      ${deps.filter((d) => d && d.output).map((d) => `<h2>Input: ${esc(d.title)}</h2><pre class="deliver">${esc(d.output.deliverable)}</pre>
        <button class="btn" data-copy="${esc(d.id)}">Copy</button>`).join("")}
      ${out ? `<h2>Deliverable</h2><pre class="deliver">${esc(out)}</pre><button class="btn" data-copy="${esc(r.id)}">Copy</button>
        ${r.output.notes ? `<p class="muted small">${esc(r.output.notes)}</p>` : ""}${r.output.owner_next?.length ? `<h2>You do next</h2>${list(r.output.owner_next)}` : ""}` : ""}
      ${scanBox(r, scanInfo)}
      ${r.kind === "owner" && r.status !== "done" ? `<div class="actions"><input id="done-note" placeholder="Note (optional): e.g. gig link" />
        <button class="btn primary" data-done="${r.id}">Mark done</button></div>` : ""}`);
    sheet.copy = Object.fromEntries([r, ...deps].filter((d) => d && d.output).map((d) => [d.id, d.output.deliverable]));
  } else if (col === "agents") {
    sheet(`<div class="label">AGENT ${esc(r.id)} · ${esc(r.status)}</div><h1>${esc(r.name)}</h1>
      <div class="kv"><div>Role</div><div>${esc(r.role)}</div><div>Department</div><div>${esc(r.department)}</div><div>Specialty</div><div>${esc(r.specialty)}</div>
      <div>Current task</div><div>${esc(r.current_task || "—")}</div><div>Delivered</div><div>${r.tasks_done || 0} tasks</div>
      <div>Cost to run</div><div>${money(r.pnl.ai_costs)} AI</div></div><h2>Work</h2>${(r.task_list || []).map(taskRow).join("") || `<div class="empty">No tasks.</div>`}`);
  } else if (col === "actions") {
    const p = r.payload || {};
    const text = r.kind === "social.post" ? p.text + (p.link ? "\n\n" + p.link : "") : r.kind === "outreach.email" ? `To: ${p.to_email}\nSubject: ${p.subject}\n\n${p.body}` : JSON.stringify(p, null, 1);
    sheet(`<div class="label">${esc((KIND[r.kind] || r.kind).toUpperCase())} ${esc(r.id)} · ${esc(r.status.replace("_", " "))}</div><h1>${esc(r.why)}</h1>
      ${r.kind === "outreach.email" ? `<div class="kv"><div>Company</div><div>${esc(p.company)}</div><div>Why them</div><div>${esc(p.why_them)}</div>
        <div>Found at</div><div><a href="${esc(p.source_url)}" target="_blank" rel="noopener" style="color:var(--cyan)">${esc(p.source_url)}</a></div></div>` : ""}
      ${p.image ? `<img src="/media/${esc(p.image)}" alt="Post image" style="width:100%;max-width:360px;border-radius:12px;display:block;margin:10px 0">
        <a class="btn" href="/media/${esc(p.image)}" download>Download image</a>` : ""}
      <pre class="deliver">${esc(text)}</pre><button class="btn" data-copy="${esc(r.id)}">Copy</button>
      ${(r.result || {}).metrics ? `<h2>Engagement</h2><p>${esc(metricsText(r.result.metrics).slice(3))} <span class="muted small">(checked ${esc(ago(r.result.metrics_at))})</span></p>` : ""}
      ${r.qa ? `<h2>QA: ${esc(r.qa.verdict)}</h2>${list(r.qa.issues)}` : ""}
      <div class="actions">${["manual", "waiting_owner", "ready"].includes(r.status) ? `<button class="btn primary" data-act="${r.id}:done">I posted / sent it</button>` : ""}
        ${r.status === "waiting_owner" ? `<button class="btn" data-act="${r.id}:send">OK, send it</button>` : ""}
        ${r.status === "sent" ? `<input id="act-note" placeholder="How did it go? (e.g. 2 replies, 1 sale)" /><button class="btn" data-act="${r.id}:result">Save result</button>` : ""}
        ${!["sent", "cancelled", "rejected"].includes(r.status) ? `<button class="btn danger" data-act="${r.id}:cancel">Cancel</button>` : ""}</div>`);
    sheet.copy = { [r.id]: text };
  } else if (col === "approvals") {
    show("approvals");
  }
}

document.addEventListener("click", (e) => {
  const kitBtn = e.target.closest("[data-kit]");
  if (kitBtn) {
    const id = kitBtn.dataset.kit, price = +(($(`#kit-price-${id}`) || {}).value || 0);
    const venture = ($(`#kit-venture-${id}`) || {}).value || undefined;
    if (!price) return toast("Set a price first");
    if (!confirm(`Put it on sale at $${price.toFixed(2)}? This lists it on the storefront${S.connectors.rails && S.connectors.rails.etsy_digital ? " and on Etsy (Etsy charges its listing fee)" : ""}.`)) return;
    kitBtn.disabled = true;
    return act(() => api(`/api/station/kits/${id}/publish`, { price, venture }), "On sale.").finally(() => { kitBtn.disabled = false; });
  }
  const scanBtn = e.target.closest("[data-scan]");
  if (scanBtn) {
    const terms = ($("#scan-terms") || {}).value || "";
    return act(() => api(`/api/station/tasks/${scanBtn.dataset.scan}/etsy-scan`, { terms }),
      "Scanning Etsy through the API. It takes a few minutes; the task closes itself with the results.").then(() => $("#sheet").classList.add("hidden"));
  }
  const el = e.target.closest("[data-open],[data-decide],[data-promote],[data-dismiss],[data-run],[data-done],[data-stage],[data-copy],[data-act],[data-link],[data-outreach],[data-addlead],[data-lead]");
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
  if (d.act) {
    const [id, what] = d.act.split(":");
    if (what === "cancel" && !confirm("Cancel it?")) return;
    return act(() => api(`/api/station/actions/${id}/${what}`, { note: ($("#act-note") || {}).value || "" }),
      { done: "Marked sent.", send: "Sending.", cancel: "Cancelled.", result: "Result saved: the War Room will use it." }[what]).then(() => $("#sheet").classList.add("hidden"));
  }
  if (d.addlead) {
    const [id, source] = d.addlead.split(":");
    return act(() => api(`/api/station/ventures/${id}/leads`, { source, note: $("#lead-note").value, action: $("#lead-post").value }),
      `Lead logged (${SRC[source]}).`).then(() => openRecord("ventures", id));
  }
  if (d.lead) {
    const [id, status] = d.lead.split(":");
    let amount = null;
    if (status === "won") {
      const v = prompt("How much did you earn from this sale? ($)");
      if (v === null) return;
      amount = parseFloat(v);
    }
    const lead = (S.leads || []).find((l) => l.id === id) || {};
    return act(() => api(`/api/station/leads/${id}`, { status, amount }), status === "won" ? "Sale booked in the treasury." : `Lead ${status}.`)
      .then(() => lead.venture && openRecord("ventures", lead.venture));
  }
  if (d.outreach) {
    const [id, to] = d.outreach.split(":");
    return act(() => api(`/api/station/ventures/${id}/outreach`, { on: to === "on" }), to === "on" ? "Outreach allowed." : "Outreach off.").then(() => openRecord("ventures", id));
  }
  if (d.link) return act(() => api(`/api/station/ventures/${d.link}/link`, { name: $("#link-name").value, url: $("#link-url").value }), "Link saved.").then(() => openRecord("ventures", d.link));
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
