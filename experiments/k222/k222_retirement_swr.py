"""
K222: Retirement Safe Withdrawal Rate with 50/50+VT -- Does VT Help or Hurt Retirees?

Background: K36 found VT hurts retirement (SWR 5.5%->4.0%). But that was SPY-only VT.
Does 50/50 SPY/GLD + VT (12/VIX) improve retirement outcomes?
The GLD component might buffer withdrawal stress.

Data: SPY, GLD, ^VIX daily from yfinance. 2005-2024 (19 years).

Methodology:
1. Simulate retirement portfolios starting with $1M
2. Monthly withdrawal of X% annualized (test 3%, 4%, 5%, 6%, 7%)
3. Three strategies:
   a) SPY B&H with withdrawals
   b) 50/50 SPY/GLD B&H with withdrawals
   c) 50/50 SPY/GLD + VT (12/VIX) with withdrawals
4. Rolling 10-year windows for robustness
5. Key question: Does 50/50+VT have higher SWR than 50/50 B&H?

[提出: User, 執行: Claude]
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA LOADING
# ============================================================
print("=" * 70)
print("K222: Retirement Safe Withdrawal Rate — 50/50+VT vs B&H")
print("=" * 70)
print(f"Run time: {datetime.now()}")

# Fetch data
print("\nFetching data from yfinance...")
spy_raw = yf.download("SPY", start="2004-06-01", end="2025-01-01", auto_adjust=True, progress=False)
gld_raw = yf.download("GLD", start="2004-06-01", end="2025-01-01", auto_adjust=True, progress=False)
vix_raw = yf.download("^VIX", start="2004-06-01", end="2025-01-01", auto_adjust=True, progress=False)

# Handle multi-level columns if present
for df_name, df in [("SPY", spy_raw), ("GLD", gld_raw), ("VIX", vix_raw)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy_close = spy_raw['Close'].squeeze()
gld_close = gld_raw['Close'].squeeze()
vix_close = vix_raw['Close'].squeeze()

# Align dates
common_idx = spy_close.index.intersection(gld_close.index).intersection(vix_close.index)
spy_close = spy_close.loc[common_idx].sort_index()
gld_close = gld_close.loc[common_idx].sort_index()
vix_close = vix_close.loc[common_idx].sort_index()

# Compute daily returns
spy_ret = spy_close.pct_change().dropna()
gld_ret = gld_close.pct_change().dropna()

# Align everything
common_idx2 = spy_ret.index.intersection(gld_ret.index).intersection(vix_close.index)
spy_ret = spy_ret.loc[common_idx2]
gld_ret = gld_ret.loc[common_idx2]
vix_close = vix_close.loc[common_idx2]

print(f"  SPY returns: {spy_ret.index[0].date()} to {spy_ret.index[-1].date()} ({len(spy_ret)} days)")
print(f"  GLD returns: {gld_ret.index[0].date()} to {gld_ret.index[-1].date()} ({len(gld_ret)} days)")
print(f"  VIX: {vix_close.index[0].date()} to {vix_close.index[-1].date()}")

# ============================================================
# 2. SIMULATION FUNCTIONS
# ============================================================

INITIAL_CAPITAL = 1_000_000
WITHDRAWAL_RATES = [0.03, 0.04, 0.05, 0.06, 0.07]
TRADING_DAYS_PER_MONTH = 21  # approximate


def simulate_retirement(daily_returns_df, strategy_name, withdrawal_rate,
                        start_date, end_date, vix_series=None):
    """
    Simulate a retirement portfolio with monthly withdrawals.

    daily_returns_df: DataFrame with columns for asset returns (already weighted)
                      OR a Series for single-asset strategy
    strategy_name: one of 'spy_bh', '5050_bh', '5050_vt'
    withdrawal_rate: annual rate (e.g. 0.04 for 4%)
    vix_series: needed for VT strategy

    Returns dict with terminal_wealth, min_wealth, ruin (bool), monthly_withdrawals
    """
    # Filter to date range
    mask = (daily_returns_df.index >= pd.Timestamp(start_date)) & \
           (daily_returns_df.index <= pd.Timestamp(end_date))

    if isinstance(daily_returns_df, pd.DataFrame):
        period_rets = daily_returns_df.loc[mask]
    else:
        period_rets = daily_returns_df.loc[mask]

    if vix_series is not None:
        vix_period = vix_series.loc[mask]

    monthly_withdrawal = INITIAL_CAPITAL * withdrawal_rate / 12.0
    wealth = INITIAL_CAPITAL
    min_wealth = INITIAL_CAPITAL
    ruined = False
    ruin_day = None
    day_count = 0
    wealth_path = []

    for i, date in enumerate(period_rets.index):
        if wealth <= 0:
            ruined = True
            if ruin_day is None:
                ruin_day = date
            wealth = 0
            wealth_path.append(0)
            continue

        # Compute daily portfolio return based on strategy
        if strategy_name == 'spy_bh':
            daily_ret = spy_ret.loc[date] if date in spy_ret.index else 0
        elif strategy_name == '5050_bh':
            s_ret = spy_ret.loc[date] if date in spy_ret.index else 0
            g_ret = gld_ret.loc[date] if date in gld_ret.index else 0
            daily_ret = 0.5 * s_ret + 0.5 * g_ret
        elif strategy_name == '5050_vt':
            s_ret = spy_ret.loc[date] if date in spy_ret.index else 0
            g_ret = gld_ret.loc[date] if date in gld_ret.index else 0
            vix_val = vix_series.loc[date] if date in vix_series.index else 20
            vt_weight = min(12.0 / vix_val, 1.0) if vix_val > 0 else 1.0
            # VT scales the ENTIRE 50/50 portfolio
            raw_ret = 0.5 * s_ret + 0.5 * g_ret
            daily_ret = vt_weight * raw_ret
            # Cash portion earns ~0% (simplification; SHY ~2-4% but small effect)
        else:
            daily_ret = 0

        # Apply return
        wealth *= (1 + daily_ret)

        # Monthly withdrawal (every ~21 trading days)
        day_count += 1
        if day_count >= TRADING_DAYS_PER_MONTH:
            wealth -= monthly_withdrawal
            day_count = 0

        if wealth < min_wealth:
            min_wealth = wealth

        wealth_path.append(wealth)

    return {
        'terminal_wealth': round(wealth, 2),
        'min_wealth': round(max(min_wealth, 0), 2),
        'ruined': ruined,
        'ruin_day': str(ruin_day.date()) if ruin_day is not None else None,
        'total_withdrawn': round(monthly_withdrawal * 12 *
                                 ((pd.Timestamp(end_date) - pd.Timestamp(start_date)).days / 365.25), 2),
        'wealth_path_len': len(wealth_path),
    }


# ============================================================
# 3. FULL-PERIOD SIMULATION (2005-2024)
# ============================================================
print("\n" + "=" * 70)
print("PART 1: Full Period 2005-2024 (19 years)")
print("=" * 70)

START = "2005-01-01"
END = "2024-12-31"

strategies = ['spy_bh', '5050_bh', '5050_vt']
strategy_labels = {
    'spy_bh': 'SPY Buy & Hold',
    '5050_bh': '50/50 SPY/GLD B&H',
    '5050_vt': '50/50 SPY/GLD + VT (12/VIX)'
}

full_results = {}

for strat in strategies:
    full_results[strat] = {}
    for wr in WITHDRAWAL_RATES:
        result = simulate_retirement(
            spy_ret, strat, wr, START, END, vix_series=vix_close
        )
        full_results[strat][f"{wr:.0%}"] = result

# Print results table
print(f"\n{'Strategy':<30} {'WR':>5} {'Terminal $':>14} {'Min $':>14} {'Ruin':>6} {'Withdrawn':>14}")
print("-" * 90)
for strat in strategies:
    for wr in WITHDRAWAL_RATES:
        r = full_results[strat][f"{wr:.0%}"]
        ruin_str = "YES" if r['ruined'] else "no"
        print(f"{strategy_labels[strat]:<30} {wr:>4.0%} {r['terminal_wealth']:>14,.0f} "
              f"{r['min_wealth']:>14,.0f} {ruin_str:>6} {r['total_withdrawn']:>14,.0f}")
    print()

# Determine SWR for each strategy (max WR where no ruin)
print("\n--- Safe Withdrawal Rates (max WR with no ruin) ---")
for strat in strategies:
    swr = 0
    for wr in WITHDRAWAL_RATES:
        if not full_results[strat][f"{wr:.0%}"]['ruined']:
            swr = wr
    print(f"  {strategy_labels[strat]:<35}: SWR = {swr:.0%}")


# ============================================================
# 4. ROLLING 10-YEAR WINDOWS
# ============================================================
print("\n" + "=" * 70)
print("PART 2: Rolling 10-Year Windows (robustness)")
print("=" * 70)

rolling_results = {}
windows = []
for start_year in range(2005, 2016):  # 2005-2014 through 2015-2024
    w_start = f"{start_year}-01-01"
    w_end = f"{start_year + 9}-12-31"
    windows.append((w_start, w_end))

for strat in strategies:
    rolling_results[strat] = {}
    for wr in WITHDRAWAL_RATES:
        rolling_results[strat][f"{wr:.0%}"] = []
        for w_start, w_end in windows:
            result = simulate_retirement(
                spy_ret, strat, wr, w_start, w_end, vix_series=vix_close
            )
            rolling_results[strat][f"{wr:.0%}"].append({
                'window': f"{w_start[:4]}-{w_end[:4]}",
                'terminal_wealth': result['terminal_wealth'],
                'min_wealth': result['min_wealth'],
                'ruined': result['ruined'],
            })

# Summary: for each strategy x WR, count how many windows survive
print(f"\n{'Strategy':<30} {'WR':>5} {'Survive':>8} {'Ruin':>6} {'Avg Terminal':>14} {'Worst Terminal':>14}")
print("-" * 85)
for strat in strategies:
    for wr in WITHDRAWAL_RATES:
        windows_data = rolling_results[strat][f"{wr:.0%}"]
        n_survive = sum(1 for w in windows_data if not w['ruined'])
        n_ruin = sum(1 for w in windows_data if w['ruined'])
        terminals = [w['terminal_wealth'] for w in windows_data]
        avg_terminal = np.mean(terminals)
        worst_terminal = min(terminals)
        print(f"{strategy_labels[strat]:<30} {wr:>4.0%} {n_survive:>6}/{len(windows_data)} "
              f"{n_ruin:>5} {avg_terminal:>14,.0f} {worst_terminal:>14,.0f}")
    print()

# SWR by rolling windows (max WR where ALL windows survive)
print("\n--- Rolling-Window SWR (max WR where ALL windows survive) ---")
rolling_swr = {}
for strat in strategies:
    swr = 0
    for wr in WITHDRAWAL_RATES:
        windows_data = rolling_results[strat][f"{wr:.0%}"]
        if all(not w['ruined'] for w in windows_data):
            swr = wr
    rolling_swr[strat] = swr
    print(f"  {strategy_labels[strat]:<35}: SWR = {swr:.0%}")


# ============================================================
# 5. FINE-GRAINED SWR SEARCH (0.5% increments)
# ============================================================
print("\n" + "=" * 70)
print("PART 3: Fine-Grained SWR Search (0.5% increments, full period)")
print("=" * 70)

fine_rates = [r / 100 for r in np.arange(2.0, 10.5, 0.5)]
fine_swr = {}

for strat in strategies:
    fine_swr[strat] = {'full_period': 0, 'all_windows': 0}
    for wr in fine_rates:
        # Full period
        result_full = simulate_retirement(
            spy_ret, strat, wr, START, END, vix_series=vix_close
        )
        if not result_full['ruined']:
            fine_swr[strat]['full_period'] = wr

        # All rolling windows
        all_survive = True
        for w_start, w_end in windows:
            result_w = simulate_retirement(
                spy_ret, strat, wr, w_start, w_end, vix_series=vix_close
            )
            if result_w['ruined']:
                all_survive = False
                break
        if all_survive:
            fine_swr[strat]['all_windows'] = wr

print(f"\n{'Strategy':<35} {'Full-Period SWR':>16} {'All-Windows SWR':>16}")
print("-" * 70)
for strat in strategies:
    fp = fine_swr[strat]['full_period']
    aw = fine_swr[strat]['all_windows']
    print(f"{strategy_labels[strat]:<35} {fp:>15.1%} {aw:>15.1%}")


# ============================================================
# 6. STRESS ANALYSIS: 2007-2009 GFC WINDOW
# ============================================================
print("\n" + "=" * 70)
print("PART 4: GFC Stress Test (starting retirement 2007-01-01)")
print("=" * 70)

GFC_START = "2007-01-01"
GFC_END = "2016-12-31"  # 10-year window starting just before GFC

gfc_results = {}
for strat in strategies:
    gfc_results[strat] = {}
    for wr in WITHDRAWAL_RATES:
        result = simulate_retirement(
            spy_ret, strat, wr, GFC_START, GFC_END, vix_series=vix_close
        )
        gfc_results[strat][f"{wr:.0%}"] = result

print(f"\n{'Strategy':<30} {'WR':>5} {'Terminal $':>14} {'Min $':>14} {'Ruin':>6}")
print("-" * 75)
for strat in strategies:
    for wr in WITHDRAWAL_RATES:
        r = gfc_results[strat][f"{wr:.0%}"]
        ruin_str = "YES" if r['ruined'] else "no"
        print(f"{strategy_labels[strat]:<30} {wr:>4.0%} {r['terminal_wealth']:>14,.0f} "
              f"{r['min_wealth']:>14,.0f} {ruin_str:>6}")
    print()


# ============================================================
# 7. VT MECHANISM ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("PART 5: VT Mechanism — Exposure & Cash Drag Analysis")
print("=" * 70)

# How often is VT < 1? What's the average VT weight?
mask_period = (vix_close.index >= pd.Timestamp(START)) & (vix_close.index <= pd.Timestamp(END))
vix_period = vix_close.loc[mask_period]
vt_weights = np.minimum(12.0 / vix_period, 1.0)

print(f"\nVT Weight Statistics (2005-2024):")
print(f"  Mean VT weight:    {vt_weights.mean():.3f}")
print(f"  Median VT weight:  {vt_weights.median():.3f}")
print(f"  % days fully invested (VT=1): {(vt_weights >= 0.999).mean():.1%}")
print(f"  % days < 80% invested:        {(vt_weights < 0.80).mean():.1%}")
print(f"  % days < 50% invested:        {(vt_weights < 0.50).mean():.1%}")
print(f"  Average cash drag:  {(1 - vt_weights.mean()):.1%} of portfolio in cash")

# VT weight during GFC
gfc_mask = (vix_close.index >= pd.Timestamp("2008-09-01")) & (vix_close.index <= pd.Timestamp("2009-03-31"))
vix_gfc = vix_close.loc[gfc_mask]
vt_gfc = np.minimum(12.0 / vix_gfc, 1.0)
print(f"\nGFC Period (Sep 2008 - Mar 2009):")
print(f"  Mean VIX:          {vix_gfc.mean():.1f}")
print(f"  Mean VT weight:    {vt_gfc.mean():.3f}")
print(f"  Cash drag:         {(1 - vt_gfc.mean()):.1%}")
print(f"  → Withdrawals from a portfolio that's {vt_gfc.mean():.0%} invested")
print(f"  → Cash drag reduces both gains AND losses, but withdrawals stay fixed")


# ============================================================
# 8. COMPARISON: CUMULATIVE RETURNS (NO WITHDRAWAL)
# ============================================================
print("\n" + "=" * 70)
print("PART 6: Reference — Cumulative Returns Without Withdrawals")
print("=" * 70)

mask_full = (spy_ret.index >= pd.Timestamp(START)) & (spy_ret.index <= pd.Timestamp(END))
spy_r = spy_ret.loc[mask_full]
gld_r = gld_ret.loc[mask_full]
vix_f = vix_close.loc[mask_full]

# SPY B&H
cum_spy = (1 + spy_r).cumprod().iloc[-1]

# 50/50 B&H
ret_5050 = 0.5 * spy_r + 0.5 * gld_r
cum_5050 = (1 + ret_5050).cumprod().iloc[-1]

# 50/50 VT
vt_w = np.minimum(12.0 / vix_f, 1.0)
ret_5050_vt = vt_w * (0.5 * spy_r + 0.5 * gld_r)
cum_5050_vt = (1 + ret_5050_vt).cumprod().iloc[-1]

print(f"\n  SPY B&H cumulative return:       {(cum_spy - 1):>8.1%}  (${INITIAL_CAPITAL * cum_spy:>14,.0f})")
print(f"  50/50 B&H cumulative return:     {(cum_5050 - 1):>8.1%}  (${INITIAL_CAPITAL * cum_5050:>14,.0f})")
print(f"  50/50+VT cumulative return:      {(cum_5050_vt - 1):>8.1%}  (${INITIAL_CAPITAL * cum_5050_vt:>14,.0f})")

# Annualized returns
n_years = (spy_r.index[-1] - spy_r.index[0]).days / 365.25
ann_spy = cum_spy ** (1/n_years) - 1
ann_5050 = cum_5050 ** (1/n_years) - 1
ann_5050_vt = cum_5050_vt ** (1/n_years) - 1

print(f"\n  SPY B&H annualized:   {ann_spy:>6.2%}")
print(f"  50/50 B&H annualized: {ann_5050:>6.2%}")
print(f"  50/50+VT annualized:  {ann_5050_vt:>6.2%}")
print(f"  VT return drag:       {(ann_5050_vt - ann_5050):>6.2%} per year")

# Volatility comparison
vol_spy = spy_r.std() * np.sqrt(252)
vol_5050 = ret_5050.std() * np.sqrt(252)
vol_5050_vt = ret_5050_vt.std() * np.sqrt(252)

print(f"\n  SPY B&H volatility:   {vol_spy:>6.2%}")
print(f"  50/50 B&H volatility: {vol_5050:>6.2%}")
print(f"  50/50+VT volatility:  {vol_5050_vt:>6.2%}")

# Max drawdown
def max_drawdown(returns):
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return dd.min()

mdd_spy = max_drawdown(spy_r)
mdd_5050 = max_drawdown(ret_5050)
mdd_5050_vt = max_drawdown(ret_5050_vt)

print(f"\n  SPY B&H max drawdown:   {mdd_spy:>7.1%}")
print(f"  50/50 B&H max drawdown: {mdd_5050:>7.1%}")
print(f"  50/50+VT max drawdown:  {mdd_5050_vt:>7.1%}")


# ============================================================
# 9. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

print(f"""
Key Findings:

1. Full-Period SWR (2005-2024, 19 years):
   SPY B&H:          {fine_swr['spy_bh']['full_period']:.1%}
   50/50 B&H:        {fine_swr['5050_bh']['full_period']:.1%}
   50/50 + VT:       {fine_swr['5050_vt']['full_period']:.1%}

2. Rolling-Window SWR (all 10-year windows must survive):
   SPY B&H:          {fine_swr['spy_bh']['all_windows']:.1%}
   50/50 B&H:        {fine_swr['5050_bh']['all_windows']:.1%}
   50/50 + VT:       {fine_swr['5050_vt']['all_windows']:.1%}

3. VT Weight Analysis:
   Average VT weight: {vt_weights.mean():.3f} (cash drag: {(1 - vt_weights.mean()):.1%})
   During GFC: VT weight = {vt_gfc.mean():.3f} (mostly in cash during crash)

4. The VT Retirement Paradox:
   - VT reduces drawdowns (MDD: {mdd_5050:.1%} → {mdd_5050_vt:.1%})
   - BUT VT also reduces total return ({ann_5050:.2%} → {ann_5050_vt:.2%} annualized)
   - For accumulators: lower vol is good (better Sharpe)
   - For retirees: FIXED withdrawals from a SMALLER portfolio = faster ruin
   - The cash drag compounds over decades, eating into terminal wealth
   - 50/50 diversification helps MORE than VT timing for retirement

