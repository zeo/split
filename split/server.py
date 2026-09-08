"""Split web server: upload -> separate -> preview/download stems."""
from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .engine import OUTPUT_FORMATS, SeparationEngine, SeparationRequest, resolve_device
from .models import MODELS, TASKS, get_model, resolve_model

log = logging.getLogger("split")

BASE_DIR = Path(__file__).resolve().parent.parent
JOBS_DIR = BASE_DIR / "jobs"
UPLOAD_DIR = BASE_DIR / "uploads"
JOBS_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_MB = 500
ALLOWED_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".wma", ".opus", ".aiff", ".aif"}
JOB_TTL_SEC = 48 * 3600
MAX_KEPT_JOBS = 20


def _ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def _sweep_old_jobs(ttl=JOB_TTL_SEC, keep=MAX_KEPT_JOBS):
    import time as _t
    now = _t.time()
    removed = 0
    try:
        dirs = sorted([d for d in JOBS_DIR.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime)
    except FileNotFoundError:
        return 0
    for d in dirs:
        if now - d.stat().st_mtime > ttl:
            shutil.rmtree(d, ignore_errors=True)
            for up in UPLOAD_DIR.glob(d.name + ".*"):
                up.unlink(missing_ok=True)
            removed += 1
    try:
        dirs = sorted([d for d in JOBS_DIR.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime)
    except FileNotFoundError:
        return removed
    excess = len(dirs) - keep
    if excess > 0:
        for d in dirs[:excess]:
            shutil.rmtree(d, ignore_errors=True)
            for up in UPLOAD_DIR.glob(d.name + ".*"):
                up.unlink(missing_ok=True)
            removed += 1
    for up in UPLOAD_DIR.iterdir():
        try:
            if now - up.stat().st_mtime > ttl and not (JOBS_DIR / up.stem).exists():
                up.unlink(missing_ok=True)
                removed += 1
        except FileNotFoundError:
            pass
    return removed


_sweep_old_jobs()

TIERS = ("fast", "balanced", "best", "ultra")

app = FastAPI(title="StemsSplit")
engine = SeparationEngine()
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def _job_payload(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        payload = {k: v for k, v in job.items() if k != "_stem_paths"}
        if job.get("status") == "done":
            payload["stems"] = {
                stem: f"/api/jobs/{job_id}/stems/{stem}" for stem in job["_stem_paths"]
            }
        return payload


def _run_job(job_id: str, req: SeparationRequest):
    def progress(frac: float, msg: str):
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["progress"] = round(frac, 4)
                jobs[job_id]["message"] = msg

    try:
        result = engine.separate(req, on_progress=progress)
        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["progress"] = 1.0
            jobs[job_id]["message"] = "Done"
            jobs[job_id]["_stem_paths"] = {s: str(p) for s, p in result.stem_files.items()}
            jobs[job_id]["finished_at"] = time.time()
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["message"] = f"{type(exc).__name__}: {exc}"


@app.get("/api/models")
def list_models():
    return {
        "models": [
            {"id": m.id, "backend": m.backend, "label": m.label,
             "description": m.description, "stems": m.stems,
             "quality": m.quality, "sdr": m.sdr}
            for m in MODELS
        ],
        "tasks": {tid: dict(info) for tid, info in TASKS.items()},
        "tiers": list(TIERS),
        "formats": list(OUTPUT_FORMATS),
        "device": resolve_device("auto"),
    }


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    task: str = Form("vocals"),
    tier: str = Form("balanced"),
    model: str | None = Form(None),
    stems: str | None = Form(None),
    output_format: str = Form("mp3"),
    overlap: float | None = Form(None),
    shifts: int | None = Form(None),
    enhanced: bool = Form(False),
):
    ext = Path(file.filename or "audio").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Unsupported file type {ext!r}. Use mp3/wav/flac/ogg/m4a.")
    if output_format not in OUTPUT_FORMATS:
        raise HTTPException(400, f"Bad format {output_format!r}")
    if output_format in ("mp3", "flac") and not _ffmpeg_available():
        raise HTTPException(500, "ffmpeg is required for mp3/flac encoding but was not found on PATH. Install ffmpeg or choose wav output.")
    if task not in TASKS:
        raise HTTPException(400, f"Unknown task {task!r}")
    if tier not in TIERS:
        raise HTTPException(400, f"Unknown tier {tier!r}")

    info = get_model(model) if model else resolve_model(task, tier)

    wanted = None
    if stems:
        wanted = [s.strip() for s in stems.split(",") if s.strip()]
        bad = [s for s in wanted if s.lower() not in [x.lower() for x in info.stems]]
        if bad:
            raise HTTPException(400, f"Model {info.id} has no stems {bad}; choose from {info.stems}")

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{job_id}{ext}"
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                dest.unlink(missing_ok=True)
                raise HTTPException(400, f"File exceeds {MAX_UPLOAD_MB} MB limit")
            fh.write(chunk)

    req = SeparationRequest(
        input_path=dest,
        output_dir=job_dir,
        model_id=info.id,
        stems=wanted,
        output_format=output_format,
        overlap=overlap if overlap else 0.25,
        shifts=shifts if shifts else 1,
        enhanced=enhanced,
    )
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": 0.0,
            "message": "Queued",
            "filename": file.filename,
            "task": task,
            "tier": tier,
            "model": info.id,
            "model_label": info.label,
            "output_format": output_format,
            "created_at": time.time(),
            "_stem_paths": {},
        }
    threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return JSONResponse({"id": job_id}, status_code=202)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return _job_payload(job_id)


@app.get("/api/jobs/{job_id}/stems/{stem}")
def get_stem(job_id: str, stem: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None or job.get("status") != "done":
            raise HTTPException(404, "stem not ready")
        path = job["_stem_paths"].get(stem)
    if not path or not Path(path).exists():
        raise HTTPException(404, "stem not found")
    fmt = job["output_format"]
    media = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac"}[fmt]
    return FileResponse(path, media_type=media,
                        filename=f"{Path(job['filename']).stem}_{stem}.{fmt}")


@app.get("/api/jobs/{job_id}/download")
def download_all(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None or job.get("status") != "done":
            raise HTTPException(404, "stems not ready")
        paths = dict(job["_stem_paths"])
        name = Path(job["filename"]).stem
    zip_path = JOBS_DIR / job_id / f"{name}_stems.zip"
    if not zip_path.exists():
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for stem, p in paths.items():
                zf.write(p, f"{name}_{stem}{Path(p).suffix}")
    return FileResponse(zip_path, media_type="application/zip",
                        filename=f"{name}_stems.zip")


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if job is None:
        raise HTTPException(404, "job not found")
    shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)
    for p in UPLOAD_DIR.glob(f"{job_id}.*"):
        p.unlink(missing_ok=True)
    return {"deleted": job_id}


WEB_DIR = BASE_DIR / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


def main():
    import uvicorn

    uvicorn.run("split.server:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
