#!/usr/bin/env python3
"""
K1047: Agent-Based Model — VT Adoption Rate Impact on Market Dynamics (Formal Version)

Type: Simulation / Theoretical (NOT empirical)
Prior work: K742 (simplified, stylized), K827 (Kyle market maker), K864 (heterogeneous)

Core Question: If X% of investors adopt 12/VIX strategy, how does market volatility change?
Is there a tipping point? How does VT alpha decay with adoption?

Model Architecture (Brock & Hommes 1998 style):
  Price is determined by aggregate demand through a market maker:
    r_t = (1/lambda) * (D_t / N)

  where lambda is the market depth parameter (higher = more liquid).

  Agent Types:
    - Fundamentalist (F): d_i = phi * (p_fund - p_t) / p_t + noise
      Contrarian: buys when price below fundamental, sells when above
    - Chartist (C): d_i = chi * sum(r_{t-k}, k=1..L) + noise
      Momentum: buys recent winners
    - VT Agent (V): d_i = min(12/VIX_t, cap) * base + noise
      Volatility target: increases exposure when VIX is low, reduces when high

  Key Design Choices:
    - ALL return is endogenous (comes from agent demands + noise)
    - No exogenous drift — fundamental value is fixed
    - lambda calibrated so that baseline (0% VT) produces ~16% annual vol
    - VIX is endogenous realized vol

References:
  - LeBaron (2006): Agent-based computational finance
  - Hommes (2006): Heterogeneous agent models in economics and finance
  - Brock & Hommes (1998): Heterogeneous beliefs and routes to chaos
  - Lux & Marchesi (1999): Scaling and criticality in a stochastic multi-agent model
  - Farmer & Foley (2009): The economy needs agent-based modelling (Nature)
  - Giardina & Bouchaud (2003): Bubbles, crashes and intermittency in agent based models
  - K742/K827/K864: Prior VT crowding simulations in this project

Seed: np.random.default_rng(42) for reproducibility
"""

import numpy as np
import json
import time
import os
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────
CONFIG = {
    "n_agents": 1000,
    "n_days": 5000,        # ~20 years of trading
    "n_sims": 50,          # Monte Carlo repetitions
    "vt_fractions": [0.0, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90],

    # Market depth — calibrated so baseline ~16% annual vol
    # Return = (1/lambda) * (avg_demand)
    # With sigma_noise=1.0 and N=1000 agents, avg_demand std ≈ 1/sqrt(1000) ≈ 0.032
    # Target daily vol ≈ 0.01, so lambda ≈ 0.032/0.01 ≈ 3.2
    "lambda_depth": 3.0,

    # Agent parameters
    "phi_fundamental": 4.0,     # fundamentalist reversion strength
    "chi_chartist": 2.0,        # chartist momentum strength
    "chartist_lookback": 5,     # days of past returns for momentum
    "sigma_agent_noise": 1.0,   # idiosyncratic noise std per agent

    # VT parameters
    "vt_base_demand": 1.0,      # VT agent's base demand (scaled by 12/VIX)
    "vt_cap": 1.5,              # max VT multiplier

    # Fundamental
    "p0": 100.0,
    "p_fundamental": 100.0,     # constant fair value

    # VIX proxy
    "vix_window": 22,
    "default_vix": 16.0,        # initial VIX guess

    # Agent composition
    "fundamentalist_share_of_non_vt": 0.6,
}

# ── Simulation Engine ─────────────────────────────────────────────────────

