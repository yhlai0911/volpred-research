# 我們把 CPI 發布日抓錯 7 次：MOVE/VIX 事件研究更正

先把錯誤說清楚。這篇文章原先使用 29 個 CPI 事件日，其中 7 個日期不符合官方發布紀錄，還多算了一場沒有發布的事件。日期改由 ALFRED 的 BLS CPI release calendar 讀取後，樣本從 29 場降為 28 場。

日期錯了，舊文章裡「CPI 前一週已提前消化」、「CPI 後 VIX 上升反映 Fed 路徑重估」以及「進場節奏應往前挪」都失去證據基礎。我們在此撤回三項說法，並以官方日期重算全文。

## 哪些日期有誤

錯誤集中在 2025 年 10 月到 2026 年 5 月。2025 年秋季的政府停擺改變或取消了部分發布時程，固定用每月預估日期會抓錯。

| 舊日期 | 官方日期 |
|---|---|
| 2025-10-15 | 2025-10-24 |
| 2025-11-13 | 無該場發布 |
| 2025-12-10 | 2025-12-18 |
| 2026-01-14 | 2026-01-13 |
| 2026-02-11 | 2026-02-13 |
| 2026-03-12 | 2026-03-11 |
| 2026-05-13 | 2026-05-12 |

![舊日期與官方日期的逐筆稽核](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1442_corrected_lazypack_date_audit_20260712.png)

## 同一套舊視窗，數字已經改變

先沿用舊文的視窗，只替換事件日，方便看出日期錯置造成多少差異。`T-5 收盤到 T0 收盤` 包含發布日反應，因此不能再稱為「公布前 5 日」。

| 指標 | 舊結果（錯誤日期） | 官方日期重算 |
|---|---:|---:|
| 事件數 | 29 | 28 |
| MOVE，T-5 收盤至 T0 收盤平均 | -3.25% | -5.20% |
| VIX，T-5 收盤至 T0 收盤平均 | -1.81% | -2.95% |
| MOVE，T0 至 T+5 平均 | -0.39% | -0.12% |
| VIX，T0 至 T+5 平均 | +5.35% | +4.51% |

舊文把 `T-5 至 T0` 寫成純粹的事前視窗，這也是方法上的錯誤。T0 收盤已經包含美東時間上午 8:30 公布後的交易反應，無法用來證明市場在發布前提前消化。

## 改用互不重疊的三段視窗

重算將每日收盤資料切成三段：

- 純發布前五日：T-6 收盤到 T-1 收盤，共 5 個報酬。
- 發布日：T-1 收盤到 T0 收盤，涵蓋當日反應。
- 發布後五日：T0 收盤到 T+5 收盤。

2024 年 1 月至 2026 年 5 月的 28 場官方發布日中，純發布前五日平均變化為 MOVE -2.53%、VIX -1.60%。發布後五日平均為 MOVE -0.12%、VIX +4.51%。前後五日的配對檢定與 97.5% bootstrap 信賴區間都沒有支持穩健差異。

發布日當天另有一個較明確的樣本現象：

| 發布日 T-1 至 T0 | MOVE | VIX |
|---|---:|---:|
| 平均變化 | -3.45% | -2.06% |
| 中位數 | -4.28% | -2.46% |
| 下跌場數 | 22 / 28 | 20 / 28 |
| 單尾 Wilcoxon p 值 | 0.00024 | 0.01237 |
| 平均值 97.5% bootstrap CI | [-5.47%, -1.35%] | [-4.89%, +1.19%] |

我們事先把 MOVE 與 VIX 視為同一組兩項檢定，Bonferroni 門檻是 0.025。MOVE 的符號檢定、Wilcoxon 檢定與 bootstrap 區間方向一致，通過完整門檻；VIX 的 bootstrap 區間仍跨過零，因此未通過完整門檻。

這是「CPI 官方發布日收盤變化」的描述性關聯。研究沒有非事件日對照、CPI surprise 變數或盤中 8:30 前後的高頻資料，不能把跌幅歸因於 CPI，也不能推出可交易策略。

![官方 CPI 日期下的 MOVE 與 VIX 事件視窗](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1442_corrected_event_windows_20260712.png)

## MOVE/VIX 比值還可以怎麼看

2026 年 6 月 9 日收盤，MOVE 為 77.03、VIX 為 19.87，MOVE/VIX 比值 3.88，位於 2003 年以來第 26 百分位。這個排名只說明當天比值在自身歷史分布中的位置，不能單憑 P26 判定 MOVE 便宜、VIX 昂貴或任何一邊錯價。

![MOVE/VIX 比值的歷史位置](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1442_corrected_ratio_20260712.png)

## 本次更正後的結論

- 舊研究使用的 29 個日期有 7 個錯置，官方樣本為 28 場。
- 舊文的事前視窗包含發布日，不能支持「提前消化」。
- MOVE 在這 28 個發布日的收盤變化呈現穩健下跌關聯；VIX 沒有通過完整保守門檻。
- 發布後五日的 MOVE 與 VIX 結果都是探索性樣本描述，沒有 CPI 專屬因果解釋。
- 原文的 Fed 路徑機制與交易時點建議一併撤回。

## 資料、限制與可重現性

事件日來自 [ALFRED 的 BLS CPI release calendar](https://alfred.stlouisfed.org/release?rid=10)，並以 [BLS 官方發布時程](https://www.bls.gov/schedule/news_release/cpi.htm)交叉核對。市場資料為 yfinance `^MOVE` 與 `^VIX` 的未調整收盤價，期間 2003-01-02 至 2026-06-09，共 5,794 個交易日。市場資料已固定為帶 SHA-256 的快照；官方日期無法取得時，程式會直接中止，不再退回手寫日期。

每日收盤視窗無法識別上午 8:30 後的盤中跳動，也沒有排除 FOMC、NFP、PPI 或其他同期消息。結果只適用於 2024 年 1 月至 2026 年 5 月這 28 場事件。

完整代碼、舊版封存檔、官方日期事件表、固定市場快照與重算結果收在實驗 K1442。

## 懶人包圖組

![日期稽核：29 場舊樣本如何改為 28 場官方樣本](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1442_corrected_lazypack_date_audit_20260712.png)

![更正後結果：MOVE 通過門檻，VIX 未通過完整門檻](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1442_corrected_lazypack_results_20260712.png)

---

**更正日期**：2026-07-12
**實驗 ID**：K1442
**揭露**：[提出: Codex, 執行: Codex]
