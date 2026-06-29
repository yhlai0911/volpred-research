"""K1574 - Tradable factor ETF implementation shortfall audit.

This experiment compares investable U.S. factor ETFs with academic paper
factors from the Kenneth French data library.  It is an ex-post attribution
diagnostic, not a tradable timing strategy.
"""

from __future__ import annotations

import io
import json
import math
import re
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)

EXPERIMENT_ID = "K1574"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_JSON = HERE / "k1574_results.json"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

SEED = 42
START = "2013-01-01"
YFINANCE_END = "2026-05-02"
BOOTSTRAP_REPS = 1000
BOOTSTRAP_MEAN_BLOCK = 21.0
TRADING_DAYS = 252.0

FACTOR_ETFS = ["MTUM", "VLUE", "QUAL", "USMV", "RPV", "IVE", "IWF"]
EXTRA_TICKERS = ["SPY"]
ALL_TICKERS = FACTOR_ETFS + EXTRA_TICKERS
FACTOR_COLS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]

FRENCH_URLS = {
    "ff5_daily": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "mom_daily": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip",
}

PRIMARY_FACTOR: dict[str, tuple[str | None, int, str]] = {
    "MTUM": ("Mom", 1, "momentum ETF"),
    "VLUE": ("HML", 1, "value ETF"),
    "RPV": ("HML", 1, "deep-value ETF"),
    "IVE": ("HML", 1, "large-cap value ETF"),
    "IWF": ("HML", -1, "large-cap growth ETF / anti-value"),
    "QUAL": ("RMW", 1, "quality/profitability ETF"),
    "USMV": (None, 0, "minimum-volatility ETF; no direct FF6 factor"),
}


@dataclass
class OLSResult:
    beta: np.ndarray
    se: np.ndarray
    t: np.ndarray
    p: np.ndarray
    residuals: np.ndarray
    r2: float
    nobs: int
    nw_lags: int


def _download_zip_member(url: str, cache_path: Path) -> str:
    if cache_path.exists():
        text = cache_path.read_text()
        normalized = _normalize_source_text(text)
        if normalized != text:
            cache_path.write_text(normalized)
        return normalized
    with urlopen(url, timeout=30) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        if not names:
            raise RuntimeError(f"no member in zip: {url}")
        text = zf.read(names[0]).decode("latin1")
    text = _normalize_source_text(text)
    cache_path.write_text(text)
    return text


