"""
K1372: BTC Halving Volatility Event Study
=========================================
Research question: BTC 半減期前後的波動率是否有可預測的 pattern？GARCH 能否捕捉？

Member question source: uq_mock1 (score 82/100)

Anti-lookahead note:
  - GARCH is estimated over the full sample for descriptive purposes only.
  - No trading signal is implied. Forward-looking event windows are purely descriptive.
  - N=3 halvings means near-zero statistical power. Results are exploratory only.

Seed: np.random.seed(42)
"""

import json
import warnings
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy.stats import mannwhitneyu, wilcoxon

warnings.filterwarnings("ignore")

# ── Seed ─────────────────────────────────────────────────────────────────────
np.random.seed(42)

# ── Constants ─────────────────────────────────────────────────────────────────
HALVINGS = {
    "H2_2016": "2016-07-09",
    "H3_2020": "2020-05-11",
    "H4_2024": "2024-04-19",
}
WINDOW = 90        # trading days on each side
ROLL_VOL = 20      # rolling window for realized vol
ANNUALIZE = np.sqrt(252)
OUT_DIR = "/Users/yhlai0911/Desktop/volpred-research/experiments/k1372"

# ── 1. Download data ──────────────────────────────────────────────────────────
print("Downloading BTC-USD data...")
price = yf.download(
    "BTC-USD",
    start="2013-01-01",
    end="2025-12-31",
    auto_adjust=True,
    progress=False,
)["Close"]

# Flatten MultiIndex if present
if isinstance(price, pd.DataFrame):
    price = price.squeeze()

price = price.dropna().sort_index()
print(f"Price series: {price.index[0].date()} to {price.index[-1].date()}, n={len(price)}")

# ── 2. Log returns ────────────────────────────────────────────────────────────
returns = np.log(price / price.shift(1)).dropna()
print(f"Returns: n={len(returns)}")

# ── 3. 20-day rolling realized vol (annualised) ───────────────────────────────
rvol = returns.rolling(ROLL_VOL).std() * ANNUALIZE
rvol = rvol.dropna()

# ── 4. GJR-GARCH(1,1)-t fit over full sample ─────────────────────────────────
print("Fitting GJR-GARCH(1,1)-t ...")
am = arch_model(returns * 100, vol="GARCH", p=1, o=1, q=1, dist="t")
res = am.fit(disp="off")
print(res.summary())

# Conditional vol from GARCH (annualised, in return units not %)
cond_vol = res.conditional_volatility / 100 * ANNUALIZE
cond_vol.index = returns.index  # ensure alignment

garch_params = {
    "spec": "GJR-GARCH(1,1)-t",
    "omega": float(res.params["omega"]),
    "alpha": float(res.params["alpha[1]"]),
    "gamma": float(res.params["gamma[1]"]),
    "beta": float(res.params["beta[1]"]),
    "nu": float(res.params["nu"]),
    "log_likelihood": float(res.loglikelihood),
}
print("GARCH params:", garch_params)

# ── 5. Event window analysis ──────────────────────────────────────────────────
halving_results = {}
post_minus_pre = []

fig1, axes1 = plt.subplots(3, 1, figsize=(12, 12))
fig1.suptitle("K1372: BTC Halving — Realized & GARCH Conditional Volatility\n±90 Trading Days", fontsize=14)

