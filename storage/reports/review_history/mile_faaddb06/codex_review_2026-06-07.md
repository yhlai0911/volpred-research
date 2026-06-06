# Codex Review — mile_faaddb06 (K593 cross-OOS window comparison)

- **Reviewer**: Codex CLI 0.135.0 (gpt-5.4)
- **Date**: 2026-06-07 05:14 台灣時間
- **Article**: 預測波動率該回望多久？五段歷史告訴我們：沒有萬靈丹
- **Published**: 2026-06-06T20:11:54Z
- **Experiment**: K593 / experiments/K593/k593_window_cross_oos.py

## VERDICT: FAIL

### SEVERE issues
1. **Forecast 對齊錯誤** `k593_window_cross_oos.py:215-221`  
   refit-every-21-day pattern 下，`last_model.forecast(horizon=1)` 在兩次 refit 之間反覆呼叫同一個已擬合結果，**沒有把 intervening OOS return 納入條件變異數更新**。也就是說 21 天區間內，每一天的 forecast 都是「同一個 t+1 預測值」而不是「frozen parameters 下 sequential one-step-ahead with updated state」。這不屬 lookahead，但屬 forecast engine bug，足以**影響全文 QLIKE 比較與 DM 檢定結論**。

2. **DM test 日期未對齊** `k593_window_cross_oos.py:370-375, 403-408, 432-436`  
   各 window 算完 loss 後直接 `[:min_len]` 截斷，沒按日期 join。若不同 window 因 fit/forecast 失敗在不同日期 → 比較的是**錯位樣本**。pooled DM 同樣問題。

3. **Pre-registration 站不住**  
   程式 docstring + JSON `decision_rule` 雖寫了判讀規則，但都與結果同檔產出，沒有獨立事前時間戳或外部 prereg artifact。**只能算 ex-post documentation，不是可驗證的事前承諾**。文章「事先就把判讀規則寫死，避免事後挑數字」陳述需要降調或改寫。

### MEDIUM issues
- 沒做 multiple-testing adjustment（5 periods × 6 pairwise comparisons = 30 tests）。Bonferroni 校正下，只有 OOS4 (p=0.00106) 與 OOS5 (p=0.000734) 的 `***` 仍成立；**OOS1 / OOS2 的 `**` 不再成立**。文章未提。
- 用 plain DM + HAC，沒有 Harvey-Leybourne-Newbold small-sample correction。文章「嚴格統計檢驗門檻」用詞需降調。
- 句子泛化過頭：「沒有萬靈丹」「市場環境會挑視窗嗎」超出單一資產 SPY 的證據範圍。應限定「在 SPY 這 5 段 OOS」。
- `Feng & Zhang (2025, Journal of Forecasting)` 引文格式可疑：作者名過泛、題目 generic、缺卷期頁碼 DOI。標**待驗證**或刪除。

### NITS
- 輸出路徑 `experiments/k593_window_cross_oos_results.json`（repo 根目錄）vs `experiments/K593/...`，重現性差。
- `all_idx.index(dt)` 在 loop 內反覆呼叫，效率差但不影響結論。

### NUMERICAL CHECK (article ↔ JSON)
- OOS1 2012–2013, W=252 QLIKE: A=1.5405, J=1.540504, diff=4.1e-6 ✓
- OOS2 2014–2015, W=2000 QLIKE: A=1.8691, J=1.869079, diff=2.1e-5 ✓
- OOS4 2020–2021, W=504 QLIKE: A=1.9981, J=1.998115, diff=1.5e-5 ✓

### LOOKAHEAD CHECK
CONDITIONAL_PASS — refit sample 只用到目標日之前資料，沒有明顯 future leak；但 forecast engine 在 refit 之間未做 sequential state update，仍不正確。

### PRE-REGISTRATION CHECK
FAIL — 無獨立事前時間戳或 prereg 證據。

## 必要動作
1. **修 K593 script**（forecast engine: 兩次 refit 間每日 `update + forecast(horizon=1)`；DM test 按日期 join；results.json 存到 K593/ 子目錄）
2. **重跑 K593** → 比對新舊 QLIKE / DM stats
3. **修正文章 mile_faaddb06**：
   - 更新 5 段 QLIKE 表 + per-period DM stats（若數字實質改變）
   - 補 Bonferroni 校正說明（OOS1/OOS2 顯著性下調）
   - 「事先就把判讀規則寫死」改寫成 "decision rule 是 ex-post documentation，未獨立 prereg"
   - 「沒有萬靈丹」/「市場環境會挑視窗嗎」明確限定「在 SPY 這 5 段 OOS」
   - 移除或標註 Feng & Zhang (2025) 引文待驗證
4. **不下架文章**（已 published 且結論方向 MIXED no universal winner 仍可能在 fix 後成立），但**標 corrigendum + linked review**。
