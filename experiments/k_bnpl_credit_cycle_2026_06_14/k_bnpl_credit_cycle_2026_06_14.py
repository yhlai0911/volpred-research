from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import URLError

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "k_bnpl_credit_cycle_2026_06_14"
OUTPUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUTPUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_EVENT_PATH = OUTPUT_DIR / "fig_bnpl_stress_event.png"
FIG_OOS_PATH = OUTPUT_DIR / "fig_oos_qlike_delta.png"
FIG_MACRO_PATH = OUTPUT_DIR / "fig_macro_credit_context.png"

START_DATE = "2021-01-01"
END_DATE = "2026-06-13"
SEED = 42
N_BOOT = 1000
MIN_TRAIN_OBS = 756
OOS_FRACTION = 0.35
TICKERS = ["AFRM", "UPST", "SOFI", "ALLY", "IWM", "HYG", "XLF", "SPY", "^VIX"]
BNPL_MEMBERS = ["AFRM", "UPST", "SOFI", "ALLY"]
TARGETS = ["IWM", "HYG", "XLF"]
FRED_SERIES = {
    "DRCLACBS": "consumer_loan_delinquency",
    "DRCCLACBS": "credit_card_delinquency",
    "UMCSENT": "consumer_sentiment",
}


@dataclass
class EventResult:
    target: str
    horizon: str
    n_event: int
    n_non_event: int
    event_mean: float
    non_event_mean: float
    ratio: float
    diff: float
    bootstrap_p_value: float
    ci95_low: float
    ci95_high: float


def fetch_close_panel() -> pd.DataFrame:
    raw = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty panel")
    close = pd.DataFrame({ticker: raw[ticker]["Close"] for ticker in TICKERS})
    close.index = pd.to_datetime(close.index)
    close = close.sort_index().dropna()
    return close


def fetch_fred_series(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        df = pd.read_csv(url)
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"FRED fetch failed for {series_id}: {exc}") from exc
    date_col = "observation_date"
    if date_col not in df.columns or series_id not in df.columns:
        raise RuntimeError(f"Unexpected FRED schema for {series_id}: {df.columns.tolist()}")
    ser = pd.Series(pd.to_numeric(df[series_id], errors="coerce").to_numpy(), index=pd.to_datetime(df[date_col]))
    return ser.dropna().sort_index()


def fetch_fred_panel(index: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict]:
    panel = pd.DataFrame(index=index)
    meta = {}
    for series_id, name in FRED_SERIES.items():
        ser = fetch_fred_series(series_id)
        raw_aligned = ser.reindex(index, method="ffill")
        lag_days = 63 if series_id.startswith("DR") else 21
        panel[name] = raw_aligned.shift(lag_days)
        meta[series_id] = {
            "name": name,
            "first_obs": ser.index.min().strftime("%Y-%m-%d"),
            "last_obs": ser.index.max().strftime("%Y-%m-%d"),
            "n_obs": int(ser.notna().sum()),
            "conservative_trading_day_lag": lag_days,
        }
    return panel, meta


def log_rv(ret: pd.Series) -> pd.Series:
    return np.log((ret**2).clip(lower=1e-12))


def rolling_log_mean_rv(ret: pd.Series, window: int) -> pd.Series:
    return np.log((ret**2).rolling(window).mean().clip(lower=1e-12))


def build_dataset(close: pd.DataFrame, fred_panel: pd.DataFrame) -> pd.DataFrame:
    ret = np.log(close).diff().dropna()
    df = pd.DataFrame(index=ret.index)
    for ticker in TICKERS:
        name = ticker.replace("^", "")
        df[f"{name}_ret"] = ret[ticker]
        df[f"{name}_rv"] = ret[ticker] ** 2
        df[f"{name}_log_rv"] = log_rv(ret[ticker])
        df[f"{name}_log_rv_lag1"] = df[f"{name}_log_rv"].shift(1)
        df[f"{name}_log_rv_lag5"] = rolling_log_mean_rv(ret[ticker], 5).shift(1)
        df[f"{name}_log_rv_lag22"] = rolling_log_mean_rv(ret[ticker], 22).shift(1)

    df["bnpl_ret"] = ret[BNPL_MEMBERS].mean(axis=1)
    df["bnpl_downside_ret"] = ret[BNPL_MEMBERS].clip(upper=0).mean(axis=1).abs()
    df["bnpl_rv"] = df["bnpl_ret"] ** 2
    df["bnpl_log_rv"] = log_rv(df["bnpl_ret"])
    df["bnpl_log_rv_lag1"] = df["bnpl_log_rv"].shift(1)
    df["bnpl_log_rv_lag5"] = np.log(df["bnpl_rv"].rolling(5).mean().clip(lower=1e-12)).shift(1)
    df["bnpl_log_rv_lag22"] = np.log(df["bnpl_rv"].rolling(22).mean().clip(lower=1e-12)).shift(1)
    df["bnpl_downside_lag1"] = df["bnpl_downside_ret"].shift(1)

    threshold = df["bnpl_log_rv"].rolling(252, min_periods=126).quantile(0.90).shift(1)
    raw_signal = df["bnpl_log_rv"] > threshold
    # Tradeable alignment: stress known after day t-1 is used for target day t.
    df["bnpl_stress_signal_lag1"] = raw_signal.shift(1).fillna(False).astype(int)

    for col in fred_panel.columns:
        df[col] = fred_panel[col].reindex(df.index)
        df[f"{col}_chg63"] = df[col].diff(63)

    return df


