# K1623 round-4 primary-path review

**Verdict: FAIL**

- Reviewer: Codex CLI 0.144.6 / gpt-5.6-sol / xhigh / read-only.
- Frozen commit: `d1316cb5e79a006b3f4d8f3b78b9bc5c03ff6345`.
- The bounded review reached the explicit conclusion `FAIL` before its 420-second watchdog ended the process; no reviewer-authored final message file was emitted. This record preserves the blocking evidence printed during the read-only run without representing it as a completed PASS artifact.

## Blocking defects

1. `README.md:323-331` still described Arm B as a location-only oracle and A−B as isolating the cost of finding break locations. Arm A selects both break count and locations, while Arm B fixes the whole partition.
2. `README.md:493` still listed a “dominant factor” in the provenance table after the per-asset classification had been withdrawn as unidentified at 500 reps.
3. The `review_verdict.json` committed at the frozen SHA was the older unfilled template, so its hashes did not certify the reviewed rev4 bytes. A fresh template must be committed before the next frozen review.

## Checks that did pass

- Recomputed `sd_A / SE` range: 1.2137939–1.3315962.
- Recomputed f1/f2/f3 products matched the total exactly for all five assets.
- Current Arm-C result summary had no per-asset dominant classification and set `dominance_identified_at_500_reps=false`.
