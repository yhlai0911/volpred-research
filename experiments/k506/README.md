# k506

- Experiment ID: `k506`
- Status: reran_2026_07_05 — Codex FAIL（核心 null robust，精確數字未達發表級，見 `codex_review_20260705.md`）
- Last updated: 2026-07-05

## 問題描述

驗證 `EWT / 0050.TW` 21 日 realized volatility ratio，是否能作為台股 VT (`8.63 / VIX`) 的額外 overlay，在 5 段不重疊兩年期 cross-OOS 中穩定改善淨 Sharpe。

## 本輪修正目標（K506_retry_lookahead_fix）

1. 修正 lookahead bias：所有調倉訊號都必須用 `t-1` 資訊決定 `t` 報酬。
2. 統一台股 ETF 往返成本為 `0.001855`（18.55bp，K625 更正後口徑）。
3. 對 5 段 + pooled 共 6 次 DM 檢定加上 Bonferroni 與 BH 校正。
4. 禁止混用 K505 的數字；K506 的對外數字只能來自本實驗 `results.json`。

## 目前狀態（2026-07-05 rerun）

- **Data blocker 已解除**：repo 移出 Desktop 後 yfinance 不再被 sandbox 擋，EWT 2010-2021 已成功補抓（`data_inputs.EWT="yfinance"`，TW50/VIX 仍走 sqlite cache）。實驗重跑成功，`results.json` 為 2026-07-05 fresh 輸出（覆蓋舊失效版）。
- **結果 = NULL/MARGINAL**：VT+VS wins 3/5（未過 ≥4/5 門檻）；pooled DM t=0.457, p=0.648；Bonferroni p=1.0；BH p=0.7313 — 全不顯著。
- **Codex review = FAIL**（見 `codex_review_20260705.md`）：核心 null（overlay 無顯著改善）在 Codex 4-variant sanity rerun 下 robust（pooled DM p=0.25–0.65 全不顯著），但精確 3/5 win-count 受三項 code 議題影響、**未達發表級**：
  1. rebalance timing：新權重套 close-to-close 報酬（應 open-to-close / 或標 non-tradable c2c）。
  2. calendar as-of：台股假日訊號用舊值（~86 日；false-null 風險，非 lookahead）。
  3. 成本口徑：round-trip 18.55bp 對每次 abs(Δw) 全額扣，label vs 套用倍率待釐清。
- **未寫 knowledge.json**（守 Codex FAIL bar）。方法論硬化見「下一步」，改完 re-review 通過才寫 knowledge / 發文。

## 資料來源需求

- `0050.TW`: 本地 SQLite cache `data/cache/price_cache.db`
- `^VIX`: 本地 SQLite cache `data/cache/price_cache.db`
- `EWT`: 需要 2010-01-01 至 2021-12-31 的日資料；目前 repo 只找到 `experiments/k1090/data/EWT.csv`（2018-01-02 至 2024-12-30），不足以支撐五段 OOS。

## 下一步（方法論硬化 → follow-up task）

1. **Rebalance timing**：載入 `0050.TW` open 價，rebalance day 舊權重吃 overnight、新權重吃 open-to-close；或明確把 close-to-close 版標為 non-tradable diagnostic。
2. **Calendar as-of**：改 timestamp-aware as-of merge（台股開盤前用最近可得的美股/VIX close），修 ~86 台股假日 stale-signal。
3. **成本口徑審計**：釐清 18.55bp 是 round-trip（買+賣）還是 per-trade，對稱套用到 VT 與 VT+VS。
4. 改完 → Codex re-review 通過（CONDITIONAL_PASS↑）→ 才寫 knowledge.json + 決定是否發文（若仍 null，寫 null-result knowledge）。
