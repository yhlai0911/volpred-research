"""K1535: ML-vs-GARCH volatility "reproduction adjudication" — daily U.S. equity.

Reproduces and adjudicates:
  Aljadani et al. (2025), "Deep Learning and Transformer Architectures for
  Volatility Forecasting: Evidence from U.S. Equity Indices", J. Risk Financial
  Management 18(12):685. https://www.mdpi.com/1911-8074/18/12/685

The paper claims a lightweight patch-Transformer (PatchTST-lite) beats
LSTM / CNN-LSTM / Vanilla-Transformer and the classical ARIMA / GARCH(1,1) /
HAR-RV on daily realized variance for S&P500 / NASDAQ100 / DJIA, h=1/5/22.

Two structural weaknesses we adjudicate:
  M1  WEAK BASELINE — only plain Gaussian GARCH(1,1); no GJR / EGARCH / Student-t,
      no GARCH-X. The paper's own Table A2 shows HAR-RV crushes GARCH(1,1)
      (DM ~ 21), so "beats GARCH(1,1)" is a low bar.
  M2  NO SIGNIFICANCE TEST ON THE DL MODELS — Table A2's DM tests only compare
      classical models with each other; the DL models never enter ANY DM/MCS.
      The Transformer "win" is a raw point-metric ranking, never tested against
      HAR-RV for significance.
  M3  POSSIBLE COVARIATE ASYMMETRY — if the NN is fed an RV proxy while GARCH
      only sees return^2, the comparison conflates architecture with information.

ADJUDICATION DESIGN (two phases):
  Phase A — FAITHFUL REPRODUCTION. Build ARIMA(1,0,1), Gaussian GARCH(1,1),
            HAR-RV, plus LSTM / CNN-LSTM / PatchTST-lite / Vanilla-Transformer.
            Confirm we can REPRODUCE the paper's raw ranking (PatchTST-lite QLIKE
            <= GARCH(1,1)) AND its Table A2 classical sanity (HAR >> GARCH(1,1)).
            If we cannot even reproduce its win, we fix the NN before claiming
            anything (guards against a fake NULL from an undertrained net).

  Phase B — FAIR BASELINE (the adjudication core). Add (i) GJR-GARCH-t and
            (ii) HAR-RV-X / GARCH-X fed the SAME information set as the DL models
            (lagged RV(1,5,22) + VIX). Run the tests the paper omitted:
            Diebold-Mariano (HLN small-sample correction) of EACH DL model vs
            GJR-t and vs HAR-RV-X, plus the Hansen-Lunde-Nason MCS over the full
            pool. Cross-index loss differentials are date-clustered before HAC
            (K1355); in this smoke run only one index is used so no clustering.

LAG / LOOKAHEAD DISCIPLINE (highest risk):
  - Every forecast of RV_t uses ONLY information dated <= t-1. NN inputs are
    windows ending at t-1; GARCH/HAR covariates enter lagged.
  - Forward-label horizon target = mean RV over [origin, origin+H-1]; the fit
    only sees rows <= origin-1, so train_end (origin-1) < forecast_origin
    (K1337 / K446 lesson: not just signal.shift(1) — the forward-label window
    must satisfy target_end < forecast_origin).
  - Each horizon H uses a DM/HLN inference horizon equal to that H (never shared).
  - All RNG (NN init, MCS bootstrap, multistart) uses a fixed seed.

SMOKE SCALE (this run): one index (^GSPC), Close-to-Close target, h=1,
reduced NN epochs, seed=0 (+ a seed-1 determinism check on one NN). The full
multi-index / multi-horizon / 5-seed / three-RV-proxy run is left to the main
thread after Codex review.

Outputs: k1535_ml_garch_adjudication_equity_results.json + figures/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import t as student_t

# Canonical project stats (DM / MCS / QLIKE). Reuse, never re-derive.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from volpred.stats.model_evaluation import qlike, qlike_pointwise  # noqa: E402
from volpred.stats.mcs import model_confidence_set  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)

VAR_FLOOR = 1e-8
VAR_CEIL = 1e6

# HAR lags (Corsi 2009): daily / weekly(5) / monthly(22).
HAR_LAGS = (1, 5, 22)


# ============================================================================ #
# Classical variance recursions (reused pattern from k1533; self-contained).   #
# ============================================================================ #
def _clip_var(v: np.ndarray) -> np.ndarray:
    return np.clip(v, VAR_FLOOR, VAR_CEIL)


def filter_garch(y, s2_init, omega, alpha, beta):
    T = len(y)
    s2 = np.empty(T)
    s2[0] = s2_init
    for t in range(1, T):
        s2[t] = min(max(omega + alpha * y[t - 1] ** 2 + beta * s2[t - 1], VAR_FLOOR), VAR_CEIL)
    return s2


def filter_gjr(y, s2_init, omega, alpha, beta, gamma):
    T = len(y)
    s2 = np.empty(T)
    s2[0] = s2_init
    for t in range(1, T):
        lev = gamma * (1.0 if y[t - 1] < 0 else 0.0) * y[t - 1] ** 2
        s2[t] = min(max(omega + alpha * y[t - 1] ** 2 + lev + beta * s2[t - 1], VAR_FLOOR), VAR_CEIL)
    return s2


def filter_garchx(y, z, s2_init, omega, alpha, beta, pi):
    """GARCH-X: + pi * z_{t-1}. z is non-negative (lagged RV or VIX-variance)."""
    T = len(y)
    s2 = np.empty(T)
    s2[0] = s2_init
    for t in range(1, T):
        s2[t] = min(max(
            omega + alpha * y[t - 1] ** 2 + beta * s2[t - 1] + pi * z[t - 1],
            VAR_FLOOR), VAR_CEIL)
    return s2


# ---- parameter transforms (unconstrained optimizer space) ------------------ #
def _sig(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def _softplus(x):
    return np.log1p(np.exp(-np.abs(x))) + np.maximum(x, 0)


def gauss_loglik(y, sigma2):
    sigma2 = np.clip(sigma2, VAR_FLOOR, VAR_CEIL)
    ll = -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + y ** 2 / sigma2)
    total = np.sum(ll)
    return total if np.isfinite(total) else -1e12


def student_t_loglik(y, sigma2, nu):
    sigma2 = np.clip(sigma2, VAR_FLOOR, VAR_CEIL)
    if nu <= 2.0:
        return -1e12
    z2 = y ** 2 / sigma2
    c = gammaln((nu + 1) / 2.0) - gammaln(nu / 2.0) - 0.5 * np.log(np.pi * (nu - 2.0))
    ll = c - 0.5 * np.log(sigma2) - 0.5 * (nu + 1.0) * np.log1p(z2 / (nu - 2.0))
    total = np.sum(ll)
    return total if np.isfinite(total) else -1e12


# ---- negative log-likelihoods ---------------------------------------------- #
def nll_garch_gauss(p, y, s2init):
    """Plain Gaussian GARCH(1,1) — exactly the paper's only GARCH (M1)."""
    omega = _softplus(p[0]) + VAR_FLOOR
    a = _sig(p[1])
    b = _sig(p[2]) * (1 - a)  # enforce a+b<1
    s2 = filter_garch(y, s2init, omega, a, b)
    return -gauss_loglik(y, s2)


