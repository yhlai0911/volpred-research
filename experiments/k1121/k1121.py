"""
K1121: Alt-data for Portfolio Construction (NOT forecasting)

PARADIGM PIVOT from K1116/K1118:
  - K1116/K1118 (9 experiments) proved alt-data NULL for *forecasting* weekly RV.
  - Hypothesis here: Alt-data may still signal "regime change" useful for *allocation*,
    even if it cannot predict tomorrow's vol.
  - VIX captures implied vol (forecasting use).
  - EPU/NFCI may capture regime shifts (allocation use).

Design:
  - Universe: SPY + GLD (CLAUDE.md 50/50 baseline "不可動搖")
  - Period: 2018-01 to 2026-04, daily
  - 6 strategies:
      S1: Static 50/50 (baseline, K2-K89 已驗證護城河)
      S2: Vol-targeted (w_SPY = clip(0.10/sigma_SPY, 0.2, 1.0), daily refit)
      S3: VIX-regime   (w_SPY = 0.7 if VIX<20 else 0.3)
      S4: EPU-regime   (w_SPY = 0.7 if EPU < 70th pct else 0.3)   <- NEW
      S5: NFCI-regime  (w_SPY = 0.7 if NFCI < 70th pct else 0.3)  <- NEW
      S6: Hybrid       (average of S3/S4/S5 signals)              <- NEW
  - All signals lagged 1 day (weight at t uses info at t-1) - NO LOOKAHEAD.
  - Evaluation: Sharpe, MDD, Sortino, Calmar, rolling OOS Sharpe,
    stationary bootstrap test on Sharpe differences (Politis-Romano 1994).

Data:
  - yfinance: SPY, GLD, ^VIX (daily)
  - FRED: USEPUINDXD (daily), NFCI (weekly -> ffill to daily)

Hypotheses:
  H1 (core): S4 (EPU-regime) or S5 (NFCI-regime) Sharpe > S2 (Vol-targeted)
      - alt-data beats vol-only signal in allocation
  H2 (moat): Any alt-data strategy Sharpe >= S1 (50/50) baseline (CLAUDE.md 護城河)
  H3 (stress): alt-data reduces SPY weight during 2020/03 COVID, 2022 rate shock
  H4 (hybrid): S6 Sharpe > max(S3, S4, S5) single-signal

Results: Even if NULL (no alt-data strategy beats 50/50 or vol-targeted),
  adds evidence that alt-data is dead-end also for allocation, not just forecasting.

Seed: np.random.seed(42) for stationary bootstrap.

References:
  - Baker, Bloom, Davis (2016) QJE - EPU index
  - Brave, Butters (2011) - NFCI
  - Politis, Romano (1994) - stationary bootstrap
  - Opdyke (2007) - Sharpe ratio distribution / SR comparison
  - Harvey, Liu, Zhu (2016) - Sharpe t>3.0 threshold
"""
import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SEED = 42
rng = np.random.default_rng(SEED)
np.random.seed(SEED)

OUT_DIR = Path(__file__).parent
DATA_DIR = OUT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)

RESULTS = {
    "experiment_id": "K1121",
    "title": "Alt-data for portfolio construction (NOT forecasting) — SPY+GLD 6-strategy horse race",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": "yfinance (SPY, GLD, ^VIX) + FRED (USEPUINDXD, NFCI)",
    "pivot_from": "K1116/K1118 9 NULL results — alt-data cannot forecast RV",
    "new_angle": "Allocation not forecasting: does alt-data add regime-detection value?",
    "prior_related": {
        "K1116": "SPY EPU+NFCI+STLFSI forecasting: NULL (actively worsens vs VIX baseline)",
        "K1118": "Cross-asset (GLD/TLT/BTC) alt-data forecasting: NULL",
        "K2-K89": "50/50 SPY/GLD moat — 8 replication studies confirm baseline cannot be beaten",
        "K679": "VIX-percentile timing Sharpe 1.68 -> 0.355 after lag fix (100% artifact)",
        "K687/K697": "VT = drawdown insurance, not alpha generator",
    },
    "hypotheses": {
        "H1_core": "S4 or S5 (alt-data regime) Sharpe > S2 (vol-targeted)",
        "H2_moat": "Any alt-data strategy Sharpe >= S1 (50/50 baseline)",
        "H3_stress": "Alt-data reduces SPY weight during COVID/2022 stress",
        "H4_hybrid": "S6 (hybrid) Sharpe > max(S3, S4, S5) single-signal",
    },
    "references": [
        "Baker, Bloom, Davis (2016) QJE - EPU",
        "Brave, Butters (2011) - NFCI",
        "Politis, Romano (1994) - stationary bootstrap",
        "Opdyke (2007) - Sharpe ratio inference",
        "Harvey, Liu, Zhu (2016) - Sharpe threshold",
    ],
    "seed": SEED,
}


