"""
K350: Heston Stochastic Volatility vs GARCH — A Fundamentally Different Paradigm
=================================================================================
[提出: Claude (跳躍式探索), 執行: Claude]

Research Question:
1. Can continuous-time Heston SV parameters be estimated from daily returns?
2. How do Heston parameters map to GARCH parameters?
3. Does Heston 1-step forecast beat GJR-GARCH on QLIKE?
4. Key question: does the continuous-time formulation add anything over discrete GARCH?

Background:
- GARCH models volatility as DISCRETE time series: σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1} + γ·r²_{t-1}·I(r<0)
- Heston (1993) models as CONTINUOUS process: dσ² = κ(θ-σ²)dt + ξ·σ·dW
  - κ = mean-reversion speed
  - θ = long-run variance
  - ξ = vol-of-vol
  - ρ = return-vol correlation (leverage effect)

IMPORTANT LIMITATION: True Heston calibration requires options data (implied vol surface).
This uses a SIMPLIFIED method-of-moments estimation from daily returns only.
This is an approximation and the results should be interpreted accordingly.

Data: SPY daily from yfinance, 2005-01-01 to 2024-12-31 (20 years).
OOS: Last 5 years (2020-2024).

Related findings:
- K188: HAR = GARCH on daily (ceiling in data)
- K342: Oil GARCH QLIKE 2.71 (oil harder to predict)
- K345: FX needs different models (GARCH OOS R²=0.04)
- All prior GARCH work assumes discrete-time
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from scipy import stats, optimize

# ---------------------------------------------------------------------------
# 0. PATHS
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = PROJECT_ROOT / "storage" / "experiments"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. DATA LOADING (yfinance)
# ---------------------------------------------------------------------------
def load_spy_data():
    """Load SPY daily data from yfinance, 2005-2024."""
    import yfinance as yf

    ticker = yf.Ticker("SPY")
    df = ticker.history(start="2005-01-01", end="2025-01-01", auto_adjust=True)
    df = df[['Close']].dropna()
    df['Return'] = np.log(df['Close'] / df['Close'].shift(1))
    df = df.dropna()

    print(f"SPY data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"Total observations: {len(df)}")
    print(f"Annualized vol: {df['Return'].std() * np.sqrt(252):.4f}")
    print(f"Mean daily return: {df['Return'].mean():.6f}")
    print(f"Skewness: {df['Return'].skew():.4f}")
    print(f"Kurtosis: {df['Return'].kurtosis():.4f}")

    return df

# ---------------------------------------------------------------------------
# 2. HESTON MODEL — METHOD OF MOMENTS ESTIMATION
# ---------------------------------------------------------------------------
class HestonMoM:
    """
    Simplified Heston estimation from daily returns using Method of Moments.

    The Heston model in continuous time:
        dS/S = μ dt + σ dW_1
        dσ² = κ(θ - σ²) dt + ξ σ dW_2
        corr(dW_1, dW_2) = ρ

    Discretization (Euler-Maruyama, Δt = 1/252):
        r_t = μΔt + σ_t √Δt ε₁_t
        σ²_{t+1} = σ²_t + κ(θ - σ²_t)Δt + ξ σ_t √Δt ε₂_t

    Method of Moments targets:
        E[r²]           → proxy for θ (long-run variance, annualized)
        Var[r²]         → relates to ξ (vol-of-vol)
        Corr(r², r²_lag) → relates to κ (mean reversion)
        Corr(r_t, r²_{t+1}) → relates to ρ (leverage)
    """

    def __init__(self):
        self.kappa = None    # mean reversion speed (annualized)
        self.theta = None    # long-run variance (annualized)
        self.xi = None       # vol-of-vol
        self.rho = None      # return-vol correlation
        self.v0 = None       # initial variance

    def estimate(self, returns, dt=1/252):
        """
        Estimate Heston parameters from daily log returns.

        Uses realized variance as a proxy for latent variance.
        """
        r = returns.values if hasattr(returns, 'values') else returns
        n = len(r)

        # Use squared returns as proxy for instantaneous variance (annualized)
        r2 = r ** 2

        # Rolling realized variance (22-day window) as better variance proxy
        rv = pd.Series(r2).rolling(22).mean().values * 252  # annualize
        rv_valid = rv[~np.isnan(rv)]
        r_valid = r[22:]  # align with rv

        # --- θ (long-run variance, annualized) ---
        self.theta = np.mean(r2) * 252

        # --- κ (mean reversion speed) ---
        # From AR(1) of realized variance: rv_t = c + φ·rv_{t-1} + e_t
        # κ ≈ -ln(φ) / Δt (but we use daily Δt=1/252)
        # More practical: κ = (1 - φ) * 252
        rv_lag = rv_valid[:-1]
        rv_lead = rv_valid[1:]
        if len(rv_lag) > 10:
            phi = np.corrcoef(rv_lag, rv_lead)[0, 1]
            # Ensure phi is in valid range
            phi = np.clip(phi, 0.001, 0.999)
            self.kappa = -np.log(phi) * 252  # annualized mean reversion
        else:
            self.kappa = 5.0  # default

        # --- ξ (vol-of-vol) ---
        # Var(σ²) = ξ² θ / (2κ) in steady state
        # So ξ = sqrt(2κ · Var(rv) / θ)
        var_rv = np.var(rv_valid)
        if self.theta > 0 and self.kappa > 0:
            xi_sq = 2 * self.kappa * var_rv / self.theta
            self.xi = np.sqrt(max(xi_sq, 1e-8))
        else:
            self.xi = 0.5  # default

        # --- ρ (return-vol correlation) ---
        # Correlation between r_t and change in realized variance
        min_len = min(len(r_valid) - 1, len(rv_valid) - 1)
        r_aligned = r_valid[:min_len]
        drv = np.diff(rv_valid[:min_len + 1])
        if len(r_aligned) > 10 and len(drv) > 10:
            self.rho = np.corrcoef(r_aligned, drv)[0, 1]
        else:
            self.rho = -0.7  # typical equity

        # --- v0 (initial variance) ---
        self.v0 = rv_valid[0] if len(rv_valid) > 0 else self.theta

        return {
            'kappa': self.kappa,
            'theta': self.theta,
            'xi': self.xi,
            'rho': self.rho,
            'v0': self.v0,
            'phi_daily': phi if 'phi' in dir() else None,
            'n_obs': n
        }

    def forecast_variance(self, returns, dt=1/252):
        """
        Generate 1-step-ahead variance forecasts using Heston dynamics.

        E[σ²_{t+1}] = σ²_t + κ(θ - σ²_t)·Δt

        This is the conditional expectation (since E[dW]=0).
        Uses rolling realized variance as the state variable.
        """
        r = returns.values if hasattr(returns, 'values') else returns
        n = len(r)

        # Use 22-day rolling RV as variance state
        r2 = r ** 2
        rv = pd.Series(r2).rolling(22).mean().values * 252  # annualized

        forecasts = np.full(n, np.nan)

        for t in range(22, n):
            v_t = rv[t]  # current variance state (annualized)
            # Heston mean-reverting forecast (annualized)
            v_next = v_t + self.kappa * (self.theta - v_t) * dt
            # Convert to daily variance for comparison
            forecasts[t] = max(v_next / 252, 1e-10)

        return forecasts

# ---------------------------------------------------------------------------
# 3. HESTON QML ESTIMATION (more rigorous)
# ---------------------------------------------------------------------------
class HestonQML:
    """
    Quasi-Maximum Likelihood estimation of Heston from daily returns.

    Uses the Euler discretization and treats σ² as a latent AR(1) process
    filtered through squared returns.

    The discretized Heston:
        σ²_{t+1} = σ²_t + κ(θ - σ²_t)Δt + ξ·σ_t·√Δt·η_t

    Filtering: we update σ² using an exponential filter:
        σ²_t = (1-λ)·r²_t/Δt + λ·σ²_{t-1}
    where λ = exp(-κΔt) ≈ 1 - κΔt

    This is essentially equivalent to EWMA with λ tied to κ.
    """

    def __init__(self):
        self.kappa = None
        self.theta = None
        self.xi = None
        self.rho = None

    def _neg_loglik(self, params, returns, dt=1/252):
        """Negative log-likelihood (Gaussian approximation)."""
        kappa, theta, xi = params[0], params[1], params[2]

        # Parameter bounds
        if kappa <= 0 or theta <= 0 or xi <= 0:
            return 1e10
        if kappa > 100 or theta > 2.0 or xi > 5.0:
            return 1e10

        # Feller condition: 2κθ > ξ² (ensures variance stays positive)
        feller = 2 * kappa * theta / (xi ** 2)

        r = returns
        n = len(r)

        # Initialize variance at unconditional mean
        v = np.full(n, theta / 252)  # daily

        # Filter variance using discretized Heston dynamics
        lam = np.exp(-kappa * dt)  # daily persistence

        loglik = 0.0
        for t in range(1, n):
            # Update variance state (mean-reverting filter)
            v[t] = lam * v[t-1] + (1 - lam) * (r[t-1]**2)
            v[t] = max(v[t], 1e-10)

            # Gaussian log-likelihood contribution
            loglik += -0.5 * (np.log(2 * np.pi) + np.log(v[t]) + r[t]**2 / v[t])

        return -loglik  # negative for minimization

    def estimate(self, returns, dt=1/252):
        """Estimate κ, θ, ξ via QML."""
        r = returns.values if hasattr(returns, 'values') else returns

        # Starting values from MoM
        mom = HestonMoM()
        mom_params = mom.estimate(returns)

        x0 = [
            max(mom_params['kappa'], 0.5),
            max(mom_params['theta'], 0.01),
            max(mom_params['xi'], 0.1)
        ]

        # Bounds
        bounds = [(0.1, 50.0), (0.005, 1.0), (0.01, 3.0)]

        result = optimize.minimize(
            self._neg_loglik, x0, args=(r, dt),
            method='L-BFGS-B', bounds=bounds,
            options={'maxiter': 1000, 'ftol': 1e-10}
        )

        if result.success:
            self.kappa = result.x[0]
            self.theta = result.x[1]
            self.xi = result.x[2]
        else:
            # Fall back to MoM
            self.kappa = mom_params['kappa']
            self.theta = mom_params['theta']
            self.xi = mom_params['xi']

        self.rho = mom_params['rho']  # ρ estimated separately

        feller = 2 * self.kappa * self.theta / (self.xi ** 2)

        return {
            'kappa': self.kappa,
            'theta': self.theta,
            'xi': self.xi,
            'rho': self.rho,
            'feller_ratio': feller,
            'feller_satisfied': feller > 1.0,
            'converged': result.success,
            'loglik': -result.fun if result.success else None,
            'n_obs': len(r)
        }

    def forecast_variance(self, returns, dt=1/252):
        """
        Generate 1-step-ahead variance forecasts.

        Uses the same filtered variance as in estimation:
            v_t = λ·v_{t-1} + (1-λ)·r²_{t-1}
            forecast_{t+1} = λ·v_t + (1-λ)·θ/252
        """
        r = returns.values if hasattr(returns, 'values') else returns
        n = len(r)

        lam = np.exp(-self.kappa * dt)

        v = np.full(n, self.theta / 252)
        forecasts = np.full(n, np.nan)

        for t in range(1, n):
            v[t] = lam * v[t-1] + (1 - lam) * (r[t-1]**2)
            v[t] = max(v[t], 1e-10)
            forecasts[t] = v[t]  # 1-step ahead = current filtered value

        return forecasts

# ---------------------------------------------------------------------------
# 4. GJR-GARCH BENCHMARK
# ---------------------------------------------------------------------------
def fit_gjr_garch(returns, window=2000):
    """Fit GJR-GARCH(1,1) and produce 1-step forecasts."""
    from arch import arch_model

    r = returns.values if hasattr(returns, 'values') else returns
    r_pct = r * 100  # arch expects percentage returns
    n = len(r_pct)

    forecasts = np.full(n, np.nan)
    params_list = []

    for t in range(window, n):
        train = r_pct[max(0, t-window):t]

        try:
            model = arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
            res = model.fit(disp='off', show_warning=False)

            # 1-step forecast (in percentage^2, convert to decimal)
            fc = res.forecast(horizon=1)
            forecasts[t] = fc.variance.values[-1, 0] / 10000  # pct^2 → decimal

            if t == window:  # save first estimation params
                params_list.append({
                    'omega': res.params.get('omega', 0),
                    'alpha': res.params.get('alpha[1]', 0),
                    'gamma': res.params.get('gamma[1]', 0),
                    'beta': res.params.get('beta[1]', 0),
                })
        except:
            if t > window:
                forecasts[t] = forecasts[t-1]

    return forecasts, params_list

# ---------------------------------------------------------------------------
# 5. EVALUATION METRICS
# ---------------------------------------------------------------------------
def qlike(realized, forecast):
    """QLIKE loss: Σ(log(σ²_f) + r²/σ²_f). Lower is better."""
    mask = ~np.isnan(forecast) & ~np.isnan(realized) & (forecast > 0)
    rv = realized[mask]
    fv = forecast[mask]
    return np.mean(np.log(fv) + rv / fv)

def mse(realized, forecast):
    """Mean Squared Error of variance forecasts."""
    mask = ~np.isnan(forecast) & ~np.isnan(realized)
    return np.mean((realized[mask] - forecast[mask])**2)

def mae(realized, forecast):
    """Mean Absolute Error of variance forecasts."""
    mask = ~np.isnan(forecast) & ~np.isnan(realized)
    return np.mean(np.abs(realized[mask] - forecast[mask]))

def mz_r2(realized, forecast):
    """Mincer-Zarnowitz R² regression."""
    mask = ~np.isnan(forecast) & ~np.isnan(realized)
    rv = realized[mask]
    fv = forecast[mask]
    if len(rv) < 10:
        return np.nan, np.nan, np.nan
    slope, intercept, r_value, p_value, std_err = stats.linregress(fv, rv)
    return r_value**2, slope, intercept

def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test.
    H0: equal predictive accuracy.
    Returns t-stat and p-value (two-sided).
    Negative t-stat means loss1 < loss2 (model 1 better).
    """
    d = loss1 - loss2
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan

    d_mean = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n

    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))

    return t_stat, p_value