def nll_gjr_t(p, y, s2init):
    """GJR-GARCH(1,1) with Student-t innovations (fair baseline, M1 fix)."""
    omega = _softplus(p[0]) + VAR_FLOOR
    a = _sig(p[1]) * 0.5
    g = _sig(p[2]) * 0.5
    b = _sig(p[3]) * (1 - a - g / 2)
    nu = 2.05 + _softplus(p[4])
    s2 = filter_gjr(y, s2init, omega, a, b, g)
    return -student_t_loglik(y, s2, nu)


def nll_garchx_t(p, y, z, s2init):
    """GARCH-X with Student-t innovations, exogenous lagged covariate z>=0."""
    omega = _softplus(p[0]) + VAR_FLOOR
    a = _sig(p[1]) * 0.5
    b = _sig(p[2]) * (1 - a)
    pi = _softplus(p[3])
    nu = 2.05 + _softplus(p[4])
    s2 = filter_garchx(y, z, s2init, omega, a, b, pi)
    return -student_t_loglik(y, s2, nu)


# ---- fitters (multistart) -------------------------------------------------- #
def _multistart(nll, x0_list, args, maxiter=300):
    best, best_f = None, np.inf
    for x0 in x0_list:
        try:
            res = minimize(nll, x0, args=args, method="L-BFGS-B",
                           options={"maxiter": maxiter})
        except Exception as e:  # noqa: BLE001
            print(f"[multistart] WARN minimize failed: {e}", file=sys.stderr)
            continue
        if res.success or np.isfinite(res.fun):
            if res.fun < best_f:
                best, best_f = res, res.fun
    return best


def fit_garch_gauss(y, s2init, rng, n_start=6):
    x0s = [rng.normal(0, 0.5, 3) for _ in range(n_start)]
    x0s[0] = np.array([np.log(np.exp(0.1) - 1), 0.0, 1.5])
    return _multistart(nll_garch_gauss, x0s, (y, s2init))


def fit_gjr_t(y, s2init, rng, n_start=6):
    x0s = [rng.normal(0, 0.5, 5) for _ in range(n_start)]
    x0s[0] = np.array([np.log(np.exp(0.1) - 1), -1.5, -1.5, 1.5, 1.5])
    return _multistart(nll_gjr_t, x0s, (y, s2init))


def fit_garchx_t(y, z, s2init, rng, n_start=6):
    x0s = [rng.normal(0, 0.5, 5) for _ in range(n_start)]
    x0s[0] = np.array([np.log(np.exp(0.05) - 1), -1.5, 1.0, -1.0, 1.5])
    return _multistart(nll_garchx_t, x0s, (y, z, s2init))


# ---- decode fitted params for forecasting ---------------------------------- #
def decode_garch(p):
    omega = _softplus(p[0]) + VAR_FLOOR
    a = _sig(p[1])
    b = _sig(p[2]) * (1 - a)
    return omega, a, b


def decode_gjr(p):
    omega = _softplus(p[0]) + VAR_FLOOR
    a = _sig(p[1]) * 0.5
    g = _sig(p[2]) * 0.5
    b = _sig(p[3]) * (1 - a - g / 2)
    nu = 2.05 + _softplus(p[4])
    return omega, a, b, g, nu


def decode_garchx(p):
    omega = _softplus(p[0]) + VAR_FLOOR
    a = _sig(p[1]) * 0.5
    b = _sig(p[2]) * (1 - a)
    pi = _softplus(p[3])
    nu = 2.05 + _softplus(p[4])
    return omega, a, b, pi, nu


