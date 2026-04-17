#!/usr/bin/env python3
"""
K676: Tax-Aware VT Strategy Optimization
=========================================
K604 showed taxes eat ~27% of Sharpe on average. Short-term capital gains
(22%) are the biggest cost. Can we reduce tax drag by modifying rebalancing
to hold positions >1 year (qualify for long-term capital gains at 15%)?

Strategies tested (all use 50/50 SPY/GLD + 12/VIX base signal):
  a. Tax-oblivious: daily rebalance, all gains taxed at 22% (short-term)
  b. Tax-aware hold: only SELL if held >1yr (15% rate). Force sell if VIX>35.
  c. Tax-loss harvesting: sell losing positions for tax deduction, re-buy next day.
  d. Annual rebalance: only rebalance Jan 1st (maximize long-term holding).
  e. Threshold+tax: rebalance only if |weight_change|>10% AND held>252 days.

Tax calculation:
  - FIFO lot tracking (simplified: one lot per buy event)
  - Short-term gain (held ≤252 days): taxed at 22%
  - Long-term gain (held >252 days): taxed at 15%
  - Losses offset gains (carried forward if excess)

Data source: yfinance (SPY, GLD, ^VIX), 2010-01-01 to 2026-03-27
Reference: K604 implementation costs analysis
"""

import json
import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque
from copy import deepcopy

# Navigate to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.chdir(PROJECT_ROOT)

# ========== TAX PARAMETERS ==========
TAX_PARAMS = {
    "short_term_rate": 0.22,     # Federal 22% bracket
    "long_term_rate": 0.15,      # Federal 15% for most investors
    "long_term_days": 252,       # ~1 year in trading days
    "risk_free_rate": 0.045,     # T-bill yield for Sharpe
}

# ========== DATA LOADING ==========

def load_data():
    """Load SPY, GLD, VIX daily data via yfinance."""
    import yfinance as yf

    start = "2010-01-01"
    end = "2026-03-27"

    print(f"Downloading SPY, GLD, ^VIX from {start} to {end}...")

    spy = yf.download("SPY", start=start, end=end, progress=False)["Close"]
    gld = yf.download("GLD", start=start, end=end, progress=False)["Close"]
    vix = yf.download("^VIX", start=start, end=end, progress=False)["Close"]

    # Flatten MultiIndex columns if present
    if hasattr(spy, 'columns'):
        spy = spy.iloc[:, 0] if len(spy.shape) > 1 else spy
    if hasattr(gld, 'columns'):
        gld = gld.iloc[:, 0] if len(gld.shape) > 1 else gld
    if hasattr(vix, 'columns'):
        vix = vix.iloc[:, 0] if len(vix.shape) > 1 else vix

    # Align dates
    df = pd.DataFrame({"SPY": spy, "GLD": gld, "VIX": vix}).dropna()
    df.index = pd.to_datetime(df.index)

    print(f"  Loaded {len(df)} trading days: {df.index[0].date()} to {df.index[-1].date()}")
    return df


# ========== 12/VIX SIGNAL ==========

def compute_12vix_weights(vix_series):
    """
    12/VIX signal: equity_weight = min(12/VIX, 1.0)
    Split equally between SPY and GLD.
    """
    equity_pct = np.minimum(12.0 / vix_series.values, 1.0)
    spy_w = equity_pct * 0.5
    gld_w = equity_pct * 0.5
    cash_w = 1.0 - equity_pct
    return pd.DataFrame({
        "SPY_w": spy_w,
        "GLD_w": gld_w,
        "cash_w": cash_w,
    }, index=vix_series.index)


# ========== LOT TRACKING (FIFO) ==========

class TaxLot:
    """A single purchase lot for FIFO tracking."""
    __slots__ = ['buy_date_idx', 'shares', 'cost_basis']

    def __init__(self, buy_date_idx, shares, cost_basis):
        self.buy_date_idx = buy_date_idx   # trading day index (int)
        self.shares = shares
        self.cost_basis = cost_basis        # per-share cost


