#!/usr/bin/env python3
"""Labor-supply / immigration public proxies as wage-sensitive ETF RV priors.

Experiment question:
Do low labor-force growth, weak foreign-born labor-force growth, high labor
tightness, or wage pressure lead realized volatility in wage-sensitive sectors
(homebuilders, retail, industrials)?

Research-honesty guardrails:
- Public proxy only: FRED/BLS monthly series are not true immigration-flow data.
- Signal timing: macro features observed at month t-1 predict ETF RV from month t
  onward. The code uses explicit ``signals.shift(1)``.
- No same-month signal/return multiplication.
- Tests use Newey-West HAC and Holm correction across the primary family.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from statsmodels.stats.multitest import multipletests


EXPERIMENT_ID = "research_labor_force_growth_immigration_shock_wage_sensit"
SEED = 42
START = "2006-01-01"
END = "2026-06-29"
MIN_Z_MONTHS = 60
TRADING_DAYS = 252

ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"

FRED_SERIES = {
    "CLF16OV": "Civilian labor force level, thousands",
    "PAYEMS": "All employees, total nonfarm, thousands",
    "JTSJOL": "Job openings, total nonfarm, thousands",
    "CES0500000003": "Average hourly earnings, total private",
    "LNU01073395": "Foreign-born civilian labor force level, thousands",
}

TARGET_ETFS = {
    "XHB": "homebuilders / construction labor sensitivity",
    "XRT": "retail labor sensitivity",
    "XLI": "industrials / manufacturing proxy",
}
BENCHMARK = "SPY"
TICKERS = [BENCHMARK, *TARGET_ETFS.keys()]
HORIZONS_MONTHS = [1, 3]

SIGNAL_COLUMNS = [
    "low_labor_force_growth_z",
    "low_foreign_born_lf_growth_z",
    "payroll_labor_supply_gap_z",
    "labor_tightness_z",
    "wage_growth_z",
    "labor_supply_stress_z",
]


@dataclass(frozen=True)
class RegressionSpec:
    etf: str
    horizon_months: int
    signal: str
    y_col: str
    controls: tuple[str, ...]


def _fred_csv_url(series_id: str) -> str:
    return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def fetch_fred_monthly() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for series_id in FRED_SERIES:
        df = pd.read_csv(_fred_csv_url(series_id), parse_dates=["observation_date"])
        df = df.rename(columns={"observation_date": "date", series_id: series_id})
        df[series_id] = pd.to_numeric(df[series_id].replace(".", np.nan), errors="coerce")
        frames.append(df.set_index("date")[[series_id]])
    macro = pd.concat(frames, axis=1, sort=True).sort_index()
    macro = macro.loc[pd.Timestamp(START) :]
    macro.index = macro.index.to_period("M").to_timestamp("M")
    return macro


def fetch_adjusted_close() -> pd.DataFrame:
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = TICKERS
    close = close.dropna(axis=1, how="all")
    missing = sorted(set(TICKERS) - set(close.columns))
    if missing:
        raise RuntimeError(f"Missing yfinance adjusted close columns: {missing}")
    return close[TICKERS].sort_index()


def _drop_partial_last_month(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    last_date = frame.index.max()
    month_end = last_date.to_period("M").to_timestamp("M")
    if last_date.normalize() < month_end:
        return frame.loc[frame.index.to_period("M") < last_date.to_period("M")]
    return frame


def _forward_rolling_sum(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    return frame.iloc[::-1].rolling(horizon, min_periods=horizon).sum().iloc[::-1]


def build_market_panel(close: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    close = _drop_partial_last_month(close)
    daily_ret = np.log(close).diff().dropna(how="all")
    month_index = daily_ret.index.to_period("M").to_timestamp("M")

    monthly_sq = daily_ret.pow(2).groupby(month_index).sum()
    monthly_days = daily_ret.groupby(month_index).count()
    monthly_ret = daily_ret.groupby(month_index).sum()

    panel = pd.DataFrame(index=monthly_sq.index)
    for ticker in TICKERS:
        rv1 = monthly_sq[ticker] * TRADING_DAYS / monthly_days[ticker]
        panel[f"{ticker}_log_rv_lag1"] = np.log(rv1).shift(1)
        panel[f"{ticker}_ret_lag1"] = monthly_ret[ticker].shift(1)
        for horizon in HORIZONS_MONTHS:
            fwd_sq = _forward_rolling_sum(monthly_sq[[ticker]], horizon)[ticker]
            fwd_days = _forward_rolling_sum(monthly_days[[ticker]], horizon)[ticker]
            fwd_rv = fwd_sq * TRADING_DAYS / fwd_days
            panel[f"{ticker}_log_rv_fwd_{horizon}m"] = np.log(fwd_rv)
            panel[f"{ticker}_rv_fwd_{horizon}m"] = fwd_rv

    metadata = {
        "start": str(close.index.min().date()),
        "end": str(close.index.max().date()),
        "daily_rows": int(len(close)),
        "monthly_rows": int(len(panel)),
        "dropped_partial_last_month": bool(close.index.max().normalize() < close.index.max().to_period("M").to_timestamp("M")),
        "last_month_in_panel": str(panel.index.max().date()) if len(panel) else None,
    }
    return panel, metadata


def expanding_z(series: pd.Series, min_periods: int = MIN_Z_MONTHS) -> pd.Series:
    mean = series.expanding(min_periods=min_periods).mean().shift(1)
    std = series.expanding(min_periods=min_periods).std(ddof=0).shift(1)
    return (series - mean) / std.replace(0.0, np.nan)


def build_macro_signals(macro: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    features = pd.DataFrame(index=macro.index)
    features["labor_force_growth_12m"] = macro["CLF16OV"].pct_change(12)
    features["foreign_born_lf_growth_12m"] = macro["LNU01073395"].pct_change(12)
    features["payroll_labor_supply_gap_12m_k"] = macro["PAYEMS"].diff(12) - macro["CLF16OV"].diff(12)
    features["job_openings_lf_ratio"] = macro["JTSJOL"] / macro["CLF16OV"]
    features["wage_growth_12m"] = macro["CES0500000003"].pct_change(12)

    z = pd.DataFrame(index=features.index)
    z["low_labor_force_growth_z"] = expanding_z(-features["labor_force_growth_12m"])
    z["low_foreign_born_lf_growth_z"] = expanding_z(-features["foreign_born_lf_growth_12m"])
    z["payroll_labor_supply_gap_z"] = expanding_z(features["payroll_labor_supply_gap_12m_k"])
    z["labor_tightness_z"] = expanding_z(features["job_openings_lf_ratio"])
    z["wage_growth_z"] = expanding_z(features["wage_growth_12m"])

    components = [
        "low_labor_force_growth_z",
        "low_foreign_born_lf_growth_z",
        "payroll_labor_supply_gap_z",
        "labor_tightness_z",
        "wage_growth_z",
    ]
    complete_components = z[components].count(axis=1) == len(components)
    z["labor_supply_stress_z"] = z[components].mean(axis=1)
    z.loc[~complete_components, "labor_supply_stress_z"] = np.nan

    # HARD lookahead guard: month t-1 macro signal predicts month t market RV.
    signal_panel = z[SIGNAL_COLUMNS].shift(1)

    metadata = {
        "macro_start": str(macro.index.min().date()),
        "macro_end": str(macro.index.max().date()),
        "macro_rows": int(len(macro)),
        "min_expanding_z_months": MIN_Z_MONTHS,
        "signal_lag_months": 1,
        "lookahead_guard": "All SIGNAL_COLUMNS are generated by z.shift(1); target month t uses macro signal from month t-1.",
        "feature_definitions": {
            "low_labor_force_growth_z": "- YoY civilian labor-force growth, expanding z",
            "low_foreign_born_lf_growth_z": "- YoY foreign-born labor-force growth, expanding z",
            "payroll_labor_supply_gap_z": "YoY payroll change minus YoY labor-force change, expanding z",
            "labor_tightness_z": "JOLTS openings / civilian labor force, expanding z",
            "wage_growth_z": "YoY average hourly earnings growth, expanding z",
            "labor_supply_stress_z": "Equal-weight average of the five z-scores above",
        },
    }
    return signal_panel, metadata


def make_regression_specs() -> list[RegressionSpec]:
    specs: list[RegressionSpec] = []
    for etf in TARGET_ETFS:
        controls = (
            f"{etf}_log_rv_lag1",
            f"{etf}_ret_lag1",
            f"{BENCHMARK}_log_rv_lag1",
            f"{BENCHMARK}_ret_lag1",
        )
        for horizon in HORIZONS_MONTHS:
            y_col = f"{etf}_log_rv_fwd_{horizon}m"
            for signal in SIGNAL_COLUMNS:
                specs.append(RegressionSpec(etf, horizon, signal, y_col, controls))
    return specs


def fit_hac(panel: pd.DataFrame, spec: RegressionSpec) -> dict[str, Any]:
    cols = [spec.y_col, spec.signal, *spec.controls]
    df = panel[cols].replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 72:
        return {
            "etf": spec.etf,
            "horizon_months": spec.horizon_months,
            "signal": spec.signal,
            "insufficient": True,
            "n_months": int(len(df)),
        }

    y = df[spec.y_col]
    x_cols = [spec.signal, *spec.controls]
    x = sm.add_constant(df[x_cols], has_constant="add")
    fit = sm.OLS(y, x).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": max(1, spec.horizon_months), "use_correction": True},
    )
    coef = float(fit.params[spec.signal])
    t_stat = float(fit.tvalues[spec.signal])
    p_value = float(fit.pvalues[spec.signal])
    return {
        "etf": spec.etf,
        "etf_description": TARGET_ETFS[spec.etf],
        "horizon_months": spec.horizon_months,
        "signal": spec.signal,
        "coef_log_rv": coef,
        "t_stat": t_stat,
        "p_value_two_sided": p_value,
        "n_months": int(len(df)),
        "r_squared": float(fit.rsquared),
        "sample_start": str(df.index.min().date()),
        "sample_end": str(df.index.max().date()),
        "controls": list(spec.controls),
        "insufficient": False,
    }


def add_multiple_testing(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = [r for r in results if not r.get("insufficient")]
    pvals = np.array([r["p_value_two_sided"] for r in valid], dtype=float)
    reject_holm, p_holm, _, _ = multipletests(pvals, alpha=0.05, method="holm")
    p_bonf = np.minimum(pvals * len(pvals), 1.0)
    for r, holm, bonf, reject in zip(valid, p_holm, p_bonf, reject_holm):
        r["p_holm"] = float(holm)
        r["p_bonferroni"] = float(bonf)
        r["holm_significant"] = bool(reject)
        r["positive_harvey_holm_support"] = bool(
            r["coef_log_rv"] > 0 and abs(r["t_stat"]) >= 3.0 and r["p_holm"] < 0.05
        )
    return results


def moving_block_bootstrap_coef(
    panel: pd.DataFrame,
    spec: RegressionSpec,
    *,
    n_boot: int = 1000,
    block: int = 6,
    seed: int = SEED,
) -> dict[str, Any]:
    cols = [spec.y_col, spec.signal, *spec.controls]
    df = panel[cols].replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < block * 6:
        return {"insufficient": True, "n_months": int(len(df))}

    rng = np.random.default_rng(seed)
    n = len(df)
    n_blocks = int(np.ceil(n / block))
    max_start = n - block
    coefs = np.empty(n_boot)
    x_cols = [spec.signal, *spec.controls]
    values = df.to_numpy()
    col_index = {name: i for i, name in enumerate(cols)}
    y_idx = col_index[spec.y_col]
    signal_param_index = 1

    for b in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        sample = np.concatenate([values[s : s + block] for s in starts], axis=0)[:n]
        y = sample[:, y_idx]
        x = sample[:, [col_index[c] for c in x_cols]]
        x = sm.add_constant(x, has_constant="add")
        try:
            coefs[b] = sm.OLS(y, x).fit().params[signal_param_index]
        except np.linalg.LinAlgError:
            coefs[b] = np.nan

    coefs = coefs[np.isfinite(coefs)]
    if len(coefs) < n_boot * 0.9:
        return {"insufficient": True, "n_valid_boot": int(len(coefs))}
    lo, hi = np.percentile(coefs, [2.5, 97.5])
    return {
        "insufficient": False,
        "coef_ci95_low": float(lo),
        "coef_ci95_high": float(hi),
        "prob_positive": float(np.mean(coefs > 0)),
        "n_boot": n_boot,
        "block_months": block,
        "seed": seed,
    }


def top_decile_diagnostics(panel: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    signal = "labor_supply_stress_z"
    for etf in TARGET_ETFS:
        for horizon in HORIZONS_MONTHS:
            y_col = f"{etf}_log_rv_fwd_{horizon}m"
            df = panel[[signal, y_col]].dropna()
            if len(df) < 72:
                continue
            threshold = df[signal].quantile(0.90)
            high = df[df[signal] >= threshold][y_col]
            rest = df[df[signal] < threshold][y_col]
            out.append(
                {
                    "signal": signal,
                    "etf": etf,
                    "horizon_months": horizon,
                    "threshold": float(threshold),
                    "n_high": int(len(high)),
                    "n_rest": int(len(rest)),
                    "mean_log_rv_high": float(high.mean()),
                    "mean_log_rv_rest": float(rest.mean()),
                    "mean_diff_high_minus_rest": float(high.mean() - rest.mean()),
                }
            )
    return out


def subsample_sensitivity(panel: pd.DataFrame, supported_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-fit supported full-sample cells before and after 2020.

    This is not a replacement for a true OOS design, but it catches full-sample
    results that are concentrated in one macro regime.
    """
    out: list[dict[str, Any]] = []
    for result in supported_results:
        etf = result["etf"]
        horizon = int(result["horizon_months"])
        signal = result["signal"]
        y_col = f"{etf}_log_rv_fwd_{horizon}m"
        controls = (
            f"{etf}_log_rv_lag1",
            f"{etf}_ret_lag1",
            f"{BENCHMARK}_log_rv_lag1",
            f"{BENCHMARK}_ret_lag1",
        )
        cols = [y_col, signal, *controls]
        df = panel[cols].replace([np.inf, -np.inf], np.nan).dropna()
        for label, mask in {
            "pre_2020": df.index < pd.Timestamp("2020-01-01"),
            "post_2020": df.index >= pd.Timestamp("2020-01-01"),
        }.items():
            sub = df.loc[mask]
            if len(sub) < 36:
                out.append(
                    {
                        "etf": etf,
                        "horizon_months": horizon,
                        "signal": signal,
                        "subsample": label,
                        "insufficient": True,
                        "n_months": int(len(sub)),
                    }
                )
                continue
            y = sub[y_col]
            x = sm.add_constant(sub[[signal, *controls]], has_constant="add")
            fit = sm.OLS(y, x).fit(
                cov_type="HAC",
                cov_kwds={"maxlags": max(1, horizon), "use_correction": True},
            )
            out.append(
                {
                    "etf": etf,
                    "horizon_months": horizon,
                    "signal": signal,
                    "subsample": label,
                    "coef_log_rv": float(fit.params[signal]),
                    "t_stat": float(fit.tvalues[signal]),
                    "p_value_two_sided": float(fit.pvalues[signal]),
                    "n_months": int(len(sub)),
                    "insufficient": False,
                }
            )
    return out


