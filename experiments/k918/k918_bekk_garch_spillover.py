"""
K918: BEKK-GARCH Volatility Spillover — SPY <-> GLD Direct Transmission

Research Question:
  Can BEKK-GARCH quantify direct cross-asset volatility spillover between SPY and GLD?
  Does spillover intensity vary with VIX regime?

Context:
  - K907 (TCI network): SPY is vol transmitter (NET=+34.8), GLD is isolator (NET=-5.5)
  - K915 (DCC-GARCH): SPY-GLD dynamic correlation mean=0.069, std=0.199
  - BEKK models H_t with cross-asset vol transmission via A matrix off-diagonals

Method:
  - Full BEKK(1,1): H_t = C'C + A' * eps_{t-1} * eps'_{t-1} * A + B' * H_{t-1} * B
  - Diagonal BEKK(1,1): A, B are diagonal (no cross terms)
  - LR test: Full vs Diagonal
  - VIX regime subsample analysis
  - BEKK-based time-varying hedge ratio and minimum variance portfolio

Data: SPY + GLD daily returns, 2005-2026, yfinance
References:
  - Engle & Kroner (1995): Multivariate Simultaneous Generalized ARCH, Econometric Theory
  - Baba, Engle, Kraft & Kroner (1990): BEKK original

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
from datetime import datetime, timezone
from scipy.optimize import minimize
from scipy.stats import chi2
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K918: BEKK-GARCH Volatility Spillover — SPY <-> GLD")
print("=" * 60)

import yfinance as yf

tickers = ['SPY', 'GLD', '^VIX']
data = yf.download(tickers, start='2004-11-01', end='2026-04-05', auto_adjust=True)

# Extract adjusted close
prices = data['Close'][['SPY', 'GLD']].dropna()
vix = data['Close']['^VIX'].reindex(prices.index).ffill()

# Log returns in percentage
returns = np.log(prices / prices.shift(1)).dropna() * 100  # percentage for numerical stability
vix = vix.reindex(returns.index)

print(f"\nSample period: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")
print(f"N observations: {len(returns)}")
print(f"\nDescriptive Statistics (% returns):")
print(returns.describe())
print(f"\nCorrelation matrix:")
print(returns.corr())

# ============================================================
# 2. Numba-Accelerated BEKK Log-Likelihood
# ============================================================

@njit(cache=True)
def bekk_loglik_full(Y, CC, A, B, S):
    """
    BEKK(1,1) log-likelihood for 2 assets (Full A, B).
    H_t = CC + A' * eps_{t-1} * eps'_{t-1} * A + B' * H_{t-1} * B

    Returns negative log-likelihood (for minimization).
    """
    T = Y.shape[0]
    log_2pi = 1.8378770664093453  # np.log(2*pi)

    H = S.copy()
    neg_ll = 0.0

    At = A.T.copy()
    Bt = B.T.copy()

    for t in range(1, T):
        e0 = Y[t-1, 0]
        e1 = Y[t-1, 1]

        # eps * eps' (outer product)
        ee00 = e0 * e0
        ee01 = e0 * e1
        ee10 = e1 * e0
        ee11 = e1 * e1

        # A' * (eps * eps') * A
        # First: tmp = (eps * eps') * A
        tmp00 = ee00 * A[0, 0] + ee01 * A[1, 0]
        tmp01 = ee00 * A[0, 1] + ee01 * A[1, 1]
        tmp10 = ee10 * A[0, 0] + ee11 * A[1, 0]
        tmp11 = ee10 * A[0, 1] + ee11 * A[1, 1]
        # Then: A' * tmp
        aea00 = At[0, 0] * tmp00 + At[0, 1] * tmp10
        aea01 = At[0, 0] * tmp01 + At[0, 1] * tmp11
        aea10 = At[1, 0] * tmp00 + At[1, 1] * tmp10
        aea11 = At[1, 0] * tmp01 + At[1, 1] * tmp11

        # B' * H * B
        bh00 = Bt[0, 0] * H[0, 0] + Bt[0, 1] * H[1, 0]
        bh01 = Bt[0, 0] * H[0, 1] + Bt[0, 1] * H[1, 1]
        bh10 = Bt[1, 0] * H[0, 0] + Bt[1, 1] * H[1, 0]
        bh11 = Bt[1, 0] * H[0, 1] + Bt[1, 1] * H[1, 1]

        bhb00 = bh00 * B[0, 0] + bh01 * B[1, 0]
        bhb01 = bh00 * B[0, 1] + bh01 * B[1, 1]
        bhb10 = bh10 * B[0, 0] + bh11 * B[1, 0]
        bhb11 = bh10 * B[0, 1] + bh11 * B[1, 1]

        # H_new = CC + A'*ee*A + B'*H*B
        H_new00 = CC[0, 0] + aea00 + bhb00
        H_new01 = CC[0, 1] + aea01 + bhb01
        H_new10 = CC[1, 0] + aea10 + bhb10
        H_new11 = CC[1, 1] + aea11 + bhb11

        # Symmetrize
        H_new01 = 0.5 * (H_new01 + H_new10)
        H_new10 = H_new01

        # Check positive definiteness via determinant
        det_H = H_new00 * H_new11 - H_new01 * H_new10
        if det_H <= 1e-12 or H_new00 <= 0 or H_new11 <= 0:
            return 1e10

        # Inverse of 2x2
        inv00 = H_new11 / det_H
        inv01 = -H_new01 / det_H
        inv10 = -H_new10 / det_H
        inv11 = H_new00 / det_H

        # Quadratic form y' H^{-1} y
        y0 = Y[t, 0]
        y1 = Y[t, 1]
        quad = y0 * (inv00 * y0 + inv01 * y1) + y1 * (inv10 * y0 + inv11 * y1)

        neg_ll += 0.5 * (2 * log_2pi + np.log(det_H) + quad)

        H[0, 0] = H_new00
        H[0, 1] = H_new01
        H[1, 0] = H_new10
        H[1, 1] = H_new11

    return neg_ll


@njit(cache=True)
def bekk_loglik_diag(Y, CC, a1, a2, b1, b2, S):
    """
    Diagonal BEKK(1,1) log-likelihood for 2 assets.
    A = diag(a1, a2), B = diag(b1, b2)
    """
    T = Y.shape[0]
    log_2pi = 1.8378770664093453

    H00 = S[0, 0]
    H01 = S[0, 1]
    H11 = S[1, 1]

    neg_ll = 0.0

    for t in range(1, T):
        e0 = Y[t-1, 0]
        e1 = Y[t-1, 1]

        # Diagonal BEKK simplification:
        # H_new[0,0] = CC[0,0] + a1^2 * e0^2 + b1^2 * H[0,0]
        # H_new[1,1] = CC[1,1] + a2^2 * e1^2 + b2^2 * H[1,1]
        # H_new[0,1] = CC[0,1] + a1*a2 * e0*e1 + b1*b2 * H[0,1]
        H_new00 = CC[0, 0] + a1 * a1 * e0 * e0 + b1 * b1 * H00
        H_new11 = CC[1, 1] + a2 * a2 * e1 * e1 + b2 * b2 * H11
        H_new01 = CC[0, 1] + a1 * a2 * e0 * e1 + b1 * b2 * H01

        det_H = H_new00 * H_new11 - H_new01 * H_new01
        if det_H <= 1e-12 or H_new00 <= 0 or H_new11 <= 0:
            return 1e10

        inv00 = H_new11 / det_H
        inv01 = -H_new01 / det_H
        inv11 = H_new00 / det_H

        y0 = Y[t, 0]
        y1 = Y[t, 1]
        quad = y0 * (inv00 * y0 + inv01 * y1) + y1 * (inv01 * y0 + inv11 * y1)

        neg_ll += 0.5 * (2 * log_2pi + np.log(det_H) + quad)

        H00 = H_new00
        H01 = H_new01
        H11 = H_new11

    return neg_ll


@njit(cache=True)
def bekk_h_series_full(Y, CC, A, B, S):
    """Compute full H_t series for Full BEKK."""
    T = Y.shape[0]
    H_series = np.zeros((T, 2, 2))
    H_series[0] = S.copy()

    At = A.T.copy()
    Bt = B.T.copy()

    H = S.copy()

    for t in range(1, T):
        e0 = Y[t-1, 0]
        e1 = Y[t-1, 1]

        ee00 = e0 * e0
        ee01 = e0 * e1
        ee10 = e1 * e0
        ee11 = e1 * e1

        tmp00 = ee00 * A[0, 0] + ee01 * A[1, 0]
        tmp01 = ee00 * A[0, 1] + ee01 * A[1, 1]
        tmp10 = ee10 * A[0, 0] + ee11 * A[1, 0]
        tmp11 = ee10 * A[0, 1] + ee11 * A[1, 1]

        aea00 = At[0, 0] * tmp00 + At[0, 1] * tmp10
        aea01 = At[0, 0] * tmp01 + At[0, 1] * tmp11
        aea10 = At[1, 0] * tmp00 + At[1, 1] * tmp10
        aea11 = At[1, 0] * tmp01 + At[1, 1] * tmp11

        bh00 = Bt[0, 0] * H[0, 0] + Bt[0, 1] * H[1, 0]
        bh01 = Bt[0, 0] * H[0, 1] + Bt[0, 1] * H[1, 1]
        bh10 = Bt[1, 0] * H[0, 0] + Bt[1, 1] * H[1, 0]
        bh11 = Bt[1, 0] * H[0, 1] + Bt[1, 1] * H[1, 1]

        bhb00 = bh00 * B[0, 0] + bh01 * B[1, 0]
        bhb01 = bh00 * B[0, 1] + bh01 * B[1, 1]
        bhb10 = bh10 * B[0, 0] + bh11 * B[1, 0]
        bhb11 = bh10 * B[0, 1] + bh11 * B[1, 1]

        H[0, 0] = CC[0, 0] + aea00 + bhb00
        H[0, 1] = CC[0, 1] + 0.5 * (aea01 + aea10) + 0.5 * (bhb01 + bhb10)
        H[1, 0] = H[0, 1]
        H[1, 1] = CC[1, 1] + aea11 + bhb11

        H_series[t] = H.copy()

    return H_series


@njit(cache=True)
def bekk_h_series_diag(Y, CC, a1, a2, b1, b2, S):
    """Compute full H_t series for Diagonal BEKK."""
    T = Y.shape[0]
    H_series = np.zeros((T, 2, 2))
    H_series[0] = S.copy()

    H00 = S[0, 0]
    H01 = S[0, 1]
    H11 = S[1, 1]

    for t in range(1, T):
        e0 = Y[t-1, 0]
        e1 = Y[t-1, 1]

        H00_new = CC[0, 0] + a1 * a1 * e0 * e0 + b1 * b1 * H00
        H11_new = CC[1, 1] + a2 * a2 * e1 * e1 + b2 * b2 * H11
        H01_new = CC[0, 1] + a1 * a2 * e0 * e1 + b1 * b2 * H01

        H_series[t, 0, 0] = H00_new
        H_series[t, 0, 1] = H01_new
        H_series[t, 1, 0] = H01_new
        H_series[t, 1, 1] = H11_new

        H00 = H00_new
        H01 = H01_new
        H11 = H11_new

    return H_series


# ============================================================
# 3. Model Wrapper
# ============================================================

class BEKK_GARCH:
    def __init__(self, returns_array, diagonal=False):
        self.Y = returns_array.astype(np.float64)
        self.T, self.N = self.Y.shape
        assert self.N == 2
        self.diagonal = diagonal
        self.S = np.cov(self.Y.T)
        self.params_opt = None
        self.loglik = None
        self.H_series = None
        self.convergence = False

    def _unpack_params(self, params):
        if self.diagonal:
            c11, c21, c22, a1, a2, b1, b2 = params
            C = np.array([[c11, 0.0], [c21, c22]])
            A = np.diag([a1, a2])
            B = np.diag([b1, b2])
        else:
            c11, c21, c22 = params[0:3]
            a11, a12, a21, a22 = params[3:7]
            b11, b12, b21, b22 = params[7:11]
            C = np.array([[c11, 0.0], [c21, c22]])
            A = np.array([[a11, a12], [a21, a22]])
            B = np.array([[b11, b12], [b21, b22]])
        return C, A, B

    def _neg_loglik(self, params):
        C, A, B = self._unpack_params(params)
        CC = C.T @ C
        if self.diagonal:
            return bekk_loglik_diag(self.Y, CC, params[3], params[4], params[5], params[6], self.S)
        else:
            return bekk_loglik_full(self.Y, CC, A, B, self.S)

    def _get_start_params(self, seed_idx=0):
        L = np.linalg.cholesky(self.S)
        c_scale = 0.3

        if self.diagonal:
            starts = [
                [L[0, 0] * c_scale, L[1, 0] * c_scale, L[1, 1] * c_scale,
                 0.15, 0.15, 0.90, 0.90],
                [L[0, 0] * c_scale * 0.5, L[1, 0] * c_scale * 0.5, L[1, 1] * c_scale * 0.5,
                 0.20, 0.20, 0.85, 0.85],
                [L[0, 0] * c_scale * 1.5, L[1, 0] * c_scale * 1.5, L[1, 1] * c_scale * 1.5,
                 0.10, 0.10, 0.92, 0.92],
                [L[0, 0] * c_scale * 0.8, L[1, 0] * c_scale * 0.8, L[1, 1] * c_scale * 0.8,
                 0.25, 0.12, 0.80, 0.88],
            ]
        else:
            starts = [
                [L[0, 0] * c_scale, L[1, 0] * c_scale, L[1, 1] * c_scale,
                 0.15, 0.01, 0.01, 0.15, 0.90, 0.01, 0.01, 0.90],
                [L[0, 0] * c_scale * 0.5, L[1, 0] * c_scale * 0.5, L[1, 1] * c_scale * 0.5,
                 0.20, 0.02, 0.02, 0.20, 0.85, 0.02, 0.02, 0.85],
                [L[0, 0] * c_scale * 1.5, L[1, 0] * c_scale * 1.5, L[1, 1] * c_scale * 1.5,
                 0.10, -0.01, 0.01, 0.10, 0.92, -0.01, 0.01, 0.92],
                [L[0, 0] * c_scale, L[1, 0] * c_scale, L[1, 1] * c_scale,
                 0.25, 0.05, -0.02, 0.12, 0.88, 0.03, -0.01, 0.88],
                [L[0, 0] * c_scale * 0.7, L[1, 0] * c_scale * 0.7, L[1, 1] * c_scale * 0.7,
                 0.18, 0.00, 0.00, 0.18, 0.88, 0.00, 0.00, 0.88],
            ]

        if seed_idx < len(starts):
            return np.array(starts[seed_idx])
        else:
            rng = np.random.RandomState(42 + seed_idx)
            base = np.array(starts[0])
            return base * (1 + 0.1 * rng.randn(len(base)))

    def fit(self, n_starts=8, maxiter=5000):
        best_nll = np.inf
        best_params = None
        n_params = 7 if self.diagonal else 11
        model_type = "Diagonal" if self.diagonal else "Full"

        if self.diagonal:
            bounds = [
                (None, None), (None, None), (1e-6, None),
                (1e-6, 0.999), (1e-6, 0.999),
                (1e-6, 0.999), (1e-6, 0.999),
            ]
        else:
            bounds = [
                (None, None), (None, None), (1e-6, None),
                (-0.999, 0.999), (-0.5, 0.5), (-0.5, 0.5), (-0.999, 0.999),
                (-0.999, 0.999), (-0.5, 0.5), (-0.5, 0.5), (-0.999, 0.999),
            ]

        print(f"\n  Fitting {model_type} BEKK(1,1) with {n_params} parameters...")

        # Warm up numba JIT
        dummy_Y = self.Y[:10].copy()
        dummy_S = np.cov(dummy_Y.T)
        if self.diagonal:
            bekk_loglik_diag(dummy_Y, dummy_S, 0.15, 0.15, 0.9, 0.9, dummy_S)
        else:
            dummy_A = np.eye(2) * 0.15
            dummy_B = np.eye(2) * 0.9
            bekk_loglik_full(dummy_Y, dummy_S, dummy_A, dummy_B, dummy_S)
        print("  JIT compiled. Starting optimization...")

        for i in range(n_starts):
            x0 = self._get_start_params(i)
            try:
                res = minimize(
                    self._neg_loglik, x0, method='L-BFGS-B',
                    bounds=bounds,
                    options={'maxiter': maxiter, 'ftol': 1e-10, 'disp': False}
                )
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_params = res.x.copy()
                    best_convergence = res.success
                    print(f"    Start {i+1}/{n_starts}: LL={-best_nll:.2f} (best so far)")
                else:
                    print(f"    Start {i+1}/{n_starts}: LL={-res.fun:.2f}")
            except Exception as e:
                print(f"    Start {i+1}/{n_starts}: FAILED ({e})")
                continue

        if best_params is None:
            raise RuntimeError(f"All {n_starts} starting points failed for {model_type} BEKK")

        self.params_opt = best_params
        self.convergence = best_convergence

        # Compute H series
        C, A, B = self._unpack_params(best_params)
        CC = C.T @ C
        if self.diagonal:
            self.H_series = bekk_h_series_diag(self.Y, CC, best_params[3], best_params[4],
                                                best_params[5], best_params[6], self.S)
        else:
            self.H_series = bekk_h_series_full(self.Y, CC, A, B, self.S)

        self.loglik = -best_nll

        print(f"\n  Final Log-likelihood: {self.loglik:.2f}")
        print(f"  Convergence: {self.convergence}")
        print(f"\n  C matrix (intercept, lower triangular):")
        print(f"    {C}")
        print(f"  C'C =")
        print(f"    {CC}")
        print(f"\n  A matrix (ARCH):")
        print(f"    {A}")
        print(f"\n  B matrix (GARCH):")
        print(f"    {B}")

        # Persistence
        AkA = np.kron(A, A)
        BkB = np.kron(B, B)
        eig_vals = np.abs(np.linalg.eigvals(AkA + BkB))
        max_persistence = np.max(eig_vals)
        print(f"\n  Max persistence eigenvalue: {max_persistence:.6f}")
        if max_persistence >= 1.0:
            print(f"  WARNING: persistence >= 1 (non-stationary)")

        return self

    def get_conditional_covariances(self, index=None):
        if self.H_series is None:
            raise RuntimeError("Model not fitted yet")
        h11 = self.H_series[:, 0, 0]
        h22 = self.H_series[:, 1, 1]
        h12 = self.H_series[:, 0, 1]
        rho = h12 / np.sqrt(h11 * h22)

        if index is not None:
            return pd.DataFrame({
                'h_SPY': h11, 'h_GLD': h22, 'h_SPYGLD': h12, 'rho': rho
            }, index=index)
        return h11, h22, h12, rho

    def get_params_dict(self):
        C, A, B = self._unpack_params(self.params_opt)
        AkA = np.kron(A, A)
        BkB = np.kron(B, B)
        eig_vals = np.abs(np.linalg.eigvals(AkA + BkB))

        result = {
            'C': C.tolist(),
            'CC': (C.T @ C).tolist(),
            'A': A.tolist(),
            'B': B.tolist(),
            'loglik': float(self.loglik),
            'n_params': 7 if self.diagonal else 11,
            'convergence': bool(self.convergence),
            'max_persistence': float(np.max(eig_vals)),
        }

        if not self.diagonal:
            result['a12_SPY_to_GLD'] = float(A[0, 1])
            result['a21_GLD_to_SPY'] = float(A[1, 0])
            result['b12_SPY_to_GLD'] = float(B[0, 1])
            result['b21_GLD_to_SPY'] = float(B[1, 0])

        return result


# ============================================================
# 3. Estimate Models
# ============================================================

ret_array = returns[['SPY', 'GLD']].values
ret_index = returns.index

print("\n" + "=" * 60)
print("Step 2: Estimating Diagonal BEKK(1,1)")
print("=" * 60)

diag_model = BEKK_GARCH(ret_array, diagonal=True)
diag_model.fit(n_starts=6, maxiter=5000)

print("\n" + "=" * 60)
print("Step 3: Estimating Full BEKK(1,1)")
print("=" * 60)

full_model = BEKK_GARCH(ret_array, diagonal=False)
full_model.fit(n_starts=8, maxiter=8000)

# ============================================================
# 4. Likelihood Ratio Test: Full vs Diagonal
# ============================================================

print("\n" + "=" * 60)
print("Step 4: Likelihood Ratio Test (Full vs Diagonal)")
print("=" * 60)

ll_full = full_model.loglik
ll_diag = diag_model.loglik
lr_stat = 2 * (ll_full - ll_diag)
df_diff = 11 - 7  # 4 additional parameters
p_value = 1 - chi2.cdf(lr_stat, df_diff)

print(f"  Full BEKK log-lik:     {ll_full:.2f}")
print(f"  Diagonal BEKK log-lik: {ll_diag:.2f}")
print(f"  LR statistic:          {lr_stat:.4f}")
print(f"  Degrees of freedom:    {df_diff}")
print(f"  p-value:               {p_value:.6f}")
print(f"  Conclusion: {'Full BEKK significantly better' if p_value < 0.05 else 'Diagonal BEKK sufficient'}")

# ============================================================
# 5. Spillover Analysis
# ============================================================

print("\n" + "=" * 60)
print("Step 5: Spillover Analysis")
print("=" * 60)

full_params = full_model.get_params_dict()
C_f, A_f, B_f = full_model._unpack_params(full_model.params_opt)

print(f"\n  Cross-spillover coefficients (A matrix):")
print(f"    a12 (SPY shock -> GLD vol): {A_f[0, 1]:.6f}")
print(f"    a21 (GLD shock -> SPY vol): {A_f[1, 0]:.6f}")
print(f"    |a12|/|a11|: {abs(A_f[0, 1])/abs(A_f[0, 0]):.4f} (relative to own ARCH)")
print(f"    |a21|/|a22|: {abs(A_f[1, 0])/abs(A_f[1, 1]):.4f} (relative to own ARCH)")

print(f"\n  Cross-persistence coefficients (B matrix):")
print(f"    b12 (SPY vol persistence -> GLD): {B_f[0, 1]:.6f}")
print(f"    b21 (GLD vol persistence -> SPY): {B_f[1, 0]:.6f}")

# Conditional covariance time series
cond_cov_full = full_model.get_conditional_covariances(ret_index)
cond_cov_diag = diag_model.get_conditional_covariances(ret_index)

print(f"\n  Conditional correlation (Full BEKK):")
print(f"    Mean:  {cond_cov_full['rho'].mean():.4f}")
print(f"    Std:   {cond_cov_full['rho'].std():.4f}")
print(f"    Min:   {cond_cov_full['rho'].min():.4f}")
print(f"    Max:   {cond_cov_full['rho'].max():.4f}")

print(f"\n  Conditional correlation (Diagonal BEKK):")
print(f"    Mean:  {cond_cov_diag['rho'].mean():.4f}")
print(f"    Std:   {cond_cov_diag['rho'].std():.4f}")
print(f"    Min:   {cond_cov_diag['rho'].min():.4f}")
print(f"    Max:   {cond_cov_diag['rho'].max():.4f}")

print(f"\n  K915 DCC SPY-GLD correlation: mean=0.069, std=0.199")

# ============================================================
# 6. VIX Regime Analysis
# ============================================================

print("\n" + "=" * 60)
print("Step 6: VIX Regime Analysis")
print("=" * 60)

regimes = {
    'Low (VIX<15)': vix < 15,
    'Medium (15-25)': (vix >= 15) & (vix < 25),
    'High (25-35)': (vix >= 25) & (vix < 35),
    'Extreme (VIX>35)': vix >= 35,
}

regime_stats = {}
for name, mask in regimes.items():
    mask_aligned = mask.reindex(cond_cov_full.index).fillna(False)
    sub = cond_cov_full[mask_aligned]
    if len(sub) > 0:
        regime_stats[name] = {
            'count': int(len(sub)),
            'rho_mean': float(sub['rho'].mean()),
            'rho_std': float(sub['rho'].std()),
            'h_SPY_mean': float(sub['h_SPY'].mean()),
            'h_GLD_mean': float(sub['h_GLD'].mean()),
            'h_cross_mean': float(sub['h_SPYGLD'].mean()),
        }
        print(f"\n  {name} (n={len(sub)}):")
        print(f"    rho: mean={sub['rho'].mean():.4f}, std={sub['rho'].std():.4f}")
        print(f"    h_SPY: mean={sub['h_SPY'].mean():.4f}")
        print(f"    h_GLD: mean={sub['h_GLD'].mean():.4f}")
        print(f"    h_cross: mean={sub['h_SPYGLD'].mean():.4f}")

# ============================================================
# 7. Spillover Asymmetry
# ============================================================

print("\n" + "=" * 60)
print("Step 7: Spillover Asymmetry Analysis")
print("=" * 60)

spy_pos = returns['SPY'] > 0
spy_neg = returns['SPY'] <= 0

rho_spy_up = cond_cov_full.loc[spy_pos, 'rho'].mean()
rho_spy_down = cond_cov_full.loc[spy_neg, 'rho'].mean()

gld_pos = returns['GLD'] > 0
gld_neg = returns['GLD'] <= 0
rho_gld_up = cond_cov_full.loc[gld_pos, 'rho'].mean()
rho_gld_down = cond_cov_full.loc[gld_neg, 'rho'].mean()

print(f"  Conditional correlation by market direction:")
print(f"    SPY up days:   rho = {rho_spy_up:.4f}")
print(f"    SPY down days: rho = {rho_spy_down:.4f}")
print(f"    GLD up days:   rho = {rho_gld_up:.4f}")
print(f"    GLD down days: rho = {rho_gld_down:.4f}")

# Next-day vol change after large shocks
spy_large_neg = returns['SPY'] < returns['SPY'].quantile(0.05)
spy_large_pos = returns['SPY'] > returns['SPY'].quantile(0.95)

gld_vol_after_spy_neg = cond_cov_full.loc[spy_large_neg, 'h_GLD'].shift(-1).mean()
gld_vol_after_spy_pos = cond_cov_full.loc[spy_large_pos, 'h_GLD'].shift(-1).mean()
gld_vol_normal = cond_cov_full['h_GLD'].mean()

print(f"\n  Next-day GLD conditional variance:")
print(f"    After SPY 5th percentile crash: {gld_vol_after_spy_neg:.4f}")
print(f"    After SPY 95th percentile surge: {gld_vol_after_spy_pos:.4f}")
print(f"    Unconditional mean:              {gld_vol_normal:.4f}")

gld_large_neg = returns['GLD'] < returns['GLD'].quantile(0.05)
gld_large_pos = returns['GLD'] > returns['GLD'].quantile(0.95)

spy_vol_after_gld_neg = cond_cov_full.loc[gld_large_neg, 'h_SPY'].shift(-1).mean()
spy_vol_after_gld_pos = cond_cov_full.loc[gld_large_pos, 'h_SPY'].shift(-1).mean()
spy_vol_normal = cond_cov_full['h_SPY'].mean()

print(f"\n  Next-day SPY conditional variance:")
print(f"    After GLD 5th percentile drop:  {spy_vol_after_gld_neg:.4f}")
print(f"    After GLD 95th percentile surge: {spy_vol_after_gld_pos:.4f}")
print(f"    Unconditional mean:              {spy_vol_normal:.4f}")

# ============================================================
# 8. Time-Varying Hedge Ratio
# ============================================================

print("\n" + "=" * 60)
print("Step 8: Time-Varying Hedge Ratio")
print("=" * 60)

# Optimal hedge ratio: beta_t = h_12,t / h_22,t
hedge_ratio = cond_cov_full['h_SPYGLD'] / cond_cov_full['h_GLD']

print(f"  BEKK hedge ratio (SPY hedged by GLD):")
print(f"    Mean:  {hedge_ratio.mean():.4f}")
print(f"    Std:   {hedge_ratio.std():.4f}")
print(f"    Min:   {hedge_ratio.min():.4f}")
print(f"    Max:   {hedge_ratio.max():.4f}")
print(f"    Median: {hedge_ratio.median():.4f}")

for name, mask in regimes.items():
    mask_aligned = mask.reindex(hedge_ratio.index).fillna(False)
    sub = hedge_ratio[mask_aligned]
    if len(sub) > 0:
        print(f"    {name}: mean={sub.mean():.4f}, std={sub.std():.4f}")

# ============================================================
# 9. Portfolio Application
# ============================================================

print("\n" + "=" * 60)
print("Step 9: Portfolio Application")
print("=" * 60)

ret_decimal = returns / 100.0

# Strategy 1: Static 50/50
w_static = np.array([0.5, 0.5])
port_static = ret_decimal.values @ w_static

# Strategy 2: BEKK Minimum Variance Portfolio
H_series = full_model.H_series
T = len(ret_decimal)
w_bekk = np.zeros((T, 2))
ones = np.ones(2)

for t in range(T):
    H_t = H_series[t]
    try:
        H_inv = np.linalg.inv(H_t)
        w = H_inv @ ones / (ones @ H_inv @ ones)
        w = np.clip(w, 0, 1)
        w = w / w.sum()
        w_bekk[t] = w
    except Exception:
        w_bekk[t] = w_static

# IMPORTANT: lag weights by 1 day (signal from t-1, return at t)
port_bekk = np.zeros(T)
for t in range(1, T):
    port_bekk[t] = ret_decimal.values[t] @ w_bekk[t-1]  # lag=1
port_bekk[0] = ret_decimal.values[0] @ w_static

# Strategy 3: HR-based
hr_clipped = hedge_ratio.clip(0.1, 0.9).values
w_hr = np.column_stack([1 - hr_clipped, hr_clipped])
port_hr = np.zeros(T)
for t in range(1, T):
    port_hr[t] = ret_decimal.values[t] @ w_hr[t-1]  # lag=1
port_hr[0] = ret_decimal.values[0] @ w_static

# Metrics
def calc_metrics(returns_series, name):
    ann_ret = returns_series.mean() * 252
    ann_vol = returns_series.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + returns_series).cumprod()
    rolling_max = np.maximum.accumulate(cum)
    drawdown = (cum - rolling_max) / rolling_max
    mdd = drawdown.min()
    return {
        'name': name,
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
    }

metrics = {}
metrics['50/50 Static'] = calc_metrics(pd.Series(port_static, index=ret_index), '50/50 Static')
metrics['BEKK MinVar'] = calc_metrics(pd.Series(port_bekk, index=ret_index), 'BEKK MinVar')
metrics['BEKK HR-Based'] = calc_metrics(pd.Series(port_hr, index=ret_index), 'BEKK HR-Based')

turnover_bekk = np.abs(np.diff(w_bekk[:, 0])).mean() * 252
turnover_hr = np.abs(np.diff(w_hr[:, 0])).mean() * 252

metrics['BEKK MinVar']['ann_turnover'] = float(turnover_bekk)
metrics['BEKK HR-Based']['ann_turnover'] = float(turnover_hr)
metrics['50/50 Static']['ann_turnover'] = 0.0

print(f"\n  Portfolio Comparison:")
print(f"  {'Strategy':<20} {'Return':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Turnover':>10}")
print(f"  {'-'*60}")
for k, v in metrics.items():
    print(f"  {v['name']:<20} {v['ann_return']:>7.4f} {v['ann_vol']:>7.4f} {v['sharpe']:>7.4f} {v['mdd']:>7.4f} {v.get('ann_turnover', 0):>9.1f}")

print(f"\n  Average BEKK MinVar weights: SPY={w_bekk[1:, 0].mean():.3f}, GLD={w_bekk[1:, 1].mean():.3f}")
print(f"  Average HR-Based weights:   SPY={w_hr[1:, 0].mean():.3f}, GLD={w_hr[1:, 1].mean():.3f}")

# ============================================================
# 10. Comparison with K915 DCC
# ============================================================

print("\n" + "=" * 60)
print("Step 10: Comparison with K915 DCC")
print("=" * 60)

bekk_rho_mean = cond_cov_full['rho'].mean()
bekk_rho_std = cond_cov_full['rho'].std()

print(f"  Dynamic Correlation Comparison:")
print(f"    DCC (K915):  mean=0.069, std=0.199")
print(f"    Full BEKK:   mean={bekk_rho_mean:.4f}, std={bekk_rho_std:.4f}")
print(f"    Diag BEKK:   mean={cond_cov_diag['rho'].mean():.4f}, std={cond_cov_diag['rho'].std():.4f}")

n_obs = len(returns)
aic_full = -2 * full_model.loglik + 2 * 11
aic_diag = -2 * diag_model.loglik + 2 * 7
bic_full = -2 * full_model.loglik + np.log(n_obs) * 11
bic_diag = -2 * diag_model.loglik + np.log(n_obs) * 7

print(f"\n  Information Criteria:")
print(f"    Full BEKK:  AIC={aic_full:.2f}, BIC={bic_full:.2f}")
print(f"    Diag BEKK:  AIC={aic_diag:.2f}, BIC={bic_diag:.2f}")
print(f"    {'Full' if aic_full < aic_diag else 'Diagonal'} BEKK preferred by AIC")
print(f"    {'Full' if bic_full < bic_diag else 'Diagonal'} BEKK preferred by BIC")

# ============================================================
# 11. Plots
# ============================================================

print("\n" + "=" * 60)
print("Step 11: Generating Plots")
print("=" * 60)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Plot 1: Spillover dynamics
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

axes[0].plot(ret_index, cond_cov_full['rho'], color='navy', linewidth=0.5, alpha=0.8)
axes[0].axhline(y=0, color='red', linestyle='--', linewidth=0.8)
axes[0].axhline(y=cond_cov_full['rho'].mean(), color='green', linestyle='--',
                linewidth=0.8, label=f'Mean={cond_cov_full["rho"].mean():.3f}')
axes[0].set_ylabel('Correlation')
axes[0].set_title('Panel A: BEKK Conditional Correlation (SPY-GLD)')
axes[0].legend(loc='upper right')
axes[0].set_ylim(-1, 1)

vol_spy = np.sqrt(cond_cov_full['h_SPY']) * np.sqrt(252)
vol_gld = np.sqrt(cond_cov_full['h_GLD']) * np.sqrt(252)
axes[1].plot(ret_index, vol_spy, color='blue', linewidth=0.5, alpha=0.8, label='SPY')
axes[1].plot(ret_index, vol_gld, color='gold', linewidth=0.5, alpha=0.8, label='GLD')
axes[1].set_ylabel('Ann. Vol (%)')
axes[1].set_title('Panel B: BEKK Conditional Volatilities')
axes[1].legend(loc='upper right')

axes[2].plot(ret_index, cond_cov_full['h_SPYGLD'], color='purple', linewidth=0.5, alpha=0.8)
axes[2].axhline(y=0, color='red', linestyle='--', linewidth=0.8)
axes[2].set_ylabel('Cov (SPY, GLD)')
axes[2].set_title('Panel C: BEKK Conditional Covariance')
axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
axes[2].xaxis.set_major_locator(mdates.YearLocator(2))

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k918_spillover_dynamics.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k918_spillover_dynamics.png")

# Plot 2: Hedge ratio
fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)

axes[0].plot(ret_index, hedge_ratio, color='darkblue', linewidth=0.5, alpha=0.8)
axes[0].axhline(y=hedge_ratio.mean(), color='red', linestyle='--', linewidth=0.8,
                label=f'Mean={hedge_ratio.mean():.3f}')
axes[0].axhline(y=0.5, color='green', linestyle='--', linewidth=0.8, label='Static 50/50')
axes[0].set_ylabel('Hedge Ratio (h12/h22)')
axes[0].set_title('Panel A: BEKK Time-Varying Hedge Ratio (SPY hedged by GLD)')
axes[0].legend(loc='upper right')

axes[1].fill_between(ret_index, 0, w_bekk[:, 0], alpha=0.6, color='blue', label='SPY weight')
axes[1].fill_between(ret_index, w_bekk[:, 0], 1, alpha=0.6, color='gold', label='GLD weight')
axes[1].axhline(y=0.5, color='red', linestyle='--', linewidth=0.8)
axes[1].set_ylabel('Weight')
axes[1].set_title('Panel B: BEKK Minimum Variance Portfolio Weights')
axes[1].legend(loc='upper right')
axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
axes[1].xaxis.set_major_locator(mdates.YearLocator(2))

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k918_hedge_ratio.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k918_hedge_ratio.png")

# Plot 3: Regime comparison
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

regime_names = list(regime_stats.keys())
rho_means = [regime_stats[r]['rho_mean'] for r in regime_names]
rho_stds = [regime_stats[r]['rho_std'] for r in regime_names]
colors = ['green', 'blue', 'orange', 'red']

bars = axes[0].bar(range(len(regime_names)), rho_means, yerr=rho_stds,
                   color=colors, alpha=0.7, capsize=5)
axes[0].set_xticks(range(len(regime_names)))
axes[0].set_xticklabels([r.split('(')[0].strip() for r in regime_names], fontsize=9)
axes[0].set_ylabel('Conditional Correlation')
axes[0].set_title('SPY-GLD Correlation by VIX Regime')
axes[0].axhline(y=0, color='black', linewidth=0.5)
for i, (m, s) in enumerate(zip(rho_means, rho_stds)):
    axes[0].text(i, m + s + 0.02, f'{m:.3f}', ha='center', fontsize=9)

spy_vols = [regime_stats[r]['h_SPY_mean'] for r in regime_names]
gld_vols = [regime_stats[r]['h_GLD_mean'] for r in regime_names]
x = np.arange(len(regime_names))
w = 0.35
axes[1].bar(x - w/2, spy_vols, w, label='SPY h11', color='blue', alpha=0.7)
axes[1].bar(x + w/2, gld_vols, w, label='GLD h22', color='gold', alpha=0.7)
axes[1].set_xticks(x)
axes[1].set_xticklabels([r.split('(')[0].strip() for r in regime_names], fontsize=9)
axes[1].set_ylabel('Conditional Variance')
axes[1].set_title('Conditional Variance by VIX Regime')
axes[1].legend()

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k918_regime_analysis.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k918_regime_analysis.png")

# ============================================================
# 12. Key Findings
# ============================================================

print("\n" + "=" * 60)
print("KEY FINDINGS")
print("=" * 60)

a12 = A_f[0, 1]
a21 = A_f[1, 0]
a11 = A_f[0, 0]
a22 = A_f[1, 1]

findings = []

if lr_stat > chi2.ppf(0.95, df_diff):
    findings.append(f"Full BEKK significantly better than Diagonal (LR={lr_stat:.2f}, p={p_value:.4f}): cross-spillover exists")
else:
    findings.append(f"Diagonal BEKK sufficient (LR={lr_stat:.2f}, p={p_value:.4f}): no significant cross-spillover")

findings.append(f"SPY->GLD spillover (a12={a12:.4f}): {abs(a12)/abs(a11)*100:.1f}% of own ARCH effect")
findings.append(f"GLD->SPY spillover (a21={a21:.4f}): {abs(a21)/abs(a22)*100:.1f}% of own ARCH effect")
findings.append(f"BEKK correlation: mean={bekk_rho_mean:.4f} (vs DCC K915: 0.069)")

if metrics['BEKK MinVar']['sharpe'] > metrics['50/50 Static']['sharpe']:
    findings.append(f"BEKK MinVar outperforms 50/50: Sharpe {metrics['BEKK MinVar']['sharpe']:.3f} vs {metrics['50/50 Static']['sharpe']:.3f}")
else:
    findings.append(f"BEKK MinVar does NOT outperform 50/50: Sharpe {metrics['BEKK MinVar']['sharpe']:.3f} vs {metrics['50/50 Static']['sharpe']:.3f} (turnover={turnover_bekk:.0f}/yr)")

for f in findings:
    print(f"  - {f}")

# ============================================================
# 13. Save Results
# ============================================================

print("\n" + "=" * 60)
print("Step 13: Saving Results")
print("=" * 60)

key_findings = " | ".join(findings)

results = {
    "experiment_id": "K918",
    "title": "BEKK-GARCH Volatility Spillover -- SPY <-> GLD Direct Transmission",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance",
    "data_period": f"{ret_index[0].strftime('%Y-%m-%d')} to {ret_index[-1].strftime('%Y-%m-%d')}",
    "sample_size": int(len(returns)),
    "assets": ["SPY", "GLD"],
    "method": "BEKK(1,1) -- Full and Diagonal",
    "references": [
        "Engle & Kroner (1995): Multivariate Simultaneous Generalized ARCH, Econometric Theory",
        "Baba, Engle, Kraft & Kroner (1990): BEKK original formulation"
    ],
    "prior_experiments": {
        "K907": "TCI network: SPY transmitter (NET=+34.8), GLD isolator (NET=-5.5)",
        "K915": "DCC-GARCH: SPY-GLD dynamic corr mean=0.069, std=0.199, portfolio NULL"
    },
    "full_bekk_params": full_params,
    "diagonal_bekk_params": diag_model.get_params_dict(),
    "lr_test": {
        "statistic": float(lr_stat),
        "df": int(df_diff),
        "p_value": float(p_value),
        "conclusion": "Full BEKK significantly better" if p_value < 0.05 else "Diagonal BEKK sufficient"
    },
    "information_criteria": {
        "full_bekk_aic": float(aic_full),
        "full_bekk_bic": float(bic_full),
        "diagonal_bekk_aic": float(aic_diag),
        "diagonal_bekk_bic": float(bic_diag),
        "preferred_by_aic": "Full" if aic_full < aic_diag else "Diagonal",
        "preferred_by_bic": "Full" if bic_full < bic_diag else "Diagonal"
    },
    "spillover_analysis": {
        "a12_SPY_shock_to_GLD_vol": float(a12),
        "a21_GLD_shock_to_SPY_vol": float(a21),
        "a12_relative_to_own": float(abs(a12) / abs(a11)),
        "a21_relative_to_own": float(abs(a21) / abs(a22)),
        "b12_SPY_persistence_to_GLD": float(B_f[0, 1]),
        "b21_GLD_persistence_to_SPY": float(B_f[1, 0]),
    },
    "conditional_correlation": {
        "full_bekk": {
            "mean": float(bekk_rho_mean),
            "std": float(bekk_rho_std),
            "min": float(cond_cov_full['rho'].min()),
            "max": float(cond_cov_full['rho'].max()),
        },
        "diagonal_bekk": {
            "mean": float(cond_cov_diag['rho'].mean()),
            "std": float(cond_cov_diag['rho'].std()),
            "min": float(cond_cov_diag['rho'].min()),
            "max": float(cond_cov_diag['rho'].max()),
        },
        "dcc_k915_reference": {"mean": 0.069, "std": 0.199}
    },
    "regime_analysis": regime_stats,
    "spillover_asymmetry": {
        "rho_SPY_up": float(rho_spy_up),
        "rho_SPY_down": float(rho_spy_down),
        "rho_GLD_up": float(rho_gld_up),
        "rho_GLD_down": float(rho_gld_down),
        "gld_vol_after_spy_crash": float(gld_vol_after_spy_neg),
        "gld_vol_after_spy_surge": float(gld_vol_after_spy_pos),
        "gld_vol_unconditional": float(gld_vol_normal),
        "spy_vol_after_gld_drop": float(spy_vol_after_gld_neg),
        "spy_vol_after_gld_surge": float(spy_vol_after_gld_pos),
        "spy_vol_unconditional": float(spy_vol_normal),
    },
    "hedge_ratio": {
        "mean": float(hedge_ratio.mean()),
        "std": float(hedge_ratio.std()),
        "min": float(hedge_ratio.min()),
        "max": float(hedge_ratio.max()),
        "median": float(hedge_ratio.median()),
    },
    "portfolio_metrics": metrics,
    "bekk_minvar_avg_weights": {
        "SPY": float(w_bekk[1:, 0].mean()),
        "GLD": float(w_bekk[1:, 1].mean()),
    },
    "key_findings": key_findings,
    "plots": [
        "k918_spillover_dynamics.png",
        "k918_hedge_ratio.png",
        "k918_regime_analysis.png"
    ]
}

results_path = os.path.join(OUT_DIR, 'k918_bekk_garch_spillover_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"  Saved: {results_path}")
print(f"\nK918 complete.")
