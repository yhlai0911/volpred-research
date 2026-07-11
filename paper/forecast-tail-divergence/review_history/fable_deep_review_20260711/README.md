# Fable 深度審查 — forecast-tail-divergence（outline-only）

- **Review date**: 2026-07-11 22:39（台灣時間）
- **Reviewer**: Fable 深度審查 agent（user-assigned P0）
- **Scope**: `paper/forecast-tail-divergence/outline.md` + `experiments/{k850,k854,k1390,k1553}/` 全套 + 面向 B 相關 K + 文獻定位
- **所有引用數字皆實際讀自 results JSON / 腳本；標「未驗證」者為 reviewer 文獻知識，需 citation-verifier 確認**

---

## 1. 執行摘要

**Verdict：3 / 5 — Conditional Go（必須改寫核心命題 + 先跑一個 gating 實驗，原 outline 命題不得直接進 body）**

三句話：

1. Outline 的 headline 數字（DM t=−5.60、HAR+CF 17/450=3.78% RED、GJR+CF trinity PASS）**全部真實可驗證**，但本次審查發現一個 outline 未察覺的**內生混淆：變異數目標尺度錯配（scale mismatch）**很可能解釋掉大部分「divergence」— HAR 的 σ 來自 TAIFEX TX 期貨 5-min RV，VaR 卻打在 0050.TW ETF close-to-close 報酬上，兩者變異數尺度差 ~30%，且這個錯配在 QLIKE 端以**相反方向**懲罰 GJR。
2. 「不同 loss 給出不同模型排名」這個定性命題已被目標期刊 IJF 自己刊過兩次（González-Rivera et al. 2004；Bams et al. 2017），照原 outline 寫會被 desk reject；**能活下來的論文是「尺度 vs 尾形的分解診斷」**，不是「divergence 存在」。
3. 修正路徑明確且便宜：一個尺度再校準 gating 實驗（重用 k850/k854 pipeline）即可裁定走「完整論文」還是「方法論短文」；K1390 可折入作 dynamic-tail 章節，K1553 只該當引用不該當章節。

---

## 2. 現況盤點

### 2.1 Outline 核心 thesis

「QLIKE（分佈中心預測力）與 VaR 尾部覆蓋**正交**：QLIKE 大勝的模型可以系統性 fail 1% VaR，故單一 loss 不能為風險管理用途排名波動率模型。」證據基底 = k850（TAIFEX/0050.TW）+ k854（common-sample 修正版）。

### 2.2 數字核對（本次逐格驗證 vs results JSON）

| Outline 宣稱 | 實際檔案值 | 判定 |
|---|---|---|
| DM t = −5.60（k850） | `k850_har_rv_var_taiwan_results.json` `dm_test.HAR-RV_vs_GJR.t_stat = −5.6037`，n=481 | ✅ 正確 |
| HAR+CF 17/450 = 3.78% RED | k850/k854 皆 17/450，Kupiec p≈0，Basel red | ✅ 正確 |
| **GJR+CF 2/450 = 0.42%** | **錯格**：2/481=0.42% 是 k850（不公平樣本）；k854 公平樣本為 **3/450=0.67%**（trinity 仍 PASS green） | ⚠️ 表格格子混用兩個實驗，起草時必修 |
| GJR+Normal 1.87–2.22% | k850 9/481=1.87%、k854 10/450=2.22% | ✅（range 寫法可，但要標明兩個分母） |
| 「DM 含 HLN small-sample correction」 | k850/k854 的 `dm_test()` 實作**無 HLN 因子**；有 Bartlett HAC、bandwidth=`ceil(h^⅓·n^⅓)`（= repo canonical 規則，**不在** `storage/ops/dm_hac_lag_baseline.json` 凍結名單） | ⚠️ 敘述與實作不符（n=450 下 HLN 因子影響 <0.1%，但文字必須照實寫） |
| QLIKE 方向 | `qlike_loss_series` = `t/f − log(t/f) − 1` = canonical actual-over-predicted | ✅ 乾淨 |

