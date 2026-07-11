# Fable Deep Review — vt-trend-following（Is VT Just Trend Following?）

**Reviewer**: Claude Fable 5（深度審查，referee 水準）
**Date**: 2026-07-11 22:36（台灣時間）
**Reviewed**: `main_v3.tex` + `body_v3.tex`（canonical，661 行，編譯 40 頁）、README.md、
`review_history/codex_contribution_gate_20260701.md`、v7 round、`reproduce.py` / `reproduce_report.json`、
`experiments/k1178|k1192|k1193`、`paper/vt-trend-following/experiments/k898_*`、
`figures/generate_figures.py`、`storage/ops/dm_hac_lag_baseline.json`
**方法**: 全文逐行讀 + 關鍵數字 claim 對照 canonical JSON + `.claude/rules/experiments.md` Methodology 硬規則 checklist

---

## 1. 執行摘要

**Verdict：2 / 5（現狀不可投稿；修完本報告 P0+P1 後可達 4/5）**

三句話：
1. **貢獻是真的、也是 JPM/FAJ 形狀的**——「alpha 被 TSMOM 吸收 ≠ 經濟價值被摧毀；drawdown 保險通道在 hedge 掉 TSMOM 後存活」這個 decomposition 對實務讀者有用、有差異化（vs Hood 2025 / Moreira-Muir / Cederburg），且論文對 alpha 的謙抑態度正確。
2. **但 Table 5（國際 13 市場）是半更新的嵌合體（chimera）**：13 個市場列全部是舊 vintage（K1178 canonical 對照 `n_matched_markets = 0`），而 Average 列與相關係數卻已換成 K1178 canonical——**表內各列平均 = 28.7 pp，印出的 Average 卻是 24.9 pp**，referee 拿計算機加一遍就抓到；且 Sharpe 欄 13/13 不符（canonical：0/13 市場 Sharpe 改善、平均 ΔSharpe −0.188，論文寫 2/13、−0.048），「4%/year 保險費」敘事目前建立在無法復現的數字上。
3. codex contribution gate（2026-07-01）的 11 項 reframing agenda **實質上 0 項完成**；唯一動過的 K-id scrub（commit e54c21136）反而在正文留下至少 8 處破損文法（`the the`×4、`extending 's`、`(, N=5,049)` 等）與未清乾淨的 internal tags（commit hash、K79、experiments/ 路徑、內部 task 用語）。

---

## 2. 現況盤點

### 2.1 Canonical 版本

- **Canonical**: `main_v3.tex`（wrapper，`\input{body_v3}`）+ `body_v3.tex`（2026-07-01 04:13 最後修改）。編譯產物 `main_v3.pdf` **40 頁**（README 寫 33 頁已過時）。
- `main.tex` 仍在 tree（頭部有 STALE banner 指向 main_v3），**未從投稿 bundle 概念中移除**——codex gate item 1 未解。
- Pipeline stage = revision（brief 口徑正確）；README 裡的「v7 PASS → ready_for_submission_candidate」已被 07-01 gate 的 BORDERLINE 推翻，README 該段 stale。
- v7 round 範圍極窄（只收 K1458 trough-decomposition 的 5 個 v6 findings），**從未稽核 Table 1 / 4 / 5**。
- `reproduce_report.json`（2026-06-10）90/90 green，但 scope 只含 Table 2 / Table 3+Fig1 / Table 6(K1376) / K1417 / figure artifacts——**Table 1、Table 4、Table 5 完全不在 reproduce gate 綁定範圍內**（`grep 'Table 5\|international\|k1178' reproduce.py` 零命中）。這是 K1259「子集稽核盲區」教訓的再現：green gate 給了「已驗證」的錯覺，最大的雷（Table 5）恰好在 scope 外。Figure artifacts「3 match」也只驗檔案層，驗不到 Fig 2 註記數字 vs 正文的矛盾。

