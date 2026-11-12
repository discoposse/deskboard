import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { insertionIndex, spanFromDrag } = require("../web/gestures.js");

const row = [
  { left: 0, top: 0, width: 100, height: 80 },
  { left: 110, top: 0, width: 100, height: 80 },
  { left: 0, top: 100, width: 100, height: 80 },
];

test("insertionIndex lands before the tile under the pointer", () => {
  assert.equal(insertionIndex([], 0, 0), 0);
  assert.equal(insertionIndex(row, 10, 10), 0);
  assert.equal(insertionIndex(row, 90, 20), 1);
  assert.equal(insertionIndex(row, 160, 20), 2);
  assert.equal(insertionIndex(row, 20, 140), 2);
  assert.equal(insertionIndex(row, 400, 400), 3);
});

test("spanFromDrag snaps col_span and row_span between 1 and 2", () => {
  assert.deepEqual(spanFromDrag(1, 1, "e", 100, 0, 100, 100), { col: 2, row: 1 });
  assert.deepEqual(spanFromDrag(1, 1, "e", 20, 0, 100, 100), { col: 1, row: 1 });
  assert.deepEqual(spanFromDrag(2, 1, "e", -40, 0, 100, 100), { col: 1, row: 1 });
  assert.deepEqual(spanFromDrag(1, 1, "w", -40, 0, 100, 100), { col: 2, row: 1 });
  assert.deepEqual(spanFromDrag(1, 1, "n", 0, -40, 100, 100), { col: 1, row: 2 });
  assert.deepEqual(spanFromDrag(1, 1, "se", 40, 40, 100, 100), { col: 2, row: 2 });
  assert.deepEqual(spanFromDrag(1, 1, "n", 80, 0, 100, 100), { col: 1, row: 1 });
  assert.deepEqual(spanFromDrag(2, 2, "sw", 40, 40, 100, 100), { col: 1, row: 2 });
  assert.deepEqual(spanFromDrag(1, 1, "e", 0, 0, 0, 0), { col: 1, row: 1 });
});
