# Codex 3rd-Model Adversarial Review — v6 README

**Timestamp**: 2026-06-10 19:14 台灣時間 (2026-06-10T11:14:57Z)
**Codex version**: 0.137.0 (gpt-5.4, medium reasoning)
**Session ID**: 019eb13c-1dc4-7651-9988-d32347110eae
**Target**: `paper/vt-trend-following/review_history/v6/README.md`
**Data verified**: `experiments/k1458_h1_trough_decomposition/k1458_results.json`

---

## Verdict: FAIL

---

## Finding 1 — CRITICAL: Decomposition Identity 定義錯誤（line 56）

README 寫：`VIX_timing_contrib (= PureVT_excess_vs_BH)`

這個等式在 `TSMOM_hedge_full = 0` 時成立，但一般情況是：

```
PureVT_excess_vs_BH = VIX_timing_contrib + TSMOM_hedge_full
```

反例（直接來自 `k1458_results.json`）：
- `SPY 2020-03`: `0.0376542 = -0.0843325 + 0.1219867` — 兩者相差 +12.2pp
- `QQQ 2020-03`: `-0.1101749 = -0.1405804 + 0.0304055` — 兩者相差 +3.0pp

這是 decomposition identity 寫錯，不是措辭問題。

**Action**: 修正欄位定義，明確說明 decomposition identity 是加法關係。

---

## Finding 2 — HIGH: Mechanism Claim 超出 K1458 直接證據範圍（line 91, 108）

README 敘述「PureVT 在 BH 最低點時的 drawdown 沒那麼深，不是靠 V 型反彈後賺更多」。

`k1458_results.json` 提供的是 trough-window arithmetic contributions，**不是** PureVT 與 BH 的 drawdown path 比較，也不是 MDD 壓縮量分解。JSON 中可見的 `trough_dd_in_window` 是 BH trough 識別用的，不是 PureVT/BH 同步 MDD gap 的直接測量。

這個機制說法目前是從窗口貢獻反推的 inference，不是直接量測。

**Action**: 把此句改寫為明確 inference，加「based on contributions, not direct MDD path measurement」。

---

## Finding 3 — HIGH: 2009-03 結論過強（line 46, 100）

README 寫 `NO (CLEARED)` 與「純 VIX-level vol-targeting（無 TSMOM hedge 污染）」。

但 JSON 顯示：
- `50/50 2009-03`: `TSMOM_hedge_full = +2.1 pp`, `TSMOM_hedge_TSMOM<0 days = +11.9 pp`
- `QQQ 2009-03`: `TSMOM_hedge_full = -3.5 pp`, `TSMOM_hedge_TSMOM<0 days = +3.3 pp`
- `cross_asset_summary["2009-03"].valid_share_count = 2`

3/5 assets 為零，但 2/5 有非零 hedge。不能說「沒有機械性 hedge」，只能說「在多數資產（3/5）缺席，整體不普遍但並非不存在」。

**Action**: 把 `NO (CLEARED)` 改為「在 3/5 資產為零，整體不普遍，但 2/5 有非零貢獻（50/50 +2.1pp, QQQ -3.5pp），不能說完全不存在」。

---

## Finding 4 — MEDIUM: Beta Clipping 說法無直接 JSON 支撐（line 39, 97）

README 說「rolling-beta 在 2004-2006 樣本初期被 clip 至 0」。

`k1458_results.json` 只包含：
- `data_window.start = 2004-06-01`
- 各資產 headline/partition 結果

但沒有 beta path、沒有 clipped-count、沒有 beta==0 days 統計。實驗 python code（`k1458_h1_trough_decomposition.py:215`）有 `beta = beta.shift(1).fillna(0).clip(0, 0.5)`，說明 beta clipping 確實是設計選擇，但 results JSON 未輸出量化 evidence。

**Action**: 改寫成條件式表述：「rolling-beta 在樣本初期因 lookback 不足可能被 clip，但 K1458 未直接量化此效應；結論是 hedge 貢獻=0，解釋原因需另補數據」。

---

## Finding 5 — MEDIUM: H1 PARTIAL CLOSURE 語氣偏強（line 48, 112）

README 雖承認 10 obs 樣本限制，但正文語氣仍接近 causal closure（`CLOSURE`、`CLEARED`、「確實有貢獻」等詞）。

對 5 assets × 2 troughs 的描述性樣本，合理上限應是 `illustrative / suggestive evidence`，不是接近定案的 CLOSURE 語言。

**Action**: 把標題降級為「H1 PARTIAL SUGGESTIVE EVIDENCE（非定案）」，正文用「empirically suggestive for 2020, absent for majority of assets in 2009」語氣。

---

## Table Verification (PASS)

K1458 decomposition table 的數字，逐資產逐 trough 與 `k1458_results.json` headline 四欄核對：

| 驗證項 | README | JSON | 一致 |
|--------|--------|------|------|
| SPY 2020-03 PureVT_excess_vs_BH | +3.8 pp | 0.037654... | ✓ |
| SPY 2020-03 VIX_timing_contrib | -8.4 pp | -0.084332... | ✓ |
| SPY 2020-03 TSMOM_hedge_full | +12.2 pp | 0.121986... | ✓ |
| SPY 2020-03 TSMOM_hedge_TSMOM<0 days | +34.6 pp | 0.345520... | ✓ |
| QQQ 2020-03 TSMOM_hedge_TSMOM<0 days | +56.1 pp | 0.561137... | ✓ |
| IWM 2020-03 TSMOM_hedge_full | 0.0 pp | 0.0 | ✓ |
| 2020-03 Median TSMOM_hedge_neg_days | +30.0 pp | 0.300033... | ✓ |

無 transposed cell，無 sign error。

---

## Ratio Warning (PASS — correctly handled)

README 在 K1458 decomposition table 注意事項中明確說明 valid_share_count=1（2020-03），表格一律使用 raw arithmetic contributions，未不當使用 ratio 指標。2009-03 valid_share_count=2 未重複展開提醒，但 README 無使用 ratio 做跨資產比較。比例相關部分無問題。

---

## Actionable Revision Points (5 items)

1. **[CRITICAL]** 修正 decomposition 定義（line 56）：把 `VIX_timing_contrib (= PureVT_excess_vs_BH)` 改成 `PureVT_excess_vs_BH = VIX_timing_contrib + TSMOM_hedge_full`，加法關係。
2. **[HIGH]** 把 `PARTIAL CLOSURE` 降級成 `suggestive descriptive evidence`，避免 `closure`、`cleared` 語氣；標題改為「H1 PARTIAL SUGGESTIVE EVIDENCE（非定案）」。
3. **[HIGH]** 刪除或改寫「PureVT 在 BH 最低點時的 drawdown 沒那麼深」為明確 inference，加 `(K1458 inference, not direct MDD path measurement)` qualifier。
4. **[HIGH]** 把 2009-03 的敘述從 `NO (CLEARED)` 改成「3/5 資產 hedge 為零，但 2/5 有非零貢獻，不可說完全不存在」。
5. **[MEDIUM]** 把 `beta clipped` 改寫成條件式表述，或補 K1458 不直接量化此效應的 caveat，不做為已驗證機制。

---

## Reviewer Note

本次 Codex adversarial review 發現 1 個 CRITICAL（decomposition identity 錯誤）、3 個 HIGH、1 個 MEDIUM。數字表本身完全正確（PASS），問題集中在 narrative claims 的推論強度與欄位定義。

v6 README 需依上述 5 點修正後，才可供 body.tex v6 修訂任務引用。
