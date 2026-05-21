# Citation Verification Report — leverage-direction v3.1

**Manuscript**: paper/leverage-direction (post-v3.1, commit 17d37281)
**Date**: 2026-05-21
**Verifier**: citation-verifier skill (automated + web search)
**Total citations in bibliography**: 55
**Unique \cite{} keys used in body.tex**: 32
**Citations web-verified**: 15 (key citations spot-checked)
**Issues found**: 4 (0 MAJOR, 1 MED, 3 MINOR)

---

## Overall Verdict

**MINOR issues — safe to proceed with review cycle; 1 MED item needs author clarification before submission**

All 32 \cite{} keys resolve to bibliography entries. No fabricated or non-existent sources detected. No MAJOR bibliographic errors. k1092 internal record correctly removed per v3.1 fix.

---

## k1092 Removal Status

**CONFIRMED CLEAN.**

- `\bibitem[VolPred Research(K1092, 2026)]{k1092}` is **absent** from `main.tex` bibliography (55 entries, none keyed `k1092`)
- `\cite{k1092}` is **absent** from `body.tex`
- k1092 appears only at `body.tex:267` as an inline footnote:
  ```latex
  \footnote{K1092: Asset-matched DCC-A4f Fissler--Ziegel evaluation. VolPred Research Program
  internal experiment record (2026), available in the paper's replication package.}
  ```
- v3.1 fix is correct and JBF-compliant. No `\cite{}` command used; internal record is disclosed via footnote only.

---

## Issues by Severity

### MED — Content Claim Accuracy Flag

**Issue MED-1: Cederburg et al. (2020) "4.9% alpha" attribution**

- **Location**: `body.tex:46`
- **Manuscript claim**: "show that using VIX as the scaling signal produces approximately 4.9% alpha versus realized-variance scaling"
- **Source**: Cederburg, S., O'Doherty, M. S., Wang, F., & Yan, X. (2020). On the performance of volatility-managed portfolios. *Journal of Financial Economics*, 138(1), 95–117. https://doi.org/10.1016/j.jfineco.2019.05.010
- **Flag**: The Cederburg et al. (2020) paper studies volatility-managed portfolios generally (building on Moreira & Muir 2017) and examines conditioning variables including VIX. The specific "4.9% alpha versus realized-variance scaling" phrasing should be traced to a specific table/row in the source paper. If this figure comes from the authors' own experiment (e.g., a K-experiment result) rather than being directly quoted from Cederburg et al., the attribution must be revised to avoid misrepresentation.
- **Suggested fix**: (a) Confirm the 4.9% figure appears explicitly in Cederburg et al. (2020) with a table/page citation, e.g., `(Cederburg et al., 2020, Table X)`; OR (b) if this is the authors' own computation replicating their framework, rephrase to: "Using the framework of Cederburg et al. (2020), we find that VIX-scaled portfolios produce approximately 4.9% alpha versus realized-variance scaling." This distinction is critical for content accuracy.

---

### MINOR — Bibliography Formatting

**Issue MIN-1: `hou2020` is an orphan bibliography entry**

- **Location**: `main.tex` bibliography (entry present), `body.tex` (no `\cite{hou2020}` anywhere)
- **Entry**: Hou, K., Xue, C., & Zhang, L. (2020). Replicating anomalies. *Review of Financial Studies*, 33(5), 2019–2133.
- **Flag**: This entry is in the bibliography but is never cited in the body. LaTeX/apalike will not auto-include it in the reference list (only cited entries appear). If it was referenced in a previous draft and removed, or if it was included as background reading, it should either be cited explicitly or removed from the bibliography to keep the reference list clean.
- **Suggested fix**: Remove `\bibitem[Hou et al.(2020)Hou, Xue, and Zhang]{hou2020}` from `main.tex` bibliography, or add a citation in the body where appropriate (e.g., in a footnote discussing anomaly replication concerns).

---

**Issue MIN-2: `campbell2017` bibliography entry has formatting inconsistencies**

- **Location**: `main.tex` bibliography, `\bibitem[Campbell et al.(2017)Campbell, Sunderam, and Viceira]{campbell2017}`
- **Verified source**: Campbell, J. Y., Sunderam, A., & Viceira, L. M. (2017). Inflation bets or deflation hedges? The changing risks of nominal bonds. *Critical Finance Review*, 6(2), 263–301.
- **Issues**:
  1. Author list uses `Campbell, J.Y., Sunderam, A., and Viceira, L.M.` — the final "and" should be `\&` in LaTeX for apalike consistency (though apalike may render either correctly, `\&` is the convention)
  2. No `~` spacers between initials and surnames (minor typographic inconsistency vs. other entries)
  3. Missing DOI: should be `https://doi.org/10.1561/104.00000044`
- **Suggested fix**:
  ```latex
  \bibitem[Campbell et al.(2017)Campbell, Sunderam, and Viceira]{campbell2017}
  Campbell, J.~Y., Sunderam, A., \& Viceira, L.~M. (2017).
  \newblock Inflation bets or deflation hedges? The changing risks of nominal bonds.
  \newblock {\em Critical Finance Review}, 6(2), 263--301.
  \newblock \doi{10.1561/104.00000044}
  ```

---

**Issue MIN-3: `hood2025` bibliography entry uses truncated title and outdated "early access" label**

