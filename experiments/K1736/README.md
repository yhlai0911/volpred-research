# K1736 — 偏度風險溢酬「期限結構」作長 horizon 尾部訊號

- Experiment ID: `K1736`
- Status: complete
- Verdict: **NULL_DEGENERATE** — 兩層失敗：(1) 免費資料建不出真正的 risk-neutral skew 期限結構，
  可建的最佳代理與 SKEW **level 相關 −0.93 ~ −0.94**（退化）；(2) 即使照樣檢定，6–12 個月 horizon
  上全部 slope cell 的 |t| ≤ 1.12、incremental |t| ≤ 2.15、OOS R² 全負。
- Created: 2026-07-30
- Model/effort: opus / xhigh (per model_router)
- 來源：`research_program.md` 期刊主題挖掘 batch（JFQA 2025 crash-risk premium / skewness swap 線）

---

## 1. 一句話結論

**在免費資料可及的範圍內，「skew premium 期限結構」既建不出來、也預測不了 6–12 個月的 SPY 報酬或
回撤。** 64 個 cell 做完全域 Holm 校正後只剩 2 個存活，而那 2 個是**完全不含偏度資訊的隱含變異數
期限結構**（`vts_3m` / `vts_6m`）在**1 個月**回撤上的效果 —— horizon 和訊號都跟本題假設相反。

---

## 2. 動機與差異化（這是本題唯一存在理由）

CBOE SKEW 這條線在本專案已被打過 7 次，全部 NULL：

| K | 內容 | 結論 |
|---|---|---|
| K181 / K184 | CBOE SKEW 作波動率預測 | NULL |
| K210 | VIX-SKEW ratio | NULL |
| K258 | SKEW dynamics | NULL |
| K447 | SKEW tail risk | NULL（子期間不穩） |
| K535 | SKEW 進 HAR 框架 | NULL（VIX sufficiency） |
| K979 | CBOE SKEW vs VIX | NULL（SKEW 無增量） |
| K43 | SKEW / VIX3M **level** | 已做 |

上述 7 個打的都是同一格：**level × 短 horizon（次日/次月 RV）**。本題刻意換到對角格：
**term-structure slope × 長 horizon（6–12 個月報酬 / 回撤）**，文獻依據為 JFQA 2025 一線的
crash-risk premium / skewness swap 結果（skew premium 在長 horizon 較強）。

差異化因此是**可證偽的**，本實驗把它拆成兩個明確的檢定，兩個都在 results JSON 裡程式化產出：

- **D1 — slope 是否帶有 level 沒有的資訊？** 用 `corr(slope, level)` 與「控制 level 後 slope 的
  incremental t」兩個獨立證據。
- **D2 — 長 horizon 是否真的比短 horizon 強？** 比較同一訊號 × 同一 target 在 H=21 與 H=252 的 |t|。

**D1 與 D2 都失敗。** 詳見 §7。

---

## 3. 本題最大的風險先講：期限結構到底建不建得出來

`^SKEW` 是 **30 天** risk-neutral skewness 指標。CBOE **沒有**免費的 SKEW3M / SKEW6M，
yfinance 也**沒有歷史期權鏈**（只有當下快照）。因此：

> **一個「被觀測到的」risk-neutral skew 期限結構，用本專案可及的免費資料建不出來。**

這寫在 `K1736_results.json` 的
`data_diagnostics.risk_neutral_skew_term_structure_available = false`。

下面三種建構法都是代理，各自的 horizon 變異來自哪裡都標清楚了：

### 建構 (a) — realized skewness 期限結構（brief 選項 a）

`premium_h = ζ₃₀ − RS_h`，slope = `premium₂₅₂ − premium₂₁`。

**代數上這個 slope 完全不含期權資訊**：

```
(ζ₃₀ − RS₂₅₂) − (ζ₃₀ − RS₂₁) = RS₂₁ − RS₂₅₂
```

共同的 30 天 risk-neutral leg **恆等地消掉**。實測 `corr(ts_realized, RS₂₁) = 0.973` —— 它實質上
就是「近月已實現偏度」，叫它 skew-premium slope 是名不副實。這條在 README 與 results 都標為
`slope_physical_only`。

### 建構 (b) — 用 VIX 期限結構作 conditioning

