# EXECUTION — crypto-fear-channel（Paper 10）

> 論文執行單。唯一權威來源：`review_history/fable_deep_review_20260711/README.md`（Fable 深審，200 行）。
> 本檔追蹤「深審 → 投稿」的可執行狀態；勾選一律以真實驗證為準（研究誠實原則）。

## BADGE

| 欄位 | 值 |
|---|---|
| stage | `revision`（`storage/paper_pipeline_status.json`；stage_entered 2026-05-22，last_touch 2026-07-01） |
| **p0** | **`TODO`**（K1025_v3 重建 + DY 敘事重寫皆未執行） |
| deep-review verdict | **2 / 5 — No-Go（現狀投稿）/ Go（salvage 路徑）** |
| journal target | **JIMFIM**（1st）→ JEF → IRFA → FRL(backup) |
| blocking bug | **FEVD 陣列誤切**（7 輪審查全漏；iid 雜訊也算出 90% spillover） |
| ready 鎖 | **禁止任何 ready 標記** — 直到 P0 完成 + Codex 語義級複核（已兩次 premature promotion） |

---

## 最終目標（North Star）

把 crypto-fear-channel 從「headline 建立在 FEVD artifact 上的不可投稿稿件」救成「以 **KPPS generalized FEVD** 重建、數字誠實可複現、可投 JIMFIM 的跨市場波動傳導實證論文」。

分水嶺在兩個存活測試：
1. **DY 方向存活** — generalized FEVD（order-invariant）下，BTC 的 net spillover 方向是否穩定（Cholesky 下已知隨排序翻號：`{VIX,SPY,BTC}` 為 net receiver −6.4pp，`{BTC,SPY,VIX}` 為 net sender +6.1pp）。
2. **QR 支柱存活** — quantile sign-reversal（低分位 β<0 → 中位翻正 → τ=0.95 放大 7×）在加入 lagged-VIX 控制（quantile-Granger 規格）+ moving-block bootstrap 後是否存活。

兩者皆活 → JIMFIM 可投；QR 陣亡 → 縮成 asymmetry + honest-null 的 FRL 短文。**核心真相**：修正後真實 total spillover ≈ **18–22%**（非已發表的 90.11% 恆等式），時變 8 倍、COVID 見峰值 — 正確結果反而讓 regime-dependence 故事**更一致**。

---

## Definition of Done（DoD — 全未達成，勿勾）

宣告論文 ready 前，以下每一項須真實驗證通過：

- [ ] K1025_v3 重跑完成：FEVD 正確切片 `decomp[:, -1, :]` + **KPPS generalized FEVD 為主結果** + 兩 Cholesky 排序為 sensitivity
- [ ] pinned snapshot 為唯一輸入（`data/spy_btc_usd_vix_2015-2026.csv`，`auto_adjust=False`，SPY/BTC return 定義統一為 log），全表數字重生成
- [ ] **iid-noise FEVD placebo 機械 gate** 通過（純雜訊輸入 → spillover index ≈ 0 才 PASS；比照 `dm_hac_lag` ratchet 進 `scripts/tests/`）
- [ ] QR sign-reversal 存活測試通過（加 `VIX_{t-1}` 控制 + moving-block bootstrap）**或**誠實降級敘事
- [ ] DY 敘事全面重寫（abstract / intro / §5.3 / §6.1 / conclusion）且與 v3 JSON 逐格一致
- [ ] subsample DM 補 HAC；AR grid 延到 22 確認非截斷選擇
- [ ] §3.4 內部一致性 6 項全修（23.7% 方向矛盾、Cholesky 排序陳述、Harvey 殘句、crisis 定義同詞異義、Table 1 SPY cells、variance/volatility 術語）
- [ ] reproduce gate 對 v3 rescope，`match_rate ≥ 95%` + `alert_level=green`
- [ ] 文獻補強：realized semivariance（BNKS 2010；Patton-Sheppard 2015）+ quantile causality（Troster 2018 等）
- [ ] **Codex 語義級複核通過**（不只 tex↔JSON 轉錄一致，須 independent re-derivation / synthetic-data sanity check）

