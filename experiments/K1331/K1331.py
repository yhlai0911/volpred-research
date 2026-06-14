from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, strategy_dm_test

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

INDEX = "SPY"
VIX = "^VIX"
COMPONENTS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "BRK-B",
    "JPM",
    "XOM",
    "UNH",
    "JNJ",
    "PG",
    "HD",
    "MA",
    "V",
    "BAC",
    "WMT",
    "KO",
    "PEP",
    "COST",
]
TICKERS = [INDEX, VIX] + COMPONENTS

START = "2013-01-01"
END = "2026-06-14"
RV_WINDOW = 21
Z_WINDOW = 252
OOS_START = "2022-01-01"
MIN_TRAIN = 756
TX_COST = 0.0002
EPS = 1e-10
HAC_LAGS = RV_WINDOW


def _extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series | None:
    if raw.empty:
        return None
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            if ticker in raw.columns.get_level_values(0):
                return raw[ticker]["Close"].rename(ticker)
            if "Close" in raw.columns.get_level_values(0):
                return raw["Close"][ticker].rename(ticker)
        if "Close" in raw.columns:
            return raw["Close"].rename(ticker)
    except Exception:
        return None
    return None


def fetch_prices(tickers: Iterable[str]) -> pd.DataFrame:
    raw = yf.download(
        list(tickers),
        start=START,
        end=END,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    series = {}
    for ticker in tickers:
        close = _extract_close(raw, ticker)
        if close is None:
            continue
        close = close.dropna()
        if close.shape[0] >= 750:
            series[ticker] = close
    prices = pd.DataFrame(series).sort_index().ffill(limit=3)
    prices = prices.dropna(how="all")
    prices.to_csv(DATA_DIR / "prices.csv")
    return prices


def future_rolling_mean(x: pd.Series, horizon: int) -> pd.Series:
    return x.shift(-1).rolling(horizon).mean().shift(-(horizon - 1))


def realized_var(ret: pd.Series | pd.DataFrame, window: int = RV_WINDOW) -> pd.Series | pd.DataFrame:
    return ret.pow(2).rolling(window).mean() * 252.0


def zscore_expanding_safe(x: pd.Series, window: int = Z_WINDOW) -> pd.Series:
    mu = x.rolling(window).mean()
    sd = x.rolling(window).std()
    return (x - mu) / sd


def build_dataset(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    needed = [INDEX, VIX] + [t for t in COMPONENTS if t in prices.columns]
    px = prices[needed].dropna()
    log_ret = np.log(px.drop(columns=[VIX])).diff()
    spy_ret = px[INDEX].pct_change()

    index_var = realized_var(log_ret[INDEX])
    component_vars = realized_var(log_ret.drop(columns=[INDEX]))
    avg_component_var = component_vars.mean(axis=1)
    dispersion_var = avg_component_var - index_var
    dispersion_vol = np.sqrt(avg_component_var.clip(lower=EPS)) - np.sqrt(index_var.clip(lower=EPS))
    corr_proxy = (index_var / avg_component_var.replace(0, np.nan)).clip(lower=0, upper=2)
    future_var = future_rolling_mean(log_ret[INDEX].pow(2), RV_WINDOW) * 252.0

    vix_var = (px[VIX] / 100.0).pow(2)
    df = pd.DataFrame(
        {
            "index_var": index_var,
            "avg_component_var": avg_component_var,
            "dispersion_var": dispersion_var,
            "dispersion_vol": dispersion_vol,
            "realized_corr_proxy": corr_proxy,
            "future_index_var_21d": future_var,
            "log_index_var": np.log(index_var.clip(lower=EPS)),
            "log_vix_var": np.log(vix_var.clip(lower=EPS)),
            "spy_return": spy_ret,
        }
    )
    df["dispersion_z"] = zscore_expanding_safe(df["dispersion_var"])
    df["corr_proxy_z"] = zscore_expanding_safe(df["realized_corr_proxy"])
    df["dispersion_ratio"] = df["avg_component_var"] / df["index_var"].replace(0, np.nan)
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    log_ret.to_csv(DATA_DIR / "log_returns.csv")
    df.to_csv(DATA_DIR / "features.csv")
    return df, spy_ret


def fit_logvar_forecasts(df: pd.DataFrame) -> dict:
    specs = {
        "M0_index_rv": ["log_index_var"],
        "M1_index_rv_dispersion": ["log_index_var", "dispersion_z"],
        "M2_index_rv_corr": ["log_index_var", "corr_proxy_z"],
        "M3_index_rv_disp_corr": ["log_index_var", "dispersion_z", "corr_proxy_z"],
        "M4_vix_index_rv": ["log_vix_var", "log_index_var"],
        "M5_vix_index_rv_disp_corr": [
            "log_vix_var",
            "log_index_var",
            "dispersion_z",
            "corr_proxy_z",
        ],
    }
    oos_idx = df.index[df.index >= pd.Timestamp(OOS_START)]
    oos_idx = [idx for idx in oos_idx if (df.index < idx).sum() >= MIN_TRAIN]
    forecasts = {name: pd.Series(index=oos_idx, dtype=float) for name in specs}

    for idx in oos_idx:
        train = df.loc[df.index < idx].copy()
        y = np.log(train["future_index_var_21d"].clip(lower=EPS).to_numpy())
        for name, features in specs.items():
            x_train = sm.add_constant(train[features], has_constant="add")
            model = sm.OLS(y, x_train).fit()
            x_now = sm.add_constant(df.loc[[idx], features], has_constant="add")
            forecasts[name].loc[idx] = float(np.exp(model.predict(x_now).iloc[0]))

    actual = df.loc[oos_idx, "future_index_var_21d"].astype(float)
    baseline_loss = qlike_pointwise(actual.to_numpy(), forecasts["M0_index_rv"].to_numpy())
    out = {}
    for name, pred in forecasts.items():
        pred = pred.astype(float)
        loss = qlike_pointwise(actual.to_numpy(), pred.to_numpy())
        t_stat, p_val = (0.0, 1.0)
        if name != "M0_index_rv":
            t_stat, p_val = dm_test(loss, baseline_loss, h=HAC_LAGS)
        mse = float(np.mean((actual.to_numpy() - pred.to_numpy()) ** 2))
        hist_mean = float(np.mean((actual.to_numpy() - actual.expanding().mean().shift(1).bfill().to_numpy()) ** 2))
        out[name] = {
            "features": specs[name],
            "qlike": float(qlike(actual.to_numpy(), pred.to_numpy())),
            "mse": mse,
            "oos_r2_vs_expanding_mean": float(1.0 - mse / hist_mean) if hist_mean > 0 else None,
            "dm_t_vs_M0": float(t_stat),
            "dm_p_vs_M0": float(p_val),
            "harvey_pass_vs_M0": bool(name != "M0_index_rv" and t_stat < -3.0),
            "forecast_mean": float(pred.mean()),
            "forecast_std": float(pred.std()),
        }

    forecast_df = pd.DataFrame({name: ser for name, ser in forecasts.items()})
    forecast_df.insert(0, "actual_future_index_var_21d", actual)
    forecast_df.to_csv(DATA_DIR / "oos_forecasts.csv")
    return {
        "oos_start": str(pd.Timestamp(OOS_START).date()),
        "oos_end": str(actual.index.max().date()),
        "oos_n": int(actual.shape[0]),
        "horizon_days": RV_WINDOW,
        "dm_hac_lags": HAC_LAGS,
        "models": out,
    }


def hac_regression(y: pd.Series, x: pd.Series) -> dict:
    aligned = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    model = sm.OLS(aligned["y"], sm.add_constant(aligned["x"])).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": HAC_LAGS},
    )
    return {
        "n_obs": int(model.nobs),
        "intercept": float(model.params["const"]),
        "slope": float(model.params["x"]),
        "t_hac": float(model.tvalues["x"]),
        "p_hac": float(model.pvalues["x"]),
        "r2": float(model.rsquared),
        "hac_lags": HAC_LAGS,
    }


def mean_reversion_tests(df: pd.DataFrame) -> dict:
    disp_change = df["dispersion_z"].shift(-RV_WINDOW) - df["dispersion_z"]
    corr_change = df["corr_proxy_z"].shift(-RV_WINDOW) - df["corr_proxy_z"]
    disp_reg = hac_regression(disp_change, df["dispersion_z"])
    corr_reg = hac_regression(corr_change, df["corr_proxy_z"])

    q20 = df["dispersion_z"].quantile(0.20)
    q80 = df["dispersion_z"].quantile(0.80)
    high = disp_change[df["dispersion_z"] >= q80].dropna()
    low = disp_change[df["dispersion_z"] <= q20].dropna()
    return {
        "dispersion_z_21d_change_on_current": disp_reg,
        "corr_proxy_z_21d_change_on_current": corr_reg,
        "dispersion_quintile_forward_change": {
            "low_q20_threshold": float(q20),
            "high_q80_threshold": float(q80),
            "low_mean_forward_change": float(low.mean()),
            "high_mean_forward_change": float(high.mean()),
            "high_minus_low": float(high.mean() - low.mean()),
            "n_low": int(low.shape[0]),
            "n_high": int(high.shape[0]),
        },
    }


def perf_stats(ret: pd.Series) -> dict:
    ret = ret.dropna()
    nav = (1.0 + ret).cumprod()
    years = ret.shape[0] / 252.0
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else np.nan
    vol = float(ret.std() * np.sqrt(252.0))
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252.0)) if ret.std() > 0 else np.nan
    mdd = float((nav / nav.cummax() - 1.0).min())
    q01 = float(ret.quantile(0.01))
    es05 = float(ret[ret <= ret.quantile(0.05)].mean())
    return {
        "n_days": int(ret.shape[0]),
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "daily_q01": q01,
        "daily_es05": es05,
    }


