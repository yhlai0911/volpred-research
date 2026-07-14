#!/usr/bin/env python3
"""P0-3: rebuild Table 3 (SAR by VIX regime) point estimates + inference on the pinned snapshot.

Motivation (fable deep review 2026-07-11 P0-3): the original Table 3 p-values came from
K716 whose script is permanently lost (K1249 confirmed rebuild blocked) and whose note
("two-sample t-test ... via bootstrap") is self-contradictory. This script recomputes the
whole table from the pinned CSV and replaces the unverifiable p-values with a paired
circular moving-block bootstrap for Delta_j = SAR(calm) - SAR(j), following the exact
inference design that Codex R2 approved for K1686 (resample complete day-rows
(|r_t|, V_t, dVIX_t) so every SAR is recomputed on the identical block draw).

Data convention: identical to experiments/k1686/k1686_contemporaneous_null.py
empirical_side() -- window 2006-01-01..2026-04-05 on the pinned CSV, log returns on
spy_adj_close, VIX level = vix_close, shock = |dVIX_t| > 2, regimes on V_t
{<15, 15-20, 20-25, 25-30, >=30}.

Determinism: seed fixed (SeedSequence 20260714), B=10,000, primary block=20 days with
10/40/63-day sensitivity. No live data fetch.

Usage:  uv run python paper/volatility-absorption/scripts/rebuild_table3_sar_inference.py
Output: paper/volatility-absorption/results/table3_sar_inference.json
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

PAPER_DIR = Path(__file__).resolve().parents[1]
PINNED_CSV = PAPER_DIR / "data" / "spy_gld_tlt_qqq_eem_vix_2005-2026.csv"
OUT = PAPER_DIR / "results" / "table3_sar_inference.json"

SAMPLE_START, SAMPLE_END = "2006-01-01", "2026-04-05"
SHOCK_ABS = 2.0
REGIME_EDGES = [15.0, 20.0, 25.0, 30.0]
REGIMES = ["calm", "normal", "elevated", "high", "crisis"]
MIN_CELL = 5          # same validity rule as K897/K1686: need >5 shock and >5 normal days
B = 10_000
BLOCKS = [10, 20, 40, 63]
PRIMARY_BLOCK = 20
MIN_VALID_REPS = 1_000
SEED = 20260714


def regime_index(V: np.ndarray) -> np.ndarray:
    idx = np.digitize(V, REGIME_EDGES)  # 0..4
    return idx


def sar_by_regime(a: np.ndarray, V: np.ndarray, shock: np.ndarray):
    """Return (sar[5], n_shock[5], n_normal[5], mean_shock[5], mean_normal[5])."""
    idx = regime_index(V)
    sar = np.full(5, np.nan)
    n_s = np.zeros(5, dtype=int)
    n_n = np.zeros(5, dtype=int)
    m_s = np.full(5, np.nan)
    m_n = np.full(5, np.nan)
    for j in range(5):
        in_j = idx == j
        s_mask = in_j & shock
        n_mask = in_j & ~shock
        n_s[j], n_n[j] = int(s_mask.sum()), int(n_mask.sum())
        if n_s[j] > MIN_CELL and n_n[j] > MIN_CELL:
            m_s[j] = a[s_mask].mean()
            m_n[j] = a[n_mask].mean()
            sar[j] = m_s[j] / m_n[j]
    return sar, n_s, n_n, m_s, m_n


def circular_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]) % n
    return idx.ravel()[:n]


def main() -> None:
    df = pd.read_csv(PINNED_CSV, parse_dates=["date"])
    df = df[(df.date >= SAMPLE_START) & (df.date <= SAMPLE_END)].copy()
    df["ret"] = np.log(df["spy_adj_close"] / df["spy_adj_close"].shift(1)) * 100
    df = df.dropna(subset=["ret", "vix_close"])
    df["dvix"] = df["vix_close"].diff()
    df = df.dropna(subset=["dvix"]).reset_index(drop=True)

    a = df["ret"].abs().values
    V = df["vix_close"].values
    dV = df["dvix"].values
    n = len(a)
    shock = np.abs(dV) > SHOCK_ABS

    sar, n_s, n_n, m_s, m_n = sar_by_regime(a, V, shock)
    point_decline = {REGIMES[j]: float(sar[0] - sar[j]) for j in range(1, 5)}

    # Paired circular moving-block bootstrap: resample complete day-rows so that
    # SAR(calm) and SAR(j) in each replication come from the same draw.
    boot = {}
    for block in BLOCKS:
        rng = np.random.default_rng(np.random.SeedSequence([SEED, block]))
        decl = {r: [] for r in REGIMES[1:]}
        sar_b = {r: [] for r in REGIMES}
        for _ in range(B):
            take = circular_block_indices(n, block, rng)
            sb, *_ = sar_by_regime(a[take], V[take], shock[take])
            for j, r in enumerate(REGIMES):
                if np.isfinite(sb[j]):
                    sar_b[r].append(float(sb[j]))
            if np.isfinite(sb[0]):
                for j in range(1, 5):
                    if np.isfinite(sb[j]):
                        decl[REGIMES[j]].append(float(sb[0] - sb[j]))
        entry = {}
        for j in range(1, 5):
            r = REGIMES[j]
            d = np.asarray(decl[r])
            n_valid = len(d)
            if n_valid < MIN_VALID_REPS:
                entry[r] = {"status": "NOT_EVALUABLE", "n_valid": n_valid}
                continue
            lo, hi = np.percentile(d, [2.5, 97.5])
            # two-sided percentile p for H0: Delta_j = 0, with (b+1)/(n+1) plug-in floor
            p_le = (np.sum(d <= 0.0) + 1) / (n_valid + 1)
            p_ge = (np.sum(d >= 0.0) + 1) / (n_valid + 1)
            entry[r] = {
                "point_estimate": point_decline[r],
                "bootstrap_mean": float(d.mean()),
                "ci95": [float(lo), float(hi)],
                "ci_excludes_zero": bool(lo > 0.0 or hi < 0.0),
                "p_two_sided": float(min(1.0, 2.0 * min(p_le, p_ge))),
                "n_valid": n_valid,
            }
        boot[str(block)] = entry

    payload = {
        "experiment": "table3_sar_inference_rebuild",
        "paper": "volatility-absorption",
        "purpose": "P0-3: replace unverifiable K716 Table 3 p-values with pinned-snapshot paired block-bootstrap inference",
        "data": {
            "pinned_csv": str(PINNED_CSV.relative_to(PAPER_DIR.parents[1])),
            "sample_start": str(df.date.iloc[0].date()),
            "sample_end": str(df.date.iloc[-1].date()),
            "n_days": n,
            "n_shock_days": int(shock.sum()),
            "shock_rule": f"|dVIX_t| > {SHOCK_ABS}",
            "return": "log(spy_adj_close_t / spy_adj_close_{t-1}) * 100",
            "vix": "vix_close",
        },
        "inference": {
            "design": "paired circular moving-block bootstrap on complete day-rows (|r_t|, V_t, dVIX_t)",
            "B": B,
            "primary_block": PRIMARY_BLOCK,
            "block_sensitivity": BLOCKS,
            "seed": SEED,
            "validity_rule": f"regime cell needs > {MIN_CELL} shock and > {MIN_CELL} normal days; replication needs calm and target regime both valid",
            "p_value": "two-sided percentile with (b+1)/(n+1) plug-in floor",
        },
        "table3": {
            REGIMES[j]: {
                "n_shock": int(n_s[j]),
                "n_normal": int(n_n[j]),
                "mean_abs_ret_shock": float(m_s[j]),
                "mean_abs_ret_normal": float(m_n[j]),
                "sar": float(sar[j]),
                "delta_sar_vs_calm": None if j == 0 else float(sar[j] - sar[0]),
            }
            for j in range(5)
        },
        "decline_inference_primary": boot[str(PRIMARY_BLOCK)],
        "decline_inference_by_block": boot,
    }

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    json.loads(text)
    OUT.parent.mkdir(exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(OUT.parent))
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, OUT)

    print(f"n={n} shocks={int(shock.sum())}")
    for j, r in enumerate(REGIMES):
        print(f"{r:>9}: n_s={n_s[j]:>3} n_n={n_n[j]:>4} m_s={m_s[j]:.3f} m_n={m_n[j]:.3f} SAR={sar[j]:.4f}")
    for r, e in boot[str(PRIMARY_BLOCK)].items():
        if "ci95" in e:
            print(f"decline calm-{r}: {e['point_estimate']:+.4f} CI[{e['ci95'][0]:+.4f},{e['ci95'][1]:+.4f}] p={e['p_two_sided']:.4g} n_valid={e['n_valid']}")
        else:
            print(f"decline calm-{r}: NOT_EVALUABLE n_valid={e['n_valid']}")
    print(f"[write] {OUT}")


if __name__ == "__main__":
    main()
