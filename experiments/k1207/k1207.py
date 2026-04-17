"""K1207 — Sector-FE vs inst-FE decomposition of θ_EAV panel (K1171 N=182).

Purpose
-------
Test K1171 (commit 17436274) narrative claim:
    "sector composition is orthogonal to institutional ownership as an
    independent driver of θ_rel."

The K1171 observation:
    AU below-ladder (θ_rel = 0.150 at mid inst_pct = 0.368) mirrors
    BR / IN / MX above-ladder residuals → suggests sector mix independently
    moves θ_EAV net of inst ownership.

Design
------
Pool: 182 stocks × 12 markets (K1171 panel; 100% GICS-classified).

Analysis 1 — Sector-FE regression
    θ_EAV_i = α + Σ_s β_s · sector_s,i + log_mcap_i + ε_i
    Report: sector-FE joint F-test, R² sector only, R² sector + log_mcap

Analysis 2 — Sector-FE vs inst-FE comparison (4-model panel OLS)
    M1: θ_EAV ~ market_FE + log_mcap                     [K1171 baseline]
    M2: θ_EAV ~ market_FE + log_mcap + inst_pct          [K1171 current]
    M3: θ_EAV ~ market_FE + log_mcap + sector_FE         [K1207 new]
    M4: θ_EAV ~ market_FE + log_mcap + inst_pct + sector_FE  [joint]

    Cluster-robust (by market) SE; compare R², inst_pct β(t) M2 vs M4.

Analysis 3 — AU / BR / IN / MX sector mix decomposition
    Per-market GICS sector share (%); whether AU heavy Financials + Materials,
    BR / IN / MX heavy Energy + Materials / Financials, explains residual
    direction on the inst-ownership ladder.

Analysis 4 — Orthogonality Spearman
    rho(sector_θ_median, sector_inst_pct_median) across GICS sectors — is
    sector-θ independent of sector-inst?

Verdict rules
-------------
SECTOR_ORTHOGONAL_CONFIRMED:
    sector-FE adj-R² ≥ 0.5 × inst-FE adj-R²  AND
    inst_pct coef |Δ| < 25% between M2 and M4 (sector-FE doesn't kill inst)
SECTOR_PARTIAL:
    sector adds explanatory power but inst-FE still stronger
SECTOR_NULL:
    sector-FE R² << inst-FE R²; K1171 claim empirically unsupported

Random seed: 42.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

np.random.seed(42)

ROOT = Path(__file__).resolve().parent
K1171_TABLE = Path(
    "/Users/yhlai0911/Desktop/volpred-research/experiments/k1171/k1171_per_stock_table.csv"
)
K1171_POOLED = Path(
    "/Users/yhlai0911/Desktop/volpred-research/experiments/k1171/k1171_pooled_by_market.json"
)
SECTORS_CSV = ROOT / "k1207_stock_sectors.csv"


def load_panel() -> pd.DataFrame:
    """Merge K1171 per-stock θ_EAV table with K1207 GICS sector classifications.

    Adds a per-stock θ_rel = θ_EAV / σ²_sample (stock-level analog of the
    pooled θ_rel K1152 metric) for a robustness regression.
    """
    panel = pd.read_csv(K1171_TABLE)
    sectors = pd.read_csv(SECTORS_CSV)
    merged = panel.merge(
        sectors[["market", "ticker", "gics_sector", "source"]],
        on=["market", "ticker"],
        how="left",
    )
    # Sanity checks
    assert merged["gics_sector"].notna().all(), "Missing sector after merge"
    # Drop stocks that have no converged θ_EAV (K1171 drops non-convergers
    # already, but defend):
    merged = merged.dropna(subset=["theta_eav"])
    # Stock-level θ_rel analog (robustness)
    merged["theta_rel_stock"] = merged["theta_eav"] / merged["sigma2_sample"]
    return merged


def cluster_robust_ols(
    y: np.ndarray, X: pd.DataFrame, clusters: np.ndarray
) -> sm.regression.linear_model.RegressionResultsWrapper:
    """Fit OLS with market-clustered SE (statsmodels)."""
    model = sm.OLS(y, X)
    # `cluster` cov_type requires integer group codes
    result = model.fit(
        cov_type="cluster", cov_kwds={"groups": clusters, "use_correction": True}
    )
    return result


def design_market_fe(df: pd.DataFrame) -> pd.DataFrame:
    """Build market-fixed-effect dummy block (drop first level)."""
    mkt = pd.get_dummies(df["market"], prefix="mkt", drop_first=True, dtype=float)
    return mkt


def design_sector_fe(df: pd.DataFrame) -> pd.DataFrame:
    """Build GICS sector fixed-effect dummy block (drop first level)."""
    sec = pd.get_dummies(
        df["gics_sector"], prefix="sec", drop_first=True, dtype=float
    )
    return sec


def fit_model(
    df: pd.DataFrame,
    add_cols: list[str],
    use_sector: bool,
    y_col: str = "theta_eav",
) -> dict:
    """Fit panel OLS with market FE + (optional) inst_pct + (optional) sector FE.

    Returns dict with R², adj_R², inst_pct β/t/p (if present), sector F-test,
    n observations, results object.
    """
    y = df[y_col].values
    components: list[pd.DataFrame] = []
    # Always: intercept + market FE + log_mcap
    const = pd.DataFrame(
        {"const": np.ones(len(df))}, index=df.index
    )
    components.append(const)
    components.append(design_market_fe(df))
    components.append(df[["log_mcap"]].reset_index(drop=True).set_index(df.index))
    # Optional inst_pct
    for col in add_cols:
        if col in df.columns:
            components.append(df[[col]].reset_index(drop=True).set_index(df.index))
    # Optional sector FE
    sector_cols: list[str] = []
    if use_sector:
        sec = design_sector_fe(df)
        sector_cols = list(sec.columns)
        components.append(sec)
    X = pd.concat(components, axis=1)
    X = X.astype(float)
    # Cluster by market integer codes
    clusters = df["market"].astype("category").cat.codes.values
    res = cluster_robust_ols(y, X, clusters)

    out = {
        "n": int(len(df)),
        "r2": float(res.rsquared),
        "adj_r2": float(res.rsquared_adj),
        "f_stat": float(res.fvalue) if not np.isnan(res.fvalue) else None,
        "f_pvalue": float(res.f_pvalue) if not np.isnan(res.f_pvalue) else None,
        "aic": float(res.aic),
        "bic": float(res.bic),
    }
    # Extract coefficients of interest
    coef_of_interest = ["log_mcap"] + list(add_cols)
    for c in coef_of_interest:
        if c in res.params.index:
            out[f"{c}_beta"] = float(res.params[c])
            out[f"{c}_se"] = float(res.bse[c])
            out[f"{c}_t"] = float(res.tvalues[c])
            out[f"{c}_p"] = float(res.pvalues[c])
    # Joint F-test for sector FE block (if present)
    if sector_cols:
        try:
            hypothesis = " = ".join([f"{c} " for c in sector_cols]) + "= 0"
            # statsmodels accepts list of strings; one simpler approach:
            ftest = res.f_test(" = 0, ".join(sector_cols) + " = 0")
            out["sector_fe_f"] = float(np.squeeze(ftest.fvalue))
            out["sector_fe_p"] = float(np.squeeze(ftest.pvalue))
            out["sector_fe_df"] = int(len(sector_cols))
        except Exception as e:  # pylint: disable=broad-except
            out["sector_fe_f"] = None
            out["sector_fe_p"] = None
            out["sector_fe_error"] = str(e)
    return out


def sector_only_regression(df: pd.DataFrame) -> dict:
    """Analysis 1 — sector-FE only (no market FE) to gauge between-stock
    cross-sectional R² attributable to sector mix alone.

    Specs:
      S1: θ_EAV ~ const + sector_FE
      S2: θ_EAV ~ const + sector_FE + log_mcap
    """
    y = df["theta_eav"].values
    sec = design_sector_fe(df)
    const = pd.DataFrame({"const": np.ones(len(df))}, index=df.index)
    clusters = df["market"].astype("category").cat.codes.values

    X_s1 = pd.concat([const, sec], axis=1).astype(float)
    res_s1 = cluster_robust_ols(y, X_s1, clusters)

    X_s2 = pd.concat(
        [const, sec, df[["log_mcap"]].reset_index(drop=True).set_index(df.index)],
        axis=1,
    ).astype(float)
    res_s2 = cluster_robust_ols(y, X_s2, clusters)

    out = {
        "S1_sector_only": {
            "n": int(len(df)),
            "r2": float(res_s1.rsquared),
            "adj_r2": float(res_s1.rsquared_adj),
        },
        "S2_sector_plus_mcap": {
            "n": int(len(df)),
            "r2": float(res_s2.rsquared),
            "adj_r2": float(res_s2.rsquared_adj),
        },
    }
    # F-test for sector block under S1
    sector_cols = list(sec.columns)
    try:
        ftest = res_s1.f_test(" = 0, ".join(sector_cols) + " = 0")
        out["S1_sector_only"]["sector_fe_f"] = float(np.squeeze(ftest.fvalue))
        out["S1_sector_only"]["sector_fe_p"] = float(np.squeeze(ftest.pvalue))
        out["S1_sector_only"]["sector_fe_df"] = int(len(sector_cols))
    except Exception as e:
        out["S1_sector_only"]["error"] = str(e)
    return out


def per_market_sector_mix(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot table of sector share (%) per market, rounded."""
    tab = (
        pd.crosstab(df["market"], df["gics_sector"], normalize="index")
        .fillna(0.0)
    )
    tab = (tab * 100).round(1)
    return tab


