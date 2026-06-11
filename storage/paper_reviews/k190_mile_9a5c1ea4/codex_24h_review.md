# K190 / mile_9a5c1ea4 — Codex 24h-rule Review

**Article**: 市場跌過之後通常更容易亂，但把波動拆更細，真的比較有用嗎？
**Published**: 2026-06-10T22:01:08Z
**Reviewer**: Codex CLI (gpt-5.4 medium)
**Date**: 2026-06-11 14:xx CST

## VERDICT: CONDITIONAL_PASS

主結論與 `experiments/k190/k190_realized_semivariance_results.json` 基本一致：  
4/5 資產最佳 QLIKE 模型仍是 GJR-GARCH，QQQ 只有 `EWMA_semivar` 小幅領先；沒有 lookahead；`t-1` 口徑與實作大致相符。

主要扣分點是統計敘事略偏強。文章把 SPY / QQQ 的 downside-ratio 現象寫得像穩健共通規律，但 code/result 顯示這更接近「SPY 穩、QQQ 邊界」，而非兩個都穩健成立。

---

## 逐條 finding

### A. Lookahead / timing discipline — PASS
- `ewma_forecast()` 明確用 `series[t-1]` 更新 `forecast[t]`。
- `Semivariance HAR` 的 regressors 全是 `RS+_{t-1}, RS-_{t-1}` 與過去 5 日均值。
- `GARCH-X SJV` 也是 `SJV_{t-1} -> r_t^2`。
- 來源：
  - [experiments/k190/k190_realized_semivariance.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance.py:126)
  - [experiments/k190/k190_realized_semivariance.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance.py:197)
  - [experiments/k190/k190_realized_semivariance.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance.py:279)
- Verdict：無 lookahead。文章尾句「所有預測只使用 t-1 資訊」可接受。 ✅

### B. QQQ downside ratio 的敘事太強 — MEDIUM
- 文章寫：
  - SPY 下跌後波動約 `1.54x`
  - QQQ 約 `1.32x`
  - 並用這兩點支撐美股/科技股「確實有這種特性」
- 結果檔顯示：
  - SPY ratio `1.5393`, `p=0.0048`
  - QQQ ratio `1.3226`, `p=0.0474`
- 若把 5 資產 SJV regime 一起視為同一 family，QQQ 這個 `p=0.0474` 不耐簡單 Bonferroni；SPY 還站得住，QQQ 不穩。
- 來源：
  - [experiments/k190/k190_realized_semivariance_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance_results.json:60)
  - [experiments/k190/k190_realized_semivariance_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance_results.json:142)
- 影響：文章應改成「SPY 明顯、QQQ 邊界」或補一句「QQQ 只在未校正 5% 水準成立」。

### C. 「QQQ 是唯一例外」的模型比較口徑 — PASS
- `best_models` 的確只有 QQQ 是 `EWMA_semivar`，其餘 4 個都是 `GJR_GARCH`。
- 文章只說「略勝一點點」，沒有宣稱 QQQ 對 GJR 顯著勝出。
- 這很重要，因為 `EWMA_semivar_vs_GJR` 在 QQQ 的 DM `p=0.6449`，但 `EWMA_semivar_vs_EWMA_total` 則 `p=0.0026`。
- 來源：
  - [experiments/k190/k190_realized_semivariance_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance_results.json:19)
  - [experiments/k190/k190_realized_semivariance_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance_results.json:111)
- Verdict：文章在這裡沒有 overclaim。 ✅

### D. Cross-asset null narrative — PASS
- GLD / BTC 的 `sjv_regime.ratio` 都 < 1 且 p-value 不顯著。
- TLT ratio `0.7305`, `p=0.0163`，方向確實與股票相反。
- 文中「GLD/BTC 幾乎沒有、TLT 反過來」與結果一致。
- 來源：
  - [experiments/k190/k190_realized_semivariance_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance_results.json:224)
  - [experiments/k190/k190_realized_semivariance_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance_results.json:306)
  - [experiments/k190/k190_realized_semivariance_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/k190_realized_semivariance_results.json:388)
- Verdict：數字與敘事一致。 ✅

### E. Experiment governance 不合規 — LOW
- `README.md` 仍是 planning 模板，沒有完整方法/樣本/結論。
- canonical 三件套命名也未完全跟 `k190` 對齊，實際檔案是 `k190_realized_semivariance.py` / `_results.json`。
- 來源：
  - [experiments/k190/README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k190/README.md:1)
- 影響：不推翻文章，但 auditability 偏弱。

---

## 建議處置

1. 若要補 errata，最小修正即可：
   - 把 QQQ 那句降成「QQQ 方向一致，但統計上較邊界」
   - 或直接補一句「SPY 穩健，QQQ 僅未校正 5% 水準成立」
2. 補完 `experiments/k190/README.md`，讓實驗三件套合規。

## 總結

這篇文章的主線沒有方法論硬傷，source-level 與敘事大致一致；問題主要是把一個「SPY 穩、QQQ 邊界」的現象，寫得稍微太像兩者都穩健。因此 verdict = **CONDITIONAL_PASS**。
