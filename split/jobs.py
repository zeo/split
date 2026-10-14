"""Job records on disk, a FIFO queue, and the supervisor that drives the worker process."""

from __future__ import annotations

import json
import logging
import multiprocessing
import queue
import shutil
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path

from . import catalog, paths, weights

KEEP_DAYS = 7
KEEP_JOBS = 40
ACTIVE = ("queued", "running")
CRASHED = "The separation process stopped unexpectedly. Try again, or pick a lighter tier."
FINISHED = ("done", "error", "cancelled")


def _now() -> float:
    return time.time()


class Supervisor:
    """Owns the worker process; restarts it after a cancel or a crash."""

    def __init__(self, target: Callable | None = None):
        self._target = target
        self._ctx = multiprocessing.get_context("spawn")
        self.process = None
        self.inbox = None
        self.outbox = None
        self.device: dict | None = None
        self.fatal: dict | None = None

    def _start(self) -> None:
        if self._target is None:
            from .engine import worker_main

            self._target = worker_main
        self.inbox = self._ctx.Queue()
        self.outbox = self._ctx.Queue()
        self.process = self._ctx.Process(target=self._target, args=(self.inbox, self.outbox), daemon=True)
        self.process.start()

    def alive(self) -> bool:
        return self.process is not None and self.process.is_alive()

    def ensure(self) -> None:
        if not self.alive():
            self._start()

    def send(self, request: dict) -> None:
        self.ensure()
        self.inbox.put(request)

    def receive(self, timeout: float) -> dict | None:
        try:
            return self.outbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def kill(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process.join(5)
        self.process = None

    def stop(self) -> None:
        if self.alive():
            self.inbox.put(None)
            self.process.join(3)
        self.kill()


class Jobs:
    def __init__(self, root: Path | None = None, supervisor: Supervisor | None = None):
        self.root = root or paths.jobs_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.supervisor = supervisor or Supervisor()
        self.lock = threading.Condition()
        self.records: dict[str, dict] = {}
        self.downloads: dict[str, dict] = {}
        self.pending: deque[tuple[str, str]] = deque()
        self.version = 0
        self.current: str | None = None
        self.cancel_requested = False
        self.opened: dict = {"seq": 0, "paths": [], "error": None}
        self.prefetching: set[str] = set()
        self._stopping = False
        self._load()
        self._thread = threading.Thread(target=self._loop, name="split-supervisor", daemon=True)

    def start(self) -> None:
        self.sweep()
        # warm the worker so torch is imported and the device known before the first job
        self.supervisor.ensure()
        self._thread.start()

    def stop(self) -> None:
        with self.lock:
            self._stopping = True
            self.lock.notify_all()
        self.supervisor.stop()

    # records

    def _load(self) -> None:
        for job_file in self.root.glob("*/job.json"):
            try:
                record = json.loads(job_file.read_text())
            except (OSError, ValueError):
                continue
            if record.get("status") in ACTIVE:
                record.update(
                    status="error", error="Split closed before this job finished", error_kind="interrupted"
                )
            self.records[record["id"]] = record

    def _save(self, record: dict) -> None:
        job_dir = self.root / record["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        temporary = job_dir / "job.json.tmp"
        temporary.write_text(json.dumps(record))
        temporary.replace(job_dir / "job.json")

    def _changed(self) -> None:
        self.version += 1
        self.lock.notify_all()

    def touch(self) -> None:
        """Wake event listeners when something outside the queue changed what the page shows."""
        with self.lock:
            self._changed()

    def busy(self) -> bool:
        with self.lock:
            return any(r["status"] in ACTIVE for r in self.records.values()) or any(
                d["status"] in ACTIVE for d in self.downloads.values()
            )

    def submit(self, spec: dict) -> dict:
        record = {
            "id": uuid.uuid4().hex[:12],
            "name": spec["name"],
            "source": spec["source"],
            "owns_source": spec.get("owns_source", False),
            "task": spec["task"],
            "tier": spec["tier"],
            "isolate": spec.get("isolate", False),
            "stems": list(spec["stems"]),
            "format": spec["format"],
            "status": "queued",
            "phase": "queued",
            "detail": "Waiting",
            "fraction": 0.0,
            "phase_fraction": None,
            "error": None,
            "error_kind": None,
            "outputs": {},
            "duration": None,
            "created": _now(),
            "started": None,
            "finished": None,
        }
        with self.lock:
            self.records[record["id"]] = record
            self.pending.append(("job", record["id"]))
            self._save(record)
            self._changed()
        return dict(record)

    def retry(self, job_id: str) -> dict:
        old = self.get(job_id)
        if old is None:
            raise KeyError(job_id)
        if old["owns_source"] and not Path(old["source"]).exists():
            raise FileNotFoundError("The uploaded file for this job was cleaned up, add it again")
        return self.submit(old)

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            record = self.records.get(job_id)
            return dict(record) if record else None

    def list(self) -> list[dict]:
        with self.lock:
            return sorted((dict(r) for r in self.records.values()), key=lambda r: r["created"], reverse=True)

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            record = self.records.get(job_id)
            if record is None or record["status"] not in ACTIVE:
                return False
            if record["status"] == "queued":
                self.pending = deque(item for item in self.pending if item != ("job", job_id))
                self._finish(record, "cancelled")
            else:
                self.cancel_requested = True
                self.lock.notify_all()
            return True

    def delete(self, job_id: str) -> bool:
        with self.lock:
            record = self.records.get(job_id)
            if record is None:
                return False
            if record["status"] in ACTIVE:
                raise RuntimeError("Cancel the job before deleting it")
            del self.records[job_id]
            self._changed()
        self._discard(record)
        return True

    def clear_finished(self) -> int:
        with self.lock:
            doomed = [r for r in self.records.values() if r["status"] in FINISHED]
            for record in doomed:
                del self.records[record["id"]]
            if doomed:
                self._changed()
        for record in doomed:
            self._discard(record)
        return len(doomed)

    def _discard(self, record: dict) -> None:
        shutil.rmtree(self.root / record["id"], ignore_errors=True)
        if record.get("owns_source"):
            Path(record["source"]).unlink(missing_ok=True)

    def download(self, model_id: str) -> None:
        with self.lock:
            if self.downloads.get(model_id, {}).get("status") in ACTIVE:
                return
            self.downloads[model_id] = {"status": "queued", "fraction": 0.0, "error": None}
            self.pending.append(("download", model_id))
            self._changed()

    def wait(self, version: int, timeout: float) -> int:
        with self.lock:
            if self.version == version:
                self.lock.wait(timeout)
            return self.version

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "version": self.version,
                "jobs": self.list(),
                "downloads": dict(self.downloads),
                "device": self.supervisor.device,
                "fatal": self.supervisor.fatal,
                "opened": dict(self.opened),
            }

    def offer(self, files: list[str], error: str | None = None) -> None:
        """Files handed to the app from outside the page: drops, a second launch, open-with."""
        with self.lock:
            self.opened = {"seq": self.opened["seq"] + 1, "paths": list(files), "error": error}
            self._changed()

    def sweep(self, now: float | None = None) -> int:
        now = now or _now()
        with self.lock:
            finished = sorted(
                (r for r in self.records.values() if r["status"] in FINISHED),
                key=lambda r: r["created"],
                reverse=True,
            )
            doomed = [
                r for i, r in enumerate(finished) if i >= KEEP_JOBS or now - r["created"] > KEEP_DAYS * 86400
            ]
            for record in doomed:
                del self.records[record["id"]]
            if doomed:
                self._changed()
        for record in doomed:
            self._discard(record)
        return len(doomed)

    def _finish(self, record: dict, status: str, **fields) -> None:
        record.update(status=status, phase=status, finished=_now(), **fields)
        if status == "done":
            record.update(fraction=1.0, detail="Done")
        elif status == "cancelled":
            record.update(detail="Cancelled")
        if record.get("owns_source") and status == "done":
            Path(record["source"]).unlink(missing_ok=True)
        self._save(record)
        self._changed()

    # supervisor loop

    def _next(self) -> tuple[str, str] | None:
        while True:
            with self.lock:
                if self._stopping:
                    return None
                if self.pending:
                    return self.pending.popleft()
            self._idle()

    def _idle(self) -> None:
        if not self.supervisor.alive():
            with self.lock:
                self.lock.wait(0.5)
            return
        event = self.supervisor.receive(0.5)
        if event is not None and event["type"] in ("ready", "fatal"):
            self._note(event)

    def _note(self, event: dict) -> None:
        with self.lock:
            if event["type"] == "ready":
                self.supervisor.device = event["device"]
                self.supervisor.fatal = None
            else:
                self.supervisor.fatal = event
            self._changed()

    def _loop(self) -> None:
        while (item := self._next()) is not None:
            kind, key = item
            if kind == "job":
                self._run_job(key)
            else:
                self._run_download(key)
            self.sweep()

    def _exchange(self, request: dict, on_event: Callable[[dict], None]) -> dict:
        """Send one request and pump events until it ends, the worker dies, or a cancel lands."""
        self.cancel_requested = False
        self.supervisor.send(request)
        while True:
            if self.cancel_requested:
                self.supervisor.kill()
                return {"type": "cancelled"}
            event = self.supervisor.receive(0.25)
            if event is None:
                if not self.supervisor.alive():
                    return {"type": "error", "kind": "crash", "message": CRASHED}
                continue
            if event["type"] == "ready":
                self._note(event)
                continue
            if event["type"] == "fatal":
                self._note(event)
                self.supervisor.kill()
                return {"type": "error", "kind": event["kind"], "message": event["message"]}
            if event.get("key") != request["key"]:
                continue
            if event["type"] == "progress":
                on_event(event)
                continue
            return event

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            record = self.records.get(job_id)
            if record is None or record["status"] != "queued":
                return
            record.update(status="running", phase="starting", detail="Starting", started=_now())
            self.current = job_id
            self._save(record)
            self._changed()
            request = {"kind": "separate", "key": job_id, "job_dir": str(self.root / job_id), **record}
            upcoming = next((self.records[key] for kind, key in self.pending if kind == "job"), None)
        if upcoming is not None:
            self.prefetch(upcoming)

        def on_event(event: dict) -> None:
            with self.lock:
                for field in ("phase", "detail", "fraction", "phase_fraction", "duration", "device"):
                    if event.get(field) is not None or field == "phase_fraction":
                        record[field] = event.get(field)
                self._changed()

        result = self._exchange(request, on_event)
        with self.lock:
            self.current = None
            if result["type"] == "done":
                self._finish(
                    record,
                    "done",
                    outputs=result["outputs"],
                    duration=result["duration"],
                    trim_db=result.get("trim_db", 0.0),
                    notes=result.get("notes", []),
                    original=result.get("original"),
                )
            elif result["type"] == "cancelled":
                shutil.rmtree(self.root / job_id / "work", ignore_errors=True)
                self._finish(record, "cancelled")
            else:
                if trace := result.get("trace"):
                    (self.root / job_id / "error.log").write_text(trace, encoding="utf-8")
                self._finish(record, "error", error=result["message"], error_kind=result["kind"])

    def _run_download(self, model_id: str) -> None:
        with self.lock:
            state = self.downloads[model_id]
            state.update(status="running")
            self._changed()

        def on_event(event: dict) -> None:
            with self.lock:
                state["fraction"] = event.get("fraction") or 0.0
                self._changed()

        result = self._exchange({"kind": "download", "key": f"model:{model_id}", "model": model_id}, on_event)
        with self.lock:
            if result["type"] == "done":
                state.update(status="done", fraction=1.0)
            elif result["type"] == "cancelled":
                state.update(status="cancelled")
            else:
                state.update(status="error", error=result["message"])
            self._changed()

    def prefetch(self, record: dict) -> None:
        """Fetch the weights the next job needs while the current one keeps the gpu busy."""
        steps = catalog.plan(record["task"], record["tier"], record.get("isolate", False))
        for model_id in dict.fromkeys(m for step in steps for m in step.models):
            model = catalog.MODELS[model_id]
            with self.lock:
                if model_id in self.prefetching or not weights.missing_files(model, deep=False):
                    continue
                self.prefetching.add(model_id)
            threading.Thread(
                target=self._prefetch, args=(model,), name=f"split-prefetch-{model_id}", daemon=True
            ).start()

    def _prefetch(self, model) -> None:
        try:
            weights.fetch(model)
        except Exception:
            # the job itself retries the download and reports whatever still fails
            logging.getLogger(__name__).warning("prefetching %s failed", model.id, exc_info=True)
        finally:
            with self.lock:
                self.prefetching.discard(model.id)

    def cancel_download(self, model_id: str) -> None:
        with self.lock:
            state = self.downloads.get(model_id)
            if state is None:
                return
            if state["status"] == "queued":
                self.pending = deque(item for item in self.pending if item != ("download", model_id))
                state.update(status="cancelled")
                self._changed()
            elif state["status"] == "running":
                self.cancel_requested = True
