# Codex 24h-Rule 文章審查報告
**審查日期**: 2026-05-27
**審查工具**: Codex CLI (gpt-5.4, ChatGPT auth)
**審查類型**: 3-model review discipline — Codex source-code review

---

## 1. mile_35913b6c / archive source `mile_63760e99` — 情緒指標能預測波動嗎？Put-Call Ratio 的混合答案

**verdict**: CONDITIONAL_PASS

**review scope**:
- 實驗代碼: `experiments/k523/k523_putcall_ratio.py`
- 結果檔: `experiments/k523/k523_putcall_ratio_results.json`
- 文章來源:
  - draft index entry `mile_35913b6c`
  - archived article body `storage/reports/_archive_mile_files/mile_63760e99.json`

**key findings**:
1. **主結論成立**: 文章核心 claim「VIX 百分位/PCR 代理策略在 2023-2025 OOS 無法擊敗 buy-and-hold」與結果檔一致。最佳 SPY long/cash 僅 `Sharpe=1.4179`，低於 `buy_hold=1.4366`；0050.TW 三組門檻也全數低於 buy-and-hold。`signal.shift(1)` 與台股 `vix_pctile.shift(1)` 皆已做，未見 lookahead bias。
2. **Harvey 門檻敘事過滿（MAJOR）**: 文章把樣本內 20 日 fear-vs-greed Welch t-test (`4.87 / 5.85 / 3.68`) 直接寫成「通過 Harvey 2016 門檻」。程式並未實作 Harvey-Liu-Zhu 多重檢定修正，也不是 forecast horse-race DM/HLN 框架。這些數字是普通兩樣本 t-test，不能升格為「Harvey PASS」。
3. **複合訊號文字與程式方向相反（MAJOR）**: 文章寫「VIX >= 80th 百分位且動量為負（VIX 仍在上升）」；但程式 `vix_mom5 < 0` 代表 VIX 過去 5 日**下跌**，也就是 fear is reverting / peaking, 不是 rising。這會誤導讀者對機制的理解。
4. **PCR 與 VIX proxy 區分有誠實揭露**: 程式在 CBOE PCR 取不到時 fallback 至 VIX percentile，results.json 與文章都明示了這是代理變數，不是假裝直接拿到 PCR。這點口徑一致。
5. **README 不完整（MINOR）**: `experiments/k523/README.md` 仍是 planning 模板，缺資料來源、fallback 條件、OOS 定義與限制，與研究誠實標準不符。

**需修正項目**:
1. 將「通過 Harvey 2016 門檻」改為「普通 t-test 達顯著；未做 Harvey-Liu-Zhu 類嚴格多重檢定修正」。
2. 將複合訊號描述改為「高 percentile + `vix_mom5 < 0`，即恐慌開始回落 / fear peaking」。
3. 補齊 `experiments/k523/README.md`，至少寫明 CBOE PCR unavailable → VIX proxy fallback、SPY 與 0050.TW 的 lag 規則、OOS 區間與未含交易成本。

**line refs**:
- `experiments/k523/k523_putcall_ratio.py:146-149` — VIX percentile proxy construction
- `experiments/k523/k523_putcall_ratio.py:272-285` — SPY OOS strategy uses `signal.shift(1)`
- `experiments/k523/k523_putcall_ratio.py:407-408` — 0050.TW cross-market signal lagged by 1 day
- `experiments/k523/k523_putcall_ratio.py:467-468` — composite signal is `vix_pctile >= th` and `vix_mom5 < 0`
- `storage/reports/_archive_mile_files/mile_63760e99.json:4-5` — archived article content with over-strong Harvey wording and reversed momentum narrative

---

## 2. mile_ecda80a3 / archive source `mile_a0322e61` — 開盤跳空 vs 夜盤波動：哪個訊號更能預測台指期隔日波動率？

**verdict**: PASS

**review scope**:
- 實驗代碼: `experiments/k1100g_d5/k1100g_d5.py`
- 結果檔: `experiments/k1100g_d5/k1100g_d5_results.json`
- 文章來源:
  - draft index entry `mile_ecda80a3`
  - archived article body `storage/reports/mile_a0322e61.json`

**key findings**:
1. **文章與結果數字一致**: 主要表格與 narrative 對 JSON 都準確。`M2_gap_total` OOS `DM-HLN t=1.49`、`QLIKE +6.62%`，`REF_night_r2` OOS `DM-HLN t=2.01`、`QLIKE +3.80%`，cross-model `DM t=-0.72, p=0.47`，IS LRT `18.87 vs 16.30` 都對得上。
2. **lookahead 紀律成立**: 程式明確只用 `gap_night[t]` 與 `gap_day[t-1]`。`gap_day[t]` 沒有進模型；`gap_day_lag = gap_day_t.shift(1)` 後才拿去預測 `r_day[t]^2`，符合「signal from t-1 / pre-open info, return at t」原則。OOS 也確實是 `2017-2019` 訓練、`2020-2021` 測試，且用 expanding window 每 5 日 refit，文章口徑正確。
3. **DM 檢定與 HLN 修正實作一致**: 程式 `dm_test_hln()` 有 Newey-West 型 HAC 長期變異估計，並加上 HLN correction factor；文章寫成 DM-HLN 並無灌水。對這篇來說，`p=0.044`、`p=0.47` 等敘事是可追溯的。
4. **文章沒有 overclaim，反而有自我收斂**: 雖然 results JSON 的 `verdict.primary` 是 `H3_NIGHT_R2_BETTER`，但文章主文已清楚寫出「cross-DM p=0.47 統計不可分」、「更接近 H2（兩者相當）」、「Harvey 2016 |t|>3 全部未過」。這比 JSON 內建 verdict explanation 更謹慎，屬合理降強度，不是誇大。
5. **唯一需要注意的是 JSON verdict explanation 本身偏強，但文章已自行修正**: 程式把 H3 解釋成「true info carrier is intra-session night movement, not just gaps」，這在 cross-DM `p=0.47` 下其實過頭；不過文章沒有照抄這句，而是保留「borderline / statistically indistinguishable」敘事，所以 publish 版本可保留。

**建議事項**:
1. 若後續再引用這個實驗，應優先引用文章中的 nuanced claim，而不是直接搬 `results.json` 的 `verdict.explanation`。
2. `experiments/k1100g_d5/README.md` 已完整，但若要更嚴謹，可補一句 `M2_gap_total` 與 `REF_night_r2` 的差異主要來自穩定性而非平均 QLIKE，大幅降低讀者把 H3 誤讀成「明確勝出」的風險。

**line refs**:
- `experiments/k1100g_d5/k1100g_d5.py:322-348` — HLN-corrected DM test implementation
- `experiments/k1100g_d5/k1100g_d5.py:380-432` — expanding-window OOS refit every 5 days
- `experiments/k1100g_d5/k1100g_d5.py:483-509` — legal gap construction and `gap_day_t.shift(1)`
- `experiments/k1100g_d5/k1100g_d5.py:583-605` — train/test split and OOS run loop
- `experiments/k1100g_d5/k1100g_d5.py:733-772` — cross-model DM between gap specs and `REF_night_r2`
- `experiments/k1100g_d5/k1100g_d5.py:800-814` — built-in verdict logic where H3 explanation is stronger than evidence
- `storage/reports/mile_a0322e61.json:4-5` — archived article content; wording is appropriately restrained relative to raw verdict
