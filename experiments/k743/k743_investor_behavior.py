"""K743: Investor Behavior Under VT — Do Investors Actually Follow the Signal?
==============================================================================
Quantify the BEHAVIORAL COST of common investor mistakes when using 12/VIX VT.

K738 showed γ≥4.5 investors should use VT. K742 showed crowding is manageable.
K675 showed panic selling costs 76% terminal wealth. But HOW MUCH does each
specific behavioral mistake cost within the VT framework?

Part A: Simulate 5 types of imperfect VT execution vs perfect 12/VIX
  1. Panic Override — VIX>30 → go 100% cash (fear overrides signal)
  2. FOMO Override — SPY daily return >2% → go 100% equity next day
  3. Delayed Rebalance — only rebalance when weight deviates >10%
  4. Anchoring — use last month's VIX (stale signal)
  5. Loss Aversion — exit VT after 3 consecutive losing months

Part B: Behavioral Cost Quantification
  - Sharpe cost, MDD cost, CAGR cost per mistake
  - Rank mistakes by severity

Part C: Robust VT Design
  - 3 behavioral-robust variants with floors/caps/smoothing
  - Test whether they survive behavioral mistakes better

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2006-01-01 to 2026-03-30 (~20 years)
Evaluation: 2007-01-03 to present (1y warmup)
Type: Empirical analysis + behavioral simulation (real market data, simulated behavior)

References:
  - K738: VT insurance cost-benefit, γ≥4.5 breakeven
  - K742: Crowding risk simulation — manageable
  - K675: Panic selling costs 76% terminal wealth
  - K687: No VT beats BH 50/50 on Sharpe after proper lag
  - K697: VIX predicts vol magnitude (r=0.57) not direction (r=0.04)
  - Kahneman & Tversky (1979), Prospect Theory, Econometrica
  - Benartzi & Thaler (1995), Myopic Loss Aversion and the Equity Premium Puzzle, QJE
  - Moreira & Muir (2017), Volatility-Managed Portfolios, JF
  - Harvey et al. (2016), ...and the Cross-Section of Expected Returns (t>3.0)
  - Odean (1998), Are Investors Reluctant to Realize Their Losses?, JF

[提出: Claude, 執行: Claude]
Author: VolPred Research System
Date: 2026-03-30
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2006-01-01"
END_DATE = "2026-03-30"
EVAL_START = "2007-01-03"
TC_BPS = 5                     # Transaction cost: 5 bps per leg
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
VIX_12_CAP = 1.5               # Max weight for 12/VIX

# Behavioral parameters
PANIC_VIX_THRESHOLD = 30       # VIX level triggering panic
FOMO_RETURN_THRESHOLD = 0.02   # Daily return triggering FOMO (2%)
LAZY_DEVIATION_THRESHOLD = 0.10  # Rebalance only when |w_actual - w_target| > 10%
ANCHORING_LAG_DAYS = 21        # Use VIX from ~1 month ago
LOSS_AVERSION_MONTHS = 3       # Exit after 3 consecutive losing months

# Robust VT parameters
FLOOR_EQUITY = 0.30            # Never below 30% equity
CEIL_EQUITY = 0.90             # Never above 90% equity
SMOOTHING_ALPHA = 0.3          # Exponential smoothing for weight changes


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY, GLD, VIX data from yfinance."""
    print("Downloading data from yfinance...")
    tickers = ["SPY", "GLD", "^VIX"]
    data = {}
    for t in tickers:
        df = yf.download(t, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[t.replace("^", "")] = df["Close"].dropna()

    # Align all series
    combined = pd.DataFrame(data)
    combined = combined.dropna()

    spy_ret = combined["SPY"].pct_change()
    gld_ret = combined["GLD"].pct_change()
    vix = combined["VIX"]

    return combined, spy_ret, gld_ret, vix


# ============================================================================
# Core Strategy: Perfect 12/VIX
# ============================================================================
def compute_perfect_12vix(spy_ret, gld_ret, vix, eval_mask):
    """Perfect 12/VIX execution: daily rebalance, proper lag."""
    # Signal from t-1, applied at t
    w_equity = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)
    w_equity = w_equity.fillna(0.5)

    # Portfolio: w_equity * SPY + (1 - w_equity) * GLD
    port_ret = w_equity * spy_ret + (1 - w_equity) * gld_ret

    # Transaction costs: |Δw| * TC_BPS * 2 (both legs)
    delta_w = w_equity.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask], w_equity[eval_mask]


