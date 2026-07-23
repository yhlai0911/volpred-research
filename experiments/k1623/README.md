# K1623 — RV 持續性：level-shift 扣除後的殘餘持續性 + break-robust OOS（rev2 已撤回識別宣稱）

> **rev2 修訂公告（2026-07-19）**
> 本實驗第一輪（2026-07-04）的 headline 宣稱經 codex `gpt-5.6-sol` 獨立二審判 **FAIL**。
> **算術沒有錯，錯在「宣稱」超出「證據」**。rev2 **撤回 3 條宣稱、修正 5 條描述/推論**，
> 並補上第一輪該做而沒做的檢定（MSE 的 DM、多重比較修正、HAC）。
> 依 K1259 規則本實驗**不寫入 `knowledge.json`**。
> 撤回總表見 **§0**；權威數字以 `k1623_rev2_results.json` 為準（`k1623_results.json` 的**預測值**仍然有效，
> 被取代的只有**推論與宣稱**）。

**Verdict（一句話，rev2）**：扣掉 Bai-Perron 結構斷點後，5 個資產的 ELW d̂ 仍為正
（BIC 斷點下 0.46–0.65，permissive 10–15 斷點下 0.19–0.58）——**這是描述性的「殘餘持續性」，
不構成對 Diebold-Inoue level-shift 假說的拒絕**（扣掉 ≤5 個*決定性*斷點，扣不掉 Diebold-Inoue
所設想的*隨機／密集* regime shift，無識別定理支撐此推論）。OOS 一步預測中，ARFIMA 與
BreakRobustHAR **在 QLIKE 與 MSE 兩個 loss 下、經多重比較修正後，都與樸素 HAR 統計上無法區分**
（20 個 focal 比較中 0 個存活 BH FDR）。**本實驗未做任何交易／成本／效用測試，故不對可交易性表態。**

---

## 0. rev2 撤回與修正總表

機讀版：`k1623_rev2_results.json` → `retracted_claims[]`（8 條，每條含 before / after / basis）。

| # | 宣稱 | 狀態 | 修正後 |
|---|---|---|---|
| 1 | 「純 level-shift 假象假說被拒絕，確有真 long-memory 成分」 | **RETRACTED** | 改為**描述性殘餘持續性**。扣 ≤5（permissive ≤15）個 deterministic mean break 無法扣掉隨機／密集 shift 過程，故 d̂>0 不是反證 |
| 2 | 「真 long-memory 成分**不可交易**」 | **RETRACTED** | **刪除**。零支撐計算——沒有任何策略／成本／效用測試存在於任何一輪 |
| 3 | 「ARFIMA/break-robust 多處反而**顯著更差**」 | **RETRACTED** | 10 個 focal QLIKE 比較中僅 **1 個**名目顯著（QQQ/ARFIMA, p=0.0332），**BH FDR 後 0 個存活** |
| 4 | §4.5 暗示 DM 對 QLIKE + MSE 都做了檢定 | **CORRECTED（補做）** | 第一輪 **只跑 QLIKE**。rev2 補齊 MSE，發現 **point estimate 方向反轉** |
| 5 | ELW =「Shimotsu-Phillips，可估非平穩 d」 | **CORRECTED** | 實作是 **sample-mean demeaning**，非 SP 的 μ̂(d) 加權估計量 |
| 6 | VIX level-shift 貢獻**上界** 20.3% | **CORRECTED（降級）** | VIX permissive 選到 **15/15 = cap binding**，故 20.3% **不是上界**，該側開放 |
| 7 | BreakRobustHAR「只用最近 latest-break 之後樣本 refit」 | **CORRECTED（描述對齊 code）** | `k1623.py:475` 在斷點太近時**刻意把窗口推回斷點之前**；無斷點時 fallback trailing 750 |
| 8 | DM t 統計量（第一輪全部） | **CORRECTED（推論升級）** | 第一輪 `dm_hln` 用 `for lag in range(1, h)`，**h=1 時是空迴圈 → 完全沒做 HAC**。rev2 全面改用 canonical Newey-West |

**沒有被撤回的**（rev2 逐項重驗，仍然成立）：OOS n=749/資產；
**QLIKE 下 HAR 對 ARFIMA 在 4/5 資產有較低的平均損失**；
BreakHAR vs HAR 10 個比較全部不顯著；扣斷點後 d̂ 仍為正（作為**描述**）。

> **rev3 更正（2026-07-20，Codex round 2 §2）**：上一行原本寫「QLIKE 下 HAR 是 5 資產的**冠軍或並列
> 最佳**」——**這是假的**。`k1623_rev2_results.json` 的 `best_by_qlike`（**全 5 模型**比較）是
> VIX=`AR1`（:118）、N225=`ARFIMA`（:278），只有 SPY / TW0050 / QQQ 三個資產的全模型冠軍是 HAR。
> 「5 資產冠軍」把一個 **HAR-vs-ARFIMA 的兩兩比較**擴張成了**全模型排名**宣稱。
> 現行說法收窄為兩兩比較，與 §6.3 表格逐格對得上。

> **rev4 降級（2026-07-23，Codex round 3）— 不在上表的第 9 條**：上表 8 條是 **rev2 對第一輪**的撤回／修正
> （機讀版 `k1623_rev2_results.json` → `retracted_claims[]`）。rev3 曾把 rev2 的跨資產主因宣稱降級為
> **asset-dependent** 分類；但 500 reps 下單一 sd 點估的粗略相對 MC SE 約 3.2%，SPY / N225 /
> TW0050 的前兩因子差距分別只有 0.31% / 3.45% / 4.08%，不足以識別逐資產主導通道。
> rev4 因此再降級為**僅報三個通道的描述性點估，明示 dominance not identified at 500 reps**。
> 唯一與 MC 噪音充分分離的是總 SE 低估量 **1.21–1.33×**。完整說明與數據在 §6.4 finding 2。
> 這條**未**寫入 `retracted_claims[]`（該欄位的 scope 是 rev2-對-第一輪），
> 其證據在 `k1623_rev3_armc_results.json`。

---

## 1. 動機與差異化

波動率序列 ACF 慢衰減（apparent long memory）是計量經典難題：可能是真的 long-range dependence
（ARFIMA / rough vol, d∈(0,0.5)），也可能是 short memory + 未建模的 **structural level shifts**
造成的假 long memory（Diebold-Inoue 2001; Granger-Hyung 2004; Perron-Qu 2010; Qu 2011）。

**第一輪原本的「識別核心」，以及它為什麼不成立**：原設計是估 d̂ on raw log-RV **vs** 估 d̂ on
**break-demeaned residual**（扣掉 Bai-Perron 斷點的 piecewise 均值），並宣稱「若 demean 後 d̂ 仍顯著 >0
→ 真 long memory 成分」。

**rev2 撤回這個推論**。理由是**識別上的不對稱**：Diebold-Inoue 的 DGP 是一個**隨機、可能密集**的
shift 過程；扣掉 ≤5 個（permissive ≤15 個）**決定性**的 Bai-Perron mean break，**在數學上並沒有把
那個過程減掉**。所以「殘餘 d̂ > 0」與「Diebold-Inoue 為真」**完全相容**，不是它的反證。
沒有任何識別定理授權從前者推到後者。雪上加霜的是，demeaned d̂ 的 SE 直接沿用 raw ELW 的漸近 SE，
**未計入斷點是估計出來的**（generated-regressor 問題，見 §6.4 的 Monte Carlo）。

