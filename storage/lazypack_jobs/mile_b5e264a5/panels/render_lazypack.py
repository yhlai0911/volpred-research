#!/usr/bin/env python3
"""Render the K1611 VolPred infographic set with JSON-bound local graphics.

This renderer intentionally uses Pillow only.  It never calls an image model or
network service.  Every displayed statistic is loaded from
``experiments/k1611/k1611_results.json``; derived counts are asserted from their
component fields before drawing.  The README and article are read as context and
validated to be the expected K1611 sources, but prose never overrides JSON.

Outputs (1600 x 1000 px, 150 dpi):

* 1_concept.png  — the reader-facing question, sample, and honest verdict
* 2_method.png   — how the regime test avoids lookahead, plus direct-test results
* 3_results.png  — primary-proxy QLIKE results in a bento grid
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from fontTools.ttLib import TTCollection, TTFont
from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1000
DPI = (150, 150)

NAVY = "#0B1F33"
NAVY_2 = "#15334F"
INK = "#142536"
MUTED = "#5E6D7A"
FAINT = "#8B99A6"
PAPER = "#F4F7FA"
WHITE = "#FFFFFF"
LINE = "#DCE4EA"
SLATE = "#718096"
SLATE_SOFT = "#E9EEF2"
TEAL = "#168C8C"
TEAL_DARK = "#0E6F72"
TEAL_SOFT = "#DDF2F0"
BLUE = "#2D6CDF"
BLUE_SOFT = "#E8F0FF"
AMBER = "#D58A24"
AMBER_SOFT = "#FFF0D7"
RED = "#B64A4A"
RED_SOFT = "#F8E7E6"
GREEN = "#24724F"
GREEN_SOFT = "#E2F2E9"


@dataclass(frozen=True)
class FontFace:
    path: Path
    index: int


@dataclass(frozen=True)
class Fonts:
    regular: FontFace
    bold: FontFace


@dataclass(frozen=True)
class BoundValue:
    key: str
    pointer: str
    raw: Any


REPO = Path(__file__).resolve().parents[4]
DEFAULT_RESULTS = REPO / "experiments/k1611/k1611_results.json"
DEFAULT_README = REPO / "experiments/k1611/README.md"
DEFAULT_ARTICLE = Path(
    "/var/folders/f1/g41vrs0n20v7cx66qzcsd1nc0000gn/T/tmpeq98ncfw_article.md"
)

FONT_PAIRS = [
    (
        FontFace(Path("/System/Library/Fonts/STHeiti Light.ttc"), 0),
        FontFace(Path("/System/Library/Fonts/STHeiti Medium.ttc"), 0),
    ),
    (
        FontFace(Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"), 0),
        FontFace(Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"), 0),
    ),
    (
        FontFace(Path("/Library/Fonts/Arial Unicode.ttf"), 0),
        FontFace(Path("/Library/Fonts/Arial Unicode.ttf"), 0),
    ),
]


class Evidence:
    """Strict JSON-pointer accessor with a manifest for the final audit."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.used: dict[str, BoundValue] = {}

    def get(self, key: str, pointer: str) -> Any:
        cur: Any = self.payload
        if not pointer.startswith("/"):
            raise ValueError(f"JSON pointer must start with '/': {pointer}")
        for raw_part in pointer.lstrip("/").split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                raise KeyError(f"Missing results.json field: {pointer}")
        self.used[key] = BoundValue(key=key, pointer=pointer, raw=cur)
        return cur

    def num(self, key: str, pointer: str) -> float:
        value = self.get(key, pointer)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"Expected numeric field at {pointer}, got {value!r}")
        if not math.isfinite(float(value)):
            raise ValueError(f"Non-finite numeric field at {pointer}")
        return float(value)

    def integer(self, key: str, pointer: str) -> int:
        value = self.get(key, pointer)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Expected integer field at {pointer}, got {value!r}")
        return value

    def text(self, key: str, pointer: str) -> str:
        value = self.get(key, pointer)
        if not isinstance(value, str):
            raise TypeError(f"Expected string field at {pointer}, got {value!r}")
        return value

    def boolean(self, key: str, pointer: str) -> bool:
        value = self.get(key, pointer)
        if not isinstance(value, bool):
            raise TypeError(f"Expected boolean field at {pointer}, got {value!r}")
        return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--article", type=Path, default=DEFAULT_ARTICLE)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent)
    return parser.parse_args()


