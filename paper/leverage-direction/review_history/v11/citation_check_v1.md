# Citation Verification Report — v11 Round (citation-verifier)

- **Paper**: `paper/leverage-direction/main.tex` (thebibliography, lines 62–235; 57 entries)
- **Date**: 2026-06-11
- **Method**: WebSearch（每條至少一個外部來源：SSRN / 出版社頁 / RePEc / Wiley / OUP / MIT Press / nowpublishers / pm-research）+ Crossref 抽驗 + `\cite` 全量 grep（body.tex + main.tex + tables_main.tex）。Bash/Crossref 批次因 sandbox classifier 間歇故障，canonical 經典文獻（Bollerslev 1986 等 35 條）以標準書目記錄比對核實並逐條標註方法。
- **Totals**: **NOT_FOUND = 0；SUSPECT = 2**（hood2025 卷期、bali2016 DOI）；VERIFIED = 46；UNUSED = 9（與 audit 清單完全一致）

---

## 最優先三條 verdicts

| key | verdict | 證據 |
|---|---|---|
| **hood2025** | **VERIFIED（存在）/ SUSPECT（卷期 52(1) 未確認）** | 論文真實存在：Benjamin Hood & Cameron Raughtigan, "Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies"。SSRN abstract 4773781（2024-04-29 posted）；JPM early-access 頁 `pm-research.com/content/iijpormgmt/early/2025/09/08/jpm20251764` — URL slug 與 DOI `10.3905/jpm.2025.1.764` 一致。姓氏 "Raughtigan" 經 SSRN + R/Finance 2024 講者頁雙重確認為真實姓氏（非 hallucination）。**未確認**：bib 寫 "52(1)"，但截至查證時間只找到 early-access 記錄（2025-09-08 ahead-of-print），無任何來源確認已編入 Vol 52 Issue 1。**建議**：改 "Journal of Portfolio Management, forthcoming（或 in press）" + DOI，或另行向 pm-research 確認 52(1) 再保留。**Contribution 2 定位安全** — 不需改錨 Moreira & Muir。 |
| **nelson2025** | **VERIFIED** | SSRN abstract **5931154** 真實存在："Portfolio Construction Under Correlation Breakdowns and Tail Risk" by **Ryan Nelson**，posted 2025-12-15（編號大是因為 2025 年末新 posting，非異常）。bib "Nelson, R. (2025)" 與 DOI `10.2139/ssrn.5931154`（SSRN 標準 DOI 格式）正確。⚠️ in-text 引用（body.tex:375「characterization of volatility scaling as non-predictive risk control」）僅能從 abstract 層面判斷 plausible，working paper 內文宣稱建議投稿前 spot-check 一次原文。 |
| **xu2024** | **VERIFIED** | Xia Xu, "Improving Volatility-Managed Portfolios in Real Time"，**CFR 官方 forthcoming 列表收錄**（`cfr.ivo-welch.info/forthcoming/papers/xu2024improving.pdf`）+ SSRN 4778937。CFR forthcoming 階段**無 DOI 屬正常**，bib 寫法（forthcoming、無 DOI）正確。出版後記得補卷期頁。 |

---

## VERIFIED（46 條）

### A. Web-verified（本輪逐條外部來源核實，21 條）

