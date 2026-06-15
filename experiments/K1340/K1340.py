"""
K1340: Retail/gamma-pressure candidate event study.

Free-data proxy:
  shock_pressure_t = return_t * prior-only volume_z_t

The shock is only known after the close on day t.  The tradable event date is
the next trading day, implemented by shifting the raw event signal forward one
row before measuring forward returns.  This avoids using same-day pressure to
explain same-day returns.

Seed: 42.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"yfinance not available: {exc}")


HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "K1340_results.json"

SEED = 42
START_DATE = "2024-01-01"
END_DATE = "2026-06-14"
TRADING_DAYS_PER_YEAR = 252

TICKERS = [
    "GME",
    "AMC",
    "KOSS",
    "BB",
    "OPEN",
    "KSS",
    "BYND",
    "GPRO",
    "DNUT",
    "HOOD",
    "CHWY",
    "LCID",
    "RIVN",
    "PLTR",
    "SOFI",
]
MARKET = "SPY"

VOLUME_Z_WINDOW = 60
VOLUME_Z_MIN = 2.0
ABS_RETURN_MIN = 0.05
PRESSURE_MIN = 0.12
COOLDOWN_DAYS = 21
HORIZONS = [5, 10, 21]
BOOTSTRAP_B = 5000
BONFERRONI_ALPHA = 0.10


@dataclass
class DownloadReport:
    symbol: str
    ok: bool
    rows: int = 0
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    error: Optional[str] = None


def _pick_column(df: pd.DataFrame, field: str, symbol: str) -> pd.Series:
    if isinstance(df.columns, pd.MultiIndex):
        if (field, symbol) in df.columns:
            return df[(field, symbol)]
        if field in df.columns.get_level_values(0):
            sub = df[field]
            if isinstance(sub, pd.DataFrame):
                return sub.iloc[:, 0]
            return sub
    if field in df.columns:
        return df[field]
    raise KeyError(f"{field} not found for {symbol}")


def download_symbol(symbol: str) -> Tuple[Optional[pd.DataFrame], DownloadReport]:
    try:
        df = yf.download(
            symbol,
            start=START_DATE,
            end=END_DATE,
            progress=False,
            auto_adjust=False,
            threads=False,
        )
    except Exception as exc:
        return None, DownloadReport(symbol=symbol, ok=False, error=str(exc))

    if df is None or df.empty:
        return None, DownloadReport(symbol=symbol, ok=False, error="empty download")

    try:
        adj = _pick_column(df, "Adj Close", symbol)
    except KeyError:
        adj = _pick_column(df, "Close", symbol)
    try:
        close = _pick_column(df, "Close", symbol)
        volume = _pick_column(df, "Volume", symbol)
    except KeyError as exc:
        return None, DownloadReport(symbol=symbol, ok=False, error=str(exc))

    out = pd.DataFrame(
        {
            "adj_close": pd.to_numeric(adj, errors="coerce"),
            "close": pd.to_numeric(close, errors="coerce"),
            "volume": pd.to_numeric(volume, errors="coerce"),
        }
    ).dropna()
    out = out[out["volume"] > 0]
    if len(out) < VOLUME_Z_WINDOW + max(HORIZONS) + 5:
        return None, DownloadReport(
            symbol=symbol,
            ok=False,
            rows=len(out),
            first_date=str(out.index[0].date()) if len(out) else None,
            last_date=str(out.index[-1].date()) if len(out) else None,
            error="insufficient rows",
        )
    report = DownloadReport(
        symbol=symbol,
        ok=True,
        rows=len(out),
        first_date=str(out.index[0].date()),
        last_date=str(out.index[-1].date()),
    )
    return out, report


def prepare_panel(symbol: str, df: pd.DataFrame, market_ret: pd.Series) -> pd.DataFrame:
    out = df.copy()
    out["ret"] = np.log(out["adj_close"] / out["adj_close"].shift(1))
    vol_mean = out["volume"].shift(1).rolling(VOLUME_Z_WINDOW, min_periods=VOLUME_Z_WINDOW).mean()
    vol_std = out["volume"].shift(1).rolling(VOLUME_Z_WINDOW, min_periods=VOLUME_Z_WINDOW).std(ddof=1)
    out["volume_z"] = (out["volume"] - vol_mean) / vol_std.replace(0, np.nan)
    out["pressure_raw"] = out["ret"] * out["volume_z"]
    out["positive_raw_event"] = (
        (out["volume_z"] >= VOLUME_Z_MIN)
        & (out["ret"] >= ABS_RETURN_MIN)
        & (out["pressure_raw"] >= PRESSURE_MIN)
    )
    out["negative_raw_event"] = (
        (out["volume_z"] >= VOLUME_Z_MIN)
        & (out["ret"] <= -ABS_RETURN_MIN)
        & (out["pressure_raw"] <= -PRESSURE_MIN)
    )

    # Explicit causal convention: event_signal at date t is based on pressure
    # observed at t-1.  Forward windows begin at this tradable date t.
    out["positive_event_signal"] = out["positive_raw_event"].shift(1).fillna(False)
    out["negative_event_signal"] = out["negative_raw_event"].shift(1).fillna(False)
    out["shock_date"] = pd.Series(out.index, index=out.index).shift(1)
    out["shock_return"] = out["ret"].shift(1)
    out["shock_volume_z"] = out["volume_z"].shift(1)
    out["shock_pressure"] = out["pressure_raw"].shift(1)
    out["market_ret"] = market_ret.reindex(out.index)
    out["excess_ret_spy"] = out["ret"] - out["market_ret"]
    return out.dropna(subset=["ret", "market_ret"])


def _cooldown_events(panel: pd.DataFrame, event_col: str) -> List[pd.Timestamp]:
    dates: List[pd.Timestamp] = []
    last_pos = -10_000
    idx = panel.index
    signal = panel[event_col].astype(bool).to_numpy()
    for pos, is_event in enumerate(signal):
        if not is_event:
            continue
        if pos - last_pos < COOLDOWN_DAYS:
            continue
        if pos < max(HORIZONS) or pos + max(HORIZONS) > len(panel):
            continue
        dates.append(idx[pos])
        last_pos = pos
    return dates


def annualized_vol(values: pd.Series) -> float:
    if len(values) < 3:
        return float("nan")
    return float(values.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def window_outcome(panel: pd.DataFrame, event_date: pd.Timestamp, horizon: int) -> Optional[Dict]:
    if event_date not in panel.index:
        return None
    loc = panel.index.get_loc(event_date)
    pre_start = loc - horizon
    post_end = loc + horizon
    if pre_start < 0 or post_end > len(panel):
        return None

    pre = panel.iloc[pre_start:loc]
    post = panel.iloc[loc:post_end]
    if len(pre) < horizon or len(post) < horizon:
        return None

    vol_pre = annualized_vol(pre["ret"])
    vol_post = annualized_vol(post["ret"])
    if not np.isfinite(vol_pre) or not np.isfinite(vol_post) or vol_pre <= 0:
        return None

    return {
        "horizon": horizon,
        "vol_pre": vol_pre,
        "vol_post": vol_post,
        "rv_jump_pct": float((vol_post - vol_pre) / vol_pre),
        "car": float(np.expm1(post["ret"].sum())),
        "car_ex_spy": float(np.expm1(post["excess_ret_spy"].sum())),
        "post_abs_return_mean": float(post["ret"].abs().mean()),
    }


def eligible_control_dates(
    panel: pd.DataFrame,
    event_dates: Iterable[pd.Timestamp],
    horizon: int,
) -> List[pd.Timestamp]:
    idx = panel.index
    event_locs = [idx.get_loc(d) for d in event_dates if d in idx]
    controls = []
    for pos, date in enumerate(idx):
        if pos < horizon or pos + horizon > len(panel):
            continue
        if panel.loc[date, "positive_event_signal"] or panel.loc[date, "negative_event_signal"]:
            continue
        if any(abs(pos - ev_pos) < horizon for ev_pos in event_locs):
            continue
        controls.append(date)
    return controls


def matched_control_mean(
    panel: pd.DataFrame,
    event_date: pd.Timestamp,
    controls_by_h: Dict[int, List[pd.Timestamp]],
    horizon: int,
    metric: str,
) -> Tuple[float, int]:
    candidates = controls_by_h[horizon]
    same_year = [d for d in candidates if d.year == event_date.year]
    use = same_year if len(same_year) >= 5 else candidates
    vals = []
    for d in use:
        outcome = window_outcome(panel, d, horizon)
        if outcome is not None and np.isfinite(outcome[metric]):
            vals.append(outcome[metric])
    if not vals:
        return float("nan"), 0
    return float(np.mean(vals)), len(vals)


def stable_seed(*parts: object) -> int:
    text = "|".join(str(p) for p in parts)
    acc = SEED
    for ch in text:
        acc = (acc * 131 + ord(ch)) % 1_000_000_007
    return SEED + acc % 100_000


def bootstrap_ci(values: np.ndarray, seed: int, B: int = BOOTSTRAP_B) -> Dict:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n < 3:
        return {
            "mean": float(np.nan),
            "ci_low": float(np.nan),
            "ci_high": float(np.nan),
            "p_signflip_two_sided": float(np.nan),
            "n": int(n),
        }
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(B, n))
    boot_means = values[idx].mean(axis=1)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(B, n))
    null_means = (values[None, :] * signs).mean(axis=1)
    obs = float(values.mean())
    p = float(np.mean(np.abs(null_means) >= abs(obs)))
    return {
        "mean": obs,
        "ci_low": float(np.quantile(boot_means, 0.025)),
        "ci_high": float(np.quantile(boot_means, 0.975)),
        "p_signflip_two_sided": p,
        "n": int(n),
    }


def clustered_bootstrap_ci(
    values: np.ndarray,
    clusters: Iterable[str],
    seed: int,
    B: int = BOOTSTRAP_B,
) -> Dict:
    df = pd.DataFrame({"value": np.asarray(values, dtype=float), "cluster": list(clusters)})
    df = df[np.isfinite(df["value"])]
    if df.empty:
        return {
            "mean": float("nan"),
            "ci_low": float("nan"),
            "ci_high": float("nan"),
            "p_signflip_two_sided": float("nan"),
            "n": 0,
            "n_clusters": 0,
        }
    cluster_values = df.groupby("cluster")["value"].mean().to_numpy(dtype=float)
    stat = bootstrap_ci(cluster_values, seed=seed, B=B)
    stat["n_events"] = int(len(df))
    stat["n_clusters"] = int(len(cluster_values))
    return stat


def build_event_records(symbol: str, panel: pd.DataFrame) -> List[Dict]:
    pos_dates = _cooldown_events(panel, "positive_event_signal")
    neg_dates = _cooldown_events(panel, "negative_event_signal")
    all_event_dates = sorted(pos_dates + neg_dates)
    records: List[Dict] = []
    controls = {
        H: eligible_control_dates(panel, all_event_dates, H)
        for H in HORIZONS
    }

    for event_type, dates in [("positive_pressure", pos_dates), ("negative_pressure", neg_dates)]:
        for event_date in dates:
            row = panel.loc[event_date]
            rec = {
                "symbol": symbol,
                "event_type": event_type,
                "event_date": str(event_date.date()),
                "shock_date": str(pd.Timestamp(row["shock_date"]).date()),
                "shock_return": float(row["shock_return"]),
                "shock_volume_z": float(row["shock_volume_z"]),
                "shock_pressure": float(row["shock_pressure"]),
                "by_horizon": {},
            }
            for H in HORIZONS:
                outcome = window_outcome(panel, event_date, H)
                if outcome is None:
                    continue
                metric_block = dict(outcome)
                for metric in ["rv_jump_pct", "car", "car_ex_spy"]:
                    ctrl_mean, ctrl_n = matched_control_mean(panel, event_date, controls, H, metric)
                    metric_block[f"{metric}_matched_control_mean"] = ctrl_mean
                    metric_block[f"{metric}_matched_diff"] = (
                        float(outcome[metric] - ctrl_mean) if np.isfinite(ctrl_mean) else float("nan")
                    )
                    metric_block[f"{metric}_matched_control_n"] = ctrl_n
                if event_type == "positive_pressure":
                    metric_block["reversal"] = bool(outcome["car"] < 0)
                else:
                    metric_block["reversal"] = bool(outcome["car"] > 0)
                rec["by_horizon"][str(H)] = metric_block
            records.append(rec)
    return records


def summarize(records: List[Dict]) -> Dict:
    pooled: Dict[str, Dict[str, Dict]] = {}
    tests = []
    for event_type in ["positive_pressure", "negative_pressure"]:
        pooled[event_type] = {}
        for H in HORIZONS:
            hkey = str(H)
            group_recs = [
                rec for rec in records
                if rec["event_type"] == event_type and hkey in rec["by_horizon"]
            ]
            rows = [rec["by_horizon"][hkey] for rec in group_recs]
            clusters = [rec["event_date"] for rec in group_recs]
            block: Dict[str, object] = {"n_events": len(rows)}
            if rows:
                block["mean_shock_return"] = float(np.mean([
                    rec["shock_return"] for rec in group_recs
                ]))
                block["reversal_rate"] = float(np.mean([r["reversal"] for r in rows]))
            for metric in ["rv_jump_pct", "car", "car_ex_spy"]:
                raw = np.asarray([r[metric] for r in rows], dtype=float)
                diff = np.asarray([r[f"{metric}_matched_diff"] for r in rows], dtype=float)
                block[metric] = bootstrap_ci(raw, stable_seed(event_type, H, metric, "raw"))
                block[f"{metric}_matched_diff"] = bootstrap_ci(
                    diff, stable_seed(event_type, H, metric, "matched")
                )
                block[f"{metric}_matched_diff_date_cluster"] = clustered_bootstrap_ci(
                    diff,
                    clusters,
                    stable_seed(event_type, H, metric, "matched", "cluster"),
                )
                if metric in {"rv_jump_pct", "car"}:
                    event_stat = block[f"{metric}_matched_diff"]
                    cluster_stat = block[f"{metric}_matched_diff_date_cluster"]
                    tests.append(
                        {
                            "event_type": event_type,
                            "horizon": H,
                            "metric": f"{metric}_matched_diff",
                            "event_level_mean": event_stat["mean"],
                            "event_level_p": event_stat["p_signflip_two_sided"],
                            "event_level_n": event_stat["n"],
                            "mean": cluster_stat["mean"],
                            "p": cluster_stat["p_signflip_two_sided"],
                            "n_clusters": cluster_stat["n_clusters"],
                            "n_events": cluster_stat["n_events"],
                        }
                    )
            pooled[event_type][hkey] = block

    alpha_bonf = BONFERRONI_ALPHA / max(len(tests), 1)
    def is_supportive(test: Dict) -> bool:
        if test["metric"] == "rv_jump_pct_matched_diff":
            return bool(np.isfinite(test["mean"]) and test["mean"] > 0)
        if test["metric"] == "car_matched_diff":
            # Positive-pressure CAR > 0 is continuation.  Negative-pressure
            # CAR > 0 is post-selloff reversal.  Both are directionally
            # meaningful; CAR < 0 is adverse continuation.
            return bool(np.isfinite(test["mean"]) and test["mean"] > 0)
        return False

    for t in tests:
        t["bonferroni_alpha_010"] = alpha_bonf
        t["direction_supportive"] = is_supportive(t)
        t["survives_bonferroni_010"] = bool(
            np.isfinite(t["p"]) and t["p"] < alpha_bonf
        )
    raw_hits = [t for t in tests if np.isfinite(t["p"]) and t["p"] < 0.10]
    raw_supportive_hits = [t for t in raw_hits if t["direction_supportive"]]
    bonf_hits = [t for t in tests if t["survives_bonferroni_010"]]
    bonf_supportive_hits = [t for t in bonf_hits if t["direction_supportive"]]
    inverse_bonf_hits = [t for t in bonf_hits if not t["direction_supportive"]]
    primary = next(
        (
            t for t in tests
            if t["event_type"] == "positive_pressure"
            and t["horizon"] == 21
            and t["metric"] == "car_matched_diff"
        ),
        None,
    )

    if (
        primary
        and primary["n_clusters"] >= 10
        and primary["p"] < alpha_bonf
        and primary["direction_supportive"]
    ):
        verdict = "PASS"
    elif bonf_supportive_hits:
        verdict = "CONDITIONAL_PASS"
    elif raw_supportive_hits:
        verdict = "WEAK_UNADJUSTED_SIGNAL"
    elif inverse_bonf_hits:
        verdict = "NULL_INVERSE_VOL_COMPRESSION"
    else:
        verdict = "NULL"

    return {
        "pooled": pooled,
        "multiple_testing": {
            "family": "2 event types x 3 horizons x 2 primary metrics (rv_jump_pct, car) = 12 tests",
            "alpha_family": BONFERRONI_ALPHA,
            "alpha_bonferroni": alpha_bonf,
            "tests": tests,
            "raw_p_lt_010": raw_hits,
            "raw_supportive_p_lt_010": raw_supportive_hits,
            "bonferroni_hits": bonf_hits,
            "bonferroni_supportive_hits": bonf_supportive_hits,
            "inverse_bonferroni_hits": inverse_bonf_hits,
            "primary_test": primary,
            "main_p_value_basis": "date-clustered sign-flip p-value; same-date cross-ticker events are averaged before testing",
        },
        "verdict": verdict,
    }


def overlap_diagnostics(records: List[Dict]) -> Dict:
    out: Dict[str, Dict] = {}
    for event_type in ["positive_pressure", "negative_pressure"]:
        dates = sorted(pd.Timestamp(r["event_date"]) for r in records if r["event_type"] == event_type)
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        out[event_type] = {
            "n": len(dates),
            "min_calendar_gap": int(min(gaps)) if gaps else None,
            "median_calendar_gap": float(np.median(gaps)) if gaps else None,
            "gaps_lt_21_calendar_days": int(sum(g < 21 for g in gaps)),
            "gaps_lt_30_calendar_days": int(sum(g < 30 for g in gaps)),
        }
    return out


def make_figures(records: List[Dict], summary: Dict) -> List[str]:
    paths: List[str] = []
    if not records:
        return paths

    counts = (
        pd.DataFrame(records)
        .groupby(["symbol", "event_type"])
        .size()
        .unstack(fill_value=0)
        .sort_index()
    )
    fig, ax = plt.subplots(figsize=(10, 4.8))
    counts.plot(kind="bar", stacked=True, ax=ax, color=["#3b82f6", "#ef4444"])
    ax.set_title("K1340 retail/gamma-pressure proxy events")
    ax.set_ylabel("Event count")
    ax.set_xlabel("")
    ax.legend(title="")
    fig.tight_layout()
    p1 = HERE / "K1340_event_counts.png"
    fig.savefig(p1, dpi=160)
    plt.close(fig)
    paths.append(str(p1.relative_to(HERE)))

    rows = []
    for event_type, hmap in summary["pooled"].items():
        for h, block in hmap.items():
            rows.append(
                {
                    "label": f"{event_type.replace('_pressure', '')} H{h}",
                    "car": block["car_matched_diff"]["mean"],
                    "car_low": block["car_matched_diff"]["ci_low"],
                    "car_high": block["car_matched_diff"]["ci_high"],
                    "rv": block["rv_jump_pct_matched_diff"]["mean"],
                    "rv_low": block["rv_jump_pct_matched_diff"]["ci_low"],
                    "rv_high": block["rv_jump_pct_matched_diff"]["ci_high"],
                }
            )
    df = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    x = np.arange(len(df))
    axes[0].bar(x, df["car"], color="#2563eb")
    axes[0].errorbar(
        x,
        df["car"],
        yerr=[df["car"] - df["car_low"], df["car_high"] - df["car"]],
        fmt="none",
        ecolor="#111827",
        capsize=3,
    )
    axes[0].axhline(0, color="#111827", linewidth=0.8)
    axes[0].set_title("Matched forward CAR difference")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(df["label"], rotation=45, ha="right")
    axes[0].set_ylabel("Return difference")

    axes[1].bar(x, df["rv"], color="#dc2626")
    axes[1].errorbar(
        x,
        df["rv"],
        yerr=[df["rv"] - df["rv_low"], df["rv_high"] - df["rv"]],
        fmt="none",
        ecolor="#111827",
        capsize=3,
    )
    axes[1].axhline(0, color="#111827", linewidth=0.8)
    axes[1].set_title("Matched RV-jump difference")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(df["label"], rotation=45, ha="right")
    axes[1].set_ylabel("Vol-jump difference")
    fig.tight_layout()
    p2 = HERE / "K1340_matched_effects.png"
    fig.savefig(p2, dpi=160)
    plt.close(fig)
    paths.append(str(p2.relative_to(HERE)))
    return paths


def run() -> Dict:
    np.random.seed(SEED)

    raw: Dict[str, pd.DataFrame] = {}
    reports: List[DownloadReport] = []
    for symbol in [MARKET] + TICKERS:
        df, report = download_symbol(symbol)
        reports.append(report)
        if df is not None:
            raw[symbol] = df

    if MARKET not in raw:
        raise SystemExit("SPY market benchmark unavailable")
    market_ret = np.log(raw[MARKET]["adj_close"] / raw[MARKET]["adj_close"].shift(1)).dropna()

    panels: Dict[str, pd.DataFrame] = {}
    records: List[Dict] = []
    for symbol in TICKERS:
        if symbol not in raw:
            continue
        panel = prepare_panel(symbol, raw[symbol], market_ret)
        panels[symbol] = panel
        records.extend(build_event_records(symbol, panel))

    records.sort(key=lambda r: (r["event_date"], r["symbol"], r["event_type"]))
    summary = summarize(records)
    figures = make_figures(records, summary)

    by_symbol = {}
    for symbol in TICKERS:
        rs = [r for r in records if r["symbol"] == symbol]
        if not rs:
            by_symbol[symbol] = {"positive_pressure": 0, "negative_pressure": 0}
        else:
            by_symbol[symbol] = {
                "positive_pressure": sum(r["event_type"] == "positive_pressure" for r in rs),
                "negative_pressure": sum(r["event_type"] == "negative_pressure" for r in rs),
            }

    out = {
        "experiment_id": "K1340",
        "title": "Gamma-squeeze candidate retail-pressure event study",
        "run_timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        "data": {
            "source": "yfinance daily adjusted close and volume",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "tickers_requested": TICKERS,
            "market": MARKET,
            "download_reports": [r.__dict__ for r in reports],
            "usable_tickers": sorted(panels.keys()),
        },
        "method": {
            "pressure_proxy": "return_t * volume_z_t, where volume_z_t compares volume_t to the prior 60 trading days",
            "lookahead_policy": "raw pressure is observed after close t; event_signal = raw_event.shift(1); forward windows begin at t+1 tradable date",
            "volume_z_window": VOLUME_Z_WINDOW,
            "volume_z_min": VOLUME_Z_MIN,
            "abs_return_min": ABS_RETURN_MIN,
            "pressure_min": PRESSURE_MIN,
            "cooldown_days_per_symbol": COOLDOWN_DAYS,
            "horizons": HORIZONS,
            "bootstrap_B": BOOTSTRAP_B,
            "seed": SEED,
        },
        "events": {
            "count_total": len(records),
            "by_symbol": by_symbol,
            "overlap_diagnostics": overlap_diagnostics(records),
            "records": records,
        },
        "summary": summary,
        "figures": figures,
        "verdict": summary["verdict"],
        "notes": [
            "This is not a true dealer-gamma test: free yfinance data has no options open interest, customer direction, or dealer gamma exposure.",
            "The proxy captures high-volume signed price pressure in retail/gamma candidate stocks.",
            "Matched controls are same-symbol, same-year when available, excluding nearby event days.",
            "All statistical claims must respect the 12-test Bonferroni family in summary.multiple_testing.",
        ],
    }
    return out


def main() -> None:
    result = run()
    RESULTS_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print(f"K1340 verdict: {result['verdict']}")
    print(f"usable tickers: {len(result['data']['usable_tickers'])}/{len(TICKERS)}")
    print(f"events: {result['events']['count_total']}")
    mt = result["summary"]["multiple_testing"]
    print(f"raw p<0.10 tests: {len(mt['raw_p_lt_010'])}")
    print(f"supportive raw p<0.10 tests: {len(mt['raw_supportive_p_lt_010'])}")
    print(f"Bonferroni hits: {len(mt['bonferroni_hits'])}")
    print(f"supportive Bonferroni hits: {len(mt['bonferroni_supportive_hits'])}")
    primary = mt["primary_test"]
    if primary:
        print(
            "primary positive H21 CAR matched diff (date-clustered): "
            f"mean={primary['mean']:.4f}, p={primary['p']:.4f}, "
            f"clusters={primary['n_clusters']}, events={primary['n_events']}"
        )


if __name__ == "__main__":
    main()
