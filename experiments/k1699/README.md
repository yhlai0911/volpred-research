# K1699：六市場 Close-Convention 補跑 — PRG_tminus1 vs GJR vs HAR

- **日期**: 2026-07-12（台灣時間）
- **角色**: prg-periodic-garch 論文「雙時點 convention」敘事的最後一塊實驗證據（deep review 2026-07-11 的 P0-2 / K-new-A）
- **Seed**: 1699（全域）；各模組 MLE multistart 內建 `RandomState(42)`，估計完全 deterministic
- **Runtime**: ~77 秒 / 全六市場（讀 pinned snapshot）
- **Verdict**: **CONFIRMED NULL（預期中的支柱性結果）** — 嚴格 close-time convention 下，PRG 對 GJR 在六市場全部無 Harvey 顯著優勢

## 1. 研究問題

K880v2（SPY DM −0.57）與 K880 重跑（SPY `PRG_Extended_tminus1` DM −1.48）顯示：**嚴格 t−1 close 口徑下 PRG 對 GJR 無優勢** — 但證據只有 SPY 一個市場。本實驗把 close-convention 補到 K1544 的同一組六市場（SPY / QQQ / GLD / EEM / 0050.TW / TAIFEX），回答：

> 「strict t−1 下 PRG 無優勢」是否六市場一般成立？高 overnight-share 市場（TAIFEX 61%、GLD 53%）是否例外？

## 2. 與 K880 / K1544 的關係

| 實驗 | Convention | 比較 | 市場 | 結果 |
|---|---|---|---|---|
| K880（canonical headline） | **混合時點**（ĥ_ov 在 d−1 close、ĥ_in 用當日已實現 overnight） | PRG vs GJR | SPY | DM +5.06（灌水，ill-posed） |
| K880v2 | Close（嚴格 t−1） | PRG vs GJR | SPY | DM −0.57（無優勢） |
| K880 重跑 `PRG_Extended_tminus1` | Close（lagged-realized plug-in） | PRG vs GJR | SPY | DM −1.48（無優勢） |
| K1544 | Open（開盤時點，fair GJR-X 同資訊） | PRG open-known vs fair GJR-X | 六市場 | PRG 全勝（4/6 過 3.0） |
| **K1699（本實驗）** | **Close（嚴格 t−1，六市場）** | PRG_tminus1 vs GJR / HAR | 六市場 | **0/6 Harvey 顯著 vs GJR** |

雙時點框架至此閉合：**open-time 下 PRG 的 session bridge 有跨六市場真實增量（K1544）；close-time 下與 GJR 無異（K1699）；canonical headline 的 +5~+6 全是時點混合 artifact**。

## 3. 設計

### 3.1 Close-convention PRG（全部資訊 ∈ F^c_{d−1}）

全日預測 = ĥ_ov + ĥ_in，於 d−1 close 發出。ĥ_ov 一律由 (r²_intra[t−1], r_intra[t−1], h_state after intraday t−1) 遞迴。intraday 方程的未觀測 overnight shock 用兩種 plug-in：

- **`PRG_tminus1_exp`（主變體，review 規格 ĥ_in(ĥ_ov)）**：model-consistent 期望代入 — `E[r²_ov[t]|F] = ĥ_ov`、leverage indicator 期望 = 1/2（對稱零均值 innovation 假設）：`ĥ_in = ω₁ + (α₁ + 0.5γ₁)·ĥ_ov + β₁·ĥ_ov`
- **`PRG_tminus1_lag`（robustness，複製 K880 重跑變體）**：lagged realized plug-in — `ĥ_in = ω₁ + α₁·r²_ov[t−1] + γ₁·r²_ov[t−1]·I(r_ov[t−1]<0) + β₁·ĥ_ov`

`PRG_canonical_diag`（混合時點，用當日已實現 r²_ov[t]）只作為對 K880/K1544 的 anchor 診斷欄，不進 headline。

### 3.2 基準（同 lag 口徑）

- **GJR(1,1)**：close-to-close returns，one-step-ahead from t−1 close，expanding window，每 63 日 refit（模組原生函式）
- **HAR**：log(σ²_fullday) 的 1/5/22 日 lag，one-step-ahead，每 63 日 refit（模組原生函式）
- PRG refit cadence 同 K1544（SPY 126 日、QQQ/GLD/EEM/0050 252 日、TAIFEX 126 sessions）；估計一律只用 forecast origin 之前的資料

### 3.3 Canonical 檢定工具（依 `.claude/rules/experiments.md` 硬規則）

- QLIKE：`volpred.stats.model_evaluation.qlike_pointwise`（actual/predicted 方向）
- DM：`volpred.stats.model_evaluation.dm_test`（h=1，Newey-West HAC，bandwidth = ceil(n^{1/3})，即 10–13 lags）— **無自寫 h−1 lag 實作**
- 每個 DM cell 附 loss differential 的 acf(1) 與 2× bandwidth 敏感度 t（supplementary；全表 |acf1| ≤ 0.26，2× bandwidth 對任何結論零影響）

