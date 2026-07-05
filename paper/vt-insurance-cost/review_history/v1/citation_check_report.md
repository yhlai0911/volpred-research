# Citation Verification Report

**稿件**: `paper/vt-insurance-cost/main.tex`  
**日期**: 2026-07-05  
**範圍**: natbib inline `\bibitem` references, DOI/web-search verification, high-risk cited-claim verification  
**引用總數**: 17 unique citation keys  
**Bibitem 總數**: 17  

---

## 總覽

| Severity | Count | 說明 |
|---|---:|---|
| MAJOR | 1 | 影響正文關鍵假設或 claim 的 citation 支撐 |
| MEDIUM | 8 | DOI/APA 缺漏、年份/來源不一致、claim 過度延伸 |
| minor | 2 | source-code key 或措辭層級問題 |

**Overall verdict**: ⚠️ 需修。  
沒有 undefined/orphan reference，但目前 bibliography 不符合 APA 7/DOI 完整性要求，且數個正文 claim 對 cited source 的支撐過度精確或超出原文範圍。建議修完 MAJOR + MEDIUM 後再進投稿版。

---

## Undefined / Orphan Reference

| Check | Result |
|---|---|
| 正文 cite 但 bibliography 未定義 | 無 |
| bibliography 定義但正文未 cite | 無 |

機械比對結果:

- Cited keys: `barroso2015`, `bekaert2014`, `bollerslev2009`, `bongaerts2020`, `booth1992`, `cboe2014`, `cederburg2020`, `fleming2001`, `harvey2016`, `harvey2018`, `hasbrouck2009`, `hocquard2013`, `huang2015`, `liu2019`, `moreira2017`, `perchet2016`, `todorov2010`
- Bibitem keys: same set

---

## 問題清單

### I-01. `all_journal_articles` - MEDIUM

**問題**: 目前 reference list 是手寫 journal style，不是 APA 7。所有 DOI-bearing journal articles 都缺 DOI；多數也缺 issue number。這不一定會造成 natbib 編譯錯，但投稿前的引用格式不合格，且 DOI correctness 無法從 manuscript 直接驗證。  

**Affected keys**: `barroso2015`, `bollerslev2009`, `bekaert2014`, `bongaerts2020`, `todorov2010`, `booth1992`, `cederburg2020`, `fleming2001`, `harvey2016`, `hasbrouck2009`, `harvey2018`, `hocquard2013`, `huang2015`, `liu2019`, `moreira2017`, `perchet2016`

**Suggested fix**: 加上 issue number 與 DOI URL，或改用 `.bib` + APA-compatible bibliography style。已查到的 DOI:

| Key | Verified DOI |
|---|---|
| `barroso2015` | `https://doi.org/10.1016/j.jfineco.2014.11.010` |
| `bollerslev2009` | `https://doi.org/10.1093/rfs/hhp008` |
| `bekaert2014` | `https://doi.org/10.1016/j.jeconom.2014.05.008` |
| `bongaerts2020` | `https://doi.org/10.1080/0015198X.2020.1790853` |
| `todorov2010` | `https://doi.org/10.1093/rfs/hhp035` |
| `booth1992` | `https://doi.org/10.2469/faj.v48.n3.26` |
| `cederburg2020` | `https://doi.org/10.1016/j.jfineco.2020.04.015` |
| `fleming2001` | `https://doi.org/10.1111/0022-1082.00327` |
| `harvey2016` | `https://doi.org/10.1093/rfs/hhv059` |
| `hasbrouck2009` | `https://doi.org/10.1111/j.1540-6261.2009.01469.x` |
| `harvey2018` | `https://doi.org/10.3905/jpm.2018.45.1.014` |
| `hocquard2013` | `https://doi.org/10.3905/jpm.2013.39.2.028` |
| `huang2015` | `https://doi.org/10.1017/S0022109018001436` |
| `liu2019` | `https://doi.org/10.3905/jpm.2019.1.107` |
| `moreira2017` | `https://doi.org/10.1111/jofi.12513` |
| `perchet2016` | `https://doi.org/10.3905/jai.2016.18.3.021` |

---

### I-02. `hasbrouck2009` - MAJOR

**Location**: line 108  

**Manuscript claim**: 5 bps transaction cost exceeds "SPY's typical bid-ask spread of 1--2 bps" with citation to Hasbrouck (2009).  

