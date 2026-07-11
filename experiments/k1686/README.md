# K1686 — Volatility Absorption: Contemporaneous Null 重跑（make-or-break gating）

- **Experiment ID**: `k1686`
- **Status**: PRE-REGISTERED（本節於執行模擬**之前** commit；見 git history）
- **Paper**: `paper/volatility-absorption`（Paper 8）
- **前身**: `experiments/k897/`（GJR-GARCH null simulation，結論 `NULL REJECTED`）
- **觸發**: `paper/volatility-absorption/review_history/fable_deep_review_20260711/README.md` §3-B / §5 P0-1
- **Created**: 2026-07-12（台灣時間）

---

## 1. 動機 — 要關閉的識別缺陷

Paper 8 的核心主張是 **SAR（Shock Amplification Ratio）**

```
SAR(regime) = mean(|r_t| | shock day, regime) / mean(|r_t| | normal day, regime)
```

隨 VIX regime 上升而**遞減**（實證 calm→high decline = 0.8165），且 K897 的 GJR-GARCH null 模擬顯示此
decline 落在 95% null 區間之外（sim mean 0.1734、95% CI [−0.2811, 0.5575]、5/5 regimes outside CI）
→ 結論 `NULL REJECTED`：「absorption 是超越 GARCH 機械效應的真實現象」。

**缺陷（fable deep review P0-1，本實驗要檢定的對象）**：

K897 的模擬中，day-t 的 vol proxy 用 `h[t]`（`k897_sar_null_simulation.py:269-278`）。在 GJR 遞迴下

```
h[t] = ω + (α + γ·1{ε_{t-1}<0})·ε_{t-1}² + β·h[t-1]
```

`h[t]` 是 **F_{t−1}-可測**的（在 t−1 收盤就已算得出），**完全不對 r_t 反應**。於是模擬的
`Δproxy[t] = √h[t] − √h[t-1]` 由 `ε_{t-1}` 驅動 —— 「shock day」被標在**大跌的隔天**，而不是大跌當天。
shock 旗標與當日 innovation `z_t` 統計獨立。

但實證端的 `ΔVIX_t = VIX_t − VIX_{t-1}` 中，`VIX_t` 是**當日收盤**的 implied vol，**與 r_t 同期共動**
（崩盤當天 VIX 同步暴漲）—— shock day 就是大跌當天。

**後果**：實證 SAR 的分子（shock 日 |r_t|）被同期共動機械性拉高，模擬 SAR 的分子沒有。直接寫在 K897 結果裡：
模擬 SAR 水準 ≈ 1.01–1.23，實證 ≈ 2.33–3.16。**null 世界的 shock 定義根本抓不到當日大波動**，
於是「empirical decline 遠大於 null」有可能只是這個口徑錯配的 artifact，不是真實的 absorption。

**這是 make-or-break**：若在同期化 null 下 decline 落回 null 區間內，Paper 8 的核心識別即關閉。

---

## 2. 修正 — 與 K897 的逐項 diff

**唯一的實質改動是 vol proxy 的 timing**。其餘（GARCH params、seed 集、路徑數、路徑長度、SAR 公式、
regime 切點）全部維持不變，使任何結果差異都能 100% 歸因於 timing 修正。

| 項目 | K897（舊） | K1686（本實驗） | 理由 |
|---|---|---|---|
| **day-t vol proxy** | `√h[t] · √252` | **`√h[t+1] · √252`** | `h[t+1]` 是觀測到 `r_t`/`ε_t` **之後**才算得出的 GARCH forecast（F_t-可測），這才是「收盤 VIX 反映當日資訊」的正確類比 |
| **shock 定義** | `\|√h[t] − √h[t-1]\|·√252 > 2`（由 ε_{t-1} 驅動 → 標在大跌**隔天**） | `\|√h[t+1] − √h[t]\|·√252 > 2`（由 ε_t 驅動 → 標在大跌**當天**） | 與 `\|ΔVIX_t\| > 2` 同期化 |
| **regime 分類的 vol level** | `√h[t]·√252` | `√h[t+1]·√252`（同一 proxy，口徑一致） | 實證用同期的 `VIX_t` 分 regime，模擬必須同口徑 |
| **h 遞迴長度** | `h[0..n-1]` | `h[0..n]`（多算 1 步；`h[n]` 只需 `ε_{n-1}`，已存在） | 使 `h[t+1]` 在 t = n−1 仍有定義。**不用 padding / 複製尾值** |
| GARCH params | 見下表 | **完全相同**（沿用 K897 fitted 值） | 保持 null DGP 不變 |
| Seeds | `RandomState(seed)`, seed = 0..9999 | **完全相同** | 同 seed + 同 `n_obs` + 同 params ⇒ 模擬報酬路徑 `r` **逐點相同**，只有 proxy 定義不同 |
| n_paths × n_obs | 10,000 × 5,000 | **完全相同** | 同上 |
| 實證資料 | **live yfinance 下載**（不可重現） | **pinned CSV**：`paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv` | 修 review P1-3：K897 實證端未走 pinned snapshot，與論文 snapshot-pinning 原則不一致 |
| z-score | `(emp − mean) / (std/√n)` → z=1967 這類荒謬值（review 抓到的 bug） | `(emp − mean) / std`（= 標準化距離）**+ 直接 Monte-Carlo 經驗 p 值**（primary，無分佈假設） | `std/√n` 是「模擬均值的 SE」，不是實證統計量的 SE。修 review §3-B (b) |
| percentile 變體 | **silently failed**（5/5 regime `n_valid_sims=0`，JSON 留著但論文未揭露） | 重新實作為 **frequency-matched null**（見 §4 變體 B），並強制驗證 `n_valid_sims > 0` | 修 review §3-B (a) |

