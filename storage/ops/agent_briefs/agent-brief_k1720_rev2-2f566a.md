# K1720 rev2 — bounded remediation after Codex round-1 FAIL

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Pool task**: `assign_99f4b3bf` (P1, source=user)
**Worktree (你的 cwd，只准寫這裡)**: `.claude/worktrees/dispatch-slot-3-87c7269d-k1720`
**Codex verdict**: `storage/ops/codex_reviews/k1720_verdict.md` — VERDICT: FAIL（不得 merge、不得寫 knowledge.json）

實驗檔在 `experiments/K1720/`：`K1720.py`、`K1720_results.json`、`README.md`、`data/raw_*_1h.parquet`（5 檔 1h bars 已快取，重跑不需重新下載；`download_1h()` 有 cache 命中就直接讀 parquet，請勿刪快取）。目前這個 worktree 的 `experiments/K1720/` 尚未 commit（`git status` = untracked），由你收尾時 commit。

這是 **bounded remediation**，不是重做實驗：研究問題、資料、identification 設計都不動，只修下面五項 + 依契約重跑。**修正後結論仍是 NULL 完全可以接受**（AGENTS.md 研究誠實原則第 9 條），不要為了「有結果」去調規格。

---

## 必修 1（阻斷性，會改動所有下游數值）— prev_close 定義錯誤

`build_session_panel()`（`K1720.py:117-155`）先在 `K1720.py:129` 用 `if len(g) != 7: continue` 丟掉半日市 / 提早收盤的 session，**之後**才在 `K1720.py:153` 做 `s["day_close"].shift(1)`。

後果：任何半日市之後的那個完整交易日，`prev_close` 拿到的是**再前一個完整 session** 的收盤，不是真正的 prior session close。`r_intra = p1530_open / prev_close - 1`（`K1720.py:154`）因此跨越多個 sessions，數值被放大；且 `analyse_complex()` 的 expanding decile threshold（`K1720.py:193`）建立在 `|r_intra|` 上 → event flag、H1、H1b、H2、time-of-day profile **全部受污染**。

這**不是 lookahead**（用的仍是過去資訊），但 predictor 定義錯 → 所有下游數字錯。

**修法**：在「完整 session 日曆」上先取得 prior-session close，再做 7-bar 過濾。具體：對 raw 1h bars 的**每一個**交易日（含半日市 / 早收）都算出該日最後一根 bar 的 close 當作該 session 的 `day_close`，用這條完整序列做 `shift(1)` 得到 `prev_close`；然後才把 `len(g) != 7` 的日子從**分析樣本**（outcome / rest-of-day 特徵）中排除。也就是：半日市自己不進分析樣本，但它仍然是它隔天的 prior session。

驗收：results.json 要能看到 (a) 完整 session 日曆天數、(b) 被排除的非 7-bar session 天數、(c) 分析樣本天數，三者關係自洽；並記錄有多少天的 `prev_close` 因這次修正而改變（rev1 vs rev2 差異筆數），寫進 results 的 remediation 區塊。

## 必修 2 — H1 的序列相關處理不足

`bootstrap_ratio_ci()`（`K1720.py:169-177`）是 iid percentile bootstrap，`K1720.py:204` 的 Welch t-test 也假設獨立觀測。日頻 volatility 有 clustering，兩者都會低估標準誤。

二選一，明確擇定並在 README 說清楚：
- **(A) 補強**：加 HAC event-dummy inference（`log(lasthour_vol) ~ event_dummy`，Newey-West，沿用既有 `hac_ols()` 的 bandwidth 慣例）+ **stationary / moving-block bootstrap**（block length 要有依據並記錄，seed 固定）取代 iid bootstrap CI；或
- **(B) 降格**：把 H1 明確標為**純描述統計**，README 與 results 都不得出現 "significant" / p-value 式的推論語言。

H1b / H2 既有的 HAC 規格 Codex 已判定合理，**不要動**。

## 必修 3 — NULL 過度解讀