保留為**控制組**（`vts_3m = log(VIX3M/VIX)`、`vts_6m = log(VIX6M/VIX)`），因為它是純變異數物件、
**完全不含偏度**。它的角色是：任何 skew slope 若有預測力，必須證明那不是變異數期限結構的影子。

### 建構 (c) — 用可觀測的隱含變異數期限結構外推 RN skewness（本題主建構）

在「三階累積量對 T 線性」（constant jump intensity / Lévy 型）假設下：

```
κ₃(T) = (T/30)·κ₃(30)                     三階累積量對 T 線性
κ₂(T) = VIX_T² · T/365                    可觀測
ζ(T)  = κ₃(T)/κ₂(T)^{3/2} = ζ₃₀ · √(30/T) · (VIX/VIX_T)³
```

期限結構平坦時退化成純 iid 的 `√(30/T)` scaling；**所有超出 iid 的 horizon 資訊都來自可觀測的
`VIX/VIX_T` 比值**。這是本題能做到最誠實的建構，但它是**假設**不是**量測** —— 見 §9。

**這是一個假設驅動的代理，不是觀測到的 skew 期限結構。** 論文若要真正回答這題，需要
OptionMetrics / 完整歷史期權鏈算多到期日的 model-free RN skewness。

---

## 4. 資料

全部 yfinance 日收盤，一次抓取後凍結在 `data/*.csv`，分析端只讀 CSV
（`float_precision='round_trip'`，K1386 跨平台 1-ULP hash 漂移教訓）。

| 角色 | 序列 | Ticker | 期間 | N | 期間內缺值率 |
|---|---|---|---|---|---|
| 30d RN skewness | CBOE SKEW | `^SKEW` | 1990-01-02 .. 2026-07-28 | 9,135 | 0.878% |
| 30d 隱含波動 | VIX | `^VIX` | 1990-01-02 .. 2026-07-29 | 9,211 | 0.000% |
| 93d 隱含波動 | VIX3M | `^VIX3M` | 2006-07-17 .. 2026-07-29 | 5,033 | 0.139% |
| 180d 隱含波動 | VIX6M | `^VIX6M` | 2008-01-02 .. 2026-07-29 | 4,665 | 0.150% |
| 標的（主） | SPY adj close（含息） | `SPY` | 1993-01-29 .. 2026-07-29 | 8,431 | 0.000% |
| 標的（備） | S&P 500 價格指數 | `^GSPC` | 1985-01-02 .. 2026-07-29 | 10,473 | 0.000% |

- 缺值率 = 該序列**自身跨度內**、SPY 有交易但該序列沒有報價的比例（交易日基準 = SPY 的 NYSE session）。
- **抓取日 2026-07-30**；`^SKEW` 的最後報價 2026-07-28，`^VIX3M`/`^VIX6M` 在 2026-07-17→07-29 有一段
  12 天缺口。這對結果沒有影響：最長 target 需要 252 個交易日的未來價格，最後一個可用的訊號日約在 2025 年中。
- 三個 joint 樣本（記在 `data_diagnostics.joint_samples`）：
  - `long`（SKEW+SPY）：1993-02-01 .. 2026-06-29，n=8,409
  - `mid`（+VIX3M）：2006-07-18 .. 2026-06-29，n=5,018
  - `short`（+VIX6M）：2008-01-03 .. 2026-06-29，n=4,650

---

## 5. 方法

### 5.1 Lookahead policy（最高風險，機械檢查）

- **每一個 regressor 都是 `signals[sig].shift(1)`**：用 t−1 收盤觀測到的值，預測**從 t 收盤才開始**
  的 target 窗口。資訊集與 target 窗口之間隔了完整一個交易日（比 repo 的「收盤可交易」慣例更保守）。
- Forward target 一律**戳在 origin 日 t**，讀 t..t+H 的價格，所以任何 target 都不可能早於它的 regressor 被讀到。
- OOS 迴圈額外強制 `j + H <= i`（訓練列 j 的 label 窗口必須在預測原點 i 之前關閉）。
- **這不只是散文宣稱**：腳本內含 `lookahead_audit`，隨機抽 200 列驗
  `lagged[t] == raw[t−1]`、抽 100 列獨立重算 `fwd_ret_252` 與 `fwd_mdd_252`，任一不過就 `raise`。
  results JSON 的 `methodology.lookahead_audit.all_passed = true`。

