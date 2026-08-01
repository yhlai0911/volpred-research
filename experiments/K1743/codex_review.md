# K1743 Codex primary-path review

- Reviewer: `codex/gpt-5.6-sol` (`ultra`)
- Review base: `32f8bc4d780275cf32a651f9e0b9951c8871f3ea` plus the byte-bound claim surface recorded in `review_verdict.json`
- Certification verdict: **PASS**
- Scientific verdict: **NULL**

## Scope and checks

I reviewed `K1743.py`, `README.md`, the regenerated `K1743_results.json`, and
`reproduce_spec.json`. I also reran the experiment and the focused regression
tests from the main-thread checkout.

The chronology is internally consistent for the stated common-date design:
Taipei-to-New-York uses the same-calendar Taiwan close only after Taipei has
closed, while New-York-to-Taipei uses the literal `signal.shift(1)`. Own-return
and premium-change controls are lagged, coefficients are fitted only through
2020-12-31, and the 2021-01-04 through 2026-07-31 window remains OOS. The
README and result artifact now explicitly state that exchange-specific
holidays can make a common-date target span more than one local session; no
intraday or information-share claim is made.

The first archived result was not certifiable: two impossible `TWD=X` ticks
(1.8015 and 3.67 TWD/USD) mechanically produced ADR premia near -94% and -88%.
The repaired runtime drops exactly those observations without imputation,
records their dates and values, and aborts if invalid FX exceeds 1% of the
common panel. The cleaned run contains 3,912 common-date observations and
1,305 OOS observations per direction.

The predeclared success rule is evaluated without overclaim. Taipei-to-New-York
worsens both MSE and QLIKE and has one-sided Clark--West p=0.4093.
New-York-to-Taipei improves MSE by only 0.0657%, worsens QLIKE by 0.2380%, and
has p=0.1799. Both `direction_supported` values are false, so `overall_verdict`
is correctly `NULL`. Recent annual ADR-premium means are treated as descriptive
only.

## Reproducibility and regression evidence

- `uv run python experiments/K1743/K1743.py` regenerated results and spec.
- Entrypoint SHA-256 in results and spec is identical:
  `dd8b51d18cb2d76a22f07a8307f8701c6110abe6db5dc785b2681392a2ac86c4`.
- Canonical result identity is
  `9c9b048b1a6f0032ddb489b93ad79955c354ff1e57a556285f6fdac4da7de696`.
- Programmatic read-back recomputed the success-rule booleans from the archived
  metrics and matched `overall_verdict=NULL`.
- `ruff` passed for the experiment and its regression test.
- Five focused tests passed. The local parity guard separately reports the new
  test as untracked until this transaction commits it; this is expected and
  must disappear when rerun from the committed checkout.

## Non-blocking limitations

Yahoo Finance is a network input rather than a frozen vendor snapshot, so the
spec honestly declares `network=allow` and the result pins the exact common
close CSV hash observed by this run. The daily common-date design cannot
identify intraday information shares or cleanly isolate exchange-specific
holiday intervals. These limitations cap the claim but do not invalidate the
reported null result.

No blocking defect remains in the reviewed snapshot.
