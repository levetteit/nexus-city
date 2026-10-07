// The Station district: ULTRON's crew lives around the city. Every station module is a building on the outer ring,
// joined to the city by roads. Agents work at their department's building while they have a task; on their free
// time they walk the roads to the lounge, the plaza, the park or a friend's building. Everything shown is live
// station data (/api/station): who is working on what, who is on break.
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { wardrobe, dress, finishMaterial, animateApparel } from "./skins.js";

export const MODULES = [
  { id: "research", name: "Research Lab", color: "#5ee7ff", depts: ["research"], shape: "dish" },
  { id: "revenue", name: "Revenue Ops", color: "#3dffa2", depts: ["revenue"], shape: "bars" },
  { id: "marketing", name: "Marketing & Media", color: "#ff7ad9", depts: ["marketing"], shape: "billboard" },
  { id: "creative", name: "Creative Lab", color: "#c38bff", depts: ["creative"], shape: "cubes" },
  { id: "marketplace", name: "Marketplace Deck", color: "#ffa94d", depts: ["marketplace"], shape: "market" },
  { id: "finance", name: "Finance Observatory", color: "#ffd84d", depts: ["finance"], shape: "observatory" },
  { id: "legal", name: "Legal & QA", color: "#9fb4ff", depts: ["legal"], shape: "temple" },
  { id: "warroom", name: "War Room", color: "#ff4d4d", depts: ["warroom"], shape: "bunker" },
  { id: "engineering", name: "Engineering Bay", color: "#4dd2ff", depts: ["engineering"], shape: "hangar" },
  { id: "quarters", name: "Agent Quarters", color: "#8a97bd", depts: [], shape: "apartments" },
  { id: "lounge", name: "Crew Lounge", color: "#b48bff", depts: [], shape: "cafe" },
  { id: "approvals", name: "Approval Chamber", color: "#ffc94d", depts: [], shape: "chamber" },
  { id: "citydock", name: "City Dock", color: "#ff5ad1", depts: ["city"], shape: "pad" },
];
export const RING_ROAD = 50;      // road around the city
export const DISTRICT = 68;       // where the station buildings stand
const ROAD_W = 3.4;
const SPEED = 5.5;                // world units a second when walking
const FREE = ["ON BREAK", "WAITING", "COMPLETED", "IDLE", "BENCHED"];

export function moduleFor(a) {
  if (a.id === "A-001") return "approvals";
  const m = MODULES.find((x) => x.depts.includes(a.department));
  return m ? m.id : "revenue";
}

export function personaOf(a) {
  const p = a.persona || {};
  const short = (a.name || a.id).replace(/ Agent$/, "").split(/[\s&/]+/)[0];
  return { callsign: a.callsign || p.callsign || short.toUpperCase(), handle: p.handle || short, vibe: p.vibe || a.role || "",
           color: p.color || "#9ab4ff", props: p.props || ["plant", "books"], idle: p.idle || ["on a break"], work: p.work || ["working"],
           win: p.win || ["done"] };
}

const glow = (c, i = 1.4) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: i, roughness: 0.4 });
const solid = (c, r = 0.7, m = 0.1) => new THREE.MeshStandardMaterial({ color: c, roughness: r, metalness: m });

export class StationDistrict {
  constructor(scene, clickables) {
    this.scene = scene;
    this.clickables = clickables;
    this.root = new THREE.Group();
    scene.add(this.root);
    this.mods = new Map();
    this.agents = new Map();
    this.spots = [];          // free-time destinations: {name, pos, angle, r}
    this.buildRoads();
    MODULES.forEach((m, i) => this.buildModule(m, i));
    this.buildPark();
  }

  // ---------------------------------------------------------------- the ground plan
  angleOf(i) { return (i / MODULES.length) * Math.PI * 2 + Math.PI / MODULES.length; }

