// Full-screen trading chart for one bot: clock-aligned 1-15m candles, its untapped
// FFVG/IFFVG zones, the live PROC, every pointer/PROC it saw, the confirming
// market's pointers, and today's entries and exits. Drag to scroll back, pinch or
// scroll to zoom, double-tap to snap back to now.

const UP = "#26d07c", DOWN = "#ff4d6d", BULL_Z = "rgba(8,153,129,.22)", BEAR_Z = "rgba(242,54,70,.22)";
const money = (v) => `${v >= 0 ? "+" : "-"}$${Math.abs(Math.round(v)).toLocaleString()}`;

export class ChartView {
  constructor(root) {
    this.root = root;
    this.canvas = root.querySelector("canvas");
    this.g = this.canvas.getContext("2d");
    this.tf = 1;
    this.n = 70;          // candles on screen
    this.back = 0;        // candles scrolled back from now
    this.data = null;
    this.botId = null;
    this.timer = null;
    new ResizeObserver(() => this.draw()).observe(this.canvas);
    root.querySelectorAll("[data-tf]").forEach((b) => (b.onclick = () => this.setTf(+b.dataset.tf)));
    this._gestures();
  }

  open(bot) {
    this.botId = bot.id;
    this.root.style.setProperty("--accent", bot.color);
    this.root.querySelector(".chart-name").textContent = `${bot.persona?.handle || bot.name} · ${bot.underlying}`;
    this.root.classList.remove("hidden");
    this.back = 0;
    this.data = null;
    this.draw();
    this.refresh();
    clearInterval(this.timer);
    this.timer = setInterval(() => this.refresh(), 3000);
  }

  close() {
    this.root.classList.add("hidden");
    clearInterval(this.timer);
    this.botId = null;
  }

  setTf(tf) {
    this.tf = tf;
    this.back = 0;
    this.root.querySelectorAll("[data-tf]").forEach((b) => b.classList.toggle("on", +b.dataset.tf === tf));
    this.refresh();
  }

  async refresh() {
    if (!this.botId) return;
    try {
      const r = await fetch(`/api/bots/${this.botId}/chart?tf=${this.tf}&count=400`);
      if (!r.ok) return;
      this.data = await r.json();
      this.draw();
      this.info();
    } catch { /* next refresh */ }
  }

  info() {
    const d = this.data, p = d.position;
    const pos = p
      ? `<b class="${p.pnl >= 0 ? "pos" : "neg"}">${p.side.toUpperCase()} ×${p.qty} @ ${p.entry.toFixed(2)} · ${money(p.pnl)}</b> <span>${p.why || ""}</span>`
      : `<span>flat</span>`;
    const day = d.trades.reduce((s, t) => s + t.pnl, 0);
    this.root.querySelector(".chart-info").innerHTML =
      `${pos}<span>${d.setup || ""}</span><span>today ${d.trades.length} trade${d.trades.length === 1 ? "" : "s"} · <b class="${day >= 0 ? "pos" : "neg"}">${money(day)}</b></span>`;
  }

