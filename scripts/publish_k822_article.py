#!/usr/bin/env python3
"""Publish K822 VIX Product Trading research article as draft."""

import sys
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')

from src.volpred.publisher.publisher import Publisher

CHART_URL = "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k822_sharpe_comparison_b1cfee.png"

CONTENT = """## 摘要

[提出: 用戶（會員提問驅動）, 執行: Claude]

GJR-GARCH 模型能以 67.9% 的準確率預測波動率方向（K787）。一個合理的問題是：這個優勢能否直接轉化為 VIX ETN 的交易利潤？K822 實驗給出了明確答案：**不能**。原因不在於方向預測失準，而在於 VIXY 的結構性 contango drag 已將所有潛在利潤侵蝕殆盡。

---

## 研究背景

| 項目 | 設定 |
|------|------|
| 數據期間 | 2018-01-03 到 2026-03-31（2071 交易日） |
| OOS 驗證期間 | 2023-01-01 到 2024-12-31（502 天） |
| 數據來源 | yfinance（VIXY, SPY, ^VIX） |
| Lag 處理 | 所有信號均 signal.shift(1) 強制執行，無 lookahead |
| 交易成本 | 每次調倉 10bps |
| GJR 重新估計 | 每 63 天（共 33 次） |

研究問題源自用戶提問：「預測波動率方向準確率 67.9%，為何不直接交易 VIXY 等 VIX ETN？」

---

## 核心發現一：VIXY 的結構性死亡螺旋

VIXY（ProShares Short-Term VIX Futures ETF）的運作機制是持續買入近月 VIX 期貨並滾倉至次月。在 VIX 期貨市場長期處於 contango 結構下（近月價格低於遠月），每次滾倉本身就是一筆必然的損失。

**全期 Contango 分析（2018-2026）**

| 指標 | 數值 |
|------|------|
| VIXY 年化報酬 | **-47.52%** |
| SPY 年化報酬 | +13.31% |
| VIXY 累積總報酬 | **-99.99%**（幾近全滅） |
| 平均月度 contango drag | -3.73%/月 |
| 中位數月度 drag | -7.1%/月 |
| 負報酬月份比例 | 67.2% |

即便不做任何擇時，單純持有 VIXY 8 年後損失接近 100%。這不是市場波動的結果，而是 ETF 結構本身設計導致的必然結局（Eraker & Wu, 2017）。

---

## 核心發現二：方向準確 ≠ 盈利

這是 K822 最關鍵的 insight。即使 GJR-GARCH 正確預測波動率上升，在 VIXY 上做多仍然平均虧損。

**方向預測 vs VIXY 實際報酬**

| 情境 | VIXY 往正確方向走的機率 | VIXY 平均日報酬 |
|------|----------------------|----------------|
| GJR 預測 vol rising（應做多 VIXY） | **39.0%**（低於隨機） | **-0.1234%/天** |
| GJR 預測 vol falling（應做空 VIXY） | 58.6% | -0.0691%/天 |

統計檢定：在 vol rising 天做多 VIXY，t = -0.475，p = 0.635——正報酬統計上完全不顯著。

關鍵洞察：即使 VIX 本身當天上漲，VIXY 的滾倉成本也會在同一天侵蝕收益。波動率的「方向」和 VIXY 的「報酬」之間存在一個幾乎無法彌補的結構性 gap。

---

## VIX Spike 的不對稱性與幻覺

有人可能認為：抓住 VIX 大漲的那幾天就夠了。數據顯示 VIX spike 時 VIXY 確實大漲：

| 情境 | 天數 | VIXY 平均漲跌 |
|------|------|--------------|
| VIX 日漲幅 > 5% | 419 天 | **+6.29%** |
| VIX 日跌幅 > 5% | 444 天 | **-4.67%** |

但問題在於 spike 在 2071 天中只有 419 天（約 20%），且需要在 spike 前一天就進場。在等待 spike 的其餘 80% 交易日，每天的 contango drag 持續運轉（平均 -3.73%/月）。等待成本遠高於 spike 收益。

---

## 全期策略績效比較

![K822 各策略 Sharpe Ratio 比較（2018-2026）]({chart_url})

**全期（2018-2026，N=2071 天）**

| 策略 | 年化報酬 | Sharpe | MDD |
|------|---------|--------|-----|
| **S0: BH SPY（基準）** | **+14.18%** | **0.734** | -33.7% |
| BH VIXY（持有不動） | -20.72% | -0.274 | -99.5% |
| S1: Long VIXY（GJR vol rising） | -16.61% | -0.367 | -93.1% |
| S2: Short VIXY（GJR vol falling） | +4.11% | 0.068 | -83.9% |
| S3: Long/Short VIXY | -12.49% | -0.165 | -97.3% |
| S2B: Short VIXY（VIX < 20dMA） | +10.01% | 0.233 | -66.5% |
| S4: Vol-Weighted VIXY | -12.78% | -0.691 | -71.9% |

DM Test 結論：只有 S4 達到 Harvey t > 3.0（t = 3.156），但其 Sharpe = -0.691，遠劣於 BH SPY。其他策略均未達統計顯著性門檻（Harvey threshold）。

---

## Short VIXY 的誘惑與陷阱

放空 VIXY 能收取 contango roll yield，在 OOS 期間（2023-2024）表現亮眼：

**OOS 期間（2023-2024，N=502 天）**

| 策略 | 年化報酬 | Sharpe | MDD |
|------|---------|--------|-----|
| **S0: BH SPY（基準）** | +23.66% | **1.847** | -10.0% |
| S2: Short VIXY（GJR） | +55.77% | 1.119 | **-42.3%** |
| S2D: Short VIXY（複合信號） | +66.90% | 1.287 | **-35.6%** |

但這忽略了 Short VIXY 的致命弱點：**尾部風險**。全期 MDD 高達 -83.9% 到 -97.3%。2020 年 3 月 COVID crash 時 VIX 從 12 飆至 85，Short VIXY 策略幾乎遭遇毀滅性損失。

Whaley (2013) 指出，持有 Short VIX 策略就像定期收取保費、卻可能在 tail event 時一次性賠光——這種「steamroller 前撿硬幣」的風險結構使得 Short VIXY 不適合散戶投資人。

---

## 結論

K822 的核心發現可用一句話總結：**波動率預測準確性與 VIX ETN 盈利之間存在一道無法逾越的結構性鴻溝，名為 contango。**

具體而言：

1. VIXY 的 contango drag（平均 -3.73%/月）在任何方向信號到達前就已啟動
2. 即使 GJR 正確預測 vol rising，VIXY 在這些天平均仍然虧損 -0.1234%/天
3. 所有測試策略（Long/Short/L-S）在全期均無法達到 BH SPY 的 Sharpe（0.734）
4. Short VIXY 雖能收取 roll yield，但尾部風險（MDD -42% 到 -93%）使其不適合一般投資人

**實務建議**：VIX 的預測能力應用於調整股票部位的波動率目標（如 12/VIX 或 GARCH VT 策略），而非直接交易 VIX 衍生產品。相關見 K762、K687 等策略實驗。

---

## 研究限制

1. VIXY 經歷多次反向分割，調整後價格可能存在 survivorship 問題
2. Short VIXY 策略假設借券可取得且成本為零（實際借券費用 1-3%/年）
3. 10bps 交易成本可能低估 VIX 產品真實執行成本（bid-ask spread 可達 20-50bps）
4. GJR-GARCH 方向準確率在此樣本與 K787 略有差異（窗口/重新估計頻率不同）

---

## 參考文獻

- Eraker & Wu (2017) "Explaining the Negative Returns to VIX Futures and ETNs," Journal of Financial Economics
- Whaley (2013) "Trading Volatility: At What Cost?," Journal of Portfolio Management
- Alexander & Korovilas (2013) "Diversification of Equity with VIX Futures," Journal of Index Investing
- Bordonado, Molnar & Samdal (2017) "VIX Futures as a Market Timing Indicator," JDF
- 相關實驗：K787（GJR 方向準確率 67.9%），K697（方向相關係數 0.04），K762（VIX 策略 regime filter）

---

*實驗腳本: experiments/k822_vix_product_trading.py*
*結果數據: experiments/k822_vix_product_trading_results.json*
*數據來源: yfinance（VIXY, SPY, ^VIX），期間：2018-2026，樣本：2071 交易日*
""".format(chart_url=CHART_URL)


def main():
    pub = Publisher()
    result = pub.publish_milestone(
        title='K822: 方向對了也賺不到錢——VIXY 的 Contango 結構性死亡螺旋',
        description=CONTENT,
        phase='research',
        tags=['研究', 'VIX', 'VIXY', 'contango', '波動率交易', 'GJR-GARCH', 'ETN', 'SPY'],
        status='draft'
    )
    print('Published result:', result)


if __name__ == '__main__':
    main()
