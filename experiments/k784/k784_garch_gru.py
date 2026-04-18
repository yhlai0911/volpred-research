#!/usr/bin/env python3
"""
K784: GARCH-GRU Hybrid Volatility Forecasting
===============================================
[提出: 用戶, 執行: Claude]

Inspired by arXiv:2504.09380 "Integrated GARCH-GRU in Financial Volatility
Forecasting" (April 2025). The paper embeds GARCH(1,1) variance directly into
the GRU cell, creating a unified recurrent unit that leverages both the
econometric structure of GARCH and the sequence-learning ability of GRU.

Implementation (faithful to the paper's spirit):
  1. Pre-compute GARCH(1,1) conditional variance series for training window
  2. Build feature vector: [r_t, r^2_t, sigma^2_t_garch, |r_t|, log(sigma^2_t)]
  3. GRU(hidden=32, layers=1) -> Linear(1) -> sigma^2_{t+1}
  4. Train with QLIKE loss (Patton 2011 robust, our standard metric)
  5. Expanding window, refit every 63 days (quarterly), min 2000 obs

Benchmarks:
  - GJR-GARCH(1,1) -- Glosten, Jagannathan, Runkle (1993)
  - GARCH(1,1) -- Bollerslev (1986)
  - EWMA (lambda=0.94) -- RiskMetrics
  - HAR-r^2 -- Corsi (2009) adapted for squared returns

Assessment (on r^2 target per Patton 2011):
  - QLIKE (primary)
  - MSE
  - Spearman rank correlation
  - DM test vs GJR-GARCH (Harvey t>3.0 threshold)

Data: SPY from yfinance, 2006-01-01 ~ present
OOS: 2023-01-01 ~ 2024-12-31 (~504 trading days)
Window: expanding, min 2000 obs

References:
  - arXiv:2504.09380 "Integrated GARCH-GRU" (April 2025)
  - Bollerslev (1986) J.Econometrics -- GARCH(1,1)
  - Glosten, Jagannathan, Runkle (1993) JoF -- GJR-GARCH
  - Corsi (2009) J.Financial Econometrics -- HAR
  - Patton (2011) J.Econometrics -- robust loss functions, QLIKE
  - Harvey et al. (2016) -- multiple testing threshold t>3.0

CRITICAL: No lookahead. GRU trained only on data before forecast date.
          All forecasts are strictly out-of-sample.
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
import torch
import torch.nn as nn
from scipy.optimize import minimize
from scipy.stats import spearmanr, norm as norm_dist
from numba import njit
from datetime import datetime, timezone
import warnings
import os
import time

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__),
                            'k784_garch_gru_results.json')

# ============================================================
# GARCH Filters (numba-accelerated)
# ============================================================

@njit(cache=True)
def garch11_filter(r, omega, alpha, beta):
    """GARCH(1,1) variance filter. Returns sigma^2 array."""
    T = len(r)
    sigma2 = np.zeros(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i]**2
    var_r /= T
    sigma2[0] = var_r
    for t in range(1, T):
        sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-12:
            sigma2[t] = 1e-12
    return sigma2


@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1) variance filter. Returns sigma^2 array."""
    T = len(r)
    sigma2 = np.zeros(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i]**2
    var_r /= T
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if r[t-1] < 0 else 0.0
        sigma2[t] = omega + (alpha + gamma * ind) * r[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-12:
            sigma2[t] = 1e-12
    return sigma2


# ============================================================
# Model Fitting
# ============================================================

def fit_garch11(returns):
    """Fit GARCH(1,1) via quasi-MLE."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    T = len(r)
    if T < 50:
        return None
    def negll(params, r):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        sigma2 = garch11_filter(r, omega, alpha, beta)
        ll = -0.5 * np.sum(np.log(sigma2[1:]) + r[1:]**2 / sigma2[1:])
        return -ll if np.isfinite(ll) else 1e10

    rv = np.var(r)
    best = None
    best_nll = 1e10
    for seed in range(3):
        np.random.seed(seed + 200)
        a0 = max(0.01, min(0.3, 0.05 + 0.03 * np.random.randn()))
        b0 = max(0.5, min(0.98, 0.90 + 0.04 * np.random.randn()))
        if a0 + b0 >= 0.99:
            b0 = 0.98 - a0
        o0 = rv * (1 - a0 - b0)
        res = minimize(negll, [max(1e-8, o0), a0, b0], args=(r,),
                      method='L-BFGS-B',
                      bounds=[(1e-10, None), (0, 0.5), (0, 0.999)],
                      options={'maxiter': 2000})
        if res.fun < best_nll:
            best_nll = res.fun
            best = res
    if best is None:
        return None
    return {
        'omega': best.x[0], 'alpha': best.x[1],
        'beta': best.x[2],
        'persistence': best.x[1] + best.x[2]
    }


def fit_gjr_garch(returns):
    """Fit GJR-GARCH(1,1) via quasi-MLE."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    T = len(r)
    if T < 50:
        return None
    def negll(params, r):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        sigma2 = gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * np.sum(np.log(sigma2[1:]) + r[1:]**2 / sigma2[1:])
        return -ll if np.isfinite(ll) else 1e10

    rv = np.var(r)
    best = None
    best_nll = 1e10
    for seed in range(3):
        np.random.seed(seed + 100)
        a0 = max(0.01, min(0.3, 0.05 + 0.03 * np.random.randn()))
        b0 = max(0.5, min(0.98, 0.88 + 0.04 * np.random.randn()))
        g0 = max(0.01, min(0.3, 0.08 + 0.04 * np.random.randn()))
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = rv * (1 - a0 - b0 - 0.5 * g0)
        res = minimize(negll, [max(1e-8, o0), a0, b0, g0], args=(r,),
                      method='L-BFGS-B',
                      bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                      options={'maxiter': 2000})
        if res.fun < best_nll:
            best_nll = res.fun
            best = res
    if best is None:
        return None
    return {
        'omega': best.x[0], 'alpha': best.x[1],
        'beta': best.x[2], 'gamma': best.x[3],
        'persistence': best.x[1] + best.x[2] + 0.5 * best.x[3]
    }


def garch11_forecast(returns, params):
    """One-step-ahead GARCH(1,1) forecast -> sigma^2_{t+1}."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    sigma2 = garch11_filter(r, params['omega'], params['alpha'], params['beta'])
    return max(params['omega'] + params['alpha'] * r[-1]**2
               + params['beta'] * sigma2[-1], 1e-12)


def gjr_forecast(returns, params):
    """One-step-ahead GJR-GARCH forecast -> sigma^2_{t+1}."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    sigma2 = gjr_filter(r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    return max(params['omega'] + (params['alpha'] + params['gamma'] * ind) * r[-1]**2
               + params['beta'] * sigma2[-1], 1e-12)


