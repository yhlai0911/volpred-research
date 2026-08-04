# K1735 第二家族獨立覆驗（2026-08-04）

REVIEWER: claude/feature-dev:code-reviewer (second-family independent re-check; fresh context, read-only)
VERDICT: PASS
BLOCKING_DEFECTS: none (confidence >=80)

覆核深度：pipeline 端到端 trace（panel 建構→bar-RV→ANOVA 分解+bias correction→T1/T2/T4 null→BH-FDR→verdict 邏輯→README render）；
gate_history 兩個凍結 blob 與最終版 diff 驗證預註冊完整性（criteria byte-identical，僅 CALIB_REPS 20→100 / CALIB_PERM 300→400 的
power 提升，門檻未動）；FDR family 30 成員 19/19 手動重數與 JSON 全符；分解 bracket 數字逐位元對齊；日夜盤 minute-indexing
邊界算術驗證（840/300 bars 精確）；headline 全欄位 README↔JSON 對齊。

RESIDUAL_RISKS（均低信心/非缺陷，供 8/8 Codex primary 補驗參考）：
1. README §3.3 提及 `n_stale_sub` 欄位，實作與 results 皆無此名（fill 行為正確、資訊由 observed_bar_fraction 承載）——
   文件命名漂移（~30 信心）。注意：README 已被 verdict pin sha，修字須連動重凍重審，留給 primary 輪裁決。
2. CONFIRMATORY_CELLS 含 primary cell 自身；排除 primary 重算仍有 2 cells 重現，verdict 不受影響。
3. agy fallback 審查過程有 mid-session self-update/salvage 事件（流程脆弱性訊號，非實驗問題）——本次跨家族覆驗即為此而設。
4. 原始 TAIFEX tick 檔在 repo 外，spec 只 pin 到 cached parquet（本庫外部資料慣例）。

原始 agent 結果全文：session 553594d7 task a1a68721299cc0cf5（166k tokens / 27 tool uses / 9.4 min）。
