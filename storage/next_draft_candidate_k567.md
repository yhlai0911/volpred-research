> 🔒 CONSUMED 2026-05-21T13:07Z — published as mile_357f5f44 "VIX 是全球恐慌指數？六個市場真錢實測的答案讓人意外" (status=draft, audience=research)

# Next Draft Candidate: K567 VIX-Conditional Leverage 在跨國市場不通用

**Prepared 2026-04-27 by main thread** as second preemptive brief in the 2026-04-26/27 cron heartbeat refill cycle (after K908 brief consumed → mile_3eb8657c). 補 K-research general-audience pool。

## K567 Overview

**Score**: 6（★ from `publication_candidates.json` `missing_general` 第 4 位; 已 covered for research, missing general）
**Title**: K567: International VT Leverage — VIX-Conditional Leverage has LIMITED Generalizability
**Coverage**: research-only; general-audience uncovered
**Verdict**: **NULL result** — 6 個市場 0/6 通過 Harvey

## Why this topic works

- **誠實 framing 案例**：研究誠實原則明文「Null result 如實報告」+「結論強度不超過證據」。讀者願意相信你的正向結果，前提是你也敢報 null
- **方法論教訓**：US 市場上有效的 VIX-conditional strategy（K398 等正向結論），blind extrapolate 到 international markets 多數無效 → 「不要把 SPY 結論套到 EWJ / EWZ」
- **跨國資產 angle**：6 個市場（SPY 美 / EFA 已開發 ex-US / EWZ 巴西 / EWJ 日 / EWU 英 / FXI 中）讓讀者看到 VIX 信號的「美股局部性」
- **不涉及 Paper 敘事**：K567 是 strategy generalizability 探討，獨立於 Paper 1-9
- **Counter-intuitive payoff**：讀者預期「VIX 是全球波動指標應該全球通用」，結果反而限縮在美國 — 有 hook
- **Mission L8「研究誠實」+「把文章寫好」**：null result + 跨市場視覺化 + 方法論 take-away 三要素齊全
- **圖表 ready**：`experiments/k567/` 已有 `k567_general_sharpe_bars.png` + `k567_general_tstat_scatter.png` — agent 不必重新跑 matplotlib（節省 dispatch 時間）

## 具體數字（必引，全部 byte-match `experiments/k567/k567_international_vt_leverage_results.json`）

### 6 市場 Harvey 結果（best variant 對比 base）

| 市場 | Base Sharpe | Best variant | Best Sharpe | Δ Sharpe | t-stat | Harvey | oos_wins/3 |
|---|---|---|---|---|---|---|---|
| SPY (US) | 0.366 | local_rv | 0.402 | +0.036 | **2.47** | FAIL | 0/3 |
| EFA (Dev ex-US) | 0.187 | none | 0.187 | +0.0005 | 0.00 | FAIL | 0/3 |
| EWZ (Brazil) | 0.139 | none | 0.139 | -0.008 | 0.00 | FAIL | 0/3 |
| EWJ (Japan) | 0.226 | local_rv | 0.254 | +0.028 | 1.81 | FAIL | 0/3 |
| EWU (UK) | 0.125 | none | 0.125 | -0.005 | 0.00 | FAIL | 0/3 |
| FXI (China) | 0.192 | us_style | 0.203 | +0.011 | 0.87 | FAIL | 0/3 |

### 3 個 punch points
1. **0/6 Harvey PASS** — 即便最寬鬆的 |t|>3 標準也通不過任何市場
2. **3/6 best variant = "none"**（EFA / EWZ / EWU）— VIX-conditional 完全沒幫助甚至倒退（Δ Sharpe 0 或負）
3. **SPY 最接近但仍 NS**：t=2.47 是 6 市場最高，仍離 Harvey threshold 0.53 個 σ；international markets 距離更遠

### 跨 OOS 全敗
6 個市場 × 3 OOS windows = 18 個 cell，**oos_wins 全部 0**。意味即便 in-sample 看似有改善，cross-OOS validation 完全消失。

## ⚠️ 4 維度文章標準（dispatch agent 必符合，2026-04-27 用戶 feedback）

每篇文章必須同時滿足：

