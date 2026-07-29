# Claim Verification

## Claim inventory

從 agent summary、README、result verdict 與圖表 caption 建立完整 claim list，至少涵蓋：

- levels、differences、ratios、percent changes
- signs、rankings、winner/loser
- p-values、test statistics、confidence intervals
- PASS/NULL/FAIL、significant/insignificant
- only/unique/all/none 類 population claims
- sample counts、periods、assets、seeds與 convergence

每個 claim 必須對應 canonical result JSON path 或可重跑計算。

## Programmatic reconstruction

- Parse `reproduce_spec.json` 找 canonical result；不猜檔名。
- 讀 raw precision，不以 README 的 rounded value 反算。
- Improvement 重新用明示 numerator/denominator 計算。
- Test sign 先確認 loss differential 的 A/B 定義。
- Population claim 掃完整 population，列出 denominator 與排除規則。
- 圖表 claim 同時核對繪圖 input，不只看圖片。

## Method consistency

- Candidate 與 baseline 的日期、lag、成本、sample filter 相同。
- DM/QLIKE/VaR/ES 使用 repository canonical implementation。
- HAC、multiple testing、OOS 與 convergence 符合 experiment rules。
- Sharpe、MDD 或顯著性異常時，先查 exposure、alignment、selection 與 leakage。

## Disagreement handling

| 情況 | 處置 |
|---|---|
| Summary 數字錯，artifact/verdict 正確 | 修正 summary，保存 discrepancy。 |
| README 與 result 不同 | Claim surface 不一致，重新 review。 |
| Result 與 code trace/spec 不同 | Blocked；找 runtime evidence，不補 checksum。 |
| Test sign/denominator 不可重建 | Blocked；不能沿用 agent interpretation。 |
| Bug 會改 result | 先 preserve pinned bytes，再修 code、重跑、重建 spec、重審。 |

## Verification report

輸出表：

| Claim | Agent value | Rebuilt value | Source path | Verdict |
|---|---:|---:|---|---|

列出掃描 population、blind spots、reconstruction command 與剩餘限制。
