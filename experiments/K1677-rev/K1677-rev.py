#!/usr/bin/env python3
"""K1677-rev — fraud/enforcement peer contagion, five-method revision.

Primary estimand
-----------------
For a hand-curated set of public fraud/enforcement revelations, test whether an
event-time-declared same-industry peer basket experiences higher volatility,
downside risk, or illiquidity over t+1..t+10.  Every directional family is
oriented so positive means contagion and is tested one-sided, with BH over the
same pre-declared m=8 family.

Revision safeguards
-------------------
1. Directional one-sided tests and BH(m=8), with sign-aware verdicts.
2. Event-specific declared peer universes, focal-firm exclusion assertions, and
   complete-case primary inference.  Missing/delisted peers drop the whole event
   from primary inference rather than silently shrinking its basket; the old
   available-peer policy is retained only as a labelled sensitivity.
3. Placebo windows cannot overlap the full [-60,+10] window of ANY real event.
4. Standard downside semivariance E[min(r,0)^2] and full-series Amihud returns,
   so the first post-event return t+1 is retained.
5. Calendar-time clusters (overlapping full [-60,+10] analysis windows) provide CR1 one-sided t tests
   and seeded cluster sign-flip p-values; claims require cluster-BH survival.

Data are the immutable K1677 event calendar and cached yfinance OHLCV files.
Missing historical/delisted tickers are never silently replaced by current
survivors.  Seed=42.  Output is written atomically.
"""

from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


SEED = 42
HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "K1677"
EVENTS_CSV = BASE / "events.csv"
DATA_DIR = BASE / "data"
RESULTS = HERE / "K1677-rev_results.json"

PRE_START = -60
PRE_END = -11
POST_START = 1
POST_END = 11
N_PLACEBO = 200
BOOT_REPS = 10_000
ANALYSIS_WINDOW_SPAN = (POST_END - 1) - PRE_START  # 70 trading-index steps
MIN_PEERS = 2
MIN_PRE_OBS = 49
MIN_POST_OBS = 10

# Raw key, expected raw direction.  Results are internally oriented so that
# positive always means the pre-declared contagion alternative.
FAMILY = {
    "rv_mktadj": ("mktadj_log_rv_ratio", +1),
    "rv_placebo_z": ("placebo_z_rv", +1),
    "rv_raw_logratio": ("log_rv_ratio", +1),
    "semivar_mktadj": ("mktadj_sv_diff", +1),
    "semivar_placebo_z": ("placebo_z_sv", +1),
    "worstday_placebo_z": ("placebo_z_worstday", -1),
    "spread_cs_mktadj": ("mktadj_log_cs_ratio", +1),
    "amihud_mktadj": ("mktadj_log_amihud_ratio", +1),
}

REFERENCES = [
    {
        "citation": "Gleason, Jenkins & Johnson (2008), The Accounting Review 83, 83-110",
        "doi": "10.2308/accr.2008.83.1.83",
        "role": "same-industry information-transfer/contagion motivation",
    },
    {
        "citation": "Karpoff, Lee & Martin (2008), JFQA 43, 581-611",
        "doi": "10.1017/S0022109000004221",
        "role": "market revelation and enforcement-cost event framing",
    },
    {
        "citation": "Corwin & Schultz (2012), Journal of Finance 67, 719-760",
        "doi": "10.1111/j.1540-6261.2012.01729.x",
        "role": "daily high-low bid-ask spread estimator",
    },
    {
        "citation": "Amihud (2002), Journal of Financial Markets 5, 31-56",
        "doi": "10.1016/S1386-4181(01)00024-6",
        "role": "absolute-return divided by dollar-volume illiquidity",
    },
]


def load_events() -> pd.DataFrame:
    ev = pd.read_csv(EVENTS_CSV)
    ev["event_date"] = pd.to_datetime(ev["event_date"])
    ev["peers"] = ev["peers"].apply(
        lambda s: [x.strip() for x in str(s).split(";") if x.strip()]
    )
    if ev["event_id"].duplicated().any():
        raise AssertionError("duplicate event_id")
    for row in ev.itertuples(index=False):
        if row.focal in row.peers:
            raise AssertionError(f"focal firm leaked into peers: {row.event_id}")
        if len(row.peers) != len(set(row.peers)):
            raise AssertionError(f"duplicate peer in {row.event_id}")
        if len(row.peers) < MIN_PEERS:
            raise AssertionError(f"too few declared peers in {row.event_id}")
    return ev