**沿用的 GARCH params**（K897 fitted，GJR-GARCH(1,1)-t on SPY 2006–2026）：

| μ | ar1 | ω | α | γ | β | ν | persistence |
|---|---|---|---|---|---|---|---|
| 0.07641014 | 0.0 | 0.02218877 | **0.0** | 0.24422367 | 0.85941473 | 5.6478791 | 0.98152657 |

> ⚠️ `α = 0`：fitted GJR 中正報酬對條件變異數**零衝擊**，只有負報酬經 γ 進入。這使
> 同期化 null 的 `Δproxy` 在正報酬日必為負（純均值回歸衰減）。這個不對稱性對 sign-split
> 變體（§4 D）的解讀至關重要，結果段會明確處理。

**內建對照組（本實驗最重要的設計）**：腳本在**同一組模擬路徑**上同時計算 K897 的 lagged-proxy SAR
（replication arm）。若該 arm 重現 K897 的 `sim_mean_decline = 0.1734` / CI [−0.2811, 0.5575]，
即證明我們的重實作忠實，**因此同期化 arm 的任何差異必然、且僅僅來自 timing 修正**。
此為內建 placebo，不是額外裝飾。

---

## 3. 事前判定規則（PRE-REGISTERED — 在跑任何模擬之前寫死）

**主要統計量**：`decline = SAR(calm, <15) − SAR(high, 25–30)`，實證值 **0.8165**
（pinned snapshot；K897 live-yf 值 0.8162，K716/Table 3 rounded 值 0.84 —— 三者一致）。

**主規格（PRIMARY）**：變體 A = 同期化 proxy + fixed threshold（regime 15/20/25/30，shock `|Δproxy| > 2`）
—— 因為論文 Table 3 的實證端正是此口徑。

**判定**（以變體 A 的模擬 decline 分佈之 95% percentile 區間為準）：

- **empirical decline 仍落在 95% null 區間之外** → 識別**成立且強化**。K897 的結論在更嚴格的同期化口徑下
  依然成立，論文顯著升級（absorption 不是同期共動的機械 artifact）。
- **empirical decline 落入 95% null 區間之內** → absorption 主張**降級**為「fixed-threshold 選樣 ×
  同期共動的機械分解」。論文走**重新框架**路線（deep review §6 hard gate）：改寫為 measurement note
  投 FRL，或把 SAR/null-simulation 方法併入其他 VIX 論文。**本篇不得再以「absorption 是超越機械效應的
  現象」為主張投稿。**

**輔助判定**（不改變上述主判定，只用於刻畫結果的穩健性）：4 個變體（A/B/C/D）+ 補充變體 E 的結論若彼此
衝突，**如實報告衝突並說明機制**，不挑對自己有利的變體當 headline。

**禁止事項（研究誠實）**：不得在看到結果後調整 threshold、seed、regime 切點、樣本期間或規格，
把結果推回想要的方向。無論落點為何，README 與 results JSON 都如實記錄。Null result 是結果，不是失敗。

---

## 4. 變體規格（口徑一致性：實證 vs 模擬逐欄對齊）

所有變體的 SAR 公式相同；差別只在 shock 定義與 regime 分類。模擬端一律用同期化 proxy
`P_t = √h[t+1]·√252`；實證端對應 `VIX_t`。

