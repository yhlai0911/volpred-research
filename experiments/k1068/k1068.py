"""
K1068: Traditional Event Study (CAR / CASV) for Taiwan Earnings Announcements
==============================================================================

Motivation (user's methodological correction):
------------------------------------------------
K1059/K1060/K1062 used a simplified volatility event-study approach (event-day
r^2 vs non-event r^2 ratio). The user pointed out that this is NOT the
standard event-study methodology in finance. The academic gold standard is
**Cumulative Abnormal Returns (CAR)** computed from a market model, covering
an event window such as [-5, +5] or [-10, +10], together with a volatility
counterpart **Cumulative Abnormal Squared Volatility (CASV)**.

This experiment re-examines the Taiwan individual earnings sample using
the classical methodology so the results are directly comparable with the
published literature.

Research questions:
-------------------
H1: Is CAR over [-5, +5] significantly non-zero? (information event)
H2: Does CAR[0, +1] differ from CAR[+2, +5]? (post-close announcements ->
    T+1 reaction vs drift)
H3: Is CASV (cumulative abnormal squared volatility) elevated in the event
    window? (the volatility event)
H4: Sectoral heterogeneity (Tech / Financial / Traditional / Telecom)

Methodology (MacKinlay 1997 gold standard):
-------------------------------------------
- Normal return: Market Model R_it = alpha_i + beta_i * R_mt + eps_it
- Estimation window: [T-250, T-11] (avoid pre-event leakage)
- Event window: [-5, +5] (11 days)
- AR_it = R_it - (alpha_hat_i + beta_hat_i * R_mt)
- CAR_i(t1,t2) = sum_{t=t1..t2} AR_it
- Tests:
    * Brown-Warner (1985) cross-sectional t-test
    * Patell (1976) standardized CAR t-test
    * Boehmer-Masumeci-Poulsen (1991) standardized cross-sectional t-test
      (robust to event-induced variance changes)
- CASV (Patell-Wolfson 1984): sum (AR^2 / sigma_i^2 - 1) over the window

Data:
-----
- Same 10 Taiwan stocks as K1060 (2330/2454/2317/2308/2303 Tech;
  2882/2891/2881 Financial; 2412 Telecom; 2002 Traditional)
- Market index proxy: ^TWII (TAIEX) - broader than 0050.TW
- Period: 2010-01-01 .. 2025-12-31
- Earnings dates: 財報公告日.txt (Big5 encoding)

Comparison with K1060:
----------------------
| Metric     | K1060 (simplified)    | K1068 (traditional)                |
| ---------- | --------------------- | ---------------------------------- |
| Normal     | Rolling 60-day r^2    | Market model alpha+beta*R_m        |
| Window     | T+0 / T+1             | [-5,+5] decomposed                 |
| Return     | r^2 ratio             | CAR (signed), plus CASV for vol    |
| Tests      | Welch t / bootstrap   | BW / Patell / Boehmer / binomial   |

References:
-----------
- MacKinlay, A.C. (1997) "Event studies in economics and finance" JEL 35
- Brown, S. & Warner, J. (1985) JFE 14
- Patell, J.M. (1976) J Accounting Research 14
- Boehmer, E., Masumeci, J., Poulsen, A.B. (1991) JFE 30
- Patell, J.M. & Wolfson, M.A. (1984) J Accounting Research 22
- Beaver (1968), Savor & Wilson (2016): earnings vol context
- K1059, K1060, K1062: prior simplified tests

Notes (discipline):
-------------------
- Individual stocks do not use clean_tw50_data (that is ETF-specific)
- Random seed: 42 (for any bootstrap / sampling)
- All numbers reported must match the JSON output (K1016 discipline)
"""

from __future__ import annotations

import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import matplotlib.patches as mpatches
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
DATA_FILE = PROJECT_ROOT / "財報公告日.txt"
START_TIME = time.time()

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
START_DATE = "2010-01-01"
END_DATE = "2025-12-31"
ESTIMATION_START = -250   # event-time days for estimation window start
ESTIMATION_END = -11      # event-time days for estimation window end (inclusive)
MIN_ESTIMATION = 100      # minimum estimation-window obs required
EVENT_WINDOW = 5          # full window is [-EVENT_WINDOW, +EVENT_WINDOW]
WINDOWS = {
    "[-5,-1]": (-5, -1),   # pre-event (leakage)
    "[0,+1]": (0, 1),      # immediate reaction (post-close -> T+1 in TW)
    "[+2,+5]": (2, 5),     # drift
    "[-5,+5]": (-5, 5),    # total
}
MARKET_INDEX = "^TWII"

