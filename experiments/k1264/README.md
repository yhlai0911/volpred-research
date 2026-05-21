# K1264: TX Futures Overnight Gap Strategy

- **Experiment ID**: K1264
- **Status**: FAIL — listing rejected
- **提出**: 用戶 / **執行**: Claude
- **Date**: 2026-05-02
- **Codex review**: PASS (no issues flagged on K1264 in working-tree review)

## 動機

延伸 K515 + K625 兩個既有 finding：

- **K515**: SPY ETF 上 overnight gap alpha 真實 — SPY-conditioned mean = 10.73bp/day, t=4.06
- **K625**: SPY ETF 路徑 cost killer — 0.04275%×2 commission + 0.1% ETF tax = 18.55bp round-trip → 完全吃掉 alpha

**K1264 假說**：台指期貨（TX）round-trip cost ~5bp（2.5bp/leg × 2），比 ETF 18.55bp 低 73%。
若 TX 本身有類似 SPY 的 overnight gap alpha，可能是第一個能上架的新策略。

## 假設

- **H0**: TX overnight gap (close → next-open) Net Sharpe ≤ 0 after 5bp cost
- **H1**: Net Sharpe > 0.5 + cross-OOS 4/5 → listing candidate
- **H2**: SPY-conditioned 條件報酬 ≥ unconditional 1.5×

## 方法

### 數據
- **TX 期貨**：TAIFEX tick CSVs（`/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_*TX.csv`）
- **期間**：2017-05-16 → 2026-04-28（夜盤導入後一致期間，n=2179 trading days）
- **解析**：每日抽 day-session 第一筆 tick (≥08:45) 為 open、最後一筆 tick (≤13:45) 為 close
- **Expiry filter**：選 day-session max-volume expiry month
- **零夜盤**：避免 K842 系列 22:00-03:00 noise（per error_log）
- **SPY**：yfinance daily OHLC，`spy_overnight = (Open_t - Close_{t-1}) / Close_{t-1}`

### 訊號（含 lookahead 防護）
- **S1 Unconditional**: 永遠 long TX overnight (close at t → open at t+1)
- **S2 SPY-conditioned**: long TX overnight only if SPY_overnight from US date <= TW_date - 1 > 0
  - Implementation: `_lookup_date = TW_date - 1 day` + `merge_asof backward` → 嚴格 t-1 alignment
  - **無 lookahead**：今日 TX 持倉 = 昨日 SPY overnight 訊號
  - Random seed = 42

### Cost
- 5bp round-trip per signal=1 day（2.5bp/leg × 2 legs）
- 套用：`net_return = gross_return - 5bp` 在每個訊號日

### Three-Gate Listing
1. Net Sharpe > 0.5
2. |t-stat| vs zero > 3.0 (Harvey 2016 threshold)
3. Cross-OOS 4/5 個年度 (2018/2020/2022/2023/2024) 同方向 (positive Sharpe)

## 結果

### 主要表現

| 指標 | S1 Unconditional | S2 SPY-conditioned |
|------|---|---|
| Trades | 2179 | 1249 (57.3% exposure) |
| Gross Sharpe | **1.045** (t=3.07) | 0.795 (t=2.34) |
| Net Sharpe (5bp) | **0.200** (t=0.59) | 0.112 (t=0.33) |
| Ann Net Return | 2.98% | 1.19% |
| Net MDD | -39.71% | -27.36% |
| Net Win Rate | 54.2% | 53.6% |
| Cross-OOS 4/5 | 3/5 | 3/5 |

### Gap return diagnostics
- Mean = **6.18 bps/day** (vs K515 SPY 10.73 bps SPY-cond)
- Std = 93.96 bps/day
- T-stat (gross) = **3.07** (significant alpha exists)
- 但 5bp cost 吃掉 81% gross return（15.59% → 2.98% ann）