for ax, (hid, hdate_str) in zip(axes1, HALVINGS.items()):
    hdate = pd.Timestamp(hdate_str)
    year_label = hdate_str[:4]

    # Find index position of halving date (or nearest trading day)
    all_idx = returns.index
    pos_candidates = all_idx[all_idx >= hdate]
    if len(pos_candidates) == 0:
        print(f"  {hid}: halving date beyond data — skipping")
        continue
    h_pos = all_idx.get_loc(pos_candidates[0])

    pre_start = max(0, h_pos - WINDOW)
    post_end = min(len(all_idx) - 1, h_pos + WINDOW)

    pre_idx = all_idx[pre_start:h_pos]        # [-90, -1]
    post_idx = all_idx[h_pos + 1:post_end + 1]  # [+1, +90]

    # Use only indices present in rvol (needs 20-day warmup)
    pre_rv = rvol.reindex(pre_idx).dropna()
    post_rv = rvol.reindex(post_idx).dropna()

    pre_garch = cond_vol.reindex(pre_idx).dropna()
    post_garch = cond_vol.reindex(post_idx).dropna()

    pre_mean_rv = float(pre_rv.mean())
    post_mean_rv = float(post_rv.mean())
    pre_mean_garch = float(pre_garch.mean())
    post_mean_garch = float(post_garch.mean())

    # Mann-Whitney U test (realized vol pre vs post)
    if len(pre_rv) >= 10 and len(post_rv) >= 10:
        mw_stat, mw_p = mannwhitneyu(pre_rv.values, post_rv.values, alternative="two-sided")
    else:
        mw_stat, mw_p = np.nan, np.nan

    halving_results[hid] = {
        "date": hdate_str,
        "pre_vol_mean": round(pre_mean_rv, 4),
        "post_vol_mean": round(post_mean_rv, 4),
        "pre_garch_mean": round(pre_mean_garch, 4),
        "post_garch_mean": round(post_mean_garch, 4),
        "mw_u": round(float(mw_stat), 2) if not np.isnan(mw_stat) else None,
        "mw_p": round(float(mw_p), 4) if not np.isnan(mw_p) else None,
        "pre_n": len(pre_rv),
        "post_n": len(post_rv),
    }
    post_minus_pre.append(post_mean_rv - pre_mean_rv)

    print(
        f"  {hid} ({hdate_str}): pre_rv={pre_mean_rv:.3f}, post_rv={post_mean_rv:.3f}, "
        f"MW p={mw_p:.4f}, n_pre={len(pre_rv)}, n_post={len(post_rv)}"
    )

    # ── Plot event window ───────────────────────────────────────────────────
    # Build time axis in "days relative to halving"
    window_idx = all_idx[pre_start: post_end + 1]
    day_offsets = np.arange(-len(pre_idx), len(post_idx) + 1)
    # realized vol
    rv_window = rvol.reindex(window_idx)
    garch_window = cond_vol.reindex(window_idx)

    ax.axvline(0, color="black", lw=1.5, linestyle="--", label="Halving day")
    ax.axvspan(-WINDOW, 0, alpha=0.07, color="blue")
    ax.axvspan(0, WINDOW, alpha=0.07, color="orange")

    # Map index → day offset properly
    idx_positions = {d: i - len(pre_idx) for i, d in enumerate(window_idx)}
    rv_x = [idx_positions[d] for d in rv_window.dropna().index]
    rv_y = rv_window.dropna().values
    garch_x = [idx_positions[d] for d in garch_window.dropna().index]
    garch_y = garch_window.dropna().values

    ax.plot(rv_x, rv_y, color="steelblue", lw=1.2, alpha=0.9, label="20d Realized Vol")
    ax.plot(garch_x, garch_y, color="tomato", lw=1.2, alpha=0.9, linestyle="--", label="GARCH Cond. Vol")
    ax.set_title(f"{hid} — {hdate_str}")
    ax.set_xlabel("Trading Days Relative to Halving")
    ax.set_ylabel("Annualised Vol")
    ax.legend(fontsize=8, loc="upper right")
    ax.set_xlim(-WINDOW - 5, WINDOW + 5)

plt.tight_layout()
fig1.savefig(f"{OUT_DIR}/k1372_event_windows.png", dpi=150, bbox_inches="tight")
plt.close(fig1)
print("Saved k1372_event_windows.png")

# ── 6. Aggregate Wilcoxon signed-rank test ────────────────────────────────────
print(f"\npost_minus_pre differences: {post_minus_pre}")
if len(post_minus_pre) >= 2:
    # Wilcoxon with N=3; if all same sign, p-value = 0.25 (exact)
    try:
        wil_stat, wil_p = wilcoxon(post_minus_pre, alternative="two-sided")
    except ValueError:
        # all zeros or insufficient data
        wil_stat, wil_p = np.nan, np.nan
else:
    wil_stat, wil_p = np.nan, np.nan

print(f"Wilcoxon: stat={wil_stat}, p={wil_p}")

# ── 7. Bar chart comparison ───────────────────────────────────────────────────
fig2, ax2 = plt.subplots(figsize=(9, 5))
halving_labels = list(halving_results.keys())
pre_means = [halving_results[h]["pre_vol_mean"] for h in halving_labels]
post_means = [halving_results[h]["post_vol_mean"] for h in halving_labels]
mw_ps = [halving_results[h]["mw_p"] for h in halving_labels]

x = np.arange(len(halving_labels))
width = 0.35

