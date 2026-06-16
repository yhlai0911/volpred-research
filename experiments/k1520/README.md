# K1520: Regime-aware in-context analog vol forecast vs HAR

- **K id**: K1520
- **Status**: completed
- **Created**: 2026-06-17
- **Task source**: `research_regime_aware_in_context_llm_vol_vs_har_regime_ll`
- **Verdict**: `NULL`

## Question

這題檢驗 regime-aware in-context learning 這條線在 VolPred 的標準下是否真有增量。

原始 backlog 方向是：

> 用 LLM few-shot in-context learning 預測 SPY realized vol，分 high-vol / low-vol / trend-break regime 比較 LLM / HAR / 結合模型。

本輪沒有直接呼叫外部 LLM API。理由是：互動式 LLM output 若沒有固定 prompt、model version、temperature、raw responses、retry policy，很難成為可重跑的研究證據。因此 K1520 先測一個可審計 surrogate：

> 把「in-context demonstrations」轉成透明的 historical nearest-neighbor analog retrieval，檢驗 regime-aware demonstration selection 這個核心機制是否能打贏 HAR。

## Literature Preamble

1. **Asaad, Hamidi, and Bereyhi (2026), arXiv:2603.10299**  
   提出 regime-aware financial volatility forecasting via in-context learning，主張高波動 regime 下改善較明顯。
2. **Corsi (2009)**  
   HAR-RV 是 realized volatility forecasting 的基準模型，核心是 daily / weekly / monthly multi-scale persistence。
3. **In-Context Learning Under Regime Change (arXiv:2604.16988)**  
   regime change 下 ICL 需要偵測變化、下修 obsolete evidence 權重，正好對應本題的 conditional retrieval。
4. **專案既有 K149**  
   非參數 regime matching ICL vs GJR 在 daily r² target 上 0/48 cells 顯著勝出，支持「daily r² ceiling」疑慮。

## Data

- Source: yfinance
- Tickers: `SPY`, `^VIX`
- Panel: 2009-12-22 to 2026-06-16 after feature warmup
- OOS: 2020-01-02 to 2026-06-16
- OOS observations: `1,621`

## Method

### Target

Forecast origin `t` predicts next trading day variance:

- `target = r_{t+1}^2`

All features are available at forecast origin `t`.

### Baselines

1. **HAR**
   - rolling OLS on `log_rv_d`, `log_rv_w`, `log_rv_m`
2. **HAR+VIX**
   - same HAR features plus `log(VIX_{t-1})`
   - this is the primary fair baseline because analog retrieval also uses `VIX_{t-1}` / VIX-defined regimes

### ICL surrogate models

1. **Analog-All**
   - nearest-neighbor historical analogs over lagged volatility / return / VIX features
   - no regime restriction
2. **Analog-Regime**
   - same retrieval, but candidates restricted to same causal regime if enough neighbors exist
3. **Combo-HAR-Regime**
   - geometric mean of HAR and Analog-Regime
4. **Combo-HARVIX-Regime**
   - geometric mean of HAR+VIX and Analog-Regime

Regime labels:

- `low`: `VIX_{t-1}` below expanding 20% quantile
- `high`: `VIX_{t-1}` above expanding 80% quantile
- `trend_break`: `|log_rv_d - log_rv_m|` above expanding 90% quantile
- `mid`: remaining days

All quantile thresholds are expanding and shifted by one day.

## Lookahead Protection

- Forecast origin `t` uses returns through `t`.
- VIX feature is `VIX_{t-1}`, not same-day VIX.
- Training rows require `target_date <= current forecast origin date`.
- Regime thresholds are expanding quantiles shifted by one day.
- No external LLM response is used as experimental data.

## Main Results

### Overall

| Model | Mean QLIKE | Improvement vs HAR | Improvement vs HAR+VIX | DM vs HAR+VIX |
|---|---:|---:|---:|---:|
| HAR | `-5.1882` | — | — | — |
| HAR+VIX | `-6.4260` | `+23.86%` | — | `t=-4.24`, p=`2.26e-05` vs HAR |
| Analog-All | `-5.6602` | `+9.10%` | `-11.92%` | `t=+4.42`, worse |
| Analog-Regime | `-5.8500` | `+12.76%` | `-8.96%` | `t=+2.63`, worse |
| Combo-HAR-Regime | `-5.8898` | `+13.52%` | `-8.34%` | `t=+3.25`, worse |
| Combo-HARVIX-Regime | `-6.3685` | `+22.75%` | `-0.90%` | `t=+0.77`, NS |

Interpretation:

- If the baseline is pure HAR, analog / regime retrieval looks useful.
- But HAR+VIX is a much stronger and fairer baseline.
- After controlling for the VIX information channel, regime-aware analog retrieval adds no formal QLIKE improvement.

### Regime Boundary

OOS regime counts:

- `high`: `334`
- `low`: `104`
- `mid`: `1,038`
- `trend_break`: `145`

Key regime findings:

- High-vol regime: Analog-Regime beats pure HAR directionally, but still loses to HAR+VIX by `17.95%` QLIKE.
- Low-vol regime: regime analogs are significantly worse than HAR+VIX.
- Mid regime: Combo-HARVIX-Regime is essentially tied with HAR+VIX (`+0.026%`, DM p=`0.980`).
- Trend-break regime: Combo-HARVIX-Regime improves `+3.08%` vs HAR+VIX, but DM p=`0.730`, not evidence.

## Verdict

**NULL**.

K1520 does not support a claim that regime-aware in-context retrieval adds robust predictive value beyond a HAR+VIX baseline.

The useful finding is a boundary condition:

1. Regime-aware analog retrieval can beat **pure HAR**.
2. The gain is absorbed by adding a simple lagged VIX term.
3. Therefore the apparent ICL edge is mostly VIX/regime information, not a distinct LLM-style reasoning advantage.

## Honest Limits

- This is not a live LLM API benchmark.
- It tests the reproducible retrieval/demonstration-selection mechanism behind ICL.
- Target is daily close-to-close squared return, not high-frequency realized variance.
- A true LLM follow-up must freeze prompts, model version, temperature, raw responses, and retry policy before claims are credible.
- If a future LLM beats HAR+VIX, it must also beat this transparent analog baseline.

## Files

- `k1520.py`
- `k1520_results.json`
- `codex_review.md`
- `figures/k1520_rolling_qlike.png`
- `figures/k1520_regime_improvement.png`

## Reproduce

```bash
uv run python experiments/k1520/k1520.py
```
