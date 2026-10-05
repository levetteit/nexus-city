import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

// ---------------------------------------------------------------- setup
const app = document.getElementById("app");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.85;
app.appendChild(renderer.domElement);

const labels = new CSS2DRenderer();
labels.setSize(innerWidth, innerHeight);
labels.domElement.className = "label-layer";
Object.assign(labels.domElement.style, { position: "fixed", inset: "0" });
app.appendChild(labels.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color("#22127a");
scene.fog = new THREE.Fog("#22127a", 90, 230);

const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.1, 600);
camera.position.set(0, 52, 88);
if (innerWidth < innerHeight) camera.position.set(0, 120, 95); // phones: higher, more top-down view so the whole city fits

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 6, 0);
controls.enableDamping = true;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.35;
controls.maxPolarAngle = Math.PI * 0.46;
controls.minDistance = 25;
controls.maxDistance = 170;
controls.addEventListener("start", () => (controls.autoRotate = false));

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.7, 0.4, 0.55);
composer.addPass(bloom);
composer.addPass(new OutputPass());

scene.add(new THREE.HemisphereLight("#8f7bff", "#120838", 0.9));
const sun = new THREE.DirectionalLight("#c9b8ff", 1.2);
sun.position.set(30, 60, 20);
scene.add(sun);

// ---------------------------------------------------------------- textures
function windowTexture(seed = Math.random(), litChance = 0.55) {
  const c = document.createElement("canvas");
  c.width = 64; c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#14102a";
  g.fillRect(0, 0, 64, 128);
  let s = seed * 9999;
  const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  for (let y = 4; y < 128; y += 10) {
    for (let x = 4; x < 64; x += 10) {
      const r = rnd();
      g.fillStyle = r < litChance ? (r < 0.12 ? "#fff3c4" : "#ffc96b") : "#2a2350";
      g.fillRect(x, y, 6, 6);
    }
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.magFilter = THREE.NearestFilter;
  return t;
}

function towerMaterial(w, h, seed, lit) {
  const tex = windowTexture(seed, lit);
  tex.repeat.set(Math.max(1, Math.round(w / 3)), Math.max(1, Math.round(h / 6)));
  return new THREE.MeshStandardMaterial({ color: "#8a80b8", map: tex, emissive: "#ffffff", emissiveMap: tex, emissiveIntensity: 0.6, roughness: 0.8 });
}

// ---------------------------------------------------------------- ground + roads
const ground = new THREE.Mesh(new THREE.CircleGeometry(400, 64), new THREE.MeshStandardMaterial({ color: "#1d1166", roughness: 1 }));
ground.rotation.x = -Math.PI / 2;
scene.add(ground);
const grid = new THREE.GridHelper(400, 160, "#4a35c9", "#33228f");
grid.position.y = 0.02;
scene.add(grid);

const plaza = new THREE.Mesh(new THREE.CircleGeometry(36, 96), new THREE.MeshStandardMaterial({ color: "#150c4c", roughness: 0.9 }));
plaza.rotation.x = -Math.PI / 2;
plaza.position.y = 0.05;
scene.add(plaza);

function glowRing(radius, color, width = 0.18, y = 0.12) {
  const m = new THREE.Mesh(new THREE.RingGeometry(radius - width, radius + width, 160),
    new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide }));
  m.rotation.x = -Math.PI / 2;
  m.position.y = y;
  scene.add(m);
  return m;
}
glowRing(36, "#bfb3ff", 0.25);
glowRing(33, "#6f5cff", 0.12);
glowRing(10, "#ffe7a3", 0.15);

// running lights around the ring road
const runLights = new THREE.Group();
{
  const geo = new THREE.SphereGeometry(0.22, 8, 8);
  const mat = new THREE.MeshBasicMaterial({ color: "#fff6d0" });
  for (let i = 0; i < 90; i++) {
    const a = (i / 90) * Math.PI * 2;
    const m = new THREE.Mesh(geo, mat);
    m.position.set(Math.cos(a) * 34.5, 0.3, Math.sin(a) * 34.5);
    runLights.add(m);
  }
}
scene.add(runLights);

// background skyline (instanced for speed)
{
  const count = 420;
  const mat = towerMaterial(3, 6, 0.42, 0.35);
  mat.emissiveIntensity = 0.3;
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, count);
  const m = new THREE.Matrix4();
  for (let i = 0; i < count; i++) {
    const a = Math.random() * Math.PI * 2;
    const r = 80 + Math.random() * 130;
    const w = 4 + Math.random() * 7, d = 4 + Math.random() * 7, h = 6 + Math.random() * (r > 120 ? 55 : 30);
    m.compose(new THREE.Vector3(Math.cos(a) * r, h / 2, Math.sin(a) * r), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.random() * Math.PI), new THREE.Vector3(w, h, d));
    mesh.setMatrixAt(i, m);
  }
  scene.add(mesh);
}

