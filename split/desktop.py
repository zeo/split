"""Desktop entry: the web ui in a native window, served from a loopback port in this process."""

from __future__ import annotations

import json
import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__, paths

EXTENSIONS = "mp3 wav flac ogg opus m4a aac aif aiff wma mp4 mkv mov webm".split()
AUDIO_FILTER = f"Audio and video ({';'.join(f'*.{e}' for e in EXTENSIONS)})"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _instance_file() -> Path:
    return paths.data_root() / "instance.json"


def _hand_off(files: list[str]) -> bool:
    """Ask an already running Split to come forward and take these files. True if it answered."""
    try:
        info = json.loads(_instance_file().read_text())
        request = urllib.request.Request(
            f"http://127.0.0.1:{info['port']}/api/focus",
            data=json.dumps({"paths": files}).encode(),
            headers={"content-type": "application/json", "x-split-token": info["token"]},
        )
        with urllib.request.urlopen(request, timeout=3):
            return True
    except (OSError, ValueError, KeyError):
        return False


def self_test(report_path: str | None) -> int:
    """Smoke check for packaged builds: every heavy import resolves and ffmpeg runs."""
    import subprocess

    import audio_separator.separator  # noqa: F401
    import torch

    from . import engine, server  # noqa: F401

    ffmpeg = subprocess.run([paths.ffmpeg_bin(), "-version"], capture_output=True, text=True, check=True)
    report = {
        "version": __version__,
        "torch": torch.__version__,
        "cuda": torch.cuda.is_available(),
        "ffmpeg": ffmpeg.stdout.splitlines()[0],
        "web": str(paths.web_dir()),
    }
    # windowed builds have no stdout, so the report can go to a file instead
    if report_path:
        Path(report_path).write_text(json.dumps(report))
    else:
        print(json.dumps(report))
    return 0


class Bridge:
    """Native dialogs for the page; everything else goes through the HTTP API."""

    def __init__(self) -> None:
        self.window = None

    def pick_files(self) -> list[str]:
        import webview

        chosen = self.window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True, file_types=(AUDIO_FILTER, "All files (*.*)")
        )
        return list(chosen or [])

    def pick_folder(self) -> str | None:
        import webview

        chosen = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return chosen[0] if chosen else None


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    args = list(sys.argv[1:] if argv is None else argv)
    paths.log_to_file_if_headless("split")
    if "--self-test" in args:
        index = args.index("--self-test")
        return self_test(args[index + 1] if index + 1 < len(args) else None)
    files = [str(Path(a).resolve()) for a in args if not a.startswith("-") and Path(a).is_file()]
    if _hand_off(files):
        return 0

    import uvicorn
    import webview
    from webview.dom import DOMEventHandler

    from .server import create_app

    paths.expose_ffmpeg()
    port = _free_port()
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="split-http", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        return 1

    instance = _instance_file()
    instance.write_text(json.dumps({"pid": os.getpid(), "port": port, "token": app.state.token}))

    bridge = Bridge()
    window = webview.create_window(
        "Split",
        f"http://127.0.0.1:{port}/",
        js_api=bridge,
        width=1320,
        height=860,
        min_size=(980, 640),
        background_color="#101418",
        text_select=False,
    )
    bridge.window = window
    app.state.focus = lambda: (window.restore(), window.show())
    if files:
        app.state.open_files(files)

    def on_drop(event: dict) -> None:
        dropped = [f.get("pywebviewFullPath") for f in event.get("dataTransfer", {}).get("files", [])]
        app.state.open_files([p for p in dropped if p])

    def wire_events() -> None:
        window.dom.document.events.dragover += DOMEventHandler(lambda _: None, prevent_default=True)
        window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True)

    window.events.loaded += wire_events
    try:
        webview.start(
            gui="edgechromium" if sys.platform == "win32" else None,
            private_mode=False,
            storage_path=str(paths.data_root() / "webview"),
            icon=str(paths.bundle_dir() / "assets" / "icon-1024.png"),
        )
    finally:
        instance.unlink(missing_ok=True)
        server.should_exit = True
        thread.join(15)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
