from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "k1428_results.json"


def load_results() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def plot_claim_support(data: dict) -> None:
    findings = data["findings"]
    labels = [f["id"] for f in findings]
    counts = [len(f["evidence"]) for f in findings]
    titles = [
        "別急著押 DL",
        "先把 benchmark 做公平",
        "看 economic value",
        "realized measure 會翻盤",
        "先做高頻 baseline",
    ]

    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#4063D8", "#389826", "#CB3C33", "#9558B2", "#E36C2F"]
    bars = ax.barh(labels, counts, color=colors)
    ax.set_xlabel("支持此主張的 primary sources 數")
    ax.set_title("K1428 文獻訊號強度")
    ax.set_xlim(0, max(counts) + 1.2)
    ax.invert_yaxis()
    for bar, count, title in zip(bars, counts, titles):
        ax.text(
            bar.get_width() + 0.08,
            bar.get_y() + bar.get_height() / 2,
            f"{count} 篇 | {title}",
            va="center",
            fontsize=10,
        )
    plt.tight_layout()
    fig.savefig(HERE / "k1428_claim_support.png", dpi=150)
    plt.close(fig)


def plot_followup_roadmap(data: dict) -> None:
    followups = sorted(data["recommended_followups"], key=lambda x: x["priority"])
    labels = [
        "共享 target baseline battle",
        "realized-measure ablation",
        "economic-value combination",
        "restrained ML extension",
    ]
    scores = [5 - item["priority"] for item in followups]
    notes = [
        "HAR-RV / Realized GARCH / HEAVY",
        "5-min RV vs MedRV vs range proxy",
        "先看風管與配置效益",
        "等 baseline 鎖定後再做",
    ]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = ["#1B9E77", "#66A61E", "#E6AB02", "#D95F02"]
    bars = ax.barh(labels, scores, color=colors)
    ax.set_xlabel("文獻支持的先後順序")
    ax.set_title("K1428 建議的 VolPred 下一步")
    ax.set_xlim(0, max(scores) + 1.2)
    ax.invert_yaxis()
    ax.set_xticks([1, 2, 3, 4], labels=["第 4 步", "第 3 步", "第 2 步", "第 1 步"])
    for bar, note in zip(bars, notes):
        ax.text(
            bar.get_width() + 0.08,
            bar.get_y() + bar.get_height() / 2,
            note,
            va="center",
            fontsize=10,
        )
    plt.tight_layout()
    fig.savefig(HERE / "k1428_followup_roadmap.png", dpi=150)
    plt.close(fig)


def main() -> None:
    data = load_results()
    plot_claim_support(data)
    plot_followup_roadmap(data)
    print("saved:", HERE / "k1428_claim_support.png")
    print("saved:", HERE / "k1428_followup_roadmap.png")


if __name__ == "__main__":
    main()
