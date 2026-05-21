# K1259 Codex Code Review v2 — Primary-Path Verification (FAIL)

**Review date**: 2026-04-29 (CST), task `task-moiszyai-2sik97`, 5m 5s
**Reviewer**: Codex CLI 0.121.0 (gpt-5.4 default), session `019dd4c9-bf01-78c2-9fc5-7d8bf23032ce`
**Trigger**: After Codex CLI 4-day blocker resolved (commits `abc71f9f` config fix +
`b3e4ca0a` production-path verified), re-review today's K1259 audit work via
**primary path** to validate the original subagent-fallback verdict.

**Scope**: 4 commits — `aff7b4a5` (NON_DM_PATH_TOKENS filter) + `53c1d559`
(apply_phase15_backfill.py + asset map) + `d4c2faf1` (load_ledger docstring) +
`b1f85845` (knowledge entry refresh).

---

## Verdict: **FAIL** (contradicts subagent v1 PASS-with-caveats)

**Findings**: 0 CRITICAL / 0 SEVERE / 2 MAJOR / 1 MED / 1 MINOR

**Comparison vs v1 subagent review** (`codex_review.md`):
- Agree: MAJOR-1 (Phase 1.5 backfill scripted) is resolved. `apply_phase15_backfill.py` + pinned map make Phase 1.5 replay reproducible.
- **Contradict**: MAJOR-2 closure is **NOT supported**. Ledger is not provenance-clean.
- **Additional findings**: 12+ residual non-DM rows outside today's blacklist, target-asset semantic ambiguity in pinned map.

---

## MAJOR-1 (NEW) — NON_DM_PATH_TOKENS undercoverage

`build_dm_ledger.py:229` `NON_DM_PATH_TOKENS = (ttest, mcnemar, wilcoxon, kstest,
kruskal)` blocks only those 5 token patterns. The extractor still admits clear
non-DM rows via generic `{t_stat, p_value}` / `{t, p_value}` shapes at
`get_dm_stat:141` and pair-walk at `iter_pair_entries:247`.

**Concrete residual non-DM rows in current `dm_ledger.json` (2730 rows)**:

| K | source_field_path | Why not DM | Verified |
|---|---|---|---|
| K528 | `statistical_tests.A_nfp_vs_all` | NFP-day t-test of conditional means | ✓ jq |
| K528 | `statistical_tests.B_nfp_vs_friday` | same | ✓ jq |
| K594 | `statistical_tests_pooled.adaptive_vs_fixed_2000` | pooled strategy t-test | ✓ jq |
| K594 | `statistical_tests_pooled.adaptive_vs_fixed_504` | same | ✓ jq |
| K594 | `statistical_tests_pooled.adaptive_vs_12_vix` | same | ✓ jq |
| K594 | `statistical_tests_pooled.adaptive_vs_buy_hold` | same | ✓ jq |
| K658 | `reentry_strategies.stat_test_30_vs_w20` | re-entry strategy stat test | ✓ jq |
| K975 | `welch_test_bw_vs_contango` | Welch t-test (NOT DM) | ✓ jq |
| K990 | `statistical_tests.vt_spy_vs_vt_only` | VT comparison t-test | ✓ jq |
| K1006 | `statistical_tests.overnight_gap_vs_zero` | one-sample test against zero | ✓ jq |
| K1006 | `statistical_tests.overnight_return_vs_zero` | same | ✓ jq |
| K1006 | `statistical_tests.naive_net_vs_zero` | same | ✓ jq |

**Token gap**: residuals come from `statistical_tests`, `stat_test_`, `welch`,
`_vs_zero`. None covered by current 5-token blacklist.

**Verification (2026-04-29 main-thread `jq` audit)**:
- `[.rows[] | select(.source_field_path | test("statistical_tests"; "i"))] | length` = **10**
- `[.rows[] | select(.source_field_path | test("welch"; "i"))] | length` = **1**
- `[.rows[] | select(.source_field_path | test("vs_zero"; "i"))] | length` = **3**
- 1 stat_test_ (K658) outside `statistical_tests` parent

Total residual ≥ 12+ rows confirmed. Codex finding stands.

**Suggested fixes**:
- Option A (Codex-recommended): replace blacklist with **positive DM gate** —
  path must contain `dm`, `harvey`, or `hln` (case-insensitive). More
  conservative but might miss legitimate DM rows in odd-named experiments.
- Option B (additive): extend `NON_DM_PATH_TOKENS` with `welch`, `stat_test`,
  `statistical_test`, `vs_zero`. Less risk of false-negative drop but requires
  ongoing maintenance as new patterns emerge.
- Both options need follow-up MCS re-run with seed=42 to verify Phase 2
  superior_set stability (today's run on 2730 rows gave 1 cosmetic change vs
  2741; further removal of ~12 rows might have similar small impact).

## MAJOR-2 (NEW) — Audit methodology too narrow; closure claim unsupported

`generic_key_audit.md:20` re-walks **only** rows where the first matched key
was `t` or `stat` (393 of 2367 navigable rows). Path heuristic at
`generic_key_audit.md:43` treats `_vs_` as compatible DM evidence.

**Blind spots**:
- Non-DM rows keyed by `t_stat` (priority position 5 in `get_dm_stat`) are NOT
  in the generic-key subpopulation, so the audit never inspects them.
