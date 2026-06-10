"""K1451: HYG-LQD credit-spread proxy and SPY forward realized volatility.

Question:
  Does the lagged HYG/LQD credit-spread proxy predict SPY forward 21d realized
  volatility beyond VIX, or is it mostly redundant with equity fear proxies?

Design:
  - Predictor: trailing 22d change in log(HYG/LQD), shifted by 1 day.
  - Outcome: SPY forward 21d RV using returns t+1..t+21.
  - Formal inference uses HAC(Newey-West, maxlags=21).
  - Cross-correlation CI uses moving-block bootstrap with seed=42.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import yfinance as yf

SEED = 42
START = "2007-01-01"
END = "2026-06-10"
SIGNAL_WINDOW = 22
OUTCOME_WINDOW = 21
HAC_LAGS = 21
N_BOOT = 1000
BLOCK_SIZE = 21
ANNUALIZER = float(np.sqrt(252.0))

OUT_DIR = Path(__file__).parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def fetch_prices() -> pd.DataFrame:
    tickers = ["HYG", "LQD", "SPY", "^VIX"]
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
    return rv.shift(-(OUTCOME_WINDOW - 1)).rename(f"{price.name}_fwd_rv21")


def moving_block_bootstrap_corr(xs: np.ndarray, ys: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    n = len(xs)
    n_blocks = int(np.ceil(n / BLOCK_SIZE))
    starts = np.arange(0, n - BLOCK_SIZE + 1)
    vals = np.empty(N_BOOT)
    for i in range(N_BOOT):
        chosen = rng.choice(starts, size=n_blocks, replace=True)
        idx = np.concatenate([np.arange(s, s + BLOCK_SIZE) for s in chosen])[:n]
        vals[i] = np.corrcoef(xs[idx], ys[idx])[0, 1]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def lead_lag_corr(sig: pd.Series, target: pd.Series, max_lag: int = 5) -> dict:
    rng = np.random.default_rng(SEED)
    aligned = pd.concat([sig.rename("x"), target.rename("y")], axis=1).dropna()
    x = aligned["x"].to_numpy()
    y = aligned["y"].to_numpy()
    n = len(aligned)
    out = {"lags": list(range(-max_lag, max_lag + 1)), "corr": [], "ci_lo": [], "ci_hi": []}
    for lag in out["lags"]:
        if lag < 0:
            xs = x[: n + lag]
            ys = y[-lag:n]
        elif lag > 0:
            xs = x[lag:]
            ys = y[: n - lag]
        else:
            xs = x
            ys = y
        corr = float(np.corrcoef(xs, ys)[0, 1])
        lo, hi = moving_block_bootstrap_corr(xs, ys, rng)
        out["corr"].append(corr)
        out["ci_lo"].append(lo)
        out["ci_hi"].append(hi)
    return out


def build_frame(px: pd.DataFrame) -> pd.DataFrame:
    ratio = (px["HYG"] / px["LQD"]).rename("hyg_lqd_ratio")
    signal = np.log(ratio).diff(SIGNAL_WINDOW).shift(1).rename("hyg_lqd_chg22_lag1")
    signal_z = ((signal - signal.rolling(252).mean()) / signal.rolling(252).std()).rename("hyg_lqd_chg22_z")
    wide_credit_stress = (signal < signal.quantile(0.2)).astype(int).rename("wide_credit_stress")
    vix_lag1 = (px["^VIX"] / 100.0).shift(1).rename("vix_lag1")
    spy_fwd_rv = compute_forward_rv(px["SPY"])
    frame = pd.concat([signal, signal_z, wide_credit_stress, vix_lag1, spy_fwd_rv], axis=1).dropna()
    frame["wide_credit_stress"] = frame["wide_credit_stress"].astype(int)
    return frame


def hac_model(formula: str, data: pd.DataFrame) -> dict:
    model = smf.ols(formula, data=data).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    out = {}
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


def multiple_test_correction(pvals: list[tuple[str, float]]) -> dict:
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


def make_figures(frame: pd.DataFrame, ll: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].plot(frame.index, frame["hyg_lqd_chg22_lag1"], color="#4c72b0", lw=0.8, label="HYG/LQD 22d log-change lag1")
    axes[0].plot(frame.index, frame["SPY_fwd_rv21"], color="#c44e52", lw=0.8, label="SPY fwd RV21")
    axes[0].set_title("Credit spread proxy vs SPY forward RV")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend()

    lags = ll["lags"]
    corr = np.array(ll["corr"])
    lo = np.array(ll["ci_lo"])
    hi = np.array(ll["ci_hi"])
    axes[1].errorbar(lags, corr, yerr=[corr - lo, hi - corr], fmt="o-", capsize=4, color="#55a868")
    axes[1].axhline(0, color="black", lw=0.6)
    axes[1].axvline(0, color="gray", lw=0.6, ls="--")
    axes[1].set_xlabel("Lag (negative = HYG/LQD leads SPY fwd RV)")
    axes[1].set_ylabel("Correlation")
    axes[1].set_title("Lead-lag cross-correlation with block-bootstrap CI")
    axes[1].grid(True, alpha=0.25)

    fig.tight_layout()
    fig.savefig(FIG_DIR / "lead_lag_credit_spread.png", dpi=130)
    plt.close(fig)


def main() -> dict:
    px = fetch_prices()
    frame = build_frame(px)
    ll = lead_lag_corr(frame["hyg_lqd_chg22_lag1"], frame["SPY_fwd_rv21"])

    model_uni = hac_model("SPY_fwd_rv21 ~ hyg_lqd_chg22_lag1", frame)
    model_ctl = hac_model("SPY_fwd_rv21 ~ hyg_lqd_chg22_lag1 + vix_lag1", frame)
    model_z = hac_model("SPY_fwd_rv21 ~ hyg_lqd_chg22_z + vix_lag1", frame)
    model_bucket = hac_model("SPY_fwd_rv21 ~ wide_credit_stress + vix_lag1", frame)

    pvals = [
        ("uni_hyg_lqd_chg22_lag1", model_uni["hyg_lqd_chg22_lag1"]["p_hac"]),
        ("ctl_hyg_lqd_chg22_lag1", model_ctl["hyg_lqd_chg22_lag1"]["p_hac"]),
        ("ctl_hyg_lqd_chg22_z", model_z["hyg_lqd_chg22_z"]["p_hac"]),
        ("bucket_wide_credit_stress", model_bucket["wide_credit_stress"]["p_hac"]),
    ]
    correction = multiple_test_correction(pvals)
    make_figures(frame, ll)

    if any(v["bonferroni_p"] < 0.05 for v in correction.values()):
        verdict = "CONDITIONAL_PASS"
        verdict_reason = (
            "At least one lagged HYG/LQD credit-stress predictor survives Bonferroni after formal HAC inference; treat as descriptive incremental evidence, not a standalone timing rule."
        )
    else:
        verdict = "NULL"
        verdict_reason = (
            "No lagged HYG/LQD credit-stress predictor survives Bonferroni; the credit-spread proxy does not robustly predict SPY forward RV beyond overlapping-noise and VIX."
        )

    result = {
        "experiment_id": "K1451",
        "title": "HYG-LQD credit-spread proxy and SPY forward realized volatility",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "sample": {
            "start": str(frame.index.min().date()),
            "end": str(frame.index.max().date()),
            "n_obs": int(len(frame)),
        },
        "data_source": "yfinance (HYG, LQD, SPY, ^VIX)",
        "lookahead_protection": {
            "predictor": "22d log(HYG/LQD) change shifted by 1 day",
            "outcome": "SPY forward RV uses returns t+1..t+21",
            "control": "vix_lag1",
        },
        "methods": {
            "inference": "OLS with Newey-West HAC maxlags=21",
            "bootstrap": f"moving-block bootstrap n={N_BOOT}, block={BLOCK_SIZE}, seed={SEED}",
        },
        "descriptive": {
            "signal_mean": float(frame["hyg_lqd_chg22_lag1"].mean()),
            "signal_std": float(frame["hyg_lqd_chg22_lag1"].std()),
            "spy_fwd_rv_mean": float(frame["SPY_fwd_rv21"].mean()),
            "corr_signal_target": float(frame["hyg_lqd_chg22_lag1"].corr(frame["SPY_fwd_rv21"])),
            "wide_credit_stress_share": float(frame["wide_credit_stress"].mean()),
        },
        "lead_lag_cross_corr": ll,
        "models": {
            "univariate": model_uni,
            "vix_control_level": model_ctl,
            "vix_control_zscore": model_z,
            "vix_control_bucket": model_bucket,
        },
        "multiple_test_correction": correction,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "figures": ["figures/lead_lag_credit_spread.png"],
    }

    (OUT_DIR / "k1451_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "reason": verdict_reason}, indent=2))
    return result


if __name__ == "__main__":
    main()
