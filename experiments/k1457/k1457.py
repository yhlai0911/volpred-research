#!/usr/bin/env python3
"""
K1457: M1 — Equity vs Non-Equity Safe-Haven Dummy in Cross-Sectional Regression

Paper 6 (vt-trend-following) v6 round-3 fix M1 (from review_history/v5).

Question: Does adding a safe-haven dummy (1 if non_equity, 0 if equity) to the
cross-sectional regression β_TSMOM_orth = γ0 + γ1·γ + ε attenuate the leverage
effect coefficient? This tests whether the γ→TSMOM relationship is driven by
asset class rather than the leverage mechanism per se.

Data: full-sample γ and β_TSMOM_orth for 22 assets from
paper/vt-trend-following/experiments/vt_tsmom_final_n22.json (canonical N=22).
Reproduces body Section 3.x line 220 (r=0.564) and line 229 (R²=0.319).

OLS specifications (HC3 robust SE; N=22):
  M0: β = γ0 + γ1·γ + ε                          (baseline, replicates body)
  M1a: β = γ0 + γ1·dummy_non_eq + ε              (dummy alone)
  M1b: β = γ0 + γ1·γ + γ2·dummy_non_eq + ε       (M1: leverage + dummy)

Lookahead: cross-sectional only; γ and β both estimated on the same
return panel (mechanical endogeneity acknowledged in body §3.x).
Seed: not applicable (deterministic OLS).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "paper/vt-trend-following/experiments/vt_tsmom_final_n22.json"
OUT = Path(__file__).parent / "k1457_results.json"


def load_panel() -> pd.DataFrame:
    data = json.loads(SRC.read_text())
    rows = []
    for ticker, row in data["asset_results"].items():
        m3 = row.get("model3_orth_tsmom") or {}
        beta = m3.get("beta_tsmom_orth")
        if beta is None:
            continue
        rows.append({
            "ticker": ticker,
            "asset_class": row["asset_class"],
            "gamma": row["gjr_gamma"],
            "beta_orth": beta,
            "dummy_non_eq": 1 if row["asset_class"] == "non_equity" else 0,
        })
    df = pd.DataFrame(rows).set_index("ticker")
    assert len(df) == 22, f"Expected 22 assets, got {len(df)}"
    return df


def run_ols(y: np.ndarray, X: np.ndarray, labels: list[str]) -> dict:
    """Cross-sectional OLS reporting both classical and HC3 robust SE.

    Body convention is classical SE (reproduces body M0 t=3.06); HC3 reported
    as robustness for cross-sectional N=22 with potential heteroscedasticity.
    """
    Xc = sm.add_constant(X, has_constant="add")
    fit_c = sm.OLS(y, Xc).fit()
    fit_h = sm.OLS(y, Xc).fit(cov_type="HC3")
    coefs = {}
    for i, name in enumerate(["intercept"] + labels):
        coefs[name] = {
            "coef": float(fit_c.params[i]),
            "se_classical": float(fit_c.bse[i]),
            "t_classical": float(fit_c.tvalues[i]),
            "p_classical": float(fit_c.pvalues[i]),
            "ci95_classical_lo": float(fit_c.conf_int()[i, 0]),
            "ci95_classical_hi": float(fit_c.conf_int()[i, 1]),
            "se_hc3": float(fit_h.bse[i]),
            "t_hc3": float(fit_h.tvalues[i]),
            "p_hc3": float(fit_h.pvalues[i]),
        }
    return {
        "n": int(fit_c.nobs),
        "r2": float(fit_c.rsquared),
        "r2_adj": float(fit_c.rsquared_adj),
        "f_stat_classical": float(fit_c.fvalue),
        "f_pvalue_classical": float(fit_c.f_pvalue),
        "coefficients": coefs,
    }


def main():
    df = load_panel()

    y = df["beta_orth"].to_numpy()
    g = df["gamma"].to_numpy()
    d = df["dummy_non_eq"].to_numpy()

    m0 = run_ols(y, g.reshape(-1, 1), ["gamma"])
    m1a = run_ols(y, d.reshape(-1, 1), ["dummy_non_eq"])
    m1b = run_ols(y, np.column_stack([g, d]), ["gamma", "dummy_non_eq"])

    eq_mask = df["asset_class"] == "equity"
    neq_mask = df["asset_class"] == "non_equity"
    desc = {
        "equity": {
            "n": int(eq_mask.sum()),
            "mean_gamma": float(df.loc[eq_mask, "gamma"].mean()),
            "mean_beta_orth": float(df.loc[eq_mask, "beta_orth"].mean()),
            "std_beta_orth": float(df.loc[eq_mask, "beta_orth"].std(ddof=1)),
        },
        "non_equity": {
            "n": int(neq_mask.sum()),
            "mean_gamma": float(df.loc[neq_mask, "gamma"].mean()),
            "mean_beta_orth": float(df.loc[neq_mask, "beta_orth"].mean()),
            "std_beta_orth": float(df.loc[neq_mask, "beta_orth"].std(ddof=1)),
        },
    }

    delta_gamma1 = m1b["coefficients"]["gamma"]["coef"] - m0["coefficients"]["gamma"]["coef"]
    pct_attenuation = (
        100.0 * (1 - m1b["coefficients"]["gamma"]["coef"] / m0["coefficients"]["gamma"]["coef"])
        if abs(m0["coefficients"]["gamma"]["coef"]) > 1e-9 else None
    )

    results = {
        "experiment_id": "K1457",
        "title": "M1: Safe-haven dummy in cross-sectional β_TSMOM ~ γ regression (N=22)",
        "paper_ref": "paper/vt-trend-following/body_v3.tex line 228-229, 230-234 (round 3 M1 fix)",
        "data_source": str(SRC.relative_to(REPO)),
        "n_assets": int(len(df)),
        "n_equity": int(eq_mask.sum()),
        "n_non_equity": int(neq_mask.sum()),
        "panel_summary": desc,
        "specifications": {
            "M0_baseline_gamma_only": m0,
            "M1a_dummy_only": m1a,
            "M1_gamma_plus_dummy": m1b,
        },
        "delta_gamma1_after_dummy": float(delta_gamma1),
        "pct_attenuation_gamma1": pct_attenuation,
        "interpretation": (
            "If γ1 coefficient remains significant and similar magnitude with the "
            "dummy added (small attenuation), the leverage effect channel survives "
            "after controlling for asset class. If γ1 collapses or loses significance, "
            "the γ→TSMOM relationship reflects an equity-vs-non-equity grouping "
            "rather than a continuous leverage-effect mechanism."
        ),
        "raw_panel": df.reset_index().to_dict(orient="records"),
    }

    OUT.write_text(json.dumps(results, indent=2))
    print(f"[K1457] wrote {OUT}")
    print(f"  M0 γ coef = {m0['coefficients']['gamma']['coef']:.4f} "
          f"(t_classical={m0['coefficients']['gamma']['t_classical']:.2f}, "
          f"t_HC3={m0['coefficients']['gamma']['t_hc3']:.2f}, R²={m0['r2']:.3f})")
    print(f"  M1 γ coef = {m1b['coefficients']['gamma']['coef']:.4f} "
          f"(t_classical={m1b['coefficients']['gamma']['t_classical']:.2f}, "
          f"t_HC3={m1b['coefficients']['gamma']['t_hc3']:.2f}, R²={m1b['r2']:.3f})")
    print(f"  M1 dummy coef = {m1b['coefficients']['dummy_non_eq']['coef']:.4f} "
          f"(t_classical={m1b['coefficients']['dummy_non_eq']['t_classical']:.2f}, "
          f"t_HC3={m1b['coefficients']['dummy_non_eq']['t_hc3']:.2f})")
    print(f"  attenuation: γ1 Δ = {delta_gamma1:+.4f} ({pct_attenuation:+.1f}% relative)")


if __name__ == "__main__":
    main()