def load_sources(args: argparse.Namespace) -> tuple[Evidence, str, str]:
    with args.results.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    readme = args.readme.read_text(encoding="utf-8")
    article = args.article.read_text(encoding="utf-8")
    if payload.get("experiment_id") != "K1611":
        raise ValueError("Renderer is data-bound to experiment K1611")
    if "K1611" not in readme or "5,368" not in article:
        raise ValueError("README/article context does not match the K1611 package")
    return Evidence(payload), readme, article


def _font_cmap(face: FontFace) -> set[int]:
    if face.path.suffix.lower() == ".ttc":
        collection = TTCollection(str(face.path), lazy=False)
        try:
            return set(collection.fonts[face.index].getBestCmap())
        finally:
            collection.close()
    font = TTFont(str(face.path), fontNumber=face.index, lazy=False)
    try:
        return set(font.getBestCmap())
    finally:
        font.close()


def choose_fonts(required_text: str) -> Fonts:
    required = {ord(ch) for ch in required_text if not ch.isspace()}
    for regular, bold in FONT_PAIRS:
        if not regular.path.exists() or not bold.path.exists():
            continue
        regular_map = _font_cmap(regular)
        bold_map = _font_cmap(bold)
        if required <= regular_map and required <= bold_map:
            return Fonts(regular=regular, bold=bold)
    missing = "".join(sorted({chr(cp) for cp in required}))
    raise RuntimeError(f"找不到可完整顯示繁體中文的 CJK 字型：{missing}")


class Painter:
    def __init__(self, image: Image.Image, fonts: Fonts) -> None:
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self.fonts = fonts
        self.used_text: list[str] = []

    @lru_cache(maxsize=96)
    def font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        face = self.fonts.bold if bold else self.fonts.regular
        return ImageFont.truetype(str(face.path), size=size, index=face.index)

    def text(
        self,
        xy: tuple[float, float],
        text: str,
        size: int,
        fill: str = INK,
        *,
        bold: bool = False,
        anchor: str | None = None,
        spacing: int = 6,
    ) -> None:
        self.used_text.append(text)
        self.draw.multiline_text(
            xy,
            text,
            font=self.font(size, bold),
            fill=fill,
            anchor=anchor,
            spacing=spacing,
        )

    def text_width(self, text: str, size: int, bold: bool = False) -> int:
        box = self.draw.textbbox((0, 0), text, font=self.font(size, bold))
        return box[2] - box[0]

    def wrap(self, text: str, size: int, max_width: int, bold: bool = False) -> str:
        lines: list[str] = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for char in paragraph:
                trial = current + char
                if current and self.text_width(trial, size, bold) > max_width:
                    lines.append(current.rstrip())
                    current = char.lstrip()
                else:
                    current = trial
            if current:
                lines.append(current.rstrip())
        return "\n".join(lines)

    def rounded(
        self,
        box: tuple[int, int, int, int],
        radius: int,
        fill: str,
        outline: str | None = None,
        width: int = 1,
    ) -> None:
        self.draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def line(self, xy: Iterable[tuple[int, int]], fill: str, width: int = 3) -> None:
        self.draw.line(list(xy), fill=fill, width=width, joint="curve")

    def arrow(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        fill: str = SLATE,
        width: int = 4,
    ) -> None:
        self.draw.line([start, end], fill=fill, width=width)
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        wing = 13
        for delta in (2.55, -2.55):
            point = (
                int(end[0] + wing * math.cos(angle + delta)),
                int(end[1] + wing * math.sin(angle + delta)),
            )
            self.draw.line([end, point], fill=fill, width=width)


def canvas(background: str = WHITE) -> Image.Image:
    return Image.new("RGB", (WIDTH, HEIGHT), background)


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_3(value: float) -> str:
    return f"{value:.3f}"


def fmt_signed_3(value: float) -> str:
    return f"{value:+.3f}".replace("-", "−")


def footer(p: Painter, experiment_id: str) -> None:
    p.line([(76, 936), (1524, 936)], LINE, 2)
    p.text((76, 954), f"資料來源：experiment {experiment_id}", 23, MUTED)
    p.text((1524, 954), "VolPred｜數字直接綁定 results.json", 21, FAINT, anchor="ra")


