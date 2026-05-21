---
paths:
  - "paper/**/*"
  - "docs/paper-guide.md"
---

# Paper Workflow Rules

## 流程核心

- 論文 `.tex` 寫作與方法論決策留在主線程；不丟 background agent 直接改寫
- 標準流程：審查 → 修正 → 編譯 → `uv run volpred ops paper-update --paper-id <id>`
- 修訂保留 review / diff / 版本化檔案，不只覆蓋舊版
- 期刊 metadata / PDF slug / 同步細節 → `docs/paper-guide.md`
- 實驗數據或引用檢查 → 明確調用 `latex-academic-reviewer` / `citation-verifier` / `paper-update`
- **Supabase 自動同步 safety net**（2026-05-11 用戶反饋 + 6 papers updated_at 停在 April incident）：
  - `paper-sync-all` cron 每 6 小時自動掃 paper/<id>/ — local .tex/.pdf mtime > Supabase updated_at 就 push（idempotent，fresh paper 跳過）
  - 主動改完 paper 後仍**建議**手動 `uv run volpred ops paper-update --paper-id <id>` 立即同步（不要等 6h cron）
  - 手動忘記時 cron 兜底；網頁日期不會再 silently lag local edits
  - `paper-update` CLI 自動 extract abstract from main_v3.tex (2026-05-11 fix e707c232，止 abstract drift)
  - `paper-sync-all` 對新 paper 自動 create Supabase record (crypto-fear-channel 2026-05-11 案例)

## Self-contained paper folder（投稿 hard requirement）

**動機**（用戶 2026-04-17 強調）：投稿時期刊要求 replication package，資料夾不 self-contained 會被直接拒稿。

每個 `paper/<name>/` 在可投稿狀態前必含：

1. **原始資料 / data_sources.md**：`data/` 或 `data_sources.md`；原始資料在 `experiments/kXXX/data/` 或受授權限制時，此處列指標/期間/來源 API/對應實驗路徑
2. **復現腳本**：`scripts/` 或 `code/`，至少主要表/圖的產出腳本；若完整程式在 `experiments/kXXX/`，此處需 `scripts/README.md` 指出對應實驗編號與入口檔
3. **結果檔**：`results/` 或 `tables/` + `figures/`（PDF/PNG；可 soft-link `experiments/kXXX/` 圖）
4. **實驗索引**：`experiments.md` 或 `README.md` 列所有支持實驗（K 編號 + 一句話貢獻）
5. **README.md**：title / 目標期刊 / status（draft/under_review/revision/published）/ 對應實驗 K 列表 / 資料來源摘要

## 四大硬規則（觸發式提醒）

下列四條在撰寫、review、paper-update 時務必滿足；**完整教訓、格式範例、歷史 incident 全在 `.claude/skills/paper-update/references/reproduce-gate-rules.md`**（paper-update / review-cycle skill 觸發時載入）。

1. **Data snapshot pinning**：投稿用資料（yfinance/FRED/高頻）必 pin snapshot CSV；`reproduce.py` 讀 local snapshot 不 live fetch；CSV 必 `auto_adjust=False`。來源：2026-04-19 P8 K903/K904 sign-flip 教訓。
2. **Reproduce gate 是 review 先決條件**：`paper/<name>/reproduce.py` 存在、exit 0、`reproduce_report.json match_rate ≥ 95%`、`alert_level=green`；未 pass **不得跑 review / 標 ready / submit**。來源：2026-04-19 P9 garch-x-vix 無 reproduce.py 拒稿風險。
3. **Table row → JSON source 必 traceable binding**：body.tex 每個 Table row 每個數字需 inline `% source:` 指向 JSON field；reproduce.py 輸出 `table_row_mapping` 驗證；paper-update CLI gate 阻擋無 binding 的 row。來源：2026-04-19 Paper 4 K732/K736 抄錯格教訓。
4. **腳本 / 資料 / 論文三方一致**（用戶 2026-04-17 強調）：數字不符處理三選一（修腳本、修論文、明記 errata），絕不偽造/硬 code/湊 seed；重建腳本若不能 allclose 還原舊 JSON 不可靜默 commit divergent。

## 投稿前檢查清單（commit 前必跑）

- 所有 Table / Figure 對應到 `results/` 或 `figures/` 具體檔
- `scripts/README.md` 從乾淨 clone 能走到每張主表/主圖
- `data_sources.md` 列全 API endpoint / 期間 / 授權條件
- 孤兒 K ref（experiments.md 標 TODO）必補齊或明註「unused in final draft」

齊全樣板：`paper/leverage-direction/`、`paper/taiwan-vt/`、`paper/vt-trend-following/`。Kickoff 階段（outline/abstract）可暫缺但 body drafting 開始必補齊。
