# EXECUTION — forecast-tail-divergence

> **BADGE** · verdict `3/5`（Conditional Go，命題必須改寫）· stage `draft`（outline-only）· journal `IJF（完整論文）｜FRL 短文（No-Go 分支）` · **p0 = TODO** · dod `0/7`
> 依據：`review_history/fable_deep_review_20260711/README.md`（Fable 深審 3/5 Conditional Go）· `docs/paper_portfolio_review_20260711.md` · `storage/paper_pipeline_status.json`
> 最後更新：2026-07-11（Fable deep review 完成，P0 尚未執行）

---

## 最終目標

把 forecast-tail-divergence 從「outline-only（僅 `outline.md`；核心命題未定；骨幹實驗 k850/k854 從未過 review gate）」狀態，經一個**強制 gating 實驗（E1 尺度再校準）**裁決後，推進到可投稿狀態 —— E1 若證明「殘餘正交」存活即走**完整論文投 International Journal of Forecasting（IJF）**；若 E1 證明 divergence 全為尺度 artifact，即誠實改寫**方法論短文投 FRL / Journal of Forecasting**。兩條路都有可發表產出。

**核心貢獻（必須改寫，不得沿用原 outline 命題）**：原 outline 的定性命題「QLIKE（中心預測力）與 VaR 尾部覆蓋正交」**不能當貢獻** —— 它（a）已被目標期刊 IJF 自家兩篇（González-Rivera, Lee & Mishra 2004；Bams, Blanchard & Lehnert 2017）刊過、（b）在 elicitability 理論下本來就是預期結果（不同 functional 排名不必一致）、（c）恐為 k850 尺度混淆製造的 artifact。**能活下來的貢獻 = 尺度 vs 尾形的可辨識分解 + violation-implied scale factor 診斷**：plug-in 波動率預測 VaR 的失敗可分解為（a）變異數目標尺度錯配與（b）標準化殘差尾形錯設兩個可辨識通道；violation-implied scale factor 在多個 α 水準的等值性可作通道判別診斷 —— 這是 corpus 能給出而文獻沒有的東西。

**期刊順序（老闆授權自主，memory `feedback_paper_autonomy_optimize_acceptance`）**：
1. **IJF（primary，完整論文分支）** — 貢獻形態是 forecast-evaluation 型（分解診斷 + trinity/FZ scorecard），是 González-Rivera (2004) 與 Bams (2017) 的直接後續對話；replication package 符合 IJF replication 友善傳統。
2. **FRL / Journal of Forecasting（No-Go 分支的方法論短文）** —《The violation-implied scale factor: diagnosing why good volatility forecasts make bad VaR》，8–12 頁。
3. **JFEC（若計量更重的備援）**。

> **關鍵裁定（寫進本檔以免再被誤導）**：`outline.md` 的 headline 數字**全部真實可驗證**（DM t=−5.60、HAR+CF 17/450=3.78% RED、GJR+CF trinity PASS），但本次深審發現 outline 未察覺的**內生混淆：變異數目標尺度錯配（scale mismatch）**很可能解釋掉大部分「divergence」。**正確動作 = 先跑 E1（尺度再校準）gating 實驗**，其結果裁決完整論文 vs 短文 —— 在 E1 跑完之前，「QLIKE 贏家 fail VaR」**不得**歸因於「中心與尾部正交」。原 outline 命題**禁止直接進 body**。

---

## 當前狀態

**Verdict 3 / 5（現狀 NO-GO for body；E1 gating 完成後才能定完整論文 vs 短文兩條路，任一都有產出）。**

