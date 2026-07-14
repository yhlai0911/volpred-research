# K1710：Open-Convention + Mixed-Timing Anchor 補跑（K1699 pinned vintage）

- **日期**：2026-07-14（台灣時間）
- **角色**：prg-periodic-garch 論文重寫「三時點 convention flip 主表」缺的兩個面板，補在 K1699 的同一批 pinned snapshot 上
- **Seed**：全域 1710；PRG estimator 用 base 模組內建 multistart seed，FairGJRX 沿用 K1544 內建 `RandomState(1544)`，全部 deterministic
- **Runtime**：~38 秒（兩趟 determinism pass；numba 已由模組 import 暖機）
- **Verdict**：**PASS** — 六市場 × open/mixed 兩面板 DM 全表落地、連跑兩趟 bit-identical、anchor 方向六市場全一致、Codex re-review PASS

## 1. 研究問題

論文重寫的 headline = **「同一模型、同一資料，PRG-vs-baseline 的 DM 只因 forecast-timing convention 就從強勝翻到約 0」**。三時點主表需要三個面板同一資料 vintage、同一 reproduce gate：

| 面板 | 物件 | 既有證據 | 問題 |
|---|---|---|---|
| Close（嚴格 t−1） | PRG_tminus1 vs GJR | **K1699**（pinned、deterministic、Codex PASS） | 已就緒 |
| Open（開盤時點） | PRG open-known vs fair GJR-X | K1544（2026-06-24，**資料未 pin**，點估計脆弱 caveat） | 不可入表 |
| Mixed（混合時點） | PRG canonical vs GJR | K880（SPY DM +5~+6，headline artifact） | 未在 K1699 vintage 重現 |

K1710 把 **Open 與 Mixed 兩物件在 K1699 的 pinned vintage 上重現**，讓論文主表三面板全部單一 vintage、reproduce gate 可驗。

## 2. 與 K880 / K1544 / K1699 的關係

| 實驗 | Convention | 主 DM cell | 市場 | 資料 | 本實驗如何用它 |
|---|---|---|---|---|---|
| K880 | Mixed（canonical headline） | GJR_vs_PRG_Extended（SPY +6.4537 artifact / +5.06 rerun，正 = PRG 優） | SPY | 未 pin | Mixed anchor 的方向性對照（從 pinned artifact 讀值） |
| K1544 | Open | fair − PRG open-known（正 = PRG 優） | 六市場 | **未 pin（06-24）** | Open panel 的 fair GJR-X 規格與 open-known 定義來源 + 方向 anchor |
| K1699 | Close（嚴格 t−1） | PRG_tminus1 vs GJR（負 = PRG 優） | 六市場 | **pinned（07-12）** | 提供 pinned snapshot + fixed PRG 傳播迴圈 + GJR baseline |
| **K1710（本實驗）** | **Open + Mixed** | 見下 | 六市場 | **= K1699 pinned vintage** | 補齊 open / mixed 兩面板 |

**符號 orientation（全實驗統一）**：每個 DM cell 皆 `dm_cell(A, B)` → pair `A_vs_B`，**負 t = A 損失較低（A 較佳）**，與 K1699 close 面板同慣例，讓三面板主表方向一致。K1544 用的是相反口徑（fair 減 PRG，正 = PRG 優）；下方 anchor 對帳明確做符號翻轉。

## 3. 設計

### 3.1 四個預測物件（每市場，OOS 期間與 refit cadence 完全同 K1699）

1. **`PRG_open_known`**（開盤發出）：全日 = 已實現 `r²_ov[t]` + `ĥ_in(r²_ov[t])`（K1544 open-known 定義）
2. **`FairGJRX`**（開盤發出）：K1544 fair-information GJR-X，`h_t = ω + α r²_c2c[t−1] + γ·1(r<0)·r² + β h[t−1] + δ r²_ov[t]`（δ 用當日 overnight），expanding window、每 63 日 refit、只用 forecast origin 前資料
3. **`PRG_canonical_mixed`**（舊論文 headline 物件）：`ĥ_ov`（d−1 close 發出）+ `ĥ_in(r²_ov[t])`（d open 發出）
4. **`GJR`**：close-to-close baseline，與 K1699 同款（`gjr_oos_forecast`）