另一項 outline 沒發現的**利多**：k854 已含 5% VaR 全表 — HAR+CF 46/450=10.2% FAIL、HAR+Normal 6.67% FAIL、GJR 全 variants PASS。Outline §7 想補的「5% robustness」其實已存在（10-day horizon 仍缺）。

### 2.3 K1390 證據強度 — 中上，可折入

- SPY conformal VaR，OOS n=2,864（2015–2026），高/低 VIX regime 859/2,005 日 — **樣本量遠優於 k850/k854 的 450**，且橫跨 2020/2022 壓力期。
- 發現：unconditional conformal（CU）在兩個 α 都 under-cover 且 CC FAIL；VIX_{t−1}>20 拆 bucket 的 CR 是唯一同時過 Kupiec+CC 的方法；per-regime VaR 幅度 2.45–2.77×，方向合理。
- Review 狀態：codex-rescue subagent（gpt-5.4）2-pass 後 PASS + 24h post-publish review CONDITIONAL_PASS（4 項 WARN：multiple-comparison 未校正、CR α=0.01 independence 子分量 p=0.046 邊界、單一 cutoff/threshold 無 sensitivity、verdict tolerance ad hoc）。**依 K1259 規則，進論文前需 primary-path Codex 二次驗證**。
- 對本論文的角色：完美的「尾層有自己的動態」章節 — 靜態尾部校準（固定 quantile）在 regime 切換下失效，呼應 mechanism 分解中的 shape-dynamics 通道。

### 2.4 K1553 證據強度 — 本身乾淨，但**主題貼合度弱**

- 5 ETF、4,333 rolling OOS、Codex primary-path review `PASS_WITH_LIMITATIONS`、lookahead audit 無 finding — 工程品質好。
- 但命題是「estimator coherence ≠ risk-measure coherence」（EWMA 9.59% 次可加性違反、de-risking 觸發日差 1,448 天），與本論文「forecast-loss vs tail-coverage 排名分歧」是**不同軸**。硬折成一章會把論文變成三個鬆散發現的沙拉 — IJF reviewer 最討厭的結構。
- 建議角色：practical-guidance 節的一段引用（「即使選對模型，estimator 層還有第三個獨立失效軸」），不是核心章節。

### 2.5 證據債（進 body 前必清）

1. **k850/k854 README 是空殼 stub**（status: planning、全「待補充」）且 knowledge.json 中 `verdict=null, reviewer=null` — **從未過 Codex review gate**。作為論文骨幹前必須：補 README + primary-path Codex review。
2. OOS n=450 **低於用戶 ≥500 樣本硬規則**，且 2023–2024 單一期間無空頭 — 1% 下期望違規僅 4.5 次，檢定力弱。
3. 0050.TW 單資產單市場承載 headline — 需 per `feedback_research_rigor` 跨 3 期間驗證。

---

## 3. 學術定位檢視

### 3.1 已被先行文獻佔住的部分（novelty 危險區）

- **González-Rivera, Lee & Mishra (2004), IJF 20(4), 629–645**（web 已驗證）：用 option pricing / utility / **VaR** / predictive likelihood 四種經濟 loss 評波動率模型，明示「排名依 loss 而異」。原 outline 的定性命題在目標期刊 22 年前就刊了。
- **Bams, Blanchard & Lehnert (2017), IJF 33(4), 848–863**（web 已驗證）：implied volatility 資訊含量高但其 VaR 打不贏簡單 GJR-GARCH VaR — 與 outline headline「預測較準的測度做 VaR 反而較差」同構，同一本期刊。
- Kuester, Mittnik & Paolella (2006, J. Financial Econometrics)：VaR 方法大賽馬，已建立「σ-model × tail-treatment」分解且 hybrid（GARCH-EVT/FHS）勝 — 「tail 層決定 VaR」這半句也被佔住。〔未驗證，citation-verifier 需確認卷期〕
- Elicitability 理論（Gneiting 2011; Fissler & Ziegel 2016 — 後者已在 K1553 文獻前導引用）：QLIKE elicit 變異數、pinball elicit 分位數，**不同 functional 的排名本來就不必一致** — 「正交性」在理論上是預期結果，不是發現。Reviewer 一句話就能把原 thesis 降維。

