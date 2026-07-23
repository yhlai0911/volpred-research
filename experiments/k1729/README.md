# K1729：自有 TAIFEX tick（5 分鐘 RV）相對「純日頻資訊」的預測增益

- **Proposer / Executor**: Claude（dispatch task `research_taifex_intraday_rv_line`）
- **Date**: 2026-07-17
- **Runtime**: ~2 s（全樣本 rolling OLS）
- **Random seed**: 42
- **Verdict**: **`HAR_RV5_WINS_ROBUST_ACROSS_PROXIES`**
- **Data as-of**: `2026-07-16`（canonical CSV 每日增列，腳本內以 `DATA_AS_OF` 釘住；
  復現對照 `data.analysis_slice_sha256`，不是會天天變的整檔 sha）
- **Review 狀態**: rev1 於 2026-07-17 被 Codex 二審判 **FAIL**（target 端 ex-post 選約 lookahead
  未揭露）。本版為 rev2 修復版，裁決檔以 `review_verdict.json` 為準——README 不自稱審查結果。

## 1. 研究問題與經濟動機

老闆 2026-07-14 裁決：以自有 TAIFEX tick 取代付費 US intraday 資料線。這條線要不要
長期維護，取決於一個可檢定的問題：

> **對 TX 隔日「日盤」波動率預測，用 5 分鐘 intraday RV 當 regressor 的 HAR，
> 是否顯著優於只用「日頻可得資訊」（日盤 open-to-close 報酬平方）的同構 HAR？**

這個題目的設計重點是 **NULL 也有價值**：若 intraday 打不贏 daily，這條資料線的
維護成本無法由預測增益 justify，「不做 intraday」就是有依據的省錢決策。本實驗
事前就接受任一方向的結果。

**實際結果：intraday 顯著有增益**（射程見 §7 —— 修復後的營運結論比 rev1 窄）。

## 2. 與庫內既有 K 的差異化（派工前完成查重）

Dispatch brief 原案的三個方向，查重後有兩個必須改（詳見 `PLANNED_K_BRIEFS.md`）：

| K | 測什麼 | 與本 K 的關係 |
|---|--------|---------------|
| K868 / K884 | HAR 日夜分解（夜盤 RV 當 regressor） | **原案 (b) 已被做過兩次，皆 NULL** → 不重做 |
| K1301 / K1303 / K1309 | TX1 上的 semivariance / jump / BMA 分解 | 皆 NULL，K1303 明寫「Standard HAR-RV is near-sufficient」 |
| K1704 | daily proxies 當 **target** 測 model ranking 穩健性 | 本 K 把 daily 資訊放在 **regressor 側**，是不同問題 |
| K1661 | daily-OHLC 上的 HARQ 測量誤差加權 | 測 HARQ spec，非 intraday-vs-daily 資訊集 |
| K853 | Proxy ceiling：r² 壓縮 HAR 對 GJR 的優勢 4 倍 | **本 K 獨立重現了這個 4 倍壓縮**（見 §5） |

**本 K 的增量**：庫內從未在 TX 上直接比較「intraday regressor vs daily-only
regressor」的資訊集價值。這正是老闆那個裁決要回答的成本問題。

## 3. 方法

### 模型（刻意對稱，不對任一方調參）

```
HAR-RV5   :  y_t ~ b0 + bd*RV5_{t-1} + bw*mean(RV5_{t-5..t-1}) + bm*mean(RV5_{t-22..t-1})
HAR-DAILY :  y_t ~ b0 + bd*r2_{t-1}  + bw*mean(r2_{t-5..t-1})  + bm*mean(r2_{t-22..t-1})
```

同 HAR(d/w/m) spec、同 rolling window（1000 列）、同 refit cadence（逐 origin）、
同 insanity filter、同 ledger。**唯一差別是 regressor 建自 5 分鐘 intraday RV
還是日盤 open-to-close 報酬平方**。兩邊都沒有 hyperparameter 被調過。

