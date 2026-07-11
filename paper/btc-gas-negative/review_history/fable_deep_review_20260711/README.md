# Fable 深度審查 — btc-gas-negative（2026-07-11）

- **Reviewer**: Claude Fable 5（資深學術審查，user-assigned P0）
- **審查時間**: 2026-07-11 22:38 台灣時間
- **Scope**: `drafts/body_v1.md`（audit-fix 後現行版）、`drafts/v0_outline_abstract.md`、`README.md`、`data_sources.md`、`experiments.md`、`review_history/v1/`（R0 三份）、`review_history/audit_2026-06-10/`、`experiments/{K1129,k1133,k1133b}/`（含 **2026-06-29 新落地的 `k1133b_robustness_results.json`**）、`storage/ops/dm_hac_lag_baseline.json`、`storage/memory/knowledge.json`（grep）、git history
- **驗證方式**: 所有引用數字直讀 JSON / git，非轉抄舊 review

> **主題澄清（重要）**: 本論文的「GAS」是 **Generalized Autoregressive Score**（Creal-Koopman-Lucas 2013 score-driven 波動率模型），**不是** blockchain gas fee。派工 brief 中「BTC gas fee 與負報酬關聯」的描述是誤讀 — 本文不存在任何 gas fee 分析。「negative」指 negative-result methodology paper（GAS-t 在 BTC 上反轉輸給 GJR-Normal 的負面結果）。

---

## 1. 執行摘要

**Verdict：3.5 / 5 — 值得建成論文（conditional Go）**，但中心宣稱必須重新框架，目標期刊改為 IJF 為主。

三句話：
1. **實證核心乾淨且已通過兩輪誠實清洗** — Period 1 五模型 factorial 全部 headline 數字（-4.67 / -3.36 / +2.67 / +5.97 / +0.28）本次直讀 `k1133b_results.json` 逐一吻合；R0 抓出的捏造 §8 與 K1129 誤歸屬在 6-10/11 修正輪已大體修復。
2. **但 2026-06-29 已落地的 robustness battery（paper 文件至今未更新）顯示：核心 attribution「Student-t innovation 是元兇」是 QLIKE-specific** — 在 MSE 與 Patton b=-1 下創新對比翻成 NS/反向，標題與摘要的「Is the Culprit」絕對化措辭無法存活誠實審查；GAS-t 的 deficit 本身則跨 loss / boundary / jackknife 全數 robust。
3. **三個新發現的誠實問題必須先修**：§5 倖存一句被實際數據打臉的捏造宣稱（tight basin <1.5%）、pre-registration 日期 git 驗證失敗、M3 重建值與 archive 不合（DM -4.03 vs -4.67）。

---

## 2. 現況盤點

### 2.1 Draft 資產

| 檔案 | 狀態 |
|---|---|
| `drafts/body_v1.md`（459 行，~12k 字，9 節全） | audit-fix 後版本；§8 已改寫為 implemented vs planned 二分 |
| `drafts/v0_outline_abstract.md` + 5 個 section drafts | 完整；**outline 檔與 body 內嵌 outline 已 drift**（見 4.3） |
| `review_history/v1/`（R0 opus FAIL + latex MAJOR_REV + citation PASS） | 完整、品質極高 |
| `review_history/audit_2026-06-10/`（16 findings + fix_log） | 6/6 HIGH 宣稱已修 — 本次驗證 5.5/6 屬實（殘 §5 L361） |
| `.tex` / `reproduce.py` / snapshot CSV / `data/` | **全部不存在**（README 宣稱的 `data/btc/btc_daily.parquet` 也不存在） |
| `experiments/k1133b/k1133b_robustness_results.json` | **2026-06-29 已落地**（runtime 2,655s），**paper 所有文件仍寫「planned、not yet run」— 狀態 stale** |

### 2.2 MAJOR_REV findings 有效性（本次逐項覆核）

R0（2026-06-07 FAIL）+ audit（2026-06-10 MAJOR_REVISION）的 findings **全部真實有效**，且大部分已修：