def log(msg):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---- data ----

def fetch_assets():
    import yfinance as yf
    log("Fetching SPY + GLD + VIX daily 2018-2026...")
    tickers = yf.download(["SPY", "GLD", "^VIX"], start="2018-01-01", end="2026-04-13",
                          progress=False, auto_adjust=True, group_by="ticker")
    # rearrange
    if isinstance(tickers.columns, pd.MultiIndex):
        spy = tickers["SPY"]["Close"].rename("SPY")
        gld = tickers["GLD"]["Close"].rename("GLD")
        vix = tickers["^VIX"]["Close"].rename("VIX")
    else:
        raise RuntimeError("expected multiindex")

    df = pd.concat([spy, gld, vix], axis=1).dropna(how="any")
    # Simple returns for portfolio-weight arithmetic exactness (daily rebalance)
    # K2-K89 paper trading convention uses simple returns via portfolio_return.
    df["r_SPY"] = df["SPY"].pct_change()
    df["r_GLD"] = df["GLD"].pct_change()
    # Also compute log returns for vol-targeted rolling std (vol estimation convention)
    df["logr_SPY"] = np.log(df["SPY"]).diff()
    log(f"  daily panel: {len(df)} rows {df.index.min().date()} -> {df.index.max().date()}")
    return df


def fetch_fred():
    """Fetch FRED series via CSV endpoint (pandas_datareader has compatibility issues).

    Caches to data/ dir for repeatability.
    """
    import io
    import time as _time
    import requests

    log("Fetching FRED: USEPUINDXD (daily), NFCI (weekly) via fredgraph CSV...")

    def _fred_csv(series_id, max_retries=5):
        cache_path = DATA_DIR / f"fred_{series_id}.csv"
        if cache_path.exists():
            log(f"  cache hit: {cache_path.name}")
            df = pd.read_csv(cache_path, parse_dates=["DATE"]).set_index("DATE")
            df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
            return df.dropna()

        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; research-agent/1.0)"}
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.get(url, headers=headers, timeout=(20, 90))
                r.raise_for_status()
                df = pd.read_csv(io.StringIO(r.text))
                df.columns = ["DATE", series_id]
                df["DATE"] = pd.to_datetime(df["DATE"])
                df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
                df = df.dropna()
                df.to_csv(cache_path, index=False)
                log(f"  {series_id}: {len(df)} rows, cached -> {cache_path.name}")
                return df.set_index("DATE")
            except Exception as e:
                last_err = e
                wait = 2 ** attempt
                log(f"  {series_id}: attempt {attempt}/{max_retries} failed ({str(e)[:80]}); retry in {wait}s")
                _time.sleep(wait)
        raise RuntimeError(f"FRED fetch failed for {series_id}: {last_err}")

    epu = _fred_csv("USEPUINDXD")
    epu = epu[(epu.index >= "2018-01-01") & (epu.index <= "2026-04-13")]
    nfci = _fred_csv("NFCI")
    nfci = nfci[(nfci.index >= "2018-01-01") & (nfci.index <= "2026-04-13")]
    log(f"  EPU: {len(epu)} rows, last={epu.index[-1].date()}")
    log(f"  NFCI: {len(nfci)} rows, last={nfci.index[-1].date()}")
    return epu, nfci


