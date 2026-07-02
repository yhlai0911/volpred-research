# K1605：區域銀行 M/B 折價與後續波動，橫斷面穩健、OOS 不過關

*[提出: publication-candidates, 執行: Codex]*

## 摘要

K1605 檢驗一個銀行風險問題：市場價格相對帳面淨值的折價，能不能提前指出區域銀行後續已實現波動率上升。樣本使用 yfinance 免費資料，包含 27 家仍上市美國區域銀行，以及 KRE、KBE 兩個銀行 ETF；主要橫斷面有效期間從 2023-03-16 到 2026-07-02。Phase-1 結果顯示，低 M/B 與較高後續 RV 的橫斷面關係明確：控制 trailing own-RV 後，Fama-MacBeth h5 與 h22 斜率約為 -0.0168，統計強度約 -4.00。正式 Phase-2 補做 block bootstrap、filing-lag robustness 與 OOS DM test 後，結論收斂為：橫斷面描述關係穩健，但加入 M/B 沒有改善 KRE/KBE 樣本外波動率預測。

## 研究背景

區域銀行的帳面淨值有天然時間差。債券未實現損失、存款外流壓力、信用惡化，會先被股價反映，財報裡的 book equity 則依季報或年報更新。2023 年區域銀行危機讓這個差距變得很具體：市場已經用價格折價表達疑慮，會計數字仍慢一步。

K1605 把這個直覺變成可檢驗命題：若一家銀行的 market-to-book ratio 較低，或整體區域銀行族群的 M/B 下滑，後續 5 日或 22 日已實現波動率是否更高。這個設定與幾個既有研究方向不同。K1481 是實體商品 inventory surprise 對 commodity RV 的 fundamental-feature 測試，結果偏 NULL；K1162 測 EAV binary fundamental 對截面的效果，偏弱；K1001 顯示 implied volatility 類訊號常常勝過 macro fundamental；K1355 則提供本研究採用的截面推論規則：不能把 asset-day 直接當 iid，要先按日期聚合再做 HAC inference。

本研究的差異在於，M/B 不是純會計變數，也不是純市場價格。分母是 book equity，分子是市場價格乘上 shares outstanding；若市場比帳本更快反映 delayed loss，M/B 可能是銀行風險的低成本 proxy。問題是這個 proxy 很容易被價格本身污染。K1605 的核心貢獻，是把「橫斷面壓力溫度計」與「時間序列可交易預測」拆開檢查。

## 方法與數據

| 項目 | 設定 |
|---|---|
| 實驗 | K1605 |
| 樣本資產 | 27 家 survivor regional banks；ETF 目標 KRE、KBE |
| 價格資料 | yfinance adjusted close，自 2020-01-01 起 |
| 分析起點 | M/B analysis window 自 2022-01-01 起；橫斷面有效起點 2023-03-16 |
| 帳面資料 | yfinance annual + quarterly balance sheet，Common Stock Equity |
| Shares | yfinance `get_shares_full` |
| 目標 | forward annualized RV over `(t, t+H]`，H = 5、22 |
| 控制變數 | trailing 22-day own-RV |
| 推論 | time-series Newey-West HAC；Fama-MacBeth daily cross-section slope + HAC |
| Lookahead 防護 | 10-Q quarter_end +45d、10-K fiscal_year_end +75d；signal `shift(1)` |
| 隨機 seed | 20260702 |

資料診斷有三個需要先說清楚的限制。第一，29 檔銀行名單中，CMA 與 SNV 價格資料失敗，實際可用銀行為 27 家。第二，yfinance 的 book equity 歷史很薄，coverage-gated cross-sectional statistics 只能從 2023-03-16 之後解讀；更早期間少於 10 家銀行有 lag-safe book equity。第三，SVB、SBNY、FRC 等 2023 年失敗銀行已不在 survivor sample，這會把樣本推向較健康銀行，可能低估真正壓力訊號。

![區域銀行 M/B 分布：2023 壓力期前後，低於帳面價值的銀行比例急升後回落](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1605_fig1_mb_dispersion.png)

## 核心發現一：2023 壓力期，M/B 橫斷面真的先變形

描述統計先確認研究對象有經濟含義。2023 壓力期內，樣本銀行的 stress-window coverage 最低仍有 27 家。最緊張的一天是 2023-05-03，低於帳面價值的銀行比例達 85.2%。同一段壓力期，KRE 22 日 trailing RV 最高達 70.3% 年化；壓力前中位數為 23.4%。

到 2026-07-02，M/B 橫斷面已明顯回穩：樣本銀行 M/B 中位數為 1.41，低於帳面價值比例降到 7.4%。這組數字說明 M/B 不是只會永久標記銀行股便宜或昂貴，它在 2023 年壓力期捕捉到整個族群被市場重新定價的程度。

