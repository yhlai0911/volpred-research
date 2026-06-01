---
name: trending-repost
description: |
  Use this skill when generating a VolPred-angle commentary on a currently
  trending high-traffic article (Taiwan or international) — re-analyze and
  rewrite with our volatility/risk/strategy lens, do NOT plagiarize, do NOT
  cite the source article. Default genre reference is the havingchien-style
  Substack column format discussed on 2026-05-15: commentary/newsletter tone,
  strong point of view, primary-source reconstruction, no source citation,
  no line-level borrowing. Output goes to volpred feed AND Ivan Lai's
  Facebook. Hard daily cap = 2 articles. Trigger phrases: '熱門改寫', '熱門
  分析', 'trending repost', 'trending rewrite', 'hot topic article',
  'Substack 風格', '專欄文'.
  Do NOT use for: K-experiment-driven articles (use feed-publisher),
  member Q&A (use member-questions), event-driven posts citing actual
  data releases (use daily_article workflow with proper citation).
paths:
  - "storage/reports/feed.json"
  - "storage/reports/trending_repost_log.json"
  - ".claude/skills/trending-repost/**"
---

# Trending Repost Skill

## Purpose

Convert high-traffic trending articles (financial / tech / market) into
**VolPred-angle commentary** — same topic, our lens, no source citation,
no copy-paste. Adds **task_type = `trending_repost`** as the 11th type
in the work_log diversity pool.

## Canonical Style Reference

Default style reference for this task type:
- **Genre model**: havingchien-style Substack column / newsletter article
- **What to imitate**: pacing, topical hook, clear point of view, essay-like
  structure, reader-facing commentary voice
- **What NOT to imitate**: wording, metaphors, sentence order, section order,
  or any distinctive phrasing from the source piece
- **Non-negotiable**: rebuild the argument from **primary sources + VolPred
  analysis**, not from the source article's text

If user says "照那篇風格寫" and context points to the 2026-05-15 directive,
this skill should interpret it as:
- Substack-style column tone
- independent reconstruction
- dual-publish to **VolPred + Ivan Lai Facebook**

## Mission Linkage

- **Goal 1 (文章寫好)**: trending topics drive organic traffic + share rate (M5 漏斗入口)
- **Goal 5 (曝光流量拉高)**: trending search terms are the highest SEO leverage we can capture
- **Monetization angle**: trending posts → high visit → conversion funnel widened
- **Trade-off**: lower research depth than K-driven articles, but compensated by traffic volume + breadth

## Hard Rules

1. **Daily cap = 2 articles**. Check before dispatch:
   ```bash
   jq --arg today "$(date '+%Y-%m-%d')" \
      '[.[] | select(.task_type == "trending_repost" and (.timestamp // "")[0:10] == $today)] | length' \
      storage/work_log.json
   ```
   Result ≥ 2 → skip, pick another task_type.

2. **No plagiarism**:
   - **Never** copy a sentence or paragraph from source — even reordered words.
   - Numbers used must be **independently verifiable** from primary sources
     (company 10-K, FRED, yfinance, TAIFEX, etc.), not from the trending article.
   - Different framing, different structure, different conclusion (or same
     conclusion via different reasoning path).

3. **No source citation**:
   - Do NOT link or name the trending article.
   - Do NOT use the source author's phrasing or framing.
   - If a fact needs attribution, cite the **primary source** (e.g., Meta 10-Q
     Q1 2026, not "according to havingchien").

4. **VolPred lens required** — every article must connect to:
   - Volatility (realized / implied / regime / cross-asset spillover), OR
   - Risk management (drawdown / VaR / hedging / correlation breakdown), OR
   - Strategy implication (VT / overlay / pair / sector rotation), OR
   - Data methodology (timing / lookahead / cross-validation pitfalls)

5. **Platform-grade evidence required**:
   - A trending_repost is **not** a pure opinion column. It must satisfy the
     VolPred platform standard: claims need real evidence, numbers need source
     traceability, and the core thesis should be supported by data rather than
     rhetoric.
   - Minimum evidence package:
     - 3+ independently verifiable quantitative facts from primary/public data
     - 1+ table built from those facts
     - 1+ chart based on actual data
     - 1+ simple analytical layer beyond narration, chosen from:
       descriptive statistics / before-after comparison / cross-sectional
       comparison / rolling comparison / event-window move / volatility change
   - If the topic cannot support this evidence package, **do not write it as
     trending_repost**. Pick another topic or another task type.