  // ---------------------------------------------------------------- gestures
  _gestures() {
    const c = this.canvas, pts = new Map();
    let start = null, lastTap = 0;
    const step = () => (c.clientWidth - 64) / this.n;
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, e.clientX);
      start = { back: this.back, n: this.n, x: e.clientX, span: this._span(pts) };
      const now = Date.now();
      if (now - lastTap < 300) { this.back = 0; this.n = 70; this.draw(); }
      lastTap = now;
    });
    c.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId) || !start) return;
      pts.set(e.pointerId, e.clientX);
      if (pts.size >= 2 && start.span) {
        this.n = Math.round(Math.max(20, Math.min(300, start.n * start.span / Math.max(20, this._span(pts)))));
      } else if (pts.size === 1) {
        this.back = Math.round(start.back + (e.clientX - start.x) / step());
      }
      this._clamp();
      this.draw();
    });
    const up = (e) => {
      pts.delete(e.pointerId);
      start = pts.size ? { back: this.back, n: this.n, x: [...pts.values()][0], span: this._span(pts) } : null;
    };
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) this.back += Math.round(-e.deltaX / step());
      else this.n = Math.round(Math.max(20, Math.min(300, this.n * (e.deltaY > 0 ? 1.12 : 0.89))));
      this._clamp();
      this.draw();
    }, { passive: false });
  }

  _span(pts) {
    const xs = [...pts.values()];
    return xs.length >= 2 ? Math.abs(xs[0] - xs[1]) : 0;
  }

  _clamp() {
    const total = this.data?.candles.length || 0;
    this.back = Math.max(0, Math.min(this.back, Math.max(0, total - 10)));
  }

  // ---------------------------------------------------------------- drawing
  draw() {
    const c = this.canvas, g = this.g, dpr = devicePixelRatio || 1;
    const W = c.clientWidth, H = c.clientHeight;
    if (!W || !H) return;
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) {
      c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
    }
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#070b14"; g.fillRect(0, 0, W, H);
    const d = this.data;
    if (!d || !d.candles.length) {
      g.fillStyle = "#7f88b5"; g.font = "14px Inter, sans-serif"; g.textAlign = "center";
      g.fillText(d ? "no candles yet" : "loading chart…", W / 2, H / 2); g.textAlign = "left";
      return;
    }
    const all = d.candles, end = all.length - this.back;
    const cs = all.slice(Math.max(0, end - this.n), end);
    const L = 6, R = W - 62, T = 10, B = H - 40, LANE = 14;   // LANE: confirming market's strip at the bottom
    const plotB = B - (d.partner ? LANE + 6 : 0);
    const step = (R - L) / this.n;
    const idx = new Map(cs.map((k, i) => [k[0], i]));
    const xi = (i) => L + (i + 0.5 + (this.n - cs.length)) * step;
    const xt = (t) => (idx.has(t) ? xi(idx.get(t)) : null);
    // price range: visible candles, the open position, and zones near them
    let lo = Math.min(...cs.map((k) => k[3])), hi = Math.max(...cs.map((k) => k[2]));
    const span0 = hi - lo || 1;
    const near = d.zones.filter((z) => z.top > lo - span0 * 0.35 && z.bottom < hi + span0 * 0.35 && z.from <= cs[cs.length - 1][0]);
    for (const z of near) { lo = Math.min(lo, z.bottom); hi = Math.max(hi, z.top); }
    if (d.position && this.back === 0) { lo = Math.min(lo, d.position.entry); hi = Math.max(hi, d.position.entry); }
    const pad = (hi - lo) * 0.06 || 1;
    lo -= pad; hi += pad;
    const y = (p) => T + (1 - (p - lo) / (hi - lo)) * (plotB - T);

    // grid + price axis
    g.font = "11px Inter, sans-serif";
    const tick = niceStep((hi - lo) / 6);
    for (let p = Math.ceil(lo / tick) * tick; p < hi; p += tick) {
      g.strokeStyle = "rgba(255,255,255,.05)"; g.lineWidth = 1;
      g.beginPath(); g.moveTo(L, y(p)); g.lineTo(R, y(p)); g.stroke();
      g.fillStyle = "#6f78a8"; g.fillText(p.toFixed(2), R + 6, y(p) + 4);
    }
    // time axis
    const every = Math.max(1, Math.ceil(70 / step));
    g.fillStyle = "#6f78a8"; g.textAlign = "center";
    cs.forEach((k, i) => { if ((all.length - this.back - cs.length + i) % every === 0 && k[5]) g.fillText(k[5], xi(i), B + 26); });
    g.textAlign = "left";

    // zones: from where they formed to the right edge (tapped ones fainter)
    const labelYs = [];
    for (const z of near) {
      const bull = z.side === "long";
      const zx = idx.has(z.from) ? xi(idx.get(z.from)) - step / 2 : (z.from < cs[0][0] ? L : null);
      if (zx === null) continue;
      g.globalAlpha = z.tapped ? 0.45 : 1;
      g.fillStyle = bull ? BULL_Z : BEAR_Z;
      g.fillRect(zx, y(z.top), R - zx, Math.max(2, y(z.bottom) - y(z.top)));
      if (z.kind === "IFFVG") {
        g.setLineDash([5, 4]); g.strokeStyle = bull ? "#2fd3b0" : "#ff6b7d"; g.lineWidth = 1;
        g.strokeRect(zx, y(z.top), R - zx, y(z.bottom) - y(z.top)); g.setLineDash([]);
      }
      const ly = y(z.top) + 11;
      if (!labelYs.some((v) => Math.abs(v - ly) < 12)) {   // skip labels that would overlap
        labelYs.push(ly);
        g.fillStyle = bull ? "#7ff5d9" : "#ff9aa8"; g.font = "10px Inter, sans-serif";
        g.fillText(`${z.tf}m ${z.kind}${z.tapped ? " ✓" : ""}`, R - 78, ly);
      }
      g.globalAlpha = 1;
    }
    // live PROC box
    if (d.proc) {
      const px = xt(d.proc.t) ?? (d.proc.t < cs[0][0] ? L : null);
      if (px !== null) {
        g.strokeStyle = d.proc.side === "long" ? "#4dff9a" : "#ff5470"; g.lineWidth = 2;
        g.strokeRect(px - step / 2, y(d.proc.high), R - px + step / 2, y(d.proc.low) - y(d.proc.high));
        g.fillStyle = g.strokeStyle; g.font = "bold 11px Inter, sans-serif";
        g.fillText(`${d.proc.tf}m PROC`, Math.min(px - step / 2 + 3, R - 62), y(d.proc.high) - 4);
      }
    }
    // candles
    const bw = Math.max(1, step * 0.62);
    cs.forEach(([, o, h, l, cl], i) => {
      const x = xi(i);
      g.strokeStyle = g.fillStyle = cl >= o ? UP : DOWN;
      g.lineWidth = 1;
      g.beginPath(); g.moveTo(x, y(h)); g.lineTo(x, y(l)); g.stroke();
      g.fillRect(x - bw / 2, Math.min(y(o), y(cl)), bw, Math.max(1, Math.abs(y(o) - y(cl))));
    });
    // pointers (small) and PROCs (big) the bot saw, under/over the candle
    const byT = new Map(cs.map((k) => [k[0], k]));
    for (const m of d.procs) {
      const x = xt(m.t), k = byT.get(m.t);
      if (x === null || !k) continue;
      const long = m.side === "long", big = m.kind === "proc";
      const yy = long ? y(k[3]) + 8 : y(k[2]) - 8;
      tri(g, x, yy, big ? 7 : 4, long, big ? (long ? "#4dff9a" : "#ff5470") : "rgba(200,200,255,.55)");
      if (big) { g.fillStyle = long ? "#4dff9a" : "#ff5470"; g.font = "bold 9px Inter, sans-serif"; g.textAlign = "center";
        g.fillText(`${m.tf}m`, x, long ? yy + 18 : yy - 11); g.textAlign = "left"; }
    }
    // confirming market's pointers/PROCs in a strip along the bottom
    if (d.partner) {
      const ly = plotB + 6 + LANE / 2;
      g.fillStyle = "rgba(255,255,255,.04)"; g.fillRect(L, plotB + 6, R - L, LANE);
      g.fillStyle = "#8f98c8"; g.font = "9px Inter, sans-serif"; g.fillText(d.partner.symbol, R + 6, ly + 3);
      for (const m of d.partner.marks) {
        const x = xt(m.t);
        if (x === null) continue;
        g.fillStyle = m.side === "long" ? "#4dff9a" : "#ff5470";
        g.globalAlpha = m.kind === "proc" ? 1 : 0.5;
        g.beginPath(); g.moveTo(x, ly - 5); g.lineTo(x + 4, ly); g.lineTo(x, ly + 5); g.lineTo(x - 4, ly); g.fill();
        g.globalAlpha = 1;
      }
    }
    // today's trades: entry arrow → exit cross, linked
    for (const t of d.trades) {
      const x0 = xt(t.t_open), x1 = xt(t.t_close);
      const col = t.pnl >= 0 ? "#4dff9a" : "#ff5470";
      if (x0 !== null && x1 !== null) {
        g.setLineDash([4, 3]); g.strokeStyle = col; g.lineWidth = 1.5;
        g.beginPath(); g.moveTo(x0, y(t.entry)); g.lineTo(x1, y(t.exit)); g.stroke(); g.setLineDash([]);
      }
      if (x0 !== null) arrow(g, x0, y(t.entry), t.side === "long", "#ffd34d");
      if (x1 !== null) {
        g.strokeStyle = col; g.lineWidth = 2.5;
        g.beginPath(); g.moveTo(x1 - 5, y(t.exit) - 5); g.lineTo(x1 + 5, y(t.exit) + 5);
        g.moveTo(x1 + 5, y(t.exit) - 5); g.lineTo(x1 - 5, y(t.exit) + 5); g.stroke();
        g.fillStyle = col; g.font = "bold 11px Inter, sans-serif";
        g.fillText(money(t.pnl), Math.min(x1 + 8, R - 44), y(t.exit) + (t.side === "long" ? -8 : 16));
      }
    }
    // open position + price
    const tag = (p, color, label, dashed) => {
      g.setLineDash(dashed ? [6, 5] : []); g.strokeStyle = color; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(L, y(p)); g.lineTo(R, y(p)); g.stroke(); g.setLineDash([]);
      g.fillStyle = color; g.fillRect(R + 1, y(p) - 9, 61, 18);
      g.fillStyle = "#000"; g.font = "bold 10px Inter, sans-serif"; g.fillText(label, R + 4, y(p) + 4);
    };
    if (d.position) {
      const p = d.position, x0 = xt(p.t_open);
      if (x0 !== null) arrow(g, x0, y(p.entry), p.side === "long", "#ffd34d");
      tag(p.entry, p.side === "long" ? "#4dff9a" : "#ff5470", `${p.side === "long" ? "L" : "S"}×${p.qty} ${money(p.pnl)}`, true);
    }
    if (this.back === 0) tag(d.price, "#ffffff", d.price.toFixed(2), false);
    // header
    g.fillStyle = "#cfd6ff"; g.font = "bold 12px Inter, sans-serif";
    g.fillText(`${d.symbol} · ${d.tf}m · ${d.clock} ET${this.back ? ` · ${this.back} back (double-tap: now)` : ""}`, L + 4, T + 12);
  }
}

function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw)), f = raw / p;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
}

function tri(g, x, y, s, up, color) {
  g.fillStyle = color;
  g.beginPath();
  if (up) { g.moveTo(x, y - s); g.lineTo(x + s, y + s); g.lineTo(x - s, y + s); }
  else { g.moveTo(x, y + s); g.lineTo(x + s, y - s); g.lineTo(x - s, y - s); }
  g.fill();
}

function arrow(g, x, y, long, color) {
  g.fillStyle = color; g.strokeStyle = "#000"; g.lineWidth = 1;
  g.beginPath();
  if (long) { g.moveTo(x, y); g.lineTo(x - 7, y + 12); g.lineTo(x + 7, y + 12); }
  else { g.moveTo(x, y); g.lineTo(x - 7, y - 12); g.lineTo(x + 7, y - 12); }
  g.closePath(); g.fill(); g.stroke();
}