def run_single_simulation(rng, config, vt_fraction):
    """
    Fully endogenous ABM: returns come from agent demands + noise.

    Market clearing: r_t = (1/lambda) * mean(demands_all_agents)

    This means:
      - When demands net positive -> price rises
      - When demands net negative -> price falls
      - Volatility is entirely endogenous (from agent interaction + noise)
    """
    N = config["n_agents"]
    T = config["n_days"]
    phi = config["phi_fundamental"]
    chi = config["chi_chartist"]
    L = config["chartist_lookback"]
    sigma_noise = config["sigma_agent_noise"]
    vt_base = config["vt_base_demand"]
    vt_cap = config["vt_cap"]
    lam = config["lambda_depth"]
    p0 = config["p0"]
    p_fund = config["p_fundamental"]
    vix_window = config["vix_window"]
    default_vix = config["default_vix"]
    f_share = config["fundamentalist_share_of_non_vt"]

    # Assign agent types
    n_vt = int(N * vt_fraction)
    n_non_vt = N - n_vt
    n_fund = int(n_non_vt * f_share)
    n_chart = n_non_vt - n_fund

    # Arrays
    prices = np.zeros(T)
    prices[0] = p0
    log_returns = np.zeros(T)

    # PnL tracking
    cum_pnl_fund = np.zeros(n_fund) if n_fund > 0 else np.array([])
    cum_pnl_chart = np.zeros(n_chart) if n_chart > 0 else np.array([])
    cum_pnl_vt = np.zeros(n_vt) if n_vt > 0 else np.array([])

    vix_t = default_vix
    prev_vt_position = min(12.0 / default_vix, vt_cap) * vt_base  # initial VT position

    for t in range(1, T):
        # ── VIX proxy (endogenous realized vol) ──
        if t >= vix_window + 1:
            recent = log_returns[t - vix_window:t]
            rvol = np.std(recent) * np.sqrt(252)
            vix_t = max(rvol * 100, 5.0)

        # ── Agent demands ──
        # NOTE: demands represent *order flow* (change in position), not position level.
        # Positive demand = buying, negative = selling.

        # 1. Fundamentalists: contrarian
        # Buy when price below fundamental, sell when above
        deviation = (p_fund - prices[t-1]) / prices[t-1]
        if n_fund > 0:
            demand_fund = phi * deviation + rng.normal(0, sigma_noise, n_fund)
        else:
            demand_fund = np.array([])

        # 2. Chartists: momentum
        if t >= L + 1:
            mom = np.sum(log_returns[t-L:t])
        else:
            mom = np.sum(log_returns[max(0, t-L):t])

        if n_chart > 0:
            demand_chart = chi * mom + rng.normal(0, sigma_noise, n_chart)
        else:
            demand_chart = np.array([])

        # 3. VT agents: demand = CHANGE in desired position
        # Desired position = min(12/VIX, cap)
        # When VIX rises (crisis) -> desired position drops -> VT SELLS (negative demand)
        # When VIX falls (calm) -> desired position rises -> VT BUYS (positive demand)
        # This is the actual mechanism: VT = contrarian w.r.t. volatility
        if n_vt > 0:
            new_vt_position = min(12.0 / vix_t, vt_cap) * vt_base
            vt_rebalance = new_vt_position - prev_vt_position  # order flow
            demand_vt = vt_rebalance + rng.normal(0, sigma_noise, n_vt)
            prev_vt_position = new_vt_position
        else:
            demand_vt = np.array([])

        # ── Market clearing ──
        all_demands = np.concatenate([
            d for d in [demand_fund, demand_chart, demand_vt] if len(d) > 0
        ])
        avg_demand = np.mean(all_demands)

        # Return is determined by average demand divided by market depth
        log_ret = avg_demand / lam
        log_returns[t] = log_ret
        prices[t] = prices[t-1] * np.exp(log_ret)

        # ── PnL: position * realized return ──
        if n_fund > 0:
            cum_pnl_fund += demand_fund * log_ret
        if n_chart > 0:
            cum_pnl_chart += demand_chart * log_ret
        if n_vt > 0:
            cum_pnl_vt += demand_vt * log_ret

    # ── Summary statistics ──
    returns = log_returns[1:]
    n_years = T / 252.0

    # Volatility
    ann_vol = float(np.std(returns) * np.sqrt(252))

    # Max drawdown
    cum_ret = np.cumsum(returns)
    running_max = np.maximum.accumulate(cum_ret)
    max_dd = float(np.min(cum_ret - running_max))

    # Higher moments
    mu_r = np.mean(returns)
    sig_r = np.std(returns)
    if sig_r > 1e-10:
        kurtosis = float(np.mean(((returns - mu_r) / sig_r) ** 4) - 3.0)
        skewness = float(np.mean(((returns - mu_r) / sig_r) ** 3))
    else:
        kurtosis, skewness = 0.0, 0.0

    # Autocorrelation of |r| (vol clustering)
    abs_r = np.abs(returns)
    abs_dm = abs_r - np.mean(abs_r)
    v0 = np.mean(abs_dm ** 2)
    ac_abs = float(np.mean(abs_dm[:-1] * abs_dm[1:]) / v0) if v0 > 1e-15 else 0.0

    # Autocorrelation of r (return predictability)
    r_dm = returns - mu_r
    v_r = np.mean(r_dm ** 2)
    ac_r = float(np.mean(r_dm[:-1] * r_dm[1:]) / v_r) if v_r > 1e-15 else 0.0

    # Agent performance
    def agent_perf(pnl):
        if len(pnl) == 0:
            return None, None
        m = float(np.mean(pnl)) / n_years
        s = float(np.std(pnl)) / np.sqrt(n_years)
        return m, m / s if s > 1e-10 else None

    f_ret, f_sh = agent_perf(cum_pnl_fund)
    c_ret, c_sh = agent_perf(cum_pnl_chart)
    v_ret, v_sh = agent_perf(cum_pnl_vt)

    return {
        "annualized_volatility": ann_vol,
        "max_drawdown": max_dd,
        "excess_kurtosis": kurtosis,
        "skewness": skewness,
        "ac_abs_return_lag1": ac_abs,
        "ac_return_lag1": ac_r,
        "fund_sharpe": f_sh,
        "chart_sharpe": c_sh,
        "vt_sharpe": v_sh,
        "fund_ann_return": f_ret,
        "chart_ann_return": c_ret,
        "vt_ann_return": v_ret,
        "final_price": float(prices[-1]),
        "n_fundamentalist": n_fund,
        "n_chartist": n_chart,
        "n_vt": n_vt,
    }


