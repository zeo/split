"""Model weight files on disk: resumable, hash-pinned downloads."""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import paths
from .catalog import MODELS, Model, WeightFile

USER_AGENT = "split-stem-separator"
CHUNK = 1 << 20

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
    done = 0
    for file in todo:
        _download(file, lambda n, base=done: progress and progress(base + n, total))
        done += file.size
        if progress:
            progress(done, total)


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


def _download(file: WeightFile, progress: Callable[[int], None]) -> None:
    target = file_path(file)
    part = target.with_name(target.name + ".part")
    offset = part.stat().st_size if part.exists() else 0
    if offset > file.size:
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
    temporary = _ledger_path().with_suffix(".tmp")
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
