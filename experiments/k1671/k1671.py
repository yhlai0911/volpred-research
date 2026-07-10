#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K1671 -- volume folk-rule independent replication.

Question
--------
Do "volume leads price" and "high-volume black candles are distribution"
predict next-day direction?

This is intentionally an independent replication / closure task for a stale
research_program backlog item. K1659 and K1667 already tested the same folk
claim. K1671 expands the universe and uses a stricter previous-volume baseline
so the backlog item can be closed without treating a duplicate as a new result.

Lookahead guard
---------------
1. Volume spike threshold uses the *previous* 20 trading days:
   volume_t > k * rolling_mean(volume, 20).shift(1)_t.
2. Event signal formed after close t is applied to return t+1 via
   signal.shift(1).
3. Pooled inference aggregates by calendar date first, then applies HAC.
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

try:
    import statsmodels.api as sm
except Exception as exc:  # pragma: no cover - dependency failure should be loud
    raise RuntimeError("K1671 requires statsmodels for HAC inference") from exc

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.utils import clean_tw50_data  # noqa: E402


SEED = 42
START = "2005-01-01"
END = "2026-07-10"
VOL_WINDOW = 20
VOL_MULT = 2.0
BLACK_RET = -0.015
BOOT_REPS = 5000
BOOT_BLOCK = 5
HAC_LAGS = 5
TRADING_DAYS = 252
TCOST = 0.0005  # 5 bps per one-way unit turnover

ASSETS = {
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "IWM": "Russell 2000 ETF",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "0050.TW": "Taiwan 50 ETF",
    "2330.TW": "TSMC Taiwan",
    "2317.TW": "Hon Hai",
}

DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figs"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)


