<!-- STATUS-BADGE: type=research-lines | health=declining-marginal-alpha | p0=3-tasks | updated=2026-07-11 -->

# EXECUTION — 非論文研究總線

> **BADGE** · `type=research-lines` · `health=邊際 alpha 率崩跌（產出量頂級）` · `p0=3 tasks` · `dead-arcs=2（外生 shock event-window / 新 covariate 進 HAR）` · `resource=論文40/債務20/新實驗25/策略15` · `updated=2026-07-11`

_最後更新：2026-07-11（Fable 深審輪）。本檔是 VolPred「研究方向組合」的可續作執行計畫；深審全文（各面向逐 K verdict、飽和診斷、資源配比推導）見 `docs/research_notes/fable_research_lines_review_20260711.md`，portfolio 層裁決見 `docs/paper_portfolio_review_20260711.md` §4。_

> 這不是一篇論文，是**研究方向的投資組合**。所以本檔追蹤的不是「單篇收斂到可投」，而是「組合是否持續命中高 ROI 象限、避開已抽乾的 NULL 弧」。

---

## 1. 最終目標

讓研究組合**持續產出高價值 alpha**（命中方法論/測量、台灣獨佔、迷思軸、淨成本工程等高 ROI 象限；避開已死的 NULL 弧），服務五大 missions —— 研究深度是內容護城河（M2）、學術權威是機構信任來源（M3）、命中率高的軸直接餵文章與曝光（M1/M5）、策略化副產品進付費 pipeline（M-C）。

**一句話定調（本輪 headline）**：組合的**產出量與方法論紀律是頂級的**（K1600+ 實驗、DM/HAC class sweep、provenance gate、10 次 ML ceiling 裁決），但**邊際 alpha 產出率已崩跌** —— 繼續用「免費資料 × 外生 proxy × 日頻 RV」象限量產註定 NULL 的 K，是在對枯井加深鑽頭。轉向 = 降新實驗量、升單筆期望值、把研究 token 重配到論文收斂與方法論債務清償。

---

## 2. 當前狀態（組合健康度快照）

| 指標 | 值 | 來源 |
|---|---|---|
| 新實驗 NULL / directional-only 率（2026-06~07） | **估 > 80%** | 深審 §1、§3 逐筆清單 |
| 已死 NULL 弧 | **2 大弧結構性死透**（見下） | 深審 §3.1 |
| ML ceiling 確認次數 | **10 次**（K618→K1535）；C14 已凍 4 筆至 2026-09-04 | 深審 §2-A、§3.1 |
| DM/HAC lag 凍結 baseline | **139 站點**（`storage/ops/dm_hac_lag_baseline.json`，只准變少） | 深審 §1-3、experiments.md rule |
| 最健康面向 | **TW（台灣線）**，飽和約 5 成、護城河加深中 | 深審 §2-TW |
| pending 研究工（next_tasks） | experiment 5 / platform_ops 3 / daily_article 1 | 深審 header |

### 2.1 兩大 NULL 弧已死（證據，勿再撿回）

| 弧 | 連 NULL 證據 | 判定 |
|---|---|---|
| **A. 外生 shock → 次日 RV event-window** | K1363/K1364/K1367/K1487/K1508/K1514/K1519/K1529/K1537/K1550/K1602/K1604/K1668/K1676/K1680/K1682/K1683 + k1614/k1615（directional-only）≈ **19 筆** | **死**。免費 proxy 資訊上限 + event n 太小 |
| **B. 新 covariate → HAR OOS 增量** | K1613（DIRECTIONAL_ONLY）/ k1616（NULL）/ K1617（NULL）/ K1618（NULL_WITH_WEAK_SECONDARY）/ k1619（NULL/NEGATIVE）**5 連**（07-03~07-09）+ 前期 K1337v2/K1432/K1516/K1518/K1655 等 **30+** | **死**（例外：獨佔 tick / point-in-time vintage 級資料可豁免，見 K1666 PDV pass） |

