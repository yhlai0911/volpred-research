# K1684 — forecast-tail-divergence E1：變異數目標尺度再校準 gating 實驗

- **Experiment ID**: `k1684`
- **Status**: completed
- **執行日期**: 2026-07-12（台灣時間）
- **提出者**: Fable 深度審查 2026-07-11（`paper/forecast-tail-divergence/review_history/fable_deep_review_20260711/` §5.1 E1，P0 gate）
- **父實驗**: `experiments/k850`（原始 headline）、`experiments/k854`（common-sample 修正版）
- **腳本**: `k1684_ftd_e1_scale_gating.py` ｜ **結果**: `k1684_ftd_e1_scale_gating_results.json`
- **資料**: `data/`（TX 5-min RV + 0050.TW 調整後收盤，皆已 pin 成 snapshot）

---

## 1. 裁決（Go / No-Go）

> ## **H2 REJECTED** → 走 **FRL / Journal of Forecasting 方法論短文**，不走完整 IJF 論文
>
> **四個 run（primary + 3 個敏感度）全部得到相同裁決。**

**理由不是「校正後 VaR 就過了」，而是 divergence 的第一條腿根本不存在。**

「QLIKE 與尾部覆蓋正交」這個命題需要兩條腿同時成立：

| | 命題需要的 | K1684 實測（450 天共同樣本） |
|---|---|---|
| **腿 1（預測損失）** | HAR 在 QLIKE 上贏 GJR | **不成立。** 在**對齊目標**（0050 r²）上 DM t = **+2.33（GJR 較優，p = 0.020）**。那個著名的 t ≈ −5.6 只在對 **TX RV**（HAR 自己的預測目標）評分時才出現：t = **−5.13** |
| **腿 2（尾部覆蓋）** | HAR 的 VaR 失敗、GJR 過關 | 尺度校正把 1% 違規從 **17/450 → 7/450**（Kupiec p 由 0.000 → 0.273，**過了**），但 Basel 仍黃燈 → trinity 仍 FAIL |

**腿 1 在源頭就斷了**：把兩個模型放在同一個目標上評分，HAR 不但沒贏，還輸。K850/K854 的 QLIKE 勝利是**對 HAR 自己的目標評分**造成的 — 這正是 VaR 端錯配的**鏡像**：同一個目標錯配，在 QLIKE 端**獎勵** HAR、在 VaR 端**懲罰** HAR，兩邊合力製造出「divergence」的表象。

沒有共同目標上的預測損失優勢，就沒有「正交性」可談 — 不論尾層怎麼修。

---

## 2. 動機與差異化

K850/K854 的 headline：**HAR-RV 的 QLIKE 大勝 GJR（DM t = −5.60），但 1% VaR 17/450 = 3.78%、Basel RED；GJR+CF 卻 trinity PASS。** 深審指出這被一個內生混淆威脅：HAR 的 σ 來自 **TAIFEX TX 期貨 5-min RV**，VaR 卻打在 **0050.TW ETF 的 close-to-close 報酬**上。

深審的定量指紋（violation-implied scale factor `c = Φ⁻¹(α)/Φ⁻¹(π̂)`）：HAR+CF 在 1% 與 5% 的 c 幾乎同值（1.31 / 1.30）→ **純尺度錯配**（σ 系統性低估約 30%），而非尾形錯設。

**E1 是 gating 實驗**：只動 σ，其他全部釘死在 K854 的建構上，重跑完整 1% + 5% trinity。

---

## 3. 設計（含三處超出 brief 的修正，每一處都有實證理由）

### 3.1 三個尺度再校準 variant

