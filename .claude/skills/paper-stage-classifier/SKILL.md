---
name: paper-stage-classifier
description: 論文 stage 分類（5 階段 early/draft/review/ready/submitted）+ continuous review loop 觸發頻率。決定資源分配。不負責跑審查（→ paper-review-cycle）或修訂操作（→ paper-update）。
user-invocable: true
---

# Paper Stage Classifier

## 5 Stage 分類

| Stage | 判定條件 | 動作 |
|-------|---------|------|
| **early** | < 20p, 主結構未完，1 個 contribution | 補實驗 + 寫初稿，**不審查**（reviewer 看不出價值）|
| **draft** | 20-30p, 結構完但內容粗 | Codex/Gemini 第一輪審查 + 修正。先寫滿再審 |
| **review** | 30+p, 內容齊但未經正式 review | 跑 SOP step 1 雙審查（latex-academic-reviewer + citation-verifier）→ step 2 修正 |
| **ready_for_submission** | latex-reviewer ≥ 4★ + citation-verifier 0 MAJOR + ≤3 MED | **進入 continuous review loop**（見下段）|
| **submitted** | 已投稿 journal | 監控 reviewer 回應，準備 R&R |

## Scope Boundary

Use this skill only for：

- paper stage 判定
- ready / submitted 的條件界定
- continuous review loop 何時啟動

Do **not** use this skill for：

- 實際跑 review → `paper-review-cycle`
- 實際修稿與平台同步 → `paper-update`

## Stage 判定 SOP（**只負責分類**，修訂操作 SOP 在 `paper-update` skill）

每次 `paper-update` 後立即：
1. 跑 `paper-list` 看 pages, citations
2. 對照上表判斷 stage
3. 用 `volpred ops paper-upsert --paper-id <id> --stage <stage>` 寫入 DB（若有 --stage 欄位；無則寫 details JSON）
4. 同步更新 `next_tasks.json` 的對應任務 description

修訂操作步驟（從 review report 到平台同步）→ 見 `paper-update` skill。本 skill 只負責 stage 判定 + continuous review loop 觸發頻率。

## Ready-for-Submission 持續審查迴圈

論文一旦進入 ready，**不視為「完成」**，必須持續優化：

```
[ready v_n] → /latex-academic-reviewer + /citation-verifier 並行
           → 兩 reports 寫入 paper/<id>/review_history/v<n>/（archived，不覆蓋）
           → 主線程修正 → body_v(n+1).tex + diff_v(n)_v(n+1).tex
           → xelatex main_v(n+1).tex × 2
           → uv run volpred ops paper-update --paper-id <id>
           → git commit "v(n+1) review-driven revisions + archived v(n) reports"
           → 回到 [ready v_(n+1)]，下一輪
```

### Review report 歸檔規則（**必須**）

**結構**：
```
paper/<paper-id>/
├── main_v<n>.tex                     # 當前最新版
├── body_v<n>.tex
├── review_history/                    # 所有歷史 review 都在這
│   ├── v1/
│   │   ├── citation_check_report.md
│   │   ├── academic_review_report.md
│   │   ├── README.md                  # 該輪摘要 + 行動清單 + 修正後 vs 修正前對照
│   │   └── (其他 reviewer agent 產出)
│   ├── v2/
│   │   ├── citation_check_report.md
│   │   ├── academic_review_report.md
│   │   └── README.md
│   └── ...
└── (其他工作檔案)
```

**規則**：
1. **每跑一輪 review，必須建新版本目錄** `review_history/v<n>/`
2. **舊 reports 不可覆蓋**——同 filename 在新版本目錄
3. 每個 v<n>/ 內必加 README.md 紀錄：
   - 該輪 review 觸發時間、原因、reviewer
   - 主要 issues 摘要（HIGH/MED/MINOR 數量）
   - 主線程後續動作（修了哪些、未修的理由、deferred 到 v<n+1> 的）
   - v(n) → v(n+1) 的關鍵 diff 摘要
4. **agent prompt 寫死**：寫 review 時必須指明輸出到 `paper/<id>/review_history/v<n>/`
5. Git track：`review_history/` 不放 `.gitignore`，全部 commit 進 repo

