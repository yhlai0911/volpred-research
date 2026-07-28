VERDICT: FAIL

## Blocking defects

1. `experiments/k1812/README.md:138` still puts the numerical benchmark
   `FP 全 CRSP 的 ~0.78` in the headline baseline-results row, but that number
   does not occur anywhere in `experiments/k1812/k1812_results.json` (an exact
   search for `0.78` returns no match), nor is there a literature-benchmark
   field from which it can be reconstructed. This directly fails round-2
   requirement (C): every key README number must be programmatically
   reconcilable with the current results artifact. It must either be removed
   from the results table or stored with explicit benchmark provenance in the
   artifact.

2. `experiments/k1812/README.md:239` states
   `pytest experiments/k1812/test_k1812.py -q → 全數通過`, but that statement
   is false for the bytes under review. Running the stated test suite produced
   `21 passed, 1 failed`; the failing assertion is
   `test_readme_does_not_claim_unrecorded_review_rounds` at
   `experiments/k1812/test_k1812.py:436-445`, because the README claims
   round-1/round-2 activity while
   `experiments/k1812/review_verdict.json` does not exist. The README also
   directs readers to that absent file at `README.md:218-219` and
   `README.md:242-243`. Deferring the round-2 verdict is correct in principle,
   but claiming that the gate already passes and that the referenced audit
   artifact exists is not truthful for the actual on-disk state. This is the
   same review-narrative/artifact-verifiability class as defect (C), so (C) is
   not fully landed.

## Non-blocking observations

- Defect (B) itself is correctly fixed. The primary series is constructed from
  calendar-ordered, interleaved observations:
  `joint = concat(...).dropna().sort_index()` at
  `experiments/k1812/k1812.py:1036-1038`, followed by
  `r_ord = joint["bab"].values` and
  `lab_ord = joint["low"].astype(int).values` at
  `experiments/k1812/k1812.py:1058-1063`. The split `y_low`/`y_high` arrays are
  used only for the explicitly demoted i.i.d. comparisons at
  `experiments/k1812/k1812.py:1078-1079`.

- `_circular_block_permute` at
  `experiments/k1812/k1812.py:571-582` performs a circular rotation, partitions
  the complete label sequence into contiguous blocks, and permutes whole
  blocks. Independent checks over 1,000 draws found sequence length and the
  125/132 label multiset preserved in every draw. The method preserves most,
  not literally all, regime-run structure: block boundaries may split or join
  runs. The artifact reports that honestly—observed label ACF(1)
  `0.3261334748` and mean run `2.95402299` become block-null
  `0.2806950203` and `2.77209015` at
  `experiments/k1812/k1812_results.json:395-416`. Thus the method is a
  time-structure-preserving block approximation, not an exact preservation of
  every run. README wording `區塊內完整保留` at `README.md:93-95` is accurate;
  broader wording should retain that qualification.

- The block length is rule-selected rather than p-selected:
  `max(ceil(n^(1/3)), ceil(mean regime run length))` at
  `experiments/k1812/k1812.py:545-568`. It gives `b=7`, while the separately
  reported sensitivity grid `{3,6,12,24}` is generated at
  `experiments/k1812/k1812.py:1062-1075`. Results p-values are respectively
  `0.128287`, `0.108989`, `0.114189`, and `0.118288`
  (`k1812_results.json:306-331`).

- The primary Monte Carlo test leaves returns fixed and permutes only the
  blockwise label sequence (`k1812.py:603-614`). Its two-sided p-value is
  exactly `(#{|null| >= |observed|}+1)/(B+1)` at
  `k1812.py:585-587`. Defaults are seed `42` and 10,000 repetitions
  (`k1812.py:590-600`). An independent rerun from
  `data/bab_regime_joint.json` reproduced:
  `diff=0.6856882958`, `p=0.1137886211`, `reps=10000`, `seed=42`, identically
  on two calls. The stored values are
  `diff=0.6856882964`, `p=0.1137886211` at
  `k1812_results.json:278-287`; the negligible difference in the effect
  estimate comes from the diagnostic JSON's decimal serialization.

- The exhaustive circular-shift comparison enumerates all non-identity shifts
  `k=1..n-1` (`k1812.py:636-662`) and stores `256` shifts with
  `p=0.1050583658`. The stationary bootstrap resamples aligned
  `(return,label)` pairs in circular geometric-length blocks
  (`k1812.py:665-711`) and is correctly labelled an effect-size CI rather than
  a null-imposed significance test. Its stored 95% CI is
  `[-0.1353642721, 1.4624714153]`
  (`k1812_results.json:345-356`).

- The i.i.d. permutation is visibly demoted. The results name the primary test
  `sharpe_difference_block_permutation`
  (`k1812_results.json:268`) and label the i.i.d. test
  `COMPARISON ONLY` (`k1812_results.json:359-371`). README lines 80-82,
  139-140, and 184-190 use the block p-value as the judgment and present
  i.i.d. `p=0.115` only as a comparison.

- The headline K1812 estimates otherwise reconcile with the results artifact:
  annualized Sharpe `0.3283485940` versus `-0.3573397024`, difference
  `0.6856882964`, primary p `0.1137886211`, and regression p
  `0.1114181617`. README lines 146-161 explicitly say the result is not
  significant at 5%, the CI covers zero, and JFE 2025 significance was not
  replicated. README lines 152-155 also correctly treat `0.115 → 0.114` as a
  measured outcome, explaining it with BAB return ACF(1) `0.070` and nearly
  identical null SDs (`0.438` versus `0.439`), rather than asserting that the
  original i.i.d. method was valid.

- No lookahead/methodology regression was found. Beta windows end at the
  formation month (`k1812.py:251-279`); the holding month is exactly the next
  month and the universe is formation-only, with missing holding returns
  failing loudly (`k1812.py:362-405`). The completed-month gate remains at
  `k1812.py:974-990`. Both full-sample and expanding-median regime signals use
  `.shift(1)` (`k1812.py:995-1004`, `1095-1104`), and the fail-loud alignment
  check is at `k1812.py:1006-1028`. Results record 257 checked months and zero
  mismatches (`k1812_results.json:217-218`). The unconditional baseline and
  conditional analysis both consume the same `bab_ret` series
  (`k1812.py:1030-1038`).

- Entrypoint provenance is internally consistent: the on-disk script,
  `reproduce_spec.json:8-9`, and `k1812_results.json:961-962` all report SHA-256
  `210c81429f73b0c2a4c56be0c9911a6b6ada50d9bc7cb10a8dc7384ce68224ba`
  and 63,300 bytes. Separately, the reproduce spec hashes only the three
  assembled CSVs even though `load_data()` reads `data/tickers/*.csv` and calls
  the assembled CSVs non-source convenience files (`k1812.py:171-204`,
  `1276-1280`). That input-provenance contract should be corrected, but it is
  distinct from the already-fixed entrypoint drift and from defects (B)/(C),
  so it is recorded here without changing this round's verdict.
