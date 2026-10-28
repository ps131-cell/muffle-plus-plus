/* The slide viewer of the pathology workbench: OpenSeadragon over a section's Deep Zoom tiles,
   with the analysis drawn on a canvas above the tissue. Speaks Streamlit's component protocol
   (v1) through postMessage; no build step.

   Every overlay coordinate is in grid units (one unit = one 112 µm tile of the scored grid);
   source.frame maps grid units to pyramid pixels (x = x0 + col·t), source.mpp gives µm per
   pyramid pixel. Evidence types (docs/pathology.md): classes and nuclei are model inferences,
   the front, zones, arcs, islands, field and risk points are rules on them, the direction of
   invasion is a hypothesis about this section. */
"use strict";

const ST = {
  send(type, data) {
    window.parent.postMessage(Object.assign({isStreamlitMessage: true, type: type}, data), "*");
  },
  ready() { this.send("streamlit:componentReady", {apiVersion: 1}); },
  height(h) { this.send("streamlit:setFrameHeight", {height: h}); },
  value(v) { this.send("streamlit:setComponentValue", {value: v, dataType: "json"}); },
};

const TOGGLES = [["front", "front line", true], ["arcs", "arcs and direction", true],
  ["breakaway", "breakaway and counting field", true], ["islands", "islands", true],
  ["regions", "risk regions", false], ["pointers", "pointers", true], ["nuclei", "nuclei", true],
  ["window", "scored window", true]];
// the slide map's colours (muffle.workbench.tile_map), so the map and the viewer read the same
const ZONE_COLORS = {"core": "#8C0000", "front band": "#FF734D", "peritumoral": "#FFD9B3"};
const QC_COLORS = {"glass": "#74B9FF", "pen ink": "#6C3483", "blur": "#16A085",
                   "unlike training tissue": "#E67E22"};
const RISK_COLORS = [null, "#FCBBA1", "#EF3B2C", "#A50F15"];
const IMMUNE = [["20 or more per tile", "#08306B"], ["5–19", "#4292C6"], ["under 5", "#C6DBEF"]];
const TIL = [["not lymphocytes", "#d6eaf8"], ["lymphocytes", "#1b4f72"],
             ["lymphocytes, the head disagrees", "#e67e22"],
             ["not lymphocytes, the head disagrees", "#c0392b"]];
const CELL_COLORS = ["#7f8c8d", "#2e86de", "#c0392b", "#8e44ad"];
const NUCLEI_MIN = 0.45;  // screen px per µm at which nuclei are drawn (a 7 µm nucleus ≈ 3 px)
const HERE = window.location.href;  // source URLs are relative to this page (slide_viewer.served)
const PREFS = "muffle-slide-viewer";

const S = {sig: null, panes: [], fill: "tissue", alpha: 0.35, link: true, gotoNonce: null,
           driver: null, syncing: false, reported: {},
           show: new Set(TOGGLES.filter(t => t[2]).map(t => t[0]))};
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                      '"': "&quot;"}[ch]));
const pct = v => Math.round(v * 100) + "%";

try {
  const saved = JSON.parse(window.localStorage.getItem(PREFS) || "null");
  if (saved) {
    S.fill = saved.fill || S.fill;
    S.alpha = saved.alpha || S.alpha;
    if (Array.isArray(saved.show)) S.show = new Set(saved.show);
  }
} catch (e) { /* storage blocked: defaults */ }

function savePrefs() {
  try {
    window.localStorage.setItem(PREFS, JSON.stringify({fill: S.fill, alpha: S.alpha,
                                                        show: [...S.show]}));
  } catch (e) { /* storage blocked */ }
}

// --- the controls ---------------------------------------------------------------------------

function controls() {
  $("fill").value = S.fill;
  $("alpha").value = S.alpha;
  $("fill").onchange = () => { S.fill = $("fill").value; S.panes.forEach(group); redraw(); };
  $("alpha").oninput = () => { S.alpha = +$("alpha").value; redraw(); };
  $("link").onchange = () => { S.link = $("link").checked; };
  const box = $("toggles");
  for (const [key, text] of TOGGLES) {
    const label = document.createElement("label");
    label.innerHTML = `<input type="checkbox" ${S.show.has(key) ? "checked" : ""}> ${text}`;
    label.firstChild.onchange = ev => {
      if (ev.target.checked) S.show.add(key); else S.show.delete(key);
      redraw();
    };
    box.append(label);
  }
}

