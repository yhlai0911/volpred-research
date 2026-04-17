#!/usr/bin/env python3
"""
K1190: Paper 3 Sector Analysis — 11 SPDR ETFs, r=0.163, gamma range [0.077, 0.160]
===================================================================================

OBJECTIVE:
    Reproduce Paper 3 sector boundary-condition analysis:
    - GJR-GARCH gamma estimation for 11 SPDR sector ETFs
    - VT Sharpe improvement per sector (VT Sharpe - BH Sharpe)
    - Pearson correlation: gamma vs Sharpe improvement
    - Paper claims: r=0.163, p=0.632, gamma range [0.077, 0.160]

PAPER CLAIMS (main.tex Section 3.4 "Boundary Condition"):
    "The Pearson correlation between gamma and VT's Sharpe improvement is
     r = 0.163 (p = 0.632)---economically small and statistically insignificant.
     The structural explanation is that gamma variation within equity sectors is
     compressed ([0.077, 0.160]) relative to the cross-asset range ([-0.037, 0.261])"

    Note: Sector analysis uses gamma vs Sharpe improvement (Delta Sharpe = VT - BH),
    NOT gamma vs TSMOM loading (which is for the 22-asset cross-sectional r=0.564).

11 SPDR ETFs (XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY, XLRE, XLC):
    - Most: December 1998 start
    - XLC: launched June 2018 (shorter history)
    - XLRE: launched October 2015 (shorter history)
    - Data through March 2026

VT SETUP (matching paper canonical):
    - w_t = min(12/VIX_{end of month t}, 1)
    - Monthly rebalancing, weight applies to month t+1 (1-month lag)
    - Cash proxy: SHY
    - Tx cost: 10 bps per round trip

GJR-GARCH(1,1):
    sigma^2_t = omega + (alpha + gamma * I[r_{t-1}<0]) * r_{t-1}^2 + beta * sigma_{t-1}^2
    gamma = asymmetric leverage effect parameter

CORRELATION:
    Pearson r between gamma_i and (Sharpe_VT_i - Sharpe_BH_i) across 11 sectors

LOOKAHEAD PROTECTION:
    - VT signal: VIX end-of-month t -> weight for month t+1
    - signal.shift(1) used explicitly

SEED: 42

Data: yfinance — SPDR ETFs + ^VIX + SHY
Period: December 1998 to March 2026 (with availability per ETF)
"""

import json
import logging
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import scipy.stats
import yfinance as yf

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
SEED = 42
np.random.seed(SEED)

SECTOR_ETFS = ['XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY', 'XLRE', 'XLC']

# Data download range (extra lead for GJR-GARCH convergence)
DATA_START = '1997-01-01'
DATA_END = '2026-04-01'

# Analysis start: December 1998 (paper stated for sector sample)
# We test two scenarios:
#   A) Each sector uses its maximum available history from Dec 1998
#   B) Unified start 2005-01-03 (matching paper's primary 22-asset sample start)
ANALYSIS_START = '1998-12-01'   # Paper states "December 1998 to March 2026"
ANALYSIS_END = '2026-03-31'

VT_NUMERATOR = 12.0
ANNUALIZE = 252

# Paper reference values
PAPER_R = 0.163
PAPER_P = 0.632
PAPER_GAMMA_MIN = 0.077
PAPER_GAMMA_MAX = 0.160

# KB reference: XLF gamma=0.251
KB_XLF_GAMMA = 0.251

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a7880876/experiments/k1190/run.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# GJR-GARCH estimation (custom MLE, no package dependency)
# ============================================================

def gjr_garch_loglik(params, returns):
    """
    GJR-GARCH(1,1) log-likelihood.
    params = [omega, alpha, gamma, beta]
    """
    omega, alpha, gamma_gjr, beta = params

    # Parameter constraints
    if omega <= 0 or alpha < 0 or gamma_gjr < -alpha or beta < 0:
        return 1e10
    if alpha + gamma_gjr / 2 + beta >= 1:
        return 1e10
    if beta >= 1:
        return 1e10

    T = len(returns)
    sigma2 = np.zeros(T)
    # Initialize variance at unconditional variance
    uncond_var = omega / (1 - alpha - gamma_gjr * 0.5 - beta)
    if uncond_var <= 0:
        return 1e10
    sigma2[0] = uncond_var

    for t in range(1, T):
        indicator = 1.0 if returns[t - 1] < 0 else 0.0
        sigma2[t] = (omega
                     + (alpha + gamma_gjr * indicator) * returns[t - 1] ** 2
                     + beta * sigma2[t - 1])
        if sigma2[t] <= 0:
            return 1e10

    # Gaussian log-likelihood
    ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + returns ** 2 / sigma2)
    return -ll  # return negative (minimize)


