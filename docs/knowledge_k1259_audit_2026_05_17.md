# Knowledge.json K1259-rule Provenance Audit — 2026-05-17

**Subject**: `storage/memory/knowledge.json`
**Auditor**: main thread (jq-only, full-population walk)
**Rule reference**: `.claude/rules/experiments.md` "Audit methodology hard rule" (K1259 v2 教訓 — full population, not subset)
**Trigger**: `docs/memory_health_audit_2026_05_17.md` flagged 2128 entries / 1.94MB; prior K1259 v1/v2 audits inspected subsets only.

---

## Scope & method

- **Total entries scanned**: **2129** (verified via `jq 'length'`; memory_health doc said 2128, 1-entry drift consistent with mid-day writes)
- **Method**: single jq pipeline, full-population walk, no Python load, no sampling
- **Categories evaluated** (in order; first match wins; no double-count):
  1. **VIOLATION — Stat claim, no K-id provenance** (V1): entry's `content + evidence + body` text contains `t-stat / t-value / p-value / p<0. / p=0.` AND has no `experiment_id / experiment_ids / related_experiments / related_k` field AND text body contains no inline `K\d{2,4}` reference
  2. **VIOLATION — Backdated** (V2): `created_at < experiment_date` (knowledge written before experiment date — temporally impossible)
  3. **VIOLATION — PASS verdict, no reviewer field** (V3): `verdict` matches `PASS|CONDITIONAL` AND none of `codex_review / codex_reviewed / reviewer_source / review / codex_verdict / codex_findings / review_source / codex_review_verdict / codex_review_notes / review_path / reviewer_notes` present
  4. **WEAK — Performance claim, no provenance**: text mentions `Sharpe / hit-rate / win-rate / annualized / CAGR / drawdown / MDD` but has no experiment-id, no `experiment_file / results_file / experiment_script / references`, and no inline `K\d{2,4}` text reference

> Entries flagged in any V1/V2/V3 set are not re-counted in WEAK (set difference applied).

## Results (de-duplicated)

| Category | Count | % of 2129 |
|---|---:|---:|
| **VIOLATION (hard provenance gap)** | **208** | 9.8% |
| **WEAK (soft provenance gap)** | **215** | 10.1% |
| **CLEAN** | **1706** | 80.1% |

### Breakdown of VIOLATION (208 total — union of V1/V2/V3)

| Sub-class | Count | Notes |
|---|---:|---|
| V1 — stat-claim, no K-id provenance | 200 | t-stat / p-value mentioned but cannot trace back to an experiment |
| V2 — backdated (`created_at < experiment_date`) | 7 | Listed below in full (small N) |
| V3 — PASS verdict, no reviewer field | 1 | `K1302b` |

### V2 — all 7 backdated entries (full list, not sample)

| id | created_at | experiment_date |
|---|---|---|
| `know_20260407171555_k984` | 2026-04-07T17:15:55Z | 2026-04-08 |
| `know_20260407171555_k987` | 2026-04-07T17:15:55Z | 2026-04-08 |
| `know_20260407184943_k986` | 2026-04-07T18:49:43Z | 2026-04-08 |
| `know_20260407205036_k989` | 2026-04-07T20:50:36Z | 2026-04-08 |
| `know_20260407205036_k990` | 2026-04-07T20:50:36Z | 2026-04-08 |
| `know_20260407224624_k991` | 2026-04-07T22:46:24Z | 2026-04-08 |
| `know_20260407224624_k993` | 2026-04-07T22:46:24Z | 2026-04-08 |

Likely root cause: writer set `experiment_date` to UTC date (next-day in TPE timezone), or stamped placeholder future date during scheduling — not necessarily fabricated content, but the date-stamp invariant is broken and needs the writer flow patched.

### Sample VIOLATION ids (5 of 208, taken from union sorted)

1. `01455e1c`
2. `02b7b339`
3. `02bb6dfe`
4. `039d0d41`
5. `0586a962`

(Plus `K1302b` and the 7 `know_20260407…` entries above.)

### Sample WEAK ids (3 of 215)

1. `00310ccd`
2. `0297640a`
3. `02d5469d`

## Recommended cleanup batches