function redraw() {
  S.panes.forEach(draw);
  legend();
  savePrefs();
}

// --- panes ----------------------------------------------------------------------------------

function render(args, theme) {
  document.body.classList.toggle("dark", !!theme && theme.base === "dark");
  const sig = JSON.stringify(args.sources.map(s => [s.slide, s.tiles, s.overlay]));
  if (sig !== S.sig) {
    S.sig = sig;
    build(args.sources, args.height);
  }
  $("linkbox").style.display = args.sources.length > 1 ? "" : "none";
  const g = args.goto;
  if (g && g.nonce !== S.gotoNonce) {
    S.gotoNonce = g.nonce;
    const p = S.panes.find(q => q.src.slide === g.slide) || S.panes[0];
    if (p) fly(p, g.row, g.col, g.span || 12);
  }
  const s = args.spot;  // the tile the page's Spot panel shows: n and p step on from it
  S.panes.forEach(p => { p.spot = s && s.slide === p.src.slide ? s.tile : null; atSpot(p); });
  legend();
}

function atSpot(p) {
  // When the Spot panel shows a pointer, that pointer is the current one, so the first n goes
  // to the next pointer (T1 shown: n opens T2) instead of re-opening the one already shown.
  if (!p.ov || !p.spot) return;
  const i = p.ov.queue.findIndex(q => `r${Math.round(q.row)}c${Math.round(q.col)}` === p.spot);
  if (i >= 0) p.cur = i;
}

function build(sources, height) {
  S.panes.forEach(p => p.viewer.destroy());
  $("wrap").innerHTML = "";
  $("wrap").style.height = height + "px";
  S.panes = sources.map(makePane);
  S.driver = S.panes[0];
}

function div(cls) {
  const el = document.createElement("div");
  el.className = cls;
  return el;
}

function makePane(src) {
  const el = div("pane"), osd = div("osd"), head = div("head"), msg = div("msg");
  el.append(osd, head, msg);
  $("wrap").append(el);
  const p = {src: src, el: el, msg: msg, ov: null, opened: false, ready: false, cur: -1, spot: null,
             pending: null, last: null, hits: [], view: null, groups: [], loaded: 0, failed: 0};
  head.innerHTML = `<b>${esc(src.label)}</b><span style="white-space:nowrap">` +
                   `${src.mpp.toFixed(2)} µm/px</span>`;
  p.jump = document.createElement("select");
  p.jump.title = "Jump to a pointer, risk region, arc, the counting field or an island";
  head.append(p.jump);
  p.jump.onchange = () => {
    const j = p.jumps[+p.jump.value];
    p.jump.value = "";
    if (j) { fly(p, j.row, j.col, j.span); pick(p, j.row, j.col); }
  };
  p.viewer = OpenSeadragon({
    element: osd,
    tileSources: {Image: {xmlns: "http://schemas.microsoft.com/deepzoom/2008",
                          Url: new URL(src.tiles, HERE).href, Format: src.format,
                          Overlap: String(src.overlap), TileSize: String(src.tile_size),
                          Size: {Width: String(src.width), Height: String(src.height)}}},
    showNavigationControl: false, showNavigator: true, navigatorPosition: "TOP_RIGHT",
    navigatorAutoFade: false, autoHideControls: false,
    navigatorMaintainSizeRatio: false, navigatorWidth: "150px", navigatorHeight: "110px",
    maxZoomPixelRatio: 3, visibilityRatio: 0.3, animationTime: 0.5,
    zoomPerScroll: 1.4, gestureSettingsMouse: {clickToZoom: false, dblClickToZoom: true},
    gestureSettingsTouch: {clickToZoom: false, dblClickToZoom: true},
  });
  p.canvas = document.createElement("canvas");
  Object.assign(p.canvas.style, {position: "absolute", left: "0", top: "0", width: "100%",
                                 height: "100%", pointerEvents: "none"});
  p.viewer.canvas.appendChild(p.canvas);
  p.ctx = p.canvas.getContext("2d");
  const v = p.viewer;
  v.addHandler("open", () => { p.opened = true; ready(p); });
  v.addHandler("open-failed", () => fail(p, "The section's tiles could not be opened."));
  v.addHandler("tile-loaded", () => { p.loaded += 1; });
  v.addHandler("tile-load-failed", () => {
    p.failed += 1;
    if (p.failed >= 8 && !p.loaded) fail(p, "The section's tiles are not reachable from here.");
  });
  v.addHandler("update-viewport", () => draw(p));
  v.addHandler("resize", () => draw(p));
  v.addHandler("animation", () => sync(p));
  v.addHandler("animation-finish", () => sync(p));
  v.addHandler("canvas-press", () => { S.driver = p; });
  v.addHandler("canvas-scroll", () => { S.driver = p; $("tip").style.display = "none"; });
  v.addHandler("canvas-click", ev => { if (ev.quick) click(p, ev.position); });
  new OpenSeadragon.MouseTracker({
    element: v.canvas,
    moveHandler: ev => hover(p, ev.position, ev.originalEvent),
    leaveHandler: () => { $("tip").style.display = "none"; },
  });
  fetch(new URL(src.overlay, HERE))
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(ov => { p.ov = prepare(ov); jumpList(p); group(p); atSpot(p); ready(p); legend(); })
    .catch(e => fail(p, "The analysis layers could not be loaded (" + e.message + ")."));
  return p;
}

