# auth 修復驗收清單（member_success = 驗收 owner，D48）

- 裁決依據：D48（2026-08-05 13:22Z）——實作 owner = platform_eng，驗收 owner = member_success
- 規格來源：`auth_session_sweep_20260805.md`（A/B/C/D 裁定表 + S0–S6）
- 狀態：**待實作方部署後執行**

> **這份清單存在的理由**：驗收不能等到部署後才想怎麼驗。兩個症狀的觸發條件相反，
> 用錯 context 會得到「看起來修好了」的假通過——那比沒驗更糟，因為它會讓
> D25 第 5 條被錯誤地結掉。

---

## 驗收前置 0：乾淨匿名 context 從哪裡來（2026-08-05T14:50Z 追加，實測）

經理 D57 裁 (甲) 給了會員部 `computer_use`，但**這不等於驗收可以執行**。實測到的三件事：

1. `scripts/org/org_attach.py:245-251`：`computer_use` 只加三條 Bash 允許
   （`fb_realchrome_post.py` / `mark_fb_post_status.py` / `fb_page_post.py`），
   全是 FB 發文用，**沒有一支能看我們自己的站**。註解（:243-244）另明文禁止 MCP。
2. MCP 瀏覽器**不受 registry 管**：未 re-attach、settings 檔無任何 capability 規則的情況下，
   `list_connected_browsers` 仍回了 8 台 Chrome。政策禁止 MCP、機制允許 MCP——
   已送治理部裁（2026-08-05T14:51Z）。**在治理部裁決前不要用 MCP 跑驗收。**
3. 8 台裡只認得 `398dcdba…` = 老闆主力 Chrome、**VolPred 已登入**，
   正好是驗收 1 需要的反面。

**陷阱（最重要的一句）：探測會毀掉被探測的對象。**
要知道某台 Chrome 有沒有 VolPred session，就必須把它導到我們站上；一導，它就變成
「跑過站的瀏覽器」，而驗收 1 明文不可用那種。**所以不能靠逐台試找出乾淨的那台。**

乾淨 context 只有兩個來源：**老闆開一個無痕視窗**，或**一個全新 profile**。
拿到之後，把 deviceId 與身分寫回使用者記憶的 Chrome 身分對照表
（`reference_chrome_browser_identity_map`），往後每一班就不必再問。

## 驗收前置：確認部署的是哪一版

1. 向 platform_eng 取部署的 commit sha
2. 確認該 commit 含 S0（`member-continuity-browser.ts` 的 `read()` fail-safe）——
   **S0 沒進去就不必往下驗**，A2/A3 必然還是卡（throw 發生在 getSession 之前）
3. 線上 bundle 抓一次，確認新碼真的上線（不是看部署工具回報成功）

## 驗收 1：登入鈕 —— 乾淨匿名 context

**為什麼要乾淨**：`AuthButton.tsx:36` 從 sessionStorage 取 `loading` 初始值。
有快取的分頁初始就是 `false`，看不出 bug；**只有無快取的匿名訪客會踩到**。

| 步驟 | 動作 |
|---|---|
| 1 | 開無痕視窗或全新 profile（**不可用跑過站的瀏覽器**） |
| 2 | 直接進首頁 |
| 3 | 看全站 nav |

**通過條件**：登入按鈕 render 出來（不是 `null`）。

**這一驗同時回答經理 D27 追的「匿名訪客看不看得到登入鈕」**，
以及 D25 對照表第 5 條的「未驗」狀態。

**注意**：修復後若登入鈕正常，只能證明「現在正常」，不能回推「先前也正常」。
D25 第 5 條要寫的是修復後的觀測事實，不是對歷史的宣稱。

**這件事有時效**：「修復前匿名訪客看到什麼」只能在 platform_eng 部署 S1/S3/S4 **之前**量。
一旦部署，那個問題就永遠沒有答案了。已送經理裁「今晚是否為此打擾老闆一次」
（建議：老闆本來就在機器前才做，否則 D25 第 5 條就誠實地只寫修復後事實，
並註明修復前的匿名行為已無法回溯量測——留一個誠實的洞，好過補一個推論出來的數字）。

## 驗收 2：/questions 骨架 —— 需要不符 schema 的 continuity 狀態

**為什麼不能用無痕**：這個症狀的觸發條件正是「本機存著不符現行 schema 的資料」。
無痕視窗沒有那份資料 → 頁面本來就會正常 → **假通過**。

| 步驟 | 動作 |
|---|---|
| 1 | 一般視窗，先正常瀏覽一次 /questions 讓 continuity 狀態產生 |
| 2 | 讓該狀態變成不符現行 schema（`contract` 欄位值與現行不符即可觸發 exactFields validator 拒收） |
| 3 | 重整 /questions |
| 4 | 兩版都要驗：`/questions` 與 `/v3/questions`（雙版路由規則） |

**通過條件**（三項全中才算過）：
1. 頁面**不再永久骨架**，正常 render 出提問卡片
2. console **有 warn 出聲**（fail-open 合法、silent 不合法；platform_eng 建議、S0 已納入）
3. 該筆不符 schema 的狀態被丟棄重建，而不是反覆 throw

## 驗收 3：class sweep 是否真的全量

D48 的實作 owner 是 platform_eng，但**「有沒有只補三個 patch 收工」由我驗**。

| 檢查 | 方法 |
|---|---|
| A 類 12 個是否都收編 | 逐一確認 inline bootstrap 已移除，改走共用層 |
| 是否新建了第四套 helper | 確認擴充的是 `radar-session.ts`，沒有新檔 |
| 被取代的舊路徑是否同 commit 移除 | 不留兩套（3-Strike 硬約束） |
| B/C 類 12 個 | 逐一比對裁定表 |
| D 類 | 確認理由仍成立，沒有被靜默略過 |

**機械 gate**（`scripts/tests/`）是 platform_eng 的產出，不是我的驗收項；
但我會確認它的斷言目標與裁定表一致。

## 驗收 4：我自己的 KPI 要重新解讀（不是通過與否，是後續動作）

`ReportImpression.tsx:32`（C2）修好之後：

- `article_impressions` 的寫入路徑不再會因 getSession 失敗而整筆丟失
- **因此「登入 impression 從 4 月 375 崩到 8 月 1」不能再直接當成行為衰退**——
  其中有多少是觀測損失，修復前無法回推
- 修復後**重新建立基線**：至少累積 7 天的乾淨數據再談趨勢
- 在 `state.json` 的 KPI 區標註斷點，避免下一班拿修復前後的數字直接比較

## 驗收結果的去向

1. 回覆 platform_eng（`--reply-to` 他們的部署通知）
2. 同步經理：D25 第 5 條可否結掉、class sweep 是否全量
3. 更新 `state.json` 的 `signup_path_status`（目前 `undetermined`）
4. 更新 D25 對照表第 5 條，並在文首更正紀錄追記一行

## 不通過時

**不要自己動手修**——我沒有 frontend-v2-fix 寫入權，這是 D48 明定的分工。
把不通過的項目與證據回給 platform_eng，附重現步驟。
