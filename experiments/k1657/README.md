# k1657 — VRP（波動率風險溢酬）交易時段 vs 隔夜分解（免付費代理版）

**日期**：2026-07-08　**seed**：42　**verdict**：CONDITIONAL_PASS（主 claim 偏 NULL）
**Reviewer**：`feature-dev:code-reviewer` subagent（fresh-context）— **PASS**。Codex CLI 於審查時 quota-out（額度到 2026-07-11 恢復），依 `.claude/rules/experiments.md` fallback 流程改用 code-reviewer subagent；Codex 恢復後應二次驗證再由主線程立 closure。

---

## 1. 動機與差異化

既有 K 記錄過 SPY 隔夜 vs 日內 variance 的**描述性佔比**（item `9c8a9d1c` 43.1%、`079377e9` 44.3%，皆 2020-2026 子樣本），以及把 **VIX−GARCH VRP 當單一序列**的可預測性（item `c7ac9d68`，Spearman −0.054）。

**本實驗的新貢獻**：不是再測一次佔比，而是把 **VRP 本身拆成 day 成分與 overnight 成分**，正式檢定「日盤 VRP 與隔夜 VRP 對未來已實現變異數的**預測內容是否不同**」。這在既有 K 中沒有做過 —— 過去 VRP 都當一條序列，從未按交易時段拆解後做差異檢定。同時把描述性佔比從 2020-2026 子樣本擴展到**全期 2004-2026（N=5,661）**，修正子樣本偏誤。

## 2. 資料

| 項目 | 內容 |
|---|---|
| 主體 | SPY + `^VIX` 日 OHLC（yfinance），2004-01-05 ~ 2026-07-07 |
| N（全期分解） | 5,661 交易日 |
| N（含 VIX + forward target） | 5,635 |
| 次要（robustness） | 0050.TW + VIXTWN（`data/vixtwn/vixtwn_daily.csv`），僅 142 天（2025-12 起）— **N≪500，只作描述觀察，禁正式顯著性結論** |

**分解定義**（timing 明示）：
- 隔夜收益 `r_on_t = ln(Open_t / Close_{t-1})`，隔夜 variance proxy `= r_on_t²`
- 日盤收益 `r_day_t = ln(Close_t / Open_t)`，日盤 variance proxy `= r_day_t²`
- close-to-close `r_cc_t = ln(Close_t / Close_{t-1}) = r_on_t + r_day_t`（恆等）
- `var_cc = var_on + var_day + 2·r_on·r_day`（交叉項）；實測交叉項僅佔 var_cc 的 **3.9%**，故 day+overnight 近似成立。

**口徑一致（年化 decimal variance，annualization factor = 252）**：
- 隱含 `IV = (VIX/100)²`（VIX 為年化 vol 百分點）
- 已實現 `RV = (252/22)·Σ₂₂(r²)`（trailing 22 交易日，對應 VIX ~30 日曆日窗口）
- forward target `fwd_rv_H = mean_daily_var[t+1..t+H]·252`
- 三者皆年化 decimal variance，可直接相減比較。

## 3. 方法（含 timing & lag）

**VRP proxy（t 可觀測，無 lookahead）**：`VRP_t = IV_t − RV_trailing_t`。依 realized share 把 IV 分配到兩時段：`vrp_day = IV·(rv_day/rv_sum) − rv_day`、`vrp_on = IV·(rv_on/rv_sum) − rv_on`（**明示建模假設**：VIX 不分時段定價，比例分配是 modeling choice；故 vrp_day/vrp_on 同號且量級比 = rv_day/rv_on）。

**Q3 預測回歸**：
- **In-sample**：OLS + Newey-West HAC SE，predictor 全部 z-score 標準化，係數差異用 HAC 協方差的線性限制 t 檢定。每個 horizon H∈{5,22,66} 的 HAC maxlags = H。
- **OOS**：expanding-window，在 log-variance 空間 OLS（exp 回來保證正值 → QLIKE 不爆），DM 檢定（Harvey-Leybourne-Newbold 1997 小樣本校正），DM lag = H。
- **防 lookahead**：predictor 皆 trailing（結束於 t）；target 落 [t+1,t+H]（`var_cc.rolling(H).sum().shift(-H)`，已單元測試驗證嚴格在 t 之後）；OOS embargo 訓練列 `j ≤ i−H`（`train_end=i−H`），確保訓練尾端 label window 不觸及預測日 i。
- QLIKE 用 canonical `volpred.stats.model_evaluation.qlike_pointwise`（actual/predicted）。

## 4. 主要結果

### Q1 — 描述（隔夜 vs 日盤 variance 佔比）

| 統計量 | 值 |
|---|---|
| 全期隔夜 variance 佔比（聚合） | **37.4%**（block-bootstrap CI95 [32.9%, 43.1%]，2000 reps, block=22, seed=42） |
| 逐年範圍 | 13.9%（2005）~ **62.5%（2020 COVID）** |
| corr(var_day, var_on) | 0.207（全期；比 prior-K 2020-2026 的 0.024 高，子樣本偏誤） |
| corr(r_day, r_on) | 0.042（近乎無關） |

> 全期 37.4% **低於** 既有 K 的 43-44% —— 那些數字取自 2020-2026 高隔夜佔比子樣本；納入 2004-2019 後回落。隔夜佔比高度時變，非固定常數。

### Q2 — VRP 分解量級

