# EXECUTION — eav-universal-magnitude

> **BADGE**: `verdict=2/5` · `stage=revision`（2026-06-11 進入）· `blocker=finishing` · `journal=IRFA（pivot 後主推）／JIFMIM 備選` · `p0=TODO` · `reproduce=partial`（20 cells green，§6.6 全數字未覆蓋）
>
> 本檔是 **eav-universal-magnitude 的執行追蹤器**，由 2026-07-11 Fable 深審裁決落地為可執行清單。權威證據來源：`review_history/fable_deep_review_20260711/README.md`（深審全文）、`docs/paper_portfolio_review_20260711.md`（portfolio 裁決）、`storage/paper_pipeline_status.json`（pipeline 狀態）。P0 尚未執行 → 所有 P0 項與 DoD 皆 ⬜。

---

## 1. 最終目標（主軸 pivot）

**論文主軸從「magnitude ordering（US>JP>TW）」改為「sign universality」。**

深審核心裁定：**sign universality 站得住、magnitude ordering 站不住**。三市場 pooled θ̂_EAV>0、cluster-bootstrap |t|∈{4.50, 5.24, 11.99}、placebo 各 0/60（within-stock date permutation，保留公告次數，設計 credible），且兩個 basin 的 θ 都是正的——**sign 結論對 K1470 的 two-basin 病態免疫**，是論文最堅固的護城河。13-market panel 把「不是 US 特例」的外部效度做起來了。

反過來 magnitude ordering 被論文自己的資料反轉：pooled-joint canonical θ_rel（去尺度後，`k1216c_results.json` 已直讀吻合）為 **JP 1.668 > US 0.415 > TW 0.314**，直接翻掉 US>JP>TW 的 headline。ordering 不是 normalization-invariant、也不是 basin-invariant，撐不起標題級 claim（違反 K1416 uniqueness/ordering 重驗規則）。

**新論文命題（重寫後應成立的一句話）**：企業盈餘公告在三個制度差異極大的市場中，對公告日 realized variance 有**普世正向、統計極強**的增量效應（sign universality），並由更高檢定力的 172-stock panel 揭示 within-market analyst attention 為主要驅動因子；跨市場的 magnitude ordering 因對 normalization / identification 敏感，降級為 exploratory observation，不作對外 claim。

**pivot 的策略價值**：sign 對 basin 免疫 → 深審列為 FATAL 的 **F1（ordering 非 normalization-invariant）與 F3（Table 1 basin / CI 排除全域最適）不再是投稿阻擋項**（它們只傷 magnitude）。深審原 P0-1 normalization refit、P0-2 basin-aware 重推論因此從「必做重活」降為**選配 robustness / 方法論 spin-off**（見 §4、§7）。這是選 pivot 而非硬救 magnitude 的核心理由。

---

## 2. 核心裁定（三句話）

1. **sign universality 站得住**（θ_EAV>0 三市場、placebo 0/60、13-market panel）——保留、任何改寫不得犧牲。
2. **magnitude ordering 站不住**——被自家 θ_rel 欄反轉（JP>US>TW），normalization-dependent，headline 撤除。
3. **兩個仍需修的實質破口**：abstract 自相矛盾（market-level constant vs within-market analyst attention）；§6.3–6.5 的 OOS DM 檢定零 HAC（違反 2026-07-11 生效的 repo DM-HAC 硬規則，且落在稽核器盲區）。

底層現象 real、provenance 紀律好、誠實文化到位（continuous-spec 撤回、asymmetric artifact 揭露）——**繼續投入 = GO；現狀投稿 = NO-GO**。

---

## 3. P0 執行清單（不做完不得進下一輪 review）

> 全部 ⬜ TODO（P0 尚未執行）。`main_thread` = 論文 .tex 寫作／方法論決策留主線程（paper-workflow rule）；`agent/experiment` = 可派 compute。

