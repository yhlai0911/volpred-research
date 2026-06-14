from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "K1332"
SEED = 42
START_DATE = "2013-02-11"
END_DATE = "2026-06-14"
OOS_START = pd.Timestamp("2021-01-04")
MIN_TRAIN_OBS = 756
N_BOOT = 1000
EPS = 1e-12

OUTPUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUTPUT_DIR / "k1332_results.json"
FIG_EVENT_PATH = OUTPUT_DIR / "k1332_private_credit_event.png"
FIG_OOS_PATH = OUTPUT_DIR / "k1332_oos_qlike_delta.png"

BDC_PROXY_TICKERS = ["BIZD", "ARCC", "MAIN", "GBDC", "PSEC", "HTGC"]
CREDIT_TICKERS = ["BKLN", "HYG", "LQD"]
TARGETS = ["BKLN", "HYG", "KRE", "IWM"]
MARKET_CONTROLS = ["SPY", "^VIX"]
ALL_TICKERS = sorted(set(BDC_PROXY_TICKERS + CREDIT_TICKERS + TARGETS + MARKET_CONTROLS))


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


def fetch_close_panel() -> tuple[pd.DataFrame, dict]:
    raw = yf.download(
        ALL_TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty panel")

    close = {}
    download_meta = {}
    for ticker in ALL_TICKERS:
        if ticker not in raw.columns.get_level_values(0):
            download_meta[ticker] = {"available": False, "reason": "missing from yfinance panel"}
            continue
        ser = raw[ticker]["Close"].dropna().astype(float)
        if len(ser) < 756:
            download_meta[ticker] = {"available": False, "reason": f"too few close observations: {len(ser)}"}
            continue
        close[ticker] = ser
        download_meta[ticker] = {
            "available": True,
            "first_obs": ser.index.min().strftime("%Y-%m-%d"),
            "last_obs": ser.index.max().strftime("%Y-%m-%d"),
            "n_obs": int(len(ser)),
        }
    panel = pd.DataFrame(close).sort_index()
    required = ["BIZD", "BKLN", "HYG", "LQD", "KRE", "IWM", "SPY", "^VIX"]
    missing_required = [ticker for ticker in required if ticker not in panel.columns]
    if missing_required:
        raise RuntimeError(f"Missing required tickers: {missing_required}")
    return panel.dropna(subset=required), download_meta


def log_rv(ret: pd.Series) -> pd.Series:
    return np.log((ret**2).clip(lower=EPS))


def rolling_log_rv(ret: pd.Series, window: int) -> pd.Series:
    return np.log((ret**2).rolling(window).mean().clip(lower=EPS))


def max_drawdown_from_returns(ret: pd.Series, window: int) -> pd.Series:
    wealth = np.exp(ret.fillna(0.0).cumsum())
    rolling_peak = wealth.rolling(window, min_periods=max(20, window // 4)).max()
    return wealth / rolling_peak - 1.0


def zscore_lagged(series: pd.Series, window: int = 252) -> pd.Series:
    mean = series.rolling(window, min_periods=126).mean()
    std = series.rolling(window, min_periods=126).std(ddof=0)
    return ((series - mean) / std.replace(0.0, np.nan)).shift(1)


def build_dataset(close: pd.DataFrame) -> pd.DataFrame:
    ret = np.log(close).diff()
    df = pd.DataFrame(index=ret.index)

    for ticker in close.columns:
        name = ticker.replace("^", "")
        df[f"{name}_ret"] = ret[ticker]
        df[f"{name}_rv"] = ret[ticker] ** 2
        df[f"{name}_log_rv"] = log_rv(ret[ticker])
        df[f"{name}_log_rv_lag1"] = df[f"{name}_log_rv"].shift(1)
        df[f"{name}_log_rv_lag5"] = rolling_log_rv(ret[ticker], 5).shift(1)
        df[f"{name}_log_rv_lag22"] = rolling_log_rv(ret[ticker], 22).shift(1)

    bdc_members = [ticker for ticker in BDC_PROXY_TICKERS if ticker in close.columns]
    bdc_ret = ret[bdc_members].mean(axis=1)
    df["pc_ret"] = bdc_ret
    df["pc_log_rv"] = log_rv(bdc_ret)
    df["pc_log_rv_lag1"] = df["pc_log_rv"].shift(1)
    df["pc_log_rv_lag5"] = rolling_log_rv(bdc_ret, 5).shift(1)
    df["pc_log_rv_lag22"] = rolling_log_rv(bdc_ret, 22).shift(1)
    df["pc_downside_lag1"] = bdc_ret.clip(upper=0.0).abs().shift(1)
    df["pc_drawdown63_lag1"] = max_drawdown_from_returns(bdc_ret, 63).shift(1)
    df["pc_vs_lqd_20d_lag1"] = (ret["LQD"].rolling(20).sum() - bdc_ret.rolling(20).sum()).shift(1)
    df["pc_stress_z_lag1"] = zscore_lagged(df["pc_log_rv"])

    rv_threshold = df["pc_log_rv"].rolling(252, min_periods=126).quantile(0.90).shift(1)
    dd_threshold = df["pc_drawdown63_lag1"].rolling(252, min_periods=126).quantile(0.10).shift(1)
    raw_stress = (df["pc_log_rv"] > rv_threshold) | (df["pc_drawdown63_lag1"] < dd_threshold)
    # Explicit tradeable alignment: stress observed after day t-1 is used for target day t.
    df["pc_stress_signal_lag1"] = raw_stress.shift(1).fillna(False).astype(int)

    return df.replace([np.inf, -np.inf], np.nan)


def block_bootstrap_event_diff(values: np.ndarray, flags: np.ndarray, block: int = 5) -> dict:
    valid = np.isfinite(values) & np.isfinite(flags)
    values = values[valid]
    flags = flags[valid].astype(bool)
    if flags.sum() < 10 or (~flags).sum() < 10:
        return {"p_value": np.nan, "ci95_low": np.nan, "ci95_high": np.nan}

    obs = values[flags].mean() - values[~flags].mean()
    rng = np.random.default_rng(SEED)
    n = len(values)
    starts = np.arange(max(1, n - block + 1))
    boot = []
    for _ in range(N_BOOT):
        pieces = []
        while sum(len(piece) for piece in pieces) < n:
            start = int(rng.choice(starts))
            pieces.append(np.arange(start, min(start + block, n)))
        idx = np.concatenate(pieces)[:n]
        b_values = values[idx]
        b_flags = flags[idx]
        if b_flags.sum() < 5 or (~b_flags).sum() < 5:
            continue
        boot.append(b_values[b_flags].mean() - b_values[~b_flags].mean())
    boot_arr = np.asarray(boot)
    centered = boot_arr - boot_arr.mean()
    return {
        "p_value": float(np.mean(np.abs(centered) >= abs(obs))),
        "ci95_low": float(np.percentile(boot_arr, 2.5)),
        "ci95_high": float(np.percentile(boot_arr, 97.5)),
    }


def event_study(df: pd.DataFrame) -> list[EventResult]:
    flag = df["pc_stress_signal_lag1"].astype(bool)
    out = []
    for target in TARGETS:
        name = target.replace("^", "")
        series_map = {
            "next_day": df[f"{name}_rv"],
            "next_5d_mean": df[f"{name}_rv"].rolling(5).mean().shift(-4),
        }
        for horizon, values in series_map.items():
            reg = pd.DataFrame({"values": values, "flag": flag}).dropna()
            event_vals = reg.loc[reg["flag"], "values"]
            non_event_vals = reg.loc[~reg["flag"], "values"]
            boot = block_bootstrap_event_diff(reg["values"].to_numpy(), reg["flag"].to_numpy())
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
    common_pc = ["pc_log_rv_lag1", "pc_log_rv_lag5", "pc_downside_lag1", "pc_drawdown63_lag1", "pc_vs_lqd_20d_lag1"]
    market = ["SPY_log_rv_lag1", "VIX_log_rv_lag1"]
    for target in TARGETS:
        name = target.replace("^", "")
        base_cols = [f"{name}_log_rv_lag1", f"{name}_log_rv_lag5", f"{name}_log_rv_lag22"]
        cols = [f"{name}_log_rv", *base_cols, *market, *common_pc]
        reg = df[cols].dropna()
        y = reg[f"{name}_log_rv"]
        base = sm.OLS(y, sm.add_constant(reg[base_cols])).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        aug = sm.OLS(y, sm.add_constant(reg[base_cols + market + common_pc])).fit(
            cov_type="HAC", cov_kwds={"maxlags": 5}
        )
        out[target] = {
            "n_obs": int(len(reg)),
            "baseline_r2": float(base.rsquared),
            "augmented_r2": float(aug.rsquared),
            "delta_r2": float(aug.rsquared - base.rsquared),
            "private_credit_terms": {
                col: {
                    "coef": float(aug.params.get(col, np.nan)),
                    "t_stat": float(aug.tvalues.get(col, np.nan)),
                    "p_value": float(aug.pvalues.get(col, np.nan)),
                }
                for col in common_pc
            },
        }
    return out


def model_features(target: str) -> dict[str, list[str]]:
    name = target.replace("^", "")
    har = [f"{name}_log_rv_lag1", f"{name}_log_rv_lag5", f"{name}_log_rv_lag22"]
    market = ["SPY_log_rv_lag1", "VIX_log_rv_lag1"]
    pc = ["pc_log_rv_lag1", "pc_log_rv_lag5", "pc_downside_lag1", "pc_drawdown63_lag1", "pc_vs_lqd_20d_lag1"]
    return {
        "har": har,
        "har_market": har + market,
        "har_pc": har + pc,
        "har_market_pc": har + market + pc,
    }


def expanding_oos_predictions(reg: pd.DataFrame, y_col: str, features: list[str]) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    preds = []
    actual = []
    dates = []
    start_idx_candidates = np.flatnonzero(reg.index >= OOS_START)
    if len(start_idx_candidates) == 0:
        raise RuntimeError("No OOS rows")
    start_idx = int(start_idx_candidates[0])

    for i in range(start_idx, len(reg)):
        if i < MIN_TRAIN_OBS:
            continue
        train = reg.iloc[:i]
        test = reg.iloc[[i]]
        model = sm.OLS(train[y_col], sm.add_constant(train[features], has_constant="add")).fit()
        pred_log = float(model.predict(sm.add_constant(test[features], has_constant="add")).iloc[0])
        preds.append(float(np.exp(pred_log)))
        actual.append(float(test[y_col.replace("log_rv", "rv")].iloc[0]))
        dates.append(test.index[0])
    return np.asarray(actual), np.asarray(preds), pd.DatetimeIndex(dates)


def rolling_oos(df: pd.DataFrame) -> dict:
    out = {}
    for target in TARGETS:
        name = target.replace("^", "")
        feature_sets = model_features(target)
        needed = [f"{name}_log_rv", f"{name}_rv", *sorted({col for cols in feature_sets.values() for col in cols})]
        reg = df[needed].dropna()
        target_out = {"models": {}, "pairwise": {}}
        losses = {}
        for model_name, features in feature_sets.items():
            actual, preds, dates = expanding_oos_predictions(reg, f"{name}_log_rv", features)
            model_losses = qlike_pointwise(actual, preds)
            losses[model_name] = model_losses
            target_out["models"][model_name] = {
                "qlike": float(qlike(actual, preds)),
                "n_oos": int(len(actual)),
                "first_oos": dates.min().strftime("%Y-%m-%d") if len(dates) else None,
                "last_oos": dates.max().strftime("%Y-%m-%d") if len(dates) else None,
            }
        for base, challenger in [("har", "har_pc"), ("har_market", "har_market_pc")]:
            t_stat, p_value = dm_test(losses[base], losses[challenger], h=1)
            base_q = target_out["models"][base]["qlike"]
            ch_q = target_out["models"][challenger]["qlike"]
            target_out["pairwise"][f"{base}_vs_{challenger}"] = {
                "dm_t_stat_base_minus_challenger": float(t_stat),
                "p_value": float(p_value),
                "harvey_pass": bool(abs(t_stat) > 3.0 and p_value < 0.05),
                "lower_qlike_model": challenger if ch_q < base_q else base,
                "qlike_improvement_pct": float((base_q - ch_q) / base_q * 100.0),
            }
        out[target] = target_out
    return out


def monthly_context(close: pd.DataFrame, df: pd.DataFrame) -> dict:
    monthly = close.resample("ME").last().pct_change()
    pc_m = monthly[[ticker for ticker in BDC_PROXY_TICKERS if ticker in monthly.columns]].mean(axis=1)
    correlations = {}
    for ticker in ["HYG", "BKLN", "KRE", "IWM", "LQD"]:
        reg = pd.DataFrame({"pc": pc_m, ticker: monthly[ticker]}).dropna()
        correlations[ticker] = float(reg["pc"].corr(reg[ticker]))
    stress_share = float(df["pc_stress_signal_lag1"].dropna().mean())
    return {
        "monthly_return_correlations_with_pc_proxy": correlations,
        "stress_signal_share": stress_share,
    }


def make_figures(event_results: list[EventResult], oos: dict) -> None:
    event_df = pd.DataFrame(asdict(row) for row in event_results)
    next_day = event_df[event_df["horizon"] == "next_day"].set_index("target")
    fig, ax = plt.subplots(figsize=(8, 4.8))
    next_day["ratio"].reindex(TARGETS).plot(kind="bar", ax=ax, color="#4C78A8")
    ax.axhline(1.0, color="#333333", linewidth=1)
    ax.set_ylabel("Stress / non-stress next-day RV")
    ax.set_title("K1332 private-credit proxy stress event diagnostic")
    fig.tight_layout()
    fig.savefig(FIG_EVENT_PATH, dpi=160)
    plt.close(fig)

    rows = []
    for target, result in oos.items():
        for pair_name, pair in result["pairwise"].items():
            rows.append({"target": target, "pair": pair_name, "qlike_improvement_pct": pair["qlike_improvement_pct"]})
    qdf = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for pair_name, sub in qdf.groupby("pair"):
        sub = sub.set_index("target").reindex(TARGETS)
        ax.plot(sub.index, sub["qlike_improvement_pct"], marker="o", label=pair_name)
    ax.axhline(0.0, color="#333333", linewidth=1)
    ax.set_ylabel("QLIKE improvement from private-credit features (%)")
    ax.set_title("K1332 rolling OOS incremental QLIKE")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_OOS_PATH, dpi=160)
    plt.close(fig)


def build_conclusion(event_results: list[EventResult], oos: dict) -> dict:
    event_df = pd.DataFrame(asdict(row) for row in event_results)
    next_day = event_df[event_df["horizon"] == "next_day"]
    event_positive = int((next_day["ratio"] > 1.0).sum())
    strong_oos = []
    weak_oos = []
    for target, result in oos.items():
        for pair_name, pair in result["pairwise"].items():
            if pair["lower_qlike_model"].endswith("pc") and pair["harvey_pass"]:
                strong_oos.append(f"{target}:{pair_name}")
            elif pair["lower_qlike_model"].endswith("pc") and pair["qlike_improvement_pct"] > 0:
                weak_oos.append(f"{target}:{pair_name}")
    if strong_oos:
        strong_targets = sorted({item.split(":", 1)[0] for item in strong_oos})
        if set(strong_targets) == set(TARGETS):
            verdict = "PASS"
        else:
            verdict = "PASS_NARROW_CREDIT_ONLY"
        summary = (
            "Private-credit proxy adds Harvey-strength OOS RV forecasting value only for "
            f"{', '.join(strong_targets)}; it does not improve all target markets."
        )
    elif weak_oos:
        verdict = "CONDITIONAL_PASS"
        summary = (
            "Lagged private-credit stress is directionally informative in some OOS comparisons, "
            "but no private-credit feature clears Harvey |t|>3."
        )
    else:
        verdict = "NULL"
        summary = (
            "Private-credit proxy stress is descriptively associated with higher next-day RV, "
            "but it does not improve rolling OOS HAR/market RV forecasts."
        )
    return {
        "verdict": verdict,
        "summary": summary,
        "event_targets_with_ratio_gt_1": event_positive,
        "weak_oos_private_credit_wins": weak_oos,
        "strong_oos_private_credit_wins": strong_oos,
    }


def main() -> None:
    np.random.seed(SEED)
    close, download_meta = fetch_close_panel()
    df = build_dataset(close)
    event_results = event_study(df)
    hac = fit_hac_regressions(df)
    oos = rolling_oos(df)
    context = monthly_context(close, df)
    make_figures(event_results, oos)
    conclusion = build_conclusion(event_results, oos)

    valid_close = close.dropna(subset=["BIZD", "BKLN", "HYG", "LQD", "KRE", "IWM", "SPY", "^VIX"])
    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Private-credit public-market shadow stress proxy",
        "seed": SEED,
        "data_source": {
            "type": "yfinance_adjusted_close",
            "start_requested": START_DATE,
            "end_requested": END_DATE,
            "sample_start_after_required_dropna": valid_close.index.min().strftime("%Y-%m-%d"),
            "sample_end_after_required_dropna": valid_close.index.max().strftime("%Y-%m-%d"),
            "n_required_panel_days": int(len(valid_close)),
            "download_meta": download_meta,
        },
        "literature": [
            {
                "citation": "Financial Stability Board (2026), Report on Vulnerabilities in Private Credit",
                "role": "documents private-credit size, bank/nonbank interlinkages, opacity, valuation, leverage, and data gaps",
                "url": "https://www.fsb.org/2026/05/report-on-vulnerabilities-in-private-credit/",
            },
            {
                "citation": "Federal Reserve FEDS Notes (2025), Bank Lending to Private Credit",
                "role": "defines private credit as nonbank lending including BDC vehicles and documents bank links to private credit funds",
                "url": "https://www.federalreserve.gov/econres/notes/feds-notes/bank-lending-to-private-credit-size-characteristics-and-financial-stability-implications-20250523.html",
            },
            {
                "citation": "IMF Global Financial Stability Report (2024), The Rise and Risks of Private Credit",
                "role": "motivates private-credit risk monitoring under borrower fragility and opaque valuations",
                "url": "https://www.elibrary.imf.org/display/book/9798400257704/CH002.xml",
            },
            {
                "citation": "VanEck BIZD product materials",
                "role": "BIZD as public BDC ETF proxy for listed private-credit exposure",
                "url": "https://www.vaneck.com/us/en/investments/bdc-income-etf-bizd/",
            },
        ],
        "method": {
            "private_credit_proxy": {
                "members": [ticker for ticker in BDC_PROXY_TICKERS if ticker in close.columns],
                "features": [
                    "pc_log_rv_lag1",
                    "pc_log_rv_lag5",
                    "pc_downside_lag1",
                    "pc_drawdown63_lag1",
                    "pc_vs_lqd_20d_lag1",
                ],
            },
            "targets": TARGETS,
            "lookahead_policy": "all predictive private-credit and market features are shifted by one trading day; stress signal uses raw_signal.shift(1)",
            "target_proxy": "daily squared close-to-close log return",
            "oos_start": str(OOS_START.date()),
            "minimum_training_observations": MIN_TRAIN_OBS,
            "success_rule": "incremental private-credit features must lower QLIKE and pass Harvey |t| > 3 in DM-HLN comparison",
            "limitations": [
                "true private-credit loan tape, NAV marks, non-traded BDC flows, and borrower-level defaults are not available",
                "BIZD and listed BDC equities are liquid market proxies and can reflect equity discount-rate shocks as well as loan-credit stress",
            ],
        },
        "event_study": [asdict(row) for row in event_results],
        "hac_regressions": hac,
        "rolling_oos": oos,
        "context": context,
        "conclusion": conclusion,
        "artifacts": {
            "event_figure": FIG_EVENT_PATH.name,
            "oos_figure": FIG_OOS_PATH.name,
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(conclusion, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
