from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, strategy_dm_test


EXPERIMENT_ID = "research_rp_f1168bab52"
HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
FIG_REGIME = HERE / "fig_premium_by_regime.png"
FIG_OOS = HERE / "fig_oos_and_strategy.png"

START = "2006-01-01"
END = "2026-06-17"
SEED = 42
INITIAL_TRAIN_MONTHS = 96
EPS = 1e-10

np.random.seed(SEED)


@dataclass
class OOSResult:
    n: int
    oos_start: str
    oos_end: str
    r2_vs_baseline: float
    mse_baseline: float
    mse_augmented: float
    qlike_baseline: float
    qlike_augmented: float
    dm_t_qlike_aug_vs_base: float
    dm_p_qlike_aug_vs_base: float
    dm_t_mse_aug_vs_base: float
    dm_p_mse_aug_vs_base: float


def download_market_data() -> pd.DataFrame:
    raw = yf.download(
        ["SPY", "^VIX", "^VIX3M"],
        start=START,
        end=END,
        progress=False,
        auto_adjust=True,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty market panel")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw.copy()
    close = close.rename(columns={"^VIX": "vix", "^VIX3M": "vix3m", "SPY": "spy"})
    missing = {"spy", "vix", "vix3m"} - set(close.columns)
    if missing:
        raise RuntimeError(f"missing columns from yfinance: {sorted(missing)}")
    return close[["spy", "vix", "vix3m"]].dropna(how="all").ffill().dropna()


def read_fred(series: str) -> pd.Series:
    path = ROOT / "storage" / "macro" / f"fred_{series}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, parse_dates=["date"])
    value = pd.to_numeric(df[series], errors="coerce")
    out = pd.Series(value.to_numpy(dtype=float), index=df["date"], name=series.lower())
    return out.sort_index()


def add_forward_window(values: pd.Series, horizon: int, agg: str) -> tuple[pd.Series, pd.Series]:
    arr = values.to_numpy(dtype=float)
    idx = values.index
    out = np.full(len(arr), np.nan, dtype=float)
    end_dates = np.full(len(arr), None, dtype=object)
    for i in range(len(arr) - horizon):
        window = arr[i + 1 : i + 1 + horizon]
        if not np.all(np.isfinite(window)):
            continue
        if agg == "mean":
            out[i] = float(np.mean(window))
        elif agg == "sum":
            out[i] = float(np.sum(window))
        else:
            raise ValueError(agg)
        end_dates[i] = idx[i + horizon]
    return pd.Series(out, index=idx), pd.Series(end_dates, index=idx)


def build_daily_panel(close: pd.DataFrame) -> pd.DataFrame:
    df = close.copy()
    df["ret"] = np.log(df["spy"]).diff()
    df["simple_ret"] = df["spy"].pct_change()
    df["r2"] = df["ret"] ** 2

    # Explicit lag guards: all signals used at month-end t are from t-1 or earlier.
    df["vix_lag1"] = df["vix"].shift(1)
    df["vix3m_lag1"] = df["vix3m"].shift(1)
    df["iv1_var"] = (df["vix_lag1"] / 100.0) ** 2
    df["iv3_var"] = (df["vix3m_lag1"] / 100.0) ** 2
    df["term_ratio_lag1"] = df["vix_lag1"] / df["vix3m_lag1"]
    df["term_slope_lag1"] = df["term_ratio_lag1"] - 1.0
    df["past20_ret_lag1"] = df["ret"].rolling(20).sum().shift(1)
    df["neg20_lag1"] = (df["past20_ret_lag1"] < 0).astype(float)
    df["abs_past20_lag1"] = df["past20_ret_lag1"].abs()

    rv21, end21 = add_forward_window(df["r2"], 21, "mean")
    rv63, end63 = add_forward_window(df["r2"], 63, "mean")
    fwd_ret21, ret_end21 = add_forward_window(df["ret"], 21, "sum")
    df["fwd_rv21"] = rv21 * 252.0
    df["fwd_rv63"] = rv63 * 252.0
    df["fwd_ret21"] = np.exp(fwd_ret21) - 1.0
    df["label_end_21"] = pd.to_datetime(end21)
    df["label_end_63"] = pd.to_datetime(end63)
    df["ret_end_21"] = pd.to_datetime(ret_end21)

    for series in ["DGS10", "DGS2", "T10YIE"]:
        s = read_fred(series).reindex(df.index).ffill()
        col = series.lower()
        df[col] = s
        df[f"{col}_chg21_lag1"] = s.diff(21).shift(1)
        df[f"{col}_lag1"] = s.shift(1)
    df["term_spread_lag1"] = df["dgs10_lag1"] - df["dgs2_lag1"]
    return df


def month_end_panel(daily: pd.DataFrame) -> pd.DataFrame:
    monthly = daily.groupby(daily.index.to_period("M")).tail(1).copy()
    monthly["premium_1m"] = monthly["iv1_var"] - monthly["fwd_rv21"]
    monthly["premium_3m"] = monthly["iv3_var"] - monthly["fwd_rv63"]
    monthly["premium_slope_1m_minus_3m"] = monthly["premium_1m"] - monthly["premium_3m"]
    return monthly


def hac_mean_test(x: pd.Series, maxlags: int = 3) -> dict:
    y = x.dropna().astype(float)
    if len(y) < 10:
        return {"n": int(len(y)), "mean": math.nan, "t": math.nan, "p": math.nan}
    X = np.ones((len(y), 1))
    model = sm.OLS(y.to_numpy(), X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "n": int(len(y)),
        "mean": float(model.params[0]),
        "t": float(model.tvalues[0]),
        "p": float(model.pvalues[0]),
    }


def regime_tests(monthly: pd.DataFrame) -> dict:
    use = monthly.dropna(subset=["premium_1m", "premium_3m", "premium_slope_1m_minus_3m", "neg20_lag1"])
    neg = use["neg20_lag1"] == 1.0
    pos = use["neg20_lag1"] == 0.0

    out: dict[str, dict] = {}
    for col in ["premium_1m", "premium_3m", "premium_slope_1m_minus_3m"]:
        a = use.loc[neg, col]
        b = use.loc[pos, col]
        t, p = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
        diff = a.mean() - b.mean()
        reg = use[[col, "neg20_lag1"]].dropna()
        hac_model = sm.OLS(reg[col], sm.add_constant(reg[["neg20_lag1"]])).fit(
            cov_type="HAC",
            cov_kwds={"maxlags": 3},
        )
        out[col] = {
            "n_negative": int(a.notna().sum()),
            "n_positive": int(b.notna().sum()),
            "negative_mean": float(a.mean()),
            "positive_mean": float(b.mean()),
            "negative_minus_positive": float(diff),
            "welch_t": float(t),
            "welch_p": float(p),
            "hac_coef_neg_minus_pos": float(hac_model.params["neg20_lag1"]),
            "hac_t_neg_minus_pos": float(hac_model.tvalues["neg20_lag1"]),
            "hac_p_neg_minus_pos": float(hac_model.pvalues["neg20_lag1"]),
            "negative_mean_volpts2": float(a.mean() * 10000.0),
            "positive_mean_volpts2": float(b.mean() * 10000.0),
            "negative_minus_positive_volpts2": float(diff * 10000.0),
        }
    return out


def regression_tests(monthly: pd.DataFrame) -> dict:
    controls = [
        "past20_ret_lag1",
        "term_slope_lag1",
        "dgs10_chg21_lag1",
        "t10yie_chg21_lag1",
        "term_spread_lag1",
    ]
    slope_cols = ["premium_slope_1m_minus_3m", "neg20_lag1"] + controls
    slope_df = monthly[slope_cols].dropna()
    X = sm.add_constant(slope_df[["neg20_lag1"] + controls])
    y = slope_df["premium_slope_1m_minus_3m"]
    slope_model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 3})

    rows = []
    panel_base = monthly.dropna(
        subset=["premium_1m", "premium_3m", "neg20_lag1", "iv1_var", "iv3_var"] + controls
    )
    for dt, row in panel_base.iterrows():
        for term, premium_col, iv_col, horizon in [
            ("1m", "premium_1m", "iv1_var", 21),
            ("3m", "premium_3m", "iv3_var", 63),
        ]:
            r = {
                "date": dt,
                "premium": row[premium_col],
                "short_maturity": 1.0 if term == "1m" else 0.0,
                "neg20_lag1": row["neg20_lag1"],
                "short_x_neg": (1.0 if term == "1m" else 0.0) * row["neg20_lag1"],
                "iv_var": row[iv_col],
                "horizon": horizon,
            }
            for c in controls:
                r[c] = row[c]
            rows.append(r)
    panel = pd.DataFrame(rows).sort_values(["date", "short_maturity"])
    Xp = sm.add_constant(panel[["short_maturity", "neg20_lag1", "short_x_neg", "iv_var"] + controls])
    yp = panel["premium"]
    panel_model = sm.OLS(yp, Xp).fit(cov_type="HAC", cov_kwds={"maxlags": 6})

    def pack_model(model: sm.regression.linear_model.RegressionResultsWrapper, key: str) -> dict:
        return {
            "coef": float(model.params[key]),
            "t": float(model.tvalues[key]),
            "p": float(model.pvalues[key]),
        }

    return {
        "fmb_style_slope_regression": {
            "description": "Monthly two-maturity slope premium regression; slope = premium_1m - premium_3m.",
            "n_months": int(len(slope_df)),
            "r_squared": float(slope_model.rsquared),
            "neg20_lag1": pack_model(slope_model, "neg20_lag1"),
            "params": {
                k: {"coef": float(v), "t": float(slope_model.tvalues[k]), "p": float(slope_model.pvalues[k])}
                for k, v in slope_model.params.items()
            },
        },
        "pooled_term_panel_regression": {
            "description": "Two-row-per-month term panel. HAC is by row order, so this is secondary evidence.",
            "n_rows": int(len(panel)),
            "n_months": int(panel["date"].nunique()),
            "r_squared": float(panel_model.rsquared),
            "short_x_neg": pack_model(panel_model, "short_x_neg"),
            "params": {
                k: {"coef": float(v), "t": float(panel_model.tvalues[k]), "p": float(panel_model.pvalues[k])}
                for k, v in panel_model.params.items()
            },
        },
    }