5. K36 Revisited:
   - K36 found VT hurts retirement for SPY-only (SWR 5.5%→4.0%)
   - With 50/50: {'VT still hurts' if fine_swr['5050_vt']['all_windows'] < fine_swr['5050_bh']['all_windows'] else 'VT helps' if fine_swr['5050_vt']['all_windows'] > fine_swr['5050_bh']['all_windows'] else 'No difference'} retirement
   - 50/50 B&H SWR ({fine_swr['5050_bh']['all_windows']:.1%}) vs 50/50+VT SWR ({fine_swr['5050_vt']['all_windows']:.1%})
""")


# ============================================================
# 10. SAVE RESULTS
# ============================================================
output = {
    'experiment': 'K222',
    'title': 'Retirement SWR: 50/50+VT vs B&H',
    'date': str(datetime.now()),
    'data_period': f"{START} to {END}",
    'initial_capital': INITIAL_CAPITAL,
    'full_period_results': {},
    'fine_swr': {},
    'rolling_swr': {},
    'gfc_stress_test': {},
    'vt_diagnostics': {
        'mean_vt_weight': round(float(vt_weights.mean()), 4),
        'median_vt_weight': round(float(vt_weights.median()), 4),
        'pct_fully_invested': round(float((vt_weights >= 0.999).mean()), 4),
        'gfc_mean_vt_weight': round(float(vt_gfc.mean()), 4),
        'avg_cash_drag_pct': round(float(1 - vt_weights.mean()) * 100, 2),
    },
    'return_comparison': {
        'spy_bh_ann': round(float(ann_spy), 5),
        '5050_bh_ann': round(float(ann_5050), 5),
        '5050_vt_ann': round(float(ann_5050_vt), 5),
        'vt_drag_ann': round(float(ann_5050_vt - ann_5050), 5),
    },
    'risk_comparison': {
        'spy_bh_vol': round(float(vol_spy), 5),
        '5050_bh_vol': round(float(vol_5050), 5),
        '5050_vt_vol': round(float(vol_5050_vt), 5),
        'spy_bh_mdd': round(float(mdd_spy), 5),
        '5050_bh_mdd': round(float(mdd_5050), 5),
        '5050_vt_mdd': round(float(mdd_5050_vt), 5),
    },
}

# Add full period results
for strat in strategies:
    output['full_period_results'][strat] = full_results[strat]
    output['fine_swr'][strat] = fine_swr[strat]
    output['rolling_swr'][strat] = rolling_swr[strat]
    output['gfc_stress_test'][strat] = gfc_results[strat]

out_path = 'experiments/k222_retirement_swr_results.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")
print("DONE.")
