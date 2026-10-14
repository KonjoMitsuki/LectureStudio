import pymupdf
from pathlib import Path
from ..config import settings


def parse_pdf(source: Path, dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    try:
        doc = pymupdf.open(source)
    except Exception as exc:
        raise ValueError("PDFを開けません。破損またはPDF以外のファイルです") from exc
    with doc:
        if not doc.is_pdf or doc.needs_pass:
            raise ValueError("暗号化PDFまたはPDF以外の形式には対応していません")
        if not 1 <= len(doc) <= settings.max_pages:
            raise ValueError(f"PDFは1〜{settings.max_pages}ページにしてください")
        pages = []
        warnings = []
        total_chars = 0
        for number, page in enumerate(doc, 1):
            text = page.get_text(sort=True).strip()
            total_chars += len(text)
            if total_chars > settings.max_text_chars:
                raise ValueError("抽出テキストが上限を超えました。PDFを分割してください")
            # Bound page raster dimensions even for maliciously large page boxes.
            scale = min(1.25, 1400 / max(page.rect.width, page.rect.height, 1))
            image_name = f"page_{number:03}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(dest / image_name)
            images = []
            for image_i, image in enumerate(page.get_images(full=True)[:12]):
                try:
                    if image[2] * image[3] > 20_000_000:
                        warnings.append(f"p.{number}: 大きすぎる埋め込み画像を除外しました")
                        continue
                    # Use PNG conversion so no executable or SVG assets escape extraction.
                    pix = pymupdf.Pixmap(doc, image[0])
                    if pix.colorspace is None or pix.colorspace.n > 3:
                        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                    name = f"image_{number:03}_{image_i:02}.png"
                    pix.save(dest / name)
                    images.append(name)
                except Exception:
                    warnings.append(f"p.{number}: 埋め込み画像の抽出に失敗しました")
            spans = [s for b in page.get_text("dict")["blocks"] if "lines" in b for l in b["lines"] for s in l["spans"] if s["text"].strip()]
            headings = [s["text"] for s in sorted(spans, key=lambda s: s["size"], reverse=True)[:3]]
            if len(text) < 20:
                warnings.append(f"p.{number}: テキストが少ないため、画像や数式を手動で確認してください（OCR未対応）")
            pages.append({"number": number, "text": text, "preview": image_name, "images": images, "headings": headings})
        if not any(len(p["text"]) >= 20 for p in pages):
            raise ValueError("文字を抽出できません。画像PDFはOCR済みPDFに変換してください")
        return {"page_count": len(doc), "pages": pages, "warnings": warnings}
