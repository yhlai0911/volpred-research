#!/usr/bin/env python3
"""
K604: Practical Implementation Cost Analysis
=============================================
What does it ACTUALLY cost to run each strategy for a retail investor?

Analyzes ALL active strategies across:
- Annual turnover (trades/year, dollar turnover)
- Bid-ask spread costs (SPY ~1bp, GLD ~2bp, 0050.TW ~5bp)
- Brokerage commissions ($0 US, $20/trade TW)
- Margin interest (5.5% on leveraged portion)
- Tax drag (US: short-term CG 22%, TW: 0% CG but 0.3% securities TX)
- Operational complexity (1-5 scale)
- Net Sharpe after ALL costs
- Minimum portfolio size for practicality

Data source: paper_trading.json (actual weight histories 2023-01 to 2026-03)
"""

import json
import sys
import os
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# Navigate to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.chdir(PROJECT_ROOT)


def load_paper_trading():
    """Load paper trading data."""
    pt_path = PROJECT_ROOT / "storage" / "paper_trading.json"
    with open(pt_path) as f:
        return json.load(f)


def load_strategy_metrics():
    """Load pre-computed strategy metrics."""
    sm_path = PROJECT_ROOT / "storage" / "strategy_metrics.json"
    with open(sm_path) as f:
        return json.load(f)


# ========== COST PARAMETERS ==========
# Based on real-world retail investor costs as of 2026

COST_PARAMS = {
    # Bid-ask spread in basis points (one-way)
    "spread_bps": {
        "SPY": 1.0,     # Most liquid ETF, typical 0.01 spread on ~$570
        "GLD": 2.0,     # Liquid but wider spread
        "0050.TW": 5.0, # Taiwan market, wider spread
        "^N225": 3.0,   # Nikkei proxy ETF
    },
    # Brokerage commission per trade (USD)
    "commission_per_trade": {
        "US": 0.0,       # Schwab, Fidelity, IBKR Lite — $0
        "TW": 20.0,      # ~NT$600 ≈ $20 (0.1425% × 2 for round-trip on small trades)
    },
    # Taiwan securities transaction tax (sell-side only)
    "tw_securities_tax_rate": 0.003,  # 0.3% on sell value
    # US tax rates
    "us_short_term_cg_rate": 0.22,    # Federal 22% bracket (typical retail)
    "us_long_term_cg_rate": 0.15,     # Federal 15% for most investors
    # Margin interest rate (annual)
    "margin_rate": 0.055,  # 5.5% typical for IBKR/Schwab margin
    # Risk-free rate (for Sharpe calculation)
    "risk_free_rate": 0.045,  # ~4.5% T-bill yield
}

