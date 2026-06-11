# k189

- Experiment ID: `k189`
- Status: rerun_completed_pending_review
- Created At: 2026-04-16T09:11:47.030667+00:00
- Corrected Re-run: 2026-06-11

## 問題描述

- 檢驗跨資產 attention aggregation 是否能改善六個 ETF 的波動率預測。
- 原版 K189 經 Codex 24h-review 判定 `FAIL`，原因是 lookahead、post-selection inference、spec mismatch 與未做 multiple-testing correction。

## 動機

- 原始文章 `mile_c26fcd8e` 宣稱「六個資產全數失敗」與「最佳設定幾乎都靠近 0.9」。
- 在保留同一批資產、同一個 alpha grid 與同一個 OOS 區間下，重跑一版 source-level 對齊正確的規格，確認結論是否仍成立。

## 資料與樣本

- 資料來源：`yfinance` 日收盤價
- 資產：`SPY, QQQ, GLD, TLT, EEM, IWM`
- VIX 控制序列：`^VIX`
- 原始下載期間：`2005-01-01` 至 `2025-01-01`
- OOS 評估區間：`2023-01-01` 至 `2025-01-01`
- 實際 OOS 交易日：預期約 502 日，實際筆數以 `k189_attention_vol_results.json` 為準

## 修正後方法

1. 目標變數仍為 22 日 rolling realized variance：`returns.rolling(22).var() * 252`。
2. `EWMA` 預測值對日期 `t` 只使用 `t-1` 及之前的報酬更新，不可用到 `ret_t^2`。
3. Attention weights 對日期 `t` 的估計只使用不晚於 `t-1` 的資料。
4. 對每個資產、每個 OOS 日期 `t`，用前 500 個交易日做 ex ante alpha selection；不可用整段 OOS 先挑 `best_alpha` 再回頭檢定。
5. 比較基準：
   - 單資產 `EWMA(0.94)`
   - rolling `GJR-GARCH(1,1)`，訓練窗 500 日
6. 評估：
   - QLIKE loss
   - DM test
   - Bonferroni 與 Benjamini-Hochberg FDR 校正，校正 family = 6 資產 × 2 baseline = 12 tests
   - Harvey `|t| > 3` 門檻僅作強度檢查，不視為多重比較替代品

## 防錯規則

- 所有 forecast 必須是 `signal at t-1 -> target at t`
- Attention correlation window 不可包含 `target_t`
- Alpha selection 必須完全在 OOS 當下可得的歷史窗內完成
- 結論必須區分：
  - 描述性 QLIKE 差值
  - 未校正 DM 顯著性
  - 多重比較校正後顯著性

## 產出

- 主程式：`experiments/k189/k189_attention_vol.py`
- 結果：`experiments/k189/k189_attention_vol_results.json`
- 審查：`paper/k189_audit/codex_review_2026_06_11.md`

## 待確認

- 重跑後是否仍支持原文章「六個全敗」的描述性結論
- 校正後是否還有任何 DM 顯著結果存活
- 原文章是否需維持 errata 或進一步 downgrade 結論
