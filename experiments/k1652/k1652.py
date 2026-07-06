#!/usr/bin/env python3
"""K1652: wrapped-token basis stress as a crypto volatility-regime signal.

This is a conservative daily-public-data proxy experiment. It does not estimate
Hasbrouck/Gonzalo-Granger information shares, because that requires high
frequency synchronized prices. The test here is narrower: do daily wrapped-token
basis/liquidity stress features add out-of-sample forecasting value for native
BTC/ETH next-day squared returns beyond lagged native volatility?

Lookahead policy:
    Target row t is native squared log return at t. Every feature is shifted by
    one day, so the information set is available at t-1 close. High-vol regime
    labels use an expanding 75th percentile threshold shifted by one day.
"""
from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
START = "2019-01-01"
END = "2026-07-05"
TRAIN_FRACTION = 0.60
MIN_OBS = 500
EPS = 1e-12


@dataclass(frozen=True)
class PairSpec:
    pair_id: str
    native: str
    wrapped: str
    asset: str
    note: str


PAIRS = [
    PairSpec("btc_wbtc", "BTC-USD", "WBTC-USD", "BTC", "Wrapped Bitcoin vs native BTC"),
    PairSpec("eth_steth", "ETH-USD", "STETH-USD", "ETH", "Lido stETH vs native ETH"),
    PairSpec("eth_cbeth", "ETH-USD", "CBETH-USD", "ETH", "Coinbase cbETH vs native ETH"),
    PairSpec("eth_weth", "ETH-USD", "WETH-USD", "ETH", "Wrapped ETH vs native ETH"),
]


def _series_from_download(df: pd.DataFrame, field: str, ticker: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        if (field, ticker) in df.columns:
            out = df[(field, ticker)]
        elif field in df.columns.get_level_values(0):
            out = df[field].iloc[:, 0]
        else:
            return pd.Series(dtype=float)
    else:
        if field not in df.columns:
            return pd.Series(dtype=float)
        out = df[field]
    out = pd.to_numeric(out, errors="coerce").dropna()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out.sort_index()


def download_ticker(ticker: str) -> dict[str, pd.Series]:
    raw = yf.download(
        ticker,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    return {
        "close": _series_from_download(raw, "Close", ticker),
        "volume": _series_from_download(raw, "Volume", ticker),
    }


def make_pair_frame(spec: PairSpec, data: dict[str, dict[str, pd.Series]]) -> pd.DataFrame:
    native = data[spec.native]
    wrapped = data[spec.wrapped]
    df = pd.DataFrame(
        {
            "native_close": native["close"],
            "wrapped_close": wrapped["close"],
            "native_volume": native["volume"],
            "wrapped_volume": wrapped["volume"],
        }
    ).dropna(subset=["native_close", "wrapped_close"])

    if df.empty:
        return df

    native_ret = np.log(df["native_close"] / df["native_close"].shift(1))
    wrapped_ret = np.log(df["wrapped_close"] / df["wrapped_close"].shift(1))
    native_rv = native_ret.pow(2)
    basis = np.log(df["wrapped_close"] / df["native_close"])
    basis_mean_30 = basis.rolling(30, min_periods=20).mean()
    basis_std_30 = basis.rolling(30, min_periods=20).std()
    basis_z = (basis - basis_mean_30) / basis_std_30.replace(0, np.nan)
    volume_ratio = np.log((df["wrapped_volume"].fillna(0.0) + 1.0) / (df["native_volume"].fillna(0.0) + 1.0))

    raw_features = pd.DataFrame(index=df.index)
    raw_features["log_lag_rv"] = np.log(native_rv + EPS)
    raw_features["log_rv_7d"] = np.log(native_rv.rolling(7, min_periods=5).mean() + EPS)
    raw_features["log_rv_30d"] = np.log(native_rv.rolling(30, min_periods=20).mean() + EPS)
    raw_features["lag_abs_return"] = native_ret.abs()
    raw_features["basis"] = basis
    raw_features["abs_basis"] = basis.abs()
    raw_features["basis_widening"] = basis.abs().diff()
    raw_features["basis_z"] = basis_z
    raw_features["large_basis"] = (basis_z.abs() > 2.0).astype(float)
    raw_features["volume_ratio"] = volume_ratio
    raw_features["wrapped_abs_return"] = wrapped_ret.abs()

    shifted = raw_features.shift(1)
    threshold = native_rv.expanding(min_periods=252).quantile(0.75).shift(1)
    high_vol = (native_rv > threshold).astype(float).where(threshold.notna())

    out = pd.concat(
        [
            pd.DataFrame(
                {
                    "target_rv": native_rv,
                    "target_log_rv": np.log(native_rv + EPS),
                    "high_vol": high_vol,
                    "high_vol_threshold": threshold,
                    "native_ret": native_ret,
                    "wrapped_ret": wrapped_ret,
                    "basis_unshifted": basis,
                    "basis_z_unshifted": basis_z,
                },
                index=df.index,
            ),
            shifted.add_prefix("x_"),
        ],
        axis=1,
    )
    return out.replace([np.inf, -np.inf], np.nan).dropna()


def _split_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    split = int(len(frame) * TRAIN_FRACTION)
    split = max(252, min(split, len(frame) - 252))
    return frame.iloc[:split].copy(), frame.iloc[split:].copy()


def _predict_ridge(train: pd.DataFrame, test: pd.DataFrame, features: list[str]) -> np.ndarray:
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0, random_state=SEED))
    model.fit(train[features], train["target_log_rv"])
    pred_log = model.predict(test[features])
    return np.exp(pred_log).clip(min=EPS)


