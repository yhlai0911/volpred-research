# FB Post Handoff — 5 Trending Reposts Pending Manual / Sidepanel Push

> Historical handoff only. Active rule is `docs/fb_pipeline_permanent_fix.md`: personal account + Claude-in-Chrome interactive posting; FB Page / Graph API was rejected and withdrawn.

**Updated**: 2026-05-19 17:10 CST
**Pending count**: 5 (was 4 in v1; +2 added 5/18; 2 marked wont_fix)
**Wont-fix**: `mile_ed85d127` (4d stale, no draft) + `mile_57894028` (1d, no draft, ROI low)

**Why not auto-posted**: Claude Code MCP claude-in-chrome NOT connected → cannot drive Chrome UI. Personal FB has no API. Historical standby was to connect the MCP browser extension; later Page/Graph API fallback was rejected, so current active path stays personal-account interactive posting only.

---

## Workflow per post

1. Open Facebook (https://facebook.com)
2. Click "Ivan Lai，在想些什麼？"
3. Paste FB POST block as main post
4. Click 發佈
5. After post appears, click 留言 → paste FIRST COMMENT block as first reply

## After posting all 5, run:

```bash
jq 'map(if .mile_id == "mile_ba1dc7f8" or .mile_id == "mile_207d3750" or .mile_id == "mile_dda1e670" or .mile_id == "mile_50f44a46" or .mile_id == "mile_dab6cc06" then .fb_post_status = "success" | .fb_posted_at = (now | strftime("%Y-%m-%dT%H:%M:%SZ")) else . end)' storage/reports/trending_repost_log.json > /tmp/trl.json && mv /tmp/trl.json storage/reports/trending_repost_log.json
```

---

## Posts (newest first)


=== mile_dab6cc06 (2026-05-18) ===
--- FB POST ---
storage/reports/fb_draft_oil_vix.txt
--- FIRST COMMENT (after posting) ---
https://volpred.zeabur.app/article/mile_dab6cc06


=== mile_ba1dc7f8 (2026-05-17) ===
--- FB POST ---
上週五，我打開帳戶。

股票跌，這個正常。

但往下看：黃金跌、長債跌、白銀跌了快 9%。

六個資產類別，同一天，沒有一個是正的。

通常是做不到這樣的。分散投資的邏輯是：股票跌，債券和黃金多少會撐一點。那天不是。

原因很明確：CPI 3.8% 超預期、PPI 創 2022 以來最大單月漲幅、油價 Brent $109。通脹預期在快速移動的時候，分散投資的前提條件就失效了。

我看了一下 VIX，只有 19。

這件事提醒我一個我其實知道但不常想到的事：VIX 只是股市的隱含波動率，不是你整個持倉的風險圖像。

分散投資的邊界條件是通脹穩定。當通脹是主角，相關矩陣就不是常數了。

2022 那年，股債同時跌了一整年。上週五的帳單，讓人想到那一年。

（連結在留言）
--- FIRST COMMENT (after posting) ---
https://volpred.zeabur.app/v3/reports/mile_ba1dc7f8


=== mile_207d3750 (2026-05-17) ===
--- FB POST ---
選擇權市場給 NVDA 財報定了 8% 的震幅。

過去四季財報當天：-0.5%、-0.1%、+2.8%、+1.4%。

超預期了四次，股票幾乎沒動過。

有人說市場不理性，有人說 AI 故事沒說完。
我比較在意的是另一件事——

那個 8%，不是在財報當天釋放的。
是在隔週，用整整五天的震盪，慢慢放完的。

Q4 FY26 最明顯：財報前一週年化波動率 9%，財報後一週跳到 58%。
漲了 1.4% 那天，之後五天在走什麼路徑？那才是關鍵。

5 月 20 日 NVDA 出財報。
方向猜不猜到是一回事。
但如果你手上有科技部位，財報後那一週的 RV 路徑，比 EPS 是否超預期更值得盯。
--- FIRST COMMENT (after posting) ---
https://volpred.zeabur.app/v3/reports/mile_207d3750


=== mile_dda1e670 (2026-05-16) ===
--- FB POST ---
看到一個數字停了一下。

Nikkei 過去一年漲 68%，但美元計價的 EWJ 只漲 32%。

中間 36 個百分點，主要被日圓貶值吃掉。

這個本來不奇怪。Abenomics 之後，弱日圓推日股，已經習慣了。

但有件事在悄悄變。

過去三個月，Nikkei 跟 USDJPY 的 60 日相關係數從 +0.31 翻到 −0.47。換句話說，「弱日圓利多日股」這個關係，現在反向。

Fisher z 檢定 p < 0.0001。不是噪音。

為什麼重要？因為對美元投資人，過去十年的對沖紅利是建立在「日股漲、日圓弱、兩邊抵銷」的同步上。

當這個同步斷掉，下一段如果日圓反彈、日股下殺，就是雙殺。EWJ 過去 30 天的波動 19%，會嚴重低估真實尾巴。

我在追的不是日股創高，是 USDJPY 會不會跌破 155。那才是 carry trade 平倉真正開始的訊號。
--- FIRST COMMENT (after posting) ---
完整版分析 + 圖表在這裡 → https://volpred.zeabur.app/article/mile_dda1e670


=== mile_50f44a46 (2026-05-16) ===
--- FB POST ---
看到 30 年公債殖利率 5.08% 和 VIX 18 同時存在，我停了一下。

這兩個數字本來不應該這樣排在一起。

債市說「出大事了」。Moody's 把美國降評，19 年來最高的長債殖利率，公債選擇權的波動率指數 MOVE 在拉警報。

但股市的恐慌指數 VIX 還在 18。正常市場的水準。

債市和股市在定價完全不同的風險。

這種情況發生過幾次。2011 年降評時 VIX 飆到 48，股市兩週跌 15%。2023 年 Fitch 降評時，幾乎沒人在乎，VIX 幾乎沒動。

現在更接近哪一個？從表面上看像 2023。但 2023 那次是市場預期降息，恐慌有出口。現在 Fed 沒有打算快速救援，30 年公債殖利率還在往上走。

這種股債波動率背離，通常不會持久。要麼債市先冷靜下來，要麼股市補跌一波。

我在觀察的是 MOVE 接下來怎麼走。那個訊號比 VIX 早說話。
--- FIRST COMMENT (after posting) ---
完整版分析 + 圖表在這裡 → https://volpred.zeabur.app/article/mile_50f44a46
