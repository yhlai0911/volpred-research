#!/usr/bin/env python3
"""
K1193: Paper 3 Split-Sample Robustness Check
=============================================
Reproduce Paper 3 body_v2.tex Section 3.3 split-sample test.

Design:
  - Estimate GJR-GARCH gamma_i from first half: 2007-01-01 to 2016-12-31
  - Estimate TSMOM orthogonalized loading (beta_TSMOM_orth) from second half: 2017-01-01 to 2026-03-20
  - Pearson/Spearman correlation across 22 assets
  - Bootstrap 95% CI (5000 replications, seed=42)

Paper claim: r=0.487 (p=0.021), CI [0.114, 0.737], rho=0.461 (p=0.031)

Methodology (verified against K55 vt_tsmom_final_n22.json):
  - GJR-GARCH: arch library, returns in percent (×100)
  - VT: daily 12/VIX strategy with shift(1) lag (confirmed to match K55 SPY R2=0.802)
  - MKT factor: asset-specific B&H excess return (verified: gives R2≈K55 for all 6 test assets)
  - TSMOM: sign(252d cum SPY return, lagged 1d) × SPY daily return
  - Orthogonalize TSMOM w.r.t. MKT; Newey-West HAC (9 lags)

References:
  - K55: vt_tsmom_final_n22.json (full-sample baseline, r=0.564)
  - body_v2.tex Section 3.3 (split-sample r=0.487)
  - nosource_rescan_report.md (N15-N17 still no source → this experiment)
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats as sp_stats
from datetime import datetime, timezone
from pathlib import Path
from numpy.linalg import lstsq

warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────
TICKERS = [
    'SPY', 'QQQ', 'IWM', 'XLF', 'XLE', 'DIA',
    'EEM', 'EFA', 'FXI', 'EWZ', 'GLD', 'TLT',
    'USO', 'HYG', 'LQD', 'EWJ', 'EWG', 'EWU',
    'EWA', 'INDA', 'VNQ', 'SLV'
]
ASSET_CLASS_MAP = {
    'SPY': 'equity', 'QQQ': 'equity', 'IWM': 'equity',
    'XLF': 'equity', 'XLE': 'equity', 'DIA': 'equity',
    'EEM': 'equity', 'EFA': 'equity', 'FXI': 'equity',
    'EWZ': 'equity', 'EWJ': 'equity', 'EWG': 'equity',
    'EWU': 'equity', 'EWA': 'equity', 'INDA': 'equity',
    'GLD': 'non_equity', 'TLT': 'non_equity',
    'USO': 'non_equity', 'HYG': 'non_equity', 'LQD': 'non_equity',
    'VNQ': 'non_equity', 'SLV': 'non_equity',
}

FULL_START = '2007-01-01'
FULL_END = '2026-03-20'

HALF1_START = '2007-01-01'
HALF1_END = '2016-12-31'
HALF2_START = '2017-01-01'
HALF2_END = '2026-03-20'

VIX_THRESHOLD = 12.0
TSMOM_LOOKBACK = 252
NW_LAGS = 9
BOOTSTRAP_N = 5000
BOOTSTRAP_SEED = 42


# ── Data Download ──────────────────────────────────────────────
def download_data() -> pd.DataFrame:
    """Download all data in one batch. Returns daily Close prices."""
    print("[Step 1] Downloading price data...")
    all_tickers = TICKERS + ['^VIX', '^IRX']
    raw = yf.download(all_tickers, start=FULL_START, end=FULL_END,
                      auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw['Close']
    else:
        prices = raw

    prices.columns = [str(c).strip() for c in prices.columns]
    prices = prices.ffill()

    print(f"  Downloaded: {prices.shape}, {prices.index[0].date()} to {prices.index[-1].date()}")
    return prices


# ── VT + BH Daily Excess Returns ─────────────────────────────
def vt_and_bh_excess(price: pd.Series, vix: pd.Series, irx: pd.Series,
                     thr: float = 12.0):
    """
    Daily 12/VIX VT strategy and B&H excess returns.
    VT weight = (thr / VIX_{t-1}).clip(0,1) -- shift(1) enforced.
    """
    ret = price.pct_change().dropna()
    c = ret.index.intersection(vix.index).intersection(irx.index)
    ret = ret.loc[c]
    v = vix.loc[c]
    r = irx.loc[c]
    rf = r / 100 / 252

    wd = (thr / v).clip(0, 1).shift(1)  # ★ CRITICAL: shift(1)
    valid = wd.dropna().index
    ret = ret.loc[valid]
    wd = wd.loc[valid]
    rf = rf.reindex(valid, method='ffill').fillna(0)

    vt_exc = wd * ret + (1 - wd) * rf - rf
    bh_exc = ret - rf
    return vt_exc, bh_exc


# ── TSMOM Factor (SPY-based) ──────────────────────────────────
def spy_tsmom_factor(spy_price: pd.Series, lb: int = 252) -> pd.Series:
    """
    TSMOM = sign(rolling_lb_cum_return, lagged 1) × daily SPY return.
    """
    r = spy_price.pct_change().dropna()
    cum = r.rolling(lb).sum()
    sig = np.sign(cum.shift(1))
    return (sig * r).dropna()


# ── GJR-GARCH Gamma (arch library) ──────────────────────────
def estimate_gjr_gamma(returns_pct: pd.Series) -> float:
    """
    arch GJR-GARCH(1,1) gamma. Input: returns × 100.
    """
    try:
        model = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1,
                           dist='normal', mean='Constant', rescale=False)
        result = model.fit(disp='off', show_warning=False)
        gamma = result.params.get('gamma[1]', np.nan)
        return float(gamma)
    except Exception as e:
        return np.nan


# ── Newey-West Regression (manual, nlags fixed at 9) ─────────
def nw_reg(y: np.ndarray, X: np.ndarray, nlags: int = 9) -> dict:
    """
    OLS with Newey-West HAC at fixed nlags=9 (matching K55).
    """
    n, k = X.shape
    beta = lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta

    S = np.zeros((k, k))
    xu = X * resid[:, None]
    S += xu.T @ xu / n
    for j in range(1, nlags + 1):
        w = 1 - j / (nlags + 1)
        G = xu[j:].T @ (X[:n - j] * resid[:n - j, None]) / n
        S += w * (G + G.T)

    V = np.linalg.inv(X.T @ X / n) @ S @ np.linalg.inv(X.T @ X / n) / n
    se = np.sqrt(np.diag(V))
    t_stats = beta / np.where(se > 0, se, 1e-10)
    p_vals = 2 * (1 - sp_stats.t.cdf(np.abs(t_stats), df=n - k))

    return {'beta': beta, 't_stats': t_stats, 'p_vals': p_vals, 'n': n}


# ── Beta TSMOM Orth for a Period ──────────────────────────────
def beta_tsmom_orth_for_period(ticker: str, prices: pd.DataFrame,
                                vix: pd.Series, irx: pd.Series,
                                spy_price: pd.Series,
                                period_start: str, period_end: str) -> float:
    """
    Compute beta_TSMOM_orth for asset `ticker` in [period_start, period_end].

    Factor model:
      VT_excess_i = alpha + beta_mkt * BH_excess_i + beta_TSMOM_orth * TSMOM_orth + eps
    where TSMOM_orth = residual of TSMOM regressed on BH_excess_i.

    MKT = asset-specific B&H excess (verified to match K55 R2 values).
    TSMOM = sign(252d SPY cumret, lagged) × SPY daily return.
    """
    if ticker not in prices.columns:
        return np.nan

    price = prices[ticker].dropna()

    # VT and BH excess (full range for data continuity)
    vt_exc, bh_exc = vt_and_bh_excess(price, vix, irx, VIX_THRESHOLD)

    # TSMOM factor (need full range for 252d lookback warmup)
    tsmom = spy_tsmom_factor(spy_price, TSMOM_LOOKBACK)

    # Restrict to period
    vt_h = vt_exc.loc[period_start:period_end]
    bh_h = bh_exc.reindex(vt_h.index)
    ts_h = tsmom.reindex(vt_h.index)

    # Align
    c = vt_h.dropna().index.intersection(bh_h.dropna().index).intersection(ts_h.dropna().index)
    if len(c) < 100:
        return np.nan

    y = vt_h.loc[c].values
    m = bh_h.loc[c].values
    t = ts_h.loc[c].values
    n = len(y)

    # Orthogonalize TSMOM w.r.t. asset BH excess (MKT)
    Xo = np.column_stack([np.ones(n), m])
    b_orth = lstsq(Xo, t, rcond=None)[0]
    t_orth = t - Xo @ b_orth

    # Model: y ~ alpha + beta_mkt * m + beta_TSMOM_orth * t_orth
    X3 = np.column_stack([np.ones(n), m, t_orth])
    reg = nw_reg(y, X3, NW_LAGS)

    return float(reg['beta'][2])


# ── Gamma for Period ──────────────────────────────────────────
def gamma_for_period(ticker: str, prices: pd.DataFrame,
                     period_start: str, period_end: str) -> float:
    """Estimate GJR-GARCH gamma for ticker in period."""
    if ticker not in prices.columns:
        return np.nan
    price = prices[ticker].dropna().loc[period_start:period_end]
    if len(price) < 200:
        return np.nan
    ret_pct = price.pct_change().dropna() * 100
    return estimate_gjr_gamma(ret_pct)


# ── Bootstrap CI ──────────────────────────────────────────────
def bootstrap_pearson_ci(x: np.ndarray, y: np.ndarray,
                          n_boot: int = 5000, seed: int = 42) -> tuple:
    """Percentile bootstrap 95% CI for Pearson r."""
    rng = np.random.default_rng(seed)
    n = len(x)
    boot_r = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        r, _ = sp_stats.pearsonr(x[idx], y[idx])
        boot_r[i] = r
    return float(np.percentile(boot_r, 2.5)), float(np.percentile(boot_r, 97.5))


# ── Main ──────────────────────────────────────────────────────
def main():
    print("=" * 72)
    print("K1193: Paper 3 Split-Sample Robustness Check")
    print(f"  gamma: {HALF1_START}–{HALF1_END}")
    print(f"  TSMOM: {HALF2_START}–{HALF2_END}")
    print("=" * 72)

    # 1. Download data
    prices = download_data()

    vix = prices['^VIX'].dropna() if '^VIX' in prices.columns else None
    irx = prices['^IRX'].dropna() if '^IRX' in prices.columns else None
    spy_price = prices['SPY'].dropna() if 'SPY' in prices.columns else None

    if vix is None:
        raise ValueError("VIX not found")
    if irx is None:
        print("  WARNING: IRX not found, using 0 RF")
        irx = pd.Series(0.0, index=vix.index)
    if spy_price is None:
        raise ValueError("SPY not found")

    # 2. First half: GJR-GARCH gamma
    print(f"\n[Step 2] First half ({HALF1_START}–{HALF1_END}): GJR-GARCH gamma_i")
    gamma_dict = {}
    for ticker in TICKERS:
        gamma = gamma_for_period(ticker, prices, HALF1_START, HALF1_END)
        n_h1 = len(prices[ticker].dropna().loc[HALF1_START:HALF1_END]) if ticker in prices.columns else 0
        g_str = f'{gamma:.4f}' if not np.isnan(gamma) else 'NaN'
        print(f"  {ticker:6s}: n={n_h1:4d}, gamma={g_str}")
        gamma_dict[ticker] = gamma

    # 3. Second half: TSMOM_orth loading
    print(f"\n[Step 3] Second half ({HALF2_START}–{HALF2_END}): TSMOM_orth loading")
    tsmom_dict = {}
    for ticker in TICKERS:
        beta = beta_tsmom_orth_for_period(
            ticker, prices, vix, irx, spy_price, HALF2_START, HALF2_END
        )
        b_str = f'{beta:.4f}' if not np.isnan(beta) else 'NaN'
        print(f"  {ticker:6s}: beta_TSMOM_orth={b_str}")
        tsmom_dict[ticker] = beta

    # 4. Cross-section
    print("\n[Step 4] Cross-sectional correlation (gamma_H1 vs beta_TSMOM_H2)")
    cs = []
    for ticker in TICKERS:
        g = gamma_dict.get(ticker, np.nan)
        b = tsmom_dict.get(ticker, np.nan)
        if np.isnan(g) or np.isnan(b):
            continue
        cs.append({
            'ticker': ticker,
            'asset_class': ASSET_CLASS_MAP.get(ticker, 'unknown'),
            'gamma_half1': float(g),
            'beta_tsmom_orth_half2': float(b),
        })

    n_cs = len(cs)
    print(f"  Valid: {n_cs} assets")

    if n_cs < 5:
        raise ValueError(f"Too few: {n_cs}")

    gammas = np.array([d['gamma_half1'] for d in cs])
    betas = np.array([d['beta_tsmom_orth_half2'] for d in cs])

    pearson_r, pearson_p = sp_stats.pearsonr(gammas, betas)
    spearman_rho, spearman_p = sp_stats.spearmanr(gammas, betas)

    print(f"  Bootstrap CI ({BOOTSTRAP_N} reps, seed={BOOTSTRAP_SEED})...")
    ci_lo, ci_hi = bootstrap_pearson_ci(gammas, betas, BOOTSTRAP_N, BOOTSTRAP_SEED)

    print(f"\n  {'═'*52}")
    print(f"  RESULTS (N={n_cs})")
    print(f"  {'═'*52}")
    print(f"  Pearson r   : {pearson_r:.3f}   (paper: 0.487)")
    print(f"  p-value     : {pearson_p:.3f}   (paper: 0.021)")
    print(f"  Spearman ρ  : {spearman_rho:.3f}   (paper: 0.461)")
    print(f"  Spearman p  : {spearman_p:.3f}   (paper: 0.031)")
    print(f"  95% CI      : [{ci_lo:.3f}, {ci_hi:.3f}]  (paper: [0.114, 0.737])")

    r_match = abs(pearson_r - 0.487) <= 0.05
    p_match = abs(pearson_p - 0.021) <= 0.015
    ci_match = abs(ci_lo - 0.114) <= 0.05 and abs(ci_hi - 0.737) <= 0.05
    rho_match = abs(spearman_rho - 0.461) <= 0.05
    n_matched = sum([r_match, p_match, ci_match, rho_match])
    match_status = "MATCHED" if n_matched == 4 else ("PARTIAL_MATCH" if n_matched >= 2 else "DIVERGED")

    print(f"\n  r match(±0.05) : {'YES' if r_match else 'NO'} ({abs(pearson_r-0.487):.3f})")
    print(f"  p match(±0.015): {'YES' if p_match else 'NO'} ({abs(pearson_p-0.021):.3f})")
    print(f"  CI match(±0.05): {'YES' if ci_match else 'NO'}")
    print(f"  ρ match(±0.05) : {'YES' if rho_match else 'NO'} ({abs(spearman_rho-0.461):.3f})")
    print(f"\n  Status: {match_status} ({n_matched}/4)")

    # Save
    results = {
        'experiment_id': 'K1193',
        'title': 'Paper 3 Split-Sample (gamma 2007-2016 vs TSMOM_orth 2017-2026)',
        'attribution': '[提出: nosource_rescan, 執行: worktree agent-af7c5b3e]',
        'methodology': {
            'gamma': 'arch GJR-GARCH(1,1) on returns×100, first half 2007-2016',
            'beta_tsmom_orth': 'daily 12/VIX VT ~ BH_excess + TSMOM_orth (NW HAC lag=9), second half 2017-2026',
            'mkt_factor': 'asset-specific B&H excess return (verified vs K55 R2 values)',
            'tsmom_factor': 'sign(252d SPY cum return lagged) × SPY daily return',
        },
        'paper_claim': {
            'pearson_r': 0.487, 'pearson_p': 0.021,
            'spearman_rho': 0.461, 'spearman_p': 0.031,
            'ci_95_lo': 0.114, 'ci_95_hi': 0.737,
            'source': 'body_v2.tex Section 3.3 + Table tab:cross_section Panel B',
        },
        'config': {
            'tickers': TICKERS,
            'half1': f'{HALF1_START} to {HALF1_END}',
            'half2': f'{HALF2_START} to {HALF2_END}',
            'vix_threshold': VIX_THRESHOLD,
            'tsmom_lookback': TSMOM_LOOKBACK,
            'nw_lags': NW_LAGS,
            'bootstrap_n': BOOTSTRAP_N,
            'bootstrap_seed': BOOTSTRAP_SEED,
        },
        'cross_sectional_data': cs,
        'results': {
            'n_assets': n_cs,
            'pearson_r': round(float(pearson_r), 4),
            'pearson_p': round(float(pearson_p), 4),
            'spearman_rho': round(float(spearman_rho), 4),
            'spearman_p': round(float(spearman_p), 4),
            'ci_lo': round(float(ci_lo), 4),
            'ci_hi': round(float(ci_hi), 4),
        },
        'match_assessment': {
            'r_match': bool(r_match),
            'p_match': bool(p_match),
            'ci_match': bool(ci_match),
            'rho_match': bool(rho_match),
            'n_matched': n_matched,
            'status': match_status,
        },
        'gammas_h1': {d['ticker']: round(d['gamma_half1'], 6) for d in cs},
        'betas_h2': {d['ticker']: round(d['beta_tsmom_orth_half2'], 6) for d in cs},
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(__file__).parent / 'k1193_results.json'
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved: {out_path}")

    return results


if __name__ == '__main__':
    results = main()