def _predict_logit(train: pd.DataFrame, test: pd.DataFrame, features: list[str]) -> np.ndarray | None:
    y_train = train["high_vol"].astype(int)
    y_test = test["high_vol"].astype(int)
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        return None
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=2000, random_state=SEED, class_weight="balanced"),
    )
    model.fit(train[features], y_train)
    return model.predict_proba(test[features])[:, 1]


def _metrics(actual: np.ndarray, pred_base: np.ndarray, pred_aug: np.ndarray) -> dict[str, Any]:
    q_base = qlike(actual, pred_base)
    q_aug = qlike(actual, pred_aug)
    mse_base = float(np.mean((actual - pred_base) ** 2))
    mse_aug = float(np.mean((actual - pred_aug) ** 2))
    loss_q_base = qlike_pointwise(actual, pred_base)
    loss_q_aug = qlike_pointwise(actual, pred_aug)
    loss_mse_base = (actual - pred_base) ** 2
    loss_mse_aug = (actual - pred_aug) ** 2
    dm_q_t, dm_q_p = dm_test(loss_q_aug, loss_q_base, h=1)
    dm_m_t, dm_m_p = dm_test(loss_mse_aug, loss_mse_base, h=1)
    return {
        "qlike_baseline": q_base,
        "qlike_augmented": q_aug,
        "qlike_improvement_pct": (q_base - q_aug) / abs(q_base) * 100.0 if np.isfinite(q_base) and q_base != 0 else None,
        "mse_baseline": mse_base,
        "mse_augmented": mse_aug,
        "mse_improvement_pct": (mse_base - mse_aug) / abs(mse_base) * 100.0 if mse_base != 0 else None,
        "dm_qlike_aug_vs_base_t": dm_q_t,
        "dm_qlike_aug_vs_base_p": dm_q_p,
        "dm_mse_aug_vs_base_t": dm_m_t,
        "dm_mse_aug_vs_base_p": dm_m_p,
        "harvey_pass_qlike": bool(abs(dm_q_t) > 3.0),
        "harvey_pass_mse": bool(abs(dm_m_t) > 3.0),
    }


