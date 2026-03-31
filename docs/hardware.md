# 硬體資源與 Agent Team 工作分派

## 硬體規格

| 項目 | 規格 |
|------|------|
| CPU | Apple M1 Max · 10 核心 |
| RAM | 64 GB |
| 平行 agent 建議 | 3-4 個 worktree agent 同時跑（每個 ~1GB RAM） |
| GARCH 估計速度 | ~6ms/model（單核） |
| Bootstrap 10,000 reps | ~2-5 秒 |
| 大規模 sweep（100 configs） | ~1 分鐘（單核串行） |

設計分析程式時參考：
- 可用 `multiprocessing` 平行化 cross-asset sweep（10 核 → 10 資產同時跑）
- 64GB RAM 足以載入全部資產的完整歷史（~500MB total）
- Agent worktree 每個 ~800MB，同時 4 個 = 3.2GB（無壓力）

## Agent Team 工作分派

Claude Code 的 Agent 工具可啟動獨立子程序（subagent），有自己的 context window 和工具權限。
**優先使用 agent team 並行分派任務**，同時推進 3-4 個方向以最大化效率。

### 模型選擇原則（必須遵守）
**根據任務複雜度與難易度選擇適當模型：**

| 任務類型 | 模型 | 原因 |
|---------|------|------|
| **研究實驗**（GARCH、統計檢定、策略回測） | `model: "opus"` | 精確性與專業性要求高 |
| **程式開發**（前端、後端、bug 修復） | `model: "opus"` | 程式碼正確性關鍵 |
| **統計分析**（DM test、bootstrap、cross-OOS） | `model: "opus"` | 數學嚴謹性不可妥協 |
| **論文寫作/審查** | `model: "opus"` | 學術品質要求 |
| **知識合成**（meta-analysis、投資指南） | `model: "opus"` | 需要深度推理 |
| 簡單搜尋（grep、檔案查找） | `subagent_type: "Explore"` | 快速唯讀，不需重模型 |
| 簡單文章撰寫（feed 文章） | `model: "sonnet"` 可接受 | 創意寫作彈性較大 |
| 規劃與架構 | `subagent_type: "Plan"` | 結構化思考 |

**規則：研究、分析、程式等精確性與專業性工作，務必使用 opus 模型。不確定時預設 opus。**

### 核心參數
- **`isolation: "worktree"`**：在獨立 git worktree 執行，不影響主分支檔案
- **`run_in_background: true`**：背景執行，主對話可繼續其他工作，完成時自動通知
- **`model: "opus"`**：指定使用 Opus 4.6 (1M context) 模型（研究/分析/程式必用）
- **`subagent_type`**：`general-purpose`（預設，可寫檔）、`Explore`（唯讀，快速搜尋）、`Plan`（規劃）
- **`resume: "agentId"`**：用之前的 agent ID 恢復已完成 agent 的 context 繼續工作
- 多個獨立 Agent 可在同一訊息中**並行啟動**，大幅提升效率

### 任務對應設定

| 任務類型 | Agent 設定 | 說明 |
|----------|-----------|------|
| 研究實驗 | `isolation="worktree"`, `model="opus"` | 跑 GARCH、統計測試，不影響主目錄 |
| 並行實驗 | 多個 `isolation="worktree"`, `model="opus"` 同時發送 | 同時跑多資產/多模型 |
| 背景部署 | `run_in_background=true` | upload-codebase frontend-v2，不阻塞研究 |
| 代碼探索 | `subagent_type="Explore"` | 快速搜尋代碼結構（唯讀） |
| AI 協作 | `/codex-cli`, `/gemini-cli` | 研究建議、審查、新方向 |
| 文獻搜尋 | `Agent + WebSearch` | 最新方法、論文 |
| 高品質發文 | 用 `feed-publisher` skill | Agent 寫完整文章再發佈 |
