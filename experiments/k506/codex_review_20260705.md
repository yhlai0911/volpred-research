# K506 Codex Review — 2026-07-05

**Reviewer**: Codex CLI (gpt-5.4, ChatGPT auth) — primary path
**Verdict**: **FAIL**（核心 null 大致成立，但精確 3/5 MARGINAL 數字未達發表級，不可引用於文章/knowledge）
**Context**: resurrect 任務 `experiment_k506_resurrect_c4` — data blocker 解除（yfinance 補抓 EWT 2010-2021）後首次重跑成功。

## 重跑結果（fresh EWT data）

- Data range: 2010-02-03 → 2021-12-30, 2922 days（EWT=yfinance, TW50/VIX=sqlite cache）
- Cross-OOS: VT+VS wins 3/5（pass threshold ≥4/5）→ MARGINAL
- Pooled: VT-only Sharpe 0.0486, VT+VS 0.2077；Harvey t_vs=0.647 << 3.0
- Pooled DM t=0.4568, p=0.6479；Bonferroni p=1.0；BH p=0.7313 — **全不顯著**
- Multiple testing family=6（5 段 + pooled），Bonferroni + BH 皆報告 ✓

## Codex Findings

1. **Rebalance timing/channel mismatch**（k506_...py:328-329）：註解寫「t open 調倉」但把新權重套到 `tw50_ret`（close-to-close, :223）。對台股用美股/VIX 訊號會把「前一日台股收盤→今日開盤」gap 也套用到今日開盤才決定的新權重。正解：rebalance day 舊權重吃 overnight、新權重吃 open-to-close，或明確標為 non-tradable c2c channel。

2. **Calendar as-of 非 timestamp-aware**（:201-210 union+ffill → 台股日 row-based shift(1) :230-231）：台股假日但美股有交易時，下一個台股開盤前已知較新 VIX/EWT close，code 仍用上一個台股交易日舊值。~86/2943 台股交易日受影響（含春節長假）。**方向是「用較舊資訊」= 對 lookahead 安全，但屬 false-null 風險**（較新訊號可能幫 VT+VS）。

3. **成本口徑**（:73-74 標 round-trip 18.55bp；:321-323 對每次 abs(Δw) 扣完整 18.55bp）：若 18.55bp 是買+賣總成本，對高 turnover 的 VT+VS 過度懲罰。註：baseline VT 與 VT+VS 用同一 `bt()`、同成本，extra turnover 被罰是公平比較的一部分；爭點在常數 label 語意 vs 實際套用倍率。

4. **DM 方向正確**（d = vs_ret − vt_ret，正 t = VT+VS 較高）。但無明確 HLN 小樣本校正（h=1 影響小，不能稱正式 HLN）。Bonferroni/BH 正確。pooled 是**單一台股策略日序列串接**，非本專案禁止的 cross-asset asset-day iid pooling ✓。

5. **README/artifact provenance 不一致**：舊 README 仍稱 results.json 為舊版失效輸出，但 results.json 已有 2026-07-05 rerun 數字（EWT=yfinance）→ 已於本輪同步更新 README。

## Codex 4-variant sanity rerun（robustness of null）

| cost | retmode | wins | pooled_dm_p | pooled_t |
|---|---|---|---|---|
| code | c2c | 3/5 | 0.6479 | 0.457 |
| side | c2c | 3/5 | 0.6304 | 0.481 |
| code | o2c_rebal | 3/5 | 0.2548 | -1.139 |
| side | o2c_rebal | 4/5 | 0.2819 | -1.076 |

**結論**：pooled DM 在所有 4 個 timing/cost 變體皆不顯著（p=0.25–0.65）→ 「overlay 無顯著 mean-return 改善」的 **null 結論 robust**；但精確 win-count（3/5 primary，o2c+side-cost 下 4/5）spec-sensitive，不可作為發表級精確數字。

## Disposition

- **不寫 knowledge.json**（守 Codex FAIL / CONDITIONAL_PASS↑ bar）。
- resurrect 任務目標（解 data blocker + 重跑 + Codex review）達成。
- 方法論硬化（Finding 1-3）另開 follow-up 實驗任務，改完 re-review 通過才寫 knowledge。
