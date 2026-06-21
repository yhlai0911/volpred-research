"""
K1511 block bootstrap (1000 iter) for the role-reversal effect.

Reads:  experiments/k1511/k1511_panel.parquet
Writes: experiments/k1511/k1511_bootstrap.json

Block bootstrap respects monthly autocorrelation in next-month return series.
Block length = 6 months (≈ half-year, conservative for monthly equity returns).

Seed: 42
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "experiments" / "k1511" / "k1511_panel.parquet"
OUT = ROOT / "experiments" / "k1511" / "k1511_bootstrap.json"

SEED = 42
N_ITER = 1000
BLOCK_LEN = 6


def hac_beta(y: np.ndarray, x: np.ndarray, maxlags: int = 3) -> tuple[float, float]:
    X = sm.add_constant(x)
    m = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return float(m.params[1]), float(m.tvalues[1])


def block_indices(n: int, block_len: int, rng: np.random.Generator) -> np.ndarray:
    n_blocks = (n // block_len) + 1
    starts = rng.integers(0, n - block_len + 1, size=n_blocks)
    idx = np.concatenate([np.arange(s, s + block_len) for s in starts])
    return idx[:n]


def main():
    panel = pd.read_parquet(PANEL)
    target = panel["inst_sell_retail_buy"].astype(float).to_numpy()
    y = panel["ret_next"].to_numpy()
    n = len(y)

    # Point estimate
    beta_bp_pt, t_pt = hac_beta(y, target)
    beta_bp_pt *= 1e4

    rng = np.random.default_rng(SEED)
    betas = np.empty(N_ITER)
    ts = np.empty(N_ITER)
    for i in range(N_ITER):
        idx = block_indices(n, BLOCK_LEN, rng)
        yi = y[idx]
        xi = target[idx]
        if xi.sum() < 2 or xi.sum() > n - 2:
            # degenerate sample
            betas[i] = np.nan
            ts[i] = np.nan
            continue
        try:
            b, t = hac_beta(yi, xi)
            betas[i] = b * 1e4
            ts[i] = t
        except Exception:
            betas[i] = np.nan
            ts[i] = np.nan

    betas_ok = betas[~np.isnan(betas)]
    ts_ok = ts[~np.isnan(ts)]

    out = {
        "n_iter": N_ITER,
        "block_len_months": BLOCK_LEN,
        "n_valid": int(len(betas_ok)),
        "point_beta_bp": float(beta_bp_pt),
        "point_t": float(t_pt),
        "beta_bp_mean": float(np.mean(betas_ok)),
        "beta_bp_se": float(np.std(betas_ok, ddof=1)),
        "beta_bp_ci95_lo": float(np.percentile(betas_ok, 2.5)),
        "beta_bp_ci95_hi": float(np.percentile(betas_ok, 97.5)),
        "beta_bp_ci90_lo": float(np.percentile(betas_ok, 5)),
        "beta_bp_ci90_hi": float(np.percentile(betas_ok, 95)),
        "t_mean": float(np.mean(ts_ok)),
        "t_pct_abs_gt_196": float(np.mean(np.abs(ts_ok) > 1.96)),
        "p_two_sided_bootstrap": float(2 * min(
            np.mean(betas_ok >= 0), np.mean(betas_ok <= 0))),
        "seed": SEED,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
