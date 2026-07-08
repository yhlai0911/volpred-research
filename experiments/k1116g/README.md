# K1116g — Nested Clark-West increment test, remaining STABLE-DATA daily families (vix-sufficiency paper)

**狀態**: COMPLETED — Verdict **NULL (robust)**: F1/F8/F11 nested Clark-West 全 FAIL Harvey |t|>3.0
**日期**: 2026-07-09
**Reviewer**: `feature-dev:code-reviewer` subagent (fresh-context) — **PASS**, lookahead 全乾淨、no blocking issues (Codex usage-limited 至 2026-07-11；agy 逾時)
**Predecessors**: k1116c (weekly F12/F13) → k1116e (daily F2/F4)
**Parent task**: `paper_body_vix_sufficiency_daily_family_clark_west` (SEVERE-2 carve-out)

## 1. 動機 (WHY)

vix-sufficiency paper 的核心 claim 是 NULL：13 個 signal families 沒有一個對 VI
alone 有統計顯著的樣本外改善。Table 3 對 daily families 只報標準 DM |t|。審稿人會問：
換成**更 powerful 的 nested Clark-West (2007)** 檢定，daily families 的 null 撐得住嗎？

- k1116c 已對 weekly alt-data F12/F13 回答（全 |t|<0.6）。
- k1116e 對**最高 IS-signal**的兩個 daily families（F2 VIX 期限結構 IS t=17.6、F4 VRP
  IS t=3.51 — prime CW-flip candidates）回答：CW t=1.69 / −0.22，皆 FAIL Harvey。
- **k1116g（本實驗）** 完成剩餘**穩定資料**的 daily families：**F1 跨資產波動動能、
  F8 殖利率曲線斜率、F11 日曆異常（Halloween）**。

仍延後的 F3（行為 P/C）、F9（Google Trends）、F10（隔夜 VIX open）需 fragile 外部資料
（CBOE put-call、pytrends、intraday VIX open）→ 資料備置後續 run。此非 bounding argument：
F1/F8/F11 是能純用 Yahoo Finance 價格 + 日期算術重建的家族，誠實計算並如實報告 CW。

## 2. 方法 (HOW) — 與 k1116e 同一 harness

- **Target**: SPY 22-day **FORWARD** realized vol（annualized ×100），over (t, t+H]，H=22。
- **Baseline (restricted M2)**: `fwd_rv22 ~ 1 + VIX_level`
- **Augmented (nests M2)**: `fwd_rv22 ~ 1 + VIX_level + signal_j`
- **Lag**: features = close-of-day-t 資訊集（無額外 shift，對齊 paper daily convention）；
  target 嚴格前向 → 無 lookahead。both nested models 用**同一** IS/OOS rows；IS 尾 22 天 embargo。
- **Clark-West**: `f_hat = e1² − e2² + (f1−f2)²`，one-sided H1: E[f_hat]>0，|t|>3.0 = Harvey pass。
  HAC nw_lag=21、HLN h=22（forward-overlap 校正）。
- **IS/OOS split**: IS ≤2018-12-31，OOS 2019-01-02 → 2026-05-28（n_oos=1861）。

### Signal 構造（依 paper main_v5.tex §2.3 prose 忠實重建）

| Family | 構造 |
|---|---|
| **F1** 跨資產波動動能 | TLT/USO/UUP/GLD 各自 22d RV + 一條 HYG−LQD credit-return spread 的 22d RV；取各自 5-day 變化 → rolling-252 z-score（lookahead-safe 正規化）→ 平均（要求 ≥3 legs） |
| **F8** 殖利率曲線斜率 | `^TNX`(10Y) − `^IRX`(13-week)，close-of-t |
| **F11** 日曆異常 | Halloween/"Sell in May" 指標：月份 ∈ {5..10} = 1，否則 0（純日期，無資料） |

## 3. 結果 (WHAT)

| Family | n_IS | n_OOS | IS signal t† | fixed-split DM \|t\|‡ | **Clark-West t** | Harvey pass (>3.0) |
|---|---|---|---|---|---|---|
| F1 跨資產動能 | 3030 | 1861 | 7.02 | 0.22 | **0.69** | ❌ |
| F8 殖利率斜率 | 6506 | 1861 | −4.24 | −0.25 | **0.11** | ❌ |
| F11 日曆 Halloween | 6506 | 1861 | 4.78 | −1.72 | **−1.50** | ❌ |

**三者 nested Clark-West 皆遠低於 Harvey 3.0（最大 |CW t|=1.50）→ VIX sufficiency 對這些
daily families 亦 robust。** 與 k1116e（F2/F4）、k1116c（F12/F13）、paper thesis 一致。

† IS signal t 是 augmented 模型內 signal 係數的 t（本 fixed-split IS 窗）。與 Table 3 的
IS ΔR² t 之 magnitude/**sign** 差異來自：(a) fixed-split IS 窗 vs paper 的 spec/sample，
(b) signal 定向差異。**CW/DM 對 signal 定向不變**（OLS 自估係數符號），故 null 結論不受影響。

‡ fixed-split DM 是**方向性 cross-check**，非 Table 3 expanding-window DM 的精確重現
（同 k1116e：F2 fixed-split DM|t|=1.30 vs Table 3 的 0.87）。Deliverable 是 CW column。

## 4. 檔案

- `k1116g.py` — harness（data load + 3 signals + same-sample nested OLS + DM + CW）
- `k1116g_results.json` — F1/F8/F11 完整統計
- `run.log` — 執行 log

## 5. 對論文的意義

Table 3 的 daily-family CW 欄現已覆蓋 5/8 nested-CW-applicable daily families
（F2/F4 from k1116e + F1/F8/F11 from k1116g），全 FAIL Harvey。剩 F3/F9/F10 待外部資料。
**Table 3 CW 欄整合 + reproduce.py rebind + paper-update 仍 blocked on F3/F9/F10**（本 fire 非 scope）。
