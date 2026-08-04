---
name: fb-publishing
description: >
  Use to deliver a prepared VolPred Facebook-native draft to Ivan Lai's
  personal Facebook through the sole supported real-Chrome worker, including
  idempotency, images, first-comment link, status writing, and readback. It
  does not write the feed article or choose the topic.
---

# Facebook Publishing

`fb-publishing` 是 **FB delivery 的唯一 owner**。唯一可操作瀏覽器的機制是：

```bash
uv run python scripts/fb_realchrome_post.py --help
```

不得改用其他 browser automation、headless browser、Graph API、MCP 或人工拼接 DOM 步驟。真 Chrome profile、attach 與一次性登入設定只看 `docs/fb_realchrome_setup.md`，不在 skill 重複 runtime 細節。

## Ownership boundary

- 內容 producer：完成 FB-native 文案、圖片清單與留言連結。
- `feed-publisher`：建立／更新 VolPred 文章並回傳真實 `mile_id`。
- **本 skill**：real-Chrome preflight、dry-run、送出、第一則留言、canonical status 與 readback。
- `mark_fb_post_status.py`：唯一 FB state writer。禁止直接改 feed 或 trending log。

## 1. 輸入契約

Canonical draft：

```text
storage/drafts/fb_<mile_id>.md
```

必含：

- `mile_id`
- 主貼文：FB-native 短文，正文不放外部連結
- 第一則留言：由 `config/project_targets.json` 的 `site.default_remote_url` 衍生，且 publish 前 HTTP 200
- 圖片：至少一張；內容重複的結果圖與懶人包圖要先去重

文案規則見 [fb-ivanlai-tone.md](../trending-repost/references/fb-ivanlai-tone.md)，並先通過：

```bash
uv run python scripts/anti_ai_gate.py --file storage/drafts/fb_<mile_id>.md
```

背景 producer 若只能 handoff，使用 formal writer：

```bash
uv run python scripts/mark_fb_post_status.py \
  --mile-id <mile_id> \
  --status awaiting_interactive_session \
  --draft-file <completed-fb-draft.md>
```

writer 會持久化 canonical draft；缺稿會 fail closed。

## 2. Preflight 與查重

```bash
uv run python scripts/fb_realchrome_post.py --check
```

只有 attach、登入與專用 profile 全通過才繼續。發布前：

- 先讓 worker 的 idempotency guard 檢查 canonical FB state。
- 用同一 real-Chrome surface 確認 timeline 沒有老闆手動或其他管道先發的同主題。
- 不確定是否重複時停止並回報，不用 `--force` 猜測。

## 3. 兩段式 delivery

```bash
# 停在送出前，檢查正文、圖片縮圖與留言
uv run python scripts/fb_realchrome_post.py \
  --post storage/drafts/fb_<mile_id>.md \
  --dry-run

# 確認後只送一次
uv run python scripts/fb_realchrome_post.py \
  --post storage/drafts/fb_<mile_id>.md
```

worker 必須一次完成主貼文與第一則留言；不得用 FB 原生排程把兩者拆開，也不得 retry-loop。中文輸入、剪貼簿驗證、圖片上傳與 permalink capture 都交給 worker 實作。

`--force` 只在已確認刪除或撤回舊版、且用戶明確要求重發時使用。

## 4. Destructive correction

刪除貼文是外部破壞性動作，只在用戶明確要求時走 worker 的兩段式：

```bash
uv run python scripts/fb_realchrome_post.py --delete-matching "<anchor>"
# 檢視 worker 產生的目標截圖
uv run python scripts/fb_realchrome_post.py \
  --delete-matching "<anchor>" \
  --confirm-delete
```

未先確認截圖，不得執行 `--confirm-delete`。

## 5. Completion readback

delivery 結束後執行：

```bash
uv run python scripts/audit_fb_pipeline.py

jq --arg id "<mile_id>" \
  '.[] | select(.id == $id) | {
    id,
    fb_post_status,
    fb_post_url,
    fb_post_status_updated_at
  }' storage/reports/feed.json
```

**欄位在頂層，不在 `.details`。** 2026-06-01 的 `migrate_fb_post_status_single_source.py` 已把
`fb_post_status` 收斂成單一來源：canonical writer（`mark_fb_post_status.py`）與 worker 的
idempotency guard（`fb_realchrome_post.py:_fb_post_status`）讀寫的都是 feed entry 的**頂層**欄位。
查 `.details.fb_post_status` 一定回 null，而那個 null 讀起來像「根本沒發出去」——已經誤導過一次
（`docs/error_log_archive/2026-Q3.md` 差點把成功的貼文判成假宣告），2026-08-01 再犯一次。驗證對外
狀態一律查「guard 實際讀的那個欄位」。

完成條件：

- canonical status 是 terminal success，或 worker 明確 idempotent skip
- permalink 已捕捉且對應本篇
- timeline 可見主貼文與正確圖片
- 第一則留言的 VolPred URL 可開啟
- `audit_fb_pipeline.py` 不再把本篇列為 pending、missing draft 或 stale

Chrome 暫不可用時只能回報 `awaiting_interactive_session`；這代表 handoff 已保存，不代表 delivery 完成。FB delivery 失敗不回滾已正確發布的 feed article，但要保留正式狀態與 retry owner。

## 歷史與其他 surface

[fb-page-operations.md](../trending-repost/references/fb-page-operations.md) 只保留歷史背景，不是 active runbook。現行 delivery 一律以本 skill、`fb_realchrome_post.py --help` 與 canonical status writer 為準。
