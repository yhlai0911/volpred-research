"""
K1127 - Cross-asset OFI lead-lag (TAIFEX TX vs ES overnight channel)

Motivation:
  K1100g_d1 found TAIFEX night->day LRT chi2=12.48 p=0.0004 (single-market
  within-Taiwan asymmetric cross-prediction). But K1100g_d2 OOS FAIL.
  K1127 tests whether the asymmetry generalizes across markets via OFI:
  does TX OFI lead/lag ES OFI through overnight information flow?

  Natural lead-lag channels:
    Channel A: ES US-afternoon OFI (21:30-04:00 TW) -> TX next-day open (08:45)
    Channel B: TX TW-close OFI (~13:44 TW) -> ES US-evening open (~21:30 TW)

Data constraints (hard):
  - yfinance ES=F 5-min: only 60 days history -> INFEASIBLE for 2+ year sample
  - yfinance ES=F 1h: 730 days history (2023-11-23 to present) -> USE 1h bars
  - TAIFEX TX tick: 2012-2026 (local 33G), aggregate to 1h bars for alignment

Experiment uses 1h bars (deviation from 5-min in the original spec, documented
in README). This is a hard data constraint.

Design:
  - Period: 2023-11-23 .. 2026-04-16 (~2.4 years overlap, ~570 trading days)
  - TX OFI: tick-level Lee-Ready tick rule -> session OFI (K1124 spec)
    * Day session 08:45-13:44:59 TW
    * Night session 15:00 T -> 05:00 T+1 TW
    * T-1 active contract rolling (K1124 Codex fix)
  - ES=F OFI: from yfinance 1h bars, range-based signed pressure proxy
    (Chordia-Roll-Subrahmanyam 2002 style; cited because tick unavailable)
  - All timestamps UTC for cross-market alignment
  - IS: 2023-11-23 .. 2025-06-30; OOS: 2025-07-01 .. 2026-04-16

Analyses:
  1. Channel A cross-correlation: ES_night_OFI(t) vs TX_day_OFI(t+lag)
  2. Channel B cross-correlation: TX_day_OFI(t) vs ES_eve_OFI(t+lag)
  3. Granger causality (bi-directional, L=2) on daily OFI and |OFI|
  4. Forecasting: M1 within-TX, M2 + ES cross, M3 asymmetric channels
  5. DM-HLN OOS vs M1; verdict scenario A/B/C/D

Author: Claude (worktree agent-k1127)
Date: 2026-04-17
Seed: 42
"""
from __future__ import annotations

import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

np.random.seed(42)

SCRIPT_DIR = Path(__file__).resolve().parent
TAIFEX_DIR = Path("/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python")

DAY_START = 84500
DAY_END = 134459
NIGHT_START = 150000
NIGHT_END = 50000

STUDY_START = pd.Timestamp("2023-11-23")
STUDY_END = pd.Timestamp("2026-04-16")

IS_END = pd.Timestamp("2025-06-30")
OOS_START = pd.Timestamp("2025-07-01")


