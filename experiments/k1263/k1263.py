"""
K1263: KAN-GARCH-MIDAS — Can structured Kolmogorov-Arnold Networks break the ML ceiling?
=========================================================================================
[提出: User, 執行: Claude]

Research Question:
  Does a KAN (Kolmogorov-Arnold Networks; Liu et al. 2024) used as the long-run
  MIDAS aggregator on top of a GJR-GARCH short-run filter beat plain GJR-GARCH
  for OOS daily volatility forecasting on SPY/QQQ?

Motivation:
- ML ceiling has been confirmed 6 times on equity vol (K785 MF2-GARCH, K816v2 GINN,
  K784 GARCH-GRU, etc.) — all NULL with DM-HLN |t| < 2 vs GJR baseline.
- KANs (2024) replace fixed-activation MLP nodes with learnable spline functions on
  edges, providing a STRUCTURED inductive prior. Hypothesis: structured prior may
  succeed where unstructured ML failed.
- Falsifiable: 三重 OOS gate (DM |t|>3.0, ≥5% QLIKE relative improvement, sub-period
  stable). Pass→article-able / Paper-3 candidate; fail→ML ceiling 第7次確認 null.

Hypotheses:
  H0: KAN-GARCH-MIDAS QLIKE indistinguishable from GJR baseline (DM |t|<3.0).
  H1: KAN beats GJR with all three gates passed.

Design:
- Assets: SPY, QQQ (both daily, yfinance, 2007-01-01 onward)
- Baseline (B): GJR-GARCH-Normal, expanding window, refit every 63 days
- Challenger (C): KAN-GARCH-MIDAS
    sigma^2_{t+1} = g_{t+1|t} * tau_{t+1|t}
    g_t : short-run GJR filter on z_t = r_t / sqrt(tau_t)
    tau_t = exp( KAN( macro_X_{t-1} ) ) — KAN replaces Beta-MIDAS polynomial
- Macro X (all lagged by 1 day, t-1):
    1. VIX level (yfinance ^VIX)
    2. 10y - 3m term spread (yfinance ^TNX - ^IRX)
    3. HYG/IEF ratio log-return (credit spread proxy; FRED unavailable in env)
    4. 22d rolling realized vol of SPY (lagged)
- Window: 1500 obs rolling (KAN refit). GJR uses expanding for fairness with K785.
- OOS: 2021-01-04 → 2026-04-10 (truncated to last available date)
- Target proxy: r^2 (Patton 2011 QLIKE)
- Refit cadence: every 63 days (quarterly)
- Seeds: 42 globally (numpy/torch); KAN init seed 42

Three-gate publishable threshold (K1100g_d1):
  (a) DM-HLN |t| > 3.0 (Harvey 2016 two-sided)
  (b) QLIKE relative improvement ≥ 5%
  (c) Sub-period stable (split at 2024-01-01: both halves better)

References:
- Liu Z. et al. (2024), "KAN: Kolmogorov-Arnold Networks", arXiv:2404.19756
- Liu Z., Ma P., Wang Y., Matusik W., Tegmark M. (2025) "KAN 2.0", arXiv:2408.10205
- Engle, Ghysels, Sohn (2013), "Stock Market Volatility and Macroeconomic
  Fundamentals", Review of Economics & Statistics 95(3):776-797 (GARCH-MIDAS).
- Conrad & Engle (2025), "Long- and Short-Run Components of GARCH", J. Applied
  Econometrics.
- Patton (2011), "Volatility forecast comparison using imperfect volatility
  proxies", J. Econometrics 160:246-256 (QLIKE proxy-robust).
- Harvey, Liu, Zhu (2016), "...and the Cross-Section of Expected Returns",
  RFS 29(1):5-68 (DM |t|>3.0 threshold).
- Diebold & Mariano (1995); Harvey, Leybourne, Newbold (1997) — DM-HLN
  small-sample correction.

Data source: yfinance (SPY, QQQ, ^VIX, ^TNX, ^IRX, HYG, IEF)
Reproduction: uv run python experiments/k1263/k1263.py
"""
from __future__ import annotations

