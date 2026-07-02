---
name: Gemini CLI 可分攤 Claude/Codex 任務量
description: 用戶 2026-05-02 指示 gemini-cli 額度可用後自主分配任務 + 寫入指示文件。已驗證 cross-model second-opinion review 對 production article 有 25-40% real-bug catch rate
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
當 gemini-cli 有額度時主動分攤輕量任務，不要全壓 Claude/Codex。

**Why**：用戶 2026-05-02 14:50 CST 主動詢問「gemini-cli 有額度可用了嗎？可分攤任務了嗎？」並隨後指示「你自己分配任務 但要把 gemini-cli 的使用寫入相關指示文件」。Session 內驗證 8 篇 article gemini-2.5-pro second-opinion review，3 個 NEEDS_FIX 中 2 個是真 bug（K518 21/27 年 + 數學錯、FOMC SPY/SPX 7,135.95 點位錯）→ patched。Cross-model review catch 主線 + agent loop blind spot 高 ROI。

**How to apply**：
- Gemini-cli 額度健康時，每篇 production article 或大檔輸出可走一次 `cat <file> | gemini -m gemini-2.5-pro -p "<prompt>"` 二審
- Prompt 必含 `today is YYYY-MM-DD` 降 date-cutoff false positive（gemini-2.5-pro cutoff ~2026-01）
- NEEDS_FIX verdict 必由主線 cross-check 真假 bug — 不可盲信 → patch
- Article-writing agent brief 可 embed self-review step（agent 自己跑 gemini review 後再 finish），減少主線 round-trip
- 規則文件已寫入 `.claude/rules/agent-delegation.md` Gemini CLI 章節（含 calibration caveat）
- 知識庫累積 hit-rate tracking entry `gemini_cli_cross_model_review_pattern_2026_05_02`

**禁忌**：
- 不要派 gemini 做 multi-step git/shell 流程（harness 限制）
- 不要把 secret pipe 進 gemini prompt
- 不要拿 gemini 做 embeddings（走 SDK，由 build_knowledge_index.py 負責）

---

**2026-07-01 memory-hygiene 更正（dreaming consolidation_review finding）**：`gemini-cli` 已於
2026-06-18 因 Google 停服棄用。此則的「額度分攤」cadence 概念**仍然有效**，但執行對象改變：
**繼任者是 `agy`（Antigravity CLI）** — 見 `feedback_gemini_cli_share_load` 精神延續到
`agy -p` headless 分攤輕量任務（second-opinion review / fact-check），`scripts/gemini_ask.py`
僅作 fallback（且每次呼叫是 paid API，需 email 通知 + log，不可比照 gemini-cli 免費額度心態濫用）。
新任務請依 CLAUDE.md「AI CLI 可用性」段 + user memory `reference_antigravity_cli` /
`reference_dual_cli_availability` 操作，不要照抄此則的 `gemini -m gemini-2.5-pro -p` 語法
（該 binary 已不存在）。
