"""Check page accounting and explanations against a separately extracted source plan."""
import re

from jsonschema import Draft202012Validator

from ..models import ContentPlan, PlanChunk, Lecture


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def validate_content_plan(raw: dict, document: dict, *, allow_empty: bool = False) -> ContentPlan:
    model = PlanChunk if allow_empty else ContentPlan
    Draft202012Validator(model.model_json_schema()).validate(raw)
    plan = model.model_validate(raw)
    pages = {page["number"]: page["text"] for page in document["pages"]}
    reviewed = {page.page: page for page in plan.pages}
    if len(reviewed) != len(plan.pages) or set(reviewed) != set(pages):
        raise ValueError("内容一覧には資料の全ページを重複なく記録してください")
    if len({topic.id for topic in plan.topics}) != len(plan.topics):
        raise ValueError("解説項目IDが重複しています")
    for topic in plan.topics:
        if topic.source_page not in pages:
            raise ValueError("解説項目の参照ページが資料に存在しません")
        if reviewed[topic.source_page].status != "content":
            raise ValueError("解説項目のページはcontentとして記録してください")
        excerpt = normalized(topic.source_excerpt)
        if not excerpt or excerpt not in normalized(pages[topic.source_page]):
            raise ValueError("解説項目のsource_excerptは参照ページから原文を抜き出してください")
    topic_pages = {topic.source_page for topic in plan.topics}
    for page in plan.pages:
        if page.status == "content" and page.page not in topic_pages:
            raise ValueError("本文ページに解説項目がありません")
        if page.status != "content" and not page.reason.strip():
            raise ValueError("解説対象外・読み取り不能ページには理由が必要です")
        if not pages[page.page].strip() and page.status == "content":
            raise ValueError("文字を抽出できないページの内容を推測しないでください")
    return plan


def validate_coverage(lecture: Lecture, plan: ContentPlan) -> None:
    topics = {topic.id: topic for topic in plan.topics}
    covered = {entry.topic_id: entry for entry in lecture.coverage}
    if len(covered) != len(lecture.coverage):
        raise ValueError("解説対応表の項目IDが重複しています")
    missing = topics.keys() - covered.keys()
    if missing:
        raise ValueError("未解説の項目があります: " + ", ".join(sorted(missing)))
    if covered.keys() - topics.keys():
        raise ValueError("解説対応表に内容一覧にない項目があります")
    scenes = {scene.id: scene for scene in lecture.scenes}
    for topic_id, entry in covered.items():
        scene = scenes.get(entry.scene_id)
        if scene is None:
            raise ValueError("解説対応表のシーンが存在しません")
        if scene.kind != "lecture":
            raise ValueError("クイズだけで解説済みとせず、通常説明のシーンに対応させてください")
        if topics[topic_id].source_page not in scene.source_pages:
            raise ValueError("解説シーンに対応する資料ページの参照がありません")
        if entry.narration_excerpt not in scene.narration:
            raise ValueError("解説対応表にはナレーションに実在する説明文を記録してください")


def coverage_warnings(plan: ContentPlan, document: dict | None = None) -> list[str]:
    warnings = []
    for status, label in [("non_content", "表紙・目次・参考文献等の解説対象外"), ("unreadable", "読み取り不能のため網羅を確認できない")]:
        pages = [page for page in plan.pages if page.status == status]
        if pages:
            warnings.append(label + "ページ: " + " / ".join(f"p.{page.page}（{page.reason}）" for page in pages))
    image_pages = [page["number"] for page in (document or {}).get("pages", []) if page.get("images")]
    if image_pages:
        warnings.append("埋め込み画像自体はAIに渡していないため、画像のみの内容の網羅は未確認です: p." + ", ".join(map(str, image_pages)))
    return warnings
