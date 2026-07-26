#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
K1658 — FOMC statement shock (14:00 ET) vs press-conference shock (14:30 ET):
distributional response decomposition for rate assets (TLT / IEF / ZN=F).

RESEARCH QUESTION
-----------------
Within a single FOMC decision day, the statement release (14:00 ET) and the
press conference (14:30 ET) are two temporally separable information events.
Do they have *different* effects on the next-day (t+1) realised volatility of
rate assets, and is that difference statistically significant?

CORE FINDING (established by Part 1)
------------------------------------
Separating the two shocks requires INTRADAY prices at <=15-min resolution that
straddle 14:00 and 14:30 ET, over a sample of many FOMC days. The only free
intraday source available in this repo (yfinance) has a HARD ~60-trading-day
lookback cap for sub-hourly bars. FOMC meets 8x/year, so the intraday window
contains only N=2 usable events (TLT/IEF) / N=1 (ZN=F). Cross-event inferential
separation of the two shocks is therefore INFEASIBLE with free data. This is
reported honestly as the primary result (see brief: "若無法真正分離兩個 shock
窗，如實回報 NULL / infeasible").

WHAT IS STILL FEASIBLE AND REAL
-------------------------------
  Part 2 — Intraday CASE STUDIES (N<=2, descriptive only, no test): for the
           events that DO have intraday coverage, we cleanly measure the
           statement-window and presser-window returns + within-window realised
           variance, plus the next-day realised volatility. Descriptive only.
  Part 3 — AGGREGATE FOMC-day effect on t+1 daily volatility (LONG daily
           sample, formal HAC-robust test + Holm multiple-testing correction).
           This measures the COMBINED (statement+presser) effect and CANNOT
           separate the two shocks; it is included as a lookahead-clean,
           testable context baseline and to satisfy the CONDITIONAL_PASS bar.

LOOKAHEAD POLICY (fixed a priori)
---------------------------------
  * Part 3 regression: outcome = log RV on day t; predictors = FOMC dummy and
    control, both taken from day t-1 via explicit `.shift(1)`. i.e. we test
    whether an FOMC announcement on day t-1 elevates volatility on day t
    (= the day AFTER the event). No same-day signal x same-day return.
  * Part 2 next-day RV is strictly the session AFTER the event day.
  * seed = 42 fixed for the block bootstrap.
  * Multiple-testing family (3 assets x 2 RV proxies = 6 tests) is fixed in
    code BEFORE looking at p-values; Holm correction applied to the whole family.

Data are cached to experiments/K1658/data/ on first run because yfinance's
60-day intraday window will roll forward and the 2026-04-29 / 2026-06-17 events
will disappear from the API — caching preserves reproducibility (byte-traceable).

Run:  uv run python experiments/K1658/K1658.py [--refresh]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SEED = 42
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

ASSETS = ["TLT", "IEF", "ZN=F"]          # 20Y+ Treasury ETF, 7-10Y ETF, 10Y T-Note future
INTRADAY_INTERVAL = "5m"
INTRADAY_PERIOD = "60d"                    # yfinance hard cap for <1h bars
DAILY_START = "2019-01-01"                 # long daily sample (multi-regime)

# Event-window definitions (ET clock), following the brief's suggestion:
#   statement window : 13:55 -> 14:15 ET  (brackets the 14:00 statement)
#   presser   window : 14:25 -> 15:30 ET  (brackets the 14:30 presser, covers Q&A)
# The 14:15->14:25 gap is deliberately excluded so the two shocks do not overlap.
STMT_WIN = ("13:55", "14:15")
PRESS_WIN = ("14:25", "15:30")

# Scheduled FOMC decision-announcement dates (second day of each two-day meeting),
# 14:00 ET statement + 14:30 ET press conference. Source: federalreserve.gov FOMC
# calendars (2024-2026 verified directly from the Fed calendar page on 2026-07-27;
# 2019-2023 compiled from the Fed calendar and cross-checked against the Fed's
# rate-decision record). Unscheduled 2020 emergency actions (2020-03-03, 2020-03-15)
# are EXCLUDED because they did not follow the standard 14:00/14:30 format
# (2020-03-15 was a Sunday evening announcement).
FOMC_DATES = [
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020 (scheduled; March slot became the 03-15 emergency action -> excluded)
    "2020-01-29", "2020-04-29", "2020-06-10", "2020-07-29",
    "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026 (through data end 2026-07-24; 2026-07-29 excluded, after data)
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
]
FOMC_SET = set(FOMC_DATES)


# ---------------------------------------------------------------------------
# Data loading (with on-disk cache for reproducibility)
# ---------------------------------------------------------------------------
def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    return df


def load_intraday(ticker: str, refresh: bool) -> pd.DataFrame:
    """5-min OHLCV, index tz-converted to America/New_York. Cached to CSV."""
    safe = ticker.replace("=", "_")
    path = os.path.join(DATA_DIR, f"intraday_{safe}_5m.csv")
    if os.path.exists(path) and not refresh:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
        return df
    import yfinance as yf
    raw = yf.download(ticker, period=INTRADAY_PERIOD, interval=INTRADAY_INTERVAL,
                      progress=False, auto_adjust=False)
    raw = _flatten(raw)
    if raw.index.tz is None:
        raw.index = raw.index.tz_localize("UTC")
    raw.index = raw.index.tz_convert("America/New_York")
    raw = raw[["Open", "High", "Low", "Close", "Volume"]]
    # persist as UTC-naive ISO so the cache is stable across machines
    out = raw.copy()
    out.index = out.index.tz_convert("UTC")
    out.to_csv(path)
    return raw


def load_daily(ticker: str, refresh: bool) -> pd.DataFrame:
    """Daily OHLC from DAILY_START. Cached to CSV."""
    safe = ticker.replace("=", "_")
    path = os.path.join(DATA_DIR, f"daily_{safe}.csv")
    if os.path.exists(path) and not refresh:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index)
        return df
    import yfinance as yf
    raw = yf.download(ticker, start=DAILY_START, end="2026-07-25",
                      progress=False, auto_adjust=False)
    raw = _flatten(raw)
    raw = raw[["Open", "High", "Low", "Close"]].dropna()
    raw.to_csv(path)
    return raw