def load_cached_prices(tickers: set[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    px: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for ticker in sorted(tickers):
        path = DATA_DIR / f"px_{ticker.replace('/', '-')}.csv"
        if not path.exists():
            missing.append(ticker)
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        need = {"adjclose", "high", "low", "close", "volume"}
        if not need.issubset(df.columns) or len(df) < 50:
            missing.append(ticker)
            continue
        df.index = pd.DatetimeIndex(df.index).tz_localize(None)
        px[ticker] = df.sort_index()
    return px, missing


def event_t0(calendar: pd.DatetimeIndex, date: pd.Timestamp) -> tuple[pd.Timestamp, int] | None:
    after = calendar[calendar >= date]
    if len(after) == 0:
        return None
    t0 = after[0]
    return t0, int(calendar.get_loc(t0))


def peer_coverage(
    px: dict[str, pd.DataFrame], peers: list[str], calendar: pd.DatetimeIndex, t0_idx: int
) -> tuple[list[str], dict[str, str]]:
    pre_dates = calendar[t0_idx + PRE_START : t0_idx + PRE_END]
    post_dates = calendar[t0_idx + POST_START : t0_idx + POST_END]
    usable: list[str] = []
    missing: dict[str, str] = {}
    for peer in peers:
        if peer not in px:
            missing[peer] = "no_cached_history_or_delisted"
            continue
        # Reindex before differencing so t0->t+1 is one trading-session return;
        # a missing t0 cannot silently become a multi-day t+1 return.
        ret = np.log(px[peer]["adjclose"].reindex(calendar)).diff()
        n_pre = int(ret.reindex(pre_dates).notna().sum())
        n_post = int(ret.reindex(post_dates).notna().sum())
        if n_pre < MIN_PRE_OBS or n_post < MIN_POST_OBS:
            missing[peer] = f"window_coverage_pre={n_pre}_post={n_post}"
            continue
        ohlcv = px[peer][["high", "low", "close", "volume"]]
        pre_ok = ohlcv.reindex(pre_dates).notna().all(axis=1).all()
        post_ok = ohlcv.reindex(post_dates).notna().all(axis=1).all()
        volume_ok = bool((ohlcv["volume"].reindex(pre_dates.append(post_dates)) > 0).all())
        if not (pre_ok and post_ok and volume_ok):
            missing[peer] = "incomplete_event_window_ohlcv_or_nonpositive_volume"
            continue
        usable.append(peer)
    return usable, missing


def basket_returns(
    px: dict[str, pd.DataFrame], peers: list[str], calendar: pd.DatetimeIndex
) -> pd.Series:
    cols = {
        peer: np.log(px[peer]["adjclose"].reindex(calendar)).diff() for peer in peers
    }
    frame = pd.DataFrame(cols, index=calendar)
    # Stable declared-universe weights: if one member is absent that day, do not
    # silently reweight the basket across the survivors.
    basket = frame.mean(axis=1, skipna=False)
    basket.name = "peer_basket_return"
    return basket


def realized_vol(ret: np.ndarray) -> float:
    ret = np.asarray(ret, dtype=float)
    if len(ret) < 2:
        return np.nan
    return float(np.std(ret, ddof=1) * np.sqrt(252.0))


def downside_semivariance(ret: np.ndarray) -> float:
    """Standard lower partial second moment around zero, over ALL days."""
    ret = np.asarray(ret, dtype=float)
    if len(ret) == 0:
        return np.nan
    return float(np.mean(np.minimum(ret, 0.0) ** 2))


def window_metrics(series: pd.Series, origin_idx: int) -> dict[str, float] | None:
    if origin_idx + PRE_START < 0 or origin_idx + POST_END > len(series):
        return None
    pre = series.iloc[origin_idx + PRE_START : origin_idx + PRE_END].dropna().to_numpy()
    post = series.iloc[origin_idx + POST_START : origin_idx + POST_END].dropna().to_numpy()
    if len(pre) != MIN_PRE_OBS or len(post) != MIN_POST_OBS:
        return None
    rv_pre, rv_post = realized_vol(pre), realized_vol(post)
    sv_pre, sv_post = downside_semivariance(pre), downside_semivariance(post)
    if not np.isfinite(rv_pre) or not np.isfinite(rv_post) or rv_pre <= 0 or rv_post <= 0:
        return None
    return {
        "rv_pre": rv_pre,
        "rv_post": rv_post,
        "log_rv_ratio": float(np.log(rv_post / rv_pre)),
        "sv_pre": sv_pre,
        "sv_post": sv_post,
        "sv_diff": float(sv_post - sv_pre),
        "log_sv_ratio": float(np.log((sv_post + 1e-12) / (sv_pre + 1e-12))),
        "worst_day_post": float(np.min(post)),
        "n_pre": int(len(pre)),
        "n_post": int(len(post)),
    }


def windows_overlap(a: int, b: int) -> bool:
    a0, a1 = a + PRE_START, a + POST_END - 1
    b0, b1 = b + PRE_START, b + POST_END - 1
    return max(a0, b0) <= min(a1, b1)


def placebo_distribution(
    basket: pd.Series,
    spy_returns: pd.Series,
    focal_event_idx: int,
    real_event_indices: list[int],
    rng: np.random.Generator,
) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    valid: list[tuple[int, dict[str, float]]] = []
    overlap_rejections = 0
    future_rejections = 0
    for origin in range(-PRE_START, len(basket) - POST_END + 1):
        # A placebo is drawn only from information strictly before the focal
        # event's own baseline begins.  This prevents future-origin controls.
        if origin + POST_END - 1 >= focal_event_idx + PRE_START:
            future_rejections += 1
            continue
        if any(windows_overlap(origin, event_idx) for event_idx in real_event_indices):
            overlap_rejections += 1
            continue
        metrics = window_metrics(basket, origin)
        spy_metrics = window_metrics(spy_returns, origin)
        if metrics is not None and spy_metrics is not None:
            metrics = dict(metrics)
            metrics["worstday_mktadj"] = (
                metrics["worst_day_post"] - spy_metrics["worst_day_post"]
            )
            valid.append((origin, metrics))
    if len(valid) < 30:
        empty = {k: np.array([], dtype=float) for k in ("log_rv_ratio", "sv_diff", "worstday_mktadj")}
        return empty, {
            "candidate_count": len(valid),
            "sampled_count": 0,
            "overlap_rejections": overlap_rejections,
            "future_rejections": future_rejections,
            "sampled_overlap_count": 0,
            "sampled_future_count": 0,
        }
    k = min(N_PLACEBO, len(valid))
    chosen = rng.choice(len(valid), size=k, replace=False)
    picked = [valid[int(i)] for i in chosen]
    sampled_overlap = sum(
        any(windows_overlap(origin, event_idx) for event_idx in real_event_indices)
        for origin, _ in picked
    )
    sampled_future = sum(
        origin + POST_END - 1 >= focal_event_idx + PRE_START for origin, _ in picked
    )
    if sampled_overlap or sampled_future:
        raise AssertionError("placebo contamination")
    arrays = {
        key: np.asarray([metrics[key] for _, metrics in picked], dtype=float)
        for key in ("log_rv_ratio", "sv_diff", "worstday_mktadj")
    }
    return arrays, {
        "candidate_count": len(valid),
        "sampled_count": k,
        "overlap_rejections": overlap_rejections,
        "future_rejections": future_rejections,
        "sampled_overlap_count": int(sampled_overlap),
        "sampled_future_count": int(sampled_future),
    }


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> float:
    paired = pd.concat([high.rename("h"), low.rename("l")], axis=1).dropna()
    if len(paired) < 2:
        return np.nan
    h = np.log(paired["h"].to_numpy(dtype=float))
    l = np.log(paired["l"].to_numpy(dtype=float))
    const = 3.0 - 2.0 * np.sqrt(2.0)
    vals = []
    for idx in range(len(h) - 1):
        beta = (h[idx] - l[idx]) ** 2 + (h[idx + 1] - l[idx + 1]) ** 2
        gamma = (max(h[idx], h[idx + 1]) - min(l[idx], l[idx + 1])) ** 2
        alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / const - np.sqrt(gamma / const)
        spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
        vals.append(max(float(spread), 0.0))
    return float(np.mean(vals)) if vals else np.nan


def peer_spread_window(
    px: dict[str, pd.DataFrame], peers: list[str], dates: pd.DatetimeIndex
) -> float:
    vals = []
    for peer in peers:
        sub = px[peer].reindex(dates)
        value = corwin_schultz_spread(sub["high"], sub["low"])
        if np.isfinite(value):
            vals.append(value)
    return float(np.mean(vals)) if len(vals) == len(peers) else np.nan


def peer_amihud_window(
    px: dict[str, pd.DataFrame], peers: list[str], dates: pd.DatetimeIndex
) -> float:
    """Amihud from full-series returns, then slice; retains first window return."""
    vals = []
    for peer in peers:
        df = px[peer]
        calendar = pd.DatetimeIndex(px["SPY"].index)
        aligned = df.reindex(calendar)
        ret = aligned["adjclose"].pct_change(fill_method=None).abs()
        dollar_volume = (aligned["close"] * aligned["volume"]).replace(0.0, np.nan)
        illiq = (ret / dollar_volume * 1e9).replace([np.inf, -np.inf], np.nan)
        win = illiq.reindex(dates).dropna()
        if len(win) == len(dates):
            vals.append(float(win.mean()))
    return float(np.mean(vals)) if len(vals) == len(peers) else np.nan


def log_ratio(pre: float, post: float) -> float | None:
    if not np.isfinite(pre) or not np.isfinite(post) or pre <= 0 or post <= 0:
        return None
    return float(np.log(post / pre))


def evaluate_events(
    ev: pd.DataFrame,
    px: dict[str, pd.DataFrame],
    calendar: pd.DatetimeIndex,
    all_event_indices: list[int],
    complete_case: bool,
) -> tuple[list[dict], list[dict], dict]:
    spy_ret = np.log(px["SPY"]["adjclose"]).diff().reindex(calendar)
    records: list[dict] = []
    dropped: list[dict] = []
    audit = {
        "sampled_placebo_overlap_count": 0,
        "sampled_placebo_future_count": 0,
        "placebo_overlap_rejections": 0,
        "placebo_future_rejections": 0,
    }

    for row in ev.itertuples(index=False):
        digest = hashlib.sha256(row.event_id.encode("utf-8")).digest()
        event_seed = (SEED + int.from_bytes(digest[:4], "little")) % (2**32)
        rng = np.random.default_rng(event_seed)
        t0_info = event_t0(calendar, row.event_date)
        if t0_info is None:
            dropped.append({"event_id": row.event_id, "reason": "event_after_data"})
            continue
        t0, t0_idx = t0_info
        usable, missing = peer_coverage(px, list(row.peers), calendar, t0_idx)
        if complete_case and missing:
            dropped.append(
                {
                    "event_id": row.event_id,
                    "reason": "incomplete_declared_peer_universe",
                    "declared_peers": list(row.peers),
                    "missing_peers": missing,
                }
            )
            continue
        peers = list(row.peers) if complete_case else usable
        if len(peers) < MIN_PEERS:
            dropped.append(
                {
                    "event_id": row.event_id,
                    "reason": "fewer_than_two_usable_peers",
                    "declared_peers": list(row.peers),
                    "missing_peers": missing,
                }
            )
            continue
        if row.focal in peers:
            raise AssertionError(f"focal contamination: {row.event_id}")

        basket = basket_returns(px, peers, calendar)
        metrics = window_metrics(basket, t0_idx)
        spy_metrics = window_metrics(spy_ret, t0_idx)
        if metrics is None or spy_metrics is None:
            dropped.append({"event_id": row.event_id, "reason": "insufficient_event_window"})
            continue

        placebo, placebo_audit = placebo_distribution(
            basket, spy_ret, t0_idx, all_event_indices, rng
        )
        audit["sampled_placebo_overlap_count"] += placebo_audit["sampled_overlap_count"]
        audit["sampled_placebo_future_count"] += placebo_audit["sampled_future_count"]
        audit["placebo_overlap_rejections"] += placebo_audit["overlap_rejections"]
        audit["placebo_future_rejections"] += placebo_audit["future_rejections"]
        placebo_available = placebo_audit["sampled_count"] >= 20

        def placebo_z(key: str, observed: float) -> float | None:
            values = placebo[key]
            if len(values) < 20:
                return None
            sd = float(np.std(values, ddof=1))
            return float((observed - np.mean(values)) / sd) if sd > 0 else None

        pre_dates = calendar[t0_idx + PRE_START : t0_idx + PRE_END]
        post_dates = calendar[t0_idx + POST_START : t0_idx + POST_END]
        cs_pre = peer_spread_window(px, peers, pre_dates)
        cs_post = peer_spread_window(px, peers, post_dates)
        am_pre = peer_amihud_window(px, peers, pre_dates)
        am_post = peer_amihud_window(px, peers, post_dates)
        spy_cs_pre = peer_spread_window(px, ["SPY"], pre_dates)
        spy_cs_post = peer_spread_window(px, ["SPY"], post_dates)
        spy_am_pre = peer_amihud_window(px, ["SPY"], pre_dates)
        spy_am_post = peer_amihud_window(px, ["SPY"], post_dates)
        peer_cs_ratio = log_ratio(cs_pre, cs_post)
        spy_cs_ratio = log_ratio(spy_cs_pre, spy_cs_post)
        peer_am_ratio = log_ratio(am_pre, am_post)
        spy_am_ratio = log_ratio(spy_am_pre, spy_am_post)

        rec = {
            "event_id": row.event_id,
            "focal": row.focal,
            "event_date": row.event_date.strftime("%Y-%m-%d"),
            "t0": t0.strftime("%Y-%m-%d"),
            "t0_index": t0_idx,
            "sector": row.sector,
            "event_type": row.event_type,
            "declared_peers": list(row.peers),
            "peers_used": peers,
            "n_peers_declared": len(row.peers),
            "n_peers_used": len(peers),
            "missing_peer_audit": missing,
            "clean_historical_placebo_available": placebo_available,
            "rv_pre": metrics["rv_pre"],
            "rv_post": metrics["rv_post"],
            "log_rv_ratio": metrics["log_rv_ratio"],
            "mktadj_log_rv_ratio": metrics["log_rv_ratio"] - spy_metrics["log_rv_ratio"],
            "placebo_z_rv": placebo_z("log_rv_ratio", metrics["log_rv_ratio"]),
            "sv_pre": metrics["sv_pre"],
            "sv_post": metrics["sv_post"],
            "log_sv_ratio": metrics["log_sv_ratio"],
            "sv_diff": metrics["sv_diff"],
            "mktadj_sv_diff": metrics["sv_diff"] - spy_metrics["sv_diff"],
            "placebo_z_sv": placebo_z("sv_diff", metrics["sv_diff"]),
            "worst_day_post": metrics["worst_day_post"],
            "spy_worst_day_post": spy_metrics["worst_day_post"],
            "mktadj_worst_day_post": metrics["worst_day_post"] - spy_metrics["worst_day_post"],
            "placebo_z_worstday": placebo_z(
                "worstday_mktadj",
                metrics["worst_day_post"] - spy_metrics["worst_day_post"],
            ),
            "cs_spread_pre": cs_pre,
            "cs_spread_post": cs_post,
            "log_cs_ratio": peer_cs_ratio,
            "spy_log_cs_ratio": spy_cs_ratio,
            "mktadj_log_cs_ratio": (
                peer_cs_ratio - spy_cs_ratio
                if peer_cs_ratio is not None and spy_cs_ratio is not None
                else None
            ),
            "amihud_pre": am_pre,
            "amihud_post": am_post,
            "log_amihud_ratio": peer_am_ratio,
            "spy_log_amihud_ratio": spy_am_ratio,
            "mktadj_log_amihud_ratio": (
                peer_am_ratio - spy_am_ratio
                if peer_am_ratio is not None and spy_am_ratio is not None
                else None
            ),
            "placebo_audit": placebo_audit,
        }
        records.append(rec)

    if (
        audit["sampled_placebo_overlap_count"] != 0
        or audit["sampled_placebo_future_count"] != 0
    ):
        raise AssertionError("nonzero placebo contamination audit")
    return records, dropped, audit


def assign_time_clusters(origins: list[int]) -> np.ndarray:
    """Connected components of overlapping full analysis windows."""
    order = np.argsort(np.asarray(origins, dtype=int))
    cluster = np.empty(len(origins), dtype=int)
    cid = 0
    prev: int | None = None
    for idx in order:
        origin = int(origins[int(idx)])
        if prev is not None and origin - prev > ANALYSIS_WINDOW_SPAN:
            cid += 1
        cluster[int(idx)] = cid
        prev = origin
    return cluster


def directional_test(
    raw: np.ndarray,
    dates: list[pd.Timestamp],
    origins: list[int],
    direction: int,
    rng: np.random.Generator,
) -> dict:
    raw = np.asarray(raw, dtype=float)
    valid = np.isfinite(raw)
    raw = raw[valid]
    dates = [d for d, keep in zip(dates, valid) if keep]
    origins = [origin for origin, keep in zip(origins, valid) if keep]
    oriented = direction * raw
    n = len(oriented)
    if n < 3:
        return {"n": n, "status": "too_few"}
    mean_oriented = float(oriented.mean())
    se_iid = float(oriented.std(ddof=1) / np.sqrt(n))
    t_iid = float(mean_oriented / se_iid) if se_iid > 0 else np.nan
    p_iid = float(stats.t.sf(t_iid, df=n - 1)) if np.isfinite(t_iid) else np.nan
    p_two = float(2.0 * stats.t.sf(abs(t_iid), df=n - 1)) if np.isfinite(t_iid) else np.nan

    clusters = assign_time_clusters(origins)
    unique = np.unique(clusters)
    g = len(unique)
    residual = oriented - mean_oriented
    sums = np.asarray([residual[clusters == c].sum() for c in unique])
    if g >= 3:
        var_mean = float((g / (g - 1.0)) * np.sum(sums**2) / (n**2))
        se_cluster = float(np.sqrt(var_mean))
        t_cluster = float(mean_oriented / se_cluster) if se_cluster > 0 else np.nan
        p_cluster = float(stats.t.sf(t_cluster, df=g - 1)) if np.isfinite(t_cluster) else np.nan
        null_cluster_sums = np.asarray([oriented[clusters == c].sum() for c in unique])
        if g <= 16:
            code = np.arange(2**g, dtype=np.uint32)[:, None]
            bit = (code >> np.arange(g, dtype=np.uint32)) & 1
            signs = bit.astype(float) * 2.0 - 1.0
            signflip_method = f"exact_all_{2**g}_cluster_sign_patterns"
        else:
            signs = rng.choice(np.array([-1.0, 1.0]), size=(BOOT_REPS, g), replace=True)
            signflip_method = f"monte_carlo_{BOOT_REPS}_cluster_sign_patterns_seed_{SEED}"
        boot_means = signs @ null_cluster_sums / n
        if g <= 16:
            p_signflip = float(np.mean(boot_means >= mean_oriented))
        else:
            p_signflip = float((1 + np.sum(boot_means >= mean_oriented)) / (len(boot_means) + 1))
    else:
        se_cluster = t_cluster = p_cluster = p_signflip = np.nan
        signflip_method = "unavailable_fewer_than_3_clusters"

    # Pairs cluster bootstrap CI: resample whole connected time clusters, never
    # individual events.  This CI is descriptive; formal claim gates below use
    # both CR1 and cluster sign-flip p-values.
    cluster_members = [oriented[clusters == c] for c in unique]
    cluster_boot_means = np.empty(BOOT_REPS)
    for b in range(BOOT_REPS):
        chosen = rng.integers(0, g, size=g)
        sample = np.concatenate([cluster_members[int(c)] for c in chosen])
        cluster_boot_means[b] = sample.mean()
    try:
        wilcox = float(stats.wilcoxon(oriented, alternative="greater").pvalue)
    except ValueError:
        wilcox = np.nan
    n_pos = int((oriented > 0).sum())
    sign_p = float(stats.binomtest(n_pos, n, 0.5, alternative="greater").pvalue)
    return {
        "n": n,
        "raw_mean": float(raw.mean()),
        "expected_raw_direction": "positive" if direction > 0 else "negative",
        "oriented_mean_positive_means_contagion": mean_oriented,
        "t_iid_directional": t_iid,
        "p_iid_one_sided": p_iid,
        "p_iid_two_sided_reference": p_two,
        "p_wilcoxon_one_sided": wilcox,
        "p_sign_one_sided": sign_p,
        "cluster_pairs_bootstrap_oriented_mean_ci95": [
            float(np.percentile(cluster_boot_means, 2.5)),
            float(np.percentile(cluster_boot_means, 97.5)),
        ],
        "time_cluster_rule": f"connected full-window overlap; origin gap <= {ANALYSIS_WINDOW_SPAN} trading steps",
        "n_time_clusters": g,
        "cluster_cr1_se": se_cluster,
        "t_cluster_directional": t_cluster,
        "p_cluster_one_sided": p_cluster,
        "p_cluster_signflip_one_sided": p_signflip,
        "cluster_signflip_method": signflip_method,
    }


def bh_adjust(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, dtype=float)
    order = np.argsort(p)
    ranked = p[order] * len(p) / (np.arange(len(p)) + 1.0)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(len(p))
    out[order] = np.minimum(ranked, 1.0)
    return [float(x) for x in out]


def aggregate(records: list[dict]) -> dict[str, dict]:
    rng = np.random.default_rng(SEED)
    out: dict[str, dict] = {}
    for name, (key, direction) in FAMILY.items():
        pairs = [
            (float(r[key]), pd.Timestamp(r["t0"]), int(r["t0_index"]))
            for r in records
            if r.get(key) is not None and np.isfinite(r[key])
        ]
        values = np.asarray([p[0] for p in pairs], dtype=float)
        dates = [p[1] for p in pairs]
        origins = [p[2] for p in pairs]
        out[name] = directional_test(values, dates, origins, direction, rng)
    if len(out) != 8:
        raise AssertionError("primary family must remain m=8")
    keys = list(out)
    iid_q = bh_adjust([out[k]["p_iid_one_sided"] for k in keys])
    cluster_q = bh_adjust([out[k]["p_cluster_one_sided"] for k in keys])
    signflip_q = bh_adjust([out[k]["p_cluster_signflip_one_sided"] for k in keys])
    for idx, key in enumerate(keys):
        out[key]["family_size_m"] = 8
        out[key]["p_bonf_iid_directional"] = min(
            1.0, 8.0 * out[key]["p_iid_one_sided"]
        )
        out[key]["p_bonf_cluster_directional"] = min(
            1.0, 8.0 * out[key]["p_cluster_one_sided"]
        )
        out[key]["p_bonf_cluster_signflip_directional"] = min(
            1.0, 8.0 * out[key]["p_cluster_signflip_one_sided"]
        )
        out[key]["p_bh_iid_directional"] = iid_q[idx]
        out[key]["p_bh_cluster_directional"] = cluster_q[idx]
        out[key]["p_bh_cluster_signflip_directional"] = signflip_q[idx]
    return out


def verdict(aggregates: dict[str, dict], n_events: int) -> dict:
    controlled_rv_keys = ("rv_mktadj", "rv_placebo_z")
    diagnostic_only = {"rv_raw_logratio"}

    def strict_hit(key: str) -> bool:
        result = aggregates[key]
        return bool(
            result["oriented_mean_positive_means_contagion"] > 0
            and result["t_cluster_directional"] >= 3.0
            and result["p_bh_iid_directional"] < 0.05
            and result["p_bh_cluster_directional"] < 0.05
            and result["p_bh_cluster_signflip_directional"] < 0.05
            and result["p_bonf_cluster_directional"] < 0.05
        )

    rv_hits = [
        key
        for key in controlled_rv_keys
        if strict_hit(key)
    ]
    secondary_hits = [
        key
        for key in aggregates
        if key not in controlled_rv_keys and key not in diagnostic_only
        and strict_hit(key)
    ]
    if rv_hits:
        label = "CLUSTER_ROBUST_RV_CONTAGION"
    elif secondary_hits:
        label = "CONTROLLED_RV_NULL_SECONDARY_STRICT_DIRECTIONAL_ASSOCIATION"
    else:
        label = "CONTROLLED_RV_NULL_NO_STRICT_SECONDARY_ASSOCIATION"
    if n_events < 30:
        label += "_UNDERPOWERED"
    return {"label": label, "rv_hits": rv_hits, "secondary_hits": secondary_hits}


def make_figure(aggregates: dict[str, dict]) -> None:
    names = list(aggregates)
    labels = [x.replace("_", "\n") for x in names]
    means = [aggregates[x]["oriented_mean_positive_means_contagion"] for x in names]
    q_cluster = [aggregates[x]["p_bh_cluster_directional"] for x in names]
    strict = [
        aggregates[name]["t_cluster_directional"] >= 3.0
        and aggregates[name]["p_bh_iid_directional"] < 0.05
        and aggregates[name]["p_bh_cluster_directional"] < 0.05
        and aggregates[name]["p_bh_cluster_signflip_directional"] < 0.05
        and aggregates[name]["p_bonf_cluster_directional"] < 0.05
        for name in names
    ]
    colors = ["#b3282d" if hit else "#718096" for hit in strict]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[1.2, 1.0])
    x = np.arange(len(names))
    axes[0].bar(x, means, color=colors)
    axes[0].axhline(0, color="black", lw=0.8)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, fontsize=8)
    axes[0].set_ylabel("oriented mean\n(positive = contagion)")
    axes[0].set_title("K1677-rev: directional peer-contagion effects")
    axes[1].bar(x, q_cluster, color=colors)
    axes[1].axhline(0.05, color="#b3282d", ls="--", lw=1.0, label="CR1 BH q = 0.05")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, fontsize=8)
    axes[1].set_ylabel("time-cluster directional BH q")
    axes[1].set_title(
        "Red requires the full gate: cluster t≥3 + iid/CR1/exact-sign BH + cluster Bonferroni; grey = not strict"
    )
    axes[1].set_ylim(0, min(1.0, max(0.12, max(q_cluster) * 1.1)))
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(HERE / "K1677-rev_directional_results.png", dpi=150)
    plt.close(fig)


