#!/usr/bin/env python3
"""K1172 — N>=13 ladder extension of K1168 cross-market test (MX + ZA + ID added).

Extends K1168 (N=10: TW/EU/JP/US/KR/CA/HK/BR/CH/IN) with 3 new markets:
 - MX (Bolsa Mexicana de Valores top 10; earnings n_events 27-88)
 - ZA (JSE Top 40 subset top 10; **UNDERPOWERED** — yfinance returns 0-4
   earnings dates for JSE tickers, all 10 dropped from >=15 events filter)
 - ID (IDX Composite large-caps top 10; earnings n_events 59-82)

So the EFFECTIVE extension is +2 markets (MX, ID) -> N=12, not N=13.
ZA is flagged as UNDERPOWERED per brief: "若某 market 不到 8 stocks
convergence -> clearly state UNDERPOWERED, don't force-fit".

Tests (same K1168 spec, fair comparison):
1. Cross-market Spearman rho(institutions_pct_mean, theta_rel)
2. Cross-market Spearman rho(analyst_median, theta_rel)
3. Cross-market Spearman rho(log_mcap_median, theta_rel)
4. Per-stock panel OLS with market FE + log_mcap (N ~= 170-175 stocks)
5. Within-market demeaned Pearson
6. Two-level R^2 decomposition (between-market N=12 vs within-market)
7. Leave-one-out sensitivity

Delta table: N=10 (K1168) vs N=12 (K1172).

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
K1168_ROOT = ROOT.parent / "k1168"
K1168_DATA = K1168_ROOT / "data"

# Legacy documented theta_rel (K1152/K1153)
LEGACY_THETA_REL: dict[str, float] = {"TW": 0.17, "EU": 0.14, "JP": 0.39, "US": 0.59}

LEGACY_POOLED_THETA_EAV: dict[str, dict] = {
    "TW": {"theta_eav": 6.362e-05, "theta_eav_t": 14.14, "source": "K1145"},
    "US": {"theta_eav": 1.909e-04, "theta_eav_t": 22.39, "source": "K1147"},
    "JP": {"theta_eav": 1.413e-04, "theta_eav_t": 20.16, "source": "K1150"},
    "EU": {"theta_eav": 4.072e-05, "theta_eav_t": 10.03, "source": "K1153"},
}


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


def demean_within(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c + "_dm"] = out.groupby("market")[c].transform(lambda x: x - x.mean())
    return out


def two_level_decomposition(df: pd.DataFrame, y_col: str,
                            between_cols: list[str], within_cols: list[str]) -> dict:
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
# Build combined N=12 panel
# =========================================================================
def build_panel() -> tuple[pd.DataFrame, dict, list[str], list[str]]:
    """Union of K1168 N=10 pool + K1172 new markets (MX, ID) — ZA dropped.

    K1168 pool = K1166(TW/EU/JP/US) + K1165(KR/CA/HK) + K1168(BR/CH/IN).
    K1172 pool = MX + ID (ZA UNDERPOWERED).
    """
    # --- K1166 TW/EU/JP/US ---
    k1166 = pd.read_csv(K1168_DATA / "k1166_per_stock_table.csv")
    k1166 = k1166[k1166["converged"].astype(bool)].copy()
    k1167 = json.load(open(K1168_DATA / "institutional_ownership_k1167.json"))
    ip_map: dict[str, float | None] = {}
    for rec in k1167["records"]:
        mh = rec.get("major_holders") or {}
        ip_map[rec["ticker"]] = mh.get("institutionsPercentHeld")
    k1166["institutions_pct"] = k1166["ticker"].map(lambda t: ip_map.get(t))

    # --- K1165 new (KR/CA/HK) ---
    k1165_new = pd.read_csv(K1168_DATA / "k1165_per_stock_table_newmkts.csv")
    k1165_new = k1165_new[k1165_new["converged"].astype(bool)].copy()

    # --- K1168 new (BR/CH/IN) ---
    k1168_new = pd.read_csv(K1168_ROOT / "k1168_per_stock_table_newmkts.csv")
    k1168_new = k1168_new[k1168_new["converged"].astype(bool)].copy()

    # --- K1172 new (MX, ID) ---
    k1172_new = pd.read_csv(ROOT / "k1172_per_stock_table_newmkts.csv")
    k1172_new = k1172_new[k1172_new["converged"].astype(bool)].copy()

    keep_cols = ["market", "ticker", "theta_eav", "theta_eav_t", "theta_eav_se",
                 "sigma2_sample", "analyst_count", "market_cap",
                 "institutions_pct", "n_obs", "n_events"]

    panel = pd.concat([
        k1166[keep_cols].assign(source="K1166"),
        k1165_new[keep_cols].assign(source="K1165"),
        k1168_new[keep_cols].assign(source="K1168"),
        k1172_new[keep_cols].assign(source="K1172"),
    ], ignore_index=True)
    panel["log_analyst"] = np.log(panel["analyst_count"].astype(float) + 1.0)
    panel["log_mcap"] = np.log(panel["market_cap"].astype(float))

    # Per-market institutional means from ALL fetched records
    inst_mean_by_mkt: dict[str, list[float]] = {}
    for rec in k1167["records"]:
        mh = rec.get("major_holders") or {}
        v = mh.get("institutionsPercentHeld")
        if v is not None:
            inst_mean_by_mkt.setdefault(rec["market"], []).append(float(v))
    ih_k1165 = json.load(open(K1168_DATA / "institutional_ownership_new.json"))
    for rec in ih_k1165["records"]:
        mh = rec.get("major_holders") or {}
        v = mh.get("institutionsPercentHeld")
        if v is not None:
            inst_mean_by_mkt.setdefault(rec["market"], []).append(float(v))
    ih_k1168 = json.load(open(K1168_DATA / "institutional_ownership_k1168.json"))
    for rec in ih_k1168["records"]:
        mh = rec.get("major_holders") or {}
        v = mh.get("institutionsPercentHeld")
        if v is not None:
            inst_mean_by_mkt.setdefault(rec["market"], []).append(float(v))
    ih_k1172 = json.load(open(DATA / "institutional_ownership_k1172.json"))
    for rec in ih_k1172["records"]:
        mh = rec.get("major_holders") or {}
        v = mh.get("institutionsPercentHeld")
        if v is not None:
            inst_mean_by_mkt.setdefault(rec["market"], []).append(float(v))

    # Record which K1172 markets actually converged pooled
    pooled_k1172 = json.load(open(ROOT / "k1172_pooled_by_market.json"))
    k1172_converged = [m for m in ("MX", "ZA", "ID")
                       if isinstance(pooled_k1172.get(m), dict)
                       and pooled_k1172[m].get("converged")]
    k1172_dropped = [m for m in ("MX", "ZA", "ID") if m not in k1172_converged]
    return panel, inst_mean_by_mkt, k1172_converged, k1172_dropped


# =========================================================================
# theta_rel per market
# =========================================================================
def compute_theta_rel(pooled_k1165: dict, pooled_k1168: dict, pooled_k1172: dict,
                      mean_sigma2_panel: dict[str, float]) -> dict[str, float]:
    out = dict(LEGACY_THETA_REL)
    for m in ("KR", "CA", "HK"):
        v = pooled_k1165.get(m)
        if isinstance(v, dict) and v.get("converged"):
            s2 = mean_sigma2_panel.get(m)
            if s2 and s2 > 0:
                out[m] = float(v["theta_eav"] / s2)
    for m in ("BR", "CH", "IN"):
        v = pooled_k1168.get(m)
        if isinstance(v, dict) and v.get("converged"):
            s2 = mean_sigma2_panel.get(m)
            if s2 and s2 > 0:
                out[m] = float(v["theta_eav"] / s2)
    for m in ("MX", "ZA", "ID"):
        v = pooled_k1172.get(m)
        if isinstance(v, dict) and v.get("converged"):
            s2 = mean_sigma2_panel.get(m)
            if s2 and s2 > 0:
                out[m] = float(v["theta_eav"] / s2)
    return out


# =========================================================================
# Plots
# =========================================================================
def plot_ladder_scatter(market_summary: pd.DataFrame, theta_rel: dict,
                        out_path: Path, spearman_inst: tuple,
                        spearman_analyst: tuple, n_markets: int):
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))
    colors = {"TW": "tab:blue", "US": "tab:red", "JP": "tab:green",
              "EU": "tab:orange", "KR": "tab:purple", "CA": "tab:brown",
              "HK": "tab:pink", "BR": "darkgoldenrod", "CH": "crimson",
              "IN": "teal", "MX": "goldenrod", "ID": "mediumseagreen"}

    markets = sorted(theta_rel.keys())
    ys = [theta_rel[m] for m in markets]

    # Left: institutions_pct vs theta_rel
    ax = axes[0]
    xs = [market_summary.loc[m, "institutions_pct_mean"] for m in markets]
    for m, x, y in zip(markets, xs, ys):
        ax.scatter(x, y, s=140, color=colors.get(m, "gray"),
                   edgecolor="black", label=m)
        ax.annotate(m, (x, y), textcoords="offset points", xytext=(8, 3),
                    fontsize=10, fontweight="bold")
    rho, p, n = spearman_inst
    ax.set_xlabel("Mean institutional ownership %")
    ax.set_ylabel(r"Market $\theta_{rel}$")
    ax.set_title(f"N={n}: institutions_pct vs theta_rel "
                 f"(rho={rho:+.3f}, p={p:.4f})")
    ax.grid(alpha=0.3)

    ax = axes[1]
    xs2 = [market_summary.loc[m, "analyst_median"] for m in markets]
    for m, x, y in zip(markets, xs2, ys):
        ax.scatter(x, y, s=140, color=colors.get(m, "gray"),
                   edgecolor="black", label=m)
        ax.annotate(m, (x, y), textcoords="offset points", xytext=(8, 3),
                    fontsize=10, fontweight="bold")
    rho2, p2, _ = spearman_analyst
    ax.set_xlabel("Median analyst count")
    ax.set_ylabel(r"Market $\theta_{rel}$")
    ax.set_title(f"N={spearman_analyst[2]}: analyst_median vs theta_rel "
                 f"(rho={rho2:+.3f}, p={p2:.4f})")
    ax.grid(alpha=0.3)

    fig.suptitle(
        f"K1172: N={n_markets} market cross-sectional test "
        "(K1168 N=10 + MX + ID; ZA dropped UNDERPOWERED)",
        fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_delta_barplot(k1168_vs_k1172: dict, out_path: Path):
    """Side-by-side barplot K1168 N=10 vs K1172 N=12 on primary metrics."""
    metrics = ["spearman_inst_rho", "spearman_inst_p",
               "drop_eu_rho", "panel_analyst_t",
               "between_r2_inst", "within_r2_analyst"]
    labels = ["Spearman rho\n(inst_pct)", "Spearman p\n(inst_pct)",
              "Drop-EU LOO rho", "Panel t\n(log_analyst)",
              "Between R2\n(inst_pct)", "Within R2\n(log_analyst)"]
    k1168_v = [k1168_vs_k1172["k1168"][m] for m in metrics]
    k1172_v = [k1168_vs_k1172["k1172"][m] for m in metrics]
    x = np.arange(len(metrics))
    w = 0.35
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(x - w/2, k1168_v, w, label=f"K1168 N={k1168_vs_k1172['k1168']['N']}",
           color="tab:gray", edgecolor="black")
    ax.bar(x + w/2, k1172_v, w, label=f"K1172 N={k1168_vs_k1172['k1172']['N']}",
           color="tab:blue", edgecolor="black")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=0, fontsize=9)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("K1172 vs K1168 — delta on cross-market metrics")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    for xi, v in zip(x - w/2, k1168_v):
        ax.annotate(f"{v:+.2f}" if abs(v) >= 0.01 else f"{v:.3f}",
                    (xi, v), textcoords="offset points", xytext=(0, 3),
                    ha="center", fontsize=8)
    for xi, v in zip(x + w/2, k1172_v):
        ax.annotate(f"{v:+.2f}" if abs(v) >= 0.01 else f"{v:.3f}",
                    (xi, v), textcoords="offset points", xytext=(0, 3),
                    ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_panel_forest(panel_coefs: dict, out_path: Path):
    specs = ["analyst_only", "inst_only", "joint"]
    varnames = ["log_analyst", "institutions_pct"]
    fig, ax = plt.subplots(1, 1, figsize=(8, 4.5))
    y_pos = []; labels = []; tstats = []; colors = []
    for spec in specs:
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
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("t-statistic (HC0 robust)")
    ax.set_title(f"K1172 panel OLS (theta_EAV_i ~ ... + market FE + log_mcap)\n"
                 f"N_stocks={panel_coefs['joint']['n']}")
    ax.legend(fontsize=9)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


# =========================================================================
# Main
# =========================================================================
def main():
    print("\n" + "=" * 72)
    print("K1172: N>=13 cross-market ladder extension (+MX/ZA/ID over K1168)")
    print("=" * 72 + "\n")

    pooled_k1165 = json.load(open(K1168_DATA / "k1165_pooled_by_market.json"))
    pooled_k1168 = json.load(open(K1168_ROOT / "k1168_pooled_by_market.json"))
    pooled_k1172 = json.load(open(ROOT / "k1172_pooled_by_market.json"))

    panel, inst_mean_by_mkt, k1172_converged, k1172_dropped = build_panel()
    print(f"[panel] rows: {len(panel)} - {panel['market'].value_counts().to_dict()}")
    print(f"[K1172 new converged]: {k1172_converged}")
    print(f"[K1172 new dropped]: {k1172_dropped}")
    if "ZA" in k1172_dropped:
        print("  -> ZA dropped: yfinance earnings coverage for JSE Top 40 is 0-4 "
              "events per ticker, all 10 fell below >=15 filter. UNDERPOWERED.")

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
    summary["institutions_pct_mean"] = [
        float(np.mean(inst_mean_by_mkt.get(m, [np.nan]))) for m in summary.index]
    summary["institutions_pct_median"] = [
        float(np.median(inst_mean_by_mkt.get(m, [np.nan]))) for m in summary.index]

    mean_sigma2_panel = summary["sigma2_sample_mean"].to_dict()
    theta_rel = compute_theta_rel(pooled_k1165, pooled_k1168, pooled_k1172,
                                  mean_sigma2_panel)

    pooled_eav = {}
    for m in summary.index:
        if m in LEGACY_POOLED_THETA_EAV:
            pooled_eav[m] = LEGACY_POOLED_THETA_EAV[m]
        elif m in pooled_k1165 and isinstance(pooled_k1165[m], dict) \
                and pooled_k1165[m].get("converged"):
            pooled_eav[m] = {
                "theta_eav": pooled_k1165[m].get("theta_eav"),
                "theta_eav_t": pooled_k1165[m].get("theta_eav_t_hessian"),
                "source": "K1165",
            }
        elif m in pooled_k1168 and isinstance(pooled_k1168[m], dict) \
                and pooled_k1168[m].get("converged"):
            pooled_eav[m] = {
                "theta_eav": pooled_k1168[m].get("theta_eav"),
                "theta_eav_t": pooled_k1168[m].get("theta_eav_t_hessian"),
                "source": "K1168",
            }
        elif m in pooled_k1172 and isinstance(pooled_k1172[m], dict) \
                and pooled_k1172[m].get("converged"):
            pooled_eav[m] = {
                "theta_eav": pooled_k1172[m].get("theta_eav"),
                "theta_eav_t": pooled_k1172[m].get("theta_eav_t_hessian"),
                "source": "K1172",
            }
    summary["pooled_theta_eav"] = [
        pooled_eav.get(m, {}).get("theta_eav") for m in summary.index]
    summary["pooled_theta_eav_t"] = [
        pooled_eav.get(m, {}).get("theta_eav_t") for m in summary.index]
    summary["theta_rel"] = [theta_rel.get(m, float("nan")) for m in summary.index]

    print("\nPer-market summary:")
    print(summary.to_string())

    markets_in_test = [m for m in summary.index
                       if np.isfinite(summary.loc[m, "theta_rel"])
                       and np.isfinite(summary.loc[m, "institutions_pct_mean"])]
    markets_sorted = sorted(markets_in_test)

    xs_inst = [summary.loc[m, "institutions_pct_mean"] for m in markets_sorted]
    xs_analyst = [summary.loc[m, "analyst_median"] for m in markets_sorted]
    xs_mcap = [summary.loc[m, "log_mcap_median"] for m in markets_sorted]
    ys_thr = [theta_rel[m] for m in markets_sorted]

    sp_inst = spearman_with_p(xs_inst, ys_thr)
    sp_analyst = spearman_with_p(xs_analyst, ys_thr)
    sp_mcap = spearman_with_p(xs_mcap, ys_thr)

    cm_spearman = {
        "institutions_pct_vs_theta_rel": dict(zip(["rho", "p", "n"], sp_inst)),
        "analyst_median_vs_theta_rel": dict(zip(["rho", "p", "n"], sp_analyst)),
        "log_mcap_median_vs_theta_rel": dict(zip(["rho", "p", "n"], sp_mcap)),
        "markets_ordered": markets_sorted,
        "theta_rel_values": ys_thr,
        "institutions_pct_mean_values": xs_inst,
        "analyst_median_values": xs_analyst,
    }

    N_cross = sp_inst[2]
    print(f"\nCross-market Spearman (N={N_cross}):")
    for k, v in cm_spearman.items():
        if isinstance(v, dict) and "rho" in v:
            print(f"  {k}: rho={v['rho']:+.3f}, p={v['p']:.4f}, n={v['n']}")

    panel_valid = panel.dropna(subset=["theta_eav", "log_analyst", "log_mcap",
                                       "institutions_pct"]).copy()
    print(f"\n[panel_valid] n={len(panel_valid)} - markets: "
          f"{panel_valid['market'].value_counts().to_dict()}")
    specs = {
        "analyst_only": panel_ols(panel_valid, "theta_eav",
                                  ["log_analyst", "log_mcap"]),
        "inst_only": panel_ols(panel_valid, "theta_eav",
                               ["institutions_pct", "log_mcap"]),
        "joint": panel_ols(panel_valid, "theta_eav",
                           ["log_analyst", "institutions_pct", "log_mcap"]),
    }
    print("\nPanel OLS (market FE + log_mcap):")
    for name, r in specs.items():
        print(f"  {name}: R2={r['r2']:.3f}, n={r['n']}")
        for c, cc in r["coefs"].items():
            if not c.startswith("D_"):
                print(f"    {c}: beta={cc['beta']:+.3e}, t={cc['t']:+.2f}, p={cc['p']:.3f}")

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

    two_level = two_level_decomposition(
        panel_valid, y_col="theta_eav",
        between_cols=["institutions_pct", "log_analyst", "log_mcap"],
        within_cols=["log_analyst", "institutions_pct", "log_mcap"])
    print("\nTwo-level R2 decomposition:")
    print(f"  between-market (N={two_level['N_markets_between']}):",
          two_level["between_market_r2"])
    print(f"  within-market  (N={two_level['N_stocks_within']}):",
          two_level["within_market_r2"])

    wm = {}
    for m, sub in panel_valid.groupby("market"):
        wm[m] = {
            "N": len(sub),
            "rho_analyst": dict(zip(
                ["rho", "p", "n"], spearman_with_p(sub["log_analyst"], sub["theta_eav"]))),
            "rho_inst_pct": dict(zip(
                ["rho", "p", "n"], spearman_with_p(sub["institutions_pct"], sub["theta_eav"]))),
        }

    loo = {}
    for drop_m in markets_sorted:
        sub_markets = [m for m in markets_sorted if m != drop_m]
        xs = [summary.loc[m, "institutions_pct_mean"] for m in sub_markets]
        ys = [theta_rel[m] for m in sub_markets]
        rho, p, _ = spearman_with_p(xs, ys)
        loo[drop_m] = {"rho": rho, "p": p, "n": len(sub_markets)}
    print(f"\nLeave-one-out (drop each market, N={N_cross-1} each):")
    for m, r in loo.items():
        print(f"  drop {m}: rho={r['rho']:+.3f}, p={r['p']:.4f}")

    inst_rho = cm_spearman["institutions_pct_vs_theta_rel"]["rho"]
    inst_p = cm_spearman["institutions_pct_vs_theta_rel"]["p"]

    if N_cross >= 10 and inst_rho > 0.7 and inst_p < 0.01:
        verdict = "CONFIRMED_1PCT"
        narrative = (f"institutions_pct Spearman rho={inst_rho:+.3f} at N={N_cross}, "
                     f"p={inst_p:.4f} < 0.01. K1167 two-level mechanism CONFIRMED at 1%. "
                     "Paper 2 Section 5 final-commit CONFIRMED narrative.")
    elif N_cross >= 10 and inst_rho > 0.5 and inst_p < 0.05:
        verdict = "CONFIRMED_5PCT"
        narrative = (f"institutions_pct Spearman rho={inst_rho:+.3f} at N={N_cross}, "
                     f"p={inst_p:.4f} < 0.05 but >= 0.01. CONFIRMED at 5% level. "
                     "Paper 2 Section 5 can commit CONFIRMED with sub-1% caveat.")
    elif inst_rho > 0.5 and inst_p < 0.10:
        verdict = "STRENGTHENED"
        narrative = (f"rho={inst_rho:+.3f}, p={inst_p:.4f} at N={N_cross}. Direction "
                     "consistent, borderline. Narrative stays STRENGTHENED (K1165/K1168 verdict).")
    elif inst_rho > 0.3 and inst_p < 0.20:
        verdict = "PARTIAL"
        narrative = (f"rho={inst_rho:+.3f}, p={inst_p:.4f} at N={N_cross}. "
                     "Direction positive but magnitude decayed — signal partial.")
    elif inst_rho > 0:
        verdict = "WEAKENED"
        narrative = (f"rho={inst_rho:+.3f} at N={N_cross}. Signal weakened as N grew.")
    else:
        verdict = "REGRESSED"
        narrative = (f"Negative or zero correlation at N={N_cross}. Mechanism "
                     "regressed with broader sample.")

    print(f"\n===== VERDICT: {verdict} =====")
    print(narrative)

    self_challenge = None
    if abs(inst_rho) > 0.95:
        self_challenge = (
            f"WARNING: rho={inst_rho:+.3f} exceeds 0.95 at N={N_cross}. "
            f"Possible selection effect; LOO must all stay positive.")

    plot_ladder_scatter(summary, theta_rel,
                        ROOT / "k1172_cross_market_scatter.png",
                        sp_inst, sp_analyst, N_cross)
    plot_panel_forest(specs, ROOT / "k1172_panel_forest.png")

    # Delta vs K1168
    try:
        k1168_res = json.load(open(K1168_ROOT / "k1168_results.json"))
        k1168_cm = k1168_res["cross_market_spearman"]
        k1168_inst_rho = k1168_cm["institutions_pct_vs_theta_rel"]["rho"]
        k1168_inst_p = k1168_cm["institutions_pct_vs_theta_rel"]["p"]
        k1168_N = k1168_cm["institutions_pct_vs_theta_rel"]["n"]
        k1168_drop_eu = k1168_res["leave_one_out_sensitivity"].get("EU", {}).get("rho", float("nan"))
        k1168_panel_analyst_t = k1168_res["panel_ols"]["joint"]["coefs"].get(
            "log_analyst", {}).get("t", float("nan"))
        k1168_between_inst = k1168_res["two_level_decomposition"]["between_market_r2"].get(
            "institutions_pct", float("nan"))
        k1168_within_analyst = k1168_res["two_level_decomposition"]["within_market_r2"].get(
            "log_analyst", float("nan"))
    except Exception as e:
        print(f"[warn] failed to load K1168 results for delta: {e}")
        k1168_inst_rho = 0.612; k1168_inst_p = 0.060; k1168_N = 10
        k1168_drop_eu = 0.750; k1168_panel_analyst_t = 3.63
        k1168_between_inst = 0.538; k1168_within_analyst = 0.062

    k1172_drop_eu = loo.get("EU", {}).get("rho", float("nan"))
    k1172_panel_analyst_t = specs["joint"]["coefs"].get("log_analyst", {}).get("t", float("nan"))
    k1172_between_inst = two_level["between_market_r2"].get("institutions_pct", float("nan"))
    k1172_within_analyst = two_level["within_market_r2"].get("log_analyst", float("nan"))

    delta = {
        "k1168": {
            "N": k1168_N,
            "spearman_inst_rho": k1168_inst_rho,
            "spearman_inst_p": k1168_inst_p,
            "drop_eu_rho": k1168_drop_eu,
            "panel_analyst_t": k1168_panel_analyst_t,
            "between_r2_inst": k1168_between_inst,
            "within_r2_analyst": k1168_within_analyst,
            "verdict": "STRENGTHENED",
        },
        "k1172": {
            "N": N_cross,
            "spearman_inst_rho": inst_rho,
            "spearman_inst_p": inst_p,
            "drop_eu_rho": k1172_drop_eu,
            "panel_analyst_t": k1172_panel_analyst_t,
            "between_r2_inst": k1172_between_inst,
            "within_r2_analyst": k1172_within_analyst,
            "verdict": verdict,
        },
        "delta_rho": inst_rho - k1168_inst_rho,
        "delta_p": inst_p - k1168_inst_p,
        "N_increase": N_cross - k1168_N,
    }
    plot_delta_barplot(delta, ROOT / "k1172_delta_vs_k1168.png")
    print("\n[figures] wrote scatter + panel_forest + delta_barplot")

    panel_valid.to_csv(ROOT / "k1172_per_stock_table.csv", index=False)
    print(f"[csv] wrote k1172_per_stock_table.csv (n={len(panel_valid)})")

    results = {
        "experiment_id": "K1172",
        "title": f"N={N_cross} cross-market extension of K1168 (MX/ID added; ZA UNDERPOWERED)",
        "proposer": "User/Claude (承接 K1168 STRENGTHENED verdict, next_tasks K1172)",
        "executor": "Claude (worktree agent)",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": 42,
        "markets_intended": ["TW", "EU", "JP", "US", "KR", "CA", "HK",
                             "BR", "CH", "IN", "MX", "ZA", "ID"],
        "markets_used": markets_sorted,
        "markets_dropped": {
            "ZA": "yfinance earnings coverage 0-4 events/ticker; all 10 below >=15 filter; UNDERPOWERED",
            "AU": "dropped in K1165 (yfinance earnings coverage)",
        },
        "N_cross_market": int(N_cross),
        "data_sources": [
            "experiments/k1166/k1166_per_stock_table.csv (TW/EU/JP/US theta_EAV_i)",
            "experiments/k1167/data/institutional_ownership.json (TW/EU/JP/US inst_pct)",
            "experiments/k1165/k1165_per_stock_table_newmkts.csv (KR/CA/HK)",
            "experiments/k1165/k1165_pooled_by_market.json",
            "experiments/k1168/k1168_per_stock_table_newmkts.csv (BR/CH/IN)",
            "experiments/k1168/k1168_pooled_by_market.json",
            "experiments/k1172/k1172_per_stock_table_newmkts.csv (MX/ID)",
            "experiments/k1172/k1172_pooled_by_market.json",
            "K1152/K1153 documented theta_rel (TW 0.17, EU 0.14, JP 0.39, US 0.59)",
        ],
        "per_market_summary": summary.reset_index().to_dict(orient="records"),
        "theta_rel": theta_rel,
        "pooled_theta_eav": pooled_eav,
        "cross_market_spearman": cm_spearman,
        "leave_one_out_sensitivity": loo,
        "panel_ols": specs,
        "within_market_pearson_demeaned": within_corr,
        "two_level_decomposition": two_level,
        "per_market_within_spearman": wm,
        "verdict": verdict,
        "verdict_narrative": narrative,
        "self_challenge_preamble_rule_5": self_challenge,
        "comparison_vs_k1168": delta,
        "k1172_new_markets_converged": k1172_converged,
        "k1172_new_markets_dropped": k1172_dropped,
        "za_underpowered_note": ("yfinance Ticker.get_earnings_dates returns 0-4 "
                                 "events per JSE ticker (NPN/BHG/AGL/SOL/MTN/SBK/"
                                 "FSR/ABG/SLM/CPI), all below the >=15 events "
                                 "filter. Per brief: UNDERPOWERED, not force-fit. "
                                 "Future K-number could use Alpha Vantage or FMP "
                                 "for JSE earnings."),
    }
    with open(ROOT / "k1172_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[json] wrote k1172_results.json")

    return results


if __name__ == "__main__":
    main()