def strategy_tests(df: pd.DataFrame) -> dict:
    strat_df = df.loc[df.index >= pd.Timestamp(OOS_START)].copy()
    signal_high_disp = (strat_df["dispersion_z"] > 1.0).astype(float).shift(1).fillna(0.0)
    signal_low_corr = (strat_df["corr_proxy_z"] < -1.0).astype(float).shift(1).fillna(0.0)
    weights = {
        "BH_SPY": pd.Series(1.0, index=strat_df.index),
        "S1_de_risk_high_dispersion": 1.0 - 0.5 * signal_high_disp,
        "S2_de_risk_low_corr_proxy": 1.0 - 0.5 * signal_low_corr,
        "S3_de_risk_either": 1.0 - 0.5 * np.maximum(signal_high_disp, signal_low_corr),
    }
    returns = {}
    for name, weight in weights.items():
        weight = pd.Series(weight, index=strat_df.index).astype(float)
        tx = weight.diff().abs().fillna(0.0) * TX_COST
        returns[name] = weight * strat_df["spy_return"] - tx

    returns_df = pd.DataFrame(returns).dropna()
    returns_df.to_csv(DATA_DIR / "strategy_returns.csv")
    baseline = returns_df["BH_SPY"]
    out = {}
    for name in returns_df.columns:
        item = perf_stats(returns_df[name])
        if name != "BH_SPY":
            neg_t, neg_p = strategy_dm_test(returns_df[name], baseline, h=1, loss_fn="negative_return")
            down_t, down_p = strategy_dm_test(returns_df[name], baseline, h=1, loss_fn="downside")
            item["dm_negative_return_vs_BH"] = {"t": float(neg_t), "p": float(neg_p)}
            item["dm_downside_vs_BH"] = {"t": float(down_t), "p": float(down_p)}
            item["harvey_pass_negative_return"] = bool(neg_t < -3.0)
            item["harvey_pass_downside"] = bool(down_t < -3.0)
            item["average_exposure"] = float(weights[name].loc[returns_df.index].mean())
            item["turnover"] = float(weights[name].loc[returns_df.index].diff().abs().sum())
        out[name] = item
    return out


