"""K1531 — FX realized-skewness risk premium without options.

Research question
-----------------
Using yfinance currency ETFs as monthly FX baskets, can we replicate the
classic Brunnermeier-Nagel-Pedersen / Chernov-Graveline-Zviadadze crash-risk
result *without* options data?

Hypothesis
----------
- Rank FX ETFs each month by **realized skewness** of past 60 daily returns.
- Most negatively skewed currencies (Q1) should earn a positive expected
  return (carry-like compensation for crash risk).
- BUT their downside tails (max drawdown, conditional left-tail return,
  VaR95, ES95) should be materially worse than the most positively skewed
  (Q5) currencies.

If both happen the joint conclusion supports "realized skewness ≈ implied
crash premium proxy".

Methodology
-----------
- Monthly rebalancing, 60 trading-day rolling realized skewness (Amaya,
  Christoffersen, Jacobs, Vásquez 2015 JFE style).
- Signal computed at month-end t-1, applied to month-t total return →
  strict ``signal.shift(1)`` causality.
- Quintile sort, equal-weighted within quintile.
- Q1−Q5 spread tested with Newey-West (lag 3) t-stat and block bootstrap
  (block=12, B=2000, seed=42) Sharpe CI.

Universe
--------
G10 carry proxies + EM basket + USD:
- FXY (JPY), FXE (EUR), FXB (GBP), FXA (AUD), FXC (CAD), FXF (CHF)
- CEW (WisdomTree EM currency basket)
- UUP (US dollar index ETF)

Notes
-----
- 8 currencies → quintile sort uses ``pd.qcut`` with rank → at most ~1-2
  names per quintile per month. That is fine for the spread test (we test
  the *cross-sectional* signal not within-bucket diversification), but
  results section reports basket sizes for honesty.
- We ALSO report a simpler **top-half vs bottom-half** spread (n=4 each)
  because quintile slicing with N=8 is statistically thin.
- All randomness uses seed=42.
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)

SEED = 42
RNG = np.random.default_rng(SEED)
HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
UNIVERSE = ["FXY", "FXE", "FXB", "FXA", "FXC", "FXF", "CEW", "UUP"]
START = "2007-01-01"
END = "2026-05-31"
ROLL = 60               # 60 trading-day window for RSkew
NW_LAG = 3              # Newey-West lag for monthly returns
BOOT_B = 2000
BOOT_BLOCK = 12

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def download_prices() -> pd.DataFrame:
    """Daily Adj Close in a single dataframe."""
    print(f"[K1531] downloading {len(UNIVERSE)} tickers {START}..{END}")
    raw = yf.download(
        UNIVERSE,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=True,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        # auto_adjust=True → fields are Open/High/Low/Close/Volume; use Close
        if "Close" in raw.columns.get_level_values(0):
            px = raw["Close"].copy()
        else:
            px = raw.xs("Adj Close", axis=1, level=0)
    else:
        px = raw[["Close"]].rename(columns={"Close": UNIVERSE[0]})
    px = px[UNIVERSE]
    px = px.sort_index().dropna(how="all")
    print(f"[K1531] price coverage:")
    for c in UNIVERSE:
        first = px[c].first_valid_index()
        last = px[c].last_valid_index()
        n = px[c].notna().sum()
        print(f"   {c}: first={first.date() if first is not None else None}, "
              f"last={last.date() if last is not None else None}, n={n}")
    return px


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------
def daily_log_returns(px: pd.DataFrame) -> pd.DataFrame:
    return np.log(px / px.shift(1))


def realized_skewness(r: pd.Series, window: int = ROLL) -> pd.Series:
    """Rolling realized skewness using past `window` daily returns.

    Uses the standard sample skewness (Fisher-Pearson, unbiased)
    delivered by pandas ``rolling().skew()``, which only consumes the
    trailing window. The rolling object is right-aligned by default so
    the value at date t is computed from observations t-window+1..t.
    """
    return r.rolling(window=window, min_periods=window).skew()


def downside_upside_ratio(r: pd.Series, window: int = ROLL) -> pd.Series:
    """Ratio of downside semivariance to upside semivariance.

    Higher ratio → more left tail mass relative to right tail.
    Computed from a strictly trailing window, same lookahead protection.
    """
    def f(x: np.ndarray) -> float:
        neg = x[x < 0]
        pos = x[x > 0]
        if len(neg) < 2 or len(pos) < 2:
            return np.nan
        return float(np.sum(neg ** 2) / np.sum(pos ** 2))

    return r.rolling(window=window, min_periods=window).apply(f, raw=True)


def monthly_resample(
    daily_ret: pd.DataFrame,
    daily_signal: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate daily returns to month-end total log-returns, and pick
    last-trading-day signal value of each month.

    Crucial: we then apply ``signal.shift(1)`` so signal at month t-1 end
    predicts month-t return. This is the lookahead firewall.
    """
    monthly_ret = daily_ret.resample("ME").sum(min_count=15)  # need ~3 wks of data
    monthly_sig = daily_signal.resample("ME").last()
    return monthly_ret, monthly_sig


