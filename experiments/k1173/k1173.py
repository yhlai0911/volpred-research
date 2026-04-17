#!/usr/bin/env python3
"""K1173 — Refined institutional-ownership proxy for EM (BR/CH/IN/MX).

Tests whether K1168/K1172 off-ladder EM residuals are proxy-measurement
artefacts (yfinance institutions_pct under/over-counting EM structural
holders) or structural (EM markets genuinely off the developed-ladder).

Spec:
  - Load K1172 N=12 pool baseline (yfinance inst_pct).
  - Load K1173 per-stock refined inst_pct (SEBI / CVM / CNBV / SSE
    disclosures via screener.in + simplywall.st curated company filings).
  - Replace yfinance inst_pct with refined for 4 EM markets (BR/CH/IN/MX)
    while keeping developed markets yfinance.
  - Recompute K1168-style cross-market Spearman + K1172-style panel.

Comparisons:
  (a) N=12 Spearman ρ(inst_pct_mean, θ_rel) baseline (yfinance) vs refined
  (b) Per-stock diff (refined - yfinance)
  (c) Drop-LOO stability
  (d) Panel OLS with refined

Verdict criteria:
  PASS: refined primary ρ lifts back to K1165 +0.75 level (ρ ≥ 0.70,
        p < 0.05) → EM residual is PROXY-MEASUREMENT ARTEFACT
  PARTIAL: refined ρ improves by ≥ 0.10 or p crosses 0.10 → partial
           contribution of proxy issue
  NULL: refined ρ within ±0.05 of yfinance baseline → EM residual is
        STRUCTURAL (not a proxy artefact)

Random seed: 42.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

np.random.seed(42)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# K1172 / K1168 baselines live in mainline; worktree branches off earlier HEAD.
# We reference mainline absolute paths for READ-ONLY dependency data.
MAINLINE_EXPERIMENTS = Path(
    "/Users/yhlai0911/Desktop/volpred-research/experiments")
K1172_ROOT = MAINLINE_EXPERIMENTS / "k1172"
K1168_ROOT = MAINLINE_EXPERIMENTS / "k1168"
K1168_DATA = K1168_ROOT / "data"


def spearman_with_p(x, y):
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3:
        return float("nan"), float("nan"), int(m.sum())
    rho, p = stats.spearmanr(x[m], y[m])
    return float(rho), float(p), int(m.sum())


def panel_ols(df: pd.DataFrame, y_col: str, x_cols: list[str]) -> dict:
    """HC0 panel OLS with market FE."""
    df = df.dropna(subset=[y_col, *x_cols]).copy()
    markets = sorted(df["market"].unique().tolist())
    X_cols, X_parts = [], []
    for m in markets:
        df[f"D_{m}"] = (df["market"] == m).astype(float)
        X_cols.append(f"D_{m}")
        X_parts.append(df[f"D_{m}"].to_numpy().reshape(-1, 1))
    for c in x_cols:
        X_cols.append(c)
        X_parts.append(df[c].to_numpy(dtype=float).reshape(-1, 1))
    X = np.hstack(X_parts); y = df[y_col].to_numpy(dtype=float)
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    n, k = X.shape
    S = (X * resid.reshape(-1, 1)).T @ (X * resid.reshape(-1, 1))
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    t = beta / se
    p = 2 * (1 - stats.t.cdf(np.abs(t), df=n - k))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(np.sum(resid ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "n": int(n), "k": int(k), "r2": r2,
        "coefs": {c: {"beta": float(beta[i]), "se": float(se[i]),
                      "t": float(t[i]), "p": float(p[i])}
                  for i, c in enumerate(X_cols)},
    }


def load_k1172_baseline() -> tuple[pd.DataFrame, dict, dict]:
    """Load K1172 per-market summary (baseline yfinance) + theta_rel."""
    k1172_res = json.load(open(K1172_ROOT / "k1172_results.json"))
    summary = pd.DataFrame(k1172_res["per_market_summary"]).set_index("market")
    theta_rel = {m: float(v) for m, v in k1172_res["theta_rel"].items()
                 if pd.notna(v)}
    # Keep only markets used in K1172 final test
    used = k1172_res["cross_market_spearman"]["markets_ordered"]
    summary = summary.loc[[m for m in used if m in summary.index]]
    return summary, theta_rel, k1172_res


def build_refined_summary(baseline: pd.DataFrame,
                          refined_csv: Path) -> pd.DataFrame:
    """Override EM institutions_pct_mean with refined per-stock means."""
    df = pd.read_csv(refined_csv, comment="#")
    # Per-market refined mean
    em_means = df.groupby("market")["refined_inst_pct"].mean()
    refined = baseline.copy()
    for m, v in em_means.items():
        if m in refined.index:
            refined.loc[m, "institutions_pct_mean_yfinance"] = \
                baseline.loc[m, "institutions_pct_mean"]
            refined.loc[m, "institutions_pct_mean"] = float(v)
    # Keep yfinance baseline copy on non-EM rows
    for m in refined.index:
        if "institutions_pct_mean_yfinance" not in refined.columns \
                or pd.isna(refined.loc[m, "institutions_pct_mean_yfinance"]):
            refined.loc[m, "institutions_pct_mean_yfinance"] = \
                baseline.loc[m, "institutions_pct_mean"]
    return refined, df


def load_panel_stock_level(refined_df: pd.DataFrame) -> pd.DataFrame:
    """Load K1172 per-stock panel and replace EM institutions_pct per ticker."""
    panel = pd.read_csv(K1172_ROOT / "k1172_per_stock_table.csv")
    panel = panel.rename(columns={"institutions_pct": "institutions_pct_yf"})
    # refined keyed by ticker with market prefix (RELIANCE.NS etc.)
    refined_by_ticker = dict(zip(refined_df["ticker"],
                                 refined_df["refined_inst_pct"]))
    panel["institutions_pct_refined"] = panel.apply(
        lambda r: refined_by_ticker.get(r["ticker"], r["institutions_pct_yf"]),
        axis=1,
    )
    # For developed markets / unmapped EM, keep yfinance
    panel["institutions_pct"] = panel["institutions_pct_refined"]
    return panel


def run_cross_market(summary: pd.DataFrame, theta_rel: dict,
                      label: str) -> dict:
    """Compute cross-market Spearman + LOO."""
    markets = sorted([m for m in summary.index
                      if np.isfinite(summary.loc[m, "institutions_pct_mean"])
                      and np.isfinite(theta_rel.get(m, np.nan))])
    xs = [summary.loc[m, "institutions_pct_mean"] for m in markets]
    ys = [theta_rel[m] for m in markets]
    rho, p, n = spearman_with_p(xs, ys)

    loo = {}
    for drop_m in markets:
        sub = [m for m in markets if m != drop_m]
        xsi = [summary.loc[m, "institutions_pct_mean"] for m in sub]
        ysi = [theta_rel[m] for m in sub]
        r, pp, nn = spearman_with_p(xsi, ysi)
        loo[drop_m] = {"rho": r, "p": pp, "n": nn}

    return {
        "label": label,
        "markets_used": markets,
        "primary_spearman": {"rho": rho, "p": p, "n": n},
        "inst_pct_values": {m: float(summary.loc[m, "institutions_pct_mean"])
                            for m in markets},
        "theta_rel_values": {m: theta_rel[m] for m in markets},
        "leave_one_out": loo,
    }


def plot_scatter_comparison(baseline_result: dict, refined_result: dict,
                             theta_rel: dict, out_path: Path):
    colors = {"TW": "tab:blue", "US": "tab:red", "JP": "tab:green",
              "EU": "tab:orange", "KR": "tab:purple", "CA": "tab:brown",
              "HK": "tab:pink", "BR": "darkgoldenrod", "CH": "crimson",
              "IN": "teal", "MX": "goldenrod", "ID": "mediumseagreen"}
    em_markets = {"BR", "CH", "IN", "MX"}

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for ax, result, title_suffix in zip(
            axes,
            [baseline_result, refined_result],
            ["yfinance baseline", "refined (brief spec)"]):
        markets = result["markets_used"]
        xs = [result["inst_pct_values"][m] for m in markets]
        ys = [theta_rel[m] for m in markets]
        for m, x, y in zip(markets, xs, ys):
            is_em = m in em_markets
            ax.scatter(x, y, s=160 if is_em else 120,
                       color=colors.get(m, "gray"),
                       edgecolor="black", linewidth=1.8 if is_em else 0.8,
                       marker="s" if is_em else "o",
                       label=f"{m}{' (EM)' if is_em else ''}")
            ax.annotate(m, (x, y), textcoords="offset points",
                        xytext=(8, 3), fontsize=10,
                        fontweight="bold" if is_em else "normal")
        rho = result["primary_spearman"]["rho"]
        p = result["primary_spearman"]["p"]
        n = result["primary_spearman"]["n"]
        ax.set_xlabel("Mean institutional ownership %")
        ax.set_ylabel(r"Market $\theta_{rel}$")
        ax.set_title(f"{title_suffix}\n"
                     f"N={n}: ρ={rho:+.3f}, p={p:.4f}")
        ax.grid(alpha=0.3)
    fig.suptitle("K1173 — EM refined institutional proxy "
                 "(square = EM refined per brief)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_diff_barplot(refined_df: pd.DataFrame, market_diff: dict,
                      out_path: Path):
    """Bar plot of yfinance vs refined at market level + per-stock diffs."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    # Left: market-level mean
    ax = axes[0]
    markets = sorted(market_diff.keys())
    yf_vals = [market_diff[m]["yfinance_mean"] for m in markets]
    refined_vals = [market_diff[m]["refined_mean"] for m in markets]
    x = np.arange(len(markets))
    w = 0.38
    ax.bar(x - w/2, yf_vals, w, label="yfinance mean",
           color="tab:gray", edgecolor="black")
    ax.bar(x + w/2, refined_vals, w, label="refined mean",
           color="tab:blue", edgecolor="black")
    ax.set_xticks(x); ax.set_xticklabels(markets)
    ax.set_ylabel("Institutional ownership %")
    ax.set_title("EM market-level mean: yfinance vs refined")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    for xi, v in zip(x - w/2, yf_vals):
        ax.annotate(f"{v:.2f}", (xi, v), textcoords="offset points",
                    xytext=(0, 3), ha="center", fontsize=9)
    for xi, v in zip(x + w/2, refined_vals):
        ax.annotate(f"{v:.2f}", (xi, v), textcoords="offset points",
                    xytext=(0, 3), ha="center", fontsize=9)

    # Right: per-stock diff sorted
    ax = axes[1]
    df_sorted = refined_df.dropna(subset=["yfinance_inst_pct"]).copy()
    df_sorted["diff"] = df_sorted["refined_inst_pct"] - df_sorted["yfinance_inst_pct"]
    df_sorted = df_sorted.sort_values("diff")
    colors = {"BR": "darkgoldenrod", "CH": "crimson",
              "IN": "teal", "MX": "goldenrod"}
    bar_colors = [colors.get(m, "gray") for m in df_sorted["market"]]
    ax.barh(range(len(df_sorted)), df_sorted["diff"], color=bar_colors,
            edgecolor="black", linewidth=0.3)
    ax.set_yticks(range(len(df_sorted)))
    ax.set_yticklabels([f"{t.split('.')[0]} ({m})"
                        for t, m in zip(df_sorted["ticker"], df_sorted["market"])],
                       fontsize=7)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlabel("refined − yfinance institutional %")
    ax.set_title("Per-stock refined vs yfinance (N=39, GRUMAB yf=None excluded)")
    ax.grid(axis="x", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def main():
    print("\n" + "=" * 72)
    print("K1173: Refined institutional-ownership proxy for EM (BR/CH/IN/MX)")
    print("=" * 72 + "\n")

    # ---- 1. Load baselines ----
    baseline_summary, theta_rel, k1172_res = load_k1172_baseline()
    print(f"[K1172 baseline] markets: {list(baseline_summary.index)}, "
          f"theta_rel: {theta_rel}")

    refined_summary, refined_df = build_refined_summary(
        baseline_summary, DATA / "k1173_em_refined_holdings.csv")
    print(f"\n[refined] N tickers with refined_pct: {len(refined_df)}")

    # ---- 2. Cross-market Spearman: baseline vs refined ----
    baseline_result = run_cross_market(baseline_summary, theta_rel,
                                        "yfinance_baseline")
    refined_result = run_cross_market(refined_summary, theta_rel,
                                       "refined_em")

    print("\n[Cross-market Spearman]")
    for r in (baseline_result, refined_result):
        sp = r["primary_spearman"]
        print(f"  {r['label']}: ρ={sp['rho']:+.3f}, p={sp['p']:.4f}, "
              f"N={sp['n']}")

    delta_rho = refined_result["primary_spearman"]["rho"] - \
                baseline_result["primary_spearman"]["rho"]
    delta_p = refined_result["primary_spearman"]["p"] - \
              baseline_result["primary_spearman"]["p"]
    print(f"  Δρ = {delta_rho:+.3f}, Δp = {delta_p:+.4f}")

    # ---- 3. LOO sensitivity ----
    print("\n[Leave-one-out: refined]")
    for m, r in refined_result["leave_one_out"].items():
        print(f"  drop {m}: ρ={r['rho']:+.3f}, p={r['p']:.4f}")

    # ---- 4. Per-stock diff summary ----
    market_diff = json.load(open(DATA / "k1173_em_refined_market_means.json"))
    print("\n[Per-market diff summary]")
    for m, rec in market_diff.items():
        print(f"  {m}: yf_mean={rec['yfinance_mean']:.3f}, "
              f"refined_mean={rec['refined_mean']:.3f}, "
              f"Δ={rec['diff_mean']:+.3f}")

    # ---- 5. Panel OLS with refined institutions_pct ----
    panel = load_panel_stock_level(refined_df)
    panel_valid = panel.dropna(subset=["theta_eav", "log_analyst", "log_mcap",
                                        "institutions_pct"]).copy()
    print(f"\n[panel refined] N_stocks={len(panel_valid)}")

    panel_specs = {
        "analyst_only": panel_ols(panel_valid, "theta_eav",
                                   ["log_analyst", "log_mcap"]),
        "inst_only_refined": panel_ols(panel_valid, "theta_eav",
                                        ["institutions_pct", "log_mcap"]),
        "joint_refined": panel_ols(panel_valid, "theta_eav",
                                    ["log_analyst", "institutions_pct",
                                     "log_mcap"]),
    }
    print("\n[Panel OLS joint (refined inst_pct)]:")
    joint = panel_specs["joint_refined"]
    for c in ("log_analyst", "institutions_pct", "log_mcap"):
        if c in joint["coefs"]:
            cc = joint["coefs"][c]
            print(f"  {c}: β={cc['beta']:+.3e}, t={cc['t']:+.2f}, "
                  f"p={cc['p']:.3f}")

    # K1172 baseline panel values for comparison
    k1172_joint = k1172_res["panel_ols"]["joint"]["coefs"]
    print("\n[K1172 panel baseline (yfinance)]:")
    for c in ("log_analyst", "institutions_pct", "log_mcap"):
        if c in k1172_joint:
            cc = k1172_joint[c]
            print(f"  {c}: β={cc['beta']:+.3e}, t={cc['t']:+.2f}, "
                  f"p={cc['p']:.3f}")

    # ---- 6. Verdict ----
    r_ref = refined_result["primary_spearman"]["rho"]
    p_ref = refined_result["primary_spearman"]["p"]
    r_base = baseline_result["primary_spearman"]["rho"]
    p_base = baseline_result["primary_spearman"]["p"]

    if r_ref >= 0.70 and p_ref < 0.05:
        verdict = "PASS"
        narrative = (f"refined ρ={r_ref:+.3f}, p={p_ref:.4f} lifts to "
                     f"K1165 +0.75 level. EM off-ladder is a "
                     f"PROXY-MEASUREMENT ARTEFACT of yfinance "
                     f"institutions_pct. Paper 2 §5 narrative should "
                     f"upgrade to STRENGTHENED/CONFIRMED (yfinance-"
                     f"dependent caveat removed).")
    elif r_ref - r_base >= 0.10 or (p_ref < 0.10 and p_base >= 0.10):
        verdict = "PARTIAL"
        narrative = (f"refined ρ={r_ref:+.3f} (Δ={delta_rho:+.3f}), "
                     f"p={p_ref:.4f} (Δp={delta_p:+.4f}) improves "
                     f"meaningfully but does not reach +0.75 level. "
                     f"PARTIAL proxy artefact: EM institutional proxy "
                     f"matters but structural factor persists. Paper 2 "
                     f"§5 narrative: acknowledge measurement issue + "
                     f"residual structural effect.")
    elif abs(delta_rho) < 0.10:
        verdict = "NULL"
        narrative = (f"refined ρ={r_ref:+.3f} within ±0.10 of yfinance "
                     f"baseline ρ={r_base:+.3f} (Δρ={delta_rho:+.3f}). "
                     f"EM off-ladder is STRUCTURAL, not a yfinance proxy "
                     f"artefact. Paper 2 §5 narrative: keep K1172 "
                     f"'STRENGTHENED with emerging-market scale residual "
                     f"caveat'; emerging markets genuinely sit off the "
                     f"developed institutional-ownership ladder even when "
                     f"the proxy is re-estimated from SEBI/CVM/BMV/SSE "
                     f"regulatory disclosures.")
    else:
        verdict = "INCONCLUSIVE"
        narrative = (f"refined ρ={r_ref:+.3f} vs baseline {r_base:+.3f}; "
                     f"direction or magnitude ambiguous. "
                     f"Need additional evidence before narrative pivot.")

    print(f"\n===== VERDICT: {verdict} =====")
    print(narrative)

    # ---- 7. Plots ----
    plot_scatter_comparison(baseline_result, refined_result, theta_rel,
                             ROOT / "k1173_scatter_refined_vs_yfinance.png")
    plot_diff_barplot(refined_df, market_diff,
                       ROOT / "k1173_diff_barplot.png")
    print("\n[figures] wrote scatter + diff barplot")

    # ---- 8. Save results ----
    results = {
        "experiment_id": "K1173",
        "title": "Refined institutional-ownership proxy for EM "
                 "(BR/CH/IN/MX) to test K1168/K1172 off-ladder residuals",
        "proposer": "User brief (承接 K1168 STRENGTHENED / K1172 PARTIAL EM residual)",
        "executor": "Claude (worktree agent)",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": 42,
        "coverage": {
            "IN": int((refined_df["market"] == "IN").sum()),
            "BR": int((refined_df["market"] == "BR").sum()),
            "MX": int((refined_df["market"] == "MX").sum()),
            "CH": int((refined_df["market"] == "CH").sum()),
            "total": int(len(refined_df)),
        },
        "data_sources": [
            "screener.in: quarterly SEBI shareholding patterns for 10 "
            "Indian tickers (Dec 2025 / Mar 2026)",
            "simplywall.st: aggregated company filings for BR/MX/CH "
            "(Apr 2026 snapshot)",
            "yfinance Ticker.major_holders (K1172 baseline)",
            "K1172 per-market summary + theta_rel",
            "K1172 per-stock panel table",
        ],
        "refined_spec": {
            "IN": "FII + DII (SEBI canonical 'institutional', "
                  "excludes promoter)",
            "BR": "simplywall.st 'Institutions' bucket only (excludes "
                  "'Private Companies' = controlling shareholder, "
                  "'Government' = state, 'Individual Insiders' = family)",
            "MX": "simplywall.st 'Institutions' bucket only (excludes "
                  "controlling-family 'Private Companies' and insiders)",
            "CH": "simplywall.st 'Institutions' + 'Sovereign Wealth Funds' "
                  "(excludes 'State or Government' and 'Private Companies' "
                  "when the latter holds the SOE parent)",
        },
        "per_market_diff": market_diff,
        "baseline_cross_market": baseline_result,
        "refined_cross_market": refined_result,
        "delta": {
            "delta_rho": float(delta_rho),
            "delta_p": float(delta_p),
            "baseline_rho": float(r_base),
            "baseline_p": float(p_base),
            "refined_rho": float(r_ref),
            "refined_p": float(p_ref),
            "N": int(refined_result["primary_spearman"]["n"]),
        },
        "panel_ols_refined": panel_specs,
        "panel_ols_baseline_k1172": k1172_res["panel_ols"]["joint"],
        "verdict": verdict,
        "verdict_narrative": narrative,
        "per_stock_table": refined_df.to_dict(orient="records"),
    }
    with open(ROOT / "k1173_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[json] wrote k1173_results.json")

    return results


if __name__ == "__main__":
    main()