`PRG_open_known` 與 `PRG_canonical_mixed` 共用同一條 PRG 迴圈與同一 `h_in_c`（皆餵當日已實現 overnight），只差第一項：canonical 用 `ĥ_ov`（預測），open-known 用 `r²_ov[t]`（已實現）。傳播迴圈直接沿用 K1699 的 **fixed** 版本（含 k881/k886 refit-failure stale-state 修正）。

### 3.2 檢定工具（依 `.claude/rules/experiments.md` 硬規則）

- QLIKE：`volpred.stats.model_evaluation.qlike_pointwise`（actual/predicted 方向）
- DM：`volpred.stats.model_evaluation.dm_test`（h=1，Newey-West HAC，bandwidth = ceil(n^{1/3})）— **無自寫 h−1 lag 實作**
- 每個 DM cell 附 loss differential 的 acf(1) 與 2× bandwidth 敏感度 t（supplementary）

### 3.3 資料（self-contained pinned snapshot）

七個 K1699 pinned CSV 複製進 `experiments/K1710/data/`，讀取一律 `float_precision="round_trip"`（K1699 §6 教訓：1 ulp 翻 MLE basin），每檔 SHA256 **assert 與 K1699 記錄一致**（全 7 檔通過）。**未重新下載任何資料**。

| 市場 | SHA256（前 12 碼） | OOS 期間 | N | OOS overnight variance share |
|---|---|---|---:|---:|
| SPY | `501af099f9e8` | 2019-01-02 ~ 2026-04-02 | 1823 | 0.4481 |
| QQQ | `b42eb0323092` | 2018-05-16 ~ 2026-04-02 | 1981 | 0.3855 |
| GLD | `0741addcf29a` | 2019-10-31 ~ 2026-04-02 | 1613 | 0.6094 |
| EEM | `924a74477545` | 2019-05-10 ~ 2026-04-02 | 1734 | 0.7065 |
| 0050.TW | `91ec88b94cc7` | 2021-01-08 ~ 2026-04-02 | 1251 | 0.6349 |
| TAIFEX | `59c21377aea9`（sessions） | 2022-07-14 ~ 2025-12-31 | 843 | 0.6890 |

> **Overnight variance share** = `sum(r²_ov) / sum(r²_ov + r²_in)`，**OOS 期間**、從 pinned snapshot 算（論文 Data 表用；舊稿值來自未 pin 資料，不可再用）。此定義（OOS 窗 + 加總比）與 K1699 README 的 full-sample 平均比不同，故數值不同（例：TAIFEX 68.9% vs 舊 61%、GLD 60.9% vs 舊 53%）。

## 4. 結果

### 4.1 QLIKE（common sample，六市場）

| Market | N | PRG open-known | Fair GJR-X | PRG canonical | GJR |
|---|---:|---:|---:|---:|---:|
| SPY | 1823 | 0.669737 | 0.726691 | 0.746933 | 0.853368 |
| QQQ | 1981 | 0.709635 | 0.742310 | 0.759845 | 0.830479 |
| GLD | 1613 | 0.553532 | 0.587197 | 0.820410 | 0.902084 |
| EEM | 1734 | 0.438539 | 0.527366 | 0.666351 | 0.790491 |
| 0050.TW | 1251 | 0.568406 | 0.625625 | 0.791331 | 0.975338 |
| TAIFEX | 843 | 0.039291 | 0.058561 | 0.120932 | 0.255001 |

### 4.2 DM 全表（canonical dm_test；**負 t = 前者較佳**；Harvey 門檻 |t|>3.0）