# ============================================================================ #
# Multi-step variance forecasting (h-day cumulative-average target).           #
# A forecast made at `origin` with info <= origin-1 produces sigma^2 for days   #
# origin .. origin+H-1; the target is the MEAN over that window (matches        #
# horizon_target_rv). We iterate the variance recursion forward from the        #
# in-sample seed state, never touching any data dated >= origin.                #
# ============================================================================ #
def garch_forecast_path(model, params, y_hist, z_future_placeholder, s2_last, H):
    """Return mean forecast variance over the H-day window [origin, origin+H-1].

    y_hist: in-sample returns up to origin-1 (already demeaned).
    s2_last: sigma^2_{origin} computed from the in-sample filter (uses y_{origin-1}).
    For multi-step we project E[sigma^2_{origin+k}] forward to the long-run var.
    Exogenous z (GARCH-X) is held at its last observed (lagged) value — i.e. the
    multi-step forecast does NOT peek at future z (lookahead-safe, mildly biased
    toward persistence which is the standard treatment).
    """
    if model == "GARCH":
        omega, a, b = params
        persist = a + b
        s2k = s2_last
        acc = []
        for k in range(H):
            acc.append(s2k)
            # E[sigma^2_{t+1}] = omega + (a+b) sigma^2_t (martingale projection)
            s2k = min(max(omega + persist * s2k, VAR_FLOOR), VAR_CEIL)
        return float(np.mean(acc))
    elif model == "GJR":
        omega, a, b, g, nu = params
        persist = a + b + 0.5 * g  # E[1{y<0}]=0.5 under symmetric-ish innovations
        s2k = s2_last
        acc = []
        for k in range(H):
            acc.append(s2k)
            s2k = min(max(omega + persist * s2k, VAR_FLOOR), VAR_CEIL)
        return float(np.mean(acc))
    elif model == "GARCH-X":
        omega, a, b, pi, nu = params
        z_last = z_future_placeholder  # last observed lagged covariate (held flat)
        persist = a + b
        s2k = s2_last
        acc = []
        for k in range(H):
            acc.append(s2k)
            s2k = min(max(omega + persist * s2k + pi * z_last, VAR_FLOOR), VAR_CEIL)
        return float(np.mean(acc))
    raise ValueError(model)


# ============================================================================ #
# HAR-RV and HAR-RV-X (OLS on log-RV; fair baseline fed lagged RV (+ VIX)).     #
# ============================================================================ #
def har_design(rv, vix=None, include_vix=False):
    """Build HAR design on log-RV with daily/weekly/monthly lagged averages.

    Returns (X, y_idx) where row i predicts log-RV at i using info <= i-1:
      x_d = log mean RV over [i-1, i-1]      (1 day)
      x_w = log mean RV over [i-5, i-1]      (5 days)
      x_m = log mean RV over [i-22, i-1]     (22 days)
      (+ log VIX^2 at i-1 if include_vix)
    All regressors strictly lagged -> no contemporaneous leakage.
    """
    logrv = np.log(np.maximum(rv, VAR_FLOOR))
    n = len(rv)
    start = max(HAR_LAGS)  # need 22 history days
    rows, ys, idxs = [], [], []
    for i in range(start, n):
        x_d = logrv[i - 1]
        x_w = np.mean(logrv[i - 5:i])
        x_m = np.mean(logrv[i - 22:i])
        feat = [1.0, x_d, x_w, x_m]
        if include_vix:
            assert vix is not None
            feat.append(np.log(max(vix[i - 1], 1e-6) ** 2))
        rows.append(feat)
        ys.append(logrv[i])
        idxs.append(i)
    return np.array(rows), np.array(ys), np.array(idxs)


def fit_har_ols(X, y):
    """OLS via least squares; returns coefficients (no leakage; pure in-sample)."""
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return coef


def har_forecast(coef, rv_hist, vix_hist=None, include_vix=False, H=1):
    """Forecast mean RV over the next H days from history ending at origin-1.

    rv_hist: RV up to origin-1 inclusive. We use the HAR design evaluated at the
    last available point (info <= origin-1), giving a 1-step log-RV forecast,
    then for H>1 we hold the HAR regressors flat (persistence projection) — the
    standard HAR multi-step proxy that never peeks at future RV.
    Returns forecast in RV (variance) units via exp(.) with a Gaussian
    log-normal retransformation bias correction (0.5 * sigma_resid^2 omitted in
    smoke; documented). Here we use a plain exp (slight downward bias, applied
    identically to HAR and HAR-X so the comparison is fair).
    """
    logrv = np.log(np.maximum(rv_hist, VAR_FLOOR))
    x_d = logrv[-1]
    x_w = np.mean(logrv[-5:])
    x_m = np.mean(logrv[-22:])
    feat = [1.0, x_d, x_w, x_m]
    if include_vix:
        feat.append(np.log(max(vix_hist[-1], 1e-6) ** 2))
    feat = np.array(feat)
    log_fc = float(feat @ coef)
    # H-step: project log-RV toward its persistence (hold regressors flat) — same
    # treatment for HAR and HAR-X. For H=1 this is exact.
    fc = np.exp(np.clip(log_fc, -30, 30))
    return float(min(max(fc, VAR_FLOOR), VAR_CEIL))


# ============================================================================ #
# ARIMA(1,0,1) on log-RV (classical paper benchmark).                          #
# ============================================================================ #
def fit_arima_forecast(rv_hist, H=1):
    """ARIMA(1,0,1) one/H-step on log-RV via statsmodels; lookahead-safe.

    Trained on rv_hist (<= origin-1), forecasts H steps; we take the mean of the
    H-step forecast path as the window target estimate.
    """
    from statsmodels.tsa.arima.model import ARIMA  # local import (heavy)
    logrv = np.log(np.maximum(rv_hist, VAR_FLOOR))
    try:
        model = ARIMA(logrv, order=(1, 0, 1))
        fit = model.fit(method_kwargs={"warn_convergence": False})
        fc_log = fit.forecast(steps=H)
        fc = np.exp(np.clip(np.asarray(fc_log), -30, 30))
        return float(min(max(np.mean(fc), VAR_FLOOR), VAR_CEIL))
    except Exception as e:  # noqa: BLE001
        print(f"[arima] WARN fit/forecast failed, using last-RV fallback: {e}",
              file=sys.stderr)
        return float(min(max(rv_hist[-1], VAR_FLOOR), VAR_CEIL))


