// Record the README demo: configurator on the left, board on the right.
// Drives a real headless Chrome through the /?config page and captures both
// pages as numbered JPEG frames. scripts/record_demo.sh turns them into GIFs.
// usage: node record_demo.mjs <base-url> <frames-dir>
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, outDir] = process.argv.slice(2);
if (!base || !outDir) {
  console.error("usage: node record_demo.mjs <base-url> <frames-dir>");
  process.exit(2);
}
mkdirSync(outDir, { recursive: true });

const CFG = { w: 1280, h: 800 };
const BOARD = { w: 1280, h: 720 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function resolveChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
  ].filter(Boolean);
  for (const c of candidates) if (existsSync(c)) return c;
  for (const bin of ["google-chrome", "chromium", "chromium-browser"]) {
    const r = spawnSync("which", [bin], { encoding: "utf8" });
    if (r.status === 0) return r.stdout.trim().split("\n")[0];
  }
  throw new Error("Chrome/Chromium not found. Set CHROME_PATH.");
}

const prof = mkdtempSync(join(tmpdir(), "deskboard-demo-"));
const port = 9800 + Math.floor(Math.random() * 150);
const chrome = spawn(
  resolveChrome(),
  ["--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", `--user-data-dir=${prof}`, `--remote-debugging-port=${port}`, "about:blank"],
  { stdio: "ignore" },
);

async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise((r, j) => {
    ws.addEventListener("open", r);
    ws.addEventListener("error", j);
  });
  let id = 0;
  const pending = new Map();
  ws.addEventListener("message", (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) {
      pending.get(d.id)(d);
      pending.delete(d.id);
    }
  });
  const send = (method, params = {}) =>
    new Promise((r) => {
      id += 1;
      pending.set(id, r);
      ws.send(JSON.stringify({ id, method, params }));
    });
  return { ws, send };
}

async function openPage(url, size) {
  const res = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" });
  const target = await res.json();
  const page = await connect(target.webSocketDebuggerUrl);
  await page.send("Emulation.setDeviceMetricsOverride", { width: size.w, height: size.h, deviceScaleFactor: 1, mobile: false });
  await page.send("Page.enable");
  await page.send("Page.navigate", { url });
  return page;
}

async function evaluate(page, expression) {
  const r = await page.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "eval failed");
  return r.result?.result?.value;
}

