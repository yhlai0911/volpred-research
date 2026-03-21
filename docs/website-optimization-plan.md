# 網站優化開發計劃
> 建立日期：2026-03-17
> 目標：將 VolPred 從研究工具升級為可行銷、可經營的產品網站
> 整合來源：website_restructure_plan_v4.md + website_ui_requirements.md + 新增行銷優化

## 原重構計劃（v4）完成度

### 已完成
- [x] Supabase PostgreSQL 資料庫 + Auth（Google OAuth）
- [x] Next.js frontend-v2 部署到 Zeabur（volpred.zeabur.app）
- [x] 導航 5 項（研究 | 工具下拉 | 論文 | 問答 | 登入）
- [x] 策略信號面板（多策略、DB 驅動、可收合）
- [x] Feed 首頁（audience 篩選、標籤、搜尋、無限滾動）
- [x] 文章 views/likes 追蹤
- [x] VIX 計算器（50/50 SPY/GLD + SPY-only 雙模式）
- [x] 風險預報儀表板
- [x] Q&A 頁面（雙欄：研究問答 + 會員排名表、auth gate、配額）
- [x] 論文頁面（卡片 + 進度條）
- [x] 文章交叉連結（延伸閱讀研究原文 / 白話版）
- [x] Dark/Light 模式
- [x] 手機底部導航
- [x] Skeleton loading
- [x] 資料遷移完成（articles, questions, memory, risk, paper trading）
- [x] supabase_sync.py 持續同步
- [x] Domain 已切換到 volpred.zeabur.app

### 未完成（原 v4 計劃遺留）
- [ ] **V0.1** 策略面板 sparkline 走勢圖（v4 要求 30 天 portfolio value 走勢）
- [ ] **V0.2** 策略面板「操作說明」按鈕（展開操作步驟）
- [ ] **V0.3** 策略面板「查看績效」連結到 Portfolio 頁面
- [ ] **V0.4** Portfolio 頁面（大改）— 完全未建
  - 每策略一個區段（錨點 #策略ID）
  - 累計報酬圖（equity curve + benchmark 比較）
  - 操作手冊（以 $100 萬為例）
  - 績效指標（Sharpe、MDD、年化、勝率）
  - 回測 vs 實盤對比
  - 交易記錄表（日期、動作、權重變化）
- [ ] **V0.5** FTS 搜尋改用 Supabase server-side（目前是 client-side filter）
- [ ] **V0.6** Thinking 分層發佈（raw → 週度日記 → feed）
- [ ] **V0.7** Feature gating 實際執行（DB 表已有，前端未 enforce）
- [ ] **V0.8** Admin Dashboard 強化（文章管理、會員管理、analytics 統計）
- [ ] **V0.9** API rate limiting（Next.js middleware + IP-based）
- [ ] **V0.10** Supabase heartbeat cron（防 free tier pause）

---

## Phase W1: SEO 基礎建設（最高優先）

### W1.1 搜尋引擎基礎
- [ ] 新增 `robots.txt`（`frontend-v2/src/app/robots.ts`）
- [ ] 新增 `sitemap.xml`（`frontend-v2/src/app/sitemap.ts`），動態列出所有文章
- [ ] 新增 favicon + apple-touch-icon（`frontend-v2/public/`）
- [ ] 新增 `manifest.json`（PWA 支援，可加到手機主畫面）

### W1.2 Open Graph & 社群分享
- [ ] `layout.tsx` 加入全站預設 OG tags（og:title, og:description, og:image, og:url）
- [ ] `/reports/[id]` 加入 `generateMetadata()` 動態產生每篇文章的 title、description、OG tags
- [ ] 製作預設 OG image（1200x630，品牌視覺）
- [ ] 各子頁面加入各自的 metadata（VIX 計算器、風險預報、論文、問答）

### W1.3 結構化資料
- [ ] 文章頁加入 JSON-LD `Article` schema
- [ ] 問答頁加入 JSON-LD `FAQPage` schema
- [ ] 首頁加入 JSON-LD `WebSite` schema（啟用 Google Sitelinks Search Box）

## Phase W2: 首頁改造 — 產品化

### W2.1 Hero Section
- [ ] 新增 Hero 區塊：一句話價值主張 + 副標題 + CTA 按鈕
  - 主標題：「AI 驅動的科學化投資策略」
  - 副標題：「每日更新波動率預測，幫你決定該持有多少股票」
  - CTA：「查看今日建議」→ 滾動到策略卡片
- [ ] 策略卡片加一行導語：「以下策略正在用真實數據實盤追蹤 →」