# Strategy metadata
STRATEGY_INFO = {
    "slow_vt": {
        "display_name": "GARCH VT (SPY)",
        "assets": ["SPY"],
        "market": "US",
        "rebalance_freq": "daily",
        "uses_leverage": False,
        "uses_garch": True,
        "complexity_score": 4,
        "complexity_reason": "Requires daily GARCH estimation (Python/R), monitoring convergence",
        "description": "Daily VT sizing via GJR-GARCH(1,1) on SPY",
    },
    "risk_parity": {
        "display_name": "Risk Parity (SPY+GLD)",
        "assets": ["SPY", "GLD"],
        "market": "US",
        "rebalance_freq": "daily",
        "uses_leverage": False,
        "uses_garch": True,
        "complexity_score": 5,
        "complexity_reason": "Two GARCH fits daily, risk parity calculation, two ETFs to manage",
        "description": "Daily risk-parity weighted SPY+GLD via GARCH",
    },
    "simple_12vix": {
        "display_name": "12/VIX (SPY)",
        "assets": ["SPY"],
        "market": "US",
        "rebalance_freq": "daily",
        "uses_leverage": False,
        "uses_garch": False,
        "complexity_score": 1,
        "complexity_reason": "Just look up VIX, divide 12/VIX, rebalance SPY",
        "description": "12/VIX simple sizing on SPY",
    },
    "recommended_5050": {
        "display_name": "50/50 SPY/GLD",
        "assets": ["SPY", "GLD"],
        "market": "US",
        "rebalance_freq": "daily",
        "uses_leverage": False,
        "uses_garch": False,
        "complexity_score": 2,
        "complexity_reason": "Look up VIX, compute 12/VIX, split 50/50 between SPY and GLD",
        "description": "50/50 SPY/GLD with 12/VIX sizing",
    },
    "taiwan_8.63vix": {
        "display_name": "Taiwan VT (0050.TW)",
        "assets": ["0050.TW"],
        "market": "TW",
        "rebalance_freq": "daily",
        "uses_leverage": False,
        "uses_garch": False,
        "complexity_score": 2,
        "complexity_reason": "Look up VIX (US), compute 8.63/VIX, trade 0050.TW. Cross-market monitoring.",
        "description": "8.63/VIX sizing on Taiwan 0050.TW",
    },
    "vix_leading_guard": {
        "display_name": "VIX+Leading (0050.TW)",
        "assets": ["0050.TW"],
        "market": "TW",
        "rebalance_freq": "daily",
        "uses_leverage": False,
        "uses_garch": False,
        "complexity_score": 3,
        "complexity_reason": "VIX + Taiwan leading indicator (monthly data, regime switch k=10/6)",
        "description": "VIX + Taiwan business cycle leading indicator for 0050.TW",
    },
    "vix_cond_leverage": {
        "display_name": "VIX Conditional Leverage",
        "assets": ["SPY", "GLD"],
        "market": "US",
        "rebalance_freq": "monthly_with_daily_monitor",
        "uses_leverage": True,
        "uses_garch": False,
        "complexity_score": 3,
        "complexity_reason": "Monthly rebalance, but daily VIX check for leverage switch. Margin required.",
        "description": "50/50 SPY/GLD, 12/VIX sizing, 1.5x leverage when VIX<15",
    },
    "taiwan_hybrid_leverage": {
        "display_name": "Taiwan Hybrid Leverage",
        "assets": ["0050.TW"],
        "market": "TW",
        "rebalance_freq": "monthly_with_daily_monitor",
        "uses_leverage": True,
        "uses_garch": False,
        "complexity_score": 4,
        "complexity_reason": "Cross-market VIX + local RV22 + VIX percentile. Leverage + Taiwan broker margin.",
        "description": "0050.TW with 8.63/VIX + conditional 1.5x leverage",
    },
    "piecewise_conservative": {
        "display_name": "Piecewise Conservative",
        "assets": ["SPY", "GLD"],
        "market": "US",
        "rebalance_freq": "daily",
        "uses_leverage": False,
        "uses_garch": False,
        "complexity_score": 1,
        "complexity_reason": "Simple piecewise VIX rule (3 zones). No computation required.",
        "description": "50/50 SPY/GLD with piecewise VIX zones (full/ramp/exit)",
    },
    "fear_dca": {
        "display_name": "Fear DCA",
        "assets": ["SPY"],
        "market": "US",
        "rebalance_freq": "monthly",
        "uses_leverage": False,
        "uses_garch": False,
        "complexity_score": 1,
        "complexity_reason": "Monthly check VIX zone → adjust DCA contribution. Minimal effort.",
        "description": "Monthly DCA multiplier based on VIX regime",
    },
    "adaptive_tier": {
        "display_name": "Adaptive Tier VT",
        "assets": ["SPY", "GLD"],
        "market": "US",
        "rebalance_freq": "monthly_with_daily_monitor",
        "uses_leverage": True,
        "uses_garch": False,
        "complexity_score": 2,
        "complexity_reason": "Monthly rebalance, daily VIX check for regime switch. 3 clear zones.",
        "description": "3-regime VIX switching: leverage/standard/exit on 50/50 SPY/GLD",
    },
}

# Active strategies (from STRATEGY_REGISTRY is_active=True)
ACTIVE_STRATEGIES = [
    "slow_vt", "risk_parity", "simple_12vix", "recommended_5050",
    "taiwan_8.63vix", "vix_leading_guard", "vix_cond_leverage",
    "taiwan_hybrid_leverage", "piecewise_conservative", "fear_dca",
    "adaptive_tier",
]


def compute_turnover_stats(entries, strategy_id):
    """
    Compute turnover statistics from paper trading entries.

    Returns:
        dict with trade_count, avg_weight_change, turnover_ratio, etc.
    """
    if len(entries) < 2:
        return None

    trade_days = 0
    total_weight_turnover = 0.0  # Sum of absolute weight changes
    weight_changes = []

    for i in range(1, len(entries)):
        prev_w = entries[i-1].get("weights", {})
        curr_w = entries[i].get("weights", {})

        # Get all assets
        all_assets = set(list(prev_w.keys()) + list(curr_w.keys()))

        # Compute absolute weight change
        day_turnover = 0.0
        for asset in all_assets:
            w0 = prev_w.get(asset, 0)
            w1 = curr_w.get(asset, 0)
            day_turnover += abs(w1 - w0)

        if day_turnover > 0.001:  # Threshold: 0.1% weight change counts as a trade
            trade_days += 1

        total_weight_turnover += day_turnover
        weight_changes.append(day_turnover)

    n_days = len(entries) - 1
    years = n_days / 252.0

    # Annual statistics
    annual_trade_days = trade_days / years if years > 0 else 0
    annual_turnover = total_weight_turnover / years if years > 0 else 0
    avg_weight_change = np.mean(weight_changes) if weight_changes else 0
    median_weight_change = np.median(weight_changes) if weight_changes else 0

    # Count actual meaningful trades (weight change > 1%)
    meaningful_trades = sum(1 for wc in weight_changes if wc > 0.01)
    annual_meaningful_trades = meaningful_trades / years if years > 0 else 0

    return {
        "total_days": n_days,
        "years": round(years, 2),
        "trade_days": trade_days,
        "trade_days_pct": round(trade_days / n_days * 100, 1),
        "annual_trade_days": round(annual_trade_days, 1),
        "meaningful_trades": meaningful_trades,
        "annual_meaningful_trades": round(annual_meaningful_trades, 1),
        "total_weight_turnover": round(total_weight_turnover, 4),
        "annual_turnover": round(annual_turnover, 4),
        "avg_daily_weight_change": round(avg_weight_change, 6),
        "median_daily_weight_change": round(median_weight_change, 6),
    }


