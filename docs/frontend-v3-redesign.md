# Frontend V3 Redesign — 線上狀態

**狀態**：2026-04-19 V3 Editorial 設計正式上線於 `/v3/*`（在 `frontend-v2-fix` 內的隔離子路由），**舊站 `/` 完全不受影響**。

**線上**：
- 新設計：https://volpred.zeabur.app/v3/
- 舊站：https://volpred.zeabur.app/
- 部署 commit：`2f68833 feat(v3): add Editorial-themed` + `f4b0988 feat: sync live production`
- 部署 ID：`69e494fe50cfe9704d09132a` (Zeabur)

**設計決定**（2026-04-19）：
- 原始 handoff 有 3 個 variant（Editorial / Journal / Terminal），最終 commit 到 **Editorial 單一設計**（NYT / Economist 雜誌風），殺掉 prototype 階段的 Variant Switcher / TweaksPanel / dark-toggle
- 全站 Editorial primitives（Card / Table / Stat / Section / Button / Pill / RuleLine / PullQuote）
- 27 個 `/v3/*` route 全部 Editorial native（含 admin 13 頁 + reports article reader）
- 深色 dashboard 僅保留於 admin 類頁面（legitimately dashboard-feel），用 `rule-strong` 邊框框入 Editorial Section chrome，不孤立

## 設計來源
- Claude Design（claude.ai/design）handoff bundle
- 使用者指定的主檔：`VolPred 優化設計.html`
- 原始 bundle 保留於 `frontend-v3-design/source/`

## 三個 variant（底部浮動 switcher 切換）
1. **雜誌編輯（Editorial）** — NYT / Economist 風，襯線大標、頭版故事、三欄式編輯排版
2. **金融終端（Terminal）** — Bloomberg / TradingView 風，深色為主、即時 ticker
3. **學術期刊（Journal）** — Stripe Press / arXiv 現代化，留白、Feature Card

共通：深/淺色切換、4 色 accent、compact / comfortable / spacious density。

## 目前部署狀態
- **主站** `https://volpred.zeabur.app/` → `frontend-v2-fix`（Next.js，未動）
- **預覽** `https://volpred.zeabur.app/preview/v3-redesign/` → `frontend-v2-fix/public/preview/v3-redesign/index.html`
- **獨立 target** `frontend-v3-design/`（root 有可部署的 `index.html`，已在 `config/project_targets.json` 註冊但尚未啟用）

下次 `frontend-v2-fix` 部署會自動把 `public/preview/v3-redesign/` 一起帶上線，不需額外步驟。

## 一鍵切換程序（未來）
目前設計仍使用 mock data（`data.js`），切成 active frontend 前必須先接真實資料（見 `frontend-v3-design/README.md` 的 TODO 清單）。準備好後：

1. 編輯 `config/project_targets.json`：
   ```
   "active_frontend": "frontend-v3-design"
   ```
2. 調 Zeabur 對應 service：把 `volpred-v3` service 的 root dir 改為 `frontend-v3-design/`，或新建 static service
3. 部署

若設計未接真實資料就不要改 `active_frontend`（會讓線上站變成 mock）。

## 本地開啟（預覽）
```bash
open /Users/yhlai0911/Desktop/volpred-research/frontend-v3-design/index.html
```
或等 `frontend-v2-fix` 部署完後：`https://volpred.zeabur.app/preview/v3-redesign/`

## 若要拿掉預覽（回到純舊站）

### Phase 1 回復（移除 `/v3/` Next.js 路由，全部新檔案刪除）
2026-04-19 已完成 Phase 1：把新設計轉為真正的 Next.js 路由 `/v3/`，接上真實 feed 資料。所有新檔案都在新路徑，舊站零修改。回復指令：

```bash
cd /Users/yhlai0911/Desktop/volpred-research/frontend-v2-fix
rm -rf src/app/v3 src/components/v3 src/styles/v3-base.css
npm run build   # 驗證
```

Phase 1 建立的新檔案清單（18 檔，~4,111 行）：
- `src/app/v3/{layout,page}.tsx` — 入口（使用 position:fixed 覆蓋全屏，脫離 root layout 的 nav）
- `src/components/v3/V3App.tsx` — 主 shell（variant/theme/accent/density state）
- `src/components/v3/VariantSwitcher.tsx` + `TweaksPanel.tsx`
- `src/components/v3/shared/{Sparkline,TickerNumber,VixGauge,CategoryBadge,VolPredMark}.tsx` + `useClock.ts`
- `src/components/v3/variants/{Editorial,Terminal,Journal}.tsx`（三個 variant，共 ~2,700 行）
- `src/components/v3/hooks/{useV3Data.ts,mockData.ts,types.ts}` — SWR fetch `/api/publications/feed` + adapter + mock fallback
- `src/styles/v3-base.css` — 設計系統 CSS variables

### Phase 0 預覽拿掉（只移除 static preview path）
```bash
rm -rf frontend-v2-fix/public/preview/v3-redesign
```

### 完整回退（連 standalone target 一起拿掉）
```bash
rm -rf frontend-v3-design
# 然後手動從 config/project_targets.json 移除 frontend-v3-design entry
```

## Phase 1 目前狀態（2026-04-19）

- ✅ `npm run typecheck` pass，`npm run build` pass
- ✅ 27 個現有路由照常 build，舊站 byte-identical
- ✅ `/v3/` 靜態 prerender，+117 kB First Load JS
- ✅ Feed 資料接到 real `/api/publications/feed?limit=20`，會自動 adapter 成設計的 `{title, abstract, tags, ago, ...}` 形狀
- ⏳ strategies / vixHistory / market 數字（VIX/GARCH-σ/SPY/0050）**目前仍是 mock** — Phase 2 接 `/api/market-status` + `/api/strategy-overview`
- ⏳ 文章點 card 目前不會導到 `/reports/[id]` 文章頁（現階段純視覺預覽）
- ⏳ 論文頁、會員 QA、calculators 尚未在 `/v3/` 實作

## 如何預覽 Phase 1

**本地**：
```bash
cd /Users/yhlai0911/Desktop/volpred-research/frontend-v2-fix
npm run dev
# 瀏覽 http://localhost:3000/v3/
```

**雲端**：commit + push frontend-v2-fix → Zeabur 重部署 → `https://volpred.zeabur.app/v3/`

## 預覽時可測試
1. 底部浮動 switcher 切換三個 variant（雜誌／終端／期刊）
2. ⚙ 開 Tweaks 面板試 dark/light、4 色 accent、3 種 density
3. 確認 feed 列表載到真實最新文章（應該是 2026-04-18/19 的 research/event 文）
4. 離開 `/v3/` 回 `/` 確認舊站外觀完全沒變
