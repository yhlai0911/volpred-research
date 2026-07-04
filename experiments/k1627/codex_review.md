# K1627 Codex Code Review（primary-path）

**Reviewer**: Codex CLI (`codex exec`, ChatGPT auth, gpt-5.4)
**Date**: 2026-07-05（台灣時間）
**Verdict**: **CONDITIONAL_PASS**

## 逐項結果

| 項目 | 結果 |
|---|---|
| 1. Lookahead / alignment | PASS — `np.searchsorted(side="right")` 找 `tw_date > us_date` 下一 TW 交易日；only-read 驗證 same_date_count=0 / non_strict_count=0 / searchsorted_mismatch=0，無 off-by-one |
| 2. 報酬計算 | PASS — SPY / 0050.TW 各自對 adj_close 做 pct_change；first-row NaN 妥善 drop；DB 核對 2016+ adj_close null=0、dup dates=0 |
| 3. 條件機率 / base rate / 對照組 | PASS — 同一 US-forward event universe；Wilson CI 公式正確；diff z-test pooled SE(test)/unpooled SE(CI) 口徑正確 |
| 4. 2×2 列聯表與檢定 | PASS — table 排列正確；min_expected<5 切 Fisher；重算四門檻與 SciPy 完全一致 |
| 5. HAC 回歸 | 計算 PASS（statsmodels OLS cov_type=HAC maxlags=5，beta/t/p/R² 正確）；**輸出文字 ISSUE（必修）** |
| 6. Bootstrap | PASS — seed=42、連續 block、circular wrap、percentile 2.5/97.5；重算 P=0.8152、CI[0.7386,0.8857]、boots=2000 |
| 7. robustness dedup | PASS — 每 TW 日保留最新 US 訊號；主結果未被污染；去重後仍顯著結論不變 |
| 8. 數值穩定性 | PASS — Wilson/diff/conditional/bootstrap 除零皆有 guard |

## 必修項（1）— 已修正

**HAC beta 符號輸出文字誤導**：β=+0.485 為同向傳導，US 跌 1%（r_us=-1）對應 TW 次日平均 **-0.485%**。原 `k1627.py:391` result note 與 `k1627.py:573` 圖標題寫成正值易誤讀。

**Fix**（2026-07-05 主線程）：
- `k1627.py:391` note 改為明示「beta>0 同向；US 每跌 1% ⇒ TW 次日平均 -beta%（≈-0.485%）；斜率遠<1 代表非全額補跌」
- `k1627.py:573` 圖標題 `{reg['beta']:.3f}%` → `{-reg['beta']:.3f}%`
- 重跑實驗，核心數字不變（beta/base rate/條件機率全同），僅輸出文字與圖標題符號正確化。

README 於 review 時已正確，無需修改。
