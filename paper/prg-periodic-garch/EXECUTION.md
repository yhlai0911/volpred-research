# EXECUTION — prg-periodic-garch

> **BADGE** · `verdict=2/5` · `journal=FRL` · `stage=revision` · `p0=TODO` · `reproduce_gate=RED` · `blocker=K1544 timing-convention 敘事未收斂 + SPY canonical 數字漂移`

_最後更新：2026-07-11（Fable 深審輪）。本檔是 prg-periodic-garch 的可執行收斂計畫；單篇深審全文見 `review_history/fable_deep_review_20260711/README.md`。_

---

## 1. 最終目標

把 prg-periodic-garch 從現狀（Major Revision，三個獨立致命傷）收斂到**誠實且可投 FRL** 的狀態。

**核心敘事裁定（K1544，本輪定調 — headline pivot）**：
放棄「單一 canonical timing convention + 辯護」路線，**重寫為「雙時點 convention」框架，並把 timing-convention flip 本身升格為論文 headline finding**。

- 同一模型、同一資料：**混合時點評估**給 DM ≈ +6.0；**嚴格 close-time**（t−1 day-ahead）給 −0.6 ~ −1.5；**coherent open-time** 給六市場全勝但幅度重排。
- 一句話新定位：「session-level 波動率模型的評估對 forecast-timing convention 高度敏感；在兩個 coherent convention 下誠實評估，PRG 的 session bridge 於 open-time 具跨六市場真實增量，於 strict close-time 與 GJR 無異。」
- 這比原「PRG dominates」更誠實、更新穎、更符合 FRL 單一 sharp-point 體裁，且對整個 overnight-information 文獻構成方法論警示。**收斂後的論文比原版更有投稿價值，不是更弱。**

**投稿目標期刊**：FRL（維持）。備援：IJF / JoF Markets（若 FRL desk-reject，可展開回 full paper）。

---

## 2. 現況快照

| 項目 | 值 | 來源 |
|---|---|---|
| Verdict | **2 / 5（Major Revision，No-Go 投稿 / Go 修訂）** | `review_history/fable_deep_review_20260711/README.md` §1 |
| 目標期刊 | FRL（字數超限待砍） | pipeline_status |
| Pipeline stage | revision（2026-05-21 起） | `storage/paper_pipeline_status.json` |
| Blocker | K1544 timing-convention 敘事未收斂 | pipeline_status |
| Canonical 稿 | `main.tex`（647 行，2026-07-01 最後編輯；main.pdf 19 pp） | 深審 §2.1 |
| Reproduce gate | **RED**（SPY 6.00 vs 重跑 5.064 = 15.6% 差，超 04-27 版 15% tolerance） | 深審 §3.4 |

**三個獨立致命傷（任一都足以擋下投稿）**：
1. **識別未收斂 + 敘事殘留** — Table 1 headline / abstract / §4.2 辯護語氣全建立在混合時點物件上；K1544 已證明同在 open 時點簡單 GJR-X 就贏 canonical PRG。
2. **SPY 數字漂移 + reproduce gate RED** — K880 於 2026-06-13 重跑，SPY 全列漂移（DM 6.00→5.06、VaR 0.93%→1.32%、MCS All→PRG-only、best model Ext→Basic）；main.tex 仍引用已不存在於 repo HEAD 的舊值。
3. **FRL 格式硬傷** — 正文 ~3,839 字（上限 2,500）、abstract ~383 字（上限 250）、19 pp。純格式即 desk-reject。

---

## 3. P0 — 必做（阻擋投稿，尚未執行）

> 全部 ⬜ TODO。P0 未動任何一項前，不得跑 review / 標 ready / submit。

