# K1684 R3 — forecast-tail-divergence E1：變異數目標尺度再校準 gating 實驗（primary Codex rescue）

> [!IMPORTANT]
> **這是 R3 primary-Codex-review rescue**，取代 2026-07-12 被 Codex BLOCKED 的 R1，也修正
> R2/R3 交界處的共同支撐、provenance、資訊集與 canonical risk-test 漂移。R1 的七項 blocker
> （[`CODEX_REVIEW_BLOCKED.md`](CODEX_REVIEW_BLOCKED.md)）關閉證據保留在歷史
> [`k1684_rerun_r2_receipt.json`](k1684_rerun_r2_receipt.json)；本次收據是
> [`k1684_rerun_r3_receipt.json`](k1684_rerun_r3_receipt.json)。**R1 的任何數字都沒有被沿用。**
>
> **裁決改變**：R1 宣稱 `H2_REJECTED`（+ FRL 短文路線）。R3 的裁決是 **`H2_UNSUPPORTED`** —
> 在 Harvey 門檻下 leg 1 **兩個方向都不顯著**，本實驗**不支持任何論文路線**。
> Primary Codex review 為 **CONDITIONAL_PASS**：可記錄 null/methodology knowledge；因 gate 為 null，
> **不得**據此寫 feed 或選論文路線，必須先完成 E2。

- **Experiment ID**: `k1684`（R3）｜ **Status**: completed — primary Codex review CONDITIONAL_PASS
- **執行日期**: 2026-07-12（台灣時間）
- **提出者**: Fable 深度審查 2026-07-11（§5.1 E1，P0 gate）；重跑由 Codex R1 review 下令
- **父實驗**: `experiments/k850`、`experiments/k854`
- **腳本**: `k1684_ftd_e1_scale_gating.py`（主）+ `k1684_rv_active.py`（RV builder）
- **結果**: `k1684_ftd_e1_scale_gating_results.json` ｜ **收據**: `k1684_rerun_r3_receipt.json`
- **Seed**: `20260712`（multistart grid、bootstrap、擾動 draw 全部同一顆 seed）｜ **R3 執行時間**: 83 秒

---

## 1. 裁決

> ## **H2_UNSUPPORTED** → **本實驗單獨不足以選擇任何論文路線**
> 五個 run（primary + 4 個 sensitivity / diagnostic）全部得到同一裁決。

「QLIKE 與尾部覆蓋正交」需要兩條腿同時成立：

| | 命題需要的 | K1684 R3 實測（450 天共同樣本） |
|---|---|---|
| **腿 1（預測損失）** | HAR 在**共同目標**上 QLIKE 贏 GJR | **立不起來。** 對齊目標（0050 r²）DM **t = +1.48**（p = 0.140，n = 436）→ 方向偏 GJR，但 **\|t\| < 3**。**兩個方向都沒過 Harvey 門檻。** |
| **腿 2（尾部覆蓋）** | HAR 的 VaR 失敗、GJR 過關，且尺度校正救不回來 | **成立。** 1% 下 HAR 家族 12 格**沒有一格** trinity PASS；GJR+CF（2/450）、RGL+CF（3/450）綠燈 PASS。三個尺度校正 rescue **0/3**（rescue 的定義是**兩個 α 都 PASS**）。 |

**腿 2 成立、腿 1 立不起來 → 沒有「divergence」可談，但也不能宣稱 H2 被推翻。**

R1 把 `t = +2.33`（R1 的數字）讀成「腿 1 反轉 → H2_REJECTED → 走 FRL 短文」，是把 p < 0.05 當結論門檻；
本專案的正式門檻是 **Harvey |t| > 3**。R3 使用修好的 RV 之後這個 t 掉到 **+1.48**，離門檻更遠。

**R3 是一個誠實的 null**：它證明 K850/K854 的 headline 建立在**建構性瑕疵**上（§3、§6），
但**沒有**產生足以支撐任何一條論文路線的正面證據。要談 HAR-RV 本身，必須跑
**E2（以自身 realized measure 評分的市場，n ≥ 2,500）**。

---

## 2. R2/R3 相對 R1 改了什麼（七項 blocker + review 過程中新抓到的項目）

