---
name: trending-repost
description: |
  Use this skill when generating a VolPred-angle commentary on a currently
  trending high-traffic article (Taiwan or international) — re-analyze and
  rewrite with our volatility/risk/strategy lens, do NOT plagiarize, do NOT
  cite the source article. Output goes to volpred feed AND Ivan Lai's
  Facebook. Hard daily cap = 2 articles. Trigger phrases: '熱門改寫', '熱門
  分析', 'trending repost', 'trending rewrite', 'hot topic article'.
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

5. **Mandatory dual-publish**:
   - VolPred feed (via `feed-publisher` workflow, status=draft, audience=general)
   - Ivan Lai's Facebook (via claude-in-chrome browser automation — see § Facebook posting)
   - Failure to post FB does NOT block volpred publish, but log the failure
     to `storage/reports/trending_repost_log.json` for retry next cycle.

6. **Anti-collision dedup**:
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
- Headline contains 1+ of: AI / capex / vol / 市場 / 風險 / 配置 / 通膨 / Fed / GPU / 半導體 / FOMC / TSMC / 台積電 / Meta / Microsoft / Amazon / Alphabet / Nvidia / ETF / 對沖 / 黃金 / VIX
- Article published in past 7 days
- Has 1+ quantitative numbers (財報、margin、價格、波動率…)
- NOT same topic as past 30 days (dedup check)

Pick **1 candidate** per fire (cap = 2/day across fires).

### Step 2 — Independent fact gathering (30min budget)

For chosen topic, **independently** gather primary-source data:
- Company filings → SEC EDGAR (10-K/10-Q/8-K) or TWSE MOPS
- Market data → yfinance / FRED / TAIFEX
- Vol data → CBOE VIX / VIXTWN / RV series in our storage
- Cross-asset → our `experiments/` historical results

Build a numbers table. **Do not look at source article again** after
Step 1 to avoid framing contamination.

### Step 3 — VolPred angle synthesis

Choose 1 of:
- **Vol regime angle**: 「這事件對 X 資產 IV/RV 結構意味什麼」
- **Risk decomp angle**: 「以 K-experiment 經驗，這風險組成怎麼看」
- **Strategy angle**: 「用我們 active strategies 中哪個 VT/overlay 對應」
- **Methodology angle**: 「主流報導常忽略的 lookahead/timing/regime split」
- **Data angle**: 「primary source 真實數字 vs 媒體 narrative 偏離點」

This is the differentiator — not the same conclusion as source.

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
獨立查到的 primary source 數字 + 表格

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
2. **Gemini pro** 一審（headless: `gemini -m gemini-2.5-pro -p - -y --skip-trust 2>/dev/null <<EOF...EOF`）
   - Prompt: "Check for (a) plagiarism risk vs URL <source-url>, (b) tone/framing originality, (c) fact accuracy on numbers cited, (d) VolPred angle clearly differentiated. VERDICT/CRITICAL/MINOR."
3. **Codex** 二審（headless: `codex exec --skip-git-repo-check`）
   - Prompt: "Check for source-level issues: numerical accuracy via primary source verification, methodology claims valid, no implicit lookahead in any backtest reference. VERDICT/CRITICAL/MINOR."
4. **Pass criteria**: Gemini PASS on plagiarism + Codex PASS on numbers

### Step 6 — Publish to VolPred

```bash
uv run python scripts/publish_draft.py /tmp/trending_<slug>.md \
  --status draft \
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

**Primary path**: claude-in-chrome browser automation.
- Open https://facebook.com (assumes Ivan Lai logged in on the user's Chrome profile)
- Compose post: short hook (150 字) + link to VolPred article
- Capture post URL → update log

**MCP path (alt)**: If user runs `/mcp` and selects "claude.ai Facebook mcp",
real tool surface appears. **Note**: as of 2026-05-15, the MCP URL is
`mcp.facebook.com/ads` — may be Ads-API only, not personal wall posting.
claude-in-chrome browser automation is the more reliable path for personal
posting.

**Failure handling**:
- FB post failure → log `fb_post_status: "failed"`, set retry flag in log
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
