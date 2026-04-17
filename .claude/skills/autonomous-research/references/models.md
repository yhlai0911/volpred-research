<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# Volatility Models Reference

## Registered Models (14 total)

### Standard (arch package wrappers)
| Model | Key | Best Use |
|-------|-----|----------|
| GARCH(1,1) | `garch_arch` | Baseline, VaR-safe |
| EGARCH | `egarch_arch` | ⚠️ Numerical instability in rolling |
| GJR-GARCH | `gjr_arch` | **Best QLIKE** when γ t-stat > 1.65 (equities, NOT gold) |

### Custom MLE (scipy L-BFGS-B)
| Model | Key | Innovation |
|-------|-----|-----------|
| Custom GARCH | `garch_custom` | MLE validation |
| Custom EGARCH | `egarch_custom` | Log-variance recursion |
| Custom GJR | `gjr_custom` | Multi-start MLE |

### Experimental (research-designed)
| Model | Key | Innovation |
|-------|-----|-----------|
| GJR-Floor | `gjr_floor` | Volatility floor prevents VaR compression |
| GJR-Adaptive | `gjr_adapt` | MA-based omega adjustment |
| **GJR-HAR** | `gjr_har` | Multi-scale HAR in GARCH — **best cross-OOS VaR** |
| Component GARCH | `cgarch` | Engle-Lee 1999, slow+fast components |
| GJR-Range | `gjr_range` | OHLC range as additional regressor |
| GJR-Overnight | `gjr_overnight` | Overnight return² regressor |

### Non-GARCH
| Model | Key | Innovation |
|-------|-----|-----------|
| HAR-RV | `har_rv` | Corsi 2009, regression-based |
| CARR | `carr` | Chou 2005, range-based (has bias) |

## Minimum Sample Size for GARCH Estimation
- ARCH(1): ≥250 observations
- **GARCH(1,1): ≥500 observations**（實務最低門檻）
- **推薦: ≥1000 observations**（穩定估計，避免局部最優）
- <700 observations: 可能有多個最優解（Hwang & Valls Pereira 2006）
- alpha 接近 0 時：即使 1000 obs 也可能不夠（Zivot 2008）
- **Rolling window=252 低於 500 門檻** → 可能導致參數不穩定
- Window=504 改善可能部分因為滿足了最低門檻

