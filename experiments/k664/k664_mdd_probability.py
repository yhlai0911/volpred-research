"""
K664: Maximum Drawdown Probability Analysis
============================================
Motivation: Investors care about "what's the worst that can happen?"
K648 analyzed drawdown recovery speed. This experiment quantifies the
PROBABILITY of experiencing various drawdown levels over any 1-year period.

Method:
- Rolling 252-day windows across 20 years of data (2006-2026)
- For each window, compute the maximum drawdown
- Count frequency of MDD exceeding 5%, 10%, 20%, 30%
- Bootstrap 5000 reps for confidence intervals on each probability
- Translate to expected dollar losses for a $100K portfolio

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27
Strategies: 12/VIX SPY, 50/50 SPY/GLD 12/VIX, Piecewise Conservative,
            Buy-and-Hold SPY, Buy-and-Hold 60/40

References:
- Martin (1987) "An Exact Measure of Risk" - Ulcer Index / drawdown analysis
- Grossman & Zhou (1993) - Optimal portfolio insurance
- Magdon-Ismail & Atiya (2004) "Maximum Drawdown" - distributional properties
"""

import json
import numpy as np
import yfinance as yf
from pathlib import Path
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────
START_DATE = "2006-01-01"
END_DATE = "2026-03-27"
WINDOW = 252  # 1 trading year
BOOTSTRAP_REPS = 5000
BOOTSTRAP_BLOCK_SIZE = 21  # block bootstrap with ~1 month blocks
DRAWDOWN_THRESHOLDS = [0.05, 0.10, 0.20, 0.30]
INVESTMENT_AMOUNT = 100_000

np.random.seed(42)


def download_data():
    """Download SPY, GLD, VIX daily data from yfinance."""
    print("Downloading data from yfinance...")
    tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
    data = {}
    for name, ticker in tickers.items():
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"No data for {ticker}")
        # Handle MultiIndex columns from yfinance
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        data[name] = df
        print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")
    return data


def align_data(data):
    """Align all series to common dates."""
    # Find common dates
    common = data["SPY"].index.intersection(data["GLD"].index).intersection(data["VIX"].index)
    common = common.sort_values()
    print(f"Common trading days: {len(common)}")

    spy_close = data["SPY"].loc[common, "Close"].values.flatten()
    gld_close = data["GLD"].loc[common, "Close"].values.flatten()
    vix_close = data["VIX"].loc[common, "Close"].values.flatten()
    dates = [d.strftime("%Y-%m-%d") for d in common]

    # Compute daily returns
    spy_ret = np.diff(spy_close) / spy_close[:-1]
    gld_ret = np.diff(gld_close) / gld_close[:-1]
    vix_levels = vix_close[1:]  # align with returns (VIX at close of day)
    dates = dates[1:]  # drop first date (no return)

    return dates, spy_ret, gld_ret, vix_levels


def compute_strategy_returns(spy_ret, gld_ret, vix_levels):
    """Compute daily returns for each strategy."""
    n = len(spy_ret)
    strategies = {}

    # 1. 12/VIX SPY: weight = min(12/VIX_prev, 1.0) on SPY, rest in cash
    # Use previous day's VIX for signal (no lookahead)
    w_12vix = np.zeros(n)
    ret_12vix = np.zeros(n)
    for i in range(n):
        if i == 0:
            w = min(12.0 / vix_levels[0], 1.0)
        else:
            w = min(12.0 / vix_levels[i - 1], 1.0)
        w_12vix[i] = w
        ret_12vix[i] = w * spy_ret[i]
    strategies["12/VIX SPY"] = ret_12vix

    # 2. 50/50 SPY/GLD + 12/VIX: same VIX weight, split 50/50
    ret_5050 = np.zeros(n)
    for i in range(n):
        if i == 0:
            w = min(12.0 / vix_levels[0], 1.0)
        else:
            w = min(12.0 / vix_levels[i - 1], 1.0)
        ret_5050[i] = w * (0.5 * spy_ret[i] + 0.5 * gld_ret[i])
    strategies["50/50 SPY/GLD (12/VIX)"] = ret_5050

    # 3. Piecewise Conservative: 50/50 SPY/GLD with piecewise VIX mapping
    #    VIX < 12 → w = 1.0; 12 <= VIX <= 20 → w = (20-VIX)/8; VIX > 20 → w = 0.0
    ret_pw = np.zeros(n)
    for i in range(n):
        vix_prev = vix_levels[i - 1] if i > 0 else vix_levels[0]
        if vix_prev < 12:
            w = 1.0
        elif vix_prev <= 20:
            w = (20 - vix_prev) / 8.0
        else:
            w = 0.0
        ret_pw[i] = w * (0.5 * spy_ret[i] + 0.5 * gld_ret[i])
    strategies["Piecewise Conservative"] = ret_pw

    # 4. Buy-and-Hold SPY
    strategies["BH SPY"] = spy_ret.copy()

    # 5. Buy-and-Hold 60/40 SPY/GLD (daily rebalanced)
    strategies["BH 60/40"] = 0.6 * spy_ret + 0.4 * gld_ret

    return strategies


