# K1714：已實現共變異數 HAR → 最小變異組合的樣本外檢定

**Verdict: `LOSE`（headline spec）／整體結論為乾淨的負面結果。**
用 HAR 直接建模已實現共變異數矩陣（Cholesky 參數化），在 GMV 組合上**沒有打敗任何一個標準
共變異數估計量**；對 RiskMetrics EWMA 甚至是**顯著更差**（年化波動 9.256% vs 8.724%，
`t = +4.564`，Holm 校正後 `p = 1.51e-05`，studentized circular block bootstrap `p = 0.0005`，
且 `|t| > 3.0` 通過 Harvey (2016) 門檻）。

**四個獨立 specification 全部指向同一方向**——這不是單一設定的運氣問題：

| specification | HAR 年化波動 | 判定 | 打敗了幾個 benchmark |
|---|---|---|---|
| Cholesky, 5 日區塊（headline） | 9.256% | `LOSE`（輸 EWMA） | 0 |
| Cholesky, 10 日區塊（事前登記 robustness） | 8.811% | `TIE_NULL` | 0 |
| Cholesky, 5 日區塊 + 禁空 | 9.506% | `LOSE`（輸 EWMA） | 0 |
| Matrix-log, 5 日區塊（post-hoc 次要 spec） | 8.990% | `LOSE`（輸 EWMA） | 0 |

`results_by_block_length` 各節點的 `adjudication.benchmarks_beaten_after_holm` 全為空陣列；
彙總欄位 `headline.model_beats_no_benchmark_in_any_specification = true`。

**但共變異數估計本身是有用的**：四種估計量的 GMV 都把年化波動從等權的 **11.433%** 壓到
**8.7–9.3%**。失敗的不是「估共變異數」這件事，而是「**用 HAR 對已實現共變異數做動態建模，
在日資料能取得的 proxy 品質下，換不到 GMV 的增益**」。

---

## 一、研究問題與庫內差異化

庫內既有的波動率預測實驗幾乎全是**單變量**（k529 multi-scale HAR、K442 long memory）。
本實驗的新面向是 **realized covariance matrix → 組合構建**：不預測單一資產的波動，
而是預測整個共變異數矩陣，並用組合層的實現波動來評分。

檢驗對象：對 **SPY / QQQ / GLD / TLT** 四資產，HAR-RCov 相對三個實務標準估計量
（rolling sample、Ledoit-Wolf shrinkage、RiskMetrics EWMA）在 **GMV 組合樣本外實現波動**上的表現。

**為什麼選 (a) 跨資產類別而非 (b) 台股**：資料品質與可重現性優先。四個 ETF 的 yfinance
調整後收盤價乾淨、無停牌與除權息重建問題，且橫跨股／債／黃金，相關結構在 2004–2026 之間
有實質變化（2008 避險需求、2013 taper tantrum、2022 股債同跌），能讓「動態共變異數建模」
真的有發揮空間。台股版本應另開 K，不在本實驗混口徑。

---

## 二、資料

| 項目 | 值 |
|---|---|
| 資產 | SPY, QQQ, GLD, TLT |
| 來源 | yfinance 調整後收盤價（`auto_adjust=True`，股息再投資） |
| 全樣本 | 2004-11-19 → 2026-07-21，**5,449 個日報酬** |
| 樣本外 | 2007-12-27 → 2026-07-15，**933 次再平衡 / 4,665 個日報酬** |
| 快取 | `data/prices_raw.csv`，sha256 記於 `data_provenance.cache_sha256` |

樣本外起點由 780 個交易日（約 3 年）的 burn-in 決定，**刻意讓 2008 金融海嘯落在 OOS 之內**
（符合「OOS 必含至少一次空頭」）。OOS 另含 2011、2015–16、2018Q4、2020 COVID、2022 股債雙殺。

報酬一律用**簡單報酬**（非對數報酬）：GMV 的組合報酬是 `w'r`，只有簡單報酬讓這個等式成立，
且 `Cov(r)` 才恰好是 GMV 要最小化的那個矩陣。

---

## 三、RCov proxy 的建構，以及「HAR 的優勢是不是套套邏輯」

