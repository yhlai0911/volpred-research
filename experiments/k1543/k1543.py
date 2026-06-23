"""
K1543 — Listed infrastructure ETF inflation-hedge:
真效應還是 energy + duration beta artifact?

Falsifiable claim:
  在 inflation-shock days, listed infra ETF (IFRA/NFRA/IGF/PAVE/GRID/UTF/XLU)
  的 RV、downside semivariance、equity correlation 顯著低於 SPY，
  且此效應在控制 energy beta (XLE) + duration beta (TLT/IEF) + VIX 後仍 survive。
  若 H4 controlled regression β1 → 0 → composite-beta artifact (NULL).

Differentiation vs K1508:
  K1508 測 AI power demand → utility ETF vol regime → NULL.
  K1543 測 inflation-hedge mechanism + controlled-regression falsification.
  不同 outcome、不同 driver、不同 hypothesis structure.

Data:
  yfinance (12 tickers) + FRED (CPIAUCSL, PPIACO, T5YIE, T10YIE) via HTTP CSV.
  Period: 2014-01-01 to 2026-06-22.

Method (4-tier):
  H1 raw RV         : paired t-test + Wilcoxon (ETF RV vs SPY RV in shock days)
  H2 semivariance   : paired t-test (downside RV)
  H3 correlation    : Fisher-z transform comparing shock vs baseline regime
  H4 controlled reg : log(rv_etf/rv_spy)_t = a + b1*shock_{t-1}
                       + b2*|r_xle|_{t-1} + b3*|r_tlt|_{t-1} + b4*vix_{t-1} + e
                      HAC standard errors.

Bonferroni: 7 ETFs * 4 tests = 28 cells, alpha=0.05/28=0.001786.

Lookahead: all predictors .shift(1); seed=42.
"""
from __future__ import annotations

import io
import json
import os
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")
np.random.seed(42)

OUTDIR = Path(__file__).parent
FRED_KEY = os.environ.get("FRED_API_KEY")
if not FRED_KEY:
    raise RuntimeError(
        "FRED_API_KEY env var not set. Source .env.local or export it before running."
    )

INFRA_ETFS = ["IFRA", "NFRA", "IGF", "PAVE", "GRID", "UTF", "XLU"]
CONTROLS = ["SPY", "XLE", "TLT", "IEF", "^VIX"]
START = "2014-01-01"
END = "2026-06-22"

ALPHA_RAW = 0.05
N_CELLS = len(INFRA_ETFS) * 4
ALPHA_BONF = ALPHA_RAW / N_CELLS  # ~0.001786


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def fred_series(series_id: str) -> pd.Series:
    """Download a FRED series via fredgraph CSV (no fredapi dep)."""
    url = (
        f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
        f"&api_key={FRED_KEY}&file_type=json&observation_start={START}"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    obs = r.json()["observations"]
    df = pd.DataFrame(obs)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    s = df.set_index("date")["value"].dropna()
    s.name = series_id
    return s


def load_prices() -> pd.DataFrame:
    """Download adjusted close for all tickers."""
    tickers = INFRA_ETFS + CONTROLS
    print(f"[data] downloading {len(tickers)} tickers from yfinance ...")
    df = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
    )["Close"]
    df = df.dropna(how="all")
    avail = df.notna().sum()
    print(f"[data] non-NaN counts:\n{avail}")
    return df