---

## P0 — 決定論文生死（全 ⬜ TODO）

> 估：1–2 個 compute job（v3 重跑 < 1 小時級）+ 主線程敘事改寫。
> canonical queue task = `fable0711_cryptofear_k1025v3`（P1，已在 `storage/next_tasks.json`）。

- ⬜ **P0-1 — K1025_v3 重跑（單一 job 打包）**
  - 修 `experiments/k1025/k1025_v2.py:362-382` FEVD.decomp shape 誤切：statsmodels `(neqs, periods, neqs)` 被當 `(horizon, n_vars, n_vars)`，`decomp[-1]` 取到 VIX 方程的 10×3 而非最後 horizon 的 3×3 → total ≈ 90% 對任何資料近恆等成立。正確切片 `decomp[:, -1, :]`。
  - 以 **KPPS generalized FEVD**（排序不變）為 headline，附 `{VIX,SPY,BTC}`／`{BTC,SPY,VIX}` 兩 Cholesky 排序當 sensitivity（可改造 `review_history/fable_deep_review_20260711/dy_corrected_diagnostic.py`）。
  - 改讀 pinned snapshot，`auto_adjust=False`，SPY/BTC return 統一 log，全數字重生成。
  - **QR 加 lagged-VIX 控制**（quantile-Granger）+ moving-block bootstrap（iid pairs 對 acf≈0.97 的 VIX 會灌水 SE）— sign-reversal 存活測試。
  - subsample DM 補 HAC（現為 naive `mean/(std/√n)`，與主 DM 口徑不一）；AR grid 由 1..10 延到 22。
  - 固定 seed；完成後交 **primary-path Codex 語義級複核**。
- ⬜ **P0-2 — DY 敘事重寫**（主線程，等 v3 JSON 落地）
  - 全面改寫 abstract / intro / §5.3 / §6.1 / conclusion；「BTC net receiver」降級為 ordering-sensitive 或改用 generalized FEVD 的方向結論。
  - §6.1 由「remarkable stability（std 0.22pp）」改寫為「connectedness 危機期飆升、與 subperiod Granger 2020 集中互證」（修正後這是更強、且符合 Diebold-Yilmaz 招牌 stylized fact 的故事）。
- ⬜ **P0-3 — reproduce gate 對 v3 rescope + 補 Table 1 SPY mean/std 兩檢查**（現 32/32 green 是對無意義量的完美轉錄；gate 須加語義層）
- ⬜ **P0-4 — 內部一致性 6 項修正**（§3.4 表）

> **平台外溢處置（非本論文 P0，已於 2026-07-11 完成，列此僅為脈絡）**：class sweep 發現 `k865_vol_spillover_network.py` 同一 FEVD bug；其修正、下游 knowledge/feed 回溯更正、iid-noise 機械 gate 已 commit（`c1831a0f6` / `6d2fd29a3` / `716e67473`）。**本論文自身的 k1025/k1025_v2/k1025b 舊 JSON 仍待標 superseded**（併入 P0-1）。

---

## P1 — resubmission 前

- ⬜ K1025b（QQQ/VXN）以 v3 同 spec 重跑（K1216b symmetric-refinement 硬規則），恢復 §6.4 multi-asset robustness。
- ⬜ Granger 檢定補 HAC-robust Wald 或 wild bootstrap F（現為 plain OLS `ssr_ftest`，對高持續 20 日 rolling RV 的 10⁻⁶ p 值是脆弱基礎；至少作 robustness 欄）。
- ⬜ 文獻補強兩支（realized semivariance / quantile causality），並寫清 directional-RV 構造與 semivariance 的關係。

## P2 — 強化與延伸（可另立新 K）

- ⬜ 機制 proxies：BTC ETF flows（2024–）、perp funding rates、liquidation 數據 → 把「retail/margin cascade」故事從 untested 變 partially tested（可能成為續作論文）。
- ⬜ Intraday 傳導（liquidation cascade 的自然檢驗場）— 獨立 future paper。