**結構性死因（非選題不夠聰明）**：K1520 教訓為總綱 —— 日頻免費資料裡 `VIX_{t-1} + lagged RV` 已吸收幾乎全部可得資訊，任何 apparent edge 拆穿後多是 VIX/regime 資訊的重新包裝；加上 Harvey |t|>3 gate 對「1-3% QLIKE 微增量、n≈2000-4000」題型 power 天生不足 —— 這類設計**在 dispatch 前就能算出必然 NULL**。

### 2.2 還有 alpha 的象限（命中率差一個數量級）

1. **測量/評估方法學層**（內部資料、零成本、每筆都提升全平台推論品質）：K1666 PDV range-proxy CONDITIONAL_PASS（QLIKE +8.79%，DM t=−4.53）、K1624 level-shift vs long-memory 識別、K1638 distribution-evaluation layer、K1655 GaR true-PIT 更正。
2. **台灣獨佔資料**：K1374 除息日 vol（ratio 1.342，Welch t=4.02）、magnet effect 2015 自然實驗（continuation 減弱 t=−4.20）、K1671 電子五哥爆量（2317.TW BH q=0.0265）、0050 5-min pipeline 修後與 TAIFEX r=0.902。
3. **迷思驗證軸**（reader-facing，命中率遠高於學術 batch）：首批 6/6 完成，K1640（VIX 破 30/40）half-true、K1671 partial。
4. **5-min RV 資料資產解鎖中**：TAIFEX 多年（K1582 n_oos=1697）、0050.TW 108 天、SPY ~114 天（234 個日檔在 `data/intraday/`）。
5. **論文素材弧**：Direction B（forecast-loss ⊥ tail-coverage divergence，k850 DM t=−5.60 但 1% VaR 不過）、C+（ML ceiling 資訊不對稱裁決）、D（複雜避險 OOS 無加值）。

### 2.3 各面向飽和度（研究總監估計值，非統計量）

A 波動率模型 9 成 · B VaR/ES 6 成 · C 找新 VT alpha 9 成 / 淨成本工程 3 成 · D 理論 8 成 · G 外生 shock 象限 10 成（死）/ 計量方法 5 成 / 台灣 4 成 · I 期貨避險 7 成 · **TW 台灣線 5 成（最健康，加碼）**。

---

## 3. 待辦（P0 / P1 / P2 — 13 條方向）

> 每條含：動機 / 設計概要 / 資料（皆免費或本機獨佔）/ 成功-kill 標準 / 貢獻 / 狀態。狀態一律起始 ⬜ TODO；派工前先 `ls experiments/` + `ls .claude/worktrees/` 查 K 編號不撞。

### P0 — 立即（本週起）

- [ ] **⬜ P0-1｜方法論債務清償 sprint**（接續起點）
  - **動機**：已發表結論可信度 = 學術權威 = monetization 護城河；三項已入 queue（P2/P3 pending）但無人推進。
  - **設計概要**：(a) K1681 Clark-West nested-DM 重跑 + nested-DM misuse class sweep；(b) 按 `scripts/audit_dm_hac_lag.py` 掃描結果批次重跑受影響 cells，`dm_hac_lag_baseline.json` 139 站點分批縮減；(c) 結論翻轉照研究誠實 §6 回溯更正（更新 knowledge/feed/paper + error_log）。
  - **資料**：全內部。
  - **成功 / kill**：成功 = baseline 只減不增 + 產出翻轉清單；**kill = 無（治理義務）**。
  - **貢獻**：全部論文 + 平台可信度（M2/M3）。