# ---- signal builders ----

def build_panel(market, epu, nfci):
    """Merge all. EPU daily (ffill NaN days). NFCI weekly -> ffill to daily."""
    df = market.copy()
    df = df.join(epu.rename(columns={"USEPUINDXD": "EPU"}), how="left")
    df = df.join(nfci.rename(columns={"NFCI": "NFCI"}), how="left")
    df["EPU"] = df["EPU"].ffill(limit=5)
    df["NFCI"] = df["NFCI"].ffill(limit=10)
    df = df.dropna(subset=["EPU", "NFCI"])
    log(f"  merged panel: {len(df)} days")
    return df


def compute_signals(df):
    """
    Compute strategy weights. ALL signals use t-1 information for time-t weight.
    Returns DataFrame with columns S1..S6 (each is w_SPY; w_GLD = 1 - w_SPY).
    """
    sig = pd.DataFrame(index=df.index)

    # S1: static 50/50
    sig["S1_wSPY"] = 0.5

    # S2: vol-targeted. sigma_SPY = rolling 20d stdev (ann.) of logr_SPY. target 15% ann vol.
    # w = clip(0.15 / sigma, 0.2, 1.0). Use past 20d, then shift(1) for lag.
    # Use log return for vol estimation (symmetric, additive across time).
    sigma = df["logr_SPY"].rolling(20).std() * np.sqrt(252)
    w2 = (0.15 / sigma).clip(0.2, 1.0)
    sig["S2_wSPY"] = w2.shift(1)  # lag-1, no lookahead

    # S3: VIX regime. w=0.7 if VIX<20 else 0.3. Lag-1.
    s3 = (df["VIX"] < 20).astype(float) * 0.7 + (df["VIX"] >= 20).astype(float) * 0.3
    sig["S3_wSPY"] = s3.shift(1)

    # S4: EPU regime. Use rolling 252d (1yr) percentile of EPU.
    # 70th pct of past 252 days. w=0.7 if EPU below 70pct else 0.3.
    # BUG-FIX: NaN in comparison -> False -> 0.0 weight (artifact). Must propagate NaN.
    def rolling_pct_rank(s, window):
        def _rank(x):
            if len(x) < 2:
                return np.nan
            return (x[:-1] < x[-1]).mean()
        return s.rolling(window + 1).apply(_rank, raw=True)

    def regime_signal(rank_series, thresh=0.7, high_w=0.7, low_w=0.3):
        """Preserve NaN so downstream dropna removes warm-up days."""
        out = pd.Series(np.nan, index=rank_series.index)
        valid = rank_series.notna()
        out[valid & (rank_series < thresh)] = high_w
        out[valid & (rank_series >= thresh)] = low_w
        return out

    # EPU release-timing: USEPUINDXD obs date X is published next day -> 2-day lag conservative
    # NFCI release-timing: obs Friday is published following Wednesday -> 5 trading-day lag
    # (Codex HIGH-severity finding 2026-04-13)
    epu_rank = rolling_pct_rank(df["EPU"], 252)
    s4 = regime_signal(epu_rank, thresh=0.7, high_w=0.7, low_w=0.3)
    sig["S4_wSPY"] = s4.shift(2)  # 2 days for EPU release
    sig["EPU_rank"] = epu_rank

    # S5: NFCI regime. 5-day lag for weekly release cycle.
    nfci_rank = rolling_pct_rank(df["NFCI"], 252)
    s5 = regime_signal(nfci_rank, thresh=0.7, high_w=0.7, low_w=0.3)
    sig["S5_wSPY"] = s5.shift(5)  # 5 trading days for NFCI release (Wed following Fri obs)
    sig["NFCI_rank"] = nfci_rank

    # S6: hybrid - average of S3, S4, S5 raw signals (0.7/0.3). Already lagged.
    sig["S6_wSPY"] = (sig["S3_wSPY"] + sig["S4_wSPY"] + sig["S5_wSPY"]) / 3.0

    return sig


# ---- backtest ----

