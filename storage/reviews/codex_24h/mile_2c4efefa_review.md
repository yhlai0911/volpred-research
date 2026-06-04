# Codex Review — `mile_2c4efefa`

- **Article**: 最貴的避險模型不一定最好：SPY 用 QQQ 對沖，花大力氣的複雜公式差多少？
- **Experiment**: K1320（SPY/QQQ 對沖 — OLS / Rolling OLS / DCC / Copula 五家族）
- **Reviewer**: Codex CLI 0.135.0 (gpt-5.4, ChatGPT auth)
- **Run date**: 2026-06-04（hourly-09 dispatch）
- **Task**: `paper_review_mile_2c4efefa` (24h Codex source-code-level review per `.claude/rules/agent-delegation.md` K1018 lesson)

---

## Verdict

`MIXED` — 文章主要數字（HE table、AIC、Clayton ρ_equiv）與 `experiments/k1320/k1320_results.json` 一致，靜態 OLS / Rolling OLS / 靜態 Copula / DCC Gaussian 的 IS/OOS 分割乾淨；但動態 Copula Gumbel 引入 **future-window 線性內插**（look-ahead），DM 檢定 loss object 錯置（實際是 `r^4` 不是標準 forecast-error loss），且 `DCC_t` 標籤與實作不符。文章「無統計差異」「不存在未來資訊外洩」需降調。

## Findings

### 1. 動態 Gumbel `np.interp` 引入未來資訊（lookahead MED）

- `experiments/k1320/k1320.py:541, 580` 動態 copula 用 `rho_interp = np.interp(...)` 把後一個 21 日 re-estimate 線性插回當前日，t 時點的 hedge ratio 因此包含 t+21 才能算到的估計。
- 文章「我們比了哪些模型？」段宣稱「所有模型的對沖比例都用『昨天算出來的比例，今天執行』，不存在未來資訊外洩」— 對靜態 / DCC Gaussian / Rolling OLS 成立，但**動態 Gumbel 不成立**。
- 動態 Gumbel OOS HE = 0.8876 與靜態 Gumbel 0.8880 差異微小，因此偏誤幅度不大；但 lookahead 在原則上不可接受，必須修。

### 2. DM 檢定方法論 UNSOUND

- `experiments/k1320/k1320.py:897, 915, 945` 程式先把 hedged return 平方成 `e = rets ** 2`，再進 `dm_test_hln_hac`，函數內部又做 `d = e1 ** 2 - e2 ** 2`，最終比較的是 **`hedged_return ** 4`** 的 differential。
- 這既不是對 forecast error 相對 realized target 的標準 Diebold-Mariano，也不是 Patton (2011) class volatility loss（QLIKE / MSE-of-variance），更不是 HE 差或 variance reduction 的 bootstrap。
- HAC / Harvey-Leybourne-Newbold small-sample correction 有做，但 object 錯了 → 文章「Gumbel 與 DCC 沒有統計上可區分的差異」結論不可用此 p=0.617 為據。

### 3. `DCC_t` 標籤錯誤

- `experiments/k1320/k1320.py:714, 720` `DCC_t` 實際只用靜態 `rho_t` 乘 GARCH sigma，並非動態 t-DCC。
- `experiments/k1320/k1320_results.json:109` `DCC_t` OOS HE = 0.8879267969307703 與 `Copula_Student_t_static` 完全相同，證明這兩者是同一個 path。
- 文章 table 「DCC + 厚尾」一列因此會誤導讀者，需改名或真正實作動態 t-DCC。

### 4. 首日 hedge 處理 comment 與 code 不符

- `experiments/k1320/k1320.py:732` 註解寫「first observation has no hedge (unhedged)」。
- `experiments/k1320/k1320.py:749` 實作是 `hr_lagged[0] = hedge_ratios[0]`，首日仍套用避險。
- 影響量小（1/1509 = 0.07%），但 audit trail 不一致。

### 5. 數字一致性 ✓

- Gumbel 0.8880 / DCC 0.8862 / Clayton 0.7133 / AIC ≈ -6940 / -5546 / Clayton ρ_equiv ≈ 0.50 — 均能在 `experiments/k1320/k1320_results.json` 直接對上。
- IS/OOS split（2005-2018 IS / 2019-2024 OOS, N=1509）程式為 `k1320.py:103/128/155/601/686` 也符合文章敘述。

## Lookahead Risk

`MED` — 靜態 OLS / Rolling OLS / 靜態 Copula / DCC Gaussian 都有等效 `signal.shift(1)` lag；但動態 Gumbel 的 `np.interp` 引入 future re-estimates，且首日並非真正 unhedged。

## DM Methodology

`UNSOUND` — Loss object 為 `r^4`，未直接檢定 HE、variance reduction、QLIKE 或其他可辯護的 volatility loss。HAC / HLN correction 有做但 target 錯。

## Overclaims

1. 「所有模型不存在未來資訊外洩」— 動態 Gumbel 不成立。
2. 「Copula Gumbel 雖然數字稍高，但和 DCC 沒有統計上可區分的差異」— 在錯置 loss 下不顯著，不等於真正未顯著。
3. 「每 252 個交易日滾動重估一次」— 程式實為「252 日窗口、每 21 日重估一次再內插」。
4. Table 「DCC + 厚尾」— 實作不是動態 t-DCC。

## Required Fixes（按優先序）

1. **移除動態 copula 未來內插**：改為 piecewise-hold（用最近一次已知估計直到下一次 re-estimate）或逐日 expanding-window 估計，禁止 forward interpolation。
2. **重做統計檢定**：用 `d_t = r²_DCC,t − r²_model,t` 的 HAC DM；或直接 bootstrap HE 差的 CI。然後**重寫**文章「核心發現」段的統計顯著性語言。
3. **重新命名 `DCC_t`** 為 `StudentT_Copula_static`（或真正實作 t-DCC）；同步更正文章表格與「動態相關模型」分類。
4. **首日 lag 一致性**：若主張「first obs unhedged」，就令首日 `hr_lagged[0] = 0` 或 NaN-skip。
5. **文章降調**：「無統計差異」→「在本實作與此 loss 定義下未見顯著差異」；對 Clayton 失敗加 N=1 樣本限制。

## Follow-up Tasks Opened

- `K1320_fix_dynamic_lookahead_DM`：code-level 修正 + 重跑 OOS（experiment）
- `mile_2c4efefa_article_caveat`：文章 prepend caveat note（降調 overclaim）

---

*Source-code review run via `codex exec --skip-git-repo-check` (read-only sandbox). 90,860 tokens used.*
