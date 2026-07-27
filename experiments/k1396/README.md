# K1396 — superseded historical daily-r² diagnostic

**Status:** `SUPERSEDED_HISTORICAL_DIAGNOSTIC_ONLY`  
**Public claim verdict:** `FAIL_PUBLIC_CLAIM`  
**Correction date:** 2026-07-16  
**Superseded by:** K1379 for the corrected Paper 9 daily-r² protocol

## Executive correction

K1396 does not supply the canonical HAR-RV benchmark that its original title
claimed. It used close-to-close daily squared returns (`r_t²`) as both the
evaluation target and the input to daily, weekly, and monthly HAR-style
features. Corsi's HAR-RV model is defined on realized-volatility measures,
normally constructed from intraday observations. Daily `r_t²` is a noisy
volatility proxy; it does not become intraday realized variance merely because
the loss is proxy-robust QLIKE.

The K1396 A4f path is also an approximation. Parameters were refit in 63-day
blocks, but every OOS forecast used `tau_t × omega/(1-alpha-gamma/2-beta)`.
The short-run `g_t` state was reset to its unconditional steady state on every
forecast date instead of being recursively carried forward. The protocol
therefore did not match K988 exactly.

The historical failure to reject equal predictive accuracy did not establish
equivalence or non-inferiority. K1396 specified no margin, reversed null,
confidence-interval inversion, or TOST procedure. In addition,
HAR-style daily-r²-VIX nests HAR-style daily-r², so their raw QLIKE DM statistic
is retained only as a historical diagnostic and cannot support an incremental
VIX conclusion.

## What actually ran

| Stored label | Accurate label | Historical implementation |
|---|---|---|
| `HAR` | HAR-style daily-r² NNLS | lagged daily `r²`, 5-day mean, 22-day mean |
| `HAR_VIX` | HAR-style daily-r²-VIX NNLS | preceding features plus lagged `VIX²/252` |
| `A4f` | blockwise-fitted steady-state-g A4f approximation | `tau_t × E[g]` on every OOS date |

- Input path recorded by the run:
  `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`.
- Data start: 2005-01-01.
- OOS start: 2019-01-01.
- Stored OOS observations: 1,866.
- Rolling estimation window: 2,000 observations; refit every 63 OOS days.
- Seed: 42.
- Target and loss: daily `r²` with actual-first Patton QLIKE.
- Timing: HAR-style regressors and VIX are lagged; the lookahead audit passes.
- Inference: a local Bartlett/Newey-West-style raw-loss DM diagnostic with a
  lag cap of 12 and an `|t| > 3` reporting screen. It is not the canonical
  repository helper and contains no Harvey-Leybourne-Newbold correction.

The run did not store an input SHA, the data endpoint, or a duplicate-date
audit. The file currently found at that path has since changed and contains
duplicate dates. Consequently the 1,866-observation result is not independently
reproducible from the committed input. The numbers are preserved as an audit
trail; this provenance gap is not evidence that they were fabricated.

**Snapshot-dedup clean rerun (2026-07-27)**: the loader was fixed to drop duplicate
trading days (`sort_index()` then `~index.duplicated(keep="last")`) and the experiment
was rerun on the clean+extended canonical snapshot, written to a **separate**
[k1396_legacy_rerun_results.json](k1396_legacy_rerun_results.json) (the frozen
`k1396_results.json` above is untouched). Clean values: n_oos=1900 (no duplicate dates;
the old 1,866 count included dups), HAR_VIX_vs_HAR DM t=−2.522 p=0.0117 (contaminated
was p=0.00843 — direction consistent, still <0.05, **no verdict flip**), HAR_vs_A4f
t=+0.846 p=0.397, HAR_VIX_vs_A4f t=−0.839 p=0.402. Severity LOW: this experiment is
superseded by K1379, so no feed/paper/knowledge change is required.

## Frozen historical values

