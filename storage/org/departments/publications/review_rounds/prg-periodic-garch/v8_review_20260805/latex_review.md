# PRG v8 — Academic / LaTeX review (read-only)

**Round**: v8, 2026-08-05
**Reviewer track**: main-thread referee simulation (publications department)
**Candidate**: `paper/prg-periodic-garch/main.tex`, 332 lines,
sha256 `8852326a7b77eb34…` (30,408 bytes; declared canonical in `canonical.json`, 2026-08-04)
**Target**: Finance Research Letters
**Prior round**: `paper/prg-periodic-garch/review_history/v7_review_20260714/`
(verdict `MINOR_FIXES`, 6 MAJOR + 6 MINOR)

## Why this round exists

The pipeline blocker read *"v7 review cycle (latex + citation + Codex) not yet run."*
That is inaccurate: the v7 round **was** run on 2026-07-14 and its findings **were**
fixed in `e2ffd8d90` (4 MAJOR + 3 MINOR), `af81d2e73` (M5/M6) and `c23e36b5c`
(9 mechanism citations, 2026-07-19). Every one of the six v7 MAJORs is addressed in the
current text — verified line by line below.

What was actually missing is the round that has to follow a revision: all v7 reports were
bound to pre-fix hashes and went stale the moment the fixes landed
(`paper-review-cycle` §5). This round reviews the post-fix manuscript. The blocker string
should be corrected, not merely cleared.

### v7 MAJOR disposition (verified against current text)

| v7 item | Where addressed | Status |
|---|---|---|
| M1 measure-theoretic error | L103 now "corresponds to no coherent single-issuance-time forecast" | RESOLVED |
| M2 vintage-fragile headline | L39/L59 "on the pinned vintage"; L200 vintage-sensitivity paragraph | RESOLVED |
| M3 functional-form confound | L62 caveat inline + L193 retained | RESOLVED |
| M4 "implicit in the literature" | L103/L106 softened to "including earlier drafts of this paper" | RESOLVED in §2.3 — **reintroduced, worse, in the conclusion (MAJOR-1)** |
| M5 "no market significant" | L187 now names QQQ p=0.02 as nominally significant against PRG | RESOLVED in §4.1 — **abstract still carries the loose version (MAJOR-3)** |
| M6 "reproduces every sign" | L198 rewritten around the 0050.TW sign flip | RESOLVED — **replacement sentence is itself false (MAJOR-2)** |

Three of the six fixes are complete; three moved the defect rather than removing it.

---

## VERDICT: `FAIL` — 4 MAJOR, 2 MINOR

No fabrication, no lookahead, no unbound number. Every statistic in Table 2 reconciles with
the two pinned JSONs (independently re-derived this round — see
`reproducibility_manifest.md`). All four MAJORs are one- or two-sentence prose fixes
requiring no new computation.

---

## MAJOR findings

### MAJOR-1 — The conclusion names two published papers as instances of the confound; neither commits it, and §2.3 says no published instance is known (L207 vs L103–106)

L207: *"Comparisons in the overnight-information literature \citep[e.g.,][]{Tsiakas2008,Todorova2014}
that combine components issued at different times---or that benchmark open-informed
forecasts against close-informed models---can overstate model value by several t-units per
market."*

Three problems, in increasing order of cost:

1. **Internal contradiction.** §2.3 (L103) concedes the only concrete instance of the mixed
   comparison is *"earlier drafts of this paper"*, and L106 argues the convention is "not a
   straw man" from first principles precisely *because* no published example is offered. The
   conclusion then supplies two published examples. A referee reading sequentially hits the
   contradiction directly.