- ✅ 已修：§8/附錄捏造數字全數移除、K1129 誤歸屬重 frame（K1133/K1133b 為 -4.67 來源；K1129 降為 2021+ cross-asset anomaly 動機）、ν>30 改真實範圍 7.1–15.5、Period 3 日期改 2026-01-05→2026-04-14、§3.4 如實描述 hybrid Gray/Klaassen、MS 方向改 parity 口徑、HLZ threshold 統一（5% 主檢定 + |t|>3 robustness tier）、76/24 attribution、state duration 降為 day-scale、kurtosis 降為定性 + 明記無 artifact。
- ❌ **未修（audit 已列）**：MCS / multiple-testing（~15 個 DM 檢定無 joint inference）、per-period kurtosis 數字未落 JSON、citation cleanup（L328「Diebold-Mariano-Harvey-Lin-Newey」錯誤展開仍在；缺 Gray 1996 / Hamilton 1989 / Blasques 系列 bib；§6 Hansen-Lunde-Nason 2003 skepticism 誤歸屬）。
- ❌ **漏網（本次新抓，見 §4）**：§5 L361 捏造宣稱倖存、pre-registration git 驗證失敗、robustness 結果與 §5 現行敘述矛盾。

### 2.3 DM/HAC lag 凍結 backlog 影響：**無**

`storage/ops/dm_hac_lag_baseline.json`（133 sites，K1655 class sweep 2026-07-11 凍結）中 **K1129 / k1133 / k1133b 均不在列**。實作驗證：`k1133b.py:427-438` 的 `dm_hln_test` 用 `max_lag = floor(n^(1/3))` + Bartlett 權重（n=1441 → lag 11），非退化 `h-1` class；與 repo canonical `ceil(h^(1/3)·n^(1/3))`（=12）僅差 floor/ceil，非實質暴露。headline DM 統計量不受 class sweep 波及。

### 2.4 Crypto 資料 real-time availability：低風險

BTC-USD 日收盤價無 vintage 修訂問題（價格非修訂型總經序列；K1655 規則不適用）。殘餘風險僅 (a) yfinance 歷史 bar 偶發回溯修正（K903/K904 教訓 — snapshot pin 就是為此，但 snapshot 尚未落地）、(b) 24/7 交易下「日收盤」= UTC 午夜切點的定義應在 §3.1 明示（現行未寫，P1 補一句）。

---

## 3. 學術深度檢視

### 3.1 經濟故事站得住嗎？

**站得住，但要降一級措辭。** 機制敘事（§7）：pre-institutional BTC 的極端報酬常無波動率前兆（交易所出事、單一司法管轄區監管、鏈上清算連鎖），Student-t score 的 tail-discounting 把這些「真訊息」當離群值折減 → 系統性低估後續變異數；GJR 的槓桿項按符號機械放大，反而接住。這是可辯護的 microstructure 故事，且與 factorial 證據方向一致。

**但 6-29 robustness 揭示兩個必須內化的複雜化**（數字直讀 `k1133b_robustness_results.json`）：
1. **Loss-function specificity**：M4 GAS-N vs M3 GAS-t 創新對比 — QLIKE(b=-2) t=+2.97 顯著；**MSE(b=0) t=-1.01 NS 且 M4 平均 MSE 83,754 vs M3 4,364（爆炸 19 倍）；Patton(b=-1) t=-0.32 NS**。即：Normal innovation 的「優勢」只在 QLIKE 的不對稱懲罰下成立 — GAS-N 偶發災難性高估變異數，QLIKE 對高估寬容、MSE 重懲。`robustness_flags.alt_loss_m4_vs_m3_all_positive = false`、`section8_ready_without_caveat = false`。M3-vs-M1 的 **deficit 本身**則跨三個 loss 全部 |t|>3（-4.03 / -5.14 / -6.02）— deficit robust，attribution 不 robust。
2. **GED 打破「厚尾 = 元兇」的簡化**：alt-distribution 跑出 GAS-GED vs M1 t=-1.23 NS（**有** recover to parity）、GAS-skew-t t=-5.02（更糟）、GAS-N vs GAS-GED t=-0.16（無差異）。所以元兇不是「厚尾 innovation」而是 **t/skew-t 特定的 score 減權形狀** — GED 同為厚尾卻表現如 Normal。這其實讓故事**更精確、更有趣**，但現行 §5 的敘述（「skewed-t 與 GED 都 do not recover to parity」）**對 GED 是錯的**，必須改寫。另注意 alt-dist 協定用 refit 252（非 headline 的 63），且該協定下 M4 vs M1 t=-2.57 **顯著**輸 — dynamics-parity 宣稱對 refit cadence 敏感，須揭露。