**本實驗 rev2 後留下什麼**（**rev3 依 Codex round 2 §8 逐點重評，不再宣稱「獨有」**）：

| # | 內容 | 支撐狀態 | 可以怎麼說 |
|---|---|---|---|
| **(a)** | 對同一組預測**同時**報 QLIKE 與 MSE 的 DM，並揭露**模型排序隨 loss 反轉** | **有計算支撐**（`dm_comparisons[40]`、`loss_function_sign_reversal[5]`，3/5 資產反轉） | 本實驗的**主要產出**。可陳述為結果，但必須連同「兩個 loss 都不顯著」一起講 |
| **(b)** | Bai-Perron break-demean 的**顆粒度敏感度**（BIC ≤5 vs permissive ≤15） | **有描述性計算支撐**（§6.2 表） | 可陳述為**描述性**敏感度，**不是**識別證據 |
| **(c)** | 量化 generated-regressor 不確定性的三臂 Monte Carlo | **只有 model-conditional 支撐**；A−B 涵蓋 BIC 對斷點 partition（數量＋位置）的選擇，B−C 涵蓋段均值估計的增量成本 | 只能說「**在 ARFIMA + 決定性斷點這個模型假設下**，抽樣 sd 是漸近 SE 的 1.21–1.33 倍」。三通道分解僅是 500-rep 描述性點估，**不可**說成主導通道已識別、對該模型的檢定，或對 generated-regressor 問題的無條件量化 |
| **(d)** | 「單一 loss 會製造方向性結論」的方法論教訓 | **不是本實驗獨有** | 改寫為：**本資料提供了 K1016 既有教訓的一個新實例**（新的資產集、新的模型集、且附帶 HAC + BH 的完整推論）。**不是**新教訓 |

**為什麼 rev3 要改這段**：原文宣稱這四點是「**仍然獨有的貢獻**」，但同一份 README 的下一段
自己就寫「K1016：…**rev2 的 §6.3 是這條教訓的又一個實例**」——**這句直接否定了 (d) 的 uniqueness**。
(c) 也在 §6.4 自陳 model-conditional，撐不起無限定的「貢獻」措辭。

**關於「獨有 / novelty」的證據邊界（rev3 明確劃線）**：本實驗查核的是
**knowledge.json + 本 repo README grep**，那只能支撐一句話 ——「**在本 repo 既有的 K 之中沒有重複**」。
**它不能支撐任何一般性的學術 uniqueness 宣稱**（那需要系統性的 prior-art / 文獻檢索，本輪未做）。
下表因此只講 repo 內部差異，不講學術首創。

**識別問題本身，本實驗現在明確表態：未解決。**

**與既有 K 的差異**（範圍限於本 repo：knowledge.json + README grep；**不構成學術 novelty 宣稱**）：
- **K442（FIGARCH）/ K435（Structural Break + Adaptive GARCH）**：都碰過 Hillebrand 效應，但那是對
  **GARCH persistence**（近單根 0.975）談「近似長記憶假象」，沒有對 d̂ 做 raw-vs-break-demeaned 對照。
- **K138 / K625 / K529（Hurst / rough vol / DFA）**：談 roughness 與 time-varying Hurst，不是 level-shift 對照。
- **K194（fractional differentiation）**：談 FFD 特徵無 OOS 增益，未做 level-shift 對照。
- **K1016**：loss function 選擇影響結論——**rev2 的 §6.3 是這條教訓的又一個實例**。

## 2. 文獻定錨

| 文獻 | 貢獻 / 本實驗用到什麼 |
|---|---|
| **Diebold & Inoue (2001, JoE)** | 證明 short memory + **隨機** level shifts 可在有限樣本產生與 long memory **觀測上無法區分**的 ACF/週期圖。**rev2 註**：正因為該 DGP 是隨機／密集的，扣除決定性斷點**無法**檢定它——這正是撤回宣稱 #1 的理由 |
| **Perron & Qu (2010, JBES)** | log-periodogram / local Whittle d̂ 在 level-shift 污染下隨頻寬 m 變化的系統性 pattern；本實驗用 d̂(m) across m=T^0.5/0.6/0.7 作**描述性**診斷（非正式檢定） |
| **Qu (2011, JBES)** | 真 vs 假 long memory 的**正式** score/sup 檢定。本實驗**未實作**——這是 rev2 後識別問題仍未解決的直接原因 |
| **Granger & Hyung (2004, JEmpFin)** | S&P500 波動率的 occasional break vs long memory 對照；motivates break-demean 設計 |
| **Gatheral, Jaisson & Rosenbaum (2018, QF)** | rough volatility；本實驗 ARFIMA(0,d,0) 為分數整合 benchmark（RFSV 一步預測公式未實作） |
| **Corsi (2009, JFEC)** | HAR-RV：multi-scale 短記憶疊加近似長記憶衰減 |
| **Geweke & Porter-Hudak (1983) / Shimotsu & Phillips (2005)** | GPH 與 ELW 估計量本身（**注意**：本實作非完整 SP 版本，見 §4.2） |
| **Diebold & Mariano (1995) / Harvey, Leybourne & Newbold (1997)** | 預測比較檢定 |
| **Benjamini & Hochberg (1995)** | FDR 多重比較修正（rev2 新增） |
| **Patton (2011, JoE)** | volatility proxy 下的 robust loss functions；**QLIKE 與 MSE 對 proxy 誤差的敏感度不同**，是 §6.3 反轉的背景 |

## 3. 資料

- 來源：本機 `data/cache/price_cache.db`（table `price_data`，欄位 ticker/date/OHLC）。
- **RV proxy（daily）**：range 資產用 **Parkinson 高低頻 range variance** σ²_P = (ln(H/L))² / (4 ln2)；
  VIX 用 **(VIX/100)²**。全程工作在 **log-variance**。d̂ 對仿射變換不變。
- **degenerate obs 處理**：range 資產中 high≤low 的日**直接剔除不 floor**——floor 成 ~0 會讓 QLIKE 引爆。
- 短 5-min RV（~115 天）樣本太短，**不進主分析**。

| 資產 | ticker | N | 期間 | rev2 重現性 |
|---|---|---|---|---|
| VIX | ^VIX | 4,655 | 2008-01 – 2026-07 | **exact**（1e-9） |
| SPY | SPY | 2,639 | 2016-01 – 2026-07 | **exact**（1e-9） |
| TW0050 | 0050.TW | 4,263 → **4,264** | 2009-01 – 2026-07 | **near**（最大相對偏差 5.26e-3，見下） |
| QQQ | QQQ | 2,639 | 2016-01 – 2026-07 | **exact**（1e-9） |
| N225 | ^N225 | 2,565 | 2016-01 – 2026-07 | **exact**（1e-9） |

**rev2 資料 vintage 鎖定（研究誠實）**：`price_cache.db` 自第一輪已前進約 10 個交易日。若不鎖定，
trailing-750 OOS 窗會滑動，就會把「檢定被修好了」與「樣本移動了」混在一起。rev2 因此把每資產
end date **pin 回第一輪**（VIX/SPY/QQQ 2026-07-02，TW0050/N225 2026-07-03），
故 **rev2 的 t 統計量是第一輪的 like-for-like 修訂，不是更新樣本的新結果**。