def run_monte_carlo(config):
    """Run full Monte Carlo across all VT fractions."""
    master_rng = np.random.default_rng(42)
    results = {}
    total = len(config["vt_fractions"]) * config["n_sims"]
    count = 0

    for vt_frac in config["vt_fractions"]:
        key = f"{vt_frac:.0%}"
        runs = []

        for _ in range(config["n_sims"]):
            seed = master_rng.integers(0, 2**31)
            r = run_single_simulation(np.random.default_rng(seed), config, vt_frac)
            runs.append(r)
            count += 1
            if count % 50 == 0:
                print(f"  Progress: {count}/{total} ({count/total*100:.0f}%)")

        # Aggregate
        metrics = {}
        for mk in ["annualized_volatility", "max_drawdown", "excess_kurtosis",
                    "skewness", "ac_abs_return_lag1", "ac_return_lag1",
                    "fund_sharpe", "chart_sharpe", "vt_sharpe",
                    "fund_ann_return", "chart_ann_return", "vt_ann_return"]:
            vals = [r[mk] for r in runs if r[mk] is not None and np.isfinite(r[mk])]
            if vals:
                metrics[mk] = {
                    "mean": float(np.mean(vals)),
                    "std": float(np.std(vals)),
                    "median": float(np.median(vals)),
                    "q5": float(np.percentile(vals, 5)),
                    "q95": float(np.percentile(vals, 95)),
                }
            else:
                metrics[mk] = None

        metrics["n_fundamentalist"] = runs[0]["n_fundamentalist"]
        metrics["n_chartist"] = runs[0]["n_chartist"]
        metrics["n_vt"] = runs[0]["n_vt"]
        results[key] = metrics

        # Print
        vol = metrics["annualized_volatility"]["mean"]
        mdd = metrics["max_drawdown"]["mean"]
        kurt = metrics["excess_kurtosis"]["mean"]
        ac = metrics["ac_abs_return_lag1"]["mean"]
        vts = metrics["vt_sharpe"]["mean"] if metrics["vt_sharpe"] else float('nan')
        print(f"  VT={key}: vol={vol:.4f}, MDD={mdd:.3f}, "
              f"kurt={kurt:.2f}, AC|r|={ac:.3f}, VT_Sharpe={vts:.3f}")

    return results


