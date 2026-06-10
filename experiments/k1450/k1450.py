"""K1450: VNQ realized volatility and stock/bond affinity under rate regimes.

Question:
  Is VNQ more equity-like or bond-like under rising-rate vs falling-rate regimes?

Design:
  - Rate regime uses lagged 63d change in ^TNX (10Y yield proxy).
  - Outcomes are forward 21d VNQ RV and forward 21d correlations VNQ-SPY / VNQ-TLT.
  - Primary inference uses HAC(Newey-West, maxlags=21) because outcomes overlap.
"""
from __future__ import annotations

import json
import time
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

START = "2005-01-01"
END = "2026-06-10"
SIGNAL_WINDOW = 63
OUTCOME_WINDOW = 21
HAC_LAGS = 21
ANNUALIZER = float(np.sqrt(252.0))

OUT_DIR = Path(__file__).parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class OutcomeSummary:
    mean: float
    median: float
    std: float
    n_days: int


def fetch_prices() -> pd.DataFrame:
    tickers = ["VNQ", "SPY", "TLT", "^TNX"]
    for attempt in range(3):
        try:
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
            if not df.empty:
                return df
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] download attempt {attempt + 1}/3 failed: {exc}")
        time.sleep(2 + attempt)
    raise RuntimeError("yfinance download failed after 3 attempts")


def compute_forward_rv(price: pd.Series) -> pd.Series:
    log_ret = np.log(price).diff()
    rv = log_ret.shift(-1).rolling(OUTCOME_WINDOW).std() * ANNUALIZER
    return rv.shift(-(OUTCOME_WINDOW - 1))


def compute_forward_corr(left: pd.Series, right: pd.Series) -> pd.Series:
    lr = np.log(left).diff()
    rr = np.log(right).diff()
    corr = lr.shift(-1).rolling(OUTCOME_WINDOW).corr(rr.shift(-1))
    return corr.shift(-(OUTCOME_WINDOW - 1))


def build_regime(tnx: pd.Series) -> pd.Series:
    signal = tnx.diff(SIGNAL_WINDOW).shift(1)
    regime = pd.Series(
        np.where(signal > 0, "rate_up", "rate_down"),
        index=signal.index,
        name="regime",
    )
    regime[signal.isna()] = np.nan
    return regime


def summarize(frame: pd.DataFrame, outcome_col: str) -> Dict[str, OutcomeSummary]:
    out: Dict[str, OutcomeSummary] = {}
    for label in ["rate_down", "rate_up"]:
        sub = frame.loc[frame["regime"] == label, outcome_col]
        out[label] = OutcomeSummary(
            mean=float(sub.mean()),
            median=float(sub.median()),
            std=float(sub.std()),
            n_days=int(len(sub)),
        )
    return out


def hac_regression(frame: pd.DataFrame, outcome_col: str) -> Dict[str, Dict[str, float]]:
    model = smf.ols(
        f'{outcome_col} ~ C(regime, Treatment(reference="rate_down"))',
        data=frame,
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


def multiple_test_correction(pvals: list[tuple[str, float]]) -> Dict[str, Dict[str, float]]:
    m = len(pvals)
    ranked = sorted(pvals, key=lambda x: x[1])
    bh_raw = [min(p * m / rank, 1.0) for rank, (_, p) in enumerate(ranked, start=1)]
    bh_adj = [0.0] * m
    running = 1.0
    for idx in range(m - 1, -1, -1):
        running = min(running, bh_raw[idx])
        bh_adj[idx] = running
    out = {}
    for idx, (label, p) in enumerate(ranked):
        out[label] = {
            "raw_p": float(p),
            "bonferroni_p": float(min(p * m, 1.0)),
            "bh_p": float(bh_adj[idx]),
            "rank": int(idx + 1),
        }
    return out


def make_figures(frame: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].plot(frame.index, frame["fwd_rv_vnq"], color="#c44e52", lw=0.8, label="VNQ fwd RV21")
    rate_up = frame["regime"] == "rate_up"
    axes[0].fill_between(frame.index, 0, frame["fwd_rv_vnq"].max() * 1.05, where=rate_up, color="orange", alpha=0.15, label="Rate up")
    axes[0].set_title("VNQ forward RV with rate-up shading")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend()

    means = {
        "VNQ RV": (
            frame.loc[~rate_up, "fwd_rv_vnq"].mean(),
            frame.loc[rate_up, "fwd_rv_vnq"].mean(),
        ),
        "VNQ-SPY corr": (
            frame.loc[~rate_up, "fwd_corr_vnq_spy"].mean(),
            frame.loc[rate_up, "fwd_corr_vnq_spy"].mean(),
        ),
        "VNQ-TLT corr": (
            frame.loc[~rate_up, "fwd_corr_vnq_tlt"].mean(),
            frame.loc[rate_up, "fwd_corr_vnq_tlt"].mean(),
        ),
    }
    labels = list(means.keys())
    down_vals = [means[k][0] for k in labels]
    up_vals = [means[k][1] for k in labels]
    x = np.arange(len(labels))
    w = 0.35
    axes[1].bar(x - w / 2, down_vals, w, label="Rate down", color="#4c72b0")
    axes[1].bar(x + w / 2, up_vals, w, label="Rate up", color="#dd8452")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels)
    axes[1].set_title("Forward outcomes by rate regime")
    axes[1].grid(True, axis="y", alpha=0.25)
    axes[1].legend()

    fig.tight_layout()
    fig.savefig(FIG_DIR / "vnq_rate_regime_summary.png", dpi=130)
    plt.close(fig)


