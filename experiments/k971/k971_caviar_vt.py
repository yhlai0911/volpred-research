"""K971: CAViaR-based Volatility Targeting vs GARCH-VT

Compare volatility targeting strategies using:
1. Buy & Hold (100% SPY)
2. GARCH-VT (GJR-GARCH sigma)
3. CAViaR-VT (implied sigma from Asymmetric Slope CAViaR)
4. Simple 12/VIX (benchmark)

CAViaR extracts implied volatility from VaR estimates:
  sigma_t = |Q_t(0.05)| / 1.645  (Normal assumption)

References:
  - Engle & Manganelli (2004) "CAViaR: Conditional Autoregressive Value at Risk"
  - Bollerslev (1986), Glosten, Jagannathan & Runkle (1993)
  - K967: CAViaR Asymmetric Slope beats GARCH Student-t on VaR (DM t=3.079)

Data source: yfinance (SPY, ^VIX), 2006-01-01 to 2026-04-07
IS: 2006-2014, OOS: 2015-2026

[Proposer: User, Executor: Claude]
Author: VolPred Research System
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import optimize
from arch import arch_model

warnings.filterwarnings("ignore")
np.random.seed(42)

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2006-01-01"
END_DATE = "2026-04-07"
IS_END = "2014-12-31"      # In-sample end
OOS_START = "2015-01-02"    # Out-of-sample start
SIGMA_TARGET = 0.15         # 15% annualized target vol
W_MIN, W_MAX = 0.2, 1.5    # Weight bounds
REFIT_MONTHS = 3            # Re-estimate CAViaR every 3 months
GARCH_WINDOW = 2000         # Rolling window for GARCH

SCRIPT_DIR = Path(__file__).parent


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY and VIX data."""
    print("Downloading data...", flush=True)
    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    spy_ret = spy["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    vix_close = vix["Close"].dropna()
    vix_close.name = "vix"

    # Align
    common = spy_ret.index.intersection(vix_close.index)
    spy_ret = spy_ret.loc[common]
    vix_close = vix_close.loc[common]

    print(f"  SPY: {spy_ret.index[0].date()} to {spy_ret.index[-1].date()}, N={len(spy_ret)}")
    print(f"  VIX: {vix_close.index[0].date()} to {vix_close.index[-1].date()}, N={len(vix_close)}")
    return spy_ret, vix_close


# ============================================================================
# CAViaR Asymmetric Slope
# ============================================================================
def caviar_as_filter(params, returns, q0):
    """Asymmetric Slope CAViaR: Q_t = b0 + b1*Q_{t-1} + b2*max(r_{t-1},0) + b3*min(r_{t-1},0)"""
    b0, b1, b2, b3 = params
    T = len(returns)
    q = np.empty(T)
    q[0] = q0
    for t in range(1, T):
        q[t] = b0 + b1 * q[t - 1] + b2 * max(returns[t - 1], 0.0) + b3 * min(returns[t - 1], 0.0)
    return q


def pinball_loss(params, returns, alpha, q0):
    """Quantile regression loss (check function)."""
    q = caviar_as_filter(params, returns, q0)
    resid = returns - q
    loss = np.where(resid < 0, (alpha - 1) * resid, alpha * resid)
    return np.mean(loss)


def estimate_caviar(returns, alpha=0.05, n_restarts=5):
    """Estimate CAViaR AS model with multiple restarts."""
    q0 = np.quantile(returns, alpha)
    best_result = None
    best_loss = np.inf

    # Initial guesses
    init_params_list = [
        [q0 * 0.01, 0.95, -0.10, 0.10],
        [q0 * 0.02, 0.90, -0.15, 0.15],
        [q0 * 0.005, 0.98, -0.05, 0.05],
        [q0 * 0.03, 0.85, -0.20, 0.20],
        [q0 * 0.01, 0.92, -0.12, 0.08],
    ]

    bounds = [(-0.1, 0.1), (0.5, 0.999), (-0.5, 0.0), (0.0, 0.5)]

    for i, init in enumerate(init_params_list[:n_restarts]):
        try:
            res = optimize.minimize(
                pinball_loss, init, args=(returns, alpha, q0),
                method="Nelder-Mead",
                options={"maxiter": 5000, "xatol": 1e-8, "fatol": 1e-10}
            )
            if res.fun < best_loss:
                best_loss = res.fun
                best_result = res
        except Exception:
            continue

    if best_result is None:
        # Fallback: use empirical quantile
        return None, q0

    return best_result.x, q0


def caviar_implied_vol(q_series):
    """Extract implied volatility from 5% VaR quantile.

    Under Normal: VaR(5%) = -z_0.05 * sigma => sigma = |VaR(5%)| / 1.645
    CAViaR estimates negative quantile directly, so sigma = |Q| / 1.645
    """
    z_005 = 1.6449
    sigma = np.abs(q_series) / z_005
    return sigma


# ============================================================================
# GARCH-VT
# ============================================================================
def estimate_garch_vol(returns, window=GARCH_WINDOW):
    """Rolling GJR-GARCH(1,1) volatility estimation."""
    T = len(returns)
    sigma = pd.Series(np.nan, index=returns.index)

    # Use expanding window for first GARCH_WINDOW points, then rolling
    for t in range(window, T):
        try:
            ret_slice = returns.iloc[max(0, t - window):t] * 100  # arch expects %
            model = arch_model(ret_slice, vol="GARCH", p=1, o=1, q=1, mean="Zero", dist="normal")
            res = model.fit(disp="off", show_warning=False)
            # One-step-ahead forecast
            fcast = res.forecast(horizon=1)
            sigma.iloc[t] = np.sqrt(fcast.variance.values[-1, 0]) / 100  # back to decimal
        except Exception:
            # Fallback: use rolling std
            sigma.iloc[t] = returns.iloc[max(0, t - 60):t].std()

    return sigma


# ============================================================================
# Strategy Implementations
# ============================================================================
def run_strategies(spy_ret, vix_close):
    """Run all four strategies and return results DataFrame."""
    print("\n=== Running Strategies ===", flush=True)
    returns = spy_ret.values
    dates = spy_ret.index
    T = len(returns)

    # --- 1. CAViaR-VT ---
    print("Estimating CAViaR (Asymmetric Slope)...", flush=True)
    alpha = 0.05

    # Initial estimation on IS data
    is_mask = dates <= IS_END
    is_returns = returns[is_mask]
    is_end_idx = np.sum(is_mask)

    params, q0 = estimate_caviar(is_returns, alpha=alpha)
    if params is None:
        print("  WARNING: CAViaR estimation failed, using fallback")
        params = np.array([q0 * 0.01, 0.95, -0.10, 0.10])

    print(f"  Initial CAViaR params: b0={params[0]:.6f}, b1={params[1]:.4f}, "
          f"b2={params[2]:.4f}, b3={params[3]:.4f}")

    # Generate full Q series with periodic refitting
    caviar_q = np.full(T, np.nan)
    caviar_q[:is_end_idx] = caviar_as_filter(params, is_returns, q0)

    # OOS: refit every REFIT_MONTHS months
    current_params = params.copy()
    last_refit = is_end_idx
    refit_count = 0

    for t in range(is_end_idx, T):
        # Check if we need to refit
        if t > is_end_idx:
            months_since = (dates[t] - dates[last_refit]).days / 30
            if months_since >= REFIT_MONTHS:
                # Refit on last 2000 points
                fit_start = max(0, t - 2000)
                new_params, new_q0 = estimate_caviar(returns[fit_start:t], alpha=alpha)
                if new_params is not None:
                    current_params = new_params
                    refit_count += 1
                last_refit = t

        # Update Q using current params
        if t == is_end_idx:
            caviar_q[t] = current_params[0] + current_params[1] * caviar_q[t - 1] + \
                          current_params[2] * max(returns[t - 1], 0) + \
                          current_params[3] * min(returns[t - 1], 0)
        else:
            caviar_q[t] = current_params[0] + current_params[1] * caviar_q[t - 1] + \
                          current_params[2] * max(returns[t - 1], 0) + \
                          current_params[3] * min(returns[t - 1], 0)

    print(f"  CAViaR refits in OOS: {refit_count}")

    # Extract implied vol
    caviar_sigma_daily = caviar_implied_vol(caviar_q)
    caviar_sigma_annual = caviar_sigma_daily * np.sqrt(252)

    # CAViaR-VT weights
    caviar_w = np.clip(SIGMA_TARGET / caviar_sigma_annual, W_MIN, W_MAX)
    caviar_w_series = pd.Series(caviar_w, index=dates)
    # LAG: use yesterday's weight for today's return
    caviar_w_lagged = caviar_w_series.shift(1)

    # --- 2. GARCH-VT ---
    print("Estimating GJR-GARCH rolling volatility...", flush=True)
    garch_sigma = estimate_garch_vol(spy_ret, window=GARCH_WINDOW)
    garch_sigma_annual = garch_sigma * np.sqrt(252)
    garch_w = np.clip(SIGMA_TARGET / garch_sigma_annual, W_MIN, W_MAX)
    # LAG: use yesterday's weight
    garch_w_lagged = garch_w.shift(1)

    # --- 3. Simple 12/VIX ---
    print("Computing 12/VIX weights...", flush=True)
    vix_w = np.clip(12.0 / vix_close, W_MIN, W_MAX)
    # LAG: use yesterday's weight
    vix_w_lagged = vix_w.shift(1)

    # --- 4. Buy & Hold ---
    bh_w = pd.Series(1.0, index=dates)

    # Assemble results
    results = pd.DataFrame(index=dates)
    results["spy_ret"] = spy_ret
    results["bh_ret"] = spy_ret * 1.0
    results["garch_w"] = garch_w_lagged
    results["garch_ret"] = spy_ret * garch_w_lagged
    results["caviar_w"] = caviar_w_lagged
    results["caviar_ret"] = spy_ret * caviar_w_lagged
    results["vix_w"] = vix_w_lagged
    results["vix_ret"] = spy_ret * vix_w_lagged
    results["caviar_q"] = caviar_q
    results["caviar_sigma_annual"] = caviar_sigma_annual
    results["garch_sigma_annual"] = garch_sigma_annual

    return results


# ============================================================================
# Performance Metrics
# ============================================================================
def compute_metrics(ret_series, name="Strategy"):
    """Compute standard performance metrics."""
    ret = ret_series.dropna()
    if len(ret) == 0:
        return {}

    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    sortino_denom = ret[ret < 0].std() * np.sqrt(252) if (ret < 0).sum() > 0 else ann_vol
    sortino = ann_ret / sortino_denom if sortino_denom > 0 else 0

    cum = (1 + ret).cumprod()
    running_max = cum.cummax()
    dd = cum / running_max - 1
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # VaR and ES (5%)
    var_5 = ret.quantile(0.05)
    es_5 = ret[ret <= var_5].mean() if (ret <= var_5).sum() > 0 else var_5

    return {
        "name": name,
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "var_5pct": float(var_5),
        "es_5pct": float(es_5),
        "n_days": int(len(ret)),
    }


def compute_turnover(weight_series):
    """Compute average daily turnover = mean(|w_t - w_{t-1}|)."""
    w = weight_series.dropna()
    if len(w) < 2:
        return 0.0
    return float(np.abs(w.diff()).mean())


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    loss1, loss2: loss series (e.g., squared portfolio returns for volatility comparison).
    Returns t-stat and p-value.
    """
    d = loss1 - loss2
    d = d.dropna()
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_bar = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += gamma_k
    var_d = (gamma_0 + 2 * gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n
    t_stat = d_bar / np.sqrt(var_d)
    from scipy import stats as sp_stats
    p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ============================================================================
# Plotting
# ============================================================================
def plot_cumulative_returns(results, save_path):
    """Plot cumulative returns for all strategies (OOS only)."""
    oos = results.loc[OOS_START:]

    fig, ax = plt.subplots(figsize=(14, 7))

    strategies = {
        "Buy & Hold (SPY)": "bh_ret",
        "GARCH-VT": "garch_ret",
        "CAViaR-VT": "caviar_ret",
        "12/VIX": "vix_ret",
    }

    colors = ["#888888", "#2196F3", "#FF5722", "#4CAF50"]

    for (name, col), color in zip(strategies.items(), colors):
        cum = (1 + oos[col].dropna()).cumprod()
        ax.plot(cum.index.to_numpy(), cum.values, label=name, color=color, linewidth=1.5)

    ax.set_title("K971: Cumulative Returns — Volatility Targeting Strategies (OOS 2015-2026)",
                 fontsize=13, fontweight="bold")
    ax.set_ylabel("Growth of $1")
    ax.set_xlabel("")
    ax.legend(loc="upper left", fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"  Saved: {save_path}")


def plot_weights_comparison(results, save_path):
    """Plot weight time series for all VT strategies (OOS only)."""
    oos = results.loc[OOS_START:]

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    strategies = [
        ("GARCH-VT Weight", "garch_w", "#2196F3"),
        ("CAViaR-VT Weight", "caviar_w", "#FF5722"),
        ("12/VIX Weight", "vix_w", "#4CAF50"),
    ]

    for ax, (name, col, color) in zip(axes, strategies):
        w = oos[col].dropna()
        ax.plot(w.index.to_numpy(), w.values, color=color, linewidth=0.8, alpha=0.8)
        ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
        ax.set_ylabel("Weight")
        ax.set_title(name, fontsize=11)
        ax.set_ylim(0, 1.6)
        ax.grid(True, alpha=0.3)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axes[-1].xaxis.set_major_locator(mdates.YearLocator())
    fig.suptitle("K971: Strategy Weights Comparison (OOS 2015-2026)",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"  Saved: {save_path}")


def plot_drawdowns(results, save_path):
    """Plot drawdowns for all strategies (OOS only)."""
    oos = results.loc[OOS_START:]

    fig, ax = plt.subplots(figsize=(14, 6))

    strategies = {
        "Buy & Hold": "bh_ret",
        "GARCH-VT": "garch_ret",
        "CAViaR-VT": "caviar_ret",
        "12/VIX": "vix_ret",
    }
    colors = ["#888888", "#2196F3", "#FF5722", "#4CAF50"]

    for (name, col), color in zip(strategies.items(), colors):
        ret = oos[col].dropna()
        cum = (1 + ret).cumprod()
        dd = cum / cum.cummax() - 1
        ax.fill_between(dd.index.to_numpy(), dd.values, 0, alpha=0.15, color=color)
        ax.plot(dd.index.to_numpy(), dd.values, color=color, linewidth=0.8, label=name)

    ax.set_title("K971: Drawdowns (OOS 2015-2026)", fontsize=13, fontweight="bold")
    ax.set_ylabel("Drawdown")
    ax.legend(loc="lower left", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"  Saved: {save_path}")


# ============================================================================
# Crisis Period Analysis
# ============================================================================
def crisis_analysis(results):
    """Analyze performance during crisis periods."""
    crises = {
        "COVID Crash (2020-02 to 2020-03)": ("2020-02-19", "2020-03-23"),
        "2022 Bear Market (2022-01 to 2022-10)": ("2022-01-03", "2022-10-12"),
        "2018 Q4 Selloff": ("2018-10-01", "2018-12-24"),
        "Aug 2024 Japan Carry Unwind": ("2024-07-15", "2024-08-05"),
    }

    crisis_results = {}
    for name, (start, end) in crises.items():
        try:
            period = results.loc[start:end]
            if len(period) < 5:
                continue
            crisis_results[name] = {
                "bh_return": float((1 + period["bh_ret"]).prod() - 1),
                "garch_vt_return": float((1 + period["garch_ret"].dropna()).prod() - 1),
                "caviar_vt_return": float((1 + period["caviar_ret"].dropna()).prod() - 1),
                "vix_12_return": float((1 + period["vix_ret"].dropna()).prod() - 1),
                "avg_garch_w": float(period["garch_w"].mean()) if not period["garch_w"].isna().all() else None,
                "avg_caviar_w": float(period["caviar_w"].mean()) if not period["caviar_w"].isna().all() else None,
                "avg_vix_w": float(period["vix_w"].mean()) if not period["vix_w"].isna().all() else None,
                "n_days": len(period),
            }
        except Exception as e:
            print(f"  Warning: Could not analyze {name}: {e}")

    return crisis_results


# ============================================================================
# Main
# ============================================================================
def main():
    print("=" * 70)
    print("K971: CAViaR-based Volatility Targeting vs GARCH-VT")
    print("=" * 70)
    print(f"  Target vol: {SIGMA_TARGET*100:.0f}%")
    print(f"  Weight bounds: [{W_MIN}, {W_MAX}]")
    print(f"  IS: {START_DATE} to {IS_END}")
    print(f"  OOS: {OOS_START} to {END_DATE}")
    print()

    # Download data
    spy_ret, vix_close = download_data()

    # Run strategies
    results = run_strategies(spy_ret, vix_close)

    # OOS metrics
    oos = results.loc[OOS_START:]
    print("\n=== OOS Performance Metrics ===")
    print(f"OOS period: {oos.index[0].date()} to {oos.index[-1].date()}, N={len(oos)}")

    strat_metrics = {}
    for name, col in [("Buy & Hold", "bh_ret"), ("GARCH-VT", "garch_ret"),
                       ("CAViaR-VT", "caviar_ret"), ("12/VIX", "vix_ret")]:
        m = compute_metrics(oos[col], name)
        strat_metrics[name] = m

    # Turnover
    for name, col in [("GARCH-VT", "garch_w"), ("CAViaR-VT", "caviar_w"), ("12/VIX", "vix_w")]:
        strat_metrics[name]["turnover"] = compute_turnover(oos[col])

    # Print table
    print(f"\n{'Strategy':<15} {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>8} {'Sortino':>8} "
          f"{'MDD':>8} {'VaR5%':>8} {'ES5%':>8} {'Turn':>8}")
    print("-" * 95)
    for name, m in strat_metrics.items():
        turn = m.get("turnover", 0)
        print(f"{name:<15} {m['ann_return']:>8.3f} {m['ann_vol']:>8.3f} {m['sharpe']:>8.3f} "
              f"{m['sortino']:>8.3f} {m['mdd']:>8.3f} {m['var_5pct']:>8.4f} {m['es_5pct']:>8.4f} "
              f"{turn:>8.4f}")

    # DM test: CAViaR-VT vs GARCH-VT (using squared returns as loss)
    print("\n=== Diebold-Mariano Tests ===")
    oos_valid = oos.dropna(subset=["garch_ret", "caviar_ret", "vix_ret"])

    # Loss = squared portfolio return (lower = better risk management)
    loss_garch = oos_valid["garch_ret"] ** 2
    loss_caviar = oos_valid["caviar_ret"] ** 2
    loss_vix = oos_valid["vix_ret"] ** 2
    loss_bh = oos_valid["bh_ret"] ** 2

    dm_pairs = [
        ("CAViaR-VT vs GARCH-VT", loss_caviar, loss_garch),
        ("CAViaR-VT vs 12/VIX", loss_caviar, loss_vix),
        ("CAViaR-VT vs B&H", loss_caviar, loss_bh),
        ("GARCH-VT vs 12/VIX", loss_garch, loss_vix),
    ]

    dm_results = {}
    for name, l1, l2 in dm_pairs:
        t_stat, p_val = dm_test(l1, l2, h=1)
        dm_results[name] = {"t_stat": t_stat, "p_value": p_val}
        sig = "***" if abs(t_stat) > 3.0 else "**" if abs(t_stat) > 2.0 else "*" if abs(t_stat) > 1.645 else ""
        direction = "1st better" if t_stat < 0 else "2nd better"
        print(f"  {name}: t={t_stat:.3f}, p={p_val:.4f} ({direction}) {sig}")

    # Crisis analysis
    print("\n=== Crisis Period Analysis ===")
    crisis = crisis_analysis(results)
    for period_name, data in crisis.items():
        print(f"\n  {period_name} ({data['n_days']} days):")
        print(f"    B&H: {data['bh_return']:+.3f}, GARCH-VT: {data['garch_vt_return']:+.3f}, "
              f"CAViaR-VT: {data['caviar_vt_return']:+.3f}, 12/VIX: {data['vix_12_return']:+.3f}")
        if data.get('avg_caviar_w') is not None:
            print(f"    Avg weights — GARCH: {data['avg_garch_w']:.2f}, "
                  f"CAViaR: {data['avg_caviar_w']:.2f}, VIX: {data['avg_vix_w']:.2f}")

    # Volatility comparison
    print("\n=== Implied Volatility Statistics (OOS) ===")
    oos_caviar_vol = oos["caviar_sigma_annual"].dropna()
    oos_garch_vol = oos["garch_sigma_annual"].dropna()
    print(f"  CAViaR sigma: mean={oos_caviar_vol.mean():.3f}, std={oos_caviar_vol.std():.3f}, "
          f"min={oos_caviar_vol.min():.3f}, max={oos_caviar_vol.max():.3f}")
    print(f"  GARCH sigma:  mean={oos_garch_vol.mean():.3f}, std={oos_garch_vol.std():.3f}, "
          f"min={oos_garch_vol.min():.3f}, max={oos_garch_vol.max():.3f}")
    corr = oos_caviar_vol.corr(oos_garch_vol)
    print(f"  Correlation(CAViaR sigma, GARCH sigma): {corr:.3f}")

    # Plots
    print("\n=== Generating Plots ===")
    plot_cumulative_returns(results, SCRIPT_DIR / "k971_cumulative_returns.png")
    plot_weights_comparison(results, SCRIPT_DIR / "k971_weights_comparison.png")
    plot_drawdowns(results, SCRIPT_DIR / "k971_drawdowns.png")

    # Save results
    output = {
        "experiment_id": "K971",
        "title": "CAViaR-based Volatility Targeting vs GARCH-VT",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance",
        "data_period": f"{START_DATE} to {END_DATE}",
        "oos_period": f"{OOS_START} to {END_DATE}",
        "config": {
            "sigma_target": SIGMA_TARGET,
            "w_min": W_MIN,
            "w_max": W_MAX,
            "refit_months": REFIT_MONTHS,
            "garch_window": GARCH_WINDOW,
            "caviar_alpha": 0.05,
            "seed": 42,
        },
        "oos_metrics": strat_metrics,
        "dm_tests": dm_results,
        "crisis_analysis": crisis,
        "vol_stats": {
            "caviar_sigma_mean": float(oos_caviar_vol.mean()),
            "caviar_sigma_std": float(oos_caviar_vol.std()),
            "garch_sigma_mean": float(oos_garch_vol.mean()),
            "garch_sigma_std": float(oos_garch_vol.std()),
            "sigma_correlation": float(corr),
        },
        "references": [
            "Engle & Manganelli (2004) 'CAViaR: Conditional Autoregressive Value at Risk', JBES",
            "Glosten, Jagannathan & Runkle (1993) 'On the Relation between Expected Value and Volatility', JoF",
            "K967: CAViaR AS beats GARCH Student-t on VaR (DM t=3.079 at alpha=0.95)",
        ],
    }

    results_path = SCRIPT_DIR / "k971_caviar_vt_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved: {results_path}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    caviar_sharpe = strat_metrics["CAViaR-VT"]["sharpe"]
    garch_sharpe = strat_metrics["GARCH-VT"]["sharpe"]
    vix_sharpe = strat_metrics["12/VIX"]["sharpe"]
    bh_sharpe = strat_metrics["Buy & Hold"]["sharpe"]

    print(f"  Sharpe: B&H={bh_sharpe:.3f}, GARCH-VT={garch_sharpe:.3f}, "
          f"CAViaR-VT={caviar_sharpe:.3f}, 12/VIX={vix_sharpe:.3f}")

    if caviar_sharpe > garch_sharpe:
        print(f"  => CAViaR-VT Sharpe {caviar_sharpe:.3f} > GARCH-VT {garch_sharpe:.3f} "
              f"(+{(caviar_sharpe - garch_sharpe):.3f})")
    else:
        print(f"  => GARCH-VT Sharpe {garch_sharpe:.3f} >= CAViaR-VT {caviar_sharpe:.3f} "
              f"(diff {(garch_sharpe - caviar_sharpe):.3f})")

    dm_cv_gv = dm_results.get("CAViaR-VT vs GARCH-VT", {})
    t_stat = dm_cv_gv.get("t_stat", 0)
    if abs(t_stat) > 3.0:
        print(f"  => DM test significant at Harvey (2016) threshold: t={t_stat:.3f}")
    else:
        print(f"  => DM test NOT significant at Harvey threshold: t={t_stat:.3f} (need |t|>3.0)")

    print("\nDone.")


if __name__ == "__main__":
    main()
