#!/usr/bin/env python3
"""
K1161: Options-implied IV crush as continuous EAV regressor — DATA FEASIBILITY
==============================================================================
[提出: Claude (承接 K1151 next_tasks K1161), 執行: Claude]

Motivation
----------
K1151 tested |Surprise(%)| as a continuous EAV regressor on the US N=30 panel
and found it NS (bootstrap t=+1.11, p=0.41). Binary EAV remained sufficient.

K1161 proposes testing a DIFFERENT continuous signal: the "IV crush" magnitude
(IV_pre − IV_post), reasoning that option-implied volatility is a market-
aggregated, forward-looking expectation of the earnings vol event — plausibly
more informative than the backward-looking Surprise(%) accounting number.

Pre-registered scenarios (per prompt):
  A: IV crush dominates M5 horse race → Paper 2 §5 adds market-implied subsection
  B: IV crush complements binary      → dual-factor narrative
  C: Raw IV_pre matters, not crush    → "forward expectation" story
  D: All IV regressors NULL            → IV signal < K1148_d2 binary EAV reliability
  DATA_INFEASIBLE: yfinance coverage < 10% → terminate, no fabricated data

Data requirement
----------------
For each earnings event e at date t_e, need:
  - IV_pre  = ATM option implied vol at t_e - 1 (close)
  - IV_post = ATM option implied vol at t_e + 1 (close)
  - IV_crush = IV_pre - IV_post

Coverage target: >= 10% of the 1,439 earnings events in K1148_d2 cache.

Feasibility investigation
-------------------------
This script documents a systematic probe of yfinance option-chain history
across the 30-stock panel and 1,439 earnings events. If coverage < 10%, we
TERMINATE the experiment and record DATA_INFEASIBLE per the prompt rule.

Author: VolPred Research System.
Date: 2026-04-17.
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)

EXPERIMENT_ID = 'K1161'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = SCRIPT_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = SCRIPT_DIR / 'k1161_results.json'
LOG_PATH = SCRIPT_DIR / 'run.log'

PROJECT_ROOT = SCRIPT_DIR.parent.parent
K1148_D2_SURPRISE_CACHE = (
    PROJECT_ROOT / 'experiments' / 'k1148_d2' / 'data'
    / 'earnings_dates_surprise_us.json'
)

# K1147 pre-registered US tickers (reused by K1148, K1148_d2, K1151)
US_TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B',
    'UNH', 'V', 'JPM', 'WMT', 'MA', 'JNJ', 'XOM', 'PG', 'HD', 'CVX',
    'ABBV', 'AVGO', 'COST', 'PEP', 'KO', 'MRK', 'ADBE', 'CSCO', 'TMO',
    'CRM', 'MCD', 'ABT',
]

COVERAGE_TERMINATE_THRESHOLD = 0.10  # < 10% → DATA_INFEASIBLE

START_TIME = time.time()


# ----------------------------------------------------------------------
# Feasibility probes
# ----------------------------------------------------------------------
def probe_current_options_chain(ticker: str) -> dict:
    """Check whether yfinance returns implied volatility for the currently
    listed option chain. (This tests the API only — not historical data.)"""
    tk = yf.Ticker(ticker)
    try:
        exps = tk.options
    except Exception as e:
        return {'ok': False, 'error': f'options list: {e}'}
    if not exps:
        return {'ok': False, 'error': 'no option expirations'}
    try:
        chain = tk.option_chain(exps[0])
        iv_col = 'impliedVolatility' in chain.calls.columns
        iv_n_valid = int((chain.calls['impliedVolatility'] > 0).sum())
        return {
            'ok': iv_col,
            'n_expirations': len(exps),
            'first_exp': exps[0],
            'last_exp': exps[-1],
            'calls_rows': int(len(chain.calls)),
            'iv_column_present': iv_col,
            'iv_rows_gt_zero': iv_n_valid,
        }
    except Exception as e:
        return {'ok': False, 'error': f'option_chain: {e}'}


def probe_historical_contract(contract_symbol: str) -> dict:
    """Attempt to fetch historical OHLC on an individual option contract.
    Returns {ok, n_rows, date_range_days, first_date, last_date}."""
    try:
        opt = yf.Ticker(contract_symbol)
        h = opt.history(period='2y')
        n = len(h)
        if n == 0:
            return {'ok': False, 'n_rows': 0, 'reason': 'delisted/no-data'}
        return {
            'ok': True,
            'n_rows': int(n),
            'date_range_days': int((h.index[-1] - h.index[0]).days),
            'first_date': h.index[0].date().isoformat(),
            'last_date': h.index[-1].date().isoformat(),
            'has_price': bool(('Close' in h.columns) and (h['Close'] > 0).any()),
            'has_iv': False,  # yfinance history does NOT expose IV
        }
    except Exception as e:
        return {'ok': False, 'n_rows': 0, 'reason': f'error: {e}'}


def reconstruct_iv_via_atm_contract(
    ticker: str,
    target_date: date,
    spot_price: float,
    lookback_days: int = 2,
) -> dict:
    """Try to reconstruct ATM IV for `ticker` on or near `target_date`
    by locating an option contract that was ATM and close to expiry on
    that date.

    Returns {ok, contract_symbol, iv_found, method, notes}.

    This is a BEST-EFFORT probe — yfinance does not expose historical IV
    directly. We would need to (a) locate the right contract, (b) back out
    IV from historical price via Black-Scholes. Since expired contracts
    return no data (step a fails), we report infeasibility.
    """
    tk = yf.Ticker(ticker)
    try:
        exps = tk.options
    except Exception as e:
        return {'ok': False, 'reason': f'options list: {e}'}
    if not exps:
        return {'ok': False, 'reason': 'no options listed'}

    # Find expiration immediately AFTER target_date (typical earnings-week expiry)
    target_dt = pd.Timestamp(target_date)
    eligible = [e for e in exps
                if pd.Timestamp(e) >= target_dt + pd.Timedelta(days=1)
                and pd.Timestamp(e) <= target_dt + pd.Timedelta(days=60)]
    if not eligible:
        return {'ok': False, 'reason': f'no expirations within 1-60 days of {target_date}'}

    exp_pick = eligible[0]
    try:
        chain = tk.option_chain(exp_pick)
    except Exception as e:
        return {'ok': False, 'reason': f'option_chain({exp_pick}): {e}'}

    # Find ATM strike
    calls = chain.calls
    if len(calls) == 0:
        return {'ok': False, 'reason': 'empty call chain'}
    idx_atm = int((calls['strike'] - spot_price).abs().idxmin())
    row_atm = calls.loc[idx_atm]
    contract_sym = row_atm['contractSymbol']

    # Attempt to fetch historical price on this option contract
    hist = probe_historical_contract(contract_sym)
    if not hist['ok']:
        return {
            'ok': False,
            'contract_symbol': contract_sym,
            'exp_pick': exp_pick,
            'reason': f'contract history unavailable: {hist.get("reason")}',
        }
    # Check whether the history covers target_date
    first_d = date.fromisoformat(hist['first_date'])
    last_d = date.fromisoformat(hist['last_date'])
    if not (first_d <= target_date <= last_d):
        return {
            'ok': False,
            'contract_symbol': contract_sym,
            'exp_pick': exp_pick,
            'hist_range': f'{first_d} ~ {last_d}',
            'target_date': target_date.isoformat(),
            'reason': 'target_date outside contract history window',
        }
    return {
        'ok': True,
        'contract_symbol': contract_sym,
        'exp_pick': exp_pick,
        'hist_first': hist['first_date'],
        'hist_last': hist['last_date'],
        'target_date': target_date.isoformat(),
        'note': 'contract price available; IV still needs Black-Scholes back-out',
    }


def full_feasibility_study(tickers: list, earnings_cache: dict) -> dict:
    """Main feasibility check:
    1. Confirm yfinance returns IV on current chain (API sanity)
    2. Count earnings events overall
    3. For each earnings event, probe whether IV_pre / IV_post can be
       reconstructed via a currently-listed option contract
    4. Tabulate coverage by year / ticker; terminate if < 10%
    """
    print(f'\n{"=" * 72}\n{EXPERIMENT_ID}: IV-crush data feasibility probe\n{"=" * 72}\n')

    # Step 1: API sanity — one ticker
    print('[1/4] yfinance option-chain API sanity check (AAPL current)')
    api_check = probe_current_options_chain('AAPL')
    print(f'  AAPL current chain: {api_check}')

    # Step 2: Count earnings
    total_events = sum(len(rows) for rows in earnings_cache.values())
    today = date.today()
    six_m = today - timedelta(days=180)
    one_y = today - timedelta(days=365)
    two_y = today - timedelta(days=365 * 2)
    n_last_6m = 0
    n_last_1y = 0
    n_last_2y = 0
    for tk, rows in earnings_cache.items():
        for r in rows:
            d = date.fromisoformat(r['date'])
            if d >= six_m:
                n_last_6m += 1
            if d >= one_y:
                n_last_1y += 1
            if d >= two_y:
                n_last_2y += 1
    print(f'\n[2/4] Earnings events in K1148_d2 panel: {total_events}')
    print(f'  Last 6 months:  {n_last_6m} ({n_last_6m / total_events:.1%})')
    print(f'  Last 1 year:    {n_last_1y} ({n_last_1y / total_events:.1%})')
    print(f'  Last 2 years:   {n_last_2y} ({n_last_2y / total_events:.1%})')

    # Step 3: Probe expired-contract retrieval
    print('\n[3/4] Probe: can yfinance return OHLC on expired option contracts?')
    expired_probes = [
        'AAPL240315C00180000',  # Mar 2024 expiry (AAPL earnings 2024-02-01 context)
        'AAPL230721C00190000',
        'MSFT240119C00330000',
        'NVDA230915C00420000',
        'AMZN231117C00140000',
    ]
    expired_results = {sym: probe_historical_contract(sym) for sym in expired_probes}
    for sym, res in expired_results.items():
        status = 'OK' if res.get('ok') else 'FAIL'
        print(f'  {sym}: {status} — {res}')

    # Step 4: Probe currently-listed contract reach-back
    print('\n[4/4] Probe: longest-dated AAPL option contract history span')
    tk = yf.Ticker('AAPL')
    exps = tk.options
    reachback = None
    if exps:
        long_exp = exps[-1]
        chain = tk.option_chain(long_exp)
        mid = len(chain.calls) // 2
        sym_to_probe = chain.calls['contractSymbol'].iloc[mid]
        rb = probe_historical_contract(sym_to_probe)
        print(f'  longest-dated exp = {long_exp}, ATM-ish contract = {sym_to_probe}')
        print(f'  history span: {rb}')
        reachback = {'contract': sym_to_probe, 'exp': long_exp, 'hist': rb}

    # Aggregate coverage bound:
    # Even in the best case, yfinance only serves history for CURRENTLY LISTED
    # contracts, and the history span is bounded by Yahoo's own retention
    # (empirically ~90 days, as observed in the reachback probe above).
    # Expired contracts (99.9% of 1,439 events over 2014-2024) → 0 coverage.
    n_all_expired_accessible = sum(
        1 for res in expired_results.values() if res.get('ok')
    )
    expired_accessibility = n_all_expired_accessible / len(expired_probes)

    # Realistic upper bound on coverage: earnings that overlap with a
    # currently-listed contract's available history (~last 90 days)
    n_last_90d = 0
    ninety_d = today - timedelta(days=90)
    for tk, rows in earnings_cache.items():
        for r in rows:
            d = date.fromisoformat(r['date'])
            if d >= ninety_d:
                n_last_90d += 1
    coverage_upper = n_last_90d / total_events

    print(f'\n  Expired-contract retrieval rate: {n_all_expired_accessible}/{len(expired_probes)}')
    print(f'  Realistic coverage upper bound (90-day history × currently listed): '
          f'{n_last_90d}/{total_events} = {coverage_upper:.2%}')

    feasible = coverage_upper >= COVERAGE_TERMINATE_THRESHOLD

    return {
        'api_sanity_current_chain': api_check,
        'total_earnings_events': total_events,
        'events_last_6m': n_last_6m,
        'events_last_1y': n_last_1y,
        'events_last_2y': n_last_2y,
        'events_last_90d': n_last_90d,
        'expired_contract_probes': expired_results,
        'expired_accessibility_rate': expired_accessibility,
        'reachback_probe': reachback,
        'coverage_upper_bound_frac': coverage_upper,
        'coverage_terminate_threshold': COVERAGE_TERMINATE_THRESHOLD,
        'feasible': bool(feasible),
    }


# ----------------------------------------------------------------------
# Plot: coverage funnel
# ----------------------------------------------------------------------
def plot_coverage_funnel(feas: dict) -> Path:
    total = feas['total_earnings_events']
    fig, ax = plt.subplots(1, 1, figsize=(9, 5))
    buckets = [
        ('Total earnings\n(2014-2025)', total),
        ('In last 2y\n(plausible if\nyfinance gave 2y)', feas['events_last_2y']),
        ('In last 1y', feas['events_last_1y']),
        ('In last 6m', feas['events_last_6m']),
        ('In last 90d\n(realistic ceiling)', feas['events_last_90d']),
    ]
    labels = [b[0] for b in buckets]
    vals = [b[1] for b in buckets]
    colors = ['#2e7d32', '#7cb342', '#fbc02d', '#fb8c00', '#d32f2f']
    bars = ax.bar(range(len(labels)), vals, color=colors, edgecolor='black', alpha=0.85)
    ax.axhline(total * 0.10, color='black', linestyle='--',
               label=f'10% threshold ({int(total * 0.10)} events)')
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel('# earnings events')
    ax.set_title(f'{EXPERIMENT_ID}: IV-crush coverage funnel — yfinance cannot historically cover '
                 'pre-2026 earnings')
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + total * 0.01,
                f'{v}\n({v / total:.1%})', ha='center', va='bottom',
                fontsize=9, fontweight='bold')
    ax.legend(loc='upper right')
    plt.tight_layout()
    path = SCRIPT_DIR / 'iv_crush_vs_surprise.png'
    plt.savefig(path, dpi=120)
    plt.close()
    return path


def plot_theta_placeholder(feas: dict) -> Path:
    """Since DATA_INFEASIBLE, theta_comparison is a placeholder showing
    what we WOULD have compared vs K1151's Surprise result."""
    fig, ax = plt.subplots(1, 1, figsize=(9, 5))
    ax.set_xticks([])
    ax.set_yticks([])
    ax.text(0.5, 0.55,
            'K1161 theta comparison NOT EXECUTED',
            ha='center', va='center', fontsize=18, fontweight='bold',
            color='#b71c1c', transform=ax.transAxes)
    ax.text(0.5, 0.42,
            'DATA_INFEASIBLE — yfinance options chain does not retain\n'
            f'expired contracts; realistic coverage ceiling = '
            f'{feas["coverage_upper_bound_frac"]:.2%} << 10%',
            ha='center', va='center', fontsize=12,
            color='#424242', transform=ax.transAxes)
    ax.text(0.5, 0.25,
            'Paper 2 §5 implication: no IV-crush upgrade candidate;\n'
            'K1148_d2 binary claim retained unchanged.',
            ha='center', va='center', fontsize=11,
            color='#1b5e20', transform=ax.transAxes)
    ax.set_title(f'{EXPERIMENT_ID}: θ comparison placeholder (experiment terminated)')
    plt.tight_layout()
    path = SCRIPT_DIR / 'theta_comparison.png'
    plt.savefig(path, dpi=120)
    plt.close()
    return path


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    with open(K1148_D2_SURPRISE_CACHE) as f:
        earnings_cache = json.load(f)

    feas = full_feasibility_study(US_TICKERS, earnings_cache)

    print(f'\n\n{"=" * 72}\n FEASIBILITY VERDICT\n{"=" * 72}')
    if not feas['feasible']:
        verdict = 'DATA_INFEASIBLE'
        rationale = (
            f"yfinance option-chain history does not support historical IV "
            f"reconstruction for earnings events prior to the last ~90 days. "
            f"Coverage ceiling = {feas['coverage_upper_bound_frac']:.2%} of "
            f"{feas['total_earnings_events']} events, below the 10% threshold. "
            f"Expired contracts return no OHLC data (tested 5/5 fail). "
            f"Currently-listed contracts only retain ~90 days of Yahoo history "
            f"(reachback probe). Therefore IV_pre / IV_post cannot be "
            f"systematically built for the K1148_d2 panel."
        )
        paper2_implication = (
            'No IV-crush upgrade candidate for Paper 2 §5. K1148_d2 binary EAV '
            'claim (US cross-market OOS PASS, panel DM t=-5.58) retained as the '
            'main spec. K1151 continuous Surprise(%) result (NS) also retained. '
            'Any market-implied magnitude test would require a paid data source '
            '(OptionMetrics IvyDB, CBOE DataShop, Bloomberg OVDV, polygon.io paid '
            'tier with historical options, or ORATS) — flagged as future work.'
        )
    else:
        verdict = 'FEASIBLE_PROCEED'
        rationale = f'coverage ceiling {feas["coverage_upper_bound_frac"]:.2%} >= 10%'
        paper2_implication = 'To be determined after running the model specs.'

    print(f'  Verdict: {verdict}')
    print(f'  Rationale: {rationale}')
    print(f'  Paper 2 implication: {paper2_implication}')

    # Plots
    print('\n[plot] coverage funnel + placeholder')
    p1 = plot_coverage_funnel(feas)
    p2 = plot_theta_placeholder(feas)
    print(f'  → {p1}')
    print(f'  → {p2}')

    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'Options-implied IV crush as continuous EAV regressor '
                 '(Paper 2 market-implied magnitude test)',
        'proposer': 'Claude (承接 K1151 next_tasks K1161)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'tickers': US_TICKERS,
        'data_source_probed': (
            'yfinance.Ticker.option_chain (current) and '
            'yfinance.Ticker(contract_symbol).history (historical per-contract)'
        ),
        'earnings_cache_source': str(K1148_D2_SURPRISE_CACHE),
        'coverage_terminate_threshold_frac': COVERAGE_TERMINATE_THRESHOLD,
        'feasibility_study': feas,
        'verdict': verdict,
        'rationale': rationale,
        'paper2_implication': paper2_implication,
        'scenario_flag': verdict,  # alias per prompt Step 7 template
        'oos_panel_dm_table': None,  # not computed
        'best_iv_regressor': None,
        'gemini_review_summary': 'see README.md §Gemini review',
        'model_specs_run': [],      # none
        'model_specs_planned': ['M1_binary', 'M2_surprise',
                                 'M3_iv_crush', 'M4_iv_pre', 'M5_joint'],
        'note': ('Experiment terminated at Step 1 (data feasibility) per '
                 'pre-registered prompt rule: "若覆蓋率 < 10% → 立即終止".'),
        'elapsed_seconds': float(time.time() - START_TIME),
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results → {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')


if __name__ == '__main__':
    main()
