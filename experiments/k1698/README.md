# K1698 — forecast-tail-divergence E1 v2：尺度再校準 gating 實驗（K1684 BLOCK 後合規重跑）

- **Experiment ID**: `k1698`
- **Status**: completed（2026-07-13 primary-path Codex review PASS；nested-DM 角色與 gate dataflow 已機械隔離）
- **執行日期**: 2026-07-12（台灣時間）
- **提出者**: Codex review of K1684（BLOCKED 2026-07-12）＋ Fable 深度審查 2026-07-11 §5.1 E1（P0 gate）
- **父實驗**: `k850`（原始 headline）、`k854`（common-sample 版）、`k1684`（被 BLOCK 的 v1）
- **腳本**: `k1698.py` ｜ **結果**: `k1698_results.json`（原子寫入）｜ **執行 log**: `run_log.txt`
- **資料**: `data/`（新建 aligned RV snapshot + 舊 TX1 RV snapshot + 0050 調整後收盤，全部 pin 死）
- **Seed**: `20260712`（GJR/RGL multistart、bootstrap、擾動 audit、AS 模擬全部固定；無 process-randomized `hash()`）

---

## 1. 裁決（Go / No-Go，事前寫死的規則之下）

> ## **GATE_VERDICT = H2_REJECTED** → 走 **FRL / Journal of Forecasting 方法論短文**，不走完整 IJF 論文
>
> 觸發條款：**腿 1 未過事前 `t < −3` 保守 guardrail** — aligned target（0050 r²）上 HAR-RV 對
> robust GJR 的非巢狀 QLIKE DM **t = +1.47（p = 0.14, n = 436）**：沒有 HAR 勝出的證據，
> 點估計方向還是 GJR 較優。沒有共同 target 上的預測損失優勢，就沒有「divergence」可談。

**v2 比 K1684 更深一層的發現：連 HAR 自家 target 的著名 t ≈ −5.6 都是 RV 建構 artifact 的一部分。**

| DM（QLIKE, canonical, h=1） | 舊 RV（bridge run，K854 建構） | 新 RV（primary，active-contract gap-complete aligned） |
|---|---|---|
| HAR vs GJR，**HAR 自家 RV target** | **t = −5.25**（p < 0.001；K850 世界的 headline） | **t = −2.06**（p = 0.040）— **未過事前門檻** |
| HAR vs GJR，**aligned target（0050 r²）** | t = +2.31（p = 0.021，GJR 優） | **t = +1.47（p = 0.14）— 無顯著差異** |
| HAR+CF 1% 違規 | **17/450**（= K854 published，完全復現） | **14/450**（仍 FAIL，但 RED → yellow） |
| 校正因子 (a) std(z) / (b) MZ / (c) HL | 1.354 / 1.349 / 1.204（= K1684 数值，完全復現） | **1.203 / 1.211 / 1.075** |
| Placebo（同機器套在 GJR 上） | 1.119 | **1.119** |

Bridge run（同 code、同 robust GJR、只把 RV 換回 K854 建構）**完全復現 K1684/K854 的世界**（HAR+CF
17/450、46/450；因子 1.354/1.349/1.204；own-target t=−5.25 ≈ K1684 的 −5.13）→ 上表左右欄的差
**全部來自 RV 重建本身**，乾淨隔離。

**含義**：K850/K854 的「QLIKE 大勝 + VaR 大敗」敘事由**四個**建構性混淆疊出來（K1684 找到三個，
v2 加上第四個且它吃掉最多）：
1. **RV 建構缺陷**（TX1-only、漏 session boundary jumps、13:30/13:45 資訊集重疊）— 修好後 own-target
   優勢從 t=−5.25 掉到 −2.06、HL 尺度因子從 1.204 掉到 1.075；
2. 變異數 target 尺度錯配 — 剩下的部分（新 RV 下 std(z)≈1.20，但 placebo 也有 1.12，見 §4.3）；
3. QLIKE 鏡像 target 錯配（own-target 獎勵 HAR、VaR 端懲罰 HAR）；
4. 尾層殘差池窗口（`sens_burnin_tailpool` 再確認：池含 COVID 時未校正 HAR+CF 自己變 3/450 綠燈 PASS）。

