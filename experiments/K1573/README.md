# K1573 — 半導體產業政策補助公告對 sector volatility 的 spillover

**Status: COMPLETE — NULL result**

## 核心發現（一句話先講）

CHIPS Act 半導體補助公告日（2024-02 到 2025-08 共 17 起 preliminary award / final award / delay / equity-swap events）的隔日起 5 個交易日（T+1..+5），SMH/SOXX/NVDA/AMD/ASML/AMAT/LRCX/KLAC/INTC/MU/TSM/GFS/WOLF 13 檔半導體相關 ticker 的 daily squared log return（RV proxy）相對前 25 個交易日（T-30..-6）baseline **沒有偵測到顯著 announcement effect**：aggregate post/pre ratio = **0.950**, 一邊 sign test p = **0.997**, 146 個 per-event tests **0 個通過 Bonferroni (alpha=0.05/146)**。

**但 NULL ≠ no effect at all**：N=17 events × 12 tickers (WOLF 雖在 sample 但 sparse) 在 Bonferroni 0.05/146 ≈ 0.00034 的極嚴格門檻下，需要 ratio ≥ ~3-5 才會 single-event 顯著；diffuse / heterogeneous 效應會被打散成 NULL。本實驗結論限定為「**沒有強烈、集中、系統性的正向 RV spike**」，不能等同「補助公告對半導體沒影響」。

## 動機與差異化

CHIPS Act 是 2024-2026 半導體產業核心政策議題，學界對其 financial market reaction 的研究剛起步。一般直覺：(a) award 公告應該降低不確定性 → RV 下降，或 (b) award 帶來大量資本支出 / supply-chain re-shuffle 預期 → RV 上升。Delay / equity-swap (Trump 2025-08-22) 屬於負面或非預期 shock，預期有非對稱反應。

**vs K1425（同樣是半導體）**：K1425 看 sector ETF 的 cross-sectional alpha attribution（PCA / sector-factor），是 contemporaneous risk decomposition，不是 event study。K1573 看的是 event-window time-series vol，是完全獨立 angle。兩 K 共用半導體 ticker 但 research question 不重疊。

**vs feed 既有文章**：暫無直接 overlap（半導體補助 + event vol spillover 是新題）。本實驗結果若發 article 應以「半導體 CHIPS 補助公告日沒掀起 sector 波動」為主軸（surprise / null finding，與「補助 = 大事 → 應該大震」的市場直覺相反）。

## 資料

### Events（events.csv）

17 個事件，全來自 commerce.gov 公開 press releases（preliminary memorandum, final award, delay statement, equity-swap announcement）：

| 類型 | 數 | 範例 |
|---|---|---|
| preliminary `award` | 8 | Intel 2024-03-20 $8.5B; TSMC AZ 2024-04-08 $6.6B; Samsung 2024-04-25 $6.4B; Micron 2024-04-26 $6.1B |
| `award_final` (final agreement) | 6 | TSMC AZ 2024-11-15; Micron 2024-12-03; Samsung 2024-12-10 (downsized to $4.745B); Intel 2025-01-15 ($7.86B) |
| `delay` | 2 | Wolfspeed 2025-02-14; Intel 2025-03-07 (Trump renegotiation) |
| `equity_swap` | 1 | Intel 2025-08-22 (10% equity stake) |

所有日期可在 commerce.gov press release index 或當事公司 8-K filings 驗證。

### Tickers (13 used, 0 missing)

- Industry ETF / bellwether (spillover targets, 8): SMH, SOXX, NVDA, AMD, ASML, AMAT, LRCX, KLAC
- Primary recipients tradeable on US exchange (5): GFS, INTC, TSM, MU, WOLF
- 排除：SSNLF (Samsung OTC 流動性差), SK hynix / Polar (no US-tradeable proxy)

### Sample

yfinance auto_adjust=True，2023-10-22 ~ 2025-12-20（543 交易日；覆蓋最早事件前 120 cal-day buffer 至最晚事件後 120 cal-day buffer）。

## 方法

### Window 定義（lookahead-safe）

| Window | Relative trading days | 含 T=0? |
|---|---|---|
| Pre baseline | T-30 ~ T-6 (25 days) | 否 |
| Gap | T-5 ~ T0 | (拋棄) |
| Post event | T+1 ~ T+5 (5 days) | 否 |

