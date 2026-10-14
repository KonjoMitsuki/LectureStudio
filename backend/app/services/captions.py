"""Deterministic captions from narration, without changing speech synthesis."""
import math
import re


MAX_CAPTION_CHARS = 42


def caption_chunks(text: str) -> list[str]:
    # Prefer sentence/clause boundaries; retain every character, including punctuation.
    clauses = re.findall(r"[^、。！？!?\n]+[、。！？!?\n]*|[、。！？!?\n]+", text)
    chunks = []
    current = ""
    for clause in clauses:
        while clause:
            room = MAX_CAPTION_CHARS - len(current)
            current += clause[:room]
            clause = clause[room:]
            if len(current) == MAX_CAPTION_CHARS or current.endswith(("。", "！", "？", "!", "?", "\n")):
                chunks.append(current)
                current = ""
        if len(current) >= 24:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks


def build_captions(text: str, seconds: float, fps: int = 30) -> list[dict]:
    """Estimate caption boundaries from measured audio duration and text positions."""
    if not text or seconds <= 0:
        return []
    end = max(1, math.ceil(seconds * fps))
    captions = []
    offset = 0
    for chunk in caption_chunks(text):
        start_frame = round(offset / len(text) * end)
        offset += len(chunk)
        end_frame = round(offset / len(text) * end)
        if end_frame > start_frame:
            captions.append({"text": chunk, "start_frame": start_frame, "end_frame": end_frame})
    return captions
