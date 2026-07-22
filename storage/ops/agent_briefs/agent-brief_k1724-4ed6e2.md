# K1724：台股當沖佔比與波動 —— 散戶 herding 的在地量化

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Worktree**: `.claude/worktrees/dispatch-slot-1-cb097ccd-k1724`（已建好，branch `wt/dispatch-slot-1-cb097ccd-k1724`）
**Task id**: `K1724`

## 為什麼派這一張（脈絡）

老闆 2026-07-22 質疑新主題實驗停滯 —— 近一週 experiment 幾乎全是 remediation 重跑，
ASIA 廣度 backlog 被排擠。這是第二棒。**要的是誠實的新結果**；NULL 照實寫，
不可為了「有結果」放寬事前註冊的門檻。

## 研究內容

**題目**：TWSE 免費日頻「當沖（day-trading）成交比重」對次日 RV 的預測力，
以及當沖與波動的**雙向 Granger** 關係 —— 是 vol 吸引當沖，還是當沖放大 vol？

台灣的當沖資料完整度國際罕見（TWSE 逐日公布），這正是國際文獻（JFQA / JEF 2024–25 的
retail order-imbalance 辯論）缺資料的地方，是本題的貢獻點。

**要做的**：

1. **資料**：TWSE 免費日頻當沖比率（先查 `.claude/skills/external-data-sources` 有無現成
   抓取路徑；沒有再自己寫，但必須是官方免費端點，禁爬付費源）。標的用大盤 TAIEX +
   至少 2 檔高當沖個股。RV 用 repo canonical 的估計式（見 `methodology.md`），不要自創。
2. **預測力**：當沖比率 → 次日 RV。基準必須是 **HAR**（不是「常數」這種稻草人）；
   要回答的是「加了當沖比率的 HAR 是否勝過純 HAR」，而不是「當沖比率有沒有相關性」。
   用 canonical `volpred.stats.model_evaluation.dm_test`（HAC bandwidth 規則）。
3. **雙向 Granger**：兩個方向都檢定，並報兩個方向的 p 值。
   **Granger 因果不是因果** —— README 的措辭必須守住這條線，禁止寫成機制宣稱。
4. **多重比較**：多標的 × 多 horizon 同時檢定時套 Holm–Bonferroni，family 定義寫進 README。

## 硬規則（違反任一條 = 實驗作廢）

1. 開工先讀 `docs/error_log.md` + `.claude/rules/experiments.md` + `.claude/rules/methodology.md`；
   搜 `storage/knowledge.json` 找相似 K（尤其既有台股 / order-flow 類），已覆蓋就回報 duplicate。
2. 至少讀 3 篇文獻（JFQA/JEF 2024–25 retail order imbalance + 台股當沖相關），README 引用。
3. **資料期間診斷先於建模**：拉最長可得樣本，OOS 必須至少涵蓋一次空頭；
   當沖制度在台灣有修訂沿革（現股當沖標的與稅率調整），**制度變更點必須標出並做子樣本檢查**
   —— 這是本題最容易出假結果的地方。
4. `signal.shift(1)` 明確 lag，seed=42，禁任何 lookahead。lookahead policy 寫進 README。
5. success criteria **事前寫定**於 README，不得看到結果再調整。
6. 收工跑 `uv run python scripts/experiment_gates.py run --path experiments/k1724`，必須過。
7. **禁止寫 knowledge.json**（K1259 教訓）。knowledge 由主線程寫。
8. **禁止合併 worktree**。
9. 假數字 = 最嚴重的失敗。

## 交付物（皆在 worktree 內）

- `experiments/k1724/README.md` — motivation / 文獻 / 資料與制度沿革診斷 / method /
  lookahead policy / 事前 success criteria / 結果與誠實結論
- `experiments/k1724/K1724.py` — seed=42、signal.shift(1)
- `experiments/k1724/K1724_results.json` — byte-traceable，含 code_trace（sha256 + size_bytes）
- `experiments/k1724/reproduce_spec.json`
- 至少 1 張圖（當沖比率 vs RV 時序，或 rolling 預測力）
- Codex review：primary path（`codex exec`），報告存
  `storage/ops/k1724_codex_review_<date>.md`。quota 被擋才可 fallback 並註明。

最後回傳 JSON 摘要：`{"verdict":"SUPPORTED|CONDITIONAL_PASS|NULL", "sample_period":...,
"dm_vs_har":{"stat":...,"p":...}, "granger_both_directions":{...}, "regime_subsamples":...,
"gates_pass":bool, "codex_verdict":..., "article_worthy":bool}`
