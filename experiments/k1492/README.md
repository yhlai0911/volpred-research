# K1492 — Stablecoin Redemption Pressure to Crypto/Treasury Vol Pilot

- Experiment ID: `K1492`
- Status: complete
- Seed: `42`
- Task origin: `research_stablecoin_redemption_pressure_crypto_to_treasur`

## Motivation

任務池新題要求測試「stablecoin redemption pressure 作 crypto-to-Treasury vol channel」。
repo 內既有 `K401` 已做過 yfinance 版 USDT/USDC 脫鉤壓力，但沒有使用較乾淨的
DefiLlama 歷史供給資料，也沒有把 short/long Treasury proxy 納入同一個
OOS forecast horse race。

本實驗的核心問題是：

1. USDT/USDC 的**流出壓力**是否領先 BTC / ETH / Treasury proxy 波動？
2. USDT/USDC 的**peg deviation** 是否比單純流出量更有訊號？
3. 這個 channel 若存在，是偏 crypto 還是能一路傳到 Treasury volatility？

## Literature Check

本實驗設計前先對齊 3 篇外部文獻／政策研究：

1. **IMF Working Paper 2026/044, _Stablecoin Shocks_**
   - 連結：<https://www.imf.org/en/publications/wp/issues/2026/03/06/stablecoin-shocks-574528>
   - 提示 stablecoin shocks 會影響 Treasury yields 與 broader financial markets。
2. **BIS Working Paper 1270, _Stablecoins and Safe Asset Prices_**
   - 連結：<https://www.bis.org/publ/work1270.pdf>
   - 直接研究 stablecoin inflows 對短端 T-bill yield 的壓縮效果。
3. **Federal Reserve FEDS Notes (2024-02-23), _Primary and Secondary Markets for Stablecoins_**
   - 連結：<https://www.federalreserve.gov/econres/notes/feds-notes/primary-and-secondary-markets-for-stablecoins-20240223.html>
   - 強調 peg 壓力與 primary / secondary market dynamics 的差異。

## Data

- Stablecoin supply:
  - DefiLlama `stablecoin/1` (USDT), `stablecoin/2` (USDC)
  - 以 chain-level `circulating.peggedUSD` 聚合每日供給
- Stablecoin prices:
  - DefiLlama `stablecoinprices`
  - 取 `tether` / `usd-coin` 每日價格
- Market prices:
  - yfinance adjusted close
  - `BTC-USD`, `ETH-USD`, `SHY`, `TLT`

樣本設定：

- requested start: `2021-01-01`
- requested end: `2026-06-14`
- OOS start: `2024-01-01`

## Method

### Stablecoin signals

1. **Redemption pressure**
   - `combined_supply_usd = USDT_supply + USDC_supply`
   - `combined_flow_pct = diff(log(combined_supply_usd))`
   - `redemption_pressure = max(0, -combined_flow_pct)`
2. **Peg deviation**
   - `peg_dev_max = max(|USDT-1|, |USDC-1|)`

### Target volatility proxy

對每個目標資產計算：

- `ret_t = log(P_t / P_{t-1})`
- `rv5_t = mean(ret^2 over last 5 obs) * 252`

### Lookahead control

所有 stablecoin 訊號都用**前一個 calendar day 可得資訊**對齊到目標資產交易日。
等價於：

- crypto: 幾乎就是 `signal.shift(1)`
- Treasury ETF: 週一使用週日之前最後一筆 stablecoin 資訊

避免 same-day contamination。

### Forecast comparison

- Baseline: `rv5_t ~ rv5_{t-1}`
- Full: `rv5_t ~ rv5_{t-1} + redemption_pressure_{t-1} + peg_dev_max_{t-1}`
- BTC 額外做 horse race：
  - baseline
  - flow-only
  - peg-only
  - full

OOS 採 expanding-window recursive refit，loss 用 QLIKE，比較用 DM-HLN style loss-differential test。

## Main Results

總結 verdict：`BTC_ONLY`

只有 `BTC-USD` 通過「QLIKE 改善 + DM 顯著」；`ETH-USD`、`SHY`、`TLT` 全部為 NULL。

### Asset-level OOS results

| Asset | OOS n | QLIKE improvement | DM-HLN p | Event / baseline forward RV5 | Verdict |
|---|---:|---:|---:|---:|---|
| BTC-USD | 895 | +0.00535 | 0.0000004 | 1.62x | **PASS** |
| ETH-USD | 895 | -0.00207 | 0.4630 | 1.35x | NULL |
| SHY | 614 | -0.13576 | 0.0794 | 1.13x | NULL |
| TLT | 614 | -0.00056 | 0.4849 | 1.00x | NULL |

### BTC horse race

| Model | Mean QLIKE | Improvement vs baseline | DM-HLN p |
|---|---:|---:|---:|
| baseline | -1.15911 | — | — |
| flow-only | -1.15911 | -0.00000 | 0.9830 |
| peg-only | -1.16432 | +0.00521 | 0.0000002 |
| full | -1.16447 | +0.00535 | 0.0000004 |

重點不是「stablecoin 流出」本身，而是**peg deviation**。  
`flow-only` 幾乎完全沒用；`peg-only` 已經抓到幾乎全部 BTC 訊號，`full` 只再多一點點。

### Signal scale

- latest combined USDT+USDC supply: `261.48B USD`
- mean redemption pressure: `0.0566%`
- redemption pressure p95: `0.2625%`
- mean max peg deviation: `12.0 bps`
- max peg deviation p95: `44.9 bps`

## Interpretation

1. **Stablecoin stress 對 BTC 有增量資訊，但主要來自 peg stress，不是供給流出。**
2. **這條 channel 沒有自然延伸到 Treasury ETF volatility。**
   - 若存在 Treasury 影響，更可能表現在 yield / bill demand，而不是 SHY / TLT 的日頻 RV5。
3. **ETH 沒有複製 BTC 結果。**
   - 這表示 stablecoin peg stress 比較像是 BTC-specific liquidity / benchmark channel，而不是廣義 crypto beta。

## Limitations

1. `SHY` / `TLT` 是 ETF proxy，不是直接的 T-bill yield、repo、SOFR 或 dealer inventory 資料。
2. DefiLlama `stablecoinprices` 是日頻 end-of-day，抓不到 intraday depeg 極值。
3. chain-level circulating supply 能反映發行／流通量，但不能直接觀察 reserve liquidation path。
4. 這是 reduced-form forecast，不是因果識別。

## Next Step

若要延伸這題，最合理的是：

1. 把 Treasury target 從 `SHY/TLT RV` 換成 **front-end yield / T-bill ETF flow / MOVE-short-end proxy**
2. 補 **USDC 2023-03 SVB event** 的高頻事件窗
3. 檢查 BTC 訊號是否只是更廣義 `crypto stress` 的代理，需加入 funding / perp basis / exchange stress control

## Artifacts

- [`experiments/k1492/k1492.py`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1492/k1492.py)
- [`experiments/k1492/k1492_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1492/k1492_results.json)
- ![signal](/Users/yhlai0911/Desktop/volpred-research/experiments/k1492/fig_signal_timeseries.png)
- ![qlike](/Users/yhlai0911/Desktop/volpred-research/experiments/k1492/fig_qlike_improvement.png)
- ![event](/Users/yhlai0911/Desktop/volpred-research/experiments/k1492/fig_event_study.png)
