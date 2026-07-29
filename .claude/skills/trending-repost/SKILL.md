---
name: trending-repost
description: >
  Use to reconstruct a current high-interest topic from primary sources and
  produce original VolPred and Facebook-native drafts. It owns trend content
  and downstream handoff only; feed mutation belongs to feed-publisher and
  Facebook delivery belongs to fb-publishing.
paths:
  - "storage/drafts/*trending*.md"
  - ".claude/skills/trending-repost/**"
---

# Trending Repost

這是**內容 producer skill**。輸出是兩份可發布草稿與證據包，不直接改 feed、不操作 FB、不建立排程，也不把 source task 假標完成。

## Ownership boundary

- 選題候選與 dedup：`publication-candidates`
- 本 skill：primary-source reconstruction、VolPred thesis、網站 draft、FB-native draft
- 語言品質：`anti-ai-style`
- Feed mutation/readback：`feed-publisher`，唯一 canonical entrypoint =
  `scripts/publish_draft.py`
- FB real-Chrome delivery/readback：`fb-publishing`

## 1. 接受正式 task

先讀 source task、live task-pool mode 與當前規則：

```bash
uv run python scripts/task_pool_control.py status
```

topic、task identity、deadline、cap 與 urgency 以 formal task receipt 和 `.claude/rules/task-routing.md` 為準；本 skill 不保存每日配額、fire 時間或 scheduler 行為。沒有正式 task 時，先交 `publication-candidates` 建 brief，不自行建立定時工作。

## 2. Source isolation

候選來源可參考 [blog-sources.md](references/blog-sources.md)，但熱門文章只用來辨識「現在大家在談什麼」。

1. 記錄 topic、來源 URL、抓取時間與一句 source thesis。
2. 離開來源文章，後續只查 primary/public sources。
3. 不複製句子、比喻、段落順序、標題或獨特 framing。
4. 文章中需要 attribution 時，引用 filing、官方資料、交易所或原始研究，不引用熱門文章替代 primary source。

## 3. Evidence package

寫第一段 prose 前，至少準備：

- 三項以上可獨立驗證的 quantitative facts
- 一張由真實資料計算的表
- 一張可重現圖
- 一層分析：描述統計、before/after、cross-section、rolling comparison、event window 或波動變化
- 每個 claim 對應的 source、timestamp、期間與計算路徑

若 topic 支撐不了這組 evidence，停止並退回選題；不能用評論語氣填補資料缺口。

## 4. VolPred thesis

只選一個主軸：

- volatility regime／IV-RV
- drawdown、VaR、hedging 或 correlation breakdown
- active strategy 的風險含義
- timing、lookahead、cross-validation 或資料口徑
- primary-source numbers 與市場 narrative 的落差

thesis 必須能由 evidence package 驗證。引用策略或 K 實驗時，回讀對應 README、程式、results 與 review，不從 knowledge 摘要轉抄數字。

## 5. 產出兩份草稿

### VolPred draft

- Traditional Chinese，`audience=general`
- 清楚 hook、primary evidence、VolPred 分析、限制與 takeaway
- 圖表、來源、alt 與 data-bound lazypack plan 齊全
- status 只寫 source task 要求的意圖，不自行 publish

### FB-native draft

按 [fb-ivanlai-tone.md](references/fb-ivanlai-tone.md) 重新寫，不複製網站正文。保存為：

```text
storage/drafts/fb_<mile_id>.md
```

若 feed gateway 尚未產生 `mile_id`，先交付可重命名的 provisional FB draft；取得真實 id 後，必經 `mark_fb_post_status.py --draft-file` 落到 canonical path，不能只留 `/tmp`。

## 6. Quality gate

```bash
uv run python scripts/anti_ai_gate.py --file <volpred-draft.md> --no-fb-mode
uv run python scripts/anti_ai_gate.py --file <fb-draft.md>
```

另做：

- 數字逐一對 primary source
- methodology／lookahead review
- source-level plagiarism review
- 文章 draft 與 FB draft 的語句相似度人工檢查

任一 gate fail 就重寫；不能靠 publisher bypass 或 delivery retry 掩蓋內容問題。

## 7. Handoff

交給 `feed-publisher`：

- VolPred draft
- evidence 路徑、圖與 plan
- source task id、task type、status intent
- anti-AI／dedup／methodology verdict

取得真實 `mile_id` 後交給 `fb-publishing`：

- canonical FB draft
- 圖片
- 由 active runtime target 解析且已驗證的留言 URL

本 skill 不呼叫 feed mutation、不操作 real Chrome、不直接寫 feed 或 FB status。

## Completion readback

內容階段只有在以下條件成立才可標 `handoff_ready`：

- primary-source evidence package 完整
- VolPred 與 FB 兩份草稿都存在
- 兩個 anti-AI gate exit 0
- 圖表與 lazypack plan 可重現
- 下游 owner、輸入路徑與 source task identity 已記錄

`handoff_ready` 不等於整張 source task `succeeded`。整體 completion 仍須依 source task acceptance，回讀 `feed-publisher` 的 mile/projection/live receipt，以及 `fb-publishing` 的 canonical draft/delivery receipt。
