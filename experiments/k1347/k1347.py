"""K1347 — CVaR-RP vs Sigma-RP on SPY/TLT/GLD/PDBC.

Lookahead protection:
- Weights formed at month-end M using data up to and including M.
- Applied from first trading day of M+1 via daily weight series with `.shift(1)`.

Random seed: 42 (used only for bootstrap; CVaR is historical simulation).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

for _thread_var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[_thread_var] = "1"

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize

SEED = 42
np.random.seed(SEED)

TICKERS = ["SPY", "TLT", "GLD", "PDBC"]
START = "2018-01-01"
END = "2025-12-31"
COST_BPS = 5.0  # one-way cost in bps applied to |Δw|
ALPHA = 0.05
SIGMA_WINDOW = 60
CVAR_WINDOW = 250
MIN_W = 0.02
BOOT_REPS = 1000
BLOCK = 20

STRESS_PERIODS = {
    "2018Q4_selloff": ("2018-10-01", "2018-12-31"),
    "2020_covid": ("2020-02-15", "2020-04-30"),
    "2022_inflation": ("2022-01-01", "2022-10-31"),
    "2025_tariff": ("2025-04-01", "2025-04-30"),
}

OUT_DIR = Path(__file__).parent
RESULTS_PATH = OUT_DIR / "k1347_results.json"
FIG_PATH = OUT_DIR / "k1347_fig.png"
DATA_PATH = OUT_DIR / "prices.csv"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def fetch_prices() -> pd.DataFrame:
    if DATA_PATH.exists():
        df = pd.read_csv(DATA_PATH, index_col=0, parse_dates=True)
        if set(TICKERS).issubset(df.columns) and df.index.min() <= pd.Timestamp(START):
            return df[TICKERS].dropna()
    raw = yf.download(
        TICKERS, start=START, end=END, auto_adjust=True, progress=False, threads=False
    )
    if isinstance(raw.columns, pd.MultiIndex):
        # auto_adjust=True returns 'Close' as adjusted
        close = raw["Close"]
    else:
        close = raw[["Close"]].rename(columns={"Close": TICKERS[0]})
    close = close[TICKERS].dropna()
    close.to_csv(DATA_PATH)
    return close


# ---------------------------------------------------------------------------
# Allocators
# ---------------------------------------------------------------------------
def sigma_rp_weights(returns_window: pd.DataFrame) -> np.ndarray:
    """Equal sigma-contribution weights (ERC)."""
    cov = returns_window.cov().values
    n = cov.shape[0]

    def obj(w: np.ndarray) -> float:
        port_vol = float(np.sqrt(w @ cov @ w))
        if port_vol < 1e-12:
            return 1e6
        marginal = cov @ w
        rc = w * marginal / port_vol
        target = port_vol / n
        return float(np.sum((rc - target) ** 2))

    w0 = np.full(n, 1.0 / n)
    bounds = [(MIN_W, 1.0)] * n
    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1.0},)
    res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=cons,
                   options={"maxiter": 200, "ftol": 1e-10})
    w = res.x if res.success else w0
    w = np.clip(w, MIN_W, None)
    w = w / w.sum()
    return w


def cvar_rp_weights(returns_window: pd.DataFrame) -> tuple[np.ndarray, dict]:
    """Equal-CVaR-contribution weights using historical simulation.

    For weight vector w, scenarios r_s = R_s @ w. VaR_alpha = -quantile(r_p, alpha).
    Tail set S = {s : r_s <= -VaR_alpha}.  Empirical
        CVaR(w)        = -mean(r_s for s in S)
        CRC_i(w)       =  w_i * (-mean(R[s,i] for s in S))
    sum_i CRC_i = CVaR(w) by construction (linearity of expectation).
    We equalize CRC_i across assets.
    """
    R = returns_window.values  # T x N
    n = R.shape[1]

    def cvar_and_crc(w: np.ndarray) -> tuple[float, np.ndarray]:
        rp = R @ w
        # historical VaR (loss positive)
        var_thresh = np.quantile(rp, ALPHA)  # this is the (alpha)-quantile of returns
        tail_mask = rp <= var_thresh
        if tail_mask.sum() < 5:
            # too few scenarios — fallback to vol RC
            cov = np.cov(R.T)
            port_vol = float(np.sqrt(w @ cov @ w))
            marginal = cov @ w
            return port_vol, w * marginal / max(port_vol, 1e-12)
        tail_returns = R[tail_mask]  # k x N
        # CVaR = -E[r_p | tail]
        cvar = float(-tail_returns.mean(axis=0) @ w)
        # CRC_i = w_i * (-E[R_i | tail])
        crc = w * (-tail_returns.mean(axis=0))
        return cvar, crc

    def obj(w: np.ndarray) -> float:
        cvar, crc = cvar_and_crc(w)
        if cvar < 1e-12:
            return 1e6
        target = cvar / n
        return float(np.sum((crc - target) ** 2))

    w0 = np.full(n, 1.0 / n)
    bounds = [(MIN_W, 1.0)] * n
    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1.0},)
    res = minimize(obj, w0, method="SLSQP", bounds=bounds, constraints=cons,
                   options={"maxiter": 300, "ftol": 1e-10})
    w = res.x if res.success else w0
    w = np.clip(w, MIN_W, None)
    w = w / w.sum()
    diag = {"success": bool(res.success), "nit": int(res.nit), "fun": float(res.fun)}
    return w, diag


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def monthly_rebalance_dates(returns: pd.DataFrame) -> list[pd.Timestamp]:
    """Last trading day of each month within returns.index."""
    df = pd.DataFrame(index=returns.index)
    df["ym"] = df.index.to_period("M")
    last = df.groupby("ym").tail(1).index
    return list(last)


def build_daily_weights(
    returns: pd.DataFrame,
    allocator: str,
) -> tuple[pd.DataFrame, list[dict]]:
    """Form weights at each month-end using only data up to that day.

    Returns weights indexed by trading day; weight at day t was formed at the
    most recent month-end <= t. To prevent lookahead the caller MUST shift(1)
    the returned weights before multiplying by daily returns.
    """
    rebal = monthly_rebalance_dates(returns)
    weights = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    diag_list: list[dict] = []
    last_w = None
    next_rebal_idx = 0

    for current_date in returns.index:
        # check if any rebalance dates <= current_date are unconsumed
        while next_rebal_idx < len(rebal) and rebal[next_rebal_idx] <= current_date:
            rd = rebal[next_rebal_idx]
            if allocator == "sigma":
                window = returns.loc[:rd].tail(SIGMA_WINDOW)
                if len(window) >= SIGMA_WINDOW:
                    last_w = sigma_rp_weights(window)
                    diag_list.append({"date": str(rd.date()), "alloc": "sigma",
                                      "w": last_w.tolist()})
            elif allocator == "cvar":
                window = returns.loc[:rd].tail(CVAR_WINDOW)
                if len(window) >= CVAR_WINDOW:
                    last_w, diag = cvar_rp_weights(window)
                    diag_list.append({"date": str(rd.date()), "alloc": "cvar",
                                      "w": last_w.tolist(), **diag})
            elif allocator == "ew":
                last_w = np.full(returns.shape[1], 1.0 / returns.shape[1])
            next_rebal_idx += 1
        if last_w is not None:
            weights.loc[current_date] = last_w
    weights = weights.dropna(how="all")
    return weights, diag_list


def backtest(returns: pd.DataFrame, weights_raw: pd.DataFrame, cost_bps: float
             ) -> pd.Series:
    """Apply lookahead-safe shift; charge cost on |Δw|."""
    # align
    w = weights_raw.reindex(returns.index).ffill().dropna()
    r = returns.loc[w.index]
    # CRITICAL lookahead safeguard: weight effective from next bar
    w_effective = w.shift(1).dropna()
    r = r.loc[w_effective.index]
    gross = (w_effective * r).sum(axis=1)
    # turnover cost: |Δw| applied at rebalance bar (before that bar's return)
    turnover = w_effective.diff().abs().sum(axis=1).fillna(0.0)
    cost = turnover * (cost_bps / 1e4)
    net = gross - cost
    net.name = "net_return"
    return net


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
TRADING_DAYS = 252


def equity_curve(net: pd.Series) -> pd.Series:
    return (1.0 + net).cumprod()


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def perf_metrics(net: pd.Series) -> dict:
    eq = equity_curve(net)
    ann_ret = float(net.mean() * TRADING_DAYS)
    ann_vol = float(net.std(ddof=0) * np.sqrt(TRADING_DAYS))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else float("nan")
    downside = net[net < 0].std(ddof=0) * np.sqrt(TRADING_DAYS)
    sortino = ann_ret / downside if downside > 0 else float("nan")
    mdd = max_drawdown(eq)
    calmar = ann_ret / abs(mdd) if mdd != 0 else float("nan")
    return {
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": float(sortino),
        "max_drawdown": mdd,
        "calmar": calmar,
        "n_obs": int(len(net)),
    }


def stress_period_metrics(net: pd.Series) -> dict:
    out = {}
    for name, (s, e) in STRESS_PERIODS.items():
        sub = net.loc[s:e]
        if len(sub) < 5:
            out[name] = {"n": int(len(sub)), "note": "insufficient data"}
            continue
        eq = equity_curve(sub)
        out[name] = {
            "n": int(len(sub)),
            "total_return": float(eq.iloc[-1] - 1.0),
            "max_drawdown": float(max_drawdown(eq)),
            "ann_vol": float(sub.std(ddof=0) * np.sqrt(TRADING_DAYS)),
        }
    return out


# ---------------------------------------------------------------------------
# DM test (Diebold-Mariano) on net returns. d_t = net2 - net1, so positive
# mean(d) means the treatment series net2 has higher average net return.
# ---------------------------------------------------------------------------
def dm_test(net1: pd.Series, net2: pd.Series, h: int = 1) -> dict:
    """DM test comparing net returns. d_t = (-net1) - (-net2) = net2 - net1.
    Positive mean(d) => net2 > net1 on average (treatment net2 better).
    HAC (Newey-West) SE with h-1 nonzero lags (h=1 means iid SE)."""
    n1, n2 = net1.align(net2, join="inner")
    d = (n2 - n1).values
    t = len(d)
    if t < 30:
        return {"t_stat": float("nan"), "p_value": float("nan"), "n": t,
                "note": "insufficient"}
    dbar = float(d.mean())
    if h == 1:
        var = float(d.var(ddof=1))
    else:
        gamma0 = float(d.var(ddof=0))
        cov_sum = 0.0
        for lag in range(1, h):
            c = float(np.cov(d[:-lag], d[lag:], ddof=0)[0, 1])
            cov_sum += 2.0 * (1.0 - lag / h) * c
        var = gamma0 + cov_sum
    se = np.sqrt(var / t)
    t_stat = dbar / se if se > 0 else float("nan")
    # two-sided
    from scipy.stats import norm
    p = float(2.0 * (1.0 - norm.cdf(abs(t_stat))))
    return {"mean_d": dbar, "t_stat": float(t_stat), "p_value": p, "n": int(t),
            "hac_lags": int(max(h - 1, 0)), "bandwidth_h": int(h)}


# ---------------------------------------------------------------------------
# Stationary block bootstrap CI on Sharpe diff and MDD diff
# ---------------------------------------------------------------------------
def block_bootstrap_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Stationary block bootstrap (Politis-Romano) indices of length n."""
    idx = np.empty(n, dtype=np.int64)
    i = 0
    while i < n:
        start = rng.integers(0, n)
        # geometric block length with mean = block
        L = rng.geometric(1.0 / block)
        L = min(L, n - i)
        for k in range(L):
            idx[i + k] = (start + k) % n
        i += L
    return idx


