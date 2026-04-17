#!/usr/bin/env python3
"""
K1148_d3: PASS vs FAIL stock characteristics (9 vs 20) for Paper 2 Option 3
==========================================================================
[提出: Claude (Paper 2 §5 Option 3 heterogeneity subsection), 執行: Claude]

Motivation:
  K1148_d1 found: only 9/29 TW stocks pass OOS DM ≤ -2 for binary EAV.
  Paper 2 Option 3 asks: can we characterize the 9 PASS stocks vs the 20
  FAIL stocks by firm-level features (sector, size, earnings frequency,
  earnings surprise magnitude, pre-event vol, GJR params)?
  If YES → Paper 2 §5 can add a "EAV effect is firm-heterogeneous, not
  universal" subsection, which is a STRONGER empirical contribution than
  an unqualified universal-magnitude claim.
  If NO (all features NS) → recommend Option 1 (IS-only) or Option 2
  (OOS heterogeneity without characterization).

Design (N=29 is tiny — BH + effect-size gating is MANDATORY):
  1. Read K1148_d1 per_stock_dm array → split PASS (DM≤-2) / FAIL (DM>-2)
  2. For each ticker, extract features:
     (a) Size: yfinance marketCap snapshot + IS avg daily $volume
     (b) Sector: yfinance info['sector'] / info['industry']
     (c) Earnings: IS freq, avg |surprise%|, |surprise mean| / |surprise mean_abs|
     (d) Vol: IS annualized vol, vol-of-vol, n_events
     (e) GJR (per-stock from K1148_d1 IS fit): omega, alpha, gamma, beta, persistence
     (f) Return: IS annualized return, IS max drawdown
  3. Per-feature tests: Welch t-test + Mann-Whitney U + Cohen's d + BH adj
  4. Plot: boxplot per-feature, bar of |d| with BH color coding
  5. Verdict: Option 3 VIABLE iff any feature has (BH adj p < 0.1) AND (|d|>0.5)

WARNING for reviewers:
  - N=29 is underpowered. Any "significance" here is exploratory, not
    confirmatory. BH adjusts the 10-15 feature family.
  - marketCap snapshot uses CURRENT yfinance info (as of run date) — we
    cannot recover historical market cap cheaply. Used as a proxy for
    2020-era ranking; we additionally compute IS avg daily trading value
    (2015-2019) which IS historically clean and is the primary size metric.
  - Sector is time-invariant for TW listed stocks (no reassignment during
    data window) so yfinance snapshot is acceptable.

References:
  - K1148_d1 (binary EAV OOS panel DM; 29 TW stocks; 9 PASS / 20 FAIL)
  - K1148 (continuous surprise EAV)
  - Benjamini & Hochberg (1995) JRSS-B
  - Cohen (1988) Statistical power analysis

Random seed: 42
Author: VolPred Research System
Date: 2026-04-17
"""
import os
import sys
import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

# -------------------------- config --------------------------
GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)
RNG = np.random.default_rng(GLOBAL_SEED)

START_TIME = time.time()
EXPERIMENT_ID = 'K1148_d3'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
K1148_D1_RESULTS = PROJECT_ROOT / 'experiments' / 'k1148_d1' / 'k1148_d1_results.json'
K1148_CACHE_DIR = PROJECT_ROOT / 'experiments' / 'k1148' / 'data'
EARNINGS_SURPRISE_JSON = K1148_CACHE_DIR / 'earnings_dates_surprise.json'
DATA_DIR = SCRIPT_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)
SECTOR_CACHE = DATA_DIR / 'sector_info_cache.json'
RESULTS_PATH = SCRIPT_DIR / 'k1148_d3_results.json'

OOS_DM_THRESHOLD = -2.0
IS_START = pd.Timestamp('2015-01-01')  # size metric window (last 5 IS years)
IS_END   = pd.Timestamp('2019-12-31')  # end of IS (before OOS 2020-)
IS_FULL_START = pd.Timestamp('2010-01-01')  # full IS window for vol / earnings freq

# --------------------- helpers --------------------------------
def cohens_d(a, b):
    """Welch-style Cohen's d (pooled SD)."""
    a = np.asarray([x for x in a if np.isfinite(x)], dtype=float)
    b = np.asarray([x for x in b if np.isfinite(x)], dtype=float)
    if len(a) < 2 or len(b) < 2:
        return np.nan
    pooled_sd = np.sqrt(((len(a) - 1) * np.var(a, ddof=1)
                          + (len(b) - 1) * np.var(b, ddof=1))
                         / (len(a) + len(b) - 2))
    if pooled_sd <= 0:
        return 0.0
    return float((np.mean(a) - np.mean(b)) / pooled_sd)