def main() -> Dict:
    px = fetch_prices()
    regime = build_regime(px["^TNX"])

    frame = pd.concat(
        [
            regime,
            compute_forward_rv(px["VNQ"]).rename("fwd_rv_vnq"),
            compute_forward_rv(px["SPY"]).rename("fwd_rv_spy"),
            compute_forward_rv(px["TLT"]).rename("fwd_rv_tlt"),
            compute_forward_corr(px["VNQ"], px["SPY"]).rename("fwd_corr_vnq_spy"),
            compute_forward_corr(px["VNQ"], px["TLT"]).rename("fwd_corr_vnq_tlt"),
        ],
        axis=1,
    ).dropna()

    summaries = {}
    models = {}
    pvals: list[tuple[str, float]] = []
    for outcome_col in ["fwd_rv_vnq", "fwd_rv_spy", "fwd_rv_tlt", "fwd_corr_vnq_spy", "fwd_corr_vnq_tlt"]:
        summaries[outcome_col] = {k: asdict(v) for k, v in summarize(frame, outcome_col).items()}
        models[outcome_col] = hac_regression(frame, outcome_col)
        pvals.append(
            (
                outcome_col,
                models[outcome_col]['C(regime, Treatment(reference="rate_down"))[T.rate_up]']["p_hac"],
            )
        )

    correction = multiple_test_correction(pvals)
    make_figures(frame)

    sig_vnq_rv = correction["fwd_rv_vnq"]["bonferroni_p"] < 0.05
    sig_vnq_spy = correction["fwd_corr_vnq_spy"]["bonferroni_p"] < 0.05
    sig_vnq_tlt = correction["fwd_corr_vnq_tlt"]["bonferroni_p"] < 0.05

    if sig_vnq_spy or sig_vnq_tlt or sig_vnq_rv:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = (
            "At least one VNQ rate-regime contrast survives Bonferroni; interpret as descriptive regime dependence, not a tradable timing rule."
        )
    else:
        verdict = "NULL"
        verdict_reason = (
            "No VNQ rate-regime contrast survives Bonferroni; REIT short-horizon vol/correlation is not robustly separated by simple lagged rate-up vs rate-down states."
        )

    result = {
        "experiment_id": "K1450",
        "title": "VNQ realized volatility and stock/bond affinity under rate regimes",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "sample": {
            "start": str(frame.index.min().date()),
            "end": str(frame.index.max().date()),
            "n_obs": int(len(frame)),
        },
        "data_source": "yfinance (VNQ, SPY, TLT, ^TNX)",
        "rate_regime_definition": {
            "signal": "^TNX.diff(63).shift(1)",
            "rate_up": "lagged 63d 10Y yield change > 0",
            "rate_down": "lagged 63d 10Y yield change <= 0",
        },
        "lookahead_protection": {
            "signal": "rate regime uses ^TNX at t-1 and earlier only",
            "outcomes": "forward 21d RV/correlation use returns t+1..t+21",
        },
        "methods": {
            "primary_inference": "OLS with Newey-West HAC maxlags=21",
            "multiple_testing": "Bonferroni + BH over 5 primary contrasts",
        },
        "regime_counts": frame["regime"].value_counts().sort_index().to_dict(),
        "summaries": summaries,
        "models": models,
        "multiple_test_correction": correction,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "figures": ["figures/vnq_rate_regime_summary.png"],
    }

    (OUT_DIR / "k1450_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "reason": verdict_reason}, indent=2))
    return result


if __name__ == "__main__":
    main()