### 5.2 重疊觀測（本題頭號統計陷阱）

日頻滾動的 H 日 target 嚴重重疊，OLS t 會大幅高估顯著性。每個 cell 同時報四種處理：

1. **Newey–West HAC**，`lag = max(H, ceil(H^{1/3}·n^{1/3}))` —— repo canonical bandwidth
   **以重疊長度為下限**。禁用 `h−1`（`.claude/rules/experiments.md`；h=1 時會退化成完全不做 HAC）。
   另報 **1.5H / 2H** 的 lag sensitivity。
2. **Hodrick (1992) 1B standard errors**：不把 LHS 加總（重疊的來源），改把 RHS regressor 加總，
   並 impose 無預測力的虛無，使一期殘差 = 去均值的一期報酬。
   **僅適用於「一期報酬之和」型 target**；forward max drawdown 是 path functional 不是這種和，
   因此 `fwd_mdd` 的 cell **刻意不報** Hodrick（results 中為 `null`）。
3. **非重疊子樣本**：每個 horizon 的全部 H 個 phase offset 都跑一遍，報 t 的 mean/median/min/max
   與 |t|>3 的比例。
4. **Effective sample size** = `樣本年數 / (H/252)`，**逐 cell 記錄**。

> **關鍵數字：12 個月 horizon 的獨立觀測數。** H=252 的迴歸樣本會被 forward window 吃掉最後
> 252 天，實際是：長樣本 1993-02-01..2025-07-28（32.5 年）→ **32.5 個**獨立 12 個月期間；
> `rn_slope_3m` 樣本（2006-07-18 起）→ **19.0 個**；需要 VIX6M 的 `rn_slope_6m` /
> `srp_slope_6m`（2008-01-03 起）→ **17.6 個**；OOS 段更只剩 **13 個**。
> 這是本題的硬上限 —— 任何在這個 horizon 上的「顯著」都必須用這個數字來讀。
> 逐 cell 的值在 `univariate_cells[*].effective_sample_size`。

### 5.3 多重檢定

搜尋空間 = 8 訊號 × 2 target × 4 horizon = **64 cells**，必須校正。

- **Romano–Wolf stepdown**（primary），circular block bootstrap、block length = 252（家族內最長
  horizon）、B=2000、seed=42。studentise 用原樣本的 HAC se 同時除觀測統計量與 bootstrap 統計量。
  家族按**資料可得期間**切成 3 組（A_long / C_mid / B_short），使 bootstrap 能在家族內重抽**同一組**
  row index —— 跨不同樣本期的 cell 無法共用一次重抽。
- **Holm**：家族內 + **全 64 cell 全域**（最保守的一層）。
- **unadjusted 與 adjusted 一律並列**，每個 cell 都有 `p_hac` / `p_romano_wolf` /
  `p_holm_within_family` / `p_holm_global`。

⚠️ **Bootstrap 的誠實限制**：block=252、n≈4,650 → 每個 replicate 只有 **19 個 block**。這不是實作
偷懶，是資料本身的天花板（18 年只有 18 個獨立年度窗口）。bootstrap 造不出樣本裡沒有的獨立性，
`n_blocks_per_replicate` 逐家族記在 results 裡。

### 5.4 樣本外

expanding window，每 21 個交易日一個 origin，最少 1,000 列訓練；predictive regression vs
**expanding historical mean**（nested）。用 repo canonical `clark_west_test`，
`h = ceil(H/STEP)`（連續 origin 相隔 21 天而 target 跨 H 天 → 誤差重疊 ceil(H/21) 個 origin，
**不是 1**），HAC lag 同樣以重疊長度為下限。另報 Campbell–Thompson OOS R²。

OOS grid 含 `fwd_mdd @ H=21` —— 那是唯一有 in-sample 存活者的格子。**一個從沒被拿去做樣本外
檢定的 in-sample 存活者，本 repo 不接受。**

### 5.5 子期間

4 段：1993–2002（網路泡沫）、2003–2012（**含 2008**）、2013–2019、2020–2026（**含 2020**）。
建構 (c) 因 VIX6M/VIX3M 起始只有後 3 段可估。

### 5.6 POSITIVE 的判定門檻（joint gate）

