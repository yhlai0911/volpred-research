# K1363 — Fedspeak forecast-revision shock as equity/bond tail-vol prior

## 動機

本題來自 `research_program.md:1144`：把 between-meeting central-bank speech 當成資訊 shock，而不是正式 FOMC 決議日或一般新聞量。文獻動機是央行 speech 的 forecast-revision content 可能影響 equity / bond volatility 與 tail risk。

K1363 做的是 public-data dictionary pilot。它不是 Journal of Econometrics 2025 類 multimodal NLP replication，也沒有高頻事件窗。目的只是檢查：用 Fed 官網 speech text + 透明 dictionary score 建出的 GDP / inflation / labor forecast-revision proxy，是否能在日頻資料上對 SPY / QQQ / TLT / IEF 的波動與 5d left-tail target 產生可檢定的增量訊號。

## 相關知識庫脈絡

- `research_program.md:1144`：原始 backlog 條目。
- knowledge 搜尋顯示已有多個 FOMC / Fed event 結果，多數強策略 claim 失敗或只支援 event-awareness；K1363 與它們的差別是 **between-meeting speech**，不是 FOMC decision-day shock。
- K1360 / K1365 的方法教訓：overlapping 5d target 必須用 HAC；free public proxy 結果不可升格成原始文獻機制。

## 文獻定位

- Gorodnichenko, Pham, and Talavera (2025), *Mind Your Language: Market Responses to Central Bank Speeches*, Journal of Econometrics：直接動機，speech-implied forecast revisions 可連到 equity / bond volatility 與 tail risk。
- Jefferson (2025), *Reading between the Lines? Textual Analysis of Central Bank Communications*：Fed 官方 speech，說明 textual analysis 與 central-bank communication 對市場的用途。
- Swanson and Jayawickrema (2024), *Speeches by the Fed Chair Are More Important Than FOMC Announcements*：支持 chair-weighted speech channel。
- Cieslak and Schrimpf (2019), *Non-monetary News in Central Bank Communication*：央行溝通可包含 growth / inflation news，而非純 policy-rate shock。

## 資料

- Fed speech corpus：Federal Reserve Board official speech pages，index URL `https://www.federalreserve.gov/newsevents/speech/{year}-speeches.htm`。
- Years requested：2020-2026。
- Parsed speeches total：526。
- Between-meeting speeches used：477。
- Speech sample：2020-01-08 至 2026-06-22。
- FOMC calendar：Federal Reserve official FOMC calendars，解析出 44 個日期；speech date 若在 parsed FOMC date 的 +/-1 business day 內就排除。
- Market data：`yfinance` daily adjusted OHLCV，`auto_adjust=True`。
- Assets：SPY / QQQ / TLT / IEF。
- Market sample：2020-01-02 至 2026-06-22，共 1,625 trading days。

## 方法

每篇 speech 先用透明 dictionary score GDP / inflation / labor 三類 forecast-revision tone。句子同時包含類別詞與方向詞時才累計 tone；有 outlook / forecast / expect 類詞時加權。Primary signal 是：

```text
forecast_revision_shock = abs(growth_revision) + abs(inflation_revision) + abs(labor_revision)
forecast_revision_shock_z_l1 = rolling z-score(raw shock, 126d), then signal.shift(1)
```

回歸 target：

- `log_rv_1d`：close-to-close squared log return proxy。
- `log_forward5_rv`：5 trading-day forward RV proxy。
- `left_tail5`：forward 5d cumulative return 是否落在該 asset full-sample 5% tail。

Controls：

- HAR daily / weekly / monthly lagged log-RV。
- Lagged Parkinson range variance proxy。

Inference：

```text
target_t ~ forecast_revision_shock_z_{t-1} + HAR controls_{t-1}
```

使用 OLS-HAC / Newey-West `maxlags=5`。Discovery bar 採 Harvey-style positive `t >= 3`，並對 12 個 primary asset-target tests 做 BH q-value。

## Lookahead 防線

