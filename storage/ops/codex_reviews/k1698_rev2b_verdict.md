Round 3 remains **FAIL**. The computational fixes largely landed, but the frozen primary claim surface still contains contradictory pre-remediation claims.

Freeze check passed: all four reviewed files match the supplied SHA-256 list; HEAD is `23975b1b0`.

## Finding adjudication

- **CRITICAL-1 — FAIL.** The implementation is sound: the unconditional forecast uses only `r[:i]`, the basis is the aligned-sample loss difference `mean(QLIKE_uncond) − mean(QLIKE_GJR)`, the +1 check recomputes TOST, and `main()` raises if the verdict or p-value moves ([k1698.py:2504](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:2504>), [k1698.py:2597](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:2597>), [k1698.py:3004](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:3004>)). JSON confirms basis `0.2491569`, `n=436`, and unchanged `p_TOST=0.868961`. But the same PRIMARY JSON still defines the margin as `0.1 x mean QLIKE(GJR)` in both `margin_disclosure` and `limitations` ([results.json:626](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698_rev2_results.json:626>), [results.json:17693](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698_rev2_results.json:17693>)). Thus the estimator is fixed, but the current claim surface still asserts the rejected, non-invariant definition.

- **MAJOR-2 — FAIL.** `pre_mask = ~tail_mask` correctly retains file-D night PM, night AM and day ≤13:30, excludes `(13:30,13:45]`, and adds file D−1’s tail ([k1698.py:408](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:408>), [k1698.py:539](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:539>)). JSON and the run receipt report exactly two changed days, both outside OOS. However README limitation 9 still says **3 days** ([README.md:299](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/README.md:299>)), contradicting both the earlier README sections and PRIMARY JSON.

- **MAJOR-3 — PASS.** PM trade-date modes are computed per delivery, and the boundary record uses the active contract’s own mode; the file-wide mode is diagnostic only ([k1698.py:431](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:431>), [k1698.py:664](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:664>)). Classification is data-driven from whether any monthly TX contract has night ticks; active-only gaps are unexcused ([k1698.py:764](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:764>)). The abort for any unexcused gap is real and applies outside OOS too ([k1698.py:2828](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:2828>)). Current output: five file-wide exceptions, zero unexcused, zero boundary/stamp/OOS failures, 481 OOS audit days.

- **MAJOR-4 — FAIL.** Both sensitivities exist and reproduce the reported ranges; README consistently says q2’s house-guardrail verdict flips and must not be reported as passing. But PRIMARY JSON’s top-level `honest_reading` still says q2 has “formal support (`|t| = 3.13 > 3`)” without the bandwidth flip, post-hoc status, or multiplicity caveat ([results.json:124](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698_rev2_results.json:124>)). That directly restores the inference rev2b says it removed.

- **MAJOR-5 — FAIL.** q2 itself has `PREREGISTRATION_STATUS: POST_HOC` and explains the generic flag and missing multiple-testing correction ([results.json:525](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698_rev2_results.json:525>)). README also globally identifies q2, equivalence, and ablation as post-hoc. PRIMARY JSON does not: q1 equivalence and `rv_ablation` have no `PREREGISTRATION_STATUS`, and its generated `limitations` contain no global post-hoc/multiplicity disclosure. Therefore not every rev2 comparison carries the required disclosure.

- **MINOR-6 — FAIL.** The canonical q1 field correctly states that `delta_min_at_5pct` is the exact threshold ([results.json:522](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698_rev2_results.json:522>)), and README agrees. But PRIMARY JSON’s prominent `what_the_route_prose_over_reads` still reports “~14% of benchmark loss” and the old “below 20%” grid framing ([results.json:123](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698_rev2_results.json:123>)). README and JSON therefore do not agree.

- **STILL-OPEN-3 — PASS.** Amending the reported route label is legitimate here. The decision mapping and venue remain unchanged; the unsupported editorial inference is removed, while the original string is preserved verbatim twice and `route_label_amended=true` records the amendment ([k1698.py:2194](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:2194>)). The sweep found no surviving accepting-the-null claim outside preserved quotations and explicit repudiations. `GATE_REASON` and current `gate.route` clearly state that neither HAR superiority nor equivalence is established.

- **STILL-OPEN-7 — FAIL.** Neither `review_receipt_rev2.json` nor `review_verdict.json` exists, while README presents both as the remedy and PRIMARY JSON declares the receipt path ([README.md:56](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/README.md:56>), [results.json:12](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698_rev2_results.json:12>)). This is blocking because the frozen claim says the documentation defect is fixed when it is not, and the repository’s merge gate separately requires `review_verdict.json`.

## Standing checks

The headline gate and FRL/Journal of Forecasting short-note route are honestly qualified: current `GATE_REASON` and `GATE_ROUTE` explicitly say only the pre-registered leg failed and both substantive propositions remain unestablished. The execution receipt finishes normally at 288.8 seconds and matches the JSON.

New issues:

- **MAJOR — stale generated claim assembly:** several old rev2 strings remain hard-coded in `k1698.py`’s result-construction block, so rerunning reproduces the false loss-level margin, old 14%/20% framing, and q2 formal-support overclaim ([k1698.py:3154](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:3154>), [k1698.py:3238](</Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:3238>)). This must be fixed in the generator and regenerated, not patched directly in JSON.

- **MINOR — runtime documentation drift:** README says approximately 260 seconds, while the frozen receipt and JSON say 288.8 seconds.

CRITICAL-1: FAIL — invariant computation works, but PRIMARY JSON still asserts the obsolete non-invariant loss-level margin.  
MAJOR-2: FAIL — mask and output are fixed, but README still reports three changed days instead of two.  
MAJOR-3: PASS — active-contract stamp, evidence-based classification, and anywhere-abort are implemented and exercised.  
MAJOR-4: FAIL — sensitivity exists and README is honest, but PRIMARY JSON still claims q2 formally clears `|t|>3`.  
MAJOR-5: FAIL — only q2 is explicitly flagged; equivalence and ablation remain unflagged in PRIMARY JSON.  
MINOR-6: FAIL — exact threshold is present, but PRIMARY JSON retains incompatible 14%/20% prose.  
STILL-OPEN-3: PASS — amendment is transparent, preserves the preregistration, and removes unsupported inference.  
STILL-OPEN-7: FAIL — both claimed review files are absent.

VERDICT: FAIL
