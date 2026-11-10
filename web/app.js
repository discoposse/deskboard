/* Deskboard frontend. One file, three modes:
   /                   kiosk board (tile grid that always fits the screen)
   /?config            drag-and-drop configurator that edits the board through its API
   /?tilepreview=<id>  one catalog tile at every span, for building and checking tiles
   Plain DOM, no frameworks, no external network (except user-configured embeds). */
"use strict";

const STAT_LABELS = { temp: "Temp", load: "Load", free: "Free", up: "Up" };
const STAT_FIELDS = ["temp", "load", "free", "up"];
const PARAMS = new URLSearchParams(location.search);
const LIVE_TYPES = new Set(["weather", "calendar", "github", "rss", "status"]);
const ALL_TYPES = [
  "clock",
  "worldclocks",
  "stats",
  "note",
  "markdown",
  "metric",
  "list",
  "weather",
  "countdown",
  "calendar",
  "github",
  "embed",
  "rss",
  "image",
  "timer",
  "status",
  "theme_card",
];
const SINGLETONS = new Set(["clock", "stats", "worldclocks"]);
// Types drawn by this file. Everything else comes from the tile catalog (tiles/).
const BUILTIN_TYPES = new Set(ALL_TYPES.filter((t) => t !== "metric"));
const MARKET_HOURS = {
  "America/New_York": { open: [9, 30], close: [16, 0], days: [1, 2, 3, 4, 5] },
  "Europe/London": { open: [8, 0], close: [16, 30], days: [1, 2, 3, 4, 5] },
  "Asia/Tokyo": { open: [9, 0], close: [15, 0], days: [1, 2, 3, 4, 5] },
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/* ---------- tile catalog ---------- */

// Metadata from GET /api/tiles for enabled tiles, and the render functions
// their render.js files register.
const TILE_CATALOG = new Map();
const TILE_RENDERERS = new Map();
const TILE_TAGS = new Set(["div", "p", "span", "strong", "em", "b", "i", "small", "ul", "ol", "li", "br", "blockquote", "figure", "figcaption"]);
const TILE_CLASS = /^[a-z][a-z0-9_-]{0,63}$/;

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const TILE_HELPERS = Object.freeze({ escape: escapeHtml });

window.DeskboardTiles = Object.freeze({
  register(id, def) {
    if (typeof id !== "string" || !TILE_CATALOG.has(id) || TILE_RENDERERS.has(id)) return;
    if (!def || typeof def.render !== "function") return;
    TILE_RENDERERS.set(id, def.render);
  },
});

// Rebuild tile markup from a short list of text tags. Every attribute except
// class is dropped, and anything else (scripts, images, links, styles) is removed.
function safeFragment(html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = String(html == null ? "" : html);
  const out = document.createDocumentFragment();
  const copy = (src, dst) => {
    for (const node of src.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) {
        dst.append(document.createTextNode(node.nodeValue));
      } else if (node.nodeType === Node.ELEMENT_NODE && TILE_TAGS.has(node.localName)) {
        const next = document.createElement(node.localName);
        const classes = String(node.getAttribute("class") || "")
          .split(/\s+/)
          .filter((c) => TILE_CLASS.test(c));
        if (classes.length) next.className = classes.join(" ");
        copy(node, next);
        dst.append(next);
      }
    }
  };
  copy(tpl.content, out);
  return out;
}

function deepFreeze(value) {
  if (value && typeof value === "object") {
    for (const key of Object.keys(value)) deepFreeze(value[key]);
    Object.freeze(value);
  }
  return value;
}

function isCatalogType(type) {
  return TILE_CATALOG.has(type);
}

function knownType(type) {
  return BUILTIN_TYPES.has(type) || TILE_CATALOG.has(type);
}

function loadTileAssets(meta, version) {
  const id = encodeURIComponent(meta.id);
  const v = encodeURIComponent(String(version || 0));
  const waits = [];
  if (meta.has_css) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.dataset.tileAsset = meta.id;
    link.href = `/tiles/${id}/tile.css?v=${v}`;
    waits.push(new Promise((resolve) => (link.onload = link.onerror = resolve)));
    document.head.append(link);
  }
  const script = document.createElement("script");
  script.dataset.tileAsset = meta.id;
  script.src = `/tiles/${id}/render.js?v=${v}`;
  waits.push(new Promise((resolve) => (script.onload = script.onerror = resolve)));
  document.head.append(script);
  return Promise.all(waits);
}

let tileCatalogLoad = null;
let tileCatalogAll = [];
let tileCatalogVersion = null;

// Load the catalog once. A failed request is retried on the next call.
function loadTileCatalog() {
  if (!tileCatalogLoad) {
    tileCatalogLoad = (async () => {
      const res = await fetch("/api/tiles", { cache: "no-store" });
      if (!res.ok) throw new Error(`GET /api/tiles: ${res.status}`);
      const data = await res.json();
      tileCatalogAll = Array.isArray(data.tiles) ? data.tiles : [];
      tileCatalogVersion = data.version;
      const fresh = [];
      for (const meta of tileCatalogAll) {
        if (!meta || !meta.enabled || TILE_CATALOG.has(meta.id)) continue;
        TILE_CATALOG.set(meta.id, deepFreeze(meta));
        fresh.push(meta);
      }
      await Promise.all(fresh.map((meta) => loadTileAssets(meta, data.version)));
    })().catch((err) => {
      tileCatalogLoad = null;
      throw err;
    });
  }
  return tileCatalogLoad;
}

// After POST /api/reload: drop every tile renderer and stylesheet, then load
// the catalog again. The version in each asset URL skips the browser cache.
function dropTileCatalog() {
  TILE_CATALOG.clear();
  TILE_RENDERERS.clear();
  for (const node of document.querySelectorAll("[data-tile-asset]")) node.remove();
  tileCatalogLoad = null;
}

function reloadTileCatalog() {
  dropTileCatalog();
  return loadTileCatalog();
}

function zonedParts(date, timeZone) {
  const out = {};
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hourCycle: "h23",
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  for (const part of fmt.formatToParts(date)) {
    if (part.type !== "literal") out[part.type] = part.value;
  }
  if (out.hour === "24") out.hour = "00";
  return out;
}

function inNight(hour, start, end) {
  if (start === end) return false;
  if (start < end) return hour >= start && hour < end;
  return hour >= start || hour < end;
}

function formatUptime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatFree(bytes) {
  const gb = Number(bytes) / 1024 / 1024 / 1024;
  return Number.isFinite(gb) ? `${gb.toFixed(1)} GB` : "-";
}

function sortWidgets(widgets) {
  return widgets
    .filter((w) => w && typeof w === "object")
    .slice()
    .sort((a, b) => (Number(a.order) || 0) - (Number(b.order) || 0) || String(a.id).localeCompare(String(b.id)));
}

function clampSpan(value) {
  const n = Number(value);
  return n === 2 ? 2 : 1;
}

function planGrid(n, hasClock, colsHint, rowsHint) {
  const cols = Number.isInteger(colsHint) && colsHint > 0 ? colsHint : null;
  const rows = Number.isInteger(rowsHint) && rowsHint > 0 ? rowsHint : null;
  if (!hasClock) {
    if (n === 0) return { cols: cols || 1, rows: rows || 1, hero: null };
    const c = cols || (n <= 3 ? n : n === 4 ? 2 : n <= 6 ? 3 : 4);
    return { cols: c, rows: rows || Math.ceil(n / c), hero: null };
  }
  if (n === 0) return { cols: cols || 1, rows: rows || 1, hero: "full" };
  const c = cols || (n <= 3 ? n : n === 4 ? 2 : n <= 6 ? 3 : 4);
  const r = rows || (n <= 3 ? 1 : n <= 8 ? 2 : 3);
  if (n <= 8) return { cols: c, rows: r, hero: "row", heroFr: n <= 3 ? 0.78 : n <= 6 ? 0.62 : 0.6 };
  return { cols: c, rows: r, hero: "cell", heroSpan: Math.max(1, Math.min(2, 12 - n)) };
}

function px(value) {
  return parseFloat(value) || 0;
}

function innerBox(node) {
  const cs = getComputedStyle(node);
  return {
    w: node.clientWidth - px(cs.paddingLeft) - px(cs.paddingRight),
    h: node.clientHeight - px(cs.paddingTop) - px(cs.paddingBottom),
  };
}

function overflows(node) {
  return node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1;
}

function fontStack(name, fallback) {
  const cleaned = String(name || "").trim();
  if (!cleaned) return fallback;
  if (/^ui-/.test(cleaned) || cleaned.includes(",")) return cleaned;
  return `"${cleaned}", ${fallback}`;
}

function applyThemeVars(target, theme) {
  if (!theme || typeof theme !== "object") return;
  const vars = theme.variables || {};
  for (const [key, value] of Object.entries(vars)) {
    if (typeof key === "string" && key.startsWith("--") && value != null) {
      target.style.setProperty(key, String(value));
      document.documentElement.style.setProperty(key, String(value));
    }
  }
  const fonts = theme.fonts || {};
  target.style.setProperty("--font-ui", fontStack(fonts.ui, "sans-serif"));
  target.style.setProperty("--font-display", fontStack(fonts.display, "serif"));
  target.style.setProperty("--font-mono", fontStack(fonts.mono, "monospace"));
  document.documentElement.style.setProperty("--font-ui", fontStack(fonts.ui, "sans-serif"));
  document.documentElement.style.setProperty("--font-display", fontStack(fonts.display, "serif"));
  document.documentElement.style.setProperty("--font-mono", fontStack(fonts.mono, "monospace"));
  target.classList.toggle("tiling", Boolean(theme.tiling));
}

async function loadTheme(themeId) {
  if (!themeId) return null;
  try {
    const res = await fetch(`/themes/${encodeURIComponent(themeId)}/theme.json`, { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch (_err) {
    return null;
  }
}

function stripHtmlTags(text) {
  return String(text || "").replace(/<[^>]*>/g, "");
}

function appendInlineMarkdown(parent, text) {
  const src = stripHtmlTags(text);
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let match;
  while ((match = re.exec(src))) {
    if (match.index > last) parent.append(document.createTextNode(src.slice(last, match.index)));
    const token = match[0];
    if (token.startsWith("**")) parent.append(el("strong", null, token.slice(2, -2)));
    else if (token.startsWith("*")) parent.append(el("em", null, token.slice(1, -1)));
    else parent.append(el("code", null, token.slice(1, -1)));
    last = match.index + token.length;
  }
  if (last < src.length) parent.append(document.createTextNode(src.slice(last)));
}

function renderMarkdownSafe(text) {
  const root = el("div", "md-body");
  const lines = stripHtmlTags(text).replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }
    const heading = trimmed.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      const node = el(`h${heading[1].length}`);
      appendInlineMarkdown(node, heading[2]);
      root.append(node);
      i += 1;
      continue;
    }
    if (/^([-*+]|\d+[.)])\s+/.test(trimmed)) {
      const ordered = /^\d+[.)]\s+/.test(trimmed);
      const list = el(ordered ? "ol" : "ul");
      while (i < lines.length) {
        const row = lines[i].trim();
        if (!/^([-*+]|\d+[.)])\s+/.test(row)) break;
        const li = el("li");
        appendInlineMarkdown(li, row.replace(/^([-*+]|\d+[.)])\s+/, ""));
        list.append(li);
        i += 1;
      }
      root.append(list);
      continue;
    }
    const p = el("p");
    appendInlineMarkdown(p, trimmed);
    root.append(p);
    i += 1;
  }
  return root;
}

function makeAnalogFace(showSeconds) {
  const face = el("div", "analog-face");
  const hour = el("div", "hand hour");
  const minute = el("div", "hand minute");
  const second = showSeconds ? el("div", "hand second") : null;
  const pivot = el("div", "pivot");
  face.append(hour, minute);
  if (second) face.append(second);
  face.append(pivot);
  return { face, hour, minute, second };
}

function setAnalogHands(parts, nodes) {
  const h = Number(parts.hour) % 12;
  const m = Number(parts.minute);
  const s = Number(parts.second);
  nodes.hour.style.transform = `rotate(${h * 30 + m * 0.5}deg)`;
  nodes.minute.style.transform = `rotate(${m * 6 + s * 0.1}deg)`;
  if (nodes.second) nodes.second.style.transform = `rotate(${s * 6}deg)`;
}

function marketOpen(zone, date) {
  let parts;
  try {
    parts = zonedParts(date, zone);
  } catch (_err) {
    return false;
  }
  const weekdayMap = { Monday: 1, Tuesday: 2, Wednesday: 3, Thursday: 4, Friday: 5, Saturday: 6, Sunday: 0 };
  const dow = weekdayMap[parts.weekday];
  const mins = Number(parts.hour) * 60 + Number(parts.minute);
  const spec = MARKET_HOURS[zone] || { open: [9, 0], close: [17, 0], days: [1, 2, 3, 4, 5] };
  if (!spec.days.includes(dow)) return false;
  const open = spec.open[0] * 60 + spec.open[1];
  const close = spec.close[0] * 60 + spec.close[1];
  return mins >= open && mins < close;
}

function hostOf(url) {
  try {
    return new URL(url).hostname || "site";
  } catch (_err) {
    return "site";
  }
}

