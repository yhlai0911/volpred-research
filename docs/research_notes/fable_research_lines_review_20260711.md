# 非論文研究線全面深審 — 研究總監檢視報告

**日期**：2026-07-11（台灣時間 22:37）
**範圍**：面向 A（波動率模型）/ B（VaR-ES）/ C（策略）/ D（理論）/ G（跳躍探索）/ I（期貨避險）/ TW（台灣線）+ 期刊主題挖掘 refill 機制
**依據**：research_program.md 全文（1552 行）、storage/next_tasks.json（pending 9 筆：experiment 5 / platform_ops 3 / daily_article 1）、experiment_experiences.json（80 條）、docs/error_log.md 近一個月、docs/strategy-registry.md、experiments/k16xx README verdicts（逐一 grep 驗證）
**驗證聲明**：本文引用的 verdict / 統計量均直接讀自上述檔案；無法獨立重驗的彙總數字（如弧線連 NULL 計數）標明來源行號並附本人親自 grep 驗證的 K-id 子集。

---

## 1. 執行摘要

**組合健康度一句話**：產出量與方法論紀律是頂級的（K1600+ 實驗、DM/HAC class sweep、provenance gate、10 次 ML ceiling 裁決），但**邊際 alpha 產出率已經崩跌** —— 2026 年 6-7 月完成的新實驗 NULL / directional-only 率估計超過八成（見 §3 逐筆清單），refill 機制被「免費資料 × 外生 proxy × 日頻 RV」這個已抽乾的象限鎖死，繼續量產註定 NULL 的 K 是在浪費研究 token。

**三個最重要發現**：

1. **兩大 NULL 弧確認死透，而且死因是結構性的，不是選題不夠聰明。**
   - 弧 A「獵奇外生 shock → 次日 RV event-window」：本人親自驗證 K1602（tax-loss crowding，NULL）、K1604（sports betting，NULL）的 README/knowledge verdict；research_program.md 內同模板另有 K1363（Fedspeak）、K1364（ETF sampling）、K1367（climate-news duration）、K1487（GDELT novel-risk）、K1508（AI 電力）、K1514（關稅相關結構）、K1519（EPU regime trigger）、K1529（FOMC credit 前哨）、K1537（biodiversity）、K1550（squeeze risk）、K1668（氣候政策 CPU）、K1676（黃金 macro moderator）、K1680（地理注意力）、K1682（跨所價差）、K1683（Treasury crowding）等 —— **同模板可數出 ~19 筆 NULL / proxy-limited**（超過 program 檔 line 495 自報的 ~15）。
   - 弧 B「新 covariate → HAR OOS 增量」：親自驗證 K1613（noise-robust RV，DIRECTIONAL_ONLY）、k1616（cointegration ECT，NULL）、K1617（TVP factor loading，NULL）、K1618（semicovariance 預警，NULL_WITH_WEAK_SECONDARY）、k1619（staleness RV，NULL/NEGATIVE）5 連；更廣義 covariate 家族（K1337-v2 / K1432 / K1516 / K1518 / K1655…）自 6 月起再加 30+ 筆。
   - **結構性死因**：K1520 的教訓是總綱 —— 日頻免費資料裡，`VIX_{t-1} + lagged RV` 已吸收幾乎全部可得資訊；任何 apparent edge 拆穿後多是 VIX/regime 資訊的重新包裝。加上 Harvey |t|>3 gate 對「1-3% QLIKE 微增量、n≈2000-4000」的題目 power 天生不足，這類設計**在 dispatch 前就可以算出必然 NULL**。

