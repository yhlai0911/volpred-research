---
title: "把分散度再精煉一次，還是救不了策略：K809 的答案很乾脆"
audience: general
status: draft
tags:
  - SPY
  - dispersion
  - sector rotation
  - volatility
  - 策略研究
experiment_refs:
  - K809
---

# 把分散度再精煉一次，還是救不了策略：K809 的答案很乾脆

有一種很常見的研究直覺是這樣：

如果 raw signal 沒有用，也許不是概念錯了，而是訊號還太粗。

`K771` 之前測過一次類股 dispersion timing，結論是 `NULL`。`K809` 做的不是重複，而是把同一個方向再推進一步：

**不要直接看分散度本身，而是看「類股分散度 ÷ SPY 自身波動率」這個 ratio。**

這個想法的邏輯其實不差。因為如果整個市場本來就很吵，單看類股之間的分散，可能只是把大盤自己的震盪也一起算進去。用 ratio 去 normalize，看起來更像是在抓「市場內部分化」這件事本身。

但結果很乾脆：

**就算把分散度做成 ratio signal，還是沒有穩定打敗 SPY。**

## Full sample 的結果，比想像中更直接

![K809 ratio vs baseline](experiments/k809/k809_general_ratio_vs_baseline.png)

`K809` 有四條線：

- `S0`：買進持有 `SPY`
- `S1`：買進持有等權類股
- `S2`：dispersion ratio 高於 expanding median 時切到類股，否則留在 `SPY`
- `S3`：用 ratio 平滑調整類股權重

看完整樣本，`SPY` 本身的 Sharpe 是 `0.815`。

然後三個你辛苦設計出來的版本，沒有一個超過它：

- `S1` = `0.791`
- `S2` = `0.762`
- `S3` = `0.804`

其中最接近的是平滑版 `S3`，但還是差一點。換句話說，這個方向不是「快成功了，只差微調」，而是 **連 normalize 之後，優勢還是沒有自然出現**。

## OOS 看起來比較溫柔，但還是不夠

![K809 cross OOS ratio](experiments/k809/k809_general_cross_oos_ratio.png)

如果只看最近一段 OOS，`S3` 的 Sharpe 有到 `1.626`，`S2` 也有 `1.310`。乍看之下，好像沒有那麼差。

但基準 `SPY` 同段是 `1.847`。

也就是說，即便在外樣本最好看的區段，這個 ratio 訊號還是沒有追上 baseline。

再把視角拉長到 `5` 個 cross-OOS 視窗：

- `S2` 只贏 `2/5`
- `S3` 只贏 `1/5`

這種結果有一個很明確的含義：訊號不是完全亂來，但它沒有形成跨 regime 的穩定優勢。偶爾有效，不等於可以放心拿來當規則。

## 這個失敗其實比表面更有資訊量

`K809` 最值得留下來的地方，不是它再一次 `NULL`，而是它幫你排除了另一種很容易自我安慰的說法：

**「前一個版本失敗，只是因為訊號定義還不夠精緻。」**

現在我們知道，至少在這條研究路線上：

- raw dispersion 不行
- dispersion ratio 也不行

這代表問題不只是 scaling，而更可能是這個訊號本身對 `SPY` 配置的增量太薄。

這也是為什麼 `K809` 和 `K771` 放在一起看很有價值。兩個版本都在測市場內部分化，但一個看 raw level、一個看 normalized ratio，最後都沒有打穿 baseline。當不同定義都指向同一個結果時，這個 `NULL` 反而更可信。

## 對投資人最有用的一句話

很多策略會給你一種「如果再多加一層處理，訊號就會乾淨很多」的感覺。

`K809` 的教訓是：

**把訊號做得更聰明，不保證會讓策略變得更強。**

有時候你只是在把一個本來就沒有厚度的訊號，包裝得更精緻而已。

## K809 的一句話結論

把類股分散度改寫成 dispersion ratio，並沒有救回 timing alpha。`K809` 最終仍然是一個乾淨的 `NULL RESULT`：這條訊號不只 raw 版本打不贏 `SPY`，ratio 版本也一樣。

## 資料來源

- 實驗編號：`K809`
- 腳本：`experiments/k809/k809_dispersion_timing.py`
- 結果：`experiments/k809/k809_dispersion_timing_results.json`
- 資料來源：`yfinance`
- 資料期間：`2011-02-01` 至 `2026-03-31`
