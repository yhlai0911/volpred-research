---
name: 新增 trending_repost task type — VolPred 角度改寫熱門文章
description: 第 11 類任務 trending_repost；每日 ≤2 篇；雙發佈 VolPred feed + Ivan Lai FB；無 source citation 無抄襲；VolPred 角度（vol/risk/strategy/methodology/data）強制
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
**Rule**: 2026-05-15 用戶新增第 11 類任務 `trending_repost`：

1. **來源**：上網搜尋國內 / 國外近日熱門文章（高流量為主）— 國內如工商時報 / 經濟日報 / Inside / 財訊；國外如 WSJ / FT / Bloomberg / Substack finance（havingchien 等 genre reference）
2. **改寫紀律**：
   - **不抄襲**：不得 echo 原文用詞 / 段落 / 結構
   - **不引用**：不得 link 或 name 原文作者
   - **獨立查證**：所有數字必須 primary source（10-K / 10-Q / FRED / yfinance / TAIFEX）獨立查
3. **VolPred 角度強制**：每篇必須以下擇一 — vol regime / risk decomp / strategy implication / methodology pitfall / data narrative bias
4. **每日 ≤2 篇**（HARD CAP）— work_log task_type=`trending_repost` 當日 ≥2 → 派工 prompt 自動 skip 改 rotate
5. **雙發佈**：
   - VolPred feed（standard `publish_draft.py` workflow，status=draft，audience=general）
   - Ivan Lai FB（claude-in-chrome browser automation 主路徑；FB MCP `mcp.facebook.com/ads` 可能僅 Ads API 不適用個人 wall posting）
   - FB post 失敗不阻 volpred publish；log to `storage/reports/trending_repost_log.json` + 3 retry max
6. **3-model gate**：Claude 寫 → Gemini pro 一審（plagiarism + tone originality + fact accuracy + angle differentiation）→ Codex 二審（numerical accuracy via primary source + methodology valid）

**Why**:
- Mission Goal 1（文章寫好）+ Goal 5（曝光流量拉高）— trending topic SEO 槓桿最高
- 用戶 substack URL 範例（havingchien AI 6/13 — AI 四巨頭 CapEx 軍備競賽）= genre reference（財務深度分析 2,200 字，深專業 / 質疑共識，targeting 投資者）
- 不直接引用避免抄襲嫌疑 + 不引用避免幫對方導流

**How to apply**:
- Skill：`.claude/skills/trending-repost/SKILL.md`（完整 7-step SOP）
- 派工 prompt：`scripts/cron_hourly_dispatch_prompt.md` 已加入第 11 type + daily cap jq query
- 11-type pool 寫進 CLAUDE.md 「系統任務類型與派工」
- Log 檔：`storage/reports/trending_repost_log.json`（trending topic + primary sources used + FB post status + retry count）
- 30 日 dedup：同 topic 30 日內不重寫

**取代/補充**：補充第 10 類後新增的第 11 類；既有 10 類規則維持，trending_repost 是**唯一帶 daily cap** 的 type。

**FB posting infra**（2026-05-15 stand-up）：
- 主路徑：claude-in-chrome browser automation（用戶 Chrome profile 須已登入 Ivan Lai FB）
- MCP 路徑：用戶執行 `/mcp` 選 `claude.ai Facebook mcp` 才能 surface 真實 tools；URL `mcp.facebook.com/ads` 可能只支援 Ads API
- 推薦讓用戶確認用哪條路徑後再走第一篇文章
