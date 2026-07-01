# leverage-direction — 投稿選項 Decision Memo

**日期**：2026-07-01 14:15（台灣時間）
**收件**：yihao.lai@gmail.com（老闆）
**由**：hourly-14 dispatch（VolPred 自主運營經理）
**目的**：打破 owner_decision_pending stall — 提供結構化選項讓老闆 5 分鐘拍板

---

## 30 秒 TL;DR

- Stage 1+2 reframe **技術面已完成**（compliance scrub CLEAN；xelatex 通過；package 已組）
- 但 **empirical pillars 都 weak**：K1591 gold regime NS、K1592 model-selection OOS 0 Harvey-Holm significant
- 3-pass multi-round codex review **一致 FAIL_MAJOR_REVISION**（contribution BORDERLINE）
- 論文**不能以現況投 JBF**；需要老闆選 reframe 路徑：**A（重寫窄化投 JBF）／B（降 FRL/IJF）／C（negative-results）／D（shelve + 拆入其他 paper）**
- **建議路徑：B**（見底部）— reason：A 的重寫工作量與 JBF 拒稿風險最高、C 的期刊池太窄、D 浪費已有 8 個月工作
- **老闆只需回一行**：`A / B / C / D` + 任何補充

---

## 1. 現況拆解（What's actually broken）

### 已完成（sunk cost，任何選項都保留）

| 項目 | 狀態 |
|---|---|
| Compliance scrub（K-id/VolPred/AI/LLM 全清） | ✅ CLEAN（`scripts/check_paper_compliance.py`） |
| xelatex 編譯 | ✅ 49pp PDF |
| Author = Yi-Hao Lai only | ✅ |
| Cover letter | ✅（惟 t=-5.79 stale gold 已修） |
| Submission package 檔案 | ✅ 齊全 |
| Stage 2 rebuild — gold pre-specified regime (K1591) | ✅ 技術完成，但**結果 weak** |
| Stage 2 rebuild — model selection genuine OOS horse race (K1592) | ✅ 技術完成，但**結果 NULL_OR_WEAK** |

### 三個結構性阻礙（reframe 都要面對）

#### (1) Contribution 過度分散
- 現稿同時談：leverage direction taxonomy、GJR model selection、VaR/ES scoring、VT allocation、time-zone arbitrage、complexity ceiling、VIX/HAR/crowding
- Codex verdict：「JBF editor 會 desk-reject，除非窄化到 ONE contribution」
- 建議 central claim：「Leverage direction (GJR gamma sign) 是可用來選 vol model 與判斷 VT 何時有經濟價值的 state variable」

#### (2) Gold finding 內部矛盾
- 舊 draft：`gamma = -0.067, HAC t = -5.79, 93% negative`（強）
- Canonical re-est：`gamma = +0.002, t = +0.15, NS`（消失）
- Regime split：bull `gamma=-0.043` vs bear `+0.048` (t=-3.79) — **有故事但 N=1 asset + 未 ex ante validate**
- Cover letter 仍寫 `t=-5.79` → 內部矛盾（已修）
- 骨牌：Codex 判定「unconditional inverted gold leverage 站不住；regime 需 out-of-sample 獨立驗證」

#### (3) OOS/Sample map 不一致
- Data section: 2017-01 到 2026-03
- Sample para: 2023-24 OOS + 2025-2026Q1 validation
- Table 1 caption: In-Sample = 2017-2025
- Table 3: 2025 是 OOS
- 三處 sample-split 互相打架 → JBF referee 不接受
- Cover letter: 12 DM comparisons；abstract/body: 11；Table 3: BTC 2025 缺列 → 敘事錯配

---

## 2. 四個投稿路徑選項

### 選項 A：Reframe → 目標 JBF R&R（原始 target）

**動作**：
- 窄化到 ONE contribution（leverage direction 的 economic content for allocation）
- 移除 time-zone、拆 VaR/HAR/crowding 到 online appendix
- Gold 用 ex ante pre-specified regime（NBER recession / VIX quantile / gold-safe-haven proxy），holdout validate
- Model selection 重建：pre-specify on one universe/period → test on disjoint（DM + MCS + FDR）
- 統一 sample split；砍到一致的 12（或 11）個 comparisons
- Rewrite intro + abstract + conclusion 全鎖 ONE claim
- Independent VT channel identification（不用 GJR construction）
- Report economic magnitudes/turnover/costs/utility

**Effort**: 4-6 週全職重寫（body 至少改 40%，重跑實驗，重建 tables/figures）
**Success prob (JBF R&R)**: ~25-35%（Codex 判 BORDERLINE，reframe 後仍需說服 editor）
**Pros**: 目標最高（JBF impact factor / 老闆學術聲譽 / 平台學術護城河）
**Cons**: Effort 最高；失敗 → 資源沉沒 + 老闆時間成本；empirical 骨幹弱（N=6 OOS + gold regime N=1）reframe 也未必救得回

---

### 選項 B：Downshift → 目標 FRL / IJF（建議）

**動作**：
- 定位改成 **diagnostic + honest null 論文**：「leverage direction 這個 state variable，實測在跨資產類別的實用邊界」
- 保留現有 taxonomy 為 descriptive contribution
- 承認 gold unconditional 是 NULL、regime dependent 是 tentative
- 承認 model selection 6/6 OOS 太小，作為 preliminary evidence
- 主 message：「即使窄到 equity-type domain，rule works；跨到 commodities/bonds/crypto 失效 — 有訊號但不 universal」
- 標題重擬（避免 overclaim）：如 `Leverage Direction as a State Variable for Volatility Model Selection: Cross-Asset Evidence and Limits`
- Body 修改幅度：25-35%（intro/abstract/conclusion 重寫，method 大致保留）

