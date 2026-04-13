# 會員問題審查與流轉 Guide

本檔是 `member-questions` 的 canonical reference。所有會員問題的評分、排序、承接與回覆綁定，都以這份 guide 為準。

它整合了三類資訊：

1. `member-questions` 本身的工作流程
2. `autonomous-research/references/question-review-guide.md` 的研究判斷原則
3. `admin-ops/references/platform-api-manual.md` 的 `question-ranking` / `question-rerank` / `question-answer` 規格

## 1. 何時使用

以下情況都應讀這份 guide：

- 每 6 小時 cron 觸發「會員問題研究」
- 要評分 `pending_questions`
- 要執行 `question-rerank`
- 要從 ranked 榜單挑題並承接
- 要把完成的文章回綁到問題

## 2. 核心原則

- 每次只處理一個最高優先且尚未被承接的題目。
- 先做排名與承接，再做研究；不要先寫文章再回頭找題目掛上去。
- 研究本身交給 `autonomous-research`，文章內容交給 `feed-publisher`。
- 文章是 `draft` 時，問題狀態保持 `researching`；只有已發佈文章才讓問題進 `answered`。
- 排名更新使用 `stable insertion`：舊榜單彼此的相對順序不可亂掉。
- 所有回答都必須可追溯到具體文章與實驗，不可直接用猜測或舊記憶湊答案。

## 3. 評分維度

建議四個主維度，總分 100：

| 維度 | 建議範圍 | 判斷重點 |
|------|------:|------|
| 研究可行性 | 0-25 | 是否能在現有數據/工具/方法下被研究，而不是純空談 |
| 讀者價值 | 0-25 | 對會員是否有明確資訊價值、決策價值或教育價值 |
| 研究相關性 | 0-25 | 是否和目前研究主軸、現有策略、風險預測、波動率框架高度相關 |
| 預期影響力 | 0-25 | 若回答成功，是否值得形成完整文章、帶來新 insight 或解鎖後續研究 |

### 評分準則

- `研究可行性` 高分：
  - 題目可用現有資料驗證
  - 可以轉成實驗、表格、回測或具體文獻整理
  - 不依賴難以取得的私有資料

- `讀者價值` 高分：
  - 問題具備普遍性
  - 不是單一用戶的高度私有狀況
  - 回答後能形成可讀文章，而不只是短客服回覆

- `研究相關性` 高分：
  - 直接連到 volatility forecasting、VT、risk management、strategy design、macro-vol linkage
  - 與現有 paper / strategy / question pool 形成研究鏈

- `預期影響力` 高分：
  - 能開出後續實驗
  - 可能形成 research 或 general audience 文章
  - 可能成為 open question 的局部答案

### 低分訊號

- 純客服型、帳務型、站務型問題
- 完全無法驗證的主觀預測題
- 與研究主軸無關的即時交易問牌
- 題目太狹窄，無法形成可公開發佈的文章

## 4. `score_breakdown` 結構

推薦 payload：

```json
[
  {
    "question_id": "uuid",
    "score": 78,
    "score_breakdown": {
      "研究可行性": 24,
      "讀者價值": 26,
      "研究相關性": 14,
      "預期影響力": 14
    }
  }
]
```

規則：

- `score` = `score_breakdown` 各項加總
- 維度名稱固定，避免後續報表與程式解析不一致
- 若某題明顯不該進研究，可低分但仍保留 breakdown，方便後續審計

## 5. 排名流程

### Step 1: 讀 summary

先讀：

```bash
uv run python -m volpred.cli ops question-ranking-summary --limit 20
```

或：

```bash
uv run python -m volpred.cli ops question-ranking-workflow --limit 20
```

你應該拿到：

- `ranked_questions`
- `pending_questions`
- `evaluation_template`
- 建議下一步

### Step 2: 評估 `pending_questions`

對每個 `pending_questions` 產出：

- `question_id`
- `score`
- `score_breakdown`

### Step 3: 執行 stable insertion rerank

```bash
uv run python -m volpred.cli ops question-rerank \
  --evaluations-json /path/to/evaluations.json
```