function fail(p, text) {
  p.msg.textContent = text + " The tile map below the viewer shows the same analysis.";
  p.msg.style.display = "flex";
  if (!S.reported[p.src.slide]) {
    S.reported[p.src.slide] = true;
    ST.value({slide: p.src.slide, failed: text, nonce: Date.now()});
  }
}

function prepare(ov) {
  const T = ov.tiles, G = ov.grid;
  ov.n = T.r.length;
  ov.idx = new Int32Array(G.rows * G.cols).fill(-1);
  let r0 = Infinity, c0 = Infinity, r1 = -1, c1 = -1;
  ov.buds = [];
  for (let i = 0; i < ov.n; i++) {
    ov.idx[T.r[i] * G.cols + T.c[i]] = i;
    r0 = Math.min(r0, T.r[i]); r1 = Math.max(r1, T.r[i]);
    c0 = Math.min(c0, T.c[i]); c1 = Math.max(c1, T.c[i]);
    if (T.bud[i] > 0) ov.buds.push(i);
  }
  ov.bbox = [r0, c0, r1 + 1, c1 + 1];
  ov.counted = Object.keys(ov.cells).length;
  return ov;
}

function ready(p) {
  if (p.ready || !p.opened || !p.ov) return;
  p.ready = true;
  const [r0, c0, r1, c1] = p.ov.bbox;
  const span = Math.max(r1 - r0, c1 - c0) + 2;
  fly(p, (r0 + r1) / 2 - 0.5, (c0 + c1) / 2 - 0.5, span, true);
  if (p.pending) fly(p, p.pending.row, p.pending.col, p.pending.span);
  p.pending = null;
  p.last = centreUm(p);
  draw(p);
}

function jumpList(p) {
  const ov = p.ov, j = [];
  ov.queue.forEach(q => j.push({text: `${q.pointer} · ${q.what}`, row: q.row, col: q.col,
                                span: 12}));
  ov.regions.forEach(r => j.push({text: `${r.card} · risk level ${r.level} (placeholder points)`,
                                  row: r.row, col: r.col, span: 14}));
  ov.arcs.forEach(a => j.push({text: `${a.arc} · ${a.pattern}, push ${a.push.toFixed(2)}`,
                               row: a.row - 0.5, col: a.col - 0.5, span: 12}));
  if (ov.hotspot) j.push({text: "Counting field (0.785 mm²)", row: ov.hotspot.row,
                          col: ov.hotspot.col, span: 2 * ov.hotspot.radius_tiles + 3});
  ov.islands.forEach(s => j.push({text: `${s.island} · island, ${s.area_mm2} mm²`,
                                  row: s.row, col: s.col, span: 8}));
  p.jumps = j;
  p.jump.innerHTML = `<option value="">jump to…</option>` +
    j.map((x, i) => `<option value="${i}">${esc(x.text)}</option>`).join("");
}

// --- navigation -----------------------------------------------------------------------------

function fly(p, row, col, span, now) {
  $("tip").style.display = "none";
  const ti = p.viewer.world.getItemAt(0);
  if (!ti || !p.ov) { p.pending = {row: row, col: col, span: span}; return; }
  const F = p.src.frame, half = span / 2;
  const rect = ti.imageToViewportRectangle(F.x0 + (col + 0.5 - half) * F.t,
                                           F.y0 + (row + 0.5 - half) * F.t,
                                           span * F.t, span * F.t);
  p.viewer.viewport.fitBounds(rect, !!now);
  S.driver = p;
}

