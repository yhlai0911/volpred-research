# K1471 M=500 full results — 驗證與 adversarial review 解讀

- **日期**: 2026-06-11
- **驗證者**: 主線程派遣 verification agent + Codex CLI adversarial review（codex-cli 0.137.0, ChatGPT auth, primary path）
- **對象**: `k1471_full_results.json`（M=500, 94,500 sims, runtime 1756s）+ `k1471_full_threshold_table.md`
- **Codex verdict**: **CONDITIONAL PASS**（9 findings: 5 HIGH / 1 MED / 3 LOW；HIGH 全為解讀與呈現問題，無計算/lookahead/seed bug）
- **本文件 verdict**: 見文末「最終定調」

---

## 謎 1：RR_VT「threshold=null 但 p=0.001」的確切含義

**答案：不是口徑矛盾，是方向過濾器（by design）。**

Threshold 提取規則（`k1471_vt_crowding_redesign.py:558-563`）：

```python
degradation = post_mean < pre_mean
threshold = adoption_labels[k_obs + 1] if (significant and degradation) else None
```

RR_VT 在全部 5 cells 的 detector 輸出（full JSON 取證）：

| Cell | p | pre_break_mean | post_break_mean | degradation_direction |
|---|---|---|---|---|
| cell1 | 0.001 | 0.477 | 0.541 | **false** |
| cell2 | 0.001 | 0.469 | 0.541 | **false** |
| cell3 | 0.003 | 0.437 | 0.502 | **false** |
| cell4 | 0.001 | 0.455 | 0.514 | **false** |
| cell5 | 0.002 | 0.462 | 0.510 | **false** |

RR_VT 的 Sharpe 隨 adoption **上升**（cell1: 0.447@10% → 0.541@100%），sup-Wald 顯著拒絕平坦性，但方向是 *improvement*，所以 threshold=null、bootstrap freq 100% 落在 `no_degradation`。

**對 VT 特異性的含義：強化、不是削弱。** VT 的 turnover-matched 隨機方向對照（footprint 幾乎一樣：freq≈1.0、|Δw|≈0.004-0.008）完全沒有惡化 — VT 的衰退來自其交易的**系統性方向**（vol-feedback loop），不是來自流量本身。這是支持論文機制的最乾淨一筆證據。

**呈現缺陷（Codex HIGH #2）**：threshold table 沒輸出 `degradation_direction` / pre/post means（script line 919-934），讀者看 `null` 會誤讀為「無顯著變化」。後續任何引用必須帶方向欄位。

---

## 謎 2：VT_baseline「break at 100%」是真斷點還是 grid 端點 artifact？

**答案：detector 機制上是合法 interior split（{10..70%} vs {100%}），但解讀上「threshold=100%」部分是 grid artifact；真實圖像是單調漸進衰退、無離散 tipping point。**

cell1 VT_baseline Sharpe-vs-adoption 曲線（mean，path-bootstrap 95% CI）：

| adoption | 10% | 30% | 40% | 50% | 60% | 70% | 100% |
|---|---|---|---|---|---|---|---|
| Sharpe | 0.510 | 0.481 | 0.405 | 0.338 | 0.203 | 0.091 | **-0.271** |

相鄰 CI 多不重疊 — 衰退在 40% 就已統計上確立，**是平滑單調下降，不是 70%（或任何點）的離散斷裂**。Codex 獨立重算 cell1 各 split 的 sup-Wald：`428, 879, 1307, 1859, 2320, 5708` — 單調遞增，max 永遠在最後一個 split。原因：

1. **Sup-Wald 的 permutation null 是「flat/exchangeable」，不是「smooth monotone but no break」**（Codex HIGH #1）。p=0.001 只證明曲線非平坦，不證明存在離散 break。對單調下降曲線，prefix-vs-suffix 均值差天然在最後一個 split 最大。
2. **演算法不使用 adoption 距離**，70%→100% 是 grid 上最寬的 gap（30pp vs 10pp），中間沒有 80/90% 採樣點 — 「threshold=100%」只能讀成「**最大邊際惡化發生在 (70%, 100%] 區間**」，不能讀成「斷點在 100%」。
3. Bootstrap interval [100%, 100%] 只說明「最後一個 split 在所有 resamples 都是 argmax」— 是上述兩點的必然結果，不是斷點定位精度。

