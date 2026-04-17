"""
K873: Weekend Volatility Effect — Calendar Anomaly in Vol Prediction

Prior knowledge:
- K423: Day-of-week vol effect MOSTLY NULL for equities (SPY 0.98x).
  BTC post-2020 is the only significant Monday effect (1.307x, t=4.43).
- K627: DOW explains <1.5% of VIX variance. All DOW-adjusted 12/VIX underperform.
- K136/K139: BTC weekend vol = 69% of weekday (institutional absence).
- K627: HAR+calendar vs HAR QLIKE -4.4% but DM p=0.196 (NS).

Research Questions:
1. Is Fri-Mon return variance MORE than 3x weekday variance? (excess weekend vol)
2. Does Friday vol predict Monday vol differently from other weekday transitions?
3. Does adding day-of-week dummies improve HAR vol forecast OOS?
4. Has the weekend effect changed over time (pre vs post 2020)?
5. Is there a VT strategy implication (use Friday VIX differently for Monday)?

Methodology:
- Weekend ratio = Var(Fri→Mon) / (3 × Var(avg weekday return)) — if >1, excess vol
- HAR(5,22) with day-of-week dummies; IS 2005-2018, OOS 2019-2026
- BTC as control (24/7 trading, no structural weekend gap)
- Bootstrap CI for weekend ratio

Data: yfinance — SPY, QQQ, BTC-USD, ^VIX. Period: 2005-01 to 2026-04.
References:
- French & Roll (1986): "Stock return variances: The arrival of information
  and the reaction of traders" — weekend variance < 3× weekday
- Patton & Sheppard (2015): "Good Volatility, Bad Volatility" — HAR extensions
- Harvey et al. (2016): t>3.0 threshold for anomaly significance

Error log rules applied:
- DM test: use strategy_dm_test from volpred.stats.model_evaluation
- signal.shift(1) for any strategy backtest
- Sharpe > 2x baseline = bug flag

Output: experiments/k873_results.json
"""

import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
import json
import warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K873: Weekend Volatility Effect — Calendar Anomaly in Vol Prediction")
print("=" * 75)

# ============================================================
# SECTION 1: Data Download
# ============================================================
assets = {
    'SPY': {'ticker': 'SPY', 'start': '2005-01-01'},
    'QQQ': {'ticker': 'QQQ', 'start': '2005-01-01'},
    'BTC': {'ticker': 'BTC-USD', 'start': '2014-09-01'},
    'VIX': {'ticker': '^VIX', 'start': '2005-01-01'},
}

