# Zeabur + Supabase OAuth Redirect 陷阱

## 問題
Google OAuth 登入成功後，瀏覽器被導向 `http://localhost:8080#access_token=...`，而不是正式網址。

## 根本原因
Zeabur 的 reverse proxy 架構：
```
用戶 → https://volpred-v2.zeabur.app → [Zeabur reverse proxy] → localhost:8080 (Next.js app)
```

在 server-side route handler 中，`request.url` 拿到的是 **內部地址** `http://localhost:8080/auth/callback`，不是外部的 `https://volpred-v2.zeabur.app/auth/callback`。

### 錯誤寫法
```ts
// ❌ 會拿到 localhost:8080
const { origin } = new URL(request.url);
return NextResponse.redirect(origin);
```

### 正確寫法
```ts
// ✅ 優先用 env var → x-forwarded-host → fallback
const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL ||
  `https://${request.headers.get('x-forwarded-host') || request.headers.get('host') || 'volpred-v2.zeabur.app'}`;
return NextResponse.redirect(siteUrl);
```

## 通用規則
在任何 reverse proxy 環境（Zeabur、Vercel、Railway、Docker + Nginx）中：
- **永遠不要** 用 `new URL(request.url).origin` 取得外部 URL
- **優先** 讀 `x-forwarded-host` / `x-forwarded-proto` headers
- **最佳實踐**：設定 `NEXT_PUBLIC_SITE_URL` 環境變數，明確指定外部 URL

## 額外注意：Implicit Flow + Server Redirect
Supabase implicit flow 的 token 放在 URL hash fragment（`#access_token=...`）。
Hash fragment **不會被送到 server**，所以 server-side redirect 會丟掉 token。
如果 callback route 做 redirect，client-side 的 `detectSessionInUrl` 可能來不及讀取 token。

### 建議
- callback route 回傳一個 HTML 頁面（而非 redirect），讓 client-side SDK 先讀取 hash 中的 token
- 或改用 PKCE flow（`flowType: 'pkce'`），token 透過 authorization code 在 server-side 交換，不依賴 hash fragment

## 相關檔案
- `frontend-v2/src/app/auth/callback/route.ts` — OAuth callback handler
- `frontend-v2/src/lib/supabase-browser.ts` — Supabase client 設定（flowType: implicit）
- `frontend-v2/src/components/AuthButton.tsx` — 登入按鈕（redirectTo 設定）

## 日期
2026-03-17