class PortfolioTracker:
    """
    Track lots for two assets (SPY, GLD) using FIFO.
    Computes realized gains/losses with short/long-term distinction.
    """

    def __init__(self, initial_capital=100_000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.lots = {"SPY": deque(), "GLD": deque()}
        self.realized_gains_st = 0.0  # short-term
        self.realized_gains_lt = 0.0  # long-term
        self.realized_losses_st = 0.0
        self.realized_losses_lt = 0.0
        self.loss_carryforward = 0.0
        self.annual_taxes_paid = 0.0
        self.total_taxes_paid = 0.0
        self.yearly_tax_history = {}

    def get_position_value(self, asset, price):
        """Total value of all lots for an asset at current price."""
        return sum(lot.shares * price for lot in self.lots[asset])

    def get_shares(self, asset):
        """Total shares held for an asset."""
        return sum(lot.shares for lot in self.lots[asset])

    def get_portfolio_value(self, prices):
        """Total portfolio value (cash + positions)."""
        val = self.cash
        for asset in ["SPY", "GLD"]:
            val += self.get_position_value(asset, prices[asset])
        return val

    def buy(self, asset, shares, price, day_idx):
        """Buy shares, creating a new lot."""
        cost = shares * price
        if cost > self.cash + 0.01:  # allow tiny float error
            # Buy only what we can afford
            shares = self.cash / price
            cost = shares * price
        if shares < 0.0001:
            return
        self.cash -= cost
        self.lots[asset].append(TaxLot(day_idx, shares, price))

    def sell(self, asset, shares_to_sell, price, day_idx):
        """
        Sell shares using FIFO. Returns (realized_gain, is_long_term_list).
        """
        if shares_to_sell < 0.0001:
            return

        remaining = shares_to_sell
        while remaining > 0.0001 and self.lots[asset]:
            lot = self.lots[asset][0]
            sell_qty = min(remaining, lot.shares)
            gain = sell_qty * (price - lot.cost_basis)
            holding_days = day_idx - lot.buy_date_idx

            if holding_days > TAX_PARAMS["long_term_days"]:
                if gain > 0:
                    self.realized_gains_lt += gain
                else:
                    self.realized_losses_lt += abs(gain)
            else:
                if gain > 0:
                    self.realized_gains_st += gain
                else:
                    self.realized_losses_st += abs(gain)

            lot.shares -= sell_qty
            remaining -= sell_qty
            self.cash += sell_qty * price

            if lot.shares < 0.0001:
                self.lots[asset].popleft()

    def sell_all(self, asset, price, day_idx):
        """Sell entire position in an asset."""
        total_shares = self.get_shares(asset)
        if total_shares > 0:
            self.sell(asset, total_shares, price, day_idx)

    def settle_annual_taxes(self, year):
        """
        Settle taxes at year-end. Apply losses against gains, carry forward excess.
        """
        # Gross tax on gains
        tax_st = self.realized_gains_st * TAX_PARAMS["short_term_rate"]
        tax_lt = self.realized_gains_lt * TAX_PARAMS["long_term_rate"]
        gross_tax = tax_st + tax_lt

        # Total losses (use the higher rate for deduction benefit)
        total_losses = self.realized_losses_st + self.realized_losses_lt
        total_losses += self.loss_carryforward

        # Losses offset gains
        loss_benefit = min(total_losses, self.realized_gains_st + self.realized_gains_lt)
        # Apply loss benefit at blended rate
        if (self.realized_gains_st + self.realized_gains_lt) > 0:
            blended_rate = gross_tax / (self.realized_gains_st + self.realized_gains_lt)
        else:
            blended_rate = TAX_PARAMS["short_term_rate"]
        loss_deduction = loss_benefit * blended_rate

        net_tax = max(0, gross_tax - loss_deduction)

        # Carry forward excess losses
        excess_loss = total_losses - loss_benefit
        # IRS allows up to $3,000/year deduction against ordinary income
        ordinary_deduction = min(excess_loss, 3000)
        self.loss_carryforward = max(0, excess_loss - ordinary_deduction)

        # Pay taxes from cash
        self.cash -= net_tax
        self.annual_taxes_paid = net_tax
        self.total_taxes_paid += net_tax

        self.yearly_tax_history[year] = {
            "gains_st": round(self.realized_gains_st, 2),
            "gains_lt": round(self.realized_gains_lt, 2),
            "losses_st": round(self.realized_losses_st, 2),
            "losses_lt": round(self.realized_losses_lt, 2),
            "gross_tax": round(gross_tax, 2),
            "loss_deduction": round(loss_deduction, 2),
            "net_tax": round(net_tax, 2),
            "loss_carryforward": round(self.loss_carryforward, 2),
        }

        # Reset annual counters
        self.realized_gains_st = 0.0
        self.realized_gains_lt = 0.0
        self.realized_losses_st = 0.0
        self.realized_losses_lt = 0.0

        return net_tax


# ========== STRATEGY SIMULATIONS ==========

def run_strategy_a_tax_oblivious(df, weights):
    """
    Strategy A: Tax-Oblivious Daily Rebalance
    Rebalance to target weights every day. All gains are short-term (22%).
    """
    tracker = PortfolioTracker()
    n = len(df)
    portfolio_values = np.zeros(n)
    current_year = df.index[0].year

    for i in range(n):
        prices = {"SPY": df["SPY"].iloc[i], "GLD": df["GLD"].iloc[i]}
        date = df.index[i]

        # Year-end tax settlement
        if date.year != current_year:
            tracker.settle_annual_taxes(current_year)
            current_year = date.year

        port_val = tracker.get_portfolio_value(prices)

        # Target allocation
        target_spy = port_val * weights["SPY_w"].iloc[i]
        target_gld = port_val * weights["GLD_w"].iloc[i]

        # Current values
        curr_spy = tracker.get_position_value("SPY", prices["SPY"])
        curr_gld = tracker.get_position_value("GLD", prices["GLD"])

        # Rebalance SPY
        diff_spy = target_spy - curr_spy
        if diff_spy < -0.01:  # sell
            shares_sell = abs(diff_spy) / prices["SPY"]
            tracker.sell("SPY", shares_sell, prices["SPY"], i)
        elif diff_spy > 0.01:  # buy
            shares_buy = diff_spy / prices["SPY"]
            tracker.buy("SPY", shares_buy, prices["SPY"], i)

        # Rebalance GLD
        diff_gld = target_gld - curr_gld
        if diff_gld < -0.01:
            shares_sell = abs(diff_gld) / prices["GLD"]
            tracker.sell("GLD", shares_sell, prices["GLD"], i)
        elif diff_gld > 0.01:
            shares_buy = diff_gld / prices["GLD"]
            tracker.buy("GLD", shares_buy, prices["GLD"], i)

        portfolio_values[i] = tracker.get_portfolio_value(prices)

    # Final year tax
    tracker.settle_annual_taxes(current_year)
    portfolio_values[-1] = tracker.get_portfolio_value(
        {"SPY": df["SPY"].iloc[-1], "GLD": df["GLD"].iloc[-1]}
    )

    return portfolio_values, tracker


def run_strategy_b_tax_aware_hold(df, weights):
    """
    Strategy B: Tax-Aware Hold
    Only SELL if position held >1 year (15% rate). New buys daily.
    Force sell if VIX > 35 (emergency exit).
    """
    tracker = PortfolioTracker()
    n = len(df)
    portfolio_values = np.zeros(n)
    current_year = df.index[0].year

    for i in range(n):
        prices = {"SPY": df["SPY"].iloc[i], "GLD": df["GLD"].iloc[i]}
        date = df.index[i]
        vix = df["VIX"].iloc[i]

        if date.year != current_year:
            tracker.settle_annual_taxes(current_year)
            current_year = date.year

        port_val = tracker.get_portfolio_value(prices)

        target_spy = port_val * weights["SPY_w"].iloc[i]
        target_gld = port_val * weights["GLD_w"].iloc[i]

        curr_spy = tracker.get_position_value("SPY", prices["SPY"])
        curr_gld = tracker.get_position_value("GLD", prices["GLD"])

        for asset, target, curr, price in [
            ("SPY", target_spy, curr_spy, prices["SPY"]),
            ("GLD", target_gld, curr_gld, prices["GLD"]),
        ]:
            diff = target - curr
            if diff < -0.01:  # need to sell
                # Check if we should sell
                emergency = vix > 35
                # Check if oldest lot is long-term
                oldest_lt = False
                if tracker.lots[asset]:
                    oldest_lot = tracker.lots[asset][0]
                    if (i - oldest_lot.buy_date_idx) > TAX_PARAMS["long_term_days"]:
                        oldest_lt = True

                if emergency or oldest_lt:
                    shares_sell = abs(diff) / price
                    tracker.sell(asset, shares_sell, price, i)
                # else: hold — don't sell short-term positions
            elif diff > 0.01:  # buy
                shares_buy = diff / price
                tracker.buy(asset, shares_buy, price, i)

        portfolio_values[i] = tracker.get_portfolio_value(prices)

    tracker.settle_annual_taxes(current_year)
    portfolio_values[-1] = tracker.get_portfolio_value(
        {"SPY": df["SPY"].iloc[-1], "GLD": df["GLD"].iloc[-1]}
    )
    return portfolio_values, tracker


def run_strategy_c_tax_loss_harvest(df, weights):
    """
    Strategy C: Tax-Loss Harvesting
    Daily rebalance like A, but additionally:
    - When any lot is at a loss AND held > 30 days (wash-sale rule),
      sell it and re-buy next day to realize the loss for tax benefit.
    """
    tracker = PortfolioTracker()
    n = len(df)
    portfolio_values = np.zeros(n)
    current_year = df.index[0].year
    # Track "harvest cooldown" per asset to respect 30-day wash-sale
    harvest_cooldown = {"SPY": 0, "GLD": 0}

    for i in range(n):
        prices = {"SPY": df["SPY"].iloc[i], "GLD": df["GLD"].iloc[i]}
        date = df.index[i]

        if date.year != current_year:
            tracker.settle_annual_taxes(current_year)
            current_year = date.year

        port_val = tracker.get_portfolio_value(prices)

        # === Tax-loss harvesting pass ===
        for asset in ["SPY", "GLD"]:
            if harvest_cooldown[asset] > 0:
                harvest_cooldown[asset] -= 1
                continue

            price = prices[asset]
            lots_to_harvest = []
            for lot in tracker.lots[asset]:
                holding_days = i - lot.buy_date_idx
                if holding_days > 30 and lot.cost_basis > price:
                    # This lot is at a loss and past wash-sale window
                    lots_to_harvest.append(lot.shares)

            if lots_to_harvest:
                # Sell all losing lots
                total_harvest = sum(lots_to_harvest)
                tracker.sell(asset, total_harvest, price, i)
                # Re-buy immediately (simplified: same day)
                tracker.buy(asset, total_harvest, price, i)
                harvest_cooldown[asset] = 31  # 30 day wash-sale buffer

        # === Normal rebalancing (same as A) ===
        port_val = tracker.get_portfolio_value(prices)  # re-evaluate after harvest
        target_spy = port_val * weights["SPY_w"].iloc[i]
        target_gld = port_val * weights["GLD_w"].iloc[i]

        curr_spy = tracker.get_position_value("SPY", prices["SPY"])
        curr_gld = tracker.get_position_value("GLD", prices["GLD"])

        diff_spy = target_spy - curr_spy
        if diff_spy < -0.01:
            tracker.sell("SPY", abs(diff_spy) / prices["SPY"], prices["SPY"], i)
        elif diff_spy > 0.01:
            tracker.buy("SPY", diff_spy / prices["SPY"], prices["SPY"], i)

        diff_gld = target_gld - curr_gld
        if diff_gld < -0.01:
            tracker.sell("GLD", abs(diff_gld) / prices["GLD"], prices["GLD"], i)
        elif diff_gld > 0.01:
            tracker.buy("GLD", diff_gld / prices["GLD"], prices["GLD"], i)

        portfolio_values[i] = tracker.get_portfolio_value(prices)

    tracker.settle_annual_taxes(current_year)
    portfolio_values[-1] = tracker.get_portfolio_value(
        {"SPY": df["SPY"].iloc[-1], "GLD": df["GLD"].iloc[-1]}
    )
    return portfolio_values, tracker


def run_strategy_d_annual_rebalance(df, weights):
    """
    Strategy D: Annual Rebalance
    Only rebalance on the first trading day of each year.
    Maximizes chance for long-term capital gains treatment.
    """
    tracker = PortfolioTracker()
    n = len(df)
    portfolio_values = np.zeros(n)
    current_year = df.index[0].year
    last_rebalance_year = None

    for i in range(n):
        prices = {"SPY": df["SPY"].iloc[i], "GLD": df["GLD"].iloc[i]}
        date = df.index[i]

        if date.year != current_year:
            tracker.settle_annual_taxes(current_year)
            current_year = date.year

        # Only rebalance on first trading day of year
        is_first_day = (last_rebalance_year is None) or (date.year != last_rebalance_year)
        if i > 0:
            prev_date = df.index[i - 1]
            is_first_day = (date.year != prev_date.year)

        if i == 0 or is_first_day:
            port_val = tracker.get_portfolio_value(prices)
            target_spy = port_val * weights["SPY_w"].iloc[i]
            target_gld = port_val * weights["GLD_w"].iloc[i]

            curr_spy = tracker.get_position_value("SPY", prices["SPY"])
            curr_gld = tracker.get_position_value("GLD", prices["GLD"])

            diff_spy = target_spy - curr_spy
            if diff_spy < -0.01:
                tracker.sell("SPY", abs(diff_spy) / prices["SPY"], prices["SPY"], i)
            elif diff_spy > 0.01:
                tracker.buy("SPY", diff_spy / prices["SPY"], prices["SPY"], i)

            diff_gld = target_gld - curr_gld
            if diff_gld < -0.01:
                tracker.sell("GLD", abs(diff_gld) / prices["GLD"], prices["GLD"], i)
            elif diff_gld > 0.01:
                tracker.buy("GLD", diff_gld / prices["GLD"], prices["GLD"], i)

            last_rebalance_year = date.year

        portfolio_values[i] = tracker.get_portfolio_value(prices)

    tracker.settle_annual_taxes(current_year)
    portfolio_values[-1] = tracker.get_portfolio_value(
        {"SPY": df["SPY"].iloc[-1], "GLD": df["GLD"].iloc[-1]}
    )
    return portfolio_values, tracker


def run_strategy_e_threshold_tax(df, weights):
    """
    Strategy E: Threshold + Tax-Aware
    Only rebalance if:
      1. |weight_change| > 10% (threshold) AND
      2. Position held > 252 days (long-term rate)
    Exception: VIX > 35 forces immediate rebalance.
    """
    tracker = PortfolioTracker()
    n = len(df)
    portfolio_values = np.zeros(n)
    current_year = df.index[0].year
    THRESHOLD = 0.10  # 10% weight deviation

    for i in range(n):
        prices = {"SPY": df["SPY"].iloc[i], "GLD": df["GLD"].iloc[i]}
        date = df.index[i]
        vix = df["VIX"].iloc[i]

        if date.year != current_year:
            tracker.settle_annual_taxes(current_year)
            current_year = date.year

        port_val = tracker.get_portfolio_value(prices)
        if port_val < 1:
            portfolio_values[i] = port_val
            continue

        curr_spy = tracker.get_position_value("SPY", prices["SPY"])
        curr_gld = tracker.get_position_value("GLD", prices["GLD"])

        curr_spy_w = curr_spy / port_val
        curr_gld_w = curr_gld / port_val

        target_spy_w = weights["SPY_w"].iloc[i]
        target_gld_w = weights["GLD_w"].iloc[i]

        spy_dev = abs(target_spy_w - curr_spy_w)
        gld_dev = abs(target_gld_w - curr_gld_w)
        max_dev = max(spy_dev, gld_dev)

        emergency = vix > 35
        threshold_exceeded = max_dev > THRESHOLD

        should_rebalance = False
        if i == 0:
            should_rebalance = True
        elif emergency:
            should_rebalance = True
        elif threshold_exceeded:
            # Check if oldest lot is long-term
            all_lt = True
            for asset in ["SPY", "GLD"]:
                if tracker.lots[asset]:
                    oldest = tracker.lots[asset][0]
                    if (i - oldest.buy_date_idx) <= TAX_PARAMS["long_term_days"]:
                        all_lt = False
            if all_lt:
                should_rebalance = True
            # Also allow buying (no tax impact)
            elif (target_spy_w > curr_spy_w + THRESHOLD) or (target_gld_w > curr_gld_w + THRESHOLD):
                # Only buy, don't sell
                for asset, target_w, curr_w, price in [
                    ("SPY", target_spy_w, curr_spy_w, prices["SPY"]),
                    ("GLD", target_gld_w, curr_gld_w, prices["GLD"]),
                ]:
                    if target_w > curr_w:
                        buy_val = (target_w - curr_w) * port_val
                        if buy_val > 0.01:
                            tracker.buy(asset, buy_val / price, price, i)
                portfolio_values[i] = tracker.get_portfolio_value(prices)
                continue

        if should_rebalance:
            target_spy_val = port_val * target_spy_w
            target_gld_val = port_val * target_gld_w

            for asset, target_val, curr_val, price in [
                ("SPY", target_spy_val, curr_spy, prices["SPY"]),
                ("GLD", target_gld_val, curr_gld, prices["GLD"]),
            ]:
                diff = target_val - curr_val
                if diff < -0.01:
                    tracker.sell(asset, abs(diff) / price, price, i)
                elif diff > 0.01:
                    tracker.buy(asset, diff / price, price, i)

        portfolio_values[i] = tracker.get_portfolio_value(prices)

    tracker.settle_annual_taxes(current_year)
    portfolio_values[-1] = tracker.get_portfolio_value(
        {"SPY": df["SPY"].iloc[-1], "GLD": df["GLD"].iloc[-1]}
    )
    return portfolio_values, tracker


# ========== PERFORMANCE METRICS ==========

def compute_metrics(portfolio_values, df_index, tracker):
    """Compute CAGR, Sharpe, max drawdown, terminal wealth after taxes."""
    pv = pd.Series(portfolio_values, index=df_index)
    pv = pv[pv > 0]  # remove any zero entries

    # Daily returns
    daily_ret = pv.pct_change().dropna()

    # CAGR
    years = (pv.index[-1] - pv.index[0]).days / 365.25
    terminal = pv.iloc[-1]
    initial = pv.iloc[0]
    cagr = (terminal / initial) ** (1 / years) - 1

    # Sharpe (excess return / vol, annualized)
    ann_ret = daily_ret.mean() * 252
    ann_vol = daily_ret.std() * np.sqrt(252)
    rf = TAX_PARAMS["risk_free_rate"]
    sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cummax = pv.cummax()
    drawdown = (pv - cummax) / cummax
    max_dd = drawdown.min()

    # Calmar
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    return {
        "cagr_pct": round(cagr * 100, 2),
        "ann_return_pct": round(ann_ret * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar": round(calmar, 3),
        "terminal_wealth": round(terminal, 2),
        "total_taxes_paid": round(tracker.total_taxes_paid, 2),
        "tax_drag_pct": round(tracker.total_taxes_paid / initial * 100, 2),
        "years": round(years, 1),
    }


# ========== MAIN ==========

def main():
    print("=" * 70)
    print("K676: Tax-Aware VT Strategy Optimization")
    print("=" * 70)

    # Load data
    df = load_data()
    weights = compute_12vix_weights(df["VIX"])

    # Run all strategies
    strategies = {
        "A_tax_oblivious": {
            "name": "Tax-Oblivious (Daily Rebalance)",
            "description": "Rebalance to target daily. All gains taxed at 22% (short-term).",
            "func": run_strategy_a_tax_oblivious,
        },
        "B_tax_aware_hold": {
            "name": "Tax-Aware Hold",
            "description": "Only sell if held >1yr (15% rate). Force sell if VIX>35.",
            "func": run_strategy_b_tax_aware_hold,
        },
        "C_tax_loss_harvest": {
            "name": "Tax-Loss Harvesting",
            "description": "Daily rebalance + harvest losses for tax deduction (30-day wash-sale rule).",
            "func": run_strategy_c_tax_loss_harvest,
        },
        "D_annual_rebalance": {
            "name": "Annual Rebalance",
            "description": "Rebalance only on Jan 1st. Maximizes long-term holding period.",
            "func": run_strategy_d_annual_rebalance,
        },
        "E_threshold_tax": {
            "name": "Threshold + Tax-Aware",
            "description": "Rebalance only if |weight_change|>10% AND held>252 days. VIX>35 override.",
            "func": run_strategy_e_threshold_tax,
        },
    }

    results = {}
    all_pv = {}

    for key, strat in strategies.items():
        print(f"\n--- {strat['name']} ---")
        pv, tracker = strat["func"](df, weights)
        metrics = compute_metrics(pv, df.index, tracker)
        results[key] = {
            "name": strat["name"],
            "description": strat["description"],
            "metrics": metrics,
            "yearly_taxes": tracker.yearly_tax_history,
        }
        all_pv[key] = pv
        print(f"  CAGR: {metrics['cagr_pct']:.2f}%  |  Sharpe: {metrics['sharpe']:.3f}  |  "
              f"MaxDD: {metrics['max_drawdown_pct']:.2f}%  |  Terminal: ${metrics['terminal_wealth']:,.0f}")
        print(f"  Total taxes: ${metrics['total_taxes_paid']:,.0f}  |  Tax drag: {metrics['tax_drag_pct']:.1f}% of initial")

    # ========== COMPARISON TABLE ==========
    print("\n" + "=" * 70)
    print("COMPARISON TABLE (sorted by after-tax Sharpe)")
    print("=" * 70)
    print(f"{'Strategy':<35} {'CAGR%':>7} {'Sharpe':>7} {'MaxDD%':>7} {'Terminal':>12} {'Taxes':>10} {'TaxDrag%':>9}")
    print("-" * 88)

    sorted_strats = sorted(results.items(), key=lambda x: x[1]["metrics"]["sharpe"], reverse=True)
    for key, strat in sorted_strats:
        m = strat["metrics"]
        print(f"{strat['name']:<35} {m['cagr_pct']:>7.2f} {m['sharpe']:>7.3f} "
              f"{m['max_drawdown_pct']:>7.2f} {m['terminal_wealth']:>12,.0f} "
              f"${m['total_taxes_paid']:>9,.0f} {m['tax_drag_pct']:>8.1f}")

    # ========== TAX SAVINGS vs BASELINE ==========
    baseline_taxes = results["A_tax_oblivious"]["metrics"]["total_taxes_paid"]
    baseline_terminal = results["A_tax_oblivious"]["metrics"]["terminal_wealth"]
    print(f"\n{'Strategy':<35} {'Tax Savings vs A':>18} {'Terminal Gain':>14} {'Sharpe Diff':>12}")
    print("-" * 80)
    for key, strat in sorted_strats:
        m = strat["metrics"]
        tax_saving = baseline_taxes - m["total_taxes_paid"]
        terminal_gain = m["terminal_wealth"] - baseline_terminal
        sharpe_diff = m["sharpe"] - results["A_tax_oblivious"]["metrics"]["sharpe"]
        sign_t = "+" if tax_saving >= 0 else ""
        sign_w = "+" if terminal_gain >= 0 else ""
        sign_s = "+" if sharpe_diff >= 0 else ""
        print(f"{strat['name']:<35} {sign_t}${abs(tax_saving):>14,.0f}   "
              f"{sign_w}${abs(terminal_gain):>10,.0f}   {sign_s}{sharpe_diff:>8.3f}")

    # ========== KEY FINDINGS ==========
    best_key = sorted_strats[0][0]
    best = results[best_key]
    worst_key = sorted_strats[-1][0]
    worst = results[worst_key]

    findings = []
    findings.append(f"Best after-tax strategy: {best['name']} (Sharpe {best['metrics']['sharpe']:.3f})")
    findings.append(f"Worst: {worst['name']} (Sharpe {worst['metrics']['sharpe']:.3f})")
    findings.append(f"Sharpe range: {worst['metrics']['sharpe']:.3f} to {best['metrics']['sharpe']:.3f}")

    # Tax savings
    tax_savings = {k: baseline_taxes - v["metrics"]["total_taxes_paid"]
                   for k, v in results.items() if k != "A_tax_oblivious"}
    best_saver = max(tax_savings, key=tax_savings.get)
    findings.append(f"Most tax-efficient: {results[best_saver]['name']} "
                    f"(saves ${tax_savings[best_saver]:,.0f} vs daily rebalance)")

    print("\n" + "=" * 70)
    print("KEY FINDINGS")
    print("=" * 70)
    for f in findings:
        print(f"  • {f}")

    # ========== SAVE RESULTS ==========
    output = {
        "experiment_id": "K676",
        "title": "Tax-Aware VT Strategy Optimization",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "data_period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "sample_size": len(df),
        "methodology": (
            "Simulated 5 tax-aware variants of 50/50 SPY/GLD + 12/VIX signal. "
            "FIFO lot tracking with short-term (≤252 days, 22%) and long-term "
            "(>252 days, 15%) capital gains rates. Losses offset gains with "
            "carry-forward. $100,000 initial capital. Based on K604 finding "
            "that taxes eat ~27% of Sharpe."
        ),
        "reference": "K604 (Practical Implementation Cost Analysis)",
        "tax_parameters": TAX_PARAMS,
        "initial_capital": 100_000,
        "strategies": {},
        "comparison": {},
        "key_findings": findings,
    }

    for key, strat in results.items():
        output["strategies"][key] = {
            "name": strat["name"],
            "description": strat["description"],
            "metrics": strat["metrics"],
            "yearly_taxes": {str(k): v for k, v in strat["yearly_taxes"].items()},
        }

    # Comparison summary
    for key in results:
        m = results[key]["metrics"]
        output["comparison"][key] = {
            "name": results[key]["name"],
            "sharpe": m["sharpe"],
            "cagr_pct": m["cagr_pct"],
            "terminal_wealth": m["terminal_wealth"],
            "total_taxes_paid": m["total_taxes_paid"],
            "tax_savings_vs_A": round(baseline_taxes - m["total_taxes_paid"], 2),
            "terminal_gain_vs_A": round(m["terminal_wealth"] - baseline_terminal, 2),
        }

    output_path = PROJECT_ROOT / "experiments" / "k676_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    return output


if __name__ == "__main__":
    main()