### 2.2 Codex reframing agenda 逐項現況（11 項，2026-07-01 gate §4）

| # | Item | 現況 | 證據 |
|---|------|------|------|
| 1 | main.tex canonical 入口歧義 | ❌ 未解 | `main.tex` 仍在 tree；banner 是 gate 前就有的 |
| 2 | 移除正文 internal experiment tags | ⚠️ 半做且**倒退** | e54c21136 scrub 掉多數 K-id，但留下：`body_v3.tex:149` 正文 “K79” + footnote 引 repo 路徑；`:206` “commit \texttt{fc0b3a02}”；`:524` “commit \texttt{d4dfd7bd}”；`:337` table note 引 `experiments/k1192/...json`、`python experiments/k1417/k1417.py`、內部 task 用語「H2 NOT SUPPORTED」。scrub 同時製造破損文法：`:117` “extending 's five-asset”、`:131` “block lengths ;”、`:380/:385/:524` “the the”、`:576` “The the canonical”、`:429` “(, $N = 5{,}049$)” |
| 3 | Figure 2 重生成 | ❌ 未做 | `figures/` mtime 2026-06-11；`generate_figures.py:230` 註記仍是 r=−0.770/ρ=−0.720（正文 −0.806/−0.835）；data array 是舊 13 列（均值 28.7 pp） |
| 4 | Table 3 Calmar (v) cells | ❌ 未做 | `body_v3.tex:356-360` 四個 `\textsuperscript{(v)}` + `:376` 正文可見 “pending the reproduce-gate recomputation” |
| 5 | BAB 來源矛盾 | ❌ 未做 | `:54` 說 BAB 來自 AQR；`:424/:429` 說 SPLV−SPHB proxy（2011 起，N=3,740），且 “(, N=5,049)” 句子破損 |
| 6 | Abstract 重寫（單一 claim） | ❌ 未做 | Abstract 仍 ~450 字、承載幾乎所有結果 |
| 7 | Forensic notes 移出正文 | ❌ 未做 | `:519` `\paragraph{Forensic notes on v3 revisions.}` 仍開場 Section 4 |
| 8 | “Sharpe drag in %/yr” 單位混淆 | ❌ 未做 | `:36/:555/:557` 仍是 “4%/year Sharpe drag” |
| 9 | 側枝 claims 降級到 appendix | ❌ 未做 | 427-config search、dynamic allocation、prediction≠application、CRRA 仍在 Discussion 正文 |
| 10 | 補 practitioner trend-following 引文 | ❌ 未做 | 書目無 Asness/Liew 類引文 |
| 11 | Cover letter | ❌ 未做 | 目錄無 cover_letter.* |

**結論：11 項中 0 項完全解決。** e54c21136 的 commit message 宣稱「compliance gate CLEAN」——gate 顯然只掃 K+3~4 位數 pattern，漏掉 K79（2 位數）、commit hash、experiments/ 路徑、內部 task 用語。這本身是 `feedback_declare_complete_requires_class_sweep` 的違例：宣告完成前沒做 class-level sweep，機械 gate 也沒同步補強。

---

## 3. 學術深度檢視

### 3.1 Contribution（JPM/FAJ 實務 relevance）

同意 codex gate 的判斷並在細讀後維持：**contribution 是 borderline-positive、venue 對位正確**。核心可教學心智模型（TSMOM 讀過去報酬的*方向*、12/VIX 讀恐慌的*水位*；兩者在 drawdown 後重疊但不是同一物件，所以 factor regression 吸掉 alpha 而 drawdown profile 不死）是 JPM/FAJ 讀者拿得走的。與 Harvey et al. (2018, JPM) 的 volatility targeting 系列是直接對話關係——投 JPM 有清楚的 lineage。