### 雙 target — 對抗「同源 proxy 偏袒」

target 選擇本身會偏袒，這是本實驗最關鍵的設計：

| Target | 與誰同源測量誤差 | 偏袒誰 |
|--------|------------------|--------|
| A. `rv_5min` | HAR-RV5 的 regressors | **偏袒 HAR-RV5** |
| B. `daily_r2` | HAR-DAILY 的 regressors | **偏袒 HAR-DAILY** |

Patton (2011) 證明 QLIKE 在任何條件不偏 proxy 下給一致 ranking，所以
**兩個 target 一致才是穩健結論**；只有一邊贏就是同源 artifact。兩個 target 都
不被當成真值。這直接繼承 K853 / K1704 的教訓。

### 夜盤斷點與 era 邊界的處理

- **2017-05-16 夜盤斷點**：實測 `rv_5min == rv_day` **恆真**（canonical 5 分鐘 RV
  層只存日盤 08:45–13:45 口徑），程式內有 `assert` 把關。因此本設計**天然不含夜盤**，
  regime change 無從進入樣本 —— 這不是迴避斷點，是讓它不可能污染。
- **2012-06-14 era 邊界（9→10 欄）**：發生在上游 raw→canonical 轉換層，
  由 collector 的 header-based normalization 吸收；本實驗消費的是已正規化的
  日頻 RV 序列，不觸及欄位語義。

### Forecast origin（明定，這是設計合法性的關鍵）

**origin = 第 t 日 08:45 開盤前**，預測當日 08:45–13:45 的 RV。

**regressor 側（合法）**：上游 `pick_active_contract()` 用每個檔案的**總量（日盤＋夜盤）**
選當日主力合約，而 TAIFEX 日檔的夜盤 tick 帶當晚日期 —— 所以第 t-1 日的選約
嵌入了「到第 t 日 05:00 為止」的成交量。在 08:45 origin 下這些 tick 全部已 realized、
可觀察，選約合法進入資訊集；**若把 origin 定在 t-1 日 13:45 收盤，它就會是
economic-clock lookahead**。08:45 origin 也是實務上最自然的（開盤前做當日預測），
且與既有慣例 `feedback_session_boundary_forecast_timing` 一致。

### target 側的 ex-post 選約（rev1 的 blocking 缺陷，本版修復）

上面那段只論證了 **regressor** 合法，**沒有論證 target**。同一條總量規則也決定了
`y_t` 是在**哪一口合約**上測量的，而那個總量**包含第 t 日自己的日盤成交量** ——
在 08:45 origin 下尚未發生。所以 `y_t` 的 estimand **一般而言無法事前固定**。
Codex 2026-07-17 判此為 blocking（`review_verdict.json`），且屬**未揭露**而非已 scope 的限制。

**修復方式（不重跑 35.9GB raw tick）**：問一個更銳利的問題 ——
*realized 的選約有多少比例是 08:45 當下就叫得出名字的？*

> **Rule E（事前規則）**：持有近月合約直到它**公告的最後結算日**（合約月第三個星期三；
> 該日非交易日則順延至次一交易日）過了，才換月。
>
> 輸入只有「t-1 日持有的合約」與「公告結算行事曆」，兩者在 08:45 都已知。

- Rule E 命中的日子 → **target 側沒有 lookahead**：事前操作的人會在**完全相同**的合約上測到同一個 `y_t`。
- Rule E 不命中的日子 → 模糊集，**列出並在敏感度 ledger 中剔除**。

**Rule E 不是配適出來的**：另一個同樣自然的寫法（取最近一個「結算日尚未過」的合約）
**與 Rule E 本身**（不只是與 realized 選約）在 **OOS 每一列都一致**。全檔只在
**第 0 列（2012-01-02）**不同 —— 純粹因為檔案在它之前沒有歷史、定位不到 2011-12 的結算日；
該列是 rolling window warmup，從未被評分。所以沒有對著資料在兩個慣例間挑過。