function sparklineSvg(values) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "sparkline");
  svg.setAttribute("viewBox", "0 0 100 36");
  svg.setAttribute("preserveAspectRatio", "none");
  const nums = (Array.isArray(values) ? values : []).map(Number).filter((n) => Number.isFinite(n));
  if (nums.length < 2) return svg;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = Math.max(1, max - min);
  const points = nums
    .map((n, i) => {
      const x = (i / (nums.length - 1)) * 100;
      const y = 32 - ((n - min) / span) * 28;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  poly.setAttribute("points", points);
  svg.appendChild(poly);
  return svg;
}

function remainingTo(targetIso, now = Date.now()) {
  const ms = Date.parse(targetIso);
  if (!Number.isFinite(ms)) return { text: "-", done: true };
  const diff = Math.max(0, ms - now);
  if (diff <= 0) return { text: "Now", done: true };
  const days = Math.floor(diff / 86400000);
  const hours = Math.floor((diff % 86400000) / 3600000);
  const mins = Math.floor((diff % 3600000) / 60000);
  if (days > 0) return { text: `${days}d ${hours}h`, done: false };
  if (hours > 0) return { text: `${hours}h ${mins}m`, done: false };
  return { text: `${mins}m`, done: false };
}

function mmss(totalSec) {
  const sec = Math.max(0, Math.floor(totalSec));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

class Board {
  constructor(root, options = {}) {
    this.root = root;
    this.options = options;
    this.timezone = "UTC";
    this.nightDim = true;
    this.nightStart = 22;
    this.nightEnd = 7;
    this.themeId = "warm-dark";
    this.themeMeta = null;
    this.gridCols = null;
    this.gridRows = null;
    this.drawn = null;
    this.lastDate = "";
    this.clockTile = null;
    this.clockWidget = null;
    this.liveCache = {};
    this.timerStarts = {};
    this.analogNodes = [];
    this.worldNodes = [];
    this.countdownNodes = [];
    this.timerNodes = [];
    root.classList.add("board");
    clear(root);
    root.append(el("div", "glow"));
    const header = el("header");
    this.markNode = el("p", "mark", "DESK");
    this.zoneNode = el("p", "zone", "UTC");
    header.append(this.markNode, this.zoneNode);
    this.grid = el("main", "grid");
    const footer = el("footer");
    this.statsNode = el("div", "stats");
    this.hostNode = el("p", "host", "");
    footer.append(this.statsNode, this.hostNode);
    this.header = header;
    this.footer = footer;
    root.append(header, this.grid, footer);
    this.statNodes = {};
    this.status = null;
  }

  setScale(width, height) {
    const u = Math.max(0.45, Math.min(width / 1920, height / 1080));
    this.root.style.setProperty("--u", u.toFixed(4));
    this.u = u;
  }

  applyConfig(data) {
    if (!data) return;
    if (typeof data.mark === "string" && data.mark) this.markNode.textContent = data.mark;
    else this.markNode.textContent = "DESK";
    if (typeof data.timezone === "string" && data.timezone) {
      try {
        new Intl.DateTimeFormat("en-GB", { timeZone: data.timezone });
        this.timezone = data.timezone;
      } catch (_err) {
        this.timezone = "UTC";
      }
    }
    if (typeof data.night_dim === "boolean") this.nightDim = data.night_dim;
    if (Number.isInteger(data.night_start)) this.nightStart = data.night_start;
    if (Number.isInteger(data.night_end)) this.nightEnd = data.night_end;
    if (typeof data.hostname === "string" && data.hostname) this.hostNode.textContent = data.hostname;
    if (typeof data.theme === "string" && data.theme) this.themeId = data.theme;
    if (Number.isInteger(data.grid_cols)) this.gridCols = data.grid_cols;
    if (Number.isInteger(data.grid_rows)) this.gridRows = data.grid_rows;
    this.paintZone();
  }

  async applyTheme(themeId) {
    const id = themeId || this.themeId || "warm-dark";
    this.themeId = id;
    const theme = await loadTheme(id);
    if (theme) {
      this.themeMeta = theme;
      applyThemeVars(this.root, theme);
    }
  }

  paintZone() {
    let text = this.timezone;
    try {
      const name = new Intl.DateTimeFormat("en-GB", { timeZone: this.timezone, timeZoneName: "short" })
        .formatToParts(new Date())
        .find((part) => part.type === "timeZoneName");
      if (name) text = name.value;
    } catch (_err) {
      text = "UTC";
    }
    this.zoneNode.textContent = text;
  }

  paintStats(data) {
    if (!data) return;
    this.status = data;
    const values = {
      temp: data.temp_c == null ? "-" : `${Math.round(data.temp_c)}°`,
      load: data.load1 == null ? "-" : Number(data.load1).toFixed(2),
      free: formatFree(data.mem_available),
      up: formatUptime(data.uptime_sec),
    };
    for (const [id, text] of Object.entries(values)) {
      const node = this.statNodes[id];
      if (node) node.textContent = text;
    }
    this.guardFooter();
  }

  paintClock() {
    let parts;
    try {
      parts = zonedParts(new Date(), this.timezone);
    } catch (_err) {
      this.timezone = "UTC";
      parts = zonedParts(new Date(), "UTC");
    }
    const night = this.nightDim && inNight(Number(parts.hour), this.nightStart, this.nightEnd);
    this.root.classList.toggle("night", night);
    if (this.clockTile && this.clockWidget) {
      const style = this.clockWidget.style === "analog" ? "analog" : "digital";
      if (style === "digital") {
        if (this.hmNode) this.hmNode.textContent = `${parts.hour}:${parts.minute}`;
        if (this.secNode) {
          this.secNode.textContent = parts.second;
          this.secNode.style.display = this.clockWidget.show_seconds === false ? "none" : "";
        }
        if (this.dateNode) {
          const date = `${parts.weekday}, ${parts.month} ${Number(parts.day)}`;
          if (date !== this.lastDate) {
            this.lastDate = date;
            this.dateNode.textContent = date;
            this.fitClock();
          }
          this.dateNode.style.display = this.clockWidget.show_date === false ? "none" : "";
        }
      } else if (this.clockAnalog) {
        setAnalogHands(parts, this.clockAnalog);
        if (this.dateNode) {
          const date = `${parts.weekday}, ${parts.month} ${Number(parts.day)}`;
          if (date !== this.lastDate) {
            this.lastDate = date;
            this.dateNode.textContent = date;
          }
          this.dateNode.style.display = this.clockWidget.show_date === false ? "none" : "";
        }
      }
    }
    for (const entry of this.analogNodes) setAnalogHands(zonedParts(new Date(), entry.zone), entry.nodes);
    for (const city of this.worldNodes) {
      const p = zonedParts(new Date(), city.zone);
      if (city.time) city.time.textContent = `${p.hour}:${p.minute}`;
      if (city.analog) setAnalogHands(p, city.analog);
      if (city.wrap) {
        const open = city.mark && marketOpen(city.zone, new Date());
        city.wrap.classList.toggle("open", open);
      }
    }
    for (const node of this.countdownNodes) {
      const rem = remainingTo(node.target);
      node.value.textContent = rem.text;
    }
    for (const node of this.timerNodes) {
      const started = this.timerStarts[node.id] || Date.now();
      const total = (Number(node.minutes) || 25) * 60;
      const left = Math.max(0, total - Math.floor((Date.now() - started) / 1000));
      node.display.textContent = mmss(left);
    }
    return parts;
  }

  setLiveData(id, payload) {
    this.liveCache[id] = payload;
    const safe = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(id) : String(id).replace(/["\\]/g, "\\$&");
    const tile = this.grid.querySelector(`[data-widget-id="${safe}"]`);
    if (!tile || !tile._livePaint) return;
    tile._livePaint(payload);
    this.fit();
  }

  setWidgets(widgets) {
    const signature = JSON.stringify({ widgets, theme: this.themeId, cols: this.gridCols, rows: this.gridRows });
    if (signature === this.drawn) return false;
    this.drawn = signature;
    this.render(widgets);
    return true;
  }

  render(widgets) {
    const enabled = sortWidgets(widgets).filter((w) => w.enabled !== false);
    const clock = enabled.find((w) => w.type === "clock");
    const stats = enabled.find((w) => w.type === "stats");
    const rest = enabled.filter((w) => w !== clock && w !== stats);

    this.renderStats(stats && Array.isArray(stats.fields) ? stats.fields : []);

    const grid = this.grid;
    clear(grid);
    this.clockTile = null;
    this.clockWidget = null;
    this.clockAnalog = null;
    this.lastDate = "";
    this.analogNodes = [];
    this.worldNodes = [];
    this.countdownNodes = [];
    this.timerNodes = [];
    for (const timer of this._embedTimers || []) clearInterval(timer);
    this._embedTimers = [];

    const plan = planGrid(rest.length, Boolean(clock), this.gridCols, this.gridRows);
    this.plan = plan;
    grid.style.gridTemplateColumns = `repeat(${plan.cols}, minmax(0, 1fr))`;
    if (plan.hero === "row") {
      grid.style.gridTemplateRows = `minmax(0, ${plan.heroFr}fr) repeat(${plan.rows}, minmax(0, 1fr))`;
    } else if (plan.hero === "full") {
      grid.style.gridTemplateRows = "minmax(0, 1fr)";
    } else {
      grid.style.gridTemplateRows = `repeat(${Math.max(1, plan.rows)}, minmax(0, 1fr))`;
    }

    if (clock) {
      const tile = this.renderClockTile(clock);
      if (plan.hero === "row" || plan.hero === "full") tile.style.gridColumn = "1 / -1";
      else {
        const span = clampSpan(clock.col_span) || plan.heroSpan || 1;
        tile.style.gridColumn = `span ${span}`;
        if (clampSpan(clock.row_span) > 1) tile.style.gridRow = `span ${clampSpan(clock.row_span)}`;
      }
      grid.append(tile);
    }

    for (const widget of rest) {
      const tile = this.renderWidget(widget);
      if (!tile) continue;
      const cs = clampSpan(widget.col_span);
      const rs = clampSpan(widget.row_span);
      if (cs > 1) tile.style.gridColumn = `span ${cs}`;
      if (rs > 1) tile.style.gridRow = `span ${rs}`;
      grid.append(tile);
    }

    if (!clock && rest.length === 0) grid.append(el("p", "empty-hint", "No tiles"));
    this.paintClock();
    if (this.status) this.paintStats(this.status);
    this.fit();
  }

  renderStats(fields) {
    clear(this.statsNode);
    this.statNodes = {};
    for (const field of fields) {
      if (!STAT_LABELS[field]) continue;
      const cell = el("div", "stat");
      cell.append(el("span", null, STAT_LABELS[field]));
      const strong = el("strong", null, "-");
      cell.append(strong);
      this.statNodes[field] = strong;
      this.statsNode.append(cell);
    }
  }

  renderClockTile(widget) {
    const tile = el("section", "tile hero clock-tile");
    tile.dataset.widgetId = widget.id || "clock";
    this.clockWidget = widget;
    const fit = el("div", "clock-fit");
    if (widget.style === "analog") {
      const wrap = el("div", "analog-wrap");
      const analog = makeAnalogFace(widget.show_seconds !== false);
      wrap.append(analog.face);
      this.dateNode = el("p", "date", "");
      if (widget.show_date !== false) wrap.append(this.dateNode);
      fit.append(wrap);
      this.clockAnalog = analog;
      this.hmNode = null;
      this.secNode = null;
    } else {
      const clock = el("div", "clock");
      this.hmNode = el("p", "hm", "00:00");
      this.secNode = el("p", "sec", "00");
      clock.append(this.hmNode, this.secNode);
      this.dateNode = el("p", "date", "");
      fit.append(clock, this.dateNode);
      this.clockAnalog = null;
    }
    tile.append(fit);
    this.clockTile = tile;
    this.clockFit = fit;
    return tile;
  }

  renderWidget(widget) {
    switch (widget.type) {
      case "list":
        return this.renderList(widget);
      case "note":
        return this.renderNote(widget);
      case "markdown":
        return this.renderMarkdown(widget);
      case "worldclocks":
        return this.renderWorldClocks(widget);
      case "weather":
        return this.renderWeather(widget);
      case "countdown":
        return this.renderCountdown(widget);
      case "calendar":
        return this.renderLiveList(widget, "calendar");
      case "rss":
        return this.renderLiveList(widget, "rss");
      case "github":
        return this.renderGithub(widget);
      case "embed":
        return this.renderEmbed(widget);
      case "image":
        return this.renderImage(widget);
      case "timer":
        return this.renderTimer(widget);
      case "status":
        return this.renderStatus(widget);
      case "theme_card":
        return this.renderThemeCard(widget);
      default:
        return TILE_RENDERERS.has(widget.type) ? this.renderCatalogTile(widget) : null;
    }
  }

  // Tiles from tiles/<id>/. render.js gets a frozen copy of the tile's fields
  // and returns markup, which goes through safeFragment before it is shown.
  renderCatalogTile(widget) {
    const meta = TILE_CATALOG.get(widget.type);
    const render = TILE_RENDERERS.get(widget.type);
    const tile = el("section", `tile tile-${widget.type}`);
    tile.dataset.widgetId = widget.id || "";
    tile.dataset.fit = meta.fit || "none";
    const data = { col_span: clampSpan(widget.col_span), row_span: clampSpan(widget.row_span) };
    for (const key of Object.keys(meta.fields || {})) {
      if (key in widget) data[key] = JSON.parse(JSON.stringify(widget[key]));
    }
    const body = el("div", "tile-body");
    try {
      body.append(safeFragment(render(deepFreeze(data), TILE_HELPERS)));
    } catch (err) {
      tile.classList.add("tile-error");
      clear(body);
      body.append(el("p", "metric-hint", `${meta.name} could not render`));
      console.error(`tile ${widget.type}`, err);
    }
    tile.append(body);
    return tile;
  }

  renderList(widget) {
    const tile = el("section", "tile list");
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    const ul = el("ul");
    const items = Array.isArray(widget.items) ? widget.items : [];
    for (const item of items) ul.append(el("li", null, String(item)));
    body.append(ul);
    tile.append(body);
    tile._items = items.map(String);
    return tile;
  }

  renderNote(widget) {
    const tile = el("section", "tile note");
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    body.append(el("p", "note-text", widget.text || ""));
    tile.append(body);
    return tile;
  }

  renderMarkdown(widget) {
    const tile = el("section", "tile note markdown");
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    body.append(renderMarkdownSafe(widget.text || ""));
    tile.append(body);
    return tile;
  }

  renderWorldClocks(widget) {
    const tile = el("section", "tile worldclocks");
    tile.dataset.widgetId = widget.id || "";
    const body = el("div", "tile-body");
    const row = el("div", "world-row");
    const style = widget.style || "analog";
    const cities = Array.isArray(widget.cities) ? widget.cities : [];
    for (const city of cities) {
      const wrap = el("div", "world-city");
      const label = el("p", "city-label", city.label || city.zone || "");
      wrap.append(label);
      let analog = null;
      if (style === "analog" || style === "both") {
        analog = makeAnalogFace(false);
        analog.face.classList.add("city-face");
        wrap.append(analog.face);
      }
      let time = null;
      if (style === "digital" || style === "both") {
        time = el("p", "city-time", "00:00");
        wrap.append(time);
      }
      if (widget.mark_markets) wrap.append(el("span", "market-dot"));
      row.append(wrap);
      this.worldNodes.push({ wrap, zone: city.zone || "UTC", time, analog, mark: Boolean(widget.mark_markets) });
    }
    body.append(row);
    tile.append(body);
    return tile;
  }

  renderWeather(widget) {
    const tile = el("section", "tile weather");
    tile.dataset.widgetId = widget.id || "";
    if (widget.label || widget.title) tile.append(el("p", "eyebrow", widget.label || widget.title || ""));
    const body = el("div", "tile-body");
    const temp = el("p", "weather-temp", "-");
    const meta = el("p", "weather-meta", "Loading");
    body.append(temp, meta);
    tile.append(body);
    tile._livePaint = (payload) => {
      if (!payload || !payload.ok) {
        temp.textContent = "-";
        meta.textContent = "Unavailable";
        return;
      }
      const unit = payload.units === "imperial" ? "°F" : "°C";
      const windUnit = payload.units === "imperial" ? "mph" : "km/h";
      temp.textContent = payload.temperature == null ? "-" : `${Math.round(payload.temperature)}${unit}`;
      const bits = [];
      if (widget.label) bits.push(widget.label);
      if (payload.high != null && payload.low != null) bits.push(`H ${Math.round(payload.high)} / L ${Math.round(payload.low)}`);
      if (payload.wind != null) bits.push(`Wind ${Math.round(payload.wind)} ${windUnit}`);
      meta.textContent = bits.join(" · ") || "Weather";
    };
    if (this.liveCache[widget.id]) tile._livePaint(this.liveCache[widget.id]);
    return tile;
  }

  renderCountdown(widget) {
    const tile = el("section", "tile countdown");
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    const value = el("p", "countdown-value", "-");
    const label = el("p", "countdown-label", widget.label || "");
    body.append(value);
    if (widget.label) body.append(label);
    tile.append(body);
    this.countdownNodes.push({ value, target: widget.target });
    return tile;
  }

  renderLiveList(widget, kind) {
    const tile = el("section", `tile list ${kind}`);
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    const ul = el("ul");
    body.append(ul);
    tile.append(body);
    tile._items = [];
    tile._livePaint = (payload) => {
      const items = payload && Array.isArray(payload.items) ? payload.items.map(String) : [];
      tile._items = items.length ? items : ["Nothing yet"];
      clear(ul);
      for (const item of tile._items) ul.append(el("li", null, item));
    };
    if (this.liveCache[widget.id]) tile._livePaint(this.liveCache[widget.id]);
    else tile._livePaint({ items: ["Loading"] });
    return tile;
  }

  renderGithub(widget) {
    const tile = el("section", "tile github");
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    tile.append(body);
    tile._livePaint = (payload) => {
      clear(body);
      const repos = payload && Array.isArray(payload.repos) ? payload.repos : [];
      if (!repos.length) {
        body.append(el("p", "metric-hint", "No repos"));
        return;
      }
      for (const repo of repos.slice(0, 3)) {
        const box = el("div", "gh-repo");
        box.append(el("p", "gh-name", repo.repo || ""));
        box.append(el("p", "gh-stars", repo.ok === false ? "-" : String(repo.stars ?? "-")));
        const today = repo.change_today == null ? 0 : repo.change_today;
        const week = repo.change_week == null ? 0 : repo.change_week;
        const sign = (n) => (n > 0 ? `+${n}` : String(n));
        box.append(el("p", "gh-change", `Today ${sign(today)} · Week ${sign(week)}`));
        if (Array.isArray(repo.sparkline) && repo.sparkline.length > 1) box.append(sparklineSvg(repo.sparkline));
        body.append(box);
      }
    };
    if (this.liveCache[widget.id]) tile._livePaint(this.liveCache[widget.id]);
    else tile._livePaint({ repos: (widget.repos || []).map((r) => ({ repo: r, stars: "-" })) });
    return tile;
  }

  renderEmbed(widget) {
    const tile = el("section", "tile embed");
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    const frame = el("iframe", "embed-frame");
    frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
    frame.setAttribute("referrerpolicy", "no-referrer");
    frame.setAttribute("loading", "lazy");
    frame.title = widget.title || "Embed";
    const fallback = el("div", "embed-fallback");
    fallback.hidden = true;
    fallback.append(el("p", "host", hostOf(widget.url)));
    fallback.append(el("p", "hint", "This site blocks embedding"));
    body.append(frame, fallback);
    tile.append(body);

    let failed = false;
    const showFallback = () => {
      failed = true;
      frame.hidden = true;
      fallback.hidden = false;
    };
    frame.addEventListener("error", showFallback);
    try {
      frame.src = widget.url || "";
    } catch (_err) {
      showFallback();
    }
    // Many sites refuse framing silently; reveal fallback after a short wait if blank.
    setTimeout(() => {
      try {
        if (!failed && frame.contentDocument == null) {
          /* cross-origin is expected; leave iframe visible */
        }
      } catch (_err) {
        /* ignore */
      }
    }, 2500);

    const refreshSec = Math.max(30, Number(widget.refresh_sec) || 300);
    if (!this.options.preview) {
      const timer = setInterval(() => {
        if (failed) return;
        try {
          frame.src = widget.url;
        } catch (_err) {
          showFallback();
        }
      }, refreshSec * 1000);
      this._embedTimers = this._embedTimers || [];
      this._embedTimers.push(timer);
    }
    return tile;
  }

  renderImage(widget) {
    const fit = widget.fit === "contain" ? "contain" : "cover";
    const tile = el("section", `tile image-tile fit-${fit}`);
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    const img = el("img");
    img.alt = widget.title || "";
    img.src = widget.src || "";
    img.decoding = "async";
    body.append(img);
    tile.append(body);
    return tile;
  }

  renderTimer(widget) {
    const tile = el("section", "tile timer");
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    const display = el("p", "timer-display", mmss((Number(widget.minutes) || 25) * 60));
    const mode = el("p", "timer-mode", widget.mode || "pomodoro");
    body.append(display, mode);
    tile.append(body);
    if (!this.timerStarts[widget.id]) this.timerStarts[widget.id] = Date.now();
    this.timerNodes.push({ id: widget.id, minutes: widget.minutes || 25, display });
    return tile;
  }

  renderStatus(widget) {
    const tile = el("section", "tile status");
    tile.dataset.widgetId = widget.id || "";
    if (widget.title) tile.append(el("p", "eyebrow", widget.title));
    const body = el("div", "tile-body");
    tile.append(body);
    tile._livePaint = (payload) => {
      clear(body);
      const rows = payload && Array.isArray(payload.targets) ? payload.targets : [];
      if (!rows.length) {
        body.append(el("p", "metric-hint", "No targets"));
        return;
      }
      for (const row of rows) {
        const line = el("div", `status-row${row.ok ? "" : " down"}`);
        line.append(el("span", "label", row.label || hostOf(row.url)));
        line.append(el("span", "pill", row.ok ? "ok" : "down"));
        line.append(el("span", "ms", row.ms != null ? `${row.ms} ms` : ""));
        body.append(line);
      }
    };
    if (this.liveCache[widget.id]) tile._livePaint(this.liveCache[widget.id]);
    else {
      const stubs = (widget.targets || []).map((t) => ({ label: t.label, url: t.url, ok: true, ms: null }));
      tile._livePaint({ targets: stubs });
    }
    return tile;
  }

  renderThemeCard(widget) {
    const tile = el("section", "tile theme-card-tile");
    tile.dataset.widgetId = widget.id || "";
    const body = el("div", "tile-body");
    const img = el("img");
    img.alt = widget.caption || widget.image || "";
    const imageId = widget.image || "default";
    let src = `/themes/${encodeURIComponent(this.themeId)}/images/${encodeURIComponent(imageId)}.svg`;
    if (this.themeMeta && Array.isArray(this.themeMeta.images)) {
      const hit = this.themeMeta.images.find((item) => item.id === imageId || item.file === imageId);
      if (hit && hit.file) src = `/themes/${encodeURIComponent(this.themeId)}/${hit.file.replace(/^\//, "")}`;
    }
    img.src = src;
    body.append(img);
    if (widget.caption) body.append(el("p", "caption", widget.caption));
    tile.append(body);
    return tile;
  }

  /* ---------- fitting ---------- */

  fit() {
    if (!this.root.isConnected) return;
    this.fitClock();
    const lists = [];
    for (const tile of this.grid.querySelectorAll(".tile")) {
      if (tile.classList.contains("list")) lists.push([tile, this.fitList(tile)]);
      else if (tile.classList.contains("note") && !tile.classList.contains("markdown")) this.fitNote(tile);
      else if (tile.classList.contains("markdown")) this.fitMarkdown(tile);
      else if (tile.dataset.fit === "metric") this.fitMetric(tile);
      else if (tile.dataset.fit === "text") this.fitText(tile);
      else if (tile.classList.contains("countdown") || tile.classList.contains("weather") || tile.classList.contains("timer")) {
        this.fitBigNumber(tile);
      }
    }
    const sizes = lists.filter(([, r]) => r && r.whole).map(([, r]) => r.size);
    if (sizes.length > 1) {
      const uniform = Math.min(...sizes);
      for (const [tile, r] of lists) {
        if (r && r.whole) tile.querySelector("ul").style.fontSize = `${uniform}px`;
      }
    }
    for (const [tile, r] of lists) if (r && r.whole) this.spreadList(tile);
    this.guardTiles();
    this.guardFooter();
  }

  fitClock() {
    const tile = this.clockTile;
    if (!tile || !tile.isConnected) return;
    const box = innerBox(tile);
    if (box.w <= 0 || box.h <= 0) return;
    const fit = this.clockFit;
    const u = this.u || 1;
    const fits = () =>
      fit.offsetWidth <= box.w + 0.5 &&
      fit.offsetHeight <= box.h + 0.5 &&
      tile.scrollHeight <= tile.clientHeight + 0.5 &&
      tile.scrollWidth <= tile.clientWidth + 0.5;

    if (this.clockWidget && this.clockWidget.style === "analog" && this.clockAnalog) {
      const face = this.clockAnalog.face;
      const date = this.dateNode;
      const showDate = !(this.clockWidget && this.clockWidget.show_date === false);
      if (date) date.style.display = showDate ? "" : "none";
      const cap = Math.min(box.w * 0.7, box.h * (showDate ? 0.72 : 0.9), 280 * u);
      let lo = 24;
      let hi = Math.max(lo, cap);
      const applyFace = (size) => {
        face.style.width = `${size}px`;
        face.style.height = `${size}px`;
        if (date) date.style.fontSize = `${Math.max(11, size * 0.14)}px`;
      };
      applyFace(lo);
      if (!fits()) {
        if (date && date.style.display !== "none") {
          date.style.display = "none";
          applyFace(lo);
        }
      }
      if (fits()) {
        for (let i = 0; i < 18; i += 1) {
          const mid = (lo + hi) / 2;
          applyFace(mid);
          if (fits()) lo = mid;
          else hi = mid;
        }
        applyFace(Math.floor(lo));
      }
      if (!fits() && date && date.style.display !== "none") {
        date.style.display = "none";
        applyFace(Math.max(24, Math.min(box.w, box.h) * 0.7));
      }
      fit.style.visibility = fits() ? "" : "hidden";
      return;
    }

    if (!this.hmNode || !this.secNode || !this.dateNode) return;
    const cap = (this.plan && this.plan.hero === "full" ? 380 : 300) * u;
    const apply = (s, side) => {
      fit.classList.toggle("side", side);
      this.hmNode.style.fontSize = `${s}px`;
      this.secNode.style.fontSize = `${s * 0.228}px`;
      this.dateNode.style.fontSize = `${Math.max(12, s * (side ? 0.24 : 0.2))}px`;
    };
    const best = (side) => {
      let lo = 8;
      let hi = cap;
      apply(lo, side);
      if (!fits()) return 0;
      for (let i = 0; i < 18; i += 1) {
        const mid = (lo + hi) / 2;
        apply(mid, side);
        if (fits()) lo = mid;
        else hi = mid;
      }
      return lo;
    };
    const stack = best(false);
    const side = best(true);
    const useSide = side > stack * 1.12;
    const size = Math.floor((useSide ? side : stack) * 10) / 10;
    apply(Math.max(size, 8), useSide);
    this.dateNode.style.display = this.clockWidget && this.clockWidget.show_date === false ? "none" : "";
    if (!fits() && this.dateNode.style.display !== "none") this.dateNode.style.display = "none";
    if (!fits()) fit.style.visibility = "hidden";
    else fit.style.visibility = "";
  }

  fitList(tile) {
    const body = tile.querySelector(".tile-body");
    const ul = body.querySelector("ul");
    if (!ul) return null;
    const u = this.u || 1;
    const items = tile._items || [];
    const build = (count) => {
      clear(ul);
      for (const item of items.slice(0, count)) ul.append(el("li", null, item));
      if (count < items.length) ul.append(el("li", "more", `+${items.length - count} more`));
    };
    build(items.length);
    const lis = () => Array.from(ul.children);
    const fitsH = () => body.scrollHeight <= body.clientHeight + 0.5;
    const fitsW = () => lis().every((li) => li.scrollWidth <= li.clientWidth + 0.5);
    const sizes = [];
    for (let s = 30; s >= 15; s -= 1) sizes.push(s * u);
    let firstH = null;
    for (const s of sizes) {
      ul.style.fontSize = `${s}px`;
      if (fitsH()) {
        if (firstH == null) firstH = s;
        if (fitsW() || s <= 24 * u) return { size: s, whole: true };
      }
    }
    if (firstH != null) {
      ul.style.fontSize = `${firstH}px`;
      return { size: firstH, whole: true };
    }
    ul.style.fontSize = `${15 * u}px`;
    for (let count = items.length - 1; count >= 0; count -= 1) {
      build(count);
      if (fitsH()) return { size: 15 * u, whole: false };
    }
    clear(ul);
    return { size: 15 * u, whole: false };
  }

  spreadList(tile) {
    const body = tile.querySelector(".tile-body");
    const ul = body.querySelector("ul");
    if (!ul) return;
    ul.style.lineHeight = "";
    for (let lh = 1.9; lh > 1.45; lh -= 0.05) {
      ul.style.lineHeight = lh.toFixed(2);
      if (body.scrollHeight <= body.clientHeight + 0.5) return;
    }
    ul.style.lineHeight = "";
  }

  fitNote(tile) {
    const body = tile.querySelector(".tile-body");
    const text = body.querySelector(".note-text");
    if (!text) return;
    const u = this.u || 1;
    text.classList.remove("clamped");
    text.style.webkitLineClamp = "";
    for (let s = 44; s >= 16; s -= 1) {
      text.style.fontSize = `${s * u}px`;
      if (body.scrollHeight <= body.clientHeight + 0.5 && body.scrollWidth <= body.clientWidth + 0.5) return;
    }
    const lineHeight = px(getComputedStyle(text).lineHeight) || 20;
    const lines = Math.max(1, Math.floor(body.clientHeight / lineHeight));
    text.classList.add("clamped");
    text.style.webkitLineClamp = String(lines);
    text.style.maxHeight = `${lines * lineHeight}px`;
  }

  fitMarkdown(tile) {
    const body = tile.querySelector(".tile-body");
    const md = body.querySelector(".md-body");
    if (!md) return;
    const u = this.u || 1;
    for (let s = 22; s >= 12; s -= 1) {
      md.style.fontSize = `${s * u}px`;
      if (body.scrollHeight <= body.clientHeight + 0.5) return;
    }
  }

  fitMetric(tile) {
    const body = tile.querySelector(".tile-body");
    const value = body.querySelector(".metric-value");
    if (!value) return;
    const u = this.u || 1;
    const box = innerBox(tile);
    let start = Math.min(96 * u, box.h * 0.6);
    for (let s = start; s >= 14 * u; s -= 2 * u) {
      value.style.fontSize = `${s}px`;
      if (value.scrollWidth <= value.clientWidth + 0.5 && body.scrollHeight <= body.clientHeight + 0.5) return;
    }
    value.style.fontSize = `${14 * u}px`;
  }

  // Catalog tiles with "fit": "text" shrink the .fit-text element (or the body)
  // until it fits. Size inner text in em so it scales along.
  fitText(tile) {
    const body = tile.querySelector(".tile-body");
    if (!body) return;
    const target = body.querySelector(".fit-text") || body;
    const u = this.u || 1;
    for (let s = 44; s >= 12; s -= 1) {
      target.style.fontSize = `${s * u}px`;
      if (body.scrollHeight <= body.clientHeight + 0.5 && body.scrollWidth <= body.clientWidth + 0.5) return;
    }
  }

  fitBigNumber(tile) {
    const body = tile.querySelector(".tile-body");
    const value = body.querySelector(".countdown-value, .weather-temp, .timer-display");
    if (!value) return;
    const u = this.u || 1;
    for (let s = 64; s >= 18; s -= 2) {
      value.style.fontSize = `${s * u}px`;
      if (body.scrollHeight <= body.clientHeight + 0.5 && value.scrollWidth <= value.clientWidth + 0.5) return;
    }
  }

  guardTiles() {
    for (const tile of this.grid.querySelectorAll(".tile:not(.hero)")) {
      const body = tile.querySelector(".tile-body");
      if (!body) continue;
      let guard = 0;
      while (overflows(body) && guard < 40) {
        guard += 1;
        const ul = body.querySelector("ul");
        if (ul && ul.lastElementChild) {
          ul.lastElementChild.remove();
          continue;
        }
        const last = Array.from(body.children).reverse().find((c) => c.style.display !== "none");
        if (!last) break;
        last.style.display = "none";
      }
      const eyebrow = tile.querySelector(".eyebrow");
      if (eyebrow && tile.scrollHeight > tile.clientHeight + 1) eyebrow.style.display = "none";
    }
  }

  guardFooter() {
    const cells = Array.from(this.statsNode.children);
    for (const cell of cells) cell.style.display = "";
    this.hostNode.style.display = "";
    for (let i = cells.length - 1; i >= 0 && overflows(this.footer); i -= 1) cells[i].style.display = "none";
    if (overflows(this.footer)) this.hostNode.style.display = "none";
  }
}

function overflowReport(root) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const bad = [];
  const tol = 0.5;
  const name = (node) => `${node.tagName.toLowerCase()}${node.className ? "." + String(node.className).trim().replace(/\s+/g, ".") : ""}`;
  const visible = (node) => {
    const cs = getComputedStyle(node);
    return cs.display !== "none" && cs.visibility !== "hidden";
  };
  for (const node of root.querySelectorAll("*")) {
    if (!visible(node)) continue;
    const r = node.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (r.left < -tol || r.top < -tol || r.right > vw + tol || r.bottom > vh + tol) {
      bad.push({ kind: "viewport", node: name(node), rect: [r.left, r.top, r.right, r.bottom].map(Math.round) });
    }
  }
  for (const tile of root.querySelectorAll(".tile")) {
    const t = tile.getBoundingClientRect();
    for (const node of tile.querySelectorAll("*")) {
      if (!visible(node)) continue;
      // Clock hands use transforms; their axis-aligned bounds can poke past the
      // circular face even when the face itself is clipped and inside the tile.
      if (node.classList.contains("hand") || node.classList.contains("pivot")) continue;
      const r = node.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      if (r.left < t.left - tol || r.top < t.top - tol || r.right > t.right + tol || r.bottom > t.bottom + tol) {
        bad.push({ kind: "tile", node: name(node), text: (node.textContent || "").slice(0, 40) });
      }
    }
  }
  for (const node of root.querySelectorAll(".tile, .tile-body, .grid, header, footer")) {
    if (overflows(node)) bad.push({ kind: "scroll", node: name(node), sh: node.scrollHeight, ch: node.clientHeight, sw: node.scrollWidth, cw: node.clientWidth });
  }
  if (root.scrollHeight > root.clientHeight + 1 || root.scrollWidth > root.clientWidth + 1) bad.push({ kind: "scroll", node: "board" });
  const ellipsized = Array.from(root.querySelectorAll(".list li, .metric-value, .metric-label, .metric-hint, .eyebrow")).filter(
    (n) => visible(n) && n.scrollWidth > n.clientWidth + 0.5,
  ).length;
  const more = Array.from(root.querySelectorAll("li.more")).map((n) => n.textContent);
  const hm = root.querySelector(".hm");
  const tileErrors = root.querySelectorAll(".tile-error").length;
  return {
    ok: bad.length === 0 && tileErrors === 0,
    tileErrors,
    viewport: [vw, vh],
    tiles: root.querySelectorAll(".tile").length,
    bad: bad.slice(0, 20),
    badCount: bad.length,
    ellipsized,
    more,
    clockPx: hm ? Math.round(px(hm.style.fontSize)) : null,
  };
}

/* ---------- kiosk mode ---------- */

function startKiosk() {
  document.documentElement.classList.add("kiosk");
  const root = el("div");
  clear(document.body);
  document.body.append(root);
  const board = new Board(root);
  const bootedAt = Date.now();
  let widgets = [];
  let themeReady = false;
  let tilesReady = false;

  const resize = () => {
    board.setScale(window.innerWidth, window.innerHeight);
    board.fit();
  };
  board.setScale(window.innerWidth, window.innerHeight);
  window.addEventListener("resize", resize);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => board.fit());

  let checked = false;

  async function refreshLive() {
    const live = widgets.filter((w) => w.enabled !== false && LIVE_TYPES.has(w.type));
    await Promise.all(
      live.map(async (w) => {
        try {
          const res = await fetch(`/api/widget-data/${encodeURIComponent(w.id)}`, { cache: "no-store" });
          if (!res.ok) return;
          const data = await res.json();
          board.setLiveData(w.id, data);
        } catch (_err) {
          /* soft fail */
        }
      }),
    );
  }

  async function refresh() {
    try {
      const [statusResponse, widgetResponse, configResponse] = await Promise.all([
        fetch("/api/status", { cache: "no-store" }),
        fetch("/api/widgets", { cache: "no-store" }),
        fetch("/api/config", { cache: "no-store" }),
      ]);
      if (!statusResponse.ok || !widgetResponse.ok) throw new Error("refresh failed");
      const status = await statusResponse.json();
      const body = await widgetResponse.json();
      const config = configResponse.ok ? await configResponse.json() : {};
      if (tilesReady && status.tiles_version != null && status.tiles_version !== tileCatalogVersion) {
        tilesReady = false;
        dropTileCatalog();
      }
      if (!tilesReady) {
        try {
          await loadTileCatalog();
          tilesReady = true;
          board.drawn = null;
        } catch (_err) {
          /* catalog tiles stay hidden until the next refresh */
        }
      }
      // applyConfig records the wanted theme id, so compare against the one painted before it.
      const paintedTheme = board.themeId;
      board.applyConfig({ ...status, ...config });
      const wantedTheme = config.theme || status.theme;
      if (!themeReady || paintedTheme !== wantedTheme) {
        await board.applyTheme(wantedTheme);
        themeReady = true;
        board.drawn = null;
      }
      board.paintStats(status);
      widgets = Array.isArray(body.widgets) ? body.widgets : [];
      board.setWidgets(widgets);
      root.classList.remove("stale");
    } catch (_err) {
      root.classList.add("stale");
    }
    if (PARAMS.has("check") && !checked) {
      checked = true;
      const run = () => {
        board.fit();
        document.documentElement.setAttribute("data-overflow", JSON.stringify(overflowReport(root)));
      };
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => setTimeout(run, 150));
      else setTimeout(run, 150);
    }
  }

  function tick() {
    const parts = board.paintClock();
    if (parts.hour === "04" && parts.minute === "00" && Date.now() - bootedAt > 60000) {
      location.reload();
      return;
    }
    setTimeout(tick, 1000 - (Date.now() % 1000));
  }

  tick();
  refresh().then(() => refreshLive());
  setInterval(refresh, 5000);
  setInterval(refreshLive, 45000);
}

/* ---------- configurator helpers ---------- */

const LIMITS = {
  widgets: 16,
  items: 8,
  item: 80,
  title: 48,
  text: 280,
  markdown: 1200,
  label: 24,
  value: 24,
  hint: 48,
  trend: 24,
  caption: 64,
};

const EDITABLE = {
  clock: ["style", "show_seconds", "show_date", "col_span", "row_span"],
  worldclocks: ["cities", "style", "mark_markets", "col_span", "row_span"],
  stats: ["fields"],
  note: ["title", "text", "col_span", "row_span"],
  markdown: ["title", "text", "col_span", "row_span"],
  list: ["title", "items", "col_span", "row_span"],
  weather: ["latitude", "longitude", "label", "units", "col_span", "row_span"],
  countdown: ["title", "target", "label", "col_span", "row_span"],
  calendar: ["title", "url", "limit", "col_span", "row_span"],
  github: ["title", "repos", "col_span", "row_span"],
  embed: ["title", "url", "refresh_sec", "col_span", "row_span"],
  rss: ["title", "url", "limit", "col_span", "row_span"],
  image: ["title", "src", "fit", "col_span", "row_span"],
  timer: ["title", "minutes", "mode", "col_span", "row_span"],
  status: ["title", "targets", "col_span", "row_span"],
  theme_card: ["image", "caption", "col_span", "row_span"],
};

const SECRET_PATTERNS = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----/, "private key"],
  [/\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_-]{16,}/, "API key"],
  [/\bgh[pousr]_[A-Za-z0-9]{20,}/, "GitHub token"],
  [/\bxox[abprs]-[A-Za-z0-9-]{10,}/, "Slack token"],
  [/\bAKIA[0-9A-Z]{16}\b/, "AWS key"],
  [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}/, "JWT"],
  [/\bBearer\s+[A-Za-z0-9._~+/-]{16,}/i, "bearer token"],
  [/\b(?:password|passwd|pwd|secret|api[ _-]?key|token|otp|passcode)\s*[:=]\s*\S+/i, "credential"],
];
const SOFT_SECRET = /[A-Za-z0-9+_-]{40,}={0,2}/;
const EMAIL_PATTERN = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/;