- **數字層健全** ✅：outline headline 逐格驗證吻合 —— `k850_har_rv_var_taiwan_results.json` `dm_test.HAR-RV_vs_GJR.t_stat = −5.6037`（n=481）、HAR+CF 17/450=3.78% Kupiec p≈0 Basel red、QLIKE 方向為 canonical actual-over-predicted（`t/f − log(t/f) − 1`），皆乾淨。
- **致命傷：headline divergence 被尺度/目標錯配混淆** ❌：HAR 的 σ = √(TAIFEX TX 期貨 5-min RV 預測)（標的為加權指數 TAIEX），VaR 目標卻是 **0050.TW ETF close-to-close 報酬**（台灣 50 指數）—— 標的組成、期現貨 basis、時段覆蓋三層錯配。`cornish_fisher_quantile()` 只修 z_α 的 skew/kurt，**不用 residual std rescale**；QLIKE 端是**鏡像錯配**（GJR 的 σ² 對 TX RV 評分）→ 同一錯配在兩指標以相反方向出現，本身就會製造「divergence」表象，違反 Patton (2011) proxy-target 一致性。定量指紋：k854 common-sample 的 implied scale c，HAR+CF 在 1%/5% 兩個 α 幾乎同值（**1.309 / 1.296**）⇒ σ 系統性低估 ~30%（尺度而非尾形）；HAR+HistSim（吸收尺度）降到 1.133 / 1.045 佐證。
- **Novelty preemption**（novelty 危險區）：原 framing 直接撞 IJF 自家 González-Rivera (2004, IJF 20(4):629–645) 與 Bams (2017, IJF 33(4):848–863)；Kuester-Mittnik-Paolella (2006, JFEC〔卷期待 citation-verifier〕) 佔住「tail 層決定 VaR」半句；elicitability 理論（Gneiting 2011；Fissler & Ziegel 2016）使「正交性」在理論上是預期結果。
- **證據債**（進 body 前必清）：（1）k850/k854 的 `README.md` 是 **planning stub**（全「待補充」）且 `knowledge.json` 中 `verdict=null, reviewer=null` —— **從未過 Codex review gate**；（2）OOS n=450 **低於 ≥500 樣本硬規則**，且 2023–2024 單一期間**無空頭**（1% 下期望違規僅 4.5 次，檢定力弱）；（3）0050.TW 單資產單市場承載 headline，違反 `feedback_research_rigor` 跨 3 期間要求。
- **E1 gating 尚未執行** → 現狀論文命題無法成立；E1（P0-1）結果是完整論文 vs 短文的**唯一 make-or-break 決策點**。

---

## 完成定義（DoD）— 全部未達成

- [ ] **P0-1** 落地：E1 尺度再校準 gating 實驗完成（三 variant + implied-c 表 + 1%/5% trinity），**Go/No-Go 裁決（完整論文 vs FRL 短文）已定**且結果誠實寫入論文
- [ ] **P0-2** 落地：k850/k854 證據債清償 —— 補 `README.md` 三件套 + primary-path Codex review PASS（`knowledge.json` 由 verdict=null 轉正）；未過 gate 前論文不得引用
- [ ] **P0-3** 落地：outline 三處誠實錯誤修正（GJR+CF 格子標明分母、刪/補「HLN correction」字樣、「唯一 PASS」句式對照 current k854 JSON）
- [ ] **P1** 落地：E2 matched-target 美股 headline + E3 2×2 因子辨識完成，**H2（殘餘正交）在 ≥2/3 市場存活**（QLIKE-rank vs trinity/FZ-rank 分歧 + implied-c 分離兩通道），或如實改走短文
- [ ] **P2** 落地：E4–E6（regime 尾層 + 第三市場 + robustness）完成，K1390 過 primary-path Codex 二次驗證後折入 H3；`body.tex` 由主線程寫成 → `paper-review-cycle` 收斂（latex-academic-reviewer + citation-verifier **0 MAJOR**）
- [ ] paper 資料夾 self-contained（`data_sources.md` / `reproduce.py` exit 0 且 match_rate ≥ 95% green / `experiments.md`）；每個支撐實驗三件套齊全 + 固定 seed
- [ ] IJF `journal-review` compliance gate 通過（author = Yi-Hao Lai only；無 volpred / AI / LLM 字樣）+ `paper-update` 同步線上驗證