6. **Mandatory anti-AI-style gate**:
   - All reader-facing drafts under this skill must co-run
     `.claude/skills/anti-ai-style/SKILL.md`.
   - Drafting must follow the anti-ai-style prompt constraints, and pre-publish
     review must run the anti-ai-style editor SOP.
   - **只要還有 AI 味、翻譯腔、模板腔、空泛評論 → 不得發布**（user directive
     2026-05-16 補強 — 一條 fail 全 fail，沒有 partial pass）
   - 改寫直到 anti-ai-style gate 全 PASS 為止；若 3 輪改寫仍 fail → 該主題 abandon

7. **Mandatory dual-publish**:
   - VolPred feed (via `feed-publisher` workflow, **status=published** —
     直接 publish 不進 draft pool，per user directive 2026-05-16)
   - Ivan Lai's Facebook personal account/page surface (via claude-in-chrome
     browser automation — see § Facebook posting + [references/fb-ivanlai-tone.md](references/fb-ivanlai-tone.md))
   - Failure to post FB does NOT block volpred publish, but log the failure
     to `storage/reports/trending_repost_log.json` for retry next cycle.

   **FB 貼文硬規則**（完整 SOP 在 references/fb-ivanlai-tone.md）：
   - FB 文案是 **改寫版** — 不可直接貼 VolPred 內文（重新組短文 200-400 字）
   - **主貼文不放連結** — 主 body 純文字 + 可選 1 張圖
   - **VolPred 連結放第一則留言**（自己 reply）
   - Ivan Lai 舊文口吻：先個人觀察 → 短句短段 → 留白 → 不把論證一次講滿 → 不寫制式財經摘要
   - claude-in-chrome 輸入中文 **整段貼上**不要逐字 type；貼後先 screenshot 檢查再送出

8. **Anti-collision dedup**:
   - Check `storage/reports/trending_repost_log.json` for past 30 days —
     same trending topic in past 30 days = skip.

## Workflow

### Step 1 — Source scan (15min budget)

Web search across high-traffic surfaces. Daily rotation suggestion:

| Day pattern | Surfaces |
|---|---|
| Odd days | International: WSJ / FT / Bloomberg / The Information / Substack finance (havingchien, stratechery, etc.) |
| Even days | Taiwan: 工商時報、經濟日報、財訊、Inside、財報狗、自由財經、Yahoo TW、SCMP |

Filter criteria:
- Headline contains 1+ of: AI / AI 發展 / token maxxing / tokenmaxx / inference cost / capex / vol / 市場 / 風險 / 配置 / 通膨 / Fed / GPU / 半導體 / FOMC / TSMC / 台積電 / Meta / Microsoft / Amazon / Alphabet / Nvidia / 矽谷裁員 / layoffs / tech layoffs / labor displacement / agent / agentic AI / Anthropic / OpenAI / Claude / GPT / Gemini / model routing / ETF / 對沖 / 黃金 / VIX
- Article published in past 7 days
- Has 1+ quantitative numbers (財報、margin、價格、波動率、headcount、token cost…)
- NOT same topic as past 30 days (dedup check)
- **High-viral keywords priority**（per 用戶 2026-05-26 feedback — share rate / monetization 漏斗入口優先）：
  - **AI 發展** (model release、capability jump、enterprise adoption)
  - **token maxxing / inference economics** (Anthropic / OpenAI / Google pricing wars、cost-per-task crossover)
  - **矽谷裁員 / tech layoffs** (Meta / Microsoft / Google / Amazon 大規模裁員 + AI 替代 narrative)
  - 這 3 類比 niche topics (specific ETF/macro release) viral 高 2-5x，主線程 source scan 應**優先掃這 3 類**

Pick **1 candidate** per fire (cap = 2/day across fires).

### Step 2 — Independent fact gathering (30min budget)

For chosen topic, **independently** gather primary-source data:
- Company filings → SEC EDGAR (10-K/10-Q/8-K) or TWSE MOPS
- Market data → yfinance / FRED / TAIFEX
- Vol data → CBOE VIX / VIXTWN / RV series in our storage
- Cross-asset → our `experiments/` historical results

