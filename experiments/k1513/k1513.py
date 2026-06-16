"""K1513 — Commodity short-term momentum-reversal coexistence under vol regime.

Hypothesis (JFEM/SSRN 2025-26 strand):
    At the same short horizon (1-4 weeks), momentum and reversal coexist in
    commodity ETFs but become separable by volatility regime:
      H1: high-vol regime -> reversal dominates (Sharpe_reversal > Sharpe_momentum)
      H0: no regime-separation (returns to long-momentum vs long-reversal
          are statistically indistinguishable conditional on vol regime).

Design notes:
  - Universe: GLD, SLV, USO, UNG, CPER, PDBC (broad commodity ETFs via yfinance).
  - Two sampling frequencies: weekly (W-FRI close) and monthly (M close).
  - Past-N-bar return as signal: N in {1, 2, 4} (interpreted as weeks; for
    monthly grid, N=1 month/2 months/4 months — analogous "short-term" range).
  - At each rebalance date t we use information up to t-1 (shift(1)) to compute
    signal sign; trade on bar return r_t. This is the canonical lookahead-safe
    convention.
  - Strategies (per asset, per N, per freq):
        momentum: position_t = sign(past_N_return_{t-1})
        reversal: position_t = -sign(past_N_return_{t-1})
  - Regime split: trailing 26-bar (weekly) / 6-bar (monthly) realized vol
    annualized; classify each rebalance date by whether trailing vol >= rolling
    median. Vol used at t is computed on returns up to t-1 (shift(1)).
  - Statistical test: Diebold-Mariano (HAC, Newey-West, lag = round(T^{1/3}))
    on per-period returns of momentum vs reversal *within each regime*.
  - Multiple testing: report Bonferroni-corrected p across 36 cells
    (6 ETFs * 3 N * 2 freq) — note this is per-regime, so 72 tests total.
  - Costs: simple 1bp turnover proxy applied to long/short flips. (Sensitivity
    rather than centerpiece; the hypothesis is regime-conditional sign, not
    profitability.)

Lookahead protections (audited):
  - Signal uses .shift(1) on past_N_return before sign.
  - Vol regime uses .shift(1) on trailing vol before regime classification.
  - Bar returns are computed at t; positions established at t use only t-1 info.

Seed: 42 for all bootstrap routines (DM uses analytical HAC; bootstrap reserved
for diagnostic CI in Patton-style robustness).

Outputs:
  experiments/k1513/k1513_results.json — full numerical grid.
  experiments/k1513/k1513_regime_split.png — visualization of regime split.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
TICKERS = ["GLD", "SLV", "USO", "UNG", "CPER", "PDBC"]
START = "2010-01-01"
END = "2026-06-15"
NS = [1, 2, 4]  # in bars (weeks for weekly freq, months for monthly)
COST_BPS = 1.0  # round-trip cost approximation, bps per signed flip


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def download_prices(tickers, start, end) -> pd.DataFrame:
    """Download adjusted close prices for the universe.

    Falls back to whatever subset is available; logs missing tickers.
    """
    print(f"[data] downloading {tickers} {start} -> {end}")
    df = yf.download(
        tickers,
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
    )
    # yfinance returns MultiIndex columns when multiple tickers; pick Close
    closes = {}
    for t in tickers:
        try:
            if isinstance(df.columns, pd.MultiIndex):
                series = df[t]["Close"]
            else:
                series = df["Close"]
            series = series.dropna()
            if len(series) > 250:
                closes[t] = series
            else:
                print(f"[data] WARN {t} only {len(series)} obs; dropping")
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[data] WARN cannot load {t}: {exc}")
    panel = pd.DataFrame(closes).sort_index()
    panel.index = pd.to_datetime(panel.index)
    return panel


# ---------------------------------------------------------------------------
# Resampling & signal construction
# ---------------------------------------------------------------------------
def resample(prices: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample to W-FRI or M end-of-period last price."""
    rule = "W-FRI" if freq == "weekly" else "ME"
    return prices.resample(rule).last().dropna(how="all")


