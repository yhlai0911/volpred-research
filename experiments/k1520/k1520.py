"""K1520: Regime-aware in-context analog volatility forecasting vs HAR.

This experiment tests the reproducible core of regime-aware ICL: selecting
historical demonstrations conditional on the current volatility regime. It does
not call an external LLM API, because API outputs are non-deterministic and hard
to audit. Instead, it uses nearest-neighbor analog retrieval as a transparent
surrogate for the in-context demonstration mechanism.

Forecast origin t predicts SPY variance at t+1 using information available at t.
Training rows are restricted to target dates observed before the forecast target.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

SEED = 42
START = "2007-01-01"
END = "2026-06-17"
OOS_START = "2020-01-02"
WINDOW = 2000
K_NEIGHBORS = 50
HAC_LAGS = 5
MIN_REGIME_NEIGHBORS = 20

OUT_DIR = Path(__file__).parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def fetch_data() -> pd.DataFrame:
    tickers = ["SPY", "^VIX"]
    for attempt in range(3):
        try:
            raw = yf.download(
                tickers,
                start=START,
                end=END,
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
            out = {}
            for ticker in tickers:
                try:
                    out[ticker] = raw[ticker]["Close"].dropna().rename(ticker)
                except Exception:
                    out[ticker] = raw["Close"][ticker].dropna().rename(ticker)
            df = pd.DataFrame(out).sort_index().dropna()
            if len(df) > 3000:
                return df
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] download attempt {attempt + 1}/3 failed: {exc}")
        time.sleep(1 + attempt)
    raise RuntimeError("yfinance download failed")


def build_panel(px: pd.DataFrame) -> pd.DataFrame:
    ret = np.log(px["SPY"]).diff().rename("ret")
    rv = (ret ** 2).clip(lower=1e-10).rename("rv")
    log_rv = np.log(rv).rename("log_rv")

    panel = pd.DataFrame(index=px.index)
    panel["rv_true"] = rv.shift(-1)
    panel["log_target"] = np.log(panel["rv_true"].clip(lower=1e-10))
    panel["log_rv_d"] = log_rv
    panel["log_rv_w"] = log_rv.rolling(5).mean()
    panel["log_rv_m"] = log_rv.rolling(22).mean()
    panel["abs_ret_5"] = ret.abs().rolling(5).mean()
    panel["ret_5"] = ret.rolling(5).sum()
    panel["vol_of_vol_22"] = log_rv.diff().abs().rolling(22).mean()
    panel["vix_lag1"] = px["^VIX"].shift(1)
    panel["log_vix_lag1"] = np.log(panel["vix_lag1"].clip(lower=1e-8))

    vix_q20 = panel["vix_lag1"].expanding(750).quantile(0.20).shift(1)
    vix_q80 = panel["vix_lag1"].expanding(750).quantile(0.80).shift(1)
    trend_gap = (panel["log_rv_d"] - panel["log_rv_m"]).abs()
    trend_q90 = trend_gap.expanding(750).quantile(0.90).shift(1)

    regime = pd.Series("mid", index=panel.index, dtype=object)
    regime = regime.mask(panel["vix_lag1"] <= vix_q20, "low")
    regime = regime.mask(panel["vix_lag1"] >= vix_q80, "high")
    regime = regime.mask(trend_gap >= trend_q90, "trend_break")
    panel["regime"] = regime
    panel["target_date"] = panel.index.to_series().shift(-1)
    panel = panel.dropna()
    return panel


def qlike(true_var: np.ndarray, pred_var: np.ndarray) -> np.ndarray:
    y = np.clip(np.asarray(true_var, dtype=float), 1e-10, None)
    p = np.clip(np.asarray(pred_var, dtype=float), 1e-10, None)
    return np.log(p) + y / p


def dm_hac(loss_model: np.ndarray, loss_base: np.ndarray, max_lag: int = HAC_LAGS) -> dict:
    d = np.asarray(loss_model, dtype=float) - np.asarray(loss_base, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return {"n": int(n), "dm_t": None, "p": None, "mean_diff": None}
    mean = float(np.mean(d))
    centered = d - mean
    gamma0 = float(np.mean(centered * centered))
    hac_var = gamma0
    lag = min(max_lag, n - 2)
    for j in range(1, lag + 1):
        weight = 1.0 - j / (lag + 1.0)
        gamma = float(np.mean(centered[j:] * centered[:-j]))
        hac_var += 2.0 * weight * gamma
    if hac_var <= 0:
        return {"n": int(n), "dm_t": None, "p": None, "mean_diff": mean}
    t_stat = mean / math.sqrt(hac_var / n)
    p_val = 2.0 * (1.0 - stats.norm.cdf(abs(t_stat)))
    return {
        "n": int(n),
        "dm_t": float(t_stat),
        "p": float(p_val),
        "mean_diff": mean,
        "hac_lags": int(lag),
        "direction": "negative favors model",
    }


def fit_linear_predict(train: pd.DataFrame, row: pd.Series, cols: list[str]) -> float:
    x = np.column_stack([np.ones(len(train)), train[cols].to_numpy()])
    y = train["log_target"].to_numpy()
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    x_now = np.array([1.0] + [row[col] for col in cols], dtype=float)
    return float(np.exp(np.dot(x_now, beta)))


def analog_predict(train: pd.DataFrame, row: pd.Series, restrict_regime: bool) -> tuple[float, bool, int]:
    cols = ["log_rv_d", "log_rv_w", "log_rv_m", "abs_ret_5", "ret_5", "vol_of_vol_22", "vix_lag1"]
    candidate = train
    used_fallback = False
    if restrict_regime:
        same = train[train["regime"] == row["regime"]]
        if len(same) >= MIN_REGIME_NEIGHBORS:
            candidate = same
        else:
            used_fallback = True

    mu = train[cols].mean()
    sig = train[cols].std().replace(0, np.nan).fillna(1.0)
    z_train = ((candidate[cols] - mu) / sig).to_numpy()
    z_now = ((row[cols] - mu) / sig).to_numpy(dtype=float)
    dist = np.sqrt(np.sum((z_train - z_now) ** 2, axis=1))
    k = min(K_NEIGHBORS, len(candidate))
    idx = np.argpartition(dist, k - 1)[:k]
    picked_dist = dist[idx]
    picked_y = candidate["log_target"].to_numpy()[idx]
    weights = np.exp(-picked_dist)
    if float(weights.sum()) <= 0:
        weights = np.ones_like(weights)
    pred_log = float(np.sum(weights * picked_y) / np.sum(weights))
    return float(np.exp(pred_log)), used_fallback, int(k)


def rolling_forecasts(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    oos_positions = np.where(panel.index >= pd.Timestamp(OOS_START))[0]
    for pos in oos_positions:
        current_date = panel.index[pos]
        start = max(0, pos - WINDOW)
        train = panel.iloc[start:pos].copy()
        # Forward-label guard: all training targets must be observed by current forecast origin.
        train = train[train["target_date"] <= current_date]
        if len(train) < 750:
            continue
        row = panel.iloc[pos]
        har = fit_linear_predict(train, row, ["log_rv_d", "log_rv_w", "log_rv_m"])
        har_vix = fit_linear_predict(train, row, ["log_rv_d", "log_rv_w", "log_rv_m", "log_vix_lag1"])
        analog_all, _, k_all = analog_predict(train, row, restrict_regime=False)
        analog_regime, fallback, k_regime = analog_predict(train, row, restrict_regime=True)
        combo = float(np.sqrt(har * analog_regime))
        combo_vix = float(np.sqrt(har_vix * analog_regime))
        rows.append(
            {
                "date": current_date,
                "rv_true": float(row["rv_true"]),
                "regime": row["regime"],
                "har": har,
                "har_vix": har_vix,
                "analog_all": analog_all,
                "analog_regime": analog_regime,
                "combo_har_regime": combo,
                "combo_harvix_regime": combo_vix,
                "regime_fallback": bool(fallback),
                "k_all": int(k_all),
                "k_regime": int(k_regime),
            }
        )
    return pd.DataFrame(rows).set_index("date")


def summarize_predictions(pred: pd.DataFrame) -> dict:
    models = ["analog_all", "analog_regime", "combo_har_regime", "combo_harvix_regime"]
    har_loss = qlike(pred["rv_true"], pred["har"])
    har_vix_loss = qlike(pred["rv_true"], pred["har_vix"])
    summary = {
        "n_oos": int(len(pred)),
        "regime_counts": {str(k): int(v) for k, v in pred["regime"].value_counts().sort_index().items()},
        "fallback_share": float(pred["regime_fallback"].mean()),
        "models": {},
        "by_regime": {},
    }
    har_mean = float(np.mean(har_loss))
    har_vix_mean = float(np.mean(har_vix_loss))
    summary["har"] = {"mean_qlike": har_mean}
    summary["har_vix"] = {
        "mean_qlike": har_vix_mean,
        "qlike_improvement_pct_vs_har": float((har_mean - har_vix_mean) / abs(har_mean) * 100.0),
        "dm_vs_har": dm_hac(har_vix_loss, har_loss),
    }
    for model in models:
        loss = qlike(pred["rv_true"], pred[model])
        mean_loss = float(np.mean(loss))
        summary["models"][model] = {
            "mean_qlike": mean_loss,
            "qlike_improvement_pct_vs_har": float((har_mean - mean_loss) / abs(har_mean) * 100.0),
            "dm_vs_har": dm_hac(loss, har_loss),
            "qlike_improvement_pct_vs_har_vix": float((har_vix_mean - mean_loss) / abs(har_vix_mean) * 100.0),
            "dm_vs_har_vix": dm_hac(loss, har_vix_loss),
        }

    for regime, sub in pred.groupby("regime"):
        reg = {"n": int(len(sub)), "har_mean_qlike": float(np.mean(qlike(sub["rv_true"], sub["har"])))}
        base = qlike(sub["rv_true"], sub["har"])
        base_vix = qlike(sub["rv_true"], sub["har_vix"])
        reg["har_vix_mean_qlike"] = float(np.mean(base_vix))
        reg["har_vix_vs_har"] = {
            "qlike_improvement_pct": float((reg["har_mean_qlike"] - reg["har_vix_mean_qlike"]) / abs(reg["har_mean_qlike"]) * 100.0),
            "dm_vs_har": dm_hac(base_vix, base),
        }
        for model in models:
            loss = qlike(sub["rv_true"], sub[model])
            mean_loss = float(np.mean(loss))
            reg[model] = {
                "mean_qlike": mean_loss,
                "qlike_improvement_pct_vs_har": float((reg["har_mean_qlike"] - mean_loss) / abs(reg["har_mean_qlike"]) * 100.0),
                "dm_vs_har": dm_hac(loss, base),
                "qlike_improvement_pct_vs_har_vix": float((reg["har_vix_mean_qlike"] - mean_loss) / abs(reg["har_vix_mean_qlike"]) * 100.0),
                "dm_vs_har_vix": dm_hac(loss, base_vix),
            }
        summary["by_regime"][str(regime)] = reg
    return summary


def multiple_test_correction(summary: dict) -> dict:
    pvals = []
    for model, metrics in summary["models"].items():
        p = metrics["dm_vs_har_vix"]["p"]
        if p is not None:
            pvals.append((f"overall:{model}", p))
    for regime, reg in summary["by_regime"].items():
        for model in ["analog_all", "analog_regime", "combo_har_regime", "combo_harvix_regime"]:
            p = reg[model]["dm_vs_har_vix"]["p"]
            if p is not None:
                pvals.append((f"{regime}:{model}", p))

    ranked = sorted(pvals, key=lambda x: x[1])
    m = len(ranked)
    bh_raw = [min(p * m / rank, 1.0) for rank, (_, p) in enumerate(ranked, start=1)]
    bh_adj = [0.0] * m
    running = 1.0
    for idx in range(m - 1, -1, -1):
        running = min(running, bh_raw[idx])
        bh_adj[idx] = running
    return {
        label: {
            "raw_p": float(p),
            "bonferroni_p": float(min(p * m, 1.0)),
            "bh_p": float(bh_adj[idx]),
            "rank": int(idx + 1),
        }
        for idx, (label, p) in enumerate(ranked)
    }


def derive_verdict(summary: dict, correction: dict) -> tuple[str, str]:
    wins = []
    for label, corr in correction.items():
        scope, model = label.split(":", 1)
        if scope == "overall":
            metrics = summary["models"][model]
        else:
            metrics = summary["by_regime"][scope][model]
        dm_t = metrics["dm_vs_har_vix"]["dm_t"]
        improvement = metrics["qlike_improvement_pct_vs_har_vix"]
        wins.append((label, improvement > 0 and dm_t is not None and dm_t < -3.0 and corr["bh_p"] < 0.05))
    passed = [label for label, ok in wins if ok]
    if any(label.startswith("overall:") for label in passed):
        return "PASS", f"At least one ICL-surrogate model beats HAR overall after BH correction: {passed}."
    if passed:
        return "REGIME_ONLY", f"ICL-surrogate improvement appears only in specific regimes after BH correction: {passed}."
    return (
        "NULL",
        "No analog in-context or regime-aware retrieval variant beats the stricter HAR+VIX baseline under Harvey-style |t|>3 plus BH correction.",
    )


def make_figures(pred: pd.DataFrame, summary: dict) -> list[str]:
    paths = []
    roll = pd.DataFrame(
        {
            "HAR": qlike(pred["rv_true"], pred["har"]),
            "HAR+VIX": qlike(pred["rv_true"], pred["har_vix"]),
            "Analog-All": qlike(pred["rv_true"], pred["analog_all"]),
            "Analog-Regime": qlike(pred["rv_true"], pred["analog_regime"]),
            "Combo": qlike(pred["rv_true"], pred["combo_har_regime"]),
            "Combo+VIX": qlike(pred["rv_true"], pred["combo_harvix_regime"]),
        },
        index=pred.index,
    ).rolling(60).mean()
    fig, ax = plt.subplots(figsize=(12, 5))
    for col in roll.columns:
        ax.plot(roll.index, roll[col], lw=1.0, label=col)
    ax.set_title("K1520 rolling 60-day QLIKE: HAR vs in-context analog variants")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    rel = "figures/k1520_rolling_qlike.png"
    fig.savefig(OUT_DIR / rel, dpi=130)
    plt.close(fig)
    paths.append(rel)

    regimes = list(summary["by_regime"].keys())
    models = ["analog_all", "analog_regime", "combo_har_regime", "combo_harvix_regime"]
    x = np.arange(len(regimes))
    width = 0.25
    fig, ax = plt.subplots(figsize=(11, 5))
    for i, model in enumerate(models):
        vals = [summary["by_regime"][r][model]["qlike_improvement_pct_vs_har_vix"] for r in regimes]
        ax.bar(x + (i - 1) * width, vals, width=width, label=model)
    ax.axhline(0, color="black", lw=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels(regimes)
    ax.set_ylabel("QLIKE improvement vs HAR+VIX (%)")
    ax.set_title("K1520 regime-specific QLIKE improvement vs stricter baseline")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    rel = "figures/k1520_regime_improvement.png"
    fig.savefig(OUT_DIR / rel, dpi=130)
    plt.close(fig)
    paths.append(rel)
    return paths


def main() -> dict:
    np.random.seed(SEED)
    px = fetch_data()
    panel = build_panel(px)
    pred = rolling_forecasts(panel)
    summary = summarize_predictions(pred)
    correction = multiple_test_correction(summary)
    verdict, verdict_reason = derive_verdict(summary, correction)
    figures = make_figures(pred, summary)

    result = {
        "experiment_id": "K1520",
        "title": "Regime-aware in-context analog volatility forecasting vs HAR",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "task_id": "research_regime_aware_in_context_llm_vol_vs_har_regime_ll",
        "random_seed": SEED,
        "data": {
            "source": "yfinance SPY and ^VIX daily close",
            "start": str(panel.index.min().date()),
            "end": str(panel.index.max().date()),
            "oos_start": OOS_START,
            "n_panel": int(len(panel)),
        },
        "methods": {
            "target": "SPY one-day-ahead daily variance r[t+1]^2",
            "baseline": "Rolling HAR-log OLS; stricter primary baseline adds log(VIX_lag1)",
            "icl_surrogate": "nearest-neighbor analog retrieval over lagged volatility/VIX features",
            "regime_aware": "restrict analog demonstrations to current causal regime label when >=20 neighbors exist",
            "combo": "geometric mean of HAR and regime-aware analog predictions",
            "window": WINDOW,
            "k_neighbors": K_NEIGHBORS,
            "inference": f"QLIKE + Newey-West HAC DM maxlags={HAC_LAGS}; primary verdict compares vs HAR+VIX with Harvey-style |t|>3 and BH correction",
        },
        "lookahead_audit": {
            "feature_timing": "forecast origin t uses SPY returns through t and VIX shifted by 1 day",
            "forward_label_training_cutoff": "training rows require target_date <= current forecast origin date",
            "regime_labels": "regime thresholds are expanding quantiles shifted by one day",
            "external_llm": "no non-reproducible API output is used as experimental data",
        },
        "literature": [
            "Asaad, Hamidi, and Bereyhi (2026), Regime-aware financial volatility forecasting via in-context learning, arXiv:2603.10299",
            "Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility",
            "In-Context Learning Under Regime Change, arXiv:2604.16988",
            "Project K149: non-parametric regime matching ICL vs GJR failed to beat GJR on daily r^2 QLIKE",
        ],
        "summary": summary,
        "multiple_test_correction": correction,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "honest_limits": [
            "This is not a live LLM API benchmark; it tests the transparent retrieval/demonstration mechanism behind regime-aware ICL.",
            "Target is daily close-to-close squared return, not high-frequency realized variance.",
            "A true LLM follow-up must freeze prompts, model version, temperature, raw responses, and retry policy before claims are credible.",
        ],
        "figures": figures,
    }
    (OUT_DIR / "k1520_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "reason": verdict_reason}, indent=2))
    return result


if __name__ == "__main__":
    main()
