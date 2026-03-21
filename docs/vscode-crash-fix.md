# VS Code 當機問題診斷與修復

## 問題
VS Code 在開啟本專案時會當掉/自動關閉。

## 根本原因分析

| 因素 | 數值 | 影響 |
|------|------|------|
| 專案總大小 | **6.1 GB** | File watcher 需監控所有變更 |
| Git 未提交檔案 | **505 個** | Git extension 對每個檔案做 diff |
| Report JSON 檔案 | **458 個** | 每個 ~10-50KB，全部在 diff 中 |
| .git 目錄 | **108 MB** | Git operations 讀取整個 history |
| Dropbox 同步 | 持續觸發 | Claude + daily_update 修改檔案 → Dropbox 同步 → VS Code file watcher 被持續觸發 |

### 當機流程
```
Claude/cron 修改 storage/*.json（每 15 分鐘）
  → Dropbox 偵測變更，開始同步
  → VS Code file watcher 收到 inotify event
  → Git extension 嘗試 diff 505 個檔案
  → TypeScript language server 也在跑（frontend-v2）
  → 記憶體 > 分配上限 → crash
```

## 修復方案

### 已實施：`.vscode/settings.json`

1. **`files.watcherExclude`** — 排除 storage/, data/cache/, frontend/public/data/ 等自動生成目錄。VS Code 不再監控這些檔案的變更
2. **`search.exclude`** — 全文搜尋排除 458 個 report JSON + lance 檔案
3. **`files.exclude`** — 隱藏 mile_*.json（數百個研究報告），減少 Explorer 負擔
4. **`git.autorefresh: false`** — 關閉 Git 自動刷新（最關鍵！否則每次檔案變更都觸發 git status）
5. **`git.decorations.enabled: false`** — 關閉檔案裝飾（減少 Git extension 工作量）
6. **`typescript.tsserver.maxTsServerMemory: 2048`** — 限制 TS server 記憶體上限 2GB
7. **`editor.minimap.enabled: false`** — 關閉 minimap 減少渲染

### 建議額外措施

#### A. 定期 git commit 減少 dirty files
目前 505 個 modified files 是最大負擔。建議：
```bash
# 把自動生成的檔案加入 .gitignore
echo "storage/knowledge_index/" >> .gitignore
echo "frontend/public/data/reports/" >> .gitignore
echo "frontend/data/reports/" >> .gitignore
echo "data/cache/" >> .gitignore
```
或者定期 commit（已有 cron 每 2 小時 commit）。

#### B. 關閉不必要的 VS Code extensions
以下 extension 在本專案特別耗資源：
- **GitLens** — 如果裝了，建議對本 workspace 關閉
- **GitHub Copilot** — 大檔案會觸發背景分析
- **ESLint / Prettier** — 對 500+ JSON 檔案逐一檢查

在 VS Code 中：`Ctrl+Shift+P` → `Extensions: Disable (Workspace)` 逐個關閉。

#### C. 用 VS Code Remote 避免 Dropbox 衝突
如果問題持續，可以用 VS Code Remote-SSH 或 Dev Container 隔離 Dropbox 同步。

#### D. 增加 VS Code 記憶體限制
在 VS Code `settings.json`（User level）:
```json
{
  "files.maxMemoryForLargeFilesMB": 4096
}
```

或啟動時加參數：
```bash
code --max-memory=4096 /path/to/project
```

## 長期建議
1. 將 `storage/reports/` 和 `frontend/public/data/reports/` 加入 `.gitignore`（已有 Supabase 同步，不需 git 追蹤每個 report）
2. 考慮將專案移出 Dropbox（git + Supabase 已足夠版本控制和同步）
3. 或使用 Dropbox Smart Sync（只下載需要的檔案）
