# Fable 深度審查 — vix-sufficiency「Can Anything Beat VIX?」

**審查日期**: 2026-07-11（台灣時間）
**審查者**: Claude Fable 5（頂級期刊 referee 水準深度檢視，user-assigned P0）
**審查對象**: `main_v5.tex`（1,317 行，2026-07-09 編譯，61-63 頁）— **canonical 工作檔已是 v5，非任務簡報所述 v4**
**方法**: 全文通讀 + 逐 table 對照 source JSON + 全部 DM/HAC 站點實作稽核（K1655 class checklist）+ reproduce gate 覆蓋分析
**數字驗證原則**: 本報告引用的每個數字均實際讀自檔案；無法驗證者明標「未驗證」。

---

## 1. 執行摘要

**Verdict: 2 / 5（REJECT-in-current-state；可救，但需系統性重算推論層 + claim 全面清洗，估 2-3 週）**

三句話：

1. v5 修掉了 v4 review 的 3 個 SEVERE（Table 6/K752 衝突、Clark-West、publication-delay convention），且修得誠實漂亮 — 但 **v4 的 8 個 MAJOR 一項都沒修**（41.8% 方向翻轉錯誤仍在 3 處、abstract overclaim、Basel/Student-t、CRRA、pre-spec 矛盾、citation orphans 全數原地）。
2. 本次審查新發現**整篇論文的 DM 推論層系統性踩 K1655 class**：餵 Table 2 F12/F13 與 Table 9 全部 16 cells 的 k1116b、餵 panorama 28 cells 的 k1203、weekly Clark-West 的 k1116c，全部是**零 HAC**（plain variance ± HLN 因子）；Table 2/3 的 daily/strategy DM 另有 5 個 degenerate 站點 — 而論文正文聲稱「HAC bandwidth = 22 / 4」。其中 6 個站點**逃過了 dm_hac_lag_baseline 凍結掃描**（auditor pattern 盲區）。
3. 另發現一個**擱置 34 個月的資料誠信欠帳**：2026-04-19 root-caused 的 K732/K736「抄錯格」決議（`decisions/k732_k736_table2_rewrite.md`）從未落地 — v5 Table 2 F3 仍印 IS t=1.64（實為 `dm_stat_oos=1.637`），F11 仍印 composite salad 值；reproduce gate 因「JSON↔JSON 不驗 LaTeX」的設計缺陷（errata 文件自己承認）而年年綠燈。

好消息：**主結論「無訊號在 beneficial 方向打敗 VIX」大概率存活**。有適當 HAC 的站點（k778、k799、k1116e、k1116g）全部支持 null；beneficial 方向所有 cell 離 Harvey 3.0 都很遠（最大 CW t=+1.69），重疊視窗 loss differential 的正自相關主導時修正只會讓 |t| 更小。真正有翻案風險的是**harmful-direction 顯著性宣稱**與 panorama「UNIVERSAL_NULL_7/7」的個別 cell（K1655 前例：同類 weekly NFCI loss differential acf(1)=0.68，修正後 Harvey-significant 26→18；k621 前例：負自協方差時 |t| 反而變大 — 雙向，不可預設安全）。

---

## 2. 現況盤點 — 版本鏈與 reproduce gate gap

### 2.1 版本鏈實況

| 版本 | 日期 | 狀態 |
|---|---|---|
| main_v3.tex | 2026-04 | reproduce gate 綁定版（98/100 = 98% GREEN, 2026-04-20） |
| main_v4.tex | 2026-07-01 | Codex review（2026-07-06）= **REJECT**：3 SEVERE + 8 MAJOR |
| **main_v5.tex** | **2026-07-09** | **現行 canonical**。SEVERE-1/2/3 已修（本審查逐項驗證屬實）；**8 MAJOR 全部未修** |

⚠️ `research_program.md` L~870 portfolio 表仍標 P7「✅ READY — GREEN 98%」— 已被 2026-06-10 audit（MAJOR_REVISION）與 2026-07-06 Codex REJECT 推翻，**stale 狀態未更新**（ops 欠帳）。

### 2.2 reproduce gate gap（逐項）

`reproduce_report.json`: `paper_version="v3"`, generated 2026-04-20, 100 checks, 98% match, green。