def draw_check_mark(p: Painter, center: tuple[int, int], color: str = TEAL) -> None:
    x, y = center
    p.draw.ellipse((x - 24, y - 24, x + 24, y + 24), fill=TEAL_SOFT)
    p.line([(x - 12, y), (x - 3, y + 10), (x + 14, y - 10)], color, 5)


def panel_concept(ev: Evidence, fonts: Fonts) -> tuple[Image.Image, list[str]]:
    experiment_id = ev.text("experiment_id", "/experiment_id")
    spy_n = ev.integer("concept.spy_n_oos", "/assets/SPY/proxies/r2/n_oos")
    tw_n = ev.integer("concept.tw_n_oos", "/assets/0050.TW/proxies/r2/n_oos")
    spy_verdict = ev.boolean(
        "concept.spy_regime_dependent_robust", "/verdict/SPY/regime_dependent_robust"
    )
    tw_verdict = ev.boolean(
        "concept.tw_regime_dependent_robust",
        "/verdict/0050.TW/regime_dependent_robust",
    )
    total_n = spy_n + tw_n
    if total_n != 5368:
        raise AssertionError("K1611 OOS total changed; review the panel wording")
    if spy_verdict or tw_verdict:
        raise AssertionError("Verdict changed; 'no robust regime dependence' is no longer valid")

    winners: list[str] = []
    for asset_key in ("SPY", "0050.TW"):
        for proxy in ("r2", "rsov"):
            for regime in ("high", "low"):
                winners.append(
                    ev.text(
                        f"concept.{asset_key}.{proxy}.{regime}.winner",
                        f"/assets/{asset_key}/proxies/{proxy}/regime_subsample_{regime}/winner",
                    )
                )
    if winners != ["GJR"] * 8:
        raise AssertionError("A regime/proxy winner changed; review the concept panel")

    image = canvas(WHITE)
    p = Painter(image, fonts)
    p.draw.rectangle((0, 0, WIDTH, 205), fill=NAVY)
    p.text((76, 52), "市場一恐慌，模型勝負會換人嗎？", 58, WHITE, bold=True)
    p.text(
        (78, 133),
        "台美市場的答案：平均分方向沒換，但不足以支持切換模型",
        28,
        "#CBD8E4",
    )
    p.rounded((1375, 54, 1524, 112), 28, NAVY_2, "#4C6680", 2)
    p.text((1449, 83), experiment_id, 25, WHITE, bold=True, anchor="mm")

    p.rounded((76, 242, 1524, 382), 24, TEAL_SOFT, "#9BD4D0", 2)
    p.text((112, 270), "核心結果", 22, TEAL_DARK, bold=True)
    p.text((112, 309), "高、低 VIX 狀態下，較低的平均 QLIKE 都指向同一模型", 39, INK, bold=True)
    p.text((112, 354), "這是描述性的小幅領先，不是統計上穩健的冠軍。", 25, MUTED)

    # Left: the two candidate models.
    p.rounded((76, 421, 430, 694), 22, PAPER, LINE, 2)
    p.text((105, 449), "每天都出一張預測單", 23, MUTED, bold=True)
    p.rounded((105, 498, 401, 568), 16, WHITE, "#CFD8E1", 2)
    p.draw.rectangle((105, 498, 115, 568), fill=SLATE)
    p.text((136, 519), "平均派｜HAR-RV", 28, INK, bold=True)
    p.rounded((105, 590, 401, 660), 16, WHITE, "#9BD4D0", 2)
    p.draw.rectangle((105, 590, 115, 660), fill=TEAL)
    p.text((136, 611), "不對稱派｜GJR-GARCH", 26, INK, bold=True)

    # Middle: the state split.
    p.arrow((445, 558), (520, 558), SLATE, 4)
    p.rounded((520, 421, 970, 694), 22, WHITE, LINE, 2)
    p.text((745, 457), "用前一日 VIX 分狀態", 27, INK, bold=True, anchor="mm")
    p.rounded((561, 508, 929, 574), 30, AMBER_SOFT, "#EDC277", 2)
    p.draw.ellipse((588, 526, 608, 546), fill=AMBER)
    p.text((626, 527), "高 VIX｜高於過去中位數", 25, INK, bold=True)
    p.rounded((561, 597, 929, 663), 30, BLUE_SOFT, "#AFC7F8", 2)
    p.draw.ellipse((588, 615, 608, 635), fill=BLUE)
    p.text((626, 616), "低 VIX｜不高於過去中位數", 25, INK, bold=True)

    # Right: the honest result.
    p.arrow((986, 558), (1060, 558), SLATE, 4)
    p.rounded((1060, 421, 1524, 694), 22, NAVY, NAVY, 2)
    draw_check_mark(p, (1110, 470), TEAL)
    p.text((1152, 449), "勝負沒有翻盤", 36, WHITE, bold=True)
    p.text((1100, 520), "八個資產 × 代理 × 市況格子", 25, "#C9D7E3")
    p.text((1100, 558), "平均 QLIKE 較低者皆為 GJR", 27, WHITE, bold=True)
    p.line([(1100, 607), (1484, 607)], "#39536C", 2)
    p.text((1100, 626), "但兩市場的穩健市況依賴判定皆為「否」", 24, "#C9D7E3")

    # Evidence strip.
    p.rounded((76, 733, 1524, 897), 22, PAPER, LINE, 2)
    p.text((110, 760), "樣本外檢驗", 22, MUTED, bold=True)
    p.text((110, 804), fmt_int(spy_n), 45, NAVY, bold=True)
    p.text((110, 856), "SPY 交易日", 22, MUTED)
    p.line([(395, 760), (395, 873)], LINE, 2)
    p.text((445, 804), fmt_int(tw_n), 45, NAVY, bold=True)
    p.text((445, 856), "0050 交易日", 22, MUTED)
    p.line([(730, 760), (730, 873)], LINE, 2)
    p.text((780, 804), fmt_int(total_n), 45, TEAL_DARK, bold=True)
    p.text((780, 856), "合計樣本日（由兩市場加總）", 22, MUTED)
    p.line([(1125, 760), (1125, 873)], LINE, 2)
    p.text((1175, 801), "沒有穩健證據", 31, INK, bold=True)
    p.text((1175, 844), "支持高 VIX 時自動換模型", 23, MUTED)

    footer(p, experiment_id)
    return image, p.used_text


