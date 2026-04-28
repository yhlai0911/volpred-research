# P10 Citation Verification Report — v3

**Paper**: The Crypto Fear Channel — Asymmetric, Tail-Concentrated, and Regime-Dependent Volatility Spillover from Bitcoin to Equity Markets
**File reviewed**: `paper/crypto-fear-channel/main.tex` (v3, 542 lines, 22 bibitems)
**Reference baseline**: v2 `citation_check_report.md` (0 MAJOR / 1 MED / 5 MINOR)
**v2→v3 commits audited**: `78593750` (v2.3 hotfix), `07e53e81` (v2.4 cross-paper meta-eval rewrite), `6a41fc40` (K1025b §6.4 multi-asset extension)
**Reviewer**: citation-verifier (subagent)
**Date**: 2026-04-28
**External web verification**: 0 fresh DOI lookups required (no new bibitems introduced v2→v3); reused v2 web-verified ground truth for all 22 entries.

---

## 1. Verdict (top-line)

| Severity | v1 baseline | v2 final | **v3 final** | Δ v2→v3 |
|---|---|---|---|---|
| **MAJOR** | 1 | 0 | **0** | 0 |
| **MED** | 5 | 1 | **1** | 0 |
| **MINOR** | 7 | 5 | **4** | -1 ✓ |

**Net v2→v3 change**: -1 MINOR (v2 MIN-N1 `andrews1991` alphabetical position **closed in v2.3 hotfix**; current bibliography order is `adrian2016` → `akyildirim2020` → `andrews1991` → `bouri2020`, which matches APA alphabetical Adrian → Akyildirim → Andrews → Bouri).

**Blocks `ready_for_submission` upgrade?** **NO.**

The 4 commits between v2 and v3 (v2.3 hotfix, v2.4 cross-paper meta-eval rewrite, K1025b §6.4 new subsection + Table 7) are **purely narrative + new experimental content with NO new citations introduced**. The v3 bibliography is **byte-identical to v2** in the 22-bibitem set: same authors, same DOIs, same APA formatting. The single carry-forward MED (v2 MED-1: `conrad2020` §2.3 ¶1 framing partial overclaim) **was not touched** by any v2→v3 commit and thus remains open at copy-edit-class severity. All 22 bibitems remain (i) cited in-text at least once, (ii) DOI-complete, (iii) alphabetically ordered.

**One v3-specific verification note**: §6.4 (NEW K1025b multi-asset robustness subsection, L307–L338) introduces a new Table~\ref{tab:multiasset} comparing K1025 (BTC→VIX/SPY) vs K1025b (BTC→VXN/QQQ) but **adds no new citations** — the only cite in that subsection is `\citet{harvey2016}` in the table footnote (L334), and `harvey2016` is already in the v2 bibliography. This is consistent with the K1025b extension being a methodological replication on a parallel index, not a new literature thread. See §6 below for the meta-evaluation question of whether K1025b should cite NASDAQ-specific literature (Hong-Stein 1999, Hou-Xue-Zhang) — **verdict: NOT required for current narrative scope.**

---

## 2. v2→v3 Citation-Layer Diff Audit

### 2.1 Commit-by-commit citation impact

| Commit | Section(s) touched | Citation changes | Verdict |
|---|---|---|---|
| `78593750` (v2.3 hotfix) | §7 footnote tightening + `andrews1991` alphabetical re-positioning + `% 22 bibitems` header verification | **0 new bibitems**, 1 alphabetical re-order (closes v2 MIN-N1) | ✓ Citation-clean |
| `07e53e81` (v2.4 cross-paper meta-eval) | §1 Introduction contribution paragraph rewrite, §7 OOS interpretation tightening, §8.3 policy-implications rewrite | **0 new bibitems**, retained `\citet{harvey2016}` and `\citet{conrad2020}` calls within rewritten paragraphs (L51 contribution + L369 interpretation) | ✓ Citation-clean (cite keys unchanged, surrounding prose softened) |
| `6a41fc40` (K1025b §6.4 + Table 7) | NEW §6.4 subsection (L307–L338) + NEW Table~\ref{tab:multiasset} | **0 new bibitems**, 1 cite (`\citet{harvey2016}`) in Table footnote (L334), already present in bibliography | ✓ Citation-clean |

**Aggregate**: 4 commits × 0 new bibitems = no v2→v3 bibliography-side change to verify.

### 2.2 In-text cite usage diff (v2 vs v3)