**Gap A — 版本覆蓋**：v4/v5 新增內容（約佔正文 1/3 以上）完全不在 gate 內：

| v4/v5 新增章節 | 來源實驗 | Gate 覆蓋 |
|---|---|---|
| §7.7 七資產 PIT panorama（28 cells, Table `panorama_7asset`） | k1203 | ✗ |
| §7.8 Channel heterogeneity（Table `channel_outcomes`） | k1135/36/37/38/43 | ✗ |
| §7.9 Publication-delay robustness（Table 9, 16 cells） | k1116b | ✗ |
| §7.10 Allocation null（Tables k1121 ×3） | k1121 | ✗ |
| Table 2 F12/F13 rows | k1116/k1116b | ✗ |
| §5.2 Clark-West（weekly + daily CW 數字） | k1116c/e/g | ✗ |
| Table 6 K752 重寫後的新數字（v5） | k752 | ✗（gate 檢的是 v3 時代 T6 cells） |

**Gap B — 設計缺陷（比 Gap A 嚴重）**：gate 是 **JSON↔JSON** 比對（reproduce.py 內 hardcode「paper claimed value」再對 source JSON），**從不解析 .tex**。`decisions/errata_table3_bh_sharpe_canonical_fix.md` 已明文承認此缺陷。後果實證：K732 列 gate 檢查「BSI t-stat 5.58」對 JSON ✓ 通過，而 **tex 實際印 1.64** — 錯誤印刷值在 green gate 下存活了三個版本。

**Gap C — gate hardcode 值與已裁決 canonical 脫鉤**：gate 檢 Calendar IS t=-2.39（舊值），而 2026-04-19 決議的 canonical 是 -0.27；gate 與決議兩者都沒進 tex。

---

## 3. 學術深度檢視

### 3.1 Contribution 定位（J. Forecasting 視角）

- **Informative null + systematic horse race 在 JoF 是可發的類型**：JoF 歷史上接受嚴謹的 forecast-comparison null（Hansen-Lunde 2005「anything beat GARCH(1,1)?」正是本文的敘事錨點，發在 JAE）。13 families × 33 年 × 5 eras × 統一 pipeline 的廣度是真賣點。
- **v5 新增的兩個方法論 hook 是投稿賣點**：(i) publication-delay convention（release-calendar-respecting shift + TLT +3.74→+1.96 collapse 的自我糾錯敘事）；(ii)「null 論文必須用 Clark-West 防自利偏誤」的自覺 — 這兩點在 forecast-comparison 文獻裡少見，是 referee 會欣賞的誠實設計。
- **弱點**：(a) 61-63 頁對 JoF 太長（typical 25-35 頁），§7.8 channel heterogeneity 與 §7.10 allocation 可壓縮或移 appendix；(b) **全文 0 張圖**（`\includegraphics` 出現 0 次）— 實證論文無圖在初審觀感差；(c) 13 families 中 5/6/7 三個 family 在 Table 2 整列是 "---"，「thirteen」的完整性敘事有點虛。
- 定位建議維持 Codex v4 判斷：**IJF 第一 / JoF 同級可投 / JBF 第二**；修好後是 major-revision 級稿件。

### 3.2 方法論

v5 已具備的正確要素（驗證屬實）：Patton proxy-robust QLIKE、MCS、Holm-Bonferroni、Clark-West nested correction（k1116e/g 用 nw_lag=21 ✓ 是全 repo 該類實驗的模範實作）、publication-delay ALFRED 驗證、K752 era 表誠實重寫（Table 6 五 era 15 cells 與 JSON 逐格吻合，本審查全數重驗 ✓）。

**方法論剩餘核心問題 = 推論層的 HAC 系統性失效**（見 3.3）與 8 個未修 MAJOR（見 §4）。

### 3.3 統計嚴謹度 — DM/HAC 站點全清查（本審查核心新發現）

`.claude/rules/experiments.md` K1655 硬規則：`lag = max(h-1, ceil(h^{1/3}·n^{1/3}))`；h=1 時 h-1=0 的退化要當場警覺；**遺漏 HAC 是雙向誤設**。逐站點稽核結果：

