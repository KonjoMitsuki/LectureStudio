"""Private generation artifacts and content-addressed, atomic checkpoints."""
import hashlib
import json
from pathlib import Path

GENERATION_VERSION = 5


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def source_data(document: dict) -> dict:
    return {'pages': [{'number': p['number'], 'text': p['text'], 'has_images': bool(p.get('images'))}
        for p in document['pages']]}


def page_chunks(document: dict, max_pages: int, max_chars: int) -> list[dict]:
    chunks, pages, size = [], [], 0
    for page in document['pages']:
        if pages and (len(pages) >= max_pages or size + len(page['text']) > max_chars):
            chunks.append({**document, 'pages': pages})
            pages, size = [], 0
        pages.append(page)
        size += len(page['text'])
    if pages:
        chunks.append({**document, 'pages': pages})
    return chunks


def topic_chunks(plan, document: dict, max_topics: int, max_chars: int):
    """Keep source order and page/section boundaries; subdivide dense pages by topics."""
    pages = {p['number']: p for p in document['pages']}
    result, group = [], []
    for topic in plan.topics:
        numbers = {t.source_page for t in group} | {topic.source_page}
        # PDF headings are hints only, never an AI-controlled executable directive.
        boundary = group and topic.source_page != group[-1].source_page and pages[topic.source_page].get('headings')
        if group and (boundary or len(group) >= max_topics or sum(len(pages[n]['text']) for n in numbers) > max_chars):
            result.append(group)
            group = []
        group.append(topic)
    if group:
        result.append(group)
    return result