#### stable insertion 規則

- 只把新待評分題目插進既有榜單
- 舊榜單彼此的相對順序不可變
- `researching` 題目維持在前段，不因新題進榜而被覆寫
- 回寫欄位包含：
  - `score`
  - `score_breakdown`
  - `current_rank`
  - `prev_rank`
  - `status`

## 6. 題目狀態與 candidate lifecycle

### 問題主狀態

| 狀態 | 意義 | 何時進入 |
|------|------|------|
| `pending` | 尚未評分 | 新進題目 |
| `ranked` | 已評分、在榜上待承接 | rerank 後 |
| `researching` | 已被某個 session 承接，研究中 | atomic claim 成功 |
| `answered` | 已有對應已發佈文章或正式回答 | `question-answer` 綁定 published 文章後 |

### candidate lifecycle

| 狀態 | 意義 |
|------|------|
| `queued` | 進入研究候選池，尚未被正式承接 |
| `claimed` | 某個 session 先拿走準備處理 |
| `completed` | 已完成研究/回覆 |
| `cancelled` | 本次不處理或轉移 |

## 7. 承接規則

### 選題

優先順序：

1. `ranked_questions` 中分數最高
2. 尚未被承接
3. 有足夠研究可行性
4. 沒有更高優先的用戶指派題

### Atomic claim

承接前一定要做：

```bash
uv run volpred ops question-claim <question_id>
```

結果解讀：

- `exit 0`：claim 成功，可繼續
- `exit 2`：另一個 session 已先承接，挑下一題

不要直接靠本地記憶假設「這題還沒人做」。

## 8. 研究與發文 handoff

### handoff 到 `autonomous-research`

當題目被 claim 後：

- 先做知識庫搜尋
- 必要時做新實驗或新數據整理
- 不可只複製舊 knowledge 當答案

### handoff 到 `feed-publisher`

當研究已有可公開結果：

- 產出完整文章，不是短答
- `proposer` 必須是會員名稱
- audience / category 應使用 member QA 對應設定

## 9. 發文與 `question-answer` 綁定

### 發文

```bash
uv run volpred ops publish-milestone \
  --title "..." \
  --description "..." \
  --phase member_qa \
  --category member_qa \
  --audience member_qa \
  --proposer 會員名稱 \
  --status draft \
  --tags "會員提問,..."
```

### 綁定

```bash
uv run volpred ops question-answer <question_id> \
  --answer "摘要" \
  --article-id <article_slug>
```

規則：

- 若文章仍是 `draft`：
  - 問題狀態保持 `researching`
  - 等 release-pool 真正發佈時，再由流程轉成 `answered`

- 若文章已是 `published`：
  - 問題可直接標為 `answered`

### 禁止事項

- 不要在文章仍是 `draft` 時手動把問題改成 `answered`
- 不要先改狀態再補文章綁定
- 不要發沒有 `proposer` 的 member QA 文章

## 10. 常見錯誤與邊界案例

### 常見錯誤

- 只做題目排序，沒有 atomic claim，導致多 session 撞題
- 文章是 draft，但問題被過早標成 answered
- 評分 breakdown 結構不一致，後續 summary 無法比較
- 把客服題、帳號題、站務題硬塞進研究流程

### 邊界案例

- 若問題本身很有價值，但短期資料不可得：
  - 可留在 `ranked` 或放入 candidate pool
  - 不要硬做低品質回答

- 若問題其實是 open question 的一部分：
  - 回答文章可以是局部答案
  - 但仍要保留與更大研究方向的連結

- 若問題已被部分回答：
  - 可更新 answer 摘要
  - 不必刪題，除非資料結構另有規範

## 11. 與其他 skills 的邊界

- `member-questions`
  - 負責評分、排序、承接、狀態與綁定
- `autonomous-research`
  - 負責真正的研究與實驗
- `feed-publisher`
  - 負責把結果寫成完整 reader-facing 文章
- `admin-ops`
  - 負責平台面 surfaces、池子、候選池、CLI/API 入口