| Gate | R1 的問題 | R2/R3 的做法 |
|---|---|---|
| **G1** | RV 用 `TX1` 單檔、三段 session 分開加總（**丟掉所有 boundary jump**）、日盤到 13:45 而 ETF 13:30 收盤（資訊集重疊） | 全 TX 合約 → 每日選**視窗內**成交量最大的 active contract → **單一連續 tick path 13:30(D−1) → 13:30(D)**，所有 boundary jump 都在路徑裡 |
| **G2** | headline 靠 4-start GJR MLE | GJR 與 RealGARCH-Log **各 100 個 seeded starts**，每次 refit 存 convergence / objective / basin 分布；fragility probe **同時**跑 K854 原始 `fit_gjr` 與 R2 fitter |
| **G3** | `Φ⁻¹(α)/Φ⁻¹(π̂)` 只在 Normal 下可識別卻套到 CF/HistSim；CI 上下界顛倒（154 格 lo > hi）；用未檢定的 `\|Δc\|<0.10` 判通道 | 改用**分布自由**的經驗尺度因子 `c = quantile_{1−α}(r/VaR)` + seeded bootstrap CI；參數版只留給 Normal 格且**在程式裡 assert 單調性**（顛倒即 raise）；`Δc` 改成**成對 bootstrap 檢定** H₀: c(1%) = c(5%) |
| **G4** | placebo 用「near 1」帶過 | placebo 全表（**三種尾層** × 雙 α × IS/OOS × VaR+ES+FZ0）+ **對池 bootstrap 的 CI** |
| **G5** | 用 p < 0.05 下結論；`decide_gate()` 宣稱檢查 leg 2 的「GJR PASS」卻沒實作 | 正式結論一律 **Harvey \|t\| > 3**；`decide_gate()` 真的檢查 GJR trinity；每個 DM pair 用自己的 pairwise mask 並報 n |
| **G6** | 缺 1%/5% × IS/OOS × VaR+ES × joint loss | 雙 α；OOS 五 run + **13 格樣本內 panel**；每格都有 canonical **Acerbi–Szekely Z1** + 補充的 **McNeil–Frey bootstrap ES 檢定** + **Fissler–Ziegel FZ0 joint loss**（Patton-Ziegel-Chen 2019）+ FZ0 的 canonical DM；每格加**精確二項（Clopper-Pearson）區間** |
| **G7** | `open(final,'w')` 直接寫 | `tmp → json.load 驗證 → os.replace`；seed / provenance / lookahead 稽核齊全 |

**Codex review 過程中新抓到、也一併修掉的項目**（不在 R1 的 blocker 清單裡）：

1. **active contract 的選擇本身會偷看未來** — 用「整日成交量」排序會用到 13:30–13:45（視窗關閉之後）的成交量。
   改成**只用視窗內成交量**排序（實測只有 **2 天**選擇不同）。
2. **父檔 `k854.var_backtest` 在零違規時 Kupiec 回 p = 1.0（自動 PASS）** — 450 天 5% 下零違規的
   LR_uc ≈ 46（p ≈ 1e-11），是**決定性拒絕**。R2 在 k1684 內自寫 `var_backtest_r2`，用 `0·log0 := 0`
   把邊界算對（**不改父檔** — scope 只在 `experiments/k1684/`）。同樣的短路也存在於 Christoffersen
   獨立性檢定（只要 t11 = 0 就回 p = 1）—— 而 t11 = 0 在 α = 1% 下是**虛無假設下的常態**，不是退化。
3. **RV 視窗與報酬視窗可能不同步** — TX tick 檔缺檔時，stitcher 會把 D 接到「上一個有檔的日子」，
   於是 RV 跨了兩個交易日、而 ETF 報酬只跨一天。新增 **continuity gate**：RV path 的起點必須等於
   ETF 的前一個交易日 → **丟掉 9 天並列名**（OOS 內 **0 天**）。
4. **placebo 的 θ 用了比 HAR 短 3.5 倍的池** — 這違反 symmetric refinement 硬規則。**修了兩次**：
   R2 先補上 GJR 的 burn-in pass 讓兩邊都從 2018+ 起算，但這只對齊了**起點**；HAR 的 expanding fit
   從第 250 筆才給得出 σ、GJR 要到第 500 筆，於是池內仍差約 250 列（θ 池 1,235 vs 985 筆）。
   R3 改成兩邊都在**共同支撐集**（兩個 σ 來源都存在的交集）上估 θ，並加一道 `RuntimeError` 斷言
   兩池筆數必須相同。**這一修直接改變了結論**（見 §3）。
5. **資訊集 audit 只查時鐘、沒查日期** — R3 同時要求 `path_end_ts` 的日期就是 RV row 的 D，且時間
   ≤ 13:30；任一 missing/date mismatch/late row 都直接 `raise`。現有 2,213 列三種違規都是 0。
6. **Trinity / ES canonical 規格漂移** — R3 的 Trinity 改為 Kupiec + Christoffersen **CC joint** + Basel；
   ES 補上 Acerbi–Szekely Z1。舊 independence-only Trinity 在現有 214 格與 CC 版恰好 0 格翻轉，
   所以主裁決不變；McNeil–Frey 留作補充診斷。

