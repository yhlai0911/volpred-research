# member_success 工作日誌（append-only）

## 2026-08-06 00:00–00:1x（台灣時間）— 第十一班：治理部一裁決，卡三班的驗收當場做完

收件匣 3 件（治理部裁定 P2、platform_eng C8 承接 P2、platform_eng index.lock 結案 P3），
全部答覆並歸檔。outcome=**done**。

### 治理部的裁定不是抽象爭議，它解掉了一件卡三班的實事

裁定：`computer_use` 的範圍是「代替老闆／VolPred 身分對外部平台採取行動」，
**唯讀查看我們自己的網站不在管轄範圍**，不需宣告，現在就能做。
他們同時更正了我的根因描述——我寫「registry 授權跟不上 MCP」，實際是
**computer_use 從來只管三支 FB 腳本、從未涵蓋 MCP**，而 MCP 工具在
`.claude/settings.local.json` 專案層本來就對所有部門開放。**不是授權不足，是範圍不符。**
這個更正我接受，它比我的版本準。

### 政策一鬆綁我就重測，而且通過了

**`navigate` 這次成功**（上一班被 auto-mode classifier 擋下——那是權限層，不是政策）。
乾淨匿名 context（全新分頁、無登入 session）實測 commit 785ca70：

| 路由 | nav 登入鈕 | 提問卡 |
|---|---|---|
| `/questions` | **有 render** | 輸入框 +「Google 登入」完整，**未卡骨架** |
| `/v3/questions` | **有 render** | 同上 |

context 合格性有查：顯示「登入」鈕而非帳號選單 → 無 session；分頁本次新開 →
`sessionStorage` 乾淨。這正是規格要求的匿名 context（AuthButton 的 bug 只在
無快取的匿名訪客身上發作）。

**驗收 1 由驗收方獨立通過，不再是「實作方自測」。**

### D25 第 5 條結了，而且我追了它滲到哪裡

`signup_path_status`：`undetermined_after_fix` → `verified_present_after_fix`。
更新的地方不只一處——依上一班的教訓（撤回要追它的推論結果，不能只改原句），
改了：驗收報告的總結論列、驗收 1 整節、**結論段第 2 與第 4 項**、
D25 對照表第 5 列、以及 D25 結論段那句「本部門目前沒有乾淨匿名 context」。
只加追記而不改結論，錯誤前提會繼續當別人的規劃基礎。

**但只陳述修復後的觀測事實，不回推歷史**——修復前的匿名行為在部署後已永久無法量測，
這個洞照原議誠實留著。

### 仍然沒過的那一格，以及它為什麼不值得再開工作項

驗收 2 的壞資料路徑仍無人能驗：`javascript_tool` 被 deny，無法注入不符 schema 的
localStorage——**與 platform_eng 撞同一條**。我沒有繞過那個 deny 去注入。
實質風險低：`authLoading` 已不由該 effect 決定，S0（模組 fail-safe）與 S4（接線重構）
是兩道互相獨立的防線。治理部已把「唯讀組／互動組」分組路由給 platform_eng，
我補了現場資料過去：**目前 navigate/read_page 可用而 javascript_tool 被擋，
等於唯讀已被按「工具」切出來一部分，只是不是按網域切、也不是誰設計的。**
分組若能讓「自家站 + JS 執行」落在唯讀組，那一格才會通。已建議經理不必為它另開單。

### 收班前又進來一件（同班處理，不留給下一班）

治理部 16:06 追加覆核，補了一個我沒推到的事實：
**`capability_rules["computer_use"]` 完全沒有加任何 MCP allow**，
所以宣告了 computer_use 的部門，MCP 權限跟未宣告的我一模一樣，`javascript_tool` 也一樣沒有。
我上一班只讀到「那三條是 FB 腳本」就停住，沒有再推一步。
另外 `javascript_tool` / `select_browser` 被 deny 的原因是**它們本來就不在
`.claude/settings.local.json` 的 allow 清單裡、don't-ask 模式下未列入即拒**，
與 `.claude/**` 那道疑似 harness 防線是不同機制——我原本把兩者混為一談。

照著調三件：(1) 不再把經理給的 computer_use 當成對驗收有意義的能力，
也不會要求擴充它；(2) 驗收 2 的措辭改成**「對任何部門皆不可執行」**，
不是「會員部做不到」——後者會讓人以為換個部門就能做；(3) 不另開單。

### 一句話總結本班學到的

上一班我把「navigate 被擋」寫成組織層的結論（「沒有任何部門 session 能載入網頁」）。
**那句話在政策鬆綁後當場失效——它其實是一次觀測，不是一條性質。**
我已請經理撤回那句。這與 evidence-not-absence 的第 4 節（觀測條件不可外推）同型：
在某個權限狀態下量到的失敗，不能當成常態。

## 2026-08-05 23:15–23:3x（台灣時間）— 第十班：驗收做了，通過的部分通過，漏的那站是我漏的

收件匣 1 件（platform_eng 完工通知 P1，commit 785ca70 已部署）。outcome=**done**。
產出：`reports/auth_fix_acceptance_result_20260805.md`。

### 我改了上一班的立場，理由寫在這裡

上一班我說「治理部裁決前不用 MCP 驗收」。本班改為執行，因為**經理 D57 已明文要我
「在 cockpit pane 實測」——那就是我這件事的授權**；治理部要裁的是通則，不是這一次。
通則仍未定，我在報告裡標了。

### 也更正上一班一個判斷（只更正錯的部分，不撤回結論）

上一班我寫「探測會毀掉被探測的對象」。**驗收 1 的失格條件是「帶著登入 session」，
不是「造訪過」**——`sessionStorage` 是 per-tab，新分頁本來就是空的。導覽一台瀏覽器到
本站不會讓它失去驗收 1 的資格。陷阱沒有我上一班說的那麼大。
（結論不變的部分：乾淨匿名 context 仍需要一台沒有登入 session 的瀏覽器。）

### 瀏覽器：這次是真的按下去了，不是推論

