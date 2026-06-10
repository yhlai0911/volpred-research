"""
K1463: Do free attention/sentiment proxies add volatility forecast value beyond HAR+VIX?

This experiment is deliberately narrower than earlier alt-data sweeps.
Prior work already tested many proxies separately and mostly found VIX
sufficiency. The remaining open angle here is joint, apples-to-apples:

    On one shared daily sample with local pinned data only,
    do free public attention/sentiment proxies improve SPY volatility
    forecasts once HAR lags and VIX are already included?

Proxies tested:
  - CNN Fear & Greed (daily market sentiment)
  - AAII bull-bear spread (weekly survey sentiment)
  - USEPUINDXD (daily policy-news uncertainty; publication-delay adjusted)
  - UMCSENT (monthly consumer sentiment; PIT-aligned via release dates)

Target:
  - Daily Parkinson variance from local SPY OHLC
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.offsets import BDay

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "K1463"
TRAIN_WINDOW = 1000
REFIT_EVERY = 63
SEED = 42
START_DATE = pd.Timestamp("2011-01-03")
END_DATE = pd.Timestamp("2023-12-29")
OOS_START = pd.Timestamp("2018-01-01")
HAC_LAGS = 5
BOOTSTRAP_REPS = 1000

SPY_PATH = ROOT.parent / "k1206" / "data" / "SPY.csv"
VIX_PATH = ROOT.parent / "k1312" / "data" / "VIX.csv"
CNNFG_PATH = REPO_ROOT / "storage" / "sentiment" / "cnn_fear_greed_historical.csv"
AAII_PATH = REPO_ROOT / "storage" / "sentiment" / "aaii_sentiment.csv"
USEPU_PATH = ROOT.parent / "k1121" / "data" / "fred_USEPUINDXD.csv"
UMCSENT_PIT_PATH = ROOT.parent / "k1117b" / "data" / "UMCSENT_monthly_pit.csv"

RESULTS_PATH = ROOT / "k1463_results.json"
FIG_PATH = ROOT / "k1463_qlike_and_pvalues.png"


@dataclass
class BootstrapCI:
    mean_diff: float
    ci_95: list[float]


def load_panel() -> pd.DataFrame:
    spy = pd.read_csv(SPY_PATH, parse_dates=["Date"]).sort_values("Date")
    spy = spy[(spy["Date"] >= START_DATE) & (spy["Date"] <= END_DATE)].copy()

    spy["park_var"] = (np.log(spy["High"] / spy["Low"]) ** 2) / (4.0 * np.log(2.0))
    spy["park_lag1"] = spy["park_var"].shift(1)
    spy["park_lag5"] = spy["park_var"].shift(1).rolling(5).mean()
    spy["park_lag22"] = spy["park_var"].shift(1).rolling(22).mean()

    spy["log_target"] = np.log(spy["park_var"].clip(lower=1e-12))
    for c in ["park_lag1", "park_lag5", "park_lag22"]:
        spy[f"log_{c}"] = np.log(spy[c].clip(lower=1e-12))

    vix = pd.read_csv(VIX_PATH, parse_dates=["Date"]).rename(columns={"^VIX": "vix"})
    spy = spy.merge(vix[["Date", "vix"]], on="Date", how="left")
    spy["log_vix_l1"] = np.log((spy["vix"].shift(1)).clip(lower=1e-12) ** 2)

    cnnfg = pd.read_csv(CNNFG_PATH)
    cnnfg["Date"] = pd.to_datetime(cnnfg["Date"])
    cnnfg["cnnfg"] = pd.to_numeric(cnnfg["Fear Greed"], errors="coerce")
    spy = spy.merge(cnnfg[["Date", "cnnfg"]], on="Date", how="left")
    spy["cnnfg_l1"] = spy["cnnfg"].shift(1)

    aaii = (
        pd.read_csv(AAII_PATH, parse_dates=["Date"])[["Date", "Bull_Bear_Spread"]]
        .dropna()
        .rename(columns={"Bull_Bear_Spread": "aaii"})
        .sort_values("Date")
    )
    # Conservative timing: report becomes usable next business day.
    aaii["release_date"] = aaii["Date"] + BDay(1)
    spy = pd.merge_asof(
        spy.sort_values("Date"),
        aaii[["release_date", "aaii"]].sort_values("release_date"),
        left_on="Date",
        right_on="release_date",
        direction="backward",
    )
    spy["aaii_l1"] = spy["aaii"].shift(1)

    usepu = (
        pd.read_csv(USEPU_PATH, parse_dates=["DATE"])
        .rename(columns={"DATE": "Date", "USEPUINDXD": "usepu"})
        .sort_values("Date")
    )
    spy = spy.merge(usepu[["Date", "usepu"]], on="Date", how="left")
    # Per error_log/K1121: publish day + trading lag => conservative shift(2).
    spy["usepu_l2"] = np.log1p(spy["usepu"].shift(2).clip(lower=0.0))

    umcsent = (
        pd.read_csv(UMCSENT_PIT_PATH, parse_dates=["release_date"])[["release_date", "value"]]
        .rename(columns={"value": "umcsent"})
        .sort_values("release_date")
    )
    spy = pd.merge_asof(
        spy.sort_values("Date"),
        umcsent,
        left_on="Date",
        right_on="release_date",
        direction="backward",
    )
    spy["umcsent_l1"] = spy["umcsent"].shift(1)

    keep_cols = [
        "Date",
        "park_var",
        "log_target",
        "log_park_lag1",
        "log_park_lag5",
        "log_park_lag22",
        "log_vix_l1",
        "cnnfg_l1",
        "aaii_l1",
        "usepu_l2",
        "umcsent_l1",
    ]
    return spy[keep_cols].dropna().reset_index(drop=True)


def fit_hac(df: pd.DataFrame, feats: list[str]) -> dict:
    fit = sm.OLS(df["log_target"], sm.add_constant(df[feats])).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}
    )
    return {
        "params": {k: float(v) for k, v in fit.params.items()},
        "pvalues": {k: float(v) for k, v in fit.pvalues.items()},
        "r2": float(fit.rsquared),
        "n": int(fit.nobs),
    }


def bootstrap_ci(diff: np.ndarray, seed: int = SEED) -> BootstrapCI:
    rng = np.random.default_rng(seed)
    boot = np.empty(BOOTSTRAP_REPS)
    n = len(diff)
    for i in range(BOOTSTRAP_REPS):
        idx = rng.integers(0, n, size=n)
        boot[i] = float(np.mean(diff[idx]))
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return BootstrapCI(mean_diff=float(np.mean(diff)), ci_95=[float(lo), float(hi)])


def run_oos(df: pd.DataFrame, models: dict[str, list[str]]) -> dict:
    start_idx = int(df.index[df["Date"] >= OOS_START][0])
    fits = {}
    preds = {name: [] for name in models}
    actual = []
    dates = []

    for i in range(start_idx, len(df)):
        if i < TRAIN_WINDOW:
            continue
        if (i - start_idx) % REFIT_EVERY == 0 or not fits:
            train = df.iloc[i - TRAIN_WINDOW : i]
            for name, feats in models.items():
                fits[name] = sm.OLS(
                    train["log_target"], sm.add_constant(train[feats], has_constant="add")
                ).fit()

        row = df.iloc[[i]]
        actual.append(float(row["park_var"].iloc[0]))
        dates.append(str(row["Date"].iloc[0].date()))
        for name, feats in models.items():
            pred = fits[name].predict(sm.add_constant(row[feats], has_constant="add")).iloc[0]
            preds[name].append(float(np.exp(pred)))

    actual_arr = np.array(actual)
    losses = {name: qlike_pointwise(actual_arr, np.array(vals)) for name, vals in preds.items()}
    out = {
        "metadata": {
            "train_window": TRAIN_WINDOW,
            "refit_every": REFIT_EVERY,
            "oos_start": dates[0],
            "oos_end": dates[-1],
            "n_oos": len(actual_arr),
        },
        "qlike": {name: float(qlike(actual_arr, np.array(vals))) for name, vals in preds.items()},
        "pairwise_dm_vs_har_vix": {},
        "bootstrap_vs_har_vix": {},
    }

    base = losses["har_vix"]
    for name, loss in losses.items():
        if name in {"har", "har_vix"}:
            continue
        t_stat, p_val = dm_test(base, loss, h=1)
        diff = loss - base
        out["pairwise_dm_vs_har_vix"][name] = {
            "dm_t": float(t_stat),
            "dm_p": float(p_val),
            "harvey_pass": bool(abs(t_stat) > 3.0),
        }
        out["bootstrap_vs_har_vix"][name] = asdict(bootstrap_ci(diff))
    return out


def make_figure(results: dict) -> None:
    q = results["oos"]["qlike"]
    order = [
        "har",
        "har_vix",
        "har_vix_cnnfg",
        "har_vix_aaii",
        "har_vix_usepu",
        "har_vix_umcsent",
        "har_vix_all",
    ]
    labels = ["HAR", "HAR+VIX", "+CNNFG", "+AAII", "+USEPU", "+UMCSENT", "+ALL"]
    vals = [q[k] for k in order]

    pvals = [
        results["full_sample_hac"]["har_vix_cnnfg"]["pvalues"]["cnnfg_l1"],
        results["full_sample_hac"]["har_vix_aaii"]["pvalues"]["aaii_l1"],
        results["full_sample_hac"]["har_vix_usepu"]["pvalues"]["usepu_l2"],
        results["full_sample_hac"]["har_vix_umcsent"]["pvalues"]["umcsent_l1"],
        results["full_sample_hac"]["har_vix_all"]["pvalues"]["cnnfg_l1"],
        results["full_sample_hac"]["har_vix_all"]["pvalues"]["usepu_l2"],
    ]
    p_labels = ["CNNFG", "AAII", "USEPU", "UMCSENT", "ALL: CNNFG", "ALL: USEPU"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    axes[0].bar(labels, vals, color=["#4c78a8", "#59a14f", "#f28e2b", "#9c755f", "#e15759", "#b07aa1", "#76b7b2"])
    axes[0].set_title("OOS QLIKE on SPY Parkinson variance")
    axes[0].set_ylabel("Lower is better")
    axes[0].tick_params(axis="x", rotation=25)

    axes[1].bar(p_labels, pvals, color="#7f7f7f")
    axes[1].axhline(0.05, color="red", linestyle="--", linewidth=1)
    axes[1].set_title("Full-sample HAC p-values for proxy coefficients")
    axes[1].set_ylabel("p-value")
    axes[1].tick_params(axis="x", rotation=25)

    fig.suptitle("K1463: Free attention proxies after HAR+VIX")
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    df = load_panel()
    models = {
        "har": ["log_park_lag1", "log_park_lag5", "log_park_lag22"],
        "har_vix": ["log_park_lag1", "log_park_lag5", "log_park_lag22", "log_vix_l1"],
        "har_vix_cnnfg": [
            "log_park_lag1",
            "log_park_lag5",
            "log_park_lag22",
            "log_vix_l1",
            "cnnfg_l1",
        ],
        "har_vix_aaii": [
            "log_park_lag1",
            "log_park_lag5",
            "log_park_lag22",
            "log_vix_l1",
            "aaii_l1",
        ],
        "har_vix_usepu": [
            "log_park_lag1",
            "log_park_lag5",
            "log_park_lag22",
            "log_vix_l1",
            "usepu_l2",
        ],
        "har_vix_umcsent": [
            "log_park_lag1",
            "log_park_lag5",
            "log_park_lag22",
            "log_vix_l1",
            "umcsent_l1",
        ],
        "har_vix_all": [
            "log_park_lag1",
            "log_park_lag5",
            "log_park_lag22",
            "log_vix_l1",
            "cnnfg_l1",
            "aaii_l1",
            "usepu_l2",
            "umcsent_l1",
        ],
    }

    full_sample = {name: fit_hac(df, feats) for name, feats in models.items()}
    oos = run_oos(df, models)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Free attention/sentiment proxies beyond HAR+VIX for SPY volatility",
        "status": "completed",
        "seed": SEED,
        "data": {
            "asset": "SPY",
            "price_source": str(SPY_PATH.relative_to(REPO_ROOT)),
            "vix_source": str(VIX_PATH.relative_to(REPO_ROOT)),
            "proxy_sources": {
                "cnnfg": str(CNNFG_PATH.relative_to(REPO_ROOT)),
                "aaii": str(AAII_PATH.relative_to(REPO_ROOT)),
                "usepu": str(USEPU_PATH.relative_to(REPO_ROOT)),
                "umcsent_pit": str(UMCSENT_PIT_PATH.relative_to(REPO_ROOT)),
            },
            "sample_start": str(df["Date"].min().date()),
            "sample_end": str(df["Date"].max().date()),
            "n_total": int(len(df)),
        },
        "timing_rules": {
            "vix": "lagged 1 trading day",
            "cnnfg": "lagged 1 trading day",
            "aaii": "report date + 1 business day, then lagged 1 day in model",
            "usepu": "shift(2) per publication delay + trading lag rule",
            "umcsent": "PIT release-date alignment, then lagged 1 day in model",
        },
        "literature_reviewed": [
            "Baker, Bloom and Davis (2016) Measuring Economic Policy Uncertainty.",
            "Da, Engelberg and Gao (2011) In Search of Attention.",
            "Shapiro et al. (2022) Measuring News Sentiment.",
            "Corsi (2009) HAR-RV multi-scale volatility persistence.",
        ],
        "full_sample_hac": full_sample,
        "oos": oos,
        "verdict": {
            "result": "MOSTLY_NULL_AFTER_VIX",
            "reason": (
                "VIX materially improves HAR, but free sentiment proxies do not deliver "
                "Harvey-significant OOS gains beyond HAR+VIX; UMCSENT and the all-in stack "
                "are significantly worse out of sample."
            ),
        },
        "notes": [
            "This is not a Google Trends replication; prior direct Trends experiments already exist (K473/K750/K789).",
            "The goal here is shared-sample incremental value after HAR+VIX, not exhaustive proxy discovery.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    make_figure(results)
    print(f"[OK] Saved {RESULTS_PATH}")
    print(f"[OK] Saved {FIG_PATH}")
    print(json.dumps(results["verdict"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