def block_bootstrap_event_diff(values: np.ndarray, flags: np.ndarray, block: int = 5) -> dict:
    valid = np.isfinite(values) & np.isfinite(flags)
    values = values[valid]
    flags = flags[valid].astype(bool)
    if flags.sum() < 10 or (~flags).sum() < 10:
        return {"p_value": np.nan, "ci95_low": np.nan, "ci95_high": np.nan}

    obs = values[flags].mean() - values[~flags].mean()
    n = len(values)
    rng = np.random.default_rng(SEED)
    stats_boot = []
    starts = np.arange(max(1, n - block + 1))
    for _ in range(N_BOOT):
        pieces = []
        while sum(len(p) for p in pieces) < n:
            start = int(rng.choice(starts))
            pieces.append(np.arange(start, min(start + block, n)))
        idx = np.concatenate(pieces)[:n]
        b_values = values[idx]
        b_flags = flags[idx]
        if b_flags.sum() < 5 or (~b_flags).sum() < 5:
            continue
        stats_boot.append(b_values[b_flags].mean() - b_values[~b_flags].mean())
    stats_boot = np.asarray(stats_boot)
    centered = stats_boot - stats_boot.mean()
    p_value = float(np.mean(np.abs(centered) >= abs(obs)))
    return {
        "p_value": p_value,
        "ci95_low": float(np.percentile(stats_boot, 2.5)),
        "ci95_high": float(np.percentile(stats_boot, 97.5)),
    }


def event_study(df: pd.DataFrame) -> list[EventResult]:
    out: list[EventResult] = []
    flag = df["bnpl_stress_signal_lag1"].astype(bool)
    for target in TARGETS:
        series_map = {
            "next_day": df[f"{target}_rv"],
            "next_5d_mean": df[f"{target}_rv"].rolling(5).mean().shift(-4),
        }
        for horizon, values in series_map.items():
            reg = pd.DataFrame({"values": values, "flag": flag}).dropna()
            boot = block_bootstrap_event_diff(reg["values"].to_numpy(), reg["flag"].to_numpy())
            event_vals = reg.loc[reg["flag"], "values"]
            non_event_vals = reg.loc[~reg["flag"], "values"]
            out.append(
                EventResult(
                    target=target,
                    horizon=horizon,
                    n_event=int(len(event_vals)),
                    n_non_event=int(len(non_event_vals)),
                    event_mean=float(event_vals.mean()),
                    non_event_mean=float(non_event_vals.mean()),
                    ratio=float(event_vals.mean() / non_event_vals.mean()),
                    diff=float(event_vals.mean() - non_event_vals.mean()),
                    bootstrap_p_value=float(boot["p_value"]),
                    ci95_low=float(boot["ci95_low"]),
                    ci95_high=float(boot["ci95_high"]),
                )
            )
    return out


