---
name: feedback_lazypack_infographic
description: 一般讀者文章文末必附懶人包圖組；NotebookLM 能生圖、多圖 poster、餵 evidence package 在寫文中生
metadata: 
  node_type: memory
  type: feedback
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

用戶 2026-06-04 三個糾正（建立 `lazypack-infographic` skill 的由來）：

1. **NotebookLM 能生 infographic**（我原本誤說不能,被糾正）：`notebooklm generate infographic` 直接出 .png,選項齊全(`--style professional|bento-grid|instructional|sketch-note|...`、`--orientation`、`--detail`、`--language zh_Hant`)。**不要再 dismiss NotebookLM 的生圖能力**。免費(網頁產品)、CLI 可 headless。

2. **餵 source 數據、寫文中生,不用 lossy prose**：「既然可以用 /notebooklm,應該在寫文章過程中就用所有寫文章的資訊去生圖,而不是等文章完成才用文章去生圖。」→ notebook 餵 evidence package(`<k>_results.json` + README + draft + refs),不是只餵成品文字。

3. **多圖 poster、不塞一張**：「類似研討會壁報,用多張圖、比較非技術的方式呈現不同型態資訊。不是只能一張,但也不要把所有不同類型資訊放同一張。」→ 一篇 2–4 張,概念/方法/結果各一張,一次生多張。

**硬約束**：生圖**不花錢** —— 只用 NotebookLM,**禁用**付費影像 API(`gpt-image-2` / 付費 Gemini key)。

**Why**：每篇一般讀者文章文末附懶人包圖組 → 提高可讀性/分享/觸及(Mission 第 1+5 條)。餵 source 數據才能把方法圖畫準、數字對得上 results.json(研究誠實)。

**How to apply**：寫一般讀者文章時走 `.claude/skills/lazypack-infographic/SKILL.md` + `scripts/gen_lazypack_infographic.py --experiment K... --plan plan.json --out-dir ...`。

相關：[[project_prepublish_content_gate]]、[[feedback_website_article_quality_4dim]]、[[feedback_use_anti_ai_style]]。
