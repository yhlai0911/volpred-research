# Knowledge.json B1 Patch — K1259 Cleanup, 2026-05-17

**Subject**: `storage/memory/knowledge.json` (8 entries)
**Executor**: general-purpose subagent (per B1 dispatch from `docs/knowledge_k1259_audit_2026_05_17.md`)
**Method**: single atomic `jq` rewrite, full-file hash diff to verify untouched-entry invariance
**Scope**: V2 backdated (7) + V3 PASS-no-reviewer (1) — exactly 8 entries

---

## V2 — Root cause: TPE/UTC timezone artifact (not fabrication)

**Evidence chain**:
1. Audit flagged `created_at = 2026-04-07T17:15..22:46Z` < `experiment_date = 2026-04-08`.
2. `git log --diff-filter=A --pretty=format:'%ad' --date=iso -- experiments/k98X/` for all 7 dirs returns commits at **2026-04-08 00:45–06:45 +0800 (TPE)**.
3. UTC times `17:15Z–22:46Z` on 2026-04-07 = TPE `01:15–06:46` on **2026-04-08**.
4. Conclusion: **experiment was genuinely run on 2026-04-08 TPE**, but writer recorded `experiment_date` from TPE-local date while `created_at` was UTC — date-string mismatch is a timezone bug, not temporal impossibility.

**Decision** (per task instruction: "prefer `experiment_date = created_at` direction — assumes writer process timestamp was correct, schema field placeholder was wrong"):
Patch `experiment_date` to the **UTC date of `created_at`** (`2026-04-07`) to restore the date-stamp invariant `created_at >= experiment_date`. The conservative direction; canonical experiment time in any future audit should re-derive from `created_at` UTC.

**Process-fix recommendation** (NOT executed here): writer (`src/volpred/` knowledge writer path) should normalize `experiment_date` to `created_at[:10]` (UTC) on insert, not derive from local-time `datetime.date.today()`.

### V2 per-entry patch table

| id | created_at (unchanged) | experiment_date BEFORE | experiment_date AFTER | git first-commit (TPE) | Evidence |
|---|---|---|---|---|---|
| `know_20260407171555_k984` | 2026-04-07T17:15:55Z | 2026-04-08 | **2026-04-07** | 2026-04-08 00:45:17 +0800 | UTC 17:15Z = TPE 01:15 next-day; commit aligns |
| `know_20260407171555_k987` | 2026-04-07T17:15:55Z | 2026-04-08 | **2026-04-07** | 2026-04-08 01:14:51 +0800 | same writer batch as k984 |
| `know_20260407184943_k986` | 2026-04-07T18:49:43Z | 2026-04-08 | **2026-04-07** | 2026-04-08 02:49:02 +0800 | UTC 18:49Z = TPE 02:49 next-day |
| `know_20260407205036_k989` | 2026-04-07T20:50:36Z | 2026-04-08 | **2026-04-07** | 2026-04-08 04:49:26 +0800 | UTC 20:50Z = TPE 04:50 next-day |
| `know_20260407205036_k990` | 2026-04-07T20:50:36Z | 2026-04-08 | **2026-04-07** | 2026-04-08 04:45:30 +0800 | same writer batch as k989 |
| `know_20260407224624_k991` | 2026-04-07T22:46:24Z | 2026-04-08 | **2026-04-07** | 2026-04-08 06:44:11 +0800 | UTC 22:46Z = TPE 06:46 next-day |
| `know_20260407224624_k993` | 2026-04-07T22:46:24Z | 2026-04-08 | **2026-04-07** | 2026-04-08 06:45:28 +0800 | same writer batch as k991 |

All 7 share the same root cause; the patch is uniform and provable from git log + timezone math.

---

## V3 — K1302b reviewer field backfill

**Evidence chain**:
1. Audit flagged `verdict=PASS` with no `codex_review` / `reviewer_source` field.
2. Inspecting the entry's `content` text reveals: *"Codex primary review CONDITIONAL_PASS (0 CRITICAL, 1 MINOR README wording fixed in 2026-05-16 follow-up commit)"*.
3. `experiments/k1302b/README.md` reviewer checklist: *"Codex review PASS — main thread runs post-merge before any knowledge.json write"* + *"Main thread runs Codex review on `experiments/k1302b/k1302b.py`"*.
4. Conclusion: review **did occur** (Codex primary review, CONDITIONAL_PASS); only the structured schema field was missing.

**Decision**: Backfill structured fields rather than demoting verdict — the verdict is genuinely supported by a documented review.

### V3 K1302b patch

| Field | BEFORE | AFTER |
|---|---|---|
| `verdict` | `"PASS"` | `"PASS"` (unchanged — `closure_status` already records `codex_conditional_pass_minor_addressed`) |
| `codex_review` | — (missing) | `"CONDITIONAL_PASS"` |
| `codex_review_notes` | — (missing) | `"Codex primary review: 0 CRITICAL, 1 MINOR (README wording, fixed in 2026-05-16 follow-up commit). Source: content text + experiments/k1302b/README.md reviewer checklist."` |
| `reviewer_source` | — (missing) | `"Codex primary review (main thread)"` |
| `review_path` | — (missing) | `"primary"` |

Verdict NOT demoted: evidence supports the original PASS classification (Codex primary path verdict was CONDITIONAL_PASS, MINOR was addressed → effectively PASS, mirroring how `closure_status` already records it).

---

## Atomic-write verification

| Check | Result |
|---|---|
| `jq 'length'` before vs after | 2129 → 2129 (unchanged) |
| File size delta | +336 bytes (consistent with 7 date-string rewrites neutral + 4 new K1302b fields) |
| md5 of all non-targeted entries (`jq -c \| sort \| md5`) before vs after | `ef1bb28333b92d144bd87146d9335103` ≡ `ef1bb28333b92d144bd87146d9335103` (identical — no other entry mutated) |
| Targeted re-extract of 8 ids shows expected new field values | ✓ confirmed |

---

## Honesty notes

- **V2 direction** chosen per task instruction (`experiment_date = created_at` direction = conservative). Alternative interpretation (experiment_date is real, created_at is wrong by a day) was rejected because (a) UTC→TPE math precisely explains the discrepancy, (b) git commits at 00:45–06:45 TPE on 2026-04-08 = UTC 16:45–22:45 on 2026-04-07, fully consistent with `created_at` timestamps being correct UTC writes.
- **V3** could alternatively demote to UNVERIFIED if we required `reviewer` evidence to live *only* in structured fields. We did not: the `content` text already contains a specific, verifiable claim about Codex CONDITIONAL_PASS that can be re-validated against git history of `experiments/k1302b/` if doubted. Adding structured fields backfills the schema without rewriting attested history.
- No git commit made; main thread to inspect diff + commit per task constraint.

---

## Follow-up

- B2-B5: V1 stat-claim backfill (200 entries, 50/batch).
- Writer-process patch: `experiment_date := created_at[:10]` on knowledge insert + CI invariant `assert reviewer_source is not None when verdict in {PASS,CONDITIONAL_PASS}`.
