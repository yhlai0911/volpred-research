"""K618: Kolmogorov-Arnold Network (KAN) for Volatility Forecasting
— Can structured neural networks beat GARCH?

Motivation:
  K590 literature search found KAN-GARCH-MIDAS (J. Applied Economics 2025)
  and KAN for VIX (Expert Systems 2025). KAN uses learnable activation
  functions (B-splines on each edge) instead of fixed activations — claimed
  to be more interpretable than MLP.
  Literature claims 8% MAE improvement over GARCH.
  BUT K600 meta-lesson says "ML cannot beat GARCH overall" (Branco 2024).

Prior art in our system:
  K530: HAR-ABS champion (QLIKE 0.49, DM=-15.45 vs GJR)
  K533: prediction != application (HAR best predictor, worst VT strategy)
  K592: MF2-GARCH null (ML hybrid worse than GJR)
  K600: ML整體無法勝 GARCH

Literature:
  - Liu et al. (2024): KAN: Kolmogorov-Arnold Networks, arXiv:2404.19756
  - KAN-GARCH-MIDAS, J. Applied Economics 2025
  - KAN for VIX forecasting, Expert Systems 2025
  - Corsi (2009, JFE): HAR-RV model
  - Branco et al. (2024): ML vs GARCH meta-study

Design:
  1. Data: SPY daily returns from yfinance (2005-2026)
  2. Features (all lagged, no look-ahead):
     - |r_{t-1}|, |r_{t-2}|, ..., |r_{t-5}| (recent absolute returns)
     - mean(|r_{t-1:t-5}|), mean(|r_{t-1:t-22}|) (HAR-like multi-scale)
     - VIX_{t-1} / 100 (scaled)
  3. Target: |r_t| (next-day absolute return)
  4. Models:
     a. KAN: Minimal B-spline KAN (1 hidden layer, 5 nodes)
     b. MLP: standard 2-layer neural network (baseline)
     c. GJR-GARCH(1,1): our standard benchmark
     d. HAR-ABS: K530's champion
  5. Training: rolling window w=1000, retrain every 63 days
  6. OOS: 2023-2024
  7. Evaluate: QLIKE + MSE + DM test (Harvey t>3.0 threshold)

Usage:
    uv run python experiments/k618_kan_volatility.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))


# ============================================================
#  Utility functions
# ============================================================

def print_section(title: str, char: str = "=", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(realized/forecast - log(realized/forecast) - 1)."""
    mask = (realized > 0) & (forecast > 0)
    r, f = realized[mask], forecast[mask]
    ratio = r / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Element-wise QLIKE loss."""
    ratio = realized / forecast
    return ratio - np.log(ratio) - 1


def mse_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """Mean squared error."""
    return float(np.mean((realized - forecast) ** 2))


def dm_test(loss1: np.ndarray, loss2: np.ndarray) -> tuple[float, float]:
    """Diebold-Mariano test. Negative t = model 1 better."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)
    # Newey-West HAC with lag = int(n^(1/3))
    max_lag = int(n ** (1 / 3))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for h in range(1, max_lag + 1):
        w = 1 - h / (max_lag + 1)
        gamma_h = np.mean((d[h:] - d_bar) * (d[:-h] - d_bar))
        gamma_sum += 2 * w * gamma_h
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ============================================================
#  Minimal KAN Implementation (B-spline based)
# ============================================================

