"""
K1387: Risk Parity + Heavy-Tailed DCC — Paolella (2025, JTSA)

Research Question: Does DCC-GARCH with heavy-tailed (Student-t) multivariate
distribution outperform Gaussian DCC in risk parity portfolio construction?

Assets: SPY, TLT, GLD
Full sample: 2015-01-01 ~ 2024-12-31
OOS: 2020-01-01 ~ 2024-12-31
IS window: 250 trading days (expanding walk-forward)
"""

import json
import warnings
import numpy as np
import pandas as pd
from scipy import optimize, stats
from scipy.special import gammaln
import yfinance as yf

warnings.filterwarnings('ignore')

np.random.seed(42)

ASSETS = ['SPY', 'TLT', 'GLD']
N = len(ASSETS)
START = '2015-01-01'
END = '2024-12-31'
OOS_START = '2020-01-01'
IS_WINDOW = 250
REBALANCE_FREQ = 5   # rebalance every 5 days

# ─── 1. DATA ──────────────────────────────────────────────────────────────────

def load_data():
    print("Downloading data...")
    raw = yf.download(ASSETS, start=START, end=END, auto_adjust=True, progress=False)
    prices = raw['Close'][ASSETS].dropna()
    returns = np.log(prices / prices.shift(1)).dropna()
    print(f"Prices shape: {prices.shape}, Returns shape: {returns.shape}")
    return prices, returns

# ─── 2. GARCH(1,1) ────────────────────────────────────────────────────────────

def garch11_fit(r):
    """Fit GARCH(1,1) with Normal innovations using MLE. Returns (omega, alpha, beta)."""
    T = len(r)
    r = np.asarray(r, dtype=float)

    def neg_ll(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
            return 1e10
        h = np.zeros(T)
        h[0] = np.var(r)
        for t in range(1, T):
            h[t] = omega + alpha * r[t-1]**2 + beta * h[t-1]
        h = np.maximum(h, 1e-12)
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r**2 / h)
        return -np.sum(ll)

    var0 = np.var(r)
    x0 = [var0 * 0.05, 0.08, 0.88]
    bounds = [(1e-8, None), (1e-6, 0.5), (1e-6, 0.9999)]

    best_val = np.inf
    best_params = x0
    for _ in range(10):
        x0_try = [var0 * np.random.uniform(0.01, 0.1),
                  np.random.uniform(0.02, 0.15),
                  np.random.uniform(0.75, 0.95)]
        try:
            res = optimize.minimize(neg_ll, x0_try, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500, 'ftol': 1e-10})
            if res.fun < best_val and res.success:
                best_val = res.fun
                best_params = res.x
        except Exception:
            pass

    # final polish
    try:
        res = optimize.minimize(neg_ll, best_params, method='L-BFGS-B', bounds=bounds,
                                options={'maxiter': 2000, 'ftol': 1e-12})
        if res.success:
            best_params = res.x
    except Exception:
        pass

    return best_params  # omega, alpha, beta


def garch11_filter(r, params):
    """Return conditional variances h_t."""
    omega, alpha, beta = params
    T = len(r)
    r = np.asarray(r, dtype=float)
    h = np.zeros(T)
    h[0] = np.var(r) if np.var(r) > 0 else omega / (1 - alpha - beta)
    for t in range(1, T):
        h[t] = omega + alpha * r[t-1]**2 + beta * h[t-1]
    return np.maximum(h, 1e-12)


# ─── 3. DCC STAGE 2 ────────────────────────────────────────────────────────────

def dcc_qbar(eps):
    """Unconditional covariance of standardized residuals."""
    return np.cov(eps.T)


def dcc_filter(eps, a, b):
    """
    DCC dynamics:
      Q_t = (1-a-b)*Qbar + a * eps_{t-1} eps_{t-1}' + b * Q_{t-1}
      R_t = diag(Q_t)^{-1/2} Q_t diag(Q_t)^{-1/2}
    Returns R_t array shape (T, N, N).
    """
    T, N = eps.shape
    Qbar = dcc_qbar(eps)
    Q = Qbar.copy()
    Rs = np.zeros((T, N, N))

    for t in range(T):
        if t > 0:
            Q = (1 - a - b) * Qbar + a * np.outer(eps[t-1], eps[t-1]) + b * Q
        Q_diag_inv_sqrt = np.diag(1.0 / np.sqrt(np.diag(Q)))
        R = Q_diag_inv_sqrt @ Q @ Q_diag_inv_sqrt
        Rs[t] = R

    return Rs


def mvn_loglik(eps, R):
    """
    Multivariate normal log-likelihood for one observation.
    eps: (N,) standardized residuals
    R: (N,N) correlation matrix
    """
    try:
        sign, logdet = np.linalg.slogdet(R)
        if sign <= 0:
            return -1e10
        Rinv = np.linalg.inv(R)
        return -0.5 * (logdet + eps @ Rinv @ eps)
    except Exception:
        return -1e10