| 變體 | regime 分類 | shock 定義（實證） | shock 定義（模擬） | 目的 |
|---|---|---|---|---|
| **A（PRIMARY）** | `VIX_t` / `P_t` ∈ {<15, 15–20, 20–25, 25–30, ≥30} | `\|ΔVIX_t\| > 2` | `\|ΔP_t\| > 2` | 與論文 Table 3 完全同口徑；主判定 |
| **B** | 頻率匹配：模擬用**每條路徑自己**的 `P` 分位數，對齊實證 VIX 各 regime 的**佔比** | `\|ΔVIX_t\| >` 第 (1−s) 分位 | `\|ΔP_t\| >` 該路徑第 (1−s) 分位 | VIX 含 variance risk premium ⇒ 水準系統性高於物理條件波動度，fixed threshold 會讓模擬過度佔用 calm regime。B 讓 **shock rate 與 regime 佔比兩者都按建構匹配** |
| **C** | 同 A | `\|ΔVIX_t\| / VIX_{t-1} > q` | `\|ΔP_t\| / P_{t-1} > q`（**同一個 q**，無單位） | VIX=12 時 ΔVIX=2 是 17% 的相對變動，VIX=40 時只有 5% —— 固定加法門檻使高 regime 的「shock」相對更弱，SAR 遞減可能有一部分是選樣機械效應。`q` 取實證 `\|ΔVIX\|/VIX_{t-1}` 中對應 s 的分位數 |
| **D** | 同 A | 分開報 `ΔVIX_t > +2`（vol 上升）與 `ΔVIX_t < −2`（vol 下降） | 同左（對 `ΔP_t`） | `\|ΔVIX\|>2` 把恐慌暴漲日與 relief-rally 日混進同一個「fear shock」桶。檢查 absorption 是否只來自單邊 |
| **E（補充）** | **`VIX_{t-1}` / `P_{t-1}`**（ambient fear，落後一期） | `\|ΔVIX_t\| > 2` | `\|ΔP_t\| > 2` | A–D 的 regime 分類本身是 `r_t` 的函數（大跌 → VIX_t 高 → 被分進高 regime），存在內生分選。E 用**衝擊前的 ambient 恐懼水準**分 regime，這也更貼近論文「ambient fear 調節反應」的故事 |

其中 `s` = 實證 `|ΔVIX_t| > 2` 的 shock rate = **0.1508**（768 / 5092）。

**共用規則**：
- normal day = 非 shock day（同 regime 內）；sign-split（D）的分母沿用同一個 normal day 集合。
- 一個 regime 的 SAR 需 `n_shock > 5` 且 `n_normal > 5` 才有效，否則記 `NaN`（沿用 K897）。
- decline 需 calm 與 high 兩個 regime 的 SAR 皆有效。
- 每個變體都會報 **regime 佔比與 shock rate 的實證 vs 模擬對照**（口徑一致性診斷）。

**推論**：
- **主判定**：實證 decline 是否落在模擬 decline 的 **95% percentile 區間** [2.5%, 97.5%] 內。
- **Monte-Carlo 經驗 p 值**（primary，無分佈假設）：`p = 2 · min(P(sim ≥ emp), P(sim ≤ emp))`，下限 `1/n_valid`。
- 標準化距離 `z = (emp − sim_mean) / sim_std`（修 K897 的 z bug）。
- `frac_sim_above_empirical`（K897 唯一誠實的統計量，保留）。

---

## 5. 資料與可重現性

- **實證**：`paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv`（pinned snapshot）。
  SPY 用 `spy_adj_close`（含息調整，等同 `yf.download` 的 `auto_adjust=True`）、VIX 用 `vix_close`。
  期間 2006-01-05 → 2026-04-02，n = 5,092。
  **驗證**：此 pinned 資料重現 K897 的 live-yf 實證 SAR 至小數點後 3 位
  （3.1490/2.7723/2.3770/2.3325/2.4514 vs K897 的 3.1487/2.7723/2.3770/2.3325/2.4514），
  decline 0.8165 vs 0.8162 —— 實證端 pin 住而不失與 K897/K716/Table 3 的連續性。
- **Seed spec**：`np.random.RandomState(seed)`，`seed = 0, 1, …, 9999`（與 K897 逐一相同）。
  每條路徑 `z = rng.standard_t(df=ν, size=5000) · √((ν−2)/ν)`。因 `n_obs` 與抽樣呼叫順序皆與 K897 相同，
  innovation 序列 **bit-identical**；`h[n]` 只需 `ε_{n-1}`，不需額外抽樣。
- **執行**：`uv run python experiments/k1686/k1686_contemporaneous_null.py`

---

## 6. 結果

### 6.0 前置驗證：K897 replication arm 完全命中

| | sim_mean_decline | sim_std_decline | 95% CI |
|---|---|---|---|
| K897 published | 0.1734 | 0.2105 | [−0.2811, 0.5575] |
| **本實驗 lagged arm** | **0.1734** | **0.2105** | **[−0.2811, 0.5575]** |