def ewma_forecast(returns, lam=0.94):
    """EWMA variance forecast -> sigma^2_{t+1}."""
    var = returns[0]**2
    for i in range(1, len(returns)):
        var = lam * var + (1 - lam) * returns[i]**2
    return max(var, 1e-12)


def fit_har_sq(sq_ret):
    """HAR-SQ: r^2_t = b0 + b1*r^2_{t-1} + b5*MA5(r^2) + b22*MA22(r^2)."""
    x = sq_ret.copy()
    n = len(x)
    if n < 30:
        return None
    ma5 = pd.Series(x).rolling(5).mean().values
    ma22 = pd.Series(x).rolling(22).mean().values
    vs = 22
    if n <= vs + 30:
        return None
    idx = np.arange(vs, n)
    Y = x[idx]
    X = np.column_stack([np.ones(len(idx)), x[idx-1], ma5[idx-1], ma22[idx-1]])
    valid = ~(np.isnan(X).any(axis=1) | np.isnan(Y))
    if valid.sum() < 30:
        return None
    Y, X = Y[valid], X[valid]
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return None
    return beta


def har_sq_forecast(sq_ret, beta):
    """One-step-ahead HAR-SQ forecast -> E[r^2_{t+1}]."""
    n = len(sq_ret)
    if n < 22:
        return None
    return max(beta[0] + beta[1]*sq_ret[-1] + beta[2]*np.mean(sq_ret[-5:])
               + beta[3]*np.mean(sq_ret[-22:]), 1e-10)


# ============================================================
# GARCH-GRU Model (PyTorch)
# ============================================================

