---
name: feedback_notebooklm_deprioritized_codex_figures
description: Owner 2026-07-15 定調：NotebookLM 放後面（確定）；圖表/懶人包生成走 Codex primary path（Codex 畫的圖好太多）
metadata:
  node_type: memory
  type: feedback
  originSessionId: telegram-784
---

Owner 2026-07-15 (Telegram msg 784) directive：「你是運營經理，你決定；但 NotebookLM 已經被我放到後面，這是確定的；畢竟 Codex 畫的圖好太多了。」

**內容**：
- NotebookLM 明確降級（back-burner），不再是圖表/視覺生成的首選。
- 圖表 / 懶人包（lazypack infographic）生成走 **Codex primary path**（含自寫 matplotlib renderer 如 `render_lazypack.py`）。Codex 圖品質明顯優於 NotebookLM。
- NotebookLM 仍保留其 **文獻 RAG** 用途（見 [[reference_notebooklm_rag_workflow.md]]），只是「圖 / 視覺產出」這一塊被 Codex 取代、整體優先序後移。
- 老闆把運營層決策授權給我（ops manager），不必逐次徵詢。

**Why**：老闆實測比較後認定 Codex 圖遠優；這是明確的工具選型定調，不是暫時傾向。

**How to apply**：
- queued 的 `platform_ops_enforce_lazypack_in_publish_pipeline`（原標「需 NotebookLM」）改走 Codex figure path / 自寫 renderer，NotebookLM 僅作 fallback。
- 任何「生成圖 / 懶人包 / 視覺」的選型預設 Codex，除非 Codex 額度用盡才退 NotebookLM/self-renderer fallback。
- 注意 Codex 額度限制（曾於 reset Jul 11 前用盡）→ 額度耗盡時退自寫 matplotlib renderer 或 NotebookLM。
關聯 [[reference_notebooklm_rag_workflow.md]]、[[feedback_lazypack_infographic.md]]、[[project_reader_preference_feedback_loop.md]]。
