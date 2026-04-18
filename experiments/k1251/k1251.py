#!/usr/bin/env python3
"""
K1251: K719 rebuild — Table 8 Hedging Cost-Benefit (CB) ratios, structured.
===========================================================================
K1231 option (a) execution for K719 per `docs/paper-guide.md` 三方一致 rule.

Context
-------
Paper 8 (volatility-absorption) Table 8 ("Hedging Cost-Benefit Ratio by VIX
Regime") was originally documented in K719 as a qualitative synthesis, with
no structured JSON. reproduce_report.json marks T8 at 0/3 match, 3
untraceable — the canonical values (Calm=13.7x, Elevated=8.0x, High=3.6x)
sit in K719 text but are not emitted by any script.

K1231 recommended option (a): build a structured reproducible script that
computes the CB ratios from raw SPY/VIX data so Table 8 reaches 3/3
reproduce. This file is that script. K719 original files are untouched;
K1251 is the new owner of the Table 8 CB computation.

Methodology (paper main_v2.tex lines 472-497)
---------------------------------------------
- VIX regimes (3-bin, as in Table 8):
    * Calm:     V < 15
    * Elevated: 15 <= V < 25
    * High:     V >= 25
- Shock day: |Delta VIX| > 2  (same filter used across Tables 3-7)
- Avg Shock Loss (%): mean |SPY log return * 100| on shock days in regime
- Daily Hedge Cost (%) = daily VRP proxy, using the paper's formula:
      VRP_t = VIX_t^2 / 252 - RV_t / 252
  We test two RV windows: 20-day (Section 7.3) and 22-day (Section 3.7 and K720),
  and pick the one closest to paper body values (22 is K720 primary).
- CB Ratio = Avg Shock Loss / Daily Hedge Cost

Data
----
yfinance SPY + ^VIX, 2006-01-01 to 2026-03-31 (same window as K716/K718/K720).

Outputs
-------
- k1251_results.json              : structured CB table + raw per-regime numbers
- k1251_vs_paper_table8.md        : allclose verdict per cell (3 rows x 3 cols)

Strict rules
------------
- Do NOT modify K719 original files.
- Fixed seed 42.
- If data download fails -> BLOCKED (documented in README and results).
- Worktree scope: experiments/k1251/ only.
"""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

START = "2006-01-01"
END = "2026-03-31"
SHOCK_THRESHOLD = 2.0  # |Delta VIX| > 2 (paper baseline)

# Paper Table 8 canonical values (main_v2.tex lines 485-487)
PAPER_TABLE8 = {
    "Calm": {"shock_loss_pct": 1.18, "hedge_cost_pct": 0.086, "cb_ratio": 13.7},
    "Elevated": {"shock_loss_pct": 1.56, "hedge_cost_pct": 0.196, "cb_ratio": 8.0},
    "High": {"shock_loss_pct": 2.61, "hedge_cost_pct": 0.725, "cb_ratio": 3.6},
}

# Paper Table 8 regime definitions (3-bin)
REGIMES = [
    ("Calm", lambda v: v < 15),
    ("Elevated", lambda v: (v >= 15) & (v < 25)),
    ("High", lambda v: v >= 25),
]

OUT_DIR = Path(__file__).parent