**Format：Markdown 為主**（不是 LaTeX）：
- Review 是頻繁迭代的 working document，MD 寫快讀快
- 主要產出是 action items（HIGH/MED/MINOR list），表格 + 清單 MD 更適合
- Git diff 比較 v(n) → v(n+1) review 演進，MD 一目了然
- 引用論文 sec/eq 用文字 "§4.3, eq.(7)" 即可，不需 `\ref{}`
- 公式用 inline `$...$` 即可（KaTeX/GitHub 原生支援）
- **罕見場景才用 .tex 補充**：reviewer 提出新數學推導且要嵌入論文 → `appendix_v<n>.tex`

**為什麼**：
- 6 個月後 reviewer 詢問「為何這篇 paper 改了 5 次？」→ 翻 review_history 即知
- 提交 journal 時可附 prior review log 證明 rigor
- catch deferred fixes（v1 deferred 的問題 v2 必查）
- 學術誠實：審查痕跡完整，無 cherry-pick

### 啟動頻率

| 觸發條件 | 行動 |
|---------|------|
| 第一次進入 ready | 跑全套 SOP step 1-6（雙審查 + v2 修正 + 同步） |
| 有新研究證據可加 | 立即觸發一輪 review-fix |
| 每月最低 1 輪 | 即使無新證據，catch reviewer-style 問題 |
| 用戶要求 review | 立即觸發 |

### 停止迴圈條件（→ 升 submitted）

**全部三條同時滿足**才能 mark `submitted`：
1. latex-reviewer 給 ★★★★★ 且 0 HIGH-priority recommendations
2. citation-verifier 0 MAJOR + 0 MED + ≤3 minor
3. 用戶確認 final（避免 agent 自行判定提交）

### Continuous review 在 next_tasks 的維持

每篇 ready 論文在 `next_tasks.json` 必須有：
```json
{
  "id": "<paper-id>_continuous_review",
  "title": "<paper-id> 持續審查迴圈 (current v<n>)",
  "priority": 2,
  "description": "上次 review: YYYY-MM-DD v<n>。下次計畫: YYYY-MM-DD v<n+1>。已知 outstanding fixes: ...",
  "status": "pending"
}
```

每次跑完一輪後**更新此任務**（不刪除），記錄上次/下次日期。

## 9 篇論文當前 stage 評估（2026-04-13）

| Paper ID | Stage | 證據 / 待辦 |
|----------|-------|------------|
| leverage-direction | **review** | citation 0 MAJOR ✅，**latex-reviewer 3★/5★ + 7 HIGH issues**（內部矛盾、缺 ES backtest、Proposition 1 N=6 脆弱）。需 v3 修正 7 HIGH 後再 review，預計修完可達 ★★★★ ready。詳 `paper/leverage-direction/review_history/v2/README.md` |
| vix-sufficiency | **review→expansion** | integration_plan_v2 ready，整合今日 6 實驗 +9.2p → 48p，主線程執行中 |
| volatility-absorption | **review** | 39p, 36 cites, JFE target，需 SOP step 1 雙審查 |
| taiwan-vt | **review** | Gemini 找到 3 weaknesses (TX tax/linear scaling/TSMC endogeneity)，待修 |
| garch-x-vix | **review** | 36p, 25 cites (Paper 9)，CLAUDE.md 標 main thread |
| vt-trend-following | **draft** | 33p, 19 cites, mid-stage |
| vt-insurance-cost | **early** | 14p, 17 cites, < 20p |
| vt-crowding-abm | **early** | 15p, 13 cites, < 20p |
| prg-periodic-garch | **early** | 14p, 19 cites, < 20p |

**Ready/Expansion phase 2 篇**（leverage-direction, vix-sufficiency）優先進入 continuous review loop。
**Review phase 3 篇**（volatility-absorption, taiwan-vt, garch-x-vix）依序排 SOP step 1。

## DB Schema 整合（待實作）

理想 schema 增加 `stage` column：
```sql
ALTER TABLE papers ADD COLUMN IF NOT EXISTS stage TEXT 
  CHECK (stage IN ('early', 'draft', 'review', 'ready_for_submission', 'submitted'));
```

CLI 增加 `--stage` 參數於 `paper-upsert`。

短期 fallback：用 `tags` field 加 `stage:<value>` tag 編碼。

## 對應 CLAUDE.md 條目

CLAUDE.md「論文更新標準程序」段已提此 SOP 大綱（行 ~221）。本 skill 提供完整實作細節 + ready-for-submission continuous loop 規範。CLAUDE.md 不重複內容，只 reference 此 skill。
