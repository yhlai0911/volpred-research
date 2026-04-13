---
name: paper-review-cycle
description: >
  論文審查迴圈標準作業：跑 latex-academic-reviewer + citation-verifier 雙審查 → 歸檔 review_history/v(n)/ → 寫 README 摘要。
  每篇論文每輪 review 的 SOP。Stage 由 paper-stage-classifier 決定，修訂操作由 paper-update。
  Trigger phrases: '論文審查', 'paper review', 'review cycle', '審查迴圈', '雙審查'
user-invocable: true
---

# Paper Review Cycle SOP

**只負責「跑審查 + 歸檔」**。不分類（→ paper-stage-classifier）、不修訂（→ paper-update）。

## 當下啟動條件

任一以下情況啟動一輪 review cycle：
1. 論文進入 `review` 或 `ready_for_submission` stage（首次）
2. v(n+1) 已完成修訂，需要新一輪審查
3. **每月最低 1 次**（Ready 論文，catch reviewer-style 問題）
4. 用戶要求

## 標準執行（4 步）

### Step 1: 並行啟動兩個 review agents

```bash
# Agent 1 (citation-verifier)
prompt: "Run citation-verifier on paper/<id>/main_v<n>.tex.
        Output to paper/<id>/review_history/v<n>/citation_check_report.md
        Format: Markdown."

# Agent 2 (latex-academic-reviewer)  
prompt: "Run latex-academic-reviewer on paper/<id>/main_v<n>.tex + body_v<n>.tex.
        Output to paper/<id>/review_history/v<n>/academic_review_report.md
        Format: Markdown."
```

**並行**（非串行）以省時間。兩 agent 互不依賴。

### Step 2: 等兩 agents 回報

待兩個 review 都產出後再進入 step 3。一個完成另一個還沒，**不要**先動 v(n+1) 修正。

### Step 3: 寫 round summary README

`paper/<id>/review_history/v<n>/README.md`：

```markdown
# Review Round v<n> — <paper-id>

**Date**: YYYY-MM-DD
**Triggered by**: <stage entry / user request / monthly cycle / new evidence>
**Reviewers**:
- citation-verifier (agent <id>)
- latex-academic-reviewer (agent <id>)

## Overall Assessment
| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | <X MAJOR / Y minor / Z MED> | ✅/⚠️ |
| Academic | <verdict + 預測 journal response> | <stars> |

## Issues Summary
### HIGH severity (N) — blocking submission
1. ...
### MEDIUM (M)
1. ...
### Minor
- ...

## Action Plan for v<n+1>
**主線程必修**:
1. ...
**可 deferred 到 v<n+2>**:
- ...
**Prediction**: if all HIGH fixed → ?★/5

## Files in this round
- citation_check_report.md
- academic_review_report.md
- README.md (本檔)

## Next round trigger
After 主線程完成 v<n+1> 修正 → 新一輪 → 寫入 review_history/v<n+1>/
```

### Step 4: 更新 stage（呼叫 paper-stage-classifier 邏輯）

依 review 結果判定 paper 應停留在哪個 stage：
- 若 latex ≥ 4★ + citation 0 MAJOR + ≤3 MED → 升 ready_for_submission
- 否則 → 留 review，等 v(n+1) 修正

→ `volpred ops paper-upsert --paper-id <id> --stage <stage>` (若 CLI 支援)
→ `next_tasks.json` 對應任務 description 同步更新

## Review Report Archive 規則（MUST）

```
paper/<id>/
└── review_history/
    ├── v1/
    │   ├── citation_check_report.md
    │   ├── academic_review_report.md
    │   └── README.md
    ├── v2/...
    └── ...
```

- **每跑一輪建新版本目錄**
- **舊 reports 不可覆蓋**——同 filename 在新版本目錄
- **Format = Markdown**（review 是 working doc，不是 publication doc）
- 公式用 inline `$...$`（KaTeX/GitHub 原生支援）
- 引用論文 sec/eq 用文字 `"§4.3, eq.(7)"`，不用 `\ref{}`
- **罕見場景**才用 `appendix_v<n>.tex`：reviewer 提出新數學推導
- **Git track 全部 commit 進 repo**（review_history 不放 .gitignore）

## 為什麼 review report 必須 archive

1. 6 個月後 reviewer 問「為何這篇 paper 改了 5 次？」→ 翻 review_history 即知
2. 提交 journal 時可附 prior review log 證明 rigor
3. catch deferred fixes（v1 deferred 的問題 v2 必查）
4. 學術誠實：審查痕跡完整，無 cherry-pick

## Agent prompt 必含的歸檔指令

當啟動 review agent 時，prompt 必寫死輸出 path：
```
"...output the report to paper/<id>/review_history/v<n>/{citation_check_report.md|academic_review_report.md} —
do NOT write to paper/<id>/ top-level."
```

避免寫到 top-level 後手動 mv（本 session 已踩過坑）。

## 與其他 skill 的關係

- **stage 判定**（什麼時候該跑 cycle、cycle 後升 stage）→ `paper-stage-classifier`
- **修訂操作**（v(n+1) tex 編輯 + 編譯 + 平台同步）→ `paper-update`
- **review 內容方法論**（什麼是好 citation 審查、什麼是好 latex 審查）→ `citation-verifier` + `latex-academic-reviewer`
- 本 skill 只負責 cycle 編排 + archive
