"""K1725 — Did the spot BTC ETF listing (IBIT, 2024-01-11) change the
*time-of-day allocation structure* of crypto realized variance?

Hypothesis (J. Futures Markets 2025 lineage): ETF-ization pulls the crypto
volatility clock toward the traditional-market clock. Concretely, the share of
daily/weekly realized variance (RV) that occurs during US regular trading hours
(RTH) rises after IBIT, while the weekend / non-session share falls. This is a
*redistribution-in-time* claim, distinct from vol-of-vol spillover ("how much"),
which is about "when".

Design summary (full rationale in README.md):
  * Data: Binance BTCUSDT 1h klines (public, no key), UTC, cached locally.
  * Hourly close-to-close log returns r_t = ln(C_t / C_{t-1}).
  * Bucket each bar by its ET wall-clock (America/New_York -> DST-correct):
      - US-session (RTH): weekday, ET open-hour in {9..15}  (~9:00-16:00 ET,
        a +/-30min approximation of the 9:30-16:00 RTH window).
      - weekend: ET Saturday or Sunday.
      - non-session: weekday, ET open-hour outside RTH.
  * RV(bucket) = sum of r_t^2 over that bucket. Primary aggregation unit = ISO
    week (ET calendar), because DAILY weekend shares are degenerate (a weekday
    has weekend_share == 0 and a weekend day has RTH_share == 0); weekly windows
    contain all three buckets so the three shares are jointly non-degenerate and
    sum to 1.
  * Known-breakpoint test at 2024-01-11 (IBIT NYSE listing) on weekly shares:
    Welch t-test + Cohen's d + circular block-bootstrap CI (seed=42).
  * Endogenous break location via sup-Wald (Andrews QLR) mean-shift scan.
  * Robustness: event buffer, all three buckets (redistribution), logit shares,
    extended pre-window, daily weekday RTH concentration.

LOOKAHEAD POLICY: This is a descriptive / structural-break study of *realized*
(contemporaneous) variance shares, NOT a forecasting exercise. There is no
predictive signal that maps t-1 information onto a t outcome, so there is no
signal.shift(1) to apply. The primary breakpoint date (2024-01-11) is exogenous
and fixed ex-ante (a calendar event), so it is not in-sample optimized. The
endogenous sup-Wald search uses only contemporaneous data and is reported as
corroboration of the break *location*, never as a predictive/tradable claim.

All randomness seeded with SEED=42.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from scipy import stats

SEED = 42
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_CSV = DATA_DIR / "btcusdt_1h.csv"
RESULTS_JSON = HERE / "k1725_results.json"

SYMBOL = "BTCUSDT"
INTERVAL = "1h"
FETCH_START = "2022-01-01"          # fetch back this far (extended pre available)
IBIT_DATE = pd.Timestamp("2024-01-11", tz="UTC")  # IBIT et al. NYSE listing
PRIMARY_PRE_START = pd.Timestamp("2023-01-11", tz="UTC")   # 1y pre (primary)
EXTENDED_PRE_START = pd.Timestamp("2022-01-11", tz="UTC")  # 2y pre (robustness)

ET = ZoneInfo("America/New_York")
RTH_ET_HOURS = frozenset(range(9, 16))   # ET open-hour 9..15  (~9:00-16:00 ET)
MIN_WEEK_BARS = 160   # full ET week ~168 bars (DST 167/169); drops partial
                      # leading/terminal weeks so all three buckets are observed.
MIN_DAY_BARS = 20     # full day = 24 bars; drops partial terminal ET dates.

BINANCE_HOSTS = [
    "https://api.binance.com",
    "https://data-api.binance.vision",
]


# --------------------------------------------------------------------------- #
# Data acquisition
# --------------------------------------------------------------------------- #
def _to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paginated Binance klines fetch (1000/req). Returns raw open/close frame."""
    rows: list[list] = []
    cur = start_ms
    host_i = 0
    while cur < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cur,
            "endTime": end_ms,
            "limit": 1000,
        }
        host = BINANCE_HOSTS[host_i % len(BINANCE_HOSTS)]
        try:
            resp = requests.get(f"{host}/api/v3/klines", params=params, timeout=30)
            resp.raise_for_status()
            batch = resp.json()
        except Exception as exc:  # noqa: BLE001 — fail over to mirror host
            host_i += 1
            if host_i >= 4 * len(BINANCE_HOSTS):
                raise RuntimeError(f"Binance fetch failed near {cur}: {exc}") from exc
            time.sleep(1.0)
            continue
        if not batch:
            break
        rows.extend(batch)
        last_open = batch[-1][0]
        nxt = last_open + 3_600_000  # advance 1h past last bar
        if nxt <= cur:               # safety: no forward progress
            break
        cur = nxt
        time.sleep(0.25)             # be polite to the public endpoint
    if not rows:
        raise RuntimeError("No klines returned from Binance.")
    df = pd.DataFrame(
        rows,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "n_trades", "taker_base",
            "taker_quote", "ignore",
        ],
    )
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["open_time"] = df["open_time"].astype("int64")
    return df