### Holiday-gap 診斷（非常重要的發現）
| Gap days | n | Mean (bps) |
|---|---|---|
| 1 (normal Mon-Thu) | 1697 | **+7.72** |
| 3 (Fri→Mon) | 397 | +1.01 |
| ≥4 (holiday) | 62 | **-9.33** |

→ Overnight premium 主要存在於 **normal 1-day gaps**；長假 gap 不僅無 premium，還反向。

### H2 SPY-conditioning fails
- Unconditional gap mean = 6.18 bps
- SPY-conditioned gap mean = 5.82 bps (ratio = 0.94)
- **SPY signal 沒有 enhance condition**（K515 SPY ETF 上 SPY-cond 反而比 uncond 高 → TX 上 contagion 更弱）

### Three-Gate Listing Decision

| Gate | S1 | S2 |
|---|---|---|
| Net Sharpe > 0.5 | FAIL (0.200) | FAIL (0.112) |
| \|t\| > 3.0 (net) | FAIL (0.59) | FAIL (0.33) |
| Cross-OOS 4/5 | FAIL (3/5) | FAIL (3/5) |
| **Verdict** | **REJECT** | **REJECT** |

**Listing recommendation: NO**

## 結論

1. **TX 期貨確實有 overnight gap gross alpha**（Sharpe 1.045, t=3.07）— 與 K515 SPY ETF finding 一致；alpha 不是 SPY-specific artifact
2. **5bp 成本仍然太高** — 81% gross return 被 cost 吃掉，net alpha t-stat 0.59 不顯著
3. **Cross-OOS 不穩** — 2018/2022 兩個 bear/correction year 嚴重虧損（-19% / -19%）
4. **SPY conditioning 對 TX 失效** — TW vs US contagion 在 K515 ETF 上有效（10.73bp）但 TX 上沒有 lift（ratio 0.94）
5. **Holiday gap 反向** — 長假 (≥4 day) overnight return = -9.33 bps；Friday→Monday 也僅 +1.01bp（顯著低於 normal 7.72bp）

### 替代研究方向（若要重啟）
- 進一步降 cost：找 broker 提供 1.5bp/leg → round-trip 3bp 才可能 Net Sharpe > 0.5
- Filter: 只在 normal 1-day gap 交易（exclude Fri→Mon 與 holiday）→ avg 7.72bp，剩 1697 days
- 結合 vol regime filter (e.g., VIX < 25)
- 注意 2018/2022 系統性 fail → 需 regime-based timing，否則 MDD 39% 不可接受

## 防錯規則 compliance

- ✅ `signal.shift(1)` via `_lookup_date = date - 1 day` + `merge_asof(direction='backward')`
- ✅ Fixed seed = 42
- ✅ 零夜盤（per K842 lessons）
- ✅ Friday→Monday vs holiday gap 分開報告
- ✅ 同 lag for baseline/treatment（S1/S2 共用 gap_ret）
- ✅ Codex review 跑過（working-tree review，K1264 無 issues 被 flag）
- ✅ Honest negative result — 不過度宣稱

## Files

- `k1264.py` — full reproducible script
- `k1264_results.json` — per-strategy / cross-OOS / gates 完整結果
- `k1264_cumulative_return.png` — cumulative net return curve
- `k1264_cross_oos_bar.png` — cross-OOS bar chart per year

## References

- K515: SPY ETF overnight gap alpha 10.73bp/day t=4.06
- K625: SPY ETF cost-killing 18.55bp round-trip
- K843: TAIFEX tick parsing pattern (Big5 encoding, max-volume expiry)
- Lou, Polk, Skouras (2019) JFE: "A Tug of War: Overnight vs Intraday Expected Returns"
- research_program.md L422-427 設計骨架

## Reproduce

```bash
uv run --no-project python experiments/k1264/k1264.py
```

Sample run with 80 files (smoke test)：
```bash
K1264_SAMPLE_LIMIT=80 uv run --no-project python experiments/k1264/k1264.py
```

Elapsed: ~26s on full 2180 files (8 worker parallelism).
