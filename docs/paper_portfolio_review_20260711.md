# Paper Portfolio 總檢視與研究計畫 — Fable 深審輪（2026-07-11）

**背景**：Fable 額度 2026-07-12 16:00 到期前，用戶指示以 Fable 對所有學術論文與複雜研究做一次深度檢視並逐一產出研究計畫。14 個 Fable 深審 agent（13 論文 + 1 研究總線）於 2026-07-11 22:22–22:48 完成，全部輸出檔已由主線程逐一驗證存在且結構完整。

**單篇完整報告位置**：`paper/<name>/review_history/fable_deep_review_20260711/README.md`；研究總線：`docs/research_notes/fable_research_lines_review_20260711.md`。本文件是 portfolio 層彙整與主線程裁決；單篇細節（逐 table 抽查、行號證據）以各單篇報告為準。

---

## 1. 總覽表（13 論文）

| Paper | Verdict | Go/No-Go | 期刊裁定 | 最重發現 | 到可投估時 |
|---|---|---|---|---|---|
| vt-insurance-cost | **3.5/5** | GO 獨立成篇 | FRL | 數字抽查零不符；只剩 package 衛生（stale JSON、過期 gate） | **數天（最近可投）** |
| btc-gas-negative | 3.5/5 | Conditional GO 建成論文 | IJF | 「Student-t 元兇」是 QLIKE-specific，標題絕對化必改；需 LaTeX+reproduce 建置 | 數週 |
| taiwan-vt | 3/5 | 現狀 No-Go → 修後 Cond GO | PBFJ | TWII γ=0.272 被 provenance 證偽（實 0.105–0.109）→ 跨國敘事反轉；兩處 % comment 吞掉 PDF 整段 | 2026-08 中下旬 |
| forecast-tail-divergence | 3/5 | Conditional GO（命題改寫） | IJF 或 FRL 短文 | k850 尺度混淆（TX RV σ 打 0050 c2c VaR）→ 原命題恐為 artifact；被 IJF 兩篇 preempt | E1 gating 實驗後定 |
| garch-x-vix | 2.5/5 | GO revision | IJF → JEF → JoF | 實驗層健全；手稿層 Table 3 無來源數字 + Harvey 翻轉；**A4f errata 等 sign-off 是假等待點（從未投稿），直接修稿** | ~2-3 週 |
| volatility-absorption | 2.5/5 | 有條件 GO | JBF → JEF/IRFA | make-or-break：contemporaneous null 檢定還沒跑（模擬 proxy timing 錯配） | P0-1 實驗後定 |
| leverage-direction | 2/5→修後 3.5 | CONDITIONAL GO | IJF → EmpEcon → JoF | 中心 null 證據（K1592 0/8 Holm）做完卻沒進稿；K1591 弱結果被隱去；**stage2 rebuild 不需再投入（已做完）** | 6-8 工作天接線 |
| vt-crowding-abm | 2/5 | GO after major revision | **QF**（改推）→ JEBO | K1471 TF/MR 不利證據漏報 + RR_TF 5/5 惡化未報（誠實問題）；v4 GREEN PASS 作廢（自審假陽性第三例） | P0 寫作一週 → 8 月上旬 |
| vt-trend-following | 2/5 | GO revision / No submit | JPM/FAJ | Table 5 半更新嵌合體（列舊 vintage、Average 新 canonical，加總 28.7 vs 24.9 pp）；Sharpe 欄 13/13 不符 | 9-14 工作天 |
| prg-periodic-garch | 2/5 | No-Go submit / GO revision | FRL（字數超限待砍） | K880 重跑後 SPY canonical 漂移、main.tex 引舊值；K1544 裁定=改雙時點框架、timing flip 升 headline | 雙時點重寫後定 |
| vix-sufficiency | 2/5 | REJECT 現狀 / 可救 | J. Forecasting | 整篇 DM 推論層系統性 K1655 class（零 HAC）；K732/K736 決議從未落地；主結論 null 大概率存活 | 2-3 週 |
| eav-universal-magnitude | 2/5 | Major revision | 待定 | sign universality 站得住；magnitude ordering 被自家 θ_rel 欄反轉；abstract 自相矛盾；DM 無 HAC（稽核盲區） | 重估計級 |
| crypto-fear-channel | 2/5 | No-Go / GO for salvage | 待定 | **7 輪審查全漏的致命 bug**：FEVD shape 誤切，iid 雜訊也算出 90% spillover；headline 隨 Cholesky 排序翻號 | generalized FEVD 重建後定 |