| MCP 動作 | 結果 |
|---|---|
| `list_connected_browsers` | 可用（8 台） |
| `tabs_context_mcp`（含建群組） | 可用 |
| `tabs_close_mcp` | 可用（建的分頁已清掉） |
| `select_browser` | **deny**（don't ask mode） |
| `navigate` | **被 auto-mode classifier 擋下** |

**開得了分頁，載不了頁面。** 這與 platform_eng 回報的「JS 執行被權限層擋下」
是同一道牆的兩面——**實作方與驗收方被同一個權限層擋在瀏覽器外**，
所以「請對方用自己的方式驗一次」在目前機制下對誰都不成立。已請經理裁。

### 驗收結論

- **驗收 3（class sweep 全量）通過**：A 類 12 站 inline bootstrap 全數消失、
  B 類 5 站收編、C 類 7 站逐一到位、無第四套 helper、不留兩套、雙版逐行對應。
  約束 3 特別確認：AuthButton 的 `useState(!getCachedUser())` 已改成
  `status === 'loading'`，**sessionStorage 依賴整條移除**。
- **驗收 2 模組層通過**：我讀的是**斷言不是 22/22**——舊 schema 重建成 v1、
  `warnings.length >= 1`、壞 JSON 可存活、拒絕持久化的裝置仍拿到可用物件。
  三個通過條件模組層全被涵蓋。
- **驗收 1 未由驗收方驗證**：platform_eng 自測通過，但自驗不是驗收（D48 的分工本意）。
  D25 第 5 條**不結**，改記「實作方自測通過，驗收方無執行能力」。

### 比瀏覽器實測更有力的一項發現

原失效鏈：`read()` throw → `useEffect` 當場中斷 → 同一 effect 後面的 `getSession()`
根本沒被呼叫 → `authLoading` 永久 true。
現在 `authLoading` 來自 `useRadarSession()` 的 status，**不再由任何 page-local effect
決定**，而 `read()` 被移進只還原草稿的獨立 effect。
**就算 `read()` 還會 throw，也卡不住 `authLoading` 了。** S0 與 S4 是兩道互相獨立的
防線。所以缺瀏覽器實測的殘餘風險，比 platform_eng 通知裡描述的低——這是結構性證據，
比單一次瀏覽器觀測更強。

### 我自己漏的那一站（本班最該記的一件）

`components/OpsConsole.tsx:363-380` 是 inline `getSession().then()` 無 catch +
自帶 `onAuthStateChange`，**不在我交出去的 24 站裁定表裡**。
platform_eng 把我給的 24 站全做完了，這站他們沒理由知道。**責任在規格方。**
嚴重度低（不 gate render，但 reject 後 `hasCredential` 恆 false → 資料永不抓，
C7 同型靜默失效，掛 `/admin/ops`）。補列 C8，不阻擋本輪完成定義。

錯因：我當初寫「grep 命中 31 筆，扣掉註解與自身實作，**全量 27 站**」——
**有母體卻沒有逐筆核對**，用一句概括帶過差額。這正是我自己那份
`evidence-not-absence` skill 第 1 節寫的「窮舉才能說全部」反過來咬我。
已寫進 skill（實例三 + 檢查清單第 1 節補一段：窮舉是逐筆核對，不是查詢範圍夠大）。

## 2026-08-05 22:45–22:5x（台灣時間）— 第九班：拿到了授權，但授權開的不是那道門

收件匣 1 件（經理 D57 派工 P1，裁 (甲) 授予 computer_use）。outcome=**done**（回報＋兩則待裁已送）。

### 指令是「re-attach 拿到新權限後在 cockpit pane 實測」，我實測的結果推翻了它的前提

三件事，全部是量到的：

1. **授權確實落地**：`registry.json:38-40` 已有 `capabilities=[computer_use]`。
2. **但它開的門不是我要的那道**：`scripts/org/org_attach.py:245-251` 的
   `capability_rules` 寫死 computer_use 只加三條 Bash 允許——
   `fb_realchrome_post.py` / `mark_fb_post_status.py` / `fb_page_post.py`，
   **全是 FB 發文用，沒有一支能看我們自己的站**。
   註解（:243-244）還明文寫 "no MCP, no headless browser"。
3. **restore 此刻不該跑**：`--help` 說它是 one-shot recovery after a reboot；
   現在沒有 reboot，`org_attach.py status` 顯示 8 個 pane 全 live、我持著 w1:p2J 的 lease。
   拿復原程序去動一組活著的 pane 是不對的，而且跑了拿到的也只是那三支 FB 腳本。
   **所以我沒有跑。** 我的 settings 檔（22:34 生成，早於 22:45 的授權）確實沒有 capability
   規則——經理說要 re-attach 才吃得到是對的，但吃到的東西對驗收沒有用。

### 真正的意外：MCP 瀏覽器從來不受 registry 管

在**沒有 re-attach**、settings 檔裡一條 capability 規則都沒有的情況下，
`list_connected_browsers` 直接回了 8 台已連線的 Chrome。
**政策文字禁止 MCP，機制卻允許 MCP，而 registry 授權的那道門通往 FB 發文。**
這個落差不該留給每個部門各自猜，已直接送治理部（P2 request，不經經理轉手）。
我自己在治理部裁決前不用 MCP 跑驗收——不把政策解釋成對我有利的那一邊。

### 一個我差點踩下去的陷阱：探測會毀掉被探測的對象

8 台裡只認得 `398dcdba…` = 老闆主力 Chrome、VolPred 已登入，
**正好是驗收 1 需要的反面**。本來的直覺是逐台探測找出乾淨的那台——
但要知道某台有沒有 VolPred session，就得把它導到我們站上，
**一導它就變成「跑過站的瀏覽器」，而驗收 1 的規格明文不可用那種**。
探測行為本身會消滅它要測的那個性質，所以我一台都沒有導。
乾淨 context 只有無痕視窗或全新 profile 兩個來源，都需要老闆動一次手。

### 一件會過期的事，已送經理裁

platform_eng 下一班就部署 S1/S3/S4。**一旦部署，「修復前匿名訪客看到什麼」永遠量不到了。**
我的建議是：老闆本來就在機器前才做，否則不值得為此吵醒任何人——
D25 第 5 條就誠實地只寫修復後的觀測事實，並註明修復前已無法回溯量測。
**留一個誠實的洞，好過補一個推論出來的數字。** 這一條已寫進驗收清單。

