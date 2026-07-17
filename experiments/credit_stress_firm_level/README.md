# credit_stress_firm_level — Firm-level 信用壓力 → 高槓桿 AI 股波動率（控制 VIX）

**Verdict: NULL** — 控制 VIX 後，高槓桿 AI 基礎設施股的 equity vol **並未**比低槓桿 hyperscaler
對信用市場壓力更敏感。Firm-level 分組差異亦無顯著增量。VIX sufficiency 延伸到 firm-level。

- **來源**：老闆 2026-07-16 Telegram msg877（財經捕手 SpaceX 破發文，high-leverage AI 股信用壓力主張）
- **執行**：VolPred autonomous research agent（worktree `dispatch-slot-1-79726798-credit-firm`）
- **樣本**：2015-01-02 .. 2026-07-17（含 2020 COVID + 2022 兩次空頭）
- **資料**：yfinance（個股 + HYG/LQD/^VIX）+ FRED OAS（短樣本 secondary）— 全部免費

---

## 1. 動機與差異化（為什麼這題值得再做一次）

Aggregate 版本的信用→波動率早已做過且**全 NULL**。開工前先 grep `storage/memory/knowledge.json`
讀了以下先前教訓（原文摘錄）：

| 先前 K | 讀到什麼 |
|---|---|
| **K872** | FRED HY OAS 對 fwd vol raw r=0.55，但 HY-VIX corr=0.77（冗餘）；**控制 VIX 後 delta-R²=0.0003**，OOS DM t=0.57 NS。VIX sufficiency confirmed。係數每 5 年翻號（4/4 flips）。 |
| **T14** | VIX alone R²=0.318；加 credit+yield 僅 **+1.6% incremental R²**（F 顯著但 econ trivial）；credit overlay 反降 Sharpe。VIX 是 sufficient statistic。 |
| **K1621** | EM sovereign-credit vol proxies **不 lead** EM equity vol（daily CCF 峰在 lag 0 = 同期共同因子）；pooled DM-HLN t=0.41 NS。VIX-regime split 有 *suggestive but not-Harvey-sig* 的 stress sign flip（當假說報告，非結論）。 |
| **K1529** | FOMC-window credit stress NULL with free ETF proxies；明說 **"firm-level or intraday credit-spread data required to reopen"** ← 本實驗正是嘗試這條路。 |
| **K1538** | bond-fund run-pressure ETF/FRED proxy 方向為正但**全數 below gates**（BH q=0.19、DM Harvey FAIL）。 |

**共同結論**：所有 *aggregate* 信用信號在控制 VIX 後增量 ≈ 0（VIX 吸收）。

**本題唯一差異化空間 = firm-level 分組對比**：文章真正主張是 *issuer-specific* —— 高槓桿公司
（ORCL、CRWV 等）**自己的**信用壓力 → **自己的** equity vol。這是先前 aggregate 實驗沒測過的維度，
也是 K1529 明示「需要 firm-level 才能 reopen」的方向。

---

## 2. 設計

### 2.1 槓桿分組（pre-specified，以 current total-debt/market-cap 佐證）

分組在看結果前就依資本結構固定；下表為 yfinance 當期快照佐證（`leverage_snapshot`）。
用 **total-debt / market-cap**（equity vol 的經濟相關量）為主判準，D/E 為輔。

| 組別 | 標的（debt/mktcap） |
|---|---|
| **HIGH-LEV**（高槓桿 AI-infra / tech） | ORCL 0.454、IBM 0.347、CRM 0.303、DLR 0.297、EQIX 0.232 |
| **LOW-LEV**（cash-rich hyperscaler） | META 0.053、MSFT 0.043、GOOGL 0.023、AAPL 0.017、NVDA 0.003 |
| **case-only**（不入檢定） | CRWV 0.875（n=326，IPO 2025-03，無空頭） |

> **限制（如實揭露）**：槓桿用當期快照做**靜態分類**套用整段樣本（免費日頻無歷史 fundamentals）。
> EQIX/DLR 是資料中心 REIT，高槓桿為結構性、且對利率敏感 → 引入 rates-vs-credit 混淆；納入是因其為
> 最信用敏感的 AI-infra 實體資產，但另附「純 levered tech」子集穩健性可延伸。

### 2.2 信用信號（個股 CDS 付費不可得 → ETF proxy）

- **PRIMARY（full 2015-2026）**：trailing-5d **HYG−LQD 信用壓力 proxy**。
  `stress_t = Σ_{trailing 5d} −(logret_HYG − logret_LQD)`，正值 = HY 相對 IG 走弱 = 信用惡化。
  這是任務授權的「HY/IG OAS + 公司債 ETF proxy」路線，且 K1529/K1538 已用同 proxy。
  **它是信用壓力的 diagnostic proxy，非 raw 單一發行人 CDS（Markit，付費）。**
