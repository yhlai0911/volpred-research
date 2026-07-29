# Platform API / CLI Contract

本檔不複製完整參數；每次操作前以 live help 與 route source 為準。

```bash
uv run volpred ops --help
uv run volpred ops <command> --help
```

## 共通 sequence

1. **Summary**：先跑對應 summary／show／health command，保存 before identity 與狀態。
2. **Mutation**：使用正式 CLI 或 Admin API；不要直接改 canonical file 或 remote row。
3. **Receipt**：保存 action、target identity、request/dedupe key、status、effect id 與
   evidence reference。非終態 receipt 不算完成。
4. **Readback**：以另一個 read surface 查 exact target；列表總數或 process exit 0 不足以
   證明送達。
5. **Reconcile**：readback mismatch 進既有 retry／incident lifecycle，不手工補值。

## Domain routing

| Domain | Read first | Mutation owner | Independent readback |
|---|---|---|---|
| 內容 | `feed-publisher` | publisher CLI | public publication endpoint |
| 會員問題 | `member-questions` | question CLI | question summary + linked public article |
| 策略 | `strategy-lifecycle.md` | strategy CLI | strategy overview API |
| 論文交付 | `paper-list` | paper CLI | public paper metadata/PDF |
| 同步 | `sync-all`／domain summary | sync CLI | remote row + reader projection |
| ops job | `jobs`／`job-show` | enqueue/worker lifecycle | terminal job + effect receipt |
| deploy | `deploy-and-runtime.md` | active frontend safe wrapper | provider state + live route |

Mutation command 的輸出只是第一份 evidence。若下游是 Supabase、Mirror、email、Telegram、
Zeabur 或 reader cache，必須再讀對應 provider／public surface。

## 錯誤處理

- validation failure：修 payload 或 owner contract，重新走同一路徑。
- provider retryable failure：保留同一 logical request identity，走既有 retry。
- ambiguous outcome：先 readback；不可直接重送可能非冪等的操作。
- 缺少 canonical surface：標 `blocked` 或實作 shared surface；不要用一次性旁路收尾。