| Variant | 定義（θ 只用 t 之前的資料估） | primary run 的 s（OOS 平均） |
|---|---|---|
| **(a) expanding std(z)** | `σ_adj,t = σ_HAR,t × s_t`，`s_t = std(z_u, u < t)`，`z = r/σ_HAR` | **1.354** |
| **(b) Mincer-Zarnowitz** | `log r² ~ a + b·log σ²_HAR`（expanding OLS），用 Duan (1983) smearing 映回變異數尺度 | 隱含尺度 **1.349**（斜率 b = **0.68**） |
| **(c) Hansen-Lunde (2005) scaling** | `σ²_adj = σ²_HAR × (Σr² / ΣRV)_{u<t}`（純 realized 量，不含預測） | **1.204** |
| **PLACEBO：同一套機器套在 GJR 上** | GJR 的 σ 本來就 fit 在 VaR 評分用的那組報酬上 → 不該有錯配 | **1.126** |

**三個獨立估計量一致指向 σ 低估約 20–35%**，而 placebo 只有 12.6% — 校正機器沒有把正確對齊的模型也亂放大。

### 3.2 三處超出 brief 的修正

**(i) Brief 的 variant (c) 前提（「RV 缺隔夜」）被實證推翻，因此改寫。**
腳本 `verify_session_alignment()` 直接讀原始 tick 檔驗證：TAIFEX 把 15:00–05:00 的夜盤掛在**次一交易日**的成交日期下（抽查 40 個檔，**40/40** 的 15:00 tick 成交日期都是前一日）。例如 `Daily_2024_03_01TX1.csv` 內 15:00 的 tick，成交日期是 **20240229**。

→ `rv_total(D)` 的視窗其實是 **15:00(D−1) → 13:45(D)**，**已經涵蓋** 0050 的 close-to-close 視窗（13:30(D−1) → 13:30(D)）。「缺隔夜」不是錯配來源。真正的來源是**成分與基差**：TX 標的是 TAIEX，0050 是台灣 50（台積電權重遠高於 TAIEX）。

→ 因此 (c) 實作為 brief 明列的替代方案（「以 t−1 以前樣本估的 c2c/RV 變異數比例」），即 Hansen–Lunde 的 realized scaling estimator。

**(ii) 加入 placebo control。** 把同一套 (a) 校正套在 GJR 上。若校正是正當的尺度修正而非硬湊的 fudge factor，它必須讓正確對齊的模型維持在 1.0 附近。實測 1.126。

**(iii) 尾層殘差池與 θ 估計窗必須解耦 — 這是本實驗最大的陷阱。**
初版把兩者綁在一起（延長殘差池到 2018 以含 COVID），結果**未做任何尺度校正**的 baseline HAR+CF 自己就從 17/450 掉到 **4/450**（Basel 綠）。那是**尾形通道**的效應（COVID 拉高峰態 → CF 分位數變寬），若不拆開，就會被誤記在尺度校正的帳上。

→ 最終設計：**尾層殘差池（決定 skew/kurt）永遠釘死在 K854 慣例**（OOS-only、63 天更新）；**θ（只影響 σ）**才用較長的即時窗（2018+）。此舉的必要性也是實證的：MZ 迴歸在 OOS 起點只有 31 個觀測時，斜率估成 **b = −0.03**（退化成常數變異數），根本測不到東西。
→ 綁在一起的那個組態保留為明確標示的**診斷 run**（`sens_burnin_tailpool`），**不參與裁決**。

---

## 4. Lookahead audit（機械驗證，非口頭宣稱）

不用「代碼裡有 shift(1)」這種宣稱，改用**擾動測試**：把 forecast origin `i` **當天及之後**的所有觀測值 **× 10**，然後要求 origin 當下的每一個預測與校正參數**逐位元不變**。任何偷看到未來的量，在這個擾動下必定會動。

涵蓋：HAR 預測、GJR 預測、θ 的三組參數（`s_a`、`k_c`、MZ 的 `a/b/smear`）。

> **結果：30 個 assertion 全數通過**（`lookahead_audit.all_passed = true`）。audit 失敗時腳本直接 `raise`，拒絕輸出結果。

各校正因子的資訊集邊界：

