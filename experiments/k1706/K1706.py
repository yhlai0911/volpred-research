#!/usr/bin/env python3
"""K1706: Tick Size Pilot pre-spread volatility heterogeneity.

The design is frozen in README.md.  The large FINRA Appendix B.I gzip is not
committed; pass it with --raw-bi.  All committed data are deterministic,
aggregated derivatives with SHA256 provenance.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import subprocess
import tarfile
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from volpred.ops.diagnostics import warn


SEED = 42
N_PERM = 999
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / "K1706_results.json"

ASSIGNMENT_URL = (
    "https://www.finra.org/sites/default/files/"
    "Tick_Pilot_Test_Group_Assignments.txt"
)
BI_URL = (
    "https://tsp.finra.org/finra_org/ticksizepilot/"
    "TSPAppendixBCStatistics/BI/201609/v1/"
    "FINRA_CHX_MKTQUALITYSTATS_201609.dat.gzip"
)
OUTCOMES = ["rv5_bps2", "range_bps", "log_dollar_volume", "amihud_1e9"]
STRATA = ["narrow", "wide"]
MONTHS = ["2016-06", "2016-07", "2016-08", "2016-11", "2016-12", "2017-01", "2017-02"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with tmp.open(encoding="utf-8") as fh:
        json.load(fh)
    os.replace(tmp, path)


def deterministic_gzip_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = df.to_csv(index=False, lineterminator="\n").encode("utf-8")
    with path.open("wb") as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0, compresslevel=9) as gz:
            gz.write(raw)


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "volpred-k1706/1.0 research"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def load_assignments() -> pd.DataFrame:
    raw_path = DATA_DIR / "assignments_official.txt"
    if not raw_path.exists():
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(download_bytes(ASSIGNMENT_URL))
    frame = pd.read_csv(raw_path, sep="|")
    frame = frame.rename(
        columns={
            "Ticker_Symbol": "symbol",
            "Tick_Size_Pilot_Program_Group": "group",
            "Listing_Exchange": "listing_exchange",
        }
    )
    frame = frame[["symbol", "group", "listing_exchange"]].copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip()
    frame["group"] = frame["group"].astype(str).str.strip()
    frame = frame[frame["group"].isin(["C", "G1", "G2", "G3"])]
    frame = frame.drop_duplicates("symbol", keep="last").sort_values("symbol")
    # Yahoo uses dashes for class shares where SIP/FINRA uses a period.
    frame["yahoo_symbol"] = frame["symbol"].str.replace(".", "-", regex=False)
    frame.to_csv(DATA_DIR / "assignments_normalized.csv", index=False, lineterminator="\n")
    return frame.reset_index(drop=True)


def aggregate_pre_spread(raw_bi: Path) -> tuple[pd.DataFrame, dict]:
    """Aggregate official September B.I WA_NBBO_Spd using SEC filters."""
    out_path = DATA_DIR / "pre_spread_official.csv"
    audit_path = DATA_DIR / "pre_spread_audit.json"
    if out_path.exists() and audit_path.exists():
        return pd.read_csv(out_path), json.loads(audit_path.read_text(encoding="utf-8"))

    weighted_spread: defaultdict[str, float] = defaultdict(float)
    weights: defaultdict[str, float] = defaultdict(float)
    row_counts: defaultdict[str, int] = defaultdict(int)
    dates: defaultdict[str, set[str]] = defaultdict(set)
    total_data_rows = 0
    accepted_rows = 0

    with gzip.open(raw_bi, "rb") as fh:
        for raw in fh:
            if not raw.startswith(b"D|"):
                continue
            total_data_rows += 1
            p = raw.rstrip(b"\r\n").split(b"|")
            if len(p) < 45:
                continue
            try:
                order_type = int(p[6])
                shares = float(p[17])
                spread = float(p[43])
            except (ValueError, TypeError) as exc:
                warn(
                    "k1706_pre_spread_parse",
                    "skipping malformed FINRA Appendix B.I row",
                    err=str(exc),
                    data_row=total_data_rows,
                    raw_head=raw[:160].decode("utf-8", errors="replace"),
                )
                continue
            if order_type > 14 or p[8] == b"Y" or p[10] == b"Y":
                continue
            if shares <= 0 or not math.isfinite(spread) or spread < 0:
                continue
            symbol = p[4].decode("utf-8", errors="strict").strip()
            date = p[1].decode("ascii", errors="strict")
            weighted_spread[symbol] += spread * shares
            weights[symbol] += shares
            row_counts[symbol] += 1
            dates[symbol].add(date)
            accepted_rows += 1

    records = []
    for symbol in sorted(weights):
        records.append(
            {
                "symbol": symbol,
                "pre_spread_usd": weighted_spread[symbol] / weights[symbol],
                "weight_order_shares": weights[symbol],
                "source_rows": row_counts[symbol],
                "source_dates": len(dates[symbol]),
            }
        )
    result = pd.DataFrame(records)
    result.to_csv(out_path, index=False, float_format="%.12g", lineterminator="\n")
    audit = {
        "source_url": BI_URL,
        "source_file": raw_bi.name,
        "source_sha256": sha256_file(raw_bi),
        "source_bytes": raw_bi.stat().st_size,
        "source_month": "2016-09",
        "total_data_rows": total_data_rows,
        "accepted_rows": accepted_rows,
        "symbols": len(result),
        "filters": [
            "Order_Type <= 14",
            "Spcl_Hndlg_Ind != Y",
            "Multiday_Order != Y",
            "Order_Shares_Ct > 0",
            "finite non-negative WA_NBBO_Spd",
        ],
        "aggregation": "Order_Shares_Ct weighted WA_NBBO_Spd by Symbol",
    }
    write_json(audit_path, audit)
    return result, audit


def fetch_ohlcv(price_repo: Path, symbols: list[str], refresh: bool) -> tuple[pd.DataFrame, dict]:
    cache = DATA_DIR / "ohlcv_daily.csv.gz"
    audit_path = DATA_DIR / "ohlcv_audit.json"
    if cache.exists() and audit_path.exists() and not refresh:
        return pd.read_csv(cache, parse_dates=["date"]), json.loads(audit_path.read_text())
    if not (price_repo / ".git").exists():
        raise FileNotFoundError(f"not a pystock-data git checkout: {price_repo}")
    commit = subprocess.check_output(
        ["git", "-C", str(price_repo), "rev-parse", "HEAD"], text=True
    ).strip()
    wanted = set(symbols)
    frames: list[pd.DataFrame] = []
    skipped_archives: list[str] = []
    archive_hash = hashlib.sha256()
    archives: list[Path] = []
    for year in (2016, 2017):
        for archive in sorted((price_repo / str(year)).glob("*.tar.gz")):
            stamp = archive.name[:8]
            if "20160520" <= stamp <= "20170301":
                archives.append(archive)
    for index, archive in enumerate(archives, start=1):
        if index % 40 == 0 or index == 1:
            print(f"[ohlcv archive] {index}/{len(archives)} {archive.name}", flush=True)
        digest = sha256_file(archive)
        archive_hash.update(str(archive.relative_to(price_repo)).encode())
        archive_hash.update(digest.encode())
        with tarfile.open(archive, "r:gz") as tf:
            try:
                member = tf.extractfile("prices.csv")
            except KeyError:
                member = None
            if member is None:
                continue
            try:
                daily = pd.read_csv(
                    member,
                    usecols=[
                        "symbol", "date", "open", "high", "low", "close", "volume", "adj_close"
                    ],
                )
            except (pd.errors.EmptyDataError, ValueError) as exc:
                warn(
                    "k1706_ohlcv_archive_parse",
                    "skipping unusable prices.csv archive",
                    err=str(exc),
                    archive=str(archive.relative_to(price_repo)),
                )
                skipped_archives.append(str(archive.relative_to(price_repo)))
                continue
        daily = daily[daily["symbol"].isin(wanted)]
        if not daily.empty:
            frames.append(daily)

    if not frames:
        raise RuntimeError("pystock-data archives returned no usable ticker histories")
    result = pd.concat(frames, ignore_index=True)
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "adj_close"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=["date", "symbol"])
    result = result[(result["date"] >= "2016-05-20") & (result["date"] < "2017-03-01")]
    result = result.sort_values(["symbol", "date"]).drop_duplicates(
        ["symbol", "date"], keep="last"
    )
    result = result.rename(columns={"symbol": "yahoo_symbol"})
    deterministic_gzip_csv(result, cache)
    returned = set(result["yahoo_symbol"].unique())
    audit = {
        "source": "eliangcs/pystock-data daily archived Yahoo Finance OHLCV",
        "source_repo": "https://github.com/eliangcs/pystock-data",
        "source_repo_commit": commit,
        "source_license": "CC BY-SA 4.0",
        "adjustment": "adj_close used for returns; raw OHLC and volume used for range/dollar volume",
        "requested_start": "2016-05-20",
        "requested_end_exclusive": "2017-03-01",
        "requested_symbols": len(symbols),
        "returned_symbols": int(result["yahoo_symbol"].nunique()),
        "rows": len(result),
        "archives": len(archives),
        "skipped_empty_or_invalid_archives": skipped_archives,
        "archive_set_sha256": archive_hash.hexdigest(),
        "missing_symbols": sorted(wanted - returned),
        "cache_sha256": sha256_file(cache),
    }
    write_json(audit_path, audit)
    return result, audit

    # Unreachable guard kept intentionally absent: every failure is audited above.


def holm_adjust(pvalues: list[float]) -> list[float]:
    p = np.asarray(pvalues, dtype=float)
    order = np.argsort(p)
    adjusted = np.empty(len(p), dtype=float)
    running = 0.0
    m = len(p)
    for rank, idx in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[idx]))
        adjusted[idx] = running
    return adjusted.tolist()


def residualize(values: np.ndarray, symbols: pd.Series, dates: pd.Series) -> np.ndarray:
    """Absorb stock and date effects exactly for an unbalanced panel."""
    out = np.asarray(values, dtype=float).copy()
    symbol_keys = symbols.to_numpy()
    date_keys = dates.to_numpy()
    for _ in range(1_000):
        previous = out.copy()
        out -= pd.DataFrame(out).groupby(symbol_keys, sort=False).transform("mean").to_numpy()
        out -= pd.DataFrame(out).groupby(date_keys, sort=False).transform("mean").to_numpy()
        if np.max(np.abs(out - previous)) < 1e-12:
            return out
    raise RuntimeError("two-way FE alternating projection did not converge")


def cluster_fe_ols(data: pd.DataFrame, outcome: str, regressors: list[str]) -> dict:
    cols = [outcome, "symbol", "date", *regressors]
    d = data[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    y = d[[outcome]].to_numpy(float)
    x = d[regressors].to_numpy(float)
    yw = residualize(y, d["symbol"], d["date"]).ravel()
    xw = residualize(x, d["symbol"], d["date"])
    keep = np.isfinite(yw) & np.isfinite(xw).all(axis=1)
    yw, xw, d = yw[keep], xw[keep], d.loc[keep]
    xtx_inv = np.linalg.pinv(xw.T @ xw)
    beta = xtx_inv @ (xw.T @ yw)
    resid = yw - xw @ beta
    groups = d["symbol"].astype(str).to_numpy()
    meat = np.zeros((len(regressors), len(regressors)))
    unique = np.unique(groups)
    for group in unique:
        mask = groups == group
        score = xw[mask].T @ resid[mask]
        meat += np.outer(score, score)
    n, k, g = len(yw), len(regressors), len(unique)
    correction = (g / (g - 1)) * ((n - 1) / max(n - k, 1)) if g > 1 else np.nan
    cov = correction * xtx_inv @ meat @ xtx_inv
    se = np.sqrt(np.maximum(np.diag(cov), 0))
    tstat = beta / se
    pval = 2 * stats.t.sf(np.abs(tstat), df=max(g - 1, 1))
    return {
        "n_obs": n,
        "n_stocks": g,
        "coefficients": {
            name: {
                "estimate": float(beta[i]),
                "cluster_se": float(se[i]),
                "t": float(tstat[i]),
                "p": float(pval[i]),
            }
            for i, name in enumerate(regressors)
        },
    }


def did_from_delta(delta: np.ndarray, treated: np.ndarray) -> float:
    return float(delta[treated].mean() - delta[~treated].mean())


def ri_for_outcome(panel: pd.DataFrame, outcome: str, rng: np.random.Generator) -> dict:
    by_stratum: dict[str, dict] = {}
    draws: dict[str, np.ndarray] = {}
    observed: dict[str, float] = {}
    for stratum in STRATA:
        d = panel[panel["spread_stratum"] == stratum]
        stock = d.groupby(["symbol", "treated", "post"], observed=True)[outcome].mean().unstack("post")
        stock = stock.dropna(subset=[False, True]).reset_index()
        delta = (stock[True] - stock[False]).to_numpy(float)
        treated = stock["treated"].astype(bool).to_numpy()
        obs = did_from_delta(delta, treated)
        sim = np.empty(N_PERM)
        for i in range(N_PERM):
            sim[i] = did_from_delta(delta, rng.permutation(treated))
        p = (1 + np.sum(np.abs(sim) >= abs(obs))) / (N_PERM + 1)
        observed[stratum] = obs
        draws[stratum] = sim
        by_stratum[stratum] = {
            "estimate_stock_delta": obs,
            "ri_p": float(p),
            "n_stocks": len(stock),
            "n_treated": int(treated.sum()),
            "n_control": int((~treated).sum()),
        }
    contrast = observed["narrow"] - observed["wide"]
    contrast_draws = draws["narrow"] - draws["wide"]
    contrast_p = (1 + np.sum(np.abs(contrast_draws) >= abs(contrast))) / (N_PERM + 1)
    return {
        "strata": by_stratum,
        "heterogeneity": {
            "narrow_minus_wide": float(contrast),
            "ri_p": float(contrast_p),
        },
    }


def prepare_panel(ohlcv: pd.DataFrame, design: pd.DataFrame) -> pd.DataFrame:
    panel = ohlcv.merge(
        design[["symbol", "yahoo_symbol", "group", "pre_spread_usd", "spread_stratum"]],
        on="yahoo_symbol",
        how="inner",
        validate="many_to_one",
    )
    panel = panel.sort_values(["symbol", "date"])
    panel["raw_log_return"] = panel.groupby("symbol", observed=True)["close"].transform(
        lambda s: np.log(s).diff()
    )
    panel["adjusted_log_return"] = panel.groupby("symbol", observed=True)["adj_close"].transform(
        lambda s: np.log(s).diff()
    )
    adjustment_factor = panel["adj_close"] / panel["close"]
    factor_change = adjustment_factor.groupby(panel["symbol"], observed=True).transform(
        lambda s: np.log(s).diff().abs()
    )
    panel["corporate_action_boundary"] = factor_change > 0.2
    panel["log_return"] = panel["adjusted_log_return"]
    boundary = panel["corporate_action_boundary"].fillna(False)
    choose_raw = boundary & (
        panel["raw_log_return"].abs() < panel["adjusted_log_return"].abs()
    )
    panel.loc[choose_raw, "log_return"] = panel.loc[choose_raw, "raw_log_return"]
    panel["analysis_period"] = np.select(
        [
            panel["date"].between("2016-06-01", "2016-09-30"),
            panel["date"].between("2016-11-01", "2017-02-28"),
        ],
        ["pre", "post"],
        default="excluded",
    )
    panel["rv5_bps2"] = panel.groupby(
        ["symbol", "analysis_period"], observed=True
    )["log_return"].transform(
        lambda s: s.pow(2).rolling(5, min_periods=5).sum() * 10_000
    )
    panel["range_bps"] = (panel["high"] - panel["low"]) / panel["close"] * 10_000
    dollar_volume = panel["close"] * panel["volume"]
    panel["log_dollar_volume"] = np.log(dollar_volume.where(dollar_volume > 0))
    panel["amihud_1e9"] = panel["log_return"].abs() / dollar_volume.where(dollar_volume > 0) * 1e9
    panel["month"] = panel["date"].dt.strftime("%Y-%m")
    panel = panel[panel["month"].isin(["2016-06", "2016-07", "2016-08", "2016-09", "2016-11", "2016-12", "2017-01", "2017-02"])].copy()
    panel["post"] = panel["date"] >= pd.Timestamp("2016-11-01")
    panel["treated"] = panel["group"].ne("C")
    panel["raw_signal"] = panel["treated"].astype(float)
    # Governance hard rule: treatment used at t is known and lagged from t-1.
    panel["signal"] = panel.groupby("symbol", observed=True)["raw_signal"].shift(1)
    panel["did"] = panel["signal"] * panel["post"].astype(float)
    stable = panel.dropna(subset=["signal"])
    assert np.array_equal(stable["signal"].to_numpy(), stable["raw_signal"].to_numpy())

    counts = panel.groupby(["symbol", "post"], observed=True)["close"].count().unstack("post")
    valid_symbols = counts.dropna().query("`False` >= 20 and `True` >= 20").index
    return panel[panel["symbol"].isin(valid_symbols) & panel["signal"].notna()].copy()


def event_study(panel: pd.DataFrame, outcome: str, stratum: str) -> dict:
    d = panel[panel["spread_stratum"] == stratum].copy()
    regressors = []
    for month in MONTHS:
        name = f"event_{month}"
        d[name] = d["signal"] * d["month"].eq(month).astype(float)
        regressors.append(name)
    return cluster_fe_ols(d, outcome, regressors)


def make_figures(main: list[dict], events: dict) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    for ax, stratum in zip(axes, STRATA):
        rows = [r for r in main if r["stratum"] == stratum]
        y = np.arange(len(rows))
        est = np.array([r["fe_estimate"] for r in rows])
        se = np.array([r["fe_cluster_se"] for r in rows])
        ax.errorbar(est, y, xerr=1.96 * se, fmt="o", capsize=3, color="#1769aa")
        ax.axvline(0, color="black", lw=0.8)
        ax.set_yticks(y, [r["outcome"] for r in rows])
        ax.set_title(f"{stratum}: pooled test − control")
        ax.set_xlabel("FE-DiD estimate (95% cluster CI)")
        ax.grid(axis="x", alpha=0.2)
    fig.suptitle("K1706 Tick Size Pilot: fixed pre-spread strata")
    fig.savefig(FIG_DIR / "k1706_did_forest.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(2, 4, figsize=(18, 8), constrained_layout=True)
    for ax, (stratum, outcome) in zip(axes.ravel(), [(s, o) for s in STRATA for o in OUTCOMES]):
        coefs = events[stratum][outcome]["coefficients"]
        labels = MONTHS
        est = np.array([coefs[f"event_{m}"]["estimate"] for m in labels])
        se = np.array([coefs[f"event_{m}"]["cluster_se"] for m in labels])
        x = np.arange(len(labels))
        ax.errorbar(x, est, yerr=1.96 * se, fmt="o-", capsize=2)
        ax.axhline(0, color="black", lw=0.8)
        ax.axvline(2.5, color="#aa3333", ls="--", lw=0.8)
        ax.set_xticks(x, [m[2:] for m in labels], rotation=45)
        ax.set_title(f"{stratum} · {outcome}")
        ax.grid(alpha=0.2)
    fig.suptitle("K1706 event study (September 2016 reference; October excluded)")
    fig.savefig(FIG_DIR / "k1706_event_study.png", dpi=180)
    plt.close(fig)


def analyze(panel: pd.DataFrame, spread_audit: dict, ohlcv_audit: dict) -> dict:
    rng = np.random.default_rng(SEED)
    main_rows: list[dict] = []
    ri_results: dict[str, dict] = {}
    heterogeneity: list[dict] = []
    for outcome in OUTCOMES:
        ri = ri_for_outcome(panel, outcome, rng)
        ri_results[outcome] = ri
        heterogeneity.append({"outcome": outcome, **ri["heterogeneity"]})
        for stratum in STRATA:
            fe = cluster_fe_ols(panel[panel["spread_stratum"] == stratum], outcome, ["did"])
            c = fe["coefficients"]["did"]
            main_rows.append(
                {
                    "outcome": outcome,
                    "stratum": stratum,
                    "fe_estimate": c["estimate"],
                    "fe_cluster_se": c["cluster_se"],
                    "fe_p": c["p"],
                    "ri_estimate_stock_delta": ri["strata"][stratum]["estimate_stock_delta"],
                    "ri_p": ri["strata"][stratum]["ri_p"],
                    "n_obs": fe["n_obs"],
                    "n_stocks": fe["n_stocks"],
                    "n_treated": ri["strata"][stratum]["n_treated"],
                    "n_control": ri["strata"][stratum]["n_control"],
                }
            )
    adjusted = holm_adjust([r["ri_p"] for r in main_rows])
    for row, p in zip(main_rows, adjusted):
        row["ri_p_holm_8"] = p
    het_adjusted = holm_adjust([r["ri_p"] for r in heterogeneity])
    for row, p in zip(heterogeneity, het_adjusted):
        row["ri_p_holm_4"] = p

    placebo_rows = []
    pre = panel[~panel["post"]].copy()
    pre["placebo_post"] = pre["date"] >= pd.Timestamp("2016-08-01")
    pre["placebo_did"] = pre["signal"] * pre["placebo_post"].astype(float)
    for outcome in OUTCOMES:
        for stratum in STRATA:
            fe = cluster_fe_ols(pre[pre["spread_stratum"] == stratum], outcome, ["placebo_did"])
            c = fe["coefficients"]["placebo_did"]
            placebo_rows.append(
                {
                    "outcome": outcome,
                    "stratum": stratum,
                    "estimate": c["estimate"],
                    "cluster_se": c["cluster_se"],
                    "p": c["p"],
                    "n_obs": fe["n_obs"],
                    "n_stocks": fe["n_stocks"],
                }
            )
    placebo_adjusted = holm_adjust([r["p"] for r in placebo_rows])
    for row, p in zip(placebo_rows, placebo_adjusted):
        row["p_holm_8"] = p

    events = {s: {o: event_study(panel, o, s) for o in OUTCOMES} for s in STRATA}
    make_figures(main_rows, events)

    sample = (
        panel[["symbol", "group", "spread_stratum", "pre_spread_usd"]]
        .drop_duplicates()
        .groupby(["spread_stratum", "group"], observed=True)
        .agg(stocks=("symbol", "count"), mean_pre_spread=("pre_spread_usd", "mean"))
        .reset_index()
        .to_dict("records")
    )
    confirmatory = []
    for outcome in OUTCOMES:
        main_sig = any(
            r["outcome"] == outcome and r["ri_p_holm_8"] < 0.05 for r in main_rows
        )
        het_sig = next(r for r in heterogeneity if r["outcome"] == outcome)["ri_p_holm_4"] < 0.05
        placebo_ok = all(
            r["p_holm_8"] >= 0.05 for r in placebo_rows if r["outcome"] == outcome
        )
        if main_sig and het_sig and placebo_ok:
            confirmatory.append(outcome)

    return {
        "experiment_id": "K1706",
        "analysis_date": "2026-07-16",
        "seed": SEED,
        "randomization_permutations": N_PERM,
        "design_status": "FROZEN_BRIEF",
        "empirical_status": "CONFIRMATORY" if confirmatory else "NULL_OR_EXPLORATORY",
        "confirmatory_outcomes": confirmatory,
        "data": {
            "official_assignment_url": ASSIGNMENT_URL,
            "official_bi": spread_audit,
            "ohlcv": ohlcv_audit,
            "pre_window": ["2016-06-01", "2016-09-30"],
            "post_window": ["2016-11-01", "2017-02-28"],
            "october_excluded": True,
            "panel_rows": len(panel),
            "panel_stocks": int(panel["symbol"].nunique()),
            "panel_start": panel["date"].min().strftime("%Y-%m-%d"),
            "panel_end": panel["date"].max().strftime("%Y-%m-%d"),
            "rv5_resets_at_pre_post_boundaries": True,
        },
        "lookahead_audit": {
            "explicit_signal_shift_1": True,
            "signal_expression": "panel.groupby('symbol')['raw_signal'].shift(1)",
            "rolling_rv_direction": (
                "backward-looking t-4 through t within each frozen pre/post period"
            ),
            "same_day_signal_times_outcome": False,
            "corporate_action_boundary_rule": (
                "if abs(diff(log(adj_close/close))) > 0.2, use the smaller-absolute "
                "of raw and adjusted log returns"
            ),
            "corporate_action_boundary_rows": int(panel["corporate_action_boundary"].sum()),
        },
        "method_audit": {
            "fixed_effects": (
                "stock and date effects absorbed by alternating projections to 1e-12 tolerance"
            ),
            "cluster_covariance": "stock-clustered finite-sample corrected sandwich",
        },
        "fixed_strata": {
            "narrow": "pre_spread_usd < 0.10",
            "wide": "pre_spread_usd > 0.15",
            "middle_excluded": "0.10 <= pre_spread_usd <= 0.15",
        },
        "sample_balance": sample,
        "primary_did": main_rows,
        "heterogeneity_tests": heterogeneity,
        "placebo_pre_period": placebo_rows,
        "event_study": events,
        "limitations": [
            "Daily OHLCV proxies from the frozen pystock-data/Yahoo archive are not TAQ/CRSP/MIDAS intraday measures.",
            "rv5_bps2 is a backward five-day corporate-action-clean daily realized-variance proxy.",
            "RI preserves treatment counts within frozen spread strata but cannot reconstruct every official selection stratum.",
            "Survivorship/data-availability selection may arise because some 2016 pilot tickers are unavailable from Yahoo in 2026.",
            "Appendix B.I pre-spread is FINRA/CHX-reported order data, not a full consolidated TAQ quote spread.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-bi", type=Path, required=True, help="official 2016-09 Appendix B.I gzip")
    parser.add_argument("--price-repo", type=Path, required=True, help="eliangcs/pystock-data checkout")
    parser.add_argument("--refresh-ohlcv", action="store_true")
    args = parser.parse_args()
    if not args.raw_bi.exists():
        raise FileNotFoundError(args.raw_bi)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/6] official assignments", flush=True)
    assignments = load_assignments()
    print("[2/6] aggregate official pre-spread", flush=True)
    spreads, spread_audit = aggregate_pre_spread(args.raw_bi)
    design = assignments.merge(spreads, on="symbol", how="inner", validate="one_to_one")
    design["spread_stratum"] = np.select(
        [design["pre_spread_usd"] < 0.10, design["pre_spread_usd"] > 0.15],
        ["narrow", "wide"],
        default="middle_excluded",
    )
    design.to_csv(DATA_DIR / "design_with_fixed_strata.csv", index=False, float_format="%.12g", lineterminator="\n")
    eligible = design[design["spread_stratum"].isin(STRATA)].copy()
    print(eligible.groupby(["spread_stratum", "group"]).size(), flush=True)

    print("[3/6] historical OHLCV", flush=True)
    ohlcv, ohlcv_audit = fetch_ohlcv(
        args.price_repo, sorted(eligible["yahoo_symbol"].unique()), args.refresh_ohlcv
    )
    print("[4/6] panel diagnostics", flush=True)
    panel = prepare_panel(ohlcv, eligible)
    panel_cols = [
        "date", "symbol", "group", "spread_stratum", "pre_spread_usd", "post",
        "signal", *OUTCOMES,
    ]
    deterministic_gzip_csv(panel[panel_cols].sort_values(["symbol", "date"]), DATA_DIR / "analysis_panel.csv.gz")
    print(panel.groupby(["spread_stratum", "group"])["symbol"].nunique(), flush=True)

    print("[5/6] FE-DiD, RI, placebo, Holm, event study", flush=True)
    results = analyze(panel, spread_audit, ohlcv_audit)
    source_manifest = {
        "assignment_url": ASSIGNMENT_URL,
        "assignment_sha256": sha256_file(DATA_DIR / "assignments_official.txt"),
        "bi_url": BI_URL,
        "bi_raw_sha256": spread_audit["source_sha256"],
        "pre_spread_csv_sha256": sha256_file(DATA_DIR / "pre_spread_official.csv"),
        "ohlcv_cache_sha256": sha256_file(DATA_DIR / "ohlcv_daily.csv.gz"),
        "analysis_panel_sha256": sha256_file(DATA_DIR / "analysis_panel.csv.gz"),
        "script_sha256_before_results_write": sha256_file(Path(__file__)),
    }
    write_json(DATA_DIR / "source_manifest.json", source_manifest)
    results["source_manifest"] = source_manifest
    write_json(RESULTS_PATH, results)
    print("[6/6] complete", flush=True)
    print(json.dumps({"status": results["empirical_status"], "stocks": results["data"]["panel_stocks"]}, indent=2))


if __name__ == "__main__":
    main()
