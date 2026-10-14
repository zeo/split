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


# hit-test codes the native move and size loops understand
HIT = {"move": 2, "w": 10, "e": 11, "n": 12, "nw": 13, "ne": 14, "s": 15, "sw": 16, "se": 17}
CUSTOM_CHROME = sys.platform == "win32"


def _native_loop(hwnd: int, hit: int) -> None:
    """Hand the drag to Windows so moving and resizing get snap, edge glue and full frame rate."""
    import ctypes

    user32 = ctypes.windll.user32
    user32.ReleaseCapture()
    user32.PostMessageW(hwnd, 0x00A1, hit, 0)  # WM_NCLBUTTONDOWN


def _round_corners(hwnd: int) -> None:
    import ctypes

    preference = ctypes.c_int(2)  # DWMWCP_ROUND
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference))


class Bridge:
    """Native dialogs and window chrome for the page; everything else goes through the HTTP API."""

    # pywebview exposes every public attribute to the page and walks it recursively,
    # so the window handle has to stay private
    def __init__(self) -> None:
        self._window = None
        self._hwnd = 0
        self._maximized = False

    def chrome(self) -> dict:
        return {"custom": CUSTOM_CHROME, "maximized": self._maximized}

    def pick_files(self) -> list[str]:
        import webview

        from .media import EXTENSIONS

        audio = f"Audio and video ({';'.join(f'*.{e}' for e in EXTENSIONS)})"
        chosen = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True, file_types=(audio, "All files (*.*)")
        )
        return list(chosen or [])

    def pick_folder(self) -> str | None:
        import webview

        chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return chosen[0] if chosen else None

    def window_drag(self, edge: str = "move") -> None:
        if self._hwnd and edge in HIT and not (self._maximized and edge != "move"):
            _native_loop(self._hwnd, HIT[edge])

    def window_minimize(self) -> None:
        self._window.minimize()

    def window_toggle(self) -> None:
        if self._maximized:
            self._window.restore()
            return
        # a borderless form maximizes over the taskbar unless told where the work area ends
        from System.Windows.Forms import Screen

        form = self._window.native
        form.MaximizedBounds = Screen.FromHandle(form.Handle).WorkingArea
        self._window.maximize()

    def window_close(self) -> None:
        self._window.destroy()

    def _attach(self, window) -> None:
        self._window = window

        def shown() -> None:
            if CUSTOM_CHROME:
                self._hwnd = int(window.native.Handle.ToInt64())
                _round_corners(self._hwnd)

        def state(maximized: bool) -> None:
            self._maximized = maximized
            window.evaluate_js(f"window.splitChrome && window.splitChrome({str(maximized).lower()})")

        window.events.shown += shown
        window.events.maximized += lambda: state(True)
        window.events.restored += lambda: state(False)


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    args = list(sys.argv[1:] if argv is None else argv)
    paths.log_to_file_if_headless("split")
    if "--self-test" in args:
        index = args.index("--self-test")
        return self_test(args[index + 1] if index + 1 < len(args) else None)
    files = [str(Path(a).resolve()) for a in args if not a.startswith("-") and Path(a).exists()]
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
        "split",
        f"http://127.0.0.1:{port}/",
        js_api=bridge,
        width=1320,
        height=860,
        min_size=(980, 640),
        background_color="#0f1317",
        text_select=False,
        frameless=CUSTOM_CHROME,
        easy_drag=False,
        # scripted runs drive the app over its api without putting a window on screen
        hidden=os.environ.get("SPLIT_WINDOW") == "hidden",
    )
    bridge._attach(window)
    app.state.focus = lambda: (window.restore(), window.show())
    app.state.quit = window.destroy
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
            # winforms only takes .ico; the other backends want an image file
            icon=str(
                paths.bundle_dir() / "assets" / ("icon.ico" if sys.platform == "win32" else "icon-1024.png")
            ),
        )
    finally:
        instance.unlink(missing_ok=True)
        server.should_exit = True
        thread.join(15)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
