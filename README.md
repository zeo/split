# Split - local lalal.ai-class stem splitter

Runs 100% on your machine. No uploads, no subscriptions, no file leaving your PC.

**Quality vs lalal.ai:** vocal models are Mel-Band / BS-RoFormer checkpoints
with published vocal SDR **12.6-12.98** (vs ~10.8 for the previous generation),
plus **Ultra ensembles** that combine multiple models per track, and an
**Enhanced mode** (denser overlap + focused single-stem passes). Speed: local
GPU inference with fp16 autocast on CUDA - an 8 s clip separates in ~6-30 s
depending on tier, with zero cloud round-trip.

## Desktop app (Windows)

Use `dist/Split/Split.exe` - double-click, your browser opens at
`http://127.0.0.1:8000`. Keep the console window open while using it.
First run downloads model weights (~100-500 MB each) into `models_cache/`
next to the exe.

To rebuild the exe: `pyinstaller split.spec` (Python 3.14, CUDA torch).

## From source

```bash
pip install -r requirements.txt
python -m uvicorn split.server:app --port 8000
# open http://127.0.0.1:8000
```

Pick a **task** in the sidebar (Vocals / Karaoke / Full band / Band 6-stem /
Drum kit / Cleanup), a **quality tier** (Fast / Balanced / Best / **Ultra**),
drop audio in, preview each stem in the browser, download singles or a `.zip`.
Tick **Enhanced quality** on any tier for denser-overlap, cleaner-edge output.

## CLI

```bash
python -m split.cli separate song.mp3 -o out/ --task vocals --tier ultra
python -m split.cli separate song.flac -o out/ --task band --tier best --format flac
python -m split.cli separate song.mp3 -o out/ --model viperx-1297 --enhanced
python -m split.cli models
```

Tasks: `vocals` `karaoke` `band` `band6` `drums` `cleanup`.
Tiers: `fast` `balanced` `best` `ultra`. Formats: `mp3` `wav` `flac`.
`--model <id>` pins a specific checkpoint (see `models` list).
`--overlap 0.1-0.75` and `--shifts` trade speed for quality on Demucs band tasks.

## Models (all local)

| Use | Fast | Balanced | Best | Ultra |
|---|---|---|---|---|
| Vocals | MDX Inst HQ3 (ONNX) | Kim Mel-Band (SDR 12.6) | Viperx-1297 (SDR 12.98) | Vocal Clean ensemble |
| Karaoke | MDX Inst HQ3 | becruily karaoke ckpt | Viperx-1297 | 3-model karaoke ensemble |
| Full band 4-stem | Demucs MMI | HD Demucs | HD Demucs fine-tuned | HD Demucs ft + shifts |
| Band 6-stem | HD Demucs | HD Demucs 6s | HD Demucs 6s | HD Demucs 6s |
| Drum kit | Demucs ft | MDX23C DrumSep | MDX23C DrumSep | MDX23C DrumSep |
| Cleanup | Denoise RoFormer | Denoise RoFormer | De-Reverb/Echo V2 | De-Reverb/Echo V2 |

FLAC supported for input and output (lossless). MP3 output is 320 kbps.

## API

- `GET /api/models` - models, tasks, tiers, active device
- `POST /api/jobs` - multipart `file` + `task`/`tier`/`output_format`/`stems?`/`overlap?`/`shifts?`/`enhanced?` → `{id}` (202)
- `GET /api/jobs/{id}` - status/progress/stem URLs
- `GET /api/jobs/{id}/stems/{stem}` - download one stem
- `GET /api/jobs/{id}/download` - all stems as `.zip`
- `DELETE /api/jobs/{id}` - delete job files

## Layout

```
split/  engine.py (RoFormer+Demucs+ensembles)  models.py  cli.py  server.py
split_gui.py  split.spec   (desktop launcher + exe build)
web/        index.html  styles.css  app.js   (macOS-native UI)
models_cache/  jobs/  uploads/   (runtime data, gitignored)
dist/Split/Split.exe   (built desktop app)
```

## Notes

- Community checkpoints circulate informally; weights are for personal use -
  get legal review before commercial redistribution.
- Orchestral/cinematic splitting has no dedicated open model; use Full band
  and keep the `other` stem.
