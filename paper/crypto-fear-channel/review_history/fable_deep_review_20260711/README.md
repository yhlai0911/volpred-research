# Fable 深度審查 — crypto-fear-channel（Paper 10）

- **審查者**: Fable 5（主線程指派之資深學術審查 agent，user-assigned P0）
- **日期**: 2026-07-11（台灣時間 22:31–22:50）
- **審查對象**: `paper/crypto-fear-channel/main.tex`（canonical active manuscript，2026-07-01 最後修改；任務 brief 所稱 body_v5.tex 為 2026-04-28 舊版殘檔，main.tex 即由其改名而來，非殼檔）
- **對照數據源**: `experiments/k1025/k1025_v2_results.json` + `experiments/k1025/k1025_v2.py`

---

## 1. 執行摘要

**Verdict: 2 / 5 — 現狀不可投稿（No-Go），但骨架可救（Go for salvage）。**

三句話：

1. **本次審查發現一個先前 7 輪審查（v1–v5 + Codex 獨立審查 + 2026-06-10 audit）全部漏掉的致命 bug**：`k1025_v2.py` 把 statsmodels `FEVD.decomp`（實際 shape `(neqs, periods, neqs)`）誤當 `(horizon, n_vars, n_vars)` 切片，整個 Diebold-Yilmaz 段落（total spillover 90.11%、BTC net receiver −74.4pp、§6.1 全文唯一 robustness 節）是切錯陣列的數學近恆等式 — **在純 iid 雜訊上同一公式也算出 90.00%**。
2. 2026-05-21 撤回 ready 的 3 個 BLOCKING（QR lag+bootstrap、subperiod AIC、OOS 切分）已在 v2 code 真修（本次逐行驗證），manuscript 文字也已誠實化；但 README 列的三項重跑前置（data pinning、FEVD ordering、K1025b）全部未動，且 `storage/next_tasks.json` 中**沒有任何**對應 pending task — 論文已閒置一個月。
3. 修正後重算（pinned snapshot、N=2812、512 windows 與論文完全一致）顯示：真實 total spillover ≈ 18–22%、時變 8 倍幅度、COVID 見峰值；**BTC net receiver 結論隨 Cholesky 排序翻號**（+6.1pp vs −6.4pp）——「fear amplifier not originator」這個 headline 敘事目前無證據支撐，須以 generalized FEVD 重建。

---

## 2. 現況盤點 — 撤回理由與解決狀態

### 撤回時間線

| 日期 | 事件 | 依據 |
|---|---|---|
| 2026-04-28 | v4.1 PROMOTED → `ready_for_submission`（6/6 gate PASS，自估「94–95% 接受率」） | commit 5a5e6939f；research_program.md P10 |
| 2026-05-21 | **Codex(GPT-5.4) 獨立審查 REJECT**（3 BLOCKING + 5 MAJOR + 3 MINOR）→ 降回 working | `review_history/v5_independent/codex_review.md`；commit bc2e9a1a6 |
| 2026-05-22 | k1025_v2 重跑完成，main.tex ~30 處數字更新 | commits 2a6c7d010 / 49c193d92 |
| 2026-06-10/11 | audit 抓 7 HIGH + 6 MEDIUM + 1 LOW（v1/v2 vintage 混用、HAC 不實宣稱等），4 HIGH 文字修復，狀態定為 MAJOR REVISION | `review_history/audit_2026-06-10/` |

### v5 撤回的 3 個 BLOCKING — 全部已真修（本次逐行驗證 code）

| BLOCKING | 修復狀態 | 驗證位置 |
|---|---|---|
| 1. QR 同日無 lag 無 bootstrap | ✅ 已修：`BTC_RV_lag1 = btc_rv20.shift(1)` + 1,000 次 bootstrap（seed 42） | `k1025_v2.py:288-315` |
| 2. subperiod lag mining（挑最小 p） | ✅ 已修：AIC 選 lag（`best_lag_aic`）+ Bonferroni 欄位 | `k1025_v2.py:734-763` |
| 3. OOS expanding + 2019-01-01 雙落 IS/OOS | ✅ 已修：IS 止 2018-12-31、OOS 起 2019-01-01、rolling 756、AIC AR(p) | `k1025_v2.py:557-616` |

