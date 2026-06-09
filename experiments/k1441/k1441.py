"""K1441: EM ex-TW realized volatility landscape via PCA and correlation regimes.

Question:
  Across EEM / INDA / EWZ / EWY / EWW, is there a dominant common realized-vol
  factor, and do high-correlation regimes coincide with materially higher EM RV?

Design:
  - Descriptive cross-asset RV study, not a forecasting horse race.
  - PCA is run on standardized 21d realized vol levels.
  - Correlation regime uses rolling 63d average pairwise correlation of RV series.
  - Inference for regime comparisons uses HAC because the rolling-correlation
    state variable is highly overlapping.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import yfinance as yf
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

OUT_DIR = Path(__file__).parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

START = "2010-01-01"
END = "2026-06-10"
RV_WINDOW = 21
CORR_WINDOW = 63
ANNUALIZER = float(np.sqrt(252.0))
TICKERS = ["EEM", "INDA", "EWZ", "EWY", "EWW"]


@dataclass
class AssetSummary:
    mean_rv: float
    median_rv: float
    std_rv: float
    acf1: float
    n_obs: int


def fetch_prices() -> pd.DataFrame:
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    out = {}
    for ticker in TICKERS:
        try:
            ser = raw[ticker]["Close"].rename(ticker)
        except Exception:
            ser = raw["Close"][ticker].rename(ticker)
        out[ticker] = ser.dropna()
    return pd.DataFrame(out).sort_index().dropna()


def compute_rv(prices: pd.DataFrame) -> pd.DataFrame:
    log_ret = np.log(prices).diff()
    return (log_ret.rolling(RV_WINDOW).std() * ANNUALIZER).dropna()


def asset_summaries(rv: pd.DataFrame) -> Dict[str, AssetSummary]:
    out: Dict[str, AssetSummary] = {}
    for col in rv.columns:
        s = rv[col]
        out[col] = AssetSummary(
            mean_rv=float(s.mean()),
            median_rv=float(s.median()),
            std_rv=float(s.std()),
            acf1=float(s.autocorr(1)),
            n_obs=int(len(s)),
        )
    return out


def rolling_avg_pairwise_corr(rv: pd.DataFrame, window: int = CORR_WINDOW) -> pd.Series:
    rolling = rv.rolling(window).corr()
    vals = []
    for dt in rv.index[window - 1:]:
        mat = rolling.loc[dt].values
        vals.append((dt, float(mat[np.triu_indices_from(mat, 1)].mean())))
    return pd.Series(dict(vals), name="avg_pairwise_corr").sort_index()


def regime_regression(series: pd.Series, regime: pd.Series) -> Dict[str, Dict[str, float]]:
    frame = pd.concat([series.rename("y"), regime.rename("regime")], axis=1).dropna()
    model = smf.ols('y ~ C(regime, Treatment(reference="mid"))', data=frame).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": CORR_WINDOW},
    )
    out: Dict[str, Dict[str, float]] = {}
    for key in model.params.index:
        out[key] = {
            "coef": float(model.params[key]),
            "se_hac": float(model.bse[key]),
            "t_hac": float(model.tvalues[key]),
            "p_hac": float(model.pvalues[key]),
        }
    out["meta"] = {
        "n_obs": int(model.nobs),
        "r2": float(model.rsquared),
        "hac_maxlags": CORR_WINDOW,
    }
    return out


def make_corr_heatmap(corr: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 5.2))
    im = ax.imshow(corr.values, cmap="YlGnBu", vmin=0.45, vmax=0.85, aspect="auto")
    ax.set_xticks(range(len(corr.columns)))
    ax.set_yticks(range(len(corr.index)))
    ax.set_xticklabels(corr.columns)
    ax.set_yticklabels(corr.index)
    for i in range(len(corr.index)):
        for j in range(len(corr.columns)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", fontsize=9, color="black")
    fig.colorbar(im, ax=ax, shrink=0.9)
    ax.set_title("K1441: Correlation of 21d RV across EM ETFs")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def make_pc1_loadings(loadings: pd.Series, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.8, 4.6))
    colors = ["#2d6a4f", "#40916c", "#52b788", "#74c69d", "#95d5b2"]
    ax.bar(loadings.index, loadings.values, color=colors)
    ax.set_ylabel("PC1 loading")
    ax.set_title("K1441: PC1 loadings on standardized EM RV")
    ax.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def make_regime_timeseries(avg_corr: pd.Series, basket_rv: pd.Series, out_path: Path) -> None:
    fig, ax1 = plt.subplots(figsize=(10.2, 5.1))
    ax1.plot(avg_corr.index, avg_corr.values, color="#1d3557", lw=1.4, label="Avg pairwise corr (63d)")
    ax1.set_ylabel("Avg pairwise corr", color="#1d3557")
    ax1.tick_params(axis="y", labelcolor="#1d3557")
    ax2 = ax1.twinx()
    ax2.plot(basket_rv.index, basket_rv.values, color="#c1121f", alpha=0.55, lw=1.0, label="Equal-weight basket RV")
    ax2.set_ylabel("Equal-weight basket 21d RV", color="#c1121f")
    ax2.tick_params(axis="y", labelcolor="#c1121f")
    ax1.set_title("K1441: EM RV correlation state and basket RV")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def main() -> Dict:
    prices = fetch_prices()
    rv = compute_rv(prices)
    corr = rv.corr()
    summaries = asset_summaries(rv)

    scaler = StandardScaler()
    z_rv = scaler.fit_transform(rv)
    pca = PCA().fit(z_rv)
    scores = pca.transform(z_rv)
    pc1 = pd.Series(scores[:, 0], index=rv.index, name="pc1_score")
    pc1_loadings = pd.Series(pca.components_[0], index=rv.columns, name="pc1_loading")

    avg_corr = rolling_avg_pairwise_corr(rv)
    basket_rv = rv.mean(axis=1).rename("basket_rv").reindex(avg_corr.index)
    q25 = float(avg_corr.quantile(0.25))
    q75 = float(avg_corr.quantile(0.75))
    regime = pd.Series(
        np.where(avg_corr <= q25, "low", np.where(avg_corr >= q75, "high", "mid")),
        index=avg_corr.index,
        name="corr_regime",
    )

    basket_reg = regime_regression(basket_rv, regime)
    asset_regs = {
        ticker: regime_regression(rv[ticker].reindex(avg_corr.index), regime) for ticker in TICKERS
    }

    make_corr_heatmap(corr, FIG_DIR / "rv_corr_heatmap.png")
    make_pc1_loadings(pc1_loadings, FIG_DIR / "pc1_loadings.png")
    make_regime_timeseries(avg_corr, basket_rv, FIG_DIR / "avg_corr_vs_basket_rv.png")

    high_pvals = [
        asset_regs[t]['C(regime, Treatment(reference="mid"))[T.high]']["p_hac"] for t in TICKERS
    ]
    low_pvals = [
        asset_regs[t]['C(regime, Treatment(reference="mid"))[T.low]']["p_hac"] for t in TICKERS
    ]
    bonf_alpha_assets = 0.05 / len(TICKERS)
    n_low_sig = int(sum(p < bonf_alpha_assets for p in low_pvals))
    n_high_sig = int(sum(p < bonf_alpha_assets for p in high_pvals))

    if pca.explained_variance_ratio_[0] >= 0.70 and pc1_loadings.min() > 0:
        if n_low_sig + n_high_sig >= 2:
            verdict = "PASS"
            verdict_reason = (
                "PC1 explains >70% of standardized RV variance with uniformly positive loadings, "
                "and at least two asset-level correlation-regime contrasts survive Bonferroni."
            )
        else:
            verdict = "CONDITIONAL_PASS"
            verdict_reason = (
                "A strong common EM vol factor is clearly present, but correlation-regime inference is mixed "
                "after HAC and multiple-testing control."
            )
    else:
        verdict = "NULL"
        verdict_reason = "No dominant common EM realized-vol factor emerges under PCA."

    result = {
        "experiment_id": "K1441",
        "title": "EM ex-TW realized volatility landscape via PCA and correlation regimes",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "data_source": "yfinance (EEM, INDA, EWZ, EWY, EWW)",
        "period": {
            "start": str(prices.index.min().date()),
            "end": str(prices.index.max().date()),
            "joint_price_obs": int(len(prices)),
            "rv_obs": int(len(rv)),
            "joint_sample_note": "Joint sample begins at INDA inception",
        },
        "rv_definition": "21d rolling std of daily log returns, annualized by sqrt(252)",
        "descriptive_stats": {k: asdict(v) for k, v in summaries.items()},
        "rv_corr_matrix": corr.round(6).to_dict(),
        "pca": {
            "explained_variance_ratio": [float(x) for x in pca.explained_variance_ratio_],
            "pc1_loadings": {k: float(v) for k, v in pc1_loadings.items()},
            "pc1_basket_rv_corr": float(pc1.corr(rv.mean(axis=1))),
        },
        "correlation_regime": {
            "window_days": CORR_WINDOW,
            "avg_pairwise_corr_q25": q25,
            "avg_pairwise_corr_q75": q75,
            "regime_counts": regime.value_counts().to_dict(),
            "avg_pairwise_corr_mean": float(avg_corr.mean()),
            "avg_pairwise_corr_std": float(avg_corr.std()),
            "corr_avgcorr_basket_rv": float(avg_corr.corr(basket_rv)),
            "basket_rv_regression_hac": basket_reg,
            "asset_rv_regression_hac": asset_regs,
            "bonferroni_alpha_asset_tests": bonf_alpha_assets,
            "n_low_regime_asset_contrasts_sig": n_low_sig,
            "n_high_regime_asset_contrasts_sig": n_high_sig,
        },
        "figures": [
            "figures/rv_corr_heatmap.png",
            "figures/pc1_loadings.png",
            "figures/avg_corr_vs_basket_rv.png",
        ],
        "verdict": verdict,
        "verdict_reason": verdict_reason,
    }

    out_path = OUT_DIR / "k1441_results.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "reason": verdict_reason}, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    main()