| 站點 | 實作 | 有效 HAC lags | 餵論文哪裡 | 論文聲稱 | 判定 |
|---|---|---|---|---|---|
| `k1116b dm_hln` (L195-212) | `se=sqrt(gamma0/n)`×HLN | **0** | Table 2 F12/F13（2.55/3.61）+ Table 9 全 16 cells + TLT flip 敘事 | bandwidth=4 (L503) | **FAIL — 聲稱與實作不符** |
| `k1203 dm_hln` (L236-258) | 同上 | **0** | Table panorama 28 cells + UNIVERSAL_NULL_7/7 | 「DM-HLN」 | **FAIL** |
| `k1116c one_sample_t(nw_lag=0)` (L107-115) | 註解自稱「h=1 無 MA 結構」 | **0** | §5.2 weekly CW t=+0.12/−0.56/+0.14 | — | **FAIL — 註解正是 K1655 謬誤原文** |
| `k730 dm_test_func(h=5)` (L481-500) | Bartlett, `range(1,min(h,n//2))` | 4 | Table 2 F1（1.45/0.147 ✓ 可追溯） | bandwidth=22 (L503) | **FAIL — 4≠22；n≈4000 canonical≈16** |
| `k731 dm_test` (L384-401) | 註解寫 NW，程式只算 plain variance | **0** | Table 3 benchmark rows | — | **FAIL — 註解與程式不符** |
| `k736 dm_test(h=1)` (L505-522) | `range(1,h)` | **0** | Table 2/3 calendar DM | bandwidth=22 | **FAIL**（已在凍結 baseline） |
| `k747 dm_test(h=1)` (L383-401) | `range(1,h)` | **0** | Table 3 ERC DM 1.02（=JSON −1.019 ✓） | — | **FAIL**（已在凍結 baseline） |
| `k751` L416 | `stats.ttest_1samp` 標名 DM | **0** | strategy 段 | — | **FAIL — 冒名 DM** |
| `k778 dm_test` (L455-475) | `ceil(h^⅓·n^⅓)`≈17 | 17 | Panel D GJR≻AMEM 3.78 / GJR≻GARCH 4.76 / AMEM≻GARCH 2.85（全部 ✓ 可追溯至 `dm_tests_all_pairs`，方向一致） | bandwidth=22 | **PASS**（宣稱 22 實為 ~17，小口徑差需改文字） |
| `k799 dm_test` (L336-356) | canonical bandwidth | ✓ | grand evaluation | — | **PASS** |
| `k1116e/k1116g` CW | `nw_lag=21` | 21 | §5.2 daily CW（5 家族數字逐一驗證 ✓） | NW lag 21 | **PASS — 模範** |

**掃描盲區（governance 發現）**：`storage/ops/dm_hac_lag_baseline.json` 的 concern 只定義為「`range(1, h)` pattern」，因此 k730（函式名 `dm_test_func`）、k731（無迴圈變體）、k751（`ttest_1samp` 冒名）、k1116b/k1203（`dm_hln` plain-variance 變體）、k1116c（`nw_lag=0` 參數）**全部逃過凍結 baseline**。`docs/governance/2026-07/dm_hac_lag_class_sweep.md` 的盲區分析需補此 6 站點的 pattern class。

**對主結論的方向性影響評估**（依 K1655/k621 雙向原則，不預設安全）：

- **Beneficial-direction null（論文 headline）**：大概率存活。理由：(a) 有正確 HAC 的 4 個站點（k778/k799/k1116e/k1116g）全部支持 null；(b) beneficial cells 全部遠離 3.0（最大 CW t=+1.69）；(c) 22 日重疊視窗 loss differential 正自相關幾乎必然 → 修正後 |t| 收縮，null 更穩。**但 k621 前例證明負自協方差會反向放大 |t|，故仍需實際重算，不可用本段推理替代重算**。
- **有實質翻案風險的宣稱**：(i) F13「-3.61 顯著 harmful」與 F12 raw p=0.012 — K1655 同類 weekly NFCI 資料 acf(1)=0.68，proper HAC 後這些 |t| 可能掉破 3.0，「significant in the harmful direction」的敘事要重寫（好消息：v5 已把敘事重心移到 CW「redundant not harmful」，降級後傷害有限）；(ii) panorama 28 cells 中 |t|>3 的 8 個 cell（含 TLT +3.743 → 這正是 publication-delay 敘事的支點數字）；(iii) Table 9 的「strengthened/threshold flip」flag 全部要重標。

