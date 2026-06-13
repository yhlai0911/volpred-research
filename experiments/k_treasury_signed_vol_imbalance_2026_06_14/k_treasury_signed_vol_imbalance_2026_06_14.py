"""
K_treasury_signed_vol_imbalance_2026_06_14
=========================================

Treasury daily signed-volume imbalance — pilot test.

H1 (self-predict): For each Treasury proxy X in {TLT, IEF, ZN=F}:
    log(RV_{t+1}^X) = a + b * signed_vol_imb_t^X + c * log(RV_t^X) + e

H2 (spillover to equity): For each Treasury proxy X:
    log(RV_{t+1}^SPY) = a + b * signed_vol_imb_t^X + c * log(RV_t^SPY) + e

Significance:
    HAC (Newey-West, L=5) |t| > 2.0 AND
    Block-bootstrap (block_len=20, B=5000, seed=42) p < 0.05
    Bonferroni across 6 tests at alpha=0.05/6 = 0.00833

Lookahead: signed_vol_imb_t aligned to predict RV_{t+1}; explicit shift(1) on
features. RV_t (control) is also strictly past (rolled with same shift).

Data: yfinance daily, 2015-01-01 .. 2026-06-13 (manual cap to avoid lookahead).
Seed: numpy seed 42, bootstrap seed 42.
"""

from __future__ import annotations

import json
import os
import time
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
import statsmodels.api as sm
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
START = "2015-01-01"
END = "2026-06-14"  # yfinance end is exclusive — gives data up to 2026-06-13
CAP_DATE = pd.Timestamp("2026-06-13")  # hard cap to avoid lookahead on today

TREASURY_PROXIES = ["TLT", "IEF", "ZN=F"]
EQUITY = "SPY"

ALL_TICKERS = TREASURY_PROXIES + [EQUITY]

N_BOOT = 5000
BLOCK_LEN = 20
HAC_LAGS = 5