| 量 | 資訊集 | 保證方式 |
|---|---|---|
| HAR 預測 σ²_t | `rv[:t]`（expanding，每 63 天 refit） | K854 `har_oos_forecasts` + 擾動測試 |
| `s_a,t`、`k_c,t`、MZ 係數 | 僅 `u < t` 的 pool（`estimate_theta(np.arange(start, i), ...)`） | 切片上界為 `i`（不含）+ 擾動測試 |
| 尾層分位數（CF / HistSim） | 同一個 `u < t` 的殘差池 | 與 θ 同一次 refresh 快照 |
| GJR / RGL | `r[:i]`（K854 原樣） | 擾動測試 |

**共同樣本強制**：任一 cell 只要無法覆蓋全部 450 個評估日，就**整格移除並明列**（`cells_unavailable`），**絕不**用「它剛好有資料的那些天」去回測 — 那正是 K854 當初修掉的不公平比較。gate run 不允許移除任何格（違反即 `raise`）。

---

## 5. 結果（primary run，450 天共同樣本，2023-03-01 ~ 2024-12-31）

**Baseline 完全複製 K854**：HAR+CF 17/450、HAR+Normal 15/450、HAR+HistSim 9/450、GJR+CF 3/450、RGL+CF 3/450（見 §7 複製檢查）。

### 5.1 1% VaR

| Cell | 違規 | 違規率 | Kupiec p | Ind p | CC p | Basel | Trinity | implied c [95% CI] |
|---|---|---|---|---|---|---|---|---|
| HAR+Normal | 15/450 | 3.33% | 0.000 | 0.517 | 0.000 | red | FAIL | 1.269 [1.12, 1.45] |
| **HAR+CF**（K854 headline） | **17/450** | **3.78%** | 0.000 | 0.668 | 0.000 | **red** | FAIL | **1.309** [1.16, 1.49] |
| HAR+HistSim | 9/450 | 2.00% | 0.060 | 0.163 | 0.065 | yellow | FAIL | 1.133 [0.99, 1.31] |
| **HAR-a+Normal** | **7/450** | 1.56% | **0.273** | 0.089 | 0.129 | yellow | FAIL | 1.079 [0.93, 1.25] |
| **HAR-a+CF** | **7/450** | 1.56% | **0.273** | 0.089 | 0.129 | yellow | FAIL | 1.079 [0.93, 1.25] |
| HAR-a+HistSim | 9/450 | 2.00% | 0.060 | 0.163 | 0.065 | yellow | FAIL | 1.133 [0.99, 1.31] |
| HAR-b+CF | 8/450 | 1.78% | 0.135 | 0.123 | 0.100 | yellow | FAIL | 1.107 [0.96, 1.28] |
| HAR-c+CF | 9/450 | 2.00% | 0.060 | 0.163 | 0.065 | yellow | FAIL | 1.133 [0.99, 1.31] |
| GJRf+CF（配對池的 GJR） | 11/450 | 2.44% | **0.009** | 0.261 | 0.018 | yellow | FAIL | 1.181 [1.03, 1.36] |
| GJRf-a+CF（placebo 校正後） | 10/450 | 2.22% | 0.025 | 0.209 | 0.037 | yellow | FAIL | 1.157 [1.01, 1.33] |
| GJR+Normal | 10/450 | 2.22% | 0.025 | 0.209 | 0.037 | yellow | FAIL | 1.157 [1.01, 1.33] |
| **GJR+CF**（K854 錨） | **3/450** | 0.67% | 0.449 | 1.000 | 0.751 | **green** | **PASS** | 0.940 [0.78, 1.13] |
| GJR+Skewed-t | 8/450 | 1.78% | 0.135 | 0.123 | 0.100 | yellow | FAIL | 1.107 [0.96, 1.28] |
| **RGL+CF** | **3/450** | 0.67% | 0.449 | 1.000 | 0.751 | **green** | **PASS** | 0.940 [0.78, 1.13] |

### 5.2 5% VaR

