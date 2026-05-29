# Knowledge.json K1259-rule Provenance Audit v2 — 2026-05-17 (Expanded Keywords)

**Subject**: `storage/memory/knowledge.json`
**Auditor**: main thread (jq-only, full-population walk)
**Predecessor**: `docs/knowledge_k1259_audit_2026_05_17.md` (v1)
**Rule reference**: `.claude/rules/experiments.md` "Audit methodology hard rule" — full population, not subset
**Trigger**: v1 § "Methodology caveats" #3 documented stat-keyword blind spot; v2 closes it with expanded regex list (DM/Welch/Patton/QLIKE/LR/F-stat/χ²/HAR/Sharpe-with-t/bootstrap-CI/Newey-West).

---

## Scope & method

- **Total entries scanned**: **2129** (`jq 'length'`; identical to v1 snapshot)
- **Method**: single jq pipeline, full-population walk, no Python load, no sampling, AUDIT ONLY (no mutations)
- **Keyword domains added vs v1 narrow** (`t-stat|t-value|p-value|p<0\.|p=0\.`):
  - `DM[- ]test`, `Diebold[- ]?Mariano`
  - `Welch`
  - `Patton`, `QLIKE`
  - `LR[- ]test`, `likelihood[- ]ratio`
  - `\bF\([0-9]` (F-statistic with df)
  - `χ²|χ2`, `chi[- ]?square`
  - `HAR\([0-9]`, `HAR-RV`
  - `Sharpe.{0,80}t[- ]?(stat|test|value)`, `Sortino...`
  - `bootstrap.{0,40}(CI|confidence)`
  - `Newey[- ]?West`, `HAC.{0,30}(adjust|correct|robust)`
- **Provenance check** (unchanged from v1): entry must have `experiment_id` / `experiment_ids` / `related_experiments` / `related_k`, OR contain inline `K\d{2,4}` text reference; otherwise → no-provenance.
- **VIOLATION vs WEAK heuristic** (honest categorization per task constraint): an entry that triggers an expanded keyword AND has no provenance is classified by proximity of digit-decimal numeric pattern to the keyword:
  - `VIOLATION` — numeric-near-keyword within 80 chars (i.e. quantitative result claim)
  - `WEAK` — keyword present but no nearby decimal number (likely method-description / definitional reference)

---

## Reconciliation against v1

| Set | Count | Notes |
|---|---:|---|
| **V1_NARROW** (re-run with v1 regex) | **201** | v1 report said 200; 1-entry drift consistent with the same 2128→2129 mid-day-write drift v1 noted on line 12 |
| **V1_EXPANDED_NEW** (caught by expanded keywords AND NOT by v1 narrow AND no provenance) | **123** | Net new — these were sitting in v1's CLEAN bucket |
| **Union (narrow ∪ expanded), no provenance** | **324** | 201 + 123 = 324 ✓ |

V1_NARROW + V1_EXPANDED_NEW are disjoint by construction (`expanded AND NOT narrow`).
**TRUE_NEW_VIOLATIONS = V1_EXPANDED_NEW = 123 entries.**

---

## Per-keyword breakdown of TRUE_NEW_VIOLATIONS (123)

Tally is by **primary trigger** (first matching keyword per entry, no double-count). VIOLATION vs WEAK split per the numeric-proximity heuristic.

### VIOLATION (76 entries — keyword + nearby numeric claim)

| Primary keyword | Count |
|---|---:|
| QLIKE | 67 |
| DM-test | 5 |
| HAR-RV | 4 |
| **Total** | **76** |

### WEAK (47 entries — keyword present but no numeric claim near it)

| Primary keyword | Count |
|---|---:|
| QLIKE | 26 |
| DM-test | 8 |
| HAR-RV | 3 |
| Patton | 3 |
| bootstrap-CI | 3 |
| Sharpe-with-t | 2 |
| Newey-West | 1 |
| chi-square-word | 1 |
| **Total** | **47** |

### Keywords with zero hits

`Diebold-Mariano` (spelled out), `Welch`, `LR-test`, `likelihood-ratio`, `F-stat (F(df))`, `chi-square-symbol (χ²)`, `HAR-paren (HAR(d))`, `Sortino-with-t`, `HAC-adj` — zero matches in `content + evidence + body` across all 2129 entries. Likely because (a) corpus authors prefer abbreviations (DM > Diebold-Mariano) and (b) some methods (Welch, LR) are rare in this volatility-prediction codebase.

---

## Sample 5 newly-flagged entries

### 5 random VIOLATION samples (numeric-claim, no provenance)

| # | Entry id | Primary keyword |
|---|---|---|
| 1 | `53a24a5b` | QLIKE |
| 2 | `1a14dfaa` | QLIKE |
| 3 | `24fc6506` | QLIKE |
| 4 | `00a0ea76` | QLIKE |
| 5 | `c135ff19` | QLIKE |

### 5 non-QLIKE VIOLATION samples (for keyword diversity)

| # | Entry id | Primary keyword |
|---|---|---|
| 1 | `0d724aad` | HAR-RV |
| 2 | `ee665577` | HAR-RV |
| 3 | `fb24066d` | DM-test |
| 4 | `2209b991` | HAR-RV |
| 5 | `2ffe439a` | DM-test |

---

## Updated total violation count

v1 reported `208 = V1(200) + V2(7) + V3(1)` (union, deduplicated). Adding V1_EXPANDED_NEW:

| Source | Count |
|---|---:|
| v1 V1 (narrow stat-claim) | 200 |
| v1 V2 (backdated) | 7 |
| v1 V3 (PASS no reviewer) | 1 |
| v1 union (deduped) | **208** |
| v2 V1_EXPANDED_NEW (76 VIOLATION + 47 WEAK) | **+123** |
| **Revised union upper bound** | **331** |

**Note on the +1 drift**: this audit's narrow re-run produced 201 (vs v1's 200). Treating v1's 208 as canonical and adding 123 net new yields 331; if you take this audit's narrow recount (201) instead, the union becomes 332. Either way, the order of magnitude (~330 hard provenance gaps) is the operative number.

If you split VIOLATION vs WEAK on the 123 new ones (76 numeric / 47 method-only):

| Tier | Count |
|---|---:|
| Hard violations (v1 208 + v2 numeric 76) | **284** |
| Soft / method-only (v2 47 + v1 WEAK 215) | **262** |
| Total surfaced for cleanup | **546** |

---

## Recommended additional cleanup batches (B6+)

Following v1's 50-per-batch pattern, the 76 new VIOLATION entries split as:

| Batch | Scope | Size | Commit message prefix |
|---|---|---:|---|
| **B6** | v2 numeric VIOLATION, oldest 50 by `created_at` | 50 | `fix(knowledge): backfill K-id for QLIKE/DM/HAR-RV claims — v2 batch 1/2` |
| **B7** | v2 numeric VIOLATION, remaining 26 | 26 | `fix(knowledge): backfill K-id for QLIKE/DM/HAR-RV claims — v2 batch 2/2` |
| **B8** (optional) | v2 WEAK (method-description only), 47 entries | 47 | `chore(knowledge): annotate method-only entries as legacy unsourced — v2 weak pass` |

**Sequencing**: run B6/B7 *after* B2-B5 (v1 narrow backfill) so writer-process patch lands first and the v2 cleanup can benefit from improved writer invariants (don't re-introduce the same gap mid-flight).

**Per-batch workflow** (identical to v1 § "Per-batch workflow"):
1. For each entry: grep `experiments/` and `experiment_experiences.json` for matching QLIKE/DM/HAR-RV numeric claim; if matched → add `experiment_id`; if not → demote `verdict` / strip stat claim / move to `experiment_experiences.json` as "legacy, unsourced".
2. Re-run this v2 audit script after each batch; confirm count drops by exactly the batch size.
3. **Process-fix** (per `永遠修流程，不修資料`): extend the CI invariant from v1 follow-up T3 — `assert experiment_id is not None when any of {QLIKE, DM-test, HAR-RV, Patton, Newey-West, χ², LR-test, F(df)} appear in content/evidence/body`. Single assertion covers v1 narrow + v2 expanded.

---

## Self-check

| Metric | jq output | Report |
|---|---:|---:|
| Total entries | 2129 | 2129 |
| V1_NARROW re-run | 201 | 201 |
| V1_EXPANDED_NEW | 123 | 123 |
| Narrow ∪ Expanded (no prov) | 324 | 324 (201+123 ✓) |
| V2 VIOLATION (numeric near keyword) | 76 | 76 |
| V2 WEAK (no numeric near keyword) | 47 | 47 |
| 76 + 47 | — | 123 ✓ |

No fabrication: every number above came from the consolidated jq pass; sums reconcile.

---

## Methodology caveats remaining (v3 candidates)

1. **`evidence` nested-structure recursion**: jq `tostring` coerces nested objects/arrays into JSON-string form, which preserves all leaf strings — so keyword detection is fine. But the numeric-proximity heuristic measures character distance in the stringified form, which is inflated by JSON syntax (`{"key":...`). A few WEAK classifications may actually be VIOLATIONs where the keyword and number are semantically adjacent but syntactically separated by JSON delimiters. Manual triage of the 47 WEAK should expect a ~5-10% promotion rate.
2. **Heuristic vs ground truth**: the numeric-near-keyword test is regex-based, not semantic. A sentence like "QLIKE was used to evaluate" (no number) → WEAK; "QLIKE benchmark of 0.512 in the literature (Patton 2011)" → VIOLATION even though it's a citation, not a self-claim. This is acceptable false-positive rate for an audit (errs on side of flagging).
3. **Acronym ambiguity**: `Patton` could match author citations (Patton 2011, 2020) rather than a Patton loss-function claim. 6 entries (3 VIOLATION-ish + 3 WEAK) total — manageable manual review burden.
4. **HAR-RV vs HAR coefficient claim**: `HAR-RV` may flag entries that just *mention* the model name without making a coefficient claim. The 4 VIOLATION entries should be sanity-checked manually before B6/B7 demotion.
5. **No coverage of**: ES test (Engle-Manganelli, Du-Escanciano), MCS (Hansen Model Confidence Set), DAC (directional accuracy), GW test (Giacomini-White). If corpus uses these, a v3 audit should add them. Quick `jq | grep -ci` probe before v3 is recommended to size the gap.

---

## Action items (NOT executed in this audit)

- [ ] **Follow-up T5**: run B6 + B7 (76 v2 numeric VIOLATION cleanup)
- [ ] **Follow-up T6**: manual triage of 47 WEAK entries; promote any with semantic numeric-claim adjacency to VIOLATION
- [ ] **Follow-up T7**: extend CI invariant from v1 T3 to cover expanded keyword set (single regex)
- [ ] **Follow-up T8** (optional v3 audit): add ES/MCS/DAC/GW keywords; estimate scope first with `jq | grep -ci` probe

Knowledge.json was **NOT modified** in this audit.
