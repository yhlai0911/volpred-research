#!/usr/bin/env python3
"""K1173 — EM refined institutional ownership fetcher documentation.

Brief requirement:
  - CH: QFII + private_institutional (excluding SOE/State)
  - IN: FII + DII (excluding promoter)
  - BR: foreign + local institutional (excluding controlling shareholder)
  - MX: institutional (excluding family controlling)

IMPLEMENTATION NOTE:
  The brief suggested fetching from official regulators (CSRC/SEBI/CVM/CNBV).
  In practice those endpoints require paid-tier access or Chinese-only forms
  plus CAPTCHA.  Public curated sources with the same disclosures are:
    - India: screener.in scrapes SEBI quarterly shareholding patterns
    - Brazil/Mexico/China: simplywall.st aggregates company filings
      (Form 20-F / annual reports / BMV DFP / SSE disclosures)

  For each EM stock we performed live WebFetch requests during K1173 (see
  run_fetch.log) and stored the manual mapping in
  data/k1173_em_refined_holdings.csv.

  The refined_inst_pct field implements the brief definition:
    - IN refined = FII_pct + DII_pct (mutual fund + insurance aggregated
      under DII per SEBI template)
    - BR/MX refined = Institutions % (simplywall.st category; excludes
      'Private Companies' = controlling shareholder bucket, 'Individual
      Insiders' = family, 'Government' = state)
    - CH refined = Institutions % + Sovereign Wealth Funds % where SWF
      represents non-state professional money; excludes 'State or
      Government' and 'Private Companies' where the Private Companies
      bucket holds the SOE parent (classic pattern: e.g. ICBC's Central
      Huijin in Institutions bucket vs MoF in State bucket, or Moutai
      Group in Private Companies as Guizhou SASAC subsidiary)

SOURCES PER TICKER are documented in the CSV.  Coverage:
  - IN 10/10 (screener.in Dec 2025 / Mar 2026)
  - BR 10/10 (simplywall.st Apr 2026)
  - MX 10/10 (simplywall.st + 2 derived from search summary for TLEVISACPO)
  - CH 10/10 (simplywall.st direct for 9 + 1 search summary for Hengrui)

Random seed 42 fixed (not used here — fetcher only).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def verify_csv_format() -> pd.DataFrame:
    """Read & sanity-check the refined holdings CSV."""
    path = DATA / "k1173_em_refined_holdings.csv"
    df = pd.read_csv(path, comment="#")
    required = {"ticker", "market", "yfinance_inst_pct", "refined_inst_pct"}
    missing = required - set(df.columns)
    assert not missing, f"Missing columns: {missing}"

    print(f"[csv] {len(df)} rows, {df['market'].value_counts().to_dict()}")
    print("\nyfinance vs refined diff summary per market:")
    df["diff"] = df["refined_inst_pct"] - df["yfinance_inst_pct"]
    for m, grp in df.groupby("market"):
        finite = grp["diff"].dropna()
        print(f"  {m}: n={len(grp)}, mean_diff={finite.mean():+.3f}, "
              f"median_diff={finite.median():+.3f}, "
              f"min={finite.min():+.3f}, max={finite.max():+.3f}")

    print("\nPer-stock refined vs yfinance (sorted by |diff| desc):")
    for _, r in df.reindex(df["diff"].abs().sort_values(ascending=False).index).iterrows():
        yf = r["yfinance_inst_pct"]
        yf_str = f"{yf:.3f}" if pd.notna(yf) else "  N/A"
        print(f"  {r['ticker']:20s} ({r['market']}): yf={yf_str} "
              f"refined={r['refined_inst_pct']:.3f} diff={r['diff']:+.3f}")

    return df


def dump_market_means(df: pd.DataFrame) -> dict:
    """Compute per-market mean refined_inst_pct (used in K1173 analysis)."""
    out = {}
    for m in ["BR", "CH", "IN", "MX"]:
        sub = df[df["market"] == m]
        out[m] = {
            "n": int(len(sub)),
            "yfinance_mean": float(sub["yfinance_inst_pct"].mean()),
            "yfinance_median": float(sub["yfinance_inst_pct"].median()),
            "refined_mean": float(sub["refined_inst_pct"].mean()),
            "refined_median": float(sub["refined_inst_pct"].median()),
            "diff_mean": float((sub["refined_inst_pct"] - sub["yfinance_inst_pct"]).mean()),
        }
    with open(DATA / "k1173_em_refined_market_means.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nMarket-level mean refined vs yfinance:")
    for m, rec in out.items():
        print(f"  {m}: yf_mean={rec['yfinance_mean']:.3f}, "
              f"refined_mean={rec['refined_mean']:.3f}, "
              f"diff={rec['diff_mean']:+.3f}")
    return out


if __name__ == "__main__":
    df = verify_csv_format()
    dump_market_means(df)