| Cell | 違規 | 違規率 | Kupiec p | Ind p | Basel | Trinity | implied c |
|---|---|---|---|---|---|---|---|
| HAR+Normal | 30/450 | 6.67% | 0.122 | 0.175 | yellow | FAIL | 1.096 |
| **HAR+CF** | **46/450** | **10.22%** | 0.000 | 0.522 | yellow | FAIL | **1.296** |
| HAR+HistSim | 26/450 | 5.78% | 0.460 | 0.247 | green | **PASS** | 1.045 |
| **HAR-a+CF** | 27/450 | 6.00% | 0.345 | 0.297 | green | **PASS** | 1.058 |
| HAR-a+Normal | 17/450 | 3.78% | 0.215 | 0.668 | green | **PASS** | 0.926 |
| HAR-b+CF | 28/450 | 6.22% | 0.251 | 0.111 | green | **PASS** | 1.071 |
| HAR-c+CF | 34/450 | 7.56% | 0.020 | 0.368 | yellow | FAIL | 1.146 |
| GJRf+CF | 36/450 | 8.00% | 0.007 | 0.497 | yellow | FAIL | 1.171 |
| GJR+CF | 20/450 | 4.44% | 0.582 | 0.905 | green | **PASS** | 0.967 |
| RGL+CF | 19/450 | 4.22% | 0.437 | 0.825 | green | **PASS** | 0.953 |

（完整 20 格 × 2 α × 4 runs 全在 results JSON。）

### 5.3 implied-c 通道診斷（尺度 vs 尾形）

| Cell | c(1%) | c(5%) | \|Δc\| | 判定 |
|---|---|---|---|---|
| **HAR+CF** | 1.309 | 1.296 | **0.013** | **SCALE**（兩個 α 幾乎同值、且遠離 1） |
| HAR+HistSim | 1.133 | 1.045 | 0.088 | SCALE |
| HAR+Normal | 1.269 | 1.096 | 0.173 | SHAPE（c 隨 α 發散） |
| HAR-a+CF（校正後） | 1.079 | 1.058 | 0.021 | **calibrated（c ≈ 1）** |
| GJR+CF | 0.940 | 0.967 | 0.027 | calibrated |
| GJRf+CF | 1.181 | 1.171 | 0.010 | SCALE |

深審的診斷**被證實**：HAR+CF 的 c 在兩個 α 水準幾乎相同 → 純尺度；校正後 c 回到 1 附近。這個 **violation-implied scale factor 作為「尺度 vs 尾形」判別工具**，是本 corpus 最有價值、可攜的方法論產出。

### 5.4 QLIKE / DM — 雙目標（這是裁決的關鍵）

DM 一律用 canonical `volpred.stats.model_evaluation.dm_test`；HAC bandwidth = `ceil(h^(1/3)·n^(1/3))` = **8**（**不是** `h−1`，後者在 h=1 時退化成不做 HAC）。loss differential 的 acf(1) 一併報告。

| 目標 | QLIKE（越低越好） | HAR-RV vs GJR（DM t） | 判定 |
|---|---|---|---|
| **TX RV**（K850/K854 慣例，**錯配**） | HAR-RV **0.1004** ｜ GJR 0.2081 | **t = −5.13**（p < 0.001，acf1 = +0.45） | HAR 大勝 |
| **0050 r²**（**對齊**，VaR 真正打的目標） | HAR-RV **1.8879** ｜ GJR **1.6272** | **t = +2.33**（p = 0.020，acf1 = +0.10） | **GJR 較優** |

**同一組預測、同一組模型，換一個目標，排名整個翻過來。**

尺度校正後（對齊目標）：HAR-a QLIKE = 1.6281 vs GJR 1.6272 → **DM t = +0.03（p = 0.976）＝ 打平**。
而 HAR-a vs HAR-RV（對齊目標）：**t = −2.54（p = 0.011）** → 尺度校正**真的**改善了 HAR 在對齊目標上的預測損失，與「σ 低估 30%」的診斷一致。

---

## 6. 敏感度與內部一致性