function pick(p, row, col) {
  ST.value({slide: p.src.slide, tile: `r${Math.round(row)}c${Math.round(col)}`,
            nonce: Date.now()});
}

function gridAt(p, pos) {
  const v = p.view;
  return [Math.floor((pos.y - v.oy) / v.ts), Math.floor((pos.x - v.ox) / v.ts)];
}

function click(p, pos) {
  if (!p.view) return;
  const hit = p.hits.find(h => h.kind === "pointer" && Math.hypot(pos.x - h.x, pos.y - h.y) < h.r);
  if (hit) { pick(p, hit.q.row, hit.q.col); return; }
  const [r, c] = gridAt(p, pos), G = p.ov.grid;
  if (r >= 0 && c >= 0 && r < G.rows && c < G.cols && p.ov.idx[r * G.cols + c] >= 0) pick(p, r, c);
}

document.addEventListener("keydown", ev => {
  if (ev.target.tagName === "SELECT" || ev.target.tagName === "INPUT") return;
  const key = ev.key.toLowerCase();
  const p = S.driver || S.panes[0];
  if ((key !== "n" && key !== "p") || !p || !p.ov || !p.ov.queue.length) return;
  const q = p.ov.queue;
  if (p.cur < 0) p.cur = key === "n" ? 0 : q.length - 1;
  else p.cur = (p.cur + (key === "n" ? 1 : q.length - 1)) % q.length;
  fly(p, q[p.cur].row, q[p.cur].col, 12);
  pick(p, q[p.cur].row, q[p.cur].col);
  ev.preventDefault();
});

function centreUm(p) {
  const c = p.viewer.viewport.getCenter(true), k = p.src.width * p.src.mpp;
  return {x: c.x * k, y: c.y * k};
}

function sync(p) {
  // Linked pan and zoom between sections: the same µm per screen pixel in every pane, and the
  // same pan distance in µm. The sections are not registered: this does not align anatomy.
  if (S.syncing || S.panes.length < 2) return;
  if (S.link && S.driver === p && p.last) {
    const vp = p.viewer.viewport;
    const um = p.src.mpp * p.src.width / (vp.getZoom(true) * vp.getContainerSize().x);
    const now = centreUm(p), dx = now.x - p.last.x, dy = now.y - p.last.y;
    S.syncing = true;
    for (const q of S.panes) {
      if (q === p || !q.ready) continue;
      const qv = q.viewer.viewport, qc = qv.getCenter(true), k = q.src.width * q.src.mpp;
      qv.panTo(new OpenSeadragon.Point(qc.x + dx / k, qc.y + dy / k), true);
      qv.zoomTo(q.src.mpp * q.src.width / (um * qv.getContainerSize().x), null, true);
    }
    S.syncing = false;
  }
  S.panes.forEach(q => { if (q.ready) q.last = centreUm(q); });
}

// --- drawing --------------------------------------------------------------------------------

function tileColor(ov, i) {
  const T = ov.tiles;
  switch (S.fill) {
    case "tissue": return T.cls[i] >= 0 ? ov.classes[T.cls[i]].color : "#bbbbbb";
    case "certainty": return T.qc[i] ? "#bbbbbb" : T.unsure[i] ? "#f39c12" : null;
    case "qc": return T.qc[i] ? QC_COLORS[ov.qcs[T.qc[i]]] : null;
    case "zones": return T.front[i] ? "#111111" : ZONE_COLORS[ov.zones[T.zone[i]]] || null;
    case "immune":
      return T.n[i] < 0 ? null : T.ly[i] >= 20 ? IMMUNE[0][1] : T.ly[i] >= 5 ? IMMUNE[1][1]
        : IMMUNE[2][1];
    case "risk": return RISK_COLORS[T.risk[i]];
    case "til": return T.til && T.til[i] >= 0 ? TIL[T.til[i]][1] : null;
    default: return null;
  }
}

function group(p) {
  // tile indices by fill colour, rebuilt when the fill layer changes
  if (!p.ov) return;
  const by = new Map();
  for (let i = 0; i < p.ov.n; i++) {
    const color = tileColor(p.ov, i);
    if (!color) continue;
    if (!by.has(color)) by.set(color, []);
    by.get(color).push(i);
  }
  p.groups = [...by.entries()];
}