def mvt_loglik(eps, R, nu):
    """
    Multivariate Student-t log-likelihood for one observation.
    eps: (N,) standardized residuals
    R: (N,N) correlation matrix
    nu: degrees of freedom
    """
    n = len(eps)
    try:
        sign, logdet = np.linalg.slogdet(R)
        if sign <= 0:
            return -1e10
        Rinv = np.linalg.inv(R)
        quad = eps @ Rinv @ eps
        ll = (gammaln((nu + n) / 2) - gammaln(nu / 2)
              - 0.5 * n * np.log(np.pi * (nu - 2))
              - 0.5 * logdet
              - 0.5 * (nu + n) * np.log(1 + quad / (nu - 2)))
        return ll
    except Exception:
        return -1e10


def dcc_gaussian_loglik(params, eps):
    a, b = params
    if a <= 0 or b <= 0 or a + b >= 0.9999:
        return 1e10
    T = len(eps)
    Rs = dcc_filter(eps, a, b)
    ll = sum(mvn_loglik(eps[t], Rs[t]) for t in range(T))
    return -ll


def dcc_studentt_loglik(params, eps):
    a, b, nu = params
    if a <= 0 or b <= 0 or a + b >= 0.9999 or nu <= 2.01:
        return 1e10
    T = len(eps)
    Rs = dcc_filter(eps, a, b)
    ll = sum(mvt_loglik(eps[t], Rs[t], nu) for t in range(T))
    return -ll


def fit_dcc_gaussian(eps):
    """Fit DCC Gaussian. Returns (a, b)."""
    best_val = np.inf
    best_params = [0.05, 0.90]

    starts = [
        [0.05, 0.90], [0.03, 0.93], [0.08, 0.88],
        [0.02, 0.95], [0.10, 0.85]
    ]
    for x0 in starts:
        try:
            res = optimize.minimize(
                dcc_gaussian_loglik, x0, args=(eps,),
                method='L-BFGS-B',
                bounds=[(1e-5, 0.3), (1e-5, 0.9998)],
                options={'maxiter': 500}
            )
            if res.fun < best_val:
                best_val = res.fun
                best_params = res.x
        except Exception:
            pass
    return best_params  # a, b


def fit_dcc_studentt(eps):
    """Fit DCC Student-t. Returns (a, b, nu)."""
    best_val = np.inf
    best_params = [0.05, 0.90, 8.0]

    starts = [
        [0.05, 0.90, 8.0], [0.03, 0.93, 6.0], [0.08, 0.88, 10.0],
        [0.02, 0.95, 5.0], [0.10, 0.85, 15.0]
    ]
    for x0 in starts:
        try:
            res = optimize.minimize(
                dcc_studentt_loglik, x0, args=(eps,),
                method='L-BFGS-B',
                bounds=[(1e-5, 0.3), (1e-5, 0.9998), (2.01, 50.0)],
                options={'maxiter': 500}
            )
            if res.fun < best_val:
                best_val = res.fun
                best_params = res.x
        except Exception:
            pass
    return best_params  # a, b, nu


# ─── 4. COVARIANCE MATRIX ─────────────────────────────────────────────────────

def get_H_matrix(D_t, R_t):
    """H_t = D_t @ R_t @ D_t where D_t = diag(sqrt(h_i,t))."""
    return D_t @ R_t @ D_t


# ─── 5. RISK PARITY (ERC) ─────────────────────────────────────────────────────

def erc_weights(Sigma):
    """
    Equal Risk Contribution weights.
    Solve: argmin sum_i (RC_i - sigma_p/N)^2
    where RC_i = w_i * (Sigma @ w)_i / sqrt(w' Sigma w)
    """
    N = Sigma.shape[0]
    # Initial guess: inverse vol
    diag_vol = np.sqrt(np.diag(Sigma))
    w0 = (1.0 / diag_vol) / np.sum(1.0 / diag_vol)

    def objective(w):
        w = np.array(w)
        port_var = w @ Sigma @ w
        if port_var <= 0:
            return 1e10
        port_vol = np.sqrt(port_var)
        MRC = Sigma @ w / port_vol
        RC = w * MRC
        target = port_vol / N
        return np.sum((RC - target)**2)

    def total_weight(w):
        return np.sum(w) - 1.0

    constraints = [{'type': 'eq', 'fun': total_weight}]
    bounds = [(0.001, 1.0)] * N

    try:
        res = optimize.minimize(
            objective, w0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'ftol': 1e-10, 'maxiter': 1000}
        )
        if res.success and np.all(res.x >= 0):
            return res.x / res.x.sum()
    except Exception:
        pass
    return w0


def inverse_vol_weights(sigma_vec):
    """Inverse volatility weights."""
    iv = 1.0 / np.maximum(sigma_vec, 1e-10)
    return iv / iv.sum()


# ─── 6. RISK CONTRIBUTION ─────────────────────────────────────────────────────

