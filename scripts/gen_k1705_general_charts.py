"""Charts for the K1705 general-audience article.

Both figures read from experiments/k1705/k1705_results.json.

  1. k1705_general_sign_audit.png -- the archived loss differential for each
     pair. Both are positive, and under the archive's own definition (first
     model minus second) positive means the first model scored WORSE. The
     chart puts the stored number and its mechanical meaning side by side,
     because the whole error was reading one without the other.
  2. k1705_general_timing_flip.png -- the redo's test statistics under the
     synchronous and one-day-delayed alignments, against the pre-set decision
     threshold. The bars cross zero between the two panels: the direction is
     an artefact of the timing assumption, and neither alignment clears the bar.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "k1705" / "k1705_results.json"
ASSETS = ROOT / "storage" / "assets"

C_A = "#B45309"
C_B = "#0F766E"
C_BAND = "#E4E4E7"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"

PAIR_LABEL = {
    "SPY-TLT": "美股 × 美國公債",
    "SPY-GLD": "美股 × 黃金",
}

THRESHOLD = 3.0


def load() -> dict:
    return json.loads(RESULTS.read_text())


def fig_sign_audit(data: dict) -> Path:
    audit = data["parent_claim_audit"]["pairs"]
    pairs = list(audit.keys())
    diffs = [audit[p]["reported_mean_loss_diff_joe_minus_dcc"] for p in pairs]
    labels = [PAIR_LABEL[p] for p in pairs]

    fig, ax = plt.subplots(figsize=(9.0, 4.4), dpi=160)
    bars = ax.barh(labels, diffs, height=0.45, color=C_A)
    ax.axvline(0, color=C_TEXT, lw=1.3)

    for b, v in zip(bars, diffs):
        ax.text(v + 0.006, b.get_y() + b.get_height() / 2, f"+{v:.3f}",
                va="center", fontsize=11, weight="bold", color=C_A)

    ax.set_xlim(0, max(diffs) * 1.42)
    ax.set_xlabel("存檔裡的誤差差距（第一個模型減第二個模型）", fontsize=10)
    ax.set_title("兩個數字都是正的，而正號的意思是「第一個模型比較差」",
                 fontsize=13.5, pad=14, weight="bold")
    ax.text(max(diffs) * 0.52, -0.62,
            "當年的說明把同樣的正號讀成「第一個模型比較好」",
            fontsize=10, color=C_TEXT, ha="center")
    ax.grid(axis="x", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1705_general_sign_audit.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_timing_flip(data: dict) -> Path:
    sync = {e["pair"]: e for e in data["synchronous_close"]}
    asyn = {e["pair"]: e for e in data["asynchronous_sensitivity"]}
    pairs = list(sync.keys())

    t_sync = [sync[p]["dependence_scores"]["canonical_dm_dcc_minus_joe"]["t_stat"]
              for p in pairs]
    t_async = [asyn[p]["dependence_scores"]["canonical_dm_dcc_minus_joe"]["t_stat"]
               for p in pairs]

    x = range(len(pairs))
    w = 0.34
    fig, ax = plt.subplots(figsize=(9.2, 5.0), dpi=160)
    ax.axhspan(-THRESHOLD, THRESHOLD, color=C_BAND, zorder=0)
    ax.bar([i - w / 2 for i in x], t_sync, width=w, color=C_A, zorder=2,
           label="兩邊同一天收盤")
    ax.bar([i + w / 2 for i in x], t_async, width=w, color=C_B, zorder=2,
           label="其中一邊延後一天")
    ax.axhline(0, color=C_TEXT, lw=1.3, zorder=3)

    for i, (a, b) in enumerate(zip(t_sync, t_async)):
        ax.text(i - w / 2, a - 0.42 if a < 0 else a + 0.2, f"{a:+.2f}",
                ha="center", fontsize=10.5, weight="bold", color=C_A,
                va="top" if a < 0 else "bottom")
        ax.text(i + w / 2, b + 0.2, f"{b:+.2f}", ha="center", fontsize=10.5,
                weight="bold", color=C_B, va="bottom")

    ax.text(len(pairs) - 0.5, 0.2, "灰帶內 = 沒過門檻", fontsize=9.5,
            color=C_TEXT, ha="right")
    ax.set_xticks(list(x))
    ax.set_xticklabels([PAIR_LABEL[p] for p in pairs], fontsize=11)
    ax.set_ylabel("檢定強度（往下偏好一邊，往上偏好另一邊）", fontsize=10)
    ax.set_ylim(-6.2, 4.6)
    ax.set_title("只是把其中一邊延後一天，方向就整個翻過去",
                 fontsize=13.5, pad=14, weight="bold")
    ax.legend(frameon=False, fontsize=9.5, loc="lower right")
    ax.grid(axis="y", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1705_general_timing_flip.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    for p in (fig_sign_audit(data), fig_timing_flip(data)):
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
