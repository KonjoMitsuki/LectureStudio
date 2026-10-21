import asyncio
import json
import shutil
import os
from pathlib import Path
from ..config import ROOT, settings
from .process import run_process
from .captions import build_captions
from .diagnostics import duration, record


async def render_video(lecture: dict, audio: list[dict], style: str, workdir: Path, on_progress=None) -> dict:
    record("図解・字幕・音声を配置し、動画の準備をしています", task=True)
    public = workdir / "render_assets"
    public.mkdir(exist_ok=True)
    scenes = []
    offset = 0
    for scene, sound in zip(lecture["scenes"], audio, strict=True):
        name = f"{scene['id']}.wav"
        shutil.copyfile(sound["path"], public / name)
        visual = {**scene["visual"], "steps": [dict(step) for step in scene["visual"]["steps"]]}
        # Estimate cue timing from text position and measured audio length.
        # This is not forced alignment; short scenes limit speaking-rate drift.
        position = 0
        for step in visual["steps"]:
            if step.get("cue"):
                position = scene["narration"].index(step["cue"], position)
                step["at_frame"] = round(position / len(scene["narration"]) * sound["audio_seconds"] * 30)
        scenes.append({**scene, "visual": visual, "audio_src": name, "audio_seconds": sound["audio_seconds"],
            "captions": build_captions(scene["narration"], sound["audio_seconds"]),
            "thinking_start_frame": sound["duration_in_frames"],
            "duration_in_frames": sound["duration_in_frames"] + scene.get("thinking_seconds", 0) * 30, "start_frame": offset})
        offset += scenes[-1]["duration_in_frames"]
    props = {"title": lecture["title"], "scenes": scenes, "style": style, "duration_in_frames": offset}
    props_path = workdir / "render_props.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False))
    output = workdir / "video.partial.mp4"
    record(f"動画の配置ができました：{len(scenes)}シーン・{duration(offset / 30)}", level="success",
        details=["映像：1920×1080 / 1秒あたり30コマ", "保存先：render_props.json（図解・字幕・音声の配置）"])

    def line_callback(line):
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                return
            if event.get("type") == "phase":
                messages = {"browser": "動画を描くためのブラウザを準備しています",
                    "bundle": "動画の画面素材をまとめています", "composition": "動画のシーン構成を読み込んでいます",
                    "frames": "図解とアニメーションの映像を描いています",
                    "encode": "映像と音声を結合して、MP4に保存しています"}
                if message := messages.get(event.get("phase")):
                    record(message, task=True)
            elif event.get("type") == "progress" and on_progress:
                on_progress(event["progress"])
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Line-buffered writes preserve progress and errors on timeout/interruption.
    with (workdir / "render.log").open("w", encoding="utf-8", buffering=1) as log:
        def output_line(line):
            log.write(line)
            line_callback(line)
        try:
            env = os.environ.copy()
            if settings.chromium_path:
                env["LECTURE_CHROMIUM_PATH"] = settings.chromium_path
            code, out, err = await run_process(["node", str(ROOT / "video/render.mjs"), str(props_path),
                str(public), str(output), str(settings.render_concurrency)], cwd=ROOT / "video",
                timeout=settings.render_timeout, on_line=output_line, on_stderr=log.write, env=env)
        except asyncio.TimeoutError as exc:
            log.write("\n待機上限に達したため停止しました。\n")
            raise RuntimeError(f"動画の書き出しが待機上限の{duration(settings.render_timeout)}に達しました。"
                "台本・音声・途中の記録は保持されています。LECTURE_RENDER_TIMEOUTを増やして再試行できます") from exc
    if code or not output.exists():
        raise RuntimeError("Remotionのレンダリングに失敗しました。プロジェクト内render.logを確認してください")
    record("書き出した動画の映像・音声・長さを検査しています", task=True)
    meta = await inspect_video(output)
    expected = offset / 30
    if abs(float(meta["format"]["duration"]) - expected) > 0.15:
        raise RuntimeError("MP4の長さが音声タイムラインと一致しません")
    video = next((s for s in meta["streams"] if s["codec_type"] == "video"), {})
    sound = next((s for s in meta["streams"] if s["codec_type"] == "audio"), {})
    if video.get("codec_name") != "h264" or sound.get("codec_name") != "aac":
        raise RuntimeError("MP4の映像・音声コーデックが不正です")
    if (video.get("width"), video.get("height"), video.get("r_frame_rate")) != (1920, 1080, "30/1"):
        raise RuntimeError("MP4の解像度・フレームレートが不正です")
    final = workdir / "video.mp4"
    output.replace(final)
    (workdir / "video_metadata.json").write_text(json.dumps(meta, indent=2))
    record("動画の検査に成功しました：映像・音声が揃い、長さも台本と一致しています", level="success",
        details=["映像：H.264 / 音声：AAC / 解像度：1920×1080 / 30fps", "保存先：video_metadata.json"])
    return {"path": str(final), "seconds": expected, "chapters": [
        {"id": s["id"], "title": s["title"], "seconds": s["start_frame"] / 30,
         "source_pages": s["source_pages"], "supplemental": s["supplemental"]} for s in scenes]}


async def inspect_video(path: Path) -> dict:
    code, stdout, stderr = await run_process(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], cwd=path.parent, timeout=30)
    if code:
        raise RuntimeError("FFprobeでMP4を検査できません")
    return json.loads(stdout)