各 regime 的模擬 SAR 水準亦逐一吻合（K897 published 1.2325 / 1.0119 / 1.0120 / 1.0591 / 1.1795）。
**重實作忠實 ⇒ 同期化 arm 的任何差異，必然、且僅僅來自 vol proxy 的 timing。** 這是本實驗的內建 placebo。

### 6.1 主結果：五個變體

實證 decline 一律為 `SAR(calm) − SAR(high 25–30)`。

| 變體 | 實證 decline | Null mean ± sd | Null 95% CI | 落在 CI 內？ | MC p |
|---|---|---|---|---|---|
| K897 lagged arm（**有缺陷的舊 null**） | 0.8165 | 0.1734 ± 0.2105 | [−0.2811, 0.5575] | **否** | 0.0004 |
| **A — PRIMARY（同期化 + fixed）** | **0.8165** | **0.6190 ± 0.2487** | **[0.0824, 1.0596]** | **是** | **0.410** |
| B — frequency-matched | 0.8165 | −0.0035 ± 0.1578 | [−0.3115, 0.3096] | 否 | 0.0002 |
| C — relative threshold | **0.3397** | −0.1877 ± 0.2159 | [−0.6543, 0.2006] | 否 | 0.0064 |
| D — sign-split：vol **UP** shocks | **−0.1192** | 0.0904 ± 0.2660 | [−0.4666, 0.5725] | 是 | 0.394 |
| D — sign-split：vol **DOWN** shocks | +1.3368 | *null 結構上不存在*（見 6.4） | — | — | — |
| E — ambient regime | 1.4643 | 0.9527 ± 0.3537 | [0.1956, 1.5830] | 是 | 0.117 |
| F — VRP 校準（**事後**加，見 6.6） | 0.8165 | *calm cell 無法評估* | — | — | — |
| G — 雙重修正（**事後**加，見 6.6） | 0.5831 | −0.3573 ± 0.4111 | [−1.2832, 0.3134] | 否 | 0.0037 |

**事前規則的主判定**：變體 A 的實證 decline **落在 null 95% 區間內**（MC p = 0.41）→ 依 §3 字面規則，
absorption 主張降級。**K897 的 `NULL REJECTED` 確實不能通過 timing 修正**（同 seed 同 params 下，
null 的 SAR 水準由 1.0–1.2 升到 1.6–2.4，decline 由 0.1734 升到 0.619）。

> ⚠️ **但我必須自己拆穿變體 A**（獨立審查 H1 指出，我確認屬實）：A 的 null 之所以生得出 0.619 的
> decline，是因為**純衰減在高波動區跨過固定 2 點門檻**（§6.3：null 在 crisis 把 82% 的日子標成
> shock，實證只有 54%）—— 這是**資料裡沒有的機制**。所以 A 的「不拒絕」是**兩個 artifact 互相抵消**，
> 不是強證據。三個修正過的 null（B / C / G）**全部拒絕**。
>
> **結論：null 比較本身是 inconclusive —— 兩個方向都不能宣稱。**
> 真正決定論文命運的是下一節那個**不需要 null** 的證據。

### 6.2 決定性的實證事實（**不需要任何 null 模型**）

把「shock」按 ΔVIX 的**正負號**拆開之後：

| regime | SAR（pooled, 論文定義） | SAR（**vol UP**, 真正的恐慌衝擊） | SAR（**vol DOWN**, relief rally） | n↑ | n↓ | n_normal |
|---|---|---|---|---|---|---|
| calm (<15) | **3.1490** | 2.3764 | **3.4710** | **10** | 24 | 1721 |
| normal (15–20) | 2.7723 | 2.8516 | 2.7002 | 80 | 88 | 1403 |
| elevated (20–25) | 2.3770 | 2.4173 | 2.3144 | 115 | 74 | 696 |
| high (25–30) | 2.3325 | 2.4956 | 2.1342 | 73 | 60 | 299 |
| crisis (≥30) | 2.4514 | 2.6794 | 2.1870 | 131 | 113 | 205 |
| **decline (calm−high)** | **+0.8165** | **−0.1192** | **+1.3368** | | | |

**把 up-only 那一列單獨看：2.38 → 2.85 → 2.42 → 2.50 → 2.68 —— 這不是遞減，是非單調的鋸齒。**
calm 不但不是最高，反而低於 normal；crisis 又彈回 2.68。**論文所宣稱的「ambient fear 越高、
恐慌衝擊越被吸收」的單調梯度，在真正的恐慌衝擊裡不存在。**

論文 headline 的 0.8165 decline，其**量級**來自 pooled 的 calm 錨點 3.1490 —— 而這一格建立在
**34 個 shock 日**上，其中 **24 日（71%）是 VIX 下跌日**，真正的恐慌衝擊**只有 10 日**。
up-only 的 calm 值（2.3764, n=10）比 pooled 的 3.1490 低了 0.77，差額全部由 down-shock 的
3.4710 貢獻。**pooled decline 的分子端是被 relief rally 灌高的。**