| 統計量 | 年化 variance |
|---|---|
| 平均 IV（隱含） | 0.0432 |
| 平均 RV_total（已實現） | 0.0352 |
| 平均 VRP_total | **+0.0080**（VIX 系統性高估 variance） |
| VRP_total > 0 比例 | **86.2%** |
| 平均 vrp_day / vrp_on | +0.0062 / +0.0032 |

VRP 壓倒性為正（86%），與經典 VRP 文獻一致；day-VRP 量級大於 on-VRP（但這是比例分配的機械結果，非獨立實證）。

### Q3 — 可預測性（主 claim）

**Reg1：兩時段 realized 成分預測未來 total variance**（z-score 係數，t 值）

| H | rv_day | rv_on | day−on 差異 t (p) | R² |
|---|---|---|---|---|
| 5 | 0.036 (t3.34) | 0.025 (t2.16) | 0.53 (0.598) | 0.333 |
| 22 | 0.035 (t3.55) | 0.012 (t1.28) | 1.39 (0.164) | 0.315 |
| 66 | 0.025 (t4.52) | 0.002 (t0.66) | **2.81 (0.005)** | 0.188 |

→ **唯一顯著發現**：季度（H66）horizon，日盤 realized variance 顯著比隔夜 realized variance 更能預測未來變異數（差異 t=2.81, p=0.005）；隔夜成分在長 horizon 幾乎無預測力（t=0.66）。短 horizon 兩者無顯著差異。隔夜波動較像 jump/gap 驅動、持續性低。

**Reg3：day-VRP vs on-VRP 預測內容差異**（控制 rv 成分）

| H | vrp_day | vrp_on | vrp_day−vrp_on 差異 t (p) |
|---|---|---|---|
| 5 | t2.18 | t3.13 | −1.15 (0.251) |
| 22 | t1.33 | t4.21 | −1.33 (0.183) |
| 66 | t2.02 | t1.63 | 0.40 (0.692) |

→ **NULL**：day-VRP 與 on-VRP 的預測內容在任何 horizon 都**無顯著差異**。有趣的是短 horizon 反而是 **on-VRP** 帶更強獨立訊號（t3.13/4.21），與 realized 成分方向相反 —— 但差異不顯著，不能宣稱。

**Reg2：aggregate VRP 在 RV 之上的增量** — VRP_total 顯著（t 5.44/4.40/6.37 across H），確認 VRP 對未來變異數有預測力（已知文獻，非新發現）。

**OOS DM（full = RV+session 成分+session VRP vs baseline = RV_total）**

| H | QLIKE 改善 | DM t | full 顯著勝？(Harvey \|t\|>3) |
|---|---|---|---|
| 5 | +7.97% | 2.31 | ✗ |
| 22 | +1.90% | 0.39 | ✗ |
| 66 | +3.31% | 0.56 | ✗ |

→ **NULL**：時段分解在 OOS 對 aggregate RV baseline 有正向但**不 robust** 的改善（DM 全部低於 Harvey 3.0 門檻）。

### TWN 次要（描述性，N=142，禁顯著性）

隔夜佔比 **59.3%**（遠高於 SPY 37%，因台股隔夜承接美股 session），VRP_total proxy 平均 +0.021、正比例 82.6%。**僅供 forward-looking 觀察，樣本不足不下任何正式結論。**

## 5. 誠實 verdict

**CONDITIONAL_PASS，主 claim 偏 NULL**：把 VRP 按交易時段拆解**沒有**產生 robustly 不同或更優的預測內容 —— day-VRP 與 on-VRP 預測內容無顯著差異（Reg3 全 NULL），OOS 分解不 robust 勝 baseline（DM 全低於 Harvey 門檻）。唯一站得住的正向發現是 **realized 成分**（非 VRP 成分）在**季度 horizon** 上分歧：日盤 RV 顯著比隔夜 RV 更持續、更能預測未來變異數（t=2.81, p=0.005）。與既有大量 VRP null 結果一致（VRP 難做 directional/decomposition edge）。

## 6. 相關 K

- `9c8a9d1c` / `079377e9`：SPY 隔夜佔比 43-44%（2020-2026 子樣本）→ 本實驗全期修正為 37.4%
- `c7ac9d68`：VRP（VIX−GARCH）單序列 vol predictor（Spearman −0.054）→ 本實驗按時段拆解後仍無 decomposition edge
- prior VRP nulls（directional trading, harvesting）：一致 —— VRP 分解無交易/預測 edge

## 7. 防錯 checklist

- [x] Lookahead：predictor trailing（結束於 t）；target [t+1,t+H]（單元測試驗證）；OOS embargo j≤i−H
- [x] 口徑一致：IV/RV/fwd 皆年化 decimal variance，factor=252 明示
- [x] seed=42（block bootstrap `default_rng(42)` + `np.random.seed(42)`）
- [x] HAC/DM horizon 各用對應 H（不共用單一 horizon）
- [x] QLIKE canonical actual/predicted
- [x] 交叉項揭露（占 var_cc 3.9%）；vrp 比例分配假設明示
- [x] TWN 短窗明標禁顯著性
- [x] Codex quota-out → code-reviewer subagent fallback PASS（待 Codex 恢復二次驗證）

## 檔案

- `k1657.py` — 完整可重跑腳本
- `k1657_results.json` — 全部統計量 / N / 期間 / seed / p-values
- `fig_a_overnight_share.png` — 隔夜佔比 63 日滾動時序
- `fig_b_vrp_components.png` — day-VRP vs on-VRP 時序
- `fig_c_vrp_dist.png` — VRP 成分分布