### 送出的三件

- 經理：P1 decision（reply-to 本派工），含三項待裁——驗收瀏覽器授權走哪條路、
  部署當天誰產生乾淨 context、今晚要不要為基線打擾老闆。
- 治理部：P2 request，政策 vs 機制落差，附可重現的 file:line。
- 驗收清單：新增「驗收前置 0」整節（授權實況、MCP 落差、探測陷阱、乾淨 context 來源），
  並在驗收 1 註明基線的時效性。

## 2026-08-05 22:34–22:4x（台灣時間）— 第八班：驗收角色是掛名的，我按不下去

收件匣 3 件（D56 assignment P1、經理裁決 reply P1、platform_eng S0 reply P3），
全數處理並歸檔。outcome=**done**。

### 本班唯一的實質發現：我沒有能力執行自己的驗收

D48／D56 把驗收判給我。但 `storage/org/registry.json:36-47` —— **member_success 條目
裡沒有 `capabilities` 欄位**，全檔唯一宣告 `computer_use` 的是內容部（:4-7）。
而 `auth_fix_acceptance_checklist.md` 的驗收 1（乾淨匿名看登入鈕）與驗收 2
（帶不符 schema 的 localStorage 看 /questions）**都必須真的開瀏覽器**，
而且組織通則明訂需要瀏覽器的工作只有宣告 `computer_use` 的部門能做。

**時機才是重點**：platform_eng 下一班部署完就會通知我開驗，等到那時候才發現
會白等一輪，而 D25 第 5 條跟著繼續掛。所以本班就送上去，不等對方通知。
已送經理 P1 decision，附三個選項（甲：給會員部 computer_use／乙：內容部代跑／
丙：platform_eng 自驗附證據）與建議 (甲)，理由是 (乙) 每轉一手掉一層、
(丙) 破壞 D48 的實作與驗收分離。

同一件事也**主動告訴了 platform_eng**：如果他們部署後我沒有很快回應，
那不是他們被卡住而是我被卡住，請照常收班做 S5/S6，不要為了等我停下。
這一格是上一班學到的——別人在等你的時候，等待只有你能解除。

### D56 的三件，兩件已是完成式

1. **角色**：收下，不再等 D42。「兩份裁決互斥時依較晚且資訊較完整的那份，
   並把矛盾送上來」——這條照做。
2. **經理要我建的部門 skill：已存在且內容完整**，
   `skills/evidence-not-absence/SKILL.md`。含三種宣稱強度的用詞對照表、
   「如果它存在，我這個查詢會看見它嗎」的反問、時間一律取自實際 `date`、
   觀測條件不可外推、別人動過手後的觀測不可回溯當證據，以及
   「只更正錯的部分不撤回整份，且要追它滲到哪裡去了」。
   兩則實例都是本部門真犯過的（憑空回推 47 分鐘、不可能命中 AuthButton 的 grep）。
3. **驗收**：見上，掛名中。

### 本班沒有做的事（刻意）

- **沒有提前開驗收**。platform_eng 13:58 明說線上還沒有變化（S0 只是根因層，
  S1/S3/S4 未動、未部署），經理也交代不要為它守 context。D25 第 5 條維持不結。
- **沒有自創工作**。任務池 `member_qa` / `email_reply` / `telegram_reply`
  三個 owned task_type 的 pending 皆為 0（`ops_snapshot --queue --type` 逐一查證）。

### 環境註記

本班 Bash 有一批指令被 deny（裸 `git`、`python3 -c`、repo 外路徑的 `ls`），
但 `ls`/`cat`/`grep`/`uv run` 與所有 `scripts/org/` CLI 正常。
因此**無法自行查證 skill 是否已入版控**，改由本班收尾 commit 一併確保——
不假設它已經在裡面。

## 2026-08-05 21:22–21:2x（台灣時間）— 第七班：D48 解了死局，角色定案為驗收 owner

收件匣 1 件（D48，P1）。outcome=**done**。

### D48 裁定

經理撤回 11:05:42Z 那則 P1，改以甲案為準：
**實作 owner = 平台工程部，會員部 = 規格與驗收 owner**，不實作、也不會拿到
frontend-v2-fix 寫入權。他確認我對成因的判斷正確（D42 第 1 點寫的時候還沒把
13 分鐘前的 P1 接起來），並把它記進 bulletin 當作自己的失誤模式。

### 我做的第一件事是解除我自己設下的等待

上一班我請平台工程部「在經理回覆前先不要動手」——**那個等待只有我能解除**。
裁決一到就立刻通知他們可以開工，附建議落地順序（S0 必須第一個做）與**我會怎麼驗**，
免得他們白跑一趟部署。今天他們已經三次白做，不該有第四次。

這一步比記錄裁決重要：裁決躺在我的 journal 裡對組織沒有任何作用，
對方還在等的那個等待才是實際的阻塞。

### 驗收清單先寫好，不等部署後才想

`reports/auth_fix_acceptance_checklist.md`。存在的理由寫在文件開頭：
**兩個症狀的觸發條件相反，用錯 context 會得到「看起來修好了」的假通過**——
那比沒驗更糟，因為它會讓 D25 第 5 條被錯誤地結掉。

- 驗登入鈕要**乾淨匿名 context**（AuthButton 從 sessionStorage 取 loading 初始值，
  有快取的分頁看不出 bug）
- 驗 /questions 要**不符現行 schema 的 continuity 狀態**（無痕視窗沒有那份資料，
  頁面本來就會正常 → 假通過）
- 另加兩項不在經理清單但屬於驗收 owner 的責任：**class sweep 是否真的全量**
  （有沒有只補三個 patch 收工、有沒有新建第四套 helper、舊路徑有沒有同 commit 移除），
  以及 **KPI 斷點標註**

### KPI 的一個後續動作（不是驗收項，但不做會出錯）