**這是本實驗最大的方法論風險，以下正面回答。**

### 3.1 為什麼不能用 range-based 估計

日頻資料沒有 intraday realized covariance。Parkinson / Garman-Klass 能從 OHLC 估**變異數**，
但**推不到共變異數**：range-based 共變異數需要 `Cov(x,y) = [Var(x+y) − Var(x−y)]/4`
（Brandt & Diebold 2006），而 `Var(x+y)` 要的是**投資組合本身的日內高低點**，
單資產 OHLC 給不出來。這條路是死的，不是我沒試。

### 3.2 實際用的 proxy

**非重疊 k 日區塊的日報酬外積和**（French–Schwert–Stambaugh 1987 的多變量版本）：

```
RCov_b = Σ_{t ∈ block b} r_t r_t'      區塊互不重疊
```

不做去均值：k 個觀測值去均值會損失一個 rank，而日報酬均值相對日波動可忽略。
`k = 5 > N = 4`，所以 5 個 rank-1 矩陣之和幾乎必然滿秩 → 正定。
`test_K1714.py::test_block_rcov_rejects_block_shorter_than_n_assets` 機械擋住 `k ≤ N`。

### 3.3 套套邏輯問題的直接回答：**沒有，而且是被設計掉的**

如果 proxy 用**滾動窗口**（例如 22 日 rolling），`RCov_t` 與 `RCov_{t+1}` 會共用 21/22 的日子，
「預測」它有 95% 是機械性延續——HAR 會拿到一個假的高 R²，那才是套套邏輯。

本實驗用**非重疊**區塊，正是為了拆掉這個機制：`RCov_b` 與 `RCov_{b+1}` 使用**完全不相交**的
日報酬集合，兩者之間沒有任何機械攜帶。這由測試 pin 住：
`test_block_rcov_blocks_are_non_overlapping` 逐對驗證區塊沒有共用任何一天。

**第二層防禦（更重要）**：評分完全不看 proxy。橫向比較的裁判是**真實日報酬算出來的組合實現變異數**，
不是「誰把 proxy 預測得準」。所以就算 proxy 對 HAR 有偏袒，GMV 的評分也不會繼承這個偏袒。

**第三層：benchmark 與 HAR 用的是同一份資訊集。** 這點可以嚴格證明——

```
mean(RCov_b, b = 1..m) / k  ==  非去均值 rolling sample 二階動差(前 m·k 日)
```

由 `test_benchmark_is_nested_in_har_information_set` 以數值恆等式驗證。也就是說 rolling sample
benchmark **完全嵌套在 HAR 的資訊集裡**，兩者是同一份日報酬歷史的不同加權方式。
所以這場比較是**純粹的加權機制檢定**，不存在「誰看到的資料比較多」的不對稱。
（為維持這個恆等式，`sample` 與 Ledoit-Wolf 都採非去均值口徑，`assume_centered=True`。）

**殘留的誠實 caveat**：非重疊區塊避開了機械重疊，但沒有避開**估計噪音**——用 5 個觀測值估
4×4 矩陣本來就很吵。這個噪音正是本實驗最後的主要發現（§六），也是我認為最脆弱的地方之一（§八）。

---

## 四、方法

### 4.1 參數化與正定性

主 spec 用 **Cholesky**（Chiriac & Voev 2011）：對 `RCov_b = L L'` 的 10 個下三角元素各配一條 HAR，
預測後重組 `Σ̂ = L̂ L̂'`。

**選 Cholesky 而非 log-matrix 的理由**：`L L'` 對**任何**對角線非零的實矩陣 `L` 都正定
——對角元素的**正負號無關**。所以線性預測不可能吐出非正定矩陣，正定性是**構造保證**而非運氣，
也不需要任何 eigenvalue 修補步驟（修補會變成「改資料」）。
`test_chol_unvec_is_pd_even_with_negative_diagonal` 用刻意帶負對角的向量驗證這件事。