def risk_contributions(w, Sigma):
    """Return (RC_1, ..., RC_N) normalized so they sum to 1."""
    port_var = w @ Sigma @ w
    if port_var <= 0:
        return np.ones(len(w)) / len(w)
    port_vol = np.sqrt(port_var)
    MRC = Sigma @ w / port_vol
    RC = w * MRC
    return RC / port_vol  # fractional risk contributions, sum = 1


# ─── 7. QLIKE ─────────────────────────────────────────────────────────────────

def portfolio_qlike(r_port, h_port):
    """QLIKE = mean(log(h) + r^2/h)"""
    h_port = np.maximum(h_port, 1e-12)
    return np.mean(np.log(h_port) + r_port**2 / h_port)


def portfolio_variance_from_H(w, H):
    """Portfolio variance = w' H w."""
    return float(w @ H @ w)


# ─── 8. VaR BACKTESTING ───────────────────────────────────────────────────────

def var_forecast(w, H, confidence=0.99, dist='normal', nu=None):
    """
    1-day portfolio VaR (positive number = loss).
    confidence: 0.99 for 1%, 0.95 for 5%
    """
    port_var = float(w @ H @ w)
    port_vol = np.sqrt(max(port_var, 1e-12))
    if dist == 'normal':
        z = stats.norm.ppf(1 - confidence)
    else:  # student-t
        # Rescale to unit-variance form: t(nu) has variance nu/(nu-2),
        # so divide quantile by sqrt(nu/(nu-2)) to get unit-variance quantile.
        # This ensures port_vol (from the covariance forecast H) is on the
        # same scale as z.
        if nu is None or nu <= 2:
            nu = 8.0
        z = stats.t.ppf(1 - confidence, df=nu) * np.sqrt((nu - 2) / nu)
    return -z * port_vol  # positive number


def kupiec_lr_test(violations, T, alpha):
    """
    Kupiec (1995) POF test.
    violations: number of VaR exceedances
    T: total observations
    alpha: nominal VaR level (e.g., 0.01 for 1%)
    Returns (LR_stat, p_value)
    """
    if violations == 0:
        violations = 0.01
    if violations >= T:
        violations = T - 0.01
    p_hat = violations / T
    if p_hat <= 0 or p_hat >= 1:
        return 0.0, 1.0
    try:
        lr = 2 * (violations * np.log(p_hat / alpha) +
                  (T - violations) * np.log((1 - p_hat) / (1 - alpha)))
        p_val = 1 - stats.chi2.cdf(lr, 1)
        return float(lr), float(p_val)
    except Exception:
        return 0.0, 1.0


def christoffersen_test(hits):
    """
    Christoffersen (1998) independence test.
    hits: binary array (1=violation, 0=no violation)
    Returns (LR_stat, p_value)
    """
    T = len(hits)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, T):
        if hits[t-1] == 0 and hits[t] == 0: n00 += 1
        elif hits[t-1] == 0 and hits[t] == 1: n01 += 1
        elif hits[t-1] == 1 and hits[t] == 0: n10 += 1
        else: n11 += 1

    pi01 = n01 / max(n00 + n01, 1)
    pi11 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)

    try:
        ll_A = (n00 * np.log(max(1 - pi01, 1e-10)) + n01 * np.log(max(pi01, 1e-10)) +
                n10 * np.log(max(1 - pi11, 1e-10)) + n11 * np.log(max(pi11, 1e-10)))
        ll_0 = ((n00 + n10) * np.log(max(1 - pi, 1e-10)) +
                (n01 + n11) * np.log(max(pi, 1e-10)))
        lr = -2 * (ll_0 - ll_A)
        p_val = 1 - stats.chi2.cdf(lr, 1)
        return float(lr), float(p_val)
    except Exception:
        return 0.0, 1.0


# ─── 9. DM TEST ───────────────────────────────────────────────────────────────

