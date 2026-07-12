# PRG (prg-periodic-garch) — Fable 深度審查 2026-07-11

- **Reviewer**: Claude Fable 5（主線程指派之深度審查 subagent）
- **審查日**: 2026-07-11 22:37（台灣時間）
- **Canonical 稿**: `paper/prg-periodic-garch/main.tex`（647 行，最後編輯 2026-07-01；main.pdf 19 pp）
- **Scope**: 全文 body 閱畢 + review_history v4–v6 / audit_2026-06-10 + K1544 兩目錄 + reproduce gate + 關鍵數字溯源 + DM/HAC 凍結 backlog 交叉比對
- **本審查未改動任何 .tex / 共享 JSON / git 狀態**

---

## 1. 執行摘要

**Verdict: 2 / 5（Major Revision，目前不可投稿）**

三句話：(1) v5 Codex REJECT 的核心識別問題（混合時點預測物件 vs 單一時點基準）在 v6 只做了措辭軟化，headline 數字結構原封未動，而 K1544 + K880 重跑的證據已足以裁定敘事必須整體重建為「雙時點 convention」框架。(2) 本審查新發現一個先前所有 round 都沒抓到的硬傷：**K880 於 2026-06-13 被重跑，canonical results JSON 的 SPY 數字已全面漂移（DM 6.00→5.06、VaR 0.93%→1.32%、MCS All→PRG-only、best model Ext→Basic），main.tex 仍引用已不存在於 repo HEAD 的舊值 — reproduce gate 現在重跑必 RED**。(3) FRL 格式硬傷：正文 ~3,839 字（硬上限 2,500）、abstract ~383 字（上限 250），照現結構投 FRL 是 desk-reject。

好消息：收斂路徑清楚且不長 — 一個六市場 Close-convention 補跑實驗 + 一次「雙時點」重寫 + K880 snapshot pin/errata，即可把論文帶到誠實且更有趣的定位。

---

## 2. 現況盤點

### 2.1 版本與 pipeline

- Canonical = `main.tex`（v6 之後累積編輯；`main_pre_v3_m2.tex` 為舊 snapshot）。Pipeline stage = revision（2026-05-21 起）。
- Review trail：v1–v4.1（04 月，曾達 ready_for_submission）→ audit_2026-06-10（13 findings：4 HIGH 已修）→ **v5_independent Codex = REJECT（3 BLOCKING + 4 MAJOR + 3 MINOR）** → v6（06-24，只做 BLOCKING #1/#3 的措辭部分 + MAJOR #4 Bonferroni 替換）。
- `README.md` / `SUBMISSION_READY.md` 均已掛 2026-06-24 status override：K1544 未收斂前禁投稿、禁 body 強化。

### 2.2 v4.1 hotfix 清單現況（逐項驗證）

| 項目 | 現況 |
|---|---|
| §4 vs §4.5 DM/QLIKE 數值不一致 | **部分修**。§4.5 表註已聲明「canonical PRG-vs-GJR 見 Table 1、本表只列 GJR-X 專屬對比」，但 SPY PRG Ext QLIKE 0.748（K880）vs 0.7559（K1260）同稱 n=1,823 的 1% 歧異仍無 footnote（audit_2026-06-10 MEDIUM #1 殘留） |
| Bollerslev1996 citation | **已修**。bibliography 存在且正確（JBES 14(2), 139–151, DOI 附） |
| Table 1 MCS 欄（PRG only vs Basic+Ext） | **已修**（main.tex:196 現為 `PRG Basic+Ext`） |
| Harvey2016 門檻 citation misuse | **已修**（MAJOR #4，92f172cf：Bonferroni α/m≈0.0025→\|z\|≈3.02 framing，主線程 06-24 verified PASS） |
| Basel 燈號 / Table 2 符號口徑 / VaR-ES 過度宣稱 / Hansen2005→2006 | **已修**（audit_2026-06-10 fix_log，主線程 06-11 逐項 grep 驗證） |

v6 拆出的未完項（仍 open）：**BLOCKING #2 full fix**（→ 已由 K1544 完成實驗但未整合）、MAJOR #6（ablation SPY-only scope）、MAJOR #7（intro L63 HAR target-mismatch 一般化殘句）、MINOR #9（機制引用）、#10（Sharpe difference test）。

### 2.3 K1544 爭點本質