def _classification_metrics(
    train: pd.DataFrame,
    test: pd.DataFrame,
    base_features: list[str],
    candidate_features: list[str],
) -> dict[str, Any]:
    proba_base = _predict_logit(train, test, base_features)
    proba_aug = _predict_logit(train, test, candidate_features)
    classification: dict[str, Any] = {"available": proba_base is not None and proba_aug is not None}
    if proba_base is not None and proba_aug is not None:
        y = test["high_vol"].astype(int).to_numpy()
        brier_base = brier_score_loss(y, proba_base)
        brier_aug = brier_score_loss(y, proba_aug)
        classification.update(
            {
                "auc_baseline": float(roc_auc_score(y, proba_base)),
                "auc_augmented": float(roc_auc_score(y, proba_aug)),
                "auc_delta": float(roc_auc_score(y, proba_aug) - roc_auc_score(y, proba_base)),
                "brier_baseline": float(brier_base),
                "brier_augmented": float(brier_aug),
                "brier_improvement_pct": float((brier_base - brier_aug) / brier_base * 100.0),
                "oos_high_vol_rate": float(y.mean()),
            }
        )
    return classification


def evaluate_pair(spec: PairSpec, frame: pd.DataFrame) -> dict[str, Any]:
    base_features = ["x_log_lag_rv", "x_log_rv_7d", "x_log_rv_30d", "x_lag_abs_return"]
    stress_features = ["x_abs_basis", "x_basis_widening", "x_basis_z", "x_large_basis", "x_volume_ratio"]
    full_wrapped_features = stress_features + ["x_basis", "x_wrapped_abs_return"]
    full_features = base_features + full_wrapped_features
    stress_only_features = base_features + stress_features
    frame = frame.dropna(subset=["target_rv", "target_log_rv", "high_vol"] + full_features)
    if len(frame) < MIN_OBS:
        return {
            "pair_id": spec.pair_id,
            "native": spec.native,
            "wrapped": spec.wrapped,
            "available": False,
            "reason": f"insufficient aligned observations after feature lag: {len(frame)} < {MIN_OBS}",
        }

    train, test = _split_frame(frame)
    pred_base = _predict_ridge(train, test, base_features)
    pred_aug = _predict_ridge(train, test, full_features)
    pred_stress = _predict_ridge(train, test, stress_only_features)
    actual = test["target_rv"].to_numpy(dtype=float)

    metrics = _metrics(actual, pred_base, pred_aug)
    stress_metrics = _metrics(actual, pred_base, pred_stress)
    classification = _classification_metrics(train, test, base_features, full_features)
    stress_classification = _classification_metrics(train, test, base_features, stress_only_features)

    return {
        "pair_id": spec.pair_id,
        "native": spec.native,
        "wrapped": spec.wrapped,
        "asset": spec.asset,
        "note": spec.note,
        "available": True,
        "sample_start": frame.index.min().date().isoformat(),
        "sample_end": frame.index.max().date().isoformat(),
        "n_total": int(len(frame)),
        "n_train": int(len(train)),
        "n_oos": int(len(test)),
        "train_start": train.index.min().date().isoformat(),
        "train_end": train.index.max().date().isoformat(),
        "oos_start": test.index.min().date().isoformat(),
        "oos_end": test.index.max().date().isoformat(),
        "basis_abs_mean_bp": float(frame["x_abs_basis"].mean() * 10000.0),
        "basis_abs_p95_bp": float(frame["x_abs_basis"].quantile(0.95) * 10000.0),
        "large_basis_rate": float(frame["x_large_basis"].mean()),
        "forecast_metrics": metrics,
        "classification_metrics": classification,
        "stress_only_robustness": {
            "description": "Augmented model excluding basis level and wrapped-token absolute return; retains abs basis, widening, z-score, large-basis indicator, and volume ratio.",
            "forecast_metrics": stress_metrics,
            "classification_metrics": stress_classification,
        },
    }


def make_plot(frames: dict[str, pd.DataFrame], results: list[dict[str, Any]]) -> str:
    plot_pairs = [r["pair_id"] for r in results if r.get("available")][:2]
    if not plot_pairs:
        return ""
    fig, axes = plt.subplots(len(plot_pairs), 1, figsize=(12, 4.2 * len(plot_pairs)), sharex=False)
    if len(plot_pairs) == 1:
        axes = [axes]
    for ax, pair_id in zip(axes, plot_pairs):
        frame = frames[pair_id].copy()
        rv = frame["target_rv"].rolling(7, min_periods=3).mean() * 365.0
        basis_z = frame["basis_z_unshifted"].clip(-8, 8)
        ax.plot(frame.index, basis_z, color="#2C7BB6", lw=1.1, label="basis z-score (clipped)")
        ax2 = ax.twinx()
        ax2.plot(frame.index, rv, color="#D7191C", alpha=0.45, lw=0.9, label="native RV 7d avg annualized")
        ax.axhline(2.0, color="#777777", ls="--", lw=0.7)
        ax.axhline(-2.0, color="#777777", ls="--", lw=0.7)
        ax.set_title(f"{pair_id}: wrapped basis stress vs native realized variance")
        ax.set_ylabel("basis z-score")
        ax2.set_ylabel("annualized variance proxy")
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9)
    fig.tight_layout()
    out = HERE / "k1652_basis_stress.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out.name