def compute_max_drawdown(returns):
    """Compute maximum drawdown from a return series."""
    wealth = np.cumprod(1 + returns)
    hwm = np.maximum.accumulate(wealth)
    dd = (wealth - hwm) / hwm
    return float(np.min(dd))  # most negative


def rolling_mdd_analysis(returns, window=WINDOW):
    """
    Compute MDD for every rolling window.
    Returns array of MDD values (one per window).
    """
    n = len(returns)
    if n < window:
        return np.array([])

    n_windows = n - window + 1
    mdds = np.empty(n_windows)

    for i in range(n_windows):
        window_ret = returns[i:i + window]
        mdds[i] = compute_max_drawdown(window_ret)

    return mdds  # all negative or zero


def compute_exceedance_probabilities(mdds, thresholds=DRAWDOWN_THRESHOLDS):
    """
    Compute P(MDD > threshold) for each threshold.
    Note: MDD values are negative, thresholds are positive.
    """
    probs = {}
    n = len(mdds)
    for t in thresholds:
        count = np.sum(mdds < -t)  # MDD more severe than threshold
        probs[f"P(MDD>{t*100:.0f}%)"] = float(count / n)
    return probs


def bootstrap_confidence_intervals(mdds, thresholds=DRAWDOWN_THRESHOLDS,
                                    n_reps=BOOTSTRAP_REPS,
                                    block_size=BOOTSTRAP_BLOCK_SIZE):
    """
    Block bootstrap confidence intervals for exceedance probabilities.
    Uses circular block bootstrap to preserve temporal dependence.
    """
    n = len(mdds)
    n_blocks = int(np.ceil(n / block_size))

    boot_probs = {f"P(MDD>{t*100:.0f}%)": [] for t in thresholds}

    for _ in range(n_reps):
        # Circular block bootstrap
        indices = []
        for _ in range(n_blocks):
            start = np.random.randint(0, n)
            block_indices = [(start + j) % n for j in range(block_size)]
            indices.extend(block_indices)
        indices = indices[:n]
        boot_mdds = mdds[indices]

        for t in thresholds:
            key = f"P(MDD>{t*100:.0f}%)"
            count = np.sum(boot_mdds < -t)
            boot_probs[key].append(float(count / n))

    ci = {}
    for key, values in boot_probs.items():
        values = np.array(values)
        ci[key] = {
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "ci_2.5": float(np.percentile(values, 2.5)),
            "ci_97.5": float(np.percentile(values, 97.5)),
        }

    return ci


def expected_loss_table(probs, investment=INVESTMENT_AMOUNT):
    """
    Translate probabilities to dollar terms.
    "If you invest $X, what's the probability of losing more than $Y in any year?"
    """
    loss_levels = [5_000, 10_000, 20_000, 30_000]
    loss_pcts = [l / investment for l in loss_levels]
    table = {}
    for loss_amt, loss_pct in zip(loss_levels, loss_pcts):
        key = f"P(lose>${loss_amt:,})"
        # Find closest threshold
        threshold_key = f"P(MDD>{loss_pct*100:.0f}%)"
        if threshold_key in probs:
            table[key] = probs[threshold_key]
        else:
            table[key] = None
    return table


