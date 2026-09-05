"""CLI: python -m split.cli separate song.mp3 -o out/ --task vocals --tier best"""
from __future__ import annotations

import argparse
from pathlib import Path

from .engine import OUTPUT_FORMATS, SeparationEngine, SeparationRequest
from .models import MODEL_IDS, TASKS, get_model, resolve_model


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="split", description="Local lalal.ai-class stem splitter")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("separate", help="Split audio into stems")
    s.add_argument("input", type=Path, help="Input audio file (mp3/wav/flac/ogg/m4a)")
    s.add_argument("-o", "--output", type=Path, default=Path("separated"))
    s.add_argument("--task", default="vocals", choices=list(TASKS),
                   help="Use case: vocals/karaoke/band/band6/drums/cleanup")
    s.add_argument("--tier", default="balanced", choices=["fast", "balanced", "best", "ultra"])
    s.add_argument("--model", default=None, choices=MODEL_IDS,
                   help="Pin a specific model (overrides task+tier)")
    s.add_argument("--demucs-model", default=None, help="Legacy: raw demucs model name")
    s.add_argument("--stems", nargs="*", default=None, help="Subset of stems (default: all)")
    s.add_argument("--format", dest="output_format", default="mp3", choices=list(OUTPUT_FORMATS))
    s.add_argument("--mp3-bitrate", type=int, default=320)
    s.add_argument("--overlap", type=float, default=0.25)
    s.add_argument("--shifts", type=int, default=1, help="Demucs ensemble shifts (band tasks)")
    s.add_argument("--enhanced", action="store_true", help="Max-quality mode: denser overlap + focused stems")
    s.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])

    sub.add_parser("models", help="List available models")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "models":
        for m in __import__("split.models", fromlist=["MODELS"]).MODELS:
            sdr = f" SDR={m.sdr}" if m.sdr else ""
            print(f"{m.id:16} [{m.quality:8}] {','.join(m.stems)}{sdr}\n                 {m.label} — {m.description}")
        return 0

    model = get_model(args.model) if args.model else resolve_model(args.task, args.tier)
    print(f"Task: {args.task} | Tier: {args.tier} | Model: {model.label}")
    engine = SeparationEngine()

    def progress(frac: float, msg: str):
        print(f"\r[{frac * 100:5.1f}%] {msg}", end="", flush=True)

    req = SeparationRequest(
        input_path=args.input,
        output_dir=args.output,
        model_id=model.id,
        model=args.demucs_model or "",
        stems=args.stems,
        output_format=args.output_format,
        mp3_bitrate=args.mp3_bitrate,
        overlap=args.overlap,
        shifts=args.shifts,
        enhanced=args.enhanced,
        device=args.device,
    )
    result = engine.separate(req, on_progress=progress)
    print()
    for stem, path in result.stem_files.items():
        print(f"  {stem:12} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
