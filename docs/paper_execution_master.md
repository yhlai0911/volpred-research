# Paper Execution Master — 論文優化執行總表

**建立**：2026-07-12（依 2026-07-11 Fable 深審輪）
**用途**：任何模型、任何 session 要執行論文優化時的**唯一入口**。流程：讀本表 → 挑一篇 → 開它的 `EXECUTION.md` → 複製「接續提示詞」開工 → 完工後更新該檔的進度日誌與 BADGE → commit。
**權威層級**：單篇真相在 `paper/<name>/EXECUTION.md`；本表只是索引視圖，衝突時以單篇為準。深審依據：`paper/<name>/review_history/fable_deep_review_20260711/README.md` + `docs/paper_portfolio_review_20260711.md`。

---

## 使用協議（給接手的模型）

1. **挑工順序**：無特別指示時照下表梯隊順序（Tier 1 先）。
2. **開工**：讀該篇 `EXECUTION.md` 全文 → 從「接續提示詞」section 複製 prompt 執行。每篇的 prompt 自帶完成判準與驗證指令。
3. **紅線**：每篇的「禁止事項」section 是深審排除過的死路/誠實紅線，**不可繞過**。
4. **收工**：更新該篇 EXECUTION.md（勾 DoD、加進度日誌一行含 commit hash、改 BADGE）→ commit。論文 .tex 修改一律主線程做（不派 background agent 寫 .tex）。
5. **投稿前硬 gate**：reproduce gate green + compliance scrub + 跨模型 review（同模型自審 GREEN PASS 不算數 — abm v4 教訓）。

## 執行總表（13 論文 + 1 研究總線）

### Tier 1 — 本月內可投（P0 量級：數天～一週）

| # | Paper | Verdict | 期刊 | P0 狀態 | 下一步（接續 prompt 指向） |
|---|-------|---------|------|---------|---------------------------|
| 1 | [vt-insurance-cost](../paper/vt-insurance-cost/EXECUTION.md) | 3.5/5 GO | **FRL** | ✅ **DONE**（5183318c0 + b0ea148e9；gate 9/9 真 green） | P1：citation C-02–C-09 清理 + 一張主圖 + 91% CI |
| 2 | [leverage-direction](../paper/leverage-direction/EXECUTION.md) | 2/5→修後 3.5 | **IJF** → EmpEcon → JoF | ⬜ TODO | K1592/K1591 證據進稿（6-8 工作天接線，無新實驗） |
| 3 | [vt-crowding-abm](../paper/vt-crowding-abm/EXECUTION.md) | 2/5（證據層 4/5） | **QF** → JEBO | ⬜ TODO | 敘事單一化 + K1471 TF/MR 誠實補報（純寫作一週） |

### Tier 2 — 8 月投稿線

| # | Paper | Verdict | 期刊 | P0 狀態 | 下一步 |
|---|-------|---------|------|---------|--------|
| 4 | [vt-trend-following](../paper/vt-trend-following/EXECUTION.md) | 2/5 | JPM → FAJ | ⬜ TODO | Table 5 國際 13 市場 canonical 重跑（嵌合體修復） |
| 5 | [taiwan-vt](../paper/taiwan-vt/EXECUTION.md) | 3/5 | PBFJ | ⬜ TODO | TWII γ decision package（⚠️ 需 owner sign-off：γ=0.272 證偽→敘事反轉） |
| 6 | [garch-x-vix](../paper/garch-x-vix/EXECUTION.md) | 2.5/5 | IJF → JEF → JoF | ⬜ TODO | 解凍（A4f 假等待點）+ Table 3 canonical 重生 |

### Tier 3 — Gated by 實驗結果

| # | Paper | Verdict | 期刊 | P0 狀態 | Gating 實驗 |
|---|-------|---------|------|---------|-------------|
| 7 | [volatility-absorption](../paper/volatility-absorption/EXECUTION.md) | 2.5/5 | JBF → JEF/IRFA | ⬜ TODO | **make-or-break**：contemporaneous null（過→升級；不過→重框/archive；判定規則事前寫死） |
| 8 | [prg-periodic-garch](../paper/prg-periodic-garch/EXECUTION.md) | 2/5 | FRL | ⬜ TODO（gate RED） | K880 pin + errata；雙時點框架重寫（K1544 裁定） |
| 9 | [vix-sufficiency](../paper/vix-sufficiency/EXECUTION.md) | 2/5 | J.Forecasting（深審建議 IJF 優先） | ⬜ TODO | DM/HAC 全量重算（K1655 class）+ K732/K736 落地 |

### 孵化 / 重建線

| # | Paper | Verdict | 期刊 | P0 狀態 | 下一步 |
|---|-------|---------|------|---------|--------|
| 10 | [btc-gas-negative](../paper/btc-gas-negative/EXECUTION.md) | 3.5/5 | IJF → JoFE → JEF | ⬜ TODO | markdown→LaTeX + reproduce.py + 標題絕對化改（QLIKE-specific） |
| 11 | [eav-universal-magnitude](../paper/eav-universal-magnitude/EXECUTION.md) | 2/5 | IRFA / JIFMIM | ⬜ TODO | magnitude ordering 降級 → sign universality 主軸重寫 |
| 12 | [crypto-fear-channel](../paper/crypto-fear-channel/EXECUTION.md) | 2/5 | JIMFIM → JEF → IRFA → FRL | ⬜ TODO | K1025_v3：FEVD bug 修 + KPPS generalized 重跑（⚠️ Codex 語義複核前禁 ready） |
| 13 | [forecast-tail-divergence](../paper/forecast-tail-divergence/EXECUTION.md) | 3/5 | IJF｜FRL 短文 | ⬜ TODO | E1 尺度再校準 gating（結果裁決完整論文 vs 短文） |

### 研究總線（非論文）

| 檔案 | 內容 |
|------|------|
| [research_execution_plan.md](research_execution_plan.md) | 13 條新實驗方向（P0：方法論債務 sprint / MZ 校準審計 / 迷思 batch 2）+ 兩大 NULL 死弧黑名單 + 資源配比 40/20/25/15 |

---

## 跨論文紅線（每篇開工前都適用）

1. **手稿接線層是主要失效點**：canonical 更新後 .tex 必同步 rebind；表格不可半更新（vt-trend Table 5 嵌合體教訓）。
2. **reproduce gate 只驗 JSON 不驗 .tex 的盲區**：投稿前抽查 .tex 印出數字 vs canonical JSON。
3. **不利證據不可漏報**（abm K1471 / levdir K1591 教訓）— 研究誠實紅線。
4. **同模型自審 GREEN PASS 無效**（第三例確認）：投稿 gate 必須跨模型 review。
5. **任務池對應**：`storage/next_tasks.json` 有 13 個 `fable0711_*` 種子任務對應各篇 gating 實驗。

## 進度日誌

- 2026-07-11 | Fable 深審輪 14 報告 commit | f913ed68c
- 2026-07-11 | vt-insurance P0 finishing（唯一 P0=DONE）| 5183318c0 + b0ea148e9
- 2026-07-12 | 13 篇 EXECUTION.md + 研究執行計畫 + 本總表建立 | （本次 commit）
