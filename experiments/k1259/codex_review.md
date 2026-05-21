# K1259 Code Review — feature-dev:code-reviewer subagent fallback (Codex blocked)

**Review date**: 2026-04-28
**Reviewer**: code-reviewer subagent (claude-sonnet-4-6), fresh-context independent review
**Reason for subagent review**: Codex CLI blocker persists (model = "gpt-5.5" unavailable). Per `.claude/rules/experiments.md` Fallback clause: "Codex CLI 不可用時，改派 `feature-dev:code-reviewer` subagent 做 independent fresh-context review. Knowledge entry 必註明 reviewer source."
**Scope**:
- `experiments/k1259/build_dm_ledger.py` (603 lines) — Phase 1 DM pair ledger builder
- `experiments/k1259/k1259_mcs.py` (467 lines) — Phase 2 MCS algorithm driver
- `experiments/k1259/dm_ledger.json` — actual on-disk ledger (Phase 1.5 version)
- `experiments/k1259/k1259_mcs_results.json` — Phase 2 MCS output
- `experiments/k1259/README.md` + `k1259_README_phase2_appendix.md`

---

## Summary

**Overall verdict: PASS-with-caveats.**

Core algorithmic logic (MCS iterative elimination, antisymmetric bootstrap null, p-value formula, seed fixation, model-name normalization, dedup policy, schema projection) is correctly implemented. No lookahead risk exists in either phase — Phase 1 is purely retrospective aggregation of completed K-experiment results, Phase 2 consumes a static ledger with no temporal structure. No shared-state writes. Phase 2 is bit-reproducible given the current `dm_ledger.json`.

Three MAJOR items are provenance/documentation issues, not algorithmic correctness blockers. Acceptable to proceed with `knowledge.json` write under subagent integrity gate. Phase 3 article must explicitly cite the Variant A limitations documented in the appendix (already done).

**Finding count**: 0 CRITICAL / 0 SEVERE / 3 MAJOR / 2 MED / 3 MINOR

---

## Per-check verdicts