裁決不是「有某個 cell 過 IS」+「有某個 cell 過 OOS」+「有某個 cell 過 incremental」。
**POSITIVE 要求同一個 (signal, target, horizon) 三元組同時**：

1. in-sample 通過 Romano–Wolf（且 return target 還要通過 Hodrick）；
2. 該 cell 的 OOS R² > 0 **且** Clark–West 單尾 p < 0.05；
3. 該 cell 控制 level 與到期日相符的 vts 後 |incremental t| > 3。

缺任何一腳（包含「該 cell 根本沒跑 OOS」）一律 **fail closed**。
在 64 格搜尋空間裡讓三個不同 cell 各出一條腿，正是製造假發現的標準做法。
本實驗的 `verdict_block.n_joint_survivors = 0`。

### 5.7 對稱性

`rn_slope_3m` 對 `vts_3m`、`rn_slope_6m` / `srp_slope_6m` 對 `vts_6m` —— **每個 slope 都配到期日
相符的變異數期限結構控制變數**。若只給 6M slope 控制、3M slope 不給，得到的差就是 asymmetric
refinement artifact 而非真效應（K1216b 教訓）。

---

## 6. 訊號清單

| 訊號 | 類型 | 定義 | 家族 |
|---|---|---|---|
| `skew_level` | level | `ζ₃₀ = (100 − SKEW)/10` | A_long |
| `srp_30d` | level | `ζ₃₀ − RS₂₁` | A_long |
| `ts_realized` | slope（純物理） | `RS₂₁ − RS₂₅₂`（RN leg 已消掉） | A_long |
| `rn_slope_3m` | slope（模型外推） | `ζ₉₃ − ζ₃₀` | C_mid |
| `rn_slope_6m` | slope（模型外推） | `ζ₁₈₀ − ζ₃₀` | B_short |
| `srp_slope_6m` | slope（模型外推） | `(ζ₁₈₀ − RS₁₂₆) − (ζ₃₀ − RS₂₁)` | B_short |
| `vts_3m` | **控制**（無偏度） | `log(VIX3M/VIX)` | C_mid |
| `vts_6m` | **控制**（無偏度） | `log(VIX6M/VIX)` | B_short |

`RS_h` = 過去 h 個交易日日報酬的樣本偏度 ÷ √h（iid 下 h 日累積報酬的偏度）。用**視窗相依**的樣本，
而不是單一日偏度乘 1/√h —— 後者是一個數字的確定性變換，根本構不成期限結構。

Target：`fwd_ret_H = log(P_{t+H}/P_t)`、`fwd_mdd_H` = 路徑 P_t..P_{t+H} 的最大回撤（正值），
H ∈ {21, 63, 126, 252}。

> `fwd_mdd` 是**被解釋變數**（單一價格路徑的統計量），不是兩條不同曝險策略的風險比較，
> 所以 exposure-matching 那條規則不適用於此處；程式裡也只有單一 drawdown 綁定、無 benchmark 差分。

---

## 7. 結果

### 7.1 D1 — slope 根本就是 level（退化）

| 訊號 | corr(level) | R²（被 level 解釋） | 退化？ |
|---|---|---|---|
| `rn_slope_6m` | **−0.944** | 0.891 | ✅ 是 |
| `srp_slope_6m` | **−0.933** | 0.870 | ✅ 是 |
| `rn_slope_3m` | **−0.927** | 0.858 | ✅ 是 |
| `ts_realized` | +0.096 | 0.009 | 否（但它 corr(RS₂₁)=0.973，是另一種退化） |

建構 (c) 的三個 slope 有 **86–89% 的變異被 SKEW level 解釋**。這正是 brief 預先警告的情況，
如實標記為退化。純 iid 版本（`ζ₃₀·(√(30/T) − 1)`）更是**解析上 |corr| = 1**，
記在 `degeneracy_diagnostics.analytic_note_iid_only_slope`。

控制 level（與到期日相符的 vts）之後的 incremental t，16 個長 horizon 檢定**沒有一個** |t| > 3，
最大只有 **2.15**。VIF 高達 **28–50**，共線性嚴重到即使有訊號也測不出來 —— 這本身就是
「這個建構沒有獨立的期限結構維度」的證據。

**D1 verdict：`FAIL_degenerate`。**