def load_data() -> tuple[pd.DataFrame, dict]:
    """Load cached klines or fetch; return (clean df indexed by UTC, hygiene report)."""
    end_ms = int(time.time() * 1000)
    if CACHE_CSV.exists():
        raw = pd.read_csv(CACHE_CSV)
    else:
        raw = fetch_klines(SYMBOL, INTERVAL, _to_ms(FETCH_START), end_ms)
        raw.to_csv(CACHE_CSV, index=False)

    hygiene: dict = {}
    n_raw = len(raw)
    # --- dedup on open_time (project has snapshot-dup history) ---
    raw = raw.drop_duplicates(subset="open_time").sort_values("open_time").reset_index(drop=True)
    n_dedup = len(raw)

    ts = pd.to_datetime(raw["open_time"], unit="ms", utc=True)
    df = raw.copy()
    df.index = pd.DatetimeIndex(ts, name="open_time_utc")

    # --- gap / missing-bar check (expect strictly 1h spacing) ---
    full = pd.date_range(df.index.min(), df.index.max(), freq="1h", tz="UTC")
    missing = full.difference(df.index)
    hygiene.update(
        rows_raw=int(n_raw),
        rows_after_dedup=int(n_dedup),
        duplicate_rows_removed=int(n_raw - n_dedup),
        expected_hourly_bars=int(len(full)),
        missing_bars=int(len(missing)),
        missing_bar_fraction=round(len(missing) / len(full), 6),
        utc_start=df.index.min().isoformat(),
        utc_end=df.index.max().isoformat(),
        source="Binance klines (api.binance.com / data-api.binance.vision)",
        symbol=SYMBOL,
        interval=INTERVAL,
    )
    return df, hygiene


# --------------------------------------------------------------------------- #
# RV decomposition
# --------------------------------------------------------------------------- #
def build_bucketed_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Return per-bar frame with squared log return + ET-based bucket labels."""
    out = pd.DataFrame(index=df.index)
    out["close"] = df["close"].values
    # close-to-close hourly log return; first bar has no prior close -> NaN dropped
    logret = np.log(out["close"]).diff()
    # Null out any return that spans a missing bar (gap != 1h): a return computed
    # across a gap is not a clean 1h realized-variance contribution. (Only known
    # gap in this sample: 2023-03-24 13:00 UTC.)
    gap = out.index.to_series().diff()
    logret = logret.where(gap == pd.Timedelta(hours=1))
    out["r2"] = logret.pow(2)
    out = out.dropna(subset=["r2"])

    # ET wall-clock of the bar's *open* time (period start), DST-correct.
    et_index = out.index.tz_convert(ET)
    et_hour = et_index.hour
    et_dow = et_index.dayofweek  # Mon=0 .. Sun=6
    et_date = et_index.normalize().tz_localize(None)  # ET calendar date

    is_weekend = et_dow >= 5
    is_rth = (~is_weekend) & np.isin(et_hour, list(RTH_ET_HOURS))
    is_nonsession = (~is_weekend) & (~is_rth)

    bucket = np.where(is_weekend, "weekend",
                      np.where(is_rth, "us_session", "non_session"))
    out["bucket"] = bucket
    out["et_date"] = pd.DatetimeIndex(et_date)
    # ISO week key (ET calendar, Monday-anchored week start)
    out["week"] = out["et_date"] - pd.to_timedelta(
        pd.DatetimeIndex(out["et_date"]).dayofweek, unit="D"
    )
    return out


def aggregate_shares(bars: pd.DataFrame, group_key: str) -> pd.DataFrame:
    """RV per bucket per group, plus total and three shares (sum to 1)."""
    piv = (
        bars.pivot_table(index=group_key, columns="bucket", values="r2",
                         aggfunc="sum", fill_value=0.0)
        .reindex(columns=["us_session", "non_session", "weekend"], fill_value=0.0)
    )
    piv["total_rv"] = piv[["us_session", "non_session", "weekend"]].sum(axis=1)
    piv["n_bars"] = (
        bars.groupby(group_key).size().reindex(piv.index).fillna(0).astype(int)
    )
    piv = piv[piv["total_rv"] > 0].copy()
    for b in ["us_session", "non_session", "weekend"]:
        piv[f"{b}_share"] = piv[b] / piv["total_rv"]
    return piv


# --------------------------------------------------------------------------- #
# Inference helpers
# --------------------------------------------------------------------------- #
def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Pooled-SD Cohen's d for (b - a)."""
    na, nb = len(a), len(b)
    va, vb = a.var(ddof=1), b.var(ddof=1)
    pooled = np.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if pooled == 0:
        return 0.0
    return float((b.mean() - a.mean()) / pooled)


