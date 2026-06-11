# K202 / mile_872abdc3 — Codex 24h-rule Review

**Article**: 比特幣自己的數據，真的比 VIX 更懂它的波動嗎？
**Published**: 2026-06-11T04:07:13Z
**Reviewer**: Codex CLI (gpt-5.4 medium)
**Date**: 2026-06-11 13:xx CST

## VERDICT: FAIL

文章的主要數字大致對得上 `experiments/k202/k202_btc_features_results.json`，但有兩個 HIGH 問題：

1. 文章把結論寫成接近「BTC 特徵不比 VIX 更有用」，但程式自己的 summary 與 DM / incremental R² 輸出其實是「**有些** VIX 之外的增量資訊」。
2. 文末聲稱「所有預測只使用 t-1 資訊」，與實作不符；多個 predictor 是用 **當日 t 的收盤後特徵** 去預測 `t+1..t+22` 的未來 RV，這不是 lookahead，但也不是 t-1 discipline。

另有一個 source-level HIGH：DM expanding-window 檢定把前一個 OOS 點尚未完全實現的 `future RV` label 提前放回 training set，存在 label-time leakage。雖然 article 沒直接引用 DM 數字，但它影響 code 對「增量資訊」的總結口徑。

---

## 逐條 finding

### A. Article 主結論與 code verdict 直接矛盾 — HIGH
- Article 寫法：
  - 「沒有一個穩定打贏簡單基準」
  - 「不要自動假設它一定比 VIX 或歷史波動更有用」
  - 「線索和可用的預測工具，中間還差很遠」
- 但 code / results 不是純 null：
  - `incremental_over_vix.btc_spy_corr.delta_r2 = +0.9669`
  - `incremental_over_vix.range_ratio.delta_r2 = +0.3298`
  - `incremental_over_vix.weekend_ratio.delta_r2 = +0.0986`
  - `diebold_mariano_tests`: weekend / btc_spy_corr / range_ratio 都是 `combo_better=True`，p 值分別約 `0.0034 / 5.6e-6 / 0.0200`
  - summary verdict 明寫 `provide some incremental information beyond VIX`
- 來源：
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:400)
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:804)
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:914)
- 影響：這不是單純少寫 caveat，而是把「relative improvement over VIX exists but absolute R² still negative」壓扁成「沒用」，結論過強。

### B. 「所有預測只使用 t-1 資訊」與實作不符 — HIGH
- `range_ratio = (High-Low)/Close`、`vol_surprise = Volume / MA20`、`btc_spy_corr`、`skewness`、`kurtosis` 都直接以日期 `t` 的特徵進 regression，沒有 `shift(1)`。
- target `btc_rv22_future` 是 `rolling(22).std().shift(-22)`，對齊後代表未來 `t+1..t+22` 的 RV；所以這是「**當日收盤後 t-feature 預測未來**」，不是 lookahead，但也不是 article 寫的「只用 t-1」。
- 來源：
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:110)
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:196)
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:387)
- 影響：時序紀律被寫得比實際更嚴。應改成「end-of-day t 資訊預測未來 22 日 RV」。

### C. DM expanding-window 有 label-time leakage — HIGH
- `expanding_forecast()` 在 forecast 第 `i` 個 OOS 點時，把 `test_df.iloc[:i]` 整段拼回 training。
- 但 `target='btc_rv22_future'` 對 OOS row `j` 的 label 需要未來 `j+1..j+22` 報酬才會完全實現。
- 這代表在 forecast 後續 OOS 點時，training set 會提早納入一些在當時資訊集下尚未可觀測的 target label。
- 來源：
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:775)
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:783)
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:797)
- 影響：`diebold_mariano_tests` 的 p 值與 code summary 不能當乾淨 real-time OOS 證據。

### D. 相關性與 regime p-value 把重疊 22 日目標近似當 iid — MEDIUM
- `btc_rv22_future` 是重疊 22 日 rolling volatility，`pearsonr` / partial correlation / regime split 都直接用標準 t / p-value。
- 這會低估標準誤、放大顯著性。
- 來源：
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:110)
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:276)
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:320)
  - [experiments/k202/k202_btc_features.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/k202_btc_features.py:758)
- 影響：文章前半段「很多特徵真的和未來波動有關」可當描述性結果，但不宜用現在這組 p-value 當正式檢定。

### E. 實驗治理不合規 — LOW
- `README.md` 仍是 planning 模板，缺方法/樣本/結論。
- canonical 三件套命名也未跟 experiment id 一致：實際檔案是 `k202_btc_features.py` / `k202_btc_features_results.json`。
- 來源：
  - [experiments/k202/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k202/README.md:1)
- 影響：不直接推翻 article，但 provenance 與 auditability 偏弱。

---

## 建議處置

1. 對 `mile_872abdc3` 發 errata：
   - 把 `t-1` 改成 `end-of-day t`
   - 把總結改成「單一特徵獨立 forecast 仍全負 R²，但部分 VIX+feature 組合顯示相對改善；是否穩健需在修正 DM leakage 後再下判斷」
2. 重跑 K202 的 expanding-window / DM：
   - 只有當 row `j` 的 future RV 已完整 realized 後，才允許該 row 進訓練集
3. 補完整 `experiments/k202/README.md`

## 總結

這篇 article 不是數字造假，而是**把 mixed evidence 壓成過度乾淨的 null 敘事**。在 source-level audit 下，現狀不夠格稱為方法與敘事一致，因此 verdict = **FAIL**。
