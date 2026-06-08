# Codex 24h Re-Review — K1427 / `mile_c07025d2`

- **Verdict**: `CONDITIONAL_PASS`

## Caveat Check

1. **Q1 顯著性**: `addressed`
   - 文章已移除精準 p 值，改成定性敘述，並補上 `69 個 clustered episodes` 的時序相依註腳。證據：`storage/reports/mile_c07025d2.json:5`

2. **Q5 forward-RV**: `addressed`
   - 文章未再引用 Q5 的 forward-RV 數字。證據：`storage/reports/mile_c07025d2.json:5`
   - 補充：README 仍保留 exploratory Q5 數字，但原 caveat 是 article-scope。`experiments/k1427/README.md:43`

3. **JSON definitions**: `partially`
   - `k1427.py` 已補上 `taxonomy_dimensions` 與 `broad_selloff_high_disp_regime`，2-D taxonomy 在程式端已修正。證據：`experiments/k1427/k1427.py:353`
   - 但 `k1427_results.json` 仍是舊版 1-D definitions，未同步 rerun。證據：`experiments/k1427/k1427_results.json:67`

4. **0050 robustness 限定語**: `addressed`
   - 文章末段已明寫結論只覆蓋美股 sector ETF，不可延伸到台股/0050。證據：`storage/reports/mile_c07025d2.json:5`

## New Issues

1. **Code / artifact 脫鉤，caveat 3 未真正 closure**  
   `experiments/k1427/k1427.py:353` 已輸出 2-D definitions，但 `experiments/k1427/k1427_results.json:67` 仍保留舊版 `rotation_regime` / `liquidation_regime`，缺 `taxonomy_dimensions` 與 `broad_selloff_high_disp_regime`。這會讓下游讀 results JSON 的 consumer 仍拿到舊定義。

2. **README 對 results.json 的聲明與實際產物不一致**  
   `experiments/k1427/README.md:84` 寫「所有數字寫入 `k1427_results.json`」，但目前 results JSON 未反映程式內最新 definitions；屬於 claim-evidence mismatch。

## Scan Summary

- **Lookahead**: 未發現新引入 lookahead。
- **Overclaim**: 文章層未見新增 overclaim；`MIXED`、美股範圍限制、防禦≠能源都寫得夠誠實。
- **Methodology bug**: 未見新的主路徑 bug；Q5 對齊 caveat 仍是既有非核心問題，且文章未拿它做強主張。

## Recommendation

- 不建議直接升 `PASS`。
- 先 rerun `experiments/k1427/k1427.py`，把 `k1427_results.json` 同步到 2-D definitions 後即可 closure。
