#!/usr/bin/env python3
"""K1400: 退休族房貸決策 — A 一次還清 / B 繼續繳 / C 還一半 的 30 年提領模擬。

Method: block bootstrap 月度 TWII log returns 1997-07 ~ 2026-05;
10,000 paths × 360 月 (30 年); 三策略 + 房貸利率 sensitivity (1.5%/2.2%/3.0%).

Reproducible: seed=42. No lookahead: month-end return -> month-end withdrawal.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

ROOT = Path(__file__).parent
REPO = ROOT.parent.parent
DATA_OLD = REPO / "paper/taiwan-vt/data/_twii_1997_2007_snapshot.csv"
DATA_NEW = REPO / "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"

SEED = 42
N_PATHS = 10_000
HORIZON_MONTHS = 360  # 30 years
BLOCK = 12  # months

# Baseline scenario
INITIAL_WEALTH = 10_000_000  # 1000 萬
MORTGAGE_BALANCE = 3_000_000  # 300 萬
MORTGAGE_YEARS_REMAINING = 15
MORTGAGE_MONTHS = MORTGAGE_YEARS_REMAINING * 12
LIVING_COST_MONTHLY = 30_000  # 月生活費 (real, t=0)
INFLATION_ANNUAL = 0.02
INFLATION_MONTHLY = (1 + INFLATION_ANNUAL) ** (1 / 12) - 1


def load_twii_monthly() -> pd.Series:
    """合併 1997-2007 snapshot + 2008-2026 panel；輸出月底 close, log returns."""
    df1 = pd.read_csv(DATA_OLD, comment="#", parse_dates=["date"])
    df1 = df1[["date", "twii_close"]].dropna()
    df2 = pd.read_csv(DATA_NEW, parse_dates=["date"])
    df2 = df2[["date", "twii_close"]].dropna()
    df = pd.concat([df1, df2], ignore_index=True).drop_duplicates(subset="date").sort_values("date")
    df = df.set_index("date")
    monthly_close = df["twii_close"].resample("ME").last().dropna()
    log_ret = np.log(monthly_close / monthly_close.shift(1)).dropna()
    return log_ret


def mortgage_monthly_payment(balance: float, annual_rate: float, months: int) -> float:
    """等額本息月供。"""
    if balance <= 0:
        return 0.0
    r = annual_rate / 12
    if r == 0:
        return balance / months
    return balance * r * (1 + r) ** months / ((1 + r) ** months - 1)


def block_bootstrap(returns: np.ndarray, n_paths: int, horizon: int, block: int, seed: int) -> np.ndarray:
    """Return (n_paths, horizon) log returns."""
    rng = np.random.default_rng(seed)
    n_obs = len(returns)
    n_blocks_per_path = (horizon + block - 1) // block
    paths = np.empty((n_paths, horizon))
    for i in range(n_paths):
        starts = rng.integers(0, n_obs - block + 1, size=n_blocks_per_path)
        out = np.concatenate([returns[s : s + block] for s in starts])
        paths[i] = out[:horizon]
    return paths


def simulate_strategy(
    paths_log_ret: np.ndarray,
    initial_portfolio: float,
    mortgage_payment_monthly: float,
    mortgage_months_active: int,
    living_cost_initial: float,
) -> dict:
    """Run all paths under a strategy. Return summary stats."""
    n_paths, horizon = paths_log_ret.shape
    portfolio = np.full(n_paths, float(initial_portfolio))
    bust_month = np.full(n_paths, -1, dtype=int)
    final_values = np.empty(n_paths)
    # Sim
    alive = np.ones(n_paths, dtype=bool)
    for m in range(horizon):
        # apply month return (only to alive paths; dead paths stay at 0)
        portfolio[alive] = portfolio[alive] * np.exp(paths_log_ret[alive, m])
        # withdraw: living cost (inflation-adjusted) + mortgage payment (nominal fixed, only if mortgage still active)
        living = living_cost_initial * (1 + INFLATION_MONTHLY) ** m
        if m < mortgage_months_active:
            withdraw = living + mortgage_payment_monthly
        else:
            withdraw = living
        portfolio[alive] = portfolio[alive] - withdraw
        # bust detection: newly bust this month
        new_bust = (portfolio < 0) & alive
        bust_month[new_bust] = m
        portfolio[new_bust] = 0.0
        alive[new_bust] = False
    final_values = portfolio
    return {
        "bust_rate": float((bust_month >= 0).mean()),
        "median_bust_month": float(np.median(bust_month[bust_month >= 0])) if (bust_month >= 0).any() else None,
        "final_p5": float(np.percentile(final_values, 5)),
        "final_p25": float(np.percentile(final_values, 25)),
        "final_p50": float(np.percentile(final_values, 50)),
        "final_p75": float(np.percentile(final_values, 75)),
        "final_p95": float(np.percentile(final_values, 95)),
        "final_mean": float(final_values.mean()),
        "_final_values": final_values,
        "_bust_month": bust_month,
    }


def run_scenario(mortgage_rate: float, paths_log_ret: np.ndarray) -> dict:
    payment = mortgage_monthly_payment(MORTGAGE_BALANCE, mortgage_rate, MORTGAGE_MONTHS)
    # Strategy A: pay off → portfolio = wealth - mortgage; no mortgage payment
    a = simulate_strategy(
        paths_log_ret,
        initial_portfolio=INITIAL_WEALTH - MORTGAGE_BALANCE,
        mortgage_payment_monthly=0,
        mortgage_months_active=0,
        living_cost_initial=LIVING_COST_MONTHLY,
    )
    # Strategy B: keep mortgage → portfolio = wealth; monthly withdraw includes mortgage payment
    b = simulate_strategy(
        paths_log_ret,
        initial_portfolio=INITIAL_WEALTH,
        mortgage_payment_monthly=payment,
        mortgage_months_active=MORTGAGE_MONTHS,
        living_cost_initial=LIVING_COST_MONTHLY,
    )
    # Strategy C: pay half (150萬) → portfolio = wealth - 150萬; mortgage 150 萬
    half_balance = MORTGAGE_BALANCE / 2
    payment_half = mortgage_monthly_payment(half_balance, mortgage_rate, MORTGAGE_MONTHS)
    c = simulate_strategy(
        paths_log_ret,
        initial_portfolio=INITIAL_WEALTH - half_balance,
        mortgage_payment_monthly=payment_half,
        mortgage_months_active=MORTGAGE_MONTHS,
        living_cost_initial=LIVING_COST_MONTHLY,
    )
    return {
        "mortgage_rate": mortgage_rate,
        "monthly_payment_full": payment,
        "monthly_payment_half": payment_half,
        "A_payoff": a,
        "B_keep": b,
        "C_half": c,
    }


def main():
    (ROOT / "figures").mkdir(parents=True, exist_ok=True)
    print("Loading TWII monthly data...")
    log_ret = load_twii_monthly()
    print(f"  {len(log_ret)} monthly obs from {log_ret.index[0].date()} to {log_ret.index[-1].date()}")
    print(f"  monthly mean={log_ret.mean():.4f}, std={log_ret.std():.4f}")
    # log_ret mean × 12 = annualized log return (≈ geometric)
    geom_log_annual = log_ret.mean() * 12
    arr_simple = np.exp(log_ret) - 1
    arith_simple_annual = arr_simple.mean() * 12
    print(f"  arith simple annual ≈ {arith_simple_annual:.4f} ({arith_simple_annual*100:.2f}%)")
    print(f"  geom log annual ≈ {geom_log_annual:.4f} ({(np.exp(geom_log_annual)-1)*100:.2f}%)")

    print("\nBlock bootstrap (price-only, no dividend)...")
    paths = block_bootstrap(log_ret.to_numpy(), N_PATHS, HORIZON_MONTHS, BLOCK, SEED)
    print(f"  paths shape: {paths.shape}")

    # Total-return adjustment: TWII is price-only; add monthly dividend log return
    # (assumed 3.5% annual dividend yield reinvested, conservative for Taiwan blue-chip ETF basket).
    DIV_YIELD_ANNUAL = 0.035
    DIV_MONTHLY_LOG = np.log(1 + DIV_YIELD_ANNUAL) / 12
    paths_tr = paths + DIV_MONTHLY_LOG  # log returns are additive
    print(f"  TR-adjusted: +{DIV_MONTHLY_LOG*12:.4f} log/year (≈ +{DIV_YIELD_ANNUAL*100:.1f}% nominal yield)")

    results = {"sensitivity_price_only": {}, "sensitivity_total_return": {}}
    for label_outer, paths_use, key in (
        ("price-only", paths, "sensitivity_price_only"),
        ("total-return +3.5% div", paths_tr, "sensitivity_total_return"),
    ):
        print(f"\n=== {label_outer} ===")
        for rate in (0.015, 0.022, 0.030):
            print(f"  Mortgage rate {rate*100:.1f}%...")
            sc = run_scenario(rate, paths_use)
            save_sc = {
                k: ({kk: vv for kk, vv in v.items() if not kk.startswith("_")} if isinstance(v, dict) else v)
                for k, v in sc.items()
            }
            results[key][f"{rate*100:.1f}%"] = save_sc
            for s in ("A_payoff", "B_keep", "C_half"):
                r = sc[s]
                print(
                    f"    {s}: bust_rate={r['bust_rate']*100:.1f}%, "
                    f"final p5/p50/p95 = {r['final_p5']/1e4:.0f}/{r['final_p50']/1e4:.0f}/{r['final_p95']/1e4:.0f} 萬"
                )

    # Save baseline (2.2%, total-return) detailed arrays for figures — TR is the realistic case
    baseline = run_scenario(0.022, paths_tr)
    baseline_po = run_scenario(0.022, paths)  # price-only for comparison

    # Figure 1: bust rate comparison (price-only vs total-return, baseline 2.2%)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    rates_labels = ["1.5%", "2.2%", "3.0%"]
    strategies = ["A 一次還清", "B 繼續繳", "C 還一半"]
    keys = ["A_payoff", "B_keep", "C_half"]
    colors = ["#2563eb", "#dc2626", "#16a34a"]
    width = 0.25
    x = np.arange(len(rates_labels))
    for ax_i, (panel_key, panel_title) in zip(axes, [
        ("sensitivity_price_only", "(a) 價格指數，不含息（保守上界）"),
        ("sensitivity_total_return", "(b) 含息 +3.5%/年（現實對照）"),
    ]):
        for i, (k, label, col) in enumerate(zip(keys, strategies, colors)):
            rates_bust = [results[panel_key][r][k]["bust_rate"] * 100 for r in rates_labels]
            ax_i.bar(x + (i - 1) * width, rates_bust, width, label=label, color=col, alpha=0.85)
        ax_i.set_xticks(x)
        ax_i.set_xticklabels([f"房貸利率 {r}" for r in rates_labels])
        ax_i.set_title(panel_title, fontsize=11)
        ax_i.grid(axis="y", alpha=0.3)
        ax_i.set_ylim(0, 65)
    axes[0].set_ylabel("30 年破產率 (%)")
    axes[0].legend(loc="upper left")
    fig.suptitle("退休 30 年破產率 — 三策略 × 房貸利率 × 含息／不含息")
    plt.tight_layout()
    fig.savefig(ROOT / "figures" / "k1400_bust_rate_comparison.png", dpi=130)
    plt.close(fig)

    # Figure 2: final value distribution (baseline 2.2%)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for s, label, col in zip(keys, strategies, colors):
        fv = baseline[s]["_final_values"] / 1e4  # 萬
        # Trim outliers for readability (top 1% can be huge)
        cap = np.percentile(fv, 99)
        fv_clip = fv[fv <= cap]
        ax.hist(fv_clip, bins=80, alpha=0.4, label=label, color=col, density=True)
    ax.axvline(0, color="black", linestyle=":", linewidth=1, label="破產線（終值 = 0）")
    ax.set_xlabel("30 年後資產終值（萬元）")
    ax.set_ylabel("密度")
    ax.set_title("退休 30 年後資產終值分布 — 含息報酬 baseline，房貸 2.2%")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(ROOT / "figures" / "k1400_final_value_distribution.png", dpi=130)
    plt.close(fig)

    # Figure 3: median path envelope (baseline)
    # Need to re-simulate to get path-level wealth trajectories
    rng = np.random.default_rng(SEED + 1)
    sample_idx = rng.choice(N_PATHS, size=500, replace=False)
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    for ax_i, (s, label, col) in zip(axes, zip(keys, strategies, colors)):
        # compute wealth trajectory under this strategy for sample paths
        if s == "A_payoff":
            init_p, pay, mort_m = INITIAL_WEALTH - MORTGAGE_BALANCE, 0, 0
        elif s == "B_keep":
            init_p, pay, mort_m = INITIAL_WEALTH, mortgage_monthly_payment(MORTGAGE_BALANCE, 0.022, MORTGAGE_MONTHS), MORTGAGE_MONTHS
        else:
            half_b = MORTGAGE_BALANCE / 2
            init_p, pay, mort_m = INITIAL_WEALTH - half_b, mortgage_monthly_payment(half_b, 0.022, MORTGAGE_MONTHS), MORTGAGE_MONTHS

        traj = np.full((len(sample_idx), HORIZON_MONTHS + 1), float(init_p))
        for j, p_idx in enumerate(sample_idx):
            w = init_p
            dead = False
            for m in range(HORIZON_MONTHS):
                if not dead:
                    # Use TR-adjusted paths (paths_tr) — consistent with baseline scenario
                    w = w * np.exp(paths_tr[p_idx, m])
                    living = LIVING_COST_MONTHLY * (1 + INFLATION_MONTHLY) ** m
                    if m < mort_m:
                        w -= living + pay
                    else:
                        w -= living
                    if w < 0:
                        w = 0
                        dead = True
                traj[j, m + 1] = w
        years = np.arange(HORIZON_MONTHS + 1) / 12
        p5 = np.percentile(traj, 5, axis=0) / 1e4
        p50 = np.percentile(traj, 50, axis=0) / 1e4
        p95 = np.percentile(traj, 95, axis=0) / 1e4
        ax_i.fill_between(years, p5, p95, alpha=0.2, color=col, label="P5-P95")
        ax_i.plot(years, p50, color=col, linewidth=2, label="中位數")
        ax_i.set_xlabel("退休後年數")
        ax_i.set_title(label)
        ax_i.legend(loc="upper right", fontsize=8)
        ax_i.grid(alpha=0.3)
        ax_i.set_ylim(bottom=0)
    axes[0].set_ylabel("資產（萬元）")
    fig.suptitle("退休 30 年資產路徑 — 中位數 + 90% 區間（含息報酬，房貸 2.2%）")
    plt.tight_layout()
    fig.savefig(ROOT / "figures" / "k1400_path_envelope.png", dpi=130)
    plt.close(fig)

    # Save numeric results
    results["meta"] = {
        "seed": SEED,
        "n_paths": N_PATHS,
        "horizon_months": HORIZON_MONTHS,
        "block_size": BLOCK,
        "data_period": f"{log_ret.index[0].date()}..{log_ret.index[-1].date()}",
        "n_monthly_obs": len(log_ret),
        "monthly_log_return_mean": float(log_ret.mean()),
        "monthly_log_return_std": float(log_ret.std()),
        "arith_simple_annual": float(arith_simple_annual),
        "geom_log_annual": float(geom_log_annual),
        "geom_simple_annual": float(np.exp(geom_log_annual) - 1),
        "initial_wealth": INITIAL_WEALTH,
        "mortgage_balance": MORTGAGE_BALANCE,
        "mortgage_years_remaining": MORTGAGE_YEARS_REMAINING,
        "living_cost_monthly": LIVING_COST_MONTHLY,
        "inflation_annual": INFLATION_ANNUAL,
        "dividend_yield_annual_assumed": DIV_YIELD_ANNUAL,
        "div_monthly_log_added": DIV_MONTHLY_LOG,
        "caveats": [
            "TWII is price-only; dividend yield ~3.5%/year added in TR scenario (assumption, not data)",
            "Inflation 2%/year ≈ conservative for Taiwan CPI 1.0-1.5% historical",
            "Bust = liquid investment portfolio ≤ 0; ignores house equity / liquidation",
            "100% TWII allocation; real retirees typically diversified",
            "Block bootstrap from 1997-2026 monthly returns; assumes future distribution ≈ historical",
            "No transaction costs, taxes, fund fees included",
            "Mortgage interest rate fixed nominal; floating-rate mortgages would worsen B/C in rising-rate regimes",
        ],
    }
    out_path = ROOT / "k1400_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n✓ Saved {out_path}")
    print(f"✓ Figures: {ROOT / 'figures'}/")


if __name__ == "__main__":
    main()
