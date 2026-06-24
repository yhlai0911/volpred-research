"""K1551 - Bond ETF AP-fragility proxy and stress-day dislocation.

This is a data-limited proxy experiment. Public yfinance data does not expose
ETF-level authorized-participant activity or 13F AP concentration for the tested
funds. The empirical layer therefore tests whether a static free-data
"AP-fragility" proxy is associated with larger bond ETF fair-value residuals and
next-5-day realized volatility on stress days.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats


SEED = 1551
EXPERIMENT_ID = "K1551"
START = "2015-01-01"
END = "2026-06-25"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FIG_DIR = BASE_DIR / "figures"
RESULT_PATH = BASE_DIR / "k1551_results.json"

ETF_TICKERS = ["AGG", "BND", "LQD", "HYG", "MUB", "EMB", "TLT", "IEF"]
FACTOR_TICKERS = ["SHY", "IEI", "TLT", "LQD", "HYG", "SPY"]
MARKET_TICKERS = ["^VIX", "^MOVE"]
ALL_TICKERS = sorted(set(ETF_TICKERS + FACTOR_TICKERS + MARKET_TICKERS))


@dataclass
class EtfResult:
    ticker: str
    category: str
    fragility_score: float
    high_fragility_group: bool
    observations: int
    stress_days: int
    stress_abs_residual_mean: float
    normal_abs_residual_mean: float
    abs_residual_stress_lift: float
    stress_fwd5_rv_mean: float
    normal_fwd5_rv_mean: float
    fwd5_rv_stress_lift: float


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def download_prices() -> pd.DataFrame:
    cache = DATA_DIR / "prices.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    raw = yf.download(ALL_TICKERS, start=START, end=END, auto_adjust=False, progress=False, threads=True)
    if raw.empty or not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("yfinance returned empty or non-MultiIndex data")
    fields = [field for field in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if field in raw.columns.get_level_values(0)]
    out = raw.loc[:, pd.IndexSlice[fields, :]].sort_index()
    out.to_parquet(cache)
    return out


def _safe_float(value: object) -> float:
    try:
        if pd.isna(value):
            return float("nan")
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def fetch_fund_metadata() -> pd.DataFrame:
    cache = DATA_DIR / "fund_metadata.csv"
    audit_cache = DATA_DIR / "data_availability_audit.json"
    if cache.exists() and audit_cache.exists():
        return pd.read_csv(cache)

    rows: list[dict] = []
    audit: dict[str, dict] = {}
    for ticker in ETF_TICKERS:
        yft = yf.Ticker(ticker)
        holder_rows = 0
        holder_error = None
        try:
            holders = yft.institutional_holders
            holder_rows = 0 if holders is None else int(getattr(holders, "shape", [0])[0])
        except Exception as exc:  # yfinance raises 404s for ETF fundamentals.
            holder_error = f"{type(exc).__name__}: {str(exc)[:200]}"

        fd = yft.funds_data
        overview = {}
        operations = pd.DataFrame()
        bond_holdings = pd.DataFrame()
        ratings = {}
        try:
            overview = fd.fund_overview or {}
        except Exception:
            overview = {}
        try:
            operations = fd.fund_operations
        except Exception:
            operations = pd.DataFrame()
        try:
            bond_holdings = fd.bond_holdings
        except Exception:
            bond_holdings = pd.DataFrame()
        try:
            ratings = fd.bond_ratings or {}
        except Exception:
            ratings = {}

        turnover = float("nan")
        expense = float("nan")
        if not operations.empty and ticker in operations.columns:
            turnover = _safe_float(operations.loc["Annual Holdings Turnover", ticker]) if "Annual Holdings Turnover" in operations.index else float("nan")
            expense = _safe_float(operations.loc["Annual Report Expense Ratio", ticker]) if "Annual Report Expense Ratio" in operations.index else float("nan")

        duration = float("nan")
        maturity = float("nan")
        if not bond_holdings.empty and ticker in bond_holdings.columns:
            duration = _safe_float(bond_holdings.loc["Duration", ticker]) if "Duration" in bond_holdings.index else float("nan")
            maturity = _safe_float(bond_holdings.loc["Maturity", ticker]) if "Maturity" in bond_holdings.index else float("nan")

        row = {
            "ticker": ticker,
            "category": overview.get("categoryName", ""),
            "family": overview.get("family", ""),
            "legal_type": overview.get("legalType", ""),
            "holder_rows": holder_rows,
            "holder_error": holder_error or "",
            "turnover": turnover,
            "expense_ratio": expense,
            "duration": duration,
            "maturity": maturity,
            "rating_bb": _safe_float(ratings.get("bb")),
            "rating_b": _safe_float(ratings.get("b")),
            "rating_below_b": _safe_float(ratings.get("below_b")),
            "rating_bbb": _safe_float(ratings.get("bbb")),
            "rating_a": _safe_float(ratings.get("a")),
            "rating_aa": _safe_float(ratings.get("aa")),
            "rating_aaa": _safe_float(ratings.get("aaa")),
            "rating_us_government": _safe_float(ratings.get("us_government")),
        }
        rows.append(row)
        audit[ticker] = {
            "institutional_holder_rows": holder_rows,
            "institutional_holder_error": holder_error,
            "funds_data_available": bool(overview or not operations.empty or not bond_holdings.empty or ratings),
        }

    meta = pd.DataFrame(rows)
    meta.to_csv(cache, index=False)
    audit_cache.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


def zscore_cross_section(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def build_fragility_scores(meta: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    close = prices["Adj Close"] if "Adj Close" in prices.columns.get_level_values(0) else prices["Close"]
    high = prices["High"]
    low = prices["Low"]
    volume = prices["Volume"]
    rows = []
    for _, row in meta.iterrows():
        ticker = row["ticker"]
        dollar_volume = (close[ticker] * volume[ticker]).replace(0, np.nan)
        spread_proxy = ((high[ticker] - low[ticker]) / close[ticker]).replace([np.inf, -np.inf], np.nan)
        rows.append(
            {
                "ticker": ticker,
                "mean_spread_proxy": float(spread_proxy.mean()),
                "median_dollar_volume": float(dollar_volume.median()),
            }
        )
    liquidity = pd.DataFrame(rows)
    out = meta.merge(liquidity, on="ticker", how="left")
    out["credit_complexity"] = (
        out[["rating_bb", "rating_b", "rating_below_b", "rating_bbb"]].fillna(0.0).sum(axis=1)
    )
    out["category_complexity"] = out["category"].str.contains("High Yield|Emerging|Muni|Corporate", regex=True, case=False).astype(float)
    out["inverse_depth"] = -np.log(out["median_dollar_volume"].replace(0, np.nan))
    components = {
        "credit_complexity_z": zscore_cross_section(out["credit_complexity"].fillna(out["credit_complexity"].median())),
        "category_complexity_z": zscore_cross_section(out["category_complexity"]),
        "turnover_z": zscore_cross_section(out["turnover"].fillna(out["turnover"].median())),
        "spread_proxy_z": zscore_cross_section(out["mean_spread_proxy"].fillna(out["mean_spread_proxy"].median())),
        "inverse_depth_z": zscore_cross_section(out["inverse_depth"].fillna(out["inverse_depth"].median())),
    }
    for name, values in components.items():
        out[name] = values
    out["ap_fragility_proxy_score"] = out[list(components)].mean(axis=1)
    median_score = out["ap_fragility_proxy_score"].median()
    out["high_fragility_group"] = out["ap_fragility_proxy_score"] >= median_score
    out.to_csv(DATA_DIR / "fragility_scores.csv", index=False)
    return out


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    total = pd.Series(0.0, index=series.index)
    for step in range(1, horizon + 1):
        total = total + series.shift(-step)
    return total


def rolling_factor_residuals(returns: pd.DataFrame, ticker: str, factors: list[str]) -> pd.Series:
    factors = [factor for factor in factors if factor != ticker and factor in returns.columns]
    target = returns[ticker]
    model_frame = pd.concat([target.rename("target"), returns[factors]], axis=1)
    residuals = pd.Series(np.nan, index=returns.index, name=ticker)
    beta: np.ndarray | None = None
    window = 504
    min_obs = 252
    refit_every = 21
    for i, date in enumerate(returns.index):
        if i < min_obs:
            continue
        if beta is None or i % refit_every == 0:
            train = model_frame.iloc[max(0, i - window) : i].dropna()
            if len(train) < min_obs:
                continue
            y = train["target"].to_numpy()
            x = train[factors].to_numpy()
            x = np.column_stack([np.ones(len(x)), x])
            beta = np.linalg.lstsq(x, y, rcond=None)[0]
        row = model_frame.loc[date, factors]
        if beta is None or row.isna().any() or pd.isna(target.loc[date]):
            continue
        x_now = np.r_[1.0, row.to_numpy(dtype=float)]
        residuals.loc[date] = float(target.loc[date] - x_now @ beta)
    return residuals


def build_panel(prices: pd.DataFrame, fragility: pd.DataFrame) -> pd.DataFrame:
    close = prices["Adj Close"] if "Adj Close" in prices.columns.get_level_values(0) else prices["Close"]
    high = prices["High"]
    low = prices["Low"]
    volume = prices["Volume"]
    returns = np.log(close).diff()
    vix = close["^VIX"] if "^VIX" in close.columns else pd.Series(np.nan, index=close.index)
    move = close["^MOVE"] if "^MOVE" in close.columns else pd.Series(np.nan, index=close.index)
    stress = ((vix > 25.0) | (move > 120.0)).astype(float)
    residual_map = {
        ticker: rolling_factor_residuals(returns, ticker, FACTOR_TICKERS)
        for ticker in ETF_TICKERS
    }
    rows = []
    fragility_idx = fragility.set_index("ticker")
    for ticker in ETF_TICKERS:
        residual = residual_map[ticker]
        ret = returns[ticker]
        spread_proxy = ((high[ticker] - low[ticker]) / close[ticker]).replace([np.inf, -np.inf], np.nan)
        dollar_volume = (close[ticker] * volume[ticker]).replace(0, np.nan)
        df = pd.DataFrame(
            {
                "date": close.index,
                "ticker": ticker,
                "ret": ret,
                "abs_fair_value_residual": residual.abs(),
                "signed_fair_value_residual": residual,
                "spread_proxy": spread_proxy,
                "dollar_volume": dollar_volume,
                "vix": vix,
                "move": move,
                "stress_day": stress,
                "fwd5_rv": forward_sum(ret**2, 5),
            }
        )
        df["category"] = fragility_idx.loc[ticker, "category"]
        df["ap_fragility_proxy_score"] = float(fragility_idx.loc[ticker, "ap_fragility_proxy_score"])
        df["high_fragility_group"] = bool(fragility_idx.loc[ticker, "high_fragility_group"])
        rows.append(df)
    panel = pd.concat(rows, ignore_index=True)
    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel.to_parquet(DATA_DIR / "panel.parquet")
    panel.to_csv(DATA_DIR / "panel_preview.csv", index=False)
    return panel


def bootstrap_ci_date_spread(values: pd.DataFrame, col: str, reps: int = 5000) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    dates = values["date"].drop_duplicates().to_numpy()
    if len(dates) == 0:
        return float("nan"), float("nan")
    stats_out = []
    for _ in range(reps):
        sampled = rng.choice(dates, size=len(dates), replace=True)
        sample = values.set_index("date").loc[sampled].reset_index()
        stats_out.append(float(sample[col].mean()))
    return tuple(np.quantile(stats_out, [0.025, 0.975]).astype(float))


def high_low_date_spreads(panel: pd.DataFrame, metric: str) -> pd.DataFrame:
    usable = panel.dropna(subset=[metric, "stress_day", "high_fragility_group"]).copy()
    grouped = (
        usable.groupby(["date", "stress_day", "high_fragility_group"])[metric]
        .mean()
        .reset_index()
        .pivot_table(index=["date", "stress_day"], columns="high_fragility_group", values=metric)
        .reset_index()
    )
    grouped = grouped.rename(columns={False: "low", True: "high"})
    grouped["high_minus_low"] = grouped["high"] - grouped["low"]
    return grouped.dropna(subset=["high_minus_low"])


def summarize(panel: pd.DataFrame, fragility: pd.DataFrame) -> tuple[list[EtfResult], dict]:
    rows: list[EtfResult] = []
    for ticker, df in panel.groupby("ticker"):
        usable = df.dropna(subset=["abs_fair_value_residual", "fwd5_rv", "stress_day"])
        stress_df = usable[usable["stress_day"] == 1.0]
        normal_df = usable[usable["stress_day"] == 0.0]
        meta_row = fragility.set_index("ticker").loc[ticker]
        rows.append(
            EtfResult(
                ticker=ticker,
                category=str(meta_row["category"]),
                fragility_score=float(meta_row["ap_fragility_proxy_score"]),
                high_fragility_group=bool(meta_row["high_fragility_group"]),
                observations=int(len(usable)),
                stress_days=int(len(stress_df)),
                stress_abs_residual_mean=float(stress_df["abs_fair_value_residual"].mean()),
                normal_abs_residual_mean=float(normal_df["abs_fair_value_residual"].mean()),
                abs_residual_stress_lift=float(stress_df["abs_fair_value_residual"].mean() - normal_df["abs_fair_value_residual"].mean()),
                stress_fwd5_rv_mean=float(stress_df["fwd5_rv"].mean()),
                normal_fwd5_rv_mean=float(normal_df["fwd5_rv"].mean()),
                fwd5_rv_stress_lift=float(stress_df["fwd5_rv"].mean() - normal_df["fwd5_rv"].mean()),
            )
        )

    result_frame = pd.DataFrame(asdict(row) for row in rows)
    abs_spreads = high_low_date_spreads(panel, "abs_fair_value_residual")
    rv_spreads = high_low_date_spreads(panel, "fwd5_rv")
    abs_stress = abs_spreads[abs_spreads["stress_day"] == 1.0]
    abs_normal = abs_spreads[abs_spreads["stress_day"] == 0.0]
    rv_stress = rv_spreads[rv_spreads["stress_day"] == 1.0]
    rv_normal = rv_spreads[rv_spreads["stress_day"] == 0.0]
    abs_did = float(abs_stress["high_minus_low"].mean() - abs_normal["high_minus_low"].mean())
    rv_did = float(rv_stress["high_minus_low"].mean() - rv_normal["high_minus_low"].mean())
    abs_t = stats.ttest_ind(abs_stress["high_minus_low"], abs_normal["high_minus_low"], equal_var=False, nan_policy="omit")
    rv_t = stats.ttest_ind(rv_stress["high_minus_low"], rv_normal["high_minus_low"], equal_var=False, nan_policy="omit")

    abs_stress_centered = abs_stress[["date", "high_minus_low"]].copy()
    abs_stress_centered["did_component"] = abs_stress_centered["high_minus_low"] - abs_normal["high_minus_low"].mean()
    rv_stress_centered = rv_stress[["date", "high_minus_low"]].copy()
    rv_stress_centered["did_component"] = rv_stress_centered["high_minus_low"] - rv_normal["high_minus_low"].mean()

    spearman_abs = stats.spearmanr(result_frame["fragility_score"], result_frame["abs_residual_stress_lift"], nan_policy="omit")
    spearman_rv = stats.spearmanr(result_frame["fragility_score"], result_frame["fwd5_rv_stress_lift"], nan_policy="omit")
    agg = {
        "tickers_tested": int(result_frame.shape[0]),
        "stress_days": int(panel[["date", "stress_day"]].drop_duplicates()["stress_day"].sum()),
        "valid_dates": int(panel[["date"]].drop_duplicates().shape[0]),
        "high_fragility_tickers": sorted(result_frame[result_frame["high_fragility_group"]]["ticker"].tolist()),
        "low_fragility_tickers": sorted(result_frame[~result_frame["high_fragility_group"]]["ticker"].tolist()),
        "abs_residual_high_minus_low_normal": float(abs_normal["high_minus_low"].mean()),
        "abs_residual_high_minus_low_stress": float(abs_stress["high_minus_low"].mean()),
        "abs_residual_did": abs_did,
        "abs_residual_did_welch_t": float(abs_t.statistic),
        "abs_residual_did_welch_p": float(abs_t.pvalue),
        "abs_residual_did_bootstrap_ci": bootstrap_ci_date_spread(abs_stress_centered.rename(columns={"did_component": "stat"}), "stat"),
        "fwd5_rv_high_minus_low_normal": float(rv_normal["high_minus_low"].mean()),
        "fwd5_rv_high_minus_low_stress": float(rv_stress["high_minus_low"].mean()),
        "fwd5_rv_did": rv_did,
        "fwd5_rv_did_welch_t": float(rv_t.statistic),
        "fwd5_rv_did_welch_p": float(rv_t.pvalue),
        "fwd5_rv_did_bootstrap_ci": bootstrap_ci_date_spread(rv_stress_centered.rename(columns={"did_component": "stat"}), "stat"),
        "spearman_fragility_vs_abs_residual_lift": {
            "rho": float(spearman_abs.statistic),
            "pvalue": float(spearman_abs.pvalue),
        },
        "spearman_fragility_vs_fwd5_rv_lift": {
            "rho": float(spearman_rv.statistic),
            "pvalue": float(spearman_rv.pvalue),
        },
    }
    return rows, agg


def make_figures(rows: list[EtfResult], agg: dict) -> None:
    frame = pd.DataFrame(asdict(row) for row in rows).sort_values("fragility_score")
    colors = np.where(frame["high_fragility_group"], "#b84a3a", "#386cb0")
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(frame["ticker"], frame["fragility_score"], color=colors)
    ax.axhline(frame["fragility_score"].median(), color="black", linewidth=0.8, linestyle="--")
    ax.set_title("K1551 free-data AP-fragility proxy scores")
    ax.set_ylabel("Cross-sectional proxy score")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1551_fragility_scores.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(frame))
    width = 0.38
    ax.bar(x - width / 2, frame["abs_residual_stress_lift"], width=width, label="Abs residual stress lift")
    ax.bar(x + width / 2, frame["fwd5_rv_stress_lift"], width=width, label="Fwd 5d RV stress lift")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(frame["ticker"], rotation=45)
    ax.set_title("K1551 stress-day lifts by ETF")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1551_stress_lifts.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    metrics = ["Abs residual", "Fwd 5d RV"]
    normal = [agg["abs_residual_high_minus_low_normal"], agg["fwd5_rv_high_minus_low_normal"]]
    stress = [agg["abs_residual_high_minus_low_stress"], agg["fwd5_rv_high_minus_low_stress"]]
    x = np.arange(len(metrics))
    ax.bar(x - 0.18, normal, width=0.36, label="Normal")
    ax.bar(x + 0.18, stress, width=0.36, label="Stress")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.set_ylabel("High-fragility minus low-fragility")
    ax.set_title("K1551 group spread on normal vs stress days")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1551_group_spreads.png", dpi=160)
    plt.close(fig)


def run() -> dict:
    ensure_dirs()
    np.random.seed(SEED)
    prices = download_prices()
    meta = fetch_fund_metadata()
    fragility = build_fragility_scores(meta, prices)
    panel = build_panel(prices, fragility)
    rows, agg = summarize(panel, fragility)
    make_figures(rows, agg)

    verdict = "DATA_LIMITED_PROXY_NULL_OR_MIXED"
    abs_ci = agg["abs_residual_did_bootstrap_ci"]
    rv_ci = agg["fwd5_rv_did_bootstrap_ci"]
    if abs_ci[0] > 0 and rv_ci[0] > 0:
        verdict = "PARTIAL_GROUP_SUPPORT_MIXED_ETF_RANKING"
        if (
            agg["spearman_fragility_vs_abs_residual_lift"]["rho"] > 0
            and agg["spearman_fragility_vs_abs_residual_lift"]["pvalue"] < 0.10
            and agg["spearman_fragility_vs_fwd5_rv_lift"]["rho"] > 0
            and agg["spearman_fragility_vs_fwd5_rv_lift"]["pvalue"] < 0.10
        ):
            verdict = "PROXY_SUPPORTS_STRESS_FRAGILITY_CHANNEL"
    elif abs_ci[1] < 0 and rv_ci[1] < 0:
        verdict = "PROXY_REJECTS_STRESS_FRAGILITY_CHANNEL"

    result = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Bond ETF AP-fragility proxy, stress-day fair-value residuals, and forward RV",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "price_source": "yfinance daily OHLCV",
            "fund_metadata_source": "yfinance funds_data snapshot",
            "start": START,
            "end": END,
            "etf_tickers": ETF_TICKERS,
            "factor_tickers": FACTOR_TICKERS,
            "market_stress_definition": "VIX > 25 or MOVE > 120 on date t",
            "ap_concentration_data_available": False,
            "ap_concentration_data_note": "yfinance institutional_holders returned empty/404 for all tested bond ETFs; no ETF-level AP activity or 13F AP concentration is observed.",
            "panel_rows": int(len(panel)),
        },
        "design": {
            "fragility_proxy": "cross-sectional mean z-score of credit complexity, category complexity, holdings turnover, high-low spread proxy, and inverse dollar-volume depth",
            "dislocation_proxy": "absolute residual from a rolling t-1 OLS fair-value model using same-day broad ETF factor returns",
            "lookahead_control": "OLS coefficients use only prior observations; stress-day forward RV target uses t+1 through t+5; no same-day signal is multiplied by same-day future return.",
            "formal_tests": [
                "date-level high-fragility minus low-fragility spread, normal vs stress Welch t-test",
                "5000-rep date bootstrap CI for stress high-low spread net of normal high-low mean",
                "cross-sectional Spearman correlation between fragility score and per-ETF stress lift",
            ],
        },
        "etf_results": [asdict(row) for row in rows],
        "aggregate": agg,
        "figures": [
            "figures/k1551_fragility_scores.png",
            "figures/k1551_stress_lifts.png",
            "figures/k1551_group_spreads.png",
        ],
        "verdict": verdict,
        "limitations": [
            "This is not an AP concentration replication; no ETF-level AP activity or AP market share is observed.",
            "The price/NAV gap is proxied by a rolling fair-value residual, not actual NAV premium/discount.",
            "Fund metadata is a current yfinance snapshot and may not match historical ETF characteristics.",
            "Only eight large bond ETFs are tested; cross-sectional power is low.",
            "Stress-day tests are diagnostic event studies, not a trading strategy.",
            "Knowledge promotion is deferred to the main K1259 writer gate.",
        ],
        "literature_basis": [
            {
                "name": "Bank of Canada Staff Analytical Note 2020-27, Concentration in the market of authorized participants of US fixed-income ETFs",
                "url": "https://www.bankofcanada.ca/2020/11/staff-analytical-note-2020-27/",
            },
            {
                "name": "BIS Quarterly Review, The anatomy of bond ETF arbitrage",
                "url": "https://www.bis.org/publ/qtrpdf/r_qt2103d.htm",
            },
            {
                "name": "Stress-Tested: Municipal Bond ETFs During Market Turmoil",
                "url": "https://afajof.org/management/viewp.php?n=192668",
            },
            {
                "name": "ICI, The Role and Activities of Authorized Participants of Exchange-Traded Funds",
                "url": "https://www.ici.org/pubfile_pdf/ppr_15_aps_etfs.pdf",
            },
        ],
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    result = run()
    print(json.dumps({"experiment_id": result["experiment_id"], "verdict": result["verdict"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