def print_results(all_results, comparison):
    """Print formatted results."""
    print("\n" + "=" * 100)
    print("K664: MAXIMUM DRAWDOWN PROBABILITY ANALYSIS")
    print(f"Data: SPY, GLD, VIX | Period: {START_DATE} to {END_DATE} | Window: {WINDOW} trading days")
    print("=" * 100)

    # Main probability table
    print("\n── Probability of Experiencing MDD > X% in Any 1-Year Period ──")
    header = f"{'Strategy':<30}"
    for t in DRAWDOWN_THRESHOLDS:
        header += f" {'P(MDD>'+str(int(t*100))+'%)':>14}"
    header += f" {'N windows':>10}"
    print(header)
    print("-" * len(header))

    for name, res in all_results.items():
        row = f"{name:<30}"
        for t in DRAWDOWN_THRESHOLDS:
            key = f"P(MDD>{t*100:.0f}%)"
            p = res["probabilities"][key]
            row += f" {p*100:>13.1f}%"
        row += f" {res['n_windows']:>10}"
        print(row)

    # Bootstrap confidence intervals
    print("\n── 95% Bootstrap Confidence Intervals (5000 reps) ──")
    for name, res in all_results.items():
        print(f"\n  {name}:")
        for t in DRAWDOWN_THRESHOLDS:
            key = f"P(MDD>{t*100:.0f}%)"
            ci = res["bootstrap_ci"][key]
            print(f"    {key}: {ci['mean']*100:.1f}% [{ci['ci_2.5']*100:.1f}%, {ci['ci_97.5']*100:.1f}%]")

    # Expected loss table
    print("\n── Expected Loss Table: If You Invest $100,000 ──")
    print(f"  What's the probability of losing more than $X in any 12-month period?\n")
    header = f"{'Strategy':<30} {'> $5K':>12} {'> $10K':>12} {'> $20K':>12} {'> $30K':>12}"
    print(header)
    print("-" * len(header))
    for name, res in all_results.items():
        row = f"{name:<30}"
        for loss_key in ["P(lose>$5,000)", "P(lose>$10,000)", "P(lose>$20,000)", "P(lose>$30,000)"]:
            p = res["expected_losses"].get(loss_key)
            if p is not None:
                row += f" {p*100:>11.1f}%"
            else:
                row += f" {'N/A':>12}"
        print(row)

    # Comparison
    print("\n── Strategy Comparison: Lowest P(MDD > 10%) ──")
    for item in comparison:
        print(f"  {item['rank']}. {item['strategy']:<30} P(MDD>10%) = {item['prob_10']*100:.1f}% "
              f"[{item['ci_low']*100:.1f}%, {item['ci_high']*100:.1f}%]")

    # MDD distribution summary
    print("\n── MDD Distribution Summary (Rolling 252-day windows) ──")
    header = f"{'Strategy':<30} {'Mean MDD':>10} {'Median':>10} {'Worst':>10} {'Best':>10} {'Std':>10}"
    print(header)
    print("-" * len(header))
    for name, res in all_results.items():
        s = res["mdd_stats"]
        print(f"{name:<30} {s['mean']*100:>9.2f}% {s['median']*100:>9.2f}% "
              f"{s['worst']*100:>9.2f}% {s['best']*100:>9.2f}% {s['std']*100:>9.2f}%")


