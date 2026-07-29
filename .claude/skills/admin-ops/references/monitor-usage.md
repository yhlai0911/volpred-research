# Ephemeral Observation

背景觀測只服務當前診斷，不擁有持久工作。

## 使用原則

- 只監看與當前 task 直接相關、已有 owner 的 process／log／receipt。
- 設定有限 timeout、可辨識的 target 與精簡 filter；不要串流整份 log。
- process 完成後讀 terminal receipt；stdout 新增一行不等於 downstream success。
- 觀察跨越互動生命週期時，handoff 給 Operations Core job 或既有 incident/liveness
  owner，不留無 owner 的背景程序。
- 要等待已啟動的 tool／agent，使用該工具的 wait/poll mechanism，不另造 heartbeat。

完成條件：觀測程序已停止或明確 handoff，且最終判斷引用 canonical receipt／live
readback，而不是 observation 本身。