`experiments/k1544_prg_fair_info_gjr/`（2026-06-24，Codex PASS_WITH_CAVEAT）把 v5 BLOCKING #2 要求的「真 current-overnight GJR-X」跑完六市場，結果**兩面刃**：

- **Fair GJR-X（daily GJR + δ·x_overnight[t]，於 day-d open 發出）在六市場 QLIKE 全勝 canonical PRG Extended**（GLD/EEM/0050/TAIFEX Harvey-significant；DM −2.5 至 −11.1）。
- **PRG open-known（r²_d0 已知 + ĥ_d1）反過來六市場全勝 fair GJR-X**（DM 2.1–10.1；GLD/EEM/0050/TAIFEX 過 3.0，QQQ 2.97、SPY 2.12 未過保守門檻但過 1.96）。

診斷（本審查裁定，詳 §5.1）：這不是矛盾，是同一病灶的兩面 — **canonical PRG 全日預測 ĥ_d0+ĥ_d1 是混合時點物件**（overnight 分量在 d−1 close 發出、intraday 分量在 d open 發出），對 close-time 基準有資訊優勢（headline DM 被灌水）、對 open-time 基準有資訊劣勢（站在 open 卻不用已實現 r²_d0 報 overnight 分量）。用它做任何單邊 DM 比較都 ill-posed。

**同向獨立證據**（K1544 之外）：
- K880v2（Close convention）：SPY DM 6.00 → −0.57。
- **K880 2026-06-13 重跑**新增 `PRG_Extended_tminus1`（嚴格 t-1 版）vs GJR：**DM t = −1.48 不顯著**。
- 三線證據一致：strict close-time 下 PRG 對 GJR 無優勢；優勢全部來自 open 時點的資訊 + bridge 結構。

### 2.4 K 編號碰撞（治理事故，需主線程處置）

`experiments/K1544/`（term-spread vol → NULL，worktree agent，06-24 03:31）與 `experiments/k1544_prg_fair_info_gjr/`（PRG 爭點實驗，Codex，06-24 06:14）**同日雙佔 K1544 編號**，違反「同一 K 編號禁止雙 agent」派工規則。knowledge/引用層面有誤指風險（本文所有 K1544 均指 `k1544_prg_fair_info_gjr`）。建議重編 term-spread 實驗為新號並全 repo grep 修引用。

**2026-07-12 resolution**：治理已完成。term-spread NULL 整體重編為 K1696（`experiments/K1696/`）；PRG fair-information 保留 K1544，本文所有 K1544 語意不變。task、knowledge 與衍生 audit 引用一併遷移，根因記入 `docs/error_log.md`。

---

## 3. 學術深度檢視

### 3.1 Contribution（相對 PRS 原論文的增量，夠投 FRL 嗎）

PRG = PRS（Lai et al. 2024, APFM）去掉 Markov-switching 的簡化 + 六市場跨資產驗證。以「模型類」貢獻投 FRL 的增量**偏薄**：session-aware GARCH 已有 Linton-Wu (2020)、Kim et al. (2023)、Opschoor-Lucas (2021)，parsimony 本身不是 letter-level novelty（v5 前 NotebookLM cross-paper meta 也標過 novelty 偏低）。

但 K1544 + K880 重跑意外給了論文一個**更強、更 FRL-shaped 的貢獻**：**forecast-timing convention 是 session-level 波動率預測評估的 first-order 問題** — 同一模型同一資料，混合時點評估給 DM +6.0，嚴格 close-time 給 −0.6～−1.5，coherent open-time 給全樣本勝但幅度重排。這是一個乾淨、可複製、對整個 overnight-information 文獻都有牙齒的 sharp point（該文獻不少論文用類似混合 convention）。誠實重寫後的論文比原版更有投稿價值，不是更弱。

### 3.2 方法論

- **QLIKE / DM / HAC**：k880（重跑版）與 k1544 的 DM 均用 Bartlett HAC、bandwidth = ⌊n^{1/3}⌋（n≈1,800 → 12 lags），屬 repo canonical bandwidth class；**PRG 支持實驗 0 站點落在 `storage/ops/dm_hac_lag_baseline.json` 凍結 backlog（133 站點皆非 PRG）**，K1655 h−1 退化類風險不適用。QLIKE 方向 actual/predicted 正確。
- **識別設計**：現行 headline（Table 1）仍是混合時點 vs close-time 基準 — v5 BLOCKING #1 的原話「這是識別問題，不是措辭問題」至今成立。v6 的 "joint advantage" 措辭承認了混合但保留數字結構，這在 referee 眼中是 hedging 不是修復。
- **PRG-vs-Separate ablation**（同 session-level 資訊集內）仍是乾淨的結構性證據，重寫後可保留為 bridge 機制的主支柱。
- **VT 經濟價值**：用混合時點 forecast 在 open 執行 — timing 敘事同樣受累；且無 Sharpe difference test / bootstrap CI（v5 MINOR #10 未修）。
- **參數表缺席**：提出新模型卻全文無任何參數估計值/SE/ρ₀ρ₁ 平穩性驗證（audit MEDIUM 未修）— referee 必問。