---

## 3. 最重要的兩個發現

### 3.1 R1 說的「σ 低估 30%」，有一大半是 RV 建構造成的

K854 的 RV 把日盤、夜盤 PM、夜盤 AM **分三段各自加總平方報酬**，三個 session boundary 的跳空
**完全沒被算進去**：

| 成分 | 佔 R2 close-to-close RV | K854 的 RV 有算嗎 |
|---|---|---|
| 日盤 08:45–13:30 | 38.2% | ✅ |
| 夜盤（15:00–05:00） | 37.4% | ✅ |
| **跳空 05:00 → 08:45（夜盤收 → 日盤開）** | **17.7%** | ❌ **丟掉** |
| **跳空 13:45 → 15:00（日盤收 → 夜盤開）** | **5.3%** | ❌ **丟掉** |
| **13:30–13:45（ETF 收盤後 15 分鐘）** | 1.0% | ❌（且屬於**下一個**視窗） |

→ **R2 / R1 的 RV 平均比 = 1.312**（相關 0.822）。K854 的 realized measure **系統性少掉約 24% 的
close-to-close 變異**，σ 少掉約 **14%**。R1 把「σ 低估約 30%」整包歸因於「TX vs 0050 目標錯配」——
**其中一大塊是它自己的 RV 少算了跳空。**

### 3.2 Placebo 也把「正確對齊」的 GJR 放大 12% — 尺度 miss **不是**目標錯配專有的

| 校正 | R1（舊 RV） | **R3 OOS 日加權平均（修好 RV + 共同支撐）** | R3 最後一次更新估計與 95% CI（對殘差池 bootstrap） |
|---|---|---|---|
| (a) expanding std(z) | 1.354 | **1.159** | **1.184 [1.111, 1.258]**（最後一次更新的估計）→ **排除 1** |
| (b) Mincer–Zarnowitz 隱含尺度 | 1.349 | **1.184** | — |
| (c) Hansen–Lunde | 1.204 | **1.072** | — |
| **PLACEBO（同一套 (a) 打在 GJR 上）** | 1.126 | **1.124** | **1.117 [1.052, 1.189]** → **也排除 1** |

**兩個 CI 大幅重疊**（HAR 1.111–1.258 vs placebo 1.052–1.189）。也就是說：
**「校正機器只動錯配的模型、不動正確對齊的模型」這個 R1 敘事站不住。**

> **R2 → R3 的差別**：把 θ 改估在共同支撐集上之後，**placebo 完全沒動**（1.117，因為交集就是
> GJR 那個較短的池），**被拉下來的是 HAR**（1.219 → 1.184）。也就是說 R2 的表裡，HAR 之所以看起來
> 比 placebo 高，有一部分是它多吃了 250 天樣本的 artifact —— 這正是 symmetric refinement 硬規則
> （`.claude/rules/experiments.md`；K1216b 前例）要防的東西。修完之後兩者更靠近，**§3.2 的結論不但
> 沒被推翻，還更強**。

為什麼 placebo 會是 1.12？樣本內的 placebo 因子是 **1.0015**（GJR 的 MLE 本來就把自己的殘差
標準差 fit 成 1）；一到**即時預測**的池上就變成 1.12 —— 這是 **GARCH 即時預測在 2018+ 池上系統性
低估變異**的效應，**與目標錯配無關**。這個 IS vs OOS 的對比（1.00 → 1.12）正是把兩者分開的關鍵，
而它只有在 placebo 用**與 HAR 相同的估計窗**時才看得到。

> **CI 的口徑**：s_t 是**階梯函數**（每 63 天才更新一次，OOS 內共 8 次更新）。把 450 個日值當
> iid bootstrap 會憑空製造 450 個觀測、把 CI 壓到極窄（本實驗 review 前就犯過這個錯）。
> 現在的 CI 是**對最後一次更新所用的殘差池** bootstrap（B = 2,000，seed 固定），
> 反映 `s = std(z)` 這個估計量真正的抽樣變異。

---

## 4. 腿 1：QLIKE / DM（雙目標，Harvey 門檻）

DM 一律用 canonical `volpred.stats.model_evaluation.dm_test`；HAC bandwidth = `ceil(h^(1/3)·n^(1/3))` = **8**
（**不是** `h−1`，後者在 h = 1 時退化成不做 HAC）。每個 pair 用自己的 common mask 並各自報 n。

