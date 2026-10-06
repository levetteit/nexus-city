// StarNet Orbital Station: the 3D view of ULTRON's station. Every module, agent, pet and planet here is live
// data from /api/station (the same as the 2D board); nothing on screen is decoration-only state.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { wardrobe, dress, finishMaterial, animateApparel, ITEMS } from "./skins.js";
import { Flight, newFlights } from "./shuttle.js";

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v) => (v == null ? "—" : (v < 0 ? "−$" : "$") + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 }));
const ago = (iso) => {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
};

// ---------------------------------------------------------------- renderer, camera, light
const app = $("#app");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.95;
app.appendChild(renderer.domElement);
const labels = new CSS2DRenderer();
labels.setSize(innerWidth, innerHeight);
labels.domElement.className = "label-layer";
Object.assign(labels.domElement.style, { position: "fixed", inset: "0" });
app.appendChild(labels.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color("#03050d");
scene.fog = new THREE.FogExp2("#03050d", 0.0042);
const PORTRAIT = innerWidth < innerHeight;
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.1, 1200);
const HOME = PORTRAIT ? new THREE.Vector3(0, 235, 160) : new THREE.Vector3(0, 70, 95);
camera.position.copy(HOME);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.25;
controls.maxPolarAngle = Math.PI * 0.49;
controls.minDistance = 14;
controls.maxDistance = 320;
controls.target.set(0, 0, 0);
controls.addEventListener("start", () => { controls.autoRotate = false; flight = null; });

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
composer.addPass(new UnrealBloomPass(new THREE.Vector2(innerWidth / 2, innerHeight / 2), 0.85, 0.5, 0.6));
composer.addPass(new OutputPass());
scene.add(new THREE.HemisphereLight("#7fa8ff", "#0a0a20", 0.9));
const key = new THREE.DirectionalLight("#dbe6ff", 1.4);
key.position.set(40, 80, 30);
scene.add(key);
const coreLight = new THREE.PointLight("#ff3b5c", 60, 60, 2);
coreLight.position.set(0, 6, 0);
scene.add(coreLight);

// ---------------------------------------------------------------- space: stars, planet, rings
{
  const n = 2600, pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const r = 420 + Math.random() * 300, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    pos.set([r * Math.sin(ph) * Math.cos(th), r * Math.cos(ph), r * Math.sin(ph) * Math.sin(th)], i * 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: "#cfe0ff", size: 1.4, sizeAttenuation: true, fog: false })));
  const planet = new THREE.Mesh(new THREE.SphereGeometry(260, 64, 48), new THREE.MeshStandardMaterial({
    color: "#123a7a", emissive: "#0a2a66", emissiveIntensity: 0.5, roughness: 0.9 }));
  planet.position.set(-120, -330, -260);
  scene.add(planet);
  const atmo = new THREE.Mesh(new THREE.SphereGeometry(268, 64, 48), new THREE.MeshBasicMaterial({ color: "#3d8bff", transparent: true, opacity: 0.12, side: THREE.BackSide, fog: false }));
  atmo.position.copy(planet.position);
  scene.add(atmo);
}

// ---------------------------------------------------------------- materials
const hull = new THREE.MeshStandardMaterial({ color: "#26324f", metalness: 0.7, roughness: 0.35 });
const hullDark = new THREE.MeshStandardMaterial({ color: "#151d33", metalness: 0.6, roughness: 0.5 });
const glass = new THREE.MeshStandardMaterial({ color: "#7fd8ff", transparent: true, opacity: 0.18, metalness: 0.2, roughness: 0.1 });
const glow = (c, i = 2) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: i });
const clickables = [];   // meshes with userData.pick = {type, id}

function label(html, cls, y) {
  const el = document.createElement("div");
  el.className = cls;
  el.innerHTML = html;
  const o = new CSS2DObject(el);
  o.position.set(0, y, 0);
  return o;
}

// ---------------------------------------------------------------- ULTRON's command core (center)
const core = new THREE.Group();
scene.add(core);
const hub = new THREE.Mesh(new THREE.CylinderGeometry(11, 12, 2, 48), hull);
hub.position.y = -1;
core.add(hub);
const hubRim = new THREE.Mesh(new THREE.TorusGeometry(11.6, 0.18, 8, 96), glow("#ff3b5c", 2.5));
hubRim.rotation.x = Math.PI / 2;
core.add(hubRim);
const eye = new THREE.Mesh(new THREE.SphereGeometry(2.2, 32, 24), glow("#ff2a4d", 4));
eye.position.y = 7;
core.add(eye);
const coreRings = [];
for (const [r, c, tilt] of [[4.2, "#ff3b5c", 0.3], [5.6, "#5ee7ff", -0.5], [7, "#ff3b5c", 1.1]]) {
  const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.07, 8, 120), glow(c, 2.2));
  ring.position.y = 7;
  ring.rotation.set(Math.PI / 2 + tilt, tilt, 0);
  core.add(ring);
  coreRings.push(ring);
}
const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.9, 40, 16, 1, true), new THREE.MeshBasicMaterial({ color: "#ff3b5c", transparent: true, opacity: 0.25 }));
beam.position.y = 26;
core.add(beam);
const corePick = new THREE.Mesh(new THREE.SphereGeometry(8, 16, 12), new THREE.MeshBasicMaterial({ visible: false }));
corePick.position.y = 6;
corePick.userData.pick = { type: "core" };
core.add(corePick);
clickables.push(corePick);
const coreLabel = label(`ULTRON COMMAND CORE<small id="core-sub">online</small>`, "mod-label", 13);
core.add(coreLabel);

// ---------------------------------------------------------------- departments: the ring of modules
const MODULES = [
  { id: "research", name: "Research Lab", color: "#5ee7ff", depts: ["research"] },
  { id: "revenue", name: "Revenue Ops", color: "#3dffa2", depts: ["revenue"] },
  { id: "marketing", name: "Marketing & Media", color: "#ff7ad9", depts: ["marketing"] },
  { id: "creative", name: "Creative Lab", color: "#c38bff", depts: ["creative"] },
  { id: "marketplace", name: "Marketplace Deck", color: "#ffa94d", depts: ["marketplace"] },
  { id: "finance", name: "Finance Observatory", color: "#ffd84d", depts: ["finance"] },
  { id: "legal", name: "Legal & QA", color: "#9fb4ff", depts: ["legal"] },
  { id: "warroom", name: "War Room", color: "#ff4d4d", depts: ["warroom"] },
  { id: "engineering", name: "Engineering Bay", color: "#4dd2ff", depts: ["engineering"] },
  { id: "quarters", name: "Agent Quarters", color: "#8a97bd", depts: [] },
  { id: "lounge", name: "Crew Lounge", color: "#b48bff", depts: [] },
  { id: "approvals", name: "Approval Chamber", color: "#ffc94d", depts: [] },
  { id: "citydock", name: "City Dock", color: "#ff5ad1", depts: ["city"] },
];
const RING = 40;
const mods = new Map();
MODULES.forEach((m, i) => {
  const a = (i / MODULES.length) * Math.PI * 2;
  const pos = new THREE.Vector3(Math.cos(a) * RING, 0, Math.sin(a) * RING);
  const g = new THREE.Group();
  g.position.copy(pos);
  scene.add(g);
  const deck = new THREE.Mesh(new THREE.CylinderGeometry(7.5, 8, 1.2, 6), hull);
  deck.position.y = -0.6;
  deck.userData.pick = { type: "module", id: m.id };
  clickables.push(deck);
  g.add(deck);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(7.8, 0.12, 6, 6), glow(m.color, 1.6));
  rim.rotation.x = Math.PI / 2;
  rim.rotation.z = Math.PI / 6;
  g.add(rim);
  const dome = new THREE.Mesh(new THREE.SphereGeometry(7.2, 32, 16, 0, Math.PI * 2, 0, Math.PI / 2), glass);
  g.add(dome);
  // corridor to the core with traveling light pulses (faster when the department is busy)
  const len = RING - 19.5, mid = pos.clone().setLength(11.5 + len / 2);
  const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.55, len, 10), hullDark);
  tube.position.set(mid.x, -0.4, mid.z);
  tube.rotation.z = Math.PI / 2;
  tube.rotation.y = -a;
  scene.add(tube);
  const pulses = [];
  for (let k = 0; k < 3; k++) {
    const p = new THREE.Mesh(new THREE.SphereGeometry(0.28, 8, 6), glow(m.color, 3));
    p.userData.t = k / 3;
    scene.add(p);
    pulses.push(p);
  }
  const lab = label(`${esc(m.name)}<small>—</small>`, "mod-label", 10.5);
  g.add(lab);
  const props = new THREE.Group();
  g.add(props);
  mods.set(m.id, { ...m, g, pos, angle: a, pulses, lab, props, busy: 0, anim: [] });
  buildProps(mods.get(m.id));
});