def write_figures(panel: pd.DataFrame, results: list[dict[str, Any]]) -> list[str]:
    fig_paths: list[str] = []

    valid = [r for r in results if not r.get("insufficient") and r["coef_log_rv"] > 0]
    top = sorted(valid, key=lambda r: r["t_stat"], reverse=True)[:12]
    if top:
        labels = [
            f"{r['etf']} {r['horizon_months']}m\n{r['signal'].replace('_z', '')}"
            for r in top
        ]
        vals = [r["t_stat"] for r in top]
        plt.figure(figsize=(11, 6))
        plt.barh(range(len(vals)), vals, color="#4C78A8")
        plt.axvline(3.0, color="#D62728", linestyle="--", linewidth=1, label="Harvey |t|=3")
        plt.yticks(range(len(vals)), labels, fontsize=8)
        plt.gca().invert_yaxis()
        plt.xlabel("Newey-West t-stat (positive coefficients only)")
        plt.title("Strongest Positive Labor-Supply Proxy Coefficients")
        plt.legend()
        plt.tight_layout()
        out = ROOT / "fig_signal_tstats.png"
        plt.savefig(out, dpi=160)
        plt.close()
        fig_paths.append(str(out.relative_to(ROOT)))

    df = panel[["labor_supply_stress_z", "XHB_log_rv_fwd_1m"]].dropna()
    if not df.empty:
        fig, ax1 = plt.subplots(figsize=(11, 5))
        ax1.plot(df.index, df["labor_supply_stress_z"], color="#4C78A8", label="Labor-supply stress z (lagged)")
        ax1.axhline(0, color="#999999", linewidth=0.8)
        ax1.set_ylabel("Lagged labor-supply stress z")
        ax2 = ax1.twinx()
        ax2.plot(df.index, df["XHB_log_rv_fwd_1m"], color="#F58518", alpha=0.65, label="XHB next-month log RV")
        ax2.set_ylabel("XHB next-month log RV")
        ax1.set_title("Lagged Labor-Supply Stress Proxy vs XHB Realized Volatility")
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
        fig.tight_layout()
        out = ROOT / "fig_labor_supply_stress_xhb.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        fig_paths.append(str(out.relative_to(ROOT)))

    return fig_paths


