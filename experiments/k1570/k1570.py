#!/usr/bin/env python3
"""K1570: Office-CRE refinancing pressure and public REIT/bank volatility.

This is a free-public-proxy experiment. It does not observe loan-level CRE
maturity walls, bank CRE books, appraisal marks, or private refinancing
negotiations. It asks a narrower question: do release-lagged FRED CRE
delinquencies plus public office-REIT stress proxies lead regional-bank,
REIT, mortgage-REIT, and CMBS ETF forward volatility after standard market
controls?

Lookahead policy:
- Quarterly FRED CRE delinquency is usable only after quarter-end + 50 days.
- Every predictive signal is explicitly converted to *_lag1 = raw.shift(1).
- Forward outcomes use strictly returns in [t+1, t+H].
- HAC/Newey-West maxlags uses the forward horizon H for overlapping targets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import warnings
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats
from statsmodels.stats.multitest import multipletests

warnings.filterwarnings("ignore")

SEED = 42
RNG = np.random.default_rng(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
OUT_JSON = HERE / "k1570_results.json"
OUT_DATA = HERE / "k1570_analysis_dataset.csv"
FIG_SIGNAL = HERE / "fig1_cre_pressure_signals.png"
FIG_HEATMAP = HERE / "fig2_hac_tstat_heatmap.png"
FIG_EVENT = HERE / "fig3_top_decile_event.png"

START = "2012-01-01"
LAST_COMPLETE_UTC_DATE = datetime.now(timezone.utc).date() - timedelta(days=1)
END = (LAST_COMPLETE_UTC_DATE + timedelta(days=1)).isoformat()

FRED_SERIES = {
    "cre_delinquency": "DRCRELEXFACBS",
    "dgs10": "DGS10",
}

OFFICE_REITS = ["BXP", "VNO", "SLG", "KRC", "HIW", "CUZ", "DEI"]
TARGET_TICKERS = ["KRE", "KBE", "VNQ", "IYR", "XLRE", "REM", "CMBS"]
TARGET_NAMES = TARGET_TICKERS + ["OFFICE_REIT_BASKET"]
CONTROL_TICKERS = ["SPY", "^VIX", "HYG", "LQD", "MBB"]
PRICE_TICKERS = sorted(set(OFFICE_REITS + TARGET_TICKERS + CONTROL_TICKERS))

HORIZONS = [5, 21]
PRIMARY_OUTCOMES = ["log_fwd_rv", "log_fwd_downside_var"]
SECONDARY_OUTCOMES = ["fwd_cotail_kre_share"]
SIGNALS = ["cre_fundamental_pressure", "office_market_stress", "combined_cre_pressure"]
BOOTSTRAP_B = 1000
ROLL_Z = 756


def git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=HERE.parents[1],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def finite_or_none(obj):
    if isinstance(obj, dict):
        return {k: finite_or_none(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [finite_or_none(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return float(obj) if np.isfinite(obj) else None
    return obj


def describe(s: pd.Series) -> dict:
    x = s.dropna()
    if x.empty:
        return {"n": 0}
    return {
        "n": int(x.shape[0]),
        "start": str(x.index.min().date()),
        "end": str(x.index.max().date()),
        "mean": float(x.mean()),
        "std": float(x.std(ddof=1)),
        "p05": float(x.quantile(0.05)),
        "p50": float(x.quantile(0.50)),
        "p95": float(x.quantile(0.95)),
    }


def rolling_z(s: pd.Series, window: int = ROLL_Z, min_periods: int = 252) -> pd.Series:
    mu = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std(ddof=1)
    return ((s - mu) / sd).replace([np.inf, -np.inf], np.nan)


def fetch_fred(series_id: str, refresh: bool = False) -> tuple[pd.Series, dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"fred_{series_id}.csv"
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    fetched = False
    if not path.exists() or refresh:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        path.write_bytes(resp.content)
        fetched = True
    df = pd.read_csv(path)
    if "observation_date" not in df.columns or series_id not in df.columns:
        raise RuntimeError(f"Unexpected FRED payload for {series_id}: {df.columns.tolist()}")
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    vals = pd.to_numeric(df[series_id].replace(".", np.nan), errors="coerce")
    s = pd.Series(vals.to_numpy(), index=df["observation_date"], name=series_id).dropna()
    info = {
        "series_id": series_id,
        "source_url": url,
        "cache_path": str(path.relative_to(HERE.parents[1])),
        "sha256": sha256_file(path),
        "fetched": fetched,
        "n": int(s.shape[0]),
        "start": str(s.index.min().date()) if not s.empty else None,
        "end": str(s.index.max().date()) if not s.empty else None,
    }
    return s, info


def fred_quarterly_release_lag_to_daily(
    quarterly: pd.Series,
    daily_index: pd.DatetimeIndex,
    *,
    lag_days_after_quarter_end: int = 50,
) -> pd.Series:
    """Map quarter-start observations to daily availability with a conservative lag."""
    available_idx = []
    values = []
    for obs_date, value in quarterly.dropna().items():
        q_end = pd.Timestamp(obs_date) + pd.offsets.QuarterEnd(0)
        available_idx.append((q_end + pd.Timedelta(days=lag_days_after_quarter_end)).normalize())
        values.append(value)
    released = pd.Series(values, index=pd.to_datetime(available_idx), name=quarterly.name)
    released = released[~released.index.duplicated(keep="last")].sort_index()
    return released.reindex(daily_index).ffill()


def fetch_prices(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "yfinance_close.csv"
    fetched = False
    if not path.exists() or refresh:
        raw = yf.download(
            PRICE_TICKERS,
            start=START,
            end=END,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if not isinstance(raw.columns, pd.MultiIndex):
            raise RuntimeError("Expected yfinance multi-ticker response")
        close = raw["Close"].copy()
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        close = close.sort_index()
        close.to_csv(path)
        fetched = True
    close = pd.read_csv(path, index_col=0, parse_dates=True)
    close = close.dropna(axis=1, thresh=500)
    missing_required = [t for t in ["KRE", "VNQ", "SPY", "^VIX", "HYG", "LQD"] if t not in close.columns]
    if missing_required:
        raise RuntimeError(f"Missing required yfinance tickers: {missing_required}")
    info = {
        "source": "yfinance auto_adjust=True close prices",
        "cache_path": str(path.relative_to(HERE.parents[1])),
        "sha256": sha256_file(path),
        "fetched": fetched,
        "tickers_requested": PRICE_TICKERS,
        "tickers_used": list(close.columns),
        "start": str(close.index.min().date()),
        "end": str(close.index.max().date()),
    }
    return close, info


def forward_window_std(ret: pd.Series, h: int) -> pd.Series:
    return ret.shift(-1).rolling(h, min_periods=h).std(ddof=1).shift(-(h - 1))


def forward_window_mean(s: pd.Series, h: int) -> pd.Series:
    return s.shift(-1).rolling(h, min_periods=h).mean().shift(-(h - 1))


def block_bootstrap_spearman(x: pd.Series, y: pd.Series, block: int, b: int = BOOTSTRAP_B) -> dict:
    df = pd.concat([x, y], axis=1).dropna()
    df.columns = ["x", "y"]
    n = df.shape[0]
    if n < max(80, block * 5) or df["x"].nunique() < 3 or df["y"].nunique() < 3:
        return {"n": int(n), "rho": None, "ci95": [None, None], "p_boot_two_sided": None}
    rho = float(stats.spearmanr(df["x"], df["y"]).statistic)
    # Fast moving-block bootstrap on precomputed ranks. This is equivalent to
    # bootstrapping the Spearman inputs after converting each variable to its
    # full-sample rank scale and avoids 1000 expensive rankdata calls per cell.
    rx = stats.rankdata(df["x"].to_numpy())
    ry = stats.rankdata(df["y"].to_numpy())
    starts = np.arange(0, n - block + 1)
    n_blocks = int(np.ceil(n / block))
    start_draws = RNG.choice(starts, size=(b, n_blocks), replace=True)
    offsets = np.arange(block)
    idx = (start_draws[:, :, None] + offsets[None, None, :]).reshape(b, -1)[:, :n]
    bx = rx[idx]
    by = ry[idx]
    bx = bx - bx.mean(axis=1, keepdims=True)
    by = by - by.mean(axis=1, keepdims=True)
    denom = np.sqrt((bx * bx).sum(axis=1) * (by * by).sum(axis=1))
    boot = ((bx * by).sum(axis=1) / denom)
    boot = boot[np.isfinite(boot)]
    ci = np.quantile(boot, [0.025, 0.975])
    p = 2 * min(float(np.mean(boot <= 0)), float(np.mean(boot >= 0)))
    return {
        "n": int(n),
        "rho": rho,
        "ci95": [float(ci[0]), float(ci[1])],
        "p_boot_two_sided": float(min(1.0, p)),
    }


def hac_regression(df: pd.DataFrame, y_col: str, x_col: str, controls: list[str], maxlags: int) -> dict | None:
    cols = [y_col, x_col] + controls
    d = df[cols].replace([np.inf, -np.inf], np.nan).dropna()
    if d.shape[0] < 250 or d[x_col].std(ddof=1) == 0:
        return None
    y = d[y_col]
    x = sm.add_constant(d[[x_col] + controls], has_constant="add")
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "n": int(d.shape[0]),
        "coef": float(model.params[x_col]),
        "t": float(model.tvalues[x_col]),
        "p": float(model.pvalues[x_col]),
        "r2": float(model.rsquared),
        "maxlags": int(maxlags),
    }


def event_study(df: pd.DataFrame, signal: str, outcome: str, h: int) -> dict | None:
    cols = [signal, outcome]
    d = df[cols].dropna()
    if d.shape[0] < 300:
        return None
    thresh = d[signal].quantile(0.90)
    stress = d[d[signal] >= thresh][outcome]
    base = d[d[signal] < thresh][outcome]
    if stress.shape[0] < 20 or base.shape[0] < 100:
        return None
    diff = float(stress.mean() - base.mean())
    stress_exp_mean = float(np.exp(stress).mean())
    base_exp_mean = float(np.exp(base).mean())
    exp_mean_ratio = float(stress_exp_mean / base_exp_mean) if base_exp_mean != 0 else None
    # Block bootstrap over contiguous rows to respect overlapping forward windows.
    vals = d.to_numpy()
    block = h
    starts = np.arange(0, vals.shape[0] - block + 1)
    boot = []
    for _ in range(BOOTSTRAP_B):
        idx_parts = []
        while len(idx_parts) * block < vals.shape[0]:
            st = int(RNG.choice(starts))
            idx_parts.append(np.arange(st, st + block))
        idx = np.concatenate(idx_parts)[: vals.shape[0]]
        sample = pd.DataFrame(vals[idx], columns=cols)
        q = sample[signal].quantile(0.90)
        s = sample[sample[signal] >= q][outcome]
        b = sample[sample[signal] < q][outcome]
        if s.shape[0] and b.shape[0]:
            boot.append(float(s.mean() - b.mean()))
    ci = np.quantile(np.asarray(boot), [0.025, 0.975])
    p = 2 * min(np.mean(np.asarray(boot) <= 0), np.mean(np.asarray(boot) >= 0))
    return {
        "n": int(d.shape[0]),
        "stress_n": int(stress.shape[0]),
        "threshold": float(thresh),
        "stress_mean": float(stress.mean()),
        "base_mean": float(base.mean()),
        "stress_exp_mean": stress_exp_mean,
        "base_exp_mean": base_exp_mean,
        "diff": diff,
        "exp_mean_ratio": exp_mean_ratio,
        "ci95": [float(ci[0]), float(ci[1])],
        "p_boot_two_sided": float(min(1.0, p)),
    }


def build_dataset(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    close, price_info = fetch_prices(refresh=refresh)
    ret = np.log(close / close.shift(1))

    office_members = [t for t in OFFICE_REITS if t in ret.columns]
    if len(office_members) < 4:
        raise RuntimeError(f"Too few office REIT proxies: {office_members}")
    ret["OFFICE_REIT_BASKET"] = ret[office_members].mean(axis=1)
    close["OFFICE_REIT_BASKET"] = (1 + ret["OFFICE_REIT_BASKET"].fillna(0)).cumprod() * 100

    fred_info = {}
    cre_q, fred_info["cre_delinquency"] = fetch_fred(FRED_SERIES["cre_delinquency"], refresh=refresh)
    dgs10, fred_info["dgs10"] = fetch_fred(FRED_SERIES["dgs10"], refresh=refresh)
    dgs10_daily = dgs10.reindex(close.index).ffill()
    cre_daily = fred_quarterly_release_lag_to_daily(cre_q, close.index, lag_days_after_quarter_end=50)

    df = pd.DataFrame(index=close.index)
    df["cre_delinquency_release_lagged"] = cre_daily
    df["dgs10"] = dgs10_daily

    office_rv21 = ret["OFFICE_REIT_BASKET"].rolling(21, min_periods=15).std(ddof=1) * np.sqrt(252)
    office_dd63 = -ret["OFFICE_REIT_BASKET"].rolling(63, min_periods=40).sum()
    cre_delinq_z = rolling_z(df["cre_delinquency_release_lagged"], window=ROLL_Z, min_periods=252)
    cre_delinq_change_1y_z = rolling_z(df["cre_delinquency_release_lagged"].diff(252), window=ROLL_Z, min_periods=252)
    rate_z = rolling_z(df["dgs10"], window=ROLL_Z, min_periods=252)
    office_rv_z = rolling_z(office_rv21, window=ROLL_Z, min_periods=252)
    office_dd_z = rolling_z(office_dd63, window=ROLL_Z, min_periods=252)

    raw_signals = pd.DataFrame(index=df.index)
    raw_signals["cre_fundamental_pressure"] = pd.concat(
        [cre_delinq_z, cre_delinq_change_1y_z, rate_z], axis=1
    ).mean(axis=1)
    raw_signals["office_market_stress"] = pd.concat([office_rv_z, office_dd_z], axis=1).mean(axis=1)
    raw_signals["combined_cre_pressure"] = pd.concat(
        [raw_signals["cre_fundamental_pressure"], raw_signals["office_market_stress"]], axis=1
    ).mean(axis=1)

    for sig in SIGNALS:
        df[f"{sig}_raw"] = raw_signals[sig]
        df[f"{sig}_lag1"] = raw_signals[sig].shift(1)

    spy_rv21 = ret["SPY"].rolling(21, min_periods=15).std(ddof=1) * np.sqrt(252)
    credit_spread = -(ret["HYG"] - ret["LQD"]).rolling(21, min_periods=15).sum()
    df["spy_log_rv21_lag1"] = np.log(spy_rv21.shift(1) ** 2 + 1e-10)
    df["vix_level_lag1"] = close["^VIX"].shift(1)
    df["vix_z_lag1"] = rolling_z(close["^VIX"], window=ROLL_Z, min_periods=252).shift(1)
    df["credit_spread_stress_lag1"] = rolling_z(credit_spread, window=ROLL_Z, min_periods=252).shift(1)

    target_available = [t for t in TARGET_NAMES if t in ret.columns]
    for target in target_available:
        rv21 = ret[target].rolling(21, min_periods=15).std(ddof=1) * np.sqrt(252)
        df[f"{target}_own_log_rv21_lag1"] = np.log(rv21.shift(1) ** 2 + 1e-10)
        q10 = ret[target].rolling(252, min_periods=126).quantile(0.10).shift(1)
        target_tail = ret[target] <= q10
        kre_q10 = ret["KRE"].rolling(252, min_periods=126).quantile(0.10).shift(1)
        kre_tail = ret["KRE"] <= kre_q10
        cotail = (target_tail & kre_tail).astype(float)
        for h in HORIZONS:
            fwd_rv = forward_window_std(ret[target], h) * np.sqrt(252)
            fwd_downside_var = forward_window_mean(np.minimum(ret[target], 0.0) ** 2, h) * 252
            df[f"{target}_h{h}_log_fwd_rv"] = np.log(fwd_rv**2 + 1e-10)
            df[f"{target}_h{h}_log_fwd_downside_var"] = np.log(fwd_downside_var + 1e-10)
            if target != "KRE":
                df[f"{target}_h{h}_fwd_cotail_kre_share"] = forward_window_mean(cotail, h)

    metadata = {
        "price_info": price_info,
        "fred_info": fred_info,
        "office_reit_members_used": office_members,
        "target_names": target_available,
        "release_lag_policy": "DRCRELEXFACBS quarterly observation usable at quarter-end + 50 calendar days, then ffilled to trading days",
    }
    return df, metadata


def run_analysis(df: pd.DataFrame, metadata: dict) -> dict:
    tests = []
    spearman = []
    event_results = {}
    targets = metadata["target_names"]
    controls_base = ["spy_log_rv21_lag1", "vix_z_lag1", "credit_spread_stress_lag1"]

    for target in targets:
        own = f"{target}_own_log_rv21_lag1"
        for h in HORIZONS:
            for outcome in PRIMARY_OUTCOMES + SECONDARY_OUTCOMES:
                y_col = f"{target}_h{h}_{outcome}"
                if y_col not in df.columns:
                    continue
                controls = [own] + controls_base
                for sig in SIGNALS:
                    x_col = f"{sig}_lag1"
                    reg = hac_regression(df, y_col, x_col, controls, maxlags=h)
                    if reg is None:
                        continue
                    is_primary = outcome in PRIMARY_OUTCOMES
                    entry = {
                        "target": target,
                        "horizon": h,
                        "outcome": outcome,
                        "signal": sig,
                        "y_col": y_col,
                        "x_col": x_col,
                        "primary_family": is_primary,
                        **reg,
                    }
                    tests.append(entry)
                    if is_primary:
                        sp = block_bootstrap_spearman(df[x_col], df[y_col], block=h)
                        spearman.append(
                            {
                                "target": target,
                                "horizon": h,
                                "outcome": outcome,
                                "signal": sig,
                                **sp,
                            }
                        )

    test_df = pd.DataFrame(tests)
    if not test_df.empty:
        primary_mask = test_df["primary_family"].to_numpy(dtype=bool)
        test_df["p_bonferroni"] = np.nan
        test_df["p_holm"] = np.nan
        if primary_mask.any():
            pvals = test_df.loc[primary_mask, "p"].to_numpy()
            _, p_bonf, _, _ = multipletests(pvals, alpha=0.05, method="bonferroni")
            _, p_holm, _, _ = multipletests(pvals, alpha=0.05, method="holm")
            test_df.loc[primary_mask, "p_bonferroni"] = p_bonf
            test_df.loc[primary_mask, "p_holm"] = p_holm
        test_df["positive_holm_survivor"] = (
            test_df["primary_family"]
            & (test_df["coef"] > 0)
            & (test_df["p_holm"] < 0.05)
            & (test_df["t"].abs() >= 3.0)
        )
    else:
        test_df["positive_holm_survivor"] = []

    for target in targets:
        y_col = f"{target}_h21_log_fwd_rv"
        if y_col in df.columns:
            event_results[target] = event_study(df, "combined_cre_pressure_lag1", y_col, h=21)

    survivors = test_df[test_df.get("positive_holm_survivor", False)] if not test_df.empty else pd.DataFrame()
    if survivors.empty:
        verdict = "NULL"
        reason = "No positive CRE-stress coefficient survives Holm adjustment plus Harvey |t|>=3 in the primary RV/downside family."
    else:
        unique_targets = sorted(survivors["target"].unique())
        if len(unique_targets) >= 3:
            verdict = "CONDITIONAL_PASS"
            reason = f"Positive Holm/Harvey survivors across {len(unique_targets)} targets: {unique_targets}."
        else:
            verdict = "WEAK_PARTIAL"
            reason = f"Positive Holm/Harvey survivors are narrow: {unique_targets}."

    primary = test_df[test_df["primary_family"]].copy() if not test_df.empty else pd.DataFrame()
    summary = {
        "verdict": verdict,
        "reason": reason,
        "n_primary_tests": int(primary.shape[0]),
        "n_positive_holm_harvey_survivors": int(survivors.shape[0]),
        "positive_holm_harvey_survivors": survivors.sort_values("p_holm").head(20).to_dict("records"),
        "top_positive_primary_raw": primary[primary["coef"] > 0].sort_values("p").head(20).to_dict("records"),
        "top_negative_primary_raw": primary[primary["coef"] < 0].sort_values("p").head(10).to_dict("records"),
    }
    return {
        "summary": summary,
        "hac_tests": test_df.sort_values(["primary_family", "p"], ascending=[False, True]).to_dict("records"),
        "spearman_block_bootstrap": spearman,
        "event_study_top_decile_combined_h21_log_rv": event_results,
    }


def make_figures(df: pd.DataFrame, results: dict) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    cols = ["cre_fundamental_pressure_lag1", "office_market_stress_lag1", "combined_cre_pressure_lag1"]
    titles = ["FRED CRE delinquency + 10Y pressure", "Office REIT market stress", "Combined CRE pressure"]
    for ax, col, title in zip(axes, cols, titles):
        df[col].plot(ax=ax, lw=1.0)
        ax.axhline(0, color="black", lw=0.7)
        ax.set_title(title)
        ax.set_ylabel("z-score")
    fig.suptitle("K1570 lookahead-safe CRE stress proxies (all lagged one day)")
    fig.tight_layout()
    fig.savefig(FIG_SIGNAL, dpi=160)
    plt.close(fig)

    tests = pd.DataFrame(results["hac_tests"])
    primary = tests[
        (tests["primary_family"])
        & (tests["signal"] == "combined_cre_pressure")
        & (tests["outcome"] == "log_fwd_rv")
    ].copy()
    if not primary.empty:
        pivot = primary.pivot_table(index="target", columns="horizon", values="t", aggfunc="first")
        fig, ax = plt.subplots(figsize=(7, 5))
        im = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="RdBu_r", vmin=-4, vmax=4)
        ax.set_xticks(range(len(pivot.columns)), [f"h={c}" for c in pivot.columns])
        ax.set_yticks(range(len(pivot.index)), pivot.index)
        for i in range(pivot.shape[0]):
            for j in range(pivot.shape[1]):
                val = pivot.iloc[i, j]
                ax.text(j, i, f"{val:.2f}" if np.isfinite(val) else "", ha="center", va="center", fontsize=8)
        ax.set_title("Combined CRE pressure HAC t-stat on forward RV")
        fig.colorbar(im, ax=ax, label="HAC t-stat")
        fig.tight_layout()
        fig.savefig(FIG_HEATMAP, dpi=160)
        plt.close(fig)

    ev = results["event_study_top_decile_combined_h21_log_rv"]
    labels, ratios = [], []
    for target, payload in ev.items():
        if payload and payload.get("exp_mean_ratio") is not None:
            labels.append(target)
            ratios.append(payload["exp_mean_ratio"])
    if labels:
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.bar(labels, ratios, color="#5a7896")
        ax.axhline(1, color="black", lw=0.8)
        ax.set_ylabel("Top-decile / base mean exp(log RV variance)")
        ax.set_title("Combined CRE pressure top-decile event diagnostic (h=21)")
        ax.tick_params(axis="x", rotation=35)
        fig.tight_layout()
        fig.savefig(FIG_EVENT, dpi=160)
        plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="refresh yfinance/FRED caches")
    args = ap.parse_args()

    df, metadata = build_dataset(refresh=args.refresh)
    results = run_analysis(df, metadata)
    make_figures(df, results)
    df.to_csv(OUT_DATA)

    data_sources = {
        "literature_and_context": [
            {
                "name": "Federal Reserve Financial Stability Report",
                "url": "https://www.federalreserve.gov/publications/financial-stability-report.htm",
                "role": "Motivates monitoring commercial-real-estate vulnerabilities and bank exposure.",
            },
            {
                "name": "FRED DRCRELEXFACBS",
                "url": "https://fred.stlouisfed.org/series/DRCRELEXFACBS",
                "role": "Quarterly delinquency rate on CRE loans excluding farmland, all commercial banks.",
            },
            {
                "name": "Gupta, Mittal, Peeters, Van Nieuwerburgh remote-work CRE evidence",
                "url": "https://www.nber.org/papers/w30526",
                "role": "Remote-work shock motivates office-specific CRE stress channel; cited as academic context.",
            },
        ],
        "market_data": metadata["price_info"],
        "fred": metadata["fred_info"],
    }

    payload = {
        "experiment_id": "K1570",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_rev": git_rev(),
        "seed": SEED,
        "sample": {
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "rows": int(df.shape[0]),
        },
        "data_sources": data_sources,
        "metadata": metadata,
        "lookahead_policy": {
            "fred_cre_delinquency": "quarter-end + 50 calendar days before daily forward-fill",
            "signals": "all predictive signals have explicit *_lag1 = raw.shift(1)",
            "forward_targets": "forward_window uses ret.shift(-1).rolling(H).shift(-(H-1)), i.e. [t+1,t+H]",
            "hac": "Newey-West maxlags equals forecast horizon H for overlapping labels",
        },
        "signals": SIGNALS,
        "horizons": HORIZONS,
        "primary_outcomes": PRIMARY_OUTCOMES,
        "secondary_outcomes": SECONDARY_OUTCOMES,
        "controls": ["own_log_rv21_lag1", "spy_log_rv21_lag1", "vix_z_lag1", "credit_spread_stress_lag1"],
        **results,
        "figures": [str(FIG_SIGNAL.name), str(FIG_HEATMAP.name), str(FIG_EVENT.name)],
        "output_files": {
            "analysis_dataset": str(OUT_DATA.name),
            "results_json": str(OUT_JSON.name),
        },
    }
    OUT_JSON.write_text(json.dumps(finite_or_none(payload), ensure_ascii=False, indent=2))
    print(json.dumps(finite_or_none(payload["summary"]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
