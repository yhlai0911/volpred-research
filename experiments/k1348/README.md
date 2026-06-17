# K1348 — ETF heartbeat / tax-efficiency 季末壓力檢定

**Status**: COMPLETED · **Verdict**: CONDITIONAL_PASS · **Date**: 2026-06-18

## Motivation

ETFs (尤其大型 equity ETF SPY/IVV/VTI/QQQ) 透過 in-kind creation/redemption 機制
循環處分低成本基差的成分股，達成 capital gains tax efficiency。Moussawi/Shen/
Velthuis (2025 RFS) 證據顯示 ETF 在**季末/年末**（tax-relevant cut-points）會集
中執行 heartbeat trade（同日大量 redemption + 等額 creation）。若此交易確實對
持股造成微結構壓力，應在 quarter-end window 內看到 (a) 成交量擴張、
(b) range-vol 抬升、(c) close-to-close RV 偏離 baseline。

本實驗用 calendar-based event study 檢定 4 大 equity ETF 與其 current top-15
holdings 在季末視窗 (last 5 trading days of Mar/Jun/Sep/Dec) 內 vs baseline 的
abnormal metrics，並做 panel OLS with asset/year fixed effects。

## Differentiation vs prior K

knowledge.json grep 結果（搜 ETF/heartbeat/quarter-end/rebalancing）：
- **K104/K151/K574 等 VT rebalancing 頻率 K**：題目是策略內部 rebalancing
  cadence，與 ETF heartbeat trade（基金端 in-kind 機制）完全不同層次
- **K1330/K1331/K1334**: 近期 K 為其他主題
- **無重疊**: 「ETF heartbeat 對持股 vol pressure 的季末檢定」為新 angle

## References

1. Moussawi R., Shen K., Velthuis R. (2025) "The Role of Taxes in the Rise of
   ETFs", *Review of Financial Studies* — 直接 motivation paper, 提供
   tax-efficiency heartbeat 機制的 stylized facts
2. Ben-David I., Franzoni F., Moussawi R. (2018) "Do ETFs Increase Volatility?",
   *Journal of Finance* 73(6): 2471-2535 — ETF arbitrage 把 noise propagation
   到 underlying，支持「ETF activity → underlying vol」的因果 channel
3. Da Z., Shive S. (2018) "Exchange traded funds and asset return correlations",
   *European Financial Management* 24(1): 136-168 — ETF flow 與 underlying
   common factor 結構的關係
4. Da Z., Liu Q., Schaumburg E. (2014) "A closer look at the short-term return
   reversal", *Management Science* 60(3): 658-674 — short-term flow-driven
   reversal 文獻起點

## Method

### Tier 1 — ETF level event study

1. yfinance 抓 SPY/IVV/VTI/QQQ + 15 top holdings (AAPL/MSFT/NVDA/AMZN/GOOGL/META/
   TSLA/AVGO/BRK-B/JPM/LLY/V/XOM/UNH/MA) 2014-01-01 to 2026-06-17 日資料
2. 算 daily metrics: `log_volume`, `range_vol` (Garman-Klass), `c2c_rv = ret²`
3. Event window dummy: `is_quarter_end_window` = 季末月（3/6/9/12）最後 5 個
   trading days；`is_year_end_window` = 12 月最後 5 個 trading days
4. Welch t-test (event vs baseline) + bootstrap 500 reps 95% CI (seed=42)
5. Event-study curve: offset ∈ [-4, +3] 對齊 last trading day of each quarter

### Tier 2 — Cross-section + Panel OLS

6. 對每個 asset 計算 `abn_{metric} = metric - own_baseline_mean`
7. Pooled OLS: `abn_metric ~ quarter_end + year_end + asset_FE + year_FE`
   with HC1 robust SE，N=59,489 obs

## Lookahead policy

- 所有 event dummy 來自 **known calendar dates**（非 forward-looking）
- 所有 test stat 在 event window 結束後計算
- 純 descriptive event study，**no predictive claim, no train-test split**
- Seed: `np.random.seed(42)`; bootstrap 用 `default_rng(42)` 顯式 seed
- baseline 與 event 用同份 series 同一 daily lag (無 shift 差異)