---

## 2. K1684 blocker 逐項解決對照表（review gate 判準）

| # | CODEX_REVIEW_BLOCKED.md 要求 | v2 做法 | 證據（本次實際數字） |
|---|---|---|---|
| **1** | GJR ≥100 starts + convergence + basin 分佈；robust fit 重算全部 headline | `fit_gjr_robust()` **120 個 seeded 起點**/refit，逐 refit 存 convergence、objective、LL 分群；全部 QLIKE/DM/VaR/ES 用 robust fit | fragility probe v2（同 1e-6 資料修訂）：σ 最大漂移 **29.03% → 5.03%**，GJR+Normal 違規數 **[8,10]/[20,21] → [9,9]/[21,21]（零翻動）**。LL 面診斷：120 起點散佈在 ~0.4 LL 單位的平坦 ridge（1e-3 分群得 116–120 群 — 是 flat ridge 上的 optimizer scatter，不是分離 basins），best-of-120 消掉了 4-start 的抽籤性 |
| **2** | 全 TX 每日成交量選 active contract；連續 tick path 含所有 session boundary jumps；封 13:30/13:45 資訊集 | `build_aligned_rv()`：per-day max-volume 合約、**單一合約**連續 5-min path，視窗 **13:30(D−1) → 13:30(D)**（含 day-tail、13:45→15:00 gap、PM→AM、05:00→08:45 gap 全部 jumps）；RV(t−1) 終點 = target 視窗起點 → 資訊集**建構上不相交** | 2,191 天、108 個 roll 日（無跨合約 return）、anchor 缺失 **0**、平均 222 returns/日；`rv_window_boundary_audit` **60 天全過**；vs 舊 RV corr 0.820、mean ratio 1.256 |
| **3** | 修 CI 單調性；implied_c 僅在可識別 cell 解讀；bootstrap 取代 0.10 閾值 | 通道診斷改用**分佈自由** `c_emp(α) = Q_{1−α}(r/VaR)`（等價於精確覆蓋所需的 σ 乘數，任何尾層都可識別）＋ **paired moving-block bootstrap**（B=2000, block=25, 共用 index draws）對 Δc=0 做正式檢定；Normal 映射僅 +Normal cells 報告且修正為遞增（K1684 反了，倒置 154 個 CI） | §4.3 表：分類全部帶 95% CI；無任何 lo>hi |
| **4** | Placebo 完整口徑報告；不得寫「near 1」；三 estimator 非獨立 | GJRf/GJRf-a 進**所有**表格（trinity 兩 α、ES、FZ0、c_emp bootstrap）；三 estimator 相關性入 JSON | OOS placebo s = **1.119**（與 HAR 的 1.075–1.211 同量級 — 校正機器**確實會動** GJR，照實報告）；**IS placebo = 0.993**（§4.5 的關鍵發現）；corr(s_a, s_c)=0.71 / corr(s_a, s_mz)=−0.23 / corr(s_c, s_mz)=−0.52，JSON 內註明非獨立 |
| **5** | 事前 \|t\|>3 保守 guardrail；gate 檢查 leg 2 GJR PASS；sensitivity 用 pairwise mask 報 n；補 1%/5%、IS/OOS VaR+ES、joint loss | `decide_gate_v2()` 事前寫死（§3.3）且**明確檢查** leg-2 pattern（本次 = true：HAR+CF FAIL 且 GJR+CF PASS @1%）；raw DM 僅保留明確非巢狀 pairs，逐筆存 role / relation / feeds_gate；**1%+5% × IS+OOS × VaR trinity + McNeil-Frey + Acerbi-Szekely Z2 + FZ0 joint loss** 全報 | aligned DM n=436、mismatched n=450 各自標明；`sens_theta_short` 掉 HAR-b 三格→**declared dropped**，其餘 cell 完整 450 天 |
| **6** | Results 原子寫入 | `write_results_atomic()`：tmp → `json.load` 驗證 → `os.replace` | ✓ |
| **7** | 重跑後只用新 JSON 改 README；重新獨立 Codex review | 本 README 每個數字皆出自 `k1698_results.json`；2026-07-13 primary-path review 已確認 gate 只吃非巢狀 `HAR-RV_vs_GJR`，所有同族 raw-DM pair 已從結果移除 | **PASS** |

