# auth 修復驗收結果（member_success = 驗收 owner）

- 受驗對象：frontend-v2-fix commit 785ca70（platform_eng 2026-08-05T15:25Z 完工通知）
- 規格來源：`auth_session_sweep_20260805.md`（24 站裁定表 + S0–S6）
- 驗收依據：`auth_fix_acceptance_checklist.md`
- 驗收時間：2026-08-05 23:2x（台灣時間）
- **總結論（2026-08-06 更新）：驗收 1、驗收 3 通過；驗收 2 模組層與結構層通過、
  瀏覽器層仍無人能執行；我的裁定表漏了一站（C8）。**
- 更新紀錄：初版（2026-08-05 15:3x）寫「瀏覽器層兩項無人能執行」，
  在治理部裁定唯讀查看自家站不受 `computer_use` 管轄後已重測，**驗收 1 通過**。
  不受影響的部分：驗收 3 的全量核對、驗收 2 的斷言核對與結構性發現、C8 的裁定，
  全部維持原樣。

---

## 先講最重要的一句：漏的那一站是我漏的，不是實作方漏的

`components/OpsConsole.tsx:363-380` 是 **inline `getSession().then()`，沒有 `.catch`，
而且自帶一個 `onAuthStateChange`** —— 就是這次要消滅的那個模式。

**它不在我交出去的 24 站裁定表裡。** platform_eng 把我給的 24 站全部做完了，
這一站他們沒有理由知道。責任在規格方。

嚴重度：**低，但不是零**。
- `loading` 初始是 `false`（:330），所以**不 gate render**，不會白畫面也不會永久 spinner
- 但 getSession 一 reject → `sessionToken` 停在 null → `hasCredential` false →
  `:464 if (!hasCredential) return;` → **資料永遠不抓**
- 症狀是「看起來沒有資料」而不是「壞了」—— 與 C7（`app/admin/page.tsx:172`）
  完全同型的靜默失效
- 影響面：`/admin/ops`（`app/admin/ops/page.tsx:37` 掛載），內部 admin，
  非讀者、非會員、不碰付費漏斗

裁定：**補列為 C8**，優先序比照 C7（修，但不阻擋本輪完成定義）。

---

## 驗收 3：class sweep 是否全量 —— **通過**（24/24），另補列 C8

判準來自清單「有沒有只補三個 patch 收工由我驗」。

| 檢查 | 結果 | 證據 |
|---|---|---|
| A 類 12 站 inline bootstrap 已移除 | ✅ | `grep -rn "getSession()" src/` 後，AuthButton、questions 兩版、三個 My*Console、三個 Editorial*、三個 Admin*Console **全部只剩註解**，無呼叫 |
| 是否新建第四套 helper | ✅ 沒有 | 擴充的是 `lib/radar-session.ts`（`{token, user, status}` + `useRadarSession()`），無新檔 |
| 被取代的舊路徑同 commit 移除 | ✅ | 未見任何站點同時保留 inline bootstrap 與共用層（不留兩套） |
| B 類 5 站 | ✅ | 五個 Admin console 皆已從 getSession 呼叫點消失 |
| C 類 7 站 | ✅ | C1/C3/C4 各自有 rejection path（`MemberContinuityActions.tsx:90`、`ArticleEngagement.tsx:150`、`product-analytics-browser.ts:167`）；C2 `ReportImpression.tsx:38` 註明 reject 時仍匿名上報；C5/C6 兩版都在外層 `try` 內（`questions/page.tsx:178`、`v3/questions/page.tsx:196`）；C7 已收編 |
| D 類理由是否仍成立 | ✅ | D1/D2 不變；D3（`AdminUsersConsole.tsx:111`）仍是事件處理器內，未阻擋 |
| 雙版路由同步 | ✅ | `questions` 與 `v3/questions` 結構逐行對應 |
| **全量性** | ⚠️ | 見上：`OpsConsole.tsx:367` 為第 25 站，規格方漏列 |

### 約束 3（AuthButton 最優先）額外確認

規格要求「不能只靠 radar-session 收編就算完成，`:36` 的
`useState(!getCachedUser())` 初始值邏輯要一起檢視」。

已改成 `const loading = status === 'loading'`（`AuthButton.tsx:25`），
**sessionStorage 依賴整條移除**，並在 :20-24 留下為什麼不能依賴快取的說明。
這是規格裡最關鍵的一格，做到了。

---

## 驗收 2：/questions 骨架 —— **模組層通過；頁面層無人能在瀏覽器驗；但結構風險已大幅降低**

### 我做了什麼（不是看通過數）

platform_eng 回報 `member-continuity-browser.test.mjs` 22/22 過。
**通過數不是證據，斷言目標才是。** 我逐條讀了斷言：

| 清單的通過條件 | 對應斷言 | 結果 |
|---|---|---|
| 壞資料被丟棄重建 | `:228` 用 `contract: 'member-continuity.v0-from-a-previous-release'`，斷言 `state.contract === 'member-continuity.v1'` | ✅ |
| console 有 warn 出聲 | `:252` 斷言 `warnings.length >= 1` | ✅ |
| 不再反覆 throw | `:261` 壞 JSON 可存活、`:281` 拒絕持久化的裝置仍拿到可用物件 | ✅ |

S0 本體也與規格逐行相符：`readStored()` / `readFresh()` / 外層 `read()` 三層，
`console.warn`（:98、:110）、`removeItem`（:103）、storage 不可用時回記憶體內身分。

### 比瀏覽器實測更強的一項發現：失效路徑是被結構性消滅的

原始失效鏈是：`read()` throw → 整個 `useEffect` 在該行中斷 →
同一個 effect 裡後面的 `getSession()` **根本沒被呼叫** → `setAuthLoading(false)`
永不執行 → 骨架永久。