def fit_hac_regressions(df: pd.DataFrame) -> dict:
    out = {}
    common_cols = [
        "bnpl_log_rv_lag1",
        "bnpl_downside_lag1",
        "VIX_log_rv_lag1",
        "SPY_log_rv_lag1",
        "consumer_loan_delinquency_chg63",
        "credit_card_delinquency_chg63",
        "consumer_sentiment_chg63",
    ]
    for target in TARGETS:
        cols = [
            f"{target}_log_rv",
            f"{target}_log_rv_lag1",
            f"{target}_log_rv_lag5",
            f"{target}_log_rv_lag22",
            *common_cols,
        ]
        reg = df[cols].replace([np.inf, -np.inf], np.nan).dropna()
        y = reg[f"{target}_log_rv"]
        x_base = sm.add_constant(reg[[f"{target}_log_rv_lag1", f"{target}_log_rv_lag5", f"{target}_log_rv_lag22"]])
        x_aug = sm.add_constant(reg[[f"{target}_log_rv_lag1", f"{target}_log_rv_lag5", f"{target}_log_rv_lag22", *common_cols]])
        base = sm.OLS(y, x_base).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        aug = sm.OLS(y, x_aug).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        out[target] = {
            "n_obs": int(len(reg)),
            "baseline_r2": float(base.rsquared),
            "augmented_r2": float(aug.rsquared),
            "delta_r2": float(aug.rsquared - base.rsquared),
            "augmented_params": {
                col: {
                    "coef": float(aug.params[col]),
                    "std_err": float(aug.bse[col]),
                    "z_stat": float(aug.tvalues[col]),
                    "p_value": float(aug.pvalues[col]),
                }
                for col in aug.params.index
            },
        }
    return out


def _fit_predict_log(train: pd.DataFrame, test: pd.Series, y_col: str, features: list[str]) -> float:
    x_train = np.column_stack([np.ones(len(train))] + [train[col].to_numpy() for col in features])
    y_train = train[y_col].to_numpy()
    beta = np.linalg.lstsq(x_train, y_train, rcond=None)[0]
    x_test = np.array([1.0] + [float(test[col]) for col in features])
    pred_log = float(x_test @ beta)
    train_actual = np.exp(y_train)
    lo, hi = np.nanquantile(train_actual, [0.01, 0.99])
    return float(np.clip(np.exp(pred_log), lo, hi))


def rolling_oos(df: pd.DataFrame) -> dict:
    out = {}
    for target in TARGETS:
        y_col = f"{target}_log_rv"
        model_features = {
            "har": [f"{target}_log_rv_lag1", f"{target}_log_rv_lag5", f"{target}_log_rv_lag22"],
            "har_market": [
                f"{target}_log_rv_lag1",
                f"{target}_log_rv_lag5",
                f"{target}_log_rv_lag22",
                "VIX_log_rv_lag1",
                "SPY_log_rv_lag1",
            ],
            "har_bnpl": [
                f"{target}_log_rv_lag1",
                f"{target}_log_rv_lag5",
                f"{target}_log_rv_lag22",
                "bnpl_log_rv_lag1",
                "bnpl_downside_lag1",
            ],
            "har_market_bnpl": [
                f"{target}_log_rv_lag1",
                f"{target}_log_rv_lag5",
                f"{target}_log_rv_lag22",
                "VIX_log_rv_lag1",
                "SPY_log_rv_lag1",
                "bnpl_log_rv_lag1",
                "bnpl_downside_lag1",
            ],
        }
        all_cols = [y_col] + sorted({col for features in model_features.values() for col in features})
        reg = df[all_cols].replace([np.inf, -np.inf], np.nan).dropna()
        split = max(MIN_TRAIN_OBS, int(len(reg) * (1 - OOS_FRACTION)))
        actual = []
        forecasts = {name: [] for name in model_features}
        dates = []
        for i in range(split, len(reg)):
            train = reg.iloc[:i]
            test = reg.iloc[i]
            actual.append(float(np.exp(test[y_col])))
            dates.append(reg.index[i].strftime("%Y-%m-%d"))
            for name, features in model_features.items():
                forecasts[name].append(_fit_predict_log(train, test, y_col, features))
        actual_arr = np.asarray(actual)
        qlike_scores = {name: float(qlike(actual_arr, np.asarray(pred))) for name, pred in forecasts.items()}
        base_losses = {
            "har": qlike_pointwise(actual_arr, np.asarray(forecasts["har"])),
            "har_market": qlike_pointwise(actual_arr, np.asarray(forecasts["har_market"])),
        }
        dm_vs_base = {}
        for name in ["har_bnpl", "har_market_bnpl"]:
            base_name = "har" if name == "har_bnpl" else "har_market"
            loss = qlike_pointwise(actual_arr, np.asarray(forecasts[name]))
            t_stat, p_value = dm_test(loss, base_losses[base_name], h=1)
            dm_vs_base[name] = {
                "baseline": base_name,
                "t_stat": float(t_stat),
                "p_value": float(p_value),
                "harvey_abs_t_gt_3": bool(abs(t_stat) > 3.0),
            }
        out[target] = {
            "n_oos": int(len(actual_arr)),
            "oos_start": dates[0] if dates else None,
            "oos_end": dates[-1] if dates else None,
            "qlike": qlike_scores,
            "dm_vs_base": dm_vs_base,
            "best_model": min(qlike_scores, key=qlike_scores.get),
        }
    return out