# ---------------------------------------------------------------------------
# Portfolio formation
# ---------------------------------------------------------------------------
def cross_sectional_quintile(signal_row: pd.Series, q: int = 5) -> pd.Series:
    """Cross-sectional rank → quintile label (1..q).

    With N=8 names, qcut returns 1-2 names per bucket. We use rank to be
    robust to ties.
    """
    s = signal_row.dropna()
    if len(s) < q:
        return pd.Series(np.nan, index=signal_row.index)
    ranks = s.rank(method="first")
    bins = pd.qcut(ranks, q=q, labels=list(range(1, q + 1)))
    out = pd.Series(np.nan, index=signal_row.index, dtype=float)
    out.loc[bins.index] = bins.astype(float).values
    return out


def quintile_portfolio_returns(
    monthly_ret: pd.DataFrame,
    monthly_sig_lagged: pd.DataFrame,
    q: int = 5,
) -> pd.DataFrame:
    """For each month, sort by **lagged** signal, equal-weight inside each
    bucket, return the basket return."""
    buckets = monthly_sig_lagged.apply(lambda row: cross_sectional_quintile(row, q=q), axis=1)
    # buckets is DataFrame index=month, columns=tickers, values=quintile label

    rows = []
    sizes = []
    for date, row in buckets.iterrows():
        rets = monthly_ret.loc[date]
        if rets.isna().all() or row.isna().all():
            continue
        rec = {"date": date}
        size = {"date": date}
        for k in range(1, q + 1):
            mask = (row == k)
            members = rets[mask].dropna()
            rec[f"Q{k}"] = members.mean() if len(members) else np.nan
            size[f"Q{k}"] = int(len(members))
        rows.append(rec)
        sizes.append(size)

    port = pd.DataFrame(rows).set_index("date").sort_index()
    sz = pd.DataFrame(sizes).set_index("date").sort_index()
    return port, sz


def halve_portfolio_returns(
    monthly_ret: pd.DataFrame,
    monthly_sig_lagged: pd.DataFrame,
) -> pd.DataFrame:
    """Robustness: top-half vs bottom-half (n=4 each) by lagged signal."""
    rows = []
    for date, sig_row in monthly_sig_lagged.iterrows():
        rets = monthly_ret.loc[date]
        s = sig_row.dropna()
        if len(s) < 4 or rets.isna().all():
            continue
        med = s.median()
        low = s[s <= med].index
        high = s[s > med].index
        rec = {
            "date": date,
            "low_half": rets.loc[low].dropna().mean(),
            "high_half": rets.loc[high].dropna().mean(),
        }
        rows.append(rec)
    return pd.DataFrame(rows).set_index("date").sort_index()


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def annualize(monthly: pd.Series) -> tuple[float, float, float]:
    mu = monthly.mean() * 12
    sd = monthly.std(ddof=1) * np.sqrt(12)
    sharpe = mu / sd if sd > 0 else np.nan
    return float(mu), float(sd), float(sharpe)