- ⬜ **P0-1｜magnitude ordering 降級 → sign universality 主軸重寫**（`paper_body` / main_thread）
  - 撤除 US>JP>TW 作為 headline / contribution；改寫 **abstract / §1 intro / §6.2 institutional 敘事 / conclusion**，主軸換成 sign universality（θ_EAV>0 三市場、cluster-bootstrap |t|、placebo 0/60、13-market 外部效度）。
  - §6.2 原本對著 raw-scale ordering 講的 institutional 故事（analyst coverage / earnings-call culture 解釋 magnitude 差異）必須拆掉或改寫為 driver 分析（不綁 ordering）。
  - magnitude 保留為 exploratory：明寫「θ_rel 在三套 normalization 下兩存一反轉，ordering 對尺度敏感，不作對外 claim」。
  - 一併移除 Table 1 footnote（`body.tex:646–658`「NOT yet re-estimated…open verification item」）與 abstract（`abstract:85–91` 引 K1470「ordering preserved」）的**直接互相矛盾**。

- ⬜ **P0-2｜abstract 自我矛盾修復（F2）**（`paper_body` / main_thread）
  - `body.tex:74`（+ `:195`、`:733`、`:778`）主張「no firm-attribute predictor → **market-level constant**」與 `body.tex:130`、`:233`（+ `:1077`、`:1326`）主張 driver (i)=**within-market analyst attention**（panel-OLS market FE，Harvey |t|=3.79，k1172 已驗）——兩句話不能同時成立。
  - 誠實和解點：TW null chain（K1109 sector ANOVA、K1113 六 covariate = mktcap/beta/earnings freq/volume/vol/momentum）**從未測過 analyst coverage**，且 N=31 檢定力遠低於 172-stock panel。改寫為「六個 pre-registered covariates 內無 predictor；更高檢定力的 172-stock panel 找到 analyst attention」。
  - 連帶**撤回或大幅降級 market-level constant 措辭**（它原是跨市場比較「不被 sample composition confound」的邏輯支柱，pivot 後不再需要撐 magnitude）。

- ⬜ **P0-3｜OOS DM 零 HAC 重算（F4 / K1655 class）**（`experiment` K-new + `paper_body`）
  - `experiments/k1149/k1149.py:750`（`dm_hln`）與 `experiments/k1148_d2/k1148_d2.py:570`（`dm_hln_stat`）皆 `var_d = np.var(d, ddof=1)/T`——**對 loss differential 完全沒做 HAC**。依 `.claude/rules/experiments.md`：`lag = max(h-1, ceil(h^{1/3}·n^{1/3}))`，h=1 絕不等於可以不做 HAC（K621：漏 HAC 是**雙向**誤設，負自協方差下修正後 |t| 反而變大——先讀 loss differential acf 再判方向，不可預設「顯著的還是顯著」）。
  - 改用 canonical `volpred.stats.model_evaluation.dm_test`（bandwidth `ceil(n^{1/3})`）重跑；並依 K1355 做 **date-aggregated panel DM 當 primary**（現狀 per-stock DM + stock bootstrap 聚合，同日跨股共同 shock 未處理）。
  - 受影響對外數字須更新：§6.5 binary DM t=−5.58 / continuous −5.25（k1148_d2）；§6.4 TW OOS DM −2.48 / US −3.31（k1149）；k1148_d1 TW binary OOS p=0.076（marginal，雙向翻盤風險）。
  - **流程面**：k1148/k1149 不在 `storage/ops/dm_hac_lag_baseline.json` 凍結清單（稽核器只掃 `range(1,h)` pattern，「完全無 HAC 迴圈」的實作漏網）——回報 enforcement owner 補盲區。此工作已立單 `fable0711_dm_hac_auditor_blindspot`（next_tasks），本篇 P0-3 與之對接。
  - 註：portfolio 矩陣把此項標 P1；本檔升為 P0，因它是 DM 推論層的研究誠實違規（K1655 class），且 team-lead 明確與 pivot 並列為本篇兩件核心事。

---

## 4. P1 / P2 後續（submission 前；可與 P0 並行）