| key | 核實結果 | 來源 |
|---|---|---|
| araya2024 | J. Applied Mathematics, 2024, art. 6305525；作者 Araya/Aduda/Berhane ✓；DOI 10.1155/2024/6305525 ✓ | Wiley OL + Project Euclid |
| acerbiszekely2014 | Risk, 27, 76–81 ✓（27(11)=Nov 2014 issue，常見引法） | scirp 引文記錄 + MSCI research |
| bayerdimitriadis2022 | JFEC 20(3), 437–471 ✓；OUP URL `/jfec/article/20/3/437` 即 DOI nbaa013 ✓ | academic.oup.com |
| bozovic2024 | IRFA 95 (2024), art. 103353 ✓；Miloš Božović ✓ | ScienceDirect S1057521924002850 + RePEc |
| bucci2020 | JFEC 18(3), 502–531 ✓；DOI 10.1093/jjfinec/nbaa008 ✓ | academic.oup.com（直接列 DOI） |
| campbell2017 | CFR 6(2), 263–301 ✓；DOI 10.1561/104.00000043 ✓（nowpublishers CFR-0043 + RePEc 104.00000043） | nowpublishers + RePEc |
| chang2021 | PBFJ 67, 101522 ✓；四位作者 Chang/Kung/Chen/Tian ✓ | ScienceDirect S0927538X21000299 |
| chevallier2017 | RIBF 39(PB), 763–778 (2017) ✓；DOI 10.1016/j.ribaf.2014.09.010 ✓（ScienceDirect S0275531914000543；online 2014、收卷 2017，年份引法正確） | RePEc + EconPapers + ScienceDirect |
| demiguel2024 | JF 79(6), 3859–3891 ✓；DOI 10.1111/jofi.13395 ✓ | Wiley OL 全文頁 |
| engle2018 | RFS 31(2), 449–492 (Feb 2018) ✓ | academic.oup.com `/rfs/article/31/2/449` |
| engleGhyselsSohn2013 | REStat 95(3), 776–797 ✓ | MIT Press direct.mit.edu `/rest/article/95/3/776` |
| fleming2001 | JF 56(1), 329–352 ✓；DOI 10.1111/0022-1082.00327 ✓ | Wiley OL |
| harri2009 | QQASS 3(3) (2009) ✓；作者 Ardian Harri + B. Wade Brorsen ✓（無 DOI 正確 — 該刊無 DOI） | SSRN 76460 + Harri vita |
| harvey2018 | JPM 45(1), 14–33 ✓ | jpm.pm-research.com/content/45/1/14 |
| hood2025 | 存在性/作者/DOI ✓（卷期見 SUSPECT） | 見上表 |
| hwang2006 | EJF 12(6–7), 473–494 ✓；DOI 10.1080/13518470500039436 ✓ | tandfonline 直連 |
| longin2001 | JF 56(2), 649–676 ✓；DOI 10.1111/0022-1082.00340 ✓ | Wiley OL + JSTOR 222577 |
| nelson2025 | 見上表 ✓ | SSRN 5931154 |
| xu2024 | 見上表 ✓ | CFR forthcoming 官方頁 |
| bali2016 | 書真實（Wiley 2016, Bali/Engle/Murray）✓ — **但 DOI 可疑，見 SUSPECT** | wiley.com 書頁 |
| mcneil2015 | Princeton UP ✓（建議補 "Revised Edition" — 2015 為修訂版） | （知識 + 出版社記錄） |

### B. Canonical 經典（標準書目記錄比對，逐條核對卷期頁與 DOI 格式，無一不符）

bollerslev1986（JoE 31(3) 307–327）、bollerslev1987（REStat 69(3) 542–547）、black1976（ASA Proceedings 177–181，無 DOI 正確）、christie1982（JFE 10(4) 407–432）、glosten1993（JF 48(5) 1779–1801）、nelson1991（Econometrica 59(2) 347–370）、engle1982（Econometrica 50(4) 987–1007；bib 用 JSTOR stable URL 1912773 ✓ 合理）、diebold1995（JBES 13(3) 253–263）、newey1987（Econometrica 55(3) 703–708）、kupiec1995（J. Derivatives 3(2) 73–84）、christoffersen1998（IER 39(4) 841–862）、hansen1994（IER 35(3) 705–730）、hansen2005（JAE 20(7) 873–889）、hansen2011（Econometrica 79(2) 453–497）、hansen2012（JAE 27(6) 877–906）、harvey2016（RFS 29(1) 5–68）、henriksson1981（J. Business 54(4) 513–533）、treynor1966（HBR 44(4) 131–136，無 DOI 正確）、parkinson1980（J. Business 53(1) 61–65）、patton2011（JoE 160(1) 246–256）、moreira2017（JF 72(4) 1611–1644）、fleming2003（JFE 67(3) 473–509）、baur2010hedge（Financial Review 45(2) 217–229）、baur2010safe（JBF 34(8) 1886–1898）、batten2010（Resources Policy 35(2) 65–71）、kuester2006（JFEC 4(1) 53–89）、francq2004（Bernoulli 10(4) 605–637）、fisslerziegel2016（Ann. Statist. 44(4) 1680–1707）、pattonSheppard2015（REStat 97(3) 683–697）、kim2019（PLoS ONE 14(2) e0212320）、cederburg2020（JFE 138(1) 95–117）、engle2006（JoE 131(1–2) 3–27）、engle2004（AER 94(3) 405–420）、bcbs2006 / bcbs2019（BIS 官方文件，無 DOI 正確）、sheppard2023（arch 軟體引用，GitHub URL ✓）。

---

## SUSPECT（2 條）

1. **hood2025 — 卷期 "52(1)" 未獲任何來源確認**。文章為 JPM early-access（2025-09-08 ahead-of-print，URL `early/2025/09/08/jpm20251764`）。DOI、作者、標題全部正確。**修正建議**：`Journal of Portfolio Management, forthcoming. https://doi.org/10.3905/jpm.2025.1.764`（或確認已編卷後保留 52(1)）。
2. **bali2016 — DOI `10.1002/9781118709207` 查無**。該書真實 ISBN：9781118095041（精裝）/ 9781118589663（ePub）/ 9781118589472（PDF）— 沒有任何一個對應 9781118709207；以 "9781118709207" 全網搜尋零命中。Wiley 書 DOI 慣例為 `10.1002/<oBook-ISBN>`，此字串對不上任何已知 ISBN，**極可能是捏造/錯置的 DOI**。**修正建議**：刪除 DOI，改 `John Wiley & Sons.`（書籍引用無 DOI 完全合規），或查 Wiley Online Library oBook 真實 DOI 再補。