2. **The attribution is wrong for both papers.** The mixed convention as defined at L103
   requires a *full-day composite* assembled from an `F^c_{d-1}`-measurable overnight
   component and an `F^o_d`-measurable intraday component, benchmarked against a model held
   at `F^c_{d-1}`. Neither cited paper constructs such an object:
   - **Tsiakas (2008, JBF)** specifies a stochastic volatility model *for daytime returns*,
     with overnight news entering as feedback; it does not model overnight returns and so
     produces no overnight forecast component to add. There is nothing to mix.
   - **Todorova and Souček (2014, FRL)** forecast *intraday* realized volatility, treating
     overnight information as a separate regressor rather than folding it into the daily RV
     aggregate — which the literature cites as the paper's contribution. The target is the
     intraday session, not the full day, so again no two-time composite exists.

   Both are, if anything, early instances of the coherent **open-time** design this paper
   advocates. Naming them as the confound inverts their contribution.
   (Evidence and its limits: `citation_report.md`.)

3. **Submission risk.** Todorova and Souček (2014) appeared *in Finance Research Letters* —
   the target venue. FRL uses single-anonymized review and routes overnight-volatility
   submissions to exactly this author pool. An unsupported methodological accusation against
   a prior FRL paper, contradicted by the submitting paper's own §2.3, is the kind of thing
   that loses a letter at first reading.

**Fix (choose one, both one sentence):**
- *Minimal*: drop the `\citep[e.g.,][]{...}` and leave the sentence generic — the claim needs
  no named defendants, and §2.3 already establishes the mechanism.
- *Better*: flip the framing — cite both as prior work that already evaluates at a coherent
  open horizon, and position this paper as formalizing what they did implicitly and
  quantifying the cost when the convention is *not* matched. This converts two likely
  referees from adversaries into cited antecedents at no cost to the contribution.

### MAJOR-2 — "Nothing approaches the conservative threshold in either variant" is false: QQQ's lagged variant lands at t = −2.95, p = 0.003 (L198)

L198 (the M6 replacement sentence): *"a lagged-realized variant (z = r²_{d-1,0}) reproduces
the verdict in every market---nothing approaches the conservative threshold in either
variant, and the near-zero 0050.TW cell flips sign across variants."*

Evidence, `experiments/k1699/k1699_results.json` (JSON orientation: negative t favours PRG;
paper prints the flipped sign):

| Market | `PRG_tminus1_exp_vs_GJR.t_stat` | `PRG_tminus1_lag_vs_GJR.t_stat` | lag `p_value` |
|---|---|---|---|
| QQQ | +2.2819 (paper −2.28) | **+2.9523 (paper −2.95)** | **0.00319** |
| SPY | +0.7414 (−0.74) | +1.2524 (−1.25) | 0.2106 |
| GLD | −0.4362 (+0.44) | −0.1822 (+0.18) | 0.8554 |
| EEM | −0.5410 (+0.54) | −0.0035 (+0.00) | 0.9972 |
| 0050.TW | −0.3175 (+0.32) | +0.2798 (−0.28) | 0.7796 |
| TAIFEX | −0.4916 (+0.49) | −0.2291 (+0.23) | 0.8189 |

QQQ's lagged cell sits **0.048 t-units** below the paper's own |t| > 3.0 threshold, and its
p-value (0.00319) is essentially at the Bonferroni level derived at L111
(α/m = 0.05/18 ≈ 0.0028). "Nothing approaches the threshold" is exactly wrong for this cell —
the second time in two rounds that a robustness sentence overstates the null (v7's M6 was the
same defect with different wording). The 0/6 Harvey count is intact
(`harvey_pass_abs_t_gt_3 = false` in all twelve cells), so the substantive verdict survives;
the sentence does not.

**Fix**: *"…a lagged-realized variant (z = r²_{d-1,0}) leaves the verdict unchanged: no market
clears the conservative threshold in either variant. The one cell that comes close, QQQ,
strengthens from t = −2.28 to −2.95 (p = 0.003) — still short of the threshold and still
against PRG — and the near-zero 0050.TW cell flips sign across variants (+0.32 vs −0.28),
exactly as statistical noise should."* More honest **and** stronger: a robustness check that
moves the one adverse cell further from PRG shows the close-time null is not propped up by
the plug-in choice.

