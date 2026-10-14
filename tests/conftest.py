import queue
import time
import urllib.request
from pathlib import Path

import pytest

from split.jobs import FINISHED, Jobs


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPLIT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # queued jobs prefetch real weights; tests must never reach the network
    def refuse(*args, **kwargs):
        raise AssertionError("tests do not download")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


class FakeSupervisor:
    """Stands in for the worker process: answers requests from a queue, instantly."""

    def __init__(self, behaviour: str = "finish"):
        self.behaviour = behaviour
        self.events: queue.Queue = queue.Queue()
        self.device = None
        self.fatal = None
        self.running = False
        self.kills = 0
        self.requests: list[dict] = []

    def ensure(self) -> None:
        if not self.running:
            self.running = True
            self.events.put(
                {"type": "ready", "device": {"kind": "cpu", "name": "CPU", "memory": 0, "note": ""}}
            )

    def alive(self) -> bool:
        return self.running

    def send(self, request: dict) -> None:
        self.ensure()
        self.requests.append(request)
        key = request["key"]
        if request["kind"] != "separate":
            self.events.put({"type": "done", "key": key})
            return
        self.events.put(
            {
                "type": "progress",
                "key": key,
                "phase": "separate",
                "detail": "Separating",
                "fraction": 0.5,
                "phase_fraction": 0.5,
            }
        )
        if self.behaviour == "hang":
            return
        if self.behaviour == "crash":
            self.running = False
            return
        if self.behaviour == "fail":
            self.events.put(
                {"type": "error", "key": key, "kind": "oom", "message": "The GPU ran out of memory."}
            )
            return
        job_dir = Path(request["job_dir"])
        (job_dir / "peaks").mkdir(parents=True, exist_ok=True)
        outputs = {}
        for stem in request["stems"]:
            name = f"{stem}.{request['format']}"
            (job_dir / name).write_bytes(stem.encode() * 64)
            (job_dir / "peaks" / f"{stem}.json").write_text('{"duration": 1.0, "peak": [0.5], "rms": [0.2]}')
            outputs[stem] = name
        (job_dir / "original.flac").write_bytes(b"mix" * 64)
        (job_dir / "peaks" / "original.json").write_text('{"duration": 1.0, "peak": [0.9], "rms": [0.4]}')
        self.events.put(
            {"type": "done", "key": key, "outputs": outputs, "original": "original.flac", "duration": 1.0}
        )

    def receive(self, timeout: float):
        try:
            return self.events.get(timeout=min(timeout, 0.05))
        except queue.Empty:
            return None

    def kill(self) -> None:
        self.running = False
        self.kills += 1
        while not self.events.empty():
            self.events.get_nowait()

    def stop(self) -> None:
        self.running = False


@pytest.fixture
def make_jobs(tmp_path):
    started = []

    def build(behaviour: str = "finish", root: Path | None = None) -> Jobs:
        jobs = Jobs(root or tmp_path / "jobs", FakeSupervisor(behaviour))
        started.append(jobs)
        return jobs

    yield build
    for jobs in started:
        jobs.stop()


def wait_for(jobs: Jobs, job_id: str, statuses=FINISHED, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = jobs.get(job_id)
        if record and record["status"] in statuses:
            return record
        time.sleep(0.02)
    raise AssertionError(f"{job_id} stuck at {jobs.get(job_id)}")