# ---------------------------------------------------------------------------
# Part 1 — Data feasibility diagnosis
# ---------------------------------------------------------------------------
def part1_feasibility(intraday: dict[str, pd.DataFrame]) -> dict:
    diag = {"per_asset": {}, "note": (
        "Intraday sub-hourly bars from yfinance are capped at ~60 trading days. "
        "FOMC meets 8x/year, so only a handful of events fall in-window.")}
    events_any = set()
    for tk, df in intraday.items():
        days = pd.Index(sorted(set(df.index.strftime("%Y-%m-%d"))))
        cover_start, cover_end = days.min(), days.max()
        # an event is "usable" if the day is present AND has bars spanning both
        # the statement and presser windows
        usable = []
        for d in FOMC_DATES:
            if d not in set(days):
                continue
            day = df[df.index.strftime("%Y-%m-%d") == d]
            hm = day.index.strftime("%H:%M")
            has_stmt = ((hm >= STMT_WIN[0]) & (hm <= STMT_WIN[1])).any()
            has_press = ((hm >= PRESS_WIN[0]) & (hm <= PRESS_WIN[1])).any()
            if has_stmt and has_press:
                usable.append(d)
        events_any.update(usable)
        diag["per_asset"][tk] = {
            "intraday_coverage_start": cover_start,
            "intraday_coverage_end": cover_end,
            "n_trading_days": int(len(days)),
            "usable_fomc_events": usable,
            "n_usable_events": len(usable),
        }
    n_events = len(events_any)
    # Power / feasibility gap: paired test (statement vs presser) needs, for a
    # two-sided alpha=0.05, power=0.80, mean-difference effect size d:
    #   N ~= (z_{a/2}+z_b)^2 / d^2  with z_{0.025}=1.960, z_{0.20}=0.8416
    zc = (1.959964 + 0.841621) ** 2
    req = {f"d={d}": math.ceil(zc / d ** 2) for d in (0.3, 0.5, 0.8)}
    years_needed = {k: round(v / 8.0, 2) for k, v in req.items()}  # 8 FOMC/yr
    diag["feasibility"] = {
        "usable_events_any_asset": sorted(events_any),
        "n_usable_events": n_events,
        "paired_test_required_N": req,
        "years_of_complete_intraday_needed": years_needed,
        "free_data_window_years": round(60 / 252, 3),
        "verdict": (
            "INFEASIBLE — cross-event inferential separation of statement vs "
            "presser shock cannot be done with free data: the intraday window "
            f"yields N={n_events} usable FOMC event(s), while even a LARGE "
            f"effect (d=0.8) needs N>={req['d=0.8']} (~{years_needed['d=0.8']} "
            "yr of complete intraday coverage)."),
    }
    return diag