**Effort**: 2-3 週
**Success prob (FRL R&R)**: ~50-60%（FRL 較接受 honest null + narrower scope）
**Success prob (IJF R&R)**: ~40-50%
**Pros**: Effort 中等；FRL/IJF 較能接受 diagnostic 論文；學術 credit 仍在（都 SSCI Q2-Q3）；不浪費已投入時間
**Cons**: 較 JBF 影響力低；老闆若在意 top-tier signal 不理想
**Timeline**: 2026-08 中前完成 R1 → 送稿；FRL R2 週期 6-9 個月

---

### 選項 C：Reframe → Negative-Results / Methodology-focused 期刊

**動作**：
- Central claim 完全翻轉：「即使 pre-specified regime + genuine OOS + FDR control，leverage direction 都 NULL / borderline — 現行文獻的 discovery 多數可能是 over-fitted」
- 定位 methodology paper — 貢獻是 discipline，不是 finding
- 目標期刊：*Journal of Empirical Finance* 部分 methodology issue / *Empirical Economics* / *Journal of Forecasting*

**Effort**: 3-4 週
**Success prob**: ~30-40%（negative-results/methodology 期刊池窄；審稿人常要求 constructive contribution）
**Pros**: 對 replication crisis 話題有貢獻；平台「研究誠實」品牌強化
**Cons**: 期刊池窄；impact factor 較 FRL/IJF 低；等於承認整份工作沒找到正向結果 — 學術履歷 signal 不佳

---

### 選項 D：Shelve → 拆入其他 paper

**動作**：
- 停止 leverage-direction 投稿線
- gold regime 結果 → 拆入 `vt-crowding-abm` 或 `garch-x-vix` 作 supporting evidence
- Model selection null → 拆入 `forecast-tail-divergence` 或未來 methodology paper
- 已產出的 tables/figures / K1591 / K1592 保留在 experiments/，之後再用

**Effort**: 1 週（closing paperwork + 資料重新歸位）
**Success prob**: N/A（不投稿）
**Pros**: 立即釋放老闆 mental bandwidth 給 vt-trend-following（下一棒）；已完成 8 個月的技術成果不浪費（拆用）
**Cons**: 沒有獨立 leverage-direction 論文；老闆若對「leverage direction 是可獨立成篇的概念」情感上 attach 會不甘

---

## 3. 建議路徑：**選項 B（Downshift FRL/IJF）**

**理由（Rank order）**：

1. **A 的期望值低**：JBF R&R prob ~30% × 6 週 effort = 期望產出 1.8 week-equivalent；B 是 55% × 2.5 週 = 1.4 week-equivalent — B 每週產出更高
2. **A 的 downside risk 高**：JBF desk-reject / R1 拒 → 6 週白花，還要走 B 或 C 重投；B 若失敗只損失 2-3 週
3. **Empirical foundation 弱**：pillars 都 weak — 這是**結構性**問題（K1591/K1592 兩個 experiment 的原始結果 NS/NULL），不是敘事問題。reframe 敘事再漂亮也救不回 empirical 骨幹弱
4. **FRL/IJF 定位相符**：這兩份期刊本就更能容納「diagnostic + limits」型論文；leverage direction 的 6-asset equity-type domain 有 signal 是 real contribution，只是不到 JBF 標準
5. **不浪費 sunk cost**：現有 compliance-clean package、tables、實驗結果 80% 可保留；只需要重寫 intro/abstract/conclusion 定位
6. **與 vt-trend-following 排程協調**：B 路徑 2-3 週 → 可與 vt-trend v7 修完剩下 10 items 平行推進；A 路徑會壟斷老闆論文線 6 週
7. **平台學術品牌**：「持續產出 solid 二線期刊論文」比「賭 top-tier 但 6 週後空手」的 signal 更穩定

**Second-best**：如果老闆對 top-tier 情感 attach 較強、可接受 downside → 選 A。**C/D 不建議**（C 期刊池窄、D 浪費獨立敘事）。

---

## 4. 老闆需回覆什麼

**Email 回信**：

```
[VolPred] Re: leverage-direction 選 A/B/C/D
選：<A/B/C/D>
補充：<可空>
```

**時限建議**：本週內。leverage-direction stall 1 天 = vt-trend-following 也連帶壓後（因為老闆 bandwidth 被卡）。

**回覆後 hourly-dispatch 會自動接手**：
- 選 B → 派 `paper_body_leverage_direction_downshift_FRL`，2-3 週分成 hourly tick 執行；FRL profile 對照 `.claude/skills/journal-review/`
- 選 A → 派 `paper_body_leverage_direction_reframe_JBF`，6 週；需 4-6 個 K experiment 重跑
- 選 C → 派 `paper_body_leverage_direction_negative_results_reframe`
- 選 D → 關掉 pipeline_status entry；K1591/K1592 findings 加 note；opening vt-trend v7 全速推進

---

## 5. Supporting Evidence（老闆若想細看）

- Contribution gate report: `paper/leverage-direction/review_history/codex_contribution_gate_20260701.md`
- Multi-round review dir: `paper/leverage-direction/review_history/multi_round_20260701/`
- Active v3 final gate: `paper/leverage-direction/review_history/multi_round_20260701/active_v3_final_gate_20260701.md`
- Pipeline status entry: `storage/paper_pipeline_status.json` — `papers[0]`

---

*Memo end. Reply-only decision needed.*
