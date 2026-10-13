"""Separation pipeline. Everything here runs inside the worker process started by jobs.py."""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import sys
import time
import traceback
import types
import urllib.error
from collections.abc import Callable
from pathlib import Path

from . import media, paths, weights
from .catalog import MODELS, Model, Step, plan

Emit = Callable[..., None]

_OUTPUT_LABEL = re.compile(r"_\(([^)]+)\)")


class _Bar:
    """Stands in for tqdm inside audio-separator so chunk progress reaches the UI."""

    sink: Callable[[float], None] | None = None

    def __init__(self, iterable=None, total=None, *args, **kwargs):
        self.iterable = iterable
        if total is None and iterable is not None and hasattr(iterable, "__len__"):
            total = len(iterable)
        self.total = total
        self.n = 0

    def __iter__(self):
        for item in self.iterable:
            yield item
            self.update()

    def update(self, n=1):
        self.n += n
        if _Bar.sink and self.total:
            _Bar.sink(min(1.0, self.n / self.total))

    def close(self):
        pass

    def set_description(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _silence_progress_bars() -> None:
    from audio_separator.separator import separator
    from audio_separator.separator.architectures import mdxc_separator
    from audio_separator.separator.uvr_lib_v5.demucs import apply, utils

    for module in (separator, mdxc_separator):
        module.tqdm = _Bar
    for module in (apply, utils):
        module.tqdm = types.SimpleNamespace(tqdm=_Bar)


def _rotate_fast(rotary_embed, tensor):
    """Rotary embedding in the tensor's own dtype with cached angles.

    audio-separator's version upcasts every query and key to float32, rebuilds cos/sin, and
    concatenates on each call, which costs more than the attention it feeds on a 20 s chunk.
    """
    import torch

    seq_dim = rotary_embed.default_seq_dim
    key = (tensor.shape[seq_dim], tensor.dtype, tensor.device, seq_dim)
    cache = rotary_embed.__dict__.setdefault("_split_angles", {})
    if key not in cache:
        positions = rotary_embed.get_seq_pos(key[0], device=tensor.device, dtype=torch.float32)
        angles = torch.outer(positions, rotary_embed.freqs.detach().to(tensor.device, torch.float32))
        if seq_dim == -3:
            angles = angles[:, None, :]
        cache[key] = (angles.cos().to(tensor.dtype), angles.sin().to(tensor.dtype))
    cos, sin = cache[key]
    even, odd = tensor.unflatten(-1, (-1, 2)).unbind(-1)
    return torch.stack((even * cos - odd * sin, odd * cos + even * sin), dim=-1).flatten(-2)


def _speed_up_roformers() -> None:
    import torch
    from audio_separator.separator.uvr_lib_v5.roformer import attend, bs_roformer, mel_band_roformer

    plain = bs_roformer._rotate_queries_or_keys

    def rotate(rotary_embed, tensor):
        full_width = rotary_embed.freqs.shape[-1] * 2 == tensor.shape[-1]
        if tensor.device.type != "cuda" or not full_width or rotary_embed.learned_freq:
            return plain(rotary_embed, tensor)
        return _rotate_fast(rotary_embed, tensor)

    bs_roformer._rotate_queries_or_keys = rotate
    mel_band_roformer._rotate_queries_or_keys = rotate

    # upstream only allows the flash kernel on an a100; every sm80+ card supports it in fp16
    setup = attend.Attend.__init__

    def init(self, *args, **kwargs):
        setup(self, *args, **kwargs)
        if self.flash and torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8:
            self.cuda_config = attend.FlashAttentionConfig(True, True, True)

    attend.Attend.__init__ = init


def _separator_class():
    from audio_separator.separator import Separator

    class CatalogSeparator(Separator):
        force_cpu = False

        def setup_torch_device(self, system_info):
            if not self.force_cpu:
                return super().setup_torch_device(system_info)
            import torch

            self.torch_device_cpu = self.torch_device = torch.device("cpu")
            self.onnx_execution_provider = ["CPUExecutionProvider"]

        # answer from split's pinned catalog so loading never consults the network
        def list_supported_model_files(self):
            grouped = {"MDXC": {}, "Demucs": {}}
            for model in MODELS.values():
                group = "Demucs" if model.arch == "demucs" else "MDXC"
                grouped[group][model.id] = {
                    "filename": model.load_name,
                    "scores": {},
                    "stems": [],
                    "target_stem": None,
                    "download_files": [f.name for f in model.files],
                }
            return grouped

    return CatalogSeparator


def _has_kernels(major: int, minor: int, arch_list: list[str]) -> bool:
    # cubins run on any card with the same major version and an equal or newer minor
    built = [(int(a[3:-1]), int(a[-1])) for a in arch_list if a.startswith("sm_")]
    return any(m == major and n <= minor for m, n in built)


def describe_device() -> dict:
    """Pick the inference device. Must run before anything initializes CUDA."""
    if os.environ.get("SPLIT_DEVICE") == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    import torch

    cpu = {"kind": "cpu", "name": "CPU", "memory": 0, "note": ""}
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        if not _has_kernels(props.major, props.minor, torch.cuda.get_arch_list()):
            # this torch build carries no kernels for the card; run on the cpu instead of crashing
            return {**cpu, "note": f"{props.name} is too old for this build, using the CPU"}
        return {"kind": "cuda", "name": props.name, "memory": props.total_memory, "note": ""}
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return {"kind": "mps", "name": "Apple GPU", "memory": 0, "note": ""}
    return cpu


class Runner:
    def __init__(self) -> None:
        self.device = describe_device()
        _silence_progress_bars()
        _speed_up_roformers()
        self.separator = None

    def _load(self, model: Model, output_dir: Path):
        if self.separator is None:
            separator_class = _separator_class()
            separator_class.force_cpu = self.device["kind"] == "cpu"
            self.separator = separator_class(
                log_level=logging.ERROR,
                model_file_dir=str(paths.models_dir()),
                output_dir=str(output_dir),
                output_format="WAV",
                normalization_threshold=1.0,
                use_soundfile=True,
                sample_rate=media.WORK_RATE,
                use_autocast=self.device["kind"] == "cuda",
                mdxc_params={
                    "segment_size": 256,
                    "override_model_segment_size": False,
                    "batch_size": None,
                    "overlap": None,
                    "pitch_shift": 0,
                },
                demucs_params={
                    "segment_size": "Default",
                    "shifts": 1,
                    "overlap": 0.25,
                    "segments_enabled": True,
                },
            )
        separator = self.separator
        separator.load_model(model.load_name)
        separator.output_dir = str(output_dir)
        instance = separator.model_instance
        instance.output_dir = str(output_dir)
        # audio-separator peak-normalizes the mix and every stem on its own, which breaks
        # the stems-sum-to-mix property; float intermediates have the headroom to skip it
        instance.normalization_threshold = math.inf
        return separator

    def _run_model(
        self, model: Model, source: Path, out: Path, report: Callable[[float], None]
    ) -> dict[str, Path]:
        out.mkdir(parents=True, exist_ok=True)
        separator = self._load(model, out)
        _Bar.sink = report
        try:
            produced = separator.separate(str(source))
        finally:
            _Bar.sink = None
        stems: dict[str, Path] = {}
        for name in produced:
            path = Path(name) if Path(name).is_absolute() else out / Path(name).name
            # audio-separator appends _(stem)_model to the input name, which may carry its own label
            labels = _OUTPUT_LABEL.findall(path.name)
            raw = labels[-1].lower() if labels else ""
            if raw not in model.stems:
                raise RuntimeError(f"{model.label} produced an unexpected stem '{raw}'")
            stems[model.stems[raw]] = path
        return stems

    def separate(self, request: dict, emit: Emit) -> dict:
        job_dir = Path(request["job_dir"])
        work = job_dir / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        recipe = plan(request["task"], request["tier"], request.get("isolate", False))
        wanted = request["stems"]
        fmt = request["format"]

        runs = sum(len(step.models) for step in recipe)
        units = 1 + runs + 0.5 + 0.25 * len(wanted)
        done = 0.0

        def progress(phase: str, detail: str, local: float = 0.0, phase_fraction: float | None = None):
            emit(
                phase=phase,
                detail=detail,
                fraction=min(0.999, (done + local) / units),
                phase_fraction=phase_fraction,
            )

        progress("decode", "Reading audio")
        mix = work / "mix.wav"
        source = media.decode(Path(request["source"]), mix)
        done += 1
        emit(duration=source.duration, device=self.device["kind"])

        available: dict[str, Path] = {"mix": mix}
        finals: dict[str, list[Path]] = {}
        run_index = 0
        for step_index, step in enumerate(recipe):
            results = []
            for model_id in step.models:
                model = MODELS[model_id]
                run_index += 1
                self._ensure_weights(
                    model,
                    lambda d, n, m=model: progress("download", f"Downloading {m.label}", 0.0, n and d / n),
                )
                position = f" ({run_index}/{runs})" if runs > 1 else ""
                label = f"Separating with {model.label}{position}"
                progress("separate", label, 0.0, 0.0)
                out = work / f"step{step_index}" / model.id
                results.append(
                    self._run_model(
                        model,
                        available[step.input],
                        out,
                        lambda f, lab=label: progress("separate", lab, f, f),
                    )
                )
                done += 1
            merged = self._combine(step, results, work / f"step{step_index}" / "combined")
            available.update(merged)
            for stem, final in step.outputs.items():
                finals.setdefault(final, []).append(merged[stem])

        progress("encode", "Finishing stems")
        outputs: dict[str, str] = {}
        peaks_dir = job_dir / "peaks"
        peaks_dir.mkdir(exist_ok=True)
        for stem in wanted:
            parts = finals[stem]
            wav = parts[0]
            if len(parts) > 1:
                wav = work / f"{stem}.wav"
                media.mix(parts, wav)
            name = f"{stem}.{fmt}"
            media.encode(wav, job_dir / name, fmt, source)
            media.write_peaks(wav, peaks_dir / f"{stem}.json")
            outputs[stem] = name
            done += 0.25
            progress("encode", f"Wrote {stem}")
        shutil.rmtree(work, ignore_errors=True)
        return {"outputs": outputs, "duration": source.duration}

    def _combine(self, step: Step, results: list[dict[str, Path]], out: Path) -> dict[str, Path]:
        if len(results) == 1:
            return results[0]
        import numpy as np
        import soundfile as sf
        from audio_separator.separator.ensembler import Ensembler

        out.mkdir(parents=True, exist_ok=True)
        ensembler = Ensembler(logging.getLogger("split.ensemble"), algorithm=step.algorithm)
        merged = {}
        for stem in results[0]:
            waves = []
            for result in results:
                data, rate = sf.read(result[stem], dtype="float32", always_2d=True)
                waves.append(np.ascontiguousarray(data.T))
            combined = ensembler.ensemble(waves)
            path = out / f"{stem}.wav"
            sf.write(path, combined.T, rate, subtype="FLOAT")
            merged[stem] = path
        return merged

    def _ensure_weights(self, model: Model, report: Callable[[int, int], None]) -> None:
        if weights.missing_files(model):
            weights.fetch(model, report)

    def download(self, model_id: str, emit: Emit) -> None:
        model = MODELS[model_id]
        weights.fetch(
            model,
            lambda d, n: emit(
                phase="download",
                detail=f"Downloading {model.label}",
                fraction=n and d / n,
                phase_fraction=n and d / n,
            ),
        )


def classify_error(exc: BaseException) -> tuple[str, str]:
    name = type(exc).__name__
    if "OutOfMemory" in name or "out of memory" in str(exc).lower():
        return "oom", "The GPU ran out of memory. Close other GPU-heavy apps or pick a lighter quality tier."
    if isinstance(exc, media.MediaError):
        return "input", str(exc)
    if isinstance(exc, urllib.error.URLError | TimeoutError | ConnectionError):
        return "network", "Could not download the model. Check your connection and try again."
    if isinstance(exc, OSError) and "integrity" in str(exc):
        return "network", str(exc)
    if isinstance(exc, FileNotFoundError) and "ffmpeg" in str(exc):
        return "setup", str(exc)
    return "internal", f"{name}: {exc}"


def _emitter(outbox, key: str) -> Emit:
    last = 0.0

    def emit(**event) -> None:
        nonlocal last
        now = time.monotonic()
        # phase boundaries always go through; chunk ticks are capped at ten a second
        if event.get("phase") is None or event.get("phase_fraction") in (0.0, 1.0) or now - last > 0.1:
            last = now
            outbox.put({"type": "progress", "key": key, **event})

    return emit


def worker_main(inbox, outbox) -> None:
    """Serve separation and download requests one at a time until told to stop."""
    paths.log_to_file_if_headless("worker")
    paths.expose_ffmpeg()
    logging.basicConfig(level=logging.WARNING)
    try:
        runner = Runner()
    except BaseException as exc:
        kind, message = classify_error(exc)
        outbox.put({"type": "fatal", "kind": kind, "message": message})
        return
    outbox.put({"type": "ready", "device": runner.device})
    while (request := inbox.get()) is not None:
        key = request["key"]
        emit = _emitter(outbox, key)
        try:
            if request["kind"] == "separate":
                result = runner.separate(request, emit)
            else:
                runner.download(request["model"], emit)
                result = {}
            outbox.put({"type": "done", "key": key, **result})
        except BaseException as exc:
            kind, message = classify_error(exc)
            outbox.put(
                {
                    "type": "error",
                    "key": key,
                    "kind": kind,
                    "message": message,
                    "trace": "".join(traceback.format_exception(exc))[-4000:],
                }
            )
            if isinstance(exc, KeyboardInterrupt):
                break
    sys.exit(0)