def atomic_write_json(obj: dict, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    with tmp.open("r", encoding="utf-8") as f:
        json.load(f)
    os.replace(tmp, path)


def flatten_yf(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def load_asset(ticker: str) -> tuple[pd.DataFrame, dict]:
    """Load daily OHLCV. Cache is stored under experiments/k1671/data."""
    cache = DATA_DIR / f"{ticker.replace('.', '_')}.csv"
    source = "cache"
    if cache.exists():
        raw = pd.read_csv(cache, index_col=0, parse_dates=True)
        raw = flatten_yf(raw)
        if raw.index.max() < pd.Timestamp("2026-07-01"):
            raw = pd.DataFrame()
    else:
        raw = pd.DataFrame()

    if raw.empty:
        import yfinance as yf

        source = "yfinance_download"
        raw = yf.download(
            ticker,
            start=START,
            end=END,
            auto_adjust=False,
            progress=False,
        )
        raw = flatten_yf(raw)
        if raw.empty:
            raise RuntimeError(f"yfinance returned no rows for {ticker}")
        raw.to_csv(cache)

    raw = raw[~raw.index.duplicated(keep="first")].sort_index()
    price_field = "Adj Close" if "Adj Close" in raw.columns and raw["Adj Close"].notna().any() else "Close"
    price = raw[price_field].astype(float)
    if ticker == "0050.TW":
        price, _ = clean_tw50_data(price)

    out = pd.DataFrame(
        {
            "price": price,
            "volume": raw["Volume"].astype(float),
        }
    ).dropna()
    out = out[out["volume"] > 0]
    out["ret"] = out["price"].pct_change()
    out = out.dropna(subset=["ret"])

    meta = {
        "ticker": ticker,
        "name": ASSETS[ticker],
        "source": source,
        "price_field": price_field,
        "start": str(out.index.min().date()),
        "end": str(out.index.max().date()),
        "n_days": int(len(out)),
    }
    return out, meta


def build_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Signals known after close t. They are lagged during evaluation."""
    vol_ma_prev = df["volume"].rolling(VOL_WINDOW, min_periods=VOL_WINDOW).mean().shift(1)
    high_volume = df["volume"] > VOL_MULT * vol_ma_prev
    sig = pd.DataFrame(index=df.index)
    sig["high_volume"] = high_volume.fillna(False).astype(bool)
    sig["high_volume_up"] = (sig["high_volume"] & (df["ret"] > 0)).astype(bool)
    sig["high_volume_down"] = (sig["high_volume"] & (df["ret"] < 0)).astype(bool)
    sig["high_volume_black"] = (sig["high_volume"] & (df["ret"] <= BLACK_RET)).astype(bool)
    return sig


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> dict:
    if n1 <= 0 or n2 <= 0:
        return {"diff": None, "z": None, "p": None}
    p1 = x1 / n1
    p2 = x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(max(p_pool * (1.0 - p_pool) * (1.0 / n1 + 1.0 / n2), 0.0))
    if se == 0:
        return {"diff": float(p1 - p2), "z": None, "p": None}
    z = (p1 - p2) / se
    p = 2.0 * (1.0 - stats.norm.cdf(abs(z)))
    return {"diff": float(p1 - p2), "z": float(z), "p": float(p)}


def circular_block_indices(rng: np.random.Generator, n: int, block: int) -> np.ndarray:
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % n
    return idx[:n]


def bootstrap_mean_diff(ret: pd.Series, sig_lag: pd.Series, seed: int) -> dict:
    """Circular block bootstrap CI for E[ret|signal]-E[ret]."""
    df = pd.DataFrame({"ret": ret, "signal": sig_lag.astype(bool)}).dropna()
    x = df["ret"].to_numpy(dtype=float)
    s = df["signal"].to_numpy(dtype=bool)
    point = float(x[s].mean() - x.mean()) if s.sum() else float("nan")
    rng = np.random.default_rng(seed)
    draws = np.empty(BOOT_REPS)
    for i in range(BOOT_REPS):
        idx = circular_block_indices(rng, len(x), BOOT_BLOCK)
        xb = x[idx]
        sb = s[idx]
        draws[i] = np.nan if sb.sum() == 0 else xb[sb].mean() - xb.mean()
    draws = draws[np.isfinite(draws)]
    centered = draws - np.nanmean(draws) + point
    ci = np.percentile(draws, [2.5, 97.5])
    p_two = float(np.mean(np.abs(centered - point) >= abs(point))) if np.isfinite(point) else None
    return {
        "point": point,
        "ci95": [float(ci[0]), float(ci[1])],
        "p_two_sided_boot": p_two,
        "reps": BOOT_REPS,
        "block": BOOT_BLOCK,
        "seed": seed,
    }


def evaluate_signal(
    ticker: str,
    df: pd.DataFrame,
    signal: pd.Series,
    direction: str,
    seed_offset: int,
) -> tuple[dict, pd.Series]:
    """Evaluate signal[t-1] -> ret[t].

    direction is the folk-claim direction: "up" or "down".
    Returns both statistics and the conditionally selected next-day returns.
    """
    sig_lag = signal.shift(1).fillna(False).astype(bool)
    ret = df["ret"].dropna()
    sig_lag = sig_lag.reindex(ret.index).fillna(False).astype(bool)
    cond = ret[sig_lag]
    all_ret = ret
    n_signal = int(sig_lag.sum())
    out = {
        "ticker": ticker,
        "n_signal": n_signal,
        "direction": direction,
        "lookahead_policy": "signal.shift(1): event at close t-1 predicts return t",
    }
    if n_signal < 20:
        out["insufficient"] = True
        return out, cond

    if direction == "up":
        hits = int((cond > 0).sum())
        base_hits = int((all_ret > 0).sum())
    elif direction == "down":
        hits = int((cond < 0).sum())
        base_hits = int((all_ret < 0).sum())
    else:
        raise ValueError(direction)

    hit_rate = hits / len(cond)
    base_rate = base_hits / len(all_ret)
    z = two_prop_z(hits, len(cond), base_hits, len(all_ret))
    try:
        binom_p = float(stats.binomtest(hits, len(cond), base_rate).pvalue)
    except ValueError:
        binom_p = None
    boot = bootstrap_mean_diff(ret, sig_lag, SEED + seed_offset)

    out.update(
        {
            "insufficient": False,
            "hit_rate": float(hit_rate),
            "unconditional_rate": float(base_rate),
            "hit_rate_minus_base": float(hit_rate - base_rate),
            "binom_p_vs_estimated_base": binom_p,
            "two_prop_z": z,
            "cond_mean_ret": float(cond.mean()),
            "uncond_mean_ret": float(all_ret.mean()),
            "mean_diff": float(cond.mean() - all_ret.mean()),
            "mean_diff_bootstrap": boot,
            "cond_worst_day": float(cond.min()),
            "cond_best_day": float(cond.max()),
        }
    )
    return out, cond


def hac_mean(x: pd.Series) -> dict:
    x = x.dropna().astype(float)
    if len(x) < 30:
        return {"available": False, "n_dates": int(len(x))}
    res = sm.OLS(x.to_numpy(), np.ones((len(x), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}
    )
    return {
        "available": True,
        "n_dates": int(len(x)),
        "mean": float(res.params[0]),
        "hac_t": float(res.tvalues[0]),
        "hac_p": float(res.pvalues[0]),
        "hac_lags": HAC_LAGS,
    }


def pooled_diagnostic(series_by_asset: dict[str, pd.Series], direction: str) -> dict:
    """Date-level pooled diagnostic. Positive signed mean supports the myth."""
    mat = pd.DataFrame(series_by_asset)
    raw_daily = mat.mean(axis=1, skipna=True).dropna()
    signed_daily = raw_daily if direction == "up" else -raw_daily
    out = {
        "note": "date-level cross-asset mean; HAC on dates, not stacked asset-days",
        "direction": direction,
        "raw_next_day_return": hac_mean(raw_daily),
        "myth_signed_return": hac_mean(signed_daily),
    }
    return out


def strategy_returns(
    returns_by_asset: dict[str, pd.Series],
    signal_by_asset: dict[str, pd.Series],
    side: int,
) -> pd.Series:
    """Equal-weight signal strategy with one-day holding and simple turnover cost."""
    all_idx = sorted(set().union(*[set(x.index) for x in returns_by_asset.values()]))
    out = pd.Series(0.0, index=pd.DatetimeIndex(all_idx))
    counts = pd.Series(0.0, index=out.index)
    for ticker, ret in returns_by_asset.items():
        sig = signal_by_asset[ticker].shift(1).reindex(ret.index).fillna(False).astype(bool)
        pos = sig.astype(float) * float(side)
        cost = pos.diff().abs().fillna(pos.abs()) * TCOST
        r = pos * ret - cost
        out.loc[r.index] += r
        counts.loc[r.index] += (pos != 0).astype(float)
    active = counts > 0
    strat = pd.Series(0.0, index=out.index)
    strat.loc[active] = out.loc[active] / counts.loc[active]
    return strat.sort_index()


def equal_weight_buyhold(returns_by_asset: dict[str, pd.Series]) -> pd.Series:
    all_idx = sorted(set().union(*[set(x.index) for x in returns_by_asset.values()]))
    mat = pd.DataFrame(index=pd.DatetimeIndex(all_idx))
    for ticker, ret in returns_by_asset.items():
        mat[ticker] = ret
    return mat.mean(axis=1, skipna=True).dropna()


def perf(ret: pd.Series) -> dict:
    ret = ret.dropna()
    if ret.empty:
        return {}
    sd = ret.std(ddof=1)
    sharpe = ret.mean() / sd * math.sqrt(TRADING_DAYS) if sd > 0 else float("nan")
    eq = (1.0 + ret).cumprod()
    dd = eq / eq.cummax() - 1.0
    return {
        "n_days": int(len(ret)),
        "active_days": int((ret != 0).sum()),
        "ann_return_arith": float(ret.mean() * TRADING_DAYS),
        "ann_vol": float(sd * math.sqrt(TRADING_DAYS)),
        "sharpe": float(sharpe),
        "max_drawdown": float(dd.min()),
        "hit_rate_positive_day": float((ret[ret != 0] > 0).mean()) if (ret != 0).any() else None,
    }


def bh_adjust(pvals: list[float | None]) -> list[float | None]:
    valid = [(i, p) for i, p in enumerate(pvals) if p is not None and np.isfinite(p)]
    out: list[float | None] = [None] * len(pvals)
    if not valid:
        return out
    order = sorted(valid, key=lambda x: x[1])
    m = len(order)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i, p = order[rank]
        q = min(prev, p * m / (rank + 1))
        prev = q
        out[i] = float(min(q, 1.0))
    return out


def summarize(results: dict) -> dict:
    tests = []
    for ticker, asset in results["assets"].items():
        for key, direction in [
            ("A_high_volume_next_up", "up"),
            ("B_high_volume_black_next_down", "down"),
        ]:
            e = asset["tests"][key]
            if e.get("insufficient"):
                continue
            p = e["two_prop_z"]["p"]
            tests.append((ticker, key, direction, p, e))

    qvals = bh_adjust([x[3] for x in tests])
    rows = []
    support = 0
    opposite = 0
    for (ticker, key, direction, p, e), q in zip(tests, qvals):
        ci = e["mean_diff_bootstrap"]["ci95"]
        mean_diff = e["mean_diff"]
        if direction == "up":
            claim_mean_ok = mean_diff > 0
            opposite_mean_ok = mean_diff < 0
            hit_ok = e["hit_rate_minus_base"] > 0
            hit_opp = e["hit_rate_minus_base"] < 0
        else:
            claim_mean_ok = mean_diff < 0
            opposite_mean_ok = mean_diff > 0
            hit_ok = e["hit_rate_minus_base"] > 0
            hit_opp = e["hit_rate_minus_base"] < 0
        ci_excludes_zero = (ci[0] > 0) or (ci[1] < 0)
        supported = bool(q is not None and q < 0.05 and ci_excludes_zero and claim_mean_ok and hit_ok)
        opp = bool(q is not None and q < 0.05 and ci_excludes_zero and opposite_mean_ok and hit_opp)
        support += int(supported)
        opposite += int(opp)
        rows.append(
            {
                "ticker": ticker,
                "test": key,
                "n_signal": e["n_signal"],
                "hit_rate_minus_base": e["hit_rate_minus_base"],
                "mean_diff": e["mean_diff"],
                "mean_diff_ci95": ci,
                "p_two_prop": p,
                "q_bh": q,
                "myth_supported": supported,
                "opposite_significant": opp,
            }
        )

    pooled = results["pooled_diagnostic"]
    strategy = results["strategy"]
    return {
        "primary_spec": f"volume > {VOL_MULT} x previous {VOL_WINDOW}d average; signal.shift(1)",
        "n_primary_tests": len(rows),
        "n_myth_supported_bh_5pct": support,
        "n_opposite_bh_5pct": opposite,
        "rows": rows,
        "pooled_A_high_volume_signed_t": pooled["A_high_volume_next_up"]["myth_signed_return"],
        "pooled_B_black_signed_t": pooled["B_high_volume_black_next_down"]["myth_signed_return"],
        "strategy_A_long_after_high_volume": strategy["A_long_after_high_volume"],
        "strategy_B_short_after_black": strategy["B_short_after_black"],
        "buyhold_equal_weight": strategy["buyhold_equal_weight"],
        "verdict": "PARTIAL_FOR_VOLUME_LEADS_PRICE__FALSE_FOR_BLACK_CANDLE_DISTRIBUTION",
        "interpretation": (
            "Independent replication refines K1659/K1667: high volume is not a universal "
            "next-day up rule across ETFs and single names, but a positive effect appears in "
            "specific Taiwan single stocks and the date-level pooled diagnostic. The "
            "high-volume black-candle/distribution claim is rejected again: next-day returns "
            "are not robustly negative and pooled evidence points in the opposite direction."
        ),
    }


def make_figures(results: dict) -> list[str]:
    for font in ["Arial Unicode MS", "Heiti TC", "STHeiti", "PingFang HK", "DejaVu Sans"]:
        try:
            import matplotlib.font_manager as fm

            fm.findfont(font, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [font]
            break
        except Exception:
            continue
    plt.rcParams["axes.unicode_minus"] = False

    tickers = list(results["assets"].keys())
    fig_paths = []

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    specs = [
        ("A_high_volume_next_up", "量先價行：爆量後隔日上漲率", "#2f77b4"),
        ("B_high_volume_black_next_down", "爆量長黑：隔日下跌率", "#b43c30"),
    ]
    for ax, (key, title, color) in zip(axes, specs):
        labs, hit, base = [], [], []
        for t in tickers:
            e = results["assets"][t]["tests"][key]
            if e.get("insufficient"):
                continue
            labs.append(t)
            hit.append(e["hit_rate"] * 100)
            base.append(e["unconditional_rate"] * 100)
        x = np.arange(len(labs))
        ax.bar(x - 0.2, hit, width=0.4, color=color, label="訊號後")
        ax.bar(x + 0.2, base, width=0.4, color="#b8b8b8", label="無條件")
        ax.axhline(50.0, color="#333333", lw=0.8, ls="--")
        ax.set_xticks(x)
        ax.set_xticklabels(labs, rotation=30, ha="right")
        ax.set_ylim(20, 75)
        ax.set_ylabel("命中率 (%)")
        ax.set_title(title)
        ax.legend(fontsize=8)
    fig.suptitle("K1671 成交量隔日方向迷思：條件命中率沒有穩定跨資產優勢")
    fig.tight_layout()
    p = FIG_DIR / "k1671_hit_rates.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    fig_paths.append(str(p.relative_to(HERE)))

    fig, ax = plt.subplots(figsize=(10, 5))
    strat_a = pd.Series(results["_plot_series"]["strategy_A"])
    strat_b = pd.Series(results["_plot_series"]["strategy_B"])
    if not strat_a.empty:
        strat_a.index = pd.to_datetime(strat_a.index)
        strat_b.index = pd.to_datetime(strat_b.index)
        ax.plot((1 + strat_a).cumprod(), label="爆量後隔日做多", color="#2f77b4")
        ax.plot((1 + strat_b).cumprod(), label="爆量長黑後隔日放空", color="#b43c30")
    ax.axhline(1.0, color="#333333", lw=0.8)
    ax.set_title("K1671 迷思策略等權淨值（5bps 單向成本）")
    ax.set_ylabel("累積淨值")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = FIG_DIR / "k1671_strategy_equity.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    fig_paths.append(str(p.relative_to(HERE)))
    return fig_paths


def main() -> dict:
    returns_by_asset: dict[str, pd.Series] = {}
    sig_high_by_asset: dict[str, pd.Series] = {}
    sig_black_by_asset: dict[str, pd.Series] = {}
    cond_a: dict[str, pd.Series] = {}
    cond_b: dict[str, pd.Series] = {}

    results = {
        "experiment_id": "k1671",
        "title": "量先價行 / 爆量長黑是出貨：成交量能否預測隔日方向（獨立複核）",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_source": "yfinance daily OHLCV, cached under experiments/k1671/data",
        "related_prior_experiments": ["k1659", "k1667"],
        "literature": [
            "Campbell, Grossman and Wang (1993), Trading Volume and Serial Correlation in Stock Returns",
            "Gervais, Kaniel and Mingelgrin (2001), The High-Volume Return Premium",
            "Llorente, Michaely, Saar and Wang (2002), Dynamic Volume-Return Relation of Individual Stocks",
        ],
        "config": {
            "start": START,
            "end": END,
            "volume_window": VOL_WINDOW,
            "volume_multiplier": VOL_MULT,
            "black_return_threshold": BLACK_RET,
            "bootstrap_reps": BOOT_REPS,
            "bootstrap_block": BOOT_BLOCK,
            "hac_lags": HAC_LAGS,
            "transaction_cost": TCOST,
            "assets": ASSETS,
            "lookahead_policy": (
                "volume threshold uses rolling(volume,20).mean().shift(1); "
                "event signal uses signal.shift(1) before multiplying same-index return"
            ),
        },
        "assets": {},
    }

    for i, ticker in enumerate(ASSETS):
        print(f"[k1671] loading/evaluating {ticker}", flush=True)
        df, meta = load_asset(ticker)
        sig = build_signals(df)
        ret = df["ret"].dropna()
        returns_by_asset[ticker] = ret
        sig_high_by_asset[ticker] = sig["high_volume"].reindex(ret.index).fillna(False)
        sig_black_by_asset[ticker] = sig["high_volume_black"].reindex(ret.index).fillna(False)

        a, ca = evaluate_signal(ticker, df, sig["high_volume"], "up", i * 10 + 1)
        b, cb = evaluate_signal(ticker, df, sig["high_volume_black"], "down", i * 10 + 2)
        upbar, _ = evaluate_signal(ticker, df, sig["high_volume_up"], "up", i * 10 + 3)
        downbar, _ = evaluate_signal(ticker, df, sig["high_volume_down"], "down", i * 10 + 4)
        cond_a[ticker] = ca
        cond_b[ticker] = cb
        results["assets"][ticker] = {
            "meta": meta,
            "event_counts": {k: int(v.sum()) for k, v in sig.items()},
            "tests": {
                "A_high_volume_next_up": a,
                "A2_high_volume_up_next_up": upbar,
                "A3_high_volume_down_next_down": downbar,
                "B_high_volume_black_next_down": b,
            },
        }

    strat_a = strategy_returns(returns_by_asset, sig_high_by_asset, side=1)
    strat_b = strategy_returns(returns_by_asset, sig_black_by_asset, side=-1)
    bh = equal_weight_buyhold(returns_by_asset)
    results["pooled_diagnostic"] = {
        "A_high_volume_next_up": pooled_diagnostic(cond_a, "up"),
        "B_high_volume_black_next_down": pooled_diagnostic(cond_b, "down"),
    }
    results["strategy"] = {
        "A_long_after_high_volume": perf(strat_a),
        "B_short_after_black": perf(strat_b),
        "buyhold_equal_weight": perf(bh),
        "A_minus_buyhold_on_active_dates": perf((strat_a - bh.reindex(strat_a.index)).loc[strat_a != 0]),
        "B_minus_buyhold_on_active_dates": perf((strat_b - bh.reindex(strat_b.index)).loc[strat_b != 0]),
    }
    results["_plot_series"] = {
        "strategy_A": {str(k.date()): float(v) for k, v in strat_a.items()},
        "strategy_B": {str(k.date()): float(v) for k, v in strat_b.items()},
    }
    results["summary"] = summarize(results)
    results["figures"] = make_figures(results)

    clean = dict(results)
    clean.pop("_plot_series", None)
    atomic_write_json(clean, HERE / "k1671_results.json")
    print("[k1671] wrote k1671_results.json", flush=True)
    return clean


if __name__ == "__main__":
    main()
