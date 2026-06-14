# Paper review (Codex 24h-rule): mile_1a6d9369 / K864

- **Article**: 分散策略救不了市場：波動率目標的集體陷阱
- **K-id**: K864 (heterogeneous ABM)
- **Reviewer**: Codex CLI 0.137.0 (ChatGPT auth, gpt-5.4 medium)
- **Review date**: 2026-06-14 18:09 台灣時間
- **VERDICT**: FAIL

## Critical issues (must-fix)

1. **無 DM / Harvey-Leybourne-Newbold correction** (`k864:481`): 只用 `welch_t_test()` 跨 simulation；若文章把 homo vs hetero 當 strategy comparison，不符專案 Harvey gate。
2. **flash_crash 用 ex-post sigma threshold** (`k864:305`): `return < -3*sigma` 的 sigma 是全樣本，非事前可得；文章主打「閃崩 6.9 倍」必須改固定門檻或 rolling t-1 sigma 後重算。
3. **Price clamp 但 rolling buffer 寫未 clamp 值** (`k864:285,290`): 100% hetero 已有 57 次 clamp，VIX/realized-vol feedback loop 不可信。
4. **Noise trader clip 不一致** (`k864:267`): clip `noise_weights` 後 `net_demand` 仍加 raw `noise_changes`，邊界記入不存在成交需求。
5. **VT demand `n_vt^2` quadratic herding** (`k864:256`): 強假設，需 linear-demand sensitivity 比對；文章不能說成一般市場機制。
6. **「A 先賣、C 開始賣、D 加入」機制敘事無 per-type flow 支持** (`feed:10847`): 程式無 per-type trade flow / lag correlation / event-time decomp，目前只能 descriptive 不能 causal。
7. **`vt_sharpe` 是 aggregate** (`k864:336`): 文章「每個人帳戶績效更好」過強，應為 aggregate portfolio。

## Minor issues
- README 仍是 planning 模板（與 published 狀態不一致）
- Header 寫 N=500/50 sims，實際 N=1000/200 sims
- annual return 用 arithmetic mean×252 非 CAGR
- bootstrap 每 metric 重設同 seed → streams 相同
- `weight_type_d()` `vix_prev` 參數未使用

## Strengths
- 交易決策無明顯 lookahead（VIX/RV/EWMA 皆 t-1）
- Seeds 固定，可重現性合格
- Results 已標 SIMULATION + limitations
- 文章數字與 results.json 對得上

## Follow-up actions
1. Issue 2/3/7 為 production blocker — 需修 code 並重跑 + revise article
2. Issue 1/4/5/6 為方法強度 — 至少需 article 加 caveat
3. 建議建 K864-v2 task 走 critical fix flight，主線程做 article revise 或 retract

