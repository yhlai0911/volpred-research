# Review Round v6 — vt-trend-following

**Date**: 2026-06-10
**Triggered by**: Task `paper_review_k1458_h1_partial_closure_v6_2026_06_10` (hourly-19).
H1 PARTIAL CLOSURE based on K1458 trough decomposition experiment.
**Reviewers**:
- H1 decomposition evidence: K1458 (`experiments/k1458_h1_trough_decomposition/k1458_results.json`)
- 3rd model adversarial: Codex (see `codex_3rd_review.md`)

---

## Round 概覽

| 欄位 | 內容 |
|------|------|
| Round | 6 |
| 觸發原因 | Gemini v4 H1 concern：「PureVT MDD 改善可能來自機械性 V 型反彈 hedge，而非 vol-timing 本身」 |
| 實驗 | K1458 (`k1458_h1_trough_decomposition`) — 5 assets × 2 troughs × raw arithmetic decomposition |
| 結論等級 | **H1 PARTIAL SUGGESTIVE EVIDENCE（非定案）** — Codex adversarial FAIL → 5 修正點已應用 |
| 範圍限制 | 僅更新 `review_history/v6/README.md`；**不修 body.tex**（另案 `paper_body` task） |

---

## H1 PARTIAL SUGGESTIVE EVIDENCE 摘要（非定案；Codex adversarial review FAIL → 修正後）

### Concern 回顧（v4/v5 Gemini 觸發）

v4 Gemini reviewer 提出：PureVT 策略在 2009-03 與 2020-03 兩次市場底部前後的 MDD 改善，可能並非源自 VIX-level vol-targeting 通道，而是 TSMOM 動量信號翻正後產生的機械性多頭 hedge（即 V 型反彈期間重新加倉）。若主要改善機制是後者，則 H1（「PureVT 透過 vol-timing 壓低 MDD」）過度強調 vol-timing 的因果貢獻。

### K1458 Evidence

K1458 對 5 assets（SPY、50/50、DIA、QQQ、IWM）在兩個 trough 周邊 ±63 交易日窗口（共 127 天）進行原始算術貢獻拆解，分離：
1. **VIX-timing 貢獻**（`vix_timing_arith_sum`）：VT 頭寸縮放相對 BH 的全期超額算術回報
2. **TSMOM hedge 全期貢獻**（`tsmom_hedge_arith_sum`）：TSMOM overlay 相對 PureVT 的全期算術超額
3. **TSMOM hedge（TSMOM<0 日）**（`tsmom_hedge_in_tsmom_neg_days_arith`）：聚焦於 TSMOM 信號負值日（最有可能是機械性 hedge 天）

**2020-03 trough 結果**：4/5 assets 有正的 TSMOM hedge 貢獻（+2.8 到 +12.2 pp），在 TSMOM<0 日的 hedge 更高（中位數 +30.0 pp，SPY +34.6 pp，QQQ +56.1 pp）。機械性 V 型反彈 hedge **確實存在**，但 VIX-timing 在同期呈負貢獻（中位數 -7.8 pp）。PureVT 整體仍輸 BH（中位數 -4.3 pp）。

**2009-03 trough 結果**：3/5 assets TSMOM hedge 全為 0（SPY、DIA、IWM），顯示 rolling-beta 在樣本初期被 clip 至 0，機械性 hedge **幾乎不存在**。50/50 有微量貢獻（+2.1 pp），QQQ 略負（-3.5 pp）。VIX-timing 主導，中位數貢獻 = -5.0 pp（多數資產 PureVT 輸 BH）。

### Evidence Verdict：PARTIAL SUGGESTIVE（Codex FAIL → 已降強度修正）

| 面向 | 結論 |
|------|------|
| 2020-03 機械性 hedge 存在？ | **YES（PARTIAL）** — hedge 貢獻正且可量化，但 VIX-timing 負貢獻抵銷，整體 PureVT 仍輸 BH |
| 2009-03 機械性 hedge 存在？ | **MOSTLY ABSENT（不普遍）** — 3/5 資產 hedge=0，但 2/5 有非零貢獻（50/50 +2.1pp、QQQ ±3.5pp）；整體不普遍，但不能說完全不存在 |
| H1 過度 claim？ | **YES（需修正）** — 不可說「MDD 改善 = 機械性 V 型反彈」，但也不可說「完全是 vol-timing」 |
| 樣本限制 | ⚠️ 10 obs（5 assets × 2 troughs），結論強度有限，須在論文中明標 limitation |