def build_panel() -> pd.DataFrame:
    prices = load_prices()
    log_ret = np.log(prices).diff()
    log_ret.columns = [c.replace("^", "") for c in log_ret.columns]

    # 20d rolling RV (annualized variance proxy: sum of sq daily log rets * 252/20)
    rv20 = (log_ret.pow(2)).rolling(20, min_periods=15).sum() * (252.0 / 20.0)

    # Downside semivariance (only negative returns)
    neg = log_ret.where(log_ret < 0, 0.0)
    sv20 = (neg.pow(2)).rolling(20, min_periods=15).sum() * (252.0 / 20.0)

    # Rolling 60d correlation each ETF with SPY
    corr60 = pd.DataFrame(index=log_ret.index, columns=INFRA_ETFS, dtype=float)
    for etf in INFRA_ETFS:
        if etf in log_ret.columns:
            corr60[etf] = log_ret[etf].rolling(60, min_periods=40).corr(log_ret["SPY"])

    panel = pd.DataFrame(index=log_ret.index)
    for c in log_ret.columns:
        panel[f"r_{c}"] = log_ret[c]
        panel[f"rv_{c}"] = rv20[c]
        panel[f"sv_{c}"] = sv20[c]
    for etf in INFRA_ETFS:
        panel[f"corr_{etf}_SPY"] = corr60[etf]

    # Keep raw VIX close as level (not return / not RV) — needed for H4 vix_lag
    vix_level = prices["^VIX"].rename("vix_level")
    panel = panel.join(vix_level, how="left")

    # FRED series
    print("[data] downloading FRED CPIAUCSL, PPIACO, T5YIE, T10YIE ...")
    cpi = fred_series("CPIAUCSL")
    ppi = fred_series("PPIACO")
    t5 = fred_series("T5YIE")
    t10 = fred_series("T10YIE")

    # CPI/PPI MoM percent change (release date conservatively = month_end + 14 trading days lag)
    cpi_mom = cpi.pct_change() * 100.0
    ppi_mom = ppi.pct_change() * 100.0

    # 12m trailing mean deviation = "surprise" proxy
    cpi_dev = cpi_mom - cpi_mom.rolling(12, min_periods=6).mean()
    ppi_dev = ppi_mom - ppi_mom.rolling(12, min_periods=6).mean()

    # CPI release lag: BLS releases CPI ~10-15 calendar days after month end.
    # Conservative proxy: align to date_index + 15 calendar days.
    cpi_dev_daily = cpi_dev.copy()
    cpi_dev_daily.index = cpi_dev_daily.index + pd.Timedelta(days=15)
    ppi_dev_daily = ppi_dev.copy()
    ppi_dev_daily.index = ppi_dev_daily.index + pd.Timedelta(days=15)

    panel = panel.join(
        cpi_dev_daily.rename("cpi_dev"), how="left"
    ).join(ppi_dev_daily.rename("ppi_dev"), how="left")
    panel["cpi_dev"] = panel["cpi_dev"].ffill(limit=20)
    panel["ppi_dev"] = panel["ppi_dev"].ffill(limit=20)

    # Breakeven inflation
    t5_d = t5.reindex(panel.index).ffill(limit=5)
    t10_d = t10.reindex(panel.index).ffill(limit=5)
    panel["t5yie"] = t5_d
    panel["t10yie"] = t10_d
    panel["dbe5"] = t5_d.diff() * 100.0  # ΔBP

    return panel


# ---------------------------------------------------------------------------
# Inflation-shock day labeling
# ---------------------------------------------------------------------------
def label_shocks(panel: pd.DataFrame) -> pd.Series:
    """
    Shock day = either:
      (a) within ±5 trading days of a CPI release date proxy
          (we proxy a "CPI release day" = first trading day on/after CPI release date proxy index)
      (b) |Δ breakeven_5y| > 5 bp single-day move
    All lagged with .shift(1) downstream.
    """
    # Detect month transitions in cpi_dev (new release each month)
    cpi_release_marks = pd.Series(0, index=panel.index)
    last_val = np.nan
    for dt in panel.index:
        v = panel.loc[dt, "cpi_dev"]
        if pd.notna(v) and v != last_val:
            cpi_release_marks.loc[dt] = 1
            last_val = v
    # Use causal (right-aligned) post-release window:
    # mark days where any CPI release happened within trailing 5 trading days.
    # Avoids center=True future-leakage (Codex review issue #3).
    cpi_window = cpi_release_marks.rolling(6, min_periods=1).sum() > 0

    breakeven_shock = panel["dbe5"].abs() > 5.0
    shock = (cpi_window | breakeven_shock.fillna(False)).astype(int)
    shock.name = "shock"
    return shock


