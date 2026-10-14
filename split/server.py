"""Local HTTP API and the web ui. Binds to loopback only."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, catalog, media, paths, weights
from .jobs import Jobs
from .updates import UpdateError, Updates

TOKEN_HEADER = "x-split-token"
TOKEN_SLOT = '<meta name="split-token" content="">'
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def safe_name(name: str) -> str:
    cleaned = " ".join(_UNSAFE.sub(" ", name).split()).strip(" .")
    return cleaned[:120] or "audio"


def _validate(spec: dict) -> dict:
    task = catalog.TASKS.get(spec.get("task", ""))
    if task is None:
        raise HTTPException(400, f"Unknown task {spec.get('task')!r}")
    tier = spec.get("tier") or task.default_tier
    try:
        task.tier(tier)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    isolate = bool(spec.get("isolate")) and task.isolatable
    allowed = task.stems_for(isolate)
    stems = spec.get("stems") or list(allowed)
    if isinstance(stems, str):
        stems = [s for s in stems.split(",") if s]
    unknown = [s for s in stems if s not in allowed]
    if unknown or not stems:
        raise HTTPException(400, f"Pick stems from {', '.join(allowed)}")
    fmt = spec.get("format") or "wav"
    if fmt not in media.FORMATS:
        raise HTTPException(400, f"Format must be one of {', '.join(media.FORMATS)}")
    return {
        "task": task.id,
        "tier": tier,
        "isolate": isolate,
        "stems": [s for s in allowed if s in stems],
        "format": fmt,
    }


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "The request body is not valid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "The request body must be a JSON object")
    return body


def _reveal(target: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{target}"] if target.is_file() else ["explorer", str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])


def create_app(jobs: Jobs | None = None, token: str | None = None, updates: Updates | None = None) -> FastAPI:
    token = token or secrets.token_urlsafe(24)
    holder: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if jobs is None:
            paths.migrate_legacy_models(catalog.file_names())
        holder["jobs"] = jobs or Jobs()
        holder["updates"] = updates or Updates(on_change=lambda: holder["jobs"].touch())
        holder["jobs"].start()
        holder["updates"].start()
        yield
        holder["updates"].stop()
        holder["jobs"].stop()

    app = FastAPI(title="split", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.state.token = token
    app.state.focus = lambda: None
    app.state.quit = lambda: None

    def open_files(files: list[str]) -> None:
        try:
            store().offer([str(p) for p in media.collect(Path(f) for f in files)])
        except media.MediaError as exc:
            store().offer([], str(exc))

    app.state.open_files = open_files

    def store() -> Jobs:
        return holder["jobs"]

    def snapshot() -> dict:
        return store().snapshot() | {"update": holder["updates"].snapshot()}

    def guard(request: Request) -> None:
        # a custom header forces a cors preflight, which this server never approves
        if not secrets.compare_digest(request.headers.get(TOKEN_HEADER, ""), token):
            raise HTTPException(403, "This request did not come from the Split window")

    def record(job_id: str) -> dict:
        found = store().get(job_id)
        if found is None:
            raise HTTPException(404, "No such job")
        return found

    def output(job_id: str, stem: str) -> tuple[dict, Path]:
        job = record(job_id)
        name = job["outputs"].get(stem)
        path = store().job_dir(job_id) / name if name else None
        if job["status"] != "done" or path is None or not path.is_file():
            raise HTTPException(404, "That stem is not ready")
        return job, path

    @app.get("/", include_in_schema=False)
    def index() -> HTMLResponse:
        html = (paths.web_dir() / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            html.replace(TOKEN_SLOT, f'<meta name="split-token" content="{token}">'),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/catalog")
    def get_catalog() -> dict:
        data = catalog.public()
        for model_id, state in weights.status().items():
            data["models"][model_id].update(state)
        data["formats"] = list(media.FORMATS)
        leftovers = weights.unused()
        data["unused"] = {"count": len(leftovers), "size": sum(p.stat().st_size for p in leftovers)}
        return data

    @app.get("/api/system")
    def system() -> dict:
        snapshot = store().snapshot()
        return {
            "version": __version__,
            "device": snapshot["device"],
            "fatal": snapshot["fatal"],
            "data_dir": str(paths.data_root()),
        }

    @app.get("/api/state")
    def state() -> dict:
        return snapshot()

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        async def stream():
            version = -1
            while not await request.is_disconnected():
                latest = await asyncio.to_thread(store().wait, version, 15.0)
                if latest == version:
                    yield ": idle\n\n"
                    continue
                version = latest
                yield f"data: {json.dumps(snapshot())}\n\n"
                await asyncio.sleep(0.1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )

    @app.post("/api/jobs", dependencies=[Depends(guard)])
    async def create_jobs(request: Request) -> dict:
        created = []
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            form = await request.form()
            spec = _validate(
                {key: form.get(key) for key in ("task", "tier", "stems", "format")}
                | {"isolate": form.get("isolate") in ("1", "true", "on")}
            )
            uploads = [item for item in form.getlist("files") if hasattr(item, "filename")]
            if not uploads:
                raise HTTPException(400, "Attach at least one file")
            inbox = store().root / "uploads"
            inbox.mkdir(exist_ok=True)
            for upload in uploads:
                dest = inbox / f"{uuid.uuid4().hex}{Path(upload.filename or '').suffix.lower()}"
                with dest.open("wb") as fh:
                    while chunk := await upload.read(1 << 20):
                        fh.write(chunk)
                created.append(
                    store().submit(
                        {
                            **spec,
                            "source": str(dest),
                            "owns_source": True,
                            "name": safe_name(Path(upload.filename or "audio").stem),
                        }
                    )
                )
            return {"jobs": created}
        body = await _body(request)
        spec = _validate(body)
        sources = scan(body.get("paths") or [])
        stems = [stem_source(item) for item in body.get("stems_of") or []]
        if not sources and not stems:
            raise HTTPException(400, "Add at least one file")
        for source in sources:
            created.append(store().submit({**spec, "source": str(source), "name": safe_name(source.stem)}))
        for job, path in stems:
            # the stem is copied so the new job keeps its input even after the old job is removed
            inbox = store().root / "uploads"
            inbox.mkdir(exist_ok=True)
            dest = inbox / f"{uuid.uuid4().hex}{path.suffix}"
            shutil.copyfile(path, dest)
            name = safe_name(f"{job['name']} ({path.stem})")
            created.append(store().submit({**spec, "source": str(dest), "owns_source": True, "name": name}))
        return {"jobs": created}

    def scan(entries: list[str]) -> list[Path]:
        try:
            return media.collect(Path(p) for p in entries)
        except media.MediaError as exc:
            raise HTTPException(400, str(exc)) from None

    def stem_source(item: dict) -> tuple[dict, Path]:
        return output(str(item.get("job", "")), str(item.get("stem", "")))

    @app.post("/api/scan", dependencies=[Depends(guard)])
    async def scan_paths(request: Request) -> dict:
        return {"paths": [str(p) for p in scan((await _body(request)).get("paths") or [])]}

    @app.delete("/api/jobs", dependencies=[Depends(guard)])
    def clear_jobs() -> dict:
        return {"deleted": store().clear_finished()}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return record(job_id)

    @app.get("/api/jobs/{job_id}/log")
    def get_log(job_id: str) -> dict:
        record(job_id)
        log = store().job_dir(job_id) / "error.log"
        if not log.is_file():
            raise HTTPException(404, "This job left no error log")
        return {"log": log.read_text(encoding="utf-8", errors="replace")}

    @app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(guard)])
    def cancel_job(job_id: str) -> dict:
        record(job_id)
        return {"cancelled": store().cancel(job_id)}

    @app.post("/api/jobs/{job_id}/retry", dependencies=[Depends(guard)])
    def retry_job(job_id: str) -> dict:
        record(job_id)
        try:
            return store().retry(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.delete("/api/jobs/{job_id}", dependencies=[Depends(guard)])
    def delete_job(job_id: str) -> dict:
        record(job_id)
        try:
            store().delete(job_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"deleted": job_id}

    @app.get("/api/jobs/{job_id}/stems/{stem}")
    def get_stem(job_id: str, stem: str, download: bool = False) -> FileResponse:
        job, path = output(job_id, stem)
        return FileResponse(
            path,
            media_type=media.MEDIA_TYPES[job["format"]],
            filename=f"{job['name']} - {stem}.{job['format']}",
            content_disposition_type="attachment" if download else "inline",
        )

    def original(job_id: str) -> Path:
        job = record(job_id)
        path = store().job_dir(job_id) / job["original"] if job.get("original") else None
        if job["status"] != "done" or path is None or not path.is_file():
            raise HTTPException(404, "This job kept no copy of the original")
        return path

    @app.get("/api/jobs/{job_id}/original")
    def get_original(job_id: str) -> FileResponse:
        return FileResponse(original(job_id), media_type="audio/flac")

    @app.get("/api/jobs/{job_id}/peaks/{stem}")
    def get_peaks(job_id: str, stem: str) -> FileResponse:
        if stem == "original":
            original(job_id)
        else:
            output(job_id, stem)
        path = store().job_dir(job_id) / "peaks" / f"{stem}.json"
        if not path.is_file():
            raise HTTPException(404, "No waveform for that stem")
        return FileResponse(path, media_type="application/json")

    @app.get("/api/jobs/{job_id}/zip")
    def get_zip(job_id: str) -> FileResponse:
        job = record(job_id)
        if job["status"] != "done":
            raise HTTPException(404, "Stems are not ready")
        job_dir = store().job_dir(job_id)
        target = job_dir / "stems.zip"
        if not target.is_file():
            partial = job_dir / "stems.zip.tmp"
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_STORED) as archive:
                for stem, name in job["outputs"].items():
                    archive.write(job_dir / name, f"{job['name']} - {stem}.{job['format']}")
            partial.replace(target)
        return FileResponse(target, media_type="application/zip", filename=f"{job['name']} - stems.zip")

    @app.post("/api/jobs/{job_id}/export", dependencies=[Depends(guard)])
    async def export_job(job_id: str, request: Request) -> dict:
        job = record(job_id)
        folder = Path((await _body(request)).get("folder") or "")
        if job["status"] != "done":
            raise HTTPException(409, "Stems are not ready")
        if not folder.is_dir():
            raise HTTPException(400, "Pick a folder that exists")
        written = []
        for stem, name in job["outputs"].items():
            dest = folder / f"{job['name']} - {stem}.{job['format']}"
            shutil.copyfile(store().job_dir(job_id) / name, dest)
            written.append(str(dest))
        return {"files": written}

    @app.post("/api/jobs/{job_id}/reveal", dependencies=[Depends(guard)])
    def reveal_job(job_id: str) -> dict:
        job = record(job_id)
        folder = store().job_dir(job_id)
        first = next(iter(job["outputs"].values()), None)
        _reveal(folder / first if first else folder)
        return {"revealed": str(folder)}

    @app.post("/api/reveal", dependencies=[Depends(guard)])
    async def reveal(request: Request) -> dict:
        target = Path((await _body(request)).get("path") or "")
        if not target.exists():
            raise HTTPException(404, "Nothing at that path")
        _reveal(target)
        return {"revealed": str(target)}

    @app.post("/api/focus", dependencies=[Depends(guard)])
    async def focus(request: Request) -> dict:
        files = [p for p in (await _body(request)).get("paths") or [] if Path(p).exists()]
        app.state.focus()
        if files:
            app.state.open_files(files)
        return {"focused": True}

    @app.delete("/api/models/unused", dependencies=[Depends(guard)])
    def delete_unused() -> dict:
        return {"freed": weights.remove_unused()}

    @app.post("/api/models/{model_id}/download", dependencies=[Depends(guard)])
    def download_model(model_id: str) -> dict:
        if model_id not in catalog.MODELS:
            raise HTTPException(404, "No such model")
        store().download(model_id)
        return {"queued": model_id}

    @app.post("/api/models/{model_id}/cancel", dependencies=[Depends(guard)])
    def cancel_model(model_id: str) -> dict:
        store().cancel_download(model_id)
        return {"cancelled": model_id}

    @app.delete("/api/models/{model_id}", dependencies=[Depends(guard)])
    def delete_model(model_id: str) -> dict:
        model = catalog.MODELS.get(model_id)
        if model is None:
            raise HTTPException(404, "No such model")
        weights.remove(model)
        return {"deleted": model_id}

    @app.get("/api/update")
    def get_update() -> dict:
        return holder["updates"].snapshot()

    @app.post("/api/update", dependencies=[Depends(guard)])
    def install_update() -> dict:
        if store().busy():
            raise HTTPException(409, "Finish or cancel the queue first, then install the update")
        try:
            holder["updates"].install(os.getpid())
        except UpdateError as exc:
            raise HTTPException(409, str(exc)) from None
        # answer the page before the window closes; the installer waits for this process to exit
        threading.Timer(0.5, app.state.quit).start()
        return {"installing": holder["updates"].snapshot()["version"]}

    app.mount("/", FreshStaticFiles(directory=paths.web_dir()), name="web")
    return app


class FreshStaticFiles(StaticFiles):
    # the webview keeps its http cache across launches; revalidate so an update never runs stale ui code
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def serve(host: str = "127.0.0.1", port: int = 8000, token: str | None = None) -> None:
    import uvicorn

    paths.expose_ffmpeg()
    uvicorn.run(create_app(token=token), host=host, port=port, log_level="warning")