**P1（submission 前必須，文字／工程層）**
- ⬜ reproduce gate 擴充到 §6.6 全部 cells（k1163/k1165/k1166/k1168/k1171/k1172/k1207/k1213/k1216*/k1173/k1470）+ 4 處 `% source: k1222b_revision_guide.md`（`body.tex:887–888, 1028, 1087, 1166`）改綁 JSON → gate green。
- ⬜ 市場數口徑統一（9/10/12/13、N=172/182 混亂）+ **panel provenance table**（K1172=12mkt/172、K1207=12mkt/182、K1216c=13mkt Spearman、K1470=3mkt，各列 N/期間/estimator label）。
- ⬜ 填 summary stats 表（現全 `---`）+ 寫 Appendix A（P0 的 analytic gradient / multistart 材料充當內容）；在此之前把引用它的 footnote（`body.tex:379–380`）改 forward-looking——**現狀引用不存在的 Appendix A**。
- ⬜ Citation 三件：`patell_wolfson1979` → JAE 1(2)（現 bib 誤為 JFE 7(2)）；+`harvey1997`（HLN, IJF 13(2) 281–291）；+`bollerslev1986`；全 bib 補 DOI。
- ⬜ 修 K1149 LRT p=0.010 vs Wald t=−0.39 矛盾句（`body.tex:808–811`）——改寫為 likelihood-surface 病態訊號、TW interaction 降 inconclusive（與 DM/basin 敘事自然銜接）。
- ⬜ ρ=+0.379（p=0.20, N=13）從 "structural driver (c)" **降為 suggestive/directional**（它從未顯著；canonical +0.441 p=0.152 亦不顯著）。
- ⬜ F=689.5（9 df, 12 clusters）補 wild cluster bootstrap 或誠實 caveat（cluster-robust joint Wald 在 G=12/q=9 自由度近耗盡，F 會爆大）；placebo z=70.7σ 降級為附註（只報 0/60 + 分佈圖）。
- ⬜ 刪內部工作語言（"FINAL"、"Paper 2 commits…"）+ "§5.5.4" 懸空引用（`body.tex:1083`）+ draft 標記；**貢獻收斂到 2–3 個**（sign universality + panel mechanism 為主；magnitude/multistart/ownership ladder 降級或移出）。

**P2（submission 打磨）**
- ⬜ CJK/fontspec preamble 移除（pdflatex 相容）+ overfull hbox；B=150 bootstrap → B≥999。
- ⬜（選配）normalization refit / basin-aware 重推論——pivot 後非阻擋項，可作 robustness 附錄或獨立方法論短文（Economics Letters / FRL methods note）。
- ⬜ CA/HK/KR multistart 補齊（消 pre-registration disclosure 懸念）；COVID structural break。

---

## 5. Definition of Done（進下一輪 review 的驗收條件）

> 全部 ⬜（P0 未執行）。

- ⬜ magnitude ordering 已從 headline / contribution 撤除，主軸為 sign universality，abstract / §1 / §6.2 / conclusion **口徑一致**。
- ⬜ abstract 自我矛盾已解（market-level constant vs within-market analyst attention），heterogeneity 敘事內部一致。
- ⬜ k1148_d2 / k1148_d1 / k1149 OOS DM 已用 canonical HAC + date-aggregated panel DM 重跑，§6.3–6.5 數字更新，loss-differential acf 已報。
- ⬜ 稽核盲區已回報 `audit_dm_hac_lag.py` enforcement owner（對接 `fable0711_dm_hac_auditor_blindspot`）。
- ⬜ reproduce gate 覆蓋 §6.6 全 cells + `reproduce_report.json` green（match_rate ≥95%, alert_level=green）。
- ⬜ placeholder 清零（summary stats 表填值、Appendix A 寫實或引用改 forward-looking）。
- ⬜ citation 三件補齊 + DOI；市場數 / N 口徑統一 + panel provenance table。
- ⬜ 內部工作語言 / 懸空引用清除；貢獻收斂 2–3 個。
- ⬜ `uv run volpred ops paper-update --paper-id eav-universal-magnitude` 同步平台；README status 更新。

---

## 6. 禁止事項（本篇特有）