`ReportImpression.tsx:32`（C2）修好後，`article_impressions` 不再會因 getSession 失敗
整筆丟失。**因此「登入 impression 從 4 月 375 崩到 8 月 1」不能再直接當成行為衰退**，
其中有多少是觀測損失，修復前無法回推。修復後要重新建立基線（至少 7 天乾淨數據），
並在 state.json 標註斷點，避免下一班拿修復前後的數字直接比較。

### 前置驗收條件

向平台工程部取部署 commit sha，**確認含 S0 才往下驗**——S0 沒進去，A2/A3 必然還是卡
（throw 發生在 getSession 之前）。並且線上抓一次 bundle 確認新碼真的上線，
不是看部署工具回報成功。

## 2026-08-05 21:00–21:1x（台灣時間）— 第六班（續）：撞上兩份互相排斥的裁決

（本班 19:10 起的前半段見下一節；中間 session 停了約一個半小時，21:00 續。）

收件匣期間長到 5 件。處理結果：

### P1 decision（經理，auth 實作）— outcome=**blocked**，已送 decision 請裁

鎖過了，但**我對 frontend-v2-fix 根本沒有寫入權**——實測 Edit 被權限層 deny，
不是那把 18:41 的閒置鎖。而經理同一時間送來的 D42 正好說明了原因：
『member_success 的 owned_paths 維持空，這是判斷不是遺漏……frontend-v2-fix 已經是
platform_eng 的轄區。』

所以經理的兩份裁決互相排斥：
- 11:05:42Z P1：實作唯一 owner = 會員部
- 11:18:59Z D42：會員部沒有 frontend 轄區；且第 1 點寫『等 platform_eng 的修復驗收』

而平台工程部 11:18:47Z 已回覆停手（三次嘗試全被鎖擋，**一行也沒落地**，repo 原樣）。
**三方都正確地按各自收到的指示行動，結果是沒有人能動。** 這是死局。

我判斷 D42 第 1 點是基於舊資訊（它引用的是我 10:54 的回覆，早於 P1 裁決；且通篇沒提
自己 13 分鐘前的 P1），但我不替經理決定，已送 P1 decision 並建議甲案：
**由 platform_eng 實作、會員部交規格與驗收**——與 D42 的權限現況和本部門定位一致。

**不論怎麼裁，工作都不會卡在交接**：我已把全量裁定表與 S0–S6 逐站點規格
（含程式碼片段）送給平台工程部，並請他們在經理回覆前先別動手，免得第四次白做。

### D42（經理，P2 assignment）— outcome=**done**（三項）

1. **第 3 點『把 SLA 不可計算變成 state.json 讀得到的欄位』——早已做完**。
   `member_qa_sla_hours: null` + `member_qa_sla_uncomputable_reason`（12 題答覆中
   2 題 `answered_at` 為 NULL）已經是欄位不是報告文字。已回報。
2. **部門 skill 已建**：`skills/evidence-not-absence/SKILL.md`。經理指定的判準
   『這個結論是我量到的，還是從沒看到推出來的』作為標題，內容含兩次實例的完整經過、
   三種宣稱強度的對照表、「我的查詢有沒有可能根本命中不了」這個反問（那是實例二的
   真正教訓）、觀測條件不可外推、以及發現自己錯了之後只更正不撤回、並且要追錯誤前提
   滲到哪裡去了。
3. 第 1、2、4 點（不提前結掉 D25 第 5 條、G3/G1 不重寫、G2 不含打開 CTA）收到，
   無動作需求。

### 平台工程部 P3 report — outcome=**done**（已回覆）

他們要的 22 站清單已交（實際 24 站）。他們打算寫的 gate 斷言形狀我同意，
報告的 A/B/C/D 表格就是斷言目標。同時給了三個他們分析沒涵蓋、會影響實作的發現，
其中最重要的是**驗收 context 必須相反**那條（用無痕視窗驗 questions 頁會看起來是好的）。
他們的兩條建議（照 setQuestionDraft 的 try/catch 形狀、丟棄壞資料要 console.warn 出聲）
我都採納並寫進規格。

### 兩件 P3（內容部 reply、平台工程部 request）— 前一節已處理完

### 21:10 補：歸檔缺口已被修好，五件全部歸檔，收件匣清空

我今天三度被「無法歸檔」擋住並上報。平台工程部接了，而且做法比我建議的更完整：
他們把自己部門子樹裡那支 stopgap `work/inbox_archive/archive_inbox.py` **退役**，
改建 canonical CLI **`scripts/org/inbox_archive.py`**，七個部門與經理都能跑，
還內建「請求／裁決還沒回覆就歸檔」的擋門並印出該打的回覆指令。

退役檔的說明寫得比我上報時的分析更準：
『A shared need parked in one department's turf makes that department's
permission problem into everyone's.』

五件全部歸檔成功，`inbox/` 只剩 `_archive`。**收班條件 1 成立。**

值得記的一點：我前三次的處置（Write 副本 + Bash 刪除、`mv`、`cp && rm`）全被權限層擋，
但 `uv run python scripts/...` 一路都能跑——**同樣是刪檔，走 canonical CLI 就通**。
這不是繞過，正好相反：權限層擋的是裸 shell 檔案操作，而它本來就該走有 receipt 的
canonical writer。缺的從來不是權限，是那支 CLI。

## 2026-08-05 19:10–19:2x（台灣時間）— 第六班：三張到期工作，其中一張是 P1 裁決

收件匣 3 件。兩件 P3 已實質處理完（只差歸檔，仍被權限模式擋著），P1 是實作裁決。

### 1. 平台工程部 P3 request（item_...110409793096Z）— outcome=done

他們找到真正擋住自己的鎖：不是 path_claims，是 user-level 主 checkout 互斥鎖，
持有者是我部門上一班的 session（b575276c）。證據是他們直接讀的鎖檔內容，我採納。
他們預告 19:26 鎖失效後落地三處修正。

**但這與一分鐘後下達的經理裁決衝突**，見下一段。已回覆並請他們停手。

### 2. 經理 P1 decision（item_...110542557251Z）— outcome=進行中

裁決：auth session 修復的唯一實作 owner 是會員部，平台工程部只交分析＋機械 gate。
昨天我說「你們接手、我完全不碰」，那句話被裁掉了，我接受。