class GARCHGRUModel(nn.Module):
    """
    GRU with GARCH-informed features.

    Input features per timestep:
      [r_t, r^2_t, sigma^2_t (GARCH), |r_t|, log(sigma^2_t)]

    The GARCH variance is pre-computed and fed as an input feature,
    following the spirit of arXiv:2504.09380 where GARCH structure
    informs the recurrent cell.
    """
    def __init__(self, input_size=5, hidden_size=32, num_layers=1, dropout=0.0):
        super().__init__()
        self.gru = nn.GRU(input_size, hidden_size, num_layers,
                          batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden_size, 1)
        self.softplus = nn.Softplus()  # ensure positive output

    def forward(self, x):
        # x: (batch, seq_len, input_size)
        out, _ = self.gru(x)
        # Take last timestep output
        last = out[:, -1, :]  # (batch, hidden)
        pred = self.softplus(self.fc(last))  # (batch, 1), positive
        return pred.squeeze(-1)


def build_gru_features(returns, garch_sigma2):
    """
    Build feature matrix for GRU.
    Features at time t: [r_t, r^2_t, sigma^2_t, |r_t|, log(sigma^2_t)]
    All are known at time t (no lookahead).
    """
    r = np.array(returns, dtype=np.float64)
    s2 = np.array(garch_sigma2, dtype=np.float64)
    n = len(r)
    features = np.zeros((n, 5))
    features[:, 0] = r                    # r_t
    features[:, 1] = r**2                 # r^2_t
    features[:, 2] = s2                   # sigma^2_t (GARCH)
    features[:, 3] = np.abs(r)            # |r_t|
    features[:, 4] = np.log(np.maximum(s2, 1e-12))  # log(sigma^2_t)
    return features


def create_sequences(features, targets, seq_len=22):
    """
    Create (sequence, target) pairs for GRU training.

    For each t in [seq_len, n-2]:
      X[i] = features[t-seq_len : t]   (features from t-seq_len to t-1)
      y[i] = targets[t]                (r^2 at time t)

    NO LOOKAHEAD: features[t-seq_len : t] uses only data up to time t-1.
    The target r^2_t is the realized squared return at time t.
    So we are using info up to t-1 to predict what happens at t.
    """
    n = len(features)
    X_list = []
    y_list = []
    for t in range(seq_len, n):
        X_list.append(features[t-seq_len:t])
        y_list.append(targets[t])
    return np.array(X_list), np.array(y_list)


def qlike_loss_torch(y_pred, y_true):
    """
    QLIKE loss for PyTorch training.
    Optimizes: mean( y_true/y_pred + log(y_pred) )
    (constant -log(y_true) - 1 dropped since it doesn't affect gradients)
    """
    eps = 1e-8
    y_pred = y_pred.clamp(min=eps)
    y_true = y_true.clamp(min=eps)
    return torch.mean(y_true / y_pred + torch.log(y_pred))


def train_garch_gru(features, targets, seq_len=22, hidden_size=32,
                    lr=0.001, epochs=50, batch_size=32, seed=42,
                    val_frac=0.2):
    """
    Train GARCH-GRU model with QLIKE loss and early stopping.
    Returns trained model and normalization stats.
    """
    torch.manual_seed(seed)
    np.random.seed(seed)

    # Create sequences
    X, y = create_sequences(features, targets, seq_len)
    if len(X) < 100:
        return None, None, None

    # Train/val split (last val_frac for validation)
    n_total = len(X)
    n_val = max(50, int(n_total * val_frac))
    n_train = n_total - n_val

    X_train, y_train = X[:n_train], y[:n_train]
    X_val, y_val = X[n_train:], y[n_train:]

    # Normalize features (per-feature mean/std from training data)
    feat_mean = X_train.reshape(-1, X_train.shape[2]).mean(axis=0)
    feat_std = X_train.reshape(-1, X_train.shape[2]).std(axis=0)
    feat_std[feat_std < 1e-10] = 1.0

    X_train_norm = (X_train - feat_mean) / feat_std
    X_val_norm = (X_val - feat_mean) / feat_std

    # Convert to tensors
    X_train_t = torch.FloatTensor(X_train_norm)
    y_train_t = torch.FloatTensor(y_train)
    X_val_t = torch.FloatTensor(X_val_norm)
    y_val_t = torch.FloatTensor(y_val)

    # Build model
    model = GARCHGRUModel(input_size=5, hidden_size=hidden_size)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode='min', factor=0.5, patience=5, min_lr=1e-5)

    # Training loop with early stopping
    best_val_loss = float('inf')
    best_state = None
    patience = 10
    patience_counter = 0

    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(len(X_train_t))
        total_loss = 0.0
        n_batches = 0

        for i in range(0, len(perm), batch_size):
            idx = perm[i:i+batch_size]
            xb = X_train_t[idx]
            yb = y_train_t[idx]

            pred = model(xb)
            loss = qlike_loss_torch(pred, yb)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        # Validation
        model.eval()  # noqa: eval is nn.Module.eval(), not builtin eval()
        with torch.no_grad():
            val_pred = model(X_val_t)
            val_loss = qlike_loss_torch(val_pred, y_val_t).item()

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= patience:
                break

    # Load best model
    if best_state is not None:
        model.load_state_dict(best_state)

    norm_stats = {'mean': feat_mean, 'std': feat_std}
    return model, norm_stats, best_val_loss


