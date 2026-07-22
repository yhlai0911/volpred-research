# ASIA-3：台股產業波動溢出網絡（Diebold–Yilmaz spillover index）

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Worktree**: `.claude/worktrees/dispatch-slot-1-cb097ccd-asia3`（已建好，branch `wt/dispatch-slot-1-cb097ccd-asia3`）
**Task id**: `asia3_tw_sector_spillover`
**K 編號**：實驗開始前到 `storage/knowledge.json` 取下一個未使用的 K 編號，README 與檔名一致使用。

## 為什麼派這一張（脈絡，別忽略）

老闆 2026-07-22 Telegram 質疑「新主題實驗停滯」。查證屬實：近一週 experiment 完成量高
（7/19 17 筆、7/21 15 筆），但幾乎全是 K1623/K1708/K1731/K1380 的 remediation 與稽核重跑，
真正的新主題被排擠。這張是 ASIA 廣度 backlog 的第一棒 —— **要的是一個誠實的新結果，
不是又一輪修補**。NULL 結論完全可以接受並且要照實寫；不可接受的是為了「有結果」而放寬標準。

## 研究內容

面向 ASIA 第三棒（台股產業層級，老闆點名台股產業）。

- **產業代表股**（yfinance，2026-07-15 smoke test 全數可用）：
  電子 2330/2317/2454、金融 2881/2891、航運 2603/2609、塑化 1301、光學 3008（`.TW` 後綴）。
- **方法**：Diebold–Yilmaz spillover index + Granger 網絡。
  **必用 generalized FEVD（Pesaran–Shin），不得用 Cholesky-FEVD** —— Cholesky 的
  排序假象規則在本 repo 已被明列為禁區，排序不同會製造出不同的「溢出方向」。
- **對照結構**：與 T5a 的既有發現（TAIEX gamma > 0050 > TSMC）並列討論，看產業層
  spillover 是否與該層級結構一致。
- **產出角度**：面向一般讀者的「產業輪動 TA」敘事（若結果撐得起）。

## 硬規則（違反任一條 = 實驗作廢）

1. 開工先讀 `docs/error_log.md` + `.claude/rules/experiments.md` + `.claude/rules/methodology.md`；
   搜 `storage/knowledge.json` 找相似 K，若已有覆蓋就回報 duplicate 而不是硬做。
2. 至少讀 3 篇文獻（Diebold–Yilmaz 2009/2012/2014 + 台股 spillover 相關），README 引用。
3. **先做資料期間診斷**：smoke test 只驗 2y，實驗要拉**最長可得樣本**，
   OOS 必須至少涵蓋一次空頭。樣本期間與缺值處理寫進 README。
4. 跨市場假日 alignment 依 `methodology.md`（不得用 forward-fill 製造假交易日）。
5. `signal.shift(1)` 明確 lag，seed=42，禁任何 lookahead。lookahead policy 寫進 README。
6. DM 檢定用 canonical `volpred.stats.model_evaluation.dm_test`（含 HAC bandwidth 規則），
   不得自己重寫。
7. 收工跑 `uv run python scripts/experiment_gates.py run --path experiments/<kid>`，必須過。
8. **禁止寫 knowledge.json**（K1259 教訓）—— 你只產出 results + README，knowledge 由主線程寫。
9. **禁止合併 worktree**。所有產出留在 worktree 內。
10. 假數字 = 最嚴重的失敗。任何無法從資料算出來的數字都不准出現在 README 或 results。

## 交付物（皆在 worktree 內）

- `experiments/<kid>/README.md` — motivation / 文獻 / method / 資料期間診斷 / lookahead policy /
  success criteria（事前寫定，不得事後調整）/ 結果與誠實結論
- `experiments/<kid>/<KID>.py` — seed=42、signal.shift(1)
- `experiments/<kid>/<KID>_results.json` — byte-traceable，含 code_trace（sha256 + size_bytes）
- `experiments/<kid>/reproduce_spec.json`
- 至少 1 張圖（spillover 網絡或 rolling total spillover index）
- Codex review：primary path（`codex exec`）。報告存
  `storage/ops/<kid>_codex_review_<date>.md`。quota 被擋才可 fallback，且必須在報告註明。

最後回傳 JSON 摘要：`{"k_id":..., "verdict":"SUPPORTED|CONDITIONAL_PASS|NULL", "sample_period":...,
"total_spillover_index":..., "gates_pass":bool, "codex_verdict":..., "article_worthy":bool}`