2. **還有 alpha 的地方有清楚 pattern，命中率差一個數量級。** (a) **測量/評估方法學層**：K1666 PDV range-proxy CONDITIONAL_PASS（QLIKE +8.79%，DM t=-4.53）、K1624 level-shift vs long-memory 識別、K1638 distribution-evaluation layer、K1655 GaR true-PIT 更正 —— 全部用內部或既有資料、零新資料成本，且直接提升平台可信度。(b) **台灣獨佔資料題**：K1374 除息日 vol（PASS，Welch t=4.02）、magnet effect 2015 自然實驗（continuation weakening t=-4.20）、K1671 個股爆量（2317.TW BH-pass）、0050 5-min pipeline 修復後與 TAIFEX r=0.902。(c) **迷思驗證軸**（老闆 msg154）：首批 6/6 完成，K1640（VIX 破 30/40）half-true、K1671 partial —— reader-facing 命中率遠高於學術 batch。(d) **5-min RV 資料資產解鎖中**：TAIFEX 已有多年（K1582 n_oos=1697）、0050.TW 108 天、SPY ~114 天（234 個日檔在 data/intraday/）。

3. **方法論債務清償是當前最高 ROI 的「研究」工作。** K1655 觸發的 DM/HAC lag class sweep 已凍結 139 個站點 baseline（storage/ops/dm_hac_lag_baseline.json，只准變少）；K1681 Clark-West nested-DM 重跑與 nested-DM misuse class sweep 已入 queue（P2 pending）；K1660 揭露 GARCH 家族 stored evaluation 用 Parkinson target 錯尺度（median fc/Parkinson=1.73 vs fc/r²=1.07）；Paper2 TWII γ=0.272 provenance 崩壞（實際 ≈0.109，error_log 2026-07-09）。這些直接關係**已發表結論的可信度 = 學術權威 = monetization 護城河**，且多數已有機械 gate 可批次推進。

---

## 2. 各面向盤點

### 面向 A：波動率預測模型
- **現況**：秩序已確立 —— HAR 家族是日頻 |r|-proxy 王者（K530 DM=-15.45，1306 實驗最強）；A4f（VIX² multiplicative GARCH-X）是 GARCH-X 王者（K988 DM t=4.48）；exp-QLIKE combination 有真增量（K1377，2/3 資產 Harvey PASS）；ML ceiling 第 10 次確認（K1535 C+ 裁決program：文獻 ML 勝利 = M1 弱 baseline + M2 無檢定 + M3 資訊不對稱，非架構優勢）。新模型類近期全數落敗或不過 gate：MSM 贏 HAR 輸 EWMA（K1637）、SV/RSV 弱平均 edge 無 Harvey（K1648）、rough/fOU 不勝 HARQ（TAIFEX n=488）。
- **飽和度**：日頻點預測約 **9 成抽乾**。
- **值得繼續嗎**：值得，但只在三個 sub-axis —— (i) 測量層（PDV K1666 已開路；intrinsic-time RV、partial-day nowcast 在 backlog）；(ii) 多變量（realized covariance → GMV 幾乎零覆蓋）；(iii) 評估層（Mincer-Zarnowitz 校準審計、conditional MCS）。**不要再對日頻點預測疊模型。**
- **下一個最有價值問題**：0050.TW 5-min 累積至 252 天後的 formal HAR-RV gate（估 2027 Q1 解鎖；現 108 天，K1664 pilot +31% QLIKE 但 DM t=-1.64）。解鎖前用 TAIFEX 多年 5-min 做 intrinsic-time / reconciliation 題。

### 面向 B：VaR / ES
- **現況**：CF-Rolling 仍是王者（K1034 6/6 Trinity）；EVT-GPD competitive not dominant（2026-07-07）；CAViaR-AS competitive 無 Harvey edge（K1651）；conformal regime effect 確立（K1390）。**Direction B 論文素材（forecast-loss ⊥ tail-coverage divergence，k850 DM t=-5.60 但 1% VaR 不過）是實驗語料庫裡最扎實的未開發論文方向**（program line 818）。
- **飽和度**：約 **6 成**。單資產分配賽馬抽乾；未做的有 score-driven GAS joint VaR-ES、expectile/elicitability、bottom-up vs top-down aggregation。
- **值得繼續嗎**：**是，B 是 monetization 對接最強的面向**（FRTB 2025 上路、Basel IV ES 監理，機構 premium/顧問 tier）。
- **下一個最有價值問題**：Direction B 論文大綱（主線程起草）+ bottom-up vs top-down VaR/ES aggregation（07-09 batch 中高信心，免費多資產可跑）。

