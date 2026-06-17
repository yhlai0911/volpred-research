"""
K1525: Idiosyncratic-volatility ICAPM covariance-risk proxy.

ETF/large-cap proxy experiment:
1. Build trailing CAPM residual volatility for a current large-cap US stock
   universe using daily yfinance data.
2. Test whether lagged idiosyncratic volatility is priced in next-month
   stock excess returns with Fama-MacBeth regressions.
3. Test whether aggregate cross-sectional IV proxies predict next-month SPY
   excess returns out of sample versus an expanding historical-mean baseline.

This is not a CRSP 1815-2018 replication of Han-Li CBIV. It is a transparent
yfinance proxy with explicit survivorship-bias limitations.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import dm_test

warnings.filterwarnings("ignore", category=FutureWarning)

OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "k1525_results.json"
FIG_PATH = OUT_DIR / "k1525_oos_r2.png"

START = "2004-01-01"
OOS_START = "2012-01-31"
MIN_TRAIN_MONTHS = 84
ROLL_DAILY = 126
ROLL_COV_MONTHS = 36

STOCKS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "JPM", "V",
    "UNH", "MA", "HD", "PG", "COST", "XOM", "NFLX", "JNJ", "WMT", "ABBV",
    "BAC", "KO", "CRM", "CVX", "ORCL", "CSCO", "MRK", "AMD", "PEP", "TMO",
    "MCD", "IBM", "ABT", "GE", "LIN", "ACN", "DIS", "ADBE", "QCOM", "TXN",
    "INTU", "VZ", "CMCSA", "AMGN", "HON", "CAT", "NKE", "LOW", "UPS",
    "RTX", "GS", "MS", "BLK", "SPGI", "NOW", "ISRG", "LLY", "AVGO", "DE",
    "MDT", "GILD", "AMAT", "BKNG", "SBUX", "BA", "AXP", "C", "COP", "SCHW",
]
MARKET = "SPY"
CASH = "SHY"
ALL_TICKERS = STOCKS + [MARKET, CASH]


@dataclass(frozen=True)
class OOSRow:
    model: str
    n_oos: int
    mse: float
    oos_r2: float
    dm_t: float
    dm_p: float
    harvey_pass: bool
    directional_accuracy: float


def _download_panel() -> pd.DataFrame:
    raw = yf.download(
        ALL_TICKERS,
        start=START,
        auto_adjust=False,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty panel")
    frames = []
    for ticker in ALL_TICKERS:
        if ticker not in raw.columns.get_level_values(0):
            continue
        df = raw[ticker].copy()
        if df.empty or "Close" not in df:
            continue
        if "Adj Close" not in df:
            df["Adj Close"] = df["Close"]
        keep = df[["Adj Close", "Close", "Volume"]].copy()
        keep.columns = pd.MultiIndex.from_product([[ticker], keep.columns])
        frames.append(keep)
    if len(frames) < 20:
        raise RuntimeError(f"too few usable tickers: {len(frames)}")
    panel = pd.concat(frames, axis=1).sort_index()
    return panel.dropna(how="all")


def _rolling_capm_idio(stock_ret: pd.DataFrame, market_ret: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    market_var = market_ret.rolling(ROLL_DAILY, min_periods=90).var()
    market_mean = market_ret.rolling(ROLL_DAILY, min_periods=90).mean()
    betas = {}
    residuals = {}
    for ticker in stock_ret:
        r = stock_ret[ticker]
        cov = r.rolling(ROLL_DAILY, min_periods=90).cov(market_ret)
        beta = cov / market_var
        alpha = r.rolling(ROLL_DAILY, min_periods=90).mean() - beta * market_mean
        resid = r - alpha - beta * market_ret
        betas[ticker] = beta
        residuals[ticker] = resid
    beta_df = pd.DataFrame(betas)
    resid_df = pd.DataFrame(residuals)
    idio_vol = resid_df.rolling(ROLL_DAILY, min_periods=90).std() * math.sqrt(252)
    return idio_vol, beta_df


def _month_end(df: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return df.resample("ME").last()


def _build_monthly_dataset(panel: pd.DataFrame) -> dict[str, pd.DataFrame | pd.Series]:
    adj = panel.xs("Adj Close", level=1, axis=1)
    close = panel.xs("Close", level=1, axis=1)
    volume = panel.xs("Volume", level=1, axis=1)

    usable_stocks = [t for t in STOCKS if t in adj.columns]
    stock_ret_d = adj[usable_stocks].pct_change()
    market_ret_d = adj[MARKET].pct_change()

    idio_vol_d, beta_d = _rolling_capm_idio(stock_ret_d, market_ret_d)
    idio_m = _month_end(idio_vol_d)
    beta_m = _month_end(beta_d)
    dollar_vol = (close[usable_stocks] * volume[usable_stocks]).rolling(63, min_periods=40).mean()
    dollar_vol_m = _month_end(dollar_vol)

    monthly_price = _month_end(adj[usable_stocks + [MARKET, CASH]])
    stock_ret_m = monthly_price[usable_stocks].pct_change()
    market_excess = monthly_price[MARKET].pct_change() - monthly_price[CASH].pct_change()
    stock_excess_next = stock_ret_m.sub(monthly_price[CASH].pct_change(), axis=0).shift(-1)
    target_next = market_excess.shift(-1)

    ewiv = idio_m.mean(axis=1, skipna=True)
    weights = dollar_vol_m.div(dollar_vol_m.sum(axis=1), axis=0)
    lwiv = (idio_m * weights).sum(axis=1, min_count=10)
    cbiv_spread = ewiv - lwiv
    beta_weighted_iv = (idio_m * beta_m.clip(lower=-3, upper=3)).mean(axis=1, skipna=True)
    market_vol = market_ret_d.rolling(ROLL_DAILY, min_periods=90).std() * math.sqrt(252)
    market_vol_m = _month_end(market_vol)

    quintile_returns = _quintile_next_returns(idio_m, stock_excess_next)
    known_hl = quintile_returns["Q5_minus_Q1"].shift(1)
    known_market = market_excess.copy()
    hedge_cov = known_hl.rolling(ROLL_COV_MONTHS, min_periods=24).cov(known_market)

    features = pd.DataFrame(
        {
            "EWIV": ewiv,
            "LWIV": lwiv,
            "CBIV_spread": cbiv_spread,
            "beta_weighted_IV": beta_weighted_iv,
            "hedge_cov_36m": hedge_cov,
            "market_vol_126d": market_vol_m,
        }
    )
    return {
        "features": features,
        "target_next": target_next,
        "stock_excess_next": stock_excess_next,
        "idio_m": idio_m,
        "beta_m": beta_m,
        "quintile_returns": quintile_returns,
        "market_excess": market_excess,
        "usable_stocks": pd.Series(usable_stocks),
    }


def _quintile_next_returns(idio_m: pd.DataFrame, stock_excess_next: pd.DataFrame) -> pd.DataFrame:
    records = []
    for date, row in idio_m.iterrows():
        ret = stock_excess_next.loc[date]
        valid = row.notna() & ret.notna()
        if valid.sum() < 25:
            records.append({"date": date})
            continue
        ranks = row[valid].rank(method="first")
        q = pd.qcut(ranks, 5, labels=False) + 1
        rec = {"date": date}
        for bucket in range(1, 6):
            rec[f"Q{bucket}"] = float(ret[valid][q == bucket].mean())
        rec["Q5_minus_Q1"] = rec["Q5"] - rec["Q1"]
        records.append(rec)
    return pd.DataFrame(records).set_index("date")


def _ols_fit_predict(x_train: pd.DataFrame, y_train: pd.Series, x_now: pd.Series) -> float:
    x = x_train.copy()
    std = x.std(ddof=1).replace(0, np.nan)
    mean = x.mean()
    x = (x - mean) / std
    x = x.replace([np.inf, -np.inf], np.nan).dropna()
    y = y_train.loc[x.index]
    valid = y.notna()
    x = x.loc[valid]
    y = y.loc[valid]
    if len(y) < MIN_TRAIN_MONTHS:
        return np.nan
    x_design = np.column_stack([np.ones(len(x)), x.to_numpy()])
    beta = np.linalg.pinv(x_design.T @ x_design) @ x_design.T @ y.to_numpy()
    x_now_std = ((x_now - mean) / std).replace([np.inf, -np.inf], np.nan)
    if x_now_std.isna().any():
        return np.nan
    x_vec = np.r_[1.0, x_now_std.to_numpy()]
    return float(x_vec @ beta)


def recursive_oos(features: pd.DataFrame, target: pd.Series, model_specs: dict[str, list[str]]) -> pd.DataFrame:
    rows = []
    data = pd.concat([target.rename("target"), features], axis=1)
    data = data.loc[data.index >= pd.Timestamp("2005-01-31")]
    for i, date in enumerate(data.index):
        if date < pd.Timestamp(OOS_START):
            continue
        train = data.iloc[:i].dropna(subset=["target"])
        if len(train) < MIN_TRAIN_MONTHS:
            continue
        y_train = train["target"]
        target_now = data.loc[date, "target"]
        if not np.isfinite(target_now):
            continue
        row = {
            "date": date,
            "target": float(target_now),
            "baseline": float(y_train.mean()),
        }
        for name, cols in model_specs.items():
            pred = _ols_fit_predict(train[cols], y_train, data.loc[date, cols])
            row[name] = pred
        rows.append(row)
    return pd.DataFrame(rows).set_index("date")


def evaluate_oos(preds: pd.DataFrame, model_specs: dict[str, list[str]]) -> list[OOSRow]:
    out = []
    y = preds["target"]
    base = preds["baseline"]
    base_loss = (y - base) ** 2
    for model in model_specs:
        aligned = pd.concat([y, base, preds[model]], axis=1, keys=["y", "base", "model"]).dropna()
        if len(aligned) < 24:
            continue
        loss_model = (aligned["y"] - aligned["model"]) ** 2
        loss_base = (aligned["y"] - aligned["base"]) ** 2
        t_stat, p_val = dm_test(loss_model.to_numpy(), loss_base.to_numpy(), h=1)
        sse_model = float(loss_model.sum())
        sse_base = float(loss_base.sum())
        oos_r2 = 1.0 - sse_model / sse_base if sse_base > 0 else np.nan
        direction = float((np.sign(aligned["model"]) == np.sign(aligned["y"])).mean())
        out.append(
            OOSRow(
                model=model,
                n_oos=len(aligned),
                mse=float(loss_model.mean()),
                oos_r2=float(oos_r2),
                dm_t=float(t_stat),
                dm_p=float(p_val),
                harvey_pass=bool(t_stat < -3.0 and oos_r2 > 0),
                directional_accuracy=direction,
            )
        )
    return out


def fama_macbeth(stock_excess_next: pd.DataFrame, idio_m: pd.DataFrame, beta_m: pd.DataFrame) -> dict[str, object]:
    gammas = []
    for date in stock_excess_next.index:
        y = stock_excess_next.loc[date]
        iv = idio_m.loc[date]
        beta = beta_m.loc[date]
        valid = y.notna() & iv.notna() & beta.notna()
        if valid.sum() < 25:
            continue
        x = pd.DataFrame({"idio_vol": iv[valid], "beta": beta[valid]})
        x = (x - x.mean()) / x.std(ddof=1).replace(0, np.nan)
        x = x.replace([np.inf, -np.inf], np.nan).dropna()
        yv = y.loc[x.index]
        if len(yv) < 25:
            continue
        design = np.column_stack([np.ones(len(x)), x.to_numpy()])
        coef = np.linalg.pinv(design.T @ design) @ design.T @ yv.to_numpy()
        gammas.append({"date": date, "alpha": coef[0], "gamma_idio": coef[1], "gamma_beta": coef[2], "n": len(yv)})
    g = pd.DataFrame(gammas).set_index("date")
    return {
        "n_months": int(len(g)),
        "mean_gamma_idio": float(g["gamma_idio"].mean()),
        "mean_gamma_beta": float(g["gamma_beta"].mean()),
        "hac_t_gamma_idio": float(_hac_mean_t(g["gamma_idio"].dropna(), lags=3)),
        "hac_t_gamma_beta": float(_hac_mean_t(g["gamma_beta"].dropna(), lags=3)),
        "mean_cross_section_n": float(g["n"].mean()),
    }


def _hac_mean_t(series: pd.Series, lags: int = 3) -> float:
    x = series.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 12:
        return 0.0
    x_mean = x.mean()
    centered = x - x_mean
    var = np.mean(centered * centered)
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (lags + 1)
        gamma = np.mean(centered[lag:] * centered[:-lag])
        var += 2 * weight * gamma
    if var <= 0:
        return 0.0
    se = math.sqrt(var / n)
    return float(x_mean / se) if se > 0 else 0.0


def make_figure(oos_rows: list[OOSRow], preds: pd.DataFrame) -> None:
    res = pd.DataFrame([r.__dict__ for r in oos_rows]).sort_values("oos_r2")
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    colors = ["#3f6f68" if v > 0 else "#9b3d35" for v in res["oos_r2"]]
    axes[0].barh(res["model"], res["oos_r2"] * 100, color=colors)
    axes[0].axvline(0, color="black", linewidth=0.8)
    axes[0].set_title("OOS R2 vs expanding mean baseline")
    axes[0].set_xlabel("OOS R2 (%)")

    idio_rows = [r for r in oos_rows if r.model != "market_vol_control"]
    best = max(idio_rows or oos_rows, key=lambda r: r.oos_r2)
    y = preds[["target", "baseline", best.model]].dropna()
    cum_diff = ((y["target"] - y["baseline"]) ** 2 - (y["target"] - y[best.model]) ** 2).cumsum()
    axes[1].plot(cum_diff.index, cum_diff, color="#3f6f68")
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title(f"Cumulative squared-error reduction: {best.model}")
    axes[1].set_ylabel("baseline loss - model loss")
    fig.suptitle("K1525 idiosyncratic-volatility ICAPM proxy audit", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    t0 = datetime.now(timezone.utc)
    panel = _download_panel()
    monthly = _build_monthly_dataset(panel)
    features = monthly["features"]
    target_next = monthly["target_next"]

    model_specs = {
        "EWIV": ["EWIV"],
        "LWIV": ["LWIV"],
        "CBIV_spread": ["CBIV_spread"],
        "beta_weighted_IV": ["beta_weighted_IV"],
        "hedge_cov_36m": ["hedge_cov_36m"],
        "market_vol_control": ["market_vol_126d"],
        "CBIV_plus_market_vol": ["EWIV", "LWIV", "CBIV_spread", "market_vol_126d"],
        "all_idio_proxies": ["EWIV", "LWIV", "CBIV_spread", "beta_weighted_IV", "hedge_cov_36m"],
    }
    preds = recursive_oos(features, target_next, model_specs)
    oos_rows = evaluate_oos(preds, model_specs)
    fmb = fama_macbeth(monthly["stock_excess_next"], monthly["idio_m"], monthly["beta_m"])
    make_figure(oos_rows, preds)

    best = max(oos_rows, key=lambda r: r.oos_r2)
    idio_model_names = [name for name in model_specs if name != "market_vol_control"]
    idio_rows = [r for r in oos_rows if r.model in idio_model_names]
    best_idio = max(idio_rows, key=lambda r: r.oos_r2)
    passes = [r.model for r in idio_rows if r.harvey_pass]
    fmb_pass = bool(abs(fmb["hac_t_gamma_idio"]) > 3.0)
    if passes:
        verdict = "PASS_NARROW_PROXY"
        summary = f"At least one idiosyncratic-volatility proxy improves monthly SPY excess-return OOS forecasts at Harvey strength: {passes}."
    elif fmb_pass:
        verdict = "MIXED_CROSS_SECTION_ONLY"
        summary = (
            f"Lagged idiosyncratic volatility is priced in Fama-MacBeth regressions "
            f"(gamma t={fmb['hac_t_gamma_idio']:.2f}), but no idiosyncratic-volatility proxy "
            f"improves next-month SPY excess-return forecasts OOS. Best idio timing model "
            f"{best_idio.model} has OOS R2={best_idio.oos_r2:.3%}, DM t={best_idio.dm_t:.2f}."
        )
    elif best_idio.oos_r2 > 0:
        verdict = "DIRECTIONAL_WEAK_PROXY"
        summary = (
            f"Best idiosyncratic-volatility proxy {best_idio.model} has positive OOS R2={best_idio.oos_r2:.3%} "
            f"but DM t={best_idio.dm_t:.2f}, well below Harvey strength. Treat as directional only."
        )
    else:
        verdict = "NULL_PROXY"
        summary = (
            "No idiosyncratic-volatility proxy beats the expanding-mean monthly SPY excess-return forecast. "
            "The yfinance large-cap proxy does not support a publishable ICAPM covariance-risk timing claim."
        )

    output = {
        "experiment_id": "K1525",
        "title": "Idiosyncratic-volatility ICAPM covariance-risk proxy for market excess-return prediction",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_id": "research_idiosyncratic_vol_icapm_covariance_risk_proxy_ex",
        "verdict": verdict,
        "summary": summary,
        "data": {
            "source": "yfinance",
            "daily_start": str(panel.index.min().date()),
            "daily_end": str(panel.index.max().date()),
            "universe_requested": len(STOCKS),
            "usable_stock_count": int(len(monthly["usable_stocks"])),
            "market": MARKET,
            "cash_proxy": CASH,
            "oos_start": OOS_START,
            "oos_months": int(max((r.n_oos for r in oos_rows), default=0)),
        },
        "method": {
            "scope": "current-name large-cap yfinance proxy; not CRSP/CRSP-Compustat and not Han-Li 1815-2018 replication",
            "idio_vol": "annualized trailing 126d residual volatility from rolling CAPM against SPY",
            "aggregate_proxies": [
                "EWIV equal-weight average idio vol",
                "LWIV dollar-volume-weighted idio vol",
                "CBIV_spread = EWIV - LWIV",
                "beta_weighted_IV",
                "hedge_cov_36m = trailing covariance of known Q5-Q1 idio-vol hedge return with market excess return",
            ],
            "forecast_design": "month-end predictors at t forecast next-month SPY-SHY excess return; recursive expanding OLS vs historical mean baseline",
            "lookahead_guard": "stock_excess_next and market target use shift(-1); all predictor construction uses only daily/monthly data available by month-end t",
            "test": "OOS R2 and dm_test on squared forecast errors, h=1; Harvey pass if DM t < -3 and OOS R2 > 0",
        },
        "oos_results": [
            {
                "model": r.model,
                "n_oos": r.n_oos,
                "mse": round(r.mse, 8),
                "oos_r2": round(r.oos_r2, 6),
                "dm_t": round(r.dm_t, 4),
                "dm_p": round(r.dm_p, 4),
                "harvey_pass": r.harvey_pass,
                "directional_accuracy": round(r.directional_accuracy, 4),
            }
            for r in oos_rows
        ],
        "fama_macbeth": {
            "n_months": fmb["n_months"],
            "mean_gamma_idio": round(fmb["mean_gamma_idio"], 8),
            "mean_gamma_beta": round(fmb["mean_gamma_beta"], 8),
            "hac_t_gamma_idio": round(fmb["hac_t_gamma_idio"], 4),
            "hac_t_gamma_beta": round(fmb["hac_t_gamma_beta"], 4),
            "mean_cross_section_n": round(fmb["mean_cross_section_n"], 1),
            "harvey_pass_idio": bool(abs(fmb["hac_t_gamma_idio"]) > 3.0),
        },
        "quintile_summary": {
            col: round(float(monthly["quintile_returns"][col].mean() * 12), 6)
            for col in monthly["quintile_returns"].columns
        },
        "key_numbers": {
            "best_model": best.model,
            "best_oos_r2": round(best.oos_r2, 6),
            "best_dm_t": round(best.dm_t, 4),
            "best_idio_model": best_idio.model,
            "best_idio_oos_r2": round(best_idio.oos_r2, 6),
            "best_idio_dm_t": round(best_idio.dm_t, 4),
            "harvey_pass_models": passes,
            "fmb_idio_t": round(fmb["hac_t_gamma_idio"], 4),
        },
        "limitations": [
            "Current-name large-cap universe creates survivorship bias and omits delisted/small stocks.",
            "Dollar-volume-weighted IV is only a liquidity-weight proxy, not true value-weighted market capitalization IV.",
            "Monthly yfinance adjusted returns and SHY cash proxy are not a CRSP excess-return construction.",
            "CBIV_spread and hedge covariance are approximations of the Han-Li ICAPM covariance-risk object.",
        ],
        "references": [
            {
                "title": "Han and Li, Idiosyncratic Volatility and the ICAPM Covariance Risk",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3475179",
            },
            {
                "title": "Goyal and Santa-Clara (2003), Idiosyncratic Risk Matters!",
                "url": "https://ideas.repec.org/a/bla/jfinan/v58y2003i3p975-1007.html",
            },
            {
                "title": "Guo and Savickas (2006), Idiosyncratic Volatility, Stock Market Volatility, and Expected Stock Returns",
                "url": "https://files.stlouisfed.org/files/htdocs/wp/2003/2003-028.pdf",
            },
        ],
        "elapsed_seconds": round((datetime.now(timezone.utc) - t0).total_seconds(), 2),
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"verdict": verdict, "summary": summary, "results": str(RESULTS_PATH)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