def sector_theta_median(df: pd.DataFrame) -> pd.DataFrame:
    """Per-sector median θ_EAV + median inst_pct for orthogonality check."""
    agg = df.groupby("gics_sector").agg(
        theta_eav_median=("theta_eav", "median"),
        theta_eav_mean=("theta_eav", "mean"),
        inst_pct_median=("institutions_pct", "median"),
        log_analyst_median=("log_analyst", "median"),
        n=("ticker", "count"),
    )
    return agg


def sector_adjusted_residuals(df: pd.DataFrame) -> pd.DataFrame:
    """For each stock, subtract its GICS sector global mean θ_EAV. Then
    per-market aggregate raw vs sector-adjusted mean. This shows how much
    of each market's residual is sector-explained.
    """
    sec_mean = df.groupby("gics_sector")["theta_eav"].transform("mean")
    adj = df["theta_eav"] - sec_mean
    tab = pd.DataFrame(
        {
            "theta_raw_mean": df.groupby(df["market"])["theta_eav"].mean(),
            "theta_sec_adj_mean": adj.groupby(df["market"]).mean(),
            "theta_raw_median": df.groupby(df["market"])["theta_eav"].median(),
            "theta_sec_adj_median": adj.groupby(df["market"]).median(),
            "n": df.groupby(df["market"]).size(),
        }
    )
    tab["abs_reduction_pct"] = (
        (tab["theta_raw_mean"].abs() - tab["theta_sec_adj_mean"].abs())
        / tab["theta_raw_mean"].abs()
        * 100
    )
    return tab