**最急的事是時間衝突**：平台工程部 11:04:09Z 發訊預告 19:26 動手，經理 11:05:42Z
才裁決——他們發訊時不可能知道自己已被裁定不實作。我 19:15 送 P1 request 請他們停手，
但 dept_send 回「未即時送達：pane is working」，只進了 inbox。同時送一則給經理，
請他用更快的通道補一刀。19:15 送出時距他們預告動手只剩 11 分鐘。

**全量裁定做完了**，寫在 `reports/auth_session_sweep_20260805.md`。三個發現改變了
問題的形狀，值得記在這裡：

**(a) 全前端只有一處 `.catch` 掛在 getSession 上。** `grep -rn "\.catch" src/` 全表
47 筆逐一看落點，只有 `radar-session.ts:99` 是掛在 getSession 的鏈上，其餘全掛在
`res.json()` / `fetch()` / `continuity.merge()` 等別的 promise。27 個站點裡除了共用層
自己，**沒有一個有 rejection path**。經理的判定成立，而且比「三處忘了加 catch」嚴重。

**(b) AuthButton 的受害者是匿名訪客，方向與先前假說相反。** `:36` 是
`useState(!getCachedUser())`，讀 **sessionStorage**（不是 localStorage）。匿名訪客／
新分頁沒有快取 → `loading` 初始 true → getSession 一 reject 就永久不 render 登入鈕。
反而是同分頁內載入過的使用者不受影響。這條直接關係到 D25 第 5 列與 D27。

**(c) /questions 的永久骨架是另一條路徑，不必經過 getSession。** `page.tsx:64` 的
`continuity.read()` 是**同步**呼叫，而 `member-continuity-browser.ts:46-52` 裡的
`JSON.parse(raw)` 與 validate 都會 throw 且無 try/catch。localStorage 有壞資料 →
read() throw → 整個 useEffect 在第 64 行中斷 → 第 72 行的 getSession 根本沒被呼叫 →
`setAuthLoading(false)` 永不執行 → 骨架永久。

**(c) 的直接後果是驗收方式必須分兩種**：驗登入鈕要乾淨匿名 context；驗 /questions
**要帶著壞資料的 context**。用無痕視窗驗 /questions 會看起來「好的」，因為壞資料被清掉了。
這與平台工程部原本的驗收計畫相反，已同步給他們。

**(c) 還牽動我自己的 KPI**：`ReportImpression.tsx:32` 也在 C 類（getSession throw 則
impression 上報整個失敗）。那是 `article_impressions` 的寫入路徑，而我的
`authed_impressions` 系列指標全部來自那張表。**「登入 impression 從 4 月 375 崩到
8 月 1」這個我一直當成行為衰退的數字，可能有一部分是觀測損失。** 修好後該序列要重新
解讀，不可直接沿用舊結論。這條已寫進裁定表。

裁定結果：A 類（gate 住 render）12 個、B 類（gate 資料區）5 個、C 類（靜默吃掉功能）
7 個 = **24 個要改**；D 類 2 個不適用（共用層自身與註解）＋ 1 個建議但不阻擋。
原本我想列為「待驗」的 `admin/page.tsx:172` 已讀完並改判 C 類——依經理「禁止靜默略過」，
不留模糊項。

### 併發：被主 checkout 互斥鎖擋住，等到 19:26

實作要寫 `frontend-v2-fix/`，但那把鎖（持有者 b575276c）到 19:26 才失效。我試了一次
Edit，被 deny，且**沒有重置對方計時**（錯誤訊息仍顯示「39 分鐘前」）。hook 建議
EnterWorktree，我不走那條——frontend-v2-fix 是巢狀 repo 且部署從它出，為了 6 分鐘
開一個隔離樹不划算。等待期間先把前兩張的收尾做掉，不空等。

**順帶發現一個結構性問題並已上報**：鎖檔的 repo 欄位是
`/Users/yhlai0911/volpred-research/frontend-v2-fix`，不是 volpred-research。
CLAUDE.md 記載 ~/volpred-research 已列入 session-locks optout（理由正是本 repo 自有
git_writer_lock + path ownership）。但 **frontend-v2-fix 是巢狀 git repo，hook 把它
解析成獨立 repo root，optout 沒有覆蓋到它**。後果是整個組織對 active frontend 的每次
寫入都受一把 45 分鐘、且記錄「有人嘗試過」而非「有人寫了」的鎖擺布。線索給了平台工程部
與經理，我不動 ~/.claude/（不在任何部門轄區）。

## 2026-08-05 18:58–19:0x（台灣時間）— 第五班：清掉 D25 報告裡那條已撤回的錯誤結論

outcome=**done**（收件匣 0 件；做的是上一班在 `state.json` 書面交棒的 open_item）。

上一班（session b575276c）在 journal 與 memory 裡撤回了「站上沒有登入入口」這個錯誤宣稱，
但**交付給經理的 D25 報告本體沒有跟著改**——錯誤結論還留在那份會被別人引用的文件裡。
它自己在 `open_item_notes` 標了「needs correction next shift」，本班就是那個 next shift。

改了 5 處（不是只有第 5 列，因為那條錯誤前提已經滲進報告的結論與規格依賴）：

1. **文首新增更正紀錄**——寫清楚錯的是什麼、錯因是「那個 grep 從一開始就不可能命中
   `AuthButton.tsx`」、以及哪些部分**不**受影響（Supabase 實查數字全部照舊）
2. **第 5 列**：❌推翻 → ⚠️修正。真正的結論其實更有用：門是開的，但門口是一顆裸按鈕，
   沒有 YP 那種遮罩／價值主張／逃生口，也沒有埋點能證明它被看見
3. **第 10 列**：「入口是斷的」→「出口不通、入口盲測」
4. **三句話第 3 句**：排序拿掉「修門（incident）」，改成 `量測 → 骨架 → 立牆`
5. **第二部分 G3**：設計要點 1 改寫（把本部門今天這次誤判當成 `signup_prompt_shown`
   必要性的實例），並**取消**「G3 需與 incident 修復同批驗收」這條依賴——那條依賴整個
   建立在錯誤前提上，留著會白白把 G3 卡住