H1b 係數仍為正、QQQ/SPX 的 HAC p ≈ 0.135 / 0.126（不顯著但方向與假說一致）。目前 `README.md:138` 的 "~fully explained" 與 `K1720.py:361` / results rationale 的 "is absorbed" 都超出證據。

改為「**在此解析度與規格下未檢出 sharp joint mechanism**」這類措辭。**不得**表述為機制已被否證、或流量已被證明吸收。全檔掃過一遍同義的過強措辭一併改掉。

## 必修 4 — Multiple testing 與 replication 口徑

- `README.md:116` 稱 QQQ/SPY 為 "independent replication" — 同期間、共享市場因子，**不是獨立重複**。改成「同期間、高度相關的第二個複合體，作為一致性檢查」這類正確口徑。
- `README.md:129` 對 6 bars × 2 complexes 的 nominal p 沒做 multiplicity adjustment → 補調整（Bonferroni / Holm 擇一並說明）或明確標為 **exploratory**。
- 14:30 那個結果**只能標 exploratory**，不得宣稱是可靠的 peak，也不得說成 "opposite of prediction"。

## 必修 5 — 樣本 provenance 不一致

實際樣本是 **2023-08-29 至 2026-07-24、719 sessions**（以你重跑後實際數字為準，不要照抄本行；若修正必修 1 後樣本數變動，用新數字）。`README.md:51`、`README.md:169`、`K1720_results.json:323` 目前寫「約 2 年 / 約 500 sessions」是錯的 → 全部更正，並依真實樣本重新表述 power limitation。

## 已通過，不要動

15:30 predictor 與 15:30-16:00 outcome 區間不重疊；event threshold 的 `shift(1)` 正確；AUM 僅作 static cross-sectional constant；seed=42。經濟量級複算一致：係數 TQQQ=6 / SQQQ=12 / SSO=2；QQQ $5.0667B／199.58%、SPX $221.96M／3.6855%（這幾個是 mechanical notional，與 prev_close 修正無關，重跑後應維持一致 — 若變了要查為什麼）。

---

## 收尾契約（硬性）

1. **run-time 產 spec**：腳本收尾必須呼叫
   ```python
   from volpred.research.reproduce_spec import finalize_experiment
   finalize_experiment(results=payload, entrypoint=__file__,
                       canonical_result="K1720_results.json",
                       inputs=[...], seeds=[("numpy", 42)], started_at=T0)
   ```
   `K1720_results.json` 與 `experiments/K1720/reproduce_spec.json` 必須由**同一次執行**寫出（K1708 教訓：事後補 spec → sha/bytes 對不上程式）。**禁止事後手寫 spec**。
2. **重跑是必要的**，不是選配 — 必修 1 改變所有數值。README 內每一個數字都要與新的 `K1720_results.json` 一致（逐一核對，不要留 rev1 的殘值）。
3. results.json 加一個 `remediation` 區塊，逐項對應 Codex 五個 FAIL 條目：改了什麼、在哪一行、rev1→rev2 數值變化。
4. **禁止寫 `storage/memory/knowledge.json`**（K1259 — 只有主線程能寫）、禁止碰 `storage/reports/feed.json`、`thinking_journal.json`、`experiment_experiences.json`、Supabase / Mirror。你只產出 `experiments/K1720/` 內的檔。
5. 自查 artifact gate：`python3 scripts/check_experiment_artifacts.py check --path experiments/K1720`
6. **在 worktree 內 commit**（訊息寫清楚修了哪五項）。**不要**自己 merge、不要碰 main。
7. 全程繁體中文寫 README。數字一律程式化產出，禁止手抄、禁止估算。

## 成功標準

- 五項必修逐項可驗證地修掉（README / K1720.py / results.json 三處一致）
- `K1720.py` 重跑成功，`K1720_results.json` + `reproduce_spec.json` 由同一次 run 產出且 sha/bytes 對得上 disk 上的 `K1720.py`
- 樣本期間與 session 數三處一致且等於實際值
- 所有結論措辭強度不超過證據（NULL 可保留）
- worktree 已 commit，`check_experiment_artifacts.py` 自查通過或明確說明為何未過
