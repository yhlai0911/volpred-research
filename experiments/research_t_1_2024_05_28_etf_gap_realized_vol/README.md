# T+1 settlement gap and realized-volatility structural-break diagnostic

## 動機

本實驗回應 `research_program.md` 的制度/法規變更題：美國 covered securities 的標準結算週期於 2024-05-28 從 T+2 改為 T+1。直覺上，較短結算週期可能改變 ETF、ADR、跨境資金與再平衡流程的庫存壓力，進而影響 overnight close-to-open gap variance、daily realized-volatility proxy、以及月底/季底再平衡日的波動。

這裡只做 public daily OHLCV structural-break diagnostic。它不是因果識別，也不是交易策略。

## 制度與文獻來源

- SEC, *Shortening the Securities Transaction Settlement Cycle* / small-entity compliance guide：T+1 effective date 與 covered securities 範圍。
  `https://www.sec.gov/investment/settlement-cycle-small-entity-compliance-guide-15c6-1-15c6-2-204-2`
- SEC Chair statement, 2024-05-21：確認 2024-05-28 conversion。
  `https://www.sec.gov/newsroom/press-releases/2024-62`
- DTCC, 2023：T+1 的 market-infrastructure 動機，包含降低風險、margin 與流動性需求。
  `https://www.dtcc.com/news/2023/february/15/dtcc-comments-on-sec-announcement-regarding-the-t1-implementation-date-of-may-2024`
- SIFMA / CCMA / ISDA, *T+1 Securities Settlement Industry Implementation Playbook*：交易處理、跨市場時點與 operational readiness。
  `https://www.sifma.org/research/white-papers/t1-playbook`
- LSEG / FTSE Russell, 2024：shorter settlement cycles 對 index 與市場流程的影響。
  `https://www.lseg.com/content/dam/ftse-russell/en_us/documents/research/market-index-impact-of-shorter-equity-settlement-cycles.pdf`

## 資料

- Market data：`yfinance` daily adjusted OHLCV，`auto_adjust=True`。
- Requested sample：2022-01-01 至 2026-06-24 exclusive。
- Effective market sample：2022-01-03 至 2026-06-22。
- Event date：2024-05-28。
- Universe：15 個 liquid ETFs / ADRs。
  - U.S. ETFs：SPY、QQQ、IWM、VTI。
  - International ETFs：EFA、EEM。
  - Credit / bond ETFs：HYG、LQD、TLT。
  - ADR basket：BABA、TSM、ASML、NVO、SAP、TM。
- 每檔 ticker 有 601 個 pre-event rows 與 518 個 post-event rows。

## 方法

Daily variables：

```text
gap_t = log(Open_t / Close_{t-1})
intraday_ret_t = log(Close_t / Open_t)
cc_ret_t = log(Close_t / Close_{t-1})
gap_var_t = gap_t^2
cc_var_t = cc_ret_t^2
range_var_t = Parkinson high-low proxy
```

Primary ticker-level test：

```text
z(log_gap_var_t) ~ post_t1 + month_end + quarter_end + z(log_dollar_volume_t)
```

Secondary tests：

- `post_t1 x month_end` 與 `post_t1 x quarter_end` 的 group-level rebalance interaction。
- `post_t1 x ADR` 與 `post_t1 x U.S. ETF` 的 pooled group interaction。

Inference：

- OLS-HAC / Newey-West `maxlags=5`。
- Harvey-style absolute threshold：`|t| >= 3`。
- BH q-value within each test family，`q <= 0.05` 才列為 pass。
- Bootstrap：pre/post mean difference block bootstrap，block=5、reps=1000、seed=42。

## Lookahead 防線

本實驗不是 return prediction，但仍避免同日資訊錯置：

- Overnight gap 明確使用 `Open_t / Close_{t-1}`。
- `post_t1` 只是制度事件日分類，不是交易訊號。
- 月底/季底旗標用每檔 ticker 實際交易日計算，避免假日與跨市場 date drift。
- Bootstrap 固定 `seed=42`。

## 結果