def summarize_verdict(results: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in results if not r.get("insufficient")]
    positive_support = [r for r in valid if r.get("positive_harvey_holm_support")]
    raw_positive_t2 = [r for r in valid if r["coef_log_rv"] > 0 and r["t_stat"] > 2.0]
    strongest_positive = max(
        (r for r in valid if r["coef_log_rv"] > 0),
        key=lambda r: r["t_stat"],
        default=None,
    )
    strongest_abs = max(valid, key=lambda r: abs(r["t_stat"]), default=None)
    verdict = "NULL" if not positive_support else "CONDITIONAL_SUPPORT"
    return {
        "verdict": verdict,
        "primary_tests": int(len(valid)),
        "positive_harvey_holm_support_count": int(len(positive_support)),
        "raw_positive_t_gt_2_count": int(len(raw_positive_t2)),
        "strongest_positive": strongest_positive,
        "strongest_absolute_t": strongest_abs,
        "conclusion": (
            "No labor-supply / immigration public proxy survives the pre-specified "
            "positive Harvey |t|>=3 plus Holm-correction gate."
            if verdict == "NULL"
            else (
                "At least one positive labor-supply proxy survives the Harvey-Holm gate, "
                "but interpretation is conditional because the strongest evidence is wage-growth "
                "and composite stress rather than a direct immigration-flow measure."
            )
        ),
    }