# ============================================================================
# Buy & Hold 50/50
# ============================================================================
def compute_bh_5050(spy_ret, gld_ret, eval_mask):
    """Buy & Hold 50/50 SPY/GLD — monthly rebalance."""
    w = 0.5
    port_ret = w * spy_ret + (1 - w) * gld_ret

    # Monthly rebalance: small TX cost on rebalance days
    # Approximate: rebalance ~21 trading days
    idx = port_ret.index
    is_rebal = pd.Series(False, index=idx)
    for i in range(0, len(idx), 21):
        is_rebal.iloc[i] = True
    tc = is_rebal.astype(float) * 0.01 * TC_BPS / 10000 * 2  # small drift ~1%
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask]


# ============================================================================
# Behavioral Mistake #1: Panic Override
# ============================================================================
def compute_panic_override(spy_ret, gld_ret, vix, eval_mask):
    """When VIX > 30, investor overrides signal → 100% cash (GLD proxy)."""
    w_equity = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)
    w_equity = w_equity.fillna(0.5)

    # Panic override: when yesterday's VIX > 30, go 0% equity
    vix_lagged = vix.shift(1)
    panic_mask = vix_lagged > PANIC_VIX_THRESHOLD
    w_panic = w_equity.copy()
    w_panic[panic_mask] = 0.0  # 100% GLD (proxy for cash/safe haven)

    port_ret = w_panic * spy_ret + (1 - w_panic) * gld_ret
    delta_w = w_panic.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    n_panic_days = panic_mask[eval_mask].sum()

    return port_ret_net[eval_mask], w_panic[eval_mask], n_panic_days


# ============================================================================
# Behavioral Mistake #2: FOMO Override
# ============================================================================
def compute_fomo_override(spy_ret, gld_ret, vix, eval_mask):
    """When SPY daily return > 2%, investor goes 100% equity next day (FOMO)."""
    w_equity = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)
    w_equity = w_equity.fillna(0.5)

    # FOMO: when yesterday's SPY return > 2%, go 100% equity today
    spy_ret_lagged = spy_ret.shift(1)
    fomo_mask = spy_ret_lagged > FOMO_RETURN_THRESHOLD
    w_fomo = w_equity.copy()
    w_fomo[fomo_mask] = 1.0

    port_ret = w_fomo * spy_ret + (1 - w_fomo) * gld_ret
    delta_w = w_fomo.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    n_fomo_days = fomo_mask[eval_mask].sum()

    return port_ret_net[eval_mask], w_fomo[eval_mask], n_fomo_days


# ============================================================================
# Behavioral Mistake #3: Delayed Rebalance (Lazy Investor)
# ============================================================================
def compute_delayed_rebalance(spy_ret, gld_ret, vix, eval_mask):
    """Only rebalance when actual weight deviates >10% from 12/VIX target."""
    w_target = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)
    w_target = w_target.fillna(0.5)

    # Track actual weight accounting for market drift
    idx = w_target.index
    w_actual = pd.Series(np.nan, index=idx)
    w_actual.iloc[0] = 0.5

    for i in range(1, len(idx)):
        # Yesterday's actual weight drifts with returns
        prev_w = w_actual.iloc[i - 1]
        spy_r = spy_ret.iloc[i] if not np.isnan(spy_ret.iloc[i]) else 0
        gld_r = gld_ret.iloc[i] if not np.isnan(gld_ret.iloc[i]) else 0

        # After market move, weight drifts
        port_val = prev_w * (1 + spy_r) + (1 - prev_w) * (1 + gld_r)
        if port_val > 0:
            drifted_w = prev_w * (1 + spy_r) / port_val
        else:
            drifted_w = prev_w

        # Rebalance only if deviation exceeds threshold
        target = w_target.iloc[i]
        if abs(drifted_w - target) > LAZY_DEVIATION_THRESHOLD:
            w_actual.iloc[i] = target  # rebalance to target
        else:
            w_actual.iloc[i] = drifted_w  # stay drifted

    port_ret = w_actual * spy_ret + (1 - w_actual) * gld_ret
    delta_w = w_actual.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    # Count rebalance events
    n_rebal = (delta_w[eval_mask] > 0.001).sum()

    return port_ret_net[eval_mask], w_actual[eval_mask], n_rebal


# ============================================================================
# Behavioral Mistake #4: Anchoring (Stale VIX Signal)
# ============================================================================
def compute_anchoring(spy_ret, gld_ret, vix, eval_mask):
    """Investor uses VIX from ~1 month ago (anchored to stale information)."""
    # Use VIX from 21 trading days ago instead of yesterday
    vix_stale = vix.shift(ANCHORING_LAG_DAYS)
    w_equity = (12.0 / vix_stale).clip(upper=VIX_12_CAP).shift(1)
    w_equity = w_equity.fillna(0.5)

    port_ret = w_equity * spy_ret + (1 - w_equity) * gld_ret
    delta_w = w_equity.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask], w_equity[eval_mask]


