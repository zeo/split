"""Command line: separate files, manage models, or serve the web ui."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from . import __version__, catalog, media, paths


def _human(size: int) -> str:
    return f"{size / 1e9:.2f} GB" if size >= 1e8 else f"{size / 1e6:.0f} MB"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="split", description="Local stem separation studio")
    parser.add_argument("--version", action="version", version=f"split {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("separate", help="split audio files into stems")
    run.add_argument("inputs", nargs="+", type=Path, help="audio or video files")
    run.add_argument(
        "-o", "--output", type=Path, default=Path("stems"), help="output folder (default: ./stems)"
    )
    run.add_argument("-t", "--task", default="vocals", choices=list(catalog.TASKS))
    run.add_argument("-q", "--tier", help="quality tier; defaults to the task's best")
    run.add_argument("-s", "--stems", nargs="+", help="only write these stems")
    run.add_argument("-f", "--format", default="wav", choices=media.FORMATS)
    run.add_argument("--isolate", action="store_true", help="cleanup tasks: isolate vocals first")
    run.add_argument("--cpu", action="store_true", help="run on the cpu even if a gpu is present")
    run.add_argument("--json", action="store_true", help="print progress as json lines")

    models = commands.add_parser("models", help="list tasks, tiers and models")
    models.add_argument("--json", action="store_true")

    fetch = commands.add_parser("download", help="download model weights ahead of time")
    fetch.add_argument("models", nargs="+", help="model ids, or 'all'")

    serve = commands.add_parser("serve", help="run the web ui in your browser")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def _list(as_json: bool) -> int:
    from . import weights

    status = weights.status()
    if as_json:
        data = catalog.public()
        for model_id, state in status.items():
            data["models"][model_id].update(state)
        print(json.dumps(data, indent=2))
        return 0
    for task in catalog.TASKS.values():
        print(f"{task.id:13} {task.label}: {task.blurb}")
        print(f"{'':13} stems: {', '.join(task.stems)}")
        for tier in task.tiers:
            mark = "*" if tier.id == task.default_tier else " "
            print(f"{'':13} {mark} {tier.id:7} {tier.blurb}")
    print("\nmodels")
    for model in catalog.MODELS.values():
        state = "ready" if status[model.id]["present"] else _human(status[model.id]["missing"])
        print(f"  {model.id:18} {model.author} {model.label} [{model.license}] {state}")
    return 0


def _download(ids: list[str]) -> int:
    from . import weights

    chosen = list(catalog.MODELS) if ids == ["all"] else ids
    unknown = [i for i in chosen if i not in catalog.MODELS]
    if unknown:
        print(f"unknown model: {', '.join(unknown)}", file=sys.stderr)
        return 2
    for model_id in chosen:
        model = catalog.MODELS[model_id]

        def report(done: int, total: int, label: str = model.label) -> None:
            print(f"\r{label}: {done * 100 // max(total, 1):3d}%", end="", flush=True)

        weights.fetch(model, report)
        print(f"\r{model.label}: ready")
    return 0


def _separate(args: argparse.Namespace) -> int:
    task = catalog.TASKS[args.task]
    tier = args.tier or task.default_tier
    try:
        task.tier(tier)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    allowed = task.stems_for(args.isolate)
    if args.stems and not set(args.stems) <= set(allowed):
        print(f"{task.label} stems are: {', '.join(allowed)}", file=sys.stderr)
        return 2
    stems = [s for s in allowed if not args.stems or s in args.stems]
    missing = [p for p in args.inputs if not p.is_file()]
    if missing:
        print(f"not found: {', '.join(map(str, missing))}", file=sys.stderr)
        return 2
    if args.cpu:
        os.environ["SPLIT_DEVICE"] = "cpu"
    paths.expose_ffmpeg()

    from .engine import Runner, classify_error

    runner = Runner()
    if not args.json:
        print(f"{task.label} / {tier} on {runner.device['name']}")
    args.output.mkdir(parents=True, exist_ok=True)
    failures = 0
    for source in args.inputs:

        def emit(source: Path = source, **event) -> None:
            if args.json:
                print(json.dumps({"file": str(source), **event}), flush=True)
            elif event.get("detail"):
                print(f"\r  {event['fraction'] * 100:5.1f}%  {event['detail'][:60]:60}", end="", flush=True)

        with tempfile.TemporaryDirectory(prefix="split-") as work:
            request = {
                "job_dir": work,
                "source": str(source),
                "task": task.id,
                "tier": tier,
                "isolate": args.isolate,
                "stems": stems,
                "format": args.format,
            }
            try:
                result = runner.separate(request, emit)
            except Exception as exc:
                failures += 1
                kind, message = classify_error(exc)
                if args.json:
                    print(json.dumps({"file": str(source), "error": message, "kind": kind}), flush=True)
                else:
                    print(f"\n{source.name}: {message}", file=sys.stderr)
                continue
            written = {}
            for stem, name in result["outputs"].items():
                dest = args.output / f"{source.stem} - {stem}.{args.format}"
                shutil.move(Path(work) / name, dest)
                written[stem] = str(dest)
        if args.json:
            print(json.dumps({"file": str(source), "outputs": written}), flush=True)
        else:
            print(f"\r{source.name}{'':70}")
            for stem, dest in written.items():
                print(f"  {stem:13} {dest}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "models":
        return _list(args.json)
    if args.command == "download":
        return _download(args.models)
    if args.command == "serve":
        from .server import serve

        print(f"Split is running at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
        serve(port=args.port)
        return 0
    return _separate(args)


if __name__ == "__main__":
    raise SystemExit(main())
