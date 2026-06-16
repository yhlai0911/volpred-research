"""
K431 v2: Smooth Transition GARCH (STGARCH) — Lookahead Fix Rerun
=================================================================
[提出: 用戶, 執行: Claude, parent task: paper_review_mile_764012ef_rerun_lookahead]

修正自 v1（paper_review_mile_764012ef CONDITIONAL_PASS 後 followup）：
  Fix A: STGARCH-lagvol 的 lagvol_arr 從 full-sample GJR fit (lookahead) 改為
         walk-forward IS-only GJR fit；每 refit cycle 用 IS window 重 fit GJR，
         OOS 段每天 tv[idx] = IS GJR conditional vol at t=idx-1 (filter mode)。
  Fix B: rolling_baseline_oos 切片 iloc[idx-lookback:idx+1] → iloc[idx-lookback:idx]
         （不可見 r[idx]）+ 改用 forecast(horizon=1).variance.iloc[-1,0] 取真正
         1-step-ahead forecast，與 STGARCH 用 tv[idx-1] 做 1-step-ahead 對稱。
  Fix C: STGARCH OOS state propagation：forecast h_t 後保留 h_forecast 作為當期
         variance state，再用 r_t 更新 eps_t，下一期才用 tv[t] 推 h_{t+1}。

預期：headline (STGARCH<GJR, QLIKE ceiling) robust；STGARCH-lagvol margin 可能縮小
（v1 lagvol 已內含 full-sample 後視性，修正後預測效能應略降，但相對 GJR 仍敗）。

若 ranking 反轉（STGARCH-lagvol 顯著贏 GJR，DM p<0.05 且 stat<0）→ 同步修文章 +
send-alert critical。本 script 輸出 k431_stgarch_v2_results.json，由下輪 hourly
interpretation agent 對比 v1 results。


背景:
- K427 發現 SPY-TLT 相關性有結構性斷裂 → regime 存在
- MS-GARCH (P33) in-sample +2.25% 但 OOS -0.01% → abrupt switching overfits
- STGARCH 是中間路線：允許參數漸進變化，可能比 abrupt MS 更 robust

模型:
Logistic Smooth Transition GARCH(1,1):
  h_t = ω₁ + α₁·ε²_{t-1} + β₁·h_{t-1} + G(s_t;γ,c) * [ω₂ + α₂·ε²_{t-1} + β₂·h_{t-1}]
  G(s_t;γ,c) = 1 / (1 + exp(-γ*(s_t - c)))

資產: SPY | 資料: 2005-01-01 ~ 2026-03-25 (yfinance) | OOS: 2023-01-01 ~ 2024-12-31
Refit: 每 63 天 | Transition variables: VIX, |return|, lagged h^0.5
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy import stats
from scipy.special import gammaln
import yfinance as yf
import json, time, warnings
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox
from arch import arch_model

warnings.filterwarnings('ignore')

# ============================================================
# STGARCH CORE: Optimized variance recursion
# ============================================================
def stgarch_filter(params, returns, transition_var):
    """Fast STGARCH variance recursion. Returns h array and eps array."""
    mu, w1, a1, b1, w2, a2, b2, gam, c = params
    T = len(returns)
    eps = returns - mu
    h = np.empty(T)
    h[0] = max(np.var(eps[:min(100, T)]), 1e-6)

    for t in range(1, T):
        arg = gam * (transition_var[t-1] - c)
        if arg > 500: G = 1.0
        elif arg < -500: G = 0.0
        else: G = 1.0 / (1.0 + np.exp(-arg))

        ht = w1 + a1 * eps[t-1]**2 + b1 * h[t-1] + G * (w2 + a2 * eps[t-1]**2 + b2 * h[t-1])
        h[t] = ht if ht > 1e-8 else 1e-8

    return h, eps

def stgarch_negll(params, returns, transition_var):
    """Negative Gaussian log-likelihood."""
    h, eps = stgarch_filter(params, returns, transition_var)
    ll = -0.5 * np.sum(np.log(h) + eps**2 / h)
    return -ll if np.isfinite(ll) else 1e10

def fit_stgarch(returns, tv, tv_name='VIX', n_starts=8):
    """Fit STGARCH with multiple random starts. Returns params dict or None."""
    T = len(returns)

    # Bounds
    if tv_name == 'VIX': c_lo, c_hi = 10.0, 45.0
    elif tv_name == 'abs_ret': c_lo, c_hi = 0.2, 4.0
    else: c_lo, c_hi = 0.3, 4.0

    bounds = [(-1, 1), (1e-6, 5), (1e-6, 0.5), (0.01, 0.999),
              (-3, 3), (-0.3, 0.5), (-0.5, 0.5), (0.01, 200), (c_lo, c_hi)]

    best = None
    np.random.seed(42)

    for i in range(n_starts):
        x0 = [np.mean(returns) + np.random.randn()*0.01,
              np.random.uniform(0.005, 0.1), np.random.uniform(0.02, 0.15),
              np.random.uniform(0.7, 0.95), np.random.uniform(-0.05, 0.05),
              np.random.uniform(-0.05, 0.1), np.random.uniform(-0.1, 0.1),
              np.random.uniform(0.1, 50), np.random.uniform(c_lo, c_hi)]
        try:
            r = minimize(stgarch_negll, x0, args=(returns, tv),
                        method='L-BFGS-B', bounds=bounds,
                        options={'maxiter': 3000, 'ftol': 1e-10})
            if r.success and (best is None or r.fun < best.fun):
                best = r
        except:
            pass

    if best is None:
        return None

    p = best.x
    names = ['mu', 'omega1', 'alpha1', 'beta1', 'omega2', 'alpha2', 'beta2', 'gamma', 'c']
    d = {n: float(v) for n, v in zip(names, p)}
    d['persistence_low'] = d['alpha1'] + d['beta1']
    d['persistence_high'] = (d['alpha1']+d['alpha2']) + (d['beta1']+d['beta2'])
    # The optimizer omits the Gaussian normalizing constant. Add it back for
    # loglik/AIC/BIC comparability with arch_model outputs.
    loglik_no_const = float(-best.fun)
    normal_const = -0.5 * T * np.log(2 * np.pi)
    d['loglik_no_const'] = loglik_no_const
    d['loglik'] = float(loglik_no_const + normal_const)
    d['aic'] = float(2*9 - 2*d['loglik'])
    d['bic'] = float(9*np.log(T) - 2*d['loglik'])
    d['converged'] = True
    d['T'] = T
    d['tv_name'] = tv_name
    return d

# ============================================================
# OOS FORECAST: Efficient rolling with refit
# ============================================================
def stgarch_1step_forecast(params, h_prev, eps_prev, s_prev):
    """Single 1-step ahead STGARCH forecast."""
    mu, w1, a1, b1, w2, a2, b2, gam, c = params
    arg = gam * (s_prev - c)
    if arg > 500: G = 1.0
    elif arg < -500: G = 0.0
    else: G = 1.0 / (1.0 + np.exp(-arg))
    h = w1 + a1*eps_prev**2 + b1*h_prev + G*(w2 + a2*eps_prev**2 + b2*h_prev)
    return max(h, 1e-8)

def rolling_stgarch_oos(returns, tv, dates, oos_start, oos_end, window=2000, refit_every=63, tv_name='VIX'):
    """Rolling OOS forecast. Maintains state between steps for efficiency."""
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]

    if len(oos_idx) == 0:
        return np.array([]), np.array([]), []

    # Pre-compute initial state before OOS
    first_oos = oos_idx[0]

    forecasts, realized, fdates = [], [], []
    params = None
    last_refit = -refit_every

    # Running state
    h_t = None
    eps_t = None

    for count, idx in enumerate(oos_idx):
        # Refit if needed
        if idx - last_refit >= refit_every or params is None:
            est_start = max(0, idx - window)
            est_ret = returns[est_start:idx]
            est_tv = tv[est_start:idx]

            d = fit_stgarch(est_ret, est_tv, tv_name=tv_name, n_starts=3)
            if d is not None:
                params = [d[k] for k in ['mu','omega1','alpha1','beta1','omega2','alpha2','beta2','gamma','c']]
                last_refit = idx
                # Re-initialize state by running filter on recent window
                lookback = min(200, idx)
                h_arr, eps_arr = stgarch_filter(params, returns[idx-lookback:idx], tv[idx-lookback:idx])
                h_t = h_arr[-1]
                eps_t = eps_arr[-1]
            elif params is None:
                continue

        # 1-step forecast
        s_prev = tv[idx-1]
        h_forecast = stgarch_1step_forecast(params, h_t, eps_t, s_prev)

        forecasts.append(h_forecast)
        realized.append(returns[idx]**2)
        fdates.append(dates[idx])

        # Update state after observing r_t. h_forecast is h_t; the next loop
        # computes h_{t+1} from h_t, eps_t, and tv[t].
        mu = params[0]
        h_t = h_forecast
        eps_t = returns[idx] - mu

        if (count+1) % 100 == 0:
            print(f"    {count+1}/{len(oos_idx)} done")

    return np.array(forecasts), np.array(realized), fdates

def compute_walkforward_lagvol(returns_s, dates, oos_start, oos_end, window=2000, refit_every=63):
    """K431 v2 Fix A: walk-forward IS-only GJR conditional volatility.

    回傳同 returns_s 等長的 array。OOS 段每個 idx t 對應位置 lagvol[t-1] 寫入
    用 IS window [t-window, t]（不含 t）fit 的 GJR conditional vol 在 t-1 的值；
    refit cadence 與其他 rolling 一致（每 refit_every 步 refit 一次）。IS 段的
    lagvol 由 first refit 的 res.conditional_volatility backfill（IS 段任一 t 的
    cond_vol 都只用到 r ≤ t，不算 lookahead）。
    """
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]
    lagvol = np.full(len(returns_s), np.nan)
    if len(oos_idx) == 0:
        return lagvol

    current_params = None
    last_refit = -refit_every

    for count, idx in enumerate(oos_idx):
        if idx - last_refit >= refit_every or current_params is None:
            est_start = max(0, idx - window)
            est_ret = returns_s.iloc[est_start:idx]
            try:
                am = arch_model(est_ret, vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')
                res = am.fit(disp='off', options={'maxiter': 3000})
                current_params = res.params
                last_refit = idx
                cv = res.conditional_volatility.values
                # backfill IS window cond_vol (legit: each t in IS uses only r_1..r_t)
                lagvol[est_start:est_start + len(cv)] = cv
            except Exception:
                if current_params is None:
                    continue

        # Filter on data up to t-1 (no peek), write cond_vol[idx-1].
        lookback = min(500, idx)
        recent = returns_s.iloc[idx - lookback:idx]
        try:
            am2 = arch_model(recent, vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')
            res2 = am2.fix(current_params)
            cv2 = res2.conditional_volatility.values
            lagvol[idx - 1] = cv2[-1]
        except Exception:
            pass

        if (count + 1) % 100 == 0:
            print(f"    walkforward lagvol {count+1}/{len(oos_idx)} done")

    return lagvol


def rolling_baseline_oos(returns_s, dates, model_type, oos_start, oos_end, window=2000, refit_every=63):
    """Rolling OOS for GARCH/GJR using arch package."""
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]

    forecasts, realized, fdates = [], [], []
    current_params = None
    last_refit = -refit_every

    for count, idx in enumerate(oos_idx):
        if idx - last_refit >= refit_every or current_params is None:
            est_start = max(0, idx - window)
            est_ret = returns_s.iloc[est_start:idx]
            try:
                if model_type == 'GARCH':
                    am = arch_model(est_ret, vol='GARCH', p=1, q=1, mean='Constant', dist='normal')
                else:
                    am = arch_model(est_ret, vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')
                res = am.fit(disp='off', options={'maxiter': 3000})
                current_params = res.params
                last_refit = idx
            except:
                if current_params is None: continue

        # K431 v2 Fix B: filter on data up to t-1 only (no peek at r_t),
        # then 1-step-ahead forecast to be symmetric with STGARCH (tv[idx-1] feeds h[idx]).
        lookback = min(500, idx)
        recent = returns_s.iloc[idx-lookback:idx]   # 不含 idx 本身
        try:
            if model_type == 'GARCH':
                am2 = arch_model(recent, vol='GARCH', p=1, q=1, mean='Constant', dist='normal')
            else:
                am2 = arch_model(recent, vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')
            res2 = am2.fix(current_params)
            f_obj = res2.forecast(horizon=1, reindex=False)
            h_f = float(f_obj.variance.iloc[-1, 0])
        except:
            if len(forecasts) > 0: h_f = forecasts[-1]
            else: continue

        forecasts.append(h_f)
        realized.append(returns_s.iloc[idx]**2)
        fdates.append(dates[idx])

        if (count+1) % 100 == 0:
            print(f"    {count+1}/{len(oos_idx)} done")

    return np.array(forecasts), np.array(realized), fdates

# ============================================================
# EVALUATION
# ============================================================
def qlike_loss(f, r):
    return np.log(f) + r / f

def compute_metrics(f, r, name=''):
    v = np.isfinite(f) & np.isfinite(r) & (f > 0)
    f, r = f[v], r[v]
    return {'name': name, 'qlike': float(np.mean(np.log(f) + r/f)),
            'mse': float(np.mean((f-r)**2)), 'mae': float(np.mean(np.abs(f-r))),
            'n_obs': int(v.sum()), 'mean_forecast': float(np.mean(f)), 'mean_realized': float(np.mean(r))}

def dm_test(loss1, loss2):
    d = loss1 - loss2
    T = len(d)
    dm = np.mean(d) / np.sqrt(np.var(d, ddof=0) / T)
    p = 2 * (1 - stats.norm.cdf(abs(dm)))
    return float(dm), float(p)

# ============================================================
# MAIN
# ============================================================
print("=" * 70)
print("K431: Smooth Transition GARCH (STGARCH) for SPY")
print("=" * 70)
t_start = time.time()

# --- Data ---
spy = yf.download('SPY', start='2005-01-01', end='2026-03-25', progress=False)
vix_data = yf.download('^VIX', start='2005-01-01', end='2026-03-25', progress=False)
for df in [spy, vix_data]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy['Return'] = spy['Close'].pct_change() * 100
spy = spy.dropna(subset=['Return'])
vix_data = vix_data[['Close']].rename(columns={'Close': 'VIX'})
data = spy[['Close', 'Return']].join(vix_data['VIX'], how='inner').dropna()

ret_arr = data['Return'].values
vix_arr = data['VIX'].values
abs_ret_arr = np.abs(ret_arr)
dates_arr = data.index
ret_series = data['Return']

print(f"Data: {dates_arr[0].strftime('%Y-%m-%d')} to {dates_arr[-1].strftime('%Y-%m-%d')}, N={len(data)}")
print(f"VIX range: {vix_arr.min():.1f} - {vix_arr.max():.1f}")

# --- Descriptive stats ---
print(f"\nDescriptive: mean={np.mean(ret_arr):.4f}%, std={np.std(ret_arr):.4f}%, "
      f"skew={stats.skew(ret_arr):.3f}, kurt={stats.kurtosis(ret_arr):.1f}")
adf_s, adf_p = adfuller(ret_arr, maxlag=20, autolag='AIC')[:2]
arch_s, arch_p = het_arch(ret_arr, nlags=10)[:2]
print(f"ADF: {adf_s:.2f} (p={adf_p:.6f}), ARCH-LM(10): {arch_s:.1f} (p={arch_p:.2e})")

# --- Lagged vol from GJR ---
# v2: 保留 full-sample lagvol_arr 給 *full-sample* STGARCH 估計使用（in-sample 評估
# 本就允許用 full-sample tv，無 lookahead 問題）。OOS rolling 段另用 walk-forward
# IS-only lagvol（lagvol_oos_arr）取代，修正 v1 lookahead。
gjr_full = arch_model(ret_series, vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')
gjr_res = gjr_full.fit(disp='off')
lagvol_arr = gjr_res.conditional_volatility.values  # for full-sample STGARCH only

# ============================================================
# FULL-SAMPLE ESTIMATION
# ============================================================
print("\n" + "=" * 70)
print("FULL-SAMPLE STGARCH ESTIMATION")
print("=" * 70)

fs_results = {}
for tv_name, tv in [('VIX', vix_arr), ('abs_ret', abs_ret_arr), ('lag_vol', lagvol_arr)]:
    print(f"\n--- {tv_name} transition ---")
    t0 = time.time()
    d = fit_stgarch(ret_arr, tv, tv_name=tv_name, n_starts=10)
    elapsed = time.time() - t0
    if d:
        fs_results[f'STGARCH_{tv_name}'] = d
        print(f"  Time: {elapsed:.0f}s | LogLik: {d['loglik']:.1f} | BIC: {d['bic']:.1f}")
        print(f"  gamma={d['gamma']:.3f} c={d['c']:.3f} | pers_low={d['persistence_low']:.3f} pers_high={d['persistence_high']:.3f}")

        # Check for issues
        if d['persistence_low'] > 1.0:
            print(f"  ⚠️ Low-regime persistence > 1 ({d['persistence_low']:.3f})")
        if d['persistence_high'] > 1.0:
            print(f"  ⚠️ High-regime persistence > 1 ({d['persistence_high']:.3f})")
        if d['gamma'] > 100:
            print(f"  ⚠️ Very large gamma → abrupt transition (≈ Markov switching)")
    else:
        print(f"  FAILED to converge")

# Baseline full-sample
garch_full = arch_model(ret_series, vol='GARCH', p=1, q=1, mean='Constant', dist='normal').fit(disp='off')
print(f"\nGARCH(1,1) full: LogLik={garch_full.loglikelihood:.1f} BIC={garch_full.bic:.1f} AIC={garch_full.aic:.1f}")
gp = gjr_res.params
print(f"GJR(1,1)   full: LogLik={gjr_res.loglikelihood:.1f} BIC={gjr_res.bic:.1f} AIC={gjr_res.aic:.1f}")
print(f"  omega={gp['omega']:.6f} alpha={gp['alpha[1]']:.4f} gamma={gp['gamma[1]']:.4f} beta={gp['beta[1]']:.4f}")

# AIC/BIC table
print(f"\n{'Model':<25} {'k':>3} {'LogLik':>10} {'AIC':>10} {'BIC':>10}")
print("-" * 62)
models_is = [('GARCH(1,1)', len(garch_full.params), garch_full.loglikelihood, garch_full.aic, garch_full.bic),
             ('GJR-GARCH(1,1)', len(gjr_res.params), gjr_res.loglikelihood, gjr_res.aic, gjr_res.bic)]
for name, d in fs_results.items():
    models_is.append((name, 9, d['loglik'], d['aic'], d['bic']))
for name, k, ll, aic, bic in sorted(models_is, key=lambda x: x[4]):
    print(f"{name:<25} {k:>3} {ll:>10.1f} {aic:>10.1f} {bic:>10.1f}")

# --- Residual diagnostics for best STGARCH ---
if 'STGARCH_VIX' in fs_results:
    d = fs_results['STGARCH_VIX']
    p_best = [d[k] for k in ['mu','omega1','alpha1','beta1','omega2','alpha2','beta2','gamma','c']]
    h_full, eps_full = stgarch_filter(p_best, ret_arr, vix_arr)
    z = eps_full / np.sqrt(h_full)
    arch_z_s, arch_z_p = het_arch(z, nlags=10)[:2]
    print(f"\nResidual diagnostics (STGARCH-VIX):")
    print(f"  Std resid: mean={np.mean(z):.3f} std={np.std(z):.3f} skew={stats.skew(z):.3f} kurt={stats.kurtosis(z):.1f}")
    print(f"  ARCH-LM(10) on z: stat={arch_z_s:.1f} p={arch_z_p:.4f} {'(remaining ARCH!)' if arch_z_p<0.05 else '(clean)'}")

# ============================================================
# ROLLING OOS FORECASTING
# ============================================================
print("\n" + "=" * 70)
print("ROLLING OOS (2023-01 to 2024-12, w=2000, refit=63d)")
print("=" * 70)

oos_start, oos_end = '2023-01-01', '2024-12-31'

# v2 Fix A: build walk-forward IS-only lagvol for OOS STGARCH-lagvol.
print("\n[pre] Building walk-forward IS-only lagvol (Fix A)...")
t0 = time.time()
lagvol_oos_arr = compute_walkforward_lagvol(ret_series, dates_arr, oos_start, oos_end)
print(f"  {time.time()-t0:.0f}s, non-nan={(~np.isnan(lagvol_oos_arr)).sum()}")

# GARCH baseline
print("\n[1/5] GARCH(1,1)...")
t0 = time.time()
f_garch, r_garch, d_garch = rolling_baseline_oos(ret_series, dates_arr, 'GARCH', oos_start, oos_end)
print(f"  {time.time()-t0:.0f}s, n={len(f_garch)}")

# GJR baseline
print("\n[2/5] GJR-GARCH(1,1)...")
t0 = time.time()
f_gjr, r_gjr, d_gjr = rolling_baseline_oos(ret_series, dates_arr, 'GJR', oos_start, oos_end)
print(f"  {time.time()-t0:.0f}s, n={len(f_gjr)}")

# STGARCH-VIX
print("\n[3/5] STGARCH-VIX...")
t0 = time.time()
f_sv, r_sv, d_sv = rolling_stgarch_oos(ret_arr, vix_arr, dates_arr, oos_start, oos_end, tv_name='VIX')
print(f"  {time.time()-t0:.0f}s, n={len(f_sv)}")

# STGARCH-|ret|
print("\n[4/5] STGARCH-|ret|...")
t0 = time.time()
f_sr, r_sr, d_sr = rolling_stgarch_oos(ret_arr, abs_ret_arr, dates_arr, oos_start, oos_end, tv_name='abs_ret')
print(f"  {time.time()-t0:.0f}s, n={len(f_sr)}")

# STGARCH-lagvol — v2 Fix A: use walk-forward IS-only lagvol (lagvol_oos_arr)
print("\n[5/5] STGARCH-lagvol (walk-forward IS-only tv)...")
t0 = time.time()
f_sl, r_sl, d_sl = rolling_stgarch_oos(ret_arr, lagvol_oos_arr, dates_arr, oos_start, oos_end, tv_name='lag_vol')
print(f"  {time.time()-t0:.0f}s, n={len(f_sl)}")

# ============================================================
# OOS COMPARISON
# ============================================================
print("\n" + "=" * 70)
print("OOS PERFORMANCE COMPARISON")
print("=" * 70)

models = [('GARCH(1,1)', f_garch, r_garch),
          ('GJR-GARCH(1,1)', f_gjr, r_gjr),
          ('STGARCH-VIX', f_sv, r_sv),
          ('STGARCH-|ret|', f_sr, r_sr),
          ('STGARCH-lagvol', f_sl, r_sl)]

all_metrics = []
print(f"\n{'Model':<20} {'QLIKE':>10} {'MSE':>10} {'MAE':>8} {'N':>5}")
print("-" * 57)
for name, f, r in models:
    m = compute_metrics(f, r, name)
    all_metrics.append(m)
    print(f"{name:<20} {m['qlike']:>10.4f} {m['mse']:>10.4f} {m['mae']:>8.4f} {m['n_obs']:>5}")

# DM tests vs GJR
print(f"\n{'Model':<20} {'DM t':>8} {'p-value':>10} {'QLIKE Δ%':>10} {'Result':>15}")
print("-" * 67)

dm_results = {}
n_common = min(len(f_gjr), min(len(f_sv), min(len(f_sr), len(f_sl))))

for name, f, r in models:
    if 'GJR' in name: continue
    n = min(len(f), len(f_gjr))
    l1 = qlike_loss(f[:n], r[:n])
    l2 = qlike_loss(f_gjr[:n], r_gjr[:n])
    t_dm, p_dm = dm_test(l1, l2)
    qdiff = (np.mean(l1) - np.mean(l2)) / abs(np.mean(l2)) * 100
    sig = "***" if p_dm < 0.01 else "**" if p_dm < 0.05 else "*" if p_dm < 0.10 else "NS"
    result = f"{'STGARCH wins' if t_dm < -1.96 else 'GJR wins' if t_dm > 1.96 else 'No diff'} {sig}"
    dm_results[name] = {'dm_stat': t_dm, 'dm_pvalue': p_dm, 'qlike_diff_pct': qdiff, 'result': result}
    print(f"{name:<20} {t_dm:>8.3f} {p_dm:>10.6f} {qdiff:>9.3f}% {result:>15}")

# Also GJR vs GARCH
n = min(len(f_gjr), len(f_garch))
l_gjr = qlike_loss(f_gjr[:n], r_gjr[:n])
l_g = qlike_loss(f_garch[:n], r_garch[:n])
t_gg, p_gg = dm_test(l_gjr, l_g)
qdiff_gg = (np.mean(l_gjr) - np.mean(l_g)) / abs(np.mean(l_g)) * 100
print(f"{'GJR vs GARCH':<20} {t_gg:>8.3f} {p_gg:>10.6f} {qdiff_gg:>9.3f}%")

# ============================================================
# TRANSITION FUNCTION ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("TRANSITION FUNCTION ANALYSIS")
print("=" * 70)

trans_analysis = {}
for tv_name, d in fs_results.items():
    gam, c = d['gamma'], d['c']
    if 'VIX' in tv_name: label = 'VIX'
    elif 'absret' in tv_name or 'abs_ret' in tv_name: label = '|return|'
    else: label = 'cond_vol'

    G25 = c - np.log(3)/gam if gam > 0 else None
    G75 = c + np.log(3)/gam if gam > 0 else None
    width = (G75 - G25) if G25 and G75 else None

    print(f"\n{tv_name}:")
    print(f"  gamma={gam:.3f} ({'abrupt' if gam>50 else 'smooth' if gam<5 else 'moderate'}), c={c:.3f} ({label})")
    if width: print(f"  G: 0.25 at {label}={G25:.2f}, 0.75 at {label}={G75:.2f}, width={width:.2f}")

    p = d
    print(f"  Low  regime (G→0): ω={p['omega1']:.4f} α={p['alpha1']:.4f} β={p['beta1']:.4f} pers={p['persistence_low']:.4f}")
    w_h = p['omega1']+p['omega2']
    a_h = p['alpha1']+p['alpha2']
    b_h = p['beta1']+p['beta2']
    print(f"  High regime (G→1): ω={w_h:.4f} α={a_h:.4f} β={b_h:.4f} pers={p['persistence_high']:.4f}")

    trans_analysis[tv_name] = {
        'gamma': gam, 'c': c, 'G25_threshold': G25, 'G75_threshold': G75,
        'width': width, 'speed': 'abrupt' if gam>50 else 'smooth' if gam<5 else 'moderate'
    }

# ============================================================
# COMPILE & SAVE RESULTS
# ============================================================
t_total = time.time() - t_start

best_model = min(all_metrics, key=lambda x: x['qlike'])
gjr_m = [m for m in all_metrics if 'GJR' in m['name']][0]
best_st = min([m for m in all_metrics if 'ST' in m['name']], key=lambda x: x['qlike'])
st_diff = (best_st['qlike'] - gjr_m['qlike']) / abs(gjr_m['qlike']) * 100

# Check if any STGARCH beats GJR significantly
any_sig_win = any(v['dm_pvalue'] < 0.05 and v['dm_stat'] < 0
                   for k, v in dm_results.items() if 'ST' in k)

if any_sig_win:
    conclusion = f"STGARCH BEATS GJR significantly! Best: {best_st['name']} (QLIKE diff {st_diff:.3f}%)"
elif best_st['qlike'] < gjr_m['qlike']:
    conclusion = f"STGARCH numerically better but NS. Best: {best_st['name']} diff={st_diff:.3f}%. QLIKE ceiling holds."
else:
    conclusion = f"STGARCH does NOT beat GJR. Best ST: {best_st['name']} diff={st_diff:.3f}%. QLIKE ceiling confirmed."

print(f"\n{'='*70}")
print(f"CONCLUSION: {conclusion}")
print(f"Runtime: {t_total:.0f}s")
print(f"{'='*70}")

results = {
    'experiment_id': 'K431_v2',
    'title': 'STGARCH Volatility Forecasting — Lookahead Fix Rerun',
    'parent_review_task': 'paper_review_mile_764012ef',
    'fixes_applied': [
        'A: walk-forward IS-only GJR cond_vol for STGARCH-lagvol tv (replaces full-sample lagvol_arr)',
        'B: rolling_baseline_oos slice iloc[idx-lookback:idx] (no peek) + forecast(horizon=1).variance for true 1-step-ahead',
        'C: STGARCH OOS state propagation uses h_forecast as current h_t before next-day recursion',
        'D: STGARCH in-sample loglik/AIC/BIC add Gaussian normalizing constant for arch_model comparability'
    ],
    'proposer': '用戶', 'executor': 'Claude',
    'asset': 'SPY', 'data_source': 'yfinance',
    'data_period': f"{dates_arr[0].strftime('%Y-%m-%d')} to {dates_arr[-1].strftime('%Y-%m-%d')}",
    'total_obs': len(data), 'oos_period': f"{oos_start} to {oos_end}",
    'window': 2000, 'refit_every': 63, 'runtime_seconds': round(t_total, 1),
    'descriptive': {
        'mean': float(np.mean(ret_arr)), 'std': float(np.std(ret_arr)),
        'skew': float(stats.skew(ret_arr)), 'kurt': float(stats.kurtosis(ret_arr)),
        'adf_p': float(adf_p), 'arch_lm_p': float(arch_p)
    },
    'full_sample': {k: {kk: (float(vv) if isinstance(vv, (np.floating, float, int, np.integer)) else vv)
                        for kk, vv in v.items()} for k, v in fs_results.items()},
    'in_sample_comparison': [{'model': m[0], 'k': m[1], 'loglik': float(m[2]), 'aic': float(m[3]), 'bic': float(m[4])}
                              for m in sorted(models_is, key=lambda x: x[4])],
    'oos_metrics': all_metrics,
    'dm_tests': dm_results,
    'transition_analysis': trans_analysis,
    'conclusion': conclusion
}

out_path = 'experiments/k431/k431_stgarch_v2_results.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\nSaved: {out_path}")