### 3.4 內部一致性 — 本審查新發現的矛盾（v4 review 未列）

1. **Table 3 ERC 列算術錯誤**（L553）：Sharpe 0.795 − 0.870 = −0.075，表印 ΔSharpe=−0.054；且 0.054 恰等於 Table 4 的 1.849−1.795（2023-26 窗對 50/50 的差）→ 該列混拼了兩個不同 benchmark/期間的數字；MDD −13.3 與 Table 4（2023-26 窗）相同但 Sharpe 差整整 1.0。同表其餘 9 列算術全部驗算 ✓。
2. **Intro L88 與 Table 2 直接矛盾**：「all Diebold-Mariano |t| < 3.0」— Table 2 F13 印 3.61。同句「maximum incremental R² = 0.038」把 in-sample ΔR²（F9）放進 out-of-sample 語境。
3. **K732 列（L483）三重斷裂**：印 1.64 = JSON `dm_stat_oos=1.637`（抄錯格原案）；DM 0.52/p 0.603 在 K732 JSON 完全找不到對應欄位（untraceable）；與 2026-04-19 canonical 決議（0.086/5.29/0.297/0.67/0.50）全列不符。F11 列同案（決議 -0.27/0.357/0.21 vs 印 -2.39/0.348/0.15）。
4. **F2 daily CW p=0.045 被寫成 "far short of significance"**（L519）：one-sided p=0.045 在傳統 5% 顯著。正確寫法是「未達 Harvey 3.0，但在傳統 5% 邊緣顯著」— null 論文對 borderline cell 措辭失真會被 referee 抓 self-serving。
5. **VaR 表自我矛盾**（L1064-1073）：note 稱「AMEM is the only model passing both Kupiec and Christoffersen at α=0.01」，但同表 GJR-GARCH(t) p=0.023/0.011 在 α=0.01 下也雙雙不拒絕。
6. **Table 2 F12 印 2.55 但自稱 corrected convention**（L492 vs L504 note）：k1116b corrected M3 = −2.54（Table 9 L884 自己也印 −2.54）。0.01 的小不一致，暴露 F12 列其實貼的是 shift(1) 值。
7. **「numerator 12 approximates long-run average VIX」**（L440）vs Table 5 全樣本 mean VIX=19.5（L628）— v4 review 已點名，未修。

### 3.5 抽查數字驗證清單（研究誠實記錄）

| 論文數字 | 來源 | 結果 |
|---|---|---|
| Table 6 全 15 cells + Harvey pass 1/5,1/5,2/5 | k752 `.part_d_competing_signals_by_era` | ✓ 全吻合 |
| 41.8% QLIKE「improvement」(L98/1038/1150) | k745 `improvement_pct = **−41.8**`；HAR-ABS daily 0.0771 **優於** 5-min HAR-RV 0.1093；N=37 PRELIMINARY | **✗ 方向翻轉 + 隱瞞 preliminary** |
| Daily CW：F2 +1.69(p .045)/F1 +0.69/F8 +0.11/F4 −0.22/F11 −1.50 | k1116e/k1116g `.specs.*.clark_west` | ✓ 全吻合（nw_lag=21 ✓） |
| Panel D 3.78/4.76/2.85 | k778 `dm_tests_all_pairs`（符號方向核對一致） | ✓ 可追溯（HAC ✓，bandwidth 實為 ~17 非 22） |
| k1121：S1 1.309/S5 1.312/p=0.966/OOS 1.975 | k1121_results.json | ✓ 全吻合 |
| Table 2 F1 1.45/0.147 | k730 `vol_prediction.dm_stat=-1.4532` | ✓ 可追溯（但 HAC h=5 非聲稱的 22） |
| Table 2 F3 DM 0.52/p 0.603 | K732 JSON 無此值 | **✗ untraceable** |
| Table 3 ERC 1.02 | k747 `erc_2-asset.t_stat=-1.019` | ✓ 可追溯（零 HAC） |
| BH 50/50 0.827 errata | k731 canonical + errata 文件 | ✓ 已落地 |