def backtest(df, sig):
    """For each strategy, compute daily portfolio returns."""
    out = pd.DataFrame(index=df.index)
    out["r_SPY"] = df["r_SPY"]
    out["r_GLD"] = df["r_GLD"]

    for s in ["S1", "S2", "S3", "S4", "S5", "S6"]:
        w = sig[f"{s}_wSPY"]
        # portfolio return = w * r_SPY + (1-w) * r_GLD
        out[f"r_{s}"] = w * df["r_SPY"] + (1 - w) * df["r_GLD"]
    out[f"w_S1"] = sig["S1_wSPY"]
    for s in ["S2", "S3", "S4", "S5", "S6"]:
        out[f"w_{s}"] = sig[f"{s}_wSPY"]
    return out


# ---- metrics ----

def sharpe(r, ann=252):
    r = r.dropna()
    if r.std() == 0 or len(r) < 20:
        return np.nan
    return (r.mean() / r.std()) * np.sqrt(ann)


def sortino(r, ann=252):
    r = r.dropna()
    neg = r[r < 0]
    if len(neg) < 10 or neg.std() == 0:
        return np.nan
    return (r.mean() / neg.std()) * np.sqrt(ann)


def max_drawdown(r):
    r = r.dropna()
    if len(r) == 0:
        return np.nan
    eq = (1 + r).cumprod()
    peak = eq.cummax()
    dd = (eq - peak) / peak
    return dd.min()


def calmar(r, ann=252):
    mdd = max_drawdown(r)
    if np.isnan(mdd) or mdd == 0:
        return np.nan
    ann_ret = r.mean() * ann
    return ann_ret / abs(mdd)


def rolling_sharpe(r, window=252, ann=252):
    return (r.rolling(window).mean() / r.rolling(window).std()) * np.sqrt(ann)


# ---- stationary bootstrap for Sharpe difference ----

def stationary_bootstrap(r1, r2, n_boot=1000, block_mean=20, seed=42):
    """
    Stationary bootstrap (Politis-Romano 1994) for Sharpe diff.
    Returns: observed diff, p-value (2-sided), CI 95%.
    Positive diff = r1 beats r2.
    """
    r1 = r1.dropna()
    r2 = r2.dropna()
    idx = r1.index.intersection(r2.index)
    r1 = r1.reindex(idx).values
    r2 = r2.reindex(idx).values
    n = len(r1)
    if n < 50:
        return {"obs_diff": np.nan, "p_value": np.nan, "ci_low": np.nan, "ci_high": np.nan}

    obs = sharpe(pd.Series(r1)) - sharpe(pd.Series(r2))

    rng_local = np.random.default_rng(seed)
    p = 1.0 / block_mean  # geometric block-length parameter
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        boot_idx = np.empty(n, dtype=int)
        i = rng_local.integers(0, n)
        boot_idx[0] = i
        for k in range(1, n):
            if rng_local.random() < p:
                i = rng_local.integers(0, n)
            else:
                i = (i + 1) % n
            boot_idx[k] = i
        b1 = r1[boot_idx]
        b2 = r2[boot_idx]
        diffs[b] = sharpe(pd.Series(b1)) - sharpe(pd.Series(b2))

    # p-value: fraction of |bootstrap - obs| >= |obs| under null of zero diff
    # Use centered distribution: diffs_centered = diffs - diffs.mean()
    centered = diffs - np.nanmean(diffs)
    p_val = 2 * min(
        np.mean(centered >= abs(obs)),
        np.mean(centered <= -abs(obs))
    )
    ci_low = np.nanpercentile(diffs, 2.5)
    ci_high = np.nanpercentile(diffs, 97.5)
    return {"obs_diff": float(obs), "p_value": float(p_val),
            "ci_low": float(ci_low), "ci_high": float(ci_high)}


# ---- OOS rolling analysis ----

def oos_rolling_sharpe(bt, strategies, window=252):
    """Return rolling 1yr Sharpe for each strategy."""
    out = pd.DataFrame(index=bt.index)
    for s in strategies:
        out[s] = rolling_sharpe(bt[f"r_{s}"], window=window)
    return out


# ---- stress episode analysis ----

