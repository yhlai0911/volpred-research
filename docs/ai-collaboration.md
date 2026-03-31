# AI 協作模式（Claude + Codex + Gemini）

三個 AI 各有分工，不只是評審——也是研究夥伴。

## 角色分工

| AI | 角色 | 使用方式 | 擅長 |
|---|---|---|---|
| **Claude**（主研究員）| 實驗執行、分析、記憶管理、論文寫作 | 直接執行 | 深度分析、code、持續研究 |
| **Codex (GPT)**| 針對性審查、第二意見、新方向 | `/codex:rescue`、`/codex:review`、`codex exec` | 找漏洞、結構性問題、editorial advice |
| **Gemini** | 方法論建議、文獻連結、robustness 建議 | `/gemini-cli` | 學術框架、cross-reference、新測試建議 |

## Codex Plugin 可用命令（openai/codex-plugin-cc v1.0.1）
| 命令 | 用途 | Claude 可呼叫 |
|------|------|--------------|
| `/codex:rescue` | 委派特定任務（審查、診斷、修正建議） | Yes |
| `/codex:review` | Git diff 代碼審查（需指定 scope） | Yes |
| `/codex:adversarial-review` | 對抗性審查（挑戰設計決策） | Yes |
| `/codex:status` | 查看背景任務進度 | Yes |
| `/codex:result` | 取得背景任務結果 | Yes |
| `/codex:cancel` | 取消背景任務 | Yes |
| `/codex:setup` | 檢查 Codex 就緒狀態 | Yes |

## 使用原則：針對特定目標，不掃全專案
- Audit single experiment: `/codex:rescue "Review experiments/kXXX.py for bugs"`
- Paper specific section: `/codex:rescue "Check Section 3 methodology in paper/xxx/main.tex"`
- Adversarial challenge: `/codex:adversarial-review --wait --base HEAD~1`
- Git diff review: `/codex:review --wait --scope branch --base HEAD~3`
- Do NOT use `--scope working-tree`（scans entire project）
- Do NOT aimlessly "let Codex look" — must have specific question or file
- `codex exec` is a fallback; prefer plugin commands

## 協作場景
- **論文審查**：三方各自審查 → Claude 整合修正
- **研究方向探索**：問 Codex/Gemini「接下來該研究什麼？」「有什麼盲點？」
- **新策略發想**：讓 Gemini 建議新的投資策略或風控方法
- **方法論驗證**：Gemini 建議用 EGARCH 驗證 → Claude 執行 → 確認 proposition robust
- **系統功能**：讓 Codex 幫忙寫程式、debug、優化架構

## 不要只當評審用
Codex 和 Gemini 可以：
- 提出新研究假說
- 建議尚未探索的文獻方向
- 幫忙設計實驗
- 生成論文段落草稿
- 延伸研究到新資產/新市場

## 研究主題來源（必須多元，不能只靠 Claude 自選）
研究主題的來源應該包括：
1. **Codex/Gemini 建議**：每 5-10 個實驗主動問一次「接下來該研究什麼方向？」，將建議寫入 research_program.md
2. **用戶指定**：用戶提出的方向**優先執行**，且**必須立刻寫入 research_program.md**（不能只口頭回應或只在記憶中記錄）
3. **會員問題**：每 6 小時 cron 自動評估會員提問
4. **文獻搜索**：WebSearch arXiv/SSRN 發現的前沿方向
5. **Claude 自選**：基於 research_program.md 的待探索方向
6. **跨 AI 交叉驗證**：一個 AI 提出假說 → 另一個 AI 設計實驗 → Claude 執行

**標準流程**：每開始新一輪實驗前，先問 Codex 或 Gemini「給我 3-5 個研究方向」→ 從中選擇 → 標注 `[提出: Codex/Gemini]` → 執行
