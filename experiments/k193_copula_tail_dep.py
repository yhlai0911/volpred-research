"""
K193: Dynamic Copula Tail Dependence and Volatility Prediction
================================================================
[提出: 用戶, 執行: Claude]

Background:
  K160 studied static copula. This extends to TIME-VARYING tail dependence:
  does increasing lower tail dependence between SPY-TLT predict future vol?
  The SPY-TLT correlation breakdown (T19) might show up in tail dependence
  BEFORE it shows in correlation.

Hypothesis:
  Tail Dependence Asymmetry (TDA = lambda_L - lambda_U) captures crash
  co-movement vs rally co-movement. When TDA increases (more crash
  co-movement), future volatility should increase.

Research Questions:
  1. Does rolling tail dependence vary meaningfully over time?
  2. Does TDA predict future 22-day realized vol?
  3. Does TDA add information beyond VIX? (partial r|VIX)
  4. Is there a structural break in SPY-TLT tail dependence around 2022?
  5. Can GARCH-X with TDA improve vol forecasts? (DM test)

Method:
  a. Rolling 252-day empirical tail dependence (rank-based, no parametric)
  b. Lower tail: lambda_L = P(U2 < q | U1 < q), q = 0.05, 0.10
  c. Upper tail: lambda_U = P(U2 > 1-q | U1 > 1-q)
  d. TDA = lambda_L - lambda_U
  e. Cross-pair: SPY-TLT, SPY-GLD, SPY-QQQ, QQQ-TLT
  f. Correlation with future 22-day RV, partial r|VIX
  g. GARCH-X with TDA as exogenous, DM test vs baseline GJR
  h. OOS: 2023-2024

Statistical requirements:
  - DM test for forecast comparison
  - Partial correlation controlling for VIX
  - Harvey (2016) threshold for strategy claims
  - Cross-pair validation (not just SPY-TLT)

Data: SPY, TLT, GLD, QQQ daily returns from yfinance.

Usage:
    uv run python experiments/k193_copula_tail_dep.py
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
from scipy import stats

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ======================================================================
# CONFIG
# ======================================================================
TICKERS = ["SPY", "TLT", "GLD", "QQQ"]
VIX_TICKER = "^VIX"
DATA_START = "2005-01-01"
DATA_END = "2026-03-24"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"

ROLLING_WINDOW = 252  # 1-year rolling window for tail dependence
QUANTILES = [0.05, 0.10]  # tail quantile thresholds
GARCH_WINDOW = 2000
REFIT_FREQ = 22  # monthly refit for GARCH

# Asset pairs to test
PAIRS = [
    ("SPY", "TLT"),
    ("SPY", "GLD"),
    ("SPY", "QQQ"),
    ("QQQ", "TLT"),
]

print("=" * 80)
print("K193: Dynamic Copula Tail Dependence and Volatility Prediction")
print("=" * 80)
print(f"  [提出: 用戶, 執行: Claude]")
print(f"  Data: {DATA_START} to {DATA_END}")
print(f"  OOS:  {OOS_START} to {OOS_END}")
print(f"  Rolling window: {ROLLING_WINDOW} days")
print(f"  Tail quantiles: {QUANTILES}")
print(f"  Pairs: {[f'{a}-{b}' for a, b in PAIRS]}")
print()


# ======================================================================
# 1. DATA LOADING
# ======================================================================
def load_data():
    """Load price data from yfinance."""
    import yfinance as yf

    print("[1] Loading data from yfinance...")
    all_tickers = TICKERS + [VIX_TICKER]
    data = yf.download(all_tickers, start=DATA_START, end=DATA_END, progress=False)

    # Handle MultiIndex columns
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data

    # Rename ^VIX
    if "^VIX" in close.columns:
        close = close.rename(columns={"^VIX": "VIX"})

    close = close.dropna()

    # Compute returns
    returns = close.pct_change().dropna()
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()

    print(f"  Data range: {close.index[0].date()} to {close.index[-1].date()}")
    print(f"  Total observations: {len(returns)}")
    for t in TICKERS:
        if t in returns.columns:
            print(f"    {t}: mean={returns[t].mean()*252:.1%}, vol={returns[t].std()*np.sqrt(252):.1%}")
    print()

    return close, returns


# ======================================================================
# 2. EMPIRICAL TAIL DEPENDENCE
# ======================================================================
def compute_empirical_tail_dep(u1: np.ndarray, u2: np.ndarray, q: float) -> tuple[float, float]:
    """
    Compute empirical lower and upper tail dependence coefficients.

    Lower tail: lambda_L = P(U2 < q | U1 < q)
    Upper tail: lambda_U = P(U2 > 1-q | U1 > 1-q)

    Uses rank-based pseudo-observations (empirical copula).
    """
    n = len(u1)

    # Lower tail
    lower_mask_1 = u1 < q
    n_lower_1 = lower_mask_1.sum()
    if n_lower_1 > 0:
        lambda_L = (u2[lower_mask_1] < q).sum() / n_lower_1
    else:
        lambda_L = np.nan

    # Upper tail
    upper_mask_1 = u1 > (1 - q)
    n_upper_1 = upper_mask_1.sum()
    if n_upper_1 > 0:
        lambda_U = (u2[upper_mask_1] > (1 - q)).sum() / n_upper_1
    else:
        lambda_U = np.nan

    return lambda_L, lambda_U


def compute_rolling_tail_dep(returns: pd.DataFrame, pair: tuple[str, str],
                              window: int, q: float) -> pd.DataFrame:
    """
    Compute rolling tail dependence for a pair of assets.
    Uses rank-based pseudo-observations within each rolling window.
    """
    a, b = pair
    r1 = returns[a].values
    r2 = returns[b].values
    idx = returns.index
    n = len(r1)

    lambda_L_arr = np.full(n, np.nan)
    lambda_U_arr = np.full(n, np.nan)
    tda_arr = np.full(n, np.nan)
    corr_arr = np.full(n, np.nan)

    for i in range(window, n):
        # Rolling window
        r1_w = r1[i - window:i]
        r2_w = r2[i - window:i]

        # Convert to pseudo-observations (ranks / (n+1))
        u1 = stats.rankdata(r1_w) / (window + 1)
        u2 = stats.rankdata(r2_w) / (window + 1)

        lam_L, lam_U = compute_empirical_tail_dep(u1, u2, q)
        lambda_L_arr[i] = lam_L
        lambda_U_arr[i] = lam_U
        tda_arr[i] = lam_L - lam_U

        # Also compute rolling correlation for comparison
        corr_arr[i] = np.corrcoef(r1_w, r2_w)[0, 1]

    result = pd.DataFrame({
        f"lambda_L_{a}_{b}": lambda_L_arr,
        f"lambda_U_{a}_{b}": lambda_U_arr,
        f"TDA_{a}_{b}": tda_arr,
        f"corr_{a}_{b}": corr_arr,
    }, index=idx)

    return result.dropna()


# ======================================================================
# 3. TAIL DEPENDENCE ANALYSIS
# ======================================================================
def analyze_tail_dependence(returns: pd.DataFrame, vix: pd.Series):
    """Main analysis of tail dependence dynamics and vol prediction."""

    print("[2] Computing rolling tail dependence...")
    print()

    all_results = {}

    for q in QUANTILES:
        print(f"  === Quantile q = {q} ===")

        for pair in PAIRS:
            a, b = pair
            pair_name = f"{a}-{b}"

            td = compute_rolling_tail_dep(returns, pair, ROLLING_WINDOW, q)
            tda_col = f"TDA_{a}_{b}"
            lam_L_col = f"lambda_L_{a}_{b}"
            lam_U_col = f"lambda_U_{a}_{b}"
            corr_col = f"corr_{a}_{b}"

            # Summary statistics
            tda = td[tda_col]
            lam_L = td[lam_L_col]
            lam_U = td[lam_U_col]

            print(f"\n  {pair_name} (q={q}):")
            print(f"    lambda_L: mean={lam_L.mean():.4f}, std={lam_L.std():.4f}, "
                  f"range=[{lam_L.min():.4f}, {lam_L.max():.4f}]")
            print(f"    lambda_U: mean={lam_U.mean():.4f}, std={lam_U.std():.4f}, "
                  f"range=[{lam_U.min():.4f}, {lam_U.max():.4f}]")
            print(f"    TDA:      mean={tda.mean():.4f}, std={tda.std():.4f}")

            # Test if TDA is significantly different from zero
            tda_t, tda_p = stats.ttest_1samp(tda.dropna(), 0)
            print(f"    TDA != 0: t={tda_t:.3f}, p={tda_p:.4f} "
                  f"({'***' if tda_p < 0.001 else '**' if tda_p < 0.01 else '*' if tda_p < 0.05 else 'NS'})")

            # --- Prediction of future vol ---
            # Future 22-day realized vol (annualized)
            spy_ret = returns["SPY"]
            future_rv = spy_ret.rolling(22).std().shift(-22) * np.sqrt(252)
            future_rv = future_rv.reindex(tda.index)

            # Align
            aligned = pd.DataFrame({
                "TDA": tda,
                "lambda_L": lam_L,
                "lambda_U": lam_U,
                "corr": td[corr_col],
                "future_rv": future_rv,
            }).dropna()

            if len(aligned) < 100:
                print(f"    SKIP: insufficient aligned data ({len(aligned)} obs)")
                continue

            # --- Full sample correlation ---
            r_tda_rv = aligned["TDA"].corr(aligned["future_rv"])
            r_lamL_rv = aligned["lambda_L"].corr(aligned["future_rv"])
            r_lamU_rv = aligned["lambda_U"].corr(aligned["future_rv"])
            r_corr_rv = aligned["corr"].corr(aligned["future_rv"])

            # t-stats for correlations
            n_obs = len(aligned)
            t_tda = r_tda_rv * np.sqrt(n_obs - 2) / np.sqrt(1 - r_tda_rv**2)
            p_tda = 2 * stats.t.sf(abs(t_tda), n_obs - 2)

            print(f"\n    Full-sample predictive correlations (n={n_obs}):")
            print(f"      r(TDA, future_RV)      = {r_tda_rv:+.4f} (t={t_tda:.2f}, p={p_tda:.4f})")
            print(f"      r(lambda_L, future_RV) = {r_lamL_rv:+.4f}")
            print(f"      r(lambda_U, future_RV) = {r_lamU_rv:+.4f}")
            print(f"      r(corr, future_RV)     = {r_corr_rv:+.4f}")

            # --- Partial correlation controlling for VIX ---
            vix_aligned = vix.reindex(aligned.index)
            aligned_vix = aligned.copy()
            aligned_vix["VIX"] = vix_aligned
            aligned_vix = aligned_vix.dropna()

            if len(aligned_vix) > 100:
                # Partial r(TDA, future_RV | VIX)
                from numpy.linalg import lstsq

                # Regress TDA on VIX, get residuals
                X_vix = np.column_stack([np.ones(len(aligned_vix)), aligned_vix["VIX"].values])
                tda_resid = aligned_vix["TDA"].values - X_vix @ lstsq(X_vix, aligned_vix["TDA"].values, rcond=None)[0]
                rv_resid = aligned_vix["future_rv"].values - X_vix @ lstsq(X_vix, aligned_vix["future_rv"].values, rcond=None)[0]

                partial_r = np.corrcoef(tda_resid, rv_resid)[0, 1]
                n_p = len(aligned_vix)
                t_partial = partial_r * np.sqrt(n_p - 3) / np.sqrt(1 - partial_r**2)
                p_partial = 2 * stats.t.sf(abs(t_partial), n_p - 3)

                # Also partial r for lambda_L
                lamL_resid = aligned_vix["lambda_L"].values - X_vix @ lstsq(X_vix, aligned_vix["lambda_L"].values, rcond=None)[0]
                partial_r_lamL = np.corrcoef(lamL_resid, rv_resid)[0, 1]

                # Also: r(VIX, future_RV) for comparison
                r_vix_rv = aligned_vix["VIX"].corr(aligned_vix["future_rv"])

                print(f"\n    Partial correlations (controlling for VIX, n={n_p}):")
                print(f"      partial r(TDA, future_RV | VIX)      = {partial_r:+.4f} (t={t_partial:.2f}, p={p_partial:.4f})")
                print(f"      partial r(lambda_L, future_RV | VIX) = {partial_r_lamL:+.4f}")
                print(f"      r(VIX, future_RV)                    = {r_vix_rv:+.4f}")

            else:
                partial_r = np.nan
                t_partial = np.nan
                p_partial = np.nan
                r_vix_rv = np.nan

            # --- OOS analysis ---
            oos_mask = (aligned.index >= OOS_START) & (aligned.index <= OOS_END)
            oos = aligned[oos_mask]

            if len(oos) > 50:
                r_oos = oos["TDA"].corr(oos["future_rv"])
                n_oos = len(oos)
                t_oos = r_oos * np.sqrt(n_oos - 2) / np.sqrt(max(1 - r_oos**2, 1e-10))
                p_oos = 2 * stats.t.sf(abs(t_oos), n_oos - 2)

                print(f"\n    OOS ({OOS_START} to {OOS_END}, n={n_oos}):")
                print(f"      r(TDA, future_RV) = {r_oos:+.4f} (t={t_oos:.2f}, p={p_oos:.4f})")

                # OOS partial r|VIX
                oos_vix = aligned_vix[oos_mask] if len(aligned_vix) > 0 else pd.DataFrame()
                if len(oos_vix) > 30:
                    X_v = np.column_stack([np.ones(len(oos_vix)), oos_vix["VIX"].values])
                    tda_r_oos = oos_vix["TDA"].values - X_v @ lstsq(X_v, oos_vix["TDA"].values, rcond=None)[0]
                    rv_r_oos = oos_vix["future_rv"].values - X_v @ lstsq(X_v, oos_vix["future_rv"].values, rcond=None)[0]
                    partial_r_oos = np.corrcoef(tda_r_oos, rv_r_oos)[0, 1]
                    print(f"      partial r(TDA, future_RV | VIX) OOS = {partial_r_oos:+.4f}")
                else:
                    partial_r_oos = np.nan
            else:
                r_oos = np.nan
                t_oos = np.nan
                p_oos = np.nan
                partial_r_oos = np.nan

            # Store results
            key = f"{pair_name}_q{q}"
            all_results[key] = {
                "pair": pair_name,
                "quantile": q,
                "n_obs": n_obs,
                "lambda_L_mean": float(lam_L.mean()),
                "lambda_L_std": float(lam_L.std()),
                "lambda_U_mean": float(lam_U.mean()),
                "lambda_U_std": float(lam_U.std()),
                "TDA_mean": float(tda.mean()),
                "TDA_std": float(tda.std()),
                "TDA_tstat": float(tda_t),
                "TDA_pval": float(tda_p),
                "r_TDA_futureRV": float(r_tda_rv),
                "t_TDA_futureRV": float(t_tda),
                "p_TDA_futureRV": float(p_tda),
                "r_lamL_futureRV": float(r_lamL_rv),
                "r_lamU_futureRV": float(r_lamU_rv),
                "r_corr_futureRV": float(r_corr_rv),
                "partial_r_TDA_VIX": float(partial_r) if not np.isnan(partial_r) else None,
                "t_partial_TDA_VIX": float(t_partial) if not np.isnan(t_partial) else None,
                "p_partial_TDA_VIX": float(p_partial) if not np.isnan(p_partial) else None,
                "r_VIX_futureRV": float(r_vix_rv) if not np.isnan(r_vix_rv) else None,
                "r_TDA_OOS": float(r_oos) if not np.isnan(r_oos) else None,
                "t_TDA_OOS": float(t_oos) if not np.isnan(t_oos) else None,
                "p_TDA_OOS": float(p_oos) if not np.isnan(p_oos) else None,
                "partial_r_TDA_OOS": float(partial_r_oos) if not np.isnan(partial_r_oos) else None,
            }

    return all_results


# ======================================================================
# 4. TDA REGIME ANALYSIS
# ======================================================================
def tda_regime_analysis(returns: pd.DataFrame, vix: pd.Series):
    """Analyze vol regimes conditional on TDA levels."""
    print("\n" + "=" * 60)
    print("[3] TDA Regime Analysis")
    print("=" * 60)

    q = 0.10  # Use q=0.10 for more observations
    pair = ("SPY", "TLT")
    a, b = pair

    td = compute_rolling_tail_dep(returns, pair, ROLLING_WINDOW, q)
    tda = td[f"TDA_{a}_{b}"]

    # Future 22-day RV
    spy_ret = returns["SPY"]
    future_rv = spy_ret.rolling(22).std().shift(-22) * np.sqrt(252)

    aligned = pd.DataFrame({
        "TDA": tda,
        "future_rv": future_rv.reindex(tda.index),
        "VIX": vix.reindex(tda.index),
    }).dropna()

    # Tercile analysis
    aligned["TDA_tercile"] = pd.qcut(aligned["TDA"], 3, labels=["Low", "Mid", "High"])

    print(f"\n  SPY-TLT TDA tercile analysis (q={q}, n={len(aligned)}):")
    print(f"  {'Tercile':<8} {'Mean RV':>10} {'Std RV':>10} {'Mean VIX':>10} {'Mean TDA':>10} {'N':>6}")

    regime_results = {}
    for tercile in ["Low", "Mid", "High"]:
        sub = aligned[aligned["TDA_tercile"] == tercile]
        regime_results[tercile] = {
            "mean_rv": float(sub["future_rv"].mean()),
            "std_rv": float(sub["future_rv"].std()),
            "mean_vix": float(sub["VIX"].mean()),
            "mean_tda": float(sub["TDA"].mean()),
            "n": int(len(sub)),
        }
        print(f"  {tercile:<8} {sub['future_rv'].mean():>10.4f} {sub['future_rv'].std():>10.4f} "
              f"{sub['VIX'].mean():>10.2f} {sub['TDA'].mean():>+10.4f} {len(sub):>6}")

    # High vs Low t-test
    high = aligned[aligned["TDA_tercile"] == "High"]["future_rv"]
    low = aligned[aligned["TDA_tercile"] == "Low"]["future_rv"]
    t_hl, p_hl = stats.ttest_ind(high, low, equal_var=False)
    print(f"\n  High vs Low TDA: t={t_hl:.3f}, p={p_hl:.4f} "
          f"({'***' if p_hl < 0.001 else '**' if p_hl < 0.01 else '*' if p_hl < 0.05 else 'NS'})")

    # --- Structural break: pre/post 2022 ---
    print(f"\n  Structural break analysis (2022 = rate hike regime):")
    break_date = "2022-01-01"
    pre = aligned[aligned.index < break_date]
    post = aligned[aligned.index >= break_date]

    if len(pre) > 50 and len(post) > 50:
        print(f"    Pre-2022  (n={len(pre):4d}): TDA mean={pre['TDA'].mean():+.4f}, std={pre['TDA'].std():.4f}")
        print(f"    Post-2022 (n={len(post):4d}): TDA mean={post['TDA'].mean():+.4f}, std={post['TDA'].std():.4f}")

        t_break, p_break = stats.ttest_ind(pre["TDA"], post["TDA"], equal_var=False)
        print(f"    Structural break test: t={t_break:.3f}, p={p_break:.4f} "
              f"({'***' if p_break < 0.001 else '**' if p_break < 0.01 else '*' if p_break < 0.05 else 'NS'})")

        # Also compare correlation pre/post
        corr_col = f"corr_{a}_{b}"
        td_aligned = td.reindex(aligned.index)
        pre_corr = td_aligned.loc[td_aligned.index < break_date, corr_col].mean()
        post_corr = td_aligned.loc[td_aligned.index >= break_date, corr_col].mean()
        print(f"    Pre-2022  correlation: {pre_corr:+.4f}")
        print(f"    Post-2022 correlation: {post_corr:+.4f}")
        print(f"    Correlation shift: {post_corr - pre_corr:+.4f}")

        regime_results["structural_break"] = {
            "pre_TDA_mean": float(pre["TDA"].mean()),
            "post_TDA_mean": float(post["TDA"].mean()),
            "t_break": float(t_break),
            "p_break": float(p_break),
            "pre_corr": float(pre_corr),
            "post_corr": float(post_corr),
        }
    else:
        print(f"    Insufficient data for structural break analysis")

    regime_results["high_vs_low_t"] = float(t_hl)
    regime_results["high_vs_low_p"] = float(p_hl)

    return regime_results


# ======================================================================
# 5. GARCH-X WITH TDA (Two-stage approach)
# ======================================================================
def garch_x_with_tda(returns: pd.DataFrame, vix: pd.Series):
    """
    Test if TDA improves vol forecasts beyond GJR-GARCH.

    Two-stage approach:
    Stage 1: Fit GJR-GARCH(1,1), get conditional variance forecast h_t
    Stage 2: Regress realized variance on h_t and TDA_{t-1}:
             sigma^2_t = alpha + beta1*h_t + beta2*TDA_{t-1} + eps_t
    If beta2 is significant, TDA adds info beyond GARCH.

    Walk-forward OOS: refit every 22 days, forecast 1-step ahead.
    DM test compares QLIKE of baseline (GARCH only) vs augmented (GARCH + TDA).
    """
    from arch import arch_model

    print("\n" + "=" * 60)
    print("[4] GARCH + TDA Two-Stage Vol Forecast (Diebold-Mariano Test)")
    print("=" * 60)

    q = 0.10
    spy_ret = returns["SPY"] * 100  # percentage returns for GARCH

    garch_results = {}

    for pair in PAIRS:
        a, b = pair
        pair_name = f"{a}-{b}"

        td = compute_rolling_tail_dep(returns, pair, ROLLING_WINDOW, q)
        tda = td[f"TDA_{a}_{b}"]

        # Align data
        aligned_idx = spy_ret.index.intersection(tda.dropna().index)
        spy_aligned = spy_ret.reindex(aligned_idx)
        tda_aligned = tda.reindex(aligned_idx)
        vix_aligned = vix.reindex(aligned_idx)

        # Drop any remaining NaN
        mask = spy_aligned.notna() & tda_aligned.notna() & vix_aligned.notna()
        spy_aligned = spy_aligned[mask]
        tda_aligned = tda_aligned[mask]
        vix_aligned = vix_aligned[mask]

        if len(spy_aligned) < GARCH_WINDOW + 252:
            print(f"\n  {pair_name}: SKIP (insufficient data: {len(spy_aligned)} obs)")
            continue

        # OOS period
        oos_mask = (spy_aligned.index >= OOS_START) & (spy_aligned.index <= OOS_END)
        oos_dates = spy_aligned.index[oos_mask]
        if len(oos_dates) < 100:
            print(f"\n  {pair_name}: SKIP OOS (only {len(oos_dates)} obs)")
            continue

        print(f"\n  {pair_name} (q={q}):")

        # Walk-forward forecasting
        realized_var = (spy_aligned / 100) ** 2  # squared returns as vol proxy
        all_idx = spy_aligned.index

        fc_baseline = pd.Series(dtype=float, index=oos_dates)
        fc_augmented = pd.Series(dtype=float, index=oos_dates)

        successful_baseline = 0
        successful_augmented = 0
        last_garch_res = None
        last_reg_coefs = None  # [alpha, beta1, beta2] for augmented model
        last_tda_mean = 0.0
        last_tda_std = 1.0

        for i, date in enumerate(oos_dates):
            pos = all_idx.get_loc(date)

            if i % REFIT_FREQ == 0:
                # Refit
                start_pos = max(0, pos - GARCH_WINDOW)
                train_ret = spy_aligned.iloc[start_pos:pos]
                train_rv = realized_var.iloc[start_pos:pos]
                train_tda = tda_aligned.iloc[start_pos:pos]

                if len(train_ret) < 500:
                    continue

                # Stage 1: Fit GJR-GARCH
                try:
                    model = arch_model(train_ret, vol="GARCH", p=1, o=1, q=1, dist="t")
                    res = model.fit(disp="off", show_warning=False)
                    last_garch_res = res

                    # Get in-sample conditional variance
                    cond_var = res.conditional_volatility ** 2  # h_t in % squared

                    # Stage 2: Regress next-day RV on h_t and TDA_t
                    # y = RV_{t+1}, x = [1, h_t, TDA_t]
                    # Use 1-day ahead alignment
                    rv_next = (train_rv * 10000).shift(-1)  # to % squared, shift forward

                    # Standardize TDA
                    tda_mean = train_tda.mean()
                    tda_std = train_tda.std()
                    if tda_std < 1e-10:
                        tda_std = 1.0
                    tda_std_vals = (train_tda - tda_mean) / tda_std

                    last_tda_mean = tda_mean
                    last_tda_std = tda_std

                    # Align
                    reg_df = pd.DataFrame({
                        "rv_next": rv_next,
                        "h_t": cond_var,
                        "tda_t": tda_std_vals,
                    }).dropna()

                    if len(reg_df) > 100:
                        from numpy.linalg import lstsq as np_lstsq
                        X_aug = np.column_stack([
                            np.ones(len(reg_df)),
                            reg_df["h_t"].values,
                            reg_df["tda_t"].values,
                        ])
                        y_reg = reg_df["rv_next"].values
                        coefs = np_lstsq(X_aug, y_reg, rcond=None)[0]
                        last_reg_coefs = coefs  # [alpha, beta_h, beta_tda]
                    else:
                        last_reg_coefs = None
                except Exception as e:
                    last_garch_res = None
                    last_reg_coefs = None

            # Generate forecasts
            if last_garch_res is not None:
                try:
                    fc = last_garch_res.forecast(horizon=1, reindex=False)
                    h_forecast = fc.variance.values[-1, 0]  # 1-step conditional var in % sq
                    fc_baseline.iloc[i] = h_forecast
                    successful_baseline += 1

                    # Augmented forecast
                    if last_reg_coefs is not None:
                        tda_val = (tda_aligned.iloc[pos] - last_tda_mean) / last_tda_std
                        augmented_fc = (last_reg_coefs[0]
                                       + last_reg_coefs[1] * h_forecast
                                       + last_reg_coefs[2] * tda_val)
                        # Floor at small positive value
                        augmented_fc = max(augmented_fc, 0.001)
                        fc_augmented.iloc[i] = augmented_fc
                        successful_augmented += 1
                except Exception:
                    pass

        # Clean up
        valid = fc_baseline.notna() & fc_augmented.notna()
        if valid.sum() < 50:
            print(f"    Too few valid forecasts: baseline={successful_baseline}, augmented={successful_augmented}")
            garch_results[pair_name] = {"status": "insufficient_forecasts"}
            continue

        fc_b = fc_baseline[valid]
        fc_a = fc_augmented[valid]
        rv = realized_var.reindex(fc_b.index) * 10000  # to percentage squared

        print(f"    Forecasts generated: baseline={successful_baseline}, augmented={successful_augmented}")
        print(f"    Valid aligned forecasts: {valid.sum()}")

        # QLIKE loss
        # Guard against log(0) or division by 0
        fc_b_safe = fc_b.clip(lower=1e-6)
        fc_a_safe = fc_a.clip(lower=1e-6)
        rv_safe = rv.clip(lower=1e-10)

        qlike_base = np.log(fc_b_safe) + rv_safe / fc_b_safe
        qlike_aug = np.log(fc_a_safe) + rv_safe / fc_a_safe

        # Filter out any infinities
        finite_mask = np.isfinite(qlike_base) & np.isfinite(qlike_aug)
        qlike_base = qlike_base[finite_mask]
        qlike_aug = qlike_aug[finite_mask]

        if len(qlike_base) < 50:
            print(f"    Too few finite QLIKE values: {len(qlike_base)}")
            garch_results[pair_name] = {"status": "insufficient_qlike"}
            continue

        mean_qlike_base = qlike_base.mean()
        mean_qlike_aug = qlike_aug.mean()

        print(f"\n    QLIKE (lower is better):")
        print(f"      Baseline GJR:     {mean_qlike_base:.6f}")
        print(f"      GJR + TDA (aug):  {mean_qlike_aug:.6f}")
        print(f"      Improvement:      {(mean_qlike_base - mean_qlike_aug):+.6f} ({(mean_qlike_base - mean_qlike_aug)/abs(mean_qlike_base)*100:+.2f}%)")

        # Diebold-Mariano test
        d = qlike_base - qlike_aug  # positive = augmented is better
        d_mean = d.mean()
        d_std = d.std()

        if d_std > 0 and len(d) > 10:
            # HAC standard error (Newey-West with bandwidth ~ n^(1/3))
            n_dm = len(d)
            bandwidth = int(np.ceil(n_dm**(1/3)))

            # Newey-West HAC
            gamma_0 = np.var(d, ddof=1)
            hac_var = gamma_0
            d_demeaned = d - d.mean()
            for k in range(1, bandwidth + 1):
                gamma_k = np.mean(d_demeaned.values[k:] * d_demeaned.values[:-k])
                weight = 1 - k / (bandwidth + 1)
                hac_var += 2 * weight * gamma_k

            dm_stat = d_mean / np.sqrt(max(hac_var / n_dm, 1e-20))
            dm_pval = 2 * stats.norm.sf(abs(dm_stat))

            print(f"\n    Diebold-Mariano test (HAC, bandwidth={bandwidth}):")
            print(f"      DM stat = {dm_stat:+.4f}")
            print(f"      p-value = {dm_pval:.4f} "
                  f"({'***' if dm_pval < 0.001 else '**' if dm_pval < 0.01 else '*' if dm_pval < 0.05 else 'NS'})")
            print(f"      Direction: {'Augmented better' if dm_stat > 0 else 'Baseline better'}")
        else:
            dm_stat = np.nan
            dm_pval = np.nan
            print(f"    DM test: could not compute (d_std={d_std:.6f})")

        # MSE comparison
        mse_base = ((fc_b - rv)**2).mean()
        mse_aug = ((fc_a - rv)**2).mean()
        print(f"\n    MSE:")
        print(f"      Baseline:  {mse_base:.6f}")
        print(f"      Augmented: {mse_aug:.6f}")

        # Last stage-2 regression coefficients
        if last_reg_coefs is not None:
            print(f"\n    Last stage-2 regression coefs:")
            print(f"      alpha (intercept) = {last_reg_coefs[0]:.6f}")
            print(f"      beta_h (GARCH)    = {last_reg_coefs[1]:.6f}")
            print(f"      beta_TDA          = {last_reg_coefs[2]:.6f}")

        garch_results[pair_name] = {
            "n_valid": int(valid.sum()),
            "qlike_baseline": float(mean_qlike_base),
            "qlike_augmented": float(mean_qlike_aug),
            "qlike_improvement_pct": float((mean_qlike_base - mean_qlike_aug)/abs(mean_qlike_base)*100),
            "dm_stat": float(dm_stat) if not np.isnan(dm_stat) else None,
            "dm_pval": float(dm_pval) if not np.isnan(dm_pval) else None,
            "mse_baseline": float(mse_base),
            "mse_augmented": float(mse_aug),
            "beta_tda_last": float(last_reg_coefs[2]) if last_reg_coefs is not None else None,
        }

    return garch_results


# ======================================================================
# 6. CROSS-PAIR TAIL DEPENDENCE COMPARISON
# ======================================================================
def cross_pair_comparison(returns: pd.DataFrame, vix: pd.Series):
    """Compare tail dependence dynamics across multiple pairs."""
    print("\n" + "=" * 60)
    print("[5] Cross-Pair TDA Comparison")
    print("=" * 60)

    q = 0.10
    spy_ret = returns["SPY"]
    future_rv = spy_ret.rolling(22).std().shift(-22) * np.sqrt(252)

    print(f"\n  {'Pair':<12} {'r(TDA,RV)':<12} {'partial r|VIX':<14} {'TDA mean':<12} {'TDA std':<12} {'lambda_L':<12} {'Asymmetry?':<12}")

    cross_results = {}
    for pair in PAIRS:
        a, b = pair
        pair_name = f"{a}-{b}"

        td = compute_rolling_tail_dep(returns, pair, ROLLING_WINDOW, q)
        tda = td[f"TDA_{a}_{b}"]
        lam_L = td[f"lambda_L_{a}_{b}"]

        aligned = pd.DataFrame({
            "TDA": tda,
            "future_rv": future_rv.reindex(tda.index),
            "VIX": vix.reindex(tda.index),
        }).dropna()

        if len(aligned) < 100:
            continue

        r_raw = aligned["TDA"].corr(aligned["future_rv"])

        # Partial r
        from numpy.linalg import lstsq
        X_v = np.column_stack([np.ones(len(aligned)), aligned["VIX"].values])
        tda_r = aligned["TDA"].values - X_v @ lstsq(X_v, aligned["TDA"].values, rcond=None)[0]
        rv_r = aligned["future_rv"].values - X_v @ lstsq(X_v, aligned["future_rv"].values, rcond=None)[0]
        partial_r = np.corrcoef(tda_r, rv_r)[0, 1]

        tda_mean = tda.mean()
        tda_std = tda.std()
        lamL_mean = lam_L.mean()

        # Is TDA significantly != 0?
        asym = "YES" if abs(tda_mean) > 2 * tda.std() / np.sqrt(len(tda)) else "no"

        print(f"  {pair_name:<12} {r_raw:+.4f}      {partial_r:+.4f}         {tda_mean:+.4f}      {tda_std:.4f}      {lamL_mean:.4f}      {asym}")

        cross_results[pair_name] = {
            "r_TDA_RV": float(r_raw),
            "partial_r_TDA_VIX": float(partial_r),
            "TDA_mean": float(tda_mean),
            "TDA_std": float(tda_std),
            "lambda_L_mean": float(lamL_mean),
            "significant_asymmetry": asym == "YES",
        }

    return cross_results


# ======================================================================
# 7. TDA LEADING INDICATOR TEST
# ======================================================================
def tda_leading_indicator(returns: pd.DataFrame, vix: pd.Series):
    """
    Test if TDA changes lead correlation changes.
    Does TDA increase BEFORE correlation breakdown?
    """
    print("\n" + "=" * 60)
    print("[6] TDA as Leading Indicator of Correlation Breakdown")
    print("=" * 60)

    q = 0.10
    pair = ("SPY", "TLT")
    a, b = pair

    td = compute_rolling_tail_dep(returns, pair, ROLLING_WINDOW, q)
    tda = td[f"TDA_{a}_{b}"]
    corr = td[f"corr_{a}_{b}"]

    # Compute changes
    tda_change = tda.diff(22)  # 1-month change in TDA
    corr_change = corr.diff(22)  # 1-month change in correlation

    aligned = pd.DataFrame({
        "tda_change": tda_change,
        "corr_change_future": corr_change.shift(-22),  # future corr change
        "corr_change_now": corr_change,
    }).dropna()

    if len(aligned) < 100:
        print("  Insufficient data for lead-lag analysis")
        return {}

    # Does TDA change predict future correlation change?
    r_lead = aligned["tda_change"].corr(aligned["corr_change_future"])
    r_contemp = aligned["tda_change"].corr(aligned["corr_change_now"])

    n_ll = len(aligned)
    t_lead = r_lead * np.sqrt(n_ll - 2) / np.sqrt(max(1 - r_lead**2, 1e-10))
    p_lead = 2 * stats.t.sf(abs(t_lead), n_ll - 2)

    print(f"\n  SPY-TLT TDA change → Correlation change (n={n_ll}):")
    print(f"    r(ΔTDA_t, Δcorr_{'{t+22}'}) = {r_lead:+.4f} (t={t_lead:.2f}, p={p_lead:.4f}) [LEADING]")
    print(f"    r(ΔTDA_t, Δcorr_t)      = {r_contemp:+.4f} [CONTEMPORANEOUS]")

    # Granger-like test: does lagged TDA improve prediction of future corr?
    from numpy.linalg import lstsq

    # y = future corr change
    y = aligned["corr_change_future"].values
    x_restricted = np.column_stack([np.ones(n_ll), aligned["corr_change_now"].values])
    x_full = np.column_stack([x_restricted, aligned["tda_change"].values])

    # OLS
    beta_r = lstsq(x_restricted, y, rcond=None)[0]
    beta_f = lstsq(x_full, y, rcond=None)[0]

    ssr_r = np.sum((y - x_restricted @ beta_r)**2)
    ssr_f = np.sum((y - x_full @ beta_f)**2)

    # F-test
    df1 = 1  # one additional regressor
    df2 = n_ll - 3
    if ssr_f > 0:
        f_stat = ((ssr_r - ssr_f) / df1) / (ssr_f / df2)
        f_pval = 1 - stats.f.cdf(f_stat, df1, df2)
    else:
        f_stat = np.nan
        f_pval = np.nan

    print(f"\n    Granger-like F-test (does TDA change improve corr prediction?):")
    print(f"      F-stat = {f_stat:.3f}, p = {f_pval:.4f} "
          f"({'***' if f_pval < 0.001 else '**' if f_pval < 0.01 else '*' if f_pval < 0.05 else 'NS'})")

    # Cross-correlation at different lags
    print(f"\n    Cross-correlation: ΔTDA(t-lag) → Δcorr(t)")
    lags_to_test = [-44, -22, -11, 0, 11, 22, 44]
    lag_results = {}
    for lag in lags_to_test:
        shifted_tda = tda_change.shift(lag)
        xcorr_aligned = pd.DataFrame({
            "tda_lagged": shifted_tda,
            "corr_change": corr_change,
        }).dropna()
        if len(xcorr_aligned) > 50:
            r_lag = xcorr_aligned["tda_lagged"].corr(xcorr_aligned["corr_change"])
            lag_results[str(lag)] = float(r_lag)
            direction = "TDA leads" if lag > 0 else "TDA lags" if lag < 0 else "contemp"
            print(f"      lag={lag:+3d}d: r={r_lag:+.4f} ({direction})")

    return {
        "r_lead_22d": float(r_lead),
        "r_contemporaneous": float(r_contemp),
        "t_lead": float(t_lead),
        "p_lead": float(p_lead),
        "f_granger": float(f_stat) if not np.isnan(f_stat) else None,
        "p_granger": float(f_pval) if not np.isnan(f_pval) else None,
        "cross_correlations": lag_results,
    }


# ======================================================================
# MAIN
# ======================================================================
def main():
    t0 = time.time()

    # Load data
    close, returns = load_data()
    vix = close["VIX"] if "VIX" in close.columns else pd.Series()

    # Run analyses
    td_results = analyze_tail_dependence(returns, vix)
    regime_results = tda_regime_analysis(returns, vix)
    garch_results = garch_x_with_tda(returns, vix)
    cross_results = cross_pair_comparison(returns, vix)
    leading_results = tda_leading_indicator(returns, vix)

    elapsed = time.time() - t0

    # ======================================================================
    # SUMMARY
    # ======================================================================
    print("\n" + "=" * 80)
    print("K193 SUMMARY: Dynamic Copula Tail Dependence")
    print("=" * 80)

    # Count significant findings
    sig_predictive = 0
    sig_partial = 0
    total_pairs = 0

    for key, res in td_results.items():
        total_pairs += 1
        if res.get("p_TDA_futureRV") is not None and res["p_TDA_futureRV"] < 0.05:
            sig_predictive += 1
        if res.get("p_partial_TDA_VIX") is not None and res["p_partial_TDA_VIX"] < 0.05:
            sig_partial += 1

    print(f"\n  1. Tail dependence dynamics:")
    print(f"     - {total_pairs} pair-quantile combinations tested")
    print(f"     - {sig_predictive}/{total_pairs} significant raw r(TDA, future RV)")
    print(f"     - {sig_partial}/{total_pairs} significant partial r(TDA, future RV | VIX)")

    print(f"\n  2. TDA regime analysis:")
    if "high_vs_low_t" in regime_results:
        print(f"     - High vs Low TDA: t={regime_results['high_vs_low_t']:.3f}, p={regime_results['high_vs_low_p']:.4f}")
    if "structural_break" in regime_results:
        sb = regime_results["structural_break"]
        print(f"     - Pre-2022 TDA: {sb['pre_TDA_mean']:+.4f}")
        print(f"     - Post-2022 TDA: {sb['post_TDA_mean']:+.4f}")
        print(f"     - Break test: t={sb['t_break']:.3f}, p={sb['p_break']:.4f}")

    print(f"\n  3. GARCH + TDA augmented forecast:")
    for pair_name, res in garch_results.items():
        if "dm_stat" in res and res["dm_stat"] is not None:
            sig = "***" if res["dm_pval"] < 0.001 else "**" if res["dm_pval"] < 0.01 else "*" if res["dm_pval"] < 0.05 else "NS"
            better = "Augmented" if res["dm_stat"] > 0 else "Baseline"
            print(f"     - {pair_name}: DM={res['dm_stat']:+.3f} (p={res['dm_pval']:.4f}, {sig}), "
                  f"QLIKE impr={res['qlike_improvement_pct']:+.2f}%, better={better}")
        elif "status" in res:
            print(f"     - {pair_name}: {res['status']}")

    print(f"\n  4. Leading indicator analysis:")
    if leading_results:
        print(f"     - ΔTDA → Δcorr (22d lead): r={leading_results.get('r_lead_22d', 'N/A')}")
        if leading_results.get("p_granger") is not None:
            print(f"     - Granger F-test: p={leading_results['p_granger']:.4f}")

    # Overall verdict
    all_dm_null = all(
        (res.get("dm_pval") is None or res.get("dm_pval", 1.0) > 0.05)
        for res in garch_results.values()
    )
    all_partial_null = sig_partial == 0

    print(f"\n  VERDICT:")
    if all_dm_null and all_partial_null:
        print(f"     NULL: Dynamic tail dependence does NOT improve vol prediction")
        print(f"     beyond VIX. TDA is subsumed by VIX information.")
        verdict = "NULL"
    elif not all_partial_null and all_dm_null:
        print(f"     MARGINAL: TDA has some information beyond VIX (partial r significant)")
        print(f"     but does not improve GARCH forecasts (DM test null).")
        verdict = "MARGINAL"
    else:
        print(f"     POSITIVE: Dynamic tail dependence adds vol prediction value.")
        verdict = "POSITIVE"

    print(f"\n  Harvey (2016) threshold check: t > 3.0 for new factors")
    max_t = max(
        (abs(res.get("t_partial_TDA_VIX", 0) or 0) for res in td_results.values()),
        default=0
    )
    print(f"     Max |t| for partial r: {max_t:.2f} {'PASS' if max_t > 3.0 else 'FAIL'}")

    print(f"\n  Time elapsed: {elapsed:.1f}s")

    # Save results
    output = {
        "experiment": "K193",
        "title": "Dynamic Copula Tail Dependence and Volatility Prediction",
        "attribution": "[提出: 用戶, 執行: Claude]",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "data_range": f"{DATA_START} to {DATA_END}",
            "oos_range": f"{OOS_START} to {OOS_END}",
            "rolling_window": ROLLING_WINDOW,
            "quantiles": QUANTILES,
            "garch_window": GARCH_WINDOW,
            "refit_freq": REFIT_FREQ,
            "pairs": [f"{a}-{b}" for a, b in PAIRS],
        },
        "tail_dependence": td_results,
        "regime_analysis": regime_results,
        "garch_x": garch_results,
        "cross_pair": cross_results,
        "leading_indicator": leading_results,
        "verdict": verdict,
        "harvey_max_t": float(max_t),
        "elapsed_seconds": float(elapsed),
    }

    out_path = Path(__file__).parent / "k193_copula_tail_dep_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")


if __name__ == "__main__":
    main()
