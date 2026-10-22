"""Readable, bounded generation records. Never persist raw CLI output or credentials."""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from time import monotonic
from ..storage import Store, now

STAGES = {"queued": "順番待ち", "pdf": "PDFの読み取り", "ai": "構成・台本の作成",
    "audio": "音声の作成", "render": "動画の書き出し", "completed": "完成"}
HEARTBEAT_SECONDS = 15
current_log: ContextVar["GenerationLog | None"] = ContextVar("generation_log", default=None)


def excerpt(value: str, maximum: int = 180) -> str:
    text = " ".join(value.split())
    return text[:maximum] + ("…" if len(text) > maximum else "")


def duration(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f"{seconds // 60}分{seconds % 60:02}秒" if seconds >= 60 else f"{seconds}秒"


def record(message: str, *, level: str = "info", details: list[str] | None = None, task: bool = False):
    if log := current_log.get():
        log.emit(message, level=level, details=details, task=task)


class GenerationLog:
    def __init__(self, store: Store, project_id: str, job_id: str):
        self.store, self.project_id = store, project_id
        self.process = None
        self.started = self.stage_started = monotonic()
        self.last_event_save = 0.0
        self.state = {"job_id": job_id, "stage": "queued", "task": "生成の開始を待っています",
            "started_at": now(), "stage_started_at": now(), "heartbeat_at": now(),
            "last_activity_at": now(), "completed_stages": [], "process": None, "ai": None}

    def ai_progress(self, phase: str, completed: int, total: int):
        ai = self.state.get("ai") or {"event_count": 0, "usage": {}, "calls": 0}
        ai.update(phase=phase, completed=completed, total=total)
        self.state["ai"] = ai
        self.store.save_activity(self.project_id, self.state)

    def ai_event(self, event: dict):
        ai = self.state.get("ai") or {"phase": "generation", "completed": 0, "total": 1,
            "event_count": 0, "usage": {}, "calls": 0}
        ai.update(event_count=ai["event_count"] + 1, last_event=event["type"], last_event_at=now())
        if event["type"] == "turn.started":
            ai["calls"] += 1
        if event["type"] == "turn.completed" and event.get("usage"):
            for key, value in event["usage"].items():
                ai["usage"][key] = ai["usage"].get(key, 0) + value
        self.state["ai"] = ai
        self.state["last_activity_at"] = now()
        # Persist terminal events immediately, throttle frequent item updates.
        if monotonic() - self.last_event_save >= 1 or event["type"] in {"turn.started", "turn.completed", "turn.failed", "error"}:
            self.store.save_activity(self.project_id, self.state)
            self.last_event_save = monotonic()

    def emit(self, message: str, *, level: str = "info", details: list[str] | None = None, task: bool = False):
        timestamp = now()
        self.state.update(heartbeat_at=timestamp, last_activity_at=timestamp)
        if task:
            self.state["task"] = excerpt(message, 240)
        event = {"created_at": timestamp, "stage": self.state["stage"], "level": level,
            "message": excerpt(message, 500), "details": [excerpt(s, 500) for s in (details or [])[:10]]}
        self.store.save_activity(self.project_id, self.state, event)

    def begin_stage(self, stage: str):
        self.stage_started = monotonic()
        self.state.update(stage=stage, stage_started_at=now(), process=None)
        self.emit(f"{STAGES[stage]}を開始しました", task=True)

    def progress(self, message: str):
        # Keep the live progress current without adding a log entry for every percent.
        self.state.update(task=excerpt(message, 240), last_activity_at=now())

    def finish_stage(self, message: str, details: list[str] | None = None):
        self.state["completed_stages"].append(self.state["stage"])
        self.emit(f"{message}（所要時間：{duration(monotonic() - self.stage_started)}）",
            level="success", details=details)

    async def heartbeat(self):
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            self.state["heartbeat_at"] = now()
            if self.process and self.state["process"]:
                self.state["process"]["alive"] = self.process.returncode is None
            self.store.save_activity(self.project_id, self.state)

    def process_started(self, process, timeout: float):
        self.process = process
        self.state["process"] = {"pid": process.pid, "started_at": now(), "last_output_at": None,
            "timeout_seconds": timeout, "status": "running", "alive": True, "output_bytes": 0}
        self.emit(f"外部の生成処理を起動しました（待機上限：{duration(timeout)}）")

    def process_output(self, size: int = 0):
        if self.state["process"]:
            self.state["process"]["last_output_at"] = now()
            self.state["process"]["output_bytes"] += size

    def process_finished(self, status: str, code: int | None):
        if self.state["process"]:
            self.state["process"].update(status=status, exit_code=code, alive=False, finished_at=now())
        messages = {"completed": "外部の処理が終了しました", "failed": "外部の処理がエラーで終了しました",
            "timeout": "待機上限に達したため、外部の処理を停止しました", "cancelled": "外部の処理を中断しました"}
        self.emit(messages[status], level="info" if status == "completed" else "warning",
            details=[f"終了コード：{code}"] if code is not None else [])


def activity_snapshot(activity: dict | None, row: dict, latest_job: dict | None):
    # Old attempts must never look like live activity for a newly queued job.
    if not activity or not latest_job or activity["job_id"] != latest_job["id"]:
        return None
    timestamp = datetime.now(timezone.utc)
    def age(value):
        return max(0, (timestamp - datetime.fromisoformat(value)).total_seconds()) if value else None
    finished_at = latest_job["finished_at"]
    end = datetime.fromisoformat(finished_at) if finished_at else timestamp
    process = activity.get("process")
    return {**activity, "running": row["status"] == "running",
        "elapsed_seconds": max(0, (end - datetime.fromisoformat(activity["started_at"])).total_seconds()),
        "stage_elapsed_seconds": max(0, (end - datetime.fromisoformat(activity["stage_started_at"])).total_seconds()),
        "heartbeat_age_seconds": age(activity["heartbeat_at"]),
        "activity_age_seconds": age(activity["last_activity_at"]),
        "process_elapsed_seconds": max(0, ((datetime.fromisoformat(process["finished_at"]) if process.get("finished_at") else end)
            - datetime.fromisoformat(process["started_at"])).total_seconds()) if process else None,
        "output_age_seconds": age(process["last_output_at"]) if process else None}


def format_event(event: dict) -> str:
    labels = {"info": "進行", "success": "成功", "warning": "確認", "error": "失敗"}
    stamp = datetime.fromisoformat(event["created_at"]).astimezone(timezone(timedelta(hours=9))).strftime("%Y/%m/%d %H:%M:%S")
    heading = f"[{stamp}] [試行 {event['job_id'][:8]}] {labels[event['level']]} / {STAGES[event['stage']]}：{event['message']}\n"
    return heading + "".join(f"  ・{line}\n" for line in event["details"])
