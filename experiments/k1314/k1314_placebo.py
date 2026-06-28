"""K1314 random-graph placebo checks.

Two outputs are produced:
- A seed=42 single-seed reference for all five assets, preserving the original
  K1314 sanity-check table.
- A 100-seed SPY random-graph distribution, used as an empirical permutation
  check for whether the real Pearson graph beats random graph structure.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import k1314  # reuse helpers

np.random.seed(SEED := 42)
OUT_DIR = Path(__file__).parent
PERMUTATION_SEEDS = list(range(1, 101))
PERMUTATION_ASSET = "SPY"


def random_graph_filter(n: int, k: int, tau: float, rng: np.random.Generator) -> np.ndarray:
    """Random symmetric k-NN graph filter (no correlation info)."""
    A = np.zeros((n, n))
    for i in range(n):
        choices = [j for j in range(n) if j != i]
        nbrs = rng.choice(choices, size=k, replace=False)
        for j in nbrs:
            A[i, j] = rng.uniform(0.1, 1.0)
    A = 0.5 * (A + A.T)
    deg = A.sum(axis=1)
    dinv = np.where(deg > 0, 1.0 / np.sqrt(deg), 0.0)
    D = np.diag(dinv)
    L = np.eye(n) - D @ A @ D
    w, V = np.linalg.eigh(L)
    return V @ np.diag(np.exp(-tau * w)) @ V.T


def gsp_features_random(
    rv: pd.DataFrame, asset: str, oos_index: pd.DatetimeIndex, seed: int = 42
) -> pd.DataFrame:
    n_assets = rv.shape[1]
    asset_idx = list(rv.columns).index(asset)
    all_dates = rv.index
    MIN_HIST = 60
    REFIT_EVERY = 21
    rng = np.random.default_rng(seed)
    filters: dict[pd.Timestamp, np.ndarray] = {}
    last = None
    for i, dt in enumerate(all_dates):
        if i < MIN_HIST:
            continue
        if (i - MIN_HIST) % REFIT_EVERY == 0 or last is None:
            last = random_graph_filter(n_assets, k1314.K_NN, k1314.TAU, rng)
        filters[dt] = last

    rv_lag1 = rv.shift(1)
    rv_lag5 = rv.shift(1).rolling(5).mean()
    rv_lag22 = rv.shift(1).rolling(22).mean()
    gd = pd.Series(index=all_dates, dtype=float)
    gw = pd.Series(index=all_dates, dtype=float)
    gm = pd.Series(index=all_dates, dtype=float)
    for dt in all_dates:
        if dt not in filters:
            continue
        H = filters[dt]
        v_d = rv_lag1.loc[dt].values
        v_w = rv_lag5.loc[dt].values
        v_m = rv_lag22.loc[dt].values
        if np.any(np.isnan(v_d)) or np.any(np.isnan(v_w)) or np.any(np.isnan(v_m)):
            continue
        gd.loc[dt] = (H @ v_d)[asset_idx]
        gw.loc[dt] = (H @ v_w)[asset_idx]
        gm.loc[dt] = (H @ v_m)[asset_idx]
    return pd.DataFrame({"gsp_d": gd, "gsp_w": gw, "gsp_m": gm})


def evaluate_predictions(y: pd.Series, pred_base: pd.Series, pred_alt: pd.Series) -> dict:
    aligned = pd.concat(
        [y.rename("y"), pred_base.rename("base"), pred_alt.rename("alt")], axis=1
    ).dropna()
    q_base = k1314.qlike(aligned["y"].values, aligned["base"].values)
    q_alt = k1314.qlike(aligned["y"].values, aligned["alt"].values)
    d = q_base - q_alt
    dm = k1314.dm_hln_test(d)
    return {
        "n_oos": int(len(aligned)),
        "qlike_baseline": float(np.mean(q_base)),
        "qlike_alt": float(np.mean(q_alt)),
        "improvement_pct": float(
            100.0 * (np.mean(q_base) - np.mean(q_alt)) / np.mean(q_base)
        ),
        "mean_d": float(np.mean(d)),
        "dm_hln": dm,
    }


def run_random_asset(
    rv: pd.DataFrame,
    ticker: str,
    pred_base: pd.Series,
    oos_start_ts: pd.Timestamp,
    seed: int,
) -> dict:
    y = rv[ticker]
    base_X = k1314.har_features(y)
    gsp_X = gsp_features_random(rv, ticker, rv.index[rv.index >= oos_start_ts], seed=seed)
    full_X = pd.concat([base_X, gsp_X], axis=1)
    pred_random = k1314.walk_forward_predict(full_X, y, oos_start_ts)
    result = evaluate_predictions(y, pred_base, pred_random)
    result["qlike_placebo"] = result.pop("qlike_alt")
    result["seed"] = int(seed)
    return result


def run_real_asset(rv: pd.DataFrame, ticker: str, pred_base: pd.Series, oos_start_ts: pd.Timestamp) -> dict:
    y = rv[ticker]
    base_X = k1314.har_features(y)
    gsp_X = k1314.gsp_features(rv, ticker, rv.index[rv.index >= oos_start_ts])
    full_X = pd.concat([base_X, gsp_X], axis=1)
    pred_real = k1314.walk_forward_predict(full_X, y, oos_start_ts)
    result = evaluate_predictions(y, pred_base, pred_real)
    result["qlike_gsp"] = result.pop("qlike_alt")
    return result


def empirical_ge_p_value(observed: float, samples: list[float]) -> tuple[float, int]:
    exceed = int(sum(x >= observed for x in samples))
    return float((exceed + 1) / (len(samples) + 1)), exceed


def main() -> None:
    print(f"[K1314-placebo] start {datetime.now(timezone.utc).isoformat()}")
    rv = k1314.fetch_rv()
    oos_start_ts = pd.Timestamp(k1314.OOS_START)
    out = {}
    pred_base_cache: dict[str, pd.Series] = {}
    for ticker in k1314.TICKERS:
        y = rv[ticker]
        base_X = k1314.har_features(y)
        pred_base = k1314.walk_forward_predict(base_X, y, oos_start_ts)
        pred_base_cache[ticker] = pred_base
        out[ticker] = run_random_asset(rv, ticker, pred_base, oos_start_ts, seed=SEED)
        print(
            f"[K1314-placebo] seed=42 {ticker} "
            f"qlike_base={out[ticker]['qlike_baseline']:.4f} "
            f"qlike_placebo={out[ticker]['qlike_placebo']:.4f} "
            f"DM t={out[ticker]['dm_hln']['t_stat']:.3f} "
            f"p={out[ticker]['dm_hln']['p_value']:.4f}"
        )

    print(f"[K1314-placebo] {PERMUTATION_ASSET} 100-seed random graph distribution...")
    observed = run_real_asset(
        rv, PERMUTATION_ASSET, pred_base_cache[PERMUTATION_ASSET], oos_start_ts
    )
    trials = []
    for seed in PERMUTATION_SEEDS:
        trial = run_random_asset(
            rv, PERMUTATION_ASSET, pred_base_cache[PERMUTATION_ASSET], oos_start_ts, seed
        )
        trials.append(
            {
                "seed": int(seed),
                "improvement_pct": trial["improvement_pct"],
                "mean_d": trial["mean_d"],
                "dm_t_stat": trial["dm_hln"]["t_stat"],
                "dm_p_value": trial["dm_hln"]["p_value"],
                "qlike_placebo": trial["qlike_placebo"],
            }
        )
        if seed % 10 == 0:
            print(f"[K1314-placebo] completed seed {seed}")

    improvements = [t["improvement_pct"] for t in trials]
    mean_ds = [t["mean_d"] for t in trials]
    dm_ts = [t["dm_t_stat"] for t in trials]
    p_improve, exceed_improve = empirical_ge_p_value(observed["improvement_pct"], improvements)
    p_mean_d, exceed_mean_d = empirical_ge_p_value(observed["mean_d"], mean_ds)
    p_dm_t, exceed_dm_t = empirical_ge_p_value(observed["dm_hln"]["t_stat"], dm_ts)
    permutation_tests = {
        PERMUTATION_ASSET: {
            "observed_real_graph": {
                "n_oos": observed["n_oos"],
                "qlike_baseline": observed["qlike_baseline"],
                "qlike_gsp": observed["qlike_gsp"],
                "improvement_pct": observed["improvement_pct"],
                "mean_d": observed["mean_d"],
                "dm_hln": observed["dm_hln"],
            },
            "random_distribution": {
                "n_trials": len(trials),
                "seed_start": PERMUTATION_SEEDS[0],
                "seed_end": PERMUTATION_SEEDS[-1],
                "improvement_pct_mean": float(np.mean(improvements)),
                "improvement_pct_std": float(np.std(improvements, ddof=1)),
                "improvement_pct_min": float(np.min(improvements)),
                "improvement_pct_median": float(np.median(improvements)),
                "improvement_pct_max": float(np.max(improvements)),
                "dm_t_stat_mean": float(np.mean(dm_ts)),
                "dm_t_stat_max": float(np.max(dm_ts)),
                "p_value_ge_observed_improvement_pct": p_improve,
                "p_value_ge_observed_mean_d": p_mean_d,
                "p_value_ge_observed_dm_t": p_dm_t,
                "exceedances_improvement_pct": exceed_improve,
                "exceedances_mean_d": exceed_mean_d,
                "exceedances_dm_t": exceed_dm_t,
            },
            "trials": trials,
        }
    }

    out_path = OUT_DIR / "k1314_placebo_results.json"
    out_path.write_text(
        json.dumps(
            {
                "experiment_id": "k1314_placebo",
                "purpose": (
                    "random-graph placebo for K1314; includes seed=42 reference "
                    "and 100-seed SPY empirical permutation test"
                ),
                "run_at_utc": datetime.now(timezone.utc).isoformat(),
                "single_seed_reference_seed": SEED,
                "single_seed_reference": out,
                "permutation_tests": permutation_tests,
                "interpretation": (
                    "For the SPY permutation test, p-values are empirical upper-tail "
                    "probabilities with +1 smoothing: (random >= observed + 1)/(trials + 1). "
                    "A p-value below 0.01 means no random graph among seeds 1..100 matched "
                    "the real Pearson graph on that statistic."
                ),
            },
            indent=2,
            default=str,
        )
    )
    print(f"[K1314-placebo] -> {out_path}")


if __name__ == "__main__":
    main()
