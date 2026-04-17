"""
K816: GARCH-Informed Neural Network (GINN) — Physics-Informed Volatility Forecasting
=====================================================================================
Proposer: User
Executor: Claude

Literature:
  - Bali, Karabulut & Zhao (2024) GINN, arXiv:2410.00288
  - Patton (2011) QLIKE proxy-robust loss, J. Econometrics 160(1), 246-256
  - Hansen & Lunde (2005) r2 unbiased proxy for sigma2, JFE 72(2), 401-438
  - Harvey et al. (2016) testing with multiple hypotheses, t>3.0 threshold
  - K426: GINN with sklearn MLP, 28 features, MSE loss -> QLIKE +1230% worse
  - K797v2: QLIKE training loss bug fix (must use +log_s2)
  - K784: GARCH-GRU null, K785: MF2 null, K787: HAR directional null

Core Hypothesis:
  GINN embeds GARCH structure into NN as physics-informed prior.
  Unlike K426 (28 generic features) or K784 (black-box GRU), GINN uses ONLY
  4 physics-informed inputs: [r2_{t-1}, sigma2_{GJR,t-1}, VIX_{t-1}, |r_{t-1}|].
  The GJR fitted variance acts as an informed prior -- the NN learns corrections
  to the GARCH base case, not a new model from scratch.

  If structure + flexibility > pure GARCH or pure ML:
  GINN should have lower QLIKE than both GJR and Pure MLP.

Design:
  Models:
    1. GJR-GARCH(1,1) -- baseline
    2. Pure MLP -- 2x32 ReLU, inputs=[r2_{t-1}, |r_{t-1}|, VIX_{t-1}] (NO GJR)
    3. GINN -- 2x32 ReLU, inputs=[r2_{t-1}, sigma2_{GJR,t-1}, |r_{t-1}|]
    4. GINN-VIX -- 2x32 ReLU, inputs=[r2_{t-1}, sigma2_{GJR,t-1}, VIX_{t-1}, |r_{t-1}|]

  Training: PyTorch, QLIKE loss (r2/s2 + log_s2), Adam lr=0.001, 200 epochs max
  Early stopping on validation QLIKE (last 20% of training set)
  Expanding window, refit every 63 trading days
  OOS: 2023-01-01 to 2024-12-31
  Asset: SPY (data from yfinance)

  Output bias initialized to log(mean(r2_train)) for SPY daily.
  log_s2 output (not raw s2) -- prevents negative variance.

LOOKAHEAD CHECK:
  All features at t-1 -> target r2_t.
  GJR sigma2_{t-1} is the FITTED variance from the GARCH model estimated on data up to t-1.
  signal.shift(1) equivalent: features are constructed with explicit lag indexing.
  No contemporaneous data used.

QLIKE TRAINING LOSS (K797v2 verified):
  loss = mean(r2/s2 + log(s2)) where s2 = exp(log_s2)
  NOT -log(s2) + r2/s2 (that diverges to -inf as s2 -> inf).
  Bounded below, minimizer at s2 = r2.

Output: experiments/k816_ginn_garch_nn_results.json
"""

import numpy as np
import pandas as pd
import yfinance as yf
import torch
import torch.nn as nn
import torch.optim as optim
from arch import arch_model
from scipy.stats import spearmanr
import json
import time
import warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K816: GARCH-Informed Neural Network (GINN)")
print("  Physics-informed volatility forecasting with ablation study")
print("  [ALL features strictly lagged -- no contemporaneous data]")
print("=" * 75)

t_start = time.time()

# ============================================================
# STEP 1: Data Download and Diagnostics
# ============================================================
print("\n--- Step 1: Data Download and Diagnostics ---")

spy = yf.download('SPY', start='2005-01-01', end='2025-12-31', progress=False)
vix = yf.download('^VIX', start='2005-01-01', end='2025-12-31', progress=False)

close = spy['Close'].squeeze().dropna()
returns_pct = 100 * close.pct_change().dropna()  # percent returns for GARCH
returns_dec = close.pct_change().dropna()  # decimal returns for r2 proxy
r2 = returns_dec ** 2  # realized variance proxy
abs_ret = returns_dec.abs()

vix_close = vix['Close'].squeeze().dropna()

# Align all series
common_idx = returns_pct.index.intersection(r2.index).intersection(vix_close.index)
returns_pct = returns_pct.loc[common_idx]
returns_dec = returns_dec.loc[common_idx]
r2 = r2.loc[common_idx]
abs_ret = abs_ret.loc[common_idx]
vix_close = vix_close.loc[common_idx]