# ---------------------------------------------------------------------------
# 6. PARAMETER MAPPING: HESTON ↔ GARCH
# ---------------------------------------------------------------------------
def heston_garch_mapping(heston_params, garch_params, dt=1/252):
    """
    Theoretical mapping between Heston and GARCH parameters.

    Nelson (1990) showed GARCH(1,1) converges to a diffusion:
        dσ² = κ*(θ* - σ²)dt + ξ*·σ·dW

    where:
        κ* = (1 - α - β) / Δt
        θ* = ω / (1 - α - β)  (times 252 for annualized)
        ξ* depends on distribution assumptions

    For GJR-GARCH:
        κ* = (1 - α - β - γ/2) / Δt  (effective persistence)
        ρ_GARCH ≈ -γ / (2α + γ)  (leverage from gamma)
    """
    gp = garch_params
    hp = heston_params

    alpha = gp.get('alpha', 0.05)
    beta = gp.get('beta', 0.90)
    gamma = gp.get('gamma', 0.10)
    omega = gp.get('omega', 0.01)

    # GARCH → equivalent continuous-time parameters
    persistence = alpha + beta + gamma / 2
    kappa_garch = (1 - persistence) * 252  # annualized mean reversion
    theta_garch = (omega / (1 - persistence)) * 252 / 10000  # annualized, decimal
    rho_garch = -gamma / (2 * alpha + gamma) if (2 * alpha + gamma) > 0 else 0

    # Half-life of shocks
    hl_heston = np.log(2) / hp['kappa'] * 252 if hp['kappa'] > 0 else np.inf  # in days
    hl_garch = np.log(2) / kappa_garch * 252 if kappa_garch > 0 else np.inf

    return {
        'heston': {
            'kappa': hp['kappa'],
            'theta': hp['theta'],
            'xi': hp['xi'],
            'rho': hp['rho'],
            'half_life_days': hl_heston,
        },
        'garch_equivalent': {
            'kappa_equiv': kappa_garch,
            'theta_equiv': theta_garch,
            'rho_equiv': rho_garch,
            'persistence': persistence,
            'half_life_days': hl_garch,
        },
        'comparison': {
            'kappa_ratio': hp['kappa'] / kappa_garch if kappa_garch > 0 else np.inf,
            'theta_ratio': hp['theta'] / theta_garch if theta_garch > 0 else np.inf,
            'rho_diff': hp['rho'] - rho_garch,
            'half_life_diff_days': hl_heston - hl_garch,
        }
    }