### 7.2 D2 — |t| 隨 horizon 遞減，方向與假設相反

`fwd_mdd` 上（`|t|` HAC）：

| 訊號 | H=21 | H=63 | H=126 | H=252 |
|---|---|---|---|---|
| `rn_slope_3m` | **3.03** | 1.63 | 1.09 | 0.99 |
| `rn_slope_6m` | **3.07** | 1.68 | 1.10 | 0.86 |
| `srp_slope_6m` | **3.12** | 1.71 | 1.12 | 0.91 |

`fwd_ret` 上全部 horizon 的 |t| ≤ 0.39。文獻主張的「長端更強」在資料上是**單調反向**的。

**D2 verdict：`MIXED_OR_FAIL`**（8 個 case 只有 3 個滿足 |t|₂₅₂ > |t|₂₁，而那 3 個的 |t| 全部 < 0.8，
是雜訊間的比大小）。

### 7.3 6–12 個月 horizon（本題的目標格）：完全 NULL

| 指標 | 值 |
|---|---|
| 全部 slope cell 在 H∈{126,252} 的 max \|t_HAC\| | **1.12** |
| 控制 level 後的 max \|incremental t\| | **2.15** |
| slope cell 在 H∈{126,252} 的最佳 OOS R² | **+0.0003**（16 格中唯一一個為正，CW p=0.343 不顯著） |
| 通過 Romano–Wolf 的長 horizon slope cell | **0** |
| 同時通過 IS + OOS + incremental 的 cell（joint gate） | **0** |

16 個長 horizon slope cell 的 OOS R² 有 15 個為負，唯一為正的
（`ts_realized`\|`fwd_mdd`\|126）只有 +0.0003 且 Clark–West p = 0.343。

⚠️ **Clark–West 顯著 ≠ OOS 有用**：`rn_slope_6m`\|`fwd_mdd`\|126 的 CW p = 0.015，
但它的 OOS R² 是 **−0.064**。CW 檢定的是「大模型是否有增量預測內容（已校正參數估計噪音）」，
不是「OOS MSE 是否真的變小」。本 README 一律以 **OOS R² 與 CW 並列** 呈現，不單獨引用 CW。

### 7.4 唯一存活的東西，不含偏度

64 cell 做**全域 Holm** 後只有 2 個 p < 0.05：

| cell | t_HAC | Holm(global) | 含偏度資訊？ |
|---|---|---|---|
| `vts_6m` \| fwd_mdd \| H=21 | −4.43 | **0.00064** | ❌ 純變異數期限結構 |
| `vts_3m` \| fwd_mdd \| H=21 | −3.78 | **0.0098** | ❌ 純變異數期限結構 |

三個 skew slope 在同一格（`fwd_mdd`, H=21）雖有 |t| = 3.03–3.12、Romano–Wolf p = 0.036–0.041，
非重疊子樣本也穩（21 個 phase 全部或 90% |t| > 3，t_mean ≈ −4.2 ~ −4.5），
**但全域 Holm 後全部掉出**（p = 0.11–0.14），而且——

**把三者放進同一條迴歸就見真章**（`fwd_mdd`, H=21）：

| 迴歸式 | `skew_level` | `vts_6m` | `rn_slope_6m` |
|---|---|---|---|
| t_HAC | −0.20 | **−2.24** | −0.26 |

| 迴歸式 | `skew_level` | `vts_6m` | `srp_slope_6m` |
|---|---|---|---|
| t_HAC | −0.28 | **−3.03** | −0.38 |

**短 horizon 的預測力整個來自隱含變異數期限結構；偏度 slope 與偏度 level 加起來貢獻為零。**
樣本外也是同一結論：`vts_6m` 在 fwd_mdd@21 拿到 OOS R² = **+0.111**，
而 `rn_slope_6m` 的 +0.114 與它幾乎相同 —— 因為它 89% 就是同一條線的影子。
單獨的 `skew_level` 只有 **+0.002**。

至於這個短 horizon 效果本身：VIX 期限結構倒掛 → 近月波動高 → 未來一個月回撤深，
這是**已知的波動群聚現象，不是本實驗的發現**，本 README 不對它作任何新宣稱。