**機制**：VIX = 13 時掉 2 點（→ 11）是罕見的大幅 relief，伴隨大漲（|r| 大）；VIX = 27 時掉 2 點只是
例行均值回歸，伴隨普通報酬。於是 down-shock 的 SAR 從 calm 的 3.471 一路掉到 high 的 2.134
（down-decline = **+1.337**，是 pooled 0.8165 的 1.6 倍）。**這是 signed-composition 的選樣效應。**

**Bootstrap（n=10 那格不能用點估計就下定論 — 獨立審查 H3）**：對 calm/high 的 up-shock 與 normal cell
做 10,000 次 bootstrap（seed 20260712）：

| 統計量 | 點估計 | Bootstrap 95% CI |
|---|---|---|
| `SAR_up(calm)` | 2.3777 | [1.8617, 3.0246] |
| **up-only decline（calm−high）** | **−0.1226** | **[−0.7289, 0.5828]** |

這個 CI **同時做到兩件事**：

1. **包含 0** → 在真正的恐慌衝擊中，**無法建立任何 absorption 梯度**。
2. **上界 0.5828 < pooled headline 0.8165** → **headline 顯著大於恐慌衝擊所能解釋的任何值**。

**所以「論文的 headline decline 不是恐慌衝擊造成的」在統計上站得住，而且完全不依賴任何 null 模型
—— 它免疫於 §6.4 全部的 null 校準爭議。**

> **誠實邊界**：這**不等於**「恐慌衝擊完全沒有任何遞減」。normal→high leg 上 up-only 仍有 +0.356
> 且落在 null 外（§6.6）；crisis 又反彈到 2.6794。正確的陳述是：**恐慌衝擊的 SAR 沒有論文宣稱的
> 單調 absorption 梯度，且 headline 的量級不是它給的。** normal→high 之間的殘留值得後續研究，
> 但那不是論文現在寫的東西。

### 6.3 機制診斷：固定門檻在高波動區被「衰減」灌爆

| | calm | normal | elevated | high | crisis |
|---|---|---|---|---|---|
| within-regime shock rate（實證 VIX） | 0.019 | 0.107 | 0.214 | 0.308 | 0.543 |
| within-regime shock rate（null，變體 A） | 0.036 | 0.152 | 0.195 | **0.485** | **0.823** |
| regime 佔比（實證） | 0.345 | 0.309 | 0.174 | 0.085 | 0.088 |
| regime 佔比（null，變體 A） | **0.766** | 0.120 | 0.050 | 0.024 | 0.039 |

固定的 ±2 絕對門檻套在均值回歸的波動度上，**水準越高越容易被跨過** —— 因為衰減項本身一天就走超過
2 個年化波動點。在 null 的 crisis regime，**82% 的日子被標成「shock」**，shock 桶被普通日灌爆，
SAR 被推向 1 → **憑空製造出 decline**。實證資料有同一個機制（0.019 → 0.543），只是程度較輕。

同時暴露變體 A 的 null 校準弱點：VIX 帶 variance risk premium，水準系統性高於物理條件波動度，
於是 null 的 calm regime 佔了 **76.6%** 的日子（實證只有 34.5%）。**這是繼承自 K897 的規格弱點，
如實揭露而非隱藏。**（變體 B 按建構消除此問題。）

### 6.4 變體衝突的誠實處理

B 與 C **拒絕** null，表面上與 A 相反。逐項說明，不挑對自己有利的當 headline：

- **B（frequency-matched）**：null decline ≈ 0，實證 0.8165 在外 (p=0.0002)。**但 B 的 null 在 5/5 個
  regime 都重現不了實證的 SAR 水準**（null ≈ 1.8 平坦，實證 2.3–3.1，全部 outside CI）。一個在每個
  regime 都對不上水準的 null，不是判斷「差分」的可靠尺。B 真正說的是：「把佔比對齊之後，GARCH 生不出
  這個 pooled decline」—— 而 §6.2 已經證明這個 pooled decline 的來源是 signed composition，**不是 absorption**。
- **C（relative threshold）**：光是把絕對門檻換成相對門檻，**實證 decline 就從 0.8165 掉到 0.3397
  （蒸發 58%）**。這直接量化了 deep review §3-C 的疑慮：headline 的多數來自固定門檻的選樣效應。