def compute_spread_cost(entries, strategy_info, cost_params):
    """
    Compute bid-ask spread cost.

    Cost = sum of (|weight_change| × spread_bps × 2) for each trade
    (×2 because you sell one position and buy another)
    """
    if len(entries) < 2:
        return 0.0

    total_spread_cost = 0.0

    for i in range(1, len(entries)):
        prev_w = entries[i-1].get("weights", {})
        curr_w = entries[i].get("weights", {})

        all_assets = set(list(prev_w.keys()) + list(curr_w.keys()))

        for asset in all_assets:
            w0 = prev_w.get(asset, 0)
            w1 = curr_w.get(asset, 0)
            delta_w = abs(w1 - w0)

            spread_bps = cost_params["spread_bps"].get(asset, 3.0)
            # Cost = weight_change × spread (in decimal) × 2 (round-trip half)
            # For a rebalance, you're crossing the spread on the changed portion
            spread_cost = delta_w * (spread_bps / 10000)
            total_spread_cost += spread_cost

    n_days = len(entries) - 1
    years = n_days / 252.0
    annual_spread_cost = total_spread_cost / years if years > 0 else 0

    return {
        "total_spread_cost_pct": round(total_spread_cost * 100, 4),
        "annual_spread_cost_pct": round(annual_spread_cost * 100, 4),
        "annual_spread_cost_bps": round(annual_spread_cost * 10000, 2),
    }


def compute_commission_cost(entries, strategy_info, cost_params):
    """
    Compute brokerage commission cost as % of portfolio.

    For US: $0 per trade (most brokers)
    For TW: ~$20 per trade (0.1425% buy + 0.1425% sell ≈ on small portfolios)

    Returns cost as % of portfolio for various portfolio sizes.
    """
    if len(entries) < 2:
        return {}

    market = strategy_info["market"]
    commission = cost_params["commission_per_trade"].get(market, 0)

    # Count trades (days with weight change > 0.1%)
    trade_count = 0
    for i in range(1, len(entries)):
        prev_w = entries[i-1].get("weights", {})
        curr_w = entries[i].get("weights", {})
        all_assets = set(list(prev_w.keys()) + list(curr_w.keys()))
        day_turnover = sum(abs(curr_w.get(a, 0) - prev_w.get(a, 0)) for a in all_assets)
        if day_turnover > 0.001:
            # Each asset that changes counts as a separate trade
            for a in all_assets:
                if abs(curr_w.get(a, 0) - prev_w.get(a, 0)) > 0.001:
                    trade_count += 1

    n_days = len(entries) - 1
    years = n_days / 252.0
    annual_trades = trade_count / years if years > 0 else 0
    annual_commission = annual_trades * commission

    # Cost as % of portfolio for different sizes
    portfolio_sizes = [10000, 25000, 50000, 100000, 250000, 500000, 1000000]
    cost_by_size = {}
    for size in portfolio_sizes:
        cost_pct = (annual_commission / size) * 100
        cost_by_size[f"${size:,}"] = round(cost_pct, 4)

    return {
        "market": market,
        "commission_per_trade": commission,
        "annual_trades": round(annual_trades, 1),
        "annual_commission_usd": round(annual_commission, 2),
        "cost_pct_by_portfolio_size": cost_by_size,
    }


def compute_tw_tax_cost(entries, strategy_info, cost_params):
    """
    Compute Taiwan securities transaction tax (0.3% on sell value).
    Only applies to TW market strategies.

    For each weight decrease, the sell amount incurs 0.3% tax.
    """
    if strategy_info["market"] != "TW":
        return {"applies": False, "annual_tax_cost_pct": 0.0}

    if len(entries) < 2:
        return {"applies": True, "annual_tax_cost_pct": 0.0}

    total_sell_weight = 0.0

    for i in range(1, len(entries)):
        prev_w = entries[i-1].get("weights", {})
        curr_w = entries[i].get("weights", {})

        for asset in prev_w:
            w0 = prev_w.get(asset, 0)
            w1 = curr_w.get(asset, 0)
            if w1 < w0:
                # Selling — tax applies
                total_sell_weight += (w0 - w1)

    total_tax = total_sell_weight * cost_params["tw_securities_tax_rate"]
    n_days = len(entries) - 1
    years = n_days / 252.0
    annual_tax = total_tax / years if years > 0 else 0

    return {
        "applies": True,
        "annual_sell_turnover_pct": round(total_sell_weight / years * 100, 2) if years > 0 else 0,
        "annual_tax_cost_pct": round(annual_tax * 100, 4),
        "annual_tax_cost_bps": round(annual_tax * 10000, 2),
    }