實務 relevance 的缺口：(a) 無 capacity/turnover 描述（只有 break-even bps）；(b)「投資人付 4%/yr 保費」的量化目前建立在不可復現的 Table 5 Sharpe 欄（見 §4 F2）——這是實務 pitch 的核心數字，必須先修；(c) 40 頁對 JPM 太長（realistic target ~5,000 字），對 FAJ 也偏重。

### 3.2 方法論

**做對的**：lagged weights（`:63`）、TSMOM signal 到 t−1（`:69`）、rolling hedge beta 只用過去 252 天（`:104`）、10bps 成本、full-sample orthogonalization 只作 attribution 用途有揭露（`:74-79`）、`>100%` retention 的保守詮釋（多處）、split-sample regime-shift 限定語（`:206`）、stationary bootstrap 補 252d block 假設（K1417）、forensic 誠實揭露不可復現的舊數字。

**問題**：

- **M-1（Table 5 的三套互相矛盾的 Sharpe 口徑）**：正文宣稱 rf = 時變 IRX（`:54`）。K1178 diff 報告（`experiments/k1178/k1178_vs_paper3_table5_diff.md`）診斷出：舊 Table 5 列用 adjusted-close（auto_adjust=True）+ 低 rf（~SHY 實際報酬），K1178 canonical 卻用 **flat 4%/yr rf**——**兩者都不是論文宣稱的設計**。Table 5 的 Sharpe 欄目前沒有任何一個來源符合正文方法論。順帶違反 repo 的 data-snapshot 硬規則（investigation 用資料必 pin snapshot 且 `auto_adjust=False`）。
- **M-2（13 市場平均的 t=10.25 把橫斷面相依當獨立）**：13 個 ΔMDD 全部由同幾次全球危機（2008、2020）驅動，one-sample t 把它們當 13 個獨立觀測，顯著性被高估——K1355 pooled-inference 硬規則的同類問題（asset-level 而非 asset-day，但相依結構相同）。Abstract 還把它升級成「13 of 13 markets achieve **significant** MDD improvement」——per-market 根本沒有檢定，只有 pooled 平均的 t。需要 joint（跨市場同日重抽）的 block bootstrap CI，或降級為描述性陳述。
- **M-3（MCHI/INDA 樣本期不可能成立）**：Table 5 note 宣稱全部 13 市場「January 2007–March 2026」，但 MCHI 2011 年、INDA 2012 年才上市。這兩列的樣本必然較短（K1178 diff 已證實），意味 (a) note 錯誤；(b) 跨市場 MDD 水位不可比（INDA 的小 ΔMDD 部分只是沒經歷 2008）。
- **M-4（DM t=−2.79 出處遺失 + 口徑不明）**：`:528` 的 “12/VIX: DM t = −2.79, p = 0.005; EWMA VT: DM t = −1.67” 在 K-scrub 後只剩 “The underlying experiment”——不可追溯。DM 用在策略報酬差（非 forecast loss）本身需要說明 loss function 與 HAC bandwidth；在 K1655 class sweep 之後，任何對外 DM 數字都應能指認 canonical 實作與 lag 規則。（本論文列名的 canonical K 均不在 `dm_hac_lag_baseline.json` 凍結名單——先前 grep 疑似命中是 k542/k550/k790 子字串誤中——但這個 −2.79 的世代不明，無法排除。）
- **M-5（per-asset GJR-GARCH）**：per-asset MLE 不觸發 pooled-MLE 100-multistart 硬規則，樣本 ~5,000 obs 也充分；但正文未報告估計器/收斂診斷，投稿版建議一句話帶過（package、收斂準則）。

### 3.3 統計嚴謹度（數字 claim 抽查）

