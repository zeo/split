/* Split stem studio. git+ design language: flat surfaces, embossed pills,
   mono machine text, run transcript stages, state dots. */
const $ = (id) => document.getElementById(id);
let TASKS = {}, MODELS = [], TIERS = ["fast", "balanced", "best", "ultra"];
let task = "vocals", tier = "balanced", format = "mp3";
let chosenFile = null, jobId = null, pollTimer = null;
let stemState = {}; // stem -> {url, audio, solo, mute, vol, peaks, canvas, color}

const TIER_LABEL = {
  fast: "Fast preview · seconds per track",
  balanced: "Balanced · quality/speed sweet spot",
  best: "Best · SOTA checkpoints, slower",
  ultra: "Ultra · multi-model ensembles, slowest",
};
const STEM_COLORS = { vocals: "#30a742", drums: "#3b82f6", bass: "#8250df", guitar: "#0e9f8a", piano: "#d29922", kick: "#3b82f6", snare: "#e5484d", instrumental: "#30a742" };
const TASK_ICON = {
  vocals: '<circle cx="12" cy="11" r="4"/><path d="M8 15v2a4 4 0 0 0 8 0v-2M12 21v-2"/>',
  karaoke: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
  band: '<path d="M4 10v4h3l4 3V7l-4 3H4z"/><path d="M15 9a4 4 0 0 1 0 6M18 7a7 7 0 0 1 0 10"/>',
  band6: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  drums: '<circle cx="12" cy="13" r="7"/><path d="M5 9l7-4 7 4M9 3l3 2 3-2"/>',
  cleanup: '<path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4L12 3z"/><path d="M18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9L18 15z"/>',
};
function icon(name) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${TASK_ICON[name] || TASK_ICON.vocals}</svg>`;
}

/* ---------- boot ---------- */
function initTheme() {
  const saved = localStorage.getItem("split_theme");
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = saved || "dark";
}
$("theme-btn").onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("split_theme", next);
  for (const st of Object.values(stemState)) paintStem(st, 0);
  if (chosenFile && !jobId) drawHeroPreview(chosenFile);
};

async function boot() {
  initTheme();
  try {
    const data = await (await fetch("/api/models")).json();
    TASKS = data.tasks || {};
    MODELS = data.models || [];
    if (data.tiers?.length) TIERS = data.tiers;
    renderTasks();
    const dev = data.device || "cpu";
    $("gpu-dot").style.background = dev === "cpu" ? "#8a8a8a" : "var(--ok)";
    $("engine-note").textContent = `local ${dev.toUpperCase()} · private`;
    const best = MODELS.filter((m) => m.quality === "best" && (m.sdr?.vocals || 0) >= 11)
      .map((m) => `${m.label} (vocal SDR ${m.sdr.vocals})`).join(" · ");
    if (best) $("models-note").textContent = `Rivaling lalal.ai - ${best} · runs on your GPU, nothing uploaded`;
  } catch { renderTasks(); }
  renderTiers();
  renderFormats();
  refreshModelNote();
}

function modelFor(t, q) {
  const wantStems = { vocals: 2, karaoke: 2, band: 4, band6: 6, drums: 6, cleanup: 2 }[t] || 2;
  const pool = MODELS.filter((m) => m.stems.length === wantStems);
  const pick = (pool.length ? pool : MODELS).filter((m) => m.quality === q);
  return pick[0] || pool[0] || MODELS[0] || {};
}

function refreshModelNote() {
  const m = modelFor(task, tier);
  const sdr = m.sdr?.vocals ? ` · vocal <b>SDR ${m.sdr.vocals}</b>` : "";
  $("preset-desc").innerHTML = `${TIER_LABEL[tier]} - ${m.label || "auto"}${sdr}`;
  renderStemChecks(m);
}

/* ---------- sidebar ---------- */
function renderTasks() {
  const box = $("usecases");
  box.innerHTML = "";
  const entries = Object.entries(TASKS);
  const fallback = [["vocals", { label: "Vocals", desc: "Lead vocal + instrumental" }],
    ["karaoke", { label: "Karaoke", desc: "Instrumental track maker" }],
    ["band", { label: "Full band", desc: "Vocals / drums / bass / other" }],
    ["band6", { label: "Band 6-stem", desc: "+ guitar and piano" }],
    ["drums", { label: "Drum kit", desc: "Kick / snare / toms / cymbals" }],
    ["cleanup", { label: "Cleanup", desc: "Denoise / de-reverb" }]];
  for (const [id, info] of (entries.length ? entries : fallback)) {
    const b = document.createElement("button");
    b.className = "task" + (id === task ? " on" : "");
    const hint = { vocals: "2 stems", karaoke: "2 stems", band: "4 stems", band6: "6 stems", drums: "6 stems", cleanup: "2 stems" }[id] || "";
    b.innerHTML = `<span class="glyph">${icon(id)}</span><span><strong>${info.label}</strong><small>${info.desc || ""}</small></span><span class="tier-hint">${hint}</span>`;
    b.onclick = () => {
      task = id;
      [...box.children].forEach((c) => c.classList.remove("on"));
      b.classList.add("on");
      refreshModelNote();
      if (chosenFile) setJobSub();
    };
    box.appendChild(b);
  }
}

function renderTiers() {
  const seg = $("quality-seg");
  seg.innerHTML = "";
  for (const q of TIERS) {
    const b = document.createElement("button");
    b.textContent = q[0].toUpperCase() + q.slice(1);
    b.dataset.q = q;
    b.setAttribute("role", "radio");
    if (q === tier) b.classList.add("on");
    b.onclick = () => {
      tier = q;
      [...seg.children].forEach((c) => c.classList.remove("on"));
      b.classList.add("on");
      refreshModelNote();
      if (chosenFile) setJobSub();
    };
    seg.appendChild(b);
  }
}

function renderFormats() {
  const seg = $("format-seg");
  seg.innerHTML = "";
  for (const f of ["mp3", "wav", "flac"]) {
    const b = document.createElement("button");
    b.textContent = f.toUpperCase();
    b.setAttribute("role", "radio");
    if (f === format) b.classList.add("on");
    b.onclick = () => {
      format = f;
      [...seg.children].forEach((c) => c.classList.remove("on"));
      b.classList.add("on");
    };
    seg.appendChild(b);
  }
}

function renderStemChecks(m) {
  const box = $("stem-checks");
  box.innerHTML = "";
  for (const s of (m.stems || ["vocals", "instrumental"])) {
    const lab = document.createElement("label");
    lab.className = "chip";
    lab.innerHTML = `<input type="checkbox" checked data-stem="${s}"> ${s}`;
    lab.querySelector("input").onchange = (e) => lab.classList.toggle("off", !e.target.checked);
    box.appendChild(lab);
  }
}

/* ---------- file intake + hero waveform ---------- */
let heroCtx = null;
function setFile(f) {
  if (!f) return;
  stopAll();
  stemState = {};
  chosenFile = f;
  $("dz-title").textContent = f.name;
  $("dz-sub").textContent = `${(f.size / 1048576).toFixed(1)} MB · click again to replace`;
  $("file-meta").textContent = `${(TASKS[task] || {}).label || task} · ${tier} · ${format.toUpperCase()}`;
  $("hero-icon").parentElement.classList.add("live");
  drawHeroPreview(f);
  $("job-panel").classList.remove("hidden");
  $("job-name").textContent = f.name;
  setJobSub();
  $("go").disabled = false;
  $("results").classList.add("hidden");
  $("stats").classList.add("hidden");
}
function setJobSub() {
  $("job-sub").textContent = `${(TASKS[task] || {}).label || task} · ${tier} · ${modelFor(task, tier).label || ""}`;
}

async function drawHeroPreview(f) {
  const canvas = $("hero-wave");
  canvas.classList.remove("hidden");
  try {
    heroCtx = heroCtx || new (window.AudioContext || window.webkitAudioContext)();
    const buf = await heroCtx.decodeAudioData(await f.arrayBuffer());
    const peaks = computePeaks(buf, 220);
    paintWave(canvas, peaks, "#30a742", 0);
  } catch { canvas.classList.add("hidden"); }
}

function computePeaks(buf, n) {
  const ch = buf.getChannelData(0);
  const step = Math.max(1, Math.floor(ch.length / n));
  const peaks = [];
  for (let i = 0; i < n; i++) {
    let mx = 0;
    const start = i * step;
    for (let j = start; j < Math.min(start + step, ch.length); j += 4) {
      const v = Math.abs(ch[j]);
      if (v > mx) mx = v;
    }
    peaks.push(mx);
  }
  return peaks;
}

function paintWave(canvas, peaks, color, progress) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || canvas.parentElement.clientWidth - 48;
  const h = 72;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const c = canvas.getContext("2d");
  c.scale(dpr, dpr);
  c.clearRect(0, 0, w, h);
  const bw = w / peaks.length;
  peaks.forEach((p, i) => {
    const bh = Math.max(2, p * (h - 8));
    const x = i * bw + bw * 0.2;
    const light = document.documentElement.dataset.theme === "light";
    c.fillStyle = (i / peaks.length) <= progress ? color : (light ? "rgba(24,24,27,0.14)" : "rgba(255,255,255,0.14)");
    c.beginPath();
    c.roundRect(x, (h - bh) / 2, Math.max(1.5, bw * 0.6), bh, 2);
    c.fill();
  });
}

$("file").onchange = (e) => setFile(e.target.files[0]);
const dz = $("dropzone");
dz.onclick = (e) => { if (e.target.tagName !== "INPUT") $("file").click(); };
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));
dz.addEventListener("keydown", (e) => { if (e.key === "Enter") $("file").click(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !$("job-panel").classList.contains("hidden") && !$("go").disabled && document.activeElement.tagName !== "INPUT") $("go").click();
});
$("overlap").oninput = (e) => ($("overlap-val").textContent = e.target.value);
$("shifts").oninput = (e) => ($("shifts-val").textContent = e.target.value === "0" ? "auto" : e.target.value);

/* ---------- jobs ---------- */
const stageClock = {};
function fmtElapsed(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}
function setStage(name) {
  const order = ["upload", "analyze", "separate", "encode"];
  const now = Date.now();
  const idx = name === "done" || name === "error" ? 99 : order.indexOf(name);
  document.querySelectorAll("#stages li").forEach((li) => {
    const key = li.dataset.s;
    const i = order.indexOf(key);
    const timer = li.querySelector(".timer");
    if (key === name && !stageClock[key]) stageClock[key] = now;
    if (i < idx || name === "done") {
      li.classList.remove("active");
      li.classList.add(name === "error" && i === idx ? "failed" : "done");
      if (stageClock[key] && timer && !timer.textContent) timer.textContent = fmtElapsed(now - stageClock[key]);
    } else if (key === name) {
      li.classList.add("active");
      li.classList.remove("done", "failed");
      if (timer) timer.textContent = "working…";
    } else {
      li.classList.remove("active", "done", "failed");
      if (timer) timer.textContent = "";
      delete stageClock[key];
    }
  });
  if (name === "upload") for (const k of Object.keys(stageClock)) delete stageClock[k];
}
setInterval(() => {
  const now = Date.now();
  document.querySelectorAll("#stages li.active .timer").forEach((t) => {
    const key = t.closest("li").dataset.s;
    if (stageClock[key]) t.textContent = fmtElapsed(now - stageClock[key]);
  });
}, 500);

$("go").onclick = async () => {
  if (!chosenFile) return;
  const fd = new FormData();
  fd.append("file", chosenFile);
  fd.append("task", task);
  fd.append("tier", tier);
  fd.append("output_format", format);
  const checked = [...document.querySelectorAll("#stem-checks input:checked")].map((i) => i.dataset.stem);
  if (checked.length) fd.append("stems", checked.join(","));
  fd.append("overlap", $("overlap").value);
  if (tier === "ultra" || $("enhanced").checked) fd.append("enhanced", "true");
  if ($("shifts").value !== "0") fd.append("shifts", $("shifts").value);

  $("go").disabled = true;
  $("results").classList.add("hidden");
  $("progress").classList.remove("hidden");
  setStage("upload");
  $("status-msg").textContent = "Uploading…";

  const res = await fetch("/api/jobs", { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    $("status-msg").textContent = "Error: " + (err.detail || res.statusText);
    setStage("upload");
    $("go").disabled = false;
    return;
  }
  jobId = (await res.json()).id;
  setStage("analyze");
  pollTimer = setInterval(poll, 1500);
  poll();
};

async function poll() {
  let job;
  try {
    job = await (await fetch(`/api/jobs/${jobId}`)).json();
  } catch {
    $("status-msg").textContent = "Connection lost - retrying…";
    return;
  }
  const p = job.progress || 0;
  $("bar").style.width = `${p * 100}%`;
  $("pct").textContent = `${Math.round(p * 100)}%`;
  $("status-msg").textContent = `${job.message || job.status} · ${job.model_label || job.model || ""}`;
  $("job-sub").textContent = `${job.filename || ""} · ${job.model_label || ""}`;
  setStage(p < 0.05 ? "upload" : p < 0.15 ? "analyze" : p < 0.9 ? "separate" : "encode");
  if (job.status === "done") {
    clearInterval(pollTimer);
    $("go").disabled = false;
    $("tb-zip").disabled = false;
    setStage("done");
    showResults(job);
  } else if (job.status === "error") {
    clearInterval(pollTimer);
    $("go").disabled = false;
    setStage("upload");
  }
}

/* ---------- results: per-stem mixer ---------- */
function showResults(job) {
  const urls = job.stems || {};
  const box = $("tracks");
  box.innerHTML = "";
  stemState = {};
  const m = MODELS.find((x) => x.id === job.model) || {};
  const names = Object.keys(urls);
  $("results-sub").textContent = `${names.length} stems · ${m.label || ""} · solo / mute to preview the mix`;
  names.forEach((stem, i) => showResultsEntry(box, m, stem, urls[stem], i));
  $("results").classList.remove("hidden");
  $("progress").classList.add("hidden");
  $("stats").classList.add("hidden");
  $("results").scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function showResultsEntry(box, m, stem, url, i) {
  const palette = Object.values(STEM_COLORS);
  const color = STEM_COLORS[stem.toLowerCase()] || STEM_COLORS[stem.toLowerCase().replace(/s$/, "")] || palette[i % palette.length];
  div.style.setProperty("--stem", color);
  const sdr = m.sdr?.[stem] ?? (stem === "vocals" ? m.sdr?.vocals : null);
  const div = document.createElement("div");
  div.className = "track";
  div.innerHTML = `
    <div>
      <div class="stem-top"><span class="stem-dot" style="background:${color}"></span>
        <div class="stem-name">${stem}${sdr ? `<span class="stem-sdr">SDR ${sdr}</span>` : ""}</div></div>
      <div class="stem-btns">
        <button class="mini solo">S</button><button class="mini mute">M</button>
      </div>
    </div>
    <div class="stem-right">
      <canvas height="64" title="Click to seek"></canvas>
      <div class="stem-row2">
        <audio controls preload="metadata" src="${url}"></audio>
        <label class="vol">vol <input type="range" min="0" max="1" step="0.01" value="1"></label>
        <button class="dl-btn" title="Download ${stem}">⤓</button>
      </div>
    </div>`;
  box.appendChild(div);
  const audio = div.querySelector("audio");
  const st = { url, audio, solo: false, mute: false, vol: 1, peaks: null, canvas: div.querySelector("canvas"), color, div, raf: 0 };
  stemState[stem] = st;

  div.querySelector(".solo").onclick = (e) => {
    st.solo = !st.solo;
    e.target.classList.toggle("solo-on", st.solo);
    div.classList.toggle("soloed", st.solo);
    applyMix();
  };
  div.querySelector(".mute").onclick = (e) => {
    st.mute = !st.mute;
    e.target.classList.toggle("mute-on", st.mute);
    div.classList.toggle("muted-d", st.mute);
    applyMix();
  };
  div.querySelector(".vol input").oninput = (e) => { st.vol = +e.target.value; applyMix(); };
  div.querySelector(".dl-btn").onclick = () => {
    const a = document.createElement("a");
    a.href = url;
    a.download = stem;
    a.click();
  };
  audio.onplay = () => { div.classList.add("playing"); drawProgress(st); };
  audio.onpause = audio.onended = () => { div.classList.remove("playing"); cancelAnimationFrame(st.raf); paintStem(st, audio.currentTime / (audio.duration || 1)); };
  audio.onloadedmetadata = () => loadPeaks(st);
  st.canvas.onclick = (e) => {
    if (!audio.duration) return;
    const r = st.canvas.getBoundingClientRect();
    audio.currentTime = ((e.clientX - r.left) / r.width) * audio.duration;
  };
}

function applyMix() {
  const anySolo = Object.values(stemState).some((s) => s.solo);
  for (const s of Object.values(stemState)) {
    const audible = anySolo ? s.solo : !s.mute;
    s.audio.volume = audible ? s.vol : 0;
  }
}

async function loadPeaks(st) {
  try {
    heroCtx = heroCtx || new (window.AudioContext || window.webkitAudioContext)();
    const buf = await heroCtx.decodeAudioData(await (await fetch(st.url)).arrayBuffer());
    st.peaks = computePeaks(buf, 180);
    paintStem(st, 0);
  } catch { /* keep native player only */ }
}

function paintStem(st, progress) {
  if (!st.peaks) return;
  paintWave(st.canvas, st.peaks, st.color, progress || 0);
}
function drawProgress(st) {
  cancelAnimationFrame(st.raf);
  const step = () => {
    if (st.audio.paused) return;
    paintStem(st, st.audio.currentTime / (st.audio.duration || 1));
    st.raf = requestAnimationFrame(step);
  };
  step();
}

/* ---------- transport ---------- */
function stopAll() {
  for (const s of Object.values(stemState)) {
    try { s.audio.pause(); } catch { /* noop */ }
    cancelAnimationFrame(s.raf);
  }
  $("play-all").textContent = "▶ Play all";
}
$("dl-all").onclick = () => { if (jobId) window.location = `/api/jobs/${jobId}/download`; };
$("tb-zip").onclick = () => { if (jobId) window.location = `/api/jobs/${jobId}/download`; };
$("reset").onclick = () => {
  stopAll();
  stemState = {};
  chosenFile = null;
  $("file").value = "";
  $("dz-title").textContent = "Drop audio to separate";
  $("dz-sub").textContent = "mp3 · wav · flac · ogg · m4a - studio stems in seconds";
  $("file-meta").textContent = "";
  $("hero-wave").classList.add("hidden");
  $("job-panel").classList.add("hidden");
  $("results").classList.add("hidden");
  $("stats").classList.remove("hidden");
};
$("play-all").onclick = () => {
  const audios = Object.values(stemState).map((s) => s.audio);
  if (!audios.length) return;
  const anyPlaying = audios.some((a) => !a.paused);
  if (anyPlaying) {
    audios.forEach((a) => a.pause());
    $("play-all").textContent = "▶ Play all";
  } else {
    applyMix();
    audios.forEach((a) => { a.currentTime = 0; a.play().catch(() => {}); });
    $("play-all").textContent = "⏸ Pause";
  }
};

boot();