**TW0050 無法精確重現，如實揭露**：其快取歷史被**修訂**（非僅延長）——pin 日的原始列數不變，
但一列原本 high==low 的 degenerate 列現在 high > low，故被保留而非剔除（n 由 4,263 → 4,264）。
TW0050 的 rev2 統計量因此是**近似重現**，實測與第一輪摘要統計的最大相對偏差 **5.26e-3**
（權威欄位 `reproduction_guard.per_asset_vintage.TW0050.max_relative_deviation_vs_original`
= `0.005259349489457132`），已逐格記錄於 `reproduction_guard.per_asset_vintage`。**不強行對齊、不隱藏。**

> **rev3 更正（2026-07-20，Codex round 2 §2）**：本 README 原本三處（§3 表格、本段、§7 limitation 9）
> 與兩份 JSON 的 prose 欄位，都把這個數字寫成 **2.5e-3 / 2.51e-3 — 約為權威值的一半**。
> 那是人手寫進 prose 字串的筆誤，不是任何計算輸出；權威欄位自始至終是 `0.00525935`。
> 全部已改為 **5.26e-3**。

## 4. 方法

1. **描述 + persistence 診斷**：log-RV 的 ACF、log-periodogram、樣本統計。
2. **Long-memory 估計**：GPH、Local Whittle、**Exact Local Whittle (ELW)**，三個頻寬 m = T^0.50/0.60/0.70。
   ELW 為 headline（標準 LW 在 d≥0.5 會頂到 0.49 邊界，已 flag）。SE 用漸近 SE（ELW/LW = 1/(2√m)）。
   - **⚠️ rev2 更正（撤回表 #5）**：本實作的 ELW 是 **sample-mean demeaning** 版本——
     `k1623.local_whittle(exact=True)` 先算一次 `xd = x - mean(x)`，然後**只對 d 最佳化**。
     它**不是** Shimotsu-Phillips 的 unknown-mean μ̂(d) 加權估計量。第一輪 §4.2/§9 稱其為
     「Shimotsu-Phillips，可估非平穩 d」**不實**。實質後果：**對 VIX（d̂=0.723 > 0.5，落在非平穩區）
     樣本平均不是有效的 level 估計量**，故 5 個資產中 VIX 的 d̂ 最不可信。
   - **⚠️ rev2 揭露**：`FD_MAXK = 2000` 截斷分數差分濾波器。對 n = 2,565–4,655 此截斷
     **對每個資產都 binding**，且 **d 越大咬得越深**（被丟棄的權重尾部以 k^(−d−1) 衰減）→ 又是 VIX 受創最重。
   - **注意**：`d significance` 用漸近 SE，**不用 block bootstrap**——moving-block bootstrap 會摧毀
     long-range dependence（實測 boot mean d≈0.13 vs 真 d≈0.72），對 long-memory 推論無效，已從程式移除。
3. **Structural break**：Bai-Perron 多斷點（log-RV mean shifts），向量化 DP，trim 0.15、max 5、BIC 選 m。
4. **描述性斷點敏感度（rev2 已從「識別」降級為「描述」）**：
   - d̂_raw（ELW, m060）vs d̂_break-demeaned。
   - **頻寬穩定性**（Perron-Qu heuristic）：d̂(m) across m。**這是啟發式診斷，不是檢定。**
   - **break 顆粒度區間**：parsimonious（BIC, trim 0.15, ≤5 斷點）vs permissive（trim 0.05, ≤15 斷點）。
     **⚠️ rev2 更正（撤回表 #6）**：**VIX 選到 15/15，cap binding**，故 VIX 的 20.3% **不構成上界**
     （允許更多斷點可能更高）。其餘 4 資產選 10–13/15，不受影響。
5. **預測含意 OOS**：expanding-window **one-step**（最後 750 obs 為測試窗），5 模型：
   - **HAR**（log-HAR, daily/weekly/monthly）
   - **AR(1)** on log-RV
   - **ARFIMA(0,d,0)**（d 每 22 origin 用 ELW 重估；權重截斷至 2000）
   - **BreakRobustHAR** — **⚠️ rev2 更正（撤回表 #7）**：第一輪描述為「只用最近 latest-break 之後樣本 refit」，
     **與程式不符**。`k1623.py:475` 實際是 `wstart = max(0, min(brk_start, i-22-60))`，
     即**斷點太近時刻意把窗口起點推回斷點之前**（以保留 ≥60 個可用列）；**無偵測到斷點時 fallback
     到 trailing 750 窗**。rev2 依 brief 選項 (i)：**修描述、不修 code**——因為本輪的目的是修
     「宣稱 vs 證據」，改 code 會讓所有數字失效並超出 scope。
     **⚠️ rev3 更正（Codex round 2 §5）**：此處原本寫「**故所有數字不變**」——**這句無限定，
     對 TW0050 為假**。程式沒改**不等於**輸入沒改：TW0050 的上游快取歷史被修訂（n 4,263→4,264），
     同一份 code 餵不同輸入就會產生不同 forecasts。正確說法是
     **「4 個 exact-pin 資產（VIX/SPY/QQQ/N225）的聚合損失重現到 1e-9；TW0050 的數字有變動，
     最大相對偏差 5.26e-3」**，詳見 `k1623_rev2_results.json` →
     `reproduction_guard.scope_and_limits`（含 `tw0050_exception`）。
   - **EWMA(0.94)**（variance space, RiskMetrics）
   - **Loss 與推論** — **⚠️ rev2 更正（撤回表 #4、#8）**：
     - 第一輪 §4.5 寫「QLIKE + MSE ... DM + HLN」，**實際只對 QLIKE 跑了 DM**；MSE 只存了 summary mean
       從未檢定。**rev2 補齊 5 資產 × 4 對照 × 2 loss = 40 個 DM 比較。**
     - 第一輪的 `dm_hln` 用 `for lag in range(1, h)`，**h=1 時是空迴圈 → var_d 只剩 γ₀，完全沒做 HAC**
       （違反 `.claude/rules/experiments.md`「DM 的 HAC 落後期不可只用 h-1」；該站點已凍結於
       `storage/ops/dm_hac_lag_baseline.json`）。rev2 全面改用 canonical
       `volpred.stats.model_evaluation.dm_test`（Newey-West，bandwidth = ⌈n^(1/3)⌉ = **10**）。
       每列保留 `t_original_degenerate_no_hac` 供稽核。
     - **多重比較**：BH FDR（primary）+ Bonferroni（secondary）。
       **primary family 在程式碼中事前指定**為 `within_loss_20`（QLIKE 與 MSE 各自獨立修正，各 20 個），
       **README 全部結論一律取 BH @ `within_loss_20`** —— 事前寫死在 code 裡，正是為了讓
       「選哪個 family」無法在看到結果後才決定。
       **⚠️ 措辭更正（rev2 二審；rev3 再修）**：這實際是**五個假設集合，不是「三個 family」**——
       QLIKE-20、MSE-20、QLIKE-focal-10、MSE-focal-10、pooled-40。
       **rev3 更正（Codex round 2 §3）**：rev2 把它們統稱為「**五個巢狀集合**」**並不精確** ——
       **QLIKE-20 與 MSE-20 彼此互斥（disjoint），談不上巢狀**；正確的關係是
       **每個 focal-10 是其對應 within-loss-20 的子集**、**pooled-40 是 QLIKE-20 與 MSE-20 的聯集**。
       換言之只有「focal ⊂ within-loss」這一組是真的巢狀。非 primary 的集合作為
       **sensitivity 報告，不是可挑選的菜單**：**focal 比較在五個集合中沒有任何一個存活 BH**，
       故結論不依賴 family 的選擇。
     - **HLN 的一個不對稱，如實揭露**：`t_hac_hln = t_hac × 0.9993`，但**送進 BH/Bonferroni 的
       `p_hac` 對應的是 `t_hac` 而非 `t_hac_hln`**。rev2 另存 `p_hac_hln` 供核對：
       兩者**最大差距 3.2e-4**（第 4 位小數），**40 個比較中 0 個 5% 判定改變**。
       揭露而非留給讀者自己發現。
     - **canonical `dm_test` 本身的兩個 caveat**（本輪未改動 canonical 函式，僅揭露）：
       (i) 它把 γ₀ 除以 n、γ_lag 除以 (n−lag)，是合法變體但非教科書有限樣本 NW 形式（統一 1/n）。
       實測 VIX/QLIKE/ARFIMA：repo 變體 t=**1.707107**（= 已發表值），統一 1/n 為 t=**1.706008**，無實質差異。
       (ii) 若估計的 long-run variance ≤ 0，它直接回傳 `(0.0, 1.0)`，會把**估計失效偽裝成完全不顯著**。
       **已實測驗證：40 個比較無一觸發此分支。**
   - log-space 模型統一做 lognormal 修正 exp(μ+0.5σ̂²)，log-forecast **clip 到 in-sample [min−1, max+1]**。
     剔除 degenerate obs 後 **clip-hit rate = 0.0%（全模型全資產）**，guard 實際不 bind。