The 22 unique cite-keys extracted from v3 main.tex via `grep -oE '\\cite[ptp]?\{[^}]+\}'`:

```
adrian2016, akyildirim2020, andrews1991, bouri2020, conlon2020, conrad2020,
corbet2018, diebold1995, diebold2009, diebold2012, diebold2014network,
diks2006, harvey1997, harvey2016, hatemi2012, hong2001, iyer2022, klein2018,
koenker1978, matkovskyy2019, shahzad2019, yarovaya2022
```

**Identical to v2 audit** (v2 report §5). 22/22 bibitems referenced in-text. **0 orphan bibitems. 0 missing-from-bib cites.** ✓

---

## 3. v2 Issue Carry-Forward Status

### 3.1 v2 MED-1: `conrad2020` §2.3 ¶1 framing partial overclaim — **CARRY-FORWARD OPEN**

- **v2 location**: L78
- **v3 location**: **L78 (UNCHANGED)**
- **v3 text** (verbatim, L78):
  > A recurring tension in the volatility-forecasting literature is the gap between in-sample statistical significance and out-of-sample economic value. \citet{conrad2020}'s GARCH-MIDAS application demonstrates that incorporating macro-economic information through long-run components can deliver in-sample fit improvements that fail to translate into forecast accuracy gains.
- **Issue (carried verbatim from v2 MED-1)**: Conrad-Kleen (2020) actually find that **some** macro variables (notably housing starts) **do** improve OOS forecasts at 2- and 3-month horizons; the paper is **not** a clean "in-sample-good-OOS-fail" cautionary tale, but rather a more nuanced "long-run regressor matters" message. Current §2.3 framing over-generalizes a paper-specific positive result into a cautionary citation.
- **Why v3 didn't fix it**: v2.3 hotfix scope was alphabetical re-order + §7 footnote; v2.4 rewrites targeted §1 contribution paragraph (L51) and §7/§8.3 narrative tightening but did NOT touch §2.3 paragraph 1; K1025b §6.4 added new subsection only.
- **Severity in v3**: **MED (unchanged)**. Still copy-edit-class — does not block stage upgrade. A careful methodology referee at JoE / IJF could still legitimately query the framing.
- **Suggested fix (carried from v2)**: Soften L78 to e.g.:
  > \citet{conrad2020} systematically evaluate which macro long-run components in GARCH-MIDAS specifications deliver out-of-sample improvements, finding that the in-sample-fit-to-OOS-accuracy mapping is variable-specific: housing starts deliver significant OOS gains at 2--3-month horizons, while several other macro components fail to translate in-sample fit into out-of-sample improvement.

### 3.2 v2 MIN-N1: `andrews1991` alphabetical position — **CLOSED in v2.3 hotfix** ✓

- **v2 issue**: Bibliography ordered Adrian → Andrews → Akyildirim, violating A-k < A-n APA sort.
- **v3 status**: Bibliography now ordered `\bibitem[Adrian and Brunnermeier, 2016]` (L408) → `\bibitem[Akyildirim et al., 2020]` (L414) → `\bibitem[Andrews, 1991]` (L420) → `\bibitem[Bouri et al., 2020]` (L426). ✓ APA-correct.
- **Verification**: `printf 'Adrian\nAkyildirim\nAndrews\n' | sort` → `Adrian\nAkyildirim\nAndrews` (matches main.tex order).

### 3.3 v2 MIN-2: `harvey2016` |t|>3 transfer footnote — **CARRY-FORWARD DEFERRED**

- **v3 location**: §1 L49 unchanged, §3.2.5 L170 unchanged, §7 L345 unchanged. No transfer footnote added.
- **Severity**: MINOR (defer-to-copy-edit). Acceptable.

### 3.4 v2 MIN-3: `iyer2022` policy-tier flag — **CARRY-FORWARD DEFERRED**

- **v3 location**: §2.2 L72 still labels Iyer "IMF policy note" — semantically clear.
- **Severity**: MINOR (defer; v1 said "NOT blocking"). Acceptable.

### 3.5 v2 MIN-4: `koenker1978` "Bassett, Jr." spelling — **CARRY-FORWARD DEFERRED**

- **v3 location**: L516–L520 — `Koenker, R. and Bassett, G. (1978)`. JStor canonical lists "Gilbert Bassett, Jr." for the 1978 Econometrica paper, but APA bibliography commonly drops the "Jr." suffix when no ambiguity arises.
- **Severity**: MINOR (cosmetic). Defer to copy-edit pass.

