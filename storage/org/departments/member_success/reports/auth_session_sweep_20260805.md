# auth session bootstrap：全量裁定表

- 部門：member_success（經理裁決指定的唯一實作 owner）
- 裁決依據：`item_20260805T110542557251Z_auth-session-catch-owner-gate-f`（P1 decision）
- 掃描範圍：`frontend-v2-fix/src/**/*.{ts,tsx}`
- 掃描時間：2026-08-05 19:1x（台灣時間）
- 判準（經理指定）：**該站點的 promise rejection 會不會讓 loading 永久 true 而 gate 住 render**

---

## 先講三個掃描結果，因為它們改變了問題的形狀

### 1. 全前端只有一處 `.catch` 掛在 `getSession()` 上

`grep -rn "\.catch" src/` 全表 47 筆，逐一看落點：**只有 `radar-session.ts:99` 那一筆
掛在 `getSession()` 的 promise 鏈上**。其餘全部掛在 `res.json()`、`fetch()`、
`continuity.merge()`、`fs.readdir()` 等別的 promise 上。

也就是說：**27 個站點裡，除了共用層自己，沒有任何一個有 rejection path。**
這證實了經理的判定——根因不是「某三個地方忘了加 `.catch`」，是共用層存在但沒人走。

### 2. 最高優先項確認成立，而且比預期更精準

`AuthButton.tsx:100` 無 catch、`:146` `if (loading) return null`。
但關鍵在 **`:36`**：

```ts
const [loading, setLoading] = useState(!getCachedUser());
```

`getCachedUser()` 讀的是 **sessionStorage**（不是 localStorage）。所以：

- **匿名訪客／新分頁** → 無快取 → `loading` 初始 **true** → getSession 一 reject，
  全站 nav 登入鈕永久不 render
- **同一分頁內已載入過的使用者** → 有快取 → `loading` 初始 false → 不受影響

**方向與先前的假說相反**：受害者是匿名訪客，不是帶舊資料的老使用者。
這一條直接關係到 D25 對照表第 5 列與 D27。

### 3. `/questions` 的永久 skeleton 是**另一條路徑**，不是同一個觸發條件

`questions/page.tsx:255` 在 `authLoading` 為 true 時 render `animate-pulse` 骨架——
就是老闆看到的那個。但它卡住的成因不必經過 getSession：

```ts
useEffect(() => {
  const continuity = getMemberContinuityBrowser();
  const draft = continuity.read().question_draft;   // ← 第 64 行，同步呼叫
  ...
  supabase.auth.getSession().then(...)              // ← 第 72 行
```

`read()`（`member-continuity-browser.ts:46-52`）裡是
`JSON.parse(raw)` + `validateAnonymousMemberContinuity(...)`，**兩者都會同步 throw
且沒有 try/catch**。localStorage 有壞掉或舊 schema 的資料 → `read()` throw →
整個 `useEffect` 在第 64 行中斷 → 第 72 行的 getSession **根本沒被呼叫** →
`setAuthLoading(false)` 永不執行 → 骨架永久。

而且 `authLoading` 初始是無條件 `useState(true)`，與有無快取無關。

**兩個症狀的觸發條件不同，驗收方式也必須不同**：

| 症狀 | 觸發條件 | 正確驗收 context |
|---|---|---|
| nav 登入鈕不 render | getSession 真的 reject | 乾淨匿名 context（無 sessionStorage） |
| /questions 永久骨架 | localStorage 有壞掉的 continuity 資料 | **帶著壞資料**的 context，或手動塞壞值 |

用乾淨無痕視窗驗 /questions 會看起來「好的」——因為壞資料被清掉了。這一點與平台工程部
先前的驗收計畫相反，已同步給他們。

---

## 全量裁定：27 個站點

（`grep -rn "getSession()"` 命中 31 筆，扣掉 `radar-session.ts` 的 3 筆註解與 1 筆自身實作）

### A 類：rejection 會 gate 住 render —— 必修（12 個）