- [ ] **⬜ P0-2｜Mincer-Zarnowitz 全平台預測校準審計**（backlog line 493，零資料成本）
  - **動機**：forecast-eval 標配、庫內從未做；直接提升 risk-forecast 頁可信度；同時處理 K1660 揭露的 GARCH 家族 stored evaluation Parkinson target 錯尺度（median fc/Parkinson=1.73 vs fc/r²=1.07）。
  - **設計概要**：對現有 HAR/GARCH 預測輸出跑 MZ 迴歸（斜率=1、截距=0 joint test）+ per-model bias 表 + bias-correction 後 QLIKE 重評；GARCH 家族 realized target 改 r²/5-min。
  - **資料**：內部 forecast 庫。
  - **成功 / kill**：成功 = 每模型校準表 + 修正建議；**「全部無偏」也是可發表 audit（不落 NULL）**。
  - **貢獻**：M2/M4；risk-forecast 產品可信度。

- [ ] **⬜ P0-3｜迷思驗證系列 batch 2（3 題）**
  - **動機**：首批 6/6 完成、half-true 率高、boss msg154 directive、天生 reader-facing、命中率遠高於學術 batch。
  - **設計概要**：3 題 =（i）定期定額 vs 一次投入、（ii）高股息 ETF vs 0050 長期報酬、（iii）融資餘額 / 散戶多空比反指標。沿用首批模板：明確 `shift(1)`、FDR/HAC gate、null 也是好文章。
  - **資料**：yfinance / TWSE 免費。
  - **成功 / kill**：成功 = 正式檢定 + 文章；**kill = 資料不可得才換題**。
  - **貢獻**：M1/M5 直接轉換。

### P1 — 兩週內排入

- [ ] **⬜ P1-4｜Direction B 論文起草**：forecast-loss ⊥ tail-coverage divergence
  - **動機**：語料庫最扎實的新論文方向（k850 DM t=−5.60 但 1% VaR 不過；k854/k824/k799/k800 支撐）。
  - **設計概要**：主線程 `.md` 大綱 + 補 1-2 個 cross-asset divergence cell（GLD/TLT/0050）。**論文寫作留主線程**，不丟 background agent 改 .tex。
  - **資料**：內部 + yfinance。
  - **成功 / kill**：成功 = 大綱 + 補強 cell 過 Codex review；kill = cross-asset 不重現則降級為 FRL short note。
  - **貢獻**：面向 B / M3 新論文。

- [ ] **⬜ P1-5｜Bottom-up vs top-down VaR/ES aggregation**（07-09 batch 中高信心）
  - **動機**：FRTB 2025 上路時效、aggregation direction 庫內零覆蓋、B 是 monetization 對接最強面向。
  - **設計概要**：SPY/TLT/GLD/HYG/QQQ；成分 VaR 加總 vs 組合直估；Kupiec / Christoffersen / DQ / ES backtest + MCS。
  - **資料**：yfinance。
  - **成功 / kill**：成功 = 任一方向系統性勝出**或** robust tie（皆可發）；**kill = 無**。
  - **貢獻**：面向 B、機構內容。

- [ ] **⬜ P1-6｜淨成本 VT 工程 pair**：no-trade band（line 485）+ regime-gated VT（line 492）合併一個 K
  - **動機**：策略頁直接受益；輸出是 break-even 成本表**不落 NULL 弧**；boss standing directive（策略持續增加）+ memory（開發新 > audit 舊）支持。
  - **設計概要**：TAIEX/SPY VT 加 21d 訊號平滑 + 帶寬；毛 vs 淨對照（台股手續費/證交稅參數）；對照「僅高 vol regime 啟動」開關。
  - **資料**：yfinance + 成本參數。
  - **成功 / kill**：成功 = turnover 下降 × 淨 Sharpe 保持的 frontier 表；**kill = 無**。
  - **貢獻**：面向 C、策略上架 pipeline。

- [ ] **⬜ P1-7｜TAIFEX intrinsic-time RV**（07-11 batch；本機 tick 獨佔，豁免黑名單）
  - **動機**：改「採樣時鐘」非換 estimator，與 K1613 noise-robust（directional）正交；獨佔資料豁免死弧黑名單。
  - **設計概要**：clock / trade / hitting / business-time RV → 同資訊 HAR，OOS QLIKE、horizon-specific DM-HLN、MCS、block bootstrap。
  - **資料**：本機 TAIFEX tick。
  - **成功 / kill**：成功 = 任一 intrinsic clock 過 Harvey **或** robust 等價（等價也可寫方法論文章）；kill = measurement-error 比較即無差異 → 記 NULL 收弧。
  - **貢獻**：面向 A 測量層。