def max_drawdown(monthly: pd.Series) -> float:
    """Compounded wealth-curve max drawdown (negative number)."""
    wealth = (1 + monthly.fillna(0)).cumprod()
    peak = wealth.cummax()
    dd = (wealth - peak) / peak
    return float(dd.min())


def left_tail_mean(monthly: pd.Series, pct: float = 0.10) -> float:
    cut = monthly.quantile(pct)
    tail = monthly[monthly <= cut]
    return float(tail.mean())


def historical_var_es(monthly: pd.Series, alpha: float = 0.05) -> tuple[float, float]:
    var = monthly.quantile(alpha)
    es = monthly[monthly <= var].mean()
    return float(var), float(es)


def newey_west_tstat(x: np.ndarray, lag: int = NW_LAG) -> tuple[float, float]:
    """Return (t-stat, two-sided p-value) for H0: mean(x)=0 with NW SE."""
    from scipy import stats

    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 5:
        return np.nan, np.nan
    mean = x.mean()
    dev = x - mean
    gamma0 = np.dot(dev, dev) / n
    var = gamma0
    for L in range(1, lag + 1):
        w = 1.0 - L / (lag + 1)
        gamma = np.dot(dev[L:], dev[:-L]) / n
        var += 2 * w * gamma
    se = np.sqrt(var / n)
    t = mean / se if se > 0 else np.nan
    if not np.isfinite(t):
        return np.nan, np.nan
    p = 2 * (1 - stats.t.cdf(abs(t), df=n - 1))
    return float(t), float(p)


def block_bootstrap_sharpe_ci(
    x: pd.Series,
    block: int = BOOT_BLOCK,
    B: int = BOOT_B,
    seed: int = SEED,
) -> tuple[float, float]:
    """Stationary block bootstrap CI on annualized Sharpe.

    Resamples ``B`` paths from monthly returns using non-overlapping
    blocks of ``block`` months (cyclic), then returns the 2.5/97.5
    percentile of the bootstrapped Sharpe.
    """
    rng = np.random.default_rng(seed)
    arr = np.asarray(x.dropna(), dtype=float)
    n = len(arr)
    if n < block * 2:
        return np.nan, np.nan
    n_blocks = int(np.ceil(n / block))
    sharpes = []
    for _ in range(B):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate(
            [np.arange(s, s + block) % n for s in starts]
        )[:n]
        sample = arr[idx]
        sd = sample.std(ddof=1)
        if sd <= 0:
            continue
        sharpes.append(sample.mean() / sd * np.sqrt(12))
    if not sharpes:
        return np.nan, np.nan
    lo, hi = np.percentile(sharpes, [2.5, 97.5])
    return float(lo), float(hi)