| Claim（body 位置） | 對照來源 | 結果 |
|---|---|---|
| 5-asset retention 103.7/95.6/106.2/109.0/102.2（abstract, `:254-258`） | k1192_results.json point_estimates | ✅（SPY 103.7、bh −55.19、vt −26.31、hedged −25.25 全符） |
| SPY 90% CI [93.0, 182.2]（Table 6） | k1192: lo 93.0 / hi 182.3 | ✅（hi 差 0.1，捨入；但 Table 6 標的來源其實是 K1376，見 F8） |
| 50/50 CI [76.0, 189.9] | k1192 | ✅（但 `n = 9925` ≠ 宣稱的 10,000 reps，75 個失敗 replication 未揭露） |
| split-sample r=0.793 / ρ=0.749（`:206`） | k1193_results.json: 0.7934 / 0.7493 | ✅ |
| 國際 avg ΔMDD 24.9 pp、t=10.25、r=−0.806、ρ=−0.835 | k1178_results.json cross_sectional | ✅（Average 列與相關係數本身正確） |
| **Table 5 的 13 個市場列** | k1178 match_assessment | ❌ **n_matched_markets = 0**；ΔMDD 重大偏離：EWZ 13.2→5.8、MCHI 23.0→15.2、EEM 33.6→21.2、FXI 29.9→17.9；VT Sharpe 欄 13/13 不符 |
| 「2 of 13 show Sharpe improvement」「avg ΔSharpe −0.048」（`:446`, abstract, Fig 2） | k1178: n_sharpe_improved = **0**、avg_sharpe_diff = **−0.188** | ❌ 舊 vintage |
| DM/EM 子平均 32.0 / 24.7 pp（`:450`, note） | k1178: 30.7 / 18.2 | ❌ 舊 vintage |
| 「all equity assets showing positive loadings」（`:143`） | 自家 Table 1：EWJ −0.006、EWU −0.007、EWA −0.011 | ❌ **與自己的表矛盾**（三個國際 ETF 為負，雖不顯著） |
| M1 joint regression「remains statistically significant, t=2.00 (HC3 2.03)」（`:249`) | N=22、3 參數 → df=19，5% 雙尾臨界值 2.093 | ❌ **過度宣稱**：p≈0.060，只到 10% 水準。此句支撐「γ subsumes asset-class effect」的關鍵論證，必須改為 marginally significant |
| Abstract「stationary bootstrap（3–5yr blocks）lower bounds 90–100%」 | K1417/Table 7：756d 的 50/50 下界 = **84.7** | ⚠️ 只有 1260d spec 成立（min 89.8）；涵蓋 756d 的寫法越界 |
| 5.3% back-calc = 0.043/0.805（`:194`, `:522`） | Table 3 自己印 VT Sharpe **0.797**（k898 供 0.805） | ⚠️ 分母與同頁表格不一致（K1192 vs K898 兩個 vintage 混用） |
| Table 6 SPY median 115.8 vs Table 7 fixed-block 252d median 115.4 | K1376（22 資產 run）vs K1192（5 資產 run） | ⚠️ 同 spec 兩個 run 的數字並陳、未向讀者解釋 |
| 「robust across all sub-periods (Section~3.6)」（`:535`） | 3.6 是 International；sub-period 是 **3.7** | ❌ 硬編碼 cross-ref 錯（`:510` 該節自身） |

QLIKE 方向 / forward-label OOS / uniqueness claims 等其餘硬規則項：本文無 QLIKE/多 horizon 檢定；「no VT variant achieves significant Sharpe improvement」的措辭其實**弱化**了實情（DM t=−2.79 是顯著*更差*），屬保守方向、可接受但宜直說。

### 3.4 內部一致性

最嚴重面向。彙總：Table 5 chimera（列 vs Average 自相矛盾，28.7 vs 24.9）、Fig 2 與正文雙重矛盾（均線 28.7 vs 24.9；註記 r=−0.770 vs −0.806）、Table 3 (v) cells、BAB 兩處說法互斥、`:143` 與 Table 1 矛盾、3.6/3.7 cross-ref、Table 6/7 median 不一致、5.3% 分母不一致、blend bootstrap n=9925。**一篇 40 頁的稿子帶著 ≥9 處可被機械檢查抓到的不一致**——這在 referee 眼中直接摧毀對整個 empirical package 的信任。