現在（`questions/page.tsx:64-76`、`v3/questions/page.tsx:84-94`）：

- `authLoading` 來自 `useRadarSession()` 的 `status`，**不再由任何 page-local effect 決定**
- `read()` 被移進**一個只負責還原草稿的獨立 `useEffect`**

**所以就算 `read()` 還會 throw，它也卡不住 `authLoading` 了** —— 兩者已經不在同一個
effect 裡。這比「加了 try/catch」強：現在有兩道**互相獨立**的防線，
S0（模組 fail-safe）與 S4（接線重構）任何一道失守，另一道仍成立。

### 誠實的殘餘

**沒有人在瀏覽器裡塞過壞值再訪問 /questions。** 上面全部是靜態與單元層證據。
它不能排除：`useRadarSession()` 自身在真實瀏覽器的某個時序下卡在 `loading`。
但那條路徑與 continuity 壞資料無關，屬於驗收 1 的範疇。

---

## 【2026-08-06 00:0x 追記】驗收 1 已由驗收方獨立驗證 —— **通過**

治理部 2026-08-05T15:33Z 裁定：`computer_use` 的政策範圍收窄為「代替老闆／VolPred 身分
對外部平台採取行動」，**唯讀查看 VolPred 自己的網站不在管轄範圍**，不需宣告 computer_use。
政策障礙消失後我重試，`navigate` 這次通過（上一班被 auto-mode classifier 擋下）。

**觀測（乾淨匿名 context、全新分頁）**

| 路由 | nav 登入鈕 | 提問卡 | 判定 |
|---|---|---|---|
| `/questions` | `button "登入"` **有 render** | 輸入框 +「Google 登入」完整 render，**未卡骨架** | ✅ |
| `/v3/questions` | v3 nav `button "登入"` **有 render** | 輸入框 +「Google 登入」完整 render，**未卡骨架** | ✅ |

context 合格性：顯示的是「登入」鈕而非帳號選單 → **無登入 session**；
分頁為本次新開 → **`sessionStorage` 乾淨**。這正是規格要求的匿名 context
（AuthButton 的 bug 只在無快取的匿名訪客身上發作）。

**因此 D25 第 5 條可以結**：修復後，匿名訪客在全新分頁看得到登入按鈕，兩版皆是。
但依清單第 36-37 行，這只陳述**修復後的觀測事實**，不回推歷史——
修復前的匿名行為在部署後已永久無法量測。

### 仍然做不到的：驗收 2 的壞資料路徑

`javascript_tool` 被權限層 deny（與 platform_eng 回報的「JS 執行被擋下」同一條）。
無法注入不符 schema 的 localStorage，因此**沒有人在瀏覽器裡走過那條路徑**。
上面兩版的 `/questions` 都正常 render，但那是**乾淨 context**——
依規格，這正是會「假通過」的那一種，不可拿來宣告驗收 2 通過。
殘餘風險評估不變（見下方結構性發現：兩道獨立防線）。

## 驗收 1（原始記錄，2026-08-05 15:3x）：登入鈕（乾淨匿名 context）—— **當時未由驗收方驗證**

platform_eng 自測通過（全新分頁匿名 → 正確 render「登入」）。
**但那是自驗，不是驗收**，D48 的分工正是為了避免這個。

我這邊執行不了，實測結果：

| MCP 動作 | 結果 |
|---|---|
| `list_connected_browsers` | ✅ 可用（回 8 台） |
| `tabs_context_mcp`（含建立群組） | ✅ 可用 |
| `tabs_close_mcp` | ✅ 可用 |
| `select_browser` | ❌ deny（don't ask mode） |
| `navigate` | ❌ **被 auto-mode classifier 擋下** |

**開得了分頁，載不了頁面。** 這與 platform_eng 回報的「瀏覽器工具 JS 執行被權限層擋下」
是同一道牆的兩面 —— **實作方與驗收方都被同一個權限層擋在瀏覽器外**，
所以「請對方用自己的方式驗一次」在目前的機制下對誰都不成立。

---

## 驗收 4：KPI 重新解讀（後續動作，非通過與否）

C2（`ReportImpression.tsx`）已修且 reject 時仍匿名上報。因此：

- `authed_impressions` 的歷史序列**存在觀測損失**，修復前後不可直接比較
- 「登入 impression 從 4 月 375 崩到 8 月 1」**不能再直接當成行為衰退**
- 修復後需重新建立基線（至少 7 天乾淨數據）再談趨勢
- 已在 `state.json` 標斷點

---

## 結論與去向

（本節於 2026-08-06 00:0x 依驗收 1 的實測結果更新；第 2、4 項的內容已改變。）

1. **可以宣告通過的**：驗收 3（24/24 + 約束 3）、驗收 2 的模組層與結構層、
   **驗收 1（2026-08-06 由驗收方在乾淨匿名 context 獨立驗證，兩版皆通過）**
2. **不能宣告通過的**：**只剩驗收 2 的瀏覽器層**（壞資料 context）——
   `javascript_tool` 被權限層 deny，無法注入不符 schema 的 localStorage
3. **新開的一項**：C8（`OpsConsole.tsx:367`），規格方漏列，已回報 platform_eng，
   對方回覆將與 F1/F2/F3 同批處理（同類 admin 站點問題）
4. **D25 第 5 條：可以結**。修復後匿名訪客在全新分頁看得到登入按鈕，
   `/questions` 與 `/v3/questions` 皆是。`signup_path_status` 由 `undetermined_after_fix`
   改為 `verified_present_after_fix`。**但只陳述修復後的觀測事實，不回推歷史。**
5. **修復前的匿名行為已永久無法量測**（部署已發生）—— 誠實留洞，不補推論值
