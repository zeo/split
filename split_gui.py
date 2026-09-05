"""Split desktop entry: launches API server + opens the app in a browser window."""
from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

APP_DIR = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("SPLIT_PORT", "8000"))


def find_free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def open_browser_later(url: str, delay: float = 1.5):
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, daemon=True).start()


def main():
    global PORT
    try:
        with socket.socket() as s:
            s.bind((HOST, PORT))
    except OSError:
        PORT = find_free_port()
    url = f"http://{HOST}:{PORT}"
    print(f"Split running at {url}  (keep this window open; Ctrl+C to quit)")
    open_browser_later(url)
    os.chdir(APP_DIR)
    # frozen exe: torch/demucs need a writable cache; audio-separator models
    # live next to the exe in models_cache/
    os.environ.setdefault("HF_HUB_CACHE", str(APP_DIR / "models_cache" / "hf"))
    os.environ.setdefault("TORCH_HOME", str(APP_DIR / "models_cache" / "torch"))
    uvicorn.run("split.server:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