// ---------------------------------------------------------------- the vault
const vault = new THREE.Group();
{
  const base = new THREE.Mesh(new THREE.CylinderGeometry(8, 9, 1.2, 48), new THREE.MeshStandardMaterial({ color: "#2b1d78" }));
  base.position.y = 0.6;
  vault.add(base);
  const colMat = new THREE.MeshStandardMaterial({ color: "#ffe2a8", emissive: "#ffb347", emissiveIntensity: 0.6 });
  for (let i = 0; i < 18; i++) {
    const a = (i / 18) * Math.PI * 2;
    const col = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 3.4, 10), colMat);
    col.position.set(Math.cos(a) * 5.4, 2.9, Math.sin(a) * 5.4);
    vault.add(col);
  }
  const ring = new THREE.Mesh(new THREE.CylinderGeometry(5.9, 5.9, 0.5, 48), colMat);
  ring.position.y = 4.8;
  vault.add(ring);
}
const domeMat = new THREE.MeshStandardMaterial({ color: "#fff8e8", emissive: "#fff1cc", emissiveIntensity: 1.0 });
const dome = new THREE.Mesh(new THREE.SphereGeometry(5.6, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2), domeMat);
dome.position.y = 5;
vault.add(dome);
scene.add(vault);

const vaultTag = document.createElement("div");
vaultTag.className = "vault-tag";
vaultTag.innerHTML = `<div class="t">THE VAULT · TODAY</div><div class="v">+$0</div><div class="s">0 workers on shift · tap for payroll</div>`;
vaultTag.onclick = () => document.getElementById("payroll").classList.toggle("hidden");
const vaultLabel = new CSS2DObject(vaultTag);
vaultLabel.position.set(0, 14, 0);
scene.add(vaultLabel);

// ---------------------------------------------------------------- buildings
const buildings = new Map(); // bot id -> { group, beam, halo, tag, pos, mats }
const clickables = [];
const BUILD_RADIUS = 23;

