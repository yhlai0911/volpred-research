# prg-periodic-garch v8 — edit instructions for the main thread

**Requested by**: manager, 2026-08-05 (`paper/` is a reserved area under CLAUDE.md — manuscript
writing and methodology decisions stay in the main thread; this department produces the
evidence-backed instructions, the main thread applies them).

**Target file**: `paper/prg-periodic-garch/main.tex`
**Verified against sha256**: `8852326a7b77eb3455038f558c823dcefa311a282697f82ff2e5d798813c86ed`
(30,408 bytes). If the file no longer hashes to this, stop — the round is stale and every
instruction below must be re-checked before use.

**Round evidence**: `../review_rounds/prg-periodic-garch/v8_review_20260805/`
(`latex_review.md`, `citation_report.md`, `reproducibility_manifest.md`, `README.md`).

Apply edits 1–4 first; they are the MAJORs and are independent of one another. Edit 1 carries live
submission risk and should go first.

---

## Edit 1 — `main.tex:207` — MAJOR-1

**Original**

```latex
Comparisons in the overnight-information literature \citep[e.g.,][]{Tsiakas2008,Todorova2014} that combine components issued at different times---or that benchmark open-informed forecasts against close-informed models---can overstate model value by several $t$-units per market.
```

**Replacement**

```latex
Comparisons that combine components issued at different times---or that benchmark open-informed forecasts against close-informed models---can overstate model value by several $t$-units per market.
```

**Basis** — the accusation is unsupported, self-contradicting, and aimed at the target venue.

1. **What the sentence claims.** That these two published papers commit the mixed-timing confound
   the manuscript defines at `main.tex:103`: a *full-day composite* assembled from an
   `F^c_{d-1}`-measurable overnight component plus an `F^o_d`-measurable intraday component,
   benchmarked against a model held at `F^c_{d-1}`.

2. **Tsiakas (2008), JBF 32(2), 251–268.** The paper specifies a stochastic volatility model *for
   daytime returns*, with overnight news entering as feedback, and **does not model overnight
   returns**. A model that produces no overnight forecast component cannot form the two-time
   composite. There is nothing to mix.

3. **Todorova & Souček (2014), FRL 11(4), 420–428.** The paper forecasts *intraday* realized
   volatility, treating overnight information as a separate regressor rather than folding it into
   the daily RV aggregate — this separation is what the literature cites as its contribution. With
   an intraday target there is no full-day composite to assemble.

4. **The manuscript contradicts itself.** `main.tex:103` states the only concrete instance of the
   mixed comparison is *"including earlier drafts of this paper"*, and `:106` argues the convention
   is "not a straw man" from first principles **because** no published example is offered. The
   conclusion then supplies two. A referee reading in order hits this directly.

5. **Venue risk.** Todorova & Souček (2014) appeared *in Finance Research Letters* — the submission
   target. FRL uses single-anonymized review and routes overnight-volatility submissions to this
   author pool. An unsupported methodological accusation against a prior FRL paper, contradicted by
   the submitting paper's own §2.3, is a first-reading rejection risk.

6. **Why deletion and not a reframe.** The stronger paper cites both as coherent open-time
   antecedents and positions this work as formalizing what they did implicitly. That claim needs
   confirmation against the primary PDFs, which were unreachable this session (`WebFetch`/`curl`
   denied; the readings in 2–3 come from consistent secondary sources). **Removing an unsupported
   accusation requires no such confirmation; replacing it with an unsupported compliment does.**
   Upgrade later if the primaries are read.

**Evidence class**: secondary sources, consistent across independent descriptions, addressing each
paper's headline design — which is what the accusation turns on. Sufficient to establish the
manuscript's claim is unsupported (the burden is the manuscript's), not yet sufficient to assert
the positive reframe.

**Side effects**: both keys stay cited at `:55`, so no `\bibitem` is orphaned. Confirm with a
compile — no "Citation undefined" warnings.

## Edit 2 — `main.tex:198` — MAJOR-2

**Original**

```latex
a lagged-realized variant ($z = r^2_{d-1,0}$) reproduces the verdict in every market---nothing approaches the conservative threshold in either variant, and the near-zero 0050.TW cell flips sign across variants ($+0.32$ vs.\ $-0.28$), exactly as statistical noise should.
```

**Replacement**

```latex
a lagged-realized variant ($z = r^2_{d-1,0}$) leaves the verdict unchanged: no market clears the conservative threshold in either variant. The one cell that comes close, QQQ, strengthens from $t=-2.28$ to $-2.95$ ($p=0.003$)---still short of the threshold and still against PRG---and the near-zero 0050.TW cell flips sign across variants ($+0.32$ vs.\ $-0.28$), exactly as statistical noise should.
```