def generate_charts(results, output_dir):
    """Generate publication-quality charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 11})

    fracs = sorted(results.keys(), key=lambda x: float(x.strip('%'))/100)
    fvals = [float(f.strip('%'))/100 for f in fracs]

    def get_mean(metric):
        return [results[f][metric]["mean"] for f in fracs]

    def get_ci(metric):
        q5 = [results[f][metric]["q5"] for f in fracs]
        q95 = [results[f][metric]["q95"] for f in fracs]
        return q5, q95

    # ── Chart 1: Market Dynamics (2x2) ────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('K1047: Market Dynamics vs VT (12/VIX) Adoption Rate\n'
                 'ABM: 1000 agents, 5000 days, 50 MC runs | Fully endogenous returns',
                 fontsize=12, fontweight='bold')

    # (a) Volatility
    ax = axes[0, 0]
    m = get_mean("annualized_volatility")
    q5, q95 = get_ci("annualized_volatility")
    ax.plot(fvals, m, 'b-o', lw=2, ms=8)
    ax.fill_between(fvals, q5, q95, alpha=0.2, color='blue')
    ax.axhline(y=m[0], color='gray', ls='--', alpha=0.5, label=f'Baseline: {m[0]:.3f}')
    ax.set_xlabel('VT Adoption Fraction')
    ax.set_ylabel('Annualized Volatility')
    ax.set_title('(a) Market Volatility')
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    # (b) Max Drawdown
    ax = axes[0, 1]
    m = get_mean("max_drawdown")
    q5, q95 = get_ci("max_drawdown")
    ax.plot(fvals, m, 'r-s', lw=2, ms=8)
    ax.fill_between(fvals, q5, q95, alpha=0.2, color='red')
    ax.set_xlabel('VT Adoption Fraction')
    ax.set_ylabel('Max Drawdown (log)')
    ax.set_title('(b) Maximum Drawdown')
    ax.grid(True, alpha=0.3)

    # (c) Kurtosis
    ax = axes[1, 0]
    m = get_mean("excess_kurtosis")
    q5, q95 = get_ci("excess_kurtosis")
    ax.plot(fvals, m, 'g-^', lw=2, ms=8)
    ax.fill_between(fvals, q5, q95, alpha=0.2, color='green')
    ax.set_xlabel('VT Adoption Fraction')
    ax.set_ylabel('Excess Kurtosis')
    ax.set_title('(c) Tail Heaviness')
    ax.grid(True, alpha=0.3)

    # (d) Vol clustering
    ax = axes[1, 1]
    m = get_mean("ac_abs_return_lag1")
    q5, q95 = get_ci("ac_abs_return_lag1")
    ax.plot(fvals, m, 'm-D', lw=2, ms=8)
    ax.fill_between(fvals, q5, q95, alpha=0.2, color='purple')
    ax.set_xlabel('VT Adoption Fraction')
    ax.set_ylabel('AC(|r|, lag=1)')
    ax.set_title('(d) Volatility Clustering')
    ax.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    c1 = os.path.join(output_dir, 'k1047_market_dynamics.png')
    plt.savefig(c1, dpi=150, bbox_inches='tight')
    plt.close()

    # ── Chart 2: Alpha Decay ──────────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    fig.suptitle('K1047: VT Strategy Alpha vs Adoption Rate',
                 fontsize=12, fontweight='bold')

    # (a) Sharpe by type
    ax = axes[0]
    for mk, label, col, mkr in [
        ("fund_sharpe", "Fundamentalist", "blue", "o"),
        ("chart_sharpe", "Chartist", "red", "s"),
        ("vt_sharpe", "VT (12/VIX)", "green", "^"),
    ]:
        xs, ys = [], []
        for f in fracs:
            v = float(f.strip('%'))/100
            d = results[f].get(mk)
            if d and d["mean"] is not None and np.isfinite(d["mean"]):
                xs.append(v)
                ys.append(d["mean"])
        if xs:
            ax.plot(xs, ys, f'-{mkr}', lw=2, label=label, color=col, ms=7)

    ax.set_xlabel('VT Adoption Fraction')
    ax.set_ylabel('Sharpe Ratio')
    ax.set_title('(a) Agent-Type Sharpe Ratios')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color='k', ls='--', alpha=0.3)

    # (b) Alpha = VT Sharpe - avg(F, C) Sharpe
    ax = axes[1]
    axs, ays = [], []
    for f in fracs:
        v = float(f.strip('%'))/100
        vs = results[f].get("vt_sharpe")
        if not vs or vs["mean"] is None or not np.isfinite(vs["mean"]):
            continue
        nvt = []
        for k in ["fund_sharpe", "chart_sharpe"]:
            d = results[f].get(k)
            if d and d["mean"] is not None and np.isfinite(d["mean"]):
                nvt.append(d["mean"])
        if nvt:
            axs.append(v)
            ays.append(vs["mean"] - np.mean(nvt))

    if axs:
        ax.plot(axs, ays, '-^', lw=2.5, ms=9, color='darkgreen')
        ax.fill_between(axs, 0, ays, alpha=0.15, color='green')

    ax.set_xlabel('VT Adoption Fraction')
    ax.set_ylabel('VT Alpha (excess Sharpe over non-VT avg)')
    ax.set_title('(b) VT Alpha Decay (Crowding Cost)')
    ax.axhline(y=0, color='k', ls='--', alpha=0.5)
    ax.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.92])
    c2 = os.path.join(output_dir, 'k1047_alpha_decay.png')
    plt.savefig(c2, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"  Chart 1: {c1}")
    print(f"  Chart 2: {c2}")
    return c1, c2


def analyze_results(results):
    """Derive tipping points, alpha decay, and conclusions."""
    fracs = sorted(results.keys(), key=lambda x: float(x.strip('%'))/100)

    base_vol = results["0%"]["annualized_volatility"]["mean"]

    # Tipping
    tipping = {
        "baseline_volatility": base_vol,
        "trajectory": {},
        "tipping_10pct": None,
        "tipping_25pct": None,
    }
    for f in fracs:
        v = results[f]["annualized_volatility"]["mean"]
        ch = (v - base_vol) / base_vol * 100
        tipping["trajectory"][f] = {"vol": v, "change_pct": ch}
        if ch > 10 and not tipping["tipping_10pct"]:
            tipping["tipping_10pct"] = float(f.strip('%'))/100
        if ch > 25 and not tipping["tipping_25pct"]:
            tipping["tipping_25pct"] = float(f.strip('%'))/100

    # Alpha decay
    alpha_decay = {}
    for f in fracs:
        fv = float(f.strip('%'))/100
        vs = results[f].get("vt_sharpe")
        if not vs or vs["mean"] is None or not np.isfinite(vs["mean"]):
            continue
        nvt_sh = []
        for k in ["fund_sharpe", "chart_sharpe"]:
            d = results[f].get(k)
            if d and d["mean"] is not None and np.isfinite(d["mean"]):
                nvt_sh.append(d["mean"])
        if nvt_sh:
            alpha_decay[f] = {
                "vt_sharpe": vs["mean"],
                "avg_non_vt": float(np.mean(nvt_sh)),
                "alpha": vs["mean"] - float(np.mean(nvt_sh)),
            }

    # Conclusions
    conclusions = []

    # Q1
    v0 = results["0%"]["annualized_volatility"]["mean"]
    v90 = results["90%"]["annualized_volatility"]["mean"]
    ch = (v90 - v0) / v0 * 100
    conclusions.append({
        "question": "Q1: Does VT adoption increase or decrease market volatility?",
        "answer": f"Baseline vol={v0:.4f}, 90% VT vol={v90:.4f} ({ch:+.1f}%)",
        "interpretation": "Increases" if ch > 5 else "Decreases" if ch < -5 else "Roughly neutral",
    })

    # Q2
    tp = tipping["tipping_10pct"]
    conclusions.append({
        "question": "Q2: Is there a tipping point?",
        "answer": f"Vol exceeds baseline by >10% at {tp:.0%}" if tp else "No tipping detected",
    })

    # Q3
    akeys = sorted(alpha_decay.keys(), key=lambda x: float(x.strip('%'))/100)
    if len(akeys) >= 2:
        a1 = alpha_decay[akeys[0]]["alpha"]
        a2 = alpha_decay[akeys[-1]]["alpha"]
        conclusions.append({
            "question": "Q3: How does VT alpha decay with adoption?",
            "answer": f"Alpha at {akeys[0]}={a1:.3f}, at {akeys[-1]}={a2:.3f}",
            "decays": a2 < a1,
        })

    # Q4
    k90 = results["90%"]["excess_kurtosis"]["mean"]
    vr = v90 / v0 if v0 > 1e-10 else float('nan')
    conclusions.append({
        "question": "Q4: Does K742's 'always converge' hold?",
        "answer": f"At 90% VT: kurtosis={k90:.2f}, vol_ratio={vr:.2f}. "
                  + ("Stable -- K742 confirmed." if k90 < 5 and vr < 2
                     else "Instability detected -- K742 needs qualification."),
    })

    # Q5
    ac0 = results["0%"]["ac_abs_return_lag1"]["mean"]
    ac90 = results["90%"]["ac_abs_return_lag1"]["mean"]
    conclusions.append({
        "question": "Q5: Does VT change volatility clustering?",
        "answer": f"AC(|r|) at 0%={ac0:.4f}, at 90%={ac90:.4f}",
    })

    return tipping, alpha_decay, conclusions


def main():
    out = os.path.dirname(os.path.abspath(__file__))

    print("=" * 72)
    print("K1047: Agent-Based Model — VT Adoption Rate Impact")
    print("  Type: Simulation / Theoretical (NOT empirical)")
    print(f"  N={CONFIG['n_agents']}, T={CONFIG['n_days']}, MC={CONFIG['n_sims']}")
    print(f"  VT fractions: {CONFIG['vt_fractions']}")
    print(f"  lambda_depth={CONFIG['lambda_depth']}, sigma_noise={CONFIG['sigma_agent_noise']}")
    print(f"  Fully endogenous returns (no exogenous drift)")
    print(f"  Seed: np.random.default_rng(42)")
    print("=" * 72)

    t0 = time.time()

    print("\n[1/3] Monte Carlo simulations...")
    results = run_monte_carlo(CONFIG)
    print(f"  Done in {time.time()-t0:.1f}s")

    print("\n[2/3] Analysis...")
    tipping, alpha_decay, conclusions = analyze_results(results)
    for c in conclusions:
        print(f"\n  {c['question']}")
        print(f"    {c['answer']}")

    print("\n[3/3] Charts...")
    c1, c2 = generate_charts(results, out)

    # Save
    output = {
        "experiment_id": "K1047",
        "title": "ABM: VT (12/VIX) Crowding Impact on Market Dynamics -- Formal Version",
        "type": "simulation",
        "proposer": "Claude",
        "executor": "Claude",
        "date": "2026-04-11",
        "data_source": "Pure simulation (no external data)",
        "description": (
            "Formal ABM with 3 agent types (Fundamentalist, Chartist, VT/12-VIX) "
            "and fully endogenous returns. Studies how VT adoption rate affects "
            "market volatility, tail risk, vol clustering, and VT alpha. "
            "Extends K742/K827/K864."
        ),
        "config": CONFIG,
        "results_by_vt_fraction": results,
        "tipping_analysis": tipping,
        "alpha_decay": alpha_decay,
        "conclusions": conclusions,
        "charts": [os.path.basename(c1), os.path.basename(c2)],
        "references": [
            "LeBaron (2006): Agent-based computational finance",
            "Hommes (2006): Heterogeneous agent models in economics and finance",
            "Brock & Hommes (1998): Heterogeneous beliefs and routes to chaos",
            "Lux & Marchesi (1999): Scaling and criticality in a stochastic multi-agent model",
            "Farmer & Foley (2009): The economy needs agent-based modelling (Nature)",
            "Giardina & Bouchaud (2003): Bubbles, crashes and intermittency",
            "K742: 12/VIX Crowding Risk Simulation (simplified)",
            "K827: ABM VT Crowding with Kyle MM",
            "K864: Heterogeneous ABM with strategy diversity",
        ],
        "limitations": [
            "Simplified market microstructure (single depth parameter)",
            "No transaction costs",
            "Agents homogeneous within class (no parameter dispersion)",
            "No adaptive learning or strategy switching",
            "Fundamental value is constant (no earnings growth/shocks)",
            "VIX proxy is realized vol, not option-implied",
            "Model-dependent results",
            "N=1000 agents is small vs real markets",
            "No margin constraints or regulatory limits",
            "Equal capital per agent",
        ],
        "seed": 42,
        "runtime_seconds": round(time.time() - t0, 1),
    }

    rpath = os.path.join(out, 'k1047_results.json')
    with open(rpath, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  Results: {rpath}")

    # Summary table
    fracs = sorted(results.keys(), key=lambda x: float(x.strip('%'))/100)
    print("\n" + "=" * 95)
    print("SUMMARY TABLE")
    print("=" * 95)
    print(f"{'VT%':<8} {'Vol':>8} {'MDD':>8} {'Kurt':>8} {'AC|r|':>8} {'Skew':>8} "
          f"{'VT_Sh':>8} {'F_Sh':>8} {'C_Sh':>8}")
    print("-" * 95)
    for f in fracs:
        r = results[f]
        def g(k):
            d = r.get(k)
            return d["mean"] if d else float('nan')
        print(f"{f:<8} {g('annualized_volatility'):>8.4f} {g('max_drawdown'):>8.3f} "
              f"{g('excess_kurtosis'):>8.2f} {g('ac_abs_return_lag1'):>8.4f} "
              f"{g('skewness'):>8.4f} {g('vt_sharpe'):>8.3f} "
              f"{g('fund_sharpe'):>8.3f} {g('chart_sharpe'):>8.3f}")

    print(f"\nRuntime: {time.time()-t0:.1f}s")
    print("Done.")


if __name__ == "__main__":
    main()
