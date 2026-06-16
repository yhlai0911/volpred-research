"""K1516 - Fiscal-monetary regime and stock-bond correlation predictability.

Question
--------
Can a lagged high-deficit x tightening regime predict the forward 60-day
SPY/TLT return correlation turning positive, and does a simple allocation
switch improve 60/40 performance out of sample?

Data
----
- yfinance: SPY, TLT adjusted daily close.
- FRED: MTSDS133FMS monthly federal surplus/deficit, GDP, FEDFUNDS.

Lookahead defense
-----------------
- Monthly deficit data are available only after a 45-calendar-day lag.
- Quarterly GDP is available only after a 120-calendar-day lag from quarter
  start (roughly 30 days after quarter end).
- Monthly FEDFUNDS is available only after a 35-calendar-day lag.
- Macro features are forward-filled to trading days after release lag and then
  shifted by 1 trading day.
- Forward-correlation target at date t uses returns from t+1 through t+60.
- Training rows require target_end < OOS_START, so no forward label overlaps
  the out-of-sample period.

Run
---
uv run python experiments/k1516_fiscal_regime_stock_bond_corr/k1516.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats
from sklearn.linear_model import LinearRegression
from sklearn.metrics import accuracy_score, mean_squared_error, r2_score, roc_auc_score

from volpred.stats.model_evaluation import dm_test, strategy_dm_test


SEED = 42
HERE = Path(__file__).resolve().parent

START = "2003-01-01"
END = "2026-06-16"
OOS_START = pd.Timestamp("2020-01-01")
HORIZON = 60
ROLL_CORR = 60

TICKERS = ["SPY", "TLT"]
FRED_SERIES = {
    "deficit_monthly": "MTSDS133FMS",
    "gdp": "GDP",
    "fedfunds": "FEDFUNDS",
}


@dataclass(frozen=True)
class SplitData:
    train: pd.DataFrame
    oos: pd.DataFrame
    full: pd.DataFrame


def fred_csv(series_id: str) -> pd.Series:
    """Download a FRED CSV series with a hard failure on missing data."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(url, timeout=45)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    if df.empty or series_id not in df.columns:
        raise RuntimeError(f"FRED returned no usable data for {series_id}")
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    ser = pd.to_numeric(df[series_id].replace(".", np.nan), errors="coerce")
    out = pd.Series(ser.values, index=df["observation_date"], name=series_id).dropna()
    if out.empty:
        raise RuntimeError(f"FRED series {series_id} is empty after numeric parse")
    return out.sort_index()


def fetch_prices() -> pd.DataFrame:
    """Fetch adjusted closes for SPY/TLT.  No synthetic fallback."""
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        progress=False,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        timeout=45,
    )
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned empty data")

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw.xs("Close", axis=1, level=1)
    else:
        raise RuntimeError("Unexpected yfinance shape: MultiIndex columns required")

    close = close.rename(columns={c: str(c) for c in close.columns})
    missing = [t for t in TICKERS if t not in close.columns]
    if missing:
        raise RuntimeError(f"Missing yfinance close columns: {missing}")

    close = close[TICKERS].dropna(how="any")
    close.index = pd.to_datetime(close.index).tz_localize(None)
    if close.empty:
        raise RuntimeError("Price frame empty after dropna")
    return close


def align_released_series(
    series: pd.Series, trading_index: pd.DatetimeIndex, release_lag_days: int
) -> pd.Series:
    """Align low-frequency values after a conservative release lag."""
    available = series.copy()
    available.index = pd.to_datetime(available.index) + pd.Timedelta(days=release_lag_days)
    available = available[~available.index.duplicated(keep="last")].sort_index()
    aligned = available.reindex(trading_index, method="ffill")
    return aligned


def forward_corr(x: pd.Series, y: pd.Series, horizon: int) -> tuple[pd.Series, pd.Series]:
    """Correlation of x/y returns from t+1 through t+h."""
    vals = np.full(len(x), np.nan, dtype=float)
    ends: list[pd.Timestamp | pd.NaT] = [pd.NaT] * len(x)
    xv = x.to_numpy(dtype=float)
    yv = y.to_numpy(dtype=float)
    idx = x.index
    for i in range(len(x) - horizon):
        xs = xv[i + 1 : i + horizon + 1]
        ys = yv[i + 1 : i + horizon + 1]
        if np.isfinite(xs).all() and np.isfinite(ys).all():
            vals[i] = np.corrcoef(xs, ys)[0, 1]
            ends[i] = idx[i + horizon]
    return (
        pd.Series(vals, index=idx, name=f"target_fwd_corr{horizon}"),
        pd.Series(ends, index=idx, name="target_end"),
    )