### 3.5 寫作

Scrub 破損（§2.2 item 2）使正文目前有肉眼可見的破句——這比 K-id 本身更糟，任何讀者第一頁就會失去信心（`:117` “extending 's five-asset canonical estimates”）。Abstract 過載、Discussion 開頭放 forensic notes、table notes 密度過高、40 頁超長——均與 codex gate 判斷一致，不重複。

---

## 4. 風險與致命傷

### 致命（不修不能投；均可修）

- **F1 — Table 5 chimera**（證據：`k1178_results.json .match_assessment`，n_matched_markets=0；列均值 28.7 ≠ Average 24.9）。第三大 contribution 的整張表需要以單一 canonical run 原子性重建（列、Average、DM/EM 子平均、相關係數、Fig 2、abstract/intro/conclusion 引用值一次換齊）。
- **F2 — 國際 Sharpe 通道無 canonical 來源**（證據：k1178 diff Finding 3——舊值 rf 過低、K1178 rf=4% flat，正文宣稱 IRX 時變；三者互斥）。「0/13 vs 2/13 改善」「−0.188 vs −0.048」直接改寫「4%/yr 保險費」敘事的量級。**方向上對論文有利**（canonical 下保險費更貴、Sharpe 犧牲更明確，insurance framing 更強），但數字必須先真。
- **F3 — 正文可見的 scrub 破損 + 殘留 internal tags**（§2.2 item 2 全列）。arXiv/期刊皆 blocking。
- **F4 — Table 3 (v) pending cells**（`:356-360`, `:376`）。「pending recomputation」出現在核心表 = 稿件未完成的自白。
- **F5 — BAB 來源矛盾**（`:54` vs `:424/:429`）。factor-control 可信度直接受損。

### 重大但可快修

- F6 —「all equity assets positive」vs 自家 Table 1（`:143`）。
- F7 — M1 joint regression 顯著性過度宣稱（`:249`，p≈0.06 說成 significant）。
- F8 — Abstract「13 of 13 **significant**」+ t=10.25 的橫斷面相依問題（M-2）；並修 MCHI/INDA 樣本期陳述（M-3）。
- F9 — DM t=−2.79 出處與 HAC 口徑不可追溯（M-4）。
- F10 — reproduce gate 不涵蓋 Table 1/4/5（違反 paper-workflow「每列 traceable binding」硬規則；也是 F1 能存活至今的根因）。
- F11 — 其餘：3.6/3.7 cross-ref、5.3% 分母、Table 6/7 median 並陳、n=9925、abstract stationary 下界 90–100% 涵蓋範圍、README stale（33 頁/ready_for_submission_candidate）。

### 非致命的結構債（投稿策略層）

40 頁長度、abstract 過載、side claims 塞正文、forensic notes 位置、單位混淆、缺 practitioner 引文、缺 cover letter——codex gate items 6-11，維持原判。

---

## 5. 接下來的研究計畫

### P0 — 數據與一致性（不做完不得進任何 review/publish 流程；估 5–8 個工作天）

**P0-1 K-new：Table 5 canonical 重跑（含 Sharpe 通道重建）** — 最高優先
- 設計：pinned snapshot（`auto_adjust=False` + 明確以除息調整重建 total return，符合 repo 規則）；rf = 每日 IRX（正文宣稱的設計）；cash sleeve = SHY 總報酬；monthly lagged 12/VIX、10bps；13 市場各自從 inception 起 + **共同樣本（2012–2026）robustness 欄**處理 MCHI/INDA；輸出 per-market Sharpe/MDD/ΔSharpe/ΔMDD + Average + DM/EM 子平均 + VIX-sens 相關。
- 推斷：ΔMDD 平均改用**跨市場同日 joint block bootstrap**（同一組日期索引同時重抽 13 市場，保留橫斷面相依）報 CI，取代 iid one-sample t；per-market 不再稱 significant。
- 成功標準：Table 5 每格有 `% source:` binding、reproduce.py 擴充後 green；13/13 MDD 改善若仍成立則敘事不變、僅量級更新。
- Kill 標準：若 joint bootstrap 下平均 ΔMDD 的 CI 含 0，或 MDD 改善不再 13/13 → 觸發 narrative 降級（誠實回報，第三 contribution 改寫為 conditional）；此結果本身仍可發（null 也是結果）。
- 工時：資料+程式 1–2 天（K1178 程式可改），body/圖/abstract 原子性換數 1 天，Codex review 0.5 天。

