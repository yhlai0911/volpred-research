---
name: project_prepublish_content_gate
description: 文章發佈前有 content-vs-source 正確性 gate（prepublish_audit.py）；正確性驗證在 publish 之前不是之後
metadata: 
  node_type: memory
  type: project
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

2026-06-03 3-strike 重構（`docs/refactor_plan_prepublish_content_gate.md`）：reader-facing 文章「發佈後 24h Codex review 才抓到 content-vs-source FAIL」復發 ≥4 次（K263 / mile_7ba7ee54 / K562 / K1413）。根因 = 正確性驗證放在 publish **之後**；對 trending「立刻發」尤其致命（錯誤先進線上+FB 才事後更正）。

## 現在的 gate（`src/volpred/publisher/prepublish_audit.py`，wire 在 `publish_milestone` status flip 前）
- **Tier-1 deterministic numeric provenance**：article 裡帶統計語境的數字必須 verbatim 出現在 cited `experiments/<k>/<k>_results.json`（%換算在 claim 端處理）。找不到 → `audit_strict=True` 時 raise（hard block，trending 立即發也擋）。抓 **fabrication / stale**（K562 類 headline Sharpe 不在任何 json）。
- **Tier-2 fast agy LLM conclusion-consistency**：warn-only + `content_audit_flagged=True` stamp + 不 block。抓**結論與 source 衝突**（K1413 類「現況最抖誤判」、mile_7ba7ee54 類策略混用）。
- gate 自身例外 → degrade 但 `content_audit_flagged` + `send_alert`（不靜默）。

## 連帶修的 silent-sync（根因 B）
`scripts/supabase_sync.py` incremental 改 **content-hash-based**（`_article_hash`），不再純 timestamp-gated。**改 content 沒 bump `updated_at` 也會同步**；per-article `reports/<id>.json` body 編輯的 mtime 也納入 sync guard。

## 教訓（最高層）
- **對外發佈的正確性驗證必須在 publish 之前**，post-hoc 24h review 是 backstop 不是 gate。「更嚴格執行 24h-rule」是表面補丁，不解決「錯誤先進線上」。
- trending「立刻發」≠「免驗證發」— 快速 deterministic gate 不犧牲時效。
- 文章數字必須 **verbatim** 對得上 source；derived（差值/平均/比率）不在 source 會被擋 → 引用 component 值或把 derived 值寫進 results.json。
- 看見結構根因（驗證在錯誤時序位置）立刻三層重構，不再加「更嚴格執行」。

相關：[[feedback_3model_review_discipline]]（24h 三模 review 仍是 backstop）、[[feedback_report_content_sync]]、[[reference_publisher_strict_audit_tag_rules]]。
