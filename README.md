# Split

![A six-stem session in Split, with the original mix on top and a loop set across the ruler](docs/screenshot.png)

Split takes a song apart on your own GPU: vocals, karaoke, four or six band stems, a drum kit, and cleanup passes for reverb, noise and crowds. It runs the strongest separation models you can download, so nothing gets uploaded and nothing gets rate-limited.

Drop files or whole folders on the window, pick a task, and each stem lands in its own lane under the original mix. Solo, mute and ride the gain to check the split, flip to the original with O, or loop a bar by dragging across the ruler. Save stems one at a time, export them all to a folder, grab a zip, or send one stem on to another task, like a vocal into de-reverb.

## Install

On Windows, install it with the rot installer, or run `split-<version>-online-setup.exe` from the [releases page](https://github.com/zeo/split/releases). The online setup is the rot installer itself. It downloads Split in parts, checks the signature, and keeps it updated: when a new version is out, Split shows it in the status bar and installs it on request. The app is about 4.4 GB on disk, most of it the CUDA build of PyTorch.

You need an NVIDIA RTX 20-series card or newer and a driver from the R580 branch or later. Older cards and machines without a supported GPU fall back to the CPU, which works but takes minutes per song. Model weights download the first time a task needs them: 270 MB for Vocals, 700 MB for 4 or 6 stems, up to 2.1 GB for Instrumental Ultra.

## Tasks

| Task | Stems | Best tier |
|---|---|---|
| Vocals | vocals, instrumental | unwa Leap Xe |
| Instrumental | instrumental, vocals | unwa Leap instrumental |
| Karaoke | lead, backing | anvuew BS-RoFormer karaoke |
| 4 stems | vocals, drums, bass, other | BS-RoFormer SW, guitar and piano folded into other |
| 6 stems | vocals, drums, bass, guitar, piano, other | BS-RoFormer SW |
| Drum kit | kick, snare, toms, hihat, cymbals | SW pulls the drums out, DrumSep 5-stem splits the kit |
| De-reverb | dry, reverb | anvuew BS de-reverb |
| Denoise | clean, noise | aufr33 denoise |
| Crowd | clean, crowd | aufr33 and viperx crowd |

Vocals, Instrumental and Karaoke also have an Ultra tier that averages two or three models sample by sample. Vocals, Instrumental and 4 stems have a Fast tier. The cleanup tasks can isolate the vocal first, so de-reverb works on the voice instead of the whole mix.

The picks follow the [MVSEP leaderboards](https://mvsep.com/quality_checker/multisong_leaderboard) as of October 2026, limited to models you can actually download. Leap Xe scores 11.76 dB SDR on vocals. SW scores 9.01 on guitar and 7.80 on piano, against 5.25 and 2.23 for HT Demucs 6s. On an RTX 4070 Ti, a four-and-a-half-minute song takes about two minutes on Vocals Best.

## Command line

```
split separate song.flac --task band6 --format flac --output stems
split separate *.mp3 --task vocals --tier ultra --stems vocals
split separate ~/Music/album --task karaoke
split models
split download leap-xe-voc sw
split serve --port 8000
```

`separate` takes any number of files or folders and anything FFmpeg can read, video included. `--json` prints progress as JSON lines for scripts. `serve` runs the same interface in your browser.

## Run from source

```
uv sync --extra desktop
uv run python -m split.desktop
uv run pytest
```

You need Python 3.11 to 3.13 (diffq, which HT Demucs needs, has no Windows wheels for 3.14) and FFmpeg on your PATH. The lockfile pulls CUDA 13.0 builds of PyTorch on Windows and Linux. `packaging/build.ps1` makes the Windows build: it fetches a pinned FFmpeg, builds with PyInstaller from a clean environment, and smoke-tests the result.

## How it works

- `split/catalog.py` is the single list of models, tasks and tiers. Every weight file is pinned by URL, size and SHA-256, so a mirror that swaps a file gets refused.
- Separation runs in a worker process (`split/engine.py`) that owns the GPU. Jobs run one at a time, a cancel kills and respawns the worker to free VRAM, and a crash fails the job instead of the app. A model that runs out of GPU memory gets a second and third try on half-length chunks.
- Models run through [audio-separator](https://github.com/nomadkaraoke/python-audio-separator) with three changes:
  - Its per-stem peak normalization is off, so stems sum back to the mix.
  - Rotary embeddings run in half precision with cached angles.
  - Flash attention is enabled on every card that supports it. Together these make inference 2.5x to 3.5x faster than float32, with vocal stems within 48 to 53 dB SNR of the float32 output.
- Input is decoded once by FFmpeg to 44.1 kHz float. Output goes back to the source's own sample rate and channel count. If any stem would clip, all of them get the same trim, so they keep summing to the mix.
- The window is [pywebview](https://pywebview.flowrl.com) on WebView2, talking to a loopback FastAPI server that accepts only local hosts and a per-launch token. Playback decodes every stem into Web Audio buffers that start on one clock, so soloing two stems never drifts. The title bar is drawn by the page, but dragging and resizing hand off to Windows, so snap and maximize behave like any other window.

Settings, models and finished jobs live in `%LOCALAPPDATA%\Split` on Windows, `~/Library/Application Support/Split` on macOS and `~/.local/share/split` on Linux. Set `SPLIT_HOME` to move them.

## License

Split's code is MIT or Apache-2.0, your choice. Model weights belong to their authors, and several are GPL-3.0, non-commercial or unlicensed. The Windows build bundles FFmpeg (GPL-3.0) and diffq (CC-BY-NC-4.0), which makes the packaged app non-commercial. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) lists every model and bundled component with its source.
