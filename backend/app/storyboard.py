"""Declarative scene composition: plain data, no generated code or markup."""
import unicodedata
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

WIDTH, HEIGHT = 1696, 668
Tone = Literal["fg", "muted", "accent", "warm", "cool"]
Fill = Literal["none", "card", "accent", "warm", "cool"]


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Element(DataModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    kind: Literal["text", "rect", "ellipse", "line", "arrow"]
    x: float = Field(ge=0, le=WIDTH)
    y: float = Field(ge=0, le=HEIGHT)
    width: float = Field(ge=-WIDTH, le=WIDTH)
    height: float = Field(ge=-HEIGHT, le=HEIGHT)
    text: str = Field(default="", max_length=160)
    font_size: float = Field(default=44, ge=28, le=120)
    align: Literal["left", "center", "right"] = "center"
    tone: Tone = "fg"
    fill: Fill = "none"
    opacity: float = Field(default=1, ge=0, le=1)


class Change(DataModel):
    target: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    x: float | None = Field(default=None, ge=0, le=WIDTH)
    y: float | None = Field(default=None, ge=0, le=HEIGHT)
    width: float | None = Field(default=None, ge=-WIDTH, le=WIDTH)
    height: float | None = Field(default=None, ge=-HEIGHT, le=HEIGHT)
    text: str | None = Field(default=None, max_length=160)
    font_size: float | None = Field(default=None, ge=28, le=120)
    tone: Tone | None = None
    fill: Fill | None = None
    opacity: float | None = Field(default=None, ge=0, le=1)


class Beat(DataModel):
    cue: str = Field(min_length=1, max_length=80)
    transition_seconds: float = Field(default=.5, ge=0, le=2)
    changes: list[Change] = Field(min_length=1, max_length=24)


def check_element(element: Element):
    """Check every composed state; shrinking text to fit is deliberately disallowed."""
    if not (0 <= element.x + element.width <= WIDTH and 0 <= element.y + element.height <= HEIGHT):
        raise ValueError("絵コンテの要素が描画領域1696×668からはみ出しています")
    if element.kind in {"line", "arrow"}:
        if element.width == 0 and element.height == 0:
            raise ValueError("線・矢印には長さが必要です")
        if element.text:
            raise ValueError("線のラベルは別のtext要素にしてください")
        return
    if element.width <= 0 or element.height <= 0:
        raise ValueError("図形・文字の幅と高さは正数です")
    if element.text:
        lines = element.text.split("\n")
        # Explicit line breaks, conservative em widths; no invisible auto-shrinking.
        em = lambda line: sum(1 if unicodedata.east_asian_width(c) in {"W", "F", "A"} else .65 for c in line)
        padding = 0 if element.kind == "text" else 24
        if max(map(em, lines)) * element.font_size > element.width - padding:
            raise ValueError("絵コンテの文字が横幅を超えています。改行・分割または領域拡大をしてください")
        if len(lines) * element.font_size * 1.25 > element.height - padding:
            raise ValueError("絵コンテの文字が高さを超えています")


class Storyboard(DataModel):
    intent: str = Field(min_length=1, max_length=240)
    elements: list[Element] = Field(min_length=1, max_length=24)
    beats: list[Beat] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_states(self):
        states = {element.id: element for element in self.elements}
        if len(states) != len(self.elements):
            raise ValueError("絵コンテの要素IDが重複しています")
        for element in states.values():
            check_element(element)
        for beat in self.beats:
            if len({change.target for change in beat.changes}) != len(beat.changes):
                raise ValueError("同じbeat内で同じ要素を二度変更できません")
            for change in beat.changes:
                if change.target not in states:
                    raise ValueError("絵コンテの変更対象が存在しません")
                patch = change.model_dump(exclude_none=True, exclude={"target"})
                if not patch:
                    raise ValueError("絵コンテの変更内容が空です")
                if "text" in patch and beat.transition_seconds:
                    check_element(Element.model_validate({**states[change.target].model_dump(), "text": patch["text"]}))
                states[change.target] = Element.model_validate({**states[change.target].model_dump(), **patch})
                check_element(states[change.target])
        return self


def validate_storyboard_cues(board: Storyboard, narration: str):
    position = -1
    for beat in board.beats:
        position = narration.find(beat.cue, position + 1)
        if position < 0:
            raise ValueError("絵コンテのcueはナレーションの出現順に指定してください")


def timed_storyboard(scene: dict, audio_seconds: float) -> dict | None:
    if not scene.get("storyboard"):
        return None
    board = Storyboard.model_validate(scene["storyboard"])
    validate_storyboard_cues(board, scene["narration"])
    result = board.model_dump()
    position = -1
    for beat in result["beats"]:
        position = scene["narration"].index(beat["cue"], position + 1)
        beat["at_frame"] = round(position / len(scene["narration"]) * audio_seconds * 30)
        beat["duration_in_frames"] = min(round(beat["transition_seconds"] * 30),
            max(0, math.ceil(audio_seconds * 30) + 15 - beat["at_frame"]))
    validate_timed_states(result)
    return result


def validate_timed_states(board: dict):
    """Check interrupted transitions too, once real speech timing is available."""
    numeric = ("x", "y", "width", "height", "font_size", "opacity")
    states = {e["id"]: dict(e) for e in board["elements"]}
    tracks = {}
    for beat in board["beats"]:
        for target, (start, length, source, destination) in tracks.items():
            amount = 1 if length == 0 else min(1, max(0, (beat["at_frame"] - start) / length))
            eased = amount * amount * (3 - 2 * amount)
            states[target] = {**destination, **{k: source[k] + (destination[k] - source[k]) * eased for k in numeric}}
            check_element(Element.model_validate(states[target]))
        for change in beat["changes"]:
            target = change["target"]
            patch = {k: v for k, v in change.items() if k != "target" and v is not None}
            source = states[target]
            destination = {**(tracks[target][3] if target in tracks else source), **patch}
            # Discrete text changes are visible immediately, before geometry grows.
            visible = destination if beat["duration_in_frames"] == 0 else {
                **source, **{k: destination[k] for k in ("text", "tone", "fill")}}
            check_element(Element.model_validate(visible))
            tracks[target] = (beat["at_frame"], beat["duration_in_frames"], dict(source), destination)
            states[target] = dict(visible)
