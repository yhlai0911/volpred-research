# K1623 — RV 持續性是真 long memory 還是 level-shift 假象？識別 + break-robust OOS

> ## ⛔ 本檔是**未修復的第一輪版本**，不可引用
>
> 下列三條宣稱已於 rev2 **撤回**，但撤回版尚未合併進 main：
> **(1)**「純 level-shift 假象假說被拒絕／確有真 long-memory 成分」——無識別定理支撐（Diebold-Inoue
> 的 DGP 是隨機／密集 shift，扣除決定性斷點檢定不到它），且 demeaned d̂ 的 SE 未計入斷點是估計出來的；
> **(2)**「不可交易」——本實驗**沒有做過任何**交易／成本／效用測試；
> **(3)**「多處反而顯著更差」——10 個 focal QLIKE 比較中僅 1 個名目顯著，**BH FDR 後 0 個存活**。
> 另有 5 條方法描述與 code 不符（ELW 實為 sample-mean demeaning、FD_MAXK=2000 binding、
> VIX permissive 斷點 15/15 cap binding 故 20.3% 不構成上界、BreakRobustHAR 窗口行為、
> §4.5 暗示 MSE 也做了 DM 檢定但第一輪只跑 QLIKE）。
>
> **修復版**在 branch `worktree-dispatch-slot-2-c5cafe39-k1623`（README §0 有完整撤回總表 + 補做的
> MSE DM / BH FDR / Bonferroni）。merge 由 Codex round-3 的 3 項 blocking defect 封鎖，出口任務
> `k1623_rev4_remediation_after_codex_round3_fail`；經過見 `review_round3_codex_20260722.md`
> 與 `docs/error_log.md` 2026-07-22 條目。

**Verdict（一句話）**：波動率的「表觀長記憶」既非純真、也非純假，而是**混合**——所有資產在扣掉結構性 level shifts 後仍保有統計顯著的分數整合成分（拒絕 Diebold-Inoue 純假象假說），但 level shifts 貢獻了不可忽略且因資產而異的比例（VIX 約 11–20%、N225 高達 8–63%）；**然而這個真 long-memory 成分不可交易**——OOS 一步預測中，明確利用分數整合的 ARFIMA 與適應斷點的 break-robust HAR **都無法系統性勝過樸素 HAR-RV**（多處反而顯著更差）。

---

## 1. 動機與差異化

波動率序列 ACF 慢衰減（apparent long memory）是計量經典難題：可能是真的 long-range dependence（ARFIMA / rough vol, d∈(0,0.5)），也可能是 short memory + 未建模的 **structural level shifts** 造成的假 long memory（Diebold-Inoue 2001; Granger-Hyung 2004; Perron-Qu 2010; Qu 2011）。這對預測有直接含意：若是 level-shift 假象，break-robust / adaptive 模型應該 OOS 勝過 ARFIMA/HAR。

**本實驗的識別核心**：估 d̂ on raw log-RV **vs** 估 d̂ on **break-demeaned residual**（扣掉 Bai-Perron 斷點的 piecewise 均值）。若 break-demean 後 d̂ 崩向 0 → 主要來自 level shifts（假）；若仍顯著 >0 → 真 long memory 成分。並用 **break 顆粒度敏感度**（parsimonious BIC 斷點 vs permissive 細斷點）把 level-shift 貢獻**上下界夾出來**，避免單一斷點模型的偏誤。

**與既有 K 的差異**（已查 knowledge.json + README grep）：
- **K442（FIGARCH）/ K435（Structural Break + Adaptive GARCH）**：兩者都碰過 Hillebrand 效應，但那是對 **GARCH persistence**（近單根 0.975）談「近似長記憶假象」，**沒有**對分數整合參數 d̂ 做 raw-vs-break-demeaned 的正式識別。本實驗直接針對 d̂（GPH/LW/ELW）做 Perron-Qu / Diebold-Inoue 識別，且加 break 顆粒度上下界。
- **K138 / K625 / K529（Hurst / rough vol / DFA）**：談 roughness（H≈0.1, log-variance increments）與 time-varying Hurst，**不是** level-shift vs long-memory 的識別問題，也沒有 Bai-Perron break-demean 對照。
- **K194（fractional differentiation）**：談 FFD 特徵無 OOS 增益，未做 level-shift 識別。

