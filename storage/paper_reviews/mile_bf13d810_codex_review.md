# Codex paper review — mile_bf13d810

**Article**: 14 個跨市場資產的波動率慣性幾乎一樣高：GJR-GARCH persistence 均值 0.9802
**Published**: 2026-06-15T14:00:20Z
**Experiment**: K491 (Universal Volatility Persistence Law — Cross-Asset Analysis)
**Reviewer**: Codex CLI 0.135 (gpt-5.4), 2026-06-16 hourly-04 dispatch
**Task**: paper_review_mile_bf13d810 (Codex 24h-rule, claimed by hourly-04)

## Verdict: PASS

無實質 issue；文章與 K491 source code 一致、claim 強度與 in-sample 描述定位匹配。

## Checked (6 dimensions)

| 維度 | 結果 | Evidence |
|------|------|----------|
| A. Lookahead | ✓ descriptive only | `k491_persistence_law.py:31`（無 trading/signal/OOS forecast） |
| B. Persistence 公式 | ✓ α+γ/2+β 正確 | `k491_persistence_law.py:183`（arch alpha[1]/gamma[1]/beta[1] 對應） |
| C. Hillebrand gap | ✓ paired t-test | `k491_persistence_law.py:516,631`（gap = full − rolling mean, ttest_1samp） |
| D. Kruskal-Wallis 分組 | ✓ 4 組正確 | `k491_persistence_law.py:389,431`（US/Intl/Bonds/Commodities；Crypto/FX n=1 排除） |
| E. DM/Harvey overclaim | N/A | 無 model comparison；文末限制明寫 in-sample |
| F. 數字一致性 | ✓ 全 reproduce | `results.json` line 600 (0.9802±0.0141)、678 (gap +0.0336 t=5.03 p=0.0002)、694 (KW p=0.062)、3535 (SPY-QQQ ρ=0.835) |

## Notes

- 文章限制段已明示 in-sample MLE、不宣稱「預測明天的波動率」、未做 Bonferroni 修正、「universal law」應理解為現象描述非物理常數 — claim 強度與證據範圍 match。
- HYG/BTC persistence = 1.0 的 IGARCH 詮釋處理得當（限制段獨立說明）。