function oneLine(value) {
  return String(value == null ? "" : value)
    .replace(/[\u0000-\u0008\u000b-\u001f\u007f\t\r\n]+/g, " ")
    .replace(/\u00a0/g, " ")
    .trim();
}

function cut(value, max) {
  if (value.length <= max) return value;
  return value.slice(0, max - 1).trimEnd() + "…";
}

function blankWidget(type) {
  const blanks = {
    clock: { type: "clock", style: "digital", show_seconds: true, show_date: true, col_span: 1, row_span: 1 },
    worldclocks: {
      type: "worldclocks",
      style: "analog",
      mark_markets: true,
      cities: [
        { label: "NYC", zone: "America/New_York" },
        { label: "LON", zone: "Europe/London" },
        { label: "TYO", zone: "Asia/Tokyo" },
      ],
      col_span: 2,
      row_span: 1,
    },
    stats: { type: "stats", fields: STAT_FIELDS.slice() },
    note: { type: "note", title: "Focus", text: "Ship it", col_span: 1, row_span: 1 },
    markdown: { type: "markdown", title: "Today", text: "**Focus**\n\n- Ship it\n- Review notes", col_span: 1, row_span: 1 },
    list: { type: "list", title: "Today", items: ["Ship it", "Review notes", "Stretch"], col_span: 1, row_span: 1 },
    weather: { type: "weather", latitude: 40.71, longitude: -74.01, label: "City", units: "metric", col_span: 1, row_span: 1 },
    countdown: { type: "countdown", title: "Ship it", target: "2027-01-01T00:00:00Z", label: "Launch", col_span: 1, row_span: 1 },
    calendar: { type: "calendar", title: "Calendar", url: "https://example.com/calendar.ics", limit: 5, col_span: 1, row_span: 1 },
    github: { type: "github", title: "Stars", repos: ["example/project"], col_span: 1, row_span: 1 },
    embed: { type: "embed", title: "Embed", url: "https://example.com", refresh_sec: 300, col_span: 2, row_span: 1 },
    rss: { type: "rss", title: "Feed", url: "https://example.com/feed.xml", limit: 6, col_span: 1, row_span: 1 },
    image: { type: "image", title: "Image", src: "/themes/warm-dark/images/default.svg", fit: "cover", col_span: 1, row_span: 1 },
    timer: { type: "timer", title: "Focus", minutes: 25, mode: "pomodoro", col_span: 1, row_span: 1 },
    status: {
      type: "status",
      title: "Status",
      targets: [{ label: "Site", url: "https://example.com" }],
      col_span: 1,
      row_span: 1,
    },
    theme_card: { type: "theme_card", image: "default", caption: "Theme art", col_span: 1, row_span: 1 },
  };
  const meta = TILE_CATALOG.get(type);
  if (meta) return JSON.parse(JSON.stringify({ type, ...meta.example, col_span: meta.col_span || 1, row_span: meta.row_span || 1 }));
  return JSON.parse(JSON.stringify(blanks[type] || { type }));
}