### 3.3 統計嚴謹度

- |t|>3.0 Bonferroni framing（~20 tests）數學正確且誠實 hedge（06-24 主線程驗證）。注意：重寫後 test family 改變，α/m 敘述需同步重算；且 open-time 新 headline 下 SPY (2.12)/QQQ (2.97) **不過論文自己的 3.0 門檻**，寫作時不可迴避（4/6 市場過、2/6 marginal 是誠實表述）。
- MCS、Kupiec/Christoffersen、FZ loss、Acerbi-Szekely 使用得當；Basel 已改 exact-binomial。

### 3.4 內部一致性 + 數字溯源（本審查抽查）

| Claim（main.tex） | 來源 JSON | 現值 | 判定 |
|---|---|---|---|
| SPY DM PRG-vs-GJR = 6.00（abstract/Table 1/Table 3） | k880 `layer5_dm_tests.GJR_vs_PRG_Extended` | **5.064** | **STALE**（6/13 重跑後漂移；舊值只存在 git history `74a01c5db^`） |
| SPY VaR 0.93% / Kupiec p=0.77（Table 4 + appendix） | k880 `layer4_var.PRG_Extended.VaR_1pct` | **1.32% / p=0.195**（24/1823） | **STALE**，且「best calibration」故事失效 |
| SPY PRG vs Sep = 6.69 | k880 | **5.69** | **STALE** |
| SPY MCS = All（Table 1） | k880 重跑 | **只剩 PRG Basic+Ext** | **STALE** |
| QQQ 4.26 / GLD 6.12 / EEM 6.63 | k881（04-17 起未動） | 4.257 / 6.1175 / 6.63 | ✅ |
| TAIFEX 5.10；GJR-HAR 0.57 | k874d | 5.0996 / 0.5669 | ✅ |
| GJR-X −0.53 / PRG-vs-GJR-X 7.72 / LR 49.37 | k1260（04-27 起未動） | −0.5309 / 7.7249 / 49.3711 | ✅ |
| VT Sharpe 1.66 / MDD −11.5% / B&H 1.01/−31.7% | k874e `layer6_economic` | 1.6622 / −0.1146 / 1.0104 / −0.3171 | ✅ |
| K1544 六市場表 | k1544 results.json | SPY 0.7581/0.7267/−4.31% 等與 README 一致 | ✅（尚未入 body，正確） |

**結論：六市場中五個市場數字健在，唯 SPY（論文的旗艦市場）整列漂移。** `reproduce_report.json`（2026-04-27）已 stale；依 04-27 版 tolerance（DM 15%），6.00 vs 5.064 = 15.6% 差 → **reproduce gate 重跑必 FAIL**。per paper-workflow 硬規則（gate 非 green 不得 review/ready/submit），這本身就是 submission blocker。漂移根因 = K880 腳本 6/13 因 Codex 24h review 補強（timing fairness/DM 實作/MCS）重跑 + yfinance 無 snapshot pin — 同時違反 paper-workflow 硬規則 1（data snapshot pinning）。該重跑被捲進不相關的 K1441 commit（`74a01c5db`「同時 stage 既有 untracked」），此後 v5/v6 兩輪 review 都沒發現。

---

## 4. 風險與致命傷