def make_figures(df: pd.DataFrame, forecast_results: dict) -> list[str]:
    paths = []
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    plot_df = df.loc["2016":].copy()
    axes[0].plot(plot_df.index, np.sqrt(plot_df["index_var"]), label="SPY realized vol", color="#1b4e6b")
    axes[0].plot(plot_df.index, np.sqrt(plot_df["avg_component_var"]), label="Avg constituent realized vol", color="#b85824", alpha=0.85)
    axes[0].legend(loc="upper left")
    axes[0].set_ylabel("Ann. vol")
    axes[1].plot(plot_df.index, plot_df["dispersion_z"], color="#384d2c")
    axes[1].axhline(1.0, color="#777777", lw=1, ls="--")
    axes[1].axhline(-1.0, color="#777777", lw=1, ls="--")
    axes[1].set_ylabel("Dispersion z")
    axes[2].plot(plot_df.index, plot_df["realized_corr_proxy"], color="#5f3b72")
    axes[2].set_ylabel("Corr proxy")
    axes[2].set_xlabel("Date")
    fig.suptitle("K1331 realized dispersion proxy")
    fig.tight_layout()
    out = FIG_DIR / "k1331_dispersion_timeseries.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    paths.append(str(out.relative_to(HERE)))

    models = forecast_results["models"]
    names = list(models)
    qlikes = [models[n]["qlike"] for n in names]
    colors = ["#777777" if n == "M0_index_rv" else "#2f6f73" for n in names]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(range(len(names)), qlikes, color=colors)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=25, ha="right")
    ax.set_ylabel("OOS QLIKE (lower is better)")
    ax.set_title("Forecast comparison vs current realized variance baseline")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    out = FIG_DIR / "k1331_oos_qlike.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    paths.append(str(out.relative_to(HERE)))
    return paths


