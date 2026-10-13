import { api, native, subscribe, whenNative } from "./api.js";
import { drawWave, formatTime } from "./lanes.js";
import { Mixer } from "./mixer.js";

const $ = (id) => document.getElementById(id);

const STEM_COLORS = {
  vocals: "#d9b45a", instrumental: "#6f9fca", lead: "#e3a35c", backing: "#87b1a1",
  drums: "#d9654a", bass: "#5c8fd8", other: "#99a877", guitar: "#c58bd0", piano: "#cdb791",
  kick: "#d9654a", snare: "#e39a48", toms: "#ad7bd3", hihat: "#79b9c1", cymbals: "#cbc068",
  dry: "#8dc1a8", reverb: "#7d8ed3", clean: "#8dc1a8", noise: "#ad9080", crowd: "#c98a69",
};
const FORMAT_NOTES = {
  wav: "24-bit PCM at the source sample rate",
  flac: "24-bit lossless at the source sample rate",
  mp3: "320 kbps, for sharing rather than mixing",
};
const STATUS_TEXT = { queued: "Waiting", cancelled: "Cancelled", done: "Done" };
const colorOf = (stem) => STEM_COLORS[stem] ?? "#9aa5ab";
const megabytes = (bytes) => (bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`);

const saved = JSON.parse(localStorage.getItem("split.settings") || "{}");
const state = {
  catalog: null,
  task: saved.task ?? "vocals",
  tiers: saved.tiers ?? {},
  stems: saved.stems ?? {},
  isolate: saved.isolate ?? {},
  format: saved.format ?? "wav",
  staged: [],
  snapshot: { jobs: [], downloads: {}, opened: { seq: 0 } },
  selected: null,
  openedSeq: null,
  session: null,
};
const mixer = new Mixer({ onEnded: () => renderTransport() });

function persist() {
  const { task, tiers, stems, isolate, format } = state;
  localStorage.setItem("split.settings", JSON.stringify({ task, tiers, stems, isolate, format }));
}

const currentTask = () => state.catalog.tasks.find((t) => t.id === state.task) ?? state.catalog.tasks[0];
const currentTier = (task = currentTask()) => {
  const id = state.tiers[task.id];
  return task.tiers.find((t) => t.id === id) ?? task.tiers.find((t) => t.id === task.default_tier);
};
const isolating = (task = currentTask()) => task.isolatable && Boolean(state.isolate[task.id]);
const stemChoices = (task = currentTask()) => (isolating(task) ? [...task.stems, "instrumental"] : task.stems);
const chosenStems = (task = currentTask()) => {
  const picked = state.stems[task.id];
  const choices = stemChoices(task);
  const kept = picked ? choices.filter((s) => picked.includes(s)) : choices;
  return kept.length ? kept : choices;
};
const jobById = (id) => state.snapshot.jobs.find((j) => j.id === id);

/* rail */

function radio(container, items, current, onPick) {
  container.replaceChildren();
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(item.id === current));
    button.textContent = item.label;
    button.addEventListener("click", () => onPick(item.id));
    container.append(button);
  }
}

function renderTasks() {
  const nav = $("tasks");
  nav.replaceChildren();
  nav.setAttribute("role", "radiogroup");
  const groups = [["separate", "Separate"], ["clean", "Clean up"]];
  for (const [group, title] of groups) {
    const heading = document.createElement("p");
    heading.className = "task-group";
    heading.textContent = title;
    nav.append(heading);
    for (const task of state.catalog.tasks.filter((t) => t.group === group)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "task";
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", String(task.id === state.task));
      const label = document.createElement("span");
      label.textContent = task.label;
      const count = document.createElement("span");
      count.className = "task-count";
      count.textContent = task.stems.length;
      const blurb = document.createElement("span");
      blurb.className = "task-blurb";
      blurb.textContent = task.blurb;
      button.append(label, count, blurb);
      button.addEventListener("click", () => {
        state.task = task.id;
        persist();
        renderRail();
      });
      nav.append(button);
    }
  }
}

function renderTier() {
  const task = currentTask();
  const tier = currentTier(task);
  $("tiers").classList.toggle("hidden", task.tiers.length < 2);
  radio($("tiers"), task.tiers, tier.id, (id) => {
    state.tiers[task.id] = id;
    persist();
    renderRail();
  });
  $("tier-blurb").textContent = tier.blurb;
  const list = $("tier-models");
  list.replaceChildren();
  for (const id of tier.models) {
    const model = state.catalog.models[id];
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = `${model.author} ${model.label}`;
    const side = document.createElement("span");
    side.className = model.present ? "license" : "license pending";
    side.textContent = model.present ? model.license.replace("Not stated by the author", "license unstated") : megabytes(model.missing);
    side.title = model.present ? model.license : "Downloads on first use";
    item.append(name, side);
    list.append(item);
  }
}

function renderStems() {
  const task = currentTask();
  const box = $("stem-picks");
  box.replaceChildren();
  const chosen = chosenStems(task);
  for (const stem of stemChoices(task)) {
    const label = document.createElement("label");
    label.className = "stem-pick";
    label.style.setProperty("--stem", colorOf(stem));
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = chosen.includes(stem);
    input.addEventListener("change", () => {
      const next = stemChoices(task).filter((s) => (s === stem ? input.checked : chosenStems(task).includes(s)));
      if (!next.length) {
        input.checked = true;
        return;
      }
      state.stems[task.id] = next;
      persist();
      renderRoute();
    });
    const dot = document.createElement("span");
    dot.className = "dot";
    const name = document.createElement("span");
    name.textContent = stem;
    label.append(input, dot, name);
    box.append(label);
  }
  $("isolate-row").classList.toggle("hidden", !task.isolatable);
  $("isolate").checked = isolating(task);
}

function renderFormats() {
  const formats = state.catalog.formats.map((id) => ({ id, label: id.toUpperCase() }));
  radio($("formats"), formats, state.format, (id) => {
    state.format = id;
    persist();
    renderFormats();
  });
  $("format-note").textContent = FORMAT_NOTES[state.format];
}

function renderFirstRun() {
  const task = currentTask();
  const tier = currentTier(task);
  const ids = new Set(tier.models);
  if (isolating(task)) ids.add("leap-xe-voc");
  const missing = [...ids].reduce((sum, id) => sum + (state.catalog.models[id].missing || 0), 0);
  $("first-run").textContent = missing
    ? `${task.label} at this quality needs ${megabytes(missing)} of model weights. They download once, on the first run.`
    : "Everything runs on this computer. Nothing is uploaded.";
}

function routeItem(className, ...children) {
  const item = document.createElement("li");
  item.className = className;
  item.append(...children);
  return item;
}

function stemChip(stem) {
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.style.setProperty("--stem", colorOf(stem));
  chip.textContent = stem;
  return chip;
}

function renderRoute() {
  const task = currentTask();
  const tier = currentTier(task);
  const steps = isolating(task) ? tier.isolated_steps : tier.steps;
  const route = $("route");
  route.replaceChildren(routeItem("source", "your file"));
  for (const step of steps) {
    if (step.input !== "mix") route.append(routeItem("", stemChip(step.input)));
    const models = step.models.map((id) => state.catalog.models[id]);
    const box = document.createElement("span");
    box.className = "box";
    if (models.length > 1) {
      box.textContent = `${models.map((m) => m.label).join(" + ")}, averaged`;
    } else {
      const by = document.createElement("span");
      by.className = "by";
      by.textContent = models[0].author;
      box.append(`${models[0].label} `, by);
    }
    route.append(routeItem("model", box));
  }
  const outputs = document.createElement("span");
  outputs.style.display = "inline-flex";
  outputs.style.gap = "12px";
  outputs.append(...chosenStems(task).map(stemChip));
  route.append(routeItem("", outputs));
}

function renderRail() {
  renderTasks();
  renderTier();
  renderStems();
  renderFormats();
  renderFirstRun();
  renderRoute();
}

$("isolate").addEventListener("change", (event) => {
  state.isolate[state.task] = event.target.checked;
  persist();
  renderStems();
  renderFirstRun();
  renderRoute();
});

/* staging */

function stage(items) {
  const known = new Set(state.staged.map((s) => s.key));
  for (const item of items) if (!known.has(item.key)) state.staged.push(item);
  state.selected = null;
  renderStage();
}

const stagePaths = (paths) => stage(paths.map((path) => ({ key: path, path, name: path.split(/[\\/]/).pop() })));
const stageFiles = (files) => stage([...files].map((file) => ({ key: `${file.name}:${file.size}:${file.lastModified}`, file, name: file.name })));

function renderStaged() {
  const list = $("staged-list");
  list.replaceChildren();
  for (const item of state.staged) {
    const row = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = item.name;
    const drop = document.createElement("button");
    drop.type = "button";
    drop.textContent = "remove";
    drop.addEventListener("click", () => {
      state.staged = state.staged.filter((s) => s !== item);
      renderStage();
    });
    row.append(name, drop);
    list.append(row);
  }
  const count = state.staged.length;
  $("staged-title").textContent = count === 1 ? "1 file ready" : `${count} files ready`;
}

async function separate() {
  if (!state.staged.length) return;
  const task = currentTask();
  const settings = { task: task.id, tier: currentTier(task).id, isolate: isolating(task), stems: chosenStems(task), format: state.format };
  const paths = state.staged.filter((s) => s.path).map((s) => s.path);
  const files = state.staged.filter((s) => s.file).map((s) => s.file);
  $("go").disabled = true;
  try {
    const created = [];
    if (paths.length) created.push(...(await api.post("/api/jobs", { ...settings, paths })).jobs);
    if (files.length) {
      const form = new FormData();
      for (const [key, value] of Object.entries(settings)) form.append(key, Array.isArray(value) ? value.join(",") : String(value));
      for (const file of files) form.append("files", file);
      created.push(...(await api.post("/api/jobs", form)).jobs);
    }
    state.staged = [];
    state.selected = created[0]?.id ?? null;
  } catch (error) {
    $("staged-title").textContent = error.message;
  } finally {
    $("go").disabled = false;
    renderStage();
  }
}

/* queue dock */

function jobStatusText(job) {
  if (job.status === "running") return job.detail || "Working";
  if (job.status === "error") return job.error || "Failed";
  return STATUS_TEXT[job.status] ?? job.status;
}

function jobActions(job) {
  const actions = [];
  if (job.status === "queued" || job.status === "running") actions.push(["Cancel", () => api.post(`/api/jobs/${job.id}/cancel`)]);
  if (job.status === "error" || job.status === "cancelled") actions.push(["Retry", async () => { state.selected = (await api.post(`/api/jobs/${job.id}/retry`)).id; }]);
  if (job.status !== "queued" && job.status !== "running") {
    actions.push(["Remove", async () => {
      if (state.selected === job.id) state.selected = null;
      await api.remove(`/api/jobs/${job.id}`);
    }]);
  }
  return actions;
}

function taskLine(job) {
  const task = state.catalog.tasks.find((t) => t.id === job.task);
  const tier = task?.tiers.find((t) => t.id === job.tier);
  const parts = [task?.label ?? job.task, task && task.tiers.length > 1 ? tier?.label : null, job.format.toUpperCase()];
  return parts.filter(Boolean).join(" Â· ");
}

function renderJobs() {
  const list = $("jobs");
  const jobs = state.snapshot.jobs;
  $("dock-count").textContent = jobs.length ? String(jobs.length) : "";
  if (!jobs.length) {
    list.innerHTML = '<li class="jobs-empty">Separated songs show up here and stay for a week.</li>';
    return;
  }
  list.replaceChildren();
  for (const job of jobs) {
    const row = document.createElement("li");
    row.className = "job" + (job.id === state.selected ? " selected" : "");
    row.dataset.status = job.status;
    row.tabIndex = 0;
    const dot = document.createElement("span");
    dot.className = "job-state";
    const name = document.createElement("span");
    name.className = "job-name";
    name.textContent = job.name;
    const task = document.createElement("span");
    task.className = "job-task mono";
    task.textContent = taskLine(job);
    const status = document.createElement("span");
    status.className = "job-status";
    if (job.status === "running") {
      const bar = document.createElement("span");
      bar.className = "bar";
      bar.innerHTML = "<span></span>";
      bar.firstChild.style.width = `${Math.round((job.fraction || 0) * 100)}%`;
      status.append(bar);
    }
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = jobStatusText(job);
    text.title = text.textContent;
    status.append(text);
    const actions = document.createElement("span");
    actions.className = "job-actions";
    for (const [label, run] of jobActions(job)) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        run().catch((error) => alert(error.message));
      });
      actions.append(button);
    }
    row.append(dot, name, task, status, actions);
    const pick = () => {
      state.selected = job.id;
      state.staged = state.staged.length ? state.staged : [];
      renderStage();
    };
    row.addEventListener("click", pick);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter") pick();
    });
    list.append(row);
  }
}

/* main stage */

function show(view) {
  for (const id of ["intake", "staged", "session", "progress"]) $(id).classList.toggle("hidden", !view.includes(id));
}

function renderStage() {
  renderJobs();
  const job = state.selected ? jobById(state.selected) : null;
  if (!job) {
    closeSession();
    renderStaged();
    show(state.staged.length ? ["staged", "intake"] : ["intake"]);
    document.title = "Split";
    return;
  }
  document.title = `${job.name} Â· Split`;
  if (job.status === "done") {
    show(["session"]);
    if (state.session?.id !== job.id) openSession(job);
    return;
  }
  closeSession();
  show(["progress"]);
  renderProgress(job);
}

function renderProgress(job) {
  $("progress-name").textContent = job.name;
  $("progress-task").textContent = taskLine(job);
  const meter = $("meter");
  const fraction = job.status === "running" && job.phase === "download" ? job.phase_fraction : job.fraction;
  const busy = job.status === "running" && (fraction == null || job.phase === "starting");
  meter.classList.toggle("indeterminate", busy);
  $("meter-fill").style.width = busy ? "" : `${Math.round((fraction || 0) * 100)}%`;
  meter.setAttribute("aria-valuenow", String(Math.round((fraction || 0) * 100)));
  const detail = job.status === "queued" ? "Waiting for the job ahead of it" : job.status === "running" ? job.detail : STATUS_TEXT[job.status] ?? "";
  $("progress-detail").textContent = detail;
  $("progress-error").classList.toggle("hidden", job.status !== "error");
  $("progress-error").textContent = job.error ?? "";
  $("progress-clock").textContent = progressClock(job);
  $("progress-cancel").classList.toggle("hidden", !["queued", "running"].includes(job.status));
  $("progress-retry").classList.toggle("hidden", !["error", "cancelled"].includes(job.status));
}

function progressClock(job) {
  if (job.status !== "running" || !job.started) return "";
  const elapsed = Date.now() / 1000 - job.started;
  const fraction = job.fraction || 0;
  const text = `${formatTime(elapsed)} elapsed`;
  if (fraction < 0.08 || job.phase === "download") return text;
  return `${text} · about ${formatTime((elapsed * (1 - fraction)) / fraction)} left`;
}

setInterval(() => {
  const job = state.selected ? jobById(state.selected) : null;
  if (job?.status === "running") $("progress-clock").textContent = progressClock(job);
}, 1000);

$("progress-cancel").addEventListener("click", () => api.post(`/api/jobs/${state.selected}/cancel`));
$("progress-retry").addEventListener("click", async () => {
  state.selected = (await api.post(`/api/jobs/${state.selected}/retry`)).id;
  renderStage();
});

/* session: lanes + transport */

function closeSession() {
  if (!state.session) return;
  mixer.dispose();
  for (const lane of state.session.lanes) lane.observer.disconnect();
  $("lanes").querySelectorAll(".lane").forEach((n) => n.remove());
  state.session = null;
  renderTransport();
}

async function openSession(job) {
  closeSession();
  const stems = Object.keys(job.outputs);
  const session = { id: job.id, job, lanes: [], ready: false };
  state.session = session;
  $("session-name").textContent = job.name;
  $("session-meta").textContent = `${taskLine(job)} Â· ${formatTime(job.duration)}`;
  $("clock-total").textContent = `/ ${formatTime(job.duration)}`;
  $("export").classList.toggle("hidden", !native());
  $("mix-note").classList.add("hidden");
  const template = $("lane-template");
  for (const [index, stem] of stems.entries()) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.style.setProperty("--stem", colorOf(stem));
    node.querySelector(".lane-name").textContent = stem;
    node.querySelector(".lane-key").textContent = index < 9 ? String(index + 1) : "";
    const save = node.querySelector(".lane-save");
    save.href = `/api/jobs/${job.id}/stems/${stem}?download=true`;
    save.download = "";
    const lane = { stem, node, canvas: node.querySelector("canvas"), peaks: null, level: node.querySelector(".level span") };
    lane.observer = new ResizeObserver(() => drawWave(lane.canvas, lane.peaks, colorOf(stem)));
    lane.observer.observe(lane.canvas);
    wireLane(lane);
    $("lanes").append(node);
    session.lanes.push(lane);
    api.get(`/api/jobs/${job.id}/peaks/${stem}`).then((peaks) => {
      lane.peaks = peaks;
      drawWave(lane.canvas, peaks, colorOf(stem));
    });
  }
  renderTransport();
  const loaded = await mixer.load(stems.map((stem) => ({ stem, url: `/api/jobs/${job.id}/stems/${stem}` })), job.duration);
  if (state.session !== session || !loaded) return;
  session.ready = true;
  if (mixer.mode === "media") {
    $("mix-note").textContent = "This session is long, so preview streams from disk. Playback may drift by a few milliseconds between stems; the files themselves are exact.";
    $("mix-note").classList.remove("hidden");
  }
  renderTransport();
}

function wireLane(lane) {
  const { node, stem } = lane;
  const solo = node.querySelector(".solo");
  const mute = node.querySelector(".mute");
  const gain = node.querySelector(".gain");
  const readout = node.querySelector(".gain-read");
  const toggle = (button, key) => {
    const on = button.getAttribute("aria-pressed") !== "true";
    button.setAttribute("aria-pressed", String(on));
    mixer.set(stem, { [key]: on });
    refreshAudible();
  };
  solo.setAttribute("aria-pressed", "false");
  mute.setAttribute("aria-pressed", "false");
  solo.addEventListener("click", () => toggle(solo, "solo"));
  mute.addEventListener("click", () => toggle(mute, "mute"));
  lane.solo = () => toggle(solo, "solo");
  lane.mute = () => toggle(mute, "mute");
  gain.addEventListener("input", () => {
    const db = Number(gain.value);
    readout.textContent = db <= -60 ? "-inf" : db.toFixed(1);
    mixer.set(stem, { db });
  });
  gain.addEventListener("dblclick", () => {
    gain.value = "0";
    gain.dispatchEvent(new Event("input"));
  });
  const wave = node.querySelector(".lane-wave");
  const hover = node.querySelector(".lane-hover");
  const timeAt = (event) => {
    const box = wave.getBoundingClientRect();
    return Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)) * mixer.duration;
  };
  wave.addEventListener("pointermove", (event) => {
    hover.textContent = formatTime(timeAt(event), true);
    const box = wave.getBoundingClientRect();
    hover.style.left = `${Math.min(box.width - 56, event.clientX - box.left + 8)}px`;
  });
  wave.addEventListener("pointerdown", (event) => {
    wave.setPointerCapture(event.pointerId);
    mixer.seek(timeAt(event));
    const drag = (move) => mixer.seek(timeAt(move));
    wave.addEventListener("pointermove", drag);
    wave.addEventListener("pointerup", () => wave.removeEventListener("pointermove", drag), { once: true });
  });
}

function refreshAudible() {
  for (const lane of state.session?.lanes ?? []) {
    lane.node.classList.toggle("silent", !mixer.audible(lane.stem));
  }
}

function renderTransport() {
  const ready = Boolean(state.session?.ready);
  const play = $("play");
  play.disabled = !ready;
  play.classList.toggle("playing", mixer.playing);
  play.setAttribute("aria-label", mixer.playing ? "Pause" : "Play");
  play.title = ready ? `${mixer.playing ? "Pause" : "Play"} (Space)` : "Loading audio";
}

async function togglePlay() {
  if (!state.session?.ready) return;
  await mixer.toggle();
  renderTransport();
}

$("play").addEventListener("click", togglePlay);

function frame() {
  mixer.tick();
  const session = state.session;
  if (session) {
    const position = mixer.position();
    $("clock").textContent = formatTime(position, true);
    const lanes = $("lanes");
    const wave = session.lanes[0]?.node.querySelector(".lane-wave");
    if (wave && mixer.duration) {
      const x = wave.offsetLeft + (position / mixer.duration) * wave.clientWidth;
      $("playhead").style.transform = `translateX(${x - wave.offsetLeft}px)`;
      $("playhead").style.left = `${wave.offsetLeft}px`;
      $("playhead").style.height = `${lanes.scrollHeight}px`;
    }
    for (const lane of session.lanes) lane.level.style.width = `${Math.round(mixer.level(lane.stem) * 100)}%`;
    if (!mixer.playing && $("play").classList.contains("playing")) renderTransport();
  }
  requestAnimationFrame(frame);
}

$("zip").addEventListener("click", () => {
  if (state.session) window.location.href = `/api/jobs/${state.session.id}/zip`;
});
$("reveal").addEventListener("click", () => {
  if (state.session) api.post(`/api/jobs/${state.session.id}/reveal`).catch((error) => alert(error.message));
});
$("export").addEventListener("click", async () => {
  const bridge = native();
  if (!bridge || !state.session) return;
  const folder = await bridge.pick_folder();
  if (!folder) return;
  try {
    const { files } = await api.post(`/api/jobs/${state.session.id}/export`, { folder });
    $("session-meta").textContent = `Saved ${files.length} files to ${folder}`;
  } catch (error) {
    alert(error.message);
  }
});

/* models sheet */

function renderModels() {
  const list = $("model-list");
  list.replaceChildren();
  for (const model of Object.values(state.catalog.models)) {
    const download = state.snapshot.downloads[model.id];
    const item = document.createElement("li");
    item.className = "model";
    const title = document.createElement("div");
    title.className = "model-title";
    title.textContent = `${model.label} `;
    const by = document.createElement("span");
    by.className = "by";
    by.textContent = `by ${model.author}`;
    title.append(by);
    const meta = document.createElement("div");
    meta.className = "model-meta";
    const link = document.createElement("a");
    link.href = model.source;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "source";
    const scores = Object.entries(model.scores).map(([stem, sdr]) => `${stem} ${sdr.toFixed(2)}`).join(", ");
    meta.append(`${model.license} Â· ${megabytes(model.size)}${scores ? ` Â· SDR ${scores}` : ""} Â· `, link);
    const side = document.createElement("div");
    side.className = "model-side";
    if (download && ["queued", "running"].includes(download.status)) {
      const bar = document.createElement("span");
      bar.className = "bar";
      bar.innerHTML = "<span></span>";
      bar.firstChild.style.width = `${Math.round((download.fraction || 0) * 100)}%`;
      side.append(bar, actionButton("Stop", () => api.post(`/api/models/${model.id}/cancel`)));
    } else if (model.present) {
      side.append("Ready", actionButton("Remove", async () => { await api.remove(`/api/models/${model.id}`); await refreshCatalog(); }));
    } else {
      if (download?.status === "error") side.append(download.error);
      side.append(actionButton("Download", () => api.post(`/api/models/${model.id}/download`)));
    }
    item.append(title, side, meta);
    if (model.note) {
      const note = document.createElement("div");
      note.className = "model-note";
      note.textContent = model.note;
      item.append(note);
    }
    list.append(item);
  }
}

function actionButton(label, run) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "quiet";
  button.textContent = label;
  button.addEventListener("click", () => run().catch((error) => alert(error.message)));
  return button;
}

$("open-models").addEventListener("click", () => {
  renderModels();
  $("models-sheet").showModal();
});
$("close-models").addEventListener("click", () => $("models-sheet").close());

/* theme */

const THEMES = ["system", "dark", "light"];
function applyTheme(choice) {
  const dark = choice === "dark" || (choice === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  $("theme").textContent = `Theme: ${choice}`;
  for (const lane of state.session?.lanes ?? []) drawWave(lane.canvas, lane.peaks, colorOf(lane.stem));
}
$("theme").addEventListener("click", () => {
  const next = THEMES[(THEMES.indexOf(localStorage.getItem("split.theme") || "system") + 1) % THEMES.length];
  localStorage.setItem("split.theme", next);
  applyTheme(next);
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(localStorage.getItem("split.theme") || "system"));

/* intake: drops, picker, keyboard */

let dragDepth = 0;
const stageEl = $("stage");
stageEl.addEventListener("dragenter", (event) => {
  event.preventDefault();
  dragDepth++;
  stageEl.classList.add("dropping");
});
stageEl.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) stageEl.classList.remove("dropping");
});
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => {
  event.preventDefault();
  dragDepth = 0;
  stageEl.classList.remove("dropping");
  // the desktop shell reads real paths on the python side and offers them over the event stream
  if (!native() && event.dataTransfer?.files.length) stageFiles(event.dataTransfer.files);
});

async function addFiles() {
  const bridge = native();
  if (bridge) {
    const picked = await bridge.pick_files();
    if (picked.length) stagePaths(picked);
  } else {
    $("file-input").click();
  }
}
$("add-files").addEventListener("click", addFiles);
$("file-input").addEventListener("change", (event) => {
  stageFiles(event.target.files);
  event.target.value = "";
});
$("go").addEventListener("click", separate);
$("clear-staged").addEventListener("click", () => {
  state.staged = [];
  renderStage();
});

document.addEventListener("keydown", (event) => {
  const target = event.target;
  const typing = target instanceof HTMLInputElement && target.type !== "range" && target.type !== "checkbox";
  if (typing || $("models-sheet").open) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "o") {
    event.preventDefault();
    addFiles();
    return;
  }
  if (event.key === "Enter" && state.staged.length && !state.selected) {
    event.preventDefault();
    separate();
    return;
  }
  if (!state.session) return;
  if (event.code === "Space") {
    event.preventDefault();
    togglePlay();
  } else if (event.key === "Home") {
    mixer.seek(0);
  } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    if (target instanceof HTMLInputElement && target.type === "range") return;
    event.preventDefault();
    const step = (event.shiftKey ? 1 : 5) * (event.key === "ArrowLeft" ? -1 : 1);
    mixer.seek(mixer.position() + step);
  } else if (/^Digit[1-9]$/.test(event.code)) {
    const lane = state.session.lanes[Number(event.code.slice(5)) - 1];
    if (lane) event.shiftKey ? lane.mute() : lane.solo();
  } else if (event.key === "Escape") {
    for (const lane of state.session.lanes) {
      const solo = lane.node.querySelector(".solo");
      if (solo.getAttribute("aria-pressed") === "true") lane.solo();
    }
  }
});

/* boot */

async function refreshCatalog() {
  state.catalog = await api.get("/api/catalog");
  renderRail();
  if ($("models-sheet").open) renderModels();
}

function renderDevice(snapshot) {
  const device = $("device");
  if (snapshot.fatal) {
    device.textContent = "engine failed";
    device.title = snapshot.fatal.message;
    device.classList.add("warn");
    return;
  }
  const info = snapshot.device;
  if (!info) return;
  device.classList.toggle("warn", info.kind === "cpu");
  device.textContent = info.kind === "cpu" ? "CPU only" : info.name.replace(/^NVIDIA (GeForce )?/, "");
  device.title = info.note || (info.kind === "cpu" ? "No supported GPU found. Expect several minutes per song." : `Running on ${info.name}`);
}

function onSnapshot(snapshot) {
  const before = state.snapshot.downloads;
  state.snapshot = snapshot;
  renderDevice(snapshot);
  if (state.openedSeq === null) state.openedSeq = snapshot.opened.seq;
  else if (snapshot.opened.seq !== state.openedSeq) {
    state.openedSeq = snapshot.opened.seq;
    stagePaths(snapshot.opened.paths);
  }
  const finished = Object.entries(snapshot.downloads).some(([id, d]) => d.status === "done" && before[id]?.status !== "done");
  const jobDone = snapshot.jobs.some((j) => j.status === "done" && j.finished && Date.now() / 1000 - j.finished < 3);
  if (finished || jobDone) refreshCatalog();
  if ($("models-sheet").open) renderModels();
  if (state.selected && !jobById(state.selected)) state.selected = null;
  renderStage();
}

async function boot() {
  applyTheme(localStorage.getItem("split.theme") || "system");
  const [system] = await Promise.all([api.get("/api/system"), refreshCatalog()]);
  $("version").textContent = `v${system.version}`;
  $("data-dir").textContent = system.data_dir;
  renderStage();
  subscribe(onSnapshot);
  whenNative(() => $("export").classList.toggle("hidden", !state.session));
  requestAnimationFrame(frame);
}

boot();
