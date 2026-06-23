"""Retail structured-product complexity ETF proxy and tail-risk diagnostics.

Experiment id:
    research_retail_structured_product_complexity_etf_proxy_t

This is an empirical, free-data proxy diagnostic. It does not observe OTC
structured-note sales or individual retail investors. It asks whether trading
activity in exchange-traded complex payoff products (option-income ETFs,
defined-outcome/buffer ETFs, and single-stock leveraged/inverse ETFs) leads
future realized volatility or downside proxies in their reference assets.

Lookahead rule:
    All predictive regressions use signal_lag1 = signal.shift(1).
"""
from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "research_retail_structured_product_complexity_etf_proxy_t"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
FIG_DIR = ROOT / "figures"
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"
README_PATH = ROOT / "README.md"

SEED = 42
START_DATE = "2021-01-01"
ROLLING_Z = 63
HORIZON = 5
HAC_LAGS = HORIZON - 1
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 20


COMPLEX_GROUPS: dict[str, list[str]] = {
    "option_income": ["JEPI", "JEPQ", "QYLD", "XYLD", "RYLD", "DIVO", "NUSI"],
    "defined_outcome": ["PJUL", "PJAN", "PAPR", "POCT", "BJUL", "BAPR", "BUFR"],
    "single_stock_leveraged": [
        "TSLL",
        "TSLQ",
        "NVDL",
        "NVDS",
        "CONL",
        "CONI",
        "AAPU",
        "AAPD",
        "GGLL",
        "GGLS",
        "MSFU",
        "MSFD",
        "AMDL",
        "AMDS",
    ],
}

SINGLE_STOCK_MAP: dict[str, str] = {
    "TSLL": "TSLA",
    "TSLQ": "TSLA",
    "NVDL": "NVDA",
    "NVDS": "NVDA",
    "CONL": "COIN",
    "CONI": "COIN",
    "AAPU": "AAPL",
    "AAPD": "AAPL",
    "GGLL": "GOOGL",
    "GGLS": "GOOGL",
    "MSFU": "MSFT",
    "MSFD": "MSFT",
    "AMDL": "AMD",
    "AMDS": "AMD",
}

TARGET_TICKERS = ["SPY", "QQQ", "IWM", "TSLA", "NVDA", "COIN", "AAPL", "GOOGL", "MSFT", "AMD"]
VOL_TICKERS = ["^VIX", "^VVIX"]

REFERENCES = [
    {
        "citation": "Celerier, C. and Vallee, B. (2026), Competition, complexity, and security design: evidence from retail investment products, Review of Finance.",
        "url": "https://academic.oup.com/rof/advance-article/doi/10.1093/rof/rfag001/8516563",
        "use": "Motivates product complexity, markups, and tail-risk concerns in retail investment products.",
    },
    {
        "citation": "Huang, Z. (2025), The Rise of Single-Stock ETFs and More Volatile Stock Prices, SSRN.",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5691524",
        "use": "Motivates single-stock ETFs as retail leverage/short-sale constraint circumvention and possible idiosyncratic volatility channel.",
    },
    {
        "citation": "Lenkey, S. L. (2024), The market impact of leveraged ETFs: A Survey of the literature, Quantitative Finance and Economics.",
        "url": "https://www.aimspress.com/article/doi/10.3934/QFE.2024031?viewType=HTML",
        "use": "Cautions that leveraged ETF market-impact evidence is mixed and often methodologically fragile.",
    },
    {
        "citation": "Garcia-Feijoo, L. and Silverstein, B. (2023), The Dynamics of Defined Outcome Exchange Traded Funds, SSRN.",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4371346",
        "use": "Motivates defined-outcome ETF nonlinear option exposure and timing risk.",
    },
    {
        "citation": "SEC Investor Advisory Committee (2023), Draft Recommendation on Single-Stock ETFs and Leveraged ETFs.",
        "url": "https://www.sec.gov/files/20230616-recommendation-single-stock-etfs-and-leveraged-etfs.pdf",
        "use": "Regulatory context for single-stock ETFs as complex, derivative-based, non-diversified products.",
    },
]


