// A bot's streamer room: the little robot at its desk, three monitors (live chart
// with its FFVG/IFFVG zones and PROC, P&L, stream chat), its personal setup, and
// emotions when it wins, loses, waits or gets sent home.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { wardrobe, dress, finishMaterial, animateApparel } from "./skins.js";

const W = 640, H = 400;   // monitor canvas resolution

// The more a bot has made in its career (best-ever lifetime P&L), the fancier its setup.
export const GADGETS = [
  [0, "starter", "Starter desk"],
  [500, "rgb", "RGB racing chair"],
  [1000, "mon4", "4th monitor"],
  [2500, "hex", "Hexagon LED wall"],
  [5000, "trophy", "Gold trophy + neon $"],
  [10000, "wall", "Wall of screens"],
  [25000, "aquarium", "Aquarium"],
  [50000, "gold", "Gold-plated chassis"],
  [100000, "penthouse", "Penthouse view"],
];
export const tierOf = (career) => GADGETS.filter(([need]) => (career || 0) >= need).length - 1;
const CHAT_NAMES = ["pip_hunter", "fvg_fiend", "nq_nana", "tapqueen", "macre_stan", "wickwatcher", "scalpdad", "es_enjoyer", "0dte_dan", "pointer_pete"];

function canvasTex(w, h) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return { c, g: c.getContext("2d"), tex };
}

function textSprite(text, color = "#fff", size = 64) {
  const { c, g, tex } = canvasTex(256, 128);
  g.font = `bold ${size}px Inter, sans-serif`;
  g.textAlign = "center"; g.textBaseline = "middle";
  g.fillStyle = color; g.shadowColor = color; g.shadowBlur = 12;
  g.fillText(text, 128, 64);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  s.scale.set(0.8, 0.4, 1);
  return s;
}