代價是 Cholesky **對資產排序不變性不成立**——這在本實驗被證明是一階問題，見 §五 permutation 敏感度。
因此另跑 **matrix-log**（Bauer & Vorkink 2011）作為次要 spec：`exp(A)` 對任何實對稱 `A` 都正定，
且該映射**對排列等變**，正好隔離「Cholesky 排序依賴」這個嫌疑。
`test_logm_is_permutation_equivariant_but_cholesky_is_not` 同時驗證 logm 等變、Cholesky 不等變。

**正定失敗率 = 0/933，兩個 spec 皆然**（`audit.positive_definite_check`）。
需要強調：**這個 0 是結構性的，不是實證發現**——兩種參數化都構造保證正定，所以這個數字
只證明程式沒寫錯，不證明模型好。真正該看的診斷是**條件數**（§六 3）。
另記 `forecast_negative_diagonal_count = 0`（Cholesky 下對角預測值從未穿越零）。

### 4.2 HAR 串級

在區塊頻率上重建 HAR 串級：lag `(1, 4, 12)` 區塊。5 日區塊下約等於（週, 月, 季）。
每個轉換後元素各自一條 OLS，**每次再平衡以擴張窗口重新估計**（首次 144 列訓練 → 末次 1,076 列）。

### 4.3 對照組

| 名稱 | 定義 |
|---|---|
| `sample` | 252 日滾動非去均值二階動差 |
| `ledoit_wolf` | 同窗口 Ledoit-Wolf 收縮（`assume_centered=True`） |
| `ewma` | RiskMetrics λ=0.94，以前 252 日二階動差初始化 |
| `equal_weight` | 1/N **參考點**，不屬檢定 family（它不是共變異數估計量） |

### 4.4 Lookahead policy（最高風險項）

**規則**：所有估計量都只讀到「區塊 t−1 最後一天」為止的日報酬；權重套用在「區塊 t 第一天」起。

機械驗證（`audit` 節點，每次再平衡都檢查）：
- `all_apply_start_after_info_end = true`
- `min_gap_days = max_gap_days = 1` — 資訊截止日與權重生效日永遠恰好差 1 天
- HAR 訓練列的最晚 target 是區塊 t−1，在區塊 t−1 結束時已完全觀測到

這等價於區塊層級的 `shift(1)`。三個測試從不同角度封住：

- `test_har_forecast_is_invariant_to_the_future` — 把區塊 t 之後的資料**全部打亂**，
  區塊 t 的預測值必須逐位元不變（同時覆蓋 regressor 與訓練列兩條洩漏通道）
- `test_har_regressor_row_uses_only_information_through_that_block`
- `test_ewma_uses_only_past_returns`
- `test_backtest_applies_weights_strictly_after_the_information_date`

### 4.5 統計推論

**主檢定**：Ledoit & Wolf (2011) 式的兩組合**變異數差異** HAC 檢定——對動差向量
`(E a, E b, E a², E b²)` 用 delta method，Newey-West 處理平方報酬的波動叢聚。
負統計量代表 HAR 波動較低。

刻意檢定**變異數**而非二階動差：GMV 最小化的是變異數，兩者在均值不同時會分歧。
`test_variance_difference_test_removes_the_mean` 用「同變異數、均值差很大」的一對序列驗證
`delta ≈ 0`。檢定的實證 size 另由 `test_variance_difference_test_is_calibrated_under_the_null` 驗證。

**HAC 落後期**：用 repo canonical bandwidth `ceil(h^(1/3)·n^(1/3))`，n=4,665 → **lag 17**。
**沒有使用 `h−1`**（h=1 時退化成完全不做 HAC，repo 硬規則明令禁止）；
`test_hac_lag_is_never_zero_at_h_equals_one` 機械擋住這個退化。

依規則**先量 acf 再判斷**：loss differential 的 acf(1) 僅 **+0.079 ~ +0.103**（`loss_differential_acf`），
自相關很弱，因此 HAC 選擇在此案例**不是關鍵**——lag 從 0 掃到 63，`t` 值只在
+4.45 ~ +4.81 之間移動（`lag_sensitivity`），結論不隨 bandwidth 改變。這點如實報告，
不誇大 HAC 的重要性。

