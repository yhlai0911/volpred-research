---
name: feedback_cross_machine_file_links
description: Mac Studio 是遠端機；要給用戶看的圖/檔/連結一律用 SendUserFile 或 Tailscale URL，不丟本機路徑
metadata: 
  node_type: memory
  type: feedback
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

當 session 跑在 Mac Studio（`100.120.217.40` / `mac-studio.tail5a659f.ts.net`）而用戶從別台機器（如 `ivanlaimacbook-pro`）經 Tailscale 連入時：**任何要讓用戶看的圖片、檔案、連結，都必須是跨機器點得到的**。

具體做法：
- 要給用戶看的產出（圖表 PNG、草稿 MD、報告）→ 用 `SendUserFile` 直接推到對話視窗（最穩，不依賴路徑/網路路由）。
- 要給可點連結 → 用 Tailscale 位址（`http://100.120.217.40:<port>` 或 `mac-studio.tail5a659f.ts.net`），不要丟 `127.0.0.1`/`localhost`。
- 本機絕對路徑（`/Users/yhlai0911/...`）只能當「檔案在 Mac Studio 上的位置」備註，**不能當成用戶可開啟的連結**——用戶那台機器開不了。
- 公開網址（`volpred.zeabur.app/...`）不受影響，公網任何機器可達。

**Why**：用戶 2026-06-14 兩次糾正——Mac Studio 不是他面前的本機，丟本機路徑等於沒給。
**How to apply**：每次想讓用戶「看」某個 local 產物前，先問「他從 MacBook 點得到嗎？」答否 → SendUserFile 或 Tailscale URL。

相關：[[reference_work_dashboard]]（dashboard 在 127.0.0.1:8787，跨機器要走 Tailscale IP）。
