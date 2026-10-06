// Skins and apparel for every robot in StarNet: the trading bots (city + streamer rooms) and the
// station's crew (3D station). Each robot has a signature look that matches its persona; more apparel
// is earned from real results and never taken back:
//   bots    lifetime P&L high-water mark (career_best), and the account getting funded
//   agents  the milestones recognition.py awards from the audit log
// dress() builds the meshes; WARDROBE lists what a robot wears and what it can still earn.
import * as THREE from "three";

// finish: the chassis. accent: lights and trim (null = the bot's own color)
const FINISH = {
  chrome: { color: "#e6ebff", metalness: 0.95, roughness: 0.12 },
  pearl: { color: "#f4f1ff", metalness: 0.3, roughness: 0.25 },
  matte: { color: "#8fae9a", metalness: 0.1, roughness: 0.8 },
  carbon: { color: "#22232b", metalness: 0.6, roughness: 0.35 },
  copper: { color: "#d08a5a", metalness: 0.85, roughness: 0.3 },
  gold: { color: "#ffcf40", metalness: 0.95, roughness: 0.2, emissive: "#5a3d00" },
  navy: { color: "#2c3a5e", metalness: 0.6, roughness: 0.35 },
  crimson: { color: "#3a0f1a", metalness: 0.7, roughness: 0.3 },
  ivory: { color: "#e9e2cf", metalness: 0.2, roughness: 0.55 },
};

// Signature looks. Bots by id (personas in backend/config.py), station crew by agent id.
export const LOOKS = {
  "mnq-3m": { finish: "chrome", wear: ["cap_back", "chain"], title: "Hype streamer" },
  "mnq-6m": { finish: "matte", wear: ["beanie", "beads"], title: "Lo-fi zen" },
  "mes-3m": { finish: "pearl", wear: ["glasses", "bowtie"], title: "Data nerd" },
  "mes-6m": { finish: "carbon", wear: ["cat_ears", "shades_neon"], title: "Neon night-owl" },
  "m2k": { finish: "copper", wear: ["propeller", "bandana"], title: "Chaotic gremlin" },
  "A-001": { finish: "crimson", wear: ["crest"], title: "Commander" },
  "A-002": { finish: "pearl", wear: ["goggles"], title: "Researcher" },
  "A-003": { finish: "navy", wear: ["glasses"], title: "Validator" },
  "A-004": { finish: "navy", wear: ["visor_cap", "tie"], title: "Finance" },
  "A-005": { finish: "chrome", wear: ["headset_cap"], title: "Marketing lead" },
  "A-006": { finish: "pearl", wear: ["beret"], title: "Creator" },
  "A-007": { finish: "navy", wear: ["cap"], title: "Outreach" },
  "A-008": { finish: "ivory", wear: ["glasses", "tie"], title: "Accountant" },
  "A-009": { finish: "carbon", wear: ["monocle"], title: "Auditor" },
  "A-010": { finish: "ivory", wear: ["bowtie", "glasses"], title: "Counsel" },
  "A-011": { finish: "navy", wear: ["hardhat"], title: "QA" },
  "A-012": { finish: "carbon", wear: ["helmet"], title: "Strategist" },
  "A-SHOP": { finish: "copper", wear: ["cap"], title: "Shop manager" },
  "A-DSGN": { finish: "pearl", wear: ["beret"], title: "Designer" },
};

// Every wearable: slot, and a rank (an earned item replaces a signature one in the same slot only
// when it ranks higher). label is what the wardrobe shows.
export const ITEMS = {
  cap_back: { slot: "head", rank: 1, label: "Backwards cap" }, beanie: { slot: "head", rank: 1, label: "Beanie" },
  cat_ears: { slot: "head", rank: 1, label: "Cat-ear headband" }, propeller: { slot: "head", rank: 1, label: "Propeller cap" },
  crest: { slot: "head", rank: 4, label: "Commander's crest" }, visor_cap: { slot: "head", rank: 1, label: "Green visor" },
  headset_cap: { slot: "head", rank: 1, label: "Headset + cap" }, beret: { slot: "head", rank: 1, label: "Beret" },
  cap: { slot: "head", rank: 1, label: "Cap" }, hardhat: { slot: "head", rank: 1, label: "Hard hat" },
  helmet: { slot: "head", rank: 1, label: "Tactical helmet" }, crown: { slot: "head", rank: 5, label: "Gold crown" },
  glasses: { slot: "face", rank: 1, label: "Glasses" }, goggles: { slot: "face", rank: 1, label: "Lab goggles" },
  monocle: { slot: "face", rank: 1, label: "Monocle" }, shades_neon: { slot: "face", rank: 1, label: "Neon shades" },
  shades: { slot: "face", rank: 2, label: "Gold shades" },
  chain: { slot: "neck", rank: 1, label: "Chain" }, beads: { slot: "neck", rank: 1, label: "Prayer beads" },
  bowtie: { slot: "neck", rank: 1, label: "Bow tie" }, bandana: { slot: "neck", rank: 1, label: "Bandana" },
  tie: { slot: "neck", rank: 1, label: "Tie" }, scarf: { slot: "neck", rank: 2, label: "Station scarf" },
  chain_gold: { slot: "neck", rank: 3, label: "Gold chain + $ pendant" },
  pin: { slot: "chest", rank: 1, label: "Star pin" }, wings: { slot: "chest", rank: 2, label: "Funded wings" },
  cape: { slot: "back", rank: 2, label: "Cape" }, jetpack: { slot: "back", rank: 3, label: "Gold jetpack" },
};

