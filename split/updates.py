"""Update checks and installs through the shared rot installer, the same way capscr does it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from . import __version__, paths

APP = "split"
CHECK_EVERY = 6 * 3600
INSTALLER = "rot-installer.exe" if sys.platform == "win32" else "rot-installer"

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class UpdateError(RuntimeError):
    pass


def installer() -> Path | None:
    candidates = []
    if paths.frozen():
        here = Path(sys.executable).resolve().parent
        candidates += [here / INSTALLER, here / "installer" / INSTALLER]
    if root := os.environ.get("PROGRAMFILES"):
        candidates.append(Path(root) / "rot" / "installer" / INSTALLER)
    if root := os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(root) / "Programs" / "rot-installer" / INSTALLER)
    return next((c for c in candidates if c.is_file()), None)


def newer(candidate: str, current: str) -> bool:
    def key(version: str) -> tuple:
        core, _, pre = version.split("+")[0].partition("-")
        # a release sorts above its own pre-releases
        return (*(int(part) for part in core.split(".")), not pre, pre)

    return key(candidate) > key(current)


def _run(exe: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(exe), *args], capture_output=True, text=True, timeout=120, creationflags=_NO_WINDOW
    )


def check(exe: Path | None = None) -> dict:
    """Ask the installer for the newest release. Raises UpdateError when updates are not possible."""
    exe = exe or installer()
    if exe is None:
        raise UpdateError("The rot installer is not on this computer")
    status = _run(exe, "status", APP, "--json")
    try:
        receipts = json.loads(status.stdout or "[]") if status.returncode == 0 else []
    except ValueError:
        receipts = []
    if not receipts:
        raise UpdateError("This copy of Split was not installed by the rot installer")
    release = _run(exe, "check", APP, "--json")
    if release.returncode != 0:
        reason = (release.stderr.strip().splitlines() or ["the update check failed"])[-1]
        raise UpdateError(reason)
    data = json.loads(release.stdout)
    return {
        "version": str(data["version"]),
        "notes": data.get("notes") or "",
        "root": receipts[0]["install_root"],
    }


class Updates:
    """Checks in the background and remembers the answer for the page."""

    def __init__(self, enabled: bool | None = None, on_change: Callable[[], None] | None = None):
        self.enabled = (paths.frozen() and sys.platform == "win32") if enabled is None else enabled
        self.on_change = on_change or (lambda: None)
        self.state = {"available": False, "version": None, "notes": "", "error": None}
        self._root: str | None = None
        self._exe: Path | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = False

    def start(self) -> None:
        if self.enabled:
            threading.Thread(target=self._loop, name="split-updates", daemon=True).start()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    def _loop(self) -> None:
        while not self._stopping:
            self.refresh()
            self._wake.wait(CHECK_EVERY)
            self._wake.clear()

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.state)

    def refresh(self) -> dict:
        try:
            exe = installer()
            release = check(exe)
            state = {
                "available": newer(release["version"], __version__),
                "version": release["version"],
                "notes": release["notes"],
                "error": None,
            }
            root = release["root"]
        except (UpdateError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            exe, root = None, None
            state = {"available": False, "version": None, "notes": "", "error": str(exc)}
        with self._lock:
            changed = state != self.state
            self.state, self._root, self._exe = state, root, exe
        if changed:
            self.on_change()
        return state

    def install(self, pid: int) -> None:
        """Hand off to the installer, which waits for this process to exit, then reopen Split."""
        with self._lock:
            ready = self.state["available"] and self._exe and self._root
            exe, root = self._exe, self._root
        if not ready:
            raise UpdateError("There is no update to install")
        relaunch = Path(root) / "Split.exe"
        # a console of its own shows download progress; a failure stays on screen until a key is pressed
        script = (
            f'title Updating Split & "{exe}" update {APP} --wait-pid {pid} && start "" "{relaunch}" || pause'
        )
        console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(f'cmd.exe /s /c "{script}"', creationflags=console)
