---
paths:
  - "storage/memory/**"
  - "storage/reports/**"
  - "storage/**/*.json"
  - "scripts/token_usage_report.py"
---

# Context Hygiene / Token 紀律

當 Claude 觸及 `storage/memory/**`、`storage/reports/**` 或任何 `storage/**/*.json` 路徑時自動觸發。

## 硬規則

1. **禁止整檔 Read** `storage/reports/feed.json`（2000+ 篇 feed 全量）。
   - 合法入口：`jq`、`grep`、單篇 `storage/reports/<id>.json`。
   - 一次需要多篇時用 `jq` 投影最少欄位（`{id, title, status, published_at}`）。
2. **禁止整檔 Read** `storage/memory/knowledge.json`（2000+ K 條目）。
   - 合法入口：`jq '[.[] | select(...)] | map(...)' storage/memory/knowledge.json`。
   - 查特定 K 用 `jq '.[] | select(.item_id == "K1098")'`。
3. **禁止整檔 Read** 其他大 JSON (`paper_trading.json`, `strategy_metrics.json` 等)。用 jq 先 pre-filter。
4. **重複性流程用 skill**，不要把長 SOP 貼進主對話（`.claude/skills/` 有對應 skill 就用）。
5. **sub-agent 隔離** — 若新任務與當前上下文、已載入 skills、或主對話無關，**必須另開乾淨 sub-agent**。目的：隔離大搜尋、大量 logs、文件探索、無關 side task，減少 context 汙染與 token 損耗。

## 沒遵守的代價

- Token 用量日報 `💬 純文字回覆（無工具）` 類別佔比 > 40% 是高消耗警告
- 2026-04-18 單日 token 用量 $1897 其中 50.3% 是無工具純文字 — 主因是把大檔 Read 結果或 ad-hoc SOP 貼進主對話
- Mission L19「資源分配要反映目標優先序 — 研究與論文永遠不輸給 ops」：context 浪費在 ops = 研究 / 論文的 token 不足

## 判斷法則

> 「我要 Read 的檔 > 500 行或 > 50KB 嗎？」→ 是 → 用 jq/grep 投影
> 「這件事燒 > 3000 tokens 嗎？」→ 是 → 派 sub-agent
> 「這 SOP 我每次都要抄一次嗎？」→ 是 → 寫成 skill
