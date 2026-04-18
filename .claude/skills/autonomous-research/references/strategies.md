<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# Trading Strategies Guide

## Strategy Types

### 1. Slow-Adjustment Vol Targeting (SPY)
- Logic: weight = target_vol / smoothed_sigma, MA=5 smoothing
- Target: 12% annual vol
- Validated: Sharpe 0.59, MaxDD -28%, cost 0.12%/yr
- Rebalance: weekly (Sharpe 0.58) or daily (0.59)

### 2. Risk Parity (SPY + GLD)
- Logic: inverse-volatility weights, scaled to target vol
- Validated: Sharpe ~1.18 (selection bias caveat, CI includes 0)
- Each asset gets GARCH-predicted sigma

### 3. Adaptive Sigma Floor
- QLIKE from GJR-arch (best accuracy)
- VaR from max(sigma_gjr, 0.9 × sigma_garch)
- Decouples accuracy from safety

## Strategy Type 4: VIX Futures Contango Roll
- Logic: VIX futures term structure contango → short far-month VIX futures
- Annualized roll yield ≈ 10-15%
- **EXTREME RISK**: VIX spike can cause 800%+ losses

## Transaction Costs (SPY)

### SPY ETF 真實交易成本（2024-2025）
- **Commission**: $0 (most brokers: Robinhood, Schwab, IBKR Lite)
- **Bid-ask spread**: SPY ≈ 0.01-0.02% (lowest globally)
- **Slippage**: SPY ≈ 0.005% (extremely liquid)
- **Single-side total: ≈ 0.015-0.025% per trade**
- **ETF management fee**: SPY 0.0945% annualized (reflected in price)
- Slow VT annual cost: 0.12%

### Options Trading Costs (for VRP strategies)
- SPY options bid-ask spread: ≈ 0.5-2% of premium
- Commission: $0.50-0.65 per contract
- Slippage: depends on expiry and strike

```python
daily_turnover = np.abs(np.diff(weights))
costs = daily_turnover * 0.0002
net_returns = gross_returns - costs
```

## Look-Ahead Bias Checklist
- [ ] All signals use t-1 or earlier data
- [ ] VIX signal uses yesterday's close
- [ ] Model params estimated only on training data
- [ ] Cost based on execution-time spread
- [ ] No OOS data used in any decision

## Options Strategies
⚠️ **Cannot use BS simulation as backtest** — need real IV surface data.
BS ignores IV skew (real OTM put IV = 1.5-2x ATM), real bid-ask (5-10%).

## Strategy 5: Hybrid Volatility Targeting (Recommended)

When VIX/GARCH ratio > 1.3 → switch VT weight from GARCH σ to VIX-implied σ:
- 16 years (2010-2026): Sharpe ~2.0, MaxDD -9.2%, $1M→$17.4M
- All 3 regime periods (post-GFC, low-vol, crises) Sharpe > 1.87
- Transaction cost robust (+0.12 Sharpe advantage at all cost levels)
- Implemented in `scripts/daily_update.py`
- Mechanism: captures VRP through VT framework (VIX systematically > realized vol)
- **10/10 historical crises protected** (avg +8.7pp over buy-and-hold): COVID +23.5pp, GFC +16.3pp, 2022 Rate +10.9pp
- **Threshold robust**: Sharpe [0.93, 0.98] for all thresholds in [1.0, 1.6]
- **Beats both pure strategies**: Hybrid Sharpe 0.94 > VIX-only 0.89 > GARCH-only 0.79

### Hybrid VT Mechanism Details
- VIX/GARCH ratio > 1.3 occurs ~49% of time (autocorr 0.76, P(stay|above)=83%)
- VRP crisis cycle: pre-crisis VIX spikes first → GARCH lags → ratio expands → deleveraging. Peak crisis GARCH catches up → ratio falls (COVID ratio=0.71) → re-leveraging = buy the dip. Recovery: gradual normalization.
- **Compensates GARCH persistence bias**: w=504 underestimates half-life by 22 days → re-leverages too early. VIX stays elevated longer → natural correction.
- Henriksson-Merton: α=5.77% ann (t=3.99). NOT directional timing (γ=-0.043). Alpha from variance management.
- Treynor-Mazuy: GARCH VT γ=-0.50 (excessive concavity), Hybrid γ=-0.15 (reduced). Hybrid captures more recovery upside.
- Factor decomposition: Hybrid VT ≈ 31% market + short VIX (β=-0.017, t=-25.0) + 4.8% residual alpha (t=4.77)
- Drawdown profile: MaxDD -13.2% (vs BH -33.7%), %time DD>10% = 3.5% (vs 13.3%), Ulcer Index 4.10% (vs 6.67%)
- Dollar value: $867K saved per $1M across 10 crises (54% damage reduction)