- [ ] **⬜ P1-8｜台股當沖佔比 × 次日 RV**（line 554）
  - **動機**：TWSE 免費日頻、國際罕見、TW 線加碼方向。
  - **設計概要**：當沖比率 `shift(1)` → 次日 RV 增量 + 雙向 Granger（vol 吸引當沖 vs 當沖放大 vol）；HAC + Harvey。
  - **資料**：TWSE 免費。
  - **成功 / kill**：成功 = 任一方向顯著；**kill = NULL 也可寫（散戶行為文章角度）**。
  - **貢獻**：面向 TW、M1/M5。

### P2 — 一個月內視產能

- [ ] **⬜ P2-9｜CBOE 選擇權賣方 overlay regime 擇時**（line 1470）
  - BXM/PUT/CLL/CNDR 官方免費 index、IV percentile / term-structure gate、beta-adjusted Sharpe（K544 Israelov 規則）。資料 = CBOE 官網免費 CSV。貢獻 = 策略多元化 + 讀者感興趣。

- [ ] **⬜ P2-10｜TSM ADR vs 2330 價格發現與創紀錄溢價**（line 1487）
  - 隔夜/日內拆解 lead-lag；K1626 已有 as-of alignment gate 基礎；ADR 溢價歷史高位 = 現成敘事鉤。資料 = yfinance + 本機日內。貢獻 = TW 線 + 高共鳴敘事。

- [ ] **⬜ P2-11｜Realized covariance HAR → GMV 組合 OOS**（line 491）
  - Cholesky / log-matrix 參數化 vs shrinkage/EWMA；多變量幾乎零覆蓋。資料 = yfinance。貢獻 = 面向 A 多變量 + 組合產品。

- [ ] **⬜ P2-12｜Realized-beta vs constant-beta 最小變異避險比率賽馬**（07-09 batch）
  - 同時補 Direction D 論文需要的 OOS HE cell（Reeves-Wu 線）。資料 = yfinance / 本機 5-min。貢獻 = 面向 I 收斂 + 論文素材。

- [ ] **⬜ P2-13｜Conditional MCS / Giacomini-White regime-conditional 賽馬**
  - **前置條件 = P0 起全實驗存 loss sidecar**；先對新產生的 series 做，**不回填舊 ledger**（K1259 教訓：舊 ledger 無逐日 loss）。資料 = 內部。貢獻 = 面向 A 評估層。

---

## 4. 凍結 / 等待清單（明確不做，防 refill 又撿回去）

- 全部「外生 shock event-window」與「新 covariate 進 HAR」backlog 條目（除非資料是本機獨佔 tick 或 point-in-time vintage 級）。
- ML 架構 4 筆維持 `blocked_until=2026-09-04`（C14 決議）。
- **Data-unlock calendar（建議寫入 refill 機制）**：
  - 0050.TW 5-min 累積至 252 天 → 約 **2027 Q1**，解鎖 formal HAR-RV gate（K1664 已預註冊；現 108 天，pilot +31% QLIKE 但 DM t=−1.64）。
  - VIXTWN 252 天 → 解鎖 Q6 ratio 穩定性 gate（K1323）。
  - K1536 crypto ML 裁決 → 等 Binance 5-min ingest 建置後再派。
- 中信心 ⚠️ 題（VC-vintage、州最低工資 RDD 等）：dispatch 前查證義務未解除，維持凍結。

---

## 5. 禁止事項（研究線 anti-NULL 硬規則）

適用**所有新 dispatch**（設計總則）：

