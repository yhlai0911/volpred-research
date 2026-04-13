"""K1164 — Analyst coverage x media-density mechanism test for cross-market θ_rel cluster.

Hypothesis (from K1153 Section 5.4):
    High analyst coverage + concentrated earnings-season media -> high θ_rel
    - US (analyst≈30+, CNBC concentration) + JP (analyst≈15, Nikkei concentration) -> HIGH cluster (θ_rel 0.39-0.59)
    - TW (analyst<10, diffuse) + EU (analyst≈20 but decentralised by country) -> LOW cluster (θ_rel 0.14-0.17)

Design:
    1. Per-stock θ_rel_i = θ_EAV_shared / σ²_i
       (θ_EAV shared across stocks within market; σ²_i = empirical variance of stock i's log-returns)
    2. Cross-market (N=4): Spearman(market_mean_analyst, market_θ_rel)
    3. Per-stock panel (N=109): regress θ_rel_i on log(analyst), log(market_cap), log(turnover) with market FE
    4. Verdict:
       - Spearman ρ > 0.7 cross-market AND panel analyst coef t > 2 -> mechanism CONFIRMED (preliminary; N=4 markets)
       - Otherwise REJECTED or INCONCLUSIVE

Inputs:
    experiments/k1145/k1145_results.json (TW)
    experiments/k1147/k1147_results.json (US)
    experiments/k1150/k1150_results.json (JP)
    experiments/k1153/k1153_results.json (EU)
    experiments/k1164/data/analyst_media_proxies.json

Outputs:
    experiments/k1164/k1164_results.json
    experiments/k1164/k1164_scatter.png
    experiments/k1164/k1164_bar_cluster.png

Lookahead discipline:
    - Analyst count is current yfinance snapshot (per-stock average over trailing 12M is not available at
      per-stock granularity without paid IBES; use current yfinance count as proxy for "analyst density").
    - market_cap is current snapshot; robustness sensitivity can use turnover median over full sample.
    - Random seed 42 for bootstrap rank tests.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

np.random.seed(42)

MAIN_REPO = Path("/Users/yhlai0911/Desktop/volpred-research")
THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"

MARKETS: dict[str, dict] = {
    "TW": {
        "source_json": MAIN_REPO / "experiments" / "k1145" / "k1145_results.json",
        "data_dir": MAIN_REPO / "experiments" / "k1145" / "data",
        "theta_rel_market": 0.16730150708150912,  # From K1152 results
        "cluster": "LOW",
    },
    "US": {
        "source_json": MAIN_REPO / "experiments" / "k1147" / "k1147_results.json",
        "data_dir": MAIN_REPO / "experiments" / "k1147" / "data",
        "theta_rel_market": 0.5862018842610842,
        "cluster": "HIGH",
    },
    "JP": {
        "source_json": MAIN_REPO / "experiments" / "k1150" / "k1150_results.json",
        "data_dir": MAIN_REPO / "experiments" / "k1150" / "data",
        "theta_rel_market": 0.3875023756698172,
        "cluster": "HIGH",
    },
    "EU": {
        "source_json": MAIN_REPO / "experiments" / "k1153" / "k1153_results.json",
        "data_dir": MAIN_REPO / "experiments" / "k1153" / "data",
        "theta_rel_market": 0.1370,  # From K1153 README (avg_σ² 2.98e-4, θ_EAV 4.07e-5)
        "cluster": "LOW",
    },
}


def load_k_experiment(market: str) -> dict:
    with open(MARKETS[market]["source_json"], "r") as f:
        return json.load(f)


def load_proxies() -> dict:
    with open(DATA_DIR / "analyst_media_proxies.json", "r") as f:
        return json.load(f)


def read_parquet_any(data_dir: Path, ticker: str) -> pd.DataFrame | None:
    candidates = [
        data_dir / f"{ticker}.parquet",
        data_dir / f"{ticker.replace('.', '_')}.parquet",
        data_dir / f"{ticker.replace('-', '_')}.parquet",
    ]
    for p in candidates:
        if p.exists():
            return pd.read_parquet(p)
    return None


def compute_stock_sigma2(data_dir: Path, ticker: str) -> float | None:
    """σ²_i = variance of daily log-returns over available history."""
    df = read_parquet_any(data_dir, ticker)
    if df is None or "Close" not in df.columns:
        return None
    close = df["Close"].dropna()
    if len(close) < 252:
        return None
    lret = np.log(close / close.shift(1)).dropna()
    return float(np.var(lret, ddof=1))


def build_per_stock_table() -> pd.DataFrame:
    """Build per-stock panel: ticker, market, analyst_count, market_cap, turnover, sigma2_i, theta_rel_i."""
    proxies = load_proxies()
    rows: list[dict] = []
    market_theta_eav: dict[str, float] = {}

    for market in ("TW", "US", "JP", "EU"):
        kr = load_k_experiment(market)
        mf = kr["main_fit_eav_window_1"]
        theta_eav_shared = float(mf["theta_eav"])
        market_theta_eav[market] = theta_eav_shared
        per_stock_tickers = mf.get("per_stock_tickers", [])
        data_dir = MARKETS[market]["data_dir"]

        # Build ticker->proxy lookup
        prox_lookup = {r["ticker"]: r for r in proxies[market]}

        for tk in per_stock_tickers:
            sigma2_i = compute_stock_sigma2(data_dir, tk)
            if sigma2_i is None or sigma2_i <= 0:
                continue
            p = prox_lookup.get(tk, {})
            rows.append({
                "market": market,
                "ticker": tk,
                "analyst_count": p.get("analyst_count"),
                "market_cap": p.get("market_cap"),
                "median_daily_turnover": p.get("median_daily_turnover"),
                "sigma2_i": sigma2_i,
                "theta_eav_shared": theta_eav_shared,
                "theta_rel_i": theta_eav_shared / sigma2_i,
            })
    df = pd.DataFrame(rows)
    return df


def market_level_summary(df_stock: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-market means of analyst, log(market_cap), log(turnover), theta_rel.
    Also append documented market-level θ_rel from K1152/K1153."""
    rows = []
    for market in ("TW", "US", "JP", "EU"):
        sub = df_stock[df_stock["market"] == market]
        rows.append({
            "market": market,
            "cluster": MARKETS[market]["cluster"],
            "n_stocks": int(len(sub)),
            "analyst_mean": float(sub["analyst_count"].mean(skipna=True)),
            "analyst_median": float(sub["analyst_count"].median(skipna=True)),
            "log_marketcap_mean": float(np.log(sub["market_cap"].dropna()).mean()),
            "log_turnover_mean": float(np.log(sub["median_daily_turnover"].dropna()).mean()),
            "theta_rel_market_docd": MARKETS[market]["theta_rel_market"],
            "theta_rel_stock_mean": float(sub["theta_rel_i"].mean()),
            "theta_rel_stock_median": float(sub["theta_rel_i"].median()),
        })
    return pd.DataFrame(rows)