外部審查者獨立重寫兩條規則驗證了這點，並另測第三種**不綁到期日**的慣例
（每個日曆月 1 號換月）——OOS 只對得上 **59.22%**。可見「綁到期日」是自然的規則族，
而**族內選哪一種對結果沒有影響**。

**實測**：OOS 2,550 列中 **2,545 列（99.80%）由 Rule E 事前決定**，模糊集僅
**5 天**（2016-03-16、2016-05-18、2016-08-17、2017-01-18、2017-02-15）——
全是結算日、且成交量已提前一天移往次月。

**誠實界線**：這**不代表** §4 主表的全 ledger 數字本身沒有 ex-post 選約 —— 它有。
**乾淨的是 §4.1 的 ex-ante ledger**；主表是「含 5 天模糊日」的版本，兩者都報。

### 防錯

- **Lookahead**：`har_features()` 明確 `shift(1)`；origin t 的訓練集只含 `[t-1000, t-1]`
  的 (X, y) pairs。Codex 逐行驗證 `rolling(5)`/`rolling(22)` 在 shift 後等價於
  `x[t-5..t-1]` / `x[t-22..t-1]`，不含 `x[t]`。
- **日期完整性**：`assert` 日期唯一且嚴格遞增 —— 否則 `shift(1)` 是「前一列」而非「前一日」。
- **非正值不 clip**：actual ≤ 0 的日子從 ledger 剔除，**不 clip 成極小正數**（K1704 紀律）。
- **DM**：只用 canonical `volpred.stats.model_evaluation.dm_test`（Newey-West，
  bandwidth floor 至 1）。**刻意不用** `evaluation/statistical_tests.diebold_mariano_test`
  —— 它在 h=1 時 `range(1,1)` 為空 → 退化成無 HAC 修正，正是 K1655 的 bug class。
- **Insanity filter**：BPQ (2016)，預測落在 in-sample support 外或 ≤0 → 用 in-sample mean，
  對兩模型規則完全一致。

## 4. 結果

### 主結果（全樣本 OOS）

| Target | n | QLIKE HAR-RV5 | QLIKE HAR-DAILY | 改善 | DM t | p | 判定 |
|--------|---|---------------|------------------|------|------|---|------|
| **A. rv_5min** | 2,548 | **0.190861** | 0.223748 | **+14.70%** | **−3.681** | 0.00024 | HAR_RV5_WINS |
| **B. daily_r2** | 2,536 | **1.394991** | 1.443710 | **+3.37%** | **−3.367** | 0.00077 | HAR_RV5_WINS |

DM 符號：負 t = HAR-RV5 的 QLIKE 較低 = intraday 有幫助。Harvey (2016) 門檻 |t| > 3。

**兩個方向相反偏袒的 proxy 上都贏、都過 Harvey 門檻 → `HAR_RV5_WINS_ROBUST_ACROSS_PROXIES`。**
即使在偏袒對手（HAR-DAILY）的 target B 上，intraday 仍然贏。

### 4.1 敏感度 —— 三條 ledger 全部同向且全部過 Harvey 門檻

全部由 `k1729.py` 產出、數字落在 `k1729_results.json` 的 `results.<target>.sensitivity`，
可從三件套自證（rev1 的 no-filter 宣稱只寫在 README、無法稽核，這是那條的修復）。

| Ledger | 剔除什麼 | target A: n / 改善 / DM t | target B: n / 改善 / DM t |
|---|---|---|---|
| **主表（全 ledger）** | — | 2,548 / +14.70% / **−3.681** | 2,536 / +3.37% / **−3.367** |
| **ex-ante 選約**（本版主修復） | 5 個 Rule E 未命中日 | 2,543 / +14.70% / **−3.671** | 2,531 / +3.39% / **−3.370** |
| **剔除所有換月日**（更保守） | 127 個 `is_roll` 日 | 2,421 / +14.66% / **−3.584** | 2,410 / +3.48% / **−3.665** |
| **關閉 insanity filter** | —（兩模型同時關） | 2,541 / +15.19% / **−3.867** | 2,524 / +3.48% / **−3.456** |