**P0-2 Table 3 Calmar 重算 + Sharpe provenance 單一化**
- 從 K1192 canonical 報酬序列補算 50/50 的年化報酬 → 4 個 Calmar cell，移除 (v) 與 `:376` caveat；Table 3 Sharpe 欄與 5.3% back-calc 分母統一到同一 canonical（建議全表改 K1192 系列，5.3% 改用同源 Sharpe 或加 footnote 明示口徑）。工時 0.5–1 天。

**P0-3 Scrub 修復 + tag 清除 class sweep + gate 補強**
- 修 8 處破句；移除 `fc0b3a02`/`d4dfd7bd`/K79 footnote/`:337` 的 experiments/ 路徑與「H2 NOT SUPPORTED」task 語言（全部改成中性 replication-package 指引或挪到 comment）。
- **同 commit 補強 compliance gate regex**：`K[0-9]{2,4}`、40-hex/8-hex commit hash、`experiments/`、`the the`/`(, ` 破損 pattern —— enforcement owner 唯一化，避免再犯（anti-stacking：收編進既有 compliance gate，不另建新 gate）。工時 0.5 天。

**P0-4 BAB 解法**
- 首選：抓 AQR BAB daily（官網免費、允許學術引用），跑 full-sample M5（N=5,049）作主結果，SPLV−SPHB 降級為 robustness footnote；data section 與 note 對齊。次選（若 AQR 資料流程有阻力）：正文改口 proxy-only，刪 `:54` 的 AQR 字樣。工時 0.5–1 天。

**P0-5 快修批次**：`:143` all-positive 改「all but three international ETFs / all US equity assets」；`:249` 改 marginally significant (10% level) 並同步弱化「γ subsumes」結論強度；abstract 刪 per-market “significant”；3.6→3.7；abstract stationary 下界限定 1260d；bootstrap n 揭露；README 狀態列更新。工時 0.5 天。

**P0-6 reproduce.py 擴充到 Table 1 / 4 / 5**（paper-workflow 硬規則；也是防 F1 復發的機械 gate）。Table 1/4 綁 `paper/vt-trend-following/experiments/vt_tsmom_final_n22.json`、`ff5_factor_controls.json`；Table 5 綁 P0-1 新 K。工時 1 天。

**P0-7 DM 出處回填**：找回（或重跑）產生 −2.79/−1.67 的實驗，確認 loss function 與 HAC bandwidth 符合 canonical `dm_test`；正文加 footnote 說明口徑，或若無法追溯 → 重跑後換數。工時 0.5–1 天。

### P1 — 投稿包重整（P0 綠後；估 4–6 個工作天）