function buildProps(mod) {
  const P = mod.props, c = mod.color, add = (mesh, x, y, z) => { mesh.position.set(x, y, z); P.add(mesh); return mesh; };
  switch (mod.id) {
    case "research": {
      const globe = add(new THREE.Mesh(new THREE.IcosahedronGeometry(2.2, 1), new THREE.MeshBasicMaterial({ color: c, wireframe: true })), 0, 4, 0);
      mod.anim.push((t) => { globe.rotation.y = t * 0.4; globe.rotation.x = t * 0.15; });
      add(new THREE.Mesh(new THREE.CylinderGeometry(1.4, 1.8, 1.2, 16), hullDark), 0, 0.6, 0);
      mod.cards = new THREE.Group();
      P.add(mod.cards);
      break;
    }
    case "revenue":
      mod.bars = new THREE.Group();
      add(new THREE.Mesh(new THREE.BoxGeometry(7, 0.3, 3), hullDark), 0, 0.15, 0);
      P.add(mod.bars);
      break;
    case "marketing": {
      const mast = add(new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.3, 5, 8), hull), 0, 2.5, 0);
      const dish = add(new THREE.Mesh(new THREE.SphereGeometry(2.2, 24, 12, 0, Math.PI * 2, 0, Math.PI / 3), new THREE.MeshStandardMaterial({ color: "#c9d4ff", metalness: 0.6, roughness: 0.3, side: THREE.DoubleSide })), 0, 5.2, 0);
      dish.rotation.x = Math.PI;
      add(new THREE.Mesh(new THREE.SphereGeometry(0.35, 12, 8), glow(c, 4)), 0, 4.4, 0);
      mod.anim.push((t) => { dish.rotation.z = Math.sin(t * 0.5) * 0.5; });
      mod.ray = add(new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 60, 8, 1, true), new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0 })), 0, 35, 0);
      void mast;
      break;
    }
    case "creative": {
      const prism = add(new THREE.Mesh(new THREE.OctahedronGeometry(1.8), new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.8, metalness: 0.3, roughness: 0.1, transparent: true, opacity: 0.85 })), 0, 4, 0);
      mod.anim.push((t) => { prism.rotation.y = t * 0.8; prism.position.y = 4 + Math.sin(t) * 0.3; });
      add(new THREE.Mesh(new THREE.BoxGeometry(2.2, 2.8, 0.15), glow("#ffffff", 0.4)), -3.5, 1.6, 1.5).rotation.y = 0.6;
      break;
    }
    case "marketplace":
      for (const [x, z, h] of [[-2, -1, 0], [-2, -1, 1.2], [0, 1, 0], [2, -1.5, 0], [2, -1.5, 1.2], [2, -1.5, 2.4]])
        add(new THREE.Mesh(new THREE.BoxGeometry(1.2, 1.2, 1.2), new THREE.MeshStandardMaterial({ color: "#a86a2c", roughness: 0.8 })), x, 0.6 + h, z);
      add(new THREE.Mesh(new THREE.BoxGeometry(3, 0.15, 1.6), glow(c, 0.8)), 0, 2.8, 1);
      break;
    case "finance": {
      add(new THREE.Mesh(new THREE.SphereGeometry(2.6, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), hull), 0, 0, -1);
      const scope = add(new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.6, 4.5, 12), new THREE.MeshStandardMaterial({ color: "#dfe6ff", metalness: 0.8, roughness: 0.2 })), 0, 3, -1);
      scope.rotation.x = -0.7;
      mod.coins = new THREE.Group();
      mod.coins.position.set(3, 0, 2);
      P.add(mod.coins);
      break;
    }
    case "legal": {
      add(new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.5, 4, 12), hull), 0, 2, 0);
      const beamL = add(new THREE.Mesh(new THREE.BoxGeometry(4.4, 0.15, 0.2), glow(c, 1)), 0, 4, 0);
      const l = add(new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 0.1, 16), glow(c, 1.2)), -2, 3, 0);
      const r = add(new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 0.1, 16), glow(c, 1.2)), 2, 3, 0);
      mod.anim.push((t) => { const k = Math.sin(t * 0.7) * 0.25; beamL.rotation.z = k * 0.3; l.position.y = 3 + k; r.position.y = 3 - k; });
      break;
    }
    case "warroom": {
      add(new THREE.Mesh(new THREE.CylinderGeometry(3, 3, 0.25, 32), hullDark), 0, 1.4, 0);
      const map = add(new THREE.Mesh(new THREE.CircleGeometry(2.7, 32), new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.35 })), 0, 1.56, 0);
      map.rotation.x = -Math.PI / 2;
      mod.map = map;
      mod.anim.push((t) => { map.material.opacity = 0.25 + (mod.hot ? 0.35 : 0.1) * (1 + Math.sin(t * 3)) / 2; });
      break;
    }
    case "engineering": {
      const gear = add(new THREE.Mesh(new THREE.TorusGeometry(1.8, 0.45, 8, 12), new THREE.MeshStandardMaterial({ color: "#aab6d6", metalness: 0.9, roughness: 0.3 })), -1, 3, 0);
      const gear2 = add(new THREE.Mesh(new THREE.TorusGeometry(1.1, 0.35, 8, 9), glow(c, 1)), 2, 2.2, 0.5);
      mod.anim.push((t) => { gear.rotation.z = t * 0.6; gear2.rotation.z = -t * 1.0; });
      break;
    }
    case "quarters":
      for (let k = 0; k < 5; k++) {
        const a = (k / 5) * Math.PI * 2;
        const pod = add(new THREE.Mesh(new THREE.CapsuleGeometry(0.9, 1.6, 6, 12), glass), Math.cos(a) * 4.4, 1.6, Math.sin(a) * 4.4);
        pod.rotation.z = Math.PI / 2;
        pod.rotation.y = -a;
      }
      break;
    case "lounge": {
      add(new THREE.Mesh(new THREE.BoxGeometry(5, 0.8, 1.4), new THREE.MeshStandardMaterial({ color: "#5b3fa8", roughness: 0.9 })), 0, 0.4, -3);
      add(new THREE.Mesh(new THREE.BoxGeometry(5, 1.4, 0.4), new THREE.MeshStandardMaterial({ color: "#4a3290", roughness: 0.9 })), 0, 1, -3.8);
      const cab = add(new THREE.Mesh(new THREE.BoxGeometry(1.4, 3, 1.2), hullDark), 4, 1.5, 1);
      const scr = add(new THREE.Mesh(new THREE.PlaneGeometry(1.1, 0.9), glow("#3dffa2", 1.5)), 4, 2.2, 0.39);
      cab.rotation.y = scr.rotation.y = -0.4;
      mod.anim.push((t) => { scr.material.emissive.setHSL((t * 0.15) % 1, 0.9, 0.5); });
      const tank = add(new THREE.Mesh(new THREE.BoxGeometry(2.4, 1.6, 1), glass), -4, 1.2, 1.5);
      const fish = add(new THREE.Mesh(new THREE.ConeGeometry(0.15, 0.4, 6), glow("#ffa94d", 2)), -4, 1.2, 1.5);
      fish.rotation.z = Math.PI / 2;
      mod.anim.push((t) => { fish.position.x = -4 + Math.sin(t * 0.8) * 0.8; fish.rotation.y = Math.cos(t * 0.8) > 0 ? 0 : Math.PI; });
      void tank;
      for (const [x, z] of [[-5.5, -3], [5.5, -3]]) add(new THREE.Mesh(new THREE.ConeGeometry(0.6, 1.8, 8), new THREE.MeshStandardMaterial({ color: "#2fbf71" })), x, 0.9, z);
      break;
    }
    case "approvals": {
      const gate = add(new THREE.Mesh(new THREE.TorusGeometry(3, 0.3, 12, 48), glow(c, 1)), 0, 3.4, 0);
      mod.gate = gate;
      mod.anim.push((t) => { gate.rotation.y = t * 0.3; gate.material.emissiveIntensity = mod.waiting ? 2 + Math.sin(t * 4) * 1.5 : 0.6; });
      break;
    }
    case "citydock": {
      const portal = add(new THREE.Mesh(new THREE.TorusGeometry(3.2, 0.35, 12, 48), glow(c, 2)), 0, 3.6, 0);
      const disc = add(new THREE.Mesh(new THREE.CircleGeometry(2.9, 32), new THREE.MeshBasicMaterial({ color: "#5b2bff", transparent: true, opacity: 0.4, side: THREE.DoubleSide })), 0, 3.6, 0);
      mod.anim.push((t) => { portal.rotation.z = t * 0.4; disc.material.opacity = 0.3 + Math.sin(t * 2) * 0.1; });
      portal.rotation.y = disc.rotation.y = -mod.angle + Math.PI / 2;
      break;
    }
  }
}

