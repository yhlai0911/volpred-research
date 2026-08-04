# K1745 independent certification review (round 1)

You are the independent reviewer of record for experiment **K1745 — TVP-HAR (Kalman random-walk
time-varying HAR) vs expanding-window OLS-HAR, one-day-ahead range-variance-proxy forecasts**.

Your verdict is the merge gate. `scripts/experiment_gates.py certify` refuses the merge unless a
`review_verdict.json` with `verdict: PASS` is bound to exactly the bytes listed below. Nothing has
been merged; nothing will be, unless you say PASS.

## Read-only contract

- Sandbox is read-only. Do **not** modify, rerun, or regenerate anything.
- Review the artifacts **as frozen**. Do not judge what the experiment "could" be after a fix;
  judge what these bytes claim and whether the claim is supported.

## Claim surface (frozen; verify these hashes before you start)

Root: `.claude/worktrees/dispatch-slot-1-c6dd8dc8-k1745/experiments/K1745`

| file | sha256 | bytes |
|---|---|---:|
| `K1745.py` | `1ddf9d84b09dbcc0a51fb7ee5b9f06ae901184dd94ae004f2a4bdc7473fde313` | 34220 |
| `K1745_results.json` | `51c4bb55edc2349bf04d0b89f0e29425083c2df500be1e6fec7f4923babefb13` | 27120 |
| `README.md` | `956af17dbcc850734195eca6e1aeab0c66e02533741e10b55280e92353cc83bf` | 6715 |
| `K1745_forecasts.csv` | `5a8010f50f303a4cea1691982c44961b36980d07e30f8b7b51b03558863eb4d3` | 1725364 |
| `K1745_paths_and_fluctuation.png` | `14bed383f0d6eccf3281073e26a6ce47e2a9d6d594d32e55662b5b959b1202eb` | 263548 |
| `test_K1745.py` | `5068c4d3c3f1f8e655880449c0a0c01bc04f399715f24f3ccc1433bfe4cc00ab` | 2895 |
| `reproduce_spec.json` | `4cd4c52e18e5a1fdb4047c4e3be2c115467b785f5b6201028f368abd3db78e32` | 3386 |
| `source_manifest.json` | `2d33081bba48e8c563a9d164f6d9361701417d4300b32969efe8b1e06204d505` | 3279 |
| `gate_history/5462187d__K1745.py` | `5462187d49e6f08e9ad7a374b9406eded082e429fb07b247f193b424fda02a95` | 33803 |
| `gate_history/bcd8e55f__K1745.py` | `bcd8e55f97f2db6792b7d146f7945e5ecf1fcca726df8050e00edd5d9d6fb39c` | 34206 |

Frozen input data: `data/SPY_ohlcv.csv` (sha256 `11bc96de…`, 480945 B),
`data/0050_TW_ohlcv.csv` (sha256 `f5bdf96a…`, 353569 B).

## What the experiment claims

Verdict `NULL_NO_MULTIPLICITY_AWARE_TVP_HAR_EDGE` — TVP-HAR does **not** beat static HAR. Headline
table (primary loss QLIKE; `improvement_pct` negative ⇒ TVP worse):

| Market | OOS n | span | QLIKE improvement | HLN t | Holm p | GR Holm p |
|---|---:|---|---:|---:|---:|---:|
| SPY | 4146 | 2010-02-05..2026-07-31 | −0.625% | 2.550 | 0.0324 | 0.0720 |
| 0050.TW | 3018 | 2014-03-18..2026-07-31 | −0.271% | 0.125 | 0.9596 | 0.2360 |

## What the dispatcher already verified mechanically (do not re-spend effort here)

These passed; treat as given and spend your budget on judgement, not arithmetic:

1. `experiment_gates.py run` → PASS on 4 files / 4 integrity gates.
2. **Byte pin exact**: on-disk `K1745.py` sha256 == `results.code_trace.sha256` ==
   `reproduce_spec.entrypoint.sha256`, sizes all 34220 (i.e. no K1708-style spec-vs-code drift).
