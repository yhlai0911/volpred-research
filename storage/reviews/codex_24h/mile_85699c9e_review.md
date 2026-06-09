# Codex 24h Review

- Article ID: `mile_85699c9e`
- Task ID: `paper_review_mile_85699c9e`
- Reviewed At: `2026-06-09`
- Reviewer: `Codex`
- Verdict: `FAIL`

## Summary

核心數字敘事表面上與 `K465` 結果檔一致：`SPY` 與 `EWT` 各 5 個 OOS 區間，`HAR` 都在 QLIKE 上優於比較模型，`HAR vs GJR` 的 DM t-stat 也確實全為正且極大。但主方法有一個足以阻斷發佈的 lookahead / index-alignment 問題：`HAR` 的 OOS 預測在測試期直接使用當日 `log_range`、`5d`、`21d` 特徵，卻與同日 `parkinson_var` 對比，等於使用了當日 high-low 已知資訊來評估當日波動代理。文章目前把方法講成「用昨天、上週、上月」更與實作不符。

因此，本文目前不能把「10/10 全勝、10/10 全部統計顯著」當成可靠的正式發現。應先修正 K465 OOS 對齊並重跑，再決定文章是否可保留。

## Numeric Verification

- `SPY` 5 段 `HAR vs GJR` DM t-stat：`14.55, 17.06, 8.32, 13.43, 17.30`
- `EWT` 5 段 `HAR vs GJR` DM t-stat：`27.16, 24.85, 27.31, 24.37, 31.70`
- `SPY` 與 `EWT` 的 summary 都是 `har_wins_vs_gjr = 5/5`、`har_wins_vs_ar1 = 5/5`
- 所以文章中的 `10/10` 與「每段都統計上站得住」這兩句，若只看現有結果檔數字，確實有來源支持

來源：
- [experiments/k465/k465_har_range_cross_oos_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k465/k465_har_range_cross_oos_results.json:1)
- [experiments/k465/k465_dm_heatmap.png](/Users/yhlai0911/Desktop/volpred-research/experiments/k465/k465_dm_heatmap.png:1)

## Findings

1. **SEVERITY 1 — HAR OOS 實作有 same-day leakage，核心結論不可採信。**  
   訓練式寫的是 `Y = train['log_range'].values[1:]`、`X = train[cols].values[:-1]`，也就是用 `t` 的特徵預測 `t+1`。但 OOS 卻用 `x_t = test[cols].values[t]` 直接產生 forecast，接著拿它和同日 `actual_var` 比。`test[cols]` 裡的 `log_range` 與 rolling means 都包含當日 high-low；文章敘事卻說是「昨天、上週、上月」。這是方法與敘事雙重不一致，也是實質 lookahead。  
   參考：[k465_har_range_cross_oos.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k465/k465_har_range_cross_oos.py:239), [k465_har_range_cross_oos.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k465/k465_har_range_cross_oos.py:251), [k465_har_range_cross_oos.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k465/k465_har_range_cross_oos.py:477), [k465_har_range_cross_oos.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k465/k465_har_range_cross_oos.py:510)

2. **SEVERITY 2 — 文章把比較對象講成單一「傳統基準模型」，但實驗其實同時對比 AR(1)、GJR、threshold；圖檔還直接是 `har_vs_gjr`。**  
   這種寫法會讓一般讀者以為全文只在比一個模糊 baseline，弱化了方法細節，也讓 `10/10` 指的到底是勝過誰不夠清楚。若要保留 general audience 寫法，至少要明說主要圖是 `HAR vs GJR`，而 robust 判準還看了 `AR(1)` 與 threshold。  
   參考：[experiments/k465/k465_har_range_cross_oos_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k465/k465_har_range_cross_oos_results.json:26)

3. **SEVERITY 2 — 實驗三件套不完整。**  
   `experiments/k465/README.md` 仍是 planning stub，沒有正式方法、資料、結果、局限；這不符合專案對實驗三件套的要求。  
   參考：[README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k465/README.md:1)

4. **SEVERITY 3 — Script 的輸出路徑與目錄結構不一致，削弱可重現性。**  
   程式最後寫入的是 `experiments/k465_har_range_cross_oos_results.json`，不是 `experiments/k465/k465_har_range_cross_oos_results.json`。目前資料夾內有正確位置的檔案，但從 script 本身看不出這是如何產生的。  
   參考：[k465_har_range_cross_oos.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k465/k465_har_range_cross_oos.py:693)

5. **SEVERITY 3 — Published feed artifact 缺 single-file report JSON。**  
   本篇在 `feed.json` 有 published entry，但缺 `storage/reports/mile_85699c9e.json`，不利 audit / downstream sync。這不是本文方法學本體問題，但屬 publish pipeline completeness issue。

## Lookahead Audit

- `AR(1)` OOS 寫法是用前一日 `log_range` 預測當日，對齊上基本合理。
- `GJR-GARCH` 是遞迴 refit 到 `t-1` 後 forecast `t`，對齊上基本合理。
- `threshold` 模型使用 lagged `VIX` 與 lagged `log_range`，對齊也大致合理。
- **只有 HAR 是關鍵破口**：rolling 特徵在 OOS 使用了當日 `log_range`，但文章又將它解釋為「昨天、上週、上月」。這不只是 wording 問題，而是會直接抬高 OOS 表現的實作錯誤。

## Recommended Tweaks

1. 先修正 K465：OOS 的 HAR forecast 必須使用 `t-1` 可得的 `log_range`、`5d`、`21d`，再對比 `t` 的 `parkinson_var`。
2. 修正後完整重跑 `SPY` / `EWT` 五段 OOS 與全部 DM tests，再重新判斷 `10/10` 是否仍成立。
3. 補寫正式 `README.md`，讓資料期間、proxy 定義、比較模型、DM 實作、局限都可稽核。
4. 修正 script output path，使其直接產出到 `experiments/k465/` 目錄內的 canonical 檔名。
5. 若文章要保留 general audience 版本，至少把「昨天、上週、上月」改成與實作一致的描述；若重跑後結果變弱，必須同步降級 `10/10` 與「每段都穩地比較好」等強敘事。
