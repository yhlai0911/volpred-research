#!/usr/bin/env python
"""Indicator Arena — daily signal emission + outcome review pipeline.

Task: indicator_arena_phase1d_cron_job_2026_06_11
Design doc: docs/indicator_arena_design.md (§2 schema, §4 honesty, §5 scoring, §6 rules)

For every non-delisted indicator in storage/indicator_arena/registry.json this
script:
  1. Computes today's real indicator value + prediction from the signal_rule
     (data source: yfinance, per-registry tickers; ^VIX9D has a CBOE CSV fallback).
  2. Appends the signal via volpred.indicators.signals.append_signal (append-only;
     never writes JSONL directly).
  3. Resolves signals past resolve_after that have no review yet, computing
     realized outcomes and appending via volpred.indicators.reviews.compute_review.
  4. Pushes local canonical files to Supabase via sync_indicator_arena().

Honesty discipline (研究誠實原則 — highest priority):
  - Ex-ante: signals only use data realized at/before as_of_ts (completed
    sessions only; in-progress bars are dropped). append_signal enforces
    as_of_ts <= emitted_at.
  - Explicit lag: every rule uses t-1 completed closes to predict day t
    (equivalent of signal.shift(1)).
  - Idempotent: signal_id = "<indicator_id>:<target_date>"; an existing
    signal_id is skipped, never re-appended or rewritten.
  - Stale data (§4.5): if a required series has not updated, the indicator is
    SKIPPED for the day (recorded in the run summary) — stale values are never
    passed off as fresh.
  - Failure isolation: one indicator failing (fetch error etc.) does not block
    the others; the exit code reflects whether the run was fully successful.

Model specs mirror the source experiments exactly:
  - garch_vix9d_spy_var25      -> experiments/k1004 (A4f-VIX9D-t, window=2000)
  - har_qr_spy_var5            -> experiments/K1313 (HAR-QR tau=0.05 on raw returns)
  - har_qr_rv_q95_qqq_gld_tlt  -> experiments/k1403 (HAR-RV QuantReg q95 on |ret%|)
  - vix_term_structure_vol_direction -> experiments/k1415 (log(VIX9D/VIX), RV=r^2*252)
  - us_tw_overnight_lead       -> experiments/k461 + k521
  - vix_crisis_alert_tw        -> experiments/k817 (spike+level composite)

Usage:
  uv run python scripts/indicator_arena_daily.py [--dry-run] [--no-sync]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.indicators.registry import load_registry  # noqa: E402
from volpred.indicators.signals import (  # noqa: E402
    SIGNALS_DIR,
    _get_git_short_sha,
    append_signal,
    compute_data_hash,
    read_signals,
)
from volpred.indicators.reviews import (  # noqa: E402
    REVIEWS_DIR,
    compute_review,
    read_reviews,
)
from volpred.indicators.supabase_sync import sync_indicator_arena  # noqa: E402

np.random.seed(42)  # all stochastic procedures fixed-seed (rule §5)

ET = ZoneInfo("America/New_York")
TST = ZoneInfo("Asia/Taipei")

CBOE_VIX9D_CSV = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv"
)

# Fixed calendar starts (reproducibility — recorded in inputs_snapshot).
TICKER_STARTS = {
    "SPY": "2013-01-01",      # >=2000 obs for A4f window + HAR-QR expanding train
    "^VIX9D": "2015-01-01",
    "^VIX": "2024-06-01",     # 60d TR median + spike detection only
    "0050.TW": "2025-09-01",  # anchor + review lookups only
    "QQQ": "2015-01-01",
    "GLD": "2015-01-01",
    "TLT": "2015-01-01",
}

A4F_WINDOW = 2000     # k1004 OOS window
A4F_MIN_OBS = 500     # below this the GARCH-X fit is unreliable -> skip
HAR_MIN_OBS = 250     # min obs for HAR / QuantReg fits


class IndicatorSkip(Exception):
    """Raised when an indicator must be skipped today (stale/missing data)."""


# ---------------------------------------------------------------------------
# Session-time helpers (explicit timezones; DST handled by zoneinfo)
# ---------------------------------------------------------------------------

def us_close_utc(d, minute_offset: int = 0) -> datetime:
    """US equity close 16:00 ET on date d, in UTC."""
    dt = datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET)
    return (dt + timedelta(minutes=minute_offset)).astimezone(timezone.utc)


def us_index_close_utc(d) -> datetime:
    """CBOE index (VIX family) settlement 16:15 ET, in UTC."""
    return us_close_utc(d, minute_offset=15)


def us_open_utc(d) -> datetime:
    dt = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
    return dt.astimezone(timezone.utc)


def tw_close_utc(d) -> datetime:
    dt = datetime(d.year, d.month, d.day, 13, 30, tzinfo=TST)
    return dt.astimezone(timezone.utc)


def tw_open_utc(d) -> datetime:
    dt = datetime(d.year, d.month, d.day, 9, 0, tzinfo=TST)
    return dt.astimezone(timezone.utc)


def next_bday(d, n: int = 1):
    """Next business day (Mon-Fri). Exchange holidays are approximated; review
    resolution anchors on actual data rows, so a holiday shift only moves the
    label, never the realized outcome used."""
    return (pd.Timestamp(d) + pd.tseries.offsets.BDay(n)).date()


def session_close_utc(ticker: str, d) -> datetime:
    if ticker.endswith(".TW"):
        return tw_close_utc(d)
    if ticker.startswith("^VIX"):
        return us_index_close_utc(d)
    return us_close_utc(d)


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

LOCAL_PRICE_CACHE_DB = PROJECT_ROOT / "data" / "cache" / "price_cache.db"


def _local_cache_closes(ticker: str, start: str) -> pd.Series | None:
    """Adj-closes from the project's own daily collection cache
    (data/cache/price_cache.db, filled by cron_collect_us/tw at 07:03/15:00).

    These are real recorded closes captured at collection time — used to fill
    holes when Yahoo's live daily feed drops a completed session (observed
    2026-06-11: SPY/^VIX 06-10 rows NaN/missing on Yahoo while the 07:03
    collection had them). Never fabricated values.
    """
    if not LOCAL_PRICE_CACHE_DB.exists():
        return None
    import sqlite3

    try:
        con = sqlite3.connect(LOCAL_PRICE_CACHE_DB)
        try:
            df = pd.read_sql(
                "SELECT date, adj_close FROM price_data "
                "WHERE ticker = ? AND date >= ? ORDER BY date",
                con,
                params=(ticker, start or "1900-01-01"),
            )
        finally:
            con.close()
    except Exception:
        return None
    if df.empty:
        return None
    s = pd.Series(
        df["adj_close"].astype(float).values,
        index=pd.DatetimeIndex(pd.to_datetime(df["date"])).normalize(),
    )
    return s.dropna().sort_index()


def yf_fetch(ticker: str, start: str) -> pd.Series:
    """Fetch daily auto-adjusted closes from yfinance, gap-filled from the
    local collection cache. Raises if both sources are unavailable."""
    import yfinance as yf

    s = None
    try:
        df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            col = df["Close"]
            if isinstance(col, pd.DataFrame):
                col = col.iloc[:, 0]
            col = col.dropna().astype(float)
            idx = pd.to_datetime(col.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            col.index = idx.normalize()
            s = col.sort_index()
    except Exception:
        s = None

    cached = _local_cache_closes(ticker, start)
    if s is None and cached is None:
        raise RuntimeError(f"No data for {ticker}: yfinance empty and no local cache")
    if s is None:
        return cached
    if cached is None:
        return s
    # yfinance live data takes precedence; cache fills dropped sessions.
    return s.combine_first(cached).sort_index()


def fetch_cboe_vix9d() -> pd.Series:
    """Fallback: CBOE official VIX9D daily CSV (free, daily-updated)."""
    with urllib.request.urlopen(CBOE_VIX9D_CSV, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(raw))
    date_col = "DATE" if "DATE" in df.columns else df.columns[0]
    close_col = "CLOSE" if "CLOSE" in df.columns else df.columns[-1]
    s = pd.Series(
        df[close_col].astype(float).values,
        index=pd.DatetimeIndex(pd.to_datetime(df[date_col])).normalize(),
    )
    return s.dropna().sort_index()


class MarketData:
    """Per-run cache of completed daily closes. fetch_fn is injectable (tests)."""

    def __init__(self, fetch_fn: Callable[[str, str], pd.Series], now_utc: datetime):
        self.fetch_fn = fetch_fn
        self.now = now_utc
        self._cache: dict[str, Any] = {}

    def _completed_only(self, ticker: str, s: pd.Series) -> pd.Series:
        """Drop in-progress sessions: keep rows whose session close <= now.

        This is the lookahead guard at the data layer — an unfinished bar
        (design doc §6 實測紀錄 (a)) can never enter a signal.
        """
        keep = [d for d in s.index if session_close_utc(ticker, d.date()) <= self.now]
        return s.loc[keep]

    def closes(self, ticker: str) -> pd.Series:
        if ticker in self._cache:
            cached = self._cache[ticker]
            if isinstance(cached, Exception):
                raise cached
            return cached
        try:
            s = self.fetch_fn(ticker, TICKER_STARTS.get(ticker, "2015-01-01"))
            s = self._completed_only(ticker, s)
            if s.empty:
                raise RuntimeError(f"No completed closes for {ticker}")
            self._cache[ticker] = s
        except Exception as exc:  # cache the failure so we fetch once per run
            self._cache[ticker] = exc
            raise
        return s

    def vix9d(self, required_through_date) -> tuple[pd.Series, str]:
        """^VIX9D closes, guaranteed fresh through required_through_date.

        yfinance first; if stale (known 1-2 day lag), merge CBOE CSV fallback.
        Still stale -> IndicatorSkip (§4.5: never substitute stale values).
        """
        s = self.closes("^VIX9D")
        if s.index[-1].date() >= required_through_date:
            return s, "yfinance"
        merged = self._cache.get("__VIX9D_MERGED__")
        if merged is None:
            fb = None
            if self.fetch_fn is not yf_fetch:  # test hook for injected fetchers
                try:
                    fb = self.fetch_fn("__CBOE_VIX9D__", "")
                except Exception:
                    fb = None
            if fb is None:
                try:
                    fb = fetch_cboe_vix9d()
                except Exception as exc:
                    raise IndicatorSkip(
                        f"^VIX9D stale (last={s.index[-1].date()}, need "
                        f"{required_through_date}) and CBOE fallback failed: {exc}"
                    ) from exc
            fb = self._completed_only("^VIX9D", fb)
            merged = fb.combine_first(s).sort_index()
            self._cache["__VIX9D_MERGED__"] = merged
        if merged.index[-1].date() >= required_through_date:
            return merged, "yfinance+cboe_fallback"
        raise IndicatorSkip(
            f"^VIX9D stale even after CBOE fallback "
            f"(last={merged.index[-1].date()}, need {required_through_date})"
        )


# ---------------------------------------------------------------------------
# A4f GARCH-X (Student-t) — exact replica of experiments/k1004/k1004.py
# ---------------------------------------------------------------------------

try:  # numba optional: identical numerics either way, just slower without
    from numba import njit
except Exception:  # pragma: no cover
    def njit(fn):
        return fn


@njit
def _t_logpdf_sum(returns, h, df):
    T = len(returns)
    scale_factor = np.sqrt((df - 2.0) / df)
    c = (
        math.lgamma((df + 1.0) / 2.0)
        - math.lgamma(df / 2.0)
        - 0.5 * np.log(np.pi * df)
    )
    ll = 0.0
    for t in range(T):
        sigma = np.sqrt(h[t])
        s = sigma * scale_factor
        z = returns[t] / s
        ll += c - np.log(s) - (df + 1.0) / 2.0 * np.log(1.0 + z * z / df)
    return ll


@njit
def _a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * vix2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix2[t - 1]
        if tau[t] < 1e-16:
            tau[t] = 1e-16
        u_prev = returns[t - 1] / np.sqrt(tau[t])
        u2 = u_prev**2
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t - 1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g


@njit
def _a4f_nll_normal(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    h, _, _ = _a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t] ** 2 / h[t]
    return 0.5 * ll


def _fit_a4f_normal(returns, vix2):
    from scipy.optimize import minimize

    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]

    def obj(p):
        if p[3] + 0.5 * p[4] + p[5] >= 1.0:
            return 1e10
        try:
            v = _a4f_nll_normal(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10

    best_res, best_nll = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, omega_init, 0.04, 0.06, 0.90]
            try:
                res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        x0 = [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]
        best_res = minimize(obj, x0, method="L-BFGS-B", bounds=bounds)
    return best_res


def fit_a4f_t_joint(returns: np.ndarray, vix2: np.ndarray) -> dict[str, Any]:
    """A4f-VIX9D-t joint MLE — same multistart scheme as k1004 fit_a4f_t_joint."""
    from scipy.optimize import minimize

    res_n = _fit_a4f_normal(returns, vix2)
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]

    def obj(p):
        if p[3] + 0.5 * p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = _a4f_recursion(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            ll = _t_logpdf_sum(returns, h, p[6])
            return -ll if np.isfinite(ll) else 1e10
        except Exception:
            return 1e10

    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        p0 = list(res_n.x) + [df_init]
        try:
            res = minimize(obj, p0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except Exception:
            continue
    if best_res is None:
        raise RuntimeError("A4f-t MLE failed to converge from all starts")
    h, tau, g = _a4f_recursion(
        best_res.x[0], best_res.x[1], best_res.x[2], best_res.x[3],
        best_res.x[4], best_res.x[5], returns, vix2,
    )
    return {
        "params": best_res.x,
        "h": h,
        "g": g,
        "converged": bool(best_res.success),
        "nll": float(best_res.fun),
        "df": float(best_res.x[6]),
    }


# ---------------------------------------------------------------------------
# Signal builders — one per indicator_id; each returns a draft payload dict
# (with "_raw_inputs" popped into data_hash by the caller) or raises
# IndicatorSkip / any Exception (recorded as failure).
# ---------------------------------------------------------------------------

def _series_snapshot(s: pd.Series, tail: int) -> dict[str, float]:
    """date->close map of the tail actually feeding the signal (for data_hash)."""
    t = s.iloc[-tail:]
    return {str(d.date()): round(float(v), 8) for d, v in t.items()}


def build_us_tw_overnight_lead(mkt: MarketData, now: datetime, spec) -> dict[str, Any]:
    spy = mkt.closes("SPY")
    if len(spy) < 2:
        raise IndicatorSkip("SPY: <2 completed closes")
    basis = spy.index[-1].date()  # last completed US session = t-1
    spy_ret = float(spy.iloc[-1] / spy.iloc[-2] - 1.0)
    target = next_bday(basis)  # next TW trading day (approx; resolution anchors on data)

    tw = mkt.closes("0050.TW")
    tw_before = tw[[d.date() < target for d in tw.index]]
    if tw_before.empty:
        raise IndicatorSkip("0050.TW: no completed close before target date")
    tw_prev_date = tw_before.index[-1].date()

    direction = "up" if spy_ret > 0 else "down"
    as_of = us_close_utc(basis)
    return {
        "signal_id": f"{spec.indicator_id}:{target}",
        "as_of_ts": as_of.isoformat(),
        "target_date": str(target),
        "prediction": {"direction": direction},
        "horizon_days": 1,
        "expires_at": tw_close_utc(target).isoformat(),
        "resolve_after": (tw_close_utc(target) + timedelta(minutes=150)).isoformat(),
        "indicator_value": spy_ret,
        "late": now > tw_open_utc(target),
        "league": spec.league,
        "inputs_snapshot": {
            "rule": "SPY t-1 close-to-close return > 0 -> 0050.TW up at t, else down",
            "spy_basis_date": str(basis),
            "spy_close_t1": round(float(spy.iloc[-1]), 6),
            "spy_close_t2": round(float(spy.iloc[-2]), 6),
            "spy_ret_t1": round(spy_ret, 8),
            "tw_prev_close_date": str(tw_prev_date),
            "price_basis": "yfinance auto_adjust=True daily close",
        },
        "_raw_inputs": {"SPY": _series_snapshot(spy, 2), "0050.TW_anchor": str(tw_prev_date)},
    }


def build_vix_term_structure(mkt: MarketData, now: datetime, spec) -> dict[str, Any]:
    spy = mkt.closes("SPY")
    vix = mkt.closes("^VIX")
    basis = spy.index[-1].date()
    if vix.index[-1].date() != basis:
        raise IndicatorSkip(
            f"^VIX stale (last={vix.index[-1].date()}, SPY basis={basis})"
        )
    vix9d, vix9d_src = mkt.vix9d(required_through_date=basis)

    joint = pd.DataFrame({"vix9d": vix9d, "vix": vix}).dropna()
    joint = joint[[d.date() <= basis for d in joint.index]]
    tr = np.log(joint["vix9d"] / joint["vix"])
    if len(tr) < 60:
        raise IndicatorSkip(f"TR series too short for 60d median (n={len(tr)})")
    tr_last = float(tr.iloc[-1])
    med60 = float(tr.iloc[-60:].median())
    direction = "up" if tr_last > med60 else "down"

    # prev-5d RV (K1415 proxy: r^2 * 252, mean over window)
    rets = np.log(spy / spy.shift(1)).dropna()
    if len(rets) < 5:
        raise IndicatorSkip("SPY: <5 returns for prev-5d RV")
    rv_prev5 = float((rets.iloc[-5:] ** 2 * 252.0).mean())

    target = next_bday(basis, 5)
    as_of = us_index_close_utc(basis)
    return {
        "signal_id": f"{spec.indicator_id}:{target}",
        "as_of_ts": as_of.isoformat(),
        "target_date": str(target),
        "prediction": {
            "direction": direction,
            "meaning": "up = SPY next-5d RV > prev-5d RV (RV proxy r^2*252, 5d mean)",
        },
        "horizon_days": 5,
        "expires_at": us_close_utc(target).isoformat(),
        "resolve_after": (us_close_utc(target) + timedelta(hours=2)).isoformat(),
        "indicator_value": tr_last,
        "late": now > us_open_utc(next_bday(basis)),
        "league": spec.league,
        "inputs_snapshot": {
            "rule": "log(VIX9D_{t-1}/VIX_{t-1}) > rolling 60d median -> next-5d RV up",
            "basis_date": str(basis),
            "tr_last": round(tr_last, 8),
            "tr_median_60d": round(med60, 8),
            "rv_prev5": round(rv_prev5, 10),
            "vix9d_close": round(float(joint["vix9d"].iloc[-1]), 4),
            "vix_close": round(float(joint["vix"].iloc[-1]), 4),
            "vix9d_source": vix9d_src,
            "rv_proxy": "daily r^2 * 252 (log returns), 5d mean (K1415)",
        },
        "_raw_inputs": {
            "TR_window": {str(d.date()): round(float(v), 8) for d, v in tr.iloc[-60:].items()},
            "SPY_prev5": _series_snapshot(spy, 6),
        },
    }


def build_garch_vix9d_var(mkt: MarketData, now: datetime, spec) -> dict[str, Any]:
    from scipy.stats import t as t_dist

    spy = mkt.closes("SPY")
    basis = spy.index[-1].date()
    vix9d, vix9d_src = mkt.vix9d(required_through_date=basis)

    df = pd.DataFrame({"close": spy, "vix9d": vix9d}).dropna()
    df = df[[d.date() <= basis for d in df.index]]
    df["ret"] = np.log(df["close"] / df["close"].shift(1))
    df = df.dropna()
    df["ret"] = df["ret"].clip(-0.20, 0.20)  # k1004 convention
    df["vix9d2"] = (df["vix9d"] / 100.0) ** 2
    if len(df) < A4F_MIN_OBS:
        raise IndicatorSkip(f"A4f: insufficient joint obs (n={len(df)} < {A4F_MIN_OBS})")
    if df.index[-1].date() != basis:
        raise IndicatorSkip("A4f: joint SPY/VIX9D series does not reach basis date")

    window = df.iloc[-A4F_WINDOW:]
    returns = window["ret"].values
    vix2 = window["vix9d2"].values
    fit = fit_a4f_t_joint(returns, vix2)

    p = fit["params"]
    theta0, theta1, omega, alpha, gamma, beta, nu = (
        float(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5]), float(p[6]),
    )
    # One-step-ahead forecast (same indexing as k1004 oos_forecast):
    tau_next = max(theta0 + theta1 * vix2[-1], 1e-16)
    u_prev = returns[-1] / np.sqrt(tau_next)
    ind = 1.0 if returns[-1] < 0 else 0.0
    g_next = max(omega + alpha * u_prev**2 + gamma * u_prev**2 * ind + beta * fit["g"][-1], 1e-16)
    h_next = tau_next * g_next
    sigma_next = float(np.sqrt(h_next))
    alpha_var = 0.025
    var_q = float(sigma_next * t_dist.ppf(alpha_var, nu) * np.sqrt((nu - 2.0) / nu))

    target = next_bday(basis)
    as_of = us_close_utc(basis)
    return {
        "signal_id": f"{spec.indicator_id}:{target}",
        "as_of_ts": as_of.isoformat(),
        "target_date": str(target),
        "prediction": {
            "var_2_5pct": round(var_q, 8),
            "alpha": alpha_var,
            "unit": "1-day log return (decimal)",
        },
        "horizon_days": 1,
        "expires_at": us_close_utc(target).isoformat(),
        "resolve_after": (us_close_utc(target) + timedelta(hours=2)).isoformat(),
        "indicator_value": round(var_q, 8),
        "late": now > us_open_utc(target),
        "league": spec.league,
        "inputs_snapshot": {
            "rule": "A4f-VIX9D-t GARCH-X (k1004 spec) daily refit, 1-step 2.5% VaR",
            "basis_date": str(basis),
            "fit_window": int(len(window)),
            "fit_window_start": str(window.index[0].date()),
            "params": {
                "theta0": theta0, "theta1": theta1, "omega": omega,
                "alpha": alpha, "gamma": gamma, "beta": beta, "nu": nu,
            },
            "converged": fit["converged"],
            "sigma_next": round(sigma_next, 8),
            "vix9d_close": round(float(window["vix9d"].iloc[-1]), 4),
            "vix9d_source": vix9d_src,
            "ret_clip": 0.20,
        },
        "_raw_inputs": {
            "SPY_window": _series_snapshot(window["close"], len(window)),
            "VIX9D_window": _series_snapshot(window["vix9d"], len(window)),
        },
    }


def build_har_qr_var(mkt: MarketData, now: datetime, spec) -> dict[str, Any]:
    import statsmodels.api as sm
    from statsmodels.regression.quantile_regression import QuantReg

    spy = mkt.closes("SPY")
    basis = spy.index[-1].date()
    ret = np.log(spy / spy.shift(1)).dropna()
    rv = ret**2  # K1313: daily squared log return as RV proxy
    panel = pd.DataFrame({
        "ret": ret,
        "sv_d": np.sqrt(rv.shift(1).clip(lower=0)),
        "sv_w": np.sqrt(rv.shift(1).rolling(5).mean().clip(lower=0)),
        "sv_m": np.sqrt(rv.shift(1).rolling(22).mean().clip(lower=0)),
    }).dropna()
    if len(panel) < HAR_MIN_OBS:
        raise IndicatorSkip(f"HAR-QR: insufficient obs (n={len(panel)})")

    tau = 0.05
    X = sm.add_constant(panel[["sv_d", "sv_w", "sv_m"]])
    qr = QuantReg(panel["ret"].values, X).fit(q=tau, max_iter=2000)
    coefs = np.asarray(qr.params, dtype=float)

    # Predictors for target day t use rv through basis (= t-1): explicit lag.
    sv_d_new = float(np.sqrt(max(float(rv.iloc[-1]), 0.0)))
    sv_w_new = float(np.sqrt(max(float(rv.iloc[-5:].mean()), 0.0)))
    sv_m_new = float(np.sqrt(max(float(rv.iloc[-22:].mean()), 0.0)))
    var_q = float(coefs[0] + coefs[1] * sv_d_new + coefs[2] * sv_w_new + coefs[3] * sv_m_new)

    target = next_bday(basis)
    as_of = us_close_utc(basis)
    return {
        "signal_id": f"{spec.indicator_id}:{target}",
        "as_of_ts": as_of.isoformat(),
        "target_date": str(target),
        "prediction": {
            "var_5pct": round(var_q, 8),
            "alpha": tau,
            "unit": "1-day log return (decimal)",
        },
        "horizon_days": 1,
        "expires_at": us_close_utc(target).isoformat(),
        "resolve_after": (us_close_utc(target) + timedelta(hours=2)).isoformat(),
        "indicator_value": round(var_q, 8),
        "late": now > us_open_utc(target),
        "league": spec.league,
        "inputs_snapshot": {
            "rule": "HAR-QR tau=0.05 on raw returns (K1313 spec), daily refit",
            "basis_date": str(basis),
            "train_start": str(panel.index[0].date()),
            "n_train": int(len(panel)),
            "coefs": {"const": coefs[0], "sv_d": coefs[1], "sv_w": coefs[2], "sv_m": coefs[3]},
            "x_new": {"sv_d": sv_d_new, "sv_w": sv_w_new, "sv_m": sv_m_new},
        },
        "_raw_inputs": {"SPY_train": _series_snapshot(spy, len(panel) + 23)},
    }


def build_vix_crisis_alert(mkt: MarketData, now: datetime, spec) -> dict[str, Any]:
    vix = mkt.closes("^VIX")
    if len(vix) < 2:
        raise IndicatorSkip("^VIX: <2 completed closes")
    basis = vix.index[-1].date()
    vix_last = float(vix.iloc[-1])
    vix_prev = float(vix.iloc[-2])
    vix_chg = vix_last / vix_prev - 1.0
    spike = vix_chg > 0.10
    level = vix_last > 25.0
    risk = bool(spike or level)
    target = next_bday(basis)

    tw = mkt.closes("0050.TW")
    tw_before = tw[[d.date() < target for d in tw.index]]
    if tw_before.empty:
        raise IndicatorSkip("0050.TW: no completed close before target date")
    tw_prev_date = tw_before.index[-1].date()

    direction = "down" if risk else "up"
    as_of = us_index_close_utc(basis)
    return {
        "signal_id": f"{spec.indicator_id}:{target}",
        "as_of_ts": as_of.isoformat(),
        "target_date": str(target),
        "prediction": {
            "direction": direction,
            "risk_light": "risk" if risk else "normal",
            "note": "'up' encodes the rule's 'not-down (>=0)' prediction; "
                    "review scores hit as actual_return > 0",
        },
        "horizon_days": 1,
        "expires_at": tw_close_utc(target).isoformat(),
        "resolve_after": (tw_close_utc(target) + timedelta(minutes=150)).isoformat(),
        "indicator_value": vix_last,
        "late": now > tw_open_utc(target),
        "league": spec.league,
        "inputs_snapshot": {
            "rule": "VIX t-1 day-change > +10% OR VIX t-1 > 25 -> risk light -> 0050.TW down",
            "basis_date": str(basis),
            "vix_close_t1": round(vix_last, 4),
            "vix_close_t2": round(vix_prev, 4),
            "vix_change_pct": round(vix_chg * 100.0, 4),
            "spike_trigger": spike,
            "level_trigger": level,
            "tw_prev_close_date": str(tw_prev_date),
        },
        "_raw_inputs": {"^VIX": _series_snapshot(vix, 2), "0050.TW_anchor": str(tw_prev_date)},
    }


Q95_ASSETS = ("QQQ", "GLD", "TLT")


def build_har_q95(mkt: MarketData, now: datetime, spec) -> dict[str, Any]:
    import statsmodels.api as sm
    from statsmodels.regression.quantile_regression import QuantReg

    series = {a: mkt.closes(a) for a in Q95_ASSETS}
    basis = min(s.index[-1].date() for s in series.values())

    q95: dict[str, float] = {}
    snap: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for asset, px in series.items():
        px = px[[d.date() <= basis for d in px.index]]
        ret_pct = (np.log(px) - np.log(px.shift(1))) * 100.0  # K1403 convention
        daily_rv = ret_pct.abs()
        panel = pd.DataFrame({
            "daily_rv": daily_rv,
            "rv_d": daily_rv.shift(1),
            "rv_w": daily_rv.rolling(5).mean().shift(1),
            "rv_m": daily_rv.rolling(22).mean().shift(1),
        }).dropna()
        if len(panel) < HAR_MIN_OBS:
            raise IndicatorSkip(f"q95 {asset}: insufficient obs (n={len(panel)})")
        X = sm.add_constant(panel[["rv_d", "rv_w", "rv_m"]])
        qr = QuantReg(panel["daily_rv"].values, X).fit(q=0.95, max_iter=5000)
        c = np.asarray(qr.params, dtype=float)
        x_new = np.array([
            1.0,
            float(daily_rv.iloc[-1]),
            float(daily_rv.iloc[-5:].mean()),
            float(daily_rv.iloc[-22:].mean()),
        ])
        q95[asset] = round(float(c @ x_new), 6)
        snap[asset] = {
            "coefs": {"const": c[0], "rv_d": c[1], "rv_w": c[2], "rv_m": c[3]},
            "x_new": {"rv_d": x_new[1], "rv_w": x_new[2], "rv_m": x_new[3]},
            "n_train": int(len(panel)),
            "train_start": str(panel.index[0].date()),
        }
        raw[asset] = _series_snapshot(px, 30)

    target = next_bday(basis)
    as_of = us_close_utc(basis)
    return {
        "signal_id": f"{spec.indicator_id}:{target}",
        "as_of_ts": as_of.isoformat(),
        "target_date": str(target),
        "prediction": {
            "q95_upper": q95,
            "alpha": 0.05,
            "unit": "abs 1-day log return x100 (%) — K1403 daily RV proxy",
            "per_asset_expected_violation": 0.05,
        },
        "horizon_days": 1,
        "expires_at": us_close_utc(target).isoformat(),
        "resolve_after": (us_close_utc(target) + timedelta(hours=2)).isoformat(),
        "indicator_value": q95["QQQ"],
        "late": now > us_open_utc(target),
        "league": spec.league,
        "inputs_snapshot": {
            "rule": "HAR-RV QuantReg q95 upper bound on |ret%| per asset (K1403 spec)",
            "basis_date": str(basis),
            "per_asset": snap,
            "joint_review_rule": "review hit=True iff ALL 3 assets within bound "
                                 "(joint expected pass ~0.857); per-asset violations "
                                 "recorded in realized.per_asset for calibration scoring",
        },
        "_raw_inputs": raw,
    }


BUILDERS: dict[str, Callable[[MarketData, datetime, Any], dict[str, Any]]] = {
    "us_tw_overnight_lead": build_us_tw_overnight_lead,
    "vix_term_structure_vol_direction": build_vix_term_structure,
    "garch_vix9d_spy_var25": build_garch_vix9d_var,
    "har_qr_spy_var5": build_har_qr_var,
    "vix_crisis_alert_tw": build_vix_crisis_alert,
    "har_qr_rv_q95_qqq_gld_tlt": build_har_q95,
}


# ---------------------------------------------------------------------------
# Review resolvers — realized outcomes for due signals (ex-post data only)
# ---------------------------------------------------------------------------

def _first_return_after(px: pd.Series, anchor_date) -> tuple[Any, float, float] | None:
    """(resolved_date, simple_return, log_return) of the first completed
    session strictly after anchor_date. None if not yet available."""
    before = px[[d.date() <= anchor_date for d in px.index]]
    after = px[[d.date() > anchor_date for d in px.index]]
    if before.empty or after.empty:
        return None
    prev = float(before.iloc[-1])
    cur = float(after.iloc[0])
    return after.index[0].date(), cur / prev - 1.0, math.log(cur / prev)


def resolve_signal(sig: dict[str, Any], mkt: MarketData) -> dict[str, Any] | None:
    ind = sig.get("indicator_id", "")
    snap = sig.get("inputs_snapshot", {}) or {}
    pred = sig.get("prediction", {}) or {}

    if ind in ("us_tw_overnight_lead", "vix_crisis_alert_tw"):
        anchor = snap.get("tw_prev_close_date")
        if not anchor:
            return None
        tw = mkt.closes("0050.TW")
        out = _first_return_after(tw, pd.Timestamp(anchor).date())
        if out is None:
            return None
        resolved_date, simple_ret, _ = out
        return {
            "actual_return": round(simple_ret, 8),
            "return_type": "simple close-to-close (yfinance auto-adjusted)",
            "resolved_date": str(resolved_date),
            "prev_close_date": anchor,
        }

    if ind == "vix_term_structure_vol_direction":
        basis = snap.get("basis_date")
        if not basis:
            return None
        spy = mkt.closes("SPY")
        rets = np.log(spy / spy.shift(1)).dropna()
        prev_mask = [d.date() <= pd.Timestamp(basis).date() for d in rets.index]
        next_mask = [d.date() > pd.Timestamp(basis).date() for d in rets.index]
        prev_rets = rets[prev_mask]
        next_rets = rets[next_mask]
        if len(next_rets) < 5 or len(prev_rets) < 5:
            return None
        rv_prev5 = float((prev_rets.iloc[-5:] ** 2 * 252.0).mean())
        rv_next5 = float((next_rets.iloc[:5] ** 2 * 252.0).mean())
        return {
            "actual_return": round(rv_next5 - rv_prev5, 10),
            "rv_next5": round(rv_next5, 10),
            "rv_prev5": round(rv_prev5, 10),
            "next5_dates": [str(d.date()) for d in next_rets.index[:5]],
            "unit": "annualized variance proxy (r^2*252, 5d mean); "
                    "actual_return = rv_next5 - rv_prev5 for direction scoring",
        }

    if ind in ("garch_vix9d_spy_var25", "har_qr_spy_var5"):
        basis = snap.get("basis_date")
        threshold = pred.get("var_2_5pct") if ind == "garch_vix9d_spy_var25" else pred.get("var_5pct")
        if not basis or threshold is None:
            return None
        spy = mkt.closes("SPY")
        out = _first_return_after(spy, pd.Timestamp(basis).date())
        if out is None:
            return None
        resolved_date, _, log_ret = out
        return {
            "actual_value": round(log_ret, 8),
            "threshold": float(threshold),
            "resolved_date": str(resolved_date),
            "violation": bool(log_ret <= float(threshold)),
            "unit": "1-day log return (decimal)",
        }

    if ind == "har_qr_rv_q95_qqq_gld_tlt":
        basis = snap.get("basis_date")
        bounds = pred.get("q95_upper") or {}
        if not basis or not bounds:
            return None
        per_asset: dict[str, Any] = {}
        margins: list[float] = []
        for asset in Q95_ASSETS:
            bound = bounds.get(asset)
            if bound is None:
                return None
            px = mkt.closes(asset)
            out = _first_return_after(px, pd.Timestamp(basis).date())
            if out is None:
                return None
            resolved_date, _, log_ret = out
            actual_rv = abs(log_ret) * 100.0
            per_asset[asset] = {
                "actual_rv": round(actual_rv, 6),
                "q95_upper": float(bound),
                "violation": bool(actual_rv > float(bound)),
                "resolved_date": str(resolved_date),
            }
            margins.append(float(bound) - actual_rv)
        return {
            "per_asset": per_asset,
            "actual_value": round(min(margins), 6),
            "threshold": 0.0,
            "n_violations": sum(1 for a in per_asset.values() if a["violation"]),
            "joint_rule": "hit=True iff all 3 assets within q95 (joint expected ~0.857); "
                          "per-asset calibration uses per_asset[*].violation",
            "unit": "abs 1-day log return x100 (%)",
        }

    return None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _load_all_signals(signals_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if signals_dir.exists():
        for f in sorted(signals_dir.glob("*.jsonl")):
            rows.extend(read_signals(f.stem, signals_dir))
    return rows


def _load_reviewed_ids(reviews_dir: Path) -> set[str]:
    ids: set[str] = set()
    if reviews_dir.exists():
        for f in sorted(reviews_dir.glob("*.jsonl")):
            for row in read_reviews(f.stem, reviews_dir):
                ids.add(row.get("signal_id", ""))
    return ids


def run_pipeline(
    now_utc: datetime | None = None,
    fetch_fn: Callable[[str, str], pd.Series] | None = None,
    signals_dir: Path | None = None,
    reviews_dir: Path | None = None,
    registry_path: Path | None = None,
    do_sync: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)
    sig_dir = signals_dir or SIGNALS_DIR
    rev_dir = reviews_dir or REVIEWS_DIR
    code_version = _get_git_short_sha()

    specs = [s for s in load_registry(registry_path) if s.status != "delisted"]
    existing = {row.get("signal_id") for row in _load_all_signals(sig_dir)}
    mkt = MarketData(fetch_fn or yf_fetch, now)

    emitted: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    # --- Phase 1: emit signals ---
    for spec in specs:
        builder = BUILDERS.get(spec.indicator_id)
        if builder is None:
            failed.append({"indicator_id": spec.indicator_id, "error": "no builder registered"})
            continue
        try:
            draft = builder(mkt, now, spec)
            if draft["signal_id"] in existing:
                skipped.append({
                    "indicator_id": spec.indicator_id,
                    "reason": f"duplicate (signal {draft['signal_id']} already emitted)",
                    "kind": "duplicate",
                })
                continue
            raw_inputs = draft.pop("_raw_inputs", {})
            payload = {
                **draft,
                "indicator_id": spec.indicator_id,
                "emitted_at": now.isoformat(),
                "published_at": now.isoformat(),
                "data_hash": compute_data_hash(raw_inputs),
                "code_version": code_version,
            }
            if not dry_run:
                append_signal(spec.indicator_id, payload, signals_dir=sig_dir)
            existing.add(payload["signal_id"])
            emitted.append({
                "indicator_id": spec.indicator_id,
                "signal_id": payload["signal_id"],
                "target_date": payload.get("target_date"),
                "indicator_value": payload.get("indicator_value"),
                "prediction": payload.get("prediction"),
                "as_of_ts": payload.get("as_of_ts"),
                "late": payload.get("late", False),
            })
        except IndicatorSkip as exc:
            skipped.append({
                "indicator_id": spec.indicator_id,
                "reason": str(exc),
                "kind": "data_unavailable",
            })
        except Exception as exc:
            failed.append({
                "indicator_id": spec.indicator_id,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=5),
            })

    # --- Phase 2: resolve due reviews ---
    reviews_done: list[dict[str, Any]] = []
    review_failures: list[dict[str, str]] = []
    reviewed_ids = _load_reviewed_ids(rev_dir)
    for sig in _load_all_signals(sig_dir):
        sid = sig.get("signal_id", "")
        if not sid or sid in reviewed_ids:
            continue
        resolve_after = sig.get("resolve_after")
        if resolve_after:
            try:
                if now < datetime.fromisoformat(resolve_after.replace("Z", "+00:00")):
                    continue
            except (ValueError, TypeError):
                pass
        try:
            realized = resolve_signal(sig, mkt)
        except Exception as exc:
            review_failures.append({"signal_id": sid, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if realized is None:
            continue  # outcome data not yet available — stays pending
        if dry_run:
            reviews_done.append({"signal_id": sid, "dry_run": True})
            continue
        try:
            res = compute_review(
                sig, realized, reviews_dir=rev_dir,
                data_source_asof=now.isoformat(),
            )
            reviewed_ids.add(sid)
            reviews_done.append({
                "signal_id": sid,
                "indicator_id": sig.get("indicator_id"),
                "hit": res.hit,
                "econ_value_bps": res.econ_value_bps,
            })
        except Exception as exc:
            review_failures.append({"signal_id": sid, "error": f"{type(exc).__name__}: {exc}"})

    # --- Phase 3: Supabase sync ---
    sync_summary: dict[str, Any] | None = None
    if do_sync and not dry_run:
        try:
            sync_summary = sync_indicator_arena()
        except Exception as exc:
            sync_summary = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    data_skips = [s for s in skipped if s.get("kind") != "duplicate"]
    ok = (
        not failed
        and not data_skips
        and not review_failures
        and (sync_summary is None or sync_summary.get("ok", False))
    )
    return {
        "ok": ok,
        "now_utc": now.isoformat(),
        "code_version": code_version,
        "emitted": emitted,
        "skipped": skipped,
        "failed": failed,
        "reviews_done": reviews_done,
        "review_failures": review_failures,
        "sync": sync_summary,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Indicator Arena daily pipeline")
    parser.add_argument("--dry-run", action="store_true", help="compute but do not write/sync")
    parser.add_argument("--no-sync", action="store_true", help="skip Supabase sync")
    args = parser.parse_args(argv)

    result = run_pipeline(do_sync=not args.no_sync, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