import json
import math
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import yfinance as yf
from scipy import stats
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

# ============================================================
# Configuration
# ============================================================
ASSETS = ["SPY", "QQQ"]
DATA_START = "2007-01-01"
DATA_END = "2026-04-10"
OOS_START = "2021-01-04"
SUB_PERIOD_SPLIT = "2024-01-01"
REFIT_INTERVAL = 63  # quarterly
WINDOW = 1500  # rolling for KAN
SEED = 42

OUTDIR = Path(__file__).parent
OUTDIR.mkdir(parents=True, exist_ok=True)

np.random.seed(SEED)
torch.manual_seed(SEED)

# ============================================================
# Data loaders (with cache to data/)
# ============================================================
DATA_DIR = OUTDIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_close(ticker: str, start: str, end: str) -> pd.Series:
    cache = DATA_DIR / f"{ticker.replace('^','').replace('-','_')}.csv"
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        s = df.iloc[:, 0]
    else:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
        if df.empty:
            raise RuntimeError(f"yfinance returned empty for {ticker}")
        # use Close (or Adj Close for equities — for ^VIX/^TNX/^IRX Close == level)
        col = "Adj Close" if "Adj Close" in df.columns else "Close"
        s = df[col]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s.name = ticker
        s.to_frame().to_csv(cache)
    s.index = pd.to_datetime(s.index)
    return s.astype(float).sort_index()


def build_panel() -> dict[str, pd.DataFrame]:
    """Returns dict[asset] -> DataFrame with columns: ret, vix, term, credit, rv22."""
    vix = fetch_close("^VIX", DATA_START, DATA_END).rename("vix")
    tnx = fetch_close("^TNX", DATA_START, DATA_END).rename("tnx")
    irx = fetch_close("^IRX", DATA_START, DATA_END).rename("irx")
    hyg = fetch_close("HYG", DATA_START, DATA_END).rename("hyg")
    ief = fetch_close("IEF", DATA_START, DATA_END).rename("ief")

    term = (tnx - irx).rename("term")
    # credit-spread proxy: daily log-return of HYG/IEF ratio (stationary).
    # Positive value = HY outperforms IG (credit easing); negative = credit stress.
    # Per K1263 design header (macro #3), this is a daily *return* not a level.
    hyg_ief_ratio = hyg / ief
    credit_ret = (np.log(hyg_ief_ratio) - np.log(hyg_ief_ratio.shift(1))).rename("credit")

    panels = {}
    for asset in ASSETS:
        px = fetch_close(asset, DATA_START, DATA_END)
        ret = (np.log(px) - np.log(px.shift(1))) * 100  # %
        rv22 = ret.rolling(22).apply(lambda x: np.sqrt(np.mean(x ** 2)), raw=True)
        df = pd.concat(
            [ret.rename("ret"), vix, term, credit_ret, rv22.rename("rv22")], axis=1
        )
        df = df.dropna()
        panels[asset] = df
    return panels


# ============================================================
# GJR-GARCH (Normal) — analytic MLE via scipy
# ============================================================
def _gjr_neg_loglik(params, r):
    omega, alpha, gamma, beta = params
    if omega <= 1e-10 or alpha < 0 or gamma < 0 or beta < 0 or alpha + 0.5 * gamma + beta >= 0.999:
        return 1e10
    n = len(r)
    var = np.empty(n)
    var[0] = np.var(r)
    for t in range(1, n):
        prev_r = r[t - 1]
        ind = 1.0 if prev_r < 0 else 0.0
        var[t] = omega + (alpha + gamma * ind) * prev_r ** 2 + beta * var[t - 1]
        if var[t] <= 1e-10:
            return 1e10
    ll = -0.5 * np.sum(np.log(2 * np.pi * var) + r ** 2 / var)
    return -ll


