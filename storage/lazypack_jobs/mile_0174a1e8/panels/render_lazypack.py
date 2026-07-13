#!/usr/bin/env python3
"""Render four evidence-bound VolPred infographic panels as PNG files."""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from itertools import combinations
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


WIDTH = 1600
HEIGHT = 1000
DPI = 150

K1570_RESULTS = "/Users/yhlai0911/volpred-research/experiments/k1570/k1570_results.json"
K1570_README = "/Users/yhlai0911/volpred-research/experiments/k1570/README.md"
K1605_RESULTS = "/Users/yhlai0911/volpred-research/experiments/k1605/k1605_results.json"
K1605_FORMAL_RESULTS = "/Users/yhlai0911/volpred-research/experiments/k1605/k1605_formal_results.json"
K1605_README = "/Users/yhlai0911/volpred-research/experiments/k1605/README.md"
K1606_RESULTS = "/Users/yhlai0911/volpred-research/experiments/k1606/k1606_results.json"
K1606_README = "/Users/yhlai0911/volpred-research/experiments/k1606/README.md"
K1679_RESULTS = "/Users/yhlai0911/volpred-research/experiments/k1679-rev2/k1679-rev2_results.json"
K1679_README = "/Users/yhlai0911/volpred-research/experiments/k1679-rev2/README.md"
ARTICLE = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_0174a1e8/panels/mile_0174a1e8_article.md"

out_dir = "/Users/yhlai0911/volpred-research/storage/lazypack_jobs/mile_0174a1e8/panels"


PAPER = "#FFFFFF"
NAVY = "#13283B"
INK = "#152535"
MUTED = "#5C6B78"
FAINT = "#7C8995"
LINE = "#D9E1E8"
CARD = "#F7F9FB"
BLUE = "#2166A5"
BLUE_SOFT = "#E8F1F8"
TEAL = "#187A72"
TEAL_SOFT = "#E5F3F0"
AMBER = "#A86716"
AMBER_SOFT = "#F8EEDC"
RED = "#A83E3E"
RED_SOFT = "#F8E9E8"


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Evidence JSON must be an object: {path}")
    return data


def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if not text.strip():
        raise ValueError(f"Evidence text is empty: {path}")
    return text


def require(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing evidence field: {path}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"Missing evidence field: {path}") from exc
        else:
            raise KeyError(f"Missing evidence field: {path}")
    return current


def require_number(data: Any, path: str) -> float:
    value = require(data, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {path}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Non-finite evidence at {path}")
    return value


def require_int(data: Any, path: str) -> int:
    value = require(data, path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Expected integer evidence at {path}")
    return value


def require_bool(data: Any, path: str) -> bool:
    value = require(data, path)
    if not isinstance(value, bool):
        raise TypeError(f"Expected boolean evidence at {path}")
    return value


def require_phrase(text: str, phrase: str, path: str) -> None:
    normalized_text = re.sub(r"\s+", " ", text).strip()
    normalized_phrase = re.sub(r"\s+", " ", phrase).strip()
    if normalized_phrase not in normalized_text:
        raise ValueError(f"Required evidence phrase missing from {path}: {phrase}")


def one_row(rows: list[dict[str, Any]], key: str, value: Any) -> dict[str, Any]:
    matches = [row for row in rows if row.get(key) == value]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one row where {key}={value!r}; got {len(matches)}")
    return matches[0]


def row_number(row: dict[str, Any], key: str, context: str) -> float:
    if key not in row:
        raise KeyError(f"Missing evidence field: {context}.{key}")
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric evidence at {context}.{key}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Non-finite evidence at {context}.{key}")
    return value


def display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in {"W", "F", "A"}:
            width += 2
        else:
            width += 1
    return width


def wrap_zh(text: str, max_units: int) -> str:
    """Wrap mixed zh-Hant/ASCII text without relying on Matplotlib auto-wrap."""
    if max_units <= 0:
        raise ValueError("max_units must be positive")
    wrapped: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            wrapped.append("")
            continue
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9./+%<>=_-]*|\s+|.", paragraph)
        line = ""
        for token in tokens:
            token = " " if token.isspace() else token
            candidate = line + token
            if line and display_width(candidate) > max_units:
                wrapped.append(line.rstrip())
                line = token.lstrip()
            else:
                line = candidate
        if line:
            wrapped.append(line.rstrip())
    return "\n".join(wrapped)


def add_text(
    ax: Any,
    registry: list[Any],
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "center",
    max_units: int | None = None,
    max_lines: int | None = None,
    linespacing: float = 1.25,
) -> Any:
    rendered = wrap_zh(text, max_units) if max_units is not None else text
    line_count = rendered.count("\n") + 1
    if max_lines is not None and line_count > max_lines:
        raise ValueError(f"Text needs {line_count} lines but only {max_lines} are allowed: {text}")
    artist = ax.text(
        x,
        y,
        rendered,
        transform=ax.transAxes,
        fontsize=size,
        color=color,
        fontweight=weight,
        ha=ha,
        va=va,
        linespacing=linespacing,
        clip_on=False,
        zorder=10,
    )
    registry.append(artist)
    return artist


def add_card(
    ax: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    face: str = CARD,
    edge: str = LINE,
    radius: float = 0.016,
    linewidth: float = 1.2,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=face,
            edgecolor=edge,
            linewidth=linewidth,
            zorder=1,
        )
    )


