import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from backend.app.models import ContentPlan, Lecture, validate_lecture, write_schema
from backend.app.services import ai_analyzer


@pytest.mark.parametrize("model", [ContentPlan, Lecture])
def test_cli_schema_requires_defaulted_fields_in_nested_objects(tmp_path, model):
    path = tmp_path / "schema.json"
    write_schema(path, model)
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)

    def check(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert set(value["required"]) == set(value["properties"])
                assert value["additionalProperties"] is False
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(schema)


def test_cli_schema_rejects_omissions_but_existing_lectures_keep_defaults(tmp_path, valid_lecture):
    path = tmp_path / "schema.json"
    write_schema(path)
    validator = Draft202012Validator(json.loads(path.read_text()))
    # Old saved lectures omit coverage, kind, thinking_seconds and cue.
    with pytest.raises(ValidationError):
        validator.validate(valid_lecture)
    lecture = validate_lecture(valid_lecture, [1])
    validator.validate(lecture.model_dump())
    assert lecture.coverage == []
    assert lecture.scenes[0].kind == "lecture"
    assert lecture.scenes[0].thinking_seconds == 0
    assert lecture.scenes[0].visual.steps[0].cue == ""


@pytest.mark.parametrize("event_type", ["error", "turn.failed"])
async def test_server_schema_error_is_classified_without_exposing_raw_data(tmp_path, monkeypatch, event_type):
    calls = []
    private = "private-account@example.test /private/file.pdf PDF本文 bearer-secret"
    server_message = json.dumps({"error": {
        "code": "invalid_json_schema",
        "message": "Invalid schema: missing coverage. " + private,
    }, "status": 400})
    event = ({"type": event_type, "message": server_message} if event_type == "error"
        else {"type": event_type, "error": {"message": server_message}})

    async def fake_process(command, **kwargs):
        calls.append(command)
        return 1, json.dumps(event), ""

    monkeypatch.setattr(ai_analyzer, "run_process", fake_process)
    with pytest.raises(RuntimeError, match="出力スキーマ") as caught:
        await ai_analyzer.CodexCLIAnalyzer()._generate(Lecture, lambda raw: raw, private, tmp_path)
    assert len(calls) == 1  # Invalid request errors are not retried.
    failure = json.loads((tmp_path / "failure.json").read_text())
    assert failure == {"exit_code": 1, "category": "出力スキーマ", "reason": "invalid_json_schema"}
    for text in [str(caught.value), *(path.read_text() for path in tmp_path.glob("*.json"))]:
        assert private not in text
        assert "bearer-secret" not in text


@pytest.mark.parametrize("details,category,reason", [
    ("Read-only file system", "ファイル権限", "permission_denied"),
    ("attempt to write a readonly database", "ファイル権限", "permission_denied"),
    ("usage_limit_reached", "利用制限", "usage_or_rate_limit"),
    ("rate_limit_exceeded", "利用制限", "usage_or_rate_limit"),
    ("401 authentication failed", "認証", "authentication_failed"),
    ("stream disconnected: error sending request", "接続", "connection_failed"),
    ("unknown failure private-account@example.test", "CLI実行", "unknown"),
])
async def test_failure_classifies_stderr_and_does_not_retry(tmp_path, monkeypatch, details, category, reason):
    calls = []

    async def fake_process(command, **kwargs):
        calls.append(command)
        return 1, "", details

    monkeypatch.setattr(ai_analyzer, "run_process", fake_process)
    with pytest.raises(RuntimeError, match=category):
        await ai_analyzer.CodexCLIAnalyzer()._generate(Lecture, lambda raw: raw, "prompt", tmp_path)
    assert len(calls) == 1
    assert json.loads((tmp_path / "failure.json").read_text()) == {
        "exit_code": 1, "category": category, "reason": reason,
    }


async def test_failed_turn_never_accepts_output_even_with_zero_exit_code(tmp_path, monkeypatch):
    async def fake_process(command, **kwargs):
        Path(command[command.index("--output-last-message") + 1]).write_text("{}")
        return 0, json.dumps({"type": "turn.failed", "error": {"message": "rate_limit_exceeded"}}), ""

    monkeypatch.setattr(ai_analyzer, "run_process", fake_process)
    with pytest.raises(RuntimeError, match="利用制限"):
        await ai_analyzer.CodexCLIAnalyzer()._generate(Lecture, lambda raw: raw, "prompt", tmp_path)


async def test_oversized_final_file_preserves_safe_failure_reason(tmp_path, monkeypatch):
    async def process(command, **kwargs):
        output = Path(command[command.index('--output-last-message') + 1])
        with output.open('wb') as file:
            file.truncate(8 * 1024 * 1024 + 1)
        return 0, '', ''
    monkeypatch.setattr(ai_analyzer, 'run_process', process)
    with pytest.raises(ai_analyzer.RetryableGenerationError, match='出力上限'):
        await ai_analyzer.CodexCLIAnalyzer()._generate(Lecture, lambda value: value, 'private', tmp_path)
    assert json.loads((tmp_path / 'failure.json').read_text()) == {'category': '出力上限', 'reason': 'output_limit'}
