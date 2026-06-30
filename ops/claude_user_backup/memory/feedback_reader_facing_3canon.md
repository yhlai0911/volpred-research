---
name: Reader-facing 文章必先讀 3 canonical（特別 trending_repost）
description: 任何 zh-Hant reader-facing 文章（特別 trending_repost）開工前必讀 3 個 canonical files；trending_repost 是正式 task type 非摘要；evidence package 先於 prose；發前必跑 anti-ai-style
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
**Rule**：任何 zh-Hant reader-facing 文章（feed-publisher / **trending_repost** / daily_article / event_article / member_qa 答覆 / FB hook）開工前，**必先讀 3 canonical files**：

1. **`.claude/skills/trending-repost/SKILL.md`** — 11 類 task type 規範、Substack/commentary 風格參考、雙發佈規則
2. **`.claude/skills/anti-ai-style/SKILL.md`** — 8 地雷 / 5 prompt 原則 / 3 階段編輯 SOP
3. **`.claude/rules/publishing.md`** — 選題 → 查重 → 寫作 → 發布的合併工作流規則

**Why**:
- 用戶 2026-05-16 明確指示：「之後凡是 reader-facing 文章，特別是 trending_repost，請先讀這三份 canonical」
- Skills 已建好但執行時容易遺忘 / 跳過 → 直接列 3 個 path 強制 binding
- trending_repost 第 1 篇 mile_ed39c127（2026-05-15）執行時跳過 evidence-package gate → 用戶不滿；現在 enforce evidence-first
- 防止寫成「摘要 / 翻譯 / 抄寫」— trending_repost 是**原創評論**，不是 source reformat

**Trending_repost 特別硬規則**（疊加在 3 canonical 之上）:
- **正式 task type**，不是摘要 / 翻譯 / 改寫
- 風格可參考 havingchien 類 Substack / commentary newsletter 的 tone / pacing / hook
- **不引用、不貼近改寫** source 原文（同 trending-repost SKILL.md 硬規則 2/3）
- 發文前 **必先完成**：(a) 選題掃描、(b) 30 日查重、(c) VolPred angle 確認
- **Evidence package 先於 prose**：在寫任何句子之前，先組好 numbers 表 + chart 候選 + 量化分析 lens

**VolPred 平台標準 evidence 套件**（reader-facing 文章皆 enforce）:
- 至少 **3 個可驗證數字**（primary source / public data）
- 至少 **1 表**（從上述數字組成）
- 至少 **1 圖**（基於實際數據）
- 至少 **1 層簡單量化分析**（descriptive stats / before-after / cross-section / rolling / event-window / vol change）
- 最好有統計檢定或明確比較框架

不滿足以上 → **不寫**（換題目或換 task type，禁強推）

**Anti-AI-style gate**:
- 所有 reader-facing draft 必跑 `.claude/skills/anti-ai-style/`
- 寫前讀 prompt-templates（5 原則套 prompt header）
- 寫後跑 editor-sop 3 階段 9-checklist；任一 fail 不 publish
- 3-model gate 之 Gemini 一審 prompt 加問「是否仍有 AI 味」
- **只要還有 AI 味、翻譯腔、模板腔、空泛評論 → 不得發布**（用戶 2026-05-16 補強，無 partial pass；3 輪改寫仍 fail → 該主題 abandon）

**Trending_repost VolPred 發佈規則**（2026-05-16 補強）:
- VolPred 上**直接 published**（不進 draft pool）— 與其他 task type 預設 draft 不同
- 每日 cap **2 篇**（per `feedback_trending_repost_route`）
- 唯一帶 daily cap 的 type

**FB 發佈規則**（同步發 Ivan Lai FB，完整 SOP `.claude/skills/trending-repost/references/fb-ivanlai-tone.md`）:
- FB 文案是**改寫版** — 不可直接貼 VolPred 內文（重新組 200-400 字短文）
- **主貼文不放連結**（FB 演算法對外連結 reach 大幅打折）
- **VolPred 連結放第一則留言**（自己 reply）
- Ivan Lai 舊文口吻：先個人觀察 → 短句短段 → 留白 → 不把論證一次講滿 → 不寫制式財經摘要
- 額外禁用詞：「綜上所述」/「值得關注」/「在 AI 時代」/「根據資料顯示」/「投資人應該…」
- claude-in-chrome 輸入中文**整段貼上**不要逐字 type；貼後 screenshot 檢查再送出
- FB post 失敗不阻 VolPred publish；log `storage/reports/trending_repost_log.json` retry max 3

**How to apply**:
- 派 reader-facing agent（feed-publisher / trending-repost / daily_article 等）brief **必含** 3 canonical paths + 上述 evidence + anti-ai 要求明文
- 主線程自己寫 reader-facing 內容也同樣 enforce
- Dispatch prompt 第 6 條已更新（commit 22cab40e+；本 entry 後續再加 3 canonical 明列）
- 違反任一 → 該 fire 視為未完成（per 完整完成 hard rule）

**例外（不適用）**：
- Code / commit msg / work_log / m.think / log message（非 reader-facing）
- 論文 `.tex`（走 finance-paper-quality + latex-academic-reviewer 流程，evidence bar 更高但 8 地雷豁免 1+8）