### README 三項重跑前置 — 全部 OPEN

| 項目 | 狀態 |
|---|---|
| Data pinning（snapshot + auto_adjust=False 重跑） | ❌ OPEN。snapshot CSV 存在且完整（4,192 列，SPY/VIX/BTC 到 2026-07；weekday 缺值均為美股假日），但 headline 數字仍出自 live yfinance `auto_adjust=True` |
| FEVD ordering robustness | ❌ OPEN — **且被本次發現升級為致命**：問題不是排序敏感度，是 FEVD 矩陣本身切錯 |
| K1025b symmetric rerun | ❌ OPEN（已從正文移除、降為 deferred，處置正確） |

**佇列缺口**：`storage/next_tasks.json` 無任何 crypto-fear / k1025 相關 pending task — 三項前置無人認領。

### K1655 vintage 規則檢查

本論文**未使用** Crypto Fear & Greed Index（全文 grep 確認）；「fear」= VIX（市場即時報價指數，無回溯修訂、無首次發布日問題）。K1655 類 real-time vintage 風險**不適用**。但 live-pull `auto_adjust=True` 違反 repo data-pinning 硬規則（paper-workflow rule 1），manuscript §3.1 已如實揭露並自我降級為 major-revision draft — 誠實處置正確，重跑仍未做。

---

## 3. 學術深度檢視

### 3.1 致命發現：DY spillover 全段為 array mis-slicing artifact（NEW，先前 7 輪未抓到）

**Bug 機制**（`k1025_v2.py:362-382`）：

```python
decomp = fevd.decomp  # 註解宣稱 shape: (horizon, n_vars, n_vars) ← 錯
spillover_matrix = decomp[-1]  # 以為取「最後 horizon 的 3×3 矩陣」
```

statsmodels（0.14.6 實測）`FEVD.decomp` 實際 shape 是 **`(neqs, periods, neqs)`**（equation × lag × component；源碼註解「switch to equation x lag x component」）。`decomp[-1]` 取到的是**最後一條方程（VIX）在 10 個 horizon 的分解**，一個 10×3 矩陣。後續 `n = shape[0] = 10`（誤把 horizon 數當變數數）、`np.trace` 只加 3 個語義錯亂的格子，於是：

> total spillover = (10 − trace)/10 × 100 ≈ **90%，對任何資料都近似成立**。

**Smoking gun（合成資料檢定，本目錄 `dy_corrected_diagnostic.py` 邏輯同源）**：對純 iid 雜訊（真實 spillover ≈ 0）跑同一公式 → total = **90.00%**、net_btc = −96.1。論文的 90.11% ± 0.22 與 −74.4pp 是數學恆等式加雜訊，不是實證結果。這同時解釋了 §6.1 引以為傲的「remarkable stability」（std 0.22pp）— 那是恆等式的穩定，不是市場的穩定。

**修正後重算**（用 paper-local pinned snapshot，樣本 N=2,812、2015-02-02→2026-04-08、512 個 rolling windows，**與論文完全一致**；正確切片 `decomp[:, -1, :]`）：

| 量 | 已發表（buggy） | 修正後 {BTC,SPY,VIX}（code 實際排序） | 修正後 {VIX,SPY,BTC}（論文宣稱排序） |
|---|---|---|---|
| total spillover mean | 90.11% | **18.34%** | **22.42%** |
| total std | 0.22pp | 8.01pp | 8.34pp |
| total min–max | 89.73–90.84 | 4.86–40.54 | 6.37–47.51 |
| total 峰值日期 | —（無變化） | 2021-03-04 | **2020-03-13（COVID）** |
| BTC net spillover mean | −74.4pp | **+6.06pp（net sender）** | **−6.44pp（net receiver）** |
| BTC 為 net receiver 的窗口占比 | 「every window」 | 45% | 81% |

