# 0050 split 污染：受害快照分類（2026-07-21 23:3x，slot-1 bb18b5bd）

任務：`k_reruns_0050_snapshot_contaminated_20260719`。本檔記錄本班查證到哪、以及為什麼**還不能開始重跑**。

## 1. 結論先講：不能用 `--csv-scan` 當受害清單的判準

任務單指定的驗證方式是 `uv run python scripts/detect_price_split_breaks.py --csv-scan`。
本班實測那支腳本**會漏報**：

| 檔案 | 2013-12-31 → 2014-01-02 (Close) | ratio | 在 `--csv-scan` 的 🚫 清單裡？ |
|---|---|---|---|
| `experiments/k1406/data/0050.TW.csv` | 37.4124 → 9.3292 | **0.2494** | ❌ **沒有** |
| `experiments/k1411/data/T0050.csv` | 37.4124 → 9.3292 | **0.2494** | ❌ **沒有** |
| `experiments/K1395/data/0050_tw_yfinance_snapshot.csv` | 37.4124 → 9.3292 | 0.2494 | ✅ 有 |
| `experiments/k1671/data/0050_TW.csv` | 37.4124 → 9.3292 | 0.2494 | ✅ 有 |

同樣的數值、同樣的斷點，有的抓得到有的抓不到 → 掃描結果的 19/1279 是**下界，不是清單**。
在偵測器修好之前重跑，會重跑一份不完整的名單，然後以為做完了。
已建單：`detect_price_split_breaks_false_negative_20260721`。

## 2. 已確認**真的污染**（ratio ≈ 0.2485–0.2494，2014-01-02 的 4:1 分割未回溯調整）

由 `--csv-scan` 標出的 10 個 0050 快照：

- `K1395/data/0050_tw_yfinance_snapshot.csv`（`t0050_adj_close`）
- `K1611/data/0050_TW_ohlc_adj.csv`（open/high/low/close）
- `k1630/data/0050TW_snapshot.csv`（Close, AdjClose）
- `k1636/data/0050_tw_ohlcv.csv`（OHLC + Adj Close）
- `k1659/data/0050.TW.csv`（OHLC + Adj Close）
- `k1660/data/0050_TW_2010-01-01_2026-07-01.csv`（close）
- `k1661/data/0050.TW_ohlc.csv`（OHLC）
- `k1671/data/0050_TW.csv`（OHLC + Adj Close）
- `k1697/data/0050.TW.csv`（OHLC + Adj Close）
- `k1711/data/ohlc_0050_TW.csv`（ohlc）

加上本班直接算出、但掃描漏掉的 2 個：

- `k1406/data/0050.TW.csv`
- `k1411/data/T0050.csv`

**合計至少 12 個**（原任務單列 14 個候選）。

## 3. 已確認**乾淨、不必動**

- `paper2_taiwan_indiv_rolling_gamma/data/0050_tw.csv`：2013-12-31 → 2014-01-02 為
  9.3531 → 9.3292，**ratio = 0.9974**，已是分割調整後的序列。原任務單把它列為受害者，**是誤列**。

## 4. k1711 的來源歧義（任務單明列的疑問）：**尚未解答**

`ohlc_0050_TW.csv` 髒、`panel_0050_TW.csv` 的價格欄不是原始價（本班讀到的首欄是 `r2`，
2013-12-31 與 2014-01-02 皆為 0.0000），無法用同一個 ratio 判準比較。
`grep 'ohlc_0050_TW\|panel_0050_TW' experiments/k1711/*.py` **無命中** → 載入點不在該層 .py，
需往 `src/` 或子目錄追。**這題留給重跑任務的執行者，不要跳過**：若進模型的是 panel 而非 ohlc，
k1711 可能根本不必重跑。

## 5. 誤報（掃描標了但不是股價分割，另案處理，勿混入重跑名單）

- `k1360/data/kalshi_*.csv`：`total_open_interest` 未平倉口數翻倍/五倍 —— 是量，不是價
- `k1556/data/prices.csv`、`k1588/data/prices_long.csv`：2018-02-05 `open` 18.44 → 37.32
  —— Volmageddon 當日的真實跳動
- `high_yield_tone` ×2.0083 —— 情緒指數，非價格
- `K1677/px_MARA.csv`（`low` ×1.96）、`px_PLUG.csv`（×0.5056）—— 需個別判斷，非 0050 線

## 6. 下一步（本任務解除 blocked 後）

1. 修好偵測器 → 重跑全掃 → 用**修好後**的清單取代第 2 節
2. 解答第 4 節的 k1711 來源問題
3. 從已修好的 `price_cache.db` 重建各快照，逐一比對重跑前後統計量（年化波動 / 極端日報酬 /
   月度 RV persistence AR(1)），差異大者才是真受害 —— 這步是 heavy compute，走 `compute_queue.py enqueue`

## 7. 偵測器修復收件（2026-07-23）

`detect_price_split_breaks_false_negative_20260721` 已把 CSV 蒐集改為遞迴搜尋
`experiments/**/data/*.csv` 與 `paper/**/data/*.csv`，不再硬編 experiment 到 `data/`
之間只能有一或兩層。回歸測試同時釘住 k1406/k1411 等價 fixture、任意巢狀深度與空掃描
必須 exit 2 的契約。

修復後全掃共掃 1279 個 CSV，命中 19 個候選；其中 2013-12-31 → 2014-01-02
ratio 約 0.25 的 0050 污染快照仍是第 2 節列出的 **12 個**，包含先前漏報的
`k1406/data/0050.TW.csv` 與 `k1411/data/T0050.csv`。其餘 7 個是第 5 節已分流的
非 0050 候選，不能納入 0050 重跑名單。