def residual_markets_report(df: pd.DataFrame) -> dict:
    """Analysis 3 — focus AU / BR / IN / MX (plus EU for reference)."""
    targets = ["AU", "BR", "IN", "MX", "EU", "US", "CA", "JP"]
    out: dict[str, dict] = {}
    for m in targets:
        sub = df[df["market"] == m]
        if len(sub) == 0:
            continue
        mix = (sub["gics_sector"].value_counts(normalize=True) * 100).round(1).to_dict()
        theta_med = float(sub["theta_eav"].median())
        inst_mean = float(sub["institutions_pct"].mean())
        out[m] = {
            "n": int(len(sub)),
            "theta_eav_median": theta_med,
            "inst_pct_mean": inst_mean,
            "sector_mix_pct": mix,
            "top_sector_pct": max(mix.values()),
            "top_sector": max(mix.items(), key=lambda x: x[1])[0],
        }
    return out


def orthogonality_spearman(sector_med: pd.DataFrame) -> dict:
    """Spearman rho(sector_theta_median, sector_inst_pct_median) across GICS
    sectors."""
    rho, p = stats.spearmanr(
        sector_med["theta_eav_median"], sector_med["inst_pct_median"]
    )
    return {
        "rho": float(rho),
        "p": float(p),
        "n_sectors": int(len(sector_med)),
    }