**長 horizon 上唯一為正的 OOS 也屬於控制組**：`vts_6m`\|`fwd_mdd`\|126 拿到 OOS R² = **+0.070**
（CW p = 0.005），`vts_3m`\|`fwd_mdd`\|252 拿到 **+0.039**（CW p = 0.024）。兩者 in-sample 都沒通過
Romano–Wolf，且獨立觀測分別只有 27 與 14 個，**本實驗不對它們作任何宣稱**；只記錄一句：
若日後要追這條線，該追的是**變異數**期限結構，不是偏度。

### 7.5 子期間穩定性：K447 的失敗模式重演

16 個 headline cell（slope × {fwd_ret, fwd_mdd} × {126, 252}）：

- **15/16 出現 beta 符號翻轉**
- **0/16 有任何一個子期間 |t| > 3**
- 例（`rn_slope_6m` | fwd_mdd | 252）：2003–2012 t = −2.20，2013–2019 t = −0.52，2020–2026 t = **+2.06**

同一個訊號在 GFC 期與 COVID 後**符號相反且量級相當**。K447 當年就是敗在子期間不穩，本題同樣。

---

## 8. 結論

1. **主假設（長端 skew premium 對 6–12 個月報酬/回撤有比短端更強的預測力）不成立**，在免費資料
   可及的三種建構下都不成立。全部長 horizon 證據：max |t| = 1.12、max incremental |t| = 2.15、
   16 個 slope cell 的 OOS R² 有 15 個為負（唯一為正者 +0.0003 且不顯著）、子期間 15/16 符號翻轉、
   joint gate（同一 cell 同時過 IS+OOS+incremental）通過數 = 0。
2. **而且這個假設在這裡沒有被公平地檢定過** —— 因為建不出真正的 risk-neutral skew 期限結構。
   最好的代理有 86–89% 是 SKEW level 的重述。**本結果不足以否證文獻的原始主張**；它否證的是
   「用 ^SKEW + ^VIX 系列的免費資料能捕捉到那個主張」。
3. **第 8 個 SKEW NULL，但這次的失敗點不同**：前 7 個是「SKEW 沒有增量資訊」，本題是
   「免費資料建不出期限結構這個維度」。這是 **data-limitation NULL**，不是 signal-is-useless NULL，
   兩者的後續行動不同（見 §10）。
4. **VIX sufficiency（knowledge #34）在這條線上再次被證實**，而且形式更強：不只 SKEW level 沒有
   增量，連從 SKEW 外推出來的期限結構在控制隱含變異數期限結構後也沒有增量。

---

## 9. 局限（必讀，決定這份結果能被怎麼引用）

1. **`ζ(T)` 是模型外推不是量測。** 建構 (c) 依賴「三階累積量對 T 線性（constant jump intensity）」。
   若真實的 jump intensity 有期限結構，這個外推就有系統性偏誤，且偏誤方向未知。
   **這是本實驗最重要的單一假設。**
2. **12 個月 horizon 的獨立觀測只有 13–32.5 個**（依樣本），這個 horizon 上的任何統計推論都很脆弱。
   本 README 的所有長 horizon 結論方向都是「找不到」，這個方向受低檢定力影響 —— **這是一個
   power-limited NULL，不是精確估計出來的零**。
3. **Romano–Wolf 的 bootstrap 每個 replicate 只有 19–34 個 block**，來自資料本身的獨立性上限。
4. **Hodrick 1B 不涵蓋 `fwd_mdd`。** 那些 cell 只有 HAC + 非重疊兩種重疊處理。
5. **只有 SPY / 美股單一市場**，未做跨市場驗證。
6. **無交易成本 / 無策略回測** —— 全篇是預測性迴歸，不宣稱任何可交易性。
7. **未使用 `^GSPC`**（已抓取備用）：主樣本用含息的 SPY adj close，因為 6–12 個月報酬迴歸應對
   總報酬而非價格指數。1990–1993 那 3 年因此未納入。

---

## 10. 審查紀錄

實驗完成後跑了一輪 **Codex primary-path**（`codex-cli 0.145.0`，`-s read-only`，
`scripts/codex_exec_bounded.sh`），聚焦四個高風險實作：Hodrick 1B、Romano–Wolf、
`zeta_at()` 代數、lookahead。**判 FAIL，兩個 blocking defect，兩個都已修**：

