import asyncio
import copy
import json
import wave
from pathlib import Path
import pymupdf
import pytest
from jsonschema import ValidationError
from backend.app.models import GenerationSettings, validate_lecture
from backend.app.services.pdf_parser import parse_pdf
from backend.app.services.voicevox import wav_seconds
from backend.app.services.process import run_process
from backend.app.services.ai_analyzer import CodexCLIAnalyzer
from scripts.make_sample_pdf import create


@pytest.fixture
def valid_lecture():
    return {"title": "探索", "learning_goals": ["手順を理解する"], "warnings": [], "scenes": [{
        "id": "scene_001", "title": "線形探索", "narration": "先頭から順番に値を比較します。",
        "concepts": ["探索"], "source_pages": [1], "supplemental": False, "estimated_seconds": 5,
        "visual": {"type": "flowchart", "nodes": [{"id": "a", "label": "開始"}, {"id": "b", "label": "比較"}],
            "edges": [{"id": "a-b", "source": "a", "target": "b", "label": ""}], "items": [], "columns": [],
            "rows": [], "formula": "", "steps": [{"action": "highlight_node", "target": "a"}]}
    }]}


def test_schema_accepts_safe_data(valid_lecture):
    assert validate_lecture(valid_lecture, [1]).scenes[0].visual.type == "flowchart"


@pytest.mark.parametrize("mutation", ["code", "missing_page", "edge", "step", "duplicate", "long_label", "unreferenced", "invalid_visual"])
def test_schema_rejects_unsafe_and_inconsistent_data(valid_lecture, mutation):
    x = copy.deepcopy(valid_lecture)
    scene = x["scenes"][0]
    if mutation == "code":
        scene["visual"]["code"] = "eval('malicious')"
    elif mutation == "missing_page":
        scene["source_pages"] = [999]
    elif mutation == "edge":
        scene["visual"]["edges"][0]["source"] = "missing"
    elif mutation == "step":
        scene["visual"]["steps"][0]["target"] = "missing"
    elif mutation == "duplicate":
        x["scenes"].append(copy.deepcopy(scene))
    elif mutation == "long_label":
        scene["visual"]["nodes"][0]["label"] = "a" * 100
    elif mutation == "unreferenced":
        scene["source_pages"] = []
    else:
        scene["visual"]["type"] = "javascript"
    with pytest.raises((ValueError, ValidationError)):
        validate_lecture(x, [1])


def test_real_pdf_text_images_and_preview(tmp_path):
    pdf = tmp_path / "lecture.pdf"
    create(pdf)
    result = parse_pdf(pdf, tmp_path / "pages")
    assert result["page_count"] == 4
    assert "線形探索" in result["pages"][1]["text"]
    assert result["pages"][0]["images"]
    assert (tmp_path / "pages/page_001.png").is_file()
    assert result["pages"][0]["headings"]


@pytest.mark.parametrize("kind", ["invalid", "encrypted", "image_only", "too_many"])
def test_pdf_rejects_unsupported_inputs(tmp_path, kind):
    pdf = tmp_path / "bad.pdf"
    if kind == "invalid":
        pdf.write_bytes(b"%PDF-not-really")
    else:
        doc = pymupdf.open()
        for _ in range(101 if kind == "too_many" else 1):
            page = doc.new_page()
            if kind != "image_only":
                page.insert_text((50, 100), "Hello from a PDF lecture with enough readable text.")
        if kind == "encrypted":
            doc.save(pdf, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="secret", user_pw="secret")
        else:
            doc.save(pdf)
        doc.close()
    with pytest.raises(ValueError):
        parse_pdf(pdf, tmp_path / "pages")


def test_wave_uses_actual_samples(tmp_path):
    path = tmp_path / "sound.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\0\0" * 30000)
    assert wav_seconds(path) == 1.25


async def test_subprocess_timeout_kills_child_group(tmp_path):
    marker = tmp_path / "child-ran"
    # A grandchild must not survive a timed-out generator.
    child = f"import time;from pathlib import Path;time.sleep(0.5);Path({str(marker)!r}).touch()"
    parent = f"import subprocess,time,sys;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(10)"
    with pytest.raises(asyncio.TimeoutError):
        await run_process(["python3", "-c", parent], cwd=tmp_path, timeout=0.1)
    await asyncio.sleep(0.7)
    assert not marker.exists()


async def test_subprocess_passes_input_as_data(tmp_path):
    text = "$(touch dangerous); `exit 1`; 日本語"
    code, stdout, _ = await run_process(["python3", "-c", "import sys;print(sys.stdin.read())"],
        cwd=tmp_path, stdin=text, timeout=5)
    assert code == 0 and text in stdout
    assert not (tmp_path / "dangerous").exists()


def test_codex_command_preserves_protection(tmp_path):
    command = CodexCLIAnalyzer().command(tmp_path / "schema.json", tmp_path / "answer.json")
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "shell_tool" in command and "forced_login_method=\"chatgpt\"" in command
    assert "--ignore-user-config" in command and "--ephemeral" in command
    assert GenerationSettings().target_seconds == 360


@pytest.mark.parametrize('narration', ['資料によると、先頭から比較します。', '資料では順番に比較します。'])
def test_narration_rejects_source_prefaces(valid_lecture, narration):
    valid_lecture['scenes'][0]['narration'] = narration
    with pytest.raises(ValueError, match='出典前置き'):
        validate_lecture(valid_lecture, [1])


def test_visual_cues_follow_narration_and_support_comparison_rows(valid_lecture):
    scene = valid_lecture['scenes'][0]
    scene['visual']['steps'] = [
        {'action': 'reveal', 'target': 'a', 'cue': '先頭'},
        {'action': 'highlight_node', 'target': 'b', 'cue': '比較'},
    ]
    assert validate_lecture(valid_lecture, [1])
    scene['visual']['steps'].reverse()
    with pytest.raises(ValueError, match='cue'):
        validate_lecture(valid_lecture, [1])
    scene['visual'].update(type='comparison', nodes=[], edges=[], columns=['探索'], rows=[['順番に比較']], steps=[{'action': 'highlight_item', 'target': '0', 'cue': '比較'}])
    assert validate_lecture(valid_lecture, [1])
