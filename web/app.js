import { api, native, subscribe, whenNative } from "./api.js";
import { drawWave, formatTime, rulerTicks } from "./lanes.js";
import { Mixer } from "./mixer.js";

const $ = (id) => document.getElementById(id);

// one letter per task, shown in brackets in the sidebar and pressed to switch
const TASK_KEYS = { vocals: "v", instrumental: "i", karaoke: "k", band4: "b", band6: "s", drums: "d", dereverb: "r", denoise: "n", crowd: "c" };
const FORMAT_NOTES = {
  wav: "24-bit PCM at the source sample rate",
  flac: "24-bit lossless at the source sample rate",
  mp3: "320 kbps, for sharing rather than mixing",
};
const FORMAT_BITS = { wav: "24-bit", flac: "24-bit", mp3: "320k" };
const STATUS_TEXT = { queued: "Waiting", cancelled: "Cancelled", done: "Done" };
const ORIGINAL = "original";
// stem pigments live in the active style's tokens; canvas drawing needs the resolved value
const stemVar = (stem) => `var(--stem-${stem}, var(--mute))`;
const colorOf = (stem) => getComputedStyle(document.documentElement).getPropertyValue(`--stem-${stem}`).trim() || "#9a9a9a";
const megabytes = (bytes) => (bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`);
const failed = (error) => alert(error.message);

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

function pickTask(id) {
  state.task = id;
  persist();
  renderRail();
}

function renderTasks() {
  const nav = $("tasks");
  nav.replaceChildren();
  nav.setAttribute("role", "radiogroup");
  for (const [group, title] of [["separate", "Separate"], ["clean", "Clean up"]]) {
    const heading = document.createElement("h2");
    heading.className = "rule-head task-group";
    heading.textContent = title;
    nav.append(heading);
    for (const task of state.catalog.tasks.filter((t) => t.group === group)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "nav-item";
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", String(task.id === state.task));
      button.title = task.blurb;
      const key = document.createElement("span");
      key.className = "nav-item-key";
      const open = document.createElement("span");
      open.className = "nav-item-bracket";
      open.textContent = "[";
      const close = open.cloneNode();
      close.textContent = "]";
      key.append(open, TASK_KEYS[task.id] ?? "", close);
      const label = document.createElement("span");
      label.textContent = task.label;
      const count = document.createElement("span");
      count.className = "nav-item-count";
      count.textContent = task.stems.length;
      button.append(key, label, count);
      button.addEventListener("click", () => pickTask(task.id));
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
    name.textContent = model.label;
    name.title = `${model.label} by ${model.author}`;
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
    label.style.setProperty("--stem", stemVar(stem));
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
  if (state.catalog) renderRoute();
}

function renderFirstRun() {
  const task = currentTask();
  const tier = currentTier(task);
  const ids = new Set(tier.models);
  if (isolating(task)) ids.add("leap-xe-voc");
  const missing = [...ids].reduce((sum, id) => sum + (state.catalog.models[id].missing || 0), 0);
  $("first-run").textContent = missing
    ? `This needs ${megabytes(missing)} of model weights. They download once, on the first run, and every file is checked before it loads.`
    : "Everything runs on this computer. Nothing is uploaded.";
}

function stemTap(stem) {
  const tap = document.createElement("span");
  tap.className = "patch-tap";
  tap.style.setProperty("--stem", stemVar(stem));
  tap.textContent = stem;
  return tap;
}

function wire() {
  const line = document.createElement("span");
  line.className = "patch-wire";
  return line;
}

function patchNode(title, note, className = "") {
  const node = document.createElement("span");
  node.className = `patch-node ${className}`;
  node.append(title);
  if (note) {
    const small = document.createElement("small");
    small.textContent = note;
    node.append(small);
  }
  return node;
}

function renderRoute() {
  const task = currentTask();
  const tier = currentTier(task);
  const steps = isolating(task) ? tier.isolated_steps : tier.steps;
  $("intake-title").textContent = task.label;
  $("intake-blurb").textContent = task.blurb;
  const patch = $("route");
  patch.replaceChildren(patchNode("your file", "any format", "source"));
  const finals = chosenStems(task);
  const side = [];
  steps.forEach((step, index) => {
    if (step.input !== "mix") patch.append(wire(), stemTap(step.input));
    const models = step.models.map((id) => state.catalog.models[id]);
    const title = models.length > 1 ? models.map((m) => m.label).join(" + ") : models[0].label;
    const note = models.length > 1 ? "averaged sample by sample" : models[0].author;
    patch.append(wire(), patchNode(title, note));
    if (index < steps.length - 1) side.push(...step.outputs.filter((o) => finals.includes(o)));
  });
  const outputs = document.createElement("ul");
  outputs.className = "patch-out";
  for (const stem of finals) {
    const item = document.createElement("li");
    item.style.setProperty("--stem", stemVar(stem));
    item.textContent = stem;
    if (side.includes(stem)) item.classList.add("side");
    outputs.append(item);
  }
  patch.append(wire(), outputs);
  renderSpec(task, tier);
}

function renderSpec(task, tier) {
  const models = [...new Set(tier.models)].map((id) => state.catalog.models[id]);
  if (isolating(task)) models.unshift(state.catalog.models["leap-xe-voc"]);
  const missing = models.reduce((sum, m) => sum + (m.missing || 0), 0);
  const size = models.reduce((sum, m) => sum + m.size, 0);
  // quote the task's lead stem, the number the task is judged by, from the strongest model that publishes it
  const lead = task.stems.find((stem) => models.some((m) => m.scores[stem] != null));
  const best = lead ? [lead, Math.max(...models.map((m) => m.scores[lead] ?? -Infinity))] : null;
  const licenses = [...new Set(models.map((m) => (m.license === "Not stated by the author" ? "unstated" : m.license === "Unknown" ? "unknown" : m.license)))];
  const cells = [
    ["models", models.length === 1 ? models[0].label : `${models.length} in chain`],
    ["published sdr", best ? `${best[1].toFixed(2)} dB ${best[0]}` : "not published"],
    ["weights", missing ? `${megabytes(missing)} to fetch` : `${megabytes(size)} ready`, missing ? "warn" : ""],
    ["license", licenses.join(", ")],
    ["output", `${state.format} ${FORMAT_BITS[state.format]}`],
  ];
  const spec = $("intake-spec");
  spec.replaceChildren();
  for (const [term, value, tone] of cells) {
    const cell = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    dd.title = value;
    if (tone) dd.className = tone;
    cell.append(dt, dd);
    spec.append(cell);
  }
  $("task-meta").textContent = `${state.catalog.tasks.length} modes`;
  $("tier-meta").textContent = tier.label;
  $("stem-meta").textContent = `${chosenStems(task).length} of ${stemChoices(task).length}`;
  $("format-meta").textContent = FORMAT_BITS[state.format];
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
  notice("");
  renderStage();
}

function notice(text) {
  $("intake-notice").textContent = text;
  $("intake-notice").classList.toggle("hidden", !text);
}

const stagePaths = (paths) => stage(paths.map((path) => ({ key: path, path, name: path.split(/[\\/]/).pop() })));
const stageFiles = (files) => stage([...files].map((file) => ({ key: `${file.name}:${file.size}:${file.lastModified}`, file, name: file.name })));
const stageStem = (job, stem) => stage([{ key: `stem:${job.id}:${stem}`, stemOf: { job: job.id, stem }, name: `${job.name} (${stem})` }]);

// folders and saved paths go through the server, which expands folders and drops what no longer exists
async function stageScanned(paths) {
  try {
    const found = (await api.post("/api/scan", { paths })).paths;
    if (found.length) stagePaths(found);
    else notice("No audio or video files in there.");
  } catch (error) {
    state.selected = null;
    renderStage();
    notice(error.message);
  }
}

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
  const stems = state.staged.filter((s) => s.stemOf).map((s) => s.stemOf);
  const files = state.staged.filter((s) => s.file).map((s) => s.file);
  $("go").disabled = true;
  try {
    const created = [];
    if (paths.length || stems.length) created.push(...(await api.post("/api/jobs", { ...settings, paths, stems_of: stems })).jobs);
    if (files.length) {
      const form = new FormData();
      for (const [key, value] of Object.entries(settings)) form.append(key, Array.isArray(value) ? value.join(",") : String(value));
      for (const file of files) form.append("files", file);
      created.push(...(await api.post("/api/jobs", form)).jobs);
    }
    state.staged = [];
    state.selected = created[0]?.id ?? null;
  } catch (error) {
    notice(error.message);
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
  return parts.filter(Boolean).join(" · ");
}

function renderJobs() {
  const list = $("jobs");
  const jobs = state.snapshot.jobs;
  $("dock-count").textContent = jobs.length ? String(jobs.length) : "";
  $("clear-finished").classList.toggle("hidden", !jobs.some((j) => !["queued", "running"].includes(j.status)));
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
        run().catch(failed);
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
  $("title-session").textContent = job ? job.name : "";
  if (!job) {
    closeSession();
    renderStaged();
    show(state.staged.length ? ["staged", "intake"] : ["intake"]);
    document.title = "split";
    return;
  }
  document.title = `${job.name} · split`;
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
  $("progress-copy").classList.toggle("hidden", job.status !== "error");
}

// everything a bug report needs, without screenshots: the message, the setup, and the worker's traceback
async function copyDetails() {
  const job = jobById(state.selected);
  if (!job) return;
  const log = await api.get(`/api/jobs/${job.id}/log`).then((r) => r.log, () => "");
  const device = state.snapshot.device;
  const lines = [
    `Split ${$("version").textContent}`,
    `${taskLine(job)} · ${job.tier}${job.isolate ? " · isolated" : ""}`,
    `device: ${device ? `${device.name} (${device.kind})` : "unknown"}`,
    `error (${job.error_kind}): ${job.error}`,
    log && `\n${log.trim()}`,
  ];
  await navigator.clipboard.writeText(lines.filter(Boolean).join("\n"));
  $("progress-copy").textContent = "Copied";
  setTimeout(() => ($("progress-copy").textContent = "Copy details"), 1600);
}
$("progress-copy").addEventListener("click", () => copyDetails().catch(failed));

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
  $("ab").setAttribute("aria-pressed", "false");
  renderLoop();
  renderTransport();
}

async function openSession(job) {
  closeSession();
  const stems = Object.keys(job.outputs);
  const session = { id: job.id, job, lanes: [], ready: false };
  state.session = session;
  $("session-name").textContent = job.name;
  const meta = $("session-meta");
  meta.replaceChildren(`${taskLine(job)} · ${formatTime(job.duration)}`);
  for (const note of job.notes ?? []) meta.append(` · ${note}`);
  if (job.trim_db) {
    // units keep their case even where the style lowercases labels
    const trim = document.createElement("span");
    trim.className = "proper";
    trim.textContent = ` · trimmed ${Math.abs(job.trim_db).toFixed(1)} dB to stay under 0 dBFS`;
    meta.append(trim);
  }
  $("clock-total").textContent = `/ ${formatTime(job.duration)}`;
  $("export").classList.toggle("hidden", !native());
  // uploads and stem copies are removed once their job is done, so only path jobs can run again
  $("run-again").classList.toggle("hidden", job.owns_source);
  $("ab").classList.toggle("hidden", !job.original);
  $("mix-note").classList.add("hidden");
  const tracks = stems.map((stem) => ({ stem, url: `/api/jobs/${job.id}/stems/${stem}` }));
  if (job.original) tracks.unshift({ stem: ORIGINAL, url: `/api/jobs/${job.id}/original` });
  const template = $("lane-template");
  for (const { stem } of tracks) {
    const node = template.content.firstElementChild.cloneNode(true);
    const index = stems.indexOf(stem);
    node.style.setProperty("--stem", stemVar(stem));
    node.classList.toggle("reference", stem === ORIGINAL);
    node.querySelector(".lane-name").textContent = stem;
    node.querySelector(".lane-key").textContent = index >= 0 && index < 9 ? String(index + 1) : "";
    const save = node.querySelector(".lane-save");
    const process = node.querySelector(".lane-process");
    if (stem === ORIGINAL) {
      save.remove();
      process.remove();
    } else {
      save.href = `/api/jobs/${job.id}/stems/${stem}?download=true`;
      save.download = "";
      process.title = `Stage the ${stem} stem as a new file to separate or clean up`;
      process.addEventListener("click", () => stageStem(job, stem));
    }
    const lane = {
      stem,
      node,
      dim: node.querySelector(".wave-dim"),
      lit: node.querySelector(".wave-lit"),
      peaks: null,
      ladder: node.querySelector(".ladder"),
      level: node.querySelector(".ladder span"),
    };
    lane.draw = () => {
      drawWave(lane.dim, lane.peaks, colorOf(stem), 0.32);
      drawWave(lane.lit, lane.peaks, colorOf(stem), 1);
      lane.level.style.setProperty("--ladder-h", `${lane.ladder.clientHeight}px`);
    };
    lane.observer = new ResizeObserver(() => {
      lane.draw();
      renderRuler();
    });
    lane.observer.observe(lane.dim);
    wireLane(lane);
    $("lanes").append(node);
    session.lanes.push(lane);
    api.get(`/api/jobs/${job.id}/peaks/${stem}`).then((peaks) => {
      lane.peaks = peaks;
      lane.draw();
    });
  }
  renderRuler();
  renderTransport();
  // channels exist as soon as load starts, so mixer state can be set while the audio decodes
  const loading = mixer.load(tracks, job.duration);
  mixer.referenceStem = job.original ? ORIGINAL : null;
  // the original starts muted; A/B or unmuting brings it in
  if (job.original) session.lanes[0].mute();
  if (state.linkLoop) {
    mixer.setRegion(...state.linkLoop);
    state.linkLoop = null;
  }
  renderLoop();
  const loaded = await loading;
  if (state.session !== session || !loaded) return;
  session.ready = true;
  if (mixer.mode === "media") {
    $("mix-note").textContent = "This session is long, so preview streams from disk. Playback may drift by a few milliseconds between stems; the files themselves are exact.";
    $("mix-note").classList.remove("hidden");
  }
  renderTransport();
}

function renderRuler() {
  const ticks = $("ruler-ticks");
  const duration = state.session?.job.duration || 0;
  ticks.querySelectorAll(".tick").forEach((n) => n.remove());
  for (const { time, major } of rulerTicks(duration, ticks.clientWidth)) {
    const tick = document.createElement("span");
    tick.className = major ? "tick" : "tick minor";
    tick.style.left = `${(time / duration) * 100}%`;
    if (major) tick.textContent = formatTime(time);
    ticks.append(tick);
  }
  renderLoop();
}

// drag across the ruler to set a loop, click to seek, shift-click to clear the loop
let draftRegion = null;

function wireRuler() {
  const ticks = $("ruler-ticks");
  const timeAt = (event) => {
    const box = ticks.getBoundingClientRect();
    return Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)) * mixer.duration;
  };
  ticks.addEventListener("pointerdown", (event) => {
    if (!state.session?.ready || event.button !== 0) return;
    if (event.shiftKey) {
      mixer.setRegion(0, 0);
      renderLoop();
      return;
    }
    ticks.setPointerCapture(event.pointerId);
    const anchor = timeAt(event);
    const startX = event.clientX;
    let dragging = false;
    const move = (step) => {
      dragging ||= Math.abs(step.clientX - startX) > 4;
      if (!dragging) return;
      draftRegion = { start: Math.min(anchor, timeAt(step)), end: Math.max(anchor, timeAt(step)) };
      renderLoop();
    };
    ticks.addEventListener("pointermove", move);
    ticks.addEventListener("pointerup", (up) => {
      ticks.removeEventListener("pointermove", move);
      draftRegion = null;
      if (dragging) mixer.setRegion(anchor, timeAt(up));
      else mixer.seek(anchor);
      renderLoop();
    }, { once: true });
  });
}

function renderLoop() {
  const region = draftRegion ?? mixer.region;
  const duration = mixer.duration || state.session?.job.duration || 0;
  const band = $("loop-band");
  const zone = $("loop-zone");
  const visible = Boolean(region && duration);
  band.classList.toggle("hidden", !visible);
  zone.classList.toggle("hidden", !visible);
  band.classList.toggle("off", !draftRegion && !mixer.looping);
  zone.classList.toggle("off", !draftRegion && !mixer.looping);
  if (visible) {
    const left = `${(region.start / duration) * 100}%`;
    const width = `${((region.end - region.start) / duration) * 100}%`;
    Object.assign(band.style, { left, width });
    const wave = state.session?.lanes[0]?.node.querySelector(".lane-wave");
    if (wave) {
      Object.assign(zone.style, {
        left: `${wave.offsetLeft + (region.start / duration) * wave.clientWidth}px`,
        width: `${((region.end - region.start) / duration) * wave.clientWidth}px`,
        height: `${$("lanes").scrollHeight}px`,
      });
    }
  }
  const loop = $("loop");
  loop.disabled = !mixer.region;
  loop.setAttribute("aria-pressed", String(mixer.looping));
  loop.title = region ? `Loop ${formatTime(region.start, true)} to ${formatTime(region.end, true)} (L)` : "Drag across the time ruler to set a loop";
}

function toggleLoop() {
  if (!mixer.region) return;
  mixer.setLooping(!mixer.looping);
  renderLoop();
}

function toggleReference() {
  if (!state.session?.ready || !mixer.referenceStem) return;
  mixer.setReference(!mixer.reference);
  $("ab").setAttribute("aria-pressed", String(mixer.reference));
  refreshAudible();
}

function wireLane(lane) {
  const { node, stem } = lane;
  const solo = node.querySelector(".solo");
  const mute = node.querySelector(".mute");
  const gain = node.querySelector(".gain");
  const readout = node.querySelector(".gain-db");
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
    const played = mixer.duration ? Math.min(100, (position / mixer.duration) * 100) : 0;
    for (const lane of session.lanes) {
      lane.level.style.height = `${Math.round(mixer.level(lane.stem) * 100)}%`;
      lane.lit.style.clipPath = `inset(0 ${100 - played}% 0 0)`;
    }
    if (!mixer.playing && $("play").classList.contains("playing")) renderTransport();
  }
  requestAnimationFrame(frame);
}

$("ab").addEventListener("click", toggleReference);
$("loop").addEventListener("click", toggleLoop);
wireRuler();
$("run-again").addEventListener("click", () => {
  if (state.session) stageScanned([state.session.job.source]);
});
$("zip").addEventListener("click", () => {
  if (state.session) window.location.href = `/api/jobs/${state.session.id}/zip`;
});
$("reveal").addEventListener("click", () => {
  if (state.session) api.post(`/api/jobs/${state.session.id}/reveal`).catch(failed);
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
    meta.append(`${model.license} · ${megabytes(model.size)}${scores ? ` · SDR ${scores}` : ""} · `, link);
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
  const { count, size } = state.catalog.unused;
  if (count) list.append(leftovers(count, size));
}

// checkpoints from older builds or swapped-out models that nothing in the catalog loads anymore
function leftovers(count, size) {
  const item = document.createElement("li");
  item.className = "model leftover";
  const title = document.createElement("div");
  title.className = "model-title";
  title.textContent = "Leftover files";
  const side = document.createElement("div");
  side.className = "model-side";
  side.append(actionButton("Remove", async () => {
    if (!confirm(`Delete ${count} unused ${count === 1 ? "file" : "files"} and free ${megabytes(size)}?`)) return;
    await api.remove("/api/models/unused");
    await refreshCatalog();
  }));
  const meta = document.createElement("div");
  meta.className = "model-meta";
  meta.textContent = `${count} ${count === 1 ? "file" : "files"} no model here uses, ${megabytes(size)}, mostly checkpoints from older versions of Split`;
  item.append(title, side, meta);
  return item;
}

function actionButton(label, run) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "quiet";
  button.textContent = label;
  button.addEventListener("click", () => run().catch(failed));
  return button;
}

function openModels() {
  renderModels();
  $("models-sheet").showModal();
}
$("open-models").addEventListener("click", openModels);
$("seg-models").addEventListener("click", openModels);

/* look: light or dark */

const THEMES = [{ id: "system", label: "System" }, { id: "dark", label: "Dark" }, { id: "light", label: "Light" }];
const look = { theme: localStorage.getItem("split.theme") || "system" };

function applyLook() {
  const dark = look.theme === "dark" || (look.theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  for (const lane of state.session?.lanes ?? []) lane.draw();
  radio($("theme-pick"), THEMES, look.theme, (id) => {
    look.theme = id;
    localStorage.setItem("split.theme", id);
    applyLook();
  });
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyLook);
$("open-look").addEventListener("click", () => $("look-sheet").showModal());

/* help */

const KEYS = [
  ["Ctrl O", "Add files"],
  ["Enter", "Separate the files waiting"],
  ["V I K B S D R N C", "Switch task"],
  ["Space", "Play or pause"],
  ["Left Right", "Seek 5 seconds, Shift for 1"],
  ["Home", "Back to the start"],
  ["1 to 9", "Solo a lane, Shift to mute"],
  ["O", "Hear the original mix instead of the stems"],
  ["L", "Loop on or off; drag across the time ruler to set one, Shift-click it to clear"],
  ["Esc", "Clear solos"],
  ["F1", "This list"],
];

function openHelp() {
  const list = $("keys");
  list.replaceChildren();
  for (const [keys, action] of KEYS) {
    const term = document.createElement("dt");
    for (const key of keys.split(" ")) {
      const cap = document.createElement("kbd");
      cap.textContent = key;
      term.append(cap, " ");
    }
    const description = document.createElement("dd");
    description.textContent = action;
    list.append(term, description);
  }
  $("help-sheet").showModal();
}
$("open-help").addEventListener("click", openHelp);
for (const button of document.querySelectorAll("[data-close]")) {
  button.addEventListener("click", () => button.closest("dialog").close());
}

/* window chrome: on windows the page draws the title bar; css marks it as the caption */

let customChrome = false;
let nativeTitle = false;
window.splitChrome = (maximized) => document.documentElement.classList.toggle("maximized", maximized);

whenNative(async (bridge) => {
  const chrome = await bridge.chrome();
  if (!chrome.custom) return;
  customChrome = true;
  nativeTitle = chrome.titleBar;
  document.documentElement.classList.toggle("native-title", nativeTitle);
  $("window-controls").classList.remove("hidden");
  $("edges").classList.remove("hidden");
  window.splitChrome(chrome.maximized);
});

$("titlebar").addEventListener("mousedown", (event) => {
  // older webview runtimes cannot hand the caption to windows, so python follows the cursor instead
  if (!customChrome || nativeTitle || event.button !== 0 || event.target.closest("button")) return;
  native().window_move();
});
$("titlebar").addEventListener("dblclick", (event) => {
  if (customChrome && !nativeTitle && !event.target.closest("button")) native().window_toggle();
});
$("edges").addEventListener("mousedown", (event) => {
  if (event.button === 0 && event.target.dataset.edge) native().window_resize(event.target.dataset.edge);
});
$("win-min").addEventListener("click", () => native().window_minimize());
$("win-max").addEventListener("click", () => native().window_toggle());
$("win-close").addEventListener("click", () => native().window_close());

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
  const folders = [...(event.dataTransfer?.items ?? [])].some((item) => item.webkitGetAsEntry?.()?.isDirectory);
  if (native() && folders) {
    // the webview does not always hand over a dropped folder's path; say so instead of doing nothing
    const seq = state.snapshot.opened.seq;
    setTimeout(() => {
      if (state.snapshot.opened.seq === seq) notice("This window could not read the dropped folder. Use “a whole folder” under the drop area instead.");
    }, 1500);
  }
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
$("add-files").addEventListener("click", (event) => {
  event.stopPropagation();
  addFiles();
});
$("add-files-top").addEventListener("click", addFiles);
$("add-folder").addEventListener("click", async (event) => {
  event.stopPropagation();
  const folder = await native()?.pick_folder();
  if (folder) stageScanned([folder]);
});
whenNative(() => $("folder-choice").classList.remove("hidden"));
$("dropzone").addEventListener("click", addFiles);
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
  if (typing || document.querySelector("dialog[open]")) return;
  if (event.key === "F1") {
    event.preventDefault();
    openHelp();
    return;
  }
  const letter = !event.ctrlKey && !event.metaKey && !event.altKey && event.key.length === 1 ? event.key.toLowerCase() : "";
  const keyed = Object.entries(TASK_KEYS).find(([, key]) => key === letter);
  if (keyed && !state.session) {
    pickTask(keyed[0]);
    return;
  }
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
    const lane = state.session.lanes.filter((l) => l.stem !== ORIGINAL)[Number(event.code.slice(5)) - 1];
    if (lane) event.shiftKey ? lane.mute() : lane.solo();
  } else if (letter === "o") {
    toggleReference();
  } else if (letter === "l") {
    toggleLoop();
  } else if (event.key === "Escape") {
    for (const lane of state.session.lanes) {
      const solo = lane.node.querySelector(".solo");
      if (solo.getAttribute("aria-pressed") === "true") lane.solo();
    }
  }
});

/* updates: the rot installer owns installs; split only asks it and hands over */

function renderUpdate(update) {
  const seg = $("seg-update");
  const available = Boolean(update?.available);
  seg.classList.toggle("hidden", !available);
  $("seg-update-sep").classList.toggle("hidden", !available);
  if (!available) return;
  $("update-version").textContent = update.version;
  $("update-title").textContent = `Split ${update.version}`;
  $("update-notes").textContent = update.notes || "No release notes were published with this version.";
}

$("seg-update").addEventListener("click", () => {
  $("update-error").classList.add("hidden");
  $("update-sheet").showModal();
});
$("update-install").addEventListener("click", async () => {
  const button = $("update-install");
  button.disabled = true;
  try {
    await api.post("/api/update");
    button.textContent = "Closing for the update";
  } catch (error) {
    $("update-error").textContent = error.message;
    $("update-error").classList.remove("hidden");
    button.disabled = false;
  }
});

$("clear-finished").addEventListener("click", () => api.remove("/api/jobs").catch(failed));

/* boot */

async function refreshCatalog() {
  state.catalog = await api.get("/api/catalog");
  renderRail();
  renderStatus(state.snapshot);
  if ($("models-sheet").open) renderModels();
}

function renderDevice(snapshot) {
  const device = $("device");
  if (snapshot.fatal) {
    device.textContent = "engine failed";
    device.title = snapshot.fatal.message;
    device.classList.add("warn");
    $("device-led").className = "led off";
    return;
  }
  const info = snapshot.device;
  if (!info) return;
  device.classList.toggle("warn", info.kind === "cpu");
  $("device-led").className = `led ${info.kind === "cpu" ? "busy" : "on"}`;
  device.textContent = info.kind === "cpu" ? "cpu only" : info.name.replace(/^NVIDIA (GeForce )?/, "");
  device.title = info.note || (info.kind === "cpu" ? "No supported GPU found. Expect several minutes per song." : `Running on ${info.name}`);
}

function renderStatus(snapshot) {
  const running = snapshot.jobs.filter((j) => j.status === "running").length;
  const waiting = snapshot.jobs.filter((j) => j.status === "queued").length;
  $("queue-led").className = `led ${running ? "busy" : ""}`;
  $("queue-state").textContent = running || waiting ? `${running} running${waiting ? `, ${waiting} waiting` : ""}` : "idle";
  if (state.catalog) {
    const models = Object.values(state.catalog.models);
    $("models-ready").textContent = `${models.filter((m) => m.present).length} of ${models.length} ready`;
  }
}

function onSnapshot(snapshot) {
  const before = state.snapshot.downloads;
  state.snapshot = snapshot;
  renderDevice(snapshot);
  renderStatus(snapshot);
  if (state.openedSeq === null) state.openedSeq = snapshot.opened.seq;
  else if (snapshot.opened.seq !== state.openedSeq) {
    state.openedSeq = snapshot.opened.seq;
    if (snapshot.opened.paths.length) stagePaths(snapshot.opened.paths);
    if (snapshot.opened.error) {
      state.selected = null;
      notice(snapshot.opened.error);
    }
  }
  renderUpdate(snapshot.update);
  const finished = Object.entries(snapshot.downloads).some(([id, d]) => d.status === "done" && before[id]?.status !== "done");
  const jobDone = snapshot.jobs.some((j) => j.status === "done" && j.finished && Date.now() / 1000 - j.finished < 3);
  if (finished || jobDone) refreshCatalog();
  if ($("models-sheet").open) renderModels();
  if (state.selected && !jobById(state.selected)) state.selected = null;
  renderStage();
}

// #job=<id>&task=<id>&theme=<id>&loop=<from>-<to> opens a view directly; the theme applies to this load only.
// #still renders one snapshot without the live stream, for headless captures that wait on network idle
function readLink() {
  const link = new URLSearchParams(location.hash.slice(1));
  if (link.has("theme")) look.theme = link.get("theme");
  if (link.has("task")) state.task = link.get("task");
  if (link.has("job")) state.selected = link.get("job");
  // loop=12.5-20 opens the session with that stretch looping
  const loop = link.get("loop")?.split("-").map(Number);
  if (loop?.length === 2 && loop.every(Number.isFinite)) state.linkLoop = loop;
}

async function boot() {
  readLink();
  applyLook();
  const [system] = await Promise.all([api.get("/api/system"), refreshCatalog()]);
  $("version").textContent = `v${system.version}`;
  $("data-dir").textContent = system.data_dir;
  renderStage();
  if (new URLSearchParams(location.hash.slice(1)).has("still")) onSnapshot(await api.get("/api/state"));
  else subscribe(onSnapshot);
  whenNative(() => $("export").classList.toggle("hidden", !state.session));
  requestAnimationFrame(frame);
}

boot();
