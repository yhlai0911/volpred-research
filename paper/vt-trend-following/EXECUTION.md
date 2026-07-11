# EXECUTION — vt-trend-following（Is VT Just Trend Following?）

> **用途**：這是本論文的**可續作執行檔**。任何 session／agent 接手時，讀本檔即可知道「現在卡在哪、下一步做什麼、怎麼算做完、有哪些雷不能踩」，直接從接續提示詞開工，不必重摸索。
> **權威來源**：深審報告 `review_history/fable_deep_review_20260711/README.md`（verdict、P0–P2、致命傷全出自此）。數字／verdict／期刊皆真實讀自該報告與 `storage/paper_pipeline_status.json`、`docs/paper_portfolio_review_20260711.md`。
>
> 註：本檔結構待與黃金範例 `paper/vt-insurance-cost/EXECUTION.md` 對齊（該檔生成中）；內容為 canonical，排版可微調。

---

## 狀態徽章 BADGE

`P0 ⬜ TODO` ｜ `P1 ⬜ TODO` ｜ `P2 ⬜ TODO` ｜ Verdict `2/5` ｜ Stage `revision` ｜ Submit `NO-GO`

<!-- EXECUTION-BADGE
paper: vt-trend-following
verdict: 2/5
stage: revision
submit: no-go
p0: TODO
p1: TODO
p2: TODO
journal_primary: JPM
journal_secondary: FAJ
last_review: fable_deep_review_20260711
canonical_tex: main_v3.tex
-->

---

## 現況摘要

| 欄位 | 值 |
|---|---|
| Verdict | **2 / 5**（現狀不可投稿；修完 P0+P1 後預估可達 4/5） |
| Go / No-Go | **GO on revision；「現在投稿」= 明確 No-Go** |
| 目標期刊 | **首選 JPM**（與 Harvey et al. 2018 JPM volatility-targeting 系列同系譜、practitioner rule 導向）；**次選 FAJ**（容忍 ~8,000 字與較重推斷 apparatus） |
| Pipeline stage | `revision`；contribution gate = **BORDERLINE**（Major revision，2026-07-01 codex gate；10 reframing items 未解） |
| 估工 | P0 5–8 天 + P1 4–6 天（portfolio：合計 **9–14 工作天**） |
| Canonical 稿 | `main_v3.tex`（`\input{body_v3.tex}`）；`main_v3.pdf` **40 頁**（README 寫 33 頁已過時） |
| 核心貢獻 | alpha 被 TSMOM 因子吸收 ≠ 經濟價值被摧毀；**drawdown 保險通道在 hedge 掉 TSMOM 後存活**（decomposition，對 JPM/FAJ 實務讀者有用、有差異化 vs Hood 2025 / Moreira-Muir / Cederburg） |

**一句話定位**：contribution 是真的、venue 對位正確、所有致命傷都在 package 層（不需推翻任何研究結論；F2 的 canonical 數字甚至讓保險敘事更強）。瓶頸是 Table 5 嵌合體與正文衛生，不是研究設計。

---

## 致命傷（不修不能投；均可修，無一需推翻研究設計）

- **F1 — Table 5（國際 13 市場）半更新嵌合體**：13 個市場列全是舊 vintage（K1178 canonical 對照 `n_matched_markets = 0`），但 Average 列與相關係數已換成 K1178 canonical → **表內各列平均 = 28.7 pp，印出的 Average 卻是 24.9 pp**（referee 拿計算機加一遍即抓到）；Sharpe 欄 13/13 不符。證據：`experiments/k1178/k1178_results.json .match_assessment`。
- **F2 — 國際 Sharpe 通道無 canonical 來源**：舊列用 adjusted-close（`auto_adjust=True`）+ 低 rf，K1178 用 **flat 4%/yr rf**，正文卻宣稱時變 IRX — 三者互斥。canonical 下「**0/13** 市場 Sharpe 改善、平均 ΔSharpe **−0.188**」（論文寫 2/13、−0.048）。方向對論文**有利**（保險費更貴、Sharpe 犧牲更明確）但數字必須先真。「4%/yr 保險費」敘事目前建立在不可復現的數字上。
- **F3 — 正文可見的 scrub 破損 + 殘留 internal tags**：`the the`×4、`extending 's`、`(, N=5,049)` 等破句；殘留 commit hash `fc0b3a02`／`d4dfd7bd`、`:149` 正文 “K79” + footnote 引 repo 路徑、`:337` table note 引 `experiments/k1192/...` 路徑與內部 task 用語「H2 NOT SUPPORTED」。arXiv／期刊皆 blocking。
- **F4 — Table 3 有 `(v)` pending Calmar cells**：`body_v3.tex:356-360` 四個 `\textsuperscript{(v)}` + `:376` 正文可見「pending the reproduce-gate recomputation」= 稿件未完成的自白。
- **F5 — BAB 來源矛盾**：`:54` 說 BAB 來自 AQR；`:424/:429` 說 SPLV−SPHB proxy（2011 起，N=3,740）。factor-control 可信度直接受損。