price_data = {}
for name, cfg in assets.items():
    df = yf.download(cfg['ticker'], start=cfg['start'], end='2026-04-05', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    price_data[name] = df['Close'].dropna().squeeze()
    print(f"  {name}: {len(price_data[name])} obs, {price_data[name].index[0].strftime('%Y-%m-%d')} to {price_data[name].index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# SECTION 2: Compute Returns and Day-of-Week
# ============================================================
def compute_weekend_stats(prices, label):
    """Compute weekend-specific volatility statistics."""
    ret = np.log(prices / prices.shift(1)).dropna()
    ret_sq = ret ** 2
    abs_ret = ret.abs()

    dow = ret.index.dayofweek  # 0=Mon, 4=Fri

    # Returns by day of week
    days = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri'}
    day_stats = {}
    for d, name in days.items():
        mask = dow == d
        r = ret[mask]
        day_stats[name] = {
            'mean_abs_ret': float(r.abs().mean()),
            'var_ret': float(r.var()),
            'mean_ret_sq': float((r**2).mean()),
            'n': int(mask.sum()),
            'mean_ret': float(r.mean()),
            'std_ret': float(r.std()),
        }

    # Weekend ratio: Var(Mon return) / Var(avg Tue-Fri return)
    # Mon return = Fri close → Mon close (3 calendar days)
    # Weekday return = 1 calendar day
    # Under H0 (no weekend effect): Var(Mon) = 3 × Var(weekday)
    # Weekend ratio = Var(Mon) / (3 × Var(avg Tue-Fri))
    mon_var = day_stats['Mon']['var_ret']
    weekday_var = np.mean([day_stats[d]['var_ret'] for d in ['Tue', 'Wed', 'Thu', 'Fri']])
    weekend_ratio = mon_var / (3 * weekday_var) if weekday_var > 0 else np.nan

    # Alternative: using mean(r²) instead of var
    mon_r2 = day_stats['Mon']['mean_ret_sq']
    weekday_r2 = np.mean([day_stats[d]['mean_ret_sq'] for d in ['Tue', 'Wed', 'Thu', 'Fri']])
    weekend_ratio_r2 = mon_r2 / (3 * weekday_r2) if weekday_r2 > 0 else np.nan

    # French-Roll (1986) style: Var(weekend) / Var(weekday) raw (no 3x adjustment)
    fr_ratio = mon_var / weekday_var if weekday_var > 0 else np.nan

    # Bootstrap CI for weekend_ratio
    n_boot = 10000
    boot_ratios = []
    mon_returns = ret[dow == 0].values
    wkday_returns = ret[(dow >= 1) & (dow <= 4)].values
    rng = np.random.default_rng(42)
    for _ in range(n_boot):
        b_mon = rng.choice(mon_returns, size=len(mon_returns), replace=True)
        b_wkday = rng.choice(wkday_returns, size=len(wkday_returns), replace=True)
        v_mon = np.var(b_mon, ddof=1)
        v_wkday = np.var(b_wkday, ddof=1)
        if v_wkday > 0:
            boot_ratios.append(v_mon / (3 * v_wkday))
    boot_ratios = np.array(boot_ratios)
    ci_lo, ci_hi = np.percentile(boot_ratios, [2.5, 97.5])

    # F-test: Mon var vs pooled weekday var
    # H0: Var(Mon) = 3 × Var(weekday)
    # Under H0, (Mon_r² / (3×weekday_var)) ~ F(n_mon, n_wkday) approximately
    n_mon = len(mon_returns)
    n_wkday = len(wkday_returns)
    F_stat = mon_var / (3 * weekday_var)
    # Two-sided: p = 2*min(P(F<f), P(F>f))
    p_lo = stats.f.cdf(F_stat, n_mon - 1, n_wkday - 1)
    p_hi = 1 - p_lo
    p_val_f = 2 * min(p_lo, p_hi)

    # ANOVA across all 5 days of |r|
    groups = [abs_ret[dow == d].values for d in range(5)]
    f_anova, p_anova = stats.f_oneway(*groups)

    # Kruskal-Wallis (non-parametric)
    kw_stat, p_kw = stats.kruskal(*groups)

    print(f"\n--- {label} ---")
    print(f"  N: Mon={n_mon}, Weekday(T-F)={n_wkday}")
    print(f"  Var(Mon)={mon_var:.6f}, Var(T-F avg)={weekday_var:.6f}")
    print(f"  French-Roll ratio (raw): {fr_ratio:.3f} (expected 3.0 under no-info)")
    print(f"  Weekend ratio (time-adjusted): {weekend_ratio:.4f} (=1 if no excess)")
    print(f"  Bootstrap 95% CI: [{ci_lo:.4f}, {ci_hi:.4f}]")
    print(f"  F-test p-value: {p_val_f:.4f}")
    print(f"  ANOVA F={f_anova:.2f}, p={p_anova:.4f}")
    print(f"  Kruskal-Wallis H={kw_stat:.2f}, p={p_kw:.4f}")
    for d in ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']:
        s = day_stats[d]
        print(f"    {d}: mean|r|={s['mean_abs_ret']*100:.3f}%, var={s['var_ret']:.6f}, n={s['n']}")

    return {
        'day_stats': day_stats,
        'weekend_ratio': float(weekend_ratio),
        'weekend_ratio_r2': float(weekend_ratio_r2),
        'french_roll_ratio': float(fr_ratio),
        'bootstrap_ci': [float(ci_lo), float(ci_hi)],
        'f_test_p': float(p_val_f),
        'anova_F': float(f_anova),
        'anova_p': float(p_anova),
        'kw_H': float(kw_stat),
        'kw_p': float(p_kw),
        'n_mon': n_mon,
        'n_weekday': n_wkday,
    }


# Run full-sample analysis
all_results = {}
for asset in ['SPY', 'QQQ', 'BTC']:
    all_results[asset] = compute_weekend_stats(price_data[asset], asset)

# ============================================================
# SECTION 3: Temporal Stability (Pre/Post 2020)
# ============================================================
print("\n" + "=" * 75)
print("SECTION 3: Temporal Stability (Pre vs Post 2020)")
print("=" * 75)

temporal_results = {}
for asset in ['SPY', 'QQQ', 'BTC']:
    p = price_data[asset]
    temporal_results[asset] = {}

    if asset == 'BTC':
        periods = {'2014-2019': ('2014-09-01', '2019-12-31'), '2020-2026': ('2020-01-01', '2026-12-31')}
    else:
        periods = {
            '2005-2012': ('2005-01-01', '2012-12-31'),
            '2013-2019': ('2013-01-01', '2019-12-31'),
            '2020-2026': ('2020-01-01', '2026-12-31'),
        }

    for pname, (start, end) in periods.items():
        sub = p[(p.index >= start) & (p.index <= end)]
        if len(sub) > 100:
            temporal_results[asset][pname] = compute_weekend_stats(sub, f"{asset} {pname}")

# ============================================================
# SECTION 4: Friday Vol → Monday Vol Prediction
# ============================================================
print("\n" + "=" * 75)
print("SECTION 4: Friday Vol → Monday Vol Prediction")
print("=" * 75)

transition_results = {}
for asset in ['SPY', 'QQQ']:
    prices = price_data[asset]
    ret = np.log(prices / prices.shift(1)).dropna()
    abs_ret = ret.abs()
    r2 = ret ** 2
    dow = ret.index.dayofweek

    # Build transition DataFrame: for each Monday, pair with preceding Friday
    mon_idx = ret.index[dow == 0]
    pairs = []
    for mi in mon_idx:
        # Find the closest preceding Friday
        for offset in range(1, 5):
            prev = mi - pd.Timedelta(days=offset)
            if prev in ret.index and prev.dayofweek == 4:
                pairs.append({
                    'date': mi,
                    'mon_abs': abs_ret.loc[mi],
                    'mon_r2': r2.loc[mi],
                    'fri_abs': abs_ret.loc[prev],
                    'fri_r2': r2.loc[prev],
                })
                break

    pdf = pd.DataFrame(pairs).set_index('date')

    # Also build Tue→Wed, Wed→Thu, Thu→Fri pairs for comparison
    weekday_pairs = []
    for d_from, d_to in [(1, 2), (2, 3), (3, 4)]:
        from_idx = ret.index[dow == d_from]
        for fi in from_idx:
            ni = fi + pd.Timedelta(days=1)
            if ni in ret.index:
                weekday_pairs.append({
                    'from_abs': abs_ret.loc[fi],
                    'to_abs': abs_ret.loc[ni],
                    'from_r2': r2.loc[fi],
                    'to_r2': r2.loc[ni],
                })
    wdf = pd.DataFrame(weekday_pairs)

    # Correlation: Fri→Mon vs weekday→next_weekday
    corr_fri_mon = pdf['fri_abs'].corr(pdf['mon_abs'])
    corr_weekday = wdf['from_abs'].corr(wdf['to_abs'])

    # Regression: mon_abs ~ fri_abs
    from scipy.stats import linregress
    sl_fm = linregress(pdf['fri_abs'], pdf['mon_abs'])
    sl_wd = linregress(wdf['from_abs'], wdf['to_abs'])

    print(f"\n{asset}: Fri→Mon correlation = {corr_fri_mon:.4f}, weekday→next = {corr_weekday:.4f}")
    print(f"  Fri→Mon regression: β={sl_fm.slope:.4f} (t={sl_fm.slope/sl_fm.stderr:.2f}), R²={sl_fm.rvalue**2:.4f}")
    print(f"  Weekday→next reg:   β={sl_wd.slope:.4f} (t={sl_wd.slope/sl_wd.stderr:.2f}), R²={sl_wd.rvalue**2:.4f}")

    # Fisher z-test to compare correlations
    def fisher_z(r, n):
        z = 0.5 * np.log((1 + r) / (1 - r))
        se = 1 / np.sqrt(n - 3)
        return z, se

    z1, se1 = fisher_z(corr_fri_mon, len(pdf))
    z2, se2 = fisher_z(corr_weekday, len(wdf))
    z_diff = (z1 - z2) / np.sqrt(se1**2 + se2**2)
    p_diff = 2 * (1 - stats.norm.cdf(abs(z_diff)))

    print(f"  Fisher z-test (Fri-Mon vs weekday): z={z_diff:.3f}, p={p_diff:.4f}")

    transition_results[asset] = {
        'corr_fri_mon': float(corr_fri_mon),
        'corr_weekday': float(corr_weekday),
        'beta_fri_mon': float(sl_fm.slope),
        't_fri_mon': float(sl_fm.slope / sl_fm.stderr),
        'r2_fri_mon': float(sl_fm.rvalue**2),
        'beta_weekday': float(sl_wd.slope),
        't_weekday': float(sl_wd.slope / sl_wd.stderr),
        'r2_weekday': float(sl_wd.rvalue**2),
        'fisher_z': float(z_diff),
        'fisher_p': float(p_diff),
        'n_fri_mon': len(pdf),
        'n_weekday': len(wdf),
    }

# ============================================================
# SECTION 5: HAR with Day-of-Week Dummies (IS/OOS)
# ============================================================
print("\n" + "=" * 75)
print("SECTION 5: HAR with Day-of-Week Dummies (OOS Evaluation)")
print("=" * 75)

from sklearn.linear_model import LinearRegression

har_results = {}
for asset in ['SPY', 'QQQ']:
    prices = price_data[asset]
    ret = np.log(prices / prices.shift(1)).dropna()
    rv = ret ** 2  # Daily proxy: r²

    # Build HAR features
    df_har = pd.DataFrame(index=rv.index)
    df_har['rv'] = rv
    df_har['rv_5'] = rv.rolling(5).mean()
    df_har['rv_22'] = rv.rolling(22).mean()
    df_har['target'] = rv.shift(-1)  # predict next day

    # Day-of-week dummies (Mon=0 reference, Tue-Fri dummies)
    dow = rv.index.dayofweek
    for d in range(1, 5):
        df_har[f'dow_{d}'] = (dow == d).astype(int)

    # Monday dummy separately (for HAR + Monday model)
    df_har['is_monday'] = (dow == 0).astype(int)

    df_har = df_har.dropna()

    # IS/OOS split
    is_mask = df_har.index < '2019-01-01'
    oos_mask = df_har.index >= '2019-01-01'

    features_base = ['rv', 'rv_5', 'rv_22']
    features_dow = ['rv', 'rv_5', 'rv_22', 'dow_1', 'dow_2', 'dow_3', 'dow_4']
    features_mon = ['rv', 'rv_5', 'rv_22', 'is_monday']

    models = {
        'HAR_base': features_base,
        'HAR_DOW': features_dow,
        'HAR_Monday': features_mon,
    }

    print(f"\n--- {asset} HAR OOS Evaluation ---")
    print(f"  IS: {df_har[is_mask].index[0].strftime('%Y-%m-%d')} to {df_har[is_mask].index[-1].strftime('%Y-%m-%d')} (n={is_mask.sum()})")
    print(f"  OOS: {df_har[oos_mask].index[0].strftime('%Y-%m-%d')} to {df_har[oos_mask].index[-1].strftime('%Y-%m-%d')} (n={oos_mask.sum()})")

    model_perf = {}
    predictions = {}
    for mname, feats in models.items():
        X_is = df_har.loc[is_mask, feats].values
        y_is = df_har.loc[is_mask, 'target'].values
        X_oos = df_har.loc[oos_mask, feats].values
        y_oos = df_har.loc[oos_mask, 'target'].values

        reg = LinearRegression()
        reg.fit(X_is, y_is)
        y_pred_is = reg.predict(X_is)
        y_pred_oos = reg.predict(X_oos)

        # Ensure positive predictions and targets for QLIKE
        eps = 1e-10
        y_pred_oos = np.maximum(y_pred_oos, eps)
        y_pred_is_pos = np.maximum(y_pred_is, eps)

        # QLIKE loss — filter out zero realized values (r²=0 means exact zero return)
        # QLIKE = E[σ²_real / σ²_pred - log(σ²_real / σ²_pred) - 1]
        # When σ²_real = 0, log(0) = -inf. Standard practice: exclude days with r²=0.
        oos_valid = y_oos > eps
        is_valid = y_is > eps
        qlike_oos = np.mean(y_oos[oos_valid] / y_pred_oos[oos_valid] - np.log(y_oos[oos_valid] / y_pred_oos[oos_valid]) - 1)
        mse_oos = np.mean((y_oos - y_pred_oos) ** 2)

        # IS metrics
        r2_is = 1 - np.sum((y_is - y_pred_is)**2) / np.sum((y_is - y_is.mean())**2)
        qlike_is = np.mean(y_is[is_valid] / y_pred_is_pos[is_valid] - np.log(y_is[is_valid] / y_pred_is_pos[is_valid]) - 1)
        n_oos_valid = int(oos_valid.sum())

        predictions[mname] = {
            'y_oos': y_oos,
            'y_pred_oos': y_pred_oos,
        }

        model_perf[mname] = {
            'qlike_oos': float(qlike_oos),
            'mse_oos': float(mse_oos),
            'r2_is': float(r2_is),
            'qlike_is': float(qlike_is),
            'n_oos': int(len(y_oos)),
        }

        # Report IS coefficients for DOW model
        if mname == 'HAR_DOW':
            print(f"\n  {mname} IS coefficients:")
            for i, f in enumerate(feats):
                print(f"    {f}: {reg.coef_[i]:.6f}")
            print(f"    intercept: {reg.intercept_:.6f}")

        print(f"  {mname}: QLIKE_OOS={qlike_oos:.6f}, MSE_OOS={mse_oos:.2e}, R²_IS={r2_is:.4f}")

    # DM test: HAR_DOW vs HAR_base (OOS QLIKE)
    y_oos = predictions['HAR_base']['y_oos']
    pred_base = predictions['HAR_base']['y_pred_oos']
    pred_dow = predictions['HAR_DOW']['y_pred_oos']
    pred_mon = predictions['HAR_Monday']['y_pred_oos']

    # QLIKE pointwise losses — exclude zero realized values
    valid = y_oos > 1e-10
    y_v = y_oos[valid]
    pb_v = pred_base[valid]
    pd_v = pred_dow[valid]
    pm_v = pred_mon[valid]
    loss_base = y_v / pb_v - np.log(y_v / pb_v) - 1
    loss_dow = y_v / pd_v - np.log(y_v / pd_v) - 1
    loss_mon = y_v / pm_v - np.log(y_v / pm_v) - 1
    print(f"  (QLIKE computed on {valid.sum()}/{len(y_oos)} non-zero days)")

    # DM test (manual HAC, since these are forecast losses not strategy returns)
    def dm_test_manual(loss1, loss2, h=1):
        """DM test with HAC(Newey-West) standard errors."""
        d = loss1 - loss2  # positive = model 2 better
        n = len(d)
        d_bar = np.mean(d)

        # HAC variance with Newey-West kernel
        bandwidth = int(np.floor(4 * (n / 100) ** (2/9)))
        gamma_0 = np.var(d, ddof=1)
        gamma_sum = 0
        for k in range(1, bandwidth + 1):
            w = 1 - k / (bandwidth + 1)
            gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
            gamma_sum += 2 * w * gamma_k
        var_d = (gamma_0 + gamma_sum) / n
        if var_d <= 0:
            return 0.0, 1.0
        t_stat = d_bar / np.sqrt(var_d)
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
        return float(t_stat), float(p_val)

    dm_dow, p_dow = dm_test_manual(loss_base, loss_dow)
    dm_mon, p_mon = dm_test_manual(loss_base, loss_mon)

    print(f"\n  DM test (HAR_base vs HAR_DOW): t={dm_dow:.3f}, p={p_dow:.4f}")
    print(f"  DM test (HAR_base vs HAR_Monday): t={dm_mon:.3f}, p={p_mon:.4f}")
    print(f"  (Positive t = DOW/Monday model better)")

    # Check: OOS QLIKE on Mondays only vs other days (within valid subset)
    oos_dow_arr = df_har.loc[oos_mask].index.dayofweek.values
    oos_dow_valid = oos_dow_arr[valid]  # subset to valid (non-zero r²) days
    mon_valid_mask = (oos_dow_valid == 0)
    if mon_valid_mask.sum() > 50:
        qlike_base_mon = np.mean(loss_base[mon_valid_mask])
        qlike_dow_mon = np.mean(loss_dow[mon_valid_mask])
        qlike_base_other = np.mean(loss_base[~mon_valid_mask])
        qlike_dow_other = np.mean(loss_dow[~mon_valid_mask])
        print(f"\n  QLIKE on Mondays only: base={qlike_base_mon:.6f}, DOW={qlike_dow_mon:.6f} (Δ={((qlike_dow_mon/qlike_base_mon)-1)*100:.2f}%)")
        print(f"  QLIKE on non-Monday:   base={qlike_base_other:.6f}, DOW={qlike_dow_other:.6f} (Δ={((qlike_dow_other/qlike_base_other)-1)*100:.2f}%)")
        model_perf['monday_only_qlike_base'] = float(qlike_base_mon)
        model_perf['monday_only_qlike_dow'] = float(qlike_dow_mon)

    model_perf['dm_base_vs_dow'] = {'t': dm_dow, 'p': p_dow}
    model_perf['dm_base_vs_mon'] = {'t': dm_mon, 'p': p_mon}

    har_results[asset] = model_perf


# ============================================================
# SECTION 6: VT Strategy — Monday-adjusted 12/VIX
# ============================================================
print("\n" + "=" * 75)
print("SECTION 6: VT Strategy — Monday-adjusted 12/VIX")
print("=" * 75)

spy = price_data['SPY']
vix = price_data['VIX']

# Align
common_idx = spy.index.intersection(vix.index)
spy_c = spy.loc[common_idx]
vix_c = vix.loc[common_idx]
spy_ret = np.log(spy_c / spy_c.shift(1)).dropna()

# Standard 12/VIX weight
w_base = (12.0 / vix_c).clip(0, 1.5)
w_base = w_base.reindex(spy_ret.index)

# Lagged weight (shift 1): signal from t-1, return at t
w_base_lag = w_base.shift(1).dropna()

# Monday-adjusted: reduce Monday weight by 20% (hypothesis: excess Monday vol → less exposure)
dow = spy_ret.index.dayofweek
w_mon_adj = w_base.copy()
w_mon_adj[dow == 0] *= 0.80  # 20% reduction on Mondays
w_mon_lag = w_mon_adj.shift(1).dropna()

# Friday-boosted: if Friday VIX is low, boost Monday weight (hypothesis: calm Friday → safe Monday)
# Use Friday's VIX for Monday weight
w_fri_boost = w_base.copy()
vix_pct = vix_c.rolling(252).rank(pct=True)
vix_pct = vix_pct.reindex(spy_ret.index)
# On Mondays, if Friday's VIX percentile < 30, boost by 10%
for i in range(1, len(w_fri_boost)):
    if w_fri_boost.index[i].dayofweek == 0:  # Monday
        prev_idx = w_fri_boost.index[i - 1]
        if prev_idx in vix_pct.index and not np.isnan(vix_pct.loc[prev_idx]):
            if vix_pct.loc[prev_idx] < 0.30:
                w_fri_boost.iloc[i] *= 1.10
            elif vix_pct.loc[prev_idx] > 0.70:
                w_fri_boost.iloc[i] *= 0.90
w_fri_lag = w_fri_boost.shift(1).dropna()

# Align all
common = spy_ret.index.intersection(w_base_lag.index).intersection(w_mon_lag.index).intersection(w_fri_lag.index)
spy_r = spy_ret.loc[common]
wb = w_base_lag.loc[common]
wm = w_mon_lag.loc[common]
wf = w_fri_lag.loc[common]

# OOS only: 2019+
oos_start = '2019-01-01'
oos_mask = common >= oos_start

# Strategy returns
strat_base = (wb * spy_r).loc[oos_mask]
strat_mon = (wm * spy_r).loc[oos_mask]
strat_fri = (wf * spy_r).loc[oos_mask]
bh_ret = spy_r.loc[oos_mask]

def calc_metrics(r, label):
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    print(f"  {label}: CAGR={ann_ret*100:.2f}%, Vol={ann_vol*100:.2f}%, Sharpe={sharpe:.3f}, MDD={mdd*100:.1f}%")
    return {
        'cagr': float(ann_ret),
        'vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'n_days': int(len(r)),
    }

print(f"\nOOS period: {oos_start} to {common[-1].strftime('%Y-%m-%d')} (n={oos_mask.sum()})")
vt_results = {}
vt_results['12vix_base'] = calc_metrics(strat_base, '12/VIX baseline')
vt_results['12vix_mon_adj'] = calc_metrics(strat_mon, '12/VIX Mon-20%')
vt_results['12vix_fri_boost'] = calc_metrics(strat_fri, '12/VIX Fri-boost')
vt_results['buy_hold'] = calc_metrics(bh_ret, 'Buy & Hold SPY')

# DM test: strategy comparisons
try:
    from volpred.stats.model_evaluation import strategy_dm_test
    dm_t_mon, dm_p_mon = strategy_dm_test(strat_base.values, strat_mon.values)
    dm_t_fri, dm_p_fri = strategy_dm_test(strat_base.values, strat_fri.values)
    print(f"\n  DM: base vs Mon-adj: t={dm_t_mon:.3f}, p={dm_p_mon:.4f}")
    print(f"  DM: base vs Fri-boost: t={dm_t_fri:.3f}, p={dm_p_fri:.4f}")
    vt_results['dm_base_vs_mon'] = {'t': float(dm_t_mon), 'p': float(dm_p_mon)}
    vt_results['dm_base_vs_fri'] = {'t': float(dm_t_fri), 'p': float(dm_p_fri)}
except ImportError:
    # Fallback: manual DM
    print("  (volpred.stats not available, using manual DM)")
    d = strat_base.values - strat_mon.values
    t_manual = np.mean(d) / (np.std(d, ddof=1) / np.sqrt(len(d)))
    p_manual = 2 * (1 - stats.t.cdf(abs(t_manual), df=len(d)-1))
    print(f"  DM: base vs Mon-adj: t={t_manual:.3f}, p={p_manual:.4f}")
    vt_results['dm_base_vs_mon'] = {'t': float(t_manual), 'p': float(p_manual)}

# ============================================================
# SECTION 7: VIX Weekend Behavior
# ============================================================
print("\n" + "=" * 75)
print("SECTION 7: VIX Day-of-Week Pattern")
print("=" * 75)

vix_ret = vix.pct_change().dropna()
vix_dow = vix_ret.index.dayofweek

vix_dow_stats = {}
for d, name in {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri'}.items():
    v = vix_ret[vix_dow == d]
    t_stat, p_val = stats.ttest_1samp(v, 0)
    vix_dow_stats[name] = {
        'mean_change': float(v.mean()),
        'std': float(v.std()),
        'n': int(len(v)),
        't_stat': float(t_stat),
        'p_value': float(p_val),
    }
    sig = "*" if abs(t_stat) > 3.0 else ""
    print(f"  {name}: Δ={v.mean()*100:.2f}%, std={v.std()*100:.2f}%, t={t_stat:.2f} {sig} (n={len(v)})")

# ============================================================
# SECTION 8: Compile Results
# ============================================================
print("\n" + "=" * 75)
print("SUMMARY & CONCLUSIONS")
print("=" * 75)

# Interpretation
for asset in ['SPY', 'QQQ', 'BTC']:
    r = all_results[asset]
    wr = r['weekend_ratio']
    ci = r['bootstrap_ci']
    contains_1 = ci[0] <= 1.0 <= ci[1]
    print(f"\n{asset}: Weekend ratio = {wr:.4f} (95% CI: [{ci[0]:.4f}, {ci[1]:.4f}])")
    print(f"  French-Roll ratio = {r['french_roll_ratio']:.3f} (expected 3.0)")
    if contains_1:
        print(f"  → CI contains 1.0: NO excess weekend vol (time-scaling explains it)")
    else:
        if wr > 1:
            print(f"  → CI ABOVE 1.0: EXCESS weekend vol beyond time-scaling")
        else:
            print(f"  → CI BELOW 1.0: Weekend vol LESS than time-scaling predicts")

# Final summary
print(f"\nHAR + DOW dummies OOS:")
for asset in ['SPY', 'QQQ']:
    dm = har_results[asset]['dm_base_vs_dow']
    print(f"  {asset}: DM t={dm['t']:.3f}, p={dm['p']:.4f} — {'SIGNIFICANT' if abs(dm['t']) > 3.0 else 'NOT significant (Harvey t<3.0)'}")

print(f"\nVT Strategy adjustments:")
if 'dm_base_vs_mon' in vt_results:
    dm = vt_results['dm_base_vs_mon']
    print(f"  Mon-adjusted: DM t={dm['t']:.3f}, p={dm['p']:.4f}")
if 'dm_base_vs_fri' in vt_results:
    dm = vt_results['dm_base_vs_fri']
    print(f"  Fri-boost:    DM t={dm['t']:.3f}, p={dm['p']:.4f}")

# ============================================================
# SAVE RESULTS
# ============================================================
final_results = {
    'experiment_id': 'K873',
    'title': 'Weekend Volatility Effect — Calendar Anomaly in Vol Prediction',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, QQQ, BTC-USD, ^VIX)',
    'period': '2005-01 to 2026-04',
    'methodology': {
        'weekend_ratio': 'Var(Mon return) / (3 × Var(avg Tue-Fri return)), with 10000 bootstrap CI',
        'har_oos': 'HAR(5,22) with DOW dummies, IS 2005-2018, OOS 2019-2026, QLIKE loss',
        'vt_strategy': '12/VIX with Monday-adjusted and Friday-boost variants, OOS DM test',
        'reference': 'French & Roll (1986), Patton & Sheppard (2015), Harvey et al (2016) t>3.0',
    },
    'weekend_ratio_analysis': all_results,
    'temporal_stability': {
        asset: {
            pname: {
                'weekend_ratio': v['weekend_ratio'],
                'bootstrap_ci': v['bootstrap_ci'],
                'french_roll_ratio': v['french_roll_ratio'],
                'anova_p': v['anova_p'],
            }
            for pname, v in periods.items()
        }
        for asset, periods in temporal_results.items()
    },
    'transition_prediction': transition_results,
    'har_oos_evaluation': har_results,
    'vt_strategy': vt_results,
    'vix_dow_pattern': vix_dow_stats,
    'conclusions': {},  # filled below
}

# Build conclusions
conclusions = []

# Q1: Weekend ratio
spy_wr = all_results['SPY']['weekend_ratio']
spy_ci = all_results['SPY']['bootstrap_ci']
btc_wr = all_results['BTC']['weekend_ratio']
btc_ci = all_results['BTC']['bootstrap_ci']

if spy_ci[0] <= 1.0 <= spy_ci[1]:
    conclusions.append(f"Q1: SPY weekend ratio = {spy_wr:.3f} (CI: [{spy_ci[0]:.3f}, {spy_ci[1]:.3f}]) — NO excess weekend vol. French-Roll confirmed: weekend variance < 3x weekday.")
else:
    conclusions.append(f"Q1: SPY weekend ratio = {spy_wr:.3f} (CI: [{spy_ci[0]:.3f}, {spy_ci[1]:.3f}]) — {'EXCESS' if spy_wr > 1 else 'DEFICIT'} weekend vol detected.")

conclusions.append(f"Q1b: BTC weekend ratio = {btc_wr:.3f} (CI: [{btc_ci[0]:.3f}, {btc_ci[1]:.3f}]) — BTC trades 24/7, different dynamics.")

# Q2: Transition prediction
for asset in ['SPY', 'QQQ']:
    tr = transition_results[asset]
    conclusions.append(
        f"Q2 {asset}: Fri→Mon corr = {tr['corr_fri_mon']:.3f} vs weekday→next = {tr['corr_weekday']:.3f} "
        f"(Fisher z={tr['fisher_z']:.2f}, p={tr['fisher_p']:.4f})"
    )

# Q3: HAR DOW
for asset in ['SPY', 'QQQ']:
    dm = har_results[asset]['dm_base_vs_dow']
    sig = "significant" if abs(dm['t']) > 3.0 else "NOT significant (Harvey t<3.0)"
    conclusions.append(f"Q3 {asset}: HAR+DOW vs HAR — DM t={dm['t']:.3f} ({sig})")

# Q4: Temporal
for asset in ['SPY', 'BTC']:
    ts = final_results['temporal_stability'][asset]
    periods_str = ", ".join([f"{p}: {v['weekend_ratio']:.3f}" for p, v in ts.items()])
    conclusions.append(f"Q4 {asset}: Weekend ratio by era — {periods_str}")

# Q5: VT
if 'dm_base_vs_mon' in vt_results:
    dm = vt_results['dm_base_vs_mon']
    conclusions.append(
        f"Q5: 12/VIX Mon-adjusted DM t={dm['t']:.3f} — "
        f"{'significant improvement' if abs(dm['t']) > 3.0 else 'NO significant improvement'}"
    )

final_results['conclusions'] = conclusions

for c in conclusions:
    print(f"\n  {c}")

# Save
with open('/Users/yhlai0911/Desktop/volpred-research/experiments/k873_results.json', 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\n\nResults saved to experiments/k873_results.json")
print("=" * 75)