  buildRoads() {
    const asphalt = new THREE.MeshStandardMaterial({ color: "#3b3570", emissive: "#1c1640", emissiveIntensity: 0.6, roughness: 0.9 });
    const ring = new THREE.Mesh(new THREE.RingGeometry(RING_ROAD - ROAD_W / 2, RING_ROAD + ROAD_W / 2, 160), asphalt);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.06;
    this.root.add(ring);
    // dashed centre line
    const dashMat = new THREE.MeshBasicMaterial({ color: "#ffe9a8" });
    const dashGeo = new THREE.PlaneGeometry(0.18, 1.4);
    for (let i = 0; i < 120; i++) {
      const a = (i / 120) * Math.PI * 2;
      const d = new THREE.Mesh(dashGeo, dashMat);
      d.rotation.x = -Math.PI / 2;
      d.rotation.z = -a;
      d.position.set(Math.cos(a) * RING_ROAD, 0.08, Math.sin(a) * RING_ROAD);
      this.root.add(d);
    }
    // edge lights
    const edge = (r, c) => {
      const m = new THREE.Mesh(new THREE.RingGeometry(r - 0.08, r + 0.08, 160), new THREE.MeshBasicMaterial({ color: c }));
      m.rotation.x = -Math.PI / 2;
      m.position.y = 0.09;
      this.root.add(m);
    };
    edge(RING_ROAD - ROAD_W / 2, "#7c5cff");
    edge(RING_ROAD + ROAD_W / 2, "#7c5cff");
    // spokes: city edge → ring road → each building's door
    MODULES.forEach((m, i) => {
      const a = this.angleOf(i);
      const spoke = new THREE.Mesh(new THREE.PlaneGeometry(2.2, DISTRICT - 7 - 36), asphalt);
      spoke.rotation.x = -Math.PI / 2;
      spoke.rotation.z = -a + Math.PI / 2;
      const mid = (36 + DISTRICT - 7) / 2;
      spoke.position.set(Math.cos(a) * mid, 0.055, Math.sin(a) * mid);
      this.root.add(spoke);
      for (const s of [-1.15, 1.15]) {   // glowing kerbs in the building's color
        const kerb = new THREE.Mesh(new THREE.PlaneGeometry(0.14, DISTRICT - 7 - 36), new THREE.MeshBasicMaterial({ color: m.color }));
        kerb.rotation.x = -Math.PI / 2;
        kerb.rotation.z = -a + Math.PI / 2;
        kerb.position.set(Math.cos(a) * mid + Math.cos(a + Math.PI / 2) * s, 0.07, Math.sin(a) * mid + Math.sin(a + Math.PI / 2) * s);
        this.root.add(kerb);
      }
      for (const r of [40, 46, 56, 61]) {   // street lamps
        const lamp = new THREE.Group();
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.09, 2.6, 6), solid("#3b3566"));
        pole.position.y = 1.3;
        const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.22, 10, 8), glow(m.color, 2.2));
        bulb.position.y = 2.7;
        lamp.add(pole, bulb);
        const off = 1.6;
        lamp.position.set(Math.cos(a) * r + Math.cos(a + Math.PI / 2) * off, 0, Math.sin(a) * r + Math.sin(a + Math.PI / 2) * off);
        this.root.add(lamp);
      }
    });
    // the city plaza itself is a free-time spot
    this.spots.push({ name: "the plaza", angle: 0.4, r: 31 }, { name: "the plaza", angle: 2.6, r: 31 }, { name: "the plaza", angle: 4.5, r: 31 });
  }

  buildPark() {
    // a small park on the ring road: trees, a fountain, benches
    const a = this.angleOf(10) + Math.PI / MODULES.length;   // between the lounge and the approval chamber
    const c = new THREE.Vector3(Math.cos(a) * 58, 0, Math.sin(a) * 58);
    const lawn = new THREE.Mesh(new THREE.CircleGeometry(5.5, 32), solid("#1f6b4a", 1));
    lawn.rotation.x = -Math.PI / 2;
    lawn.position.copy(c).setY(0.07);
    this.root.add(lawn);
    const fountain = new THREE.Mesh(new THREE.CylinderGeometry(1.4, 1.6, 0.6, 24), solid("#cfd6ff", 0.5));
    fountain.position.copy(c).setY(0.3);
    const water = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, 0.1, 24), glow("#5ee7ff", 1.2));
    water.position.copy(c).setY(0.62);
    this.fountain = water;
    this.root.add(fountain, water);
    for (let i = 0; i < 6; i++) {
      const t = new THREE.Group();
      const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.2, 1.2, 6), solid("#5a3d2b"));
      trunk.position.y = 0.6;
      const crown = new THREE.Mesh(new THREE.ConeGeometry(0.9, 2.2, 8), glow("#3dffa2", 0.35));
      crown.position.y = 2.1;
      t.add(trunk, crown);
      const ta = (i / 6) * Math.PI * 2;
      t.position.set(c.x + Math.cos(ta) * 4.2, 0, c.z + Math.sin(ta) * 4.2);
      this.root.add(t);
    }
    this.spots.push({ name: "the park", angle: a, r: 56 }, { name: "the park", angle: a + 0.05, r: 60 });
  }

  // ---------------------------------------------------------------- buildings
  buildModule(m, i) {
    const a = this.angleOf(i);
    const g = new THREE.Group();
    g.position.set(Math.cos(a) * DISTRICT, 0, Math.sin(a) * DISTRICT);
    g.rotation.y = -a - Math.PI / 2;   // the door faces the city
    g.scale.setScalar(1.3);
    const c = new THREE.Color(m.color);
    const pad = new THREE.Mesh(new THREE.CylinderGeometry(7, 7.4, 0.6, 6), new THREE.MeshStandardMaterial({ color: "#2a2366", emissive: c, emissiveIntensity: 0.12, roughness: 0.8 }));
    pad.position.y = 0.3;
    const padEdge = new THREE.Mesh(new THREE.TorusGeometry(7.05, 0.09, 6, 6), new THREE.MeshBasicMaterial({ color: c }));
    padEdge.rotation.x = Math.PI / 2;
    padEdge.rotation.z = Math.PI / 6;
    padEdge.position.y = 0.62;
    g.add(pad, padEdge);
    const body = new THREE.Group();
    body.position.y = 0.6;
    g.add(body);
    this.shape(m.shape, body, c);
    // door
    const door = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 2.2), glow(m.color, 2));
    door.position.set(0, 1.7, 4.05);
    g.add(door);
    // sign
    const el = document.createElement("div");
    el.className = "mod-sign";
    el.style.setProperty("--accent", m.color);
    el.innerHTML = `<b>${m.name}</b><small></small>`;
    el.onclick = () => this.onModule?.(m.id);
    const sign = new CSS2DObject(el);
    sign.position.set(0, 11, 0);
    g.add(sign);
    // the whole building can be clicked
    const pick = new THREE.Mesh(new THREE.CylinderGeometry(6.5, 6.5, 10, 8), new THREE.MeshBasicMaterial({ visible: false }));
    pick.position.y = 5;
    pick.userData.module = m.id;
    g.add(pick);
    this.clickables.push(pick);
    this.root.add(g);
    const door_world = new THREE.Vector3(Math.cos(a) * (DISTRICT - 7.5), 0, Math.sin(a) * (DISTRICT - 7.5));
    this.mods.set(m.id, { ...m, angle: a, group: g, body, sign: el, door: door_world, busy: 0, lights: [] });
    if (["lounge", "quarters", "citydock", "creative", "marketplace"].includes(m.id)) {
      this.spots.push({ name: `the ${m.name}`, angle: a, r: DISTRICT - 7.5, module: m.id });
    }
  }

  shape(kind, g, c) {
    const wall = new THREE.MeshStandardMaterial({ color: "#5a52a8", emissive: c, emissiveIntensity: 0.28, roughness: 0.6 });
    const trim = glow(c, 1.6);
    const box = (w, h, d, mat, x = 0, y = 0, z = 0) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      m.position.set(x, y + h / 2, z);
      g.add(m);
      return m;
    };
    const cyl = (rt, rb, h, mat, x = 0, y = 0, z = 0, seg = 20) => {
      const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), mat);
      m.position.set(x, y + h / 2, z);
      g.add(m);
      return m;
    };
    const dome = (r, mat, x = 0, y = 0, z = 0) => {
      const m = new THREE.Mesh(new THREE.SphereGeometry(r, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), mat);
      m.position.set(x, y, z);
      g.add(m);
      return m;
    };
    const windows = (w, h, z) => {   // a strip of lit windows
      const m = new THREE.Mesh(new THREE.PlaneGeometry(w, 0.35), glow("#fff1c4", 1.1));
      m.position.set(0, h, z);
      g.add(m);
    };
    this.anim = this.anim || [];
    switch (kind) {
      case "dish": {
        cyl(3, 3.4, 4, wall); dome(3, glass(c), 0, 4);
        const mast = cyl(0.15, 0.15, 3, solid("#aab"), 2.2, 4);
        const dish = new THREE.Mesh(new THREE.SphereGeometry(1.4, 20, 10, 0, Math.PI * 2, 0, Math.PI / 3), solid("#dfe6ff", 0.4, 0.5));
        dish.position.set(2.2, 7.4, 0);
        dish.rotation.x = Math.PI;
        g.add(dish);
        this.anim.push((t) => { dish.rotation.z = Math.sin(t * 0.4) * 0.5; });
        windows(5, 2, 3.05);
        break;
      }
      case "bars": {
        box(6, 1.2, 4.5, wall);
        [2.5, 4, 6, 8].forEach((h, i) => box(0.9, h, 0.9, glow(c, 0.9 + i * 0.2), -2.2 + i * 1.45, 1.2, -0.5));
        break;
      }
      case "billboard": {
        box(3.6, 8, 3.6, wall); windows(3.4, 3, 1.82); windows(3.4, 5.5, 1.82);
        const screen = box(6, 3, 0.25, glow(c, 1.8), 0, 8.4, 0);
        this.anim.push((t) => { screen.material.emissiveIntensity = 1.4 + Math.sin(t * 3) * 0.5; });
        break;
      }
      case "cubes": {
        const cols = ["#c38bff", "#ff7ad9", "#5ee7ff", "#ffd84d"];
        box(3, 3, 3, glow(cols[0], 0.7), -1.2, 0, 0);
        box(2.4, 2.4, 2.4, glow(cols[1], 0.7), 1.4, 0, 0.6);
        const top = box(2, 2, 2, glow(cols[2], 0.9), -0.4, 3, 0);
        box(1.2, 1.2, 1.2, glow(cols[3], 1), 1.3, 2.4, 0.4);
        this.anim.push((t) => { top.rotation.y = t * 0.5; });
        break;
      }
      case "market": {
        box(6, 2.4, 4, wall);
        for (let i = 0; i < 3; i++) {
          const aw = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.15, 1.6), glow(i % 2 ? "#ffffff" : c, 0.9));
          aw.position.set(-2 + i * 2, 2.9, 2.6);
          aw.rotation.x = 0.3;
          g.add(aw);
        }
        box(2.6, 1.6, 2.6, wall, 0, 2.4, -0.5); windows(5.8, 1.6, 2.05);
        break;
      }
      case "observatory": {
        cyl(3.2, 3.5, 3.5, wall); const d = dome(3.1, solid("#dfe3ff", 0.35, 0.6), 0, 3.5);
        const scope = cyl(0.35, 0.5, 3, solid("#334"), 0.8, 5.2, 0);
        scope.rotation.z = -0.7;
        box(1, 3, 0.2, trim, 0, 3.6, 2.9);
        this.anim.push((t) => { d.rotation.y = t * 0.15; });
        windows(5.5, 1.6, 3.2);
        break;
      }
      case "temple": {
        box(6.4, 0.6, 4.4, solid("#d9def5", 0.6));
        for (let i = 0; i < 5; i++) cyl(0.32, 0.32, 3.4, solid("#e8ebff", 0.5), -2.6 + i * 1.3, 0.6, 1.6);
        box(6.4, 3.4, 2.6, wall, 0, 0.6, -0.8);
        const roof = new THREE.Mesh(new THREE.ConeGeometry(4.4, 1.6, 4), solid("#e8ebff", 0.5));
        roof.position.set(0, 4.8, 0);
        roof.rotation.y = Math.PI / 4;
        roof.scale.z = 0.7;
        g.add(roof);
        box(6.4, 0.15, 0.1, trim, 0, 4.0, 2.25);
        break;
      }
      case "bunker": {
        box(6, 2.4, 4.6, solid("#3a2730", 0.9)); box(4, 1, 3, solid("#2c1d24"), 0, 2.4, 0);
        const beacon = cyl(0.3, 0.3, 0.5, glow("#ff2a2a", 3), 0, 3.4, 0);
        this.anim.push((t) => { beacon.material.emissiveIntensity = Math.sin(t * 5) > 0 ? 4 : 0.5; });
        windows(5.6, 1.5, 2.31);
        break;
      }
      case "hangar": {
        const h = new THREE.Mesh(new THREE.CylinderGeometry(3.2, 3.2, 6.4, 20, 1, false, 0, Math.PI), wall);
        h.rotation.z = Math.PI / 2;
        h.rotation.y = Math.PI / 2;
        h.position.y = 0;
        g.add(h);
        const gear = new THREE.Mesh(new THREE.TorusGeometry(1.1, 0.25, 6, 12), trim);
        gear.position.set(0, 4.3, 0);
        g.add(gear);
        this.anim.push((t) => { gear.rotation.z = t; });
        break;
      }
      case "apartments": {
        box(3, 9, 3, wall, -1.6, 0, 0); box(3, 6.5, 3, wall, 1.6, 0, 0.4);
        for (let y = 1.5; y < 9; y += 1.5) windows(2.8, y, 1.52);
        break;
      }
      case "cafe": {
        box(6, 3, 4, wall); const awning = box(6.4, 0.2, 1.6, glow(c, 1.2), 0, 3, 2.6);
        awning.rotation.x = 0.25;
        for (const x of [-2, 0, 2]) {
          cyl(0.5, 0.5, 0.08, solid("#ddd"), x, 0.9, 4.6, 12); cyl(0.07, 0.07, 0.9, solid("#888"), x, 0, 4.6, 6);
        }
        const neon = box(3, 0.6, 0.1, glow("#ff7ad9", 2.4), 0, 3.5, 2.05);
        this.anim.push((t) => { neon.material.emissiveIntensity = 2 + Math.sin(t * 2.2) * 0.8; });
        windows(5.6, 1.6, 2.05);
        break;
      }
      case "chamber": {
        cyl(3.4, 3.4, 3, wall); dome(3.4, glass(c), 0, 3);
        const ringM = new THREE.Mesh(new THREE.TorusGeometry(4.4, 0.18, 8, 64), glow("#ffc94d", 2));
        ringM.position.y = 5.5;
        ringM.rotation.x = Math.PI / 2;
        g.add(ringM);
        this.anim.push((t) => { ringM.rotation.z = t * 0.6; ringM.position.y = 5.5 + Math.sin(t) * 0.3; });
        break;
      }
      case "pad": {
        cyl(4.6, 4.6, 0.4, solid("#2a2448"));
        const h = new THREE.Mesh(new THREE.RingGeometry(2.4, 2.8, 32), glow(c, 2));
        h.rotation.x = -Math.PI / 2;
        h.position.y = 0.45;
        g.add(h);
        box(1.6, 3.5, 1.6, wall, 3.6, 0, -2.6); box(1.6, 0.4, 1.6, trim, 3.6, 3.5, -2.6);
        break;
      }
      default:
        box(5, 5, 4, wall);
    }

    function glass(col) {
      return new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.4, transparent: true, opacity: 0.55, roughness: 0.1, metalness: 0.3 });
    }
  }

  // ---------------------------------------------------------------- the crew
  makeAgent(a) {
    const pr = personaOf(a);
    const g = new THREE.Group();
    const look = wardrobe(a, "agent");
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.42, 0.7, 6, 12), finishMaterial(look.finish));
    body.position.y = 0.95;
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.46, 18, 12), new THREE.MeshStandardMaterial({ color: "#eef2ff", metalness: 0.3, roughness: 0.3 }));
    head.position.y = 1.85;
    const visor = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.2, 0.16), glow(pr.color, 2.2));
    visor.position.set(0, 1.9, 0.38);
    const belt = new THREE.Mesh(new THREE.TorusGeometry(0.44, 0.06, 6, 20), glow(pr.color, 1.2));
    belt.rotation.x = Math.PI / 2;
    belt.position.y = 0.95;
    const legs = [-0.18, 0.18].map((x) => {
      const l = new THREE.Mesh(new THREE.CapsuleGeometry(0.12, 0.35, 4, 8), solid("#9aa3d6", 0.5, 0.4));
      l.position.set(x, 0.3, 0);
      return l;
    });
    const pick = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 2.6, 8), new THREE.MeshBasicMaterial({ visible: false }));
    pick.position.y = 1.2;
    pick.userData.agent = a.id;
    this.clickables.push(pick);
    g.add(body, head, visor, belt, ...legs, pick);
    const el = document.createElement("div");
    el.className = "agent-tag";
    el.style.setProperty("--accent", pr.color);
    el.onclick = () => this.onAgent?.(a.id);
    const tag = new CSS2DObject(el);
    tag.position.y = 3.1;
    g.add(tag);
    const apparel = dress(look.wear, {   // their skin and apparel (skins.js), earned items included
      head: { parent: g, pos: [0, 2.28, 0], w: 0.9 },
      face: { parent: g, pos: [0, 1.9, 0.46], w: 0.85 },
      neck: { parent: g, pos: [0, 1.42, 0], w: 0.85 },
      chest: { parent: g, pos: [0.18, 1.12, 0.42], w: 0.8 },
      back: { parent: g, pos: [0, 1.4, -0.44], w: 0.8, rot: [0, Math.PI, 0] },
    }, pr.color);
    g.scale.setScalar(1.6);
    this.scene.add(g);
    const start = this.homeSpot(a);
    g.position.copy(start);
    return { id: a.id, group: g, legs, tag: el, persona: pr, path: [], wait: 0, speech: 0, line: "", data: a, walk: 0, apparel };
  }

  homeSpot(a) {
    const m = this.mods.get(moduleFor(a)) || this.mods.get("lounge");
    const jitter = ((parseInt(String(a.id).replace(/\D/g, "")) || 3) % 5 - 2) * 1.2;
    const side = new THREE.Vector3(Math.cos(m.angle + Math.PI / 2), 0, Math.sin(m.angle + Math.PI / 2));
    return m.door.clone().addScaledVector(side, jitter);
  }

  // waypoints along the roads: out to the ring road, around it, then in to the destination
  route(from, to) {
    const ang = (v) => Math.atan2(v.z, v.x);
    const rad = (v) => Math.hypot(v.x, v.z);
    const pts = [];
    const a0 = ang(from), a1 = ang(to);
    pts.push(new THREE.Vector3(Math.cos(a0) * RING_ROAD, 0, Math.sin(a0) * RING_ROAD));
    let d = a1 - a0;
    while (d > Math.PI) d -= Math.PI * 2;
    while (d < -Math.PI) d += Math.PI * 2;
    const steps = Math.max(1, Math.ceil(Math.abs(d) / 0.25));
    for (let i = 1; i <= steps; i++) {
      const a = a0 + (d * i) / steps;
      pts.push(new THREE.Vector3(Math.cos(a) * RING_ROAD, 0, Math.sin(a) * RING_ROAD));
    }
    if (Math.abs(rad(to) - RING_ROAD) > 0.5) pts.push(to.clone());
    else pts[pts.length - 1] = to.clone();
    if (Math.abs(rad(from) - RING_ROAD) < 0.5) pts.shift();
    return pts;
  }

  freeSpot(r) {
    const s = this.spots[Math.floor(Math.random() * this.spots.length)];
    const jit = (Math.random() - 0.5) * 0.12;
    return { pos: new THREE.Vector3(Math.cos(s.angle + jit) * s.r, 0, Math.sin(s.angle + jit) * s.r), name: s.name };
  }

  sync(list) {
    const seen = new Set();
    const busy = new Map();
    for (const a of list) {
      if (String(a.id).startsWith("BOT-")) continue;   // the trading bots live in their own buildings
      seen.add(a.id);
      let r = this.agents.get(a.id);
      if (!r) {
        r = this.makeAgent(a);
        this.agents.set(a.id, r);
      }
      r.data = a;
      r.persona = personaOf(a);
      const free = FREE.includes(a.status) || !a.current_task;
      if (!free) busy.set(moduleFor(a), (busy.get(moduleFor(a)) || 0) + 1);
      if (!free && r.mode !== "work") {           // a task came in: head to the department
        r.mode = "work";
        r.dest = "their desk";
        r.path = this.route(r.group.position, this.homeSpot(a));
        r.wait = 0;
        this.say(r, r.persona.work);
      } else if (free && r.mode !== "free") {
        r.mode = "free";
        r.wait = 1 + Math.random() * 4;
      }
      this.label(r);
    }
    for (const [id, r] of this.agents) {
      if (!seen.has(id)) {
        this.scene.remove(r.group);
        r.tag.remove();
        this.agents.delete(id);
      }
    }
    for (const m of this.mods.values()) {
      const n = busy.get(m.id) || 0;
      const crew = list.filter((a) => !String(a.id).startsWith("BOT-") && moduleFor(a) === m.id).length;
      m.busy = n;
      m.sign.querySelector("small").textContent = n ? `${n} working` : crew ? `${crew} crew` : "";
    }
  }

  label(r) {
    const a = r.data;
    const where = r.mode === "work" ? (a.current_task ? `working: ${String(a.current_task).slice(0, 40)}` : "at work")
      : r.path.length ? `walking to ${r.dest || "somewhere"}` : `hanging out at ${r.dest || "the plaza"}`;
    const html = `<b>${esc(r.persona.callsign)}</b><small>${esc(where)}</small>${r.speech > 0 ? `<i>“${esc(r.line)}”</i>` : ""}`;
    if (html !== r.html) { r.tag.innerHTML = html; r.html = html; }
  }

  say(r, lines) {
    r.line = lines[Math.floor(Math.random() * lines.length)];
    r.speech = 4;
  }

  update(dt, t) {
    for (const f of this.anim || []) f(t);
    if (this.fountain) this.fountain.scale.setScalar(1 + Math.sin(t * 3) * 0.04);
    this.tagClock = (this.tagClock || 0) + dt;
    const relabel = this.tagClock > 0.5;
    if (relabel) this.tagClock = 0;
    for (const r of this.agents.values()) {
      r.speech = Math.max(0, r.speech - dt);
      if (relabel) this.label(r);
      animateApparel(r.apparel, t);
      if (r.path.length) {
        const g = r.group, target = r.path[0];
        const dir = target.clone().sub(g.position);
        dir.y = 0;
        const dist = dir.length();
        const step = SPEED * dt;
        if (dist <= step) {
          g.position.copy(target);
          r.path.shift();
          if (!r.path.length && r.mode === "free") {
            r.wait = 6 + Math.random() * 12;
            if (Math.random() < 0.5) this.say(r, r.persona.idle);
          }
        } else {
          g.position.addScaledVector(dir.normalize(), step);
          g.rotation.y = Math.atan2(dir.x, dir.z);
        }
        r.walk += dt * 9;
        r.legs[0].position.z = Math.sin(r.walk) * 0.18;
        r.legs[1].position.z = -Math.sin(r.walk) * 0.18;
        g.position.y = Math.abs(Math.sin(r.walk)) * 0.08;
      } else {
        r.group.position.y = 0;
        r.legs[0].position.z = r.legs[1].position.z = 0;
        if (r.mode === "free") {
          r.wait -= dt;
          if (r.wait <= 0) {
            const s = this.freeSpot(r);
            r.dest = s.name;
            r.path = this.route(r.group.position, s.pos);
          }
        } else if (r.mode === "work") {
          r.group.rotation.y += Math.sin(t * 0.7 + r.group.position.x) * dt * 0.3;   // fidgeting at the desk
        }
      }
    }
  }
}

function esc(t) {
  return String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
