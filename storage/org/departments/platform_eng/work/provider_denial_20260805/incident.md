# P1 執行層全停：provider 拒絕 worker spawn（2026-08-05）

- 部門：platform_eng ｜ 回報層級 **contained 都還不到，是 `root_cause_identified_not_fixed`**
- 工作項：`item_20260805T101737280578Z_dispatch-supervisor-worker-spaw`

## 1. 症狀與證據（五步 Gate 第 1 步）

`dispatch_state.json` 最近三筆 completion 全是
`outcome=provider_policy_denied / exit_code=2 / final_model=claude-opus-5`，
最新一筆 10:15:52Z（本地 18:15），事故**仍在持續**、非歷史殘留。

## 2. 真實拒絕字串（照裁決要求，**沒有**照抄 alerts.py 的猜測）

```
2026-08-05 17:13:20 ERROR provider registry denied worker spawn:
  provider settings bytes do not match the pinned auth surface
17:31:10 / 17:57:09 / 18:06:48 / 18:15:52 同一字串
```

**經理的提醒是對的**：這不是 CLI 升級後 sha 沒進 registry。
executable 的 identity 檢查（`registry.py:884-895`）**已經通過**了——
2.1.220/.221/.222 都在 pin 清單裡，所以流程才會走到後面的 settings 檢查。
擋下來的是 `registry.py:912-919` 的另一道門：**pinned auth surface 的位元組比對**。

## 3. 根因（第 2 步）

`config/provider_registry.json` 的 `claude-cli.auth.settings_surface` 釘住
`.claude/settings.json` 的 sha256 = `95f06ba0c432ad6a…`。

| 版本 | sha256 | 來源 |
|---|---|---|
| 釘住的 | `95f06ba0c432ad6a…` | commit `76e6bfc7c`（2026-07-23） |
| 現在的 | `c4d7ed4e93666fc9…` | commit `e69a0c55c`（**2026-08-05 15:29:14 +08**） |

`e69a0c55c` 的標題是
**「feat(conflict): write-claim guard — concurrent edits can no longer collide silently」**。
它動到 `.claude/settings.json`，但沒有同步更新 registry 裡的 pin。
第一次拒絕是 15:5x、第一封警報 07:58:28Z（15:58 本地）——**時間軸完全對上**。

### 這次的變更是否涉及 auth？**不涉及**（逐鍵比對，非目測）

```
added   (2):
  + hooks.PreToolUse[3].hooks[1].command = python3 .../scripts/hooks/write_claim_guard.py
  + hooks.PreToolUse[3].hooks[1].type    = command
removed (0)   changed (0)
auth-relevant paths touched: <none>
apiKeyHelper present now: False
env block now: {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "62"}
```

`env`、`apiKeyHelper`、base URL、model override 全部沒動。
**所以重新 pin 是安全的**——這道門擋對了（它就是要擋「settings 被改了沒人知道」），
只是這次被擋的是一個良性變更。

### 這是本 session 內第二次同 class

今天稍早查 CI 紅燈時發現：`cron_org_boss_digest.sh` / `cron_org_manager_tick.sh`
兩支新 wrapper 沒跑 `--render-manifest`，`config/cron_wrapper_manifest.json` 因此陳舊，
CI 每次 push 都紅。**同一個形狀**：一個被釘住雜湊的檔案被改了，但沒有人重新釘。
差別只在 cron manifest 有 CI 測試會擋，**auth surface 沒有**——所以它一路 push 到
production 才由 daemon 在 runtime 擋下，代價是執行層全停 2.5 小時。

## 4. 為什麼 1h dedup 會讓一個從未解除的 critical 靜音（經理指定回答）

**不是 1h dedup 幹的。** 實際上有**兩層** dedup，而它們對「條件是否解除」一無所知：

| 層 | 檔案 | 視窗 | 鍵 |
|---|---|---|---|
| 產生端 | `dispatch_state.json` → `alerts_dedup` | **1 小時** | alert class（`provider_policy_denied`）|
| 投遞端 | `storage/ops/alert_dedup.json` | **24 小時** | `(level, title)`（見 `src/volpred/ops/alerts.py:1-13` 自己的 docstring）|

