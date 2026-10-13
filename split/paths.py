"""Where Split reads bundled files and keeps models, jobs and logs."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return PACKAGE_DIR.parent


def web_dir() -> Path:
    for candidate in (bundle_dir() / "web", PACKAGE_DIR / "web"):
        if (candidate / "index.html").is_file():
            return candidate
    raise FileNotFoundError("web ui files are missing from this installation")


def data_root() -> Path:
    if override := os.environ.get("SPLIT_HOME"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Split"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Split"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "split"


def models_dir() -> Path:
    return _ensure(data_root() / "models")


def jobs_dir() -> Path:
    return _ensure(data_root() / "jobs")


def logs_dir() -> Path:
    return _ensure(data_root() / "logs")


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_to_file_if_headless(name: str) -> None:
    """Windowed builds start without stdout/stderr; give library logging somewhere to go."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log = logs_dir() / f"{name}.log"
    if log.exists() and log.stat().st_size > 5_000_000:
        log.unlink()
    stream = open(log, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def legacy_model_dirs() -> list[Path]:
    # older builds kept weights next to the exe or in the source checkout
    roots = [Path(sys.executable).resolve().parent] if frozen() else [PACKAGE_DIR.parent]
    return [root / "models_cache" for root in roots if (root / "models_cache").is_dir()]


def migrate_legacy_models(keep: set[str], target: Path | None = None) -> int:
    """Adopt weights an older build already downloaded, then drop that old cache."""
    target = target or models_dir()
    moved = 0
    for legacy in legacy_model_dirs():
        for entry in legacy.iterdir():
            if entry.name in keep and entry.is_file() and not (target / entry.name).exists():
                shutil.move(entry, target / entry.name)
                moved += 1
        shutil.rmtree(legacy, ignore_errors=True)
    return moved


def ffmpeg_bin() -> str:
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    for candidate in (bundle_dir() / name, bundle_dir() / "tools" / name):
        if candidate.is_file():
            return str(candidate)
    if found := shutil.which("ffmpeg"):
        return found
    raise FileNotFoundError("ffmpeg was not found. Install it and make sure it is on PATH.")


def expose_ffmpeg() -> None:
    # audio-separator and pydub shell out to whatever ffmpeg PATH resolves first
    try:
        folder = str(Path(ffmpeg_bin()).parent)
    except FileNotFoundError:
        return
    if folder not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