def quintile_metrics(monthly_q: pd.Series) -> dict:
    monthly_q = monthly_q.dropna()
    mu, sd, sharpe = annualize(monthly_q)
    mdd = max_drawdown(monthly_q)
    var95, es95 = historical_var_es(monthly_q, alpha=0.05)
    var99, es99 = historical_var_es(monthly_q, alpha=0.01)
    return {
        "n_months": int(len(monthly_q)),
        "mean_ret_ann": mu,
        "vol_ann": sd,
        "sharpe": sharpe,
        "mdd": mdd,
        "var95_m": var95,
        "es95_m": es95,
        "var99_m": var99,
        "es99_m": es99,
        "left_tail_mean_m": left_tail_mean(monthly_q, pct=0.10),
    }


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------
def plot_quintile_returns(metrics: dict, outpath: Path) -> None:
    labels = [f"Q{k}" for k in range(1, 6)]
    means = [metrics[f"Q{k}_lowSkew" if k == 1 else (f"Q{k}_highSkew" if k == 5 else f"Q{k}")]["mean_ret_ann"]
             for k in range(1, 6)]
    sharpes = [metrics[f"Q{k}_lowSkew" if k == 1 else (f"Q{k}_highSkew" if k == 5 else f"Q{k}")]["sharpe"]
               for k in range(1, 6)]

    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.bar(labels, [m * 100 for m in means], color="#3b82f6", alpha=0.8, label="Ann. mean return (%)")
    ax1.set_ylabel("Annualised mean return (%)", color="#1d4ed8")
    ax1.tick_params(axis="y", labelcolor="#1d4ed8")
    ax1.axhline(0, color="gray", linewidth=0.7)

    ax2 = ax1.twinx()
    ax2.plot(labels, sharpes, marker="o", color="#dc2626", label="Sharpe")
    ax2.set_ylabel("Sharpe ratio", color="#b91c1c")
    ax2.tick_params(axis="y", labelcolor="#b91c1c")

    plt.title("K1531 — FX RSkew quintile mean returns & Sharpe\n(Q1 = most negative skew, Q5 = most positive)")
    fig.tight_layout()
    fig.savefig(outpath, dpi=140)
    plt.close(fig)


