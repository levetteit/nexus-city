import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { Room, moodEmoji, tierOf, GADGETS } from "./room.js";
import { ChartView } from "./chart.js";
import { wardrobe, ITEMS, dress, finishMaterial, animateApparel } from "./skins.js";
import { Flight, newFlights } from "./shuttle.js";

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
const PORTRAIT = innerWidth < innerHeight;
if (PORTRAIT) camera.position.set(0, 112, 112); // phones: pulled back so the whole city fits between the panels

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, PORTRAIT ? -14 : 6, 0);   // phones: aim lower so the city sits mid-screen
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

const hemi = new THREE.HemisphereLight("#8f7bff", "#120838", 0.9);
scene.add(hemi);
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

// background skyline (instanced for speed); it grows with the account's profit
let skyline;
{
  const count = 420;
  const mat = towerMaterial(3, 6, 0.42, 0.35);
  mat.emissiveIntensity = 0.3;
  const mesh = skyline = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, count);
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

function makeMascot(bot) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.55, 0.9, 6, 12), finishMaterial("chrome"));
  body.position.y = 1.1;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.62, 20, 14), new THREE.MeshStandardMaterial({ color: "#d9e2ff", metalness: 0.4, roughness: 0.3 }));
  head.position.y = 2.25;
  const visor = new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.28, 0.2), new THREE.MeshStandardMaterial({ color: bot.color, emissive: bot.color, emissiveIntensity: 2 }));
  visor.position.set(0, 2.3, 0.5);
  const pick = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 3.2, 8), new THREE.MeshBasicMaterial({ visible: false }));
  pick.position.y = 1.6;
  pick.userData.botId = bot.id;
  clickables.push(pick);
  g.add(body, head, visor, pick);
  g.userData.body = body;
  return g;
}

function dressMascot(b, bot) {
  const look = wardrobe(bot, "bot", { phase: state?.account?.phase });
  const key = JSON.stringify(look.wear) + look.finish;
  if (key === b.wearKey) return;
  for (const it of b.apparel) it.parent?.remove(it);
  b.mascot.userData.body.material = finishMaterial(look.finish);
  b.apparel = dress(look.wear, {
    head: { parent: b.mascot, pos: [0, 2.82, 0], w: 1.2 },
    face: { parent: b.mascot, pos: [0, 2.32, 0.62], w: 1.1 },
    neck: { parent: b.mascot, pos: [0, 1.78, 0], w: 1.1 },
    chest: { parent: b.mascot, pos: [0.25, 1.35, 0.56], w: 1.0 },
    back: { parent: b.mascot, pos: [0, 1.85, -0.56], w: 1.0, rot: [0, Math.PI, 0] },
  }, bot.color);
  b.wearKey = key;
}

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
  const towersG = new THREE.Group();   // grows taller with the bot's best-ever day (career_best)
  group.add(towersG);
  towers.forEach(([x, z, w, h], i) => {
    const mat = towerMaterial(w, h, seed + i * 0.31, 0.6);
    mats.push(mat);
    // stacked setbacks so it reads as a skyscraper
    let y = 1, width = w, remaining = h;
    while (remaining > 0.5) {
      const seg = Math.min(remaining, Math.max(3, h * 0.45));
      const m = new THREE.Mesh(new THREE.BoxGeometry(width, seg, width), mat);
      m.position.set(x, y + seg / 2, z);
      towersG.add(m);
      y += seg; remaining -= seg; width *= 0.78;
    }
    if (i === 0) {
      const spire = new THREE.Mesh(new THREE.ConeGeometry(0.4, 4, 8), new THREE.MeshBasicMaterial({ color }));
      spire.position.set(x, y + 2, z);
      towersG.add(spire);
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
  tag.onclick = () => openRoom(bot.id);
  const label = new CSS2DObject(tag);
  label.position.set(0, hero + 12 + (index % 2) * 7, 0);   // stagger heights so neighbours' labels don't collide
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
  // the bot itself, out front facing the vault, in its skin and apparel (skins.js)
  const mascot = makeMascot(bot);
  mascot.position.set(0, 1, 5.3);
  mascot.scale.setScalar(1.5);
  group.add(mascot);
  buildings.set(bot.id, { group, beam, beamMat, halo, haloMat, tag, label, labelY: label.position.y, pos, mats, hero, color, status: null,
    mascot, apparel: [], wearKey: "", towersG, grow: 1, growTo: 1 });
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

// ---------------------------------------------------------------- the station in the sky, and payout shuttles
// The Space Station hangs over the city (tap it to go there). Real money in flies to it as shuttles:
// a Lucid payout lifts off from the vault, a store sale comes in from beyond the skyline (shuttle.js).
const skyStation = new THREE.Group();
{
  const metal = new THREE.MeshStandardMaterial({ color: "#c9d2ff", metalness: 0.4, roughness: 0.4, emissive: "#3a3f8a", emissiveIntensity: 0.5 });
  const ring = new THREE.Mesh(new THREE.TorusGeometry(7, 0.7, 10, 48), metal);
  ring.rotation.x = Math.PI / 2;
  skyStation.add(ring);
  const lights = new THREE.Mesh(new THREE.TorusGeometry(7, 0.18, 6, 48), new THREE.MeshBasicMaterial({ color: "#5ee7ff" }));
  lights.rotation.x = Math.PI / 2;
  lights.position.y = 0.6;
  skyStation.add(lights);
  const core = new THREE.Mesh(new THREE.SphereGeometry(2.2, 20, 14), new THREE.MeshStandardMaterial({ color: "#ff3b5c", emissive: "#ff1f4b", emissiveIntensity: 2.2 }));
  skyStation.add(core);
  for (let i = 0; i < 4; i++) {
    const spoke = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 7, 6), metal);
    spoke.rotation.z = Math.PI / 2;
    spoke.rotation.y = (i / 4) * Math.PI;
    skyStation.add(spoke);
  }
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 9, 6), metal);
  skyStation.add(mast);
  skyStation.userData.lights = lights.material;
  skyStation.position.set(-38, 32, -52);
  skyStation.traverse((o) => { if (o.isMesh) o.userData.station = true; });
  scene.add(skyStation);
}
let stationPulse = 0;
const flightsSeen = new Set();
const flying = [];
function launchFlights(s) {
  for (const f of newFlights(flightsSeen, s.station?.flights)) {
    const payout = f.kind === "payout";
    const a = Math.random() * Math.PI * 2;
    const from = payout ? new THREE.Vector3(0, 9, 0) : new THREE.Vector3(Math.cos(a) * 200, 35, Math.sin(a) * 200);
    flying.push(new Flight(scene, f.kind, f.amount, from, skyStation.position.clone().setY(skyStation.position.y - 2),
      { scale: 1.6, height: payout ? 14 : 10, seconds: payout ? 8 : 7, onArrive: () => {
        stationPulse = 1;
        feed(`${payout ? "🚀" : "🛍️"} <b>$${Math.round(f.amount).toLocaleString()}</b> ${payout ? "payout docked at the station treasury" : "sale docked at the station treasury"}`, "win");
      } }));
    if (payout) vaultPulse = 1;
  }
}
function updateFlights(dt, t) {
  for (let i = flying.length - 1; i >= 0; i--) if (!flying[i].update(dt)) flying.splice(i, 1);
  stationPulse = Math.max(0, stationPulse - dt * 0.6);
  skyStation.rotation.y += dt * 0.12;
  skyStation.position.y = 32 + Math.sin(t * 0.4) * 1.2;
  skyStation.scale.setScalar(1 + stationPulse * 0.15);
  skyStation.userData.lights.color.set(stationPulse > 0.05 ? "#3dffa2" : "#5ee7ff");
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
const fmt = (v) => `$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const money = (v) => `${v >= 0 ? "+" : "-"}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

function applyState(s) {
  state = s;
  const waiting = s.station ? s.station.approvals + s.station.owner_tasks : 0;
  document.getElementById("station-badge").textContent = waiting || "";
  const cr = (s.station && s.station.credits) || {};
  const chip = document.getElementById("credits-chip");
  chip.textContent = cr.state === "empty" ? "⛽ empty" : cr.remaining == null ? "⛽ ?" : `⛽ $${cr.remaining.toFixed(2)}`;
  chip.className = cr.state || "";
  if (buildings.size === 0) s.bots.forEach((b, i) => makeBuilding(b, i, s.bots.length));
  const top = s.bots.reduce((a, b) => (b.realized > a.realized ? b : a), s.bots[0]);

  for (const bot of s.bots) {
    const b = buildings.get(bot.id);
    if (!b) continue;
    const statusCls = ["stopped", "walked", "disabled"].includes(bot.status) ? "stopped" : bot.status === "off_duty" ? "off" : "";
    const star = bot.id === top.id && top.realized > 0 ? "★ " : "";
    const live = bot.status === "in_trade" ? ` <span class="earned ${bot.unrealized < 0 ? "neg" : ""}">(${money(bot.unrealized)} open)</span>` : "";
    const gadget = tierOf(bot.career_best) > 0 ? ` <span title="${GADGETS[tierOf(bot.career_best)][2]}">${"💎".repeat(Math.min(3, Math.ceil(tierOf(bot.career_best) / 3)))}</span>` : "";
    b.tag.innerHTML = `<div class="name">${moodEmoji(bot)} ${star}${bot.name}${gadget}</div><div class="status ${statusCls}">${STATUS_TEXT[bot.status](bot)}</div><div class="earned ${bot.realized < 0 ? "neg" : ""}">earned ${money(bot.realized)}${live}</div>`;
    b.tag.classList.toggle("dim", bot.status === "disabled");
    b.tag.classList.toggle("off", bot.status === "disabled");
    b.status = bot.status;
    dressMascot(b, bot);
    b.growTo = Math.min(1.8, Math.max(1, 1 + ((bot.career_best || 0) / 10000) * 0.5));
    const dark = ["disabled", "stopped", "walked"].includes(bot.status);
    b.mats.forEach((m) => (m.emissiveIntensity = dark ? 0.1 : bot.status === "off_duty" ? 0.35 : 0.6));
    b.haloMat.color.set(bot.status === "stopped" || bot.status === "walked" ? "#ff4d6d" : bot.status === "off_duty" ? "#ffd34d" : "#ffffff");
  }

  const vEl = vaultTag.querySelector(".v");
  vEl.textContent = money(s.vault);
  vEl.classList.toggle("neg", s.vault < 0);
  vaultTag.querySelector(".s").textContent = `${s.on_shift} workers on shift · tap for payroll`;
  const short = innerWidth < 640;
  const sess = short ? { "NEW YORK": "NY", LONDON: "LDN", ASIA: "ASIA" }[s.session] ?? s.session : s.session;
  const lag = s.delay_min > 2.5 ? ` <small class="lag">${Math.round(s.delay_min)}m delayed</small>` : "";
  const armed = s.execution?.armed;
  document.getElementById("clock").innerHTML = s.mode === "live"
    ? `<b class="live">● ${armed ? "REAL ORDERS" : short ? "LIVE" : "LIVE PAPER"}</b> ${sess} ${s.clock}${short ? "" : " ET"}${lag}`
    : `SIM · ${sess} · ${s.clock}${short ? "" : " ET"}`;
  document.getElementById("tickers").innerHTML = Object.entries(s.tickers)
    .map(([sym, t]) => `<span>${sym} ${t.price.toFixed(2)} <b class="${t.change_pct >= 0 ? "up" : "down"}">${t.change_pct >= 0 ? "+" : ""}${t.change_pct.toFixed(2)}%</b></span>`).join("");

  document.getElementById("payroll-rows").innerHTML = s.bots
    .map((b) => `<tr><td><span class="dot" style="background:${b.color}"></span>${b.id === top.id && top.realized > 0 ? "👑 " : ""}${b.name}</td><td>${b.trades}</td><td>${b.wins}</td><td class="${b.realized >= 0 ? "pos" : "neg"}">${money(b.realized)}</td></tr>`)
    .join("");

  renderAccount(s.account);
  applyWeather(s);
  launchFlights(s);
  if (openWorkerId) renderWorker();
}

// ---------------------------------------------------------------- phone alerts (web push)
let pushOn = false;
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").then(async (reg) => {
    pushOn = !!(await reg.pushManager?.getSubscription());
  }).catch(() => {});
}
const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
function b64ToBytes(b64) {
  const s = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}
