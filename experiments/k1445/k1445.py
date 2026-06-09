"""K1445 — URA / KRBN Alternative-Asset Volatility Clustering & Cross-Asset Correlation.

Descriptive PoC:
- Fetch URA (uranium ETF), KRBN (carbon credit ETF), SPY (equity), TLT (long bonds)
- Compute descriptive stats, vol clustering tests, GARCH(1,1), rolling/static correlations
- Output 4 figures + structured results JSON

研究誠實:
- No predictive setup → no lookahead concern; rolling stats use min_periods correctly
- Seed=42 for any stochastic ops
- All numbers from actual computation
- Data integrity: report n_obs + date range + NaN drops per asset
"""
from __future__ import annotations

import json
import os
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
END_DATE = "2026-06-10"  # yfinance is exclusive on end → fetch up to 2026-06-09
START_DEFAULT = "2010-01-01"
TICKERS = ["URA", "KRBN", "SPY", "TLT"]


def fetch_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Download adjusted close prices via yfinance."""
    df = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    # When auto_adjust=True, "Close" is the adjusted close
    out = pd.DataFrame()
    for t in tickers:
        if (t, "Close") in df.columns:
            out[t] = df[(t, "Close")]
        elif t in df.columns:
            out[t] = df[t]["Close"]
    out.index = pd.to_datetime(out.index)
    return out


def compute_log_returns(prices: pd.Series) -> pd.Series:
    """Log returns, drop first NaN."""
    return np.log(prices / prices.shift(1)).dropna()


def descriptive_stats(r: pd.Series) -> dict:
    """Mean, std, skew, kurt, ann_vol, max_dd of log-return series."""
    cumret = (1.0 + r).cumprod()  # not exact but proxies path; use exp for precision
    cumret = np.exp(r.cumsum())
    running_max = cumret.cummax()
    drawdown = cumret / running_max - 1.0
    return {
        "n_obs": int(r.shape[0]),
        "start": r.index.min().strftime("%Y-%m-%d"),
        "end": r.index.max().strftime("%Y-%m-%d"),
        "mean_daily": float(r.mean()),
        "std_daily": float(r.std(ddof=1)),
        "skew": float(r.skew()),
        "excess_kurtosis": float(r.kurt()),  # pandas kurt is excess kurtosis (Fisher)
        "ann_return_pct": float(r.mean() * 252 * 100),
        "ann_vol_pct": float(r.std(ddof=1) * np.sqrt(252) * 100),
        "max_drawdown_pct": float(drawdown.min() * 100),
    }


def ljungbox_squared(r: pd.Series, lags: int = 10) -> dict:
    """Ljung-Box on squared returns for vol clustering."""
    res = acorr_ljungbox(r ** 2, lags=[lags], return_df=True)
    return {
        "lags": lags,
        "stat": float(res["lb_stat"].iloc[0]),
        "pvalue": float(res["lb_pvalue"].iloc[0]),
        "reject_no_autocorr_at_5pct": bool(res["lb_pvalue"].iloc[0] < 0.05),
    }


def archlm_test(r: pd.Series, nlags: int = 10) -> dict:
    """Engle's ARCH-LM test."""
    stat, pval, fstat, fpval = het_arch(r, nlags=nlags)
    return {
        "nlags": nlags,
        "lm_stat": float(stat),
        "lm_pvalue": float(pval),
        "f_stat": float(fstat),
        "f_pvalue": float(fpval),
        "reject_no_arch_at_5pct": bool(pval < 0.05),
    }


def fit_garch11(r: pd.Series) -> dict:
    """GARCH(1,1) with constant mean, normal innovations. arch package."""
    # Scale returns to pct to help numerical stability (arch package recommendation)
    r_pct = r * 100.0
    am = arch_model(r_pct, mean="Constant", vol="GARCH", p=1, q=1, dist="normal")
    res = am.fit(disp="off", show_warning=False)
    params = res.params
    omega = float(params.get("omega", np.nan))
    alpha = float(params.get("alpha[1]", np.nan))
    beta = float(params.get("beta[1]", np.nan))
    persistence = alpha + beta
    cond_vol = res.conditional_volatility / 100.0  # back to log-return scale
    cond_vol.index = r.index
    return {
        "spec": "GARCH(1,1) constant mean normal",
        "omega": omega,
        "alpha": alpha,
        "beta": beta,
        "persistence": float(persistence),
        "loglikelihood": float(res.loglikelihood),
        "aic": float(res.aic),
        "bic": float(res.bic),
        "convergence_flag": int(res.convergence_flag) if hasattr(res, "convergence_flag") else None,
        "_cond_vol": cond_vol,  # for plotting; will be stripped from json
    }