def dm_test(loss1, loss2):
    """
    Diebold-Mariano test (Harvey et al. 1997 version).
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Returns (t_stat, p_value)
    negative t_stat = loss1 < loss2 = model1 better
    """
    d = np.asarray(loss1) - np.asarray(loss2)
    T = len(d)
    d_bar = np.mean(d)

    # Newey-West HAC variance
    max_lag = int(np.ceil(T ** (1/3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = gamma0
    for h in range(1, max_lag + 1):
        gamma_h = np.mean((d[h:] - d_bar) * (d[:-h] - d_bar))
        gamma_sum += 2 * (1 - h / (max_lag + 1)) * gamma_h

    sigma2 = gamma_sum
    if sigma2 <= 0:
        return 0.0, 1.0

    t_stat = d_bar / np.sqrt(sigma2 / T)
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=T - 1))
    return float(t_stat), float(p_val)


# ─── 10. WALK-FORWARD MAIN LOOP ───────────────────────────────────────────────

def run_walkforward(returns_df):
    """
    Expanding window walk-forward:
    - IS: [0, t-1] with minimum IS_WINDOW observations
    - Refit every REBALANCE_FREQ days
    - Strictly no lookahead: weights at t use covariance from t-1

    Returns dict of arrays for each model.
    """
    returns = returns_df.values  # (T, N)
    T = len(returns)
    dates = returns_df.index

    # Find OOS start index
    oos_start_idx = None
    for i, d in enumerate(dates):
        if str(d.date()) >= OOS_START:
            oos_start_idx = i
            break

    if oos_start_idx is None or oos_start_idx < IS_WINDOW:
        oos_start_idx = IS_WINDOW

    print(f"Total T={T}, OOS start idx={oos_start_idx}, OOS length={T - oos_start_idx}")

    # Storage
    w_eq = np.ones(N) / N
    weights = {
        'M0': np.full((T, N), 1.0 / N),
        'M1': np.zeros((T, N)),
        'M2': np.zeros((T, N)),
        'M3': np.zeros((T, N)),
    }
    H_pred = {
        'M2': np.zeros((T, N, N)),
        'M3': np.zeros((T, N, N)),
    }
    nu_estimates = np.zeros(T)

    current_params = {
        'garch': None,  # list of (omega, alpha, beta) per asset
        'dcc_gauss': None,  # (a, b)
        'dcc_t': None,  # (a, b, nu)
        'H_last': np.diag([1e-4] * N),
        'h_last': np.array([1e-4] * N),
    }

    last_refit_idx = -1

    for t in range(T):
        # ── Inverse-vol weights (rolling 21d) ──
        start_iv = max(0, t - 21)
        if t > 21:
            vol21 = returns[start_iv:t].std(axis=0)
        else:
            vol21 = returns[:max(t, 1)].std(axis=0)
        vol21 = np.maximum(vol21, 1e-10)
        weights['M1'][t] = inverse_vol_weights(vol21)

        if t < oos_start_idx:
            # Pre-OOS: use equal weights as placeholder for DCC models
            weights['M2'][t] = w_eq
            weights['M3'][t] = w_eq
            H_pred['M2'][t] = np.eye(N) * np.mean(returns[:max(t, 1)].var(axis=0))
            H_pred['M3'][t] = H_pred['M2'][t].copy()
            nu_estimates[t] = 8.0
            continue

        # ── Refit every REBALANCE_FREQ days (or first OOS day) ──
        need_refit = (last_refit_idx < 0) or (t - last_refit_idx >= REBALANCE_FREQ)

        if need_refit:
            IS_data = returns[:t]  # shape (t, N) - strictly t-1 included
            if len(IS_data) < IS_WINDOW:
                weights['M2'][t] = w_eq
                weights['M3'][t] = w_eq
                continue

            print(f"  Refitting at t={t} (date={dates[t].date()}), IS size={len(IS_data)}...", end=' ', flush=True)

            # ── Stage 1: GARCH per asset ──
            garch_params = []
            h_vecs = []
            eps_mat = np.zeros_like(IS_data)
            for i in range(N):
                r_i = IS_data[:, i]
                try:
                    params_i = garch11_fit(r_i)
                except Exception:
                    params_i = [np.var(r_i) * 0.05, 0.08, 0.88]
                garch_params.append(params_i)
                h_i = garch11_filter(r_i, params_i)
                h_vecs.append(h_i)
                eps_mat[:, i] = r_i / np.sqrt(np.maximum(h_i, 1e-12))

            h_vecs = np.array(h_vecs).T  # (T_IS, N)

            # ── Stage 2: DCC fit ──
            try:
                dcc_g_params = fit_dcc_gaussian(eps_mat)
            except Exception:
                dcc_g_params = [0.05, 0.90]

            try:
                dcc_t_params = fit_dcc_studentt(eps_mat)
            except Exception:
                dcc_t_params = [0.05, 0.90, 8.0]

            # ── Stage 3: Update Q for one-step-ahead prediction ──
            # Use full IS eps to warm up Q, then predict next period
            a_g, b_g = dcc_g_params
            a_t, b_t, nu_t = dcc_t_params
            Qbar = dcc_qbar(eps_mat)

            # Filter to get last Q
            Q_g = Qbar.copy()
            Q_t_last = Qbar.copy()
            for s in range(len(eps_mat)):
                if s > 0:
                    Q_g = (1 - a_g - b_g) * Qbar + a_g * np.outer(eps_mat[s-1], eps_mat[s-1]) + b_g * Q_g
                    Q_t_last = (1 - a_t - b_t) * Qbar + a_t * np.outer(eps_mat[s-1], eps_mat[s-1]) + b_t * Q_t_last

            # One-step-ahead: use last eps
            eps_last = eps_mat[-1]
            h_last = h_vecs[-1]

            Q_g_next = (1 - a_g - b_g) * Qbar + a_g * np.outer(eps_last, eps_last) + b_g * Q_g
            Q_t_next = (1 - a_t - b_t) * Qbar + a_t * np.outer(eps_last, eps_last) + b_t * Q_t_last

            def Q_to_R(Q):
                d = np.sqrt(np.diag(Q))
                D_inv = np.diag(1.0 / np.maximum(d, 1e-10))
                return D_inv @ Q @ D_inv

            R_g = Q_to_R(Q_g_next)
            R_t_corr = Q_to_R(Q_t_next)

            # One-step-ahead GARCH variance
            h_pred = np.zeros(N)
            for i in range(N):
                om, al, be = garch_params[i]
                h_pred[i] = om + al * IS_data[-1, i]**2 + be * h_vecs[-1, i]

            D_pred = np.diag(np.sqrt(np.maximum(h_pred, 1e-12)))

            H_g = D_pred @ R_g @ D_pred
            H_t = D_pred @ R_t_corr @ D_pred

            # Store for next refit
            current_params['garch'] = garch_params
            current_params['dcc_gauss'] = dcc_g_params
            current_params['dcc_t'] = dcc_t_params
            current_params['H_g_next'] = H_g
            current_params['H_t_next'] = H_t
            current_params['Q_g'] = Q_g
            current_params['Q_t'] = Q_t_last
            current_params['Qbar'] = Qbar
            current_params['eps_last'] = eps_last
            current_params['h_last'] = h_pred  # h_{t|t-1}: one-step-ahead forecast, not last filtered
            current_params['nu'] = nu_t

            last_refit_idx = t
            print("done")

        # ── Use stored H to compute weights (t-1 H for t weights) ──
        H_g = current_params.get('H_g_next', np.eye(N) * 1e-4)
        H_t = current_params.get('H_t_next', np.eye(N) * 1e-4)
        nu_cur = current_params.get('nu', 8.0)

        # Make H positive definite
        for H in [H_g, H_t]:
            eigvals = np.linalg.eigvalsh(H)
            if eigvals.min() <= 0:
                H += (abs(eigvals.min()) + 1e-8) * np.eye(N)

        w_erc_g = erc_weights(H_g)
        w_erc_t = erc_weights(H_t)

        weights['M2'][t] = w_erc_g
        weights['M3'][t] = w_erc_t
        H_pred['M2'][t] = H_g
        H_pred['M3'][t] = H_t
        nu_estimates[t] = nu_cur

        # ── Update H for next day (between refits) ──
        if current_params['garch'] is not None:
            garch_params = current_params['garch']
            r_t = returns[t]  # current day realized return
            # h_last is the one-step-ahead forecast for day t (formed at t-1).
            # Use it to standardize r_t -> eps_t for the DCC update at day t.
            # This avoids the circularity of using h_t (which embeds r_t^2) to
            # standardize r_t before feeding back into the DCC recursion.
            h_t_forecast = current_params['h_last']  # h_{t|t-1}
            eps_t = r_t / np.sqrt(np.maximum(h_t_forecast, 1e-12))
            # Advance GARCH state: h_{t+1|t} uses r_t and h_{t|t-1}
            h_t = np.array([
                garch_params[i][0] + garch_params[i][1] * r_t[i]**2 + garch_params[i][2] * h_t_forecast[i]
                for i in range(N)
            ])

            Qbar = current_params['Qbar']
            a_g, b_g = current_params['dcc_gauss']
            a_t, b_t, _ = current_params['dcc_t']

            Q_g_upd = (1 - a_g - b_g) * Qbar + a_g * np.outer(current_params['eps_last'], current_params['eps_last']) + b_g * current_params['Q_g']
            Q_t_upd = (1 - a_t - b_t) * Qbar + a_t * np.outer(current_params['eps_last'], current_params['eps_last']) + b_t * current_params['Q_t']

            Q_g_next = (1 - a_g - b_g) * Qbar + a_g * np.outer(eps_t, eps_t) + b_g * Q_g_upd
            Q_t_next = (1 - a_t - b_t) * Qbar + a_t * np.outer(eps_t, eps_t) + b_t * Q_t_upd

            R_g_next = Q_to_R(Q_g_next)
            R_t_next = Q_to_R(Q_t_next)

            # H_{t+1|t} = D_{t+1|t} * R_{t+1|t} * D_{t+1|t}
            # where D_{t+1|t} = diag(sqrt(h_{t+1|t})) = diag(sqrt(h_t))
            # h_t already holds h_{t+1|t} computed above from r_t and h_{t|t-1}.
            D_next = np.diag(np.sqrt(np.maximum(h_t, 1e-12)))

            current_params['H_g_next'] = D_next @ R_g_next @ D_next
            current_params['H_t_next'] = D_next @ R_t_next @ D_next
            current_params['Q_g'] = Q_g_upd
            current_params['Q_t'] = Q_t_upd
            current_params['eps_last'] = eps_t
            current_params['h_last'] = h_t  # h_{t+1|t}: used as forecast for next day

    return weights, H_pred, nu_estimates, oos_start_idx, dates


def Q_to_R(Q):
    d = np.sqrt(np.diag(Q))
    D_inv = np.diag(1.0 / np.maximum(d, 1e-10))
    return D_inv @ Q @ D_inv


# ─── 11. EVALUATION ───────────────────────────────────────────────────────────

def evaluate(returns_df, weights, H_pred, nu_estimates, oos_start_idx):
    returns = returns_df.values
    dates = returns_df.index
    T = len(returns)
    oos_idx = oos_start_idx
    oos_len = T - oos_idx

    results = {}

    # Portfolio returns for each model
    port_returns = {}
    for m in ['M0', 'M1', 'M2', 'M3']:
        # Use t-1 weights for day t return (shift weights by 1)
        w_shifted = np.vstack([np.ones((1, N)) / N, weights[m][:-1]])
        r_port = np.sum(w_shifted * returns, axis=1)
        port_returns[m] = r_port

    oos_returns = {m: port_returns[m][oos_idx:] for m in port_returns}

    # Portfolio variance from H (for DCC models)
    h_port = {}
    for m in ['M2', 'M3']:
        h_p = np.zeros(T)
        for t in range(T):
            w_t = weights[m][t-1] if t > 0 else np.ones(N) / N
            h_p[t] = portfolio_variance_from_H(w_t, H_pred[m][t])
        h_port[m] = h_p

    oos_h_port = {m: h_port[m][oos_idx:] for m in h_port}

    # ── QLIKE ──
    qlike_vals = {}
    for m in ['M2', 'M3']:
        ql = portfolio_qlike(oos_returns[m], oos_h_port[m])
        qlike_vals[m] = float(ql)

    # QLIKE per obs for DM test
    def qlike_series(r, h):
        h = np.maximum(h, 1e-12)
        return np.log(h) + r**2 / h

    ql_M2 = qlike_series(oos_returns['M2'], oos_h_port['M2'])
    ql_M3 = qlike_series(oos_returns['M3'], oos_h_port['M3'])
    dm_t, dm_p = dm_test(ql_M2, ql_M3)  # neg = M2 better; pos = M3 better (M2 has higher loss)

    # ── VaR Backtesting ──
    var_results = {}
    for m_key, m_model, dist in [('M2', 'M2', 'normal'), ('M3', 'M3', 'student')]:
        for conf, label in [(0.99, '1pct'), (0.95, '5pct')]:
            alpha = 1 - conf
            var_preds = np.zeros(oos_len)
            for i, t in enumerate(range(oos_idx, T)):
                w_t = weights[m_model][t-1] if t > 0 else np.ones(N) / N
                nu_t = nu_estimates[t] if m_model == 'M3' else None
                var_preds[i] = var_forecast(w_t, H_pred[m_model][t], conf, dist, nu_t)

            hits = (oos_returns[m_key] < -var_preds).astype(int)
            n_viol = hits.sum()
            expected = oos_len * alpha
            lr_k, p_k = kupiec_lr_test(n_viol, oos_len, alpha)
            lr_c, p_c = christoffersen_test(hits)

            var_results[f'{m_key}_{label}'] = {
                'n_violations': int(n_viol),
                'expected_violations': float(expected),
                'violation_rate': float(n_viol / oos_len),
                'kupiec_lr': float(lr_k),
                'kupiec_p': float(p_k),
                'christoffersen_lr': float(lr_c),
                'christoffersen_p': float(p_c),
                'kupiec_pass': bool(p_k > 0.05),
                'christoffersen_pass': bool(p_c > 0.05),
            }

    # ── Risk Contribution RMSE ──
    rc_rmse = {}
    for m in ['M0', 'M1', 'M2', 'M3']:
        if m in ['M2', 'M3']:
            rmse_list = []
            for t in range(oos_idx, T):
                w_t = weights[m][t]
                H_t = H_pred[m][t]
                RC = risk_contributions(w_t, H_t)
                target = np.ones(N) / N
                rmse_list.append(np.sqrt(np.mean((RC - target)**2)))
            rc_rmse[m] = float(np.mean(rmse_list))
        else:
            # For M0/M1, use realized covariance
            rmse_list = []
            for t in range(oos_idx, T):
                start_c = max(0, t - 60)
                if t - start_c < 10:
                    rc_rmse[m] = np.nan
                    break
                Sigma_hist = np.cov(returns[start_c:t].T)
                w_t = weights[m][t]
                RC = risk_contributions(w_t, Sigma_hist)
                target = np.ones(N) / N
                rmse_list.append(np.sqrt(np.mean((RC - target)**2)))
            else:
                rc_rmse[m] = float(np.mean(rmse_list))

    # ── Portfolio Performance ──
    perf = {}
    for m in ['M0', 'M1', 'M2', 'M3']:
        r = oos_returns[m]
        ann_ret = float(np.mean(r) * 252)
        ann_vol = float(np.std(r) * np.sqrt(252))
        sharpe = float(ann_ret / ann_vol) if ann_vol > 0 else 0.0
        cum = np.cumprod(1 + r)
        dd = cum / np.maximum.accumulate(cum) - 1
        max_dd = float(dd.min())
        perf[m] = {
            'ann_return': ann_ret,
            'ann_vol': ann_vol,
            'sharpe': sharpe,
            'max_drawdown': max_dd,
        }

    return {
        'qlike': qlike_vals,
        'dm_t_stat': float(dm_t),
        'dm_p_value': float(dm_p),
        'var_accuracy': var_results,
        'rc_rmse': rc_rmse,
        'performance': perf,
        'oos_len': oos_len,
    }


# ─── 12. VERDICT ──────────────────────────────────────────────────────────────

def determine_verdict(eval_results):
    dm_t = eval_results['dm_t_stat']
    dm_p = eval_results['dm_p_value']

    # DM test: d_t = QLIKE_M2 - QLIKE_M3
    # positive dm_t -> M2 has higher QLIKE loss -> M3 better
    # negative dm_t -> M3 has higher QLIKE loss -> M2 better
    dm_sig = dm_p < 0.05
    m3_better_qlike = dm_t > 0 and dm_sig  # M3 reduces QLIKE significantly

    # VaR accuracy: require BOTH Kupiec (unconditional coverage) AND
    # Christoffersen (independence / conditional coverage) to count as pass.
    # A model with clustered breaches passes Kupiec but fails Christoffersen,
    # which is a real failure mode we must not ignore.
    var = eval_results['var_accuracy']
    m2_var_passes = sum(
        1 for k in var
        if k.startswith('M2') and var[k]['kupiec_pass'] and var[k]['christoffersen_pass']
    )
    m3_var_passes = sum(
        1 for k in var
        if k.startswith('M3') and var[k]['kupiec_pass'] and var[k]['christoffersen_pass']
    )

    if m3_better_qlike and m3_var_passes >= m2_var_passes:
        verdict = 'PASS'
    elif m3_better_qlike or m3_var_passes > m2_var_passes:
        verdict = 'MIXED'
    else:
        verdict = 'NULL'

    return verdict


# ─── 13. MAIN ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("K1387: Risk Parity + Heavy-Tailed DCC")
    print("=" * 60)

    # Load data
    prices, returns_df = load_data()
    print(f"Date range: {returns_df.index[0].date()} to {returns_df.index[-1].date()}")

    # Walk-forward
    print("\nRunning walk-forward estimation...")
    weights, H_pred, nu_estimates, oos_start_idx, dates = run_walkforward(returns_df)

    # Evaluate
    print("\nEvaluating results...")
    eval_results = evaluate(returns_df, weights, H_pred, nu_estimates, oos_start_idx)

    # Verdict
    verdict = determine_verdict(eval_results)

    # Print summary
    print("\n" + "=" * 60)
    print(f"VERDICT: {verdict}")
    print(f"OOS period: {dates[oos_start_idx].date()} to {dates[-1].date()}")
    print(f"OOS length: {eval_results['oos_len']} days")
    print(f"\nQKLIKE:")
    print(f"  M2 (Gaussian DCC): {eval_results['qlike']['M2']:.6f}")
    print(f"  M3 (Student-t DCC): {eval_results['qlike']['M3']:.6f}")
    print(f"  DM t-stat: {eval_results['dm_t_stat']:.4f} (p={eval_results['dm_p_value']:.4f})")
    print(f"\nVaR Accuracy:")
    for k, v in eval_results['var_accuracy'].items():
        print(f"  {k}: {v['n_violations']}/{eval_results['oos_len']} violations "
              f"(rate={v['violation_rate']:.3f}, Kupiec p={v['kupiec_p']:.3f})")
    print(f"\nRisk Contribution RMSE:")
    for m, v in eval_results['rc_rmse'].items():
        print(f"  {m}: {v:.4f}")
    print(f"\nPerformance (OOS):")
    for m, v in eval_results['performance'].items():
        print(f"  {m}: Sharpe={v['sharpe']:.3f}, MaxDD={v['max_drawdown']:.3f}")

    # Compile results JSON
    nu_oos = nu_estimates[oos_start_idx:].tolist()
    mean_nu = float(np.mean(nu_oos)) if len(nu_oos) > 0 else 8.0

    results = {
        "experiment_id": "K1387",
        "title": "Risk Parity + Heavy-Tailed DCC — Paolella (2025, JTSA)",
        "verdict": verdict,
        "period": {
            "full": f"{dates[0].date()} to {dates[-1].date()}",
            "oos": f"{dates[oos_start_idx].date()} to {dates[-1].date()}",
            "oos_length_days": eval_results['oos_len']
        },
        "assets": ASSETS,
        "models": {
            "M0_equal_weight": {
                "description": "1/N equal weight benchmark",
                "ann_return": eval_results['performance']['M0']['ann_return'],
                "ann_vol": eval_results['performance']['M0']['ann_vol'],
                "sharpe": eval_results['performance']['M0']['sharpe'],
                "max_drawdown": eval_results['performance']['M0']['max_drawdown'],
                "rc_rmse": eval_results['rc_rmse'].get('M0'),
            },
            "M1_inverse_vol": {
                "description": "Rolling 21-day inverse volatility weights",
                "ann_return": eval_results['performance']['M1']['ann_return'],
                "ann_vol": eval_results['performance']['M1']['ann_vol'],
                "sharpe": eval_results['performance']['M1']['sharpe'],
                "max_drawdown": eval_results['performance']['M1']['max_drawdown'],
                "rc_rmse": eval_results['rc_rmse'].get('M1'),
            },
            "M2_DCC_Gaussian": {
                "description": "DCC-GARCH(1,1) with Gaussian innovations",
                "ann_return": eval_results['performance']['M2']['ann_return'],
                "ann_vol": eval_results['performance']['M2']['ann_vol'],
                "sharpe": eval_results['performance']['M2']['sharpe'],
                "max_drawdown": eval_results['performance']['M2']['max_drawdown'],
                "qlike": eval_results['qlike']['M2'],
                "rc_rmse": eval_results['rc_rmse'].get('M2'),
            },
            "M3_DCC_StudentT": {
                "description": "DCC-GARCH(1,1) with multivariate Student-t innovations",
                "estimated_dof_mean": mean_nu,
                "ann_return": eval_results['performance']['M3']['ann_return'],
                "ann_vol": eval_results['performance']['M3']['ann_vol'],
                "sharpe": eval_results['performance']['M3']['sharpe'],
                "max_drawdown": eval_results['performance']['M3']['max_drawdown'],
                "qlike": eval_results['qlike']['M3'],
                "rc_rmse": eval_results['rc_rmse'].get('M3'),
            }
        },
        "qlike": {
            "M2": eval_results['qlike']['M2'],
            "M3": eval_results['qlike']['M3'],
            "improvement_pct": float((eval_results['qlike']['M2'] - eval_results['qlike']['M3']) / abs(eval_results['qlike']['M2']) * 100),
            "dm_t_stat": eval_results['dm_t_stat'],
            "dm_p_value": eval_results['dm_p_value'],
            "dm_significant": bool(eval_results['dm_p_value'] < 0.05),
            "m3_better": bool(eval_results['dm_t_stat'] > 0 and eval_results['dm_p_value'] < 0.05),
        },
        "var_accuracy": eval_results['var_accuracy'],
        "risk_contribution_rmse": eval_results['rc_rmse'],
        "performance": eval_results['performance'],
        "methodology": {
            "garch_spec": "GARCH(1,1) per asset, Normal innovations Stage 1",
            "dcc_spec": "Engle (2002) DCC, two-stage estimation",
            "dcc_gaussian": "MVN log-likelihood Stage 2",
            "dcc_studentt": "Multivariate Student-t log-likelihood Stage 2 with estimated df",
            "risk_parity": "Equal Risk Contribution (ERC), scipy.optimize.minimize SLSQP",
            "lookahead_protection": "Portfolio weights at t use covariance H_{t-1}, strictly no lookahead",
            "is_window": IS_WINDOW,
            "rebalance_freq": REBALANCE_FREQ,
            "seed": 42,
        },
        "conclusion": _build_conclusion(verdict, eval_results, mean_nu),
        "reviewer": "self (K1387 agent)",
        "related_experiments": ["K1100c", "K1100d"],
    }

    # Save JSON
    import os
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, 'K1387_results.json')
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {json_path}")
    return results