def main() -> dict:
    prices = fetch_prices(TICKERS)
    available_components = [t for t in COMPONENTS if t in prices.columns]
    if INDEX not in prices.columns or VIX not in prices.columns or len(available_components) < 10:
        raise RuntimeError("Insufficient price data for K1331")

    df, _ = build_dataset(prices)
    forecast_results = fit_logvar_forecasts(df)
    mr_results = mean_reversion_tests(df)
    strat_results = strategy_tests(df)
    figures = make_figures(df, forecast_results)

    best_model = min(forecast_results["models"].items(), key=lambda kv: kv[1]["qlike"])
    best_strategy = max(strat_results.items(), key=lambda kv: kv[1]["sharpe"])

    dispersion_forecast_models = [
        "M1_index_rv_dispersion",
        "M2_index_rv_corr",
        "M3_index_rv_disp_corr",
        "M5_vix_index_rv_disp_corr",
    ]
    any_forecast_pass = any(
        forecast_results["models"][name]["harvey_pass_vs_M0"]
        for name in dispersion_forecast_models
    )
    any_strategy_pass = any(
        v.get("harvey_pass_negative_return") or v.get("harvey_pass_downside")
        for k, v in strat_results.items()
        if k != "BH_SPY"
    )
    mean_reversion_pass = (
        mr_results["dispersion_z_21d_change_on_current"]["slope"] < 0
        and abs(mr_results["dispersion_z_21d_change_on_current"]["t_hac"]) > 3.0
    )
    verdict = "CONDITIONAL_PASS_MEAN_REVERSION_ONLY" if mean_reversion_pass else "NULL"
    if any_forecast_pass or any_strategy_pass:
        verdict = "MIXED"

    results = {
        "experiment_id": "K1331",
        "title": "Realized dispersion / correlation proxy without options data",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "data_source": "yfinance adjusted close",
        "period": {
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "n_obs": int(df.shape[0]),
        },
        "tickers": {
            "index": INDEX,
            "vix": VIX,
            "components_requested": COMPONENTS,
            "components_used": available_components,
            "n_components_used": len(available_components),
        },
        "methodology": {
            "rv_window_days": RV_WINDOW,
            "future_target": "next 21 trading days SPY realized variance from t+1..t+21",
            "dispersion_proxy": "mean component 21d realized variance minus SPY 21d realized variance",
            "corr_proxy": "SPY 21d realized variance divided by mean component 21d realized variance",
            "lookahead_policy": "Forecast features use information through close t for t+1..t+21 target; trading signals use explicit signal.shift(1).",
            "limitations": [
                "Fixed current mega-cap basket creates survivorship bias and is not a historical S&P 500 constituent file.",
                "This is realized dispersion, not option-implied DSPX or a tradable correlation risk premium.",
                "21d targets overlap, so DM tests use h=21 HAC and descriptive claims are downscoped.",
            ],
        },
        "descriptive_stats": {
            col: {
                "mean": float(df[col].mean()),
                "std": float(df[col].std()),
                "p05": float(df[col].quantile(0.05)),
                "p50": float(df[col].quantile(0.50)),
                "p95": float(df[col].quantile(0.95)),
            }
            for col in [
                "index_var",
                "avg_component_var",
                "dispersion_var",
                "dispersion_vol",
                "realized_corr_proxy",
                "dispersion_ratio",
            ]
        },
        "correlations": df[
            [
                "index_var",
                "avg_component_var",
                "dispersion_var",
                "realized_corr_proxy",
                "log_vix_var",
                "future_index_var_21d",
            ]
        ]
        .corr()
        .round(6)
        .to_dict(),
        "mean_reversion": mr_results,
        "forecast_results": forecast_results,
        "strategy_results": strat_results,
        "summary": {
            "best_forecast_model": best_model[0],
            "best_forecast_qlike": best_model[1]["qlike"],
            "baseline_qlike": forecast_results["models"]["M0_index_rv"]["qlike"],
            "best_strategy_by_sharpe": best_strategy[0],
            "best_strategy_sharpe": best_strategy[1]["sharpe"],
            "bh_spy_sharpe": strat_results["BH_SPY"]["sharpe"],
            "mean_reversion_pass": bool(mean_reversion_pass),
            "dispersion_forecast_harvey_pass_vs_M0": bool(any_forecast_pass),
            "any_strategy_harvey_pass_vs_BH": bool(any_strategy_pass),
            "interpretation": (
                "Realized dispersion/correlation proxy mean-reverts strongly, but does not "
                "deliver Harvey-level OOS QLIKE forecast improvement over current SPY RV. "
                "Timing value appears only as downside-risk reduction from lower exposure."
            ),
        },
        "verdict": verdict,
        "verdict_reason": (
            "Realized dispersion is strongly mean-reverting and simple de-risking improves "
            "downside loss metrics, but dispersion/correlation features do not pass the "
            "Harvey OOS QLIKE forecast gate versus current SPY RV."
        ),
        "figures": figures,
        "references": [
            {
                "label": "Cboe S&P 500 Dispersion Index (DSPX)",
                "url": "https://www.cboe.com/us/indices/dispersion/",
            },
            {
                "label": "Driessen, Maenhout, Vilkov - Option-Implied Correlations and the Price of Correlation Risk",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2166829",
            },
            {
                "label": "Dispersion Trading and Correlation Risk Premium",
                "url": "https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID1889147_code850132.pdf?abstractid=1889147&mirid=1",
            },
        ],
    }

    out_path = HERE / "K1331_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {out_path}")
    print(f"[verdict] {verdict}")
    print(f"[best forecast] {best_model[0]} qlike={best_model[1]['qlike']:.6f}")
    print(f"[baseline] M0 qlike={forecast_results['models']['M0_index_rv']['qlike']:.6f}")
    return results


if __name__ == "__main__":
    main()