---

## 期刊目標序

| 順位 | 期刊 | 理由 |
|---|---|---|
| 1st | **JIMFIM** | scope 完全對口（Yarovaya et al. 2022 同刊）；接受 reduced-form 跨市場傳導 + 誠實 OOS null；修復後 COVID-connectedness 峰值故事符合讀者群 |
| 2nd | **JEF** | 方法論訴求（Granger ≠ forecastability 的 discipline 論點）更有共鳴，但對 QR 識別更挑剔 — 需 P0-1 QR 存活 |
| 3rd | **IRFA** | Klein (2018)、Shahzad (2019) 同刊，crypto-safe-haven 辯論主場 |
| backup | **FRL** | 若 QR 支柱陣亡，縮成 asymmetry + honest-null 短文 |

**不建議**：JBF/JFE（無結構識別 / 無方法創新 / 無新資料，浪費 review cycle）；crypto 專刊（學術權重低於 JIMFIM/IRFA，對平台學術信譽線幫助小）。

---

## 禁止事項（本篇特有）

1. **P0 完成 + primary-path Codex 語義級複核前，禁止任何 ready 標記 / promotion**。本論文已兩次 premature promotion（2026-04-28 標 ready + 自估「94–95% 接受率」→ 5/21 Codex REJECT；6 月標 ready → 6/10 audit 降級）。第三次翻車會傷平台學術信譽線。
2. **禁止以 non-generalized（Cholesky-only）FEVD 當 headline** — net 方向隨排序翻號。headline 必用 **KPPS generalized FEVD**（order-invariant），Cholesky 兩排序只能作 sensitivity。
3. **禁止把 buggy 舊 JSON 當來源**：`k1025.py` / `k1025_v2.py` / `k1025b.py`（`decomp[-1]`）產出的 spillover 數字全部失真，重跑前不得引用；重跑後舊 JSON 標 `superseded`。
4. **iid-noise placebo 是硬性 gate**：任何 spillover/decomposition pipeline 投稿前必跑純雜訊 placebo（應得 index≈0），且落成 `scripts/tests/` 機械測試 — 這是唯一能攔住「陣列語意級」bug 的防線（7 輪人工審查全漏）。
5. **k865 同 bug 若再發現下游引用（knowledge/feed）須續行回溯更正**（研究誠實原則第 6 條；主體已於 2026-07-11 處置，見進度日誌）。
6. **禁止用 background agent 直接改寫 `.tex`**：DY 敘事與方法論決策留主線程（paper-workflow 硬規則）。

---

## 進度日誌

```
2026-07-11 | Fable deep review | 深審完成（發現 7 輪全漏 FEVD bug），待執行 P0 | f913ed68c
2026-07-11 | k865 外溢處置    | k865 同 FEVD bug 修正 + 下游回溯更正 + iid 機械 gate 已 commit（非本論文 P0）| c1831a0f6
```

---

## 接續提示詞

讀本檔 + `review_history/fable_deep_review_20260711/README.md` §5，從 **P0-1** 開始：

> 改 `experiments/k1025/k1025_v2.py` 的 `compute_spillover_index`：FEVD 切片改 `decomp[:, -1, :]`、改用 **KPPS generalized FEVD** 為主結果（兩 Cholesky 排序作 sensitivity）；改讀 pinned snapshot（`data/spy_btc_usd_vix_2015-2026.csv`，`auto_adjust=False`，SPY/BTC return 統一 log）重生成全表；QR 加 `VIX_{t-1}` 控制 + moving-block bootstrap 跑 sign-reversal 存活測試；subsample DM 補 HAC；AR grid 延到 22；把 iid-noise FEVD placebo 寫成 `scripts/tests/` 機械 gate（index≈0 才 PASS）。固定 seed。完成後交 primary-path Codex 做**語義級**複核（independent re-derivation，不只轉錄一致性）。**在此複核 PASS 前，禁止任何 ready 標記。** canonical queue task = `fable0711_cryptofear_k1025v3`。