def download_data():
    """Download SPY and VIX via yfinance. Return DataFrame with log returns and VIX."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed; cannot download data")

    tickers = ["SPY", "^VIX"]
    raw = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)

    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned empty frame")

    close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
    spy = close["SPY"].dropna()
    vix = close["^VIX"].dropna()

    df = pd.DataFrame({"SPY": spy, "VIX": vix}).dropna()
    df["SPY_ret"] = np.log(df["SPY"] / df["SPY"].shift(1)) * 100.0  # log return in %
    df["dVIX"] = df["VIX"].diff()
    df = df.dropna()
    return df


def compute_realized_variance(df: pd.DataFrame, window: int) -> pd.Series:
    """Rolling realized variance of daily log returns (in %^2), window days.

    Paper Section 3.7: RV_t = sum_{i=1}^{W} r_{t-W+i}^2 over window W.
    We use rolling sum of squared daily log returns (already in %). The
    daily-scale VRP then divides VIX^2 by 252 to match the paper's formula
    and divides RV by 252 (VIX^2 annualized / 252 vs RV sum / 252).
    """
    r2 = df["SPY_ret"] ** 2
    return r2.rolling(window=window).sum()


def compute_daily_vrp(df: pd.DataFrame, rv_window: int) -> pd.Series:
    """Daily VRP proxy used in Table 8:

        VRP_t = VIX_t^2 / 252 - RV_t / 252

    Note: paper notes explicitly say "proxied by the daily VRP (VIX^2/252 - RV/252)".
    We treat the hedge cost as max(VRP, 0) for CB-ratio semantics (a negative
    daily cost would invert the ratio). We also report the raw VRP mean.
    """
    rv = compute_realized_variance(df, rv_window)
    vrp = (df["VIX"] ** 2) / 252.0 - rv / 252.0
    return vrp


def assign_regime(vix_level: float) -> str | None:
    for name, fn in REGIMES:
        if fn(vix_level):
            return name
    return None


def compute_cb_table(df: pd.DataFrame, vrp: pd.Series) -> dict:
    """Compute Table 8 cells per regime.

    For each VIX regime:
        - shock_days = trading days where |dVIX| > SHOCK_THRESHOLD
        - avg_shock_loss_pct = mean(|SPY_ret|) on shock days in regime
        - daily_hedge_cost_pct = mean(VRP) on all days in regime
                                 (using raw VRP; we also report the "positive"
                                  variant clipping at 0 for robustness)
        - cb_ratio = avg_shock_loss_pct / daily_hedge_cost_pct
    """
    work = df.copy()
    work["VRP"] = vrp
    work = work.dropna(subset=["VRP"])
    work["regime"] = work["VIX"].apply(assign_regime)
    work["shock"] = work["dVIX"].abs() > SHOCK_THRESHOLD

    results: dict = {}
    for regime, _ in REGIMES:
        sub = work[work["regime"] == regime]
        shock_sub = sub[sub["shock"]]
        total_days = int(len(sub))
        shock_days = int(len(shock_sub))

        avg_shock_loss = float(shock_sub["SPY_ret"].abs().mean()) if shock_days > 0 else float("nan")

        # Primary hedge cost: mean raw daily VRP in regime
        raw_hedge_cost = float(sub["VRP"].mean()) if total_days > 0 else float("nan")
        # Robustness hedge cost: clip VRP at 0 (hedges do not yield negative cost)
        pos_hedge_cost = float(sub["VRP"].clip(lower=0).mean()) if total_days > 0 else float("nan")

        cb_raw = avg_shock_loss / raw_hedge_cost if raw_hedge_cost and raw_hedge_cost > 0 else float("nan")
        cb_pos = avg_shock_loss / pos_hedge_cost if pos_hedge_cost and pos_hedge_cost > 0 else float("nan")

        results[regime] = {
            "total_days": total_days,
            "shock_days": shock_days,
            "avg_shock_loss_pct": avg_shock_loss,
            "daily_hedge_cost_pct_raw": raw_hedge_cost,
            "daily_hedge_cost_pct_clipped": pos_hedge_cost,
            "cb_ratio_raw": cb_raw,
            "cb_ratio_clipped": cb_pos,
        }
    return results


def allclose_verdict(reconstructed: float, paper: float, rtol: float = 0.05) -> dict:
    """Per-cell allclose verdict with relative tolerance."""
    if not (math.isfinite(reconstructed) and math.isfinite(paper)):
        return {"reconstructed": reconstructed, "paper": paper, "abs_diff": None,
                "rel_diff_pct": None, "within_5pct": False, "verdict": "NO_DATA"}
    abs_diff = reconstructed - paper
    rel = abs(abs_diff) / abs(paper) if paper != 0 else float("nan")
    return {
        "reconstructed": round(reconstructed, 4),
        "paper": paper,
        "abs_diff": round(abs_diff, 4),
        "rel_diff_pct": round(rel * 100.0, 2) if math.isfinite(rel) else None,
        "within_5pct": bool(math.isfinite(rel) and rel <= rtol),
        "verdict": "YES" if math.isfinite(rel) and rel <= rtol else "NO",
    }


def run_rv_window(df: pd.DataFrame, rv_window: int) -> dict:
    vrp = compute_daily_vrp(df, rv_window)
    table = compute_cb_table(df, vrp)

    # Pick primary (raw) CB ratio for paper comparison, but also report clipped.
    compare_primary = {}
    compare_clipped = {}
    for regime in ("Calm", "Elevated", "High"):
        paper_row = PAPER_TABLE8[regime]
        rec = table[regime]
        compare_primary[regime] = {
            "shock_loss": allclose_verdict(rec["avg_shock_loss_pct"], paper_row["shock_loss_pct"]),
            "hedge_cost": allclose_verdict(rec["daily_hedge_cost_pct_raw"], paper_row["hedge_cost_pct"]),
            "cb_ratio": allclose_verdict(rec["cb_ratio_raw"], paper_row["cb_ratio"]),
        }
        compare_clipped[regime] = {
            "shock_loss": allclose_verdict(rec["avg_shock_loss_pct"], paper_row["shock_loss_pct"]),
            "hedge_cost": allclose_verdict(rec["daily_hedge_cost_pct_clipped"], paper_row["hedge_cost_pct"]),
            "cb_ratio": allclose_verdict(rec["cb_ratio_clipped"], paper_row["cb_ratio"]),
        }

    return {
        "rv_window": rv_window,
        "regime_table": table,
        "comparison_raw_vrp": compare_primary,
        "comparison_clipped_vrp": compare_clipped,
    }


def tally_pass(compare: dict) -> tuple[int, int]:
    passed = 0
    total = 0
    for regime in compare:
        for cell in compare[regime]:
            total += 1
            if compare[regime][cell]["verdict"] == "YES":
                passed += 1
    return passed, total


def main() -> dict:
    print(f"K1251: Table 8 CB reconstruction (K719 option-a per K1231) — seed={SEED}")

    try:
        df = download_data()
    except Exception as exc:
        blocked = {
            "status": "BLOCKED",
            "reason": f"data download failed: {exc!r}",
            "seed": SEED,
            "paper_reference": PAPER_TABLE8,
        }
        out_path = OUT_DIR / "k1251_results.json"
        with open(out_path, "w") as fh:
            json.dump(blocked, fh, indent=2, default=str)
        print(f"[BLOCKED] {exc!r}; wrote {out_path}")
        return blocked

    print(f"Downloaded {len(df)} rows: {df.index.min().date()} -> {df.index.max().date()}")

    # Run both RV window candidates.
    run_22 = run_rv_window(df, rv_window=22)
    run_20 = run_rv_window(df, rv_window=20)

    # Primary = 22-day (matches K720 / paper Section 3.7).
    pass_22, total_22 = tally_pass(run_22["comparison_raw_vrp"])
    pass_20, total_20 = tally_pass(run_20["comparison_raw_vrp"])
    pass_22_clipped, _ = tally_pass(run_22["comparison_clipped_vrp"])

    results = {
        "experiment_id": "K1251",
        "decision_source": "K1231 option (a) for K719",
        "paper": "volatility-absorption",
        "table": "Table 8 — Hedging Cost-Benefit Ratio by VIX Regime",
        "canonical_paper_values": PAPER_TABLE8,
        "formula": {
            "shock": "|Delta VIX| > 2",
            "regimes": {"Calm": "V<15", "Elevated": "15<=V<25", "High": "V>=25"},
            "shock_loss": "mean(|SPY log return * 100|) on shock days in regime",
            "hedge_cost": "mean(VRP) in regime, where VRP_t = VIX_t^2/252 - RV_t/252",
            "cb_ratio": "shock_loss / hedge_cost",
        },
        "seed": SEED,
        "sample": {
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "n_days": int(len(df)),
        },
        "rv_22": run_22,
        "rv_20": run_20,
        "summary": {
            "rv_22_raw_pass": f"{pass_22}/{total_22}",
            "rv_20_raw_pass": f"{pass_20}/{total_20}",
            "rv_22_clipped_pass": f"{pass_22_clipped}/{total_22}",
            "primary_rv_window": 22,
            "primary_cb_pass_rate_pct": round(100.0 * pass_22 / total_22, 2),
        },
    }

    out_path = OUT_DIR / "k1251_results.json"
    with open(out_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"Saved: {out_path}")

    write_comparison_md(results)
    return results


def write_comparison_md(results: dict) -> None:
    """Human-readable per-cell allclose report (k1251_vs_paper_table8.md)."""
    out_path = OUT_DIR / "k1251_vs_paper_table8.md"
    pt = PAPER_TABLE8
    rv22 = results["rv_22"]
    comp = rv22["comparison_raw_vrp"]
    table = rv22["regime_table"]
    n_days = results["sample"]["n_days"]
    primary = results["summary"]

    def fmt_cell(verdict_entry):
        v = verdict_entry
        if v["verdict"] == "NO_DATA":
            return "n/a"
        mark = "YES" if v["within_5pct"] else "NO"
        return f"{v['reconstructed']} vs {v['paper']} ({v['rel_diff_pct']}%) {mark}"

    lines = [
        "# K1251 vs Paper 8 Table 8 — allclose per cell",
        "",
        f"- Sample: {results['sample']['start']} -> {results['sample']['end']} ({n_days} days)",
        f"- Seed: {results['seed']}",
        "- Formula verbatim from `paper/volatility-absorption/main_v2.tex` lines 472-497.",
        "- Primary RV window: 22-day (matches K720 / Section 3.7).",
        "",
        "## Paper Table 8 (canonical)",
        "",
        "| Regime | Avg Shock Loss (%) | Daily Hedge Cost (%) | CB Ratio |",
        "|--------|-------------------|---------------------|----------|",
    ]
    for r in ("Calm", "Elevated", "High"):
        row = pt[r]
        lines.append(f"| {r} | {row['shock_loss_pct']} | {row['hedge_cost_pct']} | {row['cb_ratio']} |")

    lines += [
        "",
        "## K1251 reconstruction (RV=22, raw VRP as hedge cost)",
        "",
        "| Regime | Days | Shock Days | Avg Shock Loss (%) | Daily Hedge Cost raw (%) | Daily Hedge Cost clipped (%) | CB Ratio raw | CB Ratio clipped |",
        "|--------|------|-----------|-------------------|-------------------------|------------------------------|--------------|------------------|",
    ]
    for r in ("Calm", "Elevated", "High"):
        t = table[r]
        lines.append(
            f"| {r} | {t['total_days']} | {t['shock_days']} | "
            f"{round(t['avg_shock_loss_pct'], 4)} | "
            f"{round(t['daily_hedge_cost_pct_raw'], 4)} | "
            f"{round(t['daily_hedge_cost_pct_clipped'], 4)} | "
            f"{round(t['cb_ratio_raw'], 4) if t['cb_ratio_raw'] == t['cb_ratio_raw'] else 'nan'} | "
            f"{round(t['cb_ratio_clipped'], 4) if t['cb_ratio_clipped'] == t['cb_ratio_clipped'] else 'nan'} |"
        )

    lines += [
        "",
        "## Allclose verdict per cell (rtol=0.05 vs paper, RV=22 raw VRP)",
        "",
        "| Regime | Shock Loss | Hedge Cost | CB Ratio |",
        "|--------|-----------|-----------|----------|",
    ]
    for r in ("Calm", "Elevated", "High"):
        lines.append(
            f"| {r} | {fmt_cell(comp[r]['shock_loss'])} | "
            f"{fmt_cell(comp[r]['hedge_cost'])} | {fmt_cell(comp[r]['cb_ratio'])} |"
        )

    lines += [
        "",
        "## Summary",
        "",
        f"- RV=22 raw VRP   : {primary['rv_22_raw_pass']} cells within 5% of paper",
        f"- RV=22 clipped VRP: {primary['rv_22_clipped_pass']} cells within 5% of paper",
        f"- RV=20 raw VRP   : {primary['rv_20_raw_pass']} cells within 5% of paper",
        "",
        "## Interpretation",
        "",
        "- A YES verdict in the CB Ratio column is what ultimately drives paper Table 8 reproduce_report.",
        "- If hedge-cost cells diverge but CB ratios match, the divergence is likely a formula variant",
        "  (raw vs clipped VRP, or a different RV window). 三方一致 rule requires explicit disclosure.",
        "- If CB ratios diverge substantially, the paper owner should consider K1231 option (a) data-",
        "  vintage alignment for SPY/VIX (same fix that helps K716/K718), or option (c) errata.",
    ]

    with open(out_path, "w") as fh:
        fh.write("\n".join(lines))
    print(f"Comparison: {out_path}")


if __name__ == "__main__":
    main()