def trailing_vol_regime(returns: pd.Series, window: int) -> pd.Series:
    """High/low vol regime classification using trailing window std.

    Uses .shift(1) so that the regime label at t depends only on info up to t-1.
    Comparison threshold is the *expanding* median up to t-1 (no future info).
    """
    rolling = returns.rolling(window).std()
    rolling_lag = rolling.shift(1)
    # Expanding median of past-only rolling vol
    expanding_med = rolling_lag.expanding(min_periods=window * 2).median()
    regime = (rolling_lag >= expanding_med).astype("float")
    regime[expanding_med.isna()] = np.nan
    return regime  # 1.0 = high vol, 0.0 = low vol


def build_signals_and_returns(
    prices: pd.Series, freq: str, n: int
) -> pd.DataFrame:
    """Return a frame with columns:
        ret_t            bar return at t
        mom_signal       +1/-1/0 based on sign of past_n_return at t-1
        rev_signal       -mom_signal
        regime_high      1 if high vol regime at t (uses info up to t-1)
        mom_ret          mom_signal * ret_t  (PnL of momentum)
        rev_ret          rev_signal * ret_t  (PnL of reversal)
    """
    ret = prices.pct_change().dropna()
    if freq == "weekly":
        vol_window = 26
    else:
        vol_window = 6

    past_n = prices.pct_change(n)
    mom_sig_raw = np.sign(past_n.shift(1))  # critical .shift(1)
    rev_sig_raw = -mom_sig_raw

    regime = trailing_vol_regime(ret, vol_window)

    # Costs: 1bp per flip
    cost_unit = COST_BPS / 10_000.0
    mom_flip = mom_sig_raw.diff().abs().fillna(0.0)
    rev_flip = rev_sig_raw.diff().abs().fillna(0.0)

    mom_ret = mom_sig_raw * ret - cost_unit * mom_flip
    rev_ret = rev_sig_raw * ret - cost_unit * rev_flip

    frame = pd.DataFrame(
        {
            "ret": ret,
            "mom_signal": mom_sig_raw,
            "rev_signal": rev_sig_raw,
            "regime_high": regime,
            "mom_ret": mom_ret,
            "rev_ret": rev_ret,
        }
    ).dropna()
    return frame


# ---------------------------------------------------------------------------
# Statistics: Sharpe, DM with HAC
# ---------------------------------------------------------------------------
def annualization_factor(freq: str) -> float:
    return 52.0 if freq == "weekly" else 12.0


def sharpe(returns: pd.Series, freq: str) -> float:
    if len(returns) < 5 or returns.std() == 0:
        return float("nan")
    return float(returns.mean() / returns.std() * math.sqrt(annualization_factor(freq)))


def max_drawdown(returns: pd.Series) -> float:
    if len(returns) < 2:
        return float("nan")
    eq = (1 + returns).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    return float(dd)


