#!/usr/bin/env python3
"""PRG v7 reproduce gate: bind every printed number in main.tex to canonical JSONs.

v7 architecture (2026-07-14 rewrite): the paper's entire quantitative surface is
the flip table (Table 2) + data table + a handful of prose numbers, all sourced
from exactly TWO pinned-vintage experiment JSONs:

  - experiments/k1699/k1699_results.json   (close panel; pinned 2026-07-12)
  - experiments/K1710/K1710_results.json   (mixed anchor + open panel + ON shares;
                                            same pinned snapshots, SHA-verified)

This script derives every expected string FROM the JSONs (no hardcoded expected
values) and asserts it appears in main.tex. It never fetches live data.
Sign convention: JSONs store t as negative-favors-PRG; the paper prints
positive-favors-PRG, so all t are flipped here (same logic as
scripts/gen_flip_table.py, which generated the table).

Usage:  uv run python paper/prg-periodic-garch/reproduce.py [--tex <path>]
Output: paper/prg-periodic-garch/reproduce_report.json
Gate:   match_rate >= 95% and alert_level == green required before
        review / ready / submit (paper-workflow hard rule 2).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PAPER_DIR = Path(__file__).resolve().parent
PROJECT = PAPER_DIR.parents[1]

tex_path = PAPER_DIR / "main.tex"
if "--tex" in sys.argv:
    tex_path = Path(sys.argv[sys.argv.index("--tex") + 1])

K1699 = json.loads((PROJECT / "experiments/k1699/k1699_results.json").read_text())
K1710 = json.loads((PROJECT / "experiments/K1710/K1710_results.json").read_text())
TEX_RAW = tex_path.read_text(encoding="utf-8")
# Strip LaTeX comments (% source bindings etc.) so checks hit printed text only,
# then collapse whitespace for layout-insensitive matching.
TEX_NO_COMMENT = re.sub(r"(?<!\\)%.*", "", TEX_RAW)
TEX = re.sub(r"\s+", " ", TEX_NO_COMMENT)

MARKETS = ["SPY", "QQQ", "GLD", "EEM", "0050.TW", "TAIFEX"]
HARVEY = 3.0

checks: list[dict] = []


def check(name: str, needle: str) -> None:
    ok = re.sub(r"\s+", " ", needle) in TEX
    checks.append({"check": name, "expected": needle, "match": ok})
    print(("  OK  " if ok else "  FAIL") + f" {name}: {needle[:90]}")


def invariant(name: str, ok: bool, detail: str) -> None:
    checks.append({"check": name, "expected": detail, "match": bool(ok)})
    print(("  OK  " if ok else "  FAIL") + f" {name}: {detail}")


def cell(t_json: float, p: float) -> tuple[str, bool]:
    t = -t_json
    stars = "^{***}" if abs(t) > HARVEY else ""
    p_str = "$<$0.001" if p < 0.001 else f"{p:.2f}"
    sign = "+" if t >= 0 else "-"
    return f"${sign}{abs(t):.2f}{stars}$ ({p_str})", abs(t) > HARVEY


# ---- Table 2: full row binding per market -----------------------------------
counts = {"mixed": 0, "close": 0, "open": 0}
open_t: dict[str, float] = {}
mixed_t: dict[str, float] = {}
close_t: dict[str, float] = {}
for m in MARKETS:
    close = K1699["markets"][m]["dm_tests"]["PRG_tminus1_exp_vs_GJR"]
    mixed = K1710["markets"][m]["dm_tests"]["mixed_anchor_main"]
    open_ = K1710["markets"][m]["dm_tests"]["open_panel_main"]
    close_t[m], mixed_t[m], open_t[m] = -close["t_stat"], -mixed["t_stat"], -open_["t_stat"]
    c_mixed, h1 = cell(mixed["t_stat"], mixed["p_value"])
    c_close, h2 = cell(close["t_stat"], close["p_value"])
    c_open, h3 = cell(open_["t_stat"], open_["p_value"])
    counts["mixed"] += h1
    counts["close"] += h2
    counts["open"] += h3
    row = f"{m} & {close['n']:,} & {c_mixed} & {c_close} & {c_open} \\\\"
    check(f"table2_row_{m}", row)

check(
    "table2_summary_counts",
    f"Harvey-significant ($|t|>3$) & & {counts['mixed']}/6 & {counts['close']}/6 & {counts['open']}/6",
)

# ---- Data table: N + OOS overnight variance share ---------------------------
for m in MARKETS:
    share = K1710["markets"][m]["oos_overnight_variance_share"] * 100
    n = K1699["markets"][m]["dm_tests"]["PRG_tminus1_exp_vs_GJR"]["n"]
    n_tex = f"{n:,}".replace(",", "{,}")
    check(f"datatable_{m}_N_and_share", f"{n_tex} & 20") if False else None
    # Bind N and ON share on the same data-table row (source/period text between them).
    label = "TAIFEX TX" if m == "TAIFEX" else m
    pattern = re.compile(
        re.escape(label) + r"\s*&[^&]*&\s*" + re.escape(n_tex) + r"\s*&[^&]*&\s*"
        + re.escape(f"{share:.1f}") + r"\s*\\\\"
    )
    ok = bool(pattern.search(TEX_NO_COMMENT))
    checks.append(
        {"check": f"datatable_{m}", "expected": f"{label} .. {n_tex} .. {share:.1f}", "match": ok}
    )
    print(("  OK  " if ok else "  FAIL") + f" datatable_{m}: N={n_tex} share={share:.1f}")

# ---- Prose numbers (derived, not hardcoded) ----------------------------------
shares_pct = {
    m: K1710["markets"][m]["oos_overnight_variance_share"] * 100 for m in MARKETS
}
mixed_vals = [mixed_t[m] for m in MARKETS]
open_vals = [open_t[m] for m in MARKETS]
close_vals = [close_t[m] for m in MARKETS]
all_vals = mixed_vals + open_vals + close_vals
check("prose_mixed_range", f"$+{min(mixed_vals):.1f}$ to $+{max(mixed_vals):.1f}$")
check("prose_span", f"$-{abs(min(all_vals)):.1f}$ to $+{max(all_vals):.1f}$")
inflation = [mixed_t[m] - close_t[m] for m in MARKETS]
check("prose_inflation", f"${min(inflation):.1f}$ to ${max(inflation):.1f}$")
spread = max(
    max(mixed_t[m], close_t[m], open_t[m]) - min(mixed_t[m], close_t[m], open_t[m])
    for m in MARKETS
)
check("prose_max_spread", f"${spread:.1f}$ $t$-units")
check("prose_qqq_open", f"QQQ ($t=+{open_t['QQQ']:.2f}$")
check(
    "prose_rank_order_sentence",
    f"EEM ({shares_pct['EEM']:.1f}\\%, $t=+{open_t['EEM']:.2f}$) down to "
    f"QQQ ({shares_pct['QQQ']:.1f}\\%, $t=+{open_t['QQQ']:.2f}$",
)

# ---- Claim-level invariants (JSON-side) ---------------------------------------
invariant(
    "open_positive_all_six",
    all(v > 0 for v in open_vals),
    "open-panel t > 0 in all six markets (paper orientation)",
)
invariant(
    "close_zero_of_six_harvey",
    counts["close"] == 0,
    "close panel 0/6 Harvey",
)
lag_harvey = sum(
    abs(K1699["markets"][m]["dm_tests"]["PRG_tminus1_lag_vs_GJR"]["t_stat"]) > HARVEY
    for m in MARKETS
)
invariant("close_lag_variant_zero_harvey", lag_harvey == 0, "lag variant 0/6 Harvey")
shares = {m: K1710["markets"][m]["oos_overnight_variance_share"] for m in MARKETS}
invariant(
    "open_t_rank_ordered_in_on_share",
    sorted(MARKETS, key=lambda m: shares[m]) == sorted(MARKETS, key=lambda m: open_t[m]),
    "open-panel t perfectly rank-ordered in OOS overnight variance share",
)
invariant(
    "k1710_bit_identical_recorded",
    "two_pass_bit_identical" in json.dumps(K1710),
    "K1710 two-pass bit-identical determinism recorded",
)
invariant(
    "snapshot_metadata_present",
    bool(K1699.get("data_snapshots")),
    "K1699 pinned snapshot metadata present (K1710 asserts SHA equality at runtime)",
)
invariant(
    "no_leftover_placeholders",
    ("TODO-K1710" not in TEX_RAW) and ("X.XX" not in TEX_RAW),
    "no placeholder tokens left in tex",
)

# ---- Report -------------------------------------------------------------------
total = len(checks)
matched = sum(1 for c in checks if c["match"])
match_rate = matched / total * 100.0 if total else 0.0
alert = "green" if match_rate >= 95.0 else ("yellow" if match_rate >= 80.0 else "red")
report = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "tex": str(tex_path.name),
    "sources": [
        "experiments/k1699/k1699_results.json",
        "experiments/K1710/K1710_results.json",
    ],
    "n_checks": total,
    "n_matched": matched,
    "match_rate": round(match_rate, 2),
    "overall_match_rate_pct": round(match_rate, 2),
    "alert_level": alert,
    "checks": checks,
    "note": (
        "v7 gate: every printed number derived from the two pinned-vintage JSONs "
        "and matched against the manuscript text (sign convention flipped to "
        "positive-favors-PRG). No live data fetch. Pre-v7 gate (live yfinance "
        "reruns vs 6.00-era values) retired with the v7 rewrite; see git history."
    ),
}
(PAPER_DIR / "reproduce_report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(f"\nMatch: {matched}/{total} = {match_rate:.1f}% -> {alert.upper()}")
sys.exit(0 if alert == "green" else 1)
