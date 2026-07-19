"""
K1623 rev3 — full-text consistency self-check over the claim surface
====================================================================

Codex round 2 failed rev2 partly because a retraction was applied in one place
and left standing in another. So rev3 does not get to assert "I fixed it
everywhere"; it has to demonstrate it mechanically, over every claim-surface
file, and publish the hit list.

Each rule below is one of two kinds:

  FORBIDDEN  the pattern must not appear at all (a stale value or a retracted
             claim). Any hit fails the check.
  QUALIFIED  the pattern may appear, but only on a line that also carries one of
             the required qualifiers -- e.g. "same forecasts" is allowed only
             where the same line says it is FALSE for TW0050. This is what
             separates "the claim is gone" from "the claim is discussed as
             something we retracted".

NOTE on tooling: `grep` on this machine resolves to ugrep, whose `-r` plus an
explicit multi-file list silently degrades to "no such file" and then reports
zero hits -- i.e. it manufactures a clean bill of health. That is precisely the
failure mode this experiment exists to punish, so the check is done in Python
against read bytes instead of shelling out.

Run:  uv run python experiments/k1623/k1623_rev3_selfcheck.py
Exit: 0 = all rules pass, 1 = at least one violation
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

CLAIM_SURFACE = [
    "README.md",
    "k1623_rev2.py",
    "k1623_rev2_mc.py",
    "k1623_rev2_results.json",
    "k1623_rev2_mc_results.json",
    "k1623_rev3_patch_mc_artifact.py",
    "k1623_rev3_selfcheck.py",
]

# Qualifiers shared by every "this claim is retracted" rule. A withdrawn claim
# has to stay quotable -- the record of what was wrongly asserted is part of the
# correction -- so the test is not "does the phrase appear" but "does the phrase
# appear WITHOUT the surrounding text that marks it as withdrawn".
# DELIBERATELY NARROW. An earlier draft of this list contained `NOT `, `not an`,
# `cannot` and `不是`. Those made the check worthless: the frozen finding_3 text
# passed purely because it happens to contain "not evidence of additional level
# shifts", a phrase with nothing to do with the attribution being withdrawn. A
# marker must be a word people only write when they are RETRACTING something,
# never a word that shows up in ordinary prose. Anything that survives this
# narrow list and is still legitimate belongs in ALLOWLIST with a written reason.
RETRACTION_MARKERS = (
    r"rev3", r"撤回", r"更正", r"原本寫", r"原文宣稱", r"不再宣稱", r"為假", r"是錯的",
    r"不支撐", r"並不精確", r"高估", r"不適用", r"沒被 assert", r"這句無限定",
    r"RETRACTED", r"SUPERSED", r"superseded", r"was wrong", r"imprecise",
    r"why_it_is_wrong", r"must not be made", r"never stored", r"never stores",
    r"unsupported", r"overstat", r"typo", r"earlier draft", r"flagged",
    r"deliberately", r"IS NOT ELW", r"corrected", r"CORRECTION",
    # Precise negations only -- each quotes the thing being denied, so unlike a
    # bare `not` they cannot be satisfied by incidental prose.
    r"FALSE", r"is not an", r"NOT ['\"]ELW", r"不能說「", r"NOT 「",
)

# Explicit, reasoned exemptions. Each entry says WHY a hit that no qualifier can
# reach is nonetheless correct. Keeping this list short and argued is the point:
# an exemption nobody can justify in one sentence is a defect in disguise.
ALLOWLIST = [
    ("k1623_rev2_mc_results.json", r"finding_3_downward_attenuation",
     "Frozen-by-design. rev3 must not rewrite the original artifact text (that would be "
     "the 'pretend it was always right' failure). It is superseded in-block by "
     "summary.READ_THIS_FIRST_rev3_supersessions and claim_corrections_rev3."),
    ("k1623_rev2_mc_results.json", r"finding_4_break_recovery_is_noisy",
     "Frozen-by-design, same reason; the break-DATE sentence inside it is retracted by "
     "summary.READ_THIS_FIRST_rev3_supersessions and claim_corrections_rev3."),
    ("k1623_rev3_patch_mc_artifact.py", r"superseded_text",
     "This is the patch tool quoting the text it supersedes, which is its job."),
]

# (rule_id, blocker, kind, pattern, extra_qualifiers, note)
#   forbidden: zero hits allowed, no qualifier can rescue it
#   qualified: hits allowed only where a retraction marker appears within +/-1 line
#              (the window is needed because Python source wraps these strings)
#   required : the corrected value must actually be present somewhere
RULES = [
    ("B1-stale-deviation", "B1", "qualified",
     r"2\.51e-3|0\.00251|2\.5e-3", (r"權威值", r"一半", r"about half", r"roughly half"),
     "TW0050 max relative deviation was written as 2.51e-3 / 2.5e-3; authoritative is 5.26e-3."),
    ("B1-authoritative-present", "B1", "required",
     r"5\.26e-3", (),
     "The corrected value must actually appear."),
    ("B2-har-champion", "B2", "qualified",
     r"冠軍|並列最佳|tied-best|champion in all", (r"兩兩比較", r"只有", r"全模型"),
     "HAR was claimed the 5-asset QLIKE winner; all-model winners include AR1 and ARFIMA."),
    ("B3-unchanged-numbers", "B3", "qualified",
     r"所有數字不變|所有預測值不變|forecasts unchanged", (r"宣稱", r"guard"),
     "Unqualified 'nothing changed' is FALSE for TW0050 (n 4263 -> 4264)."),
    ("B3-same-forecasts", "B3", "qualified",
     r"same forecasts|同一個樣本", (),
     "'same forecasts / same sample' may appear only where marked false for TW0050."),
    ("B4-total-as-break-effect", "B4", "qualified",
     r"-0\.085 to -0\.027|−0\.085 到 −0\.027|0\.085 至 .?0\.027",
     (r"TOTAL", r"總偏誤", r"arm-A", r"arm A"),
     "The arm-A total may be quoted only when labelled the total, never as the break effect."),
    ("B4-break-dates-claim", "B4", "qualified",
     r"break DATES|斷點.{0,4}日期",
     # Legitimate mentions describe WHERE breaks sit or note that they were
     # estimated at all. Note "were estimated" (past) deliberately does not
     # rescue finding_4's "ARE estimated with substantial uncertainty", which is
     # the quantified claim being retracted.
     (r"植入", r"knows the break", r"估計出的斷點日期", r"數量", r"COUNT",
      r"implanted", r"true simulated", r"were estimated", r"LOCATION-oracle"),
     "Break-date UNCERTAINTY claims are retracted; describing where breaks were implanted, "
     "or stating that only counts are stored, is legitimate."),
    ("B4-arm-b-elw-only", "B4", "qualified",
     r"ELW alone|elw_own|ELW-only|ELW 而已", (),
     "Arm B must never be described as an ELW-only baseline except to deny it."),
    ("B5-uniqueness", "B5", "qualified",
     r"獨有的貢獻|unique contribution|仍然獨有", (r"否定",),
     "General academic uniqueness is unsupported; only the retraction may use the phrase."),
    ("MINOR-nested-sets", "MINOR", "qualified",
     r"五個巢狀集合|FIVE nested", (r"DISJOINT", r"互斥"),
     "QLIKE-20 and MSE-20 are disjoint, so 'five nested sets' is imprecise."),
    ("B1-every-number-in-json", "B1", "qualified",
     r"每一個 README 數字都可在 JSON 逐項對上|每一個 README 數字都可在 rev2 JSON",
     (r"為假", r"三份"),
     "README numbers live across three artifacts, not one."),
]


def main() -> int:
    docs = {}
    for name in CLAIM_SURFACE:
        path = HERE / name
        if not path.exists():
            print(f"MISSING claim-surface file: {name}")
            return 1
        docs[name] = path.read_text(encoding="utf-8").splitlines()

    # Prove the scanner can actually see the files -- the ugrep failure mode was a
    # silent zero-hit, so a positive control runs first.
    control = sum(len(re.findall(r"k1623", "\n".join(v), re.I)) for v in docs.values())
    if control == 0:
        print("POSITIVE CONTROL FAILED: scanner sees no content")
        return 1
    print(f"positive control OK: {control} 'k1623' hits across {len(docs)} files\n")

    report, violations = [], 0
    for rule_id, blocker, kind, pattern, extra_quals, note in RULES:
        # re.I is load-bearing, not cosmetic. Without it the pattern
        # "break DATES" missed the frozen finding_4 sentence "Break DATES are
        # estimated with substantial uncertainty" -- the exact claim B4(c)
        # retracts -- and the rule reported PASS while never having looked at it.
        rx = re.compile(pattern, re.I)
        qrx = [re.compile(q, re.I) for q in RETRACTION_MARKERS + extra_quals]
        hits, bad, exempt = [], [], []
        for name, lines in docs.items():
            # the self-check file itself defines the patterns; skip its own table
            if name == "k1623_rev3_selfcheck.py":
                continue
            for i, line in enumerate(lines, 1):
                if not rx.search(line):
                    continue
                hits.append(f"{name}:{i}")
                if kind == "required":
                    continue
                # Python and Markdown wrap a single statement across lines, so a
                # marker may legitimately sit on a neighbour. JSON does not: one
                # key per line, and the next key is a different claim entirely.
                # Letting JSON borrow a neighbour's marker is how the frozen
                # finding_3 first passed -- it was rescued by an unrelated "IS
                # NOT much inflated" on the following line.
                scope = (line if name.endswith(".json")
                         else "\n".join(lines[max(0, i - 2): i + 1]))
                if any(q.search(scope) for q in qrx):
                    continue
                allow = next((r for f, p, r in ALLOWLIST
                              if f == name and re.search(p, line)), None)
                if allow:
                    exempt.append({"site": f"{name}:{i}", "reason": allow})
                    continue
                bad.append(f"{name}:{i}: {line.strip()[:160]}")

        if kind == "required":
            ok = len(hits) > 0
            bad = [] if ok else ["pattern never appears"]
        else:
            ok = not bad

        violations += 0 if ok else 1
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {rule_id:26s} ({blocker:5s}) hits={len(hits):2d} "
              f"unqualified={len(bad)} exempt={len(exempt)}")
        for b in bad:
            print(f"         !! {b}")
        for e in exempt:
            print(f"         ~~ EXEMPT {e['site']}")
        report.append({
            "rule_id": rule_id, "blocker": blocker, "kind": kind, "pattern": pattern,
            "hits": hits, "unqualified_hits": bad, "allowlisted": exempt,
            "status": status, "note": note,
        })

    print(f"\n{'ALL RULES PASS' if not violations else str(violations) + ' RULE(S) FAILED'}")
    out = HERE / "k1623_rev3_selfcheck_report.json"
    out.write_text(json.dumps({
        "claim_surface_files": CLAIM_SURFACE,
        "positive_control_hits": control,
        "rules_total": len(RULES),
        "rules_failed": violations,
        "all_pass": violations == 0,
        "rules": report,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.name}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
