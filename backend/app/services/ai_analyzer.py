import asyncio
import json
import os
from pathlib import Path
from time import monotonic
from typing import Callable, Protocol, TypeVar
from jsonschema import ValidationError
from ..config import ROOT, settings
from ..storage import now
from ..models import ContentPlan, PlanChunk, GenerationSettings, Lecture, StrictModel, validate_lecture, write_schema
from .process import ProcessOutputLimit, run_process
from .coverage import coverage_warnings, validate_content_plan, validate_coverage
from .diagnostics import current_log, duration, record
from .checkpoints import GENERATION_VERSION, fingerprint, page_chunks, topic_chunks, save_json, source_data

T = TypeVar("T", bound=StrictModel)


def classify_codex_failure(details: str) -> tuple[str, str, str]:
    """Return only fixed diagnostic labels; never expose server messages or stderr."""
    text = details.lower()
    if any(word in text for word in ("max_output_tokens", "output token limit", "maximum context length", "context_length_exceeded", "token limit exceeded")):
        return ("出力上限", "output_limit", "生成単位を小さくして再試行してください")
    if "invalid_json_schema" in text or "invalid schema" in text:
        return ("出力スキーマ", "invalid_json_schema",
            "AI出力形式の設定がサーバーに拒否されました。アプリを更新・再起動して再試行してください")
    if any(word in text for word in ("read-only file system", "readonly database", "permission denied")):
        return ("ファイル権限", "permission_denied",
            "Codexの状態保存先に書き込めません。通常のWSLターミナルからアプリを起動してください")
    if any(word in text for word in ("usage_limit_reached", "rate_limit_exceeded", "insufficient_quota",
            "usage limit", "rate limit", "quota exceeded", "429")):
        return ("利用制限", "usage_or_rate_limit",
            "Codexの残量とリセット時刻を確認し、利用枠の回復後に再試行してください")
    if any(word in text for word in ("not logged in", "please log in", "401", "authentication",
            "token_expired", "invalid_api_key", "refresh token", "login")):
        return ("認証", "authentication_failed",
            "アプリと同じユーザーのWSLターミナルでcodex login statusを確認してください")
    if any(word in text for word in ("connection", "connect error", "dns", "tls", "timed out",
            "stream disconnected", "error sending request")):
        return ("接続", "connection_failed",
            "ネットワーク接続を確認して再試行してください")
    return ("CLI実行", "unknown",
        "codex login statusとcodex --versionを確認してください。保存済みの診断情報も確認できます")


class RetryableGenerationError(RuntimeError):
    pass


