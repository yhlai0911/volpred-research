"""K1584: HAR-CJ / co-jump pilot on locally pinned intraday data.

Research question
-----------------
Does splitting realized variance into a continuous component (BPV) and a jump
component improve next-day RV forecasts beyond a plain HAR-RV baseline?

Scope
-----
The only gateable long local intraday panel is TAIFEX TX active-contract
day-session data. This script therefore treats TX as the formal HAR-CJ test.
Local SPY / 0050.TW 5-minute CSVs are short 2026 snapshots and are used only as
a co-jump diagnostic; they are not publication-grade systemic co-jump evidence.

Lookahead policy
----------------
The forecast target at row t is RV_t. Every predictor is constructed from
series.shift(1) before daily / weekly / monthly rolling windows are computed, so
row t uses t-1 and older information only. Expanding OOS forecasts train on rows
strictly before the forecast row.
"""

from __future__ import annotations

import glob
import json
import math
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


EXPERIMENT_ID = "K1584"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
RESULTS_PATH = EXP_DIR / "k1584_results.json"
FORECAST_PATH = DATA_DIR / "tx_harcj_oos_forecasts.csv"
FIG_PATH = FIG_DIR / "k1584_harcj_diagnostics.png"

K1582_TX_CACHE = ROOT / "experiments" / "k1582" / "data" / "tx_active_daily_measures_2017_2026.parquet"
INTRADAY_DIR = ROOT / "data" / "intraday"

SEED = 42
EPS = 1e-12
MIN_TRAIN = 500
GATEABLE_MIN_OOS = 252
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 5
JUMP_SHARE_EVENT_THRESHOLD = 0.01


MODEL_FEATURES = {
    "HAR": ["log_rv_d", "log_rv_w", "log_rv_m"],
    "HAR_C": ["log_cont_d", "log_cont_w", "log_cont_m"],
    "HAR_RVJ": [
        "log_rv_d",
        "log_rv_w",
        "log_rv_m",
        "jump_share_d",
        "jump_share_w",
        "jump_share_m",
        "jump_event_d",
        "jump_event_w",
    ],
    "HAR_CJ": [
        "log_cont_d",
        "log_cont_w",
        "log_cont_m",
        "jump_share_d",
        "jump_share_w",
        "jump_share_m",
        "jump_event_d",
        "jump_event_w",
    ],
    "HAR_CJ_cluster": [
        "log_cont_d",
        "log_cont_w",
        "log_cont_m",
        "jump_share_d",
        "jump_share_w",
        "jump_share_m",
        "jump_event_d",
        "jump_event_w",
        "jump_cluster_w",
        "jump_cluster_m",
    ],
}


def compute_bpv(rets: np.ndarray) -> float:
    """Barndorff-Nielsen-Shephard bipower variation."""
    rets = np.asarray(rets, dtype=float)
    rets = rets[np.isfinite(rets)]
    n = len(rets)
    if n < 2:
        return float("nan")
    abs_r = np.abs(rets)
    return float((np.pi / 2.0) * (n / (n - 1.0)) * np.sum(abs_r[1:] * abs_r[:-1]))


def daily_measures_from_prices(date: pd.Timestamp, prices: np.ndarray) -> dict | None:
    prices = np.asarray(prices, dtype=float)
    prices = prices[np.isfinite(prices) & (prices > 0)]
    if len(prices) < 12:
        return None
    rets = np.diff(np.log(prices))
    rets = rets[np.isfinite(rets)]
    if len(rets) < 10:
        return None
    rv = float(np.sum(rets * rets))
    if rv <= EPS:
        return None
    bpv = compute_bpv(rets)
    raw_jump = max(rv - bpv, 0.0) if np.isfinite(bpv) else 0.0
    return {
        "date": pd.Timestamp(date).normalize(),
        "rv": rv,
        "bpv": float(bpv),
        "raw_jump": raw_jump,
        "n_returns": int(len(rets)),
    }


def load_tx_daily() -> pd.DataFrame:
    """Load the K1582 TX active-contract daily-measures cache.

    K1582 created this cache from raw TAIFEX TX tick files, selecting the active
    contract by day-session volume and aggregating to 5-minute bars. K1584 uses
    it as a transparent upstream data artifact rather than reparsing thousands
    of raw files every hourly tick.
    """
    if not K1582_TX_CACHE.exists():
        raise FileNotFoundError(
            f"Required TX daily-measures cache not found: {K1582_TX_CACHE}. "
            "Run experiments/k1582/K1582.py first or rebuild the cache from raw TAIFEX files."
        )
    df = pd.read_parquet(K1582_TX_CACHE)
    required = {"date", "rv", "bpv", "raw_jump", "n_returns"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"TX cache is missing required columns: {missing}")
    df = df[list(required) + [c for c in df.columns if c not in required]].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.sort_values("date").reset_index(drop=True)


