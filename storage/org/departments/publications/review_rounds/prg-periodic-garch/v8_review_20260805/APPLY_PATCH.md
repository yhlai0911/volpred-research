# prg-periodic-garch v8 — exact edits, ready to apply

> **SUPERSEDED as the execution copy, 2026-08-05.** The manager ruled that `paper/` is a reserved
> area (CLAUDE.md: manuscript writing stays in the main thread) and will not be granted to this
> department, so these edits are executed by the main thread from
> `../../../work/prg_v8_edit_instructions.md` — same six edits, plus line numbers and the full
> evidentiary basis for each, in the format the manager asked for. **Edit that file, not this one**,
> so the two cannot drift. This copy stays as part of the immutable round record.

**Target**: `paper/prg-periodic-garch/main.tex`, sha256
`8852326a7b77eb3455038f558c823dcefa311a282697f82ff2e5d798813c86ed` (30,408 bytes)

Every edit below is a literal find/replace against that file. The judgement is already done —
whoever holds write access to `paper/` should not need to re-read the manuscript or re-derive
anything. If `main.tex` no longer matches the hash above, stop: the round is stale and the edits
must be re-checked against the new text.

Apply in this order. Edits 1–4 are the MAJORs and are independent of each other.

---

## Edit 1 — MAJOR-1, line 207 (apply first; this is the one with external risk)

The conclusion names two published papers as instances of the mixed-timing confound. Neither
commits it, §2.3 says no published instance is known, and Todorova & Souček (2014) appeared in
Finance Research Letters — the submission target.

Taking the **minimal** fix rather than the reframe. The reframe (citing both as coherent
open-time antecedents) is the better paper, but `citation_report.md` requires confirming their
designs against the primary PDFs first, and that verification was not possible this round.
Removing an unsupported accusation needs no such confirmation; replacing it with an unsupported
compliment does.

**FIND**
```
Comparisons in the overnight-information literature \citep[e.g.,][]{Tsiakas2008,Todorova2014} that combine components issued at different times---or that benchmark open-informed forecasts against close-informed models---can overstate model value by several $t$-units per market.
```

**REPLACE**
```
Comparisons that combine components issued at different times---or that benchmark open-informed forecasts against close-informed models---can overstate model value by several $t$-units per market.
```

`Tsiakas2008` and `Todorova2014` both remain cited elsewhere (L55, and Todorova at L55 only), so
no `\bibitem` becomes orphaned. Verify with a compile.

## Edit 2 — MAJOR-2, line 198 (a false statement about the paper's own robustness result)

`PRG_tminus1_lag_vs_GJR` for QQQ is `+2.9523` in the JSON (paper convention: −2.95), p = 0.00319 —
0.048 below the paper's own threshold, and essentially at its Bonferroni level.

**FIND**
```
a lagged-realized variant ($z = r^2_{d-1,0}$) reproduces the verdict in every market---nothing approaches the conservative threshold in either variant, and the near-zero 0050.TW cell flips sign across variants ($+0.32$ vs.\ $-0.28$), exactly as statistical noise should.
```

**REPLACE**
```
a lagged-realized variant ($z = r^2_{d-1,0}$) leaves the verdict unchanged: no market clears the conservative threshold in either variant. The one cell that comes close, QQQ, strengthens from $t=-2.28$ to $-2.95$ ($p=0.003$)---still short of the threshold and still against PRG---and the near-zero 0050.TW cell flips sign across variants ($+0.32$ vs.\ $-0.28$), exactly as statistical noise should.
```

The replacement is also the stronger paragraph: a robustness check that pushes the one adverse
cell *further* from PRG shows the close-time null is not propped up by the plug-in choice.

## Edit 3 — MAJOR-3, line 39, abstract (the §4.1 fix never reached the abstract)

Unqualified, "zero of six markets significant" is false at conventional levels — QQQ is p = 0.023
in the expectation variant and p = 0.003 in the lagged one. Abstract is at 230/250 words; this
costs 9.

**FIND**
```
the advantage vanishes: zero of six markets significant.
```

**REPLACE**
```
the advantage vanishes: zero of six markets clear the conservative $|t|>3$ threshold, and the only nominally significant market points against PRG.
```

## Edit 4 — MAJOR-4, line 118 footnote (claim outruns the current evidence)