### 3.2 真正的空隙（改寫後的貢獻點）

1. **尺度 vs 尾形的可辨識分解 + violation-implied scale factor 診斷**（見 §4）：現有文獻報告「VaR fail」但不診斷 fail 的成分。「兩個 α 水準的 implied 尺度因子相等 ⇒ 尺度錯配；不等 ⇒ 尾形錯配」是一個簡單、可攜、實務可用的新診斷工具 — 這是本 corpus 能給出而文獻沒有的東西。
2. **RV-plug-in VaR 的 target-mismatch 陷阱的系統化處理**：HAR/RV 文獻（Corsi 2009 之後）大量存在「RV 預測贏 → 直接插進 VaR」的 folk practice；overnight/basis 校正（Hansen & Lunde 2005 overnight weighting〔未驗證〕；Martens 2002〔未驗證〕）與 VaR backtest 的連接很少被正面寫成方法論文。
3. **Regime-conditioned tail layer**（K1390 + K1008 arc）：conformal prediction 在金融 VaR 的 regime-conditioning 是 2024–2026 熱區，證據新。
4. 誰會引用：HAR-RV / realized-measure VaR 使用者（risk 實務）、conformal-VaR 文獻、VaR backtesting 方法論（Christoffersen/DQ/FZ 生態）。期刊層級：IJF（正好在該對話中）> Journal of Forecasting > JFEC（若計量更重）。

---

## 4. 風險與致命傷（本次審查的核心發現）

### 4.1 致命傷：headline divergence 被尺度/目標錯配混淆（confound）

k850/k854 的建構（讀自 `k850_har_rv_var_taiwan.py` L326–341, 428–438, 745–807；k854 同函式）：

- HAR 的 σ = √(TX 期貨 5-min RV 預測)（Track B 日+夜盤），VaR 目標 = **0050.TW ETF close-to-close 報酬**。TX 標的是加權指數（TAIEX），0050 是台灣 50 指數 ETF — 標的組成、期現貨 basis、時段覆蓋三層錯配。
- `cornish_fisher_quantile()` 只用 residual 的 skew/kurt 修 z_α，**不用 residual 樣本標準差 rescale** — 若 z_t = r_t/√HAR_t 的 std ≠ 1，Normal 與 CF 全額暴露在尺度偏差下；HistSim（經驗分位數）則會吸收。
- QLIKE 端是**鏡像錯配**：GJR 的 σ²（0050 報酬 fit）直接對 TX RV 評分，QLIKE 對尺度敏感 → GJR 吃系統性尺度懲罰。**同一個錯配在兩個指標以相反方向出現 — 這本身就會製造「divergence」的表象**，違反 Patton (2011) proxy-target 一致性前提。

**定量指紋**（k854 common-sample，本次以 `norm.ppf(α)/norm.ppf(actual_rate)` 計）：

| Cell | 1% implied c | 5% implied c | 解讀 |
|---|---:|---:|---|
| HAR+CF | **1.309** | **1.296** | 兩個 α 幾乎同值 ⇒ σ 系統性低估 ~30%（尺度），非尾形 |
| HAR+Normal | 1.269 | 1.096 | 混合 |
| HAR+HistSim | 1.133 | 1.045 | 經驗分位數吸收尺度後接近 1 ⇒ 佐證 |

佐證二：`avg_var_1pct`（k850）— HAR+Normal/CF 平均 1% VaR 僅 −2.09%/−2.14%，vs GJR+CF −3.83%；而 OOS 報酬 std=1.29%、kurt=7.7 之下 −2.1% 明顯過窄。佐證三：HAR+HistSim（吸收尺度）9/450=2.0% Kupiec p=0.06 邊界過，遠優於 CF 的 17/450。

**含義**：在跑過尺度再校準之前，「QLIKE 贏家 fail VaR」不能歸因於「中心與尾部正交」。誠實的論文必須把這個混淆變成論文本身（分解診斷），或被它殺掉。

### 4.2 其他風險

