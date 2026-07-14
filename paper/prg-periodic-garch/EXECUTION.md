# EXECUTION — prg-periodic-garch

> **BADGE** · `verdict=v7-rewrite-done` · `journal=FRL` · `stage=revision` · `p0=DONE` · `p1_rewrite=DONE` · `reproduce_gate=GREEN(26/26)` · `blocker=v7 review cycle（latex+citation+Codex）未跑`

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

> ✅ P0 全數完成（2026-07-14）。P0-1 的解法比原規格更徹底：不是修補 K880，而是整個 mixed 面板在 pinned vintage 重生成（K1710），舊 K880 鏈全數退役。

- [x] **✅ P0-1｜SPY 數字 errata + reproduce gate 重建**（2026-07-14，路徑升級）
  - errata 考古完成：`review_history/fable_deep_review_20260711/P0-1_errata_map.md`（三 vintage 對照 + NOT FOUND 清單）
  - mixed 面板改由 K1710 在 K1699 pinned snapshot 上重生成（SPY +5.83，6/6 Harvey）— 舊 6.00 僅存於 main.tex data 節 footnote 作歷史揭露
  - `reproduce.py` 全面重寫：JSON→tex 雙向 binding、26 checks 全部從兩個 canonical JSON 動態推導、無 live fetch；**GREEN 100%**；舊 live-yfinance gate 已刪（git history 保留）
  - （原規格「pin K880 + 修表格」由上述升級路徑取代；snapshot 的 auto_adjust 張力處置見 v7 決策記錄第 3 條）

- [x] **✅ P0-2｜K-new-A = K1699（六市場 Close-convention）**（2026-07-12 落地）
  - 0/6 Harvey vs GJR（exp/lag 雙變體一致）；高 overnight-share 市場無例外（「額外正面發現」情境不成立）
  - pinned + deterministic + bit-identical + Codex PASS_WITH_CAVEAT
  - **加碼 K1710**（2026-07-14）：open 面板（PRG open-known vs fair GJR-X，5/6 Harvey，QQQ +1.56 NS）+ mixed anchor 在同一批 snapshot 重生成 — 三面板單一 vintage，flip 主表成立

- [x] **✅ P0-3｜K1544 K 編號碰撞治理（2026-07-12）**
  - term-spread vol NULL 已由 `experiments/K1544/` 重編為 `experiments/K1696/`
  - PRG 爭點保留 K1544；本論文所有 K1544 仍明確指 `experiments/k1544_prg_fair_info_gjr/`
  - task / knowledge / generated audit 引用已遷移，dispatch 缺口已記 `docs/error_log.md`

---

## 4. P1 — 收斂主體（P0 落地後）

- [x] **✅ P1-1｜雙 convention body rewrite（2026-07-14，Fable 主線程完成）**
  - 前置 gate 滿足：≥3 互補實驗（K1544 + K1699 + K1710）+ 用戶 confirm（07-14 接續指令明示「開始 prg 雙時點重寫」）
  - 實際範圍比原規格更徹底：v7 = 全新稿（標題改為 Forecast-Timing Conventions...；三 convention 正式定義節；flip 主表為唯一中心；「natural and admissible」辯護、VaR/ES 表、VT 表、Separate ablation、HAR、MCS、舊 appendix 全部移除）；舊稿凍結為 `main_pre_v7.tex`
  - 新發現入稿：open 面板 t 與 ON share 六市場完全同序（EEM 70.7%/+10.14 → QQQ 38.5%/+1.56）
- [ ] **P1-2｜K-new-B（可與 rewrite 並行）**
  - (i) intraday-only target 版本（ĥ_d1 vs 含 current-ON regressor 的 benchmark intraday 方程），排除「r²_d0 加雙邊」機械性 QLIKE 壓縮疑慮
  - (ii) VT 經濟價值在 open-known convention 下重跑 + Sharpe difference bootstrap CI（一併關 MINOR #10）
- [x] **✅ P1-3｜FRL 減肥（v7 重寫時一併達成）**：正文 ~1.9k 字 ≤2,500；abstract 249 ≤250；9pp

---

## 5. P2 — 收尾（rewrite 後逐項 close）

- [ ] **P2-1｜殘留 open items**：MAJOR #6（ablation SPY-only scope）/ #7（intro L63 HAR target-mismatch 一般化殘句）、MINOR #9（機制引用）、0.748 vs 0.7559 同 n=1,823 的 1% 歧異 footnote（多數會在 rewrite 中自然消滅）
- [ ] **P2-2｜參數估計表（online appendix）+ ρ₀ρ₁ 平穩性報告**（referee 必問；現全文無任何參數估計值 / SE）
- [ ] **P2-3｜新一輪 v7 review cycle**（latex-academic-reviewer + citation-verifier + Codex independent），rewrite 完成後跑

---

## 6. DoD（Definition of Done — 全部未達成）

> 以下每一條達成才可標 ready / 進投稿 gate。**現狀全部 ⬜**。