**正確的重新框架**（也是最誠實、最耐審的版本）：「GAS-t 在 pre-institutional BTC 的 deficit 是 robust 事實（跨 loss / boundary / jackknife / 部分跨 proxy，cf. K1134）；把 deficit 歸因給 Student-t innovation 的 factorial 診斷在 QLIKE 下成立、在 MSE/Patton 下不成立，因為 GAS-N 以偶發變異數暴衝為代價換取 QLIKE 優勢 — 診斷本身 loss-dependent，這正是 Patton (2011) 警告的 forecast-bias 情境的實例。」這把弱點轉成方法論貢獻。

### 3.2 資料期間夠長嗎？

夠。全樣本 2015-2026（4,121 obs）、P1 OOS n=1,441 遠超 feedback_research_rigor 的 ≥500 門檻且含 2018 空頭；LOO jackknife（2017/18/19/20 各排除一年，t = -3.64/-3.47/-4.19/-2.84 全負）確認非單一年份 artifact。弱點是 **單資產**：ETH/BNB cross-asset 因 Yahoo 歷史不夠長 fail-fast（誠實的 fail，好事），Period 2 (n=345) / 3 (n=100) 的「無 deficit」屬低 power null，JSON 自標 preliminary。

### 3.3 期刊定位

- **主目標改 IJF**（International Journal of Forecasting）：forecasting evaluation + negative result + loss-function sensitivity 完全在 scope 內（Catania et al. 2019 crypto forecasting 就是 IJF）；**JBF 建議放棄** — 本文無 banking/asset-pricing 經濟內容，掛 JBF 是 desk-reject 風險。
- 備選依序：Journal of Financial Econometrics（factorial 診斷方法論角度）、Journal of Empirical Finance、Quantitative Finance。**不建議** crypto 專門期刊（權威度不符 mission 3）。
- **Novelty 風險要先清**：MS-GARCH-on-Bitcoin 已有 prior art（Ardia, Bluteau & Rüede 2019 FRL「Regime changes in Bitcoin GARCH volatility dynamics」；Caporale & Zekokh 2019 RIBAF）— 現行 §2 完全未引，「no prior paper ... tests MS-GAS-t rescue」的 gap 陳述需在引用這些後收窄為「score-driven MS + factorial 分解」。P1 排 NotebookLM prior-art audit。

### 3.4 與其他論文的重疊

`vix-sufficiency` 以 K1129/K1134 作 robust-model compendium 支撐（不同敘事、不同結論層），K1133/K1133b factorial 為本文獨佔 — **無 cannibalization**，但投稿時兩文互引需一致。

---

## 4. 風險與致命傷

### 4.1 【致命傷級，P0】§5 L361 捏造宣稱倖存，且被實際數據直接打臉

`body_v1.md:361`：「100 random initializations converge to a tight basin with maximum-to-median log-likelihood ratio below 1.5% ... The same multi-start diagnostic is reported for all five cells」— R0 C1 / audit HIGH#1 都點名此句，但 6-10 修正輪只重寫了 §8，**這句留在 §5 沒動**。更嚴重的是 6-29 實際 multistart 數據（`multistart_dispersion.aggregate`）顯示相反事實：全部 5 模型 `share_windows_max_minus_best_le_0.5 = 0.0`；**M4 的 median-start 離 best 35.5 個 LL 單位、單窗最大離散 3,140 萬** — M4 恰恰是 basin 最不穩的 cell（不過 median_minus_best：M1/M2/M3/M5 ≈1e-8、M4=35.5，表示 100 starts 下 best basin 仍可靠找到，「100-start 必要性」的辯護成立，「tight basin」的說法不成立）。此句不改，任何 referee 對照 replication package 即死。

### 4.2 【致命傷級，P0】Pre-registration 宣稱 git 驗證失敗