# ---------------------------------------------------------------------------
# Hypothesis tests
# ---------------------------------------------------------------------------
def paired_compare(
    series_etf: pd.Series, series_spy: pd.Series, mask: pd.Series
) -> dict:
    """
    Paired comparison on shock-day subset.
    H0: mean(ETF) = mean(SPY); H1: ETF < SPY (hedge = lower).
    Both paired t-test (one-sided) and Wilcoxon signed-rank (two-sided fallback).
    """
    e = series_etf[mask].dropna()
    s = series_spy[mask].dropna()
    common = e.index.intersection(s.index)
    e = e.loc[common]
    s = s.loc[common]
    n = len(e)
    if n < 30:
        return {
            "n": int(n),
            "mean_etf": float("nan"),
            "mean_spy": float("nan"),
            "diff": float("nan"),
            "t_stat": float("nan"),
            "p_t_one_sided": float("nan"),
            "p_wilcoxon": float("nan"),
            "note": "n<30",
        }
    diff = e - s
    t_stat, p_two = stats.ttest_1samp(diff, 0.0)
    # One-sided: H1: ETF < SPY -> diff < 0
    p_one = p_two / 2 if t_stat < 0 else 1 - p_two / 2
    try:
        _, p_w = stats.wilcoxon(diff, alternative="less")
    except Exception:
        p_w = float("nan")
    return {
        "n": int(n),
        "mean_etf": float(e.mean()),
        "mean_spy": float(s.mean()),
        "diff": float(diff.mean()),
        "t_stat": float(t_stat),
        "p_t_one_sided": float(p_one),
        "p_wilcoxon": float(p_w),
    }


def corr_regime_compare(
    corr_series: pd.Series, shock_mask: pd.Series
) -> dict:
    """
    H3: 60d rolling corr(ETF, SPY) lower in shock regime than baseline.
    Fisher z-transform then Welch t-test (different sample sizes).
    """
    c = corr_series.dropna()
    sm_mask = shock_mask.reindex(c.index).fillna(0).astype(bool)
    c_shock = c[sm_mask]
    c_base = c[~sm_mask]
    n1, n2 = len(c_shock), len(c_base)
    if n1 < 30 or n2 < 30:
        return {
            "n_shock": int(n1),
            "n_base": int(n2),
            "mean_corr_shock": float("nan"),
            "mean_corr_base": float("nan"),
            "z_diff": float("nan"),
            "p_one_sided": float("nan"),
            "note": "insufficient",
        }
    # Fisher z
    def fz(x: pd.Series) -> pd.Series:
        x = x.clip(-0.999, 0.999)
        return 0.5 * np.log((1 + x) / (1 - x))

    z1, z2 = fz(c_shock), fz(c_base)
    m1, m2 = z1.mean(), z2.mean()
    v1, v2 = z1.var(ddof=1) / n1, z2.var(ddof=1) / n2
    z_stat = (m1 - m2) / np.sqrt(v1 + v2)
    # H1: shock corr < base corr -> z_stat < 0
    p_one = stats.norm.cdf(z_stat)
    return {
        "n_shock": int(n1),
        "n_base": int(n2),
        "mean_corr_shock": float(c_shock.mean()),
        "mean_corr_base": float(c_base.mean()),
        "z_diff": float(z_stat),
        "p_one_sided": float(p_one),
    }