function makeBuilding(bot, index, total) {
  const angle = (index / total) * Math.PI * 2 - Math.PI / 2;
  const pos = new THREE.Vector3(Math.cos(angle) * BUILD_RADIUS, 0, Math.sin(angle) * BUILD_RADIUS);
  const color = new THREE.Color(bot.color);
  const group = new THREE.Group();
  group.position.copy(pos);
  group.lookAt(0, 0, 0);

  const platform = new THREE.Mesh(new THREE.BoxGeometry(11, 1, 11), new THREE.MeshStandardMaterial({ color: "#1a1150", emissive: color, emissiveIntensity: 0.08 }));
  platform.position.y = 0.5;
  group.add(platform);
  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(platform.geometry), new THREE.LineBasicMaterial({ color }));
  edge.position.copy(platform.position);
  group.add(edge);

  // a cluster of towers: one tall hero tower and a few shorter ones
  const mats = [];
  const seed = index * 0.137 + 0.21;
  const hero = 16 + (index % 3) * 4;
  const towers = [
    [0, 0, 4, hero], [-3.2, 2.6, 3, hero * 0.55], [3.0, 2.4, 3.2, hero * 0.65],
    [-2.8, -2.8, 2.8, hero * 0.4], [3.1, -2.9, 2.6, hero * 0.35],
  ];
  towers.forEach(([x, z, w, h], i) => {
    const mat = towerMaterial(w, h, seed + i * 0.31, 0.6);
    mats.push(mat);
    // stacked setbacks so it reads as a skyscraper
    let y = 1, width = w, remaining = h;
    while (remaining > 0.5) {
      const seg = Math.min(remaining, Math.max(3, h * 0.45));
      const m = new THREE.Mesh(new THREE.BoxGeometry(width, seg, width), mat);
      m.position.set(x, y + seg / 2, z);
      group.add(m);
      y += seg; remaining -= seg; width *= 0.78;
    }
    if (i === 0) {
      const spire = new THREE.Mesh(new THREE.ConeGeometry(0.4, 4, 8), new THREE.MeshBasicMaterial({ color }));
      spire.position.set(x, y + 2, z);
      group.add(spire);
    }
  });

  // little glowing trees around the platform, like the reel
  const treeMat = new THREE.MeshBasicMaterial({ color: "#5ef2e0" });
  for (let i = 0; i < 6; i++) {
    const t = new THREE.Mesh(new THREE.ConeGeometry(0.35, 1.2, 6), treeMat);
    const a = (i / 6) * Math.PI * 2;
    t.position.set(Math.cos(a) * 6.2, 1.6, Math.sin(a) * 6.2);
    group.add(t);
  }

  // light beam (on while the bot is in a trade)
  const beamMat = new THREE.MeshBasicMaterial({ color: color.clone().lerp(new THREE.Color("#fff3c0"), 0.55), transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.6, 140, 24, 1, true), beamMat);
  beam.position.y = hero + 70;
  group.add(beam);

  // halo ring hovering over the hero tower
  const haloMat = new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.8 });
  const halo = new THREE.Mesh(new THREE.TorusGeometry(3.2, 0.14, 8, 64), haloMat);
  halo.rotation.x = Math.PI / 2;
  halo.position.y = hero + 6;
  group.add(halo);

  scene.add(group);

  // road to the vault
  const roadDir = pos.clone().normalize();
  const roadLen = BUILD_RADIUS - 6 - 9;
  const road = new THREE.Mesh(new THREE.PlaneGeometry(1.4, roadLen), new THREE.MeshBasicMaterial({ color: color.clone().multiplyScalar(0.55) }));
  road.rotation.x = -Math.PI / 2;
  road.rotation.z = -Math.atan2(roadDir.x, roadDir.z) + Math.PI;
  road.position.copy(roadDir.clone().multiplyScalar(9 + roadLen / 2)).setY(0.1);
  scene.add(road);

  // floating label
  const tag = document.createElement("div");
  tag.className = "tag";
  tag.style.setProperty("--accent", bot.color);
  tag.onclick = () => openWorker(bot.id);
  const label = new CSS2DObject(tag);
  label.position.set(0, hero + 12, 0);
  group.add(label);

  // neon district sign at street level
  const sign = document.createElement("div");
  sign.className = "sign";
  sign.style.setProperty("--accent", bot.color);
  sign.textContent = bot.district;
  const signObj = new CSS2DObject(sign);
  signObj.position.set(0, 3.2, 6.5);
  group.add(signObj);

  group.traverse((o) => { if (o.isMesh) { o.userData.botId = bot.id; clickables.push(o); } });
  buildings.set(bot.id, { group, beam, beamMat, halo, haloMat, tag, pos, mats, hero, color, status: null });
}

// ---------------------------------------------------------------- coins
const coinGeo = new THREE.CylinderGeometry(0.55, 0.55, 0.16, 20);
const goldMat = new THREE.MeshStandardMaterial({ color: "#ffd34d", emissive: "#ffb300", emissiveIntensity: 1.2, metalness: 0.6, roughness: 0.3 });
const redMat = new THREE.MeshStandardMaterial({ color: "#ff4d6d", emissive: "#ff1f4b", emissiveIntensity: 1.2 });
const coins = [];
let vaultPulse = 0;

function sendCoins(botId, pnl) {
  const b = buildings.get(botId);
  if (!b) return;
  const win = pnl >= 0;
  const n = Math.min(24, Math.max(4, Math.round(Math.abs(pnl) / 40)));
  const near = b.pos.clone().multiplyScalar((BUILD_RADIUS - 6) / BUILD_RADIUS).setY(1);
  const vaultPt = new THREE.Vector3(0, 5, 0);
  for (let i = 0; i < n; i++) {
    const mesh = new THREE.Mesh(coinGeo, win ? goldMat : redMat);
    mesh.rotation.x = Math.PI / 2;
    mesh.visible = false;
    scene.add(mesh);
    coins.push({
      mesh, t: -i * 0.07, speed: 0.55 + Math.random() * 0.15,
      from: win ? near : vaultPt, to: win ? vaultPt : near,
      jitter: new THREE.Vector3((Math.random() - 0.5) * 1.2, 0, (Math.random() - 0.5) * 1.2),
      win,
    });
  }
  popText(b, pnl);
}

function popText(b, pnl) {
  const el = document.createElement("div");
  el.className = `pop ${pnl >= 0 ? "win" : "loss"}`;
  el.textContent = `${pnl >= 0 ? "+" : "-"}$${Math.abs(pnl).toFixed(0)}`;
  const obj = new CSS2DObject(el);
  obj.position.set(0, b.hero + 4, 0);
  b.group.add(obj);
  setTimeout(() => { b.group.remove(obj); el.remove(); }, 2300);
}