print(f"Data period: {returns_pct.index[0].strftime('%Y-%m-%d')} to {returns_pct.index[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(returns_pct)}")
print(f"\nDescriptive statistics (returns %):")
print(f"  Mean:     {returns_pct.mean():.4f}")
print(f"  Std:      {returns_pct.std():.4f}")
print(f"  Skewness: {returns_pct.skew():.4f}")
print(f"  Kurtosis: {returns_pct.kurtosis():.4f}")
print(f"  Min:      {returns_pct.min():.4f}")
print(f"  Max:      {returns_pct.max():.4f}")

# ADF test
from statsmodels.tsa.stattools import adfuller
adf_stat, adf_p, _, _, _, _ = adfuller(returns_pct.values, maxlag=20)
print(f"\nADF test: stat={adf_stat:.4f}, p={adf_p:.6f} -> {'Stationary' if adf_p < 0.05 else 'Non-stationary'}")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch
arch_lm_stat, arch_lm_p, _, _ = het_arch(returns_pct.values, nlags=10)
print(f"ARCH LM test (10 lags): stat={arch_lm_stat:.4f}, p={arch_lm_p:.6f} -> {'ARCH effects' if arch_lm_p < 0.05 else 'No ARCH'}")

# Ljung-Box on squared returns
from statsmodels.stats.diagnostic import acorr_ljungbox
lb = acorr_ljungbox(returns_pct.values**2, lags=[10], return_df=True)
lb_stat = lb['lb_stat'].values[0]
lb_p = lb['lb_pvalue'].values[0]
print(f"Ljung-Box on r^2(10): stat={lb_stat:.4f}, p={lb_p:.6f} -> {'Autocorrelated' if lb_p < 0.05 else 'No autocorrelation'}")

# ============================================================
# STEP 2: GJR-GARCH Estimation (Full Sample for Diagnostics)
# ============================================================
print("\n--- Step 2: GJR-GARCH Full-Sample Estimation ---")

am_full = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='normal')
res_full = am_full.fit(disp='off')
print(f"\nGJR-GARCH full-sample parameters:")
print(f"  omega:   {res_full.params['omega']:.6f}")
print(f"  alpha:   {res_full.params['alpha[1]']:.6f}")
print(f"  gamma:   {res_full.params['gamma[1]']:.6f}")
print(f"  beta:    {res_full.params['beta[1]']:.6f}")
persistence = (res_full.params['alpha[1]'] + res_full.params['gamma[1]'] / 2
               + res_full.params['beta[1]'])
print(f"  persist: {persistence:.6f}")
print(f"  converge:{res_full.convergence_flag}")

# Standardized residual diagnostics
std_resid = res_full.std_resid
lb_sr = acorr_ljungbox(std_resid**2, lags=[10], return_df=True)
print(f"  Std resid^2 LB(10) p: {lb_sr['lb_pvalue'].values[0]:.4f}")

garch_params = {
    'omega': float(res_full.params['omega']),
    'alpha': float(res_full.params['alpha[1]']),
    'gamma': float(res_full.params['gamma[1]']),
    'beta': float(res_full.params['beta[1]']),
    'persistence': float(persistence),
    'convergence': int(res_full.convergence_flag),
    'std_resid_sq_LB10_p': float(lb_sr['lb_pvalue'].values[0]),
}

# ============================================================
# STEP 3: Define Models (PyTorch)
# ============================================================
print("\n--- Step 3: Defining GINN Models (PyTorch) ---")


class GINNModel(nn.Module):
    """
    GARCH-Informed Neural Network.
    Output: log(sigma2) -- ensures positive variance via exp().

    Architecture: input -> Linear(hidden) -> LayerNorm -> ReLU
                       -> Linear(hidden) -> LayerNorm -> ReLU
                       -> Linear(1) + output_bias
    """

    def __init__(self, in_dim, hidden_dim=32, init_log_var=-9.0):
        super().__init__()
        self.layer1 = nn.Linear(in_dim, hidden_dim)
        self.ln1 = nn.LayerNorm(hidden_dim)
        self.layer2 = nn.Linear(hidden_dim, hidden_dim)
        self.ln2 = nn.LayerNorm(hidden_dim)
        self.output_layer = nn.Linear(hidden_dim, 1)

        # Initialize output near log(typical daily variance)
        # SPY daily decimal variance ~ 1e-4, log(1e-4) ~ -9.2
        self.output_bias = nn.Parameter(torch.tensor([init_log_var]))

        # Scale output layer weights small for stable start
        with torch.no_grad():
            self.output_layer.weight.data *= 0.1
            self.output_layer.bias.data.zero_()

    def forward(self, x):
        h = torch.relu(self.ln1(self.layer1(x)))
        h = torch.relu(self.ln2(self.layer2(h)))
        log_s2 = self.output_layer(h).squeeze(-1) + self.output_bias
        return log_s2

    def predict_var(self, x):
        """Return sigma2 = exp(log_s2), clamped for safety."""
        with torch.no_grad():
            log_s2 = self.forward(x)
            return torch.exp(log_s2).clamp(min=1e-16, max=1.0)