def classify_verdict(
    adj_r2_M1: float,
    adj_r2_M2: float,
    adj_r2_M3: float,
    adj_r2_M4: float,
    inst_beta_M2: float,
    inst_beta_M4: float,
    inst_t_M2: float,
    inst_t_M4: float,
    sector_f_M3: float,
    sector_f_p_M3: float,
) -> dict:
    """Apply verdict rules from brief."""
    # Inst-FE incremental R² = M2 - M1
    inc_inst = adj_r2_M2 - adj_r2_M1
    # Sector-FE incremental R² = M3 - M1
    inc_sec = adj_r2_M3 - adj_r2_M1
    # Joint incremental = M4 - M1
    inc_joint = adj_r2_M4 - adj_r2_M1

    # Stability of inst_pct across M2 -> M4
    beta_rel_change = (
        abs(inst_beta_M4 - inst_beta_M2) / max(abs(inst_beta_M2), 1e-12)
    )

    confirmed = (
        inc_sec >= 0.5 * inc_inst
        and beta_rel_change < 0.25
        and sector_f_p_M3 < 0.10
    )
    nulled = (inc_sec < 0.25 * max(inc_inst, 1e-6)) and sector_f_p_M3 > 0.10
    if confirmed:
        verdict = "SECTOR_ORTHOGONAL_CONFIRMED"
    elif nulled:
        verdict = "SECTOR_NULL"
    else:
        verdict = "SECTOR_PARTIAL"
    return {
        "verdict": verdict,
        "inc_R2_inst_M2_minus_M1": float(inc_inst),
        "inc_R2_sector_M3_minus_M1": float(inc_sec),
        "inc_R2_joint_M4_minus_M1": float(inc_joint),
        "inst_beta_M2": float(inst_beta_M2),
        "inst_beta_M4": float(inst_beta_M4),
        "inst_t_M2": float(inst_t_M2),
        "inst_t_M4": float(inst_t_M4),
        "inst_beta_relative_change_M2_to_M4": float(beta_rel_change),
        "sector_fe_joint_F_M3": float(sector_f_M3),
        "sector_fe_joint_p_M3": float(sector_f_p_M3),
    }