**多重比較**：family **事前寫死在程式碼**（`PRIMARY_FAMILY = (sample, ledoit_wolf, ewma)`，3 個比較），
主校正 **Holm-Bonferroni**（FWER），另報 Benjamini-Hochberg FDR。
`equal_weight` 不在 family 內（參考點）。

**Bootstrap**：studentized circular block bootstrap（2,000 次，`seed = 42`，block = 17），
作為 delta method 的穩健性對照。

**交叉驗證**：另跑 repo canonical `volpred.stats.model_evaluation.dm_test`（對平方報酬），
結果與主檢定高度一致（EWMA 比較：`t = +4.546` vs `+4.564`）。已明確標註 DM 版本檢定的是
**二階動差**而非變異數。

---

## 五、事前登記的成功標準

**在看到任何結果之前寫死於 `adjudicate()`，並由 4 個測試 pin 住語意**
（`test_adjudicate_*`，含「同時贏一個又輸一個時 LOSE 優先」以防事後挑好看的講）：

| 判定 | 條件 |
|---|---|
| `WIN` | 點估計低於全部三個 benchmark **且** 對 Ledoit-Wolf 的比較通過 Holm α=0.05 |
| `MIXED` | 有比較通過 Holm 且對模型有利，但不滿足 WIN |
| `TIE_NULL` | 沒有任何比較在任一方向通過 Holm |
| `LOSE` | 有 benchmark 在 Holm 後顯著**更低**波動 |

**NULL 結果事前即宣告為完全可接受且同樣有價值。** 超參數（區塊長度、HAR lag、burn-in、
benchmark 窗口、λ、資產集）全部事前固定；**結果出來後未做任何調參或期間挑選**。
5 日與 10 日區塊事前即登記為並列回報，並事先聲明「若兩者不一致就報告不一致，不挑贏的那個」——
本次確實不一致（§六 3），照約定處理。

---

## 六、結果

### 6.1 Headline（Cholesky，5 日區塊）

| 策略 | 年化波動 | 每次再平衡換手 | HHI | 總曝險 Σ\|w\| | 做空比例 |
|---|---|---|---|---|---|
| **har_rcov_chol** | **9.256%** | **0.400** | 0.68 | 1.32 | 81% |
| sample | 8.933% | 0.045 | 0.74 | 1.43 | 81% |
| ledoit_wolf | 9.029% | 0.034 | 0.48 | 1.17 | 56% |
| ewma | **8.724%** | 0.324 | 0.88 | 1.50 | 85% |
| equal_weight（參考） | 11.433% | 0.014 | 0.25 | 1.00 | 0% |

| 比較 | t | raw p | Holm p | bootstrap p | \|t\|>3 |
|---|---|---|---|---|---|
| HAR vs sample | +2.002 | 0.0453 | 0.0906 | 0.0565 | ✗ |
| HAR vs ledoit_wolf | +1.431 | 0.1524 | 0.1524 | 0.1539 | ✗ |
| **HAR vs ewma** | **+4.564** | 5.03e-06 | **1.51e-05** | **0.0005** | **✓** |

全部 t 為**正**＝HAR 波動較高。對 EWMA 的劣勢在 Holm、BH、bootstrap、Harvey 門檻下**全部成立**。

### 6.2 換手：同樣（或更差）的波動，7–12 倍的換手

HAR-RCov 每次再平衡換手 **0.400**，rolling 估計量只有 **0.034–0.045**。
描述性成本敏感度（`cost_sensitivity_descriptive`）：10bp 單邊成本下 HAR 淨年化報酬由
8.404% 掉到 **6.392%**，Ledoit-Wolf 只由 9.217% 掉到 **9.044%**。

**這裡的宣稱範圍要講清楚**：GMV 最小化的是變異數不是報酬，所以上面的淨報酬數字是
**描述性脈絡，不是可交易性結論**。可以誠實說的是：**HAR-RCov 沒有用更高的換手換到更低的波動**
——它在兩個維度上都被支配。不能說的是「因此某策略在扣成本後可交易」，本實驗沒做效用框架
或完整市場衝擊模型，對此不表態。

### 6.3 區塊長度：兩個判定不一致，機制是 proxy 條件數

