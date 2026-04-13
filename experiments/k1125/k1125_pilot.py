"""
K1125 Pilot — Lee-Mykland jump detection sanity check
Validate BV calculation, critical value, jump incidence rate before full run.
"""
import numpy as np
import pandas as pd
from pathlib import Path

# Load cached bars
ROOT = Path(__file__).parent
df = pd.read_parquet(ROOT / '_cache_bars_2017-01-01_2021-12-31.parquet')
print(f"Loaded {len(df)} bars, {df['date'].nunique()} days")

# ---- Lee-Mykland (2008) Jump Test ----
# L_t = |r_t| / sigma_hat_t  where sigma_hat = sqrt(BV) over rolling window
# BV = (1 / (K-2)) * sum_{i} |r_{i-1}| * |r_i|  for i in [t-K+2, t-1]
# Adjustment: BV estimator of IV has factor mu_1^{-2} = (pi/2) for asymptotic consistency

MU1 = np.sqrt(2.0 / np.pi)  # E|Z| for Z~N(0,1)
K = 16  # window size per Lee-Mykland recommendation (n^{1/2} scaling for 5-min bars)

def compute_bv_rolling(r: np.ndarray, K: int) -> np.ndarray:
    """
    Rolling bipower variation over window K (strictly past).
    sigma_hat_t uses returns from [t-K+1, t-1] (K-1 pairs from K returns prior to t).
    Returns sigma_hat at each t; NaN for t < K.

    Standard Lee-Mykland: use past K returns excluding r_t itself.
    BV_t = (1/(K-1)) * (pi/2) * sum_{j=t-K+1}^{t-1} |r_{j-1}| * |r_j|
    """
    n = len(r)
    sigma_hat = np.full(n, np.nan)
    abs_r = np.abs(r)
    # |r_{j-1}| * |r_j| pairs
    pairs = abs_r[:-1] * abs_r[1:]  # length n-1
    # sigma_hat[t] uses pairs at index [t-K+1, t-2] (K-1 pairs, strictly past)
    # index j-pair corresponds to pair_{j-1}*pair_j stored at position j-1
    # We want sum from pair at pos (t-K+1) to pair at pos (t-2), inclusive -> K-2 pairs
    # Alternative standard form: K window giving K-2 products then factor adjustment
    # Using Lee-Mykland 2008 eq (A.3): BV = 1/(K-2) sum_{j=i-K+2}^{i-1} |r_{j-1}||r_j|
    # sigma_hat_t uses r_{t-K+1},...,r_{t-1} (K-1 returns, K-2 products strictly past)
    for t in range(K, n):
        # sum pairs at positions [t-K+1, t-2]  (K-2 products)
        # pair at pos p = |r_p|*|r_{p+1}|
        # We want pairs of form |r_{j-1}||r_j| for j in [t-K+2, t-1]
        # This is pair positions [t-K+1, t-2]
        sum_pairs = pairs[t-K+1:t-1].sum()
        bv = sum_pairs / ((K-2) * MU1**2)
        sigma_hat[t] = np.sqrt(max(bv, 1e-16))
    return sigma_hat

# Pilot: use first 3 months of 2017
pilot = df[df['date'] <= pd.Timestamp('2017-03-31')].copy().reset_index(drop=True)
print(f"\nPilot sample: {len(pilot)} bars, {pilot['date'].nunique()} days")

# Compute sigma_hat per bar (continuous series, ignoring day boundaries for pilot)
r = pilot['log_ret'].values
sigma_hat = compute_bv_rolling(r, K=K)

# Lee-Mykland statistic
L = np.abs(r) / sigma_hat  # NaN where sigma_hat is NaN

# Critical value at alpha=0.01
# Lee-Mykland Thm 1: (max_i L_i - C_n) / S_n ~ Gumbel (bilateral)
# For per-bar single test at level alpha: reject if L_t > beta_star * log(n/alpha) style
# Simplified asymptotic: L_t > sqrt(2 log n) gives ~5% Type I under normal null
# For α=0.01 with bar-by-bar test, use threshold = sqrt(2 log(1/α)) ≈ 3.03

# More rigorous (Lee-Mykland 2008 eq 18): multi-test adjusted threshold
# For n bars, threshold s.t. P(max L > threshold) = alpha:
# Gumbel critical: threshold = C_n + S_n * beta_n
# where C_n = (2 log n)^{1/2} - 0.5*(log log n + log 4*pi) / (2 log n)^{1/2}
# and S_n = 1 / (2 log n)^{1/2}
# and beta_n = -log(-log(1-alpha))

# Simple single-test threshold (used as primary; multi-test for diagnostic)
thresh_single = np.sqrt(2 * np.log(1.0 / 0.01))  # ~3.035
print(f"\nSingle-test threshold (α=0.01): {thresh_single:.3f}")

# Multi-test threshold
n_valid = np.isfinite(L).sum()
alpha = 0.01
C_n = np.sqrt(2*np.log(n_valid)) - 0.5*(np.log(np.log(n_valid)) + np.log(4*np.pi)) / np.sqrt(2*np.log(n_valid))
S_n = 1.0 / np.sqrt(2*np.log(n_valid))
beta_n = -np.log(-np.log(1-alpha))
thresh_multi = C_n + S_n * beta_n
print(f"Multi-test threshold (α=0.01, n={n_valid}): {thresh_multi:.3f}")

# Jump incidence
L_finite = L[np.isfinite(L)]
jumps_single = (L_finite > thresh_single).sum()
jumps_multi = (L_finite > thresh_multi).sum()
print(f"\nL distribution:")
print(f"  mean={L_finite.mean():.3f}, median={np.median(L_finite):.3f}")
print(f"  p95={np.percentile(L_finite, 95):.3f}, p99={np.percentile(L_finite, 99):.3f}")
print(f"  max={L_finite.max():.3f}")
print(f"Jumps at single-test (|L|>{thresh_single:.2f}): {jumps_single} ({jumps_single/n_valid*100:.2f}%)")
print(f"Jumps at multi-test  (|L|>{thresh_multi:.2f}): {jumps_multi} ({jumps_multi/n_valid*100:.3f}%)")

# Quick OFI vs jump cross-tab
ofi_abs = np.abs(pilot['ofi'].values)
jump_single_mask = (L > thresh_single) & np.isfinite(L)
jump_multi_mask = (L > thresh_multi) & np.isfinite(L)
print(f"\n|OFI| stats by jump status (single-test):")
print(f"  Jump bars (N={jump_single_mask.sum()}): |OFI|={ofi_abs[jump_single_mask].mean():.4f}")
print(f"  No-jump   (N={(~jump_single_mask & np.isfinite(L)).sum()}): |OFI|={ofi_abs[~jump_single_mask & np.isfinite(L)].mean():.4f}")

print(f"\n|OFI| stats by jump status (multi-test):")
if jump_multi_mask.sum() > 0:
    print(f"  Jump bars (N={jump_multi_mask.sum()}): |OFI|={ofi_abs[jump_multi_mask].mean():.4f}")
    print(f"  No-jump   (N={(~jump_multi_mask & np.isfinite(L)).sum()}): |OFI|={ofi_abs[~jump_multi_mask & np.isfinite(L)].mean():.4f}")
else:
    print("  No jumps detected at multi-test level")

print("\nPilot complete.")