// Called once the catalog loads so the configurator knows each tile's fields.
function registerCatalogEditing() {
  for (const meta of TILE_CATALOG.values()) EDITABLE[meta.id] = Object.keys(meta.fields).concat("col_span", "row_span");
}

function catalogLimit(spec) {
  if (spec.type === "text") return spec.max || 280;
  return spec.max || 80;
}

function sanitize(widget) {
  const w = {
    id: widget.id,
    type: widget.type,
    enabled: widget.enabled !== false,
    col_span: clampSpan(widget.col_span),
    row_span: clampSpan(widget.row_span),
  };
  const warnings = [];
  const errors = [];
  const singleField = (key, max, label, required) => {
    const raw = widget[key];
    if (raw == null || raw === "") {
      if (required) errors.push(`${label} is empty`);
      return;
    }
    let value = oneLine(raw);
    if (value.length > max) {
      warnings.push(`${label} cut to ${max} characters`);
      value = cut(value, max);
    }
    if (value || required) w[key] = value;
    if (!value && required) errors.push(`${label} is empty`);
  };
  const blockField = (key, max, label, required) => {
    let text = String(widget[key] == null ? "" : widget[key])
      .replace(/\r\n?/g, "\n")
      .replace(/[\u0000-\u0008\u000b-\u001f\u007f]+/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
    if (text.length > max) {
      warnings.push(`${label} cut to ${max} characters`);
      text = cut(text, max);
    }
    if (!text && required) errors.push(`${label} is empty`);
    if (text || required) w[key] = text;
  };

  if (widget.type === "list") {
    singleField("title", LIMITS.title, "Title", false);
    let items = (Array.isArray(widget.items) ? widget.items : []).map(oneLine).filter(Boolean);
    if (items.length > LIMITS.items) {
      warnings.push(`${items.length} items, the board takes ${LIMITS.items}. Dropped the last ${items.length - LIMITS.items}.`);
      items = items.slice(0, LIMITS.items);
    }
    let cutCount = 0;
    items = items.map((item) => {
      if (item.length > LIMITS.item) cutCount += 1;
      return cut(item, LIMITS.item);
    });
    if (cutCount) warnings.push(`${cutCount} item${cutCount > 1 ? "s" : ""} cut to ${LIMITS.item} characters`);
    if (!items.length) errors.push("A list needs at least one item");
    w.items = items;
  } else if (widget.type === "note") {
    singleField("title", LIMITS.title, "Title", false);
    blockField("text", LIMITS.text, "Text", true);
  } else if (widget.type === "markdown") {
    singleField("title", LIMITS.title, "Title", false);
    blockField("text", LIMITS.markdown, "Text", true);
  } else if (isCatalogType(widget.type)) {
    const meta = TILE_CATALOG.get(widget.type);
    for (const [key, spec] of Object.entries(meta.fields)) {
      const label = spec.label || key;
      if (spec.type === "line") singleField(key, catalogLimit(spec), label, Boolean(spec.required));
      else if (spec.type === "text") blockField(key, catalogLimit(spec), label, Boolean(spec.required));
      else if (spec.type === "lines") {
        const most = spec.max_items || 8;
        let items = (Array.isArray(widget[key]) ? widget[key] : []).map(oneLine).filter(Boolean);
        if (items.length > most) {
          warnings.push(`${label} has ${items.length} lines, the tile takes ${most}`);
          items = items.slice(0, most);
        }
        items = items.map((item) => cut(item, catalogLimit(spec)));
        if (!items.length && spec.required) errors.push(`${label} is empty`);
        w[key] = items;
      } else if (spec.type === "integer") {
        const n = Number(widget[key]);
        w[key] = Number.isInteger(n) ? Math.max(spec.min, Math.min(spec.max, n)) : spec.default;
      } else if (spec.type === "boolean") {
        w[key] = widget[key] == null ? Boolean(spec.default) : Boolean(widget[key]);
      } else if (spec.type === "choice") {
        w[key] = spec.options.includes(widget[key]) ? widget[key] : spec.default || spec.options[0];
      }
    }
  } else if (widget.type === "stats") {
    const fields = (Array.isArray(widget.fields) ? widget.fields : []).filter((f) => STAT_FIELDS.includes(f));
    w.fields = Array.from(new Set(fields));
    if (!w.fields.length) errors.push("Pick at least one stats field");
  } else if (widget.type === "clock") {
    w.style = widget.style === "analog" ? "analog" : "digital";
    w.show_seconds = widget.show_seconds !== false;
    w.show_date = widget.show_date !== false;
  } else if (widget.type === "worldclocks") {
    w.style = ["analog", "digital", "both"].includes(widget.style) ? widget.style : "analog";
    w.mark_markets = Boolean(widget.mark_markets);
    const cities = Array.isArray(widget.cities) ? widget.cities : [];
    w.cities = cities
      .map((c) => ({ label: oneLine(c.label).slice(0, 24), zone: oneLine(c.zone).slice(0, 64) }))
      .filter((c) => c.label && c.zone)
      .slice(0, 8);
    if (!w.cities.length) errors.push("Add at least one city");
  } else if (widget.type === "weather") {
    singleField("label", LIMITS.title, "Label", false);
    w.units = widget.units === "imperial" ? "imperial" : "metric";
    const lat = Number(widget.latitude);
    const lon = Number(widget.longitude);
    if (!Number.isFinite(lat) || lat < -90 || lat > 90) errors.push("Latitude must be between -90 and 90");
    else w.latitude = Math.round(lat * 10000) / 10000;
    if (!Number.isFinite(lon) || lon < -180 || lon > 180) errors.push("Longitude must be between -180 and 180");
    else w.longitude = Math.round(lon * 10000) / 10000;
  } else if (widget.type === "countdown") {
    singleField("title", LIMITS.title, "Title", false);
    singleField("label", LIMITS.title, "Label", false);
    singleField("target", 40, "Target", true);
  } else if (widget.type === "calendar" || widget.type === "rss") {
    singleField("title", LIMITS.title, "Title", false);
    singleField("url", 500, "URL", true);
    const limit = Number(widget.limit);
    w.limit = Number.isInteger(limit) ? Math.max(1, Math.min(12, limit)) : widget.type === "rss" ? 6 : 5;
  } else if (widget.type === "github") {
    singleField("title", LIMITS.title, "Title", false);
    let repos = Array.isArray(widget.repos) ? widget.repos : String(widget.repos || "").split("\n");
    repos = repos.map(oneLine).filter(Boolean).slice(0, 6);
    if (!repos.length) errors.push("Add at least one owner/name repo");
    w.repos = repos;
  } else if (widget.type === "embed") {
    singleField("title", LIMITS.title, "Title", false);
    singleField("url", 500, "URL", true);
    const refresh = Number(widget.refresh_sec);
    w.refresh_sec = Number.isInteger(refresh) ? Math.max(30, Math.min(86400, refresh)) : 300;
  } else if (widget.type === "image") {
    singleField("title", LIMITS.title, "Title", false);
    singleField("src", 500, "Source", true);
    w.fit = widget.fit === "contain" ? "contain" : "cover";
  } else if (widget.type === "timer") {
    singleField("title", LIMITS.title, "Title", false);
    const minutes = Number(widget.minutes);
    w.minutes = Number.isInteger(minutes) ? Math.max(1, Math.min(180, minutes)) : 25;
    w.mode = widget.mode === "countdown" ? "countdown" : "pomodoro";
  } else if (widget.type === "status") {
    singleField("title", LIMITS.title, "Title", false);
    let targets = Array.isArray(widget.targets) ? widget.targets : [];
    targets = targets
      .map((t) => ({ label: oneLine(t.label).slice(0, 32), url: oneLine(t.url).slice(0, 500) }))
      .filter((t) => t.label && t.url)
      .slice(0, 8);
    if (!targets.length) errors.push("Add at least one status target");
    w.targets = targets;
  } else if (widget.type === "theme_card") {
    singleField("image", 64, "Image", false);
    if (!w.image) w.image = "default";
    singleField("caption", LIMITS.caption, "Caption", false);
  } else {
    errors.push(`Unknown type ${widget.type}`);
  }

  const catalogText = isCatalogType(widget.type)
    ? Object.keys(TILE_CATALOG.get(widget.type).fields).flatMap((key) => (Array.isArray(w[key]) ? w[key] : [w[key]])).filter((v) => typeof v === "string")
    : [];
  const blob = [w.title, w.text, w.label, w.value, w.hint, w.trend, w.caption, w.url, w.src, w.target]
    .concat(catalogText)
    .concat(w.items || [])
    .concat(w.repos || [])
    .concat((w.targets || []).flatMap((t) => [t.label, t.url]))
    .concat((w.cities || []).flatMap((c) => [c.label, c.zone]))
    .filter(Boolean)
    .join("\n");
  for (const [pattern, what] of SECRET_PATTERNS) {
    if (pattern.test(blob)) {
      errors.push(`Looks like a ${what}. Remove it. The board is readable by every device on the tailnet.`);
      break;
    }
  }
  if (!errors.length && SOFT_SECRET.test(blob)) warnings.push("Has a long code-like string. Make sure it is not a token or key.");
  if (EMAIL_PATTERN.test(blob)) warnings.push("Contains an email address. Every device on the tailnet can read it.");
  return { clean: w, warnings, errors };
}

function sameFields(a, b, type) {
  const keys = (EDITABLE[type] || []).concat("enabled");
  const diff = [];
  for (const key of keys) {
    const av = key === "enabled" ? a.enabled !== false : a[key];
    const bv = key === "enabled" ? b.enabled !== false : b[key];
    if (JSON.stringify(av == null ? "" : av) !== JSON.stringify(bv == null ? "" : bv)) diff.push(key);
  }
  return diff;
}

function titleFromName(name) {
  const base = String(name || "Tile").replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : "Tile";
}

function stripMarkdown(line) {
  return line
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(\*|_)(.+?)\1/g, "$2")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/~~(.+?)~~/g, "$1")
    .replace(/<[^>]+>/g, "")
    .trim();
}

