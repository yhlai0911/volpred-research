#!/usr/bin/env python3
"""
K356: Causal DAG Discovery for Cross-Asset Volatility — What Causes What?
=========================================================================
跳躍式探索：用 Granger 因果檢定建構跨資產波動率因果有向無環圖 (DAG)

Prior knowledge:
  - K304: VIX causes RV (Toda-Yamamoto p<0.0001)
  - K338: EM vol Granger-causes SPY vol but VIX absorbs
  - K342: SPY vol → oil vol (not reverse)
  - K345: VIX → FX vol (unidirectional)
  - ZERO mentions of DAG/SEM/causal discovery

Data: yfinance daily — SPY, GLD, TLT, EEM, CL=F (oil), EURUSD=X, ^VIX
      22-day rolling realized volatility for each asset
      Period: 2005-2025 (~20 years)

Methodology (practical DAG without specialized packages):
  1. Pairwise Granger causality matrix (6×6 assets)
  2. Build directed graph from significant unidirectional arrows
  3. Identify hub nodes (vol exporters) vs leaf nodes (vol importers)
  4. Regime-dependent DAG: low vs high VIX
  5. Partial DAG: after controlling for VIX, which arrows remain?

[提出: 用戶 (跳躍式探索), 執行: Claude]
Author: VolPred Research System
Date: 2026-03-25
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
import itertools
warnings.filterwarnings('ignore')

print("=" * 80)
print("K356: Causal DAG Discovery for Cross-Asset Volatility")
print("=" * 80)

# ──────────────────────────────────────────────────────────
# 0. DATA COLLECTION
# ──────────────────────────────────────────────────────────

tickers = {
    'SPY': 'SPY',
    'GLD': 'GLD',
    'TLT': 'TLT',
    'EEM': 'EEM',
    'OIL': 'CL=F',
    'EURUSD': 'EURUSD=X',
}

vix_ticker = '^VIX'

print("\n[0] Downloading data from yfinance (2005-2025)...")
raw_close = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, start='2005-01-01', end='2026-01-01',
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) > 500:
            raw_close[name] = df['Close']
            print(f"  {name} ({ticker}): {len(df)} days, "
                  f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
        else:
            print(f"  {name}: insufficient data ({len(df)} rows), skipping")
    except Exception as e:
        print(f"  {name}: download error: {e}")

# Download VIX
vix_df = yf.download(vix_ticker, start='2005-01-01', end='2026-01-01',
                      progress=False, auto_adjust=True)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
print(f"  VIX: {len(vix_df)} days")

# Align all series
price_df = pd.DataFrame(raw_close)
price_df['VIX'] = vix_df['Close'].reindex(price_df.index)
price_df = price_df.dropna()
print(f"\nAligned dataset: {len(price_df)} days, {price_df.index[0].date()} to {price_df.index[-1].date()}")

# ──────────────────────────────────────────────────────────
# 1. COMPUTE REALIZED VOLATILITY (22-day rolling)
# ──────────────────────────────────────────────────────────

print("\n[1] Computing 22-day rolling realized volatility...")
assets = [a for a in tickers.keys() if a in price_df.columns]
log_ret = np.log(price_df[assets] / price_df[assets].shift(1))
rv_22 = log_ret.rolling(22).std() * np.sqrt(252) * 100  # annualized %
rv_22 = rv_22.dropna()

# Also compute changes (first differences) for stationarity
d_rv = rv_22.diff().dropna()

# VIX level aligned
vix_level = price_df['VIX'].reindex(d_rv.index)

print(f"RV series: {len(rv_22)} observations")
print(f"Delta-RV series (stationary): {len(d_rv)} observations")
print(f"\nRV summary statistics (annualized %):")
print(rv_22.describe().round(2).to_string())

# ──────────────────────────────────────────────────────────
# 2. PAIRWISE GRANGER CAUSALITY MATRIX
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("[2] Pairwise Granger Causality Tests")
print("=" * 80)

def granger_causality_test(x, y, max_lag=5):
    """
    Test if x Granger-causes y.
    Uses OLS F-test: compare restricted model (y lags only)
    vs unrestricted model (y lags + x lags).
    Returns best lag, F-stat, p-value.
    """
    n = len(x)
    best_p = 1.0
    best_lag = 1
    best_f = 0.0

    for lag in range(1, max_lag + 1):
        if n <= 2 * lag + 2:
            continue

        # Build matrices
        Y = y[lag:]  # dependent variable

        # Restricted model: only y lags
        X_r = np.column_stack([y[lag-i-1:n-i-1] for i in range(lag)])
        X_r = np.column_stack([np.ones(len(Y)), X_r])

        # Unrestricted model: y lags + x lags
        X_u = np.column_stack([
            np.ones(len(Y)),
            *[y[lag-i-1:n-i-1] for i in range(lag)],
            *[x[lag-i-1:n-i-1] for i in range(lag)]
        ])

        # Trim to same length
        min_len = min(len(Y), X_r.shape[0], X_u.shape[0])
        Y = Y[:min_len]
        X_r = X_r[:min_len]
        X_u = X_u[:min_len]

        try:
            # OLS for restricted
            beta_r = np.linalg.lstsq(X_r, Y, rcond=None)[0]
            resid_r = Y - X_r @ beta_r
            ssr_r = np.sum(resid_r ** 2)

            # OLS for unrestricted
            beta_u = np.linalg.lstsq(X_u, Y, rcond=None)[0]
            resid_u = Y - X_u @ beta_u
            ssr_u = np.sum(resid_u ** 2)

            # F-test
            df_num = lag  # extra parameters
            df_den = min_len - X_u.shape[1]

            if df_den <= 0 or ssr_u <= 0:
                continue

            f_stat = ((ssr_r - ssr_u) / df_num) / (ssr_u / df_den)
            p_val = 1 - stats.f.cdf(f_stat, df_num, df_den)

            if p_val < best_p:
                best_p = p_val
                best_lag = lag
                best_f = f_stat
        except Exception:
            continue

    return best_lag, best_f, best_p


# Run pairwise tests on first-differenced RV (stationary)
print("\nUsing first-differenced RV (delta-RV) for stationarity.")
print("Significance threshold: p < 0.01\n")

n_assets = len(assets)
gc_matrix_p = np.ones((n_assets, n_assets))  # p-values
gc_matrix_f = np.zeros((n_assets, n_assets))  # F-stats
gc_matrix_lag = np.zeros((n_assets, n_assets), dtype=int)  # best lag

for i, src in enumerate(assets):
    for j, tgt in enumerate(assets):
        if i == j:
            continue
        x = d_rv[src].values
        y = d_rv[tgt].values
        lag, f_stat, p_val = granger_causality_test(x, y, max_lag=5)
        gc_matrix_p[i, j] = p_val
        gc_matrix_f[i, j] = f_stat
        gc_matrix_lag[i, j] = lag

# Display p-value matrix
print("Granger Causality p-value matrix (row causes column):")
print(f"{'':>8s}", end="")
for a in assets:
    print(f" {a:>8s}", end="")
print()
for i, src in enumerate(assets):
    print(f"{src:>8s}", end="")
    for j, tgt in enumerate(assets):
        if i == j:
            p_str = "   ---  "
        else:
            p = gc_matrix_p[i, j]
            if p < 0.001:
                p_str = f" <0.001*"
            elif p < 0.01:
                p_str = f"  {p:.3f}*"
            elif p < 0.05:
                p_str = f"  {p:.3f}†"
            else:
                p_str = f"  {p:.3f} "
        print(p_str, end="")
    print()

print("\n* p<0.01 (significant), † p<0.05 (marginal)")

# ──────────────────────────────────────────────────────────
# 3. BUILD DIRECTED GRAPH
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("[3] Directed Causal Graph Construction")
print("=" * 80)

THRESHOLD = 0.01

edges = []  # (src, tgt, direction, f_stat, p_val)
unidirectional = []
bidirectional = []

for i, src in enumerate(assets):
    for j, tgt in enumerate(assets):
        if i >= j:  # only process each pair once
            continue

        p_ab = gc_matrix_p[i, j]  # src → tgt
        p_ba = gc_matrix_p[j, i]  # tgt → src
        f_ab = gc_matrix_f[i, j]
        f_ba = gc_matrix_f[j, i]

        if p_ab < THRESHOLD and p_ba >= THRESHOLD:
            # Unidirectional: src → tgt
            edges.append((src, tgt, '→', f_ab, p_ab))
            unidirectional.append((src, tgt, f_ab, p_ab))
            print(f"  {src} → {tgt}  (F={f_ab:.2f}, p={p_ab:.4f}, lag={gc_matrix_lag[i,j]})")
        elif p_ba < THRESHOLD and p_ab >= THRESHOLD:
            # Unidirectional: tgt → src
            edges.append((tgt, src, '→', f_ba, p_ba))
            unidirectional.append((tgt, src, f_ba, p_ba))
            print(f"  {tgt} → {src}  (F={f_ba:.2f}, p={p_ba:.4f}, lag={gc_matrix_lag[j,i]})")
        elif p_ab < THRESHOLD and p_ba < THRESHOLD:
            # Bidirectional
            edges.append((src, tgt, '↔', max(f_ab, f_ba), min(p_ab, p_ba)))
            bidirectional.append((src, tgt, f_ab, p_ab, f_ba, p_ba))
            print(f"  {src} ↔ {tgt}  (F_ab={f_ab:.2f}, p={p_ab:.4f}; F_ba={f_ba:.2f}, p={p_ba:.4f})")
        else:
            pass  # No significant causal relationship

print(f"\nTotal edges: {len(edges)} ({len(unidirectional)} unidirectional, {len(bidirectional)} bidirectional)")

# ──────────────────────────────────────────────────────────
# 4. HUB AND LEAF ANALYSIS
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("[4] Network Topology: Hub vs Leaf Analysis")
print("=" * 80)

# Count outgoing and incoming edges for each asset
out_degree = {a: 0 for a in assets}
in_degree = {a: 0 for a in assets}

for src, tgt, direction, _, _ in edges:
    if direction == '→':
        out_degree[src] += 1
        in_degree[tgt] += 1
    elif direction == '↔':
        out_degree[src] += 1
        in_degree[src] += 1
        out_degree[tgt] += 1
        in_degree[tgt] += 1

print(f"\n{'Asset':>8s} {'Out (exports)':>14s} {'In (imports)':>14s} {'Net (out-in)':>14s}  Role")
print("-" * 65)
for a in assets:
    net = out_degree[a] - in_degree[a]
    if net > 0:
        role = "VOL EXPORTER (hub)"
    elif net < 0:
        role = "VOL IMPORTER (leaf)"
    elif out_degree[a] > 0:
        role = "RELAY (balanced)"
    else:
        role = "ISOLATED"
    print(f"{a:>8s} {out_degree[a]:>14d} {in_degree[a]:>14d} {net:>+14d}  {role}")

# Identify root cause
max_net = max(out_degree[a] - in_degree[a] for a in assets)
root_causes = [a for a in assets if out_degree[a] - in_degree[a] == max_net and max_net > 0]
if root_causes:
    print(f"\nRoot cause node(s): {', '.join(root_causes)} (highest net outgoing)")

max_in_net = min(out_degree[a] - in_degree[a] for a in assets)
leaf_nodes = [a for a in assets if out_degree[a] - in_degree[a] == max_in_net and max_in_net < 0]
if leaf_nodes:
    print(f"Terminal leaf node(s): {', '.join(leaf_nodes)} (highest net incoming)")

# ──────────────────────────────────────────────────────────
# 5. REGIME-DEPENDENT DAG (Low vs High VIX)
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("[5] Regime-Dependent DAG: Low vs High VIX")
print("=" * 80)

# Define regimes using VIX median
vix_aligned = vix_level.reindex(d_rv.index)
vix_median = vix_aligned.median()
print(f"\nVIX median: {vix_median:.1f}")

low_mask = vix_aligned <= vix_median
high_mask = vix_aligned > vix_median

regime_results = {}

for regime_name, mask in [("LOW_VIX", low_mask), ("HIGH_VIX", high_mask)]:
    d_rv_regime = d_rv[mask]
    n_obs = len(d_rv_regime)
    print(f"\n--- {regime_name} regime ({n_obs} observations) ---")

    gc_p_regime = np.ones((n_assets, n_assets))
    gc_f_regime = np.zeros((n_assets, n_assets))

    for i, src in enumerate(assets):
        for j, tgt in enumerate(assets):
            if i == j:
                continue
            x = d_rv_regime[src].values
            y = d_rv_regime[tgt].values
            lag, f_stat, p_val = granger_causality_test(x, y, max_lag=5)
            gc_p_regime[i, j] = p_val
            gc_f_regime[i, j] = f_stat

    # Count edges in this regime
    regime_edges = []
    regime_uni = []
    regime_bi = []

    for i, src in enumerate(assets):
        for j, tgt in enumerate(assets):
            if i >= j:
                continue
            p_ab = gc_p_regime[i, j]
            p_ba = gc_p_regime[j, i]
            f_ab = gc_f_regime[i, j]
            f_ba = gc_f_regime[j, i]

            if p_ab < THRESHOLD and p_ba >= THRESHOLD:
                regime_edges.append((src, tgt, '→'))
                regime_uni.append((src, tgt))
                print(f"  {src} → {tgt}  (F={f_ab:.2f}, p={p_ab:.4f})")
            elif p_ba < THRESHOLD and p_ab >= THRESHOLD:
                regime_edges.append((tgt, src, '→'))
                regime_uni.append((tgt, src))
                print(f"  {tgt} → {src}  (F={f_ba:.2f}, p={p_ba:.4f})")
            elif p_ab < THRESHOLD and p_ba < THRESHOLD:
                regime_edges.append((src, tgt, '↔'))
                regime_bi.append((src, tgt))
                print(f"  {src} ↔ {tgt}  (F_ab={f_ab:.2f}, F_ba={f_ba:.2f})")

    if not regime_edges:
        print("  No significant edges at p<0.01")

    regime_results[regime_name] = {
        'n_obs': n_obs,
        'total_edges': len(regime_edges),
        'unidirectional': len(regime_uni),
        'bidirectional': len(regime_bi),
        'edges': regime_edges,
    }

    print(f"  Total: {len(regime_edges)} edges ({len(regime_uni)} uni, {len(regime_bi)} bi)")

# Compare regimes
print(f"\n--- Regime Comparison ---")
for r in ["LOW_VIX", "HIGH_VIX"]:
    rr = regime_results[r]
    print(f"  {r}: {rr['total_edges']} edges ({rr['unidirectional']} uni + {rr['bidirectional']} bi)")

if regime_results["HIGH_VIX"]["total_edges"] > regime_results["LOW_VIX"]["total_edges"]:
    print("  → High VIX regime shows MORE causal connections (contagion intensifies in stress)")
elif regime_results["HIGH_VIX"]["total_edges"] < regime_results["LOW_VIX"]["total_edges"]:
    print("  → Low VIX regime shows MORE causal connections (tighter coupling in calm markets)")
else:
    print("  → Similar number of connections in both regimes")

# ──────────────────────────────────────────────────────────
# 6. PARTIAL DAG: After Controlling for VIX
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("[6] Partial DAG: Controlling for VIX")
print("=" * 80)

# Residualize each asset's delta-RV by removing VIX influence
d_vix = vix_aligned.diff().dropna()
common_idx = d_rv.index.intersection(d_vix.index)
d_rv_common = d_rv.loc[common_idx]
d_vix_common = d_vix.loc[common_idx].values

print(f"\nResidualizing delta-RV by removing VIX influence ({len(common_idx)} obs)...")
d_rv_residual = pd.DataFrame(index=common_idx)

for a in assets:
    y = d_rv_common[a].values
    X = np.column_stack([np.ones(len(y)), d_vix_common])
    # Also add lagged VIX changes
    d_vix_lag1 = np.roll(d_vix_common, 1)
    d_vix_lag1[0] = 0
    X = np.column_stack([X, d_vix_lag1])

    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    d_rv_residual[a] = resid
    r2 = 1 - np.var(resid) / np.var(y)
    print(f"  {a}: R² with VIX = {r2:.3f} (VIX explains {r2*100:.1f}% of delta-RV)")

# Re-run Granger causality on residuals
print(f"\nGranger causality on VIX-residualized delta-RV:")

gc_partial_p = np.ones((n_assets, n_assets))
gc_partial_f = np.zeros((n_assets, n_assets))

for i, src in enumerate(assets):
    for j, tgt in enumerate(assets):
        if i == j:
            continue
        x = d_rv_residual[src].values
        y = d_rv_residual[tgt].values
        lag, f_stat, p_val = granger_causality_test(x, y, max_lag=5)
        gc_partial_p[i, j] = p_val
        gc_partial_f[i, j] = f_stat

# Count surviving edges
print(f"\nPartial p-value matrix (row causes column, controlling for VIX):")
print(f"{'':>8s}", end="")
for a in assets:
    print(f" {a:>8s}", end="")
print()
for i, src in enumerate(assets):
    print(f"{src:>8s}", end="")
    for j, tgt in enumerate(assets):
        if i == j:
            p_str = "   ---  "
        else:
            p = gc_partial_p[i, j]
            if p < 0.001:
                p_str = f" <0.001*"
            elif p < 0.01:
                p_str = f"  {p:.3f}*"
            elif p < 0.05:
                p_str = f"  {p:.3f}†"
            else:
                p_str = f"  {p:.3f} "
        print(p_str, end="")
    print()

partial_edges = []
partial_uni = []
partial_bi = []

for i, src in enumerate(assets):
    for j, tgt in enumerate(assets):
        if i >= j:
            continue
        p_ab = gc_partial_p[i, j]
        p_ba = gc_partial_p[j, i]
        f_ab = gc_partial_f[i, j]
        f_ba = gc_partial_f[j, i]

        if p_ab < THRESHOLD and p_ba >= THRESHOLD:
            partial_edges.append((src, tgt, '→'))
            partial_uni.append((src, tgt))
            print(f"  {src} → {tgt}  (F={f_ab:.2f}, p={p_ab:.4f}) [survives VIX control]")
        elif p_ba < THRESHOLD and p_ab >= THRESHOLD:
            partial_edges.append((tgt, src, '→'))
            partial_uni.append((tgt, src))
            print(f"  {tgt} → {src}  (F={f_ba:.2f}, p={p_ba:.4f}) [survives VIX control]")
        elif p_ab < THRESHOLD and p_ba < THRESHOLD:
            partial_edges.append((src, tgt, '↔'))
            partial_bi.append((src, tgt))
            print(f"  {src} ↔ {tgt}  (F_ab={f_ab:.2f}, F_ba={f_ba:.2f}) [survives VIX control]")

print(f"\nAfter VIX control: {len(partial_edges)} edges survive "
      f"({len(partial_uni)} uni + {len(partial_bi)} bi)")
print(f"Original full-sample: {len(edges)} edges")
if len(edges) > 0:
    survival_rate = len(partial_edges) / len(edges) * 100
    print(f"Survival rate: {survival_rate:.0f}%")
    if survival_rate < 50:
        print("→ VIX absorbs most cross-asset causal links (common factor dominates)")
    else:
        print("→ Many causal links survive VIX control (genuine cross-asset transmission)")

# ──────────────────────────────────────────────────────────
# 7. CAUSAL CHAIN DETECTION
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("[7] Causal Chain Detection")
print("=" * 80)

# Build adjacency for unidirectional edges only
adj = {a: set() for a in assets}
for src, tgt, direction, _, _ in edges:
    if direction == '→':
        adj[src].add(tgt)

# Find all chains of length 2+ (A→B→C)
print("\nCausal chains (A → B → C):")
chain_count = 0
for a in assets:
    for b in adj[a]:
        for c in adj[b]:
            if c != a:  # avoid trivial loops
                chain_count += 1
                print(f"  {a} → {b} → {c}")

if chain_count == 0:
    print("  No multi-step causal chains found (all links are direct)")

# Find feedback loops (A→B→A through intermediate)
print("\nFeedback loops:")
loop_count = 0
for a in assets:
    for b in adj[a]:
        if a in adj[b]:
            # Direct feedback, already captured as bidirectional
            pass
        for c in adj[b]:
            if a in adj.get(c, set()) and c != a:
                loop_count += 1
                print(f"  {a} → {b} → {c} → {a}")

if loop_count == 0:
    print("  No feedback loops found")

# ──────────────────────────────────────────────────────────
# 8. INFORMATION FLOW TIMING (Lead-Lag via Cross-Correlation)
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("[8] Information Flow Timing (Cross-Correlation Lead-Lag)")
print("=" * 80)

print(f"\nPeak cross-correlation of delta-RV at various lags:")
print(f"{'Pair':>16s} {'Peak Lag':>9s} {'Corr':>7s} {'Interpretation':>30s}")
print("-" * 65)

for i, a in enumerate(assets):
    for j, b in enumerate(assets):
        if i >= j:
            continue
        # Cross-correlation at lags -10 to +10
        x = d_rv[a].values
        y = d_rv[b].values

        best_lag = 0
        best_corr = 0
        for lag in range(-10, 11):
            if lag == 0:
                corr = np.corrcoef(x, y)[0, 1]
            elif lag > 0:
                corr = np.corrcoef(x[:-lag], y[lag:])[0, 1]
            else:
                corr = np.corrcoef(x[-lag:], y[:lag])[0, 1]

            if abs(corr) > abs(best_corr):
                best_corr = corr
                best_lag = lag

        if best_lag > 0:
            interp = f"{a} leads {b} by {best_lag}d"
        elif best_lag < 0:
            interp = f"{b} leads {a} by {-best_lag}d"
        else:
            interp = "Contemporaneous"

        print(f"{a+'-'+b:>16s} {best_lag:>+9d} {best_corr:>7.3f} {interp:>30s}")

# ──────────────────────────────────────────────────────────
# 9. TRANSFER ENTROPY (Non-Linear Causality Check)
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("[9] Transfer Entropy (Non-Linear Causality)")
print("=" * 80)

def transfer_entropy_binned(x, y, lag=1, n_bins=5):
    """
    Estimate transfer entropy TE(X→Y) using binned estimator.
    TE(X→Y) = H(Y_t | Y_{t-lag}) - H(Y_t | Y_{t-lag}, X_{t-lag})
    Positive TE means X provides information about Y beyond Y's own past.
    """
    n = len(x) - lag
    if n < 100:
        return 0.0, 0.0

    # Bin the data
    x_binned = pd.qcut(x, n_bins, labels=False, duplicates='drop')
    y_binned = pd.qcut(y, n_bins, labels=False, duplicates='drop')

    y_t = y_binned[lag:]
    y_past = y_binned[:-lag]
    x_past = x_binned[:-lag]

    # Trim to same length
    min_len = min(len(y_t), len(y_past), len(x_past))
    y_t = y_t[:min_len]
    y_past = y_past[:min_len]
    x_past = x_past[:min_len]

    # Joint and conditional distributions
    # H(Y_t | Y_past) = H(Y_t, Y_past) - H(Y_past)
    def entropy_joint(*arrays):
        combined = np.column_stack(arrays)
        _, counts = np.unique(combined, axis=0, return_counts=True)
        probs = counts / counts.sum()
        return -np.sum(probs * np.log2(probs + 1e-12))

    def entropy_single(arr):
        _, counts = np.unique(arr, return_counts=True)
        probs = counts / counts.sum()
        return -np.sum(probs * np.log2(probs + 1e-12))

    # TE = H(Y_t, Y_past) + H(Y_past, X_past) - H(Y_past) - H(Y_t, Y_past, X_past)
    h_yt_ypast = entropy_joint(y_t, y_past)
    h_ypast_xpast = entropy_joint(y_past, x_past)
    h_ypast = entropy_single(y_past)
    h_yt_ypast_xpast = entropy_joint(y_t, y_past, x_past)

    te = h_yt_ypast + h_ypast_xpast - h_ypast - h_yt_ypast_xpast

    # Shuffle test for significance (100 permutations)
    te_null = []
    rng = np.random.RandomState(42)
    for _ in range(100):
        x_shuf = rng.permutation(x_past)
        h_ypast_xshuf = entropy_joint(y_past, x_shuf)
        h_yt_ypast_xshuf = entropy_joint(y_t, y_past, x_shuf)
        te_null.append(h_yt_ypast + h_ypast_xshuf - h_ypast - h_yt_ypast_xshuf)

    p_val = np.mean(np.array(te_null) >= te)

    return te, p_val


print(f"\nTransfer Entropy TE(A→B) with shuffle test (n_bins=5, lag=1):")
print(f"{'A→B':>16s} {'TE (bits)':>10s} {'p-value':>8s} {'Sig':>5s}")
print("-" * 45)

te_results = {}
for i, a in enumerate(assets):
    for j, b in enumerate(assets):
        if i == j:
            continue
        te, p = transfer_entropy_binned(rv_22[a].values, rv_22[b].values, lag=1, n_bins=5)
        sig = "*" if p < 0.01 else ("†" if p < 0.05 else "")
        te_results[(a, b)] = (te, p)
        if p < 0.05:  # only print significant or marginal
            print(f"{a+'→'+b:>16s} {te:>10.4f} {p:>8.3f} {sig:>5s}")

# Compare linear (Granger) vs non-linear (TE) results
print("\n--- Linear vs Non-Linear Causality Comparison ---")
print("Edges found by Granger but not by TE, and vice versa:")

for i, src in enumerate(assets):
    for j, tgt in enumerate(assets):
        if i >= j:
            continue

        gc_sig_ab = gc_matrix_p[i, j] < THRESHOLD
        gc_sig_ba = gc_matrix_p[j, i] < THRESHOLD
        te_sig_ab = te_results.get((src, tgt), (0, 1))[1] < 0.05
        te_sig_ba = te_results.get((tgt, src), (0, 1))[1] < 0.05

        # Cases of disagreement
        if gc_sig_ab and not te_sig_ab:
            print(f"  {src}→{tgt}: Granger YES, TE NO (linear-only causality)")
        if not gc_sig_ab and te_sig_ab:
            print(f"  {src}→{tgt}: Granger NO, TE YES (non-linear causality)")
        if gc_sig_ba and not te_sig_ba:
            print(f"  {tgt}→{src}: Granger YES, TE NO (linear-only causality)")
        if not gc_sig_ba and te_sig_ba:
            print(f"  {tgt}→{src}: Granger NO, TE YES (non-linear causality)")

# ──────────────────────────────────────────────────────────
# 10. SUMMARY AND DAG VISUALIZATION (ASCII)
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("[10] FINAL CAUSAL DAG SUMMARY")
print("=" * 80)

print(f"""
Data: yfinance daily, {price_df.index[0].date()} to {price_df.index[-1].date()}
Assets: {', '.join(assets)}
Volatility measure: 22-day rolling realized vol (annualized %)
Stationarity: First-differenced (delta-RV)
Test: Granger causality F-test, lags 1-5, p<0.01
""")

print("FULL-SAMPLE CAUSAL DAG:")
print("-" * 40)
if not edges:
    print("  No significant causal edges found")
else:
    for src, tgt, direction, f_stat, p_val in edges:
        print(f"  {src} {direction} {tgt}  (F={f_stat:.2f}, p={p_val:.6f})")

print(f"\nNETWORK STATISTICS:")
print(f"  Total nodes: {n_assets}")
print(f"  Total edges: {len(edges)}")
print(f"  Density: {len(edges) / (n_assets * (n_assets - 1) / 2):.2f} (max=1.0)")
print(f"  Unidirectional: {len(unidirectional)}")
print(f"  Bidirectional: {len(bidirectional)}")

print(f"\nHIERARCHY:")
sorted_assets = sorted(assets, key=lambda a: out_degree[a] - in_degree[a], reverse=True)
for rank, a in enumerate(sorted_assets, 1):
    net = out_degree[a] - in_degree[a]
    print(f"  #{rank}: {a} (out={out_degree[a]}, in={in_degree[a]}, net={net:+d})")

print(f"\nREGIME COMPARISON:")
for r in ["LOW_VIX", "HIGH_VIX"]:
    rr = regime_results[r]
    print(f"  {r}: {rr['total_edges']} edges ({rr['n_obs']} obs)")

print(f"\nVIX CONTROL:")
print(f"  Original edges: {len(edges)}")
print(f"  After VIX control: {len(partial_edges)}")
if len(edges) > 0:
    print(f"  Survival rate: {len(partial_edges)/len(edges)*100:.0f}%")

# ──────────────────────────────────────────────────────────
# 11. SAVE RESULTS
# ──────────────────────────────────────────────────────────

results = {
    'experiment': 'K356',
    'title': 'Causal DAG Discovery for Cross-Asset Volatility',
    'date': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'period': f"{price_df.index[0].date()} to {price_df.index[-1].date()}",
    'n_observations': len(d_rv),
    'assets': assets,
    'method': 'Granger causality F-test (lags 1-5, p<0.01) + Transfer Entropy',
    'full_sample': {
        'total_edges': len(edges),
        'unidirectional': len(unidirectional),
        'bidirectional': len(bidirectional),
        'edges': [(s, t, d) for s, t, d, _, _ in edges],
        'hierarchy': {a: {'out': out_degree[a], 'in': in_degree[a],
                         'net': out_degree[a] - in_degree[a]} for a in assets},
    },
    'regime_comparison': {
        'vix_median': float(vix_median),
        'low_vix_edges': regime_results['LOW_VIX']['total_edges'],
        'high_vix_edges': regime_results['HIGH_VIX']['total_edges'],
    },
    'vix_control': {
        'original_edges': len(edges),
        'surviving_edges': len(partial_edges),
        'survival_rate': len(partial_edges) / max(len(edges), 1) * 100,
    },
    'granger_p_matrix': {
        'rows_cols': assets,
        'values': gc_matrix_p.tolist(),
    },
    'partial_p_matrix': {
        'rows_cols': assets,
        'values': gc_partial_p.tolist(),
    },
}

output_path = 'experiments/k356_causal_dag_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")

print("\n" + "=" * 80)
print("K356 COMPLETE")
print("=" * 80)
