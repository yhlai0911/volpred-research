# K1459 — 龐氏結構崩潰數學：承諾報酬、提款率與新人增長的臨界條件

## 動機

Boss 2026-06-07 指令：如果每輪用新本金支付既有投資人的承諾報酬，這種
結構可以撐幾輪，臨界人數是多少，請做完整分析。

這題的重點不是抓詐騙名單，而是把「龐氏一定會崩」這句話寫成可以驗算的
數學。K1459 用最簡單、可重現的離散時間模型回答三件事：

1. 新進人數的**臨界成長率**是多少。
2. 在給定承諾報酬 `r`、提款率 `w`、初始人數 `N0` 下，每輪要補多少新人。
3. 如果實際新人增長低於臨界值，現金池大約會在第幾輪破產。

## 前置檢查

- `docs/error_log.md` 已讀
- `storage/memory/knowledge.json` / `experiment_experiences.json` 已搜，無直接同題
- `scripts/check_arc_dedup.py --title ...`：無撞題

## 文獻與定位

這類主題的直接數學文獻不多。K1459 的定位是：用最小可解模型，把「成長率
不夠就崩」寫成解析式，再用 deterministic + stochastic stress test 補有限
輪數的直觀。

參考文獻：

1. Parodi (2026), *From Ponzi Schemes to Benign Investment Dynamics*：
   用差分方程寫投資人口與資本動態，明確指出 classical Ponzi dynamics
   會崩潰。
2. Bartoletti et al. (2017), *Dissecting Ponzi Schemes on Ethereum*：
   雖是 crypto 場景，但核心機制相同：回報來自後進者資金，當新流入轉弱，
   結構會 implodes。
3. SEC OIG (2009), *Investigation of Failure of the SEC to Uncover Bernard
   Madoff's Ponzi Scheme*：提供 Madoff 作為歷史案例背景。
4. Reuters/Time (2015) 對 Picard trustee 數字的報導：Madoff net loss 約
   `17.5B USD`，可用作規模感校準。

## 模型

### 狀態變數

- `A_t`：第 `t` 輪開始時仍在場的 active investors（每人本金標準化為 1）
- `R_t`：第 `t` 輪開始時現金池 reserve
- `E_t`：第 `t` 輪新進投資人數
- `r`：每輪承諾報酬率
- `w`：每輪提款/退出比例
- `N0`：初始投資人數

### 單輪現金流

每輪對既有 active investors 要支付：

- 報酬：`r * A_{t-1}`
- 退出本金：`w * A_{t-1}`

所以本輪若不想進一步消耗 reserve，至少要有：

`E_t^flat = (r + w) * A_{t-1}`

這是 **flat-reserve 臨界新人數**。

### Active investors 遞推

支付後留下 `(1-w) * A_{t-1}` 人，再加新進者 `E_t`：

`A_t = (1 - w) * A_{t-1} + E_t`

若每輪都剛好補到 `E_t^flat`，則：

`A_t = (1 + r) * A_{t-1}`

因此：

- `A_t = N0 * (1 + r)^t`
- `E_t^flat = (r + w) * N0 * (1 + r)^(t-1)`

這是本實驗最核心的解析結論。

## 解析結論

### 1. 長期臨界條件：`g* = r`

若實際新進人數走勢是 `E_t = E_1 * (1 + g)^(t-1)`，則長期能否不崩，取決於
新進人數成長率 `g` 是否至少跟得上承諾報酬率 `r`：

- `g > r`：長期可維持/擴張
- `g = r`：臨界邊界
- `g < r`：遲早崩潰

**關鍵點**：`w` 會影響每輪需要補的**水位**，但不改變長期臨界斜率。
提款率提高會讓你更快破，但不會把 asymptotic critical growth 從 `r`
改成別的數。

### 2. 臨界人數公式

若一開始有 `N0` 人，且每輪都只求「不進一步吃 reserve」：

- 第 `t` 輪所需新人數：
  `E_t^flat = (r + w) * N0 * (1 + r)^(t-1)`