// a TradingView alert landed: flash the building's halo and show what arrived
function tvPing(ev) {
  const b = buildings.get(ev.bot);
  if (!b) return;
  const el = document.createElement("div");
  el.className = "pop tv";
  el.textContent = `TV · ${ev.action}`;
  const obj = new CSS2DObject(el);
  obj.position.set(0, b.hero + 8, 0);
  b.group.add(obj);
  b.tvFlash = 1;
  setTimeout(() => { b.group.remove(obj); el.remove(); }, 2300);
}

function updateCoins(dt) {
  for (let i = coins.length - 1; i >= 0; i--) {
    const c = coins[i];
    c.t += dt * c.speed;
    if (c.t < 0) continue;
    c.mesh.visible = true;
    const t = Math.min(c.t, 1);
    const p = c.from.clone().lerp(c.to, t).add(c.jitter.clone().multiplyScalar(Math.sin(t * Math.PI)));
    p.y += Math.sin(t * Math.PI) * 4;
    c.mesh.position.copy(p);
    c.mesh.rotation.z += dt * 8;
    if (c.t >= 1) {
      if (c.win) vaultPulse = 1;
      scene.remove(c.mesh);
      coins.splice(i, 1);
    }
  }
}

// ---------------------------------------------------------------- state -> visuals
let state = null;
let openWorkerId = null;
const STATUS_TEXT = {
  scanning: () => "on shift · scanning",
  in_trade: (b) => `in trade · ${b.position?.contract ?? ""}`,
  off_duty: () => "profit locked · off duty",
  stopped: () => "account stop · sent home",
  walked: (b) => `${b.info?.inverses ?? 3} pointer inverses · walked away`,
  disabled: () => "turned off",
};
const money = (v) => `${v >= 0 ? "+" : "-"}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

function applyState(s) {
  state = s;
  if (buildings.size === 0) s.bots.forEach((b, i) => makeBuilding(b, i, s.bots.length));
  const top = s.bots.reduce((a, b) => (b.realized > a.realized ? b : a), s.bots[0]);

  for (const bot of s.bots) {
    const b = buildings.get(bot.id);
    if (!b) continue;
    const statusCls = ["stopped", "walked", "disabled"].includes(bot.status) ? "stopped" : bot.status === "off_duty" ? "off" : "";
    const star = bot.id === top.id && top.realized > 0 ? "★ " : "";
    const live = bot.status === "in_trade" ? ` <span class="earned ${bot.unrealized < 0 ? "neg" : ""}">(${money(bot.unrealized)} open)</span>` : "";
    b.tag.innerHTML = `<div class="name">${star}${bot.name}</div><div class="status ${statusCls}">${STATUS_TEXT[bot.status](bot)}</div><div class="earned ${bot.realized < 0 ? "neg" : ""}">earned ${money(bot.realized)}${live}</div>`;
    b.tag.classList.toggle("dim", bot.status === "disabled");
    b.status = bot.status;
    const dark = ["disabled", "stopped", "walked"].includes(bot.status);
    b.mats.forEach((m) => (m.emissiveIntensity = dark ? 0.1 : bot.status === "off_duty" ? 0.35 : 0.6));
    b.haloMat.color.set(bot.status === "stopped" || bot.status === "walked" ? "#ff4d6d" : bot.status === "off_duty" ? "#ffd34d" : "#ffffff");
  }

  const vEl = vaultTag.querySelector(".v");
  vEl.textContent = money(s.vault);
  vEl.classList.toggle("neg", s.vault < 0);
  vaultTag.querySelector(".s").textContent = `${s.on_shift} workers on shift · tap for payroll`;
  document.getElementById("clock").textContent = s.clock;
  document.getElementById("tickers").innerHTML = Object.entries(s.tickers)
    .map(([sym, t]) => `<span>${sym} ${t.price.toFixed(2)} <b class="${t.change_pct >= 0 ? "up" : "down"}">${t.change_pct >= 0 ? "+" : ""}${t.change_pct.toFixed(2)}%</b></span>`).join("");

  document.getElementById("payroll-rows").innerHTML = s.bots
    .map((b) => `<tr><td><span class="dot" style="background:${b.color}"></span>${b.id === top.id && top.realized > 0 ? "👑 " : ""}${b.name}</td><td>${b.trades}</td><td>${b.wins}</td><td class="${b.realized >= 0 ? "pos" : "neg"}">${money(b.realized)}</td></tr>`)
    .join("");

  renderAccount(s.account);
  if (openWorkerId) renderWorker();
}

const PHASES = { combine: "TRADING COMBINE", funded: "FUNDED (XFA)", failed: "FAILED" };
function renderAccount(a) {
  if (!a) return;
  document.getElementById("acct-firm").textContent = a.firm.toUpperCase();
  const phase = document.getElementById("acct-phase");
  phase.textContent = PHASES[a.phase];
  phase.className = `phase ${a.phase}`;
  const room = a.equity - a.mll;
  const goal = a.target
    ? `<div class="row"><span>Target</span><span>${money(a.profit)} / $${a.target.toLocaleString()}</span></div>
       <div class="bar"><i style="width:${Math.max(0, Math.min(100, (a.profit / a.target) * 100))}%"></i></div>`
    : `<div class="row"><span>Payout days</span><span>${a.winning_days} / ${a.payout_days_needed} (≥ $150)</span></div>
       ${a.payouts.length ? `<div class="row"><span>Paid out</span><span class="pos">$${a.payouts.reduce((x, y) => x + y, 0).toLocaleString()}</span></div>` : ""}`;
  document.getElementById("acct-body").innerHTML = `
    <div class="row"><span>Balance</span><span>$${a.balance.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span></div>
    ${goal}
    <div class="row"><span>MLL</span><span>$${a.mll.toLocaleString()} · <b class="${room < 500 ? "neg" : ""}">$${Math.max(0, room).toLocaleString(undefined, { maximumFractionDigits: 0 })} room</b></span></div>
    <div class="row"><span>Today</span><span class="${a.day_pnl >= 0 ? "pos" : "neg"}">${money(a.day_pnl)}</span></div>
    <div class="row"><span>Day stop / cap</span><span>-$${a.daily_stop.toLocaleString()} / +$${a.profit_cap.toLocaleString()}</span></div>
    <div class="row"><span>Micros open</span><span>${a.open_micros} / ${a.max_micros}</span></div>
    <div class="row"><span>Best day</span><span>$${a.best_day.toLocaleString(undefined, { maximumFractionDigits: 0 })} · day ${a.days}</span></div>
    ${a.halted ? `<div class="halt">${a.halted}</div>` : ""}
    ${a.phase === "failed" || a.halted.includes("reset") ? `<button class="reset" data-reset>RESET COMBINE</button>` : ""}`;
}

function openWorker(id) {
  openWorkerId = id;
  document.getElementById("worker").classList.remove("hidden");
  renderWorker();
}

function renderWorker() {
  const bot = state?.bots.find((b) => b.id === openWorkerId);
  if (!bot) return;
  const enabled = bot.status !== "disabled";
  const pos = bot.position
    ? `<div class="row"><span>Holding</span><span>${bot.position.qty}× ${bot.position.contract}</span></div>
       <div class="row"><span>Entry → mark</span><span>${bot.position.entry} → ${bot.position.mark}</span></div>
       <div class="row"><span>Next FFVG (${bot.underlying})</span><span>${bot.position.target ?? "—"}</span></div>
       <div class="row"><span>Exit</span><span>pointer against</span></div>
       <div class="row"><span>Open P&L</span><span class="${bot.unrealized >= 0 ? "pos" : "neg"}">${money(bot.unrealized)}</span></div>`
    : "";
  const trades = bot.recent.map((t) => `<tr><td>${t.closed_at}</td><td>${t.contract}</td><td>${t.reason}</td><td class="${t.pnl >= 0 ? "pos" : "neg"}">${money(t.pnl)}</td></tr>`).join("");
  document.getElementById("worker-body").innerHTML = `
    <h3 style="color:${bot.color}">${bot.name}</h3>
    <div class="row"><span>Strategy</span><span>${bot.strategy} · ${bot.timeframe}m candles</span></div>
    <div class="row"><span>Instrument</span><span>${bot.instrument === "future" ? `${bot.underlying} micro futures` : `${bot.underlying} options`}</span></div>
    <div class="row"><span>Size</span><span>${bot.contracts} contracts, adds to ${bot.max_contracts} max</span></div>
    ${bot.info?.setup ? `<div class="row"><span>Setup</span><span style="text-align:right;max-width:65%">${bot.info.setup}</span></div>` : ""}
    ${bot.info?.signals ? `<div class="row"><span>Signals from</span><span>${{ builtin: "built-in detection", tradingview: "TradingView alerts", both: "built-in + TradingView" }[bot.info.signals]}</span></div>` : ""}
    ${bot.info?.last_signal ? `<div class="row"><span>Last TV alert</span><span>${bot.info.last_signal}</span></div>` : ""}
    ${bot.info?.walk_after ? `<div class="row"><span>Pointer inverses</span><span>${bot.info.inverses} / ${bot.info.walk_after}</span></div>` : ""}
    <div class="row"><span>Status</span><span>${STATUS_TEXT[bot.status](bot)}</span></div>
    <div class="row"><span>Earned today</span><span class="${bot.realized >= 0 ? "pos" : "neg"}">${money(bot.realized)}</span></div>
    <div class="row"><span>Trades / wins</span><span>${bot.trades} / ${bot.wins}</span></div>
    ${pos}
    ${trades ? `<table style="margin-top:10px"><thead><tr><th>Time</th><th>Contract</th><th>Why</th><th>P&L</th></tr></thead><tbody>${trades}</tbody></table>` : ""}
    <button class="toggle ${enabled ? "off" : "on"}" data-bot="${bot.id}" data-action="${enabled ? "off" : "on"}">${enabled ? "SEND HOME" : "PUT ON SHIFT"}</button>`;
}

document.addEventListener("click", async (e) => {
  const close = e.target.closest("[data-close]");
  if (close) {
    document.getElementById(close.dataset.close).classList.add("hidden");
    if (close.dataset.close === "worker") openWorkerId = null;
  }
  if (e.target.closest("[data-reset]")) await fetch("/api/account/reset", { method: "POST" });
  const btn = e.target.closest("button.toggle");
  if (btn) {
    await fetch(`/api/bots/${btn.dataset.bot}/${btn.dataset.action}`, { method: "POST" });
  }
});

// click a building in 3D to open its worker card
const ray = new THREE.Raycaster();
let downAt = null;
renderer.domElement.addEventListener("pointerdown", (e) => (downAt = [e.clientX, e.clientY]));
renderer.domElement.addEventListener("pointerup", (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  ray.setFromCamera(new THREE.Vector2((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1), camera);
  const hit = ray.intersectObjects([...clickables, dome]).find((h) => h.object.userData.botId || h.object === dome);
  if (!hit) return;
  if (hit.object === dome) document.getElementById("payroll").classList.toggle("hidden");
  else openWorker(hit.object.userData.botId);
});

// ---------------------------------------------------------------- live feed
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  const conn = document.getElementById("conn");
  ws.onopen = () => conn.classList.add("hidden");
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type !== "tick") return;
    applyState(msg.state);
    for (const ev of msg.events) {
      if (ev.type === "trade_close") sendCoins(ev.bot, ev.pnl);
      if (ev.type === "tv_signal") tvPing(ev);
    }
  };
  ws.onclose = () => { conn.classList.remove("hidden"); setTimeout(connect, 1500); };
}
connect();

// ---------------------------------------------------------------- render loop
const clock = new THREE.Clock();
function frame() {
  const dt = Math.min(clock.getDelta(), 0.1);
  const t = clock.elapsedTime;
  controls.update();
  runLights.rotation.y += dt * 0.15;

  for (const b of buildings.values()) {
    const active = b.status === "in_trade";
    const target = active ? 0.4 + Math.sin(t * 3) * 0.08 : b.status === "off_duty" ? 0.08 : 0;
    b.beamMat.opacity += (target - b.beamMat.opacity) * Math.min(1, dt * 4);
    b.beam.visible = b.beamMat.opacity > 0.01;
    b.halo.rotation.z += dt * (active ? 2.5 : 0.6);
    b.halo.position.y = b.hero + 6 + Math.sin(t * 1.5 + b.pos.x) * 0.4;
    b.haloMat.opacity = b.status === "disabled" ? 0.15 : active ? 1 : 0.6;
    if (b.tvFlash > 0) {
      b.tvFlash = Math.max(0, b.tvFlash - dt * 0.8);
      b.halo.scale.setScalar(1 + b.tvFlash * 0.8);
    }
  }

  vaultPulse = Math.max(0, vaultPulse - dt * 1.5);
  domeMat.emissiveIntensity = 0.9 + vaultPulse * 2.5;
  dome.scale.setScalar(1 + vaultPulse * 0.04);
  updateCoins(dt);

  composer.render();
  labels.render(scene, camera);
  requestAnimationFrame(frame);
}
frame();

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  composer.setSize(innerWidth, innerHeight);
  labels.setSize(innerWidth, innerHeight);
});