1. **［致命］識別未收斂 + 敘事殘留**：Table 1 headline、abstract 首段數字、§4.2「validates the Open convention as natural and admissible」的辯護性語氣，全部建立在混合時點物件上。K1544 已證明同在 open 時點下簡單 GJR-X 就贏 canonical PRG — headline 的 "joint advantage" 其實大半是時點差。不重建框架，任何 FRL referee 沿 v5 Codex 路徑一刀斃命。
2. **［致命］SPY 數字漂移 + reproduce gate RED**：見 §3.4。投稿版數字現在無法 replication。
3. **［致命-格式］FRL 硬上限**：正文 ~3,839 字 / 上限 2,500；abstract ~383 / 上限 250；19 pp。純格式即 desk-reject。
4. **［高］VaR「best calibration」支柱崩塌**：重跑後 SPY PRG Ext 1% VaR = 1.32%（p=0.195，仍 pass 但不再是 0.93%/0.77 的漂亮故事）；Table 4 與 appendix 全表需重生成。
5. **［中］殘留 open items**：MAJOR #6/#7 措辭、MINOR #9/#10、參數表、0.748/0.7559 footnote。
6. **［中-治理］K1544 編號碰撞**（§2.4）+ K880 重跑無 errata 記錄（README 有記但 paper 側無 errata、無 alert）。
7. **［低］K1544 點估計脆弱性**：Codex caveat — 非凸 MLE multistart，方向穩定但精確值需在 paper pipeline 內重現後才可入表。

---

## 5. 接下來的研究計畫

### 5.1 K1544 timing narrative 收斂方案（本審查裁定建議）

**裁定：放棄「單一 canonical convention + 辯護」路線，重寫為「雙時點 convention」框架，並把 timing-convention flip 本身升格為論文的 headline finding。**

兩個 coherent 的預測物件（取代現行混合物件）：

- **Close convention（嚴格 t−1 day-ahead）**：全日預測 = ĥ_d0 + ĥ_d1(ĥ_d0)，於 d−1 close 發出；與 GJR/HAR 同資訊集，比較公平。已知結果：SPY DM −0.57（K880v2）/ −1.48（K880 重跑 PRG_tminus1）→ **誠實結論：strict day-ahead 下 PRG 對 GJR 無顯著優勢**。
- **Open convention（開盤時點）**：全日預測 = r²_d0（已實現，係數 1）+ ĥ_d1；任何理性 forecaster 站在 open 都會這樣做，故這是唯一 coherent 的 at-open 全日物件。公平基準 = 同樣在 open 拿到 x_overnight[t] 的模型（K1544 fair GJR-X）。已知結果：**PRG open-known 六市場全勝 fair GJR-X**（4/6 過 3.0；SPY 2.12/QQQ 2.97 marginal）→ 結構（bridge + session 參數化）在 open-time 下有真價值。
- **PRG-vs-Separate**（session-level 同資訊集）保留為 bridge 機制 ablation，不動。

**新敘事一句話**：「session-level 波動率模型的評估對 forecast-timing convention 高度敏感：混合時點會把 DM 從 −1.5 灌到 +6.0；在兩個 coherent convention 下誠實評估，PRG 的 session bridge 於 open-time 具跨六市場的真實增量，於 strict close-time 與 GJR 無異。」這比「PRG dominates」更誠實、更新穎、也更符合 FRL 單一 sharp-point letter 體裁；對整個 overnight-information 文獻構成方法論警示（延續論文既有的 target-mismatch 主題，兩者同構：target 口徑 × 時點口徑）。

**需要的實驗證據**：
- **K-new-A（P0，compute queue）**：六市場 Close-convention 補跑 — PRG_tminus1（ĥ_ov+ĥ_in(ĥ_ov)）vs GJR/HAR，全部在 F^c_{d−1}。K1544 腳本已有六市場 infra，改造成本低。預期驗證「strict t−1 下 PRG 無優勢」是否六市場一般成立（目前只有 SPY 證據）— 若某市場（如 overnight share 高的 TAIFEX/GLD）在 close-time 下仍勝，那是額外的正面發現。
- **K-new-B（P1）**：Open-convention 補強 — (i) intraday-only target 版本（ĥ_d1 vs 含 current-ON regressor 的 benchmark intraday 方程），排除「r²_d0 加在雙邊」的機械性 QLIKE 壓縮疑慮；(ii) VT 經濟價值在 open-known convention 下重跑 + Sharpe difference bootstrap CI（一併關 MINOR #10）。
- **K880 數字治理（P0，與 K-new-A 並行）**：pin yfinance snapshot CSV（paper-workflow 硬規則 1）、以 6/13 重跑版為 canonical 重生成全部 SPY 表格、reproduce.py 改讀 snapshot + 更新 target 值、重跑 gate 至 green。