### 3.4 資料（pinned snapshot，SHA256 記錄於 results JSON）

首跑由 loader 抓取（yfinance，`end=2026-04-05`；TAIFEX 由本地 tick 檔建 session 序列）後立即 pin 到 `data/*.csv`；重跑一律讀 snapshot。**Snapshot 讀取必須 `float_precision="round_trip"`**（見 §6 誠實記錄）。

| 市場 | Snapshot SHA256（前 12 碼） | OOS 期間 | N |
|---|---|---|---:|
| SPY | `501af099f9e8` | 2019-01-02 ~ 2026-04-02 | 1823 |
| QQQ | `b42eb0323092` | 2018-05-16 ~ 2026-04-02 | 1981 |
| GLD | `0741addcf29a` | 2019-10-31 ~ 2026-04-02 | 1613 |
| EEM | `924a74477545` | 2019-05-10 ~ 2026-04-02 | 1734 |
| 0050.TW | `91ec88b94cc7` | 2021-01-08 ~ 2026-04-02 | 1251 |
| TAIFEX | `59c21377aea9`（sessions） | 2022-07-14 ~ 2025-12-31 | 843 |

資料 vintage = 2026-07-12 下載（yfinance `auto_adjust=True` 會回溯調整歷史，故與 K1544 的 06-24 未 pin 抓取有 ulp~0.1% 級差異；K880/K1544 數字是方向性 anchor，非 bit-identical 目標）。

## 4. 結果

### 4.1 QLIKE（common sample，六市場）

| Market | N | PRG tm1 exp | PRG tm1 lag | GJR | HAR | canonical diag |
|---|---:|---:|---:|---:|---:|---:|
| SPY | 1823 | 0.8663 | 0.8780 | 0.8534 | 1.4635 | 0.7469 |
| QQQ | 1981 | 0.8626 | 0.8829 | 0.8305 | 1.3681 | 0.7598 |
| GLD | 1613 | 0.8978 | 0.9002 | 0.9021 | 1.5173 | 0.8204 |
| EEM | 1734 | 0.7850 | 0.7904 | 0.7905 | 1.2350 | 0.6664 |
| 0050.TW | 1251 | 0.9692 | 0.9812 | 0.9753 | 3.1890 | 0.7913 |
| TAIFEX | 843 | 0.2441 | 0.2495 | 0.2550 | 0.2848 | 0.1209 |

Anchor 驗證：canonical diag 與 K1544 canonical PRG（0.7581/0.7707/0.8204/0.6786/0.7765/0.120932）方向與量級一致；TAIFEX（本地 tick 資料、無 vintage 漂移）**與 K1544 完全一致**；SPY HAR 1.4635 與 K880 重跑 1.46352 一致到第 5 位。

### 4.2 DM 全表（canonical dm_test；負 t = 前者較佳；Harvey 門檻 |t|>3.0）

| Market | exp vs GJR | exp vs HAR | lag vs GJR | lag vs HAR | GJR vs HAR |
|---|---:|---:|---:|---:|---:|
| SPY | +0.74 (p=.46) | **−6.49** | +1.25 (p=.21) | **−6.36** | **−6.89** |
| QQQ | +2.28 (p=.023) | **−7.79** | +2.95 (p=.003) | **−7.52** | **−8.53** |
| GLD | −0.44 (p=.66) | **−6.53** | −0.18 (p=.86) | **−6.47** | **−6.51** |
| EEM | −0.54 (p=.59) | **−5.73** | −0.00 (p=1.0) | **−5.61** | **−5.82** |
| 0050.TW | −0.32 (p=.75) | **−4.25** | +0.28 (p=.78) | **−4.24** | **−4.21** |
| TAIFEX | −0.49 (p=.62) | −1.82 (p=.069) | −0.23 (p=.82) | −1.72 (p=.087) | −0.71 (p=.48) |

粗體 = Harvey 顯著（|t|>3.0）。完整 p 值 / acf(1) / 2× bandwidth 敏感度在 `k1699_results.json` 的 `dm_tests`。

### 4.3 判讀