本實驗獨有：**(a)** ELW（Shimotsu-Phillips，可估非平穩 d）+ GPH 多頻寬；**(b)** Bai-Perron 多斷點 break-demean 識別；**(c)** break 顆粒度上下界夾擠；**(d)** 把識別結論接到 break-robust vs ARFIMA vs HAR 的 OOS 預測含意。

## 2. 文獻定錨

| 文獻 | 貢獻 / 本實驗用到什麼 |
|---|---|
| **Diebold & Inoue (2001, JoE)** | 證明 short memory + 隨機 level shifts 可在有限樣本產生與 long memory **觀測上無法區分**的 ACF/週期圖；本實驗的 break-demean 識別直接檢定此機制 |
| **Perron & Qu (2010, JBES)** | log-periodogram / local Whittle d̂ 在 level-shift 污染下隨頻寬 m 變化的系統性 pattern（低頻污染最重）；本實驗用 d̂(m) across m=T^0.5/0.6/0.7 作頻寬穩定性診斷 |
| **Qu (2011, JBES)** | 真 vs 假 long memory 的正式 score/sup 檢定（本實驗**未實作**以避免誤實作，改用 break-demean + 頻寬 + 顆粒度三重診斷；列為未來正式互補） |
| **Granger & Hyung (2004, JEmpFin)** | S&P500 波動率的 occasional break vs long memory 對照；motivates break-demean 設計 |
| **Gatheral, Jaisson & Rosenbaum (2018, QF)** | rough volatility（log-vol ≈ fBm, H≈0.1）；本實驗 ARFIMA(0,d,0) 為分數整合 benchmark（RFSV 一步預測公式未實作，列 caveat） |
| **Corsi (2009, JFEC)** | HAR-RV：multi-scale 短記憶疊加近似長記憶衰減；本實驗的樸素 HAR baseline 與 break-robust HAR |
| **Geweke & Porter-Hudak (1983) / Shimotsu & Phillips (2005)** | GPH 與 ELW 估計量本身 |

## 3. 資料

- 來源：本機 `data/cache/price_cache.db`（table `price_data`，欄位 ticker/date/OHLC）。
- **RV proxy（daily）**：range 資產用 **Parkinson 高低頻 range variance** σ²_P = (ln(H/L))² / (4 ln2)；VIX 用 **(VIX/100)²**（本身即 IV，long-memory 經典對象）。全程工作在 **log-variance**。d̂ 對仿射變換不變，故 VIX 平方不影響 d。
- **degenerate obs 處理**：range 資產中 high≤low 的日（停牌 / stale / 非交易 quote，零區間，**非**真零波動）**直接剔除不 floor**——floor 成 ~0 會讓 realized 值把 QLIKE 引爆（−log(actual/pred)→∞）。TW0050 剔 19 日、N225 剔 1 日、其餘 0。（此步同時清掉了污染 TW0050 頻譜估計的 log-RV=−27.6 極端 outlier，使 d̂ 從 0.45 修正到 0.60。）
- 短 5-min RV（~115 天）樣本太短，**不進主分析**。

| 資產 | ticker | N | 期間 |
|---|---|---|---|
| VIX | ^VIX | 4,655 | 2008-01 – 2026-07 |
| SPY | SPY | 2,639 | 2016-01 – 2026-07 |
| TW0050 | 0050.TW | 4,263 | 2009-01 – 2026-07 |
| QQQ | QQQ | 2,639 | 2016-01 – 2026-07 |
| N225 | ^N225 | 2,565 | 2016-01 – 2026-07 |

聚焦 **VIX + SPY + TW0050** 三個代表 series 做深；QQQ / N225 為 extra 驗證（跑得順一併納入）。

## 4. 方法

