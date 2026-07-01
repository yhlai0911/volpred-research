# VolPred FB 粉專營運 SOP（頁面本身，非單篇貼文文案）

**Scope**：這份文件管「VolPred 粉專（Page ID `61590464616031`）作為一個持續存在的頻道」要做什麼 —
大頭照/封面/簡介/vanity URL/追蹤者成長/巡檢節奏。單篇貼文的**文案風格**規則在同資料夾的
`fb-ivanlai-tone.md`；trending_repost 的**選題與雙發佈流程**在 `../SKILL.md`。三者互補，
不要重複維護。

## 背景（2026-06-03 boss 指派）

boss 明示「VolPred 粉專改由 AI 全權經營」+「固定巡檢也是你」。粉專起步時 0 追蹤者、
無大頭照/封面照。個人帳號（Ivan Lai，423 追蹤者）觸及遠優於粉專（0 觸及）。

## 發文優先序（硬性）

**先發「個人（Ivan Lai）」→ 才發粉專**。個人帳號是目前唯一有機觸及來源。粉專同步只是
「備份到頻道」，不是主發佈面。

## 待優化項目清單（AI 自主處理，非一次性 — 是 standing backlog）

- [ ] 大頭照（VolPred logo）+ 封面照
- [ ] 關於/簡介文案、CTA 按鈕、釘選貼文（精選代表作）
- [ ] vanity URL（`@volpred`）— 需先達 FB 門檻（通常追蹤數 + 帳號存在時間）
- [ ] 內容節奏：feed 已發佈的 reader-facing 文章同步上粉專（個人 → 粉專）
- [ ] 追蹤者成長：從既有個人帳號受眾導流

## 已知硬限制（2026-06-03 實測，不要重新嘗試繞過）

**Headless API 自動發粉專會卡 App Review** — 已測試 3 種 FB app 類型（FB 登入 / 企業商家 /
消費者舊版），`pages_manage_posts` 一律被 Meta 鎖在 App Review + 商家驗證後；dev 階段
Graph API Explorer 授權只拿到 `public_profile`，page 權限被丟掉。「自有粉專 dev 模式免審查」
的舊規則已在 2024+ 被 Meta 取消。

**結論**：粉專發文只能走 Claude in Chrome（互動 session），無法 headless cron 自動化，
除非投入 App Review（需商業文件、數天流程 — 屬於用戶 policy 決策範疇，不要自主啟動申請，
但可以自主提議）。`scripts/fb_page_post.py` 已寫好但 dormant，等 Page token 可用。

## 巡檢節奏建議

粉專營運屬於低頻但持續的 ops 項目 — 不需要獨立 cron job，但應該在下列時機被主動檢查一次：
- 每次要發 trending_repost / event_article（本來就會走 Chrome 互動 session）時，順手看一眼
  粉專 profile 是否還缺基本資料（大頭照/簡介等）
- 每月 skill 審查報告 / 平台體檢時，列一次「粉專 backlog 待辦清單」還剩幾項

## 相關

- 貼文文案風格 → `fb-ivanlai-tone.md`
- Trending repost 選題與雙發佈流程 → `../SKILL.md`
- FB 帳號/瀏覽器選擇機制 → user memory `reference_fb_chrome_browser_autoselect`
- 圖片生成走 Codex / ChatGPT web computer-use，禁止直接打 OpenAI pay-per-call image API
  （`scripts/gen_image.py` 已 deprecated）
