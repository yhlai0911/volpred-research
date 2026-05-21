# Citation Verification Report — leverage-direction v6

**Target paper:** `paper/leverage-direction/body.tex` + `main.tex` bibliography
**Review date:** 2026-05-22
**Reviewer:** citation-verifier skill (agent a36e2722ca8e151b0)
**Scope:** APA 7th format, DOI accuracy, author attribution, content-claim accuracy against primary sources

---

## Summary Table

| Severity | Count | Citations Affected |
|----------|-------|--------------------|
| MAJOR    | 0     | —                  |
| MED      | 2     | cederburg2020, hood2025 |
| MINOR    | 4     | nelson2025/nelson1991, campbell2017, pattonSheppard2015, black1976 |
| VERIFIED | 15    | (see Section 3) |

**Verdict: ⚠️ 0 MAJOR / 2 MED / 4 MINOR — requires MED fixes before submission**

---

## Section 1 — MED Issues

### MED-1: `cederburg2020` — Content framing is one-sided (Confidence: 88)

**File / Line:** `body.tex` line 45

**What the manuscript says:**
> `\citet{cederburg2020}` show that using VIX as the scaling signal produces substantially higher alpha versus realized-variance scaling in their equity-portfolio setting. [Footnote notes "exact figures are Table-specific…"]

**Problem:** Cederburg, O'Doherty, Wang & Yan (2020, JFE 138(1), 95–117) is a broadly **negative** paper on VT. Primary finding across 103 equity strategies: VT portfolios do **not** systematically earn higher Sharpe ratios than unmanaged counterparts. Line 45 lifts a specific secondary sub-result (VIX scaling outperforms RV scaling within a narrow specification) and presents it without the paper's overarching skeptical framing. A reader unfamiliar with the paper would infer Cederburg et al. endorse VIX-based VT — the opposite of the headline conclusion.

**Suggested fix:**
> "Within their comprehensive multi-strategy evaluation, \citet{cederburg2020} find that VIX scaling generates substantially higher alpha than realized-variance scaling for a subset of equity strategies, though they conclude that VT does not systematically outperform unmanaged portfolios across their broader sample of 103 strategies."

Alternatively add a footnote clause: "Note that Cederburg et al.'s (2020) headline finding is negative: VT does not systematically improve Sharpe ratios across their full 103-strategy sample; the VIX-vs-RV comparison is a secondary within-paper finding."

---

### MED-2: `hood2025` — Missing subtitle in bibliography entry (Confidence: 87)

**File / Line:** `main.tex` line 180–181

**Current bibliography:**
```
Hood, B., & Raughtigan, C. (2025). Volatility targeting is trendy.
Journal of Portfolio Management, early access.
https://doi.org/10.3905/jpm.2025.1.764
```

**Verified full title** (PM Research publisher page + SSRN 4773781):
"Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies"

**Problem:** APA 7th requires full title including subtitle. The subtitle "How Trend Following Explains Alpha in Volatility-Managed Strategies" is substantively relevant to the paper's core argument about trend-following and leverage direction.

**Suggested fix:**
```latex
\bibitem[Hood and Raughtigan(2025)]{hood2025}
Hood, B., \& Raughtigan, C. (2025). Volatility targeting is trendy:
How trend following explains alpha in volatility-managed strategies.
\textit{Journal of Portfolio Management}, early access.
https://doi.org/10.3905/jpm.2025.1.764
```

Note: "early access" status — verify if final pagination is now available for Vol/issue/pages.

---

## Section 2 — MINOR Issues

### MINOR-1: `nelson2025` / `nelson1991` — Missing author disambiguation (Confidence: 82)

**File / Line:** `main.tex` (two bibitem entries)

**Problem:** Two "Nelson" authors without first-initial disambiguation:
- `{nelson1991}` — Nelson, D.B. (1991, EGARCH, Econometrica)
- `{nelson2025}` — Nelson, R. (2025, tail risk SSRN)

APA 7th requires disambiguation when two authors share surname. In-text `\citep{nelson2025}` renders as "(Nelson, 2025)" — ambiguous.

**Suggested fix:** Add first-initial to 2025 bibitem label: `[Nelson R.(2025)]`

---

### MINOR-2: `campbell2017` — Bibitem label style + alphabetical order (Confidence: 80)

**File / Line:** `main.tex` line 231

**Problem:** Bibitem uses `[Campbell et~al.(2017)]` while other entries use varying tilde conventions. Also placed after `[Xu(2024)]` — breaks strict alphabetical order (C should precede X).

**Suggested fix:** Move to alphabetically correct position (after `bucci2020`, before `cederburg2020`); standardize label to `[Campbell et al.(2017)]`.

