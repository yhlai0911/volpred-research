"""K1440: Yield-curve slope regimes and forward SPY realized volatility.

Question:
  Using only yfinance-observable Treasury yield proxies, do inverted or steep
  curve regimes imply materially different forward SPY realized volatility?

Design notes:
  - Extension of K871. K871 tested predictive regressions with FRED term spreads.
    K1440 instead tests conditional forward-RV distributions using yfinance-only
    proxies (^TNX-^FVX and ^TNX-^IRX).
  - Signal at t uses slope observed at t-1 via shift(1).
  - Outcome is forward 21d RV on returns t+1..t+21, so there is no same-day leak.
  - Primary inference uses HAC(Newey-West, maxlags=21) because forward 21d RV is
    highly autocorrelated due to overlapping windows. Welch tests are descriptive.
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
from scipy import stats

OUT_DIR = Path(__file__).parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

START = "2010-01-01"
END = "2026-06-10"
RV_WINDOW = 21
HAC_LAGS = 21
ANNUALIZER = float(np.sqrt(252.0))


@dataclass
class RegimeSummary:
    mean_rv: float
    median_rv: float
    std_rv: float
    n_days: int


def fetch_prices() -> pd.DataFrame:
    tickers = ["^TNX", "^FVX", "^IRX", "SPY"]
    raw = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    out = {}
    for ticker in tickers:
        try:
            ser = raw[ticker]["Close"].rename(ticker)
        except Exception:
            ser = raw["Close"][ticker].rename(ticker)
        out[ticker] = ser.dropna()
    df = pd.DataFrame(out).sort_index().dropna()
    return df


def compute_forward_rv(spy: pd.Series, window: int = RV_WINDOW) -> pd.Series:
    log_ret = np.log(spy).diff()
    rv = log_ret.shift(-1).rolling(window).std() * ANNUALIZER
    return rv.shift(-(window - 1)).rename("fwd_rv21")


def build_regime(slope_lag1: pd.Series) -> tuple[pd.Series, float]:
    positive = slope_lag1[slope_lag1 >= 0]
    steep_threshold = float(positive.quantile(0.75))
    regime = pd.Series(
        np.where(
            slope_lag1 < 0,
            "inverted",
            np.where(slope_lag1 > steep_threshold, "steep", "flat"),
        ),
        index=slope_lag1.index,
        name="regime",
    )
    return regime, steep_threshold


def summarize_regimes(rv: pd.Series, regime: pd.Series) -> Dict[str, RegimeSummary]:
    aligned = pd.concat([rv, regime], axis=1).dropna()
    out: Dict[str, RegimeSummary] = {}
    for label in ["inverted", "flat", "steep"]:
        sub = aligned.loc[aligned["regime"] == label, rv.name]
        out[label] = RegimeSummary(
            mean_rv=float(sub.mean()),
            median_rv=float(sub.median()),
            std_rv=float(sub.std()),
            n_days=int(len(sub)),
        )
    return out


def welch_pairwise(rv: pd.Series, regime: pd.Series, left: str, right: str) -> Dict[str, float]:
    aligned = pd.concat([rv, regime], axis=1).dropna()
    a = aligned.loc[aligned["regime"] == left, rv.name].values
    b = aligned.loc[aligned["regime"] == right, rv.name].values
    t_stat, p_val = stats.ttest_ind(a, b, equal_var=False)
    return {
        "left": left,
        "right": right,
        "n_left": int(len(a)),
        "n_right": int(len(b)),
        "diff_mean_rv": float(np.mean(a) - np.mean(b)),
        "welch_t": float(t_stat),
        "welch_p": float(p_val),
    }


def hac_regression(rv: pd.Series, regime: pd.Series) -> Dict[str, Dict[str, float]]:
    aligned = pd.concat([rv, regime], axis=1).dropna().copy()
    model = smf.ols(
        'fwd_rv21 ~ C(regime, Treatment(reference="flat"))',
        data=aligned,
    ).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
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
        "hac_maxlags": HAC_LAGS,
    }
    return out


def make_boxplot(frame: pd.DataFrame, out_path: Path, title: str) -> None:
    order = ["inverted", "flat", "steep"]
    colors = ["#c44e52", "#7f7f7f", "#4c72b0"]
    data = [frame.loc[frame["regime"] == label, "fwd_rv21"].values for label in order]
    fig, ax = plt.subplots(figsize=(7.8, 4.8))
    bp = ax.boxplot(data, tick_labels=order, patch_artist=True, showfliers=False)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.65)
    ax.set_ylabel("Forward 21d annualized RV")
    ax.set_title(title)
    ax.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def analyze_one(name: str, slope: pd.Series, rv: pd.Series) -> Dict:
    slope_lag1 = slope.shift(1).rename("slope_lag1")
    regime, steep_threshold = build_regime(slope_lag1)
    frame = pd.concat([slope_lag1, regime, rv], axis=1).dropna()
    summaries = summarize_regimes(frame["fwd_rv21"], frame["regime"])
    welch = {
        "inverted_vs_flat": welch_pairwise(frame["fwd_rv21"], frame["regime"], "inverted", "flat"),
        "steep_vs_flat": welch_pairwise(frame["fwd_rv21"], frame["regime"], "steep", "flat"),
    }
    hac = hac_regression(frame["fwd_rv21"], frame["regime"])
    make_boxplot(
        frame,
        FIG_DIR / f"{name}_forward_rv_boxplot.png",
        f"K1440: SPY forward 21d RV by {name} curve regime",
    )
    return {
        "slope_name": name,
        "steep_threshold_q75_positive": steep_threshold,
        "slope_stats": {
            "mean": float(frame["slope_lag1"].mean()),
            "std": float(frame["slope_lag1"].std()),
            "min": float(frame["slope_lag1"].min()),
            "max": float(frame["slope_lag1"].max()),
        },
        "rv_acf": {
            "lag_1": float(frame["fwd_rv21"].autocorr(1)),
            "lag_5": float(frame["fwd_rv21"].autocorr(5)),
            "lag_21": float(frame["fwd_rv21"].autocorr(21)),
        },
        "regime_counts": {k: v.n_days for k, v in summaries.items()},
        "regime_summary": {k: asdict(v) for k, v in summaries.items()},
        "welch_pairwise": welch,
        "hac_regression": hac,
        "figures": [str((FIG_DIR / f"{name}_forward_rv_boxplot.png").relative_to(OUT_DIR))],
    }


def main() -> Dict:
    px = fetch_prices()
    rv = compute_forward_rv(px["SPY"])

    slope_10y5y = (px["^TNX"] - px["^FVX"]).rename("slope_10y5y")
    slope_10y3m = (px["^TNX"] - px["^IRX"]).rename("slope_10y3m")

    analyses = {
        "tnx_minus_fvx": analyze_one("tnx_minus_fvx", slope_10y5y, rv),
        "tnx_minus_irx": analyze_one("tnx_minus_irx", slope_10y3m, rv),
    }

    bonf_alpha = 0.05 / 4.0
    hac_pvals = [
        analyses["tnx_minus_fvx"]["hac_regression"]['C(regime, Treatment(reference="flat"))[T.inverted]']["p_hac"],
        analyses["tnx_minus_fvx"]["hac_regression"]['C(regime, Treatment(reference="flat"))[T.steep]']["p_hac"],
        analyses["tnx_minus_irx"]["hac_regression"]['C(regime, Treatment(reference="flat"))[T.inverted]']["p_hac"],
        analyses["tnx_minus_irx"]["hac_regression"]['C(regime, Treatment(reference="flat"))[T.steep]']["p_hac"],
    ]
    n_sig = int(sum(p < bonf_alpha for p in hac_pvals))

    if n_sig == 0:
        verdict = "NULL"
        verdict_reason = (
            "0/4 HAC regime contrasts survive Bonferroni alpha=0.0125. "
            "Naive overlap-sensitive Welch can suggest significance, but HAC removes it."
        )
    else:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = (
            f"{n_sig}/4 HAC regime contrasts survive Bonferroni alpha=0.0125. "
            "Interpret as descriptive regime evidence, not a trading rule."
        )

    result = {
        "experiment_id": "K1440",
        "title": "Yield-curve slope regimes and forward SPY realized volatility",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "period": {
            "start": str(px.index.min().date()),
            "end": str(px.index.max().date()),
            "n_obs_joint_prices": int(len(px)),
        },
        "data_source": "yfinance (^TNX, ^FVX, ^IRX, SPY)",
        "outcome": "Forward 21d SPY realized volatility, annualized",
        "lookahead_protection": {
            "signal": "slope.shift(1)",
            "outcome": "forward RV uses returns t+1..t+21",
        },
        "regime_definition": {
            "inverted": "lagged slope < 0",
            "flat": "0 <= lagged slope <= q75 of positive lagged slope (full-sample descriptive)",
            "steep": "lagged slope > q75 of positive lagged slope (full-sample descriptive)",
        },
        "multiple_testing": {
            "n_hac_contrasts": 4,
            "bonferroni_alpha": bonf_alpha,
        },
        "analyses": analyses,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "mission_note": "Extends K871 from predictive regression NULL to regime-conditioned distribution tests using yfinance-only proxies.",
    }

    out_path = OUT_DIR / "k1440_results.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "reason": verdict_reason}, indent=2, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