def panel_method(ev: Evidence, fonts: Fonts) -> tuple[Image.Image, list[str]]:
    experiment_id = ev.text("experiment_id", "/experiment_id")
    spy_start = ev.text("method.spy_oos_start", "/assets/SPY/proxies/r2/oos_start")
    spy_end = ev.text("method.spy_oos_end", "/assets/SPY/proxies/r2/oos_end")
    tw_start = ev.text("method.tw_oos_start", "/assets/0050.TW/proxies/r2/oos_start")
    tw_end = ev.text("method.tw_oos_end", "/assets/0050.TW/proxies/r2/oos_end")
    spy_n = ev.integer("method.spy_n_oos", "/assets/SPY/proxies/r2/n_oos")
    tw_n = ev.integer("method.tw_n_oos", "/assets/0050.TW/proxies/r2/n_oos")
    instruments = [
        ev.text("method.spy_instrument", "/assets/SPY/regime_instrument"),
        ev.text("method.tw_instrument", "/assets/0050.TW/regime_instrument"),
    ]
    if instruments != ["VIX_lag1_vs_expanding_median"] * 2:
        raise AssertionError("Regime instrument changed; review method panel")

    slope_rows: list[tuple[str, float, float, bool]] = []
    for asset_key, asset_label in (("SPY", "SPY"), ("0050.TW", "0050")):
        for proxy, proxy_label in (("r2", "r²"), ("rsov", "區間＋隔夜")):
            b = ev.num(
                f"method.{asset_key}.{proxy}.slope_b",
                f"/assets/{asset_key}/proxies/{proxy}/regime_slope_test_expanding_median/slope_b",
            )
            pvalue = ev.num(
                f"method.{asset_key}.{proxy}.p_value_b",
                f"/assets/{asset_key}/proxies/{proxy}/regime_slope_test_expanding_median/p_value_b",
            )
            significant = ev.boolean(
                f"method.{asset_key}.{proxy}.slope_sig",
                f"/verdict/{asset_key}/flags/{proxy}/regime_slope_sig_5pct",
            )
            slope_rows.append((f"{asset_label}｜{proxy_label}", b, pvalue, significant))
    if any(row[3] for row in slope_rows):
        raise AssertionError("A direct regime-slope test became significant")

    image = canvas("#FBFCFD")
    p = Painter(image, fonts)
    p.draw.rectangle((76, 48, 246, 58), fill=TEAL)
    p.text((76, 78), "不是分組看誰低，就叫市況效應", 52, NAVY, bold=True)
    p.text((78, 145), "真正要問的是：高低 VIX 是否改變兩模型的誤差差距？", 28, MUTED)

    # Main editorial visual.
    p.rounded((76, 207, 1018, 895), 24, WHITE, LINE, 2)
    p.text((112, 239), "一條不偷看未來的檢驗路徑", 27, INK, bold=True)
    p.text((112, 278), "所有分界與預測，只使用預測日前已知的資料。", 23, MUTED)

    # Timeline rail.
    rail_x = 167
    p.line([(rail_x, 348), (rail_x, 813)], "#B7C5D1", 5)
    steps = [
        (363, "前一日資料", "讀取前一日 VIX；不使用今天或未來數字", NAVY),
        (485, "動態分界", "和截至前一日的歷史中位數比較", AMBER),
        (607, "兩套預測", "平均派與不對稱派同場比較 QLIKE", BLUE),
        (729, "直接斜率檢定", "檢查誤差差距是否真的隨市況改變", TEAL),
    ]
    for y, title, body, color in steps:
        p.draw.ellipse((rail_x - 19, y - 19, rail_x + 19, y + 19), fill=WHITE, outline=color, width=6)
        p.draw.ellipse((rail_x - 7, y - 7, rail_x + 7, y + 7), fill=color)
        p.text((218, y - 28), title, 30, INK, bold=True)
        p.text((218, y + 14), body, 23, MUTED)

    # High/low split mini visual beside dynamic boundary.
    p.arrow((624, 488), (705, 445), AMBER, 3)
    p.arrow((624, 488), (705, 535), BLUE, 3)
    p.rounded((706, 412, 948, 470), 26, AMBER_SOFT, "#EDC277", 2)
    p.text((827, 441), "高 VIX 狀態", 23, INK, bold=True, anchor="mm")
    p.rounded((706, 507, 948, 565), 26, BLUE_SOFT, "#AFC7F8", 2)
    p.text((827, 536), "低 VIX 狀態", 23, INK, bold=True, anchor="mm")

    p.rounded((112, 798, 982, 849), 12, PAPER, LINE, 1)
    p.text((135, 811), "判讀原則：斜率未顯著離開零，就不能說市況改變了勝負。", 22, NAVY, bold=True)
    p.text(
        (112, 862),
        f"SPY：{spy_start} 至 {spy_end}（{fmt_int(spy_n)} 日）　｜　"
        f"0050：{tw_start} 至 {tw_end}（{fmt_int(tw_n)} 日）",
        18,
        FAINT,
    )

    # Annotation rail with the four direct-test results.
    p.rounded((1054, 207, 1524, 895), 24, NAVY, NAVY, 2)
    p.text((1090, 241), "直接檢定結果", 29, WHITE, bold=True)
    p.text((1090, 286), "斜率 b 與 p 值", 23, "#C4D2DE")
    y = 345
    for label, b, pvalue, significant in slope_rows:
        if significant:
            raise AssertionError("Unexpected significant row")
        p.line([(1090, y - 19), (1488, y - 19)], "#344C63", 1)
        p.text((1090, y), label, 23, "#D9E3EB", bold=True)
        p.text((1090, y + 38), f"b = {fmt_signed_3(b)}", 24, WHITE)
        p.text((1488, y + 38), f"p = {fmt_3(pvalue)}", 25, "#73D2CB", bold=True, anchor="ra")
        y += 104
    p.rounded((1088, 749, 1490, 816), 14, TEAL_DARK)
    p.text((1289, 782), "四組皆未形成顯著市況斜率", 22, WHITE, bold=True, anchor="mm")
    p.text((1090, 843), "結論是「證據不足」，不是「模型完全相同」。", 20, "#C4D2DE")

    footer(p, experiment_id)
    return image, p.used_text


