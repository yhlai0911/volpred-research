# K1704 primary pre-run delta review

Work read-only. Review the current frozen HEAD after the prior primary verdict in
`experiments/k1704/pre_run_review.md` returned FAIL. Inspect:

- `experiments/k1704/K1704.py`
- `experiments/k1704/README.md`
- `experiments/k1704/test_K1704.py`

Do not edit files, trust the old untracked cache/results, or run the full experiment.

Verify every prior blocker/high finding is resolved:

1. One fixed cross-target OOS ledger is used by all six targets and three models;
   forecast gaps fail closed instead of shrinking samples; dates and SHA-256 are recorded.
2. Cache reuse re-enumerates the source directory and hashes every current raw source file,
   failing on missing/replaced/mutated bytes.
3. README contains no scientific result before rerun/certification.
4. K1704 regression tests cover session endpoints, PIT invariance, HAR/GJR origin alignment,
   common ledger/MCS lengths, and raw mutation failure.
5. DM is accurately labelled canonical Newey-West HAC, not HLN.
6. Consensus direct self-inclusion is removed with leave-one-proxy-out residual centres and
   correlated 1/5/10-minute RV errors remain explicitly limited.
7. Literature DOI and prior-K references are correct (`Liu et al. 2015` DOI ends `.008`;
   target-native warning is K1057, not K777).

Also check for regressions introduced by the fixes, especially lookahead, mask alignment,
hash ordering, or impossible cache requirements. Return exactly one formal verdict:
`PASS`, `CONDITIONAL_PASS`, or `FAIL`, with severity and file/line references. PASS only
authorizes a fresh rerun; it does not validate results.
