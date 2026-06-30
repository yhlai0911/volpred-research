---
name: reference_knowledge_wiki_and_context_economy
description: Karpathy LLM-Wiki 編譯式知識庫 + context 經濟（CLAUDE.md 精簡=每 token 每回合付費）優化原則
metadata: 
  node_type: memory
  type: reference
  originSessionId: 84ae09c8-9673-48d4-b7bc-6113766e22dc
---

2026-06-30 用戶要求：用 Karpathy「LLM Wiki」概念優化記憶/知識庫 + 重視 context window 成本。

**Karpathy LLM-Wiki pattern（2026-04）**：不用 RAG 撈 raw docs，而是 LLM 增量建**結構化互連 markdown wiki**——concept pages / entity pages / source summaries / 矛盾追蹤 / cross-references。架構三層：`raw/`(immutable 原始) + `wiki/`(LLM 合成的概念頁) + `CLAUDE.md`(schema)。**先編譯知識**（合成成互連概念頁）再 query 編譯後 artifact → 知識複利累積、不重撈。

**對 VolPred 的 Act（未來專案，非本 session 立即做）**：
- knowledge.json(2402 K) 是扁平 raw 清單 = Karpathy 的 raw/ 層，缺 wiki/ 概念層。
- 優化 = 把同主題 K 編譯成**互連概念頁**（VIX-sufficient-statistic / VT-策略 / HAR-vol-forecast / 外生衝擊-vol 等），每頁：合成的 consolidated 結論 + 矛盾(NULL vs PASS) + cross-ref [[K-ids]] + 待答。LanceDB(`scripts/build_knowledge_index.py`) 已做 retrieval；概念-wiki 加「編譯後 single-source 結論」層。
- memory 系統已內建 Zettelkasten（一檔一事實 atomic + `[[name]]` link + MEMORY.md index + type schema）——已接近 Karpathy wiki，缺的是定期 dreaming 整併(detect_memory_governance)。

**Context 經濟（硬紀律）**：CLAUDE.md / 系統提示 / 永遠載入的內容，**每個 token 每回合都重複付費** → session 越長、always-loaded 越大，後面每題 token 成本越高。所以：
1. CLAUDE.md = **精簡 schema + 一句話 mnemonic + 指向 skill 的指標**，細節一律進 on-demand skill（progressive disclosure，觸發才載）。禁把 SOP/長清單塞 CLAUDE.md。
2. skill 本身也 progressive disclosure：SKILL.md 當目錄，細節拆 `references/*.md`。
3. 大檔禁整檔 Read（jq/grep 投影），大 side task 派 subagent 隔離（見 `.claude/rules/context-hygiene.md`）。
4. session 過長要主動 /compact 或收斂；durable 結論落檔（memory/skill/docs）讓下個 session 從精簡狀態起跑，不靠長對話串。

關聯：[[feedback_proactive_result_level_operation]]、[[feedback_progressive_disclosure]]、`.claude/rules/context-hygiene.md`、`.claude/skills/pdca-operations`（學理+實操根據 + 記憶整理 grounded 方法）。