### 3.6 v2 MIN-5: §6.3 ETF cutoff date footnote — **CARRY-FORWARD DEFERRED**

- **v3 location**: L305 reads "we partition the 2023--2026 sample at 2024-01-11 (the ETF launch date)". Semantically correct (trading-launch is the relevant cutoff for microstructure tests). No SEC-approval-vs-launch-date footnote added.
- **Severity**: MINOR (footnote polish). Defer.

---

## 4. v3 Bibliography Health Audit (22 bibitems — unchanged from v2)

| # | Bib key | DOI present? | URL line correct? | Author/year/journal verified | v2→v3 byte change? |
|---|---|---|---|---|---|
| 1 | adrian2016 | ✓ 10.1257/aer.20120555 | ✓ | ✓ (Adrian-Brunnermeier AER 2016) | none |
| 2 | akyildirim2020 | ✓ 10.1016/j.frl.2019.06.010 | ✓ | ✓ (Akyildirim et al. FRL 2020) | none |
| 3 | andrews1991 | ✓ 10.2307/2938229 | ✓ | ✓ (Andrews Econometrica 1991, 59(3):817--858) | **alphabetically re-positioned (L420 from prior position)** |
| 4 | bouri2020 | ✓ 10.1016/j.qref.2020.03.004 | ✓ | ✓ | none |
| 5 | conlon2020 | ✓ 10.1016/j.frl.2020.101607 | ✓ | ✓ | none |
| 6 | conrad2020 | ✓ 10.1002/jae.2742 | ✓ | ✓ (JAE 2020 35(1):19--45) | none — content still over-claims (see §3.1) |
| 7 | corbet2018 | ✓ 10.1016/j.econlet.2018.01.004 | ✓ | ✓ (title + author order fixed v2.1) | none |
| 8 | diebold1995 | ✓ 10.1080/07350015.1995.10524599 | ✓ | ✓ | none |
| 9 | diebold2009 | ✓ 10.1111/j.1468-0297.2008.02208.x | ✓ | ✓ | none |
| 10 | diebold2012 | ✓ 10.1016/j.ijforecast.2011.02.006 | ✓ | ✓ | none |
| 11 | diebold2014network | ✓ 10.1016/j.jeconom.2014.04.012 | ✓ | ✓ | none |
| 12 | diks2006 | ✓ 10.1016/j.jedc.2005.08.008 | ✓ | ✓ | none |
| 13 | harvey1997 | ✓ 10.1016/S0169-2070(96)00719-4 | ✓ | ✓ | none |
| 14 | harvey2016 | ✓ 10.1093/rfs/hhv059 | ✓ | ✓ (RFS 2016 29(1):5--68) | none — newly cited in K1025b §6.4 Table 7 footnote (L334) but bibitem already present |
| 15 | hatemi2012 | ✓ 10.1007/s00181-011-0484-x | ✓ | ✓ | none |
| 16 | hong2001 | ✓ 10.1016/S0304-4076(01)00043-4 | ✓ | ✓ | none |
| 17 | iyer2022 | ✓ 10.5089/9781616358068.065 | ✓ | ✓ (IMF GFSN 2022/01) | none |
| 18 | klein2018 | ✓ 10.1016/j.irfa.2018.07.010 | ✓ | ✓ | none |
| 19 | koenker1978 | ✓ 10.2307/1913643 | ✓ | ✓ (Econometrica 1978 46(1):33--50) | none — "Bassett, Jr." cosmetic carry |
| 20 | matkovskyy2019 | ✓ 10.1016/j.frl.2019.04.007 | ✓ | ✓ | none |
| 21 | shahzad2019 | ✓ 10.1016/j.irfa.2019.01.002 | ✓ | ✓ | none |
| 22 | yarovaya2022 | ✓ 10.1016/j.intfin.2022.101589 | ✓ | ✓ | none |

**Result**: **22/22 entries DOI-complete. 22/22 alphabetically ordered. 0 orphan. 0 missing-from-bib in-text cite.**

---

## 5. §1, §6.4, §7, §8.3 Narrative Citation Consistency Audit

### 5.1 §1 contribution paragraph rewrite (v2.4, L51)

