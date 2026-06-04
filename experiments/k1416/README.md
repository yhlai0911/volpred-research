# K1416 — Paper 3 HLN Small-Sample DM Correction Retrofit

**Pair**: TW0050-N225 (Paper 3 cross-market copula 10 pairs 中原始 raw-DM 規則下唯一 Harvey-sig pair, Student-t copula vs DCC, dm_t≈3.92 at OOS_START=2015-06-01)

**Verdict**: `CONDITIONAL_PASS` (Codex 2026-06-04 review)
**Robustness**: 5/5 HLN-sig @ 5% AND @ 1% across 5 OOS starts → Paper 3 OK to submit (caveats below)

## 動機

Paper 3 (DCC-Clayton) submission blocker per `research_program.md` Open Question。K1412 partial update 跑了 5 OOS starts (2014/2015/2016/2017/2018) Student-t DM_t = {3.24, 3.89, 3.66, 3.04, 3.09} all `|t|>3`，K1412 報 ROBUST，但 Codex review FAIL：K1412 retrofit_notes 用 worst-case n=10 推論而非正式套用 HLN(1997) small-sample correction 公式。

K1416 retrofit (正式版本):
- (a) 每 OOS 明確記錄 n_oos_obs (從 paper3_E2 baseline n=2067 推算 TW0050+N225 trading-day ratio)
- (b) 明確套用 HLN(1997) small-sample correction: `factor = sqrt((n + 1 - 2h + h(h-1)/n) / n)`, h=1 ⇒ `sqrt((n-1)/n)`
- (c) 明確算 critical_value: `scipy.stats.t.ppf(0.975, df=n-1)`
- (d) Verify K1412 stored `dm_dcc_vs_t` 與 paper3_E2.dm_test:783-785 內建 HLN 一致
- (e) 重算 robust_ratio with explicit HLN-corrected critical_value

## 方法

1. 從 `paper3_E2_results.json` 拿 baseline (OOS_START=2015-06-01)：n=2067, hln_factor=0.99975807, t_HLN=3.923, t_raw=3.924, critical=1.961
2. 在 K1416 重算 `hln_factor` 與 `critical_value` → 完全吻合 (`stored == computed`)
3. 對 K1412 5 OOS starts，從 baseline 推算 n_oos (trading-day ratio = 2067/4014 cal-days = 0.515)
4. 套 HLN(1997) formula + scipy.stats.t critical_value
5. 對每 OOS 判 `abs(t_HLN) > critical_value` (5% two-sided)

關鍵 assumption (Codex 確認對): K1412 stored `dm_dcc_vs_t` IS HLN-corrected per `paper3_E2.dm_test`:
- L783-785: `t_stat = t_stat_raw * hln_factor`
- K1412 L95: `dm_t['t_stat']` 直接存進 `dm_dcc_vs_t`

## 結果

```
OOS_START      n_est   factor      crit_5%   t_HLN     PASS@5%   PASS@1%
2014-01-02     2332    0.999786    1.9610    3.2402    True      True
2015-06-01*    2067    0.999758    1.9611    3.8915    True      True
2016-01-04     1955    0.999744    1.9612    3.6607    True      True
2017-01-03     1767    0.999717    1.9613    3.0442    True      True
2018-01-02     1580    0.999683    1.9615    3.0929    True      True

*baseline: n exact from paper3_E2_results.json (others inferred via trading-day ratio)
```

**Robust ratio**: 5/5 (100%) at both 5% and 1% levels.

## Codex Review Verdict: CONDITIONAL_PASS

**Core econometric logic**: PASS
- HLN formula coded correctly
- critical_value method correct (scipy.stats.t.ppf two-sided 5%)
- K1412 stored t IS HLN-corrected (verified at paper3_E2.py:783-785)
- Baseline cross-check: stored vs computed hln_factor 完全吻合

**Outstanding caveats** (paper wording 必須收斂):

1. **n_oos 是估算非實測** — 4 個非 baseline OOS 用 calendar-day ratio proxy；影響 negligible (factor 差 < 4e-6 對 ±20 obs 誤差，5% critical 差 < 2e-5；最小 `|t|=3.044` 離 critical 還有 ~1.08 margin)，結論不會翻。
   - **嚴格表述**: 「K1416 是 verified assumption + negligible-sensitivity approximation，不是 full rerun audit」
   - **改進 path** (future work): paper3_E2.dm_test 上游直接輸出 per-OOS `n` 並 K1412 patch 進去

2. **5/5 是 sensitivity grid 不是 5 次獨立 replication** — 5 OOS starts 高度重疊 (overlapping samples)，不能視為 familywise-error 校正。
   - **paper wording 必用**: "The HLN-adjusted superiority is stable across 5 alternative OOS starts (5/5 significant), supporting robustness."
   - **禁用**: 把「≥80% PASS → ROBUST」包裝成統計定理

3. **≥80% PASS gate 是 internal submission gate**，不是 econometric evidence 本身

## Paper 3 Submission Recommendation

- ✅ **Proceed**: TW0050-N225 唯一 Harvey-sig 主張 robust to OOS_START choice，HLN-corrected at 5% AND 1% 全 PASS
- 📝 **Paper wording 須含** caveats 1-3 (見上)
- 🔜 **Optional refinement** (post-submission): paper3_E2.dm_test 加 per-OOS exact n storage，K1412 重跑一次帶 metadata，K1416 補 exact-n verification

## References

- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281-291.
- K1412: `experiments/k1412/k1412_results.json` (5 OOS DM_t data)
- Paper3_E2: `experiments/paper3_E2_cross_market_copula/paper3_E2.py:757-792` (內建 HLN 邏輯)
- `research_program.md` Paper 3 Open Question (TW0050-N225 唯一 Harvey-sig)
- Codex review: `tokens used 39263` (2026-06-04)