def new_canvas(title: str, subtitle: str, accent: str) -> tuple[Any, Any, list[Any]]:
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI, facecolor=PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    registry: list[Any] = []

    ax.add_patch(Rectangle((0, 0.82), 1, 0.18, transform=ax.transAxes, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((0.055, 0.895), 0.007, 0.052, transform=ax.transAxes, facecolor=accent, edgecolor="none"))
    add_text(ax, registry, 0.075, 0.925, title, size=25.5, color=PAPER, weight="bold", max_units=70, max_lines=1)
    add_text(ax, registry, 0.075, 0.858, subtitle, size=12.8, color="#D8E3EC", max_units=132, max_lines=1)
    return fig, ax, registry


def add_footer(ax: Any, registry: list[Any], source: str) -> None:
    ax.plot([0.055, 0.945], [0.085, 0.085], transform=ax.transAxes, color=LINE, linewidth=1.0)
    add_text(
        ax,
        registry,
        0.055,
        0.061,
        source,
        size=9.6,
        color=FAINT,
        va="top",
        max_units=150,
        max_lines=2,
        linespacing=1.15,
    )


def validate_and_save(fig: Any, registry: list[Any], filename: str) -> None:
    """Fail closed if any text is clipped or any two text boxes collide."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.bbox
    boxes: list[tuple[Any, Any]] = []
    for artist in registry:
        bbox = artist.get_window_extent(renderer=renderer)
        if bbox.x0 < canvas.x0 - 1 or bbox.y0 < canvas.y0 - 1 or bbox.x1 > canvas.x1 + 1 or bbox.y1 > canvas.y1 + 1:
            raise RuntimeError(f"Text extends outside canvas: {artist.get_text()!r}")
        boxes.append((artist, bbox))

    for (artist_a, box_a), (artist_b, box_b) in combinations(boxes, 2):
        overlap_w = min(box_a.x1, box_b.x1) - max(box_a.x0, box_b.x0)
        overlap_h = min(box_a.y1, box_b.y1) - max(box_a.y0, box_b.y0)
        if overlap_w > 1 and overlap_h > 1:
            raise RuntimeError(
                "Text collision: "
                f"{artist_a.get_text()!r} overlaps {artist_b.get_text()!r}"
            )

    path = os.path.join(out_dir, filename)
    fig.savefig(
        path,
        format="png",
        dpi=DPI,
        facecolor=PAPER,
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0,
        transparent=False,
    )
    plt.close(fig)


def collect_evidence() -> dict[str, Any]:
    k1570 = load_json(K1570_RESULTS)
    k1605 = load_json(K1605_RESULTS)
    k1605_formal = load_json(K1605_FORMAL_RESULTS)
    k1606 = load_json(K1606_RESULTS)
    k1679 = load_json(K1679_RESULTS)

    k1570_readme = load_text(K1570_README)
    k1605_readme = load_text(K1605_README)
    k1606_readme = load_text(K1606_README)
    k1679_readme = load_text(K1679_README)
    article = load_text(ARTICLE)

    if require(k1570, "experiment_id") != "K1570":
        raise ValueError("Unexpected K1570 experiment_id")
    if require(k1605, "experiment_id") != "k1605":
        raise ValueError("Unexpected K1605 experiment_id")
    if require(k1605_formal, "experiment_id") != "k1605_formal":
        raise ValueError("Unexpected K1605 formal experiment_id")
    if require(k1606, "experiment_id") != "K1606":
        raise ValueError("Unexpected K1606 experiment_id")
    if require(k1679, "experiment_id") != "K1679-rev2":
        raise ValueError("Unexpected K1679-rev2 experiment_id")

    survivors = require(k1570, "summary.positive_holm_harvey_survivors")
    if not isinstance(survivors, list) or not all(isinstance(row, dict) for row in survivors):
        raise TypeError("K1570 survivor evidence must be a list of objects")
    n_tests = require_int(k1570, "summary.n_primary_tests")
    n_survivors = require_int(k1570, "summary.n_positive_holm_harvey_survivors")
    if n_survivors != len(survivors):
        raise ValueError("K1570 survivor count does not match survivor rows")
    combined = one_row(survivors, "signal", "combined_cre_pressure")
    office = one_row(survivors, "signal", "office_market_stress")
    for label, row in (("combined_cre_pressure", combined), ("office_market_stress", office)):
        if row.get("target") != "CMBS" or row.get("outcome") != "log_fwd_rv":
            raise ValueError(f"Unexpected K1570 survivor target/outcome: {label}")
        if not isinstance(row.get("horizon"), int):
            raise TypeError(f"Missing integer horizon for K1570 survivor: {label}")
        if not str(row.get("x_col", "")).endswith("_lag1"):
            raise ValueError(f"K1570 survivor is not bound to a lag-one signal: {label}")
    if combined["horizon"] != office["horizon"]:
        raise ValueError("K1570 survivors do not share one horizon")
    kre_survivors = sum(row.get("target") == "KRE" for row in survivors)
    kbe_survivors = sum(row.get("target") == "KBE" for row in survivors)

    qlike_improvement = require_number(k1606, "primary_KRE.QLIKE_improvement_pct")
    deposit_p = require_number(k1606, "primary_KRE.DM_pvalue")
    deposit_boot_p = require_number(k1606, "primary_KRE.block_bootstrap.p_two_sided")
    require_phrase(require(k1606, "conclusion"), "does NOT add robust incremental OOS predictive power", K1606_RESULTS)

    if require(k1679, "primary_signal_for_verdict") != "true_pit":
        raise ValueError("K1679-rev2 verdict is not bound to true PIT evidence")
    threshold_match = re.search(r"原始顯著性低於\s*([0-9.]+)", article)
    if not threshold_match:
        raise ValueError("Article evidence is missing the raw-significance threshold")
    raw_threshold = float(threshold_match.group(1))
    if not math.isfinite(raw_threshold):
        raise ValueError("Article raw-significance threshold is non-finite")

    true_pit_cells = require(k1679, "summary_true_pit.all_primary_cells")
    if not isinstance(true_pit_cells, list) or not all(isinstance(row, dict) for row in true_pit_cells):
        raise TypeError("K1679-rev2 primary cells must be a list of objects")
    n_cells = len(true_pit_cells)
    raw_sig_count = sum(
        row_number(row, "p_value", "summary_true_pit.all_primary_cells") < raw_threshold
        for row in true_pit_cells
    )
    if require_bool(k1679, "summary_true_pit.any_raw_p_below_05") != (raw_sig_count > 0):
        raise ValueError("K1679-rev2 raw-significance summary disagrees with primary cells")
    if not all(row.get("sign") == "hurts" for row in true_pit_cells):
        raise ValueError("K1679-rev2 true-PIT cell directions are not uniformly 'hurts'")
    strongest_p = require_number(k1679, "summary_true_pit.strongest_primary_cell.p_value")
    strongest_bh = require_number(k1679, "summary_true_pit.strongest_primary_cell.bh_q")
    strongest_bonf = require_number(k1679, "summary_true_pit.strongest_primary_cell.bonferroni")
    if not math.isclose(strongest_p, min(row_number(row, "p_value", "summary_true_pit.all_primary_cells") for row in true_pit_cells)):
        raise ValueError("K1679-rev2 strongest cell is not the minimum raw p-value")

    formal_spec = require(k1605_formal, "results.q45_a75")
    if not isinstance(formal_spec, dict):
        raise TypeError("K1605 formal q45_a75 evidence must be an object")
    n_banks = require_int(k1605_formal, "results.q45_a75.n_banks")
    if require_int(k1605, "diagnostics.n_banks_mb_built") != n_banks:
        raise ValueError("K1605 Phase-1 and formal bank counts disagree")
    formal_oos = require(k1605_formal, "results.q45_a75.oos")
    if not isinstance(formal_oos, dict):
        raise TypeError("K1605 formal OOS evidence must be an object")
    mb_oos: list[tuple[int, float]] = []
    for key, row in formal_oos.items():
        match = re.fullmatch(r"KRE_h([0-9]+)", key)
        if not match:
            continue
        if not isinstance(row, dict) or "rmse_improve_pct" not in row:
            raise KeyError(f"Missing evidence field: results.q45_a75.oos.{key}.rmse_improve_pct")
        improvement = row["rmse_improve_pct"]
        if isinstance(improvement, bool) or not isinstance(improvement, (int, float)):
            raise TypeError(f"Expected numeric evidence at results.q45_a75.oos.{key}.rmse_improve_pct")
        improvement = float(improvement)
        if not math.isfinite(improvement) or improvement >= 0:
            raise ValueError(f"K1605 {key} no longer indicates a forecast-error increase")
        mb_oos.append((int(match.group(1)), -improvement))
    mb_oos.sort()
    if len(mb_oos) != 2:
        raise ValueError(f"Expected two K1605 KRE OOS horizons; got {len(mb_oos)}")
    for horizon in ("h5", "h22"):
        mean = require_number(k1605_formal, f"results.q45_a75.fama_macbeth_boot.{horizon}.mean")
        ci95 = require(k1605_formal, f"results.q45_a75.fama_macbeth_boot.{horizon}.ci95")
        if not isinstance(ci95, list) or len(ci95) != 2:
            raise TypeError(f"K1605 {horizon} CI95 must have two endpoints")
        upper = float(ci95[1])
        if mean >= 0 or not math.isfinite(upper) or upper >= 0:
            raise ValueError(f"K1605 {horizon} no longer supports the stated negative cross-sectional slope")

    require_phrase(k1570_readme, "do not support a broad claim that office-CRE refinancing pressure", K1570_README)
    require_phrase(k1570_readme, "not as direct evidence about bank loan books", K1570_README)
    require_phrase(k1605_readme, "not past return / momentum / a pure value factor", K1605_README)
    require_phrase(k1606_readme, "no robust incremental out-of-sample predictive power", K1606_README)
    require_phrase(k1679_readme, "真正 point-in-time", K1679_README)
    require_phrase(article, "它們不能排成同一場賽跑", ARTICLE)
    require_phrase(article, "不能把它升級成銀行基本面脆弱度排名", ARTICLE)

    return {
        "n_tests": n_tests,
        "n_survivors": n_survivors,
        "cre_horizon": int(combined["horizon"]),
        "combined_t": row_number(combined, "t", "K1570 combined survivor"),
        "combined_p_holm": row_number(combined, "p_holm", "K1570 combined survivor"),
        "office_t": row_number(office, "t", "K1570 office survivor"),
        "office_p_holm": row_number(office, "p_holm", "K1570 office survivor"),
        "kre_survivors": kre_survivors,
        "kbe_survivors": kbe_survivors,
        "qlike_improvement": qlike_improvement,
        "deposit_p": deposit_p,
        "deposit_boot_p": deposit_boot_p,
        "n_deposit_cells": n_cells,
        "raw_sig_count": raw_sig_count,
        "raw_threshold": raw_threshold,
        "strongest_p": strongest_p,
        "strongest_bh": strongest_bh,
        "strongest_bonf": strongest_bonf,
        "n_banks": n_banks,
        "mb_oos": mb_oos,
    }


def render_boundaries(e: dict[str, Any]) -> None:
    fig, ax, text = new_canvas(
        "三種公開指標，回答三個不同問題",
        "資產端關聯、銀行體系資金狀態與市場定價，不能排成同一場誰先誰後的競賽。",
        TEAL,
    )
    add_text(
        ax,
        text,
        0.055,
        0.785,
        "先問每項指標在量什麼，再看它是否通過自己的研究門檻。",
        size=14.3,
        color=MUTED,
        va="top",
        max_units=118,
        max_lines=1,
    )

    cards = [
        (
            0.055,
            "CRE",
            "CRE／辦公室壓力",
            "資產端關聯",
            "觀察公開 CRE 與辦公室市場壓力，是否和未來市場波動仍有關。",
            "邊界：KRE／KBE 無穩健增量關聯",
            BLUE,
            BLUE_SOFT,
        ),
        (
            0.365,
            "H.8",
            "H.8 存款",
            "銀行體系資金狀態",
            "描述全體銀行或規模別存款如何變動，檢查能否增加 KRE 預測準確度。",
            "用途：描述體系資金狀態",
            TEAL,
            TEAL_SOFT,
        ),
        (
            0.675,
            "M/B",
            "市場帳面比",
            "市場折價與後續波動",
            "觀察市場如何替仍上市銀行定價，以及折價是否連結後續股價波動。",
            "邊界：不能當基本面脆弱度排名",
            AMBER,
            AMBER_SOFT,
        ),
    ]
    for x, icon, title, kicker, body, boundary, accent, fill in cards:
        add_card(ax, x, 0.35, 0.27, 0.36, face=fill, edge=accent)
        ax.add_patch(Circle((x + 0.043, 0.66), 0.026, transform=ax.transAxes, facecolor=accent, edgecolor="none", zorder=3))
        add_text(ax, text, x + 0.043, 0.66, icon, size=10.2, color=PAPER, weight="bold", ha="center")
        add_text(ax, text, x + 0.082, 0.66, title, size=15.2, weight="bold", max_units=23, max_lines=1)
        add_text(ax, text, x + 0.028, 0.59, kicker, size=11.2, color=accent, weight="bold", va="top", max_units=32, max_lines=1)
        add_text(ax, text, x + 0.028, 0.548, body, size=12.3, color=INK, va="top", max_units=26, max_lines=3, linespacing=1.35)
        add_text(ax, text, x + 0.028, 0.405, boundary, size=10.8, color=MUTED, va="top", max_units=29, max_lines=2, linespacing=1.25)

    add_card(ax, 0.055, 0.11, 0.89, 0.18, face=NAVY, edge=NAVY)
    add_text(ax, text, 0.077, 0.255, "研究留下的共同邊界", size=11.5, color="#A9C1D3", weight="bold")
    core = (
        f"CRE 對 KRE／KBE 沒有穩健增量關聯，只對 CMBS 留下 {e['cre_horizon']} 日全樣本窄關聯；"
        "存款與 M/B 沒有改善 KRE 的樣本外預測。"
    )
    add_text(ax, text, 0.077, 0.215, core, size=14.6, color=PAPER, weight="bold", va="top", max_units=86, max_lines=2, linespacing=1.32)
    add_footer(ax, text, "資料來源：實驗 K1570／K1605／K1606／K1679-rev2")
    validate_and_save(fig, text, "1_boundaries.png")


def render_cre_exception(e: dict[str, Any]) -> None:
    fig, ax, text = new_canvas(
        "CRE 的窄關聯，只留在 CMBS",
        "通過門檻的結果很少，而且研究設計仍是全樣本落後訊號迴歸。",
        AMBER,
    )

    add_card(ax, 0.055, 0.752, 0.89, 0.045, face=AMBER_SOFT, edge=AMBER)
    add_text(
        ax,
        text,
        0.5,
        0.774,
        "全樣本落後訊號迴歸｜不是獨立樣本外結果",
        size=12.4,
        color=AMBER,
        weight="bold",
        ha="center",
        max_units=90,
        max_lines=1,
    )

    add_card(ax, 0.055, 0.43, 0.27, 0.29, face=NAVY, edge=NAVY)
    add_text(ax, text, 0.19, 0.675, "主要檢定", size=12.6, color="#BBD0DF", weight="bold", ha="center")
    add_text(
        ax,
        text,
        0.19,
        0.575,
        f"{e['n_survivors']} ／ {e['n_tests']}",
        size=39,
        color=PAPER,
        weight="bold",
        ha="center",
    )
    add_text(ax, text, 0.19, 0.485, "組通過多重檢定與統計強度門檻", size=10.8, color="#D7E2EA", ha="center", max_units=44, max_lines=1)

    survivor_cards = [
        (0.355, "綜合 CRE 壓力", e["combined_t"], e["combined_p_holm"], BLUE, BLUE_SOFT),
        (0.655, "辦公室市場壓力", e["office_t"], e["office_p_holm"], TEAL, TEAL_SOFT),
    ]
    for x, title, t_value, p_value, accent, fill in survivor_cards:
        add_card(ax, x, 0.43, 0.29, 0.29, face=fill, edge=accent)
        add_text(ax, text, x + 0.145, 0.68, title, size=14.0, color=accent, weight="bold", ha="center")
        add_text(
            ax,
            text,
            x + 0.145,
            0.635,
            f"CMBS 未來 {e['cre_horizon']} 日波動",
            size=10.8,
            color=MUTED,
            ha="center",
        )
        add_text(ax, text, x + 0.085, 0.545, f"{t_value:.2f}", size=24.5, color=INK, weight="bold", ha="center")
        add_text(ax, text, x + 0.215, 0.545, f"{p_value:.5f}", size=21.5, color=INK, weight="bold", ha="center")
        add_text(ax, text, x + 0.085, 0.48, "統計強度", size=9.8, color=MUTED, ha="center")
        add_text(ax, text, x + 0.215, 0.48, "校正後顯著性", size=9.8, color=MUTED, ha="center")

    add_card(ax, 0.055, 0.135, 0.31, 0.22, face=RED_SOFT, edge=RED)
    add_text(ax, text, 0.21, 0.315, "區域銀行 ETF", size=11.5, color=RED, weight="bold", ha="center")
    add_text(
        ax,
        text,
        0.21,
        0.245,
        f"KRE {e['kre_survivors']} 組｜KBE {e['kbe_survivors']} 組",
        size=24,
        color=INK,
        weight="bold",
        ha="center",
    )
    add_text(ax, text, 0.21, 0.18, "通過同一套門檻的結果", size=10.5, color=MUTED, ha="center")

    add_card(ax, 0.39, 0.135, 0.555, 0.22, face=CARD, edge=LINE)
    add_text(ax, text, 0.42, 0.315, "推論邊界", size=13.5, color=INK, weight="bold")
    add_text(
        ax,
        text,
        0.42,
        0.27,
        f"• {e['n_survivors']} 組都只落在 CMBS 未來 {e['cre_horizon']} 日波動\n• 尚未做獨立樣本外評分\n• 不得外推到銀行實際貸款簿",
        size=11.8,
        color=MUTED,
        va="top",
        max_units=68,
        max_lines=3,
        linespacing=1.4,
    )
    add_footer(ax, text, "資料來源：實驗 K1570 結果 JSON")
    validate_and_save(fig, text, "2_cre_exception.png")


def render_deposit_null(e: dict[str, Any]) -> None:
    fig, ax, text = new_canvas(
        "兩種公開存款訊號，都沒有增加樣本外準確度",
        "一種看全體銀行存款流失；另一種重建當時可見的規模別 H.8 資料。",
        TEAL,
    )

    add_card(ax, 0.055, 0.18, 0.425, 0.57, face=BLUE_SOFT, edge=BLUE)
    add_text(ax, text, 0.08, 0.715, "全體銀行存款流失", size=15.0, color=BLUE, weight="bold")
    add_text(ax, text, 0.08, 0.673, "加入 KRE 基準模型後", size=10.7, color=MUTED)
    add_text(
        ax,
        text,
        0.2675,
        0.575,
        f"{e['qlike_improvement']:.3f}%",
        size=40,
        color=INK,
        weight="bold",
        ha="center",
    )
    add_text(ax, text, 0.2675, 0.5, "QLIKE 改善，幅度極小", size=11.2, color=MUTED, ha="center")

    add_card(ax, 0.078, 0.285, 0.175, 0.14, face=PAPER, edge=LINE)
    add_card(ax, 0.282, 0.285, 0.175, 0.14, face=PAPER, edge=LINE)
    add_text(ax, text, 0.1655, 0.392, "顯著性數值", size=9.7, color=MUTED, ha="center")
    add_text(ax, text, 0.1655, 0.335, f"{e['deposit_p']:.3f}", size=23.5, color=INK, weight="bold", ha="center")
    add_text(ax, text, 0.3695, 0.392, "重抽樣", size=9.7, color=MUTED, ha="center")
    add_text(ax, text, 0.3695, 0.335, f"{e['deposit_boot_p']:.3f}", size=23.5, color=INK, weight="bold", ha="center")
    add_text(ax, text, 0.2675, 0.235, "兩項檢查都未支持穩健改善", size=10.8, color=BLUE, weight="bold", ha="center")

    add_card(ax, 0.52, 0.18, 0.425, 0.57, face=TEAL_SOFT, edge=TEAL)
    add_text(ax, text, 0.545, 0.715, "小型相對大型銀行存款流失", size=15.0, color=TEAL, weight="bold")
    add_text(ax, text, 0.545, 0.673, "按當時可見版本重建", size=10.7, color=MUTED)
    add_text(
        ax,
        text,
        0.7325,
        0.575,
        f"{e['raw_sig_count']} ／ {e['n_deposit_cells']}",
        size=40,
        color=INK,
        weight="bold",
        ha="center",
    )
    add_text(
        ax,
        text,
        0.7325,
        0.5,
        f"格原始顯著性低於 {e['raw_threshold']:.2f}",
        size=11.2,
        color=MUTED,
        ha="center",
    )

    right_metrics = [
        (0.545, "最接近一格", e["strongest_p"] , 4),
        (0.68, "錯誤發現率", e["strongest_bh"], 3),
        (0.815, "家族錯誤率", e["strongest_bonf"], 3),
    ]
    for x, label, value, decimals in right_metrics:
        add_card(ax, x, 0.285, 0.11, 0.14, face=PAPER, edge=LINE)
        add_text(ax, text, x + 0.055, 0.392, label, size=8.8, color=MUTED, ha="center")
        add_text(ax, text, x + 0.055, 0.335, f"{value:.{decimals}f}", size=19.5, color=INK, weight="bold", ha="center")

    add_card(ax, 0.545, 0.2, 0.375, 0.055, face=RED_SOFT, edge=RED)
    add_text(
        ax,
        text,
        0.7325,
        0.2275,
        f"{e['n_deposit_cells']} 格方向皆為預測變差",
        size=10.5,
        color=RED,
        weight="bold",
        ha="center",
    )

    add_card(ax, 0.055, 0.105, 0.89, 0.045, face=CARD, edge=LINE)
    add_text(
        ax,
        text,
        0.5,
        0.1275,
        "解讀邊界：結果不能用來推論價格已先反映存款資訊。",
        size=10.7,
        color=MUTED,
        weight="bold",
        ha="center",
    )
    add_footer(ax, text, "資料來源：實驗 K1606／K1679-rev2 結果 JSON")
    validate_and_save(fig, text, "3_deposit_null.png")


def render_mb_boundary(e: dict[str, Any]) -> None:
    fig, ax, text = new_canvas(
        "M/B 的可說範圍：有橫向關聯，沒有 ETF 預測優勢",
        "市場折價與後續股價波動相連；加入 M/B 後，KRE 預測誤差反而增加。",
        BLUE,
    )

    add_card(ax, 0.055, 0.18, 0.42, 0.57, face=CARD, edge=LINE)
    add_text(ax, text, 0.08, 0.705, "橫向關聯", size=15.0, color=BLUE, weight="bold")
    add_text(ax, text, 0.08, 0.62, f"{e['n_banks']} 家", size=38, color=INK, weight="bold")
    add_text(ax, text, 0.08, 0.555, "仍上市區域銀行", size=11.8, color=MUTED)

    add_card(ax, 0.085, 0.39, 0.13, 0.105, face=BLUE_SOFT, edge=BLUE)
    add_card(ax, 0.315, 0.39, 0.13, 0.105, face=TEAL_SOFT, edge=TEAL)
    add_text(ax, text, 0.15, 0.4425, "M/B 較低", size=12.0, color=BLUE, weight="bold", ha="center")
    add_text(ax, text, 0.38, 0.4425, "後續波動較高", size=11.5, color=TEAL, weight="bold", ha="center")
    ax.add_patch(
        FancyArrowPatch(
            (0.225, 0.4425),
            (0.305, 0.4425),
            transform=ax.transAxes,
            arrowstyle="-|>",
            mutation_scale=18,
            linewidth=2.0,
            color=AMBER,
            zorder=5,
        )
    )
    add_text(
        ax,
        text,
        0.08,
        0.325,
        "同一天把存續銀行排在一起時，較低 M/B 與較高後續股價波動有關。",
        size=12.4,
        color=INK,
        va="top",
        max_units=44,
        max_lines=3,
        linespacing=1.38,
    )
    add_text(ax, text, 0.08, 0.225, "可描述市場折價，不等於基本面脆弱度。", size=10.5, color=MUTED, weight="bold")

    add_card(ax, 0.505, 0.48, 0.44, 0.27, face=NAVY, edge=NAVY)
    add_text(ax, text, 0.725, 0.705, "加入 M/B 後，KRE 預測誤差增加", size=14.0, color=PAPER, weight="bold", ha="center")
    metric_x = [0.615, 0.835]
    for x, (horizon, value) in zip(metric_x, e["mb_oos"], strict=True):
        add_text(ax, text, x, 0.595, f"{value:.2f}%", size=29, color=PAPER, weight="bold", ha="center")
        add_text(ax, text, x, 0.525, f"{horizon} 日", size=10.8, color="#BBD0DF", weight="bold", ha="center")

    add_card(ax, 0.505, 0.18, 0.44, 0.26, face=AMBER_SOFT, edge=AMBER)
    add_text(ax, text, 0.53, 0.402, "明確限制", size=14.0, color=AMBER, weight="bold")
    add_text(
        ax,
        text,
        0.53,
        0.355,
        "• M/B 含股價；尚未完整控制先前報酬、動能或純價值因子\n• 樣本只含仍上市銀行，存在存活者偏差",
        size=11.0,
        color=INK,
        va="top",
        max_units=54,
        max_lines=3,
        linespacing=1.4,
    )
    add_card(ax, 0.53, 0.205, 0.39, 0.05, face=RED_SOFT, edge=RED)
    add_text(ax, text, 0.725, 0.23, "不能稱作銀行基本面脆弱度排序", size=10.7, color=RED, weight="bold", ha="center")

    add_footer(ax, text, "資料來源：實驗 K1605 正式結果 JSON")
    validate_and_save(fig, text, "4_mb_boundary.png")


def main() -> None:
    os.makedirs(out_dir, exist_ok=True)
    evidence = collect_evidence()
    render_boundaries(evidence)
    render_cre_exception(evidence)
    render_deposit_null(evidence)
    render_mb_boundary(evidence)


if __name__ == "__main__":
    main()