def garch_gru_forecast(model, features, norm_stats, seq_len=22):
    """
    One-step-ahead forecast from GARCH-GRU.
    Uses the last seq_len feature vectors to predict sigma^2_{t+1}.
    NO LOOKAHEAD: features only include information available at time t.
    """
    if model is None or len(features) < seq_len:
        return None

    x = features[-seq_len:]
    x_norm = (x - norm_stats['mean']) / norm_stats['std']
    x_t = torch.FloatTensor(x_norm).unsqueeze(0)  # (1, seq_len, 5)

    model.eval()  # noqa: eval is nn.Module.eval(), not builtin eval()
    with torch.no_grad():
        pred = model(x_t)
    return max(float(pred.item()), 1e-12)


# ============================================================
# Metrics
# ============================================================

def qlike(actual, predicted):
    """QLIKE loss: actual/predicted - log(actual/predicted) - 1."""
    a = np.array(actual, dtype=np.float64)
    p = np.array(predicted, dtype=np.float64)
    valid = (a > 0) & (p > 0) & np.isfinite(a) & np.isfinite(p)
    a, p = a[valid], p[valid]
    if len(a) == 0:
        return np.nan
    return float(np.mean(a / p - np.log(a / p) - 1))


def mse_metric(actual, predicted):
    """Mean Squared Error."""
    a = np.array(actual, dtype=np.float64)
    p = np.array(predicted, dtype=np.float64)
    valid = np.isfinite(a) & np.isfinite(p)
    return float(np.mean((a[valid] - p[valid])**2))