// ---------------------------------------------------------------- ventures as planets orbiting the core
const planets = new Map();
const STAGE_COLOR = { operate: "#3dffa2", scale: "#3dffa2", measure: "#3dffa2", optimize: "#3dffa2", launch: "#ffc94d", build: "#5ee7ff",
  approved: "#5ee7ff", validate: "#5ee7ff", research: "#8a97bd", paused: "#ff3b5c", killed: "#444a5e" };
function syncPlanets(ventures) {
  ventures.forEach((v, i) => {
    let p = planets.get(v.id);
    if (!p) {
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), glow(STAGE_COLOR[v.stage] || "#8a97bd", 1.2));
      mesh.userData.pick = { type: "venture", id: v.id };
      clickables.push(mesh);
      scene.add(mesh);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(1.6, 0.05, 6, 48), new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.35 }));
      mesh.add(ring);
      ring.rotation.x = Math.PI / 2.4;
      const lab = label(esc(v.name), "planet-label", 2.4);
      mesh.add(lab);
      p = { mesh, lab, r: 15 + (i % 4) * 1.8, h: 9 + (i % 3) * 2.2, phase: i * 2.1, speed: 0.08 + (i % 3) * 0.03 };
      planets.set(v.id, p);
    }
    const c = STAGE_COLOR[v.stage] || "#8a97bd";
    p.mesh.material.color.set(c);
    p.mesh.material.emissive.set(c);
    p.mesh.scale.setScalar(0.7 + (v.health || 0) / 100);
  });
}

// ---------------------------------------------------------------- agents: robots that go where their work is
const STATUS = { WORKING: "#3dffa2", THINKING: "#5ee7ff", WAITING: "#ffc94d", COMPLETED: "#9d8bff", "ON BREAK": "#b48bff", BENCHED: "#6b7591" };
const agents = new Map();

function makeRobot(a) {
  const big = a.id === "A-001", bot = a.kind === "bot";
  const g = new THREE.Group();
  const look = lookFor(a);
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.55, 0.9, 6, 12), finishMaterial(look.finish));
  body.position.y = 1.1;
  g.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.62, 20, 14), new THREE.MeshStandardMaterial({ color: "#d9e2ff", metalness: 0.4, roughness: 0.3 }));
  head.position.y = 2.25;
  g.add(head);
  const visor = new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.28, 0.2), glow(big ? "#ff2a4d" : STATUS[a.status] || "#5ee7ff", 3));
  visor.position.set(0, 2.3, 0.5);
  g.add(visor);
  const jet = new THREE.Mesh(new THREE.ConeGeometry(0.3, 0.6, 10), glow("#5ee7ff", 3));
  jet.rotation.x = Math.PI;
  jet.position.y = 0.2;
  g.add(jet);
  const halo = new THREE.Mesh(new THREE.TorusGeometry(0.75, 0.05, 6, 30), glow("#5ee7ff", 3));
  halo.rotation.x = Math.PI / 2;
  halo.position.y = 3.2;
  halo.visible = false;
  g.add(halo);
  if (big) g.scale.setScalar(2.2);
  const pick = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 3.2, 8), new THREE.MeshBasicMaterial({ visible: false }));
  pick.position.y = 1.6;
  pick.userData.pick = { type: "agent", id: a.id };
  g.add(pick);
  clickables.push(pick);
  const el = document.createElement("div");
  el.className = "ag-label";
  const lab = new CSS2DObject(el);
  lab.position.y = big ? 1.8 : 3.6;
  g.add(lab);
  scene.add(g);
  const r = { g, body, visor, jet, halo, el, target: new THREE.Vector3(), slot: 0, pet: null, data: a, apparel: [], wearKey: "" };
  wear(r, a);
  return r;
}

// skins.js: the trading bots on the dock wear their city looks; the crew wear theirs plus what they've earned
function lookFor(a) {
  return a.kind === "bot" ? wardrobe({ id: a.id.replace(/^BOT-/, "") }, "bot") : wardrobe(a, "agent");
}
function wear(r, a) {
  const look = lookFor(a);
  const key = JSON.stringify(look.wear) + look.finish;
  if (key === r.wearKey) return;
  for (const it of r.apparel) it.parent?.remove(it);
  r.body.material = finishMaterial(look.finish);
  r.apparel = dress(look.wear, {
    head: { parent: r.g, pos: [0, 2.82, 0], w: 1.2 },
    face: { parent: r.g, pos: [0, 2.32, 0.62], w: 1.1 },
    neck: { parent: r.g, pos: [0, 1.78, 0], w: 1.1 },
    chest: { parent: r.g, pos: [0.25, 1.35, 0.56], w: 1.0 },
    back: { parent: r.g, pos: [0, 1.85, -0.56], w: 1.0, rot: [0, Math.PI, 0] },
  }, a.id === "A-001" ? "#ff2a4d" : "#5ee7ff");
  r.wearKey = key;
}