---

## P0 — gating + 證據債（E1 未跑完前不進 body；全部 ⬜ TODO）

### ⬜ P0-1 — E1 尺度再校準 gating 實驗（make-or-break；新 K，一個 compute job）

**這是全篇的決策點**：在跑過尺度再校準前，「QLIKE 贏家 fail VaR」不能歸因於「中心與尾部正交」。重用 k850/k854 pipeline，跑三個 variant，重算 1%+5% trinity + implied-c 表。

- ⬜ **variant (a)** σ × rolling std(z)（expanding、無 lookahead，z_t = r_t/√HAR_t）
- ⬜ **variant (b)** Mincer-Zarnowitz 變異數映射（log r² ~ log RV_forecast）
- ⬜ **variant (c)** overnight-inclusive 校正（對齊 0050 c2c 報酬的隔夜段）
- ⬜ 三 variant 各重跑 **1% + 5% VaR trinity**（Kupiec + Christoffersen CC + DQ）+ **implied scale factor 表**（`norm.ppf(α)/norm.ppf(actual_rate)`）

**裁決規則（寫死，避免事後移動球門）**：
- 校正後 HAR **兩個 α 皆 trinity PASS** ⇒ H2（殘餘正交）危 —— divergence 大部分是尺度 artifact，**改走 FRL 方法論短文**（K1390/k850/k854 各資產化為 feed 文章）。
- 校正後 HAR **仍 FAIL** ⇒ H2 活 —— 進**完整論文**（IJF），尺度混淆分解成論文本身的一章。
- **任一結果都寫入論文**（分解診斷章）；null 結果照 `研究誠實 §6` 如實發表。

**驗證 gate**：實驗三件套（`experiments/<id>/{README.md, <id>.py, <id>_results.json}`）+ 固定 seed + Codex primary-path review PASS；結論寫入 `knowledge.json`。
（對應 next_tasks：`fable0711_ftd_e1_scale_gating`，P1 pending，experiment lane）

### ⬜ P0-2 — k850/k854 證據債清償（骨幹實驗過 review gate；修流程不修資料）

k850/k854 是 headline 骨幹，但 README 為 planning stub、`knowledge.json` verdict=null/reviewer=null —— **未過 gate 前論文不得引用**。

- ⬜ 補 k850 / k854 的 `README.md` 三件套（動機 / 差異化 / 相關 K / 防錯規則 / 成功標準）
- ⬜ primary-path Codex review（CONDITIONAL_PASS 以上才寫 `knowledge.json`）；補齊 provenance + reviewer 欄位（`_append_to_index` gate 要求）
- ⬜ 記錄 DM 的 HAC bandwidth 現為 canonical `ceil(h^⅓·n^⅓)`（**不在** `storage/ops/dm_hac_lag_baseline.json` 凍結名單），新增任何 DM 一律走 `volpred.stats.model_evaluation.dm_test`

**驗證 gate**：`knowledge.json` 兩筆 verdict 由 null 轉正 + reviewer 欄非空；CI `scripts/validate_knowledge_provenance.py` 綠。

### ⬜ P0-3 — outline 立即修正（純手稿 metadata，估 <0.5 天）

- ⬜ **GJR+CF 格子標明分母**：`2/481=0.42%` 是 k850（**不公平樣本**）；k854 公平樣本是 **`3/450=0.67%`**（trinity 仍 PASS green）—— 起草時勿寫成「2/450」（同表混用兩個實驗）
- ⬜ **刪「DM 含 HLN small-sample correction」字樣或補實作**：k850/k854 的 `dm_test()` 實作**無 HLN 因子**（有 Bartlett HAC canonical bandwidth）；敘述與實作不符，照實寫
- ⬜ **「唯一 PASS」句式對照 current k854 JSON**：RGL+CF 也 3/450 trinity PASS green → GJR+CF **不是**唯一 PASS；任何 uniqueness framing 改寫成 strongest / most visible（K1416 教訓）