- **Novelty preemption**（§3.1）— 原 framing 直接撞 IJF 自家兩篇。
- **證據債**（§2.5）— 未 review 的骨幹實驗 + n=450 < 500 + 單一平靜期間。
- **敘事沙拉風險** — 把 K1553 硬折入會稀釋 spine。
- **Uniqueness claims**：起草時任何「唯一 PASS」句式須對照 current JSON（k854 中 RGL+CF 也是 3/450 trinity PASS green — GJR+CF **不是**唯一 PASS，outline 表格若寫成唯一即違反 K1416 規則）。

---

## 5. 接下來的研究計畫（Conditional Go 路徑）

### 5.0 改寫後的核心假說

> **H1（分解假說）**：plug-in 波動率預測 VaR 的失敗可分解為（a）變異數目標尺度錯配與（b）標準化殘差尾形錯設兩個可辨識通道；violation-implied scale factor 在多個 α 水準的等值性可作為通道判別診斷。
> **H2（殘餘正交假說）**：控制尺度後，point-forecast loss（QLIKE/FZ）排名與尾部覆蓋（trinity/AS-ES）排名仍存在統計上可辨識的分歧 — 若 H2 被拒絕，divergence 全為尺度 artifact（此結果照 null 誠實發表，改走短文）。
> **H3（動態尾層假說，K1390）**：尾層校準本身有 regime 動態；靜態校準即使尺度正確也會 fail conditional coverage。

### 5.1 新實驗清單（依序，E1 是 gating）

| # | 實驗 | 設計 | 裁決規則 |
|---|---|---|---|
| **E1（P0 gate）** | 尺度再校準 HAR VaR，重用 k850/k854 pipeline | 三個 variant：(a) σ×rolling std(z)（expanding、無 lookahead）；(b) Mincer-Zarnowitz 變異數映射 log r² ~ log RV_forecast；(c) overnight-inclusive 校正。重跑 1%+5% trinity + implied-c 表 | 校正後 HAR 兩 α 皆 trinity PASS ⇒ H2 危；仍 FAIL ⇒ H2 活。**任一結果都寫入論文**（分解章） |
| E2 | Matched-target 美股設計（消除 basis 混淆的乾淨版 headline） | SPY：HAR-RV（SPY 自身 RV，含 overnight 處理）vs GJR（報酬 fit），VaR 打 SPY c2c；OOS ≥2,500（2015–2026，含 2020/2022/2025 壓力）— 滿足 ≥500 + 3 期間硬規則 | 這是取代 k850 headline 的主表 |
| E3 | 2×2 因子辨識（σ-model × tail-layer），returns-fit only（無 proxy 錯配） | common sample、FZ0 joint VaR-ES loss + AS ES + trinity + implied-c；K1034/K1036（CF-Rolling 6/6 vs Normal 0/6；GJR+CF=A4f+CF）當 pilot，正式版重跑乾淨 | 「同 σ 換尾層翻 trinity、同尾層換 σ 不翻」= H2 的辨識證據 |
| E4 | 靜態 vs regime-conditioned 尾層（折入 K1390/K1008） | K1390 設計跨市場複製（SPY 已有；加 0050.TW/TX）+ cutoff/threshold sensitivity（補 K1390 的 3 項 WARN） | H3 章節 |
| E5 | 第三市場複製 | 台灣（E1 修正版）+ SPY（E2）+ 一個（N225 或 QQQ） | 廣度 gate |
| E6 | Robustness | 10-day horizon、2.5% α、subperiods、Bonferroni across cells、MCS；DM 一律 canonical `volpred.stats.model_evaluation.dm_test` | 投稿前 |

輔助資產：`experiments/research_evt_pot_gpd_garch_filter_es_e_backtesting/`（2026-07-07，FZ joint loss + e-backtest 工具鏈已建好）直接供 E3/E6 重用。

### 5.2 流程 gate（研究誠實）

1. k850/k854：補 README 三件套 + primary-path Codex review — **未過 gate 前論文不得引用**。
2. K1390：primary-path Codex 二次驗證（K1259 規則）+ 3 項 sensitivity 補跑（併入 E4）。
3. Outline 立即修正：GJR+CF 格子（2/481 或 3/450，標明分母）、刪「HLN correction」字樣或補實作、「唯一 PASS」句式對照 RGL+CF。
4. 所有新 DM 用 canonical dm_test；跨資產 pooled 檢定遵守 K1355（先按日聚合）。

