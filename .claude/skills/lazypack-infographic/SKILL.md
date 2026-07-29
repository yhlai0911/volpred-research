---
name: lazypack-infographic
description: >
  Use to prepare an evidence-bound lazypack plan and verify its Operations Core
  compute receipt for a reader-facing general article. It does not own article
  prose, feed mutation, scheduler creation, or ad-hoc renderer repair.
---

# Lazypack Infographic

本 skill 擁有兩件事：**strict data-bound plan** 與 **render/install receipt readback**。文章發布由 `feed-publisher` 擁有；重型 compute 的唯一時鐘是 Operations Core。

## 1. 建立 plan

先讀完整 evidence package，不可從文章 prose 或記憶抄數字。plan schema 的單一 owner 是：

```bash
uv run python scripts/lazypack_render.py --help
```

最低契約：

- root 有版本、title、evidence aliases、panels
- 每個 evidence 記錄 repo 內 path、當下 SHA-256、label
- 每個 panel 有 name、info、style、title、alt、sources、blocks
- 數字、日期、百分比、樣本數、倍數全部以 evidence binding 取值
- 2–4 張 panel，各自只講概念、方法、結果或限制中的一種

禁止把數字藏在自由文字、手動補 renderer default、用舊 plan shape、或以 prose summary 代替 evidence。

## 2. 由 feed gateway enqueue

一般 draft／scheduled 文章從正式 publisher 一次完成 article registration 與 enqueue：

```bash
uv run python scripts/publish_draft.py <draft.md> \
  --audience general \
  --status <draft|scheduled> \
  --lazypack-plan <plan.json>
```

不要先發布再靠人工提醒補 queue；helper 的 enqueue failure 是 hard error。直接呼叫 `lazypack_async_render.py enqueue` 只限 incident repair 或已存在文章的明確恢復流程。

立即 reader-visible 的文章必在 gateway mutation 前完成同一 evidence-bound section；具體 gate 以 `scripts/publish_draft.py --help` 與 `publisher.lazypack_required_at()` 為準，skill 不保存硬編 status 例外。

## 3. Operations Core 是唯一 compute clock

正式 owner 與當前 cadence／parallelism 每次從 canonical spec 解析：

```bash
jq '.system_crontab.items[] | select(.id == "volpred-compute-worker")' \
  config/runtime_schedules.json
```

- 不建立 session scheduler、host cron、LaunchAgent 或第二個 drain loop。
- 不因等待而手動常駐 `compute_queue.py run-loop`。
- scheduler row 若有變更，以當前 config 與 Operations Core schedule receipt 為準，不從本 skill 推算下一次 fire。

## 4. 讀 compute receipt

publisher 回傳 `mile_id` 後，job identity 預設為 `lazypack-<mile_id>`；真實 identity 仍以 enqueue output 為準：

```bash
uv run python scripts/compute_queue.py show <job_id>
```

只有以下全部成立才算 render 完成：

- queue receipt `status=completed` 且 terminal exit code 成功
- frozen plan、`result_artifact`、實際 `output_paths` 存在
- renderer receipt 的 plan hash 與 panel hashes 通過
- article 已由 formal installer 加上 `## 懶人包圖組`
- published article 的 projection sync 有 acknowledged readback

若 job 沒有被啟動，先讀 `config/runtime_schedules.json` 對應 row 與 `storage/ops/schedule_receipts.json` 的自然 fire；不要另建時鐘。terminal failure 由 compute queue 建正式 repair task，禁止 silent retry 或無界 requeue。

目前 renderer layer 順序、quota 分類、bounded repair 與 fallback receipt 由 `scripts/lazypack_async_render.py --help`／module docstring 擁有；不要把實作複製到 skill，也不要自行跳層。

## 5. Reader readback

```bash
jq --arg id "<mile_id>" \
  '.[] | select(.id == $id) | {id,status,has_lazypack: (.content | contains("## 懶人包圖組"))}' \
  storage/reports/feed.json

uv run volpred ops feed-sync --dry-run
```

還要人工檢視每張 PNG：

- 無 clipping、重疊、文字溢位
- alt 與 panel 意義一致
- 顯示數字逐一對回 evidence binding
- 來源 label、期間與限制可見

## Completion readback

回報 `mile_id`、job id、terminal receipt status、plan SHA、panel 檔案與 SHA、article section readback、projection acknowledgement。只有 PNG 存在、或 queue command exit 0，都不足以宣稱完成。