# ---------------------------------------------------------------------------
# Data load
# ---------------------------------------------------------------------------
def fetch_one(ticker: str) -> pd.DataFrame:
    """Download daily OHLCV from yfinance. Fail loud, no silent fallback."""
    df = yf.download(
        ticker,
        start=START,
        end=END,
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned empty frame for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df[df.index <= CAP_DATE]
    df = df.dropna(subset=["Close", "Volume"])
    df = df[df["Volume"] > 0]
    if len(df) < 500:
        raise RuntimeError(
            f"{ticker} only {len(df)} rows after clean — below floor 500"
        )
    return df


def load_all() -> Dict[str, pd.DataFrame]:
    data = {}
    for t in ALL_TICKERS:
        print(f"[data] fetching {t} ...")
        data[t] = fetch_one(t)
        print(f"[data] {t} rows={len(data[t])} span={data[t].index.min().date()}->{data[t].index.max().date()}")
    return data


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker daily features.

    daily_return_t   = log(close_t / close_{t-1})
    signed_volume_t  = sign(daily_return_t) * volume_t
    signed_vol_imb_t = signed_volume_t / volume_t  in [-1, +1]
                       (this is just sign(return) per definition;
                        we keep the explicit form to match the spec
                        and to remain neutral if 0-return ties appear)
    daily_RV_t       = (daily_return_t)^2
    """
    out = pd.DataFrame(index=df.index)
    close = df["Close"].astype(float)
    vol = df["Volume"].astype(float)

    ret = np.log(close / close.shift(1))
    out["ret"] = ret
    # sign() returns 0 for 0-return; treat 0-return as carry-forward of last nonzero
    sgn = np.sign(ret)
    sgn = sgn.replace(0, np.nan).ffill().fillna(0.0)
    signed_volume = sgn * vol
    # imbalance in [-1,1]: signed_volume / total_volume == sign of return.
    # The normalised form is preserved per spec; both produce identical series
    # when computed from a single ticker's own volume.
    out["signed_vol_imb"] = signed_volume / vol
    out["rv"] = ret.pow(2)
    return out.dropna()


# ---------------------------------------------------------------------------
# Regression + block bootstrap
# ---------------------------------------------------------------------------
@dataclass
class RegResult:
    n: int
    beta: float
    hac_se: float
    hac_t: float
    hac_p: float
    boot_p: float
    boot_ci_lo: float
    boot_ci_hi: float
    intercept: float
    coef_log_rv: float
    r2: float
    bonferroni_alpha: float
    bonferroni_pass: bool


def _build_xy(
    feat_x: pd.DataFrame, feat_y_rv: pd.Series
) -> Tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """Align signed_vol_imb_t (from feat_x) and log(RV_t) (control, from y series)
    to predict log(RV_{t+1}) (target). All features strictly past."""
    # Predictors at time t
    sig_t = feat_x["signed_vol_imb"]
    log_rv_t = np.log(feat_y_rv.replace(0, np.nan)).rename("log_rv_t")
    target_t1 = np.log(feat_y_rv.replace(0, np.nan)).shift(-1).rename("log_rv_tp1")
    # Inner join on dates that have both Treasury features and Equity (or self) RV
    panel = pd.concat([sig_t.rename("sig"), log_rv_t, target_t1], axis=1).dropna()
    if panel.empty:
        raise RuntimeError("empty regression panel")
    y = panel["log_rv_tp1"].values
    X = np.column_stack([
        np.ones(len(panel)),
        panel["sig"].values,
        panel["log_rv_t"].values,
    ])
    return X, y, panel.index


def hac_ols(X: np.ndarray, y: np.ndarray, lags: int = HAC_LAGS) -> sm.regression.linear_model.RegressionResults:
    model = sm.OLS(y, X)
    res = model.fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return res


def block_bootstrap_p(
    X: np.ndarray,
    y: np.ndarray,
    coef_idx: int,
    observed_beta: float,
    block_len: int = BLOCK_LEN,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> Tuple[float, float, float]:
    """Block bootstrap for H0: beta=0. Returns (p_two_sided, ci_lo, ci_hi).

    We resample (X,y) jointly in blocks, refit OLS, collect betas.
    p = 2 * min(P(b<=0), P(b>=0)) for two-sided test.
    """
    rng = np.random.default_rng(seed)
    n = len(y)
    n_blocks = int(np.ceil(n / block_len))
    betas = np.empty(n_boot, dtype=float)

    for i in range(n_boot):
        starts = rng.integers(0, n - block_len + 1, size=n_blocks)
        idx_parts = [np.arange(s, s + block_len) for s in starts]
        idx = np.concatenate(idx_parts)[:n]
        Xb = X[idx]
        yb = y[idx]
        try:
            beta_b = np.linalg.lstsq(Xb, yb, rcond=None)[0][coef_idx]
        except np.linalg.LinAlgError:
            beta_b = np.nan
        betas[i] = beta_b

    betas = betas[~np.isnan(betas)]
    if len(betas) == 0:
        return 1.0, np.nan, np.nan

    # Centered bootstrap distribution for hypothesis test under H0: beta=0
    centered = betas - betas.mean()
    p_left = np.mean(centered <= -abs(observed_beta))
    p_right = np.mean(centered >= abs(observed_beta))
    p_two = p_left + p_right
    p_two = min(max(p_two, 1.0 / n_boot), 1.0)
    ci_lo, ci_hi = np.quantile(betas, [0.025, 0.975])
    return float(p_two), float(ci_lo), float(ci_hi)


def run_regression(
    feat_x: pd.DataFrame,
    feat_y_rv: pd.Series,
    label: str,
    bonferroni_m: int,
) -> Tuple[RegResult, pd.DataFrame]:
    X, y, idx = _build_xy(feat_x, feat_y_rv)
    res = hac_ols(X, y)
    beta = float(res.params[1])
    se = float(res.bse[1])
    t_stat = float(res.tvalues[1])
    p_hac = float(res.pvalues[1])
    intercept = float(res.params[0])
    coef_rv = float(res.params[2])

    boot_p, ci_lo, ci_hi = block_bootstrap_p(
        X, y, coef_idx=1, observed_beta=beta
    )

    alpha = 0.05 / bonferroni_m
    bonf_pass = (abs(t_stat) > 2.0) and (boot_p < alpha)

    panel_df = pd.DataFrame(
        {
            "sig": X[:, 1],
            "log_rv_t": X[:, 2],
            "log_rv_tp1": y,
        },
        index=idx,
    )

    return (
        RegResult(
            n=len(y),
            beta=beta,
            hac_se=se,
            hac_t=t_stat,
            hac_p=p_hac,
            boot_p=boot_p,
            boot_ci_lo=ci_lo,
            boot_ci_hi=ci_hi,
            intercept=intercept,
            coef_log_rv=coef_rv,
            r2=float(res.rsquared),
            bonferroni_alpha=alpha,
            bonferroni_pass=bool(bonf_pass),
        ),
        panel_df,
    )


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------
def _scatter_panel(ax, panel: pd.DataFrame, beta: float, intercept_partial: float, title: str):
    # Residualize log_rv_tp1 on log_rv_t to show partial relationship with sig
    # using OLS predictions for the line
    x = panel["sig"].values
    y = panel["log_rv_tp1"].values
    ax.scatter(x, y, s=4, alpha=0.25, color="#446")
    xs = np.linspace(x.min(), x.max(), 50)
    # marginal regression line for visual only (ignores log_rv control)
    a, b = np.polyfit(x, y, 1)
    ax.plot(xs, a * xs + b, color="#c33", lw=1.5, label=f"slope={a:.3f}")
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("signed_vol_imb_t", fontsize=9)
    ax.set_ylabel("log(RV_{t+1})", fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)


def plot_h1(panels: Dict[str, pd.DataFrame], results: Dict[str, RegResult], path: Path):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for ax, t in zip(axes, TREASURY_PROXIES):
        r = results[t]
        _scatter_panel(
            ax,
            panels[t],
            r.beta,
            r.intercept,
            f"H1 {t}: β={r.beta:.4f} (t={r.hac_t:.2f}, p_boot={r.boot_p:.4f}, n={r.n})",
        )
    fig.suptitle("H1 — Self-predict: signed_vol_imb_t → log(RV_{t+1}) [marginal slope shown]", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_h2(panels: Dict[str, pd.DataFrame], results: Dict[str, RegResult], path: Path):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for ax, t in zip(axes, TREASURY_PROXIES):
        r = results[t]
        _scatter_panel(
            ax,
            panels[t],
            r.beta,
            r.intercept,
            f"H2 {t}→SPY: β={r.beta:.4f} (t={r.hac_t:.2f}, p_boot={r.boot_p:.4f}, n={r.n})",
        )
    fig.suptitle("H2 — Spillover: Treasury signed_vol_imb_t → log(SPY RV_{t+1}) [marginal slope shown]", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
def decide_verdict(results: Dict[str, RegResult]) -> Tuple[str, str]:
    bonf_pass = [k for k, r in results.items() if r.bonferroni_pass]
    marginal = [
        k for k, r in results.items()
        if not r.bonferroni_pass and abs(r.hac_t) > 2.0 and r.boot_p < 0.05
    ]
    if len(bonf_pass) >= 1:
        return (
            "PASS",
            f"{len(bonf_pass)} test(s) survive Bonferroni 0.00833: {bonf_pass}",
        )
    if len(marginal) >= 1:
        return (
            "CONDITIONAL_PASS",
            f"{len(marginal)} marginal test(s) at uncorrected α=0.05 but fail Bonferroni: {marginal}",
        )
    return (
        "NULL",
        "No test passes HAC|t|>2 ∧ bootstrap p<0.05; daily signed-volume "
        "imbalance does not predict next-day RV at this aggregation. "
        "Mechanism may require intraday OFI (cf. K1124, K1127) rather than "
        "daily aggregation, or signed-volume imbalance = sign(daily_return) "
        "lacks magnitude information at the daily horizon.",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    t0 = time.time()
    data = load_all()

    features = {t: build_features(df) for t, df in data.items()}
    for t, f in features.items():
        print(f"[feat] {t} rows={len(f)} "
              f"sig mean={f['signed_vol_imb'].mean():.4f} "
              f"sig std={f['signed_vol_imb'].std():.4f} "
              f"rv mean={f['rv'].mean():.6e}")

    bonferroni_m = 6  # 3 H1 + 3 H2

    h1_results: Dict[str, RegResult] = {}
    h1_panels: Dict[str, pd.DataFrame] = {}
    h2_results: Dict[str, RegResult] = {}
    h2_panels: Dict[str, pd.DataFrame] = {}

    # H1: self-predict
    for t in TREASURY_PROXIES:
        print(f"[H1] {t} self-predict ...")
        res, panel = run_regression(
            feat_x=features[t],
            feat_y_rv=features[t]["rv"],
            label=f"H1_{t}",
            bonferroni_m=bonferroni_m,
        )
        h1_results[t] = res
        h1_panels[t] = panel
        print(f"     β={res.beta:.5f} HAC t={res.hac_t:.3f} boot_p={res.boot_p:.4f} "
              f"n={res.n} bonf_pass={res.bonferroni_pass}")

    # H2: Treasury → SPY
    spy_rv = features[EQUITY]["rv"]
    for t in TREASURY_PROXIES:
        print(f"[H2] {t} → SPY ...")
        res, panel = run_regression(
            feat_x=features[t],
            feat_y_rv=spy_rv,
            label=f"H2_{t}_SPY",
            bonferroni_m=bonferroni_m,
        )
        h2_results[t] = res
        h2_panels[t] = panel
        print(f"     β={res.beta:.5f} HAC t={res.hac_t:.3f} boot_p={res.boot_p:.4f} "
              f"n={res.n} bonf_pass={res.bonferroni_pass}")

    # Plots
    plot_h1(h1_panels, h1_results, OUT_DIR / "fig_h1_self_predict.png")
    plot_h2(h2_panels, h2_results, OUT_DIR / "fig_h2_spillover.png")

    # Verdict — union across H1 and H2
    all_results = {f"H1_{k}": v for k, v in h1_results.items()}
    all_results.update({f"H2_{k}_to_SPY": v for k, v in h2_results.items()})
    verdict, justification = decide_verdict(all_results)
    print(f"\n[VERDICT] {verdict}\n{justification}")

    runtime = time.time() - t0

    results_dict = {
        "experiment_id": "k_treasury_signed_vol_imbalance_2026_06_14",
        "run_timestamp_utc": pd.Timestamp.utcnow().isoformat(),
        "verdict": verdict,
        "verdict_justification": justification,
        "config": {
            "treasury_proxies": TREASURY_PROXIES,
            "equity": EQUITY,
            "data_start": START,
            "data_end_exclusive": END,
            "cap_date": str(CAP_DATE.date()),
            "n_bootstrap": N_BOOT,
            "block_len": BLOCK_LEN,
            "hac_lags": HAC_LAGS,
            "seed": SEED,
            "bonferroni_m_tests": bonferroni_m,
            "bonferroni_alpha": 0.05 / bonferroni_m,
        },
        "data_summary": {
            t: {
                "rows": int(len(features[t])),
                "start": str(features[t].index.min().date()),
                "end": str(features[t].index.max().date()),
                "mean_signed_vol_imb": float(features[t]["signed_vol_imb"].mean()),
                "std_signed_vol_imb": float(features[t]["signed_vol_imb"].std()),
                "mean_rv": float(features[t]["rv"].mean()),
            }
            for t in ALL_TICKERS
        },
        "H1_self_predict": {k: asdict(v) for k, v in h1_results.items()},
        "H2_spillover_to_SPY": {k: asdict(v) for k, v in h2_results.items()},
        "runtime_seconds": runtime,
        "differentiation_from_prior": {
            "K1124": "TAIFEX TX intraday 5-min OFI (Lee-Ready tick rule). "
                     "This work: US Treasury DAILY signed-volume imbalance.",
            "K1127": "TAIFEX TX × ES intraday 1h OFI cross-market lead-lag. "
                     "This work: US Treasury → US equity DAILY spillover via daily volume sign.",
        },
    }

    with open(OUT_DIR / "results.json", "w") as f:
        json.dump(results_dict, f, indent=2, default=str)

    print(f"\n[done] runtime={runtime:.1f}s  outputs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
