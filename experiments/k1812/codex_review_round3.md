VERDICT: PASS

## Blocking defects

None.

## Non-blocking observations

- `review_verdict.json` is intentionally absent at review time. Running
  `.venv/bin/pytest experiments/k1812/test_k1812.py -q` produced exactly
  `21 passed, 1 failed`; the only failure was
  `test_readme_does_not_claim_unrecorded_review_rounds` at
  `test_k1812.py:436-445`, because that file is the test's explicit
  precondition. No other test failed.
- The suite also emitted the repository's CI-parity warning because
  `experiments/k1812/` is still untracked in this worktree. This did not add a
  second pytest failure. The four experiment-integrity gates independently
  reported PASS.

## Evidence

### Round-2 blockers

- The unreconcilable `FP 全 CRSP 的 ~0.78` benchmark is gone. An exact search
  of the current `README.md` for `0.78` has no match. The baseline row now says
  only that performance is qualitatively below FP and explicitly qualifies:
  `"本實驗未重建 FP 原文 universe，故不在此引用其數值做量化對比"`
  (`README.md:138`).
- Section 8 no longer reports a past successful run. Its heading calls the
  checks `"合併前必須成立的條件"` and says they are not a retrospective claim
  (`README.md:247`). The pytest item says `"必須全數通過"` rather than
  `"全數通過"` (`README.md:249`), and explicitly identifies
  `review_verdict.json` as a precondition whose absence makes the one test red
  by design (`README.md:250-252`).

### Input provenance and byte identity

- `load_data()` reads existing per-ticker caches with `pd.read_csv()` at
  `k1812.py:147-153`, constructs the complete requested set at
  `k1812.py:181-183`, and writes the three assembled convenience CSVs at
  `k1812.py:200-203`.
- `reproduce_spec.json:12-423` lists 82 inputs. I independently compared that
  list with every file under `data/tickers/*.csv`: the path sets are equal
  (82/82), and recomputed SHA-256 and byte size match for all 82 files.
  Neither `stock_prices.csv`, `market_price.csv`, nor `riskfree_irx.csv`
  appears in `inputs`.
- The three assembled CSVs appear in `outputs` at
  `reproduce_spec.json:424-431`. The script passes the ticker-cache list as
  `inputs` and the assembled CSVs as `outputs` at `k1812.py:1269-1289`.
- The current on-disk `k1812.py` is 63,817 bytes with SHA-256
  `bf615c2fab44dc166324e1ae2208f66a6cb12da33b580d7155139ae58cee1102`.
  This exactly matches `reproduce_spec.json:8-9` and
  `k1812_results.json:961-962`.
- The re-run did not change the headline scientific values recorded in the
  round-2 review (`codex_review_round2.md:69-74,92-100`): low/high Sharpe
  remains `0.3283485940 / -0.3573397024`, the difference remains
  `0.6856882964`, primary p remains `0.1137886211`, and regression p remains
  `0.1114181617`. The changed identity is the entrypoint provenance, not the
  reported scientific result.

### Independent README-to-results reconciliation

- Baseline (`README.md:138`) matches `k1812_results.json:236-243`:
  mean `-0.0010830847` = `-0.11%/month`, annualized Sharpe `-0.073846`,
  HAC t `-0.370588`, p `0.710944`, and n `257`.
- Main split (`README.md:139`) matches `k1812_results.json:248-287`:
  n `125/132`, Sharpes `0.328349/-0.357340`, difference `0.685688`,
  block length `7`, `37` blocks, `10,000` repetitions, seed `42`, and
  two-sided p `0.113789`. The stationary-bootstrap CI
  `[-0.135364, 1.462471]` matches `k1812_results.json:344-356`; regression
  beta `0.0099406`, t `1.59185`, and p `0.111418` match
  `k1812_results.json:428-435`.
- Robustness values (`README.md:140-142`) match the artifact: circular-shift
  p `0.105058` (`k1812_results.json:289-302`); block-grid p values
  `0.128287/0.108989/0.114189/0.118288`
  (`k1812_results.json:304-332`); i.i.d. comparison p `0.115288`
  (`k1812_results.json:358-371`); tercile Sharpes
  `0.260130/0.003158/-0.374749` (`k1812_results.json:438-453`); and
  expanding-median difference/p values `0.626725`, `0.163884`,
  `0.105691`, and `0.157784` (`k1812_results.json:455-519`).
- Serial-dependence numbers in `README.md:89-106` match
  `k1812_results.json:390-426`: observed label ACF(1) `0.326133`, observed
  mean/max run `2.954/30`, block-null `0.280695/2.772`, shift-null
  `0.328968/2.966`, and i.i.d.-null `-0.004528/1.992`.
- Leverage diagnostics in `README.md:171-175` match
  `k1812_results.json:221-234`: raw beta-L minimum `-0.0736595`, one
  non-positive month, maximum unshrunk leverage `11,367.23`, shrunk beta-L
  range `[0.355804, 0.852393]`, maximum shrunk leverage `2.81053`, and
  maximum monthly absolute BAB `17.8494%`.

### Conclusion and methodology

- The conclusion is appropriately bounded. It says the direction is
  consistent with JFE 2025 (`README.md:146-147`), but the primary
  block-permutation p is `0.114`, the CI covers zero, and the null cannot be
  rejected at 5% (`README.md:148-151`). It explicitly does not claim to
  reproduce JFE 2025 significance (`README.md:159-161`).
- No methodology regression was found. Beta windows require the full 12
  months and use only `(window_start, formation_month_end]`
  (`k1812.py:248-279`). Holding month is exactly formation month + 1;
  membership and weights are formation-only; missing holding returns fail
  loudly (`k1812.py:362-389`). Formation-month risk-free data also fail loudly
  if missing (`k1812.py:399-403`).
- The completed-month gate remains at `k1812.py:974-990`; results record
  `last_complete_month = 2026-06-30`, 257 BAB months, and final BAB month
  `2026-06-30` (`k1812_results.json:202-212`).
- Both the main and expanding-median signals retain explicit `.shift(1)`
  alignment (`k1812.py:995-1004,1095-1104`). The fail-loud cross-check remains
  at `k1812.py:1006-1028`, with 257 checked months and zero mismatches in
  `k1812_results.json:214-219`. The unconditional baseline and conditional
  split both consume the same `bab_ret` series (`k1812.py:1030-1040`).

### Review history

- `README.md:217-227` truthfully records round-1 FAIL, round-2 FAIL, round-2's
  acceptance of defect (B), its two remaining blockers, and the provenance
  observation. These statements agree with
  `codex_review_round2.md:1-28,30-120`.
- The README defers the current conclusion to the subsequently generated
  `review_verdict.json` (`README.md:228-229,256-257`); it does not claim a
  round-3 outcome before this review is recorded.