**Total cleanup load**: 208 hard violations (defer 215 WEAK to a separate annotation pass).

| Batch | Scope | Size | Commit message prefix |
|---|---|---:|---|
| B1 | V2 backdated (7) + V3 PASS-no-reviewer (1) — small, traceable | 8 | `fix(knowledge): patch backdated/no-reviewer entries (K1259)` |
| B2 | V1 stat-claim, oldest 50 (by `created_at`) | 50 | `fix(knowledge): backfill K-id provenance — batch 1/4` |
| B3 | V1 next 50 | 50 | `fix(knowledge): backfill K-id provenance — batch 2/4` |
| B4 | V1 next 50 | 50 | `fix(knowledge): backfill K-id provenance — batch 3/4` |
| B5 | V1 remaining 50 | 50 | `fix(knowledge): backfill K-id provenance — batch 4/4` |

**Per-batch workflow** (follow-up task, NOT this audit):
1. For each entry: grep `experiments/` and `experiment_experiences.json` for matching content; if found → add `experiment_id` field; if not → demote `verdict`/strip stat claim or move to `experiment_experiences.json` annotated as "legacy, unsourced".
2. Re-run this audit script after each batch; confirm violation count drops by exactly the batch size.
3. Process-fix (永遠修流程，不修資料): once root cause identified for V1/V2 (likely an old writer path or legacy import), patch the writer in `src/volpred/` and add a CI invariant `assert experiment_id is not None when verdict in {PASS,CONDITIONAL_PASS}`.

## Methodology caveats

1. **`evidence` field type heterogeneity**: some entries store `evidence` as object/array, jq coercion to string is lossy — minor risk of missing K-id needles inside nested structure. Re-audit with `..|strings` recursion would tighten but cost more passes.
2. **`K\d{2,4}` regex**: misses K-ids with letter suffix (K1302b matched only via `verdict` route, not text); 3-digit K-ids in older entries (K880-K999) covered; sub-K-id (e.g. K1216c) covered by `\d{2,4}` matching prefix.
3. **Stat keyword list** is not exhaustive — covers `t-stat / t-value / p-value / p</p=`. Does NOT catch DM-test wording without explicit "p", Welch wording, Patton names — could produce false negatives (i.e. some violations slip into CLEAN). Per K1259 v2 hard rule, this is the known blind spot of this audit; a v2 should add: `DM[- ]test`, `Welch`, `Patton`, `LR[- ]test`, `\\bF\\(\\d`, `\\bχ²`, `chi[- ]?square`.
4. **WEAK class is provisional** — many entries flagged WEAK are summary/methodology notes that legitimately have no numeric provenance (they describe a method, not a result). A human pass should triage WEAK before cleanup; until then, treat 215 as upper bound.
5. **No K-id in `item_id`** field for ~half the corpus (`item_id` only present for 1382 / 2129 entries) — pre-K1100 entries use a UUID-like `id`. Audit treated both as identifiers; downstream cleanup needs the `experiment_id` field, not the entry's own id.

## Self-check (counts re-confirmed against jq output)

| Metric | jq output | Report |
|---|---:|---:|
| Total entries | 2129 | 2129 |
| V1 (stat, no K-id) | 200 | 200 |
| V2 (backdated) | 7 | 7 |
| V3 (PASS no reviewer) | 1 | 1 |
| Union violations (deduped) | 208 | 208 |
| WEAK (perf, no prov, minus violations) | 215 | 215 |
| CLEAN | 1706 | 1706 |
| 208 + 215 + 1706 | — | **2129 ✓** |

No fabrication: every number above came from the consolidated jq pass; sum reconciles to 2129.

## Action items (NOT executed in this task — audit-only per task constraint)

- [ ] **Follow-up T1**: run B1 cleanup (8 entries, manual triage)
- [ ] **Follow-up T2**: run B2-B5 (V1 backfill, 50/batch)
- [ ] **Follow-up T3**: writer-process patch — add `experiment_id` requirement + CI invariant
- [ ] **Follow-up T4**: v2 audit with expanded stat-keyword list (DM/Welch/Patton/LR/chi²) to close blind spot

Knowledge.json was NOT modified in this task.