---

## P0 — 數據與一致性（不做完不得進任何 review／publish 流程；估 5–8 工作天）

- **P0-1 K-new：Table 5 國際 13 市場 canonical 重跑（含 Sharpe 通道重建）— 最高優先**
  - 設計：pinned snapshot（`auto_adjust=False` + 明確除息調整重建 total return，符 repo data-snapshot 硬規則）；rf = **每日 IRX**（正文宣稱的設計）；cash sleeve = SHY 總報酬；monthly lagged 12/VIX；10bps；13 市場各自從 inception 起 + **共同樣本 2012–2026 robustness 欄**（處理 MCHI 2011／INDA 2012 上市，不可比性）。輸出 per-market Sharpe/MDD/ΔSharpe/ΔMDD + Average + DM/EM 子平均 + VIX-sens 相關。
  - 推斷：ΔMDD 平均改用**跨市場同日 joint block bootstrap**（同一組日期索引同時重抽 13 市場，保留橫斷面相依）報 CI，取代 iid one-sample t=10.25；per-market 不再稱 significant。
  - 可複用：`experiments/k1178` 程式可改。
- **P0-2 Table 3 Calmar 重算 + Sharpe provenance 單一化**：從 K1192 canonical 報酬序列補算 50/50 年化報酬 → 4 個 Calmar cell，移除 `(v)` 與 `:376` caveat；Table 3 Sharpe 欄與 5.3% back-calc 分母統一到同一 canonical（建議全表 K1192 系列）。
- **P0-3 Scrub 修復 + tag 清除 class sweep + gate 補強**：修 8 處破句；移除 `fc0b3a02`／`d4dfd7bd`／K79 footnote／`:337` 的 `experiments/` 路徑與「H2 NOT SUPPORTED」task 語言。**同 commit 補強 compliance gate regex**（`K[0-9]{2,4}`、40-hex/8-hex commit hash、`experiments/`、`the the`／`(, ` 破損 pattern）— enforcement owner 唯一化，收編進既有 `scripts/check_paper_compliance.py`，不另建新 gate（anti-stacking）。
- **P0-4 BAB 解法**：首選抓 AQR BAB daily（官網免費、允許學術引用），跑 full-sample M5（N=5,049）作主結果，SPLV−SPHB 降級為 robustness footnote，data section 與 note 對齊。次選：正文改口 proxy-only，刪 `:54` 的 AQR 字樣。
- **P0-5 快修批次**：`:143` all-positive 改「all but three international ETFs／all US equity assets」；`:249` M1 joint regression 改 marginally significant（10% level，p≈0.06）並弱化「γ subsumes asset-class effect」結論；abstract 刪 per-market “significant”；`3.6`→`3.7` cross-ref；abstract stationary 下界限定 1260d；bootstrap n=9925 揭露；README 狀態列（33 頁/ready_for_submission_candidate）更新。
- **P0-6 reproduce.py 擴充到 Table 1 / 4 / 5**（paper-workflow 硬規則；也是防 F1 復發的機械 gate）：Table 1/4 綁 `paper/vt-trend-following/experiments/vt_tsmom_final_n22.json`、`ff5_factor_controls.json`；Table 5 綁 P0-1 新 K。
- **P0-7 DM 出處回填**：找回（或重跑）產生 `−2.79`／`−1.67` 的實驗，確認 loss function 與 HAC bandwidth 符合 canonical `volpred.stats.model_evaluation.dm_test`；正文加 footnote 說明口徑，或若無法追溯 → 重跑後換數。