def build_dataset() -> pd.DataFrame:
    prices = fetch_prices()
    logret = np.log(prices / prices.shift(1)).dropna()
    logret.columns = ["spy_ret", "tlt_ret"]

    deficit_monthly = fred_csv(FRED_SERIES["deficit_monthly"])
    gdp = fred_csv(FRED_SERIES["gdp"])
    fedfunds = fred_csv(FRED_SERIES["fedfunds"])

    monthly_deficit_12m = -deficit_monthly.rolling(12, min_periods=12).sum()
    deficit_available = align_released_series(monthly_deficit_12m, logret.index, 45)
    gdp_available = align_released_series(gdp * 1000.0, logret.index, 120)
    deficit_gdp = (deficit_available / gdp_available).rename("deficit_gdp")

    fedfunds_daily = align_released_series(fedfunds, logret.index, 35).rename("fedfunds")
    fedfunds_yoy = (fedfunds_daily - fedfunds_daily.shift(252)).rename(
        "fedfunds_yoy_chg"
    )

    target, target_end = forward_corr(logret["spy_ret"], logret["tlt_ret"], HORIZON)

    df = pd.concat(
        [
            logret,
            target,
            target_end,
            logret["spy_ret"].rolling(ROLL_CORR).corr(logret["tlt_ret"]).shift(1).rename(
                "corr60_lag1"
            ),
            deficit_gdp.shift(1).rename("deficit_gdp_lag1"),
            fedfunds_daily.shift(1).rename("fedfunds_lag1"),
            fedfunds_yoy.shift(1).rename("fedfunds_yoy_chg_lag1"),
        ],
        axis=1,
    )

    q70 = df["deficit_gdp_lag1"].expanding(min_periods=756).quantile(0.70).shift(1)
    q30 = df["deficit_gdp_lag1"].expanding(min_periods=756).quantile(0.30).shift(1)
    df["high_deficit_lag1"] = (df["deficit_gdp_lag1"] > q70).where(q70.notna())
    df["low_deficit_lag1"] = (df["deficit_gdp_lag1"] < q30).where(q30.notna())
    df["high_deficit_lag1"] = df["high_deficit_lag1"].astype(float)
    df["low_deficit_lag1"] = df["low_deficit_lag1"].astype(float)
    df["tightening_lag1"] = (df["fedfunds_yoy_chg_lag1"] > 0.75).astype(float)
    df["easing_lag1"] = (df["fedfunds_yoy_chg_lag1"] < -0.75).astype(float)
    df["high_deficit_x_tightening_lag1"] = (
        df["high_deficit_lag1"] * df["tightening_lag1"]
    )
    df["low_deficit_x_easing_lag1"] = df["low_deficit_lag1"] * df["easing_lag1"]
    df["target_positive_corr"] = (df[f"target_fwd_corr{HORIZON}"] > 0).astype(float)

    needed = [
        f"target_fwd_corr{HORIZON}",
        "target_end",
        "corr60_lag1",
        "deficit_gdp_lag1",
        "fedfunds_lag1",
        "fedfunds_yoy_chg_lag1",
        "high_deficit_lag1",
        "low_deficit_lag1",
        "tightening_lag1",
        "easing_lag1",
        "high_deficit_x_tightening_lag1",
        "low_deficit_x_easing_lag1",
    ]
    df = df.dropna(subset=needed).copy()
    return df


def split_data(df: pd.DataFrame) -> SplitData:
    train = df[(df.index < OOS_START) & (df["target_end"] < OOS_START)].copy()
    oos = df[df.index >= OOS_START].copy()
    if len(train) < 500 or len(oos) < 252:
        raise RuntimeError(f"Insufficient split sizes: train={len(train)}, oos={len(oos)}")
    return SplitData(train=train, oos=oos, full=df)


