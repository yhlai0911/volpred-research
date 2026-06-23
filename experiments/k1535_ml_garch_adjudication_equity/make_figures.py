"""K1535 figures — QLIKE ranking bar + Phase-B DM-vs-fair-baseline bar.

Reads the consolidated results JSON and renders, per target:
  fig_qlike_<target>.png  — QLIKE by model (NN vs classical vs fair baseline)
  fig_dm_<target>.png     — DM-HLN of each DL model vs GJR-t / GARCH-X / HAR-RV-X
                            with the Harvey |t|>3 threshold drawn in.
No data fabrication — every bar is read straight from the results JSON.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)

DL = ("LSTM", "CNN-LSTM", "PatchTST-lite", "Transformer")
FAIR = ("GJR-t", "GARCH-X", "HAR-RV-X")


def _color(model):
    if model in DL:
        return "#2c7fb8"      # DL = blue
    if model in ("GJR-t", "GARCH-X", "HAR-RV-X"):
        return "#d95f0e"      # fair baseline = orange
    return "#969696"          # weak classical = grey


def fig_qlike(res, target):
    ranking = res["ranking_by_qlike"]
    names = [r["model"] for r in ranking]
    vals = [r["qlike"] for r in ranking]
    colors = [_color(m) for m in names]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(range(len(names)), vals, color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlabel("QLIKE (lower is better)")
    ax.set_title(f"K1535 — QLIKE ranking, GSPC {target} h={res['horizon']} "
                 f"(n={res['n_valid_common']})\nblue=DL  orange=fair baseline  grey=weak classical")
    for i, v in enumerate(vals):
        ax.text(v, i, f" {v:.3f}", va="center", fontsize=8)
    fig.tight_layout()
    out = FIG / f"fig_qlike_{target}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def fig_dm(res, target):
    dm = res["phaseB_adjudication_dm"]
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(DL))
    width = 0.25
    for bi, base in enumerate(FAIR):
        vals = []
        for dl in DL:
            v = dm.get(f"{dl}_vs_{base}")
            vals.append(v["dm"] if v and v["dm"] is not None else np.nan)
        ax.bar(x + (bi - 1) * width, vals, width, label=f"vs {base}")
    ax.axhline(0, color="k", lw=0.8)
    ax.axhline(-3, color="red", ls="--", lw=1, label="Harvey |t|=3")
    ax.axhline(3, color="red", ls="--", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(DL)
    ax.set_ylabel("DM-HLN t-stat  (negative = DL better)")
    ax.set_title(f"K1535 — Phase B: DL vs fair baselines, GSPC {target} h={res['horizon']}\n"
                 "below −3 = DL Harvey-significantly beats baseline")
    ax.legend(fontsize=8)
    fig.tight_layout()
    out = FIG / f"fig_dm_{target}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main():
    data = json.loads((HERE / "k1535_ml_garch_adjudication_equity_results.json").read_text())
    made = []
    for key, res in data["results"].items():
        tgt = res["target"]
        made.append(fig_qlike(res, tgt))
        made.append(fig_dm(res, tgt))
    for p in made:
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