// Overlay helpers injected into the configurator: a pointer, a caption bar,
// and small actions that use the page's own buttons, inputs, and drag events.
const HELPERS = String.raw`
(() => {
  if (window.__demo) return;
  const css = document.createElement("style");
  css.textContent = [
    "#demo-cursor{position:fixed;left:0;top:0;width:22px;height:22px;z-index:99999;pointer-events:none;transition:transform .55s cubic-bezier(.4,0,.2,1)}",
    "#demo-cursor svg{filter:drop-shadow(0 1px 2px rgba(0,0,0,.6))}",
    "#demo-cursor.press svg{transform:scale(.85)}",
    "#demo-caption{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:99998;pointer-events:none;background:rgba(10,10,12,.88);color:#fff;font:500 20px/1.3 system-ui,sans-serif;padding:10px 18px;border-radius:10px;border:1px solid rgba(255,255,255,.25);white-space:nowrap}",
    "#demo-caption:empty{display:none}",
  ].join("\n");
  document.head.append(css);
  const cur = document.createElement("div");
  cur.id = "demo-cursor";
  cur.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M2 1 L2 18 L7 13.5 L10.5 21 L13.5 19.7 L10 12.3 L17 12.3 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  document.body.append(cur);
  const cap = document.createElement("div");
  cap.id = "demo-caption";
  document.body.append(cap);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let pos = [900, 400];
  cur.style.transform = "translate(" + pos[0] + "px," + pos[1] + "px)";
  const cards = () => [...document.querySelectorAll(".cfg-card")];
  const card = (title) => cards().find((c) => c.querySelector(".cfg-card-title").textContent.startsWith(title));
  const center = (node) => {
    const r = node.getBoundingClientRect();
    return [r.left + r.width / 2, r.top + r.height / 2];
  };
  async function moveTo(node, dx = 0, dy = 0) {
    node.scrollIntoView({ block: "nearest" });
    await sleep(80);
    const [x, y] = center(node);
    pos = [x + dx, y + dy];
    cur.style.transform = "translate(" + pos[0] + "px," + pos[1] + "px)";
    await sleep(650);
  }
  async function click(node) {
    await moveTo(node);
    cur.classList.add("press");
    await sleep(140);
    node.click();
    cur.classList.remove("press");
    await sleep(350);
  }
  const buttonIn = (root, label) => [...root.querySelectorAll("button")].find((b) => b.textContent.trim() === label);
  window.__demo = {
    caption(text) {
      cap.textContent = text;
    },
    async scrollToCards() {
      const sec = document.querySelector(".cfg-cards").closest("section");
      window.scrollTo({ top: sec.getBoundingClientRect().top + window.scrollY - 20, behavior: "smooth" });
      await sleep(700);
    },
    async scrollTop() {
      window.scrollTo({ top: 0, behavior: "smooth" });
      await sleep(700);
    },
    async drag(fromTitle, toTitle) {
      const src = card(fromTitle);
      const dst = card(toTitle);
      await moveTo(src.querySelector(".cfg-grip"));
      const dt = new DataTransfer();
      src.dispatchEvent(new DragEvent("dragstart", { bubbles: true, dataTransfer: dt }));
      await sleep(200);
      const r = dst.getBoundingClientRect();
      const y = r.top + 6;
      pos = [r.left + 40, y];
      cur.style.transform = "translate(" + pos[0] + "px," + pos[1] + "px)";
      await sleep(700);
      dst.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: dt, clientX: pos[0], clientY: y }));
      await sleep(500);
      dst.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt, clientX: pos[0], clientY: y }));
      src.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer: dt }));
      await sleep(500);
    },
    async edit(title) {
      await click(buttonIn(card(title), "Edit"));
    },
    async done(title) {
      await click(buttonIn(card(title), "Done"));
    },
    async span(title, label) {
      await click(buttonIn(card(title).querySelector(".cfg-span"), label));
    },
    async type(title, labelStart, text, { replace = false } = {}) {
      const c = card(title);
      const label = [...c.querySelectorAll(".cfg-edit label")].find((l) => l.textContent.startsWith(labelStart));
      const node = label.querySelector("textarea,input");
      await click(node);
      node.focus();
      if (replace) {
        node.value = "";
        node.dispatchEvent(new Event("input", { bubbles: true }));
        await sleep(250);
      }
      for (const ch of text) {
        node.value += ch;
        node.dispatchEvent(new Event("input", { bubbles: true }));
        await sleep(ch === "\n" ? 160 : 45);
      }
      await sleep(400);
    },
    async apply() {
      await click([...document.querySelectorAll(".cfg-actions button")].find((b) => b.textContent === "Apply to board"));
    },
    async theme(name) {
      const btn = [...document.querySelectorAll(".cfg-theme")].find((b) => b.querySelector("strong").textContent === name);
      await click(btn);
    },
  };
})();
`;

// Wait until the board page shows what the configurator applied.
async function waitBoard(page, expr, timeoutMs = 9000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      if (await evaluate(page, expr)) return true;
    } catch {}
    await sleep(250);
  }
  console.error("board did not reflect change:", expr);
  return false;
}

let cfg;
let board;
let frame = 0;
let recording = false;
let interval = 100;
const log = [];

async function shoot(page) {
  const s = await page.send("Page.captureScreenshot", { format: "jpeg", quality: 88 });
  return Buffer.from(s.result.data, "base64");
}