- **Cites used in rewritten paragraph**: `\citet{harvey2016}` (twice), `\citep{conrad2020}` (once)
- **Bibliography entries**: `harvey2016` L486–L490 ✓, `conrad2020` L438–L442 ✓
- **Surface consistency**: `\citet{harvey2016}` matches `\bibitem[Harvey et al., 2016]`. `\citep{conrad2020}` matches `\bibitem[Conrad and Kleen, 2020]`. ✓
- **Substance consistency**: §1 cites `harvey2016` for the "$|t| > 3$ threshold for newly proposed factors" — this matches Harvey-Liu-Zhu (2016) RFS exactly. §1 cites `conrad2020` for "when in-sample structure should and should not be expected to translate into point-forecast improvement" — this is **slightly less aggressive than the §2.3 framing** (it acknowledges the bidirectional mapping rather than asserting in-sample-good-OOS-fail), and is **acceptable as a parenthetical hand-off** to the §2.3 longer treatment. ✓ (No new MED issue introduced by v2.4 rewrite.)

### 5.2 §6.4 multi-asset NEW subsection (K1025b commit `6a41fc40`, L307–L338)

- **Cites used**: `\citet{harvey2016}` once (L334, in Table~\ref{tab:multiasset} footnote: "Both OOS DM specifications fail the \citet{harvey2016} $|t|>3$ threshold")
- **Bibliography entry**: `harvey2016` L486–L490 ✓
- **No new bibitems introduced**: ✓
- **Narrative-only treatment of NASDAQ-100 / VXN parallel**: The K1025b extension is framed as "methodological replication on a parallel asset pair" without invoking NASDAQ-specific predictability literature. See §6 below for whether this is acceptable.

### 5.3 §7 OOS narrative rewrite (v2.4, L345 + L369)

- **Cites used**: `\citet{harvey2016}` (L345), `\citet{diebold1995}` (L362, table footnote), `\citet{harvey1997}` (L362, table footnote), `\citet{conrad2020}` (L369, interpretation paragraph)
- **All 4 bibitems present**: ✓ (entries 6, 8, 13, 14 in §4 above)
- **Surface consistency**: All 4 cite-keys match bibitem labels. ✓
- **Substance consistency**: L345 cites `harvey2016` for the threshold (faithful). L362 cites `diebold1995` + `harvey1997` for the small-sample-adjusted DM test (faithful — Harvey-Leybourne-Newbold 1997 IJF is the canonical small-sample correction). L369 cites `conrad2020` for the methodological argument that "an in-sample slope that lives in the upper tail of the conditional VIX distribution and only during 1 of 5 subperiods is exactly the kind of sparse signal that fails to outperform a well-specified autoregression on average over a long OOS sample" — this is **a defensible reading of Conrad-Kleen** (the OOS-failure variables in their study are precisely the sparse / regime-conditional ones), and is **less over-generalized than the §2.3 L78 framing**. ✓ (Acceptable.)

### 5.4 §8.3 policy implications rewrite (v2.4, L389)

- **Cites used**: `\citet{iyer2022}`
- **Bibliography entry**: `iyer2022` L504–L508 ✓
- **Surface consistency**: ✓
- **Substance consistency**: L389 cites Iyer 2022 IMF GFSN for "policy recommendations focused on disclosure and concentration" — this is consistent with the IMF policy note's actual content (the Iyer 2022 GFSN does conclude with disclosure + concentration recommendations). ✓

---

## 6. Cross-Paper Meta-Evaluation: Should K1025b §6.4 cite NASDAQ-specific literature?

**Question (per parent task §6 new check dimension)**: §6.4 K1025b extension swaps SPY/VIX → QQQ/VXN but maintains narrative-only treatment. Should the subsection cite NASDAQ-100 / NDX momentum or factor-zoo literature, e.g.:
- Hong-Stein (1999) JF underreaction-to-information model
- Hou-Xue-Zhang (2020) RFS factor zoo / replication factors
- Hou-Xue-Zhang (2017) RFS q-factor model (NASDAQ-tilted)

**Verdict**: **NOT required for current narrative scope.** Justification:

1. **§6.4 is methodological replication, not new economic claim**: The subsection's contribution is "the four core building blocks (asymmetric Granger, QR, DY, DM) survive the SPY→QQQ / VIX→VXN swap with quantitatively similar magnitudes." This is a robustness statement about the BTC-equity fear channel, NOT a claim that NASDAQ-100 has different fear-transmission economics from S&P 500. Citing NASDAQ-specific predictability literature would be **scope-creep into a different paper's contribution**.

