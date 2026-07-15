# K1396 scope-repair review certification — 2026-07-16

- **Reviewed commit:** `36eb1e51214c53a3bee1d192783bdc77268940e0`
- **Reviewer:** Codex GPT-5, independent read-only review
- **Verdict:** `PASS`
- **Review scope:** the K1396 correction and supersession claim surface, not
  promotion of the frozen legacy estimates as current scientific evidence

## Review conclusion

The repair correctly classifies K1396 as
`SUPERSEDED_HISTORICAL_DIAGNOSTIC_ONLY` and withdraws every unsupported public
claim found in the legacy artifact: canonical HAR-RV, exact K988 replication,
A4f non-inferiority/equivalence, three-model parity, cross-proxy consistency,
and incremental VIX evidence from the nested raw-loss DM comparison.

The frozen `k1396_results.json` remains byte-for-byte unchanged. The new scope
audit separates historical values from current conclusions and fails closed if
either the frozen K1396 result or certified K1379 result drifts from its pinned
SHA-256.

## Evidence checked

- K1396 target and HAR-style inputs are daily close-to-close `r²`, not
  intraday realized variance.
- The legacy A4f forecast resets `g` to its unconditional steady state at every
  OOS date; it is not the canonical K988 recursive path.
- The legacy custom HAC-DM helper has no HLN correction and cannot establish
  equivalence or non-inferiority.
- HAR-style daily-r²-VIX nests the base daily-r² model; its raw QLIKE DM value
  is correctly isolated as diagnostic-only.
- Original input vintage is unpinned and cannot independently reproduce the
  stored `n=1,866`; the repair-time file diagnostic is explicitly not presented
  as original-run provenance.
- Certified K1379 fields match exactly: valid OOS `n=1,852`, 2019-01-02 through
  2026-05-18, A4f QLIKE `1.3998120448`, HAR-style daily-r² QLIKE
  `1.5244605586`, advantage `8.1765653542%`, DM `t=-7.6985543503`, and
  `p=2.2204460493e-14`.
- Both replacement charts were inspected at original resolution. Labels,
  superseded watermark, protocol caveat, and footer are visible without
  clipping or overlap.

## Verification run

- `uv run pytest -q experiments/k1396/test_scope_repair.py` → `6 passed`.
- `uv run python scripts/experiment_gates.py run --path experiments/k1396` →
  PASS across four integrity gates.
- Rebuilding the scope audit and both figures is deterministic; their bytes did
  not drift in the final delta review.
- Python compilation and `git diff --check` pass.

## Blocking defects

None.

## Remaining boundary

K1379 is a corrected daily-r² comparison, still not a canonical intraday
HAR-RV benchmark. The repair preserves that limitation and does not claim that
Paper 9's intraday benchmark gap is closed.