- **P1-1 敘事瘦身**：abstract 砍到 ~150 字（問題、方法、drawdown 量級、rule、含意 + 3 個數字）；forensic notes 全段移到 replication appendix；427-config / dynamic allocation / prediction≠application / CRRA 壓縮成一段 robustness 或移 online appendix；正文目標 JPM ~5,000 字（FAJ 版可留 ~8,000）。
- **P1-2 單位修正**：「4%/yr Sharpe drag」全部改為 annualized return cost（%/yr）或 unitless ΔSharpe，二擇一貫穿全文（P0-1 重跑後數字同步更新）。
- **P1-3 引文補強**：加 AQR practitioner trend-following 文獻（Asness-Moskowitz-Pedersen 2013 *Value and Momentum Everywhere* 或 Hurst-Ooi-Pedersen 實務系列擇一即可，定位在 intro 的 practitioner 對話段）；hood2025 補 SSRN 編號/URL（它是全文的直接對話對象，“Working Paper. Retrieved May 2025” 不夠）；baltas2013 查是否已正式刊出（有正式版就換）。
- **P1-4 投稿 bundle 收斂**：`main.tex` 改名 `_archive/main_v1.tex` 或明確排除於 bundle；cover letter 兩版（JPM/FAJ 定位不同，見下）；data/code availability statement。
- **P1-5 全文 paper-review-cycle 一輪 + citation-verifier + codex contribution gate 重審**（gate 由 BORDERLINE 升 PASS 才能進 submit gate）。

### P2 — 補強（可與投稿並行或作 referee 回應彈藥；估 3–5 天）

- **P2-1 國際 13 市場 MDD retention bootstrap**（正文自列 limitation #6）：K1376 程式延伸即可；若下界多數為正，第三 contribution 從「描述性」升「有推斷支撐」。成功=13 市場中 ≥10 個 90% CI 下界 >0；kill=多數含 0 → 留 limitation 不硬撐。
- **P2-2 Turnover / capacity 一張小表**（JPM 讀者必問）：平均月換手、成本敏感度（0/5/10/20 bps）、規模容量一句話。多數數據已有（break-even 14.9 bps），半天。
- **P2-3（選配）** 國際樣本 dependence-robust 的 Sharpe-difference 檢定（Ledoit-Wolf 或 bootstrap）替代目前無檢定的 ΔSharpe 欄。

### 期刊策略

- **首選 JPM**：與 Harvey et al. (2018, JPM) 同系譜直接對話、practitioner rule 導向、審稿快；格式要求 ~5,000 字、少方程式、表格精簡 — P1-1 就是為此做的。Desk-reject 風險點：長度、可見的內部鷹架（P0/P1 修畢即除）、以及「又一篇 VT backtest」的第一印象（cover letter 要先發制人：本文不是 performance chase，是 decomposition + 保險詮釋）。
- **次選 FAJ**：容忍 ~8,000 字與較重的推斷 apparatus（bootstrap 章節在 FAJ 是加分），CFA 讀者對 insurance-pricing 詮釋友善；審稿較嚴、較慢。若 JPM 拒且意見集中在「學術密度過高」→ 反而支持轉 FAJ 不砍推斷。
- 兩者都不吃 anonymous 格式問題（JPM 單盲）；作者名限 Yi-Hao Lai、無 volpred/AI 字樣（journal-review skill compliance gate 既有規則）。
- **arXiv**：維持 codex gate 判斷 — P0+P1 完成前**不得**公開張貼。

---

## 6. Go / No-Go 建議

**GO（continue revision）— 但對「現在投稿」是明確 No-Go。**

理由：contribution 真實、venue 對位、且所有致命傷都是 package 層而非研究設計層——沒有一項需要推翻研究結論（F2 的 canonical 數字甚至讓 insurance 敘事更強）。預估 P0（5–8 天）+ P1（4–6 天）後可達 4/5 投稿可行性。反面條件：若 P0-1 的 joint-bootstrap kill 標準觸發，回到 narrative decision 重議第三 contribution 的寫法，屆時再評。

**下一步第一動作**（建議主線程排程）：P0-1（Table 5 重跑）與 P0-3（scrub 修復+gate 補強）可並行起跑；P0-3 半天可完，先止血「肉眼可見的破句」這個最丟臉的面向。

---

*研究誠實聲明：本報告所有引用數字均實際讀自上列檔案；「未驗證」與推測處均已標明（M-4 的 DM 出處、baltas2013 刊出狀態）。本審查未修改任何 .tex / 共享 JSON、未 git commit。*