def _normalize_source_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def _parse_french_daily_csv(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^,?\s*(Mkt-RF|Mom)\b", stripped):
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError("could not find French daily CSV header")

    header = lines[header_idx].strip()
    if header.startswith(","):
        header = "Date" + header
    rows = []
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped:
            break
        if re.match(r"^\d{8},", stripped):
            rows.append(stripped)
    csv_text = "\n".join([header] + rows)
    df = pd.read_csv(io.StringIO(csv_text))
    df.columns = [str(c).strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"].astype(str), format="%Y%m%d")
    df = df.set_index("Date").sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0
    return df.dropna(how="all")


def load_french_factors() -> pd.DataFrame:
    ff5 = _parse_french_daily_csv(
        _download_zip_member(FRENCH_URLS["ff5_daily"], DATA_DIR / "ff5_daily.csv")
    )
    mom = _parse_french_daily_csv(
        _download_zip_member(FRENCH_URLS["mom_daily"], DATA_DIR / "momentum_daily.csv")
    )
    if "Mom" not in mom.columns:
        # Some French library files use a padded Mom column name.
        mom = mom.rename(columns={mom.columns[0]: "Mom"})
    factors = ff5.join(mom[["Mom"]], how="inner")
    factors = factors.rename(columns={c: c.strip() for c in factors.columns})
    factors = factors[FACTOR_COLS + ["RF"]].dropna()
    return factors


def _extract_yf_field(raw: pd.DataFrame, field: str) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        if field in raw.columns.get_level_values(0):
            out = raw[field].copy()
        elif field in raw.columns.get_level_values(1):
            out = raw.xs(field, axis=1, level=1).copy()
        else:
            raise KeyError(field)
    else:
        out = raw[[field]].copy()
        out.columns = [ALL_TICKERS[0]]
    out.columns = [str(c).strip() for c in out.columns]
    return out.reindex(columns=ALL_TICKERS)


def load_ohlcv() -> dict[str, pd.DataFrame]:
    cache_paths = {
        "close": DATA_DIR / "close_yfinance.csv",
        "high": DATA_DIR / "high_yfinance.csv",
        "low": DATA_DIR / "low_yfinance.csv",
        "volume": DATA_DIR / "volume_yfinance.csv",
    }
    if all(p.exists() for p in cache_paths.values()):
        data = {
            name: pd.read_csv(path, index_col=0, parse_dates=True)
            for name, path in cache_paths.items()
        }
        if all(set(ALL_TICKERS).issubset(df.columns) for df in data.values()):
            return {k: v[ALL_TICKERS].sort_index() for k, v in data.items()}

    import yfinance as yf

    raw = yf.download(
        ALL_TICKERS,
        start=START,
        end=YFINANCE_END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    data = {
        "close": _extract_yf_field(raw, "Close"),
        "high": _extract_yf_field(raw, "High"),
        "low": _extract_yf_field(raw, "Low"),
        "volume": _extract_yf_field(raw, "Volume"),
    }
    for name, df in data.items():
        df = df.dropna(how="all").sort_index()
        df.to_csv(cache_paths[name])
        data[name] = df
    return data


def hac_ols(y: np.ndarray, x: np.ndarray) -> OLSResult:
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    valid = np.isfinite(y) & np.isfinite(x).all(axis=1)
    y = y[valid]
    x = x[valid]
    nobs, nvar = x.shape
    if nobs <= nvar + 5:
        raise ValueError("not enough observations for HAC OLS")

    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    resid = y - x @ beta
    y_centered = y - y.mean()
    sst = float(y_centered @ y_centered)
    sse = float(resid @ resid)
    r2 = 1.0 - sse / sst if sst > 0 else float("nan")

    nw_lags = max(1, int(math.floor(4.0 * (nobs / 100.0) ** (2.0 / 9.0))))
    nw_lags = min(nw_lags, nobs // 4)
    z = x * resid[:, None]
    meat = z.T @ z
    for lag in range(1, nw_lags + 1):
        weight = 1.0 - lag / (nw_lags + 1.0)
        gamma = z[lag:].T @ z[:-lag]
        meat += weight * (gamma + gamma.T)
    cov = xtx_inv @ meat @ xtx_inv
    diag = np.maximum(np.diag(cov), 0.0)
    se = np.sqrt(diag)
    t_stat = np.divide(beta, se, out=np.zeros_like(beta), where=se > 0)
    p_val = 2.0 * stats.t.sf(np.abs(t_stat), df=max(nobs - nvar, 1))
    return OLSResult(beta=beta, se=se, t=t_stat, p=p_val, residuals=resid, r2=r2, nobs=nobs, nw_lags=nw_lags)


def max_drawdown(ret: pd.Series) -> float:
    wealth = (1.0 + ret.dropna()).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    return float(drawdown.min())


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    items = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (key, p_val) in enumerate(items, start=1):
        adj = min(1.0, (m - rank + 1) * p_val)
        running = max(running, adj)
        adjusted[key] = running
    return adjusted


def stationary_bootstrap_indices(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    out = np.empty(n, dtype=int)
    out[0] = int(rng.integers(0, n))
    p_new = 1.0 / mean_block
    for i in range(1, n):
        if rng.random() < p_new:
            out[i] = int(rng.integers(0, n))
        else:
            out[i] = (out[i - 1] + 1) % n
    return out


def summarize_liquidity(
    ticker: str,
    returns: pd.DataFrame,
    close: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    volume: pd.DataFrame,
    index: pd.DatetimeIndex,
) -> dict[str, float]:
    c = close[ticker].reindex(index)
    v = volume[ticker].reindex(index)
    h = high[ticker].reindex(index)
    l = low[ticker].reindex(index)
    r = returns[ticker].reindex(index)
    dollar_volume = c * v
    with np.errstate(divide="ignore", invalid="ignore"):
        amihud = (r.abs() / dollar_volume.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    high_low = ((h - l) / c).replace([np.inf, -np.inf], np.nan)
    return {
        "median_dollar_volume": float(dollar_volume.median()),
        "amihud_mean_x1e9": float(amihud.mean() * 1e9),
        "mean_daily_high_low_pct": float(high_low.mean()),
    }


def regression_table(
    returns: pd.DataFrame,
    factors: pd.DataFrame,
    ohlcv: dict[str, pd.DataFrame],
) -> tuple[dict[str, Any], dict[str, OLSResult]]:
    x = factors[FACTOR_COLS].to_numpy()
    names = ["Intercept"] + FACTOR_COLS
    out: dict[str, Any] = {}
    raw_results: dict[str, OLSResult] = {}
    alpha_p: dict[str, float] = {}
    spy = returns["SPY"].reindex(factors.index)

    for ticker in FACTOR_ETFS:
        y = returns[ticker].reindex(factors.index) - factors["RF"]
        result = hac_ols(y.to_numpy(), x)
        raw_results[ticker] = result
        coef = dict(zip(names, result.beta))
        tstat = dict(zip(names, result.t))
        pval = dict(zip(names, result.p))
        alpha_p[ticker] = float(pval["Intercept"])

        primary_col, sign, role = PRIMARY_FACTOR[ticker]
        if primary_col is not None:
            beta_primary = float(sign * coef[primary_col])
            t_primary = float(sign * tstat[primary_col])
            unit_factor_mean = float((sign * factors[primary_col]).mean() * TRADING_DAYS)
            beta_scaled_factor_mean = float(beta_primary * unit_factor_mean)
            unit_factor_gap = float(unit_factor_mean - beta_scaled_factor_mean)
        else:
            beta_primary = None
            t_primary = None
            unit_factor_mean = None
            beta_scaled_factor_mean = None
            unit_factor_gap = None

        resid = pd.Series(result.residuals, index=factors.index[-len(result.residuals) :])
        etf_ret = returns[ticker].reindex(factors.index)
        liquidity = summarize_liquidity(
            ticker,
            returns,
            ohlcv["close"],
            ohlcv["high"],
            ohlcv["low"],
            ohlcv["volume"],
            factors.index,
        )
        out[ticker] = {
            "role": role,
            "nobs": result.nobs,
            "nw_lags": result.nw_lags,
            "ann_total_return": float(etf_ret.mean() * TRADING_DAYS),
            "ann_excess_return": float(y.mean() * TRADING_DAYS),
            "ann_vol": float(etf_ret.std(ddof=1) * math.sqrt(TRADING_DAYS)),
            "max_drawdown": max_drawdown(etf_ret),
            "tracking_error_vs_spy": float((etf_ret - spy).std(ddof=1) * math.sqrt(TRADING_DAYS)),
            "alpha_ann": float(coef["Intercept"] * TRADING_DAYS),
            "alpha_t": float(tstat["Intercept"]),
            "alpha_p_raw": float(pval["Intercept"]),
            "r2": float(result.r2),
            "residual_vol_ann": float(resid.std(ddof=1) * math.sqrt(TRADING_DAYS)),
            "residual_vol_share": float(
                (resid.std(ddof=1) * math.sqrt(TRADING_DAYS))
                / (etf_ret.std(ddof=1) * math.sqrt(TRADING_DAYS))
            ),
            "factor_betas": {col: float(coef[col]) for col in FACTOR_COLS},
            "factor_tstats": {col: float(tstat[col]) for col in FACTOR_COLS},
            "primary_factor": primary_col,
            "primary_direction": sign,
            "primary_directional_beta": beta_primary,
            "primary_directional_beta_t": t_primary,
            "unit_paper_factor_ann_mean": unit_factor_mean,
            "beta_scaled_paper_factor_ann_mean": beta_scaled_factor_mean,
            "unit_factor_gap_ann": unit_factor_gap,
            **liquidity,
        }

    alpha_holm = holm_adjust(alpha_p)
    for ticker, p_adj in alpha_holm.items():
        out[ticker]["alpha_p_holm"] = float(p_adj)
        out[ticker]["alpha_negative_harvey_pass"] = bool(out[ticker]["alpha_t"] < -3.0)
        out[ticker]["alpha_negative_holm_5pct"] = bool(
            out[ticker]["alpha_ann"] < 0.0 and p_adj < 0.05
        )
    return out, raw_results


def bootstrap_median_alpha(returns: pd.DataFrame, factors: pd.DataFrame) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    x_full = factors[FACTOR_COLS].to_numpy()
    y_full = {
        ticker: (returns[ticker].reindex(factors.index) - factors["RF"]).to_numpy()
        for ticker in FACTOR_ETFS
    }
    n = len(factors)
    medians = []
    negative_shares = []
    for _ in range(BOOTSTRAP_REPS):
        idx = stationary_bootstrap_indices(n, BOOTSTRAP_MEAN_BLOCK, rng)
        x = x_full[idx]
        alphas = []
        for ticker in FACTOR_ETFS:
            y = y_full[ticker][idx]
            res = hac_ols(y, x)
            alphas.append(float(res.beta[0] * TRADING_DAYS))
        alpha_arr = np.asarray(alphas)
        medians.append(float(np.median(alpha_arr)))
        negative_shares.append(float(np.mean(alpha_arr < 0.0)))
    q = np.quantile(medians, [0.025, 0.5, 0.975])
    share_q = np.quantile(negative_shares, [0.025, 0.5, 0.975])
    return {
        "method": "stationary_bootstrap_common_date_indices",
        "seed": SEED,
        "reps": BOOTSTRAP_REPS,
        "mean_block_days": BOOTSTRAP_MEAN_BLOCK,
        "median_alpha_ann_ci95": [float(q[0]), float(q[2])],
        "median_alpha_ann_bootstrap_median": float(q[1]),
        "negative_alpha_share_ci95": [float(share_q[0]), float(share_q[2])],
        "negative_alpha_share_bootstrap_median": float(share_q[1]),
    }


def make_figures(results: dict[str, Any]) -> list[str]:
    tickers = FACTOR_ETFS
    alpha = np.array([results["etf_regressions"][t]["alpha_ann"] for t in tickers])
    alpha_holm = np.array([results["etf_regressions"][t]["alpha_p_holm"] for t in tickers])
    primary_beta = np.array(
        [
            results["etf_regressions"][t]["primary_directional_beta"]
            if results["etf_regressions"][t]["primary_directional_beta"] is not None
            else np.nan
            for t in tickers
        ],
        dtype=float,
    )
    resid_share = np.array([results["etf_regressions"][t]["residual_vol_share"] for t in tickers])
    vol = np.array([results["etf_regressions"][t]["ann_vol"] for t in tickers])
    mdd = np.array([results["etf_regressions"][t]["max_drawdown"] for t in tickers])
    amihud = np.array([results["etf_regressions"][t]["amihud_mean_x1e9"] for t in tickers])

    fig_paths: list[str] = []

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    colors = ["#a94442" if a < 0 else "#2b6f9e" for a in alpha]
    axes[0].bar(tickers, alpha * 100.0, color=colors)
    axes[0].axhspan(-4.0, -2.0, color="#f3c969", alpha=0.28, label="2-4 pct shortfall band")
    axes[0].axhline(0, color="#222222", linewidth=0.8)
    for i, p in enumerate(alpha_holm):
        if p < 0.05:
            axes[0].text(i, alpha[i] * 100.0, "*", ha="center", va="bottom", fontsize=12)
    axes[0].set_title("FF6 alpha after ETF implementation")
    axes[0].set_ylabel("annualized alpha (%)")
    axes[0].legend(frameon=False, fontsize=8)

    axes[1].bar(tickers, primary_beta, color="#5b7f52")
    axes[1].axhline(1.0, color="#222222", linewidth=0.8, linestyle="--")
    axes[1].axhline(0.0, color="#222222", linewidth=0.8)
    axes[1].set_title("Directional loading on intended paper factor")
    axes[1].set_ylabel("directional beta")
    for ax in axes:
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "k1574_alpha_and_factor_loading.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    fig_paths.append(str(path.relative_to(HERE)))

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    axes[0].bar(tickers, vol * 100.0, color="#4f6d7a", label="ETF vol")
    axes[0].bar(tickers, resid_share * vol * 100.0, color="#c1666b", alpha=0.7, label="residual vol")
    axes[0].set_title("Total vs residual volatility")
    axes[0].set_ylabel("annualized vol (%)")
    axes[0].legend(frameon=False, fontsize=8)

    axes[1].bar(tickers, mdd * 100.0, color="#806d9e")
    axes[1].set_title("ETF max drawdown")
    axes[1].set_ylabel("max drawdown (%)")
    axes[1].axhline(0, color="#222222", linewidth=0.8)

    axes[2].bar(tickers, amihud, color="#8a7f45")
    axes[2].set_title("Amihud cost proxy")
    axes[2].set_ylabel("mean |ret| / dollar volume x 1e9")
    for ax in axes:
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "k1574_risk_and_cost_proxies.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    fig_paths.append(str(path.relative_to(HERE)))

    return fig_paths


def build_results() -> dict[str, Any]:
    factors = load_french_factors()
    ohlcv = load_ohlcv()
    returns = ohlcv["close"].pct_change()

    aligned_index = returns.index.intersection(factors.index)
    panel = pd.concat(
        [returns.reindex(aligned_index), factors.reindex(aligned_index)],
        axis=1,
    ).dropna(subset=ALL_TICKERS + FACTOR_COLS + ["RF"])
    returns_aligned = panel[ALL_TICKERS]
    factors_aligned = panel[FACTOR_COLS + ["RF"]]

    etf_results, _ = regression_table(returns_aligned, factors_aligned, ohlcv)
    bootstrap = bootstrap_median_alpha(returns_aligned, factors_aligned)

    alpha_values = np.array([etf_results[t]["alpha_ann"] for t in FACTOR_ETFS])
    negative_count = int(np.sum(alpha_values < 0.0))
    shortfall_band_count = int(np.sum((alpha_values <= -0.02) & (alpha_values >= -0.04)))
    alpha_pass_count = int(np.sum([etf_results[t]["alpha_negative_holm_5pct"] for t in FACTOR_ETFS]))
    beta_positive_count = int(
        np.sum(
            [
                (
                    etf_results[t]["primary_directional_beta"] is not None
                    and etf_results[t]["primary_directional_beta"] > 0
                )
                for t in FACTOR_ETFS
            ]
        )
    )
    sign_test = stats.binomtest(negative_count, len(FACTOR_ETFS), 0.5, alternative="greater")

    if alpha_pass_count >= 3 and bootstrap["median_alpha_ann_ci95"][1] < 0:
        verdict = "EVIDENCE_OF_NEGATIVE_IMPLEMENTATION_ALPHA"
    elif shortfall_band_count >= 3:
        verdict = "DESCRIPTIVE_2_TO_4_PCT_ALPHA_SHORTFALL_CLUSTER"
    elif beta_positive_count >= 5 and alpha_pass_count == 0:
        verdict = "EXPOSURE_DILUTION_WITHOUT_SIGNIFICANT_ALPHA_SHORTFALL"
    else:
        verdict = "MIXED_OR_NULL_IMPLEMENTATION_SHORTFALL"

    results: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": pd.Timestamp.now(tz="Asia/Taipei").isoformat(),
        "seed": SEED,
        "question": "Do tradable factor ETFs preserve academic paper-factor alpha, or does implementation show up as lower alpha, higher residual risk, drawdown amplification, and cost proxies?",
        "data": {
            "etf_source": "yfinance adjusted OHLCV downloaded by yfinance",
            "factor_source": "Kenneth French Data Library daily five-factor and momentum CSV files",
            "tickers": ALL_TICKERS,
            "factor_columns": FACTOR_COLS,
            "requested_start": START,
            "requested_yfinance_end_exclusive": YFINANCE_END,
            "aligned_start": str(factors_aligned.index.min().date()),
            "aligned_end": str(factors_aligned.index.max().date()),
            "n_daily_rows": int(len(factors_aligned)),
        },
        "method": {
            "attribution": "Daily ETF excess returns regressed on FF5 plus momentum with an intercept.",
            "inference": "Newey-West HAC standard errors; alpha p-values Holm-adjusted across ETFs.",
            "bootstrap": "Stationary bootstrap over common date indices for cross-ETF median alpha.",
            "lookahead_note": "Same-day factors and ETF returns are used only for ex-post attribution. No trading signal is formed; no same-day signal is multiplied by same-day future return.",
            "cost_proxy": "Dollar-volume Amihud proxy and daily high-low range from ETF OHLCV; no live bid-ask or holdings-turnover data are claimed.",
        },
        "literature_used": [
            {
                "citation": "Fama and French (2015), A five-factor asset pricing model",
                "role": "baseline paper-factor model",
            },
            {
                "citation": "Carhart (1997), On Persistence in Mutual Fund Performance",
                "role": "momentum factor control",
            },
            {
                "citation": "Frazzini, Israel, and Moskowitz, Trading Costs of Asset Pricing Anomalies",
                "role": "implementation-cost motivation",
            },
            {
                "citation": "Novy-Marx and Velikov, A Taxonomy of Anomalies and Their Trading Costs",
                "role": "trading-cost/anomaly decay motivation",
            },
        ],
        "etf_regressions": etf_results,
        "aggregate": {
            "median_alpha_ann": float(np.median(alpha_values)),
            "mean_alpha_ann": float(np.mean(alpha_values)),
            "negative_alpha_count": negative_count,
            "negative_alpha_sign_test_p_greater": float(sign_test.pvalue),
            "alpha_in_minus_2_to_minus_4_pct_band_count": shortfall_band_count,
            "alpha_negative_holm_5pct_count": alpha_pass_count,
            "directional_primary_beta_positive_count": beta_positive_count,
            "median_residual_vol_share": float(
                np.median([etf_results[t]["residual_vol_share"] for t in FACTOR_ETFS])
            ),
            "median_tracking_error_vs_spy": float(
                np.median([etf_results[t]["tracking_error_vs_spy"] for t in FACTOR_ETFS])
            ),
            "verdict": verdict,
        },
        "bootstrap": bootstrap,
        "limitations": [
            "ETF regressions are attribution diagnostics, not a causal implementation-cost estimate.",
            "Kenneth French factors are long-short paper portfolios, while most ETFs here are long-only and benchmark constrained.",
            "Expense ratios, securities lending, rebalance calendars, and holdings-level transaction costs are not observed.",
            "USMV has no direct FF6 low-volatility factor, so its primary-factor capture is not scored like value, momentum, quality, or growth.",
        ],
    }
    results["figures"] = make_figures(results)
    return results


def main() -> None:
    results = build_results()
    RESULTS_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(results["aggregate"], indent=2))
    print(f"wrote {RESULTS_JSON}")


if __name__ == "__main__":
    main()