**70% 這個數字哪去了？** descriptive drop grid（非 calibration anchor）顯示 `drop>70%` 在 cell1/3/5 於 **70%** adoption 首次跨越（cell2/4 在 100%）。即原論文「70%」作為**相對衰退 70% 的 level-crossing 描述**在 3/5 cells 仍成立，但作為**結構斷點**不成立。

---

## 謎 3：RR_TF / RR_MR 的「breaks」是什麼？

**答案：兩者性質不同 — RR_TF 是真實但量級溫和的 self-impact 成本漸進累積；RR_MR 的 30% break 是 matched-control 失效 artifact，不可作為 crowding 證據。**

**RR_TF**（cell1: -0.037 → -0.086 → -0.163 → -0.178 → -0.195 → -0.192 → -0.307）：漸進下滑，總量級 ~0.27 — 「任何大型協同流量都有 self-impact 成本」的真實效應，但遠小於 VT 的 0.78 衰退。注意 RR_TF 是 match TF 的 footprint（|Δw|≈1.5、freq≈0.087），不是 VT 的對照。

**RR_MR**（cell1: -0.0075@10% → **-2.315@30%** → -0.331@40% → … → -0.743@100%）：30% 的劇烈 spike + 40% 回彈，劇烈非單調。取證鏈：

1. MR treatment 在 cell1 30% 使市場崩潰：`final_price mean ≈ 2.27e-14`、500/500 sims Sharpe 恰為 0（`pr/pv if pv>0 else 0.0` fallback，line 441）— 退化值，非真 Sharpe。cells 4/5 同樣（jq 全 population 掃描：exact-zero 只出現在 MR 30% × cells 1/4/5）。
2. MR 30% 實測 turnover `dw_mean=2.84, freq=0.974`（超過權重 cap 1.5）被直接餵給 RR_MR matching（line 830-845）。
3. RR_MR agent 經 clip 後實際 turnover 變成 `dw_mean=2.15, freq=0.625`（Codex 取證）— **已不再 matched**，control 繼承的是 collapse footprint 再被 clipping 扭曲。
4. RR_MR 的「break at 30%, p=0.001, interval [30%,30%]」完全由這個病態 cell 驅動。

MR treatment 本身在全 5 cells 都被 applicability gate（baseline < -0.5）正確擋下，**沒有任何 reported threshold 被 exact-zero 污染**；但 matched-control 輸入端沒有對應 gate（Codex HIGH #4/#5）— 迭代時需加 matched-input gate（dw_mean > cap、極端 freq、treatment price_clamp 過多 → 標記 control not applicable）。

**附帶**：TF cell2 的「threshold=30%」同樣落在病態 regime（baseline -0.444 勉強過 -0.5 floor；曲線 -0.44→-3.16→-1.69→-0.77→-2.74 劇烈非單調），不應作為 crowding 證據引用。

---

## 謎 4：smoke M=50（RR_VT p=0.13-0.39）→ full M=500（p≤0.003）是 power 還是 inconsistency？

**答案：純 power 上升，完全一致。**

- Smoke 與 full 的 RR_VT 方向相同（全 cells degradation_direction=false）、效應量相同量級（smoke pre/post: 0.489/0.580 cell1；full: 0.477/0.541）、split 位置相近。
- 效應小（+0.06~0.09），M=50 偵測不到（p=0.13-0.39），M=500 樣本×10 → sup-Wald 統計量隨 n 線性放大 → p≤0.003。
- **兩輪 threshold 都是 null**（方向過濾），結論層不變。
- 交叉驗證：大效應的 RR_TF/RR_MR 在 smoke 就已 p=0.001（位置與 full 接近）；NoiseControl 在兩輪都 p>0.4 全 null（真平坦曲線無 false positive — detector specificity 通過）；VT_baseline 兩輪 threshold 都是 100%。

---

## Adversarial review 摘要（Codex CLI primary path）

完整輸出：`/tmp/k1471_codex_review_out.txt`（session 2026-06-11；59,321 tokens）。9 findings：