| 指標 | 數值 | results.json 欄位 |
|---|---:|---|
| 可用銀行 | 27 家 | `diagnostics.n_banks_book_usable` |
| 橫斷面有效起點 | 2023-03-16 | `descriptive.panel_effective_start` |
| 低於帳面比例峰值 | 85.2% | `descriptive.frac_below_book_max` |
| 峰值日期 | 2023-05-03 | `descriptive.frac_below_book_max_date` |
| 最新 M/B 中位數 | 1.41 | `descriptive.mb_median_level_latest` |
| 最新低於帳面比例 | 7.4% | `descriptive.frac_below_book_latest` |

## 核心發現二：Phase-1 lead-lag screen 顯示正確方向

Phase-1 的問題是：低 M/B 是否對應較高後續 RV，而且效果是否超過 lagRV 自身的持續性。Fama-MacBeth 結果支持這個方向。h5 spec_B，也就是控制 lagRV 後的 signal slope，平均值為 -0.0168298，HAC 標準誤 0.0042057，統計強度 -4.0016，樣本日期 821 天。h22 spec_B 平均值為 -0.0168517，HAC 標準誤 0.0042030，統計強度 -4.0094，樣本日期 804 天。

時間序列 ETF 測試也有同方向證據。KRE h5 logMB beta 為 -0.2360，統計強度 -3.90，樣本 799；KRE h22 beta 為 -0.1688，統計強度 -2.50，樣本 782。KBE h5 beta 為 -0.1688，統計強度 -3.25，樣本 799；KBE h22 beta 為 -0.1050，統計強度 -1.74，未達 Phase-1 門檻。合計有 5 項 lagRV-controlled、正確方向、|t| > 2 的增量檢定。

![M/B 與 KRE 後續波動：估值折價越深，後續波動通常越大](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1605_fig2_scatter_kre.png)

| 檢定 | horizon | 估計量 | 統計強度 | 樣本 |
|---|---:|---:|---:|---:|
| Fama-MacBeth + lagRV | h5 | -0.0168 | -4.00 | 821 days |
| Fama-MacBeth + lagRV | h22 | -0.0169 | -4.01 | 804 days |
| KRE time-series beta | h5 | -0.2360 | -3.90 | 799 |
| KRE time-series beta | h22 | -0.1688 | -2.50 | 782 |
| KBE time-series beta | h5 | -0.1688 | -3.25 | 799 |
| KBE time-series beta | h22 | -0.1050 | -1.74 | 782 |

這個階段可以給「signal」標籤，但只能解讀成 first-look screen。K1605 的 README 已預先定義：Phase-1 使用 |t| > 2，正式 DM/Harvey 門檻與樣本外預測要延後計算。因此 Phase-1 的角色是「值得進正式檢定」，不是「已可用於交易」。

![橫斷面斜率：低 M/B 對應較高未來波動，但這仍是描述關係，不是交易訊號](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1605_fig3_fama_macbeth.png)

## 核心發現三：formal bootstrap 支持橫斷面，但 OOS DM 不支持預測改善

Phase-2 formal run 補上兩類檢查。第一類是 Fama-MacBeth cross-sectional slope 的 circular block bootstrap，2000 reps，block=22，並測三組 filing lag：q45/a75、q60/a90、q90/a120。第二類是 OOS expanding-window forecast，把 M/B-augmented model 與 RV-only HAR-lite baseline 比較，並用 DM test 檢查預測誤差差異。

bootstrap 結果支持橫斷面關係。q45/a75 設定下，h5 mean 為 -0.016832，95% CI 為 [-0.025104, -0.009644]，p_two_sided = 0.000；h22 mean 為 -0.016851，95% CI 為 [-0.024991, -0.008221]，p_two_sided = 0.000。q60/a90 與 q90/a120 也維持負向，且 95% CI 都排除 0；最保守 q90/a120 下，h5 mean 為 -0.011306，p_two_sided = 0.007，h22 mean 為 -0.012677，p_two_sided = 0.005。

OOS 結果完全不同。q45/a75 下，KRE h5 的 RMSE improvement 為 -1.35%，DM 統計強度 -2.42；KBE h5 為 -0.99%，DM 統計強度 -2.38。這兩個負值代表 M/B-augmented model 的 RMSE 較差，而且短期 h5 的顯著方向是「加入 M/B 變差」。q45/a75 的 h22 也沒有改善：KRE h22 為 -2.02%，DM 統計強度 -0.93；KBE h22 為 -1.07%，DM 統計強度 -0.55。

