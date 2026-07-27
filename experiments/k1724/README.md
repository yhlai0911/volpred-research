# K1724 — 台股當沖佔比與波動：散戶 herding 的在地量化

## 研究問題

台灣證交所（TWSE）**免費、日頻**公布「當日沖銷（當沖）交易統計」，這種零售當沖的公開日頻序列在國際市場罕見（多數市場沒有）。本實驗問兩件事：

1. **預測力（RQ1）**：當沖成交比率對**次日**已實現波動（RV）是否有*增量*預測力？在 HAR-RV baseline 之上加入當沖比率，樣本外（OOS）增量 R² 是否顯著為正？
2. **因果方向（RQ2，雙向 Granger）**：是「波動吸引當沖」（vol → day-trading，投機者被高波動吸引）還是「當沖放大波動」（day-trading → vol，散戶 herding 推高波動）？

## 資料 provenance（全部免費）

| 變數 | 來源 | 端點 / 取用 | 期間 |
|---|---|---|---|
| 當沖比率 | TWSE `TWTB4U`「當日沖銷交易統計資訊」aggregate table | `https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date=YYYYMMDD` → `tables[0]` | 2014-06-30 起（現股當沖雙向開放後） |
| TAIEX RV | yfinance `^TWII` 日頻 OHLCV | `yf.download("^TWII", ...)` | 同上重疊期 |

**當沖比率定義**：主變數 `dt_ratio` = **金額當沖比** = mean(當沖總買進金額占市場比重%, 當沖總賣出金額占市場比重%)。TWSE 官方定義：占市場比重% = 當沖買(賣)金額 ÷ [(整體市場買+賣成交金額) ÷ 2] × 100。此比率由 TWSE 直接提供（`tables[0]` 的欄位），**無需自行加總個股**，provenance 乾淨。另保留股數當沖比 `dt_vol_ratio` 作對照。

**端點驗證**：2014-01-06（現股當沖上路）起連續可得、格式一致至今；本實驗自 2014-06-30（先賣後買現股當沖亦開放、雙向 regime）起用，避開 2014 上半年單向、機械受限的過渡期。抓取採 resumable 快取（`data/daytrade_ratio.csv`），rate-limit 0.3–0.5s，非交易日（holiday）以 `stat!=OK` / 空表判為 no_data 跳過（no silent fallback，錯誤寫 stderr）。

**RV proxy**：TAIEX 無免費 intraday，故用 range-based 日頻估計：
- **Garman-Klass（primary）**：`0.5·(ln H/L)² − (2ln2−1)·(ln C/O)²`
- **Parkinson（robustness）**：`(1/(4ln2))·(ln H/L)²`
- **close-to-close 平方報酬（robustness）**：`(ln C_t/C_{t−1})²`

三者皆為日頻變異數 proxy（×1e4 做數值穩定）。**限制**：GK/Parkinson 衡量*盤中*波動，未含隔夜跳空，會低估總（close-to-close）變異數；此 proxy 選擇對 RQ2 結論有影響（見下）。

## 方法

1. **對齊**：當沖比率與 TWII RV 內連接（inner join）到交易日，`N = 2935`（2014-06-30 → 2026-07-27）。
2. **HAR baseline**：`RV_{t+1} ~ RV_d + RV_w(5) + RV_m(22)`。
3. **Augmented**：baseline + 當沖比率的 HAR 型三項（`dt_d, dt_w, dt_m`，皆 dated ≤ t）。
4. **OOS**：expanding window，初始訓練 750 obs，逐步 1-step-ahead refit；`n_oos = 2163`。指標：vs-mean OOS R²、增量 R²、QLIKE、**Diebold-Mariano**（repo canonical `volpred.stats.model_evaluation.dm_test`，Newey-West HAC，bandwidth `ceil(n^{1/3})`；QLIKE = actual/pred − log(actual/pred) − 1，canonical `qlike_pointwise`），以及**巢狀模型的正確檢定 Clark–West**（`clark_west_test`，單尾）——augmented 巢狀包含 HAR，一般 DM 對大模型有偏，nested 增量預測力以 CW 為主判準。
5. **定態**：對 log RV 與當沖比率做 ADF + KPSS；非定態則差分。
6. **雙向 Granger**：VAR(p)（p 由 AIC 選，對照 BIC）於定態轉換後的 {log RV, 當沖比率} 上，兩方向各做 Granger F-test。
7. **穩健性**：子期（2020 前 / 2020 起）、RV proxy 替換、加入控制（`|報酬|`、`log 成交量`）、雙邊差分 Granger。