class BSplineActivation(nn.Module):
    """Learnable B-spline activation function for one edge.

    Each edge in a KAN has its own learnable activation function,
    parameterized as a linear combination of B-spline basis functions.
    """

    def __init__(self, n_bases: int = 8, x_range: tuple = (-3.0, 3.0)):
        super().__init__()
        self.n_bases = n_bases
        self.x_min, self.x_max = x_range
        # Knot positions (uniformly spaced)
        self.register_buffer(
            'knots',
            torch.linspace(self.x_min, self.x_max, n_bases + 2)
        )
        # Learnable coefficients
        self.coeffs = nn.Parameter(torch.randn(n_bases) * 0.1)
        # Also add a residual SiLU (as in original KAN paper)
        self.silu_weight = nn.Parameter(torch.tensor(1.0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # B-spline basis (order 1 = piecewise linear for efficiency)
        bases = []
        for i in range(self.n_bases):
            left = self.knots[i]
            center = self.knots[i + 1]
            right = self.knots[i + 2] if i + 2 < len(self.knots) else center + (center - left)

            # Triangle basis function
            b = torch.zeros_like(x)
            # Rising part
            mask_rise = (x >= left) & (x < center)
            if center > left:
                b = torch.where(mask_rise, (x - left) / (center - left + 1e-8), b)
            # Falling part
            mask_fall = (x >= center) & (x < right)
            if right > center:
                b = torch.where(mask_fall, (right - x) / (right - center + 1e-8), b)
            bases.append(b)

        bases = torch.stack(bases, dim=-1)  # (..., n_bases)
        spline_out = (bases * self.coeffs).sum(dim=-1)

        # Residual connection with SiLU
        silu_out = self.silu_weight * torch.nn.functional.silu(x)

        return spline_out + silu_out


class KANLayer(nn.Module):
    """One layer of KAN: each (input, output) pair has its own
    learnable activation function."""

    def __init__(self, in_features: int, out_features: int, n_bases: int = 8):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features

        # One activation per edge (in_features * out_features edges)
        self.activations = nn.ModuleList([
            BSplineActivation(n_bases=n_bases)
            for _ in range(in_features * out_features)
        ])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, in_features)
        batch_size = x.shape[0]
        outputs = torch.zeros(batch_size, self.out_features, device=x.device)

        idx = 0
        for j in range(self.out_features):
            for i in range(self.in_features):
                outputs[:, j] += self.activations[idx](x[:, i])
                idx += 1

        return outputs


class KANModel(nn.Module):
    """Minimal KAN for volatility forecasting.
    Architecture: input -> KAN hidden layer -> linear output
    """

    def __init__(self, in_features: int, hidden_size: int = 5, n_bases: int = 8):
        super().__init__()
        self.kan_layer = KANLayer(in_features, hidden_size, n_bases=n_bases)
        self.output_layer = nn.Linear(hidden_size, 1)
        # Ensure positive output
        self.softplus = nn.Softplus()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.kan_layer(x)
        out = self.output_layer(h)
        return self.softplus(out).squeeze(-1)


# ============================================================
#  Standard MLP for comparison
# ============================================================

class MLPModel(nn.Module):
    """Standard 2-layer MLP baseline."""

    def __init__(self, in_features: int, hidden_size: int = 32):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_features, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Linear(hidden_size // 2, 1),
            nn.Softplus(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


# ============================================================
#  Training helper
# ============================================================

def train_nn_model(
    model: nn.Module,
    X_train: np.ndarray,
    y_train: np.ndarray,
    epochs: int = 200,
    lr: float = 0.001,
    batch_size: int = 128,
    patience: int = 20,
) -> nn.Module:
    """Train a neural network with early stopping."""
    device = torch.device('cpu')
    model = model.to(device)

    X_t = torch.FloatTensor(X_train).to(device)
    y_t = torch.FloatTensor(y_train).to(device)

    # Split into train/val (last 20% for validation)
    n = len(X_t)
    n_val = max(int(n * 0.2), 50)
    X_tr, X_val = X_t[:-n_val], X_t[-n_val:]
    y_tr, y_val = y_t[:-n_val], y_t[-n_val:]

    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode='min', factor=0.5, patience=10
    )

    best_val_loss = float('inf')
    best_state = None
    no_improve = 0

    model.train()
    for epoch in range(epochs):
        # Mini-batch training
        perm = torch.randperm(len(X_tr))
        epoch_loss = 0.0
        n_batches = 0

        for i in range(0, len(X_tr), batch_size):
            idx = perm[i:i + batch_size]
            x_batch = X_tr[idx]
            y_batch = y_tr[idx]

            pred = model(x_batch)
            # MSE loss on absolute returns
            loss = torch.mean((pred - y_batch) ** 2)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            epoch_loss += loss.item()
            n_batches += 1

        # Validation
        model.eval()
        with torch.no_grad():
            val_pred = model(X_val)
            val_loss = torch.mean((val_pred - y_val) ** 2).item()
        model.train()

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1

        if no_improve >= patience:
            break

    if best_state is not None:
        model.load_state_dict(best_state)

    model.eval()
    return model


# ============================================================
#  GJR-GARCH(1,1) via arch package
# ============================================================

def gjr_rolling_forecast(returns: np.ndarray, window: int,
                         refit_every: int = 22) -> np.ndarray:
    """Rolling GJR-GARCH forecasts."""
    from arch import arch_model

    n = len(returns)
    forecasts = np.full(n, np.nan)

    last_fit_idx = -refit_every  # Force first fit
    last_params = None

    for t in range(window, n):
        if t - last_fit_idx >= refit_every or t == window:
            train_ret = returns[t - window:t]
            try:
                am = arch_model(train_ret * 100, vol='GARCH', p=1, o=1, q=1,
                                mean='Zero', dist='normal', rescale=False)
                res = am.fit(disp='off', options={'maxiter': 500})
                fc = res.forecast(horizon=1)
                var_pct2 = fc.variance.values[-1, 0]
                forecasts[t] = np.sqrt(var_pct2 / 10000)
                last_fit_idx = t
                last_params = res.params.values
            except Exception:
                forecasts[t] = np.std(train_ret)
        else:
            # Use last fitted model with updated data
            try:
                train_ret = returns[t - window:t]
                am = arch_model(train_ret * 100, vol='GARCH', p=1, o=1, q=1,
                                mean='Zero', dist='normal', rescale=False)
                if last_params is not None:
                    res = am.fit(disp='off', starting_values=last_params,
                                 options={'maxiter': 100})
                else:
                    res = am.fit(disp='off', options={'maxiter': 100})
                fc = res.forecast(horizon=1)
                var_pct2 = fc.variance.values[-1, 0]
                forecasts[t] = np.sqrt(var_pct2 / 10000)
            except Exception:
                forecasts[t] = np.std(train_ret)

    return forecasts


# ============================================================
#  HAR-ABS model (K530 champion)
# ============================================================

def har_abs_forecast(abs_returns: np.ndarray, window: int,
                     refit_every: int = 22) -> np.ndarray:
    """HAR-ABS: c + b1*RV1 + b5*RV5 + b22*RV22."""
    n = len(abs_returns)
    forecasts = np.full(n, np.nan)

    # Precompute rolling means
    rv5 = pd.Series(abs_returns).rolling(5).mean().values
    rv22 = pd.Series(abs_returns).rolling(22).mean().values

    last_fit_idx = -refit_every
    betas = None

    for t in range(window, n):
        if t - last_fit_idx >= refit_every or betas is None:
            # Construct features for training window
            train_end = t
            train_start = t - window

            y_list = []
            X_list = []
            for s in range(max(train_start, 22), train_end):
                if not np.isnan(rv5[s - 1]) and not np.isnan(rv22[s - 1]):
                    y_list.append(abs_returns[s])
                    X_list.append([1.0, abs_returns[s - 1], rv5[s - 1], rv22[s - 1]])

            if len(y_list) > 30:
                X_mat = np.array(X_list)
                y_vec = np.array(y_list)
                try:
                    betas = np.linalg.lstsq(X_mat, y_vec, rcond=None)[0]
                except np.linalg.LinAlgError:
                    betas = np.array([np.mean(y_vec), 0.0, 0.5, 0.5])

            last_fit_idx = t

        if betas is not None and not np.isnan(rv5[t - 1]) and not np.isnan(rv22[t - 1]):
            x_now = np.array([1.0, abs_returns[t - 1], rv5[t - 1], rv22[t - 1]])
            forecasts[t] = max(np.dot(betas, x_now), 1e-6)

    return forecasts


# ============================================================
#  Feature construction
# ============================================================

def build_features(returns: np.ndarray, vix: np.ndarray = None) -> np.ndarray:
    """Build feature matrix for neural network models.

    Features (all lagged by 1, no look-ahead):
      0-4: |r_{t-1}|, |r_{t-2}|, ..., |r_{t-5}| (5 features)
      5:   mean(|r_{t-1:t-5}|) (5-day mean abs return)
      6:   mean(|r_{t-1:t-22}|) (22-day mean abs return)
      7:   VIX_{t-1} / 100 (if available)
    """
    n = len(returns)
    abs_ret = np.abs(returns)

    n_features = 8 if vix is not None else 7
    X = np.full((n, n_features), np.nan)

    for t in range(22, n):
        # Recent absolute returns (lagged 1-5)
        for lag in range(1, 6):
            X[t, lag - 1] = abs_ret[t - lag]

        # Multi-scale means
        X[t, 5] = np.mean(abs_ret[t - 5:t])   # 5-day
        X[t, 6] = np.mean(abs_ret[t - 22:t])   # 22-day

        # VIX (lagged 1)
        if vix is not None and t >= 1:
            X[t, 7] = vix[t - 1] / 100.0

    return X


# ============================================================
#  Main experiment
# ============================================================

def main():
    start_time = time.time()
    print_section("K618: KAN vs MLP vs GJR-GARCH vs HAR-ABS")
    print("Kolmogorov-Arnold Network for Volatility Forecasting")
    print("Start: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # ----------------------------------------------------------
    #  1. Load data
    # ----------------------------------------------------------
    print_section("1. Data Loading", "-")

    import yfinance as yf

    spy = yf.download("SPY", start="2004-01-01", end="2026-03-27", progress=False)
    vix = yf.download("^VIX", start="2004-01-01", end="2026-03-27", progress=False)

    # Handle MultiIndex columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    # Align dates
    common_idx = spy.index.intersection(vix.index)
    spy = spy.loc[common_idx]
    vix_close = vix.loc[common_idx, 'Close'].values.astype(float)

    returns = spy['Close'].pct_change().values.astype(float)
    abs_returns = np.abs(returns)

    print("SPY data: " + spy.index[0].strftime('%Y-%m-%d') + " to " + spy.index[-1].strftime('%Y-%m-%d'))
    print("Total observations: " + str(len(returns)))

    # ----------------------------------------------------------
    #  2. Descriptive statistics
    # ----------------------------------------------------------
    print_section("2. Descriptive Statistics (Full Sample)", "-")

    valid_ret = returns[~np.isnan(returns)]
    print("Mean daily return:   " + str(round(np.mean(valid_ret), 6)))
    print("Std daily return:    " + str(round(np.std(valid_ret), 6)))
    print("Skewness:            " + str(round(float(stats.skew(valid_ret)), 4)))
    print("Kurtosis (excess):   " + str(round(float(stats.kurtosis(valid_ret)), 4)))
    print("Mean |return|:       " + str(round(np.mean(np.abs(valid_ret)), 6)))
    print("VIX mean:            " + str(round(np.mean(vix_close), 2)))
    print("VIX std:             " + str(round(np.std(vix_close), 2)))

    # Jarque-Bera test
    from scipy.stats import jarque_bera
    jb_stat, jb_p = jarque_bera(valid_ret[1:])
    print("Jarque-Bera:         " + str(round(jb_stat, 1)) + " (p=" + str(round(jb_p, 2)) + ")")

    # ----------------------------------------------------------
    #  3. Define OOS period
    # ----------------------------------------------------------
    print_section("3. OOS Setup", "-")

    dates = spy.index
    oos_start = pd.Timestamp("2023-01-01")
    oos_end = pd.Timestamp("2024-12-31")

    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_indices = np.where(oos_mask)[0]

    print("OOS period: " + oos_start.strftime('%Y-%m-%d') + " to " + oos_end.strftime('%Y-%m-%d'))
    print("OOS observations: " + str(len(oos_indices)))

    if len(oos_indices) == 0:
        print("ERROR: No OOS observations found!")
        return

    window = 1000
    refit_every = 63  # Quarterly refit for NNs

    print("Training window: " + str(window))
    print("NN refit frequency: every " + str(refit_every) + " days")

    # ----------------------------------------------------------
    #  4. Build features
    # ----------------------------------------------------------
    print_section("4. Feature Construction", "-")

    X = build_features(returns, vix_close)
    y = abs_returns.copy()

    # Check valid range
    valid_from = 22  # Need 22 lags for features
    print("Features available from index " + str(valid_from))
    print("Feature shape: " + str(X.shape))
    print("Feature names: |r_t-1|...|r_t-5|, rv5, rv22, VIX/100")

    # Standardization statistics from training data
    train_end = oos_indices[0]
    train_X = X[valid_from:train_end]
    valid_mask_train = ~np.any(np.isnan(train_X), axis=1)
    train_X_valid = train_X[valid_mask_train]

    feat_mean = np.mean(train_X_valid, axis=0)
    feat_std = np.std(train_X_valid, axis=0)
    feat_std[feat_std < 1e-8] = 1.0

    print("Feature means: " + str(np.round(feat_mean, 4)))
    print("Feature stds:  " + str(np.round(feat_std, 4)))

    # ----------------------------------------------------------
    #  5. Run all models
    # ----------------------------------------------------------

    # 5a. GJR-GARCH
    print_section("5a. GJR-GARCH(1,1) Rolling Forecast", "-")
    t0 = time.time()

    gjr_forecasts = gjr_rolling_forecast(returns, window=window, refit_every=22)

    gjr_time = time.time() - t0
    print("GJR-GARCH done in " + str(round(gjr_time, 1)) + "s")

    # 5b. HAR-ABS
    print_section("5b. HAR-ABS Rolling Forecast", "-")
    t0 = time.time()

    har_forecasts = har_abs_forecast(abs_returns, window=window, refit_every=22)

    har_time = time.time() - t0
    print("HAR-ABS done in " + str(round(har_time, 1)) + "s")

    # 5c. KAN
    print_section("5c. KAN Rolling Forecast", "-")
    t0 = time.time()

    n_features = X.shape[1]
    kan_forecasts = np.full(len(returns), np.nan)

    refit_points = list(range(oos_indices[0], oos_indices[-1] + 1, refit_every))
    if oos_indices[-1] not in refit_points:
        refit_points.append(oos_indices[-1] + 1)

    print("KAN refit points: " + str(len(refit_points)) + " intervals")

    for seg_idx, refit_t in enumerate(refit_points):
        # Training data: [refit_t - window, refit_t)
        tr_start = max(valid_from, refit_t - window)
        tr_end = refit_t

        # Collect valid training samples
        X_tr_list, y_tr_list = [], []
        for t in range(tr_start, tr_end):
            if not np.any(np.isnan(X[t])) and not np.isnan(y[t]):
                X_tr_list.append(X[t])
                y_tr_list.append(y[t])

        if len(X_tr_list) < 100:
            continue

        X_train = np.array(X_tr_list)
        y_train = np.array(y_tr_list)

        # Standardize features
        local_mean = np.mean(X_train, axis=0)
        local_std = np.std(X_train, axis=0)
        local_std[local_std < 1e-8] = 1.0
        X_train_std = (X_train - local_mean) / local_std

        # Train KAN
        torch.manual_seed(42 + seg_idx)
        kan = KANModel(in_features=n_features, hidden_size=5, n_bases=8)
        kan = train_nn_model(kan, X_train_std, y_train, epochs=200, lr=0.001, patience=20)

        # Forecast for the next segment
        if seg_idx + 1 < len(refit_points):
            seg_end = refit_points[seg_idx + 1]
        else:
            seg_end = oos_indices[-1] + 1

        for t in range(refit_t, min(seg_end, len(returns))):
            if not np.any(np.isnan(X[t])):
                x_std = (X[t] - local_mean) / local_std
                x_tensor = torch.FloatTensor(x_std).unsqueeze(0)
                with torch.no_grad():
                    pred = kan(x_tensor).item()
                kan_forecasts[t] = max(pred, 1e-6)

        if (seg_idx + 1) % 2 == 0:
            print("  KAN segment " + str(seg_idx + 1) + "/" + str(len(refit_points)) + " done")

    kan_time = time.time() - t0
    print("KAN done in " + str(round(kan_time, 1)) + "s")

    # 5d. MLP
    print_section("5d. MLP Rolling Forecast", "-")
    t0 = time.time()

    mlp_forecasts = np.full(len(returns), np.nan)

    for seg_idx, refit_t in enumerate(refit_points):
        tr_start = max(valid_from, refit_t - window)
        tr_end = refit_t

        X_tr_list, y_tr_list = [], []
        for t in range(tr_start, tr_end):
            if not np.any(np.isnan(X[t])) and not np.isnan(y[t]):
                X_tr_list.append(X[t])
                y_tr_list.append(y[t])

        if len(X_tr_list) < 100:
            continue

        X_train = np.array(X_tr_list)
        y_train = np.array(y_tr_list)

        local_mean = np.mean(X_train, axis=0)
        local_std = np.std(X_train, axis=0)
        local_std[local_std < 1e-8] = 1.0
        X_train_std = (X_train - local_mean) / local_std

        torch.manual_seed(42 + seg_idx)
        mlp = MLPModel(in_features=n_features, hidden_size=32)
        mlp = train_nn_model(mlp, X_train_std, y_train, epochs=200, lr=0.001, patience=20)

        if seg_idx + 1 < len(refit_points):
            seg_end = refit_points[seg_idx + 1]
        else:
            seg_end = oos_indices[-1] + 1

        for t in range(refit_t, min(seg_end, len(returns))):
            if not np.any(np.isnan(X[t])):
                x_std = (X[t] - local_mean) / local_std
                x_tensor = torch.FloatTensor(x_std).unsqueeze(0)
                with torch.no_grad():
                    pred = mlp(x_tensor).item()
                mlp_forecasts[t] = max(pred, 1e-6)

        if (seg_idx + 1) % 2 == 0:
            print("  MLP segment " + str(seg_idx + 1) + "/" + str(len(refit_points)) + " done")

    mlp_time = time.time() - t0
    print("MLP done in " + str(round(mlp_time, 1)) + "s")

    # ----------------------------------------------------------
    #  6. Evaluate OOS
    # ----------------------------------------------------------
    print_section("6. OOS Evaluation (2023-2024)", "=")

    # Get OOS realized values
    realized_oos = abs_returns[oos_indices]

    # Get forecasts for OOS
    gjr_oos = gjr_forecasts[oos_indices]
    har_oos = har_forecasts[oos_indices]
    kan_oos = kan_forecasts[oos_indices]
    mlp_oos = mlp_forecasts[oos_indices]

    # Check valid counts
    model_forecasts = {
        'GJR-GARCH': gjr_oos,
        'HAR-ABS': har_oos,
        'KAN': kan_oos,
        'MLP': mlp_oos,
    }

    print("\nForecast coverage:")
    for name, fc in model_forecasts.items():
        valid = np.sum(~np.isnan(fc))
        print("  " + name + ": " + str(valid) + "/" + str(len(fc)) + " valid")

    # Find common valid indices
    valid_mask = ~np.isnan(realized_oos)
    for fc in model_forecasts.values():
        valid_mask &= ~np.isnan(fc)
    valid_mask &= (realized_oos > 0)

    n_valid = np.sum(valid_mask)
    print("\nCommon valid observations: " + str(n_valid))

    if n_valid < 50:
        print("ERROR: Too few valid observations for evaluation!")
        return

    # Filter to valid
    realized = realized_oos[valid_mask]
    gjr_fc = gjr_oos[valid_mask]
    har_fc = har_oos[valid_mask]
    kan_fc = kan_oos[valid_mask]
    mlp_fc = mlp_oos[valid_mask]

    # Compute losses
    print_section("6a. Loss Metrics", "-")

    results = {}
    for name, fc in [('GJR-GARCH', gjr_fc), ('HAR-ABS', har_fc),
                      ('KAN', kan_fc), ('MLP', mlp_fc)]:
        q = qlike_loss(realized, fc)
        m = mse_loss(realized, fc)
        mae = float(np.mean(np.abs(realized - fc)))
        corr = float(np.corrcoef(realized, fc)[0, 1])

        results[name] = {
            'QLIKE': q,
            'MSE': m,
            'MAE': mae,
            'Correlation': corr,
        }
        print("\n" + name + ":")
        print("  QLIKE:       " + str(round(q, 6)))
        print("  MSE:         " + str(round(m, 8)))
        print("  MAE:         " + str(round(mae, 6)))
        print("  Correlation: " + str(round(corr, 4)))

    # Ranking
    print_section("6b. Rankings", "-")

    for metric in ['QLIKE', 'MSE', 'MAE']:
        ranked = sorted(results.items(), key=lambda x: x[1][metric])
        print("\n" + metric + " ranking (lower = better):")
        for rank, (name, res) in enumerate(ranked, 1):
            print("  " + str(rank) + ". " + name + ": " + str(round(res[metric], 6)))

    # ----------------------------------------------------------
    #  7. DM Tests
    # ----------------------------------------------------------
    print_section("7. Diebold-Mariano Tests (QLIKE loss)", "=")

    # Compute element-wise QLIKE losses
    qlike_gjr = qlike_loss_array(realized, gjr_fc)
    qlike_har = qlike_loss_array(realized, har_fc)
    qlike_kan = qlike_loss_array(realized, kan_fc)
    qlike_mlp = qlike_loss_array(realized, mlp_fc)

    dm_results = {}

    pairs = [
        ('KAN', 'GJR-GARCH', qlike_kan, qlike_gjr),
        ('KAN', 'HAR-ABS', qlike_kan, qlike_har),
        ('KAN', 'MLP', qlike_kan, qlike_mlp),
        ('MLP', 'GJR-GARCH', qlike_mlp, qlike_gjr),
        ('MLP', 'HAR-ABS', qlike_mlp, qlike_har),
        ('HAR-ABS', 'GJR-GARCH', qlike_har, qlike_gjr),
    ]

    print("\nHarvey (2016) threshold: |t| > 3.0 for significance")
    print("Negative t = first model BETTER than second\n")

    for name1, name2, loss1, loss2 in pairs:
        t_stat, p_val = dm_test(loss1, loss2)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))
        winner = name1 if t_stat < 0 else name2

        dm_key = name1 + "_vs_" + name2
        dm_results[dm_key] = {
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
            'significant_Harvey': abs(t_stat) > 3.0,
            'winner': winner,
        }

        direction = " -> " + name1 + " better" if t_stat < 0 else " -> " + name2 + " better"
        print("  " + name1 + " vs " + name2 + ": t=" + str(round(t_stat, 4)) + " (p=" + str(round(p_val, 4)) + ") " + sig)
        print("   " + direction)

    # ----------------------------------------------------------
    #  8. MSE DM Tests
    # ----------------------------------------------------------
    print_section("8. Diebold-Mariano Tests (MSE loss)", "-")

    mse_gjr = (realized - gjr_fc) ** 2
    mse_har = (realized - har_fc) ** 2
    mse_kan = (realized - kan_fc) ** 2
    mse_mlp = (realized - mlp_fc) ** 2

    mse_dm_results = {}

    pairs_mse = [
        ('KAN', 'GJR-GARCH', mse_kan, mse_gjr),
        ('KAN', 'HAR-ABS', mse_kan, mse_har),
        ('KAN', 'MLP', mse_kan, mse_mlp),
        ('MLP', 'GJR-GARCH', mse_mlp, mse_gjr),
        ('HAR-ABS', 'GJR-GARCH', mse_har, mse_gjr),
    ]

    for name1, name2, loss1, loss2 in pairs_mse:
        t_stat, p_val = dm_test(loss1, loss2)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))

        mse_dm_results[name1 + "_vs_" + name2] = {
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
        }

        print("  " + name1 + " vs " + name2 + ": t=" + str(round(t_stat, 4)) + " (p=" + str(round(p_val, 4)) + ") " + sig)

    # ----------------------------------------------------------
    #  9. Sub-period analysis
    # ----------------------------------------------------------
    print_section("9. Sub-period Analysis", "-")

    oos_dates = dates[oos_indices][valid_mask]

    sub_periods = {
        '2023': (pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31")),
        '2024': (pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")),
    }

    sub_period_results = {}
    for period_name, (p_start, p_end) in sub_periods.items():
        sub_mask = (oos_dates >= p_start) & (oos_dates <= p_end)
        n_sub = np.sum(sub_mask)
        if n_sub < 30:
            continue

        print("\n  " + period_name + " (n=" + str(n_sub) + "):")
        sub_res = {}
        for name, fc in [('GJR-GARCH', gjr_fc[sub_mask]), ('HAR-ABS', har_fc[sub_mask]),
                          ('KAN', kan_fc[sub_mask]), ('MLP', mlp_fc[sub_mask])]:
            q = qlike_loss(realized[sub_mask], fc)
            m = mse_loss(realized[sub_mask], fc)
            sub_res[name] = {'QLIKE': round(q, 6), 'MSE': round(m, 8)}
            print("    " + name + ": QLIKE=" + str(round(q, 6)) + ", MSE=" + str(round(m, 8)))
        sub_period_results[period_name] = sub_res

    # ----------------------------------------------------------
    #  10. KAN interpretability analysis
    # ----------------------------------------------------------
    print_section("10. KAN Interpretability", "-")

    # Retrain one final KAN on the full training set to analyze
    tr_end = oos_indices[0]
    X_tr_list, y_tr_list = [], []
    for t in range(valid_from, tr_end):
        if not np.any(np.isnan(X[t])) and not np.isnan(y[t]):
            X_tr_list.append(X[t])
            y_tr_list.append(y[t])

    X_final = np.array(X_tr_list)
    y_final = np.array(y_tr_list)

    final_mean = np.mean(X_final, axis=0)
    final_std = np.std(X_final, axis=0)
    final_std[final_std < 1e-8] = 1.0
    X_final_std = (X_final - final_mean) / final_std

    torch.manual_seed(42)
    kan_final = KANModel(in_features=n_features, hidden_size=5, n_bases=8)
    kan_final = train_nn_model(kan_final, X_final_std, y_final, epochs=300, lr=0.001, patience=30)

    # Feature importance via permutation
    print("\nPermutation Feature Importance (KAN):")
    feature_names = ['|r_t-1|', '|r_t-2|', '|r_t-3|', '|r_t-4|', '|r_t-5|',
                     'rv5', 'rv22', 'VIX/100']

    # Use last 200 training samples for importance evaluation
    X_test_data = X_final_std[-200:]
    y_test_data = y_final[-200:]
    X_test = torch.FloatTensor(X_test_data)

    with torch.no_grad():
        base_pred = kan_final(X_test).numpy()
    base_mse = np.mean((y_test_data - base_pred) ** 2)

    importances = {}
    for feat_idx in range(n_features):
        X_perm = X_test.clone()
        perm_idx = torch.randperm(len(X_perm))
        X_perm[:, feat_idx] = X_perm[perm_idx, feat_idx]

        with torch.no_grad():
            perm_pred = kan_final(X_perm).numpy()
        perm_mse = np.mean((y_test_data - perm_pred) ** 2)

        importance = (perm_mse - base_mse) / (base_mse + 1e-10)
        importances[feature_names[feat_idx]] = round(float(importance), 4)
        print("  " + feature_names[feat_idx].rjust(8) + ": " + str(round(importance, 4)) + " (" + str(round(importance * 100, 1)) + "%)")

    # Sort by importance
    sorted_imp = sorted(importances.items(), key=lambda x: -x[1])
    print("\nRanked by importance:")
    for rank, (name, imp) in enumerate(sorted_imp, 1):
        print("  " + str(rank) + ". " + name + ": " + str(round(imp * 100, 1)) + "%")

    # ----------------------------------------------------------
    #  11. KAN parameter count comparison
    # ----------------------------------------------------------
    print_section("11. Model Complexity", "-")

    kan_params = sum(p.numel() for p in kan_final.parameters())

    torch.manual_seed(42)
    mlp_ref = MLPModel(in_features=n_features, hidden_size=32)
    mlp_params = sum(p.numel() for p in mlp_ref.parameters())

    print("KAN parameters:       " + str(kan_params))
    print("MLP parameters:       " + str(mlp_params))
    print("GJR-GARCH parameters: 4 (omega, alpha, gamma, beta)")
    print("HAR-ABS parameters:   4 (intercept + 3 betas)")
    print("")
    print("KAN/MLP ratio: " + str(round(kan_params / mlp_params, 2)) + "x")
    print("KAN/GJR ratio: " + str(round(kan_params / 4)) + "x")

    # ----------------------------------------------------------
    #  12. Summary & conclusions
    # ----------------------------------------------------------
    print_section("12. Summary & Conclusions", "=")

    # Find best model
    qlike_scores = {name: res['QLIKE'] for name, res in results.items()}
    best_model = min(qlike_scores, key=qlike_scores.get)

    print("\nBest model (QLIKE): " + best_model + " (" + str(round(qlike_scores[best_model], 6)) + ")")
    print("\nQLIKE ranking:")
    for rank, (name, q) in enumerate(sorted(qlike_scores.items(), key=lambda x: x[1]), 1):
        pct_diff = ((q - qlike_scores[best_model]) / qlike_scores[best_model]) * 100
        print("  " + str(rank) + ". " + name + ": " + str(round(q, 6)) + " (+" + str(round(pct_diff, 1)) + "% vs best)")

    # KAN vs GJR conclusion
    kan_vs_gjr = dm_results.get('KAN_vs_GJR-GARCH', {})
    kan_vs_har = dm_results.get('KAN_vs_HAR-ABS', {})
    kan_vs_mlp = dm_results.get('KAN_vs_MLP', {})

    print("\nKey DM tests (QLIKE):")
    kan_gjr_harvey = "PASS" if kan_vs_gjr.get('significant_Harvey') else "FAIL"
    kan_har_harvey = "PASS" if kan_vs_har.get('significant_Harvey') else "FAIL"
    kan_mlp_harvey = "PASS" if kan_vs_mlp.get('significant_Harvey') else "FAIL"

    print("  KAN vs GJR: t=" + str(kan_vs_gjr.get('t_stat', 'N/A')) + ", Harvey=" + kan_gjr_harvey)
    print("  KAN vs HAR: t=" + str(kan_vs_har.get('t_stat', 'N/A')) + ", Harvey=" + kan_har_harvey)
    print("  KAN vs MLP: t=" + str(kan_vs_mlp.get('t_stat', 'N/A')) + ", Harvey=" + kan_mlp_harvey)

    # Relate to K600 meta-lesson
    print("\n" + "=" * 72)
    print("  K600 meta-lesson check: ML cannot beat GARCH overall")
    print("=" * 72)

    if results['KAN']['QLIKE'] < results['GJR-GARCH']['QLIKE']:
        pct_better = ((results['GJR-GARCH']['QLIKE'] - results['KAN']['QLIKE']) / results['GJR-GARCH']['QLIKE']) * 100
        print("  KAN is " + str(round(pct_better, 1)) + "% better than GJR in QLIKE")
        if kan_vs_gjr.get('significant_Harvey'):
            print("  STATISTICALLY SIGNIFICANT (Harvey PASS)")
            print("  K600 meta-lesson CHALLENGED for KAN specifically")
        else:
            print("  NOT statistically significant (Harvey FAIL)")
            print("  K600 meta-lesson CONFIRMED: KAN raw improvement not robust")
    else:
        print("  KAN is WORSE than GJR. K600 meta-lesson CONFIRMED")

    if results['KAN']['QLIKE'] < results['HAR-ABS']['QLIKE']:
        print("  KAN also beats HAR-ABS — novel finding if significant")
    else:
        print("  KAN loses to HAR-ABS. HAR remains champion (K530)")

    # ----------------------------------------------------------
    #  13. Save results
    # ----------------------------------------------------------
    elapsed = time.time() - start_time

    # Generate conclusion
    conclusion_parts = []

    if results['KAN']['QLIKE'] < results['GJR-GARCH']['QLIKE']:
        pct = ((results['GJR-GARCH']['QLIKE'] - results['KAN']['QLIKE']) / results['GJR-GARCH']['QLIKE']) * 100
        if kan_vs_gjr.get('significant_Harvey'):
            conclusion_parts.append(
                "KAN beats GJR-GARCH by " + str(round(pct, 1)) + "% QLIKE (DM t=" + str(round(kan_vs_gjr['t_stat'], 2)) + ", Harvey PASS). "
                "This challenges K600 meta-lesson for KAN specifically."
            )
        else:
            conclusion_parts.append(
                "KAN raw QLIKE " + str(round(pct, 1)) + "% better than GJR but NOT significant (DM t=" + str(round(kan_vs_gjr['t_stat'], 2)) + ", Harvey FAIL). "
                "K600 meta-lesson confirmed: ML improvement not robust."
            )
    else:
        conclusion_parts.append("KAN WORSE than GJR-GARCH. K600 meta-lesson strongly confirmed.")

    if results['KAN']['QLIKE'] < results['HAR-ABS']['QLIKE']:
        conclusion_parts.append("KAN beats HAR-ABS (K530 champion).")
    else:
        conclusion_parts.append("KAN loses to HAR-ABS. HAR remains champion (K530).")

    if results['KAN']['QLIKE'] < results['MLP']['QLIKE']:
        conclusion_parts.append("KAN beats MLP — B-spline activations add value over fixed ReLU.")
    else:
        conclusion_parts.append("KAN loses to MLP — B-spline activations do NOT help vs ReLU.")

    conclusion_parts.append(
        "Best model: " + best_model + ". "
        "KAN has " + str(kan_params) + " params vs GJR's 4. Complexity not justified by performance."
    )

    conclusion_text = " ".join(conclusion_parts)

    output = {
        "experiment_id": "K618",
        "title": "KAN vs MLP vs GJR-GARCH vs HAR-ABS for Volatility Forecasting",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, ^VIX)",
        "data_period": spy.index[0].strftime('%Y-%m-%d') + " to " + spy.index[-1].strftime('%Y-%m-%d'),
        "oos_period": "2023-01-01 to 2024-12-31",
        "oos_n": int(n_valid),
        "window": window,
        "refit_every_nn": refit_every,
        "refit_every_garch": 22,
        "methodology": "Empirical analysis with rolling window OOS evaluation",
        "references": [
            "Liu et al. (2024): KAN: Kolmogorov-Arnold Networks, arXiv:2404.19756",
            "KAN-GARCH-MIDAS, J. Applied Economics 2025",
            "KAN for VIX, Expert Systems 2025",
            "Corsi (2009, JFE): HAR-RV model",
            "Branco et al. (2024): ML vs GARCH meta-study",
            "K530: HAR-ABS champion",
            "K600: ML meta-lesson",
        ],
        "models": {
            "KAN": {
                "architecture": "1 KAN layer (8->5) + Linear output",
                "hidden_size": 5,
                "n_bases": 8,
                "parameters": kan_params,
                "features": feature_names,
                "training": "Adam, lr=0.001, early stopping patience=20",
            },
            "MLP": {
                "architecture": "Linear(8->32) -> ReLU -> Linear(32->16) -> ReLU -> Linear(16->1) -> Softplus",
                "parameters": mlp_params,
            },
            "GJR-GARCH": {
                "specification": "GJR-GARCH(1,1), Zero mean, Normal dist",
                "parameters": 4,
            },
            "HAR-ABS": {
                "specification": "c + b1*|r_{t-1}| + b5*rv5 + b22*rv22, OLS",
                "parameters": 4,
            },
        },
        "results": {
            name: {
                "QLIKE": round(res['QLIKE'], 6),
                "MSE": round(res['MSE'], 8),
                "MAE": round(res['MAE'], 6),
                "Correlation": round(res['Correlation'], 4),
            }
            for name, res in results.items()
        },
        "sub_period_results": sub_period_results,
        "dm_tests_qlike": dm_results,
        "dm_tests_mse": mse_dm_results,
        "feature_importance_kan": importances,
        "computation_time": {
            "GJR-GARCH": round(gjr_time, 1),
            "HAR-ABS": round(har_time, 1),
            "KAN": round(kan_time, 1),
            "MLP": round(mlp_time, 1),
            "total": round(elapsed, 1),
        },
        "model_complexity": {
            "KAN_params": kan_params,
            "MLP_params": mlp_params,
            "GJR_params": 4,
            "HAR_params": 4,
        },
        "best_model_qlike": best_model,
        "conclusion": conclusion_text,
        "limitations": [
            "Daily proxy |r_t| instead of intraday RV",
            "Single asset (SPY) - no cross-asset validation",
            "OOS 2023-2024 only - single period",
            "Minimal KAN (1 layer, 5 nodes) - not full pykan",
            "B-spline order 1 (piecewise linear) - original KAN uses higher order",
            "No hyperparameter tuning - fixed architecture",
        ],
    }

    # Save
    results_path = project_root / "experiments" / "k618_kan_volatility_results.json"
    with open(results_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("\nResults saved to: " + str(results_path))
    print("Total time: " + str(round(elapsed, 1)) + "s")
    print("\n" + "=" * 72)
    print("  CONCLUSION: " + conclusion_text)
    print("=" * 72)


if __name__ == "__main__":
    main()