def main():
    # Download and align data
    data = download_data()
    dates, spy_ret, gld_ret, vix_levels = align_data(data)
    print(f"Return series length: {len(spy_ret)} days")
    print(f"Date range: {dates[0]} to {dates[-1]}")
    print(f"VIX range: {vix_levels.min():.1f} to {vix_levels.max():.1f}")

    # Descriptive statistics
    print(f"\n── Data Diagnostics ──")
    print(f"SPY daily return: mean={spy_ret.mean()*100:.4f}%, std={spy_ret.std()*100:.4f}%, "
          f"skew={float(np.mean(((spy_ret - spy_ret.mean())/spy_ret.std())**3)):.2f}, "
          f"kurt={float(np.mean(((spy_ret - spy_ret.mean())/spy_ret.std())**4)):.2f}")
    print(f"GLD daily return: mean={gld_ret.mean()*100:.4f}%, std={gld_ret.std()*100:.4f}%, "
          f"skew={float(np.mean(((gld_ret - gld_ret.mean())/gld_ret.std())**3)):.2f}, "
          f"kurt={float(np.mean(((gld_ret - gld_ret.mean())/gld_ret.std())**4)):.2f}")
    print(f"SPY-GLD correlation: {np.corrcoef(spy_ret, gld_ret)[0,1]:.4f}")

    # Compute strategy returns
    strategies = compute_strategy_returns(spy_ret, gld_ret, vix_levels)

    # Analyze each strategy
    all_results = {}
    for name, returns in strategies.items():
        print(f"\nAnalyzing: {name} ({len(returns)} days)")

        # Rolling MDD
        mdds = rolling_mdd_analysis(returns, WINDOW)
        print(f"  Rolling windows: {len(mdds)}")

        # Exceedance probabilities
        probs = compute_exceedance_probabilities(mdds)
        for key, p in probs.items():
            print(f"  {key} = {p*100:.1f}%")

        # Bootstrap CI
        print(f"  Running bootstrap ({BOOTSTRAP_REPS} reps)...")
        ci = bootstrap_confidence_intervals(mdds)

        # Expected losses
        losses = expected_loss_table(probs)

        # MDD distribution stats
        mdd_stats = {
            "mean": float(np.mean(mdds)),
            "median": float(np.median(mdds)),
            "worst": float(np.min(mdds)),
            "best": float(np.max(mdds)),
            "std": float(np.std(mdds)),
            "p5": float(np.percentile(mdds, 5)),
            "p25": float(np.percentile(mdds, 25)),
            "p75": float(np.percentile(mdds, 75)),
            "p95": float(np.percentile(mdds, 95)),
        }

        # Strategy return stats
        total_ret = float(np.prod(1 + returns) - 1)
        n_days = len(returns)
        ann_ret = float((1 + total_ret) ** (252 / n_days) - 1)
        ann_vol = float(np.std(returns) * np.sqrt(252))
        full_mdd = compute_max_drawdown(returns)

        all_results[name] = {
            "n_days": n_days,
            "n_windows": len(mdds),
            "probabilities": probs,
            "bootstrap_ci": ci,
            "expected_losses": losses,
            "mdd_stats": mdd_stats,
            "performance": {
                "total_return_pct": round(total_ret * 100, 2),
                "annualized_return_pct": round(ann_ret * 100, 2),
                "annualized_volatility_pct": round(ann_vol * 100, 2),
                "full_period_mdd_pct": round(full_mdd * 100, 2),
            },
        }

    # Comparison: rank by P(MDD > 10%)
    comparison = []
    for name, res in all_results.items():
        p10 = res["probabilities"]["P(MDD>10%)"]
        ci10 = res["bootstrap_ci"]["P(MDD>10%)"]
        comparison.append({
            "strategy": name,
            "prob_10": p10,
            "ci_low": ci10["ci_2.5"],
            "ci_high": ci10["ci_97.5"],
        })
    comparison.sort(key=lambda x: x["prob_10"])
    for i, item in enumerate(comparison):
        item["rank"] = i + 1

    # Print results
    print_results(all_results, comparison)

    # Key findings
    best_10 = comparison[0]
    worst_10 = comparison[-1]

    # Find BH SPY stats for context
    bh_spy = all_results.get("BH SPY", {})
    bh_spy_p10 = bh_spy.get("probabilities", {}).get("P(MDD>10%)", None)

    # Reduction factor: how much does best strategy reduce P(MDD>10%) vs BH SPY
    if bh_spy_p10 and bh_spy_p10 > 0:
        reduction = (1 - best_10["prob_10"] / bh_spy_p10) * 100
    else:
        reduction = None

    key_findings = [
        f"Lowest P(MDD>10%): {best_10['strategy']} at {best_10['prob_10']*100:.1f}% "
        f"[95% CI: {best_10['ci_low']*100:.1f}%-{best_10['ci_high']*100:.1f}%]",
        f"Highest P(MDD>10%): {worst_10['strategy']} at {worst_10['prob_10']*100:.1f}% "
        f"[95% CI: {worst_10['ci_low']*100:.1f}%-{worst_10['ci_high']*100:.1f}%]",
    ]
    if reduction is not None:
        key_findings.append(
            f"{best_10['strategy']} reduces P(MDD>10%) by {reduction:.0f}% relative to BH SPY"
        )

    # Add P(MDD>20%) comparison (tail risk)
    for name, res in all_results.items():
        p20 = res["probabilities"]["P(MDD>20%)"]
        if p20 == 0:
            key_findings.append(f"{name}: ZERO probability of >20% drawdown in any year (over {res['n_windows']} windows)")

    print("\n── KEY FINDINGS ──")
    for f in key_findings:
        print(f"  * {f}")

    # Save results
    output = {
        "experiment_id": "K664",
        "title": "Maximum Drawdown Probability Analysis",
        "description": (
            "Quantifies the probability of experiencing various drawdown levels "
            "(5%, 10%, 20%, 30%) over any 1-year period using rolling 252-day windows. "
            "Bootstrap confidence intervals (5000 reps) provide uncertainty estimates. "
            "Expected dollar loss table translates probabilities for a $100K portfolio."
        ),
        "data_source": f"yfinance (SPY, GLD, ^VIX), {START_DATE} to {END_DATE}",
        "sample_size": len(spy_ret),
        "methodology": {
            "rolling_window": WINDOW,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "bootstrap_block_size": BOOTSTRAP_BLOCK_SIZE,
            "drawdown_thresholds": [f"{t*100:.0f}%" for t in DRAWDOWN_THRESHOLDS],
            "signal_timing": "Previous day VIX used for weight calculation (no lookahead bias)",
            "strategies": {
                "12/VIX SPY": "weight = min(12/VIX, 1.0) on SPY, rest in cash",
                "50/50 SPY/GLD (12/VIX)": "weight = min(12/VIX, 1.0) split 50/50 on SPY+GLD",
                "Piecewise Conservative": "VIX<12: w=1.0; 12<=VIX<=20: w=(20-VIX)/8; VIX>20: w=0.0; split 50/50 SPY+GLD",
                "BH SPY": "100% SPY buy-and-hold",
                "BH 60/40": "60% SPY + 40% GLD, daily rebalanced",
            },
            "references": [
                "Martin, P. (1987). 'An Exact Measure of Risk: The Ulcer Index'",
                "Grossman, S.J. & Zhou, Z. (1993). 'Optimal Investment Strategies for Controlling Drawdowns'",
                "Magdon-Ismail, M. & Atiya, A.F. (2004). 'Maximum Drawdown'. Risk Magazine.",
            ],
        },
        "strategy_results": {},
        "comparison_mdd_10pct": comparison,
        "expected_loss_table_100k": {},
        "key_findings": key_findings,
        "limitations": [
            "Rolling windows overlap heavily, so events like 2008 GFC dominate many windows",
            "VIX is used as a proxy for conditional volatility; actual GARCH-based VT may differ slightly",
            "GLD data starts 2004-11, so 2006 start ensures full coverage but misses dot-com bust",
            "Block bootstrap with fixed block size may not fully capture long drawdown persistence",
            "60/40 is daily rebalanced (theoretical); real implementation has transaction costs",
        ],
    }

    # Populate strategy_results and expected_loss_table
    for name, res in all_results.items():
        output["strategy_results"][name] = {
            "n_windows": res["n_windows"],
            "performance": res["performance"],
            "exceedance_probabilities": res["probabilities"],
            "bootstrap_ci_95pct": res["bootstrap_ci"],
            "mdd_distribution": res["mdd_stats"],
        }
        output["expected_loss_table_100k"][name] = res["expected_losses"]

    out_path = Path(__file__).resolve().parent / "k664_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