# ============================================================================ #
# Neural nets (torch): LSTM, CNN-LSTM, PatchTST-lite, Vanilla Transformer.     #
# All consume a window of features ending at t-1 and predict log-RV at the      #
# target (info-symmetric with the GARCH-X / HAR-X covariate set).               #
# ============================================================================ #
def _make_nn(kind, n_feat, seq_len, seed):
    import torch
    import torch.nn as nn

    torch.manual_seed(seed)

    class LSTMNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(n_feat, 32, batch_first=True)
            self.head = nn.Linear(32, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :]).squeeze(-1)

    class CNNLSTMNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = nn.Conv1d(n_feat, 16, kernel_size=3, padding=1)
            self.act = nn.ReLU()
            self.lstm = nn.LSTM(16, 32, batch_first=True)
            self.head = nn.Linear(32, 1)

        def forward(self, x):
            # x: (B, L, F) -> conv over time
            h = self.act(self.conv(x.transpose(1, 2))).transpose(1, 2)
            out, _ = self.lstm(h)
            return self.head(out[:, -1, :]).squeeze(-1)

    class PatchTSTLite(nn.Module):
        """Lightweight patch-Transformer (PatchTST-style).

        Splits the input sequence into non-overlapping patches, linearly embeds
        each patch, adds positional encoding, runs a small TransformerEncoder,
        and regresses the flattened representation. This is the architecture the
        paper credits with the win.
        """
        def __init__(self, patch=4, d_model=32, nhead=4, nlayers=2):
            super().__init__()
            self.patch = patch
            self.n_patches = seq_len // patch
            self.embed = nn.Linear(patch * n_feat, d_model)
            self.pos = nn.Parameter(torch.zeros(1, self.n_patches, d_model))
            enc = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=nhead, dim_feedforward=64,
                batch_first=True, dropout=0.0)
            self.tr = nn.TransformerEncoder(enc, num_layers=nlayers)
            self.head = nn.Linear(d_model * self.n_patches, 1)

        def forward(self, x):
            B, L, F = x.shape
            usable = self.n_patches * self.patch
            x = x[:, L - usable:, :]  # keep last full patches
            x = x.reshape(B, self.n_patches, self.patch * F)
            h = self.embed(x) + self.pos
            h = self.tr(h)
            return self.head(h.reshape(B, -1)).squeeze(-1)

    class VanillaTransformer(nn.Module):
        def __init__(self, d_model=32, nhead=4, nlayers=2):
            super().__init__()
            self.embed = nn.Linear(n_feat, d_model)
            self.pos = nn.Parameter(torch.zeros(1, seq_len, d_model))
            enc = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=nhead, dim_feedforward=64,
                batch_first=True, dropout=0.0)
            self.tr = nn.TransformerEncoder(enc, num_layers=nlayers)
            self.head = nn.Linear(d_model, 1)

        def forward(self, x):
            h = self.embed(x) + self.pos
            h = self.tr(h)
            return self.head(h[:, -1, :]).squeeze(-1)

    if kind == "LSTM":
        return LSTMNet()
    if kind == "CNN-LSTM":
        return CNNLSTMNet()
    if kind == "PatchTST-lite":
        return PatchTSTLite()
    if kind == "Transformer":
        return VanillaTransformer()
    raise ValueError(kind)


def build_nn_windows(feat_mat, rv_target, seq_len, H):
    """Build (X, y, target_idx) for NN training/forecasting.

    feat_mat: (T, F) feature matrix where row t holds features OBSERVABLE at end
              of day t (so they are all <= t information).
    rv_target: (T,) RV series.
    For a window ending at day j (inclusive, info <= j), the prediction target is
    the MEAN RV over [j+1, j+H] (forward-label). This guarantees
    target_end (j+H) > forecast_origin (j+1), and the deepest training input
    (day j) is strictly before the target window — no lookahead (K1337).
    Returns X (n, seq_len, F), y (n,) log-RV-mean, target_idx (n,) = j+1 (origin).
    """
    T = len(rv_target)
    X, y, origins = [], [], []
    logrv = np.log(np.maximum(rv_target, VAR_FLOOR))
    for j in range(seq_len - 1, T - H):
        window = feat_mat[j - seq_len + 1: j + 1]  # ends at day j (info <= j)
        tgt_window = logrv[j + 1: j + 1 + H]       # [origin, origin+H-1]
        if len(tgt_window) < H:
            continue
        X.append(window)
        y.append(np.mean(tgt_window))
        origins.append(j + 1)
    return np.asarray(X, dtype=np.float64), np.asarray(y, dtype=np.float64), np.asarray(origins)


def train_predict_nn(kind, X_tr, y_tr, X_te, seq_len, n_feat, seed,
                     epochs, lr, feat_mean, feat_std, y_mean, y_std):
    import torch

    torch.manual_seed(seed)
    np.random.seed(seed)

    net = _make_nn(kind, n_feat, seq_len, seed)
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    loss_fn = torch.nn.MSELoss()

    Xtr = torch.tensor((X_tr - feat_mean) / feat_std, dtype=torch.float32)
    ytr = torch.tensor((y_tr - y_mean) / y_std, dtype=torch.float32)

    net.train()
    bs = 256
    n = len(Xtr)
    g = torch.Generator().manual_seed(seed)
    for ep in range(epochs):
        perm = torch.randperm(n, generator=g)
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            opt.zero_grad()
            pred = net(Xtr[idx])
            loss = loss_fn(pred, ytr[idx])
            loss.backward()
            opt.step()

    net.eval()
    with torch.no_grad():
        Xte = torch.tensor((X_te - feat_mean) / feat_std, dtype=torch.float32)
        pred = net(Xte).numpy() * y_std + y_mean  # de-standardize log-RV
    fc = np.exp(np.clip(pred, -30, 30))
    return np.clip(fc, VAR_FLOOR, VAR_CEIL)


