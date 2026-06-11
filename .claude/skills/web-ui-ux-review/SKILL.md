---
name: web-ui-ux-review
description: 前端 UI/UX 專業審查與優化 SOP — 任何 frontend-v2-fix 視覺/互動改動的設計 gate。觸發時機：(1) boss 抱怨 UI/UX (2) 新頁面/新區塊上線前 (3) 每次 deploy 前的視覺 spot check (4) 設計統一/重構任務
---

# Web UI/UX 審查與優化 SOP

> 2026-06-11 建立。背景：boss 連續抓到「同類型不同風格」「收合方式不一樣」「會員提問 badge 不見了」「footer 被蓋掉」「badge 不精確」— 工程向修補缺乏設計視角的系統性檢查。本 skill 是每次前端改動的設計 gate。

## 核心原則（依優先序）

1. **正確性先於美觀**：顯示錯的資訊（收盤顯示開盤、stale 數據）是可信度硬傷，優先於任何視覺
2. **一致性是專業感的來源**：同類型元件必同風格 — 用 `src/lib/design-tokens.ts`，禁止手寫平行樣式
3. **內容可見性**：做了的功能要讓讀者找得到（入口、排序、tab）— 「存在但看不到」= 不存在
4. **白話優先**：一般讀者看得懂（已建立 pattern：plainSignalSummary / plainInvestmentTakeaway）
5. **法律紅線**：任何文案不可暗示個人化投資建議（「建議」字眼慎用；免責聲明常駐 footer）

## 改動前 checklist（設計 gate）

### A. 一致性掃描（boss 最在乎）
- [ ] 同類型元件（卡片/badge/標題/收合/按鈕/空態）是否已有既有 pattern？**先 grep 再造** — `grep -rn "details open\|collapsed\|badgeBase" src/`
- [ ] 新樣式是否引用 `design-tokens.ts`？需要新 token 就加進去，不要 inline 手寫
- [ ] 收合元件統一規格：點整個 header 觸發 + 右側 chevron-down svg（h-5 w-5 text-gray-500，展開時 rotate-180）
- [ ] Badge 統一規格：`badgeBase`（rounded-full px-2 py-0.5 text-[10px] font-semibold）+ 色彩語意表（藍=方向/分類、紫=校準/每日、綠=狀態 good、紅=事件/警示/遲發、黃=會員/策略、灰=中性）
- [ ] 字級 scale：[10px]=徽章、[11px]=輔助、xs=說明、sm=正文、base/lg=標題 — 不可越級

### B. 資訊正確性
- [ ] 任何「狀態」顯示（開盤/收盤、active/delisted、最新時間）— 語意是 day-level 還是 live？渲染是否匹配？
- [ ] 時間顯示一律台北時區標示；相對時間（N 分鐘前）必加 `suppressHydrationWarning`
- [ ] 數據 timestamp 是否 stale 可見（讓讀者知道資料多新）

### C. 內容可見性
- [ ] 新內容類型有沒有入口（tab / nav / footer link）？
- [ ] 排序（diversify/cluster）會不會把整類內容排到不可見？少量類型（如 member_qa 9 篇）需要專屬 tab
- [ ] infinite scroll 必須有界（auto 前 3 頁，之後手動「載入更多」）— footer 必須可達

### D. Hydration / 技術品質
- [ ] `Date.now()` / `new Date()` / `Math.random()` 出現在 render path → SSR/client mismatch → #418；用 suppressHydrationWarning 或 client-only
- [ ] 任何 STATUS/CONFIG map 查表必有 fallback（未知 key 不可 crash 整頁 — /paper major_revision 事故）
- [ ] 空態、載入態、錯誤態三態都有設計（不可白屏/裸 spinner 無限轉）

### E. 部署後驗證（必做，不可只看 build 過）
- [ ] Chrome 實際開頁截圖（桌面寬度）— 看 grid 排版、留白、視覺層級
- [ ] `read_console_messages` pattern="418|error" 查 console
- [ ] 改動目標的具體驗證（JS elementFromPoint / innerText 抓實際渲染值，不靠假設）
- [ ] grid 改動必看寬螢幕（auto-fit + justify-center 在 1568px 寬造成偏右事故 2026-06-11）

## 已踩坑記錄（每次審查先讀）

| 日期 | 坑 | 教訓 |
|---|---|---|
| 06-11 | 台股收盤後 6 小時仍顯示「● 開盤」 | API is_open 是 day-level，前端當 live 渲染 — 狀態語意要對齊 |
| 06-11 | 競技場 details ▶ vs 策略面板 useState chevron 兩種收合 | 同類交互必先 grep 既有 pattern |
| 06-11 | member_qa badge「不見了」 | 其實是 9 篇全被 cluster 排序排到 100 名外 + 無 tab 入口 — 可見性問題伪裝成樣式問題 |
| 06-11 | auto-fit+justify-center 寬螢幕偏右 | grid 改動必驗寬螢幕截圖 |
| 06-11 | excerpt 裸露 markdown 符號 | 顯示層 sanitize（stripMarkdown）；上游 content_type 已強制落地 |
| 06-11 | footer 被 infinite scroll 蓋掉 | 無限自動載入必設界 |
| 06-10 | /paper STATUS_CONFIG 未知 status 全頁 crash | 查表必 fallback |

## 與其他 skill / 規則的關係
- 部署：`.claude/rules/frontend-and-deploy.md`（巢狀 repo + deploy-zeabur-safe.sh）
- 文案風格：`anti-ai-style`（reader-facing 文字）
- Badge 分類底層：publisher `content_type` 強制落地（src/volpred/publisher/publisher.py）
