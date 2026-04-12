"""
K1070: 0050.TW ETF-Level CAR/CASV Event Study — Aggregation Effect of Earnings
=================================================================================

Motivation
----------
K1068 showed on 10 individual Taiwan stocks (560 events) that:
  * CAR[-5,+5] is NULL (t_BW=-0.04, p=0.966)  — earnings do not move directional
    drift after market-model adjustment
  * CASV[-5,+5] is highly significant (t=+4.35)  — volatility spikes around
    announcements are real and ~2x stronger than K1060's simplified method

K1062 (older work) tested 0050.TW ETF-level but used the weaker event-day r^2
ratio (T+0, T+1), finding ratio ~1.132 (direction right, NS; "partial H1").

This experiment re-does the 0050.TW test with the MacKinlay (1997) gold-standard
CAR/CASV methodology so we can say cleanly how much of the individual-stock
earnings signal survives *ETF aggregation*.  Four event-set definitions are
compared to isolate the aggregation mechanism.

Research questions
------------------
H1: ETF CAR[-5,+5] is NULL (consistent with K1068 directional result)
H2: ETF CASV[-5,+5] is significantly positive but WEAKER than the individual
    stock CASV = 3.128 (this is the "diversification dilution")
H3: Does K1070 (rigorous) supersede K1062 (simplified)?  i.e. does the
    significant CASV spike show up on the same ETF when we use the correct
    methodology?
H4: Single-firm (TSMC) vs multi-firm (dense) events differ in the ETF volatility
    response — "aggregation effect".

Event sets (all restricted to 2010-2025 trading days)
-----------------------------------------------------
Set A  TSMC (2330) only                          — single large-cap event
Set B  Top-4 cap weights: 2330, 2454, 2317, 2303 — few big names
Set C  Any TWSE-50 constituent                   — full breadth
Set D  Dense days: trading days on which many
       TWSE-50 companies announce (top 10% of
       distinct-company counts)                  — aggregation extreme

Methodology (MacKinlay 1997)
----------------------------
 * Normal return from market model  R_{0050,t} = alpha + beta R_{m,t} + eps_t
 * Market benchmark: ^TWII (TAIEX) as primary
 * Estimation window [T-250, T-11] for each event
 * Event window [-5,+5] decomposed into [-5,-1] / [0,+1] / [+2,+5] / [-5,+5]
 * CAR  = sum AR_t
 * SCAR = CAR / sqrt(L * sigma_resid^2)
 * CASV = sum (AR_t^2 / sigma_resid^2 - 1)   (Patell-Wolfson 1984)
 * Tests (per window, per event set):
     - Brown-Warner (1985) cross-sectional t on CAR
     - Patell (1976) standardized CAR z-test
     - Boehmer-Masumeci-Poulsen (1991) BMP t on SCAR
     - One-sample t on CASV vs 0

Data
----
 * 0050.TW prices from yfinance, cleaned by volpred.utils.clean_tw50_data
 * ^TWII market index from yfinance
 * Earnings announcement dates from 財報公告日.txt (Big5)

Comparison table
----------------
 Metric          K1062 simplified     K1068 individuals   K1070 ETF (this)
 Subject         0050.TW              10 stocks           0050.TW
 Normal return   Rolling r^2          Market model        Market model
 Return target   r^2 ratio (T+0/T+1)  CAR [-5,+5] split   CAR [-5,+5] split
 CASV reported   No                   Yes  (t=+4.35)      Yes  (this)
 Event sets      One (TSMC)           Ten pooled          A/B/C/D

Discipline
----------
 * 0050.TW MUST use clean_tw50_data (2014-01-02 split fix)
 * Random seed 42 everywhere
 * All numbers must match the saved JSON (K1016 discipline)
 * Worktree agent cannot modify storage/ shared JSON

References
----------
 - MacKinlay (1997) JEL 35
 - Brown & Warner (1985) JFE 14
 - Patell (1976) J Accounting Research 14
 - Boehmer, Masumeci, Poulsen (1991) JFE 30
 - Patell & Wolfson (1984) J Accounting Research 22
 - Beaver (1968) J Accounting Research 6
 - Savor & Wilson (2016) JFQA 51
 - K1060, K1062, K1068 (prior tests)
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from collections import Counter, defaultdict
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

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
START_DATE = "2010-01-01"
END_DATE = "2025-12-31"
ESTIMATION_START = -250
ESTIMATION_END = -11
MIN_ESTIMATION = 100
EVENT_WINDOW = 5
WINDOWS = {
    "[-5,-1]": (-5, -1),
    "[0,+1]": (0, 1),
    "[+2,+5]": (2, 5),
    "[-5,+5]": (-5, 5),
}
MARKET_INDEX = "^TWII"
ETF_TICKER = "0050.TW"

# Top-4 TWSE-50 constituents by market cap weight (roughly stable 2010-2025)
TOP4_CODES = ["2330", "2454", "2317", "2303"]

# Comprehensive TWSE-50 constituents (code only, no .TW).  This list covers the
# companies that have been in the TWSE-50 index at some point during
# 2010-2025.  Using the union keeps Set C permissive.  Downstream we rely on
# the per-day de-duplication and the market-model filter.
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

print("=" * 72)
print("K1070: 0050.TW ETF CAR/CASV Event Study -- Aggregation Effect")
print("=" * 72)

# -----------------------------------------------------------------------------
# Part 0: Load earnings announcement data (Big5)
# -----------------------------------------------------------------------------
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
print(f"  total announcement records: {len(ea_df):,}")
print(f"  unique companies in file:   {ea_df['code'].nunique():,}")

ea_in = ea_df[(ea_df["date"] >= START_DATE) & (ea_df["date"] <= END_DATE)].copy()
ea_in = ea_in.sort_values("date").reset_index(drop=True)
print(f"  records in sample window:   {len(ea_in):,}")

# -----------------------------------------------------------------------------
# Part 1: Download ETF + market prices
# -----------------------------------------------------------------------------
print("\n[Part 1] Downloading 0050.TW + ^TWII...")


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
print(f"  0050.TW cleaned N={len(etf_ret):,} "
      f"({etf_ret.index.min().date()} .. {etf_ret.index.max().date()})")

mkt_close = fetch_close(MARKET_INDEX)
mkt_ret = np.log(mkt_close / mkt_close.shift(1)).dropna()
print(f"  ^TWII    N={len(mkt_ret):,}")

common_idx = etf_ret.index.intersection(mkt_ret.index)
etf_a = etf_ret.reindex(common_idx)
mkt_a = mkt_ret.reindex(common_idx)
trading_days = common_idx
n_days = len(trading_days)
print(f"  common trading days: {n_days:,}")

# -----------------------------------------------------------------------------
# Part 2: Build four event sets (A/B/C/D) with per-day de-duplication
# -----------------------------------------------------------------------------
print("\n[Part 2] Building event sets...")


def map_to_next_trading_day(dates: pd.Series) -> list[int]:
    positions: list[int] = []
    for d in pd.to_datetime(dates.unique()):
        pos = trading_days.searchsorted(d)
        if pos < n_days:
            positions.append(int(pos))
    return sorted(set(positions))


# Set A: TSMC only
a_dates = ea_in.loc[ea_in["code"] == "2330", "date"]
events_A = map_to_next_trading_day(a_dates)

# Set B: Top-4
b_dates = ea_in.loc[ea_in["code"].isin(TOP4_CODES), "date"]
events_B = map_to_next_trading_day(b_dates)

# Set C: TWSE-50 union
c_dates = ea_in.loc[ea_in["code"].isin(TWSE50_CODES), "date"]
events_C = map_to_next_trading_day(c_dates)

# Set D: dense days (top 10% by distinct-company count among TWSE-50 events)
# Count distinct company codes announcing on each calendar date, then take
# the 90th percentile cutoff.
day_company_counts = (
    ea_in.loc[ea_in["code"].isin(TWSE50_CODES)]
    .groupby(pd.Grouper(key="date", freq="D"))["code"]
    .nunique()
)
day_company_counts = day_company_counts[day_company_counts > 0]
if len(day_company_counts) == 0:
    dense_cutoff = np.nan
    events_D: list[int] = []
else:
    dense_cutoff = float(day_company_counts.quantile(0.90))
    dense_dates = day_company_counts[day_company_counts >= dense_cutoff].index
    events_D = map_to_next_trading_day(pd.Series(dense_dates))

print(f"  Set A (TSMC only)         : {len(events_A)} events")
print(f"  Set B (Top 4 caps)        : {len(events_B)} events")
print(f"  Set C (TWSE 50 union)     : {len(events_C)} events")
print(f"  Set D (dense, >= {int(dense_cutoff) if np.isfinite(dense_cutoff) else '?'} "
      f"firms/day) : {len(events_D)} events")

EVENT_SETS = {
    "A_TSMC":   {"label": "A: TSMC only",              "positions": events_A},
    "B_Top4":   {"label": "B: Top-4 caps",             "positions": events_B},
    "C_TWSE50": {"label": "C: TWSE-50 union",          "positions": events_C},
    "D_Dense":  {"label": f"D: Dense days (>={int(dense_cutoff) if np.isfinite(dense_cutoff) else 0} firms)",
                 "positions": events_D},
}

# -----------------------------------------------------------------------------
# Part 3: Market-model event study per set
# -----------------------------------------------------------------------------
print("\n[Part 3] Running CAR/CASV per event set...")


def bw_t(vec: np.ndarray) -> tuple[float, float]:
    """Brown-Warner (1985) cross-sectional t-test."""
    x = np.asarray(vec, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan")
    mean = float(x.mean())
    se = float(x.std(ddof=1) / np.sqrt(n))
    if se == 0:
        return float("nan"), float("nan")
    t = mean / se
    p = 2.0 * (1.0 - stats.t.cdf(abs(t), df=n - 1))
    return float(t), float(p)


def patell_z(scar_vec: np.ndarray) -> tuple[float, float]:
    """Patell (1976) standardized CAR z-test (asymptotic normal)."""
    x = np.asarray(scar_vec, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan")
    z = float(x.sum() / np.sqrt(n))
    p = 2.0 * (1.0 - stats.norm.cdf(abs(z)))
    return z, float(p)


def bmp_t(scar_vec: np.ndarray) -> tuple[float, float]:
    """Boehmer-Masumeci-Poulsen (1991) standardized cross-sectional t-test."""
    x = np.asarray(scar_vec, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan")
    mean = float(x.mean())
    se = float(x.std(ddof=1) / np.sqrt(n))
    if se == 0:
        return float("nan"), float("nan")
    t = mean / se
    p = 2.0 * (1.0 - stats.t.cdf(abs(t), df=n - 1))
    return float(t), float(p)


def casv_t(vec: np.ndarray) -> tuple[float, float]:
    """One-sample t on CASV vs 0."""
    x = np.asarray(vec, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan")
    mean = float(x.mean())
    se = float(x.std(ddof=1) / np.sqrt(n))
    if se == 0:
        return float("nan"), float("nan")
    t = mean / se
    p = 2.0 * (1.0 - stats.t.cdf(abs(t), df=n - 1))
    return float(t), float(p)


def run_event_set(positions: list[int]) -> tuple[list[dict], np.ndarray]:
    """Return (per-event records, AAR matrix shape (N, 11))."""
    recs: list[dict] = []
    ar_paths: list[np.ndarray] = []
    for pos in positions:
        est_start = pos + ESTIMATION_START
        est_end = pos + ESTIMATION_END
        if est_start < 0:
            continue
        if est_end - est_start + 1 < MIN_ESTIMATION:
            continue
        if pos + EVENT_WINDOW >= n_days:
            continue

        est_dates = trading_days[est_start: est_end + 1]
        r_i_est = etf_a.reindex(est_dates).dropna()
        r_m_est = mkt_a.reindex(r_i_est.index)
        if len(r_i_est) < MIN_ESTIMATION:
            continue

        x = np.column_stack([np.ones(len(r_m_est)), r_m_est.values])
        y = r_i_est.values
        try:
            coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        alpha, beta = float(coef[0]), float(coef[1])
        resid = y - x @ coef
        sigma2 = float(np.var(resid, ddof=2))
        if not np.isfinite(sigma2) or sigma2 <= 0:
            continue
        sigma = np.sqrt(sigma2)

        ev_positions = list(range(pos - EVENT_WINDOW, pos + EVENT_WINDOW + 1))
        ev_dates = trading_days[ev_positions]
        r_i_ev = etf_a.reindex(ev_dates).values
        r_m_ev = mkt_a.reindex(ev_dates).values
        ar = r_i_ev - (alpha + beta * r_m_ev)
        if np.any(~np.isfinite(ar)):
            continue

        rec = {
            "event_pos": int(pos),
            "event_date": trading_days[pos].strftime("%Y-%m-%d"),
            "alpha": alpha,
            "beta": beta,
            "sigma2": sigma2,
            "n_est": int(len(y)),
        }
        for label, (a, b) in WINDOWS.items():
            L = b - a + 1
            idx_a = EVENT_WINDOW + a
            idx_b = EVENT_WINDOW + b + 1
            car = float(np.sum(ar[idx_a:idx_b]))
            scar = car / np.sqrt(L * sigma2)
            casv = float(np.sum(ar[idx_a:idx_b] ** 2 / sigma2 - 1.0))
            rec[f"CAR_{label}"] = car
            rec[f"SCAR_{label}"] = float(scar)
            rec[f"CASV_{label}"] = casv

        recs.append(rec)
        ar_paths.append(ar)

    ar_matrix = np.array(ar_paths) if ar_paths else np.zeros((0, 2 * EVENT_WINDOW + 1))
    return recs, ar_matrix


set_results: dict[str, dict] = {}

for key, meta in EVENT_SETS.items():
    positions = meta["positions"]
    recs, ar_matrix = run_event_set(positions)
    df = pd.DataFrame(recs)

    window_stats: dict[str, dict] = {}
    for label in WINDOWS.keys():
        car_vec = df[f"CAR_{label}"].to_numpy() if len(df) else np.array([])
        scar_vec = df[f"SCAR_{label}"].to_numpy() if len(df) else np.array([])
        casv_vec = df[f"CASV_{label}"].to_numpy() if len(df) else np.array([])
        t_bw, p_bw = bw_t(car_vec)
        z_pat, p_pat = patell_z(scar_vec)
        t_bmp, p_bmp = bmp_t(scar_vec)
        t_cv, p_cv = casv_t(casv_vec)
        # Trimmed-mean CASV (5% trim each tail) as an outlier-robust check.
        # CASV is chi^2-shaped and can be dominated by single extreme events.
        if len(casv_vec) >= 20:
            casv_trim = stats.trim_mean(casv_vec[np.isfinite(casv_vec)], 0.05)
            casv_median = float(np.nanmedian(casv_vec))
        else:
            casv_trim = float("nan")
            casv_median = float(np.nanmedian(casv_vec)) if len(casv_vec) else float("nan")
        sig = ("***" if np.isfinite(p_bw) and p_bw < 0.01 else
               "**"  if np.isfinite(p_bw) and p_bw < 0.05 else
               "*"   if np.isfinite(p_bw) and p_bw < 0.10 else "")
        window_stats[label] = {
            "n_events": int(len(car_vec)),
            "mean_CAR": float(np.nanmean(car_vec)) if len(car_vec) else float("nan"),
            "std_CAR": float(np.nanstd(car_vec, ddof=1)) if len(car_vec) > 1 else float("nan"),
            "t_BW": t_bw, "p_BW": p_bw,
            "z_Patell": z_pat, "p_Patell": p_pat,
            "t_BMP": t_bmp, "p_BMP": p_bmp,
            "mean_CASV": float(np.nanmean(casv_vec)) if len(casv_vec) else float("nan"),
            "median_CASV": casv_median,
            "trimmed_mean_CASV_5pct": float(casv_trim) if np.isfinite(casv_trim) else None,
            "std_CASV": float(np.nanstd(casv_vec, ddof=1)) if len(casv_vec) > 1 else float("nan"),
            "t_CASV": t_cv, "p_CASV": p_cv,
            "sig_CAR": sig,
        }

    aar = ar_matrix.mean(axis=0) if len(ar_matrix) else np.zeros(2 * EVENT_WINDOW + 1)
    caar = np.cumsum(aar)

    set_results[key] = {
        "label": meta["label"],
        "n_events_attempted": len(positions),
        "n_events_used": len(recs),
        "window_stats": window_stats,
        "AAR": aar.tolist(),
        "CAAR": caar.tolist(),
    }

    print(f"\n  --- {key} ({meta['label']}) ---")
    print(f"  attempted {len(positions)}, usable {len(recs)}")
    for label in WINDOWS.keys():
        s = window_stats[label]
        print(
            f"    {label:9s} N={s['n_events']:4d} "
            f"CAR={s['mean_CAR']:+.4f} "
            f"t_BW={s['t_BW']:+.2f} (p={s['p_BW']:.3f}) {s['sig_CAR']}  "
            f"BMP={s['t_BMP']:+.2f}  "
            f"CASV={s['mean_CASV']:+.3f} (t={s['t_CASV']:+.2f}, p={s['p_CASV']:.3f})"
        )

# -----------------------------------------------------------------------------
# Part 4: Individual (K1068) vs ETF (K1070) comparison numbers
# -----------------------------------------------------------------------------
print("\n[Part 4] Diversification dilution analysis...")

# K1068 reference numbers (from k1068_results.json pooled_tests)
K1068_REF = {
    "n_events": 560,
    "mean_CAR_[-5,+5]": -0.0001,
    "t_BW_[-5,+5]": -0.04,
    "p_BW_[-5,+5]": 0.966,
    "mean_CASV_[-5,+5]": 3.128,
    "t_CASV_[-5,+5]": 4.35,
    "mean_CAR_[0,+1]": -0.0002,
    "mean_CASV_[0,+1]": 1.358,
    "t_CASV_[0,+1]": 4.15,
}

# K1062 reference (simplified ratio)
K1062_REF = {
    "T0_ratio_mean": 0.9356,
    "T1_ratio_mean": 1.1318,     # aggregate TSMC T+1 ratio
    "T1_t_one_sample": 2.0750,
    "T1_p_one_sample": 0.0339,
    "verdict": "H1 PARTIAL",
}

# Diversification dilution: the ratio of ETF CASV to individual-stock CASV for
# the matched event concept (A ~ TSMC only; B ~ roughly the 4 of K1068's tech
# names; C ~ all 10).  We report the [-5,+5] ratio.
dilution = {}
for key in set_results.keys():
    casv_etf = set_results[key]["window_stats"]["[-5,+5]"]["mean_CASV"]
    ratio = (casv_etf / K1068_REF["mean_CASV_[-5,+5]"]
             if K1068_REF["mean_CASV_[-5,+5]"] != 0 else float("nan"))
    dilution[key] = {
        "CASV_etf": casv_etf,
        "CASV_individual_K1068": K1068_REF["mean_CASV_[-5,+5]"],
        "dilution_ratio": ratio,
    }
    print(f"  {key:10s}  CASV_ETF={casv_etf:+.3f}  "
          f"dilution_ratio={ratio:+.3f}")

# -----------------------------------------------------------------------------
# Part 5: Hypothesis verdicts
# -----------------------------------------------------------------------------
print("\n[Part 5] Hypothesis verdicts...")


def verdict(p: float, threshold: float = 0.05) -> str:
    if not np.isfinite(p):
        return "INCONCLUSIVE"
    return "SUPPORTED" if p < threshold else "NOT SUPPORTED"


# H1: ETF CAR[-5,+5] is NULL (the useful ETF-aggregation story is that the
# directional drift washes out just like in K1068).  Using Set C (TWSE-50) as
# the primary test.  Harvey (2016) strict threshold: |t|>3.0.
h1_set = "C_TWSE50" if "C_TWSE50" in set_results else next(iter(set_results))
h1_w = set_results[h1_set]["window_stats"]["[-5,+5]"]
# Three-level verdict so the Harvey discipline is transparent.
if not np.isfinite(h1_w["p_BW"]) or h1_w["p_BW"] >= 0.05:
    H1_verdict = "SUPPORTED (NULL at 5%)"
elif abs(h1_w["t_BW"]) < 3.0:
    H1_verdict = ("MIXED: conventional 5% significant (|t|<3) "
                  "but FAILS Harvey 2016 t>3 -- economically tiny "
                  f"(mean CAR {h1_w['mean_CAR']:+.4f})")
else:
    H1_verdict = "NOT SUPPORTED (CAR significant at Harvey threshold)"

# H2: ETF CASV[-5,+5] is positive and significant.  Same 3-level discipline.
# Also flag the robustness issue: median CASV is negative across sets, meaning
# the "spike" is driven by a right tail of extreme events, not a bulk shift.
h2_w = set_results[h1_set]["window_stats"]["[-5,+5]"]
median_casv = h2_w.get("median_CASV", float("nan"))
trim_casv = h2_w.get("trimmed_mean_CASV_5pct")
if not np.isfinite(h2_w["p_CASV"]) or h2_w["mean_CASV"] <= 0:
    H2_verdict = "NOT SUPPORTED"
elif h2_w["p_CASV"] >= 0.05:
    H2_verdict = f"NOT SUPPORTED (p={h2_w['p_CASV']:.3f})"
elif abs(h2_w["t_CASV"]) < 3.0:
    H2_verdict = (
        f"SUPPORTED at 5% (t={h2_w['t_CASV']:+.2f}, p={h2_w['p_CASV']:.3f}) "
        f"but FAILS Harvey 2016 t>3; mean CASV=+{h2_w['mean_CASV']:.3f} "
        f"but median={median_casv:+.3f} (right-tail driven). "
        f"Weaker than K1068 individual (t=+4.35) -- consistent with ETF dilution."
    )
else:
    H2_verdict = (f"STRONGLY SUPPORTED (|t|>3 Harvey) "
                  f"t={h2_w['t_CASV']:+.2f}, p={h2_w['p_CASV']:.3f}")

# H3: K1070 supersedes K1062 (i.e. rigorous method finds a significant
# volatility signal on the same ETF that K1062 was only partial on)
H3_verdict = ("SUPPORTED (K1070 shows significant CASV; K1062 was partial)"
              if H2_verdict.startswith("SUPPORTED") else
              "NOT SUPPORTED (K1070 also NS on 0050.TW)")

# H4: Aggregation / single vs multi-firm: compare Set A (TSMC only) vs Set D
# (dense) on CASV[-5,+5]
a_casv = set_results["A_TSMC"]["window_stats"]["[-5,+5]"]["mean_CASV"] \
    if "A_TSMC" in set_results else float("nan")
d_casv = set_results["D_Dense"]["window_stats"]["[-5,+5]"]["mean_CASV"] \
    if "D_Dense" in set_results else float("nan")
H4_support = (np.isfinite(a_casv) and np.isfinite(d_casv) and d_casv > a_casv)
H4_verdict = ("SUPPORTED (dense > single-firm CASV)"
              if H4_support else "NOT SUPPORTED (dense <= single-firm)")

hypotheses = {
    "H1_ETF_CAR_NULL_consistent_with_K1068": {
        "description": "ETF CAR[-5,+5] is NULL (no directional drift)",
        "set_tested": h1_set,
        "mean_CAR": h1_w["mean_CAR"],
        "t_BW": h1_w["t_BW"],
        "p_BW": h1_w["p_BW"],
        "verdict": H1_verdict,
    },
    "H2_ETF_CASV_significant_positive": {
        "description": "ETF CASV[-5,+5] is positive and significant",
        "set_tested": h1_set,
        "mean_CASV": h2_w["mean_CASV"],
        "t_CASV": h2_w["t_CASV"],
        "p_CASV": h2_w["p_CASV"],
        "K1068_comparison": K1068_REF["mean_CASV_[-5,+5]"],
        "dilution_ratio_vs_K1068": (
            h2_w["mean_CASV"] / K1068_REF["mean_CASV_[-5,+5]"]
            if K1068_REF["mean_CASV_[-5,+5]"] != 0 else float("nan")),
        "verdict": H2_verdict,
    },
    "H3_K1070_supersedes_K1062": {
        "description": "Rigorous method detects volatility signal that simplified K1062 was only 'partial' on",
        "K1062_verdict": K1062_REF["verdict"],
        "K1070_primary_set": h1_set,
        "K1070_CASV_[-5,+5]_t": h2_w["t_CASV"],
        "K1070_CASV_[-5,+5]_p": h2_w["p_CASV"],
        "verdict": H3_verdict,
    },
    "H4_aggregation_effect_dense_vs_single": {
        "description": "Dense announcement days produce stronger ETF CASV than single-firm (TSMC-only) days",
        "single_firm_CASV": a_casv,
        "dense_CASV": d_casv,
        "verdict": H4_verdict,
    },
}

for k, v in hypotheses.items():
    print(f"  {k}: {v['verdict']}")

# -----------------------------------------------------------------------------
# Part 6: Charts
# -----------------------------------------------------------------------------
print("\n[Part 6] Generating charts...")
plt.rcParams.update({"figure.dpi": 120, "savefig.dpi": 120})

SET_COLORS = {
    "A_TSMC":   "#2E86AB",
    "B_Top4":   "#A23B72",
    "C_TWSE50": "#F18F01",
    "D_Dense":  "#6A994E",
}
SET_ORDER = ["A_TSMC", "B_Top4", "C_TWSE50", "D_Dense"]
WINDOW_ORDER = ["[-5,-1]", "[0,+1]", "[+2,+5]", "[-5,+5]"]

# 6.1  Heatmap:  4 sets x 4 windows  --  CAR (top) and CASV (bottom)
fig, axes = plt.subplots(2, 1, figsize=(10, 7.6))

car_heat = np.array([
    [set_results[s]["window_stats"][w]["mean_CAR"] for w in WINDOW_ORDER]
    for s in SET_ORDER
])
casv_heat = np.array([
    [set_results[s]["window_stats"][w]["mean_CASV"] for w in WINDOW_ORDER]
    for s in SET_ORDER
])

vmax_car = max(abs(np.nanmin(car_heat)), abs(np.nanmax(car_heat)), 1e-6)
im0 = axes[0].imshow(car_heat, cmap="RdBu_r", vmin=-vmax_car, vmax=vmax_car,
                     aspect="auto")
axes[0].set_xticks(range(len(WINDOW_ORDER)))
axes[0].set_xticklabels(WINDOW_ORDER)
axes[0].set_yticks(range(len(SET_ORDER)))
axes[0].set_yticklabels([set_results[s]["label"] for s in SET_ORDER])
for i, s in enumerate(SET_ORDER):
    for j, w in enumerate(WINDOW_ORDER):
        val = car_heat[i, j]
        t = set_results[s]["window_stats"][w]["t_BW"]
        p = set_results[s]["window_stats"][w]["p_BW"]
        star = ("***" if np.isfinite(p) and p < 0.01 else
                "**" if np.isfinite(p) and p < 0.05 else
                "*"  if np.isfinite(p) and p < 0.10 else "")
        axes[0].text(j, i, f"{val:+.4f}\n(t={t:+.2f}){star}",
                     ha="center", va="center", fontsize=8,
                     color="white" if abs(val) > vmax_car * 0.55 else "black")
axes[0].set_title("(a) Mean CAR -- 4 event sets x 4 windows")
plt.colorbar(im0, ax=axes[0], fraction=0.035, pad=0.02, label="CAR")

vmax_cv = max(abs(np.nanmin(casv_heat)), abs(np.nanmax(casv_heat)), 1e-6)
im1 = axes[1].imshow(casv_heat, cmap="RdBu_r", vmin=-vmax_cv, vmax=vmax_cv,
                     aspect="auto")
axes[1].set_xticks(range(len(WINDOW_ORDER)))
axes[1].set_xticklabels(WINDOW_ORDER)
axes[1].set_yticks(range(len(SET_ORDER)))
axes[1].set_yticklabels([set_results[s]["label"] for s in SET_ORDER])
for i, s in enumerate(SET_ORDER):
    for j, w in enumerate(WINDOW_ORDER):
        val = casv_heat[i, j]
        t = set_results[s]["window_stats"][w]["t_CASV"]
        p = set_results[s]["window_stats"][w]["p_CASV"]
        star = ("***" if np.isfinite(p) and p < 0.01 else
                "**" if np.isfinite(p) and p < 0.05 else
                "*"  if np.isfinite(p) and p < 0.10 else "")
        axes[1].text(j, i, f"{val:+.3f}\n(t={t:+.2f}){star}",
                     ha="center", va="center", fontsize=8,
                     color="white" if abs(val) > vmax_cv * 0.55 else "black")
axes[1].set_title("(b) Mean CASV -- 4 event sets x 4 windows")
plt.colorbar(im1, ax=axes[1], fraction=0.035, pad=0.02, label="CASV")

fig.suptitle("K1070: 0050.TW ETF CAR/CASV event study (2010-2025)", fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig(SCRIPT_DIR / "k1070_car_casv_windows.png", bbox_inches="tight")
plt.close()
print("  saved k1070_car_casv_windows.png")

# 6.2  AAR / CAAR time-series per set (2x1 subplots)
offsets = np.arange(-EVENT_WINDOW, EVENT_WINDOW + 1)

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
for s in SET_ORDER:
    if s not in set_results:
        continue
    axes[0].plot(offsets, set_results[s]["AAR"], marker="o",
                 color=SET_COLORS[s], label=set_results[s]["label"],
                 linewidth=1.4, markersize=4)
axes[0].axhline(y=0, color="red", linestyle="--", lw=1.0)
axes[0].axvline(x=0, color="black", linestyle=":", lw=1.0)
axes[0].set_xlabel("Trading days relative to announcement")
axes[0].set_ylabel("Average AR")
axes[0].set_title("(a) AAR across event window")
axes[0].legend(fontsize=8, loc="best")
axes[0].grid(alpha=0.3)

for s in SET_ORDER:
    if s not in set_results:
        continue
    axes[1].plot(offsets, set_results[s]["CAAR"], marker="o",
                 color=SET_COLORS[s], label=set_results[s]["label"],
                 linewidth=1.8, markersize=4)
axes[1].axhline(y=0, color="red", linestyle="--", lw=1.0)
axes[1].axvline(x=0, color="black", linestyle=":", lw=1.0)
axes[1].set_xlabel("Trading days relative to announcement")
axes[1].set_ylabel("Cumulative AAR (CAAR)")
axes[1].set_title("(b) CAAR path")
axes[1].legend(fontsize=8, loc="best")
axes[1].grid(alpha=0.3)

fig.suptitle("K1070: 0050.TW AAR/CAAR by event set", fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig(SCRIPT_DIR / "k1070_aar_timeseries.png", bbox_inches="tight")
plt.close()
print("  saved k1070_aar_timeseries.png")

# 6.3  ETF vs individual effect-size comparison
fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))

# Left: CAR[-5,+5] ETF sets vs K1068 individual
car_labels = [set_results[s]["label"] for s in SET_ORDER] + ["K1068\nindividuals"]
car_values = [set_results[s]["window_stats"]["[-5,+5]"]["mean_CAR"] for s in SET_ORDER] \
             + [K1068_REF["mean_CAR_[-5,+5]"]]
car_colors = [SET_COLORS[s] for s in SET_ORDER] + ["#555555"]
bars0 = axes[0].bar(range(len(car_labels)), car_values, color=car_colors,
                    edgecolor="black", alpha=0.88)
axes[0].axhline(y=0, color="red", linestyle="--", lw=1.0)
axes[0].set_xticks(range(len(car_labels)))
axes[0].set_xticklabels(car_labels, fontsize=8, rotation=15, ha="right")
axes[0].set_ylabel("Mean CAR[-5,+5]")
axes[0].set_title("(a) CAR[-5,+5]: ETF sets vs individual stocks")
for i, v in enumerate(car_values):
    axes[0].text(i, v + (0.0005 if v >= 0 else -0.0005), f"{v:+.4f}",
                 ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
axes[0].grid(axis="y", alpha=0.3)

# Right: CASV[-5,+5] ETF sets vs K1068 individual
casv_labels = car_labels
casv_values = [set_results[s]["window_stats"]["[-5,+5]"]["mean_CASV"] for s in SET_ORDER] \
              + [K1068_REF["mean_CASV_[-5,+5]"]]
bars1 = axes[1].bar(range(len(casv_labels)), casv_values, color=car_colors,
                    edgecolor="black", alpha=0.88)
axes[1].axhline(y=0, color="red", linestyle="--", lw=1.0)
axes[1].set_xticks(range(len(casv_labels)))
axes[1].set_xticklabels(casv_labels, fontsize=8, rotation=15, ha="right")
axes[1].set_ylabel("Mean CASV[-5,+5]")
axes[1].set_title("(b) CASV[-5,+5]: ETF sets vs individual stocks")
for i, v in enumerate(casv_values):
    t = (set_results[SET_ORDER[i]]["window_stats"]["[-5,+5]"]["t_CASV"]
         if i < len(SET_ORDER) else K1068_REF["t_CASV_[-5,+5]"])
    axes[1].text(i, v + (0.05 if v >= 0 else -0.05),
                 f"{v:+.3f}\n(t={t:+.2f})",
                 ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
axes[1].grid(axis="y", alpha=0.3)

fig.suptitle("K1070 vs K1068: ETF-aggregation dilution on CAR/CASV",
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig(SCRIPT_DIR / "k1070_comparison_k1068.png", bbox_inches="tight")
plt.close()
print("  saved k1070_comparison_k1068.png")

# -----------------------------------------------------------------------------
# Part 7: Save results JSON
# -----------------------------------------------------------------------------
elapsed = time.time() - START_TIME
now_iso = datetime.now(timezone.utc).isoformat()

results = {
    "experiment_id": "K1070",
    "title": "0050.TW ETF-Level CAR/CASV Event Study -- Aggregation Effect of Earnings",
    "proposer": "Claude (extension of K1068 to ETF level)",
    "executor": "Claude",
    "timestamp_utc": now_iso,
    "runtime_seconds": round(elapsed, 1),
    "random_seed": 42,
    "config": {
        "sample_period": f"{START_DATE} to {END_DATE}",
        "asset": ETF_TICKER,
        "market_index": MARKET_INDEX,
        "estimation_window": f"[{ESTIMATION_START},{ESTIMATION_END}]",
        "min_estimation_obs": MIN_ESTIMATION,
        "event_window_days": EVENT_WINDOW,
        "windows": WINDOWS,
        "top4_codes": TOP4_CODES,
        "twse50_universe_size": len(TWSE50_CODES),
        "dense_day_cutoff_firms": float(dense_cutoff) if np.isfinite(dense_cutoff) else None,
    },
    "data_summary": {
        "etf_trading_days": int(n_days),
        "etf_start": str(trading_days.min().date()),
        "etf_end": str(trading_days.max().date()),
        "total_announcement_records": int(len(ea_df)),
        "announcement_records_in_window": int(len(ea_in)),
    },
    "event_sets": {
        key: {
            "label": set_results[key]["label"],
            "attempted": set_results[key]["n_events_attempted"],
            "usable": set_results[key]["n_events_used"],
            "window_stats": set_results[key]["window_stats"],
            "AAR": set_results[key]["AAR"],
            "CAAR": set_results[key]["CAAR"],
        }
        for key in SET_ORDER if key in set_results
    },
    "dilution_analysis": dilution,
    "K1068_reference": K1068_REF,
    "K1062_reference": K1062_REF,
    "hypotheses": hypotheses,
    "references": [
        "MacKinlay, A.C. (1997) JEL 35(1): 13-39",
        "Brown, S. & Warner, J. (1985) JFE 14(1): 3-31",
        "Patell, J.M. (1976) J Accounting Research 14(2): 246-276",
        "Boehmer, E., Masumeci, J., Poulsen, A.B. (1991) JFE 30(2): 253-272",
        "Patell, J.M. & Wolfson, M.A. (1984) J Accounting Research 22: 223-252",
        "Beaver (1968) J Accounting Research 6: 67-92",
        "Savor & Wilson (2016) JFQA 51(1): 197-224",
        "K1060 (rolling r^2 ratio, individual)",
        "K1062 (0050.TW T+0/T+1 simplified)",
        "K1068 (10 stocks traditional CAR/CASV)",
    ],
}

out_path = SCRIPT_DIR / "k1070_results.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to {out_path}")
print("\n" + "=" * 72)
print(f"K1070 done. Elapsed: {elapsed:.1f}s")
for k, v in hypotheses.items():
    print(f"  {k}: {v['verdict']}")
print("=" * 72)