- [ ] **⬜ P0-1｜K880 snapshot pin + SPY 數字 errata + reproduce gate 重建**（接續起點）
  - pin yfinance snapshot CSV（`auto_adjust=False`，paper-workflow 硬規則 1）
  - 以 6/13 重跑版為 canonical 重生成全部 SPY 表格（Table 1 / 3 / 4 + appendix）
  - `reproduce.py` 改讀 snapshot + 更新 target 值；重跑 gate 至 **green**
  - paper 側補 K880 重跑 errata 記錄（README 有記，但論文側無 errata、無 alert）
  - _為何最先做_：不做則後續一切 review 都建在漂移的地基上。

- [ ] **⬜ P0-2｜派 K-new-A（六市場 Close-convention 補跑）**（compute queue）
  - PRG_tminus1（ĥ_ov + ĥ_in(ĥ_ov)）vs GJR / HAR，全部在 F^c_{d−1} 同資訊集
  - 複用 `experiments/k1544_prg_fair_info_gjr/` 六市場 infra（改造成本低）
  - 驗證「strict t−1 下 PRG 無優勢」是否六市場一般成立（目前僅 SPY 證據）；若高 overnight-share 市場（TAIFEX/GLD）close-time 下仍勝，是額外正面發現
  - _性質_：敘事收斂的最後一塊實驗證據。

- [x] **✅ P0-3｜K1544 K 編號碰撞治理（2026-07-12）**
  - term-spread vol NULL 已由 `experiments/K1544/` 重編為 `experiments/K1696/`
  - PRG 爭點保留 K1544；本論文所有 K1544 仍明確指 `experiments/k1544_prg_fair_info_gjr/`
  - task / knowledge / generated audit 引用已遷移，dispatch 缺口已記 `docs/error_log.md`

---

## 4. P1 — 收斂主體（P0 落地後）

- [ ] **P1-1｜雙 convention body rewrite（主線程執行，non-patch major rewrite）**
  - **前置 gate（narrative state machine）**：≥3 互補實驗已備（K880v2、K880-rerun PRG_tminus1、K1544、K-new-A）→ **用戶 confirm 雙 convention 重寫後** 才設 `status=decision_made_awaiting_body_rewrite` 並開始改 body
  - 範圍：abstract 全重寫（≤250 字）；§2.2 改雙 convention 定義（刪「natural and admissible」辯護段）；Table 1 重做為雙 convention 面板；§4.2 改 convention 對照主節；§4.5 以 K1544 fair GJR-X 取代 K1260 lagged 版（K1260 降 appendix）；§4.3/4.4 用重跑後數字重生成並縮編；Discussion/Conclusion 重寫定位
- [ ] **P1-2｜K-new-B（可與 rewrite 並行）**
  - (i) intraday-only target 版本（ĥ_d1 vs 含 current-ON regressor 的 benchmark intraday 方程），排除「r²_d0 加雙邊」機械性 QLIKE 壓縮疑慮
  - (ii) VT 經濟價值在 open-known convention 下重跑 + Sharpe difference bootstrap CI（一併關 MINOR #10）
- [ ] **P1-3｜FRL 減肥：正文砍到 ≤2,500 字（現 3,839，須砍 ~35%）**
  - VaR/ES 全表、appendix、參數表移 online appendix；主文只留 timing flip + 六市場雙 convention 主表 + ablation

---

## 5. P2 — 收尾（rewrite 後逐項 close）

- [ ] **P2-1｜殘留 open items**：MAJOR #6（ablation SPY-only scope）/ #7（intro L63 HAR target-mismatch 一般化殘句）、MINOR #9（機制引用）、0.748 vs 0.7559 同 n=1,823 的 1% 歧異 footnote（多數會在 rewrite 中自然消滅）
- [ ] **P2-2｜參數估計表（online appendix）+ ρ₀ρ₁ 平穩性報告**（referee 必問；現全文無任何參數估計值 / SE）
- [ ] **P2-3｜新一輪 v7 review cycle**（latex-academic-reviewer + citation-verifier + Codex independent），rewrite 完成後跑

---

## 6. DoD（Definition of Done — 全部未達成）

> 以下每一條達成才可標 ready / 進投稿 gate。**現狀全部 ⬜**。