---

## 4. 風險與致命傷（依嚴重度排序）

1. **【致命-A】推論層 HAC 系統性失效 + 論文虛稱 bandwidth**（§3.3）。這不只是 robustness 問題：正文白紙黑字寫「Newey-West HAC bandwidth=22/4」而 source 實作是 0 或 4/5 lags — referee 拿到 replication package 一跑就 desk-reject，且觸及研究誠實紅線（聲稱與實作不符）。**必須全量重算，不可只改文字**。
2. **【致命-B】41.8% 方向翻轉**：intro（L98）、§8.2（L1038）、conclusion（L1150）三處把「5-min 比 daily **差** 41.8%、N=37 preliminary」引為「intraday frontier 開放」的正向證據。「未來研究去 higher-frequency」的整條 forward-looking 敘事目前建在一個方向讀反的數字上。
3. **【致命-C】K732/K736 抄錯格決議 34 個月未落地**（§3.4-3）：有正式 root-cause 文件、有 canonical 決議、有 execution checklist，然後三個版本沒人執行。這在投稿後被抓 = 資料誠信事故；在內部它是 process 失效的活證據（gate 不驗 tex → 決議沒有 enforcement owner）。
4. **【重大】8 個 v4 MAJOR 全數未修**，逐項在 v5 驗證仍在：abstract「all results survive HB」（L48）、「demonstrating time-invariance」（L48）、Harvey 3.0 framing、Basel 口徑無引用 + `k780_tail_first_es.py` Student-t quantile 未做 unit-variance scaling（rules 明定 K802 class）、CRRA「most retail investors」（L1122）、「frontier exhausted」+ regulator 背書（L1150/1154）、pre-spec 矛盾（L74 vs L77：safeguard (i) 稱 13 families 全部「defined before examining OOS results」與「12-13 added in this revision」同段互斥）、citation gaps（Acerbi-Szekely 被使用但無 bibitem；Basel、CBOE white paper、Carr-Wu 缺；engle2006/bollerslev2020 inline cite = 0 次，orphan）。
5. **【重大】reproduce gate 三重失效**（§2.2）：v3-era 覆蓋 + JSON↔JSON 設計 + hardcode 值與決議脫鉤。
6. **【中】** Table 3 ERC 列算術錯、F12 2.55/2.54、VaR 表 α=0.01 矛盾、F2 CW 措辭、「42 null results」（L1157，未驗證且不可驗證的計數宣稱）、0 figures、61+ 頁超長、AI 系統掛名風險已移除與否需在投稿前 compliance scrub 再查（audit_2026-06-10 MEDIUM 曾點名）。
7. **【ops】** research_program.md P7 stale「READY GREEN 98%」需降級改寫，否則下一個 session 會再被誤導。

---

## 5. 接下來的研究計畫

### P0（投稿 blocker，依序執行）

**P0-1 DM/HAC 全量重算（新 K 實驗，走 compute_queue）**
- 範圍：k1116b 全 16 cells（3 變體 × 4 資產）、k1203 全 28 cells、k1116c weekly CW、Table 2 daily families DM（k730 等）、Table 3 strategy DM（k731/k736/k747/k751）。
- 規格：一律 `volpred.stats.model_evaluation.dm_test` canonical bandwidth `max(h−1, ceil(h^⅓·n^⅓))`；**每個 cell 先報 loss differential acf(1)**（K1655 SOP），輸出新舊 t 對照表；weekly n=170 → bandwidth ≈ 6；daily n≈4600, h=22 → ≈37 與現行 22 的差也要報 sensitivity。
- 預期：beneficial null 存活（寫進 paper 作 robustness 賣點：「null robust to HAC bandwidth」）；harmful-direction 與 panorama 個別 cell 重標；Table 9 flags 重寫。
- 產出：`experiments/k17xx/`（新編號）+ 論文 Table 2/9/panorama 全面換數 + bandwidth 文字修正。