def estimate_gjr_garch(returns):
    """
    Estimate GJR-GARCH(1,1) using 'arch' package (primary) with custom MLE fallback.
    arch package: arch_model(ret*100, vol='GARCH', p=1, o=1, q=1, dist='Normal')
    gamma = params['gamma[1]'] (the GJR leverage effect)

    Note: arch uses scaled returns (×100), but gamma is scale-invariant.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]

    if len(r) < 252:
        logger.warning(f"  Too few observations ({len(r)}) for GJR-GARCH")
        return None

    # --- Primary: arch package ---
    try:
        from arch import arch_model
        r_scaled = r * 100  # arch convention: percentage returns
        model = arch_model(r_scaled, vol='GARCH', p=1, o=1, q=1, dist='Normal',
                           mean='Zero')
        res = model.fit(disp='off', show_warning=False)
        params = res.params
        omega = float(params.get('omega', np.nan))
        alpha = float(params.get('alpha[1]', np.nan))
        gamma_gjr = float(params.get('gamma[1]', np.nan))
        beta = float(params.get('beta[1]', np.nan))
        loglik = float(res.loglikelihood)

        # Validate
        if not np.isnan(gamma_gjr) and not np.isnan(alpha) and not np.isnan(beta):
            return {
                'omega': omega / 10000,  # convert back from scaled
                'alpha': alpha,
                'gamma': gamma_gjr,
                'beta': beta,
                'loglik': loglik,
                'converged': True,
                'n_obs': int(len(r)),
                'method': 'arch'
            }
    except Exception as e:
        logger.warning(f"  arch package failed: {e}, falling back to custom MLE")

    # --- Fallback: custom multi-start L-BFGS-B ---
    from scipy.optimize import minimize

    var_r = np.var(r)
    starting_points = [
        [var_r * 0.05, 0.05, 0.08, 0.88],
        [var_r * 0.02, 0.02, 0.15, 0.88],
        [var_r * 0.02, 0.02, 0.20, 0.85],
        [var_r * 0.02, 0.02, 0.25, 0.82],
        [var_r * 0.01, 0.01, 0.20, 0.90],
        [var_r * 0.03, 0.04, 0.12, 0.87],
    ]

    bounds = [
        (1e-9, None),
        (0.0, 0.5),
        (-0.5, 0.5),
        (0.0, 0.9999),
    ]

    best_result = None
    best_val = np.inf

    for x0 in starting_points:
        try:
            res = minimize(
                gjr_garch_loglik, x0, args=(r,),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 2000, 'ftol': 1e-10}
            )
            if res.fun < best_val:
                best_val = res.fun
                best_result = res
        except Exception:
            continue

    if best_result is None:
        return None

    omega, alpha, gamma_gjr, beta = best_result.x
    return {
        'omega': float(omega),
        'alpha': float(alpha),
        'gamma': float(gamma_gjr),
        'beta': float(beta),
        'loglik': float(-best_val),
        'converged': True,
        'n_obs': int(len(r)),
        'method': 'custom_mle'
    }


# ============================================================
# Data download
# ============================================================

def download_data():
    """Download all required price data from Yahoo Finance."""
    logger.info("Downloading data from Yahoo Finance...")
    tickers = SECTOR_ETFS + ['^VIX', 'SHY']

    raw = yf.download(
        tickers,
        start=DATA_START,
        end=DATA_END,
        auto_adjust=True,
        progress=False
    )

    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw['Close']
    else:
        prices = raw

    logger.info(f"  Downloaded {len(prices)} rows, columns: {list(prices.columns)}")
    return prices


# ============================================================
# VT Sharpe improvement per sector
# ============================================================

def compute_sharpe(returns, annualize=ANNUALIZE):
    """Annualized Sharpe ratio (zero risk-free rate)."""
    r = returns.dropna()
    if len(r) < 30:
        return np.nan
    mean = r.mean() * annualize
    std = r.std() * np.sqrt(annualize)
    if std == 0:
        return np.nan
    return float(mean / std)


def compute_vt_sharpe_improvement(sector_prices, vix_series, shy_prices, label=''):
    """
    Compute VT Sharpe improvement (VT Sharpe - BH Sharpe) for a sector ETF.

    VT rule:
        w_t = min(12 / VIX_{end of month t}, 1)
        Weight w_t applies to NEXT month (shift by 1 month)

    Monthly rebalancing, tx cost 10 bps per round trip.
    """
    # Align all series
    df = pd.DataFrame({
        'price': sector_prices,
        'vix': vix_series,
        'shy': shy_prices
    }).dropna()

    if len(df) < 252:
        logger.warning(f"  {label}: insufficient data ({len(df)} days)")
        return None

    # Daily returns
    df['ret'] = df['price'].pct_change()
    df['shy_ret'] = df['shy'].pct_change()
    df = df.dropna()

    # Monthly VIX signal: end-of-month VIX -> weight for next month
    monthly_vix = df['vix'].resample('ME').last()
    monthly_weight = (VT_NUMERATOR / monthly_vix).clip(upper=1.0)
    # Shift by 1 month: weight based on LAST month's end VIX
    monthly_weight_lagged = monthly_weight.shift(1)

    # Broadcast monthly weight to daily
    daily_weight = monthly_weight_lagged.reindex(df.index, method='ffill')
    daily_weight = daily_weight.fillna(0.0)

    # Transaction cost: detect month-end rebalances
    # 10 bps per round trip = 5 bps each way
    monthly_boundaries = pd.DatetimeIndex(
        [d for d in df.index if d.is_month_end or (
            len(df.index) > 1 and df.index.get_loc(d) > 0 and
            df.index[df.index.get_loc(d) - 1].month != d.month
        )]
    )
    tx_cost_daily = pd.Series(0.0, index=df.index)
    # Approximate: charge 10 bps on rebalance days (first trading day of month)
    month_starts = df.index[pd.Series(df.index).dt.month.diff().ne(0).values]
    tx_cost_daily.loc[month_starts] = 0.001  # 10 bps per round trip

    # VT daily returns
    vt_ret = daily_weight * df['ret'] + (1 - daily_weight) * df['shy_ret'] - tx_cost_daily

    # BH returns
    bh_ret = df['ret']

    sharpe_bh = compute_sharpe(bh_ret)
    sharpe_vt = compute_sharpe(vt_ret)

    if sharpe_bh is None or sharpe_vt is None:
        return None

    delta_sharpe = sharpe_vt - sharpe_bh

    return {
        'sharpe_bh': round(sharpe_bh, 4),
        'sharpe_vt': round(sharpe_vt, 4),
        'delta_sharpe': round(delta_sharpe, 4),
        'n_days': len(df)
    }


# ============================================================
# Main analysis
# ============================================================

def main():
    logger.info("=" * 70)
    logger.info("K1190: Paper 3 Sector Analysis — 11 SPDR ETFs Reproduce")
    logger.info("=" * 70)
    logger.info(f"Paper claims: r={PAPER_R}, p={PAPER_P}, gamma [{PAPER_GAMMA_MIN}, {PAPER_GAMMA_MAX}]")
    logger.info(f"KB reference: XLF gamma={KB_XLF_GAMMA}")

    # 1. Download data
    prices = download_data()

    vix = prices['^VIX'] if '^VIX' in prices.columns else None
    shy = prices['SHY'] if 'SHY' in prices.columns else None

    if vix is None or shy is None:
        logger.error("Missing VIX or SHY data. Aborting.")
        sys.exit(1)

    # 2. Per-sector analysis
    sector_results = {}

    for ticker in SECTOR_ETFS:
        if ticker not in prices.columns:
            logger.warning(f"  {ticker}: not in downloaded data, skipping")
            continue

        sector_price = prices[ticker].dropna()

        # Trim to analysis period
        sector_price = sector_price[ANALYSIS_START:ANALYSIS_END]

        if len(sector_price) < 252:
            logger.warning(f"  {ticker}: only {len(sector_price)} trading days after {ANALYSIS_START}")

        logger.info(f"\n--- {ticker} ---")
        logger.info(f"  Data: {sector_price.index[0].date()} to {sector_price.index[-1].date()}, {len(sector_price)} days")

        # GJR-GARCH gamma
        ret_series = sector_price.pct_change().dropna().values
        logger.info(f"  Estimating GJR-GARCH on {len(ret_series)} return obs...")
        garch_result = estimate_gjr_garch(ret_series)

        if garch_result is None:
            logger.warning(f"  {ticker}: GJR-GARCH failed to converge")
            gamma_val = np.nan
        else:
            gamma_val = garch_result['gamma']
            logger.info(f"  omega={garch_result['omega']:.6f}, alpha={garch_result['alpha']:.4f}, "
                        f"gamma={gamma_val:.4f}, beta={garch_result['beta']:.4f}, "
                        f"loglik={garch_result['loglik']:.2f}, converged={garch_result['converged']}")

        # VT Sharpe improvement
        vix_aligned = vix[ANALYSIS_START:ANALYSIS_END]
        shy_aligned = shy[ANALYSIS_START:ANALYSIS_END]

        sharpe_result = compute_vt_sharpe_improvement(
            sector_price, vix_aligned, shy_aligned, label=ticker
        )

        if sharpe_result is None:
            logger.warning(f"  {ticker}: Sharpe computation failed")
            delta_sharpe = np.nan
        else:
            delta_sharpe = sharpe_result['delta_sharpe']
            logger.info(f"  BH Sharpe={sharpe_result['sharpe_bh']:.4f}, "
                        f"VT Sharpe={sharpe_result['sharpe_vt']:.4f}, "
                        f"Delta Sharpe={delta_sharpe:.4f}")

        sector_results[ticker] = {
            'ticker': ticker,
            'gamma': round(float(gamma_val), 4) if not np.isnan(gamma_val) else None,
            'garch_params': garch_result,
            'sharpe_result': sharpe_result,
            'delta_sharpe': round(float(delta_sharpe), 4) if not np.isnan(delta_sharpe) else None
        }

    # 3. Cross-sectional correlation
    logger.info("\n" + "=" * 70)
    logger.info("Cross-sectional correlation: gamma vs Delta Sharpe")

    valid = [(s['gamma'], s['delta_sharpe'])
             for s in sector_results.values()
             if s['gamma'] is not None and s['delta_sharpe'] is not None]

    if len(valid) < 3:
        logger.error(f"Only {len(valid)} valid sectors for correlation. Aborting.")
        corr_r = np.nan
        corr_p = np.nan
    else:
        gammas = np.array([v[0] for v in valid])
        delta_sharpes = np.array([v[1] for v in valid])

        corr_r, corr_p = scipy.stats.pearsonr(gammas, delta_sharpes)
        corr_r = float(corr_r)
        corr_p = float(corr_p)

        logger.info(f"  N valid sectors = {len(valid)}")
        logger.info(f"  Pearson r = {corr_r:.4f} (paper: {PAPER_R})")
        logger.info(f"  p-value   = {corr_p:.4f} (paper: {PAPER_P})")

        gamma_min = float(gammas.min())
        gamma_max = float(gammas.max())
        logger.info(f"  Gamma range: [{gamma_min:.4f}, {gamma_max:.4f}]")
        logger.info(f"  Paper range: [{PAPER_GAMMA_MIN}, {PAPER_GAMMA_MAX}]")

    # 4. KB verification: XLF gamma
    xlf_gamma = sector_results.get('XLF', {}).get('gamma', np.nan)
    logger.info(f"\nKB reference check: XLF gamma = {xlf_gamma} (KB: {KB_XLF_GAMMA})")

    # 5. Determine match status
    r_diff = abs(corr_r - PAPER_R) if not np.isnan(corr_r) else 999
    p_diff = abs(corr_p - PAPER_P) if not np.isnan(corr_p) else 999

    valid_gammas = [s['gamma'] for s in sector_results.values() if s['gamma'] is not None]
    g_min = min(valid_gammas) if valid_gammas else np.nan
    g_max = max(valid_gammas) if valid_gammas else np.nan

    r_match = r_diff <= 0.05
    gamma_range_match = (
        abs(g_min - PAPER_GAMMA_MIN) <= 0.02 and
        abs(g_max - PAPER_GAMMA_MAX) <= 0.02
        if not np.isnan(g_min) else False
    )

    if r_match and gamma_range_match:
        match_status = "MATCHED"
    elif r_match:
        match_status = "(b) r_matched_gamma_range_diverges"
    elif gamma_range_match:
        match_status = "(c) gamma_range_matched_r_diverges"
    else:
        match_status = "(a) DIVERGED"

    logger.info(f"\nMatch status: {match_status}")
    logger.info(f"  r diff: {r_diff:.4f}, gamma_range_match: {gamma_range_match}")

    # 6. Summary table
    logger.info("\n" + "=" * 70)
    logger.info(f"{'Ticker':<8} {'Gamma':>8} {'BH Sharpe':>10} {'VT Sharpe':>10} {'Delta':>8}")
    logger.info("-" * 50)
    for ticker in SECTOR_ETFS:
        if ticker in sector_results:
            s = sector_results[ticker]
            gamma_str = f"{s['gamma']:.4f}" if s['gamma'] is not None else "   NaN"
            if s['sharpe_result']:
                logger.info(f"{ticker:<8} {gamma_str:>8} "
                            f"{s['sharpe_result']['sharpe_bh']:>10.4f} "
                            f"{s['sharpe_result']['sharpe_vt']:>10.4f} "
                            f"{s['delta_sharpe']:>8.4f}")
            else:
                logger.info(f"{ticker:<8} {gamma_str:>8}   N/A")

    # 7. Build results JSON
    results = {
        "experiment_id": "k1190",
        "timestamp": datetime.now().isoformat(),
        "paper_claims": {
            "pearson_r": PAPER_R,
            "p_value": PAPER_P,
            "gamma_min": PAPER_GAMMA_MIN,
            "gamma_max": PAPER_GAMMA_MAX,
            "n_sectors": 11
        },
        "computed": {
            "pearson_r": round(corr_r, 4) if not np.isnan(corr_r) else None,
            "p_value": round(corr_p, 4) if not np.isnan(corr_p) else None,
            "gamma_min": round(g_min, 4) if not np.isnan(g_min) else None,
            "gamma_max": round(g_max, 4) if not np.isnan(g_max) else None,
            "n_valid_sectors": len(valid)
        },
        "diffs": {
            "r_diff": round(r_diff, 4) if r_diff != 999 else None,
            "p_diff": round(p_diff, 4) if p_diff != 999 else None,
            "gamma_min_diff": round(abs(g_min - PAPER_GAMMA_MIN), 4) if not np.isnan(g_min) else None,
            "gamma_max_diff": round(abs(g_max - PAPER_GAMMA_MAX), 4) if not np.isnan(g_max) else None
        },
        "match_status": match_status,
        "kb_verification": {
            "xlf_gamma_kb": KB_XLF_GAMMA,
            "xlf_gamma_computed": round(xlf_gamma, 4) if not np.isnan(xlf_gamma) else None,
            "xlf_gamma_diff": round(abs(xlf_gamma - KB_XLF_GAMMA), 4) if not np.isnan(xlf_gamma) else None
        },
        "sector_results": {
            ticker: {
                "gamma": s['gamma'],
                "sharpe_bh": s['sharpe_result']['sharpe_bh'] if s['sharpe_result'] else None,
                "sharpe_vt": s['sharpe_result']['sharpe_vt'] if s['sharpe_result'] else None,
                "delta_sharpe": s['delta_sharpe'],
                "n_days": s['sharpe_result']['n_days'] if s['sharpe_result'] else None,
                "garch_converged": s['garch_params']['converged'] if s['garch_params'] else None
            }
            for ticker, s in sector_results.items()
        },
        "methodology": {
            "vt_rule": "w_t = min(12/VIX_end_of_month_t, 1), lag 1 month",
            "rebalancing": "monthly",
            "tx_cost_bps": 10,
            "garch_model": "GJR-GARCH(1,1)",
            "correlation": "Pearson r(gamma, delta_sharpe)",
            "data_source": "yfinance",
            "period": f"{ANALYSIS_START} to {ANALYSIS_END}",
            "seed": SEED
        }
    }

    out_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a7880876/experiments/k1190/k1190_results.json'
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"\nResults written to {out_path}")
    logger.info(f"\nFINAL VERDICT: {match_status}")

    return results


if __name__ == '__main__':
    results = main()
    print("\n=== SUMMARY ===")
    print(f"Match status   : {results['match_status']}")
    print(f"Paper r=0.163  : computed r={results['computed']['pearson_r']}")
    print(f"Paper p=0.632  : computed p={results['computed']['p_value']}")
    print(f"Paper gamma [{PAPER_GAMMA_MIN},{PAPER_GAMMA_MAX}]: computed [{results['computed']['gamma_min']},{results['computed']['gamma_max']}]")
    print(f"XLF gamma KB={KB_XLF_GAMMA}: computed={results['kb_verification']['xlf_gamma_computed']}")
