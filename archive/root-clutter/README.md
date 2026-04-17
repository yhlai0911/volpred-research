# Root Clutter Archive

這個目錄用來集中根目錄中明顯不屬於正式執行路徑的雜項。

- `tracked/`：原本已被 git 追蹤、但不適合繼續放在 repo 根目錄的歷史或暫存檔案。
- `local/`：只存在本機、不需要納入版本控制的舊版、快取、備份與臨時輸出。

目前 active code path 仍然是：

- `src/`
- `scripts/`
- `storage/`
- `config/`
- `frontend-v2-fix/`
- `agent-specs/`
- `.claude/` / `.agents/`

若未來再做根目錄整理，優先把低風險的暫存或 legacy 項目收進這裡，不要直接刪除。
