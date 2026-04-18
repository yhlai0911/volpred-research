---
paths:
  - "paper/**/*"
  - "docs/paper-guide.md"
---

# Paper Workflow Rules

- 論文 `.tex` 寫作與方法論決策留在主線程；不要丟給 background agent 直接改寫。
- 標準流程：審查 → 修正 → 編譯 → `uv run volpred ops paper-update --paper-id <id>`。
- 修訂時保留 review、diff、版本化檔案，不要只覆蓋舊版。
- 期刊 metadata、PDF slug、同步細節看 `docs/paper-guide.md`。
- 若涉及實驗數據或引用檢查，主線程應明確調用 `latex-academic-reviewer`、`citation-verifier`、`paper-update` 等技能。

## 論文資料夾必備內容（Self-contained paper folder）

**動機（用戶 2026-04-17 強調）**：投稿時期刊要求附上原始資料與腳本供審稿人復現（replication package / supplementary materials）。若資料夾不 self-contained，到投稿那一刻才補會措手不及；審稿人收到不完整 package 會直接拒稿。**此為投稿 hard requirement，非 nice-to-have**。

每個 `paper/<name>/` 在論文達到可投稿狀態前，**必須**包含以下 5 項：

1. **原始資料或資料清單**：`data/` 子目錄或 `data_sources.md`（若原始資料在 `experiments/kXXX/data/` 或受授權限制，此處列指標、期間、來源 API 與對應實驗路徑）
2. **復現腳本**：`scripts/` 或 `code/` 子目錄，至少收錄主要表/圖的產出腳本；若完整程式在 `experiments/kXXX/`，此處需有 `scripts/README.md` 指出對應實驗編號與入口檔
3. **結果檔**：`results/` 或 `tables/` + `figures/`（輸出 PDF/PNG 表格與圖；可用 soft-link 指向 experiments/kXXX/ 圖）
4. **實驗索引**：`experiments.md` 或在 `README.md` 列出所有支持實驗（K 編號 + 一句話貢獻）
5. **README.md**：論文 title、目標期刊、status（draft/under_review/revision/published）、對應實驗 K 列表、資料來源摘要

**投稿前檢查清單**（投稿 commit 前必跑）：
- 所有 Table X / Figure X 在 main.tex 都能對應到 `results/` 或 `figures/` 的具體檔
- `scripts/README.md` 能從乾淨 clone 走到每張主表/主圖
- `data_sources.md` 列全 API endpoint、期間、授權條件（含付費資料的取得管道）
- 孤兒 K ref（experiments.md 標 TODO 的）必須在投稿前補齊或明註「unused in final draft」

### 腳本 / 資料 / 論文數字必須三方一致（用戶 2026-04-17 強調）

**「所有論文中的腳本和資料都要能直接跑出最新的論文內結果。」**

每次論文數字更新（新實驗、revision、OOS 延長）後，對應腳本必須能產出**與論文 body 內寫的數字一致**的結果。具體操作：

1. **reproduce 檢查常駐**：`paper/<name>/reproduce.py` 或 `scripts/reproduce_all.sh`，一鍵重跑產出 `reproduce_report.json`；若該 paper 有 `reproduce_report.json`，則 CI / 投稿前必須重跑對齊。
2. **數字不符處理三選一**：
   - (a) **修腳本到符合論文**（合理路徑：腳本有 bug、資料切片錯誤、參數 drift）
   - (b) **修論文到符合腳本**（合理路徑：研究誠實原則 — 發現舊數字有錯 → 主線程改論文 + 記 error_log + paper-update workflow）
   - (c) **明記 errata**（暫時接受 divergence，但 commit message / README 必須明標 "pending errata, magnitude <X>%"；**不得靜默保留不一致**）
3. **絕對禁止**：為了 match 論文數字而偽造腳本輸出、硬 coded 結果、調整隨機 seed 直到湊到。研究誠實原則優先於任何「看起來齊全」的表象。
4. **重建的腳本**（如 K716-K722 case）：若 reconstruction 未能 allclose 還原舊 JSON → 必須走 (a)(b)(c) 其一決策，不可靜默 commit divergent 狀態。

參考範例：`paper/leverage-direction/`、`paper/taiwan-vt/`、`paper/vt-trend-following/`（均為齊全樣板）。

Kickoff 階段（僅 outline/abstract）可暫缺，但 body drafting 開始時必須補齊；第一次投稿前跑投稿前檢查清單。