### P0 完成定義（DoD — 全部未達成）

- [ ] Table 5 由**單一 canonical run** 原子性重建：13 市場列／Average／DM-EM 子平均／相關係數／Fig 2／abstract·intro·conclusion 引用值一次換齊（列均值 = 印出 Average）
- [ ] 國際 Sharpe 欄有唯一 canonical 來源，rf 口徑與正文宣稱一致（每日 IRX）；joint block bootstrap CI 取代 iid t
- [ ] Table 3 四個 Calmar cell 有數字，`(v)` 與「pending recomputation」caveat 移除；Sharpe 分母全表單一 provenance
- [ ] 正文 8 處破句修復；commit hash／K79／`experiments/` 路徑／task 用語全清；`check_paper_compliance.py vt-trend-following` = 0 findings（含新 regex）
- [ ] BAB 來源單一化（AQR full-sample 或 proxy-only），data section 與 note 一致
- [ ] P0-5 快修 7 項全落地
- [ ] `reproduce.py` 涵蓋 Table 1／4／5，`exit 0` + `match_rate ≥ 95%` + `alert_level = green`；每 Table row 有 inline `% source:` binding
- [ ] DM `−2.79`／`−1.67` 出處可追溯、口徑符 canonical `dm_test`
- [ ] Codex primary-path review PASS；knowledge.json 新 K 帶 reviewer 欄

---

## P1 — 投稿包重整（P0 綠後；估 4–6 工作天）

- **P1-1 敘事瘦身**：abstract 砍到 ~150 字（問題／方法／drawdown 量級／rule／含意 + 3 個數字）；forensic notes 全段移到 replication appendix；427-config search／dynamic allocation／prediction≠application／CRRA 壓縮成一段 robustness 或移 online appendix；正文目標 JPM ~5,000 字（FAJ 版可留 ~8,000）。
- **P1-2 單位修正**：「4%/yr Sharpe drag」全部改為 annualized return cost（%/yr）**或** unitless ΔSharpe，二擇一貫穿全文（P0-1 重跑後數字同步更新）。
- **P1-3 引文補強**：加 AQR practitioner trend-following 文獻（Asness-Moskowitz-Pedersen 2013 *Value and Momentum Everywhere* 或 Hurst-Ooi-Pedersen 實務系列擇一，定位 intro practitioner 對話段）；`hood2025` 補 SSRN 編號/URL；`baltas2013` 查是否已正式刊出。
- **P1-4 投稿 bundle 收斂**：`main.tex` 改名 `_archive/main_v1.tex` 或明確排除於 bundle；cover letter 兩版（JPM/FAJ 定位不同）；data/code availability statement。
- **P1-5 全文 paper-review-cycle 一輪 + citation-verifier + codex contribution gate 重審**（gate 由 BORDERLINE 升 PASS 才能進 submit gate）。

### P1 完成定義（DoD — 全部未達成）

- [ ] abstract ~150 字、單一 claim；forensic notes 移出正文
- [ ] 正文長度符目標期刊（JPM ~5,000 / FAJ ~8,000）；側枝 claims 移 appendix
- [ ] 經濟成本單位全文一致（%/yr 或 ΔSharpe 二擇一）
- [ ] practitioner 引文補齊；hood2025 / baltas2013 書目更新
- [ ] `main.tex` 排除 bundle；cover letter（JPM+FAJ）；data/code availability statement 齊備
- [ ] paper-review-cycle + citation-verifier + codex contribution gate 重審通過（gate = PASS）

---

## P2 — 補強（可與投稿並行或作 referee 回應彈藥；估 3–5 工作天）

- **P2-1 國際 13 市場 MDD retention bootstrap**（正文自列 limitation #6）：`experiments/k1376` 程式延伸；若下界多數為正，第三 contribution 從「描述性」升「有推斷支撐」。成功 = 13 市場中 ≥10 個 90% CI 下界 > 0；kill = 多數含 0 → 留 limitation 不硬撐。
- **P2-2 Turnover / capacity 一張小表**（JPM 讀者必問）：平均月換手、成本敏感度（0/5/10/20 bps）、規模容量一句。多數數據已有（break-even 14.9 bps），估半天。
- **P2-3（選配）** 國際樣本 dependence-robust 的 Sharpe-difference 檢定（Ledoit-Wolf 或 bootstrap）替代目前無檢定的 ΔSharpe 欄。