### Crisis Hedge Effectiveness (10 crises, 2008-2026)
- Financial crisis (GFC-type) → GLD best hedge (+16.8%)
- Monetary tightening (2022) → GLD best (TLT -29.3%)
- Pandemic (COVID) → TLT best (+14.2%)
- Oil supply shock (2026 Iran) → CASH best (GLD -6.0%, TLT -3.4%)
- **Hybrid VT's cash allocation is the universal best**: type-agnostic, no need to detect crisis type

## Failed Strategies (documented)
- VRP directional trading: not a direction signal
- VIX term structure daily: works monthly, not daily
- Naked short puts: 99% win rate but net negative
- Regime overlay: redundant with vol targeting
- Adaptive window switching: doesn't beat fixed threshold
- Cross-asset VaR overlay (USO vol → SPY): null result, R² +0.06pp only

## Advanced Techniques

### Distribution Exploration
- **GED**: `--dist ged` — slightly fatter tails than Normal, often fixes VaR 1% issues. Good in low-vol, insufficient for high-vol level shifts.
- **Skewed-t**: `--dist skewt` — captures both skewness and fat tails simultaneously.
- **FHS (Filtered Historical Simulation)**: Non-parametric, needed for crypto (BTC) where parametric distributions fail.

### Custom Model Design
Use `CustomVolModel` base class to design volatility equations:
- **GJR-Floor** (`gjr_floor`): volatility floor prevents extreme compression → improves VaR
- **GJR-Adaptive** (`gjr_adapt`): base volatility adjusts via recent MA → responds to regime changes
- **GJR-HAR** (`gjr_har`): multi-scale HAR embedded in GARCH → best cross-OOS robustness
- All custom models use multi-start MLE (built into `CustomVolModel.fit()`)

### Forecast Combination
- Simple weighted average often beats single models
- Typical best combo: 70% best-QLIKE model + 30% most-robust-VaR model
- Combined forecasts almost always pass VaR tests (conservative model mixed in)

### Cross-OOS Robustness
- **Always** test 2+ different OOS periods (e.g., 2022-2023 high-vol + 2023-2024 low-vol)
- Single-OOS best may not be robust (e.g., GJR/Normal VaR PASS in one period, FAIL in another)
- Robustness > marginal QLIKE improvement

### GARCH Stacking (2024-2025 SOTA)
- Use multiple GARCH conditional variances as features
- Add HAR features: r²_lag, MA5_r², MA22_r², asymmetric_r²
- Meta-learner: Ridge or XGBoost for optimal combination weights
- This is model stacking / meta-learning applied to volatility

### Online Learning
- Periodically search "state of the art volatility forecasting [current year]"
- Focus areas: GARCH-informed neural networks, Realized GARCH, Transformer architectures
- Pipeline: understand core concept → design simplified version → implement with CustomVolModel → test

### 2025-2026 文獻 SOTA（WebSearch 2026-03-15）
- **Hybrid GARCH+DL 是共識** — 不是 DL 取代 GARCH，而是結合兩者
- **KAN-GARCH-MIDAS** (2025): Kolmogorov-Arnold Network + GARCH-MIDAS，用 KAN 提取非線性總經特徵
- **CNN-Transformer hybrids**: 結合 CNN 局部特徵提取 + Transformer 長程依賴，勝過純 LSTM
- **DL 在中長期勝出**: ML-based 模型在 multi-horizon 一致勝過 GARCH/HAR-RV
- **關鍵比較研究**: 2000-2025 數據，HAR-RV/ARIMA/GARCH vs LSTM/CNN-LSTM/PatchTST/Vanilla Transformer
- **啟示**: 我們的 Phase F 失敗因為 (1) 數據太少 (2) 用純架構而非 hybrid (3) 沒做消融研究

## Parkinson RV Proxy Notes
- Parkinson underestimates true volatility by ~37% (ignores overnight gaps)
- QLIKE ranking remains valid (bias is equal across all models)
- R²-log evaluation: use squared returns instead

## Strategy Report Must Include
1. Strategy logic: why does this work? Financial intuition?
2. Trade rules: when buy/sell/hold? Trigger conditions?
3. Trade frequency: daily/weekly/monthly?
4. Turnover: annualized turnover rate?
5. Pre-cost and post-cost returns (both required)
6. Full metrics: Sharpe, Sortino, Calmar, MaxDD, Win Rate, Profit Factor, VaR/CVaR 95%/99%, Worst Day, Tail Ratio
7. Dollar amounts: assume $1M initial investment
8. Annual breakdown: returns and Sharpe per year

## Operational Manual Template (for published strategies)
```markdown
## 策略操作手冊

### 觸發條件
- 何時開始：...
- 何時結束：...

### 每期操作步驟（如每週五）
1. 獲取 GARCH 預測的 sigma
2. 計算目標持倉比例：weight = target_vol / sigma
3. 判斷：weight > 當前持倉 → 買入，< → 賣出
4. 持倉上限/下限：0% ~ 200%

### 風險控制
- MaxDD 超過 X% → 停損？繼續持有？
- 模型異常（sigma 跳躍 10x）→ 如何處理？

### 成本假設
- 單邊交易成本：0.02%
- 預期年化成本：Y%
```