function moduleFor(a) {
  if (a.id === "A-001") return null;   // ULTRON stays in the core
  if (a.status === "ON BREAK") return "lounge";
  if (a.status === "BENCHED") return "quarters";
  const m = MODULES.find((x) => x.depts.includes(a.department));
  return m ? m.id : "revenue";
}

function syncAgents(list) {
  const bySlot = new Map();
  for (const a of list) {
    let r = agents.get(a.id);
    if (!r) {
      r = makeRobot(a);
      agents.set(a.id, r);
      const start = moduleFor(a);
      if (start) r.g.position.copy(mods.get(start).pos);
    }
    r.data = a;
    const m = moduleFor(a);
    if (!m) {
      r.target.set(0, 0.8, 4.2);
    } else {
      const n = bySlot.get(m) || 0;
      bySlot.set(m, n + 1);
      const base = mods.get(m).pos;
      const ang = n * 2.4 + 0.4, rad = 2.6 + 1.25 * Math.sqrt(n);   // sunflower spread: a crowded room stays readable
      r.target.set(base.x + Math.cos(ang) * rad, 0, base.z + Math.sin(ang) * rad);
    }
    r.visor.material.color.set(a.id === "A-001" ? "#ff2a4d" : STATUS[a.status] || "#5ee7ff");
    r.visor.material.emissive.copy(r.visor.material.color);
    r.halo.visible = a.status === "THINKING";
    const working = ["WORKING", "THINKING"].includes(a.status) && (a.current_task || a.last_output);
    const badge = (a.achievements || []).length ? ` <span class="badge">★${(a.achievements || []).length}</span>` : "";
    r.el.classList.toggle("idle", !working && a.id !== "A-001");
    r.el.innerHTML = (working ? `<span class="task">${esc(String(a.current_task || "").slice(0, 60))}</span><br>` : "")
      + `${esc(a.name)}${badge}`;
    syncPet(r, a);
    wear(r, a);
  }
  // modules' agent counts
  for (const mod of mods.values()) mod.busy = 0;
  for (const a of list) {
    const m = moduleFor(a);
    if (m && ["WORKING", "THINKING"].includes(a.status)) mods.get(m).busy++;
  }
}

// ---------------------------------------------------------------- pets: earned with milestones, they follow their agent
function makePet(kind) {
  const g = new THREE.Group();
  if (kind === "robo-cat") {
    const b = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.45, 0.45), new THREE.MeshStandardMaterial({ color: "#cfd8f0", metalness: 0.5, roughness: 0.3 }));
    b.position.y = 0.35; g.add(b);
    const h = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.38, 0.38), b.material); h.position.set(0.42, 0.62, 0); g.add(h);
    for (const z of [-0.12, 0.12]) { const e = new THREE.Mesh(new THREE.ConeGeometry(0.08, 0.18, 4), b.material); e.position.set(0.42, 0.88, z); g.add(e);
      const eye = new THREE.Mesh(new THREE.SphereGeometry(0.04, 6, 4), glow("#3dffa2", 4)); eye.position.set(0.62, 0.66, z * 0.8); g.add(eye); }
  } else if (kind === "drone") {
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.3, 12, 8), new THREE.MeshStandardMaterial({ color: "#ffd84d", metalness: 0.6, roughness: 0.3 }));
    g.add(b);
    const rot = new THREE.Mesh(new THREE.TorusGeometry(0.45, 0.04, 6, 24), glow("#5ee7ff", 3)); rot.rotation.x = Math.PI / 2; rot.position.y = 0.2; g.add(rot);
    g.userData.spin = rot; g.userData.fly = 2.4;
  } else if (kind === "star-jelly") {
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.4, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2), new THREE.MeshStandardMaterial({ color: "#ff7ad9", emissive: "#ff7ad9", emissiveIntensity: 1.5, transparent: true, opacity: 0.7 }));
    g.add(b);
    for (let k = 0; k < 5; k++) { const t = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.6, 4), b.material); const a = k / 5 * Math.PI * 2; t.position.set(Math.cos(a) * 0.22, -0.3, Math.sin(a) * 0.22); g.add(t); }
    g.userData.fly = 3;
  } else {   // comet-fox
    const b = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.9, 10), glow("#ff9a3d", 1.2)); b.rotation.z = -Math.PI / 2; b.position.y = 0.45; g.add(b);
    const tail = new THREE.Mesh(new THREE.ConeGeometry(0.18, 1.1, 8), glow("#ffe14d", 3)); tail.rotation.z = Math.PI / 2; tail.position.set(-0.9, 0.5, 0); g.add(tail);
  }
  scene.add(g);
  return g;
}
function syncPet(r, a) {
  if (!a.pet || a.kind === "bot") return;
  if (!r.pet || r.pet.userData.kind !== a.pet.kind) {
    if (r.pet) scene.remove(r.pet);
    r.pet = makePet(a.pet.kind);
    r.pet.userData.kind = a.pet.kind;
    r.pet.position.copy(r.g.position);
  }
}