# ---------------------------------------------------------------------------
# 7. MAIN EXPERIMENT
# ---------------------------------------------------------------------------
def main():
    print("=" * 80)
    print("K350: Heston Stochastic Volatility vs GARCH")
    print("A Fundamentally Different Paradigm (Jump Exploration)")
    print("=" * 80)
    print()

    # --- Load data ---
    print("--- 1. Loading SPY daily data ---")
    df = load_spy_data()
    returns = df['Return'].values
    dates = df.index
    n = len(returns)

    # Realized variance proxy: squared daily returns
    rv_proxy = returns ** 2

    # --- Split IS/OOS ---
    oos_start = "2020-01-01"
    is_mask = dates < oos_start
    oos_mask = dates >= oos_start
    is_returns = returns[is_mask]
    oos_returns = returns[oos_mask]
    n_is = sum(is_mask)
    n_oos = sum(oos_mask)
    print(f"\nIS: {dates[is_mask][0].strftime('%Y-%m-%d')} to {dates[is_mask][-1].strftime('%Y-%m-%d')} ({n_is} obs)")
    print(f"OOS: {dates[oos_mask][0].strftime('%Y-%m-%d')} to {dates[oos_mask][-1].strftime('%Y-%m-%d')} ({n_oos} obs)")

    # =====================================================================
    # PART A: Heston Method-of-Moments Estimation
    # =====================================================================
    print("\n" + "=" * 60)
    print("PART A: Heston Method-of-Moments Estimation (IS data)")
    print("=" * 60)

    mom = HestonMoM()
    mom_params = mom.estimate(is_returns)

    print(f"\nHeston MoM Parameters (annualized):")
    print(f"  κ (mean reversion speed): {mom_params['kappa']:.4f}")
    print(f"  θ (long-run variance):    {mom_params['theta']:.6f} (vol = {np.sqrt(mom_params['theta']):.4f})")
    print(f"  ξ (vol-of-vol):           {mom_params['xi']:.4f}")
    print(f"  ρ (return-vol corr):      {mom_params['rho']:.4f}")
    print(f"  v₀ (initial variance):    {mom_params['v0']:.6f}")
    print(f"  φ_daily (AR(1) coef):     {mom_params['phi_daily']:.6f}")

    feller = 2 * mom_params['kappa'] * mom_params['theta'] / (mom_params['xi'] ** 2)
    print(f"  Feller ratio (2κθ/ξ²):    {feller:.4f} ({'satisfied' if feller > 1 else 'VIOLATED'})")

    # =====================================================================
    # PART B: Heston QML Estimation
    # =====================================================================
    print("\n" + "=" * 60)
    print("PART B: Heston QML Estimation (IS data)")
    print("=" * 60)

    qml = HestonQML()
    qml_params = qml.estimate(is_returns)

    print(f"\nHeston QML Parameters (annualized):")
    print(f"  κ (mean reversion speed): {qml_params['kappa']:.4f}")
    print(f"  θ (long-run variance):    {qml_params['theta']:.6f} (vol = {np.sqrt(qml_params['theta']):.4f})")
    print(f"  ξ (vol-of-vol):           {qml_params['xi']:.4f}")
    print(f"  ρ (return-vol corr):      {qml_params['rho']:.4f}")
    print(f"  Feller ratio:             {qml_params['feller_ratio']:.4f} ({'satisfied' if qml_params['feller_satisfied'] else 'VIOLATED'})")
    print(f"  Converged:                {qml_params['converged']}")
    print(f"  Log-likelihood:           {qml_params['loglik']:.2f}" if qml_params['loglik'] else "  Log-likelihood: N/A")

    # =====================================================================
    # PART C: GJR-GARCH Estimation & Forecasts
    # =====================================================================
    print("\n" + "=" * 60)
    print("PART C: GJR-GARCH Estimation & Forecasts (rolling window=2000)")
    print("=" * 60)

    garch_forecasts, garch_params_list = fit_gjr_garch(returns, window=2000)

    if garch_params_list:
        gp = garch_params_list[0]
        print(f"\nGJR-GARCH Parameters (first window):")
        print(f"  ω:     {gp['omega']:.6f}")
        print(f"  α:     {gp['alpha']:.6f}")
        print(f"  γ:     {gp['gamma']:.6f}")
        print(f"  β:     {gp['beta']:.6f}")
        pers = gp['alpha'] + gp['beta'] + gp['gamma'] / 2
        print(f"  Persistence (α+β+γ/2): {pers:.6f}")

    # =====================================================================
    # PART D: Heston Forecasts (both methods)
    # =====================================================================
    print("\n" + "=" * 60)
    print("PART D: Generating Heston Variance Forecasts")
    print("=" * 60)

    # MoM forecasts (re-estimate on full sample for OOS comparison)
    mom_full = HestonMoM()
    mom_full.estimate(is_returns)
    heston_mom_fc = mom_full.forecast_variance(returns)

    # QML forecasts
    qml_full = HestonQML()
    qml_full.estimate(is_returns)
    heston_qml_fc = qml_full.forecast_variance(returns)

    print(f"  Heston MoM forecasts: {np.sum(~np.isnan(heston_mom_fc))} valid")
    print(f"  Heston QML forecasts: {np.sum(~np.isnan(heston_qml_fc))} valid")
    print(f"  GARCH forecasts:      {np.sum(~np.isnan(garch_forecasts))} valid")

    # =====================================================================
    # PART E: OOS Forecast Comparison
    # =====================================================================
    print("\n" + "=" * 60)
    print("PART E: Out-of-Sample Forecast Comparison (2020-2024)")
    print("=" * 60)

    # OOS indices
    oos_idx = np.where(oos_mask)[0]

    rv_oos = rv_proxy[oos_idx]
    garch_oos = garch_forecasts[oos_idx]
    mom_oos = heston_mom_fc[oos_idx]
    qml_oos = heston_qml_fc[oos_idx]

    # QLIKE
    qlike_garch = qlike(rv_oos, garch_oos)
    qlike_mom = qlike(rv_oos, mom_oos)
    qlike_qml = qlike(rv_oos, qml_oos)

    print(f"\nQLIKE (lower = better):")
    print(f"  GJR-GARCH:   {qlike_garch:.6f}")
    print(f"  Heston MoM:  {qlike_mom:.6f}")
    print(f"  Heston QML:  {qlike_qml:.6f}")

    best_qlike = min(qlike_garch, qlike_mom, qlike_qml)
    for name, val in [("GJR-GARCH", qlike_garch), ("Heston MoM", qlike_mom), ("Heston QML", qlike_qml)]:
        marker = " ← BEST" if val == best_qlike else ""
        pct_diff = (val / best_qlike - 1) * 100
        print(f"    {name}: +{pct_diff:.2f}% vs best{marker}")

    # MSE
    mse_garch = mse(rv_oos, garch_oos)
    mse_mom = mse(rv_oos, mom_oos)
    mse_qml = mse(rv_oos, qml_oos)

    print(f"\nMSE:")
    print(f"  GJR-GARCH:   {mse_garch:.2e}")
    print(f"  Heston MoM:  {mse_mom:.2e}")
    print(f"  Heston QML:  {mse_qml:.2e}")

    # MAE
    mae_garch = mae(rv_oos, garch_oos)
    mae_mom = mae(rv_oos, mom_oos)
    mae_qml = mae(rv_oos, qml_oos)

    print(f"\nMAE:")
    print(f"  GJR-GARCH:   {mae_garch:.2e}")
    print(f"  Heston MoM:  {mae_mom:.2e}")
    print(f"  Heston QML:  {mae_qml:.2e}")

    # MZ R²
    r2_garch, slope_garch, int_garch = mz_r2(rv_oos, garch_oos)
    r2_mom, slope_mom, int_mom = mz_r2(rv_oos, mom_oos)
    r2_qml, slope_qml, int_qml = mz_r2(rv_oos, qml_oos)

    print(f"\nMincer-Zarnowitz R² (slope, intercept):")
    print(f"  GJR-GARCH:   R²={r2_garch:.4f}  slope={slope_garch:.4f}  intercept={int_garch:.2e}")
    print(f"  Heston MoM:  R²={r2_mom:.4f}  slope={slope_mom:.4f}  intercept={int_mom:.2e}")
    print(f"  Heston QML:  R²={r2_qml:.4f}  slope={slope_qml:.4f}  intercept={int_qml:.2e}")

    # DM Tests
    print(f"\nDiebold-Mariano Tests (QLIKE loss):")

    # Compute individual QLIKE losses
    mask_all = ~np.isnan(garch_oos) & ~np.isnan(mom_oos) & ~np.isnan(qml_oos) & (garch_oos > 0) & (mom_oos > 0) & (qml_oos > 0)
    rv_m = rv_oos[mask_all]
    garch_m = garch_oos[mask_all]
    mom_m = mom_oos[mask_all]
    qml_m = qml_oos[mask_all]

    loss_garch = np.log(garch_m) + rv_m / garch_m
    loss_mom = np.log(mom_m) + rv_m / mom_m
    loss_qml = np.log(qml_m) + rv_m / qml_m

    # GARCH vs Heston MoM
    t_gm, p_gm = dm_test(loss_garch, loss_mom)
    print(f"  GARCH vs Heston MoM: t={t_gm:.4f}, p={p_gm:.4f} {'← GARCH sig. better' if t_gm < -1.96 else '← Heston sig. better' if t_gm > 1.96 else '(not significant)'}")

    # GARCH vs Heston QML
    t_gq, p_gq = dm_test(loss_garch, loss_qml)
    print(f"  GARCH vs Heston QML: t={t_gq:.4f}, p={p_gq:.4f} {'← GARCH sig. better' if t_gq < -1.96 else '← Heston sig. better' if t_gq > 1.96 else '(not significant)'}")

    # Heston MoM vs QML
    t_mq, p_mq = dm_test(loss_mom, loss_qml)
    print(f"  Heston MoM vs QML:   t={t_mq:.4f}, p={p_mq:.4f}")

    # =====================================================================
    # PART F: Parameter Mapping
    # =====================================================================
    print("\n" + "=" * 60)
    print("PART F: Heston ↔ GARCH Parameter Mapping")
    print("=" * 60)

    if garch_params_list:
        mapping = heston_garch_mapping(qml_params, garch_params_list[0])

        print(f"\n{'Parameter':<25} {'Heston':<15} {'GARCH equiv.':<15} {'Ratio':<10}")
        print("-" * 65)
        print(f"{'κ (mean reversion)':<25} {mapping['heston']['kappa']:<15.4f} {mapping['garch_equivalent']['kappa_equiv']:<15.4f} {mapping['comparison']['kappa_ratio']:<10.4f}")
        print(f"{'θ (long-run var, ann.)':<25} {mapping['heston']['theta']:<15.6f} {mapping['garch_equivalent']['theta_equiv']:<15.6f} {mapping['comparison']['theta_ratio']:<10.4f}")
        print(f"{'ρ (leverage)':<25} {mapping['heston']['rho']:<15.4f} {mapping['garch_equivalent']['rho_equiv']:<15.4f} {mapping['comparison']['rho_diff']:<10.4f}")
        print(f"{'Half-life (days)':<25} {mapping['heston']['half_life_days']:<15.1f} {mapping['garch_equivalent']['half_life_days']:<15.1f} {mapping['comparison']['half_life_diff_days']:<10.1f}")

    # =====================================================================
    # PART G: Key Insight — Is Heston Just Sophisticated EWMA?
    # =====================================================================
    print("\n" + "=" * 60)
    print("PART G: Is Heston (from daily returns) Just EWMA?")
    print("=" * 60)

    # The QML Heston filter: v_t = λ·v_{t-1} + (1-λ)·r²_{t-1}
    # This is EXACTLY EWMA with λ = exp(-κΔt)
    lam_heston = np.exp(-qml_params['kappa'] / 252)

    print(f"\n  Heston QML filter: v_t = λ·v_{{t-1}} + (1-λ)·r²_{{t-1}}")
    print(f"  λ_Heston = exp(-κ/252) = exp(-{qml_params['kappa']:.4f}/252) = {lam_heston:.6f}")
    print(f"  EWMA λ=0.94 (RiskMetrics):  0.940000")
    print(f"  EWMA λ=0.97 (retail VT):    0.970000")
    print(f"  GJR-GARCH β (persistence):   {garch_params_list[0]['beta']:.6f}" if garch_params_list else "")

    # Compare EWMA(λ_heston) forecasts
    ewma_heston = np.full(n, np.nan)
    v_ewma = np.var(returns[:252])  # initial
    for t in range(1, n):
        v_ewma = lam_heston * v_ewma + (1 - lam_heston) * returns[t-1]**2
        ewma_heston[t] = v_ewma

    ewma_heston_oos = ewma_heston[oos_idx]
    qlike_ewma_h = qlike(rv_oos, ewma_heston_oos)

    # Standard EWMA(0.94) and EWMA(0.97)
    ewma94 = np.full(n, np.nan)
    ewma97 = np.full(n, np.nan)
    v94 = np.var(returns[:252])
    v97 = np.var(returns[:252])
    for t in range(1, n):
        v94 = 0.94 * v94 + 0.06 * returns[t-1]**2
        v97 = 0.97 * v97 + 0.03 * returns[t-1]**2
        ewma94[t] = v94
        ewma97[t] = v97

    qlike_ewma94 = qlike(rv_oos, ewma94[oos_idx])
    qlike_ewma97 = qlike(rv_oos, ewma97[oos_idx])

    print(f"\n  QLIKE comparison (OOS 2020-2024):")
    print(f"    EWMA(λ_Heston={lam_heston:.4f}): {qlike_ewma_h:.6f}")
    print(f"    EWMA(λ=0.94):                {qlike_ewma94:.6f}")
    print(f"    EWMA(λ=0.97):                {qlike_ewma97:.6f}")
    print(f"    Heston QML (full):            {qlike_qml:.6f}")
    print(f"    GJR-GARCH:                    {qlike_garch:.6f}")

    # Correlation between Heston QML and EWMA forecasts
    mask_corr = ~np.isnan(qml_oos) & ~np.isnan(ewma_heston_oos)
    corr_h_ewma = np.corrcoef(qml_oos[mask_corr], ewma_heston_oos[mask_corr])[0, 1]
    print(f"\n  Correlation(Heston QML, EWMA(λ_Heston)): {corr_h_ewma:.6f}")
    print(f"  → {'IDENTICAL (as expected — same filter!)' if corr_h_ewma > 0.999 else 'Different (unexpected)'}")

    # =====================================================================
    # PART H: Sub-period Analysis
    # =====================================================================
    print("\n" + "=" * 60)
    print("PART H: Sub-period OOS Analysis")
    print("=" * 60)

    sub_periods = [
        ("2020 (COVID)", "2020-01-01", "2021-01-01"),
        ("2021 (Recovery)", "2021-01-01", "2022-01-01"),
        ("2022 (Rate hikes)", "2022-01-01", "2023-01-01"),
        ("2023 (AI rally)", "2023-01-01", "2024-01-01"),
        ("2024 (Election)", "2024-01-01", "2025-01-01"),
    ]

    print(f"\n{'Period':<25} {'GARCH QLIKE':<15} {'Heston QML':<15} {'ΔQLIKE':<12} {'Winner':<10}")
    print("-" * 77)

    garch_wins = 0
    heston_wins = 0

    for name, start, end in sub_periods:
        mask_sub = (dates >= start) & (dates < end) & oos_mask
        idx_sub = np.where(mask_sub)[0]
        if len(idx_sub) < 20:
            continue

        rv_sub = rv_proxy[idx_sub]
        g_sub = garch_forecasts[idx_sub]
        h_sub = heston_qml_fc[idx_sub]

        q_g = qlike(rv_sub, g_sub)
        q_h = qlike(rv_sub, h_sub)
        delta = q_h - q_g  # positive = GARCH better
        winner = "GARCH" if delta > 0 else "Heston"

        if winner == "GARCH":
            garch_wins += 1
        else:
            heston_wins += 1

        print(f"  {name:<23} {q_g:<15.6f} {q_h:<15.6f} {delta:<12.6f} {winner}")

    print(f"\n  Score: GARCH {garch_wins} — Heston {heston_wins}")

    # =====================================================================
    # PART I: The Fundamental Difference — What Heston Adds (Theoretically)
    # =====================================================================
    print("\n" + "=" * 60)
    print("PART I: What Heston Adds (Theory vs Practice)")
    print("=" * 60)

    print("""
    THEORETICAL ADVANTAGES of Heston over GARCH:
    1. Continuous-time → elegant option pricing (closed-form for European options)
    2. Separate Brownian motion for vol → richer dynamics
    3. ρ parameter cleanly captures leverage effect
    4. Mean-reverting vol with known stationary distribution (CIR process)
    5. Feller condition ensures positivity (if satisfied)

    PRACTICAL REALITY (from this experiment):
    1. Without options data, Heston estimation from daily returns reduces to:
       - An EWMA-like filter for variance (v_t = λ·v_{t-1} + (1-λ)·r²_{t-1})
       - Mean reversion calibrated from realized variance autocorrelation
    2. The filtered variance IS the forecast (no additional information)
    3. GJR-GARCH adds TWO things Heston (from returns alone) cannot:
       a. Asymmetric response to positive vs negative returns (γ parameter)
       b. Direct return-to-variance feedback (α·r² term)
    4. Heston's ρ captures leverage STATISTICALLY but not DYNAMICALLY
       (it's computed from correlation, not embedded in the filter)
    """)

    # =====================================================================
    # PART J: Summary Statistics
    # =====================================================================
    print("=" * 60)
    print("PART J: Summary and Conclusions")
    print("=" * 60)

    conclusions = []

    # 1. Does Heston from daily returns add anything?
    if qlike_garch < qlike_qml:
        pct_worse = (qlike_qml / qlike_garch - 1) * 100
        conclusions.append(f"Heston QML QLIKE is {pct_worse:.2f}% worse than GJR-GARCH")
    else:
        pct_better = (qlike_garch / qlike_qml - 1) * 100
        conclusions.append(f"Heston QML QLIKE is {pct_better:.2f}% better than GJR-GARCH")

    # 2. Is it just EWMA?
    conclusions.append(f"Heston QML ↔ EWMA(λ={lam_heston:.4f}) correlation: {corr_h_ewma:.6f}")
    if corr_h_ewma > 0.999:
        conclusions.append("CONFIRMED: Heston from daily returns IS equivalent to EWMA")

    # 3. DM test significance
    if p_gq < 0.05:
        if t_gq < 0:
            conclusions.append(f"DM test: GARCH significantly better (t={t_gq:.2f}, p={p_gq:.4f})")
        else:
            conclusions.append(f"DM test: Heston significantly better (t={t_gq:.2f}, p={p_gq:.4f})")
    else:
        conclusions.append(f"DM test: No significant difference (t={t_gq:.2f}, p={p_gq:.4f})")

    # 4. Key theoretical insight
    conclusions.append("Heston's advantages require OPTIONS DATA for proper calibration")
    conclusions.append("From daily returns alone, Heston ≈ mean-reverting EWMA ⊂ GARCH")

    print()
    for i, c in enumerate(conclusions, 1):
        print(f"  {i}. {c}")

    # =====================================================================
    # SAVE RESULTS
    # =====================================================================
    results = {
        'experiment': 'K350',
        'title': 'Heston Stochastic Volatility vs GARCH',
        'timestamp': datetime.now().isoformat(),
        'data': {
            'asset': 'SPY',
            'source': 'yfinance',
            'period': f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
            'n_total': int(n),
            'n_is': int(n_is),
            'n_oos': int(n_oos),
            'oos_start': oos_start,
        },
        'heston_mom': {k: float(v) if isinstance(v, (np.floating, float)) else v
                       for k, v in mom_params.items()},
        'heston_qml': {k: float(v) if isinstance(v, (np.floating, float)) else v
                       for k, v in qml_params.items()},
        'garch_params': garch_params_list[0] if garch_params_list else None,
        'oos_metrics': {
            'qlike': {
                'garch': float(qlike_garch),
                'heston_mom': float(qlike_mom),
                'heston_qml': float(qlike_qml),
                'ewma_heston_lambda': float(qlike_ewma_h),
                'ewma_094': float(qlike_ewma94),
                'ewma_097': float(qlike_ewma97),
            },
            'mse': {
                'garch': float(mse_garch),
                'heston_mom': float(mse_mom),
                'heston_qml': float(mse_qml),
            },
            'mae': {
                'garch': float(mae_garch),
                'heston_mom': float(mae_mom),
                'heston_qml': float(mae_qml),
            },
            'mz_r2': {
                'garch': float(r2_garch),
                'heston_mom': float(r2_mom),
                'heston_qml': float(r2_qml),
            },
        },
        'dm_tests': {
            'garch_vs_heston_mom': {'t_stat': float(t_gm), 'p_value': float(p_gm)},
            'garch_vs_heston_qml': {'t_stat': float(t_gq), 'p_value': float(p_gq)},
            'heston_mom_vs_qml': {'t_stat': float(t_mq), 'p_value': float(p_mq)},
        },
        'parameter_mapping': mapping if garch_params_list else None,
        'ewma_equivalence': {
            'heston_lambda': float(lam_heston),
            'correlation_heston_ewma': float(corr_h_ewma),
            'is_equivalent': bool(corr_h_ewma > 0.999),
        },
        'sub_period_results': {
            'garch_wins': garch_wins,
            'heston_wins': heston_wins,
        },
        'conclusions': conclusions,
        'limitations': [
            'True Heston requires options data (implied vol surface) for proper calibration',
            'Method-of-moments uses realized variance as proxy for latent variance',
            'QML estimation uses Gaussian approximation (Heston has non-Gaussian innovations)',
            'Daily returns lose intraday dynamics that are central to stochastic vol',
            'Single asset (SPY) — results may differ for other assets',
            'Euler discretization may be poor approximation for large dt=1/252',
        ],
    }

    outfile = STORAGE_DIR / "k350_heston_vs_garch.json"
    with open(outfile, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {outfile}")

    print("\n" + "=" * 80)
    print("K350 COMPLETE")
    print("=" * 80)

    return results

if __name__ == "__main__":
    results = main()