def _date_from_intraday_path(path: Path) -> pd.Timestamp:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if not match:
        raise ValueError(f"Cannot infer date from {path.name}")
    return pd.Timestamp(match.group(1))


def read_yfinance_5min_file(path: Path) -> dict | None:
    frame = pd.read_csv(path, skiprows=[1, 2])
    if frame.empty or "Close" not in frame.columns:
        return None
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna().to_numpy(dtype=float)
    return daily_measures_from_prices(_date_from_intraday_path(path), close)


def load_short_intraday(label: str, pattern: str) -> pd.DataFrame:
    rows: list[dict] = []
    for name in sorted(glob.glob(str(INTRADAY_DIR / pattern))):
        row = read_yfinance_5min_file(Path(name))
        if row is not None:
            row["asset"] = label
            rows.append(row)
    if not rows:
        raise ValueError(f"No local 5-minute rows found for {label}")
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def add_components(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().sort_values("date").reset_index(drop=True)
    out["rv"] = pd.to_numeric(out["rv"], errors="coerce").clip(lower=EPS)
    out["bpv"] = pd.to_numeric(out["bpv"], errors="coerce")
    out["continuous_var"] = np.minimum(out["bpv"].clip(lower=EPS), out["rv"])
    out["jump_var"] = np.maximum(out["rv"] - out["continuous_var"], 0.0)
    if "raw_jump" in out.columns:
        raw_jump = pd.to_numeric(out["raw_jump"], errors="coerce").clip(lower=0.0)
        out["jump_var"] = np.maximum(out["jump_var"], raw_jump.fillna(0.0))
    out["jump_share"] = (out["jump_var"] / out["rv"]).clip(lower=0.0, upper=10.0)
    out["jump_event"] = (out["jump_share"] > JUMP_SHARE_EVENT_THRESHOLD).astype(float)
    return out


def add_forecast_features(daily: pd.DataFrame) -> pd.DataFrame:
    d = add_components(daily)

    base_series = {
        "rv": d["rv"],
        "cont": d["continuous_var"],
        "jump_var": d["jump_var"],
        "jump_share": d["jump_share"],
        "jump_event": d["jump_event"],
    }
    for name, series in base_series.items():
        lag = series.shift(1)
        d[f"{name}_d"] = lag
        d[f"{name}_w"] = lag.rolling(5, min_periods=5).mean()
        d[f"{name}_m"] = lag.rolling(22, min_periods=22).mean()

    d["jump_cluster_w"] = d["jump_event"].shift(1).rolling(5, min_periods=5).mean()
    d["jump_cluster_m"] = d["jump_event"].shift(1).rolling(22, min_periods=22).mean()

    for col in ["rv_d", "rv_w", "rv_m", "cont_d", "cont_w", "cont_m"]:
        d[f"log_{col}"] = np.log(d[col].clip(lower=EPS))
    d["log_rv"] = np.log(d["rv"].clip(lower=EPS))

    needed = sorted({c for cols in MODEL_FEATURES.values() for c in cols} | {"log_rv", "rv"})
    return d.dropna(subset=needed).reset_index(drop=True)


def fit_predict_log_ols(train: pd.DataFrame, row: pd.DataFrame, cols: list[str]) -> float:
    x_train = train[cols].to_numpy(dtype=float)
    x_train = np.column_stack([np.ones(len(x_train)), x_train])
    y_train = train["log_rv"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
    resid = y_train - x_train @ beta
    denom = max(len(resid) - len(beta), 1)
    resid_var = float(np.sum(resid * resid) / denom)

    x_test = row[cols].to_numpy(dtype=float)
    x_test = np.column_stack([np.ones(len(x_test)), x_test])
    pred_log = float(x_test[0] @ beta)
    return max(math.exp(pred_log + 0.5 * max(resid_var, 0.0)), EPS)


def expanding_forecasts(features: pd.DataFrame) -> pd.DataFrame:
    if len(features) <= MIN_TRAIN + 10:
        raise ValueError(f"Insufficient rows after warm-up: rows={len(features)}, min_train={MIN_TRAIN}")
    rows: list[dict] = []
    for pos in range(MIN_TRAIN, len(features)):
        train = features.iloc[:pos]
        test = features.iloc[[pos]]
        rec: dict[str, object] = {
            "date": str(pd.Timestamp(test["date"].iloc[0]).date()),
            "actual_rv": float(test["rv"].iloc[0]),
            "jump_share_lag1": float(test["jump_share_d"].iloc[0]),
            "jump_event_lag1": float(test["jump_event_d"].iloc[0]),
        }
        for model, cols in MODEL_FEATURES.items():
            rec[f"{model}_forecast"] = fit_predict_log_ols(train, test, cols)
        rows.append(rec)
    return pd.DataFrame(rows)


def block_bootstrap_mean_ci(diff: np.ndarray, reps: int = BOOTSTRAP_REPS, block: int = BOOTSTRAP_BLOCK) -> dict:
    rng = np.random.default_rng(SEED)
    diff = np.asarray(diff, dtype=float)
    diff = diff[np.isfinite(diff)]
    n = len(diff)
    if n == 0:
        return {"mean": None, "ci_95": [None, None], "reps": reps, "block": block}
    boot = np.empty(reps)
    starts = np.arange(n)
    for b in range(reps):
        vals = []
        while len(vals) < n:
            start = int(rng.choice(starts))
            idx = (start + np.arange(block)) % n
            vals.extend(diff[idx].tolist())
        boot[b] = float(np.mean(vals[:n]))
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return {"mean": float(np.mean(diff)), "ci_95": [float(lo), float(hi)], "reps": reps, "block": block}


def evaluate_tx() -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    daily = load_tx_daily()
    features = add_forecast_features(daily)
    forecasts = expanding_forecasts(features)
    actual = forecasts["actual_rv"].to_numpy(dtype=float)

    losses: dict[str, np.ndarray] = {}
    model_summary: dict[str, dict] = {}
    for model in MODEL_FEATURES:
        pred = forecasts[f"{model}_forecast"].to_numpy(dtype=float)
        loss = qlike_pointwise(actual, pred)
        losses[model] = loss
        model_summary[model] = {
            "mean_qlike": float(np.mean(loss)),
            "mse": float(np.mean((actual - pred) ** 2)),
            "mean_forecast_rv": float(np.mean(pred)),
        }

    har_loss = losses["HAR"]
    pairwise: dict[str, dict] = {}
    for model in MODEL_FEATURES:
        if model == "HAR":
            continue
        t_stat, p_value = dm_test(losses[model], har_loss, h=1)
        diff = losses[model] - har_loss
        improvement = (model_summary["HAR"]["mean_qlike"] - model_summary[model]["mean_qlike"]) / abs(
            model_summary["HAR"]["mean_qlike"]
        )
        pairwise[model] = {
            "dm_t_model_minus_har": float(t_stat),
            "dm_p": float(p_value),
            "qlike_improvement_pct": float(100.0 * improvement),
            "harvey_pass_model_better": bool(t_stat < -3.0 and improvement > 0),
            "bootstrap_mean_loss_diff_model_minus_har": block_bootstrap_mean_ci(diff),
        }

    candidates_better = [
        model
        for model, stats in pairwise.items()
        if stats["qlike_improvement_pct"] > 0 and stats["dm_t_model_minus_har"] < 0
    ]
    harvey_pass = [model for model, stats in pairwise.items() if stats["harvey_pass_model_better"]]
    raw_pass = [
        model
        for model, stats in pairwise.items()
        if stats["qlike_improvement_pct"] > 0 and stats["dm_p"] < 0.05 and stats["dm_t_model_minus_har"] < 0
    ]
    if harvey_pass:
        verdict = "PASS"
    elif raw_pass:
        verdict = "WEAK_RAW_ONLY"
    elif candidates_better:
        verdict = "DIRECTIONAL_ONLY"
    else:
        verdict = "NULL"

    tx_summary = {
        "market": "TAIFEX_TX_active_day_session",
        "data_source": str(K1582_TX_CACHE.relative_to(ROOT)),
        "source_lineage": "K1582 cache generated from raw TAIFEX Daily_*TX.csv tick files; active contract selected by day-session volume.",
        "sample_start": str(pd.Timestamp(daily["date"].min()).date()),
        "sample_end": str(pd.Timestamp(daily["date"].max()).date()),
        "n_daily_raw": int(len(daily)),
        "n_feature_rows": int(len(features)),
        "n_oos": int(len(forecasts)),
        "min_train": MIN_TRAIN,
        "gateable": bool(len(forecasts) >= GATEABLE_MIN_OOS),
        "jump_detection": {
            "continuous_component": "BPV clipped at RV",
            "jump_variance": "max(RV - continuous_component, raw_jump_from_K1582, 0)",
            "jump_event_threshold": f"jump_share > {JUMP_SHARE_EVENT_THRESHOLD}",
            "jump_event_days": int(add_components(daily)["jump_event"].sum()),
            "jump_event_rate": float(add_components(daily)["jump_event"].mean()),
            "mean_jump_variance_share": float(add_components(daily)["jump_share"].mean()),
            "median_jump_variance_share": float(add_components(daily)["jump_share"].median()),
        },
        "models": model_summary,
        "pairwise_vs_har": pairwise,
        "best_model_by_qlike": min(model_summary, key=lambda key: model_summary[key]["mean_qlike"]),
        "verdict": verdict,
    }
    forecasts.to_csv(FORECAST_PATH, index=False)
    return tx_summary, forecasts, add_components(daily)


def cojump_diagnostic() -> dict:
    """Short-panel SPY/0050 co-jump diagnostic only."""
    try:
        spy = add_components(load_short_intraday("SPY", "SPY_5min_2026-*.csv"))
        tw50 = add_components(load_short_intraday("0050.TW", "0050_TW_5min_2026-*.csv"))
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    merged = pd.merge(
        spy[["date", "jump_event", "jump_share", "rv"]].rename(
            columns={"jump_event": "spy_jump_event", "jump_share": "spy_jump_share", "rv": "spy_rv"}
        ),
        tw50[["date", "jump_event", "jump_share", "rv"]].rename(
            columns={"jump_event": "tw50_jump_event", "jump_share": "tw50_jump_share", "rv": "tw50_rv"}
        ),
        on="date",
        how="inner",
    ).sort_values("date")
    n = len(merged)
    if n == 0:
        return {"available": False, "error": "No overlapping SPY/0050 dates"}
    a = merged["spy_jump_event"].astype(int).to_numpy()
    b = merged["tw50_jump_event"].astype(int).to_numpy()
    co = int(np.sum((a == 1) & (b == 1)))
    expected = float(n * np.mean(a) * np.mean(b))
    corr = float(np.corrcoef(a, b)[0, 1]) if len(np.unique(a)) > 1 and len(np.unique(b)) > 1 else float("nan")

    rng = np.random.default_rng(SEED)
    perm = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        perm[i] = np.sum((a == 1) & (rng.permutation(b) == 1))
    p_upper = float((np.sum(perm >= co) + 1) / (BOOTSTRAP_REPS + 1))
    return {
        "available": True,
        "status": "DIAGNOSTIC_ONLY_SHORT_PANEL",
        "sample_start": str(pd.Timestamp(merged["date"].min()).date()),
        "sample_end": str(pd.Timestamp(merged["date"].max()).date()),
        "n_overlap_days": int(n),
        "threshold": f"jump_share > {JUMP_SHARE_EVENT_THRESHOLD}",
        "spy_jump_days": int(np.sum(a)),
        "tw50_jump_days": int(np.sum(b)),
        "cojump_days": co,
        "expected_cojump_days_under_independence": expected,
        "event_indicator_corr": corr,
        "permutation_p_upper": p_upper,
        "interpretation": (
            "Short 2026 SPY/0050 same-calendar-date local panel; not clock-synchronized "
            "systemic co-jump network evidence."
        ),
    }


def make_plot(tx_summary: dict, forecasts: pd.DataFrame, tx_daily: pd.DataFrame) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), constrained_layout=True)

    models = [m for m in MODEL_FEATURES if m != "HAR"]
    improvements = [tx_summary["pairwise_vs_har"][m]["qlike_improvement_pct"] for m in models]
    colors = ["#4C78A8" if v >= 0 else "#E45756" for v in improvements]
    axes[0].bar(models, improvements, color=colors)
    axes[0].axhline(0, color="black", lw=0.8)
    axes[0].axhline(0, color="black", lw=0.8)
    axes[0].set_ylabel("QLIKE improvement vs HAR (%)")
    axes[0].set_title("K1584 TX HAR-CJ forecast comparison")
    axes[0].tick_params(axis="x", rotation=20)

    plot_df = tx_daily.tail(520).copy()
    axes[1].plot(plot_df["date"], plot_df["jump_share"], color="#F58518", lw=1.0, label="Jump variance share")
    axes[1].axhline(JUMP_SHARE_EVENT_THRESHOLD, color="black", lw=0.8, linestyle="--", label="event threshold")
    axes[1].set_ylabel("Jump share")
    axes[1].set_title("Recent TX BNS jump-share diagnostic")
    axes[1].legend(loc="upper right")
    fig.savefig(FIG_PATH, dpi=150)
    plt.close(fig)


