import asyncio
import fcntl
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import ROOT, settings
from .models import GenerationSettings, StrictModel
from .services.pipeline import Pipeline
from .services.voicevox import Voicevox
from .storage import Store


class GenerateRequest(StrictModel):
    settings: GenerationSettings | None = None


class BodyLimit:
    """Bound multipart bytes while receiving, before UploadFile spools the body."""
    def __init__(self, app, maximum: int):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        received = 0
        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.maximum:
                raise HTTPException(413, "アップロード容量の上限を超えました")
            return message
        await self.app(scope, limited_receive, send)


def create_app(data_dir: Path | None = None, pipeline_factory=Pipeline) -> FastAPI:
    store = Store(data_dir or settings.data_dir)
    pipeline = pipeline_factory(store)
    @asynccontextmanager
    async def lifespan(app):
        lock = (store.root / "worker.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError("同じデータフォルダのLecture Studioは1プロセスだけで起動してください")
        await pipeline.start()
        try:
            yield
        finally:
            await pipeline.stop()
            lock.close()
    app = FastAPI(title="Lecture Studio", version="0.1.0", lifespan=lifespan)
    app.state.store, app.state.pipeline = store, pipeline
    app.add_middleware(BodyLimit, maximum=(settings.max_upload_mb + 1) * 1024 * 1024)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            allowed = {"http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:5173", "http://localhost:5173"}
            if (origin is not None and origin not in allowed) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "外部サイトからの変更要求は許可されていません"}, status_code=403)
        return await call_next(request)

    def project(project_id: str):
        try:
            valid = uuid.UUID(project_id).hex == project_id
        except ValueError:
            valid = False
        row = store.get(project_id) if valid else None
        if row is None:
            raise HTTPException(404, "講義が見つかりません")
        return row

    @app.get("/api/health")
    async def health():
        voice_ready = True
        try:
            await asyncio.wait_for(Voicevox().speakers(), 3)
        except Exception:
            voice_ready = False
        return {"codex_available": shutil.which(settings.codex_bin) is not None,
            "ffmpeg_available": shutil.which("ffprobe") is not None, "voicevox_ready": voice_ready}

    @app.get("/api/speakers")
    async def speakers():
        try:
            return [{"id": style["id"], "name": f"{speaker['name']}（{style['name']}）", "credit": f"VOICEVOX:{speaker['name']}"}
                for speaker in await Voicevox().speakers() for style in speaker["styles"]]
        except Exception as exc:
            raise HTTPException(503, "VOICEVOX ENGINEに接続できません") from exc

    @app.get("/api/projects")
    def list_projects():
        return store.list_projects()

    @app.post("/api/projects", status_code=201)
    async def upload(file: UploadFile = File(...), options: str = Form("{}")):
        name = Path((file.filename or "").replace("\\", "/")).name
        if not name.lower().endswith(".pdf") or len(name) > 180:
            raise HTTPException(400, "拡張子が.pdfのファイルを選択してください")
        try:
            opts = GenerationSettings.model_validate_json(options)
        except ValueError as exc:
            raise HTTPException(422, "生成設定が不正です") from exc
        first = await file.read(65536)
        if not first.startswith(b"%PDF-"):
            raise HTTPException(400, "ファイルの実体がPDFではありません")
        row = store.create(name, opts.model_dump())
        directory = store.directory(row["id"])
        directory.mkdir(parents=True)
        total = 0
        try:
            with (directory / "source.pdf").open("wb") as output:
                chunk = first
                while chunk:
                    total += len(chunk)
                    if total > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f"PDFは{settings.max_upload_mb}MB以下にしてください")
                    await asyncio.to_thread(output.write, chunk)
                    chunk = await file.read(65536)
        except BaseException:
            store.delete(row["id"])
            shutil.rmtree(directory)
            raise
        finally:
            await file.close()
        return row

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        return {**project(project_id), "jobs": store.job_history(project_id)}

    @app.post("/api/projects/{project_id}/generate", status_code=202)
    async def generate(project_id: str, body: GenerateRequest | None = None):
        row = project(project_id)
        opts = body.settings if body and body.settings else GenerationSettings.model_validate(row["settings"])
        try:
            job_id = pipeline.submit(project_id, opts)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"job_id": job_id, "project_id": project_id}

    @app.delete("/api/projects/{project_id}", status_code=204)
    async def delete(project_id: str):
        project(project_id)
        try:
            store.delete(project_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await asyncio.to_thread(shutil.rmtree, store.directory(project_id), True)

    @app.get("/api/projects/{project_id}/video")
    def video(project_id: str, download: bool = False):
        row = project(project_id)
        path = store.directory(project_id) / "video.mp4"
        if row["status"] != "completed" or not path.is_file():
            raise HTTPException(409, "動画はまだ完成していません")
        return FileResponse(path, media_type="video/mp4", filename="lecture.mp4" if download else None,
            headers={"Cache-Control": "no-store"})

    @app.get("/api/projects/{project_id}/pages/{number}")
    def page_image(project_id: str, number: int):
        row = project(project_id)
        if not row["page_count"] or not 1 <= number <= row["page_count"]:
            raise HTTPException(404, "ページが見つかりません")
        return FileResponse(store.directory(project_id) / "pages" / f"page_{number:03}.png", media_type="image/png")

    @app.get("/api/projects/{project_id}/source")
    def source(project_id: str):
        project(project_id)
        return FileResponse(store.directory(project_id) / "source.pdf", media_type="application/pdf", filename="source.pdf")

    @app.get("/api/projects/{project_id}/lecture")
    def script(project_id: str):
        project(project_id)
        path = store.directory(project_id) / "lecture.json"
        if not path.is_file():
            raise HTTPException(404, "台本はまだ生成されていません")
        return JSONResponse(json.loads(path.read_text()))

    @app.get("/api/projects/{project_id}/diagnostics")
    def diagnostics(project_id: str):
        row = project(project_id)
        directory = store.directory(project_id)
        artifacts = [p.name for p in directory.iterdir() if p.is_file()]
        return {"status": row["status"], "stage": row["stage"], "error": row["error"], "artifacts": artifacts,
            "jobs": store.job_history(project_id)}

    built = ROOT / "frontend/dist"
    if built.exists():
        app.mount("/", StaticFiles(directory=built, html=True), name="frontend")
    return app


app = create_app()
