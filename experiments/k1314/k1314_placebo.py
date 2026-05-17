"""K1314 placebo sanity check.

Replace Pearson-correlation graph with a random graph (seeded). If SPY still
shows DM t > 3 in favour of "GSP"-HAR, then the gain is from the extra
regressors / noise, not from cross-asset spillover information — and the main
result is an implementation artifact, not a real signal.

If placebo NULL but main PASS, the SPY gain reflects genuine information from
the correlation-based graph.
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


def main() -> None:
    print(f"[K1314-placebo] start {datetime.now(timezone.utc).isoformat()}")
    rv = k1314.fetch_rv()
    oos_start_ts = pd.Timestamp(k1314.OOS_START)
    out = {}
    for ticker in k1314.TICKERS:
        y = rv[ticker]
        base_X = k1314.har_features(y)
        gsp_X = gsp_features_random(rv, ticker, rv.index[rv.index >= oos_start_ts])
        full_X = pd.concat([base_X, gsp_X], axis=1)
        pred_base = k1314.walk_forward_predict(base_X, y, oos_start_ts)
        pred_gsp = k1314.walk_forward_predict(full_X, y, oos_start_ts)
        aligned = pd.concat(
            [y.rename("y"), pred_base.rename("base"), pred_gsp.rename("gsp")], axis=1
        ).dropna()
        q_base = k1314.qlike(aligned["y"].values, aligned["base"].values)
        q_gsp = k1314.qlike(aligned["y"].values, aligned["gsp"].values)
        d = q_base - q_gsp
        dm = k1314.dm_hln_test(d)
        out[ticker] = {
            "n_oos": int(len(aligned)),
            "qlike_baseline": float(np.mean(q_base)),
            "qlike_placebo": float(np.mean(q_gsp)),
            "improvement_pct": float(100.0 * (np.mean(q_base) - np.mean(q_gsp)) / np.mean(q_base)),
            "dm_hln": dm,
        }
        print(
            f"[K1314-placebo] {ticker} qlike_base={np.mean(q_base):.4f} "
            f"qlike_placebo={np.mean(q_gsp):.4f} DM t={dm['t_stat']:.3f} p={dm['p_value']:.4f}"
        )

    out_path = OUT_DIR / "k1314_placebo_results.json"
    out_path.write_text(
        json.dumps(
            {
                "experiment_id": "k1314_placebo",
                "purpose": "random-graph placebo for K1314 SPY DM=5.4 sanity check",
                "run_at_utc": datetime.now(timezone.utc).isoformat(),
                "per_asset": out,
                "interpretation": (
                    "If SPY DM t-stat under random graph also >3, the K1314 main "
                    "gain is from extra regressors / overfit, not from correlation-graph info."
                ),
            },
            indent=2,
            default=str,
        )
    )
    print(f"[K1314-placebo] -> {out_path}")


if __name__ == "__main__":
    main()