// ---------------------------------------------------------------- effects: real events become motion
const fx = [];
function burst(at, color, n = 14) {
  for (let i = 0; i < n; i++) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.18, 6, 4), glow(color, 4));
    m.position.copy(at);
    m.userData.v = new THREE.Vector3((Math.random() - 0.5) * 8, 4 + Math.random() * 6, (Math.random() - 0.5) * 8);
    m.userData.life = 1.4;
    scene.add(m);
    fx.push(m);
  }
}
function courier(from, to, color) {   // a glowing packet flying between modules (money, leads)
  const m = new THREE.Mesh(new THREE.SphereGeometry(0.5, 12, 8), glow(color, 4));
  m.position.copy(from).setY(3);
  m.userData.from = from.clone().setY(3);
  m.userData.to = to.clone().setY(3);
  m.userData.t = 0;
  scene.add(m);
  fx.push(m);
}
// payout shuttles (shuttle.js): a Lucid payout flies in from the City Dock, a sale from the shop that made it
const flightsSeen = new Set();
const flying = [];
function launchFlights(flights) {
  for (const f of newFlights(flightsSeen, flights)) {
    const src = f.kind === "payout" ? "citydock" : /etsy|printify/i.test(f.note || "") ? "marketplace" : "revenue";
    const from = mods.get(src).pos.clone().setY(4), to = mods.get("finance").pos.clone().setY(4);
    flying.push(new Flight(scene, f.kind, f.amount, from, to, { scale: 1.1, height: 14, seconds: 6,
      onArrive: () => burst(to.clone().setY(3), f.kind === "payout" ? "#3dffa2" : "#ffd84d", 36) }));
  }
}
function toast(text, color = "#5ee7ff") {
  const t = document.createElement("div");
  t.className = "toast";
  t.style.borderLeftColor = color;
  t.textContent = text;
  $("#toasts").prepend(t);
  setTimeout(() => t.remove(), 6000);
  while ($("#toasts").children.length > 4) $("#toasts").lastChild.remove();
}
let lastEventAt = null;
function playEvents(events) {
  const fresh = lastEventAt ? events.filter((e) => e.at > lastEventAt).reverse() : [];
  if (events.length) lastEventAt = events[0].at;
  for (const e of fresh.slice(-6)) {
    const k = e.kind;
    if (k === "action.sent") {
      const mk = mods.get("marketing");
      mk.ray.material.opacity = 0.9;
      toast(`📡 ${e.summary}`, "#ff7ad9");
    } else if (k.startsWith("money.income") || k === "lead.won" || k.startsWith("money.lucid")) {
      if (k === "lead.won") courier(mods.get("revenue").pos, mods.get("finance").pos, "#ffd84d");   // money in flies as a shuttle
      burst(mods.get("finance").pos.clone().setY(3), "#ffd84d", 24);
      toast(`💵 ${e.summary}`, "#ffd84d");
    } else if (k === "shop.listed") {
      burst(mods.get("marketplace").pos.clone().setY(4), "#ffa94d", 22);
      toast(`🛍️ ${e.summary}`, "#ffa94d");
    } else if (k === "shop.order") {
      courier(mods.get("marketplace").pos, mods.get("finance").pos, "#ffd84d");
      burst(mods.get("marketplace").pos.clone().setY(4), "#ffd84d", 30);
      toast(`📦 ${e.summary}`, "#ffd84d");
    } else if (k === "venture.auto_launched") {
      burst(mods.get("revenue").pos.clone().setY(5), "#3dffa2", 40);
      toast(`🚀 ${e.summary}`, "#3dffa2");
    } else if (k === "digital.published") {
      courier(mods.get("creative").pos, mods.get("revenue").pos, "#c58bff");
      toast(`🛒 ${e.summary}`, "#c58bff");
    } else if (k === "digital.made") {
      burst(mods.get("creative").pos.clone().setY(5), "#c58bff", 14);
    } else if (k === "shop.design") {
      burst(mods.get("creative").pos.clone().setY(5), "#c58bff", 12);
    } else if (k === "lead.created") {
      courier(mods.get("marketing").pos, mods.get("revenue").pos, "#3dffa2");
      toast(`📨 ${e.summary}`, "#3dffa2");
    } else if (k === "agent.milestone") {
      const r = agents.get(e.ref);
      burst((r ? r.g.position : new THREE.Vector3()).clone().setY(3), "#ffc94d", 30);
      toast(`🏅 ${e.summary}`, "#ffc94d");
    } else if (k === "opportunity.created") {
      burst(mods.get("research").pos.clone().setY(5), "#5ee7ff", 10);
      toast(`🔭 ${e.summary}`, "#5ee7ff");
    } else if (k === "approval.requested") {
      burst(mods.get("approvals").pos.clone().setY(4), "#ffc94d", 16);
      toast(`⏳ Waiting for you: ${e.summary}`, "#ffc94d");
    } else if (k === "warroom.session") {
      burst(mods.get("warroom").pos.clone().setY(3), "#ff4d4d", 20);
      toast(`⚔️ War Room: ${e.summary}`, "#ff4d4d");
    } else if (e.severity === "WARNING" || e.severity === "CRITICAL") {
      toast(`⚠️ ${e.summary}`, "#ff3b5c");
    }
  }
}

// ---------------------------------------------------------------- live data
let S = null;
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
}
async function load() {
  try { S = await api("/api/station"); } catch (e) { $("#ultron-txt").textContent = `Station offline: ${e.message}`; return; }
  $("#loading").classList.add("hidden");
  syncPlanets(S.ventures);
  syncAgents(S.agents);
  playEvents(S.events);
  launchFlights(S.flights);
  // module labels
  const count = (id) => S.agents.filter((a) => moduleFor(a) === id).length;
  const sub = {
    research: `${S.opportunities.length} opportunities`,
    revenue: `${S.ventures.filter((v) => !["paused", "killed"].includes(v.stage)).length} live ventures`,
    marketing: `${S.outbox.sent.length} sent · ${S.outbox.manual.length} to post`,
    finance: `pool ${money(S.treasury.pool)}`,
    legal: `${S.outbox.in_qa} in QA`,
    warroom: S.warroom ? `met ${ago(S.warroom.at)}` : "not met yet",
    approvals: S.approvals.length + S.owner_tasks.length ? `<span class="warn">${S.approvals.length + S.owner_tasks.length} waiting for you</span>` : "all clear",
    lounge: `${count("lounge")} on break`,
    citydock: "trading bots",
    marketplace: S.shop ? `Etsy · ${S.shop.live.length} live · ${S.shop.orders_30d} orders (30d)` : "",
  };
  for (const mod of mods.values()) {
    mod.lab.element.innerHTML = `${esc(mod.name)}<small>${sub[mod.id] || `${count(mod.id)} crew`}${mod.busy ? ` · ${mod.busy} working` : ""}</small>`;
  }
  mods.get("approvals").waiting = S.approvals.length + S.owner_tasks.length;
  mods.get("warroom").hot = S.warroom && Date.now() - new Date(S.warroom.at) < 86400000;
  syncProps();
  const waiting = S.approvals.length + S.owner_tasks.length + S.outbox.manual.length;
  const leads7 = (S.leads || []).filter((l) => Date.now() - new Date(l.created_at) < 7 * 864e5).length;
  const cr = S.credits || {};
  const crText = cr.state === "empty" ? "empty" : cr.remaining == null ? "?" : money(cr.remaining);
  $("#chips").innerHTML = `<span class="chip ${["empty", "low"].includes(cr.state) ? "alert" : ""}" data-go="finance" title="Claude credits left">Credits <b>${crText}</b></span>`
    + `<span class="chip" data-go="finance">Pool <b>${money(S.treasury.pool)}</b></span>`
    + `<span class="chip" data-go="revenue">Leads 7d <b>${leads7}</b></span>`
    + `<span class="chip ${waiting ? "alert" : ""}" data-go="approvals">Waiting <b>${waiting}</b></span>`
    + `<span class="chip" data-go="finance">AI <b>${money(S.treasury.ai.spent_month)}</b>/${money(S.treasury.ai.budget)}</span>`;
  $("#ultron-txt").textContent = S.error ? `⚠ ${S.error}` : `${S.coordinating}${S.mission ? ` · Mission: ${S.mission.name}` : ""}`;
  $("#core-sub").textContent = S.coordinating;
  if (openPanel) openPanel();   // keep an open panel live
}

function syncProps() {
  const research = mods.get("research");
  research.cards.clear();
  S.opportunities.slice(0, 6).forEach((o, i) => {
    const card = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 0.9), new THREE.MeshBasicMaterial({ color: o.startup_cost_usd === 0 ? "#3dffa2" : "#ffc94d", transparent: true, opacity: 0.55, side: THREE.DoubleSide }));
    const a = (i / 6) * Math.PI * 2;
    card.position.set(Math.cos(a) * 4, 3 + (i % 2) * 0.8, Math.sin(a) * 4);
    card.lookAt(0, 3, 0);
    research.cards.add(card);
  });
  const rev = mods.get("revenue");
  rev.bars.clear();
  S.ventures.forEach((v, i) => {
    const h = 0.4 + (v.health || 0) / 25;
    const bar = new THREE.Mesh(new THREE.BoxGeometry(0.7, h, 0.7), glow(STAGE_COLOR[v.stage] || "#8a97bd", 1.4));
    bar.position.set(-2.6 + i * 1.1, 0.3 + h / 2, 0);
    rev.bars.add(bar);
  });
  const fin = mods.get("finance");
  fin.coins.clear();
  const stack = Math.min(14, Math.max(0, Math.round(Math.log10(Math.max(1, S.treasury.pool)) * 3)));
  for (let k = 0; k < stack; k++) {
    const c = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.15, 16), glow("#ffd84d", 1.2));
    c.position.y = 0.1 + k * 0.17;
    fin.coins.add(c);
  }
}

