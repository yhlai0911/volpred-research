"""
Paper 2 R1 SEVERE 2 — Linear scaling assumption check for the
VIXTWN-to-VIX ratio of 1.39 used in K = 12/1.39 = 8.63.

Question (Gemini R1, paper/taiwan-vt/gemini_review_v1.md line 12):
    "1.39 amplification assumed static/linear — breaks in tail events"

Test design:
  1. Load paired VIXTWN (TAIFEX official, K1098 snapshot, 2007-2022) and
     VIX (paper canonical snapshot) on dates where both are observed.
  2. Compute daily ratio_t = VIXTWN_t / VIX_t.
  3. Partition days into volatility regimes using EXPANDING-WINDOW
     quantile thresholds on VIX_t (strict t-1 information set; no
     full-sample percentile leakage). Buckets:
        Q1  : VIX_t <= expanding 25th pct (low US vol)
        Q2  : 25th-50th
        Q3  : 50th-75th
        Q4  : > 75th (high US vol)
        Tail: |VIX log-change_t| > 2 * expanding std (US-vol shock days)
     The Tail bucket is the specific stress condition the reviewer
     asks about; it overlaps with Q3/Q4 by construction.
  4. Compute mean ratio per bucket; compare each bucket mean to the
     paper-canonical 1.39 (and to the overall mean for context).
  5. Stationary block bootstrap on the *daily ratio series* with
     mean block length L=21 (one trading month) and B=500 replications,
     seed=42 globally. Returns 95% CI on the overall ratio mean and on
     each bucket mean. Verdict:
        linearity_HOLDS  if all bucket means within +/- 10% of 1.39
                         AND each bucket 95% CI contains 1.39
        linearity_BREAKS otherwise
  6. Additional tail-stress check: Kolmogorov-Smirnov 2-sample test
     comparing (Tail) bucket ratio distribution vs (non-Tail) ratios.

Strict lookahead policy:
  * Quantile threshold at day t uses observations strictly before t
    (we exclude day t from its own threshold computation).
  * Expanding mean/std for tail filter also strictly excludes day t.
  * First 252 obs are dropped (warm-up; thresholds undefined).

Outputs:
  results.json  -- structured numbers and verdict

Author: VolPred Research System (Yi-Hao Lai)
Date  : 2026-05-12
Seed  : 42
"""
from __future__ import annotations

import json
import os
import sys
import math
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path("/Users/yhlai0911/Desktop/volpred-research")
PAPER_CANONICAL_RATIO = 1.39
PAPER_CANONICAL_RATIO_PRECISE = 1.393  # body.tex line 120
SEED = 42
BOOTSTRAP_B = 500
BLOCK_MEAN_LEN = 21  # trading days, ~1 month
WARMUP_OBS = 252  # need at least 1 year before first quantile computation
TOLERANCE_PCT = 0.10  # +/- 10% of 1.39 for HOLDS verdict
RNG = np.random.default_rng(SEED)


def load_paired_series():
    """Load VIXTWN (K1098 official TAIFEX, 2007-2022) and VIX (paper snapshot).

    Returns DataFrame with columns: date (DatetimeIndex), VIXTWN, VIX, ratio.
    """
    # VIXTWN — K1098 canonical TAIFEX-derived daily series
    vixtwn_path = REPO / "experiments/k1098/k1098_vixtwn_daily.csv"
    vixtwn = pd.read_csv(vixtwn_path, parse_dates=["date"])
    vixtwn = vixtwn.rename(columns={"VIXTWN": "vixtwn"})
    vixtwn = vixtwn.drop_duplicates("date").set_index("date").sort_index()

    # VIX — paper canonical snapshot
    paper_csv = (
        REPO
        / "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
    )
    vix = pd.read_csv(paper_csv, parse_dates=["date"], usecols=["date", "vix_close"])
    vix = vix.rename(columns={"vix_close": "vix"}).drop_duplicates("date")
    vix = vix.set_index("date").sort_index()
    vix = vix.dropna()

    # Inner join — strict t==t pairing (both indices unique-aligned at calendar date).
    # Note: this pairs VIXTWN_t with VIX_t observed on the same calendar date.
    # The paper uses lagged-VIX-for-TW elsewhere; here we measure
    # *level* relationship (a contemporaneous ratio), so this is correct.
    df = vixtwn.join(vix, how="inner").dropna()
    df["ratio"] = df["vixtwn"] / df["vix"]
    return df