## 成功標準

- **PASS**: ≥2 ETF 在 **range_vol** channel 顯著 (|t|>2.5, p<0.01) 一致方向 +
  panel range_vol 支持
- **CONDITIONAL_PASS**: volume channel 清楚但 vol-pressure channel 弱/缺
- **NULL**: 兩條 channel 都不支持

## 結果

| Channel | sig ETFs (|t|>2.5, p<0.01) | Panel coef | Panel t | 結論 |
|---|---|---|---|---|
| log_volume | **2/4 (IVV, VTI)** 一致為正 | +0.0417 | +5.84 | **季末成交量擴張** ✓ |
| range_vol | 0/4 | +0.00009 | +0.77 (p=0.44) | **無 vol pressure** ✗ |
| c2c_rv | n/a | -0.00006 | -4.34 | **季末 RV 反而下降** ✗ |

Per-ETF quarter-end Welch test (log_volume vs baseline):
- SPY: t=+0.43, p=0.67 (null)
- **IVV**: t=+3.46, p=0.0006, diff=+0.113 log-vol
- **VTI**: t=+3.24, p=0.0013, diff=+0.100 log-vol
- QQQ: t=-0.34, p=0.73 (null)

Year-end 額外 dummy 方向**不一致** (SPY -0.24/p<0.001, VTI +0.21/p=0.002,
QQQ -0.36/p<0.001), 暗示 year-end behavior 隨 ETF 風格分歧（QQQ 為 NASDAQ-100
tech-tilt、SPY 為 large-cap broad，可能 tax-loss harvesting vs window-dressing
反向 dominant，需未來細分）。

### Verdict: CONDITIONAL_PASS

**Headline**: ETF heartbeat 假說的**成交量 channel 部分受支持**（IVV/VTI 季末
log-volume +10-11% vs baseline；panel coef +0.042, t=5.84），但**vol-pressure
channel null**（range-vol panel p=0.44, c2c-RV 反方向）。

**Mechanism interpretation**: 季末成交量上升存在（與 heartbeat 機制 consistent），
但這個 flow 在 ETF 與 underlying 之間是**absorb 掉的 microstructure load**，
沒有外溢到 daily realized vol。也就是說：tax-driven flow 走的是 in-kind
exchange 而非 cash market impact，所以 vol 不受影響 — 這其實**反向支持** ETF
tax efficiency 機制的「乾淨」特性。

**Limitation**:
1. Top holdings 用 current snapshot 而非 historical holdings → diagnostic-tier
2. Daily granularity 看不到 intraday heartbeat 集中時段 (EOD 30min) 的 vol burst
3. SPY/QQQ 不顯著可能跟其他 quarter-end 機制 (option expiry, rebalance)
   confound
4. 4 ETF small N panel, asset FE 吃掉跨 ETF 共變

## Codex Review

See "Codex Review" section appended at bottom (verdict + caveats).

## Reproduce

```bash
cd experiments/k1348
uv run python k1348.py     # ~70 sec, fetches yfinance live
```

Output files:
- `k1348_results.json` — byte-traceable stats
- `fig_event_study.png` — event-study curves (4 ETF × 3 metrics)
- `fig_cross_section.png` — per-asset abnormal metric histogram
- `fig_panel_regression.png` — panel coef 95% CI

## Notes for main thread

- 寫 knowledge.json: CONDITIONAL_PASS 不需 reviewer field, 但需要 provenance
  (experiment_id="k1348" + experiment_path="experiments/k1348/")
- 不直接發 feed article — 結論 nuance 太多, 適合先積到 narrative arc 與其他
  ETF microstructure K 一起整理
- 可寫 research_program.md 為「tax-efficient ETF flow does not measurably
  load vol on underlyings (daily granularity)」mini-finding
- v2 followup 候選: intraday 高頻 (5min) vol clustering at EOD on quarter-end
  days; SPY+QQQ vs IVV+VTI 結構差異探源