### 5.3 Milestones / kill 標準 / 期刊

- **M1（~3–5 天）**：E1 完成 → **正式 Go/No-Go 決策點**。
- **M2（~2 週）**：E2+E3 完成 → 若 H2 在 ≥2/3 市場存活（QLIKE-rank vs trinity/FZ-rank 分歧 + implied-c 診斷分離兩通道）→ 進 body.md。
- **M3（~4–6 週）**：E4–E6 + 三市場表 → body.tex（主線程）→ paper-review-cycle。
- **Kill 標準**：E1 校正後 HAR 全 PASS **且** E3 因子設計中尾層交換不翻任何 trinity ⇒ 完整論文死；改寫 8–12 頁方法論短文《The violation-implied scale factor: diagnosing why good volatility forecasts make bad VaR》投 FRL / J. Forecasting（short note），k850/k854/K1390 各出一篇 feed 文章資產化。
- **期刊**：主 target IJF（González-Rivera 2004 與 Bams 2017 的直接後續對話）；備援 Journal of Forecasting、JFEC。

### 5.4 No-Go 分支的資產化（若 E1+E3 殺掉 H2）

- K1390 → 獨立短文候選（regime-conformal VaR，證據自足、樣本量夠）或併入面向 B 其他 conformal arc（K1008/K1005/K1026）。
- K1553 → 已是自足 guardrail 發現，維持 knowledge + feed 文章，不強行入論文。
- 尺度錯配發現 → `docs/error_log.md` + `research_program.md` 方法論教訓（「RV-based VaR 必先做 variance-target 對齊」），並回溯檢查 repo 內其他 RV-plug-in VaR 實驗是否同病（K824/K1043 等）。

---

## 6. Go/No-Go 建議

**Conditional Go（3/5）**：

- **不准**照原 outline 直接進 body — headline 命題被尺度混淆 + IJF 先行文獻雙重壓住。
- **准**以 §5.0 改寫命題（分解診斷 + 殘餘正交 + 動態尾層）啟動，**E1 為強制 gating 實驗**，其結果決定完整論文 vs 方法論短文兩條路 — 兩條路都有可發表產出，corpus 素材（k850/k854/k824/k799/k800/K1034/K1035/K1036/K1039/K1390/K1008/EVT-GPD）足夠支撐任一條。
- K1390 折入為 H3 章節（過 primary-path review 後）；K1553 僅作 practical-guidance 引用，不設章節。

---

### 附錄：本次驗證的檔案與定位

- `paper/forecast-tail-divergence/outline.md`（全文）
- `experiments/k850/k850_har_rv_var_taiwan_results.json`（dm_test / var_results / avg_var_1pct / conclusions）
- `experiments/k850/k850_har_rv_var_taiwan.py` L326–341（return-space residuals）、L428–438（CF quantile 無 rescale）、L533–601（QLIKE canonical / DM HAC canonical bandwidth）、L745–807（VaR 建構）、L858–883（QLIKE-DM 對 TX RV 評分）
- `experiments/k854/k854_common_sample_var_results.json`（1%+5% 全表、DM 三對、per_method_valid_counts）
- `experiments/k1390/README.md` + `REVIEW_24h_2026-06-18.md`；`experiments/k1553/README.md` + `codex_review.md`
- `storage/ops/dm_hac_lag_baseline.json`（k850/k854/k824/k799/k800/k1390/k1553 皆不在凍結名單）
- `storage/memory/knowledge.json`（jq 查詢：k850/k854 verdict=null；k1390 PASS/CONDITIONAL_PASS；k1553 entry 存在）
- `research_program.md` L54–110（面向 B）、L814–836（候選新論文方向 B 段）
- Web 驗證：[González-Rivera, Lee & Mishra (2004, IJF 20(4))](https://ideas.repec.org/a/eee/intfor/v20y2004i4p629-645.html)、[Bams, Blanchard & Lehnert (2017, IJF 33(4))](https://ideas.repec.org/a/eee/intfor/v33y2017i4p848-863.html)