- **SECONDARY（短樣本 2023-07+，underpowered）**：FRED HY/IG OAS 變化。

> **關鍵資料限制（2026-07-18 實測）**：FRED BAMLH0A0HYM2（HY OAS）與 BAMLC0A0CM（IG OAS）自
> 2024 ICE 授權變更後**只保留 ~3 年 rolling window**（兩者都從 2023-07-17 起，n≈787，**無空頭**）。
> 因此無法支撐 2015-2026 兩次空頭設計 → 只能當短樣本 secondary robustness，明確標 underpowered。
> 這與 k1621 遇到的 ICE OAS 截斷同一根因。

### 2.3 模型（per firm，log-HAR 變異數尺度，Corsi 2009）

| 模型 | 特徵 |
|---|---|
| **M0 HAR** | 自身 rv 日/週/月 |
| **M1 HAR+VIX** | + log(VIX 日變異數) ← **VIX 控制硬門檻 baseline** |
| **M2 HAR+VIX+credit** | + trailing-5d HYG-LQD 信用壓力（firm-relevant credit） |

- **主增量檢定 = Clark-West (2007) nested MSPE-adjusted**，M1→M2（正 t = credit 在 HAR+VIX 後有增量）。
  **不可用 raw DM**：M1⊂M2 是 nested，nested-DM 是無效推論且為 repo gate
  （`scripts/experiment_gates.py` nested-dm-misuse）。
- **分組差異（文章可檢定含義）= panel 交互作用**：
  `fwd_logRV ~ HAR + logVIX + credit + credit×HighLev`，date-clustered SE。
  `credit×HighLev` 係數檢定高槓桿發行人是否**更**敏感。
- **Group pooled CW**：loss differential **依日期跨組內個股聚合**（K1355 cluster-robust；
  asset-day iid 非主張），再做 HAC 推論。
- **VIX 硬門檻三條**（比一般更嚴）：(1) 主檢定是控制 VIX 之後的增量（M1 已含 VIX 為 regressor，
  OLS 自動 partial out VIX）；(2) HIGH-LEV 增量須顯著大於 LOW-LEV；(3) 單純 raw 相關顯著 = 直接 NULL。

---

## 3. Lookahead mechanical audit（最高風險）

| 檢查點 | 實作位置 | 保證 |
|---|---|---|
| 特徵在 origin t、target 嚴格未來 | `forward_rv()` L~275：`window = vals[i+1 : i+1+h]` | target = mean daily var over [t+1,t+5]，明確 forward window，無 shift off-by-one |
| OOS 訓練列 target_end < origin | `oos_forecast()` L~318：`train_hi = i - H` | 訓練列 j 只在 `j + H < i` 才 admissible（等價 target window 全在 origin 前） |
| raw/partial-corr 明確一日 lag | `raw_vs_controlled()` L~430：`credit.shift(1)`、`vix_var.shift(1)` | predictor 在 t-1，target rv 在 t → 明確 `signal.shift(1)` |
| FRED OAS secondary 亦 shift(1) | `fred_oas_secondary()`：`hy_chg5...shift(1)` | 同上 |
| 無 same-day 訊號 × same-day 報酬 | HAR/credit 皆用截至 t 的已實現資訊預測 [t+1,t+5] | 禁止事項「same-day 訊號乘 same-day 報酬」已避開 |
| nested 比較用 Clark-West 非 DM | `clark_west_test()` 全程 | 過 nested-dm-misuse gate |
| DM/CW HAC bandwidth canonical | 用 `volpred.stats.model_evaluation`（canonical，hac_lag=23） | 過 dm-hac-lag ratchet |
| 隨機 seed | `SEED=42`, `np.random.seed(42)` | 可復現 |

`experiment_gates.py run` **PASS**（4 experiment-integrity gates cleared，2026-07-18）。

---

## 4. 結果（全部 NULL）

### 4.1 主檢定：credit 在控制 VIX 後有增量嗎？（group CW，date-aggregated）

| 組別 | n_dates | CW t（credit beyond VIX） | p(one-sided) | mean adj loss diff | Harvey pass |
|---|---|---|---|---|---|
| **HIGH-LEV** | 2341 | **−0.97** | 0.83 | −1.1e-9 | ❌ |
| **LOW-LEV** | 2341 | −0.75 | 0.77 | −4.8e-9 | ❌ |

兩組 CW t **皆為負**（credit 加進去反而略差），mean adjusted loss diff ≈ 1e-9（經濟上為零）。
**credit 在 HAR+VIX 之上沒有任何增量**，兩組皆然。

### 4.2 分組差異：高槓桿組更敏感嗎？（panel 交互作用，date-clustered）