---

## K1458 Decomposition Table

**說明**：所有數值為全窗口（±63 交易日，共 127 天）原始算術貢獻（pp = 百分點）。
- `PureVT_excess_vs_BH`：PureVT 相對 BH 的全期算術超額回報
- `VIX_timing_contrib`：VIX-timing 通道算術貢獻（decomposition identity：`PureVT_excess_vs_BH = VIX_timing_contrib + TSMOM_hedge_full`；僅在 TSMOM_hedge_full=0 時兩者相等，一般情況下是加法組合）
- `TSMOM_hedge_full`：TSMOM overlay 全期算術貢獻
- `TSMOM_hedge_TSMOM<0 days`：TSMOM overlay 在 TSMOM 信號負值日的算術貢獻（機械性 hedge 聚焦窗口）

| Asset | Trough | PureVT_excess_vs_BH (pp) | VIX_timing_contrib (pp) | TSMOM_hedge_full (pp) | TSMOM_hedge_TSMOM<0 days (pp) |
|-------|--------|--------------------------|-------------------------|-----------------------|-------------------------------|
| SPY | 2009-03 | -9.6 | -9.6 | 0.0 | 0.0 |
| SPY | 2020-03 | +3.8 | -8.4 | +12.2 | +34.6 |
| 50/50 | 2009-03 | +6.6 | +4.5 | +2.1 | +11.9 |
| 50/50 | 2020-03 | -4.3 | -7.1 | +2.8 | +30.0 |
| DIA | 2009-03 | -5.0 | -5.0 | 0.0 | 0.0 |
| DIA | 2020-03 | -3.5 | -7.0 | +3.5 | +24.0 |
| QQQ | 2009-03 | +19.4 | +22.9 | -3.5 | +3.3 |
| QQQ | 2020-03 | -11.0 | -14.1 | +3.0 | +56.1 |
| IWM | 2009-03 | -16.1 | -16.1 | 0.0 | 0.0 |
| IWM | 2020-03 | -7.8 | -7.8 | 0.0 | 0.0 |
| **Median** | **2009-03** | **-5.0** | **-5.0** | **0.0** | **0.0** |
| **Median** | **2020-03** | **-4.3** | **-7.8** | **+3.0** | **+30.0** |

**資料來源**：`experiments/k1458_h1_trough_decomposition/k1458_results.json`，`per_asset[asset][trough].headline` 欄位，`generated_at_utc: 2026-06-10T10:17:05Z`。

**注意**：`share_attributable_to_mechanical_rebound_hedge`（比例）僅在分子分母同號時有意義；2020-03 valid_share_count=1（僅 SPY 分子分母同正）。上表一律使用 raw arithmetic contributions，不用不穩定的比例指標。

---

## 結論

### 2020-03 trough

機械性 V 型反彈 hedge **確實有貢獻**，但屬部分貢獻（PARTIAL）：

- TSMOM hedge 在 TSMOM<0 日中位數貢獻 **+30.0 pp**（聚焦 hedge 窗口）；SPY 達 +34.6 pp，QQQ 達 +56.1 pp
- 但 VIX-timing 同期為負貢獻（中位數 **-7.8 pp**），部分抵銷 TSMOM hedge 效果
- PureVT 整體仍輸 BH 中位數 **-4.3 pp**

**機制澄清（inference，非直接量測）**：K1458 量測的是 trough window arithmetic contributions，而非 PureVT 與 BH 的 drawdown path 同步比較，也不是 MDD 壓縮量的直接分解。基於窗口貢獻的間接推論，PureVT 的 MDD 改善較可能來自底部前 VT 縮倉減少最深跌幅，而非底部後 V 型反彈追漲——但這一機制說法需另補 PureVT vs BH 的 drawdown path 直接比較才能確認（K1458 inference, not direct MDD path measurement）。

### 2009-03 trough