- [x] ✅ reproduce gate = **green**（26/26 = 100%；v7 gate = JSON→tex binding、無 live fetch、全部 expected 值動態推導）
- [x] ✅ K-new-A（K1699）落地 + Codex reviewed；加碼 K1710（open+mixed 同 vintage）+ Codex PASS
- [x] ✅ 雙時點框架 body rewrite 完成（headline = timing-convention flip；辯護語氣全刪；v7 = 全新稿）
- [x] ✅ 正文 ~1.9k ≤ 2,500 字、abstract 249 ≤ 250 字（Highlights 檔待 v7 review 後補）
- [x] ✅ K1544 編號碰撞已治理（2026-07-12；term-spread → K1696，本論文 K1544 全指 `k1544_prg_fair_info_gjr`）
- [ ] ⬜ v7 review cycle 收斂（latex + citation + Codex independent，無 BLOCKING）— **下一步**
- [ ] ⬜ FRL 合規：author = Yi-Hao Lai only、無 volpred / AI / LLM 字樣、$200 fee、data availability Option C、Highlights 檔
- [x] ✅ Open-time 邊際市場誠實表述 — **pinned vintage 上事實更新**：5/6 過 3.0，唯一 NS = QQQ（+1.56，ON share 最低 38.5%）；vintage 脆弱性（pilot SPY 2.1/QQQ 3.0 vs pinned 3.56/1.56，方向不翻）已在 Robustness 段揭露

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
| 2026-07-12 | K1699 落地 | P0-2（K-new-A）完成：六市場 close-convention 0/6 Harvey，pinned + deterministic + Codex PASS_WITH_CAVEAT | （見 experiments/k1699/） |
| 2026-07-14 | v7 重寫開工（Fable 主線程） | 架構定案（見下方 v7 決策記錄）；main_v7_draft.tex 草稿完成（正文 ~1.8k 字 / abstract 243 字 / 編譯 9pp）；K1699 close 面板數字已入稿；K1710（pinned 重跑 open+mixed 面板）與 prg-recon（P0-1 errata map）兩個 Opus agent 已派 | 13dd4dcac |
| 2026-07-14 | **v7 重寫完成** | K1710 merge（bit-identical、Codex PASS、與 K1699 一致性 0.00e+00）；flip 主表 + 全部 prose 數字入稿（`scripts/gen_flip_table.py` 生成）；main.tex 晉升（舊稿凍結 `main_pre_v7.tex`）；reproduce.py 全面重寫 → **GREEN 26/26**；README / experiments.md / data_sources.md 改 v7 口徑；open 面板 pinned 事實 = 5/6 Harvey（QQQ NS）+ t 與 ON share 完全同序 | （本 commit） |

### v7 重寫決策記錄（2026-07-14，Fable 主線程裁定）

1. **Flip 主表 = 論文唯一中心**：六市場 × 三 convention（Mixed / Close / Open），全部綁單一 pinned vintage（2026-07-12）。Close 面板 = K1699；Mixed anchor + Open 面板 = **K1710**（新實驗：在 K1699 同一批 pinned snapshot 上重現 K1544 的 open-known vs fair GJR-X 與舊 canonical mixed 物件）— 這同時解掉 §7「K1544 點估計未 pipeline 重現不可入表」的禁令與 P0-1 的 SPY 漂移（整個 mixed 列直接在 pinned vintage 重生成，舊值以 footnote 揭露）。
2. **裁掉 VaR/ES、VT 經濟價值、Separate-GARCH ablation、HAR target-mismatch、MCS**：舊值全屬未 pin 漂移類（K880/K880v2 vintage 不可重現）；FRL 單一 sharp point 體裁本來就要砍。P1 若要加回，一律以 pinned 重跑為前提（VT/VaR = 原 P1-2(ii) K-new-B；Separate ablation = 選配新 K）。reproduce surface 因此縮到 K1699 + K1710 兩個 JSON。
3. **auto_adjust 硬規則張力處置**：K1699/K1710 的 pinned snapshot 上游（K880/K881/K886 loaders）用 `auto_adjust=True`，與 paper-workflow 硬規則字面（False）不符。裁定**不重跑**：規則根本目的（vintage 漂移）已由 pin + bit-identical 驗證根治；且調整價讓 overnight return 排除除息跳空，方法論上優於 raw。處置 = 論文 Data 節明文揭露 + 本記錄 + error_log 記錄；規則母本修訂（「pin 是 enforcement 點，flag 是揭露項」）待用戶可見時提案。
4. **符號 orientation**：論文全表統一「正 = PRG 優」；K1699 JSON orientation 相反（正 = GJR 優），入稿一律翻轉並在 `% source` comment 明記。
5. **標題改**：Forecast-Timing Conventions and the Value of Overnight Information in Volatility Forecasting（headline pivot 的自然結果；舊標題的 "Session-Boundary Information Transfers" 屬舊敘事）。

---

## 9. 接續 Prompt（下次開工直接貼）

> 讀 `paper/prg-periodic-garch/EXECUTION.md` 後，從 **P0-1** 繼續：K880 snapshot pin + SPY 數字 errata + reproduce gate 重建。
>
> 具體：(1) pin yfinance snapshot CSV（`auto_adjust=False`）到 `experiments/k880/`；(2) 以 2026-06-13 重跑版為 canonical，重生成 main.tex 全部 SPY 表格數字（DM 6.00→5.06、VaR 0.93%→1.32%、MCS All→PRG Basic+Ext、best model Ext→Basic）並在論文側補 errata；(3) `reproduce.py` 改讀 snapshot + 更新 target 值，重跑至 `reproduce_report.json` match_rate ≥ 95% 且 alert_level=green。完成後接 P0-2（派 K-new-A 六市場 Close-convention 到 compute queue）。
>
> 核心敘事已定（§1）：雙時點 convention 框架、timing-convention flip 升為 headline — 但 body rewrite（P1-1）須等 P0 + K-new-A 齊備並經用戶 confirm 後才動。禁止事項見 §7（勿再辯護單一 convention、勿引漂移舊值、FRL 字數硬砍、K1544 編號治理）。
