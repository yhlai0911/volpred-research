# AI 協作模式（Claude + Codex + Gemini）

## 角色分工

| AI | 角色 | 使用方式 | 擅長 |
|---|---|---|---|
| **Claude**（主研究員）| 實驗執行、分析、記憶管理、論文寫作 | 直接執行 | 深度分析、code、持續研究 |
| **Codex (GPT)**| 針對性審查、第二意見、新方向 | `/codex:rescue`、`/codex:review`、`codex exec` | 找漏洞、結構性問題、editorial advice |
| **Gemini** | 方法論建議、文獻連結、robustness 建議 | `/gemini-cli` | 學術框架、cross-reference、新測試建議 |

## Codex Plugin 命令

| 命令 | 用途 |
|------|------|
| `/codex:rescue` | 委派特定任務（審查、診斷、修正建議） |
| `/codex:review` | Git diff 代碼審查（需指定 scope） |
| `/codex:adversarial-review` | 對抗性審查（挑戰設計決策） |
| `/codex:status` | 查看背景任務進度 |
| `/codex:result` | 取得背景任務結果 |
| `/codex:cancel` | 取消背景任務 |
| `/codex:setup` | 檢查 Codex 就緒狀態 |

**使用原則**：針對特定目標，不掃全專案。不要用 `--scope working-tree`。

## `/codex:rescue` 使用時機（必須遵守）

- **Bug 改很多次還是錯** → 停下來，用 `/codex:rescue` 換 Codex 接手重新分析
- **程式越修越壞** → 不要再修，直接 `/codex:rescue`
- **多檔案/邏輯複雜** → 用 Codex 的全局視角
- **Token 快用完**（避免思路斷掉）→ 趁還有 context 讓 Codex 接手
- **ML/非標準模型代碼審查** → 實驗完成後必須 `/codex:rescue` 審查再記錄 knowledge

**一句話：卡住 or 快沒 token → 直接 `/codex:rescue`，不要繼續自己掙扎。**

記得開啟 `--full-auto` 模式讓 Codex 自主修復。

## 研究主題來源（必須多元）

研究主題不可只靠 Claude 自選。必須來自：
1. 用戶指定（最高優先）
2. Codex/Gemini 建議
3. 會員問題
4. 文獻搜索
5. 跨 AI 交叉驗證