1. **PRG_tminus1 vs GJR：六市場 0/6 Harvey 顯著、0/6 過 1.96（除 QQQ）** — 「strict t−1 下 PRG 無優勢」由 SPY 單點推廣為六市場一般事實。主變體 DM t ∈ [−0.54, +2.28]。
2. **高 overnight-share 市場也沒有例外**：TAIFEX（ON share 61%）−0.49、GLD（53%）−0.44 — 方向偏 PRG 但離顯著極遠。deep review 提出的「額外正面發現」情境**不成立**。
3. **QQQ 是唯一 nominal 反向 cell**（exp +2.28 / lag +2.95，GJR 較佳；未過論文自己的 Bonferroni |t|>3.0 門檻）— 誠實表述是「零市場顯著、其中一市場方向上偏 GJR」，不可寫成 PRG 平手以上。
4. **PRG_tminus1 對 HAR 5/6 Harvey 顯著勝**，但 GJR vs HAR 同樣 5/6 顯著 — 這主要反映 HAR 在 r² proxy target 上的弱勢（GARCH 族全面勝 HAR），不是 PRG 結構的功勞；論文中只能作次要佐證。
5. **兩個 close-convention 變體結論完全一致**（exp 與 lag 每格同號、同不顯著），且 K880 重跑的 SPY lag 式 DM −1.48 與本實驗 +1.25 之間的差異來自資料 vintage 與 common-sample 定義，兩者都在「不顯著」判定內。

### 4.4 對雙時點敘事的裁定含義

本實驗完成 deep review §5.1 要求的證據鏈最後一環。**雙時點框架現有完整六市場證據支撐**：

- **Close convention（本實驗）**：PRG 與 GJR 無異（0/6 顯著）→ 誠實結論：session bridge 在嚴格 day-ahead 口徑下不帶來增量
- **Open convention（K1544）**：PRG open-known 六市場全勝 fair GJR-X（4/6 過 3.0）→ bridge + session 參數化在 open-time 有真價值
- **混合時點（K880 canonical headline）**：+5.06 是 ill-posed 物件的 artifact，必須從論文 headline 移除

「同一模型同一資料，DM 從 +5 到 −0.5 只因 forecast-timing convention」— 論文重寫後的 sharp point 成立。**NULL 是這裡的正確且必要結果**：若 close-time 下 PRG 仍勝，雙時點敘事反而崩潰。

## 5. Codex Review

`codex_review.md` — **PASS_WITH_CAVEAT**（gpt-5.4/high，read-only）。兩個 finding（k881/k886 分支 refit-failure stale-state、TAIFEX lag 邊界 guard）均已修復後重跑。無 headline-invalidating lookahead / 參數順序 bug；GJR/HAR 基準確認為嚴格 one-step-ahead 同資訊集。

## 6. 誠實記錄（methodology incidents）

1. **CSV roundtrip 1-ulp → MLE basin 漂移**：pandas `read_csv` 預設 C parser 有最多 1 ulp 誤差；非凸 PRG/GJR MLE 把 1e-16 級輸入擾動放大成不同 optimization basin，TAIFEX QLIKE 曾因此在「in-memory build vs snapshot read」間漂移 ~1%（DM t −0.49 → 0.00，判定不變）。修復 = 所有 snapshot 讀取加 `float_precision="round_trip"`；修復後**連續兩跑 bit-identical**，且 TAIFEX 與 tick 原始 build 完全一致。教訓：pin snapshot 不只要 pin 檔案，**讀取 parser 也要 round-trip 精確**，否則 pin 形同虛設。
2. **點值脆弱、判定穩健**：上述 ulp 敏感度意味 PRG-vs-GJR 的 nominal QLIKE 勝負（4/6 vs 3/6）會被 noise 翻轉，**不可引用「PRG QLIKE 較低的市場數」作為結論**；穩健的陳述只有 DM 全表的不顯著性（任何擾動版本下 0/6 顯著皆成立）。這與 K1544 Codex caveat（非凸 MLE multistart 點估計脆弱）同根。
3. **Leverage 期望假設**：`PRG_tminus1_exp` 的 leverage 期望用 1/2（對稱 innovation）。lag 變體不依賴此假設，兩者結論一致，故此假設非結果驅動。

## 7. 檔案

- `k1699.py` — 主腳本（六市場、雙變體、canonical 檢定、snapshot pinning）
- `k1699_results.json` / `results.json` — 完整結果（DM 全表含 p/acf1/敏感度、snapshot SHA、refit 診斷）
- `per_market_table.csv` / `per_market_table.md` — 摘要表
- `fig_k1699_close_convention.png` — QLIKE 與 DM t 圖
- `codex_review.md` — Codex review 全文 + 修復記錄
- `data/` — pinned snapshots（六市場 + TAIFEX sessions/daily）
- `run_log.txt` — 最終跑 log

## 8. References

- Bollerslev & Ghysels (1996), Periodic ARCH. JBES 14(2).
- Patton (2011), Volatility forecast comparison using imperfect volatility proxies. JoE 160(1).
- Diebold & Mariano (1995); Harvey, Leybourne & Newbold (1997); Harvey, Liu & Zhu (2016).
- Corsi (2009), HAR. J. Fin. Econometrics 7(2).
- Linton & Wu (2020), coupled component DCS-EGARCH for intraday/overnight volatility.