No end-to-end receipt exists: the experiment gate returns `unverified (INPUT_HASH_MISMATCH)` and
refuses to execute. The cause is proven non-substantive (function-level identity of `dm_test` and
`qlike_pointwise`), but "the calculation path did not change" is weaker than "reproduces
bit-identically."

**FIND**
```
every number in this paper reproduces bit-identically from the archived snapshots
```

**REPLACE**
```
every number in this paper is bound to the archived pinned-vintage result files, which the replication package reproduces from the snapshots
```

**Do not restore a bare "bit-identically" claim once the receipt lands.** Per platform
engineering's reply, state the basis the receipt compared against — otherwise this exact MAJOR
regenerates the next time any shared module is touched. Target wording once the gate is fixed and
rerun:

```
Every number reproduces from the archived pinned snapshots under the reproducibility receipt of <date>, which pins the data snapshots and the computational surface (the estimation and evaluation code reachable from the experiments' entry points).
```

---

## Edit 5 — MINOR-1, line 111 (multiple-testing family defined after seeing results)

Two options. **Recommended: option A**, which is a pure disclosure fix and touches nothing else.
Option B is defensible but edits the threshold, the table's `***` note, and every place `3.0`
appears.

**Option A — state the family boundary ex ante (recommended)**

FIND
```
the six lagged-variant robustness tests discussed in Section~\ref{sec:results} are far from significance under any threshold, and we report nominal $p$-values throughout so readers can apply their own standard.
```

REPLACE
```
the six lagged-variant robustness tests of Section~\ref{sec:results} are reported as diagnostics outside this family, since they re-examine the same close-time comparison under an alternative plug-in rather than adding an independent hypothesis; we report nominal $p$-values throughout so readers can apply their own standard.
```

**Option B — widen the family to all 24 tests.** Threshold moves 3.0 → 3.08
($\alpha/m = 0.05/24 \approx 0.0021$). Verified against the JSONs: **no verdict changes** — open
panel stays 5/6 (closest included cell SPY 3.56), close panel stays 0/6 (closest cell QQQ-lag
2.95), mixed stays 6/6 (closest 4.33). Requires updating L111, the Table 2 note, and the two
in-text references to the threshold.

## Edit 6 — MINOR-2, line 195 (high-share group omits a market that outranks an included one)

0050.TW is 63.5%, above GLD's 60.9%, and is left out. Its close-time statistic is +0.32, so
including it strengthens the paragraph.

**FIND**
```
(TAIFEX at 68.9\%, EEM at 70.7\%, GLD at 60.9\%) might retain a close-time PRG advantage. They do not: their close-time DM statistics are $+0.49$, $+0.54$, and $+0.44$---directionally favorable, nowhere near significance.
```

**REPLACE**
```
(EEM at 70.7\%, TAIFEX at 68.9\%, 0050.TW at 63.5\%, GLD at 60.9\%) might retain a close-time PRG advantage. They do not: their close-time DM statistics are $+0.54$, $+0.49$, $+0.32$, and $+0.44$---directionally favorable, nowhere near significance.
```

(Reordered by share so the enumeration is exhaustive above 60% and reads in one direction.)

---

## After applying

1. Recompile `main.tex`; confirm no orphaned citation warning from Edit 1 and that the abstract
   still fits (it will: 230 + 9 = 239 of 250).
2. Rerun `paper/prg-periodic-garch/reproduce.py` — it binds prose to the pinned JSONs, and Edits
   2, 3 and 6 add numbers to the prose. All of them are already in the JSONs
   (`PRG_tminus1_lag_vs_GJR.t_stat` / `.p_value` for QQQ, `oos_overnight_variance_share` and
   `PRG_tminus1_exp_vs_GJR.t_stat` for 0050.TW), so the gate should stay green at 28/28 or grow.
   **If it does not, stop and report — do not adjust prose to satisfy the gate.**
3. Open round v9. All three v8 reports are bound to the pre-edit hash and go stale on Edit 1.
   v9 should restore the Codex third track: v7's Codex track is what caught M5 and M6, which are
   the same defect class as this round's MAJOR-2 and MAJOR-3.
4. Correct the pipeline blocker string. It currently reads *"v7 review cycle (latex + citation +
   Codex) not yet run"*, which was already wrong before this round. Proposed replacement:
   *"v8 round FAIL (4 MAJOR, 2 MINOR) 2026-08-05; MAJORs applied <date>, awaiting round v9."*