// ---------------------------------------------------------------- panels: tap anything
let openPanel = null;
function show(html, refresh) {
  $("#panel-body").innerHTML = html;
  $("#panel").classList.remove("hidden");
  openPanel = refresh || null;
}
$("#panel-x").addEventListener("click", () => { $("#panel").classList.add("hidden"); openPanel = null; });
const list = (xs) => (xs && xs.length ? xs.map((x) => `<div class="row">${x}</div>`).join("") : `<div class="muted small">Nothing here yet.</div>`);
const agentRow = (a) => `<div class="row" data-pick="agent:${a.id}"><b>${esc(a.name)}</b> <span class="pill" style="color:${STATUS[a.status] || "#fff"}">${esc(a.status)}</span>
  <div class="m">${esc(a.role)}${a.current_task ? " · " + esc(a.current_task) : ""}${a.pet ? ` · 🐾 ${esc(a.pet.name)}` : ""}</div></div>`;

function panelCore() {
  const m = S.mission || {};
  show(`<div class="label">ULTRON · COMMAND CORE</div><h1>${esc(S.coordinating)}</h1>
    <div class="kv"><div>Mission</div><div>${esc(m.name || "—")}</div><div>Goal</div><div>${esc(m.goal || "")}</div>
    <div>First dollar</div><div>${m.first_dollar_at ? ago(m.first_dollar_at) : "not yet"}</div><div>Pool</div><div>${money(S.treasury.pool)}</div>
    <div>AI this month</div><div>${money(S.treasury.ai.spent_month)} of ${money(S.treasury.ai.budget)}</div></div>
    ${S.error ? `<h2>Problem</h2><div class="row neg">${esc(S.error)}</div>` : ""}
    <h2>Station milestones</h2>${(S.milestones || []).map((x) => `<div class="row">${x.at ? "✅" : "⬜"} ${esc(x.title)} <span class="muted small">${x.at ? ago(x.at) : ""}</span></div>`).join("")}
    <h2>Alerts</h2>${list(S.alerts.slice(0, 6).map((e) => `${esc(e.summary)}<div class="m">${ago(e.at)}</div>`))}
    <div class="actions"><a class="btn" href="station.html#/command">Open the board</a></div>`, panelCore);
}
function panelModule(id) {
  const mod = mods.get(id);
  const crew = S.agents.filter((a) => moduleFor(a) === id);
  let body = "";
  if (id === "research") body = `<h2>Routines</h2>${list(S.routines.map((r) => `${esc(r.name)}<div class="m">last run ${ago(r.last_run)}${r.last_error ? " · " + esc(r.last_error) : ""}</div>`))}
    <h2>Top opportunities</h2>${list(S.opportunities.slice(0, 6).map((o) => `${esc(o.title)} <span class="pill ${o.startup_cost_usd === 0 ? "green" : "gold"}">${o.startup_cost_usd === 0 ? "$0" : money(o.startup_cost_usd)}</span><div class="m">score ${o.score} · first $ in ~${o.days_to_first_dollar}d</div>`))}`;
  else if (id === "revenue") body = `${S.storefront && S.storefront.products.length ? `<h2>On sale (storefront)</h2>${S.storefront.products.filter((p) => p.active).slice(0, 6).map((p) => `<div class="row" style="overflow:hidden"><img src="/media/${esc(p.cover)}" alt="" style="width:36px;height:54px;object-fit:cover;border-radius:5px;float:left;margin-right:10px"><b>${esc(p.title)}</b><div class="m">${money(p.price_usd)} · ${p.sales} sale${p.sales === 1 ? "" : "s"}${p.etsy ? " · Etsy" : ""}${p.pinned ? " · pinned" : ""}</div></div>`).join("")}` : ""}<h2>Ventures</h2>${S.ventures.map((v) => `<div class="row" data-pick="venture:${v.id}"><b>${esc(v.name)}</b> <span class="pill">${esc(v.stage)}</span><div class="m">health ${v.health} · net ${money(v.pnl.net)}${v.results ? ` · ${v.results.leads} leads (30d)` : ""}</div></div>`).join("")}`;
  else if (id === "marketing") body = `<h2>Connections</h2><div class="kv"><div>Facebook</div><div>${S.connectors.social.includes("facebook") ? "connected" : "—"}</div><div>Instagram</div><div>${S.connectors.social.includes("instagram") ? "connected" : "—"}</div><div>Stripe</div><div>${S.connectors.stripe ? "connected" : "—"}</div><div>Outbound</div><div>${S.outbound ? "on" : "STOPPED"}</div></div>
    <h2>Recently sent</h2>${list(S.outbox.sent.slice(0, 6).map((a) => `${esc(a.payload.platform || a.kind)}: ${esc((a.payload.text || a.payload.subject || a.payload.name || "").slice(0, 90))}<div class="m">${ago(a.sent_at)}${a.result && a.result.metrics ? " · " + Object.entries(a.result.metrics).map(([k, v]) => `${v} ${k}`).join(", ") : ""}</div>`))}
    <h2>For you to post</h2>${list(S.outbox.manual.slice(0, 5).map((a) => `${esc(a.payload.platform || a.kind)}: ${esc((a.payload.text || a.payload.subject || "").slice(0, 80))}`))}`;
  else if (id === "finance") { const t = S.treasury; body = `<div class="kv"><div>Pool</div><div>${money(t.pool)}</div><div>Runway</div><div>${t.runway_months ?? "—"} months</div><div>City net</div><div>${money(t.city.net)}</div><div>Station net</div><div>${money(t.station.net)}</div><div>AI this month</div><div>${money(t.ai.spent_month)} / ${money(t.ai.budget)}</div></div>
    <h2>Goals</h2>${list(t.goals.map((g) => `${esc(g.name)} · ${Math.round(g.progress * 100)}%`))}
    <h2>Shuttle log</h2>${list((S.flights || []).map((f) => `${f.kind === "payout" ? "🚀 payout from the City" : "🛍️ sale"} <b>+${money(f.amount)}</b><div class="m">${esc(f.note)} · ${ago(f.at)}</div>`))}
    <h2>Recent money</h2>${list(t.recent.filter((e) => e.kind !== "ai_usage").slice(0, 6).map((e) => `${["income", "lucid_payout"].includes(e.kind) ? "+" : "−"}${money(e.amount)} · ${esc(e.note)}<div class="m">${ago(e.at)}</div>`))}`; }
  else if (id === "legal") body = `<div class="kv"><div>In QA</div><div>${S.outbox.in_qa}</div><div>Stopped by QA</div><div>${S.outbox.rejected.length}</div><div>Sent</div><div>${S.outbox.sent.length}</div></div>
    <h2>Recent QA calls</h2>${list(S.events.filter((e) => e.kind.startsWith("action.qa_")).slice(0, 6).map((e) => esc(e.summary)))}`;
  else if (id === "warroom") body = S.warroom ? `<p>${esc(S.warroom.summary)}</p><h2>Stop doing</h2>${list((S.warroom.stop_doing || []).map(esc))}<h2>Start doing</h2>${list((S.warroom.start_doing || []).map(esc))}<h2>Lessons</h2>${list(S.lessons.map((l) => esc(l.lesson)))}` : `<p class="muted">The War Room meets Sundays 17:00 ET or after 8 new results.</p>`;
  else if (id === "approvals") body = `<h2>Decisions</h2>${S.approvals.length ? S.approvals.map((a) => `<div class="row"><b>${esc(a.action)}</b><div class="m">${esc(a.reason).slice(0, 220)}</div>
      <div class="actions"><button class="btn primary" data-decide="${a.id}:approve">Approve</button><button class="btn danger" data-decide="${a.id}:reject">Reject</button></div></div>`).join("") : `<div class="muted small">Nothing to decide.</div>`}
    <h2>Your tasks</h2>${list(S.owner_tasks.map((t) => `${esc(t.title)}<div class="m">${esc(t.venture)} · open the board to see the draft</div>`))}
    <h2>Posts to publish by hand</h2>${list(S.outbox.manual.map((a) => `${esc(a.payload.platform || a.kind)}: ${esc((a.payload.text || "").slice(0, 80))}`))}`;
  else if (id === "lounge") { const lb = [...S.agents].filter((a) => a.kind !== "bot").sort((a, b) => (b.work || 0) - (a.work || 0));
    body = `<h2>Leaderboard</h2>${lb.slice(0, 10).map((a, i) => `<div class="row" data-pick="agent:${a.id}">#${i + 1} <b>${esc(a.name)}</b> · ${a.work || 0} jobs ${(a.achievements || []).length ? `<span class="badgechip">★ ${esc(a.achievements[a.achievements.length - 1].title)}</span>` : ""}${a.pet ? ` · 🐾 ${esc(a.pet.name)}` : ""}</div>`).join("")}
    <h2>Pets</h2>${list(S.agents.filter((a) => a.pet).map((a) => `🐾 ${esc(a.pet.name)} the ${esc(a.pet.kind)} · with ${esc(a.name)}`))}
    <p class="muted small">Pets are earned: a robo-cat at 5 jobs, a drone at 15, a star-jelly at 40, a comet-fox at 100.</p>`; }
  else if (id === "marketplace") { const sh = S.shop || { live: [], drafts: [], pipeline: {} };
    const thumb = (img, ink) => img ? `<img src="/media/${esc(img)}" alt="" style="width:44px;height:52px;object-fit:contain;background:${ink === "light" ? "#1d1d22" : "#f3efe6"};border-radius:6px;float:left;margin-right:10px">` : "";
    body = `<div class="kv"><div>Etsy via Printify</div><div>${sh.connected ? `<span class="pos">connected</span>` : `<span class="muted">waiting for the Printify token</span>`}</div>
      <div>Orders (30d)</div><div>${sh.orders_30d || 0} · ${money(sh.retail_30d || 0)} retail</div><div>New listings</div><div>up to ${sh.per_day}/day</div>
      <div>Pipeline</div><div>${["qa", "ready", "manual", "sent"].map((k) => `${sh.pipeline[k] || 0} ${k === "sent" ? "live" : k === "manual" ? "waiting" : k}`).join(" · ")}</div></div>
      <h2>Live on Etsy</h2>${sh.live.length ? sh.live.slice(0, 8).map((x) => `<div class="row" style="overflow:hidden">${thumb(x.image, x.ink)}<b>${esc(x.title)}</b><div class="m">${esc(x.type)} · ${x.price_cents ? money(x.price_cents[0] / 100) : ""} · ${x.orders} order${x.orders === 1 ? "" : "s"} · listed ${ago(x.sent_at)}</div></div>`).join("") : `<div class="muted small">Nothing listed yet.</div>`}
      <h2>In the works</h2>${sh.drafts.length ? sh.drafts.slice(0, 6).map((x) => `<div class="row" style="overflow:hidden">${thumb(x.image, x.ink)}<b>${esc(x.title)}</b> <span class="pill">${esc(x.status)}</span><div class="m">${esc(x.niche || "")} · ${money(x.price_usd)}</div></div>`).join("") : `<div class="muted small">The Shop Manager's next scan fills this.</div>`}`; }
  else if (id === "citydock") body = `<p>The trading city: Venture #1. The bots trade MNQ on the Lucid account; their profit and payouts fund the station.</p><div class="actions"><a class="btn primary" href="/">Go to the city</a></div>`;
  show(`<div class="label">${esc(mod.name.toUpperCase())}</div><h1>${esc(mod.name)}</h1>${body}<h2>Crew here</h2>${crew.length ? crew.map(agentRow).join("") : `<div class="muted small">Nobody here right now.</div>`}`, () => panelModule(id));
}
function wardrobePanel(a) {
  const w = lookFor(a);
  const worn = Object.values(w.wear).map((id) => ITEMS[id].label).join(" · ");
  const earn = a.kind === "bot" ? "" : w.earned.map((e) => `<div class="row">${e.owned ? "✅" : "🔒"} ${esc(ITEMS[e.item].label)} <span class="muted small">· ${esc(e.need)}</span></div>`).join("");
  return `<h2>Wardrobe${w.title ? " · " + esc(w.title) : ""}</h2><div class="row">${esc(worn)}</div>${earn}`;
}

async function panelAgent(id) {
  const a = S.agents.find((x) => x.id === id);
  if (!a) return;
  let pnl = null;
  try { pnl = (await api(`/api/station/agents/${id}`)).pnl; } catch { /* the card still works without costs */ }
  show(`<div class="label">${esc(a.role.toUpperCase())} · ${esc(a.id)}</div><h1>${esc(a.name)}</h1>
    <div class="kv"><div>Status</div><div style="color:${STATUS[a.status] || "#fff"}">${esc(a.status)}</div><div>Doing</div><div>${esc(a.current_task || "—")}</div>
    <div>Last delivered</div><div>${esc(a.last_output || "—")}</div><div>Jobs done</div><div>${a.work || a.tasks_done || 0}</div>
    <div>Specialty</div><div>${esc(a.specialty || "")}</div>${pnl ? `<div>Cost to run</div><div>${money(pnl.ai_costs)} AI</div>` : ""}</div>
    <h2>Milestones</h2>${(a.achievements || []).length ? `<div class="badges">${a.achievements.map((m) => `<span class="badgechip">★ ${esc(m.title)}</span>`).join("")}</div>` : `<div class="muted small">First milestone at 1 job.</div>`}
    ${wardrobePanel(a)}
    <h2>Pet</h2>${a.pet ? `<div class="row">🐾 <b>${esc(a.pet.name)}</b> the ${esc(a.pet.kind)}</div>` : `<div class="muted small">A robo-cat joins at 5 jobs.</div>`}
    <div class="actions"><a class="btn" href="station.html#/crew">Open in the board</a></div>`, () => panelAgent(id));
}
function panelVenture(id) {
  const v = S.ventures.find((x) => x.id === id);
  if (!v) return;
  show(`<div class="label">VENTURE · ${esc(v.id)}</div><h1>${esc(v.name)}</h1>
    <div class="kv"><div>Stage</div><div>${esc(v.stage)}</div><div>Health</div><div>${v.health}/100</div><div>Net</div><div class="${v.pnl.net < 0 ? "neg" : "pos"}">${money(v.pnl.net)}</div>
    ${v.results ? `<div>Leads (30d)</div><div>${v.results.leads} · won ${money(v.results.won_value)}</div><div>Posts (30d)</div><div>${v.results.posts_sent}</div>` : ""}
    <div>Next</div><div>${esc(v.next_action || "—")}</div></div>
    <div class="actions"><a class="btn primary" href="station.html#/ventures">Open in the board</a></div>`, () => panelVenture(id));
}

document.addEventListener("click", async (e) => {
  const d = e.target.closest("[data-pick],[data-decide],[data-go]");
  if (!d) return;
  if (d.dataset.go) { flyTo(d.dataset.go); panelModule(d.dataset.go); return; }
  if (d.dataset.pick) { const [t, id] = d.dataset.pick.split(":"); t === "agent" ? panelAgent(id) : panelVenture(id); return; }
  const [id, decision] = d.dataset.decide.split(":");
  if (decision === "reject" && !confirm("Reject it?")) return;
  try { await api(`/api/station/approvals/${id}`, { decision, note: "" }); toast(decision === "approve" ? "Approved. ULTRON is on it." : "Rejected."); await load(); }
  catch (err) { toast(err.message, "#ff3b5c"); }
});

// raycast taps on the scene (ignore drags)
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
let downAt = null;
renderer.domElement.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener("pointerup", (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 8 || !S) return;
  ptr.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ptr, camera);
  const hit = ray.intersectObjects(clickables, false)[0];
  if (!hit) return;
  const p = hit.object.userData.pick;
  if (p.type === "core") { flyTo(null); panelCore(); }
  else if (p.type === "module") { flyTo(p.id); panelModule(p.id); }
  else if (p.type === "agent") panelAgent(p.id);
  else if (p.type === "venture") panelVenture(p.id);
});