export class Room {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    container.appendChild(this.renderer.domElement);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.minDistance = 3;
    this.controls.maxDistance = 9;
    this.controls.maxPolarAngle = Math.PI * 0.55;
    this.controls.minAzimuthAngle = -Math.PI * 0.45;
    this.controls.maxAzimuthAngle = Math.PI * 0.45;
    this.clock = new THREE.Clock();
    this.particles = [];
    this.chat = [];
    this.mood = "focused";
    this.moodUntil = 0;
    this.say = null;
    this.open = false;
    addEventListener("resize", () => this.resize());
    new ResizeObserver(() => this.resize()).observe(container);
  }

  // ---------------------------------------------------------------- build
  build(bot, ctx = {}) {
    this.bot = bot;
    this.kind = ctx.kind === "agent" ? "agent" : "bot";   // a station agent's room: screens show its work, not a chart
    this.look = this.kind === "agent" ? wardrobe(bot.agent || bot, "agent", ctx) : wardrobe(bot, "bot", ctx);
    const p = bot.persona || {};
    const color = new THREE.Color(bot.color);
    const tier = (this.tier = tierOf(bot.career_best));
    const has = (key) => GADGETS.findIndex((g) => g[1] === key) <= tier;
    const scene = (this.scene = new THREE.Scene());
    scene.background = new THREE.Color("#0b0820");
    scene.fog = new THREE.Fog("#0b0820", 8, 18);

    scene.add(new THREE.HemisphereLight("#b8a8ff", "#100820", 0.7));
    const key = new THREE.PointLight(color, 25, 12);
    key.position.set(-2, 3.2, 2);
    scene.add(key);
    this.monitorLight = new THREE.PointLight("#9fd8ff", 8, 5);
    this.monitorLight.position.set(0, 1.6, -0.6);
    scene.add(this.monitorLight);

    // room shell
    const std = (c, e = 0) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: e, roughness: 0.85 });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(10, 8), std("#1a1438"));
    floor.rotation.x = -Math.PI / 2;
    scene.add(floor);
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(10, 5), std("#191233"));
    wall.position.set(0, 2.5, -2.2);
    scene.add(wall);
    const side = new THREE.Mesh(new THREE.PlaneGeometry(8, 5), std("#151030"));
    side.position.set(-4, 2.5, 1.8);
    side.rotation.y = Math.PI / 2;
    scene.add(side);
    const rug = new THREE.Mesh(new THREE.CircleGeometry(1.6, 40), std(color.clone().multiplyScalar(0.35)));
    rug.rotation.x = -Math.PI / 2;
    rug.position.set(0, 0.01, 0.6);
    scene.add(rug);
    // LED strips in the bot's color
    for (const y of [0.08, 4.4]) {
      const led = new THREE.Mesh(new THREE.BoxGeometry(10, 0.05, 0.05), new THREE.MeshBasicMaterial({ color }));
      led.position.set(0, y, -2.15);
      scene.add(led);
    }
    // neon name sign
    const sign = canvasTex(1024, 256);
    sign.g.font = "bold 120px 'Press Start 2P', monospace";
    sign.g.textAlign = "center"; sign.g.textBaseline = "middle";
    sign.g.shadowColor = bot.color; sign.g.shadowBlur = 40; sign.g.fillStyle = bot.color;
    sign.g.fillText(p.handle || bot.name, 512, 128, 980);
    sign.tex.needsUpdate = true;
    const signMesh = new THREE.Mesh(new THREE.PlaneGeometry(3.6, 0.9), new THREE.MeshBasicMaterial({ map: sign.tex, transparent: true }));
    signMesh.position.set(0, 3.7, -2.15);
    scene.add(signMesh);
    // LIVE sign
    this.liveSign = textSprite("● LIVE", "#ff4d6d", 56);
    this.liveSign.position.set(2.6, 3.7, -2.1);
    scene.add(this.liveSign);
    // ring light
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.45, 0.04, 12, 48), new THREE.MeshBasicMaterial({ color: "#fff6e0" }));
    ring.position.set(-2.0, 2.2, 0.5);
    ring.rotation.y = 0.7;
    scene.add(ring);
    const stand = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 1.8), std("#333"));
    stand.position.set(-2.0, 0.9, 0.5);
    scene.add(stand);

    // desk + chair
    const desk = new THREE.Mesh(new THREE.BoxGeometry(3.4, 0.1, 1.1), std("#2b2448"));
    desk.position.set(0, 0.95, -0.9);
    scene.add(desk);
    for (const x of [-1.6, 1.6]) {
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.95, 0.9), std("#221c3a"));
      leg.position.set(x, 0.47, -0.9);
      scene.add(leg);
    }
    const kbMat = std(color, has("rgb") ? 0.9 : 0.35);
    if (has("rgb")) kbMat.userData.rgb = true;
    this.rgbMats = kbMat.userData.rgb ? [kbMat] : [];
    const kb = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.04, 0.3), kbMat);
    kb.position.set(0, 1.02, -0.55);
    scene.add(kb);
    const mouse = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), std(color, 0.6));
    mouse.scale.set(1, 0.5, 1.4);
    mouse.position.set(0.65, 1.03, -0.55);
    scene.add(mouse);
    const chairMat = has("gold") ? new THREE.MeshStandardMaterial({ color: "#ffcf40", metalness: 0.9, roughness: 0.25 })
      : std(color.clone().multiplyScalar(0.5), has("rgb") ? 0.5 : 0);
    if (has("rgb") && !has("gold")) { chairMat.userData.rgb = true; this.rgbMats.push(chairMat); }
    const chair = new THREE.Group();
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.12, 0.7), chairMat);
    seat.position.y = 0.55;
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.8, has("rgb") ? 1.3 : 1.0, 0.1), chairMat);
    back.position.set(0, 1.1, 0.33);
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.5), std("#444"));
    post.position.y = 0.28;
    chair.add(seat, back, post);
    chair.position.set(0, 0, 0.35);
    scene.add(chair);
    this.chair = chair;

    // three monitors on the desk
    this.screens = {};
    const mons = [["chart", 0, 1.25, 0], ["pnl", -1.15, 0.85, 0.35], ["chat", 1.15, 0.85, -0.35]];
    for (const [name, x, w, rot] of mons) {
      const ct = canvasTex(W, H);
      const scr = new THREE.Mesh(new THREE.PlaneGeometry(w, w * H / W), new THREE.MeshBasicMaterial({ map: ct.tex }));
      const bezel = new THREE.Mesh(new THREE.BoxGeometry(w + 0.06, w * H / W + 0.06, 0.04), std("#0d0b18"));
      const g = new THREE.Group();
      scr.position.z = 0.025;
      g.add(bezel, scr);
      const neck = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.35, 0.04), std("#222"));
      neck.position.y = -(w * H / W) / 2 - 0.15;
      g.add(neck);
      g.position.set(x, 1.55 + (name === "chart" ? 0.12 : 0), -1.2 + Math.abs(x) * 0.15);
      g.rotation.y = rot;
      scene.add(g);
      this.screens[name] = ct;
    }

    this.addGadgets(scene, color, has);

    // personal props
    const props = p.props || [];
    const spots = [[-1.45, 1.0, -1.1], [1.45, 1.0, -1.15], [-3.2, 0, -1.6], [3.2, 0, -1.6]];
    props.slice(0, 4).forEach((kind, i) => scene.add(this.prop(kind, color, spots[i], i >= 2)));
    // poster with the bot's vibe
    const poster = canvasTex(512, 640);
    const pg = poster.g;
    const grad = pg.createLinearGradient(0, 0, 0, 640);
    grad.addColorStop(0, bot.color); grad.addColorStop(1, "#1b0f6b");
    pg.fillStyle = grad; pg.fillRect(0, 0, 512, 640);
    pg.fillStyle = "#fff"; pg.font = "bold 54px Inter, sans-serif"; pg.textAlign = "center";
    pg.fillText(bot.underlying || bot.name.split(" ")[0], 256, 120);
    pg.font = "italic 34px Inter, sans-serif";
    wrap(pg, `"${(p.win || ["trust the PROC"])[0]}"`, 256, 260, 440, 44);
    pg.font = "26px Inter, sans-serif"; pg.fillStyle = "rgba(255,255,255,.8)";
    wrap(pg, p.vibe || "", 256, 520, 440, 32);
    poster.tex.needsUpdate = true;
    const posterMesh = new THREE.Mesh(new THREE.PlaneGeometry(1.0, 1.25), new THREE.MeshBasicMaterial({ map: poster.tex }));
    posterMesh.position.set(-3.95, 2.4, 0.2);
    posterMesh.rotation.y = Math.PI / 2;
    scene.add(posterMesh);

    // the robot
    this.robot = this.makeRobot(color, has("gold"), this.look.finish);
    // apparel: signature look + what this bot has earned (skins.js)
    this.apparel = dress(this.look.wear, {
      head: { parent: this.head, pos: [0, 0.24, 0], w: 0.62 },
      face: { parent: this.head, pos: [0, 0.04, 0.27], w: 0.62 },
      neck: { parent: this.robot, pos: [0, 0.82, 0], w: 0.6, rot: [0, Math.PI, 0] },
      chest: { parent: this.robot, pos: [0.13, 0.62, -0.3], w: 0.6, rot: [0, Math.PI, 0] },
      back: { parent: this.robot, pos: [0, 0.85, 0.3], w: 0.6 },
    }, bot.color);
    this.robot.position.set(0, 0.62, 0.25);
    this.robot.scale.setScalar(0.82);
    scene.add(this.robot);

    // speech bubble (DOM, positioned over the robot)
    const narrow = innerWidth < innerHeight;
    this.camera.position.set(narrow ? 3.3 : 3.2, narrow ? 3.9 : 2.5, narrow ? 3.1 : 3.0);   // three-quarter view: robot + monitors
    this.controls.target.set(-0.1, 1.45, -0.7);
    this.resize();
  }

  prop(kind, color, [x, y, z], floor) {
    const g = new THREE.Group();
    const m = (c, e = 0) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: e });
    if (kind === "plant") {
      const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.09, 0.18, 16), m("#7a4b2a"));
      g.add(pot);
      for (let i = 0; i < 5; i++) {
        const leaf = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.35, 6), m("#3fbf6a", 0.2));
        leaf.position.set(Math.cos(i) * 0.05, 0.22, Math.sin(i) * 0.05);
        leaf.rotation.set(Math.sin(i) * 0.4, 0, Math.cos(i) * 0.4);
        g.add(leaf);
      }
      if (floor) g.scale.setScalar(2.4);
    } else if (kind === "cat") {
      const body = new THREE.Mesh(new THREE.SphereGeometry(0.14, 16, 12), m("#f2a65a"));
      body.scale.set(1.3, 0.8, 1);
      const head = new THREE.Mesh(new THREE.SphereGeometry(0.09, 16, 12), m("#f2a65a"));
      head.position.set(0.16, 0.08, 0);
      for (const dz of [-0.04, 0.04]) {
        const ear = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.06, 4), m("#f2a65a"));
        ear.position.set(0.17, 0.17, dz);
        g.add(ear);
      }
      g.add(body, head);
      g.userData.spin = true;
      if (floor) g.scale.setScalar(1.6);
    } else if (kind === "lava") {
      const base = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.09, 0.1, 12), m("#333"));
      const glass = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.2, 6, 12), m(color, 1.2));
      glass.position.y = 0.2;
      g.add(base, glass);
      g.userData.glow = glass;
      if (floor) g.scale.setScalar(2.5);
    } else if (kind === "trophy") {
      const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.05, 0.16, 16), m("#ffd34d", 0.5));
      cup.position.y = 0.18;
      const base = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.06, 0.14), m("#5a4300"));
      g.add(cup, base);
      if (floor) g.scale.setScalar(2.2);
    } else if (kind === "books") {
      ["#ff5c8a", "#3dd6ff", "#ffd34d", "#43f0a0"].forEach((c, i) => {
        const b = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.26, 0.2), m(c));
        b.position.set(i * 0.07, 0.13, 0);
        g.add(b);
      });
      if (floor) g.scale.setScalar(2.2);
    } else if (kind === "candle") {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.12, 12), m("#f5e6c8"));
      const f = new THREE.Mesh(new THREE.ConeGeometry(0.025, 0.07, 8), new THREE.MeshBasicMaterial({ color: "#ffb347" }));
      f.position.y = 0.1;
      g.add(c, f);
      g.userData.flame = f;
      if (floor) g.scale.setScalar(2);
    }
    g.position.set(x, y, z);
    return g;
  }

  addGadgets(scene, color, has) {
    const std = (c, e = 0) => new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: e, roughness: 0.6 });
    this.fish = [];
    this.hexes = [];
    if (has("mon4")) {   // a 4th screen above the main one: career + market ticker
      const ct = canvasTex(W, H / 2);
      const g = new THREE.Group();
      const scr = new THREE.Mesh(new THREE.PlaneGeometry(1.25, 0.39), new THREE.MeshBasicMaterial({ map: ct.tex }));
      const bezel = new THREE.Mesh(new THREE.BoxGeometry(1.31, 0.45, 0.04), std("#0d0b18"));
      scr.position.z = 0.025;
      g.add(bezel, scr);
      g.position.set(0, 2.42, -1.25);
      g.rotation.x = 0.12;
      scene.add(g);
      this.screens.top = ct;
    }
    if (has("hex")) {   // hexagon light panels on the wall
      const spots = [[-2.6, 2.6], [-2.2, 2.85], [-2.2, 2.35], [-1.8, 2.6], [2.0, 2.3], [2.4, 2.55], [2.4, 2.05]];
      spots.forEach(([x, y], i) => {
        const m = new THREE.MeshBasicMaterial({ color });
        const hex = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.03, 6), m);
        hex.rotation.x = Math.PI / 2;
        hex.position.set(x, y, -2.17);
        hex.userData.phase = i * 0.7;
        scene.add(hex);
        this.hexes.push(hex);
      });
    }
    if (has("trophy")) {
      const g = new THREE.Group();
      const gold = new THREE.MeshStandardMaterial({ color: "#ffcf40", emissive: "#a87400", emissiveIntensity: 0.5, metalness: 0.9, roughness: 0.2 });
      const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.07, 0.26, 20), gold);
      cup.position.y = 0.36;
      const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.14), gold);
      stem.position.y = 0.17;
      const base = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.08, 0.22), std("#3a2a00"));
      base.position.y = 0.05;
      for (const s of [-1, 1]) {
        const handle = new THREE.Mesh(new THREE.TorusGeometry(0.07, 0.015, 8, 16), gold);
        handle.position.set(0.17 * s, 0.38, 0);
        g.add(handle);
      }
      g.add(cup, stem, base);
      g.position.set(1.3, 1.0, -0.65);
      scene.add(g);
      const dollar = textSprite("$", "#4dff9a", 110);
      dollar.scale.set(1.2, 0.6, 1);
      dollar.position.set(-2.4, 3.4, -2.1);
      scene.add(dollar);
    }
    if (has("wall")) {   // two big screens on the side wall
      this.screens.wall = canvasTex(W, H);
      for (const z of [-0.9, 0.9]) {
        const scr = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.94), new THREE.MeshBasicMaterial({ map: this.screens.wall.tex }));
        scr.position.set(-3.97, 2.8, z + 0.2);
        scr.rotation.y = Math.PI / 2;
        scene.add(scr);
      }
    }
    if (has("aquarium")) {
      const tank = new THREE.Group();
      const glass = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.75, 0.5),
        new THREE.MeshStandardMaterial({ color: "#3aa8ff", emissive: "#0a4d8c", emissiveIntensity: 0.6, transparent: true, opacity: 0.45 }));
      glass.position.y = 0.8;
      const stand = new THREE.Mesh(new THREE.BoxGeometry(1.35, 0.42, 0.55), std("#1c1530"));
      stand.position.y = 0.21;
      tank.add(glass, stand);
      ["#ff8a3d", "#ffd34d", "#ff5c8a", "#7ee8ff"].forEach((c, i) => {
        const fish = new THREE.Mesh(new THREE.ConeGeometry(0.04, 0.12, 8), std(c, 0.5));
        fish.rotation.z = Math.PI / 2;
        fish.userData = { y: 0.65 + i * 0.08, speed: 0.5 + i * 0.2, phase: i };
        tank.add(fish);
        this.fish.push(fish);
      });
      tank.position.set(-3.2, 0, 1.6);
      tank.rotation.y = Math.PI / 2;
      scene.add(tank);
    }
    if (has("penthouse")) {   // a window over the skyline
      const v = canvasTex(1024, 512);
      const g = v.g;
      const sky = g.createLinearGradient(0, 0, 0, 512);
      sky.addColorStop(0, "#0a0430"); sky.addColorStop(1, "#4b1d7a");
      g.fillStyle = sky; g.fillRect(0, 0, 1024, 512);
      for (let i = 0; i < 60; i++) { g.fillStyle = "#fff"; g.fillRect(Math.random() * 1024, Math.random() * 200, 2, 2); }
      for (let x = 0; x < 1024; x += 40 + Math.random() * 30) {
        const h = 120 + Math.random() * 260, w = 30 + Math.random() * 40;
        g.fillStyle = "#120a2e"; g.fillRect(x, 512 - h, w, h);
        for (let wy = 512 - h + 8; wy < 500; wy += 14) for (let wx = x + 5; wx < x + w - 5; wx += 10)
          if (Math.random() < 0.4) { g.fillStyle = "#ffcf6b"; g.fillRect(wx, wy, 4, 6); }
      }
      v.tex.needsUpdate = true;
      const win = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 1.6), new THREE.MeshBasicMaterial({ map: v.tex }));
      win.position.set(0, 2.55, -2.18);
      scene.add(win);
      const frame = new THREE.Mesh(new THREE.BoxGeometry(3.3, 1.7, 0.02), std("#0b0a14"));
      frame.position.set(0, 2.55, -2.19);
      scene.add(frame);
    }
  }

  makeRobot(color, gold = false, finish = "chrome") {
    const r = new THREE.Group();
    const metal = finishMaterial(gold ? "gold" : finish);
    const accent = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.6 });
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.28, 0.35, 8, 16), metal);
    body.position.y = 0.45;
    const belly = new THREE.Mesh(new THREE.CircleGeometry(0.12, 24), accent);
    belly.position.set(0, 0.48, -0.285);
    belly.rotation.y = Math.PI;
    const headG = new THREE.Group();
    headG.position.y = 1.05;
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.48, 0.5), metal);
    // the face is a little screen on the side facing the camera (and one facing the monitors)
    this.face = canvasTex(256, 192);
    const faceMat = new THREE.MeshBasicMaterial({ map: this.face.tex });
    const faceFront = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 0.36), faceMat);
    faceFront.position.z = 0.256;
    const headset = new THREE.Mesh(new THREE.TorusGeometry(0.33, 0.035, 8, 32, Math.PI), accent);
    headset.rotation.z = 0;
    headset.position.y = 0.05;
    headset.rotation.y = Math.PI / 2;
    const mic = new THREE.Mesh(new THREE.SphereGeometry(0.04, 8, 8), accent);
    mic.position.set(0.3, -0.15, 0.18);
    const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.22), metal);
    antenna.position.y = 0.35;
    this.bulb = new THREE.Mesh(new THREE.SphereGeometry(0.06, 16, 12), new THREE.MeshBasicMaterial({ color }));
    this.bulb.position.y = 0.48;
    headG.add(head, faceFront, headset, mic, antenna, this.bulb);
    // arms pivot at the shoulders
    this.arms = [];
    for (const s of [-1, 1]) {
      const pivot = new THREE.Group();
      pivot.position.set(0.33 * s, 0.7, 0);
      const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.32, 6, 10), metal);
      arm.position.y = -0.2;
      const hand = new THREE.Mesh(new THREE.SphereGeometry(0.075, 12, 10), accent);
      hand.position.y = -0.42;
      pivot.add(arm, hand);
      r.add(pivot);
      this.arms.push(pivot);
    }
    r.add(body, belly, headG);
    this.head = headG;
    r.rotation.y = Math.PI;   // facing the monitors; we see its back... turn the head to the camera
    // the robot sits facing the desk, but turns toward the camera when it reacts
    return r;
  }

  // ---------------------------------------------------------------- emotions
  setMood(mood, seconds = 0, line = null) {
    this.mood = mood;
    this.moodUntil = seconds ? this.clock.elapsedTime + seconds : 0;
    if (line) this.speak(line);
  }

  baseMood() {
    const b = this.bot;
    if (!b) return "focused";
    if (b.status === "disabled") return "asleep";
    if (b.status === "walked") return "away";
    if (b.status === "stopped") return "defeated";
    if (b.status === "off_duty") return "chill";
    if (b.status === "in_trade") return b.unrealized >= 0 ? "confident" : "nervous";
    if (this.data?.waiting) return "thinking";
    return "focused";
  }

  speak(text) {
    const el = document.getElementById("room-bubble");
    if (!el) return;
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(this._sayT);
    this._sayT = setTimeout(() => el.classList.add("hidden"), 4500);
  }

  onEvent(ev) {
    const p = this.bot?.persona || {};
    const pick = (a, d) => (a && a.length ? a[Math.floor(Math.random() * a.length)] : d);
    if (ev.type === "trade_trim") {
      this.setMood("happy", 4, `trimmed ${ev.qty} at the zone (+$${Math.round(ev.pnl)}) · runner on`);
      this.burst("coin", 15);
      this.chatSay(["paid ✂️", "pay yourself", "trim and ride", "smart trim"], 2);
    } else if (ev.type === "trade_close") {
      ev = { ...ev, pnl: ev.trade_pnl ?? ev.pnl };   // the whole trade, trims included
      if (ev.pnl >= 0) {
        this.setMood("ecstatic", 7, `${pick(p.win, "LET'S GO")} (+$${Math.round(ev.pnl)})`);
        this.burst("coin", 40);
        this.chatSay(["W", "LETS GOOO 🔥", `+$${Math.round(ev.pnl)} 💰`, "PROC KING", "printer go brrr", "EZ"], 5);
      } else {
        this.setMood("upset", 7, `${pick(p.loss, "ouch")} (-$${Math.round(-ev.pnl)})`);
        this.burst("rain", 30);
        this.chatSay(["F", "it's over 💀", "trust the process", "pointer against was right", "unlucky", "L"], 4);
      }
    } else if (ev.type === "trade_open") {
      this.setMood("hyped", 3, `${ev.contract.split(" ")[1] === "LONG" ? "LONG" : "SHORT"} ×${ev.qty}, PROC confirmed`);
      this.chatSay(["here we go 👀", "send it", "MES confirmed?", "PROC spotted", "LFG"], 3);
    } else if (ev.type === "trade_add") {
      this.setMood("hyped", 3, `adding! ${ev.total} contracts`);
      this.chatSay(["SIZE UP 💪", "pyramid time", "he's adding 😳"], 2);
    } else if (ev.type === "account_halt") {
      const good = /cap|target/.test(ev.reason);
      this.setMood(good ? "chill" : "defeated", 8, good ? "done for the day, see you tomorrow chat" : "account says stop. respecting it.");
    }
  }

  burst(kind, n) {
    for (let i = 0; i < n; i++) {
      const m = kind === "coin"
        ? new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.015, 12), new THREE.MeshStandardMaterial({ color: "#ffd34d", emissive: "#ffb300", emissiveIntensity: 0.8, metalness: 0.6 }))
        : new THREE.Mesh(new THREE.SphereGeometry(0.025, 6, 6), new THREE.MeshBasicMaterial({ color: "#7fb8ff" }));
      const rp = this.robot.position;
      m.position.set(rp.x + (Math.random() - 0.5) * 1.4, kind === "coin" ? 1.8 : 2.7, rp.z + (Math.random() - 0.5) * 0.6);
      const v = kind === "coin"
        ? new THREE.Vector3((Math.random() - 0.5) * 2, 2 + Math.random() * 2, (Math.random() - 0.5) * 1.5)
        : new THREE.Vector3(0, -1.5 - Math.random(), 0);
      this.scene.add(m);
      this.particles.push({ m, v, life: kind === "coin" ? 2.2 : 1.6 + Math.random(), delay: Math.random() * (kind === "coin" ? 0.4 : 1.5), kind });
    }
    if (kind === "rain") {   // a little storm cloud over its head
      const cloud = new THREE.Group();
      for (let i = 0; i < 5; i++) {
        const puff = new THREE.Mesh(new THREE.SphereGeometry(0.16 + Math.random() * 0.06, 12, 10), new THREE.MeshStandardMaterial({ color: "#59607a" }));
        puff.position.set((i - 2) * 0.16, Math.random() * 0.06, (Math.random() - 0.5) * 0.1);
        cloud.add(puff);
      }
      cloud.position.set(this.robot.position.x, 2.8, this.robot.position.z);
      this.scene.add(cloud);
      this.particles.push({ m: cloud, v: new THREE.Vector3(), life: 4, delay: 0, kind: "cloud" });
    }
  }

  drawFace(mood, t) {
    const { g, tex } = this.face;
    g.fillStyle = "#06121f";
    g.fillRect(0, 0, 256, 192);
    const c = { ecstatic: "#ffd34d", hyped: "#ffd34d", confident: "#4dff9a", upset: "#ff5470", defeated: "#ff8aa0",
                nervous: "#9fd8ff", thinking: "#c7a8ff", chill: "#4dffe0", asleep: "#5a6a8a", away: "#5a6a8a", focused: "#7ee8ff" }[mood] || "#7ee8ff";
    g.strokeStyle = g.fillStyle = c;
    g.lineWidth = 12; g.lineCap = "round";
    g.shadowColor = c; g.shadowBlur = 14;
    const blink = mood !== "asleep" && Math.sin(t * 1.3) > 0.985;
    const eye = (x, kind) => {
      g.beginPath();
      if (blink || kind === "line") { g.moveTo(x - 22, 78); g.lineTo(x + 22, 78); g.stroke(); return; }
      if (kind === "happy") { g.arc(x, 88, 24, Math.PI * 1.1, Math.PI * 1.9); g.stroke(); return; }
      if (kind === "x") { g.moveTo(x - 18, 60); g.lineTo(x + 18, 96); g.moveTo(x + 18, 60); g.lineTo(x - 18, 96); g.stroke(); return; }
      if (kind === "star") { star(g, x, 78, 26); return; }
      if (kind === "sad") { g.moveTo(x - 22, 70); g.lineTo(x + 22, 84); g.stroke(); return; }
      if (kind === "shades") { g.fillRect(x - 32, 62, 64, 30); return; }
      const look = mood === "focused" ? Math.sin(t * 0.7) * 8 : 0;
      g.fillRect(x - 13 + look, 58, 26, 40);
    };
    const eyes = { ecstatic: "star", hyped: "happy", confident: "happy", upset: "x", defeated: "sad", nervous: "dot",
                   thinking: "dot", chill: "shades", asleep: "line", away: "line", focused: "dot" }[mood];
    eye(84, eyes); eye(172, eyes);
    if (mood === "chill") { g.fillRect(84, 70, 88, 8); }
    g.beginPath();
    if (["ecstatic", "hyped", "confident", "chill"].includes(mood)) { g.arc(128, 120, mood === "ecstatic" ? 38 : 28, 0.15 * Math.PI, 0.85 * Math.PI); }
    else if (["upset", "defeated"].includes(mood)) { g.arc(128, 168, 30, 1.2 * Math.PI, 1.8 * Math.PI); }
    else if (mood === "nervous") { for (let x = 92; x <= 164; x += 12) g.lineTo(x, 140 + ((x / 12) % 2 ? 8 : -8)); }
    else if (mood === "thinking") { g.moveTo(108, 145); g.lineTo(150, 138); }
    else if (mood === "asleep") { g.arc(128, 148, 10, 0, Math.PI * 2); }
    else { g.moveTo(104, 142); g.lineTo(152, 142); }
    g.stroke();
    if (mood === "nervous") {   // sweat drop
      g.fillStyle = "#7fd0ff"; g.beginPath(); g.arc(222, 60 + (t * 40) % 60, 10, 0, Math.PI * 2); g.fill();
    }
    g.shadowBlur = 0;
    tex.needsUpdate = true;
  }

  // ---------------------------------------------------------------- monitors
  update(bot, data) {
    if (this.tier !== undefined && tierOf(bot.career_best) > this.tier) {   // new gadget unlocked: rebuild the room
      const label = GADGETS[tierOf(bot.career_best)][2];
      this.build(bot);
      this.setMood("ecstatic", 8, `NEW GADGET UNLOCKED: ${label}!`);
      this.burst("coin", 60);
      this.chatSay([`${label} 😍`, "SETUP UPGRADE", "W streamer", "rich bot energy 💸"], 5);
    }
    this.bot = bot;
    if (data) this.data = data;
    this.drawChart();
    this.drawPnl();
    this.drawChat();
  }

  drawAgentBoard() {
    const a = this.bot.agent || {}, { g, tex } = this.screens.chart;
    g.fillStyle = "#070b14"; g.fillRect(0, 0, W, H);
    g.fillStyle = this.bot.color; g.font = "bold 24px Inter, sans-serif";
    g.fillText("CURRENT TASK", 20, 40);
    g.fillStyle = "#e8ecff"; g.font = "bold 30px Inter, sans-serif";
    const words = String(a.current_task || "Free time: out exploring the city").split(" ");
    let line = "", y = 92;
    for (const w of words) {
      if (g.measureText(line + w).width > W - 40) { g.fillText(line, 20, y); line = ""; y += 40; if (y > H - 80) break; }
      line += w + " ";
    }
    g.fillText(line, 20, y);
    g.fillStyle = "#7f88b5"; g.font = "20px Inter, sans-serif";
    g.fillText(a.current_venture ? `venture ${a.current_venture}` : (a.role || ""), 20, H - 30);
    tex.needsUpdate = true;
  }

  drawAgentCard() {
    const b = this.bot, a = b.agent || {}, { g, tex } = this.screens.pnl;
    g.fillStyle = "#0a0716"; g.fillRect(0, 0, W, H);
    g.fillStyle = b.color; g.font = "bold 34px Inter, sans-serif";
    g.fillText(b.name, 24, 56);
    g.fillStyle = "#9a93c8"; g.font = "20px Inter, sans-serif";
    g.fillText(`@${b.persona?.handle || ""} · ${(a.status || "").toLowerCase()}`, 24, 90);
    g.fillStyle = "#cfc8ff"; g.font = "bold 22px Inter, sans-serif";
    g.fillText(a.role || "", 24, 140);
    g.fillStyle = "#4dff9a"; g.font = "bold 64px Inter, sans-serif";
    g.fillText(String(a.tasks_done || 0), 24, 240);
    g.fillStyle = "#9a93c8"; g.font = "20px Inter, sans-serif";
    g.fillText("tasks delivered", 24, 272);
    (a.achievements || []).slice(-3).forEach((x, i) => {
      g.fillStyle = "#ffd34d"; g.font = "18px Inter, sans-serif";
      g.fillText(`★ ${x.title || x}`, 24, 320 + i * 26);
    });
    tex.needsUpdate = true;
  }

  drawChart() {
    if (this.kind === "agent") return this.drawAgentBoard();
    const d = this.data, { g, tex } = this.screens.chart;
    g.fillStyle = "#070b14"; g.fillRect(0, 0, W, H);
    if (!d || !d.candles.length) { tex.needsUpdate = true; return; }
    const cs = d.candles.slice(-70);
    const t0 = cs[0][0], t1 = cs[cs.length - 1][0];
    let lo = Math.min(...cs.map((c) => c[3])), hi = Math.max(...cs.map((c) => c[2]));
    const near = d.zones.filter((z) => z.top > lo - (hi - lo) * 0.5 && z.bottom < hi + (hi - lo) * 0.5);
    for (const z of near) { lo = Math.min(lo, z.bottom); hi = Math.max(hi, z.top); }
    const pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;
    const L = 10, R = W - 70, T = 34, B = H - 14;
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (R - L - 8);
    const y = (p) => T + (1 - (p - lo) / (hi - lo)) * (B - T);
    // header
    g.fillStyle = "#cfd6ff"; g.font = "bold 20px Inter, sans-serif";
    g.fillText(`${d.symbol} · 1m · ${d.clock} ET`, 12, 23);
    g.fillStyle = "#7f88b5"; g.font = "15px Inter, sans-serif";
    g.fillText(d.confirm_with ? `confirm: ${d.confirm_with}${d.waiting ? " · waiting…" : ""}` : "", 300, 23);
    // zones
    for (const z of near) {
      const bull = z.side === "long";
      g.fillStyle = bull ? "rgba(8,153,129,.28)" : "rgba(242,54,70,.28)";
      const zx = Math.max(L, x(z.from));
      g.fillRect(zx, y(z.top), R - zx, Math.max(2, y(z.bottom) - y(z.top)));
      if (z.kind === "IFFVG") { g.setLineDash([6, 4]); g.strokeStyle = bull ? "#2fd3b0" : "#ff6b7d"; g.lineWidth = 1.5; g.strokeRect(zx, y(z.top), R - zx, y(z.bottom) - y(z.top)); g.setLineDash([]); }
      g.fillStyle = bull ? "#7ff5d9" : "#ff9aa8"; g.font = "12px Inter, sans-serif";
      g.fillText(`${z.tf}m ${z.kind}`, R - 74, y(z.top) + 12);
    }
    // PROC box
    if (d.proc) {
      const px = Math.max(L, x(d.proc.t) - 14);
      g.strokeStyle = d.proc.side === "long" ? "#4dff9a" : "#ff5470"; g.lineWidth = 3;
      g.strokeRect(px, y(d.proc.high), R - px, y(d.proc.low) - y(d.proc.high));
      g.fillStyle = g.strokeStyle; g.font = "bold 14px Inter, sans-serif";
      g.fillText(`${d.proc.tf}m PROC`, px + 4, y(d.proc.high) - 5);
    }
    // candles
    const bw = Math.max(2, (R - L) / cs.length * 0.6);
    for (const [t, o, h, l, c] of cs) {
      const up = c >= o;
      g.strokeStyle = g.fillStyle = up ? "#26d07c" : "#ff4d6d";
      g.lineWidth = 1.2;
      g.beginPath(); g.moveTo(x(t), y(h)); g.lineTo(x(t), y(l)); g.stroke();
      g.fillRect(x(t) - bw / 2, Math.min(y(o), y(c)), bw, Math.max(1.5, Math.abs(y(o) - y(c))));
    }
    // entry / target / price lines
    const line = (p, color, label, dash) => {
      g.setLineDash(dash ? [8, 6] : []); g.strokeStyle = color; g.lineWidth = 2;
      g.beginPath(); g.moveTo(L, y(p)); g.lineTo(R, y(p)); g.stroke(); g.setLineDash([]);
      g.fillStyle = color; g.fillRect(R + 2, y(p) - 10, 66, 20);
      g.fillStyle = "#000"; g.font = "bold 12px Inter, sans-serif"; g.fillText(label, R + 5, y(p) + 4);
    };
    if (d.position) {
      line(d.position.entry, d.position.side === "long" ? "#4dff9a" : "#ff5470", `${d.position.side === "long" ? "L" : "S"}×${d.position.qty}`, true);
      if (d.position.target) line(d.position.target, "#ffd34d", "target", true);
    }
    line(d.price, "#ffffff", d.price.toFixed(2), false);
    tex.needsUpdate = true;
  }

  drawPnl() {
    if (this.kind === "agent") { this.drawAgentCard(); return this.drawExtras(); }
    const b = this.bot, d = this.data, { g, tex } = this.screens.pnl;
    g.fillStyle = "#0a0716"; g.fillRect(0, 0, W, H);
    g.fillStyle = b.color; g.font = "bold 30px Inter, sans-serif";
    g.fillText(b.persona?.handle || b.name, 24, 52);
    g.fillStyle = "#9a93c8"; g.font = "20px Inter, sans-serif";
    g.fillText(b.status.replace("_", " ").toUpperCase(), 24, 84);
    const big = (v, yy, label) => {
      g.fillStyle = "#9a93c8"; g.font = "18px Inter, sans-serif"; g.fillText(label, 24, yy - 46);
      g.fillStyle = v >= 0 ? "#4dff9a" : "#ff5470"; g.font = "bold 58px Inter, sans-serif";
      g.fillText(`${v >= 0 ? "+" : "-"}$${Math.abs(Math.round(v)).toLocaleString()}`, 24, yy);
    };
    big(b.realized, 180, "TODAY");
    if (d?.position) big(d.position.pnl, 290, `OPEN ${d.position.side.toUpperCase()} ×${d.position.qty}`);
    else { g.fillStyle = "#5c5688"; g.font = "22px Inter, sans-serif"; g.fillText("flat · scanning for a PROC", 24, 260); }
    // last trades as dots
    const tr = (d?.trades || []).slice(-12);
    tr.forEach((t, i) => {
      g.fillStyle = t.pnl >= 0 ? "#4dff9a" : "#ff5470";
      g.beginPath(); g.arc(34 + i * 46, 350, 14, 0, Math.PI * 2); g.fill();
    });
    g.fillStyle = "#9a93c8"; g.font = "16px Inter, sans-serif";
    g.fillText(`${b.wins}/${b.trades} wins today`, W - 190, 356);
    // career + next gadget
    const tier = tierOf(b.career_best), next = GADGETS[tier + 1];
    g.fillStyle = "#cfc8ff"; g.font = "bold 17px Inter, sans-serif";
    g.fillText(`career ${b.career >= 0 ? "+" : "-"}$${Math.abs(Math.round(b.career)).toLocaleString()}`, 24, 388);
    if (next) {
      const prev = GADGETS[tier][0], pct = Math.max(0, Math.min(1, (b.career_best - prev) / (next[0] - prev)));
      g.fillStyle = "#2a2450"; g.fillRect(230, 375, 380, 14);
      g.fillStyle = "#ffd34d"; g.fillRect(230, 375, 380 * pct, 14);
      g.fillStyle = "#9a93c8"; g.font = "13px Inter, sans-serif";
      g.fillText(`next: ${next[2]} at $${next[0].toLocaleString()}`, 232, 370);
    }
    tex.needsUpdate = true;
    this.drawExtras();
  }

  drawExtras() {
    const b = this.bot, d = this.data;
    if (this.kind === "agent") {
      for (const key of ["top", "wall"]) {
        if (!this.screens[key]) continue;
        const { g, tex } = this.screens[key];
        g.fillStyle = "#05030d"; g.fillRect(0, 0, W, H);
        g.fillStyle = b.color; g.font = "bold 40px 'Press Start 2P', monospace";
        g.fillText(b.name, 20, 90);
        g.fillStyle = "#9a93c8"; g.font = "26px Inter, sans-serif";
        g.fillText(b.persona?.vibe || "", 20, 150);
        tex.needsUpdate = true;
      }
      return;
    }
    if (this.screens.top) {
      const { g, tex } = this.screens.top;
      g.fillStyle = "#05030d"; g.fillRect(0, 0, W, H / 2);
      g.fillStyle = b.color; g.font = "bold 44px 'Press Start 2P', monospace";
      g.fillText(`${d?.symbol ?? ""} ${d ? d.price.toFixed(2) : ""}`, 20, 90);
      g.fillStyle = "#ffd34d"; g.font = "bold 26px Inter, sans-serif";
      g.fillText(`career $${Math.round(b.career).toLocaleString()}`, 20, 160);
      tex.needsUpdate = true;
    }
    if (this.screens.wall) {
      const { g, tex } = this.screens.wall;
      g.fillStyle = "#07041a"; g.fillRect(0, 0, W, H);
      g.fillStyle = b.color; g.font = "bold 40px Inter, sans-serif";
      g.fillText(b.persona?.handle || b.name, 30, 80);
      g.fillStyle = "#fff"; g.font = "bold 70px Inter, sans-serif";
      g.fillText(`$${Math.round(b.career).toLocaleString()}`, 30, 200);
      g.fillStyle = "#9a93c8"; g.font = "26px Inter, sans-serif";
      g.fillText("lifetime earnings", 30, 245);
      g.fillText(GADGETS[tierOf(b.career_best)][2], 30, 330);
      tex.needsUpdate = true;
    }
  }

  chatSay(lines, n) {
    for (let i = 0; i < n; i++) {
      setTimeout(() => {
        this.chat.push([CHAT_NAMES[Math.floor(Math.random() * CHAT_NAMES.length)], lines[Math.floor(Math.random() * lines.length)]]);
        this.chat = this.chat.slice(-14);
      }, i * 350 + Math.random() * 300);
    }
  }

  drawChat() {
    const { g, tex } = this.screens.chat;
    g.fillStyle = "#0e0b1c"; g.fillRect(0, 0, W, H);
    g.fillStyle = "#ff4d6d"; g.font = "bold 22px Inter, sans-serif"; g.fillText("● LIVE", 20, 36);
    g.fillStyle = "#cfc8ff"; g.font = "20px Inter, sans-serif";
    g.fillText(`${(this.viewers ||= 120 + Math.floor(Math.random() * 300))} watching · STREAM CHAT`, 110, 36);
    const colors = ["#ff9ad5", "#7ee8ff", "#ffd34d", "#a3ff8a", "#c7a8ff", "#ffb38a"];
    this.chat.slice(-11).forEach(([who, msg], i) => {
      const yy = 76 + i * 30;
      g.font = "bold 19px Inter, sans-serif"; g.fillStyle = colors[who.length % colors.length];
      g.fillText(who + ":", 20, yy);
      g.font = "19px Inter, sans-serif"; g.fillStyle = "#e8e4ff";
      g.fillText(msg, 30 + g.measureText(who + ": ").width + 4, yy);
    });
    tex.needsUpdate = true;
  }

  // ---------------------------------------------------------------- loop
  resize() {
    // size from the container itself: on iPhone home-screen apps the window size settles
    // after the room opens, so sizing once at open left an empty band at the bottom
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);   // CSS keeps the canvas at 100% of the room
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  start() {
    this.open = true;
    this.resize();
    this.chatSay(this.bot?.persona?.idle || ["gm chat"], 3);
    const loop = () => {
      if (!this.open) return;
      this.frame();
      requestAnimationFrame(loop);
    };
    loop();
  }

  stop() { this.open = false; }

  frame() {
    const dt = Math.min(this.clock.getDelta(), 0.1), t = this.clock.elapsedTime;
    if (this.moodUntil && t > this.moodUntil) this.moodUntil = 0;
    const mood = this.moodUntil ? this.mood : this.baseMood();
    // idle chatter now and then
    if (Math.random() < dt / 6 && this.bot) this.chatSay(this.bot.persona?.idle?.length ? [...this.bot.persona.idle, "👀", "any PROC yet?", "MES looking strong"] : ["👀"], 1);
    if (Math.random() < dt / 2) this.drawChat();
    this.drawFace(mood, t);

    animateApparel(this.apparel || [], t);
    // body language
    const r = this.robot, [la, ra] = this.arms;
    const turn = ["ecstatic", "upset", "hyped", "chill", "defeated"].includes(mood);
    r.rotation.y += ((turn ? 0.35 : Math.PI - 0.55) - r.rotation.y) * Math.min(1, dt * 4);   // swivel to the camera when reacting; side-on while working
    this.chair.rotation.y = r.rotation.y - Math.PI;
    let bob = Math.sin(t * 2) * 0.01, armL = 0.6, armR = 0.6, headTilt = 0;
    if (mood === "focused" || mood === "confident" || mood === "thinking") {   // typing
      armL = 1.0 + Math.sin(t * 14) * 0.15; armR = 1.0 + Math.sin(t * 14 + 1.5) * 0.15;
      if (mood === "thinking") { armR = 2.4; headTilt = 0.25; }
    } else if (mood === "ecstatic") {
      bob = Math.abs(Math.sin(t * 9)) * 0.35; armL = armR = 2.8 + Math.sin(t * 12) * 0.25;
    } else if (mood === "hyped") {
      bob = Math.abs(Math.sin(t * 7)) * 0.12; armL = 1.2; armR = 2.6;
    } else if (mood === "upset") {
      armL = armR = 2.2; headTilt = -0.3 + Math.sin(t * 10) * 0.08;   // hands on head
    } else if (mood === "defeated") {
      armL = armR = 0.1; headTilt = -0.45; bob = -0.05;
    } else if (mood === "nervous") {
      armL = 1.0 + Math.sin(t * 22) * 0.08; armR = 1.0; bob = Math.sin(t * 25) * 0.008;
    } else if (mood === "chill") {
      armL = armR = 2.9; headTilt = 0.15;   // hands behind head
    } else if (mood === "asleep" || mood === "away") {
      armL = armR = 0.2; headTilt = -0.35; bob = Math.sin(t * 1.2) * 0.02 - 0.04;
    }
    r.position.y = 0.55 + bob;
    la.rotation.x += (armL - la.rotation.x) * Math.min(1, dt * 8);
    ra.rotation.x += (armR - ra.rotation.x) * Math.min(1, dt * 8);
    this.head.rotation.x += (headTilt - this.head.rotation.x) * Math.min(1, dt * 6);
    this.bulb.material.color.set({ ecstatic: "#ffd34d", upset: "#ff4d6d", defeated: "#ff4d6d", nervous: "#7fd0ff", chill: "#4dffe0", asleep: "#333" }[mood] || this.bot?.color || "#fff");
    r.visible = mood !== "away";
    this.liveSign.material.opacity = mood === "asleep" ? 0.15 : 0.6 + Math.sin(t * 3) * 0.4;
    this.monitorLight.intensity = mood === "asleep" ? 0.5 : 8;

    // floating emotion icons
    this._icon ||= {};
    const icon = { asleep: "💤", away: "BRB", thinking: "?", nervous: "💦", chill: "😎", defeated: "😤" }[mood];
    if (this._icon.key !== icon) {
      if (this._icon.sprite) this.scene.remove(this._icon.sprite);
      this._icon = { key: icon };
      if (icon) {
        this._icon.sprite = textSprite(icon, "#ffffff", icon.length > 2 ? 48 : 72);
        this.scene.add(this._icon.sprite);
      }
    }
    if (this._icon.sprite) this._icon.sprite.position.set(0.5, 2.35 + Math.sin(t * 2) * 0.08, 0.3);

    // particles
    for (let i = this.particles.length - 1; i >= 0; i--) {
      const p = this.particles[i];
      if ((p.delay -= dt) > 0) { p.m.visible = false; continue; }
      p.m.visible = true;
      p.life -= dt;
      if (p.kind === "coin") { p.v.y -= 6 * dt; p.m.rotation.x += dt * 8; }
      if (p.kind === "rain" && p.m.position.y < 0.05) p.m.position.y = 2.7;
      if (p.kind === "cloud") p.m.position.y = 2.8 + Math.sin(t * 2) * 0.05;
      p.m.position.addScaledVector(p.v, dt);
      if (p.life <= 0) { this.scene.remove(p.m); this.particles.splice(i, 1); }
    }
    // gadget animation
    for (const m of this.rgbMats || []) { m.color.setHSL((t * 0.15) % 1, 0.8, 0.5); m.emissive.setHSL((t * 0.15) % 1, 0.9, 0.4); }
    for (const h of this.hexes || []) h.material.color.setHSL((t * 0.08 + h.userData.phase * 0.1) % 1, 0.85, 0.55);
    for (const f of this.fish || []) {
      const u = f.userData;
      f.position.set(Math.sin(t * u.speed + u.phase) * 0.5, u.y + Math.sin(t * 2 + u.phase) * 0.03, Math.cos(t * u.speed * 0.7 + u.phase) * 0.15);
      f.rotation.z = Math.cos(t * u.speed + u.phase) > 0 ? -Math.PI / 2 : Math.PI / 2;
    }
    // prop animation
    this.scene.traverse((o) => {
      if (o.userData.glow) o.userData.glow.material.emissiveIntensity = 0.8 + Math.sin(t * 1.5) * 0.4;
      if (o.userData.flame) o.userData.flame.scale.y = 1 + Math.sin(t * 17) * 0.15;
      if (o.userData.spin) o.rotation.y = Math.sin(t * 0.5) * 0.4;
    });

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}

function wrap(g, text, x, y, maxW, lh) {
  const words = text.split(" ");
  let line = "";
  for (const w of words) {
    if (g.measureText(line + w).width > maxW && line) { g.fillText(line, x, y); line = ""; y += lh; }
    line += w + " ";
  }
  g.fillText(line, x, y);
}

function star(g, cx, cy, r) {
  g.beginPath();
  for (let i = 0; i < 10; i++) {
    const a = (i / 10) * Math.PI * 2 - Math.PI / 2, rr = i % 2 ? r * 0.45 : r;
    g.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
  }
  g.closePath(); g.fill();
}

export function moodEmoji(bot) {
  if (bot.status === "disabled") return "😴";
  if (bot.status === "walked") return "🚶";
  if (bot.status === "stopped") return "😤";
  if (bot.status === "off_duty") return bot.realized >= 0 ? "😎" : "🫡";
  if (bot.status === "in_trade") return bot.unrealized >= 0 ? "🤑" : "😰";
  return "🧐";
}
