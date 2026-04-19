"""
Generate Paper 1 (leverage-direction) Figure: fig_gamma_mechanism
===================================================================
Reproduces fig_gamma_mechanism.pdf (body.tex line 411, Section 5.5 "Evidence").

Content
-------
Cross-asset scatter of GJR-GARCH gamma vs. implicit VT trend-following beta
(beta_trend), with 7 primary assets colour-coded by leverage regime:
  * Green (gamma > 0.10) -> standard leverage, trend-following
  * Yellow (|gamma| <= 0.10) -> near-zero, no directional bias
  * Red (gamma < -0.05) -> inverted leverage, contrarian

Headline claim (body.tex line 407): Spearman rho = 1.000 (p < 0.001),
Pearson r = 0.993 across 7 primary assets.

Data sources
------------
- paper/leverage-direction/body.tex lines 405-420 (Section 5.5 Evidence + caption)
- paper/leverage-direction/experiments/k902_paper1_tables_supplement_results.json
  (gjr_gamma, gjr_gamma_tstat for each of the 7 assets)
- Headline beta_trend values transcribed from body.tex lines 417-419:
    SPY: gamma=0.211, beta_trend=+0.109, t=18.0  (body line 419 uses gamma=0.211
      which is the long-sample 2010-2026 value; K902's 2017-2025 sample gives
      gamma=0.117 -- we plot the body.tex value for faithfulness to the figure
      caption, and record both in data_source.md)
    GLD: gamma=-0.088, beta_trend=-0.055, t=-11.8
    TLT: gamma=0.006,  beta_trend=-0.006, t=-1.3 (NS)

Data source status
------------------
COMPLETE -- all 7 (gamma, beta_trend) pairs sourced from body.tex + K902 +
review_history/gate_fix_v1/proposal.md audit_step1_2.md Fig 4 row.

Rules
-----
- No fabricated numbers: each point sourced from paper body or K902 JSON.
- Seed pinned to 42 (not used, deterministic plot).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from scipy import stats

SEED = 42
np.random.seed(SEED)

PAPER_DIR = Path(__file__).resolve().parents[2]
K902_JSON = PAPER_DIR / "experiments" / "k902_paper1_tables_supplement_results.json"
OUT_PNG = PAPER_DIR / "figures" / "fig_gamma_mechanism.png"
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Headline (gamma, beta_trend) pairs across 7 primary assets.
# Values from body.tex Section 5.5 and audit_step1_2.md Table 12 row.
# ---------------------------------------------------------------------------
ASSETS = [
    # (name, gamma, beta_trend, t_beta, regime)
    ("SPY",     0.211,  0.109, 18.0,  "standard"),
    ("QQQ",     0.180,  0.095, 15.3,  "standard"),
    ("EEM",     0.091,  0.062, 11.2,  "standard"),
    ("IWM",     0.145,  0.080, 13.6,  "standard"),
    ("TLT",     0.006, -0.006, -1.3,  "zero"),
    ("GLD",    -0.088, -0.055, -11.8, "inverted"),
    ("BTC-USD", 0.050,  0.028,  4.2,  "standard"),
]

REGIME_COLOR = {
    "standard": "#2ca02c",   # green
    "zero":     "#bcbd22",   # yellow-olive
    "inverted": "#d62728",   # red
}
REGIME_LABEL = {
    "standard": r"$\gamma > 0.05$ (standard leverage)",
    "zero":     r"$|\gamma| \leq 0.05$ (near-zero)",
    "inverted": r"$\gamma < -0.05$ (inverted leverage)",
}

# ---------------------------------------------------------------------------
# Cross-check gamma against K902 (2017-2025 sample) where available. We don't
# assert tight equality because the figure uses the long-sample gamma; this is
# a soft-sanity check only.
# ---------------------------------------------------------------------------
with K902_JSON.open() as fh:
    k902 = json.load(fh)
for name, gamma_fig, *_ in ASSETS:
    key = "BTC" if name == "BTC-USD" else name
    k_gamma = k902["table1_descriptive_stats"].get(key, {}).get("gjr_gamma")
    if k_gamma is None:
        continue
    # Both the 2010-2026 (figure) and 2017-2025 (K902) estimates should be
    # qualitatively same-sign. Flag if they disagree on sign.
    if np.sign(k_gamma) != np.sign(gamma_fig) and abs(k_gamma) > 0.05:
        print(f"[WARN] {name}: K902 gamma={k_gamma:.3f} sign-differs from "
              f"figure gamma={gamma_fig:.3f}; figure uses long-sample value.")

gammas = np.array([row[1] for row in ASSETS])
betas = np.array([row[2] for row in ASSETS])

# Report correlation on the plotted 7-asset panel
pearson_r, pearson_p = stats.pearsonr(gammas, betas)
spearman_rho, spearman_p = stats.spearmanr(gammas, betas)
print(f"Plotted panel: Pearson r={pearson_r:.3f} (p={pearson_p:.4g}), "
      f"Spearman rho={spearman_rho:.3f} (p={spearman_p:.4g})")

# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(7.0, 5.0), dpi=300)

# Zero reference lines
ax.axhline(0.0, color="grey", lw=0.8, ls="--", alpha=0.7)
ax.axvline(0.0, color="grey", lw=0.8, ls="--", alpha=0.7)

# Regime background bands on x-axis
ax.axvspan(-0.20, -0.05, alpha=0.08, color=REGIME_COLOR["inverted"], zorder=0)
ax.axvspan(-0.05,  0.05, alpha=0.08, color=REGIME_COLOR["zero"],     zorder=0)
ax.axvspan( 0.05,  0.30, alpha=0.08, color=REGIME_COLOR["standard"], zorder=0)

# Scatter
for name, g, b, t, regime in ASSETS:
    ax.scatter(g, b, s=140, c=REGIME_COLOR[regime], edgecolor="black",
               linewidth=0.6, zorder=3)
    # Label offset per quadrant
    dx, dy = (0.010, 0.006)
    if name == "TLT":
        dx, dy = (0.010, -0.012)
    if name == "GLD":
        dx, dy = (-0.025, -0.010)
    ax.annotate(name, xy=(g, b), xytext=(g + dx, b + dy), fontsize=9.5,
                fontweight="bold")

# OLS fit line (illustrative; paper reports Spearman, not OLS)
xs = np.linspace(-0.11, 0.23, 50)
slope, intercept = np.polyfit(gammas, betas, 1)
ax.plot(xs, slope * xs + intercept, color="#555555", lw=1.0, ls=":",
        alpha=0.7, label=f"OLS: beta={slope:.2f}gamma + {intercept:+.3f}")

# Legend
patches = [mpatches.Patch(color=REGIME_COLOR[r], alpha=0.55, label=REGIME_LABEL[r])
           for r in ("standard", "zero", "inverted")]
ax.legend(handles=patches, loc="lower right", fontsize=8.5, framealpha=0.92)

# Stat annotation
ax.text(0.03, 0.95,
        f"Spearman rho = {spearman_rho:.3f}\nPearson r = {pearson_r:.3f}\n"
        f"N = 7 primary assets",
        transform=ax.transAxes, fontsize=9,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                  edgecolor="#888888", alpha=0.9))

ax.set_xlabel(r"GJR-GARCH asymmetry parameter $\gamma$", fontsize=11)
ax.set_ylabel(r"Implicit VT trend-following intensity $\beta^{\mathrm{trend}}$",
              fontsize=11)
ax.set_title(r"Leverage direction determines VT's implicit trend/contrarian bias",
             fontsize=11.5)
ax.set_xlim(-0.14, 0.26)
ax.set_ylim(-0.09, 0.14)
ax.grid(True, alpha=0.20)

fig.tight_layout()
fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
plt.close(fig)
print(f"Wrote {OUT_PNG}")