## 5. 防錯（研究誠實）

- **Lookahead**：expanding one-step，預測 rv[i+1] 只用 0..i。HAR 迴歸子 `Xall[i+1]` 全部嚴格滯後；
  ARFIMA `hist` 只取 logrv 到 i；`latest_break(logrv[:i+1])` 只看樣本內；EWMA 遞迴到 rv[i]。
- **QLIKE 方向**：canonical actual/pred（用 volpred 官方函式，未反向）。
- **不 pool asset-day**：各資產獨立分析，cross-asset 只放 diagnostic。
- **套件限制 ≠ 模型無效**：ELW / frac-diff / Bai-Perron 全自寫。
- **seed 固定** np.random.seed(42)；rev2 Monte Carlo 亦 seed=42。
- **合成驗證**：ARFIMA(0,d,0) d=0.4 → GPH/LW/ELW 回收 0.49-0.51；純 level-shift 序列 →
  d_raw=0.767 但 break-demean 後 0.030。**rev2 註**：此合成檢定證明的是「**決定性**斷點被正確偵測」，
  **不**證明該程序能偵測 Diebold-Inoue 的**隨機**shift——這正是撤回宣稱 #1 的核心。
- **rev2 重現性 guard（含其能力邊界）**：**100 格**逐項比對第一輪（5 資產 × 5 模型 × 4 個統計量：
  `qlike_mean`、`qlike_median`、`mse`、`clip_hit_rate`），4 個 exact-pin 資產**全部 1e-9 內完全吻合
  （實測最大相對偏差 = 0.0）**。
  **⚠️ 這個 guard 能證明什麼、不能證明什麼（rev2 二審後修正措辭）**：
  第一輪的 artifact **只存了聚合統計量，從未存過逐期預測向量**，所以對它做逐期比對
  **不是「省略了」而是「不可能」**。四個獨立泛函（兩個 loss 動差 + 一個中位數 + 一個 guard 命中數）
  同時吻合到 1e-9，是預測路徑相同的**強證據，但不是證明**。
  故可辯護的說法是「**重現出的聚合損失完全相同**」，**不是**「預測完全相同」。
  **對 TW0050 而言，「same forecasts / same sample」是錯的**（見 §3），本 README 不作此宣稱。

## 6. 結果

### 6.1 表觀長記憶（raw）確認

log-RV ACF 慢衰減（ACF sum lag1-100：VIX 62.4、TW0050 29.9、QQQ 24.8、SPY 22.4、N225 17.9）。
raw ELW d̂ (m060) 全部顯著 >0，落在 **0.50-0.72**。**（此節未受 rev2 影響。）**

### 6.2 斷點扣除後的殘餘持續性（**描述性，非識別**）

| 資產 | d_raw (ELW) | d_BIC-demean | d_permissive | 斷點數 | d̂ 下降佔比 [BIC, permissive] | 頻寬 d(m) pattern |
|---|---|---|---|---|---|---|
| **VIX** | 0.723 | 0.645 | 0.576 | **15/15 ⚠️cap** | [10.7%, 20.3% ⚠️非上界] | 遞增 |
| **SPY** | 0.539 | 0.475 | 0.329 | 12/15 | [11.8%, 38.8%] | 平穩 |
| **TW0050** | 0.604 | 0.564 | 0.429 | 13/15 | [6.7%, 28.9%] | 遞減 |
| **QQQ** | 0.537 | 0.457 | 0.282 | 12/15 | [14.9%, 47.5%] | 平穩 |
| **N225** | 0.500 | 0.460 | 0.186 | 10/15 | [7.9%, 62.7%] | 平穩 |

**可以說的（描述）**：
- 扣掉 BIC 斷點後 d̂ 仍為正（0.46–0.65）；扣掉 10–15 個 permissive 斷點後仍為正（0.19–0.58）。
- d̂ 下降的幅度**因資產而異**：N225 對斷點顆粒度最敏感（permissive 下掉到 0.19），VIX 最不敏感。
- BIC 斷點多落在真實事件：COVID(2020-02) 全資產、2018 volmageddon(SPY/QQQ)、2022 熊市等。

**⚠️ 不可以說的（rev2 撤回）**：
- ~~「純 level-shift 假象假說被拒絕」~~ / ~~「確有真 long-memory 成分」~~ / ~~「genuine_long_memory_dominant」~~。
  扣除**決定性**斷點不能反證**隨機／密集**的 shift 過程。上表是**殘餘持續性的描述**，不是識別結果。
- 頻寬 pattern（遞增/平穩/遞減）是**啟發式簽章**，第一輪把它當「佐證」用詞過重；rev2 僅列為描述。
- 表中 d̂ 的漸近 SE **未計入斷點是估計出來的**（見 §6.4），故為**下界**。

### 6.3 預測含意（OOS one-step, n=749/資產）— **rev2 核心產出：loss 反轉**

**同一份預測程式、同一批模型、同一個評分窗，換一個 loss function，模型排序就反轉。**
（**限定**：4 個 exact-pin 資產的**聚合損失**重現到 1e-9；**TW0050 是近似重現**，
其樣本因上游歷史修訂由 n=4,263 變 4,264，故對 TW0050 不能說「同一個樣本」。見 §3、§5。）

| 資產 | QLIKE ratio (ARFIMA/HAR) | QLIKE 贏家 | QLIKE t_HAC (p) | MSE ratio (ARFIMA/HAR) | MSE 贏家 | MSE t_HAC (p) | 排序反轉？ |
|---|---|---|---|---|---|---|---|
| VIX | 1.0431 | HAR | +1.71 (0.088) | 1.0017 | HAR | +0.03 (0.974) | — |
| SPY | 1.0297 | HAR | +1.40 (0.163) | **0.8888** | **ARFIMA** | −0.97 (0.335) | ✅ |
| TW0050 | 1.0388 | HAR | +0.57 (0.571) | **0.8359** | **ARFIMA** | −0.99 (0.320) | ✅ |
| QQQ | 1.0589 | HAR | **+2.13 (0.033)** | **0.8742** | **ARFIMA** | −0.90 (0.368) | ✅ |
| N225 | 0.9710 | ARFIMA | −0.50 (0.617) | **0.8914** | **ARFIMA** | −1.12 (0.265) | — |