### 面向 C：投資策略
- **現況**：11 檔 active、3 檔高 Sharpe 正確拒絕上架（c2c timing 假象，audit 2026-06-21）。近期產出：K1505 提領規則 PASS（ruin 4.06%→2.17%，有成本）、K1532 rebalance 頻率 break-even 16-19bps（工程結論）、K1547 CTA crisis-alpha NULL、K1264 台指隔夜 gap REJECT（成本吃掉 81%）。VT 變體 overlay 全滅：季節性 / 槓桿 / stop-loss / CED / CDaR / CVaR-RP / CF-HMM sector rotation 全 NULL。
- **飽和度**：「找新 VT alpha」約 **9 成抽乾**；「淨成本工程 + 客群產品化」約 3 成。
- **值得繼續嗎**：是，但要**換問題定義** —— 從「找新 alpha」轉向「省成本 + 客群化」。這類題（no-trade band、regime-gated VT、rebalance frequency）的輸出不是 Harvey gate 而是 break-even 成本表，天然不落 NULL 弧，且直接餵策略頁與付費內容。boss standing directive（策略持續增加）+ memory（開發新 > audit 舊）支持此向。
- **下一個最有價值問題**：net-of-cost 平滑 VT + no-trade band（line 485，庫內 0 覆蓋）與 regime-gated VT（line 492）合併實作；CBOE 選擇權賣方 overlay regime 擇時（BXM/PUT/CLL/CNDR 官方免費 index，line 1470）。

### 面向 D：理論貢獻
- **現況**：VIX sufficient statistic 完成邊界刻畫（market-specific：SPY 內 PASS、cross-market NULL，K1315/K1316/K1098）；gamma-VT alpha 機制部分推翻（K1044 panel ρ=-0.209 NS）；copula asset-class boundary（Joe upper-tail 限 flight-to-safety pair）已進 Paper 3。
- **飽和度**：約 **8 成**。理論線的自然出口是論文，不是新實驗。
- **值得繼續嗎**：不開新理論線。**C+ program（ML ceiling 的資訊不對稱機制）是 D 面向最好的收斂出口** —— 「Why the Literature Keeps Finding ML Beats GARCH」已有 K1535 + K1533 兩個 reproduce-then-adjudicate 支柱，補 K1536（crypto devil's advocate）即可成文。
- **下一個最有價值問題**：K1536 crypto 5-min 裁決（需 Binance ingest）——若 crypto domain ML 真過 MCS，是「ceiling domain-bound」的可發表反例，兩面都有價值。

### 面向 G：跳躍式探索
- **現況**：**重災區**。期刊挖掘 40+ 批、累計 400+ 條 backlog，但 6-7 月完成的探索題幾乎全 NULL / proxy-limited（§3 清單）。G 面向已退化成「免費 proxy × 外生 shock → RV」的工廠化 NULL 生產線。例外亮點證明不是探索本身的錯：thematic ETF concentration（PASS_ETF_PROXY，4/4 gate，t 最高 7.00）、structured-product complexity（POSITIVE，3/33 過 Harvey+Bonferroni）、K1655 GaR true-PIT（方法論貢獻級 NULL）。
- **飽和度**：外生 shock 象限 **10 成（死）**；計量方法 / 微結構象限約 5 成；台灣獨佔象限約 4 成。
- **值得繼續嗎**：**縮編後值得**。凍結全部 event-window 模板；G 的存續 sub-axis 只留三個：計量方法前沿（intrinsic-time、reconciliation、estimation-risk inference audit）、可驗證事件源微結構（enforcement/fails/auction calendar 類，非新聞 keyword）、台灣獨佔資料。
- **下一個最有價值問題**：TAIFEX tick intrinsic-time RV（07-11 batch，本機獨佔資料，改「採樣時鐘」與 K1613 noise-robust 正交）。

