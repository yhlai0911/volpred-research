#!/usr/bin/env python3
"""Render reader-facing K1010 charts directly from certified results JSON."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[4]
RESULTS = ROOT / "experiments" / "k1010" / "k1010_results.json"
OUT_DIR = Path(__file__).resolve().parent


def _set_font() -> None:
    candidates = ["PingFang TC", "Arial Unicode MS", "Heiti TC", "Noto Sans CJK TC"]
    available = {font.name for font in fm.fontManager.ttflist}
    for candidate in candidates:
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False


def _load() -> dict:
    with RESULTS.open(encoding="utf-8") as handle:
        return json.load(handle)


def render_calibration(data: dict) -> Path:
    source = data["calibration_deviation_mad"]
    labels = {
        "A4f_t": "恐慌指標模型＋厚尾分布",
        "GJR_Normal": "壞消息模型＋鐘形分布",
        "GJR_QR": "壞消息模型＋滾動校正",
        "A4f_Normal": "恐慌指標模型＋鐘形分布",
        "Direct_QR": "直接滾動校正",
        "A4f_QR": "恐慌指標模型＋滾動校正",
    }
    ordered = sorted(source, key=source.get, reverse=True)
    values = [source[key] for key in ordered]
    names = [labels[key] for key in ordered]
    colors = ["#d95f59" if key == "A4f_QR" else "#3c78a8" if key == "A4f_t" else "#8ea9c1" for key in ordered]

    fig, ax = plt.subplots(figsize=(12, 7), dpi=160)
    bars = ax.barh(names, values, color=colors)
    ax.set_title("說幾％，最後有沒有真的發生幾％？", fontsize=19, fontweight="bold", pad=16)
    ax.set_xlabel("九個機率刻度的平均偏差，越低越好", fontsize=12)
    ax.grid(axis="x", alpha=0.2)
    ax.spines[["top", "right", "left"]].set_visible(False)
    for bar, value in zip(bars, values, strict=True):
        ax.text(value + max(values) * 0.015, bar.get_y() + bar.get_height() / 2, f"{value:.4f}", va="center", fontsize=11)
    ax.text(0, -1.05, "資料：SPY 與 VIX；可評估期間 1,325 個交易日", fontsize=10, color="#555555")
    fig.tight_layout()
    output = OUT_DIR / "k1010_calibration_comparison.png"
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def render_breaches(data: dict) -> Path:
    source = data["var_es_backtest"]
    keys = [
        "A4f_t_alpha0.01",
        "A4f_Normal_alpha0.01",
        "GJR_Normal_alpha0.01",
        "A4f_QR_med_alpha0.01",
    ]
    labels = [
        "恐慌指標模型＋厚尾分布",
        "恐慌指標模型＋鐘形分布",
        "壞消息模型＋鐘形分布",
        "恐慌指標模型＋滾動校正",
    ]
    values = [source[key]["violation_rate"] for key in keys]
    target = source[keys[0]]["expected_rate"]
    colors = ["#3c78a8", "#8ea9c1", "#8ea9c1", "#d95f59"]

    fig, ax = plt.subplots(figsize=(12, 7), dpi=160)
    bars = ax.bar(labels, values, color=colors, width=0.62)
    ax.axhline(target, color="#222222", linestyle="--", linewidth=1.5, label=f"模型承諾：{target:.0f}%")
    ax.set_title("模型說百日一次，實際多久破線一次？", fontsize=19, fontweight="bold", pad=16)
    ax.set_ylabel("實際破線比例（%）", fontsize=12)
    ax.set_ylim(0, max(values) * 1.22)
    ax.grid(axis="y", alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", rotation=10)
    for bar, value, key in zip(bars, values, keys, strict=True):
        count = source[key]["violations"]
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.18, f"{value:.2f}%\n({count} 次)", ha="center", va="bottom", fontsize=11)
    ax.legend(frameon=False, loc="upper left")
    ax.text(-0.45, -1.5, "資料：同一批 1,325 個交易日；四種做法使用相同檢驗樣本", fontsize=10, color="#555555")
    fig.tight_layout()
    output = OUT_DIR / "k1010_one_pct_breaches.png"
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def main() -> None:
    _set_font()
    data = _load()
    for path in (render_calibration(data), render_breaches(data)):
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