**六格全部 `HAR_RV5_WINS` 且 |t| > 3。** 三件事因此成立：

1. **選約缺陷不是結果的來源** —— 把模糊日全剔掉，t 值只從 −3.681 動到 −3.671。
2. 連「剔掉全部 127 個換月日」這種遠比必要更狠的切法都不翻轉。
3. filter 是**壓低**而非製造顯著性（關掉後 |t| 反而升到 3.867 / 3.456）。

**ex-ante ledger 的殘餘限制（必須誠實記）**：以「該日選約是否合乎行事曆」篩樣本，
本身用到 08:45 當下不知道的資訊，所以它的 estimand 是**條件式**的
（「選約合乎行事曆的日子上的期望損失差」），不是無條件的。這個篩選
**與模型無關**（不碰預測、不碰損失，兩模型共用同一組日子），因此不可能偏袒任一方，
但它是條件式宣稱，就照條件式報。

### 子樣本（2017-05-16 起，對照 K1301/K1303 的 TX1 ledger）

| Target | n | 改善 | DM t | p | 判定 |
|--------|---|------|------|---|------|
| A. rv_5min | 2,231 | +13.81% | −3.067 | 0.0022 | HAR_RV5_WINS |
| B. daily_r2 | 2,222 | +3.37% | **−2.921** | 0.0035 | **NULL** |

**誠實揭露**：子樣本的 target B **未過 Harvey |t|>3**（|t|=2.92），儘管 p=0.0035 < 0.05。
QLIKE 改善幅度與全樣本完全相同（3.37%），下降的是 n（2,536→2,222）帶來的 power，
不是效果消失。但按本 repo 的 Harvey 紀律，這一格判 NULL，**不升格**。
主結論以全樣本為準。

### 診斷

| | n_forecasts | insanity filter 觸發 | 有效訓練 obs |
|---|---|---|---|
| HAR-RV5 | 2,550 | 7–12 (0.27–0.47%) | 972–1,000 |
| HAR-DAILY | 2,550 | 0 (0.00%) | 972–1,000 |

Filter 觸發率不對稱是**模型行為差異，不是程式偏袒**（規則同一份）。不套 filter 的
敏感度已收進 `k1729.py`（見 §4.1 第四列），數字寫進 `results.json`，可從三件套自證。

loss differential 的 acf(1) 僅 0.072 / −0.054 → 序列相關極弱，HAC bandwidth = 14
的修正影響很小（但仍照用 canonical 實作）。

### 非巢套（nested-DM gate 的裁決依據）

兩個模型的 regressor 集合**互斥**（`RV5_{d,w,m}` vs `r2_{d,w,m}`），
**任一方都不是另一方的參數受限特例** —— 沒有任何把係數設 0 或設相等的方式能從
HAR-RV5 還原出 HAR-DAILY。DM 正是為非巢套比較設計的；Clark-West 是巢套用的。

巢套下 raw DM 失效的機制是「虛無下兩個預測**重合** → loss differential 恆為 0 →
變異數退化」。本設計不可能發生，並且**可從 results.json 直接驗證**：

| | target A | target B |
|---|---|---|
| 兩模型預測相關係數 | 0.778 | 0.791 |
| 平均相對預測差距 | 20.6% | 17.7% |
| loss differential 標準差 | 0.364 | 0.713 |
| loss differential 恰為 0 的比例 | 0.0% | 0.0% |

裁決記於 `storage/ops/nested_dm_misuse_baseline.json` 的 `reviewed_nonnested`
（與 K1049 / k1100b 同一條退場路徑，非自造後門）。

## 5. 為什麼這個結果「不是好得不像真的」

