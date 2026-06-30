---
name: project_fb_page_operation
description: VolPred FB 粉專(id 61590464616031)由 AI 全權經營+優化+固定巡檢；個人優先於粉專；headless API 發文卡 App Review
metadata: 
  node_type: memory
  type: project
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

用戶 2026-06-03 指派:**VolPred 粉專改由 AI 全權經營** —「上面所有該優化的部分都由你處理」+「固定巡檢也是你」。

## 粉專基本資料
- 名稱 **VolPred**,Page ID **61590464616031**,類別 投資服務,連結 zeabur.app
- URL: https://www.facebook.com/profile.php?id=61590464616031
- 0 追蹤者(2026-06-03 建立),**尚無大頭照/封面照**
- 管理:以 Ivan Lai 個人帳號切換為粉專身分(右上 profile switcher → VolPred);操作完**務必切回 Ivan Lai**

## Chrome 發文優先順序(用戶硬性 2026-06-03)
**先發「個人(Ivan Lai)」→ 才發粉專**。個人帳號有 423 追蹤者(觸及來源),粉專目前 0 觸及。

## 待優化項目(AI 自主處理)
- [ ] 大頭照(VolPred logo)+ 封面照
- [ ] 關於/簡介、CTA 按鈕、釘選貼文(精選)
- [ ] vanity URL(@volpred)— 需達 FB 門檻
- [ ] 內容節奏:feed 已發的 reader-facing 文章同步上粉專(個人→粉專)
- [ ] 追蹤者成長:從個人帳號/既有受眾導流

## ⚠️ Headless API 自動發粉專 = 卡 App Review(2026-06-03 實測結論)
- 建了 3 個 FB app(VolPred=FB登入 / VolPredPage=企業商家 / VolPredPoster=消費者舊版,App ID 1521006299817310)
- **三種類型都一樣**:`pages_manage_posts` 被 Meta 鎖在 **App Review + 商家驗證**後;dev 階段 Graph API Explorer 授權只拿到 `public_profile`(實測 /me/permissions 確認),page 權限被丟掉
- 「自有粉專 dev 模式免審查」的舊規則已被 Meta 取消(2024+)
- `scripts/fb_page_post.py` 已寫好(讀 .env FB_PAGE_ID/FB_PAGE_ACCESS_TOKEN,post+首留言連結),但**等不到能用的 Page token**,除非走完 App Review
- **結論**:粉專發文目前只能走 Claude in Chrome(互動 session);headless cron 要等用戶決定是否投入 App Review(數天、要公司文件)。fb_page_post.py 暫時 dormant。

## 圖片生成走 Codex,禁直接打 OpenAI pay-per-call API（用戶 2026-06-03 硬性,「幹 我不要用api」）
- 生圖一律走 **Codex（ChatGPT 訂閱、已付費）**,**不可**用 `.env` 的 `OPENAI_API_KEY` 直接打 `api.openai.com/v1/images`(按張計費)。
- `scripts/gen_image.py`（直接 API 版）**已 deprecated,不再使用**;當天誤用了 1 次（logo,已記 `storage/logs/openai_image_usage.jsonl`）。
- **可行方法(2026-06-03 實測):computer-use 操作 ChatGPT web(chatgpt.com,Ivan Lai Plus 訂閱)生圖** — 零 API 費用。流程:chatgpt.com 已登入 → 輸入生圖 prompt → Enter 不送要點右下↑送出鈕 → 等~25s → 點圖右下分享鈕 → 下載 → 檔案落 ~/Downloads → cp 到 storage/assets/。
- **Codex CLI 生圖不可行**:`codex exec` 跑 1 分鐘零輸出零檔案(coding agent 不出圖),已棄用此路。

## 打字壞字坑(2026-06-03)
Chrome `type` 動作會把少數中文字打錯(實測 沮→氮、攤→攝)。**發公開貼文前必逐段 zoom 校對**;JS 設剪貼簿在 FB 分頁會 timeout,不可靠。

相關:[[feedback_fb_opening_no_friend_asked]] [[feedback_fb_personal_account_chrome_only]] [[feedback_trending_repost_route]]
