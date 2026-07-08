"""Charts for K1660 MZ calibration audit."""
from __future__ import annotations

import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def make_charts(out, audits):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    core = [a for a in audits if a["is_core"] and a["n"] >= 200]

    # ---- Chart 1: MZ scatter for flagship SPY GJR-GARCH ----
    flag = out.get("flagship_bias_correction", {})
    pick_id = None
    if "GJR-GARCH" in flag:
        pick_id = flag["GJR-GARCH"]["exp_id"]
    scatter_src = next((a for a in audits if a["exp_id"] == pick_id), None)
    if scatter_src is None and core:
        scatter_src = max(core, key=lambda x: x["n"])
    if scatter_src is not None:
        f = np.array(scatter_src["_arrays"]["f"])
        r2 = np.array(scatter_src["_arrays"]["r2"])
        mz = scatter_src["mz_r2"]
        fig, ax = plt.subplots(figsize=(7.2, 6.4))
        ax.scatter(f * 1e4, r2 * 1e4, s=10, alpha=0.35, color="#2c6fbb", label="daily obs")
        lo = min(f.min(), r2.min()) * 1e4
        hi = max(np.percentile(f, 99.5), np.percentile(r2, 99.5)) * 1e4
        grid = np.linspace(max(lo, 0), hi, 100)
        ax.plot(grid, grid, "k--", lw=1.3, label="45° (perfect: a=0,b=1)")
        ax.plot(grid, (mz["a_hat"] * 1e4 + mz["b_hat"] * grid), color="#d1495b", lw=2.0,
                label=f"MZ fit: a={mz['a_hat']:.2e}, b={mz['b_hat']:.2f}")
        ax.set_xlim(0, hi); ax.set_ylim(0, hi)
        ax.set_xlabel("Forecast variance  (×1e-4)")
        ax.set_ylabel("Realized $r^2$  (×1e-4)")
        ax.set_title(f"Mincer-Zarnowitz: {scatter_src['family']} / {scatter_src['asset']} "
                     f"({scatter_src['oos_start']}→{scatter_src['oos_end']}, n={scatter_src['n']})\n"
                     f"Wald H0(a=0,b=1) p={mz['wald_p']:.3g} → {scatter_src['verdict']}")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.25)
        fig.tight_layout()
        p1 = os.path.join(HERE, "mz_scatter_flagship.png")
        fig.savefig(p1, dpi=130); plt.close(fig)
        print(f"wrote {p1}")

    # ---- Chart 2: family calibration summary (b_hat distribution + fc/r2 ratio) ----
    fam_summary = out.get("family_summary", {})
    if fam_summary:
        fams = list(fam_summary.keys())
        # gather per-file b_hats per family
        bmap = {fam: [a["mz_r2"]["b_hat"] for a in core if a["family"] == fam] for fam in fams}
        rmap = {fam: [a["fc_over_r2_ratio"] for a in core if a["family"] == fam
                      and np.isfinite(a["fc_over_r2_ratio"])] for fam in fams}
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.6))

        ax = axes[0]
        positions = range(len(fams))
        data = [bmap[f] for f in fams]
        bp = ax.boxplot(data, positions=list(positions), widths=0.55, patch_artist=True,
                        showmeans=True)
        for patch in bp["boxes"]:
            patch.set_facecolor("#8fb8de"); patch.set_alpha(0.7)
        ax.axhline(1.0, color="#d1495b", ls="--", lw=1.5, label="b=1 (well-calibrated slope)")
        ax.set_xticks(list(positions)); ax.set_xticklabels(fams, rotation=20, ha="right")
        ax.set_ylabel("MZ slope  $\\hat{b}$  (realized $r^2$ target)")
        ax.set_title("MZ slope by model family\n(b<1 ⇒ forecast too dispersed in high-vol)")
        ax.legend(fontsize=9); ax.grid(alpha=0.25, axis="y")

        ax = axes[1]
        med_ratios = [np.median(rmap[f]) if rmap[f] else np.nan for f in fams]
        colors = ["#e08b3c" if r > 1.10 else ("#5a9367" if 0.9 <= r <= 1.10 else "#4a6fa5")
                  for r in med_ratios]
        ax.bar(list(positions), med_ratios, color=colors, alpha=0.85)
        ax.axhline(1.0, color="k", ls="--", lw=1.3, label="mean forecast = mean realized")
        ax.set_xticks(list(positions)); ax.set_xticklabels(fams, rotation=20, ha="right")
        ax.set_ylabel("median  mean(forecast) / mean($r^2$)")
        ax.set_title("Unconditional bias by family\n(>1 ⇒ over-forecast level)")
        for i, r in enumerate(med_ratios):
            if np.isfinite(r):
                ax.text(i, r + 0.03, f"{r:.2f}", ha="center", fontsize=9)
        ax.legend(fontsize=9); ax.grid(alpha=0.25, axis="y")

        fig.suptitle("K1660 — Calibration of the VolPred GARCH forecast library (Mincer-Zarnowitz, r² target)",
                     fontsize=12)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        p2 = os.path.join(HERE, "family_calibration_summary.png")
        fig.savefig(p2, dpi=130); plt.close(fig)
        print(f"wrote {p2}")