### W2.2 內容分層
- [ ] 首頁預設顯示「一般讀者」tab（而非「全部」）
- [ ] 新增「精選文章」區塊（手動或自動置頂高品質一般讀者文章）
- [ ] 「研究」tab 改為需要點擊才展開，避免嚇跑新訪客

### W2.3 重複內容清理
- [ ] 修改 `daily_update.py`：同一天只保留最新一篇「每日建議」
- [ ] 或在前端 deduplicate 同日同標題的文章

## Phase W3: 用戶留存機制

### W3.1 訂閱系統
- [ ] 新增 Email 訂閱功能（可用 Supabase + Resend/SendGrid）
- [ ] 「每日建議」自動發送 email 給訂閱者
- [ ] 或串接 LINE Notify API，每日推送策略建議

### W3.2 社群 & 分享
- [ ] 每篇文章加入分享按鈕（LINE、Facebook、Twitter、複製連結）
- [ ] 頁尾加入社群連結（如有經營 LINE 群、FB 粉專）
- [ ] 文章卡片加入「分享」快捷按鈕

### W3.3 新手引導
- [ ] 新增「新手指南」頁面（`/guide`）：什麼是波動率目標策略、如何使用本站
- [ ] 首頁 Hero 加入「不知道從哪開始？」連結到指南

## Phase W4: 信任 & 品牌

### W4.1 關於頁面
- [ ] 新增「關於」頁面（`/about`）：研究背景、團隊（大葉大學）、研究方法
- [ ] 加入學術論文引用作為可信度背書

### W4.2 績效視覺化（合併 V0.1 + V0.4）
- [ ] Paper Trading 頁面加入 equity curve 圖表（用 Recharts）
- [ ] 策略卡片加入迷你績效走勢 sparkline
- [ ] 每策略操作手冊 + 回測 vs 實盤對比
- [ ] 策略面板「操作說明」展開按鈕（V0.2）
- [ ] 策略面板「查看績效」連結（V0.3）

### W4.3 法律 & 免責
- [ ] 新增免責聲明頁面（`/disclaimer`）
- [ ] 頁尾加入「免責聲明」連結

## Phase W5: 技術優化

### W5.1 Analytics
- [ ] 加入 Plausible 或 Umami（隱私友善、不需 cookie banner）
- [ ] 設定基本事件追蹤：頁面瀏覽、策略計算器使用、文章閱讀

### W5.2 效能
- [ ] 首頁 SWR refreshInterval 改為 300000（5 分鐘），靜態內容不需 60 秒刷新
- [ ] 考慮熱門文章用 ISR（Incremental Static Regeneration）
- [ ] 圖片用 Next.js `<Image>` 優化
- [ ] FTS 搜尋改 server-side Supabase（V0.5，取代 client-side filter）

### W5.3 UX 修復
- [ ] 修復亮色模式下寫死的 `text-gray-100`（應為 `text-gray-900 dark:text-gray-100`）
- [ ] 手機底部導覽加入「風險預報」（替換或新增一個 icon）
- [ ] 問答系統允許未登入用戶瀏覽（只限制提問需登入）

### W5.4 後端強化（V0 遺留）
- [ ] API rate limiting — Next.js middleware + IP-based（V0.9）
- [ ] Supabase heartbeat cron 防 pause（V0.10）
- [ ] Feature gating 前端 enforce（V0.7）
- [ ] Admin Dashboard 強化（V0.8）

---

## 優先執行順序（按 ROI）

| 順序 | 項目 | 預估工時 | 影響 |
|------|------|---------|------|
| 1 | W1.1 + W1.2（SEO 基礎 + OG tags）| 2-3h | Google 可索引 + 社群分享有預覽 |
| 2 | W2.1（Hero Section）| 1-2h | 新訪客轉換率大幅提升 |
| 3 | W5.1（Analytics）| 30min | 有數據才能優化 |
| 4 | W3.2（分享按鈕）| 1h | LINE 是台灣最重要傳播管道 |
| 5 | W2.3（清理重複每日建議）| 1h | 內容品質觀感 |
| 6 | W2.2（預設一般讀者 tab）| 30min | 降低新訪客跳出率 |
| 7 | W4.1（關於頁面）| 1h | 建立信任 |
| 8 | W4.2（績效曲線 + sparkline + 操作說明）| 3-4h | 視覺說服力 + v4 遺留核心 |
| 9 | W3.1（Email/LINE 訂閱）| 3-4h | 留住讀者的核心機制 |
| 10 | W1.3 + W3.3 + W5.2（進階 SEO + 新手指南 + 效能）| 3-4h | 長期 |
| 11 | W5.4（rate limit + heartbeat + feature gate）| 2-3h | 穩定性 |