def bh_adjust(pvals):
    """Benjamini & Hochberg (1995) step-up adjustment.
    Input: list of p-values (may contain NaN). Output: adjusted p in same order.
    """
    p = np.asarray(pvals, dtype=float)
    n = np.sum(np.isfinite(p))
    if n == 0:
        return p
    # Rank only finite
    fin_idx = np.where(np.isfinite(p))[0]
    fin_p = p[fin_idx]
    order = np.argsort(fin_p)
    ranked = fin_p[order]
    adj = ranked * n / (np.arange(1, n + 1))
    # Step-up: adj[i] = min(adj[i:])
    adj_mono = np.minimum.accumulate(adj[::-1])[::-1]
    adj_mono = np.minimum(adj_mono, 1.0)
    # Restore order
    out = np.full_like(p, np.nan, dtype=float)
    tmp = np.empty_like(adj_mono)
    tmp[order] = adj_mono
    out[fin_idx] = tmp
    return out


def compute_max_drawdown(prices):
    """MDD from a price series (positive number)."""
    if len(prices) < 2:
        return np.nan
    cummax = np.maximum.accumulate(prices)
    dd = (prices - cummax) / cummax
    return float(dd.min())


def rank_biserial(a, b, u_stat):
    """rank-biserial = 1 - 2U/(n1*n2) (Mann-Whitney effect size).
    Sign follows the Cohen's d convention (positive if a > b)."""
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return np.nan
    return float(1.0 - 2.0 * u_stat / (n1 * n2))


# --------------------- data loading ---------------------------
def load_k1148_d1():
    """Load per-stock DM + per-stock GJR params from K1148_d1 results."""
    with open(K1148_D1_RESULTS) as f:
        d = json.load(f)
    per_stock_dm = d['oos_dm']['per_stock_dm']
    is_tickers = d['is_fit']['per_stock_tickers']
    is_params = d['is_fit']['per_stock_params']
    # Map ticker → GJR params [theta0, omega_g, alpha, gamma_p, beta_p]
    gjr_map = {tk: params for tk, params in zip(is_tickers, is_params)}
    return per_stock_dm, gjr_map


def load_price(ticker):
    """Load cached price from K1148 data dir."""
    path = K1148_CACHE_DIR / f"{ticker.replace('^', 'IDX_')}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def load_sector_info():
    """Load yfinance info (sector / industry / marketCap) with disk cache.
    Graceful fallback if yfinance is slow or unavailable."""
    if SECTOR_CACHE.exists():
        with open(SECTOR_CACHE) as f:
            return json.load(f)
    # Fetch fresh
    print('[sector] Fetching sector / marketCap from yfinance ...')
    try:
        import yfinance as yf
    except ImportError:
        print('[sector] yfinance not available; returning empty cache')
        return {}
    cache = {}
    # We'll request for every ticker in K1148_D1
    with open(K1148_D1_RESULTS) as f:
        d = json.load(f)
    tks = d['is_fit']['per_stock_tickers']
    for tk in tks:
        try:
            info = yf.Ticker(tk).info or {}
            cache[tk] = {
                'sector': info.get('sector'),
                'industry': info.get('industry'),
                'marketCap': info.get('marketCap'),
                'shortName': info.get('shortName') or info.get('longName'),
                'currency': info.get('currency'),
            }
            print(f'  {tk}: sector={cache[tk]["sector"]}, cap={cache[tk]["marketCap"]}')
        except Exception as e:
            print(f'  {tk}: FAIL — {e}')
            cache[tk] = {'sector': None, 'industry': None,
                          'marketCap': None, 'shortName': None}
    with open(SECTOR_CACHE, 'w') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False, default=str)
    return cache


def load_earnings_surprise():
    """Load K1148 earnings surprise cache (yfinance-based)."""
    if not EARNINGS_SURPRISE_JSON.exists():
        return {}
    with open(EARNINGS_SURPRISE_JSON) as f:
        return json.load(f)