### MAJOR-3 — The abstract's "zero of six markets significant" carries no threshold qualifier, contradicting the §4.1 sentence fixed for exactly this reason (L39 vs L187)

L39: *"Under a coherent close-time convention … the advantage vanishes: zero of six markets
significant."* L187, post-M5-fix, is precise: *"no market comes near the conservative
threshold, and the only nominally significant cell (QQQ, t = −2.28, p = 0.02) points against
PRG."*

Unqualified, "zero of six markets significant" is false at conventional levels: QQQ is
p = 0.023 in the expectation variant and p = 0.003 in the lagged one. It holds only under the
paper's |t| > 3.0 convention, which the abstract never states — and the abstract *does*
mention |t| > 3 later for the *open* panel, which invites the reader to assume the close-panel
claim is the ordinary one. This is the M5 defect surviving in the section every referee and
editor reads first.

**Fix**: *"…the advantage vanishes: zero of six markets clear the conservative |t| > 3
threshold, and the only nominally significant market points against PRG."* Costs 9 words; the
abstract is at 230/250.

### MAJOR-4 — "Every number in this paper reproduces bit-identically from the archived snapshots" is not backed by a passing end-to-end receipt (L118 footnote)

Run this round:

```
uv run python scripts/reproduce_check.py run --experiment k1699 --timeout 1200
uv run python scripts/reproduce_check.py run --experiment K1710 --timeout 1200
→ both: unverified (INPUT_HASH_MISMATCH)
   summary: missing=[]; hash_mismatch=['src/volpred/stats/model_evaluation.py']
```

The gate compares whole-file hashes and **refuses to execute** on a mismatch, so no re-run
happened and no `reproducible: true` receipt exists for either experiment.

The mismatch is not substantive, and this round proves that rather than assuming it. The only
commit touching that file since the spec was pinned is `9f868e41f` (2026-07-15), adding three
lines — a `variance_risk` branch inside `strategy_dm_test`, a function neither experiment
calls. Function-level hashes of the pre-commit and HEAD versions:

```
dm_test           pre=4aa7d4d0fcdf7d3e head=4aa7d4d0fcdf7d3e  IDENTICAL
qlike_pointwise   pre=330ccbc6229a37c8 head=330ccbc6229a37c8  IDENTICAL
strategy_dm_test  pre=7e10591368fcb9df head=c1077cacf9b447ad  CHANGED
```

Both experiments import exactly `dm_test` and `qlike_pointwise` (`k1699.py:75`,
`K1710.py:88`). The computational surface behind every number is therefore byte-identical to
the pinned spec — but "the calculation path did not change" is weaker than "every number
reproduces bit-identically," and only the weaker statement is currently evidenced.

What *is* evidenced: the paper-level gate `reproduce.py` is GREEN, 28/28, 100% match
(7 JSON invariants + 21 tex bindings, no live fetch). That certifies manuscript↔pinned-JSON
binding, not snapshot→JSON re-execution.

**Fix**: two parts; only the first blocks submission.
1. Until an end-to-end receipt exists, state what is proven: *"every number in this paper is
   bound to the archived pinned-vintage result files, which the replication package reproduces
   from the snapshots."*
2. The gate's whole-file hashing is a platform defect, not a paper defect — an unrelated edit
   anywhere in a shared module silently un-certifies every dependent experiment, and the gate
   then refuses to run the check that would settle it. Referred to platform engineering.

**Update, same day** — platform engineering independently re-verified all of the above and has a
fix designed and tested (import-surface comparison: the transitive closure of module-level names
reachable from the imported symbols, rather than the whole file; five adversarial cases pass
fail-closed, and receipts will record `discovery.input_scope` with the waived whole-file mismatch
and the compared symbol closure). It is blocked only on write access to `scripts/`, escalated to
the manager.

Their reply also improves fix (1), and the improvement should be adopted: once a receipt exists,
**do not restore a bare "bit-identically" claim.** State the basis the receipt compared against.
A claim that says only "bit-identical" with no stated comparison basis will regenerate this exact
MAJOR finding the next time any shared module is touched — which is how it arose in the first
place. Suggested target wording for the footnote after the receipt lands:

> Every number reproduces from the archived pinned snapshots under the reproducibility receipt of
> <date>, which pins the data snapshots and the computational surface (the estimation and
> evaluation code reachable from the experiments' entry points).

---

## MINOR findings

### MINOR-1 — The multiple-testing family is defined after seeing the results (L111)

L111 sets the family as "the 18 pairwise DM tests of Table 2" and excludes the six lagged
robustness tests because they "are far from significance under any threshold." That exclusion
is data-dependent — and MAJOR-2 shows the stated reason is not accurate for QQQ (p = 0.003).
Including all 24 tests gives α/m = 0.05/24 ≈ 0.0021, |z| ≈ 3.08; no verdict changes (closest
open-panel cell SPY 3.56, closest close-panel cell QQQ-lag 2.95), so the honest version costs
nothing.

**Fix**: either declare the family over all 24 tests (threshold 3.0 → 3.08), or state that the
family is the main table and the lagged variants are diagnostics outside it — with the reason
given ex ante, not by their outcome.

### MINOR-2 — The "high overnight share" group silently omits 0050.TW, which outranks a market that is included (L195)

L195 names TAIFEX (68.9%), EEM (70.7%) and GLD (60.9%) as the high-share markets whose
close-time advantage might survive. 0050.TW sits at 63.5% — above GLD — and is omitted. Its
close-time statistic is +0.32, so including it strengthens the paragraph. A referee who checks
Table 1 will read the omission as a cherry-picked group boundary.

**Fix**: add 0050.TW (63.5%, +0.32); the conclusion is unchanged and the enumeration becomes
exhaustive above 60%.

---

## Checks that passed

- **Length (FRL)**: abstract 230 words (limit 250); body 2,133 words (limit ~2,500).
- **Candidate identity**: `main.pdf` page 1 carries the current post-fix abstract verbatim,
  including "on the pinned vintage" — the PDF matches the declared canonical `.tex`.
  (`main.pdf` is untracked; identity confirmed by content, not by git.)
- **Table 2 arithmetic**: all 18 DM cells + 6 lagged cells re-derived from the JSONs with the
  sign flip applied; every printed value and p-value matches to the displayed precision.
- **Derived spans**: "mixed − close gap 3.8 to 7.1" (actual 3.84–7.06); "spread reaches 9.6
  t-units (EEM)" (10.14 − 0.54 = 9.60); "−2.3 to +10.1" (−2.28, +10.14). All correct.
- **Rank-ordering claim (L193)**: share order EEM 70.7 > TAIFEX 68.9 > 0050 63.5 > GLD 60.9 >
  SPY 44.8 > QQQ 38.5 maps to open-panel t of 10.14 > 5.50 > 3.67 > 3.64 > 3.56 > 1.56 —
  strictly monotone. Claim correct, and correctly labelled vintage-sensitive.
- **Table 1 shares**: all six match
  `K1710_results.json .markets.<M>.oos_overnight_variance_share` to 1 dp.
- **Lookahead**: close panel uses `ĥ_{d,0}` (expectation) or `r²_{d-1,0}` (lag); open panel
  uses `r²_{d,0}` and grants the same to GJR-X. No component uses information ahead of its
  declared issuance time.
- **Compliance**: no platform/AI/LLM strings; single author, correct affiliation and email.

## Not verifiable this round

- **Reference style vs FRL's current Guide for Authors.** The manuscript uses `apalike`
  author–year. Session permissions blocked direct fetching of the Elsevier author guide and
  the secondary sources found disagree. Flagged for the journal-review gate before submission;
  not counted as a finding.
- **Independent Codex methodology track.** Blocked this session — `codex exec` and
  `scripts/codex_exec_bounded.sh` are both denied under the current permission mode. This
  round is two-track (referee + citation), not the three-track standard the v7 round met.
  Recorded as a round limitation.