def determine_overall_verdict(tx_verdict: str, cojump: dict) -> tuple[str, str]:
    if tx_verdict == "PASS":
        return "PASS", "At least one HAR-CJ candidate beats HAR under Harvey |t|>3 on the gateable TX panel."
    if tx_verdict == "WEAK_RAW_ONLY":
        return (
            "WEAK_RAW_ONLY",
            "A HAR-CJ candidate improves mean QLIKE with raw p<0.05, but no candidate clears the Harvey |t|>3 gate.",
        )
    if tx_verdict == "DIRECTIONAL_ONLY":
        return (
            "DIRECTIONAL_ONLY",
            "A jump-split candidate has lower mean QLIKE, but the evidence is below formal significance gates.",
        )
    return "NULL", "HAR-CJ / jump-split candidates do not improve the gateable TX HAR baseline."


def main() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    tx_summary, forecasts, tx_daily = evaluate_tx()
    cojump = cojump_diagnostic()
    make_plot(tx_summary, forecasts, tx_daily)
    verdict, summary = determine_overall_verdict(tx_summary["verdict"], cojump)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Co-jump / HAR-CJ jump-axis pilot",
        "run_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "summary": summary,
        "research_question": "Does continuous/jump realized-variance decomposition improve next-day RV forecasting beyond HAR?",
        "lookahead_policy": {
            "target": "RV_t",
            "features": "All daily/weekly/monthly predictors are built from source series.shift(1).",
            "oos_fit": "Expanding OLS; each forecast row trains only on rows strictly before that date.",
            "status": "CLEAN for implemented one-step RV forecast target.",
        },
        "statistics": {
            "primary_loss": "Patton QLIKE on realized variance",
            "dm_test": "volpred.stats.model_evaluation.dm_test with h=1; negative t means candidate lower QLIKE than HAR",
            "harvey_gate": "|DM t| > 3 with candidate lower QLIKE",
            "bootstrap": f"Moving-block bootstrap of mean loss difference, B={BOOTSTRAP_REPS}, block={BOOTSTRAP_BLOCK}, seed={SEED}",
        },
        "data_sources": {
            "tx_gateable": tx_summary["data_source"],
            "spy_5min": "data/intraday/SPY_5min_2026-*.csv",
            "tw50_5min": "data/intraday/0050_TW_5min_2026-*.csv",
        },
        "literature": [
            {
                "citation": "Caporin, Kolokolov, and Reno (2017), Systemic co-jumps, Journal of Financial Economics 126(3), 563-591",
                "doi": "10.1016/j.jfineco.2017.06.016",
            },
            {
                "citation": "Ding, Li, Liu, and Zheng (2024), Stock co-jump networks, Journal of Econometrics 239(2), 105420",
                "doi": "10.1016/j.jeconom.2023.01.026",
            },
            {
                "citation": "Corsi, Pirino, and Reno (2010), Threshold bipower variation and the impact of jumps on volatility forecasting, Journal of Econometrics",
                "doi": "10.1016/j.jeconom.2010.07.008",
            },
            {
                "citation": "Bormetti et al. (2015), Modelling systemic price cojumps with Hawkes factor models, Quantitative Finance 15(7), 1137-1156",
                "doi": "10.1080/14697688.2014.996586",
            },
        ],
        "tx_harcj_test": tx_summary,
        "cojump_diagnostic": cojump,
        "figures": [str(FIG_PATH.relative_to(ROOT))],
        "forecast_file": str(FORECAST_PATH.relative_to(ROOT)),
        "caveats": [
            "Formal result is single-market TX day-session; it is a HAR-CJ jump-axis test, not a systemic co-jump network replication.",
            "SPY/0050 co-jump diagnostic has fewer than 252 overlapping days, is same-calendar-date rather than clock-synchronized, and is not gateable.",
            "Jump event count, jump variance, and jump share are distinct metrics; results report each separately where used.",
            "BNS BPV jump split is sensitive to intraday sampling and microstructure; no Lee-Mykland tick-by-tick confirmation is used in the gateable TX forecast.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"[done] verdict={verdict}")
    print(f"[done] wrote {RESULTS_PATH}")
    print(f"[done] wrote {FIG_PATH}")
    return results


if __name__ == "__main__":
    main()