# ---------------------------------------------------------------------------
# Part 2 — Intraday case studies (descriptive, no test)
# ---------------------------------------------------------------------------
def _win_close(day: pd.DataFrame, t: str) -> float:
    """Last close at or before ET clock time t."""
    hm = day.index.strftime("%H:%M")
    sub = day[hm <= t]
    return float(sub["Close"].iloc[-1]) if len(sub) else float("nan")


def _win_rv(day: pd.DataFrame, lo: str, hi: str) -> float:
    """Realised variance = sum of squared 5-min log returns for bars in (lo, hi]."""
    hm = day.index.strftime("%H:%M")
    sub = day[(hm > lo) & (hm <= hi)].copy()
    if len(sub) < 2:
        return float("nan")
    r = np.log(sub["Close"].astype(float)).diff().dropna()
    return float((r ** 2).sum())


def _session_rv(df: pd.DataFrame, date: str) -> float:
    """Full-session realised variance from 5-min bars on `date`."""
    day = df[df.index.strftime("%Y-%m-%d") == date]
    if len(day) < 2:
        return float("nan")
    r = np.log(day["Close"].astype(float)).diff().dropna()
    return float((r ** 2).sum())


def _next_session(df: pd.DataFrame, date: str) -> str | None:
    days = sorted(set(df.index.strftime("%Y-%m-%d")))
    if date not in days:
        return None
    i = days.index(date)
    return days[i + 1] if i + 1 < len(days) else None


def part2_case_studies(intraday: dict[str, pd.DataFrame], usable: list[str]) -> dict:
    out = {"windows_ET": {"statement": STMT_WIN, "presser": PRESS_WIN},
           "events": {}}
    for ev in usable:
        rec = {}
        for tk, df in intraday.items():
            day = df[df.index.strftime("%Y-%m-%d") == ev]
            if len(day) == 0:
                rec[tk] = {"available": False}
                continue
            p1355 = _win_close(day, STMT_WIN[0])
            p1415 = _win_close(day, STMT_WIN[1])
            p1425 = _win_close(day, PRESS_WIN[0])
            p1530 = _win_close(day, PRESS_WIN[1])
            stmt_ret = math.log(p1415 / p1355) if p1355 > 0 and p1415 > 0 else float("nan")
            press_ret = math.log(p1530 / p1425) if p1425 > 0 and p1530 > 0 else float("nan")
            nxt = _next_session(df, ev)
            rec[tk] = {
                "available": True,
                "statement_window_logret": round(stmt_ret, 6),
                "presser_window_logret": round(press_ret, 6),
                "statement_window_rv_5min": round(_win_rv(day, *STMT_WIN), 8),
                "presser_window_rv_5min": round(_win_rv(day, *PRESS_WIN), 8),
                "event_day_session_rv_5min": round(_session_rv(df, ev), 8),
                "next_session_date": nxt,
                "next_session_rv_5min": (round(_session_rv(df, nxt), 8)
                                         if nxt else None),
                "abs_stmt_minus_abs_press_logret": (
                    round(abs(stmt_ret) - abs(press_ret), 6)
                    if not (math.isnan(stmt_ret) or math.isnan(press_ret)) else None),
            }
        out["events"][ev] = rec
    out["caveat"] = (
        f"N={len(usable)} event(s) with intraday coverage. These are single-event "
        "case studies; NO cross-event statistical test is claimed (N far below any "
        "power threshold, see Part 1). Signs/magnitudes are descriptive only.")
    return out


