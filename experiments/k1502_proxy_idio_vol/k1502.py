"""K1502 - FINRA off-exchange activity proxy and next-day idiosyncratic vol.

Research question:
Does a public FINRA off-exchange trading proxy lead next-day idiosyncratic
variance for a retail-tilted US equity basket?

Hard timing rule:
All forecasting features are explicit lag-1 values. A row dated t predicts
the idiosyncratic variance observed on t using information through t-1 only.

Data:
  - FINRA CNMS daily short-sale volume files, 2024-01-02..2026-06-12.
  - yfinance daily OHLC for retail-tilted tickers plus SPY.

This is a reduced-form public-data pilot. FINRA short-sale volume is not true
retail order flow; it is an off-exchange activity / short-volume proxy.
"""

from __future__ import annotations

import io
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats
from statsmodels.api import OLS, add_constant

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


SEED = 42
START = "2023-01-03"
END = "2026-06-15"
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
FIG_DIR = BASE_DIR / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

RETAIL_TILT_TICKERS = [
    "IWM",
    "GME",
    "AMC",
    "BB",
    "KOSS",
    "OPEN",
    "KSS",
    "PLTR",
    "SOFI",
    "HOOD",
    "RIVN",
    "LCID",
    "F",
    "CHWY",
    "DKNG",
    "AFRM",
    "UPST",
    "MARA",
    "RIOT",
    "COIN",
    "CVNA",
    "TLRY",
]

RESULTS: dict = {
    "experiment_id": "K1502",
    "title": "FINRA off-exchange proxy -> next-day idiosyncratic volatility",
    "seed": SEED,
    "data_window": {"start": START, "end": END},
    "universe_requested": RETAIL_TILT_TICKERS,
}


def _as_float_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype(float)


def fetch_finra_one_day(day: pd.Timestamp, symbols: set[str]) -> pd.DataFrame:
    """Fetch one consolidated FINRA CNMS daily file and keep requested symbols."""

    ymd = day.strftime("%Y%m%d")
    url = f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{ymd}.txt"
    try:
        r = requests.get(url, timeout=20)
    except requests.RequestException:
        return pd.DataFrame()
    if r.status_code != 200 or not r.text.startswith("Date|Symbol|"):
        return pd.DataFrame()
    df = pd.read_csv(
        io.StringIO(r.text),
        sep="|",
        usecols=["Date", "Symbol", "ShortVolume", "ShortExemptVolume", "TotalVolume"],
    )
    df = df[df["Symbol"].isin(symbols)].copy()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["Date"].astype(str), format="%Y%m%d")
    df["short_volume"] = _as_float_series(df["ShortVolume"])
    df["short_exempt_volume"] = _as_float_series(df["ShortExemptVolume"])
    df["offex_total_volume"] = _as_float_series(df["TotalVolume"])
    return df[["date", "Symbol", "short_volume", "short_exempt_volume", "offex_total_volume"]]


def fetch_finra(symbols: list[str]) -> pd.DataFrame:
    """Fetch and cache filtered FINRA daily rows for the selected symbols."""

    cache = DATA_DIR / "finra_cnms_filtered.csv"
    cached = pd.DataFrame()
    if cache.exists():
        cached = pd.read_csv(cache, parse_dates=["date"])
        cached = cached[cached["Symbol"].isin(symbols)].copy()
        have = set(cached["Symbol"].unique())
        if (
            not cached.empty
            and set(symbols).issubset(have)
            and cached["date"].min() <= pd.Timestamp(START) + pd.Timedelta(days=7)
            and cached["date"].max() >= pd.Timestamp(END) - pd.Timedelta(days=7)
        ):
            return cached.copy()

    days = pd.bdate_range(START, END)
    if not cached.empty:
        cached_days = set(cached["date"].dt.normalize())
        days = pd.DatetimeIndex([d for d in days if d.normalize() not in cached_days])
    symbol_set = set(symbols)
    rows: list[pd.DataFrame] = [cached] if not cached.empty else []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_finra_one_day, day, symbol_set): day for day in days}
        for n, fut in enumerate(as_completed(futures), 1):
            out = fut.result()
            if not out.empty:
                rows.append(out)
            if n % 100 == 0:
                print(f"[K1502] FINRA fetch progress {n}/{len(futures)} elapsed={time.time()-t0:.1f}s")

    if not rows:
        raise RuntimeError("No FINRA rows fetched.")
    df = pd.concat(rows, ignore_index=True)
    df = df.sort_values(["Symbol", "date"]).reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def fetch_prices(symbols: list[str]) -> pd.DataFrame:
    cache = DATA_DIR / "prices.parquet"
    all_symbols = sorted(set(symbols + ["SPY"]))
    if cache.exists():
        px = pd.read_parquet(cache)
        if (
            set(all_symbols).issubset(set(px.columns.get_level_values(1)))
            and px.index.min() <= pd.Timestamp(START) + pd.Timedelta(days=7)
            and px.index.max() >= pd.Timestamp(END) - pd.Timedelta(days=7)
        ):
            return px.loc[:, pd.IndexSlice[:, all_symbols]].copy()

    raw = yf.download(all_symbols, start=START, end=END, auto_adjust=False, progress=False, threads=True)
    if raw.empty:
        raise RuntimeError("yfinance returned empty data.")
    if not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("Expected yfinance multi-ticker MultiIndex columns.")
    fields = [f for f in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if f in raw.columns.get_level_values(0)]
    px = raw.loc[:, pd.IndexSlice[fields, :]].copy()
    px.to_parquet(cache)
    return px