| 風險 | 防線 |
|---|---|
| speech same-day impact 被拿來預測 same-day return | speech calendar date 先 map 到下一個可交易日，再用 `z.shift(1)` 產生 `*_z_l1` |
| HAR controls 混入當日 target | `har_d_l1`, `har_w_l1`, `har_m_l1`, `range_l1` 全部用 `.shift(1)` |
| FOMC decision-day 混入 | parsed FOMC date +/-1 business day 的 speeches 排除 |
| overlapping 5d target p-value 過度樂觀 | HAC `maxlags=5`；結果仍列為 diagnostic |
| dictionary proxy 過度宣稱 | verdict rule 要求 >=2 primary tests 同時過 `t>=3` 與 BH q<=0.05 才能強 claim |

## 結果

Verdict：`NULL_PUBLIC_DICTIONARY_PROXY`。

Primary signal 12 個 asset-target tests：

- positive Harvey `t >= 3`：0/12。
- absolute Harvey `|t| >= 3`：0/12。
- positive discovery pass with BH q<=0.05：0/12。

最強的正向 primary cells 仍很弱：

| Asset | Target | Coef per 1sd signal | HAC t | BH q primary |
|---|---|---:|---:|---:|
| SPY | `log_rv_1d` | +0.0332 | +1.60 | 0.654 |
| IEF | `log_rv_1d` | +0.0270 | +1.22 | 0.667 |
| TLT | `log_forward5_rv` | +0.0225 | +1.03 | 0.730 |
| IEF | `log_forward5_rv` | +0.0150 | +0.74 | 0.781 |

最負的 primary cell 是 SPY `left_tail5`，coef -0.0085、HAC t=-2.65、BH q=0.097。方向不是 tail-risk prior，而且未達 Harvey absolute threshold。

Secondary high-signal diagnostic 也不支持：在 lagged speech-shock z-signal > 0 的日期中取 top quintile（48 天），SPY / QQQ / TLT / IEF 的 forward 5d RV Welch p 分別為 0.880 / 0.607 / 0.808 / 0.497。

## 解讀

1. 免費 Fed Board speech + dictionary score 不支持「between-meeting Fedspeak forecast-revision shock 是 robust equity/bond tail-vol prior」。
2. 這不能反駁原始文獻，因為 K1363 沒有完整 FOMC-member speech corpus、Reserve Bank presidents、speech time stamp、高頻事件窗、或 multimodal NLP forecast-revision model。
3. 若要重開，下一版應抓全 FOMC member speech corpus（Board + Reserve Banks）、使用 sentence-level transformer / FinBERT 類 forecast-revision classifier，並用 intraday event-window RV / yield futures reaction 做直接測試。

## 輸出

- `K1363.py`：可重跑腳本。
- `K1363_results.json`：完整 structured results。
- `K1363_regression_table.csv`：所有 asset × signal × target HAC regression。
- `K1363_top_quintile_diagnostics.csv`：secondary high-signal diagnostic。
- `data/K1363_speech_corpus.csv`：parsed Fed speech corpus。
- `data/K1363_speech_corpus_between_meetings.csv`：排除 FOMC window 後 corpus。
- `data/K1363_daily_speech_signal.csv`：交易日 speech signal panel。
- `data/K1363_panel_{SPY,QQQ,TLT,IEF}.csv`：asset-level regression panels。
- `data/raw/fed_speech_index_*.html`、`data/raw/fed_fomc_calendars.html`、`data/raw/*_ohlcv.csv`：index/calendar/market raw cache。逐篇 official speech HTML 可由 `--refresh` 或一般重跑再生；版本控制中的 byte-trace 以 `data/K1363_speech_corpus*.csv` 的 URL / title / speaker / score 欄位為準，避免提交數百個大型官方 HTML snapshot。
- `figures/k1363_primary_hac_tstats.png`。
- `figures/k1363_signal_timeline_spy.png`。
- `codex_review.md`：source-level review。

## 重跑

```bash
uv run python experiments/k1363/K1363.py
```

強制重抓官方頁面與 yfinance：

```bash
uv run python experiments/k1363/K1363.py --refresh
```