Build a numbers table. **Do not look at source article again** after
Step 1 to avoid framing contamination.

### Step 2.5 — Evidence package assembly

Before any prose drafting, assemble a compact evidence package:
- primary-source numbers table
- at least 1 chart candidate
- the exact analytical lens you will compute
  - e.g. "Mag 7 capex YoY + capex/revenue ratio"
  - e.g. "event-window return + 20d realized vol before/after"
  - e.g. "sector cross-section valuation / drawdown / correlation comparison"
- the key claim each number is meant to support

If you cannot answer "which claim is this number supporting?", the draft is
too narrative-heavy and not ready.

### Step 3 — VolPred angle synthesis

Choose 1 of:
- **Vol regime angle**: 「這事件對 X 資產 IV/RV 結構意味什麼」
- **Risk decomp angle**: 「以 K-experiment 經驗，這風險組成怎麼看」
- **Strategy angle**: 「用我們 active strategies 中哪個 VT/overlay 對應」
- **Methodology angle**: 「主流報導常忽略的 lookahead/timing/regime split」
- **Data angle**: 「primary source 真實數字 vs 媒體 narrative 偏離點」

This is the differentiator — not the same conclusion as source.

### Step 3.5 — Style enforcement

Before drafting, lock these writing constraints:
- Open with a live issue / tension / market implication, not a research abstract
- Write like a column, not a lab note or experiment README
- Use short-to-medium paragraphs with explicit narrative movement
- Make the "so what" visible throughout, not only in the conclusion
- Keep a confident viewpoint, but every number must still trace to a primary source
- If the article starts sounding like `daily_article` summary prose, rewrite the opening and section transitions

### Step 4 — Draft (1,500-2,500 words)

Markdown structure template:
```markdown
---
title: "<your headline, NOT source's>"
audience: general
tags: [trending, <topic-tags>]
experiment_refs: []  # leave empty unless tied to specific K
description: "<200-char SEO snippet>"
---

## 開場（200 字）
觀察到的市場現象 + 為什麼這值得關注（不提媒體報導）

## 主要數據（500 字 + 1-2 表）
獨立查到的 primary source 數字 + 表格 + 至少一層簡單分析

## VolPred 角度分析（800-1,200 字）
- 與我們研究的連結（K 編號 / 文獻 / 策略）
- 主流敘事的盲點（lookahead / timing / regime / data）
- 量化推論

## 結論與啟示（300 字）
給讀者帶走的 1-2 個 actionable takeaway
```

### Step 5 — Quality gates (3-model)

Per `feedback_3model_review_discipline`:
1. **Claude** 寫
2. **Gemini pro** 一審（headless 首選 **agy 訂閱免費路徑**: `PROMPT=$(cat <<'EOF' ... EOF); agy -p "$PROMPT"`；**禁用** `scripts/gemini_ask.py`（會打 PAID API 觸發 email alert），僅 agy 不可用時才 fallback）
   - Prompt: "Check for (a) plagiarism risk vs URL <source-url>, (b) tone/framing originality, (c) fact accuracy on numbers cited, (d) VolPred angle clearly differentiated, (e) whether the prose still has AI-style landmines. VERDICT/CRITICAL/MINOR."
3. **Codex** 二審（headless: `codex exec --skip-git-repo-check`）
   - Prompt: "Check for source-level issues: numerical accuracy via primary source verification, methodology claims valid, no implicit lookahead in any backtest reference, and whether the article has enough evidence/statistical support for VolPred platform standards. VERDICT/CRITICAL/MINOR."
4. **Anti-AI editor gate**: run `.claude/skills/anti-ai-style/SKILL.md` editor SOP before publish
5. **Pass criteria**:
   - Gemini PASS on plagiarism + anti-AI-style
   - Codex PASS on numbers / methodology / evidence sufficiency
   - anti-ai-style SOP completed with no unresolved major landmines

### Step 6 — Publish to VolPred

```bash
uv run python scripts/publish_draft.py /tmp/trending_<slug>.md \
  --status published \
  --audience general
```

