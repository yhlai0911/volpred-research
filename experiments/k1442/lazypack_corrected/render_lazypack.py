#!/usr/bin/env python3
"""Render the data-bound K1442 official-date-correction lazypack PNG set."""

from __future__ import annotations

import json
import math
import os
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle


RESULTS_PATH = "/Users/yhlai0911/volpred-research/experiments/k1442/k1442_results.json"
README_PATH = "/Users/yhlai0911/volpred-research/experiments/k1442/README.md"
out_dir = "/Users/yhlai0911/volpred-research/experiments/k1442/lazypack_corrected"

WIDTH_PX = 1600
HEIGHT_PX = 1000
DPI = 150

NAVY = "#102A43"
TEXT = "#162A3A"
MUTED = "#52677A"
WHITE = "#FFFFFF"
CANVAS = "#F5F7FA"
BORDER = "#D9E2EC"
BLUE = "#2868D7"
BLUE_LIGHT = "#EDF4FF"
TEAL = "#168A82"
TEAL_LIGHT = "#EAF8F6"
AMBER = "#B86B10"
AMBER_LIGHT = "#FFF5E6"
RED = "#B54850"
RED_LIGHT = "#FFF0F1"
GREEN = "#19734A"
GREEN_LIGHT = "#EAF7F0"

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["savefig.facecolor"] = WHITE


def require(root: Mapping[str, Any], *path: str) -> Any:
    """Return a required nested field and raise a precise error if absent."""
    current: Any = root
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            dotted = ".".join(path)
            raise KeyError(f"缺少 evidence 欄位：{dotted}")
        current = current[key]
    return current


def load_evidence() -> tuple[dict[str, Any], str]:
    with open(RESULTS_PATH, "r", encoding="utf-8") as handle:
        results = json.load(handle)
    with open(README_PATH, "r", encoding="utf-8") as handle:
        readme = handle.read()

    if not isinstance(results, dict):
        raise TypeError("k1442_results.json 頂層必須是 JSON object")
    if not readme.strip():
        raise ValueError("README.md 不可為空")

    experiment_id = require(results, "experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise TypeError("experiment_id 必須是非空字串")
    if experiment_id.upper() not in readme[:240].upper():
        raise ValueError("README 標題與 results.json 的 experiment_id 不一致")
    if "官方日期更正版" not in readme:
        raise ValueError("README 缺少『官方日期更正版』更正狀態")

    return results, readme


def new_figure() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(
        figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI),
        dpi=DPI,
        facecolor=WHITE,
    )
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.axis("off")
    ax.add_patch(Rectangle((0.0, 0.0), 1.0, 1.0, facecolor=CANVAS, edgecolor="none"))
    return fig, ax


def rounded_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    facecolor: str = WHITE,
    edgecolor: str = BORDER,
    linewidth: float = 1.2,
    radius: float = 0.014,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
        )
    )