**問題**: Hasbrouck (2009) is a general methodology paper estimating effective costs from daily CRSP U.S. equity data. It verifies the broad concept of effective trading cost estimation, but it does not directly establish a current, precise 1--2 bps typical bid-ask spread for SPY. This citation is used to justify the paper's core transaction-cost assumption, so the mismatch matters. Web search also surfaced more direct but non-academic SPY liquidity material and later transaction-cost papers; Hasbrouck alone is not enough for this precise SPY claim.

**Suggested fix**:

- Best: compute SPY quoted/effective spread directly from TAQ/NBBO or another reproducible quote dataset for the sample window and cite that calculation.
- If using an external source, cite a direct SPY/ETF liquidity source rather than Hasbrouck alone.
- Rephrase to: "We set transaction costs at 5 bps per leg, a conservative assumption relative to the observed liquidity of SPY; direct-cost sensitivity is reported at 1 bps." Then cite the actual quote-data source or move the 1 bps value to an internal data appendix.

---

### I-03. `perchet2016` - MEDIUM

**Location**: line 70  

**Manuscript claim**: "We use the 12/VIX rule `\citep{perchet2016}`: `w_t = min(12/VIX_{t-1}, 1)`."

**問題**: Perchet et al. study volatility targeting strategies and target-volatility mechanics, but the web-verified metadata and accessible snippets do not establish the exact `12/VIX` implementation as a named rule from that paper. The precise formula appears to be the manuscript's implementation of a 12% annual volatility target using VIX as the forecast, not necessarily Perchet et al.'s specific rule.

**Suggested fix**: Reword attribution:

> Following the target-volatility convention studied by Perchet et al. (2016), we implement a 12% annual target using lagged VIX as the volatility forecast: ...

If there is a specific source for the `12/VIX` rule, add that source or a page/equation reference.

---

### I-04. `perchet2016` - MEDIUM

**Location**: lines 274-275  

**問題**: The bibliography displays `Perchet et al.(2015)` and year `2015`, but PM Research lists the article in *Journal of Alternative Investments* 18(3), Winter 2016, DOI `10.3905/jai.2016.18.3.021`. Some secondary sources cite 2015, but the official issue/DOI metadata points to 2016. The internal key already says `perchet2016`.

**Suggested fix**: Change visible label and year to 2016:

```tex
\bibitem[Perchet et al.(2016)]{perchet2016}
Perchet, R., de~Carvalho, R.L., Heckel, T., Moulin, P., 2016. ...
```

---

### I-05. `cboe2014` - MEDIUM

**Location**: lines 93, 241-242  

**問題**: I could not verify an official 2014 CBOE white paper with the exact title "CBOE VVIX Index: Measuring the volatility of volatility." CBOE's accessible official document is "Double the Fun with CBOE's VVIX Index" from 2012, and the current Cboe dashboard describes VVIX as expected volatility of VIX. The content claim that VVIX is a CBOE volatility-of-volatility index is correct, but the reference metadata appears unreliable or misdated.

**Suggested fix**: Replace with a verifiable CBOE source:

```tex
\bibitem[CBOE(2012)]{cboe2012}
CBOE, 2012. Double the fun with CBOE's VVIX Index. Chicago Board Options Exchange.
\url{https://cdn.cboe.com/resources/indices/documents/vvix-termstructure.pdf}
```

Optionally add the current dashboard URL: `https://www.cboe.com/us/indices/dashboard/vvix/`.

---

### I-06. `harvey2018` - MEDIUM

**Location**: line 56  

**Manuscript claim**: Harvey et al. "prominently report turnover metrics as a key performance drag."

**問題**: The verified abstract and accessible text for Harvey et al. (2018) emphasize Sharpe-ratio effects for risk assets and, more generally, lower likelihood of extreme/left-tail returns. Search found a statement that volatility scaling can have lower turnover than time-series momentum, but not support that Harvey et al. make turnover a key performance drag. This claim is currently too strong.

**Suggested fix**:

- If the intended point is tail-risk reduction, cite Harvey et al. (2018) only for that.
- If the intended point is transaction costs/turnover drag, cite a source that directly studies implementation costs of volatility-managed portfolios, or change the sentence to: "Harvey et al. (2018) report implementation and turnover-related metrics, while Cederburg et al. (2020) document poor out-of-sample performance..."