def _draw_result_card(
    p: Painter,
    box: tuple[int, int, int, int],
    market: str,
    regime: str,
    n: int,
    har: float,
    gjr: float,
    winner: str,
    state_color: str,
    state_soft: str,
) -> None:
    if winner != "GJR" or not gjr < har:
        raise AssertionError(f"Card direction inconsistent for {market} {regime}")
    x1, y1, x2, y2 = box
    p.rounded(box, 22, WHITE, LINE, 2)
    p.draw.rounded_rectangle((x1, y1, x1 + 12, y2), radius=6, fill=state_color)
    p.text((x1 + 38, y1 + 24), market, 28, NAVY, bold=True)
    p.rounded((x1 + 184, y1 + 20, x1 + 345, y1 + 60), 20, state_soft)
    p.text((x1 + 264, y1 + 40), regime, 20, INK, bold=True, anchor="mm")
    p.text((x2 - 28, y1 + 36), f"n = {fmt_int(n)}", 20, MUTED, anchor="ra")

    label_x = x1 + 38
    value_x = x1 + 274
    rail_x1 = x1 + 365
    rail_x2 = x2 - 34
    rows = [
        (y1 + 102, "平均派 HAR", har, SLATE, SLATE_SOFT, False),
        (y1 + 172, "不對稱派 GJR", gjr, TEAL, TEAL_SOFT, True),
    ]
    max_scale = 2.1
    for y, label, value, color, soft, highlight in rows:
        p.text((label_x, y), label, 22, color if highlight else INK, bold=highlight)
        p.text((value_x, y), fmt_3(value), 28, color, bold=True, anchor="ra")
        p.rounded((rail_x1, y + 3, rail_x2, y + 24), 10, soft)
        fill_x = rail_x1 + int((rail_x2 - rail_x1) * min(value / max_scale, 1.0))
        p.rounded((rail_x1, y + 3, fill_x, y + 24), 10, color)
    p.text((x2 - 28, y2 - 26), "QLIKE 較低", 19, TEAL_DARK, bold=True, anchor="ra")


