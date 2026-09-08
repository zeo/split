"""Unified separation engine: RoFormer/MDX (audio-separator) + Demucs fallback.

Quality ladder (published vocal SDR):
  Viperx-1297 12.98 · Kim 12.6 · htdemucs_ft 10.8
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import ModelInfo, get_model

OUTPUT_FORMATS = ("mp3", "wav", "flac")
MODEL_DIR = Path(__file__).resolve().parent.parent / "models_cache"


def ffmpeg_bin() -> str:
    """Resolve ffmpeg: bundled exe next to the app first, then PATH."""
    import sys
    candidates = []
    try:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        candidates += [base / "ffmpeg.exe", base / "_internal" / "ffmpeg.exe", base / "bin" / "ffmpeg.exe"]
    except Exception:
        pass
    candidates.append(Path(__file__).resolve().parent.parent / "tools" / "ffmpeg.exe")
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError("ffmpeg not found. Install ffmpeg on PATH, place ffmpeg.exe in tools/, or choose wav output.")


@dataclass
class SeparationRequest:
    input_path: Path
    output_dir: Path
    model_id: str = "kim-vocals"
    # legacy Demucs path params
    model: str = ""  # demucs model name override (backend='demucs' only)
    stems: list[str] | None = None
    output_format: str = "mp3"
    mp3_bitrate: int = 320
    overlap: float = 0.25
    shifts: int = 1
    device: str = "auto"
    jobs: int = 0
    enhanced: bool = False  # higher overlap + single-stem focus for max quality


@dataclass
class SeparationResult:
    stem_files: dict[str, Path]
    model: str
    output_dir: Path
    sample_rate: int = 44100


def resolve_device(requested: str) -> str:
    if requested in ("cuda", "cpu", "mps"):
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    except ImportError:
        return "cpu"


class SeparationEngine:
    _beartype_patched = False

    def __init__(self, default_device: str = "auto"):
        self.default_device = default_device

    @classmethod
    def _patch_beartype(cls):
        """beartype 0.18 rejects `collections.abc.Callable | None` hints used by
        audio-separator's RoFormer arch on Python 3.14. Neutralize the decorator
        (type checks only — no behavior change to inference)."""
        if cls._beartype_patched:
            return
        try:
            import beartype

            def _noop(*a, **k):
                if len(a) == 1 and callable(a[0]) and not k:
                    return a[0]

                def wrap(f):
                    return f

                return wrap

            beartype.beartype = _noop
        except ImportError:
            pass
        cls._beartype_patched = True

    _packaging_patched = False

    @classmethod
    def _patch_packaging(cls):
        """Frozen exes (PyInstaller) ship no .dist-info, so
        importlib.metadata.distribution('audio-separator') raises
        PackageNotFoundError and Separator.__init__ crashes on
        `get_package_distribution(...).version`. Stub it to a fixed
        version string — logging-only, no inference impact."""
        if cls._packaging_patched:
            return
        try:
            from audio_separator.separator.separator import Separator

            _orig = Separator.get_package_distribution

            def _safe(self, package_name):
                try:
                    dist = _orig(self, package_name)
                except Exception:
                    dist = None
                if dist is None:
                    class _Frozen:
                        version = "0.47.0-frozen"

                    return _Frozen()
                return dist

            Separator.get_package_distribution = _safe
        except ImportError:
            pass
        cls._packaging_patched = True

    def separate(self, req: SeparationRequest, on_progress=None) -> SeparationResult:
        model = get_model(req.model_id or "kim-vocals")
        req.output_dir.mkdir(parents=True, exist_ok=True)
        if model.backend in ("roformer", "roformer-ensemble"):
            return self._separate_roformer(req, model, on_progress)
        return self._separate_demucs(req, model, on_progress)

    # ---------------- RoFormer / MDX via audio-separator ----------------
    def _separate_roformer(self, req: SeparationRequest, model: ModelInfo, on_progress) -> SeparationResult:
        self._patch_beartype()
        self._patch_packaging()
        from audio_separator.separator import Separator

        device = resolve_device(req.device if req.device else self.default_device)
        fmt = req.output_format.upper() if req.output_format != "mp3" else "MP3"
        is_ensemble = model.backend == "roformer-ensemble"
        overlap = req.overlap if 0 < req.overlap < 1 else 0.25
        if req.enhanced and not is_ensemble:
            overlap = max(overlap, 0.5)  # denser windows, cleaner edges
        if on_progress:
            action = f"Loading ensemble {model.label}" if is_ensemble else f"Loading {model.label}"
            on_progress(0.03, f"{action} on {device}")

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        sep = Separator(
            model_file_dir=str(MODEL_DIR),
            output_dir=str(req.output_dir),
            output_format=fmt,
            normalization_threshold=0.9,
            output_single_stem="vocals" if (req.enhanced and "vocals" in model.stems) else None,
            use_autocast=(device == "cuda"),
            mdx_params={
                "hop_length": 1024,
                "segment_size": 256,
                "overlap": overlap,
                "batch_size": 1,
                "enable_denoise": False,
            },
            mdxc_params={
                "segment_size": 256,
                "overlap": 8 if req.enhanced else 2,  # more segment passes = fewer artifacts
                "batch_size": 1,
                "pitch_shift": 0,
            },
            ensemble_preset=model.filename if is_ensemble else None,
        )
        if on_progress:
            on_progress(0.08, "Preparing models")
        if is_ensemble:
            # Bare load_model() with the default filename arg makes the
            # Separator materialize the preset's model list (see
            # Separator.load_model: preset models swap in when the default
            # filename is passed).
            sep.load_model()
        else:
            sep.load_model(model_filename=model.filename)
        if on_progress:
            on_progress(0.15, f"Separating with {model.label}")

        # deterministic stem filenames: <track>_<stem>.<ext>
        custom = {s: f"{req.input_path.stem}_{s}" for s in (req.stems or model.stems)}
        outputs: list[str] = sep.separate(str(req.input_path))
        if on_progress:
            on_progress(0.95, "Finalizing stems")

        stem_files = self._map_roformer_outputs(outputs, model, req)
        if req.output_format == "mp3":
            stem_files = self._ensure_mp3_bitrate(stem_files, req)
        if not stem_files:
            raise RuntimeError(f"{model.id} produced no stems for {req.input_path.name}")
        if on_progress:
            on_progress(1.0, "Done")
        return SeparationResult(stem_files=stem_files, model=model.id, output_dir=req.output_dir)

    def _map_roformer_outputs(self, outputs: list[str], model: ModelInfo, req: SeparationRequest) -> dict[str, Path]:
        wanted = [s.lower() for s in (req.stems or model.stems)]
        mapped: dict[str, Path] = {}
        for out in outputs:
            p = Path(out)
            if not p.is_absolute() and not p.exists():
                # audio-separator may return paths relative to CWD
                candidate = req.output_dir / p.name
                if candidate.exists():
                    p = candidate
            stem = self._classify_stem(p, model)
            if stem in wanted and stem not in mapped:
                dest = req.output_dir / f"{req.input_path.stem}_{stem}{p.suffix.lower()}"
                if p.resolve() != dest.resolve():
                    if dest.exists():
                        dest.unlink()
                    p.rename(dest)
                mapped[stem] = dest
        # remove unmapped leftovers from previous runs with same track name
        return mapped

    def _classify_stem(self, path: Path, model: ModelInfo) -> str:
        name = path.stem.lower()
        # custom names we passed: <track>_<stem>
        for stem in model.stems:
            if name.endswith("_" + stem.lower()):
                return stem
        # audio-separator default: <track>_(<stem>)_<model>.wav — the
        # parenthesized token is the true stem label
        for token in re.findall(r"\(([^)]+)\)", path.stem):
            token = token.strip().lower()
            if token in model.aliases:
                return model.aliases[token]
            for stem in model.stems:
                if token == stem.lower():
                    return stem
        # last resort: alias lookup on full name
        for token, stem in model.aliases.items():
            if token in name:
                return stem
        return name

    def _ensure_mp3_bitrate(self, stems: dict[str, Path], req: SeparationRequest) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for stem, p in stems.items():
            if p.suffix.lower() == ".mp3":
                out[stem] = p
                continue
            dest = req.output_dir / f"{req.input_path.stem}_{stem}.mp3"
            cmd = [ffmpeg_bin(), "-y", "-v", "error", "-i", str(p),
                   "-codec:a", "libmp3lame", "-b:a", f"{req.mp3_bitrate}k", str(dest)]
            subprocess.run(cmd, check=True)
            out[stem] = dest
        return out

    # ---------------- Demucs via subprocess ----------------
    def _separate_demucs(self, req: SeparationRequest, model: ModelInfo, on_progress) -> SeparationResult:
        demucs_model = req.model or model.filename
        device = resolve_device(req.device if req.device else self.default_device)
        if on_progress:
            on_progress(0.02, f"Loading model {demucs_model} on {device}")

        with tempfile.TemporaryDirectory(prefix="split_") as tmp:
            cmd = ["python", "-m", "demucs.separate", "-n", demucs_model,
                   "--out", tmp, "-d", device, "--overlap", str(req.overlap)]
            if req.shifts and req.shifts > 1:
                cmd += ["--shifts", str(req.shifts)]
            if req.jobs:
                cmd += ["-j", str(req.jobs)]
            cmd += [str(req.input_path)]

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert proc.stdout is not None
            for line in proc.stdout:
                if on_progress and "%" in line:
                    try:
                        pct = float(line.strip().split("%")[0].split()[-1]) / 100.0
                        on_progress(0.02 + pct * 0.85, f"Separating ({line.strip()[:60]})")
                    except ValueError:
                        pass
            if proc.wait() != 0:
                raise RuntimeError(f"demucs failed for {req.input_path.name}")

            produced = Path(tmp) / demucs_model / req.input_path.stem
            if not produced.exists():
                subs = [d for d in (Path(tmp) / demucs_model).iterdir() if d.is_dir()]
                if not subs:
                    raise RuntimeError("demucs produced no output directory")
                produced = subs[0]

            wanted = req.stems or model.stems
            stem_files: dict[str, Path] = {}
            for stem in wanted:
                src = produced / f"{stem}.wav"
                if not src.exists():
                    continue
                dest = req.output_dir / f"{req.input_path.stem}_{stem}.{req.output_format}"
                if on_progress:
                    on_progress(0.9, f"Encoding {stem}.{req.output_format}")
                self._convert(src, dest, req.output_format, req.mp3_bitrate)
                stem_files[stem] = dest
            if on_progress:
                on_progress(1.0, "Done")
            return SeparationResult(stem_files=stem_files, model=model.id, output_dir=req.output_dir)

    def _convert(self, src: Path, dest: Path, fmt: str, mp3_bitrate: int) -> None:
        if fmt == "wav" and src.suffix == ".wav":
            shutil.copy(src, dest)
            return
        cmd = [ffmpeg_bin(), "-y", "-v", "error", "-i", str(src)]
        if fmt == "mp3":
            cmd += ["-codec:a", "libmp3lame", "-b:a", f"{mp3_bitrate}k"]
        elif fmt == "flac":
            cmd += ["-codec:a", "flac"]
        else:
            cmd += ["-codec:a", "pcm_s16le"]
        cmd.append(str(dest))
        subprocess.run(cmd, check=True)


def separate_file(input_path: str | Path, output_dir: str | Path, **kwargs) -> SeparationResult:
    req = SeparationRequest(input_path=Path(input_path), output_dir=Path(output_dir), **kwargs)
    return SeparationEngine().separate(req)