---

### MINOR-3: `pattonSheppard2015` — Issue number secondary-database ambiguity (Confidence: 80)

**Assessment:** Bibliography states `97(3)` — this is the **correct** publisher-authoritative (MIT Press, REST) issue number. IDEAS/EconPapers secondary database lists issue 2, which is incorrect. No correction needed.

---

### MINOR-4: `black1976` — Title variant (Confidence: 80)

**Assessment:** Current entry "Studies of stock price volatility changes" vs database variant "Studies of Stock Market Volatility Changes" — longstanding inconsistency in the literature for this conference proceedings paper. Neither definitively wrong. Current entry acceptable.

---

## Section 3 — Verified Citations (15/15 Confirmed)

| Key | Authors | Year | Venue | DOI | Content Claim | Status |
|-----|---------|------|-------|-----|--------------|--------|
| hansen2011 | Hansen, Lunde, Nason | 2011 | Econometrica 79(2) 453–497 | 10.3982/ECTA5771 | MCS procedure (body.tex line 367) | ✅ VERIFIED |
| hansen2005 | Hansen, Lunde | 2005 | JAE 20(7) 873–889 | 10.1002/jae.800 | 330-model comparison & 252-day OOS | ✅ VERIFIED |
| patton2011 | Patton | 2011 | JoE 160(1) 246–256 | 10.1016/j.jeconom.2010.03.034 | Proxy-robust QLIKE | ✅ VERIFIED |
| engle2018 | Engle, Siriwardane | 2018 | RFS 31(2) 449–492 | 10.1093/rfs/hhx099 | Structural GARCH leverage multiplier | ✅ VERIFIED |
| engleGhyselsSohn2013 | Engle, Ghysels, Sohn | 2013 | REST 95(3) 776–797 | 10.1162/REST_a_00300 | GARCH-MIDAS | ✅ VERIFIED |
| pattonSheppard2015 | Patton, Sheppard | 2015 | REST 97(3) 683–697 | 10.1162/REST_a_00503 | Realized negative semivariance | ✅ VERIFIED |
| bollerslev1986 | Bollerslev | 1986 | JoE 31(3) 307–327 | 10.1016/0304-4076(86)90063-1 | GARCH | ✅ VERIFIED |
| nelson1991 | Nelson, D.B. | 1991 | Econometrica 59(2) 347–370 | 10.2307/2938260 | EGARCH | ✅ VERIFIED |
| glosten1993 | Glosten, Jagannathan, Runkle | 1993 | JoF 48(5) 1779–1801 | 10.1111/j.1540-6261.1993.tb05128.x | GJR-GARCH | ✅ VERIFIED |
| christie1982 | Christie | 1982 | JFE 10(4) 407–432 | 10.1016/0304-405X(82)90018-6 | Leverage effect mechanism | ✅ VERIFIED |
| hwang2006 | Hwang, Valls Pereira | 2006 | EJF 12(6–7) 473–494 | 10.1080/13518470500039436 | Small-sample GARCH persistence | ✅ VERIFIED |
| francq2004 | Francq, Zakoïan | 2004 | Bernoulli 10(4) 605–637 | 10.3150/bj/1093265632 | QMLE consistency | ✅ VERIFIED |
| chevallier2017 | Chevallier, Ielpo | 2017 | RIBAF 39, 763–778 | 10.1016/j.ribaf.2014.09.010 | Inverted leverage in commodities | ✅ VERIFIED |
| hood2025 | Hood, Raughtigan | 2025 | JPM early access | 10.3905/jpm.2025.1.764 | Content (trend-VT alpha mechanism) correct; title incomplete — see MED-2 | ✅ (content) |
| demiguel2024 | DeMiguel, Martin-Utrera, Uppal | 2024 | JoF 79(6) 3859–3891 | 10.1111/jofi.13395 | Multifactor reframing, in-sample Sharpe attenuation | ✅ VERIFIED |

---

## Correction Checklist for v7

- [ ] **MED-1** (`body.tex` line 45): Reframe cederburg2020 sentence to include its negative headline conclusion across 103 strategies
- [ ] **MED-2** (`main.tex` line 181): Add full subtitle to hood2025 bibitem; verify if final pagination available
- [ ] **MINOR-1** (`main.tex`): Add `R.` disambiguation to nelson2025 bibitem label
- [ ] **MINOR-2** (`main.tex`): Move campbell2017 bibitem to correct alphabetical position
- [ ] **MINOR-3**: No change needed (pattonSheppard2015 issue 3 is correct)
- [ ] **MINOR-4**: No change needed (black1976 title variant acceptable)