**驗證 gate**：`outline.md` 三處修正 + `grep` 全篇無殘留「2/450」「HLN correction」「唯一 PASS / only ... PASS」誤述。

---

## P1 — 完整論文核心證據（E1 = Go 後啟動；全部 ⬜ TODO）

- ⬜ **E2 — Matched-target 美股設計（消除 basis 混淆的乾淨 headline）**：SPY —— HAR-RV（SPY 自身 RV，含 overnight 處理）vs GJR（報酬 fit），VaR 打 SPY c2c；OOS ≥2,500（2015–2026，含 2020/2022/2025 壓力）→ 同時滿足 ≥500 樣本 + 跨 3 期間硬規則。**取代 k850 headline 的主表**。
- ⬜ **E3 — 2×2 因子辨識（σ-model × tail-layer），returns-fit only（無 proxy 錯配）**：common sample、FZ0 joint VaR-ES loss + AS ES + trinity + implied-c；K1034/K1036（CF-Rolling 6/6 vs Normal 0/6）當 pilot，正式版重跑乾淨。「同 σ 換尾層翻 trinity、同尾層換 σ 不翻」= H2 的辨識證據。
- ⬜ **裁決點 M2**：H2 在 ≥2/3 市場存活（point-forecast loss 排名 vs 尾部覆蓋排名分歧 + implied-c 診斷分離兩通道）→ 進 `body.md`；否則改走短文分支。
- ⬜ 輔助資產直接重用：`experiments/research_evt_pot_gpd_garch_filter_es_e_backtesting/`（FZ joint loss + e-backtest 工具鏈已建好）供 E3 loss 計算。
- ⬜ 跨資產 pooled 檢定遵守 K1355（先按日期聚合 cross-asset loss differential，再對日期序列做 HAC/DM；stacked asset-day 只放 diagnostic）。

---

## P2 — 廣度 + 寫作（M2 通過後；全部 ⬜ TODO）

- ⬜ **E4 — 靜態 vs regime-conditioned 尾層（H3 章節，折入 K1390 / K1008）**：K1390（SPY conformal VaR，OOS n=2,864、high/low VIX 859/2,005 日；CR 是唯一同時過 Kupiec+CC 的方法，per-regime 幅度 2.45–2.77×）跨市場複製（加 0050.TW/TX）+ 補 K1390 的 3 項 WARN（multiple-comparison 校正、CR α=0.01 independence 邊界、cutoff/threshold sensitivity）。**K1390 進論文前必過 primary-path Codex 二次驗證（K1259 規則）** —— 目前僅 codex-rescue subagent PASS + 24h CONDITIONAL_PASS。
- ⬜ **E5 — 第三市場複製**：台灣（E1 修正版）+ SPY（E2）+ 一個（N225 或 QQQ）—— 廣度 gate。
- ⬜ **E6 — Robustness**：10-day horizon、2.5% α、subperiods、Bonferroni across cells、MCS；DM 一律 canonical `volpred.stats.model_evaluation.dm_test`。
- ⬜ **body.tex 由主線程寫成**（不丟 background agent 改 .tex，paper-workflow 硬規則）→ `paper-review-cycle`（latex-academic-reviewer + citation-verifier）收斂 → `journal-review` compliance gate → `paper-update` 同步。
- ⬜ paper 資料夾補齊 self-contained（`data_sources.md` / `scripts/README.md` / `reproduce.py` green / `experiments.md` K 索引）。
- ⬜ **No-Go 分支資產化**（若 E1+E3 殺掉 H2）：K1390 → 獨立短文候選（regime-conformal VaR，樣本量夠）；尺度錯配發現 → `docs/error_log.md` + `research_program.md` 方法論教訓（「RV-based VaR 必先做 variance-target 對齊」），回溯檢查 repo 其他 RV-plug-in VaR 實驗（K824/K1043 等）是否同病。