def draw_header(ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.add_patch(Rectangle((0.0, 0.835), 1.0, 0.165, facecolor=NAVY, edgecolor="none"))
    ax.add_patch(Rectangle((0.055, 0.842), 0.062, 0.005, facecolor=TEAL, edgecolor="none"))
    ax.text(
        0.055,
        0.925,
        title,
        color=WHITE,
        fontsize=28,
        fontweight="bold",
        ha="left",
        va="center",
    )
    ax.text(
        0.055,
        0.872,
        subtitle,
        color="#D8E4EF",
        fontsize=13.5,
        ha="left",
        va="center",
    )


def draw_footer(ax: plt.Axes, experiment_label: str) -> None:
    ax.plot([0.055, 0.945], [0.092, 0.092], color=BORDER, linewidth=1.0)
    ax.text(
        0.055,
        0.062,
        f"資料來源：實驗 {experiment_label}",
        color=MUTED,
        fontsize=10.5,
        ha="left",
        va="center",
    )
    ax.text(
        0.945,
        0.062,
        "日期來源：ALFRED／BLS 官方 CPI 發布日曆",
        color=MUTED,
        fontsize=10.5,
        ha="right",
        va="center",
    )


def draw_summary_card(
    ax: plt.Axes,
    x: float,
    label: str,
    value: str,
    note: str,
    accent: str,
) -> None:
    y, width, height = 0.655, 0.270, 0.135
    rounded_box(ax, x, y, width, height)
    ax.add_patch(Rectangle((x, y + height - 0.007), width, 0.007, facecolor=accent, edgecolor="none"))
    ax.text(x + 0.018, 0.757, label, color=MUTED, fontsize=11.5, ha="left", va="center")
    ax.text(
        x + 0.018,
        0.711,
        value,
        color=TEXT,
        fontsize=26,
        fontweight="bold",
        ha="left",
        va="center",
    )
    ax.text(x + 0.018, 0.674, note, color=MUTED, fontsize=10.5, ha="left", va="center")


def validate_date_audit(results: Mapping[str, Any]) -> dict[str, Any]:
    legacy_dates = require(results, "date_correction_audit", "legacy_dates")
    official_dates = require(results, "date_correction_audit", "official_dates")
    removed_dates = require(results, "date_correction_audit", "removed_legacy_dates")
    added_dates = require(results, "date_correction_audit", "added_official_dates")
    legacy_n = require(results, "date_correction_audit", "legacy_metrics", "n_events")
    official_n = require(
        results,
        "date_correction_audit",
        "date_only_comparison",
        "official_dates_same_legacy_window",
        "n_events",
    )
    event_n = require(results, "cpi_event_study", "n_events")

    for field_name, values in (
        ("legacy_dates", legacy_dates),
        ("official_dates", official_dates),
        ("removed_legacy_dates", removed_dates),
        ("added_official_dates", added_dates),
    ):
        if not isinstance(values, list):
            raise TypeError(f"date_correction_audit.{field_name} 必須是 list")
        for value in values:
            if not isinstance(value, str) or len(value) != 10:
                raise TypeError(f"date_correction_audit.{field_name} 含非 YYYY-MM-DD 日期")

    if len(legacy_dates) != legacy_n:
        raise ValueError("legacy_dates 筆數與 legacy_metrics.n_events 不一致")
    if len(official_dates) != official_n or official_n != event_n:
        raise ValueError("官方日期筆數與官方事件樣本數不一致")

    legacy_only = [date for date in legacy_dates if date not in set(official_dates)]
    official_only = [date for date in official_dates if date not in set(legacy_dates)]
    if legacy_only != removed_dates:
        raise ValueError("removed_legacy_dates 與兩組日期的集合差不一致")
    if official_only != added_dates:
        raise ValueError("added_official_dates 與兩組日期的集合差不一致")

    replacements_by_month: dict[str, str] = {}
    for date in added_dates:
        month = date[:7]
        if month in replacements_by_month:
            raise ValueError("同月份出現多個新增官方日期，版面無法唯一配對")
        replacements_by_month[month] = date

    rows: list[tuple[str, str | None]] = []
    used_replacements: set[str] = set()
    for old_date in removed_dates:
        replacement = replacements_by_month.get(old_date[:7])
        if replacement is not None:
            if replacement in used_replacements:
                raise ValueError("新增官方日期被重複配對")
            used_replacements.add(replacement)
        rows.append((old_date, replacement))

    if used_replacements != set(added_dates):
        raise ValueError("有新增官方日期無法依年月配對至舊日期")
    if not rows:
        raise ValueError("日期稽核沒有可呈現的更正列")

    return {
        "legacy_n": legacy_n,
        "official_n": official_n,
        "rows": rows,
        "changed_n": len(added_dates),
        "removed_n": sum(replacement is None for _, replacement in rows),
    }


def render_date_audit(results: Mapping[str, Any], experiment_label: str) -> None:
    audit = validate_date_audit(results)
    rows: list[tuple[str, str | None]] = audit["rows"]

    fig, ax = new_figure()
    draw_header(
        ax,
        f"{experiment_label} 官方日期更正｜日期稽核",
        "以官方 CPI 發布日逐場重核，保留舊版產物作為不可變更的稽核證據",
    )

    draw_summary_card(
        ax,
        0.055,
        "舊版事件樣本",
        f"{audit['legacy_n']} 場",
        "舊版日期清單",
        AMBER,
    )
    draw_summary_card(
        ax,
        0.365,
        "官方事件樣本",
        f"{audit['official_n']} 場",
        "依官方發布日重建",
        TEAL,
    )
    draw_summary_card(
        ax,
        0.675,
        "不符官方日曆",
        f"{len(rows)} 個舊日期",
        f"{audit['changed_n']} 場改期｜{audit['removed_n']} 場移除",
        RED,
    )

    ax.text(
        0.055,
        0.610,
        "舊日期與官方處理",
        color=TEXT,
        fontsize=15,
        fontweight="bold",
        ha="left",
        va="center",
    )

    table_x, table_y, table_w, table_h = 0.055, 0.130, 0.890, 0.445
    header_h = 0.060
    rounded_box(ax, table_x, table_y, table_w, table_h, radius=0.012)
    ax.add_patch(
        Rectangle(
            (table_x, table_y + table_h - header_h),
            table_w,
            header_h,
            facecolor="#E8EEF4",
            edgecolor="none",
        )
    )
    header_y = table_y + table_h - header_h / 2
    ax.text(0.095, header_y, "舊版日期", color=TEXT, fontsize=11.5, fontweight="bold", va="center")
    ax.text(0.390, header_y, "官方日期", color=TEXT, fontsize=11.5, fontweight="bold", va="center")
    ax.text(0.765, header_y, "稽核結果", color=TEXT, fontsize=11.5, fontweight="bold", va="center")

    body_h = table_h - header_h
    row_h = body_h / len(rows)
    for index, (old_date, replacement) in enumerate(rows):
        row_top = table_y + body_h - index * row_h
        row_bottom = row_top - row_h
        row_center = (row_top + row_bottom) / 2
        if index:
            ax.plot([table_x, table_x + table_w], [row_top, row_top], color=BORDER, linewidth=0.8)

        ax.text(0.095, row_center, old_date, color=TEXT, fontsize=13.5, ha="left", va="center")
        if replacement is None:
            ax.text(0.390, row_center, "—", color=MUTED, fontsize=13.5, ha="left", va="center")
            ax.text(0.765, row_center, "移除（該月無官方事件）", color=RED, fontsize=12.5, ha="left", va="center")
        else:
            ax.text(0.365, row_center, "→", color=MUTED, fontsize=13.5, ha="left", va="center")
            ax.text(0.390, row_center, replacement, color=TEXT, fontsize=13.5, ha="left", va="center")
            ax.text(0.765, row_center, "更正日期", color=TEAL, fontsize=12.5, ha="left", va="center")

    draw_footer(ax, experiment_label)
    fig.savefig(
        os.path.join(out_dir, "1_date_audit.png"),
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        pad_inches=0,
    )
    plt.close(fig)


def ensure_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} 必須是數值")
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} 必須是有限數值")
    return float(value)