### 面向 I：期貨避險
- **現況**：「複雜避險不勝簡單避險」三度確認 —— K1320 copula OHR 9 法全 p>0.08 vs DCC；K1548 台灣多幣別：full/static hedge dominates DCC-lite/HMM；naive-hedge robustness 文獻線同向。I4（VIX futures roll yield）依然 data-blocked。
- **飽和度**：約 **7 成**。方法賽馬抽乾；實務化與 contrarian 驗證未做。
- **值得繼續嗎**：低優先度維持。用戶專長（copula-GARCH hedging）使此線有論文選項（Direction D：動態相依 OOS 無加值，k920-K1320 素材），但需補 1-2 個 OOS HE-ratio run。
- **下一個最有價值問題**：realized-beta vs constant-beta 最小變異避險比率賽馬（07-09 batch 高信心 contrarian，Reeves-Wu 線）—— 它同時是 Direction D 論文需要的 OOS HE cell。

### 面向 TW：台灣市場專線
- **現況**：**最健康的面向**。核心結論穩固（8.63/VIX、VIX>VXEEM、TSMC 集中度）；新增 PASS 級發現：K1374 除息日 vol（ratio 1.342，t=4.02，含 outlier robustness）、magnet effect 7%→10% 自然實驗（continuation 減弱 t=-4.20）、K1671 電子五哥爆量（2317.TW BH q=0.0265）；基礎設施剛修好（0050 5-min session-boundary bug，修後 r=0.902）；K1664 HAR-RV pilot 方向性正確等資料。
- **飽和度**：約 **5 成**，且護城河（獨佔資料 + 中文讀者共鳴）仍在加深。
- **值得繼續嗎**：**是，加碼**。TW 線同時服務 Mission 1（文章）、2（研究）、5（曝光）且題目國際空白。
- **下一個最有價值問題**：台股當沖佔比 × 次日 RV（TWSE 免費日頻、國際罕見，line 554）；TSM ADR vs 2330 價格發現（K1626 已有基礎 + ADR 溢價歷史高位是現成敘事鉤）；颱風假復市 vol（台灣特有制度、國際零文獻）；EAV T+1 延伸（K1061-K1064 掛了三個月未做）。

---

## 3. 飽和診斷

### 3.1 已死的弧（證據）

| 弧 | 連 NULL 證據（本人驗證或 program 檔記錄） | 判定 |
|---|---|---|
| 外生 shock → 次日 RV event-window | K1363/K1364/K1367/K1487/K1508/K1514/K1519/K1529/K1537/K1550/K1602/K1604/K1668/K1676/K1680/K1682/K1683 + k1615/k1614 directional-only ≈ **19 筆** | **死**。免費 proxy 資訊上限 + event n 太小 |
| 新 covariate → HAR OOS 增量 | K1613/k1616/K1617/K1618/k1619 五連（07-03~07-09）+ 前期 K1337v2/K1432/K1516/K1518/K1655 等 30+ | **死**（例外：獨佔/PIT 級資料可豁免，見 K1666 PDV pass） |
| 日頻 ML 架構疊加 | 10 次 ceiling（K618→K1535）；C14 已把 4 筆凍結至 2026-09-04 | **死**，僅留 C+ 裁決 program 出口 |
| BMA / forgetting-factor 平均 | K1257 partial→K1300 CONFIRMED_FAIL | 死（program 已標段落結束） |
| VT overlay 變體 | K80/K81/K83/CED/CDaR/CVaR-RP/CF-HMM 全 NULL | 死（轉淨成本工程） |
| 複雜避險 vs 簡單避險 | K1320/K1548 + naive-hedge 線 | 死（轉論文素材 Direction D） |

### 3.2 還有 alpha 的弧

1. **測量/評估方法學**：K1666 PDV（pass）、K1624（level-shift 識別）、K1655（true-PIT 方法論）、K1638（evaluation layer）—— 內部資料、零成本、每一筆都提升全平台推論品質。
2. **台灣獨佔資料**：K1374、magnet、K1671、當沖/颱風/ADR 未開發題。
3. **迷思驗證軸**：首批 6/6 完成、2 條 half-true 可寫文章；後續候選 9 題現成（program line 1552）。
4. **淨成本策略工程**：K1532 已示範此類題必有可發表輸出（break-even 表而非 Harvey gate）。
5. **5-min 解鎖題**：TAIFEX 立即可用；0050/SPY 累積中，需 data-unlock calendar 而非硬做（K1521/K1582 教訓：n_oos<252 只能 pilot）。
6. **論文素材弧**：Direction B（divergence）、C+（ML 裁決）、D（hedging OOS 無加值）。