function segments(ctx, list, ox, oy, ts) {
  ctx.beginPath();
  for (const [x0, y0, x1, y1] of list) {
    ctx.moveTo(ox + x0 * ts, oy + y0 * ts);
    ctx.lineTo(ox + x1 * ts, oy + y1 * ts);
  }
}

function stroke(ctx, color, width, dash) {
  ctx.setLineDash([]);
  ctx.lineWidth = width + 2.5;
  ctx.strokeStyle = "rgba(255,255,255,0.85)";
  ctx.stroke();
  ctx.setLineDash(dash || []);
  ctx.lineWidth = width;
  ctx.strokeStyle = color;
  ctx.stroke();
  ctx.setLineDash([]);
}

function label(ctx, text, x, y, color) {
  ctx.font = "bold 12px 'Source Sans Pro', system-ui, sans-serif";
  ctx.lineWidth = 3.5;
  ctx.strokeStyle = "rgba(255,255,255,0.92)";
  ctx.strokeText(text, x, y);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}

function arrow(ctx, x, y, x2, y2, color) {
  const a = Math.atan2(y2 - y, x2 - x), h = 10;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x2 - 0.6 * h * Math.cos(a), y2 - 0.6 * h * Math.sin(a));
  stroke(ctx, color, 2.5);
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - h * Math.cos(a - 0.45), y2 - h * Math.sin(a - 0.45));
  ctx.lineTo(x2 - h * Math.cos(a + 0.45), y2 - h * Math.sin(a + 0.45));
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}