（t > 0 表示 HAR 較優。ratio < 1 表示 ARFIMA 較優。）

**結論（必須完整讀，缺一句就會誤導）**：

1. **在 HAR-vs-ARFIMA 這一對上**：QLIKE 說 HAR 在 4/5 資產較低；MSE 說 ARFIMA 在 4/5 資產較低，
   且低 11–16%。**5 個資產有 3 個排序反轉。**
   （**限定**：這是**兩兩比較**，不是全模型排名。全 5 模型的 QLIKE 冠軍只有 3 個是 HAR
   ——VIX 是 AR1、N225 是 ARFIMA，見 `per_asset.*.best_by_qlike`。）
2. **但兩個 loss 都沒有任何一個 ARFIMA-vs-HAR 比較達到統計顯著**（MSE 的 p ∈ [0.265, 0.974]）。
   所以**這不是「ARFIMA 在 MSE 下打敗 HAR」的發現**——`headline_finding.what_this_is_not` 明文標註。
3. **可辯護的結論是：兩者統計上無法區分。** 而一個只看到單邊 loss 表的讀者，
   **會在兩個方向上分別得出相反的方向性結論**。這才是本輪的方法論產出。
4. MSE 在 variance-level 資料上被少數極端觀測主導，這正是 11–16% 的平均差距仍帶著大標準誤的原因
   （呼應 Patton 2011 對 proxy 下 loss 選擇的討論）。

**多重比較（BH FDR @ within_loss_20，family size = 20）**：

| 家族 | 名目顯著 (p<0.05) | BH FDR 後 | Bonferroni 後 |
|---|---|---|---|
| QLIKE 全 20 比較 | 8 | 7 | 3 |
| MSE 全 20 比較 | 2 | **0** | **0** |
| **focal（ARFIMA/BreakHAR only, 10 QLIKE）** | **1** | **0** | **0** |
| **focal（ARFIMA/BreakHAR only, 10 MSE）** | **0** | **0** | **0** |

**⚠️ 撤回宣稱 #3**：第一輪 §3/§6.3 稱 ARFIMA/break-robust「**多處反而顯著更差**」。
**實際上 10 個 focal QLIKE 比較中只有 1 個名目顯著**（QQQ/ARFIMA，rev2 HAC 後 t=+2.13, p=0.0332；
第一輪無 HAC 的 t=+2.47, p=0.0137），**且 BH 修正後 p=0.083，不存活**。
正確說法是「**一個名目顯著的比較，且通不過多重比較修正**」。
（QLIKE 家族中 7 個存活 BH 的比較**全部是對付刻意樸素的 baseline**——VIX/EWMA、SPY/AR1、SPY/EWMA、
QQQ/AR1、QQQ/EWMA、N225/AR1、N225/EWMA。HAR 打敗 AR(1) 與 EWMA 不是本實驗有爭議的宣稱。）

**HAC 修正是雙向的，不是單向灌水**（呼應 `.claude/rules/experiments.md` 的 k621 教訓）：
40 個比較中 **31 個 |t| 縮小、9 個 |t| 放大**。4 個 loss-differential acf(1) 為負的比較**全部放大**。
5% 判定改變的有 3 個（SPY/MSE/EWMA、TW0050/MSE/BreakHAR、QQQ/MSE/EWMA，皆由顯著轉不顯著）。
**稽核者不可預設「漏做 HAC 只會灌水」。**

**未受影響的結論**：BreakRobustHAR vs HAR 的 10 個比較（兩 loss）**全部不顯著**，最小 p=0.106。

### 6.4 Generated-regressor Monte Carlo（rev2 新增 `k1623_rev2_mc.py`；**rev3 加入 Arm C** `k1623_rev3_armc_mc.py`）

brief 要求至少在 limitation 揭露「demeaned d̂ 的 SE 未計入斷點是估計出來的」。rev2 進一步**量化**它。

設計：500 次重複，seed=42，burn-in 2000。DGP = ARFIMA(0, d̂, 0) + 在**估計出的斷點日期**植入
**已擬合的分段常數 level**。
- **Arm A**（真實）= 模擬 → Bai-Perron **重新估計**斷點 → demean → ELW
- **Arm B**（**partition oracle**）= 模擬 → 在真實斷點 partition（**數量＋位置**）demean → ELW
- **Arm C**（**完全 oracle**，rev3 新增，`k1623_rev3_armc_mc.py`）= 模擬 → 減去**已知的植入 level 向量**
  → ELW（斷點位置與各段 level **都不估計**；數值上等於直接對原始 ARFIMA 路徑跑 ELW）

> **✅ rev3 更新（2026-07-20）— 原本的「已揭露、未修復」缺口現已量測**：
> `k1623_rev2_mc.py:118-120` 的 Arm B 呼叫 `K.piecewise_demean(x, breaks_true)`，
> **斷點 partition（數量＋位置）用真值，但每段的「均值」仍是從模擬資料估出來的**
> （沒有用已知的植入 level 向量）。
> 所以 Arm B oracle 化的是**整個斷點 partition**；A−B 隔離 BIC 同時選數量與位置的合併成本，
> 「估各段均值」的成本在 A、B 兩臂都存在而被差分掉。
> rev2 當時把這個缺口列為 **DISCLOSED, NOT FIXED**（揭露但未量測、也未設上界）。
> **rev3 加入 Arm C 後，該項已從「未量測」變成「已量測」**：`B−C = −0.043 至 −0.022`（見下表）。
> Arm A / Arm B 在 Arm C 這一輪**完整重現**了凍結的 rev2 數值（rtol=1e-9，5/5 資產），
> 證明三臂踩在**同一批模擬路徑**上、B−C 是乾淨的配對對照。
>
> **⚠️ B−C 只能這樣讀（不可加碼）**：Arm C **不是 zero-mean oracle**。
> `local_whittle(exact=True)` 依 Shimotsu-Phillips 定義，內部**仍然減去一個單一的樣本總均值**，
> 且 A、B、C **三臂都一樣**。所以 Arm C 估 1 個總均值，Arm B 估 `n_breaks+1` 個分段均值 ——
> **B−C 是「估分段均值」相對於「ELW 自身那一次單一總均值 demeaning」的<u>增量</u>成本**，
> **不是「估計任何均值的總成本」**，也不可被引述為後者。
> 真實資料上某種 demeaning 本來就不可免，所以增量才是對的比較口徑；
> 但把增量說成總量，就是 rev2 對 Arm B 犯過、已經撤回的**同一類 overclaim**。

**表 A — 偏誤分解（加法可分解，`additivity_residual = 0.0`，5/5 資產）**

| 資產 | d̂ (fitted) | 總偏誤 (Arm A) | **斷點 partition 選擇：數量＋位置 (A−B)** | **段均值估計 (B−C，增量)** | **生成迴歸子合計 (A−C)** | ELW 自身 (C−d̂) | 斷點**數**精確回收率 |
|---|---|---|---|---|---|---|---|
| VIX | 0.645 | −0.027 | **−0.020** | **−0.026** | **−0.046** | +0.018 | 78.4% |
| SPY | 0.475 | −0.085 | **−0.045** | **−0.040** | **−0.085** | +0.001 | 56.4% |
| TW0050 | 0.563 | −0.065 | **−0.056** | **−0.022** | **−0.078** | +0.013 | **7.0%** |
| QQQ | 0.457 | −0.077 | **−0.041** | **−0.043** | **−0.084** | +0.007 | 56.0% |
| N225 | 0.460 | −0.084 | **−0.046** | **−0.043** | **−0.089** | +0.004 | 63.4% |