### 3.3 refill 補不出 fresh 主題的結構性診斷

1. **搜尋空間被約束擠壓到同一象限**：journal-discovery 的三重約束（免費資料 × 波動率 target × 2025-26 期刊趨勢）幾乎必然把候選映射到「外生 proxy → RV」模板。40+ 批後該象限 alpha 密度被自己抽乾，agent 已誠實回報「backlog 高度飽和、不硬湊」（07-08/07-09 batch），但 refill 機制仍每逢 pool 乾就再派一批 —— **機制在對著枯井加深鑽頭**。
2. **Gate 與題型的 power 錯配**：Harvey |t|>3 對「微增量 covariate」題（期望 QLIKE 改善 1-3%、n 2000-4000）power 不足，這類題**設計上註定 NULL**。目前沒有 dispatch 前的 power pre-screen，等於用完整實驗成本去確認一個可事前算出的結論。
3. **「等資料」沒有機制位**：許多題的正確答案是等（0050 5-min 252 天、VIXTWN 252 天、K1536 Binance ingest），但 refill 只有「現在補新題」一種動作，導致往更遠更弱的 proxy 找。缺一個 **data-unlock calendar**（何時、什麼資料、解鎖哪些預註冊題）。
4. **命中率高的軸沒有被制度性優先**：迷思軸與淨成本工程軸的「可寫文章率」遠高於學術 batch，program line 1552 已寫「refill 時優先從此軸抽」，但未進 refill 程式邏輯，仍是散文提醒（依 anti-stacking 原則，應把這條規則寫進 refill 的候選排序器，單一 enforcement owner）。

---

## 4. 接下來的研究計畫

### 設計總則（anti-NULL 規則，適用所有新 dispatch）
- **Power pre-screen**：dispatch 前粗算 —— 若題型是「covariate 微增量」且期望 QLIKE 改善 <3%、n<3000，直接改設計或不派。
- **模板黑名單**：「外生 shock event-window」「新 covariate 進 HAR」兩模板停派；豁免條件 = 資料是獨佔（本機 tick）或 point-in-time vintage 級。
- **輸出型式優先序**：break-even/成本表、校準審計、識別性檢定 > Harvey gate 點預測賽馬。
- **每個新 DM-producing 實驗必存 per-day loss sidecar**（`date, loss_a, loss_b, d_t`）—— K1259/GR-fluctuation 教訓，否則 conditional MCS / fluctuation test 永遠做不了。

### P0（立即，本週起）

| # | 題目 | 動機 | 設計概要 | 資料 | 成功 / kill 標準 | 貢獻 |
|---|---|---|---|---|---|---|
| P0-1 | **方法論債務清償 sprint**：K1681 Clark-West nested-DM 重跑 + nested-DM misuse class sweep + dm_hac_lag_baseline 139 站點分批縮減 | 已發表結論可信度 = 護城河；三項已入 queue（P2/P3 pending）但無人推進 | 按 `scripts/audit_dm_hac_lag.py` 掃描結果批次重跑受影響 cells；nested 比較改 Clark-West；結論翻轉照研究誠實 §6 回溯更正 | 全內部 | 成功 = baseline 只減不增 + 翻轉清單；kill = 無（治理義務） | 全部論文 + 平台可信度 |
| P0-2 | **Mincer-Zarnowitz 全平台預測校準審計**（backlog line 493，零資料成本） | forecast-eval 標配、庫內從未做；直接提升 risk-forecast 頁可信度；同時處理 K1660 的 Parkinson target 錯配 | 對現有 HAR/GARCH 預測輸出跑 MZ 迴歸（斜率=1、截距=0 joint test）+ per-model bias 表 + bias-correction 後 QLIKE 重評；GARCH 家族 realized target 改 r²/5-min | 內部 forecast 庫 | 成功 = 每模型校準表 + 修正建議；「全部無偏」也是可發表 audit（不會 NULL） | Mission 2/4；risk-forecast 產品 |
| P0-3 | **迷思驗證系列 batch 2**（3 題）：定期定額 vs 一次投入、高股息 ETF vs 0050 長期報酬、融資餘額/散戶多空比反指標 | 首批 6/6 完成、half-true 率高、boss msg154 directive、天生 reader-facing | 沿用首批模板：明確 shift(1)、FDR/HAC gate、null 也是好文章 | yfinance / TWSE 免費 | 成功 = 正式檢定 + 文章；kill = 資料不可得才換題 | Mission 1/5 直接轉換 |

