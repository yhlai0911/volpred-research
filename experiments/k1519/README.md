# K1519: EPU 作為跨資產高波動 regime trigger

- **K id**: K1519
- **Status**: completed
- **Created**: 2026-06-17
- **Task source**: `research_epu_vol_regime_switching_trigger_incremental_pre`
- **Verdict**: `NULL`

## Question

這題檢驗 Baker-Bloom-Davis EPU 是否能作為跨資產高波動狀態的 **regime switching trigger**。

重點不是再做一次「EPU 對 HAR-RV / VIX 是否有線性增量」；K531、K1116、K1121 系列已多次顯示 EPU 類 alt-data 很容易被 VIX 或原生波動代理吸收。這次改問：

> 月頻 EPU 上升衝擊是否會提高 SPY / TAIEX 進入高波動狀態的機率？

## Literature Preamble

1. Baker, Bloom, and Davis (2016), *Measuring Economic Policy Uncertainty*, QJE: EPU 與企業股價波動、投資和就業下滑有關，且在控制 VIX 後仍看到政策不確定性通道。
2. OeNB WP 234, *Economic Policy Uncertainty and Stock Market Volatility*: 以 22 國月資料討論 EPU 與股市波動的 causal direction，估計 EPU 上升後股市波動增加。
3. Tzika and Pantelidis, *Economic policy uncertainty as an indicator of abrupt movements in the US stock market*: 用 two-regime switching model 連結 EPU 與美股 abrupt movements。
4. 專案既有 K531 / K1116 / K1121: EPU 作為線性增量預測因子大多 NULL；因此本題只測 regime trigger mechanism。

## Data

- `SPY`: yfinance adjusted close
- `TAIEX`: yfinance `^TWII`
- `EPU`: FRED `USEPUINDXD` daily Baker-Bloom-Davis EPU
- Sample after signal availability:
  - SPY: 2003-05-02 to 2026-06-16, `n=5,818`
  - TAIEX: 2003-05-02 to 2026-06-15, `n=5,668`

## Method

### Volatility state

每個資產各自用 daily log squared return 建 2-state Markov volatility-state model：

- target: winsorized `log(r_t^2)`
- model: `statsmodels.MarkovRegression(k_regimes=2, switching_variance=True)`
- state outcome: filtered high-vol probability
- high state: 依 filtered probability 加權後的 log-r² 均值較高者

這是 **Markov volatility-state proxy**，不是完整 Markov-switching GARCH likelihood。結論只能支撐 regime-state mechanism first pass。

### EPU trigger

EPU 訊號一律事前化：

- daily `USEPUINDXD` 先取月均值
- `epu_log_chg3m = log(EPU_m) - log(EPU_{m-3})`
- `epu_shock_high = epu_log_chg3m > expanding historical 75% quantile`
- month-M 訊號只在 `month_end + 2 business days` 後才 forward-fill 到 daily panel

這避免用尚未完整形成的當月 EPU 解釋同月日資料。

### Formal tests

每個資產跑 4 個 HAC tests：

- `high_prob ~ epu_shock_high`
- `low_to_high ~ epu_shock_high`
- `log_r2_winsor ~ epu_shock_high`
- `high_prob ~ epu_chg3m_z`

全部使用 Newey-West HAC `maxlags=21`，並在 `2 assets x 4 tests = 8` tests 上做 BH / Bonferroni correction。

## Main Results

### SPY

- EPU shock days: `1,290` / `5,818` (`22.2%`)
- High-vol probability:
  - normal: `0.544`
  - EPU shock: `0.576`
  - HAC t = `1.44`, p = `0.150`, BH p = `0.399`
- Low-to-high transition:
  - normal: `16.87%`
  - EPU shock: `15.89%`
  - HAC t = `-0.97`, p = `0.332`
- Log-r² conditional mean:
  - HAC t = `2.06`, raw p = `0.0398`
  - multiple-test corrected BH p = `0.319`

SPY 有方向性的 realized-vol 差異，但沒有通過多重檢定，也沒有支持「EPU shock 增加低轉高 regime transition」。

### TAIEX

- EPU shock days: `1,234` / `5,668` (`21.8%`)
- High-vol probability:
  - normal: `0.721`
  - EPU shock: `0.717`
  - HAC t = `-0.28`, p = `0.778`
- Low-to-high transition:
  - normal: `15.83%`
  - EPU shock: `16.37%`
  - HAC t = `0.49`, p = `0.622`
- Log-r² conditional mean:
  - HAC t = `0.43`, p = `0.665`

TAIEX 沒有穩定方向，也沒有顯著性。

## Verdict

**NULL**.

最精確的結論是：

1. SPY 在 EPU shock months 的 realized volatility 較高，但 formal evidence 不夠強。
2. SPY 的 regime transition test 反而不是正向。
3. TAIEX 不支持 US EPU 作為跨市場高波動 trigger。
4. K1519 不推翻既有 EPU/alt-data NULL 線；它把「EPU 可能不是線性 predictor，但會不會是 regime trigger」這個 loophole 先封住一層。

## Lookahead Audit

- EPU month-M signal only applies after `month_end + 2 BDay`.
- Expanding 75% threshold is shifted, so month-M threshold uses only prior months.
- No same-day EPU value is used as a same-day predictor.
- State labels are outcomes estimated from returns; they are not used as trading signals.

## Honest Limits

- 這不是完整 MS-GARCH；只是 MarkovRegression volatility-state proxy。
- Markov states are estimated on the full sample, so this is a mechanism-identification test, not tradable real-time forecasting.
- `USEPUINDXD` 是美國 EPU；TAIEX 部分是 US policy uncertainty spillover test，不是台灣本地 EPU。
- Low-to-high transition rate remains noisy at daily frequency; a monthly state aggregation or full time-varying-transition-probability model is the natural next robustness check.

## Files

- `k1519.py`
- `k1519_results.json`
- `codex_review.md`
- `figures/spy_epu_regime_trigger.png`
- `figures/taiex_epu_regime_trigger.png`

## Reproduce

```bash
uv run python experiments/k1519/k1519.py
```
