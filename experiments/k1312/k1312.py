"""
K1312: GARCH-to-Neural (AAAI 2024) — GARCH-LSTM Volatility Forecasting
========================================================================
[提出: VolPred Research Program, 執行: K1312 worktree agent]

Research Question:
  Does a GARCH-LSTM model (Zhao, Zhu, Ng, Lee, AAAI 2024; arXiv:2402.06642)
  — which derives GJR-GARCH equivalence and uses it as an LSTM structured prior
  — beat plain GJR-GARCH for OOS daily volatility forecasting on SPY/QQQ?

Motivation:
  ML ceiling confirmed 7 times (K785, K816v2, K784, K1263 etc.) — all NULL.
  GARCH-LSTM differs from prior attempts: instead of feeding GARCH outputs as
  features, it maps the GJR variance update equation directly to LSTM input
  structure, providing a GARCH-consistent inductive bias from initialization.

Lookahead Policy (CRITICAL — highest priority, DO NOT RELAX):
  All features at forecast time t are derived from information available at t-1:
    - r_{t-1}, r^2_{t-1}, neg_r2_{t-1}=r^2*(r<0), gjr_var_{t-1}, rv22_{t-1}, vix_{t-1}
  Implementation: df[feature_cols] = df[feature_cols].shift(1) before walk-forward.
  GJR forecast for t uses only r[:t] and var[:t] (no r_t peeking).
  LSTM window: rows [t-window_size, t-1] -> predict sigma^2_t.

Success Gates (identical to K1263 for comparability):
  (a) DM-HLN |t| > 3.0 AND t < 0 (challenger better)
  (b) QLIKE relative improvement >= 5% vs GJR
  (c) Sub-period stable: both 2021-2023 and 2024+ sub-periods better
  PASS ALL 3 -> ML ceiling breakthrough / Paper-3 candidate
  FAIL ALL -> ML ceiling 8th confirmation NULL

References:
  Zhao, Zhu, Ng, Lee (2024) "From GARCH to Neural Network for Volatility
    Forecast", AAAI 2024, arXiv:2402.06642.
  Patton (2011), J. Econometrics 160:246-256.
  Harvey, Liu, Zhu (2016), RFS 29(1):5-68.
  Diebold & Mariano (1995); Harvey-Leybourne-Newbold (1997).

Data: yfinance (SPY, QQQ, ^VIX)
Reproduction: uv run python experiments/k1312/k1312.py
"""
from __future__ import annotations

import json
import math
import random
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

# ============================================================
# PyTorch -- required; fail loudly if missing
# ============================================================
try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
except ImportError as _e:
    raise ImportError(
        "PyTorch is required for K1312. Install with: pip install torch"
    ) from _e

try:
    import yfinance as yf
except ImportError as _e:
    raise ImportError(
        "yfinance is required for K1312. Install with: pip install yfinance"
    ) from _e

# ============================================================
# Configuration
# ============================================================
ASSETS = ["SPY", "QQQ"]
DATA_START = "2007-01-01"
DATA_END = None  # current date
OOS_START = "2021-01-04"
SUB_PERIOD_SPLIT = "2024-01-01"
REFIT_INTERVAL = 63          # quarterly refit (matches K1263 for fair comparison)
WINDOW = 1500                # rolling training window obs
LSTM_SEQ_LEN = 20            # LSTM input sequence length (trading days)
LSTM_HIDDEN = 32             # hidden units per layer
LSTM_LAYERS = 2              # number of LSTM layers
LSTM_DROPOUT = 0.1           # dropout between LSTM layers
LSTM_EPOCHS = 100            # max training epochs
LSTM_PATIENCE = 10           # early stopping patience
LSTM_LR = 1e-3               # Adam learning rate
LSTM_VAL_FRAC = 0.2          # fraction of training set for validation
SEED = 42

OUTDIR = Path(__file__).parent
OUTDIR.mkdir(parents=True, exist_ok=True)
DATA_CACHE_DIR = OUTDIR / "data"
DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# -- Seed everything -------------------------------------------------
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(SEED)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False

DEVICE = torch.device("cpu")  # CPU for reproducibility
if torch.cuda.is_available():
    DEVICE = torch.device("cuda")


# ============================================================
# Data layer
# ============================================================
def fetch_close(ticker: str, start: str, end: str | None) -> pd.Series:
    safe_name = ticker.replace("^", "").replace("-", "_").replace(".", "_")
    cache = DATA_CACHE_DIR / f"{safe_name}.csv"
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        s = df.iloc[:, 0]
    else:
        dl_kwargs: dict = dict(start=start, progress=False, auto_adjust=False)
        if end:
            dl_kwargs["end"] = end
        df = yf.download(ticker, **dl_kwargs)
        if df.empty:
            raise RuntimeError(f"yfinance returned empty for {ticker}")
        col = "Adj Close" if "Adj Close" in df.columns else "Close"
        s = df[col]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s.name = ticker
        s.to_frame().to_csv(cache)
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s.astype(float).sort_index()