def main() -> None:
    print("=" * 76)
    print("K1207 — GICS sector-FE vs inst-FE decomposition (K1171 N=182 pool)")
    print("=" * 76)

    df = load_panel()
    print(f"\nPanel N = {len(df)} stocks across {df['market'].nunique()} markets")
    print(f"GICS sectors present: {df['gics_sector'].nunique()}")
    print(df["gics_sector"].value_counts().to_string())

    # Coverage table
    coverage = (
        df.groupby("market")["gics_sector"].apply(
            lambda s: f"{s.notna().sum()}/{len(s)} ({s.notna().mean():.0%})"
        )
    ).to_dict()

    # --- Analysis 1: Sector-only regression ---
    print("\n--- Analysis 1: Sector-FE only (no market FE) ---")
    a1 = sector_only_regression(df)
    print(json.dumps(a1, indent=2))

    # --- Analysis 2: 4-model panel OLS (y = θ_EAV, primary) ---
    print("\n--- Analysis 2: 4-model panel OLS (y = θ_EAV) ---")
    m1 = fit_model(df, add_cols=[], use_sector=False)
    m2 = fit_model(df, add_cols=["institutions_pct"], use_sector=False)
    m3 = fit_model(df, add_cols=[], use_sector=True)
    m4 = fit_model(df, add_cols=["institutions_pct"], use_sector=True)
    models = {"M1": m1, "M2": m2, "M3": m3, "M4": m4}
    # Robustness: same 4 models with y = θ_rel_stock
    print("\n--- Analysis 2b (robustness): y = θ_rel_stock ---")
    m1r = fit_model(df, add_cols=[], use_sector=False, y_col="theta_rel_stock")
    m2r = fit_model(df, add_cols=["institutions_pct"], use_sector=False, y_col="theta_rel_stock")
    m3r = fit_model(df, add_cols=[], use_sector=True, y_col="theta_rel_stock")
    m4r = fit_model(df, add_cols=["institutions_pct"], use_sector=True, y_col="theta_rel_stock")
    models_r = {"M1_rel": m1r, "M2_rel": m2r, "M3_rel": m3r, "M4_rel": m4r}
    for name, res in models.items():
        beta = res.get("institutions_pct_beta", None)
        t = res.get("institutions_pct_t", None)
        secf = res.get("sector_fe_f", None)
        secp = res.get("sector_fe_p", None)
        print(
            f"{name}: R²={res['r2']:.4f} adj={res['adj_r2']:.4f} "
            f"inst_β={beta} inst_t={t} sec_F={secf} sec_p={secp}"
        )
    print("Robustness (y=θ_rel_stock):")
    for name, res in models_r.items():
        beta = res.get("institutions_pct_beta", None)
        t = res.get("institutions_pct_t", None)
        secf = res.get("sector_fe_f", None)
        secp = res.get("sector_fe_p", None)
        print(
            f"{name}: R²={res['r2']:.4f} adj={res['adj_r2']:.4f} "
            f"inst_β={beta} inst_t={t} sec_F={secf} sec_p={secp}"
        )

    # --- Analysis 3a: sector-adjusted residual per market ---
    print("\n--- Analysis 3a: sector-adjusted θ_EAV residual by market ---")
    sec_adj_tab = sector_adjusted_residuals(df)
    print(sec_adj_tab.round(6).to_string())
    sec_adj_tab.to_csv(ROOT / "k1207_sector_adjusted_residuals.csv")

    # --- Analysis 3: residual-market sector mix ---
    print("\n--- Analysis 3b: per-market sector mix (AU/BR/IN/MX focus) ---")
    residual = residual_markets_report(df)
    for m, r in residual.items():
        print(
            f"  {m}: n={r['n']} top={r['top_sector']}({r['top_sector_pct']}%) "
            f"inst_pct_mean={r['inst_pct_mean']:.3f} theta_med={r['theta_eav_median']:.3e}"
        )

    # --- Analysis 4: Orthogonality Spearman ---
    print("\n--- Analysis 4: Orthogonality (sector-θ vs sector-inst) ---")
    sector_med = sector_theta_median(df)
    print(sector_med.to_string())
    orth = orthogonality_spearman(sector_med)
    print(f"  Spearman rho(sector_θ_median, sector_inst_pct_median) = {orth['rho']:+.3f}, p={orth['p']:.3f}, n={orth['n_sectors']}")

    # Per-market sector mix full table
    mix_tab = per_market_sector_mix(df)

    # --- Verdict ---
    verdict = classify_verdict(
        adj_r2_M1=m1["adj_r2"],
        adj_r2_M2=m2["adj_r2"],
        adj_r2_M3=m3["adj_r2"],
        adj_r2_M4=m4["adj_r2"],
        inst_beta_M2=m2["institutions_pct_beta"],
        inst_beta_M4=m4["institutions_pct_beta"],
        inst_t_M2=m2["institutions_pct_t"],
        inst_t_M4=m4["institutions_pct_t"],
        sector_f_M3=m3["sector_fe_f"] or float("nan"),
        sector_f_p_M3=m3["sector_fe_p"] or 1.0,
    )
    print("\n--- Verdict ---")
    print(json.dumps(verdict, indent=2))

    # --- Persist results ---
    results = {
        "experiment_id": "K1207",
        "seed": 42,
        "panel_N": int(len(df)),
        "n_markets": int(df["market"].nunique()),
        "n_gics_sectors": int(df["gics_sector"].nunique()),
        "coverage_by_market": coverage,
        "sectors_present": df["gics_sector"].value_counts().to_dict(),
        "analysis1_sector_only": a1,
        "analysis2_4model": {k: v for k, v in models.items()},
        "analysis2b_4model_theta_rel_stock": {k: v for k, v in models_r.items()},
        "analysis3a_sector_adjusted_residuals": sec_adj_tab.reset_index().to_dict(orient="records"),
        "analysis3b_residual_markets": residual,
        "analysis4_orthogonality": orth,
        "sector_median_table": sector_med.reset_index().to_dict(orient="records"),
        "per_market_sector_mix_pct": mix_tab.to_dict(),
        "verdict": verdict,
    }
    out_path = ROOT / "k1207_results.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\nWrote {out_path}")

    # Also save the sector median table + per-market mix CSVs for direct table
    # reading
    sector_med.to_csv(ROOT / "k1207_sector_median.csv")
    mix_tab.to_csv(ROOT / "k1207_per_market_sector_mix_pct.csv")
    print(f"Wrote k1207_sector_median.csv and k1207_per_market_sector_mix_pct.csv")


if __name__ == "__main__":
    main()