**Body 修改範圍**（K-new-A/B 落地後，主線程執行）：abstract 全重寫（≤250 字）；§2.2 forecast-timing 段改為雙 convention 定義（刪「natural and admissible」辯護段）；Table 1 重做為雙 convention 面板（或 Open 主表 + Close 對照列）；§4.2 改為 convention 對照主節；§4.5 以 K1544 fair GJR-X 取代 K1260 lagged 版（K1260 降級為 appendix）；§4.3/4.4 以重跑後數字重生成並縮編；Discussion/Conclusion 重寫定位。**估計是 major rewrite，非 patch。**

### 5.2 其他行動（優先序）

| 級別 | 行動 | 說明 |
|---|---|---|
| **P0-1** | K880 snapshot pin + SPY 數字 errata + reproduce gate 重建 | §5.1；不做則一切 review 都在漂移的地基上 |
| **P0-2** | 派 K-new-A（六市場 Close-convention） | 敘事收斂的最後一塊實驗證據 |
| **P0-3 ✅ 2026-07-12** | K1544 編號碰撞治理 | term-spread → K1696；引用修正與 dispatch 缺口 error_log 已完成 |
| **P1-1** | 雙 convention body rewrite（主線程） | 依 narrative state machine：≥3 互補實驗已備（K880v2、K880-rerun、K1544、K-new-A）→ 用戶 confirm 後進 body rewrite |
| **P1-2** | K-new-B（intraday-target robustness + VT open-known + Sharpe test） | 可與 rewrite 並行 |
| **P1-3** | FRL 減肥：正文砍到 ≤2,500 字 | VaR/ES 全表、appendix、參數表移 online appendix；主文只留 timing flip + 六市場雙 convention 主表 + ablation |
| **P2-1** | 殘留 MAJOR #6/#7、MINOR #9、0.748/0.7559 footnote | 多數會在 rewrite 中自然消滅，rewrite 後逐項 close |
| **P2-2** | 參數估計表（online appendix）+ ρ₀ρ₁ 平穩性報告 | referee 必問 |
| **P2-3** | 新一輪 v7 review cycle（latex + citation + Codex independent） | rewrite 完成後 |

### 5.3 FRL 投稿策略

- **維持 FRL 為第一目標**：重寫後的論文是典型 FRL 體裁 — 單一 sharp methodological point + 跨市場實證 + letter 篇幅。timing-flip 結果（+6.0 → −1.5）自帶記憶點。
- **格式合規 checklist**：正文 ≤2,500 字（現 3,839，須砍 ~35%）、abstract ≤250 字（現 383）、Highlights 檔、$200 fee、author = Yi-Hao Lai only、無 volpred/AI 字樣（現稿合規）、data availability Option C。
- **Desk-reject 風險評估（重寫後）**：主要殘餘風險是「PRS 簡化版」novelty 質疑 — 對策是把 timing-convention finding 放 title/abstract 首位，模型退居 vehicle；cover letter 明講對 overnight-information 文獻的一般性含意。
- **備援期刊**：若 FRL desk-reject，重寫版天然適合 IJF（forecasting methodology）或 JoF Markets 類；篇幅可展開回 full paper（參數表、六市場全表回主文）。
- **不可投稿條件（任一存在即 hold）**：reproduce gate 非 green；K-new-A 未落地；abstract/正文超字數。

---

## 6. Go / No-Go 建議

**投稿：No-Go（現狀）。** 三個獨立致命傷（識別未收斂、SPY 數字漂移 + gate RED、FRL 格式超限）任一都足以擋下。

**修訂：Go，且值得排 P0。** 理由：(1) 證據已齊 80% — K880v2/K880-rerun/K1544 三線一致，只缺六市場 Close-convention 一個實驗；(2) 重寫後的定位（timing convention as first-order）比原定位更強而非更弱；(3) 這是 M3 mission 的最大 stall（7 週），收斂路徑現已完全明確，繼續掛著的機會成本高於一次 major rewrite 的成本。

建議主線程處理順序：P0-1（數字地基）→ P0-2 派工（compute queue）→ 等 K-new-A 期間做 P0-3 + P1-3 的減肥草稿 → K-new-A 回來後依 narrative state machine 請用戶 confirm 雙 convention 重寫 → body rewrite → v7 review cycle → FRL 格式 gate。

---

*本檔所有數字均實際讀自所引檔案；「未驗證」項不存在（全部 claim 已溯源）。K880 舊值僅存於 git `74a01c5db^:experiments/k880/k880_results.json`。*