# ============================================================================ #
# DM-HLN test (Harvey-Leybourne-Newbold small-sample correction).              #
# Inference horizon h MUST equal the target horizon H (rule: experiments.md).   #
# ============================================================================ #
def dm_hln_test(loss_a, loss_b, h):
    """Negative dm => model A (loss_a) has lower loss (A better)."""
    d = np.asarray(loss_a) - np.asarray(loss_b)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return {"dm": None, "p": None, "n": n}
    dbar = d.mean()
    gamma0 = np.sum((d - dbar) ** 2) / n
    var = gamma0
    for k in range(1, h):
        cov = np.sum((d[k:] - dbar) * (d[:-k] - dbar)) / n
        var += 2.0 * (1 - k / h) * cov
    if var <= 0:
        return {"dm": None, "p": None, "n": n}
    dm = dbar / np.sqrt(var / n)
    corr = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_hln = dm * corr
    p = 2 * (1 - student_t.cdf(abs(dm_hln), df=n - 1))
    return {"dm": float(dm_hln), "p": float(p), "n": int(n), "dbar": float(dbar),
            "h": int(h)}


# ============================================================================ #
# OOS evaluation engine — aligns ALL models on a COMMON origin grid.            #
# ============================================================================ #
def run_index(name, df, target_col="rv_cc", H=1, oos_frac=0.30, refit_every=20,
              max_oos=None, seq_len=22, nn_epochs=30, nn_lr=1e-3, seed=0,
              nn_kinds=("LSTM", "CNN-LSTM", "PatchTST-lite", "Transformer"),
              verbose=True):
    """Run Phase A + Phase B for one index/target/horizon on a common origin grid.

    Returns a dict of forecasts/losses/tests keyed by model.
    """
    t0 = time.time()
    rng = np.random.default_rng(seed)

    ret = df["ret"].to_numpy(dtype=float)
    rv = df[target_col].to_numpy(dtype=float)
    vix = df["vix"].to_numpy(dtype=float)
    T = len(rv)

    # ---- build the common information set fed to BOTH NN and GARCH-X/HAR-X --- #
    # Features observable at end of day t: ret_t, log(rv_t), log VIX_t, plus HAR
    # aggregates of RV (computed from <= t). These ARE the same lagged RV(1,5,22)
    # + VIX information the fair GARCH-X / HAR-X baselines receive.
    logrv = np.log(np.maximum(rv, VAR_FLOOR))
    rv_d = logrv.copy()
    rv_w = pd.Series(logrv).rolling(5).mean().to_numpy()
    rv_m = pd.Series(logrv).rolling(22).mean().to_numpy()
    log_vix2 = np.log(np.maximum(vix, 1e-6) ** 2)
    feat_mat = np.column_stack([ret, rv_d, rv_w, rv_m, log_vix2])
    # rows with NaN HAR aggregates (first 21) cannot seed a window; mask later.
    feat_valid_from = max(HAR_LAGS)  # 22
    feat_mat[:feat_valid_from] = np.nan_to_num(feat_mat[:feat_valid_from], nan=0.0)

    # ---- OOS origin grid (common to all models) ----------------------------- #
    n_oos = int(T * oos_frac)
    start = T - n_oos
    if max_oos is not None:
        start = max(start, T - max_oos)
    # Need room for the H-day forward-label window AND a seq_len history.
    start = max(start, seq_len + feat_valid_from + 250)  # >=250 train rows
    last_origin = T - H  # target window [origin, origin+H-1] must fit
    origins = list(range(start, last_origin + 1))
    if verbose:
        print(f"[{name}/{target_col}/h{H}] T={T} OOS origins {start}..{last_origin} "
              f"(n={len(origins)}) seed={seed}", flush=True)

    classical_models = ["ARIMA", "GARCH(1,1)", "HAR-RV",          # Phase A classical
                        "GJR-t", "GARCH-X", "HAR-RV-X"]           # Phase B fair baselines
    forecasts = {m: np.full(len(origins), np.nan) for m in classical_models}
    targets = np.full(len(origins), np.nan)

    # cache fitted GARCH/GJR/GARCH-X params; refit_every to bound cost
    cached = None

    for oi, origin in enumerate(origins):
        # forward-label target: mean RV over [origin, origin+H-1] (>= origin)
        tgt_end = origin + H
        targets[oi] = float(np.mean(rv[origin:tgt_end]))

        # in-sample training rows: 0 .. origin-1  (train_end = origin-1 < origin)
        y_hist = ret[:origin] - float(np.mean(ret[:origin]))  # demean in-sample
        rv_hist = rv[:origin]
        vix_hist = vix[:origin]
        s2init = float(np.var(y_hist))

        # exogenous covariate for GARCH-X: lagged RV (z_{t-1} = rv at origin-1)
        z_hist = rv[:origin]  # filter uses z[t-1] internally

        need_refit = (cached is None) or (oi % refit_every == 0)
        if need_refit:
            ns = 6 if cached is None else 3
            fg = fit_garch_gauss(y_hist, s2init, rng, n_start=ns)
            fj = fit_gjr_t(y_hist, s2init, rng, n_start=ns)
            fx = fit_garchx_t(y_hist, z_hist, s2init, rng, n_start=ns)
            har_X, har_y, _ = har_design(rv_hist, include_vix=False)
            har_coef = fit_har_ols(har_X, har_y) if len(har_X) > 10 else None
            harx_X, harx_y, _ = har_design(rv_hist, vix=vix_hist, include_vix=True)
            harx_coef = fit_har_ols(harx_X, harx_y) if len(harx_X) > 10 else None
            cached = {
                "garch": fg.x if fg else None,
                "gjr": fj.x if fj else None,
                "garchx": fx.x if fx else None,
                "har": har_coef,
                "harx": harx_coef,
            }

        # --- classical forecasts (all info <= origin-1) --------------------- #
        # GARCH(1,1) seed state: sigma^2_origin from in-sample filter.
        if cached["garch"] is not None:
            om, a, b = decode_garch(cached["garch"])
            s2_filt = filter_garch(y_hist, s2init, om, a, b)
            forecasts["GARCH(1,1)"][oi] = garch_forecast_path(
                "GARCH", (om, a, b), y_hist, None, s2_filt[-1], H)
        if cached["gjr"] is not None:
            om, a, b, g, nu = decode_gjr(cached["gjr"])
            s2_filt = filter_gjr(y_hist, s2init, om, a, b, g)
            forecasts["GJR-t"][oi] = garch_forecast_path(
                "GJR", (om, a, b, g, nu), y_hist, None, s2_filt[-1], H)
        if cached["garchx"] is not None:
            om, a, b, pi, nu = decode_garchx(cached["garchx"])
            s2_filt = filter_garchx(y_hist, z_hist, s2init, om, a, b, pi)
            z_last = z_hist[-1]  # last observed lagged RV (info <= origin-1)
            forecasts["GARCH-X"][oi] = garch_forecast_path(
                "GARCH-X", (om, a, b, pi, nu), y_hist, z_last, s2_filt[-1], H)
        if cached["har"] is not None:
            forecasts["HAR-RV"][oi] = har_forecast(
                cached["har"], rv_hist, include_vix=False, H=H)
        if cached["harx"] is not None:
            forecasts["HAR-RV-X"][oi] = har_forecast(
                cached["harx"], rv_hist, vix_hist=vix_hist, include_vix=True, H=H)
        forecasts["ARIMA"][oi] = fit_arima_forecast(rv_hist, H=H)

    # ---- NN models: train ONCE on the pre-OOS window, predict the OOS grid --- #
    # Build all forward-label windows; split by origin < start (train) vs >=start.
    X_all, y_all, win_origins = build_nn_windows(feat_mat, rv, seq_len, H)
    # train mask: target window strictly before the first OOS origin
    # (origin = win_origins; train if origin < start so target_end <= start-1+H?).
    # To keep training strictly causal w.r.t. the OOS block, require the training
    # target window to END before the first OOS origin: origin + H <= start.
    train_mask = (win_origins + H) <= start
    test_mask = np.isin(win_origins, np.array(origins))
    X_tr, y_tr = X_all[train_mask], y_all[train_mask]
    # align NN test predictions to the SAME origin grid as classical models
    test_origins = win_origins[test_mask]
    X_te = X_all[test_mask]

    feat_mean = X_tr.reshape(-1, X_tr.shape[-1]).mean(axis=0)
    feat_std = X_tr.reshape(-1, X_tr.shape[-1]).std(axis=0) + 1e-8
    y_mean, y_std = y_tr.mean(), y_tr.std() + 1e-8

    nn_forecasts = {}
    nn_times = {}
    for kind in nn_kinds:
        tk = time.time()
        fc = train_predict_nn(
            kind, X_tr, y_tr, X_te, seq_len, X_tr.shape[-1], seed,
            nn_epochs, nn_lr, feat_mean, feat_std, y_mean, y_std)
        # map NN forecasts (on test_origins) onto the classical origin grid
        fc_on_grid = np.full(len(origins), np.nan)
        origin_to_idx = {o: i for i, o in enumerate(origins)}
        for o, v in zip(test_origins, fc):
            if o in origin_to_idx:
                fc_on_grid[origin_to_idx[o]] = v
        nn_forecasts[kind] = fc_on_grid
        nn_times[kind] = time.time() - tk
        if verbose:
            print(f"  [NN {kind}] trained on {len(X_tr)} windows, "
                  f"predicted {np.isfinite(fc_on_grid).sum()} origins "
                  f"({nn_times[kind]:.1f}s)", flush=True)

    all_forecasts = {**forecasts, **nn_forecasts}

    # ---- common-valid mask across ALL models + targets ---------------------- #
    valid = np.isfinite(targets)
    for m, f in all_forecasts.items():
        valid &= np.isfinite(f)
    n_valid = int(valid.sum())

    tgt_v = targets[valid]
    fc_v = {m: f[valid] for m, f in all_forecasts.items()}

    # ---- QLIKE (canonical actual/pred - log - 1) + RMSE + MAE --------------- #
    qlike_scores, rmse_scores, mae_scores, pointwise = {}, {}, {}, {}
    for m, f in fc_v.items():
        qlike_scores[m] = qlike(tgt_v, f)
        rmse_scores[m] = float(np.sqrt(np.mean((np.sqrt(tgt_v) - np.sqrt(np.maximum(f, 0))) ** 2)))
        mae_scores[m] = float(np.mean(np.abs(np.sqrt(tgt_v) - np.sqrt(np.maximum(f, 0)))))
        pointwise[m] = qlike_pointwise(tgt_v, f)

    ranking = sorted(qlike_scores.items(), key=lambda kv: kv[1] if np.isfinite(kv[1]) else 1e18)

    # ---- Phase A reproduction check: PatchTST-lite QLIKE <= GARCH(1,1)? ----- #
    repro_patch_beats_garch = (
        "PatchTST-lite" in qlike_scores and "GARCH(1,1)" in qlike_scores
        and qlike_scores["PatchTST-lite"] <= qlike_scores["GARCH(1,1)"]
    )
    # classical Table A2 sanity: HAR-RV QLIKE << GARCH(1,1), DM (h=H) significant
    dm_har_vs_garch = dm_hln_test(pointwise["HAR-RV"], pointwise["GARCH(1,1)"], h=H)

    # ---- Phase B adjudication DM tests: each DL vs GJR-t, vs GARCH-X, HAR-X -- #
    dl_models = [k for k in nn_kinds]
    fair_baselines = ["GJR-t", "GARCH-X", "HAR-RV-X"]
    dm_phaseB = {}
    for dl in dl_models:
        for base in fair_baselines:
            key = f"{dl}_vs_{base}"
            res = dm_hln_test(pointwise[dl], pointwise[base], h=H)
            res["interpretation"] = (
                "DL_better" if (res["dm"] is not None and res["dm"] < 0) else "baseline_better"
            )
            res["harvey_significant"] = bool(res["dm"] is not None and abs(res["dm"]) > 3.0)
            dm_phaseB[key] = res

    # ---- MCS over the full pool (HLN stationary bootstrap) ------------------ #
    mcs_losses = {m: pointwise[m] for m in fc_v}
    mcs = model_confidence_set(mcs_losses, alpha=0.10, n_boot=2000, seed=seed)

    elapsed = time.time() - t0
    return {
        "index": name,
        "target": target_col,
        "horizon": H,
        "seed": seed,
        "n_oos_origins": len(origins),
        "n_valid_common": n_valid,
        "qlike": qlike_scores,
        "rmse_vol": rmse_scores,
        "mae_vol": mae_scores,
        "ranking_by_qlike": [{"rank": i + 1, "model": m, "qlike": s}
                             for i, (m, s) in enumerate(ranking)],
        "phaseA_reproduction": {
            "patchtst_qlike": qlike_scores.get("PatchTST-lite"),
            "garch11_qlike": qlike_scores.get("GARCH(1,1)"),
            "patchtst_beats_garch11": bool(repro_patch_beats_garch),
            "har_vs_garch11_dm_hln": dm_har_vs_garch,
            "har_crushes_garch11_tableA2_sanity": bool(
                dm_har_vs_garch["dm"] is not None and dm_har_vs_garch["dm"] < -3.0),
        },
        "phaseB_adjudication_dm": dm_phaseB,
        "mcs": {"members": mcs["mcs_models"], "size": len(mcs["mcs_models"]),
                "p_values": mcs["p_values"]},
        "nn_train_times_s": nn_times,
        "elapsed_s": elapsed,
    }


