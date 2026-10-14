import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from split import __version__, updates
from split.server import create_app

TOKEN = "test-token"
RECEIPT = [{"app": "split", "version": "0.3.0", "install_root": "C:/Programs/Split"}]


def answer(stdout, code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


@pytest.fixture
def installer(monkeypatch, tmp_path):
    exe = tmp_path / "rot-installer.exe"
    exe.write_bytes(b"")
    replies = {
        "status": answer(json.dumps(RECEIPT)),
        "check": answer(json.dumps({"version": "9.0.0", "notes": "faster karaoke"})),
    }
    calls = []

    def run(path, *args):
        calls.append(args)
        return replies[args[0]]

    monkeypatch.setattr(updates, "installer", lambda: exe)
    monkeypatch.setattr(updates, "_run", run)
    return exe, replies, calls


@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        ("0.3.1", "0.3.0", True),
        ("0.10.0", "0.9.9", True),
        ("0.3.0", "0.3.0", False),
        ("0.2.9", "0.3.0", False),
        ("0.4.0", "0.4.0-rc.1", True),
        ("0.4.0-rc.1", "0.3.0", True),
        ("0.4.0-rc.1", "0.4.0", False),
    ],
)
def test_versions_compare_as_semver(candidate, current, expected):
    assert updates.newer(candidate, current) is expected


def test_check_reads_status_then_release(installer):
    exe, _, calls = installer
    release = updates.check(exe)
    assert release == {"version": "9.0.0", "notes": "faster karaoke", "root": "C:/Programs/Split"}
    assert calls == [("status", "split", "--json"), ("check", "split", "--json")]


def test_copies_the_installer_does_not_own_never_offer_updates(installer):
    exe, replies, calls = installer
    replies["status"] = answer("[]")
    with pytest.raises(updates.UpdateError, match="not installed by the rot installer"):
        updates.check(exe)
    assert len(calls) == 1


def test_refresh_flags_a_newer_release_and_reports_change(installer):
    changes = []
    tracker = updates.Updates(enabled=False, on_change=lambda: changes.append(1))
    state = tracker.refresh()
    assert state["available"] is True
    assert state["version"] == "9.0.0"
    assert tracker.refresh() == state
    assert changes == [1]


def test_refresh_without_an_installer_stays_quiet(monkeypatch):
    monkeypatch.setattr(updates, "installer", lambda: None)
    state = updates.Updates(enabled=False).refresh()
    assert state["available"] is False
    assert "not on this computer" in state["error"]


def test_install_hands_off_and_relaunches(installer, monkeypatch):
    launched = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda command, **kwargs: launched.append(command))
    tracker = updates.Updates(enabled=False)
    with pytest.raises(updates.UpdateError):
        tracker.install(42)
    tracker.refresh()
    tracker.install(42)
    (command,) = launched
    assert "update split --wait-pid 42" in command
    assert 'start "" "' in command and "Split.exe" in command


def test_current_release_is_not_an_update(installer):
    _, replies, _ = installer
    replies["check"] = answer(json.dumps({"version": __version__, "notes": ""}))
    assert updates.Updates(enabled=False).refresh()["available"] is False


class Tracker(updates.Updates):
    def __init__(self):
        super().__init__(enabled=False)
        self.state = {"available": True, "version": "9.0.0", "notes": "", "error": None}
        self.installed = []

    def install(self, pid):
        self.installed.append(pid)


@pytest.fixture
def client(make_jobs):
    tracker = Tracker()
    app = create_app(jobs=make_jobs("hang"), token=TOKEN, updates=tracker)
    quits = []
    app.state.quit = lambda: quits.append(1)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.tracker, test_client.quits = tracker, quits
        yield test_client


def test_state_carries_the_update(client):
    assert client.get("/api/state").json()["update"]["version"] == "9.0.0"
    assert client.get("/api/update").json()["available"] is True


def test_install_is_refused_while_the_queue_is_busy(client, tmp_path):
    song = tmp_path / "a.wav"
    song.write_bytes(b"x")
    headers = {"x-split-token": TOKEN}
    assert client.post("/api/update").status_code == 403
    client.post("/api/jobs", json={"paths": [str(song)], "task": "vocals"}, headers=headers)
    refused = client.post("/api/update", headers=headers)
    assert refused.status_code == 409
    assert "queue" in refused.json()["detail"]
    assert client.tracker.installed == []


def test_install_closes_the_window_once_the_installer_starts(client):
    import time

    reply = client.post("/api/update", headers={"x-split-token": TOKEN})
    assert reply.json() == {"installing": "9.0.0"}
    assert len(client.tracker.installed) == 1
    deadline = time.monotonic() + 3
    while not client.quits and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.quits == [1]
