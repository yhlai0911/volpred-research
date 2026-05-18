"""
K620 Supplement: Strategy A-specific statistics
補算 Strategy A (Post-Revenue Boost) 的 per-period t-stat、bootstrap CI、
交易成本、月勝率，以修正文章論證鏈條（Codex FAIL: A/C 混用）。

Seed: 42
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print("=" * 60)
print("K620 Strategy A Supplement — per-period t-stat + bootstrap")
print("=" * 60)

# ── 1. Data ────────────────────────────────────────────────
print("\n[1] Downloading data...")
etf = yf.download('0050.TW', start='2015-01-01', end='2026-12-31', progress=False)
vix = yf.download('^VIX', start='2015-01-01', end='2026-12-31', progress=False)

if isinstance(etf.columns, pd.MultiIndex):
    etf.columns = etf.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

etf['Return'] = etf['Close'].pct_change()
etf = etf.dropna(subset=['Return'])
vix_close = vix['Close'].rename('VIX')

df = etf[['Return']].copy()
df = df.join(vix_close, how='left')
df['VIX'] = df['VIX'].ffill()
df = df.dropna(subset=['VIX'])

trading_days_list = list(df.index)
trading_days_set = set(trading_days_list)
td_to_idx = {td: i for i, td in enumerate(trading_days_list)}

def find_next_trading_day(date, td_set, max_search=10):
    for i in range(max_search):
        candidate = pd.Timestamp(date + timedelta(days=i))
        if candidate in td_set:
            return candidate
    return None

# ── 2. Event dates ─────────────────────────────────────────
revenue_dates = []
for year in range(2015, 2027):
    for month in range(1, 13):
        target = datetime(year, month, 10)
        td = find_next_trading_day(target, trading_days_set)
        if td is not None and td in trading_days_set:
            revenue_dates.append(td)

df['is_pre_revenue'] = False
df['is_post_revenue'] = False

for rev_date in revenue_dates:
    if rev_date not in td_to_idx:
        continue
    rev_idx = td_to_idx[rev_date]
    for offset in range(1, 4):  # 3 pre days
        pre_idx = rev_idx - offset
        if 0 <= pre_idx < len(trading_days_list):
            df.iloc[pre_idx, df.columns.get_loc('is_pre_revenue')] = True
    for offset in range(0, 6):  # 6 post days (event day + 5 following, matching K620 POST_DAYS=5 range(0,POST_DAYS+1))
        post_idx = rev_idx + offset
        if 0 <= post_idx < len(trading_days_list):
            df.iloc[post_idx, df.columns.get_loc('is_post_revenue')] = True

# ── 3. Strategy returns ────────────────────────────────────
df['w_base'] = (8.63 / df['VIX']).clip(upper=1.0)
df['w_a'] = df['w_base'].copy()
df.loc[df['is_post_revenue'], 'w_a'] = (
    df.loc[df['is_post_revenue'], 'w_base'] * 1.20
).clip(upper=1.0)

df['ret_base'] = df['w_base'].shift(1) * df['Return']
df['ret_a'] = df['w_a'].shift(1) * df['Return']
df = df.dropna(subset=['ret_base'])
df['diff_a'] = df['ret_a'] - df['ret_base']

print(f"  Days: {len(df)} ({df.index[0].date()} to {df.index[-1].date()})")

# ── 4. Per-sub-period t-stat (A vs Baseline) ───────────────
print("\n[2] Strategy A per-period t-stat...")
oos_periods = [
    ('OOS1: 2015-2018', '2015-01-01', '2018-12-31'),
    ('OOS2: 2019-2022', '2019-01-01', '2022-12-31'),
    ('OOS3: 2023-2026', '2023-01-01', '2026-12-31'),
]

oos_results = {}
for period_name, start, end in oos_periods:
    mask = (df.index >= start) & (df.index <= end)
    sub = df[mask]
    diff = sub['diff_a']
    t_stat, p_val = stats.ttest_1samp(diff, 0)
    sharpe_base = (sub['ret_base'].mean() * 252) / (sub['ret_base'].std() * np.sqrt(252))
    sharpe_a = (sub['ret_a'].mean() * 252) / (sub['ret_a'].std() * np.sqrt(252))
    oos_results[period_name] = {
        'n_days': int(len(sub)),
        'sharpe_base': float(sharpe_base),
        'sharpe_a': float(sharpe_a),
        'ann_excess': float(diff.mean() * 252),
        'a_vs_base_t': float(t_stat),
        'a_vs_base_p': float(p_val),
    }
    print(f"  {period_name} (n={len(sub)}):")
    print(f"    Baseline Sharpe={sharpe_base:.4f}, A Sharpe={sharpe_a:.4f}")
    print(f"    A vs Base: t={t_stat:.4f}, p={p_val:.4f}, ann_excess={diff.mean()*252*100:.4f}%")

# ── 5. Bootstrap CI for Strategy A ─────────────────────────
print("\n[3] Bootstrap CI for Strategy A (n=10,000, seed=42)...")
diff_a_full = df['diff_a'].values
n_bs = 10_000
boot_means = np.empty(n_bs)
rng = np.random.default_rng(42)
for i in range(n_bs):
    boot_means[i] = rng.choice(diff_a_full, size=len(diff_a_full), replace=True).mean() * 252

ci_lower = float(np.percentile(boot_means, 2.5))
ci_upper = float(np.percentile(boot_means, 97.5))
point_est = float(diff_a_full.mean() * 252)

print(f"  Point estimate: {point_est*100:.4f}%")
print(f"  95% CI: [{ci_lower*100:.4f}%, {ci_upper*100:.4f}%]")
print(f"  Zero in CI: {ci_lower < 0 < ci_upper}")

bootstrap_a = {
    'mean_excess_annual': point_est,
    'ci_95_lower': ci_lower,
    'ci_95_upper': ci_upper,
    'zero_in_ci': bool(ci_lower < 0 < ci_upper),
    'n_bootstrap': n_bs,
}

# ── 6. Transaction costs for Strategy A ────────────────────
# Use weight-delta approach (consistent with K620 original), not strict equality count
print("\n[4] Transaction costs for Strategy A...")
w_diff_a = df['w_a'].diff().abs().fillna(0)
w_diff_base = df['w_base'].diff().abs().fillna(0)
extra_tx_daily = (w_diff_a - w_diff_base) * 0.0010  # 10bps per unit weight delta
annual_extra_tx = extra_tx_daily.sum() / (len(df) / 252)
gross_excess = point_est
net_excess = gross_excess - annual_extra_tx

print(f"  Total weight-delta extra tx cost (10bps): {extra_tx_daily.sum()*100:.4f}%")
print(f"  Annual extra tx cost: {annual_extra_tx*100:.4f}%")
print(f"  Gross excess: {gross_excess*100:.4f}%")
print(f"  Net excess: {net_excess*100:.4f}%")

tx_costs_a = {
    'methodology': 'weight-delta (consistent with K620 original)',
    'tx_cost_bps': 10,
    'annual_extra_tx': float(annual_extra_tx),
    'gross_excess_annual': float(gross_excess),
    'net_excess_annual': float(net_excess),
}

# ── 7. Monthly alpha for Strategy A ────────────────────────
print("\n[5] Monthly alpha for Strategy A...")
df['month_key'] = df.index.to_period('M')
monthly_diff = df.groupby('month_key')['diff_a'].sum()
positive_months = (monthly_diff > 0).sum()
negative_months = (monthly_diff <= 0).sum()
total_months = len(monthly_diff)
win_rate = positive_months / total_months
binom_p = stats.binomtest(int(positive_months), int(total_months), 0.5, alternative='greater').pvalue

print(f"  Total months: {total_months}")
print(f"  Positive months: {positive_months}")
print(f"  Negative months: {negative_months}")
print(f"  Win rate: {win_rate:.4f}")
print(f"  Binomial p (one-tail): {binom_p:.4f}")

monthly_a = {
    'total_months': int(total_months),
    'positive_months': int(positive_months),
    'negative_months': int(negative_months),
    'win_rate': float(win_rate),
    'mean_monthly_excess': float(monthly_diff.mean()),
    'median_monthly_excess': float(monthly_diff.median()),
    'binomial_p': float(binom_p),
}

# ── 8. Summary ─────────────────────────────────────────────
supplement = {
    'generated_at': datetime.utcnow().isoformat() + 'Z',
    'purpose': 'Strategy A specific stats to fix A/C mixing in article mile_7ba7ee54',
    'seed': 42,
    'strategy': 'A: Post-Revenue Boost (×1.20 for 5 days after monthly revenue)',
    'oos_per_period': oos_results,
    'bootstrap_a': bootstrap_a,
    'transaction_costs_a': tx_costs_a,
    'monthly_alpha_a': monthly_a,
}

out_path = 'experiments/k620/k620_strategy_a_supplement_results.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(supplement, f, ensure_ascii=False, indent=2)

print(f"\n✓ Saved: {out_path}")
print("\n=== KEY NUMBERS FOR ARTICLE REWRITE ===")
for pn, r in oos_results.items():
    print(f"{pn}: Base={r['sharpe_base']:.3f}, A={r['sharpe_a']:.3f}, t={r['a_vs_base_t']:.2f} (p={r['a_vs_base_p']:.3f})")
print(f"Bootstrap CI: [{ci_lower*100:.3f}%, {ci_upper*100:.3f}%], zero_in_CI={ci_lower < 0 < ci_upper}")
print(f"Net excess (after 10bps): {net_excess*100:.3f}%")
print(f"Monthly win rate: {win_rate:.4f} (p={binom_p:.4f})")