function draw(p) {
  const host = p.viewer.canvas, dpr = window.devicePixelRatio || 1;
  const W = host.clientWidth, H = host.clientHeight;
  if (p.canvas.width !== Math.round(W * dpr) || p.canvas.height !== Math.round(H * dpr)) {
    p.canvas.width = Math.round(W * dpr);
    p.canvas.height = Math.round(H * dpr);
  }
  const ctx = p.ctx;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const ti = p.viewer.world.getItemAt(0);
  p.hits = [];
  if (!ti || !p.ov) return;
  const o = ti.imageToViewerElementCoordinates(new OpenSeadragon.Point(0, 0));
  const e = ti.imageToViewerElementCoordinates(new OpenSeadragon.Point(10000, 0));
  const s = (e.x - o.x) / 10000, F = p.src.frame, ov = p.ov, T = ov.tiles, G = ov.grid;
  const ox = o.x + F.x0 * s, oy = o.y + F.y0 * s, ts = F.t * s, k = s / p.src.mpp;
  p.view = {ox: ox, oy: oy, ts: ts, s: s, k: k};
  const c0 = Math.max(0, Math.floor(-ox / ts)), c1 = Math.min(G.cols - 1, Math.floor((W - ox) / ts));
  const r0 = Math.max(0, Math.floor(-oy / ts)), r1 = Math.min(G.rows - 1, Math.floor((H - oy) / ts));
  const X = c => ox + c * ts, Y = r => oy + r * ts;

  if (S.fill !== "none") {
    ctx.globalAlpha = S.alpha;
    for (const [color, list] of p.groups) {
      ctx.fillStyle = color;
      ctx.beginPath();
      for (const i of list) {
        const r = T.r[i], c = T.c[i];
        if (r < r0 || r > r1 || c < c0 || c > c1) continue;
        const x = Math.round(X(c)), y = Math.round(Y(r));
        ctx.rect(x, y, Math.round(X(c + 1)) - x, Math.round(Y(r + 1)) - y);
      }
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
  if (S.show.has("window") && p.src.window) {
    ctx.beginPath();
    ctx.rect(X(0), Y(0), G.cols * ts, G.rows * ts);
    stroke(ctx, "#555", 1.5, [8, 5]);
    label(ctx, "scored window: tissue outside it was not analysed", X(0) + 6, Y(0) - 6, "#333");
  }
  if (S.show.has("regions")) {
    for (const reg of ov.regions) {
      segments(ctx, reg.outline, ox, oy, ts);
      stroke(ctx, RISK_COLORS[reg.level], 2.5);
      label(ctx, `${reg.card} · level ${reg.level}`, X(reg.col + 0.5) + 6, Y(reg.row + 0.5), "#7b241c");
    }
  }
  if (S.show.has("islands")) {
    for (const isl of ov.islands) {
      segments(ctx, isl.outline, ox, oy, ts);
      stroke(ctx, "#6c3483", 2, [5, 3]);
      if (ts >= 5) label(ctx, isl.island, X(isl.col + 1) + 4, Y(isl.row + 0.5), "#6c3483");
    }
  }
  if (S.show.has("front") && ov.front.length) {
    segments(ctx, ov.front, ox, oy, ts);
    stroke(ctx, "#111", 2);
  }
  if (S.show.has("nuclei") && k >= NUCLEI_MIN && ov.counted) {
    const paths = CELL_COLORS.map(() => new Path2D());
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        const flat = ov.cells[r + "_" + c];
        if (!flat) continue;
        const tx = X(c), ty = Y(r);
        for (let j = 0; j < flat.length; j += 4) {
          const x = tx + flat[j] * k, y = ty + flat[j + 1] * k, rad = Math.max(1.6, flat[j + 2] * k);
          paths[flat[j + 3]].moveTo(x + rad, y);
          paths[flat[j + 3]].arc(x, y, rad, 0, 2 * Math.PI);
        }
      }
    }
    ctx.lineWidth = 1.5;
    paths.forEach((path, kind) => {
      ctx.strokeStyle = CELL_COLORS[kind];
      if (kind === 3) { ctx.fillStyle = "rgba(142,68,173,0.55)"; ctx.fill(path); }
      ctx.stroke(path);
    });
  }
  if (S.show.has("breakaway")) {
    for (const i of ov.buds) {
      const x = X(T.c[i] + 0.5), y = Y(T.r[i] + 0.5);
      const d = Math.min(Math.max(2.5, 0.3 * ts), 5) + Math.min(T.bud[i], 6) * Math.min(1, ts / 12);
      ctx.beginPath();
      ctx.moveTo(x, y - d); ctx.lineTo(x + d, y); ctx.lineTo(x, y + d); ctx.lineTo(x - d, y);
      ctx.closePath();
      ctx.fillStyle = "#8e44ad";
      ctx.fill();
      ctx.lineWidth = 1;
      ctx.strokeStyle = "#fff";
      ctx.stroke();
    }
    const hs = ov.hotspot;
    if (hs) {
      const x = X(hs.col + 0.5), y = Y(hs.row + 0.5), rad = hs.radius_tiles * ts;
      ctx.beginPath();
      ctx.arc(x, y, rad, 0, 2 * Math.PI);
      stroke(ctx, "#8e44ad", 2.5, [7, 4]);
      label(ctx, `counting field 0.785 mm²: ${hs.buds_in_field} candidate cluster(s)`,
            x - rad, y - rad - 6, "#6c3483");
    }
  }
  if (S.show.has("arcs")) {
    for (const a of ov.arcs) {
      const x = X(a.col), y = Y(a.row), rad = a.dir * Math.PI / 180;
      const len = Math.max(28, Math.min(150, (4 + 14 * a.push) * ts));
      const x2 = x + len * Math.cos(rad), y2 = y - len * Math.sin(rad);
      const color = a.pattern === "infiltrative" ? "#c0392b" : "#34495e";
      arrow(ctx, x, y, x2, y2, color);
      label(ctx, a.arc, x2 + 5, y2 - 5, color);
      p.hits.push({kind: "arc", x: x, y: y, x2: x2, y2: y2, a: a});
    }
  }
  if (S.show.has("pointers")) {
    ov.queue.forEach((q, n) => {
      const x = X(q.col + 0.5), y = Y(q.row + 0.5), side = Math.max(18, ts);
      ctx.beginPath();
      ctx.rect(x - side / 2, y - side / 2, side, side);
      stroke(ctx, "#00bcd4", n === p.cur ? 4 : 2.5);
      label(ctx, q.pointer, x + side / 2 + 4, y - side / 2 + 2, "#006064");
      p.hits.push({kind: "pointer", x: x, y: y, r: side / 2 + 6, q: q});
    });
  }
  scaleBar(ctx, k, H);
}