**Lookahead 防護**：目標 `y = RV.shift(-1)`（即 `RV_{t+1}`）；所有 predictor（HAR 與當沖項）皆 dated ≤ t。OOS 迴圈 `for t in range(min_train, n)` 只用 `[:t]`（其 label 為 `RV_1..RV_t`，皆於預測 `RV_{t+1}` 前已 realized）估計，無洩漏。baseline 與 augmented 使用**完全相同**的 lag 慣例。

## 結果（全部來自 `k1724_results.json`，實際計算）

### 描述統計
- 當沖金額比率：mean **27.66%**、std 12.53%、range 2.71%–52.43%（2014 約 4% → 2026 約 43%，強上升趨勢）。
- 當沖股數比率：mean 15.17%。
- GK 日波動：mean **0.606%**、max 5.73%（2020 COVID）。
- corr(當沖金額比率, GK 日波動) = **0.191**（弱正的同期相關）。

### RQ1 — 預測力：**5% 下 NULL（邊界，非強式「零資訊」）**
| 指標 | Baseline (HAR) | Augmented (+當沖) |
|---|---|---|
| OOS R²（vs mean） | 0.1743 | 0.1767 |
| OOS 增量 R²（aug vs base） | — | **+0.0029（0.29%）** |
| OOS QLIKE | 0.3510 | 0.3595（**變差**） |

- **Clark–West（巢狀模型正確檢定）**：t = **1.605，單尾 p = 0.054**（HAC lag=13）→ 5% 下**未拒絕 NULL**，但屬**邊界**證據，不宜宣稱「毫無資訊」。（augmented 巢狀包含 HAR，一般 DM 在虛無下對大模型不利，故 nested 比較以 CW 為準；DM 併列作透明對照。）
- DM（MSE）t = **0.53，p = 0.60**；DM（QLIKE）t = **−1.49，p = 0.137** → 兩者皆不顯著，且 QLIKE 點估計偏向 baseline 較優。
- In-sample 全期：當沖三項聯合 **HAC Wald χ²(3) = 8.49，p = 0.037**（弱顯著），但 adj-R² 僅增 0.6pp（0.1833 → 0.1897）；係數 `dt_d = −0.044`、`dt_w = +0.035`、`dt_m = +0.011`（符號互抵）。
- **穩健性一致指向弱/無效**：加入控制後增量 R² 轉負（−0.003，DM QLIKE p=0.115）；子期切分中，2020 前增量 R² 負、2020 起 +0.020 但 DM 仍不顯著（p=0.244）且 in-sample 顯著性弱化（Wald p 由 0.015 升到 0.065）；換 Parkinson/squared-return proxy 增量 R² 亦近零或為負。

**RQ1 結論**：當沖比率 in-sample 有*弱*統計顯著性，樣本外增量預測力**在 5% 下未達顯著（Clark–West 邊界 p≈0.054）、經濟上微不足道、且跨子期/proxy/控制不穩健**。整體判定為 **NULL（邊界）**：不支持「當沖比率能穩健改善次日 RV 預測」的主張；不作「完全沒有資訊」的強式宣稱。

### RQ2 — 因果方向：RV→當沖穩健，當沖→RV 脆弱
定態檢定：log RV level ADF p=0.0（拒單根）；當沖比率 level ADF p=0.379、KPSS p≤0.01（兩者皆非定態）→ 一階差分。**log RV 的處理**：ADF 強烈拒絕單根、KPSS 卻拒定態，此「ADF 拒／KPSS 拒」型態是**持續 / 長記憶但無單根**序列的特徵（已實現波動的文獻常見），而非單根；VAR 需 I(0) 輸入，無單根之序列在 level 下可用，對 I(0) 長記憶序列再差分會 over-difference，故 primary 保留 log RV level，另以**雙邊差分**版本作穩健性對照。VAR lag 搜尋上限提高到 30（避免撞邊界）：primary（GK level）AIC 選 **lag=16**（未在邊界；BIC=7）。同期相關 0.077。

lag 搜尋 maxlag=30 下（primary，level-RV）：

| 方向 | 假說 | F | p (GK) | Parkinson | squared-ret |
|---|---|---|---|---|---|
| **RV → 當沖** | 波動吸引當沖 | 4.99 | **≈0** | ≈0 | ≈0 |
| **當沖 → RV** | herding 放大波動 | 2.92 | **7.9e-05** | 0.075 | 0.316 |

