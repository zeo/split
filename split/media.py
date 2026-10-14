"""Decoding, encoding, mixdown and waveform peaks around ffmpeg and soundfile."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .paths import ffmpeg_bin

WORK_RATE = 44100
FORMATS = ("wav", "flac", "mp3")
MEDIA_TYPES = {"wav": "audio/wav", "flac": "audio/flac", "mp3": "audio/mpeg"}
EXTENSIONS = tuple("mp3 wav flac ogg opus m4a aac aif aiff wma mp4 mkv mov webm".split())
MAX_FILES = 500
PEAK_BUCKETS = 2400
# -0.1 dBFS, leaving room for overshoot when resampling back to the source rate
CEILING = 0.989

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass(frozen=True)
class Source:
    sample_rate: int
    channels: int
    duration: float


class MediaError(RuntimeError):
    pass


def collect(entries: Iterable[Path]) -> list[Path]:
    """Files as given, plus every audio or video file under any folder, in name order."""
    found: list[Path] = []
    for entry in entries:
        if entry.is_dir():
            inside = (p for p in entry.rglob("*") if p.suffix[1:].lower() in EXTENSIONS and p.is_file())
            found += sorted(inside, key=lambda p: str(p).lower())
        elif entry.is_file():
            found.append(entry)
        else:
            raise MediaError(f"{entry} does not exist")
        if len(found) > MAX_FILES:
            raise MediaError(f"That is more than {MAX_FILES} files, add them in smaller batches")
    return found


def _ffmpeg(*args: str | Path) -> subprocess.CompletedProcess:
    command = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", *map(str, args)]
    return subprocess.run(command, capture_output=True, text=True, creationflags=_NO_WINDOW)


def decode(source: Path, dest: Path) -> Source:
    """Decode any container to 44.1 kHz stereo float wav, the format every model expects."""
    result = _ffmpeg(
        "-i", source, "-map", "0:a:0", "-vn", "-ac", "2", "-ar", WORK_RATE, "-c:a", "pcm_f32le", dest
    )
    if result.returncode != 0 or not dest.is_file():
        reason = (result.stderr.strip().splitlines() or ["unknown error"])[-1]
        raise MediaError(f"Could not read {source.name}: {reason}")
    stream = re.search(r"Audio: [^\n]*?(\d+) Hz, ([^,\n]+)", result.stderr)
    rate = int(stream.group(1)) if stream else WORK_RATE
    layout = stream.group(2).strip() if stream else "stereo"
    # older ffmpeg builds print "1 channels" where newer ones print "mono"
    channels = 1 if layout == "mono" or layout.startswith("1 channel") else 2
    info = sf.info(dest)
    if info.frames == 0:
        raise MediaError(f"{source.name} has no audio")
    return Source(sample_rate=rate, channels=channels, duration=info.duration)


def encode(wav: Path, dest: Path, fmt: str, source: Source, gain: float = 1.0) -> None:
    """Write a stem in the requested format at the source's own rate and channel count."""
    codec = {
        "wav": ["-c:a", "pcm_s24le"],
        "flac": "-c:a flac -sample_fmt s32 -bits_per_raw_sample 24 -compression_level 8".split(),
        "mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
    }[fmt]
    shape = ["-ar", str(source.sample_rate), "-ac", str(source.channels)]
    if fmt == "mp3":
        shape = ["-ar", str(min(source.sample_rate, 48000)), "-ac", str(source.channels)]
    level = ["-af", f"volume={gain:.6f}"] if gain != 1.0 else []
    result = _ffmpeg("-i", wav, *level, *shape, *codec, dest)
    if result.returncode != 0:
        reason = (result.stderr.strip().splitlines() or ["unknown error"])[-1]
        raise MediaError(f"Could not encode {dest.name}: {reason}")


def mix(sources: list[Path], dest: Path) -> None:
    """Sum stems sample-by-sample; used when several model outputs fold into one stem."""
    total = None
    for path in sources:
        data, rate = sf.read(path, dtype="float32", always_2d=True)
        if total is None:
            total = data
        else:
            length = max(len(total), len(data))
            total = np.pad(total, ((0, length - len(total)), (0, 0))) + np.pad(
                data, ((0, length - len(data)), (0, 0))
            )
    sf.write(dest, total, rate, subtype="FLOAT")


def peak(wav: Path) -> float:
    return max(
        (
            float(np.abs(block).max(initial=0.0))
            for block in sf.blocks(wav, blocksize=1 << 18, dtype="float32")
        ),
        default=0.0,
    )


def shared_gain(wavs: list[Path]) -> float:
    """One gain for every stem, so none clips in a fixed-point format and the stems still sum to the mix."""
    loudest = max((peak(w) for w in wavs), default=0.0)
    return min(1.0, CEILING / loudest) if loudest else 1.0


def peaks(wav: Path, buckets: int = PEAK_BUCKETS) -> dict:
    """Per-bucket peak and rms of the channel-summed signal, for drawing waveforms without decoding."""
    info = sf.info(wav)
    per_bucket = max(1, -(-info.frames // buckets))
    peak, rms = [], []
    for block in sf.blocks(wav, blocksize=per_bucket, dtype="float32", always_2d=True):
        mono = block.mean(axis=1)
        peak.append(round(float(np.abs(mono).max(initial=0.0)), 4))
        rms.append(round(float(np.sqrt(np.mean(mono * mono))) if mono.size else 0.0, 4))
    return {"duration": info.duration, "peak": peak, "rms": rms}


def write_peaks(wav: Path, dest: Path) -> None:
    dest.write_text(json.dumps(peaks(wav)))