| Market | **Open：PRG open-known vs FairGJRX** | **Mixed：PRG canonical vs GJR** | 次要：FairGJRX vs GJR | 次要：open-known vs GJR |
|---|---:|---:|---:|---:|
| SPY | **−3.557** | **−5.827** | **−6.192** | **−6.432** |
| QQQ | −1.563 | **−4.781** | **−5.665** | **−4.360** |
| GLD | **−3.643** | **−6.106** | **−10.878** | **−12.910** |
| EEM | **−10.137** | **−6.405** | **−9.855** | **−12.964** |
| 0050.TW | **−3.670** | **−5.194** | **−7.571** | **−8.921** |
| TAIFEX | **−5.503** | **−4.328** | **−5.159** | **−5.720** |

粗體 = Harvey 顯著（|t|>3.0）。完整 p / acf(1) / 2× bandwidth 敏感度在 `K1710_results.json`。

### 4.3 判讀

1. **Open 面板（PRG open-known vs FairGJRX）：六市場全部負 t（PRG 較佳），5/6 Harvey 顯著**（QQQ −1.56 例外）。開盤時點下 PRG 的 session bridge 對「同資訊集的 fair GJR-X」有真實增量 —— 重現 K1544 的核心結論。
2. **Mixed 面板（PRG canonical vs GJR）：六市場全部強負 t（|t| 4.3–6.4），6/6 Harvey 顯著**。混合時點物件因為 intraday 方程偷看當日已實現 overnight，對 close-to-close GJR 呈現「灌水」優勢 —— 重現 K880 的 headline artifact。
3. **對比 Close 面板（K1699，PRG_tminus1 vs GJR：六市場 0/6 顯著、SPY +0.74）**：同一 PRG、同一 pinned 資料，DM 由 mixed 的 −5.8 → open 的 −3.6 → close 的 +0.7。**「時點 convention 一翻，PRG 的 DM 就從強勝翻到約 0」在單一 vintage 上成立**。
4. **次要 cell**：FairGJRX 與 open-known 對 GJR 皆六市場強負（Harvey 全過）—— 兩個「開盤時點」物件都因拿到已實現 overnight 而大勝 close-to-close GJR，佐證面板設計的資訊集差異。

## 5. Anchor 對帳

### 5.1 Open 面板對 K1544（方向一致即可，點值允許 vintage 級差異）

K1544 口徑（fair 減 PRG open-known，正 = PRG 優）→ K1710 口徑（PRG 減 fair，負 = PRG 優），符號翻轉後對照：

| Market | K1710 open t（PRG−fair） | = K1544 口徑（−t） | K1544 anchor | 方向一致 |
|---|---:|---:|---:|:--:|
| SPY | −3.557 | +3.557 | +2.115 | ✔ |
| QQQ | −1.563 | +1.563 | +2.967 | ✔ |
| GLD | −3.643 | +3.643 | +3.625 | ✔（近乎一致） |
| EEM | −10.137 | +10.137 | +10.130 | ✔（近乎一致） |
| 0050.TW | −3.670 | +3.670 | +3.870 | ✔ |
| TAIFEX | −5.503 | +5.503 | +5.607 | ✔ |

**六市場方向全部一致（PRG open-known 勝 fair GJR-X）**。GLD/EEM/0050/TAIFEX 點值與 K1544 幾乎一致；SPY 偏高（+3.56 vs +2.11）、QQQ 偏低（+1.56 vs +2.97），差異來源：(a) 資料 vintage（pinned 07-12 vs 未 pin 06-24），(b) canonical dm_test（ceil bandwidth）vs K1544 local `hac_t_stat`（floor bandwidth），(c) 四模型 common-sample 交集不同。**無任何方向翻轉**，故 anchor PASS。

### 5.2 Mixed 面板對 K880（SPY）

K880 `GJR_vs_PRG_Extended` = **+6.4537**（checked-in artifact，正 = PRG 優）／ **~+5.06**（2026-06-13 rerun，directional prior）；兩者皆「PRG 較佳」。K1710 SPY mixed t = **−5.827**（PRG-first 口徑，負 = PRG 優）落在兩者之間，**方向一致**。anchor 值由 `read_k880_spy_anchor()` 從 pinned artifact 動態讀取並記錄 provenance，不硬編。

