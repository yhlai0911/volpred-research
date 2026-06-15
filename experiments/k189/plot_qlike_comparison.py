"""K189 corrected article charts for mile_48c8328b."""
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
OUT_LOSS = ROOT / "k189_corrected_loss_changes.png"
OUT_DM = ROOT / "k189_corrected_dm_tests.png"


def main() -> None:
    with open(ROOT / "k189_attention_vol_results.json", encoding="utf-8") as f:
        data = json.load(f)

    rows = data["qlike_table"]
    assets = [r["asset"] for r in rows]
    vs_ewma = np.array([r["pct_change_vs_ewma"] for r in rows])
    vs_gjr = np.array([r["pct_change_vs_gjr"] for r in rows])

    fig, ax = plt.subplots(figsize=(9.4, 5.4), dpi=150)
    x = np.arange(len(assets))
    width = 0.34

    b1 = ax.bar(x - width / 2, vs_ewma, width, label="vs 單資產 EWMA", color="#C55A4D")
    b2 = ax.bar(x + width / 2, vs_gjr, width, label="vs GJR-GARCH", color="#2F7D6D")

    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_ylabel("Attention QLIKE 相對變化（%）")
    ax.set_title("K189 corrected rerun: attention 輸 EWMA、方向上贏 GJR")
    ax.axhline(0, color="#222", linewidth=0.8)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.92)
    fig.text(
        0.07,
        0.025,
        "正值 = attention 較差；負值 = attention 較好。OOS: 2023-01-03 至 2024-12-31, n=502。",
        fontsize=8,
        color="#333",
    )

    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            va = "bottom" if h >= 0 else "top"
            offset = 0.02 if h >= 0 else -0.02
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                h + offset,
                f"{h:+.2f}%",
                ha="center",
                va=va,
                fontsize=7,
                color="#222",
            )

    fig.tight_layout(rect=[0, 0.06, 1, 1])
    plt.savefig(OUT_LOSS, bbox_inches="tight")
    plt.close(fig)

    dm_by_asset = {asset: {} for asset in assets}
    for rec in data["dm_tests"]:
        dm_by_asset[rec["asset"]][rec["baseline"]] = rec["dm_t"]

    dm_ewma = np.array([dm_by_asset[a]["EWMA"] for a in assets])
    dm_gjr = np.array([dm_by_asset[a]["GJR"] for a in assets])

    fig, ax = plt.subplots(figsize=(9.4, 5.4), dpi=150)
    b1 = ax.bar(x - width / 2, dm_ewma, width, label="DM vs EWMA", color="#C55A4D")
    b2 = ax.bar(x + width / 2, dm_gjr, width, label="DM vs GJR", color="#2F7D6D")
    ax.axhline(0, color="#222", linewidth=0.8)
    ax.axhline(3, color="#A33", linewidth=0.8, linestyle="--", alpha=0.75)
    ax.axhline(-3, color="#A33", linewidth=0.8, linestyle="--", alpha=0.75)
    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_ylabel("DM t-stat (loss_attention - loss_baseline)")
    ax.set_title("K189 corrected rerun: DM 符號方向")
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.92)
    fig.text(
        0.07,
        0.025,
        "正值 = attention 較差；負值 = attention 較好。紅線為 |t|=3 強度門檻。",
        fontsize=8,
        color="#333",
    )

    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            va = "bottom" if h >= 0 else "top"
            offset = 0.08 if h >= 0 else -0.08
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                h + offset,
                f"{h:+.2f}",
                ha="center",
                va=va,
                fontsize=7,
                color="#222",
            )

    fig.tight_layout(rect=[0, 0.06, 1, 1])
    plt.savefig(OUT_DM, bbox_inches="tight")
    plt.close(fig)

    print(f"saved: {OUT_LOSS}")
    print(f"saved: {OUT_DM}")


if __name__ == "__main__":
    main()