3. **README ↔ results.json**: every cell of the table above matches `K1745_results.json` to the
   printed precision (n, span, improvement_pct, hln_t, holm_p, GR holm_p).
4. **Independent recompute from the frozen `K1745_forecasts.csv` sidecar** reproduces, to ≤1e-9:
   `mean_tvp`, `mean_static` (canonical QLIKE = a/p − log(a/p) − 1), `mean_loss_diff`,
   `improvement_pct`; and to ≤5e-3 the Newey–West HAC t at the declared bandwidth and the HLN
   factor / `hln_t`. Holm adjustment recomputed over the declared 4-cell family — matches.
5. Arithmetic consistency: usable rows − 1260 initial-training = OOS n, exactly, both markets
   (5406−1260=4146; 4278−1260=3018).
6. `signal.shift(1)` is present at `K1745.py:133` (`predictors = raw_signal.shift(1)`).

So the numbers are internally consistent and reproducible from the sidecar. **The open question is
whether the method and its reporting are sound.**

## Your review targets (judgement, in priority order)

1. **Nesting / DM admissibility — highest priority.** TVP-HAR with state noise `q → 0` collapses to
   a constant-coefficient HAR. Are the two forecasts nested in the sense that invalidates the
   standard Diebold–Mariano null, given the estimation schemes differ (expanding-window OLS vs
   sequential Kalman filtering)? Giacomini–White conditional predictive ability licenses nested
   comparison for *forecasting methods* under finite/rolling estimation windows — but this
   experiment uses an **expanding** window. Does the reported inference survive that? Is the
   Clark–West / GW distinction handled or silently skipped? The repo's `audit_nested_dm_misuse`
   ratchet did not fire; decide whether it *should* have.
2. **Lookahead, end to end.** `shift(1)` exists, but verify the whole seam in `K1745.py`: expanding
   OLS training labels ending ≤ t−1 (README claims a runtime assertion — confirm it exists and is
   actually reachable), the Kalman update ordering (predict-then-update vs update-then-predict at
   the forecast origin), the lognormal mean correction, and the clipping rule. Confirm static and
   TVP share identical origins/targets/transforms — an asymmetry here would invalidate the
   comparison in *either* direction.
3. **q selection.** `q` chosen from `(1e-6, 1e-5, 1e-4)` on the final 252 obs of the first 1260,
   then frozen. Both markets selected the **grid boundary** `1e-6` — the smallest value, i.e. the
   one closest to "no time variation". README calls boundary selection "weak identification, not
   structural truth". Is the tuning genuinely inside training (no leakage), and does boundary
   selection mean the primary specification is effectively degenerate toward the baseline — and if
   so, is the NULL verdict actually informative or merely tautological? Say so plainly.
4. **Reporting completeness / selective emphasis.** The declared primary family is 2 markets ×
   {QLIKE, MSE}. One of those four cells — **0050.TW / MSE — is Holm-significant in TVP's favour**
   (`improvement_pct` +3.31%, `hln_t` −3.946, `p` 8.11e-05, `holm_p` 3.24e-04). The README's
   Results section shows only the QLIKE rows and points at MSE via a bare JSON path. Given the
   verdict is a NULL, is omitting a Holm-significant favourable cell from the prose an acceptable
   preregistration-discipline call (secondary loss cannot rescue primary), or is it under-reporting
   that a reader would need to know? Also check the huge MSE/QLIKE disagreement on 0050.TW —
   `mean_loss_diff` for MSE is −4.4e-10 on a variance-scale target; is MSE numerically meaningful
   here at all, or is it a scale artifact?
5. **Sign-convention coherence.** README §Method states "Differential = TVP minus static, so
   negative favors TVP"; the Results table column "QLIKE improvement" uses the *opposite* polarity
   (−0.625% means TVP is worse). Both agree with `results.json`, but decide whether one document
   carrying two opposed sign conventions is a blocking clarity defect or an editorial note.