---

## 3. 設計

### 3.1 RV 重建（blocker 2 的核心）

`rv_aligned(D)` = active 合約（當日成交量最大月份）的**單一合約**連續 5-min log-return 平方和，視窗
`(13:30(D−1), 13:30(D)]`，起點錨在 13:30(D−1) 的最後成交價。TAIFEX 把夜盤掛在次一交易日（40 檔抽查
全數確認），所以視窗組裝 = 前一檔的 day-tail (13:30,13:45] ＋ 當檔夜盤 PM/AM ＋ 當檔日盤 ≤13:30，
**所有 session boundary jumps 以同合約 return 進入 RV**。這同時解決三件事：
- **gap-complete**：K854 分段累加漏掉的 13:45→15:00、PM→AM、05:00→08:45 跳空全部補齊；
- **active contract**：結算週的 roll gap 不再污染 RV（108 個 roll 日全部單合約 path）;
- **資訊集密封**：預測子 RV(t−1) 的視窗終點 = target return 視窗起點（13:30(t−1)），重疊為零 —
  由 `rv_window_boundary_audit`（60 天段落時間戳檢查）機械驗證，非口頭宣稱。

### 3.2 三個尺度 variant + placebo（沿 K1684，θ 與尾池解耦不變）

(a) expanding std(z)；(b) Mincer-Zarnowitz log-variance 映射 + Duan smearing（本次 OOS 斜率 b≈0.71）；
(c) Hansen-Lunde realized scaling Σr²/ΣRV。尾池釘死 K854 慣例（OOS-only、63 天 refresh），θ 用 2018+
長窗；placebo = 同一套 (a) 套在 GJR。全部 θ 嚴格 `u < t`，x10 擾動 audit **30/30 通過**（fail 即 raise）。

### 3.3 事前寫死的 gate 規則（`GATE_RULES`，跑數字前已固定在腳本頂部）

- **腿 1**：HAR-RV vs robust GJR，QLIKE on aligned target（0050 r²，Patton 跨模型唯一合法比較），
  兩者為非巢狀模型族，使用 canonical nonnested DMW/West-style HAC approximation。「HAR 勝」需
  **t < −3（事前保守 guardrail）**；|t| ≤ 3 = 腿 1 失敗（p<0.05 但 |t|≤3 照報但不算）。
- **腿 2**：baseline pattern = HAR+CF trinity FAIL @1% **且** robust GJR+CF trinity PASS @1%（**代碼內
  明確檢查** — K1684 的 gate 文字有寫但實作沒查，本次 = `true`）。
- **Rescue**：某 variant 的任一尾層在**兩個 α 皆全 trinity PASS**；Kupiec-only 覆蓋另列為次要判準。
- **Verdict**：H2_SURVIVES ⟺ 腿1過 guardrail ∧ 腿2 pattern ∧ 0 variant rescue；H2_REJECTED ⟺ 腿1 敗 ∨
  腿2 pattern 不在 ∨ 全部 estimable variant rescue；其餘 H2_PARTIAL。

**DM 角色邊界**：JSON 將 QLIKE raw DM 分成 `primary_nonnested` 與 `secondary_nonnested`；只有
aligned r² target 的 `HAR-RV_vs_GJR` 帶 `feeds_gate=true`，own-target 同 pair 是 secondary。
`HAR-a_vs_HAR-RV` 是 `s_a=1` 即退回 base 的巢狀尺度限制，
已從 raw DM 移除；FZ0 中所有共享 GJR variance path 的同族尾層比較也只保留各 cell mean loss。
QLIKE / FZ0 若日後要做正式巢狀推論，需另做 general-loss encompassing 或涵蓋完整遞迴重估的 bootstrap，
不可把只適用 MSPE 的 Clark–West 換標籤套上。