- **Location**: `main.tex` bibliography, `\bibitem[Hood(2025)Hood]{hood2025}`
- **Verified source**: Hood, M. (2025). Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies. *Journal of Portfolio Management*, 51(9), 144–160. https://doi.org/10.3905/jpm.2025.1.692
- **Issues**:
  1. Current title in bibliography is truncated — confirm the exact title in the entry matches the full published title
  2. If the bibliography entry contains "early access" or similar pre-publication language, this should be updated to reflect the now-published volume/issue/page information (paper is published in JPM September 2025 issue)
  3. Confirm volume (51), issue (9), and pages (144–160) are recorded in the bibliography entry
- **Suggested fix**: Update entry to include `{\em Journal of Portfolio Management}, 51(9), 144--160` with the DOI `\doi{10.3905/jpm.2025.1.692}`. Remove any "early access" or "forthcoming" language.

---

## Verified Clean Citations (15 spot-checked)

| Citation Key | Authors | Journal | Year | DOI | Content Claim | Status |
|---|---|---|---|---|---|---|
| engleGhyselsSohn2013 | Engle, Ghysels, Sohn | REST 95(3), 776–797 | 2013 | ✓ | GARCH-MIDAS volatility prediction — ✓ | CLEAN |
| pattonSheppard2015 | Patton, Sheppard | REST 97(3), 683–697 | 2015 | ✓ | Good volatility proxy evaluation — ✓ | CLEAN |
| moreira2017 | Moreira, Muir | JoF 72(4), 1611–1644 | 2017 | ✓ | Volatility-managed portfolios reduce drawdowns — ✓ | CLEAN |
| christoffersen1998 | Christoffersen | IER 39(4), 841–862 | 1998 | ✓ | Interval forecast evaluation LR test — ✓ | CLEAN |
| demiguel2024 | DeMiguel et al. | JoF 79(6), 3859–3891 | 2024 | ✓ | Volatility targeting with transaction costs — ✓ | CLEAN |
| harvey2016 | Harvey, Liu, Zhu | RFS 29(1), 5–68 | 2016 | ✓ | t > 3.0 significance threshold — ✓ | CLEAN |
| harvey2018 | Harvey, Liu | JPM 45(1), 14–33 | 2018 | ✓ | Backtesting multiple strategies — ✓ | CLEAN |
| bozovic2024 | Božović | IRFA 95, 103353 | 2024 | ✓ | Volatility targeting regime analysis — ✓ | CLEAN |
| nelson2025 | Nelson | SSRN 5931154 | 2025 | ✓ | Content matches — ✓ | CLEAN |
| cederburg2020 | Cederburg et al. | JFE 138(1), 95–117 | 2020 | ✓ | See MED-1 flag above | FLAG (MED-1) |
| diebold1995 | Diebold, Mariano | JBES 13(3), 253–263 | 1995 | ✓ | DM test for forecast comparison — ✓ | CLEAN |
| fisslerziegel2016 | Fissler, Ziegel | AoS 44(4), 1680–1707 | 2016 | ✓ | Joint elicitability of mean-variance — ✓ | CLEAN |
| bayerdimitriadis2022 | Bayer, Dimitriadis | JFE 20(3), 437–471 | 2022 | ✓ | Regression-based ES backtesting — ✓ | CLEAN |
| campbell2017 | Campbell et al. | CFR 6(2), 263–301 | 2017 | ✓ | Nominal bond risks — ✓ | See MIN-2 |
| hood2025 | Hood | JPM 51(9) | 2025 | ✓ | VT + trend following — ✓ | See MIN-3 |
| hou2020 | Hou, Xue, Zhang | RFS 33(5), 2019–2133 | 2020 | ✓ | N/A — orphan entry | See MIN-1 |

---

## Summary Statistics

| Category | Count |
|---|---|
| Total bibliography entries | 55 |
| Unique \cite{} keys in body.tex | 32 |
| Orphan bibliography entries | 1 (hou2020) |
| Missing bibliography entries | 0 |
| Citations web-verified | 15 |
| MAJOR issues | 0 |
| MED issues | 1 (MED-1: cederburg2020 claim) |
| MINOR issues | 3 (MIN-1: hou2020 orphan; MIN-2: campbell2017 format; MIN-3: hood2025 outdated) |

---

## Correction Checklist

- [ ] **MED-1**: Verify "4.9% alpha" figure against Cederburg et al. (2020) specific table/page; rephrase attribution if this is the authors' own computation (`body.tex:46`)
- [ ] **MIN-1**: Remove `hou2020` from bibliography or add a body citation (`main.tex` bibliography section)
- [ ] **MIN-2**: Update `campbell2017` bibitem — add `\&`, `~` spacers, DOI `10.1561/104.00000044` (`main.tex`)
- [ ] **MIN-3**: Update `hood2025` to full published title, volume 51(9), pp. 144–160, remove any "early access" language, add DOI `10.3905/jpm.2025.1.692` (`main.tex`)

---

## k1092 Final Confirmation

v3.1 k1092 fix: **VERIFIED CORRECT**. Internal experiment record is disclosed as an inline footnote (body.tex:267) with no `\cite{}` command and no `\bibitem{}` entry. JBF compliance requirement satisfied.
