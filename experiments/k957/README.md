# K957: K526-K566 Session Synthesis — 37 Experiments, 5 Meta-Lessons

## Motivation

K526-K566 區段共 37 個 experiments（含主線 + sub-experiments），是 2026-03 下旬
VIX / leverage / HAR / portfolio construction 密集實驗期。單看每個實驗各有結論，
但累積起來形成 5 條 meta-lessons（E019-E023）— 這些是 research methodology
層面的凝結，比單一實驗結果更接近「我們學到了什麼」的答案。

Meta-synthesis 的價值：把 37 次實驗經歷的方法論教訓蒸餾成可被未來實驗直接引用的
決策規則，降低重複踩同樣的坑、浪費 token 與 compute 的風險。

## Scope

- **Source 區段**：K526-K566（37 experiments；K555 / K569 被 skip）
- **Source experience entries**：E019 / E020 / E021 / E022 / E023
- **Key breakthroughs to reference**：
  - K548/K551 VIX-Conditional Leverage (US): Harvey t=7.90, 11/11 OOS PASS
  - K553/K558 Taiwan Hybrid Leverage: Harvey t=4.79, 18/18 OOS PASS
  - K530/K532 HAR+|r_t| proxy: 7/7 universal DM-wins
  - K536 HAR-EVT: Trinity PASS (唯一同時過 Kupiec / Christoffersen / DQ 的 VaR model)
  - K535/K537/K539/K542/K554/K564: VIX sufficiency confirmations (10+ 種衍生信號全 null)
- **No new empirical estimation**: K957 is a synthesis / meta-analysis
  experiment — 引用既有 JSON 數字，不做新模型 fit

## Methodology

1. 掃 `storage/memory/experiment_experiences.json` E019-E023 entries
2. 對齊 `experiments/k5{26..66}/*_results.json` 中的 Harvey t-stat / Sharpe / OOS rate
3. 分類 37 實驗為 5 class：
   - class A (Harvey-pass, listable)
   - class B (Harvey-pass, methodology insight)
   - class C (predictive win but no trading lift)
   - class D (VIX-sufficiency null)
   - class E (daily-only artifact)
4. 產兩張 chart：(a) session timeline + verdict distribution; (b) experiments →
   meta-lesson Sankey
5. 輸出 K957 JSON：counts per class、Harvey t-stats for class A、all E019-E023
   recommendations

## Hard Rules Observed

- 無新隨機程序（pure synthesis）；seed N/A
- 無 lookahead（無回測）
- 原始資料引用來自 E019-E023 + 對應 experiment JSON，皆已 OOS/Harvey 驗證
- Worktree 限制不適用（主線程 synthesis，無 worktree agent 參與）

## Artifacts

- `k957.py`：shaping script — 讀既有 JSON / experiences 輸出 `k957_results.json`
  與兩張 PNG
- `k957_results.json`：meta-summary（counts、Harvey t-stats、 meta-lesson map）
- `k957_timeline.png`：K526-K566 timeline + verdict heatmap
- `k957_sankey.png`：experiments → E019-E023 meta-lessons flow

## Success Criteria

- 37 實驗全部分類到至少一條 meta-lesson
- 2 real matplotlib PNG 產出（非 ASCII）
- Harvey-pass 與 null 數量比例與 E019-E023 敘述一致（2 A-class PASS / 10+ D-class null）
- Downstream article draft ≥ 2000 CJK chars，differentiate mile_c15c7b98（K672 evidence hierarchy）

## Related

- E019 / E020 / E021 / E022 / E023 (experiment_experiences.json)
- K672 cumulative evidence (mile_c15c7b98)
- research_program.md methodology 硬規則
