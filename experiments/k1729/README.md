# K1729：自有 TAIFEX tick（5 分鐘 RV）相對「純日頻資訊」的預測增益

- **Proposer / Executor**: Claude（dispatch task `research_taifex_intraday_rv_line`）
- **Date**: 2026-07-17
- **Runtime**: ~2 s（全樣本 rolling OLS）
- **Random seed**: 42
- **Verdict**: **`HAR_RV5_WINS_ROBUST_ACROSS_PROXIES`**（= PASS）
- **Reviewer**: Codex（gpt-5.6-sol，pre-run review，1–5 項全 PASS + 3 項限制，已全數落地）

## 1. 研究問題與經濟動機

老闆 2026-07-14 裁決：以自有 TAIFEX tick 取代付費 US intraday 資料線。這條線要不要
長期維護，取決於一個可檢定的問題：

> **對 TX 隔日「日盤」波動率預測，用 5 分鐘 intraday RV 當 regressor 的 HAR，
> 是否顯著優於只用「日頻可得資訊」（日盤 open-to-close 報酬平方）的同構 HAR？**

這個題目的設計重點是 **NULL 也有價值**：若 intraday 打不贏 daily，這條資料線的
維護成本無法由預測增益 justify，「不做 intraday」就是有依據的省錢決策。本實驗
事前就接受任一方向的結果。

**實際結果是 PASS（intraday 顯著有增益），所以結論是這條線值得維護。**

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

為什麼必須明寫：上游 `pick_active_contract()` 用每個檔案的**總量（日盤＋夜盤）**
選當日主力合約，而 TAIFEX 日檔的夜盤 tick 帶當晚日期 —— 所以第 t-1 日的選約
嵌入了「到第 t 日 05:00 為止」的成交量。在 08:45 origin 下這些 tick 全部已 realized、
可觀察，選約合法進入資訊集；**若把 origin 定在 t-1 日 13:45 收盤，它就會是
economic-clock lookahead**。08:45 origin 也是實務上最自然的（開盤前做當日預測），
且與既有慣例 `feedback_session_boundary_forecast_timing` 一致。

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

Filter 觸發率不對稱是**模型行為差異，不是程式偏袒**（規則同一份）。Codex 另做了
不套 filter 的敏感度檢查：兩個 target 的方向與 DM 判讀都不翻轉 → 顯著性不是 filter 製造的。

loss differential 的 acf(1) 僅 0.072 / −0.054 → 序列相關極弱，HAC bandwidth = 14
的修正影響很小（但仍照用 canonical 實作）。

## 5. 為什麼這個結果「不是好得不像真的」

`+14.70%` 的 QLIKE 改善須主動接受懷疑檢驗（研究誠實原則：結果好得不像真的 = 90% 有 bug）。
支持它為真的四項獨立證據：

1. **與 K853 獨立吻合**：K853 發現 r² 當 proxy 會把 HAR 的優勢**壓縮 4 倍**。
   本實驗完全獨立地測到 14.70% → 3.37% 的壓縮，**比值 4.36 倍** —— 兩個不同實驗、
   不同設計，量級對上。
2. **符合文獻先驗**：Andersen & Bollerslev (1998) 以降，intraday RV 顯著優於
   daily squared return 是 realized volatility 文獻的基本結論。這裡沒有反直覺的宣稱。
3. **Codex pre-run review 1–5 全 PASS**，且獨立做了 no-filter 敏感度檢查，方向不翻轉。
4. **在偏袒對手的 target 上仍然贏**：若 14.70% 是同源測量誤差造成的假象，
   target B（偏袒 HAR-DAILY）應該翻轉或至少變 NULL。它沒有。

## 6. 樣本（誠實記載）

- 資料：`data/intraday/taifex_5min_rv.csv`（SHA-256 記於 results.json）
- 合約：TX active monthly（`same_day_max_total_volume_monthly_TX`）
- Session：**日盤 08:45–13:45 only**
- 全檔期間：2012-01-02 → 2026-07-16，3,550 個交易日
- **實際 OOS ledger：2016-01-20 → 2026-07-16**（前 1,000 列供 rolling window warmup，
  即 in-sample 2012–2016 / OOS 2016–2026）。**全檔 3,550 天不等於檢定樣本 2,548 天。**
- **排除**：
  - `rv_5min == 0` **2 天**（2025-04-07、2025-04-10）：open == close、292–481 ticks
    （常態約 30,000），隔日跳空 >2% —— 漲跌停鎖死特徵。**RV=0 是真實市場結果，
    不是資料洞**，但 QLIKE 在 actual=0 無定義，故剔除而非 clip。
  - `day_return == 0` **21 天**（target B 的 ledger，r²=0 → QLIKE 無定義）
  - 258 個日曆缺口 = 國定假日，**非資料洞**（manifest 已驗證，未當缺失處理）

## 7. 結論與對營運決策的意義

**自有 TAIFEX tick 的 5 分鐘 RV，對 TX 隔日日盤波動率預測有統計顯著且跨 proxy 穩健的
增益（QLIKE +14.70%，DM t=−3.681）。這條資料線值得維護。**

同時，**這個結論有明確射程**（Codex review 指出，本 K 接受）：

- 本 K 證明的是「5 分鐘 RV 是否比日頻壓縮資訊更有預測力」。HAR-DAILY 的
  `day_return` 在實作上仍由 collector 從 tick 算出 —— 它的**資訊集**確實是日頻可得的
  （日盤 open/close 在 TAIFEX 免費日結算資料就有），但本實驗**沒有**從外部日頻 feed
  端到端驗證。所以它**不等於**證明「外部廉價日頻資料能逐位元替代現有 tick pipeline」。
- 結果只涵蓋**日盤**，未檢定夜盤，也未涉及選擇權 tick。
- 兩個 target 都是 noisy proxy，都不是 latent integrated variance。無中立第三方 proxy
  （如 Parkinson range）：canonical 5 分鐘 RV 層未存 session high/low，
  TWII 現貨 OHLC 是不同資產（basis 問題），不乾淨。

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