def rolling_corr_summary(r1: pd.Series, r2: pd.Series, window: int = 60) -> dict:
    """60-day rolling correlation summary (mean / std / max / min)."""
    df = pd.concat([r1, r2], axis=1, join="inner").dropna()
    if df.shape[0] < window + 5:
        return {"window": window, "n_overlap": int(df.shape[0]), "insufficient_overlap": True}
    rc = df.iloc[:, 0].rolling(window, min_periods=window).corr(df.iloc[:, 1]).dropna()
    return {
        "window": window,
        "n_overlap_obs": int(df.shape[0]),
        "n_rolling_pts": int(rc.shape[0]),
        "mean": float(rc.mean()),
        "std": float(rc.std(ddof=1)),
        "max": float(rc.max()),
        "min": float(rc.min()),
        "latest": float(rc.iloc[-1]),
    }


def static_corr_matrix(returns: dict[str, pd.Series]) -> dict:
    """Pearson correlation matrix on intersection of dates."""
    df = pd.concat(returns, axis=1).dropna()
    cm = df.corr()
    out = {}
    for a in cm.columns:
        for b in cm.columns:
            if a < b:
                out[f"{a}-{b}"] = float(cm.loc[a, b])
    return {"n_overlap_obs": int(df.shape[0]), "pairs": out}


def make_figures(prices: pd.DataFrame, returns: dict[str, pd.Series], garch_cond_vol: dict[str, pd.Series], out_dir: Path):
    """Generate 4 figures."""
    # Fig 1: cumulative returns overlay (normalized to 1.0 at each asset's start)
    fig, ax = plt.subplots(figsize=(10, 5))
    for t, r in returns.items():
        cum = np.exp(r.cumsum())
        ax.plot(cum.index, cum.values, label=t, linewidth=1.2)
    ax.set_yscale("log")
    ax.set_title("K1445 Fig 1 — Cumulative Log-Returns (log scale, each from own inception)")
    ax.set_ylabel("Cumulative growth (1.0 = inception)")
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.text(0.01, -0.15, "Source: yfinance | K1445 | https://volpred.zeabur.app", transform=ax.transAxes, fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out_dir / "fig1_cumulative_returns.png", dpi=150)
    plt.close(fig)

    # Fig 2: rolling 60d realized vol (annualized %)
    fig, ax = plt.subplots(figsize=(10, 5))
    for t, r in returns.items():
        rv = r.rolling(60, min_periods=60).std(ddof=1) * np.sqrt(252) * 100
        ax.plot(rv.index, rv.values, label=t, linewidth=1.0)
    ax.set_title("K1445 Fig 2 — Rolling 60-Day Annualized Volatility (%)")
    ax.set_ylabel("Annualized vol (%)")
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.text(0.01, -0.15, "Source: yfinance | K1445", transform=ax.transAxes, fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out_dir / "fig2_rolling_vol.png", dpi=150)
    plt.close(fig)

    # Fig 3: rolling 60d correlation URA-SPY & KRBN-SPY
    fig, ax = plt.subplots(figsize=(10, 5))
    for pair_name, (a, b) in [("URA-SPY", ("URA", "SPY")), ("KRBN-SPY", ("KRBN", "SPY")), ("URA-KRBN", ("URA", "KRBN"))]:
        if a in returns and b in returns:
            df = pd.concat([returns[a], returns[b]], axis=1, join="inner").dropna()
            if df.shape[0] >= 65:
                rc = df.iloc[:, 0].rolling(60, min_periods=60).corr(df.iloc[:, 1]).dropna()
                ax.plot(rc.index, rc.values, label=pair_name, linewidth=1.2)
    ax.axhline(0, color="black", linewidth=0.5, linestyle="--")
    ax.set_title("K1445 Fig 3 — Rolling 60-Day Correlation")
    ax.set_ylabel("Pearson ρ")
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.text(0.01, -0.15, "Source: yfinance | K1445", transform=ax.transAxes, fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out_dir / "fig3_rolling_corr.png", dpi=150)
    plt.close(fig)

    # Fig 4: GARCH conditional vol for URA + KRBN (annualized %)
    fig, ax = plt.subplots(figsize=(10, 5))
    for t in ("URA", "KRBN"):
        if t in garch_cond_vol:
            cv = garch_cond_vol[t] * np.sqrt(252) * 100
            ax.plot(cv.index, cv.values, label=f"{t} GARCH(1,1) cond vol", linewidth=1.0)
    ax.set_title("K1445 Fig 4 — GARCH(1,1) Conditional Volatility (annualized %)")
    ax.set_ylabel("Annualized cond vol (%)")
    ax.set_xlabel("Date")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.text(0.01, -0.15, "Source: yfinance | K1445", transform=ax.transAxes, fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out_dir / "fig4_garch_condvol.png", dpi=150)
    plt.close(fig)