def stress_analysis(bt, sig):
    """Did alt-data strategies reduce SPY weight during stress?"""
    episodes = {
        "COVID_2020": ("2020-02-15", "2020-04-30"),
        "Rate_Shock_2022": ("2022-01-01", "2022-10-31"),
        "SVB_2023": ("2023-03-01", "2023-04-15"),
    }
    out = {}
    for name, (start, end) in episodes.items():
        mask = (bt.index >= start) & (bt.index <= end)
        period = bt.loc[mask]
        d = {}
        for s in ["S1", "S2", "S3", "S4", "S5", "S6"]:
            w = period[f"w_{s}"].mean()
            r_mean = period[f"r_{s}"].mean() * 252
            r_std = period[f"r_{s}"].std() * np.sqrt(252)
            sr = r_mean / r_std if r_std > 0 else np.nan
            mdd = max_drawdown(period[f"r_{s}"])
            d[s] = {"avg_wSPY": float(w), "ann_return": float(r_mean),
                    "ann_vol": float(r_std), "sharpe": float(sr) if not np.isnan(sr) else None,
                    "max_drawdown": float(mdd) if not np.isnan(mdd) else None}
        out[name] = {"period": [start, end], "n_days": int(mask.sum()), "by_strategy": d}
    return out


# ---- main ----

