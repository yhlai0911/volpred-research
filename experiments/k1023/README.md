# K1023: E(g)=1 Self-Consistency Framework — Theoretical Foundation for Source Decomposition

## 動機

Paper 9 的 Codex adversarial review 指出 "source decomposition into τ×g may be just relabeling"。本實驗提供正式的理論推導 + 數值驗證，證明乘法分解框架具有真正的經濟內容，不只是重新命名。

## 研究問題

1. E(g)=1 約束如何識別 τ 和 g 的 scale？
2. θ₁ 的估計如何自動校正 VRP？
3. g 的動態是否追蹤 VRP 的時序變化？
4. Free omega 如何與 constrained 在 VRP 校正通道上不同？
5. 這個分解為什麼不是 relabeling？

## 方法

### 理論部分（theory_derivation.md）
- **Proposition 1**: E(g)=1 下的無條件方差恆等式
- **Proposition 2**: θ₁ < 1/(252×10000) 的 VRP 自動校正
- **Proposition 3**: g 追蹤 VRP 偏離長期均值的動態
- **Proposition 4**: Free omega 的 VRP 通道分裂

### 數值驗證部分（k1023.py）
- 資產: SPY (2005-01-04 to 2026-04-09, n=5,349)
- VIX: ^VIX (yfinance), lagged 1 day
- 模型: A4 (constrained, E(g)=1) vs A4f (free omega)
- 全樣本估計（理論驗證用，非 OOS）

## 結果

### Proposition 1: E(g) 恆等式
| 指標 | A4 (constrained) | A4f (free omega) |
|------|------------------|------------------|
| Theoretical E(g) | 1.000 | 0.482 |
| Empirical E(g) | 0.922 | 0.395 |
| Identity error | 0.003% | < 0.01% |
| Corr(τ,g) | 0.493 | 0.516 |

- E(σ²) = E(τ)·E(g) + Cov(τ,g) 恆等式精確成立（誤差 < 0.003%）
- **誠實報告**: Corr(τ,g) ≈ 0.49 不可忽略。簡化近似 E(σ²) ≈ E(τ) 只是粗略的
- E(g) 經驗值偏離理論 8%，來自有限樣本效應 + VIX 水準非定態

### Proposition 2: VRP 自動校正
| 模型 | θ₁ ratio vs no-VRP | VRP 校正通道 |
|------|-------------------|-------------|
| A4 (constrained) | 0.781 < 1 | θ₁ 折扣 21.9% 隱含方差 |
| A4f (free omega) | 1.957 > 1 | E(g)=0.48 吸收 VRP（θ₁ 高估由 E(g) 補償）|
| A4f effective | θ₁×E(g) = 0.943 | 兩通道合計 ≈ 5.7% 折扣 |

- 平均 VRP = 18.0% of implied variance（獨立測量）
- Constrained: 所有 VRP 校正集中在 θ₁ < benchmark
- Free: VRP 校正分裂成 θ₁ (marginal) 和 E(g) (level)

### Proposition 3: g 追蹤 VRP
| 方法 | Spearman ρ | 解釋 |
|------|-----------|------|
| Direct g_t vs VRP | 0.062 | Weak — τ 已移除 VRP 信號 |
| g_proxy (σ²/VIX²) vs VRP | 0.228 | GARCH 平滑後的信號 |
| Raw r²/VIX² vs VRP | -0.688 | 原始比值（噪音大）|
| K988b OOS g_proxy vs VRP | 0.78-0.82 | Rolling refit 捕捉時變參數 |

- g>1 ↔ VRP<0 方向性一致: 69.5%
- Direct g_t 弱相關是 **by construction**（τ 移除了 VRP 信號）
- K988b 的高 ρ 來自 OOS rolling refit，非全樣本

### Not Relabeling 的五條證據
1. **參數識別**: τ 有參數形式 θ₀+θ₁VIX²，θ₁ 有 VRP 經濟解釋
2. **E(g)=1 識別**: 沒有此約束，(cτ, g/c) 對任何 c>0 觀測等價
3. **θ₁ < 1**: 直接測量 VRP 校正比例
4. **預測增益**: DM t=+4.48 vs GJR（K988），Harvey 門檻顯著
5. **g-proxy 追蹤 VRP**: ρ=0.78-0.82（K988b OOS）

## 結論

1. E(g)=1 約束提供了唯一識別，使 τ 和 g 各自有明確的經濟意義
2. θ₁ < no-VRP benchmark 是 MLE 自動進行的 VRP 校正，不是任意的 shrinkage
3. Free omega 允許 VRP 校正在 θ₁ 和 E(g) 之間分裂，提供額外的靈活性
4. 乘法分解不是 relabeling——它有參數識別、經濟內容、和可檢驗的預測

## 局限性

- 全樣本估計用於理論驗證，非 OOS 績效評估
- Corr(τ,g) ≈ 0.49 使得 E(σ²) ≈ E(τ) 的近似不精確
- E(g) 經驗偏離 8% 反映非定態性
- 僅 SPY 單一資產
- VRP proxy 用 r² 而非 realized variance (5-min RV)

## 檔案

- `k1023.py` — 數值驗證腳本
- `k1023_results.json` — 完整結果
- `k1023_eg1_framework.png` — 六面板圖表
- `theory_derivation.md` — 正式理論推導 + LaTeX 公式
- `README.md` — 本文件

## 數據來源

yfinance: SPY (2005-2026), ^VIX (2005-2026). n=5,349. seed=42.

## 參考文獻

- Bollerslev, Tauchen & Zhou (2009). Expected Stock Returns and VRP. RFS 22(11):4463-4492.
- Engle, Ghysels & Sohn (2013). Stock Market Volatility. RES 95(3):776-797.
- Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.
- Conrad & Loch (2015). Anticipating Long-Term Volatility. JBES 33(3):338-358.
- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