- **不得再宣稱 magnitude ordering（US>JP>TW）** 為 headline / contribution——被自家 pooled-joint canonical θ_rel（JP 1.668 > US 0.415 > TW 0.314）反轉；只可作 exploratory 且明寫對 normalization 敏感。
- **不得留 abstract 自相矛盾**——「market-level constant」與「within-market analyst attention driver」不能同段並存（P0-2 必修）。
- **不得對外報無 HAC 的 DM 數字**——§6.3–6.5 的 dm_hln 在修好前不得標 final；且要記得它在稽核器盲區（`range(1,h)` pattern 掃不到零 HAC 迴圈）。
- **不得沿用舊 README / motivation / 文章的 uniqueness / ordering framing**（K1416 規則：ordering claim 必須對 current result table 重驗）。
- **不得引用不存在的 Appendix A**（`body.tex:379–380` footnote 現把 placeholder 當「analytic-gradient verification」引用）。
- **不得在 reproduce gate 只蓋 §6.6 的 1/3 數字時標 ready / submit**（paper-workflow reproduce-gate 先決條件）。
- **不得把 ρ=0.379（p=0.20）當 structural driver 賣**——它是 null result。
- **論文 .tex 不丟 background agent 改寫**（paper-workflow rule：寫作 / 方法論決策留主線程）。

---

## 7. 期刊路徑

pipeline `journal_target=decide`；深審給兩條分支，本篇 pivot 已選定「sign universality」分支：

- **【已選】pivot 成 sign universality + within-market mechanism + normalization/identification 方法論教訓** → **IRFA 主推**（國際市場橫斷面 + 方法論混合體質合）、**JIFMIM 備選**。這是更誠實也更耐審的論文。
- 【已放棄】若硬救 ordering（需 normalization refit + basin-aware 重推論成功且 ordering 在 canonical 尺度存活）→ JEF 主推、IRFA 備選。pivot 後此分支降為選配 spin-off。
- **JBF / JoE 暫不建議**：JoE 會對 identification/normalization 窮追猛打（F3 根因是其主場），JBF 對貢獻大雜燴不友善。
- FRL 是快出口但會浪費 13-market panel 的厚度，不建議當主目標。

---

## 8. 關鍵檔案定位

| 項目 | 路徑 / 定位 |
|---|---|
| 論文主稿 | `paper/eav-universal-magnitude/body.tex`（2026-07-01 build，30 頁） |
| 深審全文（權威證據） | `paper/eav-universal-magnitude/review_history/fable_deep_review_20260711/README.md` |
| Portfolio 裁決 | `docs/paper_portfolio_review_20260711.md`（eav 列：L24 / L56 / L73） |
| Pipeline 狀態 | `storage/paper_pipeline_status.json`（stage=revision, blocker=finishing） |
| θ_rel 反轉證據 | `experiments/k1216c/k1216c_results.json`（canonical_theta_rel: JP 1.6675 / US 0.4148 / TW 0.3140） |
| DM 零 HAC 站點 | `experiments/k1149/k1149.py:750`、`experiments/k1148_d2/k1148_d2.py:570` |
| abstract 矛盾 | `body.tex:74`（market-level constant）vs `body.tex:130,233`（within-market analyst attention） |
| Table 1 footnote vs abstract 矛盾 | `body.tex:646–658` vs `abstract:85–91` |
| 支持實驗 | k1145 / k1147 / k1150 / k1148_d2 / k1148_d1 / k1149 / k1163 / k1172 / k1207 / k1216c / k1470 |
| reproduce gate | `reproduce.py` + `reproduce_report.json`（2026-07-06，20 cells green） |
| 對接 ops 任務 | `fable0711_dm_hac_auditor_blindspot`（next_tasks，稽核盲區補掃） |

---

## 9. 進度日誌

```
2026-07-11 | Fable deep review | 深審完成，待執行 P0 | f913ed68c
```

---

## 10. 接續提示詞

讀本 `EXECUTION.md` 後從 **P0-1** 開始：把 magnitude ordering（US>JP>TW）從 headline 降級，abstract / §1 intro / §6.2 / conclusion 主軸改寫為 **sign universality**（三市場 θ_EAV>0、cluster-bootstrap |t|∈{4.50,5.24,11.99}、placebo 各 0/60、13-market panel 外部效度）；同步消除 Table 1 footnote（`body.tex:646–658`）與 abstract（`:85–91`）關於 K1470 狀態的直接矛盾。這是 `paper_body` / main_thread 工作——**論文 .tex 不丟 background agent**。P0-1 落地後接 P0-2（abstract market-level-constant vs analyst-attention 矛盾修復）、P0-3（k1148/k1149 DM canonical HAC + date-aggregated panel DM 重算）。權威證據與逐行定位見 `review_history/fable_deep_review_20260711/README.md` §3–§5。