def atomic_write_json(payload: dict[str, Any], path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def main() -> None:
    tickers = sorted({p.native for p in PAIRS} | {p.wrapped for p in PAIRS})
    data = {ticker: download_ticker(ticker) for ticker in tickers}
    availability = {
        ticker: {
            "close_rows": int(len(blob["close"])),
            "first": blob["close"].index.min().date().isoformat() if len(blob["close"]) else None,
            "last": blob["close"].index.max().date().isoformat() if len(blob["close"]) else None,
            "volume_nonzero_rows": int((blob["volume"] > 0).sum()) if len(blob["volume"]) else 0,
        }
        for ticker, blob in data.items()
    }

    frames: dict[str, pd.DataFrame] = {}
    pair_results = []
    for spec in PAIRS:
        frame = make_pair_frame(spec, data)
        frames[spec.pair_id] = frame
        pair_results.append(evaluate_pair(spec, frame))

    available = [r for r in pair_results if r.get("available")]
    qlike_passes_full = [
        r for r in available
        if r["forecast_metrics"]["harvey_pass_qlike"]
        and r["forecast_metrics"]["dm_qlike_aug_vs_base_t"] < 0
    ]
    qlike_passes_stress = [
        r for r in available
        if r["stress_only_robustness"]["forecast_metrics"]["harvey_pass_qlike"]
        and r["stress_only_robustness"]["forecast_metrics"]["dm_qlike_aug_vs_base_t"] < 0
    ]
    positive_qlike = [
        r for r in available
        if (r["forecast_metrics"]["qlike_improvement_pct"] or 0.0) > 0.0
    ]
    verdict = (
        "CONDITIONAL_MIXED_DAILY_PROXY"
        if qlike_passes_full or qlike_passes_stress
        else "NULL_DAILY_PUBLIC_PROXY"
    )

    plot_file = make_plot(frames, pair_results)
    payload = {
        "experiment_id": "k1652",
        "title": "Wrapped-token basis stress as daily proxy for BTC/ETH volatility-regime forecasting",
        "created_at": pd.Timestamp.utcnow().isoformat(),
        "seed": SEED,
        "literature_context": [
            {
                "title": "Price Discovery through Wrapped Tokens",
                "source": "SSRN / Economics Letters, 2025",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5300493",
                "role": "Motivates wrapped-token price-discovery and liquidity channel; this experiment does not estimate high-frequency information share.",
            },
            {
                "title": "Towards verifiability of total value locked (TVL) in decentralized finance",
                "source": "BIS Working Paper 1268, 2025",
                "url": "https://www.bis.org/publ/work1268.pdf",
                "role": "Motivates caution around DeFi liquidity/TVL proxies and measurement heterogeneity.",
            },
            {
                "title": "New Evidence on Spillovers Between Crypto Assets and Financial Markets",
                "source": "IMF Working Paper 2023/213",
                "url": "https://www.imf.org/-/media/files/publications/wp/2023/english/wpiea2023213-print-pdf.pdf",
                "role": "Motivates spillover framing and volatility-connectedness caution.",
            },
            {
                "title": "The Economics of Liquid Staking Derivatives: Basis Determinants and Pricing",
                "source": "Journal of Futures Markets, 2025",
                "url": "https://ideas.repec.org/a/wly/jfutmk/v45y2025i2p91-117.html",
                "role": "Motivates treating stETH/cbETH basis as partly structural, not pure peg stress.",
            },
        ],
        "data_sources": {
            "price_volume": "Yahoo Finance via yfinance daily adjusted close and volume",
            "tickers": tickers,
            "start": START,
            "end_exclusive": END,
            "availability": availability,
        },
        "method": {
            "frequency": "daily",
            "target": "native next-day squared log return (daily realized variance proxy)",
            "high_vol_label": "target_rv > expanding 75th percentile threshold shifted by one day",
            "baseline_features": [
                "lagged log squared return",
                "lagged 7d mean log RV",
                "lagged 30d mean log RV",
                "lagged absolute return",
            ],
            "augmented_features": [
                "lagged wrapped/native log basis",
                "lagged absolute basis",
                "lagged basis widening",
                "lagged 30d rolling basis z-score",
                "lagged large-basis indicator |z|>2",
                "lagged log wrapped/native volume ratio",
                "lagged wrapped absolute return",
            ],
            "forecast_model": "chronological 60/40 split; StandardScaler + Ridge(alpha=1) on log RV",
            "classification_model": "chronological 60/40 split; StandardScaler + balanced LogisticRegression",
            "dm_test": "volpred.stats.model_evaluation.dm_test on pointwise QLIKE/MSE losses; Harvey gate |t|>3",
        },
        "lookahead_policy": {
            "feature_lag": "All model features are raw daily features shifted by one row: signal from t-1, target at t.",
            "threshold_lag": "High-vol threshold is expanding 75th percentile of native RV shifted by one row.",
            "code_markers": ["raw_features.shift(1)", "native_rv.expanding(...).quantile(0.75).shift(1)"],
        },
        "pair_results": pair_results,
        "statistical_tests": {
            "primary_test": "Diebold-Mariano HAC test on augmented-vs-baseline pointwise QLIKE losses",
            "harvey_gate": "|t| > 3.0; negative t means augmented model lower loss",
            "pairs": [
                {
                    "pair_id": r["pair_id"],
                    "dm_qlike_t_full": r["forecast_metrics"]["dm_qlike_aug_vs_base_t"] if r.get("available") else None,
                    "dm_qlike_p_full": r["forecast_metrics"]["dm_qlike_aug_vs_base_p"] if r.get("available") else None,
                    "harvey_pass_full": r["forecast_metrics"]["harvey_pass_qlike"] if r.get("available") else None,
                    "dm_qlike_t_stress_only": r["stress_only_robustness"]["forecast_metrics"]["dm_qlike_aug_vs_base_t"] if r.get("available") else None,
                    "dm_qlike_p_stress_only": r["stress_only_robustness"]["forecast_metrics"]["dm_qlike_aug_vs_base_p"] if r.get("available") else None,
                    "harvey_pass_stress_only": r["stress_only_robustness"]["forecast_metrics"]["harvey_pass_qlike"] if r.get("available") else None,
                }
                for r in pair_results
            ],
        },
        "summary": {
            "available_pairs": len(available),
            "positive_qlike_pairs": len(positive_qlike),
            "harvey_significant_augmented_qlike_wins": len(qlike_passes_full),
            "harvey_significant_stress_only_qlike_wins": len(qlike_passes_stress),
            "verdict": verdict,
            "interpretation": (
                "Daily Yahoo wrapped-token basis features do not produce a Harvey-significant out-of-sample QLIKE improvement over native lagged-vol baselines."
                if not (qlike_passes_full or qlike_passes_stress)
                else "Daily wrapped-token features improve QLIKE for some pairs, but classification AUC is weak and liquid-staking basis levels can be structural; treat as conditional/mixed, not publication-ready."
            ),
        },
        "figures": [plot_file] if plot_file else [],
        "limitations": [
            "Daily closes are a coarse proxy and cannot identify high-frequency price discovery or information share.",
            "Yahoo Finance wrapped-token volume can mix venues and may not represent DEX pool depth or bridge liquidity.",
            "No on-chain bridge supply, DeFi pool depth, or liquidity fragmentation data are included in this conservative version.",
            "Chronological split is a single OOS split, not a full rolling production forecast exercise.",
        ],
    }
    atomic_write_json(payload, HERE / "k1652_results.json")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