def controlled_regression(panel: pd.DataFrame, etf: str, shock_raw: pd.Series) -> dict:
    """
    H4: log(rv_etf/rv_spy)_t = a + b1*shock_{t-1}
        + b2*|r_xle|_{t-1} + b3*|r_tlt|_{t-1} + b4*vix_{t-1} + e
    HAC (Newey-West) standard errors, lag=10.

    Codex review fix:
    - Accept *unlagged* shock_raw and apply .shift(1) once here (avoid double lag).
    - Use VIX level (panel['vix_level']), not rv_VIX.
    """
    rv_e = panel[f"rv_{etf}"]
    rv_s = panel["rv_SPY"]
    y = np.log(rv_e / rv_s)
    X = pd.DataFrame(
        {
            "shock_lag": shock_raw.reindex(panel.index).shift(1),
            "abs_r_xle_lag": panel["r_XLE"].abs().shift(1),
            "abs_r_tlt_lag": panel["r_TLT"].abs().shift(1),
            "vix_lag": panel["vix_level"].shift(1),
        }
    )

    df_reg = pd.concat([y.rename("y"), X], axis=1).dropna()
    if len(df_reg) < 200:
        return {"n": int(len(df_reg)), "note": "insufficient n"}
    Xc = sm.add_constant(df_reg[["shock_lag", "abs_r_xle_lag", "abs_r_tlt_lag", "vix_lag"]])
    yc = df_reg["y"]
    try:
        model = sm.OLS(yc, Xc).fit(cov_type="HAC", cov_kwds={"maxlags": 10})
    except Exception as exc:
        return {"n": int(len(df_reg)), "error": str(exc)}
    return {
        "n": int(len(df_reg)),
        "beta1_shock": float(model.params["shock_lag"]),
        "beta1_se": float(model.bse["shock_lag"]),
        "beta1_p_two_sided": float(model.pvalues["shock_lag"]),
        "beta2_xle": float(model.params["abs_r_xle_lag"]),
        "beta3_tlt": float(model.params["abs_r_tlt_lag"]),
        "beta4_vix": float(model.params["vix_lag"]),
        "r2": float(model.rsquared),
        "intercept": float(model.params["const"]),
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------
def run() -> dict:
    panel = build_panel()
    panel.to_parquet(OUTDIR / "k1543_panel.parquet")
    shock_raw = label_shocks(panel)
    shock = shock_raw.shift(1).fillna(0).astype(int)  # all forward-facing → .shift(1)
    panel["shock_lag"] = shock

    # Period coverage
    coverage = {
        "panel_n": int(len(panel)),
        "shock_n": int(shock.sum()),
        "shock_pct": float(shock.mean()),
        "first": str(panel.index[0].date()),
        "last": str(panel.index[-1].date()),
        "etf_first_dates": {
            etf: str(panel[f"rv_{etf}"].dropna().index.min().date())
            if not panel[f"rv_{etf}"].dropna().empty
            else None
            for etf in INFRA_ETFS
        },
    }

    results = {
        "experiment_id": "K1543",
        "title": "Listed infrastructure inflation-hedge — energy+duration beta controlled",
        "run_at": datetime.utcnow().isoformat() + "Z",
        "seed": 42,
        "config": {
            "etfs": INFRA_ETFS,
            "controls": CONTROLS,
            "period": [START, END],
            "rv_window": 20,
            "corr_window": 60,
            "alpha_raw": ALPHA_RAW,
            "alpha_bonferroni": ALPHA_BONF,
            "n_cells": N_CELLS,
        },
        "coverage": coverage,
        "tests": {"H1_rv": {}, "H2_semivar": {}, "H3_corr": {}, "H4_regression": {}},
    }

    shock_mask = shock.astype(bool)

    for etf in INFRA_ETFS:
        rv_etf = panel[f"rv_{etf}"]
        sv_etf = panel[f"sv_{etf}"]
        rv_spy = panel["rv_SPY"]
        sv_spy = panel["sv_SPY"]
        corr_etf = panel[f"corr_{etf}_SPY"]

        results["tests"]["H1_rv"][etf] = paired_compare(rv_etf, rv_spy, shock_mask)
        results["tests"]["H2_semivar"][etf] = paired_compare(sv_etf, sv_spy, shock_mask)
        results["tests"]["H3_corr"][etf] = corr_regime_compare(corr_etf, shock_mask)
        # H4 takes the unlagged shock_raw (.shift(1) applied inside the regression).
        results["tests"]["H4_regression"][etf] = controlled_regression(panel, etf, shock_raw)

    # Count significant cells (one-sided p < alpha; for regression, use one-sided lower-tail of beta1)
    raw_pass = 0
    bonf_pass = 0
    detail_flags: list[dict] = []

    def p_value_for(test_name: str, cell: dict) -> float:
        if test_name == "H1_rv":
            return cell.get("p_t_one_sided", float("nan"))
        if test_name == "H2_semivar":
            return cell.get("p_t_one_sided", float("nan"))
        if test_name == "H3_corr":
            return cell.get("p_one_sided", float("nan"))
        if test_name == "H4_regression":
            beta = cell.get("beta1_shock", float("nan"))
            p2 = cell.get("beta1_p_two_sided", float("nan"))
            # One-sided lower-tail (H1: beta1 < 0)
            if pd.notna(beta) and pd.notna(p2):
                return p2 / 2 if beta < 0 else 1 - p2 / 2
            return float("nan")
        return float("nan")

    for test_name, etfs_d in results["tests"].items():
        for etf, cell in etfs_d.items():
            p = p_value_for(test_name, cell)
            cell["p_one_sided_canonical"] = p
            flag_raw = pd.notna(p) and p < ALPHA_RAW
            flag_bonf = pd.notna(p) and p < ALPHA_BONF
            cell["sig_raw"] = bool(flag_raw)
            cell["sig_bonferroni"] = bool(flag_bonf)
            if flag_raw:
                raw_pass += 1
            if flag_bonf:
                bonf_pass += 1
            detail_flags.append(
                {"test": test_name, "etf": etf, "p": float(p) if pd.notna(p) else None,
                 "raw": bool(flag_raw), "bonf": bool(flag_bonf)}
            )

    # H4 specific summary (KEY)
    h4_betas = [
        c["beta1_shock"]
        for c in results["tests"]["H4_regression"].values()
        if "beta1_shock" in c
    ]
    h4_sig_raw = sum(
        1
        for c in results["tests"]["H4_regression"].values()
        if c.get("sig_raw")
    )
    h4_sig_neg = sum(
        1
        for c in results["tests"]["H4_regression"].values()
        if "beta1_shock" in c and c["beta1_shock"] < 0 and c.get("sig_raw")
    )

    results["summary"] = {
        "raw_pass_count": int(raw_pass),
        "bonferroni_pass_count": int(bonf_pass),
        "alpha_raw": ALPHA_RAW,
        "alpha_bonferroni": ALPHA_BONF,
        "h4_beta1_median": float(np.nanmedian(h4_betas)) if h4_betas else None,
        "h4_beta1_min": float(np.nanmin(h4_betas)) if h4_betas else None,
        "h4_beta1_max": float(np.nanmax(h4_betas)) if h4_betas else None,
        "h4_sig_count_raw": int(h4_sig_raw),
        "h4_sig_negative_count_raw": int(h4_sig_neg),
    }

    # Sub-period robustness: 2014-2019 vs 2020-2026
    def subperiod_h4(start: str, end: str) -> dict:
        mask = (panel.index >= start) & (panel.index < end)
        sub_panel = panel[mask].copy()
        # Pass UNLAGGED raw shock; controlled_regression() applies .shift(1).
        sub_shock_raw = shock_raw[mask]
        out = {}
        for etf in INFRA_ETFS:
            if sub_panel[f"rv_{etf}"].dropna().shape[0] < 200:
                continue
            out[etf] = controlled_regression(sub_panel, etf, sub_shock_raw)
        return out

    results["robustness"] = {
        "subperiod_2014_2019": subperiod_h4("2014-01-01", "2020-01-01"),
        "subperiod_2020_2026": subperiod_h4("2020-01-01", END),
    }

    # Verdict
    if h4_sig_neg >= 4:
        verdict = "CONFIRMED_HEDGE"
        reason = f"H4 controlled regression: {h4_sig_neg}/7 ETFs show beta1<0 and sig at alpha={ALPHA_RAW}"
    elif h4_sig_neg >= 2:
        verdict = "MIXED"
        reason = f"H4 partial: only {h4_sig_neg}/7 ETFs survive controlled regression"
    else:
        verdict = "NULL_REJECTED_HEDGE"
        reason = (
            f"H4 controlled regression: only {h4_sig_neg}/7 ETFs show sig negative beta1 "
            f"after controlling energy+duration+VIX → composite-beta artifact rather than infra-specific hedge"
        )
    results["verdict_summary"] = {
        "interpretation": verdict,
        "reasoning": reason,
        "caveats": [
            "CPI/PPI surprise proxy uses FRED released data with conservative +15 calendar day lag, "
            "not Bloomberg consensus surprise (real-time vintage not used). May understate true surprise magnitude.",
            "Breakeven inflation T5YIE only available from 2003+; sample covers 2014+.",
            "Some infra ETFs (PAVE, IFRA, GRID) launched 2017+, limiting their effective n.",
            "Bonferroni adjustment is conservative; cells correlated across ETFs (especially UTF/XLU share utility exposure).",
            "Inflation-shock definition (±5d CPI window OR |ΔBE5|>5bp) is one of many possible specs; "
            "robustness to alternative thresholds not exhausted.",
            "All ETF data from yfinance (adjusted close); no intraday TAQ data used.",
            "VIX uses SPY 20d RV as fallback if VIX series missing; verify rv_VIX column populated.",
        ],
    }

    # Save JSON
    with open(OUTDIR / "k1543_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[done] results saved. verdict={verdict}, raw={raw_pass}/28, bonf={bonf_pass}/28")
    print(f"[done] H4 beta1 median={results['summary']['h4_beta1_median']}, "
          f"sig_neg={h4_sig_neg}/7")

    # Figures
    make_figures(panel, shock_mask, results)
    return results


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def make_figures(panel: pd.DataFrame, shock_mask: pd.Series, results: dict) -> None:
    # Fig 1: RV boxplot by regime
    fig, ax = plt.subplots(1, 1, figsize=(11, 6))
    data = []
    labels = []
    for etf in INFRA_ETFS + ["SPY"]:
        rv = panel[f"rv_{etf}"]
        rv_s = rv[shock_mask].dropna()
        rv_b = rv[~shock_mask].dropna()
        data.append(rv_s.values)
        data.append(rv_b.values)
        labels.append(f"{etf}\nshock")
        labels.append(f"{etf}\nbase")
    bp = ax.boxplot(data, labels=labels, showfliers=False, patch_artist=True)
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor("salmon" if i % 2 == 0 else "lightgray")
    ax.set_ylabel("20d realized variance (annualized)")
    ax.set_title("K1543 Fig 1 — 20d RV by regime (shock=salmon, baseline=gray)")
    ax.tick_params(axis="x", labelsize=7)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(OUTDIR / "fig1.png", dpi=120)
    plt.close()

    # Fig 2: forest plot H4 beta1 with 95% CI
    fig, ax = plt.subplots(1, 1, figsize=(9, 6))
    rows = []
    for etf in INFRA_ETFS:
        c = results["tests"]["H4_regression"][etf]
        if "beta1_shock" in c:
            b = c["beta1_shock"]
            se = c["beta1_se"]
            rows.append((etf, b, b - 1.96 * se, b + 1.96 * se, c.get("sig_raw", False)))
    rows.sort(key=lambda x: x[1])
    ys = np.arange(len(rows))
    for i, (etf, b, lo, hi, sig) in enumerate(rows):
        color = "red" if (sig and b < 0) else ("darkblue" if sig else "gray")
        ax.errorbar(b, i, xerr=[[b - lo], [hi - b]], fmt="o", color=color, capsize=4)
        ax.text(hi + 0.005, i, etf, va="center", fontsize=10)
    ax.axvline(0, color="black", linestyle="--", linewidth=0.8)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlabel("β1 (shock_lag coefficient on log(rv_ETF/rv_SPY))")
    ax.set_title(
        f"K1543 Fig 2 — H4 controlled regression β1 forest plot\n"
        f"(red=sig negative=hedge survives; gray=non-sig)"
    )
    plt.tight_layout()
    plt.savefig(OUTDIR / "fig2.png", dpi=120)
    plt.close()
    print("[fig] fig1.png + fig2.png saved")


if __name__ == "__main__":
    run()
