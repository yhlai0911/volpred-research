#!/usr/bin/env python3
"""K1566: DEX blockspace-pressure proxy as ETH/BTC short-RV signal.

Free-data design:
- Etherscan chart CSV daily average gas price and daily gas used.
- DefiLlama free API Ethereum DEX daily volume.
- yfinance adjusted close for ETH-USD, BTC-USD, and short-sample crypto equity/ETF proxies.

Lookahead policy:
- Signal shocks are measured at date t against a rolling baseline ending at t-1.
- Every predictor used in tests is explicitly shifted once: signal_lag1 = signal.shift(1).
- Forward targets use strictly [t+1, t+H] close-to-close returns.
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
OUT_JSON = HERE / "k1566_results.json"
OUT_DATA = HERE / "k1566_analysis_dataset.csv"
FIG1 = HERE / "fig1_blockspace_inputs.png"
FIG2 = HERE / "fig2_pressure_vs_crypto_rv.png"
FIG3 = HERE / "fig3_hac_tstat_heatmap.png"

START = "2019-01-01"
LAST_COMPLETE_UTC_DATE = datetime.now(timezone.utc).date() - timedelta(days=1)
END = (LAST_COMPLETE_UTC_DATE + timedelta(days=1)).isoformat()
ROLL = 90
BOOTSTRAP_B = 1000
PRIMARY_ASSETS = ["ETH-USD", "BTC-USD"]
SPILLOVER_ASSETS = ["COIN", "IBIT", "ETHA"]
ALL_ASSETS = PRIMARY_ASSETS + SPILLOVER_ASSETS
PRIMARY_SIGNALS = ["gas_price_shock", "dex_volume_shock", "blockspace_pressure"]
HORIZONS = [1, 5]


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


def fetch_text_cached(url: str, path: Path, refresh: bool = False) -> SourceInfo:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists() and not refresh:
        return SourceInfo(path=path, source_url=url, fetched=False)
    resp = requests.get(url, timeout=45, headers={"User-Agent": "volpred-k1566/1.0"})
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return SourceInfo(path=path, source_url=url, fetched=True)


def load_etherscan_chart(url: str, path: Path, value_name: str, refresh: bool) -> tuple[pd.Series, SourceInfo]:
    info = fetch_text_cached(url, path, refresh=refresh)
    df = pd.read_csv(info.path)
    if "Date(UTC)" not in df.columns:
        raise RuntimeError(f"Etherscan CSV schema changed: {info.path}")
    value_col = [c for c in df.columns if c.startswith("Value")][0]
    dates = pd.to_datetime(df["Date(UTC)"], utc=True).dt.tz_convert(None).dt.normalize()
    s = pd.Series(
        pd.to_numeric(df[value_col], errors="coerce").values,
        index=dates,
        name=value_name,
    ).sort_index()
    return s.replace([np.inf, -np.inf], np.nan).dropna(), info


def load_defillama_ethereum_dex(refresh: bool) -> tuple[pd.DataFrame, SourceInfo]:
    url = "https://api.llama.fi/overview/dexs/Ethereum"
    path = DATA_DIR / "defillama_ethereum_dexs_overview.json"
    info = fetch_text_cached(url, path, refresh=refresh)
    payload = json.loads(path.read_text())
    if "totalDataChart" not in payload:
        raise RuntimeError("DefiLlama overview/dexs/Ethereum missing totalDataChart")
    rows = payload["totalDataChart"]
    df = pd.DataFrame(rows, columns=["timestamp", "dex_volume_usd"])
    df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(None).dt.normalize()
    out = df.set_index("date")[["dex_volume_usd"]].sort_index()
    out["dex_volume_usd"] = pd.to_numeric(out["dex_volume_usd"], errors="coerce")
    return out.dropna(), info


def fetch_prices(refresh: bool) -> tuple[pd.DataFrame, SourceInfo]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "yfinance_prices.csv"
    if path.exists() and not refresh:
        close = pd.read_csv(path, index_col=0, parse_dates=True)
        return close, SourceInfo(path=path, source_url="yfinance adjusted close", fetched=False)
    raw = yf.download(ALL_ASSETS, start=START, end=END, auto_adjust=True, progress=False, threads=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = ALL_ASSETS[:1]
    keep = [c for c in ALL_ASSETS if c in close.columns and close[c].dropna().shape[0] >= 100]
    if not set(PRIMARY_ASSETS).issubset(set(keep)):
        raise RuntimeError(f"primary crypto yfinance data missing; available={keep}")
    close = close[keep].dropna(how="all").sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close.to_csv(path)
    return close, SourceInfo(path=path, source_url=f"yfinance adjusted close {START} to {END}", fetched=True)


def rolling_shock(log_series: pd.Series, window: int = ROLL) -> pd.Series:
    """Innovation z-score using a baseline ending at t-1."""
    innovation = log_series.diff()
    mu = innovation.rolling(window, min_periods=window).mean().shift(1)
    sd = innovation.rolling(window, min_periods=window).std(ddof=1).shift(1)
    return ((innovation - mu) / sd).replace([np.inf, -np.inf], np.nan)


def build_feature_matrix(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    gas_wei, gas_info = load_etherscan_chart(
        "https://etherscan.io/chart/gasprice?output=csv",
        DATA_DIR / "etherscan_gasprice.csv",
        "avg_gas_price_wei",
        refresh,
    )
    gas_used, gas_used_info = load_etherscan_chart(
        "https://etherscan.io/chart/gasused?output=csv",
        DATA_DIR / "etherscan_gasused.csv",
        "gas_used",
        refresh,
    )
    dex, dex_info = load_defillama_ethereum_dex(refresh=refresh)
    close, px_info = fetch_prices(refresh=refresh)

    df = pd.concat([gas_wei, gas_used, dex, close], axis=1).sort_index()
    df = df.loc[(df.index >= pd.Timestamp(START)) & (df.index <= pd.Timestamp(LAST_COMPLETE_UTC_DATE))].copy()
    df["avg_gas_price_gwei"] = df["avg_gas_price_wei"] / 1e9
    df["log_gas_price"] = np.log(df["avg_gas_price_gwei"].where(df["avg_gas_price_gwei"] > 0))
    df["log_gas_used"] = np.log(df["gas_used"].where(df["gas_used"] > 0))
    df["log_dex_volume"] = np.log1p(df["dex_volume_usd"])

    df["gas_price_shock"] = rolling_shock(df["log_gas_price"])
    df["gas_used_shock"] = rolling_shock(df["log_gas_used"])
    df["dex_volume_shock"] = rolling_shock(df["log_dex_volume"])
    df["blockspace_pressure"] = df[["gas_price_shock", "dex_volume_shock"]].mean(axis=1, skipna=False)

    # Explicit lookahead defense: all tested signals are lagged once.
    signal_cols = PRIMARY_SIGNALS + ["gas_used_shock"]
    for sig in signal_cols:
        df[f"{sig}_lag1"] = df[sig].shift(1)

    for asset in [c for c in ALL_ASSETS if c in df.columns]:
        ret = np.log(df[asset] / df[asset].shift(1))
        df[f"{asset}_ret"] = ret
        ann = 365 if asset in PRIMARY_ASSETS else 252
        for horizon in HORIZONS:
            future_r2 = pd.concat([ret.pow(2).shift(-i) for i in range(1, horizon + 1)], axis=1)
            future_ret = pd.concat([ret.shift(-i) for i in range(1, horizon + 1)], axis=1)
            df[f"{asset}_fwd_rv_{horizon}d"] = future_r2.mean(axis=1, skipna=False) * ann
            df[f"{asset}_fwd_log_rv_{horizon}d"] = np.log(df[f"{asset}_fwd_rv_{horizon}d"] + 1e-12)
            df[f"{asset}_fwd_cumret_{horizon}d"] = np.exp(future_ret.sum(axis=1, skipna=False)) - 1.0

    df.to_csv(OUT_DATA)
    source_meta = {
        "etherscan_gasprice": {
            "url": gas_info.source_url,
            "path": str(gas_info.path.relative_to(HERE)),
            "sha256": sha256_file(gas_info.path),
            "note": "Etherscan chart CSV; average gas price, not true priority fee / tip.",
        },
        "etherscan_gasused": {
            "url": gas_used_info.source_url,
            "path": str(gas_used_info.path.relative_to(HERE)),
            "sha256": sha256_file(gas_used_info.path),
        },
        "defillama_ethereum_dex_volume": {
            "url": dex_info.source_url,
            "path": str(dex_info.path.relative_to(HERE)),
            "sha256": sha256_file(dex_info.path),
        },
        "yfinance_prices": {
            "url": px_info.source_url,
            "path": str(px_info.path.relative_to(HERE)),
            "sha256": sha256_file(px_info.path),
        },
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
        "p01": float(x.quantile(0.01)),
        "p05": float(x.quantile(0.05)),
        "p50": float(x.quantile(0.50)),
        "p95": float(x.quantile(0.95)),
        "p99": float(x.quantile(0.99)),
    }


def hac_ols(y: pd.Series, x: pd.Series, horizon: int) -> dict:
    d = pd.concat([y, x], axis=1).dropna()
    d.columns = ["y", "x"]
    if d.shape[0] < 180 or d["x"].std(ddof=1) <= 1e-12:
        return {"error": "insufficient_or_constant", "n": int(d.shape[0])}
    X = sm.add_constant(d["x"].values)
    model = sm.OLS(d["y"].values, X).fit(cov_type="HAC", cov_kwds={"maxlags": horizon})
    return {
        "n": int(d.shape[0]),
        "coef": float(model.params[1]),
        "hac_t": float(model.tvalues[1]),
        "p_value": float(model.pvalues[1]),
        "r2": float(model.rsquared),
        "y_mean": float(d["y"].mean()),
        "x_mean": float(d["x"].mean()),
    }


def block_bootstrap_spearman(x: pd.Series, y: pd.Series, block: int, reps: int = BOOTSTRAP_B) -> dict:
    d = pd.concat([x, y], axis=1).dropna()
    d.columns = ["x", "y"]
    n = d.shape[0]
    if n < max(180, block * 10) or d["x"].std(ddof=1) <= 1e-12 or d["y"].std(ddof=1) <= 1e-12:
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
    if d.shape[0] < 180 or n1 < 20 or n0 < 20:
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
        decisions.append(
            {
                "label": row["label"],
                "p_value": float(row["p_value"]),
                "holm_threshold": float(threshold),
                "reject": reject,
                "coef": float(row.get("coef", np.nan)),
                "hac_t": float(row.get("hac_t", np.nan)),
            }
        )
    return {
        "alpha": alpha,
        "n_tests": m,
        "bonferroni_alpha": float(alpha / m) if m else None,
        "bonferroni_survivors": [r["label"] for r in valid if r["p_value"] <= alpha / m],
        "holm_decisions": decisions,
        "holm_survivors": [r["label"] for r in decisions if r["reject"]],
    }


def run_tests(df: pd.DataFrame) -> tuple[dict, list[dict]]:
    primary: dict = {}
    p_rows: list[dict] = []
    for asset in PRIMARY_ASSETS:
        primary[asset] = {}
        for horizon in HORIZONS:
            y = df[f"{asset}_fwd_log_rv_{horizon}d"]
            primary[asset][f"{horizon}d"] = {}
            for sig in PRIMARY_SIGNALS:
                x = df[f"{sig}_lag1"]
                ols = hac_ols(y, x, horizon=horizon)
                spearman = block_bootstrap_spearman(x, y, block=horizon)
                threshold = -0.03 if horizon == 1 else -0.05
                event = df[f"{asset}_fwd_cumret_{horizon}d"] <= threshold
                auc = roc_auc_with_ci(x, event)
                label = f"{asset}|{horizon}d|{sig}"
                out = {"hac_ols": ols, "spearman": spearman, "left_tail_auc": auc, "tail_threshold": threshold}
                primary[asset][f"{horizon}d"][sig] = out
                if "p_value" in ols:
                    p_rows.append(
                        {
                            "label": label,
                            "p_value": ols["p_value"],
                            "coef": ols["coef"],
                            "hac_t": ols["hac_t"],
                        }
                    )
    return primary, p_rows


def run_spillover_tests(df: pd.DataFrame) -> dict:
    spill: dict = {}
    for asset in SPILLOVER_ASSETS:
        if asset not in df.columns:
            continue
        spill[asset] = {}
        for horizon in HORIZONS:
            y_col = f"{asset}_fwd_log_rv_{horizon}d"
            if y_col not in df.columns:
                continue
            spill[asset][f"{horizon}d"] = {}
            for sig in PRIMARY_SIGNALS:
                spill[asset][f"{horizon}d"][sig] = {
                    "hac_ols": hac_ols(df[y_col], df[f"{sig}_lag1"], horizon=horizon),
                    "sample_note": "diagnostic only; ETF/equity proxy samples are shorter than ETH/BTC.",
                }
    return spill


def assess_verdict(primary: dict, mt: dict) -> dict:
    survivors = []
    raw_positive = []
    for asset, by_h in primary.items():
        for horizon, by_sig in by_h.items():
            for sig, res in by_sig.items():
                ols = res["hac_ols"]
                if "p_value" not in ols:
                    continue
                label = f"{asset}|{horizon}|{sig}"
                if ols["coef"] > 0 and ols["p_value"] < 0.05:
                    raw_positive.append(label)
    bonf = set(mt.get("bonferroni_survivors", []))
    for label in bonf:
        parts = label.split("|")
        if len(parts) != 3:
            continue
        asset, horizon, sig = parts
        coef = primary[asset][horizon][sig]["hac_ols"].get("coef")
        if coef is not None and coef > 0:
            survivors.append(label)

    if survivors:
        verdict = "MIXED_POSITIVE_DIAGNOSTIC"
        rationale = "At least one positive primary HAC coefficient survives Bonferroni, but economic robustness and AUC gates still need review."
    elif raw_positive:
        verdict = "WEAK_RAW_ONLY"
        rationale = "Some positive coefficients are raw-significant, but none survive the 12-test primary-family correction."
    else:
        verdict = "NULL"
        rationale = "No positive ETH/BTC t+1/t+5 RV coefficient survives, and there is no raw-significant positive primary edge to promote."
    return {"verdict": verdict, "positive_raw_p_lt_0_05": raw_positive, "positive_bonferroni_survivors": survivors, "rationale": rationale}


def make_plots(df: pd.DataFrame, primary: dict) -> None:
    plot_df = df.loc[df.index >= "2020-01-01"].copy()
    fig, ax1 = plt.subplots(figsize=(11, 5))
    ax1.plot(plot_df.index, plot_df["avg_gas_price_gwei"], color="tab:orange", lw=1, label="Avg gas price (gwei)")
    ax1.set_yscale("log")
    ax1.set_ylabel("Gas price (gwei, log)")
    ax2 = ax1.twinx()
    ax2.plot(plot_df.index, plot_df["dex_volume_usd"] / 1e9, color="tab:blue", lw=1, alpha=0.75, label="ETH DEX volume ($bn)")
    ax2.set_ylabel("DEX volume ($bn)")
    ax1.set_title("K1566 public blockspace inputs")
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels + labels2, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG1, dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=False, sharey=False)
    for ax, asset in zip(axes, PRIMARY_ASSETS):
        d = pd.concat([df["blockspace_pressure_lag1"], df[f"{asset}_fwd_log_rv_5d"]], axis=1).dropna()
        d.columns = ["pressure", "log_rv"]
        if d.shape[0] > 1500:
            d = d.sample(1500, random_state=SEED)
        ax.scatter(d["pressure"], d["log_rv"], s=8, alpha=0.25)
        if d.shape[0] > 20:
            m, b = np.polyfit(d["pressure"], d["log_rv"], 1)
            xs = np.linspace(d["pressure"].quantile(0.01), d["pressure"].quantile(0.99), 100)
            ax.plot(xs, m * xs + b, color="tab:red", lw=1.5)
        ax.set_title(f"{asset}: lagged pressure vs fwd 5d log-RV")
        ax.set_xlabel("Blockspace pressure lag1")
        ax.set_ylabel("Forward 5d log-RV")
    fig.tight_layout()
    fig.savefig(FIG2, dpi=160)
    plt.close(fig)

    labels = []
    vals = []
    for asset in PRIMARY_ASSETS:
        for horizon in HORIZONS:
            row = []
            for sig in PRIMARY_SIGNALS:
                row.append(primary[asset][f"{horizon}d"][sig]["hac_ols"].get("hac_t", np.nan))
            vals.append(row)
            labels.append(f"{asset} {horizon}d")
    arr = np.asarray(vals, dtype=float)
    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    im = ax.imshow(arr, cmap="RdBu_r", vmin=-4, vmax=4, aspect="auto")
    ax.set_xticks(np.arange(len(PRIMARY_SIGNALS)))
    ax.set_xticklabels(PRIMARY_SIGNALS, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels)
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            txt = "" if not np.isfinite(arr[i, j]) else f"{arr[i, j]:.2f}"
            ax.text(j, i, txt, ha="center", va="center", color="black", fontsize=9)
    ax.set_title("HAC t-stat: lagged blockspace signals predicting ETH/BTC forward log-RV")
    fig.colorbar(im, ax=ax, label="HAC t-stat")
    fig.tight_layout()
    fig.savefig(FIG3, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload public data instead of using cached snapshots")
    args = parser.parse_args()

    df, source_meta = build_feature_matrix(refresh=args.refresh)
    primary, p_rows = run_tests(df)
    mt = holm_bonferroni(p_rows)
    spillover = run_spillover_tests(df)
    verdict = assess_verdict(primary, mt)
    make_plots(df, primary)

    desc_cols = [
        "avg_gas_price_gwei",
        "gas_used",
        "dex_volume_usd",
        "gas_price_shock",
        "dex_volume_shock",
        "blockspace_pressure",
    ]
    signal_desc = {c: describe_series(df[c]) for c in desc_cols if c in df.columns}
    target_desc = {}
    for asset in [c for c in ALL_ASSETS if c in df.columns]:
        target_desc[asset] = {
            "price": describe_series(df[asset]),
            "ret": describe_series(df[f"{asset}_ret"]),
            **{f"fwd_rv_{h}d": describe_series(df[f"{asset}_fwd_rv_{h}d"]) for h in HORIZONS if f"{asset}_fwd_rv_{h}d" in df},
        }

    results = {
        "metadata": {
            "experiment_id": "K1566",
            "title": "DEX blockspace-pressure proxy as ETH/BTC short-RV signal",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed": SEED,
            "git_commit": git_rev(),
            "verdict": verdict["verdict"],
        },
        "data_sources": source_meta,
        "sample": {
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "n_calendar_rows": int(df.shape[0]),
            "primary_assets": PRIMARY_ASSETS,
            "spillover_assets_available": [a for a in SPILLOVER_ASSETS if a in df.columns],
        },
        "methodology": {
            "proxy_limit": "Etherscan free chart CSV gives average gas price, not a decomposition into base fee and priority fee/tip. The experiment therefore tests a blockspace-pressure proxy, not address-level mempool priority-fee replication.",
            "signal_construction": f"log daily innovations standardized by a {ROLL}-day rolling mean/std ending at t-1; tested predictors are signal.shift(1).",
            "forward_target": "Forward realized variance uses strictly close-to-close returns in [t+1, t+H].",
            "sample_cutoff": f"Rows after the last complete UTC date ({LAST_COMPLETE_UTC_DATE.isoformat()}) are dropped to avoid incomplete current-day crypto bars.",
            "hac_lag": "HAC maxlags equals forecast horizon H.",
            "spearman_ci": f"moving-block bootstrap with block=H, B={BOOTSTRAP_B}, seed={SEED}.",
            "auc_ci": "Hanley-McNeil normal approximation for fixed left-tail thresholds.",
            "primary_family": "ETH/BTC × {1d,5d} × {gas_price_shock,dex_volume_shock,blockspace_pressure} = 12 tests.",
            "success_gate": "Positive HAC coefficient must survive family correction; AUC and spillover tests are supporting diagnostics.",
        },
        "descriptive": {
            "signals": signal_desc,
            "targets": target_desc,
        },
        "primary_tests": primary,
        "spillover_diagnostics": spillover,
        "multiple_testing": mt,
        "verdict_assessment": verdict,
        "figures": [str(FIG1.relative_to(HERE)), str(FIG2.relative_to(HERE)), str(FIG3.relative_to(HERE))],
    }
    OUT_JSON.write_text(json.dumps(finite_or_none(results), indent=2, ensure_ascii=False))
    print(json.dumps({"verdict": verdict["verdict"], "assessment": verdict, "results": str(OUT_JSON)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