## NOT_FOUND（0 條）

無。57 條全部對應真實出版物。

---

## In-text 宣稱抽查（10 條高風險：方法論 + 貢獻定位）

| # | key（位置） | 宣稱 | 判定 |
|---|---|---|---|
| 1 | hood2025（body.tex:13, 375, 407, 513） | equity VT alpha 來自 leverage effect 引致的 implicit trend-following；本文 "generalizes" 該 equity-specific 發現 | **支撐** ✓ — 原文 abstract：outperformance mainly due to trend-following loading（leverage effect 引起的 return–volatility 負相關）；且明說 commodity/FI/FX（無 leverage effect 處）alpha 不歸於 trend → 本文「γ 方向決定機制、equity-type 才成立」是合理 generalization 框架 |
| 2 | chevallier2017（body.tex:7, 23） | "document inverted asymmetric volatility in gold and several agricultural commodities" | **支撐** ✓ — 原文：inverted asymmetry 僅在 gold、wheat、coffee、cocoa 成立，且 gold 效應顯著最大（兩個獨立摘要來源交叉確認語義） |
| 3 | moreira2017（body.tex:106, 272, 430） | VT 權重 σ_target/σ̂；alpha 因 volatility 變動未被 expected return 等比抵銷 | **支撐** ✓ — M&M 2017 canonical 機制 |
| 4 | hwang2006（body.tex:59, 282, 497） | GARCH(1,1) 估計至少需 ~500 obs；小樣本 persistence 負偏 | **支撐** ✓ — 原文明確建議 ARCH(1)≥250 / GARCH(1,1)≥500，且 ML 估計小樣本顯著負偏（−3.0% 數字為本文自估，歸因方式可接受） |
| 5 | patton2011（body.tex:67, 163, 312, 324, 425） | QLIKE 對 proxy noise robust、ranking 在 conditionally unbiased proxy 下不變 | **支撐** ✓ — Patton (2011) robust loss class 核心結果 |
| 6 | harri2009（body.tex:152） | overlapping observations → MA error、naive t-stat 上偏 | **支撐** ✓ — 原文 abstract 直述 |
| 7 | fisslerziegel2016 + acerbiszekely2014（body.tex:220） | (VaR,ES) 聯合 elicitable via strictly consistent scoring family；A&S 提出 exceedance-magnitude 直接檢定 | **支撐** ✓ — 兩者皆為原文核心貢獻 |
| 8 | francq2004（body.tex:53） | "QMLE of GARCH parameters remains consistent regardless of mean specification when the true conditional mean is small" | **輕微 over-reach** ⚠️ — F&Z (2004) 證的是 pure GARCH 與 ARMA-GARCH 的 QMLE consistency/AN；「對 mean specification 誤設 robust」是延伸詮釋非原定理。建議改寫為 "establish consistency of QMLE for GARCH and ARMA-GARCH processes" 並把 small-mean 推論留給本文自己的 robustness check（已有 AR(1) check，邏輯可自足） |
| 9 | bayerdimitriadis2022（body.tex:225, 231） | "power to reject misspecified ES is negligible at N < 25" | **plausible 但屬作者解讀** ⚠️ — B&D 模擬顯示小 exceedance 樣本 power 低，但 "N<25" 具體門檻非原文直接陳述，建議投稿前對到原文模擬表頁碼或軟化措辭（"power is negligible for small exceedance counts; see ..."） |
| 10 | harvey2016（body.tex:495） | multiple testing → t > 3.0 門檻 | **支撐** ✓ — HLZ 原文建議 |

## UNUSED（9 條 — 驗證 audit 清單：完全一致）

`grep -o '\\cite[tp]\?{...}'` 全量掃 `body.tex` + `main.tex` + `tables_main.tex`（tables_main.tex 含 0 個 cite），未被引用的 bibliography 條目共 9 條：

`engle2004, longin2001, mcneil2015, kim2019, bucci2020, araya2024, campbell2017, engleGhyselsSohn2013, pattonSheppard2015`

→ 與 2026-06-10 audit 所列 9 條**完全一致**，無遺漏無多列。建議：刪除（natbib + thebibliography 不會自動剔除）或在 literature review 補引（kim2019/bucci2020/araya2024 可自然掛在 ML-volatility 一句；campbell2017/longin2001 可掛 bonds/correlation；否則刪）。

---

## 修正優先序（給 paper-update）

1. **bali2016 DOI 刪除或更正**（SUSPECT — 查無的 DOI 比沒有 DOI 更傷審稿信任）
2. **hood2025 卷期改 forthcoming**（或確認 52(1) 後保留）
3. 9 條 UNUSED 處理（刪或補引）
4. francq2004 措辭精確化（§3.2 mean specification 段）
5. bayerdimitriadis2022 "N<25" 對頁碼或軟化
6. mcneil2015 補 "Revised Edition"；xu2024 出版後補卷期頁
