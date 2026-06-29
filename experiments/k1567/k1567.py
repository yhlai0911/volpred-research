#!/usr/bin/env python3
"""K1567: Public merchant-platform credit-stress proxy and ETF forward RV.

This is a free-data proxy screen. It does not observe merchant-level platform
loan approvals, underwriting enforcement, take rates, reserves, or delinquency.
It uses public equity stress in merchant / fintech platform names plus FRED
small-business credit background series.

Lookahead policy:
- Stress components at date t use rolling baselines ending at t-1.
- Tested predictors are explicitly shifted once: signal_lag1 = signal.shift(1).
- Forward targets use strictly [t+1, t+H].
- FRED low-frequency series are release-lagged conservatively before daily ffill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

SEED = 42
RNG = np.random.default_rng(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
OUT_JSON = HERE / "k1567_results.json"
OUT_DATA = HERE / "k1567_analysis_dataset.csv"
FIG1 = HERE / "fig1_platform_credit_stress.png"
FIG2 = HERE / "fig2_hac_tstat_heatmap.png"
FIG3 = HERE / "fig3_combined_stress_vs_targets.png"

START = "2018-01-01"
LAST_COMPLETE_UTC_DATE = datetime.now(timezone.utc).date() - timedelta(days=1)
END = (LAST_COMPLETE_UTC_DATE + timedelta(days=1)).isoformat()

ROLL_Z = 252
RV_WINDOW = 21
BOOTSTRAP_B = 1000

MERCHANT_NAMES = ["SHOP", "XYZ", "PYPL", "MELI"]
CREDIT_FINTECH_NAMES = ["AFRM", "UPST"]
TARGETS = ["IWM", "XRT", "KRE", "HYG"]
CONTROLS = ["SPY", "^VIX"]
PRICE_TICKERS = MERCHANT_NAMES + CREDIT_FINTECH_NAMES + TARGETS + CONTROLS
SIGNALS = ["merchant_platform_stress", "credit_fintech_stress", "combined_platform_stress"]
HORIZONS = [5, 21]

FRED_RELEASE_LAGS = {
    "BUSLOANS": 30,   # monthly C&I loans; conservative date lag
    "DRBLACBS": 100,  # quarterly business-loan delinquency; conservative date lag
    "NFCI": 7,        # weekly financial conditions
    "STLFSI4": 7,     # weekly financial stress
}


@dataclass
class SourceInfo:
    path: Path
    source_url: str
    fetched: bool


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


def fetch_prices(refresh: bool) -> tuple[pd.DataFrame, SourceInfo]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "yfinance_prices.csv"
    if path.exists() and not refresh:
        close = pd.read_csv(path, index_col=0, parse_dates=True)
        return close, SourceInfo(path=path, source_url="yfinance adjusted close cache", fetched=False)

    raw = yf.download(
        PRICE_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = PRICE_TICKERS[:1]
    close = close.dropna(how="all").sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    keep = [c for c in PRICE_TICKERS if c in close.columns and close[c].dropna().shape[0] >= 100]
    missing_targets = [t for t in TARGETS + ["SPY", "^VIX"] if t not in keep]
    if missing_targets:
        raise RuntimeError(f"missing target/control yfinance data: {missing_targets}")
    close = close[keep]
    close.to_csv(path)
    return close, SourceInfo(path=path, source_url=f"yfinance adjusted close {START} to {END}", fetched=True)


def fetch_fred_series(series_id: str, refresh: bool) -> tuple[pd.Series, SourceInfo]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    path = DATA_DIR / f"fred_{series_id}.csv"
    if not path.exists() or refresh:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "volpred-k1567/1.0"})
        resp.raise_for_status()
        path.write_bytes(resp.content)
        fetched = True
    else:
        fetched = False
    df = pd.read_csv(path)
    if "observation_date" not in df.columns or series_id not in df.columns:
        raise RuntimeError(f"FRED schema changed for {series_id}: {path}")
    s = pd.Series(
        pd.to_numeric(df[series_id], errors="coerce").values,
        index=pd.to_datetime(df["observation_date"]),
        name=series_id,
    ).dropna().sort_index()
    return s, SourceInfo(path=path, source_url=url, fetched=fetched)


def rolling_z(s: pd.Series, window: int = ROLL_Z) -> pd.Series:
    mu = s.rolling(window, min_periods=max(30, window // 4)).mean().shift(1)
    sd = s.rolling(window, min_periods=max(30, window // 4)).std(ddof=1).shift(1)
    return ((s - mu) / sd).replace([np.inf, -np.inf], np.nan)


def equal_weight_return(ret: pd.DataFrame, tickers: list[str], min_count: int) -> pd.Series:
    available = [t for t in tickers if t in ret.columns]
    if not available:
        return pd.Series(index=ret.index, dtype=float)
    return ret[available].mean(axis=1, skipna=True).where(ret[available].count(axis=1) >= min_count)


def build_stress_signal(basket_ret: pd.Series, prefix: str) -> pd.DataFrame:
    ret_5d = basket_ret.rolling(5, min_periods=5).sum()
    rv_21 = basket_ret.rolling(RV_WINDOW, min_periods=RV_WINDOW).std(ddof=1) * np.sqrt(252)
    index = np.exp(basket_ret.dropna().cumsum())
    dd_63 = np.log(index / index.rolling(63, min_periods=20).max())
    dd_63 = dd_63.reindex(basket_ret.index)
    out = pd.DataFrame(index=basket_ret.index)
    out[f"{prefix}_ret5"] = ret_5d
    out[f"{prefix}_rv21"] = rv_21
    out[f"{prefix}_drawdown63"] = dd_63
    out[f"{prefix}_stress"] = pd.concat(
        [
            rolling_z(-ret_5d),
            rolling_z(rv_21),
            rolling_z(-dd_63),
        ],
        axis=1,
    ).mean(axis=1, skipna=False)
    return out


def release_lagged_daily_fred(s: pd.Series, series_id: str, daily_index: pd.DatetimeIndex) -> pd.Series:
    lag_days = FRED_RELEASE_LAGS[series_id]
    shifted = s.copy()
    shifted.index = shifted.index + pd.to_timedelta(lag_days, unit="D")
    return shifted.reindex(daily_index.union(shifted.index)).sort_index().ffill().reindex(daily_index)


def build_feature_matrix(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    close, price_info = fetch_prices(refresh=refresh)
    close = close.loc[(close.index >= pd.Timestamp(START)) & (close.index <= pd.Timestamp(LAST_COMPLETE_UTC_DATE))]
    us_calendar_cols = [c for c in TARGETS + ["SPY", "^VIX"] if c in close.columns]
    # yfinance can retain non-US/partial calendar rows because MELI or other
    # cross-listed names trade while US ETFs are closed. The experiment target
    # is US ETF RV, so use the target/control trading calendar as the panel
    # calendar before rolling-window features are computed.
    close = close.loc[close[us_calendar_cols].notna().all(axis=1)].copy()
    ret = np.log(close / close.shift(1))
    df = close.copy()

    merchant_ret = equal_weight_return(ret, MERCHANT_NAMES, min_count=3)
    credit_ret = equal_weight_return(ret, CREDIT_FINTECH_NAMES, min_count=2)
    combined_ret = pd.concat([merchant_ret, credit_ret], axis=1).mean(axis=1, skipna=False)
    df["merchant_platform_ret"] = merchant_ret
    df["credit_fintech_ret"] = credit_ret
    df["combined_platform_ret"] = combined_ret
    df = pd.concat(
        [
            df,
            build_stress_signal(merchant_ret, "merchant_platform"),
            build_stress_signal(credit_ret, "credit_fintech"),
            build_stress_signal(combined_ret, "combined_platform"),
        ],
        axis=1,
    )

    for sig in SIGNALS:
        df[f"{sig}_lag1"] = df[sig].shift(1)

    for ticker in [c for c in close.columns if c not in ["^VIX"]]:
        r = ret[ticker]
        df[f"{ticker}_ret"] = r
        rv21 = r.rolling(RV_WINDOW, min_periods=RV_WINDOW).std(ddof=1).pow(2) * 252
        df[f"{ticker}_log_rv21_lag1"] = np.log(rv21 + 1e-12).shift(1)
        for horizon in HORIZONS:
            future_r2 = pd.concat([r.pow(2).shift(-i) for i in range(1, horizon + 1)], axis=1)
            future_ret = pd.concat([r.shift(-i) for i in range(1, horizon + 1)], axis=1)
            df[f"{ticker}_fwd_rv_{horizon}d"] = future_r2.mean(axis=1, skipna=False) * 252
            df[f"{ticker}_fwd_log_rv_{horizon}d"] = np.log(df[f"{ticker}_fwd_rv_{horizon}d"] + 1e-12)
            df[f"{ticker}_fwd_cumret_{horizon}d"] = np.exp(future_ret.sum(axis=1, skipna=False)) - 1.0

    if "^VIX" in close.columns:
        df["VIX_level_lag1"] = close["^VIX"].shift(1)

    fred_meta = {}
    fred_daily = pd.DataFrame(index=df.index)
    for series_id in FRED_RELEASE_LAGS:
        s, info = fetch_fred_series(series_id, refresh=refresh)
        daily = release_lagged_daily_fred(s, series_id, df.index)
        fred_daily[series_id] = daily
        fred_meta[series_id] = {
            "url": info.source_url,
            "path": str(info.path.relative_to(HERE)),
            "sha256": sha256_file(info.path),
            "release_lag_days": FRED_RELEASE_LAGS[series_id],
        }
    fred_daily["BUSLOANS_6m_growth"] = fred_daily["BUSLOANS"].pct_change(126)
    fred_daily["small_business_credit_stress"] = pd.concat(
        [
            rolling_z(-fred_daily["BUSLOANS_6m_growth"], window=756),
            rolling_z(fred_daily["DRBLACBS"], window=756),
        ],
        axis=1,
    ).mean(axis=1, skipna=False)
    fred_daily["financial_conditions_stress"] = pd.concat(
        [rolling_z(fred_daily["NFCI"], window=252), rolling_z(fred_daily["STLFSI4"], window=252)],
        axis=1,
    ).mean(axis=1, skipna=False)
    df = pd.concat([df, fred_daily], axis=1)

    df.to_csv(OUT_DATA)
    source_meta = {
        "yfinance_prices": {
            "url": price_info.source_url,
            "path": str(price_info.path.relative_to(HERE)),
            "sha256": sha256_file(price_info.path),
            "ticker_note": "SQ was requested in the backlog, but Block trades as XYZ in the current yfinance snapshot; XYZ is used.",
        },
        "fred": fred_meta,
        "analysis_dataset": {
            "path": str(OUT_DATA.relative_to(HERE)),
            "sha256": sha256_file(OUT_DATA),
        },
    }
    return df, source_meta


def describe_series(s: pd.Series) -> dict:
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


def ols_hac(y: pd.Series, x: pd.Series, horizon: int, controls: pd.DataFrame | None = None) -> dict:
    pieces = [y.rename("y"), x.rename("x")]
    if controls is not None:
        pieces.append(controls)
    d = pd.concat(pieces, axis=1).dropna()
    if d.shape[0] < 240 or d["x"].std(ddof=1) <= 1e-12:
        return {"error": "insufficient_or_constant", "n": int(d.shape[0])}
    X_cols = ["x"] + ([] if controls is None else list(controls.columns))
    X = sm.add_constant(d[X_cols].values)
    model = sm.OLS(d["y"].values, X).fit(cov_type="HAC", cov_kwds={"maxlags": horizon})
    return {
        "n": int(d.shape[0]),
        "coef": float(model.params[1]),
        "hac_t": float(model.tvalues[1]),
        "p_value": float(model.pvalues[1]),
        "r2": float(model.rsquared),
        "controls": X_cols[1:],
    }


def block_bootstrap_spearman(x: pd.Series, y: pd.Series, block: int, reps: int = BOOTSTRAP_B) -> dict:
    d = pd.concat([x, y], axis=1).dropna()
    d.columns = ["x", "y"]
    n = d.shape[0]
    if n < max(240, block * 10) or d["x"].std(ddof=1) <= 1e-12 or d["y"].std(ddof=1) <= 1e-12:
        return {"error": "insufficient_or_constant", "n": int(n)}
    rho, p = stats.spearmanr(d["x"], d["y"])
    vals = []
    arr_x = d["x"].to_numpy()
    arr_y = d["y"].to_numpy()
    for _ in range(reps):
        idx = []
        while len(idx) < n:
            start = int(RNG.integers(0, max(n - block + 1, 1)))
            idx.extend(range(start, min(start + block, n)))
        idx = np.asarray(idx[:n])
        brho, _ = stats.spearmanr(arr_x[idx], arr_y[idx])
        if np.isfinite(brho):
            vals.append(float(brho))
    ci = [None, None]
    if len(vals) >= 100:
        ci = [float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))]
    return {
        "n": int(n),
        "rho": float(rho),
        "p_value": float(p),
        "block": int(block),
        "bootstrap_reps": int(len(vals)),
        "ci95": ci,
    }


def roc_auc_with_ci(score: pd.Series, event: pd.Series) -> dict:
    d = pd.concat([score, event], axis=1).dropna()
    d.columns = ["score", "event"]
    d["event"] = d["event"].astype(int)
    n1 = int(d["event"].sum())
    n0 = int((1 - d["event"]).sum())
    if d.shape[0] < 240 or n1 < 20 or n0 < 20:
        return {"error": "insufficient_tail_events", "n": int(d.shape[0]), "n_event": n1, "n_nonevent": n0}
    ranks = stats.rankdata(d["score"].to_numpy())
    rank_sum_pos = ranks[d["event"].to_numpy() == 1].sum()
    auc = (rank_sum_pos - n1 * (n1 + 1) / 2.0) / (n1 * n0)
    q1 = auc / (2 - auc) if auc < 1 else 1.0
    q2 = 2 * auc * auc / (1 + auc) if auc > 0 else 0.0
    se = np.sqrt(max((auc * (1 - auc) + (n1 - 1) * (q1 - auc * auc) + (n0 - 1) * (q2 - auc * auc)) / (n1 * n0), 0))
    return {
        "n": int(d.shape[0]),
        "n_event": n1,
        "n_nonevent": n0,
        "auc": float(auc),
        "ci95": [float(max(0.0, auc - 1.96 * se)), float(min(1.0, auc + 1.96 * se))],
        "se_hanley_mcneil": float(se),
    }


def holm_bonferroni(rows: list[dict], alpha: float = 0.05) -> dict:
    valid = [r for r in rows if np.isfinite(r.get("p_value", np.nan))]
    ordered = sorted(valid, key=lambda r: r["p_value"])
    decisions = []
    still_reject = True
    m = len(ordered)
    for i, row in enumerate(ordered):
        threshold = alpha / (m - i)
        reject = bool(still_reject and row["p_value"] <= threshold)
        if not reject:
            still_reject = False
        decisions.append({
            "label": row["label"],
            "p_value": float(row["p_value"]),
            "holm_threshold": float(threshold),
            "reject": reject,
            "coef": float(row["coef"]),
            "hac_t": float(row["hac_t"]),
        })
    return {
        "alpha": alpha,
        "n_tests": m,
        "bonferroni_alpha": float(alpha / m) if m else None,
        "bonferroni_survivors": [r["label"] for r in valid if r["p_value"] <= alpha / m],
        "holm_decisions": decisions,
        "holm_survivors": [r["label"] for r in decisions if r["reject"]],
    }


def run_tests(df: pd.DataFrame) -> tuple[dict, list[dict]]:
    out: dict = {}
    p_rows: list[dict] = []
    for target in TARGETS:
        out[target] = {}
        control_cols = [f"{target}_log_rv21_lag1", "SPY_log_rv21_lag1", "VIX_level_lag1"]
        controls = df[[c for c in control_cols if c in df.columns]].copy()
        controls.columns = [c.replace(f"{target}_", "own_") for c in controls.columns]
        for horizon in HORIZONS:
            y = df[f"{target}_fwd_log_rv_{horizon}d"]
            event_threshold = -0.03 if horizon == 5 else -0.07
            event = df[f"{target}_fwd_cumret_{horizon}d"] <= event_threshold
            out[target][f"{horizon}d"] = {}
            for sig in SIGNALS:
                x = df[f"{sig}_lag1"]
                univ = ols_hac(y, x, horizon=horizon)
                controlled = ols_hac(y, x, horizon=horizon, controls=controls)
                spear = block_bootstrap_spearman(x, y, block=horizon)
                auc = roc_auc_with_ci(x, event)
                out[target][f"{horizon}d"][sig] = {
                    "univariate_hac": univ,
                    "controlled_hac": controlled,
                    "spearman": spear,
                    "left_tail_auc": auc,
                    "tail_threshold": event_threshold,
                }
                if "p_value" in controlled:
                    label = f"{target}|{horizon}d|{sig}"
                    p_rows.append({
                        "label": label,
                        "p_value": controlled["p_value"],
                        "coef": controlled["coef"],
                        "hac_t": controlled["hac_t"],
                    })
    return out, p_rows


def assess_verdict(primary: dict, mt: dict) -> dict:
    raw_positive = []
    positive_survivors = []
    bonf = set(mt.get("bonferroni_survivors", []))
    for target, by_h in primary.items():
        for horizon, by_sig in by_h.items():
            for sig, res in by_sig.items():
                hac = res["controlled_hac"]
                if "p_value" not in hac:
                    continue
                label = f"{target}|{horizon}|{sig}"
                if hac["coef"] > 0 and hac["p_value"] < 0.05:
                    raw_positive.append(label)
                if label in bonf and hac["coef"] > 0:
                    positive_survivors.append(label)
    if positive_survivors:
        verdict = "MIXED_POSITIVE_DIAGNOSTIC"
        rationale = "At least one positive controlled-HAC coefficient survives Bonferroni, but proxy limitations still prevent causal merchant-credit claims."
    elif raw_positive:
        verdict = "WEAK_RAW_ONLY"
        rationale = "Some positive controlled coefficients are raw-significant, but no primary signal survives the 24-test family correction."
    else:
        verdict = "NULL"
        rationale = "No positive controlled primary coefficient is raw-significant; no evidence that the public platform-credit proxy leads target ETF RV."
    return {
        "verdict": verdict,
        "positive_raw_p_lt_0_05": raw_positive,
        "positive_bonferroni_survivors": positive_survivors,
        "rationale": rationale,
    }


def make_plots(df: pd.DataFrame, primary: dict) -> None:
    plot_df = df.loc[df.index >= "2020-01-01"].copy()
    fig, ax = plt.subplots(figsize=(11, 5))
    for col, color in [
        ("merchant_platform_stress", "tab:blue"),
        ("credit_fintech_stress", "tab:orange"),
        ("combined_platform_stress", "tab:red"),
        ("small_business_credit_stress", "tab:green"),
    ]:
        if col in plot_df:
            ax.plot(plot_df.index, plot_df[col], lw=1.0, alpha=0.85, label=col, color=color)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_title("K1567 platform / small-business credit-stress proxies")
    ax.set_ylabel("z-score style stress proxy")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG1, dpi=160)
    plt.close(fig)

    rows = []
    labels = []
    for target in TARGETS:
        for horizon in HORIZONS:
            rows.append([primary[target][f"{horizon}d"][sig]["controlled_hac"].get("hac_t", np.nan) for sig in SIGNALS])
            labels.append(f"{target} {horizon}d")
    arr = np.asarray(rows, dtype=float)
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    im = ax.imshow(arr, cmap="RdBu_r", vmin=-4, vmax=4, aspect="auto")
    ax.set_xticks(np.arange(len(SIGNALS)))
    ax.set_xticklabels(SIGNALS, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels)
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            txt = "" if not np.isfinite(arr[i, j]) else f"{arr[i, j]:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)
    ax.set_title("Controlled HAC t-stat: platform stress predicting target forward log-RV")
    fig.colorbar(im, ax=ax, label="controlled HAC t-stat")
    fig.tight_layout()
    fig.savefig(FIG2, dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharex=True)
    for ax, target in zip(axes.ravel(), TARGETS):
        d = pd.concat([df["combined_platform_stress_lag1"], df[f"{target}_fwd_log_rv_21d"]], axis=1).dropna()
        d.columns = ["stress", "log_rv"]
        if d.shape[0] > 1500:
            d = d.sample(1500, random_state=SEED)
        ax.scatter(d["stress"], d["log_rv"], s=8, alpha=0.25)
        if d.shape[0] > 20:
            m, b = np.polyfit(d["stress"], d["log_rv"], 1)
            xs = np.linspace(d["stress"].quantile(0.01), d["stress"].quantile(0.99), 100)
            ax.plot(xs, m * xs + b, color="tab:red", lw=1.4)
        ax.set_title(f"{target}: combined stress vs fwd 21d log-RV")
        ax.set_xlabel("combined stress lag1")
        ax.set_ylabel("forward 21d log-RV")
    fig.tight_layout()
    fig.savefig(FIG3, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload yfinance/FRED data")
    args = parser.parse_args()
    df, source_meta = build_feature_matrix(refresh=args.refresh)
    primary, p_rows = run_tests(df)
    mt = holm_bonferroni(p_rows)
    verdict = assess_verdict(primary, mt)
    make_plots(df, primary)

    descriptions = {
        "signals": {c: describe_series(df[c]) for c in SIGNALS + ["small_business_credit_stress", "financial_conditions_stress"] if c in df.columns},
        "targets": {
            t: {
                "price": describe_series(df[t]),
                "fwd_rv_5d": describe_series(df[f"{t}_fwd_rv_5d"]),
                "fwd_rv_21d": describe_series(df[f"{t}_fwd_rv_21d"]),
            }
            for t in TARGETS
        },
    }
    results = {
        "metadata": {
            "experiment_id": "K1567",
            "title": "Public merchant-platform credit-stress proxy as ETF short-RV signal",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed": SEED,
            "git_commit": git_rev(),
            "verdict": verdict["verdict"],
        },
        "data_sources": source_meta,
        "sample": {
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "n_trading_rows": int(df.shape[0]),
            "merchant_names": MERCHANT_NAMES,
            "credit_fintech_names": CREDIT_FINTECH_NAMES,
            "targets": TARGETS,
        },
        "methodology": {
            "proxy_limit": "No merchant-level loan, platform enforcement, approval, reserve, or delinquency data are observed. This is a public-equity/FRED proxy screen.",
            "signal_construction": "Platform stress averages lag-safe z-scores of negative 5d return, 21d realized vol, and 63d drawdown severity. Tested predictors are signal.shift(1).",
            "fred_publication_lag": "FRED series are shifted by conservative release lags before daily forward-fill: BUSLOANS 30d, DRBLACBS 100d, NFCI/STLFSI4 7d.",
            "forward_target": "Forward realized variance uses strictly close-to-close returns in [t+1, t+H].",
            "primary_regression": "Controlled HAC OLS: fwd_log_RV_H ~ signal_lag1 + own_log_RV21_lag1 + SPY_log_RV21_lag1 + VIX_level_lag1.",
            "hac_lag": "HAC maxlags equals forecast horizon H.",
            "spearman_ci": f"moving-block bootstrap with block=H, B={BOOTSTRAP_B}, seed={SEED}.",
            "auc_ci": "Hanley-McNeil normal approximation for left-tail event AUC.",
            "primary_family": "4 targets × 2 horizons × 3 signals = 24 controlled-HAC p-values.",
            "success_gate": "Positive controlled-HAC coefficient must survive family correction; AUC and Spearman are supporting diagnostics.",
        },
        "descriptive": descriptions,
        "primary_tests": primary,
        "multiple_testing": mt,
        "verdict_assessment": verdict,
        "figures": [str(FIG1.relative_to(HERE)), str(FIG2.relative_to(HERE)), str(FIG3.relative_to(HERE))],
    }
    OUT_JSON.write_text(json.dumps(finite_or_none(results), indent=2, ensure_ascii=False))
    print(json.dumps({"verdict": verdict["verdict"], "assessment": verdict, "results": str(OUT_JSON)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