# ---------------------------------------------------------------------------
# Part 3 — Aggregate FOMC-day effect on t+1 daily volatility (formal test)
# ---------------------------------------------------------------------------
def parkinson_var(df: pd.DataFrame) -> pd.Series:
    """Parkinson (1980) high-low range variance estimator (daily)."""
    hl = np.log(df["High"].astype(float) / df["Low"].astype(float))
    return (hl ** 2) / (4.0 * math.log(2.0))


def sqret_var(df: pd.DataFrame) -> pd.Series:
    """Squared close-to-close log return (unbiased daily variance proxy)."""
    r = np.log(df["Close"].astype(float)).diff()
    return r ** 2


def part3_aggregate(daily: dict[str, pd.DataFrame]) -> dict:
    import statsmodels.api as sm
    from statsmodels.stats.multitest import multipletests

    proxies = {"parkinson": parkinson_var, "sqret": sqret_var}
    rows = []          # collects (asset, proxy, stats...) preserving a-priori order
    pvals = []

    for tk in ASSETS:
        df = daily[tk].copy()
        df.index = pd.to_datetime(df.index)
        fomc = pd.Series(
            [1.0 if d.strftime("%Y-%m-%d") in FOMC_SET else 0.0 for d in df.index],
            index=df.index, name="FOMC")
        for pname, pfun in proxies.items():
            rv = pfun(df)
            logrv = np.log(rv.replace(0.0, np.nan)).rename("logrv")
            data = pd.concat([logrv, fomc], axis=1).dropna()
            # LOOKAHEAD-CLEAN: outcome = logrv at day t; predictors from day t-1.
            # `.shift(1)` puts yesterday's FOMC dummy and yesterday's logrv on
            # today's row -> we test whether an FOMC announcement on t-1 raises
            # volatility on t (the day AFTER the event). No same-day leakage.
            y = data["logrv"]
            X = pd.DataFrame({
                "const": 1.0,
                "FOMC_lag1": data["FOMC"].shift(1),
                "logrv_lag1": data["logrv"].shift(1),
            }).loc[y.index]
            keep = X.dropna().index
            y, X = y.loc[keep], X.loc[keep]
            # explicit lag assertion (fails loudly if alignment ever breaks)
            assert X["FOMC_lag1"].equals(data["FOMC"].shift(1).loc[keep]), "lag misaligned"

            n = len(y)
            hac_lag = max(1, int(math.ceil(n ** (1.0 / 3.0))))  # canonical NW bandwidth
            res = sm.OLS(y.values, X.values).fit(
                cov_type="HAC", cov_kwds={"maxlags": hac_lag})
            beta = float(res.params[1])
            se = float(res.bse[1])
            tval = float(res.tvalues[1])
            pval = float(res.pvalues[1])

            # residual autocorrelation diagnostic (rule: measure acf before trusting HAC)
            resid = pd.Series(res.resid)
            acf1 = float(resid.autocorr(lag=1)) if len(resid) > 2 else float("nan")

            # HAC lag sensitivity
            sens = {}
            for L in sorted({1, hac_lag, 2 * hac_lag, 10}):
                r2 = sm.OLS(y.values, X.values).fit(cov_type="HAC",
                                                    cov_kwds={"maxlags": L})
                sens[f"lag{L}"] = {"t": round(float(r2.tvalues[1]), 4),
                                   "p": round(float(r2.pvalues[1]), 6)}

            # unconditional descriptive comparison (no control)
            g1 = data["logrv"][data["FOMC"].shift(1) == 1.0].dropna()
            g0 = data["logrv"][data["FOMC"].shift(1) == 0.0].dropna()

            rows.append({
                "asset": tk, "proxy": pname, "n_obs": n,
                "n_fomc_lag_days": int((X["FOMC_lag1"] == 1.0).sum()),
                "beta_fomc_lag1": round(beta, 6),
                "beta_pct_effect_on_vol": round((math.exp(beta) - 1) * 100, 3),
                "hac_se": round(se, 6), "t_stat": round(tval, 4),
                "p_value_raw": round(pval, 6), "hac_lag": hac_lag,
                "resid_acf1": round(acf1, 4),
                "hac_lag_sensitivity": sens,
                "mean_logrv_after_fomc": round(float(g1.mean()), 4),
                "mean_logrv_other": round(float(g0.mean()), 4),
            })
            pvals.append(pval)

    # Holm correction over the FIXED family of 6 tests (3 assets x 2 proxies)
    reject, p_holm, _, _ = multipletests(pvals, alpha=0.05, method="holm")
    for r, pc, rej in zip(rows, p_holm, reject):
        r["p_value_holm"] = round(float(pc), 6)
        r["holm_significant_0.05"] = bool(rej)

    # Block bootstrap of the primary (parkinson) beta, per asset, seed=42.
    boot = _block_bootstrap_beta(daily, proxy="parkinson", n_boot=2000)

    n_sig = sum(r["holm_significant_0.05"] for r in rows)
    return {
        "spec": ("logRV_t = a + b*FOMC_{t-1} + c*logRV_{t-1} + e ; "
                 "HAC(Newey-West) SE; b>0 => FOMC raises NEXT-day volatility"),
        "multiple_testing": {"family_size": len(rows), "method": "holm",
                             "n_significant_after_holm": n_sig},
        "results": rows,
        "block_bootstrap_parkinson": boot,
        "scope_caveat": (
            "Part 3 measures the COMBINED statement+presser next-day volatility "
            "effect. It does NOT and cannot separate the two shocks — that "
            "separation is the infeasible core question (Part 1)."),
    }