| 目標 | QLIKE（越低越好） | HAR-RV vs GJR | Harvey \|t\|>3？ |
|---|---|---|---|
| **TX RV**（K850/K854 慣例，**錯配**） | HAR-RV **0.1594** ｜ GJR 0.2088 | **t = −2.10**（p = 0.037，n = 450，acf1 = +0.23） | ❌ |
| **0050 r²**（**對齊**，VaR 真正打的目標） | HAR-RV 1.7178 ｜ GJR **1.6121** | **t = +1.48**（p = 0.140，n = 436，acf1 = +0.01） | ❌ |

**兩個目標、兩個方向，沒有一個過 Harvey 門檻。**

- R1（舊 RV）在錯配目標上是 t = **−5.13**；**修好 RV 後掉到 −2.10**。那個「著名的 t ≈ −5.6」
  有相當部分來自 HAR 在**自己那個少算跳空的 RV** 上的優勢。
- 對齊目標上，尺度校正後的 HAR-a 與 GJR 仍無差異（t = +0.25，p = 0.802）；
  HAR-a vs HAR-RV（對齊目標）t = **−2.21**（p = 0.028，**未過** Harvey）。
- 反過來在 **TX RV 目標**上，尺度校正是**有害的**（HAR-a vs HAR-RV：t = **+4.00**，**過 Harvey**）。
  同一個校正在兩個目標上一好一壞 —— 這是「目標錯配」本身的定量指紋。

---

## 5. 腿 2：VaR + ES（1% / 5%，OOS 450 天，2023-03-01 ~ 2024-12-31）

Basel 口徑：**1% 是標準 250 天計數規則**（綠 ≤4 / 黃 5–9 / 紅 ≥10，套在 OOS 最後 250 天）；
**5% 是自訂 α-scaled 延伸**（綠 ≤20 / 黃 ≤45），**不是** canonical Basel（後者只定義在 1%）。
每格違規率都附**精確二項（Clopper-Pearson）95% 區間**（JSON `violation_rate_ci95_exact`）。

### 5.1 1% VaR（primary run，摘錄）

| Cell | 違規 | 違規率 [精確 95% CI] | Kupiec p | CC joint p | Basel | Trinity | 經驗 c | ES MF p |
|---|---|---|---|---|---|---|---|---|
| HAR+Normal | 11/450 | 2.44% [1.22, 4.33] | 0.009 | 0.018 | **red** | FAIL | 1.329 | 0.010 |
| **HAR+CF**（K854 headline 對應格） | **14/450** | 3.11% [1.71, 5.16] | **0.000** | 0.001 | yellow | FAIL | **1.401** | 0.204 |
| HAR+HistSim | 9/450 | 2.00% [0.91, 3.76] | 0.061 | 0.065 | yellow | FAIL | 1.300 | 0.080 |
| HAR-a+CF（尺度校正後） | 7/450 | 1.56% [0.63, 3.18] | **0.273** | 0.491 | yellow | **FAIL** | 1.212 | 0.099 |
| HAR-b+CF | 8/450 | 1.78% [0.77, 3.47] | 0.135 | 0.100 | yellow | **FAIL** | 1.175 | 0.240 |
| HAR-c+CF | 9/450 | 2.00% [0.92, 3.76] | 0.060 | 0.065 | yellow | FAIL | 1.317 | 0.115 |
| GJRf+CF（配對池的 GJR） | 11/450 | 2.44% | 0.009 | 0.018 | yellow | FAIL | 1.293 | 0.387 |
| GJRf-a+CF（**placebo 校正後**） | 8/450 | 1.78% | 0.135 | 0.283 | **green** | **PASS** | 1.143 | 0.532 |
| **GJR+CF** | **2/450** | 0.44% [0.05, 1.59] | 0.183 | 0.409 | **green** | **PASS** | 0.798 | n/a（<5 次超越） |
| **RGL+CF** | **3/450** | 0.67% | 0.449 | 0.736 | **green** | **PASS** | 0.825 | n/a |

**1% 下 HAR 家族 12 格沒有一格 trinity PASS。** 尺度校正把 Kupiec 救起來了（0.000 → 0.273），
但 Basel 仍是黃燈（7 次違規落在最後 250 天的黃燈區）。Trinity 的 canonical 定義是
Kupiec + Christoffersen CC joint + Basel 三者的 AND → 仍 FAIL。
**注意 placebo 的 GJRf-a+CF 反而 PASS** —— 同一套校正打在正確對齊的模型上會把它推過門檻，
這再次說明這台機器不是中性的。

### 5.2 5% VaR（primary run，摘錄）

