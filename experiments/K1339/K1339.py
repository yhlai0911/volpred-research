"""
K1339: Commodity backwardation → contango regime-switch event study.

Tests whether cross-asset-confirmed regime-switch dates (derived from
21d-vs-63d momentum slope proxy on USO/UNG/CPER) predict elevated
realised volatility and altered SPY correlation over 30/60/90-day
forward windows.

Lookahead: regime state at t uses returns through t-1 (.shift(1)).
Event date = day-10 of sustained filter (only data through that day
is used to declare the event). Forward windows start at event_date+1.

Seed: np.random.seed(42).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception as exc:  # pragma: no cover - explicit fail
    raise SystemExit(f"yfinance not available: {exc}")


HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "K1339_results.json"

ETFS = ["USO", "UNG", "CPER"]
SPILLOVER = "SPY"
START_DATE = "2015-01-01"
END_DATE = "2026-06-14"

MOM_SHORT = 21
MOM_LONG = 63
SUSTAIN_DAYS = 10
CROSS_WINDOW = 21
HORIZONS = [30, 60, 90]
BOOTSTRAP_B = 5000
SEED = 42
TRADING_DAYS_PER_YEAR = 252


def _download(symbol: str) -> pd.Series:
    df = yf.download(
        symbol,
        start=START_DATE,
        end=END_DATE,
        progress=False,
        auto_adjust=False,
    )
    if df is None or df.empty:
        raise SystemExit(f"yfinance returned empty for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        # Newer yfinance returns MultiIndex; pick Adj Close column.
        if ("Adj Close", symbol) in df.columns:
            series = df[("Adj Close", symbol)]
        else:
            # Single-level fallback.
            series = df["Adj Close"].iloc[:, 0]
    else:
        series = df["Adj Close"]
    series = series.dropna()
    series.name = symbol
    return series


def load_prices() -> pd.DataFrame:
    cols = {}
    for sym in ETFS + [SPILLOVER]:
        cols[sym] = _download(sym)
    df = pd.concat(cols.values(), axis=1, keys=cols.keys()).dropna(how="all")
    df = df.ffill(limit=2).dropna()
    return df


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return np.log(prices / prices.shift(1)).dropna()


def regime_state(prices: pd.Series) -> pd.Series:
    """+1 if 21d log-return > 63d log-return (annualised), else -1.

    State at date t is computed from returns through t-1 (.shift(1) on
    the prices). This is the lagged regime-state used downstream — no
    information from date t is used.
    """
    logp = np.log(prices.shift(1))
    r21 = logp - logp.shift(MOM_SHORT)
    r63 = logp - logp.shift(MOM_LONG)
    # Annualise both windows (factor cancels in sign comparison but keeps
    # interpretation consistent).
    r21_ann = r21 * (TRADING_DAYS_PER_YEAR / MOM_SHORT)
    r63_ann = r63 * (TRADING_DAYS_PER_YEAR / MOM_LONG)
    state = np.where(r21_ann > r63_ann, 1, -1)
    state = pd.Series(state, index=prices.index, name=prices.name)
    state.loc[r21.isna() | r63.isna()] = 0  # warmup
    return state


def detect_single_asset_events(
    state: pd.Series, direction: str
) -> List[pd.Timestamp]:
    """Find sustained regime switches for one asset.

    direction == 'back_to_contango': state flips from +1 → -1 and stays
        -1 for SUSTAIN_DAYS consecutive trading days.
    direction == 'contango_to_back': state flips -1 → +1 and stays +1.

    Event date returned = the SUSTAIN_DAYS-th day (i.e. earliest date
    at which the filter can be evaluated using only realised data).
    """
    assert direction in {"back_to_contango", "contango_to_back"}
    from_state, to_state = (1, -1) if direction == "back_to_contango" else (-1, 1)
    events: List[pd.Timestamp] = []
    s = state.astype(int).values
    idx = state.index
    i = 1
    while i < len(s) - SUSTAIN_DAYS:
        if s[i - 1] == from_state and s[i] == to_state:
            # Check sustained for SUSTAIN_DAYS days [i, i+SUSTAIN_DAYS-1]
            window = s[i : i + SUSTAIN_DAYS]
            if np.all(window == to_state):
                event_date = idx[i + SUSTAIN_DAYS - 1]
                events.append(event_date)
                # Skip ahead past sustained period to avoid duplicates
                i += SUSTAIN_DAYS
                continue
        i += 1
    return events


def cross_confirm(
    per_asset_events: Dict[str, List[pd.Timestamp]],
    cross_window_days: int,
) -> List[Dict]:
    """Confirm an event only if ≥2 of {USO, UNG, CPER} flip same
    direction within `cross_window_days` of each other.

    Returns sorted list of {date, lead_asset, confirming_assets}.
    """
    flat = []
    for asset, dates in per_asset_events.items():
        for d in dates:
            flat.append((d, asset))
    flat.sort()
    confirmed = []
    used = set()
    for i, (d_i, a_i) in enumerate(flat):
        if (d_i, a_i) in used:
            continue
        partners = [(d_i, a_i)]
        for j in range(i + 1, len(flat)):
            d_j, a_j = flat[j]
            if (d_j - d_i).days > cross_window_days * 1.5:
                # Approximate trading-day gap via calendar days (cap).
                break
            if a_j == a_i:
                continue
            # Count business days between dates.
            bd = np.busday_count(d_i.date(), d_j.date())
            if bd <= cross_window_days and a_j not in {p[1] for p in partners}:
                partners.append((d_j, a_j))
        if len({p[1] for p in partners}) >= 2:
            # Anchor event at the LATEST partner date (so all flips are
            # in the realised past — no peek).
            anchor_date = max(p[0] for p in partners)
            confirmed.append(
                {
                    "date": anchor_date,
                    "lead_asset": a_i,
                    "confirming_assets": sorted({p[1] for p in partners}),
                }
            )
            for p in partners:
                used.add(p)
    # Dedupe by date.
    seen_dates = set()
    out = []
    for ev in confirmed:
        d = ev["date"]
        if d in seen_dates:
            continue
        seen_dates.add(d)
        out.append(ev)
    out.sort(key=lambda x: x["date"])
    return out


def annualised_vol(returns: pd.Series) -> float:
    if len(returns) < 5:
        return float("nan")
    return float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def windowed_stats(
    returns: pd.DataFrame,
    event_date: pd.Timestamp,
    horizon: int,
) -> Dict:
    """Return pre/post vol per asset and pre/post corr(USO/UNG/CPER, SPY)."""
    if event_date not in returns.index:
        # Snap to next trading day.
        loc = returns.index.searchsorted(event_date)
        if loc >= len(returns.index):
            return {}
        event_loc = loc
    else:
        event_loc = returns.index.get_loc(event_date)

    pre_start = max(0, event_loc - horizon)
    pre_end = event_loc  # exclusive of event_date itself for clean split
    post_start = event_loc + 1
    post_end = min(len(returns.index), event_loc + 1 + horizon)
    if pre_end - pre_start < 10 or post_end - post_start < 10:
        return {}

    pre = returns.iloc[pre_start:pre_end]
    post = returns.iloc[post_start:post_end]

    stats: Dict[str, Dict] = {}
    for asset in ETFS:
        v_pre = annualised_vol(pre[asset])
        v_post = annualised_vol(post[asset])
        if not (np.isfinite(v_pre) and np.isfinite(v_post)) or v_pre <= 0:
            continue
        stats[asset] = {
            "vol_pre": v_pre,
            "vol_post": v_post,
            "vol_jump_pct": (v_post - v_pre) / v_pre,
            "corr_spy_pre": float(pre[asset].corr(pre[SPILLOVER])),
            "corr_spy_post": float(post[asset].corr(post[SPILLOVER])),
        }
    return stats


def paired_bootstrap_mean(values: np.ndarray, B: int, seed: int) -> Dict:
    rng = np.random.default_rng(seed)
    n = len(values)
    if n < 3:
        return {
            "mean": float(np.nan),
            "ci_low": float(np.nan),
            "ci_high": float(np.nan),
            "p_boot_two_sided": float(np.nan),
            "n": n,
        }
    means = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, n, size=n)
        means[b] = values[idx].mean()
    ci_low = float(np.quantile(means, 0.025))
    ci_high = float(np.quantile(means, 0.975))
    obs_mean = float(values.mean())
    # Two-sided p as frac of bootstrap means with opposite sign to obs OR
    # equal to zero — using simple sign-flip null.
    centered = means - obs_mean
    p_boot = float(np.mean(np.abs(centered) >= np.abs(obs_mean)))
    return {
        "mean": obs_mean,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "p_boot_two_sided": p_boot,
        "n": int(n),
    }


def run() -> Dict:
    np.random.seed(SEED)

    prices = load_prices()
    rets = log_returns(prices)
    n_days = len(prices)

    # Build regime states for each commodity ETF.
    states: Dict[str, pd.Series] = {
        sym: regime_state(prices[sym]) for sym in ETFS
    }

    # Detect single-asset events (both directions).
    per_asset_back_to_contango: Dict[str, List[pd.Timestamp]] = {}
    per_asset_contango_to_back: Dict[str, List[pd.Timestamp]] = {}
    for sym in ETFS:
        per_asset_back_to_contango[sym] = detect_single_asset_events(
            states[sym], "back_to_contango"
        )
        per_asset_contango_to_back[sym] = detect_single_asset_events(
            states[sym], "contango_to_back"
        )

    # Cross-confirm.
    events_b2c = cross_confirm(per_asset_back_to_contango, CROSS_WINDOW)
    events_c2b = cross_confirm(per_asset_contango_to_back, CROSS_WINDOW)

    # Run windowed stats per event x horizon.
    per_event_stats: List[Dict] = []
    for direction, events in [
        ("back_to_contango", events_b2c),
        ("contango_to_back", events_c2b),
    ]:
        for ev in events:
            entry = {
                "direction": direction,
                "date": str(pd.Timestamp(ev["date"]).date()),
                "lead_asset": ev["lead_asset"],
                "confirming_assets": ev["confirming_assets"],
                "by_horizon": {},
            }
            for H in HORIZONS:
                stats = windowed_stats(rets, pd.Timestamp(ev["date"]), H)
                entry["by_horizon"][str(H)] = stats
            per_event_stats.append(entry)

    # Pool jumps per (direction, horizon, asset) and bootstrap.
    pooled: Dict = {}
    for direction in ("back_to_contango", "contango_to_back"):
        pooled[direction] = {}
        for H in HORIZONS:
            pooled[direction][str(H)] = {}
            for asset in ETFS:
                jumps = []
                dcorrs = []
                for entry in per_event_stats:
                    if entry["direction"] != direction:
                        continue
                    bh = entry["by_horizon"].get(str(H), {})
                    s = bh.get(asset)
                    if not s:
                        continue
                    jumps.append(s["vol_jump_pct"])
                    dcorrs.append(s["corr_spy_post"] - s["corr_spy_pre"])
                jumps_a = np.asarray(jumps, dtype=float)
                dcorrs_a = np.asarray(dcorrs, dtype=float)
                pooled[direction][str(H)][asset] = {
                    "vol_jump": paired_bootstrap_mean(
                        jumps_a, BOOTSTRAP_B, SEED + abs(hash((direction, H, asset))) % 10000
                    ),
                    "dcorr_spy": paired_bootstrap_mean(
                        dcorrs_a, BOOTSTRAP_B, SEED + abs(hash((direction, H, asset, "c"))) % 10000
                    ),
                }

    # Verdict logic.
    sig_hits = []
    eff_hits = []
    for direction, hor_map in pooled.items():
        for H, asset_map in hor_map.items():
            for asset, stat in asset_map.items():
                vj = stat["vol_jump"]
                if vj["n"] >= 3:
                    if np.isfinite(vj["p_boot_two_sided"]) and vj["p_boot_two_sided"] < 0.10:
                        sig_hits.append(
                            f"{direction}|H={H}|{asset}|p={vj['p_boot_two_sided']:.3f}|mean={vj['mean']:.3f}"
                        )
                    if np.isfinite(vj["mean"]) and abs(vj["mean"]) > 0.25:
                        eff_hits.append(
                            f"{direction}|H={H}|{asset}|mean={vj['mean']:.3f}|n={vj['n']}"
                        )

    n_events_total = len(per_event_stats)
    n_b2c = len(events_b2c)
    n_c2b = len(events_c2b)
    enough_events = (n_b2c >= 5) or (n_c2b >= 5)
    if enough_events and (sig_hits or eff_hits):
        verdict = "PASS"
    elif enough_events:
        verdict = "NULL_NO_EFFECT"
    else:
        verdict = "NULL_INSUFFICIENT_EVENTS"

    out = {
        "experiment_id": "K1339",
        "title": "Commodity backwardation→contango regime-switch event study",
        "run_timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        "data": {
            "etfs": ETFS,
            "spillover": SPILLOVER,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "n_trading_days": n_days,
            "first_date": str(prices.index[0].date()),
            "last_date": str(prices.index[-1].date()),
        },
        "method": {
            "regime_proxy": "21d vs 63d log-return slope sign (state at t uses .shift(1))",
            "sustain_days": SUSTAIN_DAYS,
            "cross_window_business_days": CROSS_WINDOW,
            "horizons": HORIZONS,
            "bootstrap_B": BOOTSTRAP_B,
            "seed": SEED,
            "event_date_definition": "day-(SUSTAIN_DAYS) of sustained filter, forward window starts +1",
        },
        "events": {
            "back_to_contango_count": n_b2c,
            "contango_to_back_count": n_c2b,
            "back_to_contango_dates": [str(pd.Timestamp(e["date"]).date()) for e in events_b2c],
            "contango_to_back_dates": [str(pd.Timestamp(e["date"]).date()) for e in events_c2b],
        },
        "per_event_stats": per_event_stats,
        "pooled_bootstrap": pooled,
        "signal_hits_p_lt_010": sig_hits,
        "effect_hits_abs_gt_025": eff_hits,
        "verdict": verdict,
        "notes": (
            "Regime proxy is indirect (ETF momentum slope vs true futures curve). "
            "Forward 90d windows may overlap subsequent events; per-event table reported. "
            "Verdict NULL if no statistically or economically meaningful effect."
        ),
    }
    return out


def main() -> None:
    np.random.seed(SEED)
    result = run()
    RESULTS_PATH.write_text(json.dumps(result, indent=2, default=str))
    # Stdout summary.
    print(f"K1339 verdict: {result['verdict']}")
    print(
        f"events: back→contango n={result['events']['back_to_contango_count']}, "
        f"contango→back n={result['events']['contango_to_back_count']}"
    )
    print(f"signal hits (p<0.10): {len(result['signal_hits_p_lt_010'])}")
    print(f"effect hits (|mean|>0.25): {len(result['effect_hits_abs_gt_025'])}")
    if result["signal_hits_p_lt_010"]:
        for h in result["signal_hits_p_lt_010"][:10]:
            print("  SIG:", h)
    if result["effect_hits_abs_gt_025"]:
        for h in result["effect_hits_abs_gt_025"][:10]:
            print("  EFF:", h)


if __name__ == "__main__":
    main()