Log to `storage/reports/trending_repost_log.json`:
```json
{
  "date": "2026-05-15",
  "trending_topic": "AI capex Q1 2026",
  "source_surface": "havingchien.substack.com",
  "primary_sources_used": ["Meta 10-Q", "Microsoft 10-Q", "Alphabet 10-K"],
  "volpred_angle": "vol regime",
  "mile_id": "mile_xxxxxxxx",
  "fb_post_status": "pending|success|failed",
  "fb_post_url": null,
  "word_count": 1850
}
```

### Step 7 — Facebook post (Ivan Lai)

> **⚠️ FB 發文實戰教訓（2026-05-20 多次踩雷後寫入，違反任一條就重蹈覆轍）**
>
> 1. **發文前必先 `get_page_text` 查 Ivan Lai 牆**確認該篇沒發過。pfbid scan
>    在 FB profile cache lag 下會 false-negative（dda1e670/50f44a46/74a28bcf
>    三次誤判「沒發成功」其實都發了）。只信 get_page_text 看到的牆。沒查就開
>    composer = 重複發文風險。
> 2. **留言 URL 要打進「留言框」不是「貼文本體」**。2026-05-20 把 URL 誤打進
>    composer 本體兩次。每次 type 前先 `find` 確認 ref 是留言 textbox
>    （aria-label 含「以 Ivan Lai 的身分留言」），不是 composer 本體。
> 3. **FB profile inline composer 有草稿復原機制** — 關掉 composer dialog 後
>    文字回到 profile 頂端 inline composer 框；再點它會重開 dialog 帶舊草稿。
>    這不是 dup，是同一篇未發佈草稿。別誤判、別關掉真草稿。
> 4. **主貼文本體絕不放 URL**。若不慎打入 → `cmd+a` → `Delete` → 重打乾淨版
>    → 移除 FB 自動生成的連結預覽卡（卡片右上 X）。
> 5. **留言送出**：先試獨立 send 鍵（留言框右下藍色紙飛機 / `貼文留言` button）。
>    但 **2026-05-31 實測：FB 個人檔案 inline composer 的 send button 用 ref-click
>    點兩次都沒送出**，改在已聚焦的留言框按 **Return** 才成功送出（且送出後 box 清空、
>    留言出現在列表 = 可驗證）。所以 send-button 無效時 **fallback = Return**，不要
>    連點 send button。送出後一律 `find` 確認「留言框已清空」+「留言已出現在 list」。
> 6. **每個關鍵步驟後 screenshot 確認**（composer 開了沒 / 發佈成功沒 /
>    留言送出沒），不靠 find 描述猜狀態。
> 7. **single-shot，禁 retry-loop**。發佈鍵點一次後等 6-8s + screenshot 驗，
>    沒成功查原因，不連點 — retry-loop 2026-05-19 造成 3 篇 Nikkei dup。
> 8. 發佈流程：composer → 確認本體乾淨 → `繼續` → `貼文設定`頁點藍色`發佈`
>    （不是`排程選項` row）→ 等 → screenshot 驗 composer 關閉 + 牆上「剛剛」。
> 9. **【硬規則 2026-05-31，違反 = 留言連結必漏】禁用 FB 原生「排程選項」發
>    trending / event 貼文。** 根因：FB 排程只能排貼文本體，**不能排第一則
>    留言**。一旦用排程，貼文到時自動發出，但「連結放第一則留言」要事後手動
>    回 Chrome 補 —— 貼文與留言被拆成兩個時間點，那個事後補留言步驟反覆漏掉
>    （K1408/K1409 2026-05-31 incident：兩篇排程貼文發出但留言無連結，老闆抓到）。
>    **貼文與留言必須是同一個 Chrome session 的原子操作**：發佈貼文 → 立刻在
>    同一 session 補第一則留言 → screenshot 驗留言已送出 → patch feed.json
>    `fb_post_status=success`。若老闆要求特定時段發佈，**由主線程
>    `ScheduleWakeup` 在目標時段醒來，再一次性做完「發佈+留言」**，不靠 FB
>    自己的排程器。發佈與留言之間**不可有時間落差**。

**Primary path**: claude-in-chrome browser automation.
- Open https://facebook.com (assumes Ivan Lai logged in on the user's Chrome profile)
- **Do not paste the VolPred article verbatim into Facebook.**
- Rewrite into a **Facebook-native post**:
  - shorter opening hook
  - faster payoff in first 2-3 lines
  - shorter paragraphs
  - clearer social / conversational rhythm
  - still same core thesis, but adapted for FB reading behavior