# --------------------- feature extraction ---------------------
def compute_features(ticker, gjr_params, sector_info, earnings_surprise):
    """Return dict of features for one ticker.
    Uses IS window 2010-2019 (full) + 2015-2019 (recent size) to avoid lookahead.
    """
    feats = {'ticker': ticker}
    # Sector / size (snapshot; sector is time-invariant so snapshot OK)
    sinfo = sector_info.get(ticker, {})
    feats['sector'] = sinfo.get('sector')
    feats['industry'] = sinfo.get('industry')
    feats['market_cap_snapshot'] = sinfo.get('marketCap')  # may be stale — flagged

    # Price & return (IS = 2010-2019)
    raw = load_price(ticker)
    if raw is None:
        for k in ['avg_dollar_vol_is', 'is_annualized_vol',
                   'is_annualized_return', 'vol_of_vol',
                   'max_drawdown_is', 'n_trading_days_is']:
            feats[k] = np.nan
        feats.update({'gjr_omega': np.nan, 'gjr_alpha': np.nan,
                       'gjr_gamma': np.nan, 'gjr_beta': np.nan,
                       'gjr_persistence': np.nan, 'gjr_theta0': np.nan})
        feats['earnings_freq_per_year_is'] = np.nan
        feats['avg_abs_surprise_pct_is'] = np.nan
        feats['mean_surprise_pct_is'] = np.nan
        feats['surprise_symmetry_ratio'] = np.nan
        feats['n_surprise_events_is'] = 0
        return feats

    prices = raw['Close'].copy().dropna()
    is_prices = prices[(prices.index >= IS_FULL_START) & (prices.index <= IS_END)]
    recent_is_prices = prices[(prices.index >= IS_START) & (prices.index <= IS_END)]
    log_ret_is = np.log(is_prices / is_prices.shift(1)).dropna()
    # Clip extreme tails for stats (same as K1148_d1 did: |r|<=0.30)
    log_ret_is = log_ret_is[log_ret_is.abs() <= 0.30]

    feats['n_trading_days_is'] = int(len(log_ret_is))
    feats['is_annualized_vol'] = float(log_ret_is.std() * np.sqrt(252)) \
        if len(log_ret_is) >= 30 else np.nan
    feats['is_annualized_return'] = float(log_ret_is.mean() * 252) \
        if len(log_ret_is) >= 30 else np.nan
    feats['max_drawdown_is'] = compute_max_drawdown(is_prices.values) \
        if len(is_prices) >= 10 else np.nan
    # Vol-of-vol: std of rolling-21-day realized vol
    if len(log_ret_is) >= 100:
        rv21 = log_ret_is.rolling(21).std().dropna()
        feats['vol_of_vol'] = float(rv21.std())
    else:
        feats['vol_of_vol'] = np.nan

    # Dollar volume (recent IS window 2015-2019)
    if 'Volume' in raw.columns and len(recent_is_prices) > 0:
        rv = raw.loc[recent_is_prices.index, ['Close', 'Volume']].dropna()
        if len(rv) > 0:
            feats['avg_dollar_vol_is'] = float((rv['Close'] * rv['Volume']).mean())
        else:
            feats['avg_dollar_vol_is'] = np.nan
    else:
        feats['avg_dollar_vol_is'] = np.nan

    # GJR params from K1148_d1 IS fit: [theta0, omega_g, alpha, gamma_p, beta_p]
    if gjr_params is not None:
        t0, og, a, gp, bp = gjr_params
        feats['gjr_theta0'] = float(t0)
        feats['gjr_omega'] = float(og)
        feats['gjr_alpha'] = float(a)
        feats['gjr_gamma'] = float(gp)
        feats['gjr_beta'] = float(bp)
        feats['gjr_persistence'] = float(a + gp / 2.0 + bp)
    else:
        for k in ['gjr_theta0', 'gjr_omega', 'gjr_alpha', 'gjr_gamma',
                   'gjr_beta', 'gjr_persistence']:
            feats[k] = np.nan

    # Earnings frequency + surprise (IS window only, 2010-2019)
    ev = earnings_surprise.get(ticker, [])
    # Filter to IS window
    ev_is = []
    for e in ev:
        try:
            dt = pd.Timestamp(e['date'])
            if IS_FULL_START <= dt <= IS_END:
                sp = e.get('surprise_pct')
                if sp is not None and np.isfinite(sp):
                    ev_is.append({'date': dt, 'surprise_pct': float(sp)})
        except Exception:
            continue
    feats['n_surprise_events_is'] = len(ev_is)
    if len(ev_is) >= 1:
        surprises = np.array([e['surprise_pct'] for e in ev_is])
        feats['avg_abs_surprise_pct_is'] = float(np.mean(np.abs(surprises)))
        feats['mean_surprise_pct_is'] = float(np.mean(surprises))
        # Symmetry ratio: |mean(surprise)| / mean(|surprise|).
        # Near 0 = symmetric (mix of beats/misses). Near 1 = systematic beat or miss.
        denom = np.mean(np.abs(surprises))
        feats['surprise_symmetry_ratio'] = \
            float(abs(np.mean(surprises)) / denom) if denom > 0 else np.nan
    else:
        feats['avg_abs_surprise_pct_is'] = np.nan
        feats['mean_surprise_pct_is'] = np.nan
        feats['surprise_symmetry_ratio'] = np.nan

    # Earnings freq per year — IS span in years
    n_years = (IS_END - IS_FULL_START).days / 365.25
    feats['earnings_freq_per_year_is'] = len(ev_is) / n_years if n_years > 0 else np.nan

    return feats