STOCKS = {
    "2330.TW": ("TSMC", "Tech"),
    "2454.TW": ("MediaTek", "Tech"),
    "2317.TW": ("Hon Hai", "Tech"),
    "2308.TW": ("Delta", "Tech"),
    "2303.TW": ("UMC", "Tech"),
    "2412.TW": ("Chunghwa Telecom", "Telecom"),
    "2882.TW": ("Cathay Holdings", "Financial"),
    "2891.TW": ("CTBC Financial", "Financial"),
    "2881.TW": ("Fubon Financial", "Financial"),
    "2002.TW": ("China Steel", "Traditional"),
}

SECTOR_COLORS = {
    "Tech": "#2E86AB",
    "Financial": "#A23B72",
    "Traditional": "#F18F01",
    "Telecom": "#6A994E",
}

print("=" * 72)
print("K1068: Traditional Event Study (CAR / CASV) -- Taiwan earnings")
print("=" * 72)

# -----------------------------------------------------------------------------
# Part 0: Load earnings announcement dates (Big5 -> UTF-8)
# -----------------------------------------------------------------------------
print("\n[Part 0] Loading earnings announcement data (Big5)...")

with open(DATA_FILE, "rb") as f:
    raw_text = f.read().decode("big5", errors="replace")

records = []
for line in raw_text.strip().split("\n")[1:]:
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
print(f"  parsed announcement records: {len(ea_df):,}")
print(f"  unique companies: {ea_df['code'].nunique():,}")

stock_codes = [k.replace(".TW", "") for k in STOCKS.keys()]
ea_sample = ea_df[ea_df["code"].isin(stock_codes)].copy()
ea_sample = ea_sample[(ea_sample["date"] >= START_DATE) & (ea_sample["date"] <= END_DATE)]
ea_sample = ea_sample.sort_values("date").reset_index(drop=True)
print(f"  announcements for 10 sample stocks in window: {len(ea_sample)}")

# -----------------------------------------------------------------------------
# Part 1: Download price data (stocks + market index)
# -----------------------------------------------------------------------------
print("\n[Part 1] Downloading prices...")


def fetch_close(ticker: str) -> pd.Series:
    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                     progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].astype(float)


mkt_close = fetch_close(MARKET_INDEX)
print(f"  {MARKET_INDEX} (TAIEX) N={len(mkt_close):,}")
mkt_ret = np.log(mkt_close / mkt_close.shift(1)).dropna()

stock_returns: dict[str, pd.Series] = {}
for ticker, (name, sector) in STOCKS.items():
    close = fetch_close(ticker)
    if close.empty:
        print(f"  {ticker} ({name}) EMPTY -- skipping")
        continue
    ret = np.log(close / close.shift(1)).dropna()
    stock_returns[ticker] = ret
    print(f"  {ticker} {name:18s} [{sector:11s}] N={len(ret):,}")

# Align all series on common trading days for each stock separately
# Use market index trading days as the reference calendar
print(f"\n  market trading days: {len(mkt_ret):,}")

# -----------------------------------------------------------------------------
# Part 2: Market model estimation + AR / CAR per event
# -----------------------------------------------------------------------------
print("\n[Part 2] Market model estimation + AR/CAR/CASV...")

# For each stock and each announcement, estimate alpha/beta on [-250,-11]
# then compute AR_t = R_t - (alpha + beta*R_mt) on [-5,+5] and sigma_i^2 from
# the estimation-window residual variance.

all_event_records: list[dict] = []
per_stock_windows: dict[str, dict] = {}