- **模板黑名單（死弧勿再派）**：「外生 shock event-window」與「新 covariate 進 HAR」兩模板停派。豁免條件 = 資料是本機獨佔 tick 或 PIT vintage 級（僅此二例）。
- **Power pre-screen（dispatch 前）**：若題型是「covariate 微增量」且期望 QLIKE 改善 <3%、n<3000，**直接改設計或不派** —— 這類設計 power 天生不足，用完整實驗成本去確認可事前算出的 NULL 是負 ROI。
- **輸出型式優先序**：break-even/成本表、校準審計、識別性檢定 **>** Harvey gate 點預測賽馬。
- **每個新 DM-producing 實驗必存 per-day loss sidecar**（`date, loss_a, loss_b, d_t`）—— K1259/GR-fluctuation 教訓，否則 conditional MCS / fluctuation test 永遠做不了。
- **不對日頻點預測再疊模型**（A 面向 9 成抽乾）；A 線只在測量層 / 多變量 / 評估層三個 sub-axis 動手。
- **不開新理論線**（D 面向自然出口是論文，非新實驗）。
- **refill 候選排序修正（單一 enforcement owner，勿疊層）**：把排序改為 `迷思軸 > 方法學/測量 > 台灣獨佔 > 淨成本工程 > 學術 batch`，並加 data-unlock calendar 與 power pre-screen 兩欄 —— 落在 `scripts/refill_task_pool` 既有 dedup/排序邏輯內，**不另建新 gate**（anti-stacking）。

---

## 6. 資源配比（研究 token 建議，相對目前「量產新 K」為主的分配）

| 用途 | 配比 | 理由 |
|---|---|---|
| **論文收斂（M3）** | **40%** | M3 是全組合瓶頸：P2 γ provenance body 修正、P6 PRG forecast-convention 決策、P4ins v4 review、P5/P10 major revision、Direction B 起草。素材不缺，缺的是 revision 收斂 token。 |
| **方法論債務 + 校準（P0-1/P0-2）** | **20%** | 直接影響已發表數字可信度；有機械 gate 可批次化；每筆同時強化論文線。 |
| **新實驗** | **25%** | 按 §5 anti-NULL 規則執行 P1/P2 清單。**量要降、單筆期望值要升** —— 目前新實驗 NULL 率 >8 成，原速量產是負 ROI。 |
| **策略開發（M-C）** | **15%** | 淨成本工程 + overlay timing + 迷思軸的策略化副產品；boss directive 維持策略線活水但不以「找新 alpha」為目標函數。 |

**對文章 pipeline（M1/M5）的含義**：迷思軸 batch 2 + 既有 uncovered K 蒸餾 + 方法論審計科普化（「我們如何抓自己的統計錯誤」是高信任度內容）足以支撐 draft 池；**不需要為了餵文章而開新實驗** —— 這正是過去兩個月 refill 迴圈的隱性驅動力之一，應明確切斷。

---

## 7. DoD（本執行檔的收斂判準）

> 研究線是持續組合，沒有「全部 done」的終點；以下是 **P0 批次完成** + **組合健康 invariant** 的可驗證判準。全部起始 ⬜。

- [ ] ⬜ **P0-1** dm_hac_lag_baseline 只減不增（139 → 更少），翻轉清單產出並回溯更正；K1681 Clark-West nested-DM 重跑落地並 Codex reviewed。
- [ ] ⬜ **P0-2** MZ 校準表 per-model 產出 + K1660 Parkinson target 錯尺度修正落地（GARCH 家族 realized target 改 r²/5-min）。
- [ ] ⬜ **P0-3** 迷思 batch 2 三題正式檢定完成 + 至少 1 篇 reader-facing 文章發佈。
- [ ] ⬜ **anti-NULL 規則機械化**：power pre-screen + 兩死弧模板黑名單寫入 `scripts/refill_task_pool` 候選排序器（單一 owner，非散文提醒）。
- [ ] ⬜ **loss sidecar 慣例上線**：新 DM-producing 實驗一律存 `date, loss_a, loss_b, d_t`（解鎖 P2-13 conditional MCS）。
- [ ] ⬜ **資源配比落實**：下一個統計週期新實驗量下降、論文收斂 token 佔比升至 ~40%（以 work_log 抽查驗證）。
- [ ] ⬜ **health invariant**：新實驗 NULL/directional 率脫離 >80% 區間（命中高 ROI 象限的比例上升）。

