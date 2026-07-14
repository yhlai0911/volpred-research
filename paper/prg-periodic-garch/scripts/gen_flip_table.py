#!/usr/bin/env python3
"""Generate the v7 flip-table (Table 2) and data-table LaTeX rows from canonical JSONs.

Sources (single pinned vintage, 2026-07-12):
  - Close panel : experiments/k1699/k1699_results.json  .markets.<M>.dm_tests.PRG_tminus1_exp_vs_GJR
  - Mixed panel : experiments/K1710/K1710_results.json  .markets.<M>.dm_tests.mixed_anchor_main
  - Open panel  : experiments/K1710/K1710_results.json  .markets.<M>.dm_tests.open_panel_main
  - ON share    : experiments/K1710/K1710_results.json  .markets.<M>.oos_overnight_variance_share

Sign convention: both experiment JSONs store t with "negative = PRG better".
The paper reports "positive = PRG better", so every t is sign-flipped here.
reproduce.py asserts that the printed main.tex values equal this script's output.
"""
from __future__ import annotations

import json
from pathlib import Path

PAPER_DIR = Path(__file__).resolve().parents[1]
PROJECT = PAPER_DIR.parents[1]

K1699 = json.loads((PROJECT / "experiments/k1699/k1699_results.json").read_text())
K1710 = json.loads((PROJECT / "experiments/K1710/K1710_results.json").read_text())

MARKETS = ["SPY", "QQQ", "GLD", "EEM", "0050.TW", "TAIFEX"]
LABEL = {"0050.TW": "0050.TW", "TAIFEX": "TAIFEX"}
HARVEY = 3.0


def cell(t_json: float, p: float) -> tuple[str, bool]:
    """Paper-orientation cell 't (p)' with Harvey stars; returns (latex, harvey_pass)."""
    t = -t_json  # flip: JSON negative-favors-PRG -> paper positive-favors-PRG
    stars = "^{***}" if abs(t) > HARVEY else ""
    p_str = "$<$0.001" if p < 0.001 else f"{p:.2f}"
    sign = "+" if t >= 0 else "-"
    return f"${sign}{abs(t):.2f}{stars}$ ({p_str})", abs(t) > HARVEY


def main() -> None:
    counts = {"mixed": 0, "close": 0, "open": 0}
    print("% ---- Table 2 (flip table) rows: paste between \\midrule and summary row ----")
    for m in MARKETS:
        close = K1699["markets"][m]["dm_tests"]["PRG_tminus1_exp_vs_GJR"]
        mixed = K1710["markets"][m]["dm_tests"]["mixed_anchor_main"]
        open_ = K1710["markets"][m]["dm_tests"]["open_panel_main"]
        n = close["n"]
        c_mixed, h1 = cell(mixed["t_stat"], mixed["p_value"])
        c_close, h2 = cell(close["t_stat"], close["p_value"])
        c_open, h3 = cell(open_["t_stat"], open_["p_value"])
        counts["mixed"] += h1
        counts["close"] += h2
        counts["open"] += h3
        name = LABEL.get(m, m)
        print(f"{name:8s}& {n:,} & {c_mixed} & {c_close} & {c_open} \\\\")
    print(
        f"Harvey-significant ($|t|>3$) & & {counts['mixed']}/6 & "
        f"{counts['close']}/6 & {counts['open']}/6 \\\\"
    )
    print()
    print("% ---- Data table ON-share column (OOS overnight variance share, %) ----")
    for m in MARKETS:
        share = K1710["markets"][m]["oos_overnight_variance_share"]
        print(f"{LABEL.get(m, m):8s}: {share * 100:.1f}")
    print()
    print("% ---- Abstract / prose numbers ----")
    mixed_t = [-K1710["markets"][m]["dm_tests"]["mixed_anchor_main"]["t_stat"] for m in MARKETS]
    open_t = [-K1710["markets"][m]["dm_tests"]["open_panel_main"]["t_stat"] for m in MARKETS]
    close_t = [-K1699["markets"][m]["dm_tests"]["PRG_tminus1_exp_vs_GJR"]["t_stat"] for m in MARKETS]
    all_t = mixed_t + open_t + close_t
    print(f"mixed range: +{min(mixed_t):.1f} to +{max(mixed_t):.1f}")
    print(f"all-conventions span: {min(all_t):+.1f} to {max(all_t):+.1f}")
    inflation = [m - c for m, c in zip(mixed_t, close_t)]
    print(f"mixed-minus-close inflation per market: {min(inflation):.1f} to {max(inflation):.1f}")
    spread = [max(a, b, c) - min(a, b, c) for a, b, c in zip(mixed_t, close_t, open_t)]
    print(f"max within-row spread: {max(spread):.1f} t-units")
    print(f"open SPY {open_t[0]:+.2f}  QQQ {open_t[1]:+.2f}")
    print(f"close high-ON: TAIFEX {close_t[5]:+.2f} GLD {close_t[2]:+.2f} EEM {close_t[3]:+.2f}")


if __name__ == "__main__":
    main()
