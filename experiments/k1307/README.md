# K1307 — 台灣 5-min 數據 HAR-RV（0050.TW）研究包與樣本門檻診斷

**Status**: Scaffold + local data-readiness diagnostic  
**Date**: 2026-05-25  
**Seed**: 42

## 動機

`research_program.md` 把「台灣 5-min 數據 HAR-RV（0050.TW）」列為 TW 線的開放議題。這題不是從零開始：

- `paper/taiwan-vt/experiments/k848_taifex_5min_rv.py` 已建立台灣 5 分鐘 RV 的基礎管線。
- `paper/taiwan-vt/experiments/k850_har_rv_var_taiwan.py`、`k852_realized_garch.py` 已把 TAIFEX 5 分鐘 RV 用在台灣風險預測比較。
- `experiments/k1318/` 已做過 SPY / 0050.TW 的 5 分鐘 RV HAR pilot，明確得到一個誠實結論：**方法可以做，但 0050.TW 樣本還太短，不能把 NULL 誤讀成模型失敗。**

因此 K1307 的角色不是重做 K1318，而是把 0050.TW 這條線正式整理成一個可持續續跑的研究包，並明確記錄目前資料是否已達可檢定門檻。

## 研究問題

當 0050.TW 的 5 分鐘 realized variance 樣本逐步累積後，使用真實 5 分鐘 RV 建立的 HAR-RV，是否能在台灣市場的波動率預測上，穩定優於日頻 proxy（如 `|r|`、`r²`、EWMA）？

## 與既有實驗的差異化

1. `K1318` 是 pilot，比較 SPY 與 0050.TW，重點是方法 sanity check。
2. `K1307` 聚焦 **台灣單一資產 0050.TW**，明確做成本地研究包與 readiness gate。
3. K1307 不宣稱新實證結果；它先固定資料來源、樣本門檻、lookahead 規範與續跑條件，避免之後每次重複設計。

## 相關先驗知識

- `K1318`：0050.TW 實際 5 分鐘 RV pilot 在極小樣本下得到 NULL，主要原因是 OOS 只有個位數。
- `K848/K850/K852`：台灣 5 分鐘 RV 管線與 HAR / Realized GARCH / VaR 比較已證明可行。
- `storage/memory/knowledge.json` 既有知識指出：**HAR-RV with 5-min RV needs 500+ days for stable estimation**，短樣本容易出現係數不穩與過度擬合。

## 資料來源

- `data/intraday/0050_TW_daily_rv.csv`
  - 由本地 0050.TW 5 分鐘 bars 聚合而成的日 realized variance 序列
- `data/intraday/SPY_daily_rv.csv`
  - 僅作跨市場 coverage 對照，不是本題主角
- `src/volpred/utils.py::clean_tw50_data`
  - 0050.TW 日線若未來拿來建 proxy，必須沿用既有 split artifact 修正

## 方法設計

本研究包目前只做 **樣本門檻診斷**，不在這一輪強行回測。

若後續正式執行，預設方法為：

1. 載入 `0050_TW_daily_rv.csv`
2. 以 `RV[t-1]`、`mean(RV[t-5:t-1])`、`mean(RV[t-22:t-1])` 建立 HAR-RV 特徵
3. 以 expanding-window OLS 預測 `RV[t]`
4. 與日頻 proxy 基準（HAR-ABS / HAR-SQ / EWMA）做公平比較
5. 用 QLIKE 與 DM-HLN / Harvey 門檻評估

## Lookahead 防呆

- **硬規則**：`signal from t-1, return/target at t`
- HAR-RV 特徵必須明確使用：
  - `rv.shift(1)`
  - `rv.shift(1).rolling(5).mean()`
  - `rv.shift(1).rolling(22).mean()`
- 禁止把同日 RV 當成同日預測因子

## 當前診斷目標

這一輪只回答三件事：

1. 本地 0050.TW 5 分鐘 RV 目前累積到幾個非空交易日？
2. 扣掉 HAR-22 與最小訓練窗後，實際可產生多少個 OOS 預測？
3. 是否已達到「可做有力統計推論」的最低樣本門檻？

## 成功標準

1. 建立完整 `experiments/k1307/` 三件套
2. 結果 JSON 要寫出本地資料覆蓋範圍與可訓練樣本數
3. 明確區分：
   - `scaffold / diagnostic`
   - `executed experiment`
4. 若樣本不足，要誠實回報 `NOT_READY_SAMPLE_TOO_SHORT`

## 預期後續

- 當 0050.TW 非空 RV 樣本累積到約 `>= 100` 時，可先做中期更新
- 當 `>= 252` 時，才進入正式單資產 OOS 檢定版本
- 若要寫知識庫正式條目，至少需達到 `CONDITIONAL_PASS` 的方法學驗證或更完整 OOS 證據