本次：腿 1 敗（t=+1.47）→ **H2_REJECTED**（腿 2 pattern 雖在、rescue 0/3，但腿 1 已終結命題）。

---

## 4. 結果（primary run；n = 450，2023-03-01 ~ 2024-12-31；OOS std 0.0128、kurt 8.11）

### 4.1 1% VaR trinity（節錄；primary 每個 α 20 cells；各 run 全表在 JSON，短 θ run 明列 3 cells dropped）

| Cell | 違規 | Kupiec p | Basel | Trinity | c_emp | AS-Z2 (ES) | FZ0 |
|---|---|---|---|---|---|---|---|
| HAR+Normal | 11/450 | 0.009 | red | FAIL | 1.328 | FAIL | −2.781 |
| **HAR+CF** | **14/450** | 0.000 | yellow | FAIL | **1.401** | **FAIL (p=0.000)** | −2.893 |
| HAR+HistSim | 9/450 | 0.060 | yellow | FAIL | 1.300 | pass | −2.968 |
| HAR-a+CF | 7/450 | 0.273 | yellow | FAIL | 1.165 | pass (p=0.086) | −3.117 |
| HAR-b+CF | 7/450 | 0.273 | yellow | FAIL | 1.159 | pass | −3.073 |
| HAR-c+CF | 9/450 | 0.060 | yellow | FAIL | 1.311 | FAIL | −3.022 |
| GJRf+CF（配對池 GJR） | 11/450 | 0.009 | yellow | FAIL | 1.285 | FAIL | −3.118 |
| GJRf-a+CF（placebo 校正後） | 8/450 | 0.135 | **green** | **PASS** | 1.143 | FAIL | −3.260 |
| **GJR+CF**（K854 錨） | **2/450** | 0.183 | green | **PASS** | **0.799** | pass (p=0.93) | −3.197 |
| RGL+CF | 3/450 | 0.449 | green | PASS | 0.827 | pass | −3.105 |

三個必須直說的點：
1. **校正把 HAR 的 1% 覆蓋修到 Kupiec 過**（14→7，p 0.000→0.273）但 trinity 全卡在 **Basel yellow**
   （last-250-days 窗內 a/b/c 分別 5/6/6 次違規，綠燈門檻 4）— n=450 下 Basel 綠燈由少數違規決定，
   rescue = 0/3 estimable。
2. **GJR+CF 的 PASS 是「過度保守」型 PASS**：c_emp = 0.80（CI [0.63, 1.02]），平均 1% VaR −3.95% vs
   HAR+CF −2.36% — 它用比需求寬 20% 的 VaR 換綠燈（Bams 2017 式的勝利）。
3. **placebo 校正讓配對池 GJR 也翻成 PASS**（GJRf+CF 11/450 FAIL → GJRf-a+CF 8/450 PASS）— 校正
   機器不是 HAR 專屬的「錯配修復」，它就是個泛用的保守化操作（blocker 4 的誠實版）。

5% VaR：HAR-a+CF / HAR-b+CF 皆 trinity PASS（27、28/450）；HAR+CF 40/450 FAIL；GJR anchor
（Normal / CF / Skewed-t）全 PASS，但 forecast-pool variant `GJRf+CF` 為 35/450、trinity FAIL。

### 4.2 QLIKE / DM（pairwise mask，n 各自報告）

| 比較（QLIKE；皆為非巢狀） | target | t | p | n | 事前 \|t\|>3 guardrail |
|---|---|---|---|---|---|
| HAR-RV vs GJR | **r²（aligned）** | **+1.469** | 0.142 | 436 | ✗（**腿 1 判準**） |
| HAR-RV vs GJR | RV_aligned（HAR 自家） | −2.064 | 0.040 | 450 | ✗ |
| HAR-a vs GJR | r²（aligned） | +0.043 | 0.966 | 436 | ✗（校正後打平） |