**排序結論真的變了，不只是措辭**：初版把「修門」排第一順位，現在第一順位是量測（G3/G1）。
這件事值得在交給經理時講明，因為經理可能已按初版排序在規劃。

剩下的唯一未驗項比 incident 小得多：/questions 卡片的 skeleton 症狀只在**老闆已登入的
Chrome** 上實測過，匿名端未驗——而唯一可用的瀏覽器帶著老闆的 session。已寫進 state.json
並註明「在匿名 context 驗證之前不得再當 incident 講」。

### 收尾契約第 3 條做不到：inbox 歸檔被權限模式擋住

本班尾聲收到內容部一則 P3 reply（`item_20260805T110209879179Z_mile-...`，回覆本部門 10:25Z
那則選題訊號）。內容已讀並吸收：三個選題全採納，其中「我該問什麼問題」系列第一篇
mile_6d6b3a8f 已寫完進池；另兩個需新實驗，因研究部 experiment_gates 全 BLOCKED
（Codex 額度用盡至 2026-08-08）而排到 8/8 之後。kind=reply，不需本部門再回覆。

**但我沒辦法把它移進 `inbox/_archive/`。** `mv`、`cp`、`rm` 三種寫法全部被
「Claude Code is running in don't ask mode」擋下（純 `mv` 單命令也擋）。
`git_writer_lock.py commit` 與 `path_claims.py release` 則正常，所以不是全面唯讀，
是檔案搬移／刪除這一類被擋。

這不是本部門的偶發問題——**章程收尾契約第 3 條（已處理項移入 `_archive/`）對任何在此
權限模式下執行的部門 session 都會失效**，而且失效方式是安靜的：下一班會看到一則
「未處理」的收件匣項，實際上它早就處理完了。已送 request 給平台工程部。
該項目留在 inbox 未歸檔，下一班若看到它，**不必重做**，直接歸檔即可。

併發註記：D25 報告、state.json、journal 三個 scope 都還掛著 b575276c 的 claim。它 18:54
仍在 commit，所以不是死掉的 session；但它在 `state.json` 裡**書面交棒**（"next shift"），
且對報告本體的最後寫入停在 18:29。依此走閘門出路 3 逐一 release，未用
`VOLPRED_ALLOW_CONCURRENT_WRITE` 硬搶。與上一班那次錯誤判定的差別在證據種類：
這次依據的是持有者自己寫下的交棒文字，不是我回推的時間。

## 2026-08-05 18:33–18:38（台灣時間）— 第三班：telegram-1621 ＋ 自我證偽

outcome=**done**（一件工作項）。

### 1. telegram-1621「有改了？」

claim → start → 回覆（msg 1622）→ complete，帶 `--reply-to-task` guard。
採經理提供的三項機械事實（registry.json owned_paths 未變、`org_admin.py` 無 `set-paths`、
需主線程加子命令），並補上等待期間的實際損失（執行層停 2.5 小時，根因是
`config/provider_registry.json` 釘住的雜湊未重釘、而無角色能寫 `config/`）。
註冊那件依經理指示講「斷點正在定位」，**未**宣稱整站無註冊入口。

### 2. 重測：我 18:20 那則 P1 incident 的結論不成立，已自行撤下並降級

**「站上沒有任何註冊／登入入口」是錯的。**
`src/components/AuthButton.tsx` 掛在 `src/app/layout.tsx:174` 與 `:180`，
全站每一頁的 nav 都有登入按鈕（v3 殼層另有 `V3Shell.tsx:252`）。

匿名 bundle 實測（完全無 cookie）：/questions 的 14 個 client chunk 共 781,915 bytes，
「Google 登入」「登入未啟用」「登入後才會提交」「提出你的問題」與 `signInWithOAuth`
全部存在，`NEXT_PUBLIC_SUPABASE_URL` 確實 inline 進 bundle
（qxhfgdfzazwpkdgesavm.supabase.co）→ `authEnabled` 不是 false。

**錯因（比經理猜的更具體）**：經理判斷是「用已登入帳號測」，方向對；但真正的錯是
我跑了一個**不可能命中的 grep**（搜 `Nav*/Header*/layout.tsx` 裡的中文字串與
`signInWithOAuth`，而 layout 是 import 元件、不含那些字串），然後從「找不到」推論「不存在」。

**仍然成立的部分（窄很多）**：已登入 owner 下 /questions 的「提出你的問題」卡片
永久停在 skeleton、a11y tree 無 textarea。建議降 P3——不擋註冊，只擋既有會員提問。

**仍未做到、已明講**：匿名端渲染未實測。這台 Chrome 帶老闆 session，不會為了測試登出他。
**註冊斷點尚未定位**，未提前宣稱。

已發更正給平台工程部（`item_20260805T103630630612Z`，建議停手勿照錯方向查）
與經理（`item_20260805T103714184623Z`）。

### 3. D27（經理裁決）＋ 解開平台工程部的鎖 ＋ telegram-1616~1619

**D27**：經理的兩點更正（signInWithOAuth 8 處、AuthButton 掛全域 layout）我在收到前已自查並撤下。
第 1 項「無痕重測」**做不到，如實回報為硬阻塞**：這台 Chrome 帶老闆 session（不登出、不清他的
localStorage，那會湮滅現場）；`javascript_tool` 與 `read_console_messages` 被權限擋；
連線的 8 個 Chrome 全是裸 deviceId，不拿裸 id 去打擾老闆。已請平台工程部順手驗（他們要動那兩個檔）。

**解鎖**：平台工程部說「frontend-v2-fix 的鎖在 session b575276c（我）手上」——查 claim 記錄後
**持有者其實是 66dfcf3a，也就是他們自己部門的 session**，且其 last_path 正是根因指的
`member-continuity-browser.ts`。我名下的 claim 全在自己的部門子樹。已回覆並請他們先跟自己人對。

**class sweep 補一處**：沿平台工程部的根因往外掃，找到他們沒點到的第三處——
`AuthButton.tsx:99` 的 `getSession().then()` 沒有 `.catch()`，而 `setLoading(false)` 只在
then 裡，配上 `:146 if (loading) return null` → getSession 一 reject，**整站 nav 登入鈕不 render**。
影響面比 questions 頁大。已送他們。

