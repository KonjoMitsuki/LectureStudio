"""Create an actual Japanese lecture PDF with text, vectors and an embedded image."""
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PAGES = [
    ("アルゴリズム入門：線形探索と二分探索", [
        "学習目標：データを探す手順と、その効率の違いを理解する。",
        "アルゴリズムとは、問題を解くための有限で明確な手順のこと。",
        "探索では、複数のデータから目標の値を見つける。",
        "例として、学生番号が並んだ名簿から自分の番号を探す場合を考える。",
        "入力はデータの配列と目標の値。出力は見つかった位置、または見つからないという結果。",
        "正しさと計算量の両方が、アルゴリズムを選ぶ際の重要な観点になる。",
    ]),
    ("線形探索：先頭から一つずつ調べる", [
        "線形探索は、配列の先頭から順番に目標の値と比較する。",
        "等しい値が見つかったら、その位置を返して終了する。",
        "最後まで見つからなかったら、存在しないことを返す。",
        "例：配列 [2, 4, 7, 9, 12, 15, 18] から12を探すと、比較は5回になる。",
        "データが並べ替えられていなくても利用できる。",
        "要素数をnとすると、最悪の場合の比較回数はn。計算量はO(n)。",
        "小さいデータや、並び順に制約のないデータで使いやすい。",
    ]),
    ("二分探索：範囲を半分に絞る", [
        "二分探索は、昇順に整列された配列で使用する。",
        "中央の値を目標と比較し、小さければ右半分、大きければ左半分を残す。",
        "目標と中央が等しければ、その位置を返す。範囲が空になれば存在しない。",
        "例：[2, 4, 7, 9, 12, 15, 18] から12を探す。中央9の右側に絞り、15の左側に絞り、12を見つける。",
        "探索範囲が繰り返し半分になるので、最悪の計算量はO(log n)。",
        "整列されていない配列にそのまま適用すると正しい結果は保証されない。",
        "整列する処理のコストも考慮して、手法を選ぶ必要がある。",
    ]),
    ("比較と復習", [
        "線形探索：整列は不要、実装が簡単、最悪の計算量はO(n)。",
        "二分探索：整列が必要、探索範囲を半分に絞る、最悪の計算量はO(log n)。",
        "n=1024の場合、線形探索の最悪比較は1024回。二分探索の比較回数は約10〜11回。",
        "時間計算量は、実行時間の秒数そのものではなく、入力サイズと処理量の関係を表す。",
        "一度だけ探索するのか、同じ配列を何度も探索するのかによって選択は変わる。",
        "確認問題：未整列の名簿に二分探索を適用できるか。答え：先に整列が必要。",
        "まとめ：探索手順だけでなく、前提条件と利用場面も確認する。",
    ]),
]


def create(path: Path):
    doc = pymupdf.open()
    for i, (title, lines) in enumerate(PAGES, 1):
        page = doc.new_page(width=842, height=595)
        page.insert_text((42, 64), title, fontname="japan", fontsize=23, color=(0.05, 0.16, 0.3))
        for j, line in enumerate(lines):
            page.insert_textbox(pymupdf.Rect(42, 99 + j * 38, 800, 133 + j * 38), line, fontname="japan", fontsize=12)
        for j, value in enumerate([2, 4, 7, 9, 12, 15, 18]):
            x = 120 + j * 85
            page.draw_rect(pymupdf.Rect(x, 414, x + 64, 468), color=(0.1, 0.6, 0.6), fill=(0.9, 0.97, 0.97))
            page.insert_text((x + 22, 448), str(value), fontsize=20)
        page.insert_text((42, 555), f"Lecture Studio 検証用教材 / p.{i} / 著作：プロジェクト内で作成", fontname="japan", fontsize=10)
    # Actual embedded raster diagram in addition to vector diagrams.
    diagram = pymupdf.open()
    page = diagram.new_page(width=300, height=60)
    page.draw_rect(pymupdf.Rect(5, 5, 295, 55), color=(0.1, 0.6, 0.6))
    page.insert_text((25, 36), "INPUT -> COMPARE -> RESULT", fontsize=15)
    doc[0].insert_image(pymupdf.Rect(280, 483, 580, 543), stream=page.get_pixmap().tobytes("png"))
    diagram.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()
    print(path)


if __name__ == "__main__":
    create(ROOT / "tests/fixtures/search_algorithms.pdf")