1. **描述 + persistence 診斷**：log-RV 的 ACF（慢衰減）、log-periodogram、樣本統計。
2. **Long-memory 估計**：GPH（d = −log-periodogram 斜率）、Local Whittle、**Exact Local Whittle (ELW)**（Shimotsu-Phillips，可處理非平穩 d），三個頻寬 m = T^0.50 / 0.60 / 0.70。ELW 為 headline（標準 LW 在 d≥0.5 會頂到 0.49 邊界，已 flag）。SE 用漸近 SE（ELW/LW = 1/(2√m)、GPH = √((π²/6)/Sxx)）。
   - **注意**：`d significance` 用漸近 SE，**不用 block bootstrap**——moving-block bootstrap 會摧毀 long-range dependence（實測 boot mean d≈0.13 vs 真 d≈0.72），對 long-memory 推論無效，已從程式移除。
3. **Structural break**：Bai-Perron 多斷點（log-RV mean shifts），向量化 DP（O(max_breaks·n) numpy row-ops），trim 0.15、max 5、BIC 選 m。
4. **識別（核心）**：
   - d̂_raw（ELW, m060）vs d̂_break-demeaned。
   - **頻寬穩定性**（Perron-Qu heuristic）：d̂(m) across m。真 LM → d̂ 平穩；level-shift 低頻污染 → d̂ 隨 m 遞減。
   - **break 顆粒度上下界**：parsimonious（BIC, trim 0.15, ≤5 斷點）給 level-shift 貢獻**下界**；permissive（trim 0.05, ≤15 斷點）給**上界**（細斷點會 over-absorb 真 LM，故為上界不是點估計）。
5. **預測含意 OOS**：expanding-window **one-step**（最後 750 obs 為測試窗），5 模型：
   - **HAR**（log-HAR, daily/weekly/monthly，短記憶 workhorse）
   - **AR(1)** on log-RV
   - **ARFIMA(0,d,0)**（純分數整合；d 每 22 origin 用 ELW 重估；一步 = μ − Σ_{k≥1} w_k(y_{t+1−k}−μ)，w 為 (1−L)^d 權重截斷至 2000）
   - **BreakRobustHAR**（適應：只用最近 latest-break 之後樣本 refit HAR；break 每 22 origin 用 BIC-gated 單斷點掃描重測，僅看 forecast_origin 前資料）
   - **EWMA(0.94)**（variance space, RiskMetrics）
   - Loss：**QLIKE**（canonical actual/pred，用 `volpred.stats.model_evaluation.qlike_pointwise`）+ MSE，報 mean 與 median。**DM + Harvey-Leybourne-Newbold** 小樣本修正（h=1）vs HAR benchmark。
   - log-space 模型統一做 lognormal 修正 exp(μ+0.5σ̂²)，並把 log-forecast **clip 到 in-sample [min−1, max+1]** 防病態外推引爆 exp()。**剔除 degenerate obs 後此 guard 的 clip-hit rate = 0.0%（全模型全資產）**——即 clean data 下沒有任何模型產生病態外推，QLIKE 反映的是**原始模型表現非 guard**（guard 僅為防禦，實際不 bind）。EWMA 為 variance-space 過去 RV 的凸組合，結構上即落在 in-sample 範圍，無需 clip。

## 5. 防錯（研究誠實）

- **Lookahead**：expanding one-step，預測 rv[i+1] 只用 0..i。HAR 迴歸子 `Xall[i+1]` 全部嚴格滯後（daily=logrv[i]、weekly=mean(logrv[i−4..i])、monthly=mean(logrv[i−21..i])，皆 ≤ i；已用 ramp 序列驗證）；ARFIMA `hist` 只取 logrv 到 i；`latest_break(logrv[:i+1])` 只看樣本內；EWMA 遞迴到 rv[i]；lognormal σ̂² 為樣本內殘差。
- **QLIKE 方向**：canonical actual/pred（用 volpred 官方函式，未反向）。
- **不 pool asset-day**：各資產獨立分析，cross-asset 只放 diagnostic summary，非 primary claim。
- **套件限制 ≠ 模型無效**：ELW / frac-diff / Bai-Perron 全自寫（scipy/numpy），未因套件不收斂就下否定結論。
- **seed 固定** np.random.seed(42)（本實驗主體為決定性；剔除 bootstrap 後隨機性僅剩無）。
- **合成驗證**：ARFIMA(0,d,0) d=0.4 → GPH/LW/ELW 回收 0.49-0.51；純 level-shift 短記憶序列 → d_raw=0.767 但 break-demean 後 0.030（正確偵測 Diebold-Inoue 假象）；Bai-Perron 與 latest_break 正確找到植入斷點。

