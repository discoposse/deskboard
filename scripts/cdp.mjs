// Minimal Chrome DevTools driver (no npm deps). Node 22+ for global WebSocket.
// usage: node cdp.mjs <url> <w> <h> <shot.png|-> [waitMs] [evalExpr]
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, w, h, shot, waitMs = "2500", expr = ""] = process.argv.slice(2);
const prof = mkdtempSync(join(tmpdir(), "cdp-"));
const port = 9300 + Math.floor(Math.random() * 500);

function which(bin) {
  const r = spawnSync("which", [bin], { encoding: "utf8" });
  if (r.status === 0) return r.stdout.trim().split("\n")[0];
  return "";
}

function resolveChrome() {
  const absolute = [
    process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
  ].filter(Boolean);
  for (const candidate of absolute) {
    if (existsSync(candidate)) return candidate;
  }
  for (const bin of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) {
    const hit = which(bin);
    if (hit) return hit;
  }
  throw new Error("Chrome/Chromium not found. Set CHROME_PATH.");
}

const chromeBin = resolveChrome();
const chrome = spawn(
  chromeBin,
  [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--hide-scrollbars",
    `--user-data-dir=${prof}`,
    `--remote-debugging-port=${port}`,
    `--window-size=${w},${h}`,
    "about:blank",
  ],
  { stdio: "ignore" },
);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws;
try {
  let target;
  for (let i = 0; i < 80 && !target; i++) {
    await sleep(150);
    try {
      target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page");
    } catch {}
  }
  if (!target) throw new Error("Chrome DevTools target not ready");
  ws = new WebSocket(target.webSocketDebuggerUrl);
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
      id++;
      pending.set(id, r);
      ws.send(JSON.stringify({ id, method, params }));
    });
  await send("Emulation.setDeviceMetricsOverride", { width: +w, height: +h, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Page.navigate", { url });
  await sleep(+waitMs);
  if (expr) {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) {
      console.log("EXCEPTION", JSON.stringify(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails));
    } else {
      console.log(
        typeof r.result?.result?.value === "string"
          ? r.result.result.value
          : JSON.stringify(r.result?.result?.value ?? r.result ?? r.error),
      );
    }
  }
  if (shot && shot !== "-") {
    const s = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(shot, Buffer.from(s.result.data, "base64"));
  }
} finally {
  try {
    ws && ws.close();
  } catch {}
  chrome.kill("SIGKILL");
  await sleep(200);
  rmSync(prof, { recursive: true, force: true });
}