| Cell | 違規 | Kupiec p | Basel | Trinity | 經驗 c | ES MF p |
|---|---|---|---|---|---|---|
| HAR+CF | 40/450 (8.89%) | 0.001 | yellow | FAIL | 1.271 | 0.042 |
| HAR+HistSim | 37/450 (8.22%) | 0.004 | yellow | FAIL | 1.186 | 0.256 |
| HAR-a+CF | 28/450 (6.22%) | 0.251 | green | **PASS** | 1.102 | 0.118 |
| HAR-b+CF | 29/450 (6.44%) | 0.177 | yellow | **FAIL** | 1.088 | 0.218 |
| HAR-c+CF | 38/450 (8.44%) | 0.002 | yellow | FAIL | 1.190 | 0.182 |
| GJR+CF | 21/450 (4.67%) | 0.743 | green | **PASS** | 0.926 | 0.979 |
| GJRf-a+CF（placebo） | 25/450 (5.56%) | 0.595 | green | **PASS** | 1.051 | 0.142 |

→ **HAR 只有 HAR-a 在 5% 被救回來（HAR-b 在 R3 的對稱池下已翻成 yellow/FAIL），1% 一格都沒有**
→ rescued = **0/3**（每個變體都要**兩個 α 都 PASS** 才算 rescued，沒有變體做到）。

### 5.3 ES 與 FZ0 joint loss

- **Acerbi–Szekely Z1 是 canonical ES gate**；McNeil–Frey 是補充的 exceedance-only 診斷。兩者都在
  JSON 每格 `es` 物件中完整列出。Primary 的 CF headline 格：HAR+CF 在 1% / 5% 都 FAIL
  （p = 0.011 / 0.0027）；GJR+CF 在 1% FAIL、5% PASS（p = 0.008 / 0.247）；reduced-form RGL+CF
  在雙 α 都 PASS（p = 0.306 / 0.379）。因此「GJR+CF VaR Trinity PASS」**不等於**「其 ES 也全面 PASS」。
  ES 不進 `decide_gate()`，所以不改 H2 null 裁決，但任何尾部充分性敘事都必須保留這項區分。
- 以下是 **McNeil–Frey** 的直觀尾損讀數（seeded bootstrap B = 10,000）：
  **所有 Normal 尾層的格子都不及格**（1% 與 5% 皆然；例如 HAR+Normal 1% p = 0.010、5% p = 0.002；
  GJR+Normal 兩個 α 都 p < 0.04）—— 常態尾在 ES 上系統性低估實現損失，這是尺度校正**碰不到**的一層。
  **CF / HistSim 多數過關但不是全部**：HAR+CF 在 5% 仍不及格（p = 0.042），
  HAR-b+HistSim 在 1% 實際 p = 0.054，邊緣 PASS。
- **Fissler–Ziegel FZ0**（Patton-Ziegel-Chen 2019，嚴格一致的 (VaR, ES) joint loss）+ canonical DM：
  `HAR+CF vs GJR+CF` t = +0.83（1%）/ +0.96（5%），GJR 較優但**未過 Harvey**；
  `HAR-a+CF vs HAR+CF` t = −1.62 / −2.24（尺度校正有改善，**未過 Harvey**）。
  **FZ0 這個 joint loss 上，沒有任何一組比較過 Harvey 門檻。**

### 5.4 通道判定（尺度 vs 尾形）— 改成可檢定的形式

R1 用未檢定的 `|Δc| < 0.10` 當判準。R2 拆成兩個問題、兩個工具：

1. **有沒有東西壞掉？** → **覆蓋檢定**（雙 α 的 Kupiec）。
   （n = 450 時 1% 的經驗 c 的 bootstrap band **本來就很寬**，寬到可以包含 1 —— 那是**檢定力**的陳述，
   **不是**「已校準」的證據，絕不可拿來當 PASS。）
2. **壞掉的是 scale 還是 shape？** → **成對 bootstrap 檢定** H₀: c(1%) = c(5%)。

| Cell | c(1%) | c(5%) | Δc bootstrap p | 判定 |
|---|---|---|---|---|
| HAR+CF | 1.401 | 1.271 | 0.738 | **SCALE**（覆蓋被拒；c 跨 α 不動） |
| HAR+Normal | 1.329 | 1.044 | 0.056 | SCALE（**邊緣**；Δc 幾乎顯著 → 常態尾另有 shape 成分） |
| HAR-a+CF | 1.212 | 1.102 | 0.735 | 覆蓋未被拒 → 沒有需要 scale 故事去解釋的東西 |
| GJRf+CF（**配對池的 GJR**） | 1.293 | 1.182 | 0.714 | **SCALE** |
| GJR+CF | 0.798 | 0.926 | 0.134 | 覆蓋未被拒 |

深審的「純尺度」診斷**與資料一致**（HAR+CF 的 c 在兩個 α 幾乎同值且遠離 1，H₀ 無法被拒絕）——
但**「無法拒絕」不等於「被證實」**：Δc 檢定在 n = 450 下檢定力有限。而且 **GJRf+CF（正確對齊的 GJR
配對殘差池）也被判成 SCALE，c = 1.293** —— 這個尺度 miss **不是 HAR 專有的病**。

