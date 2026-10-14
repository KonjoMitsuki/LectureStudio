import asyncio
import json
import os
from pathlib import Path
from typing import Protocol
from jsonschema import ValidationError
from ..config import ROOT, settings
from ..models import GenerationSettings, Lecture, validate_lecture, write_schema
from .process import run_process


class LectureAnalyzer(Protocol):
    async def analyze(self, document: dict, options: GenerationSettings, workdir: Path) -> Lecture: ...


class CodexCLIAnalyzer:
    def command(self, schema: Path, output: Path) -> list[str]:
        return [settings.codex_bin, "-a", "never", "exec", "--ignore-user-config", "--ephemeral",
                "--skip-git-repo-check", "--sandbox", "read-only", "--json",
                "--disable", "shell_tool", "--disable", "apps", "--disable", "plugins",
                "--disable", "browser_use", "--disable", "computer_use", "--disable", "multi_agent",
                "--disable", "skill_search", "-c", 'web_search="disabled"',
                "--disable", "view_image", "--disable", "image_generation", "--disable", "goals", "--disable", "memories",
                "-c", "project_doc_max_bytes=0", "-c", "mcp_servers={}",
                "-c", 'forced_login_method="chatgpt"',
                "--output-schema", str(schema), "--output-last-message", str(output), "-"]

    async def analyze(self, document: dict, options: GenerationSettings, workdir: Path) -> Lecture:
        workdir.mkdir(parents=True, exist_ok=True)
        schema = workdir / "schema.json"
        write_schema(schema)
        base_prompt = (ROOT / "prompts/analyze.txt").read_text()
        source = {"pages": [{"number": p["number"], "text": p["text"]} for p in document["pages"]]}
        prompt = f"{base_prompt}\nGENERATION_SETTINGS={options.model_dump_json()}\n目標秒数={options.target_seconds}\n"
        prompt += "3〜4シーンで約1分。" if options.duration == "test" else f"8〜24シーンで合計約{round(options.target_seconds / 60)}分。"
        prompt += "\nSOURCE_DATA=" + json.dumps(source, ensure_ascii=False)
        env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
        # A single retry only for invalid structured output, never for auth/quota/network failures.
        for attempt in range(2):
            output = workdir / f"answer_{attempt}.json"
            output.unlink(missing_ok=True)
            try:
                code, stdout, stderr = await run_process(self.command(schema, output), cwd=workdir,
                    timeout=settings.codex_timeout, stdin=prompt, env=env)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("Codexの実行がタイムアウトしました。認証・利用制限・接続を確認して再試行してください") from exc
            events = []
            forbidden = False
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                item = event.get("item", {})
                item_type = item.get("type")
                if item_type and item_type not in {"agent_message", "reasoning", "plan"}:
                    forbidden = True
                # Persist metadata, never PDF text, generated narration, tokens, or prompts in logs.
                events.append({"type": event.get("type"), "item_type": item_type, "usage": event.get("usage")})
            (workdir / f"events_{attempt}.json").write_text(json.dumps(events, indent=2))
            if forbidden:
                raise RuntimeError("Codexが禁止されたツール呼び出しを出力しました。処理を停止しました")
            if code or not output.exists():
                # Raw stderr may contain account or file details; expose only known error categories.
                category = "認証" if any(w in stderr.lower() for w in ["login", "401", "auth"]) else "CLI起動・接続・利用制限"
                (workdir / "failure.json").write_text(json.dumps({"exit_code": code, "category": category}))
                raise RuntimeError(f"Codexの{category}エラー（終了コード{code}）。codex login statusとCLIバージョンを確認してください")
            try:
                return validate_lecture(json.loads(output.read_text()), [p["number"] for p in document["pages"]])
            except (ValueError, ValidationError) as exc:
                if attempt:
                    raise ValueError("AIのJSONがスキーマ・参照・レイアウト検証に失敗しました。保存済みanswer JSONを確認してください") from exc
                prompt += "\n直前の応答は構造または参照検証に失敗しました。実在ページ、ID、図解必須項目とスキーマを再確認して完全なJSONを再生成してください。"
        raise AssertionError("unreachable")
