"""K1355: ML-enhanced daily liquidity proxy -> volatility channel.

This is an honest yfinance-only pilot. True CPQS needs closing bid/ask quotes;
yfinance daily OHLCV does not provide them. The experiment therefore builds a
CPQS-like percent-cost proxy from low-frequency OHLCV features, tests whether a
pre-2020 ML model can estimate that proxy out of sample, then asks whether the
lagged system liquidity factor improves next-day range-variance forecasts over
a HAR-style baseline with VIX.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


SEED = 42
EXP_ID = "K1355"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
RESULTS_PATH = EXP_DIR / "K1355_results.json"
FIG_PATH = EXP_DIR / "K1355_liquidity_vol_channel.png"

START = "2010-01-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")
OOS_START = pd.Timestamp("2020-01-01")
ASSETS = ["SPY", "QQQ", "IWM", "EEM", "HYG", "LQD", "TLT", "GLD"]
TICKERS = ASSETS + ["^VIX"]
EPS = 1e-12


@dataclass
class VolResult:
    asset: str
    train_n: int
    oos_n: int
    baseline_qlike: float
    augmented_qlike: float
    qlike_improvement_pct: float
    dm_t_augmented_vs_baseline: float
    dm_p_augmented_vs_baseline: float
    harvey_pass: bool


def field(raw: pd.DataFrame, name: str, tickers: Iterable[str]) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        if name in raw.columns.get_level_values(0):
            out = raw[name]
        else:
            raise KeyError(name)
    else:
        out = raw[[name]]
    cols = [t for t in tickers if t in out.columns]
    return out[cols].astype(float)


def download_data() -> Dict[str, pd.DataFrame]:
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty panel")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw.to_csv(DATA_DIR / "yfinance_raw_ohlcv.csv")
    return {
        "open": field(raw, "Open", TICKERS),
        "high": field(raw, "High", TICKERS),
        "low": field(raw, "Low", TICKERS),
        "close": field(raw, "Close", TICKERS),
        "adj_close": field(raw, "Adj Close", TICKERS),
        "volume": field(raw, "Volume", TICKERS),
    }


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    """Two-day Corwin-Schultz high-low spread estimate, clipped for stability."""
    hl = np.log(high / low).replace([np.inf, -np.inf], np.nan)
    beta = hl.pow(2) + hl.shift(1).pow(2)
    two_high = pd.concat([high, high.shift(1)], axis=1).max(axis=1)
    two_low = pd.concat([low, low.shift(1)], axis=1).min(axis=1)
    gamma = np.log(two_high / two_low).replace([np.inf, -np.inf], np.nan).pow(2)
    k = 3.0 - 2.0 * np.sqrt(2.0)
    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    return spread.replace([np.inf, -np.inf], np.nan).clip(lower=0.0, upper=0.25)


def rolling_z(x: pd.Series, window: int = 252) -> pd.Series:
    mean = x.rolling(window, min_periods=60).mean()
    std = x.rolling(window, min_periods=60).std(ddof=0)
    return (x - mean) / std.replace(0.0, np.nan)


def build_asset_panel(data: Dict[str, pd.DataFrame], asset: str) -> pd.DataFrame:
    open_ = data["open"][asset]
    high = data["high"][asset]
    low = data["low"][asset]
    close = data["close"][asset]
    adj = data["adj_close"][asset]
    volume = data["volume"][asset]
    vix = data["close"]["^VIX"]

    ret = np.log(adj / adj.shift(1)).replace([np.inf, -np.inf], np.nan)
    close_ret = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan)
    range_pct = ((high - low) / close).replace([np.inf, -np.inf], np.nan)
    range_var = (np.log(high / low).pow(2) / (4.0 * np.log(2.0))).replace(
        [np.inf, -np.inf], np.nan
    )
    cs_spread = corwin_schultz_spread(high, low)
    dollar_vol = (close * volume).replace([np.inf, -np.inf], np.nan)
    amihud = (ret.abs() / (dollar_vol / 1e9)).replace([np.inf, -np.inf], np.nan)

    # CPQS needs closing bid/ask. This is only a positive low-frequency
    # percent-cost proxy built from two established daily ingredients.
    cs_filled = cs_spread.mask(cs_spread <= 0).fillna(range_pct)
    cpqs_like = np.sqrt(range_pct.clip(lower=1e-8) * cs_filled.clip(lower=1e-8))
    cpqs_like = cpqs_like.clip(lower=1e-8, upper=0.50)

    out = pd.DataFrame(
        {
            "asset": asset,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": adj,
            "volume": volume,
            "ret": ret,
            "close_ret": close_ret,
            "range_pct": range_pct,
            "range_var": range_var.clip(lower=1e-12),
            "cs_spread": cs_spread,
            "cpqs_like": cpqs_like,
            "target_log_cpqs_like": np.log(cpqs_like),
            "amihud": amihud,
            "vix": vix,
            "vix_var_daily": (vix / 100.0).pow(2) / 252.0,
            "log_dollar_vol": np.log(dollar_vol.replace(0.0, np.nan)),
            "log_volume": np.log(volume.replace(0.0, np.nan)),
        }
    )

    out["abs_ret_l1"] = out["ret"].abs().shift(1)
    out["range_pct_l1"] = out["range_pct"].shift(1)
    out["range_pct_5_l1"] = out["range_pct"].rolling(5).mean().shift(1)
    out["range_pct_22_l1"] = out["range_pct"].rolling(22).mean().shift(1)
    out["rv_1_l1"] = out["range_var"].shift(1)
    out["rv_5_l1"] = out["range_var"].rolling(5).mean().shift(1)
    out["rv_22_l1"] = out["range_var"].rolling(22).mean().shift(1)
    out["log_dollar_vol_z_l1"] = rolling_z(out["log_dollar_vol"]).shift(1)
    out["log_volume_z_l1"] = rolling_z(out["log_volume"]).shift(1)
    out["amihud_log_l1"] = np.log(out["amihud"].replace(0.0, np.nan)).shift(1)
    out["vix_l1"] = out["vix"].shift(1)
    out["vix_var_daily_l1"] = out["vix_var_daily"].shift(1)
    out["overnight_abs_l1"] = np.log(open_ / close.shift(1)).abs().shift(1)

    return out.reset_index(names="date")


def build_panel(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = [build_asset_panel(data, asset) for asset in ASSETS]
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel.to_csv(DATA_DIR / "derived_panel.csv", index=False)
    return panel


def add_asset_dummies(x: pd.DataFrame) -> pd.DataFrame:
    dummies = pd.get_dummies(x["asset"], prefix="asset", dtype=float)
    return pd.concat([x.drop(columns=["asset"]), dummies], axis=1)


def fit_liquidity_proxy_models(panel: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    feature_cols = [
        "asset",
        "abs_ret_l1",
        "range_pct_l1",
        "range_pct_5_l1",
        "range_pct_22_l1",
        "rv_5_l1",
        "rv_22_l1",
        "log_dollar_vol_z_l1",
        "log_volume_z_l1",
        "amihud_log_l1",
        "vix_l1",
        "overnight_abs_l1",
    ]
    cols = ["date", "target_log_cpqs_like"] + feature_cols
    model_data = panel[cols].dropna().copy()
    train = model_data[model_data["date"] < OOS_START].copy()
    oos = model_data[model_data["date"] >= OOS_START].copy()

    x_train = add_asset_dummies(train[feature_cols])
    x_oos = add_asset_dummies(oos[feature_cols]).reindex(columns=x_train.columns, fill_value=0.0)
    x_all = add_asset_dummies(model_data[feature_cols]).reindex(columns=x_train.columns, fill_value=0.0)
    y_train = train["target_log_cpqs_like"].to_numpy()
    y_oos = oos["target_log_cpqs_like"].to_numpy()

    models = {
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=5.0)),
        "gb": GradientBoostingRegressor(
            random_state=SEED,
            n_estimators=250,
            learning_rate=0.035,
            max_depth=2,
            subsample=0.85,
            min_samples_leaf=20,
        ),
        "mlp": make_pipeline(
            StandardScaler(),
            MLPRegressor(
                hidden_layer_sizes=(16,),
                alpha=0.01,
                max_iter=700,
                random_state=SEED,
                early_stopping=True,
                validation_fraction=0.15,
            ),
        ),
    }

    diagnostics = {}
    pred_frame = model_data[["date", "asset", "target_log_cpqs_like"]].copy()
    for name, model in models.items():
        model.fit(x_train, y_train)
        pred_train = model.predict(x_train)
        pred_oos = model.predict(x_oos)
        pred_all = model.predict(x_all)
        pred_frame[f"{name}_log_cpqs_hat"] = pred_all
        pred_frame[f"{name}_cpqs_hat"] = np.exp(pred_all)
        diagnostics[name] = {
            "train_r2": float(r2_score(y_train, pred_train)),
            "oos_r2": float(r2_score(y_oos, pred_oos)),
            "train_n": int(len(train)),
            "oos_n": int(len(oos)),
        }

    return pred_frame, diagnostics


def asset_standardized_factor(pred: pd.DataFrame, col: str) -> pd.Series:
    train = pred[pred["date"] < OOS_START]
    stats = train.groupby("asset")[col].agg(["mean", "std"]).replace(0.0, np.nan)
    merged = pred.join(stats, on="asset")
    z = (merged[col] - merged["mean"]) / merged["std"]
    daily = z.groupby(merged["date"]).mean().sort_index()
    return daily


def add_liquidity_factors(panel: pd.DataFrame, pred: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    factors = {
        "gb": asset_standardized_factor(pred, "gb_log_cpqs_hat"),
        "ridge": asset_standardized_factor(pred, "ridge_log_cpqs_hat"),
        "mlp": asset_standardized_factor(pred, "mlp_log_cpqs_hat"),
        "raw_proxy": asset_standardized_factor(
            pred.rename(columns={"target_log_cpqs_like": "raw_log_cpqs"}),
            "raw_log_cpqs",
        ),
    }
    factor_df = pd.DataFrame(factors).sort_index()
    factor_df.index.name = "date"

    # Explicit lookahead guard: volatility models use yesterday's system factor.
    for name in factors:
        factor_df[f"{name}_signal"] = factor_df[name].shift(1)

    out = panel.merge(factor_df.reset_index(), on="date", how="left")
    factor_df.to_csv(DATA_DIR / "system_liquidity_factors.csv")
    return out, {
        "factor_start": factor_df.dropna(how="all").index.min().strftime("%Y-%m-%d"),
        "factor_end": factor_df.dropna(how="all").index.max().strftime("%Y-%m-%d"),
        "signal_policy": "system liquidity factor is shifted one trading day via factor.shift(1)",
    }


def fit_log_variance_model(
    train: pd.DataFrame, oos: pd.DataFrame, feature_cols: List[str]
) -> np.ndarray:
    x_train = train[feature_cols].to_numpy(dtype=float)
    y_train = np.log(train["range_var"].to_numpy(dtype=float) + EPS)
    x_oos = oos[feature_cols].to_numpy(dtype=float)
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    model.fit(x_train, y_train)
    pred_log = model.predict(x_oos)
    return np.exp(pred_log).clip(min=EPS)


def evaluate_vol_channel(panel: pd.DataFrame, signal_col: str) -> Tuple[List[VolResult], dict]:
    base_cols = [
        "rv_1_l1",
        "rv_5_l1",
        "rv_22_l1",
        "vix_var_daily_l1",
    ]
    aug_cols = base_cols + [signal_col]
    rows: List[VolResult] = []
    pooled_actual: List[np.ndarray] = []
    pooled_base_pred: List[np.ndarray] = []
    pooled_aug_pred: List[np.ndarray] = []
    loss_frames: List[pd.DataFrame] = []

    for asset in ASSETS:
        sub = panel[panel["asset"] == asset].copy()
        keep = ["date", "range_var"] + aug_cols
        sub = sub[keep].replace([np.inf, -np.inf], np.nan).dropna()
        sub = sub[sub["range_var"] > 0].copy()
        train = sub[sub["date"] < OOS_START].copy()
        oos = sub[sub["date"] >= OOS_START].copy()
        if len(train) < 500 or len(oos) < 252:
            continue
        actual = oos["range_var"].to_numpy(dtype=float)
        base_pred = fit_log_variance_model(train, oos, base_cols)
        aug_pred = fit_log_variance_model(train, oos, aug_cols)
        base_loss = qlike_pointwise(actual, base_pred)
        aug_loss = qlike_pointwise(actual, aug_pred)
        dm_t, dm_p = dm_test(aug_loss, base_loss, h=1)
        base_q = qlike(actual, base_pred)
        aug_q = qlike(actual, aug_pred)
        improvement = (base_q - aug_q) / abs(base_q) * 100.0
        rows.append(
            VolResult(
                asset=asset,
                train_n=int(len(train)),
                oos_n=int(len(oos)),
                baseline_qlike=float(base_q),
                augmented_qlike=float(aug_q),
                qlike_improvement_pct=float(improvement),
                dm_t_augmented_vs_baseline=float(dm_t),
                dm_p_augmented_vs_baseline=float(dm_p),
                harvey_pass=bool(dm_t < -3.0),
            )
        )
        pooled_actual.append(actual)
        pooled_base_pred.append(base_pred)
        pooled_aug_pred.append(aug_pred)
        loss_frames.append(
            pd.DataFrame(
                {
                    "date": oos["date"].to_numpy(),
                    "asset": asset,
                    "base_loss": base_loss,
                    "aug_loss": aug_loss,
                }
            )
        )

    actual_all = np.concatenate(pooled_actual)
    base_all = np.concatenate(pooled_base_pred)
    aug_all = np.concatenate(pooled_aug_pred)
    base_loss_all = qlike_pointwise(actual_all, base_all)
    aug_loss_all = qlike_pointwise(actual_all, aug_all)
    stacked_dm_t, stacked_dm_p = dm_test(aug_loss_all, base_loss_all, h=1)
    loss_panel = pd.concat(loss_frames, ignore_index=True)
    date_losses = loss_panel.groupby("date")[["base_loss", "aug_loss"]].mean().sort_index()
    pooled_dm_t, pooled_dm_p = dm_test(
        date_losses["aug_loss"].to_numpy(),
        date_losses["base_loss"].to_numpy(),
        h=1,
    )
    pooled_base_q = qlike(actual_all, base_all)
    pooled_aug_q = qlike(actual_all, aug_all)
    pooled = {
        "asset_count": int(len(rows)),
        "oos_asset_days": int(len(actual_all)),
        "baseline_qlike": float(pooled_base_q),
        "augmented_qlike": float(pooled_aug_q),
        "qlike_improvement_pct": float((pooled_base_q - pooled_aug_q) / abs(pooled_base_q) * 100.0),
        "dm_t_augmented_vs_baseline": float(pooled_dm_t),
        "dm_p_augmented_vs_baseline": float(pooled_dm_p),
        "harvey_pass": bool(pooled_dm_t < -3.0),
        "dm_method": "date-clustered cross-asset mean loss differential, HAC h=1",
        "stacked_asset_day_dm_diagnostic": {
            "dm_t": float(stacked_dm_t),
            "dm_p": float(stacked_dm_p),
            "note": "diagnostic only; ignores cross-asset same-day dependence",
        },
    }
    return rows, pooled


def make_figure(panel: pd.DataFrame, vol_rows: List[VolResult], pooled: dict) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), constrained_layout=True)

    factor = (
        panel[["date", "gb_signal"]]
        .drop_duplicates("date")
        .set_index("date")["gb_signal"]
        .dropna()
    )
    axes[0].plot(factor.index, factor.values, color="#1f4e79", lw=0.8)
    axes[0].axvline(OOS_START, color="#aa3333", ls="--", lw=1.0)
    axes[0].set_title("Lagged ML system liquidity factor (GB CPQS-like proxy)")
    axes[0].set_ylabel("cross-asset z")

    labels = [r.asset for r in vol_rows]
    vals = [r.qlike_improvement_pct for r in vol_rows]
    colors = ["#2a9d8f" if v > 0 else "#c44e52" for v in vals]
    axes[1].bar(labels, vals, color=colors)
    axes[1].axhline(0.0, color="black", lw=0.8)
    axes[1].set_title(
        "OOS QLIKE improvement from adding lagged liquidity factor "
        f"(pooled {pooled['qlike_improvement_pct']:.2f}%)"
    )
    axes[1].set_ylabel("QLIKE improvement (%)")
    axes[1].set_xlabel("Asset")

    fig.suptitle("K1355 yfinance-only liquidity proxy -> next-day volatility channel")
    fig.savefig(FIG_PATH, dpi=140)
    plt.close(fig)


def verdict_from_results(pooled: dict, vol_rows: List[VolResult]) -> dict:
    improvements = np.array([r.qlike_improvement_pct for r in vol_rows], dtype=float)
    positive = int(np.sum(improvements > 0))
    if pooled["harvey_pass"] and pooled["qlike_improvement_pct"] > 0 and positive >= 5:
        statistical_gate = "PASS"
        verdict = "CONDITIONAL_PASS_PROXY"
        summary = (
            "lagged ML percent-cost proxy improves pooled next-day range-variance "
            "QLIKE at Harvey strength, but true CPQS/bid-ask labels are unavailable"
        )
    elif pooled["qlike_improvement_pct"] > 0 and positive >= 5:
        statistical_gate = "WEAK_PASS"
        verdict = "MIXED_WEAK"
        summary = "directionally positive but not Harvey-strength; treat as exploratory only"
    else:
        statistical_gate = "FAIL"
        verdict = "NULL_PROXY"
        summary = "no robust OOS volatility-channel gain from this yfinance-only liquidity proxy"
    return {
        "verdict": verdict,
        "statistical_gate": statistical_gate,
        "summary": summary,
        "positive_asset_count": positive,
        "asset_count": int(len(vol_rows)),
        "harvey_asset_pass_count": int(sum(r.harvey_pass for r in vol_rows)),
        "claim_ceiling": "proxy-only; does not validate true CPQS or trade-level liquidity without bid/ask or high-frequency labels",
    }


def main() -> dict:
    np.random.seed(SEED)
    data = download_data()
    panel = build_panel(data)
    pred, liq_diag = fit_liquidity_proxy_models(panel)
    panel, factor_diag = add_liquidity_factors(panel, pred)

    vol_rows, pooled = evaluate_vol_channel(panel, "gb_signal")
    raw_rows, raw_pooled = evaluate_vol_channel(panel, "raw_proxy_signal")
    ridge_rows, ridge_pooled = evaluate_vol_channel(panel, "ridge_signal")
    mlp_rows, mlp_pooled = evaluate_vol_channel(panel, "mlp_signal")
    verdict = verdict_from_results(pooled, vol_rows)
    make_figure(panel, vol_rows, pooled)

    min_date = panel["date"].min().strftime("%Y-%m-%d")
    max_date = panel["date"].max().strftime("%Y-%m-%d")
    results = {
        "experiment_id": EXP_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance daily OHLCV, auto_adjust=False",
            "tickers": TICKERS,
            "start_requested": START,
            "end_requested": END,
            "history_start": min_date,
            "history_end": max_date,
            "oos_start": OOS_START.strftime("%Y-%m-%d"),
            "panel_rows": int(len(panel)),
            "raw_snapshot": str(DATA_DIR / "yfinance_raw_ohlcv.csv"),
            "derived_panel": str(DATA_DIR / "derived_panel.csv"),
        },
        "literature_anchor": [
            "Dai, Shi, Zhang (Journal of Financial Markets, forthcoming/2026): ML estimates daily market liquidity from low-frequency data.",
            "Chung and Zhang (2014): closing percent quoted spread (CPQS) uses closing bid/ask quotes.",
            "Corwin and Schultz (2012): high-low spread estimator from daily prices.",
            "Goyenko, Holden, Trzcinka (2009) and Fong, Holden, Trzcinka (2017): low-frequency liquidity proxy validation.",
        ],
        "related_memory": [
            "K150 Amihud Fragility GARCH-X: daily Amihud proxy did not robustly beat GJR/VIX; endogenous to volatility.",
            "K154 daily OFI proxies: in-sample partial signals did not translate to robust OOS vol gains.",
            "K1515 bond illiquidity ML: joint cross-market features did not significantly beat OLS; model-class vs feature-set caveat.",
        ],
        "honesty_constraints": {
            "true_cpqs_available": False,
            "proxy_note": "CPQS requires closing bid/ask. yfinance provides OHLCV only, so cpqs_like is a low-frequency percent-cost proxy, not true CPQS.",
            "lookahead_policy": "all liquidity and HAR/VIX predictors enter volatility tests through explicit .shift(1) columns; OOS models train only on dates before 2020-01-01.",
            "primary_test": "GB-estimated system liquidity factor added to HAR-style range-variance + VIX baseline; QLIKE plus date-clustered HAC DM h=1.",
        },
        "liquidity_proxy_estimation": liq_diag,
        "factor_diagnostics": factor_diag,
        "vol_channel_primary_gb": {
            "per_asset": [asdict(r) for r in vol_rows],
            "pooled": pooled,
        },
        "vol_channel_sensitivity": {
            "raw_proxy_signal_pooled": raw_pooled,
            "ridge_signal_pooled": ridge_pooled,
            "mlp_signal_pooled": mlp_pooled,
            "raw_proxy_per_asset": [asdict(r) for r in raw_rows],
            "ridge_per_asset": [asdict(r) for r in ridge_rows],
            "mlp_per_asset": [asdict(r) for r in mlp_rows],
        },
        "verdict": verdict,
        "artifacts": {
            "results_json": str(RESULTS_PATH),
            "figure": str(FIG_PATH),
        },
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(f"results -> {RESULTS_PATH}")
    print(f"figure  -> {FIG_PATH}")
    return results


if __name__ == "__main__":
    main()
