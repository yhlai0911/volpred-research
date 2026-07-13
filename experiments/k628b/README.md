# K628b: Cross-Asset Volatility Spillover Network

**資產**：SPY / GLD / TLT / 0050.TW / USO　**期間**：2010-01-01 → 2026-03-27（4,211 日報酬）
**資料**：yfinance 日收（auto_adjust），快取於 `data/prices.csv`

---

## ⚠️ 2026-07-13 更正：方向性結論的量級是排序假象

原始腳本的 `compute_spillover_index` **docstring 寫「generalized FEVD (Pesaran & Shin, 1998)」，
底下卻呼叫 `results.fevd(h)`**。statsmodels **沒有**內建 generalized FEVD — `.fevd()` 是
**Cholesky 正交化分解**，方向性輸出**依賴變數排列順序**。

而本實驗把 **SPY 排在第一位** — 正是機械性讓一個變數看起來最外生、NET 最大的位置 —
然後宣告 SPY 是主要傳導者（+43.7%）。

**把五個資產的 120 種排序全部枚舉**（5! = 120，不抽樣）後：

| | SPY 的 Cholesky NET |
|---|---|
| 全 120 種排序的範圍 | **−16.09pp 到 +43.71pp** |
| K628b 用的排序（SPY 第一）| **+43.68pp ← 幾乎就是最大值** |
| SPY 排最後 | −15.94pp |
| SPY 在多少排序中是最大傳出者 | **僅 33%** |
| Spearman(SPY 的排序位置, SPY 的 NET) | **−0.882**（p = 2.5e-40）|

換句話說：**原實驗取到的正是 120 種排序裡讓 SPY 最像傳導者的那一種。**

真正的 KPPS GFEVD（order-invariant，全 120 種排序下數值偏差 < 1.0e-12）重估結果：

| 資產 | Cholesky NET（原報） | **KPPS GFEVD NET** | 角色變化 |
|---|---|---|---|
| SPY | +43.68pp | **+14.58pp** | TRANSMITTER → TRANSMITTER（量級剩 1/3）|
| TLT | −24.92pp | **−9.12pp** | RECEIVER → RECEIVER（量級剩 1/3）|
| USO | −12.37pp | **+0.98pp** | **RECEIVER → BALANCED（符號翻轉）** |
| GLD | −4.65pp | **−3.69pp** | BALANCED → BALANCED |
| 0050.TW | −1.75pp | **−2.75pp** | BALANCED → BALANCED |
| Total spillover index | 11.63% | **17.50%** | — |

---

## 裁決：部分翻盤（PARTIALLY OVERTURNED）

### 倖存（可繼續引用）

1. **SPY 是最大淨傳出者** — GFEVD 下 +14.58pp，五個資產中最大。且**通過無傳染 null 檢定**：
   模擬 200 次「五個資產各走各的 AR(p)、真實傳染為零」，null 的 |NET| 最大只到 1.02pp，
   實測 +14.58pp 的 two-sided empirical p = 0.000。方向是真的。
2. **TLT 是最大淨接收者**（−9.12pp，flight-to-quality 方向性成立）。
3. **0050.TW 不是主要節點**（GFEVD −2.75pp；Cholesky 下在 120 種排序中 NET 全距只有 0.32pp，
   是全場最穩定的一個）。
4. **Granger 因果網路與 TRANSMITTER / RECEIVER 角色標籤 — 完整存活**。
   這些來自 **out-in degree**，每條連結是 `effect ~ own lags + cause lags` 的**雙變量迴歸**，
   不經 VAR 排序、不經 Cholesky 分解、不經任何共變異矩陣分解 → **結構上免疫於排序問題**。
   本次逐項重跑：13 條顯著連結、五個資產的 OUT/IN/role **全部與原值相符（ALL MATCH）**。

   | | OUT | IN | NET | 角色 |
   |---|---|---|---|---|
   | SPY | 4 | 3 | +1 | TRANSMITTER |
   | TLT | 4 | 2 | +2 | TRANSMITTER |
   | USO | 3 | 3 | 0 | BALANCED |
   | GLD | 2 | 3 | −1 | RECEIVER |
   | 0050.TW | **0** | 2 | −2 | RECEIVER（純接收者）|

   **角色標籤還扛過了多重檢定校正**（Codex review 提出）。K628b 對 20 個配對各取 5 個 lag 的
   **最小 p 值**、且未做校正 = 100 次檢定。補做 Bonferroni：

   | 校正 | 顯著連結數 | SPY | GLD | TLT | 0050.TW | USO |
   |---|---|---|---|---|---|---|
   | 未校正（K628b）| 13 | T | R | T | R | B |
   | Bonferroni ×5（lag）| 11 | T | R | T | R | B |
   | Bonferroni ×100（全部）| 8 | T | R | T | R | B |

   → **角色標籤三種校正下完全相同**（存活）。但**連結「數量」不是** —
   「13 條顯著連結」與「高波動 regime 網絡密度翻倍（11 vs 4）」都是**未校正**的數字，
   **不可當成已校正的結果引用**。

