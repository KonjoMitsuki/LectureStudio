from typing import Literal
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from jsonschema import Draft202012Validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceTopic(StrictModel):
    id: str = Field(pattern=r"^topic_[0-9]{4}$")
    title: str = Field(min_length=1, max_length=80)
    source_page: int = Field(ge=1)
    source_excerpt: str = Field(min_length=1, max_length=400)


class PageReview(StrictModel):
    page: int = Field(ge=1)
    status: Literal["content", "non_content", "unreadable"]
    reason: str = Field(max_length=160)


class ContentPlan(StrictModel):
    topics: list[SourceTopic] = Field(min_length=1, max_length=1200)
    pages: list[PageReview] = Field(min_length=1, max_length=100)


class PlanChunk(ContentPlan):
    topics: list[SourceTopic] = Field(max_length=1200)


class CoverageEntry(StrictModel):
    topic_id: str = Field(pattern=r"^topic_[0-9]{4}$")
    scene_id: str = Field(pattern=r"^scene_[0-9]{3,6}$")
    narration_excerpt: str = Field(min_length=10, max_length=400)


class Node(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    label: str = Field(min_length=1, max_length=28)


class Edge(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,32}$")
    source: str
    target: str
    label: str = Field(max_length=20)


class Step(StrictModel):
    action: Literal["reveal", "highlight_node", "highlight_edge", "highlight_item"]
    target: str
    cue: str = Field(default="", max_length=80)


class Visual(StrictModel):
    type: Literal["flowchart", "state_diagram", "block_diagram", "network", "timeline", "comparison", "formula", "keywords"]
    nodes: list[Node] = Field(max_length=6)
    edges: list[Edge] = Field(max_length=10)
    items: list[str] = Field(max_length=6)
    columns: list[str] = Field(max_length=4)
    rows: list[list[str]] = Field(max_length=5)
    formula: str = Field(max_length=160)
    steps: list[Step] = Field(max_length=12)

    @model_validator(mode="after")
    def check_layout(self):
        ids = {n.id for n in self.nodes}
        edge_ids = {e.id for e in self.edges}
        if len(ids) != len(self.nodes) or len(edge_ids) != len(self.edges):
            raise ValueError("図解IDが重複しています")
        if any(e.source not in ids or e.target not in ids for e in self.edges):
            raise ValueError("矢印の参照先が存在しません")
        if self.type in {"flowchart", "state_diagram", "block_diagram", "network"} and not self.nodes:
            raise ValueError("この図解にはノードが必要です")
        if self.type in {"timeline", "keywords"} and not self.items:
            raise ValueError("この図解には項目が必要です")
        if self.type == "comparison" and (not self.columns or not self.rows):
            raise ValueError("比較表には列と行が必要です")
        if any(len(r) != len(self.columns) for r in self.rows):
            raise ValueError("比較表の列数が一致しません")
        if self.type == "formula" and not self.formula:
            raise ValueError("数式が空です")
        for text in self.items + self.columns + [cell for row in self.rows for cell in row]:
            if not 1 <= len(text) <= 60:
                raise ValueError("図解の文字数は1〜60文字です")
        for step in self.steps:
            if step.action == "highlight_node" and step.target not in ids:
                raise ValueError("強調対象ノードが存在しません")
            if step.action == "highlight_edge" and step.target not in edge_ids:
                raise ValueError("強調対象矢印が存在しません")
            if step.action in {"reveal", "highlight_item"} and step.target not in ids | edge_ids | {str(i) for i in range(max(len(self.items), len(self.rows)))}:
                raise ValueError("アニメーションの対象が存在しません")
        return self


class AnimationState(StrictModel):
    values: list[float] = Field(default_factory=list, max_length=8)
    highlight: list[str] = Field(default_factory=list, max_length=8)
    label: str = Field(default="", max_length=80)
    formula: str = Field(default="", max_length=160)
    cue: str = Field(min_length=1, max_length=80)


class Animation(StrictModel):
    template: Literal["array", "tree", "graph", "formula", "complexity"]
    nodes: list[Node] = Field(default_factory=list, max_length=6)
    edges: list[Edge] = Field(default_factory=list, max_length=10)
    states: list[AnimationState] = Field(min_length=1, max_length=24)
    curves: list[Literal["constant", "log", "linear", "n_log_n", "quadratic", "cubic"]] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_template(self):
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes) or len({e.id for e in self.edges}) != len(self.edges):
            raise ValueError("アニメーションIDが重複しています")
        if any(e.source not in ids or e.target not in ids or e.source == e.target for e in self.edges):
            raise ValueError("アニメーションの辺の参照が不正です")
        if any(abs(v) > 1_000_000 for s in self.states for v in s.values):
            raise ValueError("配列の値が表示範囲を超えています")
        if self.template == "array":
            size = len(self.states[0].values)
            if not size or any(len(s.values) != size for s in self.states):
                raise ValueError("配列の各状態には同じ数の具体的な入力値が必要です")
            targets = {str(i) for i in range(size)}
        elif self.template in {"tree", "graph"}:
            if not ids:
                raise ValueError("木・グラフにはノードが必要です")
            targets = ids | {e.id for e in self.edges}
            if self.template == "tree":
                parents = {node: 0 for node in ids}
                children = {node: [] for node in ids}
                for edge in self.edges:
                    parents[edge.target] += 1
                    children[edge.source].append(edge.target)
                roots = [node for node in ids if parents[node] == 0]
                if len(roots) != 1 or any(v > 1 for v in parents.values()):
                    raise ValueError("木には一つの根と一意な親が必要です")
                seen, pending = set(), roots[:]
                while pending:
                    node = pending.pop()
                    if node in seen:
                        raise ValueError("木に循環があります")
                    seen.add(node)
                    pending.extend(children[node])
                if seen != ids:
                    raise ValueError("木が連結していません")
        elif self.template == "formula":
            if any(not s.formula.strip() for s in self.states):
                raise ValueError("数式の各変形状態が必要です")
            targets = set()
        else:
            if not self.curves or len(set(self.curves)) != len(self.curves):
                raise ValueError("計算量には重複のない定義済み曲線が必要です")
            targets = set(self.curves)
        if any(target not in targets for s in self.states for target in s.highlight):
            raise ValueError("アニメーションの強調対象が存在しません")
        return self