事件日 T=0 = `event_date` 所在第一個 ≥ event_date 的交易日（週末/假日公告會延到下一交易日；conservative，因會錯過 first reaction day）。

### Effect metric

`ratio = mean(r²[T+1..+5]) / mean(r²[T-30..-6])`。Ratio > 1 = post 比 pre 波動大；< 1 反之。

### Significance: random-anchor null bootstrap

從同一 ticker 的 r² 序列，隨機抽 anchor position，用同樣 [-30,-6] / [+1,+5] 結構算 null ratio，1000 reps。`p_value = mean(null_ratios ≥ observed_ratio)` 是 one-sided right-tail。`np.random.default_rng(seed=42)`。

### Multiple testing

Per-event bootstrap p-values: Bonferroni alpha = 0.05 / 146 ≈ 3.4e-4。Per-ticker pooled sign tests 與 per-type pooled tests 報告 unadjusted（descriptive only，不當 confirmatory）。

### Aggregations

- **H1 per-ticker pooled**: 每檔 ticker across 全部 events 的 mean ratio + binomial sign test (ratio>1 vs 0.5)。
- **H2 spillover**: 每個 event 比較 primary recipient 自身 ratio vs SMH/SOXX ETF ratio。
- **H3 by event type**: 按 award / award_final / delay / equity_swap 分組 pooled mean ratio。

## 結果

| 指標 | 值 |
|---|---|
| Aggregate post/pre ratio | **0.950** |
| Aggregate frac ratio>1 | 0.404 (59/146) |
| Pooled sign test (one-sided p) | **0.997** (post 不會系統性高於 pre) |
| Bonferroni-significant per-event tests | **0 / 146** |
| Unadjusted significant per-event tests (p<0.05) | (極少；見 results.json) |

### H1 per-ticker（top 5 與 bottom 5）

| Ticker | N events | mean ratio | sign test p |
|---|---|---|---|
| NVDA | 17 | 1.322 | 0.500 |
| INTC | 4 | 1.317 | 0.687 |
| SMH | 17 | 1.044 | 0.834 |
| LRCX | 17 | 1.010 | 0.834 |
| SOXX | 17 | 1.004 | 0.500 |
| ... | | | |
| AMAT | 17 | 0.819 | 0.975 |
| ASML | 17 | 0.708 | 0.975 |
| MU | 2 | 0.700 | 0.750 |
| GFS | 2 | 0.411 | 1.000 |
| TSM | 2 | 0.354 | 1.000 |

**觀察**：NVDA / INTC 點估計 ratio > 1.3，但 sign test 不顯著（散得開）；上游設備股 (AMAT, ASML) 反而傾向 post < pre（unsupplyshock 解釋 or 高 base period 偶發雜訊）；Primary recipients TSM/GFS/MU 自身在公告後 r² 反而較低（解讀：事件已 priced in，公告日 + 隔週只是不確定性 resolve）。

### H3 by event type

| Event type | N tests | mean ratio | frac>1 |
|---|---|---|---|
| `award` (preliminary) | 68 | 1.136 | 0.471 |
| `delay` | 17 | 1.024 | 0.412 |
| `equity_swap` | 9 | 0.797 | 0.444 |
| `award_final` | 52 | 0.709 | 0.269 |

**觀察（descriptive only，未調 multiple testing）**：preliminary `award` 是唯一 mean ratio > 1.1 的類別；`award_final` 反而低 — 一致於 financial-econ event-study 常見模式：**新資訊在 preliminary announcement 已釋出，final agreement 只是 administrative completion** → 真實 vol reaction 集中於前端，且即便如此整體 ratio 1.14 也未通過 strict test。`equity_swap` (Intel 2025-08-22) N 太小 (9 tickers × 1 event)，點估計 0.797 不可解讀。

### H2 Spillover（per-event primary vs SMH/SOXX）

Primary-recipient ratio 與同日 SMH/SOXX ratio 沒有系統性同向放大 — 個別事件存在 spillover (e.g. INTC 2025-01-15 自身 ratio 2.18 + 同日 SOXX 1.03)，但 cross-event 平均無顯著 spillover 模式。完整對照在 `k1573_results.json` 的 `H2_spillover_per_event`。

## 結論（誠實版）