async function turnOnAlerts() {
  if (isIOS && !standalone) return alert("On iPhone, open Starnet from its home-screen icon first, then tap this again.");
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return alert("This browser doesn't support notifications.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return alert("Notifications are blocked. Allow them in Settings → Notifications → Starnet.");
  const { public_key } = await (await fetch("/api/push")).json();
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(public_key) });
  const res = await fetch("/api/push/subscribe", { method: "POST", body: JSON.stringify(sub.toJSON()) });
  pushOn = res.ok;
  if (!res.ok) alert("Couldn't turn on alerts: " + ((await res.json()).detail ?? res.status));
}
async function turnOffAlerts() {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) {
    await fetch("/api/push/unsubscribe", { method: "POST", body: JSON.stringify({ endpoint: sub.endpoint }) });
    await sub.unsubscribe();
  }
  pushOn = false;
}
function alertRows(s) {
  if (s?.mode !== "live" || !s.push) return "";
  const where = [pushOn ? "this phone" : "", s.push.ntfy ? "ntfy" : ""].filter(Boolean).join(" + ");
  return `<div class="row"><span>Trade alerts</span><span class="${where ? "pos" : ""}">${where ? `on · ${where}` : "off"}</span></div>
    <div class="exec-btns">${pushOn
      ? `<button data-push="test">SEND TEST</button><button data-push="off">ALERTS OFF</button>`
      : s.push.web_push ? `<button class="arm" data-push="on">🔔 TURN ON ALERTS</button>` : ""}</div>`;
}