def fit_predict(train: pd.DataFrame, test_row: pd.Series, features: list[str], target: str) -> float:
    X = sm.add_constant(train[features], has_constant="add")
    y = train[target]
    model = sm.OLS(y, X).fit()
    xt = pd.DataFrame([test_row[features]], columns=features)
    xt = sm.add_constant(xt, has_constant="add")
    pred = float(model.predict(xt).iloc[0])
    floor = max(EPS, float(np.nanpercentile(y, 1)) * 0.1)
    return max(pred, floor)


def expanding_oos(monthly: pd.DataFrame, target: str, iv_col: str, label_end_col: str, horizon: int) -> OOSResult:
    controls = [
        "neg20_lag1",
        "iv_x_neg",
        "past20_ret_lag1",
        "term_slope_lag1",
        "dgs10_chg21_lag1",
        "t10yie_chg21_lag1",
        "term_spread_lag1",
    ]
    df = monthly.copy()
    df["iv_x_neg"] = df[iv_col] * df["neg20_lag1"]
    features_base = [iv_col]
    features_aug = [iv_col] + controls
    required = [target, iv_col, label_end_col] + controls
    use = df.dropna(subset=required).copy()
    use = use.sort_index()

    preds_base = []
    preds_aug = []
    actual = []
    dates = []
    for dt, row in use.iterrows():
        train = use[(use[label_end_col] < dt)].copy()
        if len(train) < INITIAL_TRAIN_MONTHS:
            continue
        pred_b = fit_predict(train, row, features_base, target)
        pred_a = fit_predict(train, row, features_aug, target)
        preds_base.append(pred_b)
        preds_aug.append(pred_a)
        actual.append(float(row[target]))
        dates.append(dt)

    a = np.asarray(actual, dtype=float)
    b = np.asarray(preds_base, dtype=float)
    aug = np.asarray(preds_aug, dtype=float)
    if len(a) < 24:
        raise RuntimeError(f"not enough OOS observations for {target}")

    mse_b = float(np.mean((a - b) ** 2))
    mse_a = float(np.mean((a - aug) ** 2))
    loss_b_qlike = qlike_pointwise(a, b)
    loss_a_qlike = qlike_pointwise(a, aug)
    dm_t_q, dm_p_q = dm_test(loss_a_qlike, loss_b_qlike, h=max(1, horizon // 21))
    dm_t_m, dm_p_m = dm_test((a - aug) ** 2, (a - b) ** 2, h=max(1, horizon // 21))

    return OOSResult(
        n=int(len(a)),
        oos_start=str(pd.Timestamp(dates[0]).date()),
        oos_end=str(pd.Timestamp(dates[-1]).date()),
        r2_vs_baseline=float(1.0 - mse_a / mse_b),
        mse_baseline=mse_b,
        mse_augmented=mse_a,
        qlike_baseline=qlike(a, b),
        qlike_augmented=qlike(a, aug),
        dm_t_qlike_aug_vs_base=float(dm_t_q),
        dm_p_qlike_aug_vs_base=float(dm_p_q),
        dm_t_mse_aug_vs_base=float(dm_t_m),
        dm_p_mse_aug_vs_base=float(dm_p_m),
    )


def max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    peak = wealth.cummax()
    dd = wealth / peak - 1.0
    return float(dd.min())


def annualized_stats(returns: pd.Series) -> dict:
    r = returns.dropna().astype(float)
    if len(r) == 0:
        return {}
    sharpe = float(r.mean() / r.std(ddof=1) * math.sqrt(12.0)) if r.std(ddof=1) > 0 else math.nan
    wealth = float((1.0 + r).prod())
    years = len(r) / 12.0
    cagr = float(wealth ** (1.0 / years) - 1.0) if years > 0 and wealth > 0 else math.nan
    return {
        "n_months": int(len(r)),
        "mean_monthly": float(r.mean()),
        "ann_return_arithmetic": float(r.mean() * 12.0),
        "ann_vol": float(r.std(ddof=1) * math.sqrt(12.0)),
        "sharpe": sharpe,
        "cagr": cagr,
        "max_drawdown": max_drawdown(r),
        "final_wealth": wealth,
    }


def trading_rule(monthly: pd.DataFrame) -> dict:
    use = monthly.dropna(subset=["fwd_ret21", "vix_lag1", "vix3m_lag1", "neg20_lag1"]).copy()
    use = use.sort_index()
    target_vol = 0.12
    cap = 1.5
    tc = 0.001
    use["w_vix1"] = (target_vol / (use["vix_lag1"] / 100.0)).clip(0.0, cap)
    use["w_vix3m"] = (target_vol / (use["vix3m_lag1"] / 100.0)).clip(0.0, cap)
    use["w_asym"] = np.where(use["neg20_lag1"] == 1.0, use["w_vix3m"], use["w_vix1"])
    use["w_bh"] = 1.0

    results = {}
    returns = {}
    for key, wcol in [("buy_hold", "w_bh"), ("vix1m_vt", "w_vix1"), ("vix3m_vt", "w_vix3m"), ("asym_vix3m_when_neg20", "w_asym")]:
        turnover = use[wcol].diff().abs().fillna(0.0)
        strat_ret = use[wcol] * use["fwd_ret21"] - tc * turnover
        returns[key] = strat_ret
        results[key] = annualized_stats(strat_ret)
        results[key]["avg_weight"] = float(use[wcol].mean())
        results[key]["avg_turnover"] = float(turnover.mean())

    loss_asym, loss_base = -returns["asym_vix3m_when_neg20"].to_numpy(), -returns["vix1m_vt"].to_numpy()
    dm_t, dm_p = dm_test(loss_asym, loss_base, h=1)
    sdm_t, sdm_p = strategy_dm_test(
        returns["asym_vix3m_when_neg20"].to_numpy(),
        returns["vix1m_vt"].to_numpy(),
        h=1,
        loss_fn="negative_return",
    )
    results["comparison_asym_vs_vix1m"] = {
        "return_dm_t_negative_means_asym_better_if_negative": float(dm_t),
        "return_dm_p": float(dm_p),
        "strategy_dm_t_asym_better_if_negative": float(sdm_t),
        "strategy_dm_p": float(sdm_p),
        "sharpe_delta": float(results["asym_vix3m_when_neg20"]["sharpe"] - results["vix1m_vt"]["sharpe"]),
        "mdd_delta": float(results["asym_vix3m_when_neg20"]["max_drawdown"] - results["vix1m_vt"]["max_drawdown"]),
    }
    cum = pd.DataFrame({k: (1.0 + v).cumprod() for k, v in returns.items()})
    return {"results": results, "cumulative_wealth": cum}


def make_figures(monthly: pd.DataFrame, regime: dict, oos: dict, trading: dict) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    labels = ["1M premium", "3M premium", "1M-3M slope"]
    keys = ["premium_1m", "premium_3m", "premium_slope_1m_minus_3m"]
    x = np.arange(len(keys))
    neg_vals = [regime[k]["negative_mean_volpts2"] for k in keys]
    pos_vals = [regime[k]["positive_mean_volpts2"] for k in keys]
    width = 0.35
    ax.bar(x - width / 2, pos_vals, width, label="past20 >= 0", color="#2f6f9f")
    ax.bar(x + width / 2, neg_vals, width, label="past20 < 0", color="#b5533c")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("IV - future RV, vol-points squared")
    ax.set_title("VIX/VIX3M Premium by Lagged 20-Day Return Regime")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_REGIME, dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    oos_keys = ["1m_21d", "3m_63d"]
    axes[0].bar(oos_keys, [oos[k]["r2_vs_baseline"] * 100.0 for k in oos_keys], color=["#2f6f9f", "#b5533c"])
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_ylabel("Augmented model OOS R2 vs VIX-only (%)")
    axes[0].set_title("OOS Forecast Increment")
    axes[0].grid(axis="y", alpha=0.25)

    cum = trading["cumulative_wealth"]
    for col, color in [
        ("buy_hold", "#777777"),
        ("vix1m_vt", "#2f6f9f"),
        ("vix3m_vt", "#6c8f3a"),
        ("asym_vix3m_when_neg20", "#b5533c"),
    ]:
        axes[1].plot(cum.index, cum[col], label=col, color=color, linewidth=1.5)
    axes[1].set_title("Monthly Tradable Overlay")
    axes[1].set_ylabel("Cumulative wealth")
    axes[1].legend(frameon=False, fontsize=8)
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_OOS, dpi=150)
    plt.close(fig)


def main() -> None:
    close = download_market_data()
    daily = build_daily_panel(close)
    monthly = month_end_panel(daily)

    regime = regime_tests(monthly)
    regressions = regression_tests(monthly)
    oos = {
        "1m_21d": expanding_oos(monthly, "fwd_rv21", "iv1_var", "label_end_21", 21).__dict__,
        "3m_63d": expanding_oos(monthly, "fwd_rv63", "iv3_var", "label_end_63", 63).__dict__,
    }
    trading = trading_rule(monthly)
    make_figures(monthly, regime, oos, trading)

    slope_t = regressions["fmb_style_slope_regression"]["neg20_lag1"]["t"]
    panel_t = regressions["pooled_term_panel_regression"]["short_x_neg"]["t"]
    oos_pass = any(v["dm_t_qlike_aug_vs_base"] < -3.0 for v in oos.values())
    strategy_delta = trading["results"]["comparison_asym_vs_vix1m"]["sharpe_delta"]

    any_positive_oos_r2 = any(v["r2_vs_baseline"] > 0 for v in oos.values())
    qlike_worse = all(v["dm_t_qlike_aug_vs_base"] > 0 for v in oos.values())

    if abs(slope_t) > 3.0 and abs(panel_t) > 3.0 and oos_pass and strategy_delta > 0:
        verdict = "PASS"
    elif any_positive_oos_r2 and qlike_worse and strategy_delta <= 0:
        verdict = "MIXED_DIAGNOSTIC_NOT_TRADABLE"
    elif abs(slope_t) > 2.0 or abs(panel_t) > 2.0 or any_positive_oos_r2:
        verdict = "MIXED_WEAK_SIGNAL"
    else:
        verdict = "NULL"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Return-extrapolation-driven IV-RV asymmetric term structure",
        "verdict": verdict,
        "seed": SEED,
        "data": {
            "market_source": "yfinance adjusted close: SPY, ^VIX, ^VIX3M",
            "fred_controls_source": "local storage/macro/fred_DGS10.csv, fred_DGS2.csv, fred_T10YIE.csv",
            "sample_start": str(close.index[0].date()),
            "sample_end": str(close.index[-1].date()),
            "n_daily": int(len(close)),
            "n_monthly_origins": int(len(monthly)),
            "monthly_first": str(monthly.index[0].date()),
            "monthly_last": str(monthly.index[-1].date()),
        },
        "design": {
            "signal_timing": "All VIX/VIX3M, macro, and past-return predictors use lag-1 values at month-end. Future RV starts at t+1.",
            "iv_1m": "(VIX_{t-1}/100)^2",
            "iv_3m": "(VIX3M_{t-1}/100)^2",
            "rv_1m": "mean squared SPY log return over t+1..t+21, annualized",
            "rv_3m": "mean squared SPY log return over t+1..t+63, annualized",
            "negative_return_regime": "sum SPY log returns over t-20..t-1 < 0",
            "oos_cutoff": "Expanding forecasts train only on rows whose forward-label end date is strictly before the forecast origin.",
        },
        "regime_tests": regime,
        "regression_tests": regressions,
        "oos_forecasts": oos,
        "trading_rule": {
            "description": "Monthly VT overlay. Baseline uses 12%/VIX1M. Asymmetric rule uses 12%/VIX3M when lagged past20 return is negative, otherwise 12%/VIX1M. 1.5x cap, 10bp per 1x turnover.",
            "results": trading["results"],
        },
        "figures": [str(FIG_REGIME.name), str(FIG_OOS.name)],
        "references": [
            "Chordia, Lin, and Xiang (2025), Return Extrapolation and Volatility Expectations.",
            "Bekaert and Hoerova (2014), The VIX, the variance premium and stock market volatility.",
            "Bollerslev, Tauchen, and Zhou (2009), Expected stock returns and variance risk premia.",
            "Carr and Wu (2009), Variance risk premiums.",
        ],
        "conclusion": {
            "primary": "The broad asymmetric-extrapolation story is not validated as a tradable rule under free monthly SPY/VIX/VIX3M data unless both OOS and strategy gates pass.",
            "caveat": "VIX/VIX3M are index-implied variance proxies, not option-chain model-free variance swap rates; results are reduced-form.",
        },
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(json.dumps({"ok": True, "results": str(RESULTS_PATH), "verdict": verdict}, indent=2))


if __name__ == "__main__":
    main()
