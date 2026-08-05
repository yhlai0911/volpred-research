# PRG v8 — Reproducibility preflight and source binding

**Round**: v8, 2026-08-05
**Repo HEAD at round start**: `431de4564`
**Gate reference**: `.claude/skills/paper-update/references/reproduce-gate-rules.md`

## 1. Candidate manifest (SHA-256, full)

| File | Bytes | SHA-256 |
|---|---|---|
| `paper/prg-periodic-garch/main.tex` (canonical) | 30,408 | `8852326a7b77eb3455038f558c823dcefa311a282697f82ff2e5d798813c86ed` |
| `paper/prg-periodic-garch/main.pdf` (untracked) | 68,804 | `8c2d2ddc673df0f7b153365f23095fc846e629ef620040a68e63cd65af95f017` |
| `paper/prg-periodic-garch/canonical.json` | 286 | `7cfb5926372cc641cabcf25c30f5272556242af61e4f4a321f5dce3372967c67` |
| `paper/prg-periodic-garch/reproduce.py` | 9,518 | `2addc02275abe935123ccb43060f13087ec2347acab0af5347fd6c5258147d25` |
| `paper/prg-periodic-garch/reproduce_report.json` | 5,308 | `b52acc9b9a958abda62bd64c36db11adc11f79fa3f0a5e59cce67149526d39e2` |
| `experiments/k1699/k1699_results.json` | 29,380 | `b258c40489bccc1146cf31b1a8bd40c857541f343253259db62102816de52c3a` |
| `experiments/K1710/K1710_results.json` | 29,850 | `7e5f4b5c38372b0d5e2d745f95be05b06a91a651f8974a822dce6457380c6da9` |
| `experiments/k1699/reproduce_spec.json` | 2,740 | `77b560d7e6d9d07cadbfc89a7b5e14877a326757b531e431314af51a6867c234` |
| `experiments/K1710/reproduce_spec.json` | 3,106 | `9eaeccf154fea29562fd9a80a4945f86ef957b6b570b6fa2044a7582a0c99383` |
| `src/volpred/stats/model_evaluation.py` (shared) | 20,257 | `c33b4617cf92e92696d2cb15d4eafa39316e1422332f7ef154cce7195a8493ca` |

**Candidate identity**: `canonical.json` declares `main.tex` (declared 2026-08-04 by the
three-strike refactor "the manuscript is declared, not inferred"). `main_pre_v3_m2.tex` and
`main_pre_v7.tex` are pre-rewrite snapshots and were **not** reviewed.

**PDF↔TeX agreement**: `main.pdf` is untracked, so git cannot attest it. Page 1 was read
directly and carries the current post-fix abstract verbatim — including the "on the pinned
vintage" clause introduced by `e2ffd8d90` — so the PDF corresponds to the declared canonical
`.tex`. Its mtime (2026-07-19 14:04) sits one minute before the last manuscript commit
`c23e36b5c` (14:05:12), consistent with compile-then-commit.

## 2. Data snapshot pinning — PASS

Both experiments read pinned snapshot CSVs (vintage 2026-07-12); no live fetch. All seven
k1699 data snapshots are hash-recorded in `reproduce_spec.json` and **all matched** this round
(`missing=[]`, and no data path appears in the mismatch list).

| Market | OOS obs | OOS period | Source |
|---|---|---|---|
| SPY | 1,823 | 2019-01 – 2026-04 | OHLC pinned |
| QQQ | 1,981 | 2018-05 – 2026-04 | OHLC pinned |
| GLD | 1,613 | 2019-10 – 2026-04 | OHLC pinned |
| EEM | 1,734 | 2019-05 – 2026-04 | OHLC pinned |
| 0050.TW | 1,251 | 2021-01 – 2026-04 | OHLC pinned |
| TAIFEX TX | 843 | 2022-07 – 2025-12 | Tick, 5-min RV |

## 3. Experiment reproducibility gate — UNVERIFIED (not FAIL, not PASS)

```
$ uv run python scripts/reproduce_check.py run --experiment k1699 --timeout 1200
[reproduce] k1699: unverified (INPUT_HASH_MISMATCH)

$ uv run python scripts/reproduce_check.py run --experiment K1710 --timeout 1200
[reproduce] K1710: unverified (INPUT_HASH_MISMATCH)
```

Receipts: `experiments/k1699/reproduce_report.json` (generated 2026-08-05T08:55:36Z) and
`experiments/K1710/reproduce_report.json` (2026-08-05T08:57:13Z), both at repo head
`b7d9753515a8f3a056ebad7a08cd3c4ae8a483df`.

```json
{"status": "unverified", "reason_code": "INPUT_HASH_MISMATCH", "severity": "warn",
 "reproducible": null,
 "summary": "missing=[]; hash_mismatch=['src/volpred/stats/model_evaluation.py']"}
```

The gate compares **whole-file** hashes and, on mismatch, declines to execute. So neither
experiment was re-run and neither produced a `reproducible: true` receipt.

### Why the mismatch is not substantive — proved, not assumed

`git log -- src/volpred/stats/model_evaluation.py` shows exactly one commit after the spec was
pinned: `9f868e41f` (2026-07-15, "finalize K841 HAC methodology repair"). Its diff against that
file is **+3 lines, 0 deletions, two hunks, both inside `strategy_dm_test`** — a new
`variance_risk` loss branch.

Function-level SHA-256 (first 16 hex) of `9f868e41f^` vs HEAD, extracted by AST:

```
dm_test           pre=4aa7d4d0fcdf7d3e head=4aa7d4d0fcdf7d3e  IDENTICAL
qlike_pointwise   pre=330ccbc6229a37c8 head=330ccbc6229a37c8  IDENTICAL
strategy_dm_test  pre=7e10591368fcb9df head=c1077cacf9b447ad  CHANGED
```

The spec's recorded hash for the file (`29c6f80d1d39…`) equals the `9f868e41f^` version,
confirming the comparison baseline. Both experiments import exactly `dm_test` and
`qlike_pointwise` — `k1699.py:75`, `K1710.py:88` — and call no other symbol from the module.
`strategy_dm_test` is not referenced by either.

**Conclusion**: the computational surface behind every number in the manuscript is
byte-identical to the pinned specification. What is *not* established is end-to-end
re-execution from snapshots, because the gate refused to run it. The manuscript's L118 claim
("every number … reproduces bit-identically from the archived snapshots") therefore outruns
the current evidence — recorded as MAJOR-4 in `latex_review.md`.

**Platform defect referred out**: whole-file hashing of a shared module means any unrelated
edit silently un-certifies every dependent experiment, and the gate then refuses to run the
check that would resolve it. Referred to the platform engineering department.

## 4. Paper-level reproduce gate — PASS (28/28 GREEN)

`paper/prg-periodic-garch/reproduce_report.json`, generated 2026-08-05T08:47:34Z:

```json
{"alert_level": "green", "match_rate": 100.0, "n_checks": 28, "n_matched": 28,
 "n_json_invariants": 7, "n_tex_bindings": 21, "overall_match_rate_pct": 100.0,
 "tex": "main.tex",
 "sources": ["experiments/k1699/k1699_results.json", "experiments/K1710/K1710_results.json"]}
```

Meets the `.claude/rules/paper-workflow.md` gate (`match_rate ≥ 95%`, `alert_level = green`).
This certifies **manuscript↔pinned-JSON binding**, not snapshot→JSON re-execution — a
distinction MAJOR-4 turns on.

## 5. Source binding — independently re-derived, all match

Every Table 2 cell was re-derived this round directly from the JSONs rather than trusting the
gate's aggregate. JSON orientation is negative-favours-PRG; the manuscript flips the sign.

| Market | Mixed (paper / JSON) | Close (paper / JSON) | Open (paper / JSON) | ON share (paper / JSON) |
|---|---|---|---|---|
| SPY | +5.83 / −5.8265 | −0.74 / +0.7414 | +3.56 / −3.5567 | 44.8 / 0.44807 |
| QQQ | +4.78 / −4.7812 | −2.28 / +2.2819 | +1.56 / −1.5632 | 38.5 / 0.38547 |
| GLD | +6.11 / −6.1058 | +0.44 / −0.4362 | +3.64 / −3.6433 | 60.9 / 0.60942 |
| EEM | +6.40 / −6.4048 | +0.54 / −0.5410 | +10.14 / −10.1373 | 70.7 / 0.70652 |
| 0050.TW | +5.19 / −5.1943 | +0.32 / −0.3175 | +3.67 / −3.6703 | 63.5 / 0.63488 |
| TAIFEX | +4.33 / −4.3283 | +0.49 / −0.4916 | +5.50 / −5.5035 | 68.9 / 0.68898 |

Sources: close column `k1699_results.json .markets.<M>.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat`;
mixed `K1710_results.json .markets.<M>.dm_tests.mixed_anchor_main.t_stat`; open
`.dm_tests.open_panel_main.t_stat`; ON share `.markets.<M>.oos_overnight_variance_share`.

p-values also checked: QQQ close 0.02260 → "0.02"; SPY open 0.000385 → "<0.001"; QQQ open
0.11816 → "0.12"; TAIFEX open 4.944e-8 → "<0.001"; EEM open recorded as 0.0 and reported as
"<0.001" (honest downward statement of an underflowed value).

Lagged robustness cells (`PRG_tminus1_lag_vs_GJR`) re-derived as well — this is where MAJOR-2
came from:

| Market | lag t (JSON) | lag t (paper convention) | lag p | Harvey |
|---|---|---|---|---|
| SPY | +1.2524 | −1.25 | 0.2106 | false |
| **QQQ** | **+2.9523** | **−2.95** | **0.00319** | false |
| GLD | −0.1822 | +0.18 | 0.8554 | false |
| EEM | −0.0035 | +0.00 | 0.9972 | false |
| 0050.TW | +0.2798 | −0.28 | 0.7796 | false |
| TAIFEX | −0.2291 | +0.23 | 0.8189 | false |

0/6 Harvey holds in both variants, as the manuscript states. The QQQ lagged cell at |t| = 2.95
is what falsifies the manuscript's "nothing approaches the conservative threshold" wording.

## 6. Preflight verdict

**CONDITIONAL PASS** — the round proceeds to reviewers, with one unresolved item carried into
the findings.

- Data pinning: PASS
- Source binding: PASS (independently re-derived, 24 DM cells + 6 shares + 5 p-values)
- Paper-level gate: PASS (28/28 GREEN)
- Experiment-level gate: **UNVERIFIED** — non-substantive cause proved, but no end-to-end
  receipt exists. Not an abort condition under `paper-review-cycle` §2 (no experiment failed,
  nothing is missing, the candidate cites the same snapshot), and not a basis for claiming
  reproducibility either.
