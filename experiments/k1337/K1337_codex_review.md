# K1337 Codex Review

**Date**: 2026-06-15 台灣時間
**Reviewer**: Codex CLI (gpt-5.4 medium, primary path)
**Verdict**: **FAIL**

## 主因 — Forward-label lookahead in expanding OLS

在預測 index `i` 時，訓練集用 `df.iloc[:i]`，但訓練列 `j` 的 `fwd_var(H)` 需要看到 `returns[j..j+H-1]`。當 `H>1` 時，靠近訓練尾端的列（`j` 滿足 `j+H-1 >= i`）其 `fwd_var(H)` 已看見「預測日之後」資訊 — coefficient 因此 contaminated。

**必修**：訓練集需限制到 `j + H < i`（即去掉訓練尾端 `H-1` 列）。

## 其他 caveats

1. **Regime contamination**：主預測 signal / HAR feature 有 `shift(1)`，但 regime label 用 raw `dslope`，rolling quantile 還包含當期值 — 不算 contamination-free。
2. **Baseline 不公平**：HAR baseline 在 level-space (raw OLS)，augmented 用 log-HAR stacking + clipping — model class 不同。應加同 model class 對照（兩邊都 log-space + clipping）。
3. **QLIKE 公式正確**；DM HAC lag=H-1 合理。
4. **Bootstrap** seed / block size 實作大致 OK，但 regime split 需先修上述 contamination。

## 結論強度

- 18/18 specs augmented WORSE — 可報，但目前只能說「**在此有瑕疵設計下**」；不可強化為「推翻 prior K」。
- **不推翻 K749 / K871**：NULL 方向合理（與 prior 一致），但**需重跑修正版本後才可信**。

## Action

- **Verdict: FAIL** → 不寫 knowledge.json（per `.claude/rules/experiments.md` K1259 process gate）
- 衍生 **K1337-v2** task：(a) 訓練 cutoff = `j + H < i`、(b) regime label 用 `dslope.shift(1)` 後的值算 rolling quantile、(c) augmented 與 baseline 同 log-space + clipping、(d) 重跑 18 specs + bootstrap
- 本實驗保留 `experiments/k1337/` 作為「flawed-design preliminary」存證