def _block_bootstrap_beta(daily: dict[str, pd.DataFrame], proxy: str,
                          n_boot: int = 2000) -> dict:
    """Moving-block bootstrap of beta to stress-test the HAC p-value (seed=42)."""
    import statsmodels.api as sm
    rng = np.random.default_rng(SEED)
    pfun = {"parkinson": parkinson_var, "sqret": sqret_var}[proxy]
    out = {}
    for tk in ASSETS:
        df = daily[tk].copy()
        df.index = pd.to_datetime(df.index)
        fomc = pd.Series([1.0 if d.strftime("%Y-%m-%d") in FOMC_SET else 0.0
                          for d in df.index], index=df.index)
        logrv = np.log(pfun(df).replace(0.0, np.nan))
        data = pd.concat([logrv.rename("y"), fomc.rename("f")], axis=1).dropna()
        y = data["y"]
        X = pd.DataFrame({"const": 1.0, "f1": data["f"].shift(1),
                          "y1": data["y"].shift(1)})
        keep = X.dropna().index
        y, X = y.loc[keep].to_numpy(), X.loc[keep].to_numpy()
        n = len(y)
        bl = max(2, int(round(n ** (1.0 / 3.0))))
        nblocks = int(math.ceil(n / bl))
        betas = []
        starts_all = np.arange(0, n - bl + 1)
        n_skipped = 0
        for _ in range(n_boot):
            starts = rng.choice(starts_all, size=nblocks, replace=True)
            idx = np.concatenate([np.arange(s, s + bl) for s in starts])[:n]
            try:
                b = sm.OLS(y[idx], X[idx]).fit().params[1]
                betas.append(float(b))
            except Exception:  # silent-ok: rare singular resample; count surfaced via n_skipped_singular
                # A rare resample can yield a singular design matrix (e.g. an
                # all-same-FOMC block draw). The drop is NOT silent at the result
                # level: n_skipped_singular and n_boot_effective (=len(betas)) both
                # surface it, so any material loss of draws is observable.
                n_skipped += 1
                continue
        betas = np.array(betas)
        lo, hi = np.percentile(betas, [2.5, 97.5])
        # bootstrap two-sided p for H0: beta=0
        frac_le0 = float((betas <= 0).mean())
        p_boot = 2 * min(frac_le0, 1 - frac_le0)
        out[tk] = {"beta_mean": round(float(betas.mean()), 6),
                   "ci95": [round(float(lo), 6), round(float(hi), 6)],
                   "p_boot_two_sided": round(p_boot, 6),
                   "block_len": bl, "n_boot_effective": int(len(betas)),
                   "n_skipped_singular": int(n_skipped)}
    return out


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def make_figures(intraday: dict[str, pd.DataFrame], usable: list[str],
                 part3: dict) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    paths = []
    # Fig 1: intraday afternoons for TLT & IEF on the usable FOMC days
    ev_plot = [e for e in usable]
    if ev_plot:
        fig, axes = plt.subplots(len(ev_plot), 2, figsize=(12, 4.2 * len(ev_plot)),
                                 squeeze=False)
        for i, ev in enumerate(ev_plot):
            for j, tk in enumerate(["TLT", "IEF"]):
                ax = axes[i][j]
                df = intraday[tk]
                day = df[df.index.strftime("%Y-%m-%d") == ev]
                aft = day[(day.index.strftime("%H:%M") >= "13:30") &
                          (day.index.strftime("%H:%M") <= "15:55")]
                ax.plot(aft.index, aft["Close"], color="#1f4e79", lw=1.3)
                # window shading
                def span(lo, hi, color, label):
                    hm = aft.index.strftime("%H:%M")
                    seg = aft[(hm >= lo) & (hm <= hi)]
                    if len(seg):
                        ax.axvspan(seg.index[0], seg.index[-1], color=color,
                                   alpha=0.18, label=label)
                span(*STMT_WIN, "#d97706", "statement 13:55–14:15")
                span(*PRESS_WIN, "#2563eb", "presser 14:25–15:30")
                for t, c in [("14:00", "#b91c1c"), ("14:30", "#1d4ed8")]:
                    hm = aft.index.strftime("%H:%M")
                    mk = aft[hm == t]
                    if len(mk):
                        ax.axvline(mk.index[0], color=c, ls="--", lw=1.0)
                ax.set_title(f"{tk} — {ev} (statement 14:00 / presser 14:30 ET)",
                             fontsize=10)
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                ax.tick_params(labelsize=8)
                if i == 0 and j == 0:
                    ax.legend(fontsize=7, loc="best")
        fig.suptitle("K1658 Part 2 — intraday case studies (N=%d events, "
                     "descriptive only)" % len(ev_plot), fontsize=12)
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        p1 = os.path.join(HERE, "K1658_fig1_intraday_casestudies.png")
        fig.savefig(p1, dpi=130)
        plt.close(fig)
        paths.append(p1)

    # Fig 2: Part 3 beta estimates with 95% HAC CI, Holm significance marked
    rows = part3["results"]
    fig, ax = plt.subplots(figsize=(9, 5))
    labels, betas, los, his, cols = [], [], [], [], []
    for r in rows:
        labels.append(f"{r['asset']}\n{r['proxy']}")
        b, se = r["beta_fomc_lag1"], r["hac_se"]
        betas.append(b); los.append(1.96 * se); his.append(1.96 * se)
        cols.append("#15803d" if r["holm_significant_0.05"] else "#9ca3af")
    x = np.arange(len(labels))
    ax.bar(x, betas, color=cols, alpha=0.85)
    ax.errorbar(x, betas, yerr=[los, his], fmt="none", ecolor="black",
                elinewidth=1, capsize=3)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("β  (effect of prior-day FOMC on log next-day RV)")
    ax.set_title("K1658 Part 3 — aggregate FOMC→t+1 volatility effect\n"
                 "(green = Holm-significant at 0.05; COMBINED effect, not a "
                 "shock decomposition)", fontsize=10)
    fig.tight_layout()
    p2 = os.path.join(HERE, "K1658_fig2_aggregate_fomc_rv.png")
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    paths.append(p2)
    return paths


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="re-pull data from yfinance (default: use cached CSVs)")
    ap.add_argument("--no-figs", action="store_true")
    args = ap.parse_args()

    intraday = {tk: load_intraday(tk, args.refresh) for tk in ASSETS}
    daily = {tk: load_daily(tk, args.refresh) for tk in ASSETS}

    part1 = part1_feasibility(intraday)
    usable = part1["feasibility"]["usable_events_any_asset"]
    part2 = part2_case_studies(intraday, usable)
    part3 = part3_aggregate(daily)

    figs = []
    if not args.no_figs:
        try:
            figs = make_figures(intraday, usable, part3)
        except Exception as e:  # figures are optional, never block the artifact
            figs = [f"FIGURE_ERROR: {e!r}"]

    verdict = (
        "CONDITIONAL_PASS — core research question (separating statement vs "
        "presser shock) is INFEASIBLE with free data (N=%d intraday FOMC "
        "events, far below any power threshold). Reported honestly as the "
        "primary NULL/infeasible result. A lookahead-clean, HAC-robust, "
        "Holm-corrected aggregate FOMC->t+1 volatility test IS completed "
        "(Part 3) and %d/6 tests survive multiple-testing correction; it "
        "measures the COMBINED effect and does not separate the two shocks."
        % (part1["feasibility"]["n_usable_events"],
           part3["multiple_testing"]["n_significant_after_holm"]))

    results = {
        "experiment_id": "K1658",
        "title": ("FOMC statement shock (14:00 ET) vs press-conference shock "
                  "(14:30 ET): distributional response decomposition for rate "
                  "assets"),
        "seed": SEED,
        "run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "orthogonality_note": (
            "Distinct from research_program line 1425 (statement/minutes "
            "linguistic complexity, a TEXT-readability level). K1658 is a "
            "same-day TWO-STAGE market-reaction decomposition, not a text "
            "feature."),
        "assets": ASSETS,
        "data_sources": {
            "intraday": "yfinance 5m (period=60d, HARD cap), tz->America/New_York",
            "daily": f"yfinance daily OHLC from {DAILY_START} to 2026-07-24",
            "fomc_calendar": ("federalreserve.gov FOMC calendars; 2024-2026 "
                              "verified directly 2026-07-27, 2019-2023 cross-"
                              "checked vs Fed rate-decision record"),
            "cached_to": "experiments/K1658/data/ (preserves the 60-day intraday "
                         "window, which rolls forward in yfinance)",
        },
        "lookahead_policy": (
            "Part 3: outcome=logRV_t, predictors=FOMC and control via explicit "
            ".shift(1) (from t-1); tests day-AFTER-FOMC volatility. Part 2 "
            "next-day RV is the strictly-following session. seed=42."),
        "part1_feasibility_diagnosis": part1,
        "part2_intraday_case_studies": part2,
        "part3_aggregate_fomc_effect": part3,
        "figures": [os.path.basename(f) for f in figs],
        "verdict": verdict,
        "unresolved": (
            "Core two-shock SEPARATION remains INFEASIBLE with free data "
            "(N=%d events). To answer it properly requires paid intraday "
            "Treasury-futures/SOFR tick history (>=1.5-4 yr of complete "
            "intraday coverage per Part1 power calc). Options-implied "
            "skew/tail outcomes are also out of scope (no free intraday IV "
            "surface). Codex primary-path review + worktree merge are handled "
            "by the followup fire (per brief)."
            % part1["feasibility"]["n_usable_events"]),
    }

    out_path = os.path.join(HERE, "K1658_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # concise console summary
    print("=" * 72)
    print("K1658 done.")
    print("Part1 usable intraday FOMC events:",
          part1["feasibility"]["n_usable_events"],
          part1["feasibility"]["usable_events_any_asset"])
    print("Part1 verdict:", part1["feasibility"]["verdict"][:90], "...")
    print("Part3 Holm-significant:",
          part3["multiple_testing"]["n_significant_after_holm"], "/ 6")
    for r in part3["results"]:
        print(f"  {r['asset']:5s} {r['proxy']:9s} beta={r['beta_fomc_lag1']:+.4f}"
              f" t={r['t_stat']:+.2f} p_raw={r['p_value_raw']:.4f}"
              f" p_holm={r['p_value_holm']:.4f} sig={r['holm_significant_0.05']}"
              f" acf1={r['resid_acf1']:+.3f}")
    print("Figures:", [os.path.basename(f) for f in figs])
    print("Wrote", out_path)


if __name__ == "__main__":
    main()