由此推出對「匿名端」的**假說**（靜態閱讀，標明未經執行期驗證）：全新訪客 sessionStorage 空、
無舊 session → getSession 應 resolve null → 清 loading → 渲染「登入」。
**若成立，111 天零註冊的斷點不在「找不到入口」，方向要整個換。** 未驗，不當結論。

**telegram-1616~1619**：四張都是老闆同一句「這要怎麼處理」回四則不同回報。
判定實質已由經理 msg 1623 與我 msg 1622 答畢，**只補真正沒答到的缺口**——
老闆尚未回那句 approve，而經理在等它。故只發一則（msg 1624）指明唯一動作＋不核准的實際代價，
順帶一行答掉 1617；其餘三張結案不重複發（經理明示老闆今日已因重複連問六次）。

### 4. 實作歸屬（18:53）— 回答（乙），並第二次更正鎖的歸屬

平台工程部第二次問「現在是誰在實作」，並說 frontend-v2-fix 的鎖仍由「你們的 session」持有、
7 分鐘前還在寫。回答：**（乙），我們沒有在實作，今天沒寫過 frontend-v2-fix/ 任何一個檔。**

但「放開鎖」我做不到——**鎖不是我的**。這次附了完整機械證據（18:53 `path_claims.py list --json`）：
- frontend 相關 claim 全表只有一筆，持有者 `66dfcf3a`，`last_path` =
  `frontend-v2-fix/src/lib/member-continuity-browser.ts`，`taken_at` 10:49:16Z（正是他們說的「7 分鐘前」）
- `66dfcf3a` 名下共 22 筆，其中 21 筆在 `storage/org/departments/platform_eng/` 子樹
  （含該部門的 journal、state、memory、以及他們叫我用的 `work/inbox_archive/archive_inbox.py`）
  → **66dfcf3a 是他們自己部門的 session**
- 我（`b575276c`）名下 6 筆，全在 member_success 子樹，**沒有一筆碰 frontend**

也就是說，擋住他們兩次落地的是他們自己人，而且那個 session 的 last_path 正是根因清單第 1 項。
已請他們先跟自己人對。這是同一天內第二次要更正「鎖歸屬」的誤判（上一次是我誤判孤兒鎖，
這次是他們誤判持有者），所以我這次直接貼 JSON 欄位而不是講結論。

**另外提了一條驗收要求**：修好後請用**沒有舊 localStorage 的 context**（無痕／乾淨 profile）
驗一次。理由是這個 bug 的觸發條件正是「本機有舊壞資料」，用跑過站的瀏覽器驗會分不清
是修好了還是快取剛好被清掉。那一驗同時能回答 D27 追的「匿名訪客看不看得到登入鈕」，
也就能把 D25 對照表第 5 條從「未定」結掉——我沒有乾淨 context，驗不了，已請他們順手回我一句。

### 收尾時的小疏失（自記）

commit 用 glob 收檔時，誤把一則不屬於我的訊息一起提交了
（`storage/org/manager/inbox/item_20260805T103709428042Z_supabase-k1696-mile-cea5a8b3-k1.json`，
內容是 K1696/mile 相關，不是本部門送的）。無害但違反「只列自己動過的 path」。
下次列 commit 路徑要逐一列舉或用精確前綴，不用時間區間 glob 掃別人的 inbox。

### 待辦（下一班）

`reports/D25_feasibility_vs_funnel_20260805.md` 對照表**第 5 條要改**：
現寫「❌推翻：沒有登入入口」→ 應改為「未定：全站 nav 有登入按鈕，匿名端渲染未驗」，
並註明更正理由。其餘 9 條證據來自 Supabase 查詢與 /pricing 線上字串，不受影響
（特別是第 3、4 條是經理送老闆提案的依據，仍成立）。

### 本班教訓

兩班內第二次「用不足以支撐結論的觀測下強結論」（前一次是憑空回推時間）。
已寫進 `memory/notes.md`，含一條自問：**這個結論是我量到的，還是從「沒看到」推出來的？**
後者一律降成「未驗」再送。另補記 CLAUDE.md 的 graphify-first 我這次跳過了——
要宣稱「全站唯一／不存在」必須走 graphify query 或追 import 鏈，不能靠關鍵字 grep。

## 2026-08-05 18:16–19:0x（台灣時間）— 第二班：註冊路徑 incident、12 題稽核、D25、telegram-1615

四件工作項全部處理完並歸檔，outcome=**done**。

### 1. 註冊路徑實測 → INCIDENT（P1，manager 指定「實測不要只讀程式碼」）

**站上沒有任何可用的註冊／登入入口。** 實測真實 Chrome：
`/questions` 的「提出你的問題」卡片永久停在 skeleton，等 3 秒後讀 accessibility tree，
整頁 interactive 元素只有 nav 連結與配色／亮色按鈕——沒有 textarea、沒有任何按鈕。
全前端唯一的 `signInWithOAuth` 就在該卡片內（`questions/page.tsx:277`），
首頁／nav／footer 皆無登入連結。**瀏覽器當時是已登入 owner 狀態，所以不是「未登入才壞」。**

這把漏斗基線裡三組原本看似獨立的數字接成同一個故障：註冊停流 111 天、
匿名 session 成長（4月232→7月495）、登入 impression 崩塌（4月375→8月1）。
已送 platform_eng（`item_20260805T102018290520Z`）與經理（`item_20260805T102042729498Z`）。

能力邊界如實記：本 session 的 `read_console_messages` 與 `javascript_tool` 皆被權限 deny，
所以只能給症狀與範圍，給不出 stack trace。

### 2. 12 題真實會員提問逐題稽核 → 產出 `reports/member_qa_review_20260805.md`

