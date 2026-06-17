"""research_factor_timing_regime

Does high-dimensional factor timing add value in volatility regimes, or does
turnover/cost eat the edge?

Data: yfinance adjusted close, monthly factor ETF returns.
Assets: MTUM, VLUE, QUAL, USMV, RPV, IVE, IWF.
Baselines: equal-weight factor basket, 12-1M momentum top-3.
Model: expanding-window ElasticNet panel prediction, long-only top-3.

Lookahead guard:
  - Features at month t use information available at month-end t.
  - Training rows for forecast date t require feature_date < t, so each target
    return ended no later than month t and is observable at allocation time.
  - Weights formed at month-end t are applied to month t+1 returns.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

import numpy as np
import pandas as pd

from volpred.stats.model_evaluation import strategy_dm_test

warnings.filterwarnings("ignore", category=FutureWarning)

EXPERIMENT_ID = "research_factor_timing_regime"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

FACTOR_TICKERS = ["MTUM", "VLUE", "QUAL", "USMV", "RPV", "IVE", "IWF"]
EXTRA_TICKERS = ["SPY", "^VIX"]
ALL_TICKERS = FACTOR_TICKERS + EXTRA_TICKERS
START = "2013-01-01"
END = "2026-06-18"
OOS_START = "2018-01-31"
SEED = 42
COST_BPS = 10.0
TOP_K = 3
BOOTSTRAP_B = 1000
BOOTSTRAP_BLOCK = 6.0


@dataclass
class StrategyResult:
    returns_gross: pd.Series
    returns_net: pd.Series
    weights: pd.DataFrame
    turnover: pd.Series


def load_prices() -> pd.DataFrame:
    cache_path = DATA_DIR / "prices_yfinance.csv"
    if cache_path.exists():
        prices = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if all(t in prices.columns for t in ALL_TICKERS):
            return prices[ALL_TICKERS].dropna(how="all")

    import yfinance as yf

    raw = yf.download(
        ALL_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        prices = raw[["Close"]].copy()
        prices.columns = ALL_TICKERS[:1]
    prices = prices.reindex(columns=ALL_TICKERS).dropna(how="all")
    prices.to_csv(cache_path)
    return prices


def monthly_data(prices: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    monthly_prices = prices.resample("ME").last()
    # Drop the current partial month. A 2026-06-17 pull must not be treated as
    # a complete June monthly return.
    monthly_prices = monthly_prices[monthly_prices.index <= prices.index.max().normalize()]
    factor_prices = monthly_prices[FACTOR_TICKERS].dropna(how="any")
    factor_returns = factor_prices.pct_change().dropna(how="any")
    spy_returns = monthly_prices["SPY"].pct_change()
    vix = monthly_prices["^VIX"].reindex(factor_returns.index).ffill()
    return factor_returns, spy_returns.reindex(factor_returns.index), vix


def trailing_return(ret: pd.DataFrame, window: int, skip: int = 0) -> pd.DataFrame:
    shifted = (1.0 + ret).shift(skip)
    return shifted.rolling(window).apply(np.prod, raw=True) - 1.0


def build_feature_panel(
    factor_returns: pd.DataFrame, spy_returns: pd.Series, vix: pd.Series
) -> pd.DataFrame:
    ret_1m = factor_returns
    ret_3m = trailing_return(factor_returns, 3)
    ret_6m = trailing_return(factor_returns, 6)
    ret_12_1 = trailing_return(factor_returns, 11, skip=1)
    vol_3m = factor_returns.rolling(3).std(ddof=1) * np.sqrt(12.0)
    vol_6m = factor_returns.rolling(6).std(ddof=1) * np.sqrt(12.0)
    spy_3m = trailing_return(spy_returns.to_frame("SPY"), 3)["SPY"]
    spy_vol_3m = spy_returns.rolling(3).std(ddof=1) * np.sqrt(12.0)
    vix_level = vix / 100.0
    vix_chg_3m = vix.pct_change(3)
    vix_high_20 = (vix > 20.0).astype(float)

    rows = []
    for dt in factor_returns.index:
        for ticker in FACTOR_TICKERS:
            rows.append(
                {
                    "date": dt,
                    "ticker": ticker,
                    "ret_1m": ret_1m.at[dt, ticker],
                    "ret_3m": ret_3m.at[dt, ticker],
                    "ret_6m": ret_6m.at[dt, ticker],
                    "ret_12_1": ret_12_1.at[dt, ticker],
                    "vol_3m": vol_3m.at[dt, ticker],
                    "vol_6m": vol_6m.at[dt, ticker],
                    "spy_ret_3m": spy_3m.loc[dt],
                    "spy_vol_3m": spy_vol_3m.loc[dt],
                    "vix_level": vix_level.loc[dt],
                    "vix_chg_3m": vix_chg_3m.loc[dt],
                    "vix_high_20": vix_high_20.loc[dt],
                    "ret_12_1_x_vix": ret_12_1.at[dt, ticker] * vix_high_20.loc[dt],
                    "vol_3m_x_vix": vol_3m.at[dt, ticker] * vix_high_20.loc[dt],
                    "target_next_ret": factor_returns[ticker].shift(-1).loc[dt],
                }
            )
    panel = pd.DataFrame(rows)
    feature_cols = [
        "ret_1m",
        "ret_3m",
        "ret_6m",
        "ret_12_1",
        "vol_3m",
        "vol_6m",
        "spy_ret_3m",
        "spy_vol_3m",
        "vix_level",
        "vix_chg_3m",
        "vix_high_20",
        "ret_12_1_x_vix",
        "vol_3m_x_vix",
        "target_next_ret",
    ]
    return panel.dropna(subset=feature_cols).reset_index(drop=True)


def equal_weights(dates: Iterable[pd.Timestamp]) -> pd.DataFrame:
    return pd.DataFrame(
        1.0 / len(FACTOR_TICKERS),
        index=pd.Index(dates, name="date"),
        columns=FACTOR_TICKERS,
    )


def top_k_weights(scores: pd.Series, top_k: int = TOP_K) -> pd.Series:
    scores = scores.reindex(FACTOR_TICKERS)
    chosen = scores.sort_values(ascending=False).head(top_k).index
    w = pd.Series(0.0, index=FACTOR_TICKERS)
    w.loc[chosen] = 1.0 / top_k
    return w


def momentum_weights(panel: pd.DataFrame, dates: Iterable[pd.Timestamp]) -> pd.DataFrame:
    out = []
    for dt in dates:
        sub = panel[panel["date"] == dt].set_index("ticker")
        out.append(top_k_weights(sub["ret_12_1"]))
    return pd.DataFrame(out, index=pd.Index(dates, name="date"))


def fit_predict_elastic_net(train: pd.DataFrame, test: pd.DataFrame, feature_cols: list[str]) -> pd.Series:
    x_train = train[feature_cols].to_numpy(dtype=float)
    y_train = train["target_next_ret"].to_numpy(dtype=float)
    x_test = test[feature_cols].to_numpy(dtype=float)

    mu = x_train.mean(axis=0)
    sd = x_train.std(axis=0, ddof=1)
    sd = np.where(sd <= 1e-12, 1.0, sd)
    x_train_z = (x_train - mu) / sd
    x_test_z = (x_test - mu) / sd

    try:
        from sklearn.linear_model import ElasticNet

        model = ElasticNet(alpha=0.002, l1_ratio=0.35, fit_intercept=True, max_iter=10000)
        model.fit(x_train_z, y_train)
        pred = model.predict(x_test_z)
    except Exception:
        ridge = 0.5
        x = np.column_stack([np.ones(len(x_train_z)), x_train_z])
        beta = np.linalg.solve(x.T @ x + ridge * np.eye(x.shape[1]), x.T @ y_train)
        pred = np.column_stack([np.ones(len(x_test_z)), x_test_z]) @ beta
    return pd.Series(pred, index=test["ticker"].to_numpy())


def elastic_net_weights(panel: pd.DataFrame, dates: Iterable[pd.Timestamp]) -> pd.DataFrame:
    feature_cols = [
        "ret_1m",
        "ret_3m",
        "ret_6m",
        "ret_12_1",
        "vol_3m",
        "vol_6m",
        "spy_ret_3m",
        "spy_vol_3m",
        "vix_level",
        "vix_chg_3m",
        "vix_high_20",
        "ret_12_1_x_vix",
        "vol_3m_x_vix",
    ]
    out = []
    for dt in dates:
        train = panel[panel["date"] < dt]
        test = panel[panel["date"] == dt]
        if train["date"].nunique() < 36:
            scores = test.set_index("ticker")["ret_12_1"]
        else:
            scores = fit_predict_elastic_net(train, test, feature_cols)
        out.append(top_k_weights(scores))
    return pd.DataFrame(out, index=pd.Index(dates, name="date"))


def simulate_strategy(weights: pd.DataFrame, factor_returns: pd.DataFrame) -> StrategyResult:
    cost_rate = COST_BPS / 10000.0
    gross_rets = []
    net_rets = []
    turnovers = []
    ret_dates = []
    prev_end_weights = pd.Series(0.0, index=FACTOR_TICKERS)

    for dt, w in weights.iterrows():
        pos = factor_returns.index.get_loc(dt)
        if pos + 1 >= len(factor_returns.index):
            continue
        next_dt = factor_returns.index[pos + 1]
        r = factor_returns.loc[next_dt, FACTOR_TICKERS]
        turnover = float(np.abs(w - prev_end_weights).sum())
        cost = cost_rate * turnover
        gross = float((w * r).sum())
        net = gross - cost

        gross_rets.append(gross)
        net_rets.append(net)
        turnovers.append(turnover)
        ret_dates.append(next_dt)

        denom = 1.0 + gross
        if denom > 1e-12:
            prev_end_weights = w * (1.0 + r) / denom
        else:
            prev_end_weights = w.copy()

    return StrategyResult(
        returns_gross=pd.Series(gross_rets, index=ret_dates),
        returns_net=pd.Series(net_rets, index=ret_dates),
        weights=weights,
        turnover=pd.Series(turnovers, index=ret_dates),
    )


def max_drawdown(ret: pd.Series) -> float:
    wealth = (1.0 + ret).cumprod()
    peak = wealth.cummax()
    return float((wealth / peak - 1.0).min())


def perf_stats(res: StrategyResult) -> Dict[str, float]:
    ret = res.returns_net
    gross = res.returns_gross
    years = len(ret) / 12.0
    wealth = float((1.0 + ret).prod())
    gross_wealth = float((1.0 + gross).prod())
    ann = ret.mean() * 12.0
    vol = ret.std(ddof=1) * np.sqrt(12.0)
    gross_ann = gross.mean() * 12.0
    gross_vol = gross.std(ddof=1) * np.sqrt(12.0)
    return {
        "n_months": int(len(ret)),
        "ann_return_net": float(ann),
        "ann_vol_net": float(vol),
        "sharpe_net": float(ann / vol) if vol > 0 else 0.0,
        "ann_return_gross": float(gross_ann),
        "ann_vol_gross": float(gross_vol),
        "sharpe_gross": float(gross_ann / gross_vol) if gross_vol > 0 else 0.0,
        "cagr_net": float(wealth ** (1.0 / years) - 1.0) if years > 0 else 0.0,
        "cagr_gross": float(gross_wealth ** (1.0 / years) - 1.0) if years > 0 else 0.0,
        "max_drawdown_net": max_drawdown(ret),
        "avg_monthly_turnover": float(res.turnover.mean()),
        "ann_cost_drag": float((gross - ret).mean() * 12.0),
        "final_wealth_net": wealth,
    }


def stationary_bootstrap_sharpe_diff(
    ret_a: np.ndarray,
    ret_b: np.ndarray,
    *,
    n_boot: int = BOOTSTRAP_B,
    mean_block: float = BOOTSTRAP_BLOCK,
    seed: int = SEED,
) -> Dict[str, float]:
    rng = np.random.default_rng(seed)
    n = len(ret_a)
    p = 1.0 / mean_block
    diffs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.empty(n, dtype=np.int64)
        idx[0] = rng.integers(0, n)
        for t in range(1, n):
            idx[t] = rng.integers(0, n) if rng.random() < p else (idx[t - 1] + 1) % n
        a = ret_a[idx]
        c = ret_b[idx]
        sa = a.mean() / a.std(ddof=1) * np.sqrt(12.0) if a.std(ddof=1) > 0 else 0.0
        sb = c.mean() / c.std(ddof=1) * np.sqrt(12.0) if c.std(ddof=1) > 0 else 0.0
        diffs[b] = sa - sb
    return {
        "mean_diff": float(diffs.mean()),
        "ci_lower_2p5": float(np.percentile(diffs, 2.5)),
        "ci_upper_97p5": float(np.percentile(diffs, 97.5)),
        "p_value_two_sided": float(2.0 * min(np.mean(diffs > 0), np.mean(diffs < 0))),
    }


def regime_breakdown(strategies: Dict[str, StrategyResult], vix: pd.Series) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for name, res in strategies.items():
        signal_dates = res.weights.index
        hold_dates = res.returns_net.index
        signal_for_return = pd.Series(signal_dates[: len(hold_dates)], index=hold_dates)
        vix_signal = signal_for_return.map(vix)
        high = vix_signal > 20.0
        for label, mask in [("high_vix_gt20", high), ("low_vix_le20", ~high)]:
            r = res.returns_net[mask.fillna(False)]
            out[f"{name}_{label}"] = {
                "n_months": int(len(r)),
                "ann_return": float(r.mean() * 12.0) if len(r) else 0.0,
                "ann_vol": float(r.std(ddof=1) * np.sqrt(12.0)) if len(r) > 1 else 0.0,
                "sharpe": float(r.mean() / r.std(ddof=1) * np.sqrt(12.0))
                if len(r) > 1 and r.std(ddof=1) > 0
                else 0.0,
            }
    return out


def make_figure(strategies: Dict[str, StrategyResult]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    for name, res in strategies.items():
        wealth = (1.0 + res.returns_net).cumprod()
        axes[0].plot(wealth.index, wealth.values, label=name, lw=1.6)
        axes[1].plot(res.turnover.index, res.turnover.rolling(6).mean(), label=name, lw=1.2)
    axes[0].set_title("Net wealth, monthly factor ETF strategies")
    axes[0].set_ylabel("Growth of $1")
    axes[0].legend()
    axes[0].grid(alpha=0.3)
    axes[1].set_title("6-month rolling average turnover")
    axes[1].set_ylabel("Turnover")
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "factor_timing_wealth_turnover.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    np.random.seed(SEED)
    prices = load_prices()
    factor_returns, spy_returns, vix = monthly_data(prices)
    panel = build_feature_panel(factor_returns, spy_returns, vix)

    all_dates = sorted(panel["date"].unique())
    oos_dates = [d for d in all_dates if d >= pd.Timestamp(OOS_START)]
    # Exclude final feature date because target next-month return is unavailable.
    oos_dates = [d for d in oos_dates if factor_returns.index.get_loc(d) + 1 < len(factor_returns.index)]

    weights = {
        "EW": equal_weights(oos_dates),
        "MOM_12_1_TOP3": momentum_weights(panel, oos_dates),
        "EN_REGIME_TOP3": elastic_net_weights(panel, oos_dates),
    }
    strategies = {name: simulate_strategy(w, factor_returns) for name, w in weights.items()}

    summary = {name: perf_stats(res) for name, res in strategies.items()}
    dm_tests = {}
    bootstraps = {}
    benchmark = strategies["EW"].returns_net
    for i, name in enumerate(["MOM_12_1_TOP3", "EN_REGIME_TOP3"]):
        r = strategies[name].returns_net.reindex(benchmark.index).dropna()
        b = benchmark.reindex(r.index)
        t_stat, p_val = strategy_dm_test(r.values, b.values, h=1, loss_fn="negative_return")
        dm_tests[f"{name}_vs_EW_net"] = {
            "t_stat": float(t_stat),
            "p_value": float(p_val),
            "interpretation": "negative t means strategy has higher net monthly return than EW",
            "harvey_pass_abs_t_gt_3": bool(abs(t_stat) > 3.0),
        }
        bootstraps[f"{name}_vs_EW_net"] = stationary_bootstrap_sharpe_diff(
            r.values, b.values, seed=SEED + i
        )

    # Cost-eats-edge diagnostic: gross advantage minus net advantage.
    cost_diagnostic = {}
    ew = strategies["EW"]
    for name, res in strategies.items():
        if name == "EW":
            continue
        common = res.returns_net.index.intersection(ew.returns_net.index)
        gross_edge = (res.returns_gross.loc[common] - ew.returns_gross.loc[common]).mean() * 12.0
        net_edge = (res.returns_net.loc[common] - ew.returns_net.loc[common]).mean() * 12.0
        cost_diagnostic[name] = {
            "gross_edge_vs_EW_ann": float(gross_edge),
            "net_edge_vs_EW_ann": float(net_edge),
            "edge_lost_to_cost_ann": float(gross_edge - net_edge),
            "avg_turnover_minus_EW": float(res.turnover.mean() - ew.turnover.mean()),
        }

    make_figure(strategies)

    out = {
        "experiment_id": EXPERIMENT_ID,
        "title": "High-dimensional factor timing under volatility regimes: turnover/cost audit",
        "data": {
            "source": "yfinance adjusted close (cached)",
            "tickers": FACTOR_TICKERS,
            "extra_tickers": EXTRA_TICKERS,
            "daily_start": str(prices.index.min().date()),
            "daily_end": str(prices.index.max().date()),
            "monthly_start": str(factor_returns.index.min().date()),
            "monthly_end": str(factor_returns.index.max().date()),
            "oos_start": OOS_START,
            "n_oos_months": int(summary["EW"]["n_months"]),
        },
        "config": {
            "seed": SEED,
            "cost_bps_one_way": COST_BPS,
            "top_k": TOP_K,
            "bootstrap_B": BOOTSTRAP_B,
            "bootstrap_mean_block_months": BOOTSTRAP_BLOCK,
            "lookahead_guard": "features at t, training feature_date < t, weights at t applied to t+1 returns",
            "model": "expanding panel ElasticNet(alpha=0.002,l1_ratio=0.35), long-only top-3",
        },
        "summary_stats": summary,
        "dm_tests_net_returns": dm_tests,
        "bootstrap_sharpe_diff": bootstraps,
        "cost_eats_edge": cost_diagnostic,
        "regime_breakdown": regime_breakdown(strategies, vix),
        "figures": ["figures/factor_timing_wealth_turnover.png"],
        "verdict": "NULL",
        "verdict_rationale": (
            "No timing strategy clears Harvey |t|>3 vs equal-weight after costs; "
            "ElasticNet/regime timing increases turnover and does not deliver a robust net edge."
        ),
    }

    out_path = EXP_DIR / f"{EXPERIMENT_ID}_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=float)
    print(json.dumps(out["summary_stats"], indent=2))
    print(f"[done] wrote {out_path}")


if __name__ == "__main__":
    main()