1. **深度**：解釋 mechanism（為什麼 VIX 是美股局部現象）+ 1 個 counter-intuitive insight + cross-K ≥3
2. **可讀性**：Title punchy（避免「K567: International VT...」academic 命名 → 改類似「VIX 是全球波動指標？6 個市場實測說 No」）；Intro 用 hook（讀者預設挑戰）；段落 ≤5 句；Trinity / Harvey / VT 等專有名詞首次定義；結尾 take-away 一句話
3. **資訊性**：≥2 真實 PNG（已 ready）+ 具體 magnitude（不只「不顯著」要寫 t=2.47/0.00 等）+ 數據來源 + Harvey 檢定 + 樣本期間
4. **參考性**：≥3 cross-link（K398 / K549 / K1018 等）+ 延伸閱讀段 + reproduce method（k567_international_vt_leverage.py + results.json path）

**Anti-pattern（不可犯）**：results.json 數字直譯 + 兩張圖貼上去就交差（缺 mechanism = 深度 0）。讀者要的是「why generalizability fails」的解釋，不是「結果是 0/6 PASS」事實 dump。

## Article Skeleton（general audience 1500-2000 chars）

1. **Intro**: 一個直觀假設 — VIX 是全球波動指標，VIX-conditional 策略應全球通用？K567 結果說 NO
2. **VIX-conditional 是什麼**: VT（volatility targeting）+ VIX 高時降槓桿 / 低時加槓桿。reader 一句話理解
3. **3 個 variant 設計**: us_style / percentile / local_rv — 各代表 VIX 對策略的不同編碼方式
4. **6 市場 × 3 variants 結果表**（chart 1 sharpe bars 引用）
5. **Why international fails**: VIX 反應美股投資人情緒；EFA/EWZ/EWU/EWJ/FXI 的 local risk 不一定跟 SPY 同步
6. **t-stat scatter 視角**（chart 2 t-stat scatter 引用）— 即便 SPY 最高 t=2.47 仍 NS，其他市場逼近 0
7. **Methodology take-away**: US 結論 ≠ international 結論；「VT + VIX」要在 US 內限縮使用，不要 blind extrapolate
8. **結論**: K567 是研究誠實的範例 — null result 也是結果，告訴你策略 boundary 在哪

## Charts needed（**已有 2 張 ready**，agent 直接上傳即可）

1. `experiments/k567/k567_general_sharpe_bars.png` — Base Sharpe vs Best Variant Sharpe，6 市場橫條對照
2. `experiments/k567/k567_general_tstat_scatter.png` — 6 市場 t-stat 散點圖，highlight Harvey threshold 線

**Agent 工作**：直接 read 這兩個 PNG → 上傳 Supabase Storage（hash naming，避免覆蓋）→ 在 article markdown 內 `![]()` 引用 → HTTP 200 驗證。**不必重 matplotlib**（除非檔案 corrupt）。

## Data sources

- `experiments/k567/k567_international_vt_leverage_results.json` — 主結果（含 summary / oos_results / cross_market_meta / methodology）
- `experiments/k567/k567_international_vt_leverage.py` — script 對照
- 6 ETF: SPY / EFA / EWZ / EWJ / EWU / FXI（yfinance）
- VIX (^VIX) 作 leverage signal
- 期間 / sample size：在 `oos_results` 內查 `n_obs` / `period` 欄位

## Cross-link refs

- K398 系列: VIX-conditional VT 在 US 的早期正向實驗（contrast）
- K549 / K774 / K1018: Multi-asset VT 相關
- K1041 / K1092: DCC-A4f portfolio VaR

## Tags（必填，下次 agent dispatch 時 enforce）

`K567`, `國際市場`, `VIX`, `VT`, `volatility-targeting`, `Harvey`, `null-result`, `跨市場`, `方法論`, `一般讀者`

⚠️ **教訓 from K908 dispatch**：上次 agent tag 缺 `K908` + `ES`（不顯著違規但偏離 brief）。本 brief tags 含 `K567` 是必填項，agent prompt 要 enforce。

## Dispatch when

- Pool drops below 4 OR 主線程主動補 general-audience pool
- 用 Claude general-purpose agent + feed-publisher skill
- agent prompt 明示：
  - read 本 brief
  - byte-match results.json 數字
  - 直接 reuse `k567_general_*.png` 兩張圖（不重跑 matplotlib）
  - tags 必含 `K567`（K908 dispatch 教訓）
  - status=draft, audience=general, 1500-2000 CJK chars

## Status

**Ready** — 主線程已驗證 results.json 6 市場數字 + 兩張 PNG 存在。等下次 dispatch trigger。

**Do NOT consume manually**；agent dispatch 後改本 memo header 為 `🔒 CONSUMED <ISO 8601 UTC> — published as mile_<id>` 留 audit trail（模仿 K908 brief 標法）。