---

### I-07. `harvey2016` - MEDIUM

**Location**: lines 195-196  

**Manuscript claim**: Apply Harvey et al. (2016) `|t| > 3.0` threshold to DM test statistics.

**問題**: Harvey, Liu, and Zhu (2016) propose a multiple-testing hurdle for newly discovered factors in the cross-section of expected returns. The manuscript applies the threshold to pairwise strategy DM tests. This is conservative, but not a standard DM-test critical value and not exactly the setting of the cited paper.

**Suggested fix**: Make the scope explicit:

> As a conservative multiple-testing heuristic inspired by Harvey et al. (2016), we also report whether `|t| > 3.0`; formal pairwise inference is based on the DM/HAC statistic.

For a formal data-snooping/multiple-model comparison standard, add White Reality Check, Hansen SPA, Romano-Wolf, or a bootstrap model-comparison reference.

---

### I-08. `liu2019` - MEDIUM

**Location**: line 207  

**Manuscript claim**: Liu et al. find that VT "destroys value in smooth sailing environments."

**問題**: The phrase is no longer quoted, which is good, but the verb "destroys" is still stronger than the verified source metadata supports. Liu, Tang, and Zhou (2019) question whether volatility-managed portfolios really work and are commonly summarized as finding benefits concentrated in crisis/high-volatility states. The current sentence turns that into a broad value-destruction claim for low-VoV regimes.

**Suggested fix**:

> ...consistent with Liu et al. (2019), who find that volatility management does not consistently improve performance outside the states where volatility timing is most valuable.

If the manuscript wants to say "destroys value", cite the exact table/result from Liu et al. or use the paper's own evidence instead of attributing it to Liu et al.

---

### I-09. `fleming2001` - MEDIUM

**Location**: line 54  

**Manuscript claim**: Fleming et al. (2001), together with Hocquard et al. (2013), confirms VT's ability to compress the return distribution, particularly in the left tail.

**問題**: Hocquard et al. and Harvey et al. directly support tail-risk/left-tail reduction. Fleming et al. (2001) is correctly cited for the economic value of volatility timing, but web-verified metadata does not show it as a direct left-tail compression paper. The current combined citation over-attributes a left-tail distribution claim to Fleming.

**Suggested fix**:

> Fleming et al. (2001) establish the economic value of volatility timing, while Harvey et al. (2018) and Hocquard et al. (2013) document thinner tails and drawdown/tail-risk mitigation.

---

### I-10. `moreira2017` - minor

**Location**: line 54  

**問題**: "formalized by Moreira and Muir" is mostly acceptable as an influential modern formulation of volatility-managed portfolios, but it can read as a priority claim. Volatility timing predates Moreira and Muir, including Fleming et al. (2001).  

**Suggested fix**: Change "formalized by" to "in the influential formulation of" or "popularized in modern asset-pricing form by".

---

### I-11. `huang2015` - minor

**Location**: lines 265-266  

**問題**: The visible citation is correct as Huang et al. (2019), but the internal key remains `huang2015`. This will not affect compiled output, but it is source-code misleading and can cause future citation mistakes.

**Suggested fix**: Rename key to `huang2019` in both cite and bibitem.

---

## Web-Search Verified Key Claims

