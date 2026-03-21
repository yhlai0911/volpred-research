# 網頁 UI/功能需求總覽

整理自用戶歷次對話中的明確要求。

## 1. 導航
- **5 項**：研究（首頁）| 工具（下拉：VIX 計算器 + 風險預報）| 論文 | 問答 | 登入
- **手機版**：導航不能超出邊界 → `overflow-x-auto`, `whitespace-nowrap`
- Thinking/Admin 手機隱藏（`sm:block`）

## 2. Feed 首頁
- **投資策略固定面板**（脫離 feed 卡片，獨立置頂區塊）
  - 多策略並列、可動態增減（DB `strategy_signals` 表驅動）
  - 顯示策略名、當前配置、VIX、更新時間
  - 可收合/展開
- 文章卡片含 views/likes
- audience 篩選（研究/一般/日記/QA）
- **標籤篩選可開合**，預設前 10 個，超過顯示 "+N more"
- 無限滾動 + FTS 搜尋

## 3. 文章系統
- **雙受眾**：research（專業）+ general（白話版）
- **文章交叉連結**：
  - 一般文章底 → 📊 延伸閱讀研究原文
  - 研究文章底 → 📖 看不懂？讀白話版
- 文章 badge 要正確分類（不要全是 milestone）
- 每篇記錄 views/likes/bookmarks/shares/read time

## 4. Q&A（問答頁）
- **兩欄佈局**：
  - 左：研究 Q&A（待研究 + 已解答 open questions）
  - 右：**會員排名表**（#、主題、提出者、狀態）
    - 不顯示分數，只有排名順序
    - 狀態：⏳評估中 → 📊已排名 → 🔬研究中 → ✓已解答
    - Internal open questions **不參與排名**
- 提問需登入、有配額（free=3/月）
- **排名機制說明**：讓用戶知道不能隨便提問，否則永遠排不到
- 排名表有欄位名稱
- 已解答問題的超連結用文章標題（不是 ID）

## 5. 論文頁
- **多篇論文展示**（卡片 + 進度條），不是只放一篇
- 論文更新後同步更新頁面（頁數、PDF）

## 6. 工具頁
- **VIX 計算器**：50/50 SPY/GLD 模式（預設推薦）、手機滑桿
- **風險預報**：儀表板風格、VIX/GARCH gauge

## 7. 會員系統
- Google OAuth + Magic Link（零密碼）
- 角色：free / premium / admin
- Feature gating（一條 SQL 切換 free→premium）
- 未來開放付費（Substack 同步可能性）

## 8. 後台管理
- Claude 自主管理後台（排程、數據分析）
- 管理文章、會員
- 檢視分析文章與會員數據（views/read time/likes 統計）
- Audit log 追蹤操作

## 9. Analytics（閱讀數據）
- 每篇 feed/paper 的**點選次數、閱讀時間、按讚、分享**
- server-side insert（防 spam）
- 聚合 materialized view（定時 refresh）
- 90 天 retention + 聚合後刪原始記錄

## 10. 留言/評論
- **預留功能，暫不啟用**
- Schema 已設計（comments table + RLS disabled）

## 11. Thinking 發佈
- **分層發佈**：raw thinking → 週度日記 → feed
- 不是所有 thinking 都發佈，過濾整理後才上

## 12. 部署
- **新 Zeabur 專案** `volpred-v2`（不影響現有站）
- 穩定後用戶切換 domain
- 過渡期現有網站持續更新

## 13. 全站 UI
- Dark/Light 模式
- 手機底部導航
- Skeleton loading
- SEO 優化
- PWA
