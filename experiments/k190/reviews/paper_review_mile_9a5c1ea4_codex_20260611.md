# Paper Review (Codex 24h-rule) — mile_9a5c1ea4 (K190)

**Article**: 市場跌過之後通常更容易亂，但把波動拆更細，真的比較有用嗎？
**Audience**: general (verified — 0 academic keywords)
**Published**: 2026-06-10 22:01 UTC
**Reviewer**: Codex CLI (`gpt-5.4`), session 2026-06-11 20:08 CST
**Verdict**: **CONDITIONAL_PASS**

## Audit dimensions

### 1. Lookahead — **CLEAN**
- `ewma_forecast` (line 126): `h_t = lam*h_{t-1} + (1-lam)*x_{t-1}`, explicit comment "forecast[t] uses info <= t-1"
- `model_ewma_semivar` / `semivar_har_forecast` / `gjr_garch_forecast` / `garch_x_sjv_forecast`: 全用 t-1 或更早資訊
- `sjv_regime_analysis` 的 `shift(-1)` 是 forward outcome（`SJV_t → RV_{t+1}`），非 lookahead bias

### 2. Number consistency — **ALIGNED**
| Article claim | results.json field | Status |
|---|---|---|
| SPY 1.54 倍 | `per_asset.SPY.sjv_regime.ratio = 1.5393` | ✓ |
| QQQ 1.32 倍 | `per_asset.QQQ.sjv_regime.ratio = 1.3226` | ✓ |
| 4 個 GJR-GARCH 贏 | `cross_asset_summary.model_wins.GJR_GARCH = 4` | ✓ |
| QQQ 例外 (EWMA_semivar) | `per_asset.QQQ.best_model = EWMA_semivar` | ✓ |
| TLT 反向（漲後波動高） | `sjv_regime.ratio = 0.7305, p = 0.0163` | ✓ |
| GLD/BTC 無明顯模式 | sjv_ratio 0.89/0.89, p > 0.46 | ✓ |

### 3. DM overclaim — **FLAGGED (acceptable hedge)**
- Article: "QQQ 是把正負波動拆開看的簡化版本**略勝一點點**"
- Reality: QQQ `EWMA_semivar_vs_GJR` DM t=-0.4611, p=0.6449（QLIKE 差距 -7.968 vs -7.957，無統計顯著）
- Article 用「略勝一點點」是 hedge wording — 沒誤導為 Harvey/DM-significant 勝出，可接受
- 若未來重寫，可加 "但統計檢定上沒有顯著差異" 一句更明確

### 4. SJV → RV causality — **CLEAN**
- `sjv_t < 0` (downside dominant today) 預測 `RV_{t+1}`（明日波動）— 純 forward prediction，因果方向乾淨

## Final verdict
**CONDITIONAL_PASS** — 可保留 published 狀態。

## Optional follow-up（非阻塞）
- 若日後寫 "Realized Semivariance follow-up" 文章，可補一句 "QQQ 的 EWMA_semivar 雖然 QLIKE 略低，DM 檢定下與 GJR-GARCH 無顯著差異" 強化研究誠實 narrative