- **E（ambient regime）**：實證 1.4643 落在 null [0.1956, 1.5830] 內（p=0.117）—— 與 A 同向，識別關閉。
- **D_down 的 null 結構上不存在**（calm/normal/elevated 三個 regime `n_valid_sims = 0`）：這**不是 bug，
  是可以解析證明的 null 性質**。因為 fitted `α = 0`，正報酬對次日變異數零貢獻，null 一天內能跌最多的
  情況就是純衰減 `h_next = ω + β·h`。解

  ```
  (√(ω + β·h) − √h) · √252 = −2      ⇒   P* = 28.84（年化波動點）
  ```

  **在 P < 28.84 以下，這個 null 根本不可能出現「vol 下降 2 點」的日子** —— 也就是整個
  calm / normal / elevated regime。（腳本 `decay_only_drop_level()` 計算，寫入 JSON
  `down_shock_impossibility`。）

  這件事比「n_valid_sims = 0」嚴重得多：**實證的 decline 是 100% 由 vol 下降日撐起的（§6.2），
  而 null 在那些 regime 連這個通道都不存在。** 換言之，在下跌側，null 與實證**根本不是在量同一種事件**。
  這也解釋了為什麼 B / C 會「拒絕 null」—— 它們拒絕的是「GARCH 沒有 relief-rally 通道」，
  不是「市場存在 absorption」。

  （K897 讓一個變體 silently 回傳 0 valid sims 卻完全不揭露；此處明確揭露、解析證明、並寫進 JSON。）

**§6.4 的收斂結論**：**null 比較是 inconclusive 的 —— 兩個方向都不能宣稱。**
「這只是 GARCH 機械效應」沒被證實（B/C/G 拒絕）；「這是 absorption」也沒被證實
（A 的不拒絕是 artifact 互抵；且 B/C/G 拒絕的是「GARCH 沒有 relief-rally 通道」）。
**論文的命運由 §6.2 那個不需要 null 的證據決定，不由這裡決定。**

---

## 6.5 已知限制（如實列出）

1. **同期化在 α=0 下是「不對稱」的**（獨立審查 M1，我確認屬實且原本漏了）：因為 fitted `α = 0`，
   在**正報酬日** `h[t+1] = ω + β·h[t]` —— **完全不含 `ε_t²`**。所以修正後的 proxy 只在**下跌日**
   真正對 `r_t` 同期反應；上漲日它仍然是 F_{t−1}-可測的。這是繼承自 K897 的 fit，不是本實驗引入，
   但它意味著變體 A–G 的「同期性」只做到一半，**必須明講而不是默認**。
2. **Null 的 DGP 是特定的 GJR-GARCH-t**。它對 `r_t` 的反應是該函數形式；VIX 的實際反應更陡、更凸，
   且有 relief-rally 通道（§6.4）。**以實證 ΔVIX–return 彈性校準的 implied-vol null 是最有價值的
   後續工作** —— 在它存在之前，沒有任何 null 檢定能對下跌側發言。
3. **calm regime 的 up-shock cell 只有 n = 10**。已用 bootstrap 量化（§6.2），不以點估計下定論。
4. **crisis 上界**：本實驗模擬端用 `1e6`（與 K897 模擬端相同）；實證端 K897 用 200，本實驗用 `1e6`
   —— VIX 史上最高約 85，無實質差異。

---

## 6.6 事後追加的兩個變體（明確標註：**非** pre-registered）

獨立審查（M2）指出 B / C / E **每個只修一個缺陷**，缺一個「同時修多個」的 null。我補了兩個。
**兩者都是看到結果之後才加的，因此不得用來取代事前規則的主判定** —— 只用來刻畫穩健性，
且無論結果偏向哪邊都照實報。

| 變體 | 設計 | 結果 |
|---|---|---|
| **F — VRP 校準** | 用實證擬合的仿射映射 `VIX ≈ 7.967 + 0.691 · P` 把 null 的 proxy 搬到 VIX 的尺度，**再**套論文的原始固定門檻。這是對「A 的 null 水準校準不良」最直接的回應 | **calm cell 無法評估**。因為 b = 0.691 < 1，映射在修正 level 的同時**壓縮了日增量** —— VIX 尺度上 2 點的移動，需要 null 自身單位的 \|ΔP\| > 2.89，calm 水準下幾乎不發生（null 整體 shock rate 崩到 0.060，實證 0.151）。**可評估的 normal→high leg：實證 0.4398 落在 null [−0.2916, 0.4561] 內（p=0.061）** |
| **G — 雙重修正** | ambient regime（殺掉 regime 內生分選）**＋** relative threshold（殺掉固定門檻選樣）—— 審查要求的「最外科手術式」null | 實證 0.5831 vs null [−1.2832, 0.3134] → **拒絕**（p=0.0037） |

**F 失敗本身是一個發現，不是 bug**：**沒有任何單一仿射校準能讓 GARCH proxy 同時對上 VIX 的
level 與 increment 尺度** —— 修好一個就弄壞另一個。**這個統計量根本不存在「校準不變」的 null。**
這正是 SAR 設計最深的問題，也是為什麼 §6.4 的 null 比較註定 inconclusive。
（K897 讓失敗的變體 silently 消失；此處明確揭露、解釋成因、並補一條可評估的 leg。）