### P1（兩週內排入）

| # | 題目 | 動機 | 設計概要 | 資料 | 成功 / kill | 貢獻 |
|---|---|---|---|---|---|---|
| P1-4 | **Direction B 論文起草**：forecast-loss ⊥ tail-coverage divergence | 語料庫最扎實的新論文方向（k850 DM t=-5.60 但 1% VaR 不過；k854/k824/k799/k800 支撐） | 主線程 .md 大綱 + 補 1-2 個 cross-asset divergence cell（GLD/TLT/0050） | 內部 + yfinance | 成功 = 大綱 + 補強 cell 過 Codex review；kill = cross-asset 不重現則降級為 FRL short note | 面向 B / M3 新論文 |
| P1-5 | **Bottom-up vs top-down VaR/ES aggregation**（07-09 batch 中高信心） | FRTB 時效、aggregation direction 庫內零覆蓋 | SPY/TLT/GLD/HYG/QQQ；成分 VaR 加總 vs 組合直估；Kupiec/Christoffersen/DQ/ES backtest + MCS | yfinance | 成功 = 任一方向系統性勝出或 robust tie（皆可發）；kill = 無 | 面向 B、機構內容 |
| P1-6 | **淨成本 VT 工程 pair**：no-trade band（line 485）+ regime-gated VT（line 492）合併一個 K | 策略頁直接受益；輸出是 break-even 成本表，不落 NULL 弧 | TAIEX/SPY VT 加 21d 訊號平滑 + 帶寬；毛 vs 淨對照（台股手續費/證交稅參數）；對照「僅高 vol regime 啟動」開關 | yfinance + 成本參數 | 成功 = turnover 下降 × 淨 Sharpe 保持的 frontier 表；kill = 無 | 面向 C、策略上架 pipeline |
| P1-7 | **TAIFEX intrinsic-time RV**（07-11 batch；本機 tick 獨佔） | 改「採樣時鐘」非換 estimator，與 K1613 noise-robust（directional）正交；獨佔資料豁免黑名單 | clock/trade/hitting/business-time RV → 同資訊 HAR，OOS QLIKE、horizon-specific DM-HLN、MCS、block bootstrap | 本機 TAIFEX tick | 成功 = 任一 intrinsic clock 過 Harvey 或 robust 等價（等價也可寫方法論文章）；kill = measurement error 比較即無差異 → 記 NULL 收弧 | 面向 A 測量層 |
| P1-8 | **台股當沖佔比 × 次日 RV**（line 554） | TWSE 免費日頻、國際罕見、TW 線加碼方向 | 當沖比率 shift(1) → 次日 RV 增量 + 雙向 Granger（vol 吸引當沖 vs 當沖放大 vol）；HAC + Harvey | TWSE 免費 | 成功 = 任一方向顯著；kill = NULL 也可寫（散戶行為文章角度） | 面向 TW、Mission 1/5 |

### P2（一個月內視產能）

