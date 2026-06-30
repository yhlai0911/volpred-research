#!/usr/bin/env python3
"""Generate local, free lazypack PNGs and update drafts for existing articles.

⚠️ DEPRECATED for primary use (2026-06-30, boss directive + quality review).
This renderer chops article PROSE to short excerpts (numeric_snippets → sent[:86])
and grabs the first number it sees, so its panels truncate mid-sentence and headline
superficial prose numbers (e.g. a "2% GDP target" instead of the article's actual
1.426x vol-multiplier / 0-of-315 multiple-testing NULL result). Two panels can even
share the same wrong headline. Output passed the enforce gate (a 懶人包圖組 section
exists) but is LOW QUALITY and can MISREPRESENT the data.

PRIMARY lazypack generator is now `scripts/gen_lazypack_codex.py` (codex exec writes
a bespoke render script per article, numbers bound to results.json). Use THIS script
only as a last-resort fallback when codex exec AND NotebookLM are both unavailable,
and only after main-thread review of the output.

This is a deterministic, free renderer (never calls a paid image API). The generated
draft is intended for:

    uv run python scripts/publish_draft.py <draft> --update <mile_id> ...
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "storage" / "reports" / "feed.json"
OUT_ROOT = ROOT / "storage" / "lazypack_backfill"
DRAFT_ROOT = ROOT / "storage" / "drafts" / "lazypack_backfill"

WIDTH = 1600
HEIGHT = 2100
PAPER = "#F7F8FA"
INK = "#18202A"
MUTED = "#5E6978"
FAINT = "#8B95A3"
CARD = "#FFFFFF"
GRID = "#DDE4EC"
BLUE = "#245B9C"
TEAL = "#147C72"
AMBER = "#B7791F"
RED = "#B23A48"
BLUE_SOFT = "#E8F1FB"
TEAL_SOFT = "#E7F4F2"
AMBER_SOFT = "#FFF4DF"

NUMERIC_RE = re.compile(r"[-+]?\d+(?:\.\d+)?\s*(?:%|倍|檔|天|年|次|個|pp|GDP|億|萬|兆)?")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


def load_feed() -> list[dict[str, Any]]:
    return json.loads(FEED.read_text(encoding="utf-8"))


def find_article(article_id: str) -> dict[str, Any]:
    for item in load_feed():
        if isinstance(item, dict) and item.get("id") == article_id:
            return item
    raise SystemExit(f"article not found: {article_id}")


def strip_markdown(text: str) -> str:
    text = IMAGE_RE.sub("", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sentences(text: str) -> list[str]:
    cleaned = strip_markdown(text)
    parts = re.split(r"(?<=[。！？])\s+|(?<=\.)\s+", cleaned)
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def numeric_snippets(content: str, limit: int = 5) -> list[str]:
    out: list[str] = []
    for sent in sentences(content):
        if "|" in sent:
            continue
        if NUMERIC_RE.search(sent):
            out.append(sent[:86])
        if len(out) >= limit:
            break
    return out


def takeaway_snippets(content: str, limit: int = 4) -> list[str]:
    bold = [strip_markdown(m.group(1)) for m in re.finditer(r"\*\*([^*]{8,120})\*\*", content)]
    out = [b for b in bold if b]
    for heading in HEADING_RE.findall(content):
        h = strip_markdown(heading)
        if h and h not in out:
            out.append(h)
        if len(out) >= limit:
            break
    for sent in sentences(content):
        if sent not in out:
            out.append(sent[:78])
        if len(out) >= limit:
            break
    return out[:limit]


def font_candidates() -> list[str]:
    return [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = font_candidates()
    if bold:
        candidates.insert(0, "/System/Library/Fonts/PingFang.ttc")
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue  # silent-ok: font fallback chain, next candidate tried; final fallback = PIL default
    return ImageFont.load_default(size=size)


def wrap_for_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    chars = list(text)
    lines: list[str] = []
    line = ""
    for ch in chars:
        candidate = line + ch
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = ch
    if line:
        lines.append(line)
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    width: int,
    *,
    line_gap: int = 12,
    max_lines: int | None = None,
) -> int:
    x, y = xy
    lines = wrap_for_width(draw, text, font, width)
    if max_lines is not None:
        truncated = len(lines) > max_lines
        lines = lines[:max_lines]
        if truncated and lines:
            lines[-1] = lines[-1].rstrip("，。；、 ") + "…"
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_gap
    return y


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str = GRID) -> None:
    draw.rounded_rectangle(box, radius=32, fill=fill, outline=outline, width=2)


def draw_header(draw: ImageDraw.ImageDraw, title: str, subtitle: str, accent: str) -> None:
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=PAPER)
    draw.rounded_rectangle((84, 84, 260, 106), radius=10, fill=accent)
    draw.text((84, 132), "VolPred 懶人包", font=load_font(38, bold=True), fill=accent)
    title_font = load_font(66, bold=True)
    y = 210
    for line in wrap_for_width(draw, title, title_font, 1360)[:3]:
        draw.text((84, y), line, font=title_font, fill=INK)
        y += 86
    draw_wrapped(draw, (88, y + 20), subtitle, load_font(36), MUTED, 1320, max_lines=3)


def draw_footer(draw: ImageDraw.ImageDraw, article_id: str, refs: list[str]) -> None:
    source = f"資料來源：VolPred {article_id}"
    if refs:
        source += " / " + "、".join(refs)
    source += "；本圖文字與數字取自既有文章內容"
    draw.line((84, HEIGHT - 132, WIDTH - 84, HEIGHT - 132), fill=GRID, width=2)
    draw_wrapped(draw, (84, HEIGHT - 102), source, load_font(26), FAINT, 1180, max_lines=2)


def metric_label(snippet: str) -> str:
    matches = list(NUMERIC_RE.finditer(snippet))
    if not matches:
        return "重點"
    for match in matches:
        value = match.group(0)
        if any(unit in value for unit in ("%","倍","pp","檔","天","次","個")):
            return value
    return matches[-1].group(0)


def render_framework(article: dict[str, Any], snippets: list[str], out: Path) -> None:
    title = str(article.get("title") or article.get("id") or "")
    article_id = str(article.get("id") or "")
    refs = list((article.get("details") or {}).get("experiment_refs") or [])
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    draw_header(draw, title, "先把新聞標題、資料證據與投資解讀分開看。", BLUE)
    cards = [
        ("1 先看問題", title, BLUE, BLUE_SOFT),
        ("2 再看證據", snippets[0] if snippets else "文章沒有可抽取的數字句，請回主文檢視完整資料。", TEAL, TEAL_SOFT),
        ("3 再看範圍", snippets[-1] if len(snippets) > 1 else "這是懶人包摘要，不取代主文的資料來源與方法限制。", AMBER, AMBER_SOFT),
    ]
    y = 620
    for label, text, accent, fill in cards:
        rounded(draw, (84, y, 1516, y + 330), fill=fill)
        draw.text((132, y + 48), label, font=load_font(36, bold=True), fill=accent)
        draw_wrapped(draw, (132, y + 118), text, load_font(40), INK, 1260, max_lines=4)
        y += 420
    draw_footer(draw, article_id, refs)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)


def render_numbers(article: dict[str, Any], snippets: list[str], out: Path) -> None:
    title = str(article.get("title") or article.get("id") or "")
    article_id = str(article.get("id") or "")
    refs = list((article.get("details") or {}).get("experiment_refs") or [])
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(img)
    draw_header(draw, "關鍵數字怎麼讀", title, TEAL)
    y = 610
    palette = [(BLUE, BLUE_SOFT), (TEAL, TEAL_SOFT), (AMBER, AMBER_SOFT), (RED, "#FCE8EB")]
    for idx, snippet in enumerate((snippets or ["完整數字請回主文與資料來源。"])[:4]):
        accent, fill = palette[idx % len(palette)]
        x = 84 if idx % 2 == 0 else 828
        if idx % 2 == 0 and idx:
            y += 430
        rounded(draw, (x, y, x + 688, y + 370), fill=fill)
        draw.text((x + 42, y + 42), metric_label(snippet), font=load_font(58, bold=True), fill=accent)
        draw_wrapped(draw, (x + 42, y + 128), snippet, load_font(32), INK, 590, max_lines=5)
    rounded(draw, (84, 1535, 1516, 1848), fill=CARD)
    draw.text((132, 1592), "讀法", font=load_font(42, bold=True), fill=TEAL)
    draw_wrapped(
        draw,
        (132, 1666),
        "這些數字是主文中已揭露的觀察或實驗結果；懶人包只做整理，不新增推論，也不把 null result 包裝成交易訊號。",
        load_font(38),
        INK,
        1250,
        max_lines=4,
    )
    draw_footer(draw, article_id, refs)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)


def has_lazypack(content: str) -> bool:
    return bool(re.search(r"^#+\s*.*懶人包.*$", content, flags=re.MULTILINE))


def build_article(article_id: str) -> dict[str, Any]:
    article = find_article(article_id)
    content = str(article.get("content") or "")
    if has_lazypack(content):
        raise SystemExit(f"article already has lazypack section: {article_id}")
    snippets = numeric_snippets(content)
    if len(snippets) < 2:
        snippets.extend(takeaway_snippets(content, limit=4 - len(snippets)))
    out_dir = OUT_ROOT / article_id
    p1 = out_dir / f"{article_id}_lazypack_1_framework.png"
    p2 = out_dir / f"{article_id}_lazypack_2_numbers.png"
    render_framework(article, snippets, p1)
    render_numbers(article, snippets, p2)
    section = (
        "\n\n## 懶人包圖組\n\n"
        f"![懶人包：文章框架]({p1})\n\n"
        f"![懶人包：關鍵數字]({p2})\n"
    )
    draft_dir = DRAFT_ROOT
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft = draft_dir / f"{article_id}.md"
    draft.write_text(content.rstrip() + section + "\n", encoding="utf-8")
    return {
        "id": article_id,
        "title": article.get("title"),
        "images": [str(p1), str(p2)],
        "draft": str(draft),
        "snippets": snippets[:5],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("article_ids", nargs="+", help="mile_id(s) to backfill")
    ap.add_argument("--json", action="store_true", help="print machine-readable summary")
    args = ap.parse_args()

    results = [build_article(article_id) for article_id in args.article_ids]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"{result['id']}: draft={result['draft']}")
            for image in result["images"]:
                print(f"  image={image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