---

## 6. GJR MLE 的 basin 脆弱性：R1 的指控成立，而且 R3 修好了

`gjr_fragility_probe()` 對報酬施加 **1e-6 相對擾動**（= yfinance 重新四捨五入的量級），
重跑整條 OOS refit 迴圈 10 次（seeded），**兩個 fitter 各跑一次**（4-start 那組呼叫的是
**K854 父檔的真正程式** `k854.fit_gjr`，不是把 robust fitter 截成 4 starts）：

| Fitter | σ 最大變動 | 1% 違規數範圍 | 5% 違規數範圍 | 違規數穩定？ |
|---|---|---|---|---|
| `k854.fit_gjr`（4 starts，**父檔原碼**） | **22.23%** | **[9, 10]** | **[20, 21]** | ❌ |
| `fit_gjr_robust`（100 starts） | 4.26% | [9, 9] | [21, 21] | ✅ |

**R1 的指控復現**（R1 報 29.03%，本次樣本因 continuity gate 少 9 天，數字是 22.23%，**同一結論**）：
數值上無關緊要的資料修訂會讓 4-start GJR 的違規數游走 —— 而 trinity 吃的正是違規數。
**100 starts 之後違規數完全不動。**

為什麼 4 starts 不夠：每次 refit 的 100 個起點中，**平均只有 1.5% 落進最佳 basin**
（~99 個相異 basin，最好與最差的 log-likelihood 差約 **29 個單位**）。
**K854 的 GJR 參數幾乎確定不是 MLE。**

> σ 仍會動 4.26%（最壞的那一天）不代表沒修好：**σ 的敏感度和違規數的敏感度是兩件事**，
> 只有違規數會進 trinity。兩個數字都報在 JSON 裡。

---

## 7. 樣本內 vs 樣本外（G6）

樣本內 panel（2017-01-03 ~ 2022-12-30，1,454 個 aligned rows；扣除 HAR 的 22-day 起始 lag 後
各表 1,432 個可評分日；**參數、尺度校正、尾層全部 fit 在同一批
報酬上**，因此**沒有任何預測力宣稱**，只用來做 IS/OOS 對照）：

| Cell | IS 1% 違規 | IS Kupiec p | IS Basel | IS trinity | OOS 1% trinity |
|---|---|---|---|---|---|
| HAR+CF | 5/1432 (0.35%) | 0.004 | green | FAIL（**過度保守被拒**） | FAIL（過度寬鬆） |
| HAR+HistSim | 15/1432 (1.05%) | 0.858 | green | **PASS** | FAIL |
| HAR-a+CF | 4/1432 (0.28%) | 0.001 | green | FAIL | FAIL |
| GJR+CF | 5/1432 (0.35%) | 0.004 | green | FAIL | **PASS** |
| GJR+Skewed-t | 10/1432 (0.70%) | 0.225 | green | **PASS** | FAIL |
| GJRf-a+CF（**IS placebo**） | 5/1432 | 0.004 | green | FAIL | PASS |
| RGL+CF | 4/1432 (0.28%) | 0.001 | green | FAIL | PASS |

兩個關鍵讀數：

1. **IS placebo 的尺度因子 = 1.0015**（vs OOS 的 1.117）。GJR 的 MLE 在樣本內把自己的殘差標準差
   fit 成 1 —— 完全符合理論。**OOS 才變成 1.12，證明那 12% 是「即時預測低估變異」，不是目標錯配。**
2. **「樣本內過度保守、樣本外過度寬鬆」這個訊號只有在 Kupiec 邊界修好之後才看得到**：
   舊實作在低違規數時回 p = 1.0 自動 PASS，會把它整個吃掉。CF 尾層在 2017–2022（含 COVID）
   殘差上估出來的尾巴**太胖**，到平靜的 2023–2024 反而變成太窄 —— 這是**第三個通道**
   （殘差池窗口 / 尾形），`sens_burnin_tailpool` 也獨立指向它。

---

## 8. 敏感度與內部一致性

| Run | 設定 | 1% baseline HAR+CF | rescued | 裁決 |
|---|---|---|---|---|
| **primary（gate）** | R2 RV；尾池 = K854（OOS-only, 63d）；θ 窗 = 2018+ | 14/450 | 0/3 | **H2_UNSUPPORTED** |
| sens_theta_short | θ 窗也用 K854 短池（HAR-b 三格不可估 → **移除並列名**） | 14/450 | 1/2 | H2_UNSUPPORTED |
| sens_daily_refresh | 尾池每日更新 | 10/450 | 0/3 | H2_UNSUPPORTED |
| sens_burnin_tailpool | 尾池延長到 2018（含 COVID）— **診斷用，不裁決** | 3/450 | 3/3 | H2_UNSUPPORTED |
| **sens_legacy_rv** | **R1/K854 的舊 RV**，其餘機器全部相同 — **診斷用** | 17/450 | 0/3 | H2_UNSUPPORTED |