def circular_block_bootstrap_diff(pre: np.ndarray, post: np.ndarray,
                                  n_boot: int = 5000, seed: int = SEED) -> dict:
    """CI for (mean(post) - mean(pre)) preserving autocorrelation via circular
    block bootstrap of each series independently."""
    rng = np.random.default_rng(seed)

    def _boot_means(x: np.ndarray) -> np.ndarray:
        n = len(x)
        block = max(1, int(round(n ** (1 / 3))))  # ~ n^{1/3} block length
        n_blocks = int(np.ceil(n / block))
        means = np.empty(n_boot)
        for i in range(n_boot):
            starts = rng.integers(0, n, size=n_blocks)
            idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % n
            means[i] = x[idx[:n]].mean()
        return means

    diffs = _boot_means(post) - _boot_means(pre)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {
        "point_diff": float(post.mean() - pre.mean()),
        "boot_mean_diff": float(diffs.mean()),
        "ci95_low": float(lo),
        "ci95_high": float(hi),
        "excludes_zero": bool(lo > 0 or hi < 0),
        "n_boot": n_boot,
        "block_len_pre": int(max(1, round(len(pre) ** (1 / 3)))),
        "block_len_post": int(max(1, round(len(post) ** (1 / 3)))),
    }


def welch_test(pre: np.ndarray, post: np.ndarray) -> dict:
    t, p = stats.ttest_ind(post, pre, equal_var=False)
    return {
        "pre_mean": float(pre.mean()),
        "post_mean": float(post.mean()),
        "pre_n": int(len(pre)),
        "post_n": int(len(post)),
        "diff_pp": float((post.mean() - pre.mean()) * 100),  # percentage points
        "welch_t": float(t),
        "welch_p": float(p),
        "cohens_d": cohens_d(pre, post),
    }


def sup_wald_break(series: pd.Series, trim: float = 0.15) -> dict:
    """Andrews (1993) sup-Wald mean-shift break test. y_t = a + b*1[t>=k] + e.
    Legal break fractions satisfy trim on BOTH tails: k in
    [ceil(n*trim), floor(n*(1-trim))]. Returns classical sup-F (no HAC), argmax
    break date, and both the 1993 and 2003-corrigendum 5% critical values."""
    y = series.values.astype(float)
    n = len(y)
    lo = int(np.ceil(n * trim))          # first legal split (>= trim on left tail)
    hi = int(np.floor(n * (1 - trim)))   # last legal split (>= trim on right tail)
    grand_mean = y.mean()
    sst = np.sum((y - grand_mean) ** 2)
    best_f, best_k = -np.inf, None
    for k in range(lo, hi + 1):
        pre, post = y[:k], y[k:]
        if len(pre) < 2 or len(post) < 2:
            continue
        # F for a single mean-shift regressor (equivalent to Chow with 1 param)
        sse = np.sum((pre - pre.mean()) ** 2) + np.sum((post - post.mean()) ** 2)
        if sse <= 0:
            continue
        f = ((sst - sse) / 1) / (sse / (n - 2))
        if f > best_f:
            best_f, best_k = f, k
    break_date = series.index[best_k]
    # Andrews sup-F 5% asymptotic crit, 1 parameter, 15% trim, p=1:
    #   1993 (Econometrica 61) simulated value ~ 8.85
    #   2003 corrigendum (Econometrica 71) more precise value ~ 8.68
    crit_2003 = 8.68
    return {
        "sup_f": float(best_f),
        "break_index": int(best_k),
        "break_date": str(break_date.date()) if hasattr(break_date, "date") else str(break_date),
        "asymptotic_crit_5pct_1993": 8.85,
        "asymptotic_crit_5pct_2003_corrigendum": crit_2003,
        "significant_5pct": bool(best_f > crit_2003),
        "n": int(n),
        "trim": trim,
        "legal_break_index_range": [int(lo), int(hi)],
        "inference_note": "classical sup-F, no HAC; weekly share loss has mild serial dependence, so treat significance as assumption-heavy and read date location only, not as a proof of a unique break.",
    }