def macro_context(df: pd.DataFrame) -> dict:
    monthly = pd.DataFrame(
        {
            "bnpl_rv": df["bnpl_rv"].resample("ME").mean(),
            "consumer_loan_delinquency": df["consumer_loan_delinquency"].resample("ME").last(),
            "credit_card_delinquency": df["credit_card_delinquency"].resample("ME").last(),
            "consumer_sentiment": df["consumer_sentiment"].resample("ME").last(),
        }
    ).dropna()
    out = {"n_months": int(len(monthly)), "spearman": {}}
    for col in ["consumer_loan_delinquency", "credit_card_delinquency", "consumer_sentiment"]:
        rho, p_value = stats.spearmanr(monthly["bnpl_rv"], monthly[col])
        out["spearman"][col] = {"rho": float(rho), "p_value": float(p_value)}
    return out


def make_figures(event_results: list[EventResult], oos_results: dict, df: pd.DataFrame) -> None:
    event_df = pd.DataFrame([asdict(item) for item in event_results])
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(TARGETS))
    width = 0.35
    for offset, horizon in [(-0.5, "next_day"), (0.5, "next_5d_mean")]:
        sub = event_df[event_df["horizon"] == horizon].set_index("target").loc[TARGETS]
        ax.bar(x + offset * width, sub["ratio"], width=width, label=horizon)
    ax.axhline(1.0, color="black", linewidth=1, linestyle="--")
    ax.set_xticks(x, TARGETS)
    ax.set_ylabel("Stress / non-stress RV ratio")
    ax.set_title("Lagged BNPL stress signal vs target realized variance")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_EVENT_PATH, dpi=180)
    plt.close(fig)

    q_rows = []
    for target, payload in oos_results.items():
        har = payload["qlike"]["har"]
        market = payload["qlike"]["har_market"]
        q_rows.append({"target": target, "model": "har_bnpl_vs_har", "delta_pct": 100 * (payload["qlike"]["har_bnpl"] / har - 1)})
        q_rows.append(
            {
                "target": target,
                "model": "har_market_bnpl_vs_market",
                "delta_pct": 100 * (payload["qlike"]["har_market_bnpl"] / market - 1),
            }
        )
    q_df = pd.DataFrame(q_rows)
    fig, ax = plt.subplots(figsize=(9, 5))
    width = 0.35
    for offset, model in [(-0.5, "har_bnpl_vs_har"), (0.5, "har_market_bnpl_vs_market")]:
        sub = q_df[q_df["model"] == model].set_index("target").loc[TARGETS]
        ax.bar(x + offset * width, sub["delta_pct"], width=width, label=model)
    ax.axhline(0.0, color="black", linewidth=1)
    ax.set_xticks(x, TARGETS)
    ax.set_ylabel("QLIKE delta %, negative is better")
    ax.set_title("Does BNPL proxy improve rolling OOS forecasts?")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_OOS_PATH, dpi=180)
    plt.close(fig)

    monthly = df[["bnpl_rv", "consumer_loan_delinquency", "credit_card_delinquency", "consumer_sentiment"]].resample("ME").last()
    monthly["bnpl_rv"] = df["bnpl_rv"].resample("ME").mean()
    monthly = monthly.dropna()
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    axes[0].plot(monthly.index, np.sqrt(monthly["bnpl_rv"]) * np.sqrt(252), label="BNPL basket vol", color="#2b6f6a")
    axes[0].set_ylabel("Annualized vol")
    axes[0].legend(frameon=False)
    axes[1].plot(monthly.index, monthly["consumer_loan_delinquency"], label="Consumer loans", color="#5b5b5b")
    axes[1].plot(monthly.index, monthly["credit_card_delinquency"], label="Credit cards", color="#a84c35")
    axes[1].set_ylabel("Delinquency, %")
    axes[1].legend(frameon=False)
    fig.suptitle("BNPL proxy volatility and lagged FRED credit context")
    fig.tight_layout()
    fig.savefig(FIG_MACRO_PATH, dpi=180)
    plt.close(fig)