雙邊差分（Δlog RV, Δ當沖；maxlag=30）穩健性：

| 方向 | GK | Parkinson | squared-ret |
|---|---|---|---|
| RV → 當沖 | ≈0 | ≈0 | ≈0 |
| 當沖 → RV | 0.0012 | 0.196 | 0.115 |

- **RV → 當沖（波動吸引當沖）：ROBUST** — 三種 RV proxy、level 與雙邊差分下 p≈0，方向穩定。
- **當沖 → RV（herding 放大波動）：FRAGILE** — 僅在 Garman-Klass proxy 下顯著（level p=7.9e-05、雙邊差分 p=0.0012），換成 Parkinson（level p=0.075、diff p=0.196）或平方報酬（level p=0.316、diff p=0.115）即不顯著。此 leg 的顯著性**綁在 RV 估計量的選擇**（GK 用 open-to-close `ln(C/O)` 分量，Parkinson 僅用高低全距），屬 **proxy-sensitive**，不宜歸因為特定經濟機制，也不構成穩健的市場現象。

**RQ2 結論**：資料**更穩健地支持「波動吸引當沖客」（RV→DT）**，而非「散戶 herding 放大波動」（DT→RV）。後者僅在單一 RV 估計量下成立，不具跨 proxy 穩健性，故對 herding-amplifies-volatility 假說**不給予穩健支持**。

## 圖
- `fig1_daytrade_vs_rv.png` — 當沖金額比率（趨勢上升）vs GK 已實現波動（22 日均，均值回歸）疊圖；視覺上呈現兩者動態脫節，佐證 RQ1 的 NULL。
- `fig2_ddt_vs_drv.png` — Δ當沖比率(t) vs Δlog RV(t+1) 散布圖，無明顯次日關係。

## 限制
1. **RV 為 range-based proxy，非 5-min RV**：無免費 TAIEX intraday；GK/Parkinson 衡量盤中波動、漏隔夜跳空，低估總變異數。RQ2 的當沖→RV leg 只在 GK 下顯著、換 proxy 即消失，凸顯此結果對 RV 估計量選擇敏感（proxy-sensitive），不宜作經濟機制歸因。
2. **當沖比率為大盤 aggregate**，無法分辨哪些個股的當沖驅動哪些波動；個股層級（TWSE 亦有 per-stock 表）是後續方向。
3. **結構性趨勢 / regime**：2014 分階段開放、2017 當沖證交稅減半、2020–21 COVID 零售潮，使當沖比率非定態；已用差分處理，但 regime 異質仍在（子期分析已呈現）。
4. **Granger ≠ 結構因果**：僅為 reduced-form 的預測先行關係。
5. **金額當沖比採 TWSE 官方分母定義**（(市場買+賣)/2）。

## Codex 二審
見本檔末「## Codex review」段（審查 verdict 摘要）。裁決檔 `review_verdict.json` 由 `experiment_gates.py verdict-template` 產生並 pin 住 claim surface 的 sha256。

## 復現
```bash
uv run python experiments/k1724/k1724.py fetch    # 續跑式抓當沖比率 + TWII（首次約需分段）
uv run python experiments/k1724/k1724.py analyze  # 對齊→HAR→OOS→DM→Granger→robustness→圖→JSON
# 或 uv run python experiments/k1724/k1724.py all
```
產物：`k1724.py`、`k1724_results.json`、`fig1_daytrade_vs_rv.png`、`fig2_ddt_vs_drv.png`、`data/`（快取）。

## Codex review

**Round 2 verdict（2026-07-27）：PASS**（round 1 = CONDITIONAL_PASS，缺陷已修並二審確認）。

Codex 摘要：CW 方向與判準正確，p=0.054 的 NULL／邊界措辭適當；Granger maxlag=30、GK lag=16 未撞邊界，三 proxy 雙差分亦支持 RV→DT 穩健、DT→RV 脆弱。round-2 唯一 blocking 缺陷為 README RQ2 表將 RV→DT 的 GK p 值誤寫為 7.9e-05（JSON 實值 ≈0，7.9e-05 屬反方向 DT→RV），**已於本次收件修正為 ≈0**；修正後 Codex 判定可 PASS。無其他會推翻 RQ1(NULL, 邊界) 或 RQ2(RV→DT robust / DT→RV fragile) 的方法論問題。
