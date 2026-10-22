from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LECTURE_", env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    voicevox_url: str = "http://127.0.0.1:50021"
    voice_concurrency: int = Field(default=2, ge=1, le=8)
    codex_bin: str = "codex"
    codex_timeout: int = Field(default=900, ge=1)
    plan_chunk_pages: int = Field(default=3, ge=1, le=20)
    chapter_topics: int = Field(default=6, ge=1, le=20)
    chunk_text_chars: int = Field(default=12000, ge=1000, le=100000)
    manim_python: str = ""
    manim_timeout: int = Field(default=600, ge=1)
    render_timeout: int = 7200
    render_concurrency: int = 2
    chromium_path: str | None = None
    max_upload_mb: int = 30
    max_pages: int = 100
    max_text_chars: int = 100_000
    max_queue: int = 10


settings = Settings()