The original [k1396_results.json](k1396_results.json) is preserved byte for
byte with SHA-256
`c2816e6e0d2a2f7b18d3b78421e342ff9606c8c39fd5fab9064574042c7c1a10`.

| Historical approximation | Mean QLIKE | Raw HAC-DM reading |
|---|---:|---:|
| HAR-style daily-r² | 1.561152 | vs A4f approximation: `t=+0.86597` |
| HAR-style daily-r²-VIX | 1.522854 | vs A4f approximation: `t=-0.87683` |
| steady-state-g A4f approximation | 1.538951 | — |
| daily-r²-VIX vs daily-r² | — | nested diagnostic: `t=-2.60404` |

These values may only be cited as a withdrawn 2026-05 historical
approximation. They do not support canonical HAR-RV, A4f parity,
non-inferiority, three-model equivalence, or cross-proxy consistency.

## Corrected evidence from K1379

K1379 repaired the daily-r² comparison with a hash-pinned unique-date snapshot,
actual-first QLIKE, consistent A4f fit/OOS recursion, and the canonical
Bartlett-HAC DM helper. On 1,852 shared valid OOS dates from 2019-01-02 through
2026-05-18:

| Corrected comparison | Result |
|---|---:|
| A4f mean QLIKE | 1.399812 |
| HAR-style daily-r² mean QLIKE | 1.524461 |
| A4f QLIKE advantage | 8.177% |
| A4f vs HAR-style daily-r² DM | `t=-7.69855`, `p=2.22e-14` |

The negative K1379 statistic favors the first-named model, A4f. The result
survives the reported HAC lag grid. It overturns K1396's public “only a small
gap” story. K1379 still uses daily `r²`, so Paper 9's canonical intraday HAR-RV
benchmark remains unfulfilled rather than silently relabeled.

## Reproduction and artifacts

```bash
uv run python experiments/k1396/scope_repair.py
```

The command:

1. verifies the frozen K1396 result hash;
2. reads the certified K1379 result;
3. writes `k1396_scope_audit.json` atomically;
4. regenerates the correctly labelled legacy chart; and
5. renders a K1396-to-K1379 supersession chart.

`k1396.py` is retained to explain the legacy implementation. A rerun writes
`k1396_legacy_rerun_results.json`; it can no longer overwrite the frozen audit
artifact. No rerun may be promoted to a current result without a unique,
hash-pinned input, canonical recursion, canonical inference, lag sensitivity,
and a new byte-bound independent review.

## Files

- `k1396.py`: legacy implementation with corrected scope labels.
- `k1396_results.json`: immutable historical result.
- `scope_repair.py`: deterministic scope-audit and figure generator.
- `k1396_scope_audit.json`: machine-readable correction contract.
- `k1396_general_article_chart.png`: relabelled historical diagnostic.
- `k1396_scope_correction_chart.png`: K1396/K1379 supersession comparison.

## References

- Corsi, F. (2009), “A Simple Approximate Long-Memory Model of Realized
  Volatility,” *Journal of Financial Econometrics* 7(2), 174–196.
  DOI: `10.1093/jjfinec/nbp001`.
- Patton, A. J. (2011), “Volatility Forecast Comparison Using Imperfect
  Volatility Proxies,” *Journal of Econometrics* 160(1), 246–256.
  DOI: `10.1016/j.jeconom.2010.03.034`.
- Diebold, F. X. and Mariano, R. S. (1995), “Comparing Predictive Accuracy,”
  *Journal of Business & Economic Statistics* 13(3), 253–263.
  DOI: `10.1080/07350015.1995.10524599`.
- Schuirmann, D. J. (1987), “A Comparison of the Two One-Sided Tests Procedure
  and the Power Approach for Assessing the Equivalence of Average
  Bioavailability,” *Journal of Pharmacokinetics and Biopharmaceutics* 15(6),
  657–680. DOI: `10.1007/BF01068419`.