| Run | 設定 | baseline HAR+CF 1% | HAR-a+CF 1% | 裁決 |
|---|---|---|---|---|
| **primary（gate）** | 尾池 = K854（OOS-only, 63d）；θ 窗 = 2018+ | 17/450 | 7/450 | **H2_REJECTED** |
| sens_theta_short | θ 窗也用 K854 短池 | 17/450 | 7/450 | H2_REJECTED |
| sens_daily_refresh | 尾池每日更新 | 14/450 | 7/450 | H2_REJECTED |
| sens_burnin_tailpool | **尾池**延長到 2018（含 COVID）— **診斷用，不裁決** | **4/450** | 2/450 | H2_REJECTED |

**HistSim 尺度不變性（內部一致性檢查）**：HistSim 用經驗分位數，殘差以校正後的 σ 標準化時，分位數會被同一個因子除掉 → **任何純尺度校正都不可能移動它**。實測 `max|VaR_a − VaR_base| = 1.4e−17` → **恆等**。

這不是瑕疵，是一個**硬限制**：HAR+HistSim 的 9/450（2.0%、Basel 黃）**是尺度校正的下界** — 它失敗的部分，與尺度無關。

---

## 7. K854 複製檢查 + 一個意外發現（GJR MLE 脆弱性）

**11/14 格完全複製**。差異的分佈本身就是線索：

- **7 個 RV 驅動的 cell（HAR × 3 尾層、RGL+CF）全部完全吻合。**
- 差 1 個違規的 3 格**全部是 GJR**（GJR+Skewed-t @1%、GJR+Normal/+CF @5%）— 正是 σ 來自**報酬 MLE** 的那些格。

第一個假說（「報酬第 7 位小數飄移直接翻掉邊界違規」）**被自己的檢定推翻**：最接近 VaR 線的報酬距離有 3.6%（相對），rounding 等級的變動翻不動它。

真因是 **GJR 的 MLE basin 不穩定**（`fit_gjr` 只用 4 個隨機起點）。腳本內 `gjr_mle_fragility_probe()` 用 20 次抽樣實測：

> 對報酬施加 **1e-6 的相對擾動**（就是本次 yfinance 拉取與 K854 之間的差異量級）：
> - GJR 的 σ 最大變動 **29.0%**
> - persistence 在 refit 之間跳 basin（0.92 ↔ 0.97）
> - GJR+Normal 5% 違規數在 **[20, 21]** 之間游走，1% 在 **[8, 10]**
> - **K854 公布的 21（5%）與 10（1%）都落在這個擾動範圍內**

**這本身就是一個必須寫進論文的 caveat**：K854「GJR+CF trinity PASS」的結論，**對數值上無關緊要的資料修訂並不穩健**。任何下游論文都必須把 `fit_gjr` 的 multistart 拉高（本專案 pooled MLE 的硬規則是 ≥100）並報告 likelihood basin 分佈。

---

## 8. 對論文的結論：不是「一個混淆」，是**三個**

原 outline 的 divergence 敘事，被三個各自獨立、且**方向一致**的建構性混淆撐著：

1. **變異數目標尺度錯配**（σ 低估約 30%）— 在 VaR 端懲罰 HAR。三個獨立估計量一致，placebo 對照乾淨。
2. **QLIKE 的鏡像目標錯配** — 對 TX RV（HAR 自己的目標）評分，在預測損失端**獎勵** HAR。換成對齊目標，排名直接翻轉。
3. **尾層殘差池不對稱** — K854 的 GJR/RGL 尾層用**樣本內 ~1,500 筆**殘差（含 COVID），HAR 尾層只有 **≤450 筆平靜期**殘差。用配對池重做（GJRf+CF），GJR 也 fail（11/450, Kupiec p = 0.009）。

三者都不是「中心預測力與尾部覆蓋正交」的證據，而是**目標與建構沒對齊**的證據。

**建議路線**（與深審 §5.4 的 No-Go 分支一致）：

