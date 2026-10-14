import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

BUSY = {"queued", "running"}
JSON_FIELDS = {"settings", "warnings", "chapters"}


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "lecture.db"
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
                    created_at TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                    progress REAL, error TEXT, settings TEXT NOT NULL, warnings TEXT NOT NULL DEFAULT '[]',
                    chapters TEXT NOT NULL DEFAULT '[]', page_count INTEGER, seconds REAL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, stage TEXT NOT NULL, error TEXT
                );
                CREATE TABLE IF NOT EXISTS scenes (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    id TEXT NOT NULL, position INTEGER NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(project_id,id)
                );
                CREATE TABLE IF NOT EXISTS assets (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    scene_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, seconds REAL NOT NULL,
                    PRIMARY KEY(project_id,scene_id,kind)
                );
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def directory(self, project_id: str) -> Path:
        # Parse IDs before path construction, even for internal callers.
        if uuid.UUID(project_id).hex != project_id:
            raise ValueError("プロジェクトIDが不正です")
        return self.root / "projects" / project_id

    def decode(self, row):
        if row is None:
            return None
        item = dict(row)
        for key in JSON_FIELDS:
            if key in item:
                item[key] = json.loads(item[key])
        return item

    def create(self, filename: str, options: dict):
        project_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute("INSERT INTO projects(id,title,filename,created_at,status,stage,settings) VALUES(?,?,?,?,?,?,?)",
                (project_id, filename.removesuffix(".pdf"), filename, now(), "uploaded", "uploaded", json.dumps(options)))
        return self.get(project_id)

    def get(self, project_id: str):
        with self.connect() as conn:
            return self.decode(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    def list_projects(self):
        with self.connect() as conn:
            return [self.decode(row) for row in conn.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT 100")]

    def update(self, project_id: str, **fields):
        allowed = {"title", "status", "stage", "progress", "error", "warnings", "chapters", "page_count", "seconds", "settings"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("不正な更新フィールドです")
        values = [json.dumps(value, ensure_ascii=False) if key in JSON_FIELDS else value for key, value in fields.items()]
        with self.connect() as conn:
            conn.execute(f"UPDATE projects SET {','.join(key + '=?' for key in fields)} WHERE id=?", [*values, project_id])

    def enqueue(self, project_id: str, options: dict, max_queue: int) -> str:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None:
                raise KeyError(project_id)
            if row["status"] in BUSY:
                raise ValueError("この講義はすでに生成中です")
            count = conn.execute("SELECT count(*) FROM projects WHERE status IN ('queued','running')").fetchone()[0]
            if count >= max_queue:
                raise ValueError("待機ジョブの上限に達しました。完了を待ってください")
            job_id = uuid.uuid4().hex
            conn.execute("INSERT INTO jobs(id,project_id,created_at,status,stage) VALUES(?,?,?,?,?)", (job_id, project_id, now(), "queued", "queued"))
            conn.execute("UPDATE projects SET status='queued',stage='queued',progress=NULL,error=NULL,settings=? WHERE id=?", (json.dumps(options), project_id))
        return job_id

    def job(self, job_id: str, status: str, stage: str, error: str | None = None):
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET status=?,stage=?,error=?,finished_at=? WHERE id=?",
                (status, stage, error, now() if status in {"completed", "failed"} else None, job_id))

    def job_history(self, project_id: str):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC", (project_id,))]

    def recover(self):
        with self.connect() as conn:
            error = "アプリの終了により処理が中断されました。保存済み成果物から再試行できます"
            conn.execute("UPDATE projects SET status='failed',progress=NULL,error=? WHERE status='running'", (error,))
            conn.execute("UPDATE jobs SET status='failed',error=?,finished_at=? WHERE status='running'", (error, now()))
            return [(row["project_id"], row["id"]) for row in conn.execute("SELECT id,project_id FROM jobs WHERE status='queued' ORDER BY created_at")]

    def save_scenes(self, project_id: str, scenes: list[dict]):
        with self.connect() as conn:
            conn.execute("DELETE FROM scenes WHERE project_id=?", (project_id,))
            conn.executemany("INSERT INTO scenes VALUES(?,?,?,?)", [(project_id, s["id"], i, json.dumps(s, ensure_ascii=False)) for i, s in enumerate(scenes)])

    def save_audio(self, project_id: str, scene_id: str, audio: dict):
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO assets VALUES(?,?,?,?,?)", (project_id, scene_id, "audio", audio["path"], audio["audio_seconds"]))

    def delete(self, project_id: str):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM projects WHERE id=?", (project_id,)).fetchone()
            if row and row["status"] in BUSY:
                raise ValueError("生成中の講義は削除できません")
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
