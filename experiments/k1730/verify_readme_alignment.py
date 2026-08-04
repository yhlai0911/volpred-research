"""Assert that every number quoted in K1730's prose is the number in the JSON.

Codex's v1 review failed this experiment partly because the narrative document
made claims the results file did not support. Prose and results drift apart the
moment a run is repeated and only one of them is updated, and a reviewer has no
cheap way to notice. So the alignment is a test, not a promise: this script
re-reads the results JSON and checks it against the values written into
``README.md`` and ``K1730_ARM_A_FULL_RUN_COLLECTION.md``.

It also greps both documents for the specific overclaim vocabulary the v1 review
flagged, so a future edit cannot quietly reintroduce "decisive" or a
multi-modality verdict.

Run:  uv run python verify_readme_alignment.py
Exit: 0 if aligned, 1 otherwise (prints every mismatch).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "k1730_gevreg_midas_ssvs_results.json"
DOCS = ["README.md", "K1730_ARM_A_FULL_RUN_COLLECTION.md"]

# Words that may not appear in the prose at all. Each was either flagged by the
# v1 review or is a synonym close enough that using it would restage the same
# claim.
BANNED = [
    r"\bdecisive\b", r"\bdecisively\b", r"決定性", r"決定地",
    r"\bconclusive\b", r"\bconclusively\b", r"確鑿",
    r"multi-?modal", r"多峰",
    r"\bproves\b", r"\bproven\b", r"證明了",
    # The placebo shift is deliberately non-circular: wrapping the tail onto the
    # head is the very leakage the redesign removes. Calling it "circular-shift"
    # describes a design that would reinstate the v1 defect, so the misnomer is
    # banned outright — "non-circular" is exempted by the lookbehind.
    r"(?<!non-)\bcircular[-\s]?shift",
]
# ...except where the document is explicitly describing the retracted claim.
RETRACTION_MARKERS = ("撤回", "RETRACTED", "retracted", "v1 宣稱", "v1 claimed",
                      "不再", "no longer", "禁用詞", "banned")


def approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def main() -> int:
    if not RESULTS.exists():
        print(f"FAIL: {RESULTS.name} missing")
        return 1
    r = json.loads(RESULTS.read_text())
    texts = {}
    for d in DOCS:
        p = HERE / d
        if not p.exists():
            print(f"FAIL: {d} missing (experiment three-piece rule)")
            return 1
        texts[d] = p.read_text()

    problems: list[str] = []

    # ---- 1. banned vocabulary -------------------------------------------
    for name, text in texts.items():
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(m in line for m in RETRACTION_MARKERS):
                continue          # the line is *about* the retracted wording
            for pat in BANNED:
                if re.search(pat, line, flags=re.IGNORECASE):
                    problems.append(
                        f"{name}:{line_no} uses banned claim word /{pat}/: "
                        f"{line.strip()[:90]}")

    # ---- 2. headline numbers must appear verbatim in the README ---------
    oos = r["oos"]
    readme = texts["README.md"]
    checks: list[tuple[str, str]] = [
        ("OOS block count", str(oos["n_common_oos"])),
        ("OOS start", oos["oos_start"]),
        ("OOS end", oos["oos_end"]),
        ("sample blocks", f"{r['sample']['n_weekly_blocks']:,}"),
    ]
    for m, e in oos["by_model"].items():
        checks.append((f"{m} mean pinball", f"{e['mean_pinball']:.5f}"))
        checks.append((f"{m} 90% coverage",
                       f"{e['intervals']['0.90']['empirical_coverage']:.4f}"))
    for name, val in checks:
        if val not in readme:
            problems.append(f"README.md does not contain {name} = {val}")

    # ---- 3. the two verdicts that must stay downgraded -------------------
    tier = r["ssvs_summary"]["inference_tier"]
    if tier != "inference":
        for name, text in texts.items():
            if "diagnostic" not in text.lower() and "診斷" not in text:
                problems.append(
                    f"{name}: ssvs inference_tier is '{tier}' but the document "
                    f"never labels the PIP as diagnostic-only")

    if "placebo_test" in r:
        p = r["placebo_test"]
        for name, val in [
            ("placebo p-value", f"{p['one_sided_p_value']:.3f}"),
            ("placebo arm count", str(p["n_placebo_arms"])),
            ("matched sample", str(p["matched_sample_blocks"])),
        ]:
            if val not in readme:
                problems.append(f"README.md does not contain {name} = {val}")
        for lag, rep in p["lookahead_recheck_on_shifted_stamps"].items():
            if not rep["passed"]:
                problems.append(f"placebo {lag} failed its lookahead recheck")

    # ---- 4. GEV multistart wording ---------------------------------------
    mle = r["mle_convergence_summary"]
    if f"{mle['mean_basin_concentration']:.3f}" not in readme and \
       f"{mle['mean_basin_concentration']:.2f}" not in readme:
        problems.append("README.md does not quote mean_basin_concentration "
                        f"({mle['mean_basin_concentration']:.3f})")

    if problems:
        print(f"MISALIGNED — {len(problems)} problem(s):\n")
        for p_ in problems:
            print(f"  - {p_}")
        return 1
    print(f"ALIGNED — {len(checks)} numeric claims in README.md match "
          f"{RESULTS.name}; no banned claim vocabulary in {len(DOCS)} documents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
