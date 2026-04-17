#!/usr/bin/env python3
"""
K1177: Paper 3 Table 3 TSMOM Hedge SPY — Canonical Replication
==============================================================

OBJECTIVE:
    Precisely replicate the paper's Table 3 setup to determine whether:
    (a) Paper values (SPY Hedged VT Sharpe=0.737, MDD retention=93%) are correct,
        meaning K898 used a different construction; or
    (b) K898 values (Sharpe=0.848, MDD retention=107%) are canonical,
        meaning the paper has an errata.

KEY DIFFERENCES FROM K898:
    1. VT rebalancing: MONTHLY (paper text line 98: "Rebalancing is monthly,
       with transaction costs of 10 basis points per round trip"), not daily
    2. Transaction costs: 10 bps per round trip (paper text), not 0
    3. TSMOM hedge factor: orthogonalized TSMOM^perp = TSMOM - beta_MKT * MKT
       (paper Eq. 3 + Table 3 notes), not raw TSMOM
    4. Sample period: strictly 2005-01-03 to 2026-03-31 (paper Table 3 notes:
       "Full-sample results over 2005-2026")

PAPER SETUP (from main.tex):
    - VT: w_t = min(12/VIX_end_of_month_{t-1}, 1), monthly rebalancing
    - Cash proxy: SHY
    - Tx cost: 10 bps per round trip applied to monthly weight changes
    - TSMOM hedge: rolling 252-day regression of VT on TSMOM^perp
    - TSMOM^perp = TSMOM - beta_MKT_fullsample * MKT
    - PureVT = VT - beta_TSMOM_rolling * TSMOM^perp
    - Asset-specific TSMOM: sign(cumret_{t-252:t-1}) * r_t

DATA SOURCES:
    yfinance: SPY, GLD, DIA, QQQ, IWM, ^VIX, SHY
    Period: 2004-01-01 to 2026-04-01 (extra lead for TSMOM lookback)
    Analysis window: 2005-01-03 to 2026-03-31

REFERENCES:
    - Hood & Malik (2025) JBF — VT alpha absorption
    - Moskowitz, Ooi, Pedersen (2012) JFE — TSMOM definition
    - Harvey (2016) RFS — t>3.0 threshold
    - Paper main.tex lines 94-139 (equations 1-6)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# ============================================================
# Configuration — matching paper exactly
# ============================================================
START_DATE = '2003-12-01'   # Extra lead for monthly VIX + 252-day TSMOM lookback
END_DATE = '2026-04-01'
ANALYSIS_START = pd.Timestamp('2005-01-03')  # Paper Table 3 notes: "2005-2026"
VT_NUMERATOR = 12.0
TSMOM_LOOKBACK = 252        # Paper: 252-day lookback (daily)
BOOTSTRAP_REPS = 10_000
BOOTSTRAP_BLOCK = 252       # 1-year block
ANNUALIZE = 252
TX_COST_BPS = 10.0          # Paper: 10 bps per round trip (monthly rebalancing)
TX_COST_ONEWAY = TX_COST_BPS / 2 / 10000  # 5 bps one-way (round trip = 10 bps)
SEED = 42


def download_data():
    """Download price data from yfinance."""
    tickers = ['SPY', 'GLD', 'DIA', 'QQQ', 'IWM', '^VIX', 'SHY']
    print(f"Downloading {tickers} from {START_DATE} to {END_DATE}...")
    raw = yf.download(tickers, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw['Close']
    else:
        close = raw

    close = close.rename(columns={'^VIX': 'VIX'})
    close = close.ffill()

    print(f"Data range: {close.index[0].date()} to {close.index[-1].date()}")
    print(f"Shape: {close.shape}")
    for col in close.columns:
        first_valid = close[col].first_valid_index()
        print(f"  {col}: starts {first_valid.date() if first_valid else 'N/A'}")

    return close


def compute_daily_returns(close):
    """Compute daily simple returns."""
    ret = close.pct_change()
    return ret


def get_monthly_vt_weights(vix_daily):
    """
    Compute VT weights using MONTHLY VIX signal with lag.

    Paper: "VIX at the end of month t determines the allocation for month t+1.
            Rebalancing is monthly."

    Implementation:
    1. Resample VIX to month-end
    2. Compute w = min(12/VIX_month_end, 1)
    3. Shift by 1 month (lag — no lookahead)
    4. Merge back to daily, forward-fill within each month

    Returns: daily series of VT weights (constant within each month)
    """
    # Month-end VIX
    vix_monthly = vix_daily.resample('ME').last()
    w_monthly = (VT_NUMERATOR / vix_monthly).clip(upper=1.0)

    # Lag by 1 month: weight for month t+1 is determined by VIX at end of month t
    w_monthly_lagged = w_monthly.shift(1)

    # Reindex to daily and forward fill
    # Create daily index covering the full period
    daily_idx = vix_daily.index
    w_daily = w_monthly_lagged.reindex(daily_idx, method='ffill')

    return w_daily


def compute_monthly_tx_costs(w_daily):
    """
    Compute monthly transaction costs: 10 bps per round trip.

    Cost is incurred only at month-end rebalancing dates.
    Round trip = buy + sell = 10 bps, so 5 bps one-way.
    But for a simple one-way rebalance: |Δw| * 10 bps.

    Paper: "10 basis points per round trip" = cost per weight unit changed.
    """
    # Find dates where weight changes (month boundaries)
    w_changed = w_daily.diff().abs()

    # Apply 10 bps per unit change (round trip interpretation: 10 bps total)
    # This means for each unit of weight changed: 10 bps cost
    costs = w_changed * (TX_COST_BPS / 10000)
    return costs.fillna(0)


def build_monthly_vt_returns(asset_ret, shy_ret, vix_daily, analysis_start):
    """
    Build VT returns using monthly rebalancing with 10 bps tx costs.

    VT_t = w_t * asset_ret_t + (1-w_t) * shy_ret_t - tx_cost_t

    w_t is constant within each month, determined by end-of-prior-month VIX.
    """
    w_daily = get_monthly_vt_weights(vix_daily)

    common_idx = (asset_ret.dropna().index
                  .intersection(shy_ret.dropna().index)
                  .intersection(w_daily.dropna().index))
    common_idx = common_idx[common_idx >= analysis_start]

    r_asset = asset_ret.loc[common_idx]
    r_shy = shy_ret.loc[common_idx]
    w = w_daily.loc[common_idx]

    # B&H
    bh = r_asset.copy()

    # VT with SHY remainder
    vt = w * r_asset + (1 - w) * r_shy

    # Transaction costs at rebalancing dates
    tx = compute_monthly_tx_costs(w)
    tx = tx.loc[common_idx]
    vt = vt - tx

    return bh, vt, w, common_idx


def build_5050_monthly_vt_returns(spy_ret, gld_ret, shy_ret, vix_daily, analysis_start):
    """
    Build 50/50 SPY/GLD VT returns with monthly rebalancing.

    B&H: 0.5*SPY + 0.5*GLD (continuously rebalanced daily approximation)
    VT: w * blend + (1-w) * SHY - tx_costs (monthly w)
    """
    w_daily = get_monthly_vt_weights(vix_daily)

    common_idx = (spy_ret.dropna().index
                  .intersection(gld_ret.dropna().index)
                  .intersection(shy_ret.dropna().index)
                  .intersection(w_daily.dropna().index))
    common_idx = common_idx[common_idx >= analysis_start]

    r_spy = spy_ret.loc[common_idx]
    r_gld = gld_ret.loc[common_idx]
    r_shy = shy_ret.loc[common_idx]
    w = w_daily.loc[common_idx]

    # B&H blend (50/50)
    bh = 0.5 * r_spy + 0.5 * r_gld

    # VT on blend
    vt = w * bh + (1 - w) * r_shy

    # Transaction costs
    tx = compute_monthly_tx_costs(w)
    tx = tx.loc[common_idx]
    vt = vt - tx

    return bh, vt, w, common_idx


def compute_tsmom_factor(asset_returns, lookback=TSMOM_LOOKBACK):
    """
    TSMOM factor: sign(cumulative return over past 'lookback' days) * today's return.

    TSMOM_t = sign(sum(log(1+r_{t-lookback:t-1}))) * r_t

    Signal (sign) is from t-lookback to t-1 (no lookahead).
    """
    log_ret = np.log1p(asset_returns)
    cum_log_ret_lagged = log_ret.rolling(lookback).sum().shift(1)  # shift ensures no lookahead
    signal = np.sign(cum_log_ret_lagged)
    factor = signal * asset_returns
    return factor


def orthogonalize_tsmom_to_mkt(tsmom_factor, mkt_return):
    """
    Orthogonalize TSMOM to market factor (full-sample).

    Paper Eq. 3: TSMOM^perp = TSMOM - beta_MKT * MKT
    beta_MKT estimated from full-sample OLS regression.

    This removes the market co-movement from TSMOM to avoid
    correlated-regressor bias (paper line 109).
    """
    common = tsmom_factor.dropna().index.intersection(mkt_return.dropna().index)
    tsmom = tsmom_factor.loc[common]
    mkt = mkt_return.loc[common]

    # Full-sample OLS: TSMOM = alpha + beta_MKT * MKT + eps
    beta_mkt = np.cov(tsmom, mkt)[0, 1] / np.var(mkt)
    alpha_mkt = tsmom.mean() - beta_mkt * mkt.mean()
    tsmom_perp = tsmom - beta_mkt * mkt  # orthogonalized (alpha absorbed in residual)

    return tsmom_perp, beta_mkt, alpha_mkt


def compute_hedged_vt_orthogonalized(vt_returns, asset_returns, mkt_returns=None,
                                      lookback=TSMOM_LOOKBACK):
    """
    TSMOM-Hedged VT using ORTHOGONALIZED TSMOM factor.

    Paper setup:
      1. Compute raw TSMOM_t = sign(cumret_{t-252:t-1}) * r_t
      2. Orthogonalize: TSMOM^perp = TSMOM - beta_MKT_fullsample * MKT
         (paper Eq. 3 + Table 3 notes "TSMOM-Hedged VT removes TSMOM exposure
          via a rolling 252-day regression")
      3. Rolling 252-day regression: VT_t = a + b(t) * TSMOM^perp_t + eps
      4. PureVT_t = VT_t - b(t) * TSMOM^perp_t
         (b(t) lagged by 1 day: estimated at t-1, applied at t)

    Note: Paper's Eq. 6 writes TSMOM_t (not TSMOM^perp_t) in the hedge formula,
    but Table 3 notes reference "TSMOM exposure via rolling 252-day regression"
    which matches the M2 factor (TSMOM^perp). We implement using TSMOM^perp
    (consistent with the full paper methodology section) and also provide
    raw-TSMOM version for comparison.
    """
    if mkt_returns is None:
        mkt_returns = asset_returns  # Fallback: use asset return as market proxy

    tsmom_raw = compute_tsmom_factor(asset_returns, lookback)

    # Orthogonalize to market factor
    common_for_orth = (tsmom_raw.dropna().index
                       .intersection(mkt_returns.dropna().index)
                       .intersection(vt_returns.dropna().index))
    tsmom_perp, beta_mkt, alpha_mkt = orthogonalize_tsmom_to_mkt(
        tsmom_raw.loc[common_for_orth],
        mkt_returns.loc[common_for_orth]
    )

    common_idx = vt_returns.dropna().index.intersection(tsmom_perp.dropna().index)
    vt = vt_returns.loc[common_idx]
    tsmom_f = tsmom_perp.loc[common_idx]

    # Rolling 252-day OLS of VT on TSMOM^perp
    rolling_cov = vt.rolling(lookback).cov(tsmom_f)
    rolling_var = tsmom_f.rolling(lookback).var()
    b_tsmom = (rolling_cov / rolling_var).replace([np.inf, -np.inf], np.nan)

    # Lag beta by 1 day (estimated at t-1, applied at t) — no lookahead
    # Paper does NOT constrain beta (unlike K898 which constrained to [0, 0.5])
    b_tsmom_lagged = b_tsmom.shift(1).fillna(0)

    # PureVT = VT - b * TSMOM^perp
    hedged = vt - b_tsmom_lagged * tsmom_f
    hedged = hedged.dropna()

    return hedged, b_tsmom_lagged, tsmom_perp, beta_mkt


def compute_hedged_vt_raw_tsmom(vt_returns, asset_returns, lookback=TSMOM_LOOKBACK):
    """
    TSMOM-Hedged VT using RAW TSMOM factor (Eq. 6 literal interpretation).

    This version follows Eq. 6 literally: TSMOM_t (not TSMOM^perp_t).
    Used for sensitivity comparison.
    """
    tsmom_raw = compute_tsmom_factor(asset_returns, lookback)

    common_idx = vt_returns.dropna().index.intersection(tsmom_raw.dropna().index)
    vt = vt_returns.loc[common_idx]
    tsmom_f = tsmom_raw.loc[common_idx]

    rolling_cov = vt.rolling(lookback).cov(tsmom_f)
    rolling_var = tsmom_f.rolling(lookback).var()
    b_tsmom = (rolling_cov / rolling_var).replace([np.inf, -np.inf], np.nan)

    # Lag by 1 day, no constraint (paper does not mention beta constraint)
    b_tsmom_lagged = b_tsmom.shift(1).fillna(0)

    # PureVT = VT - b * TSMOM
    hedged = vt - b_tsmom_lagged * tsmom_f
    hedged = hedged.dropna()

    return hedged, b_tsmom_lagged, tsmom_f


def compute_pure_tsmom(asset_returns, lookback=TSMOM_LOOKBACK):
    """
    Pure TSMOM strategy: long if past return positive, short if negative.

    Long/short version: TSMOM_t = sign(cumret_{t-252:t-1}) * r_t
    """
    log_ret = np.log1p(asset_returns)
    cum_log_ret_lagged = log_ret.rolling(lookback).sum().shift(1)
    signal = np.sign(cum_log_ret_lagged)
    tsmom_ret = signal * asset_returns
    return tsmom_ret.dropna()


def compute_sharpe(returns):
    """Annualized Sharpe ratio."""
    r = returns.dropna()
    if len(r) < 10 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(ANNUALIZE))


def compute_mdd(returns):
    """Maximum drawdown (negative number)."""
    wealth = (1 + returns.dropna()).cumprod()
    peak = wealth.cummax()
    dd = (wealth - peak) / peak
    return float(dd.min())


def compute_calmar(returns):
    """Calmar = annualized return / |MDD|."""
    r = returns.dropna()
    ann_ret = float(r.mean() * ANNUALIZE)
    mdd = compute_mdd(r)
    if mdd == 0:
        return 0.0
    return ann_ret / abs(mdd)


def compute_metrics(returns, name=''):
    """Compute all metrics for a strategy."""
    r = returns.dropna()
    if len(r) < 10:
        return {'sharpe': 0, 'mdd_pct': 0, 'calmar': 0, 'n_obs': len(r), 'name': name}

    sharpe = compute_sharpe(r)
    mdd = compute_mdd(r)
    calmar = compute_calmar(r)
    ann_ret = float(r.mean() * ANNUALIZE)
    ann_vol = float(r.std() * np.sqrt(ANNUALIZE))

    return {
        'name': name,
        'sharpe': round(sharpe, 3),
        'mdd_pct': round(mdd * 100, 2),
        'calmar': round(calmar, 3),
        'ann_return_pct': round(ann_ret * 100, 2),
        'ann_vol_pct': round(ann_vol * 100, 2),
        'n_obs': len(r),
        'start': str(r.index[0].date()),
        'end': str(r.index[-1].date()),
    }


def block_bootstrap_mdd_retention(bh_returns, vt_returns, hedged_returns,
                                   n_reps=BOOTSTRAP_REPS, block_size=BOOTSTRAP_BLOCK,
                                   seed=SEED):
    """
    Block bootstrap 90% CI for MDD retention.

    MDD Retention = (MDD_BH - MDD_Hedged) / (MDD_BH - MDD_VT)

    Positive retention < 100%: hedged VT retains some but not all of VT's MDD protection.
    Retention > 100%: hedged VT IMPROVES MDD beyond VT (unusual, suggests hedge adds value).
    """
    rng = np.random.RandomState(seed)

    common_idx = (bh_returns.dropna().index
                  .intersection(vt_returns.dropna().index)
                  .intersection(hedged_returns.dropna().index))

    bh = bh_returns.loc[common_idx].values
    vt = vt_returns.loc[common_idx].values
    hedged = hedged_returns.loc[common_idx].values
    n = len(bh)

    n_blocks = max(1, n // block_size)
    retentions = []

    for _ in range(n_reps):
        starts = rng.randint(0, n - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]

        def _mdd(rets):
            w = np.cumprod(1 + rets)
            peak = np.maximum.accumulate(w)
            return float(np.min(w / peak - 1))

        bh_mdd = _mdd(bh[indices])
        vt_mdd = _mdd(vt[indices])
        hedged_mdd = _mdd(hedged[indices])

        # Protection = improvement vs B&H (positive when VT/Hedged < B&H in MDD)
        vt_protection = bh_mdd - vt_mdd       # negative - negative = positive if VT has less MDD
        hedged_protection = bh_mdd - hedged_mdd

        if abs(vt_protection) > 1e-10:
            retention = hedged_protection / vt_protection
            if -1.0 <= retention <= 3.0:
                retentions.append(retention)

    retentions = np.array(retentions)
    return {
        'point_estimate_pct': round(float(np.median(retentions) * 100), 1),
        'mean_pct': round(float(np.mean(retentions) * 100), 1),
        'ci_lower_5_pct': round(float(np.percentile(retentions, 5) * 100), 1),
        'ci_upper_95_pct': round(float(np.percentile(retentions, 95) * 100), 1),
        'pvalue_le_80': round(float(np.mean(retentions <= 0.80)), 4),
        'reject_80_at_5pct': bool(np.mean(retentions <= 0.80) < 0.05),
        'n_valid': len(retentions),
    }


def analyze_asset_canonical(ret_df, vix_daily, shy_ret, asset, analysis_start,
                              use_orthogonalized_tsmom=True):
    """
    Full canonical analysis for a single equity asset.

    Canonical = monthly VT rebalancing + 10 bps tx costs + orthogonalized TSMOM hedge.
    """
    print(f"\n{'='*60}")
    print(f"Analyzing: {asset} [canonical: monthly VT, 10bps, orth-TSMOM]")
    print(f"{'='*60}")

    asset_ret = ret_df[asset]
    bh, vt, w, common_idx = build_monthly_vt_returns(asset_ret, shy_ret, vix_daily, analysis_start)

    # --- Canonical hedge: orthogonalized TSMOM ---
    if use_orthogonalized_tsmom:
        hedged_vt, beta, tsmom_used, beta_mkt = compute_hedged_vt_orthogonalized(
            vt, bh, mkt_returns=bh, lookback=TSMOM_LOOKBACK
        )
        hedge_method = 'orthogonalized_tsmom_perp'
    else:
        hedged_vt, beta, tsmom_used = compute_hedged_vt_raw_tsmom(
            vt, bh, lookback=TSMOM_LOOKBACK
        )
        hedge_method = 'raw_tsmom'
        beta_mkt = None

    # --- Also compute raw-TSMOM hedge for sensitivity ---
    hedged_vt_raw, beta_raw, tsmom_raw_f = compute_hedged_vt_raw_tsmom(
        vt, bh, lookback=TSMOM_LOOKBACK
    )

    # Pure TSMOM (long/short)
    pure_tsmom = compute_pure_tsmom(bh, TSMOM_LOOKBACK)

    # Align all series to common index
    common = (bh.index
               .intersection(vt.index)
               .intersection(hedged_vt.index)
               .intersection(hedged_vt_raw.index)
               .intersection(pure_tsmom.index))

    bh_a = bh.loc[common]
    vt_a = vt.loc[common]
    hedged_a = hedged_vt.loc[common]
    hedged_raw_a = hedged_vt_raw.loc[common]
    tsmom_a = pure_tsmom.loc[common]

    # Metrics
    bh_m = compute_metrics(bh_a, f'{asset} B&H')
    vt_m = compute_metrics(vt_a, f'{asset} 12/VIX VT monthly')
    hedged_m = compute_metrics(hedged_a, f'{asset} Hedged VT (orth TSMOM)')
    hedged_raw_m = compute_metrics(hedged_raw_a, f'{asset} Hedged VT (raw TSMOM)')
    tsmom_m = compute_metrics(tsmom_a, f'{asset} Pure TSMOM')

    # Decomposition
    delta_sharpe = round(vt_m['sharpe'] - bh_m['sharpe'], 3)

    # For CANONICAL hedged version
    delta_sharpe_lost = round(vt_m['sharpe'] - hedged_m['sharpe'], 3)
    pct_tsmom = round((delta_sharpe_lost / delta_sharpe * 100) if abs(delta_sharpe) > 0.001 else 0, 1)

    # MDD (in percentage points, values are negative so need care)
    bh_mdd = bh_m['mdd_pct']
    vt_mdd = vt_m['mdd_pct']
    hedged_mdd = hedged_m['mdd_pct']

    # MDD protection = how much VT reduces MDD vs B&H
    # e.g., BH=-55.2, VT=-24.7 => protection = (-24.7) - (-55.2) = +30.5 pp improvement
    mdd_protection_pp = round(vt_mdd - bh_mdd, 1)  # negative minus more-negative = positive

    # MDD retained by hedging = how much of VT's protection survives
    mdd_retained_pp = round(hedged_mdd - bh_mdd, 1)  # same direction

    # Retention % = mdd_retained / mdd_protection
    if abs(mdd_protection_pp) > 0.1:
        mdd_retention_pct = round(mdd_retained_pp / mdd_protection_pp * 100, 0)
    else:
        mdd_retention_pct = 0.0

    # Bootstrap
    boot = block_bootstrap_mdd_retention(bh_a, vt_a, hedged_a)

    # Avg beta
    beta_valid = beta.loc[common].dropna()
    avg_beta = float(beta_valid.mean()) if len(beta_valid) > 0 else 0

    result = {
        'asset': asset,
        'hedge_method': hedge_method,
        'bh': bh_m,
        'vt': vt_m,
        'hedged_vt': hedged_m,
        'hedged_vt_raw': hedged_raw_m,
        'pure_tsmom': tsmom_m,
        'avg_tsmom_beta': round(avg_beta, 4),
        'beta_mkt_fullsample': round(float(beta_mkt), 4) if beta_mkt is not None else None,
        'decomposition': {
            'delta_sharpe': delta_sharpe,
            'delta_sharpe_lost_to_tsmom': delta_sharpe_lost,
            'pct_sharpe_from_tsmom': pct_tsmom,
            'mdd_protection_pp': mdd_protection_pp,
            'mdd_protection_retained_pp': mdd_retained_pp,
            'mdd_retention_pct': float(mdd_retention_pct),
        },
        'bootstrap_mdd_retention': boot,
    }

    # Print summary
    print(f"  B&H:                Sharpe={bh_m['sharpe']:.3f}, MDD={bh_m['mdd_pct']:.1f}%")
    print(f"  12/VIX VT monthly:  Sharpe={vt_m['sharpe']:.3f}, MDD={vt_m['mdd_pct']:.1f}%")
    print(f"  Hedged VT (orth):   Sharpe={hedged_m['sharpe']:.3f}, MDD={hedged_m['mdd_pct']:.1f}%")
    print(f"  Hedged VT (raw):    Sharpe={hedged_raw_m['sharpe']:.3f}, MDD={hedged_raw_m['mdd_pct']:.1f}%")
    print(f"  Pure TSMOM:         Sharpe={tsmom_m['sharpe']:.3f}, MDD={tsmom_m['mdd_pct']:.1f}%")
    print(f"  Avg TSMOM beta:     {avg_beta:.4f}")
    print(f"  ΔSharpe (VT-BH):    {delta_sharpe:+.3f}")
    print(f"  ΔSharpe lost:       {delta_sharpe_lost:+.3f} ({pct_tsmom:.1f}%)")
    print(f"  MDD protection:     {mdd_protection_pp:.1f} pp")
    print(f"  MDD retained:       {mdd_retained_pp:.1f} pp ({mdd_retention_pct:.0f}%)")
    print(f"  Bootstrap 90% CI:   [{boot['ci_lower_5_pct']:.1f}%, {boot['ci_upper_95_pct']:.1f}%]")

    return result


def analyze_5050_canonical(ret_df, vix_daily, shy_ret, analysis_start):
    """Full canonical analysis for 50/50 SPY/GLD blend."""
    print(f"\n{'='*60}")
    print(f"Analyzing: 50/50 SPY/GLD [canonical: monthly VT, 10bps, orth-TSMOM]")
    print(f"{'='*60}")

    spy_ret = ret_df['SPY']
    gld_ret = ret_df['GLD']
    bh, vt, w, common_idx = build_5050_monthly_vt_returns(
        spy_ret, gld_ret, shy_ret, vix_daily, analysis_start)

    hedged_vt, beta, tsmom_used, beta_mkt = compute_hedged_vt_orthogonalized(
        vt, bh, mkt_returns=bh, lookback=TSMOM_LOOKBACK
    )
    hedged_vt_raw, beta_raw, tsmom_raw_f = compute_hedged_vt_raw_tsmom(
        vt, bh, lookback=TSMOM_LOOKBACK
    )
    pure_tsmom = compute_pure_tsmom(bh, TSMOM_LOOKBACK)

    common = (bh.index
               .intersection(vt.index)
               .intersection(hedged_vt.index)
               .intersection(hedged_vt_raw.index)
               .intersection(pure_tsmom.index))

    bh_a = bh.loc[common]
    vt_a = vt.loc[common]
    hedged_a = hedged_vt.loc[common]
    hedged_raw_a = hedged_vt_raw.loc[common]
    tsmom_a = pure_tsmom.loc[common]

    bh_m = compute_metrics(bh_a, '50/50 B&H')
    vt_m = compute_metrics(vt_a, '50/50 12/VIX VT monthly')
    hedged_m = compute_metrics(hedged_a, '50/50 Hedged VT (orth TSMOM)')
    hedged_raw_m = compute_metrics(hedged_raw_a, '50/50 Hedged VT (raw TSMOM)')
    tsmom_m = compute_metrics(tsmom_a, '50/50 Pure TSMOM')

    delta_sharpe = round(vt_m['sharpe'] - bh_m['sharpe'], 3)
    delta_sharpe_lost = round(vt_m['sharpe'] - hedged_m['sharpe'], 3)
    pct_tsmom = round((delta_sharpe_lost / delta_sharpe * 100) if abs(delta_sharpe) > 0.001 else 0, 1)

    bh_mdd = bh_m['mdd_pct']
    vt_mdd = vt_m['mdd_pct']
    hedged_mdd = hedged_m['mdd_pct']
    mdd_protection_pp = round(vt_mdd - bh_mdd, 1)
    mdd_retained_pp = round(hedged_mdd - bh_mdd, 1)
    mdd_retention_pct = round(mdd_retained_pp / mdd_protection_pp * 100, 0) if abs(mdd_protection_pp) > 0.1 else 0.0

    boot = block_bootstrap_mdd_retention(bh_a, vt_a, hedged_a)

    beta_valid = beta.loc[common].dropna()
    avg_beta = float(beta_valid.mean()) if len(beta_valid) > 0 else 0

    result = {
        'asset': '50/50 SPY/GLD',
        'hedge_method': 'orthogonalized_tsmom_perp',
        'bh': bh_m,
        'vt': vt_m,
        'hedged_vt': hedged_m,
        'hedged_vt_raw': hedged_raw_m,
        'pure_tsmom': tsmom_m,
        'avg_tsmom_beta': round(avg_beta, 4),
        'beta_mkt_fullsample': round(float(beta_mkt), 4) if beta_mkt is not None else None,
        'decomposition': {
            'delta_sharpe': delta_sharpe,
            'delta_sharpe_lost_to_tsmom': delta_sharpe_lost,
            'pct_sharpe_from_tsmom': pct_tsmom,
            'mdd_protection_pp': mdd_protection_pp,
            'mdd_protection_retained_pp': mdd_retained_pp,
            'mdd_retention_pct': float(mdd_retention_pct),
        },
        'bootstrap_mdd_retention': boot,
    }

    print(f"  B&H:                Sharpe={bh_m['sharpe']:.3f}, MDD={bh_m['mdd_pct']:.1f}%")
    print(f"  12/VIX VT monthly:  Sharpe={vt_m['sharpe']:.3f}, MDD={vt_m['mdd_pct']:.1f}%")
    print(f"  Hedged VT (orth):   Sharpe={hedged_m['sharpe']:.3f}, MDD={hedged_m['mdd_pct']:.1f}%")
    print(f"  Hedged VT (raw):    Sharpe={hedged_raw_m['sharpe']:.3f}, MDD={hedged_raw_m['mdd_pct']:.1f}%")
    print(f"  Pure TSMOM:         Sharpe={tsmom_m['sharpe']:.3f}, MDD={tsmom_m['mdd_pct']:.1f}%")
    print(f"  ΔSharpe (VT-BH):    {delta_sharpe:+.3f}")
    print(f"  ΔSharpe lost:       {delta_sharpe_lost:+.3f} ({pct_tsmom:.1f}%)")
    print(f"  MDD protection:     {mdd_protection_pp:.1f} pp")
    print(f"  MDD retained:       {mdd_retained_pp:.1f} pp ({mdd_retention_pct:.0f}%)")
    print(f"  Bootstrap 90% CI:   [{boot['ci_lower_5_pct']:.1f}%, {boot['ci_upper_95_pct']:.1f}%]")

    return result


def main():
    print("=" * 70)
    print("K1177: Paper 3 Table 3 TSMOM Hedge — Canonical Replication")
    print("=" * 70)
    print("OBJECTIVE: Determine canonical paper numbers vs K898 divergence")
    print()
    print("KEY DIFFERENCES vs K898:")
    print("  1. VT rebalancing: MONTHLY (not daily)")
    print("  2. Tx costs: 10 bps per round trip (not 0)")
    print("  3. TSMOM hedge: orthogonalized TSMOM^perp (not raw TSMOM)")
    print("  4. Beta constraint: NONE (K898 constrains [0, 0.5])")
    print()
    print(f"Analysis period: {ANALYSIS_START.date()} to 2026-03-31")
    print(f"TSMOM lookback: {TSMOM_LOOKBACK} days")
    print(f"Bootstrap: {BOOTSTRAP_REPS} reps, block={BOOTSTRAP_BLOCK}")
    print(f"Seed: {SEED}")

    # Download data
    close = download_data()
    ret_df = compute_daily_returns(close)
    vix_daily = close['VIX']
    shy_ret = ret_df['SHY']

    all_results = {}

    # 1. SPY — primary asset in Table 3
    all_results['SPY'] = analyze_asset_canonical(
        ret_df, vix_daily, shy_ret, 'SPY', ANALYSIS_START
    )

    # 2. 50/50 SPY/GLD blend
    all_results['50/50'] = analyze_5050_canonical(
        ret_df, vix_daily, shy_ret, ANALYSIS_START
    )

    # 3. DIA, QQQ, IWM
    for asset in ['DIA', 'QQQ', 'IWM']:
        all_results[asset] = analyze_asset_canonical(
            ret_df, vix_daily, shy_ret, asset, ANALYSIS_START
        )

    # ============================================================
    # Paper comparison
    # ============================================================
    paper_table3 = {
        'SPY': {
            'bh_sharpe': 0.611, 'vt_sharpe': 0.797, 'hedged_sharpe': 0.737,
            'bh_mdd': -55.2, 'vt_mdd': -24.7, 'hedged_mdd': -26.9,
            'tsmom_sharpe': 0.172, 'tsmom_mdd': -27.5,
            'mdd_retention': 93,
            'delta_sharpe': 0.186, 'delta_sharpe_lost': 0.060,
        },
        '50/50': {
            'bh_sharpe': 0.865, 'vt_sharpe': 0.982, 'hedged_sharpe': 0.937,
            'bh_mdd': -32.5, 'vt_mdd': -12.4, 'hedged_mdd': -13.1,
            'tsmom_sharpe': 0.232, 'tsmom_mdd': -31.8,
            'mdd_retention': 96,
            'delta_sharpe': 0.117, 'delta_sharpe_lost': 0.045,
        },
    }
    paper_mdd_retention = {'SPY': 93, '50/50': 96, 'DIA': 91, 'QQQ': 90, 'IWM': 97}

    k898_table3 = {
        'SPY': {
            'bh_sharpe': 0.616, 'vt_sharpe': 0.805, 'hedged_sharpe': 0.848,
            'bh_mdd': -55.2, 'vt_mdd': -24.7, 'hedged_mdd': -22.5,
            'tsmom_sharpe': 0.242, 'tsmom_mdd': -51.4,
            'mdd_retention': 107,
        },
        '50/50': {
            'bh_sharpe': 0.878, 'vt_sharpe': 0.998, 'hedged_sharpe': 0.830,
            'bh_mdd': -32.5, 'vt_mdd': -12.3, 'hedged_mdd': -13.3,
            'tsmom_sharpe': 0.232, 'tsmom_mdd': None,
            'mdd_retention': 110,
        },
    }

    print("\n" + "=" * 80)
    print("PAPER vs K1177 vs K898 COMPARISON")
    print("=" * 80)

    for key in ['SPY', '50/50']:
        r = all_results[key]
        pv = paper_table3[key]
        kv = k898_table3[key]

        print(f"\n--- {key} ---")
        print(f"{'Metric':<22} {'Paper':>8} {'K1177':>8} {'K898':>8} {'K1177-Paper':>12} {'K1177-K898':>12}")
        print("-" * 75)

        def row(name, pval, k1177val, k898val):
            d1 = k1177val - pval
            d2 = k1177val - k898val
            pct1 = abs(d1 / pval * 100) if pval != 0 else 0
            close_paper = "~" if pct1 < 2 else ("*" if pct1 < 10 else "DIFF")
            print(f"  {name:<20} {pval:>8.3f} {k1177val:>8.3f} {k898val:>8.3f}  {d1:>+8.3f}({close_paper}){d2:>+8.3f}")

        row('B&H Sharpe', pv['bh_sharpe'], r['bh']['sharpe'], kv['bh_sharpe'])
        row('VT Sharpe', pv['vt_sharpe'], r['vt']['sharpe'], kv['vt_sharpe'])
        row('Hedged Sharpe', pv['hedged_sharpe'], r['hedged_vt']['sharpe'], kv['hedged_sharpe'])
        row('B&H MDD(%)', pv['bh_mdd'], r['bh']['mdd_pct'], kv['bh_mdd'])
        row('VT MDD(%)', pv['vt_mdd'], r['vt']['mdd_pct'], kv['vt_mdd'])
        row('Hedged MDD(%)', pv['hedged_mdd'], r['hedged_vt']['mdd_pct'], kv['hedged_mdd'])
        row('TSMOM Sharpe', pv['tsmom_sharpe'], r['pure_tsmom']['sharpe'], kv['tsmom_sharpe'])
        row('MDD retention(%)', pv['mdd_retention'], r['decomposition']['mdd_retention_pct'], kv['mdd_retention'])

    print(f"\n--- MDD Retention all assets ---")
    print(f"{'Asset':<12} {'Paper':>6} {'K1177':>6} {'K898':>6}  {'Direction':<25}")
    print("-" * 60)
    k898_retention = {'SPY': 107, '50/50': 110, 'DIA': 104, 'QQQ': 120, 'IWM': 115}
    for key in ['SPY', '50/50', 'DIA', 'QQQ', 'IWM']:
        r = all_results[key]
        paper_ret = paper_mdd_retention[key]
        k1177_ret = r['decomposition']['mdd_retention_pct']
        k898_ret = k898_retention[key]
        direction = "IMPROVES MDD" if k1177_ret > 100 else "DEGRADES MDD (paper claim)"
        print(f"  {key:<10} {paper_ret:>5.0f}% {k1177_ret:>5.0f}% {k898_ret:>5.0f}%  {direction}")

    # ============================================================
    # Verdict
    # ============================================================
    spy_hedged_sharpe = all_results['SPY']['hedged_vt']['sharpe']
    spy_mdd_retention = all_results['SPY']['decomposition']['mdd_retention_pct']

    paper_sharpe = 0.737
    k898_sharpe = 0.848
    paper_retention = 93
    k898_retention_spy = 107

    dist_to_paper_sharpe = abs(spy_hedged_sharpe - paper_sharpe)
    dist_to_k898_sharpe = abs(spy_hedged_sharpe - k898_sharpe)
    dist_to_paper_retention = abs(spy_mdd_retention - paper_retention)
    dist_to_k898_retention = abs(spy_mdd_retention - k898_retention_spy)

    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    print(f"K1177 SPY Hedged Sharpe:    {spy_hedged_sharpe:.3f}")
    print(f"  vs Paper  0.737:  diff = {spy_hedged_sharpe - paper_sharpe:+.3f}  ({dist_to_paper_sharpe/paper_sharpe*100:.1f}% rel)")
    print(f"  vs K898   0.848:  diff = {spy_hedged_sharpe - k898_sharpe:+.3f}  ({dist_to_k898_sharpe/k898_sharpe*100:.1f}% rel)")
    print()
    print(f"K1177 SPY MDD Retention:    {spy_mdd_retention:.0f}%")
    print(f"  vs Paper  93%:    diff = {spy_mdd_retention - paper_retention:+.0f}pp")
    print(f"  vs K898   107%:   diff = {spy_mdd_retention - k898_retention_spy:+.0f}pp")
    print()

    closer_paper_sharpe = dist_to_paper_sharpe < dist_to_k898_sharpe
    closer_paper_retention = dist_to_paper_retention < dist_to_k898_retention
    retention_improves_mdd = spy_mdd_retention > 100

    if closer_paper_sharpe and closer_paper_retention:
        verdict = "(a) K1177 MATCHES PAPER — paper is correct, K898 used different construction"
    elif not closer_paper_sharpe and not closer_paper_retention:
        verdict = "(b) K1177 MATCHES K898 — paper has errata, K898 is canonical"
    else:
        verdict = "(c) K1177 INTERMEDIATE — errata pending further analysis"

    print(f"Verdict: {verdict}")
    print()
    print(f"MDD direction: {'IMPROVES (retention>100%)' if retention_improves_mdd else 'DEGRADES (retention<100%)'}")
    print(f"  Paper claims: DEGRADES (93% retention)")
    print(f"  K898 shows:   IMPROVES (107% retention)")
    print(f"  K1177 shows:  {'IMPROVES' if retention_improves_mdd else 'DEGRADES'} ({spy_mdd_retention:.0f}% retention)")

    # ============================================================
    # Build JSON output
    # ============================================================
    output = {
        'experiment_id': 'K1177',
        'title': 'Paper 3 Table 3 TSMOM Hedge SPY — Canonical Replication',
        'description': (
            'Canonical replication of paper Table 3 with paper-specified methodology: '
            'monthly VT rebalancing, 10 bps tx costs, orthogonalized TSMOM hedge. '
            'Determines whether paper 0.737/93% or K898 0.848/107% is canonical.'
        ),
        'data_source': 'yfinance',
        'period': f'{ANALYSIS_START.date()} to 2026-03-31',
        'methodology': {
            'vt_rule': 'w_t = min(12/VIX_month_end_{t-1}, 1)',
            'rebalancing': 'monthly (month-end VIX, applied next month)',
            'signal_lag': 'VIX end-of-month t -> weight for month t+1',
            'remainder': 'SHY (short-term treasury)',
            'tx_cost_bps': TX_COST_BPS,
            'tsmom_lookback': TSMOM_LOOKBACK,
            'tsmom_hedge': 'Rolling 252-day OLS of VT on TSMOM^perp; PureVT = VT - b*TSMOM^perp',
            'tsmom_orthogonalization': 'Full-sample: TSMOM^perp = TSMOM - beta_MKT * MKT',
            'beta_constraint': 'None (unlike K898 which constrains to [0, 0.5])',
            'bootstrap': f'{BOOTSTRAP_REPS} reps, block size {BOOTSTRAP_BLOCK} days, seed={SEED}',
        },
        'key_differences_from_k898': {
            '1_rebalancing': 'MONTHLY (K898: daily)',
            '2_tx_costs': f'{TX_COST_BPS} bps (K898: 0 bps)',
            '3_tsmom_factor': 'orthogonalized TSMOM^perp (K898: raw TSMOM)',
            '4_beta_constraint': 'None (K898: constrained [0, 0.5])',
        },
        'results': {},
        'paper_comparison': {
            'paper_values': paper_table3,
            'paper_mdd_retention': paper_mdd_retention,
            'k898_values': k898_table3,
            'k898_mdd_retention': k898_retention,
        },
        'verdict': {
            'spy_hedged_sharpe_k1177': spy_hedged_sharpe,
            'spy_mdd_retention_k1177': float(spy_mdd_retention),
            'spy_hedged_sharpe_paper': paper_sharpe,
            'spy_hedged_sharpe_k898': k898_sharpe,
            'spy_mdd_retention_paper': float(paper_retention),
            'spy_mdd_retention_k898': float(k898_retention_spy),
            'dist_to_paper_sharpe': round(dist_to_paper_sharpe, 4),
            'dist_to_k898_sharpe': round(dist_to_k898_sharpe, 4),
            'closer_to_paper_sharpe': bool(closer_paper_sharpe),
            'closer_to_paper_retention': bool(closer_paper_retention),
            'mdd_direction_improves': bool(retention_improves_mdd),
            'decision': verdict,
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    }

    for key in ['SPY', '50/50', 'DIA', 'QQQ', 'IWM']:
        r = all_results[key]
        output['results'][key] = {
            'buy_and_hold': r['bh'],
            '12vix_vt_monthly': r['vt'],
            'tsmom_hedged_vt_orth': r['hedged_vt'],
            'tsmom_hedged_vt_raw': r['hedged_vt_raw'],
            'pure_tsmom': r['pure_tsmom'],
            'avg_tsmom_beta': r['avg_tsmom_beta'],
            'beta_mkt_fullsample': r.get('beta_mkt_fullsample'),
            'decomposition': r['decomposition'],
            'bootstrap_mdd_retention': r['bootstrap_mdd_retention'],
        }

    out_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a9d575bd/experiments/k1177/k1177_results.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n✓ Results saved to {out_path}")

    return output


if __name__ == '__main__':
    results = main()