def fit_predict(train: pd.DataFrame, oos: pd.DataFrame) -> dict:
    ytr = train[f"target_fwd_corr{HORIZON}"].to_numpy()
    yte = oos[f"target_fwd_corr{HORIZON}"].to_numpy()

    baseline_cols = ["corr60_lag1"]
    augmented_cols = [
        "corr60_lag1",
        "deficit_gdp_lag1",
        "fedfunds_lag1",
        "fedfunds_yoy_chg_lag1",
        "high_deficit_lag1",
        "tightening_lag1",
        "high_deficit_x_tightening_lag1",
        "low_deficit_x_easing_lag1",
    ]

    baseline = LinearRegression()
    augmented = LinearRegression()
    baseline.fit(train[baseline_cols].to_numpy(), ytr)
    augmented.fit(train[augmented_cols].to_numpy(), ytr)

    base_pred = baseline.predict(oos[baseline_cols].to_numpy())
    aug_pred = augmented.predict(oos[augmented_cols].to_numpy())
    base_loss = (yte - base_pred) ** 2
    aug_loss = (yte - aug_pred) ** 2
    dm_t, dm_p = dm_test(aug_loss, base_loss, h=HORIZON)

    yclass = oos["target_positive_corr"].to_numpy(dtype=int)
    base_auc = roc_auc_score(yclass, base_pred) if len(np.unique(yclass)) > 1 else np.nan
    aug_auc = roc_auc_score(yclass, aug_pred) if len(np.unique(yclass)) > 1 else np.nan

    return {
        "baseline_cols": baseline_cols,
        "augmented_cols": augmented_cols,
        "baseline_pred": base_pred,
        "augmented_pred": aug_pred,
        "baseline_metrics": {
            "oos_r2": float(r2_score(yte, base_pred)),
            "oos_rmse": float(np.sqrt(mean_squared_error(yte, base_pred))),
            "positive_corr_auc": float(base_auc),
            "positive_corr_accuracy_pred_gt0": float(
                accuracy_score(yclass, base_pred > 0)
            ),
        },
        "augmented_metrics": {
            "oos_r2": float(r2_score(yte, aug_pred)),
            "oos_rmse": float(np.sqrt(mean_squared_error(yte, aug_pred))),
            "positive_corr_auc": float(aug_auc),
            "positive_corr_accuracy_pred_gt0": float(accuracy_score(yclass, aug_pred > 0)),
        },
        "dm_augmented_vs_baseline": {
            "loss": "squared_error_forward_corr60",
            "t_stat": float(dm_t),
            "p_value": float(dm_p),
            "direction_note": "negative t means augmented model has lower loss",
        },
        "ols_augmented_coefficients": dict(
            zip(augmented_cols, [float(v) for v in augmented.coef_])
        ),
        "ols_augmented_intercept": float(augmented.intercept_),
    }


def hac_lpm(df: pd.DataFrame, reg_col: str) -> dict:
    """HAC linear probability test for future positive correlation."""
    import statsmodels.api as sm

    sub = df[["target_positive_corr", reg_col]].dropna().copy()
    x = sm.add_constant(sub[reg_col].astype(float))
    y = sub["target_positive_corr"].astype(float)
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": HORIZON})
    coef = float(model.params[reg_col])
    pval = float(model.pvalues[reg_col])
    tval = float(model.tvalues[reg_col])
    group = sub.groupby(reg_col)["target_positive_corr"].agg(["mean", "count"])
    return {
        "regressor": reg_col,
        "coef_probability_points": coef,
        "hac_t": tval,
        "hac_p": pval,
        "group_rates": {
            str(k): {"mean": float(v["mean"]), "count": int(v["count"])}
            for k, v in group.iterrows()
        },
    }


def regime_descriptives(oos: pd.DataFrame) -> dict:
    out: dict[str, dict] = {}
    target = f"target_fwd_corr{HORIZON}"
    regimes = {
        "high_deficit_x_tightening": "high_deficit_x_tightening_lag1",
        "low_deficit_x_easing": "low_deficit_x_easing_lag1",
    }
    for name, col in regimes.items():
        mask = oos[col] > 0.5
        out[name] = {
            "n_days": int(mask.sum()),
            "share": float(mask.mean()),
            "mean_fwd_corr60": float(oos.loc[mask, target].mean()) if mask.any() else None,
            "positive_corr_rate": float(oos.loc[mask, "target_positive_corr"].mean())
            if mask.any()
            else None,
            "non_regime_mean_fwd_corr60": float(oos.loc[~mask, target].mean()),
            "non_regime_positive_corr_rate": float(
                oos.loc[~mask, "target_positive_corr"].mean()
            ),
            "hac_lpm_positive_corr": hac_lpm(oos, col),
        }
    return out