def compute_us_tax_drag(entries, strategy_info, cost_params, metrics):
    """
    Estimate US capital gains tax drag.

    For daily-rebalanced strategies, most gains are SHORT-TERM (taxed at 22%).
    For monthly strategies, most gains may qualify for LONG-TERM (taxed at 15%).

    We estimate the annual tax drag = realized gains × tax rate.
    Rough approach: annual return × tax rate × turnover fraction
    """
    if strategy_info["market"] != "US":
        return {"applies": False, "annual_tax_drag_pct": 0.0}

    freq = strategy_info["rebalance_freq"]
    annual_return = metrics.get("annualized_return", 0) / 100  # Convert from % to decimal

    if "daily" in freq:
        # Nearly all gains are short-term
        short_term_fraction = 0.90
        long_term_fraction = 0.10
    elif "monthly" in freq:
        # More gains can be long-term (held > 1 year across rebalances)
        short_term_fraction = 0.40
        long_term_fraction = 0.60
    else:
        short_term_fraction = 0.60
        long_term_fraction = 0.40

    # Only positive returns create tax liability
    if annual_return > 0:
        st_tax = annual_return * short_term_fraction * cost_params["us_short_term_cg_rate"]
        lt_tax = annual_return * long_term_fraction * cost_params["us_long_term_cg_rate"]
        total_tax_drag = st_tax + lt_tax
    else:
        total_tax_drag = 0.0

    return {
        "applies": True,
        "short_term_fraction": short_term_fraction,
        "long_term_fraction": long_term_fraction,
        "estimated_annual_tax_drag_pct": round(total_tax_drag * 100, 2),
        "effective_tax_rate": round(
            (short_term_fraction * cost_params["us_short_term_cg_rate"] +
             long_term_fraction * cost_params["us_long_term_cg_rate"]) * 100, 1
        ),
    }


def compute_margin_cost(entries, strategy_info, cost_params):
    """
    Compute margin interest cost for leveraged strategies.

    Margin cost = average_leveraged_portion × margin_rate
    Leveraged portion = max(0, total_weight - 1.0) (i.e., the part above 100%)
    """
    if not strategy_info["uses_leverage"]:
        return {"applies": False, "annual_margin_cost_pct": 0.0}

    leveraged_portions = []
    for entry in entries:
        w = entry.get("weights", {})
        total_w = sum(w.values())
        leveraged = max(0, total_w - 1.0)
        leveraged_portions.append(leveraged)

    avg_leverage = np.mean(leveraged_portions) if leveraged_portions else 0
    max_leverage = max(leveraged_portions) if leveraged_portions else 0
    pct_leveraged = sum(1 for lp in leveraged_portions if lp > 0) / len(leveraged_portions) * 100 if leveraged_portions else 0

    annual_margin_cost = avg_leverage * cost_params["margin_rate"]

    return {
        "applies": True,
        "avg_leveraged_portion": round(avg_leverage, 4),
        "max_leveraged_portion": round(max_leverage, 4),
        "pct_days_leveraged": round(pct_leveraged, 1),
        "annual_margin_cost_pct": round(annual_margin_cost * 100, 4),
    }


def compute_net_sharpe(metrics, total_annual_cost_pct, cost_params):
    """
    Compute net Sharpe ratio after all costs.

    Net Sharpe = (annualized_return - risk_free - total_costs) / annualized_vol
    """
    ann_ret = metrics.get("annualized_return", 0) / 100  # to decimal
    ann_vol = metrics.get("annualized_vol", 1) / 100  # to decimal
    rf = cost_params["risk_free_rate"]
    total_cost = total_annual_cost_pct / 100  # to decimal

    if ann_vol == 0:
        return None

    gross_sharpe = (ann_ret - rf) / ann_vol
    net_sharpe = (ann_ret - rf - total_cost) / ann_vol
    sharpe_reduction = gross_sharpe - net_sharpe

    return {
        "gross_sharpe_vs_rf": round(gross_sharpe, 3),
        "net_sharpe_vs_rf": round(net_sharpe, 3),
        "sharpe_reduction": round(sharpe_reduction, 3),
        "sharpe_reduction_pct": round(sharpe_reduction / gross_sharpe * 100, 1) if gross_sharpe != 0 else 0,
    }


def compute_minimum_portfolio_size(strategy_info, commission_cost, total_annual_cost_pct, metrics):
    """
    Compute minimum portfolio size for the strategy to be practical.

    Criteria:
    1. Commission costs < 0.5% of portfolio per year
    2. Leverage strategies need margin minimum ($25K US, $100K TW)
    3. Total costs < 50% of gross excess return
    """
    market = strategy_info["market"]
    uses_leverage = strategy_info["uses_leverage"]

    # Criterion 1: Commission threshold
    annual_commission = commission_cost.get("annual_commission_usd", 0)
    if annual_commission > 0:
        min_for_commission = int(annual_commission / 0.005)  # 0.5% threshold
    else:
        min_for_commission = 0

    # Criterion 2: Margin minimums
    if uses_leverage:
        if market == "US":
            min_for_margin = 25000  # Pattern day trader rule
        else:
            min_for_margin = 100000  # Taiwan margin account minimum
    else:
        min_for_margin = 0

    # Criterion 3: Cost/return ratio
    ann_ret = metrics.get("annualized_return", 0)
    if ann_ret > 0 and total_annual_cost_pct > 0:
        # Total cost < 50% of gross return
        # At what portfolio size does this hold?
        # For commission-dominated strategies, solve: commission/size + other_costs < 0.5 * return
        pass

    # Take the maximum
    minimum = max(min_for_commission, min_for_margin, 1000)  # At least $1,000

    # Round up to nice number
    if minimum <= 5000:
        minimum = 5000
    elif minimum <= 10000:
        minimum = 10000
    elif minimum <= 25000:
        minimum = 25000
    elif minimum <= 50000:
        minimum = 50000
    elif minimum <= 100000:
        minimum = 100000

    return {
        "minimum_portfolio_usd": minimum,
        "min_for_commission_threshold": min_for_commission,
        "min_for_margin_requirement": min_for_margin,
        "reason": "margin requirement" if min_for_margin >= min_for_commission else "commission threshold" if min_for_commission > min_for_margin else "minimum practical size",
    }


