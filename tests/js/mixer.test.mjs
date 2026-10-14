import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { Mixer, wrap } from "../../web/mixer.js";

// just enough of the web audio graph for the mixer's bookkeeping
class FakeParam {
  constructor() {
    this.value = 1;
  }
  setTargetAtTime(value) {
    this.value = value;
  }
}

class FakeNode {
  constructor() {
    this.gain = new FakeParam();
  }
  connect(next) {
    return next;
  }
  disconnect() {}
}

const started = [];

class FakeSource extends FakeNode {
  start(when, offset) {
    this.started = { when, offset };
    started.push(this);
  }
  stop() {}
}

class FakeContext {
  constructor() {
    this.currentTime = 10;
    this.destination = new FakeNode();
  }
  createGain() {
    return new FakeNode();
  }
  createAnalyser() {
    return new FakeNode();
  }
  createBufferSource() {
    return new FakeSource();
  }
  async decodeAudioData() {
    return { duration: 30 };
  }
  async resume() {}
}

globalThis.AudioContext = FakeContext;
globalThis.fetch = async () => ({ arrayBuffer: async () => new ArrayBuffer(8) });

let mixer;

beforeEach(async () => {
  started.length = 0;
  mixer = new Mixer();
  await mixer.load(["original", "vocals", "drums"].map((stem) => ({ stem, url: stem })), 30);
});

const gainOf = (stem) => mixer.channels.get(stem).gain.gain.value;

test("solo silences every other lane, mute only its own", () => {
  mixer.set("vocals", { solo: true });
  assert.deepEqual(["original", "vocals", "drums"].map((s) => mixer.audible(s)), [false, true, false]);
  mixer.set("vocals", { solo: false });
  mixer.set("drums", { mute: true });
  assert.equal(gainOf("drums"), 0);
  assert.equal(gainOf("vocals"), 1);
});

test("gain follows decibels and bottoms out at -60", () => {
  mixer.set("vocals", { db: -6 });
  assert.ok(Math.abs(gainOf("vocals") - 0.501) < 0.001);
  mixer.set("vocals", { db: -60 });
  assert.equal(gainOf("vocals"), 0);
});

test("the a/b reference is the only thing heard while it is on", () => {
  mixer.referenceStem = "original";
  mixer.set("original", { mute: true });
  mixer.setReference(true);
  assert.equal(gainOf("original"), 1);
  assert.equal(gainOf("vocals"), 0);
  mixer.setReference(false);
  assert.equal(gainOf("original"), 0);
  assert.equal(gainOf("vocals"), 1);
});

test("a/b does nothing without a reference lane", () => {
  mixer.referenceStem = null;
  mixer.setReference(true);
  assert.equal(mixer.reference, false);
});

test("loops wrap playback between their ends", () => {
  const loop = { start: 10, end: 14 };
  assert.equal(wrap(12, loop), 12);
  assert.equal(wrap(14, loop), 10);
  assert.equal(wrap(17, loop), 13);
  assert.equal(wrap(17, null), 17);
});

test("setting a region turns looping on and orders its ends", () => {
  mixer.setRegion(20, 5);
  assert.deepEqual(mixer.region, { start: 5, end: 20 });
  assert.equal(mixer.looping, true);
  mixer.setRegion(3, 3.1);
  assert.equal(mixer.region, null);
  assert.equal(mixer.looping, false);
});

test("playing with a loop starts inside it and every source loops", async () => {
  mixer.setRegion(5, 9);
  mixer.seek(20);
  await mixer.play();
  assert.equal(started.length, 3);
  for (const source of started) {
    assert.equal(source.loop, true);
    assert.equal(source.loopStart, 5);
    assert.equal(source.loopEnd, 9);
    assert.equal(source.started.offset, 5);
  }
  mixer.context.currentTime += 6;
  // sources start 40 ms after play, so 6 s later 5.96 s have played: 4 to the loop end, then 1.96 more
  assert.ok(Math.abs(mixer.position() - 6.96) < 1e-9);
});

test("turning the loop off keeps the region for later", () => {
  mixer.setRegion(5, 9);
  mixer.setLooping(false);
  assert.equal(mixer.loop, null);
  assert.deepEqual(mixer.region, { start: 5, end: 9 });
  mixer.setLooping(true);
  assert.deepEqual(mixer.loop, { start: 5, end: 9 });
});

test("playback ends at the end of the file when nothing loops", async () => {
  let ended = 0;
  mixer.onEnded = () => ended++;
  mixer.seek(29.5);
  await mixer.play();
  mixer.context.currentTime += 1;
  mixer.tick();
  assert.equal(ended, 1);
  assert.equal(mixer.playing, false);
  assert.equal(mixer.position(), 0);
});
