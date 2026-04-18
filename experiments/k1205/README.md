# K1205 — Paper 3 K1128 OFI-Jump Regime Synthesis (4-branch NULL panorama)

**Type**: Pure synthesis (no new estimation)  
**Date**: 2026-04-17  
**Seed**: 42  
**Data**: TAIFEX TX 5-min bars, 2017-2021 (K1124 cache), 73,203 bars, 115 Lee-Mykland K=16 jumps (alpha=0.01, Gumbel threshold 5.1256)

---

## 1. K1128 Story — 一句話

Paper 3 的 leverage-direction 外延假設 OFI->jump 的預測力會隨 VIX-regime 變化。主線程原設計是 VIX 三分位 IS-fixed cutoffs (K1128)，但 2020-2021 COVID VIX 分布與 2017-2019 完全脫節，造成 OOS 覆蓋退化 (0/854/20060)。三個互補 branch (K1131 連續 spline、K1142 vol-norm、K1199 expanding-window) 全部用來補救這個核心假設。K1205 把四者合成成一張「K1128 4-branch NULL panorama」供 Paper 3 narrative pivot 決策。

## 2. 4-Branch Canonical Synthesis Table

（完整 JSON 在 `k1205_results.json`；CSV 在 `k1205_synthesis_table.csv`。）

| Exp  | Branch | Focal model | n_OOS | OOS jumps | AUC | LL_OOS | Brier | DM t | Verdict |
|------|--------|-------------|-------|-----------|-----|--------|-------|------|---------|
| K1128 | VIX tertile (IS-fixed) | M3_tertile_high | 20,060 | 32 | 0.5926 | 0.01196 * | 0.001592 | +1.31 | NULL (degenerate OOS coverage) |
| K1131 | Natural cubic spline | M_spline | 20,914 | 33 | 0.4965 | 0.01248 | NA | -3.93 | NULL |
| K1142 | Vol-normalized OFI (sigma_60) | M_volnorm | 20,914 | 33 | 0.5940 | 0.01165 | 0.001574 | +2.25 | PARTIAL_OOS_ONLY |
| K1199 | Expanding-window VIX quantile | M_expanding | 20,914 | 33 | 0.5484 | 0.01165 | 0.001574 | +1.14 | NULL |

\* K1128 raw JSON records `ll_oos` as negative log-loss (log-likelihood per obs); sign-flipped in the synthesis for comparability with K1131/K1142/K1199 positive log-loss convention. DM t-statistic is reported verbatim (sign unchanged).

**讀圖**：Figure A (4-panel panorama) / Figure B (OOS regime coverage) / Figure C (AUC ranking)。PDF + PNG 300 dpi 雙格式。

## 3. Numerical Integrity Check — 7/7 PASS

完整 `k1205_integrity_report.txt`；重點摘要：

- **Lee-Mykland 總跳躍數**：K1128/K1131/K1142/K1199 全部回報 115，Gumbel 臨界值 5.125598 四實驗一致 → 無資料洩漏或方法論漂移。
- **IS VIX tertile cutoffs**：K1128/K1131/K1199 三個實驗三組 cutoff_33=12.07, cutoff_67=14.99 完全一致。
- **M_base 係數**：K1131 與 K1199 的 M_base (intercept + jump_curr + |OFI| + OFI) 係數逐位相同到 1e-6。K1142 M_base NLL 略低 (556.95 vs 557.06)，原因是 K1142 強制 sigma_60 strict-past 非 NaN，丟棄 43 row (n_valid=52,369 vs 52,412)，非 bug。
- **K1128 coverage gap**：Full OOS 20,914 - K1128 high-tertile 20,060 = 854，正好是 K1128 mid-tertile 的 n_oos=854 → coverage 退化如實可追溯。
- **K1142 vs K1199 M_volnorm AUC 差異**：K1142 AUC_oos=0.5940、K1199 同名 M_volnorm AUC_oos=0.6712。**這是實作差異，不是 divergence bug**：K1199 在 sigma_60 rolling 缺失時 fallback 到 Lee-Mykland BV sigma，K1142 嚴格丟棄。**Paper 的 vol-norm canonical number 採用 K1142 的 0.5940**（K1142 是專屬 vol-norm 實驗，方法論最乾淨）。

