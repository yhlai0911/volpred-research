#!/usr/bin/env python3
"""Render the reader-facing K1649 pinball-loss chart from canonical results."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "k1649" / "K1649_results.json"
OUTPUT = ROOT / "storage" / "drafts" / "article_images" / "K1649_pinball.png"

MODELS = ["HS250", "LinearQR", "ALSExpectile-VaR", "CARE-SAV"]
PANELS = [
    ("TLT_05", "TLT 5%"),
    ("TLT_01", "TLT 1%"),
    ("HYG_05", "HYG 5%"),
    ("HYG_01", "HYG 1%"),
]
COLORS = ["#64748b", "#0f766e", "#ea580c", "#2563eb"]


def main() -> None:
    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    by_panel = payload["by_asset_alpha"]
    values = np.array(
        [
            [by_panel[key]["per_model"][model]["mean_pinball"] for model in MODELS]
            for key, _ in PANELS
        ]
    )

    plt.rcParams["font.sans-serif"] = [
        "Arial Unicode MS",
        "PingFang TC",
        "Noto Sans CJK TC",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(12, 6.2))
    x = np.arange(len(PANELS))
    width = 0.19
    for idx, (model, color) in enumerate(zip(MODELS, COLORS, strict=True)):
        bars = ax.bar(
            x + (idx - 1.5) * width,
            values[:, idx],
            width,
            label=model,
            color=color,
        )
        ax.bar_label(bars, labels=[f"{v:.6f}" for v in values[:, idx]], padding=3, fontsize=8)

    ax.set_title("四種模型的平均預測罰分（越低越好）", fontsize=18, pad=18)
    ax.set_ylabel("平均罰分")
    ax.set_xticks(x, [label for _, label in PANELS])
    ax.grid(axis="y", alpha=0.22)
    ax.legend(ncol=2, frameon=False)
    ax.set_ylim(0, float(values.max()) * 1.22)
    fig.text(
        0.01,
        0.01,
        "資料：VolPred 實驗結果；TLT / HYG，樣本外自 2015-01-01，"
        "每個資產與門檻 2,891 筆。",
        fontsize=9,
        color="#475569",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
