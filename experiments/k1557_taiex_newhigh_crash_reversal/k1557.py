#!/usr/bin/env python3
"""K1557 — Verify FinLab's TAIEX "new-1yr-high → sharp crash → short bounce but
1-year underperformance" claim with real ^TWII data.

FinLab (FB) claimed (TAIEX, 1999–now): index makes a 1-yr high, then within 3-4
days a sharp drop whose trailing-3d decline ranks in the worst 2% of the past
year. 10 occurrences. 3M +4.7% (88% win); 6M -0.2% (40%); 1Y -1.7% (<30% win)
vs buy-hold +8.5%; worst 2007 (GFC) -47.6%.

We replicate honestly. Codex review (2026-06-28) FAIL'd v1 for: (a) entry at
close[t] is optimistic — event is only confirmed at close[t], so a tradable
entry is the NEXT close (t+1); (b) dedupe that kept the episode's sharpest day
is retrospective trough-picking that inflates the bounce — use the FIRST
trigger. Both fixed here. Event signal uses only data <= t (252d high +
trailing-3d-return percentile vs prior 252d); forward returns measured from the
t+1 entry. Seed fixed for the bootstrap CI. n is small (5-28 by filter) so all
stats are descriptive with wide CIs — reported, not hidden.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

OUT = Path(__file__).resolve().parent
SEED = 42
TD_1Y = 252
TD_3D = 3
PCTILE = 2.0
HIGH_LOOKBACK_DAYS = 5
FWD = {"3M": 63, "6M": 126, "1Y": 252}
DEDUPE_DAYS = 20


def load_taiex() -> pd.Series:
    df = yf.download("^TWII", start="1997-01-01", end="2026-06-28",
                     progress=False, auto_adjust=False)
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    close.index = pd.to_datetime(close.index)
    return close


def find_events(close: pd.Series, lookback: int = HIGH_LOOKBACK_DAYS,
                pctile: float = PCTILE, dedupe: int = DEDUPE_DAYS) -> list[int]:
    """Return FIRST-trigger event indices (signal known at close[t])."""
    c = close.values
    idx = close.index
    n = len(c)
    r3 = pd.Series(c, index=idx).pct_change(TD_3D).values
    roll_high = pd.Series(c, index=idx).rolling(TD_1Y).max().values
    # strict-new-high helper: close[j] is the max of the 252d window AND strictly
    # above the prior window's max (a genuinely fresh high, not a flat tie).
    prev_high = pd.Series(c, index=idx).shift(1).rolling(TD_1Y).max().values

    raw = []
    for t in range(TD_1Y + TD_3D, n):
        if idx[t].year < 1999:
            continue
        made_high = False
        for k in range(0, lookback + 1):
            j = t - k
            if (not np.isnan(roll_high[j]) and abs(c[j] - roll_high[j]) < 1e-6
                    and (np.isnan(prev_high[j]) or c[j] > prev_high[j] - 1e-6)):
                made_high = True
                break
        if not made_high:
            continue
        window = r3[t - TD_1Y + 1: t + 1]
        window = window[~np.isnan(window)]
        if len(window) < 100:
            continue
        if r3[t] <= np.percentile(window, pctile):
            raw.append(t)

    # dedupe: keep the FIRST trigger of an episode (Codex fix — no retrospective
    # trough-picking).
    episodes: list[int] = []
    for t in raw:
        if episodes and (t - episodes[-1]) <= dedupe:
            continue
        episodes.append(t)
    return episodes


def forward_from_entry(close: pd.Series, t: int, h: int) -> float | None:
    """Forward return from the NEXT-day entry (t+1) over h trading days."""
    c = close.values
    entry = t + 1                      # tradable entry: close after event known
    if entry + h >= len(c):
        return None
    return round((c[entry + h] / c[entry] - 1) * 100, 2)


def event_rows(close: pd.Series, episodes: list[int]) -> list[dict]:
    c = close.values
    idx = close.index
    r3 = pd.Series(c, index=idx).pct_change(TD_3D).values
    rows = []
    for t in episodes:
        row = {"event_date": idx[t].strftime("%Y-%m-%d"),
               "entry_date": idx[t + 1].strftime("%Y-%m-%d") if t + 1 < len(c) else None,
               "close": round(float(c[t]), 1),
               "r3_pct": round(float(r3[t]) * 100, 2)}
        for label, h in FWD.items():
            row[label] = forward_from_entry(close, t, h)
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    rng = np.random.default_rng(SEED)
    out = {}
    for label in FWD:
        vals = np.array([r[label] for r in rows if r[label] is not None], dtype=float)
        if len(vals) == 0:
            out[label] = None
            continue
        boot = [(rng.choice(vals, len(vals), replace=True) > 0).mean() for _ in range(5000)]
        out[label] = {
            "n": int(len(vals)),
            "median_pct": round(float(np.median(vals)), 2),
            "mean_pct": round(float(np.mean(vals)), 2),
            "win_rate": round(float((vals > 0).mean()), 3),
            "win_rate_95ci": [round(float(np.percentile(boot, 2.5)), 3),
                              round(float(np.percentile(boot, 97.5)), 3)],
            "min_pct": round(float(vals.min()), 2),
            "max_pct": round(float(vals.max()), 2),
        }
    return out


def unconditional(close: pd.Series) -> dict:
    c = close.values
    n = len(c)
    out = {}
    for label, h in FWD.items():
        rets = np.array([(c[t + h] / c[t] - 1) * 100 for t in range(n - h)
                         if close.index[t].year >= 1999])
        out[label] = {"median": round(float(np.median(rets)), 2),
                      "win_rate": round(float((rets > 0).mean()), 3),
                      "n": int(len(rets))}
    return out


def sensitivity(close: pd.Series) -> list[dict]:
    rows = []
    for lb in (3, 5, 7):
        for pc in (2.0, 3.0, 5.0):
            eps = find_events(close, lookback=lb, pctile=pc)
            r = event_rows(close, eps)
            s = summarize(r)
            rows.append({
                "lookback": lb, "pctile": pc, "n_events": len(r),
                "m3M": (s["3M"] or {}).get("median_pct"),
                "m1Y": (s["1Y"] or {}).get("median_pct"),
                "win1Y": (s["1Y"] or {}).get("win_rate"),
            })
    return rows


def main() -> None:
    close = load_taiex()
    episodes = find_events(close)
    rows = event_rows(close, episodes)
    summ = summarize(rows)
    uncond = unconditional(close)
    sens = sensitivity(close)

    m1y_vals = [s["m1Y"] for s in sens if s["m1Y"] is not None]
    result = {
        "experiment_id": "K1557",
        "title": "TAIEX new-1yr-high → sharp-crash → forward returns (FinLab claim verification)",
        "data": {"ticker": "^TWII", "source": "yfinance",
                 "range": [close.index.min().strftime("%Y-%m-%d"),
                           close.index.max().strftime("%Y-%m-%d")],
                 "n_days": int(len(close))},
        "method": {
            "event_signal": "252d new high within last 5 td AND trailing-3d return "
                            "<= 2nd percentile of prior-252d 3d returns (signal uses data<=t)",
            "entry": "t+1 close (event confirmed at close[t]) — Codex fix",
            "dedupe": "first trigger within 20 td (no retrospective trough-picking) — Codex fix",
            "event_year_min": 1999,
        },
        "n_events": len(rows),
        "events": rows,
        "conditional_forward": summ,
        "unconditional_forward_1999plus": uncond,
        "sensitivity": sens,
        "robustness_verdict": {
            "3M_bounce": "check across sensitivity m3M column",
            "1Y_median_range_across_filters": [min(m1y_vals), max(m1y_vals)] if m1y_vals else None,
        },
        "finlab_claim": {"n_events": 10, "3M": {"win": 0.88, "median": 4.7},
                         "6M": {"median": -0.2, "win": 0.40},
                         "1Y": {"median": -1.7, "win_lt": 0.30, "buyhold_median": 8.5},
                         "worst_2007_1Y": -47.6},
        "seed": SEED,
    }
    (OUT / "k1557_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("n_events:", len(rows))
    for r in rows:
        print(f"  ev={r['event_date']} entry={r['entry_date']} r3={r['r3_pct']}% "
              f"| 3M={r['3M']} 6M={r['6M']} 1Y={r['1Y']}")
    print("conditional:", json.dumps(summ, ensure_ascii=False))
    print("unconditional:", json.dumps(uncond, ensure_ascii=False))
    print("sensitivity 1Y range:", result["robustness_verdict"]["1Y_median_range_across_filters"])
    for s in sens:
        print(f"  lb={s['lookback']} pct={s['pctile']}: n={s['n_events']} "
              f"3M={s['m3M']} 1Y={s['m1Y']} win1Y={s['win1Y']}")


if __name__ == "__main__":
    main()