**P0-2 Claim 清洗（主線程修 tex，一個 commit）**
- 41.8% 三處：改為誠實方向（5-min pilot 目前**落後** daily，N=37 preliminary，frontier 是 open question 不是 evidence-backed promise）或整段降級刪除。
- 落地 K732/K736 2026-04-19 決議（decisions 文件有逐欄 spec 與 inline comment 模板，直接執行）。
- Table 3 ERC 列重算（用 k747 canonical 同期數字，ΔSharpe 對齊 benchmark 定義）；intro L88 兩處；F12 2.54；VaR 表 note；F2 CW 措辭；L440 「12 approximates long-run VIX」改為 target-vol 誠實表述。

**P0-3 reproduce gate v5 重建**
- 新 reproduce.py：加 **LaTeX 數字 extractor**（tex↔JSON 雙向，errata 文件早已指定此方向），覆蓋 v5 全部 tables（含 k1203/k1121/k1116b/c/e/g/k1137-43），match_rate ≥95% + green 才准進下一輪 review。
- 同 commit 修 `scripts/audit_dm_hac_lag.py` AST pattern 補 4 個逃逸變體（plain-variance dm/hln 命名、`nw_lag=0` 參數、`ttest_1samp` 冒名、異名 `dm_test_func`），enforcement owner 維持 `test_dm_hac_lag_ratchet.py`（anti-stacking：不開新 gate）。

### P1（投稿前必要，P0 後並行）

- **8 MAJOR 逐項修**：Holm family 口徑統一（abstract 限定「across the 10 regression tests」）；Harvey 措辭全文一致化為 approximate conservative；k780 Student-t unit-variance scaling 重算 VaR/ES 表 + Basel traffic-light 正式引用（BCBS 1996）或改稱自訂口徑；CRRA welfare 加 estimation uncertainty + 把「most retail investors」降級；pre-spec 段改為誠實兩階段揭露（刪 safeguard (i) 的絕對句）；conclusion 撤「frontier exhausted」與 regulator 背書；citation 補 Acerbi-Szekely (2014)、BCBS、CBOE VIX white paper、Carr-Wu (2009)，engle2006/bollerslev2020 補 inline 或移出 bib。
- **圖表**：至少 3 張 — era R² 穩定性圖（K752）、DM/CW forest plot（重算後全 cells 一圖收斂，正好展示 null 的 across-the-board 性質）、VT drawdown insurance 圖（K738）。
- **瘦身**：§7.8 channel heterogeneity 移 online appendix；§7.10 allocation 壓縮至 1 頁 + appendix；目標 ≤40 頁。
- research_program.md P7 列更新 + `experiments.md` 補 k1116e/g、k1203、k1121 索引。

### P2（投稿策略與後續）

- **期刊**：主推 **IJF**（forecast-comparison null + MCS/CW 方法論契合度最高；Hansen-Lunde 血統）；備選 J. Forecasting；JBF 需強化經濟意義段。短 null note 版（FRL）保留為 plan C。
- **F3/F9/F10 daily CW data-provisioning followup**（論文 L519 已自我披露）：pin CBOE put-call、Google Trends、VIX open 序列後補 3 個 CW cell，消掉「deferred」腳註。
- **Cover letter 賣點**：pre-registration 誠實揭露 + publication-delay convention + Clark-West self-check + HAC-bandwidth robustness（P0-1 的副產品）— 把這輪修復寫成方法論貢獻。
- 投稿前 compliance scrub（作者僅 Yi-Hao Lai、無 AI/volpred 字樣、acknowledgement 清理）走 `journal-review` skill。

---

## 6. Go/No-Go 建議

**現狀投稿：No-Go**（致命傷 A/B/C 任一單獨即構成 desk-reject 或誠信風險）。

**救援路徑：Go** — 論文骨架健康：資料廣度真實、v5 的三個 SEVERE 修復品質高（Table 6 重寫與 CW 段是誠實研究的正面示範）、正確 HAC 的站點全部支持主結論。P0 三項（重算 + 清洗 + gate 重建）估 1-1.5 週 compute+主線程，P1 一週，之後進 fresh paper-review-cycle（Codex primary + agy 二審）→ 通過才 `paper-update` 同步平台。**在 P0-1 重算完成前，disable 任何「已驗證 null」的對外引用（feed 文章、FB）以免傳播可能要重標的 cell 數字。**

---

*本報告未改動任何 .tex / 共享 JSON / git 狀態。所有 file:line 引用以 2026-07-11 22:40（台灣時間）的 working tree 為準。*
