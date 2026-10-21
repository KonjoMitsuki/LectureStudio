import asyncio
import hashlib
import json
from contextlib import suppress
from pathlib import Path
from time import monotonic
import httpx
from jsonschema import ValidationError
from ..config import settings
from ..models import GenerationSettings, validate_lecture
from ..storage import Store
from .ai_analyzer import CodexCLIAnalyzer
from .coverage import validate_content_plan, validate_coverage
from .pdf_parser import parse_pdf
from .voicevox import Voicevox
from .render_service import render_video
from .diagnostics import GenerationLog, current_log, duration, excerpt


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
        interrupted = [(row, self.store.job_history(row["id"])[0]) for row in self.store.list_projects()
            if row["status"] == "running"]
        for job in self.store.recover():
            self.queue.put_nowait(job)
        for row, job in interrupted:
            log = GenerationLog(self.store, row["id"], job["id"])
            if state := self.store.activity(row["id"]):
                log.state = state
            log.state["stage"] = row["stage"]
            log.emit("アプリの終了により生成が中断されました。保存済みの工程から再試行できます", level="error", task=True)
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
        log = GenerationLog(self.store, project_id, job_id)
        log.emit("生成を受け付けました。ほかの処理があれば完了を待ちます", task=True)
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
        log = GenerationLog(self.store, project_id, job_id)
        token = current_log.set(log)
        heartbeat = asyncio.create_task(log.heartbeat())
        def step(value, progress=None):
            nonlocal stage
            stage = value
            self.store.update(project_id, status="running", stage=value, progress=progress, error=None)
            self.store.job(job_id, "running", value)
            log.begin_stage(value)
        try:
            options = GenerationSettings.model_validate(self.store.get(project_id)["settings"])
            log.emit("動画の生成を開始しました", details=[
                f"動画の長さの目安：{duration(options.target_seconds)} / 理解確認クイズ：{options.quiz_count}問",
                f"AIの待機上限：1回につき{duration(settings.codex_timeout)} / 動画書き出しの待機上限：{duration(settings.render_timeout)}"])
            step("pdf")
            document_path = workdir / "document.json"
            if document_path.exists():
                document = json.loads(document_path.read_text())
                log.emit("保存済みのPDF読み取り結果を再利用します")
            else:
                document = await asyncio.to_thread(parse_pdf, workdir / "source.pdf", workdir / "pages")
                save_json(document_path, document)
            self.store.update(project_id, page_count=document["page_count"], warnings=document["warnings"])
            log.finish_stage(f"PDFを読み取れました：{document['page_count']}ページ・{sum(len(p['text']) for p in document['pages']):,}文字",
                [f"p.{p['number']}：{excerpt(' / '.join(p.get('headings', [])) or p['text'])}" for p in document["pages"][:3]]
                + [f"確認事項：{len(document['warnings'])}件 / 保存先：document.json・pages/"])
            step("ai")
            fingerprint = hashlib.sha256(json.dumps({"settings": options.model_dump(), "visual_script_version": 4}, sort_keys=True).encode()).hexdigest()
            script = workdir / "lecture.json"
            marker = workdir / "settings.sha256"
            lecture = None
            if script.exists() and marker.exists() and marker.read_text() == fingerprint:
                try:
                    lecture = validate_lecture(json.loads(script.read_text()), [p["number"] for p in document["pages"]])
                    plan_path = workdir / "ai/content_plan.json"
                    if plan_path.exists():
                        validate_coverage(lecture, validate_content_plan(json.loads(plan_path.read_text()), document))
                    log.emit("保存済みの台本を検証し、再利用します", level="success")
                except (ValueError, ValidationError):
                    # Keep the invalid artifact for diagnosis, but do not retry it forever.
                    script.replace(workdir / "lecture.invalid.json")
                    lecture = None
                    log.emit("保存済みの台本が検証に通らなかったため、作り直します", level="warning")
            if lecture is None:
                lecture = await self.analyzer.analyze(document, options, workdir / "ai")
                save_json(script, lecture.model_dump())
                marker.write_text(fingerprint)
            warnings = document["warnings"] + lecture.warnings
            self.store.update(project_id, title=lecture.title, warnings=warnings)
            self.store.save_scenes(project_id, [s.model_dump() for s in lecture.scenes])
            log.finish_stage(f"構成・台本が完成しました：{len(lecture.scenes)}シーン",
                [f"タイトル：{lecture.title}", f"学習内容：{' / '.join(lecture.learning_goals)}"]
                + [f"シーン{i + 1}「{s.title}」：{excerpt(s.narration)}" for i, s in enumerate(lecture.scenes[:3])]
                + ["台本全文：lecture.json（画面の「台本の全文」から確認できます）"])
            step("audio", 0)
            log.emit("音声を作るサービスに接続しています", task=True)
            speakers = await self.voice.speakers()
            if options.speaker not in {s["id"] for speaker in speakers for s in speaker["styles"]}:
                raise ValueError("選択したVOICEVOX話者が存在しません")
            log.emit("音声サービスへの接続と、選択した話者を確認できました", level="success")
            audio = []
            for i, scene in enumerate(lecture.scenes):
                log.emit(f"音声を作成中：{i + 1}/{len(lecture.scenes)}「{scene.title}」", task=True)
                item = await self.voice.synthesize(scene.narration, options.speaker, options.speed, self.store.root / "audio")
                audio.append(item)
                self.store.save_audio(project_id, scene.id, item)
                self.store.update(project_id, progress=(i + 1) / len(lecture.scenes))
                log.emit(f"音声ができました：{i + 1}/{len(lecture.scenes)}（{duration(item['audio_seconds'])}）", level="success")
            save_json(workdir / "audio.json", audio)
            actual_seconds = sum(a["duration_in_frames"] for a in audio) / 30 + sum(s.thinking_seconds for s in lecture.scenes)
            minimum, maximum = {"test": (40, 100), "short": (300, 600), "medium": (900, 1200), "long": (1800, 2400)}[options.duration]
            if not minimum <= actual_seconds <= maximum:
                if actual_seconds > maximum:
                    warnings.append(f"資料全体の解説を優先したため、動画長は{actual_seconds / 60:.1f}分となり、指定した目安を超えています")
                else:
                    warnings.append(f"実音声の動画長は{actual_seconds / 60:.1f}分です。指定した目安の範囲から外れています")
                self.store.update(project_id, warnings=warnings)
                log.emit(warnings[-1], level="warning")
            log.finish_stage(f"全{len(audio)}シーンの音声が揃いました。動画の長さは約{duration(actual_seconds)}です",
                ["保存先：audio.json（音声の一覧と長さ）"])
            step("render", 0)
            last_render_progress = -10
            last_render_value = -1
            def render_progress(value):
                nonlocal last_render_progress, last_render_value
                self.store.update(project_id, progress=value)
                percent = min(100, max(0, int(value * 100)))
                if value > last_render_value:
                    last_render_value = value
                    log.progress(f"動画を書き出しています：{percent}%")
                if percent >= last_render_progress + 10:
                    last_render_progress = percent
                    log.emit(f"動画の書き出しが進みました：{percent}%", task=True)
            result = await self.renderer(lecture.model_dump(), audio, options.style, workdir,
                render_progress)
            save_json(workdir / "result.json", result)
            log.finish_stage(f"動画を書き出せました：{duration(result['seconds'])}",
                [f"保存先：video.mp4 / 大きさ：{(workdir / 'video.mp4').stat().st_size / 1024 / 1024:.1f} MB"])
            self.store.update(project_id, status="completed", stage="completed", progress=1, error=None,
                seconds=result["seconds"], chapters=result["chapters"])
            self.store.job(job_id, "completed", "completed")
            (workdir / "error.json").unlink(missing_ok=True)
            log.state["stage"] = "completed"
            log.emit(f"すべての工程が完了しました（全体の所要時間：{duration(monotonic() - log.started)}）",
                level="success", task=True)
        except asyncio.CancelledError:
            message = "処理が中断されました。再試行すると保存済み成果物を再利用します"
            self.store.update(project_id, status="failed", stage=stage, progress=None, error=message)
            self.store.job(job_id, "failed", stage, message)
            log.emit(message, level="error", task=True)
            raise
        except Exception as exc:
            if isinstance(exc, httpx.HTTPError):
                message = ("音声サービスの応答が時間内に届きませんでした。ENGINEの状態を確認し、再試行してください"
                    if isinstance(exc, httpx.TimeoutException) else
                    "VOICEVOXに接続または音声合成できません。ENGINEの起動と話者を確認してください")
            elif isinstance(exc, (ValueError, RuntimeError)):
                message = str(exc)[:400]
            else:
                message = f"{stage}工程で{type(exc).__name__}が発生しました。保存済みの診断情報を確認してください"
            save_json(workdir / "error.json", {"stage": stage, "type": type(exc).__name__, "message": message})
            self.store.update(project_id, status="failed", stage=stage, progress=None, error=message)
            self.store.job(job_id, "failed", stage, message)
            log.emit(message, level="error", task=True, details=[f"エラーの種類：{type(exc).__name__}",
                "ここまでに保存した台本・音声は、再試行時に確認して再利用します"])
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            current_log.reset(token)
