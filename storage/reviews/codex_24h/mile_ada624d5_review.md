# Codex 24h Review — mile_ada624d5 (K709)

- **Article**: 降息時黃金漲 30.8%、股票漲 13.4%——那為什麼跟著利率調倉，幾乎等於沒做？
- **Published**: 2026-05-29T03:53:51+00:00
- **Reviewed**: 2026-05-29 13:15 台灣時間
- **Reviewer**: Codex CLI 0.132.0 (gpt-5.4 medium, ChatGPT auth)
- **Verdict**: **FAIL_PROVENANCE**

## Codex 結論摘要

1. **Reproducibility: FAIL** — `experiments/k709/` 無 `k709.py` 腳本，README 全 placeholder，`data/` 與 `references/` 空目錄；`k709_results.json` 只有 3 個數字 (`cond_sharpe=0.869, bh_sharpe=0.85, delta=0.019`)，違反研究誠實原則 §2「實驗三件套」。

2. **Lookahead / Algorithm: 不可驗證** — 無腳本無法檢查 `signal.shift(1)` / 6m window / regime labeling 是否使用同期或未來資訊。最大風險：用事後完整 6m 變化先分群，再回算同期報酬，產生 regime hindsight bias。

3. **Claim-evidence matching: 大多數數字無來源** — `results.json` 只能支撐 `0.850 / 0.869 / +0.019`。**完全無 artifact 來源**: `30.8%`、`13.4%`、regime 佔比 `21%/62%/19%`、配置表、月再平衡頻率、TNX 6m 變化分群定義。

4. **Overclaim: 有** — `0.850 vs 0.869` 差距 0.019 寫成「等於沒做」結論需要 DM / Harvey 或 bootstrap 檢定，現文證據強度不足。

5. **Recommendation**: **Unpublish 或退回 draft**。補齊 `k709.py`/README/data/references → 重算所有數字 → 對 0.019 補 DM/Harvey/bootstrap → 重審後再 publish。

## 主線程處置 (2026-05-29 13:15)

- 文章狀態：published → **draft** (退回，supabase_sync 同步)
- 文章頂部加 audit caveat banner
- 建立 followup task `K709_rebuild_reproducibility` (P3, experiment type) → 下次 hourly fire 認領
- knowledge.json: 補 K709 reviewer/verdict provenance（reviewer_source=codex, verdict=FAIL_PROVENANCE）
- Email boss: 通知此 incident + 處置方案

## 引用
- `experiments/k709/k709_results.json`
- `storage/reports/feed.json` (article record)
- `.claude/rules/experiments.md` (三件套規則)