Verdict：`CONDITIONAL_BREAK_DIAGNOSTIC`。

Primary overnight gap-variance tests：

- 15 個 ticker-level `log_gap_var` tests。
- 9/15 同時通過 `|t| >= 3` 與 BH `q <= 0.05`。
- 最大絕對 HAC t-stat cells：

| Ticker | Group | HAC post coef | HAC t | BH q | Raw post-pre mean |
|---|---|---:|---:|---:|---:|
| HYG | credit_etf | -0.530 | -7.66 | 7.42e-14 | -1.600 |
| TSM | adr | -0.602 | -7.47 | 3.04e-13 | +0.242 |
| LQD | credit_etf | -0.481 | -6.46 | 2.54e-10 | -0.913 |
| SAP | adr | -0.602 | -5.90 | 7.98e-09 | +0.046 |
| TLT | bond_etf | -0.416 | -5.89 | 8.09e-09 | -0.705 |
| SPY | us_etf | -0.272 | -3.98 | 1.00e-04 | -0.489 |

Rebalance interaction：

- 0/30 `post_t1 x month_end` / `post_t1 x quarter_end` group tests pass both Harvey and BH.
- U.S. ETF month-end `log_gap_var` term has HAC t=3.06 but BH q=0.066, so it is not counted as discovery.

Group interaction：

- 4/6 pooled ADR / U.S. ETF post-event interactions pass both Harvey and BH.
- ADR interactions are positive for `log_gap_var`, `log_cc_var`, and `log_range_var`, so the cross-segment pattern is not simply "vol fell everywhere."

## 解讀

日頻 public proxy 支持一個有限結論：T+1 生效日附近，ETF / ADR 的 overnight gap variance 與 realized-volatility proxy 出現可檢定的 cross-segment structural break，尤其 credit ETFs 與 bond ETF 的 gap variance 在 post-event regression 中下降明顯。

但這不是強因果 claim。2024-2026 同時有利率、信用、科技股與全球市場 regime 變化；單一制度日期無法用 daily OHLCV 分離所有共同衝擊。ADR raw mean 與控制後 regression coefficient 也可能方向不同，代表 liquidity / dollar-volume controls 與 regime trend 會影響估計。

## 局限

1. Daily OHLCV 看不到 intraday settlement fail、affirmation rate、ETF creation/redemption basket timing、或 market-on-close imbalance。
2. ADR basket 是免費資料 proxy，不是真正 cross-border settlement pressure 資料。
3. 月底/季底旗標只是每月/每季最後交易日，不是官方 index rebalance calendar。
4. Pooled group interaction 使用日頻 proxy，仍可能受 cross-sectional date shock 影響；結果應視為篩選，而非最終識別。

## 輸出

- `research_t_1_2024_05_28_etf_gap_realized_vol.py`：可重跑腳本。
- `research_t_1_2024_05_28_etf_gap_realized_vol_results.json`：structured results。
- `research_t_1_2024_05_28_etf_gap_realized_vol_ticker_breaks.csv`：ticker-level pre/post 與 HAC tests。
- `research_t_1_2024_05_28_etf_gap_realized_vol_rebalance_interactions.csv`：月底/季底 interaction tests。
- `research_t_1_2024_05_28_etf_gap_realized_vol_group_interactions.csv`：ADR / U.S. ETF group interactions。
- `data/research_t_1_2024_05_28_etf_gap_realized_vol_daily_panel.csv`：daily panel。
- `data/raw/*_ohlcv.csv`：yfinance raw cache。
- `figures/t1_gap_var_hac_tstats.png`。
- `figures/t1_group_gap_var_timeline.png`。
- `codex_review.md`：source-level review。

## 重跑

```bash
uv run python experiments/research_t_1_2024_05_28_etf_gap_realized_vol/research_t_1_2024_05_28_etf_gap_realized_vol.py
```

強制重新下載 yfinance：

```bash
uv run python experiments/research_t_1_2024_05_28_etf_gap_realized_vol/research_t_1_2024_05_28_etf_gap_realized_vol.py --refresh
```