10 日區塊下 HAR 明顯改善（9.256% → **8.811%**），判定變成 `TIE_NULL`
（vs EWMA `t = +0.052`，實質打平；vs LW `t = −1.789` 點估計較優但不顯著）。

**照事前約定報告不一致，並給出機制證據**：

| | 5 日區塊 | 10 日區塊 |
|---|---|---|
| RCov 條件數 median | 196 | **67** |
| 條件數 p95 | 3,206 | **319** |
| 條件數 max | 463,462 | **1,580** |

用 10 個觀測值估 4×4 矩陣比用 5 個好得多，條件數 p95 降 10 倍、max 降 290 倍。
關鍵不對稱：block 拉長時 **HAR 改善 0.45pp，benchmark 反而各自小幅變差 0.06–0.09pp**
（sample 8.933→8.991，LW 9.029→9.076，EWMA 8.724→8.807）。若差異來自「再平衡頻率變低」，
應該全體同向移動；實際是 HAR 單獨大幅改善，指向**proxy 估計噪音才是綁住 HAR 的因素**。

**但即使在 10 日區塊，HAR 仍未打敗任何 benchmark**（`benchmarks_beaten_after_holm = []`），
而且換手仍是 0.468 對上 sample 的 0.068。所以這個不一致改變的是「輸多少」，不是「有沒有贏」。

⚠️ 10 日 spec 的初始訓練列只有 66 列（5 日為 144 列），這是它自己的弱點，一併揭露。

### 6.4 參數化：換成 matrix-log 仍然輸

| | 年化波動 | 換手 | HHI | Σ\|w\| | vs EWMA |
|---|---|---|---|---|---|
| Cholesky | 9.256% | 0.400 | 0.68 | 1.32 | t=+4.564 |
| **Matrix-log** | **8.990%** | **0.528** | **1.53** | **1.89** | t=+2.528（Holm₃ 0.0344） |

matrix-log 改善了波動（部分呼應排序依賴的診斷），但**仍輸給 EWMA**，且**部位明顯更激進**
（HHI 由 0.68 升到 1.53，總曝險 1.89）、**換手更高**（0.528）。

⚠️ **這個 spec 是 post-hoc 加入的**（在看到主結果之後，為了回答「負面結果會不會只是 Cholesky
排序依賴的產物」）。誠實處理方式：程式另算了**橫跨兩個 spec 的 6 比較 Holm 校正**
（`widened_correction_over_both_specs`）。在該較嚴格的校正下 `logm_vs_ewma` 為 **0.0573**
（落在 0.05 之外，變成邊緣），`chol_vs_ewma` 仍為 **3e-05**。
需要說明的是：**對模型不利的結論不會因為多看一眼而變便宜**，多重比較校正保護的是
「找到有利結果」的方向；這裡把兩邊都報出來只是為了透明。

### 6.5 禁空與次期間

**禁空 GMV**（`long_only_robustness`）：HAR 9.506% vs EWMA 8.868%，`t = +4.607`，Holm `p = 1.22e-05`
——判定同為 `LOSE`。空頭約束沒有救回 HAR。

**次期間**（`subperiods_ann_vol`，年化波動）：

| 期間 | HAR | sample | LW | EWMA | 等權 |
|---|---|---|---|---|---|
| GFC 2007-12–2009-06 | 12.939% | 12.497% | 12.483% | 12.279% | 18.605% |
| 後 GFC 2009-07–2019-12 | 7.309% | 6.968% | 7.040% | 6.914% | 8.360% |
| COVID 後 2020-01– | 10.901% | 10.608% | 10.765% | 10.224% | 13.374% |

**HAR 在三個次期間全部是共變異數類策略中最差的**，符號完全一致，不是特定期間的產物。

### 6.6 Cholesky 排序敏感度：效應量級被排序選擇淹沒

跑完 24 種資產排序的完整 pipeline（`cholesky_permutation_sensitivity`）：

- 年化波動範圍 **9.056% – 9.823%**，全距 **0.767pp**，標準差 0.218pp
- canonical 排序（SPY,QQQ,GLD,TLT）給 9.256%，接近 24 種的均值 9.360%——**沒有誤選到極端排序**