def cross_market_spearman(summary: pd.DataFrame) -> dict:
    """Spearman rank correlation between market-mean proxies and market θ_rel (N=4 markets)."""
    results: dict = {}
    theta = summary["theta_rel_market_docd"].values
    for col in ("analyst_mean", "analyst_median", "log_marketcap_mean", "log_turnover_mean"):
        x = summary[col].values
        if len(x) < 3:
            continue
        rho, p = spearmanr(x, theta)
        # pearson for comparison
        r = float(np.corrcoef(x, theta)[0, 1])
        results[col] = {
            "spearman_rho": float(rho),
            "spearman_p_two_sided": float(p),
            "pearson_r": r,
            "n_markets": int(len(x)),
        }
    return results


def panel_regression(df_stock: pd.DataFrame) -> dict:
    """OLS with market fixed effects:
        theta_rel_i = α_TW*D_TW + α_US*D_US + α_JP*D_JP + α_EU*D_EU
                    + β1 * log(analyst_count + 1) + β2 * log(market_cap) + β3 * log(turnover) + ε
    Use HC (White) robust SE.
    """
    d = df_stock.dropna(subset=["analyst_count", "market_cap", "median_daily_turnover"]).copy()
    d = d[d["analyst_count"] > 0]
    d = d[d["market_cap"] > 0]
    d = d[d["median_daily_turnover"] > 0]

    d["log_analyst"] = np.log(d["analyst_count"])
    d["log_mcap"] = np.log(d["market_cap"])
    d["log_turnover"] = np.log(d["median_daily_turnover"])

    # market dummies
    markets = ("TW", "US", "JP", "EU")
    for m in markets:
        d[f"D_{m}"] = (d["market"] == m).astype(float)

    # Design matrix: 4 market FE + 3 continuous; no global intercept
    fe_cols = [f"D_{m}" for m in markets]
    cont_cols = ["log_analyst", "log_mcap", "log_turnover"]
    X_cols = fe_cols + cont_cols
    X = d[X_cols].values
    y = d["theta_rel_i"].values
    n, k = X.shape

    # OLS
    XtX = X.T @ X
    XtX_inv = np.linalg.inv(XtX)
    beta = XtX_inv @ X.T @ y
    y_hat = X @ beta
    resid = y - y_hat
    rss = float(np.sum(resid ** 2))
    tss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - rss / tss if tss > 0 else np.nan

    # HC0 robust SE (White)
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    cov_hc0 = XtX_inv @ S @ XtX_inv
    se_hc0 = np.sqrt(np.diag(cov_hc0))
    t_hc0 = beta / se_hc0

    out: dict = {
        "n_obs": int(n),
        "n_params": int(k),
        "r2": float(r2),
        "rss": rss,
        "tss": tss,
        "coefs": {},
    }
    for i, c in enumerate(X_cols):
        out["coefs"][c] = {
            "beta": float(beta[i]),
            "se_hc0": float(se_hc0[i]),
            "t_hc0": float(t_hc0[i]),
        }
    return out


