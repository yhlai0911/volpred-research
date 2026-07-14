# PRG v7 Review — 2026-07-14

**Reviewer**: read-only review agent (Fable, main-thread-dispatched) + Codex CLI 0.144.1 (gpt-5.6-sol, ultra, read-only)
**Target**: `paper/prg-periodic-garch/main.tex` (v7 rewrite, 313 lines) → Finance Research Letters
**Evidence base**: `experiments/k1699/k1699_results.json` (close panel) + `experiments/K1710/K1710_results.json` (mixed anchor + open panel + ON shares), single pinned vintage 2026-07-12
**Scope**: read-only; no `.tex` / JSON modified. Three tracks: (1) academic referee sim, (2) citation verification (15 bibitems), (3) Codex independent methodology + reproduce-binding audit.

---

## VERDICT: `MINOR_FIXES`

No BLOCKING defects. Every printed data-result number reconciles bit-for-bit with the two canonical JSONs (reconciled independently by me via `jq`, and independently by Codex — see the Codex section for command + archived transcript); reproduce gate is GREEN 26/26; all 15 citations PASS; no lookahead found in either panel; FRL length limits met (abstract ~234 ≤250, body ~1,817 ≤2,500); compliance clean (no volpred/AI/LLM, author = Yi-Hao Lai only). The paper is close to referee-ready.

Six MAJOR items remain — all are **prose/framing fixes, no new experiment strictly required** — that a FRL/JoE referee would very likely raise. Two of them (M5, M6) are factual misstatements the paper makes about its own results, and M5 contradicts the paper's own Table 2 — these must be corrected before submission. The most consequential framing issue (M2) is a research-honesty reconciliation: two headline framings (open-panel "5/6 significant" and "perfectly rank-ordered") are both pinned-vintage-specific and would change under the unpinned vintage the paper itself discloses. Fix all six MAJORs before advancing to the journal-review / compliance gate.

- **BLOCKING: 0**
- **MAJOR: 6** — (M1) mixed-convention "not adapted to any single information set" is measure-theoretically incorrect; (M2) "5/6 significant" + "perfect rank-ordering" are vintage-fragile and overstated vs the robustness section; (M3) open-panel constructive claim confounded with functional form by the paper's own caveat; (M4) "mixed convention implicit in the literature" asserted without a concrete published example; **(M5)** "no market significant even at nominal levels" is false — QQQ close p=0.023 is nominally significant and contradicts Table 2's own "(0.02)"; **(M6)** "reproduces every sign" is false — 0050.TW flips sign between the exp and lag close variants.
- **MINOR: 6**

_M5 and M6 were surfaced by the Codex independent track and re-verified by me against the JSONs; M1–M4 by the referee-sim track. The `+ Codex` claim in this report's header and in M1 is backed by the archived transcript `codex_raw_transcript.txt` and the command logged in the Codex section below._

---

## MAJOR findings

### M1 — "The composite is not adapted to any single information set" is measure-theoretically false (line 103)
§2.3, Mixed convention: the composite is `σ̂²_M = ĥ_{d,0} + ĥ_{d,1}(r²_{d,0})`. The paper says it "combines an F^c_{d-1}-measurable component with an F^o_d-measurable one" (correct) and then "The composite is not adapted to any single information set" (**incorrect**). Because `F^c_{d-1} ⊆ F^o_d`, the sum of an `F^c_{d-1}`-measurable term and an `F^o_d`-measurable term **is** `F^o_d`-measurable — the whole object is computable at the day-`d` open, so it *is* adapted to `F^o_d`.

What the authors actually mean is coherence, not measurability: the composite corresponds to **no single issuance time's coherent forecast** — it treats `r_{d,0}` as *unobserved* in the first term (predicts it via `ĥ_{d,0}`) yet *observed* in the second (feeds realized `r²_{d,0}`). No single information set makes both choices simultaneously rational. This is exactly the kind of measure-theoretic imprecision a JoE/FRL econometrics referee catches, and it sits in the paper's central conceptual definition.
**Fix (1 sentence)**: replace "not adapted to any single information set" with e.g. "corresponds to no coherent single-issuance-time forecast — it treats the overnight return as unobserved in the overnight component yet observed in the intraday component — and is benchmarked against a model held at the earlier set F^c_{d-1}." (This is independently the point Codex raised at first pass.)