證據（兩邊的帳對不起來，這正是關鍵）：

- 產生端認為它 09:13、10:15 都送了（`alerts_dedup.provider_policy_denied = 10:15:52Z`）
- 投遞端只記錄**一次**：`provider 拒絕 spawn — 派工全停`，
  `send_count = 1`、`last_sent_at = 07:58:28Z`
- 全系統最後一封成功投遞的警報是 08:20:51Z，之後 2 小時**任何警報都沒有**

三個互相咬合的缺陷造成「條件永不解除但訊號永遠不再出現」：

1. **標題是常數**。條件持續 → 每小時產生的信件內容完全相同 →
   永遠打不過投遞端 `(level, title)` 的 24h 雜湊 dedup。
   **越是持續不解除的故障，越保證被靜音**——這是反向的優先序。
2. **產生端不看投遞結果**。`alerts.py:242-243` 呼叫 `_send(...)` 後**無條件**
   `state.mark_alert_sent(key)`，完全忽略 `_send` 的 exit code。
   於是投遞被 dedup 掉、或 `send-alert` 失敗（今天 13:20:13 就有一筆 `exit=-15`），
   產生端的 state 仍然寫「已送出」。**supervisor 的自我認知是錯的**。
3. **這個形狀沒有進 incident 生命週期**。`provider_policy_denied` 在
   `scripts/dispatch_supervisor/` 以外的地方一次都沒出現——沒有 occurrence 計數、
   沒有 episode、沒有升級。`.claude/rules/alert.md` 的內部可自癒路由能把重複條件
   升級成 root-cause 任務，但這個 alert 從來沒被接上去，所以「重複 15 次」和
   「發生 1 次」在系統裡長得一模一樣。

**一句話**：fail-closed 的門 ＋ 常數標題 ＋ 投遞端 24h 內容雜湊 dedup ＋
產生端不驗投遞結果 ＝ 一個永不解除的 critical 保證只叫一次。

## 5. 修法（第 3 步，全部落在 blocked-on-D14 的路徑）

| # | 修法 | 面 | 性質 |
|---|---|---|---|
| A | 重新 pin `settings_surface.sha256` = `c4d7ed4e93666fc9…`（**必須自己算，不可照抄本文**）| `config/provider_registry.json` | 止血，解本次事故 |
| B | 加 CI 檢查：pinned auth surface 必須等於 `.claude/settings.json` 現值，否則紅燈 | `tests/` | **治本**——讓 pin 陳舊在 push 前就被擋，比照 cron manifest 已有的那道 |
| C | `mark_alert_sent` 改成只在 `_send` 回 0 時才蓋章 | `scripts/dispatch_supervisor/alerts.py` | 治本——state 不再說謊 |
| D | 持續性條件的 dedupe key 帶 episode/occurrence（標題含第 N 次），或直接接進 incident 生命週期讓重複自動升級 | `scripts/dispatch_supervisor/alerts.py` ＋ `src/volpred/ops/incident.py` | 治本——解除「越持久越安靜」 |

**A 沒有 canonical CLI**（我查過，registry 是手維護的，這是設計：auth surface 變更
本來就要人審）。所以 A 這一步天生就需要一個有權改 `config/` 的人。

## 6. 尚未完成（第 4、5 步）

第 4 步（重跑一班真實 dispatch、回讀 `dispatch_state` 拿到非
`provider_policy_denied` 的 completion）與第 5 步（制度化）**都還沒做**，
因為 A–D 全部落在 `config/` 與 `scripts/`，本部門的 `owned_paths` 只有
`frontend-v2-fix/`。依 D14 裁決 (a) 停在原地、未繞路。

**所以本輪的誠實回報層級是 `root_cause_identified_not_fixed`——連 contained 都不是，
因為執行層此刻仍然全停。**