| # | 嚴重度 | 要點 |
|---|---|---|
| 1 | HIGH | Permutation null 是 flatness 不是「無離散 break」— 文件/輸出口徑混淆，p=0.001 不可解讀為 tipping point 證明 |
| 2 | HIGH | Threshold table 缺 `degradation_direction` / pre/post means → 「null+0.001」誤導 |
| 3 | HIGH | threshold=100% 帶 grid artifact（演算法不用 adoption 距離；70-100 是最寬 gap）→ 只能說「最大惡化在 (70%,100%]」 |
| 4 | HIGH | RR_MR matched-control 在病態 treatment 上失效（input dw_mean 2.84 超 cap → clip 後實際 2.15/0.625 不再 matched）→ 需 matched-input gate |
| 5 | HIGH | `pv>0 else 0.0` fallback 把 collapsed-market sims 靜默轉成 Sharpe=0（MR 30% × cells 1/4/5 各 500/500）→ 應標 NaN/collapse flag；目前未污染任何 reported threshold，但污染 RR_MR matching 輸入 |
| 6 | MED | 35 個 detector runs 無 multiple-testing 修正；p=0.001 過 Bonferroni(35)，p=0.003 邊緣 |
| 7 | LOW | VT/TF/MR/NC 共用 base seed = common random numbers 設計（合法、降噪，但論文須明說） |
| 8 | LOW | 單元測試未覆蓋「平滑單調無 break 仍顯著」「顯著但 improvement」「pv==0 collapse」三個關鍵 case |
| 9 | LOW | 不顯著 cells（如 NoiseControl p=0.953）仍輸出 bootstrap interval [40%,100%] → 假定位感，不應與正式 threshold 同列 |

自查補充（與 Codex 獨立、互相印證）：
- Seed collision 全 population 掃描：跨 adoption group 無 seed 重疊（gap ≥10000 > M=500）→ 同一 detector call 內各 group 獨立，permutation 前提成立。
- Exact-zero Sharpe 全 population jq 掃描：僅 MR 30% × cells 1/4/5（各 500/500），無外溢至任何非 gated group。

---

## 最終定調

**三選一：(b) 結果支持修改版主張** — 但 headline 必須重寫，原「70% tipping point」作為結構斷點的表述需撤回。

**M=500 + Codex CONDITIONAL PASS 下可支持的主張**：

1. **VT Sharpe 隨 adoption 單調漸進惡化**（cell1: 0.510 → -0.271；五 cells 方向一致；40% 起相鄰 CI 即分離）。
2. **惡化是 VT 特異的**：turnover-matched 隨機方向對照 RR_VT 無任何惡化（方向反而改善 +0.06~0.09）→ 機制是 vol-feedback 的系統性方向，不是協同流量本身。這比原論文的 NoiseControl falsifier 強得多。
3. **無離散 70% tipping point**：sup-Wald 只拒絕 flatness；最大邊際惡化落在 (70%, 100%] 區間（grid 無 80/90% 點，無法更細定位）。
4. 原「70%」數字以 **descriptive drop>70% level-crossing** 形式在 3/5 cells 倖存（cell1/3/5 @70%；cell2/4 @100%）— 可作 robustness 描述，不可作 calibration anchor 或 break 宣稱。

**不可支持的主張**：
- 「存在 sup-Wald 證明的離散斷點」（任何位置，含 100%）。
- RR_MR / TF-cell2 的 breaks 作為 crowding 證據（matched-control 失效 / 病態 regime）。

**Detector 是否需要迭代（選項 c 的成分）**：核心計算無 bug，不需重跑 M=500；但下列修正應在引用前或下一版完成：
- (i) threshold table 加 `degradation_direction` + pre/post means 欄（修呈現，不需重算）；
- (ii) 不顯著 cells 的 bootstrap interval 不與正式 threshold 同列；
- (iii) RR matched-input gate + collapsed-sim Sharpe 改 NaN（影響 RR_MR 解讀，已在本文件以解讀層面處理）;
- (iv) 文件措辭把「breakpoint detector」改為「non-flatness test + argmax split localization」；
- (v)（可選，若論文要更精細定位）cell1 grid 補 80%/90% 點。

**對論文 vt-crowding-abm 的含義**：v5 的「70% tipping」敘事不能保留原樣；重寫方向 = 「monotone, strategy-specific erosion」+ RR_VT 對照作為機制識別主證據 + descriptive drop grid 作 70% 數字的 continuity 註腳。這比原主張更弱（無 tipping）但也更強（control 識別更乾淨、CI 更誠實）。

— 以上所有數字均直接取自 `k1471_full_results.json` / `k1471_smoke_results.json`（jq）與 Codex 獨立重算，無臆測值。