def expanding_quantile_threshold(x: np.ndarray, q: float) -> np.ndarray:
    """For each t, compute the q-th quantile over x[:t] (strictly before t).
    Returns NaN until enough data accumulates (WARMUP_OBS).
    """
    n = len(x)
    out = np.full(n, np.nan)
    for t in range(WARMUP_OBS, n):
        out[t] = np.quantile(x[:t], q)
    return out


def expanding_mean_std(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each t, compute mean & std over x[:t] (strictly before t)."""
    n = len(x)
    mean = np.full(n, np.nan)
    std = np.full(n, np.nan)
    csum = np.cumsum(x)
    csum2 = np.cumsum(x * x)
    for t in range(WARMUP_OBS, n):
        m = csum[t - 1] / t
        v = csum2[t - 1] / t - m * m
        mean[t] = m
        std[t] = math.sqrt(max(v, 0.0))
    return mean, std


def assign_buckets(df: pd.DataFrame) -> pd.DataFrame:
    """Add bucket flags using expanding-window thresholds (no lookahead)."""
    vix = df["vix"].to_numpy()
    q25 = expanding_quantile_threshold(vix, 0.25)
    q50 = expanding_quantile_threshold(vix, 0.50)
    q75 = expanding_quantile_threshold(vix, 0.75)
    df = df.copy()
    df["q25"] = q25
    df["q50"] = q50
    df["q75"] = q75

    # Quantile bucket assignment (strictly using expanding thresholds)
    def _bucket(row):
        v, a, b, c = row["vix"], row["q25"], row["q50"], row["q75"]
        if not np.isfinite(a):
            return "warmup"
        if v <= a:
            return "Q1"
        if v <= b:
            return "Q2"
        if v <= c:
            return "Q3"
        return "Q4"

    df["bucket"] = df.apply(_bucket, axis=1)

    # Tail flag: log-VIX shock |Δlog(VIX_t)| > 2 * expanding_std(Δlog(VIX))
    log_vix = np.log(vix)
    dlog = np.concatenate([[np.nan], np.diff(log_vix)])
    df["dlog_vix"] = dlog
    mu, sd = expanding_mean_std(np.where(np.isnan(dlog), 0.0, dlog))
    # Note: mu/sd used here are conservative; we want strictly-prior std.
    # Using the cumulative arrays gives mean/std over x[:t] which excludes t.
    df["dlog_mean"] = mu
    df["dlog_std"] = sd
    z = (df["dlog_vix"] - df["dlog_mean"]) / df["dlog_std"]
    df["tail_z"] = z
    df["is_tail"] = (df["tail_z"].abs() > 2.0) & df["dlog_std"].notna()
    return df


def stationary_block_bootstrap_mean(
    x: np.ndarray, mask: np.ndarray, B: int, mean_block: int, rng: np.random.Generator
) -> np.ndarray:
    """Stationary block bootstrap (Politis-Romano 1994) of the mean of x[mask].

    We resample blocks from the *full* series x with the same mask logic preserved
    by tracking which sampled indices fall inside `mask`. This preserves serial
    dependence near the bucket-condition boundary. If a sampled segment yields
    no in-bucket observations, that replication uses the global ratio mean as a
    safety fallback (rare for our buckets with >100 obs).

    Returns array of B bootstrap mean estimates.
    """
    n = len(x)
    p = 1.0 / mean_block  # geometric prob: block length ~ Geom(p), mean = 1/p
    means = np.empty(B)
    for b in range(B):
        # Build a resample of size n by concatenating random-length geometric blocks
        idx = []
        cur = 0
        while cur < n:
            start = rng.integers(0, n)
            L = rng.geometric(p)
            seg = [(start + k) % n for k in range(L)]
            idx.extend(seg)
            cur += L
        idx = np.array(idx[:n], dtype=int)
        sample_mask = mask[idx]
        sample_x = x[idx]
        if sample_mask.sum() == 0:
            means[b] = np.nan
        else:
            means[b] = sample_x[sample_mask].mean()
    return means


def ci_from_samples(samples: np.ndarray, alpha: float = 0.05) -> tuple[float, float]:
    s = samples[np.isfinite(samples)]
    if len(s) == 0:
        return float("nan"), float("nan")
    return float(np.quantile(s, alpha / 2)), float(np.quantile(s, 1 - alpha / 2))


def ks_two_sample(a: np.ndarray, b: np.ndarray) -> dict:
    """Manual KS 2-sample test (avoids extra scipy dep beyond stdlib)."""
    a = np.sort(a[np.isfinite(a)])
    b = np.sort(b[np.isfinite(b)])
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return {"D": float("nan"), "p_approx": float("nan"), "n_a": n, "n_b": m}
    all_v = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, all_v, side="right") / n
    cdf_b = np.searchsorted(b, all_v, side="right") / m
    D = float(np.max(np.abs(cdf_a - cdf_b)))
    # Smirnov asymptotic p-value
    en = math.sqrt(n * m / (n + m))
    # Smirnov-Kolmogorov series approximation
    lam = (en + 0.12 + 0.11 / en) * D
    p = 2.0 * sum((-1) ** (k - 1) * math.exp(-2.0 * lam * lam * k * k) for k in range(1, 101))
    p = max(0.0, min(1.0, p))
    return {"D": D, "p_approx": p, "n_a": n, "n_b": m}


def main():
    print("=" * 72)
    print("Paper 2 R1 SEVERE 2 — VIXTWN/VIX linear scaling check")
    print("=" * 72)

    df = load_paired_series()
    print(f"Paired observations (VIXTWN INNER VIX): n={len(df)}")
    print(f"  Date range: {df.index[0].date()} -> {df.index[-1].date()}")
    print(f"  Overall ratio mean   : {df['ratio'].mean():.4f}")
    print(f"  Overall ratio median : {df['ratio'].median():.4f}")
    print(f"  Overall ratio std    : {df['ratio'].std():.4f}")
    print(f"  Paper canonical      : {PAPER_CANONICAL_RATIO}")

    df = assign_buckets(df)
    df_eval = df[df["bucket"] != "warmup"].copy()
    print(f"After {WARMUP_OBS}-day warmup: n_eval={len(df_eval)}")

    # ----- Per-bucket means -----
    buckets = ["Q1", "Q2", "Q3", "Q4", "Tail"]
    bucket_results = {}
    overall_mean = float(df_eval["ratio"].mean())

    for b in buckets:
        if b == "Tail":
            mask = df_eval["is_tail"].to_numpy()
            criterion = "|Δlog(VIX_t)| > 2 * expanding_std (US-vol shock days)"
        else:
            mask = (df_eval["bucket"] == b).to_numpy()
            criterion = f"VIX_t in expanding-window {b} of [Q1<=25th, Q2<=50th, Q3<=75th, Q4>75th]"
        n_b = int(mask.sum())
        if n_b == 0:
            bucket_results[b] = {"n": 0, "criterion": criterion, "mean_ratio": None}
            continue
        ratios_b = df_eval.loc[mask, "ratio"].to_numpy()
        mean_b = float(ratios_b.mean())
        median_b = float(np.median(ratios_b))
        std_b = float(ratios_b.std(ddof=1)) if len(ratios_b) > 1 else float("nan")
        bucket_results[b] = {
            "criterion": criterion,
            "n": n_b,
            "mean_ratio": mean_b,
            "median_ratio": median_b,
            "std_ratio": std_b,
            "vix_mean": float(df_eval.loc[mask, "vix"].mean()),
            "vixtwn_mean": float(df_eval.loc[mask, "vixtwn"].mean()),
            "deviation_from_1_39_pct": (mean_b / PAPER_CANONICAL_RATIO - 1.0) * 100,
        }
        print(
            f"  {b:5s}: n={n_b:4d}  mean_ratio={mean_b:.4f}  "
            f"median={median_b:.4f}  std={std_b:.4f}  "
            f"VIX_mean={df_eval.loc[mask, 'vix'].mean():.2f}  "
            f"dev_from_1.39={bucket_results[b]['deviation_from_1_39_pct']:+.2f}%"
        )

    # ----- Stationary block bootstrap on the overall ratio and each bucket mean -----
    print("\nStationary block bootstrap (B=500, mean_block=21, seed=42)...")
    x = df_eval["ratio"].to_numpy()

    bs_overall = stationary_block_bootstrap_mean(
        x, np.ones(len(x), dtype=bool), BOOTSTRAP_B, BLOCK_MEAN_LEN, RNG
    )
    overall_ci = ci_from_samples(bs_overall)
    bs_overall_mean = float(np.nanmean(bs_overall))
    bs_overall_se = float(np.nanstd(bs_overall, ddof=1))
    print(
        f"  Overall: bs_mean={bs_overall_mean:.4f}  bs_se={bs_overall_se:.4f}  "
        f"95% CI=[{overall_ci[0]:.4f}, {overall_ci[1]:.4f}]"
    )
    overall_contains_1_39 = overall_ci[0] <= PAPER_CANONICAL_RATIO <= overall_ci[1]

    bucket_cis = {}
    for b in buckets:
        if b == "Tail":
            mask = df_eval["is_tail"].to_numpy()
        else:
            mask = (df_eval["bucket"] == b).to_numpy()
        if mask.sum() == 0:
            bucket_cis[b] = {"ci_low": None, "ci_high": None, "contains_1_39": None}
            continue
        bs = stationary_block_bootstrap_mean(
            x, mask, BOOTSTRAP_B, BLOCK_MEAN_LEN, RNG
        )
        lo, hi = ci_from_samples(bs)
        contains = lo <= PAPER_CANONICAL_RATIO <= hi
        bucket_cis[b] = {
            "bs_mean": float(np.nanmean(bs)),
            "bs_se": float(np.nanstd(bs, ddof=1)),
            "ci_low": lo,
            "ci_high": hi,
            "contains_1_39": bool(contains),
        }
        print(
            f"  {b:5s}: bs_mean={bucket_cis[b]['bs_mean']:.4f}  "
            f"95% CI=[{lo:.4f}, {hi:.4f}]  "
            f"contains 1.39? {contains}"
        )

    # ----- KS 2-sample: Tail vs non-Tail -----
    tail_mask = df_eval["is_tail"].to_numpy()
    ks = ks_two_sample(
        df_eval.loc[tail_mask, "ratio"].to_numpy(),
        df_eval.loc[~tail_mask, "ratio"].to_numpy(),
    )
    print(
        f"\nKS 2-sample (Tail vs non-Tail ratio dist): "
        f"D={ks['D']:.4f}, p≈{ks['p_approx']:.4f}, "
        f"n_tail={ks['n_a']}, n_nontail={ks['n_b']}"
    )

    # ----- Verdict -----
    all_within_tol = True
    all_cis_contain = True
    for b in buckets:
        br = bucket_results[b]
        if br.get("mean_ratio") is None:
            continue
        if abs(br["deviation_from_1_39_pct"]) > TOLERANCE_PCT * 100:
            all_within_tol = False
        if bucket_cis[b].get("contains_1_39") is False:
            all_cis_contain = False

    if all_within_tol and all_cis_contain and overall_contains_1_39:
        verdict = "linearity_HOLDS"
        rationale = (
            f"All buckets within +/-{TOLERANCE_PCT*100:.0f}% of 1.39 and "
            f"each 95% bootstrap CI contains 1.39. The static-ratio assumption is "
            f"empirically defensible; recommend keeping the canonical 8.63/VIX "
            f"calibration and adding a footnote pointing to this robustness check."
        )
    else:
        verdict = "linearity_BREAKS"
        rationale = (
            "At least one volatility-regime bucket exceeds the +/-10% tolerance "
            "around 1.39, OR its 95% bootstrap CI does not cover 1.39. The static "
            "ratio understates regime dependence; recommend replacing the single "
            "1.39 figure in the main narrative with a regime-conditional table and "
            "noting that K = 8.63 represents the long-run mean while VT exposure in "
            "tail-vol periods is under- or over-stated."
        )

    print(f"\nVERDICT: {verdict}")
    print(f"  {rationale}")

    # ----- Assemble results.json -----
    out = {
        "experiment_id": "paper2_R1_linear_scaling_fix",
        "title": "Paper 2 R1 SEVERE 2 — VIXTWN/VIX 1.39 linearity / regime conditioning",
        "purpose": (
            "Address Gemini R1 SEVERE 2: '1.39 amplification assumed static/linear "
            "— breaks in tail events'. The VIXTWN-to-VIX ratio of 1.39 is the basis "
            "for K = 12/1.39 = 8.63 in the 8.63/VIX strategy and is also invoked "
            "qualitatively elsewhere in the paper. This experiment tests whether "
            "the ratio is regime-stable by partitioning days into expanding-window "
            "VIX quantile buckets and a tail-shock bucket, then applies stationary "
            "block bootstrap (B=500, seed=42) to obtain regime-conditional 95% CIs."
        ),
        "data_sources": {
            "vixtwn": {
                "path": str(
                    (REPO / "experiments/k1098/k1098_vixtwn_daily.csv").relative_to(REPO)
                ),
                "n_raw": int(len(pd.read_csv(REPO / "experiments/k1098/k1098_vixtwn_daily.csv"))),
                "source": "TAIFEX official Dropbox (K1098 canonical parse)",
            },
            "vix": {
                "path": str(
                    (
                        REPO
                        / "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
                    ).relative_to(REPO)
                ),
                "column": "vix_close",
                "source": "paper canonical snapshot (yfinance ^VIX)",
            },
        },
        "configuration": {
            "seed": SEED,
            "bootstrap_B": BOOTSTRAP_B,
            "block_mean_length_days": BLOCK_MEAN_LEN,
            "warmup_obs": WARMUP_OBS,
            "tolerance_pct_of_1_39": TOLERANCE_PCT,
            "lookahead_guard": (
                "Expanding-window quantile and mean/std thresholds use x[:t] strictly "
                "(day t excluded from its own threshold). First 252 obs dropped."
            ),
            "buckets": {
                "Q1": "VIX_t <= expanding 25th pct",
                "Q2": "25th < VIX_t <= 50th",
                "Q3": "50th < VIX_t <= 75th",
                "Q4": "VIX_t > 75th",
                "Tail": "|Δlog(VIX_t)| > 2 * expanding std (overlaps with Q3/Q4)",
            },
        },
        "paired_data_summary": {
            "n_paired": int(len(df)),
            "n_eval_after_warmup": int(len(df_eval)),
            "date_start": str(df.index[0].date()),
            "date_end": str(df.index[-1].date()),
            "overall_ratio_mean": overall_mean,
            "overall_ratio_median": float(df_eval["ratio"].median()),
            "overall_ratio_std": float(df_eval["ratio"].std(ddof=1)),
            "vixtwn_mean": float(df_eval["vixtwn"].mean()),
            "vix_mean": float(df_eval["vix"].mean()),
        },
        "paper_canonical_ratio": PAPER_CANONICAL_RATIO,
        "paper_canonical_ratio_precise": PAPER_CANONICAL_RATIO_PRECISE,
        "amplification_per_quantile": bucket_results,
        "bootstrap_ci": {
            "overall": {
                "mean": bs_overall_mean,
                "se": bs_overall_se,
                "ci_low": overall_ci[0],
                "ci_high": overall_ci[1],
                "contains_1_39": bool(overall_contains_1_39),
            },
            "per_bucket": bucket_cis,
        },
        "ks_test_tail_vs_nontail": ks,
        "verdict": verdict,
        "rationale": rationale,
        "body_addition_target": "paper/taiwan-vt/body.tex (proposed §4 or end of §3 robustness)",
        "timestamp_utc": pd.Timestamp.utcnow().isoformat(),
    }

    out_path = REPO / "experiments/paper2_R1_linear_scaling_fix/results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"\nWrote: {out_path}")
    print("Done.")


if __name__ == "__main__":
    main()
