# k_ai_infra_financing_spillover_2026_06_14

## Research Question

AI 基建熱潮若真的透過電力、基建與信用融資鏈條傳導，公開市場上是否會先看到
`XLU/PAVE` 與 `HYG/LQD` 的波動率異動，再延伸到 Nasdaq (`QQQ`) 的次日波動率？

這是一個 **public-market proxy pilot**。它不直接觀測資料中心專案融資、private
credit 貸款台帳、或電網專案現金流，只測試這個敘事是否在可重跑的日頻 ETF /
股票資料中留下可驗證的 lead-lag 痕跡。

## Motivation

`research_program.md` 在 2026-06-14 journal-topic-discovery backlog 新增了
「AI 基建資金鏈的波動傳導」方向。相較於 repo 內已存在的 AI 題材：

- `k1410_ai_capex_iv_divergence` 著重於 **CapEx vs vol 定價落差**
- 本實驗改問 **vol transmission ordering**

因此這個 pilot 的差異化在於：

1. 不討論 AI 題材是否火，而是測「資金鏈壓力」是否可在電力/信用籃子先被看見。
2. 用 `HAR-X` 的 OOS QLIKE + DM，而不只看事件圖。
3. 明確接受 **null result**：如果只是同日共振、沒有可靠領先性，就如實報告。

## Literature Preamble

1. Jessica Wachter and Jonathan Wachter (2026), NBER Working Paper 35290,
   *What Investment Data Implies about the AI Transition*:
   大型科技公司 CapEx 快速上升，AI transition 已成真實的資本開支現象。
2. J.P. Morgan Asset Management (2026), *Alternative Investments Outlook 2026*:
   AI build-out 已把資料中心、電網與 private credit 融資綁在同一個資本循環中。
3. IMF GFSR (2025, Chapter 1 / 2024 Chapter 2 background):
   private credit 與銀行/其他金融機構的連結可能放大信用衝擊，代表信用腿值得單獨追蹤。
4. *Powering AI: How Do Data Centers Affect Renewable Energy Markets and Emissions?*
   (2026 working paper / SSRN-RePEc listing):
   AI 資料中心需求與電力投資、尤其 renewable / storage 供給擴張有明顯連動。

這些來源支持「AI → 電力/基建/信用」的機制動機，但 **不保證** 日頻公開市場資料
一定會呈現可交易的領先關係；那正是本實驗要驗證的地方。

## Data

- Source: `yfinance` adjusted close
- Sample: `2015-01-02` to `2026-06-12`
- AI basket: `MSFT`, `NVDA`, `SMH`
- Infrastructure / power basket: `XLU`, `PAVE`
- Credit basket: `HYG`, `LQD`
- Nasdaq target: `QQQ`
- Frequency: daily
- RV proxy: close-to-close squared log return

## Hypotheses

### H1: descriptive aftershock pattern

如果 AI build-out shock 會沿著基建/信用鏈條傳導，那麼在 **AI 正向 shock 日** 後，
`infra_rv` / `credit_rv` 的 `t+1`、`t+2` 反應，至少相對常態應該不弱於 `QQQ`。

### H2: predictive value for Nasdaq volatility

若電力/信用腿真有「先出現、再傳到 Nasdaq」的資訊，那把
`infra_rv_{t-1}` / `credit_rv_{t-1}` 加入 `QQQ` 的 HAR-RV baseline，
應該在 OOS QLIKE 上優於純 HAR。

## Design

### Shock definition

AI 正向 shock 定義為：

`ai_ret_t > lagged_252d_95pct(ai_ret)`

其中 percentile 以 `shift(1)` lagged 門檻計算，避免同日 threshold lookahead。
注意：**shock 標籤本身仍使用 same-day AI return**，所以 `t` 的事件圖是描述性分析，
不是交易訊號。

### Predictive model

Baseline HAR:

`log(RV^QQQ_{t+1}) ~ 1 + log(RV_t) + log(RV_{5,t}) + log(RV_{22,t})`

Augmented HAR-X:

`+ log(infra_rv_t) + log(credit_rv_t) + ai_shock_t`

評估方式：

- In-sample HAC (`maxlags=5`) 檢查方向
- Rolling OOS QLIKE
- Diebold-Mariano test vs baseline HAR

## Main Result

Verdict: **NULL_FOR_LEAD_LAG_TRANSMISSION**

### What does hold

- AI 正向 shock 當天，三條腿都明顯放大：
  - infra same-day RV ratio ≈ `4.91x`
  - credit same-day RV ratio ≈ `3.24x`
  - QQQ same-day RV ratio ≈ `6.33x`
- `t+1` 相對常態的 RV 倍數，infra / credit 確實高於 QQQ：
  - infra `3.23x`
  - credit `3.42x`
  - QQQ `2.21x`

### What does not hold

- 一旦放進 proper HAR controls，`infra_rv_{t-1}`、`credit_rv_{t-1}`、
  `ai_shock_t` 的增量解釋力非常小：
  - `ΔR² ≈ +0.002`
  - HAC p-values 都未達 5%
- OOS QLIKE 最佳模型仍是 **baseline HAR**
- HAR+AI / HAR+infra / HAR+credit / HAR+all 對 baseline 的 DM 全數不顯著

## Interpretation

最誠實的解讀是：

1. AI 題材 shock 會帶來 **同日共振**，這沒有問題。
2. 電力/基建與信用腿在 `t+1` 的 aftershock ratio 比 `QQQ` 更高，說明它們不是完全沒反應。
3. 但這種 aftershock **沒有穩定到足以轉化成 OOS 預測優勢**。

所以本次 evidence 支持的是：

- `co-volatility under AI shock`

而不是：

- `infrastructure/credit lead Nasdaq vol in a tradable way`

## Files

- `k_ai_infra_financing_spillover_2026_06_14.py`
- `k_ai_infra_financing_spillover_2026_06_14_results.json`
- `fig_event_window_ratios.png`
- `fig_oos_qlike.png`

## Reproduce

```bash
uv run python experiments/k_ai_infra_financing_spillover_2026_06_14/k_ai_infra_financing_spillover_2026_06_14.py
```
