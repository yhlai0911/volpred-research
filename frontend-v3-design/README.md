# frontend-v3-design

VolPred 優化設計（Claude Design 產出）— 以獨立 frontend target 形式存放，**尚未啟用為正式 active frontend**。

## 設計來源
- 原始 bundle 來自 `claude.ai/design` 的 handoff；保留於 `source/` 目錄
- 母設計：`source/project/VolPred 優化設計.html`
- 設計對話紀錄：`source/chats/chat1.md`

## 三個 variant
- **V1 Editorial（雜誌編輯）** — NYT / Economist 風
- **V2 Terminal（金融終端）** — Bloomberg / TradingView 風
- **V3 Journal（學術期刊）** — Stripe Press / arXiv 風

底部浮動 switcher 可即時切換 variant + 深/淺色 + accent + density。

## 檔案結構
- `index.html` — 入口（React via CDN + Babel standalone）
- `styles/base.css` — 設計系統（三個 variant 的 CSS variables）
- `components/*.jsx` — variant 實作與 shared components
- `data.js` — 目前使用設計階段的 mock data
- `source/` — 原始 handoff bundle（README、chats、原始 project/）

## 預覽
目前版本不受影響；此設計可用以下兩種方式預覽：

1. **線上 preview path**（已隨 `frontend-v2-fix` 部署）
   ```
   https://volpred.zeabur.app/preview/v3-redesign/
   ```
   主站 `/`、`/feed`、`/strategies` 等路徑完全不動，僅新增 `/preview/v3-redesign/` 入口

2. **本地開啟**
   ```
   open /Users/yhlai0911/Desktop/volpred-research/frontend-v3-design/index.html
   ```

## 一鍵切換到這個設計（未來路徑）
當確認要切過去時，只需：

1. 改 `config/project_targets.json`：
   ```json
   "active_frontend": "frontend-v3-design"
   ```
2. 在 Zeabur 新增一個 static service（或替換現有 `volpred-v3` 的 source dir 指向 `frontend-v3-design/`），deploy
3. （未來）將 `data.js` 的 mock 資料改為從 Supabase / Mirror API fetch，走 Research Feed、策略、VIX 的真實資料來源（詳見下面「接真實資料 TODO」）

## 接真實資料 TODO
目前 `data.js` 是設計階段 mock，若未來要作為正式 active frontend 必須：
- [ ] `window.VolPredData.feed` 改為 fetch `/api/feed` 或讀 `feed.json`（`frontend-v2-fix/public/feed.json` 或對應 API）
- [ ] `window.VolPredData.strategies` 改為 fetch 當日 strategies 資料（走 `strategy_metrics.json`）
- [ ] `window.VolPredData.vixHistory` 改為接 market data API
- [ ] 三欄 feed 列表點擊需導到現有文章頁（article routing）
- [ ] 論文頁、會員問題頁 routing

## 不要做的事
- 不要直接改 `frontend-v2-fix/` 的 UI — 這是 active frontend，改動會直接影響線上站
- 不要把 mock data 混進 `storage/`（研究資料 source of truth）
- 不要在這個 folder 做 npm build — 目前只是靜態 HTML + React CDN，不需要打包
