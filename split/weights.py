"""Model weight files on disk: resumable, hash-pinned downloads."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from . import paths
from .catalog import MODELS, Model, WeightFile, file_names

USER_AGENT = "split-stem-separator"
CHUNK = 1 << 20
ATTEMPTS = 4
# room for the ledger, configs and a little slack beyond the weights themselves
SPARE = 64 << 20

Progress = Callable[[int, int], None]

_lock = threading.Lock()


def file_path(file: WeightFile) -> Path:
    return paths.models_dir() / file.name


def missing_files(model: Model, deep: bool = True) -> list[WeightFile]:
    return [f for f in model.files if not _trusted(f, deep)]


def status() -> dict[str, dict]:
    # shallow: size match is enough here, the worker hashes before it loads anything
    report = {}
    for model in MODELS.values():
        missing = sum(f.size for f in missing_files(model, deep=False))
        report[model.id] = {"present": missing == 0, "size": model.size, "missing": missing}
    return report


def fetch(model: Model, progress: Progress | None = None) -> None:
    todo = missing_files(model)
    total = sum(f.size for f in todo)
    if todo:
        partial = sum(_partial_size(f) for f in todo)
        paths.require_space(paths.models_dir(), total - partial + SPARE, f"Downloading {model.label}")
    done = 0
    for file in todo:
        # the app prefetches in its own process while the worker may want the same file
        with _claim(file):
            if not _trusted(file):
                _download_with_retries(file, lambda n, base=done: progress and progress(base + n, total))
        done += file.size
        if progress:
            progress(done, total)


@contextmanager
def _claim(file: WeightFile) -> Iterator[None]:
    """Hold a lock on one weight file across processes; the os drops it if the holder dies."""
    lock = file_path(file).with_name(file.name + ".lock")
    with lock.open("a+b") as handle:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            while True:
                try:
                    # blocks for about ten seconds per attempt, then raises
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def unused() -> list[Path]:
    """Files in the models folder that no catalog model names: older checkpoints and caches."""
    names = file_names()
    keep = names | {_ledger_path().name} | {f"{name}.{tail}" for name in names for tail in ("part", "lock")}
    return sorted(p for p in paths.models_dir().iterdir() if p.is_file() and p.name not in keep)


def remove_unused() -> int:
    freed = 0
    for path in unused():
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        freed += size
    return freed


def remove(model: Model) -> None:
    keep = {
        f.name
        for m in MODELS.values()
        if m.id != model.id and not missing_files(m, deep=False)
        for f in m.files
    }
    for file in model.files:
        if file.name not in keep:
            file_path(file).unlink(missing_ok=True)
            _forget(file)


def _partial_size(file: WeightFile) -> int:
    part = file_path(file).with_name(file.name + ".part")
    return min(part.stat().st_size, file.size) if part.is_file() else 0


def _transient(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(exc, urllib.error.URLError | TimeoutError | ConnectionError | http.client.HTTPException)


def _download_with_retries(file: WeightFile, progress: Callable[[int], None]) -> None:
    # each attempt resumes from the .part file, so a dropped connection costs only the lost chunk
    for attempt in range(ATTEMPTS):
        try:
            return _download(file, progress)
        except Exception as exc:
            if attempt == ATTEMPTS - 1 or not _transient(exc):
                raise
            time.sleep(2 * 2**attempt)


def _download(file: WeightFile, progress: Callable[[int], None]) -> None:
    target = file_path(file)
    part = target.with_name(target.name + ".part")
    offset = part.stat().st_size if part.exists() else 0
    if offset >= file.size:
        part.unlink()
        offset = 0
    request = urllib.request.Request(file.url, headers={"User-Agent": USER_AGENT})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response:
        if offset and response.status != 206:
            offset = 0
        if offset:
            _hash_into(part, digest)
        with part.open("ab" if offset else "wb") as out:
            written = offset
            while chunk := response.read(CHUNK):
                written += len(chunk)
                if written > file.size:
                    raise OSError(f"{file.name} is larger than expected")
                out.write(chunk)
                digest.update(chunk)
                progress(written)
    if written != file.size or digest.hexdigest() != file.sha256:
        part.unlink(missing_ok=True)
        raise OSError(f"{file.name} failed its integrity check, try downloading again")
    part.replace(target)
    _remember(file)


def _hash_into(path: Path, digest) -> None:
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)


def _ledger_path() -> Path:
    return paths.models_dir() / "verified.json"


def _ledger() -> dict[str, list]:
    try:
        return json.loads(_ledger_path().read_text())
    except (OSError, ValueError):
        return {}


def _stamp(path: Path) -> list:
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def _save_ledger(ledger: dict[str, list]) -> None:
    # the app and the worker both record verified files, so each writes its own temporary
    temporary = _ledger_path().with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(ledger))
    temporary.replace(_ledger_path())


def _remember(file: WeightFile) -> None:
    with _lock:
        ledger = _ledger()
        ledger[file.name] = [*_stamp(file_path(file)), file.sha256]
        _save_ledger(ledger)


def _forget(file: WeightFile) -> None:
    with _lock:
        ledger = _ledger()
        if ledger.pop(file.name, None) is not None:
            _save_ledger(ledger)


def _trusted(file: WeightFile, deep: bool = True) -> bool:
    path = file_path(file)
    if not path.is_file() or path.stat().st_size != file.size:
        return False
    if not deep or _ledger().get(file.name) == [*_stamp(path), file.sha256]:
        return True
    # files from older builds were never hashed; check them once
    digest = hashlib.sha256()
    _hash_into(path, digest)
    if digest.hexdigest() != file.sha256:
        return False
    _remember(file)
    return True