### M2 — Open-panel "5/6 significant" and "perfectly rank-ordered" are pinned-vintage-specific; abstract/intro overstate them vs the paper's own robustness section (lines 39, 59, 62, 187, 193, 200)
The two most quotable open-panel framings both flip under the unpinned K1544 vintage that the paper discloses at line 200:

- **Harvey count.** Pinned open panel = 5/6 (`SPY +3.56, GLD +3.64, 0050 +3.67, TAIFEX +5.50, EEM +10.14` sig; `QQQ +1.56` NS). Unpinned K1544 = **4/6** (`SPY +2.11` NS, `QQQ +2.97` NS, rest sig). SPY flips NS→sig on a **1.46 t-unit vintage swing**, and three of the five "significant" markets (SPY 3.56, GLD 3.64, 0050 3.67) sit within 0.7 of the 3.0 threshold. The abstract/intro lead with "exceeds |t|>3 in five" as a firm finding, while the Robustness paragraph says the paper makes "no claims from … borderline point values" — an internal tension, since the count *rests* on borderline values.
- **Rank-ordering.** Line 193 leans on "perfectly rank-ordered in overnight variance share … exactly the ordering a genuine overnight-information channel predicts." This perfect ordering holds **only in the pinned vintage**. Under K1544, the two lowest-share markets invert (share order QQQ<SPY, but K1544 t has QQQ 2.97 > SPY 2.11), so the ordering is *not* perfect there. The paper discloses the SPY/QQQ point moves but never notes that they break the perfect ordering it uses as mechanism evidence.

The vintage-robust claims are narrower and should be what the abstract leads with: **direction** (all six positive) and the **large-margin markets** (EEM +10.1, TAIFEX +5.5) are stable; the count (4/6 vs 5/6) and the perfect ordering are vintage-sensitive.
**Fix**: add one sentence to Robustness explicitly stating that the Harvey count and the perfect rank-ordering are vintage-sensitive (only direction + the high-share markets are robust), and soften "five of six" / "perfectly rank-ordered" in the abstract/intro to match. No new experiment required, though a 2–3-vintage stability table would make it bulletproof.

### M3 — Open-panel constructive claim ("session structure beats an exogenous-regressor patch") is confounded with functional form by the paper's own admission (lines 39, 62, 193, 207)
The paper's constructive core is the open panel: PRG open-known beats an information-matched GJR-X. But §4.2 (line 193) honestly concedes "part of the gap may reflect functional form rather than information processing, since PRG embeds the realized overnight component additively … while GJR-X must load it through a single linear regressor," and defers the clean test (intraday-target-only) to follow-up. That caveat undercuts the strong abstract/conclusion phrasing "session-level modeling adds genuine, statistically significant value" (line 62) / "Overnight information has genuine forecasting value at the open horizon" (line 39): the specific thing threatened by the confound — that PRG's *session structure* (not just its additive embedding of realized overnight) is what wins — is precisely the constructive claim.
**Fix**: soften the abstract/conclusion so the "genuine value of session structure" claim carries the functional-form caveat inline (not only in §4.2), OR run the promised intraday-target-only comparison (P1-2(i) in EXECUTION.md) and fold in one row. For an FRL letter the wording fix is likely sufficient; a referee may still ask for the experiment.

### M4 — "Mixed convention implicit in parts of the overnight-information literature" is asserted without a single concrete published example (lines 39, 103, 106)
The motivating claim of a methods-warning paper is that the literature actually commits the mixed-timing comparison. The only concrete instance given is "including earlier drafts of this paper" (line 103) — the authors' own prior work. The cited session-level papers (Linton-Wu 2020, Todorova-Souček 2014, Opschoor-Lucas 2021, Kim et al. 2023) are cited *only* as session-modeling examples, not shown to benchmark an open-informed composite against a close-informed day-ahead model. A referee will want either (a) one documented published example of the mixed comparison, or (b) the claim softened to "a latent degree of freedom that is easy to fall into (as our own earlier drafts did)" rather than "implicit in the literature."
**Fix**: either cite a concrete instance or soften the "implicit in the literature" framing. Borderline MAJOR/MINOR, but for a warning-paper the motivating claim carries weight.