def fit_gjr_normal(r: np.ndarray):
    r = np.asarray(r, dtype=float)
    x0 = np.array([0.05, 0.05, 0.05, 0.85])
    bounds = [(1e-6, None), (0.0, 0.5), (0.0, 0.5), (0.0, 0.999)]
    best = None
    for seed_x in [x0, [0.1, 0.1, 0.1, 0.7], [0.02, 0.03, 0.07, 0.88]]:
        try:
            res = minimize(
                _gjr_neg_loglik,
                seed_x,
                args=(r,),
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 200},
            )
            if res.success and (best is None or res.fun < best.fun):
                best = res
        except Exception:
            continue
    if best is None:
        # fallback minimal valid params
        return {"omega": np.var(r) * 0.05, "alpha": 0.05, "gamma": 0.05, "beta": 0.85}
    omega, alpha, gamma, beta = best.x
    return {"omega": omega, "alpha": alpha, "gamma": gamma, "beta": beta}


def gjr_filter(r: np.ndarray, params: dict) -> np.ndarray:
    """Returns sigma^2 series given params."""
    omega, alpha, gamma, beta = params["omega"], params["alpha"], params["gamma"], params["beta"]
    n = len(r)
    var = np.empty(n)
    var[0] = np.var(r)
    for t in range(1, n):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        var[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * var[t - 1]
        var[t] = max(var[t], 1e-10)
    return var


def gjr_one_step_forecast(r: np.ndarray, var: np.ndarray, params: dict) -> float:
    omega, alpha, gamma, beta = params["omega"], params["alpha"], params["gamma"], params["beta"]
    last_r, last_v = r[-1], var[-1]
    ind = 1.0 if last_r < 0 else 0.0
    return omega + (alpha + gamma * ind) * last_r ** 2 + beta * last_v


# ============================================================
# KAN long-run aggregator (using pykan)
# ============================================================
# pykan dependency note: this experiment requires `pykan` installed in the active
# Python env. As of 2026-05-02 the volpred project pyproject.toml declares
# requires-python>=3.12 and does not list pykan; this script is intended to run
# with the system anaconda3 python 3.9 environment that has pykan 0.0.5 + torch
# 2.0.1 installed (see CLAUDE.md / experiments/k1263/README.md).
try:
    from kan import KAN
except ImportError as _e:
    raise ImportError(
        "pykan not available in current python env. "
        "Run with `python experiments/k1263/k1263.py` using the anaconda3 python "
        "(which has pykan 0.0.5 + torch installed), or `pip install pykan` first."
    ) from _e


def fit_kan_longrun(X_train: np.ndarray, y_train: np.ndarray, in_dim: int):
    """
    Fit a small KAN to predict log(rv22) from macro X (all t-1 lagged upstream).
    Returns a callable predict(x) -> log_tau scalar/vector.
    """
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    # standardize
    mu, sd = X_train.mean(0), X_train.std(0) + 1e-8
    Xs = (X_train - mu) / sd
    ymu, ysd = y_train.mean(), y_train.std() + 1e-8
    ys = (y_train - ymu) / ysd

    Xt = torch.tensor(Xs, dtype=torch.float32)
    yt = torch.tensor(ys, dtype=torch.float32).reshape(-1, 1)

    # Compact KAN: in_dim → 3 → 1, grid=5, k=3 (cubic spline)
    model = KAN(width=[in_dim, 3, 1], grid=5, k=3, seed=SEED)
    # pykan 0.0.5 API uses .train() (not .fit())
    dataset = {
        "train_input": Xt,
        "train_label": yt,
        "test_input": Xt,
        "test_label": yt,
    }
    train_succeeded = False
    last_err = None
    try:
        model.train(dataset, opt="LBFGS", steps=20, lamb=0.001, log=-1)
        train_succeeded = True
    except Exception as e:
        last_err = e
        try:
            model.train(dataset, opt="Adam", steps=100, lr=0.01, log=-1)
            train_succeeded = True
        except Exception as e2:
            last_err = e2
    if not train_succeeded:
        # CRITICAL (Codex P1): never silently use random-init KAN as challenger.
        raise RuntimeError(
            f"KAN training failed (LBFGS+Adam both raised). Last err: {last_err!r}. "
            "Refusing to forecast with random-init weights — would publish invalid results."
        )

    def predict(Xnew: np.ndarray) -> np.ndarray:
        Xn = (Xnew - mu) / sd
        with torch.no_grad():
            yhat = model(torch.tensor(Xn, dtype=torch.float32)).cpu().numpy().flatten()
        return yhat * ysd + ymu

    return predict


# ============================================================
# Patton QLIKE
# ============================================================
def qlike(proxy_r2: np.ndarray, sigma2_hat: np.ndarray) -> float:
    proxy_r2 = np.maximum(proxy_r2, 1e-10)
    sigma2_hat = np.maximum(sigma2_hat, 1e-10)
    return float(np.mean(proxy_r2 / sigma2_hat - np.log(proxy_r2 / sigma2_hat) - 1.0))


def qlike_loss_series(proxy_r2: np.ndarray, sigma2_hat: np.ndarray) -> np.ndarray:
    proxy_r2 = np.maximum(proxy_r2, 1e-10)
    sigma2_hat = np.maximum(sigma2_hat, 1e-10)
    return proxy_r2 / sigma2_hat - np.log(proxy_r2 / sigma2_hat) - 1.0


# ============================================================
# DM-HLN (Harvey-Leybourne-Newbold small-sample correction)
# ============================================================
def dm_hln(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple[float, float]:
    """Returns (t_stat, p_value). H0: equal predictive accuracy.
    loss1 = challenger, loss2 = baseline. Negative t_stat → challenger better."""
    d = loss1 - loss2
    n = len(d)
    if n < 10:
        return float("nan"), float("nan")
    mean_d = np.mean(d)
    # autocovariances
    gamma0 = np.var(d, ddof=0)
    var_d = gamma0
    for k in range(1, h):
        gk = np.cov(d[k:], d[:-k], ddof=0)[0, 1]
        var_d += 2 * (1 - k / h) * gk
    if var_d <= 0:
        return float("nan"), float("nan")
    dm_stat = mean_d / np.sqrt(var_d / n)
    # HLN small-sample correction
    correction = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_stat = dm_stat * correction
    p = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p)


# ============================================================
# Walk-forward engine
# ============================================================
def run_asset(asset: str, df: pd.DataFrame) -> dict:
    print(f"\n=== {asset} ===  n_obs={len(df)}")
    # CRITICAL lookahead protection: macro X and rv22 used at time t MUST be t-1
    # We use values at t-1 to forecast variance at t.
    df = df.copy()
    macro_cols = ["vix", "term", "credit", "rv22"]
    df[macro_cols] = df[macro_cols].shift(1)  # ALL macro lagged by 1 day
    df = df.dropna()

    oos_mask = df.index >= pd.Timestamp(OOS_START)
    oos_dates = df.index[oos_mask]
    n_oos = oos_mask.sum()
    print(f"  OOS rows: {n_oos}  ({oos_dates.min()} → {oos_dates.max()})")

    r_full = df["ret"].values
    proxy_full = r_full ** 2
    X_full = df[macro_cols].values

    # Pre-allocate forecasts
    sig2_gjr = np.full(len(df), np.nan)
    sig2_kan = np.full(len(df), np.nan)

    # Walk-forward; refit at OOS_START and every REFIT_INTERVAL thereafter
    oos_idx_list = np.where(oos_mask)[0]
    refit_points = set(oos_idx_list[::REFIT_INTERVAL].tolist())
    # ensure first oos idx in refit set
    refit_points.add(int(oos_idx_list[0]))

    gjr_params = None
    kan_predict = None
    kan_train_logtau_mean = 0.0  # for fallback

    t0 = time.time()
    for i, idx in enumerate(oos_idx_list):
        if int(idx) in refit_points:
            # GJR: expanding window train on r[:idx]
            train_r = r_full[:idx]
            gjr_params = fit_gjr_normal(train_r)
            # KAN: rolling window of WINDOW obs ending at idx-1
            lo = max(0, idx - WINDOW)
            X_tr = X_full[lo:idx]
            # target = log of realized var = log(r^2)+small_floor
            r2_tr = np.maximum(r_full[lo:idx] ** 2, 1e-6)
            y_tr = np.log(r2_tr)
            # smooth target (22d EWMA of log r^2) so KAN learns long-run, not noise
            y_tr_smooth = pd.Series(y_tr).ewm(span=22, adjust=False).mean().values
            kan_predict = fit_kan_longrun(X_tr, y_tr_smooth, in_dim=X_tr.shape[1])
            kan_train_logtau_mean = float(np.mean(y_tr_smooth))
            print(
                f"  [refit @ {df.index[idx].date()}]  GJR ω={gjr_params['omega']:.4f} α={gjr_params['alpha']:.3f} γ={gjr_params['gamma']:.3f} β={gjr_params['beta']:.3f}"
            )

        # GJR one-step forecast: filter from start to idx-1, then forecast idx
        # For efficiency we re-filter only on the train portion + sliding extension
        filt_r = r_full[: idx]
        var_path = gjr_filter(filt_r, gjr_params)
        sig2_gjr[idx] = gjr_one_step_forecast(filt_r, var_path, gjr_params)

        # KAN-GARCH-MIDAS: tau = exp(KAN(macro_{t-1}))
        try:
            x_now = X_full[idx : idx + 1]
            log_tau = float(kan_predict(x_now)[0])
        except Exception:
            log_tau = kan_train_logtau_mean
        tau_t = math.exp(np.clip(log_tau, -8, 8))  # = exp(log_var). Treat as long-run var
        # short-run g: standardize r by sqrt(tau) and run GJR on z; we already have GJR on raw r
        # canonical MIDAS: sigma^2 = g * tau, where g~1 on average. Use g_t = sig2_gjr[idx] / mean(tau)
        # but to keep model stable, use multiplicative scaling: sig2_kan = sig2_gjr_t * (tau_t / running_mean_tau)
        # Approximate running mean of tau via train mean:
        mean_tau_train = math.exp(kan_train_logtau_mean)
        g_t = sig2_gjr[idx] / mean_tau_train  # short-run scaled
        sig2_kan[idx] = g_t * tau_t

        if (i + 1) % 100 == 0:
            print(f"    progress {i+1}/{n_oos}  elapsed={time.time()-t0:.1f}s")

    # Truncate to OOS only, drop NaNs
    oos_proxy = proxy_full[oos_mask]
    oos_gjr = sig2_gjr[oos_mask]
    oos_kan = sig2_kan[oos_mask]
    oos_dates_arr = df.index[oos_mask]

    valid = ~(np.isnan(oos_gjr) | np.isnan(oos_kan))
    oos_proxy = oos_proxy[valid]
    oos_gjr = oos_gjr[valid]
    oos_kan = oos_kan[valid]
    oos_dates_arr = oos_dates_arr[valid]

    qlike_gjr = qlike(oos_proxy, oos_gjr)
    qlike_kan = qlike(oos_proxy, oos_kan)
    rel_impr = (qlike_gjr - qlike_kan) / qlike_gjr

    loss_g = qlike_loss_series(oos_proxy, oos_gjr)
    loss_k = qlike_loss_series(oos_proxy, oos_kan)
    t_stat, p_val = dm_hln(loss_k, loss_g, h=1)

    # sub-period
    sub_split = pd.Timestamp(SUB_PERIOD_SPLIT)
    early = oos_dates_arr < sub_split
    late = ~early

    sub = {}
    for label, mask in [("early_2021_2023", early), ("late_2024_2026", late)]:
        if mask.sum() < 20:
            sub[label] = {"n": int(mask.sum()), "qlike_gjr": None, "qlike_kan": None}
            continue
        qg = qlike(oos_proxy[mask], oos_gjr[mask])
        qk = qlike(oos_proxy[mask], oos_kan[mask])
        sub[label] = {
            "n": int(mask.sum()),
            "qlike_gjr": qg,
            "qlike_kan": qk,
            "kan_better": bool(qk < qg),
            "rel_improvement": (qg - qk) / qg if qg > 0 else None,
        }

    # gates
    gate_dm = bool(abs(t_stat) > 3.0 and t_stat < 0)  # negative => kan better
    gate_rel = bool(rel_impr >= 0.05)
    gate_sub = bool(
        sub.get("early_2021_2023", {}).get("kan_better", False)
        and sub.get("late_2024_2026", {}).get("kan_better", False)
    )
    gates_passed = sum([gate_dm, gate_rel, gate_sub])

    return {
        "asset": asset,
        "n_oos": int(len(oos_proxy)),
        "oos_start": str(oos_dates_arr.min().date()),
        "oos_end": str(oos_dates_arr.max().date()),
        "qlike": {"gjr_baseline": qlike_gjr, "kan_garch_midas": qlike_kan},
        "relative_improvement": float(rel_impr),
        "dm_test_kan_vs_gjr": {
            "t_stat": float(t_stat),
            "p_value": float(p_val),
            "interpretation": "negative t favors KAN",
            "harvey_significant": bool(abs(t_stat) > 3.0),
        },
        "sub_period": sub,
        "gates": {
            "dm_t_gt_3": gate_dm,
            "rel_improvement_5pct": gate_rel,
            "sub_period_stable": gate_sub,
            "passed_count": gates_passed,
        },
        "verdict": (
            "POSITIVE — Paper-3 candidate" if gates_passed == 3 else
            "PARTIAL" if gates_passed >= 2 else
            "NULL — ML ceiling reaffirmed"
        ),
        "_arrays": {
            "dates": [d.strftime("%Y-%m-%d") for d in oos_dates_arr],
            "proxy_r2": oos_proxy.tolist(),
            "sig2_gjr": oos_gjr.tolist(),
            "sig2_kan": oos_kan.tolist(),
        },
    }


# ============================================================
# Plots
# ============================================================
def make_plots(per_asset: dict, results_summary: dict):
    # 1) QLIKE comparison bar chart
    fig, ax = plt.subplots(1, 1, figsize=(7, 4.2))
    assets = list(per_asset.keys())
    qg = [per_asset[a]["qlike"]["gjr_baseline"] for a in assets]
    qk = [per_asset[a]["qlike"]["kan_garch_midas"] for a in assets]
    x = np.arange(len(assets))
    w = 0.35
    ax.bar(x - w / 2, qg, w, label="GJR-GARCH (baseline)", color="#4477AA")
    ax.bar(x + w / 2, qk, w, label="KAN-GARCH-MIDAS", color="#EE6677")
    for i, a in enumerate(assets):
        rel = per_asset[a]["relative_improvement"] * 100
        ax.text(i, max(qg[i], qk[i]) * 1.02, f"Δ={rel:+.2f}%", ha="center", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_ylabel("OOS QLIKE (lower = better)")
    ax.set_title("K1263: KAN-GARCH-MIDAS vs GJR-GARCH baseline (Patton QLIKE on r²)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTDIR / "k1263_qlike_comparison.png", dpi=140)
    plt.close(fig)

    # 2) DM heatmap (t-stat per asset, full + sub-periods)
    fig, ax = plt.subplots(1, 1, figsize=(7, 3.6))
    rows = ["Full OOS", "Early 2021–2023", "Late 2024–2026"]
    M = np.zeros((len(rows), len(assets)))
    for j, a in enumerate(assets):
        r = per_asset[a]
        # Full-OOS: dm_hln returns negative t when challenger (KAN) better.
        # Flip sign so the heatmap convention is uniform: POSITIVE = KAN better.
        M[0, j] = -r["dm_test_kan_vs_gjr"]["t_stat"]
        # recompute sub-period DM via approx using QLIKE diff scaled by sqrt(n) — just reuse cached sub
        for i, key in enumerate(["early_2021_2023", "late_2024_2026"]):
            sub = r["sub_period"].get(key, {})
            qg, qk = sub.get("qlike_gjr"), sub.get("qlike_kan")
            n = sub.get("n", 0)
            if qg is None or qk is None or n < 20:
                M[1 + i, j] = np.nan
            else:
                # rough proxy t = (qk-qg)/(sd/sqrt(n)) — but we don't have per-row losses cached
                # signed rel improvement * sqrt(n) is informative as a heuristic
                M[1 + i, j] = (qg - qk) / qg * math.sqrt(n)
    im = ax.imshow(M, aspect="auto", cmap="RdBu_r", vmin=-4, vmax=4)
    ax.set_xticks(range(len(assets)))
    ax.set_xticklabels(assets)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = M[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=10,
                        color="white" if abs(v) > 2 else "black")
    ax.set_title("K1263: DM-HLN t-stats (full) and √n·rel-impr (sub-periods)\n(positive = KAN better)")
    fig.colorbar(im, ax=ax, label="signed score")
    fig.tight_layout()
    fig.savefig(OUTDIR / "k1263_dm_heatmap.png", dpi=140)
    plt.close(fig)


# ============================================================
# Main
# ============================================================
def main():
    print("K1263: KAN-GARCH-MIDAS — running...")
    print(f"  ASSETS={ASSETS}  OOS={OOS_START}→{DATA_END}  REFIT={REFIT_INTERVAL}  WIN={WINDOW}  SEED={SEED}")
    panels = build_panel()

    per_asset = {}
    for asset in ASSETS:
        per_asset[asset] = run_asset(asset, panels[asset])

    # Strip _arrays from saved JSON to keep file small; save separately
    summary = {
        "experiment_id": "K1263",
        "title": "KAN-GARCH-MIDAS: Can structured Kolmogorov-Arnold Networks break the ML ceiling?",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "data_source": "yfinance",
        "assets": ASSETS,
        "oos_period": f"{OOS_START} to {DATA_END}",
        "config": {
            "refit_interval": REFIT_INTERVAL,
            "window": WINDOW,
            "seed": SEED,
            "macro_features": ["vix(t-1)", "term_spread(t-1)", "credit_proxy(t-1)", "rv22(t-1)"],
            "lookahead_protection": "all macro X shifted by 1 day before walk-forward",
        },
        "models": {
            "baseline": "GJR-GARCH-Normal (expanding window, scipy MLE)",
            "challenger": "KAN-GARCH-MIDAS (pykan width=[d,3,1] grid=5 k=3, log-var target, EWMA-22 smoothed)",
        },
        "references": [
            "Liu Z. et al. (2024), 'KAN: Kolmogorov-Arnold Networks', arXiv:2404.19756",
            "Engle, Ghysels, Sohn (2013), Stock Market Volatility and Macroeconomic Fundamentals, RES",
            "Patton (2011), Volatility forecast comparison using imperfect proxies, J. Econometrics",
            "Harvey, Liu, Zhu (2016), ...and the cross-section of expected returns, RFS",
            "Diebold & Mariano (1995); Harvey-Leybourne-Newbold (1997)",
        ],
        "per_asset": {a: {k: v for k, v in r.items() if k != "_arrays"} for a, r in per_asset.items()},
    }
    # cross-asset verdict
    pos_count = sum(1 for a in ASSETS if per_asset[a]["gates"]["passed_count"] == 3)
    summary["overall_verdict"] = (
        "POSITIVE on all assets" if pos_count == len(ASSETS)
        else f"POSITIVE on {pos_count}/{len(ASSETS)}" if pos_count >= 1
        else "NULL — ML ceiling reaffirmed (7th time)"
    )

    out_json = OUTDIR / "k1263_results.json"
    out_json.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n  wrote {out_json}")

    # Plot
    make_plots(per_asset, summary)
    print(f"  wrote {OUTDIR / 'k1263_qlike_comparison.png'}")
    print(f"  wrote {OUTDIR / 'k1263_dm_heatmap.png'}")

    # Print verdict
    print("\n=== K1263 VERDICT ===")
    for a in ASSETS:
        r = per_asset[a]
        print(
            f"  {a}: QLIKE GJR={r['qlike']['gjr_baseline']:.4f}  KAN={r['qlike']['kan_garch_midas']:.4f}  "
            f"Δ={r['relative_improvement']*100:+.2f}%  "
            f"DM t={r['dm_test_kan_vs_gjr']['t_stat']:+.2f} (p={r['dm_test_kan_vs_gjr']['p_value']:.3f})  "
            f"gates={r['gates']['passed_count']}/3  → {r['verdict']}"
        )
    print(f"\n  Overall: {summary['overall_verdict']}")


if __name__ == "__main__":
    main()