function scaleBar(ctx, k, H) {
  let um = 5;
  for (const v of [5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]) if (v * k <= 150) um = v;
  const w = um * k, x = 12, y = H - 16;
  ctx.fillStyle = "rgba(255,255,255,0.85)";
  ctx.fillRect(x - 6, y - 18, w + 12, 26);
  ctx.fillStyle = "#111";
  ctx.fillRect(x, y, w, 4);
  ctx.font = "12px 'Source Sans Pro', system-ui, sans-serif";
  ctx.fillText(um >= 1000 ? `${um / 1000} mm` : `${um} µm`, x, y - 5);
}

// --- hover ----------------------------------------------------------------------------------

function nearSegment(px, py, h) {
  const dx = h.x2 - h.x, dy = h.y2 - h.y, len = dx * dx + dy * dy || 1;
  const t = Math.max(0, Math.min(1, ((px - h.x) * dx + (py - h.y) * dy) / len));
  return Math.hypot(px - (h.x + t * dx), py - (h.y + t * dy)) < 7;
}

function compass(deg) {
  return ["right", "upper right", "up", "upper left", "left", "lower left", "down",
          "lower right"][Math.floor(((deg + 22.5) % 360) / 45)];
}

function tileTip(p, pos) {
  const ov = p.ov, G = ov.grid, T = ov.tiles;
  const [r, c] = gridAt(p, pos);
  if (r < 0 || c < 0 || r >= G.rows || c >= G.cols) {
    return p.src.window ? "<i>Outside the scored window: not analysed.</i>" : null;
  }
  const i = ov.idx[r * G.cols + c];
  if (i < 0) return null;
  const parts = [`<b>r${r}c${c}</b>`];
  if (T.qc[i]) parts.push(`excluded by quality control: ${esc(ov.qcs[T.qc[i]])}`);
  else parts.push(`<b>${esc(ov.classes[T.cls[i]].label)}</b>, top score ${T.top[i]}%` +
                  (T.unsure[i] ? " · <b>unsure here</b>" : "") + " <i>(model inference)</i>");
  const zone = ov.zones[T.zone[i]] || "no zone", d = T.dist[i];
  parts.push(`${esc(zone)}` + (T.front[i] ? " · on the front line" : d === null ? "" :
             d < 0 ? ` · ${-d} µm inside the front` : ` · ${d} µm outside the front`));
  parts.push(T.n[i] < 0 ? "nuclei not counted here" :
             `${T.n[i]} nuclei, ${T.ly[i]} lymphocyte-like, ${T.bud[i]} breakaway cluster(s)`);
  if (T.pts[i]) parts.push(`risk ${T.pts[i]} points, level ${T.risk[i]} (placeholder points)`);
  if (T.til && T.til[i] >= 0) parts.push(`second model: ${esc(TIL[T.til[i]][0])} <i>(WSInfer ` +
                                         `TIL, model inference)</i>`);
  if (S.show.has("nuclei") && p.view.k >= NUCLEI_MIN) {
    const flat = ov.cells[r + "_" + c];
    if (flat) {
      const tx = p.view.ox + c * p.view.ts, ty = p.view.oy + r * p.view.ts, k = p.view.k;
      for (let j = 0; j < flat.length; j += 4) {
        const rad = Math.max(1.6, flat[j + 2] * k) + 2;
        if (Math.hypot(pos.x - (tx + flat[j] * k), pos.y - (ty + flat[j + 1] * k)) <= rad) {
          parts.push(`nucleus: <b>${esc(ov.cell_kinds[flat[j + 3]])}</b>, area ` +
                     `${Math.round(Math.PI * flat[j + 2] ** 2)} µm² <i>(StarDist, not ` +
                     `validated on breast here)</i>`);
          break;
        }
      }
    }
  }
  return parts.join("<br>");
}

function hover(p, pos, ev) {
  const tip = $("tip");
  if (!p.ov || !p.view || !ev) { tip.style.display = "none"; return; }
  let html = null;
  for (const h of p.hits) {
    if (h.kind === "pointer" && Math.hypot(pos.x - h.x, pos.y - h.y) < h.r) {
      html = `<b>${esc(h.q.pointer)}</b> · ${esc(h.q.what)}<br>check by eye: ${esc(h.q.check)}` +
             `<br><i>${esc(h.q.evidence)}; ${esc(h.q.status)}</i>`;
      break;
    }
    if (h.kind === "arc" && nearSegment(pos.x, pos.y, h)) {
      const a = h.a;
      html = `<b>${esc(a.arc)}</b> · ${esc(a.pattern)} · invading ${compass(a.dir)} ` +
             `(${Math.round(a.dir)}°)<br>push ${a.push.toFixed(2)} · roughness ${pct(a.rough)} · ` +
             `faces ${esc(a.faces.toLowerCase())} · ${a.length_mm} mm of front<br>` +
             "<i>a hypothesis about this section, not a forecast</i>";
      break;
    }
  }
  if (!html) html = tileTip(p, pos);
  if (!html) { tip.style.display = "none"; return; }
  tip.innerHTML = html;
  tip.style.display = "block";
  const x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 4);
  const y = ev.clientY + 16 + tip.offsetHeight > window.innerHeight
    ? ev.clientY - tip.offsetHeight - 10 : ev.clientY + 16;
  tip.style.left = Math.max(2, x) + "px";
  tip.style.top = Math.max(2, y) + "px";
}