Sources: [Hwang & Valls Pereira 2006](https://www.tandfonline.com/doi/abs/10.1080/13518470500039436), [Zivot 2008](https://faculty.washington.edu/ezivot/research/practicalgarchfinal.pdf), [2024 GARCH sample sizes](https://www.tandfonline.com/doi/full/10.1080/03796205.2024.2439099)

## Asset-Specific Optimal Window Size
- **SPY**: w=504 default (wins in extreme crisis e.g. COVID); w=5000 wins in 3/6 OOS periods (calm+moderate crisis)
- **TLT**: w=504 (升級自 w=252; w=252 在 2026 VaR 5% 失敗)
- **GLD**: w=504 (regime-dependent leverage, need to capture recent regime)
- **QQQ**: w=504-756 (tech sector adds volatility, longer window marginally better)
- **EEM**: w=504 (stable, std=0.017, γ=+0.34 → use GJR)
- **BTC**: w=252-378 (highest base vol → recent data most relevant)
- **General rule**: higher base volatility → shorter optimal window. But w=504 works within 1% of optimal for all assets except BTC.
- **Window QLIKE U-shape (SPY)**: w=504 (0.540), w=1000-2000 worst (0.555-0.560), w=5000 best (0.529). But regime-dependent: extreme crisis → w=504, calm/moderate → w=5000. Adaptive window doesn't beat fixed.
- **Persistence bias**: w=504 underestimates persistence by -3.0% (half-life 14d vs true 36d). w=2000+ ~0% bias. This causes VT to re-leverage ~22 days too early after crises.

## Window Size Literature
- Hwang & Valls Pereira (2006): Monte Carlo — β bias at N=500 is -1.1% to -8.5%, convergence 89-99%. At N=1000: -0.5% to -6.7%.
- Ng & Lam (2006): recommend ≥1000
- Engle et al.: tested N=300, 1000, 5000. N=5000 for consistency.

## Key Findings
- QLIKE ceiling: -9.034 (GJR-arch, daily SPY, w=504)
- GARCH accuracy: 98.8% vs 5-min RV gold standard
- Multi-start MLE improves custom models 0.25-0.48%
- EGARCH false convergence in regime-change windows
- Ljung-Box: ALL window sizes (126-1000) produce iid residuals — GARCH structure sufficient at any N
- Parkinson RV underestimates true vol ~37% (overnight gap bias)

## Cross-Asset Model Selection Rules
**Use γ direction, NOT skewness:**
- **γ t-stat > 1.65 AND γ > 0** → use GJR (equities SPY/QQQ/EEM, ETH)
- **γ < 0** → use GARCH (gold GLD in bull market, supply-shock commodities JO/UNG/WEAT)
- **γ ≈ 0** → use GARCH (bonds TLT, commodity baskets DBA)
- **GLD is regime-dependent**: bull market γ<0 (inverted), bear market γ>0 (standard) — check quarterly
- Improved rule: use 4-quarter γ average (100% OOS accuracy vs 83% single-point)
- Monte Carlo validated: 95% accuracy (300 simulations, 3 DGPs)
- Crypto → needs independent analysis + FHS VaR

## Leverage Direction Research Findings
- **Leverage direction is regime-dependent for some assets**: GLD in bull→inverted, bear→standard; USO in normal→standard, supply shock→inverted. Check γ quarterly.
- GLD inverted leverage: HAC-corrected t = −5.79, p < 0.001. 93% quarterly negative in bull markets. Reversed to +0.17~+0.30 in 2013-2015 bear market.
- 2026 Q1: GLD γ=-0.221 (strongest inverted), USO γ=-0.133 (inverted deepened during Iran crisis)

## VaR/ES Research Findings
- **Student-t(df=5) >> Normal** for VaR: reduces violations by 21-48%
- **Fixed df=5 >> jointly estimated df** (17 vs 24 violations for SPY). Joint estimation over-adapts in quiet markets.
- **VIX/GARCH ratio > 1.5 → VaR unreliable** — 94% of VaR violations occur in this state
- Multi-step VaR: use proper GARCH h-step formula σ²_h = h×σ²_∞ + (σ²_1-σ²_∞)×(1-ρ^h)/(1-ρ), not naive σ×√h

## Claude Model / Agent 選擇原則

| 任務類型 | 模型 | 原因 |
|---------|------|------|
| **研究實驗**（GARCH、統計檢定、策略回測） | `model: "opus"` | 精確性與專業性要求高 |
| **程式開發**（前端、後端、bug 修復） | `model: "opus"` | 程式碼正確性關鍵 |
| **統計分析**（DM test、bootstrap、cross-OOS） | `model: "opus"` | 數學嚴謹性不可妥協 |
| **論文寫作/審查** | `model: "opus"` | 學術品質要求 |
| 簡單搜尋（grep、檔案查找） | `subagent_type: "Explore"` | 快速唯讀 |
| 簡單文章撰寫（feed 文章） | `model: "sonnet"` 可接受 | 創意寫作彈性較大 |
| 規劃與架構 | `subagent_type: "Plan"` | 結構化思考 |

**規則：研究、分析、程式等精確性工作，務必使用 opus。不確定時預設 opus。**

## 硬體資源

| 項目 | 規格 |
|------|------|
| CPU | Apple M1 Max · 10 核心 |
| RAM | 64 GB |
| 平行 agent 建議 | 3-4 個 worktree agent 同時跑（每個 ~1GB RAM） |
| GARCH 估計速度 | ~6ms/model（單核） |
| Bootstrap 10,000 reps | ~2-5 秒 |
