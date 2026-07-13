from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from plot_style import apply_cjk_style  # noqa: E402

apply_cjk_style()

import matplotlib.pyplot as plt  # noqa: E402


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "k1430_results.json"


def load_results() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def plot_same_day_alignment(results: dict) -> None:
    data = results["same_day_alignment_test_window"]
    labels = ["BPV", "PCA_1D", "AE_1D", "GarmanKlass", "Parkinson"]
    corrs = [data[k]["corr"] for k in labels]
    colors = ["#2E8B57", "#4C78A8", "#F58518", "#9C755F", "#BAB0AC"]

    fig, ax = plt.subplots(figsize=(8, 4.8))
    bars = ax.bar(labels, corrs, color=colors)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("和當日 RV 的相關係數")
    ax.set_title("Same-Day Fit on Test Window")
    for bar, val in zip(bars, corrs):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 0.02, f"{val:.3f}", ha="center")
    plt.tight_layout()
    fig.savefig(HERE / "k1430_same_day_corr.png", dpi=150)
    plt.close(fig)


def main() -> None:
    results = load_results()
    plot_same_day_alignment(results)
    print("saved:", HERE / "k1430_same_day_corr.png")


if __name__ == "__main__":
    main()