**Basis** — "nothing approaches the conservative threshold" is false for one cell.

From `experiments/k1699/k1699_results.json` (JSON orientation: negative *t* favours PRG; the paper
prints the flipped sign):

| Market | `.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat` | `.dm_tests.PRG_tminus1_lag_vs_GJR.t_stat` | lag `.p_value` |
|---|---|---|---|
| SPY | +0.7414 (paper −0.74) | +1.2524 (−1.25) | 0.2106 |
| **QQQ** | +2.2819 (−2.28) | **+2.9523 (−2.95)** | **0.00319** |
| GLD | −0.4362 (+0.44) | −0.1822 (+0.18) | 0.8554 |
| EEM | −0.5410 (+0.54) | −0.0035 (+0.00) | 0.9972 |
| 0050.TW | −0.3175 (+0.32) | +0.2798 (−0.28) | 0.7796 |
| TAIFEX | −0.4916 (+0.49) | −0.2291 (+0.23) | 0.8189 |

QQQ's lagged cell is **0.048 t-units** below the paper's own |t| > 3.0 threshold, and p = 0.00319 is
essentially the Bonferroni level derived at `:111` (α/m = 0.05/18 ≈ 0.0028). The 0/6 Harvey count is
intact (`harvey_pass_abs_t_gt_3 = false` in all twelve cells), so the substantive verdict survives —
the sentence does not.

This is the second round running in which a robustness sentence overstates the null: v7's M6 was the
same defect in different words. The replacement is also the stronger claim — a robustness check that
pushes the one adverse cell *further* from PRG shows the close-time null is not propped up by the
plug-in choice.

## Edit 3 — `main.tex:39` (abstract) — MAJOR-3

**Original**

```latex
the advantage vanishes: zero of six markets significant.
```

**Replacement**

```latex
the advantage vanishes: zero of six markets clear the conservative $|t|>3$ threshold, and the only nominally significant market points against PRG.
```

**Basis** — unqualified, the claim is false at conventional levels. QQQ close is p = 0.0226 in the
expectation variant and p = 0.0032 in the lagged one. It holds only under the paper's own |t| > 3.0
convention, which the abstract never states — and the abstract *does* mention |t| > 3 later for the
*open* panel, inviting the reader to assume the close-panel claim is the ordinary one.