bars_pre = ax2.bar(x - width / 2, pre_means, width, label="Pre (-90d)", color="steelblue", alpha=0.85)
bars_post = ax2.bar(x + width / 2, post_means, width, label="Post (+90d)", color="tomato", alpha=0.85)

# Significance markers
for i, p in enumerate(mw_ps):
    if p is not None:
        if p < 0.01:
            marker = "***"
        elif p < 0.05:
            marker = "**"
        elif p < 0.1:
            marker = "*"
        else:
            marker = "ns"
        ymax = max(pre_means[i], post_means[i]) + 0.02
        ax2.text(x[i], ymax, f"MW {marker}\n(p={p:.3f})", ha="center", fontsize=9)

ax2.set_xticks(x)
ax2.set_xticklabels(halving_labels, fontsize=10)
ax2.set_ylabel("Mean Annualised Realised Vol (±90 trading days)")
ax2.set_title("K1372: BTC Halving — Pre vs Post Realised Volatility Comparison")
ax2.legend(fontsize=10)
ax2.set_ylim(0, max(pre_means + post_means) * 1.35)

# Aggregate Wilcoxon note
wil_note = f"Aggregate Wilcoxon (N=3): stat={wil_stat:.2f}, p={wil_p:.3f}" if not (
    np.isnan(wil_stat) if isinstance(wil_stat, float) else False
) else "Aggregate Wilcoxon: insufficient data"
fig2.text(0.5, -0.01, wil_note + "\n⚠ N=3 halvings — near-zero statistical power. Results exploratory only.",
          ha="center", fontsize=9, style="italic")

plt.tight_layout()
fig2.savefig(f"{OUT_DIR}/k1372_vol_comparison.png", dpi=150, bbox_inches="tight")
plt.close(fig2)
print("Saved k1372_vol_comparison.png")

# ── 8. Verdict logic ──────────────────────────────────────────────────────────
n_post_increase = sum(1 for d in post_minus_pre if d > 0)
agg_p = wil_p if not (isinstance(wil_p, float) and np.isnan(wil_p)) else 1.0
if n_post_increase >= 2 and agg_p < 0.1:
    verdict = "EXPLORATORY_SIGNAL (low confidence)"
else:
    verdict = "EXPLORATORY_NULL (insufficient power)"

print(f"\nVerdict: {verdict}")
print(f"Post > Pre count: {n_post_increase}/3, Wilcoxon p={agg_p:.4f}")

# ── 9. Write results JSON ─────────────────────────────────────────────────────
results = {
    "experiment_id": "K1372",
    "title": "BTC Halving Volatility Event Study",
    "research_question": "BTC 半減期前後的波動率是否有可預測的 pattern？GARCH 能否捕捉？",
    "data": {
        "asset": "BTC-USD",
        "source": "yfinance",
        "start": "2013-01-01",
        "end": str(price.index[-1].date()),
        "n_obs": int(len(returns)),
    },
    "halvings": {
        hid: {
            "date": v["date"],
            "pre_vol_mean": v["pre_vol_mean"],
            "post_vol_mean": v["post_vol_mean"],
            "pre_garch_mean": v["pre_garch_mean"],
            "post_garch_mean": v["post_garch_mean"],
            "mw_u": v["mw_u"],
            "mw_p": v["mw_p"],
            "pre_n": v["pre_n"],
            "post_n": v["post_n"],
        }
        for hid, v in halving_results.items()
    },
    "aggregate": {
        "post_minus_pre_differences": [round(d, 4) for d in post_minus_pre],
        "post_minus_pre_mean": round(float(np.mean(post_minus_pre)), 4),
        "n_post_increase": n_post_increase,
        "wilcoxon_stat": round(float(wil_stat), 4) if not (isinstance(wil_stat, float) and np.isnan(wil_stat)) else None,
        "wilcoxon_p": round(float(wil_p), 4) if not (isinstance(wil_p, float) and np.isnan(wil_p)) else None,
        "n_halvings": 3,
    },
    "garch": garch_params,
    "verdict": verdict,
    "power_caveat": "N=3 halvings, very low statistical power. Results exploratory only.",
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}

json_path = f"{OUT_DIR}/k1372_results.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nSaved {json_path}")
print("\n=== K1372 COMPLETE ===")
print(f"Verdict: {verdict}")
for hid, v in halving_results.items():
    print(f"  {hid}: pre={v['pre_vol_mean']:.3f}, post={v['post_vol_mean']:.3f}, MW p={v['mw_p']}")