---

## 8. 進度日誌

| 日期 | 動作 | 摘要 | commit |
|---|---|---|---|
| 2026-07-11 | Fable research-lines review | 深審完成，13 條方向待派 | f913ed68c |

---

## 9. 接續 Prompt（下次開工直接貼；每個可獨立派 experiment agent）

### 9.1 方法論債務 sprint（= P0-1，最高 ROI，接續起點）

> 讀 `docs/research_execution_plan.md` §3 P0-1 後執行方法論債務清償 sprint。三項：(1) 派 agent 重跑 K1681 Clark-West nested-DM + nested-DM misuse class sweep（原用 plain DM 比較 nested model 者一律改 Clark-West）；(2) 跑 `uv run python scripts/audit_dm_hac_lag.py` 取受影響 cells，批次重跑並把 `storage/ops/dm_hac_lag_baseline.json` 139 站點分批縮減（ratchet：只准變少）；(3) 任何結論翻轉照研究誠實 §6 回溯更正 knowledge.json / feed / 對應論文 + 記 `docs/error_log.md`。成功 = baseline 只減不增 + 翻轉清單；此為治理義務，無 kill 條件。每個 DM-producing 重跑必存 per-day loss sidecar。完成後接 P0-2。

### 9.2 Mincer-Zarnowitz 全平台校準審計（= P0-2，零資料成本、不會 NULL）

> 讀 `docs/research_execution_plan.md` §3 P0-2 後派 experiment agent 做 MZ 校準審計。範圍：對現有 HAR/GARCH 預測輸出跑 Mincer-Zarnowitz 迴歸（realized = a + b·forecast，joint test a=0、b=1）+ per-model bias 表 + bias-correction 後 QLIKE 重評。同時修 K1660 揭露的 GARCH 家族 stored evaluation Parkinson target 錯尺度（median fc/Parkinson=1.73 vs fc/r²=1.07）—— realized target 改 r²/5-min 後重算。資料全內部（forecast 庫）。成功標準 = 每模型校準表 + 修正建議；「全部無偏」也是可發表 audit，不落 NULL。輸出可科普化為 risk-forecast 頁可信度文章。先讀 `docs/error_log.md` + 搜 knowledge.json 相似 K；完成後 Codex review 才寫 knowledge。

### 9.3 迷思驗證系列 batch 2（= P0-3，reader-facing、命中率最高）

> 讀 `docs/research_execution_plan.md` §3 P0-3 + `.claude/skills/anti-ai-style/` 後派 agent 做迷思驗證 batch 2（沿用首批 6/6 模板）。三題：(i) 定期定額 vs 一次投入（DCA vs lump-sum）、(ii) 高股息 ETF vs 0050 長期報酬、(iii) 融資餘額 / 散戶多空比反指標。設計硬規則：明確 `signal.shift(1)`、隨機程序固定 seed、FDR/HAC gate、null 也是好文章（half-true / partial 結論最有分享性）。資料 = yfinance / TWSE 免費。成功 = 正式檢定 + 文章；kill = 資料不可得才換題。每題完成走 feed-publisher（非事件驅動 → draft 進池），reader-facing 文末附懶人包圖組。

### 9.4 P1 批次派工（P0 落地後）

> 讀 `docs/research_execution_plan.md` §3 P1 後，依序或並行派 P1-4~P1-8（Direction B 論文起草留主線程；P1-5 top-down/bottom-up VaR aggregation、P1-6 淨成本 VT 工程、P1-7 TAIFEX intrinsic-time RV、P1-8 台股當沖 × 次日 RV 可派 experiment agent）。派工前對每題跑 §5 power pre-screen；P1-7 為本機 tick 獨佔資料，豁免死弧黑名單。每個 DM 實驗存 loss sidecar。