**這是本實驗最重要的方法論警告**：HAR 與 benchmark 的差距約 0.2–0.5pp，
而**單純換資產排序就能移動 0.77pp**。也就是說 Cholesky spec 下**效應量級並未被識別**。

不過方向性結論仍然成立：即使是 24 種排序中**最好的那一個**（9.056%），
仍高於 EWMA 的 8.724%，也沒有低於 LW 的 9.029% 多少。**所以「HAR 沒贏」對排序穩健，
「HAR 差多少」則不可信。** 這也正是加跑排列等變的 matrix-log spec 的理由。

---

## 七、我宣稱什麼、不宣稱什麼

**宣稱（每條都指得到 results.json 欄位）**：

1. 在本資產集與樣本期間，HAR-RCov（兩種參數化、兩種區塊長度、含禁空）**未能在 GMV 樣本外實現波動上
   打敗 sample / Ledoit-Wolf / EWMA 任何一個**。→ `headline.model_beats_no_benchmark_in_any_specification`
2. 5 日區塊 Cholesky spec 下，**EWMA 顯著優於 HAR-RCov**，且在 Holm / BH / bootstrap / Harvey
   四道門檻下都成立。→ `block_5d.inference.tests.ewma`
3. HAR-RCov 的換手是 rolling 估計量的 **7–12 倍**，且**沒有換到更低的波動**。→ `metrics.*.turnover_mean_per_rebalance`
4. 共變異數估計對 GMV 明顯有價值（相對等權降低約 2.2–2.7pp 年化波動），失敗的是 **HAR 動態建模這一層**。→ `metrics.equal_weight.ann_vol`
5. 有證據指向**綁住 HAR 的是日資料 RCov proxy 的估計噪音**（條件數 + 區塊長度不對稱改善）。→ `audit.block_rcov_condition_number`

**不宣稱**：

- ❌ **不宣稱**「HAR-RCov 在有 intraday 資料時也會輸」。本實驗只證明**在日資料能造出的 proxy 品質下**輸。
  文獻中 Chiriac & Voev (2011) 的增益是建立在**日內** realized covariance 上的，本實驗沒有反駁那個設定。
- ❌ **不宣稱**任何可交易性結論。沒做效用框架、沒做市場衝擊模型、成本分析僅為描述性。
- ❌ **不宣稱** EWMA 是最佳共變異數估計量。它在本設定贏，但它同時是最集中、最高曝險的
  （HHI 0.88、Σ|w| 1.50），本實驗沒有檢定它的尾端風險。
- ❌ **不宣稱**效應量級。§六 6 顯示 Cholesky spec 下量級被排序選擇淹沒。
- ❌ **不宣稱**這個結論外推到其他資產集、其他 N、或其他組合目標（僅測 GMV，未測 mean-variance / risk parity）。
- ❌ 報酬與 Sharpe 差異**不作為證據**：GMV 不以報酬為目標，這些數字只是描述性脈絡。

---

## 八、給審查者：我認為最脆弱的三個地方

### 1. RCov proxy 的估計噪音與「模型 vs proxy」的識別問題（最脆弱）

用 5 個觀測值估 4×4 共變異數矩陣本來就很吵（條件數 max 達 463,462）。
HAR 是對這些吵的 Cholesky 元素做線性迴歸，離群值會主導 OLS。

**這造成一個我沒有完全解開的識別問題**：本實驗的負面結果，究竟是
(a)「HAR 這個動態結構對共變異數沒用」，還是 (b)「proxy 太吵，任何建模都救不了」？
§六 3 的區塊長度證據**傾向 (b)**，但那只有兩個點（5 日與 10 日），不足以定論。

誠實的說法是：**本實驗證明的是「日資料下這條路走不通」，而不是「HAR-RCov 這個想法不對」。**
README 全文已按此範圍寫。真正要分辨 (a)/(b) 需要 intraday 資料，那是另一個 K。

### 2. Cholesky 的排序依賴是一階效應，不是註腳