**波及的正文宣稱**（全部失效）：abstract「net receiver」句、intro Regime-dependence 段、§5.3 末段（90.1% / 23.7% / −74.4）、**§6.1 整節**（全文唯一 active robustness）、conclusion「mean net spillover −74.4pp」、「BTC remains a net receiver in every window」（修正後兩種排序下分別只有 45% / 81%）、「crypto as fear amplifier, not fear originator」reframing 本身。

**諷刺的正面訊息**：修正後的指數**在 COVID 飆升 4–8 倍**，與 subperiod Granger 的 2020 集中互相印證 — 正確的 DY 結果其實讓 regime-dependence 故事**更一致**，而 buggy 版本的「connectedness 恆定」反而與 DY 文獻的招牌特徵（危機期 connectedness 飆升；Diebold-Yilmaz 2009/2012 的核心 stylized fact）矛盾，本來就該被任何熟悉該文獻的 referee 一眼識破。

**Bug class 全量掃描**（per `feedback_declare_complete_requires_class_sweep`）：repo 內 7 個檔案呼叫 `results.fevd(`：

| 檔案 | 切片 | 判定 |
|---|---|---|
| `experiments/k1025/k1025.py:341` | `decomp[-1]` | ❌ BUGGY |
| `experiments/k1025/k1025_v2.py:362` | `decomp[-1]` | ❌ BUGGY（本論文數據源） |
| `experiments/k1025b/k1025b.py:351` | `decomp[-1]` | ❌ BUGGY（繼承） |
| `experiments/k865/k865_vol_spillover_network.py:116` | `decomp[-1]` | ❌ **BUGGY — 本論文之外的另一實驗，下游影響（knowledge/feed）待查** |
| `experiments/k834/k834_iv_connectedness.py:131-134` | `decomp[i, -1, j]` | ✅ 正確 |
| `experiments/k628b/k628b_vol_spillover.py:299-303` | `decomp[i][-1]` | ✅ 正確 |
| `experiments/k304/k304_causal_inference.py:1041-1042` | `decomp[1][h-1, j]` | ✅ 正確 |

### 3.2 Contribution 評估（假設 P0 修復完成後）

- **定位**：reduced-form 的「誠實聯合報告」（in-sample 非對稱 + tail QR + regime + OOS null）。對 JIMFIM/JEF/IRFA 級別是合格的 empirical contribution；對 JBF/JFE 級別不足（無結構識別、無新方法、無新資料）。
- **最有賣點的 finding** 是 QR sign reversal（低分位 β 顯著為負 → 中位翻正 → τ=0.95 放大 7×），但它有一個 referee 必問的識別弱點（見 3.3-2）。
- **「fear amplifier」reframing** 在 DY 修復前是空中樓閣；修復後能否重建取決於 generalized FEVD 的 net 方向（Cholesky 下已知翻號）。
- **機制**（retail / margin cascade）誠實標註為 untested — 正確，但也意味 mechanism 貢獻為零，僅剩 characterization。
- **文獻缺口（審查者將點名）**：(a) realized semivariance 文獻完全缺席 — 本文的 directional RV 本質是 20 日 rolling semivolatility，Barndorff-Nielsen–Kinnebrock–Shephard (2010)、Patton & Sheppard (2015)「good vol, bad vol」是不可迴避的先行者，且提供更標準的構造；(b) quantile-causality 文獻（Troster 2018；Bouri et al. 系列把 quantile causality 用在 crypto）— 直接關聯 §4.3 的方法選擇。

### 3.3 方法論與統計嚴謹度

已驗證為妥當的部分：QR lag + seed 固定 bootstrap ✓、OOS 切分乾淨（rolling 756、one-step-ahead、無重疊）✓、主 DM 檢定 Bartlett-kernel HAC（lag = ⌊T^{1/3}⌋ = 12，接近 repo canonical ⌈·⌉ = 13，非 h−1 退化類）+ Harvey-Newbold 小樣本修正 ✓、subperiod Bonferroni ✓、QLIKE 方向為 actual-over-predicted 變體（`log(f²)+a²/f²`，`k1025_v2.py:632`）✓ 不違反 repo QLIKE 硬規則。

**Referee 級別的殘留弱點**：