// real orders on your Lucid accounts (live mode only)
function feedLast(s) {
  const problems = (s.watchdog?.problems || []).map((p) => `<div class="halt">🚨 ${esc(p)}</div>`).join("");
  return problems + feedLastRow(s);
}
function feedLastRow(s) {
  const f = s.feed_last;
  if (!f) return `<div class="row"><span>TradingView webhooks</span><span>none received yet</span></div>`;
  const when = new Date(f.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return f.ok
    ? `<div class="row"><span>TradingView webhooks</span><span class="pos">last ${when} · ${esc(f.ticker)} ✓</span></div>`
    : `<div class="halt">TradingView webhook at ${when} rejected: ${esc(f.reason)}</div>`;
}

function execRows(s) {
  if (s?.mode !== "live") return "";
  const x = s.execution, live = s.feed === "tradingview";
  // MNQ trades and MES confirms: both need the real-time feed, or the late MES candles are lost
  const missing = live ? ["MNQ", "MES"].filter((x) => !(s.feed_symbols || []).includes(x)) : [];
  const data = `<div class="row"><span>Price data</span><span class="${live && !missing.length ? "pos" : missing.length ? "neg" : ""}">${live ? `TradingView · real-time (${(s.feed_symbols || []).join(", ")})` : `Yahoo · ${Math.round(s.delay_min)}m delayed`}</span></div>
    ${missing.length ? `<div class="halt">⚠️ ${missing.join(" & ")} not on the real-time feed: add the Starnet feed alert on the ${missing.map((x) => x + "1!").join(" / ")} 1-minute chart too</div>` : ""}
    ${feedLast(s)}`;
  if (!x) return data;
  if (!x.configured) return data + `<div class="row"><span>Real orders</span><span>not connected</span></div>`;
  const open = Object.entries(x.open).map(([sym, p]) => `${p.side === "buy" ? "LONG" : "SHORT"} ${p.qty} ${p.contract}`).join(", ");
  return data + `
    <div class="row"><span>Real orders</span><span class="${x.armed ? "neg" : ""}">${x.armed ? "● ARMED" : "off (paper only)"}</span></div>
    ${x.armed && !x.data_ok ? `<div class="halt">entries paused: price data is over ${x.max_delay} min old</div>` : ""}
    ${open ? `<div class="row"><span>On your accounts</span><span>${open}</span></div>` : ""}
    ${x.last_error ? `<div class="halt">last order failed: ${x.last_error}</div>` : ""}
    <div class="exec-btns">${x.armed
      ? `<button data-exec="disarm">DISARM</button><button class="danger" data-exec="flatten">FLATTEN ALL</button>`
      : `<button class="arm" data-exec="arm">ARM REAL ORDERS</button>`}</div>`;
}

const PHASES = { evaluation: "EVALUATION", funded: "FUNDED", failed: "FAILED" };
function renderAccount(a) {
  if (!a) return;
  document.getElementById("acct-firm").textContent = a.firm.toUpperCase();
  const phase = document.getElementById("acct-phase");
  phase.textContent = PHASES[a.phase];
  phase.className = `phase ${a.phase}`;
  const room = a.equity - a.mll;
  const goalPct = Math.max(0, Math.min(100, (a.day_pnl / a.cap) * 100));
  const stage = a.target
    ? `<div class="row"><span>Target</span><span>${money(a.profit)} / ${fmt(a.target)}</span></div>
       <div class="bar"><i style="width:${Math.max(0, Math.min(100, (a.profit / a.target) * 100))}%"></i></div>`
    : `<div class="row"><span>Payout cycle</span><span>${a.cycle_days} / ${a.payout_days} days ≥ ${fmt(a.payout_day_min)} · net ${money(a.cycle_net)}</span></div>
       <div class="bar"><i style="width:${Math.min(100, (a.cycle_days / a.payout_days) * 100)}%"></i></div>
       <div class="row"><span>Payout</span><span class="${a.payout_eligible ? "pos" : ""}">${a.payout_eligible
         ? `up to ${fmt(a.payout_limit)} · ${a.safe_payout ? `take ${fmt(a.safe_payout)}` : `wait (keeps ${fmt(a.keep_room)} room)`}`
         : "not yet"}</span></div>
       <div class="row"><span>Paid out</span><span>${fmt(a.paid_out)} (${a.payouts}/${a.max_payouts ?? "∞"}) · you keep ${fmt(a.paid_out * 0.9)}</span></div>
       ${a.scale_micros ? `<div class="row"><span>Scaling plan</span><span>${a.scale_micros} micros max today</span></div>` : ""}
       ${a.payout_eligible ? `<button class="desk-btn" data-payout="${a.safe_payout || a.payout_limit}">💸 RECORD A PAYOUT</button>` : ""}`;
  document.getElementById("acct-sum").innerHTML = `
    <span>${fmt(a.balance)}</span>
    <span class="${a.day_pnl >= 0 ? "pos" : "neg"}">today ${money(a.day_pnl)}</span>
    <span class="${room < 500 ? "neg" : ""}">${fmt(Math.max(0, room))} room</span>
    <span class="more">▾</span>`;
  document.getElementById("acct-body").innerHTML = `
    <div class="row"><span>Balance</span><span>${fmt(a.balance)}</span></div>
    ${stage}
    <div class="row"><span>Drawdown</span><span>${fmt(a.mll)}${a.mll_locked ? " 🔒" : ""} · <b class="${room < 500 ? "neg" : ""}">${fmt(Math.max(0, room))} room</b></span></div>
    <div class="row"><span>Today</span><span class="${a.day_pnl >= 0 ? "pos" : "neg"}">${money(a.day_pnl)}${a.goal_reached ? " · goal ✓" : ""}</span></div>
    <div class="row"><span>Day goal</span><span>${fmt(a.goal)} → ${fmt(a.cap)} cap</span></div>
    <div class="bar day"><i style="width:${goalPct}%"></i><em style="left:${(a.goal / a.cap) * 100}%"></em></div>
    <div class="row"><span>Day stop</span><span>-${fmt(a.daily_stop)}</span></div>
    <div class="row"><span>Micros open</span><span>${a.open_micros} / ${a.max_micros}</span></div>
    <div class="row"><span>Best day</span><span>${fmt(a.best_day)}${a.consistency ? ` (max ${a.consistency * 100}%)` : ""} · day ${a.days}</span></div>
    ${state.mode === "live" ? `<button class="reports-btn" data-reports>📒 DAILY REPORTS</button>` : ""}
    ${state.accounts ? `<button class="desk-btn" data-accounts>👥 MY LUCID ACCOUNTS (${state.accounts.count})${state.accounts.payouts_ready ? ` · ${fmt(state.accounts.payouts_ready)} READY` : ""}</button>` : ""}
    <button class="desk-btn" data-scale>📈 SCALE PLAN: NEXT PAYOUTS & ACCOUNTS</button>
    ${state.mode === "live" ? `<button class="desk-btn" data-signals>🎯 SIGNAL CHECK VS. YOUR INDICATOR</button>` : ""}
    ${deskRow(state)}
    ${scoreRows(state)}
    ${historyRows(state)}
    ${newsRows(state)}
    ${alertRows(state)}
    ${execRows(state)}
    ${a.halted ? `<div class="halt">${a.halted}</div>` : ""}
    ${a.phase === "failed" || a.halted.includes("reset") ? `<button class="reset" data-reset>RESET EVALUATION</button>` : ""}
    ${state.mode === "live" ? `<button class="desk-btn" data-sync>🔄 SYNC WITH MY LUCID ACCOUNT</button>` : ""}`;
}

function scoreRows(s) {
  const c = s.scorecard;
  if (!c) return "";
  const p = c.paper, b = c.backtest;
  const pct = (v) => (v == null ? "—" : `${v}%`);
  const cash = (v) => (v == null ? "—" : money(v));
  const last = c.last
    ? `<div class="row"><span>Last day ${c.last.day.slice(5)}</span><span class="${c.last.verdict === "match" ? "pos" : "neg"}">${money(c.last.live_pnl)} vs replay ${money(c.last.replay_pnl)} ${c.last.verdict === "match" ? "✓" : "⚠"}</span></div>`
    : `<div class="row"><span>Replay check</span><span>${c.running ? "running…" : "after the first full day"}</span></div>`;
  return `<div class="row"><span><b>📊 Paper vs backtest</b></span><span>${p.days} day${p.days === 1 ? "" : "s"}</span></div>
    <div class="row"><span>Green days</span><span>${pct(p.profitable_day_pct)} · bt ${b.profitable_day_pct}%</span></div>
    <div class="row"><span>Avg day</span><span>${cash(p.avg_day)} · bt ${money(b.avg_day)}</span></div>
    <div class="row"><span>Profit factor</span><span>${p.profit_factor ?? "—"} · bt ${b.profit_factor}</span></div>
    ${c.clean_days ? `<div class="row"><span>Replay match</span><span>${c.clean_days_matched}/${c.clean_days} days · ${pct(c.trade_match_pct)} trades</span></div>` : ""}
    ${last}`;
}

function historyRows(s) {
  const h = s.history;
  if (!h) return "";
  const syms = Object.keys(h.symbols);
  const span = syms.length ? `${h.symbols[syms[0]].first} → ${(h.symbols[syms[0]].last || "").slice(0, 10)}` : "saving…";
  return `<div class="row"><span><b>📼 Candle history</b></span><span>${h.days} days · ${span}</span></div>
    ${syms.length ? `<div class="row"><span>Download</span><span>${syms.map((x) => `<a href="/api/history/${x}.csv" download>${x}</a>`).join(" · ")}</span></div>` : ""}
    ${tvRows(h)}`;
}
function tvRows(h) {   // the TradingView feed's own candles, saved as they arrive
  const tv = h.tradingview || {}, syms = Object.keys(tv);
  if (!syms.length) return `<div class="row"><span>TradingView candles</span><span>start with the first feed candle</span></div>`;
  const first = syms.map((x) => tv[x].first).sort()[0];
  const vol = syms.some((x) => tv[x].volume);
  return `<div class="row"><span>TradingView candles</span><span>${h.tv_days} days since ${first}${vol ? " · with volume" : ""}</span></div>
    <div class="row"><span>Download</span><span>${syms.map((x) => `<a href="/api/history/tradingview/${x}.csv" download>${x} (TV)</a>`).join(" · ")}</span></div>`;
}

function newsRows(s) {
  const n = s.news;
  if (!n) return "";
  const hold = n.hold ? `<div class="halt">📰 ${n.hold} · paused until ${n.hold_until}</div>` : "";
  const next = n.next.length
    ? n.next.slice(0, 3).map((e) => `<div class="row"><span>${e.time}</span><span>${e.title}</span></div>`).join("")
    : `<div class="row"><span>News</span><span>no high-impact USD news ahead</span></div>`;
  return `<div class="row"><span><b>📰 News filter</b></span><span>${n.error ? "using saved calendar" : "on"}</span></div>${hold}${next}`;
}

// ---------------------------------------------------------------- signal check
async function sigPost(day, action, body) {
  const r = await fetch(`/api/signals/${day}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) alert((await r.json()).detail);
}

async function openSignals(day = null) {
  const panel = document.getElementById("signals"), body = document.getElementById("signals-body");
  panel.classList.remove("hidden");
  let list;
  try { list = await (await fetch("/api/signals")).json(); } catch { body.innerHTML = `<p class="note">live mode only</p>`; return; }
  const st = list.stats;
  const head = `<p class="note">Compare each PROC the bots traded with Andrew Macre's indicator on your MNQ chart (same timeframe, same candle time).
    Your ✅/❌ show exactly where our rebuild of his indicator differs, so it can be fixed.</p>
    <div class="row"><span>Your checks so far</span><span>${st.reviewed ? `${st.match_pct}% match · ${st.reviewed} checked · ${st.missed} missed` : "none yet"}</span></div>`;
  if (!day) {
    body.innerHTML = head + (list.days.map((d) => `<div class="day" data-sig-day="${d.day}"><div class="row"><b>${d.day}</b>
      <span>${d.signals} traded PROC${d.signals === 1 ? "" : "s"} · ${d.reviewed}/${d.signals} checked${d.no ? ` · ${d.no} ❌` : ""}</span></div></div>`).join("")
      || `<p class="note">The first PROCs show up here after the bots' first trades.</p>`);
    return;
  }
  const doc = await (await fetch(`/api/signals/${day}`)).json();
  const tfs = ["3m", "4m", "5m", "6m"];
  const counts = Object.keys(doc.counts).length ? `<table><tr><th>PROCs seen</th>${tfs.map((t) => `<th>${t}</th>`).join("")}</tr>
    ${Object.entries(doc.counts).map(([s, c]) => `<tr><td>${s}</td>${tfs.map((t) => `<td>${c[t] || 0}</td>`).join("")}</tr>`).join("")}</table>
    <small class="note">How many PROCs our engine saw per killzone. If your indicator shows far fewer, ours is too loose.</small>` : "";
  const cards = doc.signals.map((s) => {
    const v = doc.votes[s.id]?.vote;
    return `<div class="sig">
      <div class="row"><b>${s.tf}m PROC ${s.side === "long" ? "↑ LONG" : "↓ SHORT"} · ${s.clock} candle</b><span>${s.session || ""} · ${esc(s.handle)}</span></div>
      <small>off the ${s.zone.tf}m ${s.zone.kind} ${s.zone.bottom.toFixed(2)}–${s.zone.top.toFixed(2)} · closed ${s.closed} · entry ${s.entry.toFixed(2)}</small>
      <canvas data-sig-chart="${s.id}"></canvas>
      <div class="actions">
        <button class="yes ${v === "yes" ? "on" : ""}" data-sig-vote="yes" data-id="${s.id}" data-day="${day}">✅ ON MY CHART</button>
        <button class="no ${v === "no" ? "on" : ""}" data-sig-vote="no" data-id="${s.id}" data-day="${day}">❌ NOT ON MY CHART</button>
      </div>${doc.votes[s.id]?.note ? `<small>note: ${esc(doc.votes[s.id].note)}</small>` : ""}</div>`;
  }).join("");
  const missed = doc.missed.map((m) => `<li>${m.clock} · ${m.tf}m ${m.side}${m.note ? ` · ${esc(m.note)}` : ""}</li>`).join("");
  body.innerHTML = `${head}<div class="actions"><button data-signals>← ALL DAYS</button></div><h4 style="margin:10px 0 4px">${day}</h4>${counts}
    ${cards || `<p class="note">No traded PROCs this day.</p>`}
    ${missed ? `<div class="sig"><b>PROCs you saw that the bots missed</b><ul>${missed}</ul></div>` : ""}
    <div class="actions"><button data-sig-missed="${day}">＋ ADD A PROC THE BOTS MISSED</button></div>`;
  for (const s of doc.signals) drawSignal(body.querySelector(`[data-sig-chart="${s.id}"]`), s);
}

function drawSignal(canvas, s) {
  const dpr = devicePixelRatio || 1, W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const tf = s.tf, bars = [];
  for (const [t, o, h, l, c] of s.candles) {   // 1m candles -> the PROC's timeframe, clock-aligned
    const k = t - (t % tf), last = bars[bars.length - 1];
    if (last && last[0] === k) { last[2] = Math.max(last[2], h); last[3] = Math.min(last[3], l); last[4] = c; }
    else bars.push([k, o, h, l, c]);
  }
  if (!bars.length) { g.fillStyle = "#7f88b5"; g.font = "12px Inter, sans-serif"; g.fillText("chart ready after the day closes", 10, H / 2); return; }
  let lo = Math.min(...bars.map((b) => b[3]), s.zone.bottom), hi = Math.max(...bars.map((b) => b[2]), s.zone.top);
  const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
  const L = 4, R = W - 4, step = (R - L) / bars.length;
  const x = (i) => L + (i + 0.5) * step, y = (p) => 4 + (1 - (p - lo) / (hi - lo)) * (H - 8);
  const idx = (t) => bars.findIndex((b) => b[0] === t - (t % tf));
  const zi = Math.max(0, bars.findIndex((b) => b[0] >= s.zone.created - (s.zone.created % tf)));
  g.fillStyle = s.zone.side === "long" ? "rgba(8,153,129,.3)" : "rgba(242,54,70,.3)";
  g.fillRect(x(zi) - step / 2, y(s.zone.top), R - x(zi) + step / 2, Math.max(2, y(s.zone.bottom) - y(s.zone.top)));
  bars.forEach(([, o, h, l, c], i) => {
    g.strokeStyle = g.fillStyle = c >= o ? "#26d07c" : "#ff4d6d";
    g.beginPath(); g.moveTo(x(i), y(h)); g.lineTo(x(i), y(l)); g.stroke();
    g.fillRect(x(i) - step * 0.3, Math.min(y(o), y(c)), step * 0.6, Math.max(1, Math.abs(y(o) - y(c))));
  });
  const pi = idx(s.t);
  if (pi >= 0) {
    g.strokeStyle = s.side === "long" ? "#4dff9a" : "#ff5470"; g.lineWidth = 2;
    g.strokeRect(x(pi) - step * 0.6, y(s.box.high) - 2, step * 1.2, y(s.box.low) - y(s.box.high) + 4);
    g.fillStyle = g.strokeStyle; g.font = "bold 10px Inter, sans-serif";
    g.fillText(`${s.tf}m PROC`, Math.min(x(pi) + step, R - 50), y(s.box.high) - 4);
  }
  const ei = idx(s.entry_t);
  if (ei >= 0) {
    g.fillStyle = "#ffd34d"; g.beginPath();
    const ey = y(s.entry), up = s.side === "long";
    g.moveTo(x(ei), ey); g.lineTo(x(ei) - 6, ey + (up ? 10 : -10)); g.lineTo(x(ei) + 6, ey + (up ? 10 : -10)); g.fill();
  }
}

// ---------------------------------------------------------------- lucid accounts
let acctData = null;
async function openAccounts() {
  const panel = document.getElementById("accounts"), body = document.getElementById("accounts-body");
  panel.classList.remove("hidden");
  try { acctData = await (await fetch("/api/accounts")).json(); } catch { body.innerHTML = `<p class="note">accounts are tracked in live mode</p>`; return; }
  const d = acctData;
  const cards = d.accounts.map((a) => {
    const room = Math.max(0, a.room), roomPct = Math.min(100, (room / 2000) * 100);
    const status = a.phase === "failed" ? "failed" : a.halted ? `stopped today: ${esc(a.halted)}` : a.can_enter ? "trading" : "no new entries today";
    const stage = a.phase === "evaluation"
      ? `<div class="row"><span>Target</span><span>${money(a.profit)} / ${fmt(a.target)}</span></div>
         <div class="bar"><i style="width:${Math.max(0, Math.min(100, (a.profit / a.target) * 100))}%"></i></div>`
      : a.phase === "funded"
      ? `<div class="row"><span>Payout cycle</span><span>${a.cycle_days}/${a.payout_days} days ≥ ${fmt(a.payout_day_min)} · net ${money(a.cycle_net)}</span></div>
         <div class="bar"><i style="width:${Math.min(100, (a.cycle_days / a.payout_days) * 100)}%"></i></div>
         <div class="row"><span>Payout</span><span class="${a.payout_eligible ? "pos" : ""}">${a.payout_eligible ? `up to ${fmt(a.payout_limit)} · ${a.safe_payout ? `take ${fmt(a.safe_payout)}` : "wait for cushion"}` : "not yet"}</span></div>
         <div class="row"><span>Paid out</span><span>${fmt(a.paid_out)} (${a.payouts}/${a.max_payouts ?? "∞"})</span></div>` : "";
    return `<div class="card ${a.phase}">
      <h5><span>${esc(a.name)}</span><span><span class="tag3 ${a.phase}">${a.phase.toUpperCase()}</span>${a.routed ? `<span class="tag3 route">OWN WEBHOOK</span>` : ""}</span></h5>
      <div class="row"><span>Balance</span><span>${fmt(a.balance)} · today <b class="${a.day_pnl >= 0 ? "pos" : "neg"}">${money(a.day_pnl)}</b></span></div>
      <div class="row"><span>Room to MLL ${fmt(a.mll)}${a.mll_locked ? " 🔒" : ""}</span><span class="${room < 500 ? "neg" : ""}">${fmt(room)}</span></div>
      <div class="bar room"><i style="width:${roomPct}%"></i></div>
      ${stage}
      <div class="row"><span>Status</span><span>${status}</span></div>
      <div class="actions">
        ${a.payout_eligible ? `<button class="go" data-acct="payout" data-id="${a.id}">💸 PAYOUT</button>` : ""}
        <button data-acct="sync" data-id="${a.id}">SYNC</button>
        <button data-acct="webhook" data-id="${a.id}">${a.routed ? "WEBHOOK ✓" : "ADD WEBHOOK"}</button>
        <button data-acct="remove" data-id="${a.id}">REMOVE</button>
      </div></div>`;
  }).join("");
  body.innerHTML = `
    <div class="sum"><div><b>${d.count}</b><small>accounts</small></div>
      <div><b class="pos">${fmt(d.payouts_ready)}</b><small>payouts ready now</small></div>
      <div><b>${fmt(d.paid_out * 0.9)}</b><small>you've kept (90%)</small></div></div>
    ${cards || `<p class="note">Add each Lucid account you buy. The bots' trades are applied to every account, so you can see each one's drawdown room, evaluation progress and payouts. Give an account its own TradersPost webhook and accounts that must stop (target reached, daily stop, close to the MLL) are left out of new trades automatically.</p>`}
    <button class="add" data-acct="add">＋ ADD A LUCID ACCOUNT</button>`;
}

// ---------------------------------------------------------------- scale plan (backend/scale.py)
let scaleData = null;
const STAGE_ICON = { evaluation: "🎯", passing: "✅", funded: "💼", "payout ready": "💸", live: "🏁", failed: "✖" };
async function openScale() {
  const panel = document.getElementById("scale"), body = document.getElementById("scale-body");
  panel.classList.remove("hidden");
  try { scaleData = await (await fetch("/api/scale")).json(); } catch { body.innerHTML = `<p class="note">scale plan unavailable</p>`; return; }
  const d = scaleData, n = d.next_eval;
  const day = (iso) => iso ? new Date(iso + "T12:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) : "—";
  const lane = (stage, label) => {
    const rows = d.accounts.filter((a) => a.stage === stage);
    return rows.length ? `<div class="lane"><h5>${STAGE_ICON[stage]} ${label} <small>${rows.length}</small></h5>${rows.map((a) => `
      <div class="card ${stage.replace(" ", "-")}"><div class="row"><b>${esc(a.name)}</b><span>${a.eta ? day(a.eta) : ""}</span></div>
      <div class="row"><span>${esc(a.next)}</span></div>
      ${stage === "evaluation" ? `<div class="bar"><i style="width:${Math.max(0, Math.min(100, (a.profit / (a.profit + a.left)) * 100))}%"></i></div>` : ""}
      ${a.paid_out ? `<div class="row"><span class="muted">paid out</span><span>${fmt(a.paid_out)} (${a.payouts}/${a.max_payouts ?? "∞"})</span></div>` : ""}</div>`).join("")}</div>` : "";
  };
  body.innerHTML = `
    ${d.mode !== "live" ? `<p class="note">Simulation: this plan uses the simulated account. In live mode it reads your 👥 accounts.</p>` : ""}
    <div class="sum"><div><b>${d.accounts.length}</b><small>accounts (limit ${d.limit})</small></div>
      <div><b class="pos">${d.coming.length ? fmt(d.coming[0].amount) : "—"}</b><small>next payout${d.coming.length ? ` · ${day(d.coming[0].eta)}` : ""}</small></div>
      <div><b>${d.monthly_ceiling ? fmt(d.monthly_ceiling) : "—"}</b><small>monthly ceiling (est.)</small></div></div>
    ${lane("payout ready", "Payout ready")}${lane("funded", "Funded")}${lane("passing", "Passing")}${lane("evaluation", "In evaluation")}${lane("live", "Moved to live")}${lane("failed", "Failed")}
    <div class="next ${n.can_fund ? "go" : ""}"><h5>🚀 Next account</h5><p>${esc(n.text)}</p>
      ${n.price ? `<div class="row"><span>Treasury free (after a month of bills)</span><span>${fmt(n.free)} / ${fmt(n.price)}</span></div>
      <div class="bar"><i style="width:${Math.min(100, (n.free / n.price) * 100)}%"></i></div>` : ""}
      <p class="muted">${n.can_fund ? "ULTRON has put the purchase in your approvals. Nothing is bought for you: you buy it at Lucid, then add it under 👥." : "When the treasury covers it, ULTRON asks you to approve the purchase."}</p>
      <button data-scale-set>${n.price ? `PRICE ${fmt(n.price)} · LIMIT ${d.limit} · EDIT` : "SET THE EVALUATION PRICE"}</button></div>
    ${d.coming.length ? `<h5>💸 Payouts coming (your 90%)</h5>${d.coming.map((c) => `<div class="row"><span>${day(c.eta)} · ${esc(c.account)}</span><span class="pos">${fmt(c.amount)}</span></div>`).join("")}` : ""}
    <p class="note">Estimates at ${fmt(d.pace.avg_day)}/day (${esc(d.pace.source)}), with about ${Math.round(d.pace.qualify_rate * 100)}% of days making $150+. Lucid pays up to 50% of profit, $2,000 max per payout, 5 payouts per account.</p>`;
}

async function accountAction(action, id) {
  const a = acctData?.accounts.find((x) => x.id === id);
  const post = async (path, body) => {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
    if (!r.ok) alert((await r.json()).detail);
    return r.ok;
  };
  const ask = (q, v) => prompt(q, v ?? "");
  if (action === "add" || action === "sync") {
    const name = action === "add" ? ask("Account name (e.g. Flex #1):", `Flex #${(acctData?.count || 0) + 1}`) : a.name;
    if (name === null) return;
    const phase = ask("Phase (evaluation or funded):", a?.phase === "funded" ? "funded" : "evaluation");
    if (!phase) return;
    const balance = ask("Balance from your Lucid dashboard ($):", a ? Math.round(a.balance) : 50000);
    if (!balance) return;
    const mll = ask("Max Loss Limit / MLL ($):", a ? Math.round(a.mll) : 48000);
    if (!mll) return;
    let payouts = 0, cycle = 0;
    if (phase.trim() === "funded") {
      payouts = ask("Payouts taken so far:", a?.payouts ?? 0); if (payouts === null) return;
      cycle = ask("Days this payout cycle with $150+ profit:", a?.cycle_days ?? 0); if (cycle === null) return;
    }
    const body = { name, phase: phase.trim(), balance: +balance, mll: +mll, payouts: +payouts, cycle_days: +cycle };
    if (action === "add") body.webhook = ask("Optional: this account's own TradersPost webhook URL (leave empty if it copies the main strategy):", "") || "";
    await post(action === "add" ? "/api/accounts" : `/api/accounts/${id}/sync`, body);
  } else if (action === "payout") {
    const amt = ask(`Record a payout you requested at Lucid for ${a.name}.\nAllowed up to $${a.payout_limit.toLocaleString()} (min $500). Suggested $${(a.safe_payout || 0).toLocaleString()}.\n\nAmount:`, a.safe_payout || a.payout_limit);
    if (amt) await post(`/api/accounts/${id}/payout`, { amount: +amt });
  } else if (action === "webhook") {
    const url = ask(`TradersPost webhook URL for ${a.name} only (empty = it copies the main strategy):`, "");
    if (url !== null) await post(`/api/accounts/${id}/webhook`, { url });
  } else if (action === "remove") {
    if (confirm(`Stop tracking ${a.name}? (This doesn't touch the account at Lucid.)`)) await post(`/api/accounts/${id}/remove`);
  }
  openAccounts();
}

// ---------------------------------------------------------------- trading desk
// everything the desk writes comes from a model that read the web: always escape it
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function deskRow(s) {
  const d = s.desk;
  if (!d) return "";
  if (!d.enabled) return `<div class="row"><span><b>🧠 Desk</b></span><span>off · add ANTHROPIC_API_KEY</span></div>`;
  const mode = d.mode.replace("_", " ").toUpperCase();
  return `<div class="row"><span><b>🧠 Desk mode</b></span><span class="${d.mode === "normal" ? "pos" : "neg"}">${d.act ? mode : "advisory"}${d.running ? " · meeting…" : ""}</span></div>
    ${d.why ? `<div class="row"><span></span><span style="text-align:right;max-width:75%">${esc(d.why)}</span></div>` : ""}
    <button class="desk-btn" data-desk>🧠 DESK NOTES & JOURNALS</button>`;
}

let deskBot = null;
async function openDesk(botId = null) {
  deskBot = botId;
  const panel = document.getElementById("desk"), body = document.getElementById("desk-body");
  panel.classList.remove("hidden");
  body.innerHTML = `<p class="note">loading…</p>`;
  let d;
  try { d = await (await fetch("/api/desk")).json(); } catch { body.innerHTML = `<p class="note">the desk only runs in live mode</p>`; return; }
  if (!d.enabled) {
    body.innerHTML = `<p class="note">The desk runs on Claude. Add an <b>ANTHROPIC_API_KEY</b> environment variable on Render to switch it on.</p>`;
    return;
  }
  const name = (id) => { const b = state?.bots.find((x) => x.id === id); return b?.persona?.handle || b?.name || id; };
  const days = d.days.map((day) => {
    const m = day.morning, e = day.evening;
    const journals = (e?.journals || []).filter((j) => !botId || j.bot_id === botId).map((j) => `
      <div class="entry"><b>${name(j.bot_id)}</b> · ${esc(j.mood)}<br>${esc(j.entry)}
        <small>lesson: ${esc(j.lesson)}</small><small>focus: ${esc(j.focus_tomorrow)}</small></div>`).join("");
    const notes = (m?.bot_notes || []).filter((n) => !botId || n.bot_id === botId).map((n) => `<li><b>${name(n.bot_id)}</b>: ${esc(n.note)}</li>`).join("");
    return `<h4>${new Date(day.day + "T12:00").toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" })}</h4>
      ${m ? `<div class="entry"><b>☀️ Morning briefing</b> <span class="mode ${m.mode}">${m.mode.replace("_", " ")}</span><br>${esc(m.briefing)}
        <ul>${m.drivers.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>${m.watch.length ? `<small>watch: ${esc(m.watch.join(" · "))}</small>` : ""}
        <small>${esc(m.mode_why)}</small>${notes ? `<ul>${notes}</ul>` : ""}</div>` : ""}
      ${e && !botId ? `<div class="entry"><b>🌙 Desk meeting</b> <span class="mode ${e.next_mode}">${e.next_mode.replace("_", " ")}</span><br>${esc(e.desk_summary)}<small>${esc(e.next_mode_why)}</small></div>` : ""}
      ${journals}`;
  }).join("");
  body.innerHTML = `
    <div class="row"><span>Risk mode</span><span><span class="mode ${d.mode}">${d.mode.replace("_", " ")}</span>${d.until ? ` until ${new Date(d.until).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}` : ""}</span></div>
    <div class="row"><span>Desk can take risk off</span><span>${d.act ? "yes" : "no (advisory only)"}</span></div>
    ${d.error ? `<small>last error: ${esc(d.error)}</small>` : ""}
    <div class="actions">
      <button data-desk-meeting="morning">HOLD BRIEFING NOW</button>
      <button data-desk-meeting="evening">HOLD REVIEW NOW</button>
      <button data-desk-act="${d.act ? "off" : "on"}">${d.act ? "MAKE ADVISORY ONLY" : "LET DESK ACT"}</button>
    </div>
    ${!botId && d.lessons_list.length ? `<h4>STANDING LESSONS</h4><ul>${d.lessons_list.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
    ${botId ? `<h4>${name(botId).toUpperCase()}'S JOURNAL</h4>` : ""}
    ${days || `<p class="note">No meetings yet. The first desk meeting runs after today's close (~6pm ET); the morning briefing runs at 8:40 ET on weekdays.</p>`}`;
}
document.getElementById("room-journal").onclick = () => openDesk(roomBotId);
if (new URLSearchParams(location.search).get("desk")) setTimeout(() => openDesk(), 1500);

// ---------------------------------------------------------------- daily reports
async function openReports(day = null) {
  const panel = document.getElementById("reports"), body = document.getElementById("reports-body");
  panel.classList.remove("hidden");
  body.innerHTML = `<p class="note">loading…</p>`;
  let list = [];
  try { list = await (await fetch("/api/reports")).json(); } catch { /* shown as empty */ }
  if (!Array.isArray(list) || !list.length) {
    body.innerHTML = `<p class="note">The first report arrives after the first full trading day (it's pushed to your phone around 6pm ET).</p>`;
    return;
  }
  body.innerHTML = list.map((r) => `
    <div class="day" data-report-day="${r.day}">
      <div class="row"><span><b>${new Date(r.day + "T12:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</b>
        ${r.passed ? `<span class="tag2">PASSED</span>` : ""}${r.goal_hit ? `<span class="tag2">GOAL</span>` : ""}</span>
        <span><b class="${r.pnl >= 0 ? "pos" : "neg"}">${money(r.pnl)}</b> · ${r.trades} trade${r.trades === 1 ? "" : "s"}${r.check ? ` · replay ${r.check === "match" ? "✅" : "⚠️"}` : ""}</span></div>
      <div class="detail hidden" id="report-${r.day}"></div>
    </div>`).join("");
  if (day) toggleReport(day, true);
}

async function toggleReport(day, open = false) {
  const el = document.getElementById(`report-${day}`);
  if (!el) return;
  if (!el.classList.contains("hidden") && !open) { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");
  el.innerHTML = `<p class="note">loading…</p>`;
  const r = await (await fetch(`/api/reports/${day}`)).json();
  const a = r.account;
  const progress = a.phase === "evaluation" && a.target
    ? `Evaluation ${money(a.profit)} / ${fmt(a.target)} (${Math.max(0, Math.round((100 * a.profit) / a.target))}%)`
    : `Funded ${money(a.profit)} · ${a.profitable_days}/${a.payout_days} payout days${a.payout_eligible ? " · payout eligible" : ""}`;
  const c = r.check;
  const check = c
    ? `<div class="row"><span>Replay check</span><span class="${c.verdict === "match" ? "pos" : "neg"}">${c.verdict === "match" ? "✅ matched" : "⚠️ drift"} · ${c.matched}/${Math.max(c.live_trades, c.replay_trades)} trades · replay ${money(c.replay_pnl)}</span></div>
       ${c.explained_by.length ? `<small class="note">${c.explained_by.join("; ")}</small>` : ""}
       ${c.only_replay.length ? `<small class="note">replay only: ${c.only_replay.join(", ")}</small>` : ""}
       ${c.only_live.length ? `<small class="note">paper only: ${c.only_live.join(", ")}</small>` : ""}`
    : `<div class="row"><span>Replay check</span><span>pending</span></div>`;
  const trades = r.trades.map((t) => `
    <div class="trade"><b class="${t.pnl >= 0 ? "pos" : "neg"}">${money(t.pnl)}</b> · ${t.handle} ${t.side.toUpperCase()} ×${t.qty} · ${t.opened}→${t.closed}
      <small>in: ${t.why || "—"} @ ${t.entry}${t.adds.length ? ` · added: ${t.adds.join(", ")}` : ""}</small>
      ${t.trims?.length ? `<small>trimmed: ${t.trims.map((x) => `${x.qty} @ ${x.price} ${money(x.pnl)}`).join(", ")}</small>` : ""}
      <small>out: ${t.exit_reason} @ ${t.exit}</small></div>`).join("");
  el.innerHTML = `
    <div class="row"><span>Day</span><span><b class="${r.pnl >= 0 ? "pos" : "neg"}">${money(r.pnl)}</b> · ${r.wins}W ${r.losses}L${r.goal_hit ? " · goal ✓" : ""}</span></div>
    <div class="row"><span>Account</span><span>${progress}</span></div>
    <div class="row"><span>Room to MLL</span><span>${fmt(r.room)}</span></div>
    ${check}
    ${r.news.length ? `<div class="row"><span>News pauses</span><span>${r.news.join(", ")}</span></div>` : ""}
    ${r.halts.length ? `<div class="row"><span>Stopped</span><span>${r.halts.join(", ")}</span></div>` : ""}
    ${r.partial ? `<small class="note">the server restarted during this day, so some trades may be missing</small>` : ""}
    ${r.desk ? `<div class="trade"><b>🧠 Desk</b> · next session ${r.desk.mode.replace("_", " ")}<small>${esc(r.desk.summary)}</small>
      ${r.desk.journals.map((j) => `<small><b>${esc(j.bot_id)}</b> (${esc(j.mood)}): ${esc(j.entry)}</small>`).join("")}</div>` : ""}
    ${trades || `<p class="note">no trades</p>`}`;
}

const wantReport = new URLSearchParams(location.search).get("report");
if (wantReport) setTimeout(() => openReports(wantReport), 1500);
navigator.serviceWorker?.addEventListener("message", (e) => {
  const u = e.data?.open && new URL(e.data.open, location.href);
  if (u?.searchParams.get("report")) openReports(u.searchParams.get("report"));
  else if (u?.searchParams.get("desk")) openDesk();
});

// ---------------------------------------------------------------- activity feed
const lastSetup = new Map();
const nameOf = (id) => state?.bots.find((b) => b.id === id)?.name ?? id;
function feed(text, cls = "") {
  const list = document.getElementById("feed-list");
  list.querySelector(".muted")?.remove();
  const li = document.createElement("li");
  li.className = cls;
  li.innerHTML = `<time>${state?.clock ?? ""}</time> ${text}`;
  list.prepend(li);
  while (list.children.length > 40) list.lastChild.remove();
}
function feedEvents(events) {
  for (const ev of events) {
    const who = `<b>${nameOf(ev.bot)}</b>`;
    if (ev.type === "trade_open") feed(`${who} entered ${ev.contract} ×${ev.qty}${ev.note ? ` · ${ev.note}` : ""}`, "open");
    else if (ev.type === "trade_add") feed(`${who} added ${ev.qty} → ${ev.total} contracts · ${ev.why}`, "open");
    else if (ev.type === "trade_trim") feed(`${who} trimmed ${ev.qty} ${money(ev.pnl)} · ${ev.left} left · ${ev.why}`, "win");
    else if (ev.type === "trade_close") {
      const whole = ev.trade_pnl ?? ev.pnl;
      feed(`${who} closed ${money(whole)}${whole !== ev.pnl ? ` (runner ${money(ev.pnl)})` : ""} · ${ev.reason}`, whole >= 0 ? "win" : "loss");
    }
    else if (ev.type === "account_halt") feed(`<b>Account</b> ${ev.reason}`, /cap|target/.test(ev.reason) ? "win" : "loss");
    else if (ev.type === "tv_signal") feed(`${who} TradingView: ${ev.action}`);
    else if (ev.type === "new_session") feed(`<b>New trading day</b>`, "muted2");
    else if (ev.type === "acct_event") feed(`👥 ${esc(ev.text)}`, { passed: "win", payout: "win", failed: "loss", halt: "think" }[ev.what] || "");
    else if (ev.type === "desk_mode") feed(`🧠 <b>Desk</b> ${ev.mode.replace("_", " ")} until ${ev.until} · ${esc(ev.why)}`, "think");
    else if (ev.type === "desk_meeting") feed(`🧠 <b>${ev.kind === "evening" ? "Desk meeting" : "Morning briefing"}</b> · ${ev.session}: ${ev.mode.replace("_", " ")} · ${esc(ev.why)}`, "think");
    else if (ev.type === "news_hold") feed(`📰 <b>${ev.title}</b> at ${ev.at} · no new trades until ${ev.until}`, "think");
  }
}
function feedSetups(s) {   // what each working bot is thinking: PROC seen, waiting for MES, skipped…
  for (const b of s.bots) {
    const setup = b.info?.setup;
    if (!setup || b.status === "disabled" || lastSetup.get(b.id) === setup) continue;
    const first = !lastSetup.has(b.id);
    lastSetup.set(b.id, setup);
    if (!first && !/waiting for a PROC|entered|closed/.test(setup)) feed(`<b>${b.name}</b> ${setup}`, "think");
  }
}

// ---------------------------------------------------------------- streamer rooms
let room = null, roomBotId = null, roomTimer = null;
async function refreshRoom() {
  const bot = state?.bots.find((b) => b.id === roomBotId);
  if (!bot) return;
  try {
    const data = await (await fetch(`/api/bots/${roomBotId}/room`)).json();
    room.update(bot, data);
  } catch { /* next refresh */ }
}
function openRoom(id) {
  const bot = state?.bots.find((b) => b.id === id);
  if (!bot) return;
  const el = document.getElementById("room");
  el.classList.remove("hidden");
  el.style.setProperty("--accent", bot.color);
  document.getElementById("room-title").innerHTML = `<b>${bot.persona?.handle || bot.name}</b> <span>${bot.name} · ${bot.persona?.vibe || ""}</span>`;
  room ||= new Room(document.getElementById("room-view"));
  if (roomBotId !== id) { room.build(bot, { phase: state?.account?.phase }); room.chat = []; }
  roomBotId = id;
  room.start();
  refreshRoom();
  clearInterval(roomTimer);
  roomTimer = setInterval(refreshRoom, 2000);
  openWorkerId = null;
  document.getElementById("worker").classList.add("hidden");
}
function closeRoom() {
  document.getElementById("room").classList.add("hidden");
  room?.stop();
  clearInterval(roomTimer);
  roomBotId = null;
  document.getElementById("worker").classList.add("hidden");
  openWorkerId = null;
}
document.getElementById("room-close").onclick = closeRoom;
const chartView = new ChartView(document.getElementById("chart"));
document.getElementById("room-chart").onclick = () => {
  const bot = state?.bots.find((b) => b.id === roomBotId);
  if (bot) chartView.open(bot);
};
document.getElementById("chart-close").onclick = () => chartView.close();
document.getElementById("room-stats").onclick = () => {
  const w = document.getElementById("worker");
  w.classList.toggle("hidden");
  openWorkerId = roomBotId;
  renderWorker();
};

function openWorker(id) {
  openWorkerId = id;
  document.getElementById("worker").classList.remove("hidden");
  renderWorker();
}

function wardrobeHtml(bot) {
  const w = wardrobe(bot, "bot", { phase: state?.account?.phase });
  const worn = Object.values(w.wear).map((id) => ITEMS[id].label).join(" · ");
  const earn = w.earned.map((e) => `<div class="row"><span>${e.owned ? "✅" : "🔒"} ${ITEMS[e.item].label}</span><span>${e.need}</span></div>`).join("");
  return `<h4 style="margin:14px 0 6px">👕 Wardrobe · ${w.title}</h4>
    <div class="row"><span>Wearing</span><span style="text-align:right;max-width:65%">${worn}</span></div>${earn}`;
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
    <div class="row"><span>Strategy</span><span>${bot.strategy}${bot.info?.pointer_tfs ? ` · ${bot.info.pointer_tfs.map((t) => t + "m").join("/")} pointers` : ` · ${bot.timeframe}m candles`}</span></div>
    ${bot.info?.proc !== undefined ? `<div class="row"><span>Current PROC</span><span>${bot.info.proc ?? "none"}</span></div>
    <div class="row"><span>Untapped zones</span><span>${bot.info.untapped_zones}</span></div>
    <div class="row"><span>Confirmation</span><span>${bot.info.confirm ?? "off"}${bot.info.waiting ? ` · ${bot.info.waiting} waiting` : ""}</span></div>` : ""}
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
    ${wardrobeHtml(bot)}
    <button class="toggle ${enabled ? "off" : "on"}" data-bot="${bot.id}" data-action="${enabled ? "off" : "on"}">${enabled ? "SEND HOME" : "PUT ON SHIFT"}</button>`;
}

document.getElementById("acct-toggle").onclick = () => document.getElementById("account").classList.toggle("expanded");
document.getElementById("acct-sum").onclick = () => document.getElementById("account").classList.toggle("expanded");

document.addEventListener("click", async (e) => {
  const close = e.target.closest("[data-close]");
  if (close) {
    document.getElementById(close.dataset.close).classList.add("hidden");
    if (close.dataset.close === "worker") openWorkerId = null;
  }
  if (e.target.closest("[data-reset]")) await fetch("/api/account/reset", { method: "POST" });
  if (e.target.closest("[data-reports]")) openReports();
  const pay = e.target.closest("[data-payout]");
  if (pay) {
    const a = state.account;
    const amt = prompt(`Record a payout you requested at Lucid.\n\nAllowed: $${a.payout_limit.toLocaleString()} max (min $500).\nSuggested: $${(a.safe_payout || 0).toLocaleString()} (keeps $${a.keep_room.toLocaleString()} above the MLL, which locks at $50,100 after a payout).\n\nAmount:`, pay.dataset.payout);
    if (amt) {
      const r = await fetch("/api/account/payout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ amount: +amt }) });
      if (!r.ok) alert((await r.json()).detail);
    }
  }
  if (e.target.closest("[data-sync]")) {
    const a = state.account;
    const phase = prompt("Sync with your Lucid dashboard.\n\nPhase (evaluation or funded):", a.phase === "failed" ? "evaluation" : a.phase);
    if (phase) {
      const balance = prompt("Account balance ($):", Math.round(a.balance));
      const mll = balance && prompt("Max Loss Limit / MLL ($):", Math.round(a.mll));
      const extra = mll && phase.trim() === "funded"
        ? [prompt("Payouts taken so far:", a.payouts), prompt("Days this payout cycle with $150+ profit:", a.cycle_days)] : [0, 0];
      if (mll && extra[0] !== null && extra[1] !== null) {
        const r = await fetch("/api/account/sync", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phase: phase.trim(), balance: +balance, mll: +mll, payouts: +extra[0], cycle_days: +extra[1] }) });
        alert(r.ok ? "Synced. The bots now trade with your real account's numbers." : (await r.json()).detail);
      }
    }
  }
  if (e.target.closest("[data-desk]")) openDesk();
  if (e.target.closest("[data-accounts]")) openAccounts();
  if (e.target.closest("[data-scale]")) openScale();
  if (e.target.closest("[data-scale-set]")) {
    const p = prompt("What Lucid charges you for one LucidFlex 50K evaluation ($):", scaleData?.eval_price ?? "");
    if (p !== null) {
      const m = prompt("Most accounts you're allowed to run at once (your plan's limit):", scaleData?.limit ?? 5);
      const r = await fetch("/api/scale", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ eval_price: +p || 0, max_accounts: m === null ? null : +m }) });
      if (!r.ok) alert((await r.json()).detail); else openScale();
    }
  }
  if (e.target.closest("[data-signals]")) openSignals();
  const sd = e.target.closest("[data-sig-day]");
  if (sd) openSignals(sd.dataset.sigDay);
  const sv = e.target.closest("[data-sig-vote]");
  if (sv) {
    const current = sv.classList.contains("on");
    const note = !current && sv.dataset.sigVote === "no" ? prompt("Optional: what's different on your chart? (e.g. no PROC there, different timeframe, the zone isn't untapped)", "") ?? "" : "";
    await sigPost(sv.dataset.day, "vote", { id: sv.dataset.id, vote: current ? "" : sv.dataset.sigVote, note });
    openSignals(sv.dataset.day);
  }
  const sm = e.target.closest("[data-sig-missed]");
  if (sm) {
    const day = sm.dataset.sigMissed;
    const clock = prompt("Time of the PROC candle on your chart (ET, HH:MM, e.g. 09:42):", "");
    const tf = clock && prompt("Its timeframe in minutes (3, 4, 5 or 6):", "3");
    const side = tf && prompt("Direction (long or short):", "long");
    const note = side && (prompt("Optional note:", "") ?? "");
    if (side) { await sigPost(day, "missed", { clock, tf: +tf, side: side.trim().toLowerCase(), note }); openSignals(day); }
  }
  const ac = e.target.closest("[data-acct]");
  if (ac) await accountAction(ac.dataset.acct, ac.dataset.id);
  const dm = e.target.closest("[data-desk-meeting]");
  if (dm) {
    const r = await fetch("/api/desk/meeting", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: dm.dataset.deskMeeting }) });
    dm.textContent = r.ok ? "MEETING STARTED… (1-2 MIN)" : (await r.json()).detail;
  }
  const da = e.target.closest("[data-desk-act]");
  if (da) {
    await fetch("/api/desk/act", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ act: da.dataset.deskAct === "on" }) });
    openDesk(deskBot);
  }
  const rd = e.target.closest("[data-report-day]");
  if (rd) toggleReport(rd.dataset.reportDay);
  const pb = e.target.closest("[data-push]");
  if (pb) {
    const act = pb.dataset.push;
    if (act === "on") await turnOnAlerts();
    else if (act === "off") await turnOffAlerts();
    else await fetch("/api/push/test", { method: "POST" });
    if (state) renderAccount(state.account);
  }
  const ex = e.target.closest("[data-exec]");
  if (ex) {
    const act = ex.dataset.exec;
    let res;
    if (act === "arm") {
      const typed = prompt("Real orders will be placed on your Lucid account(s) through TradersPost whenever a bot trades.\n\nType ARM to confirm.");
      if (typed !== "ARM") return;
      res = await fetch("/api/execution", { method: "POST", body: JSON.stringify({ armed: true, confirm: "ARM" }) });
    } else if (act === "disarm") {
      res = await fetch("/api/execution", { method: "POST", body: JSON.stringify({ armed: false }) });
    } else if (act === "flatten") {
      if (!confirm("Exit every position on your Lucid accounts now and disarm?")) return;
      res = await fetch("/api/execution/flatten", { method: "POST" });
    }
    if (res && !res.ok) alert((await res.json()).detail ?? "failed");
  }
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
  const hit = ray.intersectObjects([...clickables, dome, skyStation], true).find((h) => h.object.userData.botId || h.object === dome || h.object.userData.station);
  if (!hit) return;
  if (hit.object.userData.station) { location.href = "station3d.html"; return; }
  if (hit.object === dome) document.getElementById("payroll").classList.toggle("hidden");
  else openRoom(hit.object.userData.botId);
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
    feedEvents(msg.events);
    feedSetups(msg.state);
    if (roomBotId && room) for (const ev of msg.events) if (ev.bot === roomBotId || ev.type === "account_halt") room.onEvent(ev);
    for (const ev of msg.events) {
      if (ev.type === "trade_close" || ev.type === "trade_trim") sendCoins(ev.bot, ev.pnl);
      if (ev.type === "tv_signal") tvPing(ev);
    }
  };
  ws.onclose = () => { conn.classList.remove("hidden"); setTimeout(connect, 1500); };
}
connect();

// ---------------------------------------------------------------- sky and market weather
// Day and night follow the ET clock (the market's sessions); the weather follows volatility
// (engine.weather(): storm on news or a 1.8x range spike, rain at 1.25x, fog when the tape is dead).
// The background skyline grows with the account's profit, each district with its bot's best day.
const SKY = [   // [ET hour, background, hemisphere sky, sun colour, light level]
  [0, "#0d0838", "#5b4bd6", "#7d6cff", 0.55],
  [4, "#0d0838", "#5b4bd6", "#7d6cff", 0.55],
  [6, "#4a1f6e", "#ff9ec7", "#ffb3a1", 0.8],
  [10, "#2a2a9c", "#a99bff", "#e2d8ff", 1.15],
  [15, "#2a2a9c", "#a99bff", "#e2d8ff", 1.15],
  [16.5, "#5a2a7a", "#ffb37a", "#ffcf8a", 1.0],
  [18.5, "#22127a", "#8f7bff", "#c9b8ff", 0.9],
  [21, "#0d0838", "#5b4bd6", "#7d6cff", 0.55],
  [24, "#0d0838", "#5b4bd6", "#7d6cff", 0.55],
];
const WEATHER = {
  clear: { icon: "☀️", text: "calm", fog: [90, 230], dim: 1 },
  fog: { icon: "🌫️", text: "quiet tape", fog: [30, 140], dim: 0.85 },
  rain: { icon: "🌧️", text: "volatile", fog: [70, 200], dim: 0.8 },
  storm: { icon: "⛈️", text: "storm", fog: [55, 170], dim: 0.6 },
};
const sky = { bg: new THREE.Color("#22127a"), top: new THREE.Color("#8f7bff"), sun: new THREE.Color("#c9b8ff"), level: 1, hour: 20, kind: "clear", news: false,
  skylineGrow: 1, skylineTo: 1, flash: 0, nextFlash: 0, rainOpacity: 0 };
const _a = new THREE.Color(), _b = new THREE.Color();

const RAIN_N = 1400;
const rainPos = new Float32Array(RAIN_N * 6);
for (let i = 0; i < RAIN_N; i++) {
  const x = (Math.random() - 0.5) * 220, y = Math.random() * 120, z = (Math.random() - 0.5) * 220;
  rainPos.set([x, y, z, x - 0.3, y - 2.2, z], i * 6);
}
const rainGeo = new THREE.BufferGeometry();
rainGeo.setAttribute("position", new THREE.BufferAttribute(rainPos, 3));
const rainMat = new THREE.LineBasicMaterial({ color: "#a9c4ff", transparent: true, opacity: 0, depthWrite: false });
const rain = new THREE.LineSegments(rainGeo, rainMat);
rain.frustumCulled = false;
rain.visible = false;
scene.add(rain);

const PREVIEW = new URLSearchParams(location.search);   // ?weather=storm&hour=7 previews a sky
function applyWeather(s) {
  const [hh, mm] = String(PREVIEW.get("hour") || s.clock || "20:00").split(":").map(Number);
  sky.hour = (hh || 0) + (mm || 0) / 60;
  const w = PREVIEW.get("weather") ? { kind: PREVIEW.get("weather") } : s.weather || {};
  sky.kind = WEATHER[w.kind] ? w.kind : "clear";
  sky.news = !!w.news;
  const profit = (s.account && s.account.profit) || 0;
  sky.skylineTo = Math.min(1.6, Math.max(0.85, 1 + (profit / 3000) * 0.2));
  const chip = document.getElementById("weather-chip");
  if (chip) {
    const W = WEATHER[sky.kind];
    chip.textContent = `${W.icon} ${innerWidth < 640 ? "" : W.text}`.trim();
    chip.title = `Market weather: ${sky.news ? "news hold" : W.text}${w.vol_ratio ? ` · range ${w.vol_ratio}x normal` : ""}`;
    chip.className = sky.kind;
  }
}

function updateSky(dt, t) {
  let i = 0;
  while (i < SKY.length - 2 && SKY[i + 1][0] <= sky.hour) i++;
  const [h0, bg0, top0, sun0, l0] = SKY[i], [h1, bg1, top1, sun1, l1] = SKY[i + 1];
  const f = h1 > h0 ? Math.min(1, Math.max(0, (sky.hour - h0) / (h1 - h0))) : 0;
  const W = WEATHER[sky.kind];
  const k = Math.min(1, dt * 0.6);   // ease toward the target so changes drift in, never snap
  sky.bg.lerp(_a.set(bg0).lerp(_b.set(bg1), f).multiplyScalar(W.dim), k);
  sky.top.lerp(_a.set(top0).lerp(_b.set(top1), f), k);
  sky.sun.lerp(_a.set(sun0).lerp(_b.set(sun1), f), k);
  sky.level += ((l0 + (l1 - l0) * f) * W.dim - sky.level) * k;
  scene.background.copy(sky.bg);
  scene.fog.color.copy(sky.bg);
  scene.fog.near += (W.fog[0] - scene.fog.near) * k;
  scene.fog.far += (W.fog[1] - scene.fog.far) * k;

  // storm: lightning every few seconds
  if (sky.kind === "storm" && t > sky.nextFlash) {
    sky.flash = 1;
    sky.nextFlash = t + 2.5 + Math.random() * 6;
  }
  sky.flash = Math.max(0, sky.flash - dt * 3.5);
  const strike = sky.flash > 0.6 || (sky.flash > 0.2 && sky.flash < 0.35) ? sky.flash : 0;   // double flicker
  hemi.color.copy(sky.top);
  hemi.intensity = 0.9 * sky.level + strike * 2.5;
  sun.color.copy(sky.sun);
  sun.intensity = 1.2 * sky.level;
  bloom.strength = 0.7 + strike * 0.9;
  if (strike) scene.background.lerp(_a.set("#c9d4ff"), strike * 0.35);

  // rain falls in rain and storms
  const wantRain = sky.kind === "storm" ? 0.8 : sky.kind === "rain" ? 0.5 : 0;
  sky.rainOpacity += (wantRain - sky.rainOpacity) * Math.min(1, dt * 1.5);
  rainMat.opacity = sky.rainOpacity;
  rain.visible = sky.rainOpacity > 0.02;
  if (rain.visible) {
    const fall = dt * (sky.kind === "storm" ? 90 : 60);
    for (let j = 0; j < RAIN_N; j++) {
      const o = j * 6;
      rainPos[o + 1] -= fall; rainPos[o + 4] -= fall;
      if (rainPos[o + 4] < 0) { rainPos[o + 1] += 120; rainPos[o + 4] += 120; }
    }
    rainGeo.attributes.position.needsUpdate = true;
    rain.position.set(camera.position.x * 0.5, 0, camera.position.z * 0.5);
  }

  sky.skylineGrow += (sky.skylineTo - sky.skylineGrow) * Math.min(1, dt * 0.5);
  skyline.scale.y = sky.skylineGrow;
}

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
    b.grow += (b.growTo - b.grow) * Math.min(1, dt * 0.8);
    b.towersG.scale.y = b.grow;
    b.towersG.position.y = 1 - b.grow;   // towers start at y=1: keep their base on the platform
    const top = b.hero * b.grow;
    b.beam.position.y = top + 70;
    b.label.position.y = b.labelY + top - b.hero;
    b.halo.position.y = top + 6 + Math.sin(t * 1.5 + b.pos.x) * 0.4;
    b.haloMat.opacity = b.status === "disabled" ? 0.15 : active ? 1 : 0.6;
    // the bot out front: bounces while it's in a trade, slumps when sent home
    b.mascot.position.y = 1 + (active ? Math.abs(Math.sin(t * 5 + b.pos.x)) * 0.5 : Math.sin(t * 1.4 + b.pos.z) * 0.06);
    b.mascot.rotation.z = b.status === "stopped" || b.status === "disabled" ? 0.25 : 0;
    animateApparel(b.apparel, t);
    if (b.tvFlash > 0) {
      b.tvFlash = Math.max(0, b.tvFlash - dt * 0.8);
      b.halo.scale.setScalar(1 + b.tvFlash * 0.8);
    }
  }

  updateSky(dt, t);
  updateFlights(dt, t);

  vaultPulse = Math.max(0, vaultPulse - dt * 1.5);
  domeMat.emissiveIntensity = 0.9 + vaultPulse * 2.5;
  dome.scale.setScalar(1 + vaultPulse * 0.04);
  updateCoins(dt);

  if (!roomBotId) composer.render();   // the city pauses while you're inside a room
  labels.render(scene, camera);
  requestAnimationFrame(frame);
}
frame();

function fitCity() {
  const w = app.clientWidth || innerWidth, h = app.clientHeight || innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  composer.setSize(w, h);
  labels.setSize(w, h);
}
addEventListener("resize", fitCity);
new ResizeObserver(fitCity).observe(app);   // iPhone home-screen apps settle their size after load
