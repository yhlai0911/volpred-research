"""K1528: Cross-sectional sentiment-beta strategy using free proxies.

Research question
-----------------
Does firm-level sensitivity to market sentiment changes predict the
cross-section of future U.S. stock returns?

This is a free-proxy replication of the "emotion beta" idea in Hasan, Kumar
and Taffler (2025). Their market emotion dictionary is proprietary/not readily
replicable from this repo, so this experiment uses two public monthly proxies:

1. VIX optimism shock = -diff(log(VIX)); positive means fear falls.
2. UMCSENT change = monthly change in Michigan consumer sentiment.

Lookahead policy
----------------
- Rolling betas for month t are estimated using months [t-60, t-1] only.
- Portfolios sorted on beta at t hold month-t stock returns.
- The fixed large-cap universe is declared ex ante in this script. This is a
  survivorship-biased pilot, not a paper-grade CRSP replication.
- yfinance calls explicitly set auto_adjust=False and use Adj Close.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

from volpred.stats.model_evaluation import strategy_dm_test


K_ID = "K1528"
SEED = 42
START = "2004-01-01"
END = "2026-06-14"
ROLLING_WINDOW_MONTHS = 60
MIN_OBS_IN_WINDOW = 48
BOOTSTRAP_B = 1000
BOOTSTRAP_BLOCK = 6
HARVEY_T = 3.0

OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

# Fixed liquid U.S. large-cap universe. The fixed list avoids dynamic index
# membership lookahead but remains survivorship-biased; README/results disclose
# this explicitly.
TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "NVDA", "TSLA",
    "JPM", "JNJ", "V", "WMT", "PG", "MA", "HD", "BAC", "XOM", "CVX",
    "PFE", "KO", "MRK", "ABBV", "PEP", "COST", "CSCO", "ADBE", "NFLX",
    "CRM", "ORCL", "INTC", "AMD", "IBM", "MCD", "DIS", "NKE", "UNH",
    "T", "TMO", "ABT", "AVGO", "QCOM", "TXN", "AMGN", "LOW", "SBUX",
    "UPS", "CAT", "GS", "BA", "GE", "HON", "LMT",
]


@dataclass
class ProxyResult:
    proxy: str
    n_months: int
    n_stocks_median: int
    high_mean_ann: float
    low_mean_ann: float
    long_short_mean_ann: float
    long_short_vol_ann: float
    long_short_sharpe: float
    high_low_dm_t: float
    high_low_dm_p: float
    ls_vs_zero_dm_t: float
    ls_vs_zero_dm_p: float
    fmb_beta_mean_monthly: float
    fmb_beta_t_nw: float
    fmb_beta_p_nw: float
    fmb_beta_control_mkt_mean_monthly: float
    fmb_beta_control_mkt_t_nw: float
    fmb_beta_control_mkt_p_nw: float
    bootstrap_ci_low_ann: float
    bootstrap_ci_high_ann: float
    bootstrap_p_mean_le_zero: float
    harvey_pass: bool
    direction_pass: bool
    verdict: str


def _download_adj_close(tickers: list[str]) -> pd.DataFrame:
    data = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    if isinstance(data.columns, pd.MultiIndex):
        if "Adj Close" not in data.columns.get_level_values(0):
            raise RuntimeError("yfinance response missing Adj Close")
        px = data["Adj Close"].copy()
    else:
        px = data[["Adj Close"]].copy()
        px.columns = tickers
    px = px.dropna(axis=1, how="all")
    px.index = pd.to_datetime(px.index).tz_localize(None)
    return px


def _download_umcsent() -> pd.Series:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UMCSENT"
    df = pd.read_csv(url)
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    values = pd.to_numeric(df["UMCSENT"].replace(".", np.nan), errors="coerce")
    s = pd.Series(values.values, index=df["observation_date"], name="UMCSENT").dropna()
    return s.resample("ME").last()


def monthly_returns(adj_close: pd.DataFrame) -> pd.DataFrame:
    monthly_px = adj_close.resample("ME").last()
    return monthly_px.pct_change()


def _ols_beta(y: np.ndarray, x: np.ndarray) -> np.ndarray | None:
    mask = np.isfinite(y) & np.all(np.isfinite(x), axis=1)
    if mask.sum() < MIN_OBS_IN_WINDOW:
        return None
    xm = x[mask]
    ym = y[mask]
    if np.linalg.matrix_rank(xm) < xm.shape[1]:
        return None
    coef, *_ = np.linalg.lstsq(xm, ym, rcond=None)
    return coef


def compute_rolling_betas(
    returns: pd.DataFrame,
    market_ret: pd.Series,
    sentiment_shock: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = returns.index.intersection(market_ret.index).intersection(sentiment_shock.index)
    idx = idx.sort_values()
    tickers = list(returns.columns)
    beta_sent = pd.DataFrame(np.nan, index=idx, columns=tickers)
    beta_mkt = pd.DataFrame(np.nan, index=idx, columns=tickers)

    aligned_ret = returns.reindex(idx)
    aligned_mkt = market_ret.reindex(idx)
    aligned_sent = sentiment_shock.reindex(idx)

    for pos in range(ROLLING_WINDOW_MONTHS, len(idx)):
        hist = idx[pos - ROLLING_WINDOW_MONTHS:pos]
        x = np.column_stack([
            np.ones(len(hist)),
            aligned_mkt.loc[hist].to_numpy(dtype=float),
            aligned_sent.loc[hist].to_numpy(dtype=float),
        ])
        if np.nanstd(x[:, 2]) <= 1e-12:
            continue
        for ticker in tickers:
            y = aligned_ret.loc[hist, ticker].to_numpy(dtype=float)
            coef = _ols_beta(y, x)
            if coef is None:
                continue
            beta_mkt.loc[idx[pos], ticker] = coef[1]
            beta_sent.loc[idx[pos], ticker] = coef[2]
    return beta_sent, beta_mkt


def build_quintile_returns(
    returns: pd.DataFrame,
    beta_sent: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series]:
    rows: list[dict[str, Any]] = []
    n_stocks: dict[pd.Timestamp, int] = {}
    for dt in beta_sent.index:
        beta = beta_sent.loc[dt]
        ret = returns.reindex(beta_sent.index).loc[dt]
        valid = beta.notna() & ret.notna()
        if valid.sum() < 20:
            continue
        ranked = beta[valid].sort_values()
        q = max(1, len(ranked) // 5)
        low_names = ranked.index[:q]
        high_names = ranked.index[-q:]
        row = {
            "low": float(ret[low_names].mean()),
            "high": float(ret[high_names].mean()),
        }
        row["long_short"] = row["high"] - row["low"]
        rows.append({"date": dt, **row})
        n_stocks[dt] = int(valid.sum())
    if not rows:
        return pd.DataFrame(), pd.Series(dtype=float)
    out = pd.DataFrame(rows).set_index("date").sort_index()
    return out, pd.Series(n_stocks).sort_index()


def newey_west_t(x: pd.Series | np.ndarray, lags: int = 3) -> tuple[float, float, float]:
    arr = np.asarray(x, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    if n < 12:
        return float("nan"), float("nan"), float("nan")
    mu = float(np.mean(arr))
    e = arr - mu
    var = float(np.mean(e * e))
    max_lag = min(lags, n - 1)
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1)
        gamma = float(np.mean(e[lag:] * e[:-lag]))
        var += 2.0 * weight * gamma
    if var <= 0:
        return mu, float("nan"), float("nan")
    se = math.sqrt(var / n)
    t = mu / se if se > 0 else float("nan")
    p = 2.0 * (1.0 - stats.t.cdf(abs(t), df=n - 1)) if np.isfinite(t) else float("nan")
    return mu, float(t), float(p)


def fama_macbeth(
    returns: pd.DataFrame,
    beta_sent: pd.DataFrame,
    beta_mkt: pd.DataFrame,
    *,
    control_market_beta: bool,
) -> pd.Series:
    slopes = []
    for dt in beta_sent.index:
        y = returns.reindex(beta_sent.index).loc[dt]
        b = beta_sent.loc[dt]
        mb = beta_mkt.loc[dt]
        valid = y.notna() & b.notna()
        if valid.sum() < 20:
            continue
        cols = [np.ones(valid.sum())]
        b_valid = b[valid].to_numpy(dtype=float)
        if np.nanstd(b_valid) <= 1e-12:
            continue
        # Standardize beta cross-sectionally; slope = monthly return per 1-SD beta.
        b_z = (b_valid - np.nanmean(b_valid)) / np.nanstd(b_valid)
        cols.append(b_z)
        if control_market_beta:
            valid = valid & mb.notna()
            if valid.sum() < 20:
                continue
            yv = y[valid].to_numpy(dtype=float)
            b_valid = b[valid].to_numpy(dtype=float)
            mb_valid = mb[valid].to_numpy(dtype=float)
            if np.nanstd(b_valid) <= 1e-12:
                continue
            b_z = (b_valid - np.nanmean(b_valid)) / np.nanstd(b_valid)
            if np.nanstd(mb_valid) <= 1e-12:
                continue
            mb_z = (mb_valid - np.nanmean(mb_valid)) / np.nanstd(mb_valid)
            x = np.column_stack([np.ones(len(yv)), b_z, mb_z])
        else:
            yv = y[valid].to_numpy(dtype=float)
            x = np.column_stack(cols)
        if len(yv) < 20 or np.linalg.matrix_rank(x) < x.shape[1]:
            continue
        coef, *_ = np.linalg.lstsq(x, yv, rcond=None)
        slopes.append({"date": dt, "slope": float(coef[1])})
    if not slopes:
        return pd.Series(dtype=float)
    return pd.DataFrame(slopes).set_index("date")["slope"].sort_index()


def moving_block_bootstrap_mean(
    x: pd.Series,
    *,
    block: int = BOOTSTRAP_BLOCK,
    B: int = BOOTSTRAP_B,
    seed: int = SEED,
) -> dict[str, float]:
    arr = x.dropna().to_numpy(dtype=float)
    n = len(arr)
    if n < block * 2:
        return {
            "ci_low_ann": float("nan"),
            "ci_high_ann": float("nan"),
            "p_mean_le_zero": float("nan"),
        }
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block)
    means = np.empty(B)
    for b in range(B):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        sample = np.concatenate([arr[s:s + block] for s in starts])[:n]
        means[b] = sample.mean() * 12.0
    return {
        "ci_low_ann": float(np.quantile(means, 0.025)),
        "ci_high_ann": float(np.quantile(means, 0.975)),
        "p_mean_le_zero": float((np.sum(means <= 0.0) + 1) / (B + 1)),
    }


def summarize_proxy(
    proxy_name: str,
    returns: pd.DataFrame,
    market_ret: pd.Series,
    shock: pd.Series,
) -> tuple[ProxyResult, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    beta_sent, beta_mkt = compute_rolling_betas(returns, market_ret, shock)
    qret, n_stocks = build_quintile_returns(returns, beta_sent)
    if qret.empty:
        raise RuntimeError(f"{proxy_name}: no valid quintile returns")

    high = qret["high"].dropna()
    low = qret["low"].dropna()
    ls = qret["long_short"].dropna()
    common = high.index.intersection(low.index).intersection(ls.index)
    high = high.loc[common]
    low = low.loc[common]
    ls = ls.loc[common]

    high_low_dm_t, high_low_dm_p = strategy_dm_test(
        high.to_numpy(), low.to_numpy(), h=1, loss_fn="negative_return"
    )
    zero = np.zeros(len(ls))
    ls_vs_zero_dm_t, ls_vs_zero_dm_p = strategy_dm_test(
        ls.to_numpy(), zero, h=1, loss_fn="negative_return"
    )

    fmb = fama_macbeth(returns, beta_sent, beta_mkt, control_market_beta=False)
    fmb_ctrl = fama_macbeth(returns, beta_sent, beta_mkt, control_market_beta=True)
    fmb_mu, fmb_t, fmb_p = newey_west_t(fmb, lags=3)
    fmbc_mu, fmbc_t, fmbc_p = newey_west_t(fmb_ctrl, lags=3)
    boot = moving_block_bootstrap_mean(ls)

    mean_ann = float(ls.mean() * 12.0)
    vol_ann = float(ls.std(ddof=1) * math.sqrt(12.0))
    sharpe = float(mean_ann / vol_ann) if vol_ann > 0 else float("nan")
    direction_pass = bool(mean_ann > 0 and fmb_mu > 0)
    harvey_pass = bool(
        direction_pass
        and abs(high_low_dm_t) > HARVEY_T
        and abs(fmb_t) > HARVEY_T
    )
    verdict = "PASS" if harvey_pass else ("DIRECTIONAL_ONLY" if direction_pass else "NULL")

    result = ProxyResult(
        proxy=proxy_name,
        n_months=int(len(ls)),
        n_stocks_median=int(n_stocks.loc[common].median()),
        high_mean_ann=float(high.mean() * 12.0),
        low_mean_ann=float(low.mean() * 12.0),
        long_short_mean_ann=mean_ann,
        long_short_vol_ann=vol_ann,
        long_short_sharpe=sharpe,
        high_low_dm_t=float(high_low_dm_t),
        high_low_dm_p=float(high_low_dm_p),
        ls_vs_zero_dm_t=float(ls_vs_zero_dm_t),
        ls_vs_zero_dm_p=float(ls_vs_zero_dm_p),
        fmb_beta_mean_monthly=float(fmb_mu),
        fmb_beta_t_nw=float(fmb_t),
        fmb_beta_p_nw=float(fmb_p),
        fmb_beta_control_mkt_mean_monthly=float(fmbc_mu),
        fmb_beta_control_mkt_t_nw=float(fmbc_t),
        fmb_beta_control_mkt_p_nw=float(fmbc_p),
        bootstrap_ci_low_ann=boot["ci_low_ann"],
        bootstrap_ci_high_ann=boot["ci_high_ann"],
        bootstrap_p_mean_le_zero=boot["p_mean_le_zero"],
        harvey_pass=harvey_pass,
        direction_pass=direction_pass,
        verdict=verdict,
    )
    return result, qret, fmb, fmb_ctrl, n_stocks


def plot_cumulative(qrets_by_proxy: dict[str, pd.DataFrame]) -> str:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for name, qret in qrets_by_proxy.items():
        ls = qret["long_short"].dropna()
        wealth = (1.0 + ls).cumprod() - 1.0
        ax.plot(wealth.index, wealth.values, label=name)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("K1528 sentiment-beta long-short cumulative return")
    ax.set_ylabel("Cumulative return")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = FIG_DIR / "k1528_cumulative_long_short.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return str(path.relative_to(OUT_DIR))


def plot_summary(results: list[ProxyResult]) -> str:
    labels = [r.proxy for r in results]
    means = [r.long_short_mean_ann for r in results]
    tvals = [r.high_low_dm_t for r in results]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    axes[0].bar(labels, means, color=["#3b82f6", "#f97316"])
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_title("Annualized high-minus-low return")
    axes[0].set_ylabel("Annualized return")
    axes[1].bar(labels, tvals, color=["#64748b", "#64748b"])
    axes[1].axhline(HARVEY_T, color="red", linestyle="--", linewidth=1, label="Harvey +3")
    axes[1].axhline(-HARVEY_T, color="red", linestyle="--", linewidth=1)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("DM t: high vs low (positive = high worse)")
    axes[1].legend()
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    path = FIG_DIR / "k1528_summary_bars.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return str(path.relative_to(OUT_DIR))


def main() -> None:
    np.random.seed(SEED)
    all_tickers = sorted(set(TICKERS + ["SPY", "^VIX"]))
    adj = _download_adj_close(all_tickers)
    if "SPY" not in adj.columns or "^VIX" not in adj.columns:
        raise RuntimeError("SPY or ^VIX missing from yfinance response")

    stock_cols = [t for t in TICKERS if t in adj.columns]
    stock_ret = monthly_returns(adj[stock_cols])
    market_ret = monthly_returns(adj[["SPY"]])["SPY"]
    vix_level = adj["^VIX"].resample("ME").last()
    vix_optimism = -np.log(vix_level).diff()
    vix_optimism.name = "vix_optimism"

    umcsent = _download_umcsent()
    umcsent_change = (umcsent.diff() / 100.0).rename("umcsent_change")

    # Align and drop stocks with too little usable monthly history after IPOs.
    min_months = ROLLING_WINDOW_MONTHS + 36
    keep = [c for c in stock_ret.columns if stock_ret[c].dropna().shape[0] >= min_months]
    stock_ret = stock_ret[keep]

    proxies = {
        "VIX_optimism": vix_optimism,
        "UMCSENT_change": umcsent_change,
    }

    proxy_results: list[ProxyResult] = []
    qrets: dict[str, pd.DataFrame] = {}
    fmb_slopes: dict[str, dict[str, list[float]]] = {}
    n_stocks_by_proxy: dict[str, dict[str, float]] = {}

    for name, shock in proxies.items():
        res, qret, fmb, fmb_ctrl, n_stocks = summarize_proxy(
            name,
            stock_ret,
            market_ret,
            shock,
        )
        proxy_results.append(res)
        qrets[name] = qret
        fmb_slopes[name] = {
            "plain": [float(x) for x in fmb.dropna().values],
            "control_market_beta": [float(x) for x in fmb_ctrl.dropna().values],
        }
        n_stocks_by_proxy[name] = {
            "min": float(n_stocks.min()),
            "median": float(n_stocks.median()),
            "max": float(n_stocks.max()),
        }

    fig1 = plot_cumulative(qrets)
    fig2 = plot_summary(proxy_results)

    any_pass = any(r.harvey_pass for r in proxy_results)
    any_direction = any(r.direction_pass for r in proxy_results)
    if any_pass:
        verdict = "PASS"
    elif any_direction:
        verdict = "CONDITIONAL_DIRECTIONAL_ONLY"
    else:
        verdict = "NULL"

    summary = {
        "k_id": K_ID,
        "run_date": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "period": {"start": START, "end": END},
        "lookahead_policy": (
            "Rolling sentiment betas for month t use only months t-60..t-1; "
            "portfolios sorted on beta at t hold month-t returns."
        ),
        "data": {
            "source": "yfinance Adj Close (auto_adjust=False) + FRED UMCSENT",
            "universe_declared": TICKERS,
            "universe_used": keep,
            "n_universe_declared": len(TICKERS),
            "n_universe_used": len(keep),
            "survivorship_bias_warning": (
                "Fixed current liquid large-cap universe; not CRSP historical constituents."
            ),
            "monthly_return_rows": int(stock_ret.dropna(how="all").shape[0]),
        },
        "config": {
            "rolling_window_months": ROLLING_WINDOW_MONTHS,
            "min_obs_in_window": MIN_OBS_IN_WINDOW,
            "bootstrap_B": BOOTSTRAP_B,
            "bootstrap_block_months": BOOTSTRAP_BLOCK,
            "harvey_t_threshold": HARVEY_T,
        },
        "proxy_results": [r.__dict__ for r in proxy_results],
        "n_stocks_by_proxy": n_stocks_by_proxy,
        "figures": [fig1, fig2],
        "verdict": verdict,
        "interpretation": (
            "Free sentiment proxies do not reproduce a robust high-minus-low "
            "sentiment-beta premium under Harvey |t|>3 and Fama-MacBeth gates."
            if verdict != "PASS"
            else "At least one free proxy passes the pre-registered Harvey/FMB gates."
        ),
    }

    out = OUT_DIR / "k1528_results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "k_id": K_ID,
        "verdict": verdict,
        "proxy_results": [r.__dict__ for r in proxy_results],
        "figures": [fig1, fig2],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