// camera flights
let flight = null;
function flyTo(id) {
  controls.autoRotate = false;
  const to = id ? mods.get(id).pos.clone() : new THREE.Vector3();
  const dir = to.clone().setY(0).normalize();
  const camTo = id ? to.clone().add(dir.multiplyScalar(26)).setY(22) : HOME.clone();
  flight = { t: 0, fromC: camera.position.clone(), toC: camTo, fromT: controls.target.clone(), toT: to };
}
$("#home-btn").addEventListener("click", () => { flyTo(null); $("#panel").classList.add("hidden"); openPanel = null; });
// labels: who's working (default) → everyone → off
const LABEL_MODES = [["", "Labels: working"], ["alllabels", "Labels: all"], ["nolabels", "Labels: off"]];
let labelMode = 0;
function setLabels(i) {
  labelMode = i % LABEL_MODES.length;
  document.body.classList.remove("alllabels", "nolabels");
  if (LABEL_MODES[labelMode][0]) document.body.classList.add(LABEL_MODES[labelMode][0]);
  $("#labels-btn").textContent = LABEL_MODES[labelMode][1];
}
$("#labels-btn").addEventListener("click", () => setLabels(labelMode + 1));
setLabels(0);

// ---------------------------------------------------------------- the loop
const clock = new THREE.Clock();
function frame() {
  requestAnimationFrame(frame);
  const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
  controls.update();
  for (const r of agents.values()) if (r.apparel.length) animateApparel(r.apparel, clock.elapsedTime);
  document.body.classList.toggle("far", camera.position.distanceTo(controls.target) > 170);   // far away: module names only
  if (flight) {
    flight.t = Math.min(1, flight.t + dt / 1.4);
    const k = flight.t * flight.t * (3 - 2 * flight.t);
    camera.position.lerpVectors(flight.fromC, flight.toC, k);
    controls.target.lerpVectors(flight.fromT, flight.toT, k);
    if (flight.t >= 1) flight = null;
  }
  // core
  eye.material.emissiveIntensity = 3.5 + Math.sin(t * 2.2) * 1.2;
  coreRings.forEach((r, i) => { r.rotation.z += dt * (0.3 + i * 0.25) * (i % 2 ? -1 : 1); });
  beam.material.opacity = 0.18 + Math.sin(t * 1.5) * 0.07;
  // modules
  for (const mod of mods.values()) {
    for (const f of mod.anim) f(t);
    const speed = 0.08 + mod.busy * 0.12;
    mod.pulses.forEach((p) => {
      p.userData.t = (p.userData.t + dt * speed) % 1;
      const r = 11.5 + (RING - 19.5) * p.userData.t;
      p.position.set(Math.cos(mod.angle) * r, -0.4, Math.sin(mod.angle) * r);
    });
    if (mod.ray && mod.ray.material.opacity > 0) mod.ray.material.opacity = Math.max(0, mod.ray.material.opacity - dt * 0.4);
  }
  // planets
  for (const p of planets.values()) {
    const a = p.phase + t * p.speed;
    p.mesh.position.set(Math.cos(a) * p.r, p.h + Math.sin(t * 0.5 + p.phase) * 0.6, Math.sin(a) * p.r);
    p.mesh.rotation.y += dt * 0.5;
  }
  // agents walk (hover) to where their work is
  for (const r of agents.values()) {
    const pos = r.g.position, d = r.target.clone().sub(pos);
    d.y = 0;
    const dist = d.length(), moving = dist > 0.15;
    if (moving) {
      const step = Math.min(dist, dt * 7);
      pos.add(d.normalize().multiplyScalar(step));
      r.g.rotation.y = Math.atan2(d.x, d.z);
    }
    const s = r.data.status;
    const hover = moving ? 1.2 : s === "ON BREAK" ? 0 : 0.15;
    pos.y += ((hover + (s === "WORKING" ? Math.abs(Math.sin(t * 6)) * 0.15 : Math.sin(t * 2 + r.g.id) * 0.08)) - pos.y) * Math.min(1, dt * 5);
    r.jet.visible = moving;
    if (r.halo.visible) r.halo.rotation.z += dt * 3;
    if (r.pet) {
      const pp = r.pet.position, side = new THREE.Vector3(Math.cos(t * 0.6 + r.g.id) * 1.6, 0, Math.sin(t * 0.6 + r.g.id) * 1.6);
      const goal = pos.clone().add(side);
      pp.lerp(goal, Math.min(1, dt * 2));
      pp.y = (r.pet.userData.fly || 0) + Math.sin(t * 3 + r.g.id) * 0.12;
      r.pet.lookAt(goal.x, pp.y, goal.z);
      if (r.pet.userData.spin) r.pet.userData.spin.rotation.z += dt * 12;
    }
  }
  // effects
  for (let i = flying.length - 1; i >= 0; i--) if (!flying[i].update(dt)) flying.splice(i, 1);
  for (let i = fx.length - 1; i >= 0; i--) {
    const m = fx[i];
    if (m.userData.to) {
      m.userData.t += dt / 1.6;
      const k = Math.min(1, m.userData.t);
      m.position.lerpVectors(m.userData.from, m.userData.to, k);
      m.position.y += Math.sin(k * Math.PI) * 10;
      if (k >= 1) { scene.remove(m); fx.splice(i, 1); }
    } else {
      m.userData.life -= dt;
      m.userData.v.y -= dt * 9;
      m.position.addScaledVector(m.userData.v, dt);
      if (m.userData.life <= 0) { scene.remove(m); fx.splice(i, 1); }
    }
  }
  composer.render();
  labels.render(scene, camera);
}
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  composer.setSize(innerWidth, innerHeight);
  labels.setSize(innerWidth, innerHeight);
});
frame();
load();
setInterval(load, 8000);