1. **Granger F 檢定無 HAC**（`ssr_ftest` plain OLS F）。manuscript 已如實描述（§4.1「plain lag-augmentation diagnostics」），但誠實揭露 ≠ 方法充分：以高度持續的 20 日 rolling RV 為解釋變數，殘差自相關僅靠 lag augmentation 吸收，對 F 統計量在 10⁻⁶ 級的 p 值宣稱是脆弱基礎。至少需要 wild/HAC-robust Wald 或報告 robustness。
2. **QR 沒有 lagged VIX 控制**（`k1025_v2.py:289-294`：`VIX_t ~ const + BTC_RV_{t-1}`，僅此而已）。對照 Granger 檢定都控制 VIX 自身 lags，QR 估的是**非條件分位關聯**而非增量預測內容。低分位負係數極可能是樣本組成效應（2017/2021 牛市 = 高 BTC RV + 低 VIX），「BTC volatility dampens equity fear in calm markets」的因果語氣站不住。**referee 會要求加 VIX_{t-1} 控制（quantile-Granger 規格），headline 7× 放大與 sign reversal 有實質風險縮水或消失** — 這是 P0 必做的存活測試。
3. **QR bootstrap 是 iid pairs resampling**（`k1025_v2.py:308`）— 對自相關 ~0.97 的 VIX 序列，iid 重抽會低估 SE（t = 8.17 之類的數字被灌水）。需 moving-block bootstrap。
4. **Subsample DM 無 HAC**（`k1025_v2.py:709`：`mean/(std/√n)` naive SE），與主 DM（有 HAC）口徑不一。Normal 子樣本 t = −1.96 恰在邊界，per K1655 教訓 HAC 修正方向不可預設 —「neither subsample rejects」的措辭（§7）在 p≈0.05 下本就勉強。
5. **AR order 撞到 grid 上界**（AIC 在 1..10 中選 p=10，`k1025_v2.py:563-566`）— grid 應延伸（如 22）確認非截斷選擇。

### 3.4 內部一致性（本次新抓，audit 之外）

| # | 位置 | 問題 |
|---|---|---|
| 1 | §5.3 (main.tex:282) vs §6.1 (main.tex:296) | 同一個 23.7%：§5.3 說是「from BTC **to** the system」、§6.1 說是「BTC's **from-system**（received）」— 兩句直接矛盾（buggy 語義下兩者皆非；修正後兩量分別是 ~12 與 ~6） |
| 2 | §2.2 (main.tex:73) + §4.4 (main.tex:161) vs `k1025_v2.py:395-399` | 論文宣稱 Cholesky 排序 {VIX, RV_spy, RV_btc}，code 實際 {BTC_RV, SPY_RV, VIX} — 恰好相反；Cholesky 下排序即識別假設 |
| 3 | §7 (main.tex:305) vs §2.2 (main.tex:75) | §2.2 明言「不把 factor-discovery 門檻移植進 forecast-comparison inference」，§7 又寫「well below the \citet{harvey2016} |t|>3 threshold」— 自我矛盾；audit MEDIUM 只修了一半 |
| 4 | §7 (main.tex:326) vs Table 5 (main.tex:271-274) | 「Crisis subsample」= VIX>25 vs Table 5 Crisis = VIX>35，同詞異義且無 footnote 說明（audit 已點名，未修） |
| 5 | Table 1 (main.tex:107) | SPY 列 mean 0.060 / std 1.120，JSON 實值 0.0564 / 1.1169 — 印出精度下不符（reproduce gate 32 檢查不含這兩格；v1 殘值嫌疑） |
| 6 | abstract/§4.3/§5.2 | 「realized **variance**」與 §3.2 定義的 RV = rolling **std**（volatility）混用 — 量綱敘述錯誤 |

### 3.5 Reproduce gate 的結構性盲區（process 教訓）

