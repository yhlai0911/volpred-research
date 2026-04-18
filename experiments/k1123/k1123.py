"""
K1123: Cross-asset alt-data allocation (SPY + GLD + TLT)

EXTENSION OF K1121:
  K1121 tested alt-data regime signals on 2-asset SPY+GLD portfolio.
  Finding: S4 EPU-regime Sharpe 1.283 (tied S1 50/50 baseline 1.309, NS).
  Limitation (K1121 robustness note #1): only 2 assets. TLT (US long bond)
  provides a third, lower-correlation safe-asset leg.

HYPOTHESIS:
  H1: Cross-asset alt-data allocation (defensive tilt toward TLT+GLD during
      stress regimes) beats Static 40/30/30 and Rolling Risk-Parity baselines.
  H2: Alt-data regime edge is larger in 3-asset than in 2-asset universe,
      because stress days can rotate into bonds (not just gold).
  H3: Smooth-tilt (continuous z-score weighting) > step-function regime (S1-S3).

DESIGN:
  Universe: SPY (equity) + GLD (gold) + TLT (US long bond)
  Period: 2018-01-01 to 2026-04-13, daily
  Lags (per error_log 2026-04-13 FRED publication delay):
    - NFCI: shift(5) trading days  (weekly, published Wed following Fri obs)
    - EPU:  shift(2) trading days  (daily, published next day)
    - VIX:  shift(1)               (intraday, 1-day conservative)
    - Vol estimators: shift(1)

  Baselines:
    B0: Static 50/50 SPY/GLD  (K1121/K846 moat)
    B1: Static 40/30/30 SPY/GLD/TLT  (equal-ish with bond leg)
    B2: Rolling Risk Parity SPY/GLD/TLT (inverse-vol, 60d rolling, lag-1)

  Alt-data strategies:
    S1 (NFCI-regime):
      stress flag = NFCI_252d_rank >= 0.80
      normal : wSPY=0.40, wGLD=0.30, wTLT=0.30
      stress : wSPY=0.20, wGLD=0.40, wTLT=0.40
    S2 (EPU-regime):
      stress flag = EPU_252d_rank >= 0.80
      normal : wSPY=0.40, wGLD=0.30, wTLT=0.30
      stress : wSPY=0.20, wGLD=0.50, wTLT=0.30  (EPU is uncertainty -> gold)
    S3 (combined OR):
      stress flag = (NFCI_rank >= 0.80) | (EPU_rank >= 0.80)
      same defensive tilt as S1 but both inputs
    S4 (smooth tilt):
      z_stress = 0.5 * z(NFCI) + 0.5 * z(EPU)  (252d rolling z)
      wSPY = clip(0.40 - 0.10 * z_stress, 0.15, 0.60)
      remainder split: wGLD : wTLT = (1 + 0.5*z_stress) : (1 - 0.5*z_stress)
                       (when stress: more GLD; when calm: more TLT)
      continuous allocation, no step function.

  TX cost: 5 bps per weight change, applied turnover * cost

Evaluation:
  - Sharpe, Sortino, MDD, Calmar, CAGR (full, IS 2018-2022, OOS 2023+)
  - DM-HLN via stationary bootstrap (Politis-Romano 1994, 1000 reps, block=20)
    on Sharpe difference vs B0, B1, B2
  - Regime-conditional Sharpe: stress days vs calm days
  - Harvey t>3.0 threshold for cross-test (Sharpe ratio SE ~ 1/sqrt(N))

Seed: np.random.seed(42) + rng.default_rng(42) + bootstrap seed=42

References:
  - Baker, Bloom, Davis (2016) QJE - EPU index
  - Brave, Butters (2011) - NFCI
  - Politis, Romano (1994) - stationary bootstrap
  - Harvey, Liu, Zhu (2016) - Sharpe t>3 threshold
  - K1121 (experiments/k1121) - 2-asset baseline
  - K846 - 50/50 SPY/GLD moat
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

TX_BPS = 5.0  # 5 bps per unit of turnover (sum|dw|) per rebalance

RESULTS = {
    "experiment_id": "K1123",
    "title": "Cross-asset alt-data allocation (SPY+GLD+TLT) - extension of K1121",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": "yfinance (SPY, GLD, TLT) + FRED (USEPUINDXD, NFCI) cached",
    "extension_of": "K1121 (2-asset SPY+GLD) -> adds TLT bond leg",
    "prior_related": {
        "K1121": "SPY+GLD alt-data regime: S4 EPU Sharpe 1.283 (tied S1 1.309, NS)",
        "K1118": "Cross-asset (GLD/TLT/BTC) forecasting: NULL",
        "K846": "50/50 SPY/GLD moat - triple-validated",
        "K687/K697": "VT = drawdown insurance, not alpha",
    },
    "hypotheses": {
        "H1_beat_baselines": "Alt-data 3-asset Sharpe > max(B0, B1, B2) with p<0.05",
        "H2_cross_asset_edge": "3-asset alt-data edge > K1121 2-asset edge (+0.003)",
        "H3_smooth_vs_step": "S4 smooth-tilt Sharpe > S1/S2/S3 step-function",
        "H4_regime_conditional": "stress-period Sharpe improvement t>2 AND total t>2",
    },
    "publication_lags_applied": {
        "NFCI": "shift(5) - weekly obs Fri published following Wed (error_log 2026-04-13)",
        "EPU": "shift(2) - daily obs X published X+1 (error_log 2026-04-13)",
        "VIX_vol": "shift(1) - rolling-estimator lag",
    },
    "transaction_cost_bps": TX_BPS,
    "seed": SEED,
}


def log(msg):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ----- Data fetching -----

def fetch_assets():
    import yfinance as yf
    log("Fetching SPY + GLD + TLT daily 2018-2026...")
    tickers = yf.download(
        ["SPY", "GLD", "TLT"],
        start="2018-01-01",
        end="2026-04-14",
        progress=False,
        auto_adjust=True,
        group_by="ticker",
    )
    if isinstance(tickers.columns, pd.MultiIndex):
        spy = tickers["SPY"]["Close"].rename("SPY")
        gld = tickers["GLD"]["Close"].rename("GLD")
        tlt = tickers["TLT"]["Close"].rename("TLT")
    else:
        raise RuntimeError("expected multiindex")

    df = pd.concat([spy, gld, tlt], axis=1).dropna(how="any")
    df["r_SPY"] = df["SPY"].pct_change()
    df["r_GLD"] = df["GLD"].pct_change()
    df["r_TLT"] = df["TLT"].pct_change()
    df["logr_SPY"] = np.log(df["SPY"]).diff()
    df["logr_GLD"] = np.log(df["GLD"]).diff()
    df["logr_TLT"] = np.log(df["TLT"]).diff()
    log(f"  daily panel: {len(df)} rows {df.index.min().date()} -> {df.index.max().date()}")
    return df


def fetch_fred_cached():
    """Load from cached CSVs (from k1121 / k1122)."""
    log("Loading cached FRED data...")

    epu_path = DATA_DIR / "fred_USEPUINDXD.csv"
    nfci_path = DATA_DIR / "fred_NFCI.csv"

    if not epu_path.exists() or not nfci_path.exists():
        raise RuntimeError("FRED cache missing")

    epu = pd.read_csv(epu_path, parse_dates=["DATE"]).set_index("DATE")
    epu["USEPUINDXD"] = pd.to_numeric(epu["USEPUINDXD"], errors="coerce")
    epu = epu.dropna()
    epu = epu[(epu.index >= "2018-01-01") & (epu.index <= "2026-04-13")]

    nfci = pd.read_csv(nfci_path, parse_dates=["DATE"]).set_index("DATE")
    nfci["NFCI"] = pd.to_numeric(nfci["NFCI"], errors="coerce")
    nfci = nfci.dropna()
    nfci = nfci[(nfci.index >= "2018-01-01") & (nfci.index <= "2026-04-13")]

    log(f"  EPU: {len(epu)} rows, last={epu.index[-1].date()}")
    log(f"  NFCI: {len(nfci)} rows, last={nfci.index[-1].date()}")
    return epu, nfci


def build_panel(market, epu, nfci):
    df = market.copy()
    df = df.join(epu.rename(columns={"USEPUINDXD": "EPU"}), how="left")
    df = df.join(nfci.rename(columns={"NFCI": "NFCI"}), how="left")
    df["EPU"] = df["EPU"].ffill(limit=5)
    df["NFCI"] = df["NFCI"].ffill(limit=10)
    df = df.dropna(subset=["EPU", "NFCI"])
    log(f"  merged panel: {len(df)} days")
    return df


# ----- Signal helpers -----

def rolling_pct_rank(s, window):
    """Rolling percentile rank of the latest value vs past `window` values."""
    def _rank(x):
        if len(x) < 2:
            return np.nan
        return (x[:-1] < x[-1]).mean()
    return s.rolling(window + 1).apply(_rank, raw=True)


def rolling_z(s, window):
    """Rolling z-score: (x - mean) / std over past `window` values."""
    mu = s.rolling(window).mean()
    sd = s.rolling(window).std()
    return (s - mu) / sd


# ----- Strategies (weights as (wSPY, wGLD, wTLT)) -----

def strategy_B0_5050(df):
    """Static 50/50 SPY/GLD (K1121/K846 baseline, TLT=0)."""
    idx = df.index
    return pd.DataFrame({
        "wSPY": 0.50,
        "wGLD": 0.50,
        "wTLT": 0.00,
    }, index=idx)


def strategy_B1_403030(df):
    """Static 40/30/30 SPY/GLD/TLT."""
    idx = df.index
    return pd.DataFrame({
        "wSPY": 0.40,
        "wGLD": 0.30,
        "wTLT": 0.30,
    }, index=idx)


def strategy_B2_risk_parity(df, window=60):
    """Rolling Risk Parity: inverse-vol weights on SPY/GLD/TLT, 60d rolling.

    Weights based on t-1 info (shift(1)) - no lookahead.
    """
    # Use log returns for vol estimation (symmetric, conventional)
    sig_SPY = df["logr_SPY"].rolling(window).std()
    sig_GLD = df["logr_GLD"].rolling(window).std()
    sig_TLT = df["logr_TLT"].rolling(window).std()

    inv_SPY = 1.0 / sig_SPY
    inv_GLD = 1.0 / sig_GLD
    inv_TLT = 1.0 / sig_TLT
    total = inv_SPY + inv_GLD + inv_TLT

    wSPY = inv_SPY / total
    wGLD = inv_GLD / total
    wTLT = inv_TLT / total

    # Shift(1) for lag - weight at t uses vol estimated up to t-1
    out = pd.DataFrame({
        "wSPY": wSPY.shift(1),
        "wGLD": wGLD.shift(1),
        "wTLT": wTLT.shift(1),
    }, index=df.index)
    return out


def strategy_S1_NFCI_regime(df):
    """NFCI stress-regime defensive tilt. shift(5) for weekly NFCI publication."""
    nfci_rank = rolling_pct_rank(df["NFCI"], 252)
    stress_flag = (nfci_rank >= 0.80).astype(float)
    # Lag 5 trading days for NFCI publication
    stress_flag = stress_flag.shift(5)

    # Valid mask: where rank computable and lag applied
    valid = stress_flag.notna()

    wSPY = pd.Series(np.nan, index=df.index)
    wGLD = pd.Series(np.nan, index=df.index)
    wTLT = pd.Series(np.nan, index=df.index)

    # Normal: 40/30/30
    normal_mask = valid & (stress_flag == 0.0)
    wSPY[normal_mask] = 0.40
    wGLD[normal_mask] = 0.30
    wTLT[normal_mask] = 0.30
    # Stress: 20/40/40
    stress_mask = valid & (stress_flag == 1.0)
    wSPY[stress_mask] = 0.20
    wGLD[stress_mask] = 0.40
    wTLT[stress_mask] = 0.40

    return pd.DataFrame({"wSPY": wSPY, "wGLD": wGLD, "wTLT": wTLT}, index=df.index)


def strategy_S2_EPU_regime(df):
    """EPU stress-regime defensive tilt. shift(2) for EPU publication."""
    epu_rank = rolling_pct_rank(df["EPU"], 252)
    stress_flag = (epu_rank >= 0.80).astype(float)
    stress_flag = stress_flag.shift(2)  # EPU: X obs published X+1

    valid = stress_flag.notna()

    wSPY = pd.Series(np.nan, index=df.index)
    wGLD = pd.Series(np.nan, index=df.index)
    wTLT = pd.Series(np.nan, index=df.index)

    # Normal: 40/30/30
    normal_mask = valid & (stress_flag == 0.0)
    wSPY[normal_mask] = 0.40
    wGLD[normal_mask] = 0.30
    wTLT[normal_mask] = 0.30
    # Stress: 20/50/30 (EPU is uncertainty -> gold heavy)
    stress_mask = valid & (stress_flag == 1.0)
    wSPY[stress_mask] = 0.20
    wGLD[stress_mask] = 0.50
    wTLT[stress_mask] = 0.30

    return pd.DataFrame({"wSPY": wSPY, "wGLD": wGLD, "wTLT": wTLT}, index=df.index)


def strategy_S3_combined(df):
    """Combined NFCI OR EPU stress flag. Uses max of the two lag rules.

    Stress = NFCI_rank>=0.80 (lag5) OR EPU_rank>=0.80 (lag2).
    """
    nfci_rank = rolling_pct_rank(df["NFCI"], 252)
    epu_rank = rolling_pct_rank(df["EPU"], 252)

    nfci_stress = (nfci_rank >= 0.80).astype(float).shift(5)
    epu_stress = (epu_rank >= 0.80).astype(float).shift(2)

    # Combined: requires both to be non-NaN
    valid = nfci_stress.notna() & epu_stress.notna()
    stress_flag = ((nfci_stress == 1.0) | (epu_stress == 1.0)).astype(float)
    stress_flag[~valid] = np.nan

    wSPY = pd.Series(np.nan, index=df.index)
    wGLD = pd.Series(np.nan, index=df.index)
    wTLT = pd.Series(np.nan, index=df.index)

    normal_mask = valid & (stress_flag == 0.0)
    wSPY[normal_mask] = 0.40
    wGLD[normal_mask] = 0.30
    wTLT[normal_mask] = 0.30

    stress_mask = valid & (stress_flag == 1.0)
    wSPY[stress_mask] = 0.20
    wGLD[stress_mask] = 0.45
    wTLT[stress_mask] = 0.35

    return pd.DataFrame({"wSPY": wSPY, "wGLD": wGLD, "wTLT": wTLT}, index=df.index)


def strategy_S4_smooth(df):
    """Smooth tilt: continuous z-score of combined (NFCI, EPU) drives allocation.

    z_stress = 0.5 * z(NFCI, 252d) + 0.5 * z(EPU, 252d)
    wSPY = clip(0.40 - 0.10 * z_stress, 0.15, 0.60)
    wTLT : wGLD split: balance shifts toward GLD under stress
    NFCI uses shift(5), EPU uses shift(2) - applied AFTER z-score computation
    """
    z_nfci = rolling_z(df["NFCI"], 252).shift(5)  # publication-aware lag
    z_epu = rolling_z(df["EPU"], 252).shift(2)

    # Combined stress z-score - both must be valid
    z_stress = 0.5 * z_nfci + 0.5 * z_epu
    valid = z_stress.notna()

    # Clip z for numerical stability
    z_clipped = z_stress.clip(-3, 3)

    wSPY = 0.40 - 0.10 * z_clipped
    wSPY = wSPY.clip(0.15, 0.60)

    # Remainder = 1 - wSPY split between GLD and TLT
    # stress (z>0) -> more GLD; calm (z<0) -> more TLT
    remainder = 1.0 - wSPY
    gld_share = (1.0 + 0.25 * z_clipped).clip(0.3, 1.7) / 2.0  # ~0.5 baseline, ±0.4 tilt
    # Normalize so gld_share+tlt_share = 1 AFTER applying tilt
    gld_share_norm = gld_share.clip(0.15, 0.85)
    tlt_share_norm = 1.0 - gld_share_norm

    wGLD = remainder * gld_share_norm
    wTLT = remainder * tlt_share_norm

    wSPY[~valid] = np.nan
    wGLD[~valid] = np.nan
    wTLT[~valid] = np.nan

    return pd.DataFrame({"wSPY": wSPY, "wGLD": wGLD, "wTLT": wTLT}, index=df.index)


# ----- Backtest -----

def backtest(df, weights_dict, tx_bps=TX_BPS):
    """
    For each strategy, compute daily portfolio returns net of TX cost.

    weights_dict: {strategy_name: DataFrame with wSPY, wGLD, wTLT}
    Return: DataFrame with r_{strategy} and turnover_{strategy}.
    """
    out = pd.DataFrame(index=df.index)
    out["r_SPY"] = df["r_SPY"]
    out["r_GLD"] = df["r_GLD"]
    out["r_TLT"] = df["r_TLT"]

    for name, w in weights_dict.items():
        # Gross return
        r_gross = (w["wSPY"] * df["r_SPY"]
                   + w["wGLD"] * df["r_GLD"]
                   + w["wTLT"] * df["r_TLT"])
        # Turnover: sum of absolute weight changes
        dw = w.diff().abs().sum(axis=1)
        tx_cost = dw * (tx_bps / 1e4)  # bps to decimal
        r_net = r_gross - tx_cost

        out[f"r_{name}"] = r_net
        out[f"rg_{name}"] = r_gross
        out[f"to_{name}"] = dw
        out[f"w_{name}_SPY"] = w["wSPY"]
        out[f"w_{name}_GLD"] = w["wGLD"]
        out[f"w_{name}_TLT"] = w["wTLT"]

    return out


# ----- Metrics -----

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


def cagr(r, ann=252):
    r = r.dropna()
    if len(r) == 0:
        return np.nan
    eq_final = (1 + r).prod()
    years = len(r) / ann
    if years <= 0:
        return np.nan
    return eq_final ** (1 / years) - 1


# ----- Stationary bootstrap for Sharpe difference -----

def stationary_bootstrap(r1, r2, n_boot=1000, block_mean=20, seed=42):
    """
    Stationary bootstrap (Politis-Romano 1994) for Sharpe diff (r1 - r2).
    Returns: obs_diff, p_value (2-sided), CI 95%, t-stat proxy.
    """
    r1 = r1.dropna()
    r2 = r2.dropna()
    idx = r1.index.intersection(r2.index)
    r1 = r1.reindex(idx).values
    r2 = r2.reindex(idx).values
    n = len(r1)
    if n < 50:
        return {"obs_diff": np.nan, "p_value": np.nan,
                "ci_low": np.nan, "ci_high": np.nan, "t_stat": np.nan, "n": n}

    obs = sharpe(pd.Series(r1)) - sharpe(pd.Series(r2))

    rng_local = np.random.default_rng(seed)
    p = 1.0 / block_mean
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

    centered = diffs - np.nanmean(diffs)
    p_val = 2 * min(
        np.mean(centered >= abs(obs)),
        np.mean(centered <= -abs(obs))
    )
    ci_low = np.nanpercentile(diffs, 2.5)
    ci_high = np.nanpercentile(diffs, 97.5)

    # t-stat = obs / SE_boot (approximate)
    se_boot = np.nanstd(diffs)
    t_stat = obs / se_boot if se_boot > 0 else np.nan

    return {
        "obs_diff": float(obs),
        "p_value": float(p_val),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "t_stat": float(t_stat),
        "n": int(n),
    }


# ----- Regime-conditional analysis -----

def regime_conditional(bt, df, strategy_names):
    """Compute Sharpe on stress days vs calm days.

    Stress day = NFCI_rank>=0.80 (lag5) OR EPU_rank>=0.80 (lag2) -- same rule as S3.
    """
    nfci_rank = rolling_pct_rank(df["NFCI"], 252).shift(5)
    epu_rank = rolling_pct_rank(df["EPU"], 252).shift(2)
    stress_flag = ((nfci_rank >= 0.80) | (epu_rank >= 0.80)).astype(float)
    stress_flag = stress_flag.reindex(bt.index)
    # valid = at least one of the two ranks is non-NaN
    valid = nfci_rank.reindex(bt.index).notna() | epu_rank.reindex(bt.index).notna()

    stress_days = valid & (stress_flag == 1.0)
    calm_days = valid & (stress_flag == 0.0)

    out = {}
    for s in strategy_names:
        r_stress = bt.loc[stress_days, f"r_{s}"]
        r_calm = bt.loc[calm_days, f"r_{s}"]
        out[s] = {
            "stress_n": int(stress_days.sum()),
            "calm_n": int(calm_days.sum()),
            "stress_sharpe": float(sharpe(r_stress)) if len(r_stress.dropna()) >= 20 else None,
            "calm_sharpe": float(sharpe(r_calm)) if len(r_calm.dropna()) >= 20 else None,
            "stress_mean_ann": float(r_stress.mean() * 252),
            "calm_mean_ann": float(r_calm.mean() * 252),
            "stress_vol_ann": float(r_stress.std() * np.sqrt(252)),
            "calm_vol_ann": float(r_calm.std() * np.sqrt(252)),
        }
    out["_stress_days_count"] = int(stress_days.sum())
    out["_calm_days_count"] = int(calm_days.sum())
    return out


# ----- Main -----

def main():
    log("=== K1123: Cross-asset alt-data allocation (SPY+GLD+TLT) ===")

    # 1. Data
    market = fetch_assets()
    epu, nfci = fetch_fred_cached()
    df = build_panel(market, epu, nfci)
    df.to_parquet(DATA_DIR / "panel.parquet")
    log(f"Saved: {DATA_DIR/'panel.parquet'}")

    # 2. Descriptive stats
    desc = {
        "SPY_mean_ann": float(df["r_SPY"].mean() * 252),
        "SPY_vol_ann": float(df["r_SPY"].std() * np.sqrt(252)),
        "GLD_mean_ann": float(df["r_GLD"].mean() * 252),
        "GLD_vol_ann": float(df["r_GLD"].std() * np.sqrt(252)),
        "TLT_mean_ann": float(df["r_TLT"].mean() * 252),
        "TLT_vol_ann": float(df["r_TLT"].std() * np.sqrt(252)),
        "SPY_GLD_corr": float(df[["r_SPY", "r_GLD"]].corr().iloc[0, 1]),
        "SPY_TLT_corr": float(df[["r_SPY", "r_TLT"]].corr().iloc[0, 1]),
        "GLD_TLT_corr": float(df[["r_GLD", "r_TLT"]].corr().iloc[0, 1]),
        "VIX_not_available_period_ok": True,
    }
    log(f"Desc: SPY {desc['SPY_mean_ann']:.2%}/{desc['SPY_vol_ann']:.2%}, "
        f"TLT {desc['TLT_mean_ann']:.2%}/{desc['TLT_vol_ann']:.2%}, "
        f"SPY-TLT corr={desc['SPY_TLT_corr']:.3f}")

    # 3. Compute strategy weights
    log("--- Computing strategies ---")
    weights = {
        "B0": strategy_B0_5050(df),
        "B1": strategy_B1_403030(df),
        "B2": strategy_B2_risk_parity(df, window=60),
        "S1": strategy_S1_NFCI_regime(df),
        "S2": strategy_S2_EPU_regime(df),
        "S3": strategy_S3_combined(df),
        "S4": strategy_S4_smooth(df),
    }
    # Save weights snapshot for inspection
    weights_snap = pd.concat({k: v for k, v in weights.items()}, axis=1)
    weights_snap.to_parquet(DATA_DIR / "weights.parquet")

    for name, w in weights.items():
        # confirm weights sum to ~1
        ws = (w["wSPY"] + w["wGLD"] + w["wTLT"]).dropna()
        if len(ws) > 0:
            log(f"  {name}: weight sum [{ws.min():.4f}, {ws.max():.4f}] avg_wSPY={w['wSPY'].mean():.3f} "
                f"avg_wGLD={w['wGLD'].mean():.3f} avg_wTLT={w['wTLT'].mean():.3f}")

    # 4. Backtest (net of TX cost)
    log("--- Running backtest (net of TX cost) ---")
    bt = backtest(df, weights, tx_bps=TX_BPS)
    # drop rows where any strategy return is NaN (warm-up period)
    strat_ret_cols = [f"r_{s}" for s in weights.keys()]
    bt = bt.dropna(subset=strat_ret_cols)
    log(f"Backtest window: {bt.index.min().date()} -> {bt.index.max().date()} ({len(bt)} days)")
    bt.to_parquet(DATA_DIR / "backtest.parquet")

    # 5. Full-sample metrics
    log("--- Full-sample metrics (net of TX) ---")
    strategies = list(weights.keys())
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
            "cagr": float(cagr(r)),
            "total_return": float((1 + r).prod() - 1),
            "avg_wSPY": float(bt[f"w_{s}_SPY"].mean()),
            "avg_wGLD": float(bt[f"w_{s}_GLD"].mean()),
            "avg_wTLT": float(bt[f"w_{s}_TLT"].mean()),
            "turnover_per_day": float(bt[f"to_{s}"].mean()),
            "turnover_annual": float(bt[f"to_{s}"].mean() * 252),
            "tx_drag_annual_pct": float(bt[f"to_{s}"].mean() * (TX_BPS / 1e4) * 252 * 100),
        }
        log(f"  {s}: Sharpe={full_metrics[s]['sharpe']:.3f} MDD={full_metrics[s]['max_drawdown']:.3f} "
            f"CAGR={full_metrics[s]['cagr']:.3f} wSPY={full_metrics[s]['avg_wSPY']:.2f} "
            f"wGLD={full_metrics[s]['avg_wGLD']:.2f} wTLT={full_metrics[s]['avg_wTLT']:.2f} "
            f"TO_ann={full_metrics[s]['turnover_annual']:.2f} TX_drag={full_metrics[s]['tx_drag_annual_pct']:.2f}%")

    # 6. IS / OOS split
    log("--- IS/OOS split (IS=<2023, OOS>=2023) ---")
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
                "cagr": float(cagr(r)),
                "n_days": int(mask.sum()),
            }

    # 7. Bootstrap vs baselines (DM-HLN via stationary bootstrap)
    log("--- Stationary bootstrap: alt-data strategies vs baselines ---")
    boot_results = {}
    alt_strategies = ["S1", "S2", "S3", "S4"]
    for s in alt_strategies:
        boot_results[s] = {}
        for b in ["B0", "B1", "B2"]:
            log(f"  bootstrapping {s} vs {b}...")
            res = stationary_bootstrap(bt[f"r_{s}"], bt[f"r_{b}"],
                                        n_boot=1000, block_mean=20, seed=SEED)
            boot_results[s][f"vs_{b}"] = res
            log(f"    {s} vs {b}: diff={res['obs_diff']:.3f} p={res['p_value']:.3f} "
                f"t={res['t_stat']:.2f} CI=[{res['ci_low']:.3f},{res['ci_high']:.3f}]")

    # 8. OOS-specific bootstrap (focus on OOS comparison)
    log("--- OOS bootstrap (2023+) ---")
    bt_oos = bt.loc[oos_mask]
    boot_oos = {}
    for s in alt_strategies:
        boot_oos[s] = {}
        for b in ["B0", "B1", "B2"]:
            res = stationary_bootstrap(bt_oos[f"r_{s}"], bt_oos[f"r_{b}"],
                                        n_boot=1000, block_mean=20, seed=SEED)
            boot_oos[s][f"vs_{b}_OOS"] = res
            log(f"    OOS {s} vs {b}: diff={res['obs_diff']:.3f} p={res['p_value']:.3f} t={res['t_stat']:.2f}")

    # 9. Regime-conditional Sharpe
    log("--- Regime-conditional analysis ---")
    regime_cond = regime_conditional(bt, df, strategies)
    log(f"  stress days: {regime_cond['_stress_days_count']}, calm days: {regime_cond['_calm_days_count']}")
    for s in strategies:
        log(f"  {s}: stress_SR={regime_cond[s]['stress_sharpe']} calm_SR={regime_cond[s]['calm_sharpe']}")

    # 10. Hypothesis tests
    log("--- Hypothesis tests ---")
    baseline_max_sr = max(full_metrics[b]["sharpe"] for b in ["B0", "B1", "B2"])
    best_alt_strat = max(alt_strategies, key=lambda s: full_metrics[s]["sharpe"])
    best_alt_sr = full_metrics[best_alt_strat]["sharpe"]

    # H1: Alt-data beats all three baselines with p<0.05 vs ALL three
    h1_pass_candidates = []
    for s in alt_strategies:
        passes = all(boot_results[s][f"vs_{b}"]["p_value"] < 0.05
                     and boot_results[s][f"vs_{b}"]["obs_diff"] > 0
                     for b in ["B0", "B1", "B2"])
        if passes:
            h1_pass_candidates.append(s)

    # H2: 3-asset edge vs K1121 2-asset edge
    # K1121: best alt over B0 (50/50) was S5 NFCI diff +0.003 (tied)
    # 3-asset edge = best_alt_sr - B0_sr
    edge_3asset_vs_B0 = best_alt_sr - full_metrics["B0"]["sharpe"]
    k1121_edge = 0.003  # K1121 S5 vs S1 (50/50)
    h2_pass = edge_3asset_vs_B0 > k1121_edge

    # H3: S4 smooth > max(S1, S2, S3)
    step_strategies_max_sr = max(full_metrics[s]["sharpe"] for s in ["S1", "S2", "S3"])
    h3_pass = full_metrics["S4"]["sharpe"] > step_strategies_max_sr

    # H4: stress-period t>2 AND total-period t>2 (Harvey-like criterion)
    h4_candidates = {}
    for s in alt_strategies:
        # Total-period: use bootstrap t-stat vs B2 (most-comparable baseline = rolling RP)
        total_t = boot_results[s]["vs_B2"]["t_stat"]
        stress_sr = regime_cond[s]["stress_sharpe"]
        b2_stress_sr = regime_cond["B2"]["stress_sharpe"]
        # Rough stress-improvement t-stat: use stress Sharpe diff / Sharpe SE
        # Sharpe SE ~ sqrt(1/N_stress)
        n_stress = regime_cond[s]["stress_n"]
        if n_stress > 0 and stress_sr is not None and b2_stress_sr is not None:
            stress_diff = stress_sr - b2_stress_sr
            stress_t = stress_diff / np.sqrt(1 / n_stress)  # approximate
        else:
            stress_t = None
        h4_candidates[s] = {
            "total_t_vs_B2": total_t,
            "stress_t_vs_B2": stress_t,
            "n_stress": n_stress,
            "total_pass": abs(total_t) > 2.0 if total_t is not None else False,
            "stress_pass": abs(stress_t) > 2.0 if stress_t is not None else False,
        }
    h4_pass_candidates = [s for s in alt_strategies
                          if h4_candidates[s]["total_pass"] and h4_candidates[s]["stress_pass"]
                          and boot_results[s]["vs_B2"]["obs_diff"] > 0]

    h_tests = {
        "H1_beat_baselines": {
            "best_alt": best_alt_strat,
            "best_alt_sharpe": best_alt_sr,
            "baseline_max_sharpe": baseline_max_sr,
            "pass_candidates": h1_pass_candidates,
            "PASS": len(h1_pass_candidates) > 0,
        },
        "H2_cross_asset_edge": {
            "edge_3asset_vs_B0": edge_3asset_vs_B0,
            "k1121_edge": k1121_edge,
            "diff": edge_3asset_vs_B0 - k1121_edge,
            "PASS": h2_pass,
        },
        "H3_smooth_vs_step": {
            "S4_sharpe": full_metrics["S4"]["sharpe"],
            "max_step_sharpe": step_strategies_max_sr,
            "diff": full_metrics["S4"]["sharpe"] - step_strategies_max_sr,
            "PASS": h3_pass,
        },
        "H4_regime_conditional": {
            "candidates": h4_candidates,
            "pass_candidates": h4_pass_candidates,
            "PASS": len(h4_pass_candidates) > 0,
        },
    }

    # 11. Verdict synthesis
    n_pass = sum(1 for h in ["H1_beat_baselines", "H2_cross_asset_edge",
                              "H3_smooth_vs_step", "H4_regime_conditional"]
                 if h_tests[h]["PASS"])
    if n_pass >= 3:
        verdict = "PASS"
    elif n_pass >= 1:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    RESULTS["verdict"] = verdict
    RESULTS["n_hypotheses_passed"] = n_pass

    # 12. Assemble and save
    RESULTS["n_days"] = int(len(bt))
    RESULTS["period_actual"] = [str(bt.index.min().date()), str(bt.index.max().date())]
    RESULTS["descriptive"] = desc
    RESULTS["full_sample_metrics"] = full_metrics
    RESULTS["is_oos_metrics"] = is_oos_metrics
    RESULTS["bootstrap_vs_baselines_full"] = boot_results
    RESULTS["bootstrap_vs_baselines_OOS"] = boot_oos
    RESULTS["regime_conditional"] = regime_cond
    RESULTS["hypothesis_tests"] = h_tests

    # Headline table
    headline = []
    for s in strategies:
        headline.append({
            "strategy": s,
            "sharpe_full": round(full_metrics[s]["sharpe"], 3),
            "sharpe_IS": round(is_oos_metrics["IS"][s]["sharpe"], 3),
            "sharpe_OOS": round(is_oos_metrics["OOS"][s]["sharpe"], 3),
            "mdd": round(full_metrics[s]["max_drawdown"], 3),
            "cagr": round(full_metrics[s]["cagr"], 3),
            "calmar": round(full_metrics[s]["calmar"], 3),
            "sortino": round(full_metrics[s]["sortino"], 3),
            "avg_wSPY": round(full_metrics[s]["avg_wSPY"], 3),
            "avg_wGLD": round(full_metrics[s]["avg_wGLD"], 3),
            "avg_wTLT": round(full_metrics[s]["avg_wTLT"], 3),
            "turnover_annual": round(full_metrics[s]["turnover_annual"], 2),
            "tx_drag_pct": round(full_metrics[s]["tx_drag_annual_pct"], 3),
        })
    RESULTS["headline_table"] = headline

    RESULTS["finished_utc"] = datetime.utcnow().isoformat() + "Z"

    out_path = OUT_DIR / "k1123_results.json"
    with open(out_path, "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"Saved: {out_path}")

    # 13. Print summary
    log("\n=== HEADLINE TABLE ===")
    hdr = (f"{'strat':<4} {'SR_full':>7} {'SR_IS':>7} {'SR_OOS':>7} {'MDD':>7} "
           f"{'CAGR':>7} {'Calmar':>7} {'avg_wSPY':>9} {'avg_wTLT':>9} {'TO':>6} {'TX_drag':>7}")
    log(hdr)
    for h in headline:
        log(f"{h['strategy']:<4} {h['sharpe_full']:>7.3f} {h['sharpe_IS']:>7.3f} "
            f"{h['sharpe_OOS']:>7.3f} {h['mdd']:>7.3f} {h['cagr']:>7.3f} "
            f"{h['calmar']:>7.3f} {h['avg_wSPY']:>9.3f} {h['avg_wTLT']:>9.3f} "
            f"{h['turnover_annual']:>6.2f} {h['tx_drag_pct']:>7.3f}")

    log("\n=== HYPOTHESIS TESTS ===")
    for hname, hres in h_tests.items():
        log(f"{hname}: {'PASS' if hres['PASS'] else 'FAIL'}")
    log(f"\n=== VERDICT: {verdict} (H pass: {n_pass}/4) ===")


if __name__ == "__main__":
    main()