`HAR-a vs HAR-RV` 的 individual mean QLIKE 仍在 JSON，但因兩者是巢狀尺度限制，不再輸出 raw-DM
t / p。**FZ0 joint VaR-ES loss 的非巢狀 cross-family DM race**（vs GJR+CF anchor）：1% 的 HAR-family
pairs 全部 |t| < 1（HAR+CF vs GJR+CF t=+0.84）；RGL+CF vs GJR+CF 為 t=+1.154（p=0.249）。
所有 cross-family pair 都未過事前 |t|>3 guardrail；這不表示同族尾層等效。

### 4.3 通道診斷（分佈自由 c_emp + paired block bootstrap，取代 K1684 的 Normal 映射 + 0.10 閾值）

| Cell | c_emp(1%) [95% CI] | Δc [95% CI] | 事前規則分類 |
|---|---|---|---|
| HAR+CF | 1.401 [1.02, 2.10] | +0.131 [−0.25, +0.68] | **SCALE**（c≠1、Δc 含 0） |
| HAR+HistSim | 1.300 [0.95, 2.00] | +0.114 [−0.22, +0.68] | SCALE |
| HAR+Normal | 1.328 [0.95, 2.10] | +0.283 [−0.02, +1.01] | calibrated（CI 含 1 — **檢定力不足**，非證據） |
| HAR-a+CF（校正後） | 1.165 [0.85, 1.74] | +0.108 [−0.21, +0.56] | calibrated |
| **GJRf+CF（placebo 基線）** | **1.285 [1.02, 1.57]** | +0.110 [−0.20, +0.33] | **SCALE** |
| GJR+Normal | 1.168 [0.91, 1.48] | +0.248 [+0.03, +0.51] | **SHAPE**（Δc CI 排除 0） |
| GJR+CF | 0.799 [0.63, 1.02] | −0.127 [−0.34, +0.07] | calibrated（保守側） |

**對深審 §4.1 指紋的誠實更新**：HAR+CF 的 SCALE 分類在 bootstrap 口徑下存活，**但配對池的
GJRf+CF —— 一個 σ 打在自己 target 上、零錯配的模型 —— 給出幾乎同樣的 SCALE 指紋**（1.285 [1.02,1.57]）。
「兩個 α 等值的 implied scale」**不是 cross-target 錯配的專屬指紋**，平靜期 OOS-only 殘差池自己就會
製造它。這個否定結果本身是短文的素材。

### 4.4 ES 層（本次新增，blocker 5）

- **Acerbi-Szekely Z2**（cell 自身尾模型模擬 p，B=500）：1% 下 HAR+CF **z2=+2.29, p=0.000 FAIL**
  （ES 深度不足，不只 VaR 頻率超標）；校正後 HAR-a+CF p=0.086 過；GJR+CF z2=−0.65, p=0.93（保守）。
- **McNeil-Frey**：HAR+CF 1% 反而 pass（p=0.24, n_exc=14, mean residual −0.19）— MF 只看 exceedance
  residual 均值、n=14 檢定力極低；AS Z2 對頻率×深度聯合敏感，兩者張力照實報告。
- **FZ0**：見 §4.2 — 非巢狀 cross-family joint-loss pairs 無顯著排名分歧；GJR 同族尾層不做 raw-DM 推論。

### 4.5 IS vs OOS（本次新增；IS = 2019-01-02 ~ 2022-12-30，n=974，含 COVID 與 2022 空頭）

| | IS（單一 pre-OOS fit，池含 COVID） | OOS（primary） |
|---|---|---|
| HAR+CF 1% | 3/974 = 0.31%（Kupiec p=0.011 **因違規太少而 reject**） | 14/450 = 3.11% FAIL（不足） |
| GJR+CF 1% | 3/974 = 0.31%（同樣過度保守 reject） | 2/450 PASS（保守） |
| θ：std(z) | **1.103** | 1.203 |
| θ：placebo s_GJR | **0.993** | 1.119 |

**IS/OOS 的反轉方向本身是發現**：含 COVID 的殘差池把 CF 尾層撐得太寬（兩家在 IS 都過度保守），
平靜 OOS-only 池則太窄；同時 **IS placebo 回到 1.0**（0.993）而 OOS placebo 有 1.12 —— OOS 校正因子
裡至少有一半是「平靜池 + 2024 尾部事件」的泛用效應，不是 HAR 專屬的 target 錯配。深審「σ 系統性
低估 ~30%」的量級：新 RV 的 OOS 窗剩 ~20%、IS 窗剩 ~10%，且須扣掉 placebo 同向的 ~12%/0%。

