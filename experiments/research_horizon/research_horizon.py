"""
research_horizon: skew-premium "term-structure" proxy for long-horizon SPY tail outcomes.

Task brief:
- Use free data only (^VIX, ^SKEW, SPY).
- Build short- and long-horizon skew-premium proxies from option-implied tail fear
  and realized skewness anchors.
- Test whether the long-end proxy is more informative than the short-end proxy for
  6-12 month SPY returns and drawdowns.

Methodology notes:
- Signal at t uses only information available by the close of day t.
- Targets start at t+1 to avoid same-day contamination.
- Overlapping long-horizon targets use HAC / Newey-West inference.
- OOS evaluation uses annual expanding-window refits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


EXPERIMENT_ID = "research_horizon"
ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"
FIG_DIR = ROOT / "figures"
FIG_DIR.mkdir(exist_ok=True)
SEED = 42

START = "2010-01-01"
OOS_START = "2018-01-01"
END = pd.Timestamp.today(tz="Asia/Taipei").strftime("%Y-%m-%d")

SHORT_WINDOW = 22
LONG_WINDOW = 126
TARGET_HORIZONS = [126, 252]


@dataclass
class ForecastResult:
    model_name: str
    feature_name: str | None
    oos_r2: float
    mse: float
    coef_full: float | None
    tstat_full: float | None
    pvalue_full: float | None
    n_oos: int


def hac_t_pvalue(model: sm.regression.linear_model.RegressionResultsWrapper, name: str) -> tuple[float, float, float]:
    coef = float(model.params[name])
    tval = float(model.tvalues[name])
    pval = float(model.pvalues[name])
    return coef, tval, pval


def download_panel() -> pd.DataFrame:
    raw = yf.download(
        ["SPY", "^VIX", "^SKEW"],
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty panel")

    close = raw["Close"].copy()
    close.columns = [str(col) for col in close.columns]
    close = close.rename(columns={"SPY": "spy", "^VIX": "vix", "^SKEW": "skew"})
    df = close.dropna().sort_index()
    if len(df) < 2500:
        raise RuntimeError(f"Too few rows after join: {len(df)}")
    return df


def realized_skew(ret: pd.Series, window: int) -> pd.Series:
    def _sk(x: np.ndarray) -> float:
        if len(x) < window:
            return np.nan
        sigma = x.std(ddof=0)
        if sigma <= 1e-12:
            return np.nan
        centered = x - x.mean()
        return float(np.mean(centered**3) / sigma**3)

    return ret.rolling(window).apply(_sk, raw=True)


def future_log_return(log_ret: pd.Series, horizon: int) -> pd.Series:
    out = np.full(len(log_ret), np.nan)
    values = log_ret.to_numpy()
    for i in range(len(values) - horizon):
        out[i] = float(np.nansum(values[i + 1 : i + horizon + 1]))
    return pd.Series(out, index=log_ret.index)


def future_max_drawdown(close: pd.Series, horizon: int) -> pd.Series:
    out = np.full(len(close), np.nan)
    values = close.to_numpy()
    for i in range(len(values) - horizon):
        path = values[i + 1 : i + horizon + 1]
        if len(path) == 0:
            continue
        peak = np.maximum.accumulate(path)
        dd = path / peak - 1.0
        out[i] = float(dd.min())
    return pd.Series(out, index=close.index)


def dm_hac(loss_a: pd.Series, loss_b: pd.Series, max_lag: int) -> dict[str, float]:
    diff = (loss_a - loss_b).dropna()
    if len(diff) < max_lag + 10:
        return {"dm_stat": np.nan, "p_value": np.nan, "mean_diff": np.nan, "n": int(len(diff))}
    x = np.ones((len(diff), 1))
    res = sm.OLS(diff.to_numpy(), x).fit(cov_type="HAC", cov_kwds={"maxlags": max_lag})
    return {
        "dm_stat": float(res.tvalues[0]),
        "p_value": float(res.pvalues[0]),
        "mean_diff": float(diff.mean()),
        "n": int(len(diff)),
    }


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    arr = np.array(pvalues, dtype=float)
    out = np.full_like(arr, np.nan)
    valid = np.isfinite(arr)
    if not valid.any():
        return out.tolist()
    vals = arr[valid]
    order = np.argsort(vals)
    ranked = vals[order]
    m = len(ranked)
    adj = np.empty(m)
    running = 1.0
    for i in range(m - 1, -1, -1):
        rank = i + 1
        running = min(running, ranked[i] * m / rank)
        adj[i] = running
    restored = np.empty(m)
    restored[order] = adj
    out[valid] = restored
    return out.tolist()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["log_ret"] = np.log(out["spy"]).diff()
    out["rv_21"] = out["log_ret"].pow(2).rolling(SHORT_WINDOW).mean() * 252
    out["ret_21"] = out["log_ret"].rolling(SHORT_WINDOW).sum()

    out["rskew_22"] = realized_skew(out["log_ret"], SHORT_WINDOW)
    out["rskew_126"] = realized_skew(out["log_ret"], LONG_WINDOW)

    # SKEW > 100 implies more left-tail pricing. Multiply by VIX to proxy a priced tail-fear level.
    out["implied_tail_fear"] = ((out["skew"] - 100.0) / 100.0) * (out["vix"] / 100.0)
    out["realized_tail_22"] = -out["rskew_22"]
    out["realized_tail_126"] = -out["rskew_126"]

    out["short_skew_premium"] = out["implied_tail_fear"] - out["realized_tail_22"]
    out["long_skew_premium"] = out["implied_tail_fear"] - out["realized_tail_126"]
    out["term_structure_gap"] = out["long_skew_premium"] - out["short_skew_premium"]

    for horizon in TARGET_HORIZONS:
        out[f"fwd_ret_{horizon}"] = future_log_return(out["log_ret"], horizon)
        out[f"fwd_mdd_{horizon}"] = future_max_drawdown(out["spy"], horizon)

    for col in [
        "vix",
        "ret_21",
        "rv_21",
        "short_skew_premium",
        "long_skew_premium",
        "term_structure_gap",
    ]:
        out[f"{col}_lag1"] = out[col].shift(1)

    return out


def fit_full_sample_hac(df: pd.DataFrame, y_col: str, x_cols: list[str], max_lag: int, feature_name: str | None) -> tuple[float | None, float | None, float | None]:
    data = df[[y_col] + x_cols].dropna()
    x = sm.add_constant(data[x_cols])
    model = sm.OLS(data[y_col], x).fit(cov_type="HAC", cov_kwds={"maxlags": max_lag})
    if feature_name is None:
        return None, None, None
    return hac_t_pvalue(model, feature_name)


def expanding_oos_forecast(df: pd.DataFrame, y_col: str, x_cols: list[str], feature_name: str | None, max_lag: int, model_name: str) -> tuple[ForecastResult, pd.DataFrame]:
    use = df[[y_col] + x_cols].dropna().copy()
    use = use.loc[use.index >= pd.Timestamp("2011-01-01")]
    preds = []
    oos_mask = use.index >= pd.Timestamp(OOS_START)
    oos_years = sorted(use.loc[oos_mask].index.year.unique())

    for year in oos_years:
        train = use.loc[use.index < pd.Timestamp(f"{year}-01-01")]
        test = use.loc[(use.index >= pd.Timestamp(f"{year}-01-01")) & (use.index < pd.Timestamp(f"{year + 1}-01-01"))]
        if len(train) < 750 or test.empty:
            continue

        x_train = sm.add_constant(train[x_cols])
        x_test = sm.add_constant(test[x_cols], has_constant="add")
        model = sm.OLS(train[y_col], x_train).fit()
        pred = model.predict(x_test)
        frame = pd.DataFrame(
            {
                "actual": test[y_col],
                "pred": pred,
                "date": test.index,
            }
        ).set_index("date")
        preds.append(frame)

    if not preds:
        raise RuntimeError(f"No OOS predictions produced for {model_name} / {y_col}")

    pred_df = pd.concat(preds).sort_index()
    mse = float(np.mean((pred_df["actual"] - pred_df["pred"]) ** 2))
    baseline = float(np.mean((pred_df["actual"] - pred_df["actual"].mean()) ** 2))
    oos_r2 = 1.0 - mse / baseline if baseline > 0 else np.nan
    coef, tval, pval = fit_full_sample_hac(use, y_col, x_cols, max_lag, feature_name)

    result = ForecastResult(
        model_name=model_name,
        feature_name=feature_name,
        oos_r2=float(oos_r2),
        mse=mse,
        coef_full=coef,
        tstat_full=tval,
        pvalue_full=pval,
        n_oos=int(len(pred_df)),
    )
    return result, pred_df


def make_figures(df: pd.DataFrame, summary_rows: list[dict[str, object]]) -> list[str]:
    paths: list[str] = []

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    plot_df = df.loc[df.index >= "2014-01-01", ["short_skew_premium", "long_skew_premium"]].dropna()
    plot_df.iloc[-1200:].plot(ax=axes[0], linewidth=1.2)
    axes[0].set_title("Short vs Long Skew-Premium Proxy")
    axes[0].set_ylabel("Proxy level")
    axes[0].grid(alpha=0.25)

    plot_gap = df.loc[df.index >= "2014-01-01", "term_structure_gap"].dropna()
    plot_gap.iloc[-1200:].plot(ax=axes[1], color="#8c2d04", linewidth=1.2)
    axes[1].axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
    axes[1].set_title("Term-Structure Gap = Long Proxy - Short Proxy")
    axes[1].set_ylabel("Gap")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "proxy_timeseries.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    paths.append(path.name)

    bar_df = pd.DataFrame(summary_rows)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=False)
    for ax, target_type in zip(axes, ["return", "drawdown"]):
        sub = bar_df[bar_df["target_type"] == target_type].copy()
        labels = [f"{int(h)}d\n{m}" for h, m in zip(sub["horizon"], sub["model"])]
        ax.bar(labels, sub["oos_r2"], color=["#4C78A8", "#F58518", "#54A24B"] * 2)
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_title(f"OOS R² ({target_type})")
        ax.set_ylabel("OOS R²")
        ax.tick_params(axis="x", rotation=0)
        ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "oos_r2_bars.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    paths.append(path.name)
    return paths


def main() -> None:
    np.random.seed(SEED)
    df = build_features(download_panel())

    controls = ["vix_lag1", "ret_21_lag1", "rv_21_lag1"]
    specs = [
        ("M1_short", controls + ["short_skew_premium_lag1"], "short_skew_premium_lag1"),
        ("M2_long", controls + ["long_skew_premium_lag1"], "long_skew_premium_lag1"),
        ("M3_gap", controls + ["term_structure_gap_lag1"], "term_structure_gap_lag1"),
    ]

    all_results: dict[str, dict[str, ForecastResult]] = {}
    predictions: dict[str, dict[str, pd.DataFrame]] = {}
    primary_tests: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    for horizon in TARGET_HORIZONS:
        target_map = {
            f"return_{horizon}": (f"fwd_ret_{horizon}", horizon, "return"),
            f"drawdown_{horizon}": (f"fwd_mdd_{horizon}", horizon, "drawdown"),
        }
        for target_key, (y_col, lag, target_type) in target_map.items():
            all_results[target_key] = {}
            predictions[target_key] = {}
            for model_name, x_cols, feature_name in specs:
                result, pred = expanding_oos_forecast(df, y_col, x_cols, feature_name, lag, model_name)
                all_results[target_key][model_name] = result
                predictions[target_key][model_name] = pred
                summary_rows.append(
                    {
                        "target": target_key,
                        "target_type": target_type,
                        "horizon": horizon,
                        "model": model_name,
                        "oos_r2": result.oos_r2,
                    }
                )

            loss_short = (predictions[target_key]["M1_short"]["actual"] - predictions[target_key]["M1_short"]["pred"]) ** 2
            loss_long = (predictions[target_key]["M2_long"]["actual"] - predictions[target_key]["M2_long"]["pred"]) ** 2
            dm = dm_hac(loss_short, loss_long, max_lag=lag)
            primary_tests.append(
                {
                    "target": target_key,
                    "horizon": horizon,
                    "target_type": target_type,
                    "null": "long proxy is not better than short proxy",
                    "alternative": "long proxy has lower OOS squared error than short proxy",
                    "dm_stat": dm["dm_stat"],
                    "p_value": dm["p_value"],
                    "mean_loss_short_minus_long": dm["mean_diff"],
                    "long_better": bool(np.isfinite(dm["mean_diff"]) and dm["mean_diff"] > 0),
                    "short_oos_r2": all_results[target_key]["M1_short"].oos_r2,
                    "long_oos_r2": all_results[target_key]["M2_long"].oos_r2,
                }
            )

    bh = benjamini_hochberg([float(t["p_value"]) for t in primary_tests])
    for test, adj in zip(primary_tests, bh):
        test["bh_fdr_p"] = adj
        test["harvey_like_pass"] = bool(
            np.isfinite(test["dm_stat"]) and np.isfinite(adj) and test["dm_stat"] > 3.0 and adj < 0.05
        )

    figures = make_figures(df, summary_rows)

    key_findings = []
    for test in primary_tests:
        target = str(test["target"])
        key_findings.append(
            {
                "target": target,
                "long_better": test["long_better"],
                "dm_stat": test["dm_stat"],
                "p_value": test["p_value"],
                "bh_fdr_p": test["bh_fdr_p"],
                "short_oos_r2": test["short_oos_r2"],
                "long_oos_r2": test["long_oos_r2"],
            }
        )

    long_wins = sum(1 for t in primary_tests if t["long_better"])
    strong_long_wins = sum(1 for t in primary_tests if t["harvey_like_pass"])
    if strong_long_wins >= 2:
        verdict = "CONDITIONAL_PASS"
        summary = "Long-end skew-premium proxy beats short-end proxy on multiple long-horizon cells after BH-FDR."
    elif long_wins >= 2:
        verdict = "MIXED"
        summary = "Long-end proxy often beats short-end proxy economically, but formal significance is weak after BH-FDR."
    else:
        verdict = "NULL"
        summary = "Long-end skew-premium proxy does not robustly outperform the short-end proxy for 6-12 month SPY tail outcomes."

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Skew-premium term-structure proxy for long-horizon SPY tail outcomes",
        "seed": SEED,
        "data_source": "yfinance (SPY, ^VIX, ^SKEW)",
        "sample": {
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "n_obs": int(len(df)),
            "oos_start": OOS_START,
        },
        "methodology": {
            "signal_timing": "All predictors lagged by one trading day; targets begin at t+1.",
            "controls": controls,
            "short_window": SHORT_WINDOW,
            "long_window": LONG_WINDOW,
            "target_horizons": TARGET_HORIZONS,
            "proxy_definition": {
                "implied_tail_fear": "((SKEW - 100)/100) * (VIX/100)",
                "realized_tail_22": "- rolling 22d realized skewness",
                "realized_tail_126": "- rolling 126d realized skewness",
                "short_skew_premium": "implied_tail_fear - realized_tail_22",
                "long_skew_premium": "implied_tail_fear - realized_tail_126",
                "term_structure_gap": "long_skew_premium - short_skew_premium",
            },
        },
        "full_sample_descriptives": {
            "corr_vix_skew": float(df["vix"].corr(df["skew"])),
            "corr_short_long_proxy": float(df["short_skew_premium"].corr(df["long_skew_premium"])),
            "mean_short_proxy": float(df["short_skew_premium"].mean()),
            "mean_long_proxy": float(df["long_skew_premium"].mean()),
        },
        "per_target_results": {
            target: {
                model: {
                    "oos_r2": res.oos_r2,
                    "mse": res.mse,
                    "coef_full": res.coef_full,
                    "tstat_full": res.tstat_full,
                    "pvalue_full": res.pvalue_full,
                    "n_oos": res.n_oos,
                }
                for model, res in model_results.items()
            }
            for target, model_results in all_results.items()
        },
        "primary_tests_long_vs_short": primary_tests,
        "key_findings": key_findings,
        "verdict": verdict,
        "summary": summary,
        "figures": figures,
        "limitations": [
            "Only one free implied skew measure (^SKEW) is available, so the horizon dimension comes from realized-skew anchors rather than separate option maturities.",
            "Targets are overlapping 126d/252d windows; HAC helps inference but finite-sample power remains limited.",
            "Single asset (SPY) only; cross-asset replication is still required.",
            "Drawdown is path-dependent and forecasted here with simple linear models.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ok": True, "verdict": verdict, "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