## 6. 誠實記錄（methodology + 內部一致性）

1. **與 K1699 bit-identical 交叉驗證（最強證據）**：K1710 的 `PRG_canonical_mixed` 與 `GJR` OOS QLIKE **與 K1699 的 `PRG_canonical_diag` / `GJR` 逐市場差 = 0.00e+00**（六市場全部精確相符，含 TAIFEX 0.120932）。證明 K1710 的 PRG 迴圈與 GJR baseline 在同一 pinned 資料上與 K1699 完全重現 —— 這是 pinned-vintage 補跑的正確性硬證據。
2. **Determinism**：全 pipeline 連跑兩趟，numeric core（QLIKE + DM t/p + overnight share）assert **bit-identical**（`determinism.two_pass_bit_identical = true`）。
3. **點值脆弱、方向穩健**：非凸 PRG/GJR MLE 對 ulp 級輸入敏感（K1544/K1699 同根 caveat），故 open 面板的 SPY/QQQ 點值與 K1544 有 vintage 級差異；**穩健結論只引用 DM 方向**（六市場全一致），不引用 nominal 點值。
4. **HAC 敏感度**：TAIFEX open 面板 loss-diff acf(1)=0.358（其餘接近 0），canonical HAC（bandwidth 10）已吸收；2× bandwidth（20）下 t 由 −5.50 → −4.84，仍遠過 |3|，**結論不翻**。全表任何 cell 的 2× bandwidth 皆不改判定。
5. **Leverage / 資訊集**：open-known 與 fair GJR-X 只用開盤已知的 `r²_ov[t]`，不碰 `r_c2c[t]` / intraday / target[t]；`ĥ_ov` 與 GJR 只用 t−1 及更早。Codex round-1 lookahead / refit-boundary / QLIKE 皆 PASS。

## 7. Codex Review

`codex_review.md` — round-1 **FAIL（僅 item 4 文字/metadata 方向矛盾，計算 item 1/2/3/5 全 PASS）** → 修正 docstring orientation、改名誤導 JSON key、改為從 pinned artifact 讀 K880 anchor、加 TAIFEX session 對齊 assertion → round-2 **PASS_WITH_CAVEAT**（殘留一行敘述）→ 修正後 **PASS**。無 lookahead / 參數順序 / QLIKE 方向 bug。Reviewer：Codex CLI 0.144.1（gpt-5.6-sol，read-only，經 `codex_exec_bounded.sh` 有界呼叫）。

## 8. 檔案

- `K1710.py` — 主腳本（四物件、canonical 檢定、snapshot SHA 驗證、兩趟 determinism、K880 anchor 動態讀取）
- `K1710_results.json` / `results.json` — 完整結果（DM 全表含 p/acf1/敏感度、snapshot SHA、anchor 對帳、determinism 旗標）
- `per_market_table.csv` / `per_market_table.md` — 摘要表（含 overnight share 欄）
- `fig_K1710_open_and_mixed.png` — QLIKE 與 open/mixed DM t 圖
- `codex_review.md` — 兩輪 Codex review 全文 + 修復記錄
- `data/` — 七個 pinned snapshot（= K1699 vintage，SHA256 驗證）
- `run_log.txt` — 最終跑 log

## 9. References

- Bollerslev & Ghysels (1996), Periodic ARCH. JBES 14(2).
- Patton (2011), Volatility forecast comparison using imperfect volatility proxies. JoE 160(1).
- Diebold & Mariano (1995); Harvey, Leybourne & Newbold (1997); Harvey, Liu & Zhu (2016).
- Corsi (2009), HAR. J. Fin. Econometrics 7(2).
- Linton & Wu (2020), coupled component DCS-EGARCH for intraday/overnight volatility.