- `sens_legacy_rv` 是**歸因對照**：RV 換回 K854 建構、其他（100-start GJR、修好的 Kupiec/Christoffersen、
  ES、FZ0）全部不變。它復現 R1 的 **17/450**，且對齊目標 DM t = **+2.32**（vs primary 的 +1.48）
  → **RV 重建本身就吃掉了 R1「腿 1 反轉」敘事的一大塊。**
- **HistSim 尺度不變性**：純尺度校正在數學上不可能移動 HistSim（殘差被同一個因子除掉）。
  實測 `max|VaR_a − VaR_base| = 1.4e−17` → 恆等。這是**硬限制**：HAR+HistSim 失敗的部分與尺度無關。
- **共同樣本**：任一格若無法覆蓋全部 450 個評估日，**整格移除並列名**（`cells_unavailable`），
  絕不用「它剛好有資料的那些天」回測。gate run 不允許移除任何格（違反即 `raise`）。

---

## 9. Lookahead / 資訊集稽核（機械驗證，非口頭宣稱）

1. **RV 資訊集**：2,213 天的 tick path，`path_end_ts` **全部與 RV row 同日**且結束時間全部
   ≤ 13:30:00（最晚 13:30:00、最早 13:29:51；date mismatch / late / missing 都是 0）——
   即「D 日收盤前最後一筆成交」。RV(D) 在 0050 收盤那一刻就已知，
   正好是 r(D+1) 報酬視窗開啟的瞬間 → R1 的 13:30/13:45 重疊**封死**。
2. **Continuity gate**：RV path 的起點必須等於 ETF 的**前一個交易日**（否則 realized measure 與它的
   目標描述的不是同一段區間）→ **丟掉 9 天並列名**（`2017-02-20` … `2025-04-24`），**OOS 內 0 天**。
3. **擾動稽核**：把 forecast origin `i` **當天及之後**的所有觀測值 × 10，要求 origin 當下的每一個
   預測與校正參數**逐位元不變**。涵蓋 HAR 預測、GJR 預測、θ 的三組參數。**30 條 assertion 全過**；
   失敗時腳本直接 `raise`，拒絕輸出結果。

---

## 10. 限制（誠實揭露）

1. **n = 450 < 專案 ≥500 硬規則。** 1% 下期望違規僅 4.5 次 → Kupiec 檢定力弱，單一違規就能翻動 trinity。
   所有違規率附精確二項區間；經驗 c 的 bootstrap band 在 1% 相應很寬（寬到可以含 1）。
   Δc 的「無法拒絕 H₀」同樣是低檢定力下的結果，**不是**純尺度的證明。
2. **單一市場、單一平靜期間**（2023–2024，無空頭）。外部效度未測 → E2 / E5 仍為必要。
3. **HAR 用 TX（TAIEX 期貨）的 RV 去打 0050（台灣 50 ETF，台積電權重遠高）。** 即使 RV 建構完美，
   兩者仍是**不同標的**：成分與基差錯配是**設計上就存在的**。
   **本實驗不能用來宣稱「HAR-RV 不如 GARCH」** —— 它談的是 **cross-asset RV plug-in**。
4. **報酬用 simple pct_change（股利調整後收盤），RV 用 log return** — 日頻下差異是二階項，但不為零。
5. **5% 的 Basel 燈號是自訂 α-scaled 延伸**，不是監理標準。
6. **樣本內數字沒有任何預測力宣稱**，只用於 IS/OOS 對照。
7. **殘差池窗口是第三個通道**，本實驗只當診斷報告（§7 + `sens_burnin_tailpool`），未做完整通道分解。
8. **continuity gate 丟掉的 9 天**都落在訓練期；它們仍會讓 GARCH recursion 把相鄰兩列當成連續交易日
   （報酬與 RV 視窗本身仍然對齊，見 `trading_calendar_audit`）。
9. **尺度因子與 Δc 的 uncertainty 使用 iid resampling**，沒有保留序列依賴；E2 必須補 block-bootstrap
   sensitivity，不能把這裡的 band 當成跨制度的精確區間。
10. **0050 r² 的 aligned QLIKE 排除 14 個零報酬日**（log loss 在恰為 0 的 proxy 上未定義），因此
    aligned DM n = 436，少於 TX-RV DM 的 450。
