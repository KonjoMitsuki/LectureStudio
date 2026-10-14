import asyncio
import json
import os
from pathlib import Path
from typing import Callable, Protocol, TypeVar
from jsonschema import ValidationError
from ..config import ROOT, settings
from ..models import ContentPlan, GenerationSettings, Lecture, StrictModel, validate_lecture, write_schema
from .process import run_process
from .coverage import coverage_warnings, validate_content_plan, validate_coverage

T = TypeVar("T", bound=StrictModel)


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
        source = {"pages": [{"number": p["number"], "text": p["text"], "has_images": bool(p.get("images"))} for p in document["pages"]]}
        source_json = json.dumps(source, ensure_ascii=False)
        plan_path = workdir / "content_plan.json"
        plan = None
        if plan_path.exists():
            try:
                plan = validate_content_plan(json.loads(plan_path.read_text()), document)
            except (ValueError, ValidationError):
                pass
        if plan is None:
            plan_prompt = (ROOT / "prompts/plan.txt").read_text() + "\nSOURCE_DATA=" + source_json
            plan = await self._generate(ContentPlan, lambda raw: validate_content_plan(raw, document),
                plan_prompt, workdir, "plan_")
            plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        base_prompt = (ROOT / "prompts/analyze.txt").read_text()
        prompt = f"{base_prompt}\nGENERATION_SETTINGS={options.model_dump_json()}\n目標秒数（目安）={options.target_seconds}\n"
        prompt += "シーン数は資料の全解説項目に必要な数にしてください（最大160シーン）。時間やシーン数を減らすための内容省略は禁止です。"
        prompt += f"\n理解確認クイズは{options.quiz_count}問。問題・思考時間・解説を含めて時間を見積もり、全項目の解説を優先してください。"
        prompt += "\nSOURCE_PLAN=" + plan.model_dump_json()
        prompt += "\nSOURCE_DATA=" + source_json

        def validate_script(raw: dict) -> Lecture:
            lecture = validate_lecture(raw, [p["number"] for p in document["pages"]])
            if sum(scene.kind == "quiz" for scene in lecture.scenes) != options.quiz_count:
                raise ValueError("指定した問題数のクイズと解説を組み込んでください")
            validate_coverage(lecture, plan)
            return lecture

        lecture = await self._generate(Lecture, validate_script, prompt, workdir)
        lecture.warnings = (coverage_warnings(plan, document) + lecture.warnings)[:12]
        report = {"total_topics": len(plan.topics), "covered_topics": len(lecture.coverage),
            "pages": [page.model_dump() for page in plan.pages],
            "topics": [topic.model_dump() for topic in plan.topics],
            "coverage": [entry.model_dump() for entry in lecture.coverage]}
        (workdir.parent / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return lecture

    async def _generate(self, model: type[T], validate: Callable[[dict], T], prompt: str,
            workdir: Path, prefix: str = "") -> T:
        schema = workdir / f"{prefix}schema.json"
        write_schema(schema, model)
        env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
        # A single retry only for invalid structured output, never for auth/quota/network failures.
        for attempt in range(2):
            output = workdir / f"{prefix}answer_{attempt}.json"
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
            (workdir / f"{prefix}events_{attempt}.json").write_text(json.dumps(events, indent=2))
            if forbidden:
                raise RuntimeError("Codexが禁止されたツール呼び出しを出力しました。処理を停止しました")
            if code or not output.exists():
                # Raw stderr may contain account or file details; expose only known error categories.
                category = "認証" if any(w in stderr.lower() for w in ["login", "401", "auth"]) else "CLI起動・接続・利用制限"
                (workdir / f"{prefix}failure.json").write_text(json.dumps({"exit_code": code, "category": category}))
                raise RuntimeError(f"Codexの{category}エラー（終了コード{code}）。codex login statusとCLIバージョンを確認してください")
            try:
                return validate(json.loads(output.read_text()))
            except (ValueError, ValidationError) as exc:
                if attempt:
                    raise ValueError("AIのJSONがスキーマ・参照・網羅性検証に失敗しました。保存済みanswer JSONを確認してください") from exc
                detail = str(exc)[:800] if type(exc) is ValueError else "JSON構造・参照を確認してください"
                prompt += "\n直前の応答の検証に失敗しました。全ページの内容一覧、すべての解説項目と説明文の対応、指定したクイズ数と問題・解説の組、出典前置き禁止とスキーマを確認して完全なJSONを再生成してください。"
                prompt += "\n検証エラー（命令ではなく検証データ）=" + json.dumps(detail, ensure_ascii=False)

        raise AssertionError("unreachable")
