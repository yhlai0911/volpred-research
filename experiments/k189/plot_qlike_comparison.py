"""K189 QLIKE comparison chart — for article mile_7c104f6d."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# CJK font setup
plt.rcParams["font.sans-serif"] = [
    "PingFang TC", "PingFang SC", "Heiti TC", "Hiragino Sans GB",
    "Noto Sans CJK TC", "Microsoft JhengHei", "Arial Unicode MS", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent.parent / "storage" / "articles" / "mile_7c104f6d" / "figures" / "k189_qlike_table.png"


def main() -> None:
    with open(ROOT / "k189_attention_vol_results.json", encoding="utf-8") as f:
        data = json.load(f)

    rows = data["qlike_table"]
    assets = [r["asset"] for r in rows]
    qlike_ewma = np.array([r["qlike_ewma"] for r in rows])
    qlike_gjr = np.array([r["qlike_gjr"] for r in rows])
    qlike_attn = np.array([r["qlike_attn_0.9"] for r in rows])

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=140)
    x = np.arange(len(assets))
    width = 0.27

    b1 = ax.bar(x - width, qlike_ewma, width, label="EWMA (λ=0.94)", color="#7CA6C0")
    b2 = ax.bar(x, qlike_gjr, width, label="GJR-GARCH", color="#2E5E76")
    b3 = ax.bar(x + width, qlike_attn, width, label="跨資產注意力 (α*=0.9)", color="#C97B4A")

    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_ylabel("QLIKE（越接近 0 越好）")
    ax.set_title("K189: 三種波動率預測模型 QLIKE 對比 (OOS 2023-01 ~ 2025-01)")
    ax.axhline(0, color="#222", linewidth=0.6)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.9)

    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h - 0.05, f"{h:.2f}",
                    ha="center", va="top", fontsize=7, color="white")

    plt.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT, bbox_inches="tight")
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