def ensure_ci(value: Any, field_name: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise TypeError(f"{field_name} 必須是兩端點陣列")
    lower = ensure_number(value[0], f"{field_name}[0]")
    upper = ensure_number(value[1], f"{field_name}[1]")
    if lower > upper:
        raise ValueError(f"{field_name} 下界不可大於上界")
    return lower, upper


def format_pct(value: float, decimals: int = 2, *, plus_for_positive: bool = False) -> str:
    if value < 0:
        sign = "−"
    elif value > 0 and plus_for_positive:
        sign = "+"
    else:
        sign = ""
    return f"{sign}{abs(value):.{decimals}f}%"


def format_ci(ci: tuple[float, float]) -> str:
    return f"[{format_pct(ci[0], plus_for_positive=True)}, {format_pct(ci[1], plus_for_positive=True)}]"


def validate_primary_results(results: Mapping[str, Any]) -> dict[str, Any]:
    event_n = require(results, "cpi_event_study", "n_events")
    alpha = ensure_number(
        require(results, "cpi_event_study", "primary_release_day_decline_tests", "bonferroni_alpha"),
        "primary_release_day_decline_tests.bonferroni_alpha",
    )

    validated: dict[str, Any] = {"event_n": event_n, "assets": {}}
    for asset in ("MOVE", "VIX"):
        prefix = ("cpi_event_study", "primary_release_day_decline_tests", asset)
        mean = ensure_number(require(results, *prefix, "mean"), f"{asset}.mean")
        negative_count = require(results, *prefix, "negative_count")
        n_nonzero = require(results, *prefix, "n_nonzero")
        frequency = ensure_number(
            require(results, *prefix, "negative_frequency_pct"),
            f"{asset}.negative_frequency_pct",
        )
        wilcoxon_p = ensure_number(
            require(results, *prefix, "wilcoxon_one_sided_p"),
            f"{asset}.wilcoxon_one_sided_p",
        )
        ci = ensure_ci(require(results, *prefix, "bootstrap_mean", "ci"), f"{asset}.bootstrap_mean.ci")
        ci_level = ensure_number(
            require(results, *prefix, "bootstrap_mean", "ci_level"),
            f"{asset}.bootstrap_mean.ci_level",
        )
        robust_decline = require(results, *prefix, "robust_decline")

        if not isinstance(event_n, int) or isinstance(event_n, bool):
            raise TypeError("cpi_event_study.n_events 必須是整數")
        if not isinstance(negative_count, int) or isinstance(negative_count, bool):
            raise TypeError(f"{asset}.negative_count 必須是整數")
        if not isinstance(n_nonzero, int) or isinstance(n_nonzero, bool):
            raise TypeError(f"{asset}.n_nonzero 必須是整數")
        if n_nonzero != event_n:
            raise ValueError(f"{asset}.n_nonzero 與 cpi_event_study.n_events 不一致")
        expected_frequency = negative_count / n_nonzero * 100.0
        if not math.isclose(frequency, expected_frequency, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError(f"{asset}.negative_frequency_pct 與場次比例不一致")
        if type(robust_decline) is not bool:
            raise TypeError(f"{asset}.robust_decline 必須是 boolean")
        expected_gate = wilcoxon_p < alpha and ci[1] < 0.0
        if robust_decline != expected_gate:
            raise ValueError(f"{asset}.robust_decline 與預設 gate 規則不一致")

        validated["assets"][asset] = {
            "mean": mean,
            "negative_count": negative_count,
            "n_nonzero": n_nonzero,
            "frequency": frequency,
            "ci": ci,
            "ci_level": ci_level,
            "robust_decline": robust_decline,
            "ci_crosses_zero": ci[0] <= 0.0 <= ci[1],
        }

    return validated


def draw_metric_card(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    label: str,
    value: str,
    note: str,
    accent: str,
    facecolor: str,
    value_size: float,
) -> None:
    rounded_box(ax, x, y, width, height, facecolor=facecolor, edgecolor=BORDER)
    ax.add_patch(Rectangle((x, y + height - 0.007), width, 0.007, facecolor=accent, edgecolor="none"))
    ax.text(
        x + 0.018,
        y + height - 0.035,
        label,
        color=MUTED,
        fontsize=11.5,
        fontweight="bold",
        ha="left",
        va="center",
    )
    ax.text(
        x + 0.018,
        y + height * 0.50,
        value,
        color=TEXT,
        fontsize=value_size,
        fontweight="bold",
        ha="left",
        va="center",
    )
    ax.text(
        x + 0.018,
        y + 0.025,
        note,
        color=MUTED,
        fontsize=10.5,
        ha="left",
        va="center",
    )


def draw_gate_item(
    ax: plt.Axes,
    x: float,
    y: float,
    asset: str,
    passed: bool,
    ci_crosses_zero: bool,
) -> None:
    color = GREEN if passed else RED
    circle_face = GREEN_LIGHT if passed else RED_LIGHT
    ax.add_patch(Circle((x, y), 0.016, facecolor=circle_face, edgecolor=color, linewidth=1.4))
    if passed:
        ax.plot(
            [x - 0.008, x - 0.002, x + 0.009],
            [y, y - 0.007, y + 0.008],
            color=color,
            linewidth=2.0,
            solid_capstyle="round",
            solid_joinstyle="round",
        )
    else:
        ax.plot(
            [x - 0.006, x + 0.006],
            [y - 0.006, y + 0.006],
            color=color,
            linewidth=1.8,
            solid_capstyle="round",
        )
        ax.plot(
            [x - 0.006, x + 0.006],
            [y + 0.006, y - 0.006],
            color=color,
            linewidth=1.8,
            solid_capstyle="round",
        )
    status = "通過預設描述性下降門檻" if passed else "未通過預設描述性下降門檻"
    reason = "（信賴區間跨零）" if (not passed and ci_crosses_zero) else ""
    ax.text(
        x + 0.026,
        y,
        f"{asset}：{status}{reason}",
        color=TEXT,
        fontsize=11.5,
        fontweight="bold",
        ha="left",
        va="center",
    )


def render_corrected_results(results: Mapping[str, Any], experiment_label: str) -> None:
    primary = validate_primary_results(results)
    move = primary["assets"]["MOVE"]
    vix = primary["assets"]["VIX"]

    fig, ax = new_figure()
    draw_header(
        ax,
        f"{experiment_label} 更正後結果｜官方發布日樣本",
        "日頻描述性事件研究；呈現樣本關聯，不作 CPI 因果或交易方向推論",
    )

    draw_metric_card(
        ax,
        0.055,
        0.610,
        0.200,
        0.180,
        label="官方事件樣本",
        value=f"{primary['event_n']} 場",
        note="官方 CPI 發布日",
        accent=NAVY,
        facecolor=WHITE,
        value_size=29,
    )
    draw_metric_card(
        ax,
        0.275,
        0.610,
        0.315,
        0.180,
        label="MOVE｜發布日平均變化",
        value=format_pct(move["mean"]),
        note="發布日收盤對收盤",
        accent=TEAL,
        facecolor=TEAL_LIGHT,
        value_size=31,
    )
    draw_metric_card(
        ax,
        0.610,
        0.610,
        0.335,
        0.180,
        label="VIX｜發布日平均變化",
        value=format_pct(vix["mean"]),
        note="發布日收盤對收盤",
        accent=AMBER,
        facecolor=AMBER_LIGHT,
        value_size=31,
    )

    draw_metric_card(
        ax,
        0.055,
        0.400,
        0.430,
        0.170,
        label="MOVE｜發布日下跌頻率",
        value=format_pct(move["frequency"], decimals=1),
        note=f"{move['negative_count']}／{move['n_nonzero']} 場為負",
        accent=TEAL,
        facecolor=WHITE,
        value_size=29,
    )
    draw_metric_card(
        ax,
        0.515,
        0.400,
        0.430,
        0.170,
        label="VIX｜發布日下跌頻率",
        value=format_pct(vix["frequency"], decimals=1),
        note=f"{vix['negative_count']}／{vix['n_nonzero']} 場為負",
        accent=AMBER,
        facecolor=WHITE,
        value_size=29,
    )

    draw_metric_card(
        ax,
        0.055,
        0.190,
        0.430,
        0.170,
        label="MOVE｜重抽樣平均值區間",
        value=format_ci(move["ci"]),
        note=f"{move['ci_level'] * 100:.1f}% 信賴水準",
        accent=TEAL,
        facecolor=TEAL_LIGHT,
        value_size=22,
    )
    draw_metric_card(
        ax,
        0.515,
        0.190,
        0.430,
        0.170,
        label="VIX｜重抽樣平均值區間",
        value=format_ci(vix["ci"]),
        note=f"{vix['ci_level'] * 100:.1f}% 信賴水準",
        accent=AMBER,
        facecolor=AMBER_LIGHT,
        value_size=22,
    )

    rounded_box(ax, 0.055, 0.095, 0.890, 0.065, facecolor=WHITE, edgecolor=BORDER, radius=0.010)
    ax.plot([0.500, 0.500], [0.108, 0.147], color=BORDER, linewidth=1.0)
    draw_gate_item(ax, 0.080, 0.128, "MOVE", move["robust_decline"], move["ci_crosses_zero"])
    draw_gate_item(ax, 0.540, 0.128, "VIX", vix["robust_decline"], vix["ci_crosses_zero"])

    draw_footer(ax, experiment_label)
    fig.savefig(
        os.path.join(out_dir, "2_corrected_results.png"),
        dpi=DPI,
        facecolor=WHITE,
        edgecolor="none",
        pad_inches=0,
    )
    plt.close(fig)


def main() -> None:
    results, _readme = load_evidence()
    experiment_id = require(results, "experiment_id")
    experiment_label = experiment_id.upper()

    os.makedirs(out_dir, exist_ok=True)
    render_date_audit(results, experiment_label)
    render_corrected_results(results, experiment_label)


if __name__ == "__main__":
    main()
