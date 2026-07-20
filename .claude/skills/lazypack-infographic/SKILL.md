---
name: lazypack-infographic
description: |
  Use this skill when producing a 懶人包 (cheat-sheet) infographic SET for a
  reader-facing article (audience='general', including reader-facing event,
  daily, digest, and trending pieces). PRIMARY path (boss 2026-07-15): codex
  exec writes a data-bound bespoke poster script (scripts/gen_lazypack_codex.py)
  executed locally; deterministic scripts/lazypack_render.py is the FALLBACK
  (template look — boss-flagged as ugly). Numbers must always bind to evidence
  JSON; the main-thread LLM never writes or repairs rendering code itself.
---

# lazypack-infographic — 確定性懶人包圖組

每篇一般讀者文章在 reader-visible 邊界必須有文末 `## 懶人包圖組`，通常含 2–4 張獨立 PNG。每張只講一種資訊型態：概念、方法、結果或結論；禁止把全部資訊塞進單張。

## 渲染鏈：codex bespoke = PRIMARY，deterministic = FALLBACK

三層順位（boss 2026-07-15 拍板；provenance 見下方「視覺分層」）：

1. **PRIMARY = `codex exec` bespoke poster**：

   ```bash
   uv run python scripts/gen_lazypack_codex.py \
     --article-id <mile_id> --plan <plan.json> --out-dir <dir>
   ```

   codex **寫**一支 data-bound Pillow/matplotlib 腳本、本 process 本地執行；腳本存檔於 out-dir、可重跑復現。

2. **FALLBACK = deterministic renderer**（模板級外觀，只准當 fallback）：

   ```bash
   uv run python scripts/lazypack_render.py --plan <plan.json> --out-dir <dir>
   ```

   codex 不可用（CLI 故障 / **額度耗盡** / 逾時 / 修復輪耗盡）時**順位自動生效** — async 管線由 `_record_fallback` 機械留痕；互動 session 手動走 fallback 必須在 work_log 註記。禁止 silent fallback。

3. **NotebookLM AI-poster = 最後備援**：僅前兩條都不可用時人工授權 + 覆核；不得自動 fallback。

兩條渲染路徑吃**同一份 strict plan v1**（schema 見下；owner = `lazypack_render.py`），evidence hash 驗證與 data-bound 硬規則不因 renderer 而異。主線程 LLM 的責任只到：讀 evidence、選 panel、寫繁中短文、指定 JSON 欄位綁定。主線程 LLM 不得把 evidence 數字抄成 literal、不得自己寫渲染腳本、不得在 layout fail 後修補程式 — bespoke 腳本由 codex 寫、修復輪也由 codex 修（`gen_lazypack_codex.py` bounded repair rounds）。

## 生圖時機：draft async、立即發佈同步

- **draft（一般 daily_article 等）**：正文 publish 成 draft 後 enqueue；compute worker 走 codex-primary 渲染鏈（失敗自動 logged fallback 到 deterministic renderer）出圖、上傳、append section、單篇 re-sync。

  ```bash
  uv run python scripts/lazypack_async_render.py enqueue \
    --article-id <mile_id> --plan <plan.json>

  uv run python scripts/compute_queue.py show lazypack-<mile_id>
  ```

- **立即發佈（event_article / trending_repost / published daily_digest）**：先同步執行同一 codex-primary 渲染鏈（`gen_lazypack_codex.py`；失敗才 logged fallback 到 `lazypack_render.py`），完成上傳與 section append 後才 publish。

Gate 邊界單一來源：`volpred.publisher.publisher.lazypack_required_at()`；draft/scheduled 建檔可先放行，published 必須已有 section。

## plan.json v1 契約

Root 必填 `schema_version: 1`、`title`、`evidence`、`panels`。`evidence` 是 alias map；每個 alias 必填 `{path, sha256, label}`。每個 panel 必填 `{name, info, style, title, alt, sources, blocks}`。`blocks` 以 `kind` 區分，只接受 `text` 與 `metric`；任何數值都必須由 `value: {source, path, format}` 綁 evidence JSON，其中 `format` 是格式物件。

最小結構範例（`sha256` 要換成 evidence 實際值；production 必須有 2–4 個 panels）：

```json
{
  "schema_version": 1,
  "title": "K1413 懶人包",
  "evidence": {
    "results": {
      "path": "experiments/k1413/k1413_results.json",
      "sha256": "<64-character-lowercase-sha256>",
      "label": "experiment K1413 results"
    }
  },
  "panels": [
    {
      "name": "1_framework",
      "info": "concept",
      "style": "professional",
      "title": "先分清楚訊號與結果",
      "alt": "訊號與結果的概念框架",
      "sources": ["results"],
      "blocks": [
        {
          "kind": "text",
          "heading": "讀法",
          "body": ["先看資料在回答哪一個問題，再看數字大小。"]
        },
        {
          "kind": "metric",
          "label": "樣本數",
          "value": {
            "source": "results",
            "path": "summary.n_obs",
            "format": {"kind": "integer", "suffix": " 筆"}
          }
        }
      ]
    },
    {
      "name": "2_results",
      "info": "results",
      "style": "bento-grid",
      "title": "主要結果與研究邊界",
      "alt": "主要結果與研究邊界",
      "sources": ["results"],
      "blocks": [
        {
          "kind": "metric",
          "label": "樣本數",
          "value": {
            "source": "results",
            "path": "summary.n_obs",
            "format": {"kind": "integer", "suffix": " 筆"}
          }
        }
      ]
    }
  ]
}
```