def main() -> int:
    np.random.seed(SEED)
    macro = fetch_fred_monthly()
    close = fetch_adjusted_close()
    market_panel, market_meta = build_market_panel(close)
    signals, signal_meta = build_macro_signals(macro)
    panel = pd.concat([market_panel, signals], axis=1, join="inner").sort_index()

    specs = make_regression_specs()
    results = add_multiple_testing([fit_hac(panel, spec) for spec in specs])
    valid_results = [r for r in results if not r.get("insufficient")]
    strongest_positive = max(
        (r for r in valid_results if r["coef_log_rv"] > 0),
        key=lambda r: r["t_stat"],
        default=None,
    )
    bootstrap = None
    if strongest_positive is not None:
        strongest_spec = RegressionSpec(
            etf=strongest_positive["etf"],
            horizon_months=int(strongest_positive["horizon_months"]),
            signal=strongest_positive["signal"],
            y_col=f"{strongest_positive['etf']}_log_rv_fwd_{int(strongest_positive['horizon_months'])}m",
            controls=(
                f"{strongest_positive['etf']}_log_rv_lag1",
                f"{strongest_positive['etf']}_ret_lag1",
                f"{BENCHMARK}_log_rv_lag1",
                f"{BENCHMARK}_ret_lag1",
            ),
        )
        bootstrap = {
            "selected_by": "strongest positive HAC t-stat before multiplicity correction",
            "spec": strongest_positive,
            "bootstrap": moving_block_bootstrap_coef(panel, strongest_spec),
        }

    figures = write_figures(panel, results)
    event_diagnostics = top_decile_diagnostics(panel)
    verdict = summarize_verdict(results)
    supported = [
        r for r in valid_results if r.get("positive_harvey_holm_support")
    ]
    sensitivity = subsample_sensitivity(panel, supported)

    payload = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Labor-force growth / immigration public proxy as wage-sensitive sector RV prior",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data_sources": {
            "fred": {
                "series": FRED_SERIES,
                "url_template": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>",
            },
            "market": {
                "provider": "yfinance",
                "tickers": TICKERS,
                "price_field": "Close (auto_adjust=True)",
            },
        },
        "literature_context": [
            "FRBSF Economic Letter 2025: Immigration and Changes in Labor Force Demographics",
            "FRBSF Economic Letter 2023: The Role of Immigration in U.S. Labor Market Tightness",
            "FRBSF Economic Letter 2024: Recent Spike in Immigration and Easing Labor Markets",
            "Boston Fed 2024 working paper: Quantifying the Recent Immigration Surge",
            "BLS annual Foreign-born Workers release for CPS definitions and sector composition",
        ],
        "market_metadata": market_meta,
        "signal_metadata": signal_meta,
        "test_design": {
            "targets": TARGET_ETFS,
            "benchmark_controls": BENCHMARK,
            "horizons_months": HORIZONS_MONTHS,
            "primary_family_size": len([r for r in results if not r.get("insufficient")]),
            "hac": "Newey-West HAC with maxlags=max(1, horizon_months)",
            "multiplicity": "Holm and Bonferroni across all ETF x horizon x signal primary tests",
            "support_gate": "coef > 0, |t| >= 3.0, Holm p < 0.05",
        },
        "panel": {
            "start": str(panel.dropna(how="all").index.min().date()),
            "end": str(panel.dropna(how="all").index.max().date()),
            "rows": int(len(panel)),
            "complete_case_rows_for_any_regression_min": int(
                min((r["n_months"] for r in results if not r.get("insufficient")), default=0)
            ),
            "complete_case_rows_for_any_regression_max": int(
                max((r["n_months"] for r in results if not r.get("insufficient")), default=0)
            ),
        },
        "regression_results": results,
        "strongest_positive_bootstrap": bootstrap,
        "top_decile_diagnostics": event_diagnostics,
        "subsample_sensitivity_supported_cells": sensitivity,
        "figures": figures,
        "verdict": verdict,
        "research_honesty_notes": [
            "FRED LNU01073395 is a CPS foreign-born labor-force level proxy, not true immigration-flow data.",
            "Census/BLS data can undercount sudden undocumented migration flows; this weakens proxy validity.",
            "All signals are lagged one month before predicting ETF realized volatility.",
            "The experiment tests public-market ETF RV associations, not causal labor-market transmission.",
            "No portfolio rule or investable strategy is claimed.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    print(f"Wrote {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