// --- legend ---------------------------------------------------------------------------------

function swatches(items) {
  return items.map(([text, color]) => `<span class="sw" style="background:${color}"></span>` +
                   esc(text)).join("");
}

function legend() {
  const ov = (S.panes.find(p => p.ov) || {}).ov;
  const rows = [];
  if (ov) {
    const fills = {
      tissue: ov.classes.map(c => [c.label, c.color]).concat([["excluded by quality control",
                                                               "#bbbbbb"]]),
      certainty: [["unsure here (top score below the placeholder cutoff)", "#f39c12"],
                  ["excluded", "#bbbbbb"], ["confident: no colour", "transparent"]],
      qc: Object.entries(QC_COLORS).map(([k, c]) => [k + (k === "unlike training tissue"
        ? ": not scored (calibrated rule)" : " (placeholder rule)"), c]),
      zones: [["front line", "#111111"], ["core", ZONE_COLORS.core],
              ["front band ± 500 µm", ZONE_COLORS["front band"]],
              ["peritumoral 0.5–2 mm", ZONE_COLORS.peritumoral]],
      immune: IMMUNE.map(([t, c]) => ["lymphocyte-like nuclei " + t, c])
        .concat([["not counted: no colour", "transparent"]]),
      risk: [["level 1", RISK_COLORS[1]], ["level 2", RISK_COLORS[2]], ["level 3", RISK_COLORS[3]]]
        .map(([t, c]) => [t + " (placeholder points)", c]),
      til: TIL.concat([["not scored: no colour", "transparent"]]),
    };
    if (fills[S.fill]) rows.push(`<b>Tiles</b>${swatches(fills[S.fill])}`);
    rows.push("<b>Marks</b>" + swatches([["front line", "#111"],
      ["arrow: infiltrative arc (length by push)", "#c0392b"], ["arrow: pushing arc", "#34495e"],
      ["breakaway candidates and the dashed counting field", "#8e44ad"],
      ["pointers T1…", "#00bcd4"], ["islands (dashed)", "#6c3483"]]));
    const anyCells = S.panes.some(p => p.ov && p.ov.counted);
    rows.push("<b>Nuclei</b>" + (anyCells
      ? swatches(ov.cell_kinds.map((t, i) => [t, CELL_COLORS[i]])) +
        " · drawn from about 0.5 screen px per µm; circles of the nucleus's area, not its outline"
      : " not counted on this section"));
  }
  rows.push("<i>Tile classes are model inferences (a BCSS head on GigaPath-Flash embeddings)." +
            "The front, zones, arcs, islands, counting field and risk points are rules on those " +
            "inferences, with placeholder cutoffs. The arrows are a hypothesis about where the " +
            "tumor is invading in this section, not a forecast. Nuclei: StarDist " +
            "2D_versatile_he, pretrained, not validated on breast here. The second lymphocyte " +
            "model (WSInfer TIL InceptionV4, CC BY 4.0) is a model inference on the centre 50 " +
            "µm of front-band and peritumoral tiles; where it disagrees with the head is a " +
            "place to look, not a verdict. Not reviewed by a pathologist.</i>");
  $("legend").innerHTML = rows.map(r => `<div class="row">${r}</div>`).join("");
}

// --- protocol -------------------------------------------------------------------------------

window.addEventListener("message", ev => {
  if (ev.data && ev.data.type === "streamlit:render") render(ev.data.args, ev.data.theme);
});
new ResizeObserver(() => ST.height(Math.ceil(document.body.getBoundingClientRect().height) + 4))
  .observe(document.body);
controls();
ST.ready();