完整欄位、format 與驗證方式以 `uv run python scripts/lazypack_render.py --help` 及 renderer tests 為準；不要把 renderer 實作複製進 skill。

### Data-bound 硬規則

1. `path` 指向 repo 內真實 evidence JSON；`sha256` 必須是該檔案當下內容雜湊。renderer 會驗證，不符即停。
2. `sources` 只列該 panel 實際引用的 evidence aliases；圖底資料來源由這些 labels 產生。
3. `metric.value.source` 必須存在於 root `evidence` 且列在該 panel 的 `sources`；`path` 必須解析到既有欄位。含點或斜線的 JSON key 用 RFC 6901 pointer（例如 `/weights/1515.TW`）。欄位不存在就 raise。
4. 數字、日期、百分比、樣本數、倍數等不可藏在 `text` 或標題中硬編；使用 metric binding 與 renderer 支援的 format。
5. 舊版 root list、缺少必填欄位、未知 block `kind` / info / style / format 一律 fail。**禁止**自動轉換、補預設值或 silent LLM fallback。

## 內容與視覺規則

- 全部繁體中文；一般讀者可讀，但不可刪掉證據強度與限制。
- 來源用完整 evidence package，而不是只讀文章 prose；prose 是 lossy summary。
- `concept`：核心框架或名詞；`method`：白話步驟與資料口徑；`results`：主要數字與限制；每 panel 聚焦一種型態。
- 專業、簡潔、資料導向；style 只用 `professional`、`editorial`、`bento-grid`、`scientific`。禁卡通、可愛、anime、clay、手繪與塗鴉風。
- renderer 完成後必跑 layout guard；任何 clipping、文字碰撞或卡片溢位都視為失敗，不准帶病發布。
- 人工檢視 PNG，逐項核對 evidence path、格式化結果、來源 label 與 alt；歷史結果不得憑記憶填入。

## 視覺分層（boss directive 2026-07-15 晚間升級：codex = 所有 reader-facing 預設）

老闆 2026-07-15 晚間直接指令：「懶人包圖不是改走 codex 生成嗎？現在的懶人包圖還是 render 得很醜」— 據此，原「未來選項」正式啟動，**`codex exec` bespoke poster（`scripts/gen_lazypack_codex.py`）成為所有 reader-facing 懶人包的預設 primary**（不再限旗艦篇）：

1. **PRIMARY = `codex exec` bespoke poster**（`scripts/gen_lazypack_codex.py`）：codex **寫**一支 data-bound Pillow/matplotlib 腳本、本 process 本地執行；每個數字由 evidence JSON 讀出、腳本存檔可重跑（研究誠實不變）；ChatGPT 訂閱 flat-rate 零增量成本。CLI：`--article-id <mile_id> --source <evidence.json> --plan <plan.json> --out-dir <dir>`。
2. **FALLBACK = 確定性 renderer（`lazypack_render.py`）**：codex 不可用（CLI 故障 / 額度耗盡 / 逾時 / 修復輪耗盡）時的可靠退路，**順位自動生效** — 零 LLM、秒級、零幻覺，但視覺是模板級（老闆已兩度嫌醜），**只准當 fallback；async 管線由 `_record_fallback` 機械留痕，互動 session 手動 fallback 必須在 work_log 註記**（不得 silent）。
3. **NotebookLM AI-poster → 最後備援**：僅在前兩條都不可用時人工授權 + 覆核；不得自動 fallback。

按張計費影像 API（`gpt-image-2`、付費 Gemini key 等）仍禁止用於此流程。

> **管線改寫已落地（2026-07-16 commit c89a87021）**：`lazypack_async_render.py` 已接 codex-primary — compute worker `run` 先跑 `gen_lazypack_codex.py`，失敗才走 deterministic fallback 並寫 `_record_fallback` 事件（receipt 記 `primary_renderer` / `fallback_renderer`；gate = `tests/test_lazypack_async_pipeline.py`）。draft 文章照常 enqueue async 佇列即可；同步（立即發佈）與 async 兩條 lane 現在是同一條渲染鏈。

## 發佈後處理

1. 每張 PNG 上傳 Supabase `article-images` bucket。
2. 依 panel 順序 append 到文章末尾 `## 懶人包圖組`，alt 使用 plan 的 `alt`。
3. 走正式單篇 feed sync / queue completion 流程，不手改歷史 feed 或 Supabase 欄位補洞。

## 交叉參考

- `scripts/gen_lazypack_codex.py`（PRIMARY bespoke harness；flow / timeout / repair rounds 見其 docstring）
- `scripts/lazypack_render.py --help`（plan schema、format、CLI；strict plan v1 的 owner）
- renderer 與 async pipeline tests（合法/缺欄位/舊 list/layout regression、primary→fallback receipt）
- `.claude/rules/publishing.md`（reader-visible gate）
- `scripts/lazypack_async_render.py`（draft queue；codex-primary + logged fallback）
