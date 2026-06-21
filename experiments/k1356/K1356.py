"""K1356: Oil-market news attention as an OOS volatility feature.

Question
--------
Does a free GDELT oil-news attention proxy add one-day-ahead volatility
forecasting information for crude oil and energy ETFs after controlling for
price-based HAR features and a public EIA crude-inventory control?

Lookahead discipline
--------------------
* Target at row t is RV[t+1].
* HAR features use RV through t.
* GDELT daily news attention is treated conservatively as available only after
  the day closes: news_signal[t] = news_z[t-1].
* Weekly EIA inventory changes are shifted +5 business days from the Friday
  period date, forward-filled to daily, then inventory_signal[t] =
  inventory_z[t-1].

Outputs
-------
* K1356_results.json
* K1356_news_oil_vol.png
* data/gdelt_oil_timeline_raw.json
* data/gdelt_oil_daily.csv
* data/eia_crude_stocks.csv
* data/yfinance_ohlcv.csv
* data/model_panel.csv
"""

from __future__ import annotations

import json
import io
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


SEED = 42
EXP_ID = "K1356"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
RESULTS_PATH = EXP_DIR / f"{EXP_ID}_results.json"
FIG_PATH = EXP_DIR / f"{EXP_ID}_news_oil_vol.png"

START = "2017-01-01"  # GDELT DOC API reliable public window starts in 2017
OOS_START = "2020-01-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")
TICKERS = ["CL=F", "USO", "XLE", "XOP"]
REFIT_EVERY = 252
INIT_TRAIN_MIN = 504

GDELT_QUERY = '("crude oil" OR "oil market" OR OPEC OR petroleum OR "oil prices" OR "energy market")'
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
EIA_WCESTUS1_XLS = "https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    features: list[str]


MODELS = [
    ModelSpec("HAR", ["log_rv_d", "log_rv_w", "log_rv_m"]),
    ModelSpec("HAR_INV", ["log_rv_d", "log_rv_w", "log_rv_m", "inventory_signal"]),
    ModelSpec("HAR_INV_NEWS", ["log_rv_d", "log_rv_w", "log_rv_m", "inventory_signal", "news_signal"]),
    ModelSpec(
        "HAR_INV_NEWS_ABS",
        ["log_rv_d", "log_rv_w", "log_rv_m", "inventory_signal", "news_abs_signal"],
    ),
]


def _save_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _gdelt_params(start: str, end: str) -> dict[str, str]:
    return {
        "query": GDELT_QUERY,
        "mode": "timelinevolraw",
        "format": "json",
        "STARTDATETIME": start,
        "ENDDATETIME": end,
        "TIMELINESMOOTH": "0",
    }


