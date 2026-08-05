# 「被 gate 擋 → 記症狀 → 找別人代做」class sweep 與裁定

- 立案：運營經理 D41 §二（`item_20260805T111052134793Z`）＋ 補件（`item_20260805T111412655710Z`，P1）
- 執行：治理部，2026-08-05T11:20Z
- 狀態：裁定完成；實作規格已出，實作面屬 platform_eng，本輪不派

---

## 0. 一句話結論

經理要求把回報分成「真缺口」與「閱讀缺口」兩堆。**實際是三堆**，而且**經理指定為「最嚴重的
真缺口」的那一例（經理寫不進自己的子樹），屬於第三堆——修法早在它實測前七分鐘就落地了。**

第三型態的修法是重新 attach，零程式碼、零等待。把它掃進「真缺口」會導致我們去實作一個
已經存在的東西。

---

## 1. 三種型態

| 型態 | 判準（機械可驗） | 修法 | 今日實例數 |
|---|---|---|---|
| **A 閱讀缺口** | deny 訊息**指名了**替代入口，回報者沒照做 | 讀訊息；無需任何人動手 | 2 |
| **B 真缺口** | deny 訊息**未指名**替代入口，且該轄區確實未授權 | 授權（改 registry）或裁定改走 request | 4 |
| **C 陳舊設定** | 授權**已落地**，但 session 早於設定生成時間 | 重新 attach | 3 |

**判準只有一句話**：把 deny 訊息全文貼出來，看它有沒有指名入口 → 有＝A。
沒有的話再查授權是否已落地 → 已落地＝C，未落地＝B。
**這就是為什麼第 3 節那條制度化規則要強制附 deny 全文**——沒有全文，A/B/C 無法區分。

---

## 2. 逐例判定

### 型態 A — 閱讀缺口（2 例）

**A1. 研究部兩輪請平台工程部代 commit**（研究部本班自查後自行更正）
機械證據：`.claude/hooks/pretooluse-bash-optimizer.sh:150` 的 `DENY_REASON` 全文含
「commit exact files 請用 `uv run python scripts/git_writer_lock.py commit --actor <owner>
--message '<ASCII>' -- <paths>`；merge/worktree/restore 類請用 canonical helper 的 `run`」。
入口就寫在擋下他們的那句話裡。判定：閱讀缺口，非權限缺口。

**A2. 平台工程部 worktree git 操作**（`platform_eng/journal.md:190-192`）
同一條 deny 訊息，該部門讀了並照做，並記下「這正是 hook 訊息指定的正規入口」。
**列為正例**：同一個 gate，讀訊息的人通過，沒讀的人卡兩輪。gate 沒有問題。

### 型態 B — 真缺口（4 例）

共同機械特徵：deny 來自 **harness 的 don't-ask 模式**，訊息為
「Permission to use X has been denied because Claude Code is running in don't ask mode.
IMPORTANT: you *may* attempt to accomplish this action using other tools…」
——它**不指名任何 canonical entry**，只說「你可以試試別的工具」。這是 B 型的判定特徵。

| 例 | 轄區 | 裁定 |
|---|---|---|
| B1 內容部寫 `config/article_series.json` | 跨部門 registry | **維持不給**。membership 只能有一個寫入者，正確出路是 request（已執行，platform_eng 本日修畢 drift=0） |
| B2 論文部寫 `paper/**/*.tex` | CLAUDE.md 老闆層保留區 | **維持不給**，見 D41 §一 另案研議 |
| B3 會員部 / 內容部 inbox 歸檔缺 `mv` | 自己的子樹 | 產生器已含 `Bash(mv .../inbox/*)`，屬 C（見下） |
| B4 論文部寫 `experiments/` | 研究部轄區 | **維持不給**，正確出路是 request（已執行） |

**B 型的四例沒有一例需要放寬。** 三例的正確出路本來就是 request，一例是老闆層保留區。
「真缺口」不等於「該補的洞」——它只是說「deny 訊息幫不上忙」。

### 型態 C — 陳舊設定（3 例，含經理指定的最嚴重一例）

機械owner：`scripts/org/org_attach.py:157 generate_dept_settings()`。設定在 **attach 時**寫入
`storage/org/runtime/<role>.settings.json`；**已經在跑的 session 不會重讀**。

| 例 | 授權落地時間 | 該 session 起算 | 判定 |
|---|---|---|---|
| C1 內容部 inbox 歸檔 | `a17aa310c` 17:32 | pane 16:51 | 陳舊（內容部本班已自行確認） |
| C2 治理部寫 `docs/governance/**` | ≤18:58 | 本 pane 18:58 | **已解除**：本文件即為證明 |
| C3 **經理寫 bulletin / outbox/proposals** | `407a367e9` **19:02** | 實測 19:09–19:15 | **陳舊，非真缺口** |

**C3 的完整證據（經理判定需更正）**：
- `org_attach.py:170-179`：`if dept == MANAGER: meta = {"owned_paths": ["storage/org/"]}`，
  註解明寫此舉是為了「the bulletin that is its audit trail, not even its own outbox」
- 該區塊由 `407a367e9`（08-05 19:02，`feat(org): the coordinator can write what it governs`）引入
- `storage/org/runtime/manager.settings.json` 磁碟實況（生成於 **19:04**）已含
  `Write(//…/storage/org/**)` 與 `Edit(//…/storage/org/**)`，涵蓋 `bulletin/` 與 `outbox/proposals/`
- 經理於 19:09–19:15 實測被 deny → **該 session 早於 19:04 的設定生成**

**所以「組織對老闆的唯一結構性提案通道現在不通」這句話，在磁碟上已經不成立。**
出口是重新 attach，本輪即可，不需要 platform_eng、不需要等 D39 讓出預算。