- [ ] ⬜ reproduce gate = **green**（match_rate ≥ 95%、alert_level=green；SPY 表格已 rebind 到 6/13 重跑 canonical）
- [ ] ⬜ K-new-A（六市場 Close-convention）已落地並 Codex reviewed
- [ ] ⬜ 雙時點框架 body rewrite 完成（headline = timing-convention flip；已刪「natural and admissible」辯護）
- [ ] ⬜ 正文 ≤ 2,500 字、abstract ≤ 250 字、Highlights 檔齊
- [x] ✅ K1544 編號碰撞已治理（2026-07-12；term-spread → K1696，本論文 K1544 全指 `k1544_prg_fair_info_gjr`）
- [ ] ⬜ v7 review cycle 收斂（latex + citation + Codex independent，無 BLOCKING）
- [ ] ⬜ FRL 合規：author = Yi-Hao Lai only、無 volpred / AI / LLM 字樣、$200 fee、data availability Option C
- [ ] ⬜ 開 Open-time 新 headline 下 SPY(2.12) / QQQ(2.97) 不過 3.0 門檻已誠實表述（4/6 過、2/6 marginal），不迴避

---

## 7. 禁止事項（本篇特有）

- **不可再辯護單一 timing convention**。現稿 §4.2「validates the Open convention as natural and admissible」的辯護語氣必刪；改雙時點對照框架。v6 的 "joint advantage" 措辭是 hedging 不是修復。
- **不可再引用漂移的 SPY 舊值**（DM 6.00 / VaR 0.93% / p=0.77 / MCS=All / best=Ext 皆 stale，僅存於 git `74a01c5db^`）。一切 review / 表格 / abstract 用 6/13 重跑版 canonical。
- **FRL 字數硬上限不可超**：正文 ≤ 2,500、abstract ≤ 250。照現結構（3,839 / 383 / 19 pp）投 FRL = desk-reject。
- **K1544 引用仍不可含糊**：碰撞已於 2026-07-12 治理，所有 K1544 引用須明確指向 `k1544_prg_fair_info_gjr`；term-spread NULL 現為 K1696。
- **reproduce gate RED 狀態下不可標 ready / submit**（paper-workflow 硬規則 2）。
- **K1544 點估計脆弱**（非凸 MLE multistart，方向穩定但精確值需在 paper pipeline 內重現後才可入表）— 未 pipeline 內重現前不可硬 code 進 Table。
- 不手改 canonical JSON 湊數；數字不符走「修腳本 / 修論文 / 明記 errata」三選一（paper-workflow 硬規則 4）。

---

## 8. 進度日誌

| 日期 | 動作 | 摘要 | commit |
|---|---|---|---|
| 2026-07-11 | Fable deep review | 深審完成，待執行 P0 | f913ed68c |

---

## 9. 接續 Prompt（下次開工直接貼）

> 讀 `paper/prg-periodic-garch/EXECUTION.md` 後，從 **P0-1** 繼續：K880 snapshot pin + SPY 數字 errata + reproduce gate 重建。
>
> 具體：(1) pin yfinance snapshot CSV（`auto_adjust=False`）到 `experiments/k880/`；(2) 以 2026-06-13 重跑版為 canonical，重生成 main.tex 全部 SPY 表格數字（DM 6.00→5.06、VaR 0.93%→1.32%、MCS All→PRG Basic+Ext、best model Ext→Basic）並在論文側補 errata；(3) `reproduce.py` 改讀 snapshot + 更新 target 值，重跑至 `reproduce_report.json` match_rate ≥ 95% 且 alert_level=green。完成後接 P0-2（派 K-new-A 六市場 Close-convention 到 compute queue）。
>
> 核心敘事已定（§1）：雙時點 convention 框架、timing-convention flip 升為 headline — 但 body rewrite（P1-1）須等 P0 + K-new-A 齊備並經用戶 confirm 後才動。禁止事項見 §7（勿再辯護單一 convention、勿引漂移舊值、FRL 字數硬砍、K1544 編號治理）。