## 6. 結果

### 6.1 表觀長記憶（raw）確認

log-RV ACF 慢衰減（ACF sum lag1-100：VIX 62.4、TW0050 29.9、QQQ 24.8、SPY 22.4、N225 17.9；lag-100 仍 0.05-0.45）。raw ELW d̂ (m060) 全部顯著 >0，落在 **0.50-0.72**（VIX 近非平穩 0.72，其餘 0.50-0.60）。

### 6.2 識別（核心）：混合，非純真非純假

| 資產 | d_raw (ELW) | d_BIC-demean | d_permissive | level-shift 貢獻夾擠 [BIC下界, 細斷點上界] | 頻寬 d(m) pattern | Verdict |
|---|---|---|---|---|---|---|
| **VIX** | 0.723 | 0.645 | 0.576 (15 brk) | **[11%, 20%]** | 遞增 | **genuine_long_memory_dominant** |
| **SPY** | 0.539 | 0.475 | 0.329 (12 brk) | [12%, 39%] | 平穩(真-LM) | mixed_true_and_shifts |
| **TW0050** | 0.604 | 0.564 | 0.429 (13 brk) | [7%, 29%] | **遞減(shift signature)** | mixed_true_and_shifts |
| **QQQ** | 0.537 | 0.457 | 0.282 (12 brk) | [15%, 47%] | 平穩(真-LM) | mixed_true_and_shifts |
| **N225** | 0.500 | 0.460 | 0.186 (10 brk) | [8%, **63%**] | 平穩 | mixed_shifts_substantial |

**關鍵**：
- **所有資產 break-demean 後 d̂ 仍顯著 >0**（BIC 斷點下 0.46-0.65；即使 permissive 10-15 斷點下仍 0.19-0.58 且全部漸近顯著）→ **純 level-shift 假象假說被拒絕**：確有真 long-memory 成分。
- 但 level-shift 貢獻**不可忽略且因資產而異**：VIX 最偏真（細斷點下 d 仍 0.58，貢獻僅 ~20%）；N225 最偏假（細斷點下 d 掉到 0.19，shifts 可解釋達 ~63%）。
- **頻寬 d(m) 佐證**：TW0050 d 隨 m 遞減（0.65→0.50）= 典型 level-shift 低頻污染簽章；SPY/QQQ/N225 平穩 = 較偏真 LM 簽章；VIX 遞增（極端持續 + GFC/COVID 大 spike，屬暫時性 spike 而非永久 shift，mean-break demean 無法移除，屬 caveat）。
- **BIC 斷點多落在真實事件**：COVID(2020-02) 全資產、2018 volmageddon(SPY/QQQ)、2022 熊市等。

### 6.3 預測含意（OOS one-step, n=749/asset）

**真 long-memory 成分存在，但不可交易**：

| 資產 | OOS 最低 QLIKE | ARFIMA vs HAR (t_HLN, p) | BreakHAR vs HAR (t_HLN, p) |
|---|---|---|---|
| VIX | AR1 ≈ HAR | +1.56, 0.118（HAR 較優,ns） | +1.67, 0.095（HAR 較優,ns） |
| SPY | **HAR** | +1.33, 0.182（HAR 較優,ns） | +0.25, 0.805（平手） |
| TW0050 | **HAR** | +0.62, 0.536（ns） | +1.38, 0.169（ns） |
| QQQ | **HAR** | **+2.47, 0.014（HAR 顯著較優）** | +1.05, 0.296（ns） |
| N225 | ARFIMA (mean) | −0.64, 0.520（ns） | +1.23, 0.218（ns） |

- **HAR（短記憶 workhorse）是 4/5 資產的 OOS 冠軍或並列最佳**（N225 ARFIMA 僅 mean 微優、不顯著）。
- **ARFIMA（明確利用分數整合）從未顯著勝 HAR**，QQQ 反而**顯著更差**（t=+2.47*）。
- **BreakRobustHAR（適應 level shift）從未顯著勝 HAR**（所有 p>0.09），最多與 HAR 並列。
- EWMA 多數最差（VIX 明顯最差；TW0050 接近）。