### 次要 leg（`SAR(normal) − SAR(high)`，因為 F 的 calm cell 不可評估）

| 變體 | 實證 | Null 95% CI | 落在 CI 內？ | MC p |
|---|---|---|---|---|
| A | 0.4398 | [−0.2850, 0.7294] | 是 | 0.520 |
| **F（VRP 校準）** | **0.4398** | **[−0.2916, 0.4561]** | **是** | 0.061 |
| E | 0.6230 | [−0.1115, 1.4286] | 是 | 0.792 |
| B | 0.4398 | [−0.2756, 0.2980] | 否 | 0.0034 |
| C | 0.4344 | [−0.6171, 0.2960] | 否 | 0.0078 |
| D_up | 0.3560 | [−0.8281, 0.2486] | 否 | 0.015 |

次要 leg 上同樣是分裂的（A / E / F 不拒絕；B / C / D_up 拒絕）—— **再次確認 null 比較不能定案。**

---

## 7. Verdict

# 🔴 ABSORPTION CLAIM NOT SUPPORTED

三個發現，依「能承受多少重量」排序：

### (1) 不需要任何 null 模型 — 決定性

論文的**機制**不是驅動它的統計量的東西。把 shock 按 VIX 移動的**正負號**拆開：

- pooled decline = **0.8165**（論文 headline）
- 真正的**恐慌衝擊**（ΔVIX > +2）decline = **−0.1226**，bootstrap 95% CI **[−0.7289, 0.5828]**
  → **包含 0**（建立不了 absorption 梯度）**且上界低於 0.8165**（headline 顯著大於恐慌衝擊能解釋的量）
- decline 住在 **relief rally**（ΔVIX < −2）裡：**+1.3368**
- 決定 headline 量級的 calm 錨點：**10 個真恐慌日 vs 24 個 relief 日**

**「ambient fear 越高、恐慌衝擊越被吸收」不是 SAR decline 所顯示的東西。**
此結論**不依賴任何 null 模型**，因此免疫於 §6.4 的全部校準爭議。

### (2) Null 比較本身 inconclusive — 兩個方向都不能宣稱

- 事前規則的主判定（變體 A）**不拒絕** null（0.8165 落在 [0.0824, 1.0596] 內，p = 0.41）→
  依 §3 字面規則，absorption 主張降級。**照實報告。**
- **但 A 的 null 是靠「純衰減跨過固定門檻」賺到它的 0.619 decline 的**（§6.3：null 在 crisis 標
  82% 的日子為 shock，實證只有 54%）—— 那是資料裡沒有的機制。**A 的「不拒絕」是兩個 artifact 互抵。**
- 三個修正過的 null（B / C / G）**全部拒絕**。
- ⇒ **「這只是 GARCH 機械效應」沒被證實；「這是 absorption」也沒被證實。**
  而 B/C/G 拒絕的東西，是「GARCH 沒有 relief-rally 通道」（§6.4 的 P\* = 28.84 證明），
  **不是**「市場存在 absorption」。

### (3) 無論如何，K897 的結論不成立

K897 的 `NULL REJECTED` 建立在一個 vol proxy 無法對當日報酬反應的 null 上。在**同 seed、同 params**
下把 proxy 同期化：null 的 SAR 水準由 1.0–1.2 → 1.6–2.4，decline 由 0.1734 → 0.619。
**K897 報告的 margin 大部分是 timing artifact。**

---

### 對論文的處置建議（交主線程裁決）

依 deep review §6 的 **hard gate**（事前承諾）：**本篇不得再以「volatility absorption 是超越機械效應的
現象」為主張投稿。**

但**這不是空手而歸** —— 資料裡有一個**真實、且 GARCH null 生不出來**的規律，只是它不是 absorption：

> **建議重新框架為 measurement note（FRL）**：
> 「**VIX-regime SAR 的遞減是 signed-composition 效應**：它由 relief rally 而非恐慌衝擊驅動，
> 對 shock 門檻的絕對/相對定義極度敏感（換成相對門檻即蒸發 58%），且**沒有校準不變的 GARCH null**
> 可以檢定它（§6.6 F）。」
>
> 這是有內容的正面貢獻：它糾正一個看似合理的現象，並給出可操作的診斷工具組
> （sign-split + relative threshold + contemporaneous null + 機制診斷）。本實驗的 7 個變體
> 已經是這篇 note 的完整實證骨架。

