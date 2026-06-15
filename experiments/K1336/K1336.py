#!/usr/bin/env python3
"""K1336: EM FX carry x FX-vol regime double-gate test."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


SEED = 42
START = "2004-01-01"
END = "2026-06-15"
OOS_START = pd.Timestamp("2012-01-03")
TRADING_DAYS = 252
VOL_WINDOW = 60
THRESHOLD_WINDOW = 756
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
ONE_WAY_COST_BPS = 5.0
SPOT_LOGRET_OUTLIER_ABS = 0.15
EPS = 1e-12

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "K1336_results.json"
FIG_EQUITY = HERE / "K1336_fig_equity.png"
FIG_DRAWDOWN = HERE / "K1336_fig_drawdown.png"
FIG_CURRENCY = HERE / "K1336_fig_currency_metrics.png"


CURRENCIES = {
    "BRL": {
        "fx_ticker": "BRL=X",
        "fred_rate": "IRSTCB01BRM156N",
        "rate_frequency": "monthly",
        "name": "Brazilian real",
    },
    "MXN": {
        "fx_ticker": "MXN=X",
        "fred_rate": "IR3TIB01MXM156N",
        "rate_frequency": "monthly",
        "name": "Mexican peso",
    },
    "ZAR": {
        "fx_ticker": "ZAR=X",
        "fred_rate": "IR3TIB01ZAM156N",
        "rate_frequency": "monthly",
        "name": "South African rand",
    },
    "IDR": {
        "fx_ticker": "IDR=X",
        "fred_rate": "IR3TIB01IDQ156N",
        "rate_frequency": "quarterly",
        "name": "Indonesian rupiah",
    },
}
US_RATE = "TB3MS"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
AVAILABILITY_LAG_DAYS = {"monthly": 45, "quarterly": 90}
MAX_STALE_DAYS = {"monthly": 120, "quarterly": 210}


@dataclass(frozen=True)
class StrategyMetrics:
    nobs: int
    ann_return: float
    ann_vol: float
    sharpe: float
    max_drawdown: float
    active_share: float
    avg_gross_exposure: float
    turnover_per_year: float
    cost_drag_ann: float
    skew: float


def read_fred_series(series_id: str, frequency: str, name: str) -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(FRED_CSV.format(series_id=series_id))
    value_col = [c for c in raw.columns if c != "observation_date"][0]
    values = pd.to_numeric(raw[value_col].replace(".", np.nan), errors="coerce")
    obs_date = pd.to_datetime(raw["observation_date"])
    lag_days = AVAILABILITY_LAG_DAYS[frequency]
    df = pd.DataFrame(
        {
            "value": values,
            "observation_date": obs_date,
            "available_date": obs_date + pd.Timedelta(days=lag_days),
        }
    ).dropna()
    df = df.sort_values("available_date").set_index("available_date")
    df[["value", "observation_date"]].to_csv(DATA_DIR / f"fred_{name}.csv")
    return df


def align_rate_to_daily(rate_df: pd.DataFrame, daily_index: pd.DatetimeIndex, frequency: str) -> pd.Series:
    value = rate_df["value"].reindex(daily_index.union(rate_df.index)).sort_index().ffill().reindex(daily_index)
    available_date = pd.Series(rate_df.index, index=rate_df.index)
    last_available = available_date.reindex(daily_index.union(rate_df.index)).sort_index().ffill().reindex(daily_index)
    stale = (daily_index - pd.to_datetime(last_available).to_numpy()) > np.timedelta64(MAX_STALE_DAYS[frequency], "D")
    value = value.mask(stale)
    return value


def download_fx() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tickers = [meta["fx_ticker"] for meta in CURRENCIES.values()]
    raw = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("yfinance returned no FX data")
    close = raw["Close"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].copy()
    close = close.rename(columns={meta["fx_ticker"]: code for code, meta in CURRENCIES.items()})
    close.index = pd.to_datetime(close.index)
    close = close[list(CURRENCIES)].dropna(how="all")
    close.to_csv(DATA_DIR / "fx_close.csv")
    return close


def build_panel() -> tuple[pd.DataFrame, dict[str, dict]]:
    fx = download_fx()
    daily_index = fx.index
    us_rate_df = read_fred_series(US_RATE, "monthly", "US_TB3MS")
    us_rate = align_rate_to_daily(us_rate_df, daily_index, "monthly")

    panels: list[pd.DataFrame] = []
    data_quality: dict[str, dict] = {}
    for code, meta in CURRENCIES.items():
        rate_df = read_fred_series(meta["fred_rate"], meta["rate_frequency"], code)
        em_rate = align_rate_to_daily(rate_df, daily_index, meta["rate_frequency"])
        rate_diff = em_rate - us_rate
        usd_lcy_log_ret_raw = np.log(fx[code] / fx[code].shift(1))
        spot_outlier = usd_lcy_log_ret_raw.abs() > SPOT_LOGRET_OUTLIER_ABS
        usd_lcy_log_ret = usd_lcy_log_ret_raw.mask(spot_outlier)
        local_long_spot_ret = -usd_lcy_log_ret
        carry_available = rate_diff / 100.0
        carry_lag1 = carry_available.shift(1)
        carry_daily_lag1 = carry_lag1 / TRADING_DAYS
        fx_vol_lag1 = (usd_lcy_log_ret.rolling(VOL_WINDOW).std(ddof=1) * np.sqrt(TRADING_DAYS)).shift(1)
        carry_threshold_lag1 = carry_available.rolling(THRESHOLD_WINDOW, min_periods=252).quantile(0.60).shift(1)
        vol_threshold_lag1 = fx_vol_lag1.rolling(THRESHOLD_WINDOW, min_periods=252).median().shift(1)

        gross_carry_ret = local_long_spot_ret + carry_daily_lag1
        pure_weight = (carry_lag1 > 0.0).astype(float)
        gate_weight = (
            (carry_lag1 > 0.0)
            & (carry_lag1 > carry_threshold_lag1)
            & (fx_vol_lag1 < vol_threshold_lag1)
        ).astype(float)
        valid_signal = gross_carry_ret.notna() & carry_lag1.notna() & fx_vol_lag1.notna()
        pure_weight = pure_weight.where(valid_signal, 0.0)
        gate_weight = gate_weight.where(valid_signal, 0.0)

        one_way_cost = ONE_WAY_COST_BPS / 10000.0
        pure_turnover = pure_weight.diff().abs().fillna(pure_weight.abs())
        gate_turnover = gate_weight.diff().abs().fillna(gate_weight.abs())
        per_currency_weight = 1.0 / len(CURRENCIES)
        panel = pd.DataFrame(
            {
                f"{code}_spot": fx[code],
                f"{code}_usd_lcy_log_ret": usd_lcy_log_ret,
                f"{code}_carry_lag1": carry_lag1,
                f"{code}_fx_vol60_lag1": fx_vol_lag1,
                f"{code}_carry_threshold_lag1": carry_threshold_lag1,
                f"{code}_vol_threshold_lag1": vol_threshold_lag1,
                f"{code}_pure_weight": pure_weight * per_currency_weight,
                f"{code}_gate_weight": gate_weight * per_currency_weight,
                f"{code}_pure_net_ret": pure_weight * per_currency_weight * gross_carry_ret
                - pure_turnover * per_currency_weight * one_way_cost,
                f"{code}_gate_net_ret": gate_weight * per_currency_weight * gross_carry_ret
                - gate_turnover * per_currency_weight * one_way_cost,
                f"{code}_pure_turnover": pure_turnover * per_currency_weight,
                f"{code}_gate_turnover": gate_turnover * per_currency_weight,
            }
        )
        panels.append(panel)
        data_quality[code] = {
            "fx_ticker": meta["fx_ticker"],
            "fred_rate": meta["fred_rate"],
            "rate_frequency": meta["rate_frequency"],
            "rate_obs_start": str(rate_df["observation_date"].min().date()),
            "rate_obs_end": str(rate_df["observation_date"].max().date()),
            "rate_available_end": str(rate_df.index.max().date()),
            "valid_return_days": int(valid_signal.sum()),
            "spot_logret_outliers_removed": int(spot_outlier.sum()),
        }

    full = pd.concat(panels, axis=1)
    full["pure_net_ret"] = full[[f"{c}_pure_net_ret" for c in CURRENCIES]].sum(axis=1)
    full["gate_net_ret"] = full[[f"{c}_gate_net_ret" for c in CURRENCIES]].sum(axis=1)
    full["pure_weight_sum"] = full[[f"{c}_pure_weight" for c in CURRENCIES]].sum(axis=1)
    full["gate_weight_sum"] = full[[f"{c}_gate_weight" for c in CURRENCIES]].sum(axis=1)
    full["pure_turnover"] = full[[f"{c}_pure_turnover" for c in CURRENCIES]].sum(axis=1)
    full["gate_turnover"] = full[[f"{c}_gate_turnover" for c in CURRENCIES]].sum(axis=1)
    full = full.replace([np.inf, -np.inf], np.nan)
    full.to_csv(DATA_DIR / "panel.csv")
    return full, data_quality


def max_drawdown(ret: pd.Series) -> float:
    equity = (1.0 + ret.fillna(0.0)).cumprod()
    dd = equity / equity.cummax() - 1.0
    return float(dd.min())


def metrics(ret: pd.Series, weight_sum: pd.Series, turnover: pd.Series) -> StrategyMetrics:
    sample = ret.dropna()
    ann_return = (1.0 + sample).prod() ** (TRADING_DAYS / len(sample)) - 1.0
    ann_vol = sample.std(ddof=1) * np.sqrt(TRADING_DAYS)
    sharpe = ann_return / ann_vol if ann_vol > 0 else np.nan
    return StrategyMetrics(
        nobs=int(len(sample)),
        ann_return=round(float(ann_return), 6),
        ann_vol=round(float(ann_vol), 6),
        sharpe=round(float(sharpe), 4),
        max_drawdown=round(max_drawdown(sample), 6),
        active_share=round(float((weight_sum.reindex(sample.index).fillna(0.0) > 0).mean()), 6),
        avg_gross_exposure=round(float(weight_sum.reindex(sample.index).fillna(0.0).mean()), 6),
        turnover_per_year=round(float(turnover.reindex(sample.index).fillna(0.0).mean() * TRADING_DAYS), 6),
        cost_drag_ann=round(float(turnover.reindex(sample.index).fillna(0.0).mean() * TRADING_DAYS * ONE_WAY_COST_BPS / 10000.0), 6),
        skew=round(float(sample.skew()), 4),
    )


def hac_mean_test(series: pd.Series, maxlags: int = 21) -> dict:
    sample = series.dropna()
    x = np.ones((len(sample), 1))
    fit = sm.OLS(sample.to_numpy(dtype=float), x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "nobs": int(fit.nobs),
        "mean_daily": round(float(fit.params[0]), 8),
        "mean_ann": round(float(fit.params[0]) * TRADING_DAYS, 6),
        "hac_t": round(float(fit.tvalues[0]), 4),
        "hac_p": round(float(fit.pvalues[0]), 6),
        "maxlags": maxlags,
    }


def moving_block_bootstrap_sharpe_diff(base: pd.Series, gate: pd.Series) -> dict:
    aligned = pd.DataFrame({"base": base, "gate": gate}).dropna()
    arr = aligned.to_numpy(dtype=float)
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(BOOTSTRAP_REPS):
        chosen: list[int] = []
        while len(chosen) < len(arr):
            start = int(rng.integers(0, max(1, len(arr) - BOOTSTRAP_BLOCK + 1)))
            chosen.extend(range(start, min(start + BOOTSTRAP_BLOCK, len(arr))))
        b = arr[np.asarray(chosen[: len(arr)], dtype=int)]
        base_ret = pd.Series(b[:, 0])
        gate_ret = pd.Series(b[:, 1])
        base_vol = base_ret.std(ddof=1) * np.sqrt(TRADING_DAYS)
        gate_vol = gate_ret.std(ddof=1) * np.sqrt(TRADING_DAYS)
        base_ann = (1.0 + base_ret).prod() ** (TRADING_DAYS / len(base_ret)) - 1.0
        gate_ann = (1.0 + gate_ret).prod() ** (TRADING_DAYS / len(gate_ret)) - 1.0
        diffs.append((gate_ann / gate_vol if gate_vol > 0 else np.nan) - (base_ann / base_vol if base_vol > 0 else np.nan))
    vals = pd.Series(diffs).dropna().to_numpy(dtype=float)
    return {
        "mean": round(float(vals.mean()), 6),
        "ci_2p5": round(float(np.quantile(vals, 0.025)), 6),
        "ci_97p5": round(float(np.quantile(vals, 0.975)), 6),
        "p_gt_0": round(float((vals > 0).mean()), 4),
        "reps": BOOTSTRAP_REPS,
        "block_length": BOOTSTRAP_BLOCK,
        "seed": SEED,
    }


def currency_metrics(panel: pd.DataFrame, sample_index: pd.DatetimeIndex) -> dict[str, dict]:
    out = {}
    for code in CURRENCIES:
        pure = panel[f"{code}_pure_net_ret"].reindex(sample_index).fillna(0.0)
        gate = panel[f"{code}_gate_net_ret"].reindex(sample_index).fillna(0.0)
        out[code] = {
            "pure": asdict(metrics(pure, panel[f"{code}_pure_weight"], panel[f"{code}_pure_turnover"])),
            "gate": asdict(metrics(gate, panel[f"{code}_gate_weight"], panel[f"{code}_gate_turnover"])),
            "gate_minus_pure_hac": hac_mean_test(gate - pure),
        }
    return out


def build_figures(panel: pd.DataFrame, oos: pd.DataFrame, strategy_metrics: dict, per_currency: dict) -> None:
    equity = (1.0 + oos[["pure_net_ret", "gate_net_ret"]].fillna(0.0)).cumprod()
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(equity.index, equity["pure_net_ret"], label="Pure carry", color="#4c78a8")
    ax.plot(equity.index, equity["gate_net_ret"], label="Carry x low-FX-vol gate", color="#f58518")
    ax.set_title("K1336 EM FX Carry Double-Gate Equity Curve")
    ax.set_ylabel("Growth of $1")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_EQUITY, dpi=180)
    plt.close(fig)

    dd = equity / equity.cummax() - 1.0
    fig2, ax2 = plt.subplots(figsize=(10, 5))
    ax2.plot(dd.index, dd["pure_net_ret"], label="Pure carry", color="#4c78a8")
    ax2.plot(dd.index, dd["gate_net_ret"], label="Carry x low-FX-vol gate", color="#f58518")
    ax2.set_title("K1336 Drawdown")
    ax2.set_ylabel("Drawdown")
    ax2.legend(frameon=False)
    fig2.tight_layout()
    fig2.savefig(FIG_DRAWDOWN, dpi=180)
    plt.close(fig2)

    labels = list(CURRENCIES)
    pure_sharpe = [per_currency[c]["pure"]["sharpe"] for c in labels]
    gate_sharpe = [per_currency[c]["gate"]["sharpe"] for c in labels]
    x = np.arange(len(labels))
    width = 0.35
    fig3, ax3 = plt.subplots(figsize=(9, 5))
    ax3.bar(x - width / 2, pure_sharpe, width, label="Pure", color="#4c78a8")
    ax3.bar(x + width / 2, gate_sharpe, width, label="Gate", color="#f58518")
    ax3.axhline(0.0, color="#333333", linewidth=1)
    ax3.set_xticks(x, labels)
    ax3.set_ylabel("Sharpe")
    ax3.set_title("Per-Currency Strategy Sharpe")
    ax3.legend(frameon=False)
    fig3.tight_layout()
    fig3.savefig(FIG_CURRENCY, dpi=180)
    plt.close(fig3)


def main() -> None:
    np.random.seed(SEED)
    panel, data_quality = build_panel()
    oos = panel[panel.index >= OOS_START].copy()
    oos = oos.dropna(subset=["pure_net_ret", "gate_net_ret"])
    strategy_metrics = {
        "pure_carry": asdict(metrics(oos["pure_net_ret"], oos["pure_weight_sum"], oos["pure_turnover"])),
        "carry_vol_gate": asdict(metrics(oos["gate_net_ret"], oos["gate_weight_sum"], oos["gate_turnover"])),
    }
    per_currency = currency_metrics(panel, oos.index)
    diff = oos["gate_net_ret"] - oos["pure_net_ret"]
    tests = {
        "gate_minus_pure_hac_mean": hac_mean_test(diff, maxlags=21),
        "gate_minus_pure_sharpe_bootstrap": moving_block_bootstrap_sharpe_diff(
            oos["pure_net_ret"], oos["gate_net_ret"]
        ),
    }
    build_figures(panel, oos, strategy_metrics, per_currency)

    pure = strategy_metrics["pure_carry"]
    gate = strategy_metrics["carry_vol_gate"]
    sharpe_diff = gate["sharpe"] - pure["sharpe"]
    mdd_improvement = abs(pure["max_drawdown"]) - abs(gate["max_drawdown"])
    mdd_improvement_pct = mdd_improvement / abs(pure["max_drawdown"]) if pure["max_drawdown"] < 0 else np.nan
    support = (
        sharpe_diff >= 0.15
        and tests["gate_minus_pure_hac_mean"]["hac_t"] > 3.0
        and mdd_improvement_pct >= 0.20
        and tests["gate_minus_pure_sharpe_bootstrap"]["ci_2p5"] > 0.0
    )
    partial = (
        sharpe_diff > 0.0
        and mdd_improvement_pct > 0.0
        and tests["gate_minus_pure_sharpe_bootstrap"]["p_gt_0"] >= 0.80
    )
    verdict = "SUPPORT" if support else "PARTIAL" if partial else "NULL"

    results = {
        "experiment_id": "K1336",
        "title": "EM FX carry x FX-vol regime double-gate",
        "date_run_utc": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "data": {
            "fx_source": "yfinance adjusted close; spot tickers are USD per local-currency pairs shown as local currency per USD",
            "rate_source": "FRED/OECD monthly or quarterly short-rate proxies",
            "currencies": CURRENCIES,
            "us_rate": US_RATE,
            "start": START,
            "end": END,
            "oos_start": str(OOS_START.date()),
            "oos_rows": int(len(oos)),
            "cached_data_dir": "experiments/K1336/data/",
            "data_quality": data_quality,
        },
        "method": {
            "return_proxy": "long EM currency funded in USD: rate_diff_lag1/252 - dlog(USDLC)",
            "rate_availability_lag_days": AVAILABILITY_LAG_DAYS,
            "max_stale_days_after_available_rate": MAX_STALE_DAYS,
            "pure_carry_baseline": "1/4 notional per currency when lagged EM-USD short-rate differential is positive",
            "double_gate": (
                "1/4 notional only when lagged carry is positive, above its rolling 756d 60th percentile, "
                "and lagged 60d FX realized volatility is below its rolling 756d median"
            ),
            "lookahead_policy": [
                "FRED rate observations are shifted to conservative availability dates before daily alignment",
                "carry, realized-volatility, and threshold signals use explicit .shift(1)",
                "strategy returns at date t use only signals available before date t",
            ],
            "transaction_cost": f"{ONE_WAY_COST_BPS} bps per one-way notional change",
            "spot_outlier_filter": f"abs(dlog USDLC) > {SPOT_LOGRET_OUTLIER_ABS} treated as FX spot data error and set to NaN",
            "success_rule": (
                "SUPPORT requires gate Sharpe improvement >=0.15, HAC t>3 for gate-minus-pure mean return, "
                "MDD improvement >=20%, and bootstrap Sharpe-diff 95% CI lower bound >0. PARTIAL requires "
                "positive Sharpe and MDD improvement with bootstrap p_gt_0 >=0.80."
            ),
        },
        "strategy_metrics": strategy_metrics,
        "per_currency_metrics": per_currency,
        "tests": tests,
        "figures": [FIG_EQUITY.name, FIG_DRAWDOWN.name, FIG_CURRENCY.name],
        "literature": [
            {
                "citation": "Menkhoff, Sarno, Schmeling, and Schrimpf (2012), Carry Trades and Global Foreign Exchange Volatility",
                "url": "https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2012.01728.x",
            },
            {
                "citation": "Lustig, Roussanov, and Verdelhan (2011), Common Risk Factors in Currency Markets",
                "url": "https://academic.oup.com/rfs/article-abstract/24/11/3731/1589752",
            },
            {
                "citation": "Brunnermeier, Nagel, and Pedersen (2008), Carry Trades and Currency Crashes",
                "url": "https://www.nber.org/papers/w14473",
            },
            {
                "citation": "FRED/OECD short-rate proxies and yfinance USD/EM FX spot data",
                "url": "https://fred.stlouisfed.org/",
            },
        ],
        "research_honesty_notes": [
            "This is a spot-plus-rate-differential proxy, not a fully collateralized institutional FX forward carry book.",
            "Brazil's FRED/OECD rate series ends in 2023; stale-rate masking limits later BRL contribution.",
            "Monthly and quarterly macro-rate releases are conservatively availability-lagged before daily use.",
            "The gate lowers exposure; lower drawdown can come from sitting in cash rather than superior timing.",
            "Extreme yfinance FX spot glitches are removed with a pre-specified absolute log-return filter.",
        ],
        "verdict": {
            "overall": verdict,
            "sharpe_diff": round(float(sharpe_diff), 6),
            "mdd_improvement": round(float(mdd_improvement), 6),
            "mdd_improvement_pct": round(float(mdd_improvement_pct), 6),
            "support": support,
            "partial": partial,
            "plain_english": (
                "The carry x low-FX-vol gate beats pure carry on the full statistical and drawdown gate."
                if verdict == "SUPPORT"
                else "The carry x low-FX-vol gate improves some risk metrics but fails the full statistical gate."
                if verdict == "PARTIAL"
                else "The carry x low-FX-vol gate does not beat the pure carry baseline under the pre-specified gate."
            ),
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results["verdict"], indent=2, ensure_ascii=False))
    print(json.dumps(strategy_metrics, indent=2))


if __name__ == "__main__":
    main()