# ============================================================================
# Behavioral Mistake #5: Loss Aversion (Quit After Losing)
# ============================================================================
def compute_loss_aversion(spy_ret, gld_ret, vix, eval_mask):
    """Exit VT after 3 consecutive losing months, switch to BH 50/50.
    Re-enter VT after 2 consecutive winning months of BH."""
    w_equity = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)
    w_equity = w_equity.fillna(0.5)

    # Monthly returns for VT
    idx = spy_ret.index
    port_ret_vt = w_equity * spy_ret + (1 - w_equity) * gld_ret
    port_ret_bh = 0.5 * spy_ret + 0.5 * gld_ret

    # Monthly return calculation
    monthly_ret_vt = port_ret_vt.resample("ME").sum()
    monthly_ret_bh = port_ret_bh.resample("ME").sum()

    # State machine: True = using VT, False = using BH 50/50
    using_vt = True
    consecutive_losses = 0
    consecutive_bh_wins = 0

    # Map month-end dates to state
    state_by_month = {}
    for m_date in monthly_ret_vt.index:
        state_by_month[m_date] = using_vt

        if using_vt:
            if monthly_ret_vt.loc[m_date] < 0:
                consecutive_losses += 1
            else:
                consecutive_losses = 0

            if consecutive_losses >= LOSS_AVERSION_MONTHS:
                using_vt = False
                consecutive_losses = 0
                consecutive_bh_wins = 0
        else:
            # Using BH — check if we should re-enter VT
            if monthly_ret_bh.loc[m_date] > 0:
                consecutive_bh_wins += 1
            else:
                consecutive_bh_wins = 0

            if consecutive_bh_wins >= 2:
                using_vt = True
                consecutive_bh_wins = 0
                consecutive_losses = 0

    # Create daily state series from monthly decisions
    daily_state = pd.Series(True, index=idx)
    sorted_months = sorted(state_by_month.keys())
    for i, m_date in enumerate(sorted_months):
        if i + 1 < len(sorted_months):
            next_m = sorted_months[i + 1]
            mask = (idx > m_date) & (idx <= next_m)
        else:
            mask = idx > m_date
        daily_state[mask] = state_by_month[m_date]

    # Apply: use VT weight when in VT mode, 0.5 when in BH mode
    w_loss_aversion = w_equity.copy()
    w_loss_aversion[~daily_state] = 0.5

    port_ret = w_loss_aversion * spy_ret + (1 - w_loss_aversion) * gld_ret
    delta_w = w_loss_aversion.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    n_switches = sum(1 for i in range(1, len(sorted_months))
                     if state_by_month[sorted_months[i]] != state_by_month[sorted_months[i-1]])
    pct_in_bh = (~daily_state[eval_mask]).mean() * 100

    return port_ret_net[eval_mask], w_loss_aversion[eval_mask], n_switches, pct_in_bh


# ============================================================================
# Part C: Behavioral-Robust VT Variants
# ============================================================================
def compute_robust_floor_cap(spy_ret, gld_ret, vix, eval_mask):
    """Robust VT v1: Floor 30% / Cap 90% equity — prevents extreme positions."""
    w_equity = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)
    w_equity = w_equity.fillna(0.5)
    w_equity = w_equity.clip(lower=FLOOR_EQUITY, upper=CEIL_EQUITY)

    port_ret = w_equity * spy_ret + (1 - w_equity) * gld_ret
    delta_w = w_equity.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask], w_equity[eval_mask]


def compute_robust_smoothed(spy_ret, gld_ret, vix, eval_mask):
    """Robust VT v2: EWMA-smoothed weight changes — prevents whipsaw."""
    w_target = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)
    w_target = w_target.fillna(0.5)

    # Exponential smoothing: w_t = α * target_t + (1-α) * w_{t-1}
    w_smoothed = w_target.ewm(alpha=SMOOTHING_ALPHA, adjust=False).mean()

    port_ret = w_smoothed * spy_ret + (1 - w_smoothed) * gld_ret
    delta_w = w_smoothed.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask], w_smoothed[eval_mask]


def compute_robust_combined(spy_ret, gld_ret, vix, eval_mask):
    """Robust VT v3: Floor/Cap + Smoothing + Weekly rebalance."""
    w_target = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1)
    w_target = w_target.fillna(0.5)

    # Floor/cap
    w_target = w_target.clip(lower=FLOOR_EQUITY, upper=CEIL_EQUITY)

    # Smoothing
    w_smoothed = w_target.ewm(alpha=SMOOTHING_ALPHA, adjust=False).mean()

    # Weekly rebalance: only change weight on Fridays
    idx = w_smoothed.index
    is_friday = pd.Series(idx.dayofweek == 4, index=idx)

    w_weekly = w_smoothed.copy()
    last_rebal_w = 0.5
    for i in range(len(idx)):
        if is_friday.iloc[i]:
            last_rebal_w = w_smoothed.iloc[i]
        w_weekly.iloc[i] = last_rebal_w

    port_ret = w_weekly * spy_ret + (1 - w_weekly) * gld_ret
    delta_w = w_weekly.diff().abs().fillna(0)
    tc = delta_w * TC_BPS / 10000 * 2
    port_ret_net = port_ret - tc

    return port_ret_net[eval_mask], w_weekly[eval_mask]