function parseText(text, name) {
  const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
  let title = null;
  const rows = [];
  let bullets = 0;
  for (const raw of lines) {
    let line = raw.trim();
    if (!line) {
      rows.push(null);
      continue;
    }
    if (/^(```|---+|\*\*\*+|===+)$/.test(line)) continue;
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (heading) {
      if (!title) {
        title = stripMarkdown(heading[1]);
        continue;
      }
      line = heading[1];
    }
    if (/^([-*+•]|\d+[.)])\s+/.test(line)) bullets += 1;
    line = line.replace(/^([-*+•]|\d+[.)])\s+/, "").replace(/^\[[ xX]\]\s+/, "");
    line = stripMarkdown(line);
    if (line) rows.push(line);
  }
  const nonEmpty = rows.filter(Boolean);
  const finalTitle = title || titleFromName(name);
  const asList = bullets >= 2 || (nonEmpty.length >= 2 && nonEmpty.every((l) => l.length <= LIMITS.item));
  if (asList) {
    return [{ widget: { type: "list", title: finalTitle, items: nonEmpty }, notes: [`From ${name}, one item per line`], alt: "note" }];
  }
  const paragraphs = [];
  let current = [];
  for (const row of rows) {
    if (row == null) {
      if (current.length) paragraphs.push(current.join(" "));
      current = [];
    } else current.push(row);
  }
  if (current.length) paragraphs.push(current.join(" "));
  return [{ widget: { type: "note", title: finalTitle, text: paragraphs.join("\n") }, notes: [`From ${name}, as a note`], alt: "list" }];
}

function parseCsvRows(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  const src = String(text).replace(/^\ufeff/, "");
  const delim =
    (src.split("\n")[0].match(/;/g) || []).length > (src.split("\n")[0].match(/,/g) || []).length
      ? ";"
      : src.split("\n")[0].includes("\t") && !src.split("\n")[0].includes(",")
        ? "\t"
        : ",";
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === delim) {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += ch;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.map((r) => r.map((c) => c.trim())).filter((r) => r.some((c) => c));
}

const NUMERICISH = /^[\s$€£¥+\-~<>]*[\d.,]+\s*[%°A-Za-z/]*\s*$/;

function csvDefaults(rows) {
  const first = rows[0] || [];
  const second = rows[1] || [];
  const headerWords = /^(label|value|hint|name|title|item|items|task|tasks|metric|count|total|event|summary|when|date|note|status)$/i;
  let header =
    rows.length > 1 &&
    (first.some((c) => headerWords.test(c)) || (first.length > 1 && !NUMERICISH.test(first[1] || "") && NUMERICISH.test(second[1] || "")));
  const data = header ? rows.slice(1) : rows;
  const cols = Math.max(...rows.map((r) => r.length));
  const names = header ? first : Array.from({ length: cols }, (_, i) => `Column ${i + 1}`);
  const valueIdx = header ? first.findIndex((c) => /^value$/i.test(c)) : -1;
  const numericShare = data.length ? data.filter((r) => NUMERICISH.test(r[1] || "")).length / data.length : 0;
  let mode = "list";
  if (cols >= 2 && cols <= 3 && data.length <= 10 && (valueIdx >= 0 || numericShare >= 0.6)) mode = "metrics";
  let column = 0;
  if (header) {
    const idx = first.findIndex((c) => /^(title|task|tasks|item|items|name|summary|event)$/i.test(c));
    if (idx >= 0) column = idx;
  }
  return { header, mode, column, names, cols };
}

function csvWidgets(rows, opts, name) {
  const data = opts.header ? rows.slice(1) : rows;
  if (opts.mode === "metrics") {
    return data
      .filter((r) => r[0])
      .map((r) => ({
        widget: { type: "metric", label: r[0], value: r[1] || "", hint: r[2] || "" },
        notes: [`From ${name}, row ${r[0]}`],
      }));
  }
  const title =
    opts.header && opts.names[opts.column] && !/^column \d+$/i.test(opts.names[opts.column])
      ? titleFromName(opts.names[opts.column])
      : titleFromName(name);
  const items = data.map((r) => r[opts.column] || "").filter(Boolean);
  return [{ widget: { type: "list", title, items }, notes: [`From ${name}, column ${opts.names[opts.column] || opts.column + 1}`] }];
}

function specFromObject(obj, name) {
  const notes = [];
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return null;
  let type = obj.type;
  if (!type) {
    if (Array.isArray(obj.items)) type = "list";
    else if (obj.text != null) type = "note";
    else if (obj.label != null && obj.value != null) type = "metric";
  }
  if (!EDITABLE[type] || !knownType(type)) return null;
  const allowed = new Set(["id", "type", "enabled", "col_span", "row_span"].concat(EDITABLE[type]));
  const widget = { type };
  const dropped = [];
  for (const [key, value] of Object.entries(obj)) {
    if (key === "order") continue;
    if (allowed.has(key)) widget[key] = value;
    else dropped.push(key);
  }
  if (Array.isArray(widget.items)) widget.items = widget.items.map((x) => (typeof x === "string" ? x : JSON.stringify(x)));
  if (dropped.length) notes.push(`Ignored fields the board rejects: ${dropped.join(", ")}`);
  notes.push(`From ${name}`);
  return { widget, notes, fromSpec: true };
}

function parseJson(text, name) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (err) {
    throw new Error(`${name} is not valid JSON`);
  }
  if (data && !Array.isArray(data) && Array.isArray(data.widgets)) data = data.widgets;
  if (Array.isArray(data)) {
    if (data.every((x) => typeof x === "string" || typeof x === "number")) {
      return [{ widget: { type: "list", title: titleFromName(name), items: data.map(String) }, notes: [`From ${name}, array of strings`] }];
    }
    const out = data.map((x) => specFromObject(x, name)).filter(Boolean);
    if (!out.length) throw new Error(`${name} has no widgets I can read`);
    return out;
  }
  const spec = specFromObject(data, name);
  if (spec) return [spec];
  if (data && typeof data === "object") {
    const entries = Object.entries(data).filter(([, v]) => v == null || ["string", "number", "boolean"].includes(typeof v));
    if (!entries.length) throw new Error(`${name} has no flat values to show`);
    return entries.map(([k, v]) => ({ widget: { type: "metric", label: k, value: String(v), hint: "" }, notes: [`From ${name}, key ${k}`] }));
  }
  throw new Error(`${name} has nothing I can show`);
}

const WINDOWS_ZONES = {
  "Eastern Standard Time": "America/New_York",
  "Central Standard Time": "America/Chicago",
  "Mountain Standard Time": "America/Denver",
  "Pacific Standard Time": "America/Los_Angeles",
  "GMT Standard Time": "Europe/London",
  "W. Europe Standard Time": "Europe/Berlin",
  "Romance Standard Time": "Europe/Paris",
  "Central European Standard Time": "Europe/Warsaw",
  "India Standard Time": "Asia/Kolkata",
  "AUS Eastern Standard Time": "Australia/Sydney",
  "Tokyo Standard Time": "Asia/Tokyo",
  UTC: "UTC",
};

function validZone(tz) {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return true;
  } catch (_err) {
    return false;
  }
}

function zoneOffsetMs(ms, tz) {
  const p = {};
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  for (const part of fmt.formatToParts(new Date(ms))) p[part.type] = part.value;
  const hour = p.hour === "24" ? 0 : Number(p.hour);
  return Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), hour, Number(p.minute), Number(p.second)) - Math.floor(ms / 1000) * 1000;
}

function wallToUtc(c, tz) {
  const guess = Date.UTC(c.y, c.m - 1, c.d, c.hh, c.mm, c.ss);
  let ms = guess - zoneOffsetMs(guess, tz);
  ms = guess - zoneOffsetMs(ms, tz);
  return ms;
}

function parseIcsDate(value, params, boardTz) {
  const m = String(value).match(/^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(Z)?)?$/);
  if (!m) return null;
  const c = { y: +m[1], m: +m[2], d: +m[3], hh: +(m[4] || 0), mm: +(m[5] || 0), ss: +(m[6] || 0) };
  const allDay = !m[4];
  let tz = boardTz;
  if (m[7]) tz = "UTC";
  else if (params.TZID) {
    const raw = params.TZID.replace(/^"|"$/g, "");
    tz = validZone(raw) ? raw : WINDOWS_ZONES[raw] || boardTz;
  }
  if (allDay) tz = boardTz;
  return { c, tz, allDay, ms: wallToUtc(c, tz) };
}

function addDays(c, n) {
  const t = new Date(Date.UTC(c.y, c.m - 1, c.d + n));
  return { ...c, y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() };
}

function unescapeIcs(value) {
  return String(value)
    .replace(/\\n/gi, " ")
    .replace(/\\([,;\\])/g, "$1")
    .trim();
}

function parseIcs(text, name, boardTz, now = Date.now()) {
  const unfolded = String(text)
    .replace(/\r\n?/g, "\n")
    .replace(/\n[ \t]/g, "");
  const lines = unfolded.split("\n");
  const events = [];
  let calName = "";
  let cur = null;
  for (const line of lines) {
    if (line === "BEGIN:VEVENT") {
      cur = { exdates: [] };
      continue;
    }
    if (line === "END:VEVENT") {
      if (cur) events.push(cur);
      cur = null;
      continue;
    }
    const idx = line.indexOf(":");
    if (idx < 0) continue;
    const left = line.slice(0, idx);
    const value = line.slice(idx + 1);
    const [prop, ...paramList] = left.split(";");
    const params = {};
    for (const p of paramList) {
      const eq = p.indexOf("=");
      if (eq > 0) params[p.slice(0, eq).toUpperCase()] = p.slice(eq + 1);
    }
    const key = prop.toUpperCase();
    if (!cur) {
      if (key === "X-WR-CALNAME") calName = unescapeIcs(value);
      continue;
    }
    if (key === "DTSTART") cur.start = parseIcsDate(value, params, boardTz);
    else if (key === "DTEND") cur.end = parseIcsDate(value, params, boardTz);
    else if (key === "DURATION") cur.duration = value;
    else if (key === "SUMMARY") cur.summary = unescapeIcs(value);
    else if (key === "STATUS") cur.status = value.toUpperCase();
    else if (key === "RRULE") cur.rrule = value;
    else if (key === "RECURRENCE-ID") cur.recurrenceId = value;
    else if (key === "EXDATE")
      for (const v of value.split(",")) {
        const d = parseIcsDate(v, params, boardTz);
        if (d) cur.exdates.push(d.ms);
      }
  }
  const horizon = now + 14 * 86400000;
  const occurrences = [];
  let skippedRules = 0;
  const durationMs = (ev) => {
    if (ev.end) return Math.max(0, ev.end.ms - ev.start.ms);
    const m = String(ev.duration || "").match(/^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/);
    if (m) return ((+m[1] || 0) * 7 * 86400 + (+m[2] || 0) * 86400 + (+m[3] || 0) * 3600 + (+m[4] || 0) * 60 + (+m[5] || 0)) * 1000;
    return ev.start.allDay ? 86400000 : 0;
  };
  for (const ev of events) {
    if (!ev.start || ev.status === "CANCELLED") continue;
    const dur = durationMs(ev);
    const push = (ms) => {
      if (ev.exdates.includes(ms)) return;
      if (ms + Math.max(dur, 1) > now && ms < horizon) occurrences.push({ ms, allDay: ev.start.allDay, summary: ev.summary || "Busy" });
    };
    if (!ev.rrule) {
      push(ev.start.ms);
      continue;
    }
    const rule = {};
    for (const part of ev.rrule.split(";")) {
      const [k, v] = part.split("=");
      rule[k.toUpperCase()] = v;
    }
    const freq = rule.FREQ;
    if (freq !== "DAILY" && freq !== "WEEKLY") {
      skippedRules += 1;
      push(ev.start.ms);
      continue;
    }
    const interval = Math.max(1, +rule.INTERVAL || 1);
    const count = rule.COUNT ? +rule.COUNT : Infinity;
    const until = rule.UNTIL ? (parseIcsDate(rule.UNTIL, {}, "UTC") || {}).ms || Infinity : Infinity;
    const dayCodes = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];
    const startDow = new Date(Date.UTC(ev.start.c.y, ev.start.c.m - 1, ev.start.c.d)).getUTCDay();
    const byDay = freq === "WEEKLY" && rule.BYDAY ? rule.BYDAY.split(",").map((d) => dayCodes.indexOf(d.slice(-2))).filter((d) => d >= 0) : [startDow];
    let n = 0;
    for (let day = 0; day < 3660; day += 1) {
      const c = addDays(ev.start.c, day);
      const dow = (startDow + day) % 7;
      let hit;
      if (freq === "DAILY") hit = day % interval === 0;
      else hit = byDay.includes(dow) && Math.floor((day + ((startDow + 6) % 7)) / 7) % interval === 0;
      if (!hit) continue;
      const ms = wallToUtc(c, ev.start.tz);
      if (ms > until || ms > horizon) break;
      n += 1;
      if (n > count) break;
      push(ms);
    }
  }
  occurrences.sort((a, b) => a.ms - b.ms);
  const today = zonedParts(new Date(now), boardTz);
  const fmtDay = new Intl.DateTimeFormat("en-US", { timeZone: boardTz, weekday: "short" });
  const fmtDate = new Intl.DateTimeFormat("en-US", { timeZone: boardTz, month: "short", day: "numeric" });
  const fmtTime = new Intl.DateTimeFormat("en-GB", { timeZone: boardTz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const seen = new Set();
  const items = [];
  for (const o of occurrences) {
    const d = new Date(o.ms);
    const p = zonedParts(d, boardTz);
    const sameDay = (q) => q.year === p.year && q.month === p.month && q.day === p.day;
    const day = sameDay(today) ? "Today" : o.ms - now < 6 * 86400000 ? fmtDay.format(d) : fmtDate.format(d);
    const line = o.allDay ? `${day}  ${o.summary}` : `${day} ${fmtTime.format(d)}  ${o.summary}`;
    if (seen.has(line)) continue;
    seen.add(line);
    items.push(line);
  }
  const notes = [`From ${name}, ${items.length} upcoming event${items.length === 1 ? "" : "s"} in the next 14 days, event titles only`];
  if (skippedRules) notes.push(`${skippedRules} monthly or yearly repeat rule${skippedRules > 1 ? "s" : ""} not expanded`);
  if (!items.length) items.push("Nothing on the calendar");
  return [{ widget: { type: "list", title: calName ? cut(calName, LIMITS.title) : "Meetings", items }, notes, merge: true }];
}

/* ---------- configurator UI ---------- */

function startConfigurator() {
  document.documentElement.classList.add("cfg");
  document.title = "Deskboard tiles";
  clear(document.body);

  const S = {
    server: [],
    entries: [],
    config: {},
    status: null,
    themes: [],
    key: 0,
    busy: false,
    undo: [],
    previewW: 1920,
    previewH: 1080,
  };

  const wrap = el("div", "cfg-wrap");
  const head = el("div", "cfg-head");
  head.append(el("h1", null, "Deskboard tiles"));
  head.append(
    el("p", "cfg-privacy", "Everything on the board is readable by every device on the tailnet. Plain text only. No secrets, tokens, or private mail."),
  );
  wrap.append(head);

  const cols = el("div", "cfg-cols");
  const left = el("div");
  const right = el("div");
  cols.append(left, right);
  wrap.append(cols);
  document.body.append(wrap);

  const prevSec = el("section", "cfg-section");
  const prevHead = el("div", "cfg-toolbar");
  prevHead.append(el("h2", null, "Preview"));
  const sizeWrap = el("div", "cfg-size");
  const sizeSelect = el("select");
  for (const [label, wh] of [
    ["1920 × 1080", [1920, 1080]],
    ["1280 × 720", [1280, 720]],
    ["2560 × 1440", [2560, 1440]],
    ["1080 × 1920 portrait", [1080, 1920]],
    ["720 × 1280 portrait", [720, 1280]],
  ]) {
    const o = el("option", null, label);
    o.value = wh.join("x");
    sizeSelect.append(o);
  }
  sizeWrap.append(sizeSelect);
  prevHead.append(sizeWrap);
  prevSec.append(prevHead);

  const frame = el("div", "cfg-frame");
  const boardRoot = el("div");
  frame.append(boardRoot);
  prevSec.append(frame);
  const slots = el("div", "cfg-slots");
  prevSec.append(slots);
  const slotNote = el("p", "cfg-slot-note", "");
  prevSec.append(slotNote);

  const actions = el("div", "cfg-actions");
  const applyBtn = el("button", "cfg-btn primary", "Apply to board");
  const undoBtn = el("button", "cfg-btn", "Undo");
  const discardBtn = el("button", "cfg-btn", "Discard changes");
  const reloadBtn = el("button", "cfg-btn", "Reload from board");
  const exportBtn = el("button", "cfg-btn", "Export JSON");
  const importBtn = el("button", "cfg-btn", "Import JSON");
  const reloadTilesBtn = el("button", "cfg-btn", "Reload tiles");
  reloadTilesBtn.title = "Rescan tiles/ on the server and pick up new or changed tiles";
  const importInput = el("input");
  importInput.type = "file";
  importInput.accept = ".json,application/json";
  importInput.style.display = "none";
  actions.append(applyBtn, undoBtn, discardBtn, reloadBtn, exportBtn, importBtn, reloadTilesBtn, importInput);
  prevSec.append(actions);
  const log = el("pre", "cfg-log", "Loading the board…");
  prevSec.append(log);
  left.append(prevSec);

  const themeSec = el("section", "cfg-section");
  themeSec.append(el("h2", null, "Theme"));
  const themeGrid = el("div", "cfg-themes");
  themeSec.append(themeGrid);
  left.append(themeSec);

  const board = new Board(boardRoot, { preview: true });

  function applyPreviewSize() {
    const [w, h] = sizeSelect.value.split("x").map(Number);
    S.previewW = w;
    S.previewH = h;
    frame.classList.toggle("portrait", h > w);
    board.setScale(w, h);
    const s = frame.clientWidth / w;
    boardRoot.style.width = `${w}px`;
    boardRoot.style.height = `${h}px`;
    boardRoot.style.transform = `scale(${s})`;
    boardRoot.style.transformOrigin = "top left";
    frame.style.height = `${h * s}px`;
    board.fit();
  }
  sizeSelect.addEventListener("change", () => {
    applyPreviewSize();
    renderPreview();
  });
  if (window.ResizeObserver) new ResizeObserver(applyPreviewSize).observe(frame);
  window.addEventListener("resize", applyPreviewSize);
  setInterval(() => board.paintClock(), 1000);

  const dropSec = el("section", "cfg-section");
  dropSec.append(el("h2", null, "Add from files"));
  const drop = el("div", "cfg-drop");
  const dropText = el("div", null, "Drop .txt .md .csv .json .ics files here");
  dropText.append(
    el(
      "small",
      null,
      "Text and Markdown become a list or a note. CSV becomes a list or metric tiles. JSON can be strings, key and value pairs, widget specs, or a full layout. ICS becomes upcoming events.",
    ),
  );
  const pickBtn = el("button", "cfg-btn", "Choose files");
  pickBtn.style.marginTop = "10px";
  dropText.append(el("br"), pickBtn);
  drop.append(dropText);
  const fileInput = el("input");
  fileInput.type = "file";
  fileInput.multiple = true;
  fileInput.accept = ".txt,.md,.markdown,.csv,.tsv,.json,.ics,text/plain,text/csv,application/json,text/calendar,image/*";
  fileInput.style.display = "none";
  dropSec.append(drop, fileInput);
  const paste = el("div", "cfg-paste");
  const pasteArea = el("textarea");
  pasteArea.placeholder = "Or paste text, one item per line";
  const pasteRow = el("div", "cfg-row");
  const pasteBtn = el("button", "cfg-btn", "Add pasted text");
  pasteRow.append(pasteBtn);
  paste.append(pasteArea, pasteRow);
  dropSec.append(paste);
  right.append(dropSec);

  const gallerySec = el("section", "cfg-section");
  gallerySec.append(el("h2", null, "Widget gallery"));
  const gallery = el("div", "cfg-gallery");
  function renderGallery() {
    clear(gallery);
    const list = ALL_TYPES.filter(knownType).concat([...TILE_CATALOG.keys()].filter((t) => !ALL_TYPES.includes(t)));
    for (const type of list) {
      const meta = TILE_CATALOG.get(type);
      const b = el("button", null, meta && !ALL_TYPES.includes(type) ? meta.name : type.replace(/_/g, " "));
      if (meta) b.title = meta.description;
      b.addEventListener("click", () => addBlank(type));
      gallery.append(b);
    }
  }
  renderGallery();
  gallerySec.append(gallery);
  right.append(gallerySec);

  const cardSec = el("section", "cfg-section");
  cardSec.append(el("h2", null, "Tiles, drag to reorder"));
  const cards = el("div", "cfg-cards");
  cardSec.append(cards);
  right.append(cardSec);

  function say(text) {
    log.textContent = text;
  }

  function live() {
    return S.entries.filter((e) => !e.deleted);
  }

  function maxSlots() {
    return Number(S.config.max_widgets) || LIMITS.widgets;
  }

  function pushUndo() {
    S.undo.push(JSON.stringify(S.entries.map((e) => ({ key: e.key, origId: e.origId, w: e.w, deleted: e.deleted, notes: e.notes, open: e.open }))));
    if (S.undo.length > 40) S.undo.shift();
  }

  function undo() {
    if (!S.undo.length) {
      say("Nothing to undo.");
      return;
    }
    const snap = JSON.parse(S.undo.pop());
    S.entries = snap.map((e) => ({ ...e, group: null, _sig: null, _res: null }));
    renderCards();
    say("Undid the last local edit.");
  }

  function computed(entry) {
    if (!entry._sig || entry._sig !== JSON.stringify(entry.w)) {
      entry._sig = JSON.stringify(entry.w);
      entry._res = sanitize(entry.w);
    }
    return entry._res;
  }

  function serverById(id) {
    return S.server.find((w) => w.id === id);
  }

  function changedKeys(entry) {
    if (!entry.origId) return [];
    const srv = serverById(entry.origId);
    if (!srv) return [];
    return sameFields(computed(entry).clean, srv, srv.type);
  }

  function orderedLive() {
    const l = live();
    const head = l.filter((e) => e.w.type === "clock" || e.w.type === "stats");
    const rest = l.filter((e) => e.w.type !== "clock" && e.w.type !== "stats");
    return head.concat(rest);
  }

  function problems() {
    const list = [];
    const l = live();
    const limit = maxSlots();
    if (l.length > limit) list.push(`${l.length} tiles, the board holds ${limit}. Delete ${l.length - limit}.`);
    for (const t of SINGLETONS) if (l.filter((e) => e.w.type === t).length > 1) list.push(`Only one ${t} is allowed`);
    for (const e of l) for (const err of computed(e).errors) list.push(`${labelOf(e)}: ${err}`);
    return list;
  }

  // The field a card title comes from: title, label, or name. Without one the
  // card shows the tile's name.
  function catalogTitleKey(type) {
    const fields = TILE_CATALOG.get(type).fields;
    for (const key of ["title", "label", "name"]) if (fields[key] && fields[key].type === "line") return key;
    return null;
  }

  function labelOf(entry) {
    const w = entry.w;
    if (w.type === "clock") return "Clock";
    if (w.type === "stats") return "Stats";
    if (w.type === "worldclocks") return "World clocks";
    if (w.type === "theme_card") return oneLine(w.caption) || "Theme card";
    if (isCatalogType(w.type)) {
      const key = catalogTitleKey(w.type);
      return (key && oneLine(w[key])) || TILE_CATALOG.get(w.type).name;
    }
    return oneLine(w.title) || oneLine(w.label) || w.type;
  }

  function summaryOf(entry) {
    const w = computed(entry).clean;
    if (w.type === "clock") return `${w.style || "digital"} clock`;
    if (w.type === "stats") return `Footer: ${(w.fields || []).map((f) => STAT_LABELS[f]).join(", ") || "no fields"}`;
    if (w.type === "worldclocks") return (w.cities || []).map((c) => c.label).join(" · ");
    if (w.type === "list") return `${(w.items || []).length} item${(w.items || []).length === 1 ? "" : "s"}`;
    if (w.type === "note" || w.type === "markdown") return w.text;
    if (isCatalogType(w.type)) {
      const titleKey = catalogTitleKey(w.type);
      return Object.entries(TILE_CATALOG.get(w.type).fields)
        .filter(([key, spec]) => key !== titleKey && (spec.type === "line" || spec.type === "text" || spec.type === "lines"))
        .map(([key]) => (Array.isArray(w[key]) ? w[key].join(", ") : oneLine(w[key])))
        .filter(Boolean)
        .join(" ");
    }
    if (w.type === "weather") return `${w.label || "Weather"} ${w.latitude}, ${w.longitude}`;
    if (w.type === "countdown") return `${w.target || ""}`;
    if (w.type === "github") return (w.repos || []).join(", ");
    if (w.type === "embed" || w.type === "rss" || w.type === "calendar") return w.url || "";
    if (w.type === "image") return w.src || "";
    if (w.type === "timer") return `${w.minutes || 25} min ${w.mode || ""}`;
    if (w.type === "status") return `${(w.targets || []).length} target${(w.targets || []).length === 1 ? "" : "s"}`;
    if (w.type === "theme_card") return w.caption || w.image || "";
    return w.type;
  }

  function renderThemes() {
    clear(themeGrid);
    const current = S.config.theme || "warm-dark";
    for (const theme of S.themes) {
      const btn = el("button", `cfg-theme${theme.id === current ? " on" : ""}`);
      btn.append(el("strong", null, theme.name || theme.label || theme.id));
      btn.append(el("span", null, theme.description || theme.id));
      btn.addEventListener("click", async () => {
        try {
          await api("PATCH", "/api/config", { theme: theme.id });
          S.config.theme = theme.id;
          await board.applyTheme(theme.id);
          board.drawn = null;
          renderThemes();
          renderPreview();
          say(`Theme set to ${theme.name || theme.id}.`);
        } catch (err) {
          say(String(err.message || err));
        }
      });
      themeGrid.append(btn);
    }
  }

  function renderPreview() {
    const limit = maxSlots();
    const ordered = orderedLive().slice(0, limit);
    const widgets = ordered.map((e, i) => ({ ...computed(e).clean, order: i * 10 }));
    board.drawn = null;
    board.setWidgets(widgets);
    const l = live();
    clear(slots);
    for (let i = 0; i < limit; i += 1) {
      const s = el("span");
      const e = orderedLive()[i];
      if (e) s.className = e.origId ? "used" : "new";
      slots.append(s);
    }
    if (l.length > limit) for (const s of slots.children) s.className = "over";
    const pending = pendingSummary();
    slotNote.textContent = `${Math.min(l.length, 99)} of ${limit} slots used. ${pending || "No unsaved changes."}`;
    const probs = problems();
    applyBtn.disabled = S.busy || Boolean(probs.length) || !pending;
    if (probs.length && !S.busy) say(`Fix before applying:\n${probs.map((p) => "  " + p).join("\n")}`);
    applyPreviewSize();
  }

  function pendingSummary() {
    const adds = live().filter((e) => !e.origId).length;
    const dels = S.entries.filter((e) => e.deleted && e.origId).length;
    const edits = live().filter((e) => changedKeys(e).length).length;
    const ids = orderedLive()
      .filter((e) => e.origId)
      .map((e) => e.origId);
    const srvIds = sortWidgets(S.server)
      .map((w) => w.id)
      .filter((id) => ids.includes(id));
    const moved = JSON.stringify(ids) !== JSON.stringify(srvIds);
    const parts = [];
    if (adds) parts.push(`${adds} new`);
    if (edits) parts.push(`${edits} edited`);
    if (dels) parts.push(`${dels} deleted`);
    if (moved) parts.push("new order");
    return parts.length ? `Pending: ${parts.join(", ")}.` : "";
  }

  let dragKey = null;

  function renderCards() {
    clear(cards);
    const ordered = S.entries.slice().sort((a, b) => {
      const rank = (e) => (e.w.type === "clock" ? 0 : e.w.type === "stats" ? 1 : 2);
      return rank(a) - rank(b) || S.entries.indexOf(a) - S.entries.indexOf(b);
    });
    let liveIndex = 0;
    const seenGroups = new Set();
    for (const entry of ordered) {
      if (!entry.deleted) liveIndex += 1;
      const firstOfGroup = Boolean(entry.group) && !seenGroups.has(entry.group);
      if (entry.group) seenGroups.add(entry.group);
      cards.append(renderCard(entry, !entry.deleted && liveIndex > maxSlots(), firstOfGroup));
    }
    renderPreview();
  }

  function renderCard(entry, over, showPicker) {
    const card = el("div", "cfg-card");
    const fixed = entry.w.type === "clock" || entry.w.type === "stats";
    if (!entry.origId) card.classList.add("is-new");
    else if (changedKeys(entry).length) card.classList.add("is-changed");
    if (entry.deleted) card.classList.add("is-deleted");
    if (over) card.classList.add("is-over");
    card.dataset.key = entry.key;
    const top = el("div", "cfg-card-top");
    top.append(el("span", "cfg-grip", fixed ? "·" : "⠿"));
    top.append(el("span", "cfg-badge", entry.w.type));
    top.append(el("span", "cfg-card-title", labelOf(entry) + (entry.w.enabled === false ? " (hidden)" : "")));
    if (!entry.deleted) {
      const edit = el("button", "cfg-btn", entry.open ? "Done" : "Edit");
      edit.addEventListener("click", () => {
        entry.open = !entry.open;
        renderCards();
      });
      top.append(edit);
      if (entry.origId && changedKeys(entry).length) {
        const revert = el("button", "cfg-btn", "Revert");
        revert.addEventListener("click", () => {
          pushUndo();
          entry.w = JSON.parse(JSON.stringify(serverById(entry.origId)));
          renderCards();
        });
        top.append(revert);
      }
      const del = el("button", "cfg-btn danger", "Delete");
      del.addEventListener("click", () => {
        pushUndo();
        if (entry.origId) entry.deleted = true;
        else S.entries.splice(S.entries.indexOf(entry), 1);
        renderCards();
      });
      top.append(del);
    } else {
      const undoKeep = el("button", "cfg-btn", "Keep");
      undoKeep.addEventListener("click", () => {
        pushUndo();
        entry.deleted = false;
        renderCards();
      });
      top.append(undoKeep);
    }
    card.append(top);
    const sum = el("p", "cfg-card-sum", summaryOf(entry));
    card.append(sum);
    const warnBox = el("div");
    const paintWarn = () => {
      clear(warnBox);
      const r = computed(entry);
      for (const n of entry.notes || []) {
        const note = el("p", "cfg-warn", n);
        note.style.color = "var(--faint)";
        warnBox.append(note);
      }
      for (const w of r.warnings) warnBox.append(el("p", "cfg-warn", w));
      for (const e of r.errors) warnBox.append(el("p", "cfg-warn bad", e));
      if (over) warnBox.append(el("p", "cfg-warn bad", `Past the ${maxSlots()} tile limit, will not fit`));
      sum.textContent = summaryOf(entry);
    };
    paintWarn();
    card.append(warnBox);
    if (showPicker && !entry.deleted) card.append(renderCsvPicker(entry));
    if (entry.open && !entry.deleted) card.append(renderDrawer(entry, paintWarn));

    if (!fixed && !entry.deleted) {
      card.draggable = true;
      card.addEventListener("dragstart", (ev) => {
        dragKey = entry.key;
        card.classList.add("dragging");
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/x-deskboard-tile", String(entry.key));
      });
      card.addEventListener("dragend", () => {
        dragKey = null;
        card.classList.remove("dragging");
      });
      card.addEventListener("dragover", (ev) => {
        if (dragKey == null || dragKey === entry.key) return;
        ev.preventDefault();
        const r = card.getBoundingClientRect();
        const after = ev.clientY > r.top + r.height / 2;
        card.classList.toggle("drop-after", after);
        card.classList.toggle("drop-before", !after);
      });
      card.addEventListener("dragleave", () => card.classList.remove("drop-after", "drop-before"));
      card.addEventListener("drop", (ev) => {
        if (dragKey == null) return;
        ev.preventDefault();
        ev.stopPropagation();
        const r = card.getBoundingClientRect();
        const after = ev.clientY > r.top + r.height / 2;
        const moving = S.entries.find((e) => e.key === dragKey);
        if (!moving || moving === entry) return;
        pushUndo();
        S.entries.splice(S.entries.indexOf(moving), 1);
        const at = S.entries.indexOf(entry) + (after ? 1 : 0);
        S.entries.splice(at, 0, moving);
        dragKey = null;
        renderCards();
      });
    }
    return card;
  }

  function field(labelText, node) {
    const label = el("label", null, labelText);
    label.append(node);
    return label;
  }

  function spanButtons(entry, onChange) {
    const wrap = el("div", "cfg-span");
    for (const [label, cs, rs] of [
      ["1×1", 1, 1],
      ["2×1", 2, 1],
      ["1×2", 1, 2],
      ["2×2", 2, 2],
    ]) {
      const b = el("button", null, label);
      if (clampSpan(entry.w.col_span) === cs && clampSpan(entry.w.row_span) === rs) b.classList.add("on");
      b.addEventListener("click", () => {
        pushUndo();
        entry.w.col_span = cs;
        entry.w.row_span = rs;
        onChange();
        renderCards();
      });
      wrap.append(b);
    }
    return wrap;
  }

  function renderDrawer(entry, paintWarn) {
    const box = el("div", "cfg-drawer cfg-edit");
    const w = entry.w;
    const onChange = () => {
      paintWarn();
      renderPreview();
    };
    let snapped = false;
    const snapOnce = () => {
      if (!snapped) {
        pushUndo();
        snapped = true;
      }
    };
    const input = (key, max, multiline, kind) => {
      const node = el(multiline ? "textarea" : "input");
      if (kind === "lines") node.value = (w[key] || []).join("\n");
      else if (key === "items") node.value = (w.items || []).join("\n");
      else if (key === "repos") node.value = (w.repos || []).join("\n");
      else if (key === "cities") node.value = (w.cities || []).map((c) => `${c.label}|${c.zone}`).join("\n");
      else if (key === "targets") node.value = (w.targets || []).map((t) => `${t.label}|${t.url}`).join("\n");
      else node.value = w[key] == null ? "" : w[key];
      node.addEventListener("input", () => {
        snapOnce();
        if (kind === "lines") w[key] = node.value.split("\n");
        else if (kind === "number") w[key] = Number(node.value);
        else if (key === "items") w.items = node.value.split("\n");
        else if (key === "repos") w.repos = node.value.split("\n");
        else if (key === "cities")
          w.cities = node.value
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean)
            .map((line) => {
              const [label, zone] = line.split("|");
              return { label: oneLine(label), zone: oneLine(zone || label) };
            });
        else if (key === "targets")
          w.targets = node.value
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean)
            .map((line) => {
              const idx = line.indexOf("|");
              if (idx < 0) return { label: oneLine(line), url: oneLine(line) };
              return { label: oneLine(line.slice(0, idx)), url: oneLine(line.slice(idx + 1)) };
            });
        else if (key === "latitude" || key === "longitude" || key === "minutes" || key === "limit" || key === "refresh_sec")
          w[key] = Number(node.value);
        else w[key] = node.value;
        onChange();
      });
      if (max && !multiline) node.maxLength = max * 2;
      return node;
    };
    const select = (key, options) => {
      const node = el("select");
      for (const [value, label] of options) {
        const o = el("option", null, label);
        o.value = value;
        node.append(o);
      }
      node.value = w[key] == null ? options[0][0] : String(w[key]);
      node.addEventListener("change", () => {
        snapOnce();
        w[key] = node.value === "true" ? true : node.value === "false" ? false : node.value;
        onChange();
        renderCards();
      });
      return node;
    };
    const boolRow = (key, labelText) => {
      const cb = el("input");
      cb.type = "checkbox";
      if (key === "mark_markets") cb.checked = Boolean(w.mark_markets);
      else if (key === "show_seconds") cb.checked = w.show_seconds !== false;
      else if (key === "show_date") cb.checked = w.show_date !== false;
      else cb.checked = Boolean(w[key]);
      cb.addEventListener("change", () => {
        snapOnce();
        w[key] = cb.checked;
        onChange();
      });
      const label = el("label", null, labelText);
      label.style.display = "flex";
      label.style.gap = "6px";
      label.prepend(cb);
      return label;
    };

    if (w.type === "list") {
      box.append(field(`Title (up to ${LIMITS.title})`, input("title", LIMITS.title)));
      box.append(field(`Items, one per line (up to ${LIMITS.items})`, input("items", 0, true)));
    } else if (w.type === "note" || w.type === "markdown") {
      box.append(field(`Title (up to ${LIMITS.title})`, input("title", LIMITS.title)));
      box.append(field(`Text (up to ${w.type === "markdown" ? LIMITS.markdown : LIMITS.text})`, input("text", 0, true)));
    } else if (isCatalogType(w.type)) {
      for (const [key, spec] of Object.entries(TILE_CATALOG.get(w.type).fields)) {
        const label = spec.label || key;
        if (spec.type === "line") box.append(field(label, input(key, catalogLimit(spec))));
        else if (spec.type === "text") box.append(field(`${label} (up to ${catalogLimit(spec)})`, input(key, 0, true)));
        else if (spec.type === "lines") box.append(field(`${label}, one per line`, input(key, 0, true, "lines")));
        else if (spec.type === "integer") box.append(field(`${label} (${spec.min} to ${spec.max})`, input(key, 0, false, "number")));
        else if (spec.type === "boolean") box.append(boolRow(key, label));
        else if (spec.type === "choice") box.append(field(label, select(key, spec.options.map((o) => [o, o]))));
      }
    } else if (w.type === "stats") {
      const row = el("div", "cfg-row");
      for (const f of STAT_FIELDS) {
        const cb = el("input");
        cb.type = "checkbox";
        cb.checked = (w.fields || []).includes(f);
        cb.addEventListener("change", () => {
          snapOnce();
          const set = new Set(w.fields || []);
          if (cb.checked) set.add(f);
          else set.delete(f);
          w.fields = STAT_FIELDS.filter((x) => set.has(x));
          onChange();
        });
        const label = el("label", null, STAT_LABELS[f]);
        label.style.display = "flex";
        label.style.gap = "6px";
        label.prepend(cb);
        row.append(label);
      }
      box.append(row);
    } else if (w.type === "clock") {
      box.append(field("Style", select("style", [["digital", "Digital"], ["analog", "Analog"]])));
      box.append(boolRow("show_seconds", "Show seconds"));
      box.append(boolRow("show_date", "Show date"));
    } else if (w.type === "worldclocks") {
      box.append(field("Style", select("style", [["analog", "Analog"], ["digital", "Digital"], ["both", "Both"]])));
      box.append(boolRow("mark_markets", "Mark market hours"));
      box.append(field("Cities, one per line as Label|Timezone", input("cities", 0, true)));
    } else if (w.type === "weather") {
      box.append(field("Label", input("label", LIMITS.title)));
      box.append(field("Latitude", input("latitude")));
      box.append(field("Longitude", input("longitude")));
      box.append(field("Units", select("units", [["metric", "Metric"], ["imperial", "Imperial"]])));
    } else if (w.type === "countdown") {
      box.append(field("Title", input("title", LIMITS.title)));
      box.append(field("Label", input("label", LIMITS.title)));
      box.append(field("Target ISO date", input("target", 40)));
    } else if (w.type === "calendar" || w.type === "rss") {
      box.append(field("Title", input("title", LIMITS.title)));
      box.append(field("URL", input("url", 500)));
      box.append(field("Limit", input("limit")));
    } else if (w.type === "github") {
      box.append(field("Title", input("title", LIMITS.title)));
      box.append(field("Repos, one owner/name per line", input("repos", 0, true)));
    } else if (w.type === "embed") {
      box.append(field("Title", input("title", LIMITS.title)));
      box.append(field("URL", input("url", 500)));
      box.append(field("Refresh seconds", input("refresh_sec")));
    } else if (w.type === "image") {
      box.append(field("Title", input("title", LIMITS.title)));
      box.append(field("Source (/themes, /media, or https)", input("src", 500)));
      box.append(field("Fit", select("fit", [["cover", "Cover"], ["contain", "Contain"]])));
    } else if (w.type === "timer") {
      box.append(field("Title", input("title", LIMITS.title)));
      box.append(field("Minutes", input("minutes")));
      box.append(field("Mode", select("mode", [["pomodoro", "Pomodoro"], ["countdown", "Countdown"]])));
    } else if (w.type === "status") {
      box.append(field("Title", input("title", LIMITS.title)));
      box.append(field("Targets, one per line as Label|URL", input("targets", 0, true)));
    } else if (w.type === "theme_card") {
      box.append(field("Image id", input("image", 64)));
      box.append(field("Caption", input("caption", LIMITS.caption)));
    }

    if (w.type !== "stats") box.append(spanButtons(entry, onChange));

    const row = el("div", "cfg-row");
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = w.enabled !== false;
    cb.addEventListener("change", () => {
      snapOnce();
      w.enabled = cb.checked;
      onChange();
    });
    const show = el("label", null, "Show on board");
    show.style.display = "flex";
    show.style.gap = "6px";
    show.prepend(cb);
    row.append(show);
    if (!entry.origId && (w.type === "list" || w.type === "note")) {
      const sw = el("button", "cfg-btn", w.type === "list" ? "Make it a note" : "Make it a list");
      sw.addEventListener("click", () => {
        pushUndo();
        if (w.type === "list") {
          w.type = "note";
          w.text = (w.items || []).join("\n");
          delete w.items;
        } else {
          w.type = "list";
          w.items = String(w.text || "")
            .split(/\n+/)
            .filter(Boolean);
          delete w.text;
        }
        renderCards();
      });
      row.append(sw);
    }
    box.append(row);
    return box;
  }

  function renderCsvPicker(entry) {
    const g = entry.group;
    const box = el("div", "cfg-pick");
    const mode = el("select");
    for (const [v, t] of [
      ["list", "List from one column"],
      ["metrics", "Metric tiles (label, value, hint)"],
    ]) {
      const o = el("option", null, t);
      o.value = v;
      mode.append(o);
    }
    mode.value = g.opts.mode;
    box.append(mode);
    const col = el("select");
    g.opts.names.forEach((n, i) => {
      const o = el("option", null, n || `Column ${i + 1}`);
      o.value = String(i);
      col.append(o);
    });
    col.value = String(g.opts.column);
    col.style.display = g.opts.mode === "list" ? "" : "none";
    box.append(col);
    const hdr = el("label", null, "First row is a header");
    const hcb = el("input");
    hcb.type = "checkbox";
    hcb.checked = g.opts.header;
    hdr.prepend(hcb);
    box.append(hdr);
    const regen = () => {
      pushUndo();
      g.opts.mode = mode.value;
      g.opts.column = Number(col.value);
      g.opts.header = hcb.checked;
      if (!g.opts.header) g.opts.names = Array.from({ length: g.opts.cols }, (_, i) => `Column ${i + 1}`);
      else g.opts.names = g.rows[0].slice();
      const at = S.entries.findIndex((e) => e.group === g);
      S.entries = S.entries.filter((e) => e.group !== g);
      const made = csvWidgets(g.rows, g.opts, g.name).map((p) => newEntry(p, g));
      S.entries.splice(at < 0 ? S.entries.length : at, 0, ...made);
      renderCards();
    };
    mode.addEventListener("change", regen);
    col.addEventListener("change", regen);
    hcb.addEventListener("change", regen);
    return box;
  }

  function slugId(base) {
    const taken = new Set(S.server.map((w) => w.id).concat(S.entries.map((e) => e.w.id)).filter(Boolean));
    let slug = oneLine(base)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "")
      .slice(0, 14);
    if (!/^[a-z]/.test(slug)) slug = "tile" + slug;
    slug = slug.slice(0, 14) || "tile";
    let id = slug;
    for (let n = 2; taken.has(id); n += 1) id = `${slug.slice(0, 12)}${n}`;
    return id;
  }

  function newEntry(parsed, group) {
    const w = { enabled: true, col_span: 1, row_span: 1, ...parsed.widget };
    const validId = typeof w.id === "string" && /^[a-z][a-z0-9_-]{0,31}$/.test(w.id);
    const taken = S.server.some((x) => x.id === w.id) || S.entries.some((e) => e.w.id === w.id);
    if (!validId || taken) w.id = slugId(w.type === "metric" ? w.label || "metric" : w.title || w.type);
    S.key += 1;
    return { key: S.key, origId: null, w, deleted: false, notes: parsed.notes || [], group: group || null, open: false };
  }

  function addParsed(list) {
    let added = 0;
    for (const parsed of list) {
      const type = parsed.widget.type;
      if (SINGLETONS.has(type) && live().some((e) => e.w.type === type)) {
        say(`Skipped a ${type} from the file, the board already has one`);
        continue;
      }
      if (Array.isArray(list) && parsed.fromSpec && parsed.widget && knownType(type) && parsed.widget.id) {
        /* layout import handled elsewhere */
      }
      const match = live().find(
        (e) =>
          e.w.type === type &&
          ((parsed.widget.id && e.w.id === parsed.widget.id) ||
            ((parsed.merge || type === "list" || type === "note") &&
              oneLine(e.w.title).toLowerCase() === oneLine(parsed.widget.title).toLowerCase() &&
              oneLine(e.w.title)) ||
            (type === "metric" && oneLine(e.w.label).toLowerCase() === oneLine(parsed.widget.label).toLowerCase())),
      );
      if (match && !parsed.group) {
        pushUndo();
        for (const key of EDITABLE[type] || []) if (key in parsed.widget) match.w[key] = parsed.widget[key];
        if ("enabled" in parsed.widget) match.w.enabled = parsed.widget.enabled;
        match.notes = (parsed.notes || []).concat("Updates the existing tile with the same name");
        added += 1;
        continue;
      }
      pushUndo();
      S.entries.push(newEntry(parsed));
      added += 1;
    }
    renderCards();
    return added;
  }

  function addBlank(type) {
    if (SINGLETONS.has(type) && live().some((e) => e.w.type === type)) {
      say(`Only one ${type} is allowed.`);
      return;
    }
    pushUndo();
    const e = newEntry({ widget: blankWidget(type), notes: [] });
    if (SINGLETONS.has(type)) e.w.id = slugId(type);
    e.open = true;
    S.entries.push(e);
    renderCards();
  }

  async function readFile(file) {
    const name = file.name || "file";
    const ext = (name.match(/\.([^.]+)$/) || [, ""])[1].toLowerCase();
    if (file.size > 2 * 1024 * 1024) throw new Error(`${name} is over 2 MB`);
    if (/^image\//.test(file.type) || ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) {
      return [
        {
          widget: {
            type: "image",
            title: titleFromName(name),
            src: "/media/" + name.replace(/[^A-Za-z0-9._-]+/g, "-"),
            fit: "cover",
          },
          notes: [`From ${name}. Set src to a file under /media or /themes after you place it on the host.`],
        },
      ];
    }
    const text = await file.text();
    const tz = S.config.timezone || "UTC";
    if (ext === "ics" || /^BEGIN:VCALENDAR/m.test(text.slice(0, 200))) return parseIcs(text, name, tz);
    if (ext === "json") {
      let data;
      try {
        data = JSON.parse(text);
      } catch (_err) {
        throw new Error(`${name} is not valid JSON`);
      }
      if (data && Array.isArray(data.widgets)) {
        return data.widgets.map((w) => ({ widget: w, notes: [`From layout ${name}`], fromSpec: true }));
      }
      return parseJson(text, name);
    }
    if (ext === "csv" || ext === "tsv") {
      const rows = parseCsvRows(text);
      if (!rows.length) throw new Error(`${name} is empty`);
      const opts = csvDefaults(rows);
      const group = { rows, opts, name };
      return csvWidgets(rows, opts, name).map((p) => ({ ...p, group }));
    }
    if (ext === "txt" || ext === "md" || ext === "markdown" || ext === "" || file.type.startsWith("text/")) return parseText(text, name);
    throw new Error(`${name}: use .txt .md .csv .json or .ics`);
  }

  async function takeFiles(files) {
    const msgs = [];
    for (const file of files) {
      try {
        const parsed = await readFile(file);
        const grouped = parsed.filter((p) => p.group);
        if (grouped.length) {
          pushUndo();
          const g = grouped[0].group;
          for (const p of grouped) S.entries.push(newEntry(p, g));
          msgs.push(`${file.name}: ${grouped.length} tile${grouped.length > 1 ? "s" : ""} staged`);
        }
        const plain = parsed.filter((p) => !p.group);
        if (plain.length) msgs.push(`${file.name}: ${addParsed(plain)} tile${plain.length > 1 ? "s" : ""} staged`);
      } catch (err) {
        msgs.push(String(err.message || err));
      }
    }
    renderCards();
    say(`${msgs.join("\n")}\nNothing is on the board until you press Apply.`);
  }

  ["dragenter", "dragover"].forEach((t) =>
    drop.addEventListener(t, (ev) => {
      if (dragKey != null) return;
      ev.preventDefault();
      drop.classList.add("hot");
    }),
  );
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("hot")));
  drop.addEventListener("drop", (ev) => {
    if (dragKey != null) return;
    ev.preventDefault();
    ev.stopPropagation();
    takeFiles(Array.from(ev.dataTransfer.files || []));
  });
  window.addEventListener("dragover", (ev) => ev.preventDefault());
  window.addEventListener("drop", (ev) => {
    ev.preventDefault();
    if (dragKey == null && ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files.length) takeFiles(Array.from(ev.dataTransfer.files));
  });
  pickBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    takeFiles(Array.from(fileInput.files || []));
    fileInput.value = "";
  });
  pasteBtn.addEventListener("click", () => {
    if (!pasteArea.value.trim()) return;
    addParsed(parseText(pasteArea.value, "Pasted"));
    pasteArea.value = "";
  });

  async function api(method, path, body) {
    const res = await fetch(path, {
      method,
      cache: "no-store",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try {
      data = await res.json();
    } catch (_err) {
      data = null;
    }
    if (!res.ok) throw new Error(`${method} ${path}: ${(data && data.error) || res.status}`);
    return data;
  }

  async function load() {
    try {
      await loadTileCatalog();
      registerCatalogEditing();
      renderGallery();
    } catch (err) {
      say(`Could not load the tile catalog: ${err.message || err}`);
    }
    const [w, c, s, t] = await Promise.all([
      api("GET", "/api/widgets"),
      api("GET", "/api/config"),
      api("GET", "/api/status"),
      api("GET", "/api/themes"),
    ]);
    S.server = Array.isArray(w.widgets) ? w.widgets : [];
    S.config = c || {};
    S.status = s;
    S.themes = Array.isArray(t.themes) ? t.themes : [];
    board.applyConfig({ ...s, ...c });
    await board.applyTheme(c.theme || s.theme);
    board.paintStats(s);
    S.entries = sortWidgets(S.server).map((x) => {
      S.key += 1;
      return { key: S.key, origId: x.id, w: JSON.parse(JSON.stringify(x)), deleted: false, notes: [], group: null, open: false };
    });
    S.undo = [];
    renderThemes();
    renderCards();
  }

  async function apply() {
    if (S.busy) return;
    const probs = problems();
    if (probs.length) return;
    S.busy = true;
    applyBtn.disabled = true;
    const lines = [];
    const step = (t) => {
      lines.push(t);
      say(lines.join("\n"));
    };
    try {
      const widgets = orderedLive().map((e, i) => {
        const clean = computed(e).clean;
        return { ...clean, order: i * 10 };
      });
      await api("PUT", "/api/widgets/import", { widgets });
      step(`Replaced board with ${widgets.length} tile${widgets.length === 1 ? "" : "s"}.`);
      step("Done. The board picks this up within 5 seconds.");
    } catch (err) {
      step(`Stopped: ${err.message || err}`);
      step("Reloaded what the board has now.");
    } finally {
      S.busy = false;
      const keep = lines.join("\n");
      try {
        await load();
      } catch (_err) {
        /* keep the log */
      }
      say(keep);
    }
  }

  function exportLayout() {
    const widgets = orderedLive().map((e, i) => ({ ...computed(e).clean, order: i * 10 }));
    const blob = new Blob([JSON.stringify({ widgets, theme: S.config.theme || "warm-dark" }, null, 2)], { type: "application/json" });
    const a = el("a");
    a.href = URL.createObjectURL(blob);
    a.download = "deskboard-layout.json";
    a.click();
    URL.revokeObjectURL(a.href);
    say("Downloaded deskboard-layout.json.");
  }

  async function importLayoutFile(file) {
    const text = await file.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (_err) {
      throw new Error("Import file is not valid JSON");
    }
    const list = Array.isArray(data) ? data : data.widgets;
    if (!Array.isArray(list)) throw new Error("Import needs a widgets array");
    pushUndo();
    S.entries = list.map((w) => {
      S.key += 1;
      const widget = JSON.parse(JSON.stringify(w));
      if (!widget.id) widget.id = slugId(widget.type || "tile");
      return { key: S.key, origId: null, w: widget, deleted: false, notes: ["Imported layout"], group: null, open: false };
    });
    if (data && typeof data.theme === "string") {
      try {
        await api("PATCH", "/api/config", { theme: data.theme });
        S.config.theme = data.theme;
        await board.applyTheme(data.theme);
        renderThemes();
      } catch (_err) {
        /* theme optional */
      }
    }
    renderCards();
  }

  applyBtn.addEventListener("click", apply);
  undoBtn.addEventListener("click", undo);
  discardBtn.addEventListener("click", () => {
    pushUndo();
    S.entries = sortWidgets(S.server).map((x) => {
      S.key += 1;
      return { key: S.key, origId: x.id, w: JSON.parse(JSON.stringify(x)), deleted: false, notes: [], group: null, open: false };
    });
    renderCards();
    say("Changes discarded.");
  });
  reloadTilesBtn.addEventListener("click", async () => {
    if (S.busy) return;
    S.busy = true;
    reloadTilesBtn.disabled = true;
    let lines = [];
    try {
      const r = await api("POST", "/api/reload", {});
      lines.push(`Tiles reloaded (version ${r.version}). Loaded: ${r.loaded.map((t) => t.id).join(", ") || "none"}.`);
      if (r.disabled.length) lines.push(`Off: ${r.disabled.join(", ")}.`);
      for (const p of r.skipped) lines.push(`Skipped ${p}`);
      await reloadTileCatalog();
      registerCatalogEditing();
      renderGallery();
      board.drawn = null;
    } catch (err) {
      lines.push(`Reload failed: ${err.message || err}`);
    } finally {
      S.busy = false;
      reloadTilesBtn.disabled = false;
    }
    renderCards();
    lines.push("The board picks up the new tiles within 5 seconds. Unsaved edits are still pending.");
    say(lines.join("\n"));
  });
  reloadBtn.addEventListener("click", () =>
    load()
      .then(() => say("Loaded the current board."))
      .catch((err) => say(String(err.message || err))),
  );
  exportBtn.addEventListener("click", exportLayout);
  importBtn.addEventListener("click", () => importInput.click());
  importInput.addEventListener("change", () => {
    const file = importInput.files && importInput.files[0];
    importInput.value = "";
    if (!file) return;
    importLayoutFile(file)
      .then(() => say("Layout imported locally. Press Apply to put it on the board."))
      .catch((err) => say(String(err.message || err)));
  });

  window.addEventListener("keydown", (ev) => {
    if ((ev.metaKey || ev.ctrlKey) && String(ev.key).toLowerCase() === "z") {
      ev.preventDefault();
      undo();
    }
  });

  load()
    .then(() => say("Loaded the current board. Drop files or edit tiles, check the preview, then Apply."))
    .catch((err) => say(`Could not load the board: ${err.message || err}`));

  window.__deskcfg = { S, takeFiles, apply, renderCards, parseIcs, parseText, parseJson, parseCsvRows, csvDefaults, board };
}

/* ---------- tile preview ---------- */

// /?tilepreview=<id>&theme=<theme> draws one catalog tile at all four spans
// on a 4 by 3 board with its example data. Add &check for the overflow report.
const PREVIEW_SPANS = [
  [2, 2],
  [1, 2],
  [1, 1],
  [2, 1],
];

async function startTilePreview() {
  document.documentElement.classList.add("kiosk");
  const root = el("div");
  clear(document.body);
  document.body.append(root);
  const board = new Board(root);
  const id = PARAMS.get("tilepreview") || "";
  const check = PARAMS.has("check");
  const resize = () => {
    board.setScale(window.innerWidth, window.innerHeight);
    board.fit();
  };
  board.setScale(window.innerWidth, window.innerHeight);
  window.addEventListener("resize", resize);
  const report = () => document.documentElement.setAttribute("data-overflow", JSON.stringify(overflowReport(root)));
  const say = (text) => {
    clear(board.grid);
    board.grid.append(el("p", "empty-hint", text));
    if (check) report();
  };
  let status = {};
  let config = {};
  let themes = [];
  try {
    const [st, cf, th] = await Promise.all(["/api/status", "/api/config", "/api/themes"].map((u) => fetch(u, { cache: "no-store" }).then((r) => r.json())));
    status = st;
    config = cf;
    themes = Array.isArray(th.themes) ? th.themes : [];
    await loadTileCatalog();
  } catch (err) {
    say(`Could not load the board: ${err.message || err}`);
    return;
  }
  const meta = TILE_CATALOG.get(id);
  if (!meta) {
    const off = tileCatalogAll.find((t) => t && t.id === id);
    say(off ? `${id} is off. Add it to enabled_community_tiles in config.json and restart.` : `No tile named ${id}`);
    return;
  }
  if (!TILE_RENDERERS.has(id)) {
    say(`tiles/${id}/render.js did not register a renderer`);
    return;
  }
  const theme = PARAMS.get("theme") || config.theme || status.theme;
  board.applyConfig({ ...status, ...config, theme });
  await board.applyTheme(theme);
  board.gridCols = 4;
  board.gridRows = 3;
  board.markNode.textContent = `${meta.name} preview`;
  board.zoneNode.textContent = theme;
  if (!check && themes.length) {
    const pick = el("select", "preview-theme");
    for (const t of themes) {
      const o = el("option", null, t.name || t.id);
      o.value = t.id;
      pick.append(o);
    }
    pick.value = theme;
    pick.addEventListener("change", () => {
      const next = new URLSearchParams(location.search);
      next.set("theme", pick.value);
      location.search = next.toString();
    });
    clear(board.zoneNode);
    board.zoneNode.append(pick);
  }
  const widgets = PREVIEW_SPANS.map(([cs, rs], i) => ({
    ...JSON.parse(JSON.stringify(meta.example)),
    id: `preview-${cs}x${rs}`,
    type: id,
    enabled: true,
    order: i * 10,
    col_span: cs,
    row_span: rs,
  }));
  board.setWidgets(widgets);
  board.paintStats(status);
  setInterval(() => board.paintClock(), 1000);
  const done = () => {
    board.fit();
    if (check) report();
  };
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => setTimeout(done, 150));
  else setTimeout(done, 150);
}

/* ---------- boot ---------- */

if (PARAMS.has("tilepreview")) startTilePreview();
else if (PARAMS.has("config") || location.pathname.replace(/\/+$/, "") === "/config") startConfigurator();
else startKiosk();