**最有價值的後續研究**（也是唯一能救回 null 檢定的路）：建一個**有 relief-rally 通道**的
implied-vol null（用實證 ΔVIX–return 彈性校準、且在高檔有自己的均值回歸）。在它存在之前，
**沒有任何 null 能對下跌側發言** —— 而下跌側正是整個效應的所在。

### 連帶關閉的 review 項目

- **P0-1**（本實驗）：✅ 完成。結果：absorption 主張不成立；null 比較 inconclusive；K897 verdict 推翻。
- **§3-C sign-split robustness 要求**：✅ 已做（§6.2），且它才是決定性的證據。
- **§3-C relative-threshold 疑慮**：✅ 已量化（headline decline 有 **58%** 來自固定門檻）。
- **P1-3 K897 衛生**：✅ z-score bug 已修（標準化距離 + MC 經驗 p 值，`(b+1)/(n+1)` plug-in）；
  percentile 變體的 silent fail 已重實作並揭露；實證端已改讀 pinned CSV。

---

## 9. 審查紀錄（研究誠實：reviewer source 必須標明）

**Reviewer**：`feature-dev:code-reviewer` subagent（fresh-context 對抗性審查）
**Verdict**：**CONDITIONAL PASS** —— **程式碼零 bug**（masks / 索引 / off-by-one / RNG 決定性 /
推論公式全部確認正確；replication arm 逐位對上 K897），但**指出我的 headline 過度宣稱**。

| 審查發現 | 我的處置 |
|---|---|
| **H1** A 的不拒絕與它自己的 selection artifact 糾纏；B/C 拒絕 → 不能宣稱 CLOSED | **接受**。改寫 verdict 為「null 比較 inconclusive」，並在 §6.1/§6.4 自己拆穿 A |
| **H2** `verdict` 欄只讀變體 A，把衝突埋起來，違反自訂的誠實條款 | **接受**。新增 `variant_disagreement` 欄；verdict 字串現在**自帶**分裂與機制說明 |
| **H3** D_up 的 calm cell 只有 n=10，不能當定論 | **接受**。加 10,000 次 bootstrap（seed 20260712）；CI **[−0.729, 0.583]** —— 反而**強化**了結論（排除 pooled 0.8165） |
| **M1** α=0 使同期化**不對稱**（正報酬日 proxy 仍是 F_{t−1}-可測） | **接受**，原本漏了。寫入 §6.5 限制 1 |
| **M2** 缺「雙重修正」的 null | **接受**。新增變體 **G**（ambient + relative）→ 拒絕 null（p=0.0037），如實報告 |
| **M3** B 過度校準（null 在 5/5 regime 都對不上 SAR 水準） | **同意**，已在 §6.4 說明 |
| **L3** MC p 值下限應用 `(b+1)/(n+1)` 而非 `1/n` | **接受**，已改 |
| **L1** crisis 上界 `1e6` vs K897 的 `200` | 查證：K897 **模擬端**也是 `1e6`（其 L292），僅**實證端**為 200；VIX 史上最高約 85 → 無實質差異。已註於 §6.5 |

> ⚠️ **Codex primary path 未完成（必須揭露）**：依 `.claude/rules/experiments.md`，primary reviewer
> 應為 Codex CLI。本次 **`codex exec` 連續 3 次**（700s / 1500s / 內嵌程式碼版）都在 transport 層
> 被截斷、預算耗盡於重複讀檔，**未產出 verdict**。因此改走規則明列的 **`code-reviewer` subagent
> fallback**。
> **依 K1259 規則：subagent PASS ≠ primary-path Codex PASS。主線程在寫 `knowledge.json` 之前，
> 必須用 Codex 再驗一次。** 本 agent 未寫 knowledge.json（符合規範）。

---

## 8. 檔案

| 檔 | 內容 |
|---|---|
| `k1686_contemporaneous_null.py` | 模擬 + 7 變體（A–G）+ K897 replication arm + 機制診斷 + bootstrap |
| `k1686_contemporaneous_null_results.json` | 全部結果（`seed_spec` / `k897_replication_check` / `variant_disagreement` / **`null_free_evidence`**（決定性）/ `down_shock_impossibility` / `mechanism_diagnostic_*` / `calibration_diagnostics` / `up_shock_bootstrap`） |
| `k1686_null_distributions.png` | 8 格圖：K897 replication arm / A / B / C / D_up null 分佈 + **實證 sign-split（不需 null 的關鍵證據）** + E + 機制診斷。**變體 F / G 只在 JSON 與 README，未進圖**（F 的 calm cell 不可評估，無分佈可畫；G 見 §6.6 表） |

**復現**：`uv run --extra dev python experiments/k1686/k1686_contemporaneous_null.py`
—— 已驗證**逐位元決定性**（連跑兩次 results JSON 的 SHA-1 相同：`3b4809f0…`）。