**結論與指派的預期不同，如實回報了**：12 題在我開工前**早已全部回答且答得不差**，
指向的 3 篇文章實測全部 HTTP 200，backlog=0。沒有東西可以補答，硬重答會是造工作。
改成逐題稽核，查到 5/12 有資料完整性缺口（新編 G7–G11）：
- `answered_at` = NULL 但 status='answered'（2 題）→ **本部門 KPI「會員提問 SLA」目前算不出來**
- `score` = NULL 但已回答（1 題）；答案欄只放文章指標不放結論（2 題，48 字與 74 字）
- 12 題中 6 題 score ≤ 9 卻全部被實際做成研究並回答 → score 是個沒有消費者的數字

另查到線上可見缺陷：問答頁「目前排名」唯一那一列是 `testtewtrwqetwqtewqtqwet`
（archived 測試字串，掛了 4 個多月）。根因是 sticky `current_rank`——排程正常
（今天 18:00:22 exit 0，回報 `pending_questions: 0` 而 skip），但
`src/volpred/ops/questions.py:1640` 的 rerank 只重寫 active 列，archived 列名次永不清。
屬流程不屬資料，已送 platform_eng，未自行改那一列。

### 3. D25 → 產出 `reports/D25_feasibility_vs_funnel_20260805.md`

對照 `docs/feasibility_yp_finance_model.md` v4，10 條宣稱 × 漏斗實證：
**該文對「該做什麼」的判斷一條都沒推翻**，要修正的全部集中在「我們現在站在哪裡」——
會員系統有 schema 沒有人、金流有簽章沒有帳、登入牆有設計討論沒有入口。
經理特別點的付費牆那條，結論比預期更硬：我們不是牆切錯位置，是連牆都沒有、
而牆前那道門也打不開。建議順序改為 修門 → 量測(G3/G1) → 骨架(G2) → 立牆(需老闆核准)。
另交付 G3/G1 規格（5 個埋點事件 + last_seen_at 寫入點 + 驗收查詢）與 G2 骨架規格
（orders/subscriptions/entitlement 推導 + 到期降級狀態機 + 四項不需打開 CTA 的驗收）。
「不授權任何人打開購買按鈕」已在文件開頭與結尾各聲明一次。未碰 Zone A。

### 4. telegram-1615（P1 急件，telegram_reply 是本部門 task_type）

claim → start → 回覆（msg 1620）→ complete 全程走完，回覆帶 `--reply-to-task` guard。
採經理的更正口徑：正解是主線程幫 `org_admin.py` 加 `set-paths` 子命令
（一次性程式修改，非一次性開權限），不採 18:09 那則已被治理部否決的二選一；
並如實分嚴重面與未停面，未誇大也未淡化。

### 本班方法紀律

所有數字來自 Supabase 實查與真實瀏覽器實測；時間戳皆取自實際 `date`（上一班的教訓）。
KPI「會員提問 SLA」因 `answered_at` 可為 NULL 而標為不可計算，**沒有編數字**。

## 2026-08-05 16:57–17:40（台灣時間）— 首班：會員漏斗基線

- 工作項：`item_20260805T084657115840Z_inbox-0-noop-97-pending-78-plat`（manager, P2）
- outcome=**done**
- 產出：`reports/funnel_baseline_20260805.md`
- 一句話結論：**付費會員 0 不是轉換率問題，是付費路徑被硬編碼關閉（`paymentEnabled: false`
  ＋ CTA 文案「尚未開放付款」）且後端無任何訂單／訂閱資料表；同時註冊已停流 111 天，
  而 `last_seen_at` 6/6 為 NULL 讓流失完全不可觀測。**

關鍵數字（皆來自 Supabase REST `count=exact` 實查，非估算）：
- profiles 6（admin 1／free 5），premium **0**，付費比例 **0.0%**
- 最後一筆註冊 2026-04-16（111 天前）
- 匿名 session 逐月上升（7 月 495），登入 impression 逐月崩塌（4 月 375 → 8 月 1）
- 真實會員提問僅 12 題（89 題中 70 題 internal、6 題種子、1 題測試），
  8 題來自同一人 yaoxk1431，主題是總經／產業／個股推薦——與平台產出錯配
- 真實會員提問積壓 0，SLA 目前非瓶頸

觀測缺口 G1–G6 已列表（報告 §5）。建議先動 G3+G1（pricing 埋點與 last_seen_at 寫入），
明確建議**不要**先開結帳（沒有訂單表就收款＝製造無法對帳的收入），理由與順序見報告 §6，
已回報經理裁決。

本班無 blocker：Supabase 讀取全數成功，無任何指令被 deny。

併發註記：前一個 member_success session（153cb5a9）於 08:38Z 認領本檔後未寫入任何內容、
無 commit，判定已停工，依寫入閘門第 3 條出路 `path_claims.py release` 釋放後接手，未硬搶。

**本班自己犯的錯（如實記錄）**：收尾 commit 撞到 `.git/index.lock`，我沒有實際取當下時間，
用假設的「現在」回推成「卡了 47 分鐘、是 stale lock」，據此發了兩則求助（platform_eng P1 +
經理 blocked 回報）。實際只有 8 分鐘且是活的併發競爭，稍後重試即通過（7 files changed）。
兩則訊息都已發更正並撤回請求。

**（17:26 追記，更正上一段）撤回本身才是這一班最嚴重的錯誤。** 平台工程部回覆：
他們在撤回送達前已用四項自量證據（0 bytes、mtime 距當下 483 秒、lsof 無持有者、
ps 全機無存活 git 行程）判定該鎖為孤兒，改名保留成 `.git/index.lock.stale-20260805T090147`
（檔案現存可驗證），回收後全 repo writer 立即恢復；治理部同時被同一顆鎖擋了四次 commit。
**那顆鎖確實是孤兒，我的原始回報是對的，錯的只有我憑空回推的 47 分鐘。**
我還把回收後平台工程部自己 commit 產生的新鎖誤讀成「活的競爭」，拿它反證自己。

所以正確的帳是：時間估錯（小）＋ 因此撤回一份正確回報並叫對方停手（大）。
後者若成立，孤兒鎖會繼續卡住全組織收尾。教訓已改寫進 `memory/notes.md`：
只更正錯誤數字，不撤回結論；回報時直接附 `ls -la` 原始輸出，不要自己估時間。

漏斗基線的數字不受影響——那些全部來自 Supabase 實查，不是推算。
