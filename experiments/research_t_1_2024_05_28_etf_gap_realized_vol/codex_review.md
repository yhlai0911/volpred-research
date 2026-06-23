# Codex source review

## 結論

未發現會推翻本實驗 `CONDITIONAL_BREAK_DIAGNOSTIC` verdict 的程式錯誤。腳本可重跑、資料來源透明、bootstrap 固定 seed，且 overnight gap 使用 `Close_{t-1}`，沒有把 same-day close 混入 open gap。

## 檢查項目

- 實驗三件套完整：
  - `README.md`
  - `research_t_1_2024_05_28_etf_gap_realized_vol.py`
  - `research_t_1_2024_05_28_etf_gap_realized_vol_results.json`
- 資料：
  - yfinance daily adjusted OHLCV，`auto_adjust=True`。
  - 每檔 ticker raw cache 寫入 `data/raw/*_ohlcv.csv`。
  - daily panel 寫入 `data/research_t_1_2024_05_28_etf_gap_realized_vol_daily_panel.csv`。
- Lookahead：
  - `prev_close = close.shift(1)`。
  - `gap = log(open / prev_close)`。
  - `post_t1` 是 calendar event dummy，不是可交易 alpha signal。
- Inference：
  - ticker-level test 使用 OLS-HAC `maxlags=5`。
  - bootstrap 使用 `np.random.default_rng(SEED)`，seed=42。
  - discovery gate 同時要求 Harvey-style `|t| >= 3` 與 BH q-value。
- 產物：
  - 結果 JSON 包含 data source、official source、method、claim rule、limitations、key findings。
  - CSV 與 figures 由腳本重跑生成，未手工改資料。

## 殘餘風險

- 這是 daily OHLCV proxy，無法觀察 true settlement fail、affirmation timing、ETF primary-market flow 或 official rebalance calendar。
- `post_t1` 是共同日期 shock，不能排除 2024-2026 macro / rates / credit regime confounding。
- Pooled group interaction 沒有做 date-clustered covariance；可作篩選，但不能升級為最終因果證據。
- ADR raw post-pre mean 與 volume-controlled HAC coefficient 在部分 ticker 方向不同，README 已標明此點，避免過度宣稱。

## 建議下一版

若要把 diagnostic 升級成 publishable event study，應加入：

- NSCC / DTCC fails 或 affirmation-rate data。
- ETF creation/redemption 或 primary-market basket flow。
- 官方 index rebalance calendar。
- Date-clustered 或 two-way clustered inference。