11. **`RGL` 是 reduced-form log-GARCH-X comparator**（return likelihood + lagged log RV），不是含完整
    measurement equation 的 Realized-GARCH system；它不進 `decide_gate()`，不可拿來做完整 RGL 主張。

---

## 11. 資料來源（Data provenance）

| 來源 | 內容 | Snapshot |
|---|---|---|
| TAIFEX TX tick（`~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_*TX.csv`，**全合約**） | 2,213 個交易日；每日視窗內成交量最大的 active contract（平均成交量佔比 **95.15%**，108 個換月日）；連續 5-min path 13:30(D−1)→13:30(D) | `data/tx_rv_active_c2c_5min_2017_2025.csv` |
| 同上（R1/K854 建構，僅供對照） | TX1 檔、三 session 分開加總、日盤到 13:45 | `data/tx_rv_5min_daily_2017_2025.csv` |
| yfinance `0050.TW` | 調整後收盤（`auto_adjust=True`） | `data/tw0050_adjclose_2016_2025.csv` |

**為什麼 `auto_adjust=True`**（與專案偏好的 `False` 不同）：為精確複製 K854 的 baseline 報酬。
以 K854 published 的 OOS 動差當指紋反推 — 本次 OOS std = **0.0127988916**、kurt = **8.1145711**
（K854: 0.0127988873 / 8.114549，**吻合到小數第 7 位**）。

**K854 逐格比對**（診斷，**不是** replication gate）：primary run 只有 **36%** 的格子違規數與 K854 相同 ——
**本來就不該相同**（RV 換了、GJR 從 4 starts 換成 100 starts、Kupiec/Christoffersen 邊界修了）。
把 RV 換回 K854 的建構（`sens_legacy_rv`）後回到 **71%**。

---

## 12. 復現

```bash
uv run --extra dev python experiments/k1684/k1684_ftd_e1_scale_gating.py
```

首跑會從 ~2,300 個 tick 檔重建 RV 並 pin 成 snapshot（需數分鐘）；cached snapshot 後每跑約 **85 秒**。
Seed = `20260712`。Lookahead audit 或 RV 資訊集稽核失敗時腳本 `raise`，**不會**輸出結果。
結果 JSON 為**原子寫入**（tmp → `json.load` 驗證 → `os.replace`）。

**圖**：
- `fig1_implied_c_by_alpha.png` — 經驗尺度因子跨 α（bootstrap band）+ Δc 的 bootstrap 檢定（取代硬編門檻）
- `fig2_trinity_before_after.png` — 校正前後 trinity（Basel 燈號 + trinity 斜線標記）
- `fig3_scale_factors.png` — RV 重建補回了什麼 ｜ 三個校正因子 + placebo ｜ GJR basin 脆弱性（4 vs 100 starts）

---

## 13. 這份結果**不可以**被用來宣稱什麼

- ❌ 不可宣稱「H2 被推翻」「divergence 是純尺度假象」→ 腿 1 在 Harvey 門檻下**兩個方向都不顯著**。
- ❌ 不可宣稱「HAR-RV 不如 GJR」→ 本實驗的 HAR 打的是**別的標的**的 RV（§10.3）。
- ❌ 不可宣稱「校正機器只動錯配的模型」→ placebo 也把正確對齊的 GJR 放大 12%（CI 與 HAR 重疊）。
- ❌ 不可宣稱「純尺度已被證實」→ Δc 檢定只是**無法拒絕** H₀，且 1% 的 band 很寬。
- ❌ 不可據此選 FRL / IJF 任何一條路線 → 裁決是 **H2_UNSUPPORTED**，需要 E2 先跑。
- ✅ 可以（本次 primary Codex review CONDITIONAL_PASS 後）記錄的**null 與方法論教訓**：
  1. session 分段加總的 realized measure 會系統性少掉 boundary jump（此處 **24%**）；
  2. 4-start GARCH MLE 在多峰似然面上幾乎抓不到 MLE（100 starts 中僅 **1.5%** 命中最佳 basin）；
  3. `Φ⁻¹(α)/Φ⁻¹(π̂)` 只在 Normal 下可識別，且**對 π 遞增**（R1 把 CI 上下界寫反）；
  4. 零違規時 Kupiec 回 p = 1.0（以及 t11 = 0 時 Christoffersen 回 p = 1.0）是**實作 bug**，
     會讓過度保守 / 反群聚的 VaR 拿到 trinity PASS；
  5. 只在 63 天更新一次的階梯參數，**不能**當成 450 個 iid 日值去 bootstrap；
  6. **placebo 的估計窗必須與待測對象對稱** —— 不對稱時 placebo 的 CI 會虛胖／虛瘦，結論會反轉。