def main():
    print("[K1445] Fetching prices ...")
    prices = fetch_prices(TICKERS, START_DEFAULT, END_DATE)
    print(f"[K1445] Raw price df shape: {prices.shape}")
    print(prices.head(3))
    print(prices.tail(3))

    returns: dict[str, pd.Series] = {}
    descriptive: dict[str, dict] = {}
    ljung: dict[str, dict] = {}
    archlm: dict[str, dict] = {}
    garch: dict[str, dict] = {}
    garch_cond_vol_for_plot: dict[str, pd.Series] = {}
    data_period: dict[str, dict] = {}

    for t in TICKERS:
        px = prices[t].dropna()
        if px.shape[0] < 100:
            print(f"[K1445] WARN: insufficient data for {t}: {px.shape[0]} obs")
            continue
        r = compute_log_returns(px)
        returns[t] = r
        data_period[t] = {
            "start": r.index.min().strftime("%Y-%m-%d"),
            "end": r.index.max().strftime("%Y-%m-%d"),
            "n_obs": int(r.shape[0]),
        }
        descriptive[t] = descriptive_stats(r)
        ljung[t] = ljungbox_squared(r, lags=10)
        archlm[t] = archlm_test(r, nlags=10)
        g = fit_garch11(r)
        garch_cond_vol_for_plot[t] = g.pop("_cond_vol")
        garch[t] = g
        print(f"[K1445] {t}: n={r.shape[0]} LB10={ljung[t]['pvalue']:.4g} ARCH-LM={archlm[t]['lm_pvalue']:.4g} α+β={garch[t]['persistence']:.4f}")

    # Correlation
    static_full = static_corr_matrix(returns)

    returns_2024 = {k: v[v.index >= "2024-01-01"] for k, v in returns.items()}
    static_2024 = static_corr_matrix(returns_2024)

    rolling_summary: dict[str, dict] = {}
    pairs = [("URA", "SPY"), ("URA", "TLT"), ("KRBN", "SPY"), ("KRBN", "TLT"), ("URA", "KRBN")]
    for a, b in pairs:
        if a in returns and b in returns:
            rolling_summary[f"{a}-{b}"] = rolling_corr_summary(returns[a], returns[b], window=60)

    # Figures
    print("[K1445] Generating figures ...")
    make_figures(prices, returns, garch_cond_vol_for_plot, OUT_DIR)

    # Verdict logic
    cluster_strong = all(
        (ljung[t]["pvalue"] < 0.01 and archlm[t]["lm_pvalue"] < 0.01 and garch[t]["persistence"] > 0.85)
        for t in ("URA", "KRBN") if t in ljung
    )
    cross_meaningful = False
    pairs_dict = static_full["pairs"]
    def _get_pair(a, b):
        return pairs_dict.get(f"{a}-{b}", pairs_dict.get(f"{b}-{a}"))
    ura_spy = _get_pair("URA", "SPY")
    krbn_spy = _get_pair("KRBN", "SPY")
    if ura_spy is not None and krbn_spy is not None:
        # "meaningful" = either pair shows |ρ|>0.2 OR rolling has wide swings (max-min>0.5)
        cross_meaningful = (abs(ura_spy) > 0.2 or abs(krbn_spy) > 0.2)
        if "URA-SPY" in rolling_summary and not rolling_summary["URA-SPY"].get("insufficient_overlap"):
            rng = rolling_summary["URA-SPY"]["max"] - rolling_summary["URA-SPY"]["min"]
            if rng > 0.5:
                cross_meaningful = True

    if cluster_strong and cross_meaningful:
        verdict = "PASS"
    elif cluster_strong or cross_meaningful:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    results = {
        "meta": {
            "k_id": "K1445",
            "run_at": datetime.utcnow().isoformat() + "Z",
            "seed": SEED,
            "end_date": END_DATE,
            "tickers": TICKERS,
            "data_period_per_asset": data_period,
        },
        "descriptive": descriptive,
        "ljungbox_squared_lag10": ljung,
        "arch_lm_lag10": archlm,
        "garch11": garch,
        "correlation": {
            "static_full_sample": static_full,
            "static_2024_onwards": static_2024,
            "rolling_60d_summary": rolling_summary,
        },
        "verdict": verdict,
        "figures": [
            "fig1_cumulative_returns.png",
            "fig2_rolling_vol.png",
            "fig3_rolling_corr.png",
            "fig4_garch_condvol.png",
        ],
    }

    out_json = OUT_DIR / "k1445_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[K1445] Results JSON: {out_json}")
    print(f"[K1445] Verdict: {verdict}")
    return results


if __name__ == "__main__":
    main()
