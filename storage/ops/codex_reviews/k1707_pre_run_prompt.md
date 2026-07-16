# K1707 pre-run source review

Read only `experiments/k1707/README.md` and `experiments/k1707/K1707.py`. Do not edit files and do not run the 401 MB analysis.

Return `VERDICT: PASS` or `VERDICT: FAIL` on the first line. Check:

1. The author file is explicitly randomized/noised pseudo-data, so the fixed support gate (`dates>=80`, `VIX>=30 days>=30`, symbols>=10, no weekend pseudo dates) must fail closed before confirmatory inference.
2. VIX is point-in-time lagged with explicit `.shift(1)`; same-day VIX cannot enter.
3. Raw datafile MD5 is pinned; required columns, dates and auction indicator fail loudly; no silent fallback.
4. Aggregate statistics and auction-benefit signs are correct; altered pseudo timestamps are used only for support audit, with no VIX slope or p-value.
5. Result and manifest writes are atomic/validated, randomness seed is 42, and reruns are byte-oriented rather than timestamp-dependent.
6. If the pinned data unexpectedly pass support, code must fail rather than claim an unimplemented interaction.

List any blocking defect with file/line and a minimal fix. Separate non-blocking limitations. The pre-run PASS only authorizes executing the frozen adequacy audit; it is not a scientific PASS verdict.
