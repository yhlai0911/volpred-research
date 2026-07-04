"""
K1625 - Perpetual funding pressure and BTC/ETH high-RV regimes.

Question
--------
Do extreme crypto perpetual funding rates forecast next-day / next-5-day
realized-volatility regimes for BTC and ETH, and is the effect asymmetric for
long-crowding (positive funding) vs short-crowding (negative funding)?

Data
----
Binance USD-M futures public API:
  * /fapi/v1/fundingRate, 8-hour funding observations
  * /fapi/v1/klines, 1-day perpetual futures OHLCV

Research honesty controls
-------------------------
* Signal is explicitly lagged: all predictive features use funding.shift(1) or
  lagged return/RV controls.
* Forward 5-day RV target at date t is mean(rv[t]..rv[t+4]); predictor is
  funding observed on t-1.
* High-RV threshold is rolling and lagged. For h=5, the threshold uses labels
  whose target windows end before t.
* Inference uses HAC/Newey-West covariance with maxlags=h.
* Cross-asset pooled claims are not primary; BTC and ETH are reported separately.
* Seed fixed for bootstrap / any randomized step.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm


SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
FIGURES = HERE / "figures"
DATA.mkdir(exist_ok=True)
FIGURES.mkdir(exist_ok=True)

EXPERIMENT_ID = "k1625"
BASE_URL = "https://fapi.binance.com"
SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
START_DATE = "2019-09-01"
END_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
FUNDING_ROLL = 365
FUNDING_MIN = 180
RV_ROLL = 365
RV_MIN = 180
HORIZONS = [1, 5]
EPS = 1e-12
HARVEY_T = 3.0


def to_ms(date_str: str) -> int:
    return int(pd.Timestamp(date_str, tz="UTC").timestamp() * 1000)


def utc_date_from_ms(ms: pd.Series) -> pd.Series:
    return pd.to_datetime(ms, unit="ms", utc=True).dt.tz_convert(None).dt.date


def request_json(path: str, params: dict[str, Any], retries: int = 4) -> Any:
    url = f"{BASE_URL}{path}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code in {418, 429}:
                time.sleep(2.0 + attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"Binance API failed path={path} params={params}: {last_exc}")


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    cursor = start_ms
    while cursor <= end_ms:
        payload = request_json(
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000},
        )
        if not payload:
            break
        rows.extend(payload)
        last_time = int(payload[-1]["fundingTime"])
        next_cursor = last_time + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(payload) < 1000:
            break
        time.sleep(0.05)

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"No funding data returned for {symbol}")
    df["fundingTime"] = pd.to_numeric(df["fundingTime"], errors="coerce").astype("int64")
    df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    df["markPrice"] = pd.to_numeric(df.get("markPrice"), errors="coerce")
    df["date"] = utc_date_from_ms(df["fundingTime"])
    df = df.dropna(subset=["fundingRate"]).drop_duplicates("fundingTime").sort_values("fundingTime")
    return df


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows: list[list[Any]] = []
    cursor = start_ms
    while cursor <= end_ms:
        payload = request_json(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": "1d", "startTime": cursor, "endTime": end_ms, "limit": 1500},
        )
        if not payload:
            break
        rows.extend(payload)
        last_open = int(payload[-1][0])
        next_cursor = last_open + 24 * 60 * 60 * 1000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(payload) < 1500:
            break
        time.sleep(0.05)

    if not rows:
        raise RuntimeError(f"No kline data returned for {symbol}")
    cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "num_trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce").astype("int64")
    df["date"] = utc_date_from_ms(df["open_time"])
    df = df.dropna(subset=["close"]).drop_duplicates("open_time").sort_values("open_time")
    return df


def forward_mean(s: pd.Series, h: int) -> pd.Series:
    shifted = pd.concat([s.shift(-i) for i in range(h)], axis=1)
    valid = shifted.notna().sum(axis=1) == h
    out = shifted.mean(axis=1)
    out[~valid] = np.nan
    return out


def build_panel(asset: str, symbol: str, start_ms: int, end_ms: int, force_refresh: bool = False) -> pd.DataFrame:
    funding_path = DATA / f"{symbol}_funding.csv"
    kline_path = DATA / f"{symbol}_klines_1d.csv"

    if force_refresh or not funding_path.exists():
        funding = fetch_funding(symbol, start_ms, end_ms)
        funding.to_csv(funding_path, index=False)
    else:
        funding = pd.read_csv(funding_path)
        funding["date"] = pd.to_datetime(funding["date"]).dt.date

    if force_refresh or not kline_path.exists():
        klines = fetch_klines(symbol, start_ms, end_ms)
        klines.to_csv(kline_path, index=False)
    else:
        klines = pd.read_csv(kline_path)
        klines["date"] = pd.to_datetime(klines["date"]).dt.date

    fd = (
        funding.groupby("date")
        .agg(
            funding_mean=("fundingRate", "mean"),
            funding_sum=("fundingRate", "sum"),
            funding_min=("fundingRate", "min"),
            funding_max=("fundingRate", "max"),
            funding_abs_mean=("fundingRate", lambda x: float(np.mean(np.abs(x)))),
            funding_count=("fundingRate", "size"),
        )
        .reset_index()
    )
    px = klines[["date", "open", "high", "low", "close", "volume", "quote_volume"]].copy()
    px = px.sort_values("date")
    px["ret"] = np.log(px["close"] / px["close"].shift(1))
    px["rv1"] = px["ret"] ** 2
    px["range_var"] = np.log(px["high"] / px["low"]) ** 2

    panel = px.merge(fd, on="date", how="left").sort_values("date")
    panel["asset"] = asset
    panel["date"] = pd.to_datetime(panel["date"])

    # Explicit lagged signal: information through t-1 predicts return/RV at t.
    lag_funding = panel["funding_mean"].shift(1)
    panel["funding_lag1"] = lag_funding
    panel["funding_abs_lag1"] = lag_funding.abs()
    panel["funding_z_lag1"] = (
        (lag_funding - lag_funding.rolling(FUNDING_ROLL, min_periods=FUNDING_MIN).mean())
        / lag_funding.rolling(FUNDING_ROLL, min_periods=FUNDING_MIN).std(ddof=0)
    )
    panel["funding_abs_z_lag1"] = (
        (
            lag_funding.abs()
            - lag_funding.abs().rolling(FUNDING_ROLL, min_periods=FUNDING_MIN).mean()
        )
        / lag_funding.abs().rolling(FUNDING_ROLL, min_periods=FUNDING_MIN).std(ddof=0)
    )
    panel["funding_q90_lag1"] = lag_funding.rolling(FUNDING_ROLL, min_periods=FUNDING_MIN).quantile(0.90)
    panel["funding_q10_lag1"] = lag_funding.rolling(FUNDING_ROLL, min_periods=FUNDING_MIN).quantile(0.10)
    panel["funding_abs_q90_lag1"] = (
        lag_funding.abs().rolling(FUNDING_ROLL, min_periods=FUNDING_MIN).quantile(0.90)
    )
    panel["pos_extreme_lag1"] = (panel["funding_lag1"] >= panel["funding_q90_lag1"]).astype(float)
    panel["neg_extreme_lag1"] = (panel["funding_lag1"] <= panel["funding_q10_lag1"]).astype(float)
    panel["abs_extreme_lag1"] = (panel["funding_abs_lag1"] >= panel["funding_abs_q90_lag1"]).astype(float)
    for col in ["pos_extreme_lag1", "neg_extreme_lag1", "abs_extreme_lag1"]:
        panel.loc[panel["funding_q90_lag1"].isna(), col] = np.nan

    panel["rv1_lag1"] = panel["rv1"].shift(1)
    panel["abs_ret_lag1"] = panel["ret"].abs().shift(1)
    panel["trailing_rv5_lag1"] = panel["rv1"].rolling(5, min_periods=5).mean().shift(1)
    panel["log_trailing_rv5_lag1"] = np.log(panel["trailing_rv5_lag1"] + EPS)

    for h in HORIZONS:
        panel[f"rv_fwd{h}"] = forward_mean(panel["rv1"], h)
        panel[f"log_rv_fwd{h}"] = np.log(panel[f"rv_fwd{h}"] + EPS)
        if h == 1:
            threshold = panel["rv1"].shift(1).rolling(RV_ROLL, min_periods=RV_MIN).quantile(0.80)
        else:
            past_labels = panel[f"rv_fwd{h}"].shift(h)
            threshold = past_labels.rolling(RV_ROLL, min_periods=RV_MIN).quantile(0.80)
        panel[f"high_rv{h}_threshold"] = threshold
        panel[f"high_rv{h}"] = (panel[f"rv_fwd{h}"] >= threshold).astype(float)
        panel.loc[threshold.isna() | panel[f"rv_fwd{h}"].isna(), f"high_rv{h}"] = np.nan

    return panel


def fit_hac_ols(df: pd.DataFrame, y_col: str, x_cols: list[str], maxlags: int) -> dict[str, Any]:
    d = df[[y_col] + x_cols].replace([np.inf, -np.inf], np.nan).dropna()
    if len(d) < 250:
        return {"n": int(len(d)), "error": "insufficient observations"}
    y = d[y_col].astype(float)
    x = sm.add_constant(d[x_cols].astype(float), has_constant="add")
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    terms = {}
    for name in x.columns:
        terms[name] = {
            "coef": float(model.params[name]),
            "se_hac": float(model.bse[name]),
            "t": float(model.tvalues[name]),
            "p": float(model.pvalues[name]),
        }
    contrast = np.zeros(len(x.columns))
    if "pos_extreme_lag1" in x.columns and "neg_extreme_lag1" in x.columns:
        contrast[list(x.columns).index("pos_extreme_lag1")] = 1.0
        contrast[list(x.columns).index("neg_extreme_lag1")] = -1.0
        test = model.t_test(contrast)
        asym = {
            "coef_pos_minus_neg": float(test.effect[0]),
            "t": float(test.tvalue[0][0]),
            "p": float(test.pvalue),
        }
    else:
        asym = {"coef_pos_minus_neg": np.nan, "t": np.nan, "p": np.nan}
    return {
        "n": int(len(d)),
        "r2": float(model.rsquared),
        "y_mean": float(y.mean()),
        "y_std": float(y.std(ddof=1)),
        "terms": terms,
        "asymmetry_pos_minus_neg": asym,
    }


def conditional_rates(df: pd.DataFrame, h: int) -> dict[str, Any]:
    cols = [f"high_rv{h}", f"rv_fwd{h}", "pos_extreme_lag1", "neg_extreme_lag1", "abs_extreme_lag1"]
    d = df[cols].dropna()
    out: dict[str, Any] = {"n": int(len(d))}
    if d.empty:
        return out
    base_rate = float(d[f"high_rv{h}"].mean())
    out["base_high_rv_rate"] = base_rate
    for label, mask in [
        ("positive_funding_extreme", d["pos_extreme_lag1"] == 1.0),
        ("negative_funding_extreme", d["neg_extreme_lag1"] == 1.0),
        ("absolute_funding_extreme", d["abs_extreme_lag1"] == 1.0),
        ("non_extreme", (d["pos_extreme_lag1"] == 0.0) & (d["neg_extreme_lag1"] == 0.0)),
    ]:
        sub = d[mask]
        out[label] = {
            "n": int(len(sub)),
            "high_rv_rate": float(sub[f"high_rv{h}"].mean()) if len(sub) else np.nan,
            "mean_rv": float(sub[f"rv_fwd{h}"].mean()) if len(sub) else np.nan,
            "rate_minus_base": float(sub[f"high_rv{h}"].mean() - base_rate) if len(sub) else np.nan,
        }
    return out


def summarize_asset(asset: str, panel: pd.DataFrame) -> dict[str, Any]:
    valid = panel.dropna(subset=["funding_mean", "rv1"])
    x_cols = [
        "funding_z_lag1",
        "pos_extreme_lag1",
        "neg_extreme_lag1",
        "log_trailing_rv5_lag1",
        "abs_ret_lag1",
    ]
    regressions: dict[str, Any] = {}
    conditionals: dict[str, Any] = {}
    for h in HORIZONS:
        regressions[f"log_rv_fwd{h}"] = fit_hac_ols(panel, f"log_rv_fwd{h}", x_cols, maxlags=h)
        regressions[f"high_rv{h}_lpm"] = fit_hac_ols(panel, f"high_rv{h}", x_cols, maxlags=h)
        conditionals[f"h{h}"] = conditional_rates(panel, h)

    return {
        "symbol": SYMBOLS[asset],
        "sample_start": str(valid["date"].min().date()) if len(valid) else None,
        "sample_end": str(valid["date"].max().date()) if len(valid) else None,
        "n_daily_rows_with_funding_and_rv": int(len(valid)),
        "funding_observations": int(panel["funding_count"].sum(skipna=True)),
        "funding_days": int(panel["funding_mean"].notna().sum()),
        "funding_mean": float(panel["funding_mean"].mean(skipna=True)),
        "funding_std": float(panel["funding_mean"].std(skipna=True)),
        "funding_p10": float(panel["funding_mean"].quantile(0.10)),
        "funding_p90": float(panel["funding_mean"].quantile(0.90)),
        "annualized_close_to_close_vol_pct": float(math.sqrt(365.0 * panel["rv1"].mean(skipna=True)) * 100.0),
        "regressions": regressions,
        "conditional_high_rv_rates": conditionals,
    }


def collect_primary_tstats(per_asset: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset, res in per_asset.items():
        for model_name, reg in res["regressions"].items():
            if reg.get("error"):
                continue
            horizon = 5 if "fwd5" in model_name or "rv5" in model_name else 1
            is_regime = "high_rv" in model_name
            for term in ["funding_z_lag1", "pos_extreme_lag1", "neg_extreme_lag1"]:
                stat = reg["terms"].get(term)
                if stat:
                    rows.append({
                        "asset": asset,
                        "model": model_name,
                        "horizon": horizon,
                        "is_regime_model": is_regime,
                        "term": term,
                        "t": stat["t"],
                        "p": stat["p"],
                        "coef": stat["coef"],
                    })
            asym = reg.get("asymmetry_pos_minus_neg", {})
            rows.append({
                "asset": asset,
                "model": model_name,
                "horizon": horizon,
                "is_regime_model": is_regime,
                "term": "asymmetry_pos_minus_neg",
                "t": asym.get("t", np.nan),
                "p": asym.get("p", np.nan),
                "coef": asym.get("coef_pos_minus_neg", np.nan),
            })
    return rows


def make_plots(panels: dict[str, pd.DataFrame], per_asset: dict[str, Any]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=False)
    for ax, asset in zip(axes, ["BTC", "ETH"]):
        d = panels[asset].dropna(subset=["funding_lag1", "rv_fwd5"]).copy()
        ax2 = ax.twinx()
        ax.plot(d["date"], d["funding_lag1"] * 100.0, color="#2b6cb0", lw=0.8, label="lagged funding mean (%)")
        ax2.plot(d["date"], np.sqrt(d["rv_fwd5"] * 365.0) * 100.0, color="#c53030", lw=0.7, alpha=0.6, label="forward 5d ann. RV")
        ax.axhline(0, color="black", lw=0.6)
        ax.set_title(f"{asset}: lagged daily funding vs forward 5d realized volatility")
        ax.set_ylabel("funding %")
        ax2.set_ylabel("ann. RV %")
    fig.tight_layout()
    fig.savefig(FIGURES / "fig1_funding_vs_forward_rv.png", dpi=140)
    plt.close(fig)

    rows = []
    for asset, res in per_asset.items():
        reg = res["regressions"].get("high_rv5_lpm", {})
        if reg.get("error"):
            continue
        for term, label in [
            ("funding_z_lag1", "funding z"),
            ("pos_extreme_lag1", "pos extreme"),
            ("neg_extreme_lag1", "neg extreme"),
        ]:
            rows.append({"asset": asset, "term": label, "t": reg["terms"][term]["t"]})
        rows.append({"asset": asset, "term": "pos-neg", "t": reg["asymmetry_pos_minus_neg"]["t"]})
    if rows:
        df = pd.DataFrame(rows)
        fig, ax = plt.subplots(figsize=(9, 5))
        labels = [f"{r.asset}\n{r.term}" for r in df.itertuples()]
        colors = ["#2a9d8f" if v > 0 else "#d62828" for v in df["t"]]
        ax.bar(np.arange(len(df)), df["t"], color=colors)
        ax.axhline(3.0, color="black", ls="--", lw=0.8)
        ax.axhline(-3.0, color="black", ls="--", lw=0.8)
        ax.axhline(0, color="black", lw=0.6)
        ax.set_xticks(np.arange(len(df)))
        ax.set_xticklabels(labels, rotation=0, fontsize=8)
        ax.set_ylabel("HAC t-stat")
        ax.set_title("K1625: high-RV(5d) LPM funding coefficients")
        fig.tight_layout()
        fig.savefig(FIGURES / "fig2_high_rv5_tstats.png", dpi=140)
        plt.close(fig)

    rows = []
    for asset, res in per_asset.items():
        cond = res["conditional_high_rv_rates"]["h5"]
        for key, label in [
            ("non_extreme", "non-extreme"),
            ("positive_funding_extreme", "positive"),
            ("negative_funding_extreme", "negative"),
            ("absolute_funding_extreme", "abs"),
        ]:
            item = cond.get(key, {})
            rows.append({"asset": asset, "bucket": label, "rate": item.get("high_rv_rate", np.nan)})
    df = pd.DataFrame(rows).dropna()
    if not df.empty:
        fig, ax = plt.subplots(figsize=(8, 5))
        width = 0.35
        buckets = ["non-extreme", "positive", "negative", "abs"]
        x = np.arange(len(buckets))
        for i, asset in enumerate(["BTC", "ETH"]):
            vals = [df[(df["asset"] == asset) & (df["bucket"] == b)]["rate"].mean() for b in buckets]
            ax.bar(x + (i - 0.5) * width, vals, width=width, label=asset)
        ax.set_xticks(x)
        ax.set_xticklabels(buckets)
        ax.set_ylabel("High forward-5d RV rate")
        ax.set_title("K1625: high-RV rate conditional on lagged funding bucket")
        ax.legend()
        fig.tight_layout()
        fig.savefig(FIGURES / "fig3_conditional_high_rv_rates.png", dpi=140)
        plt.close(fig)


def main(force_refresh: bool = False) -> None:
    start_ms = to_ms(START_DATE)
    end_ms = to_ms(END_DATE)
    panels = {
        asset: build_panel(asset, symbol, start_ms, end_ms, force_refresh=force_refresh)
        for asset, symbol in SYMBOLS.items()
    }
    for asset, panel in panels.items():
        panel.to_csv(DATA / f"{asset}_analysis_panel.csv", index=False)

    per_asset = {asset: summarize_asset(asset, panel) for asset, panel in panels.items()}
    primary_tstats = collect_primary_tstats(per_asset)
    primary_df = pd.DataFrame(primary_tstats)
    if primary_df.empty:
        n_abs_t3 = 0
        n_regime_h5_abs_t3 = 0
        max_abs_t = np.nan
        max_row = {}
    else:
        primary_df["abs_t"] = primary_df["t"].abs()
        n_abs_t3 = int((primary_df["abs_t"] >= HARVEY_T).sum())
        regime_h5 = primary_df[(primary_df["is_regime_model"]) & (primary_df["horizon"] == 5)]
        n_regime_h5_abs_t3 = int((regime_h5["abs_t"] >= HARVEY_T).sum())
        max_idx = primary_df["abs_t"].idxmax()
        max_abs_t = float(primary_df.loc[max_idx, "abs_t"])
        max_row = primary_df.loc[max_idx].replace({np.nan: None}).to_dict()

    # Conservative pre-registered gate: the task is about high-RV regimes, so a
    # publishable signal needs h=5 high-RV regime evidence at Harvey strength.
    if n_regime_h5_abs_t3 >= 2:
        verdict = "SIGNAL_CANDIDATE"
    elif n_regime_h5_abs_t3 == 1:
        verdict = "MIXED_WEAK_SINGLE_CELL"
    else:
        verdict = "NULL"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "config": {
            "data_source": "Binance USD-M futures public API (/fapi/v1/fundingRate, /fapi/v1/klines)",
            "symbols": SYMBOLS,
            "start_date_requested": START_DATE,
            "end_date_requested": END_DATE,
            "funding_roll_days": FUNDING_ROLL,
            "funding_min_days": FUNDING_MIN,
            "rv_threshold_roll_days": RV_ROLL,
            "rv_threshold_min_days": RV_MIN,
            "horizons": HORIZONS,
            "harvey_abs_t_threshold": HARVEY_T,
            "lookahead_control": "features use funding.shift(1); h=5 high-RV threshold uses labels shifted by h",
        },
        "data_provenance": {
            asset: {
                "funding_csv": f"data/{SYMBOLS[asset]}_funding.csv",
                "klines_csv": f"data/{SYMBOLS[asset]}_klines_1d.csv",
                "analysis_panel_csv": f"data/{asset}_analysis_panel.csv",
            }
            for asset in SYMBOLS
        },
        "per_asset": per_asset,
        "primary_tstats": primary_tstats,
        "verdict": verdict,
        "verdict_basis": {
            "primary_scope": "h=5 high-RV regime LPM terms and positive-minus-negative asymmetry",
            "n_all_primary_abs_t_ge_3": n_abs_t3,
            "n_h5_regime_abs_t_ge_3": n_regime_h5_abs_t3,
            "max_abs_t_any_test": max_abs_t,
            "max_abs_t_row": max_row,
            "interpretation_rule": (
                "SIGNAL_CANDIDATE requires at least two h=5 high-RV regime cells at |t|>=3; "
                "one cell is MIXED_WEAK_SINGLE_CELL; zero is NULL."
            ),
        },
    }
    (HERE / "k1625_results.json").write_text(json.dumps(results, indent=2, allow_nan=False), encoding="utf-8")
    make_plots(panels, per_asset)
    print(json.dumps({
        "experiment_id": EXPERIMENT_ID,
        "verdict": verdict,
        "n_h5_regime_abs_t_ge_3": n_regime_h5_abs_t3,
        "max_abs_t_any_test": max_abs_t,
        "output": str(HERE / "k1625_results.json"),
    }, indent=2))


if __name__ == "__main__":
    main(force_refresh=False)