`reproduce_report.json` 32/32 green 完全屬實 — 但 gate 驗的是 **tex ↔ JSON 轉錄一致性**，JSON 本身由 buggy code 產出，於是「DY: BTC net spillover −74.41 ✓ match」是對一個無意義量的完美轉錄。7 輪審查全數失手同理：v5 Codex 查的是「tex 宣稱 vs code 宣稱」（抓到 generalized-FEVD 不實），audit 查的是「tex 數字 vs JSON vintage」（抓到 v1/v2 混用），**沒有任何一層做「code 是否算出它自稱的量」的語義重推導**。K1259 的 audit 硬規則（re-walk full population + blind-spot 分析）應擴充一條：paper 級 gate 對每類統計量至少做一次 independent re-derivation 或 synthetic-data sanity check（iid 雜訊上 spillover 應 ≈ 0 這種一行測試就能攔住本案）。

---

## 4. 風險與致命傷

1. **［致命］DY 段落整體失效**（§3.1）— 不修不能投稿；修了 headline 敘事可能改寫（net 方向排序相依）。
2. **［高］QR sign-reversal 支柱未過 lagged-VIX 存活測試** — 若加控制後消失，論文剩 asymmetric Granger + OOS null，貢獻縮水到 FRL 短文級。
3. **［高］二次 premature promotion 前科**（4/28 ready + 「94–95% 接受率」自估 → 5/21 REJECT；6/8 標 ready 的紀錄 → 6/10 audit 降級）。第三次 promotion 若再翻車，平台學術信譽線受損。任何 ready 標記前必須過「語義重推導」層審查。
4. **［中］k865 同 bug 未處置** — 本論文之外的 spillover network 實驗數字同樣失真，若曾餵 knowledge.json 或 feed 文章需回溯更正（研究誠實原則第 6 條）。
5. **［中］資料規格 mongrel**（SPY simple return vs BTC log return、auto_adjust=True live pull）— 已揭露但 referee 會要求統一；pinning 重跑時一併解決，數字會小幅漂移、全表重生成。
6. **［低］佇列真空** — 修復項不在 next_tasks，靠人記憶 = 必然再閒置。

---

## 5. 接下來的研究計畫

### P0 — 決定論文生死（先做，估 1–2 個 compute job + 主線程改寫）

1. **K1025_v3 重跑（單一 job 打包）**：
   - 修 `compute_spillover_index`：正確切片 `decomp[:, -1, :]`；以 **KPPS generalized FEVD**（order-invariant）為主結果，附兩種 Cholesky 排序當 sensitivity（本目錄診斷腳本可直接改造）；
   - 改讀 pinned snapshot（`data/spy_btc_usd_vix_2015-2026.csv`，本次已驗證完整），依 repo 規則用 `auto_adjust=False` 欄位並統一 SPY/BTC return 定義（雙雙 log），全部數字重生成；
   - **QR 加 lagged-VIX 控制**（quantile-Granger 規格）+ moving-block bootstrap — sign-reversal 存活測試；
   - subsample DM 補 HAC；AR grid 延到 22。
2. **DY 敘事重寫**（主線程，等 v3 JSON）：abstract / intro / §5.3 / §6.1 / conclusion 全面改寫；「net receiver」降級為 ordering-sensitive 或改用 generalized FEVD 的方向結論；§6.1 改寫成「connectedness 危機期飆升、與 subperiod Granger 2020 集中互證」（修正後這是更強的故事）。
3. **Platform bug-class 收口**：修 k865（+ 追其下游 knowledge/feed 引用，錯了就回溯更正）；加機械 gate — synthetic iid FEVD 單元測試（index ≈ 0 才 PASS）進 `scripts/tests/`，比照 dm_hac_lag ratchet 模式；k1025/k1025b 舊 JSON 標 superseded。
4. **把上述三項寫進 `storage/next_tasks.json`**（P1 priority），終結佇列真空。

### P1 — resubmission 前

5. K1025b（QQQ/VXN）以 v3 同 spec 重跑（K1216b symmetric-refinement 硬規則），恢復 §6.4 multi-asset robustness。
6. Granger 檢定補 HAC-robust Wald 或 wild bootstrap F（至少作為 robustness 欄）。
7. 文字修正批次：§3.4 表列 6 項（23.7% 方向矛盾、排序陳述、Harvey 殘句、crisis 定義、T1 SPY cells、variance/volatility 術語）。
8. 文獻補強：realized semivariance（BNKS 2010；Patton-Sheppard 2015）+ quantile causality（Troster 2018 等）兩支，並把本文 directional-RV 構造與 semivariance 的關係寫清楚。
9. reproduce.py 對 v3 rescope + 補 T1 SPY mean/std 兩檢查。

