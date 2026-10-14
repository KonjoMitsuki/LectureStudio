import asyncio
import hashlib
import json
from pathlib import Path
import httpx
from jsonschema import ValidationError
from ..config import settings
from ..models import GenerationSettings, validate_lecture
from ..storage import Store
from .ai_analyzer import CodexCLIAnalyzer
from .pdf_parser import parse_pdf
from .voicevox import Voicevox
from .render_service import render_video


def save_json(path: Path, value: dict | list):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


class Pipeline:
    def __init__(self, store: Store, analyzer=None, voice=None, renderer=None):
        self.store = store
        self.analyzer = analyzer or CodexCLIAnalyzer()
        self.voice = voice or Voicevox()
        self.renderer = renderer or render_video
        self.queue = asyncio.Queue()
        self.task = None

    async def start(self):
        for job in self.store.recover():
            self.queue.put_nowait(job)
        self.task = asyncio.create_task(self.worker())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def submit(self, project_id: str, options: GenerationSettings):
        job_id = self.store.enqueue(project_id, options.model_dump(), settings.max_queue)
        self.queue.put_nowait((project_id, job_id))
        return job_id

    async def worker(self):
        while True:
            project_id, job_id = await self.queue.get()
            try:
                await self.run(project_id, job_id)
            finally:
                self.queue.task_done()

    async def run(self, project_id: str, job_id: str):
        workdir = self.store.directory(project_id)
        stage = "pdf"
        options = GenerationSettings.model_validate(self.store.get(project_id)["settings"])
        def step(value, progress=None):
            nonlocal stage
            stage = value
            self.store.update(project_id, status="running", stage=value, progress=progress, error=None)
            self.store.job(job_id, "running", value)
        try:
            step("pdf")
            document_path = workdir / "document.json"
            if document_path.exists():
                document = json.loads(document_path.read_text())
            else:
                document = await asyncio.to_thread(parse_pdf, workdir / "source.pdf", workdir / "pages")
                save_json(document_path, document)
            self.store.update(project_id, page_count=document["page_count"], warnings=document["warnings"])
            step("ai")
            fingerprint = hashlib.sha256(json.dumps(options.model_dump(), sort_keys=True).encode()).hexdigest()
            script = workdir / "lecture.json"
            marker = workdir / "settings.sha256"
            lecture = None
            if script.exists() and marker.exists() and marker.read_text() == fingerprint:
                try:
                    lecture = validate_lecture(json.loads(script.read_text()), [p["number"] for p in document["pages"]])
                except (ValueError, ValidationError):
                    # Keep the invalid artifact for diagnosis, but do not retry it forever.
                    script.replace(workdir / "lecture.invalid.json")
            if lecture is None:
                lecture = await self.analyzer.analyze(document, options, workdir / "ai")
                save_json(script, lecture.model_dump())
                marker.write_text(fingerprint)
            warnings = document["warnings"] + lecture.warnings
            self.store.update(project_id, title=lecture.title, warnings=warnings)
            self.store.save_scenes(project_id, [s.model_dump() for s in lecture.scenes])
            step("audio", 0)
            speakers = await self.voice.speakers()
            if options.speaker not in {s["id"] for speaker in speakers for s in speaker["styles"]}:
                raise ValueError("選択したVOICEVOX話者が存在しません")
            audio = []
            for i, scene in enumerate(lecture.scenes):
                item = await self.voice.synthesize(scene.narration, options.speaker, options.speed, self.store.root / "audio")
                audio.append(item)
                self.store.save_audio(project_id, scene.id, item)
                self.store.update(project_id, progress=(i + 1) / len(lecture.scenes))
            save_json(workdir / "audio.json", audio)
            actual_seconds = sum(a["duration_in_frames"] for a in audio) / 30
            minimum, maximum = {"test": (40, 100), "short": (300, 600), "medium": (900, 1200), "long": (1800, 2400)}[options.duration]
            if not minimum <= actual_seconds <= maximum:
                warnings.append(f"実音声の動画長は{actual_seconds / 60:.1f}分です。指定した目安の範囲から外れています")
                self.store.update(project_id, warnings=warnings)
            step("render", 0)
            result = await self.renderer(lecture.model_dump(), audio, options.style, workdir,
                lambda value: self.store.update(project_id, progress=value))
            save_json(workdir / "result.json", result)
            self.store.update(project_id, status="completed", stage="completed", progress=1, error=None,
                seconds=result["seconds"], chapters=result["chapters"])
            self.store.job(job_id, "completed", "completed")
        except asyncio.CancelledError:
            message = "処理が中断されました。再試行すると保存済み成果物を再利用します"
            self.store.update(project_id, status="failed", stage=stage, progress=None, error=message)
            self.store.job(job_id, "failed", stage, message)
            raise
        except Exception as exc:
            if isinstance(exc, httpx.HTTPError):
                message = "VOICEVOXに接続または音声合成できません。ENGINEの起動と話者を確認してください"
            elif isinstance(exc, (ValueError, RuntimeError)):
                message = str(exc)[:400]
            else:
                message = f"{stage}工程で{type(exc).__name__}が発生しました。保存済みの診断情報を確認してください"
            save_json(workdir / "error.json", {"stage": stage, "type": type(exc).__name__, "message": message})
            self.store.update(project_id, status="failed", stage=stage, progress=None, error=message)
            self.store.job(job_id, "failed", stage, message)