def build_panel() -> dict[str, pd.DataFrame]:
    """Build feature panel.

    NOTE: Feature columns are NOT shifted here. The walk-forward loop
    applies shift(1) explicitly before using them as model inputs.
    """
    vix = fetch_close("^VIX", DATA_START, DATA_END).rename("vix")

    panels = {}
    for asset in ASSETS:
        px = fetch_close(asset, DATA_START, DATA_END)
        ret = (np.log(px) - np.log(px.shift(1))) * 100.0  # percent

        # 22-day rolling realized vol
        rv22 = ret.rolling(22).apply(
            lambda x: np.sqrt(np.mean(x ** 2)), raw=True
        ).rename("rv22")

        df = pd.concat([ret.rename("ret"), vix, rv22], axis=1).dropna()
        panels[asset] = df
    return panels


# ============================================================
# GJR-GARCH (Normal MLE via scipy)
# ============================================================
def _gjr_neg_loglik(params: np.ndarray, r: np.ndarray) -> float:
    omega, alpha, gamma, beta = params
    if (omega <= 1e-10 or alpha < 0 or gamma < 0 or beta < 0
            or alpha + 0.5 * gamma + beta >= 0.999):
        return 1e10
    n = len(r)
    var = np.empty(n)
    var[0] = np.var(r)
    for t in range(1, n):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        var[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * var[t - 1]
        if var[t] <= 1e-10:
            return 1e10
    ll = -0.5 * np.sum(np.log(2 * np.pi * var) + r ** 2 / var)
    return -ll


def fit_gjr_normal(r: np.ndarray) -> dict:
    r = np.asarray(r, dtype=float)
    x0 = np.array([0.05, 0.05, 0.05, 0.85])
    bounds = [(1e-6, None), (0.0, 0.5), (0.0, 0.5), (0.0, 0.999)]
    starts = [
        x0,
        [0.1, 0.1, 0.1, 0.70],
        [0.02, 0.03, 0.07, 0.88],
        [0.08, 0.06, 0.08, 0.80],
    ]
    best = None
    for s in starts:
        try:
            res = minimize(
                _gjr_neg_loglik, s, args=(r,),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 300, "ftol": 1e-9},
            )
            if res.success and (best is None or res.fun < best.fun):
                best = res
        except Exception:
            continue
    if best is None:
        return {
            "omega": float(np.var(r) * 0.05),
            "alpha": 0.05, "gamma": 0.05, "beta": 0.85,
        }
    omega, alpha, gamma, beta = best.x
    return {
        "omega": float(omega), "alpha": float(alpha),
        "gamma": float(gamma), "beta": float(beta),
    }


