"""Asset generator for the K1695 general-audience article.

Reads ONLY pinned K1695 artifacts (never re-fetches, never writes into experiments/).
Produces:
  storage/drafts/k1695_fig1_exposure_matched.png
  storage/drafts/k1695_fig2_cost_and_mechanism.png
  storage/drafts/k1695_article_evidence.json   (derived numbers, for lazypack binding)

The exposure-matched drawdown gap is computed with the repo's canonical
volpred.stats.drawdown.compare_max_drawdown, because K1695's VT sleeve runs
32-39% below buy-and-hold realized volatility in every market, which is over the
20% mismatch threshold at which raw MDD differences stop being reportable alone.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from volpred.stats.drawdown import compare_max_drawdown

REPO = Path(__file__).resolve().parents[2]
EXP = REPO / "experiments" / "k1695"
OUT = REPO / "storage" / "drafts"

RESULTS = json.loads((EXP / "k1695_results.json").read_text())
COMMON = pd.read_csv(EXP / "common_sample_rows.csv")
FIG2 = pd.read_csv(EXP / "figure2_data.csv")

with gzip.open(EXP / "data" / "paired_common_returns.csv.gz", "rt") as fh:
    PAIRED = pd.read_csv(fh, parse_dates=["date"]).set_index("date")

# Integrity: the paired panel must be the exact bytes K1695 pinned.
pinned = RESULTS["artifacts"]["sha256"]["data/paired_common_returns.csv.gz"]
actual = hashlib.sha256((EXP / "data" / "paired_common_returns.csv.gz").read_bytes()).hexdigest()
assert pinned == actual, f"paired panel sha mismatch: {pinned} vs {actual}"

NAMES = {
    "EFA": "成熟市場(EAFE)", "EWJ": "日本", "EWG": "德國", "EWU": "英國",
    "EWA": "澳洲", "EWC": "加拿大", "VGK": "歐洲", "EEM": "新興市場",
    "FXI": "中國大型股", "EWZ": "巴西", "INDA": "印度", "EWT": "台灣", "MCHI": "中國廣義",
}
TICKERS = list(NAMES)

# ---------------------------------------------------------------- exposure match
rows = []
for tkr in TICKERS:
    cmp = compare_max_drawdown(PAIRED[f"{tkr}_vt"].values, PAIRED[f"{tkr}_bh"].values)
    region = COMMON.loc[COMMON.ticker == tkr, "region"].iloc[0]
    rows.append(
        {
            "ticker": tkr,
            "name_zh": NAMES[tkr],
            "region": region,
            "raw_mdd_gap_pp": cmp.raw_mdd_improvement * 100,
            "exposure_matched_gap_pp": cmp.exposure_matched_gap * 100,
            "vol_ratio": cmp.vol_ratio,
            "vol_cut_pct": (1 - cmp.vol_ratio) * 100,
            "exposure_mismatch": cmp.exposure_mismatch,
            "matched_lambda": cmp.matched_lambda,
        }
    )
EM = pd.DataFrame(rows)

# Cross-check: the raw gap we recompute must reproduce K1695's published delta_mdd_pp.
merged = EM.merge(COMMON[["ticker", "delta_mdd_pp"]], on="ticker")
assert np.allclose(merged.raw_mdd_gap_pp, merged.delta_mdd_pp, atol=1e-8), "raw gap does not reproduce K1695"

evidence = {
    "note": "Derived from pinned K1695 artifacts only. Common sample 2012-02-07..2026-03-31, N=3557.",
    "source_experiment": "K1695",
    "paired_returns_sha256": pinned,
    "common_sample": {
        "n_obs": int(RESULTS["samples"]["common_period"]["n_obs"]),
        "start": "2012-02-07",
        "end": "2026-03-31",
        "n_markets": 13,
    },
    "exposure_matched": {
        "n_markets_vol_mismatch_flagged": int(EM.exposure_mismatch.sum()),
        "min_vol_cut_pct": float(EM.vol_cut_pct.min()),
        "max_vol_cut_pct": float(EM.vol_cut_pct.max()),
        "mean_vol_cut_pct": float(EM.vol_cut_pct.mean()),
        "avg_raw_mdd_gap_pp": float(EM.raw_mdd_gap_pp.mean()),
        "avg_exposure_matched_gap_pp": float(EM.exposure_matched_gap_pp.mean()),
        "shrinkage_pct": float(
            (1 - EM.exposure_matched_gap_pp.mean() / EM.raw_mdd_gap_pp.mean()) * 100
        ),
        "n_markets_matched_gap_positive": int((EM.exposure_matched_gap_pp > 0).sum()),
        "n_markets_matched_gap_negative": int((EM.exposure_matched_gap_pp < 0).sum()),
        "per_market": EM.set_index("ticker")[
            ["raw_mdd_gap_pp", "exposure_matched_gap_pp", "vol_cut_pct"]
        ].to_dict("index"),
    },
    "published_k1695": {
        "avg_delta_mdd_pp_common": RESULTS["samples"]["common_period"]["summary"]["average_delta_mdd_pp"],
        "avg_delta_sharpe_common": RESULTS["samples"]["common_period"]["summary"]["average_delta_sharpe"],
        "n_sharpe_improved_common": RESULTS["samples"]["common_period"]["summary"]["n_sharpe_improved"],
        "avg_annual_return_cost_pp_common": RESULTS["samples"]["common_period"]["summary"]["average_annual_return_cost_pp"],
        "avg_delta_mdd_pp_inception": RESULTS["samples"]["inception_aware"]["summary"]["average_delta_mdd_pp"],
        "n_sharpe_improved_inception": RESULTS["samples"]["inception_aware"]["summary"]["n_sharpe_improved"],
        "vix_r_inception": RESULTS["samples"]["inception_aware"]["summary"]["vix_sensitivity_vs_delta_mdd"]["pearson_r"],
        "vix_p_inception": RESULTS["samples"]["inception_aware"]["summary"]["vix_sensitivity_vs_delta_mdd"]["pearson_p"],
        "vix_r_common": RESULTS["samples"]["common_period"]["summary"]["vix_sensitivity_vs_delta_mdd"]["pearson_r"],
        "vix_p_common": RESULTS["samples"]["common_period"]["summary"]["vix_sensitivity_vs_delta_mdd"]["pearson_p"],
        "bootstrap_ci_lower_pp": RESULTS["inference"]["primary"]["average_delta_mdd_pp"]["lower"],
        "bootstrap_ci_upper_pp": RESULTS["inference"]["primary"]["average_delta_mdd_pp"]["upper"],
    },
}
(OUT / "k1695_article_evidence.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
)

# ---------------------------------------------------------------- figure 1
plt.rcParams["font.sans-serif"] = ["Heiti TC", "PingFang TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

D = EM.sort_values("raw_mdd_gap_pp", ascending=False).reset_index(drop=True)
x = np.arange(len(D))
w = 0.38

fig, ax = plt.subplots(figsize=(11, 6.2))
ax.bar(x - w / 2, D.raw_mdd_gap_pp, w, label="帳面回撤改善（原始）", color="#9db8d6", edgecolor="#4a6fa5")
ax.bar(
    x + w / 2, D.exposure_matched_gap_pp, w,
    label="同風險口徑下的回撤改善", color="#d1604a", edgecolor="#8c3423",
)
ax.axhline(0, color="#333", lw=1)
ax.set_xticks(x)
ax.set_xticklabels(D.name_zh, rotation=40, ha="right", fontsize=10)
ax.set_ylabel("回撤改善（百分點）", fontsize=11)
ax.set_title(
    "把「少冒險」扣掉之後，回撤改善剩多少\n"
    f"13 個市場，2012-02-07 至 2026-03-31，N={evidence['common_sample']['n_obs']:,}",
    fontsize=13, pad=14,
)
ax.legend(frameon=False, fontsize=10)
ax.spines[["top", "right"]].set_visible(False)
ax.text(
    0.995, -0.30,
    "資料：K1695 pinned yfinance snapshot（2026-03-31 截止）｜同風險口徑 = 把買進持有等比例縮到與策略相同的實現波動後再比回撤",
    transform=ax.transAxes, ha="right", fontsize=7.5, color="#666",
)
fig.tight_layout()
fig.savefig(OUT / "k1695_fig1_exposure_matched.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- figure 2
fig, axes = plt.subplots(1, 2, figsize=(13, 5.6))

S = COMMON.sort_values("delta_sharpe").reset_index(drop=True)
S["name_zh"] = S.ticker.map(NAMES)
ax = axes[0]
ax.barh(S.name_zh, S.delta_sharpe, color="#c0574a", edgecolor="#7d3226")
ax.axvline(0, color="#333", lw=1)
ax.set_xlabel("夏普比率變化（策略 − 買進持有）", fontsize=10)
ax.set_title("13 個市場，沒有一個的風險報酬比變好", fontsize=12, pad=10)
ax.spines[["top", "right"]].set_visible(False)
ax.tick_params(labelsize=9)

ax = axes[1]
inc = FIG2.copy()
cmn = COMMON.copy()
ax.scatter(inc.vix_sensitivity, inc.delta_mdd_pp, s=70, color="#4a6fa5",
           label=f"各自上市起算：r={evidence['published_k1695']['vix_r_inception']:.2f}"
                 f"（p={evidence['published_k1695']['vix_p_inception']:.4f}）")
ax.scatter(cmn.vix_sensitivity, cmn.delta_mdd_pp, s=70, marker="^", color="#d1604a",
           label=f"13 市場共同期間：r={evidence['published_k1695']['vix_r_common']:+.2f}"
                 f"（p={evidence['published_k1695']['vix_p_common']:.2f}）")
for df, col in ((inc, "#4a6fa5"), (cmn, "#d1604a")):
    m, b = np.polyfit(df.vix_sensitivity, df.delta_mdd_pp, 1)
    xs = np.linspace(df.vix_sensitivity.min(), df.vix_sensitivity.max(), 20)
    ax.plot(xs, m * xs + b, color=col, lw=1.4, ls="--", alpha=0.8)
ax.set_xlabel("市場對 VIX 的敏感度", fontsize=10)
ax.set_ylabel("回撤改善（百分點）", fontsize=10)
ax.set_title("換一個樣本期間，那條「機制」就翻面了", fontsize=12, pad=10)
ax.legend(frameon=False, fontsize=9, loc="upper left")
ax.spines[["top", "right"]].set_visible(False)

fig.suptitle("波動率目標策略付出的代價，與那個站不住的解釋", fontsize=14, y=1.02)
fig.text(0.5, -0.04, "資料：K1695（experiments/k1695/common_sample_rows.csv、figure2_data.csv）",
         ha="center", fontsize=8, color="#666")
fig.tight_layout()
fig.savefig(OUT / "k1695_fig2_cost_and_mechanism.png", dpi=150, bbox_inches="tight")
plt.close(fig)

print(json.dumps(evidence["exposure_matched"], ensure_ascii=False, indent=2, default=str)[:1200])
print("\nper-market matched gaps:")
print(EM[["ticker", "raw_mdd_gap_pp", "exposure_matched_gap_pp", "vol_cut_pct"]].to_string(index=False))