- 前 `T` 輪累積參與人數：
  `C_T = N0 * [1 + ((r + w) / r) * ((1 + r)^T - 1)]`

這表示「每輪報酬越高」，需要的不是線性增員，而是幾何級數。

## 實驗設計

### Deterministic 路徑

給定 `(r, g, w, N0)`，設定：

- `R_0 = N0`
- `A_0 = N0`
- `E_1 = (r + w) * N0`
- `E_t = E_1 * (1 + g)^(t-1)`

然後遞推：

- `R_t = R_{t-1} + E_t - (r + w) * A_{t-1}`
- `A_t = (1 - w) * A_{t-1} + E_t`

當 `R_t < 0`，定義為 collapse。

### Monte Carlo stress

不是只看一條平滑路徑。K1459 再加一層離散隨機化：

- 新進人數：`Poisson(E_t)`
- 退出人數：`Binomial(A_{t-1}, w)`

固定 `seed=42`，每組參數跑 `400` 次，估 collapse probability。

### 參數格點

- `r ∈ {0.5%, 1%, 2%, 5%, 10%}`
- `g ∈ {0%, 0.5%, 1%, 1.5%, 2%, 3%, 5%, 8%, 10%}`
- `w ∈ {0%, 1%, 2%, 5%, 10%}`
- horizon = 120 輪

## 主要結果

### A. 三個代表情境

| Scenario | r | g | w | Deterministic 結果 |
|---|---:|---:|---:|---|
| stable_1pct | 1% | 2% | 1% | 存活至 120 輪 |
| critical_1pct | 1% | 1% | 2% | 臨界邊界，deterministic 120 輪仍撐住，reserve 幾乎原地踏步 |
| aggressive_10pct | 10% | 5% | 5% | 第 17 輪崩潰；Monte Carlo collapse prob = 100% |

### B. 核心數學直觀

1. **臨界成長率不是 `r + w`，而是 `r`**  
   `w` 放大的是每輪補洞規模，不是長期幾何斜率。

2. **提款率仍然很致命**  
   同樣 `g = r`，高 `w` 的路徑更脆弱，因為 reserve buffer 更容易被抽乾。

3. **高承諾報酬會爆炸式推高頭數需求**  
   例如 `r = 10%` 時，active base 每輪按 `1.10^t` 擴張；新人需求不是
   多一點，而是越來越快失控。

### C. 歷史規模校準

#### Madoff 尺度（示意，不是結案重建）

若 outstanding capital = `17.5B USD`，承諾平滑月報酬 `1%`：

- `w = 0%`：每月光報酬就要 `175M USD` 新錢
- `w = 2%`：每月要 `525M USD`
- `w = 5%`：每月要 `1.05B USD`

這還沒算 panic redemption 的非線性加速。

#### Charles Ponzi 風格

若每輪承諾 `50%`，即使 `w = 0`，第 10 輪也需要：

- 單輪新人數 ≈ 初始人數的 `19.2x`
- 累積參與人數 ≈ 初始人數的 `57.7x`

若 `w > 0`，水位更高。

## 檔案

- `k1459_ponzi_collapse_math.py`：主腳本
- `k1459_results.json`：結果與格點掃描
- `k1459_collapse_heatmaps.png`：deterministic collapse round + MC collapse prob
- `k1459_scenario_entrants.png`：三種情境的新進人數路徑
- `k1459_scenario_reserves.png`：三種情境的 reserve path
- `article_draft.md`：一般讀者版本草稿

## Caveats

1. 這是**結構模型**，不是任何單一案件的 forensic reconstruction。
2. 每位投資人本金標準化為 1；異質本金、分層費率、operator 自留資金未納入。
3. Madoff/Charles Ponzi 的歷史例子只用來給規模直觀，不是校準參數後的擬合。
4. Monte Carlo 用 Poisson/Binomial 是 stress-test，不是假裝知道真實招募/提領分布。

## Run

```bash
uv run python experiments/k1459_ponzi_collapse_math/k1459_ponzi_collapse_math.py
```