def pointwise_qlike(actual, predicted):
    """Pointwise QLIKE losses for DM test."""
    a = np.array(actual, dtype=np.float64)
    p = np.array(predicted, dtype=np.float64)
    ratio = a / p
    return ratio - np.log(ratio) - 1


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC. Negative -> model 1 better."""
    d = np.array(loss1) - np.array(loss2)
    n = len(d)
    d_mean = np.mean(d)
    bandwidth = max(1, int(np.ceil(n**(1/3))))
    gamma0 = np.mean(d**2) - d_mean**2
    gamma_sum = 0.0
    for k in range(1, bandwidth + 1):
        gk = np.mean(d[k:] * d[:-k]) - d_mean**2
        gamma_sum += 2 * (1 - k / (bandwidth + 1)) * gk
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return {'stat': 0.0, 'pvalue': 1.0}
    t_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * norm_dist.cdf(-abs(t_stat))
    return {'stat': float(t_stat), 'pvalue': float(p_val)}


# ============================================================
# Main Experiment
# ============================================================

def main():
    print("=" * 70)
    print("K784: GARCH-GRU Hybrid Volatility Forecasting")
    print("=" * 70)
    t0 = time.time()

    # ----------------------------------------------------------
    # 1. Download Data
    # ----------------------------------------------------------
    print("\n[1] Downloading SPY data...")
    spy = yf.download('SPY', start='2006-01-01', end='2025-01-01',
                      progress=False, auto_adjust=True)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = spy.sort_index()
    returns = spy['Close'].pct_change().dropna()
    returns.name = 'return'

    print(f"  Total returns: {len(returns)} ({returns.index[0].strftime('%Y-%m-%d')} "
          f"to {returns.index[-1].strftime('%Y-%m-%d')})")

    # ----------------------------------------------------------
    # 2. Descriptive Statistics (diagnostics first)
    # ----------------------------------------------------------
    print("\n[2] Descriptive Statistics:")
    r_arr = returns.values
    print(f"  Mean:     {np.mean(r_arr)*252:.4f} (annualized)")
    print(f"  Std:      {np.std(r_arr)*np.sqrt(252):.4f} (annualized)")
    print(f"  Skewness: {pd.Series(r_arr).skew():.4f}")
    print(f"  Kurtosis: {pd.Series(r_arr).kurt():.4f}")
    print(f"  Min:      {np.min(r_arr):.4f}")
    print(f"  Max:      {np.max(r_arr):.4f}")

    # ----------------------------------------------------------
    # 3. OOS Configuration
    # ----------------------------------------------------------
    oos_start = '2023-01-01'
    oos_end = '2024-12-31'
    min_window = 2000
    refit_freq = 63  # quarterly refit
    seq_len = 22     # GRU lookback (1 month)

    oos_mask = (returns.index >= oos_start) & (returns.index <= oos_end)
    oos_dates = returns.index[oos_mask]
    print(f"\n[3] OOS period: {oos_start} to {oos_end}")
    print(f"  OOS days: {len(oos_dates)}")

    # ----------------------------------------------------------
    # 4. Rolling OOS Forecasts
    # ----------------------------------------------------------
    print("\n[4] Generating OOS forecasts (expanding window, refit every 63 days)...")

    forecasts = {
        'garch_gru': [],
        'gjr_garch': [],
        'garch11': [],
        'ewma': [],
        'har_sq': [],
    }
    actual_r2 = []
    dates_out = []

    # Model caches
    gjr_params = None
    garch_params = None
    har_beta = None
    gru_model = None
    gru_norm = None
    last_refit = -refit_freq  # force first refit

    all_returns = returns.values
    all_dates = returns.index
    all_r2 = all_returns**2

    oos_positions = np.where(oos_mask)[0]
    n_oos = len(oos_positions)

    print(f"  Processing {n_oos} OOS forecasts...")
    refit_count = 0

    for i, pos in enumerate(oos_positions):
        if pos < min_window:
            continue

        # Training data: all data before forecast date (NO LOOKAHEAD)
        train_ret = all_returns[:pos]
        train_r2 = all_r2[:pos]
        T_train = len(train_ret)

        # Refit check
        days_since_refit = i - last_refit
        need_refit = (days_since_refit >= refit_freq) or (gjr_params is None)

        if need_refit:
            refit_count += 1
            if refit_count <= 3 or refit_count % 2 == 0:
                print(f"  Refit #{refit_count} at OOS day {i+1}/{n_oos} "
                      f"(train={T_train} obs)")

            # Fit GJR-GARCH
            gjr_params = fit_gjr_garch(train_ret)

            # Fit GARCH(1,1)
            garch_params = fit_garch11(train_ret)

            # Fit HAR-SQ
            har_beta = fit_har_sq(train_r2)

            # Fit GARCH-GRU
            if garch_params is not None:
                garch_sigma2 = garch11_filter(
                    np.ascontiguousarray(train_ret, dtype=np.float64),
                    garch_params['omega'], garch_params['alpha'],
                    garch_params['beta'])

                gru_features = build_gru_features(train_ret, garch_sigma2)

                gru_model, gru_norm, val_loss = train_garch_gru(
                    gru_features, train_r2,
                    seq_len=seq_len, hidden_size=32,
                    lr=0.001, epochs=50, batch_size=32, seed=42,
                    val_frac=0.2)
                if refit_count <= 3 or refit_count % 2 == 0:
                    vl_str = f"{val_loss:.6f}" if val_loss is not None else "N/A"
                    print(f"    GARCH-GRU val QLIKE: {vl_str}")
            else:
                gru_model = None
                gru_norm = None

            last_refit = i

        # --- Generate forecasts for r^2 at position pos ---
        actual_val = all_r2[pos]

        # GJR-GARCH
        fc_gjr = gjr_forecast(train_ret, gjr_params) if gjr_params else np.nan

        # GARCH(1,1)
        fc_garch = garch11_forecast(train_ret, garch_params) if garch_params else np.nan

        # EWMA
        fc_ewma = ewma_forecast(train_ret)

        # HAR-SQ
        fc_har = har_sq_forecast(train_r2, har_beta) if har_beta is not None else np.nan

        # GARCH-GRU
        if gru_model is not None and gru_norm is not None and garch_params is not None:
            garch_sigma2_full = garch11_filter(
                np.ascontiguousarray(train_ret, dtype=np.float64),
                garch_params['omega'], garch_params['alpha'],
                garch_params['beta'])
            gru_feat_pred = build_gru_features(train_ret, garch_sigma2_full)
            fc_gru = garch_gru_forecast(gru_model, gru_feat_pred, gru_norm,
                                       seq_len=seq_len)
        else:
            fc_gru = np.nan

        forecasts['garch_gru'].append(fc_gru if fc_gru is not None else np.nan)
        forecasts['gjr_garch'].append(fc_gjr if fc_gjr is not None else np.nan)
        forecasts['garch11'].append(fc_garch if fc_garch is not None else np.nan)
        forecasts['ewma'].append(fc_ewma if fc_ewma is not None else np.nan)
        forecasts['har_sq'].append(fc_har if fc_har is not None else np.nan)
        actual_r2.append(actual_val)
        dates_out.append(str(all_dates[pos].date()))

        if (i+1) % 100 == 0:
            print(f"  Progress: {i+1}/{n_oos}")

    actual_arr = np.array(actual_r2)
    n_forecasts = len(actual_arr)
    print(f"\n  Completed: {n_forecasts} OOS forecasts, {refit_count} refits")

    # ----------------------------------------------------------
    # 5. Results
    # ----------------------------------------------------------
    print("\n[5] Results (target: r^2)")
    print("-" * 70)

    model_names = ['garch_gru', 'gjr_garch', 'garch11', 'ewma', 'har_sq']
    display_names = {
        'garch_gru': 'GARCH-GRU',
        'gjr_garch': 'GJR-GARCH',
        'garch11': 'GARCH(1,1)',
        'ewma': 'EWMA(0.94)',
        'har_sq': 'HAR-SQ',
    }

    results_table = {}
    for name in model_names:
        fc = np.array(forecasts[name])
        valid = np.isfinite(fc) & np.isfinite(actual_arr) & (fc > 0) & (actual_arr > 0)
        if valid.sum() < 10:
            print(f"  {display_names[name]}: insufficient valid forecasts ({valid.sum()})")
            results_table[name] = {
                'qlike': np.nan, 'mse': np.nan,
                'spearman': np.nan, 'spearman_p': np.nan,
                'n_valid': int(valid.sum())
            }
            continue

        a = actual_arr[valid]
        p = fc[valid]

        q = qlike(a, p)
        m = mse_metric(a, p)
        sr, sp = spearmanr(a, p)

        results_table[name] = {
            'qlike': round(q, 6),
            'mse': round(m, 12),
            'spearman': round(sr, 4),
            'spearman_p': round(sp, 6),
            'n_valid': int(valid.sum())
        }

        print(f"  {display_names[name]:15s}  QLIKE={q:.6f}  MSE={m:.2e}  "
              f"Spearman={sr:.4f} (p={sp:.4f})  N={valid.sum()}")

    # ----------------------------------------------------------
    # 6. DM Tests (GARCH-GRU vs each benchmark)
    # ----------------------------------------------------------
    print("\n[6] Diebold-Mariano Tests (GARCH-GRU vs benchmarks)")
    print("-" * 70)

    dm_results = {}
    fc_gru_arr = np.array(forecasts['garch_gru'])

    for bm_name in ['gjr_garch', 'garch11', 'ewma', 'har_sq']:
        fc_bm = np.array(forecasts[bm_name])
        valid = (np.isfinite(fc_gru_arr) & np.isfinite(fc_bm) &
                 np.isfinite(actual_arr) &
                 (fc_gru_arr > 0) & (fc_bm > 0) & (actual_arr > 0))

        if valid.sum() < 50:
            print(f"  vs {display_names[bm_name]}: insufficient overlap ({valid.sum()})")
            dm_results[bm_name] = {'stat': np.nan, 'pvalue': np.nan}
            continue

        a = actual_arr[valid]
        p_gru = fc_gru_arr[valid]
        p_bm = fc_bm[valid]

        loss_gru = pointwise_qlike(a, p_gru)
        loss_bm = pointwise_qlike(a, p_bm)

        dm = dm_test(loss_gru, loss_bm)
        dm_results[bm_name] = dm

        direction = "GARCH-GRU better" if dm['stat'] < 0 else f"{display_names[bm_name]} better"
        sig = "***" if abs(dm['stat']) > 3.0 else ("**" if abs(dm['stat']) > 2.0 else
              ("*" if abs(dm['stat']) > 1.65 else ""))
        print(f"  vs {display_names[bm_name]:15s}  DM={dm['stat']:+.4f} {sig:4s} "
              f"p={dm['pvalue']:.4f}  [{direction}]")

    # ----------------------------------------------------------
    # 7. Model Ranking
    # ----------------------------------------------------------
    print("\n[7] Model Ranking (by QLIKE)")
    print("-" * 70)
    ranking = sorted(
        [(name, results_table[name]['qlike'])
         for name in model_names if np.isfinite(results_table[name].get('qlike', np.nan))],
        key=lambda x: x[1]
    )
    for rank, (name, ql) in enumerate(ranking, 1):
        marker = " <-- GARCH-GRU" if name == 'garch_gru' else ""
        print(f"  #{rank}: {display_names[name]:15s}  QLIKE={ql:.6f}{marker}")

    gru_rank = next((r for r, (n, _) in enumerate(ranking, 1) if n == 'garch_gru'), -1)

    # ----------------------------------------------------------
    # 8. Harvey (2016) significance
    # ----------------------------------------------------------
    print("\n[8] Harvey (2016) Significance Check")
    print("-" * 70)
    any_significant = False
    for bm_name, dm in dm_results.items():
        if np.isfinite(dm['stat']) and abs(dm['stat']) > 3.0:
            any_significant = True
            better = "GARCH-GRU" if dm['stat'] < 0 else display_names[bm_name]
            print(f"  SIGNIFICANT: |DM|={abs(dm['stat']):.2f} > 3.0 "
                  f"({better} significantly better, vs {display_names[bm_name]})")

    if not any_significant:
        print("  No pairwise comparison reaches Harvey (2016) t>3.0 threshold.")
        print("  All models are statistically indistinguishable at this stringent level.")

    # ----------------------------------------------------------
    # 9. Summary
    # ----------------------------------------------------------
    elapsed = time.time() - t0
    print(f"\n[9] Summary")
    print("=" * 70)

    gjr_qlike = results_table.get('gjr_garch', {}).get('qlike', np.nan)
    gru_qlike = results_table.get('garch_gru', {}).get('qlike', np.nan)
    beats_gjr = gru_qlike < gjr_qlike if (np.isfinite(gru_qlike) and np.isfinite(gjr_qlike)) else None

    dm_vs_gjr = dm_results.get('gjr_garch', {})
    dm_stat_gjr = dm_vs_gjr.get('stat', np.nan)

    if beats_gjr is True:
        improvement = (gjr_qlike - gru_qlike) / gjr_qlike * 100
        print(f"  GARCH-GRU QLIKE: {gru_qlike:.6f} (rank #{gru_rank})")
        print(f"  GJR-GARCH QLIKE: {gjr_qlike:.6f}")
        print(f"  Improvement: {improvement:.2f}%")
        if np.isfinite(dm_stat_gjr) and dm_stat_gjr < -3.0:
            print(f"  DM test: {dm_stat_gjr:.4f} -> STATISTICALLY SIGNIFICANT (Harvey t>3.0)")
        else:
            print(f"  DM test: {dm_stat_gjr:.4f} -> NOT significant at Harvey t>3.0")
    elif beats_gjr is False:
        degradation = (gru_qlike - gjr_qlike) / gjr_qlike * 100
        print(f"  GARCH-GRU QLIKE: {gru_qlike:.6f} (rank #{gru_rank})")
        print(f"  GJR-GARCH QLIKE: {gjr_qlike:.6f}")
        print(f"  Degradation: +{degradation:.2f}% (GARCH-GRU is worse)")
    else:
        print(f"  GARCH-GRU QLIKE: {gru_qlike}")
        print(f"  GJR-GARCH QLIKE: {gjr_qlike}")

    print(f"\n  Elapsed: {elapsed:.1f}s")

    # ----------------------------------------------------------
    # 10. Save Results
    # ----------------------------------------------------------
    results = {
        'experiment_id': 'K784',
        'title': 'GARCH-GRU Hybrid Volatility Forecasting',
        'description': 'Integrates GARCH(1,1) variance as input feature to GRU '
                       'for volatility forecasting (inspired by arXiv:2504.09380)',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance (SPY)',
        'data_period': f"{returns.index[0].strftime('%Y-%m-%d')} to "
                       f"{returns.index[-1].strftime('%Y-%m-%d')}",
        'oos_period': f"{oos_start} to {oos_end}",
        'n_total': len(returns),
        'n_oos': n_forecasts,
        'n_refits': refit_count,
        'methodology': {
            'model': 'GRU(hidden=32, layers=1) with GARCH-informed features',
            'features': ['r_t', 'r^2_t', 'sigma^2_t(GARCH)', '|r_t|', 'log(sigma^2_t)'],
            'seq_len': seq_len,
            'training_loss': 'QLIKE',
            'refit_frequency': f'{refit_freq} trading days',
            'min_window': min_window,
            'expanding_window': True,
            'epochs': 50,
            'batch_size': 32,
            'hidden_size': 32,
            'early_stopping_patience': 10,
            'learning_rate': 0.001,
            'seed': 42,
        },
        'benchmarks': ['GJR-GARCH(1,1)', 'GARCH(1,1)', 'EWMA(0.94)', 'HAR-SQ'],
        'target': 'r^2 (squared returns, Patton 2011 proxy-robust)',
        'results': {
            name: {
                'display_name': display_names[name],
                **results_table[name]
            }
            for name in model_names
        },
        'dm_tests': {
            f'garch_gru_vs_{bm}': {
                'stat': round(dm['stat'], 4) if np.isfinite(dm['stat']) else None,
                'pvalue': round(dm['pvalue'], 4) if np.isfinite(dm['pvalue']) else None,
                'significant_harvey': bool(np.isfinite(dm['stat']) and abs(dm['stat']) > 3.0),
                'better_model': 'GARCH-GRU' if (np.isfinite(dm['stat']) and dm['stat'] < 0)
                               else display_names.get(bm, bm)
            }
            for bm, dm in dm_results.items()
        },
        'ranking': [
            {'rank': r, 'model': display_names[n], 'qlike': round(q, 6)}
            for r, (n, q) in enumerate(ranking, 1)
        ],
        'garch_gru_rank': gru_rank,
        'garch_gru_beats_gjr': beats_gjr,
        'conclusion': '',
        'limitations': [
            'Daily returns only (no intraday RV)',
            'Single asset (SPY) -- needs cross-asset validation',
            'GARCH component is pre-computed, not fully integrated into GRU cell',
            'Relatively short OOS period (504 days)',
            'r^2 is noisy proxy for true sigma^2 (Patton 2011 guarantees ranking consistency)',
            'GRU hyperparameters not extensively tuned',
        ],
        'references': [
            'arXiv:2504.09380 -- Integrated GARCH-GRU (April 2025)',
            'Bollerslev (1986) J.Econometrics -- GARCH(1,1)',
            'Glosten, Jagannathan, Runkle (1993) JoF -- GJR-GARCH',
            'Corsi (2009) J.Financial Econometrics -- HAR',
            'Patton (2011) J.Econometrics -- robust loss, QLIKE',
            'Harvey et al. (2016) -- multiple testing t>3.0',
        ],
        'elapsed_seconds': round(elapsed, 1),
    }

    # Build conclusion
    if beats_gjr is True:
        sig_text = ("statistically significant" if (np.isfinite(dm_stat_gjr) and dm_stat_gjr < -3.0)
                    else "NOT statistically significant")
        improvement = (gjr_qlike - gru_qlike) / gjr_qlike * 100
        results['conclusion'] = (
            f"GARCH-GRU (rank #{gru_rank}) achieves QLIKE={gru_qlike:.6f}, "
            f"beating GJR-GARCH ({gjr_qlike:.6f}) by {improvement:.2f}%. "
            f"However, the DM test (t={dm_stat_gjr:.4f}) is {sig_text} at "
            f"Harvey (2016) t>3.0 threshold. "
            f"The hybrid model captures nonlinear dynamics beyond GARCH's linear structure."
        )
    elif beats_gjr is False:
        results['conclusion'] = (
            f"GARCH-GRU (rank #{gru_rank}) achieves QLIKE={gru_qlike:.6f}, "
            f"WORSE than GJR-GARCH ({gjr_qlike:.6f}). The added complexity of GRU "
            f"does not improve upon the parsimonious GJR-GARCH for daily SPY volatility. "
            f"This is consistent with the literature suggesting GARCH is hard to beat "
            f"for daily equity volatility without intraday data."
        )
    else:
        results['conclusion'] = "Insufficient data to draw conclusion."

    print(f"\n  Conclusion: {results['conclusion']}")

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {RESULTS_PATH}")

    return results


if __name__ == '__main__':
    results = main()
