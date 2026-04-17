#!/usr/bin/env python3
"""
K717: NSI Regression — Multi-Asset Strategy Scorecard
======================================================
RECONSTRUCTED from paper/volatility-absorption/main_v2.tex (2026-04-17)
Reason: original .py never committed; replication package recovery.

NOTE: k717_results.json contains a strategy scorecard (slow_vt, risk_parity,
      recommended_5050, etc.) rather than the NSI regression described in the
      methodology. This experiment appears to be a VT strategy comparison that
      was cited as K717 in the paper but contains DIFFERENT content than what
      main_v2.tex references as "NSI regression (K717)". The paper's NSI
      regression (slope=-0.00028, t=-3.42 for SPY) is actually produced in K716.

      This reconstruction implements the strategy scorecard that IS in k717_results.json:
      a multi-strategy volatility-targeting comparison using SPY data
      (2022-01-01 to 2026-04-17, ~810-825 days, matching n_days in results).

Research Question (from k717_results.json structure):
    Which VT/hybrid strategy has the best composite score across
    CAGR, Sharpe, Sortino, MDD, Calmar, win-rate dimensions?

Data:
    - SPY, 0050.TW: yfinance
    - Strategy period appears to be ~2022-2026 (n_days ~809 for most strategies)

Output:
    k717_results_reconstructed.json
    k717_reconstruction_diff.md
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).parent

# Strategy backtesting period inferred from n_days ≈ 809-827
# Most strategies have 809 days → ~2022-10-01 to 2026-03-31
START_MAIN = "2022-10-01"
START_TW = "2022-07-01"   # Taiwan strategies have ~747-775 days
END = "2026-03-31"
TARGET_VOL = 12.0  # 12/VIX rule
RISK_FREE = 0.0


def download_data():
    """Download SPY, 0050.TW daily close prices."""
    tickers = ["SPY", "0050.TW", "^VIX", "GLD", "TLT"]
    raw = yf.download(
        tickers, start="2021-01-01", end=END, auto_adjust=True, progress=False
    )
    close = raw["Close"].copy()
    close.columns = [c.replace("^", "") for c in close.columns]
    return close


def log_returns(prices):
    return np.log(prices / prices.shift(1))


def compute_metrics(ret_series, name="strategy"):
    """Compute CAGR, Sharpe, Sortino, MDD, Calmar, win rates."""
    ret = ret_series.dropna()
    n = len(ret)
    years = n / 252.0

    cum = (1 + ret).cumprod()
    total_return = float(cum.iloc[-1] - 1) * 100
    cagr = float((cum.iloc[-1] ** (1 / years) - 1) * 100) if years > 0 else 0

    ann_vol = float(ret.std() * np.sqrt(252)) * 100
    sharpe = cagr / ann_vol if ann_vol > 0 else 0

    neg = ret[ret < 0]
    downside = float(neg.std() * np.sqrt(252)) * 100
    sortino = cagr / downside if downside > 0 else 0

    roll_max = cum.cummax()
    dd = (cum / roll_max - 1)
    mdd = float(dd.min()) * 100

    calmar = cagr / abs(mdd) if mdd < 0 else 0

    monthly = ret.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    win_rate_monthly = float((monthly > 0).mean()) * 100

    win_rate_daily = float((ret > 0).mean()) * 100

    return {
        "cagr": round(cagr, 1),
        "total_return": round(total_return, 1),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "mdd": round(mdd, 1),
        "calmar": round(calmar, 2),
        "win_rate_monthly": round(win_rate_monthly, 1),
        "win_rate_daily": round(win_rate_daily, 1),
        "n_days": n,
    }


def strategy_slow_vt(spy_ret, vix, target=12.0):
    """Slow VT: weight = target/VIX, lagged."""
    w = (target / vix.shift(1)).clip(0, 1.5)
    ret = (w.shift(1) * spy_ret).dropna()
    return ret


def strategy_risk_parity(spy_ret, gld_ret, tlt_ret):
    """Simple risk parity: equal vol-weighted SPY, GLD, TLT."""
    assets = pd.concat([spy_ret, gld_ret, tlt_ret], axis=1)
    assets.columns = ["SPY", "GLD", "TLT"]
    vol = assets.rolling(20).std()
    inv_vol = 1 / vol
    w = inv_vol.div(inv_vol.sum(axis=1), axis=0)
    ret = (w.shift(1) * assets).sum(axis=1).dropna()
    return ret


def main():
    print("K717: Multi-strategy scorecard — downloading data...")
    close = download_data()

    spy = close["SPY"].dropna()
    gld = close["GLD"].dropna()
    tlt = close["TLT"].dropna()
    vix = close["VIX"].dropna()
    tw = close["0050.TW"].dropna()

    spy_r = log_returns(spy)
    gld_r = log_returns(gld)
    tlt_r = log_returns(tlt)
    tw_r = log_returns(tw)

    # Restrict to strategy period
    start = pd.Timestamp(START_MAIN)
    end = pd.Timestamp(END)
    spy_r_m = spy_r.loc[start:end]
    gld_r_m = gld_r.loc[start:end]
    tlt_r_m = tlt_r.loc[start:end]
    vix_m = vix.loc[start:end]

    print(f"Main strategy period: {spy_r_m.index[0].date()} to {spy_r_m.index[-1].date()}, N={len(spy_r_m)}")

    # Compute strategies (simplified versions matching paper descriptions)
    strats = {}

    # slow_vt: 12/VIX weight
    w_vt = (TARGET_VOL / vix_m.shift(1)).clip(0, 1.5)
    strats["slow_vt"] = (w_vt.shift(1) * spy_r_m).dropna()

    # risk_parity
    strats["risk_parity"] = strategy_risk_parity(spy_r_m, gld_r_m, tlt_r_m)

    # simple_12vix (same as slow_vt but uncapped)
    w_12 = (12.0 / vix_m.shift(1)).clip(0, 1.0)
    strats["simple_12vix"] = (w_12.shift(1) * spy_r_m).dropna()

    # recommended_5050: 50% risk_parity + 50% slow_vt
    common_idx = strats["slow_vt"].index.intersection(strats["risk_parity"].index)
    strats["recommended_5050"] = (
        0.5 * strats["slow_vt"].loc[common_idx]
        + 0.5 * strats["risk_parity"].loc[common_idx]
    )

    # Build results (simplified metrics)
    output = {}
    for name, ret in strats.items():
        m = compute_metrics(ret, name)
        m["stress_apr2025"] = "N/A"  # would need specific date calculation
        output[name] = m

    # Save reconstructed results
    out_path = OUT_DIR / "k717_results_reconstructed.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved: {out_path}")

    # ─── Generate diff report ─────────────────────────────────────────────────
    orig_path = OUT_DIR / "k717_results.json"
    if orig_path.exists():
        with open(orig_path) as f:
            orig = json.load(f)
        generate_diff_report(orig, output, OUT_DIR / "k717_reconstruction_diff.md")

    return output


def generate_diff_report(orig, recon, out_path):
    """Generate diff markdown."""
    lines = [
        "# K717 Reconstruction Diff Report",
        "",
        "Comparison: `k717_results.json` (original) vs `k717_results_reconstructed.json` (reconstructed)",
        "",
        "## IMPORTANT STRUCTURAL NOTE",
        "",
        "k717_results.json contains a **multi-strategy VT scorecard** (14 strategies including",
        "slow_vt, risk_parity, taiwan_spy_momentum, etc.) rather than the NSI regression",
        "described in Section 3 of main_v2.tex. This suggests K717 was a strategy comparison",
        "experiment used for Section 6 (Economic Implications / VT Strategy Design), not the",
        "NSI regression (which is produced in K716).",
        "",
        "The reconstruction covers only 4 core strategies from the original 14. Full reconstruction",
        "of all 14 strategies (taiwan_spy_momentum, tz_tw_jp_5050, vix_cond_leverage, etc.) would",
        "require additional data sources and strategy specifications beyond what main_v2.tex provides.",
        "",
        "**Reconstruction status: APPROXIMATE — partial strategy coverage**",
        "",
        "## Strategy Coverage",
        "",
        "| Strategy | In Original | In Reconstructed | Notes |",
        "|----------|-------------|------------------|-------|",
    ]

    orig_keys = set(orig.keys())
    recon_keys = set(recon.keys())

    for k in sorted(orig_keys):
        in_recon = "YES" if k in recon_keys else "NO"
        lines.append(f"| {k} | YES | {in_recon} | {'Reconstructed' if in_recon == 'YES' else 'Missing — needs full strategy spec'} |")

    lines += [
        "",
        "## Metric Comparison (Available Strategies)",
        "",
        "| Strategy | Metric | Original | Reconstructed | Diff |",
        "|----------|--------|----------|---------------|------|",
    ]

    common_keys = orig_keys & recon_keys
    metrics = ["cagr", "sharpe", "mdd", "n_days"]
    for k in sorted(common_keys):
        for m in metrics:
            o_val = orig[k].get(m, "MISSING")
            r_val = recon[k].get(m, "MISSING")
            if isinstance(o_val, (int, float)) and isinstance(r_val, (int, float)):
                diff = round(abs(o_val - r_val), 3)
                lines.append(f"| {k} | {m} | {o_val} | {r_val} | {diff} |")

    lines += [
        "",
        "## Overall Status",
        "",
        "**Reconstruction result: APPROXIMATE**",
        "",
        "- Only 4 of 14 strategies reconstructed in this script",
        "- Strategies with Taiwan data (0050.TW) or specialized overlays (vix_cond_leverage,",
        "  taiwan_hybrid_leverage, piecewise_conservative, adaptive_tier) require full spec",
        "- Metric values may diverge due to exact date range differences",
        "- Paper risk: K717 strategies appear in Section 6 as supporting evidence only;",
        "  core claims (SAR, NSI regression) are in K716/K718/K721. Low errata risk.",
    ]

    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Diff report: {out_path}")


if __name__ == "__main__":
    main()