def make_plots(summary: pd.DataFrame, df_stock: pd.DataFrame, out_dir: Path) -> list[str]:
    figures: list[str] = []

    # Plot 1: market-level analyst vs θ_rel scatter
    fig, ax = plt.subplots(figsize=(7, 5.5))
    colors = {"LOW": "#2E86AB", "HIGH": "#E63946"}
    for _, row in summary.iterrows():
        ax.scatter(row["analyst_median"], row["theta_rel_market_docd"],
                   s=260, color=colors[row["cluster"]], edgecolor="black", linewidth=1.5, zorder=3)
        ax.annotate(row["market"], (row["analyst_median"], row["theta_rel_market_docd"]),
                    textcoords="offset points", xytext=(10, 6), fontsize=13, fontweight="bold")
    ax.set_xlabel("Market-median analyst count (current)", fontsize=12)
    ax.set_ylabel(r"Market $\theta_\mathrm{rel}$ (from K1152/K1153)", fontsize=12)
    ax.set_title("K1164 — Cross-market analyst coverage vs θ_rel cluster", fontsize=13)
    ax.grid(alpha=0.3, zorder=0)
    # Legend
    ax.scatter([], [], color=colors["HIGH"], s=160, edgecolor="black", label="HIGH cluster (US/JP)")
    ax.scatter([], [], color=colors["LOW"], s=160, edgecolor="black", label="LOW cluster (TW/EU)")
    ax.legend(loc="upper left", fontsize=10)
    p1 = out_dir / "k1164_scatter.png"
    fig.tight_layout()
    fig.savefig(p1, dpi=150)
    plt.close(fig)
    figures.append(p1.name)

    # Plot 2: bar chart of θ_rel by cluster, overlaid with analyst_count bar
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))
    order = ["TW", "EU", "JP", "US"]
    sm = summary.set_index("market").loc[order]
    bar_colors = [colors[MARKETS[m]["cluster"]] for m in order]

    ax1.bar(order, sm["theta_rel_market_docd"], color=bar_colors, edgecolor="black")
    ax1.set_ylabel(r"$\theta_\mathrm{rel}$ = $\theta_\mathrm{EAV}$ / $\sigma^2$", fontsize=11)
    ax1.set_title("Market θ_rel (from K1152/K1153)", fontsize=12)
    ax1.grid(axis="y", alpha=0.3)
    for i, m in enumerate(order):
        ax1.text(i, sm.loc[m, "theta_rel_market_docd"] + 0.02,
                 f"{sm.loc[m, 'theta_rel_market_docd']:.3f}",
                 ha="center", fontsize=10)

    ax2.bar(order, sm["analyst_median"], color=bar_colors, edgecolor="black")
    ax2.set_ylabel("Median analyst count (current, yfinance)", fontsize=11)
    ax2.set_title("Market median analyst coverage", fontsize=12)
    ax2.grid(axis="y", alpha=0.3)
    for i, m in enumerate(order):
        ax2.text(i, sm.loc[m, "analyst_median"] + 0.5,
                 f"{sm.loc[m, 'analyst_median']:.1f}",
                 ha="center", fontsize=10)
    fig.suptitle("K1164 — θ_rel vs analyst coverage by market (ordered LOW→HIGH cluster)",
                 fontsize=12)
    p2 = out_dir / "k1164_bar_cluster.png"
    fig.tight_layout()
    fig.savefig(p2, dpi=150)
    plt.close(fig)
    figures.append(p2.name)

    return figures


