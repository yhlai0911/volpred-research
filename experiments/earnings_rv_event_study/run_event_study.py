#!/usr/bin/env python3
"""Earnings-day realized-volatility event study for 8 large-cap tech names.

Design
------
- Universe: NVDA AAPL MSFT AMZN GOOGL META TSM AMD
- Earnings dates: yfinance ``get_earnings_dates`` (reported quarters only)
- Event day t=0 = first trading session whose close prices the announcement:
    * announcement timestamp >= 16:00 ET (after close)  -> next trading day
    * announcement timestamp <  09:30 ET (before open)  -> same trading day
    * otherwise (intraday, rare)                        -> same trading day
- Return = log close-to-close (auto-adjusted prices)
- RV over a window = sqrt(252 * mean(r^2))  (annualized, %)
- Baseline window = t-30 .. t-11 (20 trading days), i.e. no overlap with the
  pre-earnings run-up window.
- Pre window = t-5 .. t-1 ; Post window = t+1 .. t+5 ; event day reported alone.

Outputs
-------
storage/experiments/earnings_rv_event_study.json  (evidence JSON)
storage/article_assets/earnings-rv-20260720/*.png (figure)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

REPO = Path(__file__).resolve().parents[2]
TICKERS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSM", "AMD"]
N_QUARTERS = 12
PRICE_START = "2021-06-01"
BASE_LO, BASE_HI = -30, -11
PRE_LO, PRE_HI = -5, -1
POST_LO, POST_HI = 1, 5
EVT_LO, EVT_HI = -10, 10
ANN_FACTOR = math.sqrt(252.0)
SEED = 20260720


def annualized_rv(rets: np.ndarray) -> float:
    """Annualized realized vol (%) from a vector of daily log returns."""
    if len(rets) == 0:
        return float("nan")
    return float(np.sqrt(np.mean(rets**2)) * ANN_FACTOR * 100.0)


def load_prices() -> dict[str, pd.DataFrame]:
    out = {}
    for tk in TICKERS:
        df = yf.download(
            tk, start=PRICE_START, auto_adjust=True, progress=False, actions=False
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"]).copy()
        df["ret"] = np.log(df["Close"]).diff()
        df = df.dropna(subset=["ret"])
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        out[tk] = df
    return out


CACHE = Path(__file__).resolve().parent / "earnings_dates_cache.json"


def load_earnings(tk: str) -> list[pd.Timestamp]:
    """Return event-day (t=0) trading dates, most recent first.

    yfinance intermittently returns an empty frame; retry, then fall back to
    the on-disk cache so a rerun reproduces the same sample.
    """
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    raw = None
    for _ in range(4):
        try:
            raw = yf.Ticker(tk).get_earnings_dates(limit=80)
        except Exception:
            raw = None
        if raw is not None and not raw.empty:
            break
        import time

        time.sleep(3)
    if raw is not None and not raw.empty:
        cache[tk] = [
            [str(ix), float(v) if v == v else None]
            for ix, v in zip(raw.index, raw["Reported EPS"])
        ]
        CACHE.write_text(json.dumps(cache, indent=1))
    elif tk in cache:
        print(f"  [cache] {tk} earnings dates from local cache")
        raw = pd.DataFrame(
            {"Reported EPS": [v for _, v in cache[tk]]},
            index=pd.DatetimeIndex([pd.Timestamp(s) for s, _ in cache[tk]]),
        )
    if raw is None or raw.empty:
        raise RuntimeError(f"no earnings dates for {tk}")
    raw = raw[raw["Reported EPS"].notna()]
    events = []
    for ts in raw.index:
        et = ts.tz_convert("America/New_York")
        day = pd.Timestamp(et.date())
        after_close = et.hour >= 16
        events.append((day, after_close, ts))
    return events


def main() -> None:
    prices = load_prices()
    today = pd.Timestamp(datetime.now(timezone.utc).date())

    per_event = []
    dropped = []

    for tk in TICKERS:
        px = prices[tk]
        idx = px.index
        rets = px["ret"].to_numpy()
        raw_events = load_earnings(tk)
        kept = 0
        for day, after_close, ts in raw_events:
            if kept >= N_QUARTERS:
                break
            # locate the anchor trading session
            pos = int(idx.searchsorted(day, side="left"))
            if pos >= len(idx):
                dropped.append((tk, str(ts), "no trading day at/after announcement"))
                continue
            if after_close:
                # announcement after this session's close -> reaction is next session
                if idx[pos] == day:
                    pos = pos + 1
                # if the announcement day was a holiday, pos already points to next
            if pos >= len(idx) or pos + POST_HI >= len(idx):
                dropped.append((tk, str(ts), "post-window incomplete"))
                continue
            if pos + BASE_LO < 0:
                dropped.append((tk, str(ts), "baseline window incomplete"))
                continue
            t0 = idx[pos]
            if t0 > today:
                continue

            def win(lo, hi):
                return rets[pos + lo : pos + hi + 1]

            base = win(BASE_LO, BASE_HI)
            pre = win(PRE_LO, PRE_HI)
            post = win(POST_LO, POST_HI)
            evt_ret = float(rets[pos])
            base_mad = float(np.mean(np.abs(base)))
            if base_mad <= 0:
                dropped.append((tk, str(ts), "degenerate baseline"))
                continue
            # mean of log|r| over the baseline window: the correct centering
            # constant for a paired log-ratio test (avoids Jensen bias, since
            # geo-mean of |r| sits well below mean|r| even under the null).
            base_abs = np.abs(base)
            base_abs = base_abs[base_abs > 0]
            base_log_mean = float(np.mean(np.log(base_abs)))

            path = {}
            for k in range(EVT_LO, EVT_HI + 1):
                j = pos + k
                path[k] = float(rets[j]) if 0 <= j < len(idx) else float("nan")

            per_event.append(
                {
                    "ticker": tk,
                    "announce_ts": str(ts),
                    "after_close": bool(after_close),
                    "event_day": str(t0.date()),
                    "rv_base": annualized_rv(base),
                    "rv_pre5": annualized_rv(pre),
                    "rv_post5": annualized_rv(post),
                    "evt_abs_ret_pct": abs(evt_ret) * 100.0,
                    "evt_ret_pct": evt_ret * 100.0,
                    "base_mean_abs_ret_pct": base_mad * 100.0,
                    "base_log_mean": base_log_mean,
                    "evt_over_base": abs(evt_ret) / base_mad,
                    "evt_log_excess": (
                        math.log(abs(evt_ret)) - base_log_mean if evt_ret != 0 else None
                    ),
                    "path_abs_over_base": {
                        str(k): (abs(v) / base_mad if v == v else None)
                        for k, v in path.items()
                    },
                    "path_log_excess": {
                        str(k): (
                            math.log(abs(v)) - base_log_mean
                            if v == v and v != 0
                            else None
                        )
                        for k, v in path.items()
                    },
                }
            )
            kept += 1

    ev = pd.DataFrame(per_event)
    ev["log_post_pre"] = np.log(ev["rv_post5"] / ev["rv_pre5"])
    ev["log_post_base"] = np.log(ev["rv_post5"] / ev["rv_base"])
    ev["log_evt_base"] = np.log(ev["evt_over_base"])

    rng = np.random.default_rng(SEED)

    def boot_ci(x, fn=np.mean, n=20000):
        x = np.asarray(x, dtype=float)
        draws = rng.choice(x, size=(n, len(x)), replace=True)
        stat = fn(draws, axis=1)
        return float(np.percentile(stat, 2.5)), float(np.percentile(stat, 97.5))

    from scipy import stats as st

    def paired_block(name, series):
        s = np.asarray(series, dtype=float)
        s = s[np.isfinite(s)]
        t, p = st.ttest_1samp(s, 0.0)
        try:
            w, pw = st.wilcoxon(s)
        except Exception:
            w, pw = float("nan"), float("nan")
        lo, hi = boot_ci(s)
        return {
            "name": name,
            "n": int(len(s)),
            "mean_log": float(np.mean(s)),
            "median_log": float(np.median(s)),
            "ratio_mean": float(np.exp(np.mean(s))),
            "ratio_median": float(np.exp(np.median(s))),
            "t_stat": float(t),
            "p_value": float(p),
            "wilcoxon_p": float(pw),
            "boot_ci_log": [lo, hi],
            "boot_ci_ratio": [float(np.exp(lo)), float(np.exp(hi))],
            "share_positive": float(np.mean(s > 0)),
        }

    tests = {
        "event_day_vs_baseline": paired_block(
            "log|r_t0| - mean(log|r|) over baseline window (paired, Jensen-safe)",
            ev["evt_log_excess"],
        ),
        "post5_vs_pre5": paired_block("log(RV_post5 / RV_pre5)", ev["log_post_pre"]),
        "post5_vs_baseline": paired_block(
            "log(RV_post5 / RV_base)", ev["log_post_base"]
        ),
        "pre5_vs_baseline": paired_block(
            "log(RV_pre5 / RV_base)", np.log(ev["rv_pre5"] / ev["rv_base"])
        ),
    }

    # ── event-time average path (pooled + per ticker) ──────────────────────
    ks = list(range(EVT_LO, EVT_HI + 1))
    path_mat = np.array(
        [[e["path_abs_over_base"][str(k)] or np.nan for k in ks] for e in per_event]
    )
    pooled_path = np.nanmean(path_mat, axis=0)
    pooled_p25 = np.nanpercentile(path_mat, 25, axis=0)
    pooled_p75 = np.nanpercentile(path_mat, 75, axis=0)

    def days_to_normal(vals: np.ndarray) -> int | None:
        """First k>=1 where mean |r|/baseline falls back to <= 1.0."""
        for i, k in enumerate(ks):
            if k >= 1 and vals[i] <= 1.0:
                return k
        return None

    # day-by-day pooled test on the Jensen-safe paired statistic
    excess_mat = np.array(
        [
            [
                (
                    e["path_log_excess"][str(k)]
                    if e["path_log_excess"][str(k)] is not None
                    else np.nan
                )
                for k in ks
            ]
            for e in per_event
        ]
    )
    by_day = []
    for i, k in enumerate(ks):
        col = path_mat[:, i]
        col = col[np.isfinite(col)]
        exc = excess_mat[:, i]
        exc = exc[np.isfinite(exc)]
        t, p = st.ttest_1samp(exc, 0.0)
        by_day.append(
            {
                "k": k,
                "n": int(len(col)),
                "mean_ratio": float(np.mean(col)),
                "median_ratio": float(np.median(col)),
                "log_excess_mean": float(np.mean(exc)),
                "t_stat": float(t),
                "p_value": float(p),
            }
        )

    per_ticker = []
    for tk in TICKERS:
        sub = ev[ev["ticker"] == tk]
        if sub.empty:
            continue
        m = np.array(
            [
                [
                    e["path_abs_over_base"][str(k)] or np.nan
                    for k in ks
                ]
                for e in per_event
                if e["ticker"] == tk
            ]
        )
        tk_path = np.nanmean(m, axis=0)
        per_ticker.append(
            {
                "ticker": tk,
                "n_events": int(len(sub)),
                "first_event": sub["event_day"].min(),
                "last_event": sub["event_day"].max(),
                "rv_base_mean": float(sub["rv_base"].mean()),
                "rv_pre5_mean": float(sub["rv_pre5"].mean()),
                "rv_post5_mean": float(sub["rv_post5"].mean()),
                "post_over_pre": float(np.exp(np.mean(np.log(sub["rv_post5"] / sub["rv_pre5"])))),
                "post_over_base": float(np.exp(np.mean(np.log(sub["rv_post5"] / sub["rv_base"])))),
                "evt_abs_ret_mean_pct": float(sub["evt_abs_ret_pct"].mean()),
                "evt_abs_ret_median_pct": float(sub["evt_abs_ret_pct"].median()),
                "evt_over_base_geo": float(np.exp(np.mean(sub["log_evt_base"]))),
                "evt_over_base_mean": float(sub["evt_over_base"].mean()),
                "evt_over_base_median": float(sub["evt_over_base"].median()),
                "evt_log_excess_mean": float(
                    np.nanmean(np.asarray(sub["evt_log_excess"], dtype=float))
                ),
                # RMS-based amplification: event-day RV vs baseline RV (vol units)
                "rv_event_day": float(
                    np.sqrt(np.mean((sub["evt_ret_pct"] / 100.0) ** 2)) * ANN_FACTOR * 100.0
                ),
                "vol_amp_rms": float(
                    np.sqrt(np.mean((sub["evt_ret_pct"] / 100.0) ** 2))
                    / np.sqrt(np.mean((sub["rv_base"] / (ANN_FACTOR * 100.0)) ** 2))
                ),
                "days_to_normal": days_to_normal(tk_path),
                "path": {str(k): (None if not np.isfinite(v) else float(v)) for k, v in zip(ks, tk_path)},
            }
        )

    per_ticker.sort(key=lambda d: -d["vol_amp_rms"])

    # cross-section: does the event-day jump scale with baseline vol?
    xs_x = np.array([d["rv_base_mean"] for d in per_ticker])
    xs_y = np.array([d["vol_amp_rms"] for d in per_ticker])
    xs_r, xs_p = st.pearsonr(xs_x, xs_y)
    xs_rho, xs_rho_p = st.spearmanr(xs_x, xs_y)

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "yfinance daily OHLC (auto-adjusted) + yfinance get_earnings_dates",
            "universe": TICKERS,
            "quarters_per_ticker_target": N_QUARTERS,
            "n_events": int(len(ev)),
            "sample_first_event": str(ev["event_day"].min()),
            "sample_last_event": str(ev["event_day"].max()),
            "definitions": {
                "rv": "sqrt(252 * mean(r^2)) * 100, r = daily log close-to-close return",
                "baseline_window": "t-30..t-11 (20 trading days)",
                "pre_window": "t-5..t-1",
                "post_window": "t+1..t+5",
                "event_day": "first session whose close prices the announcement",
            },
            "bootstrap": {"draws": 20000, "seed": SEED},
            "dropped_events": dropped,
        },
        "headline": {
            "event_day_amplification_geo_mean": float(
                np.exp(np.mean(ev["log_evt_base"]))
            ),
            "event_day_amplification_median": float(ev["evt_over_base"].median()),
            "event_day_mean_abs_ret_pct": float(ev["evt_abs_ret_pct"].mean()),
            "baseline_mean_abs_ret_pct": float(ev["base_mean_abs_ret_pct"].mean()),
            "post5_over_pre5_geo": float(np.exp(np.mean(ev["log_post_pre"]))),
            "post5_over_base_geo": float(np.exp(np.mean(ev["log_post_base"]))),
            "pooled_days_to_normal": days_to_normal(pooled_path),
            # primary definition: first post-event day whose paired test can no
            # longer distinguish it from the baseline window at the 5% level
            "pooled_first_insignificant_day": next(
                (b["k"] for b in by_day if b["k"] >= 1 and b["p_value"] > 0.05), None
            ),
            "share_events_evt_over_base_gt_2": float(np.mean(ev["evt_over_base"] > 2)),
            "rv_event_day_pooled": float(
                np.sqrt(np.mean((ev["evt_ret_pct"] / 100.0) ** 2)) * ANN_FACTOR * 100.0
            ),
            "rv_base_pooled": float(
                np.sqrt(np.mean((ev["rv_base"] / (ANN_FACTOR * 100.0)) ** 2))
                * ANN_FACTOR
                * 100.0
            ),
            "rv_pre5_pooled": float(
                np.sqrt(np.mean((ev["rv_pre5"] / (ANN_FACTOR * 100.0)) ** 2))
                * ANN_FACTOR
                * 100.0
            ),
            "rv_post5_pooled": float(
                np.sqrt(np.mean((ev["rv_post5"] / (ANN_FACTOR * 100.0)) ** 2))
                * ANN_FACTOR
                * 100.0
            ),
            "vol_amp_rms_pooled": float(
                np.sqrt(np.mean((ev["evt_ret_pct"] / 100.0) ** 2))
                / np.sqrt(np.mean((ev["rv_base"] / (ANN_FACTOR * 100.0)) ** 2))
            ),
        },
        "tests": tests,
        "by_event_day": by_day,
        "per_ticker": per_ticker,
        "pooled_path": {
            "k": ks,
            "mean_abs_over_base": [float(v) for v in pooled_path],
            "p25": [float(v) for v in pooled_p25],
            "p75": [float(v) for v in pooled_p75],
        },
        "cross_section": {
            "x": "baseline annualized RV (%) per ticker",
            "y": "event-day amplification (geo mean)",
            "pearson_r": float(xs_r),
            "pearson_p": float(xs_p),
            "spearman_rho": float(xs_rho),
            "spearman_p": float(xs_rho_p),
        },
        "per_event": per_event,
    }

    out_json = REPO / "storage/experiments/earnings_rv_event_study.json"
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_json}")

    print(json.dumps({k: v for k, v in payload["headline"].items()}, indent=2))
    print(json.dumps(payload["tests"], indent=2))
    for d in per_ticker:
        print(
            f"{d['ticker']:6s} n={d['n_events']:2d} base={d['rv_base_mean']:6.1f} "
            f"pre5={d['rv_pre5_mean']:6.1f} post5={d['rv_post5_mean']:6.1f} "
            f"post/pre={d['post_over_pre']:.2f} rv_evt={d['rv_event_day']:6.1f} "
            f"amp={d['vol_amp_rms']:.2f} med={d['evt_over_base_median']:.2f} "
            f"d2n={d['days_to_normal']}"
        )
    print(json.dumps(payload["cross_section"], indent=2))
    print("by_event_day:")
    for b in by_day:
        print(f"  k={b['k']:+3d} mean={b['mean_ratio']:.2f} med={b['median_ratio']:.2f} t={b['t_stat']:+.2f} p={b['p_value']:.4f}")
    print("dropped:", dropped)


if __name__ == "__main__":
    main()
