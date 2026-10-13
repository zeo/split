// decoded buffers keep every stem on one sample clock; past this much audio we
// stream through media elements instead and nudge them back into line
const BUFFER_LIMIT_STEM_MINUTES = 60;
const DRIFT_TOLERANCE = 0.035;

const toGain = (db) => (db <= -60 ? 0 : 10 ** (db / 20));

export class Mixer {
  constructor({ onEnded } = {}) {
    this.onEnded = onEnded;
    this.context = null;
    this.channels = new Map();
    this.duration = 0;
    this.offset = 0;
    this.startedAt = 0;
    this.playing = false;
    this.mode = "buffer";
    this.generation = 0;
  }

  ensureContext() {
    if (!this.context) {
      this.context = new AudioContext({ latencyHint: "interactive" });
      this.master = this.context.createGain();
      this.master.connect(this.context.destination);
    }
    return this.context;
  }

  async load(stems, duration, onReady) {
    this.dispose();
    const generation = ++this.generation;
    const context = this.ensureContext();
    this.duration = duration;
    this.mode = (duration / 60) * stems.length > BUFFER_LIMIT_STEM_MINUTES ? "media" : "buffer";
    for (const { stem } of stems) {
      const gain = context.createGain();
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      gain.connect(analyser).connect(this.master);
      this.channels.set(stem, { gain, analyser, db: 0, solo: false, mute: false, buffer: null, source: null, element: null, scratch: new Float32Array(1024) });
    }
    await Promise.all(stems.map(async ({ stem, url }) => {
      const channel = this.channels.get(stem);
      if (this.mode === "media") {
        const element = new Audio();
        element.preload = "auto";
        element.src = url;
        context.createMediaElementSource(element).connect(channel.gain);
        channel.element = element;
      } else {
        const bytes = await (await fetch(url)).arrayBuffer();
        if (generation !== this.generation) return;
        channel.buffer = await context.decodeAudioData(bytes);
      }
      if (generation === this.generation) onReady?.(stem);
    }));
    if (generation !== this.generation) return false;
    this.applyGains();
    return true;
  }

  position() {
    if (!this.playing) return this.offset;
    if (this.mode === "media") {
      const first = this.channels.values().next().value;
      return first?.element?.currentTime ?? this.offset;
    }
    return Math.min(this.duration, this.context.currentTime - this.startedAt);
  }

  async play() {
    if (this.playing || !this.channels.size) return;
    const context = this.ensureContext();
    await context.resume();
    if (this.offset >= this.duration - 0.01) this.offset = 0;
    if (this.mode === "media") {
      for (const channel of this.channels.values()) channel.element.currentTime = this.offset;
      await Promise.all([...this.channels.values()].map((c) => c.element.play()));
    } else {
      const when = context.currentTime + 0.04;
      for (const channel of this.channels.values()) {
        const source = context.createBufferSource();
        source.buffer = channel.buffer;
        source.connect(channel.gain);
        source.start(when, this.offset);
        channel.source = source;
      }
      this.startedAt = when - this.offset;
    }
    this.playing = true;
  }

  pause() {
    if (!this.playing) return;
    this.offset = this.position();
    this.halt();
  }

  halt() {
    for (const channel of this.channels.values()) {
      if (channel.source) {
        channel.source.onended = null;
        channel.source.stop();
        channel.source.disconnect();
        channel.source = null;
      }
      channel.element?.pause();
    }
    this.playing = false;
  }

  toggle() {
    return this.playing ? (this.pause(), false) : this.play().then(() => true);
  }

  seek(seconds) {
    const wasPlaying = this.playing;
    if (wasPlaying) this.halt();
    this.offset = Math.max(0, Math.min(this.duration, seconds));
    if (wasPlaying) this.play();
  }

  // called every animation frame by the ui
  tick() {
    if (!this.playing) return;
    const now = this.position();
    if (now >= this.duration - 0.005) {
      this.halt();
      this.offset = 0;
      this.onEnded?.();
      return;
    }
    if (this.mode === "media") {
      for (const channel of this.channels.values()) {
        if (Math.abs(channel.element.currentTime - now) > DRIFT_TOLERANCE) channel.element.currentTime = now;
      }
    }
  }

  set(stem, change) {
    Object.assign(this.channels.get(stem), change);
    this.applyGains();
  }

  audible(stem) {
    const channel = this.channels.get(stem);
    const soloing = [...this.channels.values()].some((c) => c.solo);
    return soloing ? channel.solo : !channel.mute;
  }

  applyGains() {
    if (!this.context) return;
    for (const [stem, channel] of this.channels) {
      const target = this.audible(stem) ? toGain(channel.db) : 0;
      channel.gain.gain.setTargetAtTime(target, this.context.currentTime, 0.012);
    }
  }

  level(stem) {
    const channel = this.channels.get(stem);
    if (!channel || !this.playing) return 0;
    channel.analyser.getFloatTimeDomainData(channel.scratch);
    let sum = 0;
    for (const value of channel.scratch) sum += value * value;
    const rms = Math.sqrt(sum / channel.scratch.length);
    return Math.max(0, Math.min(1, (20 * Math.log10(rms + 1e-9) + 54) / 54));
  }

  dispose() {
    this.generation++;
    this.halt();
    for (const channel of this.channels.values()) {
      channel.gain.disconnect();
      channel.analyser.disconnect();
      if (channel.element) channel.element.src = "";
    }
    this.channels.clear();
    this.offset = 0;
  }
}