機械性 hedge **多數資產缺席（3/5），整體不普遍但非完全不存在**：

- 3/5 assets（SPY、DIA、IWM）TSMOM hedge 全為 0 —— 可能源於 rolling-beta 在樣本初期因 lookback 不足而數值接近 0（K1458 code 有 `clip(0, 0.5)`，但 K1458 未直接量化 beta=0 天數，此解釋屬合理推論而非直接量測）
- 2/5 assets 有非零 hedge：50/50 全期 +2.1pp（TSMOM<0 日 +11.9pp），QQQ 全期 -3.5pp（TSMOM<0 日 +3.3pp）
- VIX-timing 主導，中位數貢獻 **-5.0 pp**（多數資產 PureVT 輸 BH）
- 結論：2009 的機制以 VIX-level vol-targeting 為主，TSMOM hedge 污染程度在多數資產極低，但在少數資產（50/50）有可量化的貢獻

### Narrative 修正建議（供 body.tex v6 另案使用）

現有敘事過強之處：
- **不可說**：「PureVT MDD 改善來自 mechanical V-shape rebound hedge」（過強——2009 無此機制；2020 此機制被 VIX-timing 負貢獻部分抵銷，整體 PureVT 仍輸 BH）
- **不可說**：「MDD 改善完全來自 vol-timing」（過弱——2020 TSMOM<0 日 hedge 貢獻確實存在）

**建議修正說法（已整合 Codex FAIL 修正，降強度）**：「2020-03 trough 附近，TSMOM hedge 在趨勢信號負值日產生正的算術貢獻（中位數 +30.0 pp），但同期 VIX-timing 通道呈負（中位數 -7.8 pp），PureVT 整體仍輸 BH。2009-03 trough 中，3/5 資產 TSMOM hedge 貢獻為零，整體不普遍（K1458 內的 rolling-beta 採 clip(0, 0.5) 設計，樣本初期可能數值極低，但未直接量化）。兩個 trough 的算術貢獻數據在描述性層面（illustrative evidence, N=10）顯示：MDD 改善的主要通道可能是 VT 在底部前的頭寸縮減，但 K1458 未直接量測 PureVT vs BH drawdown path gap，此一機制仍需後續直接驗證。」

### 樣本限制（必須在論文中標明）

⚠️ **K1458 樣本限制**：5 assets × 2 troughs = **10 observations**。統計推斷能力受限，結論屬描述性（descriptive）而非推斷性（inferential）。建議在論文中加 footnote：「Trough decomposition analysis is based on 10 asset-trough observations and should be interpreted as illustrative evidence rather than definitive causal attribution.」

---

## 下一步

| 任務 | 類型 | 優先 |
|------|------|------|
| Section 3.3 / 4.1 narrative 修正（接受 PARTIAL CLOSURE 敘事） | paper_body | P1（另案） |
| 加 K1458 decomposition table 為 Online Appendix | paper_body | P1（另案） |
| Footnote：K1458 10-obs limitation 標明 | paper_body | P1（另案） |
| NEW-H1 abstract CI 描述修正（v5 殘留） | paper_body | P1（另案） |
| H2 K1417 CI table 加入（v5 殘留） | paper_body | P1（另案） |

---

## 本 Round Files

- `README.md`（本文件）— v6 overall verdict + H1 PARTIAL CLOSURE 摘要 + decomposition table
- `codex_3rd_review.md` — Codex adversarial review（narrative claims + data verification）

## Provenance

- K1458 results: `experiments/k1458_h1_trough_decomposition/k1458_results.json` (generated_at_utc: 2026-06-10T10:17:05Z)
- v5 review basis: `paper/vt-trend-following/review_history/v5/README.md` (Jun 10 2026)
- body 審查對象（本 round 不含）：`paper/vt-trend-following/body_v3.tex`（v6 body 另案）
- README initial timestamp: 2026-06-10T11:10:00Z (Taiwan time: 2026-06-10 19:10)
- Codex adversarial review: 2026-06-10T11:14:57Z (Taiwan time: 2026-06-10 19:14) — verdict FAIL (5 findings)
- README post-Codex revision: 2026-06-10T11:15:00Z (Taiwan time: 2026-06-10 19:15) — 5 actionable points applied
