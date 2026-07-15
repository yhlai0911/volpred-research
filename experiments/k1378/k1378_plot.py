#!/usr/bin/env python3
"""Render K1378's corrected, result-driven diagnostic and article charts."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

from k1378 import OOS_END, OOS_START, load_analysis_data  # noqa: E402


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
ASSET_DIR = PROJECT_ROOT / "storage" / "drafts" / "assets"
RESULTS_PATH = HERE / "k1378_results.json"
PERIOD_KEYS = (
    "full_oos",
    "pre_covid_oos",
    "covid_only_oos",
    "post_covid_oos",
    "no_covid_oos",
)
PERIOD_LABELS = {
    "full_oos": "全期",
    "pre_covid_oos": "疫情前",
    "covid_only_oos": "廣義疫情窗",
    "post_covid_oos": "疫情後",
    "no_covid_oos": "排除疫情窗",
}
COLORS = ["#4C72B0", "#55A868", "#C44E52", "#8172B3", "#DD8452"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save_atomic(fig: plt.Figure, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.tmp{destination.suffix}")
    fig.savefig(temporary, dpi=180, bbox_inches="tight", facecolor="white")
    image = plt.imread(temporary)
    if image.ndim not in (2, 3) or min(image.shape[:2]) < 100:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Rendered chart failed verification: {destination.name}")
    os.replace(temporary, destination)
    plt.close(fig)
    print(f"Saved: {destination}")


def _load_inputs() -> tuple[dict, pd.DatetimeIndex, np.ndarray, np.ndarray, np.ndarray]:
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    if results.get("experiment_id") != "k1378":
        raise RuntimeError("Unexpected results artifact")
    if set(PERIOD_KEYS) - set(results.get("periods", {})):
        raise RuntimeError("Corrected period schema is incomplete; rerun k1378.py first")

    filenames = {
        "gjr": "k1378_losses_gjr.npy",
        "a4f": "k1378_losses_a4f.npy",
        "valid": "k1378_valid_mask.npy",
    }
    expected_hashes = results["metadata"]["saved_array_sha256"]
    for filename in filenames.values():
        path = HERE / filename
        if _sha256(path) != expected_hashes[filename]:
            raise RuntimeError(f"Array hash mismatch: {filename}")

    loss_gjr = np.load(HERE / filenames["gjr"], allow_pickle=False)
    loss_a4f = np.load(HERE / filenames["a4f"], allow_pickle=False)
    valid = np.load(HERE / filenames["valid"], allow_pickle=False)
    frame, _ = load_analysis_data()
    oos_dates = frame.index[(frame.index >= OOS_START) & (frame.index <= OOS_END)]
    if not (len(oos_dates) == len(loss_gjr) == len(loss_a4f) == len(valid)):
        raise RuntimeError("Date/loss array lengths disagree")
    return results, oos_dates, loss_a4f, loss_gjr, valid


def _period_axis_labels(results: dict) -> list[str]:
    return [
        f"{PERIOD_LABELS[key]}\n(n={results['periods'][key]['n']:,})"
        for key in PERIOD_KEYS
    ]


def render_dm_chart(results: dict) -> None:
    values = [results["periods"][key]["dm_t"] for key in PERIOD_KEYS]
    fig, axis = plt.subplots(figsize=(10.2, 5.8))
    bars = axis.bar(_period_axis_labels(results), values, color=COLORS, width=0.62)
    axis.axhline(0.0, color="#777777", linewidth=0.9)
    axis.axhline(3.0, color="#B22222", linestyle="--", linewidth=1.25)
    axis.axhline(-3.0, color="#B22222", linestyle="--", linewidth=1.25)
    for bar, value in zip(bars, values, strict=True):
        offset = 0.10 if value >= 0 else -0.10
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            value + offset,
            f"{value:+.2f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=10,
            fontweight="bold",
        )
    margin = max(0.8, 0.12 * max(abs(value) for value in values))
    axis.set_ylim(min(-3.0, min(values)) - margin, max(3.0, max(values)) + margin)
    axis.set_ylabel("Bartlett-HAC DM t（A4f loss − GJR loss）")
    axis.set_title("K1378：修正後的分期預測損失比較")
    axis.text(
        0.01,
        0.02,
        "負值偏向 A4f；正值偏向 GJR。紅色虛線為 |t|=3 報告門檻。",
        transform=axis.transAxes,
        fontsize=9,
        color="#444444",
    )
    axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    _save_atomic(fig, HERE / "k1378_dm_subperiods.png")


def render_rolling_gap(
    results: dict,
    dates: pd.DatetimeIndex,
    loss_a4f: np.ndarray,
    loss_gjr: np.ndarray,
    valid: np.ndarray,
) -> None:
    difference = np.where(valid, loss_a4f - loss_gjr, np.nan)
    rolling = pd.Series(difference, index=dates).rolling(63, min_periods=40).mean()
    fig, axis = plt.subplots(figsize=(11.0, 5.6))
    axis.plot(rolling.index, rolling, color="#355C7D", linewidth=1.25)
    axis.axhline(0.0, color="#333333", linewidth=0.9)
    axis.axvspan(
        pd.Timestamp(results["metadata"]["covid_exclusion_start"]),
        pd.Timestamp(results["metadata"]["covid_exclusion_end"]),
        color="#C44E52",
        alpha=0.12,
        label="K1378 廣義疫情窗",
    )
    axis.set_ylabel("63 日平均 QLIKE 差（A4f − GJR）")
    axis.set_title("修正後的相對預測損失隨時間變化")
    axis.text(
        0.01,
        0.02,
        "0 以下代表 A4f 在該段期間平均損失較低；單日平方報酬是噪音較高的波動代理。",
        transform=axis.transAxes,
        fontsize=9,
        color="#444444",
    )
    axis.legend(frameon=False, loc="upper right")
    axis.grid(axis="y", alpha=0.23)
    fig.tight_layout()
    _save_atomic(fig, ASSET_DIR / "k1378_loss_gap_rolling.png")


def render_period_gap(results: dict) -> None:
    values = [
        results["periods"][key]["mean_loss_differential"] for key in PERIOD_KEYS
    ]
    fig, axis = plt.subplots(figsize=(10.2, 5.8))
    bars = axis.bar(_period_axis_labels(results), values, color=COLORS, width=0.62)
    axis.axhline(0.0, color="#333333", linewidth=0.9)
    for bar, value in zip(bars, values, strict=True):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:+.3f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=9,
            fontweight="bold",
        )
    axis.set_ylabel("平均 QLIKE 差（A4f − GJR）")
    axis.set_title("修正後的分期平均損失差")
    axis.text(
        0.01,
        0.02,
        "負值代表 A4f 平均損失較低；是否穩健仍以 Bartlett-HAC DM 檢定判讀。",
        transform=axis.transAxes,
        fontsize=9,
        color="#444444",
    )
    axis.grid(axis="y", alpha=0.23)
    fig.tight_layout()
    _save_atomic(fig, ASSET_DIR / "k1378_period_gap_bars.png")


def main() -> None:
    apply_cjk_style()
    results, dates, loss_a4f, loss_gjr, valid = _load_inputs()
    render_dm_chart(results)
    render_rolling_gap(results, dates, loss_a4f, loss_gjr, valid)
    render_period_gap(results)


if __name__ == "__main__":
    main()