# --------------------- main analysis --------------------------
def main():
    print(f'\n{"=" * 72}')
    print(f'{EXPERIMENT_ID}: PASS vs FAIL characteristics')
    print(f'{"=" * 72}\n')

    # --- 1. Load K1148_d1 per-stock DM + GJR ---
    per_stock_dm, gjr_map = load_k1148_d1()
    print(f'[1/5] Loaded {len(per_stock_dm)} stocks from K1148_d1\n')

    # --- 2. Split PASS / FAIL ---
    pass_rows = [p for p in per_stock_dm if p['dm_stat'] is not None
                 and p['dm_stat'] <= OOS_DM_THRESHOLD]
    fail_rows = [p for p in per_stock_dm if p['dm_stat'] is not None
                 and p['dm_stat'] > OOS_DM_THRESHOLD]
    pass_tks = [p['ticker'] for p in pass_rows]
    fail_tks = [p['ticker'] for p in fail_rows]
    print(f'  PASS (DM ≤ {OOS_DM_THRESHOLD}): n={len(pass_tks)}')
    print(f'    {pass_tks}')
    print(f'  FAIL (DM > {OOS_DM_THRESHOLD}): n={len(fail_tks)}')
    print(f'    {fail_tks}\n')

    # --- 3. Load auxiliary data sources ---
    sector_info = load_sector_info()
    earnings_surprise = load_earnings_surprise()
    print(f'[2/5] Loaded sector_info ({len(sector_info)}) + '
          f'earnings_surprise ({len(earnings_surprise)})\n')

    # --- 4. Extract features for each ticker ---
    print('[3/5] Extracting features ...')
    features = []
    for row in per_stock_dm:
        tk = row['ticker']
        feats = compute_features(tk, gjr_map.get(tk), sector_info, earnings_surprise)
        feats['dm_stat'] = row['dm_stat']
        feats['group'] = 'PASS' if row['dm_stat'] <= OOS_DM_THRESHOLD else 'FAIL'
        features.append(feats)
        print(f'  {tk} ({feats["group"]}): sector={feats.get("sector")}, '
              f'vol={feats.get("is_annualized_vol"):.3f}, '
              f'n_surp={feats.get("n_surprise_events_is")}')
    df = pd.DataFrame(features)
    print(f'\n  Feature DF: {df.shape}\n')

    # --- 5. Statistical comparison (numeric features only) ---
    numeric_features = [
        'market_cap_snapshot',
        'avg_dollar_vol_is',
        'is_annualized_vol',
        'is_annualized_return',
        'vol_of_vol',
        'max_drawdown_is',
        'gjr_alpha',
        'gjr_gamma',
        'gjr_beta',
        'gjr_persistence',
        'gjr_theta0',
        'n_surprise_events_is',
        'earnings_freq_per_year_is',
        'avg_abs_surprise_pct_is',
        'mean_surprise_pct_is',
        'surprise_symmetry_ratio',
    ]
    print('[4/5] Per-feature PASS vs FAIL comparison ...\n')
    tests = []
    for fname in numeric_features:
        a = df.loc[df['group'] == 'PASS', fname].values
        b = df.loc[df['group'] == 'FAIL', fname].values
        a_fin = np.asarray([x for x in a if np.isfinite(x)], dtype=float)
        b_fin = np.asarray([x for x in b if np.isfinite(x)], dtype=float)
        entry = {
            'feature': fname,
            'pass_n': int(len(a_fin)),
            'fail_n': int(len(b_fin)),
            'pass_mean': float(np.mean(a_fin)) if len(a_fin) > 0 else None,
            'pass_std': float(np.std(a_fin, ddof=1)) if len(a_fin) > 1 else None,
            'pass_median': float(np.median(a_fin)) if len(a_fin) > 0 else None,
            'fail_mean': float(np.mean(b_fin)) if len(b_fin) > 0 else None,
            'fail_std': float(np.std(b_fin, ddof=1)) if len(b_fin) > 1 else None,
            'fail_median': float(np.median(b_fin)) if len(b_fin) > 0 else None,
        }
        if len(a_fin) < 2 or len(b_fin) < 2:
            entry.update({'t_stat': None, 't_p': None,
                           'u_stat': None, 'u_p': None,
                           'cohens_d': None, 'rank_biserial': None})
        else:
            t_stat, t_p = stats.ttest_ind(a_fin, b_fin, equal_var=False)
            try:
                u_stat, u_p = stats.mannwhitneyu(a_fin, b_fin, alternative='two-sided')
                rb = rank_biserial(a_fin, b_fin, float(u_stat))
            except Exception:
                u_stat, u_p, rb = None, None, None
            entry.update({
                't_stat': float(t_stat), 't_p': float(t_p),
                'u_stat': float(u_stat) if u_stat is not None else None,
                'u_p': float(u_p) if u_p is not None else None,
                'cohens_d': cohens_d(a_fin, b_fin),
                'rank_biserial': rb,
            })
        tests.append(entry)

    # BH adjustment on Welch t p-values
    t_pvals = [e['t_p'] for e in tests]
    u_pvals = [e['u_p'] for e in tests]
    t_adj = bh_adjust(t_pvals)
    u_adj = bh_adjust(u_pvals)
    for i, e in enumerate(tests):
        e['t_p_bh_adj'] = float(t_adj[i]) if np.isfinite(t_adj[i]) else None
        e['u_p_bh_adj'] = float(u_adj[i]) if np.isfinite(u_adj[i]) else None

    # Print summary
    print(f'{"feature":30} | {"PASS (μ±σ)":>22} | {"FAIL (μ±σ)":>22} | '
          f'{"d":>7} | {"t_p":>8} | {"t_p_BH":>8} | {"u_p":>8} | {"u_p_BH":>8}')
    for e in tests:
        if e['t_stat'] is None:
            print(f'  {e["feature"]:28} | insufficient data')
            continue
        pm = f"{e['pass_mean']:+.3e}±{e['pass_std']:+.2e}"
        fm = f"{e['fail_mean']:+.3e}±{e['fail_std']:+.2e}"
        print(f'  {e["feature"]:28} | {pm:>22} | {fm:>22} | '
              f'{e["cohens_d"]:>+7.3f} | {e["t_p"]:>8.4f} | '
              f'{e["t_p_bh_adj"]:>8.4f} | {e["u_p"]:>8.4f} | '
              f'{e["u_p_bh_adj"]:>8.4f}')

    # --- 5b. Categorical feature: sector (Fisher exact on collapsed 2x2) ---
    print('\n  Sector distribution (PASS / FAIL):')
    sectors_pass = df.loc[df['group'] == 'PASS', 'sector'].fillna('UNK').tolist()
    sectors_fail = df.loc[df['group'] == 'FAIL', 'sector'].fillna('UNK').tolist()
    all_sectors = sorted(set(sectors_pass) | set(sectors_fail))
    sector_stats = []
    for s in all_sectors:
        p_in = sum(1 for x in sectors_pass if x == s)
        f_in = sum(1 for x in sectors_fail if x == s)
        # Fisher exact on 2x2 (s vs not-s) × (PASS vs FAIL)
        p_not = len(sectors_pass) - p_in
        f_not = len(sectors_fail) - f_in
        try:
            odds, p_val = stats.fisher_exact([[p_in, p_not], [f_in, f_not]])
        except Exception:
            odds, p_val = None, None
        sector_stats.append({
            'sector': s,
            'pass_count': p_in,
            'fail_count': f_in,
            'pass_pct': p_in / len(sectors_pass) if sectors_pass else 0,
            'fail_pct': f_in / len(sectors_fail) if sectors_fail else 0,
            'fisher_odds': float(odds) if odds is not None else None,
            'fisher_p': float(p_val) if p_val is not None else None,
        })
        print(f'    {s:25}: PASS={p_in}/{len(sectors_pass)} '
              f'({p_in/max(len(sectors_pass),1):.0%}), '
              f'FAIL={f_in}/{len(sectors_fail)} '
              f'({f_in/max(len(sectors_fail),1):.0%}), '
              f'Fisher p={p_val if p_val is not None else "NA"}')

    # Also list sector → tickers for paper narrative
    sector_tickers = {}
    for row in features:
        s = row.get('sector') or 'UNK'
        sector_tickers.setdefault(s, {'PASS': [], 'FAIL': []})[row['group']].append(row['ticker'])

    # --- 6. Verdict ---
    print('\n[5/5] Verdict evaluation:')
    significant_feats = []
    for e in tests:
        if e['cohens_d'] is None or e['t_p_bh_adj'] is None:
            continue
        if e['t_p_bh_adj'] < 0.1 and abs(e['cohens_d']) > 0.5:
            significant_feats.append({
                'feature': e['feature'],
                'cohens_d': e['cohens_d'],
                't_p_bh_adj': e['t_p_bh_adj'],
                'pass_mean': e['pass_mean'],
                'fail_mean': e['fail_mean'],
            })
    # Check sector too (BH on Fisher p)
    sp = [s['fisher_p'] for s in sector_stats]
    sp_adj = bh_adjust(sp)
    for i, s in enumerate(sector_stats):
        s['fisher_p_bh_adj'] = float(sp_adj[i]) if np.isfinite(sp_adj[i]) else None
    sig_sectors = [s for s in sector_stats
                   if s['fisher_p_bh_adj'] is not None
                   and s['fisher_p_bh_adj'] < 0.1]

    option3_viable = (len(significant_feats) >= 1) or (len(sig_sectors) >= 1)
    verdict = 'Option 3 VIABLE' if option3_viable else 'Option 3 REJECTED'
    print(f'  → {verdict}')
    print(f'  Significant numeric features (BH adj p<0.1 AND |d|>0.5): '
          f'{len(significant_feats)}')
    for s in significant_feats:
        print(f'    - {s["feature"]}: d={s["cohens_d"]:+.3f}, '
              f'BH adj p={s["t_p_bh_adj"]:.4f}, '
              f'PASS μ={s["pass_mean"]:.3e}, FAIL μ={s["fail_mean"]:.3e}')
    print(f'  Significant sectors (Fisher BH adj p<0.1): {len(sig_sectors)}')
    for s in sig_sectors:
        print(f'    - {s["sector"]}: PASS={s["pass_count"]}, '
              f'FAIL={s["fail_count"]}, BH p={s["fisher_p_bh_adj"]:.4f}')

    # --- Plots ---
    print('\n[plot] pass_vs_fail_features.png ...')
    plot_features = [f for f in numeric_features
                     if df[f].notna().sum() >= 10]
    n_feat = len(plot_features)
    ncol = 4
    nrow = int(np.ceil(n_feat / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 3.2 * nrow))
    axes = np.atleast_2d(axes).flatten()
    for i, fname in enumerate(plot_features):
        ax = axes[i]
        a = df.loc[df['group'] == 'PASS', fname].dropna().values
        b = df.loc[df['group'] == 'FAIL', fname].dropna().values
        # Mini-boxplot + scatter jitter
        bp = ax.boxplot([a, b], labels=['PASS\n(n=%d)' % len(a),
                                          'FAIL\n(n=%d)' % len(b)],
                         widths=0.55, patch_artist=True, showmeans=True)
        for patch, color in zip(bp['boxes'], ['#66b3ff', '#ff7f7f']):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
        # Scatter raw
        rng = np.random.default_rng(GLOBAL_SEED + i)
        ax.scatter(np.full_like(a, 1, dtype=float)
                    + rng.normal(0, 0.04, size=len(a)),
                   a, color='black', alpha=0.5, s=14, zorder=3)
        ax.scatter(np.full_like(b, 2, dtype=float)
                    + rng.normal(0, 0.04, size=len(b)),
                   b, color='black', alpha=0.5, s=14, zorder=3)
        # Title with d + BH p
        entry = next((e for e in tests if e['feature'] == fname), None)
        if entry and entry['cohens_d'] is not None:
            ax.set_title(f'{fname}\nd={entry["cohens_d"]:+.2f}, '
                          f'BH p={entry["t_p_bh_adj"]:.2f}',
                          fontsize=9)
        else:
            ax.set_title(fname, fontsize=9)
        ax.grid(alpha=0.3)
    for j in range(len(plot_features), len(axes)):
        axes[j].axis('off')
    plt.suptitle(f'K1148_d3: PASS (9) vs FAIL (20) TW stock features — OOS DM≤-2',
                  fontsize=12, y=1.01)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / 'pass_vs_fail_features.png',
                dpi=120, bbox_inches='tight')
    plt.close()
    print(f'  → {SCRIPT_DIR / "pass_vs_fail_features.png"}')

    # Feature importance chart
    print('[plot] feature_importance.png ...')
    valid_tests = [e for e in tests if e['cohens_d'] is not None]
    valid_tests_sorted = sorted(valid_tests, key=lambda e: abs(e['cohens_d']),
                                 reverse=True)
    names = [e['feature'] for e in valid_tests_sorted]
    ds = [e['cohens_d'] for e in valid_tests_sorted]
    bh_ps = [e['t_p_bh_adj'] for e in valid_tests_sorted]
    colors = []
    for p in bh_ps:
        if p is None:
            colors.append('lightgray')
        elif p < 0.05:
            colors.append('#d62728')    # red: sig at 5%
        elif p < 0.1:
            colors.append('#ff7f0e')    # orange: sig at 10%
        else:
            colors.append('#1f77b4')    # blue: NS
    fig, ax = plt.subplots(figsize=(10, 6))
    y_pos = np.arange(len(names))
    ax.barh(y_pos, [abs(d) for d in ds], color=colors, edgecolor='black')
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=9)
    ax.invert_yaxis()
    ax.axvline(0.2, color='gray', linestyle=':', label='small (|d|=0.2)')
    ax.axvline(0.5, color='gray', linestyle='--', label='medium (|d|=0.5)')
    ax.axvline(0.8, color='gray', linestyle='-', alpha=0.4, label='large (|d|=0.8)')
    ax.set_xlabel('|Cohen\'s d|')
    ax.set_title('K1148_d3: Feature importance for PASS vs FAIL split\n'
                  '(color: BH adj p — red<0.05, orange<0.1, blue=NS)')
    ax.legend(loc='lower right', fontsize=8)
    ax.grid(alpha=0.3, axis='x')
    # Annotate BH p
    for i, (d, p) in enumerate(zip(ds, bh_ps)):
        lbl = f'd={d:+.2f}, BH p={p:.2f}' if p is not None else f'd={d:+.2f}'
        ax.text(abs(d) + 0.02, i, lbl, va='center', fontsize=8)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / 'feature_importance.png',
                dpi=120, bbox_inches='tight')
    plt.close()
    print(f'  → {SCRIPT_DIR / "feature_importance.png"}')

    # --- Save results ---
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'PASS vs FAIL TW stock characteristics for Paper 2 Option 3',
        'proposer': 'Claude (Paper 2 §5 Option 3 heterogeneity subsection)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_source': 'K1148_d1 results + yfinance + K1148 earnings cache',
        'oos_dm_threshold': OOS_DM_THRESHOLD,
        'n_pass': len(pass_tks),
        'n_fail': len(fail_tks),
        'pass_tickers': pass_tks,
        'fail_tickers': fail_tks,
        'features_raw': features,
        'feature_tests': tests,
        'sector_tests': sector_stats,
        'sector_tickers': sector_tickers,
        'significant_numeric_features': significant_feats,
        'significant_sectors': sig_sectors,
        'option3_viable': option3_viable,
        'verdict': verdict,
        'caveats': [
            'N=29 is underpowered. Significance is exploratory, not confirmatory.',
            'BH adj applied over 16 numeric features (controls FDR at 10%).',
            'market_cap_snapshot is CURRENT yfinance — primary size metric is '
            'avg_dollar_vol_is (2015-2019 IS; historically clean).',
            'Sector from yfinance snapshot; TW listed stocks rarely reassigned, '
            'so snapshot ≈ 2020-era sector.',
            'Per-stock GJR (alpha/gamma/beta) from K1148_d1 IS fit — pooled θ_EAV '
            'was shared, so we cannot report per-stock β_EAV; only GJR-component '
            'heterogeneity.',
        ],
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results → {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s\n')
    print(f'  FINAL VERDICT: {verdict}')


if __name__ == '__main__':
    main()