class Scene(StrictModel):
    id: str = Field(pattern=r"^scene_[0-9]{3,6}$")
    title: str = Field(min_length=1, max_length=40)
    narration: str = Field(min_length=1, max_length=1500)
    concepts: list[str] = Field(min_length=1, max_length=8)
    source_pages: list[int] = Field(max_length=20)
    supplemental: bool
    estimated_seconds: float = Field(gt=0, le=300)
    visual: Visual
    kind: Literal["lecture", "quiz", "quiz_answer"] = "lecture"
    thinking_seconds: int = Field(default=0, ge=0, le=10)
    renderer: Literal["remotion", "manim"] = "remotion"
    animation: Animation | None = None

    @model_validator(mode="after")
    def validate_renderer(self):
        if self.renderer == "manim" and self.animation is None:
            raise ValueError("Manimシーンには固定テンプレートの指定が必要です")
        return self


class Lecture(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    learning_goals: list[str] = Field(min_length=1, max_length=8)
    warnings: list[str] = Field(max_length=12)
    scenes: list[Scene] = Field(min_length=1, max_length=12000)
    coverage: list[CoverageEntry] = Field(default_factory=list, max_length=1200)

    @model_validator(mode="after")
    def unique_scenes(self):
        if len({s.id for s in self.scenes}) != len(self.scenes):
            raise ValueError("シーンIDが重複しています")
        for index, scene in enumerate(self.scenes):
            if scene.kind == "quiz":
                if scene.thinking_seconds < 3:
                    raise ValueError("クイズには3秒以上の思考時間が必要です")
                if index + 1 >= len(self.scenes) or self.scenes[index + 1].kind != "quiz_answer":
                    raise ValueError("クイズの直後には正答と解説のシーンが必要です")
            elif scene.thinking_seconds:
                raise ValueError("思考時間はクイズにのみ設定できます")
            if scene.kind == "quiz_answer" and (index == 0 or self.scenes[index - 1].kind != "quiz"):
                raise ValueError("解説シーンには直前のクイズが必要です")
        return self


class GenerationSettings(StrictModel):
    duration: Literal["test", "short", "medium", "long"] = "short"
    level: Literal["beginner", "standard", "detailed"] = "beginner"
    style: Literal["whiteboard", "motion", "slides"] = "motion"
    speaker: int = Field(default=3, ge=0, le=10000)
    speed: float = Field(default=1.0, ge=0.7, le=1.4)

    @property
    def quiz_count(self) -> int:
        return {"test": 0, "short": 1, "medium": 2, "long": 3}[self.duration]

    @property
    def target_seconds(self) -> int:
        return {"test": 60, "short": 360, "medium": 960, "long": 1800}[self.duration]


def validate_lecture(raw: dict, page_numbers: list[int]) -> Lecture:
    Draft202012Validator(Lecture.model_json_schema()).validate(raw)
    result = Lecture.model_validate(raw)
    available = set(page_numbers)
    for scene in result.scenes:
        if not set(scene.source_pages) <= available:
            raise ValueError("資料に存在しない参照ページがあります")
        if not scene.source_pages and not scene.supplemental:
            raise ValueError("資料由来のシーンには参照ページが必要です")
        last_position = -1
        for step in scene.visual.steps:
            if step.cue:
                position = scene.narration.find(step.cue, max(0, last_position))
                if position < 0:
                    raise ValueError("画面切り替えのcueはナレーション中の順序通りの原文にしてください")
                last_position = position
        last_position = -1
        for state in scene.animation.states if scene.animation else []:
            position = scene.narration.find(state.cue, max(0, last_position + 1))
            if position < 0:
                raise ValueError("アニメーションのcueはナレーションの出現順に指定してください")
            last_position = position
        if any(phrase in scene.narration for phrase in ("資料によると", "資料により", "資料では", "資料によれば", "この資料では", "スライドによると", "スライドでは")):
            raise ValueError("ナレーションの出典前置きを省き、内容を直接説明してください")
    return result


def write_schema(path: Path, model: type[StrictModel] = Lecture):
    schema = model.model_json_schema()

    def require_all_fields(value):
        # Structured Outputs requires every property, including fields with local
        # defaults. Apply this to $defs too without changing local validation or
        # the defaults used when loading existing lecture artifacts.
        if isinstance(value, dict):
            if value.get("type") == "object" and "properties" in value:
                value["required"] = list(value["properties"])
                value["additionalProperties"] = False
            for child in value.values():
                require_all_fields(child)
        elif isinstance(value, list):
            for child in value:
                require_all_fields(child)

    require_all_fields(schema)
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