5. **Forbes-Rigobon 無傳染結論**（相關係數法，不經 VAR）、**滾動相關危機 vs 平靜**、
   **OOS spillover-informed 組合 NULL**（由 rolling Granger F-stat 驅動，不經 FEVD）— 全數不受影響。

### 翻盤（必須撤回）

1. **所有 FEVD 方向性的「量級」**。+43.7% 這個數字及一切建立在它上面的敘述作廢。
2. **「SPY 傳出量（48.28%）是接收量（4.60%）的 10 倍以上」** — 完全是排序產物
   （SPY 排第一 → 接收量被壓到最低）。GFEVD 下是 40.1% vs 25.5%，約 **1.6 倍**。
3. **「USO 是淨接收者」** — 符號翻轉，改為 BALANCED。這是唯一角色標籤真的翻掉的資產。
4. **「SPY 的 net +43.68% 遠高於其他四個加總」** — 這句話**兩重錯誤**：
   (a) 43.68 是排序假象；(b) **NET 依定義加總為零**（每一單位傳出必是另一資產的傳入），
   所以只要 SPY 是**唯一**淨傳出者，「高於其他四個加總」就是**恆等式**，
   在任何分解下都不構成證據。更正時**不可用新數字重寫成同樣句型**。
5. **Total spillover 均值 25.8%（9.5%–51.6%）** — 那是 Cholesky TSI。GFEVD 下 rolling 均值
   **29.79%（9.91%–54.19%）**。兩者時序高度同步（Spearman 0.917），但見下方警告。

### TSI 的「水準」不可單獨解讀

跑「五個資產完全獨立、真實傳染為零」的對照組（獨立 AR(p)，seed 42，200 次）：

| | 無傳染 null 的 TSI 中位數 | 實測 TSI | empirical p |
|---|---|---|---|
| 全樣本（n=4,190, lag=5）| **0.43%** | 17.50% | 0.000 |
| 滾動視窗（n=200, lag=3）| **12.40%** | 29.79%（均值）| 0.000 |

全樣本沒問題。但 **200 日滾動視窗光靠估計噪音就能生出 12.4% 的 TSI** —
所以「滾動 TSI 均值 29.8%」裡有將近一半是有限樣本偏誤，**絕對水準不可當成連動強度**，
只有「超出 null 的部分」與「時序變化」站得住。

---

## Code review

**Codex（gpt-5.6-sol, ultra）primary-path review，2026-07-13 → VERDICT = PASS**。逐項確認：
KPPS 公式合乎 Pesaran-Shin (1998)（分子分母軸向、`sigma_jj` 除在 column、h=0..H-1）、
Diebold-Yilmaz 的 from/to 方向沒顛倒、排序的逆映射正確、AR null 的 `phi[0]` 與 `[::-1]` 對齊、
無 lookahead、Granger 確實不經 FEVD。

Codex 另提三個**寫作 caveat**（已納入本 README 與 results JSON 的 `caveats`）：

1. **這是回顧式的樣本內網路描述，不是即時訊號**。log-vs-level 的決策與 null 的 AR 校準
   都用了全樣本 — **不可包裝成可交易 / 即時可得的訊號**。
2. **Granger 角色免疫於 FEVD 排序 ≠ 結構因果**。它仍是雙變量預測關係，
   一樣受共同因子、遺漏變數、lag/spec 選擇影響。
3. **多重檢定**（見上表）。

## 檔案

