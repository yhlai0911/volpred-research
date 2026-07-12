# K1442 — MOVE/VIX 與 CPI 發布日前後的描述性變化（官方日期更正版）

## 更正狀態

本實驗於 2026-07-12 完成回溯更正。舊版把 2024-01 至 2026-05 的 29 個日期寫死在程式裡；對照 BLS／ALFRED 官方發布日後，7 個日期不符，其中 `2025-11-13` 是不存在的事件（2025 年 10 月 CPI 因政府停擺取消）。官方樣本因此是 28 場，不是 29 場。

舊版另把 `T-5 close → T0 close` 稱為「公布前 5 日」，但 CPI 在 T0 早上 08:30 ET 發布，T0 收盤已包含發布日反應。本版將真正的事前、發布日與事後窗口拆開；舊窗口只留作日期更正的同口徑比較。

## 研究問題與證據邊界

1. 2026-06-09 的 MOVE/VIX 比值在自身歷史分布的位置為何？
2. 官方 CPI 發布日前五個交易日、發布日、發布後五個交易日，MOVE 與 VIX 的樣本變化如何？
3. 發布日的下降是否通過預先設定的描述性統計 gate？

這是日頻描述性事件研究，不含 CPI surprise、一般交易日 benchmark、日內 08:30 窄窗或跨事件控制。因此結果不能識別 CPI 的因果效果，也不能支持錯價、機制或交易方向宣稱。

## 資料與可重現性

- 市場資料：yfinance `^MOVE`、`^VIX`，`auto_adjust=False`
- 市場期間：2003-01-02 至 2026-06-09，共 5,794 個共同交易日
- 凍結快照：`k1442_market_close.csv`
- 快照 SHA-256：`8f0ea7c8f94c02c026e107c7739c6605e420bb9044344bb41e504b253f57a4af`
- 事件日期：`from volpred.data.event_dates import cpi_release_dates`
- 日期來源：ALFRED `release_id=10`（BLS Consumer Price Index release calendar），並以 BLS archive 核對停擺延期／取消日期
- 官方事件樣本：2024-01-11 至 2026-05-12，共 28 場
- 研究類型：descriptive event study

舊版已發布產物保留為 immutable audit evidence：

- `k1442_results_legacy_20260609.json`，SHA-256 `f875a0c22472708700b9a6548839eea96808382241c1e093372219aa97c97d76`
- `k1442_cpi_events_legacy_20260609.csv`，SHA-256 `36241b44ca8c581e38f9132aceaa0aa50ecf28ca943a1e5c8e468bef4948e189`

新快照重算舊 29 場逐列數字的最大絕對差為 `4.44e-14`，表示日期更正比較未被資料 vintage 的微小末位修訂混淆。

## 日期稽核

| 舊日期 | 官方處理 |
|---|---|
| 2025-10-15 | 改為 2025-10-24 |
| 2025-11-13 | 移除；該場 CPI 取消 |
| 2025-12-10 | 改為 2025-12-18 |
| 2026-01-14 | 改為 2026-01-13 |
| 2026-02-11 | 改為 2026-02-13 |
| 2026-03-12 | 改為 2026-03-11 |
| 2026-05-13 | 改為 2026-05-12 |

程式要求官方發布日本身必須存在於 MOVE/VIX 共同交易日；缺日會直接 raise，不會平移到下一個交易日。

## 方法

每場事件建立 `T-6..T+5` 交易日窗口：

- true pre：`T-6 close → T-1 close`，五個 close-to-close returns
- release day：`T-1 close → T0 close`
- post：`T0 close → T+5 close`，五個 returns
- legacy-comparable：`T-5 close → T0 close`，只用來隔離日期更正，不再稱作「公布前」

Primary family 是 MOVE、VIX 發布日變化是否小於 0。每個資產同時報告：

- one-sided Wilcoxon signed-rank test
- one-sided sign test
- 5,000 次固定 seed bootstrap mean CI
- 兩資產 Bonferroni 校正後 `α=0.025`，對應 97.5% CI

`robust_decline=true` 必須 Wilcoxon `p<0.025` 且 bootstrap CI 上界小於 0。發布後五日與 true-pre 對 post 的比較均為 exploratory，不形成獨立 headline；±5 日窗口未排除鄰近 FOMC、NFP、PPI 等事件。

## 結果

### 2026-06-09 歷史位置

| 指標 | 數值 |
|---|---:|
| MOVE | 77.03 |
| VIX | 19.87 |
| MOVE/VIX | 3.8767 |
| 2003 年以來百分位 | P26 |
| trailing-1Y 百分位 | P35 |
| 全期中位數 | 4.7805 |

P26 只描述歷史位置，不等於便宜、昂貴或錯價。

### 只更換日期、保留舊窗口

| 指標 | 舊 29 日 | 官方 28 日 |
|---|---:|---:|
| MOVE `T-5→T0` 均值 | -3.25% | -5.20% |
| MOVE `T0→T+5` 均值 | -0.39% | -0.12% |
| VIX `T-5→T0` 均值 | -1.81% | -2.95% |
| VIX `T0→T+5` 均值 | +5.35% | +4.51% |
| MOVE paired p | 0.287 | 0.0386 |
| VIX paired p | 0.211 | 0.200 |