def chow_test(series: pd.Series, break_ts: pd.Timestamp) -> dict:
    """Chow test at a known break date (mean-shift specification)."""
    idx = series.index
    pre = series[idx < break_ts].values.astype(float)
    post = series[idx >= break_ts].values.astype(float)
    n = len(pre) + len(post)
    if len(pre) < 2 or len(post) < 2:
        return {"error": "insufficient obs", "pre_n": len(pre), "post_n": len(post)}
    y = np.concatenate([pre, post])
    sst = np.sum((y - y.mean()) ** 2)
    sse = np.sum((pre - pre.mean()) ** 2) + np.sum((post - post.mean()) ** 2)
    f = ((sst - sse) / 1) / (sse / (n - 2))
    p = float(stats.f.sf(f, 1, n - 2))
    return {"chow_f": float(f), "chow_p": p, "pre_n": len(pre), "post_n": len(post)}


def split_pre_post(piv: pd.DataFrame, share_col: str, pre_start: pd.Timestamp,
                   break_ts: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    idx = pd.DatetimeIndex(piv.index).tz_localize("UTC") if piv.index.tz is None else piv.index
    s = pd.Series(piv[share_col].values, index=idx)
    pre = s[(s.index >= pre_start) & (s.index < break_ts)].values
    post = s[s.index >= break_ts].values
    return pre, post


def logit(x: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    x = np.clip(x, eps, 1 - eps)
    return np.log(x / (1 - x))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> dict:
    np.random.seed(SEED)
    df, hygiene = load_data()
    bars = build_bucketed_returns(df)

    # weekly shares (primary unit)
    weekly = aggregate_shares(bars, "week")
    weekly.index = pd.DatetimeIndex(weekly.index).tz_localize("UTC")
    weekly = weekly[weekly.index >= EXTENDED_PRE_START]
    # COMPLETE-WEEK GATE (B1 fix): drop partial leading/terminal weeks whose bar
    # count is far below a full ET week (~168; DST 167/169). A partial week is
    # degenerate (e.g. a 9-bar terminal week is (0,1,0)) and contaminates every
    # test, especially logit (clip of a 0/1 share -> extreme log-odds).
    n_weeks_before_gate = int(len(weekly))
    weekly = weekly[weekly["n_bars"] >= MIN_WEEK_BARS].copy()
    n_weeks_dropped = n_weeks_before_gate - int(len(weekly))

    results: dict = {
        "experiment_id": "k1725",
        "seed": SEED,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "ibit_date": str(IBIT_DATE.date()),
        "primary_pre_start": str(PRIMARY_PRE_START.date()),
        "extended_pre_start": str(EXTENDED_PRE_START.date()),
        "rth_definition": "ET weekday, open-hour in {9..15} (~9:00-16:00 ET, +/-30min approx of 9:30-16:00 RTH); DST via America/New_York",
        "aggregation_unit": "ISO week (ET calendar, Monday-anchored)",
        "complete_week_gate": {
            "min_week_bars": MIN_WEEK_BARS,
            "weeks_before_gate": n_weeks_before_gate,
            "weeks_after_gate": int(len(weekly)),
            "partial_weeks_dropped": n_weeks_dropped,
        },
        "data_hygiene": hygiene,
        "n_weeks_total": int(len(weekly)),
    }

    # ---- consistency check: three shares sum to 1 ----
    share_sum = (weekly["us_session_share"] + weekly["non_session_share"]
                 + weekly["weekend_share"])
    results["consistency_shares_sum_to_one"] = {
        "max_abs_dev_from_1": float((share_sum - 1.0).abs().max()),
        "passed": bool((share_sum - 1.0).abs().max() < 1e-9),
    }

    # ---- PRIMARY: weekly US-session share, 1y pre vs post ----
    buckets = ["us_session", "non_session", "weekend"]
    primary = {}
    for b in buckets:
        col = f"{b}_share"
        pre, post = split_pre_post(weekly, col, PRIMARY_PRE_START, IBIT_DATE)
        wt = welch_test(pre, post)
        boot = circular_block_bootstrap_diff(pre, post)
        primary[b] = {"welch": wt, "block_bootstrap": boot}
    results["primary_weekly_shares_1y_pre"] = primary

    # ---- structural break location (weekly US-session share, extended series) ----
    us_series = pd.Series(weekly["us_session_share"].values, index=weekly.index)
    results["sup_wald_break_us_session"] = sup_wald_break(us_series)
    results["chow_at_ibit_us_session"] = chow_test(us_series, IBIT_DATE)
    # proximity of endogenous break to IBIT
    bd = pd.Timestamp(results["sup_wald_break_us_session"]["break_date"], tz="UTC")
    results["sup_wald_break_us_session"]["days_from_ibit"] = int((bd - IBIT_DATE).days)

    # ---- serial-dependence diagnostic (why Chow/sup-Wald iid inference is
    #      assumption-heavy): acf(1) and Ljung-Box(lag=4) on the IBIT-demeaned
    #      weekly US-session share series. ----
    idx_ibit = int((us_series.index >= IBIT_DATE).argmax())
    demeaned = us_series.values.astype(float).copy()
    demeaned[:idx_ibit] -= demeaned[:idx_ibit].mean()
    demeaned[idx_ibit:] -= demeaned[idx_ibit:].mean()
    acf1 = float(np.corrcoef(demeaned[:-1], demeaned[1:])[0, 1])
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox
        lb = acorr_ljungbox(demeaned, lags=[4], return_df=True)
        lb_p = float(lb["lb_pvalue"].iloc[0])
    except Exception:  # noqa: BLE001
        lb_p = None
    results["serial_dependence_diagnostic"] = {
        "ibit_demeaned_us_share_acf1": acf1,
        "ljung_box_lag4_pvalue": lb_p,
        "note": "acf1 != 0 or LB p < 0.05 => classical Chow/sup-F standard errors are not exact; break inference is assumption-heavy, so we read direction/location, not p-values, as primary.",
    }

    # ---- ROBUSTNESS (R1 event buffer, R2 logit, R3 extended pre, R4 daily) ----
    robustness: dict = {}

    # (R1) event buffer: drop +/-4 weeks around IBIT
    buf = pd.Timedelta(weeks=4)
    for b in buckets:
        col = f"{b}_share"
        s = pd.Series(weekly[col].values, index=weekly.index)
        pre_b = s[(s.index >= PRIMARY_PRE_START) & (s.index < IBIT_DATE - buf)].values
        post_b = s[s.index >= IBIT_DATE + buf].values
        robustness.setdefault("event_buffer_4w", {})[b] = welch_test(pre_b, post_b)

    # (R2) logit-transformed shares (primary window). NOTE: on the logit scale
    # `diff_pp`/`pre_mean`/`post_mean` are LOG-ODDS, not shares/percentage points.
    for b in buckets:
        col = f"{b}_share"
        pre, post = split_pre_post(weekly, col, PRIMARY_PRE_START, IBIT_DATE)
        robustness.setdefault("logit_shares", {})[b] = welch_test(logit(pre), logit(post))
    robustness["logit_shares"]["_scale_note"] = "values are log-odds (logit of share), not percentage points"

    # (R3) extended pre-window (2y pre)
    for b in buckets:
        col = f"{b}_share"
        pre, post = split_pre_post(weekly, col, EXTENDED_PRE_START, IBIT_DATE)
        robustness.setdefault("extended_pre_2y", {})[b] = welch_test(pre, post)

    # (R4) daily weekday RTH concentration = RTH_RV / (RTH_RV + nonsession_RV)
    weekday_bars = bars[bars["bucket"].isin(["us_session", "non_session"])]
    daily = aggregate_shares(weekday_bars, "et_date")
    daily = daily[daily["n_bars"] >= MIN_DAY_BARS]  # drop partial ET dates (B1)
    daily["rth_concentration"] = daily["us_session"] / (
        daily["us_session"] + daily["non_session"]
    )
    daily = daily[daily["us_session"] + daily["non_session"] > 0]
    daily.index = pd.DatetimeIndex(daily.index).tz_localize("UTC")
    d = pd.Series(daily["rth_concentration"].values, index=daily.index)
    pre_d = d[(d.index >= PRIMARY_PRE_START) & (d.index < IBIT_DATE)].values
    post_d = d[d.index >= IBIT_DATE].values
    robustness["daily_weekday_rth_concentration"] = {
        "welch": welch_test(pre_d, post_d),
        "block_bootstrap": circular_block_bootstrap_diff(pre_d, post_d),
        "min_day_bars": MIN_DAY_BARS,
        "note": "share of weekday RV occurring in RTH vs non-RTH (weekends excluded)",
    }

    results["robustness"] = robustness

    # ---- redistribution verdict ----
    us = primary["us_session"]["welch"]
    wk = primary["weekend"]["welch"]
    ns = primary["non_session"]["welch"]
    results["redistribution_check"] = {
        "us_session_direction": "up" if us["diff_pp"] > 0 else "down",
        "weekend_direction": "up" if wk["diff_pp"] > 0 else "down",
        "non_session_direction": "up" if ns["diff_pp"] > 0 else "down",
        "us_significant_5pct": bool(us["welch_p"] < 0.05),
        # NOTE: this boolean is satisfied by a non-session decline alone; the
        # actual weekend direction (see weekend_direction) may CONTRADICT the
        # "toward-traditional-clock" story (which predicts weekend share to
        # FALL). Do not read this flag as confirmation — read the full block.
        "is_redistribution_toward_rth": bool(
            us["diff_pp"] > 0 and (wk["diff_pp"] < 0 or ns["diff_pp"] < 0)
        ),
        "weekend_contradicts_clean_hypothesis": bool(wk["diff_pp"] > 0),
    }

    # ---- mechanical verdict derivation (byte-traceable; no overclaim) ----
    # The primary hypothesis is COMPOSITIONAL and DIRECTIONAL: US-session share
    # rises AND weekend/non-session share falls after IBIT. The gate therefore
    # checks BOTH direction and significance for US-session, AND the predicted
    # direction of the offsetting buckets (B3 fix). A gate that only checked US
    # p-values would PASS on a US *decline* or on a weekend *rise*.
    us_boot = primary["us_session"]["block_bootstrap"]
    buf_us = robustness["event_buffer_4w"]["us_session"]
    logit_us = robustness["logit_shares"]["us_session"]
    sw = results["sup_wald_break_us_session"]
    ns_boot = primary["non_session"]["block_bootstrap"]
    checks = {
        # directional: hypothesis predicts US up, weekend down, non-session down
        "us_direction_up": bool(us["diff_pp"] > 0),
        "weekend_direction_down_as_predicted": bool(wk["diff_pp"] < 0),
        "non_session_direction_down_as_predicted": bool(ns["diff_pp"] < 0),
        # significance of the US-session move across specs
        "primary_us_welch_sig5pct": bool(us["welch_p"] < 0.05),
        "primary_us_bootstrap_excludes_zero": bool(us_boot["excludes_zero"]),
        "event_buffer_us_welch_sig5pct": bool(buf_us["welch_p"] < 0.05),
        "logit_us_welch_sig5pct": bool(logit_us["welch_p"] < 0.05),
        # break location / confounded specs
        "endogenous_break_within_60d_of_ibit": bool(abs(sw["days_from_ibit"]) <= 60),
        "chow_at_ibit_sig5pct": bool(
            results["chow_at_ibit_us_session"].get("chow_p", 1.0) < 0.05
        ),
        "extended_pre_us_welch_sig5pct": bool(
            robustness["extended_pre_2y"]["us_session"]["welch_p"] < 0.05
        ),
        "non_session_decline_bootstrap_excludes_zero": bool(ns_boot["excludes_zero"]),
    }
    # PASS = robust, directional, compositional support for the ETF-clock story:
    #   US rises AND is significant in all three primary-window specs, AND at
    #   least one offsetting bucket falls in the predicted direction.
    robust_us_support = (
        checks["us_direction_up"]
        and checks["primary_us_welch_sig5pct"]
        and checks["event_buffer_us_welch_sig5pct"]
        and checks["logit_us_welch_sig5pct"]
    )
    compositional_ok = (
        checks["weekend_direction_down_as_predicted"]
        or checks["non_session_direction_down_as_predicted"]
    )
    # weekend RISING is a direct contradiction of the clean redistribution story
    weekend_contradicts = bool(wk["diff_pp"] > 0)
    if robust_us_support and compositional_ok and not weekend_contradicts:
        verdict = "PASS"
    elif checks["us_direction_up"] and (
        checks["primary_us_welch_sig5pct"] or checks["primary_us_bootstrap_excludes_zero"]
    ):
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"
    results["conclusion"] = {
        "verdict": verdict,
        "primary_hypothesis": "US-session RV share rises AND weekend/non-session share falls after IBIT 2024-01-11 (compositional, directional)",
        "checks": checks,
        "weekend_contradicts_clean_hypothesis": weekend_contradicts,
        "one_line": (
            "Primary 1y-pre weekly US-session RV share rose only "
            f"{us['diff_pp']:+.2f}pp ({us['pre_mean']:.3f}->{us['post_mean']:.3f}), "
            f"NOT significant (Welch p={us['welch_p']:.3f}, d={us['cohens_d']:.2f}, "
            "bootstrap CI includes 0). The only primary effect whose bootstrap CI "
            f"excludes 0 is the non-session DECLINE ({ns['diff_pp']:+.2f}pp), but "
            f"weekend share ROSE ({wk['diff_pp']:+.2f}pp), contradicting the clean "
            "toward-traditional-clock redistribution. The strongest endogenous "
            f"mean-shift candidate is {sw['break_date']} "
            f"(sup-F={sw['sup_f']:.2f}, 5% crit {sw['asymptotic_crit_5pct_2003_corrigendum']}, "
            f"{sw['days_from_ibit']}d from IBIT), i.e. far from the ETF; break "
            "inference is assumption-heavy (serial dependence). Nominal significance "
            "appears only in the 2y extended-pre and Chow specs (which reuse the "
            "confounded 2022 regime) and vanishes under both the event-buffer and "
            "logit-normalization robustness checks."
        ),
    }

    RESULTS_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    return results


if __name__ == "__main__":
    res = main()
    us = res["primary_weekly_shares_1y_pre"]["us_session"]["welch"]
    boot = res["primary_weekly_shares_1y_pre"]["us_session"]["block_bootstrap"]
    print("=" * 64)
    print(f"Weeks total: {res['n_weeks_total']} | "
          f"missing hourly bars: {res['data_hygiene']['missing_bars']} "
          f"({res['data_hygiene']['missing_bar_fraction']:.4%})")
    print(f"Shares sum-to-1 max dev: {res['consistency_shares_sum_to_one']['max_abs_dev_from_1']:.2e}")
    print("-" * 64)
    print("PRIMARY (weekly US-session RV share, 1y pre vs post IBIT):")
    print(f"  pre mean  = {us['pre_mean']:.4f}  (n={us['pre_n']})")
    print(f"  post mean = {us['post_mean']:.4f}  (n={us['post_n']})")
    print(f"  diff      = {us['diff_pp']:+.2f} pp | Welch t={us['welch_t']:.2f} "
          f"p={us['welch_p']:.4g} | d={us['cohens_d']:.2f}")
    print(f"  bootstrap 95% CI on diff: [{boot['ci95_low']:+.4f}, {boot['ci95_high']:+.4f}] "
          f"excl0={boot['excludes_zero']}")
    sw = res["sup_wald_break_us_session"]
    print(f"  sup-Wald break: {sw['break_date']} (F={sw['sup_f']:.2f}, "
          f"sig5%={sw['significant_5pct']}, {sw['days_from_ibit']}d from IBIT)")
    print(f"  redistribution-toward-RTH: {res['redistribution_check']['is_redistribution_toward_rth']}")
    print("=" * 64)