def gjr_filter(r: np.ndarray, params: dict) -> np.ndarray:
    """Return sigma^2 path for given params (in-sample filter)."""
    omega = params["omega"]
    alpha = params["alpha"]
    gamma = params["gamma"]
    beta  = params["beta"]
    n = len(r)
    var = np.empty(n)
    var[0] = np.var(r)
    for t in range(1, n):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        var[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * var[t - 1]
        var[t] = max(var[t], 1e-10)
    return var


def gjr_one_step_forecast(r: np.ndarray, var: np.ndarray, params: dict) -> float:
    """One-step-ahead forecast at t given r[:t] and var[:t]."""
    omega = params["omega"]
    alpha = params["alpha"]
    gamma = params["gamma"]
    beta  = params["beta"]
    last_r, last_v = r[-1], var[-1]
    ind = 1.0 if last_r < 0 else 0.0
    return float(omega + (alpha + gamma * ind) * last_r ** 2 + beta * last_v)


# ============================================================
# GARCH-LSTM Architecture (Zhao et al. 2024 AAAI)
# ============================================================
class GARCHLSTMModel(nn.Module):
    """GARCH-LSTM implementing the GARCH-NN equivalence from Zhao et al. (2024).

    Key design:
    - Input features include GARCH-structured terms: r^2_{t-1}, neg_r2_{t-1},
      gjr_var_{t-1} -- mapping to omega, alpha, gamma, beta of GJR.
    - Input layer is initialized to match GJR update structure.
    - Output: positive sigma^2 via softplus activation + small floor.
    """

    def __init__(
        self,
        n_features: int,
        hidden_size: int = LSTM_HIDDEN,
        num_layers: int = LSTM_LAYERS,
        dropout: float = LSTM_DROPOUT,
    ):
        super().__init__()
        self.n_features = n_features
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        # Feature projection
        self.input_proj = nn.Linear(n_features, hidden_size, bias=True)

        self.lstm = nn.LSTM(
            input_size=hidden_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0.0,
            batch_first=True,
        )

        # Output head: hidden_size -> 1, softplus for positivity
        self.output_head = nn.Sequential(
            nn.Linear(hidden_size, 1),
            nn.Softplus(beta=10),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (batch, seq_len, n_features) -> (batch, 1)"""
        h = self.input_proj(x)          # (batch, seq_len, hidden)
        out, _ = self.lstm(h)           # (batch, seq_len, hidden)
        last_h = out[:, -1, :]         # (batch, hidden)
        sigma2 = self.output_head(last_h)  # (batch, 1)
        return sigma2 + 1e-8           # floor


def _garch_init_lstm(model: GARCHLSTMModel, gjr_params: dict) -> None:
    """Initialize input layer weights to reflect GJR structure.

    GARCH-NN equivalence (Zhao et al. 2024):
      GJR update: h_t = omega + (alpha+gamma*I)*eps^2 + beta*h_{t-1}
      Maps to RNN input: [r^2, neg_r2, gjr_var, rv22, vix, ret]
      Weights: [alpha, gamma, beta, small, small, small] / hidden_size
    """
    omega = gjr_params["omega"]
    alpha = gjr_params["alpha"]
    gamma = gjr_params["gamma"]
    beta  = gjr_params["beta"]
    hs = model.hidden_size

    with torch.no_grad():
        # input_proj weight: (hidden_size, n_features)
        # Feature order: [ret, r2, neg_r2, gjr_var, rv22, vix] (idx 0-5)
        W = model.input_proj.weight.data
        W[:, 1] = alpha / hs   # r^2 -> alpha
        W[:, 2] = gamma / hs   # neg_r2 -> gamma
        W[:, 3] = beta  / hs   # gjr_var -> beta
        model.input_proj.bias.data.fill_(omega / hs)


def build_sequences(
    feats: np.ndarray,      # (T, n_features) -- already shifted (t-1 info)
    targets: np.ndarray,    # (T,) -- r^2 proxies at time t
    seq_len: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build (X, y):
      X[i] = feats[i:i+seq_len]  (window of t-seq_len..t-1 info)
      y[i] = targets[i+seq_len]  (sigma^2 proxy at t)
    """
    T = len(feats)
    n = T - seq_len
    if n <= 0:
        return np.empty((0, seq_len, feats.shape[1])), np.empty(0)
    X = np.stack([feats[i:i + seq_len] for i in range(n)], axis=0)  # (n, seq_len, F)
    y = targets[seq_len:]                                            # (n,)
    return X, y


def fit_garch_lstm(
    feats_train: np.ndarray,
    targets_train: np.ndarray,
    gjr_params: dict,
    seq_len: int = LSTM_SEQ_LEN,
    hidden_size: int = LSTM_HIDDEN,
    num_layers: int = LSTM_LAYERS,
    dropout: float = LSTM_DROPOUT,
    epochs: int = LSTM_EPOCHS,
    patience: int = LSTM_PATIENCE,
    lr: float = LSTM_LR,
    val_frac: float = LSTM_VAL_FRAC,
    seed: int = SEED,
) -> tuple:
    """Fit a GARCH-LSTM model on training features/targets.

    Returns: (model_in_inference_mode, feat_mean, feat_std, y_mean, y_std)
    """
    torch.manual_seed(seed)
    np.random.seed(seed)

    n_features = feats_train.shape[1]
    X, y = build_sequences(feats_train, targets_train, seq_len)

    # Normalize features
    feat_mean = feats_train.mean(axis=0)
    feat_std = feats_train.std(axis=0) + 1e-8
    y_log = np.log(np.maximum(targets_train, 1e-8))
    y_mean = float(y_log.mean())
    y_std = float(y_log.std() + 1e-8)

    model = GARCHLSTMModel(n_features, hidden_size, num_layers, dropout).to(DEVICE)
    _garch_init_lstm(model, gjr_params)

    if len(X) < 50:
        # Not enough data to train; return GARCH-initialized model only
        model.train(False)  # set to inference mode
        return model, feat_mean, feat_std, y_mean, y_std

    X_norm = (X - feat_mean) / feat_std

    y_log_seq = np.log(np.maximum(y, 1e-8))
    y_norm = (y_log_seq - y_mean) / y_std

    # Chronological train/val split
    n_val = max(1, int(len(X_norm) * val_frac))
    n_tr = len(X_norm) - n_val

    X_tr = torch.tensor(X_norm[:n_tr], dtype=torch.float32).to(DEVICE)
    y_tr = torch.tensor(y_norm[:n_tr], dtype=torch.float32).unsqueeze(1).to(DEVICE)
    X_val = torch.tensor(X_norm[n_tr:], dtype=torch.float32).to(DEVICE)
    y_val = torch.tensor(y_norm[n_tr:], dtype=torch.float32).unsqueeze(1).to(DEVICE)

    loader_tr = DataLoader(TensorDataset(X_tr, y_tr), batch_size=64, shuffle=False)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    criterion = nn.MSELoss()

    best_val_loss = float("inf")
    best_state: dict | None = None
    wait = 0

    for _epoch in range(epochs):
        model.train(True)
        for xb, yb in loader_tr:
            optimizer.zero_grad()
            pred = model(xb)
            pred_log_norm = torch.log(pred.clamp(min=1e-8))
            loss = criterion(pred_log_norm, yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        model.train(False)
        with torch.no_grad():
            val_pred = model(X_val)
            val_pred_log_norm = torch.log(val_pred.clamp(min=1e-8))
            val_loss = criterion(val_pred_log_norm, y_val).item()

        if val_loss < best_val_loss - 1e-6:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    model.train(False)  # inference mode
    return model, feat_mean, feat_std, y_mean, y_std


def predict_garch_lstm(
    model: GARCHLSTMModel,
    feats_window: np.ndarray,   # (seq_len, n_features) -- already shifted
    feat_mean: np.ndarray,
    feat_std: np.ndarray,
    y_mean: float,
    y_std: float,
) -> float:
    """Predict sigma^2 for next period given last seq_len rows of features."""
    x_norm = (feats_window - feat_mean) / feat_std
    x_t = torch.tensor(x_norm, dtype=torch.float32).unsqueeze(0).to(DEVICE)
    with torch.no_grad():
        sigma2_raw = model(x_t).item()
    # Model output is in normalized log space; denormalize
    log_sigma2_norm = math.log(max(sigma2_raw, 1e-10))
    log_sigma2 = log_sigma2_norm * y_std + y_mean
    return float(math.exp(np.clip(log_sigma2, -20, 20)))


# ============================================================
# Evaluation metrics
# ============================================================
def qlike(proxy_r2: np.ndarray, sigma2_hat: np.ndarray) -> float:
    proxy_r2 = np.maximum(proxy_r2, 1e-10)
    sigma2_hat = np.maximum(sigma2_hat, 1e-10)
    return float(np.mean(proxy_r2 / sigma2_hat - np.log(proxy_r2 / sigma2_hat) - 1.0))


def qlike_loss_series(proxy_r2: np.ndarray, sigma2_hat: np.ndarray) -> np.ndarray:
    proxy_r2 = np.maximum(proxy_r2, 1e-10)
    sigma2_hat = np.maximum(sigma2_hat, 1e-10)
    return proxy_r2 / sigma2_hat - np.log(proxy_r2 / sigma2_hat) - 1.0


def mse_loss(proxy_r2: np.ndarray, sigma2_hat: np.ndarray) -> float:
    return float(np.mean((proxy_r2 - sigma2_hat) ** 2))


def dm_hln(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple[float, float]:
    """DM-HLN test. H0: equal predictive accuracy.
    loss1 = challenger, loss2 = baseline.
    Returns (t_stat, p_value). Negative t_stat => challenger (loss1) better."""
    d = loss1 - loss2
    n = len(d)
    if n < 10:
        return float("nan"), float("nan")
    mean_d = np.mean(d)
    gamma0 = np.var(d, ddof=0)
    var_d = gamma0
    for k in range(1, h):
        gk = np.cov(d[k:], d[:-k], ddof=0)[0, 1]
        var_d += 2.0 * (1.0 - k / h) * gk
    if var_d <= 0:
        return float("nan"), float("nan")
    dm_stat = mean_d / np.sqrt(var_d / n)
    correction = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_stat = dm_stat * correction
    p_val = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ============================================================
# Feature construction
# ============================================================
FEATURE_COLS = ["ret", "r2", "neg_r2", "gjr_var", "rv22", "vix"]


def build_features(df_raw: pd.DataFrame, gjr_var_path: np.ndarray) -> pd.DataFrame:
    """Construct 6-feature matrix (RAW values, not yet shifted).

    Features:
      ret     : log return %
      r2      : ret^2 (GARCH alpha input analog)
      neg_r2  : ret^2 * I(ret<0) (GJR gamma input analog)
      gjr_var : GJR filtered variance (GARCH memory)
      rv22    : 22d rolling realized vol
      vix     : VIX level
    """
    ret = df_raw["ret"].values
    r2 = ret ** 2
    neg_r2 = r2 * (ret < 0).astype(float)
    rv22 = df_raw["rv22"].values
    vix = df_raw["vix"].values

    return pd.DataFrame({
        "ret": ret,
        "r2": r2,
        "neg_r2": neg_r2,
        "gjr_var": gjr_var_path,
        "rv22": rv22,
        "vix": vix,
    }, index=df_raw.index)


# ============================================================
# Walk-forward engine
# ============================================================
def run_asset(asset: str, df: pd.DataFrame) -> dict:
    print(f"\n=== {asset} ===  n_obs={len(df)}")

    r_full = df["ret"].values
    n_full = len(r_full)

    oos_mask = df.index >= pd.Timestamp(OOS_START)
    oos_idx_array = np.where(oos_mask)[0]

    if len(oos_idx_array) == 0:
        print(f"  WARNING: no OOS data for {asset}")
        return {}

    refit_set = set(oos_idx_array[::REFIT_INTERVAL].tolist())
    refit_set.add(int(oos_idx_array[0]))

    print(
        f"  OOS rows: {len(oos_idx_array)}"
        f"  ({df.index[oos_idx_array[0]].date()} -> {df.index[oos_idx_array[-1]].date()})"
    )
    print(f"  Refit points: {len(refit_set)}")

    # ── Pass 1: build full GJR variance path (expanding window) ──
    gjr_var_full = np.full(n_full, np.nan)
    is_end = int(oos_idx_array[0])
    init_gjr = fit_gjr_normal(r_full[:is_end])
    init_var = gjr_filter(r_full[:is_end], init_gjr)
    gjr_var_full[:is_end] = init_var

    current_gjr_params = init_gjr
    current_var_path = init_var

    for i, idx in enumerate(oos_idx_array):
        if int(idx) in refit_set:
            current_gjr_params = fit_gjr_normal(r_full[:idx])
            current_var_path = gjr_filter(r_full[:idx], current_gjr_params)
            if i == 0 or (i + 1) % 200 == 0:
                print(
                    f"  [GJR refit @ {df.index[idx].date()}]"
                    f"  omega={current_gjr_params['omega']:.5f}"
                    f"  alpha={current_gjr_params['alpha']:.4f}"
                    f"  gamma={current_gjr_params['gamma']:.4f}"
                    f"  beta={current_gjr_params['beta']:.4f}"
                )
        gjr_var_full[idx] = gjr_one_step_forecast(
            r_full[:idx], current_var_path, current_gjr_params
        )

    # ── Build feature matrix (raw, then shift in walk-forward) ──
    feats_raw = build_features(df, gjr_var_full)

    # CRITICAL LOOKAHEAD PROTECTION:
    # Shift all features by 1 day so that at time t we only use t-1 info.
    feats_shifted = feats_raw.copy()
    feats_shifted[FEATURE_COLS] = feats_raw[FEATURE_COLS].shift(1)
    feats_shifted = feats_shifted.dropna()

    # Align dataframes to shifted index
    df_aligned = df.loc[feats_shifted.index].copy()
    feats_arr = feats_shifted[FEATURE_COLS].values
    proxy_arr = df_aligned["ret"].values ** 2

    oos_mask_aligned = df_aligned.index >= pd.Timestamp(OOS_START)
    oos_idx_aligned = np.where(oos_mask_aligned)[0].tolist()

    # GJR forecasts on aligned index (re-map from original gjr_var_full)
    orig_to_aligned = {d: i for i, d in enumerate(df_aligned.index)}
    gjr_aligned = np.array([
        gjr_var_full[j]
        for j in [np.where(df.index == d)[0][0] for d in df_aligned.index]
    ])

    # ── Pass 2: GARCH-LSTM walk-forward ──
    print(f"  Starting GARCH-LSTM walk-forward ({len(oos_idx_aligned)} OOS steps)...")
    t0 = time.time()

    sig2_lstm = np.full(len(df_aligned), np.nan)

    lstm_refit_set = set(oos_idx_aligned[::REFIT_INTERVAL])
    lstm_refit_set.add(oos_idx_aligned[0])

    lstm_model = None
    feat_mean = feat_std = None
    y_mean_val: float = 0.0
    y_std_val: float = 1.0

    for i, idx in enumerate(oos_idx_aligned):
        # Refit LSTM at refit points
        if int(idx) in lstm_refit_set:
            lo = max(0, idx - WINDOW)
            feats_tr = feats_arr[lo:idx]
            targets_tr = proxy_arr[lo:idx]

            gjr_params_init = fit_gjr_normal(df_aligned["ret"].values[:idx])

            result_tuple = fit_garch_lstm(
                feats_tr, targets_tr, gjr_params_init,
                seq_len=LSTM_SEQ_LEN,
                hidden_size=LSTM_HIDDEN,
                num_layers=LSTM_LAYERS,
                dropout=LSTM_DROPOUT,
                epochs=LSTM_EPOCHS,
                patience=LSTM_PATIENCE,
                lr=LSTM_LR,
                val_frac=LSTM_VAL_FRAC,
                seed=SEED,
            )
            lstm_model, feat_mean, feat_std, y_mean_val, y_std_val = result_tuple

            if i == 0 or (i + 1) % 100 == 0:
                print(
                    f"  [LSTM refit @ {df_aligned.index[idx].date()}]"
                    f"  elapsed={time.time()-t0:.1f}s"
                )

        # LSTM one-step forecast at time idx
        if lstm_model is not None and idx >= LSTM_SEQ_LEN and feat_mean is not None:
            window_feats = feats_arr[idx - LSTM_SEQ_LEN:idx]
            if len(window_feats) == LSTM_SEQ_LEN:
                try:
                    sig2_lstm[idx] = predict_garch_lstm(
                        lstm_model, window_feats,
                        feat_mean, feat_std, y_mean_val, y_std_val,
                    )
                except Exception as exc:
                    print(f"  LSTM predict error at idx={idx}: {exc}")

        if (i + 1) % 250 == 0:
            print(f"    OOS progress: {i+1}/{len(oos_idx_aligned)}  elapsed={time.time()-t0:.1f}s")

    print(f"  Walk-forward done. Elapsed: {time.time()-t0:.1f}s")

    # ── Evaluate ──
    oos_proxy = proxy_arr[oos_mask_aligned]
    oos_gjr = gjr_aligned[oos_mask_aligned]
    oos_lstm_fc = sig2_lstm[oos_mask_aligned]
    oos_dates = df_aligned.index[oos_mask_aligned]

    valid = ~(np.isnan(oos_gjr) | np.isnan(oos_lstm_fc) | np.isnan(oos_proxy))
    n_dropped = int((~valid).sum())
    if n_dropped > 0:
        print(f"  Dropping {n_dropped} NaN rows from OOS")
    oos_proxy = oos_proxy[valid]
    oos_gjr   = np.maximum(oos_gjr[valid], 1e-10)
    oos_lstm_fc = np.maximum(oos_lstm_fc[valid], 1e-10)
    oos_dates = oos_dates[valid]

    qlike_gjr  = qlike(oos_proxy, oos_gjr)
    qlike_lstm = qlike(oos_proxy, oos_lstm_fc)
    mse_gjr    = mse_loss(oos_proxy, oos_gjr)
    mse_lstm   = mse_loss(oos_proxy, oos_lstm_fc)

    rel_qlike = (qlike_gjr - qlike_lstm) / qlike_gjr if qlike_gjr > 0 else float("nan")
    rel_mse   = (mse_gjr  - mse_lstm)  / mse_gjr   if mse_gjr  > 0 else float("nan")

    loss_gjr_q  = qlike_loss_series(oos_proxy, oos_gjr)
    loss_lstm_q = qlike_loss_series(oos_proxy, oos_lstm_fc)
    t_q, p_q    = dm_hln(loss_lstm_q, loss_gjr_q, h=1)

    loss_gjr_m  = (oos_proxy - oos_gjr)    ** 2
    loss_lstm_m = (oos_proxy - oos_lstm_fc) ** 2
    t_m, p_m    = dm_hln(loss_lstm_m, loss_gjr_m, h=1)

    # Sub-period
    sub_split = pd.Timestamp(SUB_PERIOD_SPLIT)
    sub_period: dict = {}
    for label, mask in [
        ("early_2021_2023", oos_dates < sub_split),
        ("late_2024_2026",  oos_dates >= sub_split),
    ]:
        if mask.sum() < 20:
            sub_period[label] = {"n": int(mask.sum()), "qlike_gjr": None, "qlike_lstm": None}
            continue
        qg = qlike(oos_proxy[mask], oos_gjr[mask])
        ql = qlike(oos_proxy[mask], oos_lstm_fc[mask])
        sub_period[label] = {
            "n": int(mask.sum()),
            "qlike_gjr":  float(qg),
            "qlike_lstm": float(ql),
            "lstm_better": bool(ql < qg),
            "rel_improvement": float((qg - ql) / qg) if qg > 0 else None,
        }

    # Three-gate evaluation
    gate_dm  = bool(not math.isnan(t_q) and abs(t_q) > 3.0 and t_q < 0)
    gate_rel = bool(not math.isnan(rel_qlike) and rel_qlike >= 0.05)
    gate_sub = bool(
        sub_period.get("early_2021_2023", {}).get("lstm_better", False)
        and sub_period.get("late_2024_2026", {}).get("lstm_better", False)
    )
    gates_passed = sum([gate_dm, gate_rel, gate_sub])

    if gates_passed == 3:
        verdict = "POSITIVE -- ML ceiling breakthrough candidate"
    elif gates_passed >= 2:
        verdict = "PARTIAL -- investigate sub-period effects"
    else:
        verdict = "NULL -- ML ceiling 8th confirmation"

    print(f"\n  QLIKE  GJR={qlike_gjr:.6f}  LSTM={qlike_lstm:.6f}  rel={rel_qlike:+.2%}")
    print(f"  DM-HLN (QLIKE): t={t_q:.3f}  p={p_q:.4f}")
    print(f"  Gates: DM={gate_dm}  RelImpr={gate_rel}  SubPeriod={gate_sub}  -> {verdict}")

    return {
        "asset": asset,
        "n_oos": int(len(oos_proxy)),
        "oos_start": str(oos_dates.min().date()),
        "oos_end":   str(oos_dates.max().date()),
        "qlike": {
            "gjr_baseline": float(qlike_gjr),
            "garch_lstm":   float(qlike_lstm),
        },
        "mse": {
            "gjr_baseline": float(mse_gjr),
            "garch_lstm":   float(mse_lstm),
        },
        "relative_improvement_qlike": float(rel_qlike),
        "relative_improvement_mse":   float(rel_mse),
        "dm_test_qlike": {
            "t_stat":    float(t_q),
            "p_value":   float(p_q),
            "interpretation": "negative t_stat => GARCH-LSTM better (QLIKE)",
            "harvey_significant_3sd": bool(not math.isnan(t_q) and abs(t_q) > 3.0),
        },
        "dm_test_mse": {
            "t_stat":    float(t_m),
            "p_value":   float(p_m),
            "interpretation": "negative t_stat => GARCH-LSTM better (MSE)",
            "harvey_significant_3sd": bool(not math.isnan(t_m) and abs(t_m) > 3.0),
        },
        "sub_period": sub_period,
        "gates": {
            "dm_t_gt_3_and_negative":     gate_dm,
            "rel_improvement_qlike_5pct": gate_rel,
            "sub_period_stable":          gate_sub,
            "passed_count":               gates_passed,
        },
        "verdict": verdict,
        "_arrays": {
            "dates":      [d.strftime("%Y-%m-%d") for d in oos_dates],
            "proxy_r2":   oos_proxy.tolist(),
            "sig2_gjr":   oos_gjr.tolist(),
            "sig2_lstm":  oos_lstm_fc.tolist(),
        },
    }


# ============================================================
# Plotting
# ============================================================
def make_plots(results_per_asset: dict[str, dict]) -> list[str]:
    plot_files: list[str] = []
    n_assets = len(results_per_asset)
    if n_assets == 0:
        return plot_files

    fig, axes = plt.subplots(n_assets, 2, figsize=(14, 5 * n_assets))
    if n_assets == 1:
        axes = axes.reshape(1, 2)

    for row, (asset, res) in enumerate(results_per_asset.items()):
        arr = res.get("_arrays", {})
        if not arr:
            continue
        dates = pd.to_datetime(arr["dates"])
        proxy = np.array(arr["proxy_r2"])
        sig2_gjr  = np.array(arr["sig2_gjr"])
        sig2_lstm = np.array(arr["sig2_lstm"])

        # Panel 1: forecast volatility comparison
        ax = axes[row, 0]
        ax.plot(dates, np.sqrt(sig2_gjr)  * 100, label="GJR-GARCH",  alpha=0.7, lw=0.8)
        ax.plot(dates, np.sqrt(sig2_lstm) * 100, label="GARCH-LSTM", alpha=0.7, lw=0.8)
        ax.set_title(f"{asset}: OOS Forecast Vol (%)", fontsize=10)
        ax.legend(fontsize=8)
        ax.tick_params(axis="x", labelsize=7)

        # Panel 2: QLIKE loss differential
        ax2 = axes[row, 1]
        loss_gjr  = qlike_loss_series(proxy, sig2_gjr)
        loss_lstm = qlike_loss_series(proxy, sig2_lstm)
        diff = loss_gjr - loss_lstm    # positive => LSTM better
        ax2.fill_between(dates, diff, 0, where=diff >= 0,
                         alpha=0.5, color="green", label="LSTM better")
        ax2.fill_between(dates, diff, 0, where=diff < 0,
                         alpha=0.5, color="red",   label="GJR better")
        ax2.axhline(0, color="black", lw=0.8)
        dm_t = res.get("dm_test_qlike", {}).get("t_stat", float("nan"))
        ax2.set_title(
            f"{asset}: QLIKE diff (GJR-LSTM)  DM t={dm_t:.2f}", fontsize=10
        )
        ax2.legend(fontsize=8)
        ax2.tick_params(axis="x", labelsize=7)

    plt.tight_layout()
    fig_path = str(OUTDIR / "k1312_qlike_comparison.png")
    plt.savefig(fig_path, dpi=120)
    plt.close()
    plot_files.append(fig_path)
    print(f"  Saved: {fig_path}")
    return plot_files


# ============================================================
# Main
# ============================================================
def main() -> dict:
    print("=" * 60)
    print("K1312: GARCH-to-Neural (AAAI 2024) -- GARCH-LSTM")
    print("=" * 60)
    print(f"  Config: OOS={OOS_START}  REFIT={REFIT_INTERVAL}  WINDOW={WINDOW}")
    print(f"  LSTM: hidden={LSTM_HIDDEN}  layers={LSTM_LAYERS}  seq_len={LSTM_SEQ_LEN}")
    print(f"  seed={SEED}  device={DEVICE}")

    t_start = time.time()
    panels = build_panel()

    results_per_asset: dict[str, dict] = {}
    for asset in ASSETS:
        df = panels[asset]
        res = run_asset(asset, df)
        if res:
            results_per_asset[asset] = res

    all_verdicts = [r["verdict"] for r in results_per_asset.values()]
    if any("POSITIVE" in v for v in all_verdicts):
        overall = "POSITIVE -- GARCH-LSTM breakthrough in at least one asset"
    elif any("PARTIAL" in v for v in all_verdicts):
        overall = "PARTIAL -- mixed results, investigate further"
    else:
        overall = "NULL -- ML ceiling 8th confirmation (GARCH-LSTM fails all gates)"

    plot_files = make_plots(results_per_asset)

    output = {
        "experiment_id": "K1312",
        "title": "GARCH-to-Neural (AAAI 2024): GARCH-LSTM Volatility Forecasting",
        "reference": "Zhao, Zhu, Ng, Lee (2024) arXiv:2402.06642, AAAI 2024",
        "date_computed": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_seconds": round(time.time() - t_start, 1),
        "config": {
            "assets":            ASSETS,
            "oos_start":         OOS_START,
            "sub_period_split":  SUB_PERIOD_SPLIT,
            "refit_interval":    REFIT_INTERVAL,
            "window":            WINDOW,
            "lstm_seq_len":      LSTM_SEQ_LEN,
            "lstm_hidden":       LSTM_HIDDEN,
            "lstm_layers":       LSTM_LAYERS,
            "lstm_dropout":      LSTM_DROPOUT,
            "lstm_epochs":       LSTM_EPOCHS,
            "lstm_patience":     LSTM_PATIENCE,
            "lstm_lr":           LSTM_LR,
            "seed":              SEED,
            "device":            str(DEVICE),
            "lookahead_protection": (
                "All features shifted by 1 day before walk-forward. "
                "GJR forecast at t uses only r[:t] and var[:t]. "
                "LSTM window: feats[t-seq_len:t] (shifted, so max info=t-1)."
            ),
            "features":        FEATURE_COLS,
            "garch_nn_init": (
                "Input layer initialized with GJR alpha/gamma/beta priors "
                "per Zhao et al. (2024) GARCH-NN equivalence."
            ),
        },
        "per_asset": {
            k: {kk: vv for kk, vv in v.items() if kk != "_arrays"}
            for k, v in results_per_asset.items()
        },
        "overall_verdict": overall,
        "three_gate_framework": {
            "gate_a": "DM-HLN |t|>3.0 AND t<0 (challenger better)",
            "gate_b": "QLIKE relative improvement >= 5% vs GJR",
            "gate_c": "Sub-period stable (both 2021-23 and 2024+ better)",
            "reference": "Harvey, Liu, Zhu (2016) RFS; Diebold & Mariano (1995)",
        },
        "plot_files":  plot_files,
        "ml_ceiling_context": (
            "7 prior NULL results: K785 MF2-GARCH, K816v2 GINN, K784 GARCH-GRU, "
            "K1263 KAN-GARCH-MIDAS, and others. All DM-HLN |t|<3 vs GJR-GARCH."
        ),
    }

    out_path = OUTDIR / "k1312_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, allow_nan=False)
    print(f"\nResults saved: {out_path}")
    print(f"\nOVERALL VERDICT: {overall}")
    print(f"Total elapsed: {time.time()-t_start:.1f}s")
    return output


if __name__ == "__main__":
    main()