def panel_results(ev: Evidence, fonts: Fonts) -> tuple[Image.Image, list[str]]:
    experiment_id = ev.text("experiment_id", "/experiment_id")
    cards: list[dict[str, Any]] = []
    for asset_key, market in (("SPY", "美股 SPY"), ("0050.TW", "台股 0050")):
        for regime_key, regime, color, soft in (
            ("high", "高 VIX", AMBER, AMBER_SOFT),
            ("low", "低 VIX", BLUE, BLUE_SOFT),
        ):
            base = f"/assets/{asset_key}/proxies/r2/regime_subsample_{regime_key}"
            cards.append(
                {
                    "market": market,
                    "regime": regime,
                    "n": ev.integer(f"results.{asset_key}.{regime_key}.n", f"{base}/n"),
                    "har": ev.num(f"results.{asset_key}.{regime_key}.qlike_har", f"{base}/qlike_har"),
                    "gjr": ev.num(f"results.{asset_key}.{regime_key}.qlike_gjr", f"{base}/qlike_gjr"),
                    "winner": ev.text(f"results.{asset_key}.{regime_key}.winner", f"{base}/winner"),
                    "color": color,
                    "soft": soft,
                }
            )

    flags: list[bool] = []
    for asset_key in ("SPY", "0050.TW"):
        for proxy in ("r2", "rsov"):
            flags.append(
                ev.boolean(
                    f"results.{asset_key}.{proxy}.slope_sig",
                    f"/verdict/{asset_key}/flags/{proxy}/regime_slope_sig_5pct",
                )
            )
    if flags != [False, False, False, False]:
        raise AssertionError("The four direct slope flags are no longer all false")

    image = canvas(PAPER)
    p = Painter(image, fonts)
    p.text((76, 48), "四種市況，同一個平均分方向", 49, NAVY, bold=True)
    p.text((78, 112), "主要代理 r²｜QLIKE 越低越好｜數值由 results.json 格式化至小數三位", 24, MUTED)
    p.rounded((1268, 43, 1524, 105), 30, NAVY)
    p.text((1396, 74), "QLIKE 比分", 23, WHITE, bold=True, anchor="mm")

    boxes = [
        (76, 174, 782, 405),
        (818, 174, 1524, 405),
        (76, 435, 782, 666),
        (818, 435, 1524, 666),
    ]
    for box, row in zip(boxes, cards, strict=True):
        _draw_result_card(
            p,
            box,
            row["market"],
            row["regime"],
            row["n"],
            row["har"],
            row["gjr"],
            row["winner"],
            row["color"],
            row["soft"],
        )

    # Two bottom bento cells separate descriptive direction from inference.
    p.rounded((76, 704, 944, 898), 22, NAVY, NAVY, 2)
    p.text((112, 736), "讀圖重點", 22, "#BFD0DE", bold=True)
    p.text((112, 779), "四個 r² 市況格子，GJR 的平均 QLIKE 都較低", 31, WHITE, bold=True)
    p.text((112, 828), "但差距小；不能只靠四張平均分卡片宣布顯著冠軍。", 24, "#C9D7E3")

    p.rounded((980, 704, 1524, 898), 22, WHITE, "#9BD4D0", 2)
    p.text((1016, 736), "直接市況斜率檢定", 22, MUTED, bold=True)
    p.text((1016, 775), "四組皆未顯著", 36, TEAL_DARK, bold=True)
    p.text((1016, 826), "沒有穩健證據支持高 VIX 時換模型", 23, INK, bold=True)
    p.text((1016, 862), "「未顯著」不等於「兩模型完全相同」", 20, MUTED)

    footer(p, experiment_id)
    return image, p.used_text


