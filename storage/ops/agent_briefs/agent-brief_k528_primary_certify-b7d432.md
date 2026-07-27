# K528 primary-path Codex certification (authoritative merge gate)

**Model**: claude-opus-4-8 / high (per model_router). Codex does the review judgement.

## Why this job exists
K528 (NFP official-release-date event study on SPY vol: does restricting the event
group to the *correct* official NFP dates flip the headline significance?) has been
through 6+ review rounds. Fallback reviewers validated blocks B1–B4 as PASS, and
round-7 gate hardening is DONE (structural nearest-governor release-misbinding gate
replacing a fragile 5-phrase blocklist; 15 pytest pass, evasion suite
`TestReleaseMisbindingGateIsStructural`). **The ONLY unclosed gate is the primary-path
Codex certification** — per `.claude/rules/experiments.md`, fallback reviewer PASS ≠
Codex PASS, so the worktree branch `k528-nfp-official-dates` (HEAD `b2634ed41`) MUST NOT
merge until Codex independently certifies the current bytes. No prior review_verdict
targets HEAD b2634ed41 (latest verdicts v2/v6 were FAIL at older commits).

## Saga defect classes Codex previously caught (must be re-checked as CLOSED)
1. **Wrong official dates** (v2): `event_dates.py` accessor used `max()` over multiple
   same-month FRED release-id-50 entries, picking off-cycle releases as NFP for 6 dates.
2. **Contaminated corrections** (v2): with *correct* dates the core sig→NS flip did NOT
   hold (1.1779x, p~0.0249 still significant); the 18/237 article corrections were
   claimed on contaminated dates. Verify the CURRENT headline claim + any article
   corrections are consistent with the corrected official dates and the current results.
3. **Fail-closed completeness bypass** (v6): completeness gate could be bypassed by
   putting a tail month into KNOWN_MISSING_MONTHS + REVIEWED_MULTI_ENTRY_MONTHS so the
   raw→selected check skipped it while the counter-check only scanned the selected span.
   Verify this is now genuinely fail-closed / not evadable.

## Your task (this is the PRIMARY full certification, not a bounded diff)
Work in this worktree cwd. Use `codex exec` (codex-cli, ChatGPT auth) for the review.

1. Have Codex read the FROZEN current claim surface at HEAD b2634ed41:
   - `experiments/k528/k528_nfp_event_study.py` (sha256 `917133ce7bf28b7c97c6d45bb479428fe06696cddf131a36745d0eb419a72129`)
   - `experiments/k528/k528_nfp_event_study_results.json` (`5833bf2acec6f0dd2a510dfe7a30dd04c91ddf60ebb08b15c3150d43a519dd34`)
   - `experiments/k528/k528_nfp_official_dates_results.json` (`65c1e2339f6ef4894e0fa0d4ffec6d472ed519d9b09c346d722814631fe1e953`)
   - `experiments/k528/README.md` (`30c8e4304347a285016ee42a2093a75847488fd7970f578e52d05dfe908fc2d3`)
   - `experiments/k528/build_article_correction.py` (`5c6b6c814c6051aae984eabf84866eec4a45b525c7b9fb57a36cfbff30abe886`)
   - `tests/test_nfp_official_release_dates.py` (`e05d1bd047cc37f068314d33cf53447d5aea4dff97a85a6459a16914b24a5953`)
2. Codex must independently rule on the SCIENCE + the three closed-defect classes above:
   correct official NFP dates (no off-cycle contamination), headline claim matches the
   current results with correct dates, no lookahead / no result contamination, the
   completeness / fail-closed gates are structural (not evadable), and any article
   corrections are consistent with the certified numbers. Do NOT rubber-stamp the
   fallback B1–B4 — re-derive the key numbers from the frozen results JSONs.
3. Save the full Codex review log to `experiments/k528/codex_review_primary_certify.md`.
4. Fill the verdict skeleton:
   `uv run python scripts/experiment_gates.py verdict-template --path experiments/k528 --out experiments/k528/review_verdict.json`
   then write: verdict=PASS or FAIL, reviewer=<Codex model/effort + session>, reviewed_at,
   reviewed_commit=`b2634ed41` (the CURRENT worktree HEAD — abort/FAIL if HEAD moved),
   review_artifact=`experiments/k528/codex_review_primary_certify.md`, and `reviewed_sha256`
   covering the full claim surface at this commit with the exact current hashes above.
   Commit the verdict + review log to this worktree branch (`git -C . commit`).
5. If Codex finds ANY blocking defect → verdict=FAIL, list defects precisely; the main
   thread will open round-8. Do NOT merge on FAIL. Do NOT hand-edit a PASS.

## Result artifact
`experiments/k528/review_verdict.json` at reviewed_commit=b2634ed41, verdict=PASS with
reviewed_sha256 matching the current claim surface (or an explicit FAIL with defects).