| # | 題目 | 動機 / 概要 | 資料 |
|---|---|---|---|
| P2-9 | **CBOE 選擇權賣方 overlay regime 擇時**（line 1470）：BXM/PUT/CLL/CNDR 官方 index、IV percentile / term-structure gate、beta-adjusted Sharpe（K544 Israelov 規則） | 策略多元化 + 讀者感興趣 | CBOE 官網免費 CSV |
| P2-10 | **TSM ADR vs 2330 價格發現與創紀錄溢價**（line 1487）：隔夜/日內拆解 lead-lag；K1626 已有 as-of alignment gate 基礎 | TW 線 + 高共鳴敘事鉤 | yfinance + 本機日內 |
| P2-11 | **Realized covariance HAR → GMV 組合 OOS**（line 491）：Cholesky/log-matrix 參數化 vs shrinkage/EWMA；多變量幾乎零覆蓋 | 面向 A 多變量 + 組合產品 | yfinance |
| P2-12 | **Realized-beta vs constant-beta 避險比率賽馬**（07-09 batch）：同時補 Direction D 論文需要的 OOS HE cell | 面向 I 收斂 + 論文素材 | yfinance / 本機 5-min |
| P2-13 | **Conditional MCS / Giacomini-White regime-conditional 賽馬**：前置條件 = P0 起全實驗存 loss sidecar；先對新產生的 series 做，不回填舊 ledger（K1259 教訓：舊 ledger 無逐日 loss） | 面向 A 評估層 | 內部 |

### 凍結 / 等待清單（明確不做，防 refill 又撿回去）
- 全部「外生 shock event-window」與「新 covariate 進 HAR」backlog 條目（除非獨佔/PIT 資料）。
- ML 架構 4 筆維持 blocked_until=2026-09-04（C14 決議）。
- **Data-unlock calendar**（建議寫入 refill 機制）：0050.TW 5-min 252 天 → 約 2027 Q1，解鎖 formal HAR-RV gate（K1664 預註冊）；VIXTWN 252 天 → 解鎖 Q6 ratio 穩定性 gate（K1323）；K1536 crypto 裁決 → 等 Binance 5-min ingest 建置。
- 中信心 ⚠️ 題（VC-vintage、州最低工資 RDD 等）：dispatch 前查證義務未解除，維持凍結。

---

## 5. 對 5 missions 的資源分配建議

**研究 token 建議配比**（相對目前「量產新 K」為主的分配）：

| 用途 | 配比 | 理由 |
|---|---|---|
| **論文收斂（M3）** | **40%** | M3 是全組合瓶頸：P2 γ provenance 等 owner sign-off 後的 body 修正、P6 PRG forecast-convention 決策、P4ins v4 review、P5/P10 major revision、Direction B 新論文起草。素材不缺，缺的是 revision 收斂 token。 |
| **方法論債務 + 校準（P0-1/P0-2）** | **20%** | 直接影響已發表數字可信度；有機械 gate 可批次化；每一筆都同時強化論文線。 |
| **新實驗** | **25%** | 按 §4 anti-NULL 規則執行 P1/P2 清單。量要降、單筆期望值要升 —— 目前新實驗 NULL 率 >8 成，繼續原速量產是負 ROI。 |
| **策略開發（M-C）** | **15%** | 淨成本工程 + overlay timing + 迷思軸的策略化副產品；boss directive 維持策略線活水但不以「找新 alpha」為目標函數。 |

**對文章 pipeline（Mission 1/5）的含義**：迷思軸 batch 2 + 既有 uncovered K 蒸餾 + 方法論審計的科普化（「我們如何抓自己的統計錯誤」是高信任度內容）足以支撐 draft 池；**不需要為了餵文章而開新實驗** —— 這正是過去兩個月 refill 迴圈的隱性驅動力之一，應明確切斷。

**對 refill 機制的一次性修正建議**（單一 enforcement owner，勿疊層）：把候選排序改為 `迷思軸 > 方法學/測量 > 台灣獨佔 > 淨成本工程 > 學術 batch`，並加 data-unlock calendar 與 power pre-screen 兩個欄位 —— 落在 `scripts/refill_task_pool` 既有 dedup/排序邏輯內，不另建新 gate。

---

*報告完。所有 K-id verdict 可在 experiments/<id>/README.md 與 storage/memory/knowledge.json 追溯；彙總判斷（飽和度百分比）為研究總監估計值，非統計量。*