def validate_rendered_text(fonts: Fonts, texts: Iterable[str]) -> None:
    combined = "".join(texts)
    required = {ord(ch) for ch in combined if not ch.isspace()}
    for label, face in (("regular", fonts.regular), ("bold", fonts.bold)):
        cmap = _font_cmap(face)
        missing = sorted(required - cmap)
        if missing:
            chars = "".join(chr(cp) for cp in missing)
            raise RuntimeError(f"{label} CJK font lacks rendered glyphs: {chars}")


def audit_manifest(ev: Evidence) -> None:
    print("\nEvidence manifest (raw values; results.json is authoritative):")
    for bound in ev.used.values():
        print(f"- {bound.key}: {bound.pointer} = {bound.raw!r}")


def main() -> int:
    args = parse_args()
    ev, _readme, _article = load_sources(args)

    # All visible static copy is listed here so a CJK face is chosen before draw.
    font_probe = """
    市場一恐慌模型勝負會換人嗎台美平均分方向不足支持切換核心結果
    高低狀態較低誤差同一描述性小幅領先統計穩健冠軍每天預測單
    平均派不對稱派用前一日分過去中位數沒有翻盤資產代理市況格子
    樣本外檢驗交易日合計證據不是分組看誰低就叫效應真正要問改變
    一條不偷看未來路徑所有分界只使用預測日前已知資料動態兩套
    直接斜率檢定判讀原則離開零結果區間隔夜四組皆未形成顯著結論
    完全相同美股台股讀圖重點數字來源實驗編號由格式化至小數三位
    資料來源數字直接綁定至與四個讀圖未顯著未形成顯著市況斜率
    ；，。：！？｜×＋−²（）「」—→=./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz
    """
    fonts = choose_fonts(font_probe)
    panels = [
        ("1_concept.png", *panel_concept(ev, fonts)),
        ("2_method.png", *panel_method(ev, fonts)),
        ("3_results.png", *panel_results(ev, fonts)),
    ]
    all_text = [text for _, _, texts in panels for text in texts]
    validate_rendered_text(fonts, all_text)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for filename, image, _texts in panels:
        if image.size != (WIDTH, HEIGHT):
            raise AssertionError(f"Unexpected canvas size for {filename}: {image.size}")
        output = args.out_dir / filename
        image.save(output, format="PNG", dpi=DPI, optimize=True)
        if not output.exists() or output.stat().st_size == 0:
            raise IOError(f"PNG output missing or empty: {output}")
        with Image.open(output) as check:
            if check.size != (WIDTH, HEIGHT) or check.mode != "RGB":
                raise AssertionError(f"PNG verification failed: {output}")
        print(f"wrote {output} ({output.stat().st_size:,} bytes)")

    print(
        "font:",
        fonts.regular.path,
        f"(TTC index {fonts.regular.index}, Heiti TC when using STHeiti)",
    )
    audit_manifest(ev)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
