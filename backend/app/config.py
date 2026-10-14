from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LECTURE_", env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    voicevox_url: str = "http://127.0.0.1:50021"
    codex_bin: str = "codex"
    codex_timeout: int = 900
    render_timeout: int = 7200
    render_concurrency: int = 2
    chromium_path: str | None = None
    max_upload_mb: int = 30
    max_pages: int = 100
    max_text_chars: int = 100_000
    max_queue: int = 10


settings = Settings()