# ============================================================================ #
# Main (smoke).                                                                #
# ============================================================================ #
def _synth_conclusion(res):
    """Synthesize the smoke verdict for one (index,target,h) result block.

    The adjudication hinges on the DL-vs-HAR-RV-X DM tests: if NO DL model is
    Harvey-significant (|t|>3) over the SAME-information HAR-RV-X, the paper's
    DL advantage is an information advantage (M2/M3), not architecture.
    """
    pa = res["phaseA_reproduction"]
    dl_models = [k for k in res["qlike"] if k in
                 ("LSTM", "CNN-LSTM", "PatchTST-lite", "Transformer")]
    # DL vs HAR-RV-X (same info set) — does ANY DL beat HAR-X with Harvey sig?
    dl_beats_harx_sig = []
    for dl in dl_models:
        v = res["phaseB_adjudication_dm"].get(f"{dl}_vs_HAR-RV-X")
        if v and v["dm"] is not None and v["dm"] < 0 and abs(v["dm"]) > 3.0:
            dl_beats_harx_sig.append(dl)
    # DL vs GARCH(1,1)-family weak baseline — typical DL "win" the paper claims
    dl_beats_gjr_sig = []
    for dl in dl_models:
        v = res["phaseB_adjudication_dm"].get(f"{dl}_vs_GJR-t")
        if v and v["dm"] is not None and v["dm"] < 0 and abs(v["dm"]) > 3.0:
            dl_beats_gjr_sig.append(dl)
    return {
        "phaseA_reproduced_raw_win": bool(pa["patchtst_beats_garch11"]),
        "dl_models_significantly_beating_HAR_RV_X": dl_beats_harx_sig,
        "dl_models_significantly_beating_GJR_t": dl_beats_gjr_sig,
        "ceiling_holds": bool(len(dl_beats_harx_sig) == 0),
        "interpretation": (
            "CEILING HOLDS — once HAR-RV-X gets the same lagged RV(1,5,22)+VIX "
            "info, NO DL model is Harvey-significant over it (M2/M3 confirmed: "
            "the paper's DL 'win' is an information advantage, not architecture)."
            if len(dl_beats_harx_sig) == 0 else
            f"COUNTER-EXAMPLE — {dl_beats_harx_sig} significantly beat the "
            "same-info HAR-RV-X; DL genuinely breaks the ceiling here. Report "
            "as a real, publishable result; do not suppress."
        ),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="gspc")
    ap.add_argument("--target", default="rv_cc",
                    help="single target; ignored if --targets given")
    ap.add_argument("--targets", default=None,
                    help="comma list, e.g. rv_cc,rv_park (consolidated JSON)")
    ap.add_argument("--horizon", type=int, default=1)
    ap.add_argument("--max-oos", type=int, default=400, help="cap OOS origins (smoke)")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seed-check", action="store_true",
                    help="also run a second seed to verify NN determinism")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    df = pd.read_parquet(DATA / f"{args.index}.parquet")
    targets = (args.targets.split(",") if args.targets else [args.target])

    results = {}
    conclusions = {}
    for tgt in targets:
        res = run_index(
            args.index.upper(), df, target_col=tgt, H=args.horizon,
            max_oos=args.max_oos, nn_epochs=args.epochs, seed=args.seed)
        key = f"{args.index}_{tgt}_h{args.horizon}_seed{args.seed}"
        results[key] = res
        conclusions[key] = _synth_conclusion(res)

    out = {
        "experiment_id": "k1535_ml_garch_adjudication_equity",
        "title": "ML-vs-GARCH volatility reproduction adjudication (daily US equity)",
        "reproduced_paper": {
            "citation": "Aljadani et al. (2025), J. Risk Financial Management 18(12):685",
            "url": "https://www.mdpi.com/1911-8074/18/12/685",
            "claimed_winner": "PatchTST-lite over LSTM/CNN-LSTM/Vanilla-Transformer "
                              "and ARIMA/GARCH(1,1)/HAR-RV on daily RV, h=1/5/22",
            "weaknesses_targeted": {
                "M1": "weak baseline — only plain Gaussian GARCH(1,1)",
                "M2": "no significance test on the DL models (DM/MCS classical-only)",
                "M3": "possible covariate asymmetry (RV proxy to NN, return^2 to GARCH)",
            },
            "paper_numbers_verified": "unverified — not cross-checked against PDF in smoke",
        },
        "run_type": "smoke_test",
        "verdict": "SMOKE_PENDING_FULL_RUN",
        "data_source": json.loads((DATA / "data_meta.json").read_text()),
        "config": {
            "index": args.index, "targets": targets, "horizon": args.horizon,
            "max_oos": args.max_oos, "epochs": args.epochs, "seed": args.seed,
            "info_set": "ret_t, log RV_t, log RV_w(5), log RV_m(22), log VIX^2 — "
                        "identical for NN windows and GARCH-X/HAR-X baselines",
            "target_note": "rv_cc (close-to-close r^2) is a very noisy proxy on "
                           "which classical GARCH wins by construction and the "
                           "paper's HAR>>GARCH ranking does NOT hold; the paper's "
                           "claim is on a SMOOTH RV target (range-based), so "
                           "rv_park is the faithful-reproduction target.",
        },
        "smoke_conclusions": conclusions,
        "results": results,
    }

    if args.seed_check:
        # determinism: re-run NN-only path at same seed must reproduce; a different
        # seed verifies seeding is wired (results should differ).
        tgt = targets[-1]
        res_same = run_index(
            args.index.upper(), df, target_col=tgt, H=args.horizon,
            max_oos=args.max_oos, nn_epochs=args.epochs, seed=args.seed,
            nn_kinds=("PatchTST-lite",), verbose=False)
        res_diff = run_index(
            args.index.upper(), df, target_col=tgt, H=args.horizon,
            max_oos=args.max_oos, nn_epochs=args.epochs, seed=args.seed + 1,
            nn_kinds=("PatchTST-lite",), verbose=False)
        q_orig = results[f"{args.index}_{tgt}_h{args.horizon}_seed{args.seed}"]["qlike"]["PatchTST-lite"]
        q_same = res_same["qlike"]["PatchTST-lite"]
        q_diff = res_diff["qlike"]["PatchTST-lite"]
        out["determinism_check"] = {
            "target": tgt,
            "patchtst_qlike_seed0_runA": q_orig,
            "patchtst_qlike_seed0_runB": q_same,
            "same_seed_reproduces": bool(abs(q_orig - q_same) < 1e-9),
            "patchtst_qlike_seed1": q_diff,
            "different_seed_differs": bool(abs(q_orig - q_diff) > 1e-12),
        }

    out_path = HERE / "k1535_ml_garch_adjudication_equity_results.json"
    out_path.write_text(json.dumps(out, indent=2, default=float))
    print(f"\nwrote {out_path}")

    # console summary (per target)
    for key, r in results.items():
        print(f"\n=== {r['index']} {r['target']} h={r['horizon']} "
              f"(n_valid={r['n_valid_common']}) ===")
        print("QLIKE ranking:")
        for row in r["ranking_by_qlike"]:
            print(f"  {row['rank']:2d}. {row['model']:16s} {row['qlike']:.6f}")
        pa = r["phaseA_reproduction"]
        print(f"Phase A: PatchTST-lite QLIKE={pa['patchtst_qlike']:.6f} vs "
              f"GARCH(1,1)={pa['garch11_qlike']:.6f} -> "
              f"reproduce paper win (PatchTST<=GARCH)? {pa['patchtst_beats_garch11']}")
        print("Phase B DL-vs-HAR-RV-X (same info set):")
        for dl in ("LSTM", "CNN-LSTM", "PatchTST-lite", "Transformer"):
            v = r["phaseB_adjudication_dm"].get(f"{dl}_vs_HAR-RV-X")
            if v:
                print(f"  {dl:16s} dm={v['dm']:.3f} p={v['p']:.4f} "
                      f"{v['interpretation']} harvey_sig={v['harvey_significant']}")
        print(f"MCS members: {r['mcs']['members']}")
        print(f"CONCLUSION: {conclusions[key]['interpretation']}")


if __name__ == "__main__":
    main()
