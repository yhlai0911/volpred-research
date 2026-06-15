# K1505 — Vol-aware 提領法則與報酬順序風險

## 問題

提領期的 sequence-of-returns risk 不是 Sharpe 問題，而是「壞報酬早到時，是否會在低點被迫賣資產提款」的破產 / shortfall 問題。本實驗比較固定 4% 實質提領與三種只用已發生資訊的動態提款規則：

- `fixed`：固定實質提款。
- `vol_cut`：過去 12 個月 60/40 實質報酬年化波動高於歷史 75 分位時，下月少領 15%。
- `drawdown_cut`：無提款 60/40 實質 NAV 較高點跌超過 15% 時，下月少領 15%。
- `combined_cut`：任一 vol / drawdown 條件觸發即少領 15%。

## 資料與方法

- 資料來源：`SPY` / `IEF` yfinance adjusted close；CPI 使用 `storage/macro/fred_CPIAUCSL.csv`。
- 樣本：2006-02-28 到 2026-05-31，共 242 個月。
- 投組：60% SPY + 40% IEF，月頻再平衡，扣 CPI 後形成實質報酬。
- 診斷：60/40 實質年化平均報酬 5.87%，年化波動 9.41%，樣本內複利 NAV 最大回撤 -30.63%。
- 模擬：12 個月 moving-block bootstrap，10,000 條 30 年路徑，`seed=20260616`，起始資產 1,000,000。
- 提款：月初提款、月末套用該月報酬；動態規則的 month-t 訊號只用 t-1 以前的報酬 / NAV。

這是 empirical inputs 驅動的 bootstrap simulation，不是 30 年真實 cohort 回測，也不是 OOS volatility forecast。

## 4% 實質提領主結果

| 規則 | 破產率 | Δ 破產率 vs fixed | 平均總提款 | 平均少領 vs full plan | 終值 P5 | 平均觸發月數 |
|---|---:|---:|---:|---:|---:|---:|
| fixed | 4.06% | — | 1,191,293 | 0.73% | 70,186 | 0.0 |
| vol_cut | 2.95% | -1.11pp | 1,149,931 | 4.17% | 173,340 | 88.4 |
| drawdown_cut | 2.50% | -1.56pp | 1,167,709 | 2.69% | 202,978 | 56.0 |
| combined_cut | 2.17% | -1.89pp | 1,140,618 | 4.95% | 239,690 | 111.0 |

paired path CI（破產率差）：`combined_cut` 相對 fixed 為 -1.89pp，95% CI [-2.16pp, -1.62pp]；平均總提款少 50,675 美元。

## 提領率敏感度

| 初始提領率 | fixed | vol_cut | drawdown_cut | combined_cut |
|---:|---:|---:|---:|---:|
| 3.5% | 1.75% | 1.26% | 0.83% | 0.74% |
| 4.0% | 4.06% | 2.95% | 2.50% | 2.17% |
| 4.5% | 8.34% | 6.26% | 5.69% | 5.10% |
| 5.0% | 14.97% | 11.88% | 11.80% | 10.30% |
| 5.5% | 23.71% | 19.24% | 19.92% | 17.56% |

核心判讀：vol/drawdown-aware 提領規則在同一批 bootstrap path 上穩定降低破產率，但不是免費提高安全提領率。它靠市場壓力期少提款換取較低 ruin probability；若退休者無法承受約 3-5% 的平均消費 shortfall，這類規則的實務價值會下降。

## 文獻定位

- Bengen (1994), *Determining Withdrawal Rates Using Historical Data*, Journal of Financial Planning — 固定實質提款基準。
- Guyton and Klinger (2006), *Decision Rules and Maximum Initial Withdrawal Rates*, Journal of Financial Planning — flexible withdrawal / guardrail 動機。
- Finke, Pfau, and Blanchett (2013), *The 4 Percent Rule Is Not Safe in a Low-Yield World*, Journal of Financial Planning — 4% rule forward-looking caveat。
- CFA Institute FAJ summary (2017), *Managing Sequence Risk to Optimize Retirement Income* — sequence risk framing。

## 限制

- 本地 CPI cache 從 2006 開始，ETF/CPI common sample 只有 242 個月；30 年結果靠 block bootstrap 延伸，不是真實 30 年 cohort。
- 波動門檻使用全樣本描述性校準；不得改寫成 OOS timing signal。
- 動態提款改善 solvency 的機制是少領錢；本實驗沒有估計效用、生活費底線、稅、費用、社安、年金或 RMD。
- `IEF` 是中期美債 ETF proxy；債券期限、通膨連結債、現金桶或年金配置可能改變結果。

## 檔案

- `k1505_vol_aware_withdrawal.py`：可重跑腳本。
- `k1505_results.json`：完整數字、設定、文獻與限制。
- `figures/k1505_ruin_shortfall.png`：4% 主結果。
- `figures/k1505_ruin_sensitivity.png`：提領率敏感度。
- `figures/k1505_terminal_distribution.png`：終值分布。
- `data/SPY.csv`, `data/IEF.csv`：yfinance adjusted close cache。

## 審查

Codex self-review：PASS。詳見 `codex_review.md`。重點確認：訊號 lag 正確、無 same-month return lookahead、固定 seed、MDD 使用複利 NAV、沒有 Sharpe / OOS forecast overclaim。
