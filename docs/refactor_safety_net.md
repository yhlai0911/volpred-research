# 大改重構安全網 + 回滾指令（2026-05-29 建立）

> 用戶 2026-05-29 要「大刀闊斧修改」，要求在丟棄式 branch 上大改、壞掉能完整退回。
> 本檔記錄安全網結構與回滾指令，**compact/clear 後讀此檔即可恢復脈絡**。

## 安全網結構

```
volpred-research/   ← 主目錄，停在 main，autonomous ops loop（codex_loop / hourly-dispatch）繼續不間斷
volpred-refactor/   ← 獨立 git worktree，在 branch refactor/autonomy-overhaul，所有大改在這裡做
```

- **錨點 tag**：`stable-pre-refactor-20260529` — 標記大改前已知良好的 main HEAD（commit `2b252a8f`）
- **重構 branch**：`refactor/autonomy-overhaul`
- **重構 worktree 路徑**：`../volpred-refactor`（相對 volpred-research）= `/Users/yhlai0911/Desktop/volpred-refactor`
- 為什麼用 worktree：daemon 會 commit 到當前 checkout 的 branch；主目錄留 main 讓 ops 不中斷，重構在獨立目錄隔離，符合「不間斷自動化 + 可丟棄大改」雙要求。

## 回滾指令

### A. 丟棄全部重構，回到乾淨狀態（最常用）
```bash
cd /Users/yhlai0911/Desktop/volpred-research
git worktree remove ../volpred-refactor      # ⚠️ 絕不加 --force（CLAUDE.md 硬禁止）
git branch -D refactor/autonomy-overhaul
# main 完全沒被動過，等於重構沒發生過
```

### B. 保留 worktree 但重置回錨點（想重新開始大改）
```bash
cd /Users/yhlai0911/Desktop/volpred-refactor
git reset --hard stable-pre-refactor-20260529
```

### C. 確認 main 本身沒被污染
```bash
cd /Users/yhlai0911/Desktop/volpred-research
git log --oneline -1                         # 應指向重構期間的正常 ops commit 或 2b252a8f
git diff stable-pre-refactor-20260529 --stat  # 看 main 相對錨點被動了什麼（理想：只有 ops/data）
```

### D. 把重構成果合併進 main（重構成功、驗證通過後才做）
```bash
cd /Users/yhlai0911/Desktop/volpred-research
git merge refactor/autonomy-overhaul          # 或先 review diff 再 merge
# 合併後可清 worktree：git worktree remove ../volpred-refactor
```

## ⚠️ branch/worktree 救不回的東西（大改若動到這些，必須各自另外快照）

git 只保護被追蹤的程式碼/config/storage JSON。**以下不會被 `git checkout`/worktree remove 還原**：
- **Supabase DB**（schema / 資料）→ 改前先 DB backup 或寫 migration
- **Zeabur 線上部署的站** → 改前記下當前 deploy，能 redeploy 舊版
- **Mirror API** 狀態
- **OS 層**：`~/Library/LaunchAgents/*.plist`、crontab、`~/.volpred/bin/` wrapper、跑著的 daemon（codex_loop）→ 改前 `cp` 備份 plist / `crontab -l` 快照（crontab 快照已自動存 `storage/ops/crontab_backups/`）

## 相關 ops 風險（2026-05-29 發現，獨立於重構）

本地 main 與 GitHub origin **分叉**：本地領先 269 commit（autonomous loop 長期沒 push）、origin 領先 38 commit（別處推的）。
→ origin/main **不是**本地工作的乾淨備份；269 個本地 commit 未上雲。
→ reconcile（併 38 remote commit 再 push）需小心處理衝突，應在重構 worktree 之外單獨做。