def qlike_training_loss(log_s2, r2_target):
    """
    QLIKE training loss: mean(r2/s2 + log(s2))
    where s2 = exp(log_s2).

    K797v2 verified: must use +log_s2, NOT -log_s2.
    With -log_s2, loss diverges to -inf when s2 grows large (model collapses).
    With +log_s2, bounded below, stable. Minimizer at s2 = r2.
    """
    s2 = torch.exp(log_s2).clamp(min=1e-16)
    return (r2_target / s2 + log_s2).mean()


def train_ginn(X_train, y_train, in_dim, hidden_dim=32, n_epochs=200,
               lr=0.001, batch_size=64, patience=20, init_log_var=-9.0):
    """
    Train GINN model with expanding window.
    Uses QLIKE training loss, early stopping on validation set (last 20%).

    Returns: (model, X_mean, X_std, best_val_loss)
    """
    # Split: 80% train, 20% validation
    n = len(X_train)
    n_val = max(int(n * 0.2), 20)
    n_tr = n - n_val

    X_tr = X_train[:n_tr]
    y_tr = y_train[:n_tr]
    X_val = X_train[n_tr:]
    y_val = y_train[n_tr:]

    # Normalize inputs
    X_mean = X_tr.mean(axis=0)
    X_std = X_tr.std(axis=0)
    X_std[X_std < 1e-8] = 1e-8

    X_tr_n = (X_tr - X_mean) / X_std
    X_val_n = (X_val - X_mean) / X_std

    # Convert to tensors
    X_tr_t = torch.tensor(X_tr_n, dtype=torch.float32)
    y_tr_t = torch.tensor(y_tr, dtype=torch.float32)
    X_val_t = torch.tensor(X_val_n, dtype=torch.float32)
    y_val_t = torch.tensor(y_val, dtype=torch.float32)

    # Compute init_log_var from training target
    mean_r2 = max(float(np.mean(y_tr)), 1e-12)
    init_log_var_data = float(np.log(mean_r2))

    model = GINNModel(in_dim=in_dim, hidden_dim=hidden_dim,
                      init_log_var=init_log_var_data)
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)

    # DataLoader
    dataset = torch.utils.data.TensorDataset(X_tr_t, y_tr_t)
    loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size,
                                         shuffle=True)

    best_val_loss = np.inf
    best_state = None
    wait = 0

    for epoch in range(n_epochs):
        # Training
        model.train()
        for xb, yb in loader:
            optimizer.zero_grad()
            log_s2 = model(xb)
            loss = qlike_training_loss(log_s2, yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        scheduler.step()

        # Validation
        model.eval()
        with torch.no_grad():
            val_log_s2 = model(X_val_t)
            val_loss = qlike_training_loss(val_log_s2, y_val_t).item()

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()

    return model, X_mean, X_std, best_val_loss


# ============================================================
# STEP 4: Expanding Window OOS Forecasting
# ============================================================
print("\n--- Step 4: Expanding Window OOS Forecasting ---")

oos_start = '2023-01-01'
oos_end = '2024-12-31'
refit_every = 63
min_train = 2000  # minimum training window

# Find OOS indices
oos_mask = (returns_pct.index >= oos_start) & (returns_pct.index <= oos_end)
oos_indices = np.where(oos_mask)[0]
print(f"OOS period: {returns_pct.index[oos_indices[0]].strftime('%Y-%m-%d')} to "
      f"{returns_pct.index[oos_indices[-1]].strftime('%Y-%m-%d')}")
print(f"OOS observations: {len(oos_indices)}")

# Storage for predictions
n_oos = len(oos_indices)
gjr_preds = np.full(n_oos, np.nan)
pure_mlp_preds = np.full(n_oos, np.nan)
ginn_preds = np.full(n_oos, np.nan)
ginn_vix_preds = np.full(n_oos, np.nan)
actual_r2 = np.full(n_oos, np.nan)

# Track model states
current_gjr_res = None
current_pure_mlp = None
current_ginn = None
current_ginn_vix = None
pure_mlp_norm = None
ginn_norm = None
ginn_vix_norm = None

n_refits = 0
last_refit = -refit_every  # force refit at start

for i, oos_idx in enumerate(oos_indices):
    # The actual r2 at time t (what we are predicting)
    actual_r2[i] = r2.iloc[oos_idx]

    # Check if we need to refit
    if i - last_refit >= refit_every or current_gjr_res is None:
        last_refit = i
        n_refits += 1
        train_end = oos_idx  # train on data up to (but not including) oos_idx

        if train_end < min_train:
            print(f"  WARNING: train_end={train_end} < min_train={min_train}, skipping refit")
            continue

        # ---- Refit GJR-GARCH ----
        train_returns = returns_pct.iloc[:train_end]
        am = arch_model(train_returns, vol='GARCH', p=1, o=1, q=1, dist='normal')
        current_gjr_res = am.fit(disp='off', show_warning=False)

        # Extract GJR conditional variances for the training period
        # These are in percent-squared units -- convert to decimal-squared
        gjr_cond_var = current_gjr_res.conditional_volatility ** 2 / (100**2)

        # Build feature matrices for training (all lagged by 1)
        # Features at time t use information from t-1 (and earlier)
        train_r2 = r2.iloc[:train_end].values
        train_abs_ret = abs_ret.iloc[:train_end].values
        train_vix = vix_close.iloc[:train_end].values
        train_gjr_var = gjr_cond_var.values  # sigma2_{GJR,t}

        # Targets: r2_t for t >= 1
        # Features: values from t-1
        # So features[t-1] -> target[t], for t = 1, ..., train_end-1

        # Pure MLP features: [r2_{t-1}, |r_{t-1}|, VIX_{t-1}]
        X_pure_mlp = np.column_stack([
            train_r2[:-1],      # r2_{t-1}
            train_abs_ret[:-1], # |r_{t-1}|
            train_vix[:-1],     # VIX_{t-1}
        ])

        # GINN features: [r2_{t-1}, sigma2_{GJR,t-1}, |r_{t-1}|]
        X_ginn = np.column_stack([
            train_r2[:-1],       # r2_{t-1}
            train_gjr_var[:-1],  # sigma2_{GJR,t-1}  <-- the physics-informed feature
            train_abs_ret[:-1],  # |r_{t-1}|
        ])

        # GINN-VIX features: [r2_{t-1}, sigma2_{GJR,t-1}, VIX_{t-1}, |r_{t-1}|]
        X_ginn_vix = np.column_stack([
            train_r2[:-1],       # r2_{t-1}
            train_gjr_var[:-1],  # sigma2_{GJR,t-1}
            train_vix[:-1],      # VIX_{t-1}
            train_abs_ret[:-1],  # |r_{t-1}|
        ])

        y_target = train_r2[1:]  # r2_t

        # Remove any rows with NaN
        valid = np.isfinite(X_ginn_vix).all(axis=1) & np.isfinite(y_target)
        X_pure_mlp_clean = X_pure_mlp[valid]
        X_ginn_clean = X_ginn[valid]
        X_ginn_vix_clean = X_ginn_vix[valid]
        y_clean = y_target[valid]

        # ---- Train Pure MLP ----
        current_pure_mlp, pm_mean, pm_std, pm_val = train_ginn(
            X_pure_mlp_clean, y_clean, in_dim=3, hidden_dim=32,
            n_epochs=200, lr=0.001, patience=20
        )
        pure_mlp_norm = (pm_mean, pm_std)

        # ---- Train GINN ----
        current_ginn, gn_mean, gn_std, gn_val = train_ginn(
            X_ginn_clean, y_clean, in_dim=3, hidden_dim=32,
            n_epochs=200, lr=0.001, patience=20
        )
        ginn_norm = (gn_mean, gn_std)

        # ---- Train GINN-VIX ----
        current_ginn_vix, gv_mean, gv_std, gv_val = train_ginn(
            X_ginn_vix_clean, y_clean, in_dim=4, hidden_dim=32,
            n_epochs=200, lr=0.001, patience=20
        )
        ginn_vix_norm = (gv_mean, gv_std)

        if n_refits <= 3 or n_refits % 3 == 0:
            print(f"  Refit #{n_refits} at OOS day {i}: "
                  f"val_loss(PureMLP={pm_val:.4f}, GINN={gn_val:.4f}, GINN-VIX={gv_val:.4f})")

    # ---- Generate GJR one-step forecast ----
    if current_gjr_res is not None:
        omega = current_gjr_res.params['omega']
        alpha = current_gjr_res.params['alpha[1]']
        gamma_p = current_gjr_res.params['gamma[1]']
        beta = current_gjr_res.params['beta[1]']

        # Use previous day's data to compute today's forecast
        prev_ret_pct = returns_pct.iloc[oos_idx - 1]  # r_{t-1} in percent
        # Get previous day's conditional variance
        if oos_idx - 1 < len(current_gjr_res.conditional_volatility):
            prev_h = current_gjr_res.conditional_volatility.iloc[oos_idx - 1] ** 2
        else:
            prev_h = current_gjr_res.conditional_volatility.iloc[-1] ** 2

        # GJR recursion: h_t = omega + alpha * r2_{t-1} + gamma * r2_{t-1} * I(r<0) + beta * h_{t-1}
        indicator = 1.0 if prev_ret_pct < 0 else 0.0
        h_t = omega + alpha * prev_ret_pct**2 + gamma_p * prev_ret_pct**2 * indicator + beta * prev_h
        gjr_preds[i] = h_t / (100**2)  # convert percent-squared to decimal-squared

    # ---- Generate NN forecasts ----
    # Features at t-1 for predicting r2_t
    prev_r2 = r2.iloc[oos_idx - 1]
    prev_abs_ret = abs_ret.iloc[oos_idx - 1]
    prev_vix = vix_close.iloc[oos_idx - 1]

    # GJR sigma2_{t-1} from fitted model (in decimal units)
    if current_gjr_res is not None and (oos_idx - 1) < len(current_gjr_res.conditional_volatility):
        prev_gjr_var = current_gjr_res.conditional_volatility.iloc[oos_idx - 1] ** 2 / (100**2)
    else:
        # Fallback: use the GJR recursion result from the previous step
        prev_gjr_var = gjr_preds[max(0, i - 1)] if i > 0 else float(np.mean(r2.iloc[:oos_idx]))

    # Pure MLP: [r2_{t-1}, |r_{t-1}|, VIX_{t-1}]
    if current_pure_mlp is not None and pure_mlp_norm is not None:
        x_pm = np.array([[prev_r2, prev_abs_ret, prev_vix]])
        x_pm_n = (x_pm - pure_mlp_norm[0]) / pure_mlp_norm[1]
        x_pm_t = torch.tensor(x_pm_n, dtype=torch.float32)
        pure_mlp_preds[i] = float(current_pure_mlp.predict_var(x_pm_t).numpy()[0])

    # GINN: [r2_{t-1}, sigma2_{GJR,t-1}, |r_{t-1}|]
    if current_ginn is not None and ginn_norm is not None:
        x_gn = np.array([[prev_r2, prev_gjr_var, prev_abs_ret]])
        x_gn_n = (x_gn - ginn_norm[0]) / ginn_norm[1]
        x_gn_t = torch.tensor(x_gn_n, dtype=torch.float32)
        ginn_preds[i] = float(current_ginn.predict_var(x_gn_t).numpy()[0])

    # GINN-VIX: [r2_{t-1}, sigma2_{GJR,t-1}, VIX_{t-1}, |r_{t-1}|]
    if current_ginn_vix is not None and ginn_vix_norm is not None:
        x_gv = np.array([[prev_r2, prev_gjr_var, prev_vix, prev_abs_ret]])
        x_gv_n = (x_gv - ginn_vix_norm[0]) / ginn_vix_norm[1]
        x_gv_t = torch.tensor(x_gv_n, dtype=torch.float32)
        ginn_vix_preds[i] = float(current_ginn_vix.predict_var(x_gv_t).numpy()[0])

    # Progress
    if (i + 1) % 100 == 0:
        print(f"  OOS day {i+1}/{n_oos} complete")

print(f"\n  Total refits: {n_refits}")
print(f"  Refit interval: {refit_every} days")

# ============================================================
# STEP 5: Evaluation
# ============================================================
print("\n--- Step 5: Evaluation ---")

# Use the project's evaluation utilities
from volpred.stats.model_evaluation import qlike, qlike_pointwise, dm_test


def compute_metrics(actual, predicted, label):
    """Compute QLIKE, Spearman, and diagnostics for a model."""
    valid = np.isfinite(actual) & np.isfinite(predicted) & (predicted > 0)
    a = actual[valid]
    f = predicted[valid]
    n = len(a)

    ql = qlike(a, f)
    sp_rho, sp_p = spearmanr(a, f)
    pearson_r = np.corrcoef(a, f)[0, 1]
    mse = float(np.mean((a - f)**2))
    mae = float(np.mean(np.abs(a - f)))

    print(f"\n  {label}:")
    print(f"    QLIKE:    {ql:.6f}")
    print(f"    MSE:      {mse:.2e}")
    print(f"    MAE:      {mae:.2e}")
    print(f"    Spearman: {sp_rho:.4f} (p={sp_p:.4e})")
    print(f"    Pearson:  {pearson_r:.4f}")
    print(f"    Pred range: [{f.min():.2e}, {f.max():.2e}], mean={f.mean():.2e}")
    print(f"    Valid obs: {n}")

    return {
        'QLIKE': float(ql),
        'MSE': float(mse),
        'MAE': float(mae),
        'Spearman_rho': float(sp_rho),
        'Spearman_p': float(sp_p),
        'Pearson_r': float(pearson_r),
        'pred_min': float(f.min()),
        'pred_max': float(f.max()),
        'pred_mean': float(f.mean()),
        'n_valid': int(n),
    }


# Actual r2
actual = actual_r2
print(f"\nActual r2 range: [{actual[np.isfinite(actual)].min():.2e}, "
      f"{actual[np.isfinite(actual)].max():.2e}], "
      f"mean={actual[np.isfinite(actual)].mean():.2e}")

# Compute metrics for each model
metrics_gjr = compute_metrics(actual, gjr_preds, "GJR-GARCH")
metrics_pure_mlp = compute_metrics(actual, pure_mlp_preds, "Pure MLP (no GJR input)")
metrics_ginn = compute_metrics(actual, ginn_preds, "GINN (with GJR input)")
metrics_ginn_vix = compute_metrics(actual, ginn_vix_preds, "GINN-VIX (GJR + VIX)")

# ============================================================
# STEP 6: DM Tests (pairwise)
# ============================================================
print("\n--- Step 6: DM Tests (Harvey t>3.0 threshold) ---")

# Compute pointwise QLIKE losses
valid_all = (np.isfinite(actual) & np.isfinite(gjr_preds)
             & np.isfinite(pure_mlp_preds) & np.isfinite(ginn_preds)
             & np.isfinite(ginn_vix_preds)
             & (gjr_preds > 0) & (pure_mlp_preds > 0)
             & (ginn_preds > 0) & (ginn_vix_preds > 0))

a_valid = actual[valid_all]
gjr_v = gjr_preds[valid_all]
pm_v = pure_mlp_preds[valid_all]
gn_v = ginn_preds[valid_all]
gv_v = ginn_vix_preds[valid_all]

ql_gjr = qlike_pointwise(a_valid, gjr_v)
ql_pm = qlike_pointwise(a_valid, pm_v)
ql_gn = qlike_pointwise(a_valid, gn_v)
ql_gv = qlike_pointwise(a_valid, gv_v)

dm_tests = {}

# DM convention: dm_test(loss1, loss2)
# Negative DM stat means model 1 is better (lower loss)

pairs = [
    ('GJR vs Pure_MLP', ql_gjr, ql_pm, 'GJR', 'Pure_MLP'),
    ('GJR vs GINN', ql_gjr, ql_gn, 'GJR', 'GINN'),
    ('GJR vs GINN-VIX', ql_gjr, ql_gv, 'GJR', 'GINN-VIX'),
    ('Pure_MLP vs GINN', ql_pm, ql_gn, 'Pure_MLP', 'GINN'),
    ('Pure_MLP vs GINN-VIX', ql_pm, ql_gv, 'Pure_MLP', 'GINN-VIX'),
    ('GINN vs GINN-VIX', ql_gn, ql_gv, 'GINN', 'GINN-VIX'),
]

for label, l1, l2, m1, m2 in pairs:
    dm_stat, dm_p = dm_test(l1, l2)
    significant = abs(dm_stat) > 3.0
    if dm_stat < 0:
        better = m1
    else:
        better = m2
    dm_tests[label] = {
        'DM_stat': float(dm_stat),
        'p_value': float(dm_p),
        'better_model': better,
        'significant_Harvey': significant,
    }
    sig_str = "***" if significant else "ns"
    print(f"  {label}: DM={dm_stat:+.4f} (p={dm_p:.4f}) -> {better} better [{sig_str}]")

# ============================================================
# STEP 7: Ablation Analysis
# ============================================================
print("\n--- Step 7: Ablation Analysis ---")

gjr_ql = metrics_gjr['QLIKE']
ablation = {}
for name, ql_val in [('Pure_MLP', metrics_pure_mlp['QLIKE']),
                      ('GINN', metrics_ginn['QLIKE']),
                      ('GINN-VIX', metrics_ginn_vix['QLIKE'])]:
    pct_change = (ql_val - gjr_ql) / gjr_ql * 100
    direction = "WORSE" if pct_change > 0 else "BETTER"
    ablation[name] = {
        'QLIKE': ql_val,
        'pct_vs_GJR': float(pct_change),
        'direction': direction,
    }
    print(f"  {name}: QLIKE={ql_val:.6f} ({pct_change:+.2f}% vs GJR) [{direction}]")

# The key question: does adding GJR input help?
ginn_vs_mlp = metrics_ginn['QLIKE'] - metrics_pure_mlp['QLIKE']
ginn_vix_vs_mlp = metrics_ginn_vix['QLIKE'] - metrics_pure_mlp['QLIKE']
print(f"\n  GJR input effect (GINN - Pure MLP): {ginn_vs_mlp:+.6f} "
      f"({'helps' if ginn_vs_mlp < 0 else 'hurts'})")
print(f"  GJR+VIX input effect (GINN-VIX - Pure MLP): {ginn_vix_vs_mlp:+.6f} "
      f"({'helps' if ginn_vix_vs_mlp < 0 else 'hurts'})")

# ============================================================
# STEP 8: Conclusion
# ============================================================
print("\n--- Step 8: Conclusion ---")

# Rank models by QLIKE
models_ranked = sorted([
    ('GJR-GARCH', metrics_gjr['QLIKE']),
    ('Pure_MLP', metrics_pure_mlp['QLIKE']),
    ('GINN', metrics_ginn['QLIKE']),
    ('GINN-VIX', metrics_ginn_vix['QLIKE']),
], key=lambda x: x[1])

print("\n  QLIKE Ranking (lower is better):")
for rank, (name, ql) in enumerate(models_ranked, 1):
    marker = " <-" if name == 'GJR-GARCH' else ""
    print(f"    #{rank}: {name:12s} QLIKE={ql:.6f}{marker}")

best_model = models_ranked[0][0]
best_ql = models_ranked[0][1]

# Check if any NN beats GJR significantly
any_beats_gjr = any(
    dm_tests[k]['better_model'] != 'GJR' and dm_tests[k]['significant_Harvey']
    for k in dm_tests if 'GJR' in k
)

# Check if GINN beats Pure MLP significantly
ginn_beats_mlp = dm_tests.get('Pure_MLP vs GINN', {}).get('significant_Harvey', False)

if best_model == 'GJR-GARCH':
    verdict = "NULL: GJR-GARCH remains best -- GINN (physics-informed NN) does not beat pure GARCH"
elif any_beats_gjr:
    verdict = f"POSITIVE: {best_model} significantly beats GJR-GARCH at Harvey t>3.0"
else:
    verdict = f"MARGINAL: {best_model} has lowest QLIKE but difference not significant (Harvey t>3.0)"

# Specific GINN insight
if metrics_ginn['QLIKE'] < metrics_pure_mlp['QLIKE']:
    ginn_insight = "GJR input HELPS: GINN < Pure MLP (physics-informed prior adds value)"
else:
    ginn_insight = "GJR input HURTS/NEUTRAL: GINN >= Pure MLP (physics-informed prior adds no value or is redundant)"

print(f"\n  VERDICT: {verdict}")
print(f"  GINN INSIGHT: {ginn_insight}")

total_time = time.time() - t_start
print(f"\n  Total runtime: {total_time:.1f}s")

# ============================================================
# STEP 9: Save Results
# ============================================================
print("\n--- Step 9: Saving Results ---")

results = {
    "experiment_id": "K816",
    "title": "GARCH-Informed Neural Network (GINN) -- Physics-Informed Volatility Forecasting",
    "date": datetime.now(timezone.utc).isoformat(),
    "proposer": "User",
    "executor": "Claude",
    "asset": "SPY",
    "data_source": "yfinance (SPY + ^VIX)",
    "data_period": f"{returns_pct.index[0].strftime('%Y-%m-%d')} to {returns_pct.index[-1].strftime('%Y-%m-%d')}",
    "total_observations": int(len(returns_pct)),
    "oos_period": f"{returns_pct.index[oos_indices[0]].strftime('%Y-%m-%d')} to {returns_pct.index[oos_indices[-1]].strftime('%Y-%m-%d')}",
    "oos_observations": int(n_oos),
    "refit_every": refit_every,
    "n_refits": n_refits,
    "min_train_window": min_train,
    "literature": [
        "Bali, Karabulut & Zhao (2024) GINN, arXiv:2410.00288",
        "Patton (2011) J. Econometrics 160(1), 246-256 -- QLIKE proxy-robust",
        "Hansen & Lunde (2005) JFE 72(2), 401-438 -- r2 proxy",
        "Harvey et al. (2016) -- multiple testing t>3.0",
        "K426: GINN sklearn MLP, 28 features, MSE loss -> QLIKE +1230% worse",
        "K797v2: QLIKE training loss bug fix (must use +log_s2)",
        "K784: GARCH-GRU null, K785: MF2 null, K787: HAR directional null",
    ],
    "hypothesis": ("Structure + flexibility > pure GARCH or pure ML. "
                   "GINN uses GJR fitted sigma2 as physics-informed prior in NN architecture."),
    "architecture": {
        "GJR-GARCH": "GJR-GARCH(1,1) baseline, arch package",
        "Pure_MLP": {
            "inputs": ["r2_{t-1}", "|r_{t-1}|", "VIX_{t-1}"],
            "hidden": "2x32 neurons, ReLU, LayerNorm",
            "output": "log(sigma2) + learnable bias -> exp -> sigma2",
            "loss": "QLIKE (r2/sigma2 + log(sigma2))",
            "optimizer": "Adam lr=0.001, weight_decay=1e-5",
            "scheduler": "CosineAnnealing",
            "early_stopping": "patience=20 on validation QLIKE (20% holdout)",
            "epochs": "200 max",
        },
        "GINN": {
            "inputs": ["r2_{t-1}", "sigma2_{GJR,t-1}", "|r_{t-1}|"],
            "note": "sigma2_{GJR,t-1} is the physics-informed feature from GARCH",
            "hidden": "2x32 neurons, ReLU, LayerNorm",
            "output": "log(sigma2) + learnable bias -> exp -> sigma2",
            "loss": "QLIKE",
        },
        "GINN-VIX": {
            "inputs": ["r2_{t-1}", "sigma2_{GJR,t-1}", "VIX_{t-1}", "|r_{t-1}|"],
            "note": "Full physics-informed model with market-implied vol",
            "hidden": "2x32 neurons, ReLU, LayerNorm",
            "output": "log(sigma2) + learnable bias -> exp -> sigma2",
            "loss": "QLIKE",
        },
    },
    "diagnostics": {
        "ADF": {"stat": float(adf_stat), "p": float(adf_p),
                "stationary": bool(adf_p < 0.05)},
        "ARCH_LM": {"stat": float(arch_lm_stat), "p": float(arch_lm_p),
                     "arch_effects": bool(arch_lm_p < 0.05)},
        "Ljung_Box_r2": {"stat": float(lb_stat), "p": float(lb_p),
                          "autocorrelated": bool(lb_p < 0.05)},
    },
    "garch_params": garch_params,
    "models": {
        "GJR-GARCH": metrics_gjr,
        "Pure_MLP": metrics_pure_mlp,
        "GINN": metrics_ginn,
        "GINN-VIX": metrics_ginn_vix,
    },
    "dm_tests": dm_tests,
    "ablation": ablation,
    "gjr_input_effect": {
        "GINN_minus_PureMLP_QLIKE": float(ginn_vs_mlp),
        "GINN-VIX_minus_PureMLP_QLIKE": float(ginn_vix_vs_mlp),
        "gjr_input_helps": bool(ginn_vs_mlp < 0),
        "insight": ginn_insight,
    },
    "ranking": [{"rank": r+1, "model": n, "QLIKE": float(q)}
                for r, (n, q) in enumerate(models_ranked)],
    "verdict": verdict,
    "ginn_insight": ginn_insight,
    "any_nn_beats_gjr_harvey": bool(any_beats_gjr),
    "ginn_beats_pure_mlp_harvey": bool(ginn_beats_mlp),
    "total_runtime_s": round(total_time, 1),
    "k426_comparison": (
        "K426 used sklearn MLPRegressor with MSE loss + 28 generic features -> QLIKE +1230% worse. "
        "K816 uses PyTorch with proper QLIKE training loss + only 4 physics-informed features. "
        "This tests whether the failure was due to (a) wrong loss function, (b) too many features, "
        "or (c) fundamental ML ceiling."
    ),
    "lookahead_check": {
        "all_features_lagged": True,
        "lag_mechanism": ("Features at t-1 -> target r2_t. "
                          "GJR sigma2_{t-1} from model fitted on data up to t-1. "
                          "No contemporaneous data."),
        "shift_equivalent": "Explicit index-based lag (features[t-1] -> target[t])",
    },
    "limitations": [
        "r2 proxy for sigma2 is noisy (no intraday data) -- Hansen & Lunde (2005)",
        "Single asset (SPY) -- cross-asset validation needed",
        "OOS 2023-2024 (~500 days) -- limited OOS sample",
        "Hidden dim=32 -- larger architectures not tested",
        "No attention/transformer -- only feedforward MLP",
        "GJR refit every 63 days -- params may be stale during fast regimes",
        "VIX is closing value -- intraday VIX spikes not captured",
    ],
}

out_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/k816_ginn_garch_nn_results.json"
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to: {out_path}")
print(f"\n{'=' * 75}")
print(f"K816 COMPLETE: {verdict}")
print(f"{'=' * 75}")