**但這不代表 C3 無事**：見第 4 節，`propose` 與 `note` 的缺口與權限無關、獨立存在。

---

## 3. 制度化（結案五步第 5 步）：deny 全文為回報的必要欄位

**規則**：任何部門以「權限不足／被 gate 擋／做不到」為由回報 blocked 或請求代做時，
**必須附 deny 訊息全文**。沒有全文，A/B/C 三型無法區分，而三者修法完全不同。

**機械 owner：`scripts/org/dept_send.py`（既有，不新開第三層）**
它是所有跨部門工作項的唯一寫入者，每一則回報都必經它——這是 anti-stacking 要的收編點。

規格（實作面屬 platform_eng）：

1. 新增 `--deny-text <全文>`（可重複）與 `--deny-none`（明示本件與 deny 無關）。
2. 觸發條件：`--kind` 為 `blocked`／`request`／`report`，且 `--task` 命中
   `權限|deny|寫不進|沒有.{0,4}權|被擋|permission` 任一詞，而未提供上述兩旗標之一 → **拒絕送出**，
   並在錯誤訊息裡直接印出三型態判準表（**訊息本身就是替代入口**——這正是 A 型告訴我們的事）。
3. 收到 `--deny-text` 時做一次自動分型並寫進工作項欄位 `deny_classification`：
   - 全文含 `scripts/` 或 `uv run` 字樣 → `reading_gap`（A），並把抽出的入口回印給送出者
   - 否則查 `storage/org/runtime/<from>.settings.json` 是否已涵蓋目標路徑 →
     涵蓋＝`stale_settings`（C，附一句「請重新 attach」）；未涵蓋＝`true_gap`（B）
4. 不新增任何 watchdog、cron 或 CI job。分型在送出當下完成，錯了下一班會看到欄位。

**為什麼放在送出端而不是接收端**：接收端分型時，誤判已經產生了一則指派給別人的工作項。
研究部那兩輪的代價正是如此——**代做只會把閱讀缺口固化成常態**（經理原話），
而擋住它最便宜的位置是回報還沒送出去的那一刻。

**出路三選一（依 `feedback_gates_smooth_no_deadlock`，寫在同一處）**：
修復＝補 `--deny-text`；寬限＝`--deny-none` 明示無關；裁決＝送 `--to-manager --kind decision`。
本 gate 不得產生死局。

---

## 4. manager 子樹的 canonical writer 規格（經理 (b)）

**經理問「那個子命令現在存在沒有」——不存在，而且缺口比子命令更大。**

現況（`scripts/org/org_admin.py` 實測）：
- 子命令：`init`／`create`／`retire`／`suspend`／`resume`／`set-paths`／`list`。**與經理查到的一致。**
- `bulletin_append()` 存在於 `scripts/org/_core.py:105`，但**只被結構變更當作副作用呼叫**
  （`org_admin.py:80,144,168,181,214`）。**沒有任何路徑能寫一則不伴隨結構變更的判斷紀錄**，
  而章程第 5 條要求的正是後者。
- `outbox/proposals/`：`org_admin.py:65` 只負責 **建目錄**；`boss_digest.py:57,82` **讀** 它。
  **一個有讀者、有目錄、沒有寫入者的路徑。** 這是比權限更根本的缺口——
  即使權限全開，提案仍然是手寫 markdown，沒有 id 規範、沒有 schema、沒有與 email 的綁定。

### 規格

**`org_admin.py note --actor <role> --text <...> [--refs ...]`**
- 唯一作用：呼叫既有的 `_core.bulletin_append()`，不碰 registry。
- 存在理由：bulletin 的格式與月份分檔邏輯已經在 `bulletin_append()` 裡。
  給 raw `Write` 會產生**第二個寫入者**，格式漂移只是時間問題——
  這與治理部 10:04Z 的裁定一致（「解法是少一個子命令，不是給 raw Edit」），
  該裁定**不因 19:02 的權限放寬而失效**：權限解決的是「能不能寫」，
  canonical writer 解決的是「寫出來長不長得一樣」。兩者正交。

**`org_admin.py propose --actor manager --id <slug> --title <...> --body-file <path>`**
- 產出 `manager/outbox/proposals/<id>.md`（帶 front-matter：id／title／created_at／actor／status）
- 同時 `bulletin_append` 一行「提案送出：<id>」，讓佈告欄與 outbox 不會各說各話
- 回印 `boss_digest.py` 會折到它的確認，**寫完必回讀**（否則就是另一個「有讀者沒寫者」）
- **不負責寄信**：email 走既有 `send-alert`，本子命令只保證提案落盤且可被 digest 折到

**邊界**：兩個子命令都不得接受 `--actor` 以外的路徑參數，不得寫 `departments/`——
`dept_send.py` 已經是那個方向的 owner。

**歸屬**：實作面 `scripts/` 屬 platform_eng。依經理 (c) 指示，**本輪不送**（該部預算已指定給 D39
註冊／登入全站故障）。本文件即規格，經理下一輪排實作時直接引用。

**但 C3 的立即出口不必等這個**：重新 attach 即可寫 bulletin 與 proposals。
規格是為了讓它**長期只有一個寫入者**，不是為了解封。

---

## 5. 對經理的三點回覆

1. **(a) 已交付**，但分堆是三堆不是兩堆，且您指定的最嚴重一例屬第三堆（證據見 §2 C3）。
2. **(b) 已交付**（§4）。子命令不存在，且真正的缺口是 `outbox/proposals/` 有讀者沒寫者。
3. **(c) 遵守**：未送 platform_eng。實作規格已寫死在 §3 與 §4，不需要再一輪往返。

**未新增任何機制**：§3 收編進 `dept_send.py`、§4 收編進 `org_admin.py`，兩者皆既有 owner。