q60/a90 唯一微幅正向格子是 KBE h22，RMSE improvement 只有 +0.0179%，DM 統計強度 0.012，p = 0.990。q90/a120 更保守 filing lag 下，KRE h22 與 KBE h22 的 RMSE improvement 分別為 -15.27% 與 -14.94%。沒有任何 OOS 設定通過 Harvey |t| > 3 的預測改善門檻。

| Formal 設定 | 橫斷面 bootstrap | OOS forecast 結論 |
|---|---|---|
| q45/a75 | h5、h22 slope 皆負；CI95 不跨 0 | KRE/KBE h5、h22 全部 RMSE improvement 為負 |
| q60/a90 | h5、h22 slope 皆負；CI95 不跨 0 | 只有 KBE h22 +0.0179%，DM 幾乎為 0 |
| q90/a120 | h5、h22 slope 皆負；CI95 不跨 0 | h22 RMSE 明顯變差，未過 Harvey 門檻 |

## 實務意義

K1605 最有價值的地方，是把銀行 M/B 放回「風險監控」位置，而不是把它包裝成短線波動率預測模型。若研究者或風控人員想知道市場正在懷疑哪一批銀行，M/B 橫斷面有資訊。2023 年壓力期 85.2% 銀行跌破帳面價值，搭配 KRE RV22 升到 70.3%，很適合用作族群性壓力儀表。

若目標是 KRE/KBE 的短期 RV forecast，formal OOS 檢定不支持把 M/B 直接加進模型。最保守的結論是：M/B 反映市場已經定價的 delayed-loss prior，但這個 prior 在樣本外沒有打敗 RV persistence。這與波動率預測的常見經驗一致：低頻 fundamental proxy 能描述壓力來源，卻不一定提升短 horizon forecast。

後續研究可以往三個方向推進。第一，加入 past return、momentum 或純 value factor，測試 M/B 的訊號是否只是價格下跌的另一種寫法。第二，擴展樣本到更長、多 regime 的銀行資料，降低單一 post-SVB regime 的依賴。第三，改用 bank-level call report 或更乾淨的 HTM/AFS unrealized loss disclosure，讓 delayed-loss channel 更接近真正會計機制。

## 限制與穩健性

本研究有四個主要限制。第一，樣本只含 survivor banks，SVB/SBNY/FRC 等最關鍵的失敗銀行不在資料中，估計可能偏向保守或低估壓力。第二，daily M/B 多數變動來自價格，price confound 不能只靠 lagRV 完全消除。第三，book equity 由 yfinance balance sheet 提供，歷史短且更新稀疏；橫斷面有效起點實際落在 2023-03-16。第四，OOS horizon 與 ETF 目標只有 KRE/KBE，尚未證明可跨銀行 ETF 或個股交易場景泛化。

穩健性方面，K1605 已做三層防護。時間對齊採 quarter_end +45d、fiscal_year_end +75d，並對 signal 做 `shift(1)`；forward RV 嚴格使用 `(t, t+H]`。推論上，Fama-MacBeth 先按日期做 cross-sectional slope，再對 slope time series 做 HAC，遵守 K1355 的 non-iid asset-day guard。正式檢定上，block bootstrap 支持橫斷面 slope，但 OOS DM test 否定 forecasting improvement。這三層結果合在一起，形成「描述關係成立、預測用途不成立」的邊界。

## 結論

K1605 的最終研究結論是 CONDITIONAL_PASS，而不是 PASS。低 M/B 的區域銀行後續波動較高，這個橫斷面關係在 Phase-1 HAC 與 Phase-2 bootstrap 下都穩健；但把 M/B 加進 KRE/KBE 樣本外波動率模型，沒有改善 forecast，短 horizon 甚至常讓 RMSE 變差。因此，M/B 可以放進銀行風險儀表板，標記市場對帳面淨值的懷疑程度；目前證據不支持把它當成可交易的區域銀行波動率 timing signal。

## Reproduce

```bash
uv run python experiments/k1605/k1605.py
uv run python experiments/k1605/k1605_formal.py
```

主要輸出：

- `experiments/k1605/k1605_results.json`
- `experiments/k1605/k1605_formal_results.json`
- `experiments/k1605/k1605_fig1_mb_dispersion.png`
- `experiments/k1605/k1605_fig2_scatter_kre.png`
- `experiments/k1605/k1605_fig3_fama_macbeth.png`

*資料來源：yfinance adjusted close、yfinance annual/quarterly balance sheet、yfinance shares outstanding。樣本：27 家 survivor regional banks、KRE、KBE。主要橫斷面有效期間：2023-03-16 至 2026-07-02。*