### 4.6 敏感度與診斷 run

| Run | 關鍵差異 vs primary | 結果 |
|---|---|---|
| `sens_theta_short` | θ 也用 OOS-only 短池（HAR-b 三格不可估，declared drop） | verdict 同；**但 HAR-c+CF 兩 α 全 trinity PASS**（5/450 綠、24/450 綠）— 在此組態尺度校正完全 rescue，rescue 結論對 θ 窗有敏感性，照實報告 |
| `sens_daily_refresh` | 尾池每日更新 | verdict 同、量級同 |
| `sens_burnin_tailpool`（診斷，不裁決） | 尾池延長含 COVID | 未校正 HAR+CF 自己變 **3/450 綠 PASS** — 殘差池窗口第三通道再確認（與 K1684 一致） |
| `bridge_old_rv`（診斷） | 全套換回 K854 RV | 完全復現 K1684 世界（§1 表）— RV 重建效果的乾淨隔離 |

### 4.7 Robust GJR 與 K854 復現 bridge

- 120 起點/refit，8 refits 都是 **120/120 converged**；每次得到 116–120 個 1e-3 LL basins，
  LL 面在最優附近是 ~0.4 LL 單位的**平坦 ridge**
  （所以 K854 的 4-start 抽籤才會拉出 29% 的 σ 漂移）。best-of-120 下 1e-6 資料修訂的 σ 漂移剩
  5.03%，**兩個 α 的違規數零翻動**（[9,9]、[21,21]）— blocker 1 的「不穩定 GJR 不能承擔裁決」已解。
- K854 replication bridge：**11/14 格完全一致**；差的 3 格全是 GJR 家族（10→9、3→2、9→7），方向
  一致 = robust fit 略保守 — 這就是 4-start 不穩定值多少違規的量化答案。RV-driven cells（HAR×3、
  RGL）在舊 RV 下**逐格完全復現**（17、9、15、46...）。

---

## 5. 對論文的結論（短文路線的素材盤點）

1. **命題裁決**：H2（殘餘正交）被拒 — 且拒得比 K1684 更徹底：正確建構下**連 divergence 的表象都
   大半消失**（own-target t −5.25→−2.06）。原 outline 與深審 §4.1 的「σ 低估 ~30% 純尺度」需回溯
   降級：那個 30% 裡混著 RV 建構缺陷（最大宗）、平靜池泛用效應（placebo 1.12）、真正的
   composition/basis 殘餘（HL 因子 1.075，~7%）。
2. **短文的可攜貢獻**：(i) `c_emp` 分佈自由診斷 + paired bootstrap Δc 檢定（修好 K1684 的識別問題
   後仍站得住）；(ii) **RV-plug-in VaR 的四層建構檢查清單**（active contract / gap completeness /
   information-set alignment / 殘差池窗口）— 每一層都有本實驗的 before/after 數字當 evidence；
   (iii) 「SCALE 指紋不專屬錯配」的否定結果（GJRf+CF 對照）。
3. **不可宣稱**：HAR 劣於 GJR（aligned t=+1.47 n.s.）；divergence 存在；GJR+CF「校準良好」（它是
   c_emp=0.80 的過度保守 PASS）。
4. **回溯更正義務**（主線程）：K850/K854 knowledge entries 的 headline（t=−5.6 建立在有缺陷的 RV
   建構上）；深審 E1 條目中「缺隔夜」前提（K1684 已推翻）與「純尺度 30%」量級。

---

## 6. 限制（誠實揭露）

1. **n = 450 < ≥500 硬規則**；1% 期望違規 4.5 次，Basel 綠燈由單一違規決定（HAR-a+CF 的 FAIL 是
   window 內 5 vs 門檻 4）。所有分類附 bootstrap CI；「rescue 0/3」對 Basel 這種 knife-edge 判準
   的穩健性有限（`sens_theta_short` 下 HAR-c 全 rescue）。裁決主要靠腿 1（DM），不靠腿 2 邊界。