| Claim / reference | Verification result | Conclusion |
|---|---|---|
| Moreira and Muir (2017): volatility-managed portfolios scale exposure inversely to recent volatility | Wiley/JSTOR/author PDF metadata confirms the paper's strategy increases exposure after low volatility and reduces it after high volatility. | Supported, but soften "formalized" priority language. |
| Harvey et al. (2018): VT reduces tail/extreme return risk | SSRN/PM Research/Duke PDF metadata state that volatility targeting reduces likelihood of extreme returns and lessens left-tail events across assets. | Supported. |
| Harvey et al. (2018): turnover metrics are a key performance drag | Search did not verify this as a headline Harvey et al. claim; available text emphasizes tail risk and Sharpe effects. | Not sufficiently supported; revise or cite another source. |
| Cederburg et al. (2020): poor OOS performance across 103 strategies | ScienceDirect abstract confirms 103 equity strategies and poor OOS versions with lower CER/Sharpe, driven by structural instability. | Supported. |
| Bongaerts et al. (2020): conditional VT conditions on volatility states | SSRN/Taylor & Francis metadata confirm conditional VT adjusts exposure in high/low volatility states and aims to improve Sharpe ratios. | Supported. |
| Perchet et al. (2016): exact `12/VIX` rule | Verified as a target-volatility/volatility-targeting article, but exact `12/VIX` rule was not verified from web-search snippets. | Partially supported only; rephrase implementation attribution. |
| CBOE VVIX citation | Official Cboe dashboard and 2012 VVIX white paper support VVIX as expected volatility of VIX; exact 2014 title was not verified. | Content supported; bibliographic entry should be replaced. |
| Hasbrouck (2009): SPY bid-ask spread 1--2 bps | DOI and metadata verified for a general U.S. equities effective-cost estimation paper; not a direct source for precise SPY 1--2 bps. | Not sufficiently supported; use direct quote-data or SPY liquidity source. |
| Booth and Fama (1992): diversification/rebalancing return mechanism | CFA/Taylor metadata confirm "Diversification Returns and Asset Contributions." | Supported for theoretical diversification-return framing. |
| Harvey et al. (2016): `t > 3.0` hurdle | Oxford abstract confirms a higher multiple-testing hurdle and specifically mentions t-statistic greater than 3.0 for new factors. | Supported as factor-discovery heuristic, not formal DM-test critical value. |
| Liu et al. (2019): VT destroys value in smooth sailing environments | DOI/metadata confirm article questioning whether volatility-managed portfolios work; exact "destroys value" claim not verified. | Overstated; soften. |
| Huang et al. (2019), Bollerslev et al. (2009), Todorov (2010), Bekaert and Hoerova (2014): broader VoV / variance-risk-premium literature | Publisher/RePEc/Cambridge/Oxford metadata support these as volatility/variance risk premium and volatility-of-volatility sources. | Supported. |

---

## DOI / Publication Detail Verification Notes

Selected authoritative sources checked:

- Moreira and Muir (2017), Wiley DOI page: `https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513`
- Harvey et al. (2018), PM Research DOI page: `https://www.pm-research.com/content/iijpormgmt/45/1/14`
- Cederburg et al. (2020), ScienceDirect: `https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X`
- Bongaerts et al. (2020), Taylor & Francis: `https://www.tandfonline.com/doi/full/10.1080/0015198X.2020.1790853`
- Barroso and Santa-Clara (2015), ScienceDirect: `https://www.sciencedirect.com/science/article/abs/pii/S0304405X14002566`
- Bollerslev et al. (2009), Oxford/RFS: `https://academic.oup.com/rfs/article-abstract/22/11/4463/1565787`
- Bekaert and Hoerova (2014), ScienceDirect/RePEc: `https://ideas.repec.org/a/eee/econom/v183y2014i2p181-192.html`
- Todorov (2010), Oxford/RFS: `https://academic.oup.com/rfs/article-abstract/23/1/345/1578053`
- Harvey, Liu, and Zhu (2016), Oxford/RFS: `https://academic.oup.com/rfs/article/29/1/5/1843824`
- Huang et al. (2019), Cambridge Core: `https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/volatilityofvolatility-risk/9D8ABBDE874D8259A5176FA455C674B7`
- CBOE VVIX official dashboard: `https://www.cboe.com/us/indices/dashboard/vvix/`
- CBOE 2012 VVIX white paper: `https://cdn.cboe.com/resources/indices/documents/vvix-termstructure.pdf`
- Perchet et al. (2016), PM Research: `https://www.pm-research.com/content/iijaltinv/18/3/21`

---

## 修正優先順序

1. Fix `hasbrouck2009` SPY spread support or compute spread directly.
2. Add DOI + issue numbers for all DOI-bearing journal references.
3. Replace `cboe2014` with verifiable CBOE 2012/current URL metadata.
4. Fix `perchet2016` visible year and soften exact `12/VIX` attribution.
5. Revise over-strong cited claims: `harvey2018` turnover drag, `harvey2016` DM threshold scope, `liu2019` value destruction, `fleming2001` left-tail attribution.
6. Clean minor source-code keys/wording: `huang2015` -> `huang2019`; "formalized by Moreira and Muir" -> "influential formulation".