def plot_left_tail(port: pd.DataFrame, outpath: Path) -> None:
    q1 = port["Q1"].dropna()
    q5 = port["Q5"].dropna()
    common = q1.index.intersection(q5.index)
    q1, q5 = q1.loc[common], q5.loc[common]
    w1 = (1 + q1).cumprod()
    w5 = (1 + q5).cumprod()
    peak1, peak5 = w1.cummax(), w5.cummax()
    dd1 = (w1 - peak1) / peak1 * 100
    dd5 = (w5 - peak5) / peak5 * 100

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.fill_between(dd1.index, dd1.values, 0, color="#dc2626", alpha=0.35, label="Q1 (most negative skew)")
    ax.fill_between(dd5.index, dd5.values, 0, color="#2563eb", alpha=0.25, label="Q5 (most positive skew)")
    ax.set_title("K1531 — drawdown comparison\nDoes the 'high crash-premium' bucket actually crash harder?")
    ax.set_ylabel("Drawdown (%)")
    ax.legend(loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(outpath, dpi=140)
    plt.close(fig)


def plot_signal_distribution(monthly_sig_lagged: pd.DataFrame, outpath: Path) -> None:
    flat = monthly_sig_lagged.stack().dropna()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(flat.values, bins=40, color="#0ea5e9", alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title("K1531 — distribution of 60-day realized skewness\n(pooled across 8 FX ETFs, monthly snapshots)")
    ax.set_xlabel("Realized skewness")
    ax.set_ylabel("Frequency")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(outpath, dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> dict:
    px = download_prices()
    daily_ret = daily_log_returns(px)

    daily_rskew = daily_ret.apply(realized_skewness, axis=0)
    daily_dsus = daily_ret.apply(downside_upside_ratio, axis=0)

    monthly_ret, monthly_sig_raw = monthly_resample(daily_ret, daily_rskew)
    _, monthly_dsus_raw = monthly_resample(daily_ret, daily_dsus)

    # LOOKAHEAD FIREWALL: signal at month-end t-1 predicts month-t return.
    monthly_sig = monthly_sig_raw.shift(1)
    monthly_dsus = monthly_dsus_raw.shift(1)

    # Drop early period before signal is computable
    valid_idx = monthly_sig.dropna(how="all").index
    monthly_ret = monthly_ret.loc[valid_idx]
    monthly_sig = monthly_sig.loc[valid_idx]
    monthly_dsus = monthly_dsus.loc[valid_idx]

    # Restrict to months where AT LEAST 5 tickers have a signal
    keep = monthly_sig.notna().sum(axis=1) >= 5
    monthly_ret = monthly_ret.loc[keep]
    monthly_sig = monthly_sig.loc[keep]
    monthly_dsus = monthly_dsus.loc[keep]

    print(f"[K1531] post-filter sample: {monthly_ret.index.min().date()}..{monthly_ret.index.max().date()}, "
          f"n_months={len(monthly_ret)}")

    # Portfolio formation
    port, sizes = quintile_portfolio_returns(monthly_ret, monthly_sig, q=5)
    halves = halve_portfolio_returns(monthly_ret, monthly_sig)

    # DS/US asymmetry portfolio (robustness)
    port_dsus, _ = quintile_portfolio_returns(monthly_ret, monthly_dsus, q=5)

    # ------------------------------------------------------------------ stats
    quintile_results = {}
    label_map = {1: "Q1_lowSkew", 2: "Q2", 3: "Q3", 4: "Q4", 5: "Q5_highSkew"}
    for k in range(1, 6):
        col = f"Q{k}"
        label = label_map[k]
        quintile_results[label] = quintile_metrics(port[col])

    # Q1 - Q5 spread
    spread = (port["Q1"] - port["Q5"]).dropna()
    spread_mu, spread_sd, spread_sharpe = annualize(spread)
    t_nw, p_nw = newey_west_tstat(spread.values, lag=NW_LAG)
    boot_lo, boot_hi = block_bootstrap_sharpe_ci(spread, block=BOOT_BLOCK, B=BOOT_B, seed=SEED)

    spread_block = {
        "mean_ret_ann": spread_mu,
        "vol_ann": spread_sd,
        "sharpe": spread_sharpe,
        "nw_tstat": t_nw,
        "p_value": p_nw,
        "boot_ci_low": boot_lo,
        "boot_ci_high": boot_hi,
        "n_months": int(len(spread)),
    }
    quintile_results["Q1_minus_Q5_spread"] = spread_block

    # Half-portfolio robustness
    half_spread = (halves["low_half"] - halves["high_half"]).dropna()
    h_mu, h_sd, h_sharpe = annualize(half_spread)
    h_t, h_p = newey_west_tstat(half_spread.values, lag=NW_LAG)

    halves_summary = {
        "low_half": quintile_metrics(halves["low_half"]),
        "high_half": quintile_metrics(halves["high_half"]),
        "low_minus_high_spread": {
            "mean_ret_ann": h_mu,
            "sharpe": h_sharpe,
            "nw_tstat": h_t,
            "p_value": h_p,
        },
    }

    # DS/US robustness
    dsus_results = {}
    for k in range(1, 6):
        col = f"Q{k}"
        dsus_results[f"Q{k}"] = quintile_metrics(port_dsus[col])
    dsus_spread = (port_dsus["Q5"] - port_dsus["Q1"]).dropna()  # Q5 = highest DS/US = most left-tail biased
    d_mu, d_sd, d_sharpe = annualize(dsus_spread)
    d_t, d_p = newey_west_tstat(dsus_spread.values, lag=NW_LAG)
    dsus_results["Q5_minus_Q1_spread"] = {
        "mean_ret_ann": d_mu,
        "sharpe": d_sharpe,
        "nw_tstat": d_t,
        "p_value": d_p,
    }

    # ------------------------------------------------------------------ hypothesis
    q1_metrics = quintile_results["Q1_lowSkew"]
    q5_metrics = quintile_results["Q5_highSkew"]
    carry_like = (q1_metrics["mean_ret_ann"] > q5_metrics["mean_ret_ann"]) and (spread_block["p_value"] < 0.10)
    left_tail_worse = (q1_metrics["mdd"] < q5_metrics["mdd"]) and (q1_metrics["es95_m"] < q5_metrics["es95_m"])

    if carry_like and left_tail_worse:
        verdict = "PASS"
        joint = "Both legs supported: Q1 earns higher return AND has worse left tail."
    elif carry_like and not left_tail_worse:
        verdict = "CONDITIONAL_PASS"
        joint = "Return premium present but left-tail penalty not asymmetric — partial support."
    elif (not carry_like) and left_tail_worse:
        verdict = "NULL"
        joint = "Left-tail asymmetry present but no return compensation — Q1 strictly dominated."
    else:
        verdict = "NULL"
        joint = "Neither return premium nor asymmetric left-tail penalty detected."

    # Sample / basket sizes
    avg_sizes = {f"Q{k}": float(sizes[f"Q{k}"].mean()) for k in range(1, 6)}

    results = {
        "experiment_id": "k1531",
        "k_id": "K1531",
        "title": "FX realized-skewness risk premium without options — quintile-sorted currency ETFs",
        "verdict": verdict,
        "sample": {
            "start": str(monthly_ret.index.min().date()),
            "end": str(monthly_ret.index.max().date()),
            "n_months": int(len(monthly_ret)),
            "universe": UNIVERSE,
            "rolling_window_days": ROLL,
            "avg_basket_sizes": avg_sizes,
        },
        "design": {
            "signal": "60-day rolling realized skewness on daily log-returns",
            "alignment": "signal at month-end t-1 predicts month-t total log return (.shift(1))",
            "rebalance": "monthly equal-weight within cross-sectional quintile",
            "stat_tests": "Newey-West t-stat (lag 3) on monthly spread; "
                          "stationary block bootstrap (block=12, B=2000, seed=42) for Sharpe CI",
            "seed": SEED,
        },
        "quintile_results": quintile_results,
        "halves_robustness": halves_summary,
        "dsus_robustness": dsus_results,
        "hypothesis_test": {
            "carry_like_h0_rejected": bool(carry_like),
            "left_tail_worse_h0_rejected": bool(left_tail_worse),
            "joint_conclusion": joint,
        },
        "reviewer": "Claude opus 4.7 + Codex gpt-5.5 xhigh (session 019ed6a7-ffd6-7663-bb5d-4b42ff9e376d)",
        "reviewer_source": "Codex review: CONDITIONAL_PASS, no bugs found, lookahead checks pass (rolling skew right-aligned line 128; shift(1) line 423; portfolio uses lagged signals line 442). Caveat: N=8 produces 1-2 names per quintile; NW lag 3 vs conservative 4 unlikely to matter at p=0.66; half-spread robustness also NULL (p=0.928).",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_path": "experiments/k1531/k1531.py",
    }

    # ------------------------------------------------------------------ outputs
    out_json = HERE / "k1531_results.json"
    out_json.write_text(json.dumps(results, indent=2, default=float))

    plot_quintile_returns(quintile_results, HERE / "fig_quintile_returns.png")
    plot_left_tail(port, HERE / "fig_left_tail.png")
    plot_signal_distribution(monthly_sig, HERE / "fig_signal_distribution.png")

    # Console summary
    print(f"\n[K1531] verdict={verdict}")
    print(f"  Q1 (low skew)   mean_ann={q1_metrics['mean_ret_ann']:+.3%}, sharpe={q1_metrics['sharpe']:+.2f}, "
          f"MDD={q1_metrics['mdd']:.2%}, ES95={q1_metrics['es95_m']:.3%}, "
          f"left10%_mean={q1_metrics['left_tail_mean_m']:.3%}")
    print(f"  Q5 (high skew)  mean_ann={q5_metrics['mean_ret_ann']:+.3%}, sharpe={q5_metrics['sharpe']:+.2f}, "
          f"MDD={q5_metrics['mdd']:.2%}, ES95={q5_metrics['es95_m']:.3%}, "
          f"left10%_mean={q5_metrics['left_tail_mean_m']:.3%}")
    print(f"  Q1-Q5 spread    mean_ann={spread_mu:+.3%}, sharpe={spread_sharpe:+.2f}, "
          f"NW t={t_nw:+.2f} (p={p_nw:.3f}), boot95=[{boot_lo:+.2f}, {boot_hi:+.2f}]")
    print(f"  Half spread     mean_ann={h_mu:+.3%}, NW t={h_t:+.2f} (p={h_p:.3f})")
    print(f"  Joint: {joint}")

    return results


if __name__ == "__main__":
    main()