- **Do not place the VolPred link inside the main FB post body**
- After the FB post is published, add the **VolPred original article link in the first comment**
  - **URL hard rule**：FB 第一則留言連結**只能**用 `https://volpred.zeabur.app/v3/reports/<mile_id>`。**禁止**用 `/article/<mile_id>`（404，2026-05-19 incident）。發文前必 `curl -I` 驗 HTTP 200，並寫入 `fb_comment_link` 欄位（log schema）。
- Before posting, rewrite against the **Ivan Lai FB style spec** below, not just
  against generic "social media best practices"
- Recommended structure:

#### Ivan Lai FB style spec

Derived from sampled pre-2022 posts on 2026-05-15.

- Write the FB post as a **personal observation first**, not as a site summary
- Prefer **short sentences** and **short paragraphs**
- Lead with **one judgment / one feeling / one tension**, then let the article
  carry the full evidence
- Allow **measured留白**; do not explain every implication inside the FB body
- Accept occasional **image-like / lyrical phrasing** when natural, but avoid
  purple prose or forced metaphors
- Do **not** front-load too many numbers in the main post; keep only the 1-2
  most decision-relevant figures
- The FB body should feel like "我看到一件事，我的切入角度是這個", not
  "以下是完整分析摘要"
- External article / VolPred link belongs in the **first comment**, not the body
- If the copy reads like an analyst memo, newsletter abstract, or SEO snippet,
  it fails the Ivan Lai FB style gate and must be rewritten

#### FB rewrite checklist

- First 1-2 lines can stand alone as a hook
- No dense bullet-list compression from the VolPred article
- No forced "結論是"/"換句話說"/"這代表什麼" cadence unless truly natural
- No obligation to restate all evidence already in the site article
- Keep the core thesis intact, but let the FB version sound more like a person
  posting than a publication exporting copy
  - 1 hook
  - 2-4 short paragraphs of rewritten commentary
  - 1 explicit takeaway / question
- Default target is **Ivan Lai** FB surface per 2026-05-15 user directive; do
  not treat FB posting as optional housekeeping
- Capture post URL → add first comment with VolPred link → update log

**MCP path (alt)**: If user runs `/mcp` and selects "claude.ai Facebook mcp",
real tool surface appears. **Note**: as of 2026-05-15, the MCP URL is
`mcp.facebook.com/ads` — may be Ads-API only, not personal wall posting.
claude-in-chrome browser automation is the more reliable path for personal
posting.

**Failure handling**:
- FB post failure → log `fb_post_status: "failed"`, set retry flag in log
- FB comment-link failure → keep `fb_post_status` separate from comment-link status in log if needed; retry comment before treating cycle complete
- VolPred article publish is independent — don't roll back if FB fails
- Next trending_repost fire checks log for pending FB retries before
  generating new content (max 3 retries before giving up)

## Daily Cap Enforcement (in dispatch prompt)

The hourly dispatch prompt must check trending_repost daily count BEFORE
picking task. Implementation in `cron_hourly_dispatch_prompt.md`:

```
若 today's trending_repost count ≥ 2 → 禁挑 trending_repost type，rotate
其他 type。
```

## Task Type Pool — Now 11 Types

Updated pool (added trending_repost as #11):
1. experiment
2. paper_decision
3. paper_body
4. paper_review
5. event_article
6. daily_article
7. member_qa
8. strategy_lifecycle
9. platform_ops
10. governance
11. **trending_repost** (NEW, daily cap = 2)

Diversity rule unchanged: last-3 work_log task_type 不含的 type 優先派。

## Failure modes to watch

- **Plagiarism slip**: 連續寫到一半發現自己 echo source 用詞 → 重寫該段，並
  增加 dedup check 在 prompt
- **No VolPred angle**: 寫成純市場評論 → reject, 必須回 K-experiment / 策略
  /方法論其中之一
- **FB post fail**: claude-in-chrome session 沒登入或 Chrome 沒開 → log
  failure，提示用戶開 Chrome；不重試超過 3 次
- **Daily cap miscount**: 應用 work_log timestamp 的 local-date 不是 UTC，
  cap 是 local CST 算
- **FB copy too similar to site article**: reject and rewrite for Facebook-native cadence