def max_drawdown(returns: pd.Series) -> float:
    nav = (1.0 + returns.fillna(0.0)).cumprod()
    dd = nav / nav.cummax() - 1.0
    return float(dd.min())


def annualized_sharpe(returns: pd.Series) -> float:
    mu = returns.mean() * 252.0
    vol = returns.std(ddof=1) * np.sqrt(252.0)
    return float(mu / vol) if vol > 0 else np.nan


def allocation_test(full: pd.DataFrame) -> dict:
    """Simple daily strategy using yesterday's high-deficit/tightening signal."""
    oos_ret = full.loc[full.index >= OOS_START, ["spy_ret", "tlt_ret"]].copy()
    signal = (
        full["high_deficit_x_tightening_lag1"]
        .shift(1)
        .reindex(oos_ret.index)
        .fillna(0.0)
        > 0.5
    )
    base = 0.60 * oos_ret["spy_ret"] + 0.40 * oos_ret["tlt_ret"]
    switched = np.where(signal, 0.60 * oos_ret["spy_ret"], base)
    switched = pd.Series(switched, index=oos_ret.index, name="cash_instead_of_tlt")

    dm_t, dm_p = strategy_dm_test(
        switched.to_numpy(), base.to_numpy(), h=1, loss_fn="negative_return"
    )
    return {
        "strategy": "If high_deficit_x_tightening_lag1 then move 40% TLT sleeve to cash for next trading day; otherwise 60/40.",
        "oos_start": OOS_START.date().isoformat(),
        "n_days": int(len(base)),
        "signal_days": int(signal.sum()),
        "signal_share": float(signal.mean()),
        "static_60_40": {
            "annual_return": float(base.mean() * 252.0),
            "annual_vol": float(base.std(ddof=1) * np.sqrt(252.0)),
            "sharpe": annualized_sharpe(base),
            "max_drawdown": max_drawdown(base),
        },
        "regime_switch": {
            "annual_return": float(switched.mean() * 252.0),
            "annual_vol": float(switched.std(ddof=1) * np.sqrt(252.0)),
            "sharpe": annualized_sharpe(switched),
            "max_drawdown": max_drawdown(switched),
        },
        "strategy_dm_vs_static": {
            "loss": "negative_return",
            "t_stat": float(dm_t),
            "p_value": float(dm_p),
            "direction_note": "negative t means regime_switch has higher average return/lower loss",
        },
    }


def make_plot(oos: pd.DataFrame, preds: dict, results: dict) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        print(f"[plot] matplotlib unavailable: {exc}")
        return

    target = oos[f"target_fwd_corr{HORIZON}"]
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)

    axes[0].plot(oos.index, target, color="black", lw=0.8, label="Actual fwd corr60")
    axes[0].plot(
        oos.index,
        preds["baseline_pred"],
        color="tab:blue",
        lw=0.8,
        label="Baseline corr60_lag1",
    )
    axes[0].plot(
        oos.index,
        preds["augmented_pred"],
        color="tab:red",
        lw=0.8,
        label="Augmented fiscal-monetary",
    )
    axes[0].axhline(0.0, color="gray", lw=0.8)
    axes[0].set_title("K1516 OOS: SPY/TLT forward 60-day correlation")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    axes[1].plot(oos.index, oos["deficit_gdp_lag1"], color="tab:purple", lw=0.8)
    axes[1].set_ylabel("Deficit/GDP")
    axes[1].grid(alpha=0.3)

    signal = oos["high_deficit_x_tightening_lag1"] > 0.5
    axes[2].fill_between(
        oos.index,
        0,
        1,
        where=signal.to_numpy(),
        color="tab:red",
        alpha=0.25,
        transform=axes[2].get_xaxis_transform(),
        label="High deficit x tightening",
    )
    axes[2].plot(oos.index, oos["fedfunds_lag1"], color="tab:green", lw=0.8)
    axes[2].set_ylabel("Fed funds")
    axes[2].legend(fontsize=8)
    axes[2].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(HERE / "k1516_plots.png", dpi=140)
    plt.close(fig)