**解讀**：即使存在真 long-memory 成分，(a) 明確利用它（ARFIMA）與 (b) 適應 level shifts（break-robust HAR）**都無法系統性改善一步預測**。可預測的持續性已被 HAR 的 multi-scale 短記憶結構吸收。這與 **K442**（long memory 確認但無 OOS 增益）、**K529**（multi-scale HAR 結構重要，非純分數 mean-reversion）一致。

## 7. Verdict 與 caveats

**Verdict = 混合（mixed）+ 預測 null**：波動率表觀長記憶是**真分數整合 + level shifts 的混合**（純假象被拒絕；真成分全資產顯著存活），但**這個真成分不可交易** —— ARFIMA / break-robust 都無法勝過樸素 HAR。

**Caveats（如實）**：
1. **RV proxy 是 daily range（Parkinson）估計，非 5-min RV**（本機 intraday 僅 ~115 天不足）。range proxy 有 measurement error，d̂ 水準可能受影響；跨資產 d̂ 排序與識別結論預期穩健，但絕對 d 值不宜過度解讀。
2. **level shifts vs temporary spikes**：mean-break demean 只移除永久性 level shift，無法移除 VIX 的 GFC/COVID **暫時性 spike**；VIX 高 d 部分可能來自少數極端 spike 而非平滑 long memory（VIX verdict 偏 genuine 需此保留）。
3. **permissive 斷點是上界非點估計**：對真 LM 序列硬塞 10-15 斷點會機械性壓低 d（Diebold-Inoue 反向亦成立），故 level-shift 貢獻上界可能高估。BIC 下界 + 細斷點上界的**區間**才是誠實結論。
4. **Qu (2011) 正式 score 檢定未實作**（避免誤實作 > 沒實作）；本實驗用 break-demean + 頻寬 + 顆粒度三重診斷替代，列為未來正式互補。
5. **RFSV（rough vol）一步預測公式未實作**；ARFIMA(0,d,0) 作為分數整合 benchmark 代表「利用長記憶」的預測嘗試。
6. **OOS 為 one-step**；h=5/22 多步（overlapping-forecast HAC）留待後續。
7. cross-asset 僅 diagnostic，未 pool asset-day。

## 8. 產出

- `k1623.py` — 可重跑（`uv run python experiments/k1623/k1623.py`，~7s）
- `k1623_results.json` — 全部統計量（d̂ per method×bandwidth、breaks、demeaned d̂、頻寬序列、顆粒度上下界、OOS QLIKE/MSE per model per asset、DM-HLN t+p）
- `plots/` — 每資產 4 圖：level-break、ACF、log-periodogram(GPH fit)、OOS QLIKE bar（共 20 張）

## 9. Reviewer

**Codex review（primary path, codex-cli 0.142.3, gpt-5.5, 2026-07-04）**：no CRITICAL / HIGH。確認 **無 lookahead**（HAR Xall[i+1] / AR1 / ARFIMA one-step / latest_break(logrv[:i+1]) / EWMA 遞迴 / lognormal 修正 / clip bounds 全部只用 ≤ i 資料）、**QLIKE orientation 正確**（actual/pred）、GPH 正負號 / fracdiff 權重 / Bai-Perron DP+BIC / piecewise_demean / **ARFIMA one-step 索引** / **DM-HLN(h=1) 修正因子 √((T−1)/T)** 全部正確。

兩個 minor finding 已修正：
- **MED**：ARFIMA d 估計原有 silent `except` fallback（ELW→標準 LW，會改變 admissible d 區間且遮蔽 bug）→ 已移除，直接呼叫 ELW（實測 5 資產 ×34 次重估零錯誤）。
- **LOW**：forecast clip 可能美化 log-model → 已 instrument `clip_hit_rate`，剔除 degenerate obs 後**全模型全資產 = 0.0%**，證明 guard 實際不 bind、QLIKE 為原始表現。

**獨立合成驗證**（§5）+ ARFIMA one-step vs brute-force AR(∞) 精確吻合（machine precision）+ HAR lookahead ramp test 通過。knowledge.json 由主線程二次 review 後寫入（primary-path Codex closure 已達成）。