def build_results(close: pd.DataFrame, fred_panel: pd.DataFrame, fred_meta: dict) -> dict:
    df = build_dataset(close, fred_panel)
    event_results = event_study(df)
    hac_results = fit_hac_regressions(df)
    oos_results = rolling_oos(df)
    macro_results = macro_context(df)
    make_figures(event_results, oos_results, df)

    bnpl_passes = []
    for target, payload in oos_results.items():
        bnpl_pair = payload["dm_vs_base"]["har_bnpl"]
        market_pair = payload["dm_vs_base"]["har_market_bnpl"]
        bnpl_passes.append(bnpl_pair["harvey_abs_t_gt_3"] and payload["qlike"]["har_bnpl"] < payload["qlike"]["har"])
        bnpl_passes.append(
            market_pair["harvey_abs_t_gt_3"] and payload["qlike"]["har_market_bnpl"] < payload["qlike"]["har_market"]
        )
    verdict = "BNPL_PROXY_OOS_PASS" if any(bnpl_passes) else "NULL_NO_ROBUST_OOS_EDGE"

    return {
        "experiment_id": EXPERIMENT_ID,
        "title": "BNPL / consumer-lending public proxy as credit-cycle early warning",
        "status": verdict,
        "seed": SEED,
        "n_bootstrap": N_BOOT,
        "data_sources": {
            "prices": "yfinance adjusted close",
            "fred": fred_meta,
        },
        "sample_start": close.index.min().strftime("%Y-%m-%d"),
        "sample_end": close.index.max().strftime("%Y-%m-%d"),
        "n_price_obs": int(len(close)),
        "tickers": {
            "bnpl_consumer_lender_proxy": BNPL_MEMBERS,
            "targets": TARGETS,
            "market_controls": ["SPY", "^VIX"],
        },
        "methodology": {
            "signal_alignment": "Every predictive BNPL/market/macro feature is lagged with shift(1) or a conservative FRED lag before target-day RV.",
            "target": "Close-to-close squared daily return as noisy daily realized-variance proxy.",
            "event_test": "Lagged BNPL stress signal = prior-day BNPL log RV above its own lagged rolling 252-day 90th percentile; moving-block bootstrap, block=5, seed=42.",
            "oos_test": "Expanding-window OOS log-RV regressions; QLIKE on target-day r^2; DM HAC test with Harvey |t|>3 threshold.",
            "macro_lag": "FRED quarterly delinquency shifted 63 trading days and UMCSENT shifted 21 trading days to avoid revised/release timing lookahead.",
        },
        "event_study": [asdict(item) for item in event_results],
        "hac_regressions": hac_results,
        "oos_model_comparison": oos_results,
        "macro_context": macro_results,
        "summary": {
            "verdict": verdict,
            "best_models": {target: payload["best_model"] for target, payload in oos_results.items()},
            "har_bnpl_dm_t": {
                target: payload["dm_vs_base"]["har_bnpl"]["t_stat"] for target, payload in oos_results.items()
            },
            "har_market_bnpl_dm_t": {
                target: payload["dm_vs_base"]["har_market_bnpl"]["t_stat"] for target, payload in oos_results.items()
            },
            "event_next_day_ratios": {
                item.target: item.ratio for item in event_results if item.horizon == "next_day"
            },
            "event_next_5d_ratios": {
                item.target: item.ratio for item in event_results if item.horizon == "next_5d_mean"
            },
        },
        "research_honesty_notes": [
            "This experiment uses listed lender equity volatility as a public-market proxy, not private BNPL loan-level performance.",
            "FRED delinquency data are slow-moving macro context; the primary forecasting claim rests on daily price-based proxies.",
            "The BNPL public ticker sample starts in 2021, so OOS evidence is short and includes one rate-hike cycle.",
            "Same-day BNPL stress is never multiplied by same-day target returns; the event flag is explicitly lagged one trading day.",
        ],
        "artifacts": {
            "event_figure": FIG_EVENT_PATH.name,
            "oos_figure": FIG_OOS_PATH.name,
            "macro_figure": FIG_MACRO_PATH.name,
        },
    }


def main() -> None:
    close = fetch_close_panel()
    fred_panel, fred_meta = fetch_fred_panel(close.index)
    results = build_results(close, fred_panel, fred_meta)
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