`:187` was already corrected for exactly this defect in v7 ("the only nominally significant cell
(QQQ, t = −2.28, p = 0.02) points against PRG"); the fix never reached the abstract. Abstract is
230/250 words, so the 9 extra words fit.

## Edit 4 — `main.tex:118` (footnote) — MAJOR-4

**Original**

```latex
every number in this paper reproduces bit-identically from the archived snapshots
```

**Replacement**

```latex
every number in this paper is bound to the archived pinned-vintage result files, which the replication package reproduces from the snapshots
```

**Basis** — the claim currently outruns the evidence. Run this round:

```
uv run python scripts/reproduce_check.py run --experiment k1699 --timeout 1200
uv run python scripts/reproduce_check.py run --experiment K1710 --timeout 1200
→ both: unverified (INPUT_HASH_MISMATCH)
   summary: missing=[]; hash_mismatch=['src/volpred/stats/model_evaluation.py']
```

The gate compares whole-file hashes and **refuses to execute** on mismatch, so neither experiment
was re-run and no `reproducible: true` receipt exists.

The mismatch is non-substantive and this round proved it: the only commit touching that file since
the spec was pinned is `9f868e41f` (2026-07-15), +3 lines in two hunks, both inside
`strategy_dm_test` — a function neither experiment calls. AST function-level hashes of
`9f868e41f^` vs HEAD:

```
dm_test           pre=4aa7d4d0fcdf7d3e head=4aa7d4d0fcdf7d3e  IDENTICAL
qlike_pointwise   pre=330ccbc6229a37c8 head=330ccbc6229a37c8  IDENTICAL
strategy_dm_test  pre=7e10591368fcb9df head=c1077cacf9b447ad  CHANGED
```

Both experiments import exactly `dm_test` and `qlike_pointwise` (`k1699.py:75`, `K1710.py:88`). So
the computational surface is byte-identical to the pinned spec — but "the calculation path did not
change" is weaker than "reproduces bit-identically," and only the weaker statement is evidenced.

What *is* evidenced: `paper/prg-periodic-garch/reproduce.py` is GREEN, 28/28, 100 % match (7 JSON
invariants + 21 tex bindings, no live fetch) — manuscript↔pinned-JSON binding, not snapshot→JSON
re-execution.

**Do not restore a bare "bit-identically" claim once a receipt lands.** Platform engineering's
import-surface fix will produce one; state the basis it compared against, or this MAJOR regenerates
the next time any shared module is touched. Target wording then:

```latex
Every number reproduces from the archived pinned snapshots under the reproducibility receipt of <date>, which pins the data snapshots and the computational surface (the estimation and evaluation code reachable from the experiments' entry points).
```

## Edit 5 — `main.tex:111` — MINOR-1 (recommended option A)

**Original**

```latex
the six lagged-variant robustness tests discussed in Section~\ref{sec:results} are far from significance under any threshold, and we report nominal $p$-values throughout so readers can apply their own standard.
```

**Replacement**

```latex
the six lagged-variant robustness tests of Section~\ref{sec:results} are reported as diagnostics outside this family, since they re-examine the same close-time comparison under an alternative plug-in rather than adding an independent hypothesis; we report nominal $p$-values throughout so readers can apply their own standard.
```

**Basis** — the multiple-testing family is currently defined by outcome: the six lagged tests are
excluded because they "are far from significance under any threshold." That is data-dependent, and
Edit 2 shows the stated reason is not even accurate for QQQ (p = 0.003). The replacement gives an
ex-ante reason (they re-test the same hypothesis under a different plug-in) and touches nothing else.

**Option B, if a wider family is preferred**: declare all 24 tests, α/m = 0.05/24 ≈ 0.0021,
|z| ≈ 3.08. Verified against the JSONs — **no verdict changes**: open panel stays 5/6 (closest
included cell SPY 3.56), close stays 0/6 (closest QQQ-lag 2.95), mixed stays 6/6 (closest 4.33).
Requires editing `:111`, the Table 2 note, and both in-text references to the threshold.

## Edit 6 — `main.tex:195` — MINOR-2

**Original**

```latex
(TAIFEX at 68.9\%, EEM at 70.7\%, GLD at 60.9\%) might retain a close-time PRG advantage. They do not: their close-time DM statistics are $+0.49$, $+0.54$, and $+0.44$---directionally favorable, nowhere near significance.
```

**Replacement**

```latex
(EEM at 70.7\%, TAIFEX at 68.9\%, 0050.TW at 63.5\%, GLD at 60.9\%) might retain a close-time PRG advantage. They do not: their close-time DM statistics are $+0.54$, $+0.49$, $+0.32$, and $+0.44$---directionally favorable, nowhere near significance.
```

**Basis** — 0050.TW is at 63.5 % overnight variance share
(`K1710_results.json .markets["0050.TW"].oos_overnight_variance_share` = 0.63488), above GLD's
60.9 %, and is omitted from the "high share" group. Its close-time statistic is +0.32
(`k1699_results.json .markets["0050.TW"].dm_tests.PRG_tminus1_exp_vs_GJR.t_stat` = −0.3175, sign
flipped), so including it strengthens the paragraph. A referee checking Table 1 reads the omission as
a cherry-picked group boundary. Reordered by share so the enumeration is exhaustive above 60 % and
reads in one direction.

---

## After applying

1. **Recompile.** Confirm no undefined-citation warning from Edit 1; abstract fits (230 + 9 = 239
   of 250).
2. **Rerun `paper/prg-periodic-garch/reproduce.py`.** Edits 2, 3 and 6 add numbers to the prose; all
   are already in the pinned JSONs (`PRG_tminus1_lag_vs_GJR.t_stat`/`.p_value` for QQQ,
   `oos_overnight_variance_share` and `PRG_tminus1_exp_vs_GJR.t_stat` for 0050.TW), so the gate
   should stay green at 28/28 or grow. **If it does not, stop and report — do not adjust prose to
   satisfy the gate.**
3. **Correct the pipeline blocker string.** It currently reads *"v7 review cycle (latex + citation +
   Codex) not yet run"*, which was already wrong before this round: v7 ran 2026-07-14 and its six
   MAJORs were fixed across `e2ffd8d90`, `af81d2e73`, `c23e36b5c`. Suggested replacement:
   *"v8 round FAIL (4 MAJOR, 2 MINOR) 2026-08-05; MAJORs applied &lt;date&gt;, awaiting round v9."*
   Also set `blocker_verified_at` — governance ruled 2026-08-05 that a blocker without one is
   treated as stale by default.
4. **Open round v9.** All three v8 reports are bound to the pre-edit hash and go stale on Edit 1.
   v9 should restore the Codex third track: v7's Codex track caught M5 and M6, the same defect class
   as this round's MAJOR-2 and MAJOR-3, and v8 could not run it (`codex exec` and the bounded
   wrapper were both denied).
