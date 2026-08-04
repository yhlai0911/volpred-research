# 接手：backbone 封鎖（worker spawn 被 forbidden env 擋死）

建立：2026-08-04 12:48（台灣時間）
狀態：**進行中 — 全部派工停擺**
Task：`assign_ec2a9ee7`（P1）

## 一句話

dispatch supervisor 每次 fire 都被 provider registry 拒絕，
理由是被驗證的 child env 含 `OPENAI_API_KEY`。
**它自己也是一張 P1 派工任務，所以救不了自己 —— 必須由主線程直接處理。**

## 為什麼緊急

這是「看起來健康」的故障：`ops_snapshot` 全綠、heartbeat 新鮮、supervisor 活著、
fire 照排程觸發 —— 但**零執行**。目前已有 3 張 P1 卡住：

- `assign_ec2a9ee7` 本單
- `assign_ce6097bf` k1308/k1399 統計量重跑（兩篇已發佈文章的 erratum 等它）
- `assign_078bd8a2` tombstone 埋掉未竟事項的機制缺口

## 症狀（live）

```
ERROR [dispatch_supervisor.worker] provider registry denied worker spawn:
  provider environment contains forbidden API-key/alternate-auth variables ['OPENAI_API_KEY']
INFO  worker returned outcome=provider_policy_denied attempts=1 duration=0.0s
```

自 2026-08-04 12:38 起每次 fire 皆然。查驗指令：

```bash
grep "provider registry denied\|provider_policy_denied" ~/.volpred/logs/dispatch_supervisor.log | tail -5
```

## 前一道關卡已修 —— 不要重做

同一時段還有另一個拒絕原因：`executable identity is not pinned`。
根因是 Claude CLI 在 12:00 自動 `2.1.220 → 2.1.221`，而 registry 用 sha256 釘死身分。

已於 **commit `8c7d261cb`** 把 2.1.221 加入 `config/provider_registry.json`：
sha `7a181f36ed0fc4fbac6cee4ecf2b615eff93d8b434221fff5d7c878dc5ebf380`，
**用 `shasum -a 256` 獨立驗證過，不是照抄 log**；2.1.220 保留作滾動視窗。

修完後拒絕訊息**確實換成本單這一個** —— 這就是那關已過的證據。

## 已排除的四條路（不必重走）

1. **supervisor process 環境乾淨** —— `ps eww -p <pid>` 僅 11 個變數：
   `HOME LOGNAME PATH SHELL SSH_AUTH_SOCK TMPDIR USER
   VOLPRED_CODEX_FAILOVER VOLPRED_WRITER_ISOLATION_REQUIRED XPC_FLAGS XPC_SERVICE_NAME`
   —— **沒有** `OPENAI_API_KEY`
2. **plist 乾淨** —— `EnvironmentVariables` 只有
   `VOLPRED_WRITER_ISOLATION_REQUIRED / VOLPRED_CODEX_FAILOVER / PATH / HOME`
3. **`.env` 不是路徑** —— 它確實含此 key，但 mtime 自 2026-07-02 未變，
   且 `scripts/dispatch_supervisor/` 全樹 **無任何 `load_dotenv`**
4. **isolation 走白名單** —— `isolated_environment` 只放行
   `_PASSTHROUGH_ENV`（isolation.py:308）∪ `_PROVIDER_AUTH_ENV['claude-cli']`
   （僅 `CLAUDE_CODE_OAUTH_TOKEN`）；此 key 兩邊都不在

**所以矛盾尚未解開**：被驗證的 env 含此 key，但已知的三個來源都乾淨。

## 下一步該查哪裡

驗證點：`scripts/dispatch_supervisor/worker.py:679`
→ `authorize_provider_spawn(contract_id="dispatch-supervisor.claude", ..., environment=child_env)`

`child_env` 有三個賦值點：

| 行 | 來源 |
|---|---|
| 493 | `external_child_environment(...)` |
| 626 | `external_child_environment(overrides={VOLPRED_ACTOR...})` — 繼承 `os.environ` 扣掉 supervisor-private |
| 655 | `isolation.isolated_environment(...)` — 白名單 |

先確認**這次 fire 實際走了哪個分支**。若走 626，就要解釋 supervisor `os.environ`
明明乾淨為何驗證時有此 key（可能是 `external_child_environment` 的 base 不是我以為的那個）。

加 diagnostic 時 **只印 key 名單、不印 value**。

## 一個設計判斷（請先想清楚再改）

若確認 `OPENAI_API_KEY` 是 **Codex 合法需要**而非洩漏，那問題就不是「有髒東西」，
而是「claude-cli 的 `forbidden_env` 與同機要跑 Codex」這個設計衝突。

正解可能是：**spawn 路徑在驗證前就 strip 掉 forbidden 變數（fail-safe）**，
而不是整體 fail-closed。

**不要為了讓它動就放寬 `forbidden_env` 清單。** 那份清單存在的理由是防止
claude-cli 誤用替代 auth（見 `config/provider_registry.json` 的 forbidden_env 註解）。

## 成功標準

worker 真的 spawn 成功（`current_job` 出現且 `phase=running`），
且 `provider_policy_denied` 計數停止增加。附一次真實 fire 的 live 回讀，
不接受「改完應該就好了」。

## 相關

- 內容誠信那條線的交接：`docs/handoffs/2026-08-04_snapaudit_errata_continuation.md`
- 本輪其他修復：`8c7d261cb`（provider pin）、`4258631ae`（snapaudit handoff）