結論：**無 cross-experiment divergence 疑慮**；四個 branch 共享同一 TAIFEX 5-min cache 與 jump 偵測，只在各自 branch 特定 feature set 或 regime 定義上有差異，全部可追溯、全部記錄在原 JSON。

## 4. Narrative Pivot Decision Matrix

| Path | Evidence strength | Feasibility | Reviewer risk | Cost |
|------|-------------------|-------------|---------------|------|
| (a) Full K1142 vol-norm anchor | **PARTIAL** — single cell AUC 0.594, DM t=+2.25, n_jumps=33；|t|<3 不過 Harvey (2016) | **HIGH** — K1142 已完整 | **HIGH** — 單一 positive cell + 統計力不足 (33 OOS jumps)，審稿人易質疑 overfitting | 需丟棄 K1128/K1131/K1199 全部敘事素材 |
| (b) Hybrid null + positive | **COMPLETE** — 4-branch honest null 含一個 partial positive，構成完整方法論故事 | **MEDIUM** — 敘事較複雜 (要解釋 leverage-direction 為何失敗 AND vol-norm 為何部分成功) | **MEDIUM** — Honest negative result + 替代機制是 JoE / IJF / PBFJ 可發表定位 | 保留全部實驗，reframe 為 "regime-switching 失敗 + vol-norm 作為替代" |
| (c) Abandon leverage-direction | N/A (K1142 保留另行投稿) | **HIGH** | N/A | 一年 K1128 story 研究沉沒成本 |

## 5. Recommendation (≤50 字)

**推薦 Path (b) Hybrid null+positive**：4-branch honest null + K1142 vol-norm partial 適合 negative-result methodological paper，evidence 完整且不過度宣稱。

（最終決策權在主線程 / 用戶，K1205 不替主線程下決定。）

## 6. Files in `experiments/k1205/`

| File | Purpose |
|------|---------|
| `README.md` | 本文件 |
| `k1205.py` | Synthesis script (pure aggregation) |
| `k1205_figures.py` | Figure A/B/C generator (300 dpi PNG+PDF) |
| `k1205_results.json` | Consolidated canonical numbers + decision matrix |
| `k1205_synthesis_table.csv` | 4-branch panorama CSV |
| `k1205_integrity_report.txt` | 7-check cross-experiment integrity log |
| `k1205_figureA_panorama.{png,pdf}` | 4-panel bar chart (AUC / LL / Brier / DM t) |
| `k1205_figureB_regime_coverage.{png,pdf}` | OOS VIX tertile coverage comparison |
| `k1205_figureC_auc_ranking.{png,pdf}` | AUC ranking with Harvey / methodological threshold reference |

## 7. Reproduction

```bash
cd <repo_root>
python experiments/k1205/k1205.py          # regenerate JSON + CSV + integrity report
python experiments/k1205/k1205_figures.py  # regenerate all figures
```

Inputs: existing `experiments/k{1128,1131,1142,1199}/k*_results.json`. No
external data or random sampling involved; rerunning is deterministic.

## 8. References

- Lee & Mykland (2008) RFS 21(6), 2535-2563
- Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88
- Harvey, Leybourne, Newbold (1997) IJF 13(2), 281-291
- Harvey (2016) RFS 29(11), 2824-2859 (Harvey |t|>3 threshold)
- Hastie & Tibshirani (1990) Generalized Additive Models
- Ruppert, Wand, Carroll (2003) Semiparametric Regression

## 9. Scope & Limitations

- **Synthesis only, no new estimation**. All numbers verbatim from K1128/K1131/K1142/K1199 JSONs.
- Statistical power is limited across all 4 branches by 33 OOS jumps; |t|>3 Harvey threshold is informative but may be overly strict with this sample size.
- K1142 partial positive is an OOS-only claim; IS DM t=+1.45 (<2), so the effect is not consistently present across the full sample.
- K1205 explicitly refuses to reconcile the K1142 vs K1199 volnorm AUC difference — the divergence is a documented implementation choice (sigma fallback), and K1142 is the canonical number for Paper 3 vol-norm reference.