| # | Check | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | Phase 1 schema 12-key strict enforcement | PASS-with-caveats | `main()` L427 projects exactly `ROW_KEYS` before writing. However, on-disk `dm_ledger.json` has `"phase": "1.5_asset_backfill"` and rows carry extra `"asset_source"` key — ledger was overwritten by a Phase 1.5 backfill not in the reviewed code. See MAJOR-1. |
| 2 | Nested JSON walk NoneType / key collision safety | PASS | `iter_pair_entries` guards `isinstance(node, dict/list)` at every branch. `get_numeric` checks `isinstance(d, dict)` before key access. `extract_rows_from_file` wraps `json.load` in `try/except`. No unguarded attribute access. |
| 3 | Harvey-adjustment identification | PASS | `get_harvey_flag()` checks explicit bool keys, string coercion ("true"/"yes"/"1"), and structural inference (`DM_HLN_t`, `harvey_t`, `harvey_p` → True). Unknown cases return null per README policy. |
| 4 | `get_dm_stat` generic key false-positives | MAJOR | Keys `"t"` and `"stat"` match any dict with those field names. See MAJOR-2. |
| 5 | sample_n / period multi-schema handling | PASS | `detect_sample_n` tries 6 root keys; `resolve_sample_n` checks pair_dict first then falls back to root. `detect_period` handles dict-period (start/end), string-period, OOS_start, subperiod regex, and context hits. No hardcoded schema assumed. |
| 6 | Idempotent re-run Phase 1 | CONDITIONAL PASS | Phase 1 script is internally idempotent. But re-running alone overwrites Phase 1.5 backfill in `dm_ledger.json`. Full pipeline (Phase 1 + Phase 1.5) is not documented as a single reproducible command. See MAJOR-1. |
| 7 | MCS HLN 2011 Variant A step-by-step match | PASS | `mcs_test()`: init M₀ = all indices; while \|M\|>1: off-diagonal row-max T_max_obs; B=1000 antisymmetric Gaussian bootstrap; p = (1 + #{T_max,b ≥ T_max_obs}) / (B+1); if p < α eliminate argmax else stop. Matches appendix sec.1 algorithm exactly. |
| 8 | Antisymmetric bootstrap correctness | PASS | L326: `g = (g - g.T) / sqrt(2)` yields antisymmetric matrix with `g[i,j] ~ N(0,1)`, `g[j,i] = -g[i,j]`. Division by sqrt(2) preserves unit marginal variance. Diagonal set to -inf. Mathematically correct for Variant A Gaussian null. |
| 9 | Loss function / alpha testing structure | PASS | Outer loop: ASSETS × LOSS_FNS; inner loop: ALPHAS. Each (asset, loss_fn) builds one T-matrix shared across α calls. α=0.10 and α=0.20 run on same T independently. Results stored as `alpha_0.10`, `alpha_0.20` subkeys. |
| 10 | 18/20 MCS runs claim | PASS | Config: 5 × 2 × 2 = 20 theoretical runs. 0050.TW/MSE has zero DM rows → `insufficient_models` status → 2 alpha runs skipped = 18 actual runs. Appendix sec.5 table confirms. Claim in task brief is accurate. |
| 11 | p-value formula correctness | PASS | L331: `p = (1 + #{T_max,b >= T_max_obs}) / (B+1)` — standard Monte Carlo p with continuity correction. L332: lower-bounded at `1/(B+1)` to prevent p=0. Matches Hansen (2005) / Romano & Wolf convention. |
| 12 | Seed / reproducibility | PASS | `SEED = 42`; `rng = np.random.default_rng(seed)` (modern seeded Generator, not legacy). Phase 2 output verified bit-identical on re-run per appendix sec.7. Phase 1 deterministic given same input JSONs. |
| 13 | Pair-orientation canonical aggregation (L243) | PASS (confusingly written) | `if (a, b) in pair_t or (b, a) not in pair_t` is the De Morgan complement of "else if (b,a) seen but (a,b) not". All three cases handled correctly: new pair → (a,b) created; existing (a,b) → append; existing (b,a) only → else branch flips sign. See MINOR-2. |
| 14 | T-matrix antisymmetry enforced | PASS | L271: `T[j, i] = -t_agg` set explicitly after `T[i, j] = t_agg`. Diagonal initialized 0. `np.ix_` submatrix extraction preserves antisymmetry. |
| 15 | No lookahead / data leakage | PASS | Phase 1 reads completed K `*_results.json` — retrospective. Phase 2 reads static ledger — no temporal structure. No forecast-contamination path exists. |
| 16 | Shared-state write isolation | PASS | Neither script touches `storage/memory/*.json`, `feed.json`, `paper/*`, or Supabase/Mirror sync. All output confined to `experiments/k1259/`. |
| 17 | Phase 2 output schema self-describing for Phase 3 | PASS | `k1259_mcs_results.json`: top-level keys `experiment_id, phase, variant, variant_rationale, config, results, summary` present. Per-cell: `n_models_input, candidate_models, n_pairs_total, alpha_0.10, alpha_0.20`. Per-alpha: `superior_set, eliminated_ordered, n_models_survived, final_stopping_p, bootstrap_B, seed, trace`. Complete for Phase 3 consumption. |
| 18 | Coverage gap logging (Phase 1) | PASS | `missing_dm` list collects all files without extractable DM rows; written to ledger header as `n_files_without_dm`. Summary MD flags assets <5 rows and models ≤2 rows. No silent swallowing. |
| 19 | `load_ledger` loss_fn filter doc/code mismatch | MAJOR | Docstring claims "loss_fn must be recognized" but code never enforces this. See MAJOR-3. |
| 20 | Same-seed bootstrap for both alpha runs | MINOR | Both alpha=0.10 and alpha=0.20 pass `seed=42`; each creates independent `np.random.default_rng(42)` — sequences are independent (modern Generator, no shared state). Results identical because superior sets collapse at same stopping p. See MINOR-3. |

---

## Severity classification

**CRITICAL (blocks knowledge.json write): 0**

**SEVERE (must address pre-paper): 0**

### MAJOR (document and disclose; non-blocking for knowledge.json)

**MAJOR-1: `dm_ledger.json` is Phase 1.5 output, not Phase 1 — code/data provenance mismatch**

Evidence: `dm_ledger.json` L3 shows `"phase": "1.5_asset_backfill"`. All rows include extra `"asset_source"` key not in the 12-key `ROW_KEYS` schema. `dm_ledger_summary.md` L1 confirms: "Generated by `build_dm_ledger.py` (Phase 1) and augmented by main-thread asset backfill (Phase 1.5, 2026-04-20)." The Phase 1.5 backfill re-tagged 67 singleton rows and 1023 multi-asset rows, increasing asset coverage from 38% to 78%.

Impact: (a) Re-running `build_dm_ledger.py` alone overwrites the Phase 1.5 backfill, breaking Phase 2 reproducibility from scratch. (b) `dm_ledger.json` `row_schema` header claims 12 keys but actual rows have 13; Phase 2 `load_ledger` ignores unknown keys (harmless functionally). (c) Phase 3 readers cannot reproduce `dm_ledger.json` from the committed code alone.

Required action: Commit the Phase 1.5 backfill script to `experiments/k1259/` (e.g., `build_dm_ledger_phase15_backfill.py`). Update README to show two-step pipeline command sequence. Until then, treat `dm_ledger.json` as a committed artifact — do not re-run Phase 1 alone.

**MAJOR-2: `get_dm_stat` matches on generic keys `"t"` and `"stat"` — false-positive extraction risk**

Evidence: `build_dm_ledger.py` L148 and L153: keys searched by `get_dm_stat` include `"t"` (single-char, matches GARCH parameter `t`, time-step variable, degrees-of-freedom) and `"stat"` (common generic statistic field). Any experiment result dict containing `{"t": 1.23, ...}` will be flagged as a DM pair entry by `iter_pair_entries` Case A.

Impact: Silent extraction of non-DM statistics as DM rows. Downstream protection is partial: model-name filter in `extract_rows_from_file` L356–362 skips rows where model names cannot be resolved AND no `winner`/`better_model` field exists. But if a non-DM dict incidentally has a parseable parent key label (e.g., `"GARCH_vs_EWMA"`) and a numeric `"t"` field, a spurious row enters the ledger. The 2741-row ledger was not audited for false-positive rows from these generic keys.

Required action: For Phase 3, spot-check ledger rows where `source_field_path` ends in a key matched by `"t"` or `"stat"` (not `"dm_stat"`, `"dm_t"`, `"t_stat"`, `"harvey_t"`, `"DM_HLN_t"`). Low-impact given dedup and model-name filtering, but a targeted audit would strengthen provenance.

**MAJOR-3: `load_ledger` docstring/code mismatch on loss_fn filter**

Evidence: `k1259_mcs.py` L167–168 docstring: "loss_fn must be recognized" listed as filter rule. Code L196–208: no such filter implemented — rows with `loss_fn = "Parkinson"`, `"ES"`, `"FZ1%"`, `"FZ"` pass `load_ledger` and enter `kept`. They are excluded only at `build_t_matrix` because MCS iterates only `LOSS_FNS = ["QLIKE", "MSE"]` cells.

Impact: No functional impact on MCS results. However, the docstring misleads Phase 3 engineers who might write code iterating `kept` rows and assume Parkinson/ES/FZ rows are absent.

Required action: Remove "loss_fn must be recognized" from the docstring, or add `if r.get("loss_fn") not in RECOGNIZED_LOSS_FNS: continue` to the filter loop.

### MEDIUM

**MED-1: QLIKE-by-default rows not distinguished from confirmed QLIKE in ledger**

`resolve_loss` L323 returns `"QLIKE"` as a fallback default when neither pair_dict nor ctx_path contains any loss-function signal. The ledger contains 2263 QLIKE rows, but no flag distinguishes confirmed QLIKE (from explicit `loss`/`loss_fn` field or strong context) from inferred QLIKE (fallback). Phase 2 MCS aggregates both. This is a transparency issue. Suggested fix: add `"loss_fn_inferred": true/false` to the row schema in a future Phase 1 revision.

**MED-2: Appendix does not clarify that α=0.10 and α=0.20 bootstrap draws are independent**

Both alpha calls to `mcs_test` use `seed=42` but create independent `np.random.default_rng(42)` instances (modern Generator does not share state). The appendix sec.2 and sec.5 do not clarify this, so readers might wonder if the identical superior sets result from shared random state rather than the algorithm's stopping behavior. A one-line note in the appendix would suffice.

### MINOR

**MINOR-1: Bootstrap inner loop not vectorized (performance)**

`mcs_test` L323–328: pure Python loop of B=1000 iterations, each generating one `(m×m)` normal matrix. For SPY/QLIKE with m=100, this is 10M float operations per MCS run, run serially. Vectorizable as `rng.standard_normal((B, m, m))` → antisymmetrize → `max` reduction along axes. No correctness impact; runtime is acceptable for a one-shot analysis.

**MINOR-2: `pair_t` canonical orientation logic correct but unreadable (L243)**

```python
if (a, b) in pair_t or (b, a) not in pair_t:
    pair_t[(a, b)].append(t)
else:
    pair_t[(b, a)].append(-t)
```

The logic is correct (see check #13) but the condition is the De Morgan inverse of the intended "if (b,a) exists and (a,b) does not, flip sign; else use (a,b)". Clearer rewrite:

```python
if (b, a) in pair_t and (a, b) not in pair_t:
    pair_t[(b, a)].append(-t)
else:
    pair_t[(a, b)].append(t)
```

**MINOR-3: Edge case — `mcs_test` with `len(models)==1` or 0 not exercised in tests**

`build_t_matrix` can return `keep_models=[]` or `keep_models=["X"]` when data is sparse. `main()` guards with `len(models) < MIN_CANDIDATE_MODELS` before calling `mcs_test`, so the edge is handled. `mcs_test` would also not crash on empty models (while condition immediately False). No failure path, but no unit test exercises this guard.

---

## Recommendations

1. **Commit Phase 1.5 backfill script** to `experiments/k1259/` with full docstring explaining the two-step pipeline. Update README command sequence. (MAJOR-1 — required for reproducibility.)
2. **Fix `load_ledger` docstring** (MAJOR-3): remove "loss_fn must be recognized" or enforce the filter.
3. **Phase 3 article disclosure** (MAJOR-1 + appendix): Explicitly state that Phase 2 consumed the Phase 1.5 ledger (with main-thread asset backfill). The appendix Variant A limitations section is otherwise complete and sufficient for honest reporting.
4. **Spot-check generic-key matches** (MAJOR-2): Before Phase 3 write-up, filter `dm_ledger.json` rows where the dm_stat was matched via `"t"` or `"stat"` key (not a DM-specific key name) and audit a sample of 10–20 for plausibility.
5. **No changes required to Phase 2 MCS results** — `k1259_mcs_results.json` is correct given the Phase 1.5 ledger input and seed=42.

---

## Infrastructure blocker reference

- Same Codex blocker as K1258 review: `~/.codex/config.toml` `model = "gpt-5.5"` unavailable.
- This review satisfies the `.claude/rules/experiments.md` fallback gate: "code-reviewer subagent fallback... Bar 不變：CONDITIONAL PASS 以上才寫 knowledge.json."
- K1259 verdict: **PASS-with-caveats** — above the CONDITIONAL PASS bar.
- Reviewer source to record in knowledge.json: `code-reviewer subagent fallback (claude-sonnet-4-6, 2026-04-28)`.