（定義：「總偏誤」= `arm_a.mean − d_demeaned_fitted`；「A−B」= `arm_a.mean − arm_b.mean`；
「B−C」= `arm_b.mean − arm_c.mean`，**相對 ELW 自身單一總均值 demeaning 的增量**（見上方警告框）；
「A−C」= (A−B) + (B−C) = 生成迴歸子偏誤合計；「C−d̂」= ELW 自身有限樣本偏誤，
**含**其內建的單次 demeaning 與 FD_MAXK=2000 截斷效應，**不是**純 zero-generated-regressor 量。
A−B 欄與凍結的 `k1623_rev2_mc_results.json` → `claim_corrections_rev3.corrected_attribution`
**逐位元相同**；其餘欄位出自 `k1623_rev3_armc_results.json` → `per_asset.<資產>.bias_decomposition`。）

**表 B — 抽樣 sd 分解（乘法：`sd_A/SE = f1 × f2 × f3`，`product_check` 5/5 相符）**

| 資產 | 已發表漸近 SE | MC sd (Arm A) | SE 低估倍數 | f1 漸近公式 | f2 段均值估計 | f3 斷點 partition 選擇 |
|---|---|---|---|---|---|---|
| VIX | 0.0398 | 0.0518 | **1.30×** | 1.195 | 1.072 | 1.016 |
| SPY | 0.0472 | 0.0629 | **1.33×** | 1.126 | 1.123 | 1.053 |
| TW0050 | 0.0408 | 0.0496 | **1.21×** | 1.043 | 1.058 | 1.101 |
| QQQ | 0.0472 | 0.0619 | **1.31×** | 1.067 | 1.188 | 1.034 |
| N225 | 0.0475 | 0.0602 | **1.27×** | 1.102 | 1.140 | 1.010 |

（`f1 = sd_C/SE_published`（漸近公式自身的樂觀程度）、`f2 = sd_B/sd_C`（估段均值）、
`f3 = sd_A/sd_B`（BIC 選斷點 partition：數量＋位置）。來源：
`k1623_rev3_armc_results.json` → `per_asset.<資產>.sd_decomposition`。）

**四個發現（含一個與批評方向相反、仍如實報告）**：

1. **已發表的 SE 確實低估**：真實抽樣 sd 是漸近 SE 的 **1.21–1.33 倍**，原信賴區間過窄。
2. **三通道只報描述性點估；500 reps 無法識別主導通道（rev4 再降級）**：
   三因子的點估範圍是漸近公式 **1.043–1.195×**、段均值估計 **1.058–1.188×**
   （rev2 的兩臂設計看不見這一項）、斷點 partition 選擇 **1.010–1.101×**。
   但 500 次重複下單一 sd 點估的粗略相對 Monte Carlo SE 約為
   `1/√(2×499) ≈ 3.2%`（高斯近似的量級檢查；本 artifact 未保存 replication-level draws，
   無法估 paired covariance 或 bootstrap 排名）。SPY、N225、TW0050 的前兩名差距只有
   **0.31%、3.45%、4.08%**；因此 rev3 的逐資產 argmax 分類也沒有識別基礎，已從 README 與
   機讀 summary 撤下。各因子接近 1 的個別點估同樣不足以支撐「每個 factor 都 >1」。
   **可識別且存活的只有總量**：Arm A 的 MC sd / 已發表 SE 為 **1.21–1.33×**，與 3.2% 的
   粗略 MC 噪音充分分離；這支撐「總 SE 被低估」，不支撐低估由哪個通道主導。
3. **擬合斷點會機械性地把 d̂ 往下拉**，即使模擬的 DGP **恰好只含**被移除的那些 level shift。
   **正確歸因是配對 A−B contrast = −0.056 至 −0.020**（權威：
   `claim_corrections_rev3.corrected_attribution.break_partition_selection_effect_range_a_minus_b`）。
   **⚠️ rev3 更正**：本段原本寫「往下拉 **−0.085 到 −0.027**」——那是 **Arm A 的總偏誤**，
   其中 −0.039 至 −0.007 是 Arm B 在真實斷點位置下就已經有的偏誤。
   **把總量說成斷點估計的效應，約高估兩倍**。§9 表格的 MED 條目早已改用 A−B，本段之前沒跟上，
   造成同一份 README 內部自相矛盾 —— 現已統一。
   質性結論不變：第一輪報告的 raw → demeaned d̂ 下降，**有一部分是擬合斷點的機械假象，
   不是額外 level shift 的證據**；這在**兩個方向**上都削弱了第一輪的解讀。
   **rev4 更正**：Arm A 重新跑 BIC、同時選斷點數量與位置，而 Arm B 固定整個真實 partition；
   因此 A−B 是「選斷點 partition（數量＋位置）」的合併通道，不能再叫「找斷點位置」（數值未變）。
   Arm C 使**生成迴歸子的合計**效應也可量測 = **A−C = −0.089 至 −0.046**
   （`summary.total_generated_regressor_range_a_minus_c`），其中段均值估計佔 **28.8%–56.3%**
   （`bias_decomposition.mean_estimation_share_of_generated_regressor`，5/5 資產
   `shares_are_interpretable = true`，因三項偏誤同號故比重可解釋）。
4. **斷點「數量」回收很吵**：精確回收斷點**數**的比例只有 **7%–78%**（TW0050 最差 7%）。
   **⚠️ rev3 撤回（Codex round 2 §7）**：凍結 JSON 的 `finding_4` 原本附帶一句
   「break **dates** are estimated with substantial uncertainty」——**本 artifact 不支撐這句**：
   模擬只記錄被選中的斷點**數量**，從未儲存或比對估計出的斷點**日期**，
   因此無法量化定位誤差。該句已在 `claim_corrections_rev3.superseded_claims` 明列撤回。
   **本 README 不作任何關於斷點日期不確定性的宣稱。**

**存活的**：以 MC sd 0.045–0.063 對 d̂ 0.457–0.645，**d/sd = 7.4–12.5**，故 break-demeaned d̂
在此模型下仍明確為正。**但這是「殘餘持續性」的陳述，不是識別結果**——
再多的 SE 修正也不能讓一個 5 斷點的決定性模型去回答隨機密集 shift 的替代假說。

**MC 的 scope 限制（必讀）**：
1. 此 MC 是 **model-conditional** 的——它假設 DGP **真的是** ARFIMA + 估計日期上的決定性斷點，
   量化的是**該模型下**的抽樣不確定性。
   **它不是對該模型的檢定，也不是支持該模型的證據，更無法處理 Diebold-Inoue 的隨機／密集 shift DGP。**
2. **Arm B oracle 化整個斷點 partition（數量＋位置）**，仍估各段均值 →
   A−B 隔離的是 BIC partition 選擇成本，混合 count-selection 與 location-estimation，不能拆讀。
   **rev3 更新**：mean-structure 那一份已由 Arm C 量測（B−C = −0.043 至 −0.022），
   此項不再是未量測缺口 —— 但**只在下一條的限定內成立**。
