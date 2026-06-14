"""K1327-v2 -- matched adaptive multi-factor HAR public-proxy test.

This script repairs K1327's Codex review failure by comparing HAR and
multi-factor challengers under the same training window and refit cadence.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


SEED = 42
ROOT = Path(__file__).resolve().parents[2]
BASE_SCRIPT = ROOT / "experiments" / "k1327" / "k1327.py"
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "k1327_v2_results.json"
CHART_PATH = OUT_DIR / "k1327_v2_qlike_comparison.png"


def load_base_module():
    spec = importlib.util.spec_from_file_location("k1327_base", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import base K1327 helper script: {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_chart(primary: dict, sensitivity: dict) -> None:
    primary_names = list(primary["models"].keys())
    primary_values = [primary["models"][name]["qlike"] for name in primary_names]
    sensitivity_names = list(sensitivity["models"].keys())
    sensitivity_values = [sensitivity["models"][name]["qlike"] for name in sensitivity_names]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    colors = ["#4c78a8", "#54a24b", "#e45756"]

    axes[0].bar(primary_names, primary_values, color=colors)
    axes[0].set_title("Primary: rolling 1000 / refit 21d")
    axes[0].set_ylabel("OOS QLIKE (lower is better)")
    axes[0].tick_params(axis="x", rotation=25)

    axes[1].bar(sensitivity_names, sensitivity_values, color=colors)
    axes[1].set_title("Sensitivity: expanding / refit 21d")
    axes[1].tick_params(axis="x", rotation=25)

    fig.suptitle("K1327-v2 matched adaptive multi-factor HAR test")
    fig.tight_layout()
    fig.savefig(CHART_PATH, dpi=160)
    plt.close(fig)


def conclusion_from_primary(primary: dict) -> dict:
    model_qlikes = {name: row["qlike"] for name, row in primary["models"].items()}
    best_model = min(model_qlikes, key=model_qlikes.get)
    strong_winners = [
        name
        for name, row in primary["pairwise_vs_har3"].items()
        if row["harvey_pass"] and row["lower_qlike_model"] == name
    ]
    if strong_winners:
        return {
            "verdict": "PASS",
            "best_model": best_model,
            "summary": "Matched rolling multi-factor model beats HAR3 at Harvey strength: "
            + ", ".join(strong_winners)
            + ".",
        }
    if best_model != "HAR3":
        best_row = primary["pairwise_vs_har3"][best_model]
        return {
            "verdict": "CONDITIONAL_PASS",
            "best_model": best_model,
            "summary": (
                f"{best_model} lowers QLIKE under matched rolling window/refit, "
                f"but DM-HLN t={best_row['dm_t_stat_har3_minus_model']:.3f} remains below Harvey |t|>3."
            ),
        }
    return {
        "verdict": "NULL",
        "best_model": best_model,
        "summary": "No matched rolling multi-factor challenger lowers QLIKE versus HAR3.",
    }


def main() -> None:
    np.random.seed(SEED)
    base = load_base_module()

    master = base.build_master_frame()
    data, all_features, _ = base.add_shifted_factor_features(master)
    train = data[data["date"] < base.OOS_START].copy()
    har_features = ["SPY_rv_lagmean1", "SPY_rv_lagmean5", "SPY_rv_lagmean22"]
    mf_features = all_features
    hyper = base.select_hyperparams(train, mf_features)

    primary_specs = [
        base.ModelSpec("HAR3", "har3", "ols", rolling=True, window=1000, refit_every=21),
        base.ModelSpec(
            "MF_Ridge_rolling_matched",
            "multifactor",
            "ridge",
            alpha=hyper["ridge"]["alpha"],
            rolling=True,
            window=1000,
            refit_every=21,
        ),
        base.ModelSpec(
            "MF_ElasticNet_rolling_matched",
            "multifactor",
            "elasticnet",
            alpha=hyper["elasticnet"]["alpha"],
            l1_ratio=hyper["elasticnet"]["l1_ratio"],
            rolling=True,
            window=1000,
            refit_every=21,
        ),
    ]
    sensitivity_specs = [
        base.ModelSpec("HAR3", "har3", "ols", rolling=False, refit_every=21),
        base.ModelSpec(
            "MF_Ridge_expanding_matched",
            "multifactor",
            "ridge",
            alpha=hyper["ridge"]["alpha"],
            rolling=False,
            refit_every=21,
        ),
        base.ModelSpec(
            "MF_ElasticNet_expanding_matched",
            "multifactor",
            "elasticnet",
            alpha=hyper["elasticnet"]["alpha"],
            l1_ratio=hyper["elasticnet"]["l1_ratio"],
            rolling=False,
            refit_every=21,
        ),
    ]

    primary = base.evaluate_models(data, har_features, mf_features, primary_specs)
    sensitivity = base.evaluate_models(data, har_features, mf_features, sensitivity_specs)
    make_chart(primary, sensitivity)

    _, _, enet_masks = base.walk_forward(data, mf_features, primary_specs[-1])
    selection = base.family_selection_summary(enet_masks, mf_features)
    conclusion = conclusion_from_primary(primary)

    results = {
        "experiment_id": "K1327_v2",
        "predecessor": "K1327",
        "title": "Matched Adaptive Multi-Factor HAR public-proxy test",
        "seed": SEED,
        "data_source": {
            "local_files": [
                "experiments/k1206/data/*.csv",
                "storage/sentiment/vix_historical.csv",
                "storage/sentiment/vvix_historical.csv",
                "storage/sentiment/skew_index.csv",
                "storage/sentiment/credit_spread_proxy.csv",
            ],
            "sample_start": str(data["date"].min().date()),
            "sample_end": str(data["date"].max().date()),
            "oos_start": str(base.OOS_START.date()),
            "n_total": int(len(data)),
            "n_train_pre_oos": int(len(train)),
            "n_features_multifactor": int(len(mf_features)),
        },
        "literature": [
            "Cinquetti, Hong, Nolte & Nolte (2025/2026), Volatility Forecasting Factors",
            "Corsi (2009), HAR-RV",
            "Patton (2011), volatility forecast comparison with imperfect proxies",
        ],
        "method": {
            "target": "SPY daily squared log return",
            "model_space": "log(rv_t)",
            "evaluation": "QLIKE on positive variance forecasts exp(pred_log)",
            "lookahead_policy": "all factor features are shifted by one day before rolling aggregation",
            "hyperparam_selection": "pre-OOS train/validation split only",
            "primary_comparison": "HAR3 and multi-factor challengers all use rolling=True, window=1000, refit_every=21",
            "sensitivity_comparison": "HAR3 and multi-factor challengers all use expanding window, refit_every=21",
        },
        "hyperparams": hyper,
        "evaluation": {
            "primary_matched_rolling": {
                "models": primary["models"],
                "pairwise_vs_har3": primary["pairwise_vs_har3"],
            },
            "sensitivity_expanding": {
                "models": sensitivity["models"],
                "pairwise_vs_har3": sensitivity["pairwise_vs_har3"],
            },
        },
        "rolling_elasticnet_family_selection": selection,
        "conclusion": conclusion,
        "artifacts": {
            "chart": CHART_PATH.name,
            "base_helper_script": str(BASE_SCRIPT.relative_to(ROOT)),
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(results["conclusion"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