| 檔案 | 說明 |
|---|---|
| `k628b_vol_spillover.py` | 原始實驗。**已修正**：改用手刻 KPPS GFEVD；Cholesky 降級為具名的 order-dependent 診斷（`cholesky_diagnostic_ORDER_DEPENDENT`）|
| `k628b_results.json` | 現行結果（**已是 GFEVD 數字**），含 `_correction_2026_07_13` 區塊 |
| `k628b_results_SUPERSEDED_cholesky_ordering.json` | **更正前的原始輸出，逐字保留**，供歷史對照，不可再引用 |
| `k628b_kpps_rerun.py` | 更正實驗：120 排序全枚舉 + GFEVD 重估 + 無傳染 null + 下游更正清單 |
| `k628b_kpps_rerun_results.json` | 上述結果（含 `corrections_required`）|
| `k628b_kpps_rerun_net_comparison.png` | Cholesky vs GFEVD 的 NET 對照 |
| `k628b_kpps_rerun_ordering_distribution.png` | SPY NET 在 120 種排序下的分佈 |
| `k628b_kpps_rerun_rolling_tsi.png` | 滾動 TSI vs 無傳染 null floor |

## 防錯設計（可驗證，非宣稱）

- **Cholesky 臂重現原數字**：max |diff| = **0.001pp**（16 個量）→ 差異可歸因於**估計子**，
  不是資料版本或 pipeline 差異。這是整個比較成立的前提。
- **軸序 bug 排除**：K865 的 `decomp[-1]`（取到最後一個**變數**）在此**不存在**。
  `check_axis_equivalence()` 逐元素驗證 K628b 的 `decomp[i][-1]` ≡ `decomp[:, -1, :]`，
  最大偏差 **0.0**。缺陷是標籤與估計子，不是索引。
- **GFEVD 排序不變性 — 數值驗證而非引用**：全 120 種排序下 NET 最大偏差 **1.02e-12**。
- **AIC lag 在 120 種排序下恆為 5** → NET 的離散**純粹來自排序**，不是 lag 選擇的副作用。
- **無 try/except 包住估計迴圈**：靜默跳過的 fit 正好是 VAR 最不穩的那些，會美化估計子。
- **固定 seed 42**（null 模擬）；排序是**全枚舉**，不涉抽樣。
- **無 lookahead**：本實驗是樣本內網路描述，非預測。滾動視窗只用該視窗資料，
  並戳記在該視窗的**最後一個觀測日**。

## 下游更正清單

完整清單在 `k628b_kpps_rerun_results.json` 的 `corrections_required`。摘要：

- **`storage/memory/knowledge.json` K628b**（**主線程寫入**，本 agent 只提供 diff 提案 — K1259 規則）：
  標題「SPY dominant transmitter」需改；`net +43.7%` 撤回改 `+14.6pp`；
  `0050.TW 純接收者 (OUT=0, IN=2)`、Granger 網絡密度、Forbes-Rigobon、組合 NULL **全部保留**。
- **`mile_55758994`**（archived，但 live 導讀 `mile_1597b341` 的「本期精選」仍連過去）：
  **HIGH** — 整個「結果一」表格與其解讀建立在排序假象上。需更正或從導讀移除連結。
- **`mile_1597b341`**（**published / LIVE**）：**LOW-MEDIUM** — 該文引用 K628b 的正文段落（第二層）
  只用 Granger + Forbes-Rigobon，**兩者都不受影響，論述本身站得住**。需要動的是
  (a) 文首更正聲明補一句、(b) 處理指向 `mile_55758994` 的連結。
- **`mile_530a28bc`**（unpublished）：發佈前若引用 FEVD 方向性數字需換成 GFEVD 版本。

## Ratchet

`storage/ops/fevd_ordering_baseline.json` 已移除 `experiments/k628b/k628b_vol_spillover.py`
（偵測器 `scripts/audit_fevd_ordering.py` 現判為 `OK_GFEVD`；
`scripts/tests/test_fevd_ordering_ratchet.py` 23 passed）。
偵測器規則是**「不信註解，只信呼叫」** — 只改 docstring 不會過，必須真的手刻 KPPS。

## 參考文獻

- Pesaran, H.H. & Shin, Y. (1998). "Generalized Impulse Response Analysis in Linear Multivariate Models." *Economics Letters* 58(1), 17–29.
- Koop, G., Pesaran, M.H. & Potter, S.M. (1996). "Impulse Response Analysis in Nonlinear Multivariate Models." *Journal of Econometrics* 74(1), 119–147.
- Diebold, F.X. & Yilmaz, K. (2012). "Better to Give than to Receive." *IJF* 28(1), 57–66.
- Forbes, K. & Rigobon, R. (2002). "No Contagion, Only Interdependence." *Journal of Finance* 57(5), 2223–2261.
- 同缺陷 class：`experiments/k865b/`（K865 的 SPY-hub 敘事亦為排序假象）
