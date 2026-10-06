// Payout shuttles: real money in, flown between the city and the station. Shared by city.js and station3d.js.
// Every flight is a ledger entry (Treasury.flights): a Lucid payout launches from the city's vault and docks at
// the station's treasury; a store sale flies from the marketplace to the treasury. Nothing here is made up.
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";

const COLORS = { payout: "#3dffa2", sale: "#ffd84d" };

export function makeShuttle(kind = "payout") {
  const color = new THREE.Color(COLORS[kind] || COLORS.payout);
  const g = new THREE.Group();
  const hull = new THREE.MeshStandardMaterial({ color: "#e9ecff", metalness: 0.4, roughness: 0.35, emissive: "#3a3f70", emissiveIntensity: 0.4 });
  const trim = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 1.4 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.55, 2.2, 6, 14), hull);
  body.rotation.x = Math.PI / 2;   // nose along +z
  g.add(body);
  const canopy = new THREE.Mesh(new THREE.SphereGeometry(0.42, 14, 10, 0, Math.PI * 2, 0, Math.PI / 2), new THREE.MeshStandardMaterial({ color: "#5ee7ff", emissive: "#2aa9ff", emissiveIntensity: 1.2, transparent: true, opacity: 0.85 }));
  canopy.position.set(0, 0.32, 0.7);
  g.add(canopy);
  const wing = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.1, 0.9), trim);
  wing.position.set(0, -0.1, -0.3);
  g.add(wing);
  const fin = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.9, 0.7), trim);
  fin.position.set(0, 0.55, -1.1);
  g.add(fin);
  const flame = new THREE.Mesh(new THREE.ConeGeometry(0.42, 1.6, 12, 1, true), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false }));
  flame.rotation.x = -Math.PI / 2;
  flame.position.z = -2.1;
  g.add(flame);
  g.userData.flame = flame;
  return g;
}

// A flight along an arc from `from` to `to`; call update(dt) every frame until it returns false.
export class Flight {
  constructor(scene, kind, amount, from, to, { scale = 1, height = 30, seconds = 7, label = true, onArrive } = {}) {
    this.scene = scene;
    this.ship = makeShuttle(kind);
    this.ship.scale.setScalar(scale);
    this.from = from.clone();
    this.to = to.clone();
    this.mid = from.clone().lerp(to, 0.5);
    this.mid.y = Math.max(from.y, to.y) + height;
    this.t = 0;
    this.seconds = seconds;
    this.onArrive = onArrive;
    this.trail = [];
    this.trailMat = new THREE.MeshBasicMaterial({ color: COLORS[kind] || COLORS.payout, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false });
    this.trailGeo = new THREE.SphereGeometry(0.22 * scale, 6, 4);
    if (label) {
      const el = document.createElement("div");
      el.className = `shuttle-tag ${kind}`;
      el.textContent = `${kind === "payout" ? "🚀 payout" : "🛍️ sale"} +$${Math.round(amount).toLocaleString()}`;
      this.tag = new CSS2DObject(el);
      this.tag.position.set(0, 2.2, 0);
      this.ship.add(this.tag);
    }
    this.ship.position.copy(this.from);
    scene.add(this.ship);
  }

  point(t, out = new THREE.Vector3()) {   // quadratic bezier
    const a = (1 - t) * (1 - t), b = 2 * (1 - t) * t, c = t * t;
    return out.set(a * this.from.x + b * this.mid.x + c * this.to.x, a * this.from.y + b * this.mid.y + c * this.to.y,
      a * this.from.z + b * this.mid.z + c * this.to.z);
  }

  update(dt) {
    this.t = Math.min(1, this.t + dt / this.seconds);
    const k = this.t * this.t * (3 - 2 * this.t);   // ease in and out: lift off, cruise, dock
    const p = this.point(k), ahead = this.point(Math.min(1, k + 0.01));
    this.ship.position.copy(p);
    if (ahead.distanceToSquared(p) > 1e-6) this.ship.lookAt(ahead);
    const f = this.ship.userData.flame;
    f.scale.set(1, 0.8 + Math.random() * 0.5, 1);
    if (Math.random() < 0.6) {   // exhaust trail
      const s = new THREE.Mesh(this.trailGeo, this.trailMat);
      s.position.copy(p);
      s.userData.life = 1;
      this.scene.add(s);
      this.trail.push(s);
    }
    for (let i = this.trail.length - 1; i >= 0; i--) {
      const s = this.trail[i];
      s.userData.life -= dt * 0.9;
      s.scale.setScalar(Math.max(0.01, s.userData.life));
      if (s.userData.life <= 0) { this.scene.remove(s); this.trail.splice(i, 1); }
    }
    if (this.t >= 1 && !this.arrived) {
      this.arrived = true;
      this.scene.remove(this.ship);
      if (this.tag) this.tag.element.remove();
      this.onArrive?.();
    }
    return !(this.arrived && this.trail.length === 0);
  }
}

// Which ledger flights are new since the page loaded (the first look only marks them seen, so a reload
// doesn't re-fly old payouts). `?shuttle=payout` or `?shuttle=sale` previews one.
export function newFlights(seen, flights) {
  const first = seen.size === 0 && !seen.primed;
  seen.primed = true;
  const fresh = [];
  for (const f of flights || []) {
    if (!seen.has(f.id)) { seen.add(f.id); if (!first) fresh.push(f); }
  }
  const preview = new URLSearchParams(location.search).get("shuttle");
  if (first && preview) fresh.push({ id: "preview", kind: preview === "sale" ? "sale" : "payout", amount: preview === "sale" ? 27 : 900, note: "preview" });
  return fresh.reverse();   // oldest first
}
