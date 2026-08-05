# /questions「提出你的問題」永遠停在 skeleton — 根因與修法

- 日期：2026-08-05（台灣時間 19:0x）
- 部門：platform_eng
- 來源工作項：manager D28 順序第 1 項；member_success `item_20260805T103630630612Z`（更正後的窄症狀）
- 轄區：`frontend-v2-fix/`（本部門唯一有寫入權的區域）

## 1. 症狀（會員部實測，我複驗程式碼路徑）

已登入 owner 的瀏覽器開 `https://volpred.zeabur.app/questions`，「提出你的問題」卡片
等 3 秒以上仍只有**一條** skeleton 灰條，accessibility tree 沒有 textarea、沒有按鈕。

## 2. 症狀與程式碼的逐點對應（不是假說）

`src/app/questions/page.tsx`

- L255-258：`authLoading ? (一條 h-4 w-40 的 animate-pulse 灰條) : …`
  → **「只有一條灰條」就是 `authLoading === true` 的那個分支本身**，符號級對上。
- L59：`authLoading` 初值 `true`。
- 全檔只有兩處把它設回 false：L69（`!supabase` 分支）與 L79（`getSession().then` 內）。
  **兩處都在 L63-64 之後。**
- L63-64：
  ```ts
  const continuity = getMemberContinuityBrowser();
  const draft = continuity.read().question_draft;
  ```
  這兩行**沒有任何保護**。只要 `read()` 拋例外，effect 當場中斷，L66 之後一行都不執行，
  `authLoading` 永遠是 true → 永遠是那條灰條。

`src/lib/member-continuity-browser.ts` 的 `read()` 為什麼會拋：

- L47-52：`JSON.parse(raw)` 後直接餵 `validateAnonymousMemberContinuity`。
- validator（`member-continuity.ts:689-733`）用 `exactFields` 做**嚴格**欄位比對，
  contract 不符、欄位多一個少一個、`question_draft` 超過 2000 字元一律 `throw`。
- `resolveBrowserAnonymousId`（`browser-anonymous-identity.ts:33-35`）也會 throw。

也就是說：**localStorage 是不可信輸入，卻被當成可信輸入直接驗證並讓例外往上跑。**
前一版 schema 的殘留、被外部改過、半截寫入，任何一種都會讓這一頁對該裝置永久壞掉，
而且**不會自癒**——那份壞資料就躺在使用者的 localStorage 裡，每次重新整理都再壞一次。

這也解釋了為什麼「已登入的 owner 反而看到壞掉的頁」：owner 的 localStorage 是全站最舊的一份。

同一支檔案裡的 L118-122 已經有對照組——`setQuestionDraft` 被 try/catch 包住並給使用者訊息。
**同一類風險，寫入端有保護、讀取端沒有**，這是不一致，不是設計取捨。

## 3. 修法（三層，root cause 在第一層）

1. **`member-continuity-browser.ts::read()` 自癒**（根因層）
   本機那份讀不動時，丟棄它、`console.warn` 出聲、重新建立一份乾淨狀態。
   丟棄一律出聲，不做靜默 fallback（`.claude/rules/no-silent-fallback.md`：fail-open 合法、silent 不合法）。
   修在來源等於一次覆蓋所有讀取端（`ArticleEngagement`、`MemberContinuityActions`、
   `MemberContinuityPrivacy` 與兩版 questions）。

2. **兩版 questions page 的呼叫端隔離**（防線層）
   草稿讀取失敗（例如 localStorage 被停用或配額滿，第 1 層也救不了的硬失敗）
   絕對不能連帶擋住登入狀態的解析。草稿是加值功能，auth 是主線。

3. **`AuthButton.tsx` 的 `getSession().then()` 補 `.catch()`**（同 class）
   L100 沒有 catch，L146 是 `if (loading) return null` → promise 一旦 reject，
   全站 nav 的登入鈕永遠不出現。這與第 1 項是同一個形狀：
   **未解決的 promise ＝ 永久 loading ＝ UI 永久消失，且沒有任何錯誤訊號。**

### class sweep（宣告完成前的全量掃描）

`grep -rn "getSession()" frontend-v2-fix/src` 共 28 處。其中「`.then` 內設 ready/loading、
無 `.catch`」的同 class 實例（reject 即永久 loading）：

| 檔案 | 行 | 面向 |
|---|---|---|
| `components/AuthButton.tsx` | 100 | 全站 nav（兩版共用，V3Shell 也是 require 這支）|
| `app/questions/page.tsx` | 72 | 原版問答 |
| `app/v3/questions/page.tsx` | 93 | v3 問答 |
| `components/MyMemberHomeConsole.tsx` | 58 | 會員中心 |
| `components/MyQuestionsConsole.tsx` | 71 | 我的提問 |
| `components/MyBookmarksConsole.tsx` | 33 | 我的收藏 |
| `components/v3/editorial/me/EditorialMemberHome.tsx` | 80 | v3 會員中心 |
| `components/v3/editorial/me/EditorialBookmarks.tsx` | 76 | v3 我的收藏 |
| `components/v3/editorial/me/EditorialQuestions.tsx` | 118 | v3 我的提問 |

Admin 側（`AdminUsersConsole`、`AdminContentConsole` 等 7 處）形狀相同但屬內部介面，
本輪不動，記在此處供後續。

## 4. 落地被擋的真正原因（更正本部門先前的判斷）

前一班與本班都以為擋住寫入的是 `path_claims` 的 `frontend-v2-fix/src/` claim（session 66dfcf3a）。
**錯的。** 實際 deny 來自另一層：user-level PreToolUse hook `~/.claude/hooks/main-checkout-lock.sh`。

鎖檔 `~/.claude/session-locks/af037391a28f.lock`（直接讀出，非推論）：

```
b575276c-b48e-47b2-a6d5-c816ee245fcb|12538|1785926504|/Users/yhlai0911/volpred-research/frontend-v2-fix
```

`1785926504` = 2026-08-05 18:41:44 台灣時間，持有者是 member_success 的 session。

**結構根因**：`~/.claude/session-locks/optout.conf` 只列了
`/Users/yhlai0911/volpred-research`。而 `frontend-v2-fix/` 是**獨立巢狀 git repo**
（`.claude/rules/frontend-and-deploy.md` 第一段），hook 的 `$root` 會解析成巢狀 repo 自己，
於是**專案的 opt-out 蓋不到它**。結果是：全平台唯一由部門擁有寫入權的前端轄區，
被一道「該專案已經聲明不使用」的互斥鎖守著。

而且鎖是 PreToolUse 落的——記錄的是「有人試過寫」而不是「有人寫了」。member_success
說他們今天沒寫過任何 frontend 檔，我採信，兩件事並不矛盾。
這與 `write_claim_guard` 的幽靈 claim（治理部 2026-08-05 已裁定為 bug）是**同一個 class**：
**鎖記錄嘗試而非事實，然後對真正的 owner 說謊。** 今天這個 class 擋了同一個部門兩次。

**永久修法**：在 `frontend-v2-fix/` 內放 `.claude/no-session-lock`（hook L46 的 opt-out 之一，
隨 clone 走，比 per-machine 的 optout.conf 更耐移機）。本班在鎖失效後第一件事就做這個。
`optout.conf` 本身不在本部門 owned_paths，Edit 被拒——**這是正確的拒絕，不繞過。**