for ticker, (name, sector) in STOCKS.items():
    if ticker not in stock_returns:
        continue
    ret = stock_returns[ticker]

    # Common calendar for this stock (intersection with market)
    common_idx = ret.index.intersection(mkt_ret.index)
    ret_a = ret.reindex(common_idx)
    mkt_a = mkt_ret.reindex(common_idx)

    trading_days = common_idx
    n_days = len(trading_days)

    # Get this stock's announcements, map to next trading day
    code = ticker.replace(".TW", "")
    ea_dates = ea_sample.loc[ea_sample["code"] == code, "date"].sort_values().unique()
    mapped: list[int] = []  # positions (index) of event day t=0 (next trading day)
    for d in ea_dates:
        pos = trading_days.searchsorted(pd.Timestamp(d))
        if pos < n_days:
            mapped.append(int(pos))
    mapped = sorted(set(mapped))

    records: list[dict] = []
    window_curves_ar: list[np.ndarray] = []     # per-event AR path [-5..+5]
    window_curves_scaled: list[np.ndarray] = [] # AR / sigma_i path for CASV

    for pos in mapped:
        est_start = pos + ESTIMATION_START
        est_end = pos + ESTIMATION_END
        if est_start < 0:
            continue
        if est_end - est_start + 1 < MIN_ESTIMATION:
            continue
        if pos + EVENT_WINDOW >= n_days:
            continue

        est_dates = trading_days[est_start: est_end + 1]
        r_i_est = ret_a.reindex(est_dates).dropna()
        r_m_est = mkt_a.reindex(r_i_est.index)

        # Market model OLS (with constant)
        x = np.column_stack([np.ones(len(r_m_est)), r_m_est.values])
        y = r_i_est.values
        # Guard against degenerate estimation window
        if len(y) < MIN_ESTIMATION:
            continue
        try:
            coef, *_ = np.linalg.lstsq(x, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        alpha, beta = float(coef[0]), float(coef[1])
        resid_est = y - x @ coef
        sigma2 = float(np.var(resid_est, ddof=2))
        if not np.isfinite(sigma2) or sigma2 <= 0:
            continue
        sigma = np.sqrt(sigma2)

        # Event window AR path
        ev_positions = list(range(pos - EVENT_WINDOW, pos + EVENT_WINDOW + 1))
        ev_dates = trading_days[ev_positions]
        r_i_ev = ret_a.reindex(ev_dates).values
        r_m_ev = mkt_a.reindex(ev_dates).values
        ar = r_i_ev - (alpha + beta * r_m_ev)
        ar_scaled = ar / sigma

        # Skip events with any missing day
        if np.any(~np.isfinite(ar)):
            continue

        window_curves_ar.append(ar)
        window_curves_scaled.append(ar_scaled)

        # CAR / CASV for each window
        # Event-time offsets are -EVENT_WINDOW..+EVENT_WINDOW, indexed 0..L-1
        rec = {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "event_pos": pos,
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
            # Standardized CAR (Patell 1976):
            # SCAR = CAR / sqrt(L * sigma^2 * correction)
            # Simplified correction (MacKinlay 1997 Eq.16): use L*sigma^2
            scar = car / np.sqrt(L * sigma2)
            casv = float(np.sum(ar[idx_a:idx_b] ** 2 / sigma2 - 1.0))
            rec[f"CAR_{label}"] = car
            rec[f"SCAR_{label}"] = float(scar)
            rec[f"CASV_{label}"] = casv
        records.append(rec)

    if not records:
        print(f"  {ticker} {name}: no valid events -- skipped")
        continue

    df_rec = pd.DataFrame(records)
    all_event_records.extend(records)

    # Average AR path (AAR) and Cumulative AAR (CAAR) over events in this stock
    ar_matrix = np.array(window_curves_ar)                # (N_ev, 11)
    scaled_matrix = np.array(window_curves_scaled)        # standardized
    aar = ar_matrix.mean(axis=0)
    caar = np.cumsum(aar)                                 # CAAR path
    per_stock_windows[ticker] = {
        "name": name,
        "sector": sector,
        "n_events": int(len(records)),
        "AAR": aar.tolist(),
        "CAAR": caar.tolist(),
        "mean_SAR": scaled_matrix.mean(axis=0).tolist(),
        "records": df_rec,
    }
    # Verbose per-stock summary (use main windows)
    mean_car_all = df_rec["CAR_[-5,+5]"].mean()
    mean_car_01 = df_rec["CAR_[0,+1]"].mean()
    mean_casv_all = df_rec["CASV_[-5,+5]"].mean()
    print(
        f"  {ticker} {name:18s} [{sector:11s}] "
        f"N_ev={len(records):3d} "
        f"CAR[-5,+5]={mean_car_all:+.4f} CAR[0,+1]={mean_car_01:+.4f} "
        f"CASV[-5,+5]={mean_casv_all:+.3f}"
    )

event_df = pd.DataFrame(all_event_records)
print(f"\n  total usable events across stocks: {len(event_df):,}")


# -----------------------------------------------------------------------------
# Part 3: Statistical tests per window (pooled across events)
# -----------------------------------------------------------------------------
print("\n[Part 3] Cross-sectional CAR / CASV tests per window...")


def bw_t(car_vec: np.ndarray) -> tuple[float, float]:
    """Brown-Warner (1985) cross-sectional t-test on CAR."""
    x = np.asarray(car_vec, dtype=float)
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


def patell_t(scar_vec: np.ndarray) -> tuple[float, float]:
    """Patell (1976) standardized CAR t-test (asymptotic normal)."""
    x = np.asarray(scar_vec, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan")
    t = float(x.sum() / np.sqrt(n))
    p = 2.0 * (1.0 - stats.norm.cdf(abs(t)))
    return t, float(p)


def bmp_t(scar_vec: np.ndarray) -> tuple[float, float]:
    """Boehmer-Masumeci-Poulsen (1991) standardized cross-sectional t-test
    (robust to event-induced variance)."""
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


def cs_casv_t(casv_vec: np.ndarray) -> tuple[float, float]:
    """One-sample t-test on CASV vs zero (volatility counterpart)."""
    x = np.asarray(casv_vec, dtype=float)
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


# Pooled tests across all 10 stocks (treat every event as a draw; this is the
# Brown-Warner style pooling where events are considered independent).
pooled_tests: dict[str, dict] = {}
for label in WINDOWS.keys():
    car_vec = event_df[f"CAR_{label}"].to_numpy()
    scar_vec = event_df[f"SCAR_{label}"].to_numpy()
    casv_vec = event_df[f"CASV_{label}"].to_numpy()
    t_bw, p_bw = bw_t(car_vec)
    t_pat, p_pat = patell_t(scar_vec)
    t_bmp, p_bmp = bmp_t(scar_vec)
    t_casv, p_casv = cs_casv_t(casv_vec)
    sig = "***" if p_bw < 0.01 else "**" if p_bw < 0.05 else "*" if p_bw < 0.10 else ""
    pooled_tests[label] = {
        "n_events": int(np.isfinite(car_vec).sum()),
        "mean_CAR": float(np.nanmean(car_vec)),
        "std_CAR": float(np.nanstd(car_vec, ddof=1)),
        "t_BW": t_bw, "p_BW": p_bw,
        "t_Patell": t_pat, "p_Patell": p_pat,
        "t_BMP": t_bmp, "p_BMP": p_bmp,
        "mean_CASV": float(np.nanmean(casv_vec)),
        "t_CASV": t_casv, "p_CASV": p_casv,
        "sig": sig,
    }
    print(
        f"  window {label:9s} N={pooled_tests[label]['n_events']:4d} "
        f"mean CAR={pooled_tests[label]['mean_CAR']:+.4f} "
        f"t_BW={t_bw:+.2f} (p={p_bw:.3f}) {sig}  "
        f"t_Patell={t_pat:+.2f}  t_BMP={t_bmp:+.2f}  "
        f"CASV={pooled_tests[label]['mean_CASV']:+.3f} (t={t_casv:+.2f})"
    )


# -----------------------------------------------------------------------------
# Part 4: Per-stock aggregates + sectoral analysis
# -----------------------------------------------------------------------------
print("\n[Part 4] Per-stock and sectoral aggregates...")

per_stock_summary: list[dict] = []
for ticker in STOCKS.keys():
    if ticker not in per_stock_windows:
        continue
    info = per_stock_windows[ticker]
    df_rec = info["records"]
    row: dict = {
        "ticker": ticker,
        "name": info["name"],
        "sector": info["sector"],
        "n_events": info["n_events"],
    }
    for label in WINDOWS.keys():
        car_vec = df_rec[f"CAR_{label}"].to_numpy()
        t_bw, p_bw = bw_t(car_vec)
        casv_vec = df_rec[f"CASV_{label}"].to_numpy()
        row[f"mean_CAR_{label}"] = float(np.nanmean(car_vec))
        row[f"t_BW_{label}"] = t_bw
        row[f"p_BW_{label}"] = p_bw
        row[f"mean_CASV_{label}"] = float(np.nanmean(casv_vec))
    per_stock_summary.append(row)

ps_df = pd.DataFrame(per_stock_summary)
print(ps_df[["ticker", "name", "sector", "n_events",
            "mean_CAR_[-5,+5]", "t_BW_[-5,+5]",
            "mean_CAR_[0,+1]",  "t_BW_[0,+1]",
            "mean_CASV_[-5,+5]"]].to_string(index=False))

# Sectoral aggregation (events pooled within sector)
sector_tests: dict[str, dict] = {}
for sector in sorted(set(info[1] for info in STOCKS.values())):
    mask = event_df["sector"] == sector
    sub = event_df[mask]
    sector_row: dict = {
        "n_stocks": int(sub["ticker"].nunique()),
        "n_events": int(len(sub)),
    }
    for label in WINDOWS.keys():
        car_vec = sub[f"CAR_{label}"].to_numpy()
        scar_vec = sub[f"SCAR_{label}"].to_numpy()
        casv_vec = sub[f"CASV_{label}"].to_numpy()
        t_bw, p_bw = bw_t(car_vec)
        t_bmp, p_bmp = bmp_t(scar_vec)
        t_casv, p_casv = cs_casv_t(casv_vec)
        sector_row[f"mean_CAR_{label}"] = float(np.nanmean(car_vec))
        sector_row[f"t_BW_{label}"] = t_bw
        sector_row[f"p_BW_{label}"] = p_bw
        sector_row[f"t_BMP_{label}"] = t_bmp
        sector_row[f"mean_CASV_{label}"] = float(np.nanmean(casv_vec))
        sector_row[f"t_CASV_{label}"] = t_casv
    sector_tests[sector] = sector_row
    print(
        f"  sector {sector:11s} N_ev={sector_row['n_events']:3d} "
        f"CAR[-5,+5]={sector_row['mean_CAR_[-5,+5]']:+.4f} "
        f"(t_BW={sector_row['t_BW_[-5,+5]']:+.2f})  "
        f"CASV={sector_row['mean_CASV_[-5,+5]']:+.3f}"
    )

# ANOVA-like test for sector heterogeneity on CAR[-5,+5]
sector_groups = [event_df.loc[event_df["sector"] == s, "CAR_[-5,+5]"].values
                 for s in sorted(event_df["sector"].unique())]
sector_groups = [g[np.isfinite(g)] for g in sector_groups]
if min(len(g) for g in sector_groups) >= 3:
    f_stat, f_p = stats.f_oneway(*sector_groups)
else:
    f_stat, f_p = float("nan"), float("nan")
print(f"\n  sector F-test on CAR[-5,+5]: F={f_stat:.3f} p={f_p:.4f}")


# -----------------------------------------------------------------------------
# Part 5: Hypothesis verdicts + comparison with K1060
# -----------------------------------------------------------------------------
print("\n[Part 5] Hypothesis verdicts...")


def verdict(mean: float, p: float, threshold: float = 0.05,
            direction: str = "nonzero") -> str:
    if not np.isfinite(p):
        return "INCONCLUSIVE"
    if p >= threshold:
        return "NOT SUPPORTED"
    if direction == "positive":
        return "SUPPORTED" if mean > 0 else "CONTRADICTED"
    if direction == "negative":
        return "SUPPORTED" if mean < 0 else "CONTRADICTED"
    return "SUPPORTED"  # nonzero


hypotheses = {
    "H1_CAR_m5_p5_nonzero": {
        "description": "CAR over [-5,+5] is significantly non-zero",
        "mean_CAR": pooled_tests["[-5,+5]"]["mean_CAR"],
        "t_BW": pooled_tests["[-5,+5]"]["t_BW"],
        "p_BW": pooled_tests["[-5,+5]"]["p_BW"],
        "verdict": verdict(pooled_tests["[-5,+5]"]["mean_CAR"],
                           pooled_tests["[-5,+5]"]["p_BW"], 0.05, "nonzero"),
    },
    "H2_post_close_T1_differs_from_drift": {
        "description": "CAR[0,+1] (immediate post-close reaction) differs from CAR[+2,+5] (drift)",
        "mean_CAR_0_1": pooled_tests["[0,+1]"]["mean_CAR"],
        "mean_CAR_2_5": pooled_tests["[+2,+5]"]["mean_CAR"],
        "t_diff": float("nan"),
        "p_diff": float("nan"),
    },
    "H3_CASV_window_elevated": {
        "description": "CASV over [-5,+5] is significantly positive (volatility spike)",
        "mean_CASV": pooled_tests["[-5,+5]"]["mean_CASV"],
        "t_CASV": pooled_tests["[-5,+5]"]["t_CASV"],
        "p_CASV": pooled_tests["[-5,+5]"]["p_CASV"],
        "verdict": verdict(pooled_tests["[-5,+5]"]["mean_CASV"],
                           pooled_tests["[-5,+5]"]["p_CASV"], 0.05, "positive"),
    },
    "H4_sector_heterogeneity": {
        "description": "Sector heterogeneity in CAR[-5,+5] (one-way ANOVA)",
        "F_stat": float(f_stat) if np.isfinite(f_stat) else None,
        "p_value": float(f_p) if np.isfinite(f_p) else None,
        "verdict": ("SUPPORTED" if np.isfinite(f_p) and f_p < 0.05 else
                    "NOT SUPPORTED"),
    },
}

# H2 paired test: are CAR[0,+1] and CAR[+2,+5] drawn from the same distribution?
diff_vec = event_df["CAR_[0,+1]"].to_numpy() - event_df["CAR_[+2,+5]"].to_numpy()
diff_vec = diff_vec[np.isfinite(diff_vec)]
if len(diff_vec) >= 3:
    t_d, p_d = stats.ttest_1samp(diff_vec, popmean=0.0)
    hypotheses["H2_post_close_T1_differs_from_drift"]["t_diff"] = float(t_d)
    hypotheses["H2_post_close_T1_differs_from_drift"]["p_diff"] = float(p_d)
    hypotheses["H2_post_close_T1_differs_from_drift"]["verdict"] = (
        "DIFFERENT" if p_d < 0.05 else "SIMILAR"
    )

# Comparison with K1060 (simplified ratio)
k1060_comparison = {
    "method": {
        "K1060": "r^2 ratio (event vs non-event mean, rolling 60-day)",
        "K1068": "CAR / CASV under market model (MacKinlay 1997)",
    },
    "K1060_numbers": {
        "mean_ratio_T0": 0.9356,
        "mean_ratio_T1": 1.4657,
        "one_sample_t_T1": 2.0750,
        "one_sample_p_T1": 0.0339,
    },
    "K1068_numbers": {
        "mean_CAR_[-5,+5]": pooled_tests["[-5,+5]"]["mean_CAR"],
        "t_BW_[-5,+5]": pooled_tests["[-5,+5]"]["t_BW"],
        "p_BW_[-5,+5]": pooled_tests["[-5,+5]"]["p_BW"],
        "mean_CAR_[0,+1]": pooled_tests["[0,+1]"]["mean_CAR"],
        "t_BW_[0,+1]": pooled_tests["[0,+1]"]["t_BW"],
        "mean_CASV_[-5,+5]": pooled_tests["[-5,+5]"]["mean_CASV"],
        "t_CASV_[-5,+5]": pooled_tests["[-5,+5]"]["t_CASV"],
    },
}


# -----------------------------------------------------------------------------
# Part 6: Charts
# -----------------------------------------------------------------------------
print("\n[Part 6] Generating charts...")
plt.rcParams.update({"figure.dpi": 120, "savefig.dpi": 120})

# 6.1 CAR by window with 95% CI (bar chart)
fig, ax = plt.subplots(figsize=(9, 5.5))
window_labels = list(WINDOWS.keys())
means = [pooled_tests[w]["mean_CAR"] for w in window_labels]
stds = [pooled_tests[w]["std_CAR"] for w in window_labels]
ns = [pooled_tests[w]["n_events"] for w in window_labels]
cis = [1.96 * s / np.sqrt(max(n, 1)) for s, n in zip(stds, ns)]
bar_colors = ["#888888" if "5,-1" in w else "#2E86AB" if "0,+1" in w
              else "#F18F01" if "2,+5" in w else "#A23B72"
              for w in window_labels]
bars = ax.bar(window_labels, means, yerr=cis, capsize=6,
              color=bar_colors, edgecolor="black", alpha=0.85)
ax.axhline(y=0, color="red", linestyle="--", lw=1.0)
ax.set_ylabel("Mean CAR")
ax.set_title("K1068: Mean CAR by Event Window (95% CI)\n"
             "Taiwan earnings, 10 stocks, 2010-2025")
for i, (m, c, n, sig) in enumerate(zip(means, cis, ns,
                                        [pooled_tests[w]["sig"] for w in window_labels])):
    ax.text(i, m + c + 0.0015 if m >= 0 else m - c - 0.0015,
            f"{m:+.4f}\n(N={n}) {sig}", ha="center",
            va="bottom" if m >= 0 else "top", fontsize=9)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(SCRIPT_DIR / "k1068_car_windows.png", bbox_inches="tight")
plt.close()
print("  saved k1068_car_windows.png")

# 6.2 AAR and CAAR time-series across event days (pooled across stocks)
all_ar = []
for ticker, info in per_stock_windows.items():
    all_ar.append(np.array(info["AAR"]))
if all_ar:
    # Equal-weight across stocks (each stock's AAR)
    aar_pooled = np.mean(all_ar, axis=0)
else:
    aar_pooled = np.zeros(2 * EVENT_WINDOW + 1)
caar_pooled = np.cumsum(aar_pooled)

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
offsets = np.arange(-EVENT_WINDOW, EVENT_WINDOW + 1)
axes[0].bar(offsets, aar_pooled, color="#2E86AB", edgecolor="black", alpha=0.85)
axes[0].axhline(y=0, color="red", linestyle="--", lw=1.0)
axes[0].axvline(x=0, color="black", linestyle=":", lw=1.0)
axes[0].set_xlabel("Trading days relative to announcement")
axes[0].set_ylabel("Average AR")
axes[0].set_title("(a) AAR across event window")
axes[0].grid(alpha=0.3)

axes[1].plot(offsets, caar_pooled, marker="o", color="#A23B72", linewidth=1.8)
axes[1].axhline(y=0, color="red", linestyle="--", lw=1.0)
axes[1].axvline(x=0, color="black", linestyle=":", lw=1.0)
axes[1].set_xlabel("Trading days relative to announcement")
axes[1].set_ylabel("Cumulative AAR (CAAR)")
axes[1].set_title("(b) CAAR path")
axes[1].grid(alpha=0.3)

fig.suptitle("K1068: Average Abnormal Return across [-5,+5] (10 stocks)",
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig(SCRIPT_DIR / "k1068_car_timeseries.png", bbox_inches="tight")
plt.close()
print("  saved k1068_car_timeseries.png")

# 6.3 Sector heterogeneity heatmap (sectors x windows, mean CAR)
sectors = sorted(sector_tests.keys())
heat = np.array([[sector_tests[s][f"mean_CAR_{w}"] for w in window_labels]
                 for s in sectors])
fig, ax = plt.subplots(figsize=(9, 4.2))
vmax = max(abs(heat.min()), abs(heat.max()))
im = ax.imshow(heat, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
ax.set_xticks(range(len(window_labels)))
ax.set_xticklabels(window_labels)
ax.set_yticks(range(len(sectors)))
ax.set_yticklabels(sectors)
for i, s in enumerate(sectors):
    for j, w in enumerate(window_labels):
        val = heat[i, j]
        t = sector_tests[s][f"t_BW_{w}"]
        txt = f"{val:+.4f}\n(t={t:+.2f})"
        color = "white" if abs(val) > vmax * 0.55 else "black"
        ax.text(j, i, txt, ha="center", va="center", fontsize=8, color=color)
ax.set_title(
    f"K1068: Sector x Window Mean CAR\n"
    f"ANOVA on CAR[-5,+5]: F={f_stat:.2f}, p={f_p:.4f}"
)
plt.colorbar(im, ax=ax, label="Mean CAR")
plt.tight_layout()
plt.savefig(SCRIPT_DIR / "k1068_sector_heterogeneity.png", bbox_inches="tight")
plt.close()
print("  saved k1068_sector_heterogeneity.png")

# 6.4 Comparison with K1060 (K1060 ratio vs K1068 CAR[0,+1])
# Map each stock's K1060 T+1 ratio alongside the K1068 CAR[0,+1] t-stat.
k1060_t1 = {
    "2330.TW": 0.983, "2454.TW": 0.872, "2317.TW": 2.063,
    "2308.TW": 1.681, "2303.TW": 2.579, "2412.TW": 0.452,
    "2882.TW": 1.960, "2891.TW": 0.791, "2881.TW": 1.128, "2002.TW": 2.146,
}
tickers_sorted = [t for t in STOCKS.keys() if t in per_stock_windows]
x_ratio = [k1060_t1.get(t, np.nan) for t in tickers_sorted]
y_car = [next(r["mean_CAR_[0,+1]"] for r in per_stock_summary if r["ticker"] == t)
         for t in tickers_sorted]
y_t = [next(r["t_BW_[0,+1]"] for r in per_stock_summary if r["ticker"] == t)
       for t in tickers_sorted]
sectors_per = [STOCKS[t][1] for t in tickers_sorted]

fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
# (a) Cross-method scatter: K1060 T+1 ratio vs K1068 CAR[0,+1] t_BW
sc_colors = [SECTOR_COLORS.get(s, "gray") for s in sectors_per]
axes[0].scatter(x_ratio, y_t, c=sc_colors, s=110, edgecolor="black", alpha=0.9)
for t, xi, yi in zip(tickers_sorted, x_ratio, y_t):
    axes[0].annotate(t.replace(".TW", ""), (xi, yi),
                     textcoords="offset points", xytext=(5, 5), fontsize=9)
axes[0].axhline(y=0, color="red", linestyle="--", lw=1.0)
axes[0].axvline(x=1.0, color="red", linestyle="--", lw=1.0)
axes[0].set_xlabel("K1060 T+1 ratio (simplified)")
axes[0].set_ylabel("K1068 t_BW on CAR[0,+1] (market model)")
axes[0].set_title("(a) Per-stock cross-method scatter")
axes[0].grid(alpha=0.3)

# Pearson correlation
xs = np.array(x_ratio); ys = np.array(y_t)
mask = np.isfinite(xs) & np.isfinite(ys)
if mask.sum() >= 3:
    rho, rho_p = stats.pearsonr(xs[mask], ys[mask])
else:
    rho, rho_p = float("nan"), float("nan")
axes[0].text(0.02, 0.97, f"Pearson rho={rho:.3f} (p={rho_p:.3f})",
             transform=axes[0].transAxes, fontsize=9, va="top",
             bbox=dict(facecolor="white", alpha=0.8, edgecolor="gray"))

# (b) Method comparison bars
labels_b = ["K1060\n(T+0 ratio-1)", "K1060\n(T+1 ratio-1)",
            "K1068 CAR\n[-5,+5]", "K1068 CAR\n[0,+1]", "K1068 CAR\n[+2,+5]"]
values_b = [
    k1060_comparison["K1060_numbers"]["mean_ratio_T0"] - 1.0,
    k1060_comparison["K1060_numbers"]["mean_ratio_T1"] - 1.0,
    pooled_tests["[-5,+5]"]["mean_CAR"],
    pooled_tests["[0,+1]"]["mean_CAR"],
    pooled_tests["[+2,+5]"]["mean_CAR"],
]
color_b = ["#888888", "#888888", "#A23B72", "#2E86AB", "#F18F01"]
axes[1].bar(labels_b, values_b, color=color_b, edgecolor="black", alpha=0.85)
axes[1].axhline(y=0, color="red", linestyle="--", lw=1.0)
axes[1].set_ylabel("Effect size")
axes[1].set_title("(b) K1060 vs K1068 effect sizes")
for i, v in enumerate(values_b):
    axes[1].text(i, v + (0.01 if v >= 0 else -0.01), f"{v:+.4f}",
                 ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
axes[1].grid(axis="y", alpha=0.3)
axes[1].tick_params(axis="x", labelsize=8)

fig.suptitle("K1068 vs K1060: Method comparison on the same event sample",
             fontsize=12)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig(SCRIPT_DIR / "k1068_comparison_k1060.png", bbox_inches="tight")
plt.close()
print("  saved k1068_comparison_k1060.png")


# -----------------------------------------------------------------------------
# Part 7: Save results JSON
# -----------------------------------------------------------------------------
elapsed = time.time() - START_TIME
now_iso = datetime.now(timezone.utc).isoformat()

# Strip pandas DataFrames from per_stock_windows before serializing
per_stock_serializable = {}
for ticker, info in per_stock_windows.items():
    per_stock_serializable[ticker] = {
        "name": info["name"],
        "sector": info["sector"],
        "n_events": info["n_events"],
        "AAR": info["AAR"],
        "CAAR": info["CAAR"],
        "mean_SAR": info["mean_SAR"],
    }

results = {
    "experiment_id": "K1068",
    "title": "Traditional CAR/CASV Event Study for Taiwan Earnings Announcements",
    "proposer": "User (methodological correction of K1059/K1060/K1062)",
    "executor": "Claude",
    "timestamp_utc": now_iso,
    "runtime_seconds": round(elapsed, 1),
    "random_seed": 42,
    "config": {
        "sample_period": f"{START_DATE} to {END_DATE}",
        "market_index": MARKET_INDEX,
        "estimation_window": f"[{ESTIMATION_START},{ESTIMATION_END}]",
        "min_estimation_obs": MIN_ESTIMATION,
        "event_window_days": EVENT_WINDOW,
        "windows": WINDOWS,
        "stocks": STOCKS,
    },
    "data_summary": {
        "announcement_records_total": int(len(ea_df)),
        "announcement_records_sample": int(len(ea_sample)),
        "stocks_loaded": len(stock_returns),
        "total_events_analyzed": int(len(event_df)),
    },
    "pooled_tests": pooled_tests,
    "per_stock_summary": per_stock_summary,
    "per_stock_windows": per_stock_serializable,
    "sector_tests": sector_tests,
    "sector_f_test": {
        "target": "CAR_[-5,+5]",
        "F_stat": float(f_stat) if np.isfinite(f_stat) else None,
        "p_value": float(f_p) if np.isfinite(f_p) else None,
    },
    "hypotheses": hypotheses,
    "k1060_comparison": k1060_comparison,
    "references": [
        "MacKinlay, A.C. (1997) JEL 35(1): 13-39",
        "Brown, S. & Warner, J. (1985) JFE 14(1): 3-31",
        "Patell, J.M. (1976) J Accounting Research 14(2): 246-276",
        "Boehmer, E., Masumeci, J., Poulsen, A.B. (1991) JFE 30(2): 253-272",
        "Patell, J.M. & Wolfson, M.A. (1984) J Accounting Research 22: 223-252",
        "Beaver (1968) J Accounting Research 6: 67-92",
        "Savor & Wilson (2016) JFQA 51(1): 197-224",
        "K1059, K1060, K1062 (prior simplified event-study tests)",
    ],
}

out_path = SCRIPT_DIR / "k1068_results.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\nResults saved to {out_path}")

print("\n" + "=" * 72)
print(f"K1068 done. Elapsed: {elapsed:.1f}s")
print(f"H1 (CAR[-5,+5] != 0): mean={pooled_tests['[-5,+5]']['mean_CAR']:+.4f}, "
      f"t_BW={pooled_tests['[-5,+5]']['t_BW']:+.2f} "
      f"p={pooled_tests['[-5,+5]']['p_BW']:.4f} "
      f"-> {hypotheses['H1_CAR_m5_p5_nonzero']['verdict']}")
print(f"H3 (CASV[-5,+5] > 0): mean={pooled_tests['[-5,+5]']['mean_CASV']:+.3f}, "
      f"t={pooled_tests['[-5,+5]']['t_CASV']:+.2f} "
      f"p={pooled_tests['[-5,+5]']['p_CASV']:.4f} "
      f"-> {hypotheses['H3_CASV_window_elevated']['verdict']}")
print(f"H4 (sector heterogeneity): F={f_stat:.3f} p={f_p:.4f} "
      f"-> {hypotheses['H4_sector_heterogeneity']['verdict']}")
print("=" * 72)