def verdict_from_results(results: dict) -> str:
    pred = results["prediction"]
    reg = results["regime_descriptives"]["high_deficit_x_tightening"]
    strat = results["allocation"]

    dm_t = pred["dm_augmented_vs_baseline"]["t_stat"]
    dm_p = pred["dm_augmented_vs_baseline"]["p_value"]
    r2_gain = (
        pred["augmented_metrics"]["oos_r2"] - pred["baseline_metrics"]["oos_r2"]
    )
    lpm_t = reg["hac_lpm_positive_corr"]["hac_t"]
    sharpe_gain = (
        strat["regime_switch"]["sharpe"] - strat["static_60_40"]["sharpe"]
    )

    if r2_gain > 0 and dm_t < -3.0 and lpm_t > 3.0 and sharpe_gain > 0.15:
        return "PASS"
    if r2_gain > 0 and dm_p < 0.10 and lpm_t > 2.0 and sharpe_gain > 0.05:
        return "CONDITIONAL_PASS"
    return "NULL"


def main() -> int:
    print(f"[k1516] start {datetime.now().isoformat(timespec='seconds')}")
    df = build_dataset()
    split = split_data(df)
    print(
        f"[k1516] usable rows={len(df)} train={len(split.train)} "
        f"oos={len(split.oos)}"
    )
    print(
        f"[k1516] train {split.train.index.min().date()} -> "
        f"{split.train.index.max().date()} target_end<"
        f"{OOS_START.date()}"
    )
    print(
        f"[k1516] oos {split.oos.index.min().date()} -> "
        f"{split.oos.index.max().date()}"
    )

    preds = fit_predict(split.train, split.oos)

    results = {
        "experiment_id": "K1516",
        "title": "Fiscal-monetary regime predictability for SPY/TLT stock-bond correlation",
        "seed": SEED,
        "data": {
            "prices": "yfinance adjusted close: SPY, TLT",
            "macro": FRED_SERIES,
            "start": START,
            "end": END,
            "oos_start": OOS_START.date().isoformat(),
            "target": f"forward {HORIZON}-trading-day SPY/TLT return correlation",
            "n_usable": int(len(df)),
            "n_train": int(len(split.train)),
            "n_oos": int(len(split.oos)),
            "train_start": split.train.index.min().date().isoformat(),
            "train_end": split.train.index.max().date().isoformat(),
            "oos_start_actual": split.oos.index.min().date().isoformat(),
            "oos_end": split.oos.index.max().date().isoformat(),
        },
        "lookahead_defenses": [
            "FRED MTSDS133FMS monthly deficit uses 45-calendar-day release lag.",
            "FRED GDP quarterly level uses 120-calendar-day release lag from quarter start.",
            "FRED FEDFUNDS monthly rate uses 35-calendar-day release lag.",
            "All macro/regime features are shifted by one trading day before use.",
            "Forward-correlation target at t uses returns from t+1 through t+60.",
            "Training rows require target_end < OOS_START.",
            "Allocation signal is shifted again before applying to same-day returns.",
        ],
        "prediction": {
            k: v
            for k, v in preds.items()
            if k not in {"baseline_pred", "augmented_pred"}
        },
        "regime_descriptives": regime_descriptives(split.oos),
        "allocation": allocation_test(split.full),
        "references": [
            {
                "citation": "Li, Zha, Zhang, and Zhou, Does Fiscal Policy Matter for Stock-Bond Return Correlation?, NBER WP 27861.",
                "url": "https://www.nber.org/papers/w27861",
            },
            {
                "citation": "Campbell, Sunderam, and Viceira, Inflation Bets or Deflation Hedges?, Critical Finance Review 2017 / NBER WP 14701.",
                "url": "https://www.nber.org/papers/w14701",
            },
            {
                "citation": "CFA Institute Research Foundation, Macroeconomic Drivers of Stocks and Bonds, 2025.",
                "url": "https://rpc.cfainstitute.org/research/foundation/2025/macroeconomic-drivers",
            },
        ],
        "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    results["verdict"] = verdict_from_results(results)

    out_path = HERE / "k1516_results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    make_plot(split.oos, preds, results)

    print(f"[k1516] wrote {out_path}")
    print(f"[k1516] verdict={results['verdict']}")
    print(
        "[k1516] R2 base={:.4f} aug={:.4f} DM t={:.3f} p={:.4f}".format(
            results["prediction"]["baseline_metrics"]["oos_r2"],
            results["prediction"]["augmented_metrics"]["oos_r2"],
            results["prediction"]["dm_augmented_vs_baseline"]["t_stat"],
            results["prediction"]["dm_augmented_vs_baseline"]["p_value"],
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