| # | 站點 | gate 位置 | 影響面 |
|---|---|---|---|
| A1 | `components/AuthButton.tsx:100` | `:146 if (loading) return null` | **最高**：全站 nav 登入鈕，付費漏斗入口 |
| A2 | `app/questions/page.tsx:72` | `:255 authLoading ? <skeleton>` | 高：提問入口（原版） |
| A3 | `app/v3/questions/page.tsx:93` | `:351 authLoading ? <skeleton>` | 高：提問入口（v3 版） |
| A4 | `components/MyQuestionsConsole.tsx:71` | `:101 if (!ready)` | 中：會員自己的提問頁 |
| A5 | `components/MyBookmarksConsole.tsx:33` | `:63 if (!ready)` | 中：收藏頁 |
| A6 | `components/MyMemberHomeConsole.tsx:58` | `:88 if (!ready)` | 中：會員首頁 |
| A7 | `components/v3/editorial/me/EditorialQuestions.tsx:118` | `:153 if (!ready)` | 中：v3 版 A4 |
| A8 | `components/v3/editorial/me/EditorialBookmarks.tsx:76` | `:111 if (!ready)` | 中：v3 版 A5 |
| A9 | `components/v3/editorial/me/EditorialMemberHome.tsx:80` | `:115 if (!ready)` | 中：v3 版 A6 |
| A10 | `components/AdminAnalyticsConsole.tsx:200` | `:219 if (!ready)` | 低：內部 admin |
| A11 | `components/AdminHealthConsole.tsx:56` | `:86 if (!ready)` | 低：內部 admin |
| A12 | `components/AdminSchedulesConsole.tsx:99` | `:118 if (!ready)` | 低：內部 admin |

A1–A9 全部面向讀者或會員。A4–A9 是 **同一頁的兩版**（雙版路由規則），必須同步改。

### B 類：rejection 讓 `loading` 卡在 true，但 gate 的是資料區不是整頁（5 個）

| # | 站點 | 說明 |
|---|---|---|
| B1 | `components/AdminContentConsole.tsx:338` | `loading` 初始 true，`:393 setLoading(false)` 在 then 內 |
| B2 | `components/AdminQuestionsConsole.tsx:209` | 同上，`:276` |
| B3 | `components/AdminUsersConsole.tsx:142` | 同上，`:193` |
| B4 | `components/AdminStrategiesConsole.tsx:197` | 同上，`:260` |
| B5 | `components/AdminPapersConsole.tsx:175` | 同上，`:223` |

**仍要修**：症狀是永久 spinner 而非白畫面，但機制與 A 類完全相同，只是 blast radius
小。全部是內部 admin，優先序低於 A1–A9，但不列為「不適用」。

### C 類：rejection 不 gate render，但會靜默吃掉功能（6 個）

| # | 站點 | 說明 | 裁定 |
|---|---|---|---|
| C1 | `components/MemberContinuityActions.tsx:64` | `void ....then(async ...)`，前面加了 `void` 但**沒有 catch**——rejection 變成 unhandled rejection | 修：加 rejection path，token 設 null |
| C2 | `components/ReportImpression.tsx:32` | `await getSession()` 取 header；throw 則整個 impression 上報失敗 | 修：這是 `authed_impressions` 的來源，本部門 KPI 直接依賴它 |
| C3 | `components/ArticleEngagement.tsx:147` | `await getSession()` 設 viewerSession | 修 |
| C4 | `lib/product-analytics-browser.ts:161` | `await getSession()` 組 auth header | 修 |
| C5 | `app/questions/page.tsx:182` | 送出提問時 `await getSession()`，在 submit handler 內 | 修：外層需有 try/catch 才不會吃掉錯誤訊息 |
| C6 | `app/v3/questions/page.tsx:212` | v3 版 C5 | 修 |
| C7 | `app/admin/page.tsx:172` | 無 loading 旗標，rejection 讓 `accessToken` 停在 null → `:192 hasAuth` 恆 false → 所有授權 SWR 不發，頁面看起來像「沒資料」而非「壞了」 | 修 |