1. **POSITIVE gate 可以拼裝不相關的證據**（原 code）：只要求「某個 cell 過 IS」「某個 cell 過 OOS」
   「某個 incremental 過關」，三者可以不是同一格。**修**：改成 §5.6 的 joint gate，同一三元組要同時
   過三關，缺腿 fail closed；並補上 `fwd_mdd@126` 的 OOS cell 讓所有長 horizon 格都有 OOS 對照。
   *對現行結論無影響*（三腿本來就都是空的），但這段 code 正是「如果資料長成另一個樣子就會宣稱
   POSITIVE」的機器，必須是對的。
2. **Hodrick 1B 的 `w_t` 建在 `dropna()` 之後的壓縮陣列上**：`^SKEW` 有 0.878% 的 NYSE session 缺報價，
   壓縮後 `w_t = Σ_{j=0}^{H-1} Z_{t-j}` 實際上往回加了「前 H 個**有值的**列」而非「前 H 個**交易日**」，
   且 `e_{t+1}` 的對齊也跟著跑掉。**修**：`hodrick_1b()` 改吃 calendar-indexed series，
   `w_t` 用 `rolling(H, min_periods=H)` 建在完整 NYSE 日曆上；因為 SKEW 的缺口密到幾乎沒有一個
   252 日窗口是乾淨的，regressor 在**只為了 w_t 求和**時 forward-fill 上限 10 個 session
   （CBOE 當天沒發布時，最後一個發布值就是投資人手上的資訊），迴歸樣本本身完全不受影響。
   修正後每格只掉 251 列（H−1 暖身列），Hodrick t 幾乎不變（例：`skew_level`\|`fwd_ret`\|252
   由 −0.4256 → −0.4260）。**缺陷是真的，但對結論無實質影響**。

Codex 另指出原 `run_lookahead_audit()` 偏 tautological（只驗一個訊號、一個 horizon）。已擴充為
5 項檢查：8 個訊號全驗、驗組裝好的迴歸 frame、驗 OOS 訓練切點 `j + H <= i`、獨立重算
`fwd_ret_252` 與 `fwd_mdd_252`。全部 pass（`methodology.lookahead_audit`）。

Codex 確認無誤的部分：cumsum 邊界、Hodrick 的 1/T 縮放與 beta 一致性、Romano–Wolf 的降冪
stepdown / remaining-max / 單調性 / 重抽中心化 / circular block、`zeta_at()` 代數、
四條路徑（univariate / multivariate / subperiod / OOS）的 lag。

> ⚠️ 本輪是**聚焦統計實作**的有界審查，不是完整 claim-surface 認證。
> `review_verdict.json`（merge 門票）由主線程用
> `scripts/experiment_gates.py verdict-template` 產生後派完整審查填寫 —— 本 agent 刻意不寫，
> 因為未填的模板被 commit 進去會變成一份「對著沒審過的東西說話」的裁決。

### Round 2 — 收件審查（2026-07-30，主線程 hourly slot-1）

完整紀錄見 `review_round2_collection.md`。**判 PASS**，merge 門票 `review_verdict.json` 由本輪產生。

兩件事：**(i)** 主線程把 `verdict_block` 的十個計數器丟掉、只吃 64 個 univariate cells /
32 個 multivariate rows / 35 個 OOS cells 重算一次 —— **全部對上，零筆不符**；
另驗 64/64 的 `hac_lag ≥ H`、64/64 的 `t = β/SE`、64/64 的 Holm 單調性，以及
Hodrick 1B 的 scope 限制**確實只在 32 個 `fwd_ret` cell 給數字、32 個 `fwd_mdd` cell 全部留白**。
**(ii)** 另派一個獨立敵意審查 agent（預設立場：「這個 NULL 是 bug」），在凍結資料上
**重跑得到逐位元一致的科學 payload**，判 PASS_WITH_NOTES 並找出三個缺陷 —— **本班全部修完**：

1. **ISSUE-1（造假）**：`analytic_note_iid_only_slope.corr_with_skew_level = 1.0` 是寫死的、
   沒算過，**而且正負號錯了**。`skew_level` 就是 `zeta30`（L265），iid-only 斜率的乘數
   `√(30/93) − 1 = −0.432038` 是負的，所以相關係數是 **−1.0**。
   已改成**把序列建出來實測**（附 `multiplier_at_T_93` / `corr_source` / `n = 8356`），
   而不是把常數改對就算了 —— `|corr| = 1` 的退化結論不變。
