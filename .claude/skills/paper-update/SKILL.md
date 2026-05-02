---
name: paper-update
description: >
  論文修訂操作 SOP — body_v(n+1).tex → xelatex → paper-update CLI → commit
  → 驗證 API。只負責修訂操作；review 由 paper-review-cycle 負責，stage 由
  paper-stage-classifier 負責。Trigger phrases: 'paper-update', '更新論文',
  '同步論文平台'. Do not use for review orchestration（use paper-review-cycle）
  或 stage 判定（use paper-stage-classifier）。
model: sonnet
effort: medium
user-invocable: true
---

# Paper Update SOP

**只負責「修訂 + 同步」**。不審查（→ paper-review-cycle）、不分類（→ paper-stage-classifier）。

## Scope Boundary

Use this skill for：

- review 後的 tex 修訂
- compile 驗證
- `volpred ops paper-update` 平台同步

Do **not** use this skill for：

- review orchestration → `paper-review-cycle`
- stage 判定 → `paper-stage-classifier`

## 啟動條件

review_history/v(n)/README.md action plan 已就緒，主線程要把 v(n+1) 修出來。

## 6 步 SOP（不可跳步）

```
1. 修正（主線程，不可用 agent，per CLAUDE.md「禁止用 agent 寫論文」）：
   - body_v(n+1).tex（保留原版 v(n)）
   - main_v(n+1).tex 對應更新 \input{}
   - v(n)_to_v(n+1)_diff.md（變動摘要，供 reviewer log）

2. 編譯（驗 latex 無 error）：
   - cd paper/<id> && xelatex main_v(n+1).tex && xelatex main_v(n+1).tex
   - 確認 PDF 出來
   - 確認 page count 合理

3. 一鍵同步平台：
   - uv run volpred ops paper-update --paper-id <id>
   - 自動：計算 pages + citations → 上傳 PDF → 更新 metadata → 複製到前端

4. Git commit：
   - 含 review_history/v(n)/* + body_v(n+1).tex + main_v(n+1).tex + diff
   - Message: "Paper <id> v(n+1): <核心修正主題>"

5. 驗證：
   - curl API 確認 pages/citations/pdf_url 正確
   - 看前端 /paper 頁面顯示無誤

6. 觸發下一輪 review_history（呼叫 paper-review-cycle skill）
```

## ⚠️ 規則

- **agent 禁止寫 .tex**（per CLAUDE.md）—— 修訂必須主線程
- **修正完不跑 step 3 = 沒修**——paper-update CLI 取代手動 upload + metadata update
- 每次 commit 必含 review_history/v(n)/ 全部檔案
- v(n+1).tex 完成後立即觸發新一輪 review（→ paper-review-cycle）

## 與其他 skill 關係

- **review 跑不跑、何時跑** → `paper-review-cycle`
- **stage 升降判定** → `paper-stage-classifier`
- **本 skill 只在 review reports ready，要動 .tex 寫 v(n+1) 時用**
