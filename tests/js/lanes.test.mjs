import assert from "node:assert/strict";
import { test } from "node:test";

import { formatTime, rulerTicks } from "../../web/lanes.js";

test("times read as minutes and seconds", () => {
  assert.equal(formatTime(0), "0:00");
  assert.equal(formatTime(61.95), "1:01");
  assert.equal(formatTime(61.95, true), "1:01.9");
  assert.equal(formatTime(-3), "0:00");
  assert.equal(formatTime(undefined), "0:00");
});

test("ruler labels stay at least 70px apart", () => {
  const width = 900;
  const duration = 272;
  const majors = rulerTicks(duration, width).filter((t) => t.major);
  const spacing = ((majors[1].time - majors[0].time) / duration) * width;
  assert.ok(spacing >= 70, `labels ${spacing}px apart`);
  assert.equal(majors[0].time, 0);
  assert.ok(majors.at(-1).time <= duration);
});

test("four minor marks sit between labels", () => {
  const ticks = rulerTicks(60, 1000);
  assert.deepEqual(ticks.slice(0, 6).map((t) => t.major), [true, false, false, false, false, true]);
});

test("a ruler with nothing to measure is empty", () => {
  assert.deepEqual(rulerTicks(0, 800), []);
  assert.deepEqual(rulerTicks(120, 0), []);
});

test("very long files fall back to fifteen minute labels", () => {
  const majors = rulerTicks(4 * 3600, 400).filter((t) => t.major);
  assert.equal(majors[1].time, 900);
});
