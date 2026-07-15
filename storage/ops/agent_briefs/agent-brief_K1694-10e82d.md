# K1694 — FCM 清算集中度是否在高波動期排擠小型交易者並放大商品流動性風險

**Model**: opus / xhigh (per model_router)
**Task type**: experiment（worktree topology；本 job 由 compute worker 執行）
**Task id**: K1694（starvation-released，aged >72h）

## 研究問題
用 CFTC 月度 **FCM customer-segregated assets** 算清算集中度（HHI），檢定：FCM 集中度在**高波動期**是否排擠小型交易者、放大商品流動性風險？接 CFTC DCOT 的 **non-reportable**（小型交易者）部位變化作為排擠的代理。

## 開工前必讀（研究誠實，最高優先）
1. `AGENTS.md` §研究誠實原則（尤其 #2 資料來源透明、#6 觀察先於計算、#7 正式檢定、#11 lookahead、#12 seed、#F provenance/發布日）。
2. `.claude/rules/experiments.md` §Methodology 硬規則。
3. `docs/error_log.md` Class F（發布日/vintage）與 Class G（方法論）。
4. `.claude/skills/external-data-sources`（CFTC 取用方式、發布日陷阱）。knowledge.json 檢索既有 FCM / 集中度 / 流動性 K。

## 資料（provenance 是最高風險）
- CFTC 月度 FCM financial data（customer-segregated / secured amount）→ 算 HHI 集中度。
- CFTC DCOT（Disaggregated COT）non-reportable positions（小型交易者代理）。
- 波動：對應商品的 realized vol（如能源/金屬/農產期貨或綜合指數）。
- **按實際發布日 lag**（HARD）：CFTC 報告有發布時滯，訊號必用**發布當日可得**的 vintage，嚴禁用 as-of 日期造成 lookahead（Class F 教訓）。標明每個數據的 as-of 日 vs 發布日。

## 方法（必含正式檢定）
1. **觀察先於計算**：HHI 時序、與波動的散佈、high-vol vs low-vol regime 分組描述統計。
2. **排擠假說**：high-vol 期 FCM 集中度上升 → non-reportable 部位/佔比下降？用 regime split 或交互項回歸，控制商品固定效果與時間趨勢。
3. **明確 lag**：集中度/波動訊號在 t（發布可得），排擠結果在 t 或 t+1；`shift` 明示。
4. **顯著性**：HAC 標準誤（lag 依 acf 定，不可只用 h-1）；panel 需 cluster；bootstrap 固定 seed。
5. **Null 如實報告**。

## 交付（三件套 + 圖表）
- `experiments/K1694/README.md`（設計、資料來源/期間/樣本數/發布日處理、方法、結論、局限）
- `experiments/K1694/K1694.py`（可重跑、固定 seed、發布日 lag 明示）
- `experiments/K1694/K1694_results.json`（統計量、p 值、樣本數）
- 圖表（HHI 時序 / regime 對照 / 排擠關係）
- 過 `uv run python scripts/experiment_gates.py run --path experiments/K1694`（PASS 才算完成）

## 誠實邊界
資料樣本可能偏短（月度 FCM）→ 結論強度須節制；區分相關與因果；承認局限。發布日處理任何不確定處如實揭露。