**C2 值得單獨講**：它是 `article_impressions` 寫入路徑。本部門的 KPI
`authed_impressions_2026_07 = 44`、`2026_08_to_date = 1` 全部來自這張表。
如果 getSession 在某些使用者身上 reject，**這些人的閱讀從來沒有被記錄過**——
那意味著「登入 impression 從 4 月 375 崩到 8 月 1」這個我一直當成行為指標的數字，
可能有一部分是這個 bug 造成的觀測損失，不是真實的行為衰退。
這一條修好之後，該指標的歷史序列需要重新解讀，不可直接沿用結論。

### D 類：不適用 —— 逐一說明理由（4 個）

| # | 站點 | 不適用理由 |
|---|---|---|
| D1 | `lib/radar-session.ts:95` | **它就是 enforcement owner 本身**，已有 `:99 .catch` 正確落到 anonymous |
| D2 | `lib/radar-session.ts:7,14,119` | 註解文字，非程式碼站點 |
| D3 | `components/AdminUsersConsole.tsx:110` | `await getSession()` 在事件處理器（非 mount），已在 async 函式內；不 gate 初始 render。仍建議順手加 try/catch，但不阻擋本次完成定義 |

**原本列為 D3 的 `app/admin/page.tsx:172` 已讀完，改判 C 類（見 C7）**——
它沒有 loading 旗標，rejection 只讓 `accessToken` 停在 null，頁面照 render，
但 `:192 hasAuth` 恆為 false（除非手動貼 token），所有需要授權的 SWR 全部不發，
admin 頁看起來像「沒有資料」而不是「壞了」。典型的靜默失效，不是不適用。

---

## 實作方案（依經理三條硬約束）

### 約束 1：不得新建第四套 session helper

`radar-session.ts` 目前只暴露 `{ token, status }`，但 A1–A9 多數站點還需要
`session.user`（id / email / user_metadata）。**做法是擴充它，不是繞過它**：

- 在既有 singleton 上增加 `user` 欄位，`RadarSessionState` 變成
  `{ token, user, status }`
- 新增 `useRadarSession()` 回傳完整狀態；`useRadarAccessToken()` 保留為薄封裝，
  既有 radar 元件不必動
- 既有的 `.catch(() => anonymous)`（`:99`）自動涵蓋所有新收編的站點——
  這正是「共用層已經對了，問題是沒人走」的解法

### 約束 2：class sweep 全量

A（12）+ B（5）+ C（7）= **24 個站點要改**，D1/D2 不適用，D3 建議但不阻擋。
每個站點的 inline bootstrap（`getSession().then` + 自己的 `onAuthStateChange`）
**同 commit 移除**，不留兩套。

### 約束 3：AuthButton 最優先

A1 先做。但**它不能只靠 radar-session 收編就算完成**：`:36` 那個
`useState(!getCachedUser())` 的初始值邏輯要一起檢視，因為匿名訪客初始 true 正是
放大這個 bug 的原因。

### 額外一項（不在經理清單，但同一根因）

`member-continuity-browser.ts:46` 的 `read()` 必須對壞資料 fail-safe：
`JSON.parse` / validate throw 時視為「沒有資料」並重置，而不是把例外丟給呼叫端的
`useEffect`。**不修這一條，A2/A3 修了也還是會卡**——因為 throw 發生在 getSession
之前，rejection path 根本輪不到。

---

## 逐站點改動規格（讓實作機械化，也讓接手者不必重推）

### S0：`lib/member-continuity-browser.ts` — `read()` fail-safe

把現行 `read()` 更名為 `readStored()`（內容不動），新增外層 `read()`：

```ts
const read = (): AnonymousMemberContinuity => {
  try { return readStored(); }
  catch {
    try { adapters.storage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    try { return readFresh(); }          // 重建一份乾淨狀態並寫回
    catch {
      // storage 本身不可用（Safari 無痕／配額／封鎖 cookie）：回記憶體值，
      // 讓呼叫端仍拿到物件而不是例外
      return Object.freeze({
        contract: 'member-continuity.v1' as const,
        anonymous_id: adapters.randomId(),
        intents: Object.freeze([]),
      }) as AnonymousMemberContinuity;
    }
  }
};
```