3. **Arm C 不是 zero-mean oracle**：`local_whittle(exact=True)` 在**三臂**都會減去一次單一樣本總均值。
   故 (i) 該步驟在差分中抵消，**不汙染** B−C 與 A−C；
   (ii) 但 **B−C 是相對該次單一 demeaning 的<u>增量</u>成本，不是「估計任何均值的總成本」**；
   「ELW 自身偏誤 (C−d̂)」同理**不是**字面上的 zero-generated-regressor 量，且**含** FD_MAXK 截斷效應。
   把任一項引述為更強的版本，等於對 Arm C 重犯 rev2 已為 Arm B 撤回的那個 overclaim。
4. **Arm C 的 oracle 資訊在真實資料上不存在**：它減去的是模擬時**植入**的 level 向量，
   因此 Arm C 是**分解工具，不是任何人能用的估計量**。
5. **主導 sd 因子未識別**：500 reps 下單一 sd 估計的粗略相對 MC SE 約 3.2%，且缺少
   replication-level draws 估 paired covariance。機讀 artifact 不再輸出逐資產 argmax；
   三通道數值只能讀成描述性點估。
6. **只有斷點數量、沒有斷點日期**：本 artifact 無法對日期定位誤差說任何話（Arm C 不改變這點）。
7. 高斯 innovation；FD_MAXK = 2000 截斷在此同樣 binding，**且對 Arm C 也 binding**。

## 7. Verdict 與 caveats（rev2）

**Verdict**：
1. **識別問題：未解決，且本實驗不再宣稱解決。** 扣斷點後 d̂ 仍為正是**描述性殘餘持續性**。
2. **預測：null。** QLIKE 與 MSE 兩個 loss、經 BH 修正後，ARFIMA 與 BreakRobustHAR 都**與 HAR 無法區分**。
3. **方法論產出（本輪最有價值的部分）：模型排序隨 loss function 在 3/5 資產反轉，而第一輪只報了其中一個 loss。**
4. **可交易性：不表態**（零測試）。

**Residual limitations（機讀版：`k1623_rev2_results.json` → `residual_limitations[]`）**：
1. **識別未被取代，只被撤回**。要檢定真 vs 假 long memory，需要為**隨機／密集** shift 過程設計的檢定——
   Qu (2011) score test、Shimotsu (2006) splitting、或 Perron-Qu (2010)。**本實驗一個都沒實作。**
2. **demeaned d̂ 的 SE 是下界**（未計入斷點是估計的）。§6.4 的 MC 量化了缺口（1.21–1.33×），
   但 MC **不能替代正確的解析 SE**。
3. **ELW 是 sample-mean demeaned**，非 Shimotsu-Phillips μ̂(d)。**VIX（d̂=0.723>0.5）最不可信。**
4. **FD_MAXK = 2000 對每個資產都 binding**，d 最大處（VIX）咬得最深。
5. **VIX permissive 斷點 15/15 cap binding** → 20.3% **不是上界**，該側開放。
6. **零交易／成本／效用測試**（任何一輪都沒有）。
7. **RV proxy 是 daily range（Parkinson）**，非 5-min RV；measurement error 影響 d̂ 的**水準**。
8. **OOS 為 one-step**；h=5/22（需 overlapping-forecast HAC）未測試。
9. **TW0050 為近似重現**（上游快取修訂，n 差 1，最大相對偏差 5.26e-3）。
10. cross-asset 僅 diagnostic，未 pool asset-day。
11. **level shifts vs temporary spikes**：mean-break demean 無法移除 VIX 的 GFC/COVID 暫時性 spike。

## 8. 產出

| 檔案 | 內容 | 狀態 |
|---|---|---|
| `k1623.py` | 第一輪主程式（~7s） | **未修改**（依 brief 選項 (i)）；**4 個 exact-pin 資產的聚合損失重現到 1e-9，TW0050 的預測值因上游 vintage 修訂而變動** — 見 `scope_and_limits` |
| `k1623_results.json` | 第一輪全部統計量 | **預測值有效；DM 推論已被 rev2 取代** |
| `k1623_rev2.py` | rev2 主程式：vintage pinning、重現性 guard、40 個 HAC DM、BH/Bonferroni | 新增 |
| `k1623_rev2_results.json` | **rev2 權威結果**：`dm_comparisons[40]`、`retracted_claims[8]`、`loss_function_sign_reversal[5]`、`residual_limitations[11]`、`reproduction_guard` | 新增 |
| `k1623_rev2_mc.py` | generated-regressor Monte Carlo（500 reps, seed=42, ~306s） | 新增；**rev3 修正 Arm B 的描述與欄位命名（不改任何計算）** |
| `k1623_rev2_mc_results.json` | MC 結果 + scope 限制 | 新增；**rev3 附加 `claim_corrections_rev3`（原數值欄位一格未動）** |
| `k1623_rev3_patch_mc_artifact.py` | rev3 標註工具：把 MC artifact 的失效宣稱逐條標記，並由凍結的 arm means **計算** A−B 正確歸因 | 新增（含 guard：任一原數值欄位被改動就拒絕寫入） |
| `k1623_rev3_remediation.json` | rev3 本輪的 remediation 紀錄（逐 blocker 的 before/after + 自檢結果） | 新增 |
| `k1623_rev3_armc_mc.py` | **Arm C**（完全 oracle）三臂 MC（500 reps, seed=42, ~308s）；內含對凍結 rev2 arm A/B 的 `ReproductionFailure` gate | 新增 |
| `k1623_rev3_armc_results.json` | **Arm C 權威結果**：三臂 `bias_decomposition` / `sd_decomposition` / `reproduction_check_vs_frozen_rev2_mc` | 新增；**未修改 rev2 MC artifact 任何一格**（`supersedes_nothing`） |
| `plots/` | 每資產 4 圖（共 20 張） | 未修改 |

**Arm C 與凍結 artifact 的關係**：`k1623_rev3_armc_mc.py` 以唯讀方式開啟 `k1623_rev2_mc_results.json`，
**只新增一臂、不改寫任何既有欄位**。Arm C 不消耗亂數，故 eps 串流與凍結 rev2 完全相同 ——
這點由 arm A/B 的重現 gate（rtol=1e-9，5/5 資產 `all_ok = true`）**驗證**而非假設。

**README 數字的來源分佈（rev3 更正）**：

> **⚠️ 這裡原本寫「每一個 README 數字都可在 JSON 逐項對上」——Codex round 2 §2 指出這句為假**：
> 它讓人以為單看 `k1623_rev2_results.json` 就能核完全文，但 README 的數字實際散落在**三份** artifact。
> 誠實的對應如下：

