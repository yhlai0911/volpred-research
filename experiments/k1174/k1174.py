#!/usr/bin/env python3
"""K1174 — True per-stock press concentration ratio (PCR) from GDELT raw files.

Goal: Replace the K1170 hardcoded market-level PCR (Reuters Institute 2024 +
Pew + K1153 calibration — flagged circular on core-4) with an empirical,
per-stock PCR computed from actual GDELT GKG article counts in the
T-2..T+2 earnings window.

Pipeline:
  1. Load per-stock per-window GDELT mention counts from
     data/per_stock_window_counts.csv (produced by
     k1174_fetch_gdelt_files.py).
  2. For each (ticker, event_date): PCR_event = count_T0 / sum(T-2..T+2).
     Skip events where the denominator is 0 (no mentions in window at all)
     or where any window day is missing.
  3. PCR_stock = mean over event PCRs with >=1 mention in window.
  4. PCR_market_true = mean of per-stock PCRs within each market.
  5. Compare vs K1170 hardcoded PCR (Spearman rho across markets).
  6. Re-test EU-JP pair: delta_PCR(JP-EU), ratio vs cross-market SD.
  7. Per-stock panel rerun (N=153 from K1168):
       theta_EAV_i ~ log_analyst + institutions_pct + pcr_stock_i
                    + log_mcap + market_FE
     (PCR is NOW within-market varying → not absorbed by FE.)
  8. Update verdict on K1170 mechanism (strengthen / weaken / overturn).

Inputs:
  data/per_stock_window_counts.csv  (from fetch script)
  data/earnings_dates.csv
  ../k1168/k1168_per_stock_table.csv  (panel N=153)
  K1170 hardcoded per-market PCR (copied inline below)

Outputs:
  k1174_results.json
  k1174_per_stock_pcr.csv
  k1174_true_vs_hardcoded_pcr.png
  k1174_eu_jp_histogram.png

Random seed: 42.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

try:
    import statsmodels.api as sm
    HAS_SM = True
except Exception:
    HAS_SM = False

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
K1168_PANEL = HERE.parent / "k1168" / "k1168_per_stock_table.csv"

RNG = np.random.default_rng(42)

# ----------------------------------------------------------------------------
# K1170 hardcoded PCR (reference values to correlate against)
# ----------------------------------------------------------------------------
K1170_PCR = {
    "TW": 0.650,
    "EU": 0.317,
    "JP": 0.767,
    "US": 0.850,
    "KR": 0.650,
    "CA": 0.650,
    "HK": 0.667,
    "BR": 0.567,
    "CH": 0.567,  # K1170 reference only; no CH stocks in K1168 panel
    "IN": 0.517,
}
THETA_REL = {
    "TW": 0.170, "EU": 0.140, "JP": 0.390, "US": 0.590, "KR": 0.276,
    "CA": 1.448, "HK": 0.180, "BR": 1.887, "CH": 0.304, "IN": 1.170,
}
INST_PCT = {
    "TW": 0.247, "EU": 0.416, "JP": 0.425, "US": 0.750, "KR": 0.365,
    "CA": 0.552, "HK": 0.261, "BR": 0.486, "CH": 0.157, "IN": 0.383,
}


# ----------------------------------------------------------------------------
# Load counts and build per-event PCR
# ----------------------------------------------------------------------------
def load_counts() -> pd.DataFrame:
    p = DATA / "per_stock_window_counts.csv"
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}; run k1174_fetch_gdelt_files.py first.")
    df = pd.read_csv(p)
    df["event_date"] = pd.to_datetime(df["event_date"]).dt.date
    return df


def per_event_pcr(df_counts: pd.DataFrame) -> pd.DataFrame:
    """Compute PCR_event = count_T0 / sum(T-2..T+2).

    Only events with sum > 0 AND all 5 days observed (not missing) are kept.
    """
    rows = []
    for (ticker, event), sub in df_counts.groupby(["ticker", "event_date"]):
        sub = sub.sort_values("day_offset")
        # need all 5 offsets -2..+2
        offsets = set(sub["day_offset"].tolist())
        if offsets != {-2, -1, 0, 1, 2}:
            continue
        counts = sub.set_index("day_offset")["count"]
        if counts.isna().any():
            continue
        total = float(counts.sum())
        t0 = float(counts.loc[0])
        if total <= 0:
            continue  # no mentions in window; skip
        rows.append({
            "ticker": ticker,
            "event_date": event,
            "count_t0": t0,
            "count_tm2": float(counts.loc[-2]),
            "count_tm1": float(counts.loc[-1]),
            "count_tp1": float(counts.loc[1]),
            "count_tp2": float(counts.loc[2]),
            "count_total": total,
            "pcr_event": t0 / total,
        })
    return pd.DataFrame(rows)


def per_stock_pcr(events: pd.DataFrame, stock_map: pd.DataFrame) -> pd.DataFrame:
    rows = []
    name_mkt = {r.ticker: r.market for r in stock_map.itertuples()}
    for ticker, sub in events.groupby("ticker"):
        sub = sub.dropna(subset=["pcr_event"])
        if len(sub) == 0:
            continue
        rows.append({
            "ticker": ticker,
            "market": name_mkt.get(ticker),
            "n_events_with_signal": int(len(sub)),
            "mean_events_coverage": float(sub["count_total"].mean()),
            "pcr_stock": float(sub["pcr_event"].mean()),
            "pcr_stock_sd": float(sub["pcr_event"].std(ddof=1)) if len(sub) > 1 else float("nan"),
        })
    return pd.DataFrame(rows).sort_values(["market", "ticker"]).reset_index(drop=True)


# ----------------------------------------------------------------------------
# Panel rerun
# ----------------------------------------------------------------------------
def panel_rerun(panel: pd.DataFrame, pcr_stock: pd.DataFrame) -> Dict[str, Any]:
    """Panel OLS with market FE on N=153 K1168 table augmented by per-stock PCR.

    Where a stock has no true PCR (not in fetched sample), fall back to the
    per-market mean of observed PCR so every panel row has a value. We report
    how many rows used the fallback.
    """
    if not HAS_SM:
        return {"error": "statsmodels unavailable"}

    merged = panel.merge(pcr_stock[["ticker", "pcr_stock"]], on="ticker", how="left")
    # Per-market mean fallback
    market_mean = merged.groupby("market")["pcr_stock"].transform("mean")
    n_fallback = int(merged["pcr_stock"].isna().sum())
    merged["pcr_stock_filled"] = merged["pcr_stock"].fillna(market_mean)
    # If any market has no observed PCR at all, fall back to K1170 hardcoded
    k1170_map = pd.Series(K1170_PCR)
    merged["pcr_stock_filled"] = merged["pcr_stock_filled"].fillna(
        merged["market"].map(k1170_map)
    )

    specs = {
        "pcr_only_filled": ["pcr_stock_filled"],
        "pcr_analyst": ["log_analyst", "pcr_stock_filled"],
        "pcr_analyst_inst": ["log_analyst", "institutions_pct", "pcr_stock_filled"],
        "full_panel": ["log_analyst", "institutions_pct", "pcr_stock_filled", "log_mcap"],
    }

    results = {}
    for name, regs in specs.items():
        sub = merged.dropna(subset=regs + ["theta_eav"]).copy()
        if len(sub) < len(regs) + 5:
            results[name] = {"error": f"insufficient N={len(sub)}"}
            continue
        fe = pd.get_dummies(sub["market"], prefix="fe", drop_first=True)
        X = pd.concat([sub[regs].astype(float), fe.astype(float)], axis=1)
        X = sm.add_constant(X)
        Y = sub["theta_eav"].astype(float)
        m = sm.OLS(Y, X).fit(cov_type="HC0")
        results[name] = {
            "n": int(len(sub)),
            "regressors": regs,
            "params": {k: float(v) for k, v in m.params.items()},
            "tvalues": {k: float(v) for k, v in m.tvalues.items()},
            "pvalues": {k: float(v) for k, v in m.pvalues.items()},
            "r2": float(m.rsquared),
            "r2_adj": float(m.rsquared_adj),
        }

    # Within-market variant: use OBSERVED pcr_stock only (drop fallback rows)
    obs_only = merged.dropna(subset=["pcr_stock"])
    if len(obs_only) >= 25:
        fe = pd.get_dummies(obs_only["market"], prefix="fe", drop_first=True)
        X = pd.concat([
            obs_only[["log_analyst", "institutions_pct", "pcr_stock", "log_mcap"]].astype(float),
            fe.astype(float)
        ], axis=1)
        X = sm.add_constant(X)
        Y = obs_only["theta_eav"].astype(float)
        m = sm.OLS(Y, X).fit(cov_type="HC0")
        results["observed_only_full"] = {
            "n": int(len(obs_only)),
            "regressors": ["log_analyst", "institutions_pct", "pcr_stock", "log_mcap"],
            "params": {k: float(v) for k, v in m.params.items()},
            "tvalues": {k: float(v) for k, v in m.tvalues.items()},
            "pvalues": {k: float(v) for k, v in m.pvalues.items()},
            "r2": float(m.rsquared),
            "r2_adj": float(m.rsquared_adj),
        }

    results["n_fallback_used"] = n_fallback
    results["n_total_panel"] = int(len(merged))
    return results


# ----------------------------------------------------------------------------
# EU-JP pair test + cross-market comparison
# ----------------------------------------------------------------------------
def market_summary(pcr_stock: pd.DataFrame) -> pd.DataFrame:
    g = pcr_stock.groupby("market").agg(
        n_stocks=("ticker", "count"),
        true_pcr_mean=("pcr_stock", "mean"),
        true_pcr_sd=("pcr_stock", "std"),
    ).reset_index()
    g["k1170_pcr"] = g["market"].map(K1170_PCR)
    g["theta_rel"] = g["market"].map(THETA_REL)
    g["institutions_pct"] = g["market"].map(INST_PCT)
    return g


def eu_jp_pair_test(summary: pd.DataFrame, pcr_stock: pd.DataFrame) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if "EU" not in summary["market"].tolist() or "JP" not in summary["market"].tolist():
        result["skipped"] = "EU or JP missing from observed sample"
        return result
    eu = summary[summary["market"] == "EU"].iloc[0]
    jp = summary[summary["market"] == "JP"].iloc[0]
    result["eu_true_pcr_mean"] = float(eu["true_pcr_mean"])
    result["jp_true_pcr_mean"] = float(jp["true_pcr_mean"])
    result["eu_n"] = int(eu["n_stocks"])
    result["jp_n"] = int(jp["n_stocks"])
    result["delta_true_pcr_jp_minus_eu"] = float(jp["true_pcr_mean"] - eu["true_pcr_mean"])
    result["delta_k1170_pcr_jp_minus_eu"] = float(
        summary.set_index("market").loc["JP", "k1170_pcr"]
        - summary.set_index("market").loc["EU", "k1170_pcr"]
    )
    # Cross-market PCR SD (observed markets only)
    sd = float(summary["true_pcr_mean"].std(ddof=0))
    result["cross_market_sd_observed"] = sd
    result["ratio_vs_sd"] = (
        float(result["delta_true_pcr_jp_minus_eu"] / sd) if sd > 0 else None
    )
    # Welch t-test on per-stock PCR samples
    eu_vals = pcr_stock[pcr_stock["market"] == "EU"]["pcr_stock"].dropna().values
    jp_vals = pcr_stock[pcr_stock["market"] == "JP"]["pcr_stock"].dropna().values
    if len(eu_vals) >= 2 and len(jp_vals) >= 2:
        t, p = stats.ttest_ind(jp_vals, eu_vals, equal_var=False)
        result["welch_t_jp_vs_eu"] = float(t)
        result["welch_p_jp_vs_eu"] = float(p)
    else:
        result["welch_t_jp_vs_eu"] = None
        result["welch_p_jp_vs_eu"] = None
    return result


def cross_market_spearman(summary: pd.DataFrame, x: str, y: str) -> Dict[str, Any]:
    sub = summary.dropna(subset=[x, y])
    if len(sub) < 3:
        return {"n": int(len(sub)), "rho": None, "p": None}
    rho, p = stats.spearmanr(sub[x], sub[y])
    return {"n": int(len(sub)), "rho": float(rho), "p": float(p)}


# ----------------------------------------------------------------------------
# Plots
# ----------------------------------------------------------------------------
def plot_true_vs_hardcoded(summary: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    s = summary.dropna(subset=["true_pcr_mean", "k1170_pcr"])
    ax.scatter(s["k1170_pcr"], s["true_pcr_mean"], s=96, color="#2c7fb8")
    for _, r in s.iterrows():
        ax.annotate(r["market"], (r["k1170_pcr"], r["true_pcr_mean"]),
                    xytext=(6, 4), textcoords="offset points", fontsize=11)
    lims = [min(s["k1170_pcr"].min(), s["true_pcr_mean"].min()) - 0.05,
            max(s["k1170_pcr"].max(), s["true_pcr_mean"].max()) + 0.05]
    ax.plot(lims, lims, "k--", linewidth=0.7, alpha=0.5, label="y = x")
    ax.set_xlabel("K1170 hardcoded PCR")
    ax.set_ylabel("K1174 true GDELT PCR (per-market mean)")
    ax.set_title("K1174 — True vs hardcoded press concentration ratio")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def plot_eu_jp_hist(pcr_stock: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    eu = pcr_stock[pcr_stock["market"] == "EU"]["pcr_stock"].dropna().values
    jp = pcr_stock[pcr_stock["market"] == "JP"]["pcr_stock"].dropna().values
    bins = np.linspace(0, 1, 11)
    if len(eu):
        ax.hist(eu, bins=bins, alpha=0.55, label=f"EU (n={len(eu)})", color="#d95f0e")
    if len(jp):
        ax.hist(jp, bins=bins, alpha=0.55, label=f"JP (n={len(jp)})", color="#2c7fb8")
    ax.set_xlabel("per-stock PCR")
    ax.set_ylabel("# stocks")
    ax.set_title("K1174 — EU vs JP per-stock PCR histogram")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Verdict
# ----------------------------------------------------------------------------
def verdict(eu_jp: Dict[str, Any],
            cross_corr: Dict[str, Any],
            panel: Dict[str, Any],
            n_reliable_events: int = 0,
            n_stocks_observed: int = 0,
            n_markets_observed: int = 0) -> Dict[str, Any]:
    label = "PARTIAL_CONFIRMED"
    notes: List[str] = []

    # Power gate: if coverage is too thin to distinguish noise from signal,
    # we refuse to move off K1170's label and report INSUFFICIENT_COVERAGE.
    eu_n = eu_jp.get("eu_n", 0) or 0
    jp_n = eu_jp.get("jp_n", 0) or 0
    insufficient = (eu_n < 4 or jp_n < 4 or n_markets_observed < 6
                    or n_reliable_events < 30)
    if insufficient:
        notes.append(
            "INSUFFICIENT_COVERAGE: this partial GDELT sample (1/96 rate, "
            f"Jan-May 2024 only) gives EU n={eu_n}, JP n={jp_n}, "
            f"markets={n_markets_observed}, reliable events={n_reliable_events}. "
            "Per-stock and pair tests are under-powered; direction is "
            "reported for transparency but K1170's PARTIAL_CONFIRMED label "
            "is preserved pending a full 96-files-per-day or BigQuery scan."
        )
        label = "INSUFFICIENT_COVERAGE"
        # continue to collect descriptive notes but don't change label below
        locked_label = True
    else:
        locked_label = False

    # (1) EU-JP gap — decision tree ordered most-extreme first
    d = eu_jp.get("delta_true_pcr_jp_minus_eu")
    ratio = eu_jp.get("ratio_vs_sd")
    welch_p = eu_jp.get("welch_p_jp_vs_eu")
    if d is not None and d < -0.05:
        notes.append(
            f"EU-JP gap REVERSED (true ΔPCR={d:+.3f}, Welch p={welch_p}); "
            "K1170 direction overturned."
        )
        if not locked_label:
            label = "OVERTURNED"
    elif d is not None and d > 0.1:
        notes.append(f"EU-JP gap POSITIVE (true ΔPCR={d:+.3f}, ratio={ratio})")
        if ratio is not None and ratio >= 1.0 and not locked_label:
            label = "STRENGTHENED"
    elif d is not None and abs(d) <= 0.05:
        notes.append(f"EU-JP gap NEAR-ZERO (true ΔPCR={d:+.3f}); K1170 claim fails")
        if not locked_label:
            label = "WEAKENED"

    # (2) Cross-market ρ(true, K1170)
    rho_cross = cross_corr.get("rho")
    if rho_cross is not None:
        if rho_cross >= 0.7:
            notes.append(
                f"True-vs-K1170 cross-market ρ={rho_cross:.3f} HIGH → "
                "hardcoded calibration holds up empirically.")
        elif rho_cross >= 0.3:
            notes.append(
                f"True-vs-K1170 cross-market ρ={rho_cross:.3f} MODEST.")
        else:
            notes.append(
                f"True-vs-K1170 cross-market ρ={rho_cross:.3f} LOW → "
                "hardcoded calibration poorly aligned with GDELT.")

    # (3) Per-stock panel
    obs = panel.get("observed_only_full")
    if isinstance(obs, dict) and "tvalues" in obs:
        t = obs["tvalues"].get("pcr_stock")
        if t is not None and abs(t) > 2.0:
            notes.append(f"Observed-only panel: pcr_stock t={t:+.2f} SIGNIFICANT")
            if not locked_label and label not in {"STRENGTHENED", "OVERTURNED"}:
                label = "STRENGTHENED"
        else:
            notes.append(f"Observed-only panel: pcr_stock t={t} NS")

    full = panel.get("full_panel")
    if isinstance(full, dict) and "tvalues" in full:
        t = full["tvalues"].get("pcr_stock_filled")
        n_fb = panel.get("n_fallback_used", 0)
        n_tot = panel.get("n_total_panel", 0)
        notes.append(
            f"Filled full panel (N={full['n']}, {n_fb}/{n_tot} used"
            f" per-market-mean fallback): pcr_stock_filled t={t}"
        )
        if t is not None and abs(t) > 3.0:
            notes.append(
                "  -> Harvey |t|>3 PASS, BUT driven by between-market"
                " variation with large imputation share. Treated as"
                " suggestive, not confirmatory."
            )

    return {"label": label, "notes": notes,
            "method": "true per-stock PCR from GDELT GKG raw files (12:00 UTC slice)"}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    counts = load_counts()
    stock_map = pd.read_csv(DATA / "stock_company_map.csv")
    events_all = per_event_pcr(counts)
    events_all.to_csv(DATA / "per_event_pcr.csv", index=False)

    # Reliability filter: with ~1/96 GDELT sampling, events with very few
    # total mentions give near-binary PCR (0 or 1 depending on which day the
    # single article lands). Events with >= MIN_MENTIONS in the 5-day window
    # are treated as reliable.
    MIN_MENTIONS = 5
    events = events_all[events_all["count_total"] >= MIN_MENTIONS].copy()
    pcr_stock = per_stock_pcr(events, stock_map)
    pcr_stock.to_csv(HERE / "k1174_per_stock_pcr.csv", index=False)
    # Also emit the unfiltered version for full transparency
    per_stock_pcr(events_all, stock_map).to_csv(
        HERE / "k1174_per_stock_pcr_unfiltered.csv", index=False
    )

    summary = market_summary(pcr_stock)

    # EU-JP pair test
    eu_jp = eu_jp_pair_test(summary, pcr_stock)
    # Cross-market Spearman: true pcr vs K1170 hardcoded
    cross_corr = cross_market_spearman(summary, "k1170_pcr", "true_pcr_mean")
    # Cross-market Spearman: true pcr vs theta_rel
    pcr_vs_theta = cross_market_spearman(summary, "true_pcr_mean", "theta_rel")

    # Panel rerun
    panel_raw = pd.read_csv(K1168_PANEL)
    panel_result = panel_rerun(panel_raw, pcr_stock)

    ver = verdict(
        eu_jp, cross_corr, panel_result,
        n_reliable_events=int(len(events)),
        n_stocks_observed=int(len(pcr_stock)),
        n_markets_observed=int(summary["market"].nunique()),
    )

    # Preamble Rule #5 self-challenge — per-stock PCR t > 6 check
    obs = panel_result.get("observed_only_full", {})
    t_obs = obs.get("tvalues", {}).get("pcr_stock") if isinstance(obs, dict) else None
    rule5_triggered = (t_obs is not None and abs(t_obs) > 6.0)

    out = {
        "experiment_id": "k1174",
        "title": "True per-stock PCR from GDELT raw files — supersedes K1170 hardcoded",
        "proposer": "Claude (K1170 §7 limitation; rerun request)",
        "executor": "Claude",
        "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "random_seed": 42,
        "data_sources": [
            "GDELT GKG 2.1 raw CSV.zip files (one per unique earnings-window day at"
            " 12:00 UTC; fetched by k1174_fetch_gdelt_files.py)",
            "yfinance earnings_dates (2024-01 to 2025-12)",
            "experiments/k1168/k1168_per_stock_table.csv (panel N=153)",
            "K1170 hardcoded PCR (for comparison only; see k1170_results.json)",
        ],
        "sampling_disclosure": (
            "One 15-min GKG slice (12:00 UTC) per calendar day; ~1/96 ≈ 1.04% of"
            " full-day GDELT news volume. Relative PCR estimable if sampling"
            " rate is uncorrelated with T0 vs T±2 positioning."
        ),
        "n_events_all": int(len(events_all)),
        "n_events_reliable": int(len(events)),
        "min_mentions_filter": int(MIN_MENTIONS),
        "median_event_mentions": float(events_all["count_total"].median()) if len(events_all) else None,
        "n_stocks_with_pcr": int(len(pcr_stock)),
        "n_markets_observed": int(summary["market"].nunique()),
        "per_market_summary": summary.round(6).to_dict(orient="records"),
        "cross_market_spearman_true_vs_k1170": cross_corr,
        "cross_market_spearman_true_vs_theta_rel": pcr_vs_theta,
        "eu_jp_pair_test": eu_jp,
        "panel_rerun": panel_result,
        "verdict_vs_k1170": ver,
        "preamble_rule5_self_check": {
            "rule5_triggered": bool(rule5_triggered),
            "note": (
                "Per-preamble: if observed-only panel |t(pcr_stock)| > 6.0 we"
                " must self-challenge (possible circularity / mechanical"
                " correlation with θ_EAV_i)."
            ),
        },
    }
    (HERE / "k1174_results.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )

    # Plots
    if len(summary) >= 2:
        plot_true_vs_hardcoded(summary, HERE / "k1174_true_vs_hardcoded_pcr.png")
    if eu_jp.get("eu_n") and eu_jp.get("jp_n"):
        plot_eu_jp_hist(pcr_stock, HERE / "k1174_eu_jp_histogram.png")

    # Print summary
    print("\n=== K1174 RESULTS ===")
    print(f"Events with signal: {len(events)}")
    print(f"Stocks with PCR:    {len(pcr_stock)}")
    print(f"Markets observed:   {summary['market'].nunique()}")
    print("\nPer-market summary:")
    print(summary.round(3).to_string(index=False))
    print(f"\nCross-market ρ(true PCR, K1170 hardcoded) = {cross_corr}")
    print(f"Cross-market ρ(true PCR, θ_rel)          = {pcr_vs_theta}")
    print(f"\nEU-JP pair test: {eu_jp}")
    print(f"\nVerdict: {ver['label']}")
    for n in ver["notes"]:
        print(f"  - {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