2. **Hong-Stein (1999) is about gradual-information-diffusion within equity markets**, not about cross-asset (crypto-to-equity) fear transmission. It would only be relevant if §6.4 invoked an underreaction mechanism specific to NASDAQ retail investors that differs from the §8.1 retail-fear mechanism for S&P 500 — which it does not.

3. **Hou-Xue-Zhang factor zoo is about cross-sectional return predictability**, not about volatility spillover. Different econometric object.

4. **The K1025b extension reuses the same Hatemi-J asymmetric-Granger / Koenker-Bassett QR / Diebold-Yilmaz / Diebold-Mariano machinery**, all four of which are already cited. The novelty is **the empirical replication on a parallel asset pair**, not a new methodological apparatus that would need new citations.

5. **Counterfactual check**: Were §6.4 to make a NASDAQ-tech-concentration *economic* claim (e.g., "the slightly higher upper-tail amplification ratio for VXN [11× vs 8.5× for VIX] reflects NASDAQ-100's tech-retail composition relative to S&P 500"), then a Hong-Stein 1999 or behavioral-finance citation would become appropriate. Current §6.4 L312 explicitly attributes the modest quantitative shift to "the empirical variation expected when changing from broad-market S\&P 500 to tech-concentrated NASDAQ-100 equity-fear gauges" without invoking a behavioral-finance mechanism — this **defensibly stays within robustness scope** and does not need additional cites.

**Recommendation**: K1025b §6.4 narrative-only treatment is **citation-complete as written**. If the paper's reviewer process at JoE / IJF / JBF requests deeper economic interpretation of the VIX-vs-VXN quantitative gap, the response would be (a) extending §8.1 retail-mechanism discussion with a NASDAQ-100 retail-tilt citation, or (b) adding a post-hoc footnote in §6.4 — neither of which is required for the current `ready_for_submission` upgrade decision.

**No new MINOR or MED issue arises from this audit dimension.**

---

## 7. Final v3 Verdict

| Severity | Count | Items | Blocks `ready_for_submission`? |
|---|---|---|---|
| **MAJOR** | **0** | — | NO |
| **MED** | **1** | v3 MED-1 (carry-forward from v2 MED-1): `conrad2020` §2.3 L78 framing partial overclaim — copy-edit-class softening | NO (defer to final copy-edit pass) |
| **MINOR** | **4** | v3 MIN-1 (carry-forward v2 MIN-2): `harvey2016` |t|>3 transfer footnote optional<br>v3 MIN-2 (carry-forward v2 MIN-3): `iyer2022` policy-tier flag deferred (§2.2 already labels)<br>v3 MIN-3 (carry-forward v2 MIN-4): `koenker1978` "Bassett, Jr." cosmetic<br>v3 MIN-4 (carry-forward v2 MIN-5): §6.3 L305 ETF cutoff footnote | NO (all defer-to-copy-edit) |

**Net v2→v3 progress**: 0 MAJOR / 1 MED / 5 MINOR → **0 MAJOR / 1 MED / 4 MINOR**. -1 MINOR (v2 MIN-N1 closed by v2.3 alphabetical fix).

**Citation quality verdict**: **PUBLICATION-READY (citation hygiene)**.

**Blocks `ready_for_submission` upgrade?** **NO.** The 4 commits between v2 and v3 introduced no new citations, no new bibitems, and no new citation-substance issues. The single carry-forward MED is copy-edit-class (one-sentence framing softening at L78) and does not require holding the paper at the current review stage. The 4 carry-forward MINORs are all defer-to-copy-edit.

**Recommended actions (non-blocking)**:
1. Soften L78 `conrad2020` framing — addresses v3 MED-1 (single-line edit).
2. Add §6.3 L305 ETF cutoff date footnote distinguishing SEC approval (2024-01-10) from trading launch (2024-01-11) — addresses v3 MIN-4 (single footnote).
3. `koenker1978` "Bassett, Jr." spelling — cosmetic, defer to journal-specific copy-edit pass.
4. `harvey2016` |t|>3 cross-sectional-to-time-series transfer footnote at L50 — optional, defer.

**v3 is ready for review-stage progression to `ready_for_submission`** modulo the above defer-to-copy-edit list. The cumulative v1→v3 trajectory (1 MAJOR / 5 MED / 7 MINOR → 0 MAJOR / 1 MED / 4 MINOR) demonstrates citation hygiene has converged below the per-issue blocking threshold.

---

*End of citation_check_report.md v3*
