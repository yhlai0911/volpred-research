# Codex 24h Review — mile_2d4edb65 (K901)

- **Article**: 一套方法在 13 個市場都有效，卻不代表它會幫你賺更多
- **Draft source**: `/private/tmp/mile_2d4edb65.md` extracted from `storage/reports/feed.json`
- **Task**: `paper_review_mile_2d4edb65`
- **Reviewed**: 2026-06-03 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## Summary

核心敘事大致成立，而且方法層面比多數一般讀者文更乾淨：`K901` 明確使用 `signal.shift(1)` 防 lookahead，BH/VT 的對齊問題也已在 v3 修掉，`13/13` 市場最大回撤改善、`0/13` 市場 Sharpe 改善、`0/13` 達 Harvey `|t| > 3` 的主結論都能由實驗結果直接支持。

需要修的不是主數字，而是敘事邊界：

1. 文中前段把它講得太像「跨很多國家都能用的全球通用規則」。
2. 但真正實驗設計是 **13 個以美元計價的 US-listed ETF**，共用 **US VIX** 當訊號、**SHY** 當現金 proxy。

所以這篇不是 FAIL，但應明確降一級成「在 13 個美元 ETF 市場代理上，防守效果一致」，不要再往「全球市場萬用答案」推。

## Numeric verification

下列核心口徑與 `experiments/k901/k901_international_vt_13markets_results.json` 一致：

| Draft line | Claim | Source | Match |
|---|---|---|---|
| 15 | 13/13 市場都比較不容易跌深 | `cross_sectional.n_mdd_improved = 13` | ✓ |
| 16 | 0/13 風險調整後報酬變更好 | `cross_sectional.n_sharpe_improved = 0` | ✓ |
| 17 | 0/13 沒有夠強證據證明比抱住更會賺 | `cross_sectional.n_dm_significant_harvey = 0` | ✓ |
| 23 | MDD 改善幅度約 5pp 到近 30pp | Table 5: `FXI +5.08pp`, `EFA +29.49pp` | ✓ |
| 62 | 13 個以美元計價 ETF 市場 | README line 59, results `limitations[0:2]` | ✓ |

## Findings

1. **Opening overstates external validity beyond the actual design** — `/private/tmp/mile_2d4edb65.md:5`
   文中寫「跨很多國家都能用」「市場不同、投資人不同、政策不同，結果它居然在 13 個市場都成立」。這個說法會讓讀者以為測的是 13 個彼此獨立、在地訊號驅動的本地市場規則。  
   但 `K901` 實際設計是 13 個 **US-listed、美元計價 ETF**，共用 **同一個 US VIX 訊號** 與 **同一個 SHY cash proxy**，README 也明確要求加 qualifier：`13 USD-denominated ETFs sharing US VIX signal`，不是 fully independent local-market validation。見 [README](../../experiments/k901/README.md:59)。

2. **“跨市場通用” 結論需要加同一個 qualifier，不然會延續前段 overclaim** — `/private/tmp/mile_2d4edb65.md:38-46`
   `「跨市場通用的防守工具」` 這句在一般讀者文裡很順，但如果不加限定，會比 source code / README 支持的範圍更大。較準確的版本應是：  
   `在 13 個美元 ETF 市場代理上，這套規則更像一致的防守工具，而不是穩定的報酬放大器。`

3. **Method honesty is otherwise good: article did not overstate Sharpe/DM evidence** — `/private/tmp/mile_2d4edb65.md:15-17,44-46,62`
   這點反而應給正評。`0/13 Sharpe improved`、`0/13 Harvey-grade DM significance` 和 source 完全一致；文中也沒有把這個 defensive rule 寫成能提升最終報酬的策略。雖然部分市場的 DM raw p-value 對 `BH > VT` 有 5% 水準訊號，但文章的表述是「沒有足夠強證據支持 VT 更會賺」，這個方向沒有寫反。

## Lookahead audit

- PASS — `run_vt()` 明確使用 `signal = raw_signal.shift(1)`，以 `VIX_{t-1}` 決定 `t` 日權重，見 [k901_international_vt_13markets.py](../../experiments/k901/k901_international_vt_13markets.py:177)。
- PASS — v3 已把 `bh_ret_aligned = mkt_ret.loc[vt_idx].values` 補上，DM 與 bootstrap 不再有一日錯位，見 [k901_international_vt_13markets.py](../../experiments/k901/k901_international_vt_13markets.py:406)。

## Recommended fixes

1. 把 line 5 的「跨很多國家都能用」「13 個市場都成立」降級成「在 13 個美元計價 ETF 市場代理上都出現一致的防守效果」。
2. 把 line 40 的「跨市場通用」改成「跨這 13 個 ETF 市場代理一致」或等價限定語。
3. 可在文末註腳再補一句：`共用 US VIX 訊號與 SHY 現金 proxy，因此這是跨 ETF 市場代理的防守一致性，不等同各國本地波動率規則的全面驗證。`