24 種排序的全距（0.767pp）**大於**待測效應本身（0.2–0.5pp）。我用 matrix-log spec 部分緩解
（排列等變），但 matrix-log 是 post-hoc 加的，而且它自己有另一個問題：對 ill-conditioned 區塊做
特徵分解，小特徵值的對數會被放大成極端值——這可能正是它 HHI 飆到 1.53、曝險 1.89 的原因，
我**沒有進一步診斷**這一點。

如果要我指出最可能被審查者攻破的設計選擇，這是第二個。

### 3. 只有一個資產集、N 只有 4，且 EWMA 的勝出未被解釋

N=4 是為了讓 5 日區塊 RCov 保持正定而綁定的（k > N）。但 N=4 也是
**shrinkage 最不需要發揮的規模**——Ledoit-Wolf 的優勢在 N 大時才明顯，這可能解釋了
為什麼 LW 在此並非最佳。反過來說，本實驗**沒有測到高維情境**，而高維正是實務組合的常態。

另外我**沒有解釋 EWMA 為什麼贏**。合理猜測是 λ=0.94（約 33 日半衰）恰好匹配這四個資產的
共變異數變化速度，但這是猜測，results.json 裡**沒有任何欄位支撐它**，因此未寫入宣稱。

### 其他已知但影響較小的問題

- 10 日區塊 spec 的初始訓練列僅 66 列，早期 OOS 的參數估計不穩（已於 §六 3 揭露）。
- matrix-log 的 `E[exp(A)] ≠ exp(E[A])`、Cholesky 的 `E[LL'] ≠ E[L]E[L]'`，兩者都有 Jensen 偏誤，
  本實驗未做偏誤修正（文獻上 Chiriac & Voev 亦承認此問題）。
- 成本模型只有線性單邊 bps，無市場衝擊、無 bid-ask 動態。已標為描述性。

---

## 九、復現

```bash
uv run python experiments/K1714/K1714.py                                  # 約 40 秒
uv run --extra dev python -m pytest experiments/K1714/test_K1714.py -q    # 33 tests
```

首次執行會下載並快取 `data/prices_raw.csv`；之後一律讀快取，確保 byte-level 可復現。
所有隨機程序（bootstrap、circular block 抽樣）固定 `seed = 42`。

**檔案**

| 檔案 | 內容 |
|---|---|
| `K1714.py` | 完整 pipeline |
| `K1714_results.json` | 全部結果（宣稱的唯一來源） |
| `test_K1714.py` | 33 個不變量測試（lookahead / 嵌套性 / 推論校準 / 判定規則） |
| `data/prices_raw.csv` | 價格快取（sha256 記於 results.json） |
| `figures/fig1_rolling_vol.png` | OOS 63 日滾動年化波動 |
| `figures/fig2_cumulative_variance_differential.png` | 對 LW 的累積平方報酬差 |
| `figures/fig3_turnover_leverage.png` | 換手與總曝險 |
| `figures/fig4_rcov_conditioning.png` | RCov proxy 條件數分佈 |

## 十、參考文獻

- Chiriac, R., & Voev, V. (2011). Modelling and forecasting multivariate realized volatility. *Journal of Applied Econometrics*, 26(6), 922–947.
- Bauer, G. H., & Vorkink, K. (2011). Forecasting multivariate realized stock market volatility. *Journal of Econometrics*, 160(1), 93–101.
- Ledoit, O., & Wolf, M. (2011). Robust performance hypothesis testing with the variance. *Wilmott*, 2011(55), 86–89.
- Ledoit, O., & Wolf, M. (2004). A well-conditioned estimator for large-dimensional covariance matrices. *Journal of Multivariate Analysis*, 88(2), 365–411.
- DeMiguel, V., Garlappi, L., & Uppal, R. (2009). Optimal versus naive diversification. *Review of Financial Studies*, 22(5), 1915–1953.
- French, K. R., Schwert, G. W., & Stambaugh, R. F. (1987). Expected stock returns and volatility. *Journal of Financial Economics*, 19(1), 3–29.
- Corsi, F. (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics*, 7(2), 174–196.
- Harvey, C. R. (2017). Presidential address: The scientific outlook in financial economics. *Journal of Finance*, 72(4), 1399–1440.