def newey_west_se(x: np.ndarray, lag: int | None = None) -> float:
    """Newey-West HAC standard error for the sample mean of x."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    T = len(x)
    if T < 5:
        return float("nan")
    if lag is None:
        lag = max(1, int(round(T ** (1.0 / 3.0))))
    xbar = x.mean()
    dev = x - xbar
    gamma0 = (dev @ dev) / T
    var = gamma0
    for k in range(1, lag + 1):
        cov = (dev[k:] @ dev[:-k]) / T
        w = 1.0 - k / (lag + 1.0)
        var += 2.0 * w * cov
    var = max(var, 1e-18)
    return float(math.sqrt(var / T))


def dm_test(diff: pd.Series) -> tuple[float, float]:
    """DM test on a loss/return-differential series.

    Returns (t_stat, two-sided p-value approximated via standard normal).
    """
    d = diff.dropna().values
    if len(d) < 10:
        return float("nan"), float("nan")
    se = newey_west_se(d)
    if not math.isfinite(se) or se == 0:
        return float("nan"), float("nan")
    t = float(d.mean() / se)
    # two-sided p via normal approx
    from math import erf

    p = 2.0 * (1.0 - 0.5 * (1.0 + erf(abs(t) / math.sqrt(2.0))))
    return t, float(p)


# ---------------------------------------------------------------------------
# Per-cell evaluation
# ---------------------------------------------------------------------------
@dataclass
class CellResult:
    ticker: str
    freq: str
    n: int
    n_obs_total: int
    n_obs_high: int
    n_obs_low: int
    sharpe_mom_full: float
    sharpe_rev_full: float
    sharpe_mom_high: float
    sharpe_rev_high: float
    sharpe_mom_low: float
    sharpe_rev_low: float
    mdd_mom_full: float
    mdd_rev_full: float
    dm_t_full: float
    dm_p_full: float
    dm_t_high: float
    dm_p_high: float
    dm_t_low: float
    dm_p_low: float
    mean_mom_high: float
    mean_rev_high: float
    mean_mom_low: float
    mean_rev_low: float


def evaluate_cell(
    prices: pd.Series, ticker: str, freq: str, n: int
) -> CellResult | None:
    frame = build_signals_and_returns(prices, freq, n)
    if len(frame) < 80:
        return None

    high_mask = frame["regime_high"] == 1.0
    low_mask = frame["regime_high"] == 0.0

    diff_full = frame["rev_ret"] - frame["mom_ret"]
    diff_high = diff_full[high_mask]
    diff_low = diff_full[low_mask]

    t_full, p_full = dm_test(diff_full)
    t_high, p_high = dm_test(diff_high)
    t_low, p_low = dm_test(diff_low)

    return CellResult(
        ticker=ticker,
        freq=freq,
        n=n,
        n_obs_total=int(len(frame)),
        n_obs_high=int(high_mask.sum()),
        n_obs_low=int(low_mask.sum()),
        sharpe_mom_full=sharpe(frame["mom_ret"], freq),
        sharpe_rev_full=sharpe(frame["rev_ret"], freq),
        sharpe_mom_high=sharpe(frame.loc[high_mask, "mom_ret"], freq),
        sharpe_rev_high=sharpe(frame.loc[high_mask, "rev_ret"], freq),
        sharpe_mom_low=sharpe(frame.loc[low_mask, "mom_ret"], freq),
        sharpe_rev_low=sharpe(frame.loc[low_mask, "rev_ret"], freq),
        mdd_mom_full=max_drawdown(frame["mom_ret"]),
        mdd_rev_full=max_drawdown(frame["rev_ret"]),
        dm_t_full=t_full,
        dm_p_full=p_full,
        dm_t_high=t_high,
        dm_p_high=p_high,
        dm_t_low=t_low,
        dm_p_low=p_low,
        mean_mom_high=float(frame.loc[high_mask, "mom_ret"].mean()),
        mean_rev_high=float(frame.loc[high_mask, "rev_ret"].mean()),
        mean_mom_low=float(frame.loc[low_mask, "mom_ret"].mean()),
        mean_rev_low=float(frame.loc[low_mask, "rev_ret"].mean()),
    )


# ---------------------------------------------------------------------------
# Aggregate verdict
# ---------------------------------------------------------------------------
def classify_verdict(cells: list[CellResult]) -> dict:
    """Compute aggregate metrics and verdict.

    H1 (regime separation) supported if a significant fraction of cells show:
      - high-vol regime: mean_rev > mean_mom  AND DM p_high < alpha
      - low-vol regime:  mean_mom > mean_rev  AND DM p_low  < alpha
    With Bonferroni correction across the regime-conditional grid.
    """
    n_cells = len(cells)
    if n_cells == 0:
        return {"verdict": "FAIL", "reason": "no cells evaluated"}

    # Bonferroni across n_cells *per regime* (separate families) is conservative.
    alpha_raw = 0.05
    alpha_bonf = alpha_raw / n_cells

    high_supports = []
    low_supports = []
    for c in cells:
        if math.isfinite(c.dm_p_high) and c.dm_p_high < alpha_raw and c.mean_rev_high > c.mean_mom_high:
            high_supports.append(c)
        if math.isfinite(c.dm_p_low) and c.dm_p_low < alpha_raw and c.mean_mom_low > c.mean_rev_low:
            low_supports.append(c)

    high_supports_bonf = [c for c in high_supports if c.dm_p_high < alpha_bonf]
    low_supports_bonf = [c for c in low_supports if c.dm_p_low < alpha_bonf]

    # Also count any-regime sign agreement (descriptive)
    sign_consistent = sum(
        1
        for c in cells
        if c.mean_rev_high > c.mean_mom_high and c.mean_mom_low > c.mean_rev_low
    )

    meta = {
        "n_cells": n_cells,
        "alpha_raw": alpha_raw,
        "alpha_bonferroni": alpha_bonf,
        "n_high_regime_reversal_sig_raw": len(high_supports),
        "n_low_regime_momentum_sig_raw": len(low_supports),
        "n_high_regime_reversal_sig_bonf": len(high_supports_bonf),
        "n_low_regime_momentum_sig_bonf": len(low_supports_bonf),
        "n_sign_consistent_cells": sign_consistent,
    }

    # Verdict logic
    if len(high_supports_bonf) + len(low_supports_bonf) >= max(2, n_cells // 6):
        verdict = "PASS"
        reason = "Bonferroni-significant regime separation in multiple cells"
    elif len(high_supports) + len(low_supports) >= max(2, n_cells // 4):
        verdict = "CONDITIONAL_PASS"
        reason = "raw-significant regime separation but fragile after Bonferroni"
    elif sign_consistent >= n_cells // 3:
        verdict = "NULL"
        reason = "sign-consistent direction but no statistical significance"
    else:
        verdict = "NULL"
        reason = "no consistent regime separation"

    meta["verdict"] = verdict
    meta["reason"] = reason
    return meta


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
def plot_regime_split(cells: list[CellResult], path: Path) -> None:
    # For each freq plot mean returns (mom vs rev) by regime, panel per N.
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), sharey=False)
    for row, freq in enumerate(["weekly", "monthly"]):
        for col, n in enumerate(NS):
            ax = axes[row, col]
            subset = [c for c in cells if c.freq == freq and c.n == n]
            tickers = [c.ticker for c in subset]
            x = np.arange(len(tickers))
            width = 0.2
            ax.bar(x - 1.5 * width, [c.mean_mom_high for c in subset], width, label="mom|high-vol", color="#d62728")
            ax.bar(x - 0.5 * width, [c.mean_rev_high for c in subset], width, label="rev|high-vol", color="#ff9896")
            ax.bar(x + 0.5 * width, [c.mean_mom_low for c in subset], width, label="mom|low-vol", color="#1f77b4")
            ax.bar(x + 1.5 * width, [c.mean_rev_low for c in subset], width, label="rev|low-vol", color="#aec7e8")
            ax.axhline(0, color="black", lw=0.5)
            ax.set_xticks(x)
            ax.set_xticklabels(tickers, rotation=45)
            ax.set_title(f"{freq} N={n}")
            if row == 0 and col == 2:
                ax.legend(loc="upper right", fontsize=7)
    fig.suptitle("K1513 — Momentum vs Reversal mean per-period return by vol regime")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    panel = download_prices(TICKERS, START, END)
    print(f"[data] loaded panel shape={panel.shape}, tickers={list(panel.columns)}")

    cells: list[CellResult] = []
    for freq in ["weekly", "monthly"]:
        re = resample(panel, freq)
        print(f"[run] {freq} resampled shape={re.shape}")
        for ticker in re.columns:
            prices = re[ticker].dropna()
            for n in NS:
                cell = evaluate_cell(prices, ticker, freq, n)
                if cell is not None:
                    cells.append(cell)
                    print(
                        f"  cell {ticker:>5s} {freq} N={n:>2d} "
                        f"sharpe_mom={cell.sharpe_mom_full:+.2f} "
                        f"sharpe_rev={cell.sharpe_rev_full:+.2f} "
                        f"DM_high t={cell.dm_t_high:+.2f} "
                        f"DM_low t={cell.dm_t_low:+.2f}"
                    )

    summary = classify_verdict(cells)
    output = {
        "experiment_id": "K1513",
        "seed": SEED,
        "universe": TICKERS,
        "loaded_tickers": [t for t in TICKERS if t in panel.columns],
        "period_start": START,
        "period_end": END,
        "n_bars": [int(n) for n in NS],
        "cost_bps_per_flip": COST_BPS,
        "cells": [asdict(c) for c in cells],
        "summary": summary,
    }

    out_json = OUT_DIR / "k1513_results.json"
    out_json.write_text(json.dumps(output, indent=2, default=float))
    print(f"[done] wrote {out_json}")

    out_png = OUT_DIR / "k1513_regime_split.png"
    plot_regime_split(cells, out_png)
    print(f"[done] wrote {out_png}")

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