@dataclass
class RegressionResult:
    test_id: str
    signal: str
    target: str
    outcome: str
    n_obs: int
    coef: float
    hac_t: float
    p_value: float
    r2: float
    control_coef: float | None


def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def download_one(ticker: str) -> pd.DataFrame | None:
    cache = RAW_DIR / f"{ticker.replace('^', 'IDX_')}_{START_DATE}_ohlcv.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["Date"], index_col="Date")
        return df
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(
                ticker,
                start=START_DATE,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    if "Close" not in keep:
        return None
    df = df[keep].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_csv(cache, index_label="Date")
    return df


def load_market_data(tickers: Iterable[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    diagnostics: dict[str, dict] = {}
    for ticker in sorted(set(tickers)):
        df = download_one(ticker)
        if df is None or df.empty:
            diagnostics[ticker] = {"available": False}
            continue
        close = pd.to_numeric(df["Close"], errors="coerce")
        vol = pd.to_numeric(df.get("Volume", pd.Series(index=df.index, dtype=float)), errors="coerce")
        valid = close.dropna()
        diagnostics[ticker] = {
            "available": bool(len(valid) >= 80),
            "start": str(valid.index.min().date()) if len(valid) else None,
            "end": str(valid.index.max().date()) if len(valid) else None,
            "n_obs": int(len(valid)),
        }
        if len(valid) < 80:
            continue
        closes[ticker] = close
        volumes[ticker] = vol
    close_df = pd.DataFrame(closes).sort_index()
    volume_df = pd.DataFrame(volumes).reindex(close_df.index)
    return close_df, volume_df, diagnostics


def rolling_zscore(series: pd.Series, window: int = ROLLING_Z) -> pd.Series:
    x = np.log1p(series.replace([np.inf, -np.inf], np.nan))
    mean = x.rolling(window, min_periods=max(20, window // 2)).mean()
    std = x.rolling(window, min_periods=max(20, window // 2)).std(ddof=1)
    return (x - mean) / std.replace(0.0, np.nan)


def build_signals(close: pd.DataFrame, volume: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    dollar_volume = close * volume
    product_z = pd.DataFrame(
        {ticker: rolling_zscore(dollar_volume[ticker]) for tickers in COMPLEX_GROUPS.values() for ticker in tickers if ticker in dollar_volume}
    )

    signals: dict[str, pd.Series] = {}
    signal_meta: dict[str, dict] = {}
    for group, tickers in COMPLEX_GROUPS.items():
        available = [ticker for ticker in tickers if ticker in product_z]
        if not available:
            continue
        min_count = 1 if len(available) < 3 else 2
        signal = product_z[available].mean(axis=1, skipna=True)
        signal[product_z[available].notna().sum(axis=1) < min_count] = np.nan
        signals[group] = signal
        signal_meta[group] = {
            "tickers_requested": tickers,
            "tickers_available": available,
            "min_count": min_count,
            "n_non_null": int(signal.notna().sum()),
        }

    for underlying in sorted(set(SINGLE_STOCK_MAP.values())):
        products = [ticker for ticker, mapped in SINGLE_STOCK_MAP.items() if mapped == underlying and ticker in product_z]
        if not products:
            continue
        signal_name = f"single_stock_{underlying}"
        signal = product_z[products].mean(axis=1, skipna=True)
        signals[signal_name] = signal
        signal_meta[signal_name] = {
            "tickers_requested": [ticker for ticker, mapped in SINGLE_STOCK_MAP.items() if mapped == underlying],
            "tickers_available": products,
            "min_count": 1,
            "n_non_null": int(signal.notna().sum()),
        }

    return pd.DataFrame(signals).sort_index(), signal_meta


def forward_sum(series: pd.Series, horizon: int = HORIZON) -> pd.Series:
    return series.rolling(horizon).sum().shift(-(horizon - 1))


def build_targets(close: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    returns = close.pct_change()
    log_returns = np.log(close).diff()
    targets: dict[str, pd.Series] = {}
    target_types: dict[str, str] = {}
    for ticker in TARGET_TICKERS:
        if ticker not in returns:
            continue
        targets[f"{ticker}_rv5"] = forward_sum(returns[ticker].pow(2))
        target_types[f"{ticker}_rv5"] = "future_5d_realized_variance"
        targets[f"{ticker}_left_loss5"] = -forward_sum(log_returns[ticker])
        target_types[f"{ticker}_left_loss5"] = "future_5d_negative_log_return"
    for ticker in VOL_TICKERS:
        if ticker not in log_returns:
            continue
        clean = ticker.replace("^", "")
        targets[f"{clean}_chg5"] = forward_sum(log_returns[ticker])
        target_types[f"{clean}_chg5"] = "future_5d_log_change"
    return pd.DataFrame(targets).sort_index(), target_types


def build_lagged_controls(close: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    returns = close.pct_change()
    log_returns = np.log(close).diff()
    controls: dict[str, pd.Series] = {}
    for target in targets.columns:
        if target.endswith("_rv5"):
            ticker = target.removesuffix("_rv5")
            controls[target] = returns[ticker].pow(2).rolling(HORIZON).sum().shift(1)
        elif target.endswith("_left_loss5"):
            ticker = target.removesuffix("_left_loss5")
            controls[target] = -log_returns[ticker].rolling(HORIZON).sum().shift(1)
        elif target.endswith("_chg5"):
            ticker = "^" + target.removesuffix("_chg5")
            controls[target] = log_returns[ticker].rolling(HORIZON).sum().shift(1)
    return pd.DataFrame(controls).sort_index()


def ols_hac(y: pd.Series, x: pd.Series, control: pd.Series | None, test_id: str, signal: str, target: str, outcome: str) -> RegressionResult | None:
    data = pd.DataFrame({"y": y, "signal": x})
    if control is not None:
        data["control"] = control
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 80 or data["signal"].std(ddof=1) == 0:
        return None
    x_cols = ["signal"] + (["control"] if "control" in data else [])
    X = sm.add_constant(data[x_cols], has_constant="add")
    model = sm.OLS(data["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    coef = float(model.params["signal"])
    t_val = float(model.tvalues["signal"])
    p_val = float(model.pvalues["signal"])
    control_coef = float(model.params["control"]) if "control" in model.params else None
    return RegressionResult(
        test_id=test_id,
        signal=signal,
        target=target,
        outcome=outcome,
        n_obs=int(model.nobs),
        coef=coef,
        hac_t=t_val,
        p_value=p_val,
        r2=float(model.rsquared),
        control_coef=control_coef,
    )


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    q_ranked = np.empty(n)
    running = 1.0
    for i in range(n - 1, -1, -1):
        running = min(running, ranked[i] * n / (i + 1))
        q_ranked[i] = running
    q = np.empty(n)
    q[order] = q_ranked
    return q.tolist()


def run_regressions(signals: pd.DataFrame, targets: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    signal_lag = signals.shift(1)  # lookahead guard: signal from t-1, target starts at t
    tests: list[tuple[str, str, str]] = []
    for signal in ["option_income", "defined_outcome"]:
        if signal not in signal_lag:
            continue
        for target in ["SPY_rv5", "QQQ_rv5", "IWM_rv5", "SPY_left_loss5", "VIX_chg5", "VVIX_chg5"]:
            if target in targets:
                tests.append((signal, target, "index_or_vol_proxy"))
    if "single_stock_leveraged" in signal_lag:
        for target in ["TSLA_rv5", "NVDA_rv5", "COIN_rv5", "AAPL_rv5", "GOOGL_rv5", "MSFT_rv5", "AMD_rv5"]:
            if target in targets:
                tests.append(("single_stock_leveraged", target, "family_to_underlying_rv"))
    for underlying in sorted(set(SINGLE_STOCK_MAP.values())):
        signal = f"single_stock_{underlying}"
        if signal not in signal_lag:
            continue
        for suffix, outcome in [("rv5", "underlying_specific_rv"), ("left_loss5", "underlying_specific_left_loss")]:
            target = f"{underlying}_{suffix}"
            if target in targets:
                tests.append((signal, target, outcome))

    results: list[RegressionResult] = []
    for idx, (signal, target, outcome) in enumerate(tests, start=1):
        result = ols_hac(
            y=targets[target],
            x=signal_lag[signal],
            control=controls[target] if target in controls else None,
            test_id=f"T{idx:02d}",
            signal=signal,
            target=target,
            outcome=outcome,
        )
        if result is not None:
            results.append(result)
    table = pd.DataFrame([asdict(r) for r in results])
    if table.empty:
        return table
    table["abs_t"] = table["hac_t"].abs()
    table["bh_q"] = benjamini_hochberg(table["p_value"].tolist())
    table["bonferroni_p"] = np.minimum(table["p_value"] * len(table), 1.0)
    table["harvey_pass"] = table["abs_t"] >= 3.0
    table["bh_pass_5pct"] = table["bh_q"] <= 0.05
    table = table.sort_values(["abs_t", "n_obs"], ascending=[False, False]).reset_index(drop=True)
    return table


def moving_block_bootstrap_ci(y: pd.Series, x: pd.Series, control: pd.Series | None, reps: int = BOOTSTRAP_REPS) -> dict:
    data = pd.DataFrame({"y": y, "signal": x})
    if control is not None:
        data["control"] = control
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 80:
        return {"available": False, "reason": "n<80"}
    rng = np.random.default_rng(SEED)
    n = len(data)
    coefs: list[float] = []
    x_cols = ["signal"] + (["control"] if "control" in data else [])
    values = data.reset_index(drop=True)
    for _ in range(reps):
        starts = rng.integers(0, max(1, n - BOOTSTRAP_BLOCK + 1), size=math.ceil(n / BOOTSTRAP_BLOCK))
        idx = np.concatenate([np.arange(s, min(s + BOOTSTRAP_BLOCK, n)) for s in starts])[:n]
        sample = values.iloc[idx]
        X = sm.add_constant(sample[x_cols], has_constant="add")
        try:
            model = sm.OLS(sample["y"], X).fit()
            coefs.append(float(model.params["signal"]))
        except Exception:
            continue
    if len(coefs) < max(100, reps // 2):
        return {"available": False, "reason": "too_few_successful_bootstraps", "n_success": len(coefs)}
    arr = np.asarray(coefs)
    return {
        "available": True,
        "seed": SEED,
        "reps": reps,
        "block": BOOTSTRAP_BLOCK,
        "coef_mean": float(np.mean(arr)),
        "ci_025": float(np.quantile(arr, 0.025)),
        "ci_975": float(np.quantile(arr, 0.975)),
        "n_success": int(len(arr)),
    }


def make_figures(signals: pd.DataFrame, reg_table: pd.DataFrame) -> dict[str, str]:
    figures: dict[str, str] = {}
    if not signals.empty:
        fig, ax = plt.subplots(figsize=(11, 5))
        for col in [c for c in ["option_income", "defined_outcome", "single_stock_leveraged"] if c in signals]:
            signals[col].rolling(10, min_periods=3).mean().plot(ax=ax, label=col)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title("Complex payoff ETF demand proxy (10d smoothed volume z-score)")
        ax.set_ylabel("rolling z-score")
        ax.legend()
        fig.tight_layout()
        path = FIG_DIR / "complex_demand_proxy_timeseries.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        figures["demand_timeseries"] = str(path.relative_to(ROOT))

    if not reg_table.empty:
        top = reg_table.head(14).iloc[::-1]
        labels = top["signal"] + " -> " + top["target"]
        colors = np.where(top["harvey_pass"], "#2ca02c", "#7f7f7f")
        fig, ax = plt.subplots(figsize=(11, 6))
        ax.barh(labels, top["hac_t"], color=colors)
        ax.axvline(3.0, color="#2ca02c", ls="--", lw=1)
        ax.axvline(-3.0, color="#2ca02c", ls="--", lw=1)
        ax.axvline(0, color="black", lw=0.8)
        ax.set_title("Top HAC t-statistics (signal lagged one trading day)")
        ax.set_xlabel("HAC t-stat")
        fig.tight_layout()
        path = FIG_DIR / "top_hac_tstats.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        figures["top_hac_tstats"] = str(path.relative_to(ROOT))
    return figures


def summarize_data(close: pd.DataFrame, signals: pd.DataFrame, targets: pd.DataFrame, diagnostics: dict) -> dict:
    valid_tickers = [ticker for ticker, meta in diagnostics.items() if meta.get("available")]
    return {
        "data_source": "yfinance OHLCV daily data",
        "start_date_requested": START_DATE,
        "sample_start": str(close.dropna(how="all").index.min().date()) if len(close) else None,
        "sample_end": str(close.dropna(how="all").index.max().date()) if len(close) else None,
        "n_trading_days_union": int(len(close)),
        "valid_tickers": valid_tickers,
        "missing_or_short_tickers": [ticker for ticker, meta in diagnostics.items() if not meta.get("available")],
        "n_signals": int(signals.shape[1]),
        "n_targets": int(targets.shape[1]),
        "ticker_diagnostics": diagnostics,
    }


def write_readme(results: dict) -> None:
    reg = results.get("regression_summary", {})
    top_rows = results.get("top_results", [])[:8]
    top_md = "\n".join(
        f"| {row['signal']} | {row['target']} | {row['n_obs']} | {row['coef']:.6g} | {row['hac_t']:.2f} | {row['p_value']:.4f} | {row['bh_q']:.4f} |"
        for row in top_rows
    )
    refs_md = "\n".join(f"- {ref['citation']} — {ref['url']}" for ref in REFERENCES)
    figures_md = "\n".join(f"- `{name}`: `{path}`" for name, path in results.get("figures", {}).items())
    README_PATH.write_text(
        f"""# {EXPERIMENT_ID}

## Motivation

This experiment tests whether exchange-traded complex payoff products can serve as a free proxy for retail structured-product complexity demand. The ideal variable would be product-level structured-note sales / AUM / payoff terms. Those data are not public in this repository, so this experiment deliberately uses a narrower ETF proxy.

## Data & Methodology

- Data source: {results['data']['data_source']}.
- Requested start: `{results['data']['start_date_requested']}`.
- Effective sample: `{results['data']['sample_start']}` to `{results['data']['sample_end']}` across {results['data']['n_trading_days_union']} union trading days.
- Complex-product proxy: rolling {ROLLING_Z}d z-score of log dollar volume for option-income ETFs, defined-outcome/buffer ETFs, and single-stock leveraged/inverse ETFs.
- Targets: next {HORIZON} trading-day realized variance, next {HORIZON}d negative log return, and next {HORIZON}d VIX/VVIX log changes.
- Lookahead guard: every predictive regression uses `signal_lag = signals.shift(1)`, so the signal is known no later than t-1 and the target starts at t.
- Inference: OLS with HAC({HAC_LAGS}) standard errors, Benjamini-Hochberg q-values, Bonferroni p-values, and Harvey-style `|t| >= 3` screening.
- Methodology type: empirical proxy diagnostic, not causal identification.

## Main Result

Verdict: **{results['verdict']}**.

- Total regressions: {reg.get('n_tests')}.
- Harvey `|t| >= 3` passes: {reg.get('harvey_pass_count')}.
- BH 5% passes: {reg.get('bh_pass_count')}.
- Bonferroni 5% passes: {reg.get('bonferroni_pass_count')}.

## Top HAC Cells

| signal | target | n | coef | HAC t | p | BH q |
|---|---:|---:|---:|---:|---:|---:|
{top_md}

## Bootstrap Check

```json
{json.dumps(results.get('bootstrap_top_cell', {}), ensure_ascii=False, indent=2)}
```

## Figures

{figures_md}

## References

{refs_md}

## Limitations

- ETF volume is only a proxy for retail complex-payoff demand; it is not OTC structured-note issuance or investor-level exposure.
- Some product families have short histories and product launches during the sample; early periods are sparse by construction.
- Daily close-to-close data cannot test late-day rebalancing pressure directly.
- The tests are predictive associations, not causal identification.
""",
        encoding="utf-8",
    )


def main() -> None:
    ensure_dirs()
    all_tickers = set(TARGET_TICKERS + VOL_TICKERS)
    for tickers in COMPLEX_GROUPS.values():
        all_tickers.update(tickers)

    close, volume, diagnostics = load_market_data(all_tickers)
    signals, signal_meta = build_signals(close, volume)
    targets, target_types = build_targets(close)
    controls = build_lagged_controls(close, targets)
    reg_table = run_regressions(signals, targets, controls)
    if reg_table.empty:
        raise RuntimeError("No valid regression tests were produced")

    signal_lag = signals.shift(1)
    top = reg_table.iloc[0]
    bootstrap = moving_block_bootstrap_ci(
        y=targets[top["target"]],
        x=signal_lag[top["signal"]],
        control=controls[top["target"]] if top["target"] in controls else None,
    )

    figures = make_figures(signals, reg_table)
    reg_csv = ROOT / f"{EXPERIMENT_ID}_regressions.csv"
    signal_csv = ROOT / f"{EXPERIMENT_ID}_signals.csv"
    reg_table.to_csv(reg_csv, index=False)
    signals.to_csv(signal_csv, index_label="Date")

    harvey_pass_count = int(reg_table["harvey_pass"].sum())
    bh_pass_count = int(reg_table["bh_pass_5pct"].sum())
    bonf_pass_count = int((reg_table["bonferroni_p"] <= 0.05).sum())
    if harvey_pass_count == 0 and bh_pass_count == 0 and bonf_pass_count == 0:
        verdict = "NULL_PROXY"
    elif harvey_pass_count > 0 and bonf_pass_count > 0:
        verdict = "POSITIVE_PROXY_NEEDS_CAUSAL_FOLLOWUP"
    else:
        verdict = "WEAK_PROXY_SIGNAL"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "random_seed": SEED,
        "data": summarize_data(close, signals, targets, diagnostics),
        "signal_metadata": signal_meta,
        "target_types": target_types,
        "methodology": {
            "type": "empirical_proxy_diagnostic",
            "lookahead_guard": "signal_lag = signals.shift(1); target starts at t",
            "hac_lags": HAC_LAGS,
            "rolling_z_window": ROLLING_Z,
            "horizon_days": HORIZON,
            "multiple_testing": ["Harvey |t|>=3", "Benjamini-Hochberg", "Bonferroni"],
            "bootstrap": {"reps": BOOTSTRAP_REPS, "block": BOOTSTRAP_BLOCK, "seed": SEED},
        },
        "regression_summary": {
            "n_tests": int(len(reg_table)),
            "harvey_pass_count": harvey_pass_count,
            "bh_pass_count": bh_pass_count,
            "bonferroni_pass_count": bonf_pass_count,
            "max_abs_t": float(reg_table["abs_t"].max()),
            "min_bh_q": float(reg_table["bh_q"].min()),
        },
        "top_results": reg_table.head(12).to_dict(orient="records"),
        "bootstrap_top_cell": {
            "signal": str(top["signal"]),
            "target": str(top["target"]),
            "hac_coef": float(top["coef"]),
            "hac_t": float(top["hac_t"]),
            **bootstrap,
        },
        "figures": figures,
        "tables": {
            "regressions_csv": reg_csv.name,
            "signals_csv": signal_csv.name,
        },
        "references": REFERENCES,
        "verdict": verdict,
        "limitations": [
            "ETF volume proxy is not investor-level structured-note sales.",
            "Short product histories limit inference for newer single-stock leveraged ETFs.",
            "Daily data cannot isolate close-auction rebalancing pressure.",
            "Predictive regressions are not causal identification.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_readme(results)
    print(json.dumps({
        "experiment_id": EXPERIMENT_ID,
        "verdict": verdict,
        "n_tests": int(len(reg_table)),
        "harvey_pass_count": harvey_pass_count,
        "bh_pass_count": bh_pass_count,
        "bonferroni_pass_count": bonf_pass_count,
        "top": reg_table.head(3).to_dict(orient="records"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