CHIPS Act 半導體補助公告 — **包含正面 award、負面 delay、罕見 equity-swap** — 在 2024-2025 sample 期間，**沒有引起半導體 sector ETF 或 bellwether ticker 的系統性 RV 上升**。aggregate post/pre ratio < 1（post 反而略低），sign test 強烈反方向（p=0.997 表示「post > pre」幾乎不可能是 true effect 的證據），無單一 event-ticker 對通過 Bonferroni。

**為什麼可能 NULL**：
1. **資訊預期已 priced in**：CHIPS Act 自 2022 立法後，市場早知道哪幾家會領補助；preliminary 公告只是時間問題，邊際資訊量低。
2. **公告金額 vs 公司市值不對稱**：Intel $8.5B grant ≈ 其市值 5%，但攤到未來 5-7 年資本支出，對短期 vol impact 弱。
3. **High base volatility**：2024-2025 半導體在 AI cycle 已是高 vol，CHIPS 公告作為 marginal news 被 swamped。
4. **真正的 announcement effect 可能在 intraday**：本實驗用 daily r²，5min intraday RV 或許能 detect 公告小時內的 micro-spike，後續 K-experiment 可考慮。

**不過度宣稱**：本實驗無法 rule out (a) 個別事件存在效應（INTC 2025-01-15 self ratio 2.18 可能是真的，只是孤點），(b) 較長 window (T+22) 或不同 metric (jump-style range, log r²)， (c) intraday timing 效應。N=17 events × 5d window 在強多重檢定下 power 天然低；報告為 descriptive null。

## 產出檔案

- `events.csv` — 17 events with source notes (commerce.gov references)
- `k1573.py` — 完整可重現腳本 (seed=42)
- `k1573_results.json` — 所有數字（per-ticker + per-type + per-event + bootstrap p-values + verdict）
- `event_ticker_results.csv` — 146 per event-ticker tests 明細
- `fig_a.png` — 12 ticker post/pre ratio boxplot + null line (ratio=1)

## 防錯與限制

- **無 lookahead**：T=0 嚴格不入 post window；pre window 結束於 T-6 留 5 個 gap day 防 announcement leakage。POST_START_REL=1, PRE_END_REL=-6 寫死在程式碼。
- **Holiday alignment**: 週末/假日公告（如 2024-04-26 Friday → T=0=Mon 2024-04-29 if Sat-Sun pattern）conservative 會錯過 first reaction day；results.json 有 `holiday_alignment_note` 揭露。
- **seed 全固定**：np.random.default_rng(42) cover bootstrap；無其他隨機程序。
- **Null distribution 包含 event-window 本身作為 anchor**：random-anchor 從整段 sample 抽，可能包含其他 event date 鄰近，這是 conservative null（會稍微膨脹 null mean → 推 observed ratio 顯得更小 → p 偏大）。
- **Multiple testing**：per-event Bonferroni 嚴格；per-ticker / per-type pooled 不調，僅 descriptive。
- **N small**: 17 events × 12 tickers, primary recipients per-ticker N=2-4。Power 對 moderate effect (ratio 1.2-1.5) 不足。
- **資料來源**：events.csv 所有 dates 可在 commerce.gov press release archive + 公司 8-K filings 重複驗證；prices 來自 yfinance auto_adjust=True。

## Review

Codex CLI (gpt-5.4) 一輪 review: **CONDITIONAL_PASS**。
- No critical methodological bugs (window alignment, T+1 exclusion, p-value direction, seed coverage all OK)
- Required fix (applied): explicit missing-ticker reporting in results.json
- Minor fixes (applied): removed dead `stationary_bootstrap_indices` helper, added low-power caveat in NULL verdict, added holiday-alignment note
- 結論：腳本 methodologically sound，NULL result 可信。

## 可發 article 嗎

**可以，但定位為 "surprising NULL / market efficiency demo"**：
- Hook: 「CHIPS Act 撒下 $400B+ 補助，半導體股波動率公告日…幾乎沒反應？」
- 角度：information already priced in / market efficiency / 為什麼公告日不再是大事
- Caveats 一定要寫清楚（N 小、Bonferroni 嚴格、intraday 可能不同、不否認個別 event 效應）
- 避免標題殺：「補助無用」、「政策無效」這類過度延伸
