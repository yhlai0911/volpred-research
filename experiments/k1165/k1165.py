#!/usr/bin/env python3
"""K1165 — Cross-market confirmation test for K1167 two-level mechanism
(N=7 markets: TW, EU, JP, US [K1166/K1167 legacy] + KR, CA, HK [new]).

Rationale
---------
K1167 identified institutional ownership (major_holders.institutionsPercentHeld)
as the cross-market ranking variable for the θ_rel cluster split, at N=4 markets
(ρ=+0.80, p=0.20 — direction right, no statistical power). K1165 extends to
N=7 markets to test confirmation.

AU was attempted as 8th market but dropped: yfinance get_earnings_dates returns
<=3 past announcement dates per ASX stock (semi-annual reporting + poor Yahoo
coverage), making per-stock MLE impossible (requires ≥15 events).

Data
----
- TW, EU, JP, US: per-stock θ_EAV from K1166 CSV; pooled θ_EAV from K1145/
  K1147/K1150/K1153 pooled-shared MLE; institutions_pct from K1167.
- KR, CA, HK: fitted here via k1165_per_stock_refit.py (same K1166/K1145 spec).

Tests
-----
1. Cross-market Spearman ρ(institutions_pct_mean, θ_rel) at N=7.
2. Cross-market Spearman ρ(log_analyst_median, θ_rel) at N=7.
3. Cross-market Spearman ρ(log_mcap_median, θ_rel) at N=7.
4. Per-stock panel θ_EAV_i ~ log_analyst + institutions_pct + log_mcap + market_FE.
5. Within-market demeaned correlation.
6. Two-level decomposition (between-market R² vs within-market R²).

Random seed: 42. No lookahead — institutions_pct is current snapshot.
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

# -------------------------------------------------------------------------
# Legacy market θ_rel (K1152/K1153 documented)
# -------------------------------------------------------------------------
LEGACY_THETA_REL: dict[str, float] = {"TW": 0.17, "EU": 0.14, "JP": 0.39, "US": 0.59}

# Legacy pooled θ_EAV from K1145/K1147/K1150/K1153 main fits
LEGACY_POOLED_THETA_EAV: dict[str, dict] = {
    "TW": {"theta_eav": 6.362e-05, "theta_eav_t": 14.14, "source": "K1145"},
    "US": {"theta_eav": 1.909e-04, "theta_eav_t": 22.39, "source": "K1147"},
    "JP": {"theta_eav": 1.413e-04, "theta_eav_t": 20.16, "source": "K1150"},
    "EU": {"theta_eav": 4.072e-05, "theta_eav_t": 10.03, "source": "K1153"},
}

# -------------------------------------------------------------------------
def spearman_with_p(x, y):
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3:
        return float("nan"), float("nan"), int(m.sum())
    rho, p = stats.spearmanr(x[m], y[m])
    return float(rho), float(p), int(m.sum())


def pearson_with_p(x, y):
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3:
        return float("nan"), float("nan"), int(m.sum())
    r, p = stats.pearsonr(x[m], y[m])
    return float(r), float(p), int(m.sum())


def panel_ols(df: pd.DataFrame, y_col: str, x_cols: list[str]) -> dict:
    """White HC0 panel OLS with market FE (no intercept; absorb via dummies)."""
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


def demean_within(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c + "_dm"] = out.groupby("market")[c].transform(
            lambda x: x - x.mean())
    return out


def two_level_decomposition(df: pd.DataFrame, y_col: str,
                            between_cols: list[str],
                            within_cols: list[str]) -> dict:
    """R² decomposition:
       between-market: regress market-mean(y) on market-mean(x_between)
       within-market:  regress demeaned y on demeaned x_within
    """
    # Between-market
    bm = df.groupby("market").mean(numeric_only=True)
    between_r2 = {}
    for c in between_cols:
        sub = bm[[y_col, c]].dropna()
        if len(sub) < 3:
            between_r2[c] = float("nan"); continue
        x = sub[c].to_numpy(dtype=float); y = sub[y_col].to_numpy(dtype=float)
        X = np.column_stack([np.ones_like(x), x])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        yhat = X @ coef
        ss_res = np.sum((y - yhat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        between_r2[c] = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")

    # Within-market
    dm = demean_within(df, within_cols + [y_col])
    within_r2 = {}
    for c in within_cols:
        sub = dm[[y_col + "_dm", c + "_dm"]].dropna()
        if len(sub) < 3:
            within_r2[c] = float("nan"); continue
        x = sub[c + "_dm"].to_numpy(dtype=float); y = sub[y_col + "_dm"].to_numpy(dtype=float)
        ss_tot = float(np.sum(y ** 2))
        if ss_tot <= 0:
            within_r2[c] = float("nan"); continue
        coef = float(np.sum(x * y) / np.sum(x * x)) if np.sum(x * x) > 0 else 0.0
        yhat = coef * x
        ss_res = float(np.sum((y - yhat) ** 2))
        within_r2[c] = float(1.0 - ss_res / ss_tot)
    return {"between_market_r2": between_r2, "within_market_r2": within_r2,
            "N_markets_between": int(bm.dropna(subset=[y_col]).shape[0]),
            "N_stocks_within": int(dm.dropna(subset=[y_col + "_dm"]).shape[0])}


# =========================================================================
# Build 7-market panel
# =========================================================================
def build_panel() -> tuple[pd.DataFrame, dict]:
    """Union of K1166 TW/EU/JP/US (110 stocks, 108 with analyst) +
       K1165 KR/CA/HK new (25 stocks)."""
    k1166 = pd.read_csv(DATA / "k1166_per_stock_table.csv")
    k1166 = k1166[k1166["converged"].astype(bool)].copy()

    # K1167 institutions_pct for TW/EU/JP/US
    k1167 = json.load(open(DATA / "institutional_ownership_k1167.json"))
    ip_map = {}
    for rec in k1167["records"]:
        mh = rec.get("major_holders") or {}
        ip_map[rec["ticker"]] = mh.get("institutionsPercentHeld")
    k1166["institutions_pct"] = k1166["ticker"].map(lambda t: ip_map.get(t))

    # K1165 new markets
    k1165_new = pd.read_csv(ROOT / "k1165_per_stock_table_newmkts.csv")
    k1165_new = k1165_new[k1165_new["converged"].astype(bool)].copy()

    # Schema alignment — keep common columns
    keep_cols = ["market", "ticker", "theta_eav", "theta_eav_t", "theta_eav_se",
                 "sigma2_sample", "analyst_count", "market_cap",
                 "institutions_pct", "n_obs", "n_events"]
    # For k1166, median_daily_turnover not needed; all keep_cols present
    panel = pd.concat([
        k1166[keep_cols].assign(source="K1166"),
        k1165_new[keep_cols].assign(source="K1165"),
    ], ignore_index=True)
    panel["log_analyst"] = np.log(panel["analyst_count"].astype(float) + 1.0)
    panel["log_mcap"] = np.log(panel["market_cap"].astype(float))

    # Market metadata (mean institutions_pct using ALL fetched records even if
    # their MLE dropped — use k1167 full 110 + k1165 fetch full 40 for mean inst_pct)
    ih_new = json.load(open(DATA / "institutional_ownership_new.json"))
    inst_mean_by_mkt: dict[str, list[float]] = {}
    for rec in k1167["records"]:
        m = rec["market"]
        mh = rec.get("major_holders") or {}
        v = mh.get("institutionsPercentHeld")
        if v is not None:
            inst_mean_by_mkt.setdefault(m, []).append(float(v))
    for rec in ih_new["records"]:
        m = rec["market"]
        mh = rec.get("major_holders") or {}
        v = mh.get("institutionsPercentHeld")
        if v is not None:
            inst_mean_by_mkt.setdefault(m, []).append(float(v))
    return panel, inst_mean_by_mkt


# =========================================================================
# Compute per-market θ_rel for new markets (same def as K1152: pooled θ_EAV / mean σ²)
# =========================================================================
def compute_theta_rel(pooled_new: dict,
                      mean_sigma2_panel: dict[str, float]) -> dict[str, float]:
    """θ_rel = pooled θ_EAV / mean_σ²_market (same definition as K1152)."""
    out = dict(LEGACY_THETA_REL)  # TW/EU/JP/US
    for m in ("KR", "CA", "HK"):
        if m in pooled_new and pooled_new[m].get("converged"):
            te = pooled_new[m]["theta_eav"]
            s2 = mean_sigma2_panel[m]
            # θ_rel = θ_EAV * (EAV days/total) / σ² — but K1152 defined as
            # θ_EAV/σ² giving a unitless scale. Use same convention.
            out[m] = float(te / s2)
    return out


# =========================================================================
# Plots
# =========================================================================
def plot_8market_scatter(market_summary: pd.DataFrame, theta_rel: dict,
                         out_path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    colors = {"TW": "tab:blue", "US": "tab:red", "JP": "tab:green",
              "EU": "tab:orange", "KR": "tab:purple", "CA": "tab:brown",
              "HK": "tab:pink"}

    # Left: institutions_pct vs θ_rel
    ax = axes[0]
    markets = sorted(theta_rel.keys())
    xs = [market_summary.loc[m, "institutions_pct_mean"] for m in markets]
    ys = [theta_rel[m] for m in markets]
    for m, x, y in zip(markets, xs, ys):
        ax.scatter(x, y, s=110, color=colors.get(m, "gray"),
                   edgecolor="black", label=m)
        ax.annotate(m, (x, y), textcoords="offset points", xytext=(8, 2),
                    fontsize=9)
    rho, p, _ = spearman_with_p(xs, ys)
    ax.set_xlabel("Mean institutional ownership %")
    ax.set_ylabel(r"Market $\theta_{rel}$")
    ax.set_title(f"N=7: institutions_pct vs θ_rel (ρ={rho:+.3f}, p={p:.3f})")
    ax.grid(alpha=0.3)

    # Right: analyst_median vs θ_rel
    ax = axes[1]
    xs2 = [market_summary.loc[m, "analyst_median"] for m in markets]
    for m, x, y in zip(markets, xs2, ys):
        ax.scatter(x, y, s=110, color=colors.get(m, "gray"),
                   edgecolor="black", label=m)
        ax.annotate(m, (x, y), textcoords="offset points", xytext=(8, 2),
                    fontsize=9)
    rho2, p2, _ = spearman_with_p(xs2, ys)
    ax.set_xlabel("Median analyst count")
    ax.set_ylabel(r"Market $\theta_{rel}$")
    ax.set_title(f"N=7: analyst_median vs θ_rel (ρ={rho2:+.3f}, p={p2:.3f})")
    ax.grid(alpha=0.3)

    fig.suptitle("K1165: N=7 market cross-sectional test of K1167 two-level mechanism",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_panel_forest(panel_coefs: dict, out_path: Path):
    """Forest plot of log_analyst / institutions_pct t-stats across 3 panel specs."""
    specs = ["analyst_only", "inst_only", "joint"]
    varnames = ["log_analyst", "institutions_pct"]
    fig, ax = plt.subplots(1, 1, figsize=(7, 4))
    y_pos = []
    labels = []
    tstats = []
    colors = []
    for i, spec in enumerate(specs):
        sp = panel_coefs[spec]
        for v in varnames:
            if v in sp["coefs"]:
                labels.append(f"{spec}: {v}")
                tstats.append(sp["coefs"][v]["t"])
                y_pos.append(len(y_pos))
                colors.append("tab:blue" if v == "log_analyst" else "tab:red")
    ax.barh(y_pos, tstats, color=colors, alpha=0.7, edgecolor="black")
    ax.axvline(0, color="grey", lw=0.8)
    ax.axvline(2, color="green", lw=0.8, ls=":", label="|t|=2")
    ax.axvline(3, color="red", lw=0.8, ls="--", label="Harvey |t|=3")
    ax.axvline(-2, color="green", lw=0.8, ls=":")
    ax.axvline(-3, color="red", lw=0.8, ls="--")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("t-statistic (HC0 robust)")
    ax.set_title("K1165 panel OLS (θ_EAV_i ~ ... + market FE + log_mcap)\nN_stocks={}".format(
        panel_coefs["joint"]["n"]))
    ax.legend(fontsize=8)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# =========================================================================
# Main
# =========================================================================
def main():
    print("\n" + "=" * 72)
    print("K1165: N=7 markets (TW, EU, JP, US + KR, CA, HK) cross-market test")
    print("=" * 72 + "\n")

    # 1. Load pooled_new
    pooled_new = json.load(open(ROOT / "k1165_pooled_by_market.json"))
    # 2. Build panel
    panel, inst_mean_by_mkt = build_panel()
    print(f"[panel] rows: {len(panel)} — {panel['market'].value_counts().to_dict()}\n")

    # 3. Per-market summary table
    gb = panel.groupby("market")
    summary = gb.agg(
        n=("ticker", "count"),
        theta_eav_mean=("theta_eav", "mean"),
        theta_eav_median=("theta_eav", "median"),
        sigma2_sample_mean=("sigma2_sample", "mean"),
        analyst_median=("analyst_count", "median"),
        market_cap_median=("market_cap", "median"),
        log_mcap_median=("log_mcap", "median"),
    )
    # Use ALL-fetched institutions_pct (not just stocks in panel) for market means
    summary["institutions_pct_mean"] = [
        float(np.mean(inst_mean_by_mkt.get(m, [np.nan]))) for m in summary.index]
    summary["institutions_pct_median"] = [
        float(np.median(inst_mean_by_mkt.get(m, [np.nan]))) for m in summary.index]

    # 4. Compute θ_rel for new markets
    mean_sigma2_panel = summary["sigma2_sample_mean"].to_dict()
    theta_rel = compute_theta_rel(pooled_new, mean_sigma2_panel)
    # Add pooled θ_EAV info
    pooled_eav = {}
    for m in summary.index:
        if m in LEGACY_POOLED_THETA_EAV:
            pooled_eav[m] = LEGACY_POOLED_THETA_EAV[m]
        elif m in pooled_new:
            pooled_eav[m] = {
                "theta_eav": pooled_new[m].get("theta_eav"),
                "theta_eav_t": pooled_new[m].get("theta_eav_t_hessian"),
                "source": "K1165",
            }
    summary["pooled_theta_eav"] = [pooled_eav[m]["theta_eav"] for m in summary.index]
    summary["pooled_theta_eav_t"] = [pooled_eav[m]["theta_eav_t"] for m in summary.index]
    summary["theta_rel"] = [theta_rel[m] for m in summary.index]

    print("Per-market summary:\n" + summary.to_string())

    # 5. Cross-market Spearman (N=7)
    markets_sorted = list(summary.index)
    xs_inst = [summary.loc[m, "institutions_pct_mean"] for m in markets_sorted]
    xs_analyst = [summary.loc[m, "analyst_median"] for m in markets_sorted]
    xs_mcap = [summary.loc[m, "log_mcap_median"] for m in markets_sorted]
    ys_thr = [theta_rel[m] for m in markets_sorted]

    cm_spearman = {
        "institutions_pct_vs_theta_rel": dict(zip(
            ["rho", "p", "n"], spearman_with_p(xs_inst, ys_thr))),
        "analyst_median_vs_theta_rel": dict(zip(
            ["rho", "p", "n"], spearman_with_p(xs_analyst, ys_thr))),
        "log_mcap_median_vs_theta_rel": dict(zip(
            ["rho", "p", "n"], spearman_with_p(xs_mcap, ys_thr))),
        "markets_ordered": markets_sorted,
        "theta_rel_values": ys_thr,
        "institutions_pct_mean_values": xs_inst,
        "analyst_median_values": xs_analyst,
    }
    print("\nCross-market Spearman (N=7):")
    for k, v in cm_spearman.items():
        if isinstance(v, dict) and "rho" in v:
            print(f"  {k}: ρ={v['rho']:+.3f}, p={v['p']:.3f}, n={v['n']}")

    # 6. Per-stock panel OLS (N=?, market FE + log_mcap)
    # Only use stocks with converged theta_eav + analyst_count + institutions_pct
    panel_valid = panel.dropna(subset=["theta_eav", "log_analyst", "log_mcap",
                                       "institutions_pct"]).copy()
    print(f"\n[panel_valid] n={len(panel_valid)}  — markets: "
          f"{panel_valid['market'].value_counts().to_dict()}")
    specs = {
        "analyst_only": panel_ols(panel_valid, "theta_eav",
                                  ["log_analyst", "log_mcap"]),
        "inst_only":    panel_ols(panel_valid, "theta_eav",
                                  ["institutions_pct", "log_mcap"]),
        "joint":        panel_ols(panel_valid, "theta_eav",
                                  ["log_analyst", "institutions_pct",
                                   "log_mcap"]),
    }
    print("\nPanel OLS (market FE + log_mcap):")
    for name, r in specs.items():
        print(f"  {name}: R²={r['r2']:.3f}, n={r['n']}")
        for c, cc in r["coefs"].items():
            if not c.startswith("D_"):
                print(f"    {c}: β={cc['beta']:+.3e}, t={cc['t']:+.2f}, p={cc['p']:.3f}")

    # 7. Within-market Pearson
    dm = demean_within(panel_valid, ["log_analyst", "institutions_pct",
                                     "log_mcap", "theta_eav"])
    within_corr = {
        "log_analyst_x_theta_eav": dict(zip(
            ["r", "p", "n"], pearson_with_p(dm["log_analyst_dm"], dm["theta_eav_dm"]))),
        "institutions_pct_x_theta_eav": dict(zip(
            ["r", "p", "n"], pearson_with_p(dm["institutions_pct_dm"], dm["theta_eav_dm"]))),
        "log_analyst_x_institutions_pct": dict(zip(
            ["r", "p", "n"], pearson_with_p(dm["log_analyst_dm"], dm["institutions_pct_dm"]))),
    }
    print("\nWithin-market (demeaned) Pearson:")
    for k, v in within_corr.items():
        print(f"  {k}: r={v['r']:+.3f}, p={v['p']:.3f}, n={v['n']}")

    # 8. Two-level decomposition
    two_level = two_level_decomposition(
        panel_valid, y_col="theta_eav",
        between_cols=["institutions_pct", "log_analyst", "log_mcap"],
        within_cols=["log_analyst", "institutions_pct", "log_mcap"])
    print("\nTwo-level R² decomposition:")
    print(f"  between-market (N={two_level['N_markets_between']}):",
          two_level["between_market_r2"])
    print(f"  within-market  (N={two_level['N_stocks_within']}):",
          two_level["within_market_r2"])

    # 9. Per-market within-market Spearman
    wm = {}
    for m, sub in panel_valid.groupby("market"):
        wm[m] = {
            "N": len(sub),
            "rho_analyst": dict(zip(
                ["rho", "p", "n"], spearman_with_p(sub["log_analyst"], sub["theta_eav"]))),
            "rho_inst_pct": dict(zip(
                ["rho", "p", "n"], spearman_with_p(sub["institutions_pct"], sub["theta_eav"]))),
        }

    # 10. Verdict
    inst_rho = cm_spearman["institutions_pct_vs_theta_rel"]["rho"]
    inst_p = cm_spearman["institutions_pct_vs_theta_rel"]["p"]
    analyst_rho = cm_spearman["analyst_median_vs_theta_rel"]["rho"]

    if inst_rho > 0.7 and inst_p < 0.05:
        verdict = "CONFIRMED"
        narrative = ("institutions_pct Spearman ρ > 0.7 with p < 0.05 at N=7. "
                     "K1167 two-level mechanism strengthened. Paper 2 §5 ready.")
    elif inst_rho > 0.5 and inst_p < 0.10:
        verdict = "STRENGTHENED"
        narrative = ("Direction and magnitude consistent with K1167, but p does "
                     "not reach 0.05 at N=7. Supportive; not yet fully confirmed.")
    elif inst_rho > 0.5:
        verdict = "PARTIAL"
        narrative = ("Direction consistent (ρ>+0.5) but p too weak at N=7. "
                     "Need N≥10 markets for confirmation.")
    elif inst_rho > 0:
        verdict = "WEAKENED"
        narrative = ("Direction still positive but ρ drops below 0.5. K1167 "
                     "signal weaker at N=7 than at N=4; partial support only.")
    else:
        verdict = "REJECTED"
        narrative = ("Cross-market institutional ownership hypothesis "
                     "contradicted at N=7 (ρ<=0). K1167 preliminary finding "
                     "did not replicate. Mechanism returns to OPEN.")

    print(f"\n===== VERDICT: {verdict} =====")
    print(narrative)

    # Self-challenge per Preamble Rule #5
    rho_abs = abs(inst_rho)
    self_challenge = None
    if rho_abs > 0.95:
        self_challenge = (
            f"⚠️ ρ={inst_rho:+.3f} exceeds 0.95 at N=7. Even with 7 markets, "
            f"a perfect or near-perfect ranking could reflect cherry-picked "
            f"market inclusion. Sensitivity: check what happens dropping each "
            f"market one at a time (leave-one-out)."
        )

    # Leave-one-out sensitivity
    loo = {}
    for drop_m in markets_sorted:
        sub_markets = [m for m in markets_sorted if m != drop_m]
        xs = [summary.loc[m, "institutions_pct_mean"] for m in sub_markets]
        ys = [theta_rel[m] for m in sub_markets]
        rho, p, _ = spearman_with_p(xs, ys)
        loo[drop_m] = {"rho": rho, "p": p, "n": len(sub_markets)}
    print("\nLeave-one-out (drop each market):")
    for m, r in loo.items():
        print(f"  drop {m}: ρ={r['rho']:+.3f}, p={r['p']:.3f}")

    # 11. Figures
    plot_8market_scatter(summary, theta_rel,
                         ROOT / "k1165_cross_market_scatter.png")
    plot_panel_forest(specs, ROOT / "k1165_panel_forest.png")
    print(f"\n[figures] wrote cross_market_scatter.png + panel_forest.png")

    # 12. Save panel CSV
    panel_valid.to_csv(ROOT / "k1165_per_stock_table.csv", index=False)
    print(f"[csv] wrote k1165_per_stock_table.csv  (n={len(panel_valid)})")

    # 13. Save results JSON
    results = {
        "experiment_id": "K1165",
        "title": "N=7 cross-market confirmation of K1167 two-level "
                 "institutional-ownership + analyst-coverage mechanism",
        "proposer": "Claude (K1167 next_tasks K1165/K1168 extension)",
        "executor": "Claude",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": 42,
        "markets_intended": ["TW", "EU", "JP", "US", "KR", "CA", "HK", "AU"],
        "markets_used": markets_sorted,
        "markets_dropped": {"AU": "yfinance get_earnings_dates returns only future "
                                  "dates / <=3 past for ASX; per-stock MLE "
                                  "requires >=15 events"},
        "data_sources": [
            "experiments/k1166/k1166_per_stock_table.csv (TW/EU/JP/US θ_EAV_i)",
            "experiments/k1167/data/institutional_ownership.json (TW/EU/JP/US inst_pct)",
            "experiments/k1145/1147/1150/1153 pooled θ_EAV",
            "k1165_fetch.py yfinance (KR, CA, HK, AU) prices + earnings + "
            "major_holders + info.analyst_count",
            "K1152/K1153 documented θ_rel (TW 0.17, EU 0.14, JP 0.39, US 0.59)",
        ],
        "per_market_summary": summary.reset_index().to_dict(orient="records"),
        "theta_rel": theta_rel,
        "pooled_theta_eav": pooled_eav,
        "cross_market_spearman_N7": cm_spearman,
        "leave_one_out_sensitivity": loo,
        "panel_ols": specs,
        "within_market_pearson_demeaned": within_corr,
        "two_level_decomposition": two_level,
        "per_market_within_spearman": wm,
        "verdict": verdict,
        "verdict_narrative": narrative,
        "self_challenge_preamble_rule_5": self_challenge,
        "notes": {
            "hk_stocks_used": 5,
            "hk_stocks_total_fetched": 10,
            "hk_skipped_due_to_low_earnings": ["1299.HK", "0941.HK", "0883.HK",
                                                "0016.HK", "1109.HK"],
            "au_market_dropped_reason": "yfinance earnings coverage insufficient",
        },
    }
    with open(ROOT / "k1165_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[json] wrote k1165_results.json")

    return results


if __name__ == "__main__":
    main()