6. **Giacomini–Rossi fluctuation implementation.** 20% window (829 / 603 obs, min 126), full-sample
   HAC standardization, seeded 499-draw circular moving-block bootstrap of the sup|local stat|.
   Check: is full-sample HAC standardization appropriate under the fluctuation null; is the block
   length (18 / 16) defensible against the Bartlett lag (17 / 15); does centering under the null
   match GR (2010); is 499 draws adequate for the 5% critical value being reported to 3 decimals;
   is `peak_window_end_index` 3016 of 3018 for 0050.TW (i.e. at the very sample edge) a red flag?
7. **Data proxy honesty.** Garman–Klass daily range variance is *not* intraday RV. `0050.TW` had 19
   non-positive raw GK values floored at 1e-12 — check the floor cannot distort QLIKE (which
   divides by the prediction and logs the ratio). Extremes >99pct: 55 / 43. Is the TX exclusion
   (`provenance.tx_feasibility`) honest, or convenient?
8. **Literature and citation integrity.** Five cited works; verify authors/years/DOIs are correct
   and that each is characterized accurately — in particular that Xu (2025) is local-linear TVP
   (not Kalman) as the README concedes, and Manner–Türk–Eichler (2018) is the true state-space
   precedent. K1739's round-4 FAIL included fabricated citation authors; assume nothing.
9. **`test_K1745.py`** — does it test anything that would actually catch a lookahead or an
   estimation-asymmetry bug, or is it decorative?

## Standard

- Judge the **null claim** with the same severity you would a positive one. A NULL that is null for
  the wrong reason (a bug that handicaps TVP, a degenerate q, an inadmissible test) is just as
  wrong as a fabricated positive, and it poisons the knowledge base against a method that may work.
- Any defect that would make the recorded finding wrong, unsupported, or misleading is **blocking**
  ⇒ FAIL. Style, wording, and nice-to-haves are non-blocking notes.
- Do not soften. The precedent case K1739 was FAILed at round 4 for 6 defects and the gate correctly
  held it out of main. FAIL is a normal, expected outcome.

## Required output

Write a full prose review: what you checked, what you found, file:line evidence for every defect,
and severity for each. Then end the report with **exactly one** fenced JSON block, last thing in the
file, matching this schema verbatim (the dispatcher extracts it programmatically — do not vary keys,
do not add commentary inside the block):

```json
{
  "kid": "K1745",
  "verdict": "PASS or FAIL",
  "reviewer": "<model> / <effort>",
  "reviewed_at": "<ISO8601>",
  "reviewed_commit": "<the frozen sha you read, or the worktree HEAD>",
  "review_artifact": "storage/ops/codex_reviews/k1745_round1_verdict.md",
  "blocking_defects": [],
  "reviewed_sha256": {
    "K1745.py": "1ddf9d84b09dbcc0a51fb7ee5b9f06ae901184dd94ae004f2a4bdc7473fde313",
    "K1745_paths_and_fluctuation.png": "14bed383f0d6eccf3281073e26a6ce47e2a9d6d594d32e55662b5b959b1202eb",
    "K1745_results.json": "51c4bb55edc2349bf04d0b89f0e29425083c2df500be1e6fec7f4923babefb13",
    "README.md": "956af17dbcc850734195eca6e1aeab0c66e02533741e10b55280e92353cc83bf",
    "gate_history/5462187d__K1745.py": "5462187d49e6f08e9ad7a374b9406eded082e429fb07b247f193b424fda02a95",
    "gate_history/bcd8e55f__K1745.py": "bcd8e55f97f2db6792b7d146f7945e5ecf1fcca726df8050e00edd5d9d6fb39c",
    "test_K1745.py": "5068c4d3c3f1f8e655880449c0a0c01bc04f399715f24f3ccc1433bfe4cc00ab"
  }
}
```

`blocking_defects` must be `[]` if and only if `verdict` is `PASS`; otherwise one plain-language
entry per blocking defect, each naming the file and line it lives at.
