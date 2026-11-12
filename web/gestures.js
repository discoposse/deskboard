/* Pointer math for the configurator canvas.
   Loaded before app.js. Also required by the gesture tests. */
"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DeskboardGestures = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  // Index among the given tile rects where a tile should land.
  // rects are in visual order and do not include the tile being dragged.
  function insertionIndex(rects, x, y) {
    const list = Array.isArray(rects) ? rects : [];
    for (let i = 0; i < list.length; i += 1) {
      const r = list[i] || {};
      const width = Number(r.width) || 0;
      const height = Number(r.height) || 0;
      const left = Number(r.left) || 0;
      const top = Number(r.top) || 0;
      const cx = left + width / 2;
      const aboveRow = y < top;
      const sameRow = y >= top && y <= top + height;
      if (aboveRow || (sameRow && x < cx)) return i;
    }
    return list.length;
  }

  function nextSpan(start, delta, cell) {
    const base = Number(start) >= 2 ? 2 : 1;
    if (!Number.isFinite(cell) || cell <= 0 || !Number.isFinite(delta)) return base;
    if (base === 1 && delta > cell * 0.35) return 2;
    if (base === 2 && delta < -cell * 0.35) return 1;
    return base;
  }

  // handle is n, e, s, w, ne, nw, se, or sw.
  // dx and dy are viewport pixels from the pointer-down point.
  // Positive dx is to the right. Positive dy is down.
  function spanFromDrag(startCol, startRow, handle, dx, dy, cellW, cellH) {
    const name = String(handle || "");
    const growX = name.indexOf("w") >= 0 ? -dx : name.indexOf("e") >= 0 ? dx : 0;
    const growY = name.indexOf("n") >= 0 ? -dy : name.indexOf("s") >= 0 ? dy : 0;
    return {
      col: nextSpan(startCol, growX, cellW),
      row: nextSpan(startRow, growY, cellH),
    };
  }

  return { insertionIndex, spanFromDrag };
});