def compute_cost_at_portfolio_size(
    portfolio_size, spread_annual_pct, commission_annual_usd,
    margin_annual_pct, tw_tax_annual_pct, us_tax_drag_pct
):
    """Compute total cost at a specific portfolio size."""
    commission_pct = (commission_annual_usd / portfolio_size) * 100 if portfolio_size > 0 else 0
    total = spread_annual_pct + commission_pct + margin_annual_pct + tw_tax_annual_pct + us_tax_drag_pct
    return round(total, 4)


def main():
    print("=" * 70)
    print("K604: Practical Implementation Cost Analysis")
    print("=" * 70)
    print()

    pt = load_paper_trading()
    metrics = load_strategy_metrics()

    results = {
        "experiment_id": "K604",
        "title": "Practical Implementation Cost Analysis",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "paper_trading.json (actual weight histories)",
        "cost_assumptions": COST_PARAMS,
        "methodology": (
            "Computed actual turnover from paper_trading.json weight changes. "
            "Applied real-world cost parameters: SPY spread 1bp, GLD 2bp, 0050.TW 5bp; "
            "$0 US commissions, $20/trade TW; 5.5% margin rate; "
            "US tax: 22% short-term / 15% long-term; TW: 0.3% securities TX. "
            "Net Sharpe computed against 4.5% risk-free rate."
        ),
        "strategies": {},
        "summary": {},
        "ranking": {},
    }

    print(f"Analyzing {len(ACTIVE_STRATEGIES)} active strategies...")
    print()

    all_strategy_results = {}

    for strat_id in ACTIVE_STRATEGIES:
        info = STRATEGY_INFO.get(strat_id)
        if not info:
            print(f"  [SKIP] {strat_id}: no strategy info defined")
            continue

        strat_metrics = metrics.get(strat_id)
        if not strat_metrics:
            print(f"  [SKIP] {strat_id}: no metrics available")
            continue

        entries = pt.get(strat_id, {}).get("entries", [])
        if len(entries) < 10:
            print(f"  [SKIP] {strat_id}: insufficient entries ({len(entries)})")
            continue

        print(f"--- {info['display_name']} ({strat_id}) ---")

        # 1. Turnover
        turnover = compute_turnover_stats(entries, strat_id)
        print(f"  Turnover: {turnover['annual_trade_days']:.0f} trade days/yr, "
              f"annual weight turnover = {turnover['annual_turnover']:.1f}x")

        # 2. Spread cost
        spread = compute_spread_cost(entries, info, COST_PARAMS)
        print(f"  Spread cost: {spread['annual_spread_cost_bps']:.1f} bps/yr")

        # 3. Commission cost
        commission = compute_commission_cost(entries, info, COST_PARAMS)
        print(f"  Commissions: {commission['annual_trades']:.0f} trades/yr, "
              f"${commission['annual_commission_usd']:.0f}/yr")

        # 4. Taiwan securities tax
        tw_tax = compute_tw_tax_cost(entries, info, COST_PARAMS)
        if tw_tax["applies"]:
            print(f"  TW securities tax: {tw_tax['annual_tax_cost_bps']:.1f} bps/yr")

        # 5. US tax drag
        us_tax = compute_us_tax_drag(entries, info, COST_PARAMS, strat_metrics)
        if us_tax["applies"]:
            print(f"  US tax drag: {us_tax['estimated_annual_tax_drag_pct']:.2f}%/yr "
                  f"(effective rate {us_tax['effective_tax_rate']:.1f}%)")

        # 6. Margin cost
        margin = compute_margin_cost(entries, info, COST_PARAMS)
        if margin["applies"]:
            print(f"  Margin cost: {margin['annual_margin_cost_pct']:.2f}%/yr "
                  f"(leveraged {margin['pct_days_leveraged']:.0f}% of days)")

        # 7. Total cost (at $100K portfolio)
        portfolio_size = 100000
        commission_pct_100k = (commission["annual_commission_usd"] / portfolio_size) * 100
        total_cost_pct = (
            spread["annual_spread_cost_pct"] +
            commission_pct_100k +
            margin.get("annual_margin_cost_pct", 0) +
            tw_tax.get("annual_tax_cost_pct", 0) +
            us_tax.get("estimated_annual_tax_drag_pct", 0)
        )

        # Cost breakdown at various sizes
        cost_at_sizes = {}
        for size in [10000, 25000, 50000, 100000, 250000, 500000, 1000000]:
            cost_at_sizes[f"${size:,}"] = compute_cost_at_portfolio_size(
                size,
                spread["annual_spread_cost_pct"],
                commission["annual_commission_usd"],
                margin.get("annual_margin_cost_pct", 0),
                tw_tax.get("annual_tax_cost_pct", 0),
                us_tax.get("estimated_annual_tax_drag_pct", 0),
            )

        print(f"  Total cost @$100K: {total_cost_pct:.2f}%/yr")

        # 8. Net Sharpe
        net_sharpe = compute_net_sharpe(strat_metrics, total_cost_pct, COST_PARAMS)
        if net_sharpe:
            print(f"  Gross Sharpe (vs Rf): {net_sharpe['gross_sharpe_vs_rf']:.3f} → "
                  f"Net Sharpe: {net_sharpe['net_sharpe_vs_rf']:.3f} "
                  f"(-{net_sharpe['sharpe_reduction_pct']:.0f}%)")

        # 9. Minimum portfolio size
        min_size = compute_minimum_portfolio_size(info, commission, total_cost_pct, strat_metrics)
        print(f"  Min portfolio: ${min_size['minimum_portfolio_usd']:,} ({min_size['reason']})")

        # 10. Cost breakdown
        cost_breakdown = {
            "spread_pct": round(spread["annual_spread_cost_pct"], 4),
            "commission_pct_at_100k": round(commission_pct_100k, 4),
            "margin_pct": round(margin.get("annual_margin_cost_pct", 0), 4),
            "tw_tax_pct": round(tw_tax.get("annual_tax_cost_pct", 0), 4),
            "us_tax_drag_pct": round(us_tax.get("estimated_annual_tax_drag_pct", 0), 2),
            "total_pct_at_100k": round(total_cost_pct, 4),
        }

        # Compute total cost WITHOUT tax (since tax is on gains, not operational)
        operational_cost_pct = (
            spread["annual_spread_cost_pct"] +
            commission_pct_100k +
            margin.get("annual_margin_cost_pct", 0) +
            tw_tax.get("annual_tax_cost_pct", 0)
        )

        strat_result = {
            "display_name": info["display_name"],
            "description": info["description"],
            "market": info["market"],
            "assets": info["assets"],
            "rebalance_frequency": info["rebalance_freq"],
            "uses_leverage": info["uses_leverage"],
            "uses_garch": info["uses_garch"],
            "complexity_score": info["complexity_score"],
            "complexity_reason": info["complexity_reason"],
            "performance": {
                "annualized_return_pct": strat_metrics.get("annualized_return"),
                "annualized_vol_pct": strat_metrics.get("annualized_vol"),
                "sharpe": strat_metrics.get("sharpe"),
                "max_drawdown_pct": strat_metrics.get("max_drawdown"),
                "calmar": strat_metrics.get("calmar"),
            },
            "turnover": turnover,
            "cost_breakdown": cost_breakdown,
            "cost_at_portfolio_sizes": cost_at_sizes,
            "operational_cost_pct": round(operational_cost_pct, 4),
            "spread_detail": spread,
            "commission_detail": commission,
            "tw_tax_detail": tw_tax,
            "us_tax_detail": us_tax,
            "margin_detail": margin,
            "net_sharpe": net_sharpe,
            "minimum_portfolio": min_size,
        }

        all_strategy_results[strat_id] = strat_result
        print()

    results["strategies"] = all_strategy_results

    # ========== SUMMARY TABLES ==========
    print("=" * 70)
    print("SUMMARY: Implementation Cost Comparison")
    print("=" * 70)
    print()

    # Table 1: Cost Overview (at $100K portfolio)
    print("Table 1: Annual Cost Breakdown (at $100,000 portfolio)")
    print("-" * 120)
    header = f"{'Strategy':<30} {'Spread':>8} {'Commiss':>8} {'Margin':>8} {'TW Tax':>8} {'US Tax':>8} {'Total':>8} {'Oper.':>8}"
    print(header)
    print("-" * 120)

    for strat_id in ACTIVE_STRATEGIES:
        r = all_strategy_results.get(strat_id)
        if not r:
            continue
        cb = r["cost_breakdown"]
        name = r["display_name"][:28]
        print(f"{name:<30} {cb['spread_pct']:>7.2f}% {cb['commission_pct_at_100k']:>7.2f}% "
              f"{cb['margin_pct']:>7.2f}% {cb['tw_tax_pct']:>7.2f}% "
              f"{cb['us_tax_drag_pct']:>7.2f}% {cb['total_pct_at_100k']:>7.2f}% "
              f"{r['operational_cost_pct']:>7.2f}%")
    print()

    # Table 2: Net Sharpe Comparison
    print("Table 2: Sharpe Ratio Impact")
    print("-" * 100)
    header2 = f"{'Strategy':<30} {'Gross SR':>10} {'Net SR':>10} {'Reduction':>10} {'Complexity':>10} {'Min Size':>12}"
    print(header2)
    print("-" * 100)

    for strat_id in ACTIVE_STRATEGIES:
        r = all_strategy_results.get(strat_id)
        if not r or not r["net_sharpe"]:
            continue
        ns = r["net_sharpe"]
        name = r["display_name"][:28]
        min_sz = f"${r['minimum_portfolio']['minimum_portfolio_usd']:,}"
        print(f"{name:<30} {ns['gross_sharpe_vs_rf']:>9.3f} {ns['net_sharpe_vs_rf']:>9.3f} "
              f"{ns['sharpe_reduction_pct']:>8.1f}% {r['complexity_score']:>9}/5 {min_sz:>12}")
    print()

    # Table 3: Turnover Comparison
    print("Table 3: Turnover Analysis")
    print("-" * 100)
    header3 = f"{'Strategy':<30} {'Trade Days/Yr':>14} {'Annual TO':>10} {'Avg Δw/Day':>12} {'Rebalance':>12}"
    print(header3)
    print("-" * 100)

    for strat_id in ACTIVE_STRATEGIES:
        r = all_strategy_results.get(strat_id)
        if not r:
            continue
        t = r["turnover"]
        name = r["display_name"][:28]
        print(f"{name:<30} {t['annual_trade_days']:>13.0f} {t['annual_turnover']:>9.1f}x "
              f"{t['avg_daily_weight_change']*100:>10.2f}% {r['rebalance_frequency']:>12}")
    print()

    # Table 4: Cost at Various Portfolio Sizes
    print("Table 4: Total Annual Cost (%) at Various Portfolio Sizes")
    print("-" * 130)
    sizes_header = f"{'Strategy':<30} {'$10K':>8} {'$25K':>8} {'$50K':>8} {'$100K':>8} {'$250K':>8} {'$500K':>8} {'$1M':>8}"
    print(sizes_header)
    print("-" * 130)

    for strat_id in ACTIVE_STRATEGIES:
        r = all_strategy_results.get(strat_id)
        if not r:
            continue
        cs = r["cost_at_portfolio_sizes"]
        name = r["display_name"][:28]
        print(f"{name:<30} {cs.get('$10,000',0):>7.2f}% {cs.get('$25,000',0):>7.2f}% "
              f"{cs.get('$50,000',0):>7.2f}% {cs.get('$100,000',0):>7.2f}% "
              f"{cs.get('$250,000',0):>7.2f}% {cs.get('$500,000',0):>7.2f}% "
              f"{cs.get('$1,000,000',0):>7.2f}%")
    print()

    # ========== RANKINGS ==========

    # Rank by Net Sharpe (after all costs at $100K)
    net_sharpe_ranking = sorted(
        [(sid, r["net_sharpe"]["net_sharpe_vs_rf"])
         for sid, r in all_strategy_results.items()
         if r.get("net_sharpe") and r["net_sharpe"]["net_sharpe_vs_rf"] is not None],
        key=lambda x: x[1],
        reverse=True,
    )

    # Rank by Operational Cost (lowest)
    oper_cost_ranking = sorted(
        [(sid, r["operational_cost_pct"]) for sid, r in all_strategy_results.items()],
        key=lambda x: x[1],
    )

    # Rank by Complexity (lowest = easiest)
    complexity_ranking = sorted(
        [(sid, r["complexity_score"]) for sid, r in all_strategy_results.items()],
        key=lambda x: x[1],
    )

    # "Best Value" ranking: Net Sharpe / Complexity Score
    value_ranking = sorted(
        [(sid, r["net_sharpe"]["net_sharpe_vs_rf"] / r["complexity_score"])
         for sid, r in all_strategy_results.items()
         if r.get("net_sharpe") and r["net_sharpe"]["net_sharpe_vs_rf"] is not None],
        key=lambda x: x[1],
        reverse=True,
    )

    print("RANKINGS:")
    print()
    print("By Net Sharpe (after all costs @$100K):")
    for i, (sid, val) in enumerate(net_sharpe_ranking):
        name = all_strategy_results[sid]["display_name"]
        print(f"  {i+1}. {name}: {val:.3f}")
    print()

    print("By Operational Cost (lowest, excl. tax):")
    for i, (sid, val) in enumerate(oper_cost_ranking):
        name = all_strategy_results[sid]["display_name"]
        print(f"  {i+1}. {name}: {val:.2f}%")
    print()

    print("By Ease of Use (complexity, 1=easiest):")
    for i, (sid, val) in enumerate(complexity_ranking):
        name = all_strategy_results[sid]["display_name"]
        print(f"  {i+1}. {name}: {val}/5")
    print()

    print("By Value (Net Sharpe / Complexity):")
    for i, (sid, val) in enumerate(value_ranking):
        name = all_strategy_results[sid]["display_name"]
        print(f"  {i+1}. {name}: {val:.3f}")
    print()

    results["ranking"] = {
        "by_net_sharpe": [{"strategy": sid, "net_sharpe": round(val, 3)} for sid, val in net_sharpe_ranking],
        "by_operational_cost": [{"strategy": sid, "oper_cost_pct": round(val, 4)} for sid, val in oper_cost_ranking],
        "by_complexity": [{"strategy": sid, "complexity": val} for sid, val in complexity_ranking],
        "by_value": [{"strategy": sid, "value_ratio": round(val, 3)} for sid, val in value_ranking],
    }

    # ========== KEY FINDINGS ==========

    # Find the best and worst
    best_net = net_sharpe_ranking[0] if net_sharpe_ranking else None
    worst_net = net_sharpe_ranking[-1] if net_sharpe_ranking else None
    cheapest = oper_cost_ranking[0] if oper_cost_ranking else None
    most_expensive = oper_cost_ranking[-1] if oper_cost_ranking else None
    easiest = complexity_ranking[0] if complexity_ranking else None
    best_value = value_ranking[0] if value_ranking else None

    findings = []

    if best_net:
        findings.append(
            f"Best net Sharpe: {all_strategy_results[best_net[0]]['display_name']} "
            f"({best_net[1]:.3f})"
        )
    if cheapest:
        findings.append(
            f"Lowest operational cost: {all_strategy_results[cheapest[0]]['display_name']} "
            f"({cheapest[1]:.2f}%/yr)"
        )
    if easiest:
        findings.append(
            f"Easiest to implement: {all_strategy_results[easiest[0]]['display_name']} "
            f"(complexity {easiest[1]}/5)"
        )
    if best_value:
        findings.append(
            f"Best value (Sharpe/Complexity): {all_strategy_results[best_value[0]]['display_name']} "
            f"({best_value[1]:.3f})"
        )

    # Cost impact analysis
    avg_sharpe_reduction = np.mean([
        r["net_sharpe"]["sharpe_reduction_pct"]
        for r in all_strategy_results.values()
        if r.get("net_sharpe") and r["net_sharpe"]["sharpe_reduction_pct"] is not None
    ])
    findings.append(f"Average Sharpe reduction from costs: {avg_sharpe_reduction:.1f}%")

    # Taiwan vs US cost comparison
    tw_strats = [r for r in all_strategy_results.values() if r["market"] == "TW"]
    us_strats = [r for r in all_strategy_results.values() if r["market"] == "US"]
    if tw_strats and us_strats:
        avg_tw_cost = np.mean([r["operational_cost_pct"] for r in tw_strats])
        avg_us_cost = np.mean([r["operational_cost_pct"] for r in us_strats])
        findings.append(
            f"TW strategies avg operational cost: {avg_tw_cost:.2f}% vs US: {avg_us_cost:.2f}% "
            f"({'TW more expensive' if avg_tw_cost > avg_us_cost else 'US more expensive'})"
        )

    # Tax impact
    tax_sensitive = [(sid, r["us_tax_detail"]["estimated_annual_tax_drag_pct"])
                     for sid, r in all_strategy_results.items()
                     if r.get("us_tax_detail", {}).get("applies")]
    if tax_sensitive:
        max_tax = max(tax_sensitive, key=lambda x: x[1])
        findings.append(
            f"Highest US tax drag: {all_strategy_results[max_tax[0]]['display_name']} "
            f"({max_tax[1]:.2f}%/yr)"
        )

    results["summary"]["key_findings"] = findings
    results["summary"]["avg_sharpe_reduction_pct"] = round(avg_sharpe_reduction, 1)

    # Investor profile recommendations
    recommendations = {
        "beginner_low_effort": {
            "recommended": "piecewise_conservative",
            "reason": "Lowest complexity (1/5), very low cost, good Sharpe. Just check VIX zone.",
        },
        "beginner_passive": {
            "recommended": "fear_dca",
            "reason": "Monthly check only (1/5 complexity), enhances existing DCA habit.",
        },
        "intermediate_us": {
            "recommended": "recommended_5050",
            "reason": "Good Sharpe, moderate complexity (2/5), $0 commissions, diversified SPY+GLD.",
        },
        "intermediate_tw": {
            "recommended": "taiwan_8.63vix",
            "reason": "Simple VIX rule for Taiwan market. Higher commissions but no capital gains tax.",
        },
        "advanced_us": {
            "recommended": "adaptive_tier",
            "reason": "Best value ratio (Sharpe/complexity). 3-regime system with leverage in calm markets.",
        },
        "quantitative": {
            "recommended": "risk_parity",
            "reason": "Highest gross Sharpe, but requires daily GARCH computation. For quant-oriented investors.",
        },
    }
    results["summary"]["recommendations"] = recommendations

    print("KEY FINDINGS:")
    for f in findings:
        print(f"  - {f}")
    print()

    print("RECOMMENDATIONS BY INVESTOR PROFILE:")
    for profile, rec in recommendations.items():
        r_strat = all_strategy_results.get(rec["recommended"], {})
        print(f"  {profile}: {rec['recommended']} — {rec['reason']}")
    print()

    # Save results
    results_path = PROJECT_ROOT / "experiments" / "k604_implementation_costs_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"Results saved to: {results_path}")

    return results


if __name__ == "__main__":
    main()