另：`paper/k189_audit/` 非論文（只有 2 份 codex 審查檔）— 建議自 `storage/paper_pipeline_status.json` 移除或標 archive（governance 項，見 §5）。

## 2. 跨論文系統性診斷（比單篇發現更重要）

1. **失效點幾乎全在「手稿接線層」，不在「實驗證據層」**。13 篇中至少 8 篇（levdir、vt-trend、taiwan-vt、garchx、prg、vixsuff、abm、vt-ins）的底層實驗數字驗證乾淨或大體乾淨，垮掉的是：canonical 更新後 .tex 沒 rebind（prg K880、garchx 4.148、taiwan-vt γ）、證據做完沒進稿（levdir K1592）、表格半更新成嵌合體（vt-trend Table 5）、狀態檔沒更新造成假 stall（vt-ins）。**根因：reproduce gate 是 JSON↔JSON，從不驗 .tex 印出的數字。**
2. **K1655 DM/HAC class 比凍結 baseline 更大**。vixsuff 6 站點、eav k1148/k1149、taiwan-vt 的 paper-side experiments/*.py 全逃過 `audit_dm_hac_lag.py` 的掃描 pattern。
3. **同模型自審假陽性第三例確認**（abm v4 GREEN PASS）— 跨模型 review 硬規則維持，且舊 GREEN PASS 一律不可信任為現狀。
4. **不利證據漏報是最高風險類**（abm K1471 TF/MR、levdir K1591）— 研究誠實原則層級，任何投稿前必須清零。
5. **多輪審查會集體漏掉「陣列語意」級 bug**（crypto-fear FEVD 7 輪全漏）— 唯一有效防線是 null-input sanity check（iid 雜訊餵進 pipeline 應得無資訊結果）。

## 3. 投稿排序（monetization：學術權威線的最短路徑）

**第一梯隊（本月內可投）**
1. **vt-insurance-cost → FRL**：P0 = package 衛生（stale JSON 移除、reproduce gate 重跑、README 狀態同步），數天。
2. **leverage-direction → IJF**：P0 = K1592/K1591 進稿 + HM rebind K1256 + 26/14-asset 宣稱處置，6-8 工作天。不再投入 stage2 重型實驗。
3. **vt-crowding-abm → QF**：P0 = 純寫作（敘事單一化、scope 收斂 VT-only、K1471 誠實補報），一週。

**第二梯隊（8 月）**
4. **vt-trend-following → JPM/FAJ**：Table 5 canonical 重跑 + scrub 破句修復 + Calmar 重算，9-14 工作天。
5. **taiwan-vt → PBFJ**：TWII γ decision package + rolling gamma calendar-aligned 重跑 + comment-swallow 修復，8 月中下旬。
6. **garch-x-vix → IJF**：A4f 解凍直接修稿 + Table 3 canonical 重生 + K1393-faithful OOS 覆核實驗。

**第三梯隊（gated by 實驗結果）**
7. **volatility-absorption**：先跑 P0-1 contemporaneous null（事前寫死判定規則）— 過→JBF 升級；不過→重框或 archive。
8. **prg-periodic-garch**：雙時點框架重寫 + 六市場 close-convention 補跑 + FRL 字數砍半。
9. **vix-sufficiency**：DM 推論層全面 HAC 重算 + K732/K736 落地 + LaTeX-binding gate。

**孵化/重建**
10. **btc-gas-negative**：markdown → LaTeX + reproduce 建置，重框標題。
11. **eav-universal-magnitude**：magnitude ordering 降級為 sign universality 主軸 + DM HAC 重算。
12. **crypto-fear-channel**：generalized FEVD 重建（真值 ~18-22% spillover），headline 重寫。
13. **forecast-tail-divergence**：E1 尺度再校準 gating 實驗 → 完整論文或 FRL 方法論短文二擇一。

## 4. 新實驗清單（各深審提出的 gating/補強實驗，待編 K 入池）

| 來源論文 | 實驗 | 性質 | 優先 |
|---|---|---|---|
| volatility-absorption | contemporaneous null（h[t+1] proxy、10k sims、事前判定規則） | make-or-break | P0 |
| forecast-tail-divergence | E1 尺度再校準 HAR（std(z)/MZ/overnight 三 variant）重跑 k850/k854 trinity | make-or-break | P0 |
| garch-x-vix | K1393-faithful spec 延長 OOS 覆核（K1391 −2.03 反轉從未用正確 spec 重跑） | 投稿前必答 | P0 |
| prg-periodic-garch | 六市場 close-convention 補跑（PRG_tminus1 vs GJR/HAR；K1544 infra 複用） | 敘事最後一塊 | P0 |
| vt-trend-following | Table 5 canonical 重跑（pinned snapshot、IRX rf、跨市場 joint block bootstrap） | 修致命傷 | P0 |
| taiwan-vt | rolling gamma calendar-aligned snapshot 重跑 → Table 2 rolling block 重建 | 修致命傷 | P0 |
| crypto-fear-channel | generalized FEVD 重建 + K1025b data pinning | 重建 headline | P1 |
| vix-sufficiency | DM 推論層 HAC 全面重算（k1116b/k1203/k1116c） | 修 K1655 class | P1 |
| eav-universal-magnitude | k1148/k1149 DM HAC 重算 | 修 K1655 class | P1 |

**研究總線 P0**（非論文，詳見 `docs/research_notes/fable_research_lines_review_20260711.md`）：
- 方法論債務 sprint（K1681 Clark-West、nested-DM sweep、dm_hac_lag_baseline 139 站點縮減）
- Mincer-Zarnowitz 全平台校準審計（零資料成本、不會 NULL）
- 迷思驗證 batch 2（定期定額 vs 一次投入、高股息 ETF vs 0050、融資餘額反指標）
- Anti-NULL 規則入 refill：power pre-screen + 兩死弧模板黑名單（外生 shock→RV event-window ~19 NULL；covariate→HAR 5 連 NULL）
- 資源配比：論文收斂 40% / 方法論債務 20% / 新實驗 25% / 策略 15%

## 5. Governance / 流程修正（跨論文根因，依 anti-stacking 收編既有 owner）

1. **LaTeX-binding gate**（根治 §2-1）：reproduce gate 增加「.tex 印出數字 ↔ canonical JSON」驗證層（pdftotext 或 tex-parse）；owner = 各論文 reproduce.py 慣例 + `scripts/check_paper_compliance.py`。同時加 comment-swallow lint（taiwan-vt 兩處 % 吞段教訓）。
2. **dm_hac_lag 稽核器盲區補掃**：`scripts/audit_dm_hac_lag.py` 擴 pattern（`paper/*/experiments/*.py`、`dm_hln`/`var(d)/T` 變體、`t_stat` priority keys）；baseline 只准變少的 ratchet 不變。
3. **k189_audit 移出 paper pipeline**（非論文）。
4. **K1544 編號碰撞治理**：experiments/K1544（term-spread NULL）與 k1544_prg_fair_info_gjr 雙佔編號 → 重編號 + error_log。
5. **Null-input sanity check 慣例**：任何 spillover/decomposition 類 pipeline，投稿前必跑 iid 雜訊 placebo（crypto-fear FEVD 教訓）。
6. **舊 GREEN PASS 全面除魅**：pipeline status 中凡引用 2026-06 前 verdict 的 stage 註記，以本輪 fable review 為準。

## 6. 對 5 missions 的落點

- **Mission 3（論文）**：最短變現路徑 = 第一梯隊 3 篇（FRL/IJF/QF）本月投出；本輪已把「哪篇差幾天、哪篇差一個實驗」全部量化。
- **Mission 2（研究）**：9 個 gating/修復實驗 + 研究總線 13 條新方向，refill 池未來 4-6 週不缺高價值工。
- **Mission 1（文章）**：迷思 batch 2 與方法學發現（FEVD bug、尺度混淆）都是高分享性文章素材。
- **研究誠實**：本輪抓出的漏報/嵌合/證偽項在任何投稿前清零 — 這是學術權威護城河的直接投資。