// What can be earned, in order. `need` describes it in words for the wardrobe.
const BOT_EARN = [
  { item: "pin", need: "first $100 lifetime", ok: (b) => (b.career_best || 0) >= 100 },
  { item: "shades", need: "$1,000 lifetime", ok: (b) => (b.career_best || 0) >= 1000 },
  { item: "chain_gold", need: "$5,000 lifetime", ok: (b) => (b.career_best || 0) >= 5000 },
  { item: "wings", need: "the account gets funded", ok: (b, ctx) => ["funded", "payout"].includes(ctx?.phase) },
  { item: "cape", need: "$10,000 lifetime", ok: (b) => (b.career_best || 0) >= 10000 },
  { item: "crown", need: "$25,000 lifetime", ok: (b) => (b.career_best || 0) >= 25000 },
  { item: "jetpack", need: "$50,000 lifetime", ok: (b) => (b.career_best || 0) >= 50000 },
];
const AGENT_EARN = [   // titles from backend/station/recognition.py MILESTONES
  { item: "pin", need: "First delivery", title: "First delivery" },
  { item: "scarf", need: "Reliable (5 jobs)", title: "Reliable" },
  { item: "shades", need: "Veteran (15 jobs)", title: "Veteran" },
  { item: "cape", need: "Legend (40 jobs)", title: "Legend" },
  { item: "crown", need: "Hall of Fame (100 jobs)", title: "Station Hall of Fame" },
];

/** The robot's whole wardrobe: what it wears (by slot), what it owns, what it can still earn. */
export function wardrobe(who, kind = "bot", ctx = {}) {
  const look = LOOKS[who.id] || { finish: kind === "bot" ? "chrome" : "navy", wear: ["cap"], title: "" };
  const earned = kind === "bot"
    ? BOT_EARN.map((e) => ({ ...e, owned: e.ok(who, ctx) }))
    : AGENT_EARN.map((e) => ({ ...e, owned: (who.achievements || []).some((a) => a.title === e.title) }));
  const owned = [...look.wear, ...earned.filter((e) => e.owned).map((e) => e.item)];
  const wear = {};
  for (const id of owned) {
    const it = ITEMS[id];
    if (it && (!wear[it.slot] || ITEMS[wear[it.slot]].rank < it.rank)) wear[it.slot] = id;
  }
  // the finish turns gold once a bot is a legend (crown) or an agent reaches the Hall of Fame
  const finish = owned.includes("crown") && kind === "bot" ? "gold" : look.finish;
  return { finish, title: look.title, wear, signature: look.wear, earned, owned };
}

export function finishMaterial(name) {
  // These scenes have no environment map to reflect, so a true mirror finish would render black:
  // metalness is capped and a faint self-glow in the finish's own color keeps it reading as that color.
  const f = FINISH[name] || FINISH.chrome;
  return new THREE.MeshStandardMaterial({ color: f.color, metalness: Math.min(0.55, f.metalness), roughness: Math.max(0.3, f.roughness),
                                          emissive: f.emissive || f.color, emissiveIntensity: f.emissive ? 0.35 : 0.12 });
}

// ---------------------------------------------------------------- meshes
const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.1, ...o });
const GOLD = () => std("#ffcf40", { metalness: 0.95, roughness: 0.2, emissive: "#5a3d00", emissiveIntensity: 0.4 });
const glow = (c, k = 2) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: k });

function mesh(geo, mat, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z);
  return m;
}