| README 段落 | 數字來源 | 檔案 |
|---|---|---|
| §6.1 ACF sum、raw ELW d̂ | 第一輪 artifact | **`k1623_results.json`** |
| §6.2 d_raw / d_demean / 斷點數 / 頻寬 pattern | 第一輪 artifact | **`k1623_results.json`** |
| §3 重現性、n、pin dates、最大相對偏差 | rev2 | `k1623_rev2_results.json` → `reproduction_guard` |
| §6.3 全部（ratio / t / p / BH / Bonferroni / 反轉） | rev2 | `k1623_rev2_results.json` → `dm_comparisons[]`、`loss_function_sign_reversal[]` |
| §6.4 表 A「d̂」「總偏誤」、表 B「漸近 SE」「MC sd」「低估倍數」、回收率 | MC | `k1623_rev2_mc_results.json` → `per_asset` |
| §6.4 表 A「A−B」欄 | MC（rev3 由凍結 arm means **計算**，非重跑；與 Arm C 那輪重跑值**逐位元相同**） | `k1623_rev2_mc_results.json` → `claim_corrections_rev3.corrected_attribution` |
| §6.4 表 A「B−C」「A−C」「C−d̂」、表 B「f1/f2/f3」、通道點估與 dominance 未識別聲明 | **Arm C**（rev3 新增，重跑三臂） | **`k1623_rev3_armc_results.json`** → `per_asset.*.{bias,sd}_decomposition`、`summary` |
| §0 撤回表、§7 limitations | rev2 | `k1623_rev2_results.json` → `retracted_claims[]`、`residual_limitations[]` |

**所以正確的說法是：每個 README 數字都能在上表指定的那一份 artifact 裡對上 —— 但不是全部都在 rev2 JSON 裡。**

## 9. Reviewer 與 reviewer 可靠度教訓

| 輪次 | Reviewer | 判定 |
|---|---|---|
| 第一輪 (2026-07-04) | codex-cli 0.142.3, **gpt-5.5** | **no CRITICAL / HIGH** |
| 孤兒收尾 (2026-07-17) | codex **gpt-5.6-sol**, reasoning=high | **FAIL**（7 條理由） |
| **rev2 (2026-07-19)** | codex **gpt-5.6-sol**（審 rev2 自身） | **no CRITICAL**；1 HIGH + 2 MEDIUM + 4 LOW，**全部已修**（見下） |

### rev2 自身也被抓到同一 class 的錯（如實記錄）

**rev2 的第一版草稿，犯了它自己正在修的那個毛病** —— 宣稱超出證據。二審抓到 7 條，全部已修正：

| 嚴重度 | 發現 | 修正 |
|---|---|---|
| **HIGH** | 宣稱「forecasts unchanged / same forecasts, same sample」，但 guard 只比對**聚合**統計量、且 TW0050 根本沒被 assert | guard 由 50 → **100 格**（加 `qlike_median` + `clip_hit_rate` 兩個獨立泛函，仍 1e-9 全中）；措辭改為「重現出的**聚合損失**相同」；新增 `scope_and_limits` 明寫逐期比對**不可能**（原 artifact 沒存）；明寫 TW0050 不適用此宣稱 |
| **MED** | `t_hac_hln` 有算但 `p_hac` 對應的是未乘 HLN 的 t，且送進 BH 的是後者 | 新增 `p_hac_hln` 欄位並揭露不對稱；實測最大差 3.2e-4、**0 個判定改變** |
| **MED** | MC 把 arm A 的**全部** bias（−0.085 至 −0.027）歸因於 break 估計，但 oracle arm B 本身就有 ELW 有限樣本 bias | 改報**配對 A−B contrast = −0.056 至 −0.020**（真正歸因於估計斷點的部分），並分列 ELW 自身 bias。原數字**高估約兩倍** |
| **LOW** | 稱「三個 family」，實際是**五個巢狀重疊**集合 | 措辭更正；並在 code 中**事前指定** primary family，說明非 primary 者為 sensitivity 而非菜單 |
| **LOW** | canonical `dm_test` 的 γ_lag 用 1/(n−lag) 非統一 1/n；LRV≤0 時靜默回傳 (0,1) | 揭露兩者（**未改 canonical 函式**，超出 scope）；實測統一 1/n 為 t=1.706008 vs 1.707107，無實質差異；**實測驗證 40 列無一觸發 LRV 分支** |
| **LOW** | MC 只記錄 break **數量**回收率，卻宣稱 break **日期**不確定性 | 措辭收窄為「數量回收率」，明寫本 artifact **無法**量化日期定位誤差 |
| **LOW** | headline 寫「No MSE comparison reaches significance」，但 summary 顯示 MSE 名目顯著 = 2 | 收窄為「無任何 **ARFIMA-vs-HAR** 的 MSE 比較顯著」+「無任何 MSE 比較存活修正」，並註明那 2 個名目顯著都是對 EWMA baseline |

**這件事本身就是教訓**：一個專門為了「修正 overclaim」而存在的修訂輪，初稿仍然產生了 7 條 overclaim。
**「意識到某個錯誤模式」不等於「不會再犯它」——只有被獨立審查逐條對帳才會被抓出來。**

**兩份 review 對同一份 code 直接衝突。** 第一輪 review 確認了 lookahead / QLIKE orientation /
ARFIMA 索引等**機械正確性**（這些 rev2 複驗仍然成立），但**完全沒有捕捉到**：
識別宣稱缺乏定理支撐、DM 只跑了一個 loss、`range(1, h)` 使 HAC 完全失效、
「多處顯著更差」與結果表不符、ELW 與 BreakRobustHAR 的描述與 code 不符。

**教訓（已寫入 `docs/error_log.md`）**：**「Codex 判 no CRITICAL/HIGH」不等於「宣稱與證據相符」。**
code review 天然會去看「程式有沒有照它想的跑」，而第一輪的失效全部落在
**「README 對人類說的話，有沒有被程式產生的數字支撐」**——這是一個**不同的檢查面**，
必須被**明確要求**才會執行。K1709 的教訓（自帶測試全過但違反 repo 硬規則）是同一個 class 的另一面。

**本輪 reviewer**：見 `review_verdict.json`（gate 產生，pin 住 claim surface sha256）。

## 10. 可發佈 angle（素材已備妥，**本輪不寫文章**）

撤回識別宣稱後，仍有一個**純描述性、可從 JSON 直接驗證**的可發佈素材：

> **「同一份預測、同一批模型、同一個評分窗，換一個 loss function 結論就反轉」**
> —— 在 **HAR 對 ARFIMA** 這一對上：QLIKE 說樸素 HAR 在 5 個資產中有 4 個較低；
> MSE 說 ARFIMA 在 5 個資產中有 4 個較低、且低 11–16%。
> 5 個資產有 3 個排序反轉。**而兩邊都不統計顯著**——所以真正的教訓不是「哪個模型好」，
> 而是**「只報一個 loss，就等於製造了一個方向性結論」**。

- **寫文章時不可省略的兩個限定**（省掉任一個，文章就變成第一輪錯誤的鏡像版本）：
  1. 這是 **HAR-vs-ARFIMA 的兩兩比較**，**不是**「HAR 是 5 資產冠軍」。全 5 模型的 QLIKE 冠軍
     只有 3 個是 HAR（VIX=AR1、N225=ARFIMA）。
  2. 「同一個樣本」**對 TW0050 為假**（n 4,263→4,264，上游歷史修訂）。要寫成「同一份預測程式 +
     同一個評分窗」，4 個資產的聚合損失重現到 1e-9、TW0050 為近似重現（最大相對偏差 5.26e-3）。

- **呼應** K1016（loss function 選擇影響結論）與 Patton (2011)。
- **誠實線**：文章**必須**同時寫出「兩個 loss 都不顯著」，否則就變成第一輪錯誤的鏡像版本。
- **可加碼**：第一輪 `range(1, h)` 讓 HAC 完全失效、且修正是**雙向**的（31 縮 / 9 漲）——
  這是一個具體、可驗證的「檢定設定細節如何改變結論」案例。
- **資料來源**：`k1623_rev2_results.json` 的 `loss_function_sign_reversal[]` 與 `dm_comparisons[]`。
