---
name: reference_fb_chrome_browser_autoselect
description: FB 發文用「MAX STUDIO」Chrome（有 facebook.com/yihao.lai 登入分頁），自己選不要問用戶；deviceId 會輪替
metadata:
  node_type: memory
  type: reference
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

用戶 2026-06-08 硬性糾正：「每次都還要我選 那就不叫全自動了」+「為什麼每次還要我允許」+「妳幫我做啊」。

**FB 發文 / Claude in Chrome 的瀏覽器選擇 = 自己決定，不要跑 AskUserQuestion 問用戶。**

## 哪台登入了 FB
- **「MAX STUDIO」** 這台 Chrome 登入了用戶 FB（Ivan Lai）。辨識特徵：它的 tabs 含 `https://www.facebook.com/yihao.lai`（用戶個人檔案）+ `http://127.0.0.1:8787/`（VolPred 工作監控）。
- ⚠️ **deviceId 會輪替**（同一台 connectedAt 變、name 也可能變 Browser 2→3）——**不要 hardcode deviceId**。每次 `list_connected_browsers` 拿最新，select 後 `tabs_context_mcp` 看哪台 tabs 有 `facebook.com/yihao.lai` 就是它。
- 「MAC STUDIO」（名字很像但不同台）的 FB 是**登出**的 — 別用。新開分頁到 facebook.com 會顯示登入牆。

## 流程（不問用戶）
1. `list_connected_browsers` → 找 name 含 "MAX STUDIO" 的 deviceId → `select_browser`
2. `tabs_context_mcp` → 找 `facebook.com/yihao.lai` 的 tabId（會輪替，每次重抓）
3. 直接操作那個 tab 發文
4. 連線會 flapping（中途掉線要重 list+select）；MAX STUDIO 掉線就等它回來再抓

## 中文輸入（已驗證可行 2026-06-08；⚠️ 2026-07-16 重大限定）
- FB composer 用 `type` 會中文亂碼 → **改 `pbcopy`（agent 本機）寫剪貼簿 + 瀏覽器 Cmd+V**。2026-06-08 實測：貼上的中文完全正確、連結預覽卡正常生成。
- 發文流程：點「在想些什麼?」composer → 點文字區 → Cmd+V → 按「繼續」→ 貼文設定頁（受眾/排程）→ 按「發佈」。
- **⚠️ pbcopy 只對「本機」Chrome 有效（2026-07-16 incident）**：MCP extension 連的 `398dcdba`（老闆主力 Chrome）在**另一台機器** — 本機 `pbcopy` 到不了它的剪貼簿，Cmd+V 貼出來的是**老闆那台機器剪貼簿裡的私人內容**（當時是研究溝通英文長文，差點貼進公開 FB 留言，當場 cmd+a Delete 清除未送出）。規則：(a) MCP Chrome 上**貼上後必截圖驗證內容再送出**；(b) 純 ASCII（URL）直接用 `type`，不走剪貼簿；(c) 中文長文只能走本機 CDP Chrome（`fb_realchrome_post.py`，port 9222，pbcopy 同機有效且有 pbpaste+回讀雙驗證）。

## 安全邊界
- **不能替用戶輸入 FB 密碼**（硬規則，即使他說「妳幫我做」）。所以只能用「已登入」的瀏覽器；若都登出只能請用戶登入一次。
- 擴充「逐網域 permission」（navigate 跳允許）要全自動需用戶在擴充給 facebook.com 持久授權。

相關：[[feedback_fb_personal_account_chrome_only]]、[[feedback_fb_opening_no_friend_asked]]、[[feedback_dont_ask_do]]、[[project_fb_page_operation]]。
