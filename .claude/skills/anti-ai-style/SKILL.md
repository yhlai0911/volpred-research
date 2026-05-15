---
name: anti-ai-style
description: |
  Use this skill whenever drafting reader-facing text in zh-Hant (feed
  articles, trending_repost, daily_article, member_qa answers, paper
  abstracts, social-media hooks) to eliminate generic "AI 味" — the
  hollow, formulaic, translation-stilted phrasing that makes readers
  bounce. Enforces an 8-landmine avoidance catalog, a 5-rule prompt
  protocol, and a 3-stage editor SOP grounded in 5 expert sources
  (Wu Dan-Ru 50-year writer's framework + 4 prompt-engineering guides).
  Trigger phrases: '避免 AI 味', '人味', '人話', 'avoid AI style',
  'humanize AI text', '去 AI 腔', 'AI 文案優化', '檢查 AI 風格'.
  Do NOT use for: code/log/error messages, internal memory notes
  (m.think), or pure data tables.
paths:
  # Writing stage — when an AI draft is being authored
  - "storage/reports/*.md"
  - "storage/next_draft_candidate_*.md"
  - "paper/**/*.tex"
  - "paper/**/*.md"
  # Skill-self trigger
  - ".claude/skills/anti-ai-style/**"
  # Pre-publish audit path
  - "scripts/publish_draft.py"
  - "src/volpred/publisher/publisher.py"
  # Co-trigger paths (when these skills run, anti-ai-style should also load)
  - ".claude/skills/feed-publisher/**"
  - ".claude/skills/trending-repost/**"
---

# Anti-AI-Style Skill

讓 zh-Hant 文章脫掉「AI 味」— 空洞、套路、翻譯腔、做作昇華的文字病。
本 skill 強制三道防線：寫前 prompt 設計、寫中即時自檢、寫後編輯 SOP。

## 為什麼這個 skill 存在

平台讀者面對的最大威脅不是事實錯誤，是**「讀起來像 AI」的觀感**。一旦讀者
察覺，回訪率、分享率、付費轉換全垮 — 直接打擊 Mission Goal 1（文章寫好）
與 Goal 5（曝光流量拉高）。AI 味與「研究誠實」是並列重要的內容品質維度，
任一不過關都不該 publish。

---

## 三層防線速查（先讀這段，細節在 references/）

### Layer 1 — 8 大地雷 catalog（寫前先記、寫後必檢）

| # | 地雷 | 一句症狀 |
|---|---|---|
| 1 | **「不是…而是…」假哲理** | 強行對立不對等概念 |
| 2 | **無效換句話說** | 6 句講完 2 句的事 |
| 3 | **標籤式情緒** | 直接寫「讓人感到心酸」 |
| 4 | **爆米花式昇華** | 小事擴張成宇宙大道理 |
| 5 | **生硬戲劇轉折** | 「然而，真正的考驗才正要開始」 |
| 6 | **稻草人「有人說」** | 捏造假想敵且無查證 |
| 7 | **翻譯腔「這」** | 「這讓人不禁感到…」 |
| 8 | **吊書袋空詞** | 「結構性梳理」等 |

完整症狀／根因／修正 → [references/8-landmines.md](references/8-landmines.md)

### Layer 2 — 5 大 prompt 原則（寫前下指令時用）

1. **年齡降級**：「以國二學生口吻」強制 AI 放棄官腔
2. **長文裁切法**：先寫 800-1000 字再人工裁到 300-400 字
3. **資訊密度**：每句必含新資訊，禁迴圈
4. **負向約束**：明列禁用句式（「不是…而是」/「有人說」/「這讓人」）
5. **蘇格拉底對槓**：用 Gemini 反問出處，戳事實幻覺

完整模板與情境 → [references/prompt-templates.md](references/prompt-templates.md)

### Layer 3 — 3 階段編輯 SOP（寫後必跑）

- **階段一 邏輯與結構初審**：拆假骨架（檢「不是…而是」/ 爆米花 / 稻草人）
- **階段二 資訊密度與語法去油膩**：修壞肉（新資訊測試 / 拔轉折詞 / 清翻譯腔）
- **階段三 事實查核與情感注入**：注入靈魂（跨模型查證 / 情緒→畫面 / 留白）

完整 checklist 9 項 → [references/editor-sop.md](references/editor-sop.md)

---

## 標準執行流程

### 寫新文章（feed-publisher / trending-repost / daily_article 都適用）

```
1. 讀 references/prompt-templates.md，套 5 原則組 prompt
   ↓
2. 跑 AI 生成 → 拿到 first draft
   ↓
3. 開 references/bad-vs-good.md 對照 8 地雷自查
   ↓
4. 跑 references/editor-sop.md 三階段（每段勾完才 publish）
   ↓
5. 三模 review 額外加 anti-ai-style gate：
   Gemini prompt 加問：「是否仍有 AI 味？指出最像 AI 的 3 句並建議改寫。」
```

### 改稿 / 審稿（trending_repost 改寫熱門文）

```
1. 先用 sources 獨立查證數字 → 不引原文
   ↓
2. 草稿完成 → 直接跳到 editor-sop 階段一
   ↓
3. 通過後再做 trending-repost 的 3-model gate
```

---

## 硬規則（不可違反）

1. **8 地雷任一未消除 → 不 publish**（即使其他品質維度全 PASS）
2. **情緒命名禁直白**：禁「讓人感到」「心酸」「孤獨」「拋棄」「不禁」直接出現
   — 改畫面 / 動作 / 意象
3. **轉折詞配額**：每篇 ≤2 個「然而」/「真正的」/「但其實」/「事實上」
4. **「這」字密度**：每 200 字 ≤3 個（用具體主詞替代）
5. **每句必有新資訊**：editor-sop 階段二必跑逐句測試
6. **不靠 AI 自審**：editor-sop 必由人類或 cross-model（非同一 LLM）執行

---

## 與其他 skill 的協作邊界

| 你正在做… | 主要 skill | 本 skill 角色 |
|---|---|---|
| 寫 feed 文章 | `feed-publisher` | 寫前 prompt 設計 + 寫後 SOP 必跑 |
| 改寫熱門文 | `trending-repost` | 同上，且 3-model gate 加 anti-AI 問項 |
| 會員問答 | `member-questions` | 答覆 draft 完成後 SOP 階段二必跑 |
| 寫論文 | `latex-academic-reviewer` | 論文用學術腔可豁免地雷 1/4/8；地雷 2/3/5/6/7 仍 enforce |
| 寫 commit / log | （無）| 本 skill **不適用** |

---

## Failure modes 與救援

- **「我覺得已經 OK 了」幻覺**：要求自己用 Gemini 跑 anti-AI 問項 cross-check
  — 自己看不出來的 AI 味，跨模型看得出來
- **改太多失去原意**：editor-sop 階段三第 3 項「人味與溫度」保留個人觀點，
  非機械化清詞 — 寧可留 1 個地雷也要保人類獨特角度
- **時間壓力跳 SOP**：禁；改用快版 — 至少跑階段一邏輯初審（3 個 check
  項），階段二/三排到下次 update_history

---

## 5 個 sources（NotebookLM notebook `20291e44-e14a-4dbc-9df1-ff4d252f581d`）

詳細引用 → [references/sources.md](references/sources.md)

1. AI 生成文案專業品質控管與編輯審核準則（Google Docs）
2. 專業文案生成策略建議書：從避雷到升華的 AI 協作指南（Google Docs）
3. 拒絕「AI 味」：提升文字生命力的寫作邏輯大揭密（Google Docs）
4. 提示詞優化手冊：讓你的 AI 報告更有「人味」（Google Docs）
5. 🚩 吳淡如 EP5 — AI 寫文的 8 個地雷（YouTube `eIeqTmCM9Vo`，50 年寫作經驗）
