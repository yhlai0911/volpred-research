# K1415 — VIX9D/VIX 短端期限結構作為 HAR-RV 基線之邊際 RV 預測因子

- Experiment ID: `k1415`
- Status: Codex review = CONDITIONAL_PASS（2026-06-04, codex-cli 0.135.0）
- Created: 2026-06-04
- Seed: 42

## 問題

在 SPY 1-day-ahead realized variance 的預測中，於 HAR-RV(daily/weekly/monthly) baseline
加入 `log(VIX9D/VIX)` 短端 implied-vol 期限結構比率，是否帶來統計上顯著、樣本外可重複
的邊際增量？

## 動機 / Hypothesis

- **H1**: VIX9D 反映未來 9 日 expected vol，VIX 反映 30 日。比率 `log(VIX9D/VIX)` 攜帶
  *短端* expected vol 與 *長端* expected vol 之 wedge 資訊；當 wedge 為正（contango 短端
  > 長端）通常代表 imminent vol 衝擊預期，與 HAR-RV 捕捉的 realized persistence 互補。
- **H0**: 增益微小或不顯著（QLIKE 改善 <0.5%、DM 不顯著）。

## 方法

- Data: SPY adj close + ^VIX + ^VIX9D from yfinance；2014-01-02 → 2026-05-29 inner join；
  n=3,097 obs（feature panel）。
- RV proxy: `RV_t = r_t² × 252`，r_t = log(close_t/close_{t-1})。**限制**：真 5-min RV
  不可得；本實驗為 first-cut feasibility test。
- HAR features at t（皆 shift(1)）: `log(RV_{t-1})`, `log(mean RV_{t-5..t-1})`,
  `log(mean RV_{t-22..t-1})`。
- Term-structure feature at t: `TR_{t-1} = log(VIX9D_{t-1} / VIX_{t-1})`。
- Models:
  - M0: `log(RV_t) = α + β1·logRV_lag1 + β2·logRV_w + β3·logRV_m + ε`
  - M1: M0 + `β4·TR_{t-1}`
- Estimation: OLS, HAC SE (Newey-West, lag=22)；OOS expanding window，年末 refit 預測
  下一年；IS-start 2014，OOS-start 2020-01-02。
- Back-transform from log to level: lognormal smearing correction
  `RV_pred = exp(logRV_pred + σ²_resid/2)`。
- Loss: QLIKE `L = true/pred − log(true/pred) − 1`。
- Test: Diebold-Mariano on QLIKE diff with HAC Newey-West (lag=22)。

## Lookahead 防護

- Target `RV_t` 用 `return(close_{t-1} → close_t)`
- 所有 features 用 `.shift(1)` 或 `.shift(1).rolling(k).mean()` 建構 → 嚴格只用 ≤ t-1 資訊
- Annual refit：train slice `index < year-01-01`，predict slice 同年 → 無 leakage
- `lookahead_check` 已記入 results.json

## 結果（一行摘要）

| Model | R² (full) | OOS QLIKE | Δ% vs M0 |
|-------|-----------|-----------|----------|
| M0 (HAR-RV) | 0.111 | 2.1555 | — |
| M1 (HAR-RV + TR) | 0.131 | 2.0141 | **+6.56%** |

- DM stat = **−7.70**, p = **1.4e-14**（M1 顯著優於 M0；OOS evidence）
- β_TR = **+4.043**, HAC t=**8.56**, p<1e-17（full-sample OLS；符號與 H1 一致）
- 子樣本 post-2021 (n=1357): Δ% **+5.64%**, DM stat=−6.57, p<1e-10（穩健）
- HAC lag=10 sensitivity: DM p<1e-13（穩健）
- **Verdict: CONDITIONAL_PASS**（Codex 審：代碼 lookahead / QLIKE / DM 全乾淨；conditional 因 single asset + RV proxy 限制與 ratio 選擇未做 multiple-testing 校正）

**重要**：β_TR 與 t 值來自 **full-sample OLS**（推論用）；DM stat 與 QLIKE 改善百分比來自 **OOS expanding-window**（預測力證據）。兩者是 **不同估計**，不可混讀為同一證據。

### 為何選 9D / 30D 比率
VIX9D 是 CBOE 唯一公開可得的短端 (≤2 週) implied vol 指標；VIX (30D) 是參考標準。比率設計參考 Johnson (2017, *JFQA*) VIX term structure slope literature。**未做** multiple testing 校正（沒掃 VIX/VIX3M, VIX/VIX6M, VIX9D/VIX3M 等多 ratio），這是 limitation。下一輪可以 grid 全 ratio + 套 BH FDR 控制。

## 解釋

`log(VIX9D/VIX)` 在 SPY 日 RV 預測上對 HAR-RV 帶來顯著且 OOS 可重複的邊際改善。係數正
號符合 H1：當短端 implied vol 相對長端走高（短期市場預期更高的 imminent vol），下一日
realized variance 也較高。改善幅度 6.6% QLIKE 在 daily vol 文獻屬大但非異常 —— 與
Johnson (2017, *JFQA*) 「VIX term-structure slope predicts equity returns and variance」
的方向一致；該文獻指出短端 implied vol 比率攜帶 jump risk premium 與 imminent uncertainty
information，HAR-RV 純粹從 past realized 無法 capture。

## Limitations

- RV proxy = daily r²×252，非 5-min RV（無 intraday data；HAR 原始文獻用 5-min RV，本實驗
  proxy 較 noisy，可能高估 baseline QLIKE 進而放大邊際改善百分比）。
- 單一資產（SPY）；跨指數（QQQ, IWM, ES 期貨）泛化未測。
- 樣本 12 年（2014-2026）；VIX9D 在 2014 前不可得。
- 年末 refit cadence 而非 daily；adaptive gain 可能被低估。
- 結果幅度大 → **必須 Codex review**（task brief 已規定）排除 implementation bug。

## Monetization angle

可成為 VolPred 平台一個 daily 公開 signal（「短端 IV 期限結構 → 明日波動預期」），於
member 牆 / strategy listing 露出，搭配 VIX 期限結構交易策略（K1408 變奏）。

## 後續方向

1. 跨資產複製：QQQ / IWM / ES / 國際 ETF
2. 換 5-min RV proxy（若取得 intraday）
3. 加入 VIX/VIX3M, VIX/VIX6M wedge 對比短端 vs 中端期限結構
4. 結合 GARCH/EGARCH 殘差檢查是否仍 captured

## 檔案

- `k1415.py` — full reproducible script
- `k1415_results.json` — structured results
- `k1415_qlike_plot.png` — rolling 60-day mean QLIKE M0 vs M1
- `README.md` — this file

## Reproduce

```bash
uv run python experiments/k1415/k1415.py
```