def bootstrap_ci(net1: pd.Series, net2: pd.Series, reps: int, block: int, seed: int
                 ) -> dict:
    rng = np.random.default_rng(seed)
    n1, n2 = net1.align(net2, join="inner")
    a = n1.values
    b = n2.values
    n = len(a)
    sharpe_diff = np.empty(reps)
    mdd_diff = np.empty(reps)
    for r in range(reps):
        idx = block_bootstrap_indices(n, block, rng)
        a_b = a[idx]
        b_b = b[idx]
        s_a = a_b.mean() * TRADING_DAYS / (a_b.std(ddof=0) * np.sqrt(TRADING_DAYS) + 1e-12)
        s_b = b_b.mean() * TRADING_DAYS / (b_b.std(ddof=0) * np.sqrt(TRADING_DAYS) + 1e-12)
        sharpe_diff[r] = s_b - s_a
        eq_a = np.cumprod(1.0 + a_b)
        eq_b = np.cumprod(1.0 + b_b)
        mdd_a = (eq_a / np.maximum.accumulate(eq_a) - 1.0).min()
        mdd_b = (eq_b / np.maximum.accumulate(eq_b) - 1.0).min()
        mdd_diff[r] = mdd_b - mdd_a
    return {
        "reps": int(reps),
        "block": int(block),
        "seed": int(seed),
        "sharpe_diff_mean": float(sharpe_diff.mean()),
        "sharpe_diff_ci95": [float(np.quantile(sharpe_diff, 0.025)),
                              float(np.quantile(sharpe_diff, 0.975))],
        "mdd_diff_mean": float(mdd_diff.mean()),
        "mdd_diff_ci95": [float(np.quantile(mdd_diff, 0.025)),
                          float(np.quantile(mdd_diff, 0.975))],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t0 = time.time()
    prices = fetch_prices()
    rets = prices.pct_change().dropna()
    print(f"[K1347] Loaded {len(rets)} daily returns "
          f"({rets.index.min().date()} → {rets.index.max().date()}) on {list(rets.columns)}")

    print("[K1347] Computing sigma-RP weights...")
    w_sigma, diag_sigma = build_daily_weights(rets, "sigma")
    print("[K1347] Computing CVaR-RP weights...")
    w_cvar, diag_cvar = build_daily_weights(rets, "cvar")

    # equal weight daily series
    ew_w = pd.DataFrame(0.25, index=rets.index, columns=rets.columns)
    net_ew = backtest(rets, ew_w, COST_BPS)
    net_sigma = backtest(rets, w_sigma, COST_BPS)
    net_cvar = backtest(rets, w_cvar, COST_BPS)

    # align all three on common index (drops warmup)
    common = net_ew.index.intersection(net_sigma.index).intersection(net_cvar.index)
    # CVaR has longer warmup (250d) so use that as the cut
    cvar_first = net_cvar.index.min()
    common = common[common >= cvar_first]
    net_ew = net_ew.loc[common]
    net_sigma = net_sigma.loc[common]
    net_cvar = net_cvar.loc[common]
    print(f"[K1347] Common OOS sample: {common.min().date()} → {common.max().date()}, "
          f"n={len(common)}")

    metrics = {
        "EW": perf_metrics(net_ew),
        "Sigma_RP": perf_metrics(net_sigma),
        "CVaR_RP": perf_metrics(net_cvar),
    }
    stress = {
        "EW": stress_period_metrics(net_ew),
        "Sigma_RP": stress_period_metrics(net_sigma),
        "CVaR_RP": stress_period_metrics(net_cvar),
    }
    # stress-period MDD diff (CVaR_RP - Sigma_RP) < 0 means CVaR improves MDD
    stress_mdd_diff = {}
    for k in STRESS_PERIODS:
        s_mdd = stress["Sigma_RP"].get(k, {}).get("max_drawdown")
        c_mdd = stress["CVaR_RP"].get(k, {}).get("max_drawdown")
        if s_mdd is None or c_mdd is None:
            stress_mdd_diff[k] = None
        else:
            stress_mdd_diff[k] = {
                "sigma_mdd": s_mdd,
                "cvar_mdd": c_mdd,
                "cvar_minus_sigma": c_mdd - s_mdd,
                "improvement": c_mdd > s_mdd,  # less negative => improvement
            }

    print("[K1347] DM test CVaR vs Sigma (net returns)...")
    dm = dm_test(net_sigma, net_cvar, h=5)  # 5-day HAC

    print(f"[K1347] Bootstrap {BOOT_REPS} reps, block={BLOCK}, seed={SEED}...")
    boot = bootstrap_ci(net_sigma, net_cvar, BOOT_REPS, BLOCK, SEED)

    # Determine verdict
    n_improved_periods = sum(1 for v in stress_mdd_diff.values()
                             if v is not None and v["improvement"])
    n_evaluable_periods = sum(1 for v in stress_mdd_diff.values() if v is not None)
    stress_denominator = max(n_evaluable_periods, 1)
    sharpe_diff = metrics["CVaR_RP"]["sharpe"] - metrics["Sigma_RP"]["sharpe"]
    dm_mean = dm.get("mean_d", 0)
    boot_ci = boot["sharpe_diff_ci95"]
    boot_includes_zero = boot_ci[0] <= 0 <= boot_ci[1]

    if n_improved_periods >= 3 and dm_mean >= 0 and not boot_includes_zero and boot_ci[0] > 0:
        verdict = "PASS"
        verdict_reason = (f"MDD improved in {n_improved_periods}/{stress_denominator} "
                          "evaluable stress periods; "
                          f"DM mean_d positive; bootstrap CI strictly > 0.")
    elif n_improved_periods >= 2 and sharpe_diff >= -0.1:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = (f"MDD improved in {n_improved_periods}/{stress_denominator} "
                          "evaluable stress periods; "
                          f"Sharpe diff {sharpe_diff:+.3f} (mild trade-off).")
    elif abs(sharpe_diff) < 0.05 and abs(boot["mdd_diff_mean"]) < 0.005:
        verdict = "NULL"
        verdict_reason = ("No material difference between CVaR-RP and Sigma-RP on "
                          "full-period Sharpe or MDD.")
    else:
        verdict = "FAIL"
        verdict_reason = (f"CVaR-RP underperforms: Sharpe diff {sharpe_diff:+.3f}, "
                          f"MDD improved in only {n_improved_periods}/{stress_denominator} "
                          "evaluable stress periods.")

    runtime_s = time.time() - t0
    out = {
        "experiment_id": "K1347",
        "title": "CVaR-RP vs Sigma-RP (ERC) on SPY/TLT/GLD/PDBC",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "config": {
            "tickers": TICKERS,
            "period": [START, END],
            "cost_bps_one_way": COST_BPS,
            "alpha": ALPHA,
            "sigma_window": SIGMA_WINDOW,
            "cvar_window": CVAR_WINDOW,
            "min_weight": MIN_W,
            "boot_reps": BOOT_REPS,
            "boot_block": BLOCK,
            "rebalance": "monthly_last_business_day",
            "lookahead_guard": "weights.shift(1) on daily series; "
                               "weights formed at t use data <= t, applied from t+1",
        },
        "sample": {
            "first_oos_day": str(common.min().date()),
            "last_oos_day": str(common.max().date()),
            "n_obs": int(len(common)),
        },
        "full_period_metrics": metrics,
        "stress_periods": stress,
        "stress_mdd_diff_cvar_minus_sigma": stress_mdd_diff,
        "n_stress_periods_improved": int(n_improved_periods),
        "n_stress_periods_evaluable": int(n_evaluable_periods),
        "dm_test_cvar_vs_sigma": dm,
        "bootstrap_ci": boot,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "sigma_rp_weight_diagnostics_sample": diag_sigma[:3] + diag_sigma[-3:],
        "cvar_rp_weight_diagnostics_sample": diag_cvar[:3] + diag_cvar[-3:],
        "cvar_rp_n_rebalances": len(diag_cvar),
        "cvar_rp_optimizer_success_rate": float(
            np.mean([d["success"] for d in diag_cvar])) if diag_cvar else None,
        "runtime_seconds": round(runtime_s, 2),
        "codex_review": None,  # filled in after Codex review
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2))
    print(f"[K1347] Results written to {RESULTS_PATH}")

    # --- figure ---
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    eqs = {
        "EW": equity_curve(net_ew),
        "Sigma-RP": equity_curve(net_sigma),
        "CVaR-RP": equity_curve(net_cvar),
    }
    for name, eq in eqs.items():
        axes[0].plot(eq.index, eq.values, label=name, lw=1.4)
    axes[0].set_title("K1347 Equity curves — SPY/TLT/GLD/PDBC (net of 5bps turnover cost)")
    axes[0].set_ylabel("Equity (start=1)")
    axes[0].legend(loc="upper left")
    axes[0].grid(alpha=0.3)
    for name, eq in eqs.items():
        dd = eq / eq.cummax() - 1.0
        axes[1].plot(dd.index, dd.values, label=name, lw=1.2)
    axes[1].set_title("Drawdown")
    axes[1].set_ylabel("Drawdown")
    axes[1].axhline(0, color="k", lw=0.5)
    axes[1].legend(loc="lower left")
    axes[1].grid(alpha=0.3)
    # shade stress periods
    for name, (s, e) in STRESS_PERIODS.items():
        for ax in axes:
            ax.axvspan(pd.to_datetime(s), pd.to_datetime(e), color="red", alpha=0.08)
    plt.tight_layout()
    plt.savefig(FIG_PATH, dpi=110)
    print(f"[K1347] Figure written to {FIG_PATH}")
    print(f"\n[K1347] VERDICT: {verdict}")
    print(f"[K1347] {verdict_reason}")
    print(f"[K1347] Full-period Sharpe — EW={metrics['EW']['sharpe']:.3f}, "
          f"Sigma-RP={metrics['Sigma_RP']['sharpe']:.3f}, "
          f"CVaR-RP={metrics['CVaR_RP']['sharpe']:.3f}")
    print(f"[K1347] Full-period MDD — EW={metrics['EW']['max_drawdown']:.3f}, "
          f"Sigma-RP={metrics['Sigma_RP']['max_drawdown']:.3f}, "
          f"CVaR-RP={metrics['CVaR_RP']['max_drawdown']:.3f}")
    print(f"[K1347] DM mean_d={dm['mean_d']:.2e}, t={dm['t_stat']:.3f}, p={dm['p_value']:.3f}")
    print(f"[K1347] Bootstrap Sharpe diff CI95={boot['sharpe_diff_ci95']}")
    print(f"[K1347] Stress periods improved: {n_improved_periods}/{stress_denominator}")
    print(f"[K1347] Done in {runtime_s:.1f}s")


if __name__ == "__main__":
    main()
