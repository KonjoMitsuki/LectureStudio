from typing import Literal
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from jsonschema import Draft202012Validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


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
            if step.action in {"reveal", "highlight_item"} and step.target not in ids | edge_ids | {str(i) for i in range(len(self.items))}:
                raise ValueError("アニメーションの対象が存在しません")
        return self


class Scene(StrictModel):
    id: str = Field(pattern=r"^scene_[0-9]{3}$")
    title: str = Field(min_length=1, max_length=40)
    narration: str = Field(min_length=1, max_length=1500)
    concepts: list[str] = Field(min_length=1, max_length=8)
    source_pages: list[int] = Field(max_length=20)
    supplemental: bool
    estimated_seconds: float = Field(gt=0, le=300)
    visual: Visual


class Lecture(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    learning_goals: list[str] = Field(min_length=1, max_length=8)
    warnings: list[str] = Field(max_length=12)
    scenes: list[Scene] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_scenes(self):
        if len({s.id for s in self.scenes}) != len(self.scenes):
            raise ValueError("シーンIDが重複しています")
        return self


class GenerationSettings(StrictModel):
    duration: Literal["test", "short", "medium", "long"] = "short"
    level: Literal["beginner", "standard", "detailed"] = "beginner"
    style: Literal["whiteboard", "motion", "slides"] = "motion"
    speaker: int = Field(default=3, ge=0, le=10000)
    speed: float = Field(default=1.0, ge=0.7, le=1.4)

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
    return result


def write_schema(path: Path):
    path.write_text(json.dumps(Lecture.model_json_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
