# K189 / mile_c26fcd8e — Codex 24h-rule Review Verdict

**Date**: 2026-06-11 11:15 台灣時間
**Reviewer**: codex-cli (gpt-5.4 medium reasoning)
**Article**: mile_c26fcd8e「把六個市場一起看，真的比只看自己更懂波動嗎？」
**Verdict**: **FAIL**

## HIGH severity (4)

1. **Contemporaneous leakage (forecast)**: EWMA + attention forecast 用同日 `ret_t^2`/`EWMA_t` 比同日 `rv_t`，非乾淨 t-1→t 預測。(`k189_attention_vol.py:105-112, 227-255, 321-349`)
2. **Contemporaneous leakage (attention weights)**: attention weights 在 t 估計時包含 target rv[t]，再用同 t 權重生成並評估 forecast[t]。(`k189_attention_vol.py:180-200, 382-439`)
3. **Post-selection inference**: 先用整段 OOS 挑每個資產 best_alpha，再用同段 OOS 做 DM test → p 值樂觀化。(`k189_attention_vol.py:364-439, 620-633`)
4. **Spec mismatch**: 文章說 training window=500，但 attention/EWMA 沒套（只 GJR 用）；attention 用整段歷史上的 252 日 rolling correlation。

## MEDIUM (4)

- 無 Bonferroni / FDR multiple testing correction（6 個資產 + GJR/EWMA 對比）
- 「最佳設定靠近 0.9」只能說「grid {0.3,0.5,0.7,0.9} 中六個資產都選 0.9」
- 「相關不等於增量」超出實證範圍（只證明此 attention spec 在此資料未贏）
- OOS 502 日 + 22 日 rolling RV → 嚴重重疊，有效獨立樣本 << 502

## 修正建議（5）

1. forecast + attention weights 全改嚴格 lagged（`shift(1)` 等效）
2. alpha 選擇移到 training window 內 OR rolling re-selection + validation slice
3. DM test 重跑 + Bonferroni/FDR 校正
4. 文章三句核心改口徑：(a) 刪「historical window 只用 t-1 前資訊」(b) 「最佳 0.9」→「grid 中 0.9 最常勝」(c) 「相關不等於增量」→「本 attention 規格未顯示穩健增量」
5. 補 `experiments/k189/README.md`（目前仍 planning 模板）

## Action items

- [ ] Article mile_c26fcd8e errata：撤誇大宣稱 + 加 lookahead 揭露
- [ ] K189 重跑：lagged forecast + ex ante alpha selection
- [ ] knowledge.json 新增 K189 FAIL entry（reviewer=codex-cli 2026-06-11）