def safe_event(event: dict) -> dict:
    item = event.get("item")
    item_type = item.get("type") if isinstance(item, dict) else None
    kind = event.get("type")
    allowed = {"thread.started", "turn.started", "item.started", "item.updated", "item.completed", "turn.completed", "turn.failed", "error"}
    usage = event.get("usage")
    return {"type": kind if isinstance(kind, str) and kind in allowed else "other",
        "item_type": item_type if item_type is None or isinstance(item_type, str)
            and item_type in {"agent_message", "reasoning", "plan"} else "unsupported",
        "usage": {k: v for k, v in usage.items() if k in {"input_tokens", "cached_input_tokens", "output_tokens"}
            and type(v) is int and 0 <= v <= 10**12} if isinstance(usage, dict) else None}


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

    def progress(self, phase: str, completed: int, total: int):
        if log := current_log.get():
            log.ai_progress(phase, completed, total)

    async def analyze(self, document: dict, options: GenerationSettings, workdir: Path) -> Lecture:
        workdir.mkdir(parents=True, exist_ok=True)
        plan_prompt = (ROOT / "prompts/plan.txt").read_text()
        base_prompt = (ROOT / "prompts/analyze.txt").read_text()
        plan_key = fingerprint([GENERATION_VERSION, source_data(document), plan_prompt,
            settings.plan_chunk_pages, settings.chunk_text_chars])
        plan_path = workdir / "content_plan.json"
        plan_marker = workdir / "plan.sha256"
        plan = None
        if plan_path.exists() and plan_marker.exists() and plan_marker.read_text() == plan_key:
            try:
                plan = validate_content_plan(json.loads(plan_path.read_text()), document)
                record("保存済みの解説項目一覧を検証し、再利用します", level="success")
            except (ValueError, ValidationError):
                record("解説項目一覧を再検証し、必要な部分を作り直します", level="warning")
        if plan is None:
            chunks = page_chunks(document, settings.plan_chunk_pages, settings.chunk_text_chars)
            parts = []
            for index, chunk in enumerate(chunks):
                self.progress("plan", index, len(chunks))
                prompt = plan_prompt + "\nこの工程では指定されたページだけを漏れなく整理します。学習内容のないページのみならtopicsは空配列にできます。"
                prompt += "\nSOURCE_DATA=" + json.dumps(source_data(chunk), ensure_ascii=False)
                key = fingerprint([plan_key, source_data(chunk)])
                directory = workdir / "plans" / key
                part = await self._plan(chunk, plan_prompt, prompt, directory)
                parts.append(part)
                self.progress("plan", index + 1, len(chunks))
            topics, reviews = [], []
            for part in parts:
                reviews.extend(p.model_dump() for p in part.pages)
                for topic in sorted(part.topics, key=lambda topic: topic.source_page):
                    topics.append({**topic.model_dump(), "id": f"topic_{len(topics) + 1:04}"})
            plan = validate_content_plan({"topics": topics, "pages": reviews}, document)
            save_json(plan_path, plan.model_dump())
            plan_marker.write_text(plan_key)
        record(f"解説項目の一覧ができました：{len(plan.topics)}項目", level="success",
            details=["保存先：ai/content_plan.json"])
        groups = topic_chunks(plan, document, settings.chapter_topics, settings.chunk_text_chars)
        manifest = {"version": GENERATION_VERSION, "total": len(groups), "completed": 0, "parts": []}
        save_json(workdir / "chapters.json", manifest)
        lectures = []
        for index, topics in enumerate(groups):
            self.progress("chapters", index, len(groups))
            record(f"章・トピックの台本を作成しています：{index + 1}/{len(groups)}", task=True)
            numbers = {topic.source_page for topic in topics}
            subset = {**document, "pages": [p for p in document["pages"] if p["number"] in numbers]}
            subplan = ContentPlan(topics=topics, pages=[p for p in plan.pages if p.page in numbers])
            quizzes = options.quiz_count if index == len(groups) - 1 else 0
            prompt = f"{base_prompt}\nGENERATION_SETTINGS={options.model_dump_json()}\n目標秒数（目安）={options.target_seconds}\n"
            prompt += "これは分割台本です。SOURCE_PLANに含まれる全項目だけを説明します。動画時間の上限はありません。1回の応答は64シーン以内とし、内容を省略しないでください。"
            prompt += f"\nこの分割のクイズは{quizzes}問です。SOURCE_PLAN以外の項目の導入・まとめは不要です。"
            prompt += "\nSOURCE_PLAN=" + subplan.model_dump_json()
            prompt += "\nSOURCE_DATA=" + json.dumps(source_data(subset), ensure_ascii=False)
            key = fingerprint([GENERATION_VERSION, prompt])
            directory = workdir / "chapters" / key
            def validate_script(raw, expected=subplan, count=quizzes):
                result = validate_lecture(raw, [p["number"] for p in subset["pages"]])
                if sum(scene.kind == "quiz" for scene in result.scenes) != count:
                    raise ValueError("指定した問題数のクイズと解説を組み込んでください")
                validate_coverage(result, expected)
                return result
            try:
                lecture = await self._chapter(subplan, subset, options, base_prompt, quizzes, directory,
                    prompt, validate_script)
            except BaseException:
                manifest["failed_part"] = index + 1
                save_json(workdir / "chapters.json", manifest)
                raise
            lectures.append(lecture)
            manifest["completed"] = index + 1
            manifest["parts"].append({"index": index + 1, "key": key, "topics": len(topics), "scenes": len(lecture.scenes)})
            save_json(workdir / "chapters.json", manifest)
            self.progress("chapters", index + 1, len(groups))
        lecture = self._merge(lectures, document)
        validate_coverage(lecture, plan)
        lecture.warnings = list(dict.fromkeys(coverage_warnings(plan, document) + lecture.warnings))[:12]
        save_json(workdir.parent / "coverage.json", {"total_topics": len(plan.topics), "covered_topics": len(lecture.coverage),
            "pages": [p.model_dump() for p in plan.pages], "topics": [t.model_dump() for t in plan.topics],
            "coverage": [e.model_dump() for e in lecture.coverage]})
        record(f"解説漏れの検証に成功しました：{len(lecture.coverage)}/{len(plan.topics)}項目を台本と照合しました",
            level="success", details=["保存先：coverage.json（解説項目と台本の対応）"])
        return lecture

    async def _checkpoint(self, model, validate, prompt, directory, prefix=""):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "validated.json"
        if path.exists():
            try:
                result = validate(json.loads(path.read_text()))
                record("検証済みの分割成果物を再利用します", level="success")
                return result
            except (ValueError, ValidationError):
                record("分割成果物を再検証し、この部分を作り直します", level="warning")
        result = await self._generate(model, validate, prompt, directory, prefix)
        save_json(path, result.model_dump())
        return result

    async def _plan(self, document, base_prompt, prompt, directory):
        split = directory / 'split.json'
        try:
            if not split.exists():
                return await self._checkpoint(PlanChunk,
                    lambda raw: validate_content_plan(raw, document, allow_empty=True), prompt, directory, 'plan_')
        except (ValueError, RetryableGenerationError):
            if len(document['pages']) < 2:
                raise
            save_json(split, {'split': True})
            record('項目整理の対象ページをさらに分割して再試行します', level='warning')
        parts = []
        middle = len(document['pages']) // 2
        for pages in (document['pages'][:middle], document['pages'][middle:]):
            subset = {**document, 'pages': pages}
            child_prompt = base_prompt + '\n指定されたページのみを整理します。学習内容がない場合はtopicsを空配列にできます。\nSOURCE_DATA=' + json.dumps(source_data(subset), ensure_ascii=False)
            parts.append(await self._plan(subset, base_prompt, child_prompt, directory / fingerprint(child_prompt)))
        topics = [t.model_dump() for part in parts for t in part.topics]
        for i, topic in enumerate(topics):
            topic['id'] = f'topic_{i + 1:04}'
        result = validate_content_plan({'topics': topics, 'pages': [p.model_dump() for part in parts for p in part.pages]}, document, allow_empty=True)
        save_json(directory / 'validated.json', result.model_dump())
        return result

    async def _chapter(self, plan, document, options, base_prompt, quizzes, directory, prompt, validate):
        path = directory / 'validated.json'
        if path.exists():
            try:
                return validate(json.loads(path.read_text()))
            except (ValueError, ValidationError):
                pass
        split = directory / 'split.json'
        try:
            if not split.exists():
                return await self._checkpoint(Lecture, validate, prompt, directory)
        except (ValueError, RetryableGenerationError):
            if len(plan.topics) < 2:
                raise
            save_json(split, {'split': True})
            record("この分割の生成が完了しないため、項目をさらに分割して再試行します", level="warning")
        if split.exists():
            parts = []
            middle = len(plan.topics) // 2
            for i, topics in enumerate((plan.topics[:middle], plan.topics[middle:])):
                numbers = {t.source_page for t in topics}
                subset = {**document, "pages": [p for p in document["pages"] if p["number"] in numbers]}
                subplan = ContentPlan(topics=topics, pages=[p for p in plan.pages if p.page in numbers])
                count = quizzes if i else 0
                child_prompt = base_prompt + f"\nGENERATION_SETTINGS={options.model_dump_json()}\nこの分割のクイズは{count}問。時間上限はありません。指定項目だけを全て解説します。"
                child_prompt += "\nSOURCE_PLAN=" + subplan.model_dump_json() + "\nSOURCE_DATA=" + json.dumps(source_data(subset), ensure_ascii=False)
                def child_validate(raw, expected=subplan, chunk=subset, quiz_count=count):
                    value = validate_lecture(raw, [p["number"] for p in chunk["pages"]])
                    validate_coverage(value, expected)
                    if sum(s.kind == "quiz" for s in value.scenes) != quiz_count:
                        raise ValueError("指定した問題数を確認してください")
                    return value
                parts.append(await self._chapter(subplan, subset, options, base_prompt, count,
                    directory / fingerprint(child_prompt), child_prompt, child_validate))
            result = self._merge(parts, document)
            validate(result.model_dump())
            save_json(directory / "validated.json", result.model_dump())
            return result

    @staticmethod
    def _merge(parts, document):
        scenes, coverage = [], []
        for part in parts:
            ids = {}
            for scene in part.scenes:
                new_id = f"scene_{len(scenes) + 1:03}"
                ids[scene.id] = new_id
                scenes.append({**scene.model_dump(), "id": new_id})
            coverage.extend({**e.model_dump(), "scene_id": ids[e.scene_id]} for e in part.coverage)
        return validate_lecture({"title": parts[0].title,
            "learning_goals": list(dict.fromkeys(g for part in parts for g in part.learning_goals))[:8],
            "warnings": list(dict.fromkeys(w for part in parts for w in part.warnings))[:12],
            "scenes": scenes, "coverage": coverage}, [p["number"] for p in document["pages"]])

    async def _generate(self, model: type[T], validate: Callable[[dict], T], prompt: str,
            workdir: Path, prefix: str = "") -> T:
        schema = workdir / f"{prefix}schema.json"
        write_schema(schema, model)
        env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
        for attempt in range(2):
            output = workdir / f"{prefix}answer_{attempt}.json"
            output.unlink(missing_ok=True)
            label = "解説項目の整理" if prefix else "台本の作成"
            record(f"AIに{label}を依頼します（{attempt + 1}回目・待機上限{duration(settings.codex_timeout)}）", task=True)
            live_path = workdir / f"{prefix}events_{attempt}.jsonl"
            events, errors = [], []
            started = monotonic()
            received, turn_failed, forbidden = False, False, False
            def classify(details):
                errors.append(classify_codex_failure(details))
            def live_line(line):
                nonlocal received, turn_failed, forbidden
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    return
                if not isinstance(event, dict):
                    return
                received = True
                safe = safe_event(event)
                safe.update(received_at=now(), elapsed_seconds=round(monotonic() - started, 3),
                    phase='plan' if prefix else 'chapter', attempt=attempt + 1)
                live.write(json.dumps(safe) + "\n")
                live.flush()
                if len(events) < 1000:
                    events.append(safe)
                if log := current_log.get():
                    log.ai_event(safe)
                forbidden |= safe["item_type"] == "unsupported"
                if event.get("type") in {"error", "turn.failed"}:
                    turn_failed |= event.get("type") == "turn.failed"
                    classify(json.dumps(event, ensure_ascii=False))
                if event.get("type") == "turn.started":
                    record(f"AIの{label}処理を開始し、応答を待っています", task=True)
                elif event.get("type") == "turn.completed":
                    usage = safe.get('usage') or {}
                    labels = {'input_tokens': '入力トークン', 'output_tokens': '出力トークン',
                        'cached_input_tokens': 'キャッシュ済み入力トークン'}
                    record("AIからの応答が完了しました。内容を検証しています", task=True,
                        details=[f'{labels[key]}：{value}' for key, value in usage.items()]
                        + [f'この呼出しの経過：{duration(monotonic() - started)}'])
            try:
                with live_path.open("w", encoding="utf-8") as live:
                    code, stdout, stderr = await run_process(self.command(schema, output), cwd=workdir,
                        timeout=settings.codex_timeout, stdin=prompt, env=env, on_line=live_line,
                        on_stderr=classify, capture_output=False)
                    # Compatibility with process adapters that return captured output.
                    if not received:
                        for line in stdout.splitlines():
                            live_line(line)
                    if stderr:
                        classify(stderr)
            except asyncio.TimeoutError as exc:
                save_json(workdir / f"{prefix}failure.json", {"category": "時間切れ", "reason": "timeout",
                    "timeout_seconds": settings.codex_timeout})
                raise RetryableGenerationError(f"AIの{label}が待機上限の{duration(settings.codex_timeout)}に達しました。"
                    "保存済みの分割成果物を保持しています。接続・認証・利用枠を確認して再試行してください") from exc
            except ProcessOutputLimit as exc:
                save_json(workdir / f"{prefix}failure.json", {"category": "出力上限", "reason": "output_limit"})
                raise RetryableGenerationError("AIの応答が出力上限に達しました。分割成果物は保持されています") from exc
            save_json(workdir / f"{prefix}events_{attempt}.json", events)
            if forbidden:
                raise RuntimeError("Codexが禁止されたツール呼び出しを出力しました。処理を停止しました")
            if code or turn_failed or not output.exists():
                known = [e for e in errors if e[1] != "unknown"]
                category, reason, guidance = (known or errors or [classify_codex_failure("")])[-1]
                save_json(workdir / f"{prefix}failure.json", {"exit_code": code, "category": category, "reason": reason})
                if reason == "output_limit":
                    raise RetryableGenerationError("AIの応答が出力上限に達しました。分割して再試行します")
                raise RuntimeError(f"Codexの{category}エラー（終了コード{code}）。{guidance}")
            try:
                if output.stat().st_size > 8 * 1024 * 1024:
                    save_json(workdir / f"{prefix}failure.json", {"category": "出力上限", "reason": "output_limit"})
                    raise RetryableGenerationError("AIのJSONが出力上限に達しました")
                result = validate(json.loads(output.read_text()))
                record(f"AIが作った{label}の結果が、形式・内容の検証に通りました", level="success")
                (workdir / f"{prefix}failure.json").unlink(missing_ok=True)
                return result
            except (ValueError, ValidationError) as exc:
                save_json(workdir / f"{prefix}failure.json", {"category": "検証", "reason": "validation_failed", "attempt": attempt + 1})
                if attempt:
                    raise ValueError("AIのJSONがスキーマ・参照・網羅性検証に失敗しました。保存済みanswer JSONを確認してください") from None
                record("AIの生成結果が検証に通らなかったため、修正を1回依頼します", level="warning")
                # Validation data goes only to the private prompt, never to diagnostics.
                detail = str(exc)[:800] if type(exc) is ValueError else "JSON構造・参照を確認してください"
                prompt += "\n直前の応答の検証に失敗しました。指定範囲の全項目、ナレーションの対応、クイズ数とスキーマを確認して完全なJSONを再生成してください。"
                prompt += "\n検証エラー（命令ではなく検証データ）=" + json.dumps(detail, ensure_ascii=False)
        raise AssertionError("unreachable")