// Each builder makes the item for a head `w` wide, at the origin of its slot anchor, facing +z.
const BUILD = {
  cap_back: (w, c) => { const g = new THREE.Group();
    g.add(mesh(new THREE.SphereGeometry(w * 0.52, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), std(c)));
    const bill = mesh(new THREE.BoxGeometry(w * 0.6, w * 0.04, w * 0.45), std(c), 0, 0.01, -w * 0.55); g.add(bill); return g; },
  cap: (w, c) => { const g = BUILD.cap_back(w, c); g.rotation.y = Math.PI; return g; },
  beanie: (w) => { const g = new THREE.Group();
    g.add(mesh(new THREE.SphereGeometry(w * 0.53, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), std("#6b8f71")));
    g.add(mesh(new THREE.TorusGeometry(w * 0.52, w * 0.07, 8, 24), std("#4e6b53"), 0, 0.02, 0).rotateX(Math.PI / 2));
    g.add(mesh(new THREE.SphereGeometry(w * 0.12, 10, 8), std("#e7efe0"), 0, w * 0.55, 0)); return g; },
  cat_ears: (w) => { const g = new THREE.Group();
    for (const s of [-1, 1]) g.add(mesh(new THREE.ConeGeometry(w * 0.16, w * 0.32, 4), glow("#ff3df2", 1.5), s * w * 0.3, w * 0.14, 0));
    g.add(mesh(new THREE.TorusGeometry(w * 0.45, w * 0.03, 6, 24, Math.PI), std("#222")).rotateZ(0)); return g; },
  propeller: (w) => { const g = BUILD.cap(w, "#ff8a3d");
    const p = mesh(new THREE.BoxGeometry(w * 0.9, w * 0.03, w * 0.1), glow("#3dd6ff", 1), 0, w * 0.6, 0);
    p.userData.spin = 8; g.add(mesh(new THREE.CylinderGeometry(w * 0.02, w * 0.02, w * 0.12), std("#999"), 0, w * 0.53, 0), p); return g; },
  crest: (w) => { const g = new THREE.Group();
    for (let i = -2; i <= 2; i++) g.add(mesh(new THREE.ConeGeometry(w * 0.08, w * (0.45 - Math.abs(i) * 0.08), 4), glow("#ff2a4d", 2), i * w * 0.14, w * 0.18, 0));
    return g; },
  visor_cap: (w) => { const g = new THREE.Group();
    g.add(mesh(new THREE.TorusGeometry(w * 0.5, w * 0.03, 6, 24), std("#222")).rotateX(Math.PI / 2));
    g.add(mesh(new THREE.CylinderGeometry(w * 0.5, w * 0.52, w * 0.02, 24, 1, false, -Math.PI / 2, Math.PI), new THREE.MeshStandardMaterial({ color: "#2ecc71", transparent: true, opacity: 0.7 }), 0, 0, w * 0.15));
    return g; },
  headset_cap: (w, c) => { const g = BUILD.cap(w, c);
    g.add(mesh(new THREE.TorusGeometry(w * 0.55, w * 0.04, 8, 24, Math.PI), std("#222")).rotateY(Math.PI / 2)); return g; },
  beret: (w) => { const g = new THREE.Group(); const b = mesh(new THREE.CylinderGeometry(w * 0.55, w * 0.5, w * 0.12, 24), std("#c0392b"), w * 0.08, w * 0.06, 0);
    b.rotation.z = -0.25; g.add(b, mesh(new THREE.SphereGeometry(w * 0.05, 8, 6), std("#c0392b"), w * 0.1, w * 0.15, 0)); return g; },
  hardhat: (w) => { const g = new THREE.Group();
    g.add(mesh(new THREE.SphereGeometry(w * 0.55, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), std("#ffc94d", { roughness: 0.3 })));
    g.add(mesh(new THREE.CylinderGeometry(w * 0.7, w * 0.7, w * 0.04, 24), std("#ffc94d", { roughness: 0.3 }))); return g; },
  helmet: (w) => { const g = new THREE.Group();
    g.add(mesh(new THREE.SphereGeometry(w * 0.58, 20, 10, 0, Math.PI * 2, 0, Math.PI / 1.8), std("#3d4a2f", { roughness: 0.9 })));
    g.add(mesh(new THREE.BoxGeometry(w * 0.3, w * 0.12, w * 0.1), glow("#5ee7ff", 2), 0, w * 0.25, w * 0.5)); return g; },
  crown: (w) => { const g = new THREE.Group(); const gold = GOLD();
    g.add(mesh(new THREE.CylinderGeometry(w * 0.42, w * 0.42, w * 0.18, 20, 1, true), gold, 0, w * 0.09, 0));
    for (let i = 0; i < 6; i++) { const a = (i / 6) * Math.PI * 2;
      g.add(mesh(new THREE.ConeGeometry(w * 0.07, w * 0.22, 4), gold, Math.cos(a) * w * 0.42, w * 0.28, Math.sin(a) * w * 0.42));
      g.add(mesh(new THREE.SphereGeometry(w * 0.04, 8, 6), glow(i % 2 ? "#ff3b5c" : "#5ee7ff", 2), Math.cos(a) * w * 0.42, w * 0.12, Math.sin(a) * w * 0.42)); }
    return g; },
  glasses: (w) => { const g = new THREE.Group(); const m = std("#111", { metalness: 0.5 });
    for (const s of [-1, 1]) g.add(mesh(new THREE.TorusGeometry(w * 0.12, w * 0.02, 6, 20), m, s * w * 0.17, 0, 0));
    g.add(mesh(new THREE.BoxGeometry(w * 0.1, w * 0.02, w * 0.02), m)); return g; },
  goggles: (w) => { const g = new THREE.Group();
    for (const s of [-1, 1]) g.add(mesh(new THREE.CylinderGeometry(w * 0.14, w * 0.14, w * 0.08, 16), new THREE.MeshStandardMaterial({ color: "#5ee7ff", transparent: true, opacity: 0.6 }), s * w * 0.18, 0, 0).rotateX(Math.PI / 2));
    g.add(mesh(new THREE.TorusGeometry(w * 0.5, w * 0.03, 6, 24), std("#333")).rotateX(Math.PI / 2)); return g; },
  monocle: (w) => { const g = new THREE.Group(); const gold = GOLD();
    g.add(mesh(new THREE.TorusGeometry(w * 0.13, w * 0.02, 6, 20), gold, w * 0.17, 0, 0));
    g.add(mesh(new THREE.CylinderGeometry(w * 0.006, w * 0.006, w * 0.4), gold, w * 0.28, -w * 0.25, 0)); return g; },
  shades_neon: (w) => { const g = new THREE.Group(); g.add(mesh(new THREE.BoxGeometry(w * 0.7, w * 0.13, w * 0.04), glow("#ff3df2", 2.5))); return g; },
  shades: (w) => { const g = new THREE.Group(); const gold = GOLD();
    for (const s of [-1, 1]) g.add(mesh(new THREE.BoxGeometry(w * 0.28, w * 0.14, w * 0.03), std("#0a0a0a", { metalness: 0.9, roughness: 0.05 }), s * w * 0.17, 0, 0));
    g.add(mesh(new THREE.BoxGeometry(w * 0.72, w * 0.025, w * 0.03), gold, 0, w * 0.07, 0)); return g; },
  chain: (w) => { const g = new THREE.Group(); g.add(mesh(new THREE.TorusGeometry(w * 0.45, w * 0.03, 8, 32), std("#d9dcff", { metalness: 1, roughness: 0.2 })).rotateX(Math.PI / 2.4)); return g; },
  chain_gold: (w) => { const g = new THREE.Group(); const gold = GOLD();
    g.add(mesh(new THREE.TorusGeometry(w * 0.45, w * 0.045, 8, 32), gold).rotateX(Math.PI / 2.4));
    const tag = canvasDollar(); g.add(mesh(new THREE.CircleGeometry(w * 0.13, 20), new THREE.MeshBasicMaterial({ map: tag }), 0, -w * 0.2, w * 0.42)); return g; },
  beads: (w) => { const g = new THREE.Group();
    for (let i = 0; i < 14; i++) { const a = (i / 14) * Math.PI * 2;
      g.add(mesh(new THREE.SphereGeometry(w * 0.045, 8, 6), std("#7a4b2a"), Math.cos(a) * w * 0.44, Math.sin(a) * w * 0.1 - w * 0.05, Math.sin(a) * w * 0.44)); }
    return g; },
  bowtie: (w) => { const g = new THREE.Group(); const m = std("#c0392b");
    for (const s of [-1, 1]) g.add(mesh(new THREE.ConeGeometry(w * 0.09, w * 0.18, 4), m, s * w * 0.09, 0, w * 0.42).rotateZ(s * Math.PI / 2));
    return g; },
  tie: (w) => { const g = new THREE.Group(); g.add(mesh(new THREE.BoxGeometry(w * 0.1, w * 0.45, w * 0.02), std("#2c3e8f"), 0, -w * 0.25, w * 0.42)); return g; },
  bandana: (w) => { const g = new THREE.Group(); g.add(mesh(new THREE.ConeGeometry(w * 0.4, w * 0.35, 3, 1, true), std("#e74c3c", { side: THREE.DoubleSide }), 0, -w * 0.1, w * 0.2).rotateX(Math.PI)); return g; },
  scarf: (w) => { const g = new THREE.Group(); const m = std("#5ee7ff");
    g.add(mesh(new THREE.TorusGeometry(w * 0.42, w * 0.08, 8, 24), m).rotateX(Math.PI / 2));
    g.add(mesh(new THREE.BoxGeometry(w * 0.14, w * 0.4, w * 0.05), m, w * 0.15, -w * 0.25, w * 0.42)); return g; },
  pin: (w) => { const g = new THREE.Group(); const s = new THREE.Shape();
    for (let i = 0; i < 10; i++) { const r = i % 2 ? w * 0.05 : w * 0.11, a = (i / 10) * Math.PI * 2 + Math.PI / 2; i ? s.lineTo(Math.cos(a) * r, Math.sin(a) * r) : s.moveTo(Math.cos(a) * r, Math.sin(a) * r); }
    g.add(mesh(new THREE.ExtrudeGeometry(s, { depth: w * 0.02, bevelEnabled: false }), GOLD())); return g; },
  wings: (w) => { const g = new THREE.Group();
    for (const s of [-1, 1]) { const m = mesh(new THREE.BoxGeometry(w * 0.3, w * 0.06, w * 0.02), GOLD(), s * w * 0.18, 0, 0); m.rotation.z = s * 0.25; g.add(m); }
    g.add(mesh(new THREE.SphereGeometry(w * 0.06, 10, 8), glow("#5ee7ff", 2))); return g; },
  cape: (w, c) => { const g = new THREE.Group();
    const cape = mesh(new THREE.PlaneGeometry(w * 1.0, w * 1.5, 1, 6), std(c, { side: THREE.DoubleSide, roughness: 0.9 }), 0, -w * 0.75, 0);
    cape.userData.wave = true; g.add(cape); return g; },
  jetpack: (w) => { const g = new THREE.Group(); const gold = GOLD();
    for (const s of [-1, 1]) { g.add(mesh(new THREE.CylinderGeometry(w * 0.12, w * 0.12, w * 0.6, 12), gold, s * w * 0.16, -w * 0.3, 0));
      const f = mesh(new THREE.ConeGeometry(w * 0.1, w * 0.3, 10), glow("#ff8a3d", 3), s * w * 0.16, -w * 0.75, 0); f.rotation.x = Math.PI; f.userData.flicker = true; g.add(f); }
    return g; },
};