def fetch_gdelt_timeline() -> dict:
    """Fetch or load GDELT DOC TimelineVolRaw article counts."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "gdelt_oil_timeline_raw.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    start_dt = START.replace("-", "") + "000000"
    end_dt = END.replace("-", "") + "000000"
    params = _gdelt_params(start_dt, end_dt)
    last_text = ""
    for attempt in range(4):
        if attempt:
            time.sleep(6 * attempt)
        response = requests.get(GDELT_URL, params=params, timeout=90)
        last_text = response.text[:500]
        if response.status_code == 429:
            continue
        response.raise_for_status()
        payload = response.json()
        _save_json(cache, payload)
        return payload
    raise RuntimeError(f"GDELT fetch failed after retries; last response: {last_text}")


def parse_gdelt_daily(payload: dict) -> pd.DataFrame:
    timeline = payload.get("timeline") or []
    if not timeline:
        raise ValueError("GDELT payload has no timeline")
    data = timeline[0].get("data") or []
    df = pd.DataFrame(data)
    if df.empty:
        raise ValueError("GDELT timeline has no rows")
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None).dt.normalize()
    df["news_count"] = pd.to_numeric(df["value"], errors="coerce")
    df["gdelt_total"] = pd.to_numeric(df["norm"], errors="coerce")
    df = df[["date", "news_count", "gdelt_total"]].dropna().sort_values("date")
    df["news_share"] = df["news_count"] / df["gdelt_total"].replace(0, np.nan)
    df["log_news_share"] = np.log(df["news_share"].clip(lower=1e-12))
    roll_mean = df["log_news_share"].shift(1).rolling(252, min_periods=60).mean()
    roll_std = df["log_news_share"].shift(1).rolling(252, min_periods=60).std()
    df["news_z"] = (df["log_news_share"] - roll_mean) / roll_std
    df["news_z"] = df["news_z"].replace([np.inf, -np.inf], np.nan).clip(-8, 8)
    out = df.set_index("date")
    out.to_csv(DATA_DIR / "gdelt_oil_daily.csv")
    return out


def load_eia_inventory_signal(daily_index: pd.DatetimeIndex) -> pd.Series:
    cache = DATA_DIR / "eia_crude_stocks.csv"
    if cache.exists():
        raw = pd.read_csv(cache)
    else:
        response = requests.get(EIA_WCESTUS1_XLS, timeout=60)
        response.raise_for_status()
        xls = pd.ExcelFile(io.BytesIO(response.content))
        raw_xls = pd.read_excel(xls, sheet_name="Data 1", header=None)
        raw = raw_xls.iloc[3:].copy()
        raw.columns = ["DATE", "WCESTUS1"]
        raw.to_csv(cache, index=False)
    raw["DATE"] = pd.to_datetime(raw["DATE"], errors="coerce")
    raw["WCESTUS1"] = pd.to_numeric(raw["WCESTUS1"], errors="coerce")
    s = raw.dropna().set_index("DATE")["WCESTUS1"].sort_index()
    delta = s.diff()
    roll_mean = delta.shift(1).rolling(52, min_periods=26).mean()
    roll_std = delta.shift(1).rolling(52, min_periods=26).std()
    z = ((delta - roll_mean) / roll_std).replace([np.inf, -np.inf], np.nan).clip(-8, 8)

    # Period date is Friday. Use following Friday as conservative availability.
    avail = pd.Series(z.values, index=z.index + pd.tseries.offsets.BDay(5)).sort_index()
    daily = avail.reindex(avail.index.union(daily_index)).sort_index().ffill().reindex(daily_index)
    return daily


def load_yfinance_ohlcv() -> pd.DataFrame:
    cache = DATA_DIR / "yfinance_ohlcv.csv"
    if cache.exists():
        df = pd.read_csv(cache, header=[0, 1], index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        return df
    df = yf.download(TICKERS, start=START, end=END, auto_adjust=False, progress=False, group_by="ticker")
    if not isinstance(df.columns, pd.MultiIndex):
        raise ValueError("Expected yfinance multi-index columns")
    df = df.sort_index()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.to_csv(cache)
    return df


def garman_klass_rv(asset: pd.DataFrame) -> pd.Series:
    op = asset["Open"].astype(float)
    hi = asset["High"].astype(float)
    lo = asset["Low"].astype(float)
    cl = asset["Close"].astype(float)
    valid = (op > 0) & (hi > 0) & (lo > 0) & (cl > 0)
    rv = pd.Series(np.nan, index=asset.index, dtype=float)
    rv.loc[valid] = (
        0.5 * np.log(hi.loc[valid] / lo.loc[valid]) ** 2
        - (2 * math.log(2) - 1) * np.log(cl.loc[valid] / op.loc[valid]) ** 2
    )
    return rv.clip(lower=1e-10)


def build_panel() -> pd.DataFrame:
    gdelt = parse_gdelt_daily(fetch_gdelt_timeline())
    yfin = load_yfinance_ohlcv()
    all_dates = yfin.index
    news = gdelt["news_z"].reindex(gdelt.index.union(all_dates)).sort_index().ffill().reindex(all_dates)
    inventory = load_eia_inventory_signal(all_dates)

    rows = []
    for ticker in TICKERS:
        asset = yfin[ticker].dropna(subset=["Open", "High", "Low", "Close"]).copy()
        if asset.empty:
            continue
        rv = garman_klass_rv(asset)
        log_rv = np.log(rv)
        frame = pd.DataFrame(index=asset.index)
        frame["ticker"] = ticker
        frame["rv"] = rv
        frame["log_rv"] = log_rv
        frame["log_rv_d"] = log_rv
        frame["log_rv_w"] = log_rv.rolling(5).mean()
        frame["log_rv_m"] = log_rv.rolling(22).mean()
        frame["target_log_rv"] = log_rv.shift(-1)
        frame["target_rv"] = rv.shift(-1)
        frame["news_z"] = news.reindex(asset.index)
        frame["inventory_z"] = inventory.reindex(asset.index)
        frame["news_signal"] = frame["news_z"].shift(1)
        frame["news_abs_signal"] = frame["news_z"].abs().shift(1)
        frame["inventory_signal"] = frame["inventory_z"].shift(1)
        rows.append(frame)
    panel = pd.concat(rows).reset_index().rename(columns={"index": "date", "Date": "date"})
    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel.to_csv(DATA_DIR / "model_panel.csv", index=False)
    return panel


def fit_ols(train: pd.DataFrame, features: list[str]) -> np.ndarray:
    x = train[features].to_numpy(dtype=float)
    y = train["target_log_rv"].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return beta


def predict_ols(beta: np.ndarray, row: pd.Series, features: list[str]) -> float:
    x = np.array([1.0] + [float(row[f]) for f in features])
    return float(x @ beta)


def expanding_predictions(asset_df: pd.DataFrame, spec: ModelSpec) -> pd.Series:
    df = asset_df.sort_values("date").reset_index(drop=True)
    preds = pd.Series(np.nan, index=df.index, dtype=float)
    feature_cols = spec.features
    last_fit = -10**9
    beta = None
    first_oos_idx = int(df.index[df["date"] >= pd.Timestamp(OOS_START)][0])
    for i in range(first_oos_idx, len(df)):
        if i < INIT_TRAIN_MIN:
            continue
        if beta is None or i - last_fit >= REFIT_EVERY:
            train = df.iloc[:i].dropna(subset=feature_cols + ["target_log_rv"])
            if len(train) < INIT_TRAIN_MIN:
                continue
            beta = fit_ols(train, feature_cols)
            last_fit = i
        row = df.iloc[i]
        if row[feature_cols].isna().any() or pd.isna(row["target_log_rv"]):
            continue
        preds.iloc[i] = predict_ols(beta, row, feature_cols)
    preds.index = df["date"]
    return preds


def evaluate_asset(asset_df: pd.DataFrame) -> dict:
    ticker = str(asset_df["ticker"].iloc[0])
    df = asset_df.sort_values("date").reset_index(drop=True)
    pred_map: dict[str, pd.Series] = {}
    for spec in MODELS:
        pred_map[spec.name] = expanding_predictions(df, spec)
    pred_df = pd.DataFrame(pred_map)
    pred_df["date"] = pred_df.index
    actual = df.set_index("date")[["target_log_rv", "target_rv"]].join(pred_df.drop(columns=["date"]))
    actual = actual.dropna(subset=["target_log_rv", "target_rv", "HAR_INV", "HAR_INV_NEWS"])

    metrics = {}
    losses = {}
    for spec in MODELS:
        valid = actual.dropna(subset=[spec.name])
        if valid.empty:
            continue
        pred_var = np.exp(valid[spec.name].to_numpy(dtype=float)).clip(1e-10, 10.0)
        obs_var = valid["target_rv"].to_numpy(dtype=float).clip(1e-10, 10.0)
        ql = qlike_pointwise(obs_var, pred_var)
        mse = (valid["target_log_rv"].to_numpy(dtype=float) - valid[spec.name].to_numpy(dtype=float)) ** 2
        metrics[spec.name] = {
            "n_oos": int(len(valid)),
            "qlike": float(np.mean(ql)),
            "mse_log": float(np.mean(mse)),
        }
        losses[spec.name] = pd.DataFrame({"date": valid.index, "qlike": ql, "mse_log": mse})

    comparisons = {}
    for challenger in ("HAR_INV", "HAR_INV_NEWS", "HAR_INV_NEWS_ABS"):
        common = losses[challenger].merge(losses["HAR_INV"], on="date", suffixes=("_challenger", "_base"))
        q_t, q_p = dm_test(common["qlike_challenger"].to_numpy(), common["qlike_base"].to_numpy(), h=1)
        m_t, m_p = dm_test(common["mse_log_challenger"].to_numpy(), common["mse_log_base"].to_numpy(), h=1)
        base_q = metrics["HAR_INV"]["qlike"]
        ch_q = metrics[challenger]["qlike"]
        comparisons[f"{challenger}_vs_HAR_INV"] = {
            "qlike_improvement_pct": float((base_q - ch_q) / abs(base_q) * 100),
            "mse_log_improvement_pct": float(
                (metrics["HAR_INV"]["mse_log"] - metrics[challenger]["mse_log"])
                / abs(metrics["HAR_INV"]["mse_log"])
                * 100
            ),
            "dm_qlike_t": float(q_t),
            "dm_qlike_p": float(q_p),
            "dm_mse_t": float(m_t),
            "dm_mse_p": float(m_p),
        }

    return {"ticker": ticker, "metrics": metrics, "comparisons": comparisons, "losses": losses}


def pooled_dm(asset_results: list[dict], challenger: str, base: str = "HAR_INV") -> dict:
    pieces = []
    for res in asset_results:
        ticker = res["ticker"]
        ch = res["losses"][challenger][["date", "qlike"]].rename(columns={"qlike": "ch"})
        ba = res["losses"][base][["date", "qlike"]].rename(columns={"qlike": "base"})
        merged = ch.merge(ba, on="date")
        merged["ticker"] = ticker
        merged["diff"] = merged["ch"] - merged["base"]
        pieces.append(merged)
    panel = pd.concat(pieces, ignore_index=True)
    by_date = panel.groupby("date", as_index=True)["diff"].mean().dropna()
    t_stat, p_val = dm_test(by_date.to_numpy(), np.zeros(len(by_date)), h=1)
    return {
        "challenger": challenger,
        "base": base,
        "n_dates": int(len(by_date)),
        "mean_loss_diff": float(by_date.mean()),
        "dm_t": float(t_stat),
        "dm_p": float(p_val),
        "method": "date-clustered cross-asset mean QLIKE loss differential",
    }


def make_figure(panel: pd.DataFrame, results: dict) -> None:
    daily = panel.drop_duplicates("date").sort_values("date")
    per_asset = results["per_asset"]
    labels = [x["ticker"] for x in per_asset]
    imp = [x["comparisons"]["HAR_INV_NEWS_vs_HAR_INV"]["qlike_improvement_pct"] for x in per_asset]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    ax = axes[0]
    ax.plot(daily["date"], daily["news_z"], lw=0.8, color="#38598b", alpha=0.8)
    ax.axhline(0, color="#555555", lw=0.8)
    ax.axhline(2, color="#c44536", lw=0.8, ls="--")
    ax.axhline(-2, color="#c44536", lw=0.8, ls="--")
    ax.set_title("GDELT oil-market news attention z-score")
    ax.set_ylabel("z-score")

    ax = axes[1]
    colors = ["#2a9d8f" if v > 0 else "#d1495b" for v in imp]
    ax.bar(labels, imp, color=colors)
    ax.axhline(0, color="#333333", lw=0.8)
    ax.set_title("OOS QLIKE improvement: HAR+inventory+news vs HAR+inventory")
    ax.set_ylabel("Improvement (%)")
    for i, v in enumerate(imp):
        ax.text(i, v + (0.05 if v >= 0 else -0.05), f"{v:.2f}%", ha="center", va="bottom" if v >= 0 else "top")
    fig.savefig(FIG_PATH, dpi=140)
    plt.close(fig)


def verdict(results: dict) -> dict:
    pooled = results["pooled"]["HAR_INV_NEWS_vs_HAR_INV"]
    per = results["per_asset"]
    positive = sum(
        1
        for item in per
        if item["comparisons"]["HAR_INV_NEWS_vs_HAR_INV"]["qlike_improvement_pct"] > 0
    )
    if pooled["dm_t"] < -3.0 and positive >= 3:
        label = "CONDITIONAL_PASS_PROXY"
        summary = "news attention improves pooled QLIKE under Harvey-strength date-clustered DM"
    elif pooled["dm_t"] < 0 and pooled["dm_p"] < 0.10 and positive >= 3:
        label = "MIXED_WEAK"
        summary = "directionally positive but below Harvey |t|>3 gate"
    else:
        label = "NULL"
        summary = "GDELT oil-news attention does not add robust OOS information beyond HAR+inventory"
    return {
        "verdict": label,
        "summary": summary,
        "positive_asset_count": int(positive),
        "asset_count": int(len(per)),
        "claim_ceiling": (
            "GDELT volume proxy only; not true topic model, not Reuters full-text NLP, "
            "and inventory control is realized stock-change proxy rather than survey surprise"
        ),
    }


def main() -> dict:
    np.random.seed(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    panel = build_panel()
    usable = panel.dropna(
        subset=[
            "target_log_rv",
            "target_rv",
            "log_rv_d",
            "log_rv_w",
            "log_rv_m",
            "inventory_signal",
            "news_signal",
        ]
    )
    asset_results_raw = []
    for ticker, asset_df in usable.groupby("ticker"):
        if len(asset_df) < INIT_TRAIN_MIN + 252:
            continue
        asset_results_raw.append(evaluate_asset(asset_df.copy()))

    per_asset = []
    for res in asset_results_raw:
        per_asset.append(
            {
                "ticker": res["ticker"],
                "metrics": res["metrics"],
                "comparisons": res["comparisons"],
            }
        )
    pooled = {
        "HAR_INV_NEWS_vs_HAR_INV": pooled_dm(asset_results_raw, "HAR_INV_NEWS"),
        "HAR_INV_NEWS_ABS_vs_HAR_INV": pooled_dm(asset_results_raw, "HAR_INV_NEWS_ABS"),
    }
    results = {
        "experiment_id": EXP_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "start": START,
            "end_requested": END,
            "oos_start": OOS_START,
            "tickers": TICKERS,
            "sources": [
                "yfinance daily OHLCV auto_adjust=False",
                "GDELT DOC 2.0 TimelineVolRaw oil-market query",
                "EIA WCESTUS1 weekly crude stocks XLS",
            ],
            "n_panel_rows": int(len(panel)),
            "n_usable_rows": int(len(usable)),
        },
        "lookahead_policy": {
            "target": "row t forecasts Garman-Klass RV[t+1]",
            "news": "news_signal = news_z.shift(1)",
            "inventory": "weekly stock-change z shifted +5 business days, then inventory_signal = inventory_z.shift(1)",
            "har": "HAR features use RV through t only",
        },
        "model_design": {
            "baseline": "HAR_INV = HAR range-variance features + lagged EIA inventory-control proxy",
            "primary_challenger": "HAR_INV_NEWS = HAR_INV + lagged GDELT oil-news attention z-score",
            "diagnostic_challenger": "HAR_INV_NEWS_ABS = HAR_INV + absolute attention shock",
            "oos": "expanding OLS, annual refit, OOS 2020 onward",
        },
        "per_asset": per_asset,
        "pooled": pooled,
    }
    results["verdict"] = verdict(results)
    make_figure(panel, results)
    _save_json(RESULTS_PATH, results)
    print(json.dumps({"verdict": results["verdict"], "pooled": pooled}, indent=2))
    return results


if __name__ == "__main__":
    main()
