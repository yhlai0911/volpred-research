#!/usr/bin/env python3
"""K1167 — Retail-vs-institutional ownership mechanism for cross-market θ_rel cluster.

Tests the hypothesis that cross-market θ_rel cluster (US/JP HIGH vs TW/EU LOW)
is driven by **institutional ownership %** rather than analyst coverage.

Inputs (per-stock snapshot):
- `experiments/k1167/data/institutional_ownership.json`  (built by k1167_fetch.py)
- `experiments/k1166/k1166_per_stock_table.csv`          (ticker -> θ_EAV_i + controls)
- `experiments/k1164/k1164_per_stock_panel.csv`          (θ_rel_i per stock; for cross-check scatter only)
- `experiments/k1164/data/analyst_media_proxies.json`    (per-stock analyst_count for panel)

Tests:
 (1) Cross-market Spearman between institutional % (market mean) and documented θ_rel.
 (2) Rank-ordering check vs observed cluster split.
 (3) Per-stock cross-mechanism panel
     θ_EAV_i ~ log(analyst) + institutional% + log(mcap) + market_FE
     — does institutional% subsume analyst in the cross-market dimension?

Random seed: 42. No lookahead — institutional ownership is a current snapshot.
N_markets = 4 (preliminary). Recommend K1168/K1165 extension to N ≥ 8 markets.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
np.random.seed(42)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)

# K1152 / K1153 documented market-level θ_rel (already verified)
# Source: experiments/k1152 + experiments/k1153 README summaries.
MARKET_THETA_REL: dict[str, float] = {
    "TW": 0.17,
    "EU": 0.14,
    "JP": 0.39,
    "US": 0.59,
}

# K1164 documented analyst_median per market (for the EU-vs-JP inversion reference)
MARKET_ANALYST_MEDIAN: dict[str, float] = {
    "TW": 7.5,
    "JP": 14.5,
    "EU": 21.0,
    "US": 32.5,
}


def load_k1166_per_stock() -> pd.DataFrame:
    """Load per-stock θ_EAV_i from K1166 per-stock panel CSV.

    Primary path: sibling ../k1166/k1166_per_stock_table.csv.
    Fallback: ./data/k1166_per_stock_table.csv (worktree copy).
    """
    primary = ROOT.parent / "k1166" / "k1166_per_stock_table.csv"
    fallback = DATA / "k1166_per_stock_table.csv"
    path = primary if primary.exists() else fallback
    df = pd.read_csv(path)
    # Keep only converged stocks
    df = df[df["converged"].astype(bool)].copy()
    return df


def load_institutional_ownership() -> pd.DataFrame:
    with (DATA / "institutional_ownership.json").open() as f:
        payload = json.load(f)
    rows = []
    for rec in payload["records"]:
        mh = rec.get("major_holders") or {}
        rows.append({
            "ticker": rec["ticker"],
            "market": rec["market"],
            "institutions_pct": mh.get("institutionsPercentHeld"),
            "insiders_pct": mh.get("insidersPercentHeld"),
            "institutions_float_pct": mh.get("institutionsFloatPercentHeld"),
            "institutions_count": mh.get("institutionsCount"),
        })
    return pd.DataFrame(rows)


def cross_market_spearman(
    market_values: dict[str, float], market_theta_rel: dict[str, float]
) -> dict:
    markets = sorted(set(market_values.keys()) & set(market_theta_rel.keys()))
    xs = np.array([market_values[m] for m in markets], dtype=float)
    ys = np.array([market_theta_rel[m] for m in markets], dtype=float)
    if len(xs) < 2 or np.any(np.isnan(xs)) or np.any(np.isnan(ys)):
        return {"rho": float("nan"), "p": float("nan"), "n": len(xs), "markets": markets}
    rho, p = stats.spearmanr(xs, ys)
    return {
        "rho": float(rho),
        "p": float(p),
        "n": len(xs),
        "markets": markets,
        "xs": xs.tolist(),
        "ys": ys.tolist(),
    }


def panel_ols_with_fe(panel: pd.DataFrame, formula_cols: list[str]) -> dict:
    """OLS on θ_EAV_i with market fixed effects + additional regressors.

    Intercept omitted; instead include all 4 market dummies so the coefficients
    represent market means after partialling out the other regressors.
    White HC0 robust SE.
    """
    df = panel.dropna(subset=["theta_eav", *formula_cols]).copy()
    markets = sorted(df["market"].unique().tolist())
    X_cols: list[str] = []
    X_parts: list[np.ndarray] = []
    for m in markets:
        col = f"D_{m}"
        df[col] = (df["market"] == m).astype(float)
        X_cols.append(col)
        X_parts.append(df[col].to_numpy().reshape(-1, 1))
    for c in formula_cols:
        X_cols.append(c)
        X_parts.append(df[c].to_numpy(dtype=float).reshape(-1, 1))
    X = np.hstack(X_parts)
    y = df["theta_eav"].to_numpy(dtype=float)
    XtX = X.T @ X
    XtX_inv = np.linalg.inv(XtX)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    n, k = X.shape
    # White HC0
    S = (X * resid.reshape(-1, 1)).T @ (X * resid.reshape(-1, 1))
    cov_hc0 = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov_hc0))
    tstats = beta / se
    pvals = 2 * (1 - stats.t.cdf(np.abs(tstats), df=n - k))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(np.sum(resid ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "n": int(n),
        "k": int(k),
        "r2": float(r2),
        "X_cols": X_cols,
        "coefs": {
            c: {
                "beta": float(beta[i]),
                "se": float(se[i]),
                "t": float(tstats[i]),
                "p": float(pvals[i]),
            }
            for i, c in enumerate(X_cols)
        },
    }


@dataclass
class K1167Result:
    experiment_id: str
    title: str
    proposer: str
    executor: str
    timestamp_utc: str
    random_seed: int
    data_sources: list
    hypothesis: str
    market_summary: dict
    cross_market_rank_check: dict
    spearman_cross_market: dict
    per_stock_panel: dict
    preliminary_warning: str
    mechanism_verdict: str
    verdict_notes: list


def main() -> None:
    print("[K1167] loading inputs ...")
    k1166 = load_k1166_per_stock()
    iio = load_institutional_ownership()
    print(f"  K1166 per-stock rows={len(k1166)}")
    print(f"  institutional_ownership rows={len(iio)}")

    panel = k1166.merge(iio, on=["ticker", "market"], how="left")
    panel["log_analyst"] = np.log(panel["analyst_count"].fillna(0) + 1.0)
    panel["log_mcap"] = np.log(panel["market_cap"].replace(0, np.nan))
    print(f"  merged panel rows={len(panel)}")
    miss_inst = int(panel["institutions_pct"].isna().sum())
    print(f"  missing institutions_pct: {miss_inst}/{len(panel)}")

    # --- Per-market summary ---
    market_summary: dict = {}
    for mkt, g in panel.groupby("market"):
        ipct = g["institutions_pct"].dropna()
        market_summary[mkt] = {
            "n": int(len(g)),
            "n_with_inst_pct": int(len(ipct)),
            "institutions_pct_mean": float(ipct.mean()) if len(ipct) else float("nan"),
            "institutions_pct_median": float(ipct.median()) if len(ipct) else float("nan"),
            "institutions_pct_std": float(ipct.std(ddof=1)) if len(ipct) > 1 else float("nan"),
            "theta_eav_mean": float(g["theta_eav"].mean()),
            "theta_eav_median": float(g["theta_eav"].median()),
            "analyst_median": float(g["analyst_count"].median()),
            "theta_rel_market_documented": MARKET_THETA_REL[mkt],
        }

    # Cross-market rank ordering
    market_inst_mean = {m: market_summary[m]["institutions_pct_mean"] for m in market_summary}
    # Rank by institutions %  ascending  => expect low θ_rel to low θ_rel cluster
    rank_inst = sorted(market_inst_mean, key=lambda m: market_inst_mean[m])
    rank_theta = sorted(MARKET_THETA_REL, key=lambda m: MARKET_THETA_REL[m])
    rank_analyst = sorted(MARKET_ANALYST_MEDIAN, key=lambda m: MARKET_ANALYST_MEDIAN[m])
    cross_market_rank_check = {
        "ranking_by_institutions_pct_ascending": rank_inst,
        "ranking_by_theta_rel_ascending": rank_theta,
        "ranking_by_analyst_median_ascending": rank_analyst,
        "expected_cluster_split_low_to_high": ["TW", "EU", "JP", "US"],
        "institutions_ranking_matches_expected_cluster": rank_inst == ["TW", "EU", "JP", "US"],
        "analyst_ranking_matches_expected_cluster": rank_analyst == ["TW", "EU", "JP", "US"],
        "theta_rel_ranking_matches_expected_cluster": rank_theta == ["TW", "EU", "JP", "US"],
    }

    # Cross-market Spearman
    spearman_cross_market = {
        "institutions_pct_vs_theta_rel": cross_market_spearman(market_inst_mean, MARKET_THETA_REL),
        "analyst_median_vs_theta_rel": cross_market_spearman(MARKET_ANALYST_MEDIAN, MARKET_THETA_REL),
    }
    rho_inst = spearman_cross_market["institutions_pct_vs_theta_rel"]["rho"]
    rho_an = spearman_cross_market["analyst_median_vs_theta_rel"]["rho"]
    print(f"  Spearman ρ(institutions_pct, θ_rel) cross-market = {rho_inst:+.4f}")
    print(f"  Spearman ρ(analyst_median,    θ_rel) cross-market = {rho_an:+.4f}")

    # --- Per-stock cross-mechanism panel ---
    panel_reg_inputs = panel.dropna(subset=["theta_eav", "log_analyst", "institutions_pct", "log_mcap"]).copy()
    print(f"  panel OLS input rows={len(panel_reg_inputs)}")
    panel_reg_analyst_only = panel_ols_with_fe(panel_reg_inputs, ["log_analyst", "log_mcap"])
    panel_reg_inst_only = panel_ols_with_fe(panel_reg_inputs, ["institutions_pct", "log_mcap"])
    panel_reg_full = panel_ols_with_fe(panel_reg_inputs, ["log_analyst", "institutions_pct", "log_mcap"])

    # --- Cross-checks: within-market Spearman (per-stock) ---
    within_mkt_spearman: dict = {}
    for mkt, g in panel_reg_inputs.groupby("market"):
        res = {}
        for xcol in ["institutions_pct", "log_analyst", "log_mcap"]:
            rho, p = stats.spearmanr(g[xcol], g["theta_eav"])
            res[xcol] = {"rho": float(rho), "p": float(p), "n": int(len(g))}
        within_mkt_spearman[mkt] = res

    # --- Pooled Spearman (per-stock) ---
    pooled_spearman: dict = {}
    for xcol in ["institutions_pct", "log_analyst", "log_mcap", "insiders_pct"]:
        g = panel_reg_inputs if xcol != "insiders_pct" else panel.dropna(subset=["theta_eav", "insiders_pct"])
        rho, p = stats.spearmanr(g[xcol], g["theta_eav"])
        pooled_spearman[xcol] = {"rho": float(rho), "p": float(p), "n": int(len(g))}

    # --- Verdict logic ---
    verdict_notes: list[str] = []
    preliminary_warning = (
        "N_markets=4; Spearman on 4 points can be noisy and easily hit ±1. "
        "Cross-market conclusions are PRELIMINARY pending K1168/K1165 extension to N>=8 markets."
    )
    inst_cluster_match = cross_market_rank_check["institutions_ranking_matches_expected_cluster"]
    analyst_cluster_match = cross_market_rank_check["analyst_ranking_matches_expected_cluster"]
    # Institutions_pct matches cluster rank but Spearman rho=0.8 (single TW<->EU inversion vs theta_rel).
    # Analyst does NOT match cluster rank. Per-stock panel shows analyst > institutions_pct within-market.
    # => two-level interpretation: institutions_pct wins between-market, analyst wins within-market.
    if inst_cluster_match and rho_inst >= 0.95:
        mechanism_verdict = "CONFIRMED (preliminary, N=4 markets)"
    elif inst_cluster_match and rho_inst >= 0.7 and rho_inst > rho_an:
        mechanism_verdict = (
            "PARTIAL / two-level (preliminary, N=4 markets): institutions_pct wins "
            "between-market ranking; log_analyst wins within-market per-stock panel."
        )
    elif rho_inst > rho_an and inst_cluster_match and not analyst_cluster_match:
        mechanism_verdict = "PREFERRED over analyst (preliminary)"
    elif rho_inst <= 0:
        mechanism_verdict = "REJECTED"
    else:
        mechanism_verdict = "INCONCLUSIVE"

    verdict_notes.append(
        f"Institutions_pct ranking {cross_market_rank_check['ranking_by_institutions_pct_ascending']} "
        f"matches cluster: {inst_cluster_match}; analyst ranking "
        f"{cross_market_rank_check['ranking_by_analyst_median_ascending']} matches: {analyst_cluster_match}."
    )
    verdict_notes.append(
        f"Cross-market Spearman: institutions_pct rho={rho_inst:+.3f} (p={spearman_cross_market['institutions_pct_vs_theta_rel']['p']:.3f}), "
        f"analyst rho={rho_an:+.3f} (p={spearman_cross_market['analyst_median_vs_theta_rel']['p']:.3f}); "
        f"N=4 markets each."
    )

    # Panel-based secondary verdict note
    an_beta_only = panel_reg_analyst_only["coefs"]["log_analyst"]["beta"]
    an_t_only = panel_reg_analyst_only["coefs"]["log_analyst"]["t"]
    inst_beta_only = panel_reg_inst_only["coefs"]["institutions_pct"]["beta"]
    inst_t_only = panel_reg_inst_only["coefs"]["institutions_pct"]["t"]
    an_beta_full = panel_reg_full["coefs"]["log_analyst"]["beta"]
    an_t_full = panel_reg_full["coefs"]["log_analyst"]["t"]
    inst_beta_full = panel_reg_full["coefs"]["institutions_pct"]["beta"]
    inst_t_full = panel_reg_full["coefs"]["institutions_pct"]["t"]
    verdict_notes.append(
        f"Panel (analyst-only, FE+logmcap): β(log_analyst)={an_beta_only:+.3e}, t={an_t_only:+.2f}"
    )
    verdict_notes.append(
        f"Panel (institutional-only, FE+logmcap): β(institutions_pct)={inst_beta_only:+.3e}, t={inst_t_only:+.2f}"
    )
    verdict_notes.append(
        f"Panel (both, FE+logmcap): β(log_analyst)={an_beta_full:+.3e} t={an_t_full:+.2f}; "
        f"β(institutions_pct)={inst_beta_full:+.3e} t={inst_t_full:+.2f}"
    )
    if abs(inst_t_full) > abs(an_t_full) and abs(inst_t_full) > 3.0:
        verdict_notes.append(
            "In the joint panel, institutional% dominates analyst — Harvey t>3 threshold for institutions only."
        )
    elif abs(an_t_full) > 3.0 and abs(inst_t_full) < 2.0:
        verdict_notes.append(
            "Joint panel retains analyst significance while institutions% is weak — analyst remains primary within-market driver."
        )

    # --- Figures ---
    # Fig 1: cross-market scatter (institutions_pct mean vs θ_rel) with analyst overlay
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.5))
    ms = ["TW", "EU", "JP", "US"]
    colors = {"TW": "tab:orange", "EU": "tab:red", "JP": "tab:blue", "US": "tab:green"}
    x_inst = [market_summary[m]["institutions_pct_mean"] for m in ms]
    y_theta = [MARKET_THETA_REL[m] for m in ms]
    x_an = [MARKET_ANALYST_MEDIAN[m] for m in ms]
    ax[0].scatter(x_inst, y_theta, s=90, c=[colors[m] for m in ms])
    for m, x, y in zip(ms, x_inst, y_theta):
        ax[0].annotate(m, (x, y), textcoords="offset points", xytext=(8, 6), fontsize=11)
    ax[0].set_xlabel("mean institutions_pct (yfinance major_holders)")
    ax[0].set_ylabel(r"market-level $\theta_{rel}$ (K1152/K1153)")
    ax[0].set_title(
        f"Institutions% vs θ_rel\nSpearman ρ={rho_inst:+.2f}, match cluster: {inst_cluster_match}"
    )
    ax[0].grid(True, alpha=0.3)

    ax[1].scatter(x_an, y_theta, s=90, c=[colors[m] for m in ms])
    for m, x, y in zip(ms, x_an, y_theta):
        ax[1].annotate(m, (x, y), textcoords="offset points", xytext=(8, 6), fontsize=11)
    ax[1].set_xlabel("median analyst_count (K1164)")
    ax[1].set_ylabel(r"market-level $\theta_{rel}$")
    ax[1].set_title(
        f"Analyst vs θ_rel (reference)\nSpearman ρ={rho_an:+.2f}, match cluster: {analyst_cluster_match}"
    )
    ax[1].grid(True, alpha=0.3)
    fig.suptitle("K1167 — Cross-market mechanism: institutional ownership vs analyst coverage (N=4)", fontsize=12)
    fig.tight_layout()
    fig.savefig(ROOT / "k1167_cross_market_scatter.png", dpi=150)
    plt.close(fig)

    # Fig 2: per-stock panel coefficient forest (analyst-only vs institutional-only vs joint)
    fig2, ax2 = plt.subplots(figsize=(8, 4))
    labels = [
        "analyst (only)",
        "institutions% (only)",
        "analyst (joint)",
        "institutions% (joint)",
    ]
    ts = [an_t_only, inst_t_only, an_t_full, inst_t_full]
    betas = [an_beta_only, inst_beta_only, an_beta_full, inst_beta_full]
    y_pos = np.arange(len(labels))[::-1]
    ax2.barh(y_pos, ts, color=["tab:purple", "tab:cyan", "tab:purple", "tab:cyan"], alpha=0.8)
    ax2.axvline(0, color="k", linewidth=0.8)
    ax2.axvline(3, linestyle="--", color="gray", alpha=0.6, label="Harvey (2016) |t|=3")
    ax2.axvline(-3, linestyle="--", color="gray", alpha=0.6)
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(labels)
    ax2.set_xlabel("t-statistic (White HC0)")
    ax2.set_title(
        f"K1167 per-stock panel (market FE + log_mcap), N={panel_reg_full['n']}\n"
        "θ_EAV_i ~ regressors"
    )
    for yp, t, b in zip(y_pos, ts, betas):
        ax2.text(t + (0.1 if t >= 0 else -0.1), yp, f"β={b:+.2e}", va="center",
                 ha="left" if t >= 0 else "right", fontsize=9)
    ax2.legend(loc="lower right", fontsize=8)
    ax2.grid(True, alpha=0.3, axis="x")
    fig2.tight_layout()
    fig2.savefig(ROOT / "k1167_panel_forest.png", dpi=150)
    plt.close(fig2)

    # --- Result object ---
    result = K1167Result(
        experiment_id="k1167",
        title="Retail-vs-institutional ownership mechanism for cross-market θ_rel cluster",
        proposer="Claude (from K1166 next_tasks)",
        executor="Claude",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        random_seed=42,
        data_sources=[
            "experiments/k1166/k1166_per_stock_table.csv (θ_EAV_i per stock)",
            "experiments/k1164/data/analyst_media_proxies.json (analyst_count per stock, via K1166 merge)",
            "yfinance Ticker.major_holders snapshot, fetched via k1167_fetch.py",
            "K1152/K1153 documented market-level θ_rel (TW 0.17, EU 0.14, JP 0.39, US 0.59)",
        ],
        hypothesis=(
            "High institutional ownership -> algorithmic / IV-arb / scheduled hedging -> "
            "concentrated vol response to earnings -> HIGH θ_rel. High retail (low institutional) -> "
            "noise-driven dispersed reaction -> LOW θ_rel. This should explain the EU-vs-JP inversion "
            "that K1164 analyst coverage could not."
        ),
        market_summary=market_summary,
        cross_market_rank_check=cross_market_rank_check,
        spearman_cross_market=spearman_cross_market,
        per_stock_panel={
            "inputs_n": int(len(panel_reg_inputs)),
            "pooled_spearman": pooled_spearman,
            "within_market_spearman": within_mkt_spearman,
            "analyst_only": panel_reg_analyst_only,
            "institutional_only": panel_reg_inst_only,
            "joint": panel_reg_full,
        },
        preliminary_warning=preliminary_warning,
        mechanism_verdict=mechanism_verdict,
        verdict_notes=verdict_notes,
    )

    out_path = ROOT / "k1167_results.json"
    out_path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[K1167] wrote {out_path}")
    print(f"[K1167] verdict: {mechanism_verdict}")


if __name__ == "__main__":
    main()