`readFresh()` 即現行 `read()` 尾段（`resolveBrowserAnonymousId` + `write` 空狀態）抽出。
**這一項必須先做**：不做則 A2/A3 修了也還是卡，因為 throw 發生在 getSession 之前。

### S1：`lib/radar-session.ts` — 擴充為完整 session（不新建 helper）

- `RadarSessionState` 由 `{ token, status }` 擴為 `{ token, user, status }`，
  `RadarSessionUser = { id, email?, name?, avatar? }`
- `stateForToken()` 改為 `stateForSession(session)`，同時取 `access_token` 與 `user`
- `setState` 的 dedup 條件維持比對 token + status（user 隨 token 變動，不需另比）
- 新增 `useRadarSession(): RadarSessionState`；`useRadarAccessToken()` 保留為薄封裝
  （回傳 `{ token, status }`），既有 radar 元件一行都不用改
- 既有 `:99 .catch(() => anonymous)` 自動涵蓋所有新收編的站點——**這就是全部的修復**

### S2：A4–A9（六個 console，完全同構）

現行模式：
```ts
supabase.auth.getSession().then(({ data }) => {
  setAccessToken(data.session?.access_token ?? null);
  setReady(true);
});
const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
  setAccessToken(session?.access_token ?? null);
  setReady(true);
});
```
改為：
```ts
const { token: accessToken, status } = useRadarAccessToken();
const ready = status !== 'loading';
```
整段 `useEffect` 與 `useState` 刪除（同 commit 移除，不留兩套）。
`if (!ready)` 的 gate 不動——它現在會因為共用層的 catch 而正確解除。

適用：MyQuestionsConsole、MyBookmarksConsole、MyMemberHomeConsole、
EditorialQuestions、EditorialBookmarks、EditorialMemberHome。

### S3：A1 `AuthButton.tsx`

改用 `useRadarSession()` 取 `{ user, token, status }`，刪掉自己的 getSession +
onAuthStateChange。`loading` 改由 `status === 'loading'` 推導，
**`:36` 的 `useState(!getCachedUser())` 一併移除**——sessionStorage 快取仍可留作
首屏 avatar 的樂觀顯示，但不得再作為 loading 初始值的依據（它正是讓匿名訪客
初始 true 的原因）。`refreshAdminState` 的 token 去重邏輯保留。

### S4：A2/A3 `questions` 兩版

- `authLoading` 改由 `status === 'loading'` 推導
- `user` 改讀共用層的 `user`
- `continuity.read()` 因 S0 已不會 throw，保持原位即可
- `continuity.merge(...)` 的既有 `.catch` 保留（它掛的是別的 promise，本來就對）
- **雙版路由規則**：兩版同步改，改完兩版都要線上驗證

### S5：B 類 5 個 admin console

同 S2 模式，但 gate 的是資料區而非整頁。`loading` 由 `status === 'loading'` 推導。

### S6：C 類 7 個

- C1 `MemberContinuityActions.tsx:64`：`void ....then(...)` 補 `.catch(() => setAccessToken(null))`
- C2 `ReportImpression.tsx:32`、C3 `ArticleEngagement.tsx:147`、
  C4 `product-analytics-browser.ts:161`：`await getSession()` 包 try/catch，
  失敗時以匿名 header 繼續送（**不可整個放棄上報**——C2 是 KPI 來源）
- C5/C6 `questions` submit handler：包 try/catch，失敗顯示可操作的錯誤訊息
- C7 `admin/page.tsx:172`：`.then` 補 `.catch(() => setAccessToken(null))`

## 完成定義（經理指定）

改完 + build 過 + 部署 + **線上實際驗證登入鈕會 render**。
本表列的驗收要用兩種 context（見上方表格），不可只用無痕視窗。

## 不歸本部門

`scripts/tests/` 的機械 gate 由平台工程部撰寫（經理已指派）。本表的 A/B/C/D 分類
即為該 gate 的斷言目標，已同步給他們。
