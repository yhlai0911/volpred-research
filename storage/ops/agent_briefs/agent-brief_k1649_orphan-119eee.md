# Task: 收尾孤兒實驗 K1649（dreaming_orphaned_experiment_k1649）

**Model**: opus / xhigh (per model_router)
**Repo**: /Users/yhlai0911/volpred-research（在你的 cwd worktree 內作業）
**Task id**: dreaming_orphaned_experiment_k1649（P3，已餓死 86h）

## 背景
`experiments/K1649/` 有完整 results 但沒有任何 consumer —— knowledge.json / feed.json / paper / open task 都沒提到 K1649，實驗 6.7 天前跑完就沒人收。這次要把它收乾淨，讓它不再是孤兒。

## 你要做的事（依序）

1. **讀懂實驗**：`experiments/K1649/README.md`、`K1649.py`、`K1649_results.json`、圖（fig_k1649_coverage.png / fig_k1649_mean_pinball.png）、`K1649_forecasts.parquet`。搞清楚：假設是什麼、資料期間與樣本、方法、主要數字、有沒有做樣本外 / 統計檢定。
2. **驗證數字**（agent-result-verification skill 的精神）：README / 結論裡宣稱的每個數字，都要能在 `K1649_results.json` 或可重跑的程式輸出裡對得上。對不上就照實記錄「宣稱 X，JSON 顯示 Y」，**不要幫它圓**。
3. **Codex 二審**：用 `.claude/skills/codex-cli` 的方式跑 `codex exec`，把實驗設計與結論交給 Codex review，要求它明確給 PASS / CONDITIONAL PASS / FAIL 並列出理由。**CONDITIONAL PASS 以上才可寫成 knowledge**；FAIL 就照實記錄 FAIL 與原因。
4. **產出提案檔**（**這是你的交付物**）：寫到 **`storage/ops/orphan_collect/k1649_knowledge_proposal.json`**，schema：
   ```json
   {
     "experiment_id": "k1649",
     "verdict": "PASS|CONDITIONAL PASS|FAIL|NULL",
     "reviewer_provenance": {"reviewer": "codex", "model": "<實際 model>", "verdict": "...", "reviewed_at": "<ISO>"},
     "proposed_entry": {"title": "...", "summary": "...", "key_numbers": {...}, "method": "...", "data_window": "...", "caveats": [...], "artifacts": [...]},
     "number_verification": [{"claim": "...", "source": "K1649_results.json:<key>", "matches": true}],
     "publishable": true,
     "publish_rationale": "為什麼值得 / 不值得寫成讀者向文章"
   }
   ```
5. **Null result 照實寫** —— null 也是結果，不要為了「有東西可寫」把 null 講成發現。

## 硬性禁令
- 🚫 **不要碰 `storage/memory/knowledge.json`**（K1259：agent 禁寫 knowledge.json）。你只產 proposal 檔，主線程負責寫入。
- 🚫 不要碰 `storage/feed.json`、不要發佈任何文章。
- 🚫 不要 force push、不要 `--no-verify`、不要編造數字。**研究誠實 > 一切**。

## 成功判準
`storage/ops/orphan_collect/k1649_knowledge_proposal.json` 存在、schema 完整、verdict 有 Codex provenance、每個 key number 都有 verification 記錄。