2. **ISSUE-2（驗證表演）**：lookahead audit 第 3 項是恆真檢查
   （`(i − H − 1) + H > i` 化簡為 `i − 1 > i`），無條件 pass、對偵測 OOS lookahead 檢定力為 **0**。
   已改成沿 **SPY session 日曆**從最後一列訓練資料自己的日期往前走 H 個 session、
   斷言窗口在 origin 當天或之前關閉 —— 獨立於它所稽核的列運算。
   結果：`n_origins_probed = 666`、`min_gap_sessions = 1`（貼齊但不越界），仍 pass。
3. **ISSUE-3（死碼 / 註解誇大）**：L455-456 的 no-op guard 與 L440-441 誇大的 docstring，已清。

修正後全樹 diff（忽略時間戳與 runtime 環境）**只有 9 處差異，全落在上述兩個欄位群內**；
64 個 cell、32 個 multivariate rows、35 個 OOS cells、整個 `verdict_block` **逐位元不變**，
`experiment_gates.py run` 仍 PASS。

> ⚠️ **下一個碰這份實驗的人先看這行**：`K1736.py` **必須從 repo root 執行**。
> 以實驗目錄為 cwd 會在 `finalize_experiment` → `reproduce_spec.trace_file` 崩潰
> （L1469-1476 的輸入路徑相對 repo root 解析），而 `finalize_experiment`
> **在崩潰點之前就已寫出 results JSON** —— 一次失敗的執行會覆蓋 canonical result。
> Round 2 的審查 agent 就踩到了，已 `git checkout --` 還原並由主線程以 sha256 對 HEAD 驗證後才續行。

## 11. 若要重開這題，需要什麼

**不要**再用 `^SKEW` 做另一個代理。需要的是：

- **OptionMetrics / CBOE 完整歷史期權鏈**，對多個到期日各自算 model-free risk-neutral skewness
  （Bakshi–Kapadia–Madan），才有**被觀測到的**期限結構；
- 或 **skewness swap 報價**（OTC，非公開）；
- 有了真資料後，本腳本的推論機器（HAC/Hodrick/非重疊/Romano–Wolf/CW/子期間）可直接沿用，
  只要換掉 §3 的訊號建構段。

---

## 12. 復現

```bash
uv run python experiments/K1736/K1736.py          # ~13s，資料已凍結在 data/
uv run python scripts/experiment_gates.py run --path experiments/K1736
python3 scripts/check_experiment_artifacts.py check --path experiments/K1736
```

- seed：`numpy 42`（Romano–Wolf bootstrap 唯一的隨機來源，B=2000）
- `data/*.csv` 已凍結；刪掉才會重新向 yfinance 抓取（抓取日 2026-07-30）
- 產物：`K1736_results.json`（canonical）、`reproduce_spec.json`（run-time 產生）、
  `figures/K1736_slope_level_and_targets.png`、`figures/K1736_degeneracy_and_tstats.png`

### 核心數字在 results JSON 的位置

| 主張 | JSON path |
|---|---|
| 總裁決 | `verdict_block.verdict` |
| 長 horizon 三個關鍵上界 | `verdict_block.headline_long_horizon_evidence` |
| D1 退化證據 | `differentiation_from_prior_nulls.D1_slope_vs_level` |
| D2 horizon 遞減 | `differentiation_from_prior_nulls.D2_long_vs_short_horizon.abs_t_by_horizon` |
| RN 期限結構不可得 | `data_diagnostics.risk_neutral_skew_term_structure_available` |
| 每 cell 的 unadj/RW/Holm p | `univariate_cells[*].{p_hac,p_romano_wolf,p_holm_within_family,p_holm_global}` |
| Effective sample size | `univariate_cells[*].effective_sample_size` |
| Lookahead 機械檢查 | `methodology.lookahead_audit.all_passed` |
| 子期間符號翻轉 | `subperiod_stability_summary[*].sign_flips` |
| POSITIVE joint gate 通過數 | `verdict_block.n_joint_survivors`（規則在 `.positive_verdict_rule`） |
| Hodrick 日曆對齊掉列數 | `univariate_cells[*].hodrick_1b.n_rows_dropped_for_calendar_gaps` |
