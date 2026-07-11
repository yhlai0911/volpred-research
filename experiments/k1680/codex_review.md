# K1680 Codex review

## Verdict

**PASS_RETROSPECTIVE_NULL**

## Pre-run findings and fixes

正式執行前完成 code review，並修正下列 blocking issues：

1. Google Trends 單一當前 vintage 不得冒充歷史時點可得資料；全文與 results/status 已降級為 `retrospective pseudo-OOS diagnostic`。
2. RCFS demo 的 `GSearch` 每 firm-week 重新定基，不能直接跨週做 lead-lag；錯誤 dynamic arm 已刪除，只保留同週 static FE sanity。
3. Attention week 只在確認 Sunday week-start、連續 7 日 cadence 後才 `+5d` 對齊 Friday，再明確 `signal.shift(1)`；target week 與 attention source week無交易日重疊。
4. Pooled Clark-West 只用六檔共同日期，逐週 assert firm count=6，且至少 52 週。
5. Corwin–Schultz 的合法 0 spread 改用 `log1p`，不再 EPS-log；描述性 DM 使用 squared error，不誤用 QLIKE。
6. CW/HAC、MSE、p-value 與 Holm 全部做 finite/degeneracy gate；失敗時原子寫出 `NULL_DATA_LIMITATION`，不讓 NaN 阻斷 results。

## Post-run result audit

- Google Trends cache：12/12 payload，hash 全部與 manifest 一致。
- Cache-only 重跑：verdict、四 target pooled results、multiple testing 與 RCFS sanity 完全一致。
- RV：model-scale MSE +0.7978%，但 QLIKE -0.3955%；CW t=1.8801、Holm p=0.1202，FAIL。
- Gap：MSE -0.9221%；CW t=-1.3178、Holm p=0.9062，FAIL。
- CS spread：MSE -0.1380%；CW t=0.8497、Holm p=0.3955，FAIL。
- National attention：MSE +0.5333%；CW t=1.6685、Holm p=0.1428，FAIL。
- DM 符號與 loss 方向一致；0/4 target 通過 retrospective gate。

研究結論僅支持 `RETROSPECTIVE_NULL`。不允許改寫為 genuine OOS、因果 local-information advantage，或「所有 geographic attention 都無效」。