def main() -> None:
    ev = load_events()
    tickers = {"SPY"}
    for peers in ev["peers"]:
        tickers.update(peers)
    px, globally_missing = load_cached_prices(tickers)
    if "SPY" not in px:
        raise RuntimeError("SPY cache unavailable")
    calendar = pd.DatetimeIndex(px["SPY"].index).sort_values()
    event_indices = []
    for date in ev["event_date"]:
        info = event_t0(calendar, date)
        if info is not None:
            event_indices.append(info[1])

    primary_records, primary_dropped, primary_placebo_audit = evaluate_events(
        ev, px, calendar, event_indices, complete_case=True
    )
    sensitivity_records, sensitivity_dropped, sensitivity_placebo_audit = evaluate_events(
        ev, px, calendar, event_indices, complete_case=False
    )
    primary_agg = aggregate(primary_records)
    sensitivity_agg = aggregate(sensitivity_records)
    primary_verdict = verdict(primary_agg, len(primary_records))
    sensitivity_verdict = verdict(sensitivity_agg, len(sensitivity_records))
    make_figure(primary_agg)

    missing_occurrences = []
    for row in ev.itertuples(index=False):
        for peer in row.peers:
            if peer in globally_missing:
                missing_occurrences.append({"event_id": row.event_id, "ticker": peer})

    results = {
        "experiment_id": "K1677-rev",
        "revises": "K1677 (Codex FAIL: five method problems)",
        "title": "Fraud/enforcement peer contagion: directional, fail-closed declared-universe revision",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": primary_verdict,
        "sensitivity_verdict": sensitivity_verdict,
        "data_and_methodology": {
            "methodology_type": "empirical event study; descriptive/predictive association, not causal",
            "event_source": "hand-curated public revelation calendar from K1677/events.csv; not full AAER population",
            "price_source": "K1677 cached yfinance daily OHLCV, auto_adjust=False",
            "price_period": [str(calendar.min().date()), str(calendar.max().date())],
            "input_events": len(ev),
            "primary_usable_events": len(primary_records),
            "sensitivity_usable_events": len(sensitivity_records),
            "post_window": "t+1..t+10",
            "pre_window": "t-60..t-12 (Python slice [-60,-11))",
            "primary_peer_policy": "event-specific declared list, focal ticker excluded, strict 49/49 pre-return + 10/10 post-return and full OHLCV; complete-event drop if any declared peer fails",
            "sensitivity_peer_policy": "available declared peers, explicitly labelled; never substitutes current survivors",
            "multiple_testing": "directional one-sided Bonferroni+BH separately over pre-declared m=8; claim requires iid-BH, CR1 cluster-BH+Bonferroni, cluster-sign-flip BH all <.05 plus cluster t>=3",
            "time_dependence": f"CR1 connected components of overlapping full [-60,+10] windows (origin gap <= {ANALYSIS_WINDOW_SPAN} trading steps); cluster sign-flip sensitivity",
        },
        "five_fixes": {
            "directional_tests": "all eight outcomes sign-oriented; one-sided iid/cluster tests and BH(m=8)",
            "peer_universe_fail_closed": "focal ticker assertion + frozen event-specific declared peers + strict complete-event primary; missing peers/events fully reported; not represented as a licensed historical-universe reconstruction",
            "clean_placebo": "historical-only candidate [-60,+10] window must end before focal baseline and cannot overlap any real event [-60,+10] window; both audits asserted zero",
            "measure_definitions": "standard E[min(r,0)^2]; Amihud full-series pct_change before slicing retains t+1",
            "time_cluster_inference": "calendar-time CR1, whole-cluster pairs CI, and 10,000 seeded cluster sign flips; no iid-only finding is called robust",
        },
        "peer_universe_audit": {
            "globally_missing_tickers": globally_missing,
            "missing_occurrences": missing_occurrences,
            "n_missing_occurrences": len(missing_occurrences),
            "primary_dropped_events": primary_dropped,
            "sensitivity_dropped_events": sensitivity_dropped,
        },
        "placebo_audit_primary": primary_placebo_audit,
        "placebo_audit_sensitivity": sensitivity_placebo_audit,
        "aggregates_primary_complete_case": primary_agg,
        "aggregates_available_peer_sensitivity": sensitivity_agg,
        "per_event_primary": primary_records,
        "per_event_available_peer_sensitivity": sensitivity_records,
        "references": REFERENCES,
        "honesty_caveats": [
            "Salient events are hand-curated, so results do not estimate average effects in the full SEC AAER population.",
            "Peer lists are frozen event-specific declarations, not a licensed historical index-membership database.",
            "Ticker-string focal exclusion cannot replace PERMCO/entity-level exclusion; no knowledge-grade claim about a fully reconstructed point-in-time industry universe is made.",
            "Complete-case primary inference avoids silent survivor reweighting but can lose events with delisted peers; available-peer sensitivity is reported separately.",
            "N<30 remains underpowered; cluster inference further reduces effective degrees of freedom.",
            "Associations around revelation dates are not causal estimates.",
            "Liquidity families are market-adjusted against contemporaneous SPY CS/Amihud changes; raw peer ratios remain diagnostics only.",
        ],
    }

    HERE.mkdir(parents=True, exist_ok=True)
    tmp = RESULTS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(results, indent=2, default=str))
    json.loads(tmp.read_text())
    os.replace(tmp, RESULTS)
    pd.DataFrame(primary_records).to_csv(HERE / "K1677-rev_event_table.csv", index=False)

    print(json.dumps({
        "experiment_id": "K1677-rev",
        "n_primary": len(primary_records),
        "n_sensitivity": len(sensitivity_records),
        "verdict": primary_verdict,
        "missing_occurrences": len(missing_occurrences),
        "placebo_overlap": primary_placebo_audit["sampled_placebo_overlap_count"],
    }, indent=2))


if __name__ == "__main__":
    main()
