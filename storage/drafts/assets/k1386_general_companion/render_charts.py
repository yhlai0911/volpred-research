from pathlib import Path

import matplotlib.pyplot as plt


OUT = Path(__file__).resolve().parent / "k1386_qlike_comparison.png"
ROUGH_OUT = Path(__file__).resolve().parent / "k1386_hurst_estimates.png"
MODELS = ["HAR", "單市場近似", "跨市場近似"]
VALUES = [0.37534907, 0.47163477, 0.47314873]


def main() -> None:
    plt.rcParams["font.sans-serif"] = ["Heiti TC", "Arial Unicode MS", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(9.6, 5.4))
    bars = ax.bar(MODELS, VALUES, color=["#16877a", "#6d7f90", "#9a6a35"], width=0.62)
    ax.set_title("隔日波動預測損失：簡單 HAR 較低", fontsize=18, weight="bold", pad=16)
    ax.set_ylabel("平均 QLIKE（越低越好）")
    ax.set_ylim(0, 0.55)
    ax.grid(axis="y", alpha=0.2)
    for bar, value in zip(bars, VALUES):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.012, f"{value:.6f}", ha="center", fontsize=12)
    fig.text(0.98, 0.015, "K1386｜n=1,097｜2022-01-03 至 2026-05-19", ha="right", color="#5d6b78")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(OUT, dpi=180, bbox_inches="tight")
    plt.close(fig)

    assets = ["SPY", "QQQ", "GLD"]
    hurst = [0.103081, 0.093565, 0.029357]
    fig, ax = plt.subplots(figsize=(9.6, 5.4))
    bars = ax.bar(assets, hurst, color=["#1c4563", "#16877a", "#b87627"], width=0.6)
    ax.axhline(0.5, color="#9a3d45", linestyle="--", linewidth=1.8, label="一般布朗運動 H=0.5")
    ax.set_title("三個市場的日波動路徑都呈現低 H", fontsize=18, weight="bold", pad=16)
    ax.set_ylabel("結構函數 Hurst 估計")
    ax.set_ylim(0, 0.58)
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", alpha=0.2)
    for bar, value in zip(bars, hurst):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.012, f"{value:.3f}", ha="center", fontsize=12)
    fig.text(0.98, 0.015, "K1386｜樣本內 2010-01-04 至 2021-12-31", ha="right", color="#5d6b78")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(ROUGH_OUT, dpi=180, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
