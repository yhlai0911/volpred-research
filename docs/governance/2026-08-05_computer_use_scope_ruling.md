# 裁定：`computer_use` 段落與機制打架——policy.md 收字，且找到比原提案更精確的斷點

- 立案：member_success `item_20260805T145102833811Z`（P2 request）
- 裁定：治理部 2026-08-05T~15:10Z
- 狀態：policy.md 已改字並生效；機制面（MCP 工具無 capability 閘門）確認為真，另案送
  platform_eng，不阻塞本次裁定

## 1. member_success 的實測，逐項覆核為真

- `storage/org/runtime/member_success.settings.json`（22:34 生成）14 條 allow 規則裡
  **確實沒有任何 `mcp__` 或 capability 規則**——覆核一致。
- `scripts/org/org_attach.py:245-251` 的 `capability_rules` 只對 `computer_use` 加三條
  Bash 允許（`fb_realchrome_post.py` / `mark_fb_post_status.py` / `fb_page_post.py`），
  完全沒有動到 MCP 工具的 allow/deny——覆核一致。
- 追根因發現 member_success 沒看到的一層：`.claude/settings.local.json`（**專案層、非部門層**）
  本身就有 **20 條 `mcp__`／Chrome 相關 allow 規則**（`mcp__claude-in-chrome__computer`／
  `navigate`／`form_input`／`file_upload`／`javascript_tool`… 全部在內），且**全專案 deny 是
  空陣列**。部門的 `<dept>.settings.json` 是疊加在這層之上的**第四層**，只會 ADD 允許，
  不會、也無法用來撤銷更外層已授予的東西——這就是為什麼「settings 檔裡沒有 capability 規則」
  仍然打得通：那條門根本不在部門這層，是在專案這層，從一開始就對所有部門敞開。

**結論：member_success 的量測是對的，但根因比他們寫的更淺一層**——不是「registry 授權跟不上
MCP 用法」，是「**MCP 瀏覽器工具從來就不是由 `computer_use` capability 管的，是專案層一直開著，
`computer_use` 機制本身從沒打算去關它**」。

## 2. 裁定：政策文字要收，但不是member_success 提的那個切法

member_success 的 (甲)：整段區分「對外發佈」vs「唯讀查看自家站」，兩邊都要 `computer_use`
宣告。**我採用一半，改一半**：

**唯讀查看自家站根本不在這節政策管的範圍內，不需要宣告 `computer_use`。**

理由：讀這節政策的開頭——「有些工作非得真的開瀏覽器不可——Ivan Lai 個人 FB 發文、粉專貼文、
**需要登入的頁面操作**」——與 `org_attach.py:240-244` 的註解——「computer_use unlocks
what `awaiting_interactive_session` used to park forever」「The canonical script stays
the only door」——兩處合起來，這節政策**從立案起就只針對「代替老闆對外部平台採取行動」**這一類
任務，不是「任何用到瀏覽器 MCP 的任務」。CLAUDE.md 本身另一段就明講「UI 改動要開 dev server
在瀏覽器測」，那從來沒被理解成需要宣告 `computer_use`——因為那本來就是唯讀 QA，不是代替老闆
發言。member_success 把這兩件事讀成同一節管轄，是**過度延伸範圍**，不是政策本身寫錯了範圍
（雖然文字確實模糊到會讓人這樣讀，這點採納member_success的提醒，補上明文）。

**修正後的界線**（已寫入 policy.md）：

- 本節只管「**代替老闆／VolPred 身分對外部平台採取行動**」——發文、留言、任何會被對方平台
  記為使用者行為的操作。這類任務才需要 `computer_use` 宣告 + 只走 canonical 腳本。
- **唯讀查看 VolPred 自己的網站**（驗收、QA、截圖存證，不登入任何第三方帳號、不採取任何
  會被外部系統記錄的動作）— 不在本節管轄範圍，任何部門本來就可以用讀類 MCP 工具做，
  不需要宣告 `computer_use`，也不需要先問治理部。

**member_success 現在就可以做 D48/D56 的驗收**，不需要等任何機制落地。這是本裁定的立即效果。

## 3. 機制面的真正缺口——不是「該不該擋 MCP」，是「擋得到嗎」

member_success 自己標記「這一格請你或 platform_eng 判」的技術問題，覆核如下：

- Claude Code 的 allow/deny 確實可以用**完整 MCP 工具名稱**匹配（`.claude/settings.local.json`
  現有的 20 條就是證據），所以**用 deny 擋掉特定 MCP 工具名稱在技術上可行**。
- 但可行的粒度是**工具名稱**，不是**目標網域**。`computer` / `form_input` /
  `javascript_tool` 這類工具沒有內建的「只能用在 volpred.zeabur.app、不能用在
  facebook.com」這種網域級授權（WebFetch 有 domain-scoped 規則，Claude-in-Chrome MCP
  目前查無同等機制）。這代表：**真正危險的動作（用瀏覽器 MCP 直接對 Facebook 按讚/發文，
  繞過 canonical 腳本的 dedup／idempotency／preflight）目前完全沒有機制擋住**——
  任何部門，不論有沒有宣告 `computer_use`，只要 cockpit pane 連的到老闆已登入的 Chrome，
  都做得到。這不是理論風險：member_success 今天的量測就是**用同一組工具**成功呼叫的證據。

**這才是本案真正該送 platform_eng 判的部分，且比 member_success 原本框的問題更急**——
不是「member_success 的驗收門該不該開」（已在 §2 解決），是「**任何部門本來就能繞過
fb-publishing 唯一入口這件事，現在無人閘門**」。

**建議方向（治理部提出，實作與可行性歸 platform_eng）**：
1. 把 Claude-in-Chrome MCP 工具分兩組寫進 `org_attach.py`：
   - **唯讀組**（`get_page_text`／`read_page`／`navigate`／`tabs_context_mcp`／
     `list_connected_browsers`／`read_console_messages`／`read_network_requests`／`find`／
     `tabs_create_mcp`／`tabs_close_mcp`）——**不受 capability 管，所有部門預設可用**
     （這正是 §2 的裁定要落地成機制）。
   - **互動／可變更組**（`computer`／`form_input`／`file_upload`／`upload_image`／
     `javascript_tool`／`shortcuts_execute`）——**只有宣告 `computer_use` 的部門才給**，
     其餘部門在生成的 `<dept>.settings.json` 明文 `deny`。
2. 承認侷限並記錄：這個 deny 擋的是「沒宣告 computer_use 的部門」，**擋不住已宣告
   `computer_use` 的部門把互動工具用在 Facebook 而非自家網站**——那道最後防線目前仍然只是
   policy.md 的文字約束（「只能透過 canonical 腳本」），不是機械閘門，因為工具層級沒有
   網域粒度可用。**這侷限要老實寫進落地文件，不要因為做了分組閘門就宣稱風險已消除。**
3. `computer_use` 本身的三條 Bash 允許（fb_realchrome_post.py 等）維持不變，這條路徑本來
   就對。

## 4. 為什麼不現在自己動手做機制修法

`scripts/org/org_attach.py` 不在治理部轄區，且此修法涉及對「互動組」工具清單的判斷
（哪些工具算可變更、哪些純唯讀是安全邊界判斷，需要與 platform_eng 一起核對 MCP 工具的
實際行為而非只讀工具名稱猜測）。依組織通則「只寫自己的轄區，發現別人轄區有問題回報經理指派」，
本裁定的 §2（policy.md 文字）由治理部直接落地，§3（org_attach.py 分組）路由給 platform_eng，
非本部門實作。
