"""
K1071: Right-Tail CASV Decomposition — Which Events Drive 0050.TW's Vol Spike?
==============================================================================

Motivation
----------
K1070 found the pivotal anomaly for Paper 2 (Taiwan VT):
  * Set C (N=999) mean CASV[-5,+5] = +2.78  (t=2.13, p=0.034, significant)
  * median CASV[-5,+5] = -2.80              (strongly negative)
  * Every of the four event sets (A/B/C/D) shows median < 0

Interpretation: MOST earnings days do NOT create an ETF vol spike.  A small
right-tail drives the positive mean.  This experiment decomposes that
right-tail so Paper 2 can state *which* events matter.

Research questions (matching prompt)
------------------------------------
Q1 Right-tail events (top 10% CASV) common characteristics
Q2 Do they cluster in crisis vs calm periods?
Q3 Sector clustering (tech / finance / traditional)?
Q4 Overlap with systematic shocks (FOMC / NFP / VIX spikes)?
Q5 After stripping top 10% — is the rest zero (median) or still positive?

Design
------
Step 1  Re-estimate per-event CAR/CASV for Set C (999 events), market model
        with ^TWII, seed=42, consistent with K1070.  For each event record:
          * event_date
          * CAR / SCAR / CASV [-5,+5]
          * announcing-company codes on that calendar date
          * announcement_count (# distinct TWSE-50 firms that date)
          * sector counts (tech / financial / traditional / other)
          * SPY return on event day (US co-movement)
          * VIX level and VIX change on event day
          * VIX regime (High if VIX >= 25, else Low)
Step 2  Rank by CASV[-5,+5]; flag top/middle/bottom.
Step 3  Analyze top 10% (N=100): time distribution, sector distribution,
        announcement-count distribution, VIX regime, SPY return distribution.
Step 4  Strip right tail and recompute mean/median CASV; compare to full
        sample.  Show that 90% of events have no aggregate vol spike.
Step 5  Winsorized / trimmed bootstrap CI for mean CASV.

Discipline
----------
* 0050.TW via clean_tw50_data (2014-01-02 split fix)
* Random seed 42 everywhere
* Worktree: no shared-state writes
* Output numbers must match the saved JSON (K1016)
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

matplotlib.use("Agg")
warnings.filterwarnings("ignore")

RNG = np.random.default_rng(42)
np.random.seed(42)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from volpred.utils import clean_tw50_data  # noqa: E402

DATA_FILE = PROJECT_ROOT / "財報公告日.txt"
START_TIME = time.time()

# ---------------------------------------------------------------------------
# Configuration  (must match K1070)
# ---------------------------------------------------------------------------
START_DATE = "2010-01-01"
END_DATE = "2025-12-31"
ESTIMATION_START = -250
ESTIMATION_END = -11
MIN_ESTIMATION = 100
EVENT_WINDOW = 5
MARKET_INDEX = "^TWII"
ETF_TICKER = "0050.TW"
WINDOW_LABEL = "[-5,+5]"
CRISIS_VIX = 25.0  # VIX threshold for "crisis" regime

# TWSE-50 constituents (same union as K1070).  Sector map below is used for
# per-event sector counts.
TWSE50_CODES = [
    # Semiconductor / Tech
    "2330", "2454", "2303", "2379", "2408", "2352", "3034", "3008", "3045",
    "3231", "2382", "3711", "2474", "2357", "2356",
    # Electronics / EMS / Components
    "2317", "2301", "2324", "2353", "2354", "2327", "2385", "2376", "2439",
    "2449", "2458", "2492", "3481", "2404", "2313", "2347", "3037", "2409",
    "6669", "3044",
    # Financial
    "2881", "2882", "2883", "2884", "2885", "2886", "2887", "2888", "2889",
    "2890", "2891", "2892", "5880", "2801", "2809", "2812", "2823", "2834",
    "2836", "2838",
    # Telecom / Media
    "2412", "3045", "4904", "3702",
    # Food / Retail
    "1216", "1301", "1303", "2912", "2801",
    # Traditional / Materials / Others
    "2002", "1101", "1102", "1216", "1326", "2105", "2207", "9910", "9921",
    "9933", "2207", "2105", "9914", "2615", "2618", "2610", "2603",
    "2912", "9945",
]
TWSE50_CODES = sorted(set(TWSE50_CODES))

# Sector classification.  TWSE convention: 23xx / 24xx / 33xx / 34xx / 37xx /
# 66xx are tech-related (semiconductor, EMS, components, networking).  28xx
# and 58xx are financials (holdings, banks).  11xx / 13xx / 29xx / 10xx /
# 99xx are traditional / food / transport / materials.  Telecom 2412 / 4904
# treated as "service".
TECH_PREFIX = ("23", "24", "33", "34", "37", "66")
FIN_PREFIX = ("28", "58")
TRAD_PREFIX = ("11", "13", "29", "10", "99", "21", "22", "26", "20")


def classify_sector(code: str) -> str:
    for p in TECH_PREFIX:
        if code.startswith(p):
            return "tech"
    for p in FIN_PREFIX:
        if code.startswith(p):
            return "financial"
    for p in TRAD_PREFIX:
        if code.startswith(p):
            return "traditional"
    return "other"


print("=" * 72)
print("K1071: Right-Tail CASV Decomposition (0050.TW)")
print("=" * 72)

# ---------------------------------------------------------------------------
# Part 0: Earnings announcements
# ---------------------------------------------------------------------------
print("\n[Part 0] Loading earnings announcement data (Big5)...")

with open(DATA_FILE, "rb") as f:
    raw = f.read().decode("big5", errors="replace")

records = []
for line in raw.strip().split("\n")[1:]:
    parts = line.strip().split("\t")
    if len(parts) >= 4:
        code = parts[0].strip()
        ym = parts[2].strip()
        date_str = parts[3].strip()
        if date_str:
            try:
                dt = pd.Timestamp(date_str.replace("/", "-"))
                records.append({"code": code, "ym": ym, "date": dt})
            except Exception:
                pass

ea_df = pd.DataFrame(records)
ea_in = ea_df[(ea_df["date"] >= START_DATE) & (ea_df["date"] <= END_DATE)].copy()
ea_in = ea_in.sort_values("date").reset_index(drop=True)
ea_50 = ea_in[ea_in["code"].isin(TWSE50_CODES)].copy()
print(f"  total announcement records: {len(ea_df):,}")
print(f"  TWSE-50 records 2010-2025:  {len(ea_50):,}")
print(f"  unique companies:           {ea_50['code'].nunique():,}")

# ---------------------------------------------------------------------------
# Part 1: Prices (0050.TW, ^TWII, SPY, ^VIX)
# ---------------------------------------------------------------------------
print("\n[Part 1] Downloading 0050.TW + ^TWII + SPY + ^VIX...")


def fetch_close(ticker: str) -> pd.Series:
    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                     progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].astype(float)


etf_raw = fetch_close(ETF_TICKER)
etf_clean_px, etf_clean_ret = clean_tw50_data(etf_raw)
etf_ret = etf_clean_ret.dropna()

mkt_close = fetch_close(MARKET_INDEX)
mkt_ret = np.log(mkt_close / mkt_close.shift(1)).dropna()

common_idx = etf_ret.index.intersection(mkt_ret.index)
etf_a = etf_ret.reindex(common_idx)
mkt_a = mkt_ret.reindex(common_idx)
trading_days = common_idx
n_days = len(trading_days)
print(f"  0050.TW N={len(etf_ret):,}, ^TWII N={len(mkt_ret):,}, "
      f"common N={n_days:,}")

# SPY return + VIX level on the same Taiwan trading-day calendar.  We join by
# calendar date so an event on a Taiwan date maps to the *most recent* US
# close.  For the event-day market-context columns we use the SAME calendar
# date SPY close, i.e. the close that had just occurred in the prior US
# session (Asia opens ~13 hours after US close on the same calendar date,
# so the US close on T-1 UTC is the closest information available to a
# Taiwan T open).  For a robustness check we also record the SPY return on
# the prior US trading day.
spy_close = fetch_close("SPY")
spy_ret = np.log(spy_close / spy_close.shift(1)).dropna()
# Align SPY to Taiwan calendar: use last SPY close on-or-before each Taiwan
# trading day (asof merge).
spy_aligned = spy_ret.reindex(trading_days, method="ffill")
# VIX level on the *US session ending on-or-before* the Taiwan date.
vix_close = fetch_close("^VIX").reindex(trading_days, method="ffill")
vix_change = vix_close.diff()
print(f"  SPY N_aligned={spy_aligned.notna().sum():,}, "
      f"VIX aligned mean={float(vix_close.mean()):.2f}")

# ---------------------------------------------------------------------------
# Part 2: Build Set C events (TWSE-50 union)
# ---------------------------------------------------------------------------
print("\n[Part 2] Building Set C events (TWSE-50 union)...")

# map calendar date -> first Taiwan trading day on-or-after that date.
# Also accumulate the list of firms announcing on that *calendar* date.


def map_calendar_to_trading_pos(calendar_date: pd.Timestamp) -> int | None:
    pos = trading_days.searchsorted(calendar_date)
    if pos >= n_days:
        return None
    return int(pos)


# For each TWSE-50 calendar date, group into a single event.  If a calendar
# date is a non-trading day, roll to the next trading day.  Multiple
# calendar dates can roll to the same trading day (e.g. Friday announcements
# and weekend announcements both land on Monday); these merge into one
# event with a combined firm list.
cal_to_firms: dict[pd.Timestamp, list[str]] = {}
for _, row in ea_50.iterrows():
    cal_to_firms.setdefault(row["date"].normalize(), []).append(row["code"])

# Now collapse to trading-day positions.
pos_to_firms: dict[int, list[str]] = {}
pos_to_calendar: dict[int, list[pd.Timestamp]] = {}
for cal_date, firms in cal_to_firms.items():
    pos = map_calendar_to_trading_pos(cal_date)
    if pos is None:
        continue
    pos_to_firms.setdefault(pos, []).extend(firms)
    pos_to_calendar.setdefault(pos, []).append(cal_date)

event_positions = sorted(pos_to_firms.keys())
print(f"  calendar announcement dates: {len(cal_to_firms):,}")
print(f"  unique trading-day events:   {len(event_positions):,}")

# ---------------------------------------------------------------------------
# Part 3: Market model CAR/CASV per event + features
# ---------------------------------------------------------------------------
print("\n[Part 3] Running CAR/CASV + feature collection...")


def event_study_one(pos: int, firms: list[str],
                    cal_dates: list[pd.Timestamp]) -> dict | None:
    est_start = pos + ESTIMATION_START
    est_end = pos + ESTIMATION_END
    if est_start < 0:
        return None
    if est_end - est_start + 1 < MIN_ESTIMATION:
        return None
    if pos + EVENT_WINDOW >= n_days:
        return None
    if pos - EVENT_WINDOW < 0:
        return None

    est_dates = trading_days[est_start: est_end + 1]
    r_i_est = etf_a.reindex(est_dates).dropna()
    r_m_est = mkt_a.reindex(r_i_est.index)
    if len(r_i_est) < MIN_ESTIMATION:
        return None

    X = np.column_stack([np.ones(len(r_m_est)), r_m_est.values])
    y = r_i_est.values
    try:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    alpha, beta = float(coef[0]), float(coef[1])
    resid = y - X @ coef
    sigma2 = float(np.var(resid, ddof=2))
    if not np.isfinite(sigma2) or sigma2 <= 0:
        return None

    ev_positions = list(range(pos - EVENT_WINDOW, pos + EVENT_WINDOW + 1))
    ev_dates = trading_days[ev_positions]
    r_i_ev = etf_a.reindex(ev_dates).values
    r_m_ev = mkt_a.reindex(ev_dates).values
    ar = r_i_ev - (alpha + beta * r_m_ev)
    if np.any(~np.isfinite(ar)):
        return None

    L = 2 * EVENT_WINDOW + 1
    car = float(np.sum(ar))
    scar = float(car / np.sqrt(L * sigma2))
    casv = float(np.sum(ar ** 2 / sigma2 - 1.0))

    date_t = trading_days[pos]
    spy_t = float(spy_aligned.loc[date_t]) if pd.notna(spy_aligned.loc[date_t]) else np.nan
    vix_t = float(vix_close.loc[date_t]) if pd.notna(vix_close.loc[date_t]) else np.nan
    vix_d = float(vix_change.loc[date_t]) if pd.notna(vix_change.loc[date_t]) else np.nan

    sector_counts = Counter(classify_sector(c) for c in firms)

    return {
        "event_pos": int(pos),
        "event_date": date_t.strftime("%Y-%m-%d"),
        "year": int(date_t.year),
        "month": int(date_t.month),
        "alpha": alpha,
        "beta": beta,
        "sigma2": sigma2,
        "CAR": car,
        "SCAR": scar,
        "CASV": casv,
        "n_firms": int(len(firms)),
        "firms_tech": int(sector_counts.get("tech", 0)),
        "firms_financial": int(sector_counts.get("financial", 0)),
        "firms_traditional": int(sector_counts.get("traditional", 0)),
        "firms_other": int(sector_counts.get("other", 0)),
        "firm_codes": sorted(set(firms)),
        "calendar_dates": [d.strftime("%Y-%m-%d") for d in cal_dates],
        "spy_return_aligned": spy_t,
        "vix_level": vix_t,
        "vix_change": vix_d,
        "vix_regime": ("high" if (np.isfinite(vix_t) and vix_t >= CRISIS_VIX)
                       else "low"),
    }


records: list[dict] = []
for pos in event_positions:
    rec = event_study_one(pos, pos_to_firms[pos], pos_to_calendar[pos])
    if rec is not None:
        records.append(rec)

df = pd.DataFrame(records)
print(f"  events usable : {len(df):,}")
print(f"  mean CASV     : {df['CASV'].mean():+.3f}")
print(f"  median CASV   : {df['CASV'].median():+.3f}")
print(f"  mean CAR      : {df['CAR'].mean():+.6f}")

# ---------------------------------------------------------------------------
# Part 4: Rank and split top/middle/bottom
# ---------------------------------------------------------------------------
print("\n[Part 4] Right-tail / Middle / Bottom classification...")

df = df.sort_values("CASV").reset_index(drop=True)
N = len(df)
n_tail = int(round(N * 0.10))
bottom_idx = df.index[:n_tail]
top_idx = df.index[-n_tail:]
middle_idx = df.index[n_tail: N - n_tail]

df["tail_group"] = "middle"
df.loc[bottom_idx, "tail_group"] = "bottom10"
df.loc[top_idx, "tail_group"] = "top10"

top_df = df.loc[top_idx].copy()
mid_df = df.loc[middle_idx].copy()
bot_df = df.loc[bottom_idx].copy()

print(f"  N total    = {N}")
print(f"  top 10%    = {len(top_df)}")
print(f"  middle 80% = {len(mid_df)}")
print(f"  bottom 10% = {len(bot_df)}")
print(f"  top 10% CASV range:    "
      f"[{top_df['CASV'].min():+.2f}, {top_df['CASV'].max():+.2f}]  "
      f"mean={top_df['CASV'].mean():+.2f}")
print(f"  middle 80% CASV range: "
      f"[{mid_df['CASV'].min():+.2f}, {mid_df['CASV'].max():+.2f}]  "
      f"mean={mid_df['CASV'].mean():+.2f}")
print(f"  bottom 10% CASV range: "
      f"[{bot_df['CASV'].min():+.2f}, {bot_df['CASV'].max():+.2f}]  "
      f"mean={bot_df['CASV'].mean():+.2f}")

# ---------------------------------------------------------------------------
# Part 5: Top-10% feature analysis
# ---------------------------------------------------------------------------
print("\n[Part 5] Top-10% feature analysis...")

# A. Time distribution
top_year = Counter(top_df["year"].tolist())
mid_year = Counter(mid_df["year"].tolist())
bot_year = Counter(bot_df["year"].tolist())
all_year = Counter(df["year"].tolist())

# Fisher / chi2 style: share of top in each year vs share of overall
year_stats = []
for yr in sorted(all_year.keys()):
    n_total = all_year[yr]
    n_top = top_year.get(yr, 0)
    expected = len(top_df) * n_total / N
    year_stats.append({
        "year": yr, "n_events": n_total,
        "n_top10": n_top,
        "expected_top10": round(expected, 2),
        "top10_share": n_top / n_total if n_total else 0.0,
    })

# B. Announcement count
ann_count_top = top_df["n_firms"].describe().to_dict()
ann_count_mid = mid_df["n_firms"].describe().to_dict()
ann_ks = stats.ks_2samp(top_df["n_firms"], mid_df["n_firms"])
ann_mw = stats.mannwhitneyu(top_df["n_firms"], mid_df["n_firms"],
                             alternative="two-sided")

# C. Sector
top_sector_sum = {
    "tech": int(top_df["firms_tech"].sum()),
    "financial": int(top_df["firms_financial"].sum()),
    "traditional": int(top_df["firms_traditional"].sum()),
    "other": int(top_df["firms_other"].sum()),
}
mid_sector_sum = {
    "tech": int(mid_df["firms_tech"].sum()),
    "financial": int(mid_df["firms_financial"].sum()),
    "traditional": int(mid_df["firms_traditional"].sum()),
    "other": int(mid_df["firms_other"].sum()),
}
all_sector_sum = {
    "tech": int(df["firms_tech"].sum()),
    "financial": int(df["firms_financial"].sum()),
    "traditional": int(df["firms_traditional"].sum()),
    "other": int(df["firms_other"].sum()),
}

# Share per event (normalize by event's total firms)
def sector_share(d: pd.DataFrame) -> dict[str, float]:
    total = (d["firms_tech"] + d["firms_financial"]
             + d["firms_traditional"] + d["firms_other"]).sum()
    if total == 0:
        return {"tech": 0.0, "financial": 0.0,
                "traditional": 0.0, "other": 0.0}
    return {
        "tech": float(d["firms_tech"].sum() / total),
        "financial": float(d["firms_financial"].sum() / total),
        "traditional": float(d["firms_traditional"].sum() / total),
        "other": float(d["firms_other"].sum() / total),
    }


top_sector_share = sector_share(top_df)
mid_sector_share = sector_share(mid_df)
all_sector_share = sector_share(df)

# Fisher-like 2x2 table for tech: tech vs non-tech  x  top vs mid
def two_by_two(d_top: pd.DataFrame, d_mid: pd.DataFrame,
               col: str) -> tuple[list[list[int]], float, float]:
    t_top = int(d_top[col].sum())
    nt_top = int((d_top["firms_tech"] + d_top["firms_financial"]
                  + d_top["firms_traditional"] + d_top["firms_other"]).sum()
                 - t_top)
    t_mid = int(d_mid[col].sum())
    nt_mid = int((d_mid["firms_tech"] + d_mid["firms_financial"]
                  + d_mid["firms_traditional"] + d_mid["firms_other"]).sum()
                 - t_mid)
    table = [[t_top, nt_top], [t_mid, nt_mid]]
    try:
        odds, pval = stats.fisher_exact(table)
    except Exception:
        odds, pval = (float("nan"), float("nan"))
    return table, float(odds), float(pval)


tech_table, tech_odds, tech_p = two_by_two(top_df, mid_df, "firms_tech")
fin_table, fin_odds, fin_p = two_by_two(top_df, mid_df, "firms_financial")
trad_table, trad_odds, trad_p = two_by_two(top_df, mid_df, "firms_traditional")

# D. Market co-movement
vix_top = top_df["vix_level"].dropna()
vix_mid = mid_df["vix_level"].dropna()
vix_all = df["vix_level"].dropna()

vixd_top = top_df["vix_change"].dropna()
vixd_mid = mid_df["vix_change"].dropna()

spy_top = top_df["spy_return_aligned"].dropna()
spy_mid = mid_df["spy_return_aligned"].dropna()

# VIX high (>= 25) regime share
top_highvix_share = float((top_df["vix_regime"] == "high").mean())
mid_highvix_share = float((mid_df["vix_regime"] == "high").mean())
all_highvix_share = float((df["vix_regime"] == "high").mean())

# 2x2 high-VIX x top-vs-mid
hv_tab = [[int((top_df["vix_regime"] == "high").sum()),
           int((top_df["vix_regime"] == "low").sum())],
          [int((mid_df["vix_regime"] == "high").sum()),
           int((mid_df["vix_regime"] == "low").sum())]]
try:
    _, hv_p = stats.fisher_exact(hv_tab)
    hv_p = float(hv_p)
except Exception:
    hv_p = float("nan")

# KS / MannWhitney on VIX level
ks_vix = stats.ks_2samp(vix_top, vix_mid)
mw_vix = stats.mannwhitneyu(vix_top, vix_mid, alternative="two-sided")

# SPY absolute-return (large SPY moves)
spy_abs_top = spy_top.abs()
spy_abs_mid = spy_mid.abs()
ks_spy = stats.ks_2samp(spy_abs_top, spy_abs_mid)
mw_spy = stats.mannwhitneyu(spy_abs_top, spy_abs_mid, alternative="two-sided")

print(f"  announcement count    top N={top_df['n_firms'].mean():.2f} "
      f"vs mid N={mid_df['n_firms'].mean():.2f} "
      f"(KS p={ann_ks.pvalue:.3f}, MW p={ann_mw.pvalue:.3f})")
print(f"  high-VIX regime share top={top_highvix_share:.3f} "
      f"vs mid={mid_highvix_share:.3f} (Fisher p={hv_p:.3g})")
print(f"  sector share  top tech={top_sector_share['tech']:.3f} "
      f"vs mid tech={mid_sector_share['tech']:.3f} "
      f"(Fisher odds={tech_odds:.2f}, p={tech_p:.3g})")
print(f"  sector share  top fin ={top_sector_share['financial']:.3f} "
      f"vs mid fin={mid_sector_share['financial']:.3f} "
      f"(Fisher odds={fin_odds:.2f}, p={fin_p:.3g})")

# ---------------------------------------------------------------------------
# Part 6: Strip right tail and recompute
# ---------------------------------------------------------------------------
print("\n[Part 6] Strip right tail and recompute...")


def one_sample_t(vec: np.ndarray) -> tuple[float, float, int]:
    x = np.asarray(vec, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan"), n
    mean = float(x.mean())
    se = float(x.std(ddof=1) / np.sqrt(n))
    if se == 0:
        return float("nan"), float("nan"), n
    t = mean / se
    p = 2.0 * (1.0 - stats.t.cdf(abs(t), df=n - 1))
    return float(t), float(p), n


stripped_results = {}
subsets = {
    "full_N999":           df["CASV"].to_numpy(),
    "excl_top10pct":       df.iloc[:N - n_tail]["CASV"].to_numpy(),
    "excl_top5pct":        df.iloc[:N - int(round(N * 0.05))]["CASV"].to_numpy(),
    "excl_both_tails_10":  df.iloc[n_tail:N - n_tail]["CASV"].to_numpy(),
    "excl_both_tails_5":   df.iloc[int(round(N * 0.05)):N - int(round(N * 0.05))]
                             ["CASV"].to_numpy(),
}
for name, arr in subsets.items():
    t, p, n = one_sample_t(arr)
    stripped_results[name] = {
        "n": int(n),
        "mean_CASV": float(np.nanmean(arr)) if n else float("nan"),
        "median_CASV": float(np.nanmedian(arr)) if n else float("nan"),
        "std_CASV": float(np.nanstd(arr, ddof=1)) if n > 1 else float("nan"),
        "t_stat": t,
        "p_value": p,
    }
    print(f"  {name:22s}  N={n:4d}  mean={stripped_results[name]['mean_CASV']:+.3f}  "
          f"median={stripped_results[name]['median_CASV']:+.3f}  "
          f"t={t:+.2f}  p={p:.3f}")

# Winsorized / trimmed mean
casv_full = df["CASV"].to_numpy()
wins_95 = stats.mstats.winsorize(casv_full, limits=[0.025, 0.025])
wins_90 = stats.mstats.winsorize(casv_full, limits=[0.05, 0.05])
trim_95 = stats.trim_mean(casv_full, 0.025)
trim_90 = stats.trim_mean(casv_full, 0.05)

winsor_results = {
    "raw_mean":          float(np.mean(casv_full)),
    "raw_median":        float(np.median(casv_full)),
    "winsor_95_mean":    float(np.mean(wins_95)),
    "winsor_90_mean":    float(np.mean(wins_90)),
    "trimmed_95_mean":   float(trim_95),
    "trimmed_90_mean":   float(trim_90),
}
print(f"\n  winsor/trim comparison:")
for k, v in winsor_results.items():
    print(f"    {k:22s}  {v:+.3f}")

# Bootstrap CI for raw mean vs trimmed mean
def bootstrap_mean(arr: np.ndarray, reps: int, trim: float = 0.0,
                   seed: int = 42) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    arr = np.asarray(arr, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    out = np.empty(reps)
    for i in range(reps):
        idx = rng.integers(0, n, n)
        sample = arr[idx]
        if trim > 0:
            out[i] = stats.trim_mean(sample, trim)
        else:
            out[i] = sample.mean()
    return float(np.mean(out)), float(np.percentile(out, 2.5)), \
        float(np.percentile(out, 97.5))


boot_raw = bootstrap_mean(casv_full, 2000, 0.0, seed=42)
boot_t95 = bootstrap_mean(casv_full, 2000, 0.025, seed=42)
boot_t90 = bootstrap_mean(casv_full, 2000, 0.05, seed=42)

bootstrap_results = {
    "raw_mean":        {"mean": boot_raw[0], "ci2.5": boot_raw[1], "ci97.5": boot_raw[2]},
    "trimmed_95_mean": {"mean": boot_t95[0], "ci2.5": boot_t95[1], "ci97.5": boot_t95[2]},
    "trimmed_90_mean": {"mean": boot_t90[0], "ci2.5": boot_t90[1], "ci97.5": boot_t90[2]},
}
print("\n  bootstrap 95% CI (2000 reps):")
for k, v in bootstrap_results.items():
    print(f"    {k:22s}  mean={v['mean']:+.3f}  CI[{v['ci2.5']:+.3f}, {v['ci97.5']:+.3f}]")

# ---------------------------------------------------------------------------
# Part 7: Crisis regime analysis
# ---------------------------------------------------------------------------
print("\n[Part 7] Crisis regime analysis...")

regime_groups = df.groupby("vix_regime")
regime_stats: dict[str, dict] = {}
for name, g in regime_groups:
    t, p, n = one_sample_t(g["CASV"].to_numpy())
    regime_stats[str(name)] = {
        "n": int(n),
        "mean_CASV": float(g["CASV"].mean()),
        "median_CASV": float(g["CASV"].median()),
        "std_CASV": float(g["CASV"].std(ddof=1)) if n > 1 else float("nan"),
        "t_stat": t,
        "p_value": p,
        "mean_CAR": float(g["CAR"].mean()),
        "share_of_sample": float(len(g) / N),
    }
    print(f"  {name:5s}  N={n:4d}  mean_CASV={regime_stats[str(name)]['mean_CASV']:+.3f}  "
          f"t={t:+.2f}  p={p:.3f}")

# ---------------------------------------------------------------------------
# Part 8: Plots
# ---------------------------------------------------------------------------
print("\n[Part 8] Generating plots...")

plt.rcParams["axes.unicode_minus"] = False

# Plot 1: CASV distribution with right-tail highlighted (2-panel: zoomed + full log)
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
casv_arr = df["CASV"].to_numpy()
mid_mask = (df["tail_group"] == "middle").to_numpy()
top_mask = (df["tail_group"] == "top10").to_numpy()
bot_mask = (df["tail_group"] == "bottom10").to_numpy()

# Left panel: zoomed view [-10, 50] (captures 98% of events)
ax = axes[0]
zoom_lo, zoom_hi = -12, 50
bins = np.linspace(zoom_lo, zoom_hi, 60)
ax.hist(casv_arr[mid_mask], bins=bins, color="#9ca3af",
        alpha=0.85, label=f"middle 80% (N={mid_mask.sum()})")
ax.hist(casv_arr[top_mask & (casv_arr <= zoom_hi)], bins=bins, color="#dc2626",
        alpha=0.90, label=f"top 10% in view (N={int((top_mask & (casv_arr <= zoom_hi)).sum())})")
ax.hist(casv_arr[bot_mask], bins=bins, color="#2563eb",
        alpha=0.90, label=f"bottom 10% (N={bot_mask.sum()})")
ax.axvline(0, color="black", linestyle="--", lw=1)
ax.axvline(df["CASV"].mean(), color="red", linestyle=":", lw=2,
           label=f"mean = {df['CASV'].mean():+.2f}")
ax.axvline(df["CASV"].median(), color="navy", linestyle=":", lw=2,
           label=f"median = {df['CASV'].median():+.2f}")
n_offscale = int((casv_arr > zoom_hi).sum())
ax.set_xlabel("CASV [-5,+5]  (zoomed)")
ax.set_ylabel("events")
ax.set_title(f"A. Zoomed view  [{zoom_lo},{zoom_hi}]\n"
             f"{n_offscale} right-tail events off-scale (max={casv_arr.max():.0f})")
ax.legend(loc="upper right", fontsize=8)
ax.grid(alpha=0.3)

# Right panel: log-y view of the full range
ax = axes[1]
full_bins = np.concatenate([
    np.linspace(casv_arr.min(), 50, 40),
    np.linspace(50, casv_arr.max(), 20)[1:],
])
ax.hist(casv_arr[mid_mask], bins=full_bins, color="#9ca3af",
        alpha=0.85, label=f"middle 80%")
ax.hist(casv_arr[top_mask], bins=full_bins, color="#dc2626",
        alpha=0.90, label=f"top 10%")
ax.hist(casv_arr[bot_mask], bins=full_bins, color="#2563eb",
        alpha=0.90, label=f"bottom 10%")
ax.set_yscale("log")
ax.axvline(0, color="black", linestyle="--", lw=1)
ax.set_xlabel(f"CASV [-5,+5]  (full range, max={casv_arr.max():.0f})")
ax.set_ylabel("events (log)")
ax.set_title("B. Full range, log-y\n"
             "shows the extreme right tail")
ax.legend(loc="upper right", fontsize=9)
ax.grid(alpha=0.3, which="both")

plt.suptitle(f"K1071 — Set C CASV distribution (N={N}).  "
             f"Right-tail drives the positive mean (see Part 6).")
plt.tight_layout()
fig.savefig(SCRIPT_DIR / "k1071_casv_distribution.png", dpi=130)
plt.close(fig)

# Plot 2: Top 10% feature panel (4 subplots)
fig, axes = plt.subplots(2, 2, figsize=(13, 9))

# 2A year distribution
ax = axes[0, 0]
years_sorted = sorted(all_year.keys())
x = np.arange(len(years_sorted))
w = 0.38
total_counts = [all_year[y] for y in years_sorted]
top_counts = [top_year.get(y, 0) for y in years_sorted]
ax.bar(x - w / 2, total_counts, w, color="#9ca3af", label="all events")
ax.bar(x + w / 2, top_counts, w, color="#dc2626", label="top 10%")
ax.set_xticks(x)
ax.set_xticklabels(years_sorted, rotation=45)
ax.set_ylabel("events")
ax.set_title("A. Year distribution — all vs top 10%")
ax.legend()
ax.grid(axis="y", alpha=0.3)

# 2B announcement count distribution
ax = axes[0, 1]
max_ann = int(max(df["n_firms"].max(), 1))
bins_ann = np.arange(0.5, max_ann + 1.5, 1)
ax.hist(mid_df["n_firms"], bins=bins_ann, color="#9ca3af", alpha=0.85,
        label="middle 80%", density=True)
ax.hist(top_df["n_firms"], bins=bins_ann, color="#dc2626", alpha=0.85,
        label="top 10%", density=True)
ax.set_xlabel("# firms announcing (per event date)")
ax.set_ylabel("density")
ax.set_title(f"B. Announcement count  KS p={ann_ks.pvalue:.3f}")
ax.legend()
ax.grid(alpha=0.3)

# 2C sector share
ax = axes[1, 0]
sectors = ["tech", "financial", "traditional", "other"]
top_vals = [top_sector_share[s] for s in sectors]
mid_vals = [mid_sector_share[s] for s in sectors]
xx = np.arange(len(sectors))
ax.bar(xx - w / 2, mid_vals, w, color="#9ca3af", label="middle 80%")
ax.bar(xx + w / 2, top_vals, w, color="#dc2626", label="top 10%")
ax.set_xticks(xx)
ax.set_xticklabels(sectors)
ax.set_ylabel("share of announcing firms")
ax.set_title("C. Sector share (per firm)")
ax.legend()
ax.grid(axis="y", alpha=0.3)

# 2D VIX level distribution
ax = axes[1, 1]
bins_vix = np.linspace(0, max(60, float(vix_all.max())), 40)
ax.hist(vix_mid, bins=bins_vix, color="#9ca3af", alpha=0.85,
        label="middle 80%", density=True)
ax.hist(vix_top, bins=bins_vix, color="#dc2626", alpha=0.85,
        label="top 10%", density=True)
ax.axvline(CRISIS_VIX, color="black", linestyle="--", lw=1,
           label=f"VIX={CRISIS_VIX:.0f}")
ax.set_xlabel("VIX level (on event date)")
ax.set_ylabel("density")
ax.set_title(f"D. VIX level  MW p={mw_vix.pvalue:.3f}")
ax.legend()
ax.grid(alpha=0.3)

plt.suptitle("K1071 — Top 10% CASV features vs middle 80%")
plt.tight_layout()
fig.savefig(SCRIPT_DIR / "k1071_top10pct_features.png", dpi=130)
plt.close(fig)

# Plot 3: Winsorized / trimmed comparison bar
fig, ax = plt.subplots(figsize=(10, 5))
labels = ["raw mean", "winsor 95%", "winsor 90%",
          "trim 95%", "trim 90%", "raw median"]
vals = [winsor_results["raw_mean"], winsor_results["winsor_95_mean"],
        winsor_results["winsor_90_mean"], winsor_results["trimmed_95_mean"],
        winsor_results["trimmed_90_mean"], winsor_results["raw_median"]]
colors = ["#dc2626", "#f59e0b", "#f59e0b", "#3b82f6", "#3b82f6", "#1e3a8a"]
bars = ax.bar(labels, vals, color=colors)
for bar, v in zip(bars, vals):
    ax.text(bar.get_x() + bar.get_width() / 2, v + (0.1 if v >= 0 else -0.3),
            f"{v:+.2f}", ha="center",
            va="bottom" if v >= 0 else "top", fontsize=9)
ax.axhline(0, color="black", lw=1)
ax.set_ylabel("CASV statistic")
ax.set_title(f"K1071 — Raw vs robust estimators of CASV mean  (N={N})")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
fig.savefig(SCRIPT_DIR / "k1071_winsorized_tests.png", dpi=130)
plt.close(fig)

# Plot 4: Crisis regime
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
ax = axes[0]
regimes = ["low", "high"]
means = [regime_stats[r]["mean_CASV"] if r in regime_stats else float("nan")
         for r in regimes]
medians = [regime_stats[r]["median_CASV"] if r in regime_stats else float("nan")
           for r in regimes]
xx = np.arange(len(regimes))
ax.bar(xx - 0.2, means, 0.38, color="#dc2626", label="mean CASV")
ax.bar(xx + 0.2, medians, 0.38, color="#1e3a8a", label="median CASV")
for i, r in enumerate(regimes):
    if r in regime_stats:
        ax.text(i, max(means[i], medians[i]) + 0.3,
                f"N={regime_stats[r]['n']}", ha="center", fontsize=9)
ax.axhline(0, color="black", lw=1)
ax.set_xticks(xx)
ax.set_xticklabels([f"low (VIX<{CRISIS_VIX:.0f})",
                    f"high (VIX≥{CRISIS_VIX:.0f})"])
ax.set_ylabel("CASV [-5,+5]")
ax.set_title("A. CASV by VIX regime")
ax.legend()
ax.grid(axis="y", alpha=0.3)

# Top 10% share by year line
ax = axes[1]
yrs = [s["year"] for s in year_stats]
share = [s["top10_share"] for s in year_stats]
baseline = 0.10
ax.plot(yrs, share, marker="o", color="#dc2626", label="top 10% share")
ax.axhline(baseline, color="black", linestyle="--",
           label=f"uniform baseline = {baseline:.2f}")
ax.set_xlabel("year")
ax.set_ylabel("share of events that are top 10% CASV")
ax.set_title("B. Top 10% events by year")
ax.legend()
ax.grid(alpha=0.3)

plt.suptitle("K1071 — Crisis regime + year-by-year right-tail")
plt.tight_layout()
fig.savefig(SCRIPT_DIR / "k1071_crisis_regime.png", dpi=130)
plt.close(fig)

print("  saved 4 plots")

# ---------------------------------------------------------------------------
# Part 9: Save JSON
# ---------------------------------------------------------------------------
print("\n[Part 9] Saving results JSON...")

runtime = time.time() - START_TIME

# Top-10% event list (lightweight): event_date, CASV, n_firms, vix_level,
# vix_regime, firm_codes
top10_list = []
for _, row in top_df.sort_values("CASV", ascending=False).iterrows():
    top10_list.append({
        "event_date": row["event_date"],
        "CASV": float(row["CASV"]),
        "CAR": float(row["CAR"]),
        "n_firms": int(row["n_firms"]),
        "firms": list(row["firm_codes"]),
        "vix_level": None if not np.isfinite(row["vix_level"]) else float(row["vix_level"]),
        "vix_change": None if not np.isfinite(row["vix_change"]) else float(row["vix_change"]),
        "vix_regime": row["vix_regime"],
        "spy_return_aligned": None if not np.isfinite(row["spy_return_aligned"])
                              else float(row["spy_return_aligned"]),
        "firms_tech": int(row["firms_tech"]),
        "firms_financial": int(row["firms_financial"]),
        "firms_traditional": int(row["firms_traditional"]),
        "firms_other": int(row["firms_other"]),
    })

output = {
    "experiment_id": "K1071",
    "title": "Right-Tail CASV Decomposition — Which Events Drive 0050.TW's Vol Spike?",
    "proposer": "Claude (Paper 2 Taiwan VT track)",
    "executor": "Claude (worktree)",
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "runtime_seconds": round(runtime, 1),
    "random_seed": 42,
    "config": {
        "start_date": START_DATE,
        "end_date": END_DATE,
        "event_window": f"[-{EVENT_WINDOW},+{EVENT_WINDOW}]",
        "estimation_window": f"[{ESTIMATION_START},{ESTIMATION_END}]",
        "min_estimation": MIN_ESTIMATION,
        "market_index": MARKET_INDEX,
        "etf_ticker": ETF_TICKER,
        "crisis_vix_threshold": CRISIS_VIX,
        "twse50_codes": TWSE50_CODES,
    },
    "data_summary": {
        "n_announcement_records": int(len(ea_in)),
        "n_twse50_records": int(len(ea_50)),
        "n_unique_companies_twse50": int(ea_50["code"].nunique()),
        "n_trading_days": int(n_days),
        "trading_day_start": str(trading_days.min().date()),
        "trading_day_end": str(trading_days.max().date()),
    },
    "setC_reproduction": {
        "n_events_attempted": int(len(event_positions)),
        "n_events_used": int(N),
        "mean_CAR": float(df["CAR"].mean()),
        "std_CAR": float(df["CAR"].std(ddof=1)),
        "mean_CASV": float(df["CASV"].mean()),
        "median_CASV": float(df["CASV"].median()),
        "std_CASV": float(df["CASV"].std(ddof=1)),
        "note": "Reproduces K1070 Set C (TWSE-50 union) per-event CAR/CASV.",
    },
    "tail_split": {
        "n_total": int(N),
        "n_top10": int(len(top_df)),
        "n_middle80": int(len(mid_df)),
        "n_bottom10": int(len(bot_df)),
        "top10": {
            "mean_CASV": float(top_df["CASV"].mean()),
            "min_CASV": float(top_df["CASV"].min()),
            "max_CASV": float(top_df["CASV"].max()),
            "share_of_total_mean": float(
                top_df["CASV"].sum() / df["CASV"].sum()
                if df["CASV"].sum() != 0 else float("nan")
            ),
        },
        "middle80": {
            "mean_CASV": float(mid_df["CASV"].mean()),
            "median_CASV": float(mid_df["CASV"].median()),
        },
        "bottom10": {
            "mean_CASV": float(bot_df["CASV"].mean()),
            "min_CASV": float(bot_df["CASV"].min()),
            "max_CASV": float(bot_df["CASV"].max()),
        },
    },
    "stripped_tests": stripped_results,
    "winsor_trim": winsor_results,
    "bootstrap_CI": bootstrap_results,
    "year_distribution": year_stats,
    "announcement_count": {
        "top10": ann_count_top,
        "middle80": ann_count_mid,
        "ks_p_value": float(ann_ks.pvalue),
        "mannwhitney_p_value": float(ann_mw.pvalue),
    },
    "sector": {
        "top10_share": top_sector_share,
        "middle80_share": mid_sector_share,
        "all_share": all_sector_share,
        "fisher_tech":        {"table": tech_table, "odds_ratio": tech_odds, "p_value": tech_p},
        "fisher_financial":   {"table": fin_table,  "odds_ratio": fin_odds,  "p_value": fin_p},
        "fisher_traditional": {"table": trad_table, "odds_ratio": trad_odds, "p_value": trad_p},
    },
    "market_comovement": {
        "vix_level": {
            "top10_mean":   float(vix_top.mean()),
            "middle80_mean": float(vix_mid.mean()),
            "top10_median": float(vix_top.median()),
            "middle80_median": float(vix_mid.median()),
            "ks_p_value":   float(ks_vix.pvalue),
            "mannwhitney_p_value": float(mw_vix.pvalue),
        },
        "high_vix_regime_share": {
            "top10":   top_highvix_share,
            "middle80": mid_highvix_share,
            "all":      all_highvix_share,
            "fisher_p": hv_p,
            "table":    hv_tab,
        },
        "spy_abs_return": {
            "top10_mean": float(spy_abs_top.mean()),
            "middle80_mean": float(spy_abs_mid.mean()),
            "ks_p_value": float(ks_spy.pvalue),
            "mannwhitney_p_value": float(mw_spy.pvalue),
        },
    },
    "regime_stats": regime_stats,
    "top10_events": top10_list,
    "K1070_reference": {
        "set_C_mean_CASV": 2.78,
        "set_C_median_CASV": -2.80,
        "set_C_t_stat": 2.13,
        "set_C_p": 0.034,
        "note": "K1071 must reproduce these numbers in setC_reproduction.",
    },
    "hypotheses_answered": {
        "Q1_top_characteristics": (
            "See sector / announcement-count / VIX blocks; details in "
            "top10_events list."
        ),
        "Q2_crisis_clustering":
            f"High-VIX regime share: top10={top_highvix_share:.3f}, "
            f"mid80={mid_highvix_share:.3f}, Fisher p={hv_p:.3g}.",
        "Q3_sector_clustering":
            f"Tech share top={top_sector_share['tech']:.3f} "
            f"vs mid={mid_sector_share['tech']:.3f} "
            f"(Fisher odds={tech_odds:.2f}, p={tech_p:.3g}); "
            f"Financial top={top_sector_share['financial']:.3f} "
            f"vs mid={mid_sector_share['financial']:.3f} "
            f"(odds={fin_odds:.2f}, p={fin_p:.3g}).",
        "Q4_systematic_shocks":
            f"VIX level MW p={mw_vix.pvalue:.3g}; "
            f"SPY |return| MW p={mw_spy.pvalue:.3g}.",
        "Q5_residual_after_stripping":
            f"Excluding top 10% (N={stripped_results['excl_top10pct']['n']}): "
            f"mean={stripped_results['excl_top10pct']['mean_CASV']:+.3f}, "
            f"median={stripped_results['excl_top10pct']['median_CASV']:+.3f}, "
            f"t={stripped_results['excl_top10pct']['t_stat']:+.2f}, "
            f"p={stripped_results['excl_top10pct']['p_value']:.3f}.",
    },
    "references": [
        "MacKinlay (1997) JEL 35",
        "Brown & Warner (1985) JFE 14",
        "Patell (1976) J Accounting Research 14",
        "Patell & Wolfson (1984) J Accounting Research 22",
        "Beaver (1968) J Accounting Research 6",
        "Wilcox (2017) Introduction to Robust Estimation and Hypothesis Testing",
        "K1068, K1070 (predecessor event studies)",
    ],
}

out_json = SCRIPT_DIR / "k1071_results.json"
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=float)

print(f"  saved {out_json}")
print(f"\nK1071 done in {runtime:.1f}s")