| 係數 | 估計 | t | 判定 |
|---|---|---|---|
| `logVIX` | 0.468 | **24.6** | VIX 完全主導（一如既往） |
| `credit`（LOW-LEV 基準） | 2.47 | 1.70 | marginal，未達顯著 |
| **`credit×HighLev`** | **−1.09** | **−0.95**（p=0.34） | ❌ 高槓桿組**沒有**更敏感，係數還微負 |

文章的核心可檢定含義（高槓桿發行人信用壓力→自身 vol 更強）**被否定**：交互作用不顯著且方向為負。

### 4.3 Raw vs 控制 VIX（K872 影子測試，明確 shift(1)）

| 組別 | raw corr(credit_{t-1}, RV_t) | partial corr | VIX | 
|---|---|---|---|
| HIGH-LEV | 0.031 | 0.014 |
| LOW-LEV | 0.025 | 0.005 |

**連 raw 相關本身就 ≈ 0.03**（比 K872 的 aggregate raw r=0.55 更弱）—— HYG-LQD 5d 壓力對個股 RV
幾乎無單變量預測力，控制 VIX 後更趨近零。這是比 K872 **更乾淨**的 NULL。

### 4.4 VIX-regime split（K1621 stress-flip 假說，本次未複製）

| 組別 | Calm (VIX<20) credit gain | Stress (VIX≥20) credit gain |
|---|---|---|
| HIGH-LEV | −0.17% | −0.52% |
| LOW-LEV | −0.22% | −0.34% |

K1621 曾在 stress regime 見到 suggestive 正向 sign flip；**本 firm-level 實驗未複製** —— stress 下
credit gain 仍為**負**，且高槓桿組在 stress 下更差。無 stress-conditional 信號。

### 4.5 每股增量（無一通過 Harvey |t|>3）

最槓桿的 ORCL（debt/mktcap 0.45）credit QLIKE gain +0.53%、CW t=0.38 —— 唯一正向但遠低於門檻；
其餘多為負。VIX gain 才是真正在做事（多數 +4~18%）。

### 4.6 CRWV case illustration（描述性，不入檢定）

n=326（IPO 2025-03，無空頭，單一 regime）。信用壓力 vs 20d 年化 vol 同期相關 0.17（弱正），
平均年化 vol 102%。**僅作 illustration**（如文章 SpaceX/SPCX 例），排除於所有正式檢定。

### 4.7 FRED OAS secondary（短樣本，underpowered）

HY OAS window 2023-07..2026-07（n=787，無空頭）。HIGH-LEV raw corr 0.031、partial|VIX 0.022 ——
與 primary 同為 NULL。

---

## 5. 結論

**Firm-level 亦無控制 VIX 後的增量。** 高槓桿 AI 基礎設施股的 equity vol 不比低槓桿 hyperscaler
對信用市場壓力更敏感（panel 交互作用 t=−0.95、p=0.34，方向還相反）。VIX sufficiency 從 aggregate
延伸到 firm-level 分組維度。這與 K872/T14/K1621/K1529/K1538 一脈相承，並**否證**了「issuer-specific
信用壓力是槓桿股波動率的獨立前導」這一（財經捕手文）主張——至少在免費 ETF/OAS proxy 可觸及的範圍內。

**未推翻既有結論**（本就預期 NULL），反而是對 VIX-sufficiency 護城河的又一次 firm-level 獨立確認。

**誠實邊界**：這否證的是 *proxy-level* firm 信用壓力的每日前導性，不否證 raw 單一發行人 CDS 在
事件窗口的關係（Markit 付費資料才能檢驗；K1529 的 reopen 條件仍未被免費資料滿足）。

---

## COLLECTION NOTES

- **一句話結論**：控制 VIX 後，高槓桿 AI 股 vol 對信用壓力**不**比低槓桿股更敏感——firm-level 分組
  差異不顯著（t=−0.95），VIX sufficiency 延伸到個股層級，又一個乾淨 NULL。
- **關鍵數字 3 個**：(1) panel `credit×HighLev` t=**−0.95**（p=0.34，方向相反）；
  (2) HIGH-LEV group CW t=**−0.97**（credit 在 VIX 後無增量，Harvey FAIL）；
  (3) raw corr(credit,RV)=**0.031** → partial|VIX=**0.014**（連 raw 都近零，比 K872 更弱）。
- **是否具 feed 文章價值**：**建議不發獨立文章**（純 NULL、且信號比 K872 更弱、無新反直覺角度）。
  可考慮**併入既有「VIX 是波動率充分統計量」導讀/系列**當作 firm-level 佐證段落（低優先），
  或作為未來「為什麼免費信用 proxy 抓不到 issuer risk」方法論文章的一個 data point。
  → 記 knowledge（NULL_NEGATIVE，firm-level credit-stress 分組無控制 VIX 後增量）由主線程處理
  （worktree agent 禁寫 knowledge.json）。