# ============================================================================
# Performance Metrics
# ============================================================================
def compute_metrics(returns, name=""):
    """Compute standard performance metrics."""
    ret = returns.dropna()
    if len(ret) < 252:
        return {"name": name, "error": "insufficient data"}

    # Annualized return (geometric)
    cum = (1 + ret).prod()
    n_years = len(ret) / 252
    cagr = cum ** (1 / n_years) - 1

    # Annualized volatility
    vol = ret.std() * np.sqrt(252)

    # Sharpe ratio (excess return / vol)
    excess = ret - RF_DAILY
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

    # Maximum drawdown
    cum_ret = (1 + ret).cumprod()
    running_max = cum_ret.cummax()
    drawdown = cum_ret / running_max - 1
    mdd = drawdown.min()

    # Calmar ratio
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Worst month
    monthly = ret.resample("ME").sum()
    worst_month = monthly.min()

    # Terminal wealth from $100
    terminal = 100 * cum

    # Sortino ratio
    downside = ret[ret < 0]
    downside_vol = downside.std() * np.sqrt(252)
    sortino = (cagr - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

    return {
        "name": name,
        "cagr": round(float(cagr), 4),
        "vol": round(float(vol), 4),
        "sharpe": round(float(sharpe), 4),
        "mdd": round(float(mdd), 4),
        "calmar": round(float(calmar), 4),
        "sortino": round(float(sortino), 4),
        "worst_month": round(float(worst_month), 4),
        "terminal_100": round(float(terminal), 2),
        "n_days": len(ret),
        "n_years": round(n_years, 1),
    }


def compute_behavioral_cost(perfect_metrics, mistake_metrics):
    """Compute the cost of a behavioral mistake vs perfect execution."""
    cost = {}
    for key in ["sharpe", "cagr", "mdd", "terminal_100", "sortino"]:
        perfect_val = perfect_metrics[key]
        mistake_val = mistake_metrics[key]

        if key == "mdd":
            # More negative MDD = worse → cost is how much deeper
            cost[f"{key}_diff"] = round(mistake_val - perfect_val, 4)
            cost[f"{key}_pct_worse"] = round(
                (mistake_val - perfect_val) / abs(perfect_val) * 100, 1
            ) if perfect_val != 0 else 0
        elif key == "terminal_100":
            cost[f"{key}_diff"] = round(mistake_val - perfect_val, 2)
            cost[f"{key}_pct_loss"] = round(
                (mistake_val - perfect_val) / perfect_val * 100, 1
            ) if perfect_val > 0 else 0
        else:
            cost[f"{key}_diff"] = round(mistake_val - perfect_val, 4)
            cost[f"{key}_pct_change"] = round(
                (mistake_val - perfect_val) / abs(perfect_val) * 100, 1
            ) if perfect_val != 0 else 0

    return cost


# ============================================================================
# Crisis Period Analysis
# ============================================================================
def crisis_analysis(returns_dict, spy_ret, eval_mask):
    """Analyze performance during crisis periods."""
    crises = {
        "GFC (2008-09)": ("2008-09-01", "2009-03-31"),
        "COVID (2020-02/03)": ("2020-02-19", "2020-03-23"),
        "2022 Bear": ("2022-01-03", "2022-10-12"),
        "VIX Spike Aug 2024": ("2024-07-15", "2024-08-15"),
    }

    results = {}
    for crisis_name, (start, end) in crises.items():
        crisis_results = {}
        for strat_name, ret_series in returns_dict.items():
            mask = (ret_series.index >= start) & (ret_series.index <= end)
            crisis_ret = ret_series[mask]
            if len(crisis_ret) < 5:
                continue
            cum = (1 + crisis_ret).prod() - 1
            crisis_results[strat_name] = round(float(cum), 4)
        results[crisis_name] = crisis_results

    return results


# ============================================================================
# Part C: Behavioral Robustness Test
# ============================================================================
def test_robustness_under_mistakes(spy_ret, gld_ret, vix, eval_mask):
    """Test if robust VT variants survive behavioral mistakes better.
    Apply panic override to both perfect 12/VIX and robust variants."""

    # Perfect 12/VIX with panic override (baseline)
    w_perfect = (12.0 / vix).clip(upper=VIX_12_CAP).shift(1).fillna(0.5)
    vix_lagged = vix.shift(1)
    panic_mask = vix_lagged > PANIC_VIX_THRESHOLD

    # Apply panic override to each variant
    variants = {}

    # 1. Perfect 12/VIX + panic
    w1 = w_perfect.copy()
    w1[panic_mask] = 0.0
    r1 = w1 * spy_ret + (1 - w1) * gld_ret
    delta1 = w1.diff().abs().fillna(0)
    tc1 = delta1 * TC_BPS / 10000 * 2
    variants["perfect_12vix_panicked"] = (r1 - tc1)[eval_mask]

    # 2. Floor/Cap VT + panic → floor prevents going to 0
    w2_base = w_perfect.clip(lower=FLOOR_EQUITY, upper=CEIL_EQUITY)
    w2 = w2_base.copy()
    w2[panic_mask] = FLOOR_EQUITY  # panic, but floor prevents 0%
    r2 = w2 * spy_ret + (1 - w2) * gld_ret
    delta2 = w2.diff().abs().fillna(0)
    tc2 = delta2 * TC_BPS / 10000 * 2
    variants["floor_cap_panicked"] = (r2 - tc2)[eval_mask]

    # 3. Smoothed VT + panic → smoothing dampens panic response
    w3_target = w_perfect.copy()
    w3_target[panic_mask] = 0.0
    w3 = w3_target.ewm(alpha=SMOOTHING_ALPHA, adjust=False).mean()
    r3 = w3 * spy_ret + (1 - w3) * gld_ret
    delta3 = w3.diff().abs().fillna(0)
    tc3 = delta3 * TC_BPS / 10000 * 2
    variants["smoothed_panicked"] = (r3 - tc3)[eval_mask]

    # 4. Combined VT + panic → both protections
    w4_target = w_perfect.clip(lower=FLOOR_EQUITY, upper=CEIL_EQUITY)
    w4_target_panicked = w4_target.copy()
    w4_target_panicked[panic_mask] = FLOOR_EQUITY
    w4 = w4_target_panicked.ewm(alpha=SMOOTHING_ALPHA, adjust=False).mean()
    r4 = w4 * spy_ret + (1 - w4) * gld_ret
    delta4 = w4.diff().abs().fillna(0)
    tc4 = delta4 * TC_BPS / 10000 * 2
    variants["combined_panicked"] = (r4 - tc4)[eval_mask]

    return {name: compute_metrics(ret, name) for name, ret in variants.items()}


# ============================================================================
# Main Execution
# ============================================================================
def main():
    print("=" * 70)
    print("K743: Investor Behavior Under VT — Behavioral Cost Quantification")
    print("=" * 70)

    # Download data
    combined, spy_ret, gld_ret, vix = download_data()

    # Create evaluation mask
    eval_mask = spy_ret.index >= EVAL_START

    print(f"\nData: {combined.index[0].strftime('%Y-%m-%d')} to "
          f"{combined.index[-1].strftime('%Y-%m-%d')}")
    print(f"Evaluation: {EVAL_START} to {combined.index[-1].strftime('%Y-%m-%d')}")
    print(f"Eval days: {eval_mask.sum()}")

    # ========================================================================
    # Part A: Compute all strategies
    # ========================================================================
    print("\n" + "=" * 70)
    print("Part A: Computing strategies...")
    print("=" * 70)

    # 1. Perfect 12/VIX
    ret_perfect, w_perfect = compute_perfect_12vix(spy_ret, gld_ret, vix, eval_mask)
    m_perfect = compute_metrics(ret_perfect, "Perfect 12/VIX")
    print(f"\n1. Perfect 12/VIX: Sharpe={m_perfect['sharpe']}, "
          f"CAGR={m_perfect['cagr']:.1%}, MDD={m_perfect['mdd']:.1%}")

    # 2. BH 50/50
    ret_bh = compute_bh_5050(spy_ret, gld_ret, eval_mask)
    m_bh = compute_metrics(ret_bh, "BH 50/50")
    print(f"2. BH 50/50:      Sharpe={m_bh['sharpe']}, "
          f"CAGR={m_bh['cagr']:.1%}, MDD={m_bh['mdd']:.1%}")

    # 3. Panic Override
    ret_panic, w_panic, n_panic = compute_panic_override(
        spy_ret, gld_ret, vix, eval_mask)
    m_panic = compute_metrics(ret_panic, "Panic Override")
    print(f"\n3. Panic Override: Sharpe={m_panic['sharpe']}, "
          f"CAGR={m_panic['cagr']:.1%}, MDD={m_panic['mdd']:.1%}, "
          f"panic days={n_panic}")

    # 4. FOMO Override
    ret_fomo, w_fomo, n_fomo = compute_fomo_override(
        spy_ret, gld_ret, vix, eval_mask)
    m_fomo = compute_metrics(ret_fomo, "FOMO Override")
    print(f"4. FOMO Override:  Sharpe={m_fomo['sharpe']}, "
          f"CAGR={m_fomo['cagr']:.1%}, MDD={m_fomo['mdd']:.1%}, "
          f"FOMO days={n_fomo}")

    # 5. Delayed Rebalance
    ret_lazy, w_lazy, n_rebal = compute_delayed_rebalance(
        spy_ret, gld_ret, vix, eval_mask)
    m_lazy = compute_metrics(ret_lazy, "Delayed Rebalance")
    print(f"5. Delayed Rebal:  Sharpe={m_lazy['sharpe']}, "
          f"CAGR={m_lazy['cagr']:.1%}, MDD={m_lazy['mdd']:.1%}, "
          f"rebalances={n_rebal}")

    # 6. Anchoring (Stale VIX)
    ret_anchor, w_anchor = compute_anchoring(
        spy_ret, gld_ret, vix, eval_mask)
    m_anchor = compute_metrics(ret_anchor, "Anchoring (Stale VIX)")
    print(f"6. Anchoring:      Sharpe={m_anchor['sharpe']}, "
          f"CAGR={m_anchor['cagr']:.1%}, MDD={m_anchor['mdd']:.1%}")

    # 7. Loss Aversion
    ret_loss, w_loss, n_switches, pct_bh = compute_loss_aversion(
        spy_ret, gld_ret, vix, eval_mask)
    m_loss = compute_metrics(ret_loss, "Loss Aversion")
    print(f"7. Loss Aversion:  Sharpe={m_loss['sharpe']}, "
          f"CAGR={m_loss['cagr']:.1%}, MDD={m_loss['mdd']:.1%}, "
          f"switches={n_switches}, %inBH={pct_bh:.1f}%")

    # ========================================================================
    # Part B: Behavioral Cost Quantification
    # ========================================================================
    print("\n" + "=" * 70)
    print("Part B: Behavioral Cost Quantification (vs Perfect 12/VIX)")
    print("=" * 70)

    mistakes = {
        "Panic Override": m_panic,
        "FOMO Override": m_fomo,
        "Delayed Rebalance": m_lazy,
        "Anchoring (Stale VIX)": m_anchor,
        "Loss Aversion": m_loss,
    }

    costs = {}
    for name, metrics in mistakes.items():
        cost = compute_behavioral_cost(m_perfect, metrics)
        costs[name] = cost
        sharpe_cost = cost.get("sharpe_diff", 0)
        terminal_cost = cost.get("terminal_100_pct_loss", 0)
        print(f"\n  {name}:")
        print(f"    Sharpe cost: {sharpe_cost:+.4f} "
              f"({cost.get('sharpe_pct_change', 0):+.1f}%)")
        print(f"    Terminal wealth: {cost.get('terminal_100_diff', 0):+.2f} "
              f"({terminal_cost:+.1f}%)")
        print(f"    MDD change: {cost.get('mdd_diff', 0):+.4f} "
              f"({cost.get('mdd_pct_worse', 0):+.1f}%)")

    # Rank by Sharpe cost (most negative = most costly)
    ranked = sorted(costs.items(), key=lambda x: x[1].get("sharpe_diff", 0))
    print("\n  RANKING (most costly to least costly):")
    for i, (name, cost) in enumerate(ranked, 1):
        print(f"    #{i}: {name} "
              f"(Sharpe {cost.get('sharpe_diff', 0):+.4f}, "
              f"Terminal {cost.get('terminal_100_pct_loss', 0):+.1f}%)")

    # ========================================================================
    # Part C: Robust VT Variants
    # ========================================================================
    print("\n" + "=" * 70)
    print("Part C: Robust VT Variants")
    print("=" * 70)

    # Compute robust variants
    ret_floor, w_floor = compute_robust_floor_cap(spy_ret, gld_ret, vix, eval_mask)
    m_floor = compute_metrics(ret_floor, "Robust: Floor/Cap")

    ret_smooth, w_smooth = compute_robust_smoothed(spy_ret, gld_ret, vix, eval_mask)
    m_smooth = compute_metrics(ret_smooth, "Robust: Smoothed")

    ret_combined, w_combined = compute_robust_combined(spy_ret, gld_ret, vix, eval_mask)
    m_combined = compute_metrics(ret_combined, "Robust: Combined")

    robust_variants = {
        "Floor/Cap (30%-90%)": m_floor,
        "EWMA Smoothed (α=0.3)": m_smooth,
        "Combined (Floor+Smooth+Weekly)": m_combined,
    }

    print(f"\n  Perfect 12/VIX:     Sharpe={m_perfect['sharpe']}, "
          f"CAGR={m_perfect['cagr']:.1%}, MDD={m_perfect['mdd']:.1%}")
    for name, m in robust_variants.items():
        print(f"  {name}: Sharpe={m['sharpe']}, "
              f"CAGR={m['cagr']:.1%}, MDD={m['mdd']:.1%}")

    # Test robustness under panic override
    print("\n  --- Robustness Under Panic Override ---")
    panic_robustness = test_robustness_under_mistakes(
        spy_ret, gld_ret, vix, eval_mask)

    for name, m in panic_robustness.items():
        print(f"  {name}: Sharpe={m['sharpe']}, "
              f"CAGR={m['cagr']:.1%}, MDD={m['mdd']:.1%}")

    # Compute protection ratio: how much of panic cost does each variant recover?
    base_panic_sharpe = panic_robustness["perfect_12vix_panicked"]["sharpe"]
    perfect_sharpe = m_perfect["sharpe"]
    sharpe_lost_to_panic = perfect_sharpe - base_panic_sharpe

    protection = {}
    if sharpe_lost_to_panic != 0:
        for name, m in panic_robustness.items():
            if name == "perfect_12vix_panicked":
                continue
            recovered = m["sharpe"] - base_panic_sharpe
            pct_protected = recovered / sharpe_lost_to_panic * 100
            protection[name] = round(pct_protected, 1)
            print(f"  {name}: recovers {pct_protected:.1f}% of panic cost")

    # ========================================================================
    # Crisis Analysis
    # ========================================================================
    print("\n" + "=" * 70)
    print("Crisis Period Performance")
    print("=" * 70)

    returns_dict = {
        "Perfect 12/VIX": ret_perfect,
        "BH 50/50": ret_bh,
        "Panic Override": ret_panic,
        "FOMO Override": ret_fomo,
        "Delayed Rebalance": ret_lazy,
        "Anchoring": ret_anchor,
        "Loss Aversion": ret_loss,
        "Robust: Floor/Cap": ret_floor,
        "Robust: Smoothed": ret_smooth,
        "Robust: Combined": ret_combined,
    }

    crisis_results = crisis_analysis(returns_dict, spy_ret, eval_mask)
    for crisis_name, strat_rets in crisis_results.items():
        print(f"\n  {crisis_name}:")
        for strat_name, cum_ret in sorted(strat_rets.items(),
                                           key=lambda x: x[1], reverse=True):
            print(f"    {strat_name}: {cum_ret:+.1%}")

    # ========================================================================
    # Statistical significance
    # ========================================================================
    print("\n" + "=" * 70)
    print("Statistical Tests")
    print("=" * 70)

    # Paired t-test: Perfect 12/VIX vs each mistake
    stat_tests = {}
    aligned_perfect = ret_perfect.reindex(ret_perfect.index)

    for name, ret in [("Panic", ret_panic), ("FOMO", ret_fomo),
                       ("Delayed", ret_lazy), ("Anchoring", ret_anchor),
                       ("Loss Aversion", ret_loss)]:
        common_idx = aligned_perfect.index.intersection(ret.index)
        diff = aligned_perfect[common_idx] - ret[common_idx]
        diff = diff.dropna()
        if len(diff) > 30:
            t_stat, p_val = sp_stats.ttest_1samp(diff, 0)
            stat_tests[name] = {
                "t_stat": round(float(t_stat), 3),
                "p_value": round(float(p_val), 4),
                "mean_diff_bps": round(float(diff.mean() * 10000), 2),
                "significant_5pct": p_val < 0.05,
                "harvey_significant": abs(t_stat) > 3.0,
            }
            print(f"  Perfect vs {name}: t={t_stat:.3f}, p={p_val:.4f}, "
                  f"mean diff={diff.mean()*10000:.2f} bps/day"
                  f" {'***' if abs(t_stat) > 3 else '**' if p_val < 0.05 else ''}")

    # ========================================================================
    # Compile Results
    # ========================================================================
    print("\n" + "=" * 70)
    print("Compiling results...")
    print("=" * 70)

    all_metrics = {
        "benchmarks": {
            "perfect_12vix": m_perfect,
            "bh_5050": m_bh,
        },
        "behavioral_mistakes": {
            "panic_override": {
                **m_panic,
                "description": "VIX>30 → override signal, go 100% GLD",
                "n_panic_days": int(n_panic),
                "pct_panic_days": round(n_panic / eval_mask.sum() * 100, 1),
            },
            "fomo_override": {
                **m_fomo,
                "description": "SPY daily return >2% → override signal, go 100% equity",
                "n_fomo_days": int(n_fomo),
                "pct_fomo_days": round(n_fomo / eval_mask.sum() * 100, 1),
            },
            "delayed_rebalance": {
                **m_lazy,
                "description": "Only rebalance when weight deviates >10% from target",
                "n_rebalances": int(n_rebal),
            },
            "anchoring_stale_vix": {
                **m_anchor,
                "description": f"Use VIX from {ANCHORING_LAG_DAYS} trading days ago",
            },
            "loss_aversion": {
                **m_loss,
                "description": "Exit VT after 3 consecutive losing months, re-enter after 2 winning",
                "n_mode_switches": int(n_switches),
                "pct_time_in_bh": round(pct_bh, 1),
            },
        },
        "behavioral_costs": costs,
        "cost_ranking_by_sharpe": [
            {"rank": i + 1, "mistake": name, "sharpe_cost": cost.get("sharpe_diff", 0),
             "terminal_pct_loss": cost.get("terminal_100_pct_loss", 0)}
            for i, (name, cost) in enumerate(ranked)
        ],
        "robust_variants": {
            "floor_cap": m_floor,
            "smoothed": m_smooth,
            "combined": m_combined,
        },
        "panic_robustness_test": {
            "metrics": panic_robustness,
            "protection_pct": protection,
        },
        "crisis_analysis": crisis_results,
        "statistical_tests": stat_tests,
    }

    # Summary
    most_costly = ranked[0][0]
    least_costly = ranked[-1][0]

    summary = {
        "most_costly_mistake": most_costly,
        "most_costly_sharpe_loss": ranked[0][1].get("sharpe_diff", 0),
        "most_costly_terminal_loss_pct": ranked[0][1].get("terminal_100_pct_loss", 0),
        "least_costly_mistake": least_costly,
        "least_costly_sharpe_loss": ranked[-1][1].get("sharpe_diff", 0),
        "best_robust_variant": max(
            robust_variants.items(), key=lambda x: x[1]["sharpe"])[0],
        "best_robust_sharpe": max(
            robust_variants.items(), key=lambda x: x[1]["sharpe"])[1]["sharpe"],
        "best_protection_variant": max(protection.items(), key=lambda x: x[1])[0] if protection else "N/A",
        "best_protection_pct": max(protection.values()) if protection else 0,
    }

    print(f"\n  SUMMARY:")
    print(f"  Most costly mistake: {most_costly} "
          f"(Sharpe {ranked[0][1].get('sharpe_diff', 0):+.4f})")
    print(f"  Least costly mistake: {least_costly} "
          f"(Sharpe {ranked[-1][1].get('sharpe_diff', 0):+.4f})")
    print(f"  Best robust variant: "
          f"{max(robust_variants.items(), key=lambda x: x[1]['sharpe'])[0]}")
    if protection:
        best_prot = max(protection.items(), key=lambda x: x[1])
        print(f"  Best panic protection: {best_prot[0]} ({best_prot[1]:.1f}%)")

    # ========================================================================
    # Save Results
    # ========================================================================
    results = {
        "experiment_id": "K743",
        "title": "Investor Behavior Under VT — Behavioral Cost Quantification",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "period": f"{combined.index[0].strftime('%Y-%m-%d')} to "
                  f"{combined.index[-1].strftime('%Y-%m-%d')}",
        "eval_period": f"{EVAL_START} to "
                       f"{combined.index[-1].strftime('%Y-%m-%d')}",
        "eval_days": int(eval_mask.sum()),
        "methodology": "Empirical simulation with real market data, "
                       "behavioral overrides on 12/VIX signal",
        "lag_verification": "All strategies use signal.shift(1) — "
                           "signal from t-1, return at t",
        "tx_cost": f"{TC_BPS} bps per leg, applied on abs(Δw)",
        "parameters": {
            "vix_12_cap": VIX_12_CAP,
            "panic_vix_threshold": PANIC_VIX_THRESHOLD,
            "fomo_return_threshold": FOMO_RETURN_THRESHOLD,
            "lazy_deviation_threshold": LAZY_DEVIATION_THRESHOLD,
            "anchoring_lag_days": ANCHORING_LAG_DAYS,
            "loss_aversion_months": LOSS_AVERSION_MONTHS,
            "robust_floor": FLOOR_EQUITY,
            "robust_cap": CEIL_EQUITY,
            "smoothing_alpha": SMOOTHING_ALPHA,
        },
        "references": [
            "K738: VT insurance cost-benefit, γ≥4.5 breakeven",
            "K742: Crowding risk simulation — manageable",
            "K675: Panic selling costs 76% terminal wealth",
            "K687: No VT beats BH 50/50 on Sharpe after proper lag",
            "K697: VIX predicts vol magnitude (r=0.57) not direction (r=0.04)",
            "Kahneman & Tversky (1979), Prospect Theory, Econometrica",
            "Benartzi & Thaler (1995), Myopic Loss Aversion, QJE",
            "Moreira & Muir (2017), Vol-Managed Portfolios, JF",
            "Odean (1998), Reluctance to Realize Losses, JF",
        ],
        "metrics": all_metrics,
        "summary": summary,
        "proposer": "Claude",
        "executor": "Claude",
    }

    out_path = Path("experiments/k743_investor_behavior_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == "__main__":
    results = main()
    print("\nDone.")