MOVE 的舊窗口 paired p 從 0.287 變成 0.0386，證明原公開文「兩者都遠高於 0.05」不再成立；但這仍不是 primary test，且在多重比較與窗口誤標下不能單獨支撐方向結論。

### 修正後的等長窗口

| 視窗 | MOVE 均值 | MOVE 中位數 | VIX 均值 | VIX 中位數 |
|---|---:|---:|---:|---:|
| `T-6→T-1` true pre | -2.53% | -2.82% | -1.60% | -0.93% |
| `T-1→T0` release day | -3.45% | -4.28% | -2.06% | -2.46% |
| `T0→T+5` post | -0.12% | +0.99% | +4.51% | +1.24% |

### Primary：發布日變化對 0

| 資產 | 負值場次 | Wilcoxon p | Sign p | 97.5% bootstrap mean CI | Gate |
|---|---:|---:|---:|---:|---|
| MOVE | 22/28 (78.6%) | 0.00024 | 0.00186 | [-5.47%, -1.35%] | descriptive decline PASS |
| VIX | 20/28 (71.4%) | 0.01237 | 0.01785 | [-4.89%, +1.19%] | FAIL（CI 跨 0） |

MOVE 在這 28 個官方發布日的日頻樣本呈現穩健負向關聯；VIX 雖然秩檢定低於校正門檻，但 bootstrap CI 跨 0，因此不通過交集 gate。這仍不是「CPI 造成 MOVE 下跌」的因果證據。

### Exploratory：發布後五日

- MOVE 平均 -0.12%，下跌 13/28（46.4%）
- VIX 平均 +4.51%，下跌 12/28（42.9%）
- MOVE 與 VIX 的 97.5% bootstrap CI 都跨 0
- true-pre 對 post 的 paired p：MOVE 0.343、VIX 0.314

這些窗口沒有控制其他宏觀事件，只能視為未調整的樣本描述。

## 結論

1. 舊版日期確實污染結果：7 個日期不符官方日曆，且一個事件根本不存在。
2. 舊版把含發布日的 `T-5→T0` 誤稱為「公布前」，所以「市場提前消化」不由原設計支持。
3. 官方日期下，MOVE 在發布日樣本有穩健負向關聯；VIX 沒有通過同一保守 gate。
4. 發布後五日沒有穩健下降證據。日頻、無 benchmark 的設計不能把這解讀成 CPI 特有的 vol crush，也不能推論 Fed path、錯價或交易策略。

## 限制

- 28 場集中在 2024-2026，屬特定通膨／政策 regime。
- 無 actual-minus-consensus CPI surprise、注意力或 regime interaction。
- 日頻 close-to-close 無法隔離 08:30 ET 後幾分鐘內的反應。
- ±5 日可能重疊其他宏觀消息，未做 clean-event 或 matched-control sensitivity。
- ALFRED release list 可能含系列 revision date；專案 helper 採每月最後一筆 heuristic，本次已另以 BLS archive 核對異常月份。
- `^MOVE` 是 yfinance 的 ICE BofA MOVE Index proxy，可能與 Bloomberg 原值有末位差異。

## 文獻

- Andersen, Bollerslev, Diebold, and Vega (2007), *Real-Time Price Discovery in Global Stock, Bond and Foreign Exchange Markets*, Journal of International Economics 73(2), 251-277. DOI: `10.1016/j.jinteco.2007.02.004`.
- Jones, Lamont, and Lumsdaine (1998), *Macroeconomic News and Bond Market Volatility*, Journal of Financial Economics 47, 315-337. DOI: `10.1016/S0304-405X(97)00047-0`.
- Kroner (2025), *How Markets Process Macro News: The Importance of Investor Attention*, FEDS 2025-022. DOI: `10.17016/FEDS.2025.022`.

## 重跑與驗證

```bash
uv run python experiments/k1442/k1442_move_vix_ratio_cpi.py
uv run pytest -q tests/test_event_dates.py
```

正式 run 會先驗證市場 snapshot、legacy JSON、legacy CSV 的 SHA-256，所有日期與統計完成後再暫存兩張 PNG、CSV、JSON；全部 readback 通過才替換 canonical outputs，results JSON 最後寫入。

同一 inputs 連續兩次重跑的 canonical SHA-256 完全一致：

- `k1442_results.json`: `0baacff94f47116532afea712dafd6aefb7b04eab90753e3deb08a506cbf17f1`
- `k1442_cpi_events.csv`: `2fca82dc5633d24f784fbdc53d76c1f90995cdde0b3ef310c67e2c5f44ef4d03`
- `fig_a_ratio_timeseries.png`: `9b695a489eaeab0dcc03bb7a5fc0a9f3920f7f623d9e6715382c5e0498e58b2a`
- `fig_b_cpi_event_study.png`: `6ecb86984ee7770798b6974ac252d33841832a4db3fbd73b1cb641a21e8ed500`

Pre-run code review 與 claim-evidence review 均為 PASS；helper regression tests 5/5 通過。