論文多處（§5、experiments.md §Methodological pre-registration、data_sources.md）宣稱 k1133 period split「committed **2026-04-12**, before any factorial run」、K1133b methodology note「v1.0 dated **2026-04-15** ... before running estimation」。**git 事實**（含 `--all`）：`experiments/k1133/` 最早 commit = **2026-04-17 23:38**（b05e47458），k1133b = 2026-04-18；k1133b results `created_at` = 2026-04-17 17:04 UTC。README 與 factorial 實質同日落地，2026-04-12 不存在於任何可驗證歷史（worktree 內部 commit 已不可考）。§5 用 pre-registration 反 data-mining critique 是 load-bearing 論證（R0 也預警「if the commit dates check out」）— **必須降級**為「the factorial contrasts follow mechanically from the 2×2 design, limiting specification-search freedom」之類的結構性論證，刪除不可驗證的日期宣稱。研究誠實 § 下這不可協商。

### 4.3 【高風險，P0】M3 重建發散 → reproduce gate 設計問題

robustness 的 `baseline_vs_original_results_json`：M1/M2/M4/M5 重建 delta=0.0，**M3 GAS-t 重建 QLIKE 2.2076 vs archive 2.1904（Δ0.017）、DM -4.03 vs -4.67（Δ0.64）**。方向與顯著性不變，但 exact-match reproduce gate（match_rate ≥95%）對 M3 會 fail。根因即 GAS-t 非凸面 + 重建腳本 RNG stream 差異。**解法**：reproduce.py 採兩層設計 — 快速層從 **persist 的 forecast 序列**重算 loss/DM（bit-exact 可達成；目前 forecast 序列未存檔，需先落地）、慢速層 full re-estimation 標 tolerance；並在論文 §8 誠實揭露 M3 重建變異幅度（-4.0 ~ -4.7 全都遠過 |3| bar，揭露成本低）。

### 4.4 【高風險，P0】標題 / 摘要與 robustness 證據不相容

標題「Student-t Innovation, Not Score-Driven Dynamics, **Is the Culprit**」+ 摘要「isolating Student-t innovation as **the proximate cause**」在 `alt_loss_m4_vs_m3_all_positive=false` 面前過強。K1133b README（6-29）已自承：「The stronger claim that the Normal-vs-Student-t decomposition is uniformly robust across losses, optimizers, and ETH/BNB does **not** pass」。建議標題方向：*"The QLIKE-Specific Anatomy of a GAS-t Failure on Pre-Institutional Bitcoin"* 或保留原架構但把副標改為診斷的條件性。同時 body 內嵌 abstract（L21，仍寫「FTX-Luna (2021-2023) and spot-ETF (2024+)」）與已修正的 `v0_outline_abstract.md`（「post-FTX recovery (OOS 2023)」）drift — 收斂為單一來源。

### 4.5 【中風險，P1】其餘未結項

- MCS / multiple-testing 未做（audit MEDIUM；IJF referee 必問）。
- per-period kurtosis 未落 JSON（§7.1 現為定性，可接受但弱）。
- Citation：L328 錯誤展開、缺 6 條 bib、Hansen 2003 誤歸屬、**缺 Ardia et al. 2019 / Caporale & Zekokh 2019 prior art**（§3.3）。
- Compliance（2026-07-01 audit 已列）：「Codex」以審查者身分出現在方法論正文（L310, 426 等）、「hourly-08 fire / Next Sub-Tasks / P4 paper_body」平台 metadata 在 header/尾段 — 投稿前全 scrub。
- knowledge.json 的 K1133 條目仍寫「K1129 DM t=-4.58 **decomposes into** P1 2017-2020」— K1129 無 2017-2020 OOS，此為已知誤歸屬的殘留，需主線程修 knowledge 條目。
- paper 文件三處（README「planned robustness package」、experiments.md §8 列、§8 prose「not yet run」）與 6-29 已落地的 robustness JSON 狀態脫節。

---

## 5. 接下來的研究計畫（Go 路線）

### P0 — 誠實修正 + 可復現底盤（阻擋 .tex 的全部項；估 3-4 個工作天）

| # | 任務 | 內容 | 估時 |
|---|---|---|---|
| P0-1 | **§5/§8/abstract/標題對 robustness JSON 重寫**（主線程，markdown） | 刪 L361 捏造句改引真實 multistart aggregate；§8 從「planned」改為引用 6-29 真數字的 mixed battery（boundary PASS、LOO PASS、alt-loss deficit-robust/attribution-not、GED/skew-t 真值、ETH/BNB fail-fast 如實）；GED 敘述修正；揭露 alt-dist refit-252 協定差異與 M4 該協定下 -2.57；標題/摘要降級為 QLIKE-conditional attribution；收斂雙份 abstract | 1 天 |
| P0-2 | **snapshot CSV + forecast 序列 persist + reproduce.py** | 落地 2026-04-15 pinned CSV；改 k1133b pipeline 存 per-model OOS forecast 序列；reproduce.py 兩層 gate（archived-forecast 快速層 bit-exact + re-estimation 慢速層 tolerance）；§8 揭露 M3 重建變異 | 1.5-2 天 |
| P0-3 | **pre-registration 宣稱降級** | 刪 2026-04-12/04-15 日期宣稱，改結構性論證；experiments.md / data_sources.md 同步 | 0.5 天 |