let _dollar = null;
function canvasDollar() {
  if (_dollar) return _dollar;
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = "#ffcf40"; g.beginPath(); g.arc(32, 32, 30, 0, Math.PI * 2); g.fill();
  g.fillStyle = "#5a3d00"; g.font = "bold 44px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText("$", 32, 35);
  return (_dollar = new THREE.CanvasTexture(c));
}

/**
 * Put the apparel on a robot. `anchors` maps each slot to { parent, pos: [x, y, z], w } where parent is
 * the group the item hangs from (the head group for head/face items), pos its local position and w
 * the head width there. Returns the meshes added (to animate or remove later).
 */
export function dress(wear, anchors, color = "#5ee7ff") {
  const added = [];
  for (const [slot, id] of Object.entries(wear)) {
    const a = anchors[slot];
    const build = BUILD[id];
    if (!a || !build) continue;
    const item = build(a.w, color);
    item.position.set(...a.pos);
    if (a.rot) item.rotation.set(...a.rot);
    item.userData.apparel = id;
    a.parent.add(item);
    added.push(item);
  }
  return added;
}

/** Animate what moves: propellers spin, capes wave, jetpack flames flicker. Call every frame. */
export function animateApparel(items, t) {
  for (const it of items) {
    it.traverse((o) => {
      if (o.userData.spin) o.rotation.y = t * o.userData.spin;
      if (o.userData.flicker) o.scale.y = 0.8 + Math.sin(t * 30 + o.position.x * 9) * 0.25;
      if (o.userData.wave) o.rotation.x = 0.15 + Math.sin(t * 2.2) * 0.08;
    });
  }
}