### M5 — "No market is significant even at nominal levels" is factually false and contradicts the paper's own Table 2 (line 187; abstract L39) — *caught by Codex, verified against JSON*
§4.1 (line 187): "the advantage evaporates: no market is significant even at nominal levels … and the only market approaching conventional significance (QQQ, t=−2.28) points against PRG." But QQQ close has `p = 0.0226 < 0.05` — **nominally significant at 5%** (against PRG). Table 2 prints QQQ close as "$-2.28$ (0.02)", so the prose directly contradicts the paper's own table. Two errors in one sentence: (i) "no market significant even at nominal levels" is false; (ii) "approaching conventional significance" understates QQQ, which is *past* the conventional 5% level, not approaching it. The abstract carries the same "approaching conventional significance" understatement. This is the highest-priority fix — a factual misstatement about the paper's own results in a research-honesty-first pipeline.
**Fix**: reword to e.g. "no market favors PRG at the |t|>3 threshold, and the only nominally significant close-time cell (QQQ, p=0.023) points *against* PRG." Keep the abstract consistent.

### M6 — "Reproduces every sign" is false: 0050.TW sign-flips between the exp and lag close variants (line 198) — *caught by Codex, verified against JSON*
§4.1 Robustness (line 198): "a lagged-realized variant (z = r²_{d-1,0}) reproduces every sign and every insignificance of the expectation variant." Verified against K1699: 0050.TW is `exp t=−0.318` (PRG better) vs `lag t=+0.280` (GJR better) in JSON orientation — **the sign flips**. The "every insignificance" half holds (both variants 0/6 Harvey, both |t|≪1.96), so the substantive close-panel null is unaffected; but the literal "every sign" claim is wrong for 1 of 6 markets.
**Fix**: reword to "reproduces every insignificance (0/6 Harvey) and every sign except 0050.TW, whose near-zero statistic flips from −0.32 to +0.28 — both far from any threshold." Low substantive impact, but it is a false robustness claim as written.

---

## MINOR findings

_Note: m2, m3, m4 below (all `reproduce.py`) were **applied by the main thread during this review** — the docstring now says "data-result number (claim)" with a scope note, each check carries a `kind: tex_binding | json_invariant` tag, and the dead `if False` line is gone. Retained here as the record of what was found._