async function recorder() {
  while (recording) {
    const t0 = Date.now();
    const [a, b] = await Promise.all([shoot(cfg), shoot(board)]);
    frame += 1;
    const n = String(frame).padStart(5, "0");
    writeFileSync(join(outDir, `cfg_${n}.jpg`), a);
    writeFileSync(join(outDir, `board_${n}.jpg`), b);
    const spent = Date.now() - t0;
    await sleep(Math.max(0, interval - spent));
  }
}

// While the board catches up on its 5 second poll, sample slower so the wait
// plays back as a short time-lapse.
async function fastForward(fn) {
  interval = 400;
  try {
    return await fn();
  } finally {
    interval = 100;
  }
}

try {
  for (let i = 0; i < 80; i += 1) {
    await sleep(150);
    try {
      await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
      break;
    } catch {}
  }
  board = await openPage(`${base}/`, BOARD);
  cfg = await openPage(`${base}/?config`, CFG);
  await sleep(3500);
  await evaluate(cfg, HELPERS);
  await evaluate(board, "document.fonts ? document.fonts.ready.then(() => true) : true");

  recording = true;
  const rec = recorder();
  const say = (t) => evaluate(cfg, `__demo.caption(${JSON.stringify(t)})`);
  const run = (js) => evaluate(cfg, js);
  await sleep(1200);

  // 1. Reorder
  await say("1. Drag the Today list ahead of World clocks, then Apply");
  await run("__demo.scrollToCards()");
  await run("__demo.drag('Today', 'World clocks')");
  await run("__demo.scrollTop()");
  await run("__demo.apply()");
  await fastForward(() =>
    waitBoard(board, `(() => { const ids = [...document.querySelectorAll('[data-widget-id]')].map(n => n.dataset.widgetId); return ids.indexOf('today') > -1 && ids.indexOf('today') < ids.indexOf('world'); })()`),
  );
  await sleep(1200);
  log.push("reorder");

  // 2. World clocks: add a city
  await say("2. Add Sydney to the world clocks");
  await run("__demo.scrollToCards()");
  await run("__demo.edit('World clocks')");
  await run("__demo.type('World clocks', 'Cities', '\\nSydney|Australia/Sydney')");
  await run("__demo.done('World clocks')");
  await run("__demo.scrollTop()");
  await run("__demo.apply()");
  await fastForward(() => waitBoard(board, `document.body.textContent.includes('Sydney')`));
  await sleep(1200);
  log.push("worldclock");

  // 3. Edit the list and make it tall
  await say("3. Rewrite the Today list and resize it to 1×2");
  await run("__demo.scrollToCards()");
  await run("__demo.edit('Today')");
  await run("__demo.type('Today', 'Items', 'Record the demo GIF\\nTag v1.0\\nWater the plants', { replace: true })");
  await run("__demo.span('Today', '1×2')");
  await run("__demo.done('Today')");
  await run("__demo.scrollTop()");
  await run("__demo.apply()");
  await fastForward(() => waitBoard(board, `document.body.textContent.includes('Water the plants')`));
  await sleep(1200);
  log.push("list");

  // 4. Theme
  await say("4. Switch the theme to Nord");
  await run("window.scrollTo({ top: document.querySelector('.cfg-themes').getBoundingClientRect().top + window.scrollY - 300, behavior: 'smooth' })");
  await sleep(700);
  await evaluate(board, "window.__vars = document.documentElement.style.cssText");
  await run("__demo.theme('Nord')");
  await fastForward(() =>
    waitBoard(board, "document.documentElement.style.cssText !== window.__vars"),
  );
  await sleep(1500);
  await run("__demo.scrollTop()");
  await say("");
  await sleep(2500);
  log.push("theme");

  recording = false;
  await rec;
  console.log(JSON.stringify({ frames: frame, steps: log }));
} finally {
  recording = false;
  try {
    cfg?.ws.close();
    board?.ws.close();
  } catch {}
  chrome.kill("SIGKILL");
  await sleep(200);
  rmSync(prof, { recursive: true, force: true });
}