def build_panel(finra: pd.DataFrame, prices: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Build ticker-date panel with lagged features and next-day target."""

    close_field = "Adj Close" if "Adj Close" in prices.columns.get_level_values(0) else "Close"
    close = prices[close_field].copy()
    high = prices["High"].copy()
    low = prices["Low"].copy()
    volume = prices["Volume"].copy()
    returns = np.log(close).diff()
    spy_ret = returns["SPY"].rename("spy_ret")
    spy_r2 = (spy_ret**2).rename("spy_r2")

    out = []
    for ticker in tickers:
        if ticker not in close.columns or ticker == "SPY":
            continue
        df = pd.DataFrame(
            {
                "ticker": ticker,
                "ret": returns[ticker],
                "spy_ret": spy_ret,
                "spy_r2": spy_r2,
                "close": close[ticker],
                "high": high[ticker],
                "low": low[ticker],
                "yf_volume": volume[ticker],
            }
        )
        valid_beta = df[["ret", "spy_ret"]].dropna()
        if len(valid_beta) < 300:
            continue
        cov = df["ret"].rolling(126, min_periods=63).cov(df["spy_ret"])
        var = df["spy_ret"].rolling(126, min_periods=63).var()
        beta = (cov / var).clip(-3.0, 4.0)
        alpha = (df["ret"] - beta * df["spy_ret"]).rolling(126, min_periods=63).mean()
        resid = df["ret"] - alpha - beta * df["spy_ret"]
        df["idio_r2"] = (resid**2).clip(lower=1e-10)
        df["log_idio_r2"] = np.log(df["idio_r2"])
        df["log_idio_r2_lag1"] = df["log_idio_r2"].shift(1)
        df["log_idio_r2_lag5"] = df["log_idio_r2"].rolling(5, min_periods=3).mean().shift(1)
        df["log_idio_r2_lag22"] = df["log_idio_r2"].rolling(22, min_periods=10).mean().shift(1)
        df["spy_r2_lag1"] = np.log(df["spy_r2"].clip(lower=1e-10)).shift(1)
        # Descriptive controls known by t-1.
        df["abs_ret_lag1"] = df["ret"].abs().shift(1)
        df["dollar_volume_lag1"] = (df["close"] * df["yf_volume"]).shift(1)

        f = finra[finra["Symbol"] == ticker].copy()
        f = f.groupby("date", as_index=True).agg(
            short_volume=("short_volume", "sum"),
            short_exempt_volume=("short_exempt_volume", "sum"),
            offex_total_volume=("offex_total_volume", "sum"),
        )
        f["short_ratio"] = f["short_volume"] / f["offex_total_volume"].replace(0, np.nan)
        f["log_offex_volume"] = np.log(f["offex_total_volume"].replace(0, np.nan))
        df = df.join(f, how="left")
        # Rolling z-scores use strictly prior observations; final signal is shifted again.
        for col in ["short_ratio", "log_offex_volume"]:
            mu = df[col].shift(1).rolling(60, min_periods=20).mean()
            sd = df[col].shift(1).rolling(60, min_periods=20).std()
            df[f"{col}_z_raw"] = (df[col] - mu) / sd
            df[f"{col}_z_lag1"] = df[f"{col}_z_raw"].shift(1)
        df["finra_present_lag1"] = df["short_ratio"].notna().shift(1).fillna(False).astype(int)
        out.append(df.reset_index(names="date"))

    panel = pd.concat(out, ignore_index=True)
    return panel.sort_values(["ticker", "date"]).reset_index(drop=True)


def rolling_oos_one(df: pd.DataFrame, ticker: str, window: int = 252, step: int = 21) -> tuple[dict, pd.DataFrame]:
    """Per-ticker rolling OOS forecast. h=1, so no forward-label embargo is needed."""

    cols_base = ["log_idio_r2_lag1", "log_idio_r2_lag5", "log_idio_r2_lag22", "spy_r2_lag1"]
    cols_full = cols_base + ["short_ratio_z_lag1", "log_offex_volume_z_lag1", "finra_present_lag1"]
    use_cols = ["date", "ticker", "idio_r2", "log_idio_r2"] + cols_full
    d = df[df["ticker"] == ticker][use_cols].dropna().sort_values("date").reset_index(drop=True)
    if len(d) < window + 80:
        return {"ticker": ticker, "status": "insufficient_data", "n": int(len(d))}, pd.DataFrame()

    preds = []
    beta_base = beta_full = None
    for i in range(window, len(d)):
        if beta_base is None or (i - window) % step == 0:
            tr = d.iloc[i - window : i]
            y_tr = tr["log_idio_r2"].values
            xb = np.c_[np.ones(len(tr)), tr[cols_base].values]
            xf = np.c_[np.ones(len(tr)), tr[cols_full].values]
            beta_base, *_ = np.linalg.lstsq(xb, y_tr, rcond=None)
            beta_full, *_ = np.linalg.lstsq(xf, y_tr, rcond=None)
        row = d.iloc[i]
        log_pred_base = float(np.r_[1.0, row[cols_base].values] @ beta_base)
        log_pred_full = float(np.r_[1.0, row[cols_full].values] @ beta_full)
        preds.append(
            {
                "date": row["date"],
                "ticker": ticker,
                "actual_var": float(row["idio_r2"]),
                "actual_log_var": float(row["log_idio_r2"]),
                "pred_var_base": float(np.exp(np.clip(log_pred_base, -25, 2))),
                "pred_var_full": float(np.exp(np.clip(log_pred_full, -25, 2))),
                "pred_log_base": log_pred_base,
                "pred_log_full": log_pred_full,
                "short_ratio_z_lag1": float(row["short_ratio_z_lag1"]),
                "offex_volume_z_lag1": float(row["log_offex_volume_z_lag1"]),
            }
        )

    pred_df = pd.DataFrame(preds)
    loss_base = qlike_pointwise(pred_df["actual_var"].values, pred_df["pred_var_base"].values)
    loss_full = qlike_pointwise(pred_df["actual_var"].values, pred_df["pred_var_full"].values)
    dm_stat, dm_p = dm_test(loss_full, loss_base, h=1)
    q_base = qlike(pred_df["actual_var"].values, pred_df["pred_var_base"].values)
    q_full = qlike(pred_df["actual_var"].values, pred_df["pred_var_full"].values)
    mse_base = float(np.mean((pred_df["actual_log_var"] - pred_df["pred_log_base"]) ** 2))
    mse_full = float(np.mean((pred_df["actual_log_var"] - pred_df["pred_log_full"]) ** 2))
    res = {
        "ticker": ticker,
        "status": "ok",
        "n_model": int(len(d)),
        "n_oos": int(len(pred_df)),
        "oos_start": str(pred_df["date"].min().date()),
        "oos_end": str(pred_df["date"].max().date()),
        "qlike_base": float(q_base),
        "qlike_full": float(q_full),
        "qlike_improvement_pct": float((q_base - q_full) / abs(q_base) * 100.0),
        "log_mse_base": mse_base,
        "log_mse_full": mse_full,
        "log_mse_improvement_pct": float((mse_base - mse_full) / abs(mse_base) * 100.0),
        "dm_full_vs_base": {"stat": float(dm_stat), "p_value": float(dm_p), "harvey_pass": bool(abs(dm_stat) > 3.0)},
    }
    pred_df["loss_base"] = loss_base
    pred_df["loss_full"] = loss_full
    pred_df["loss_diff_full_minus_base"] = loss_full - loss_base
    return res, pred_df


def in_sample_hac(panel: pd.DataFrame) -> list[dict]:
    rows = []
    predictors = [
        "log_idio_r2_lag1",
        "log_idio_r2_lag5",
        "log_idio_r2_lag22",
        "spy_r2_lag1",
        "short_ratio_z_lag1",
        "log_offex_volume_z_lag1",
        "finra_present_lag1",
    ]
    for ticker, g in panel.groupby("ticker"):
        d = g[["log_idio_r2"] + predictors].dropna()
        if len(d) < 300:
            continue
        X = add_constant(d[predictors])
        y = d["log_idio_r2"]
        fit = OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        rows.append(
            {
                "ticker": ticker,
                "n": int(len(d)),
                "short_ratio_z_lag1_beta": float(fit.params["short_ratio_z_lag1"]),
                "short_ratio_z_lag1_t": float(fit.tvalues["short_ratio_z_lag1"]),
                "offex_volume_z_lag1_beta": float(fit.params["log_offex_volume_z_lag1"]),
                "offex_volume_z_lag1_t": float(fit.tvalues["log_offex_volume_z_lag1"]),
                "r2": float(fit.rsquared),
            }
        )
    return rows


def summarize(oos_rows: list[dict], pred_all: pd.DataFrame, is_rows: list[dict]) -> dict:
    ok = [r for r in oos_rows if r.get("status") == "ok"]
    imp = np.array([r["qlike_improvement_pct"] for r in ok], dtype=float)
    dm_stats = np.array([r["dm_full_vs_base"]["stat"] for r in ok], dtype=float)
    pass_rows = [r for r in ok if r["dm_full_vs_base"]["harvey_pass"]]
    pooled_dm = dm_test(pred_all["loss_full"].values, pred_all["loss_base"].values, h=1)
    sign_test = stats.binomtest(int(np.sum(imp > 0)), n=len(imp), p=0.5, alternative="greater") if len(imp) else None
    is_short_t = np.array([r["short_ratio_z_lag1_t"] for r in is_rows], dtype=float)
    is_vol_t = np.array([r["offex_volume_z_lag1_t"] for r in is_rows], dtype=float)
    return {
        "n_tickers_ok": int(len(ok)),
        "n_tickers_harvey_pass": int(len(pass_rows)),
        "harvey_pass_tickers": [r["ticker"] for r in pass_rows],
        "median_qlike_improvement_pct": float(np.nanmedian(imp)) if len(imp) else float("nan"),
        "mean_qlike_improvement_pct": float(np.nanmean(imp)) if len(imp) else float("nan"),
        "positive_improvement_count": int(np.sum(imp > 0)) if len(imp) else 0,
        "sign_test_positive_improvement_p": float(sign_test.pvalue) if sign_test else float("nan"),
        "best_ticker_by_qlike_improvement": max(ok, key=lambda r: r["qlike_improvement_pct"])["ticker"] if ok else None,
        "worst_ticker_by_qlike_improvement": min(ok, key=lambda r: r["qlike_improvement_pct"])["ticker"] if ok else None,
        "pooled_dm_full_vs_base": {"stat": float(pooled_dm[0]), "p_value": float(pooled_dm[1])},
        "median_dm_stat": float(np.nanmedian(dm_stats)) if len(dm_stats) else float("nan"),
        "is_short_ratio_t_median": float(np.nanmedian(is_short_t)) if len(is_short_t) else float("nan"),
        "is_offex_volume_t_median": float(np.nanmedian(is_vol_t)) if len(is_vol_t) else float("nan"),
        "verdict": "NULL" if len(pass_rows) == 0 else "MIXED",
    }


def make_figures(oos_rows: list[dict], pred_all: pd.DataFrame) -> None:
    ok = [r for r in oos_rows if r.get("status") == "ok"]
    if not ok:
        return
    tickers = [r["ticker"] for r in ok]
    imp = [r["qlike_improvement_pct"] for r in ok]
    order = np.argsort(imp)
    plt.figure(figsize=(10, 6))
    colors = ["C2" if v > 0 else "C3" for v in np.array(imp)[order]]
    plt.barh(np.array(tickers)[order], np.array(imp)[order], color=colors)
    plt.axvline(0, color="black", lw=0.8)
    plt.xlabel("QLIKE improvement vs HAR-log baseline (%)")
    plt.title("K1502: FINRA proxy incremental OOS idiosyncratic-vol signal")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "k1502_qlike_improvement_by_ticker.png", dpi=150)
    plt.close()

    top = pred_all.nlargest(800, "short_ratio_z_lag1").copy()
    rest = pred_all.copy()
    rest["short_ratio_bucket"] = pd.qcut(rest["short_ratio_z_lag1"], q=5, labels=False, duplicates="drop")
    bucket = rest.groupby("short_ratio_bucket", as_index=False).agg(
        n=("actual_var", "size"),
        mean_short_z=("short_ratio_z_lag1", "mean"),
        mean_actual_var=("actual_var", "mean"),
        median_actual_var=("actual_var", "median"),
    )
    plt.figure(figsize=(8, 5))
    plt.bar(bucket["short_ratio_bucket"].astype(str), bucket["mean_actual_var"], color="C0")
    plt.xlabel("Lagged FINRA short-ratio z-score quintile")
    plt.ylabel("Mean next-day idiosyncratic variance")
    plt.title("K1502 descriptive: next-day idio variance by lagged FINRA short-ratio bucket")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "k1502_short_ratio_bucket_nextday_idio_var.png", dpi=150)
    plt.close()

    _ = top  # retained for quick debugger inspection


def main() -> None:
    np.random.seed(SEED)
    print("[K1502] fetch FINRA")
    finra = fetch_finra(RETAIL_TILT_TICKERS)
    print(f"[K1502] FINRA rows={len(finra)} symbols={finra['Symbol'].nunique()}")
    print("[K1502] fetch prices")
    prices = fetch_prices(RETAIL_TILT_TICKERS)
    print(f"[K1502] price rows={len(prices)}")
    print("[K1502] build panel")
    panel = build_panel(finra, prices, RETAIL_TILT_TICKERS)
    panel.to_parquet(DATA_DIR / "panel.parquet")

    available = sorted(panel["ticker"].dropna().unique().tolist())
    RESULTS["data_sources"] = {
        "finra": "https://cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt",
        "prices": "yfinance daily OHLC",
        "finra_proxy_caveat": "FINRA short-volume ratio/off-exchange volume are public off-exchange activity proxies, not direct retail order-flow.",
    }
    RESULTS["sample"] = {
        "tickers_available": available,
        "n_panel_rows": int(len(panel)),
        "panel_date_start": str(panel["date"].min().date()),
        "panel_date_end": str(panel["date"].max().date()),
        "finra_date_start": str(finra["date"].min().date()),
        "finra_date_end": str(finra["date"].max().date()),
        "finra_rows_filtered": int(len(finra)),
    }

    print("[K1502] rolling OOS")
    oos_rows = []
    pred_parts = []
    for ticker in available:
        res, preds = rolling_oos_one(panel, ticker)
        oos_rows.append(res)
        if not preds.empty:
            pred_parts.append(preds)
        print(f"  {ticker}: {res.get('status')} n_oos={res.get('n_oos')} imp={res.get('qlike_improvement_pct')}")

    if not pred_parts:
        raise RuntimeError("No OOS forecasts produced.")
    pred_all = pd.concat(pred_parts, ignore_index=True)
    pred_all.to_parquet(DATA_DIR / "oos_predictions.parquet")
    is_rows = in_sample_hac(panel)
    summary = summarize(oos_rows, pred_all, is_rows)
    RESULTS["method"] = {
        "target": "next-day CAPM-residual squared return, clipped at 1e-10",
        "baseline": "rolling 252-day HAR-log idiosyncratic variance + SPY variance lag",
        "full_model": "baseline + lagged FINRA short-ratio z + lagged log off-exchange volume z + FINRA-present indicator",
        "timing": "all predictors use explicit shift(1); row t uses information through t-1",
        "oos": {"window": 252, "refit_step": 21, "horizon": 1},
        "evaluation": "Patton QLIKE on residual variance, canonical volpred.stats.model_evaluation.dm_test, Harvey |t|>3 gate",
    }
    RESULTS["oos_by_ticker"] = oos_rows
    RESULTS["in_sample_hac_by_ticker"] = is_rows
    RESULTS["summary"] = summary
    make_figures(oos_rows, pred_all)
    RESULTS["figures"] = [
        "figures/k1502_qlike_improvement_by_ticker.png",
        "figures/k1502_short_ratio_bucket_nextday_idio_var.png",
    ]
    out = BASE_DIR / "k1502_results.json"
    out.write_text(json.dumps(RESULTS, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    print(f"[K1502] wrote {out}")


if __name__ == "__main__":
    main()