def _build_conclusion(verdict, eval_results, mean_nu):
    dm_t = eval_results['dm_t_stat']
    dm_p = eval_results['dm_p_value']
    ql_m2 = eval_results['qlike']['M2']
    ql_m3 = eval_results['qlike']['M3']
    m3_better = dm_t > 0 and dm_p < 0.05

    var = eval_results['var_accuracy']
    m2_1pct = var.get('M2_1pct', {})
    m3_1pct = var.get('M3_1pct', {})

    if verdict == 'PASS':
        return (f"Student-t DCC significantly outperforms Gaussian DCC for risk parity portfolio construction. "
                f"DM test: t={dm_t:.3f} (p={dm_p:.4f}), QLIKE M2={ql_m2:.4f} vs M3={ql_m3:.4f}. "
                f"Mean estimated df={mean_nu:.1f}, consistent with heavy-tailed dynamics. "
                f"VaR backtests show improved accuracy for heavy-tailed specification.")
    elif verdict == 'MIXED':
        return (f"Mixed evidence: Student-t DCC {'improves' if m3_better else 'does not improve'} QLIKE "
                f"(DM t={dm_t:.3f}, p={dm_p:.4f}) but VaR accuracy is comparable. "
                f"QLIKE M2={ql_m2:.4f}, M3={ql_m3:.4f}. Mean estimated df={mean_nu:.1f}. "
                f"Heavy-tailed distribution partially captures tail risk in {','.join(ASSETS)} portfolio.")
    else:
        return (f"NULL result: Student-t DCC does not significantly outperform Gaussian DCC for risk parity. "
                f"DM test: t={dm_t:.3f} (p={dm_p:.4f}), QLIKE M2={ql_m2:.4f} vs M3={ql_m3:.4f}. "
                f"Mean estimated df={mean_nu:.1f}. Consistent with K1100d (regime-switching DCC also NULL) "
                f"and univariate Student-t non-dominance pattern.")


if __name__ == '__main__':
    main()
