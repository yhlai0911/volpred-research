# K1724 — 台股當沖佔比與波動：散戶 herding 的在地量化

**Model**: opus / xhigh (per model_router)
**Task id**: K1724  |  **Type**: experiment  |  **Worktree cwd**: `.claude/worktrees/dispatch-slot-1-f4a65558-k1724`

## 研究問題（grounded in research_program.md open question：散戶行為 × 在地波動微結構）

台灣證交所（TWSE）**免費公布日頻「當日沖銷（當沖）成交比率」**，此資料的完整性與頻率在國際上罕見（多數市場沒有零售當沖的公開日頻序列）。核心問題：

1. **預測力**：當沖佔比對**次日**已實現波動（RV）是否有增量預測力？在 HAR-RV baseline 之上加入當沖佔比，OOS 增量 R² 是否顯著為正？
2. **因果方向（雙向 Granger）**：是「波動吸引當沖」（vol → day-trading，投機者被高波動吸引）還是「當沖放大波動」（day-trading → vol，散戶 herding 推高波動）？還是雙向回饋？

來源脈絡：JFQA / Journal of Empirical Finance 2024–25 對零售交易與波動的實證線。

## 資料（全部免費，先讀 `.claude/skills/external-data-sources`）

- **當沖佔比**：TWSE 日頻當日沖銷交易統計（大盤層級整體當沖比率；若可取得個股彙總更佳，但先以大盤 aggregate 起步）。查 external-data-sources skill 的 TWSE 取用方式；若該 skill 未涵蓋此端點，記錄實際使用的 TWSE OpenAPI / 每日交易統計 endpoint 與欄位到 README 的 provenance 段。
- **台股 RV**：`^TWII`（TAIEX）日頻，用 yfinance；RV proxy 用日頻可得的 range-based estimator（Parkinson / Garman-Klass，因無免費 intraday）或 squared returns，明確標註 proxy 選擇與其限制。
- 樣本期：盡量取最長可得重疊期（TWSE 當沖統計約 2014 起放寬後較完整；以資料實際可得為準）。

## 方法

1. **對齊**：當沖佔比 series 與 TWII RV 對齊到交易日；處理缺值/停牌。做 summary stats（表）。
2. **Baseline**：HAR-RV（RV_d, RV_w, RV_m）預測 next-day RV。
3. **Augmented**：HAR-RV + lagged 當沖佔比（及其 w/m 平均）。比較 in-sample fit 與 **OOS**（rolling / expanding，明確窗長）增量 R²、QLIKE、Diebold-Mariano 檢定 vs baseline。
4. **雙向 Granger**：VAR(p)（p 用 AIC/BIC 選）在 {RV, 當沖佔比} 上，兩個方向的 Granger F-test；報 lag、F、p。討論同期相關 vs 領先落後。
5. **穩健性**：子期（如 COVID 前後）、RV proxy 替換、控制大盤報酬與成交量。

## 交付物（寫到 worktree 的 `experiments/k1724/`）

- `k1724.py` — 完整可重跑腳本（資料抓取→對齊→模型→檢定→輸出）。
- **`k1724_results.json`** — 結構化結果（sample 期間與 N、summary stats、baseline vs augmented 的 IS/OOS 指標、DM 統計與 p、雙向 Granger 的 F/p/lag、robustness 摘要、每個數字的 provenance）。**此為成功後置條件檔，路徑必須存在。**
- 至少 1 圖（如 OOS QLIKE / 增量 R² by 子期，或當沖佔比 vs RV 疊圖）存 `experiments/k1724/`。
- `README.md` — 研究問題、資料 provenance（含實際 TWSE endpoint）、方法、**誠實結論**（含 NULL 情形）、限制。

## 誠實與驗證（HARD RULES）

- **研究誠實 > 一切**。若當沖佔比無增量預測力或 Granger 不顯著，**如實報 NULL**，不得美化、不得捏造數字。所有 JSON 數字必來自實際計算，禁止 placeholder。
- 完成後**自我核實**：README 宣稱的每個關鍵數字都要能在 `k1724_results.json` 對上（agent-result-verification skill 精神）。
- **Codex 二審**：完成後用 `codex exec`（codex-cli skill）對方法與數字做一次獨立審查，把 verdict 摘要記進 README。若 Codex 指出方法瑕疵（如 RV proxy 偏誤、Granger 前未檢定定態），修正後再跑。
- 定態檢查：Granger 前對 RV 與當沖佔比做 ADF；非定態則差分或說明。

## 邊界

- 只在此 worktree 內寫檔；不碰 feed.json / supabase / next_tasks.json / knowledge.json。
- 不做 reader-facing 發佈（本任務是研究，不是文章）。
- 若 TWSE 當沖日頻資料實際無法免費取得或覆蓋太短 → 在 README 記錄實際限制、把 `k1724_results.json` 標為 `status: blocked_on_data` 並說明，不要編數字硬湊。