- Specifically, `K528 / K594 / K658 / K975 / K990 / K1006` non-DM rows above
  are keyed via `t_stat` field, not `t` or `stat`, so the audit's "393 generic-key
  matches, 11 false-positives" framing missed them.
- The `_vs_` heuristic is **misleading** — many non-DM tests use `_vs_`
  naming convention (`adaptive_vs_fixed_2000`, `vt_spy_vs_vt_only`).

**Closure language to retract**:
- `generic_key_audit.md:125` "Closes K1259 MAJOR-2... fully reviewed and
  provenance-clean" — premature.
- `experiments/k1259/README.md` audit row "11 false-positives 已從 ledger 移除" —
  understates the actual residual.
- `storage/memory/knowledge.json` entry `c4db347a` confidence=0.88 + content
  "fully reviewed and provenance-clean" — must be downgraded.
- `research_program.md` K1259 row "review-cycle 全結 2026-04-28" — must revert.
- `docs/project_improvement_status.md` "K1259 review-cycle 全結 2026-04-28
  3/3 MAJORs closed" — must revert MAJOR-2 specifically.

**Suggested fix**: re-audit ALL 2730 rows (not just generic-key subset),
output residual non-DM list explicitly, and only reclaim closure after fix
implemented + ledger row count stabilizes.

## MED — phase15_asset_map.json target-asset semantic ambiguity

`K1128`, `K1130`, `K1131` are TAIFEX TX 5-min jump-prediction experiments
(per their READMEs); VIX is used as a **lagged regime/conditioning variable**,
not the forecast target. Singleton `VIX` mapping is honest extract from
existing ledger but **semantically wrong** if `asset` means
target/traded asset (which is what Phase 2 MCS assumes when grouping rows
into per-asset T-matrices).

`K1006` has the same issue but its rows are already non-DM (will be removed
when MAJOR-1 fix lands).

**Suggested fix**: clarify `asset` semantics in `dm_ledger_summary.md`:
- "target/forecast asset" → re-tag K1128/K1130/K1131 to TX (TAIFEX)
- "primary entity in pair comparison" → keep VIX, but document the convention

This is independent of MAJOR-1/2 — the asset-tag question is about
interpretation, not extraction. Lower priority.

## MINOR — Inline comment row count mismatch

`build_dm_ledger.py:227` says "audit found 5 such rows from K744 / K789 /
K1059", but `generic_key_audit.md:51` documents **11 rows from 5
K-experiments** (K649×4, K706×2, K744×2, K1059×2, K789×1).

**Suggested fix**: update or remove the numeric/commentary claim.

## Direct answers to original review questions

- **Q1 idempotency**: PASS. `apply_phase15_backfill.py:75` skips already-tagged
  rows; `:83` skips non-empty `asset` rows. Re-run is row-level no-op. Mixed
  provenance observed (e.g. K512 has both `asset_source=null` rows and
  backfilled rows) — script correctly leaves prefilled rows untouched.
- **Q2/Q3 NON_DM_PATH_TOKENS**: filter works as written; zero residual paths
  match the 5 tokens. Real problem is **undercoverage**, not false negatives
  within those tokens. Hypothetical `Wilcoxon-DM-test` would be filtered by
  substring match.
- **Q4 phase15_asset_map.json**: provenance honest. Concern is target-asset
  semantic correctness for VIX singletons (MED above), not fabrication.
- **Q5 audit blind spot**: yes. Bigger issue than 374 not-navigable — only
  re-walked generic-key subset, misses `t_stat`-keyed non-DM rows.
- **Q6 row-count invariant**: numerically consistent (`2741 − 11 = 2730`),
  but 2730 is **NOT** a DM-clean final ledger; residual non-DM rows remain.

---

## Lessons (process-improvement)

1. **Subagent fallback ≠ primary-path Codex**. Today's K1259 audit went
   through `feature-dev:code-reviewer` because Codex CLI was blocked. Subagent
   PASSED but Codex (post-restoration) caught real issues. Going forward,
   when Codex is available, subagent should be **secondary** opinion — not
   substitute for primary review.
2. **"Provenance-clean" claims need full-population audit**, not subset
   sampling. Audit methodology that only re-walks generic-key subset
   guarantees missing `t_stat`-keyed false positives.
3. **Blacklist designs need maintenance schedule**. Pattern blacklist
   (`NON_DM_PATH_TOKENS`) only catches what authors had in mind that day.
   Positive DM gate is more conservative but bounds the false-positive
   surface to a known constant.
4. **Update knowledge.json + research_program.md + project_improvement_status
   atomically when retracting**. Not doing so leaves stale claims standing
   in canonical sources of truth.

## Next slot's required follow-up

1. Choose Option A (positive DM gate) or B (extended blacklist) for MAJOR-1
   fix in `build_dm_ledger.py`.
2. Re-run pipeline: `build_dm_ledger.py` → `apply_phase15_backfill.py` →
   `k1259_mcs.py` (seed=42 for stability check).
3. Document residual rows AFTER fix + new row count.
4. Update knowledge entry to reflect post-fix state with proper confidence.
5. Address MED (asset semantic clarification) + MINOR (comment fix).
