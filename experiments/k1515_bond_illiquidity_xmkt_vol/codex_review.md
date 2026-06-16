# K1515 Codex Review

Reviewer: Codex CLI (gpt-5.4, ChatGPT auth) — primary path
Date: 2026-06-16
Verdict: **CONDITIONAL_PASS**

## Findings

1. **Lookahead / split — PASS.** 7 features 皆 `.shift(1)`；train 2014-2022 / OOS 2023-2026 切分正確；XGB `random_state=42`。
2. **DM 檢定方向正確.** p=0.961 支持「XGB 未顯著勝同特徵 OLS」的弱結論。
3. **Critical caveat — framing 過強.** OLS 也用同 7 features (含 cross-market)，DM 只比 model class (XGB vs OLS) 不比 feature set。要說「cross-market 無增量」必須對 AR-only 跑 baseline。已在 README §6 補 framing caveat。
4. **Sample size 充足** for daily PoC (n_oos=864)。v2 應升級到 HAC 或 HLN finite-sample correction，當前 iid normal DM approximation 在 daily h=1 可能 understate 自相關。
5. **Caveat 誠實.** Single-name、range-based proxy、daily 頻率與 FAJ 2024 monthly 差距、無 HPO 都列出。需明說 VIX feature_importance=0.46 是 in-sample split gain 非 OOS power — README §6 已補。

## v2 建議

1. **AR-only OLS baseline**：3-way DM (AR-OLS vs AR+XMKT-OLS vs AR+XMKT-XGB) 才能 isolate feature 增量 vs model 增量
2. **頻率變寬**：weekly / monthly aggregated illiquidity；FAJ 2024 即 monthly
3. **Panel**：HYG + LQD + VCIT + EMB + MUB 同時跑，fixed effects 控制 issuer-segment
4. **多 illiq proxy**：Roll / Amihud / Corwin-Schultz vs (H-L)/C robustness
5. **HAC / HLN DM**：finite-sample correction
6. **Regime split**：COVID stress vs calm 區分 conditional incremental power

## Knowledge Provenance

- parent_review_task: `research_illiquidity_vol_feature` (auto-research-fallback)
- experiment_id: `k1515_bond_illiquidity_xmkt_vol`
- commit: `7df716ce`
- reviewer_source: `codex_cli_primary`
- verdict: CONDITIONAL_PASS (NULL on joint feature set; AR-only baseline missing prevents strong cross-market null claim)