2. 單一市場、單一平靜 OOS 期間；IS 窗（含 COVID）已部分補足但屬 in-sample。E2（SPY, n≥2500）仍必要。
3. 三個 θ estimator 共用 r²/RV 資料（相關係數已入 JSON）— 是同一 wedge 的三個估計，不是三份獨立證據。
4. 5% Basel 燈號是 α-scaled 自訂延伸（沿 K854），非 canonical Basel。
5. CF 的 ES 由（可能非單調的）CF 分位數多項式積分而來；FZ0 中 es ≥ var 的列被剔除並計數（本次全部 cell 為 0 列）。
6. Skewed-t 錨的尾層沿 K854 單起點估計（2 參數、有界）；變異數 MLE 的 multistart 為
   GJR 120 起點、RGL 40 起點。
7. 0050 收盤價沿 K1684 的 `auto_adjust=True` snapshot（K854 指紋匹配到小數第 7 位；OOS std/kurt
   0.0128/8.11 再確認）— 與專案偏好 `auto_adjust=False` 不同，理由同 K1684 §10。
8. 新 RV 的 2017-01~2017-05（夜盤上線前）視窗只含日盤+隔夜跳空，屬訓練段；OOS 全在夜盤時代。
9. 非巢狀 gate 使用 canonical DMW/West-style HAC approximation，尚未做涵蓋完整 recursive refit 的
   bootstrap。因 aligned loss differential 的點估計方向本就朝 GJR（t=+1.469），只調標準誤不會產生
   事前定義的單尾 HAR 勝出；publication-grade size refinement 仍列為 sensitivity 工作。
10. Harvey–Liu–Zhu (2016) 的 `|t|>3` 是 multiple-testing 動機，不是 DM 專屬臨界值；本實驗只把它當
    事前保守 house guardrail，沒有標成「Harvey 顯著」。

---

## 7. 方法邊界與文獻

- West (1996, *Econometrica* 64, 1067–1084)：估計參數下的 predictive-ability inference。
- Clark & West (2007, *Journal of Econometrics* 138, 291–311)：巢狀 **MSPE** adjustment；不能改名套到 QLIKE / FZ0。
- Giacomini & White (2006, *Econometrica* 74, 1545–1578)：fixed-window、general-loss conditional predictive ability。
- McCracken (2007, *Journal of Econometrics* 140, 719–752)：recursive nested forecast tests 的非標準分配。
- Corradi & Swanson (2007, *International Economic Review* 48, 67–109)：recursive estimation predictive inference 的 bootstrap。

## 8. 資料 provenance

| 來源 | 內容 | Snapshot |
|---|---|---|
| TAIFEX 全合約 TX tick（`~/Dropbox/TAIFEXDATA/`，2,192 檔） | 每日 active contract 連續 path → aligned RV | `data/tx_rv_aligned_1330_active_contract_2017_2025.csv`（本次建構並 pin） |
| K854/K1684 TX1 RV（bridge 用） | trade-date convention 分段 RV | `data/tx1_rv_tradedate_convention_2017_2025.csv`（k1684 snapshot 複本） |
| yfinance `0050.TW`（`auto_adjust=True`） | 調整後收盤 | `data/tw0050_adjclose_2016_2025.csv`（k1684 snapshot 複本） |
| 視窗邊界 audit | 60 天段落時間戳檢查 | `data/rv_boundary_audit.json` |

## 9. 復現

```bash
uv run --extra dev python experiments/k1698/k1698.py
```

Snapshot 已 pin：本次 cache-hit 重跑 **57.3 秒**；首次建 RV 約再 +1 分鐘。Seed = `20260712`。
Lookahead audit（30 assertions）或 RV boundary audit 失敗時腳本 `raise`，不輸出結果。

**圖**：`fig1_implied_scale_bootstrap.png`（c_emp 通道診斷 + Δc 檢定）、
`fig2_trinity_before_after.png`（兩 α trinity 對照）、`fig3_scale_factors.png`（因子 + placebo）。