def main():
    log("=== K1121: Alt-data for portfolio construction ===")

    # 1. Data
    market = fetch_assets()
    epu, nfci = fetch_fred()
    df = build_panel(market, epu, nfci)
    # Persist raw data to data/ dir for reproducibility
    df.to_parquet(DATA_DIR / "panel.parquet")
    log(f"Saved panel: {DATA_DIR/'panel.parquet'}")

    # 2. Signals
    sig = compute_signals(df)
    sig.to_parquet(DATA_DIR / "signals.parquet")

    # 3. Backtest
    bt = backtest(df, sig)
    # Drop initial rows where signals are NaN
    bt = bt.dropna(subset=["r_S1", "r_S2", "r_S3", "r_S4", "r_S5", "r_S6"])
    log(f"Backtest window: {bt.index.min().date()} -> {bt.index.max().date()} ({len(bt)} days)")
    bt.to_parquet(DATA_DIR / "backtest.parquet")

    strategies = ["S1", "S2", "S3", "S4", "S5", "S6"]

    # 4. Full-sample metrics
    log("--- Full-sample metrics ---")
    full_metrics = {}
    for s in strategies:
        r = bt[f"r_{s}"]
        full_metrics[s] = {
            "ann_return": float(r.mean() * 252),
            "ann_vol": float(r.std() * np.sqrt(252)),
            "sharpe": float(sharpe(r)),
            "sortino": float(sortino(r)),
            "max_drawdown": float(max_drawdown(r)),
            "calmar": float(calmar(r)),
            "avg_wSPY": float(bt[f"w_{s}"].mean()),
            "wSPY_std": float(bt[f"w_{s}"].std()),
        }
        log(f"  {s}: Sharpe={full_metrics[s]['sharpe']:.3f} MDD={full_metrics[s]['max_drawdown']:.3f} "
            f"avg_wSPY={full_metrics[s]['avg_wSPY']:.3f}")

    # 5. IS / OOS split (IS=2018-2022, OOS=2023+)
    log("--- IS/OOS split metrics ---")
    is_mask = bt.index < "2023-01-01"
    oos_mask = bt.index >= "2023-01-01"
    is_oos_metrics = {"IS": {}, "OOS": {}}
    for s in strategies:
        for label, mask in [("IS", is_mask), ("OOS", oos_mask)]:
            r = bt.loc[mask, f"r_{s}"]
            is_oos_metrics[label][s] = {
                "sharpe": float(sharpe(r)),
                "sortino": float(sortino(r)),
                "max_drawdown": float(max_drawdown(r)),
                "ann_return": float(r.mean() * 252),
                "ann_vol": float(r.std() * np.sqrt(252)),
                "n_days": int(mask.sum()),
            }

    # 6. Stationary bootstrap pairwise vs S1 (50/50 baseline)
    log("--- Stationary bootstrap test vs S1 (50/50 baseline) ---")
    boot_vs_s1 = {}
    for s in ["S2", "S3", "S4", "S5", "S6"]:
        res = stationary_bootstrap(bt[f"r_{s}"], bt["r_S1"], n_boot=1000, block_mean=20, seed=SEED)
        boot_vs_s1[f"{s}_vs_S1"] = res
        log(f"  {s} vs S1: diff={res['obs_diff']:.3f} p={res['p_value']:.3f} "
            f"CI=[{res['ci_low']:.3f},{res['ci_high']:.3f}]")

    # 7. Stationary bootstrap pairwise vs S2 (vol-targeted)
    log("--- Stationary bootstrap test vs S2 (vol-targeted) ---")
    boot_vs_s2 = {}
    for s in ["S3", "S4", "S5", "S6"]:
        res = stationary_bootstrap(bt[f"r_{s}"], bt["r_S2"], n_boot=1000, block_mean=20, seed=SEED)
        boot_vs_s2[f"{s}_vs_S2"] = res
        log(f"  {s} vs S2: diff={res['obs_diff']:.3f} p={res['p_value']:.3f}")

    # 8. OOS rolling Sharpe
    log("--- OOS rolling Sharpe (252d window) ---")
    rsharpe = oos_rolling_sharpe(bt, strategies, window=252)
    rsharpe_oos = rsharpe.loc[oos_mask].dropna(how="all")
    rsharpe_summary = {}
    for s in strategies:
        vals = rsharpe_oos[s].dropna()
        rsharpe_summary[s] = {
            "mean": float(vals.mean()) if len(vals) > 0 else None,
            "min": float(vals.min()) if len(vals) > 0 else None,
            "max": float(vals.max()) if len(vals) > 0 else None,
            "pct_negative": float((vals < 0).mean()) if len(vals) > 0 else None,
        }

    # 9. Stress episode analysis
    log("--- Stress episode analysis ---")
    stress = stress_analysis(bt, sig)

    # 10. Hypothesis tests
    log("--- Hypothesis tests ---")
    h_tests = {}
    # H1: S4 or S5 Sharpe > S2
    h_tests["H1_core"] = {
        "S4_vs_S2_sharpe_diff": full_metrics["S4"]["sharpe"] - full_metrics["S2"]["sharpe"],
        "S5_vs_S2_sharpe_diff": full_metrics["S5"]["sharpe"] - full_metrics["S2"]["sharpe"],
        "S4_bootstrap_p": boot_vs_s2["S4_vs_S2"]["p_value"],
        "S5_bootstrap_p": boot_vs_s2["S5_vs_S2"]["p_value"],
        "PASS": ((full_metrics["S4"]["sharpe"] > full_metrics["S2"]["sharpe"]
                  and boot_vs_s2["S4_vs_S2"]["p_value"] < 0.05)
                 or (full_metrics["S5"]["sharpe"] > full_metrics["S2"]["sharpe"]
                     and boot_vs_s2["S5_vs_S2"]["p_value"] < 0.05)),
    }

    # H2: Any alt-data strategy Sharpe >= S1
    alt_sharpes = [full_metrics[s]["sharpe"] for s in ["S4", "S5", "S6"]]
    h_tests["H2_moat"] = {
        "S1_sharpe": full_metrics["S1"]["sharpe"],
        "S4_sharpe": full_metrics["S4"]["sharpe"],
        "S5_sharpe": full_metrics["S5"]["sharpe"],
        "S6_sharpe": full_metrics["S6"]["sharpe"],
        "best_alt_sharpe": max(alt_sharpes),
        "PASS": max(alt_sharpes) >= full_metrics["S1"]["sharpe"],
    }

    # H3: Alt-data reduces SPY weight in stress
    h_tests["H3_stress"] = {
        name: {
            "S1_avg_wSPY": stress[name]["by_strategy"]["S1"]["avg_wSPY"],
            "S4_avg_wSPY": stress[name]["by_strategy"]["S4"]["avg_wSPY"],
            "S5_avg_wSPY": stress[name]["by_strategy"]["S5"]["avg_wSPY"],
            "S4_reduced": stress[name]["by_strategy"]["S4"]["avg_wSPY"] < 0.5,
            "S5_reduced": stress[name]["by_strategy"]["S5"]["avg_wSPY"] < 0.5,
        }
        for name in stress
    }

    # H4: Hybrid > max single signal
    max_single = max(full_metrics["S3"]["sharpe"], full_metrics["S4"]["sharpe"], full_metrics["S5"]["sharpe"])
    h_tests["H4_hybrid"] = {
        "S6_sharpe": full_metrics["S6"]["sharpe"],
        "max_single_sharpe": max_single,
        "PASS": full_metrics["S6"]["sharpe"] > max_single,
    }

    # 11. Save results
    RESULTS["n_days"] = int(len(bt))
    RESULTS["period_actual"] = [str(bt.index.min().date()), str(bt.index.max().date())]
    RESULTS["descriptive"] = {
        "SPY_daily_return_mean": float(df["r_SPY"].mean()),
        "SPY_daily_return_std": float(df["r_SPY"].std()),
        "GLD_daily_return_mean": float(df["r_GLD"].mean()),
        "GLD_daily_return_std": float(df["r_GLD"].std()),
        "SPY_GLD_corr": float(df[["r_SPY", "r_GLD"]].corr().iloc[0, 1]),
        "VIX_mean": float(df["VIX"].mean()),
        "EPU_mean": float(df["EPU"].mean()),
        "NFCI_mean": float(df["NFCI"].mean()),
    }
    RESULTS["full_sample_metrics"] = full_metrics
    RESULTS["is_oos_metrics"] = is_oos_metrics
    RESULTS["bootstrap_vs_S1_50_50"] = boot_vs_s1
    RESULTS["bootstrap_vs_S2_voltarget"] = boot_vs_s2
    RESULTS["rolling_sharpe_OOS_summary"] = rsharpe_summary
    RESULTS["stress_episodes"] = stress
    RESULTS["hypothesis_tests"] = h_tests
    RESULTS["finished_utc"] = datetime.utcnow().isoformat() + "Z"

    # Headline table for quick scan
    headline = []
    for s in strategies:
        headline.append({
            "strategy": s,
            "sharpe_full": round(full_metrics[s]["sharpe"], 3),
            "sharpe_OOS": round(is_oos_metrics["OOS"][s]["sharpe"], 3),
            "mdd": round(full_metrics[s]["max_drawdown"], 3),
            "calmar": round(full_metrics[s]["calmar"], 3),
            "sortino": round(full_metrics[s]["sortino"], 3),
            "avg_wSPY": round(full_metrics[s]["avg_wSPY"], 3),
        })
    RESULTS["headline_table"] = headline

    out_path = OUT_DIR / "k1121_results.json"
    with open(out_path, "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"Saved: {out_path}")

    # Print summary
    log("\n=== HEADLINE TABLE ===")
    hdr = f"{'strat':<5} {'full_SR':>8} {'OOS_SR':>8} {'MDD':>7} {'Calmar':>7} {'avg_wSPY':>9}"
    log(hdr)
    for h in headline:
        log(f"{h['strategy']:<5} {h['sharpe_full']:>8.3f} {h['sharpe_OOS']:>8.3f} "
            f"{h['mdd']:>7.3f} {h['calmar']:>7.3f} {h['avg_wSPY']:>9.3f}")

    log("\n=== HYPOTHESIS TESTS ===")
    log(f"H1 (S4 or S5 > S2): {'PASS' if h_tests['H1_core']['PASS'] else 'FAIL'}")
    log(f"H2 (alt >= 50/50):  {'PASS' if h_tests['H2_moat']['PASS'] else 'FAIL'}")
    log(f"H4 (hybrid>single): {'PASS' if h_tests['H4_hybrid']['PASS'] else 'FAIL'}")
    log(f"H3 stress episodes: {list(h_tests['H3_stress'].keys())}")


if __name__ == "__main__":
    main()
