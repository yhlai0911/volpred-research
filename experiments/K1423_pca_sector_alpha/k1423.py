"""
K1423: 「打敗市場的超額報酬，是真 Alpha，還是還沒被命名的因子？」
PCA + 因子回歸在台股與美股半導體籃子上實證。

核心論點：sector ETF（不選股、不擇時）對市場做迴歸常得顯著 alpha，
但那 alpha 其實是「未命名的 sector 共同因子曝險」。用 PCA 把籃子 latent
structure 抽出 (PC1=sector factor)，加進迴歸後 alpha 應大幅縮小。
台美都做，比較兩市場 sector-factor 結構。

研究誠實：
- contemporaneous risk-attribution 迴歸（非 forecast），無 lookahead。
- seed=42 固定；報酬 inner join 對齊，缺值 drop 並記數量。
- alpha 年化 = 日 alpha * 252；t-stat 用 Newey-West HAC（lag=5）。
- 所有數字寫進 k1423_results.json。
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import statsmodels.api as sm

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
START = "2014-01-01"
END = "2026-06-01"
NW_LAG = 5  # Newey-West HAC lag

US_BASKET = ["NVDA", "AMD", "TSM", "ASML", "AMAT", "MU", "QCOM", "AVGO"]
US_ETF = "SMH"
US_MKT = "SPY"

TW_BASKET = ["2330.TW", "2454.TW", "2303.TW", "3711.TW", "2379.TW", "3034.TW", "3037.TW", "2308.TW"]
TW_MKT = "0050.TW"


def fetch_returns(tickers):
    """Download adjusted-close daily returns; return DataFrame + drop log."""
    data = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)
    close = data["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame()
    # drop tickers entirely missing
    present = [t for t in tickers if t in close.columns and close[t].notna().sum() > 100]
    dropped = [t for t in tickers if t not in present]
    close = close[present]
    rets = np.log(close / close.shift(1))
    return rets, present, dropped


def run_pca_descriptive(basket_rets):
    """Descriptive PCA on FULL basket RAW returns: how strong is common sector structure?
    Reports PC1/PC2 explained variance and PC1 loadings (all same sign = common up/down).
    NOT used as a regression regressor (that would be mechanically collinear)."""
    df = basket_rets.dropna()
    cols = list(df.columns)
    Xz = StandardScaler().fit_transform(df.values)
    pca = PCA(random_state=SEED)
    pca.fit(Xz)
    evr = pca.explained_variance_ratio_
    raw_load = pca.components_[0]
    sign = 1.0 if np.sum(raw_load > 0) >= len(cols) / 2 else -1.0
    pc1_load = dict(zip(cols, (raw_load * sign).tolist()))
    pc2_load = dict(zip(cols, (pca.components_[1] * sign).tolist())) if len(evr) > 1 else {}
    all_same_sign = all(v > 0 for v in pc1_load.values()) or all(v < 0 for v in pc1_load.values())
    return {
        "n_obs": int(len(df)),
        "components": cols,
        "explained_var_pc1": float(evr[0]),
        "explained_var_pc2": float(evr[1]) if len(evr) > 1 else None,
        "explained_var_top3": [float(x) for x in evr[:3]],
        "pc1_loadings": pc1_load,
        "pc2_loadings": pc2_load,
        "pc1_all_same_sign": bool(all_same_sign),
    }


def residualize_on_market(stock_rets, mkt_rets):
    """Residualize each stock's daily return on the market (remove market-beta component).
    Returns a DataFrame of market-neutral residual returns (return units)."""
    df = pd.concat([stock_rets, mkt_rets.rename("mkt")], axis=1, join="inner").dropna()
    resid = {}
    for col in stock_rets.columns:
        X = sm.add_constant(df["mkt"])
        m = sm.OLS(df[col], X).fit()
        resid[col] = df[col] - m.predict(X)
    return pd.DataFrame(resid, index=df.index)


def run_pca(basket_rets, mkt_rets):
    """Build a MARKET-NEUTRAL, return-unit sector factor via PCA.

    Design (per Codex review of v1 mechanical-collinearity bug):
      1. Residualize each basket stock on the market first -> remove market component.
      2. PCA on the residual returns -> PC1 loadings = common sector-specific structure.
      3. Sector factor return f_t = (PC1 loadings) . (residual returns at t), normalized to
         unit-L2 loadings so the factor is a return-unit long portfolio (not a std-score).
    This gives a tradable-style market-neutral sector factor in RETURN units, avoiding the
    v1 bug where a raw standardized PCA score (variance units, contemporaneous with the
    sector proxy built from the same stocks) mechanically inflated R^2 to 0.99.
    """
    resid = residualize_on_market(basket_rets, mkt_rets).dropna()
    cols = list(resid.columns)
    # PCA on standardized residuals (loadings estimated in z-space).
    scaler = StandardScaler()
    Xz = scaler.fit_transform(resid.values)
    pca = PCA(random_state=SEED)
    pca.fit(Xz)
    evr = pca.explained_variance_ratio_
    comp = pca.components_[0]
    # sign-align so majority positive
    sign = 1.0 if np.sum(comp > 0) >= len(cols) / 2 else -1.0
    comp = comp * sign
    # Back-transform z-space loadings to RAW-return space (w_raw = comp / std) so the factor
    # is a consistent raw-return portfolio of the residuals (Codex fix: avoid the z-loadings
    # x raw-returns mismatch). Then unit-L2 normalize.
    std = scaler.scale_
    w_raw = comp / std
    w = w_raw / np.linalg.norm(w_raw)
    factor = pd.Series(resid.values @ w, index=resid.index, name="PC1")
    pc1_load = dict(zip(cols, w.tolist()))
    # PC2 loadings also back-transformed to raw-return space + unit-L2 (consistent units
    # with PC1; Codex v3 minor fix to avoid mixed-unit reporting).
    if len(evr) > 1:
        w2_raw = (pca.components_[1] * sign) / std
        w2 = w2_raw / np.linalg.norm(w2_raw)
        pc2_load = dict(zip(cols, w2.tolist()))
    else:
        pc2_load = {}
    all_same_sign = all(v > 0 for v in pc1_load.values()) or all(v < 0 for v in pc1_load.values())
    return {
        "n_obs": int(len(resid)),
        "components": cols,
        "factor_construction": "market-residualized PCA, unit-L2 loadings, return units",
        "explained_var_pc1": float(evr[0]),
        "explained_var_pc2": float(evr[1]) if len(evr) > 1 else None,
        "explained_var_top3": [float(x) for x in evr[:3]],
        "pc1_loadings": pc1_load,
        "pc2_loadings": pc2_load,
        "pc1_all_same_sign": bool(all_same_sign),
    }, factor


def hac_regress(y, X_df):
    """OLS with Newey-West HAC SE. X_df: columns of regressors (no const). Returns dict."""
    X = sm.add_constant(X_df)
    model = sm.OLS(y, X, missing="drop").fit(cov_type="HAC", cov_kwds={"maxlags": NW_LAG})
    out = {
        "n_obs": int(model.nobs),
        "r2": float(model.rsquared),
        "alpha_daily": float(model.params["const"]),
        "alpha_annual": float(model.params["const"] * 252),
        "alpha_tstat": float(model.tvalues["const"]),
        "alpha_pvalue": float(model.pvalues["const"]),
        "betas": {},
    }
    for c in X_df.columns:
        out["betas"][c] = {
            "coef": float(model.params[c]),
            "tstat": float(model.tvalues[c]),
            "pvalue": float(model.pvalues[c]),
        }
    return out


def split_robustness(basket_present, basket_rets, mkt_x):
    """Premium-attribution alpha across ALL balanced disjoint splits of the basket.
    factor_pool = half A, sector_y = EW of half B; sector_long = EW of half A.
    Regress sector_y ~ mkt + sector_long; collect alpha & t. Tests that alpha-absorption
    is not an artifact of one arbitrary split (Codex CONDITIONAL note)."""
    from itertools import combinations
    stocks = sorted(basket_present)
    n = len(stocks)
    half = n // 2
    alphas, tstats = [], []
    seen = set()
    for combo in combinations(range(n), half):
        # avoid double-counting complementary splits (A|B == B|A)
        comp = tuple(sorted(set(range(n)) - set(combo)))
        key = frozenset([combo, comp])
        if key in seen:
            continue
        seen.add(key)
        fpool = [stocks[i] for i in combo]
        ppool = [stocks[i] for i in comp]
        sy = basket_rets[ppool].mean(axis=1)
        sl = basket_rets[fpool].mean(axis=1)
        df = pd.concat([sy.rename("sector"), mkt_x, sl.rename("SECTOR_LONG")], axis=1, join="inner").dropna()
        reg = hac_regress(df["sector"], df[["mkt", "SECTOR_LONG"]])
        alphas.append(reg["alpha_annual"])
        tstats.append(reg["alpha_tstat"])
    alphas = np.array(alphas)
    tstats = np.array(tstats)
    return {
        "n_splits": int(len(alphas)),
        "alpha_with_sectorlong_mean": float(alphas.mean()),
        "alpha_with_sectorlong_min": float(alphas.min()),
        "alpha_with_sectorlong_max": float(alphas.max()),
        "frac_splits_alpha_insignificant": float(np.mean(np.abs(tstats) < 1.96)),
        "tstat_mean": float(tstats.mean()),
    }


def analyze_market(name, basket, etf_or_basket_proxy, mkt, results):
    print(f"\n=== {name} ===")
    # fetch all tickers
    need = list(set(basket + [mkt] + ([etf_or_basket_proxy] if etf_or_basket_proxy else [])))
    rets, present, dropped = fetch_returns(need)
    print(f"  dropped: {dropped}")

    basket_present = [t for t in basket if t in present]
    basket_rets = rets[basket_present]
    mkt_x = rets[mkt].dropna()
    mkt_x.name = "mkt"

    # ---- sector proxy (y) and factor-construction pool: ALWAYS DISJOINT (per Codex v3
    #      review: SMH holds the same 8 stocks -> not a true leave-out -> mechanical
    #      circularity). BOTH markets now use a disjoint leave-out split for the
    #      identification regression. Deterministic sorted split for reproducibility. ----
    sorted_basket = sorted(basket_present)
    half = len(sorted_basket) // 2
    factor_pool = sorted_basket[:half]
    proxy_pool = sorted_basket[half:]
    sector_y = basket_rets[proxy_pool].mean(axis=1).dropna()
    sector_label = f"EW_leaveout_proxy({len(proxy_pool)})"
    sector_kind = "equal_weight_basket_leave_out"
    split_note = (f"leave-out split: factor pool={factor_pool}; sector_y=EW of disjoint "
                  f"pool={proxy_pool} (NO shared stocks -> no mechanical collinearity)")
    sector_y.name = "sector"
    print(f"  {split_note}")

    # Descriptive real-world ETF baseline (US only): SMH ~ SPY — this is the "headline"
    # alpha a real investor would see. Reported separately; NOT the identification test
    # (SMH overlaps the factor stocks so it is not used to claim absorption).
    etf_baseline = None
    if etf_or_basket_proxy and etf_or_basket_proxy in present:
        etf_y = rets[etf_or_basket_proxy].dropna()
        etf_y.name = "etf"
        dfe = pd.concat([etf_y, mkt_x], axis=1, join="inner").dropna()
        ebase = hac_regress(dfe["etf"], dfe[["mkt"]])
        etf_baseline = {"etf": etf_or_basket_proxy, "market": mkt, "regression_mkt_only": ebase}
        print(f"  [ETF baseline {etf_or_basket_proxy}~{mkt}] alpha_ann={ebase['alpha_annual']:.4f} "
              f"t={ebase['alpha_tstat']:.2f} R2={ebase['r2']:.3f}")

    # Descriptive PCA on the FULL basket (raw returns) — for the "how strong is the
    # common sector structure" claim (Fig 1 / cross-market comparison). This is the
    # latent-structure description, separate from the regression factor.
    full_pca = run_pca_descriptive(basket_rets)
    print(f"  [FULL basket PCA] PC1 explained var: {full_pca['explained_var_pc1']:.3f}; "
          f"same-sign: {full_pca['pc1_all_same_sign']}")

    # PCA factor used in regression: from factor_pool only, market-residualized
    pca_res, pc1_series = run_pca(basket_rets[factor_pool], mkt_x)
    pca_res["factor_pool"] = factor_pool
    pca_res["split_note"] = split_note
    pca_res["full_basket_pca"] = full_pca
    print(f"  [factor PCA] PC1 explained var (resid): {pca_res['explained_var_pc1']:.3f}; "
          f"same-sign: {pca_res['pc1_all_same_sign']}")

    # Stage 1: sector ~ const + mkt
    df1 = pd.concat([sector_y, mkt_x], axis=1, join="inner").dropna()
    reg1 = hac_regress(df1["sector"], df1[["mkt"]])
    print(f"  [Mkt only] alpha_ann={reg1['alpha_annual']:.4f} t={reg1['alpha_tstat']:.2f} R2={reg1['r2']:.3f}")

    # Stage 2: sector ~ const + mkt + PC1  (VARIANCE attribution: market-neutral zero-mean PC1)
    df2 = pd.concat([sector_y, mkt_x, pc1_series], axis=1, join="inner").dropna()
    reg2 = hac_regress(df2["sector"], df2[["mkt", "PC1"]])
    print(f"  [Mkt+PC1 var-attr] alpha_ann={reg2['alpha_annual']:.4f} t={reg2['alpha_tstat']:.2f} R2={reg2['r2']:.3f}")

    # Stage 3: sector ~ const + mkt + SECTOR_LONG  (RETURN/PREMIUM attribution).
    # Sector-long factor = EW long return of the DISJOINT factor_pool (carries its mean =
    # sector premium). Per Codex review: only a mean-bearing traded factor can absorb the
    # alpha LEVEL. leave-out keeps it non-mechanical.
    sector_long = basket_rets[factor_pool].mean(axis=1).dropna()
    sector_long.name = "SECTOR_LONG"
    df3 = pd.concat([sector_y, mkt_x, sector_long], axis=1, join="inner").dropna()
    reg3 = hac_regress(df3["sector"], df3[["mkt", "SECTOR_LONG"]])
    print(f"  [Mkt+SectorLong premium-attr] alpha_ann={reg3['alpha_annual']:.4f} "
          f"t={reg3['alpha_tstat']:.2f} R2={reg3['r2']:.3f}")
    reg3["sector_long_mean_annual"] = float(sector_long.mean() * 252)

    alpha_shrink_pct = None  # variance-attr (PC1) shrink
    if abs(reg1["alpha_annual"]) > 1e-12:
        alpha_shrink_pct = (1 - reg2["alpha_annual"] / reg1["alpha_annual"]) * 100
    alpha_shrink_pct_premium = None  # premium-attr (sector-long) shrink — the KEY number
    if abs(reg1["alpha_annual"]) > 1e-12:
        alpha_shrink_pct_premium = (1 - reg3["alpha_annual"] / reg1["alpha_annual"]) * 100

    results[name] = {
        "tickers_present": present,
        "tickers_dropped": dropped,
        "sector_proxy": {"label": sector_label, "kind": sector_kind},
        "market_proxy": mkt,
        "pca": pca_res,
        "regression_mkt_only": reg1,
        "regression_mkt_plus_pc1_variance_attr": reg2,
        "regression_mkt_plus_sectorlong_premium_attr": reg3,
        "alpha_shrink_pct_variance_attr": alpha_shrink_pct,
        "alpha_shrink_pct_premium_attr": alpha_shrink_pct_premium,
        "etf_descriptive_baseline": etf_baseline,
        "n_drops_in_alignment_stage1": int(min(len(sector_y), len(mkt_x)) - len(df1)),
    }

    # Robustness: premium-attribution alpha across ALL balanced disjoint splits
    # (Codex CONDITIONAL note: single deterministic split is not enough for TW).
    results[name]["premium_attr_split_robustness"] = split_robustness(basket_present, basket_rets, mkt_x)
    rob = results[name]["premium_attr_split_robustness"]
    print(f"  [split robustness] n_splits={rob['n_splits']} "
          f"alpha_with_sectorlong mean={rob['alpha_with_sectorlong_mean']:.4f} "
          f"[{rob['alpha_with_sectorlong_min']:.4f}, {rob['alpha_with_sectorlong_max']:.4f}]")
    return pca_res, reg1, reg2, reg3, sector_label


def main():
    results = {
        "experiment_id": "k1423",
        "title": "PCA + factor regression: is sector-ETF alpha a real alpha or an unnamed factor exposure?",
        "seed": SEED,
        "period": {"start": START, "end": END},
        "method_note": ("Contemporaneous risk-attribution regression (sector_t ~ mkt_t [+ PC1_t]); "
                        "NOT a forecast, no lookahead. Alpha annualized = daily_alpha*252. "
                        "Newey-West HAC SE with lag=5."),
        "data_source": "yfinance (auto_adjust=True, daily log returns)",
    }

    us_pca, us_r1, us_r2, us_r3, us_sec = analyze_market("US", US_BASKET, US_ETF, US_MKT, results)
    tw_pca, tw_r1, tw_r2, tw_r3, tw_sec = analyze_market("TW", TW_BASKET, None, TW_MKT, results)

    # cross-market comparison table (PC1/PC2 from FULL-basket descriptive PCA)
    us_full = us_pca["full_basket_pca"]
    tw_full = tw_pca["full_basket_pca"]
    results["cross_market_comparison"] = {
        "pc1_explained_var": {"US": us_full["explained_var_pc1"], "TW": tw_full["explained_var_pc1"]},
        "pc2_explained_var": {"US": us_full["explained_var_pc2"], "TW": tw_full["explained_var_pc2"]},
        "alpha_annual_mkt_only": {"US": us_r1["alpha_annual"], "TW": tw_r1["alpha_annual"]},
        "alpha_tstat_mkt_only": {"US": us_r1["alpha_tstat"], "TW": tw_r1["alpha_tstat"]},
        "r2_mkt_only": {"US": us_r1["r2"], "TW": tw_r1["r2"]},
        # variance attribution (market-neutral PC1)
        "alpha_annual_with_pc1": {"US": us_r2["alpha_annual"], "TW": tw_r2["alpha_annual"]},
        "alpha_tstat_with_pc1": {"US": us_r2["alpha_tstat"], "TW": tw_r2["alpha_tstat"]},
        "r2_with_pc1": {"US": us_r2["r2"], "TW": tw_r2["r2"]},
        "alpha_shrink_pct_variance_attr": {"US": results["US"]["alpha_shrink_pct_variance_attr"],
                                           "TW": results["TW"]["alpha_shrink_pct_variance_attr"]},
        # premium attribution (leave-out sector long, the KEY test)
        "alpha_annual_with_sectorlong": {"US": us_r3["alpha_annual"], "TW": tw_r3["alpha_annual"]},
        "alpha_tstat_with_sectorlong": {"US": us_r3["alpha_tstat"], "TW": tw_r3["alpha_tstat"]},
        "r2_with_sectorlong": {"US": us_r3["r2"], "TW": tw_r3["r2"]},
        "alpha_shrink_pct_premium_attr": {"US": results["US"]["alpha_shrink_pct_premium_attr"],
                                          "TW": results["TW"]["alpha_shrink_pct_premium_attr"]},
        "frac_splits_alpha_insignificant": {
            "US": results["US"]["premium_attr_split_robustness"]["frac_splits_alpha_insignificant"],
            "TW": results["TW"]["premium_attr_split_robustness"]["frac_splits_alpha_insignificant"],
        },
        "etf_descriptive_baseline_US_SMH": results["US"]["etf_descriptive_baseline"],
    }

    # honest verdict — judged on the PREMIUM-attribution stage (the one that can absorb alpha LEVEL)
    def verdict(r1, r3):
        a1, a3 = r1["alpha_annual"], r3["alpha_annual"]
        sig1 = abs(r1["alpha_tstat"]) > 1.96
        sig3 = abs(r3["alpha_tstat"]) > 1.96
        shrink = (1 - a3 / a1) * 100 if abs(a1) > 1e-12 else 0.0
        if not sig1:
            return "alpha_not_significant_even_in_mkt_only"
        if sig1 and not sig3 and shrink > 50:
            return "alpha_significant_then_absorbed_by_sector_premium"
        if sig1 and shrink > 50:
            return "alpha_largely_absorbed_still_marginally_significant"
        if sig1 and shrink > 20:
            return "alpha_partially_absorbed"
        return "alpha_robust_to_sector_premium"

    results["verdict"] = {
        "US": verdict(us_r1, us_r3),
        "TW": verdict(tw_r1, tw_r3),
        "note": ("Variance-attribution (PC1) leaves alpha LEVEL unchanged by construction "
                 "(zero-mean market-neutral factor raises R2/beta only). The alpha-absorption "
                 "test is the premium-attribution stage (mean-bearing leave-out sector-long factor)."),
    }
    us_rob = results["US"]["premium_attr_split_robustness"]
    results["honest_conclusion"] = (
        f"US: a real semiconductor ETF (SMH) shows a headline alpha of "
        f"{results['US']['etf_descriptive_baseline']['regression_mkt_only']['alpha_annual']*100:.1f}%/yr "
        f"vs SPY (t={results['US']['etf_descriptive_baseline']['regression_mkt_only']['alpha_tstat']:.2f}, marginal). "
        f"On a clean disjoint leave-out proxy the sector alpha point estimate shrinks "
        f"substantially ({us_r1['alpha_annual']*100:.1f}%->{us_r3['alpha_annual']*100:.1f}%/yr) once a "
        f"disjoint sector-long factor is added, and becomes insignificant (t={us_r3['alpha_tstat']:.2f}) "
        f"-- but the mkt-only alpha was itself only marginally significant "
        f"(t={us_r1['alpha_tstat']:.2f}, p={us_r1['alpha_pvalue']:.3f}) and the result is split-sensitive "
        f"(35-split residual-alpha range [{us_rob['alpha_with_sectorlong_min']*100:.1f}%, "
        f"{us_rob['alpha_with_sectorlong_max']*100:.1f}%], "
        f"{us_rob['frac_splits_alpha_insignificant']*100:.0f}% of splits insignificant). "
        f"Evidence is SUGGESTIVE that the sector alpha is mostly unnamed common-factor exposure, "
        f"not decisive. TW: no significant alpha to begin with (t={tw_r1['alpha_tstat']:.2f}), so there "
        f"is nothing to absorb; TW sector cohesion is weaker (PC1 explains "
        f"{tw_full['explained_var_pc1']*100:.0f}% vs US {us_full['explained_var_pc1']*100:.0f}%). "
        f"Variance-attribution (market-neutral PC1) raises R2/beta sharply but cannot move the alpha "
        f"LEVEL by construction -- the comovement is a strong common factor, but the alpha-level "
        f"question is answered only by the mean-bearing premium-attribution stage."
    )

    out_path = HERE / "k1423_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nWrote {out_path}")

    make_charts(results, us_pca, tw_pca, us_r1, us_r2, us_r3, tw_r1, tw_r2, tw_r3)
    return results


def make_charts(results, us_pca, tw_pca, us_r1, us_r2, us_r3, tw_r1, tw_r2, tw_r3):
    # Use FULL-basket descriptive PCA for the latent-structure figures (Fig1/Fig3)
    us_pca = us_pca["full_basket_pca"]
    tw_pca = tw_pca["full_basket_pca"]
    # Fig 1: PC1/PC2 explained variance US vs TW
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ["PC1", "PC2"]
    us_vals = [us_pca["explained_var_pc1"] * 100, us_pca["explained_var_pc2"] * 100]
    tw_vals = [tw_pca["explained_var_pc1"] * 100, tw_pca["explained_var_pc2"] * 100]
    x = np.arange(len(labels))
    w = 0.35
    ax.bar(x - w / 2, us_vals, w, label="US (NVDA/AMD/TSM...)", color="#2c6fbb")
    ax.bar(x + w / 2, tw_vals, w, label="TW (2330/2454/2303...)", color="#d1495b")
    for i, v in enumerate(us_vals):
        ax.text(x[i] - w / 2, v + 0.8, f"{v:.1f}%", ha="center", fontsize=9)
    for i, v in enumerate(tw_vals):
        ax.text(x[i] + w / 2, v + 0.8, f"{v:.1f}%", ha="center", fontsize=9)
    ax.set_ylabel("Explained Variance (%)")
    ax.set_title("Semiconductor Basket PCA: PC1/PC2 Explained Variance\n(US vs TW)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "fig1_pca_explained_var.png", dpi=140)
    plt.close(fig)

    # Fig 2: alpha across 3 stages (Mkt only / +PC1 variance-attr / +SectorLong premium-attr)
    fig, ax = plt.subplots(figsize=(11, 6))
    cats = ["US\nMkt only", "US\n+PC1\n(var-attr)", "US\n+SectorLong\n(premium-attr)",
            "TW\nMkt only", "TW\n+PC1\n(var-attr)", "TW\n+SectorLong\n(premium-attr)"]
    alphas = [us_r1["alpha_annual"] * 100, us_r2["alpha_annual"] * 100, us_r3["alpha_annual"] * 100,
              tw_r1["alpha_annual"] * 100, tw_r2["alpha_annual"] * 100, tw_r3["alpha_annual"] * 100]
    tstats = [us_r1["alpha_tstat"], us_r2["alpha_tstat"], us_r3["alpha_tstat"],
              tw_r1["alpha_tstat"], tw_r2["alpha_tstat"], tw_r3["alpha_tstat"]]
    colors = ["#2c6fbb", "#7aa3d0", "#9db8d6", "#d1495b", "#df8090", "#e8a7b2"]
    bars = ax.bar(cats, alphas, color=colors)
    ymax = max(alphas) if max(alphas) > 0 else 1
    ax.set_ylim(min(0, min(alphas)) - ymax * 0.05, ymax * 1.18)
    for b, a, t in zip(bars, alphas, tstats):
        sig = "*" if abs(t) > 1.96 else ""
        # for tall bars near the top, place label INSIDE to avoid colliding with title
        if a > ymax * 0.85:
            ax.text(b.get_x() + b.get_width() / 2, a - ymax * 0.08,
                    f"{a:.1f}%\nt={t:.2f}{sig}", ha="center", va="top", fontsize=8.5, color="white")
        else:
            ax.text(b.get_x() + b.get_width() / 2, a + (ymax * 0.02 if a >= 0 else -ymax * 0.10),
                    f"{a:.1f}%\nt={t:.2f}{sig}", ha="center",
                    va="bottom" if a >= 0 else "top", fontsize=8.5)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Annualized Alpha (%)")
    ax.set_title("Sector Alpha Across Attribution Stages  (* = |t|>1.96)\n"
                 "Zero-mean PC1 leaves alpha LEVEL fixed (variance attr); mean-bearing "
                 "leave-out SectorLong is the premium-attribution test")
    fig.tight_layout()
    fig.savefig(HERE / "fig2_alpha_before_after.png", dpi=140)
    plt.close(fig)

    # Fig 3: PC1 loadings US & TW
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for ax, pca, title, color in [
        (axes[0], us_pca, "US Semiconductor Basket", "#2c6fbb"),
        (axes[1], tw_pca, "TW Semiconductor Basket", "#d1495b"),
    ]:
        load = pca["pc1_loadings"]
        names = list(load.keys())
        vals = list(load.values())
        ax.barh(names, vals, color=color)
        ax.axvline(0, color="black", lw=0.8)
        ax.set_title(f"{title}\nPC1 loadings (all same sign = common factor: {pca['pc1_all_same_sign']})")
        ax.set_xlabel("PC1 loading")
    fig.tight_layout()
    fig.savefig(HERE / "fig3_pc1_loadings.png", dpi=140)
    plt.close(fig)

    print("Charts saved: fig1_pca_explained_var.png, fig2_alpha_before_after.png, fig3_pc1_loadings.png")


if __name__ == "__main__":
    main()