### P1 — R1 前補強（估 2-3 個工作天 + 計算）

1. **MCS**（Hansen-Lunde-Nason，6 模型 × 3 期，α=0.10/0.25）落 JSON + §3.6 multiple-testing 說明（primary contrasts pre-specified、其餘 descriptive）。計算量小（loss 序列已有）。
2. per-period excess kurtosis 落 JSON、§3.1 補 UTC 收盤定義、Period 2 warm-up 揭露（Luna/FTX 崩盤不在 OOS）。
3. Citation cleanup 全套 + **Ardia 2019 / Caporale & Zekokh 2019 prior art 引用與 gap 陳述收窄** + NotebookLM prior-art audit（確認「previously unreported」站得住）。
4. Compliance scrub（Codex 名稱 → 「an independent code review」；刪平台 metadata / Next Sub-Tasks 段）。
5. knowledge.json K1133 條目誤歸屬修正（主線程）。
6. （可選但高價值）**ETH 原生窗 factorial**：ETH-USD 2017-11 起至 2020-12-31，OOS ~2.3 年 — 用 ETH 自己的 pre-institutional 窗而非硬對齊 BTC P1，一舉補掉單資產致命傷。計算 ~1 小時級（對照 robustness 全套 2,655s）。
7. 用 canonical `volpred.stats.model_evaluation.dm_test`（`ceil(h^(1/3)·n^(1/3))`）重算一份 DM 對照表附錄，消除 floor/ceil 差異的任何質疑（數字預期不動，成本極低）。

### P2 — 轉換與投稿（估 3-5 個工作天）

1. Markdown → **IJF（Elsevier）LaTeX**（非 JBF template），每 Table row 掛 `% source:` binding；xelatex 過。
2. `paper-review-cycle` R1（latex-academic-reviewer + citation-verifier）→ 收斂 → `journal-review`（IJF profile）→ compliance gate。
3. `paper-update` CLI 同步 + pipeline stage 推進。

**合計 ~8-12 個工作天**（平台 hourly cadence 下約 2-3 週 calendar）。P0 全部完成前**維持禁轉 .tex**（延續 R0/audit gate）。

### 若改判 No-Go 的資產化方案（備案，不建議）

factorial 診斷 + loss-specificity 故事轉 2-3 篇 feed 文章（「換個 loss，結論就反過來」是絕佳一般讀者素材）；K1133b 併入 vix-sufficiency 的 robust-model compendium 敘事作 BTC 深掘一節。但實證核心已乾淨、robustness 已跑完、離 R1 只差誠實重寫 — 棄置的邊際浪費大於完成成本。

---

## 6. Go/No-Go 建議

**Go（conditional）**。條件 = P0 三項全落地 + 標題/摘要降級為 QLIKE-conditional attribution + 目標期刊改 IJF。

裁決依據：(a) 實證核心逐數驗證乾淨、方法論設計（factorial + placebo + MS rescue）在 crypto 波動率文獻確有空缺；(b) 兩輪審查 + audit 的清洗把最危險的捏造大體移除，剩餘問題全部可在 ~2 週內修完；(c) loss-specificity 不是致命傷而是可轉化的方法論貢獻 — 前提是論文擁抱它而非掩蓋它；(d) 反面因素（單資產、P2/P3 低 power、pre-reg 驗證失敗）把上限壓在 3.5/5：這是一篇「扎實的 IJF 投稿候選」，不是 JFE/RFS 級別。

*審查完成：2026-07-11 22:41 台灣時間。所有數字來源：`k1133b_results.json`、`k1133b_robustness_results.json`、`k1129_results.json`（間接）、git log、`dm_hac_lag_baseline.json`。無未標註的未驗證引用。*