### P2 完成定義（DoD — 全部未達成）

- [ ] MDD retention bootstrap 完成，第三 contribution 依結果升級或維持 limitation
- [ ] turnover/capacity 小表入稿
- [ ]（選配）dependence-robust Sharpe-difference 檢定完成

---

## 禁止事項（本篇特有）

- **Table 5 別再半更新**：任何重跑必**原子性換齊**「13 市場列 + Average + DM/EM 子平均 + 相關係數 + Fig 2 + abstract/intro/conclusion 引用值」，一次到位。半更新正是現狀 F1 嵌合體的成因（28.7 vs 24.9 pp 自相矛盾，referee 一眼抓到）。
- **別 merge／混談 `vt-insurance-cost`、`vt-crowding-abm`**：本篇獨立成篇（TSMOM 吸收 alpha vs drawdown 保險通道 decomposition）；跨 VT 論文共用敘事或數字會製造 provenance 污染，並模糊本篇的差異化貢獻。
- **別再靠 reproduce gate 綠燈當「已驗證」**：現行 gate scope **不含 Table 1／4／5**（`grep 'Table 5\|international\|k1178' reproduce.py` 零命中），F1 就是因此存活至今（K1259 子集稽核盲區再現）。宣告 green 前必先完成 P0-6 擴充，否則 green 是假象。
- **不手改 JSON 欄位湊數**：數字不符走「修腳本／修論文／errata」三選一（paper-workflow 硬規則），絕不偽造/硬 code/湊 seed。
- **不用 background agent 直接改 `.tex`**：論文寫作與方法論決策留主線程（`.claude/rules/paper-workflow.md`）。

---

## 接續提示詞（下一手 = P0-1）

> 讀 `paper/vt-trend-following/EXECUTION.md` 與 `review_history/fable_deep_review_20260711/README.md` §5 後，從 **P0-1（Table 5 國際 13 市場 canonical 重跑）** 開始：
>
> 1. **開新 K**（改 `experiments/k1178` 程式）：pinned snapshot（`auto_adjust=False` + 除息調整重建 total return）、rf = 每日 IRX、cash = SHY 總報酬、monthly lagged 12/VIX、10bps；13 市場 inception-aware + 共同樣本 2012–2026 robustness 欄（MCHI 2011／INDA 2012）。輸出 per-market Sharpe/MDD/ΔSharpe/ΔMDD + Average + DM/EM 子平均 + VIX-sens 相關。
> 2. **推斷**：ΔMDD 平均改**跨市場同日 joint block bootstrap** 報 CI（取代 iid t=10.25）；per-market 不稱 significant。
> 3. **判準**：13/13 MDD 改善仍成立 → 敘事不變、僅更新量級；joint CI 含 0 或不再 13/13 → 觸發 **narrative 降級**（誠實回報，第三 contribution 改寫為 conditional；null 也可發）。
> 4. **驗證**：Codex primary-path review PASS；Table 5 每格 inline `% source:` binding；`reproduce.py` 擴充涵蓋 Table 1/4/5 後 `exit 0` + `match_rate ≥ 95%` + `alert_level=green`。
> 5. **回寫**：原子性換齊 `body_v3.tex` 表／Fig 2（`figures/generate_figures.py`）／abstract／intro／conclusion 全部引用值；`knowledge.json`（含 reviewer 欄，走 Python writer）；本檔進度日誌 + BADGE `p0` 狀態；`research_program.md` 若研究方向有變。
>
> 完成 P0-1 後接 P0-3（scrub 修復，半天可完，先止血最丟臉的破句），再依序 P0-2/4/5/6/7。

---

## 進度日誌

| 日期 | 事件 | 狀態 | commit |
|---|---|---|---|
| 2026-07-11 | Fable deep review | 深審完成，待執行 P0 | `f913ed68c` |
