# K1583: Conditional / Sequential MCS meta-evaluation of K1380_v4 SPY 17-spec horse race

## Motivation

K1380_v4 跑了 17 個 SPY vol forecast spec（GARCH-X / MIDAS A1-A5, A2f/A4f, A3f, A2n/A4n, B1-B3, C2-C3, B0），OOS 2019-01-02 → 2026-05-20。原報告用 pointwise QLIKE 排名，但**沒有 multiple-testing**，無法說「哪些 spec 顯著優於其他」。

K1583 補上 **Model Confidence Set (MCS)** 的三層分析：
1. **Unconditional MCS** — 全期 16 specs（C1 因 0 valid samples 排除）的 set selection
2. **Conditional MCS** — VIX regime (high≥20 / mid / low<15) + recession (NBER USRECD) 各自 subsample MCS（Liu-Pelger-Yang 2025 JRSS-B kernel-weighted approach 的粗近似）
3. **Sequential drift** — Rolling 252-day window MCS，stride 21 days，看 top-1 spec 是否隨時間漂移

References:
- Hansen, Lunde, Nason (2011) — original MCS T_R statistic
- Liu, Pelger, Yang (2025) JRSS-B qkag066 — conditional MCS kernel-weighted approach
- Hansen (2005) — Sequential SPA
- arXiv 2505.21278 — Online/sequential MCS

## Method

### Loss inventory
- 來源：`storage/k1380_v4/spy_losses.npy`（K1380_v4 cached losses，shape `(17, 1866)`）
- Loss proxy：Patton (2011) QLIKE = `r²/σ² - log(r²/σ²) - 1`
- OOS sample：2019-01-02 to 2026-05-20

### MCS implementation
- Routine：`src/volpred/stats/mcs.py::model_confidence_set` (HLN T_R variant, stationary bootstrap, HAC SE)
- α = 0.10 (保留 90% confidence set)
- Bootstrap：B = 1000（static）, B = 500（rolling — 預算限制）
- Seed = 42

### Conditioning variables
- VIX：`spy_vix_qqq_eem_fez_2000-2026.csv` `vix_close` (contemporaneous — characterizes regime, not predictor)
- Recession：FRED `USRECD` daily, ffill across non-trading days
- VIX thresholds：high ≥ 20、low < 15、mid 15-20

### Cross-asset pooling: DISABLED
依 K1355 禁 asset-day stacked panel 規則，K1258 multi-asset losses 只 inventoried 不 pooled。

### Lookahead policy
- Ex-post meta-analysis on already-realized losses
- Conditioning variables describe **the day's realized state**, not future
- Rolling MCS at origin t uses **only past 252 days** loss differentials → 無 forward leak

## Key Results

### Unconditional MCS（α=0.10, B=1000）
**16/16 specs all retained**，p_set = 0.438（停止 elimination 的 set-level p-value）。

⚠️ p-value 是 MCS survivor-set p（停止淘汰時 worst-model 的 bootstrap p），**不是每個 spec 的 individual score**。Identical values 反映演算法在第一輪就無法拒絕 → 整 set 共享 stopping p。

### Conditional MCS

| Regime | N days | p_set | MCS size |
|--------|--------|-------|----------|
| VIX high (≥20) | 717 | 0.384 | 16 |
| VIX mid (15-20) | n/a | n/a | 16 |
| VIX low (<15) | n/a | n/a | 16 |
| NBER recession | 43 (raw 61, joint-NaN 後) | underpowered | 16 |

**結論**：無論 regime，16 specs 都無法被 MCS 區別 → **K1380_v4 17-spec horse race 的 GARCH-X / MIDAS 變體在 QLIKE loss 上統計不可區分**。

### Sequential drift（rolling 252-day, stride 21 days）
- 77 個 rolling window
- 74/77 window 保留 16/16 specs
- 3/77 window (2021-11-30, 2021-12-30, 2022-01-31) 縮到 15/16，top_model = B0
- Top_model 在不同 window 切換（A2, A4, B0, C3 等），但這多半是同 p-value 下 mean QLIKE tie-break 的結果，**不是真 regime shift evidence**

## Verdict

**CONDITIONAL_PASS** (Codex 82/100, 2026-06-30)

### Limitations（誠實揭露）

1. **單資產 (SPY only)**：K1258 multi-asset panels inventoried but NOT pooled (K1355 rule)。跨市場 conditional 需 per-asset MCS 或 panel-HAC，out of scope。
2. **Subsample MCS = 粗近似**：proper conditional MCS (Liu-Pelger-Yang 2025) 用 kernel-weighted loss differentials，本實驗未實作。
3. **Recession N 小**：43 days (COVID 2020-03 to 2020-04)，underpowered；結論 descriptive only。
4. **Sequential drift ≠ formal break test**：rolling MCS top-1 是 visualization aid，非 Inoue-Jin-Rossi online SPA。
5. **Tie-breaking**：'top-1' 用 min mean QLIKE within tied MCS p-values，會偏向 low-mean models；alternative tie-break 會改變 timeline。

## Implication

K1380_v4 17-spec horse race 的 QLIKE differences 在 MCS 統計上 **不可區分**。pointwise QLIKE ranking 可能反映 noise 而非真 model superiority。未來 K-experiments 比較 GARCH-X / MIDAS variants 應預期：差異難以 MCS 顯著區別 → 應把 effort 投入 conceptually distinct models（jump 軸 / regime-switching / 外生 regressor），不是 GARCH parameterization 變體。

## Files

- `k1583.py` — main script (25KB)
- `k1583_results.json` — full results JSON (51KB)
- `k1583_conditional_mcs_heatmap.png` — 16x4 regime heatmap (unconditional + VIX high/mid/low + recession)
- `k1583_sequential_winner_timeline.png` — top_model timeline + mcs_size annotation

## Lineage

- 來源 task：`K1583` (next_tasks.json, source=research_backlog_auto, source_line=484)
- 派工 fire：hourly-11 (2026-06-30 11:50 CST claim)
- 完工 fire：hourly-12 (2026-06-30 12:32 CST close + Codex review + README)
- Codex review：`codex-cli 0.142.3` read-only review, verdict CONDITIONAL_PASS 82/100