def _parse_date_from_filename(fname):
    base = fname.replace("Daily_", "")
    try:
        ymd = base.split("TX")[0]
        parts = ymd.split("_")
        if len(parts) != 3:
            return None
        return pd.Timestamp(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None


def _read_taifex_file(path):
    if not path.exists() or path.stat().st_size < 100:
        return None
    for enc in ("big5", "cp950", "utf-8"):
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
            break
        except Exception:
            df = None
    if df is None or len(df) < 10:
        return None
    contract = df.iloc[:, 2].astype(str)
    monthly_mask = contract.str.match(r"^\d{6}$")
    df = df.loc[monthly_mask].copy()
    df["contract_month"] = pd.to_numeric(df.iloc[:, 2], errors="coerce").astype("Int64")
    df["time_int"] = pd.to_numeric(df.iloc[:, 3], errors="coerce").astype("Int64")
    df["price"] = pd.to_numeric(df.iloc[:, 4], errors="coerce")
    df["volume"] = pd.to_numeric(df.iloc[:, 5], errors="coerce")
    df = df.dropna(subset=["contract_month", "time_int", "price", "volume"])
    if len(df) < 10:
        return None
    return df[["contract_month", "time_int", "price", "volume"]]


def _pick_active_contract(df):
    return int(df.groupby("contract_month")["volume"].sum().idxmax())


def _pick_active_contract_rolling(prev_df, curr_df):
    if prev_df is None:
        return _pick_active_contract(curr_df)
    prev_totals = prev_df.groupby("contract_month")["volume"].sum()
    curr_contracts = set(curr_df["contract_month"].unique())
    for contract, _ in prev_totals.sort_values(ascending=False).items():
        if int(contract) in curr_contracts:
            return int(contract)
    return _pick_active_contract(curr_df)


def tick_rule_direction(prices):
    n = len(prices)
    dirs = np.zeros(n, dtype=np.int8)
    prev_dir = 1
    prev_price = prices[0]
    dirs[0] = prev_dir
    for i in range(1, n):
        if prices[i] > prev_price:
            prev_dir = 1
        elif prices[i] < prev_price:
            prev_dir = -1
        dirs[i] = prev_dir
        prev_price = prices[i]
    return dirs


def compute_tx_sessions_for_day(day_df, date):
    day_df = day_df.sort_values("time_int").reset_index(drop=True)
    t = day_df["time_int"].values
    p = day_df["price"].values.astype(float)
    v = day_df["volume"].values.astype(float)

    day_mask = (t >= DAY_START) & (t <= DAY_END)
    early_night_mask = (t >= NIGHT_START)
    late_night_mask = (t <= NIGHT_END) & (t < DAY_START)

    dirs = tick_rule_direction(p)
    signed_vol = dirs.astype(float) * v

    def session_stats(mask, name):
        if mask.sum() < 50:
            return None
        ps = p[mask]
        vs = v[mask]
        svs = signed_vol[mask]
        total_vol = float(vs.sum())
        signed_sum = float(svs.sum())
        ofi = signed_sum / total_vol if total_vol > 0 else 0.0
        log_rets = np.diff(np.log(ps))
        rv = float(np.sum(log_rets ** 2))
        return {
            "date": date,
            "session": name,
            "n_ticks": int(mask.sum()),
            "volume": total_vol,
            "signed_vol": signed_sum,
            "ofi": ofi,
            "rv": rv,
            "price_open": float(ps[0]),
            "price_close": float(ps[-1]),
            "log_ret": float(np.log(ps[-1] / ps[0])),
        }

    return {
        "day": session_stats(day_mask, "day"),
        "night_early": session_stats(early_night_mask, "night_early"),
        "night_late": session_stats(late_night_mask, "night_late"),
    }


def load_tx_sessions(start, end, cache=True):
    cache_path = SCRIPT_DIR / f"_cache_tx_sessions_{start.date()}_{end.date()}.parquet"
    if cache and cache_path.exists():
        print(f"[CACHE] Loading {cache_path.name}")
        df = pd.read_parquet(cache_path)
        df["date"] = pd.to_datetime(df["date"])
        return df

    print(f"[TAIFEX] Scanning {TAIFEX_DIR} for {start.date()}..{end.date()}")
    all_files = sorted(TAIFEX_DIR.glob("Daily_*TX.csv"))
    rows = []
    prev_df = None
    t0 = time.time()
    n_done = 0
    for f in all_files:
        date = _parse_date_from_filename(f.name)
        if date is None or date < (start - pd.Timedelta(days=4)) or date > end:
            continue
        df = _read_taifex_file(f)
        if df is None:
            prev_df = None
            continue
        active = _pick_active_contract_rolling(prev_df, df)
        prev_df = df
        if date < start:
            continue
        df_active = df[df["contract_month"] == active].copy()
        if len(df_active) < 50:
            continue
        sessions = compute_tx_sessions_for_day(df_active, date)
        for s_name, s_dat in sessions.items():
            if s_dat is not None:
                rows.append(s_dat)
        n_done += 1
        if n_done % 50 == 0:
            print(f"  processed {n_done} days, elapsed {time.time()-t0:.1f}s")

    out = pd.DataFrame(rows)
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"])
        out = out.sort_values(["date", "session"]).reset_index(drop=True)
    print(f"[TAIFEX] Loaded {n_done} days, {len(out)} session rows, {time.time()-t0:.1f}s")
    if cache:
        out.to_parquet(cache_path, index=False)
        print(f"[CACHE] Saved to {cache_path.name}")
    return out


def load_es_1h(start, end, cache=True):
    """ES=F 1h from yfinance. Range-based OFI proxy:
       direction = sign(close - open)
       magnitude = |close-open|/(high-low)  in [0,1]
       OFI = direction * magnitude
    """
    cache_path = SCRIPT_DIR / f"_cache_es_1h_{start.date()}_{end.date()}.parquet"
    if cache and cache_path.exists():
        print(f"[CACHE] Loading {cache_path.name}")
        return pd.read_parquet(cache_path)

    import yfinance as yf
    print(f"[YF] Fetching ES=F 1h from {start.date()} to {end.date()}")
    es = yf.Ticker("ES=F")
    df = es.history(period="730d", interval="1h", auto_adjust=False)
    if df.empty:
        raise RuntimeError("ES=F 1h returned empty")
    df.index = df.index.tz_convert("UTC")
    df = df.reset_index().rename(columns={"Datetime": "datetime_utc", "Open": "open",
                                          "High": "high", "Low": "low", "Close": "close",
                                          "Volume": "volume"})
    df = df[(df["datetime_utc"] >= pd.Timestamp(start, tz="UTC")) &
            (df["datetime_utc"] <= pd.Timestamp(end + pd.Timedelta(days=1), tz="UTC"))]
    df = df.sort_values("datetime_utc").reset_index(drop=True)

    range_ = df["high"] - df["low"]
    range_ = range_.replace(0, np.nan)
    direction = np.sign(df["close"] - df["open"])
    magnitude = np.abs(df["close"] - df["open"]) / range_
    magnitude = magnitude.fillna(0).clip(0, 1)
    df["ofi"] = direction * magnitude
    df["ofi"] = df["ofi"].fillna(0)
    df["log_ret"] = np.log(df["close"]).diff()
    df["rv"] = df["log_ret"] ** 2
    df = df.dropna(subset=["volume", "close"])
    df = df[df["volume"] > 0].reset_index(drop=True)

    print(f"[YF] ES=F 1h loaded {len(df)} bars, from {df['datetime_utc'].min()} to {df['datetime_utc'].max()}")
    if cache:
        df.to_parquet(cache_path, index=False)
        print(f"[CACHE] Saved to {cache_path.name}")
    return df


def aggregate_es_windows(es):
    """Aggregate ES 1h into TW-date-keyed windows.
    Windows:
      - es_night_pre_tw_open: (T-1 18:00 UTC, T 00:45 UTC]
        = US afternoon + post-close, strictly BEFORE TX day T opens.
        (Eliminates look-ahead when predicting TX day T RV.)
      - es_night_for_tw_full: (T-1 18:00 UTC, T 05:00 UTC]
        = includes first 4.25h of TX day (for cross-corr analysis only).
      - es_eve_after_tw: (T 13:00 UTC, T 21:00 UTC]
        = US morning/afternoon after TW close T.
    """
    es = es.copy()
    es["utc"] = es["datetime_utc"]
    es["utc_date"] = es["utc"].dt.date

    records = []
    unique_dates = sorted(es["utc_date"].unique())
    es_sorted = es.sort_values("utc").reset_index(drop=True)

    # Extend forward one more calendar day to catch next-day night window
    all_tw_dates = set(unique_dates)
    for d in unique_dates:
        all_tw_dates.add((pd.Timestamp(d) + pd.Timedelta(days=1)).date())
    for d in sorted(all_tw_dates):
        d_ts = pd.Timestamp(d)

        # Window 1: strictly pre-TX-open (no lookahead)
        # Gemini audit fix: yfinance 1h bars are interval-START; a bar timestamped
        # 00:00 UTC covers [00:00, 01:00) which spans 15 min AFTER TW 08:45 open.
        # To avoid this leak, end window at 00:00 UTC (exclusive on bar starting 00:00).
        # This means last ES bar used is timestamped 23:00 UTC T-1 (covering 23:00-24:00),
        # strictly BEFORE TX day T opens at 00:45 UTC T.
        w1s = pd.Timestamp(d_ts - pd.Timedelta(days=1)).tz_localize("UTC") + pd.Timedelta(hours=18)
        w1e = pd.Timestamp(d_ts).tz_localize("UTC")  # 00:00 UTC (inclusive end = last bar at 23:00 UTC T-1)
        mask = (es_sorted["utc"] > w1s) & (es_sorted["utc"] < w1e)
        sub = es_sorted.loc[mask]
        if len(sub) >= 2:
            tv = sub["volume"].sum()
            ofi = float((sub["ofi"] * sub["volume"]).sum() / tv) if tv > 0 else 0.0
            records.append({"tw_date": d_ts, "window": "es_night_pre_tw_open",
                            "n_bars": len(sub), "volume": float(tv),
                            "ofi": ofi, "rv": float(sub["rv"].sum()),
                            "log_ret": float(sub["log_ret"].sum())})

        # Window 2: full overnight (for diagnostic cross-corr)
        w2s = w1s
        w2e = pd.Timestamp(d_ts).tz_localize("UTC") + pd.Timedelta(hours=5)
        mask = (es_sorted["utc"] > w2s) & (es_sorted["utc"] <= w2e)
        sub = es_sorted.loc[mask]
        if len(sub) >= 2:
            tv = sub["volume"].sum()
            ofi = float((sub["ofi"] * sub["volume"]).sum() / tv) if tv > 0 else 0.0
            records.append({"tw_date": d_ts, "window": "es_night_for_tw_full",
                            "n_bars": len(sub), "volume": float(tv),
                            "ofi": ofi, "rv": float(sub["rv"].sum()),
                            "log_ret": float(sub["log_ret"].sum())})

        # Window 3: ES evening after TW close
        w3s = pd.Timestamp(d_ts).tz_localize("UTC") + pd.Timedelta(hours=13)
        w3e = pd.Timestamp(d_ts).tz_localize("UTC") + pd.Timedelta(hours=21)
        mask = (es_sorted["utc"] > w3s) & (es_sorted["utc"] <= w3e)
        sub = es_sorted.loc[mask]
        if len(sub) >= 2:
            tv = sub["volume"].sum()
            ofi = float((sub["ofi"] * sub["volume"]).sum() / tv) if tv > 0 else 0.0
            records.append({"tw_date": d_ts, "window": "es_eve_after_tw",
                            "n_bars": len(sub), "volume": float(tv),
                            "ofi": ofi, "rv": float(sub["rv"].sum()),
                            "log_ret": float(sub["log_ret"].sum())})
    return pd.DataFrame(records)


def build_cross_market_panel(tx, es_windows):
    tx = tx.copy()
    tx_piv = tx.pivot_table(index="date", columns="session",
                            values=["ofi", "rv", "volume"], aggfunc="first")
    tx_piv.columns = [f"{col[1]}_{col[0]}" for col in tx_piv.columns]
    tx_piv = tx_piv.reset_index()

    tx_piv["night_late_ofi_shift"] = tx_piv["night_late_ofi"].shift(-1)
    tx_piv["night_late_rv_shift"] = tx_piv["night_late_rv"].shift(-1)
    tx_piv["night_late_vol_shift"] = tx_piv["night_late_volume"].shift(-1)

    w_early = tx_piv["night_early_volume"].fillna(0)
    w_late = tx_piv["night_late_vol_shift"].fillna(0)
    total = w_early + w_late
    tx_piv["tx_night_ofi"] = np.where(
        total > 0,
        (tx_piv["night_early_ofi"].fillna(0) * w_early +
         tx_piv["night_late_ofi_shift"].fillna(0) * w_late) / total.replace(0, np.nan),
        np.nan
    )
    tx_piv["tx_night_rv"] = (tx_piv["night_early_rv"].fillna(0) +
                             tx_piv["night_late_rv_shift"].fillna(0)).replace(0, np.nan)
    tx_piv["tx_day_ofi"] = tx_piv["day_ofi"]
    tx_piv["tx_day_rv"] = tx_piv["day_rv"]

    tx_clean = tx_piv[["date", "tx_day_ofi", "tx_day_rv", "tx_night_ofi", "tx_night_rv"]].copy()
    tx_clean = tx_clean.rename(columns={"date": "tw_date"})

    es_piv = es_windows.pivot_table(index="tw_date", columns="window",
                                     values=["ofi", "rv"], aggfunc="first")
    es_piv.columns = [f"{col[1]}_{col[0]}" for col in es_piv.columns]
    es_piv = es_piv.reset_index()

    panel = pd.merge(tx_clean, es_piv, on="tw_date", how="inner")
    panel = panel.sort_values("tw_date").reset_index(drop=True)
    return panel


def cross_corr_lags(x, y, max_lag=4):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    x = x - np.nanmean(x)
    y = y - np.nanmean(y)
    result = {}
    for k in range(-max_lag, max_lag + 1):
        if k >= 0:
            x_cut = x[:len(x) - k]
            y_cut = y[k:]
        else:
            x_cut = x[-k:]
            y_cut = y[:len(y) + k]
        mask = np.isfinite(x_cut) & np.isfinite(y_cut)
        if mask.sum() < 30:
            result[k] = np.nan
            continue
        x_m = x_cut[mask]
        y_m = y_cut[mask]
        sx = np.sqrt(np.sum(x_m ** 2))
        sy = np.sqrt(np.sum(y_m ** 2))
        if sx == 0 or sy == 0:
            result[k] = np.nan
            continue
        result[k] = float(np.sum(x_m * y_m) / (sx * sy))
    return result


def granger_test(y, x, max_lag=2):
    """Does x Granger-cause y? F-test on lagged x coefficients."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n = len(y)
    if n != len(x):
        raise ValueError("length mismatch")
    L = max_lag
    rows = []
    for t in range(L, n):
        row = [1.0]
        for i in range(1, L + 1):
            row.append(y[t - i])
        for i in range(1, L + 1):
            row.append(x[t - i])
        row.append(y[t])
        rows.append(row)
    if len(rows) < 20:
        return {"F": np.nan, "p": np.nan, "df_num": L, "df_den": 0, "n": 0}
    arr = np.array(rows)
    mask = np.all(np.isfinite(arr), axis=1)
    arr = arr[mask]
    if len(arr) < 20:
        return {"F": np.nan, "p": np.nan, "df_num": L, "df_den": 0, "n": int(mask.sum())}

    X_full = arr[:, :-1]
    y_t = arr[:, -1]
    beta_full, *_ = np.linalg.lstsq(X_full, y_t, rcond=None)
    ssr_full = float(np.sum((y_t - X_full @ beta_full) ** 2))
    X_restr = arr[:, :1 + L]
    beta_restr, *_ = np.linalg.lstsq(X_restr, y_t, rcond=None)
    ssr_restr = float(np.sum((y_t - X_restr @ beta_restr) ** 2))
    q = L
    df_den = len(y_t) - (1 + 2 * L)
    if df_den <= 0 or ssr_full <= 0:
        return {"F": np.nan, "p": np.nan, "df_num": q, "df_den": df_den, "n": int(len(arr))}
    F = ((ssr_restr - ssr_full) / q) / (ssr_full / df_den)
    from scipy.stats import f as f_dist
    p = 1 - f_dist.cdf(F, q, df_den)
    return {"F": float(F), "p": float(p), "df_num": q, "df_den": int(df_den), "n": int(len(arr))}


def fit_ols(X, y):
    X1 = np.hstack([np.ones((len(X), 1)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return beta


def predict_ols(X, beta):
    X1 = np.hstack([np.ones((len(X), 1)), X])
    return X1 @ beta


def dm_hln(e1, e2, h=1):
    d = e1 - e2
    mask = np.isfinite(d)
    d = d[mask]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    mean_d = np.mean(d)
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0 / n
    if var_d <= 0:
        return 0.0, 1.0
    dm = mean_d / np.sqrt(var_d)
    k = ((n + 1 - 2 * h + h * (h - 1) / n) / n) ** 0.5
    dm_hln_stat = dm * k
    df = n - 1
    pval = 2 * (1 - sp_stats.t.cdf(abs(dm_hln_stat), df=df))
    return float(dm_hln_stat), float(pval)


def qlike_loss(y_true, y_pred):
    y_pred = np.clip(y_pred, 1e-12, None)
    y_true = np.clip(y_true, 1e-12, None)
    return y_true / y_pred - np.log(y_true / y_pred) - 1


def main():
    print("=" * 60)
    print("K1127 - Cross-asset OFI lead-lag (TX vs ES)")
    print("=" * 60)

    print("\n[Step 1] Load TAIFEX TX sessions")
    tx = load_tx_sessions(STUDY_START, STUDY_END, cache=True)
    print(f"TX session rows: {len(tx)}, days: {tx['date'].nunique()}")
    print(tx["session"].value_counts())

    print("\n[Step 2] Load ES=F 1h bars")
    es = load_es_1h(STUDY_START, STUDY_END, cache=True)
    print(f"ES 1h bars: {len(es)}")

    tx_days = tx["date"].nunique()
    es_days = es["datetime_utc"].dt.date.nunique()
    coverage_pct = 100 * min(tx_days, es_days) / max(tx_days, es_days)
    print(f"\n[Coverage] TX days={tx_days}, ES dates={es_days}, ratio={coverage_pct:.1f}%")
    if coverage_pct < 20:
        print("DATA_INFEASIBLE: terminating.")
        final = {
            "experiment_id": "K1127",
            "verdict": "DATA_INFEASIBLE",
            "reason": f"ES coverage {coverage_pct:.1f}% < 20%",
            "tx_days": int(tx_days),
            "es_days": int(es_days),
        }
        with open(SCRIPT_DIR / "k1127_results.json", "w") as f:
            json.dump(final, f, indent=2, default=str)
        return final

    print("\n[Step 3] Aggregate ES into TW-date overnight windows")
    es_windows = aggregate_es_windows(es)
    print(f"ES window rows: {len(es_windows)}")
    print(es_windows.groupby("window").size())

    print("\n[Step 4] Build cross-market panel")
    panel = build_cross_market_panel(tx, es_windows)
    print(f"Panel rows: {len(panel)}")
    if len(panel) > 0:
        print(f"Period: {panel['tw_date'].min().date()}..{panel['tw_date'].max().date()}")

    # Use the lookahead-free ES window for main analysis
    key_cols = ["tx_day_ofi", "tx_day_rv", "tx_night_ofi", "tx_night_rv",
                "es_night_pre_tw_open_ofi", "es_night_pre_tw_open_rv",
                "es_eve_after_tw_ofi", "es_eve_after_tw_rv"]
    missing = [c for c in key_cols if c not in panel.columns]
    if missing:
        print(f"Missing panel cols: {missing}")
        # Fall back: check what we have
        print(f"Actual panel cols: {panel.columns.tolist()}")
    panel_c = panel.dropna(subset=[c for c in key_cols if c in panel.columns]).reset_index(drop=True)
    print(f"Complete-case panel: {len(panel_c)} rows")
    if len(panel_c) < 50:
        print(f"Too few rows: {len(panel_c)}.")
        final = {
            "experiment_id": "K1127",
            "verdict": "DATA_INFEASIBLE",
            "reason": f"aligned days = {len(panel_c)} < 50",
            "tx_days": int(tx_days),
            "es_days": int(es_days),
            "panel_rows": int(len(panel)),
        }
        with open(SCRIPT_DIR / "k1127_results.json", "w") as f:
            json.dump(final, f, indent=2, default=str)
        return final

    print("\n[Step 5] Cross-correlation analysis")

    # Channel A: ES overnight (pre-TX-open) vs TX day
    ch_a_ofi = cross_corr_lags(panel_c["es_night_pre_tw_open_ofi"].values,
                               panel_c["tx_day_ofi"].values, max_lag=4)
    ch_a_rv = cross_corr_lags(panel_c["es_night_pre_tw_open_rv"].values,
                              panel_c["tx_day_rv"].values, max_lag=4)
    ch_a_abs_ofi = cross_corr_lags(np.abs(panel_c["es_night_pre_tw_open_ofi"].values),
                                   np.abs(panel_c["tx_day_ofi"].values), max_lag=4)
    print("Channel A (ES overnight -> TX day):")
    for k in sorted(ch_a_ofi.keys()):
        print(f"  lag {k:+d}: OFI={ch_a_ofi[k]:+.4f}, RV={ch_a_rv[k]:+.4f}, |OFI|={ch_a_abs_ofi[k]:+.4f}")

    # Channel B: TX day vs ES evening
    ch_b_ofi = cross_corr_lags(panel_c["tx_day_ofi"].values,
                               panel_c["es_eve_after_tw_ofi"].values, max_lag=4)
    ch_b_rv = cross_corr_lags(panel_c["tx_day_rv"].values,
                              panel_c["es_eve_after_tw_rv"].values, max_lag=4)
    ch_b_abs_ofi = cross_corr_lags(np.abs(panel_c["tx_day_ofi"].values),
                                   np.abs(panel_c["es_eve_after_tw_ofi"].values), max_lag=4)
    print("Channel B (TX day -> ES evening):")
    for k in sorted(ch_b_ofi.keys()):
        print(f"  lag {k:+d}: OFI={ch_b_ofi[k]:+.4f}, RV={ch_b_rv[k]:+.4f}, |OFI|={ch_b_abs_ofi[k]:+.4f}")

    print("\n[Step 6] Granger causality (L=2)")
    g_A_ofi = granger_test(panel_c["tx_day_ofi"].values,
                           panel_c["es_night_pre_tw_open_ofi"].values, max_lag=2)
    g_A_rv = granger_test(panel_c["tx_day_rv"].values,
                          panel_c["es_night_pre_tw_open_rv"].values, max_lag=2)
    g_A_absofi = granger_test(np.abs(panel_c["tx_day_ofi"].values),
                              np.abs(panel_c["es_night_pre_tw_open_ofi"].values), max_lag=2)
    g_B_ofi = granger_test(panel_c["es_eve_after_tw_ofi"].values,
                           panel_c["tx_day_ofi"].values, max_lag=2)
    g_B_rv = granger_test(panel_c["es_eve_after_tw_rv"].values,
                          panel_c["tx_day_rv"].values, max_lag=2)
    g_B_absofi = granger_test(np.abs(panel_c["es_eve_after_tw_ofi"].values),
                              np.abs(panel_c["tx_day_ofi"].values), max_lag=2)
    print("Channel A (ES -> TX):")
    print(f"  OFI F={g_A_ofi['F']:.3f}, p={g_A_ofi['p']:.4f}")
    print(f"  RV F={g_A_rv['F']:.3f}, p={g_A_rv['p']:.4f}")
    print(f"  |OFI| F={g_A_absofi['F']:.3f}, p={g_A_absofi['p']:.4f}")
    print("Channel B (TX -> ES):")
    print(f"  OFI F={g_B_ofi['F']:.3f}, p={g_B_ofi['p']:.4f}")
    print(f"  RV F={g_B_rv['F']:.3f}, p={g_B_rv['p']:.4f}")
    print(f"  |OFI| F={g_B_absofi['F']:.3f}, p={g_B_absofi['p']:.4f}")

    print("\n[Step 7] Forecasting models (target: tx_day_rv)")
    df = panel_c.copy().reset_index(drop=True)
    df["tx_day_rv_lag1"] = df["tx_day_rv"].shift(1)
    df["tx_day_abs_ofi_lag1"] = np.abs(df["tx_day_ofi"].shift(1))
    df["tx_day_ofi_lag1"] = df["tx_day_ofi"].shift(1)
    # For ES, use the same-date overnight (pre-open window) as overnight info available before TX open
    # This is LEGITIMATE overnight info for predicting TX day t (no lookahead)
    df["es_night_rv_sameday"] = df["es_night_pre_tw_open_rv"]
    df["es_night_absofi_sameday"] = np.abs(df["es_night_pre_tw_open_ofi"])
    df["es_night_ofi_sameday"] = df["es_night_pre_tw_open_ofi"]
    # TX night "prior" (night session starting T-1 15:00 ending T 05:00) -> not in our panel directly
    # Our tx_night_ofi[t] is night starting 15:00 T. For predicting day T we need night starting T-1.
    df["tx_night_rv_prior"] = df["tx_night_rv"].shift(1)
    df["tx_night_ofi_prior"] = df["tx_night_ofi"].shift(1)

    df = df.dropna(subset=["tx_day_rv", "tx_day_rv_lag1", "tx_day_abs_ofi_lag1",
                           "es_night_rv_sameday", "es_night_absofi_sameday",
                           "tx_night_rv_prior", "tx_night_ofi_prior"]).reset_index(drop=True)

    is_mask = df["tw_date"] <= IS_END
    oos_mask = df["tw_date"] >= OOS_START
    df_is = df.loc[is_mask].copy().reset_index(drop=True)
    df_oos = df.loc[oos_mask].copy().reset_index(drop=True)
    print(f"IS rows={len(df_is)} ({df_is['tw_date'].min().date() if len(df_is)>0 else 'NA'}..{df_is['tw_date'].max().date() if len(df_is)>0 else 'NA'})")
    print(f"OOS rows={len(df_oos)} ({df_oos['tw_date'].min().date() if len(df_oos)>0 else 'NA'}..{df_oos['tw_date'].max().date() if len(df_oos)>0 else 'NA'})")

    if len(df_is) < 20 or len(df_oos) < 20:
        print("Too few IS/OOS for modeling; reporting cross-corr/Granger only.")
        final = _package_results(panel_c, tx_days, es_days, coverage_pct,
                                  ch_a_ofi, ch_a_rv, ch_a_abs_ofi,
                                  ch_b_ofi, ch_b_rv, ch_b_abs_ofi,
                                  g_A_ofi, g_A_rv, g_A_absofi,
                                  g_B_ofi, g_B_rv, g_B_absofi,
                                  None, None, None, None,
                                  df_is, df_oos)
        with open(SCRIPT_DIR / "k1127_results.json", "w") as f:
            json.dump(final, f, indent=2, default=str)
        return final

    y_is = df_is["tx_day_rv"].values
    y_oos = df_oos["tx_day_rv"].values

    def run_model(feature_cols, name):
        X_is = df_is[feature_cols].values
        X_oos = df_oos[feature_cols].values
        beta = fit_ols(X_is, y_is)
        p_is = np.clip(predict_ols(X_is, beta), 1e-12, None)
        p_oos = np.clip(predict_ols(X_oos, beta), 1e-12, None)
        return {
            "name": name,
            "features": feature_cols,
            "beta": beta.tolist(),
            "IS_QLIKE": float(np.mean(qlike_loss(y_is, p_is))),
            "OOS_QLIKE": float(np.mean(qlike_loss(y_oos, p_oos))),
            "q_oos": qlike_loss(y_oos, p_oos),
        }

    M1 = run_model(["tx_day_rv_lag1", "tx_day_abs_ofi_lag1"], "M1_within_TX")
    M2 = run_model(["tx_day_rv_lag1", "tx_day_abs_ofi_lag1",
                    "es_night_rv_sameday", "es_night_absofi_sameday"], "M2_plus_ES_cross")
    M3 = run_model(["tx_day_rv_lag1", "tx_day_abs_ofi_lag1",
                    "es_night_rv_sameday", "es_night_ofi_sameday",
                    "tx_night_rv_prior", "tx_night_ofi_prior"], "M3_asymmetric")

    print(f"M1: IS QLIKE={M1['IS_QLIKE']:.4f}, OOS QLIKE={M1['OOS_QLIKE']:.4f}")
    print(f"M2: IS QLIKE={M2['IS_QLIKE']:.4f}, OOS QLIKE={M2['OOS_QLIKE']:.4f}")
    print(f"M3: IS QLIKE={M3['IS_QLIKE']:.4f}, OOS QLIKE={M3['OOS_QLIKE']:.4f}")

    dm_results = {}
    for name, m in [("M2", M2), ("M3", M3)]:
        dm, pval = dm_hln(M1["q_oos"], m["q_oos"], h=1)
        qlike_impr = 100 * (M1["OOS_QLIKE"] - m["OOS_QLIKE"]) / M1["OOS_QLIKE"]
        dm_results[name] = {"dm_stat": dm, "dm_pvalue": pval,
                            "qlike_improvement_pct": qlike_impr}
        print(f"DM {name} vs M1: t={dm:+.3f}, p={pval:.4f}, QLIKE impr={qlike_impr:+.2f}%")

    final = _package_results(panel_c, tx_days, es_days, coverage_pct,
                              ch_a_ofi, ch_a_rv, ch_a_abs_ofi,
                              ch_b_ofi, ch_b_rv, ch_b_abs_ofi,
                              g_A_ofi, g_A_rv, g_A_absofi,
                              g_B_ofi, g_B_rv, g_B_absofi,
                              M1, M2, M3, dm_results,
                              df_is, df_oos)
    with open(SCRIPT_DIR / "k1127_results.json", "w") as f:
        json.dump(final, f, indent=2, default=str)
    print(f"\n[DONE] Wrote {SCRIPT_DIR / 'k1127_results.json'}")

    make_plots(panel_c, ch_a_ofi, ch_a_abs_ofi, ch_b_ofi, ch_b_abs_ofi,
               M1, M2, M3, final["cross_correlations"]["critical_95pct_threshold"], SCRIPT_DIR)

    return final


def _package_results(panel_c, tx_days, es_days, coverage_pct,
                      ch_a_ofi, ch_a_rv, ch_a_abs_ofi,
                      ch_b_ofi, ch_b_rv, ch_b_abs_ofi,
                      g_A_ofi, g_A_rv, g_A_absofi,
                      g_B_ofi, g_B_rv, g_B_absofi,
                      M1, M2, M3, dm_results,
                      df_is, df_oos):
    n_pair = len(panel_c)
    cr95 = 2 / np.sqrt(n_pair) if n_pair > 0 else np.nan

    a_sig_ofi_lag0 = abs(ch_a_ofi.get(0, 0)) > cr95
    a_sig_absofi_lag0 = abs(ch_a_abs_ofi.get(0, 0)) > cr95
    a_granger = (g_A_ofi["p"] is not None and g_A_ofi["p"] < 0.05) or \
                (g_A_absofi["p"] is not None and g_A_absofi["p"] < 0.05)
    b_sig_ofi_lag0 = abs(ch_b_ofi.get(0, 0)) > cr95
    b_sig_absofi_lag0 = abs(ch_b_abs_ofi.get(0, 0)) > cr95
    b_granger = (g_B_ofi["p"] is not None and g_B_ofi["p"] < 0.05) or \
                (g_B_absofi["p"] is not None and g_B_absofi["p"] < 0.05)

    channel_A_pass = (a_sig_ofi_lag0 or a_sig_absofi_lag0) and a_granger
    channel_B_pass = (b_sig_ofi_lag0 or b_sig_absofi_lag0) and b_granger

    if channel_A_pass and channel_B_pass:
        scenario = "C"
        verdict_text = "Bi-directional overnight info transfer"
    elif channel_A_pass and not channel_B_pass:
        scenario = "A"
        verdict_text = "US overnight info flows into TW microstructure (standard global lead-lag)"
    elif not channel_A_pass and channel_B_pass:
        scenario = "B"
        verdict_text = "Asia-first price discovery - novel"
    else:
        scenario = "D"
        verdict_text = "Microstructure info does not cross markets at daily aggregate"

    final = {
        "experiment_id": "K1127",
        "title": "Cross-asset OFI lead-lag TX vs ES overnight channel",
        "data_source": "TAIFEX TX tick (local) + yfinance ES=F 1h (730d)",
        "data_constraint_note": "5-min ES unavailable >60d; used 1h bars",
        "period": {"start": str(STUDY_START.date()), "end": str(STUDY_END.date())},
        "n_tx_days": int(tx_days),
        "n_es_dates": int(es_days),
        "n_aligned_days": int(len(panel_c)),
        "coverage_pct": float(coverage_pct),
        "IS_period": (f"{df_is['tw_date'].min().date()}..{df_is['tw_date'].max().date()}"
                      if len(df_is) > 0 else "NA"),
        "OOS_period": (f"{df_oos['tw_date'].min().date()}..{df_oos['tw_date'].max().date()}"
                       if len(df_oos) > 0 else "NA"),
        "n_IS": int(len(df_is)),
        "n_OOS": int(len(df_oos)),
        "cross_correlations": {
            "channel_A_es_to_tx": {
                "ofi": {str(k): v for k, v in ch_a_ofi.items()},
                "rv": {str(k): v for k, v in ch_a_rv.items()},
                "abs_ofi": {str(k): v for k, v in ch_a_abs_ofi.items()},
            },
            "channel_B_tx_to_es": {
                "ofi": {str(k): v for k, v in ch_b_ofi.items()},
                "rv": {str(k): v for k, v in ch_b_rv.items()},
                "abs_ofi": {str(k): v for k, v in ch_b_abs_ofi.items()},
            },
            "critical_95pct_threshold": float(cr95) if np.isfinite(cr95) else None,
        },
        "granger_tests": {
            "channel_A_es_to_tx": {"ofi": g_A_ofi, "rv": g_A_rv, "abs_ofi": g_A_absofi},
            "channel_B_tx_to_es": {"ofi": g_B_ofi, "rv": g_B_rv, "abs_ofi": g_B_absofi},
        },
        "models": {
            "M1_within_TX": {k: v for k, v in M1.items() if k != "q_oos"} if M1 else None,
            "M2_plus_ES_cross": {k: v for k, v in M2.items() if k != "q_oos"} if M2 else None,
            "M3_asymmetric": {k: v for k, v in M3.items() if k != "q_oos"} if M3 else None,
        },
        "dm_tests_vs_M1": dm_results if dm_results else {},
        "verdict": {
            "scenario": scenario,
            "description": verdict_text,
            "channel_A_pass": bool(channel_A_pass),
            "channel_B_pass": bool(channel_B_pass),
        },
    }
    return final


def make_plots(panel_c, ch_a_ofi, ch_a_abs_ofi, ch_b_ofi, ch_b_abs_ofi,
               M1, M2, M3, cr95, out_dir):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    lags = sorted(ch_a_ofi.keys())
    a_ofi = [ch_a_ofi[k] for k in lags]
    a_absofi = [ch_a_abs_ofi[k] for k in lags]
    b_ofi = [ch_b_ofi[k] for k in lags]
    b_absofi = [ch_b_abs_ofi[k] for k in lags]

    axes[0].stem(lags, a_ofi, basefmt=" ", linefmt="C0-", markerfmt="C0o", label="signed OFI")
    axes[0].stem([x + 0.2 for x in lags], a_absofi, basefmt=" ", linefmt="C1-", markerfmt="C1s", label="|OFI|")
    if cr95 is not None:
        axes[0].axhline(cr95, color="gray", ls="--", lw=0.8, label=f"+/-{cr95:.3f} 95% CI")
        axes[0].axhline(-cr95, color="gray", ls="--", lw=0.8)
    axes[0].axhline(0, color="black", lw=0.5)
    axes[0].set_title("Channel A: ES overnight -> TX day OFI")
    axes[0].set_xlabel("lag (days)")
    axes[0].set_ylabel("cross-correlation")
    axes[0].legend(fontsize=8)

    axes[1].stem(lags, b_ofi, basefmt=" ", linefmt="C0-", markerfmt="C0o", label="signed OFI")
    axes[1].stem([x + 0.2 for x in lags], b_absofi, basefmt=" ", linefmt="C1-", markerfmt="C1s", label="|OFI|")
    if cr95 is not None:
        axes[1].axhline(cr95, color="gray", ls="--", lw=0.8)
        axes[1].axhline(-cr95, color="gray", ls="--", lw=0.8)
    axes[1].axhline(0, color="black", lw=0.5)
    axes[1].set_title("Channel B: TX day -> ES eve OFI")
    axes[1].set_xlabel("lag (days)")
    axes[1].set_ylabel("cross-correlation")
    axes[1].legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "tx_es_ofi_crosscorr.png", dpi=100)
    plt.close()

    if M1 is not None and M2 is not None and M3 is not None:
        fig, ax = plt.subplots(figsize=(9, 5))
        labels = ["M1\nwithin-TX", "M2\n+ES cross", "M3\nasymmetric"]
        vals = [M1["OOS_QLIKE"], M2["OOS_QLIKE"], M3["OOS_QLIKE"]]
        colors = ["gray", "steelblue", "coral"]
        bars = ax.bar(labels, vals, color=colors, alpha=0.8)
        ax.set_ylabel("OOS QLIKE (lower better)")
        ax.set_title("K1127 OOS QLIKE: within-TX vs cross-market overnight features")
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.4f}",
                    ha="center", va="bottom", fontsize=9)
        plt.tight_layout()
        plt.savefig(out_dir / "overnight_info_transfer.png", dpi=100)
        plt.close()


if __name__ == "__main__":
    main()