- 改寫成 **8–12 頁方法論短文**投 **FRL / Journal of Forecasting**：《The violation-implied scale factor: diagnosing why good volatility forecasts make bad VaR》。賣點是**可辨識的通道分解診斷**（§5.3）+ **RV-plug-in VaR 的 target-mismatch 陷阱系統化處理** — 這是現有文獻（González-Rivera 2004；Bams 2017 只報告「fail」不診斷成因）沒給的東西。
- **不要**用本實驗宣稱「HAR-RV 不如 GARCH」。本實驗的 HAR 用的是**別的標的**（TX/TAIEX）的 RV 去打 0050 — 對齊目標後的「打平」是關於 **cross-asset RV plug-in** 的結論，**不是**關於 HAR-RV 本身。要談 HAR-RV，必須做 **E2（SPY 用自身 RV，n ≥ 2,500）**。
- K850/K854 的 knowledge entry 需**回溯更正**：headline「QLIKE 大勝但 VaR 失敗」在對齊目標下不成立。

---

## 9. 限制（誠實揭露）

1. **n = 450 < 專案 ≥500 硬規則。** 1% 下期望違規僅 4.5 次 → Kupiec 檢定力弱，**單一違規就能翻動 trinity**（Basel 綠燈在 1% 需最近 250 天 ≤4 次）。所有違規率都附精確 Clopper-Pearson 區間；implied-c 的 95% 區間相應很寬（1% 的 HAR+CF：[1.16, 1.49]）。**本實驗的裁決主要靠腿 1（DM，n = 436），不靠腿 2 的 trinity 邊界。**
2. **單一市場、單一平靜期間**（2023–2024，無空頭）。尺度通道的外部效度未測 → E2/E5 仍為必要。
3. **5% 的 Basel 燈號是自訂 α-scaled 延伸**（綠 ≤20、黃 ≤45），**不是** canonical Basel（Basel traffic light 只定義在 1%、250 天）。1% 用的是標準 250 天計數規則（綠 ≤4 / 黃 5–9 / 紅 ≥10），套在 450 天 OOS 的**最後 250 天**。
4. **報酬用 simple pct_change（股利調整後收盤），RV 用 log return** — 日頻下差異是二階項，但不為零。
5. **GJR 的 MLE basin 脆弱性（§7）** 使 GJR 錨點本身帶有 ±1 違規的不確定性。
6. `sens_burnin_tailpool` 顯示**殘差池窗口是第三個通道**（它自己就會移動未校正的 baseline）。本實驗只把它當診斷報告，未做完整的通道分解 — 若走短文，這需要一節正式處理。

---

## 10. 資料來源（Data provenance）

| 來源 | 內容 | Snapshot |
|---|---|---|
| TAIFEX TX1 tick（`~/Dropbox/TAIFEXDATA/`） | 2,192 個交易日，5-min RV（日盤 + 夜盤） | `data/tx_rv_5min_daily_2017_2025.csv` |
| yfinance `0050.TW` | 調整後收盤（**`auto_adjust=True`**） | `data/tw0050_adjclose_2016_2025.csv` |

**為什麼 `auto_adjust=True`（與專案偏好的 `auto_adjust=False` 不同）**：為了精確複製 K854 的 baseline。以 K854 published 的 OOS 動差當指紋反推 —
`auto_adjust=True` → std 0.0127988900、kurt 8.114553（K854: 0.0127988873 / 8.114549，**吻合到小數第 7 位**）；
`auto_adjust=False` → std 0.0129080522、kurt 7.823046（**明顯不符**）。
兩者的殘差差異（第 7 位小數）已由 §7 的 fragility probe 完整解釋。

---

## 11. 復現

```bash
uv run --extra dev python experiments/k1684/k1684_ftd_e1_scale_gating.py
```

首跑會從 tick 檔建 RV 並 pin 成 snapshot（約 90 秒）；之後每跑約 **20 秒**。
Seed = `20260712`（GJR multistart、擾動 audit、fragility probe 全部固定）。
Lookahead audit 失敗時腳本 `raise`，**不會**輸出結果。

**圖**：
- `fig1_implied_c_by_alpha.png` — implied-c 跨 α 對照（區分尺度 vs 尾形通道）+ Δc 判別器
- `fig2_trinity_before_after.png` — 校正前後 trinity 對照（Basel 燈號 + trinity 斜線標記）
- `fig3_scale_factors.png` — 三個校正因子 + placebo