def main() -> None:
    out_dir = THIS_DIR
    print("K1164 — Analyst × Media-density mechanism test")
    print("=" * 60)

    # 1. Build per-stock panel with θ_rel_i
    df_stock = build_per_stock_table()
    print(f"[panel] built: n_obs={len(df_stock)}")
    print(df_stock.groupby("market").agg(
        n=("ticker", "count"),
        theta_rel_mean=("theta_rel_i", "mean"),
        sigma2_mean=("sigma2_i", "mean"),
        analyst_mean=("analyst_count", "mean"),
    ).round(4))

    # 2. Market-level summary
    summary = market_level_summary(df_stock)
    print("\n[market summary]")
    print(summary.to_string(index=False))

    # 3. Cross-market Spearman (N=4)
    spearman = cross_market_spearman(summary)
    print("\n[cross-market Spearman (N=4)]")
    for k_, v in spearman.items():
        print(f"  {k_:20s}  ρ={v['spearman_rho']:+.4f}  p={v['spearman_p_two_sided']:.4f}  pearson={v['pearson_r']:+.4f}")

    # 4. Panel regression with market FE
    panel = panel_regression(df_stock)
    print(f"\n[panel regression] n_obs={panel['n_obs']}  r2={panel['r2']:.4f}")
    for c, v in panel["coefs"].items():
        print(f"  {c:15s}  β={v['beta']:+.6f}  se={v['se_hc0']:.6f}  t={v['t_hc0']:+.3f}")

    # 5. Verdict logic
    #   Primary: Spearman ρ(analyst_median, theta_rel) cross-market
    #   Secondary: panel log_analyst coef t-stat (with market FE absorbed)
    #   Tertiary: rank ordering check (does analyst rank replicate θ_rel cluster split?)
    primary_rho = spearman.get("analyst_median", {}).get("spearman_rho", np.nan)
    primary_p = spearman.get("analyst_median", {}).get("spearman_p_two_sided", np.nan)
    panel_coef = panel["coefs"].get("log_analyst", {})

    # Rank ordering check
    rank_by_analyst = summary.sort_values("analyst_median")["market"].tolist()
    rank_by_theta = summary.sort_values("theta_rel_market_docd")["market"].tolist()
    low_cluster = {"TW", "EU"}
    high_cluster = {"US", "JP"}
    # Expected: bottom 2 by analyst should == low_cluster, top 2 == high_cluster
    bottom2_analyst = set(rank_by_analyst[:2])
    top2_analyst = set(rank_by_analyst[2:])
    rank_matches_cluster = (bottom2_analyst == low_cluster) and (top2_analyst == high_cluster)

    # Sigma2 tautology diagnostic: θ_rel_i = θ_EAV / σ²_i is mechanically driven by σ²_i.
    # If within-market log(analyst) correlates with σ²_i, panel coef on log(analyst) is confounded.
    within_market_analyst_sigma2: dict = {}
    from scipy.stats import spearmanr as _sp
    for mkt in ("TW", "US", "JP", "EU"):
        sub = df_stock[(df_stock["market"] == mkt) & df_stock["analyst_count"].notna() & (df_stock["analyst_count"] > 0)]
        if len(sub) < 3:
            continue
        rho_as, p_as = _sp(np.log(sub["analyst_count"]), sub["sigma2_i"])
        within_market_analyst_sigma2[mkt] = {"rho": float(rho_as), "p": float(p_as), "n": int(len(sub))}

    # Verdict rule:
    #   CONFIRMED_PRELIMINARY: ρ_cross ≥ 0.7 AND panel log_analyst t ≥ 2 AND rank_matches_cluster
    #   REJECTED: rank_matches_cluster == False OR ρ_cross ≤ -0.3
    #   INCONCLUSIVE: otherwise
    verdict = "INCONCLUSIVE"
    notes: list[str] = []

    if not rank_matches_cluster:
        verdict = "REJECTED"
        notes.append(
            f"Rank-ordering check FAILS: analyst_median rank = {rank_by_analyst} but θ_rel LOW cluster = {sorted(low_cluster)}, HIGH = {sorted(high_cluster)}. "
            f"EU has MORE analysts than JP yet sits in LOW θ_rel cluster (0.14 vs JP 0.39). Direct contradiction of K1153 hypothesis."
        )
    elif primary_rho >= 0.7 and panel_coef.get("t_hc0", 0) >= 2:
        verdict = "CONFIRMED_PRELIMINARY"
    elif primary_rho <= -0.3:
        verdict = "REJECTED"
    else:
        verdict = "INCONCLUSIVE"

    notes.append(
        f"Cross-market Spearman ρ(analyst_median, θ_rel) = {primary_rho:+.3f} (p={primary_p:.3f}, N_markets=4)."
    )
    notes.append(
        f"Panel log_analyst coef = {panel_coef.get('beta', float('nan')):+.4f}, t_HC0 = {panel_coef.get('t_hc0', float('nan')):+.3f}."
    )
    # Sigma2 tautology warning
    positive_within_rho = [
        f"{m}: ρ={v['rho']:+.3f} (n={v['n']})"
        for m, v in within_market_analyst_sigma2.items()
        if v["rho"] > 0.25
    ]
    if positive_within_rho:
        notes.append(
            "⚠️ TAUTOLOGY WARNING: within-market log(analyst) correlates POSITIVELY with σ²_i "
            "(" + "; ".join(positive_within_rho) + "). "
            "Since θ_rel_i = θ_EAV/σ²_i by construction, the negative panel coef on log(analyst) is "
            "likely a SIZE/VOL confound, NOT evidence of a coverage mechanism."
        )

    # Rule 5 self-check
    if abs(primary_rho) > 0.95:
        notes.append(
            "⚠️ Rule #5 self-check: |ρ| > 0.95 on N=4 markets — almost certainly cherry-picked or perfect fit; "
            "verdict must be reported as PRELIMINARY only; cannot claim PASS."
        )
    else:
        notes.append(
            f"N_markets=4 → any finding must be treated as preliminary; recommend K1165 N≥8 extension "
            f"(add AU ASX, KR KOSPI, CA TSX, HK HSI) to gain df."
        )

    print(f"\n[VERDICT] {verdict}")
    for n in notes:
        print("  -", n)

    # 6. Save results JSON
    results = {
        "experiment_id": "K1164",
        "title": "Analyst coverage × media density mechanism test for cross-market θ_rel cluster",
        "proposer": "Claude (K1153 next_task K1164)",
        "executor": "Claude",
        "timestamp_utc": pd.Timestamp.utcnow().isoformat(),
        "random_seed": 42,
        "data_sources": [
            "K1145 (TW) / K1147 (US) / K1150 (JP) / K1153 (EU) per-stock GJR-τ fits",
            "yfinance Ticker.info (analyst count, market cap) — current snapshot",
            "Cached parquet turnover medians",
        ],
        "markets": list(MARKETS.keys()),
        "n_stocks_loaded": int(len(df_stock)),
        "per_stock_panel_head": df_stock.head(5).to_dict(orient="records"),
        "per_market_summary": summary.to_dict(orient="records"),
        "cross_market_spearman_N4": spearman,
        "panel_regression_with_market_FE": panel,
        "rank_ordering_check": {
            "rank_by_analyst_median_low_to_high": rank_by_analyst,
            "rank_by_theta_rel_low_to_high": rank_by_theta,
            "expected_low_cluster": sorted(list(low_cluster)),
            "expected_high_cluster": sorted(list(high_cluster)),
            "rank_matches_cluster": bool(rank_matches_cluster),
        },
        "within_market_analyst_vs_sigma2": within_market_analyst_sigma2,
        "verdict": verdict,
        "verdict_notes": notes,
        "hypothesis_tested": (
            "K1153 new hypothesis: High analyst coverage + concentrated earnings-season media "
            "-> high θ_rel cluster (US/JP). Low analyst + diffuse media -> low θ_rel cluster (TW/EU)."
        ),
        "figures": [],
    }

    figs = make_plots(summary, df_stock, out_dir)
    results["figures"] = figs

    out_path = out_dir / "k1164_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=float)
    print(f"\n[saved] {out_path}")

    # Also dump per-stock panel as csv for reproducibility
    df_stock.to_csv(out_dir / "k1164_per_stock_panel.csv", index=False)
    print(f"[saved] {out_dir / 'k1164_per_stock_panel.csv'}")


if __name__ == "__main__":
    main()