### P2 — 強化與延伸（可另立新 K）

10. 機制 proxies：BTC ETF flows（2024–）、perp funding rates、liquidation 數據 → 把「retail/margin」故事從 untested 變 partially tested（可能成為續作論文）。
11. Intraday 傳導（liquidation cascade 的自然檢驗場）— 獨立 future paper。

### 期刊目標（明確推薦）

| 順位 | 期刊 | 理由 |
|---|---|---|
| 1st | **JIMFIM** | scope 完全對口（Yarovaya et al. 2022 同刊）；接受 reduced-form 跨市場傳導 + 誠實 OOS null 的組合；修復後的 COVID-connectedness 峰值故事符合其讀者群 |
| 2nd | **JEF** | 方法論訴求（Granger ≠ forecastability 的 discipline 論點）在此更有共鳴，但對 QR 識別會更挑剔 — 需 P0-3 存活 |
| 3rd | **IRFA** | Klein (2018)、Shahzad (2019) 同刊，crypto-safe-haven 辯論的主場 |
| Backup | **FRL** | 若 QR 支柱陣亡，縮成 asymmetry + honest null 的短文 |

**不建議** JBF/JFE：無結構識別、無方法創新，投了浪費 review cycle。crypto 專刊（如 Journal of Digital Finance 類）不建議 — 學術權重低於 JIMFIM/IRFA，對平台學術信譽線幫助小。

---

## 6. Go/No-Go 建議

**No-Go（現狀投稿）— 即刻生效**：DY artifact 波及 abstract 到 conclusion 的 headline 宣稱，任何懂 DY 文獻的 referee 看到「90% 恆定 connectedness」都會起疑，一旦要求 replication package 即當場斃命且傷及作者信譽。

**Go（salvage 路徑）**：修復路徑完全明確、compute 輕量（v3 重跑 < 1 小時級）、asymmetric Granger + OOS null 兩支柱經本次逐行驗證是乾淨的。分水嶺在 P0-1 的兩個存活測試：(a) generalized FEVD 下 net 方向是否穩定、(b) QR sign reversal 加 lagged-VIX 控制後是否存活。兩者皆活 → JIMFIM 可投；QR 死 → 降 FRL 短文。**在 P0 完成並經 primary-path Codex 語義級複核前，禁止任何 ready 標記**（本論文已兩次 premature promotion）。

---

## 附錄：審查方法與盲區聲明（per experiments.md audit 硬規則）

- **掃描範圍**：main.tex 全文 502 行逐行；`k1025_v2.py` 資料建構/QR/DY/OOS/subperiod/EWMA 六段逐行；數字抽查 40 項（reproduce gate 32 項全數 + 手動 8 項：symmetric Granger lag1-2、subsample DM×2、MAE/QLIKE、RV/VIX/SPY 描述統計、DY 全欄位）；review_history 全 7 輪；repo-wide `.fevd(` class sweep（7 檔）。
- **驗證方法**：jq 對照 JSON、statsmodels 0.14.6 合成 iid 檢定（smoking gun）、pinned snapshot 全樣本重算（N=2,812 / 512 windows 與論文一致；腳本 = 本目錄 `dy_corrected_diagnostic.py`，含每序列先 dropna 的修正 — 初版在含週末 NaN 的 calendar index 上做 pct_change 曾誤刪週一）。
- **盲區**：(a) Granger/QR/OOS 的 JSON 數值未從零重跑（信任 v2 code 產出，該 code path 已逐行讀過）；(b) 引用文獻逐條 DOI 未重驗（沿用 v4 citation report）；(c) k865 下游 knowledge/feed 影響未 trace（列 P0-3）；(d) 自訂 MA-rep 的 DY 實作（不經 `results.fevd`）不在本次 grep 覆蓋內。
