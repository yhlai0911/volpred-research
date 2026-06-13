# K880 Codex 24h Review — mile_862223de

- **Date**: 2026-06-13 10:14 台灣時間
- **Reviewer**: Codex CLI 0.137.0 (GPT-5.4 default)
- **Article**: 波動率模型 PRG 在美股 SPY 也站得住腳 — 從台股驗到美股的跨市場故事
- **Published**: 2026-06-13T01:01:31Z
- **Verdict**: NEEDS_REVISION

## Dimension scoring

| Dimension | Verdict | Notes |
|---|---|---|
| LOOKAHEAD | concern | k880_prg_spy_validation.py:511-518 — PRG forecast 使用 same-day overnight observation |
| DM_HARVEY | concern | k880_prg_spy_validation.py:888 — `dm_test()` 回傳 tuple，code 使用 `.get()` 落入 manual fallback；Harvey 僅 `abs(t)>3`，無 HLN 小樣本修正或 family adjustment |
| CROSS_MARKET_FAIRNESS | concern | PRG 用 at-open info set，GJR/HAR/Separate 用 close-only，不是 apples-to-apples |
| SESSION_TIMING | ok | session-boundary at-open 使用已 realized overnight 為 legitimate timing（Paper 6 K880 判定原則） |
| SAMPLE | ok | IS 2000-2018、OOS 2019-2026、n=1823，含 COVID + 2022 熊市 |
| MCS_SPEARMAN | concern | k880_prg_spy_validation.py:708, 778 — 簡化版 iid bootstrap，非 HLN block/stationary bootstrap，所有 model 都「survive」不支持 PRG 在 superior set 的 claim |

## Key findings

- PRG refit 是 walk-forward clean（`[:t]`，無 future refit leak），但 forecast 使用 same-day `r2_overnight[t]` / `r_overnight[t]`；對 at-open forecast valid，**非** strict t-1 day-ahead forecast。
- PRG 的 information set 比 GJR/HAR/Separate 更豐富（含 open-time overnight observation），「PRG beats GJR」不是 apples-to-apples，除非文章明說 timing asymmetry。
- DM path 標籤錯誤；Harvey 通過僅靠 `abs(t)>3`，無 HLN 小樣本修正或 pair-family adjustment（與 K547 / K208 / 多篇 paper 反覆出現的 Harvey threshold 誤用同類問題）。
- MCS 非 HLN-style block/bootstrap MCS，使用 iid resampling 且所有 model 都 survive，不支持 PRG-superior-set claim。
- README 為 placeholder despite published — reproducibility documentation incomplete。

## Recommended fixes

| File:Line | Fix |
|---|---|
| `experiments/k880/k880_prg_spy_validation.py:511` | 明確標記 forecast 為 at-open horizon；或補一個 strict t-1 day-ahead variant |
| `experiments/k880/k880_prg_spy_validation.py:888` | 修正 DM 呼叫為 tuple unpacking；補 Bonferroni/BH-adjusted p-values 跨 pairs |
| `experiments/k880/k880_prg_spy_validation.py:708` | 改用 `src/volpred/stats/mcs.py` block/stationary bootstrap 實作 |
| `experiments/k880/k880_prg_spy_validation.py:778` | 補 rolling-window Spearman stability，不只全期 iid bootstrap CI |
| `experiments/k880/README.md` | 補完整 data / sample / method / results / limitations 段落 |

## Article-level fix（mile_862223de errata）

核心結論不變（PRG 在 SPY 跨市場驗證 + session-boundary at-open legitimate per memory feedback_session_boundary_forecast_timing），但需要：

1. 明確說明 PRG 是 at-open forecast（使用已 realized overnight），info set 比 GJR (close-only) 大；對 SPY open-time hedge / VT 場景有意義，但不是 strict day-ahead horserace
2. DM-Harvey 標籤明說使用 `|t|>3` 啟發式，非正式 HLN/Bonferroni 修正後 verdict
3. MCS 段落改述為「所有 model survive」非「PRG 在 superior set」

## Provenance

- Source code reviewed: `experiments/k880/k880_prg_spy_validation.py` (1388 LOC)
- Results: `experiments/k880/k880_results.json`
- Codex tokens used: 267,957
- Raw output: `experiments/k880/reviews/codex_24h_review_mile_862223de.txt`
