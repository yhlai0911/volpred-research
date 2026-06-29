#!/usr/bin/env python3
"""K1568: Federal Register rule-flow proxy and compliance-exposed ETF volatility.

This is a public-proxy screen. It does not observe true firm-level compliance
costs, staff hours, legal spend, paperwork burden, or RegData industry exposure.
It asks whether a free Federal Register rule/proposed-rule flow proxy has
incremental lead information for RV, downside semivariance, or volume shocks in
small-cap and regulated-sector ETF proxies.

Lookahead policy:
- Federal Register documents are assigned to their publication date's next US
  ETF trading date, then all tested signals are signal.shift(1).
- Rolling z-score baselines end at t-1.
- Forward targets use strictly [t+1, t+H].
- yfinance adjusted close/volume are end-of-day public-market data; the one-day
  signal lag avoids same-day publication/close ambiguity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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
OUT_JSON = HERE / "k1568_results.json"
OUT_DATA = HERE / "k1568_analysis_dataset.csv"
FIG1 = HERE / "fig1_federal_register_rule_flow.png"
FIG2 = HERE / "fig2_hac_tstat_rv_heatmap.png"
FIG3 = HERE / "fig3_combined_signal_vs_kre_downside.png"

START = "2012-01-01"
LAST_COMPLETE_UTC_DATE = datetime.now(timezone.utc).date() - timedelta(days=1)
END = (LAST_COMPLETE_UTC_DATE + timedelta(days=1)).isoformat()

ROLL_Z = 252
RV_WINDOW = 21
VOL_BASE_WINDOW = 63
BOOTSTRAP_B = 1000

TARGETS = ["IJR", "IWM", "KRE", "KBE", "XLF", "XLV", "XLI", "XRT"]
CONTROLS = ["SPY", "^VIX"]
PRICE_TICKERS = TARGETS + CONTROLS
FEDREG_TYPE_CODES = {"RULE": "rule", "PRORULE": "proposed_rule"}
SIGNALS = ["rule_flow_stress", "proposed_rule_flow_stress", "combined_reg_flow_stress"]
HORIZONS = [5, 21]
OUTCOMES = ["log_rv", "log_downside_var", "volume_shock"]


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


def rolling_z(s: pd.Series, window: int = ROLL_Z, min_periods: int | None = None) -> pd.Series:
    if min_periods is None:
        min_periods = max(30, window // 4)
    mu = s.rolling(window, min_periods=min_periods).mean().shift(1)
    sd = s.rolling(window, min_periods=min_periods).std(ddof=1).shift(1)
    return ((s - mu) / sd).replace([np.inf, -np.inf], np.nan)


def fetch_ohlcv(refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame, SourceInfo]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    close_path = DATA_DIR / "yfinance_close.csv"
    volume_path = DATA_DIR / "yfinance_volume.csv"
    if close_path.exists() and volume_path.exists() and not refresh:
        close = pd.read_csv(close_path, index_col=0, parse_dates=True)
        volume = pd.read_csv(volume_path, index_col=0, parse_dates=True)
        return close, volume, SourceInfo(close_path, "yfinance adjusted OHLCV cache", False)

    raw = yf.download(
        PRICE_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("Expected yfinance multi-ticker OHLCV response")
    close = raw["Close"].copy()
    volume = raw["Volume"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    volume.index = pd.to_datetime(volume.index).tz_localize(None).normalize()
    close = close.sort_index()
    volume = volume.sort_index()
    missing = [t for t in PRICE_TICKERS if t not in close.columns or close[t].dropna().shape[0] < 500]
    if missing:
        raise RuntimeError(f"missing required yfinance data: {missing}")
    close = close[PRICE_TICKERS]
    volume = volume[[t for t in TARGETS + ["SPY"] if t in volume.columns]]
    close.to_csv(close_path)
    volume.to_csv(volume_path)
    return close, volume, SourceInfo(close_path, f"yfinance adjusted OHLCV {START} to {END}", True)


def fetch_federal_register_docs(refresh: bool) -> tuple[pd.DataFrame, SourceInfo]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "federal_register_rule_prorule_documents.csv"
    url = "https://www.federalregister.gov/api/v1/documents.json"
    if path.exists() and not refresh:
        docs = pd.read_csv(path, parse_dates=["publication_date"])
        return docs, SourceInfo(path, "Federal Register API documents cache", False)

    rows: list[dict] = []
    session = requests.Session()
    headers = {"User-Agent": "volpred-k1568/1.0 (research; contact via project owner)"}
    start_year = pd.Timestamp(START).year
    end_year = LAST_COMPLETE_UTC_DATE.year
    fields = ["publication_date", "type", "document_number", "title", "agencies"]
    for year in range(start_year, end_year + 1):
        year_start = date(year, 1, 1)
        year_end = min(date(year, 12, 31), LAST_COMPLETE_UTC_DATE)
        if year_start > LAST_COMPLETE_UTC_DATE:
            break
        for type_code, type_label in FEDREG_TYPE_CODES.items():
            params: dict[str, object] = {
                "per_page": 1000,
                "conditions[publication_date][gte]": year_start.isoformat(),
                "conditions[publication_date][lte]": year_end.isoformat(),
                "conditions[type][]": type_code,
                "fields[]": fields,
            }
            next_url: str | None = url
            while next_url:
                resp = session.get(next_url, params=params if next_url == url else None, headers=headers, timeout=60)
                resp.raise_for_status()
                payload = resp.json()
                for item in payload.get("results", []):
                    agencies = item.get("agencies") or []
                    rows.append(
                        {
                            "publication_date": item.get("publication_date"),
                            "type_code": type_code,
                            "type_label": type_label,
                            "api_type": item.get("type"),
                            "document_number": item.get("document_number"),
                            "title": item.get("title"),
                            "agency_slugs": "|".join(
                                sorted(str(a.get("slug", "")) for a in agencies if isinstance(a, dict))
                            ),
                        }
                    )
                next_url = payload.get("next_page_url")
                params = {}
                time.sleep(0.04)

    docs = pd.DataFrame(rows)
    if docs.empty:
        raise RuntimeError("Federal Register API returned no RULE/PRORULE rows")
    docs["publication_date"] = pd.to_datetime(docs["publication_date"]).dt.tz_localize(None).dt.normalize()
    docs = docs.sort_values(["publication_date", "type_code", "document_number"]).drop_duplicates(
        ["publication_date", "type_code", "document_number"]
    )
    docs.to_csv(path, index=False)
    return docs, SourceInfo(path, "https://www.federalregister.gov/api/v1/documents.json", True)


def align_fedreg_counts_to_trading_days(docs: pd.DataFrame, trading_index: pd.DatetimeIndex) -> pd.DataFrame:
    trading_index = pd.DatetimeIndex(trading_index).sort_values()
    out = pd.DataFrame(0.0, index=trading_index, columns=["rule_count", "proposed_rule_count"])
    if docs.empty:
        return out
    for row in docs.itertuples(index=False):
        pub_date = pd.Timestamp(row.publication_date).normalize()
        pos = trading_index.searchsorted(pub_date, side="left")
        if pos >= len(trading_index):
            continue
        col = "rule_count" if row.type_label == "rule" else "proposed_rule_count"
        out.iat[pos, out.columns.get_loc(col)] += 1.0
    out["combined_rule_count"] = out["rule_count"] + out["proposed_rule_count"]
    return out


def build_regulatory_signals(docs: pd.DataFrame, trading_index: pd.DatetimeIndex) -> pd.DataFrame:
    counts = align_fedreg_counts_to_trading_days(docs, trading_index)
    out = counts.copy()
    for prefix, count_col in [
        ("rule", "rule_count"),
        ("proposed_rule", "proposed_rule_count"),
        ("combined_reg", "combined_rule_count"),
    ]:
        out[f"{prefix}_count_5d"] = out[count_col].rolling(5, min_periods=1).sum()
        out[f"{prefix}_count_21d"] = out[count_col].rolling(21, min_periods=5).sum()
        out[f"{prefix}_count_63d"] = out[count_col].rolling(63, min_periods=21).sum()

    out["rule_flow_stress"] = pd.concat(
        [
            rolling_z(np.log1p(out["rule_count_5d"]), window=ROLL_Z),
            rolling_z(np.log1p(out["rule_count_21d"]), window=ROLL_Z),
        ],
        axis=1,
    ).mean(axis=1, skipna=False)
    out["proposed_rule_flow_stress"] = pd.concat(
        [
            rolling_z(np.log1p(out["proposed_rule_count_5d"]), window=ROLL_Z),
            rolling_z(np.log1p(out["proposed_rule_count_21d"]), window=ROLL_Z),
        ],
        axis=1,
    ).mean(axis=1, skipna=False)
    out["combined_reg_flow_stress"] = pd.concat(
        [
            rolling_z(np.log1p(out["combined_reg_count_5d"]), window=ROLL_Z),
            rolling_z(np.log1p(out["combined_reg_count_21d"]), window=ROLL_Z),
        ],
        axis=1,
    ).mean(axis=1, skipna=False)
    for sig in SIGNALS:
        out[f"{sig}_lag1"] = out[sig].shift(1)
    return out


def build_feature_matrix(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    close, volume, price_info = fetch_ohlcv(refresh=refresh)
    close = close.loc[(close.index >= pd.Timestamp(START)) & (close.index <= pd.Timestamp(LAST_COMPLETE_UTC_DATE))]
    volume = volume.loc[(volume.index >= pd.Timestamp(START)) & (volume.index <= pd.Timestamp(LAST_COMPLETE_UTC_DATE))]
    us_calendar_cols = TARGETS + ["SPY", "^VIX"]
    close = close.loc[close[us_calendar_cols].notna().all(axis=1)].copy()
    volume = volume.reindex(close.index)
    ret = np.log(close / close.shift(1))
    df = close.copy()

    docs, fedreg_info = fetch_federal_register_docs(refresh=refresh)
    reg = build_regulatory_signals(docs, df.index)
    df = pd.concat([df, reg], axis=1)

    for ticker in TARGETS + ["SPY"]:
        r = ret[ticker]
        rv21 = r.rolling(RV_WINDOW, min_periods=RV_WINDOW).std(ddof=1).pow(2) * 252
        down21 = r.clip(upper=0).pow(2).rolling(RV_WINDOW, min_periods=RV_WINDOW).mean() * 252
        df[f"{ticker}_ret"] = r
        df[f"{ticker}_log_rv21_lag1"] = np.log(rv21 + 1e-12).shift(1)
        df[f"{ticker}_log_downside21_lag1"] = np.log(down21 + 1e-12).shift(1)

        if ticker in volume.columns:
            logv = np.log(volume[ticker].replace(0, np.nan))
            vol_mu = logv.rolling(VOL_BASE_WINDOW, min_periods=30).mean().shift(1)
            vol_sd = logv.rolling(VOL_BASE_WINDOW, min_periods=30).std(ddof=1).shift(1)
            df[f"{ticker}_volume_z"] = ((logv - vol_mu) / vol_sd).replace([np.inf, -np.inf], np.nan)
            df[f"{ticker}_volume_z_lag1"] = df[f"{ticker}_volume_z"].shift(1)

        if ticker in TARGETS:
            for horizon in HORIZONS:
                future_r2 = pd.concat([r.pow(2).shift(-i) for i in range(1, horizon + 1)], axis=1)
                future_down = pd.concat([r.clip(upper=0).pow(2).shift(-i) for i in range(1, horizon + 1)], axis=1)
                future_ret = pd.concat([r.shift(-i) for i in range(1, horizon + 1)], axis=1)
                df[f"{ticker}_fwd_rv_{horizon}d"] = future_r2.mean(axis=1, skipna=False) * 252
                df[f"{ticker}_fwd_log_rv_{horizon}d"] = np.log(df[f"{ticker}_fwd_rv_{horizon}d"] + 1e-12)
                df[f"{ticker}_fwd_downside_var_{horizon}d"] = future_down.mean(axis=1, skipna=False) * 252
                df[f"{ticker}_fwd_log_downside_var_{horizon}d"] = np.log(
                    df[f"{ticker}_fwd_downside_var_{horizon}d"] + 1e-12
                )
                df[f"{ticker}_fwd_cumret_{horizon}d"] = np.exp(future_ret.sum(axis=1, skipna=False)) - 1.0
                if ticker in volume.columns:
                    logv = np.log(volume[ticker].replace(0, np.nan))
                    future_logv = pd.concat([logv.shift(-i) for i in range(1, horizon + 1)], axis=1)
                    base_mu = logv.rolling(VOL_BASE_WINDOW, min_periods=30).mean().shift(1)
                    base_sd = logv.rolling(VOL_BASE_WINDOW, min_periods=30).std(ddof=1).shift(1)
                    df[f"{ticker}_fwd_volume_shock_{horizon}d"] = (
                        (future_logv.mean(axis=1, skipna=False) - base_mu) / base_sd
                    ).replace([np.inf, -np.inf], np.nan)

    if "^VIX" in close.columns:
        df["VIX_level_lag1"] = close["^VIX"].shift(1)

    df.to_csv(OUT_DATA)
    source_meta = {
        "yfinance_ohlcv": {
            "url": price_info.source_url,
            "close_path": str((DATA_DIR / "yfinance_close.csv").relative_to(HERE)),
            "volume_path": str((DATA_DIR / "yfinance_volume.csv").relative_to(HERE)),
            "close_sha256": sha256_file(DATA_DIR / "yfinance_close.csv"),
            "volume_sha256": sha256_file(DATA_DIR / "yfinance_volume.csv"),
        },
        "federal_register": {
            "url": fedreg_info.source_url,
            "path": str(fedreg_info.path.relative_to(HERE)),
            "sha256": sha256_file(fedreg_info.path),
            "type_codes": FEDREG_TYPE_CODES,
            "alignment": "publication_date assigned to first target ETF trading date >= publication_date; tested signal then shift(1)",
        },
        "analysis_dataset": {
            "path": str(OUT_DATA.relative_to(HERE)),
            "sha256": sha256_file(OUT_DATA),
        },
    }
    return df, source_meta


def ols_hac(y: pd.Series, x: pd.Series, horizon: int, controls: pd.DataFrame | None = None) -> dict:
    pieces = [y.rename("y"), x.rename("x")]
    if controls is not None:
        pieces.append(controls)
    d = pd.concat(pieces, axis=1).dropna()
    if d.shape[0] < 240 or d["x"].std(ddof=1) <= 1e-12:
        return {"error": "insufficient_or_constant", "n": int(d.shape[0])}
    x_cols = ["x"] + ([] if controls is None else list(controls.columns))
    X = sm.add_constant(d[x_cols].values)
    model = sm.OLS(d["y"].values, X).fit(cov_type="HAC", cov_kwds={"maxlags": horizon})
    return {
        "n": int(d.shape[0]),
        "coef": float(model.params[1]),
        "hac_t": float(model.tvalues[1]),
        "p_value": float(model.pvalues[1]),
        "r2": float(model.rsquared),
        "controls": x_cols[1:],
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
        idx: list[int] = []
        while len(idx) < n:
            start = int(RNG.integers(0, max(n - block + 1, 1)))
            idx.extend(range(start, min(start + block, n)))
        idx_arr = np.asarray(idx[:n])
        brho, _ = stats.spearmanr(arr_x[idx_arr], arr_y[idx_arr])
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
    se = np.sqrt(
        max(
            (auc * (1 - auc) + (n1 - 1) * (q1 - auc * auc) + (n0 - 1) * (q2 - auc * auc))
            / (n1 * n0),
            0.0,
        )
    )
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
                "coef": float(row["coef"]),
                "hac_t": float(row["hac_t"]),
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


def controls_for(df: pd.DataFrame, target: str, outcome: str) -> pd.DataFrame:
    cols = [f"{target}_log_rv21_lag1", "SPY_log_rv21_lag1", "VIX_level_lag1"]
    if outcome == "log_downside_var":
        cols.append(f"{target}_log_downside21_lag1")
    if outcome == "volume_shock":
        cols.extend([f"{target}_volume_z_lag1", "SPY_volume_z_lag1"])
    controls = df[[c for c in cols if c in df.columns]].copy()
    controls.columns = [
        c.replace(f"{target}_", "own_").replace("SPY_", "market_") for c in controls.columns
    ]
    return controls


def target_series(df: pd.DataFrame, target: str, horizon: int, outcome: str) -> pd.Series:
    if outcome == "log_rv":
        return df[f"{target}_fwd_log_rv_{horizon}d"]
    if outcome == "log_downside_var":
        return df[f"{target}_fwd_log_downside_var_{horizon}d"]
    if outcome == "volume_shock":
        return df[f"{target}_fwd_volume_shock_{horizon}d"]
    raise ValueError(outcome)


def run_tests(df: pd.DataFrame) -> tuple[dict, list[dict]]:
    out: dict = {}
    p_rows: list[dict] = []
    for target in TARGETS:
        out[target] = {}
        for horizon in HORIZONS:
            horizon_key = f"{horizon}d"
            event_threshold = -0.03 if horizon == 5 else -0.07
            event = df[f"{target}_fwd_cumret_{horizon}d"] <= event_threshold
            out[target][horizon_key] = {}
            for outcome in OUTCOMES:
                y = target_series(df, target, horizon, outcome)
                controls = controls_for(df, target, outcome)
                out[target][horizon_key][outcome] = {}
                for sig in SIGNALS:
                    x = df[f"{sig}_lag1"]
                    univ = ols_hac(y, x, horizon=horizon)
                    controlled = ols_hac(y, x, horizon=horizon, controls=controls)
                    spear = block_bootstrap_spearman(x, y, block=horizon)
                    auc = roc_auc_with_ci(x, event)
                    out[target][horizon_key][outcome][sig] = {
                        "univariate_hac": univ,
                        "controlled_hac": controlled,
                        "spearman": spear,
                        "left_tail_auc": auc,
                        "tail_threshold": event_threshold,
                    }
                    if "p_value" in controlled:
                        label = f"{target}|{horizon_key}|{outcome}|{sig}"
                        p_rows.append(
                            {
                                "label": label,
                                "p_value": controlled["p_value"],
                                "coef": controlled["coef"],
                                "hac_t": controlled["hac_t"],
                            }
                        )
    return out, p_rows


def assess_verdict(primary: dict, mt: dict) -> dict:
    raw_positive = []
    positive_bonferroni = []
    positive_holm = []
    bonf = set(mt.get("bonferroni_survivors", []))
    holm = set(mt.get("holm_survivors", []))
    for target, by_h in primary.items():
        for horizon, by_outcome in by_h.items():
            for outcome, by_sig in by_outcome.items():
                for sig, res in by_sig.items():
                    hac = res["controlled_hac"]
                    if "p_value" not in hac:
                        continue
                    label = f"{target}|{horizon}|{outcome}|{sig}"
                    if hac["coef"] > 0 and hac["p_value"] < 0.05:
                        raw_positive.append(label)
                    if label in bonf and hac["coef"] > 0:
                        positive_bonferroni.append(label)
                    if label in holm and hac["coef"] > 0:
                        positive_holm.append(label)
    if positive_bonferroni or positive_holm:
        verdict = "MIXED_PROXY_POSITIVE"
        rationale = (
            "At least one positive controlled-HAC coefficient survives family correction, "
            "but the Federal Register proxy is not firm-level compliance burden evidence."
        )
    elif raw_positive:
        verdict = "WEAK_RAW_ONLY"
        rationale = (
            "Some positive controlled coefficients are raw-significant, but no positive primary "
            "cell survives the full family correction."
        )
    else:
        verdict = "NULL"
        rationale = (
            "No positive controlled primary coefficient is raw-significant; the public rule-flow "
            "proxy does not robustly lead ETF RV/downside/volume outcomes."
        )
    return {
        "verdict": verdict,
        "positive_raw_p_lt_0_05": raw_positive,
        "positive_bonferroni_survivors": positive_bonferroni,
        "positive_holm_survivors": positive_holm,
        "rationale": rationale,
    }


def top_controlled_rows(primary: dict, n: int = 20) -> list[dict]:
    rows = []
    for target, by_h in primary.items():
        for horizon, by_outcome in by_h.items():
            for outcome, by_sig in by_outcome.items():
                for sig, res in by_sig.items():
                    hac = res["controlled_hac"]
                    if "p_value" not in hac:
                        continue
                    rows.append(
                        {
                            "label": f"{target}|{horizon}|{outcome}|{sig}",
                            "coef": hac["coef"],
                            "hac_t": hac["hac_t"],
                            "p_value": hac["p_value"],
                            "n": hac["n"],
                            "spearman_rho": res["spearman"].get("rho"),
                            "spearman_ci95": res["spearman"].get("ci95"),
                            "tail_auc": res["left_tail_auc"].get("auc"),
                            "tail_auc_ci95": res["left_tail_auc"].get("ci95"),
                        }
                    )
    return sorted(rows, key=lambda r: r["p_value"])[:n]


def make_plots(df: pd.DataFrame, primary: dict) -> None:
    plot_df = df.loc[df.index >= "2018-01-01"].copy()
    fig, ax1 = plt.subplots(figsize=(11, 5))
    ax1.plot(plot_df.index, plot_df["rule_count_21d"], lw=1.0, label="RULE 21d count", color="tab:blue")
    ax1.plot(
        plot_df.index,
        plot_df["proposed_rule_count_21d"],
        lw=1.0,
        label="PRORULE 21d count",
        color="tab:orange",
    )
    ax1.set_ylabel("21-trading-day Federal Register count")
    ax2 = ax1.twinx()
    ax2.plot(
        plot_df.index,
        plot_df["combined_reg_flow_stress"],
        lw=0.9,
        alpha=0.75,
        label="combined stress z",
        color="tab:red",
    )
    ax2.axhline(0, color="black", lw=0.7)
    ax2.set_ylabel("combined rule-flow stress")
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels + labels2, loc="upper left", fontsize=8)
    ax1.set_title("K1568 Federal Register rule/proposed-rule flow proxy")
    fig.tight_layout()
    fig.savefig(FIG1, dpi=160)
    plt.close(fig)

    rows = []
    labels = []
    for target in TARGETS:
        for horizon in HORIZONS:
            rows.append(
                [
                    primary[target][f"{horizon}d"]["log_rv"][sig]["controlled_hac"].get("hac_t", np.nan)
                    for sig in SIGNALS
                ]
            )
            labels.append(f"{target} {horizon}d")
    arr = np.asarray(rows, dtype=float)
    fig, ax = plt.subplots(figsize=(8.8, 6.0))
    im = ax.imshow(arr, cmap="RdBu_r", vmin=-4, vmax=4, aspect="auto")
    ax.set_xticks(np.arange(len(SIGNALS)))
    ax.set_xticklabels(SIGNALS, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels)
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            txt = "" if not np.isfinite(arr[i, j]) else f"{arr[i, j]:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=8.5)
    ax.set_title("Controlled HAC t-stat: rule-flow proxy predicting forward log-RV")
    fig.colorbar(im, ax=ax, label="controlled HAC t-stat")
    fig.tight_layout()
    fig.savefig(FIG2, dpi=160)
    plt.close(fig)

    d = pd.concat(
        [df["combined_reg_flow_stress_lag1"], df["KRE_fwd_log_downside_var_21d"]],
        axis=1,
    ).dropna()
    d.columns = ["signal", "downside"]
    if d.shape[0] > 1800:
        d = d.sample(1800, random_state=SEED)
    fig, ax = plt.subplots(figsize=(7.5, 5.4))
    ax.scatter(d["signal"], d["downside"], s=8, alpha=0.24)
    if d.shape[0] > 20:
        m, b = np.polyfit(d["signal"], d["downside"], 1)
        xs = np.linspace(d["signal"].quantile(0.01), d["signal"].quantile(0.99), 100)
        ax.plot(xs, m * xs + b, color="tab:red", lw=1.4)
    ax.set_title("KRE: combined rule-flow stress vs forward 21d downside variance")
    ax.set_xlabel("combined_reg_flow_stress_lag1")
    ax.set_ylabel("forward 21d log downside variance")
    fig.tight_layout()
    fig.savefig(FIG3, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload yfinance/Federal Register data")
    args = parser.parse_args()

    df, source_meta = build_feature_matrix(refresh=args.refresh)
    primary, p_rows = run_tests(df)
    mt = holm_bonferroni(p_rows)
    verdict = assess_verdict(primary, mt)
    top_rows = top_controlled_rows(primary, n=20)
    make_plots(df, primary)

    descriptions = {
        "regulatory_signals": {
            c: describe_series(df[c])
            for c in [
                "rule_count_21d",
                "proposed_rule_count_21d",
                "combined_reg_count_21d",
            ]
            + SIGNALS
            if c in df.columns
        },
        "targets": {
            t: {
                "price": describe_series(df[t]),
                "fwd_rv_5d": describe_series(df[f"{t}_fwd_rv_5d"]),
                "fwd_rv_21d": describe_series(df[f"{t}_fwd_rv_21d"]),
                "fwd_downside_5d": describe_series(df[f"{t}_fwd_downside_var_5d"]),
                "fwd_downside_21d": describe_series(df[f"{t}_fwd_downside_var_21d"]),
                "fwd_volume_shock_5d": describe_series(df[f"{t}_fwd_volume_shock_5d"]),
                "fwd_volume_shock_21d": describe_series(df[f"{t}_fwd_volume_shock_21d"]),
            }
            for t in TARGETS
        },
    }
    results = {
        "metadata": {
            "experiment_id": "K1568",
            "title": "Federal Register rule-flow public proxy as compliance-exposed ETF RV regime signal",
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
            "targets": TARGETS,
            "controls": CONTROLS,
            "federal_register_docs": int(pd.read_csv(DATA_DIR / "federal_register_rule_prorule_documents.csv").shape[0]),
        },
        "methodology": {
            "proxy_limit": (
                "Federal Register RULE/PRORULE flow is a public regulatory-activity proxy. "
                "It is not RegData restriction intensity, OIRA paperwork burden, firm legal "
                "spend, or true compliance-labor exposure."
            ),
            "signal_construction": (
                "Rule/proposed-rule publication counts are aligned to the next ETF trading date; "
                "5d and 21d log-count rolling z-scores use baselines ending at t-1. Tested "
                "predictors are signal.shift(1)."
            ),
            "forward_target": "Forward outcomes use close-to-close / volume realizations strictly in [t+1, t+H].",
            "primary_regression": (
                "Controlled HAC OLS: forward outcome ~ signal_lag1 + own_log_RV21_lag1 "
                "+ SPY_log_RV21_lag1 + VIX_level_lag1, with downside/volume lag controls added "
                "for matching outcomes."
            ),
            "hac_lag": "HAC maxlags equals forecast horizon H.",
            "spearman_ci": f"moving-block bootstrap with block=H, B={BOOTSTRAP_B}, seed={SEED}.",
            "auc_ci": "Hanley-McNeil normal approximation for left-tail event AUC.",
            "primary_family": (
                f"{len(TARGETS)} targets x {len(HORIZONS)} horizons x {len(OUTCOMES)} outcomes "
                f"x {len(SIGNALS)} signals = {len(TARGETS) * len(HORIZONS) * len(OUTCOMES) * len(SIGNALS)} "
                "controlled-HAC p-values."
            ),
            "success_gate": (
                "Positive controlled-HAC coefficient must survive Bonferroni/Holm family correction; "
                "AUC and Spearman are supporting diagnostics only."
            ),
        },
        "descriptive": descriptions,
        "primary_tests": primary,
        "top_controlled_tests": top_rows,
        "multiple_testing": mt,
        "verdict_assessment": verdict,
        "figures": [str(FIG1.relative_to(HERE)), str(FIG2.relative_to(HERE)), str(FIG3.relative_to(HERE))],
    }
    OUT_JSON.write_text(json.dumps(finite_or_none(results), indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {
                "verdict": verdict["verdict"],
                "assessment": verdict,
                "n_tests": mt["n_tests"],
                "top_controlled_tests": top_rows[:5],
                "results": str(OUT_JSON),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
