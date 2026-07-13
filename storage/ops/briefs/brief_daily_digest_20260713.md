# Brief — daily_digest_20260713（每日精選導讀專題策展）

**Model**: opus / medium (per task_type routing)
**Task id**: `daily_digest_20260713`（已 claim + start，owner=hourly-10）
**Task type**: daily_digest（1/day fixture，今天尚未發 → 必須今天發出）
**你是唯一會寫 feed.json 的 agent**（另一個 writer 只寫 draft 檔，不碰 feed）→ 你可以直接 publish。

## 開工前必讀（3 canonical，不可跳過）

1. `.claude/skills/trending-repost/SKILL.md`（dual-publish + style 規範通用）
2. `.claude/skills/anti-ai-style/SKILL.md`
3. `.claude/rules/publishing.md`

另讀 `.claude/skills/feed-publisher/SKILL.md` 的 daily_digest 段。

## 這是什麼（規格，`.claude/rules/task-routing.md` daily_digest 列）

**每日精選導讀 ＝ 專題策展（editorial curation），不是「當天文章逐篇 recap」。** 老闆已連 4 次糾正此點，做錯會被打回。

硬規格：
- **主題必須由時事／近期重要宣告／近期熱門新聞／近期熱門標的驅動**，或框成回答一個**具體投資議題**（例：「AI 資本支出爆增，選擇權市場怎麼定價、該不該擔心？」）。
- **撈整個 archive 同主題舊文 3–6 篇**串成敘事弧 — **禁止**只湊「本週發過的文章」。跨時間找最能支撐該議題的文章。
- **每篇被引用的文章要 inline 標註**（標題 + 連結 + 那篇提供了哪個具體數字／結論），不是文末列清單。
- **深度 ≥ 4000 字**。
- 具名框架（例如前一版用的「三個 VIX 照不到的角落」＋檢查表）— 讓讀者帶走可用的東西。
- **title 不可以「每日精選導讀｜」起頭**（前端區塊已有此標頭，會重複）；用專題式標題。
- `details.content_type='daily_digest'`；被策展的文章 slug 寫進 `details.digest_articles`；tags 含 `精選導讀`。
- 立即 `published`（不進 draft pool）。

參考已上線的正確範例：`mile_4901f7bc`（AI 資本支出投資議題專欄 v2）。

## 選題

今天（2026-07-13）的時事 hook 自己判斷（可用 WebSearch 掃近期市場新聞／熱門標的）。注意：**今早 10:00 剛上線無人載具系列 EP0**（`mile_a8d79d6a`），且本班另有 EP1 在寫 —— **digest 不要選無人機／國防題材**，避免與系列自我打架、佔用同一版位。挑另一條軸線。

## Evidence package 先於 prose（硬規則）

動筆前先組好：
- ≥3 個可驗證數字（primary source：yfinance / FRED / 我們自己的 experiments results.json；標來源與日期）
- ≥1 表
- ≥1 圖（真圖表，matplotlib 產生；**不可** ASCII／文字框冒充）
- ≥1 層量化分析（before-after / cross-section / rolling / event-window / vol change 擇一以上）

數字對不上就換題，不強推。研究誠實 > 一切：不可造假、不可虛構、不過度宣稱。

## Dedup gate（寫之前跑，不可跳過）

```bash
uv run python scripts/check_arc_dedup.py --text-file /tmp/digest_theme.md --audience general --title "<planned title>"
```
exit 1（K-COVERAGE 或 ARC DUPLICATE）→ 換題，不要硬寫。

## 寫後 gate（全部要過才 publish）

1. `.claude/skills/anti-ai-style/references/editor-sop.md` 3 階段 9-checklist
2. `uv run python scripts/anti_ai_gate.py --file /tmp/<draft>.md` → **exit 0 才可 publish**；MUST hit 任一 = 整篇改寫。禁 `--force` 繞過。
3. 破折號規則、禁翻譯腔／套路 hook／空泛評論。

## 懶人包

general audience 文章文末附懶人包圖組（`lazypack-infographic` skill）。Codex 為 primary generator；若 codex 不可用，走自寫 matplotlib renderer（數字直讀 results.json，不可手 key）。

## 發佈

走 feed-publisher 正規路徑 publish（立即 published）。發完回報：mile_id、title、字數、引用的 archive 文章 slug 清單、圖表路徑、gate 結果。

## 成功標準

- 專題策展（非逐篇 recap）、時事／議題驅動、跨時間撈 archive 3–6 篇、每篇 inline 標註
- ≥4000 字、真圖表、真數字有來源
- arc-dedup + anti_ai_gate 皆通過
- 已 published 且線上可見（curl 驗證 `https://volpred.zeabur.app/v3/reports/<mile_id>`）

## Mission sanity check

服務 Mission #1（把文章寫好）+ #5（曝光流量）。digest 是每日 fixture，斷檔 = release 節奏斷 = 老闆點名過的問題。