- **m1 (line 59)** — Intro says "PRG **dominates** GJR-GARCH" flatly, whereas Results (line 187) correctly hedges "PRG **appears to** dominate … exactly the kind of headline the overnight-information literature reports." Since the mixed result is the artifact the paper debunks, the intro should hedge too (the abstract's neutral "PRG beats GJR-GARCH" is fine). One-word fix.
- **m2 (reproduce.py docstring, line 1)** — Docstring claims it binds "every printed number in main.tex." In fact it binds every printed **data-result** number (the claims), which is the right scope, but ~8–10 printed numbers are method constants / dates / historical values that are *not* mechanically bound (see "Uncovered numbers" below). Reword the docstring to "every printed data-result number / claim," not "every printed number."
- **m3 (reproduce.py, invariant() group)** — 6 of the 26 checks (`open_positive_all_six`, `close_zero_of_six_harvey`, `close_lag_variant_zero_harvey`, `open_t_rank_ordered_in_on_share`, `k1710_bit_identical_recorded`, `snapshot_metadata_present`) assert **JSON-side** claim-truths and do **not** guard the manuscript text — editing the .tex would not fail them. Only the other 19 `check()` calls + `no_leftover_placeholders` bind tex↔JSON. Not tautological (they verify real JSON properties), but the single "26/26 match_rate" blends two check kinds; a reader could over-read it as "26 tex bindings." Consider labeling the two layers, or reporting `tex_bound=20 / json_invariant=6`.
- **m4 (reproduce.py, line 100)** — Dead no-op line: `check(f"datatable_{m}_N_and_share", ...) if False else None`. Harmless but should be deleted.
- **m5 (line 193)** — "perfectly rank-ordered … descriptive with six markets" — with n=6 a perfect ordering is a striking but fragile coincidence (see M2). The "descriptive" hedge is good; add the vintage caveat from M2. (Rolled into M2's fix.)
- **m6 (line 111)** — The multiple-testing threshold derivation ("roughly 20 pairwise tests", "α/m ≈ 0.0025", "|z| ≈ 3.02") is internally consistent (0.05/20 = 0.0025 two-sided → |z| = 3.02, verified) but the "roughly 20" is vague — state the exact count of pairwise tests reported in the paper so the Bonferroni denominator is auditable.

---

## Citation verification (15 bibitems — all PASS)

All verified via web search against publisher/RePEc records (author, year, journal, volume/issue, pages, DOI). Each cited usage in the text was checked for fidelity to the source's actual content.

| # | Key | Cite (journal, vol(iss), pp) | Detail | Usage fidelity | Verdict |
|---|---|---|---|---|---|
| 1 | Blanc2014 | Physica A 402, 58–75 | ✓ | "two sessions have different feedback structures" — accurate | PASS |
| 2 | Bollerslev1996 | JBES 14(2), 139–151 | ✓ | periodic GARCH / periodic stationarity `ρ₀ρ₁<1` — accurate; this is the model's parent | PASS |
| 3 | BollerslevWooldridge1992 | Econometric Reviews 11(2), 143–172 | ✓ | Gaussian QMLE — accurate | PASS |
| 4 | Diebold1995 | JBES 13(3), 253–263 | ✓ | DM predictive-accuracy test — accurate | PASS |
| 5 | Glosten1993 | J. Finance 48(5), 1779–1801 | ✓ | GJR leverage benchmark — accurate | PASS |
| 6 | Haas2004 | J. Financial Econometrics 2(4), 493–530 | ✓ | Markov-switching GARCH (cited as "no latent regimes" contrast) — accurate | PASS |
| 7 | Hansen2006 | J. Econometrics 131(1–2), 97–121 | ✓ | consistent ranking under imperfect proxy — accurate | PASS |
| 8 | Hansen2012 | J. Applied Econometrics 27(6), 877–906 | ✓ | Realized GARCH (cited to disambiguate PRG's "Realized" label) — accurate | PASS |
| 9 | Harvey1997 | Int. J. Forecasting 13(2), 281–291 | ✓ | small-sample DM correction — accurate | PASS |
| 10 | Kim2023 | JBES 41(4), 1215–1227 | ✓ | overnight GARCH-Itô (session-level lit) — accurate | PASS |
| 11 | Lai2024 | Asia-Pacific Financial Markets 31(2), 285–305 | ✓ | author's own periodic-regime-switching Taiwan paper — accurate | PASS |
| 12 | Linton2020 | J. Econometrics 217(1), 176–201 | ✓ title = "coupled component **DCS-EGARCH** model" (working-paper title differed; published title matches bibitem) | cited as "coupled intraday–overnight score-driven system" — accurate; **not** accused by name of the mixed convention | PASS |
| 13 | Opschoor2021 | Int. J. Forecasting 37(2), 622–633 | ✓ | "realized-variance model augmented with overnight returns" — accurate; models overnight separately | PASS |
| 14 | Patton2011 | J. Econometrics 160(1), 246–256 | ✓ | QLIKE proxy-robustness — accurate (Patton derives the robust-ranking conditions; QLIKE qualifies) | PASS |
| 15 | Todorova2014 | Finance Research Letters 11(4), 420–428 | ✓ | overnight info flow for RV forecasting — accurate; paper argues overnight treated *separately* (consistent with citation) | PASS |

**Fairness note on the mixed-convention attribution (task-flagged)**: the paper does **not** name Linton-Wu, Opschoor-Lucas, Bollerslev-Ghysels, Todorova-Souček, or Kim et al. as mixed-convention offenders. They are cited only as session-level-modeling examples; the mixed-convention charge is hedged as "implicit in parts of the literature" and the only concrete instance is the authors' own prior drafts. So no citation is *misused* to imply an error a source did not commit — the fairness issue is that the "implicit in the literature" claim lacks a documented example (see M4), not that any specific citation is unfair.

---

## Codex independent review (verdict + summary + evidence)

**Ran? Yes.** Codex CLI 0.144.1, model `gpt-5.6-sol`, reasoning effort `ultra`, sandbox `read-only`, session id `019f5ee4-5fec-7310-a163-41547f6ccf46`.

- **Command** (Chinese prompt via file arg, read-only, backgrounded):
  `codex exec --skip-git-repo-check -s read-only "$(cat <scratchpad>/codex_prg_review_prompt.md)"`
- **Full raw transcript archived as durable evidence**: `review_history/v7_review_20260714/codex_raw_transcript.txt` (3,719 lines). Prompt used: reproduced from the task's 3-track brief (A methodology / B number reconciliation / C reproduce-binding coverage).
- **Verbatim header** (proof of run):
  > `OpenAI Codex v0.144.1 … model: gpt-5.6-sol … sandbox: read-only … session id: 019f5ee4-5fec-7310-a163-41547f6ccf46`

**Honesty caveat on the verdict token**: Codex completed all three tracks (A/B/C each marked ✓ including "整合嚴重度、行號與 overall verdict"), but its final synthesis turn hit an internal tool error (`collab: Wait` / `timeout_ms must be at least 10000`) and **hung before printing a clean `PASS / PASS_WITH_CAVEAT / FAIL` token**; I stopped the hung process after archiving its transcript. So the labelled verdict below is **my characterization of Codex's stated findings, not a token Codex emitted**. Its findings themselves are verbatim and archived.

**Codex verdict (inferred from its stated findings)**: numbers/implementation clean; issues confined to prose interpretation + gate coverage — equivalent to **PASS on the numeric/reproduction surface, with prose-level caveats**. Verbatim closing finding (transcript ~line 3166):
> 「數字對帳本身很乾淨：Table 2 的 18 個 t/p cell、符號翻轉、星號與 6/6、0/6、5/6 全部正確。問題集中在正文解讀與 gate 覆蓋：例如 QQQ close 的 p=0.0226 已是 nominal 5% 顯著，正文卻寫成『nominal 也沒有』；另 lag robustness 的 0050.TW 確實發生符號翻轉。」

**Codex findings, mapped to this report**:
1. **(→ M1)** Verbatim, transcript line 846: 「Mixed 合成值在數學上其實是 F^o_d-可測，因此『不 adapted 到任何單一資訊集』這句不成立；真正問題是它作為 open-time 物件卻拿 close-time benchmark 比，屬資訊不匹配。」 — this is the measurability point in M1; I reached the same conclusion independently and both are recorded here.
2. **(→ M5, NEW — I had missed this)** QQQ close `p=0.0226` is nominally 5%-significant, contradicting line 187's "no market is significant even at nominal levels." Independently re-verified: `k1699 .markets.QQQ.dm_tests.PRG_tminus1_exp_vs_GJR.p_value = 0.02260`. Table 2 itself prints QQQ close as "(0.02)", so the prose contradicts the paper's own table.
3. **(→ M6, NEW — I had missed this)** The lag close variant sign-flips for 0050.TW, contradicting line 198's "reproduces every sign." Independently re-verified: exp `t=-0.3175` vs lag `t=+0.2798` (JSON orientation) → sign flip = true.
4. **(→ confirms clean surface)** Codex independently reconciled all 18 Table 2 t/p cells, the sign-flip convention, stars, and the 6/6, 0/6, 5/6 counts; independently confirmed the two JSON SHA-256 hashes and the canonical `dm_test` implementation (QLIKE actual/predicted orientation, HAC bandwidth ⌈n^{1/3}⌉, no lookahead in either panel — including a line-by-line audit of the FairGJRX open-panel benchmark for lookahead).

M2/M3/M4 were raised by me (the referee-sim track), not Codex; M5/M6 were raised by Codex and independently verified by me against the JSONs.

---

## Uncovered numbers (printed in main.tex but outside the reproduce.py 26 checks)

All are traceable to a source (JSON field or experiment README); none are fabricated. They are *not* mechanically gated by `reproduce.py`, which binds data-result claims but not method constants, dates, or historical/anchor values.

| # | Printed number(s) | main.tex loc | Source (traceable) | Bound by reproduce.py? |
|---|---|---|---|---|
| 1 | "6–8 parameters" | abstract, L59, L209 | model design (Eq. 2: ω,α,γ,β × 2 sessions; Basic sets γ=0) | No — design, not a data result |
| 2 | HAC bandwidth `⌈n^{1/3}⌉` | L111, L183 | method; JSON records per-cell `hac_bandwidth_canonical` = 10–13 | No — formula printed, not value |
| 3 | "roughly 20 pairwise tests", "α/m ≈ 0.0025", "|z| ≈ 3.02" | L111 | Bonferroni derivation (internally consistent) | No — method constant |
| 4 | Refit cadence "63", "126–252 sessions" | L111 | K1699 §3.2 / K1710; JSON method_summary has "63" only | No |
| 5 | Data-table OOS periods (2019-01–2026-04, …) | L131–136 | JSON `.markets.<M>.oos_period`; K1699 §3.4 | No — datatable regex skips the period column (`[^&]*`) |
| 6 | Data vintage "2026-07-12" | L118 | JSON `data_snapshots`; K1699/K1710 READMEs | No |
| 7 | "70/30 split", TAIFEX clock "15:00–08:45 / 08:45–13:45", "2014 split" | L141 | data description; K1699/K1710 READMEs | No — data description |
| 8 | Historical "SPY headline DM of 6.00" | L118 footnote | retired K880 unpinned artifact (git history) | No — deliberately unbound historical disclosure |
| 9 | Unpinned robustness "SPY +2.1, QQQ +3.0" | L200 | K1710 `anchor_validation.k1544_open_anchor` = 2.1149 / 2.9668 | No — present in K1710 JSON but not checked |
| 10 | Close-panel prose "+0.49, +0.54, +0.44" | L195 | = bound Table 2 close cells (TAIFEX/EEM/GLD) | Indirect — values are bound in the table row, prose occurrence not separately checked |

**Recommendation**: none blocks submission. If the gate wants to live up to "every printed number," the two cheap additions are #9 (unpinned +2.1/+3.0 → already in K1710 `anchor_validation`) and #5/#6 (OOS periods + vintage date → JSON `oos_period` / `data_snapshots`). #1–4, #7, #8 are method/design/historical and correctly left unbound.

---

## Numbers independently reconciled (spot-check log)

Verified by direct `jq` extraction from both JSONs (sign-flipped to positive-favors-PRG), matching Codex's independent pass:

- **Flip table (Table 2)**: close (K1699 `PRG_tminus1_exp_vs_GJR`) SPY −0.74 / QQQ −2.28 / GLD +0.44 / EEM +0.54 / 0050 +0.32 / TAIFEX +0.49; mixed (K1710 `mixed_anchor_main`) +5.83/+4.78/+6.11/+6.41/+5.19/+4.33; open (K1710 `open_panel_main`) +3.56/+1.56/+3.64/+10.14/+3.67/+5.50 — all match printed cells. Harvey counts 6/6, 0/6, 5/6 ✓.
- **Prose ranges**: mixed +4.3→+6.4 ✓; span −2.3→+10.1 (close QQQ −2.28, open EEM +10.14) ✓; inflation 3.8→7.1 (mixed−close: TAIFEX 3.84 → QQQ 7.06) ✓; max spread 9.6 t-units EEM (10.14−0.54) ✓.
- **Rank order** (pinned): by ON share asc = QQQ 38.5, SPY 44.8, GLD 60.9, 0050 63.5, TAIFEX 68.9, EEM 70.7; by open t asc = QQQ 1.56, SPY 3.56, GLD 3.64, 0050 3.67, TAIFEX 5.50, EEM 10.14 — identical ordering ✓ (but see M2: breaks under unpinned vintage).
- **Data table**: N 1823/1981/1613/1734/1251/843 ✓; ON share 44.8/38.5/60.9/70.7/63.5/68.9 = `oos_overnight_variance_share`×100 ✓.
- **Lag variant** 0/6 Harvey (SPY 1.25, QQQ 2.95, GLD −0.18, EEM −0.004, 0050 0.28, TAIFEX −0.23) ✓; K1710 `two_pass_bit_identical=true` ✓; K1699 `data_snapshots` present ✓.