`+14.70%` 的 QLIKE 改善須主動接受懷疑檢驗（研究誠實原則：結果好得不像真的 = 90% 有 bug）。
支持它為真的四項獨立證據：

1. **與 K853 獨立吻合**：K853 發現 r² 當 proxy 會把 HAR 的優勢**壓縮 4 倍**。
   本實驗完全獨立地測到 14.70% → 3.37% 的壓縮，**比值 4.36 倍** —— 兩個不同實驗、
   不同設計，量級對上。
2. **符合文獻先驗**：Andersen & Bollerslev (1998) 以降，intraday RV 顯著優於
   daily squared return 是 realized volatility 文獻的基本結論。這裡沒有反直覺的宣稱。
3. **四條 ledger 都不翻轉**（§4.1）：剔除選約模糊日、剔除全部換月日、關閉 insanity
   filter，六格全部維持 `HAR_RV5_WINS` 且 |t| > 3。
4. **在偏袒對手的 target 上仍然贏**：若 14.70% 是同源測量誤差造成的假象，
   target B（偏袒 HAR-DAILY）應該翻轉或至少變 NULL。它沒有。

**不算證據的東西（rev1 誤列，此處更正）**：rev1 把「Codex pre-run review 1–5 全 PASS」
列為支持證據。那是**凍結前**的預審，不是 final audit —— 它沒看到凍結後的 claim surface，
**不能拿來取代裁決**。實際的凍結後 final audit（2026-07-17）判的是 **FAIL**。
最終審查結果一律以 `review_verdict.json` 為準。

## 6. 樣本（誠實記載）

- 資料：`data/intraday/taifex_5min_rv.csv`，**as-of `2026-07-16`**（腳本內 `DATA_AS_OF` 釘住）
  - collector **每個交易日增列一列**，整檔 sha256 隔天就對不上 —— 所以復現對照的是
    `data.analysis_slice_sha256`（截斷後切片的 hash，穩定），整檔 sha 只當 provenance 記錄
- 合約：TX active monthly（`same_day_max_total_volume_monthly_TX`；**選約的 ex-post 性質見 §3**）
- Session：**日盤 08:45–13:45 only**
- 全檔期間：2012-01-02 → 2026-07-16，3,550 個交易日
- **實際 OOS ledger：2016-01-20 → 2026-07-16**（前 1,000 列供 rolling window warmup，
  即 in-sample 2012–2016 / OOS 2016–2026）。**全檔 3,550 天不等於檢定樣本 2,548 天。**
- **排除**（**全檔筆數 ≠ 真正扣掉 ledger 列的筆數** —— 第 1,000 列以前是 rolling window
  warmup，從來沒進過任何 ledger。rev1 只報全檔數，這裡分開報）：

  | 排除項 | 全檔 | **實際扣掉 OOS ledger 列** |
  |---|---|---|
  | `rv_5min == 0`（target A） | 2 | **2** |
  | `day_return == 0`（target B） | 21 | **14** |

  - `rv_5min == 0`（2025-04-07、2025-04-10）：open == close、292–481 ticks
    （常態約 30,000），隔日跳空 >2% —— 漲跌停鎖死特徵。**RV=0 是真實市場結果，
    不是資料洞**，但 QLIKE 在 actual=0 無定義，故剔除而非 clip。
  - `day_return == 0`：r²=0 → QLIKE 無定義。21 天中有 7 天落在 OOS 起點之前，
    只有 **14 天**真的讓 target B 的 ledger 從 2,550 掉到 2,536。
  - 258 個日曆缺口 = 國定假日，**非資料洞**（manifest 已驗證，未當缺失處理）

## 7. 結論與對營運決策的意義

**在 08:45 開盤前形成當日日盤變異數預測這個設定下，5 分鐘 RV 建的 HAR 顯著優於
只用日頻 open-to-close 報酬平方建的同構 HAR：兩個方向相反偏袒的 proxy 上都贏，
且在剔除選約模糊日的 ex-ante ledger 上仍然贏（+14.70% / t=−3.671；+3.39% / t=−3.370）。**

