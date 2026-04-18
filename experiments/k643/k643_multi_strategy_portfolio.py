#!/usr/bin/env python3
"""
K643: Optimal Multi-Strategy Portfolio
======================================
Can we combine multiple VT strategies into a meta-portfolio that beats
the single best strategy through diversification?

Data: paper_trading.json (2023-01 to 2026-03) + yfinance VIX
Methods: Equal-weight, Inverse-vol, Risk Parity, Max Sharpe,
         Best-2 momentum, Regime-conditional
References:
  - DeMiguel et al. (2009) "Optimal Versus Naive Diversification" RFS
  - Maillard et al. (2010) "The Properties of Equally Weighted Risk Contribution Portfolios" JPM
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Configuration ────────────────────────────────────────────────────
ROLLING_WINDOW = 60  # days for rolling estimates
MIN_HISTORY = 60     # minimum days before we start combining
ANNUAL_FACTOR = 252
TX_COST_BPS = 10     # basis points per round-trip

# Strategy display names
STRATEGY_NAMES = {
    "slow_vt": "GARCH VT",
    "risk_parity": "Risk Parity",
    "simple_12vix": "12/VIX",
    "recommended_5050": "50/50 SPY/GLD",
    "vix_cond_leverage": "VIX Cond Lev",
    "piecewise_conservative": "Piecewise Cons",
    "fear_dca": "Fear DCA",
    "adaptive_tier": "Adaptive Tier",
}

# Regime-conditional mapping (from K641 findings)
CALM_STRATEGIES = ["adaptive_tier", "recommended_5050"]
STRESS_STRATEGIES = ["piecewise_conservative", "vix_cond_leverage"]


def load_strategy_returns():
    """Load daily portfolio_return for each strategy from paper_trading.json."""
    pt_path = Path(__file__).resolve().parents[1] / "storage" / "paper_trading.json"
    with open(pt_path) as f:
        data = json.load(f)

    frames = {}
    for key, display in STRATEGY_NAMES.items():
        if key not in data:
            print(f"  [SKIP] {key} not in paper_trading.json")
            continue
        entries = data[key].get("entries", [])
        records = []
        for e in entries:
            ret = e.get("portfolio_return")
            if ret is not None:
                records.append({"date": e["data_date"], "return": ret})
        if len(records) > MIN_HISTORY:
            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            df = df[~df.index.duplicated(keep="last")]
            frames[key] = df["return"]
            print(f"  {display}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")
        else:
            print(f"  [SKIP] {key}: only {len(records)} records (need {MIN_HISTORY})")

    # Align on common dates
    returns_df = pd.DataFrame(frames)
    returns_df = returns_df.dropna()
    print(f"\n  Aligned: {len(returns_df)} common dates, {len(returns_df.columns)} strategies")
    print(f"  Period: {returns_df.index[0].date()} to {returns_df.index[-1].date()}")
    return returns_df


def load_vix():
    """Load VIX data from yfinance for regime classification."""
    import yfinance as yf
    vix = yf.download("^VIX", start="2022-01-01", end="2026-12-31",
                       progress=False, auto_adjust=True)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix = vix["Close"].dropna()
    vix.index = vix.index.tz_localize(None)
    return vix


# ── Combination Methods ─────────────────────────────────────────────

def equal_weight(returns_df):
    """1/N across all strategies."""
    n = returns_df.shape[1]
    weights = pd.DataFrame(
        np.ones_like(returns_df.values) / n,
        index=returns_df.index, columns=returns_df.columns
    )
    combined = (returns_df * weights).sum(axis=1)
    return combined, weights, "Equal Weight (1/N)"


def inverse_vol_weight(returns_df, window=ROLLING_WINDOW):
    """Weight proportional to 1/sigma_i (rolling)."""
    rolling_vol = returns_df.rolling(window, min_periods=window).std()
    inv_vol = 1.0 / rolling_vol
    inv_vol = inv_vol.replace([np.inf, -np.inf], np.nan)
    weights = inv_vol.div(inv_vol.sum(axis=1), axis=0)
    weights = weights.dropna()

    common = returns_df.index.intersection(weights.index)
    combined = (returns_df.loc[common] * weights.loc[common]).sum(axis=1)
    return combined, weights, "Inverse Volatility"


def risk_parity_weight(returns_df, window=ROLLING_WINDOW):
    """Each strategy contributes equal risk to the portfolio."""
    combined_returns = []
    weight_records = []

    for i in range(window, len(returns_df)):
        hist = returns_df.iloc[i - window:i]
        cov = hist.cov().values
        n = len(returns_df.columns)

        # Iterative risk parity (simple version)
        w = np.ones(n) / n
        for _ in range(100):
            port_vol = np.sqrt(w @ cov @ w)
            if port_vol < 1e-12:
                break
            marginal_risk = (cov @ w) / port_vol
            risk_contrib = w * marginal_risk
            target = port_vol / n
            # Adjust weights
            w_new = w * (target / (risk_contrib + 1e-12))
            w_new = w_new / w_new.sum()
            if np.max(np.abs(w_new - w)) < 1e-8:
                w = w_new
                break
            w = w_new

        w = w / w.sum()  # Normalize
        date = returns_df.index[i]
        ret = (returns_df.iloc[i].values * w).sum()
        combined_returns.append({"date": date, "return": ret})
        weight_records.append({"date": date, **{c: ww for c, ww in zip(returns_df.columns, w)}})

    combined = pd.DataFrame(combined_returns).set_index("date")["return"]
    weights = pd.DataFrame(weight_records).set_index("date")
    return combined, weights, "Risk Parity"


def max_sharpe_weight(returns_df, window=ROLLING_WINDOW):
    """Rolling Markowitz mean-variance optimization (long-only)."""
    from scipy.optimize import minimize

    combined_returns = []
    weight_records = []

    for i in range(window, len(returns_df)):
        hist = returns_df.iloc[i - window:i]
        mu = hist.mean().values * ANNUAL_FACTOR
        cov = hist.cov().values * ANNUAL_FACTOR
        n = len(returns_df.columns)

        def neg_sharpe(w):
            port_ret = w @ mu
            port_vol = np.sqrt(w @ cov @ w)
            if port_vol < 1e-12:
                return 0.0
            return -(port_ret / port_vol)

        constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        bounds = [(0.0, 1.0)] * n
        w0 = np.ones(n) / n

        result = minimize(neg_sharpe, w0, method="SLSQP",
                          bounds=bounds, constraints=constraints,
                          options={"maxiter": 200, "ftol": 1e-10})
        w = result.x if result.success else w0
        w = np.maximum(w, 0)
        w = w / w.sum()

        date = returns_df.index[i]
        ret = (returns_df.iloc[i].values * w).sum()
        combined_returns.append({"date": date, "return": ret})
        weight_records.append({"date": date, **{c: ww for c, ww in zip(returns_df.columns, w)}})

    combined = pd.DataFrame(combined_returns).set_index("date")["return"]
    weights = pd.DataFrame(weight_records).set_index("date")
    return combined, weights, "Max Sharpe (Markowitz)"


def best_2_momentum(returns_df, window=ROLLING_WINDOW):
    """Hold the 2 strategies with highest rolling Sharpe (equal weight)."""
    combined_returns = []
    weight_records = []

    for i in range(window, len(returns_df)):
        hist = returns_df.iloc[i - window:i]
        mu = hist.mean()
        sigma = hist.std()
        sharpe = mu / (sigma + 1e-12)

        # Pick top 2
        top2 = sharpe.nlargest(2).index.tolist()
        n = len(returns_df.columns)
        w = np.zeros(n)
        for col in top2:
            idx = list(returns_df.columns).index(col)
            w[idx] = 0.5

        date = returns_df.index[i]
        ret = (returns_df.iloc[i].values * w).sum()
        combined_returns.append({"date": date, "return": ret})
        wd = {c: ww for c, ww in zip(returns_df.columns, w)}
        weight_records.append({"date": date, **wd})

    combined = pd.DataFrame(combined_returns).set_index("date")["return"]
    weights = pd.DataFrame(weight_records).set_index("date")
    return combined, weights, "Best-2 Momentum"


def regime_conditional(returns_df, vix_series):
    """Calm (VIX<20): Adaptive Tier + 50/50; Stress (VIX>=20): Piecewise + VIX Cond Leverage."""
    # Align VIX with return dates
    common_dates = returns_df.index.intersection(vix_series.index)
    returns_sub = returns_df.loc[common_dates]
    vix_sub = vix_series.loc[common_dates]

    combined_returns = []
    weight_records = []
    n = len(returns_df.columns)
    cols = list(returns_df.columns)

    for date, vix_val in vix_sub.items():
        w = np.zeros(n)
        if vix_val < 20:
            # Calm: equal weight between calm strategies
            active = [s for s in CALM_STRATEGIES if s in cols]
        else:
            # Stress: equal weight between stress strategies
            active = [s for s in STRESS_STRATEGIES if s in cols]

        if len(active) == 0:
            active = cols  # fallback
        for s in active:
            w[cols.index(s)] = 1.0 / len(active)

        ret = (returns_sub.loc[date].values * w).sum()
        combined_returns.append({"date": date, "return": ret})
        weight_records.append({"date": date, **{c: ww for c, ww in zip(cols, w)}})

    combined = pd.DataFrame(combined_returns).set_index("date")["return"]
    weights = pd.DataFrame(weight_records).set_index("date")
    return combined, weights, "Regime Conditional"


# ── Evaluation ───────────────────────────────────────────────────────

def compute_metrics(returns, name=""):
    """Compute Sharpe, MDD, Calmar, Sortino, etc."""
    if len(returns) < 20:
        return {"name": name, "error": "too few observations"}

    r = returns.values if hasattr(returns, "values") else np.array(returns)
    mu = np.mean(r) * ANNUAL_FACTOR
    sigma = np.std(r, ddof=1) * np.sqrt(ANNUAL_FACTOR)
    sharpe = mu / sigma if sigma > 0 else 0.0

    # Sortino
    downside = r[r < 0]
    down_std = np.std(downside, ddof=1) * np.sqrt(ANNUAL_FACTOR) if len(downside) > 1 else sigma
    sortino = mu / down_std if down_std > 0 else 0.0

    # MDD
    cum = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = float(np.min(dd))

    # Calmar
    calmar = mu / abs(mdd) if abs(mdd) > 0 else 0.0

    # Win rate
    win_rate = np.mean(r > 0) * 100

    # Cumulative return
    cum_ret = float(cum[-1] / cum[0] - 1) if len(cum) > 0 else 0.0

    return {
        "name": name,
        "n_days": int(len(r)),
        "ann_return_pct": round(mu * 100, 2),
        "ann_vol_pct": round(sigma * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown_pct": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "win_rate_pct": round(win_rate, 1),
        "cumulative_return_pct": round(cum_ret * 100, 2),
    }


def compute_turnover(weights_df):
    """Compute average daily turnover from weight changes."""
    if len(weights_df) < 2:
        return 0.0
    diffs = weights_df.diff().abs()
    daily_turnover = diffs.sum(axis=1) / 2  # one-way turnover
    return float(daily_turnover.mean())


def compute_tx_adjusted(returns, weights_df, tx_bps=TX_COST_BPS):
    """Compute transaction-cost adjusted returns."""
    if len(weights_df) < 2:
        return returns
    diffs = weights_df.diff().abs().sum(axis=1) / 2
    common = returns.index.intersection(diffs.index)
    tx_cost = diffs.loc[common] * (tx_bps / 10000)
    adjusted = returns.loc[common] - tx_cost
    return adjusted


def rolling_sharpe(returns, window=ROLLING_WINDOW):
    """Compute rolling Sharpe ratio."""
    roll_mean = returns.rolling(window).mean() * ANNUAL_FACTOR
    roll_std = returns.rolling(window).std() * np.sqrt(ANNUAL_FACTOR)
    return (roll_mean / roll_std).dropna()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("K643: Optimal Multi-Strategy Portfolio")
    print("=" * 70)

    # 1. Load data
    print("\n[1] Loading strategy returns...")
    returns_df = load_strategy_returns()

    print("\n[2] Loading VIX data...")
    vix = load_vix()
    print(f"  VIX: {len(vix)} days ({vix.index[0].date()} to {vix.index[-1].date()})")

    # 2. Individual strategy metrics
    print("\n[3] Individual strategy performance...")
    individual_metrics = {}
    for col in returns_df.columns:
        m = compute_metrics(returns_df[col], STRATEGY_NAMES.get(col, col))
        individual_metrics[col] = m
        print(f"  {m['name']:20s}: Sharpe={m['sharpe']:6.3f}  MDD={m['max_drawdown_pct']:7.2f}%  "
              f"Calmar={m['calmar']:6.3f}  Cum={m['cumulative_return_pct']:7.2f}%")

    # 3. Correlation matrix
    print("\n[4] Correlation matrix...")
    corr_matrix = returns_df.corr()
    corr_dict = {}
    for c1 in corr_matrix.columns:
        for c2 in corr_matrix.columns:
            if c1 < c2:
                corr_dict[f"{STRATEGY_NAMES.get(c1,c1)} vs {STRATEGY_NAMES.get(c2,c2)}"] = round(
                    corr_matrix.loc[c1, c2], 4
                )

    # Average pairwise correlation
    mask = np.triu(np.ones_like(corr_matrix, dtype=bool), k=1)
    avg_corr = float(corr_matrix.values[mask].mean())
    min_corr = float(corr_matrix.values[mask].min())
    max_corr = float(corr_matrix.values[mask].max())
    print(f"  Average pairwise correlation: {avg_corr:.4f}")
    print(f"  Min: {min_corr:.4f}, Max: {max_corr:.4f}")

    # Find most and least correlated pairs
    sorted_pairs = sorted(corr_dict.items(), key=lambda x: x[1])
    print(f"  Least correlated: {sorted_pairs[0][0]} ({sorted_pairs[0][1]:.4f})")
    print(f"  Most correlated:  {sorted_pairs[-1][0]} ({sorted_pairs[-1][1]:.4f})")

    # 4. Run all combination methods
    print("\n[5] Running combination methods...")
    methods = {}

    # a) Equal weight
    ret_ew, w_ew, name_ew = equal_weight(returns_df)
    methods["equal_weight"] = (ret_ew, w_ew, name_ew)

    # b) Inverse vol
    ret_iv, w_iv, name_iv = inverse_vol_weight(returns_df)
    methods["inverse_vol"] = (ret_iv, w_iv, name_iv)

    # c) Risk parity
    ret_rp, w_rp, name_rp = risk_parity_weight(returns_df)
    methods["risk_parity_meta"] = (ret_rp, w_rp, name_rp)

    # d) Max Sharpe
    ret_ms, w_ms, name_ms = max_sharpe_weight(returns_df)
    methods["max_sharpe"] = (ret_ms, w_ms, name_ms)

    # e) Best-2
    ret_b2, w_b2, name_b2 = best_2_momentum(returns_df)
    methods["best_2"] = (ret_b2, w_b2, name_b2)

    # f) Regime conditional
    ret_rc, w_rc, name_rc = regime_conditional(returns_df, vix)
    methods["regime_conditional"] = (ret_rc, w_rc, name_rc)

    # 5. Evaluate all methods
    print("\n[6] Evaluation Results")
    print("-" * 100)
    print(f"{'Method':30s} {'Sharpe':>8s} {'Sortino':>8s} {'MDD%':>8s} {'Calmar':>8s} "
          f"{'Cum%':>8s} {'Turnover':>10s} {'NetSharpe':>10s}")
    print("-" * 100)

    combination_results = {}
    for key, (ret, wts, name) in methods.items():
        m = compute_metrics(ret, name)

        # Turnover
        turnover = compute_turnover(wts)

        # TX-adjusted
        ret_adj = compute_tx_adjusted(ret, wts)
        m_adj = compute_metrics(ret_adj, name + " (net)")

        m["avg_daily_turnover"] = round(turnover, 6)
        m["ann_turnover_pct"] = round(turnover * ANNUAL_FACTOR * 100, 2)
        m["net_sharpe"] = m_adj["sharpe"]
        m["net_ann_return_pct"] = m_adj["ann_return_pct"]

        combination_results[key] = m
        print(f"  {name:28s} {m['sharpe']:8.3f} {m['sortino']:8.3f} {m['max_drawdown_pct']:7.2f}% "
              f"{m['calmar']:8.3f} {m['cumulative_return_pct']:7.2f}% {m['ann_turnover_pct']:8.2f}% "
              f"{m['net_sharpe']:9.3f}")

    print("-" * 100)

    # Also show best individual for comparison
    best_individual_key = max(individual_metrics, key=lambda k: individual_metrics[k]["sharpe"])
    best_ind = individual_metrics[best_individual_key]
    print(f"  {'[Best Individual: ' + best_ind['name'] + ']':28s} "
          f"{best_ind['sharpe']:8.3f} {best_ind['sortino']:8.3f} {best_ind['max_drawdown_pct']:7.2f}% "
          f"{best_ind['calmar']:8.3f} {best_ind['cumulative_return_pct']:7.2f}%")

    # 6. Diversification benefit analysis
    print("\n[7] Diversification Benefit Analysis")
    max_ind_sharpe = max(m["sharpe"] for m in individual_metrics.values())
    max_ind_name = [m["name"] for m in individual_metrics.values() if m["sharpe"] == max_ind_sharpe][0]

    print(f"  Best individual Sharpe: {max_ind_sharpe:.3f} ({max_ind_name})")
    for key, m in combination_results.items():
        benefit = m["sharpe"] - max_ind_sharpe
        benefit_pct = (benefit / max_ind_sharpe) * 100 if max_ind_sharpe != 0 else 0
        marker = "+" if benefit > 0 else ""
        print(f"  {m['name']:28s}: Sharpe={m['sharpe']:.3f} ({marker}{benefit:.3f}, "
              f"{marker}{benefit_pct:.1f}%)")

    # 7. Rolling stability analysis
    print("\n[8] Rolling Sharpe Stability (std of rolling Sharpe)")
    stability_results = {}
    for col in returns_df.columns:
        rs = rolling_sharpe(returns_df[col])
        stability_results[STRATEGY_NAMES.get(col, col)] = {
            "mean_rolling_sharpe": round(float(rs.mean()), 3),
            "std_rolling_sharpe": round(float(rs.std()), 3),
            "min_rolling_sharpe": round(float(rs.min()), 3),
            "max_rolling_sharpe": round(float(rs.max()), 3),
        }
    for key, (ret, wts, name) in methods.items():
        rs = rolling_sharpe(ret)
        stability_results[name] = {
            "mean_rolling_sharpe": round(float(rs.mean()), 3),
            "std_rolling_sharpe": round(float(rs.std()), 3),
            "min_rolling_sharpe": round(float(rs.min()), 3),
            "max_rolling_sharpe": round(float(rs.max()), 3),
        }

    print(f"  {'Name':30s} {'Mean':>8s} {'Std':>8s} {'Min':>8s} {'Max':>8s}")
    for name, s in stability_results.items():
        print(f"  {name:30s} {s['mean_rolling_sharpe']:8.3f} {s['std_rolling_sharpe']:8.3f} "
              f"{s['min_rolling_sharpe']:8.3f} {s['max_rolling_sharpe']:8.3f}")

    # 8. Weight concentration analysis for Max Sharpe
    print("\n[9] Max Sharpe Weight Concentration")
    ms_weights = methods["max_sharpe"][1]
    avg_weights = ms_weights.mean()
    print("  Average allocation:")
    for col in avg_weights.index:
        if avg_weights[col] > 0.01:
            print(f"    {STRATEGY_NAMES.get(col, col):20s}: {avg_weights[col]*100:.1f}%")

    # HHI concentration index
    hhi_series = (ms_weights ** 2).sum(axis=1)
    print(f"  Average HHI: {hhi_series.mean():.4f} (1/{len(returns_df.columns)} = {1/len(returns_df.columns):.4f})")
    print(f"  → {'Concentrated' if hhi_series.mean() > 0.5 else 'Diversified'} portfolio")

    # 9. Best-2 selection frequency
    print("\n[10] Best-2 Momentum: Selection Frequency")
    b2_weights = methods["best_2"][1]
    selection_freq = (b2_weights > 0.01).mean() * 100
    print("  % of time each strategy selected:")
    for col in selection_freq.index:
        print(f"    {STRATEGY_NAMES.get(col, col):20s}: {selection_freq[col]:.1f}%")

    # 10. Regime-conditional: days in each regime
    print("\n[11] Regime Conditional: Regime Days")
    common_dates_rc = returns_df.index.intersection(vix.index)
    vix_aligned = vix.loc[common_dates_rc]
    n_calm = int((vix_aligned < 20).sum())
    n_stress = int((vix_aligned >= 20).sum())
    print(f"  Calm (VIX<20): {n_calm} days ({n_calm/len(vix_aligned)*100:.1f}%)")
    print(f"  Stress (VIX>=20): {n_stress} days ({n_stress/len(vix_aligned)*100:.1f}%)")

    # 11. Sub-period analysis: first half vs second half
    print("\n[12] Sub-period Robustness")
    mid = len(returns_df) // 2
    sub_results = {}
    for key, (ret, wts, name) in methods.items():
        # Align to returns_df index range
        common_idx = ret.index.intersection(returns_df.index)
        ret_aligned = ret.loc[common_idx]
        if len(ret_aligned) < 60:
            continue
        mid_r = len(ret_aligned) // 2
        m1 = compute_metrics(ret_aligned.iloc[:mid_r], name + " H1")
        m2 = compute_metrics(ret_aligned.iloc[mid_r:], name + " H2")
        sub_results[key] = {"H1": m1, "H2": m2}
        print(f"  {name:28s}: H1 Sharpe={m1['sharpe']:.3f}  H2 Sharpe={m2['sharpe']:.3f}  "
              f"Δ={m2['sharpe']-m1['sharpe']:+.3f}")

    # 12. Final ranking
    print("\n[13] Final Ranking (by Net Sharpe)")
    print("-" * 70)
    ranked = sorted(combination_results.items(), key=lambda x: x[1].get("net_sharpe", 0), reverse=True)
    for rank, (key, m) in enumerate(ranked, 1):
        print(f"  #{rank} {m['name']:28s}: Net Sharpe={m['net_sharpe']:.3f}  "
              f"Gross Sharpe={m['sharpe']:.3f}  MDD={m['max_drawdown_pct']:.2f}%")

    # 13. Key finding
    best_combo_key = ranked[0][0]
    best_combo = ranked[0][1]
    diversification_works = best_combo["sharpe"] > max_ind_sharpe

    print("\n" + "=" * 70)
    print("KEY FINDING:")
    if diversification_works:
        print(f"  Strategy diversification ADDS value.")
        print(f"  Best combination ({best_combo['name']}): Sharpe={best_combo['sharpe']:.3f}")
        print(f"  vs Best individual ({max_ind_name}): Sharpe={max_ind_sharpe:.3f}")
        print(f"  Improvement: {(best_combo['sharpe']-max_ind_sharpe)/max_ind_sharpe*100:+.1f}%")
    else:
        print(f"  Strategy diversification does NOT beat the single best strategy.")
        print(f"  Best combination ({best_combo['name']}): Sharpe={best_combo['sharpe']:.3f}")
        print(f"  Best individual ({max_ind_name}): Sharpe={max_ind_sharpe:.3f}")
        print(f"  Shortfall: {(best_combo['sharpe']-max_ind_sharpe)/max_ind_sharpe*100:+.1f}%")
    print("=" * 70)

    # ── Save results ──────────────────────────────────────────────
    results = {
        "experiment_id": "K643",
        "title": "Optimal Multi-Strategy Portfolio",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "paper_trading.json + yfinance (VIX)",
        "data_period": f"{returns_df.index[0].date()} to {returns_df.index[-1].date()}",
        "n_common_days": int(len(returns_df)),
        "n_strategies": int(len(returns_df.columns)),
        "strategies_used": {k: STRATEGY_NAMES[k] for k in returns_df.columns},
        "rolling_window": ROLLING_WINDOW,
        "methodology": {
            "equal_weight": "1/N across all strategies",
            "inverse_vol": "Weight ~ 1/sigma_i, rolling 60-day",
            "risk_parity_meta": "Each strategy contributes equal risk (iterative)",
            "max_sharpe": "Rolling Markowitz mean-variance, long-only constrained",
            "best_2": "Hold 2 strategies with highest rolling 60-day Sharpe, equal weight",
            "regime_conditional": "Calm (VIX<20): Adaptive Tier + 50/50; Stress: Piecewise + VIX Cond Lev",
        },
        "references": [
            "DeMiguel et al. (2009) Optimal vs Naive Diversification, RFS",
            "Maillard et al. (2010) ERC Portfolios, JPM",
        ],
        "individual_metrics": individual_metrics,
        "combination_metrics": combination_results,
        "correlation": {
            "avg_pairwise": round(avg_corr, 4),
            "min_pairwise": round(min_corr, 4),
            "max_pairwise": round(max_corr, 4),
            "pairs": corr_dict,
        },
        "stability": stability_results,
        "sub_period_robustness": {
            k: {
                "H1_sharpe": v["H1"]["sharpe"],
                "H2_sharpe": v["H2"]["sharpe"],
                "delta": round(v["H2"]["sharpe"] - v["H1"]["sharpe"], 3),
            }
            for k, v in sub_results.items()
        },
        "max_sharpe_concentration": {
            "avg_hhi": round(float(hhi_series.mean()), 4),
            "avg_weights": {STRATEGY_NAMES.get(c, c): round(float(v), 4) for c, v in avg_weights.items()},
        },
        "best_2_selection_freq": {
            STRATEGY_NAMES.get(c, c): round(float(v), 1) for c, v in selection_freq.items()
        },
        "regime_split": {
            "calm_days": n_calm,
            "stress_days": n_stress,
            "calm_pct": round(n_calm / len(vix_aligned) * 100, 1),
        },
        "key_finding": {
            "diversification_adds_value": diversification_works,
            "best_combination": best_combo["name"],
            "best_combination_sharpe": best_combo["sharpe"],
            "best_combination_net_sharpe": best_combo.get("net_sharpe", None),
            "best_individual": max_ind_name,
            "best_individual_sharpe": max_ind_sharpe,
            "improvement_pct": round(
                (best_combo["sharpe"] - max_ind_sharpe) / max_ind_sharpe * 100, 1
            ) if max_ind_sharpe != 0 else 0,
        },
    }

    out_path = Path(__file__).resolve().parent / "k643_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == "__main__":
    main()