---

## 禁止事項（本篇特有）

- ⛔ **別把原 outline 命題（「QLIKE 與 VaR 尾部正交」）直接進 body** —— 被 IJF 自家兩篇（González-Rivera 2004、Bams 2017）preempt + elicitability 理論下是預期結果 + 恐為 k850 尺度混淆 artifact；命題**必須改寫**成尺度 vs 尾形分解診斷。
- ⛔ **別把 k850 的尺度混淆當真效應** —— HAR σ 來自 TAIFEX TX 期貨 5-min RV（TAIEX 標的），VaR 卻打 0050.TW ETF c2c 報酬（三層錯配），QLIKE 端鏡像懲罰 GJR；**E1 跑完前不得歸因「中心與尾部正交」**，違反 Patton (2011) proxy-target 一致性。
- ⛔ **GJR+CF「2/450」是錯格** —— 2/481=0.42% 是 k850（**不公平樣本**），k854 公平樣本是 **3/450=0.67%**（trinity 仍 PASS green）；起草必標明分母，不可寫「2/450」。
- ⛔ **禁「唯一 PASS」句式** —— k854 中 RGL+CF 也 3/450 trinity PASS green，GJR+CF **非唯一** PASS；任何 uniqueness framing 必回 current k854 JSON 重驗（K1416 教訓）。
- ⛔ **別宣稱 DM 含 HLN small-sample correction** —— k850/k854 的 `dm_test()` 實作**無 HLN 因子**（有 Bartlett HAC canonical bandwidth）；敘述與實作不符，照實寫。
- ⛔ **別把 K1553 硬折成章節** —— 它是「estimator coherence ≠ risk-measure coherence」（EWMA 9.59% 次可加性違反），與本篇「forecast-loss vs tail-coverage 分歧」是**不同軸**；硬折會把論文變沙拉，只作 practical-guidance 一段引用。
- ⛔ **不整檔讀** `feed.json` / `knowledge.json`（用 grep / jq / 單檔）；**修流程不修資料**（k994 類 sign 錯要修產生邏輯，不 sed / Edit JSON 欄位）。

---

## 進度日誌

```
2026-07-11 | Fable deep review | 深審完成（命題改寫 conditional GO），待執行 P0 | f913ed68c
```

---

## 接續提示詞

讀 `paper/forecast-tail-divergence/EXECUTION.md` 後，從 **P0-1** 開始：跑 **E1 尺度再校準 gating 實驗**（next_tasks `fable0711_ftd_e1_scale_gating`，experiment lane）—— 重用 k850/k854 pipeline，跑三個 variant（(a) σ×rolling std(z) expanding 無 lookahead；(b) Mincer-Zarnowitz 變異數映射 log r²~log RV_forecast；(c) overnight-inclusive 校正），重算 1%+5% VaR trinity + implied scale factor 表。**這是全篇的 make-or-break 決策點**：校正後 HAR 兩個 α 皆 trinity PASS ⇒ divergence 是尺度 artifact → 改走 FRL 方法論短文；仍 FAIL ⇒ 殘餘正交存活 → 進完整論文投 IJF ——**任一結果都誠實寫入論文**（分解診斷章），null 也發表。E1 跑完前**不得**把「QLIKE 贏家 fail VaR」歸因於「中心與尾部正交」（原 outline 命題已被 IJF 兩篇 preempt + 恐為 k850 混淆 artifact，禁止直接進 body）。E1 是 compute job（新 K，實驗三件套 + 固定 seed + Codex primary-path review PASS 才寫 knowledge.json）；可與 P0-2（k850/k854 補 README + 過 review gate）、P0-3（outline 三處誠實修正）平行。P1（E2 matched-target 美股 headline + E3 2×2 因子辨識）僅在 E1=Go 後啟動；body.tex 一律主線程寫（paper-workflow 硬規則）。每項改動的來源數字先讀 results JSON 驗證再寫，不臆造。