**這對營運決策的意義，以及它撐不起什麼**：

- ✅ **撐得起**：在**預測增益**這一個維度上，5 分鐘 RV 對日頻壓縮資訊有可檢定的增量。
  「這條線在預測上等於沒用、可以直接關掉」這個假說被資料**拒絕**了。
- ⚠️ **撐不起「這條線值得維護」這個結論本身**（rev1 這樣寫，超出證據，此處收回）。
  「值得維護」是**成本效益**判斷，需要維護成本、替代方案成本、以及增益的**經濟價值**
  三個量 —— 本實驗**一個都沒有測**。QLIKE 改善 14.70% 沒有被換算成任何 P&L、
  避險效率或風險管理績效。**統計顯著 ≠ 值得付錢。**
- 📌 **正確的讀法**：本 K 把「預測增益是否為零」從成本討論中**移除**（答案：不為零），
  讓後續的成本效益分析可以在一個已確立的事實上進行 —— 它**不是**那個分析本身。

其餘射程限制：

- 本 K 證明的是「5 分鐘 RV 是否比日頻壓縮資訊更有預測力」。HAR-DAILY 的
  `day_return` 在實作上仍由 collector 從 tick 算出 —— 它的**資訊集**確實是日頻可得的
  （日盤 open/close 在 TAIFEX 免費日結算資料就有），但本實驗**沒有**從外部日頻 feed
  端到端驗證。所以它**不等於**證明「外部廉價日頻資料能逐位元替代現有 tick pipeline」。
- 結果只涵蓋**日盤**，未檢定夜盤，也未涉及選擇權 tick。
- 兩個 target 都是 noisy proxy，都不是 latent integrated variance。無中立第三方 proxy
  （如 Parkinson range）：canonical 5 分鐘 RV 層未存 session high/low，
  TWII 現貨 OHLC 是不同資產（basis 問題），不乾淨。
- **ex-ante ledger 是條件式 estimand**（§4.1 末段）：以「選約是否合乎行事曆」篩樣本
  用到 08:45 當下未知的資訊。篩選與模型無關、兩模型共用同一組日子，故不偏袒任一方，
  但它不是無條件宣稱。
- 子樣本 target B 未過 Harvey 門檻（§4，|t|=2.92），主結論以全樣本為準、不升格。

**對後續題組的意義**：既然 intraday 對日頻預測確有增益，`PLANNED_K_BRIEFS.md` 的
K-C（選擇權 tick）就不是先驗上沒價值的方向 —— 但它的 blocker 是資料
（`OPTIONDATA` 僅同步 1,024/13,093 檔），必須先解 blocker 再談研究。

## 8. 文獻

1. Corsi (2009), *Journal of Financial Econometrics*, 7(2), 174–196. doi:10.1093/jjfinec/nbp001 — HAR baseline
2. Andersen & Bollerslev (1998), *International Economic Review*, 39(4), 885–905. doi:10.2307/2527343 — intraday RV 優於 daily r²
3. Patton (2011), *Journal of Econometrics*, 160(1), 246–256. doi:10.1016/j.jeconom.2010.03.034 — QLIKE 在 noisy proxy 下 ranking 一致
4. Hansen & Lunde (2006), *JBES*, 24(2), 127–161. doi:10.1198/073500106000000071 — proxy 選擇對 ranking 的影響
5. Bollerslev, Patton & Quaedvlieg (2016), *Journal of Econometrics*, 192(1), 1–18. doi:10.1016/j.jeconom.2015.10.007 — HARQ、insanity filter
6. Harvey (2016) — |t| > 3 顯著性門檻

## 9. 檔案

- `k1729.py` — 實驗腳本
- `k1729_results.json` — 結果（含 SHA-256、診斷、排除審計）
- `PLANNED_K_BRIEFS.md` — 後續 K 的 brief（含為何 (b)/(c) 原案須改）
