# 登入 / 註冊 / Onboarding 現況盤點

> Owner: growth agent（task `growth_p1_auth_onboarding`）
> 盤點日期：2026-07-19（台灣時間）
> 目的：解決 `docs/boss_direction_recommendations.md` rid:auth-onboarding 卡了 26 天的「flow 如果還沒」懸而未決 —— 先確認現況，再決定任務範圍。

## 一句話結論

**部分可用 → 登入/註冊 flow 已上線且線上可用，缺的是 onboarding。** 因此本任務**縮為 welcome onboarding**（首登歡迎頁 / 引導 / welcome email），不需要從零建 auth。

---

## 一、已有什麼（What exists — 有證據）

### 前端登入流程（LIVE）
- **登入元件**：`frontend-v2-fix/src/components/AuthButton.tsx` — Google OAuth 按鈕，`supabase.auth.signInWithOAuth({ provider: 'google', redirectTo: .../auth/callback })`（line 128-133）。登入後顯示頭像 + 下拉選單（會員中心 / 我的收藏 / 我的提問 / 登出）。
- **全站掛載**：`AuthButton` 掛在 `src/app/layout.tsx`（原版 header）與 `src/components/v3/V3Shell.tsx`（v3 header）—— 兩版都有入口，不是孤兒元件。
- **OAuth callback**：`src/app/auth/callback/route.ts` 回傳 HTML（非 server redirect），保留 URL hash fragment 讓 client SDK 讀 token —— 已針對 `docs/zeabur-oauth-gotcha.md` 記載的 Zeabur reverse-proxy + implicit-flow 陷阱做修正（用 `x-forwarded-host` / `NEXT_PUBLIC_SITE_URL`，fallback `volpred.zeabur.app`）。
- **Supabase client**：`src/lib/supabase-browser.ts` 用 `flowType: 'implicit'` + `detectSessionInUrl: true`；`isSupabaseBrowserConfigured()` 檢查 `NEXT_PUBLIC_SUPABASE_URL` / `_ANON_KEY`。
- **session 管理**：全站以 `supabase.auth.getSession()` + `onAuthStateChange` 訂閱（AuthButton、MyMemberHomeConsole、questions、radar、admin console 等 20+ 元件）。

### 後端 / DB（LIVE）
- **profile 自動建立**：`docs/migration/003_auth_trigger.sql` 的 `handle_new_user()` trigger（`AFTER INSERT ON auth.users`）—— 新用戶註冊時自動在 `public.profiles` 建一筆（email / display_name / avatar），無需前端額外呼叫。
- **提問配額**：同檔 `check_question_quota()` trigger 依 role（一般 / premium / admin）自動管月配額。
- **request auth**：`src/lib/request-auth.ts` / `admin-auth.ts` 用 `supabaseAuth.auth.getUser(token)` 驗 API bearer token。
- 註：`src/volpred/mirror_auth.py` 是 **ops mirror sync 的 admin token**（`x-ops-key`），與用戶登入無關，勿混淆。

### auth-gated 功能（都已依賴上述 flow 運作）
`/me`（會員中心）、`/me/bookmarks`、`/me/questions`、`/questions`（提問）、`/radar`、`/admin/*` 全部靠這套 session。

## 二、線上實測證據（curl 唯讀，2026-07-19）

| 檢查 | 結果 | 意義 |
|---|---|---|
| `GET /` | HTTP 200 | 首頁正常 |
| `GET /auth/callback` | HTTP 200（HTML） | OAuth callback route 線上存活 |
| `GET /me` | HTTP 200 | 會員中心可達（client-side gate） |
| 首頁 HTML | 含 `qxhfgdfzazwpkdgesavm.supabase.co` | **Supabase 公鑰已注入 → 登入按鈕啟用**（非「登入未啟用」狀態） |
| `GET /login /signin /signup /auth /register /me/login` | 全 **HTTP 404** | 無專屬登入/註冊頁（見下方「缺什麼」） |

## 三、缺什麼（What's missing）

1. **無 welcome / onboarding 首登體驗** ← 本任務核心缺口
   - 新用戶 Google 登入後直接落到與老用戶相同的會員中心 summary；`MyMemberHomeConsole.tsx` 登出態只顯示「登入後可查看收藏/提問」提示，登入態直接顯示 summary，**沒有首登歡迎、沒有引導、沒有平台功能導覽**。
   - `handle_new_user` trigger 靜默建 profile，沒有任何歡迎訊號。
2. **無 welcome email** — Supabase 沒接 auth email hook，新會員註冊後不會收到任何信。
3. **無專屬登入/註冊 landing page** — 登入只有 header 一顆按鈕（`/login` 等全 404）。OAuth-only 情境下可接受，但缺一個「為什麼要登入 / 會員權益」的 conversion 落地頁（漏斗入口）。
4. **只有 Google OAuth** — 無 email/password、無其他 provider（Apple/GitHub 等）。限縮了不用 Google 的可觸及用戶。

## 四、後續可派工 scope（onboarding MVP，每項可獨立派工）

> 前端改動注意：`frontend-v2-fix/` 是巢狀 git repo（commit 要 `cd` 進去）；且**原版 + v3 雙版路由**都要同步改（見 `.claude/rules/frontend-and-deploy.md`）。

- **OB-1｜首登歡迎卡（P1，最小可行）**：`MyMemberHomeConsole.tsx` 判斷「profile 剛建立 / 首次登入」時，頂部插入一張歡迎卡（歡迎詞 + 3 步引導：看研究 feed / 收藏文章 / 提問）。判準可用 profile `created_at` 距今 < N 分鐘，或 localStorage flag。原版 + v3 各一。
- **OB-2｜歡迎 email（P2）**：接 Supabase auth email hook 或在 `handle_new_user` 後觸發一封 welcome email（平台簡介 + 熱門文章連結 + 提問引導）。需與現有 email 基建（`send-alert` / ops mailer）對齊，避免另建一套。
- **OB-3｜登入 landing page（P2）**：新增 `/login` 頁（原版 + v3），說明會員權益 + Google 登入 CTA，取代目前「header 按鈕是唯一入口」；順帶修掉 `/login` 404（利於外部分享與 SEO 落地）。
- **OB-4｜email/password 或多 provider（P3，選配）**：評估是否加 email magic-link 或 Apple/GitHub provider，擴大可觸及用戶；非 MVP，視 OB-1~3 轉換數據再定。

**建議順序**：OB-1（前端純呈現、最快見效、無後端相依）→ OB-2 → OB-3 → OB-4。OB-1 可立即拆成一支前端 task 派工。
