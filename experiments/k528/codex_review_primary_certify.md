2026-07-27T00:29:22.648570Z ERROR codex_models_manager::cache: failed to load models cache: missing field `supports_reasoning_summaries` at line 88 column 5
OpenAI Codex v0.144.6
--------
workdir: /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: read-only
reasoning effort: xhigh
reasoning summaries: none
session id: 019fa0f9-f2ce-7622-8c03-e32eb0198d36
--------
user
你是資深計量財務審稿人，執行 VolPred K528 實驗「進 main 的唯一認證關卡」PRIMARY-PATH 審查。你的預算有限（<9 分鐘），請把預算全部花在下面六個檔案與指定的重算上，**不要 grep 整個 repo、不要讀 knowledge.json / error_log.md / storage/**。目標：交出一個明確的 VERDICT。

工作目錄 = 這個 git worktree 根。用 shell/jq/python 自己讀檔重算，但只碰下列檔案：
- experiments/k528/k528_nfp_event_study.py
- experiments/k528/k528_nfp_event_study_results.json
- experiments/k528/k528_nfp_official_dates_results.json
- experiments/k528/README.md
- experiments/k528/build_article_correction.py
- tests/test_nfp_official_release_dates.py
- （只在需要時）src/volpred/data/event_dates.py

## 背景（K528）
NFP 官方發布日對 SPY 日內波動的事件研究。前幾輪 Codex 抓到三類缺陷，本輪認證它們是否關閉。

## 我（主線程）已獨立重算並確認的數字，請你 VERIFY（自己重算對照，不要照抄）：
- headline（週五 session NFP vs 非 NFP 週五）：mean_ratio=1.18899、p_nominal=0.020854、n=237；Holm(confirmatory family=6)=0.041709 仍顯著；Holm(all 22 outputs)=0.375377 不顯著。
- vs 全體非 NFP：1.10778×、p=0.11206、不顯著。
- VIX regime：2.02730×、p=4.55e-9；VIX Pearson r=0.44044、p=1.98e-13；Spearman=0.34550、p=1.67e-8。
- 樣本：n_official=253，n_release_dated_friday=243，n_traded_in_friday_session=237，dates_in_common=212，n_proxy=254。
- n_claims_audited=6、n_claims_flipped=0（六格前後皆 nominal 顯著，無翻轉）。
- 六筆 Good Friday（release 在週五但下週一 session 吸收）：2007-04-06/2010-04-02/2012-04-06/2015-04-03/2021-04-02/2023-04-07 → 243−6=237。

## 三類缺陷，逐一裁 CLOSED / NOT CLOSED（附證據）
### A（v2）錯誤官方日期（off-cycle max() 污染）
六個同月多筆月份第一版誤取 max()（把年度季調修訂當就業報告），正確應取 min()：2006-05→05-05、2012-12→12-07、2013-05→05-03、2020-05→05-08、2024-01→01-05、2024-08→08-02。
驗證：現行結果 JSON 的事件集合是否用正確日期、六個 off-cycle 修訂日不在、六個正式發布日在。檢查 src/volpred/data/event_dates.py 的 per-month min() + cadence fail-closed 是否結構成立（不是只靠 fixture）。

### B（v2）污染日期下的假翻轉 + 據以撤回正確結論
第一次修正曾得出錯誤「顯著→不顯著」翻轉並準備 18 條文章更正（會撤回本來正確的結論），被二審 FAIL 擋下。
驗證：現行 headline 與 JSON 一致、n_claims_flipped=0、README 對「週五 session(237) vs 發布日在週五(243) vs 全部(253)」三種口徑的區分是否誠實無 overclaim；build_article_correction.py 是否真 dry-run（不寫 feed.json）；README 宣稱的更正是否與認證數字一致、無殘留假翻轉。

### C（v6）fail-closed 完整性 gate 可被繞過
六審發現：把端點月同時放進 KNOWN_MISSING_MONTHS + REVIEWED_MULTI_ENTRY_MONTHS 可讓 raw→selected 檢查跳過、counter-check 只掃 selected span。
驗證：主腳本的 check_calendar_is_complete（六道關卡）、端點期望（由「請求視窗」而非 feed 推導）、check_price_coverage、check_vix_forward_fill_age 是否結構上 fail-closed、擋得住此繞過形狀。README §fail-closed 面明講一個殘留限制（同時從 raw 刪月 + 書面宣告缺失＝有文件的假宣稱，不涵蓋）——判斷此 scope 揭露是否誠實充分。
另確認：主腳本無 lookahead（事件分組/對照組不使用未來資訊）、隨機程序有 seed（若有）。
另確認：tests/test_nfp_official_release_dates.py 的 round-7 TestReleaseMisbindingGateIsStructural 是 nearest-governor 結構檢查（非字面 blocklist）。

## 輸出（務必在預算內完成）
先各類缺陷一句 CLOSED/NOT CLOSED + 證據，最後一行給：**VERDICT: PASS** 或 **VERDICT: FAIL**（FAIL 需逐條列 blocking defect：檔案+行+為何 blocker）。非 blocking 觀察另列，不影響 verdict。現在就開始，優先確保收斂出 VERDICT。

2026-07-27T00:29:25.679434Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
codex
我會把審查範圍鎖死在你列出的檔案：先定位 A/B/C 的實作與測試，再用 results JSON 自行重算 headline、Holm、樣本與六筆日期，最後只依可驗證證據下 PASS/FAIL。不会掃 repo、不会讀 storage/knowledge/error log。
exec
/bin/zsh -lc 'wc -l experiments/k528/k528_nfp_event_study.py experiments/k528/k528_nfp_event_study_results.json experiments/k528/k528_nfp_official_dates_results.json experiments/k528/README.md experiments/k528/build_article_correction.py tests/test_nfp_official_release_dates.py src/volpred/data/event_dates.py
rg -n "check_calendar_is_complete|check_price_coverage|check_vix_forward_fill_age|KNOWN_MISSING_MONTHS|REVIEWED_MULTI_ENTRY_MONTHS|REQUEST|requested|seed|random|shift|lookahead|Holm|confirmatory|claims_flipped|dry.run|feed.json|Good Friday|Friday|週五|243|237|253|nearest|governor|Misbinding" experiments/k528/k528_nfp_event_study.py experiments/k528/k528_nfp_event_study_results.json experiments/k528/k528_nfp_official_dates_results.json experiments/k528/README.md experiments/k528/build_article_correction.py tests/test_nfp_official_release_dates.py src/volpred/data/event_dates.py' in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
    2036 experiments/k528/k528_nfp_event_study.py
    6062 experiments/k528/k528_nfp_event_study_results.json
     372 experiments/k528/k528_nfp_official_dates_results.json
     434 experiments/k528/README.md
     348 experiments/k528/build_article_correction.py
    1292 tests/test_nfp_official_release_dates.py
     164 src/volpred/data/event_dates.py
   10708 total
experiments/k528/build_article_correction.py:4:which dated every NFP to the first Friday of the month. On the official BLS
experiments/k528/build_article_correction.py:17:That mattered far more than six dates out of 253 suggests, because it moved the
experiments/k528/build_article_correction.py:18:NFP-vs-Friday test across the 5% line. The voided list told readers that a
experiments/k528/build_article_correction.py:30:The event group is a weekday mixture while the control group is pure Friday, so
experiments/k528/build_article_correction.py:31:the Friday effect leaks into the estimate. The corrected test restricts the
experiments/k528/build_article_correction.py:32:event group to the 237 releases ABSORBED BY a Friday session.
experiments/k528/build_article_correction.py:35:weekday, and the two do not agree. Of the 253 releases, 243 are DATED a Friday
experiments/k528/build_article_correction.py:36:but only 237 TRADE in one: the six Good Fridays (2007-04-06, 2010-04-02,
experiments/k528/build_article_correction.py:39:Monday returns and cannot enter a comparison whose control group is pure Friday
experiments/k528/build_article_correction.py:41:"237 Friday releases" is therefore the wrong phrase for this number in either
experiments/k528/build_article_correction.py:42:direction -- 237 is a session count, 243 is the release count.
experiments/k528/build_article_correction.py:45:correction. The proxy CALENDAR was all-Friday by construction, but mapping
experiments/k528/build_article_correction.py:46:holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
experiments/k528/build_article_correction.py:47:(239/254 = 94.1% Friday SESSIONS, against 237/253 = 93.7% now). The old spec was
experiments/k528/build_article_correction.py:48:already comparing a mixed group against a pure-Friday control; correcting the
experiments/k528/build_article_correction.py:53:     SESSION. Prose quoting it says 「消息落在週五交易日的 NFP」, not "NFP" and
experiments/k528/build_article_correction.py:54:     not 「在週五公布的 NFP」 -- the latter would be the 243, not the 237.
experiments/k528/build_article_correction.py:61:`storage/reports/feed.json` is shared canonical state. `.claude/rules/worktree.md`
experiments/k528/build_article_correction.py:63:than ceremonial: this worktree carries its own 15MB checkout of feed.json, so a
experiments/k528/build_article_correction.py:100:    # --- sample size: 254 -> 253 ---
experiments/k528/build_article_correction.py:103:        "總共 253 次 NFP 公布日的資料算過一遍",
experiments/k528/build_article_correction.py:114:    # --- Friday baseline: 1.17x -> 1.19x, STILL significant; estimand made explicit ---
experiments/k528/build_article_correction.py:116:        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，"
experiments/k528/build_article_correction.py:119:        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。253 場 NFP 裡，有 243 場的公布日是週五，"
experiments/k528/build_article_correction.py:120:        "但其中 6 場碰上 Good Friday 休市（BLS 照常發布，市場沒開），行情要等下週一才反應；"
experiments/k528/build_article_correction.py:121:        "真正在週五盤被消化掉的是 237 場。這個比較只取那 237 場，讓兩邊的星期別一致："
experiments/k528/build_article_correction.py:122:        "這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準"
experiments/k528/build_article_correction.py:124:        "要注意這個數字講的是「**消息落在週五交易日的** NFP」，既不是「公布日在週五的 NFP」"
experiments/k528/build_article_correction.py:125:        "（那是 243 場），也不是 NFP 一般而言；被排掉的那 16 場本身比較平靜，"
experiments/k528/build_article_correction.py:126:        "所以限定週五會把倍數墊高一些（不限定的話是 1.18 倍）。"
experiments/k528/build_article_correction.py:130:        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；"
experiments/k528/build_article_correction.py:132:        "所以精確的講法是：消息落在週五交易日的 NFP 確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；"
experiments/k528/build_article_correction.py:140:        "那 253 次 NFP 日裡",
experiments/k528/build_article_correction.py:146:        "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
experiments/k528/build_article_correction.py:180:        "對週五基準是 1.17 倍、達到顯著水準。",
experiments/k528/build_article_correction.py:182:        "若只看消息落在週五交易日的那 237 場、拿非 NFP 的週五當基準，是 1.19 倍、達到顯著水準。",
experiments/k528/build_article_correction.py:190:        "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
experiments/k528/build_article_correction.py:194:        "253 場歷史樣本加上 7/2 這場實測",
experiments/k528/build_article_correction.py:200:        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，"
experiments/k528/build_article_correction.py:203:        "**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。"
experiments/k528/build_article_correction.py:204:        "與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，"
experiments/k528/build_article_correction.py:206:        "但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n"
experiments/k528/build_article_correction.py:208:        "（同組對照的無母數檢定則顯著，兩者不一致）、對週五基準達到顯著、"
experiments/k528/build_article_correction.py:213:        "另有一項口徑調整：週五基準的比較，事件組原本是全部樣本（星期別混合）、對照組卻只有週五，"
experiments/k528/build_article_correction.py:214:        "兩邊不對等。現改為只取消息在週五交易日被消化的 237 場，維持兩邊星期別一致，"
experiments/k528/build_article_correction.py:215:        "所以該數字講的是「消息落在週五交易日的 NFP」——"
experiments/k528/build_article_correction.py:216:        "既不是「公布日在週五的 NFP」（公布日在週五的其實有 243 場，其中 6 場遇 Good Friday 休市、"
experiments/k528/build_article_correction.py:218:        "被排掉的 16 場本身比較平靜，因此限定週五會把倍數墊高一些（不限定為 1.18 倍、限定為 1.19 倍），"
experiments/k528/build_article_correction.py:231:    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
experiments/k528/build_article_correction.py:234:        raise KeyError(f"{ARTICLE_ID} not found in {storage_dir}/reports/feed.json")
experiments/k528/build_article_correction.py:281:                "NFP-vs-Friday test across the 5% line. It would have retracted a "
experiments/k528/build_article_correction.py:322:                "K528 event dates corrected from a first-Friday proxy to the official BLS "
experiments/k528/build_article_correction.py:323:                "release calendar. Sample 254 -> 253 events; headline numbers restated "
experiments/k528/build_article_correction.py:324:                "(1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, "
experiments/k528/build_article_correction.py:325:                "r 0.45->0.44). No directional conclusion changes. The Friday comparison "
experiments/k528/build_article_correction.py:326:                "now restricts the event group to the 237 releases absorbed by a Friday "
experiments/k528/build_article_correction.py:327:                "SESSION so weekday is held fixed on both sides -- 243 releases are dated "
experiments/k528/build_article_correction.py:328:                "a Friday, but six of those are Good Fridays traded the following Monday."
experiments/k528/build_article_correction.py:336:    # A dry run that rewrites the audit file is not a dry run (k528 Codex v2
experiments/k528/build_article_correction.py:342:        print("\ndry run -- nothing written. Re-run with --apply from the repo root, "
experiments/k528/k528_nfp_official_dates_results.json:3:  "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
experiments/k528/k528_nfp_official_dates_results.json:11:    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
experiments/k528/k528_nfp_official_dates_results.json:103:    "n_official": 253,
experiments/k528/k528_nfp_official_dates_results.json:104:    "nfp_days_on_friday_official": 237
experiments/k528/k528_nfp_official_dates_results.json:135:        "n": 253,
experiments/k528/k528_nfp_official_dates_results.json:144:      "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
experiments/k528/k528_nfp_official_dates_results.json:163:        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
experiments/k528/k528_nfp_official_dates_results.json:169:          "note": "what the proxy run actually published: all 254 events (239 Friday, 15 Monday) against non-NFP Fridays. This is the number the article quoted, so it is kept, but it is NOT the like-for-like comparison against the corrected column."
experiments/k528/k528_nfp_official_dates_results.json:176:        "n": 237,
experiments/k528/k528_nfp_official_dates_results.json:177:        "nfp_days_on_friday": 237,
experiments/k528/k528_nfp_official_dates_results.json:179:        "win_rate": 0.569620253164557,
experiments/k528/k528_nfp_official_dates_results.json:180:        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
experiments/k528/k528_nfp_official_dates_results.json:185:          "n": 253,
experiments/k528/k528_nfp_official_dates_results.json:189:      "note": "Two things changed here and they are separated rather than conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: the event group is a weekday mixture while the control group is pure Friday, so the test now restricts the event group to the releases that are absorbed by a Friday SESSION (237 of the 243 releases dated a Friday; the other six are Good Fridays traded the following Monday). Defect (2) was NOT created by (1) -- the proxy run was already mixed (239/254 Friday, the other 15 being holiday-shifted Mondays), it was simply never noticed. Both columns above therefore use the SAME restricted estimand so the delta is attributable to the dates alone; `as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` (after) hold the old estimand on each side for reference.",
experiments/k528/k528_nfp_official_dates_results.json:238:        "n": 253,
experiments/k528/k528_nfp_official_dates_results.json:254:        "n": 253,
experiments/k528/k528_nfp_official_dates_results.json:269:        "n": 253,
experiments/k528/k528_nfp_official_dates_results.json:366:  "n_claims_flipped": 0,
experiments/k528/README.md:19:原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 錯得有結構、不是隨機噪音：
experiments/k528/README.md:21:- BLS 在參考週較晚的月份會改到**第二個週五**發布
experiments/k528/README.md:24:- proxy 把每一場都放在**週五**；官方日曆的 253 場有 243 場**發布日**在週五，
experiments/k528/README.md:25:  其中 237 場**在週五的交易 session 被吸收**（差額是六個 Good Friday，見下）
experiments/k528/README.md:49:六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
experiments/k528/README.md:67:- 檢定（**這六個就是 confirmatory family**，見下方「多重比較」）：Welch t（vs 全體非 NFP
experiments/k528/README.md:68:  日 / vs 非 NFP 週五 session）、Mann-Whitney U、VIX 中位數分組 regime 檢定、
experiments/k528/README.md:73:### 週五基準的口徑（estimand）調整
experiments/k528/README.md:75:> **口徑更正（2026-07-20，Codex 五審 B1）**：本節此前寫的是「**在週五公布**的 NFP」。
experiments/k528/README.md:76:> 程式篩的其實是**在週五交易 session 被吸收**的 NFP —— 兩者差六場。
experiments/k528/README.md:77:> 253 場有效發布中，**243 場發布日在週五**，但只有 **237 場在週五開盤**：
experiments/k528/README.md:79:> 全是 **Good Friday**，BLS 照常公布、市場休市，消息由**下週一**吸收。
experiments/k528/README.md:81:> **1.189× / p=0.0209 識別的是「週五 session 是否因吸收 NFP 而波動更大」，
experiments/k528/README.md:82:> 不是「發布日落在週五的 NFP」。** 全文已改用前者措辭。
experiments/k528/README.md:86:> 若改用發布日 weekday 篩 243 場，等於把六筆**週一報酬**放進一個對照組是純週五的比較裡
experiments/k528/README.md:91:事件組是**星期別混合**、對照組是**純週五**，週五本身的波動特性會直接混進 p 值。
experiments/k528/README.md:93:**這個缺陷不是日期修正造成的 —— 修正只是讓它被看見。** proxy 的*日曆*確實每場都是週五，
experiments/k528/README.md:95:94.1% 在週五）；官方日曆是 237/253 = 93.7%。混合程度幾乎沒變，舊版一直都在拿混合事件組
experiments/k528/README.md:96:比純週五對照組，只是從來沒人注意到。
experiments/k528/README.md:98:本輪把事件組**限定為在週五 session 交易的 237 場**，兩邊星期別一致。另一個選項是保留全部
experiments/k528/README.md:99:253 場改用 weekday-matched controls，未採用的理由：被排除的 16 場按 **session** 星期別是
experiments/k528/README.md:103:（那 6 筆週一 session 就是上面的六個 Good Friday；其餘 10 筆是發布日本身就不在週五
experiments/k528/README.md:104:—— 週二 2、週三 1、週四 7。兩種來源合起來 16 筆，與 253 − 237 一致。）
experiments/k528/README.md:106:**限定週五不是中性的樣本刪除，這點必須明講**：被排除的 16 場平均 |ret| 是 0.715%，比週五
experiments/k528/README.md:108:性質，不是效果變強的證據。（六個 Good Friday 子集平均 |ret| = 0.715%，與 16 場整體幾乎
experiments/k528/README.md:111:**因此這個檢定識別的是「在週五 session 被吸收的 NFP」**，既不是「NFP 一般而言」，
experiments/k528/README.md:112:也不是「發布日在週五的 NFP」。引用這個數字的文字必須寫「在週五交易 session 的 NFP」。
experiments/k528/README.md:116:| | 限定週五（主口徑） | 混合星期別（舊口徑） |
experiments/k528/README.md:119:| 修正後（官方） | **1.189× / p=0.0209 / n=237** | 1.177× / p=0.0257 / n=253（DIAGNOSTIC ONLY） |
experiments/k528/README.md:121:（proxy 側的兩格對照組定義不同：限定週五那格用的是**去洩漏**的對照組 832 筆，
experiments/k528/README.md:137:| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
experiments/k528/README.md:140:| 週五 session NFP vs 非 NFP 週五（平均） | 1.167× (p=0.0421, nominal 顯著, n=239) | 1.189× (p=0.0209, **仍 nominal 顯著**；Holm=0.0417, n=237) | 數值微調 |
experiments/k528/README.md:164:- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112（Holm 0.112），**未拒絕**
experiments/k528/README.md:165:- Welch 平均差（**在週五 session 交易的 NFP** 對非 NFP 週五）：1.189×，p=0.0209，
experiments/k528/README.md:166:  **nominal 拒絕**；confirmatory family 內 Holm=0.0417，**仍拒絕**；對全部 22 個
experiments/k528/README.md:167:  inferential outputs 校正則 Holm=0.375，**不拒絕**
experiments/k528/README.md:168:  —— 條件於週五 session，不是關於 NFP 一般而言，也不是關於「發布日在週五」
experiments/k528/README.md:169:- Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019（Holm 0.0058），**拒絕**
experiments/k528/README.md:182:| 檢定 | p (nominal) | Holm（family=6） | 5% 存活 |
experiments/k528/README.md:188:| **B 週五 session Welch** | **0.0209** | **0.0417** | **✓** |
experiments/k528/README.md:191:**週五結果的三種讀法，全部照實報**：
experiments/k528/README.md:196:| Holm，confirmatory family（6） | p=0.0417 | 拒絕 |
experiments/k528/README.md:197:| Holm，全部 inferential outputs（22） | p=0.375 | **不拒絕** |
experiments/k528/README.md:203:- 可以寫的：「nominal 顯著；在六項 confirmatory family 內通過 Holm 校正（**該 family 非預先登記**，
experiments/k528/README.md:207:**為什麼用 Holm 不用 Romano-Wolf**：這個 family 混了 Welch t、Mann-Whitney U 與兩個相關檢定，
experiments/k528/README.md:208:且樣本互相重疊；沒有單一 resampling 方案對四者同時有效。Holm 在**任意相依**下都控制 FWER。
experiments/k528/README.md:223:| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
experiments/k528/README.md:228:| `k528_round5_remediation.json` | 五審四個 blocker 的處置紀錄（before/after、證據、測試、Holm 表） |
experiments/k528/README.md:241:文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、進場 VIX
experiments/k528/README.md:244:（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
experiments/k528/README.md:245:外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。
experiments/k528/README.md:255:**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
experiments/k528/README.md:257:自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
experiments/k528/README.md:268:- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、其中 237 筆在週五
experiments/k528/README.md:269:  session 交易（對照官方 BLS 日曆的 243 筆發布日在週五，兩者差額為六個順延到下週一
experiments/k528/README.md:270:  session 的 Good Friday 發布，見上文 §估計量）、212 個日期共通、結果檔宣告 fail-closed
experiments/k528/README.md:278:- `TestFridayEstimandIsScopedHonestly` — 釘住 conditional estimand 有標示、
experiments/k528/README.md:282:- `test_no_live_artifact_describes_the_237_as_a_release_count` + `TestReleaseMisbindingGateIsStructural`
experiments/k528/README.md:283:  — 釘住「237 不是 Friday-release 數，而是 Friday-session 數」的措辭不變量。
experiments/k528/README.md:285:  但它當時其實只是**5 詞字面 blocklist + 兩個無條件行豁免**（同行出現 `243` 就整行放行、
experiments/k528/README.md:287:  （「237 場 NFP 是週五發布的」「published on a Friday」「publication day was a Friday」
experiments/k528/README.md:288:  「限定週五發布的 237 場」）全部溜過，行內無關 `243`（如「243 trading weeks」）與鄰句的
experiments/k528/README.md:289:  否定詞都能挾持豁免。round-7 把它換成**組合式、就近支配（nearest-governor）**的結構檢查：
experiments/k528/README.md:290:  release-dated 語意 = Friday token 的最近支配動詞是 release/發布 類（而非 session/交易 類），
experiments/k528/README.md:292:  legitimate 反例（正確對照 / 正確 errata）全部進 `TestReleaseMisbindingGateIsStructural`，
experiments/k528/README.md:307:價格序列覆蓋不足、VIX 陳舊。它們**不**涵蓋「有人寫下一則假的 `KNOWN_MISSING_MONTHS`
experiments/k528/README.md:311:**日曆完整性**（`check_calendar_is_complete`）**同時驗證 raw feed 與 accessor 的選擇**。
experiments/k528/README.md:319:2. 任何同月多筆的月份**必須列在 `REVIEWED_MULTI_ENTRY_MONTHS`**，且選到的日期要與人工
experiments/k528/README.md:325:5. `KNOWN_MISSING_MONTHS` 宣稱的缺口，會回頭去 raw feed **驗證它真的是缺口** → 有資料就
experiments/k528/README.md:338:| 刪 `2005-01` | 259 / 253 | 34d | 21d | **通過** |
experiments/k528/README.md:339:| 刪 `2026-03` | 259 / 253 | 6d | 44d | **通過** |
experiments/k528/README.md:363:  delete head month 2005-01: ACCEPTED  (259 raw / 253 selected, head_short=34d tail_short=21d)
experiments/k528/README.md:364:  delete tail month 2026-03: ACCEPTED  (259 raw / 253 selected, head_short=6d  tail_short=44d)
experiments/k528/README.md:366:  delete head month 2005-01: RAISED    the requested window ... fully contains the publication window of 1 month(s)...
experiments/k528/README.md:367:  delete tail month 2026-03: RAISED    the requested window ... fully contains the publication window of 1 month(s)...
experiments/k528/README.md:370:**殘留限制（明講）**：端點期望仍可被「把該月加進 `KNOWN_MISSING_MONTHS`」壓掉。
experiments/k528/README.md:382:本輪新增（`check_price_coverage` / `check_vix_forward_fill_age`，都寫成**函式**以便被測試
experiments/k528/README.md:414:`REVIEWED_MULTI_ENTRY_MONTHS`（六個月份逐一對照 BLS news-release archive 驗證過）。
experiments/k528/README.md:423:事件窗篩選的 253 個。因窗口不足被排除的 `2005-01-07` 仍然是真實的 NFP 日，把它留在對照組
experiments/k528/README.md:424:就是本實驗存在的理由（「把真的事件日丟進對照組」）的 1/253 版本。三審 Codex 與本輪自查
tests/test_nfp_official_release_dates.py:1:"""Pin the NFP event dates that a first-Friday proxy gets wrong.
tests/test_nfp_official_release_dates.py:4:dates from a "first Friday of the month" rule. Against the official BLS
tests/test_nfp_official_release_dates.py:48:# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
tests/test_nfp_official_release_dates.py:60:# The 6 the proxy happened to get right. Pinned so a "fix" that shifts every
tests/test_nfp_official_release_dates.py:111:            f"{proxy_date} came from the first-Friday proxy and is not an "
tests/test_nfp_official_release_dates.py:121:        """Guard the fixture itself: each 'proxy' date must be a first Friday.
tests/test_nfp_official_release_dates.py:163:        """July 4 fell on a Saturday, observed Friday July 3, so BLS moved up."""
tests/test_nfp_official_release_dates.py:341:# An intermediate 2026-07-19 rerun did report the NFP-vs-Friday result flipping
tests/test_nfp_official_release_dates.py:369:    """Reject a calendar carrying the first-Friday proxy's fingerprints.
tests/test_nfp_official_release_dates.py:381:            f"all {len(dates)} releases fall on a Friday. The official calendar "
tests/test_nfp_official_release_dates.py:382:            "does not: BLS moves the release off Friday at holiday and shutdown "
tests/test_nfp_official_release_dates.py:391:            "every release sits on the first Friday of its month -- proxy calendar"
tests/test_nfp_official_release_dates.py:426:        """237 of 253, not 253 of 253. The gap is the corrected dates."""
tests/test_nfp_official_release_dates.py:429:        assert n == 253
tests/test_nfp_official_release_dates.py:430:        assert on_friday == 237
tests/test_nfp_official_release_dates.py:448:        An earlier rerun selected those six and moved the NFP-vs-Friday test
tests/test_nfp_official_release_dates.py:485:        with pytest.raises(AssertionError, match="Friday"):
tests/test_nfp_official_release_dates.py:541:    for required in ("check_calendar_is_complete", "KNOWN_MISSING_MONTHS",
tests/test_nfp_official_release_dates.py:542:                     "REVIEWED_MULTI_ENTRY_MONTHS", "MAX_WINDOW_SHORTFALL_DAYS"):
tests/test_nfp_official_release_dates.py:549:    experiment exists to document -- it just happened at 1/253 scale instead of
tests/test_nfp_official_release_dates.py:577:        that re-leaks 2005-01-07 while dropping some other Friday -- the count
tests/test_nfp_official_release_dates.py:584:        # 2005-01-07 is the proxy's January-2005 event: it is the first Friday of
tests/test_nfp_official_release_dates.py:598:        # wrongly excluding some other Friday.
tests/test_nfp_official_release_dates.py:600:        assert der["n_fridays_in_sample"] == 1072, "pinned Friday count for this sample"
tests/test_nfp_official_release_dates.py:635:        return _k528_module().check_calendar_is_complete
tests/test_nfp_official_release_dates.py:685:        requested window, so it is REQUIRED). Match either layer -- same reasoning
tests/test_nfp_official_release_dates.py:700:        The requested window here stops on 2024-03-10, so 2024-03's publication
tests/test_nfp_official_release_dates.py:714:        """KNOWN_MISSING_MONTHS is for real cancellations. If it is taken on
tests/test_nfp_official_release_dates.py:717:        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
tests/test_nfp_official_release_dates.py:723:            mod.check_calendar_is_complete(
tests/test_nfp_official_release_dates.py:734:        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
tests/test_nfp_official_release_dates.py:738:            mod.check_calendar_is_complete(
tests/test_nfp_official_release_dates.py:761:        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
tests/test_nfp_official_release_dates.py:763:            mod.check_calendar_is_complete(
tests/test_nfp_official_release_dates.py:771:        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
tests/test_nfp_official_release_dates.py:772:        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-03"] = {
tests/test_nfp_official_release_dates.py:776:            mod.check_calendar_is_complete(
tests/test_nfp_official_release_dates.py:784:        mod.KNOWN_MISSING_MONTHS["2024-02"] = "fabricated"
tests/test_nfp_official_release_dates.py:785:        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
tests/test_nfp_official_release_dates.py:788:        with pytest.raises(RuntimeError, match="both KNOWN_MISSING_MONTHS"):
tests/test_nfp_official_release_dates.py:789:            mod.check_calendar_is_complete(
tests/test_nfp_official_release_dates.py:799:        mod.KNOWN_MISSING_MONTHS["2024-04"] = "fabricated"
tests/test_nfp_official_release_dates.py:801:            mod.check_calendar_is_complete(
tests/test_nfp_official_release_dates.py:827:        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
tests/test_nfp_official_release_dates.py:831:            mod.check_calendar_is_complete(
tests/test_nfp_official_release_dates.py:842:        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
tests/test_nfp_official_release_dates.py:845:        out = mod.check_calendar_is_complete(
tests/test_nfp_official_release_dates.py:866:        out = mod.check_calendar_is_complete(
tests/test_nfp_official_release_dates.py:870:            mod.REVIEWED_MULTI_ENTRY_MONTHS
tests/test_nfp_official_release_dates.py:875:# Round-7 N1: a STRUCTURAL detector for the 237-as-a-release-count misbinding.
tests/test_nfp_official_release_dates.py:877:# 237 is the count of official NFP releases that TRADED in a Friday session; 243
tests/test_nfp_official_release_dates.py:878:# is the count DATED a Friday. Round 6 shipped a guard advertised as a
tests/test_nfp_official_release_dates.py:880:# unconditional line-level exemptions (any 243 on the line, or any denial token
tests/test_nfp_official_release_dates.py:885:#   * "release-dated language" is NOT a fixed phrase. It is a Friday token whose
tests/test_nfp_official_release_dates.py:886:#     nearest governing verb (within a small window) is a release/publication
tests/test_nfp_official_release_dates.py:887:#     verb -- so 'released on a Friday', 'published on a Friday', '週五發布',
tests/test_nfp_official_release_dates.py:888:#     '發布日在週五' all trip it, but '237 releases traded in a Friday session'
tests/test_nfp_official_release_dates.py:889:#     (where 'releases' is the subject noun and Friday governs 'session') does
tests/test_nfp_official_release_dates.py:892:#   * a Friday token bound to a SESSION verb marks the correct estimand, so a
tests/test_nfp_official_release_dates.py:893:#     clause that binds Friday to a session (or draws the 243/237 distinction)
tests/test_nfp_official_release_dates.py:894:#     is exempt -- but an unrelated '243 trading weeks' no longer buys a pass,
tests/test_nfp_official_release_dates.py:895:#     because the session word has to sit NEXT TO the Friday, not merely on the
tests/test_nfp_official_release_dates.py:902:_FRIDAY_TOKENS = ("friday", "週五", "周五", "星期五", "禮拜五")
tests/test_nfp_official_release_dates.py:915:_RE_237 = re.compile(r"(?<!\d)237(?!\d)")
tests/test_nfp_official_release_dates.py:918:# the wrong wording ('Friday releases', 「Friday releases」) in order to retire
tests/test_nfp_official_release_dates.py:919:# it. Verbs inside such spans do not bind their Friday.
tests/test_nfp_official_release_dates.py:923:# The farthest a verb may sit from a Friday token and still be taken to govern
tests/test_nfp_official_release_dates.py:924:# it. Beyond this the Friday is treated as governed by neither.
tests/test_nfp_official_release_dates.py:949:def _nearest_gap(friday_span, verb_spans):
tests/test_nfp_official_release_dates.py:950:    """Smallest character gap between a Friday token and any of ``verb_spans``
tests/test_nfp_official_release_dates.py:951:    (0 if they overlap), or None if the nearest is beyond ``_MAX_BIND_GAP``."""
tests/test_nfp_official_release_dates.py:967:    """For every Friday token, decide by NEAREST GOVERNOR whether it is bound to
tests/test_nfp_official_release_dates.py:971:    Nearest-governor rather than a fixed window because the two readings sit at
tests/test_nfp_official_release_dates.py:972:    different distances: 'publication day was a Friday' puts the release verb 11
tests/test_nfp_official_release_dates.py:973:    characters out, while 'a Friday session' puts the session word right against
tests/test_nfp_official_release_dates.py:975:    unrelated '243 trading weeks'; comparing which governor is CLOSER does not.
tests/test_nfp_official_release_dates.py:977:    cannot launder a tight 'Friday releases'."""
tests/test_nfp_official_release_dates.py:987:        rd = _nearest_gap(span, release_spans)
tests/test_nfp_official_release_dates.py:988:        sd = _nearest_gap(span, session_spans)
tests/test_nfp_official_release_dates.py:996:def _clause_misbinds_237(clause):
tests/test_nfp_official_release_dates.py:997:    """Does this clause present 237 (a SESSION count) as a Friday-RELEASE count
tests/test_nfp_official_release_dates.py:999:    if not _RE_237.search(clause):
tests/test_nfp_official_release_dates.py:1003:        # 237 is here, but no Friday token governs a release act, e.g.
tests/test_nfp_official_release_dates.py:1004:        # '237 traded in a Friday session' -- the correct estimand.
tests/test_nfp_official_release_dates.py:1007:        # A Friday also governs a session in this clause: either the session
tests/test_nfp_official_release_dates.py:1008:        # estimand itself or the 243/237 distinction being drawn. Both honest.
tests/test_nfp_official_release_dates.py:1009:        return False, "Friday bound to a session (correct estimand / distinction drawn)"
tests/test_nfp_official_release_dates.py:1012:    return True, "237 sits in Friday-release language with no Friday-session reading"
tests/test_nfp_official_release_dates.py:1017:    misbind 237. `text` is normally one logical unit (a Markdown/JSON physical
tests/test_nfp_official_release_dates.py:1022:        bad, reason = _clause_misbinds_237(clause)
tests/test_nfp_official_release_dates.py:1033:    would otherwise wrap a 'Friday' away from its 'session' onto the next
tests/test_nfp_official_release_dates.py:1058:class TestFridayEstimandIsScopedHonestly:
tests/test_nfp_official_release_dates.py:1059:    """Codex v3 finding 4: restricting to Friday is a legitimate conditional
tests/test_nfp_official_release_dates.py:1066:        # Round-5 B1 tightened this. The old assertion pinned "Friday NFP", which
tests/test_nfp_official_release_dates.py:1068:        # Friday" (243) and "traded in a Friday session" (237). Pinning the
tests/test_nfp_official_release_dates.py:1070:        # Friday" elsewhere, so the scope must ALSO rule that reading out.
tests/test_nfp_official_release_dates.py:1072:        assert "NFP traded in a Friday session" in b["claim_scope"]
tests/test_nfp_official_release_dates.py:1073:        assert "not 'NFP released on a Friday'" in b["claim_scope"], (
tests/test_nfp_official_release_dates.py:1085:        one word: 243 releases are DATED a Friday, 237 TRADE in a Friday session.
tests/test_nfp_official_release_dates.py:1091:        assert est["n_release_date_on_friday"] == 243
tests/test_nfp_official_release_dates.py:1092:        assert est["n_traded_in_friday_session"] == 237
tests/test_nfp_official_release_dates.py:1099:        ), "the 243/237 gap must be fully accounted for by the named releases"
tests/test_nfp_official_release_dates.py:1104:            assert release.weekday() == 4, f"{release} is not a Friday release"
tests/test_nfp_official_release_dates.py:1109:    def test_no_live_artifact_describes_the_237_as_a_release_count(self):
tests/test_nfp_official_release_dates.py:1113:        The defect is not a phrase, it is a MISBINDING: 237 is the count of
tests/test_nfp_official_release_dates.py:1114:        releases ABSORBED BY a Friday session; 243 is the count of releases
tests/test_nfp_official_release_dates.py:1115:        DATED a Friday. Saying '237 Friday releases' fuses them, and that is the
tests/test_nfp_official_release_dates.py:1122:        language as a Friday token GOVERNING a release verb, exempts a Friday
tests/test_nfp_official_release_dates.py:1126:        ``TestReleaseMisbindingGateIsStructural`` so the guard itself has a
tests/test_nfp_official_release_dates.py:1149:                if "237" not in unit:
tests/test_nfp_official_release_dates.py:1157:            "237 is a SESSION count, not a release count. These clauses bind it "
tests/test_nfp_official_release_dates.py:1158:            "to Friday-release language with no Friday-session reading and no "
tests/test_nfp_official_release_dates.py:1189:class TestReleaseMisbindingGateIsStructural:
tests/test_nfp_official_release_dates.py:1199:    ``_clause_misbinds_237`` back into a wordlist, the synonym cases go red.
tests/test_nfp_official_release_dates.py:1205:            "restricting the event group to Friday releases (237)",
tests/test_nfp_official_release_dates.py:1209:        pytest.param("237 場 NFP 是週五發布的", id="synonym_zh_published"),
tests/test_nfp_official_release_dates.py:1211:            "the 237 NFP announcements published on a Friday",
tests/test_nfp_official_release_dates.py:1215:            "237 releases whose publication day was a Friday",
tests/test_nfp_official_release_dates.py:1218:        pytest.param("限定週五發布的 237 場 NFP 事件", id="synonym_zh_restricted"),
tests/test_nfp_official_release_dates.py:1221:            "restricting the event group to Friday releases (237); "
tests/test_nfp_official_release_dates.py:1222:            "sample spans 243 trading weeks",
tests/test_nfp_official_release_dates.py:1223:            id="hijack_unrelated_243_on_line",
tests/test_nfp_official_release_dates.py:1226:            "既不是 proxy 的問題 -- 237 Friday releases were used",
tests/test_nfp_official_release_dates.py:1235:            "243 releases were dated a Friday; "
tests/test_nfp_official_release_dates.py:1236:            "237 of them traded in a Friday session",
tests/test_nfp_official_release_dates.py:1240:            "更正：此前寫的是「237 Friday releases」是錯的 — "
tests/test_nfp_official_release_dates.py:1241:            "237 是週五 session 交易數，243 才是週五發布的 release 數",
tests/test_nfp_official_release_dates.py:1245:            "253 場有效發布中，243 場發布日在週五，但只有 237 場在週五開盤",
tests/test_nfp_official_release_dates.py:1249:            "event group to the 237 releases ABSORBED BY a Friday session.",
tests/test_nfp_official_release_dates.py:1257:            "the hardened gate let a 237-as-a-release-count misbinding through: "
tests/test_nfp_official_release_dates.py:1269:    def test_the_243_exemption_is_conditional_not_blanket(self):
tests/test_nfp_official_release_dates.py:1270:        """Round-6 weakness: any 243 on the line bought a free pass. A 243 that
tests/test_nfp_official_release_dates.py:1271:        is not itself bound to Friday-release language must NOT launder 237."""
tests/test_nfp_official_release_dates.py:1272:        # 243 present, and a session word ('sessions') present, so the old
tests/test_nfp_official_release_dates.py:1273:        # blanket rule would have exempted -- but Friday governs 'released'.
tests/test_nfp_official_release_dates.py:1275:            "237 released on a Friday across 243 sessions"
tests/test_nfp_official_release_dates.py:1282:            "更正了其他行；237 released on a Friday"
tests/test_nfp_official_release_dates.py:1289:        assert _release_misbinding_offenders("event group of 237 Friday releases")
tests/test_nfp_official_release_dates.py:1291:            "237 releases traded in a Friday session; 243 were dated a Friday"
experiments/k528/k528_nfp_event_study.py:21:The original run dated every NFP to the first Friday of the month. That proxy is
experiments/k528/k528_nfp_event_study.py:22:wrong for ~20% of the sample and it is wrong SYSTEMATICALLY, not randomly: BLS
experiments/k528/k528_nfp_event_study.py:23:moves the release to the second Friday whenever the reference week falls late
experiments/k528/k528_nfp_event_study.py:26:happened, and it forces every event onto a Friday when 16 of the 254 official
experiments/k528/k528_nfp_event_study.py:27:releases are not on a Friday at all.
experiments/k528/k528_nfp_event_study.py:69:# entry needs a documented reason, and check_calendar_is_complete VERIFIES the
experiments/k528/k528_nfp_event_study.py:73:KNOWN_MISSING_MONTHS: dict[str, str] = {
experiments/k528/k528_nfp_event_study.py:78:        "CPI release described in volpred/data/event_dates.py. The first-Friday proxy "
experiments/k528/k528_nfp_event_study.py:109:REVIEWED_MULTI_ENTRY_MONTHS: dict[str, dict] = {
experiments/k528/k528_nfp_event_study.py:118:# How far the observed calendar may fall short of the requested window before the
experiments/k528/k528_nfp_event_study.py:132:# the month). Regular releases land on the first or second Friday, i.e. day 1-14;
experiments/k528/k528_nfp_event_study.py:136:# REQUESTED WINDOW ALONE. That independence is the whole point: every other check
experiments/k528/k528_nfp_event_study.py:140:#     deleting 2005-01 from raw AND selected together -> 259/253, head shortfall
experiments/k528/k528_nfp_event_study.py:141:#     34d, passes; deleting 2026-03 the same way -> 259/253, tail shortfall 44d,
experiments/k528/k528_nfp_event_study.py:146:# The requested window is the one fact the feed cannot edit.
experiments/k528/k528_nfp_event_study.py:149:# How far SPY / ^VIX may fall short of the requested window at either end. The
experiments/k528/k528_nfp_event_study.py:189:def check_calendar_is_complete(selected, raw, start, end):
experiments/k528/k528_nfp_event_study.py:275:    unreviewed = sorted(set(multi) - set(REVIEWED_MULTI_ENTRY_MONTHS))
experiments/k528/k528_nfp_event_study.py:283:            "REVIEWED_MULTI_ENTRY_MONTHS."
experiments/k528/k528_nfp_event_study.py:288:        m: {"now": [str(d.date()) for d in multi[m]], "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]}
experiments/k528/k528_nfp_event_study.py:290:        if [str(d.date()) for d in multi[m]] != REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]
experiments/k528/k528_nfp_event_study.py:300:            "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]}
experiments/k528/k528_nfp_event_study.py:302:        if m in sel_by_month and str(sel_by_month[m].date()) != REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]
experiments/k528/k528_nfp_event_study.py:315:    # UNCONDITIONAL: no KNOWN_MISSING_MONTHS subtraction here. If the raw feed has
experiments/k528/k528_nfp_event_study.py:326:            "silently shortened sample. This is not excusable via KNOWN_MISSING_MONTHS: "
experiments/k528/k528_nfp_event_study.py:334:    both = sorted(set(KNOWN_MISSING_MONTHS) & set(REVIEWED_MULTI_ENTRY_MONTHS))
experiments/k528/k528_nfp_event_study.py:337:            f"month(s) {both} appear in both KNOWN_MISSING_MONTHS and "
experiments/k528/k528_nfp_event_study.py:338:            "REVIEWED_MULTI_ENTRY_MONTHS. A month cannot both have published nothing and "
experiments/k528/k528_nfp_event_study.py:351:            f"official NFP calendar does not cover the requested window "
experiments/k528/k528_nfp_event_study.py:361:    # check derives what MUST be there from the requested window alone.
experiments/k528/k528_nfp_event_study.py:388:    absent_required = sorted(set(required_months) - set(sel_months) - set(KNOWN_MISSING_MONTHS))
experiments/k528/k528_nfp_event_study.py:391:            f"the requested window {start}..{end} fully contains the publication window of "
experiments/k528/k528_nfp_event_study.py:393:            f"{absent_required}. This is derived from the REQUESTED WINDOW, not from the feed, "
experiments/k528/k528_nfp_event_study.py:403:    missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
experiments/k528/k528_nfp_event_study.py:408:            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
experiments/k528/k528_nfp_event_study.py:417:    bogus = sorted(m for m in KNOWN_MISSING_MONTHS if raw_by_month.get(m))
experiments/k528/k528_nfp_event_study.py:420:            f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
experiments/k528/k528_nfp_event_study.py:429:        "reviewed_multi_entry_months": dict(sorted(REVIEWED_MULTI_ENTRY_MONTHS.items())),
experiments/k528/k528_nfp_event_study.py:431:        "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
experiments/k528/k528_nfp_event_study.py:433:            "requested": f"{start}..{end}",
experiments/k528/k528_nfp_event_study.py:440:            "derived_from": "requested window only -- never from the feed",
experiments/k528/k528_nfp_event_study.py:445:            "excused_by_known_missing": sorted(set(required_months) & set(KNOWN_MISSING_MONTHS)),
experiments/k528/k528_nfp_event_study.py:449:                "253 selected, shortfall inside the 70d tolerance) and the sample silently "
experiments/k528/k528_nfp_event_study.py:450:                "shortened. The requested window is the one fact a truncated feed cannot edit."
experiments/k528/k528_nfp_event_study.py:457:            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A new "
experiments/k528/k528_nfp_event_study.py:460:            "KNOWN_MISSING_MONTHS. That is deliberate -- 2025-10 really was cancelled -- and "
experiments/k528/k528_nfp_event_study.py:483:    completeness = check_calendar_is_complete(dates, raw, start, end)
experiments/k528/k528_nfp_event_study.py:505:def check_price_coverage(frame, ticker, start, end):
experiments/k528/k528_nfp_event_study.py:514:    Same principle as the calendar gate: the requested window is the yardstick,
experiments/k528/k528_nfp_event_study.py:523:            f"{ticker} does not cover the requested window {start}..{end}: first bar "
experiments/k528/k528_nfp_event_study.py:541:    "SPY": check_price_coverage(spy, "SPY", SAMPLE_START, SAMPLE_END),
experiments/k528/k528_nfp_event_study.py:542:    "^VIX": check_price_coverage(vix, "^VIX", SAMPLE_START, SAMPLE_END),
experiments/k528/k528_nfp_event_study.py:548:spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
experiments/k528/k528_nfp_event_study.py:555:def check_vix_forward_fill_age(vix_series):
experiments/k528/k528_nfp_event_study.py:592:spy["VIX"], vix_ffill_audit = check_vix_forward_fill_age(spy["VIX"])
experiments/k528/k528_nfp_event_study.py:608:# The proxy forced every event onto a Friday. The official calendar does not,
experiments/k528/k528_nfp_event_study.py:609:# and that is load-bearing for the Friday-baseline test below.
experiments/k528/k528_nfp_event_study.py:612:      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
experiments/k528/k528_nfp_event_study.py:616:# open -- hence "next trading day", not "nearest". Every release must land on
experiments/k528/k528_nfp_event_study.py:651:# check_price_coverage has already confirmed both series reach both ends of it. So
experiments/k528/k528_nfp_event_study.py:659:        f"was requested for {SAMPLE_START}..{SAMPLE_END}; with both endpoints verified, every "
experiments/k528/k528_nfp_event_study.py:675:n_shifted = sum(1 for r, s in release_to_session.items() if r != s)
experiments/k528/k528_nfp_event_study.py:680:# holiday, and every one of those in this sample is a Good Friday -- so the
experiments/k528/k528_nfp_event_study.py:681:# "Friday" event group was 237 sessions, not the 243 Friday releases the prose
experiments/k528/k528_nfp_event_study.py:687:# non-trading day -- that is the only mechanism that can shift one. Stating it as
experiments/k528/k528_nfp_event_study.py:689:# (say, "nearest session" instead of "next session") cannot quietly redefine the
experiments/k528/k528_nfp_event_study.py:691:weekday_shifted = sorted(
experiments/k528/k528_nfp_event_study.py:694:misattributed = [r for r in weekday_shifted if r in set(trading_dates)]
experiments/k528/k528_nfp_event_study.py:702:# The Friday releases that are absorbed by a non-Friday session, named rather than
experiments/k528/k528_nfp_event_study.py:704:# on a Friday".
experiments/k528/k528_nfp_event_study.py:722:    "n_shifted_to_next_session": n_shifted,
experiments/k528/k528_nfp_event_study.py:731:print(f"  Mapped to trading sessions: {len(nfp_trading_dates)} ({n_shifted} shifted to next open)")
experiments/k528/k528_nfp_event_study.py:770:        # six Good Friday releases; see friday_estimand in the results JSON.
experiments/k528/k528_nfp_event_study.py:776:        # SESSION weekday. This is the one the Friday test filters on, and it is
experiments/k528/k528_nfp_event_study.py:782:        "session_shifted_from_release": bool(release_ts != nfp_date),
experiments/k528/k528_nfp_event_study.py:813:# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
experiments/k528/k528_nfp_event_study.py:825:# Friday-only baseline. The event group is a weekday MIXTURE while the control
experiments/k528/k528_nfp_event_study.py:826:# group is pure Friday, so any Friday-vs-other-weekday volatility difference
experiments/k528/k528_nfp_event_study.py:831:# correction. The proxy calendar was all-Friday by construction, but mapping
experiments/k528/k528_nfp_event_study.py:832:# holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
experiments/k528/k528_nfp_event_study.py:833:# -- 239/254 = 94.1% Friday, against 237/253 = 93.7% here. The mixture was
experiments/k528/k528_nfp_event_study.py:835:# a mixed group against a pure-Friday control. Correcting the dates is what made
experiments/k528/k528_nfp_event_study.py:843:print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
experiments/k528/k528_nfp_event_study.py:858:# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
experiments/k528/k528_nfp_event_study.py:861:#   (i)  restrict the event group to the releases traded in a Friday session, or
experiments/k528/k528_nfp_event_study.py:863:# This run takes (i). The non-Friday events are a handful of thin weekday cells
experiments/k528/k528_nfp_event_study.py:864:# out of 253 -- cells that thin make (ii) a weighted average dominated by a few
experiments/k528/k528_nfp_event_study.py:871:#     among trading sessions that fall on a Friday, do those that absorb an NFP
experiments/k528/k528_nfp_event_study.py:874:# NOT "among NFP releases dated a Friday". The two differ by six Good Fridays
experiments/k528/k528_nfp_event_study.py:876:# published on a Friday, but the market was shut, so the news is absorbed by the
experiments/k528/k528_nfp_event_study.py:877:# following Monday. 243 of the 253 releases are dated a Friday; 237 are traded on
experiments/k528/k528_nfp_event_study.py:884:# Monday returns into a comparison against a pure-Friday control group, which
experiments/k528/k528_nfp_event_study.py:890:# events are quieter than the Friday ones, so restricting RAISES the ratio
experiments/k528/k528_nfp_event_study.py:892:# of a stronger effect. Both numbers are reported, and the six Good Friday events
experiments/k528/k528_nfp_event_study.py:915:    "filter": "session weekday == Friday",
experiments/k528/k528_nfp_event_study.py:917:        "Among trading sessions falling on a Friday, do the sessions that absorb an NFP "
experiments/k528/k528_nfp_event_study.py:919:        "session that trades the news, NOT about releases dated a Friday."
experiments/k528/k528_nfp_event_study.py:937:            "Every one is a Good Friday: BLS published, the market was shut, the news is "
experiments/k528/k528_nfp_event_study.py:939:            "enter a comparison whose control group is pure Friday without reintroducing the "
experiments/k528/k528_nfp_event_study.py:946:        "Monday returns against a Friday-only control group."
experiments/k528/k528_nfp_event_study.py:949:        "Not 'NFP in general' (the sample is conditioned on Friday sessions) and not "
experiments/k528/k528_nfp_event_study.py:950:        "'releases dated a Friday' (six such releases are traded on a Monday and excluded)."
experiments/k528/k528_nfp_event_study.py:955:        "release-Friday / session-Friday counts do not reconcile with the shifted set; the "
experiments/k528/k528_nfp_event_study.py:1031:# Holm rather than Romano-Wolf: Holm controls FWER under ARBITRARY dependence,
experiments/k528/k528_nfp_event_study.py:1038:    """Holm step-down adjusted p-values, monotone and capped at 1."""
experiments/k528/k528_nfp_event_study.py:1048:# The confirmatory family: the six tests README's "方法 / 檢定" line has named as
experiments/k528/k528_nfp_event_study.py:1058:confirmatory = [
experiments/k528/k528_nfp_event_study.py:1066:confirmatory_adj = holm_adjust([p for _, p in confirmatory])
experiments/k528/k528_nfp_event_study.py:1082:all_outputs = confirmatory + exploratory
experiments/k528/k528_nfp_event_study.py:1085:_b_idx = [n for n, _ in confirmatory].index("B_nfp_vs_friday_welch")
experiments/k528/k528_nfp_event_study.py:1089:    "method": "Holm step-down (FWER, valid under arbitrary dependence)",
experiments/k528/k528_nfp_event_study.py:1097:        "Not pre-registered. The confirmatory endpoints predate the date correction and this "
experiments/k528/k528_nfp_event_study.py:1101:    "confirmatory_family": {
experiments/k528/k528_nfp_event_study.py:1102:        "n": len(confirmatory),
experiments/k528/k528_nfp_event_study.py:1105:            for (n, p), a in zip(confirmatory, confirmatory_adj)
experiments/k528/k528_nfp_event_study.py:1117:        "p_holm_confirmatory_family": float(confirmatory_adj[_b_idx]),
experiments/k528/k528_nfp_event_study.py:1120:            "Survives Holm within the six-test confirmatory family; does NOT survive Holm "
experiments/k528/k528_nfp_event_study.py:1122:            "Holm-robust only within the declared confirmatory family."
experiments/k528/k528_nfp_event_study.py:1126:        "Everything outside the confirmatory family -- the 12 monthly cells, vol crush, VIX "
experiments/k528/k528_nfp_event_study.py:1132:print("\n--- Multiplicity (Holm) ---")
experiments/k528/k528_nfp_event_study.py:1133:print(f"  Confirmatory family: {len(confirmatory)} tests")
experiments/k528/k528_nfp_event_study.py:1134:for (n, p), a in zip(confirmatory, confirmatory_adj):
experiments/k528/k528_nfp_event_study.py:1135:    print(f"    {n:28s} p={p:.4g}  Holm={a:.4g}  {'PASS' if a < 0.05 else 'fail'}")
experiments/k528/k528_nfp_event_study.py:1136:print(f"  Friday test vs all {len(all_outputs)} outputs: Holm={all_adj[_b_all_idx]:.4g}")
experiments/k528/k528_nfp_event_study.py:1150:print(f"\n--- B. Friday NFP vs Friday Non-NFP (weekday held fixed) ---")
experiments/k528/k528_nfp_event_study.py:1151:print(f"  Friday NFP |return|:  {nfp_friday_abs.mean():.6f} (n={len(nfp_friday_abs)})")
experiments/k528/k528_nfp_event_study.py:1152:print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
experiments/k528/k528_nfp_event_study.py:1157:print(f"  [excluded] non-Friday NFP events: n={len(nfp_nonfriday_abs)}, "
experiments/k528/k528_nfp_event_study.py:1159:print(f"  [diagnostic, NOT a headline] all-events vs Friday baseline: "
experiments/k528/k528_nfp_event_study.py:1268:    f"Welch mean-difference, NFP traded in a Friday session vs Friday non-NFP "
experiments/k528/k528_nfp_event_study.py:1275:    f"ABSORBED BY a Friday session, not to releases DATED a Friday: "
experiments/k528/k528_nfp_event_study.py:1276:    f"{_n_release_friday} are dated a Friday but only {_n_session_friday} trade in one, "
experiments/k528/k528_nfp_event_study.py:1277:    f"the {len(_gf)} Good Friday releases in between being absorbed by the following "
experiments/k528/k528_nfp_event_study.py:1288:        "so a rank test can detect a location shift the Welch mean test cannot. "
experiments/k528/k528_nfp_event_study.py:1327:print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
experiments/k528/k528_nfp_event_study.py:1359:# Reconstructing it needs the first-Friday rule for exactly the months the
experiments/k528/k528_nfp_event_study.py:1374:    _ff = _first + pd.Timedelta(days=(4 - _first.weekday()) % 7)   # first Friday
experiments/k528/k528_nfp_event_study.py:1404:# The proxy calendar was all-Friday by construction, but 15 of its 254 events
experiments/k528/k528_nfp_event_study.py:1405:# mapped to a Monday because the first Friday was a market holiday. So the
experiments/k528/k528_nfp_event_study.py:1406:# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
experiments/k528/k528_nfp_event_study.py:1408:# (Friday events only) rather than comparing a mixed `before` against a
experiments/k528/k528_nfp_event_study.py:1498:# --- 1.17x : NFP vs Friday-only baseline ---
experiments/k528/k528_nfp_event_study.py:1500:    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
experiments/k528/k528_nfp_event_study.py:1502:        # Same estimand as the `after` column: Friday events only.
experiments/k528/k528_nfp_event_study.py:1512:        # restated: a regression that re-leaks one Friday while wrongly dropping
experiments/k528/k528_nfp_event_study.py:1525:        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
experiments/k528/k528_nfp_event_study.py:1532:                "what the proxy run actually published: all 254 events (239 Friday, "
experiments/k528/k528_nfp_event_study.py:1533:                "15 Monday) against non-NFP Fridays. This is the number the article "
experiments/k528/k528_nfp_event_study.py:1547:        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
experiments/k528/k528_nfp_event_study.py:1559:         "Friday, so the test now restricts the event group to the releases that "
experiments/k528/k528_nfp_event_study.py:1560:         "are absorbed by a Friday SESSION (237 of the 243 releases dated a Friday; "
experiments/k528/k528_nfp_event_study.py:1561:         "the other six are Good Fridays traded the following Monday). "
experiments/k528/k528_nfp_event_study.py:1563:         "(239/254 Friday, the other 15 being holiday-shifted Mondays), it was "
experiments/k528/k528_nfp_event_study.py:1722:        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
experiments/k528/k528_nfp_event_study.py:1760:            "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
experiments/k528/k528_nfp_event_study.py:1763:                "group is restricted to NFP releases that trade on a Friday, and the "
experiments/k528/k528_nfp_event_study.py:1764:                f"{int(len(nfp_nonfriday_abs))} non-Friday events are excluded rather "
experiments/k528/k528_nfp_event_study.py:1765:                "than compared against a pure-Friday control group."
experiments/k528/k528_nfp_event_study.py:1772:                "releases DATED a Friday, six of which are Good Fridays traded the "
experiments/k528/k528_nfp_event_study.py:1774:                "must say 'NFP traded in a Friday session', not 'NFP' and not "
experiments/k528/k528_nfp_event_study.py:1775:                "'NFP released on a Friday'."
experiments/k528/k528_nfp_event_study.py:1797:            "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
experiments/k528/k528_nfp_event_study.py:1801:                "group against a pure-Friday control group, so the p-value absorbs "
experiments/k528/k528_nfp_event_study.py:1802:                "any Friday-vs-other-weekday volatility difference. Retained solely "
experiments/k528/k528_nfp_event_study.py:1904:        "family each was judged in and its Holm-adjusted value. The Friday result is "
experiments/k528/k528_nfp_event_study.py:1905:        "Holm-robust within the six-test confirmatory family and is NOT Holm-robust against "
experiments/k528/k528_nfp_event_study.py:1906:        "all 22 inferential outputs; neither the confirmatory family nor this study as a "
experiments/k528/k528_nfp_event_study.py:1922:_confirmatory_names = {n for n, _ in confirmatory}
experiments/k528/k528_nfp_event_study.py:1939:    confirmatory_member = family_name in _confirmatory_names
experiments/k528/k528_nfp_event_study.py:1941:        "family": "confirmatory" if confirmatory_member else "exploratory",
experiments/k528/k528_nfp_event_study.py:1944:        "p_holm_confirmatory_family": (
experiments/k528/k528_nfp_event_study.py:1945:            dict(zip([n for n, _ in confirmatory], confirmatory_adj))[family_name]
experiments/k528/k528_nfp_event_study.py:1946:            if confirmatory_member else None
experiments/k528/k528_nfp_event_study.py:1949:            "Nominal, then Holm within the declared confirmatory family."
experiments/k528/k528_nfp_event_study.py:1950:            if confirmatory_member else
experiments/k528/k528_nfp_event_study.py:1971:        "family": "confirmatory",
experiments/k528/k528_nfp_event_study.py:1974:            "p_holm_confirmatory_family": float(
experiments/k528/k528_nfp_event_study.py:1975:                dict(zip([n for n, _ in confirmatory], confirmatory_adj))["E_vix_pearson"]),
experiments/k528/k528_nfp_event_study.py:1980:            "p_holm_confirmatory_family": float(
experiments/k528/k528_nfp_event_study.py:1981:                dict(zip([n for n, _ in confirmatory], confirmatory_adj))["E_vix_spearman"]),
experiments/k528/k528_nfp_event_study.py:2007:    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
experiments/k528/k528_nfp_event_study.py:2025:    "n_claims_flipped": n_flipped,
experiments/k528/k528_nfp_event_study_results.json:10:    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
experiments/k528/k528_nfp_event_study_results.json:13:    "total_nfp_events": 253,
experiments/k528/k528_nfp_event_study_results.json:17:    "nfp_days_on_friday": 237,
experiments/k528/k528_nfp_event_study_results.json:18:    "nfp_releases_dated_friday": 243,
experiments/k528/k528_nfp_event_study_results.json:22:      "n_shifted_to_next_session": 6,
experiments/k528/k528_nfp_event_study_results.json:29:      "n_valid_events": 253
experiments/k528/k528_nfp_event_study_results.json:88:        "2025-10": "Federal government shutdown. ALFRED shows no release id 50 entry between 2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed September report landed on 11-20. Same shutdown that cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py. The first-Friday proxy INVENTED an event here -- that phantom is one of the reasons for this rerun."
experiments/k528/k528_nfp_event_study_results.json:91:        "requested": "2005-01-01..2026-03-27",
experiments/k528/k528_nfp_event_study_results.json:98:        "derived_from": "requested window only -- never from the feed",
experiments/k528/k528_nfp_event_study_results.json:106:        "why": "Codex round-5 B2: deleting an endpoint month from the raw feed and the selection together left every feed-relative check self-consistent (259 raw / 253 selected, shortfall inside the 70d tolerance) and the sample silently shortened. The requested window is the one fact a truncated feed cannot edit."
experiments/k528/k528_nfp_event_study_results.json:108:      "residual_limitation": "Two heuristics remain. (1) Same-month selection uses 'earliest wins', which cannot distinguish an off-cycle item filed BEFORE the report from the report itself, so every multi-entry month must additionally appear in REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A new multi-entry month fails the run rather than being assumed. (2) The endpoint expectation can still be silenced by adding a required month to KNOWN_MISSING_MONTHS. That is deliberate -- 2025-10 really was cancelled -- and it is bounded by check 4, which verifies against the RAW feed that a claimed hole is a real hole. What remains uncovered is a month deleted from the raw feed AND declared missing in writing: a documented false claim, not a silent truncation. This gate is fail-closed against the latter, not the former."
experiments/k528/k528_nfp_event_study_results.json:134:      "filter": "session weekday == Friday",
experiments/k528/k528_nfp_event_study_results.json:135:      "estimand": "Among trading sessions falling on a Friday, do the sessions that absorb an NFP release show larger |return| than those that do not? This is a claim about the session that trades the news, NOT about releases dated a Friday.",
experiments/k528/k528_nfp_event_study_results.json:136:      "n_events_total": 253,
experiments/k528/k528_nfp_event_study_results.json:137:      "n_release_date_on_friday": 243,
experiments/k528/k528_nfp_event_study_results.json:138:      "n_traded_in_friday_session": 237,
experiments/k528/k528_nfp_event_study_results.json:180:        "why_excluded": "Every one is a Good Friday: BLS published, the market was shut, the news is absorbed by the following Monday. Their returns are Monday returns and cannot enter a comparison whose control group is pure Friday without reintroducing the weekday confound the restriction exists to remove."
experiments/k528/k528_nfp_event_study_results.json:182:      "why_session_and_not_release_weekday": "The measured quantity is a session return and the confound held fixed is the day-of-week effect of that session. Filtering on release weekday would place these Monday returns against a Friday-only control group.",
experiments/k528/k528_nfp_event_study_results.json:183:      "what_this_does_not_identify": "Not 'NFP in general' (the sample is conditioned on Friday sessions) and not 'releases dated a Friday' (six such releases are traded on a Monday and excluded)."
experiments/k528/k528_nfp_event_study_results.json:204:        "family": "confirmatory",
experiments/k528/k528_nfp_event_study_results.json:207:        "p_holm_confirmatory_family": 0.11206360938619585,
experiments/k528/k528_nfp_event_study_results.json:208:        "how_to_report": "Nominal, then Holm within the declared confirmatory family."
experiments/k528/k528_nfp_event_study_results.json:212:      "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
experiments/k528/k528_nfp_event_study_results.json:213:      "estimand": "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event group is restricted to NFP releases that trade on a Friday, and the 16 non-Friday events are excluded rather than compared against a pure-Friday control group.",
experiments/k528/k528_nfp_event_study_results.json:214:      "claim_scope": "This identifies the effect of an NFP release ABSORBED BY A FRIDAY SESSION. It does not license a statement about NFP releases in general -- the excluded events are quieter, so the restriction raises the ratio relative to the mixed-weekday spec -- and it is NOT a statement about releases DATED a Friday, six of which are Good Fridays traded the following Monday and therefore excluded. Any prose quoting this number must say 'NFP traded in a Friday session', not 'NFP' and not 'NFP released on a Friday'.",
experiments/k528/k528_nfp_event_study_results.json:220:      "n_event": 237,
experiments/k528/k528_nfp_event_study_results.json:231:        "family": "confirmatory",
experiments/k528/k528_nfp_event_study_results.json:234:        "p_holm_confirmatory_family": 0.041708567301642185,
experiments/k528/k528_nfp_event_study_results.json:235:        "how_to_report": "Nominal, then Holm within the declared confirmatory family."
experiments/k528/k528_nfp_event_study_results.json:239:      "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
experiments/k528/k528_nfp_event_study_results.json:241:      "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
experiments/k528/k528_nfp_event_study_results.json:253:        "family": "confirmatory",
experiments/k528/k528_nfp_event_study_results.json:256:        "p_holm_confirmatory_family": 0.005814780156608164,
experiments/k528/k528_nfp_event_study_results.json:257:        "how_to_report": "Nominal, then Holm within the declared confirmatory family."
experiments/k528/k528_nfp_event_study_results.json:272:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:285:        "family": "confirmatory",
experiments/k528/k528_nfp_event_study_results.json:288:          "p_holm_confirmatory_family": 1.1890253436287752e-12,
experiments/k528/k528_nfp_event_study_results.json:293:          "p_holm_confirmatory_family": 6.679994201849973e-08,
experiments/k528/k528_nfp_event_study_results.json:300:      "mean_change": 0.08312253989721004,
experiments/k528/k528_nfp_event_study_results.json:308:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:324:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:338:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:352:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:366:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:380:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:388:      "t_stat": 1.6354952375962966,
experiments/k528/k528_nfp_event_study_results.json:394:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:408:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:422:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:436:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:450:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:464:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:478:        "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:492:      "family": "confirmatory",
experiments/k528/k528_nfp_event_study_results.json:495:      "p_holm_confirmatory_family": 2.275924568911991e-08,
experiments/k528/k528_nfp_event_study_results.json:496:      "how_to_report": "Nominal, then Holm within the declared confirmatory family."
experiments/k528/k528_nfp_event_study_results.json:508:      "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:515:    "total": 253,
experiments/k528/k528_nfp_event_study_results.json:522:      "p_holm_confirmatory_family": null,
experiments/k528/k528_nfp_event_study_results.json:543:    "method": "Holm step-down (FWER, valid under arbitrary dependence)",
experiments/k528/k528_nfp_event_study_results.json:546:    "pre_registration_note": "Not pre-registered. The confirmatory endpoints predate the date correction and this rerun, but were not lodged before the data were seen. Both families are therefore reported and the narrow one is not presented as the only defensible reading.",
experiments/k528/k528_nfp_event_study_results.json:547:    "confirmatory_family": {
experiments/k528/k528_nfp_event_study_results.json:571:          "p_holm": 1.1890253436287752e-12,
experiments/k528/k528_nfp_event_study_results.json:727:      "p_holm_confirmatory_family": 0.041708567301642185,
experiments/k528/k528_nfp_event_study_results.json:729:      "verdict": "Survives Holm within the six-test confirmatory family; does NOT survive Holm against all 22 inferential outputs. Report as nominally significant, Holm-robust only within the declared confirmatory family."
experiments/k528/k528_nfp_event_study_results.json:731:    "exploratory_note": "Everything outside the confirmatory family -- the 12 monthly cells, vol crush, VIX buildup, time trend and direction binomial -- is EXPLORATORY. Nominal p-values are reported for description; none may be quoted as a 5% finding."
experiments/k528/k528_nfp_event_study_results.json:735:    "Welch mean-difference, NFP traded in a Friday session vs Friday non-NFP (CONDITIONAL ON THE FRIDAY SESSION, weekday held fixed): 1.19x, nominal p=0.0209 (rejects at 5% BEFORE any multiplicity correction -- the family-adjusted values live in `multiplicity` and must be quoted alongside this one; n=237 vs 834). Scoped to the releases ABSORBED BY a Friday session, not to releases DATED a Friday: 243 are dated a Friday but only 237 trade in one, the 6 Good Friday releases in between being absorbed by the following Monday. The 16 excluded events are quieter, so this is not a statement about NFP releases in general.",
experiments/k528/k528_nfp_event_study_results.json:737:    "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, so a rank test can detect a location shift the Welch mean test cannot. Report both; do not summarise them as a single verdict.",
experiments/k528/k528_nfp_event_study_results.json:742:  "claim_scope_note": "Every significance statement in this artifact is scoped to its own test. The superseded run summarised these as 'insignificant across all tests', which contradicted the one-sided Mann-Whitney result in the same file (k528 Codex v2 finding 6). Every `significant_5pct` flag here is NOMINAL: see the top-level `multiplicity` block and the per-test `multiplicity` stamp for the family each was judged in and its Holm-adjusted value. The Friday result is Holm-robust within the six-test confirmatory family and is NOT Holm-robust against all 22 inferential outputs; neither the confirmatory family nor this study as a whole was pre-registered.",
experiments/k528/k528_nfp_event_study_results.json:758:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:766:      "vix_change_event": -0.5799999237060547,
experiments/k528/k528_nfp_event_study_results.json:779:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:800:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:821:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:842:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:863:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:884:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:905:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:926:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:929:      "pre_avg_abs_return": 0.00692837547824392,
experiments/k528/k528_nfp_event_study_results.json:947:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:968:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:971:      "pre_avg_abs_return": 0.004914923756553291,
experiments/k528/k528_nfp_event_study_results.json:989:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1010:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1031:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1039:      "vix_change_event": -0.8299999237060547,
experiments/k528/k528_nfp_event_study_results.json:1052:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1073:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1094:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1104:      "volume_ratio": 1.22258592122237
experiments/k528/k528_nfp_event_study_results.json:1115:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1116:      "event_return": -0.006512431511225492,
experiments/k528/k528_nfp_event_study_results.json:1117:      "event_abs_return": 0.006512431511225492,
experiments/k528/k528_nfp_event_study_results.json:1136:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1157:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1178:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1199:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1203:      "post_avg_abs_return": 0.004594124383982679,
experiments/k528/k528_nfp_event_study_results.json:1220:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1223:      "pre_avg_abs_return": 0.0038745221534092432,
experiments/k528/k528_nfp_event_study_results.json:1241:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1262:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1268:      "event_vix": 10.079999923706055,
experiments/k528/k528_nfp_event_study_results.json:1271:      "high_low_range": 0.0039361375253048414,
experiments/k528/k528_nfp_event_study_results.json:1283:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1304:      "session_shifted_from_release": true,
experiments/k528/k528_nfp_event_study_results.json:1325:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1346:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1356:      "volume_ratio": 0.9029092538989029
experiments/k528/k528_nfp_event_study_results.json:1367:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1371:      "post_avg_abs_return": 0.008176682825380555,
experiments/k528/k528_nfp_event_study_results.json:1388:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1409:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1419:      "volume_ratio": 1.4873562376105027
experiments/k528/k528_nfp_event_study_results.json:1430:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1451:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1461:      "volume_ratio": 1.7068308025399932
experiments/k528/k528_nfp_event_study_results.json:1472:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1493:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1514:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1535:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1540:      "pre_vix": 27.549999237060547,
experiments/k528/k528_nfp_event_study_results.json:1544:      "high_low_range": 0.024362065365397475,
experiments/k528/k528_nfp_event_study_results.json:1556:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1577:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1598:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1619:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1640:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1661:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1670:      "high_low_range": 0.023709990288188987,
experiments/k528/k528_nfp_event_study_results.json:1682:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1689:      "post_vix_1d": 52.04999923706055,
experiments/k528/k528_nfp_event_study_results.json:1703:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1724:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1745:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1766:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1787:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1808:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1829:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1833:      "post_avg_abs_return": 0.012715563253330231,
experiments/k528/k528_nfp_event_study_results.json:1835:      "event_vix": 32.04999923706055,
experiments/k528/k528_nfp_event_study_results.json:1850:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1871:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1892:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1913:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1934:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1955:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1976:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1997:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:1998:      "event_return": 0.0033280223799523334,
experiments/k528/k528_nfp_event_study_results.json:1999:      "event_abs_return": 0.0033280223799523334,
experiments/k528/k528_nfp_event_study_results.json:2004:      "post_vix_1d": 17.549999237060547,
experiments/k528/k528_nfp_event_study_results.json:2007:      "volume_ratio": 1.1120587252535024
experiments/k528/k528_nfp_event_study_results.json:2018:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2023:      "pre_vix": 26.079999923706055,
experiments/k528/k528_nfp_event_study_results.json:2039:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2047:      "vix_change_event": -1.2999992370605469,
experiments/k528/k528_nfp_event_study_results.json:2060:      "session_shifted_from_release": true,
experiments/k528/k528_nfp_event_study_results.json:2081:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2086:      "pre_vix": 32.79999923706055,
experiments/k528/k528_nfp_event_study_results.json:2090:      "high_low_range": 0.03918742492579243,
experiments/k528/k528_nfp_event_study_results.json:2102:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2112:      "volume_ratio": 1.4828925864525355
experiments/k528/k528_nfp_event_study_results.json:2123:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2144:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2165:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2172:      "post_vix_1d": 23.799999237060547,
experiments/k528/k528_nfp_event_study_results.json:2186:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2207:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2208:      "event_return": 0.0037623730707110337,
experiments/k528/k528_nfp_event_study_results.json:2209:      "event_abs_return": 0.0037623730707110337,
experiments/k528/k528_nfp_event_study_results.json:2228:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2249:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2258:      "high_low_range": 0.012741821023788735,
experiments/k528/k528_nfp_event_study_results.json:2270:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2273:      "pre_avg_abs_return": 0.009024582253568881,
experiments/k528/k528_nfp_event_study_results.json:2291:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2312:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2333:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2354:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2375:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2396:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2417:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2438:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2459:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2480:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2501:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2522:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2543:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2564:      "session_shifted_from_release": true,
experiments/k528/k528_nfp_event_study_results.json:2585:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2606:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2627:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2648:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2651:      "pre_avg_abs_return": 0.00664069225399746,
experiments/k528/k528_nfp_event_study_results.json:2669:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2690:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2693:      "pre_avg_abs_return": 0.003912371664996628,
experiments/k528/k528_nfp_event_study_results.json:2696:      "event_vix": 14.329999923706055,
experiments/k528/k528_nfp_event_study_results.json:2711:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2732:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2737:      "pre_vix": 16.579999923706055,
experiments/k528/k528_nfp_event_study_results.json:2739:      "post_vix_1d": 16.049999237060547,
experiments/k528/k528_nfp_event_study_results.json:2753:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2759:      "event_vix": 13.829999923706055,
experiments/k528/k528_nfp_event_study_results.json:2774:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2795:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2816:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2837:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2858:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2879:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2883:      "post_avg_abs_return": 0.005460824831793243,
experiments/k528/k528_nfp_event_study_results.json:2900:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2921:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2929:      "vix_change_event": 0.07999992370605469,
experiments/k528/k528_nfp_event_study_results.json:2942:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2948:      "event_vix": 13.329999923706055,
experiments/k528/k528_nfp_event_study_results.json:2963:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2984:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:2989:      "pre_vix": 15.079999923706055,
experiments/k528/k528_nfp_event_study_results.json:3005:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3026:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3029:      "pre_avg_abs_return": 0.00996199441292538,
experiments/k528/k528_nfp_event_study_results.json:3047:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3068:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3077:      "high_low_range": 0.019313256237152857,
experiments/k528/k528_nfp_event_study_results.json:3089:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3110:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3131:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3138:      "post_vix_1d": 11.329999923706055,
experiments/k528/k528_nfp_event_study_results.json:3152:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3160:      "vix_change_event": 0.07999992370605469,
experiments/k528/k528_nfp_event_study_results.json:3173:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3194:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3215:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3236:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3257:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3263:      "event_vix": 17.549999237060547,
experiments/k528/k528_nfp_event_study_results.json:3278:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3285:      "post_vix_1d": 18.549999237060547,
experiments/k528/k528_nfp_event_study_results.json:3299:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3320:      "session_shifted_from_release": true,
experiments/k528/k528_nfp_event_study_results.json:3341:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3345:      "post_avg_abs_return": 0.0038932470724319266,
experiments/k528/k528_nfp_event_study_results.json:3351:      "volume_ratio": 1.5253429732608264
experiments/k528/k528_nfp_event_study_results.json:3362:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3383:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3404:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3425:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3431:      "event_vix": 27.799999237060547,
experiments/k528/k528_nfp_event_study_results.json:3446:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3451:      "pre_vix": 22.549999237060547,
experiments/k528/k528_nfp_event_study_results.json:3467:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3473:      "event_vix": 14.329999923706055,
experiments/k528/k528_nfp_event_study_results.json:3488:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3509:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3516:      "post_vix_1d": 24.299999237060547,
experiments/k528/k528_nfp_event_study_results.json:3530:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3539:      "high_low_range": 0.023782927870619096,
experiments/k528/k528_nfp_event_study_results.json:3551:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3552:      "event_return": 0.0032536768069937327,
experiments/k528/k528_nfp_event_study_results.json:3553:      "event_abs_return": 0.0032536768069937327,
experiments/k528/k528_nfp_event_study_results.json:3554:      "pre_avg_abs_return": 0.008412429192436077,
experiments/k528/k528_nfp_event_study_results.json:3572:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3593:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3614:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3635:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3656:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3677:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3698:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3719:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3724:      "pre_vix": 22.079999923706055,
experiments/k528/k528_nfp_event_study_results.json:3740:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3750:      "volume_ratio": 0.993462870602378
experiments/k528/k528_nfp_event_study_results.json:3761:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3782:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3803:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3824:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3845:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3866:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3887:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3908:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3929:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3950:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3957:      "post_vix_1d": 10.329999923706055,
experiments/k528/k528_nfp_event_study_results.json:3971:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3992:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:3998:      "event_vix": 9.579999923706055,
experiments/k528/k528_nfp_event_study_results.json:4000:      "vix_change_event": -0.5799999237060547,
experiments/k528/k528_nfp_event_study_results.json:4013:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4034:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4055:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4076:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4084:      "vix_change_event": 2.549999237060547,
experiments/k528/k528_nfp_event_study_results.json:4085:      "high_low_range": 0.02737557877000243,
experiments/k528/k528_nfp_event_study_results.json:4097:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4100:      "pre_avg_abs_return": 0.0038653084224312463,
experiments/k528/k528_nfp_event_study_results.json:4118:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4139:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4160:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4168:      "vix_change_event": -0.5499992370605469,
experiments/k528/k528_nfp_event_study_results.json:4181:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4202:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4223:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4244:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4265:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4266:      "event_return": 0.03349574243599118,
experiments/k528/k528_nfp_event_study_results.json:4267:      "event_abs_return": 0.03349574243599118,
experiments/k528/k528_nfp_event_study_results.json:4286:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4307:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4313:      "event_vix": 16.049999237060547,
experiments/k528/k528_nfp_event_study_results.json:4314:      "post_vix_1d": 14.329999923706055,
experiments/k528/k528_nfp_event_study_results.json:4328:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4333:      "pre_vix": 13.579999923706055,
experiments/k528/k528_nfp_event_study_results.json:4349:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4370:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4371:      "event_return": 0.010006757672534228,
experiments/k528/k528_nfp_event_study_results.json:4372:      "event_abs_return": 0.010006757672534228,
experiments/k528/k528_nfp_event_study_results.json:4376:      "event_vix": 16.299999237060547,
experiments/k528/k528_nfp_event_study_results.json:4391:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4412:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4433:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4454:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4462:      "vix_change_event": -2.0799999237060547,
experiments/k528/k528_nfp_event_study_results.json:4475:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4482:      "post_vix_1d": 12.829999923706055,
experiments/k528/k528_nfp_event_study_results.json:4496:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4517:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4527:      "volume_ratio": 0.9123185446202431
experiments/k528/k528_nfp_event_study_results.json:4538:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4559:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4580:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4586:      "event_vix": 46.79999923706055,
experiments/k528/k528_nfp_event_study_results.json:4601:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4622:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4643:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4664:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4685:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4706:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4727:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4732:      "pre_vix": 27.579999923706055,
experiments/k528/k528_nfp_event_study_results.json:4748:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4755:      "post_vix_1d": 21.299999237060547,
experiments/k528/k528_nfp_event_study_results.json:4769:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4776:      "post_vix_1d": 24.079999923706055,
experiments/k528/k528_nfp_event_study_results.json:4790:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4791:      "event_return": 0.00393612433833046,
experiments/k528/k528_nfp_event_study_results.json:4792:      "event_abs_return": 0.00393612433833046,
experiments/k528/k528_nfp_event_study_results.json:4811:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4832:      "session_shifted_from_release": true,
experiments/k528/k528_nfp_event_study_results.json:4837:      "pre_vix": 17.329999923706055,
experiments/k528/k528_nfp_event_study_results.json:4840:      "vix_change_event": 0.5799999237060547,
experiments/k528/k528_nfp_event_study_results.json:4853:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4856:      "pre_avg_abs_return": 0.004638924985392534,
experiments/k528/k528_nfp_event_study_results.json:4874:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4895:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4916:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4937:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4958:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:4959:      "event_return": -0.0018237895765306211,
experiments/k528/k528_nfp_event_study_results.json:4960:      "event_abs_return": 0.0018237895765306211,
experiments/k528/k528_nfp_event_study_results.json:4979:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5000:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5001:      "event_return": -0.008701292232374147,
experiments/k528/k528_nfp_event_study_results.json:5002:      "event_abs_return": 0.008701292232374147,
experiments/k528/k528_nfp_event_study_results.json:5010:      "volume_ratio": 1.1310925338714326
experiments/k528/k528_nfp_event_study_results.json:5021:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5042:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5063:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5084:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5105:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5126:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5129:      "pre_avg_abs_return": 0.015454737368262372,
experiments/k528/k528_nfp_event_study_results.json:5147:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5152:      "pre_vix": 26.079999923706055,
experiments/k528/k528_nfp_event_study_results.json:5168:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5189:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5192:      "pre_avg_abs_return": 0.012437271948932672,
experiments/k528/k528_nfp_event_study_results.json:5210:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5220:      "volume_ratio": 1.0415054253418123
experiments/k528/k528_nfp_event_study_results.json:5231:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5236:      "pre_vix": 25.299999237060547,
experiments/k528/k528_nfp_event_study_results.json:5237:      "event_vix": 24.549999237060547,
experiments/k528/k528_nfp_event_study_results.json:5252:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5255:      "pre_avg_abs_return": 0.010026988253158464,
experiments/k528/k528_nfp_event_study_results.json:5262:      "volume_ratio": 1.1479992434797885
experiments/k528/k528_nfp_event_study_results.json:5273:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5281:      "vix_change_event": -1.3299999237060547,
experiments/k528/k528_nfp_event_study_results.json:5282:      "high_low_range": 0.025355588225001967,
experiments/k528/k528_nfp_event_study_results.json:5294:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5300:      "event_vix": 18.329999923706055,
experiments/k528/k528_nfp_event_study_results.json:5315:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5321:      "event_vix": 24.799999237060547,
experiments/k528/k528_nfp_event_study_results.json:5336:      "session_shifted_from_release": true,
experiments/k528/k528_nfp_event_study_results.json:5357:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5378:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5386:      "vix_change_event": -1.0499992370605469,
experiments/k528/k528_nfp_event_study_results.json:5399:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5405:      "event_vix": 14.829999923706055,
experiments/k528/k528_nfp_event_study_results.json:5420:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5441:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5462:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5483:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5504:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5525:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5532:      "post_vix_1d": 13.079999923706055,
experiments/k528/k528_nfp_event_study_results.json:5546:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5567:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5588:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5609:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5630:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5635:      "pre_vix": 12.579999923706055,
experiments/k528/k528_nfp_event_study_results.json:5651:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5672:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5673:      "event_return": -0.018618371424376612,
experiments/k528/k528_nfp_event_study_results.json:5674:      "event_abs_return": 0.018618371424376612,
experiments/k528/k528_nfp_event_study_results.json:5680:      "vix_change_event": 4.799999237060547,
experiments/k528/k528_nfp_event_study_results.json:5693:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5714:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5718:      "post_avg_abs_return": 0.006632535408032414,
experiments/k528/k528_nfp_event_study_results.json:5735:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5756:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5777:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5778:      "event_return": -0.015267533310024395,
experiments/k528/k528_nfp_event_study_results.json:5779:      "event_abs_return": 0.015267533310024395,
experiments/k528/k528_nfp_event_study_results.json:5798:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5819:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5820:      "event_return": 0.005604885237354251,
experiments/k528/k528_nfp_event_study_results.json:5821:      "event_abs_return": 0.005604885237354251,
experiments/k528/k528_nfp_event_study_results.json:5840:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5861:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5882:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5903:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5924:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5925:      "event_return": -0.016390515253635662,
experiments/k528/k528_nfp_event_study_results.json:5926:      "event_abs_return": 0.016390515253635662,
experiments/k528/k528_nfp_event_study_results.json:5945:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5966:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:5987:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:6008:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:6012:      "post_avg_abs_return": 0.002409243560045993,
experiments/k528/k528_nfp_event_study_results.json:6029:      "session_shifted_from_release": false,
experiments/k528/k528_nfp_event_study_results.json:6050:      "session_shifted_from_release": false,

2026-07-27T00:29:40.216477Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "jq 'keys' experiments/k528/k528_nfp_event_study_results.json
jq 'keys' experiments/k528/k528_nfp_official_dates_results.json
rg -n '"'^def (check_calendar_is_complete|check_price_coverage|check_vix_forward_fill_age|main|load_|holm|build_|run_)|KNOWN_MISSING_MONTHS|REVIEWED_MULTI_ENTRY_MONTHS|REQUESTED|request_start|request_end|calendar_request|expected_month'"' experiments/k528/k528_nfp_event_study.py src/volpred/data/event_dates.py
rg -n 'class TestReleaseMisbindingGateIsStructural|nearest|governor|misbind|blocklist|structur' tests/test_nfp_official_release_dates.py" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
[
  "april_nfp",
  "claim_scope_note",
  "conclusions",
  "data_source",
  "date",
  "directional_bias",
  "event_data",
  "event_date_source",
  "experiment_id",
  "intraday_range",
  "main_results",
  "multiplicity",
  "practical_implication",
  "references",
  "regime_analysis",
  "sample",
  "seasonal_analysis",
  "statistical_tests",
  "time_trend",
  "title",
  "volume"
]
[
  "after_source",
  "article_correction",
  "before_source",
  "calendar_diff",
  "event_date_source",
  "experiment_id",
  "generated_at",
  "items",
  "n_claims_audited",
  "n_claims_flipped",
  "title",
  "win_rate_definition"
]
experiments/k528/k528_nfp_event_study.py:73:KNOWN_MISSING_MONTHS: dict[str, str] = {
experiments/k528/k528_nfp_event_study.py:109:REVIEWED_MULTI_ENTRY_MONTHS: dict[str, dict] = {
experiments/k528/k528_nfp_event_study.py:136:# REQUESTED WINDOW ALONE. That independence is the whole point: every other check
experiments/k528/k528_nfp_event_study.py:189:def check_calendar_is_complete(selected, raw, start, end):
experiments/k528/k528_nfp_event_study.py:275:    unreviewed = sorted(set(multi) - set(REVIEWED_MULTI_ENTRY_MONTHS))
experiments/k528/k528_nfp_event_study.py:283:            "REVIEWED_MULTI_ENTRY_MONTHS."
experiments/k528/k528_nfp_event_study.py:288:        m: {"now": [str(d.date()) for d in multi[m]], "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]}
experiments/k528/k528_nfp_event_study.py:290:        if [str(d.date()) for d in multi[m]] != REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]
experiments/k528/k528_nfp_event_study.py:300:            "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]}
experiments/k528/k528_nfp_event_study.py:302:        if m in sel_by_month and str(sel_by_month[m].date()) != REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]
experiments/k528/k528_nfp_event_study.py:315:    # UNCONDITIONAL: no KNOWN_MISSING_MONTHS subtraction here. If the raw feed has
experiments/k528/k528_nfp_event_study.py:326:            "silently shortened sample. This is not excusable via KNOWN_MISSING_MONTHS: "
experiments/k528/k528_nfp_event_study.py:334:    both = sorted(set(KNOWN_MISSING_MONTHS) & set(REVIEWED_MULTI_ENTRY_MONTHS))
experiments/k528/k528_nfp_event_study.py:337:            f"month(s) {both} appear in both KNOWN_MISSING_MONTHS and "
experiments/k528/k528_nfp_event_study.py:338:            "REVIEWED_MULTI_ENTRY_MONTHS. A month cannot both have published nothing and "
experiments/k528/k528_nfp_event_study.py:388:    absent_required = sorted(set(required_months) - set(sel_months) - set(KNOWN_MISSING_MONTHS))
experiments/k528/k528_nfp_event_study.py:393:            f"{absent_required}. This is derived from the REQUESTED WINDOW, not from the feed, "
experiments/k528/k528_nfp_event_study.py:403:    missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
experiments/k528/k528_nfp_event_study.py:408:            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
experiments/k528/k528_nfp_event_study.py:417:    bogus = sorted(m for m in KNOWN_MISSING_MONTHS if raw_by_month.get(m))
experiments/k528/k528_nfp_event_study.py:420:            f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
experiments/k528/k528_nfp_event_study.py:429:        "reviewed_multi_entry_months": dict(sorted(REVIEWED_MULTI_ENTRY_MONTHS.items())),
experiments/k528/k528_nfp_event_study.py:431:        "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
experiments/k528/k528_nfp_event_study.py:445:            "excused_by_known_missing": sorted(set(required_months) & set(KNOWN_MISSING_MONTHS)),
experiments/k528/k528_nfp_event_study.py:457:            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A new "
experiments/k528/k528_nfp_event_study.py:460:            "KNOWN_MISSING_MONTHS. That is deliberate -- 2025-10 really was cancelled -- and "
experiments/k528/k528_nfp_event_study.py:469:def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
experiments/k528/k528_nfp_event_study.py:505:def check_price_coverage(frame, ticker, start, end):
experiments/k528/k528_nfp_event_study.py:555:def check_vix_forward_fill_age(vix_series):
experiments/k528/k528_nfp_event_study.py:1037:def holm_adjust(pvals):
875:# Round-7 N1: a STRUCTURAL detector for the 237-as-a-release-count misbinding.
879:# "structural invariant" that was really a 5-phrase blocklist with two
886:#     nearest governing verb (within a small window) is a release/publication
910:    "wrong", "typo", "erratum", "errata", "correction", "misbind",
949:def _nearest_gap(friday_span, verb_spans):
951:    (0 if they overlap), or None if the nearest is beyond ``_MAX_BIND_GAP``."""
971:    Nearest-governor rather than a fixed window because the two readings sit at
975:    unrelated '243 trading weeks'; comparing which governor is CLOSER does not.
976:    Ties go to release (the misbinding), so appending a distant session word
987:        rd = _nearest_gap(span, release_spans)
988:        sd = _nearest_gap(span, session_spans)
996:def _clause_misbinds_237(clause):
1015:def _release_misbinding_offenders(text):
1017:    misbind 237. `text` is normally one logical unit (a Markdown/JSON physical
1022:        bad, reason = _clause_misbinds_237(clause)
1029:    """Yield ``(lineno, text)`` logical units for the misbinding scan.
1110:        """Round-5 B1 residual, rebuilt in round 7 (N1) from a 5-phrase blocklist
1111:        into a compositional, proximity-aware structural check.
1121:        now delegates to (``_release_misbinding_offenders``) reads release-dated
1151:                for clause, reason in _release_misbinding_offenders(unit):
1189:class TestReleaseMisbindingGateIsStructural:
1190:    """Round-7 N1. The round-6 guard was a 5-phrase blocklist and the round-6
1199:    ``_clause_misbinds_237`` back into a wordlist, the synonym cases go red.
1208:        # -- four synonym rephrasings that the 5-phrase blocklist missed --
1255:    def test_misbindings_are_caught(self, text):
1256:        assert _release_misbinding_offenders(text), (
1257:            "the hardened gate let a 237-as-a-release-count misbinding through: "
1263:        hits = _release_misbinding_offenders(text)
1274:        assert _release_misbinding_offenders(
1281:        assert _release_misbinding_offenders(
1289:        assert _release_misbinding_offenders("event group of 237 Friday releases")
1290:        assert not _release_misbinding_offenders(

2026-07-27T00:29:49.507646Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "sed -n '1,480p' experiments/k528/k528_nfp_event_study.py
sed -n '505,610p' experiments/k528/k528_nfp_event_study.py
sed -n '1,164p' src/volpred/data/event_dates.py
jq '{sample,event_date_source,main_results,regime_analysis,statistical_tests,multiplicity,conclusions,claim_scope_note}' experiments/k528/k528_nfp_event_study_results.json
jq '{event_date_source,calendar_diff,n_claims_audited,n_claims_flipped,article_correction,items}' experiments/k528/k528_nfp_official_dates_results.json" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
"""
K528: NFP (Non-Farm Payrolls) Event Study on SPY Volatility
=============================================================
Extends K513 (FOMC/NFP/CPI event study) with deeper NFP-specific analysis.

K513 finding: NFP vol ratio = 1.09x (NS, p=0.195). This study digs deeper:
  - Larger sample with more granular windows
  - VIX predictive regression
  - Vol crush pattern analysis
  - Seasonal decomposition (which months matter?)
  - NFP surprise impact (FRED PAYEMS data)

Data sources:
  - SPY daily OHLCV: yfinance (2005-01 to 2026-03)
  - VIX daily close: yfinance (^VIX)
  - NFP dates: OFFICIAL BLS release calendar via ALFRED (FRED release id 50)
  - NFP actual values: FRED PAYEMS (monthly, for surprise calculation)

CORRECTION 2026-07-19
---------------------
The original run dated every NFP to the first Friday of the month. That proxy is
wrong for ~20% of the sample and it is wrong SYSTEMATICALLY, not randomly: BLS
moves the release to the second Friday whenever the reference week falls late
(28 dates land exactly 7 days early), and pulls it forward around holidays (12
dates land 3-4 days late). It also invents a release in 2025-10 that never
happened, and it forces every event onto a Friday when 16 of the 254 official
releases are not on a Friday at all.

Wrong event dates do not fail loudly. They count quiet days as event days and
dump real event days into the control group, and the figures still render. So
the dates now come from the official release calendar and the run FAILS CLOSED
if that calendar is unreachable -- `get_first_friday` is gone, not deprecated.

This script also emits a before/after comparison against the archived proxy-era
results so the correction's effect on every published number is auditable
(k528_nfp_official_dates_results.json).

References:
  - Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?"
    JFE, core finding: scheduled macro announcements earn risk premium
  - Lucca & Moench (2015) "The Pre-FOMC Announcement Drift" JFE
  - K513: Our prior FOMC/NFP/CPI event study (2005-2025, 668 events)
  - K1442: event-date audit that found this bug

Author: VolPred Research System
Date: 2026-03-27 (corrected 2026-07-19)
"""

import json
import os
import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

from volpred.data.event_dates import RELEASE_IDS, _fetch, nfp_release_dates

warnings.filterwarnings("ignore")

SAMPLE_START = "2005-01-01"
SAMPLE_END = "2026-03-27"

# Months for which BLS published no Employment Situation report at all. Each
# entry needs a documented reason, and check_calendar_is_complete VERIFIES the
# claim against the raw feed before honouring it -- an allowlist that is taken
# on faith is just a way to make a failing check pass, which is the failure mode
# this whole experiment exists to document.
KNOWN_MISSING_MONTHS: dict[str, str] = {
    "2025-10": (
        "Federal government shutdown. ALFRED shows no release id 50 entry between "
        "2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed "
        "September report landed on 11-20. Same shutdown that cancelled the Oct-2025 "
        "CPI release described in volpred/data/event_dates.py. The first-Friday proxy "
        "INVENTED an event here -- that phantom is one of the reasons for this rerun."
    ),
}

# Two same-month entries closer together than this cannot be told apart as
# "regular report" vs "off-cycle revision" by date order alone, so the run
# refuses to guess.
#
# A correction I got wrong once and am recording so it is not repeated: I removed
# this gate claiming the real feed "straddles" it, because three genuine cases
# (2006-05, 2013-05, 2020-05) are exactly 3 days apart. That was a misreading of
# my own condition -- the test is `gap < 3`, and a 3-day gap passes it. The real
# data never falsified this gate; I falsified it by first changing `<` to `<=`
# and then deleting it. It is restored, at `< 3`, where every real case passes.
AMBIGUOUS_SAME_MONTH_GAP_DAYS = 3

# The months where ALFRED returns two release-id-50 entries, pinned as the FULL
# raw date set plus which entry is the actual Employment Situation report. Each
# verified individually against the BLS news-release archive
# (bls.gov/news.release/archives/empsit_<MMDDYYYY>.htm).
#
# Why an explicit reviewed list rather than a rule: "earliest entry in the month"
# is right for every case we have checked, but it is a HEURISTIC, and it fails
# silently if an off-cycle item is ever filed BEFORE the report. There is no way
# to tell those apart from dates alone.
#
# Why the full date set and not just the month key: authorising a MONTH means a
# reviewed month whose feed later gains a third entry still sails through on a
# review that never saw it. The approval has to be of the shape someone actually
# looked at, so a change to that shape sends it back for review.
REVIEWED_MULTI_ENTRY_MONTHS: dict[str, dict] = {
    "2006-05": {"raw": ["2006-05-05", "2006-05-08"], "report": "2006-05-05"},
    "2012-12": {"raw": ["2012-12-07", "2012-12-12"], "report": "2012-12-07"},
    "2013-05": {"raw": ["2013-05-03", "2013-05-06"], "report": "2013-05-03"},
    "2020-05": {"raw": ["2020-05-08", "2020-05-11"], "report": "2020-05-08"},
    "2024-01": {"raw": ["2024-01-05", "2024-01-10"], "report": "2024-01-05"},
    "2024-08": {"raw": ["2024-08-02", "2024-08-21"], "report": "2024-08-02"},
}

# How far the observed calendar may fall short of the requested window before the
# run treats it as truncated. One monthly cycle plus slack; a feed that stops
# early otherwise shrinks the "observed span" it is checked against and passes.
#
# This tolerance is NOT the endpoint defence -- see EXPECTED_MONTHS below. 70 days
# is wide enough for an entire endpoint month to vanish from raw AND selected
# together, which is exactly the hole Codex round-5 B2 reproduced. It is kept
# because it catches a different shape (a feed that is wildly off-window), but it
# is no longer the thing standing between this run and a silently shortened sample.
MAX_WINDOW_SHORTFALL_DAYS = 70

# The latest day-of-month on which the Employment Situation has ever been
# published in this sample: 2013-10-22, delayed by the October 2013 federal
# shutdown (the 2025 shutdown produced 2025-11-20 and 2025-12-16, both earlier in
# the month). Regular releases land on the first or second Friday, i.e. day 1-14;
# this bound is the shutdown-delayed worst case plus nothing.
#
# It exists so the required-month expectation below can be derived from the
# REQUESTED WINDOW ALONE. That independence is the whole point: every other check
# in this function reasons about the feed using the feed, so a feed that is short
# at one end simply moves the yardstick with it. Codex round-5 B2:
#
#     deleting 2005-01 from raw AND selected together -> 259/253, head shortfall
#     34d, passes; deleting 2026-03 the same way -> 259/253, tail shortfall 44d,
#     passes
#
# Nothing in the old gate could see either, because after the deletion the
# observed span, the raw->selected diff and the allowlists were all self-consistent.
# The requested window is the one fact the feed cannot edit.
LATEST_OBSERVED_RELEASE_DAY_OF_MONTH = 22

# How far SPY / ^VIX may fall short of the requested window at either end. The
# window edges are calendar dates, the data are sessions, so a few days of slack
# is structural (2005-01-01 is a Saturday; yfinance's `end` is exclusive). Ten
# days covers the longest holiday weekend and is still a fifth of the ~30 days it
# would take to lose a month.
MAX_PRICE_COVERAGE_SHORTFALL_DAYS = 10

# How many consecutive SPY sessions may carry a forward-filled VIX. Observed max
# in this sample is 0 -- ^VIX and SPY trade the same calendar -- so this is pure
# headroom for a stray holiday mismatch, not an accommodation of anything real.
MAX_VIX_FFILL_TRADING_DAYS = 3


def write_json_atomic(path: Path, payload) -> None:
    """Write `payload` to `path` atomically.

    A truncate-then-write leaves a half-written results file on the disk if the
    run dies mid-dump, and a half-written results file is worse than none: it
    still parses far enough to look like data to the next reader. Write to a
    temp file in the same directory, fsync, then os.replace (atomic on POSIX).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
        raise


# ============================================================
# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
# ============================================================
def check_calendar_is_complete(selected, raw, start, end):
    """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.

    "Did the call succeed?" is the wrong question. A monthly release calendar
    that silently lost 2019 still returns a non-empty list, still produces
    event windows, still renders.

    This validates the RAW feed as well as the accessor's per-month selection.
    Validating only the selection cannot work: the accessor collapses each month
    to one date before this function ever sees it, so a same-month ambiguity is
    already resolved -- silently, and possibly wrongly -- by the time a check on
    the output could look for it. That is precisely how the k528 v2 BLOCKER got
    through (Codex v3 finding 3).

    Four ways the input can be wrong without being empty, all of which raise:
      1. a month has two entries too close together to tell report from revision
      2. the selection is not the earliest entry of its month
      3. a month is missing from the observed span
      4. a month is claimed as a known hole but the raw feed actually has data
    """
    sel = [pd.Timestamp(d) for d in selected]
    sel_months = [d.strftime("%Y-%m") for d in sel]

    raw_by_month: dict[str, list[pd.Timestamp]] = {}
    for d in raw:
        ts = pd.Timestamp(d)
        raw_by_month.setdefault(ts.strftime("%Y-%m"), []).append(ts)
    for v in raw_by_month.values():
        v.sort()

    # 0: the selection itself must be well-formed before anything is inferred
    # from it. Building a month->date dict first would silently keep only the
    # last of a duplicated month and hide exactly what we are looking for.
    sel_month_counts: dict[str, int] = {}
    for m in sel_months:
        sel_month_counts[m] = sel_month_counts.get(m, 0) + 1
    sel_dupes = sorted(m for m, c in sel_month_counts.items() if c > 1)
    if sel_dupes:
        raise RuntimeError(
            f"selected calendar has more than one entry for {sel_dupes}. The Employment "
            "Situation is monthly; a duplicated month means the accessor stopped collapsing."
        )
    invented = sorted(set(sel_months) - set(raw_by_month))
    if invented:
        raise RuntimeError(
            f"selected calendar contains month(s) absent from the raw feed: {invented}. "
            "The selection must be a subset of what the source actually published."
        )
    off_feed = sorted(str(d.date()) for d in sel if d not in raw_by_month.get(d.strftime("%Y-%m"), []))
    if off_feed:
        raise RuntimeError(
            f"selected dates that do not appear in the raw feed at all: {off_feed}."
        )

    # 1: the accessor's per-month choice must be the earliest entry, and any
    # same-month pair must be far enough apart to tell report from revision.
    ambiguous, mis_selected = [], []
    sel_by_month = dict(zip(sel_months, sel))
    for month, entries in raw_by_month.items():
        if len(entries) > 1:
            gap = (entries[1] - entries[0]).days
            if gap < AMBIGUOUS_SAME_MONTH_GAP_DAYS:
                ambiguous.append(
                    f"{month}: {entries[0].date()} vs {entries[1].date()} ({gap}d apart)"
                )
        if month in sel_by_month and sel_by_month[month] != entries[0]:
            mis_selected.append(
                f"{month}: selected {sel_by_month[month].date()}, earliest is {entries[0].date()}"
            )
    if ambiguous:
        raise RuntimeError(
            f"{len(ambiguous)} month(s) carry two release entries too close together to "
            f"identify the Employment Situation report by date order: {ambiguous}. "
            "Refusing to guess which one is the monthly report."
        )
    if mis_selected:
        raise RuntimeError(
            f"accessor did not select the earliest entry in {len(mis_selected)} month(s): "
            f"{mis_selected}. The later same-month entry is an off-cycle revision, not the "
            "monthly report -- selecting it is the k528 v2 BLOCKER."
        )

    # "Earliest wins" is a heuristic and cannot survive an off-cycle item filed
    # BEFORE the report. Every multi-entry month therefore has to be one a human
    # checked against the BLS archive, and the checked answer has to match.
    multi = {m: v for m, v in raw_by_month.items() if len(v) > 1}
    unreviewed = sorted(set(multi) - set(REVIEWED_MULTI_ENTRY_MONTHS))
    if unreviewed:
        raise RuntimeError(
            f"{len(unreviewed)} month(s) carry multiple release entries but have never been "
            f"checked against the BLS archive: "
            f"{ {m: [str(d.date()) for d in multi[m]] for m in unreviewed} }. "
            "Selecting the earliest is only a heuristic; verify which entry is the Employment "
            "Situation report at bls.gov/news.release/archives/ and add it to "
            "REVIEWED_MULTI_ENTRY_MONTHS."
        )
    # Approve the SHAPE, not the month. A reviewed month whose feed later gains
    # or loses an entry is a shape nobody reviewed, so it goes back for review.
    reshaped = {
        m: {"now": [str(d.date()) for d in multi[m]], "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]}
        for m in multi
        if [str(d.date()) for d in multi[m]] != REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]
    }
    if reshaped:
        raise RuntimeError(
            f"the raw feed for reviewed month(s) no longer matches what was reviewed: {reshaped}. "
            "The approval covers the entry set someone actually checked, not the month name. "
            "Re-verify against bls.gov/news.release/archives/ before proceeding."
        )
    contradicted = {
        m: {"selected": str(sel_by_month[m].date()),
            "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]}
        for m in multi
        if m in sel_by_month and str(sel_by_month[m].date()) != REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]
    }
    if contradicted:
        raise RuntimeError(
            f"selection contradicts the human-verified release date in {contradicted}. "
            "Either the feed changed or the accessor regressed; do not proceed on the guess."
        )

    # Every month the source published must survive into the selection. Without
    # this, a month can vanish between raw and selected (stale accessor cache vs
    # a live raw fetch is exactly that shape) and neither the gap check nor the
    # window-coverage check sees it -- the observed span just ends one month
    # earlier and still looks continuous.
    # UNCONDITIONAL: no KNOWN_MISSING_MONTHS subtraction here. If the raw feed has
    # entries for a month, that month is not missing -- whatever a list says. The
    # earlier version subtracted the allowlist, which let a tail month be dropped
    # from the selection and then excused by declaring it "known missing", while
    # the counter-check that would have caught the lie only looked inside the
    # selected span (Codex v3 round-4 BLOCKER).
    dropped = sorted(set(raw_by_month) - set(sel_months))
    if dropped:
        raise RuntimeError(
            f"the raw feed has {len(dropped)} month(s) that the selected calendar does not: "
            f"{dropped}. A month present at the source and absent from the analysis is a "
            "silently shortened sample. This is not excusable via KNOWN_MISSING_MONTHS: "
            "that list is for months the source never published."
        )

    # The two allowlists must not overlap. "This month published nothing" and
    # "this month published several entries I reviewed" cannot both be true, and
    # allowing both is what turned two independently-reasonable lists into a
    # bypass when combined.
    both = sorted(set(KNOWN_MISSING_MONTHS) & set(REVIEWED_MULTI_ENTRY_MONTHS))
    if both:
        raise RuntimeError(
            f"month(s) {both} appear in both KNOWN_MISSING_MONTHS and "
            "REVIEWED_MULTI_ENTRY_MONTHS. A month cannot both have published nothing and "
            "have a reviewed multi-entry shape."
        )

    # 3a: the observed span must actually cover what was asked for. Checking only
    # for gaps INSIDE the observed span cannot catch truncation -- if the feed
    # stops early, the span shrinks with it and nothing looks missing. Found by
    # self-audit while Codex v3 round-2 was running.
    want_start, want_end = pd.Timestamp(start), pd.Timestamp(end)
    head_short = (min(sel) - want_start).days
    tail_short = (want_end - max(sel)).days
    if head_short > MAX_WINDOW_SHORTFALL_DAYS or tail_short > MAX_WINDOW_SHORTFALL_DAYS:
        raise RuntimeError(
            f"official NFP calendar does not cover the requested window "
            f"{start}..{end}: first release {min(sel).date()} ({head_short}d in), "
            f"last release {max(sel).date()} ({tail_short}d short of the end). "
            f"Tolerance is {MAX_WINDOW_SHORTFALL_DAYS}d. A truncated feed silently "
            "shortens the sample while every printed count still agrees with itself."
        )

    # 3a-bis: THE ENDPOINT EXPECTATION. Every check above (and 3a) reasons about
    # the feed using the feed, so deleting an endpoint month from raw and selected
    # at the same time moves every yardstick with it and nothing looks wrong. This
    # check derives what MUST be there from the requested window alone.
    #
    # A month is required when the window contains the whole interval in which its
    # report could have been published: day 1 (earliest possible) through
    # LATEST_OBSERVED_RELEASE_DAY_OF_MONTH (shutdown-delayed worst case). Anything
    # narrower would demand a release the window may legitimately cut off.
    #
    # The constant is self-policing: if the feed ever carries a release later in
    # its month than the constant allows, the premise of this rule has expired and
    # the run says so instead of quietly under-requiring.
    latest_day_seen = max((d.day for d in sel), default=0)
    if latest_day_seen > LATEST_OBSERVED_RELEASE_DAY_OF_MONTH:
        offenders = sorted(str(d.date()) for d in sel if d.day > LATEST_OBSERVED_RELEASE_DAY_OF_MONTH)
        raise RuntimeError(
            f"release(s) {offenders} fall later in their month than "
            f"LATEST_OBSERVED_RELEASE_DAY_OF_MONTH={LATEST_OBSERVED_RELEASE_DAY_OF_MONTH}. "
            "That constant is the premise of the required-month endpoint check; a later "
            "release means the premise is stale and the endpoint expectation would silently "
            "under-require. Re-derive the constant against the BLS archive before proceeding."
        )

    required_months = sorted(
        p.strftime("%Y-%m")
        for p in pd.period_range(start=want_start, end=want_end, freq="M")
        if p.to_timestamp() >= want_start
        and p.to_timestamp().replace(day=LATEST_OBSERVED_RELEASE_DAY_OF_MONTH) <= want_end
    )
    absent_required = sorted(set(required_months) - set(sel_months) - set(KNOWN_MISSING_MONTHS))
    if absent_required:
        raise RuntimeError(
            f"the requested window {start}..{end} fully contains the publication window of "
            f"{len(absent_required)} month(s) that the calendar has no release for: "
            f"{absent_required}. This is derived from the REQUESTED WINDOW, not from the feed, "
            "so it still fires when a month is deleted from the raw feed and the selection at "
            "the same time -- the case the observed-span checks structurally cannot see."
        )

    # 3b: no month may vanish from inside the observed span.
    span = {
        p.strftime("%Y-%m")
        for p in pd.period_range(start=min(sel), end=max(sel), freq="M")
    }
    missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
    if missing:
        raise RuntimeError(
            f"official NFP calendar is missing {len(missing)} month(s) inside the observed "
            f"span: {missing}. A partial calendar dumps real event days into the control "
            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
            "reason (e.g. a cancelled release), never to make this check pass."
        )

    # 4: a claimed hole must actually be a hole in the RAW feed. Without this the
    # allowlist is a bypass: any month could be declared 'known missing' and the
    # check would stop looking at it.
    # Scan the WHOLE allowlist, not just the part inside the observed span: a
    # claim about a month outside the span is exactly the one nobody re-checks.
    bogus = sorted(m for m in KNOWN_MISSING_MONTHS if raw_by_month.get(m))
    if bogus:
        raise RuntimeError(
            f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
            f"entries for them: { {m: [str(d.date()) for d in raw_by_month[m]] for m in bogus} }. "
            "The allowlist is for real cancellations, not for silencing a selection bug."
        )

    return {
        "n_months_in_span": len(span),
        "n_raw_entries": len(raw),
        "months_with_multiple_raw_entries": sorted(multi),
        "reviewed_multi_entry_months": dict(sorted(REVIEWED_MULTI_ENTRY_MONTHS.items())),
        "ambiguity_gap_threshold_days": AMBIGUOUS_SAME_MONTH_GAP_DAYS,
        "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
        "window_coverage": {
            "requested": f"{start}..{end}",
            "observed": f"{min(sel).date()}..{max(sel).date()}",
            "head_shortfall_days": int(head_short),
            "tail_shortfall_days": int(tail_short),
            "tolerance_days": MAX_WINDOW_SHORTFALL_DAYS,
        },
        "endpoint_expectation": {
            "derived_from": "requested window only -- never from the feed",
            "latest_observed_release_day_of_month": LATEST_OBSERVED_RELEASE_DAY_OF_MONTH,
            "n_required_months": len(required_months),
            "required_first_month": required_months[0] if required_months else None,
            "required_last_month": required_months[-1] if required_months else None,
            "excused_by_known_missing": sorted(set(required_months) & set(KNOWN_MISSING_MONTHS)),
            "why": (
                "Codex round-5 B2: deleting an endpoint month from the raw feed and the "
                "selection together left every feed-relative check self-consistent (259 raw / "
                "253 selected, shortfall inside the 70d tolerance) and the sample silently "
                "shortened. The requested window is the one fact a truncated feed cannot edit."
            ),
        },
        "residual_limitation": (
            "Two heuristics remain. (1) Same-month selection uses 'earliest wins', which "
            "cannot distinguish an off-cycle item filed BEFORE the report from the report "
            "itself, so every multi-entry month must additionally appear in "
            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A new "
            "multi-entry month fails the run rather than being assumed. (2) The endpoint "
            "expectation can still be silenced by adding a required month to "
            "KNOWN_MISSING_MONTHS. That is deliberate -- 2025-10 really was cancelled -- and "
            "it is bounded by check 4, which verifies against the RAW feed that a claimed "
            "hole is a real hole. What remains uncovered is a month deleted from the raw feed "
            "AND declared missing in writing: a documented false claim, not a silent "
            "truncation. This gate is fail-closed against the latter, not the former."
        ),
    }


def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
    """Official NFP (Employment Situation) release dates.

    Deliberately has no except branch. If the release calendar cannot be
    reached, this run must die -- a proxy calendar produces plausible numbers
    from non-events, which is worse than no numbers at all. See the CORRECTION
    note in the module docstring.
    """
    dates = nfp_release_dates(start, end)
    if len(dates) == 0:
        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
    # Pull the unselected feed as well: the accessor collapses each month to one
def check_price_coverage(frame, ticker, start, end):
    """Fail closed on a price series that does not reach both ends of the window.

    Codex round-5 B3: there was no coverage check here at all. A SPY download
    ending a month early does not raise and does not produce NaNs -- the releases
    past the end simply get filed under `n_outside_price_sample` and the run
    reports a conclusion on a quietly shorter sample. A short ^VIX tail is worse
    still, because the ffill below turns it into stale-but-present numbers.

    Same principle as the calendar gate: the requested window is the yardstick,
    because it is the one thing a truncated download cannot move.
    """
    if len(frame) == 0:
        raise RuntimeError(f"{ticker}: download returned no rows for {start}..{end}")
    head_short = (frame.index[0] - pd.Timestamp(start)).days
    tail_short = (pd.Timestamp(end) - frame.index[-1]).days
    if head_short > MAX_PRICE_COVERAGE_SHORTFALL_DAYS or tail_short > MAX_PRICE_COVERAGE_SHORTFALL_DAYS:
        raise RuntimeError(
            f"{ticker} does not cover the requested window {start}..{end}: first bar "
            f"{frame.index[0].date()} ({head_short}d in), last bar {frame.index[-1].date()} "
            f"({tail_short}d short of the end). Tolerance is "
            f"{MAX_PRICE_COVERAGE_SHORTFALL_DAYS}d (long holiday weekend). A truncated price "
            "series shortens this fixed historical sample without shortening any count that "
            "gets printed."
        )
    return {
        "ticker": ticker,
        "n_rows": int(len(frame)),
        "observed": f"{frame.index[0].date()}..{frame.index[-1].date()}",
        "head_shortfall_days": int(head_short),
        "tail_shortfall_days": int(tail_short),
        "tolerance_days": MAX_PRICE_COVERAGE_SHORTFALL_DAYS,
    }


price_coverage = {
    "SPY": check_price_coverage(spy, "SPY", SAMPLE_START, SAMPLE_END),
    "^VIX": check_price_coverage(vix, "^VIX", SAMPLE_START, SAMPLE_END),
}

# Calculate returns
spy["Return"] = spy["Close"].pct_change()
spy["AbsReturn"] = spy["Return"].abs()
spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
spy.dropna(subset=["Return"], inplace=True)

# Merge VIX
vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
spy = spy.join(vix_close, how="left")

def check_vix_forward_fill_age(vix_series):
    """Bound how long a forward-filled VIX may be carried, BEFORE filling.

    `ffill()` is silent by construction: a ^VIX series that stops a month early
    leaves the last real quote stamped on every session after it, and the regime
    split and the correlation then run on a constant that looks like data.
    Holidays justify carrying a quote for a session or two; they do not justify
    carrying one for a month.

    A function rather than inline code so it can be attacked by a test. An
    unexercised guard and an absent guard fail the same way.
    """
    missing = vix_series.isna()
    run = max_run = 0
    for m in missing:
        run = run + 1 if m else 0
        max_run = max(max_run, run)
    if max_run > MAX_VIX_FFILL_TRADING_DAYS:
        raise RuntimeError(
            f"^VIX is missing for up to {max_run} consecutive SPY sessions; the limit is "
            f"{MAX_VIX_FFILL_TRADING_DAYS}. Forward-filling across a gap that long would carry "
            "a stale VIX into the regime split and the correlation as if it were an "
            "observation. A run this long is a truncated or partial ^VIX download, not a holiday."
        )
    filled = vix_series.ffill()
    if filled.isna().any():
        raise RuntimeError(
            f"{int(filled.isna().sum())} session(s) still have no VIX after forward fill. The "
            "gap is at the START of the sample, where there is nothing to carry forward."
        )
    return filled, {
        "n_sessions_without_native_vix": int(missing.sum()),
        "max_consecutive_ffill_trading_days": int(max_run),
        "limit_trading_days": MAX_VIX_FFILL_TRADING_DAYS,
    }


spy["VIX"], vix_ffill_audit = check_vix_forward_fill_age(spy["VIX"])
price_coverage["vix_forward_fill"] = vix_ffill_audit

print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data "
      f"({vix_ffill_audit['n_sessions_without_native_vix']} forward-filled, "
      f"longest run {vix_ffill_audit['max_consecutive_ffill_trading_days']}d)")

# ============================================================
# 3. Map NFP dates to trading days
# ============================================================
print("\n[2/6] Mapping NFP dates to trading days...")

nfp_calendar, calendar_completeness = load_nfp_dates()
trading_dates = spy.index

# The proxy forced every event onto a Friday. The official calendar does not,
# and that is load-bearing for the Friday-baseline test below.
n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
"""Official macro-event release dates.

Event studies treat the event date as a constant. It is not — it is data, and it
needs a primary source like any other input. A calendar proxy ("CPI comes out
around the 13th") silently does two things at once: it counts non-event days as
event days, and it dumps real event days into the control group. Nothing throws,
nothing is NaN, the figures still render.

That is not hypothetical. Until 2026-07-12 our CPI event studies hard-coded the
release dates from a 13th-of-month proxy. Against the official calendar 7 of 13
dates were wrong, one of them a day on which BLS published no CPI at all (the
Oct-2025 release was cancelled during the shutdown). Recomputing the CPI-day VIX
reaction on the real dates flipped the mean from +2.18% to -0.85%.

So: get the dates from the release calendar. `ALFRED` (FRED's real-time archive)
publishes the actual news-release dates per statistical release, which is exactly
the ground truth an event study needs.

Usage:
    from volpred.data.event_dates import cpi_release_dates
    dates = cpi_release_dates("2024-01-01", "2026-12-31")   # DatetimeIndex

See docs/error_log.md 2026-07-12 for the incident this module exists to prevent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# FRED release ids for the macro releases we run event studies on.
# https://fred.stlouisfed.org/releases
RELEASE_IDS = {
    "CPI_US": 10,      # Consumer Price Index
    "NFP_US": 50,      # Employment Situation
    "FOMC": 101,       # H.4.1 is not the FOMC; FOMC statements are not a FRED release
}

_CACHE_DIR = Path(__file__).resolve().parents[3] / "storage" / "data" / "event_dates_cache"
_CACHE_TTL = timedelta(days=7)


def _api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    root = Path(__file__).resolve().parents[3]
    for cand in (".env.local", ".env"):
        p = root / cand
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if line.startswith("FRED_API_KEY"):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(
        "FRED_API_KEY not found. Event dates must come from the official release "
        "calendar — do not fall back to a hard-coded list or a calendar proxy."
    )


def _fetch(release_id: int, start: str, end: str) -> list[str]:
    r = requests.get(
        "https://api.stlouisfed.org/fred/release/dates",
        params={
            "release_id": release_id,
            "api_key": _api_key(),
            "file_type": "json",
            "realtime_start": start,
            "realtime_end": end,
            # Without this, ALFRED only returns releases that already carry data, so
            # scheduled-but-not-yet-published dates (the ones an upcoming-event
            # populator actually needs) are missing. Verified 2026-07-12 that it does
            # NOT resurrect cancelled releases: the Oct-2025 CPI, scrapped during the
            # shutdown, stays absent either way.
            "include_release_dates_with_no_data": "true",
            "limit": 1000,
            "sort_order": "asc",
        },
        timeout=30,
    )
    r.raise_for_status()
    return [d["date"] for d in r.json()["release_dates"]]


def release_dates(event: str, start: str, end: str, *, use_cache: bool = True) -> pd.DatetimeIndex:
    """Official news-release dates for `event` within [start, end].

    Monthly releases can carry off-cycle entries (annual seasonal-factor and
    benchmark revisions are filed against the same release id, LATER in the
    month than the regular report). We therefore keep the EARLIEST entry in
    each month — 2026-07-19 k528 Codex review proved the previous `max()` rule
    picked 6 off-cycle dates as NFP events and flipped a significance result.

    Fail-closed on ambiguity: the selected sequence must look like a monthly
    release calendar (consecutive gaps 13–110 days; shutdown catch-ups compress for real,
    e.g. 2013-10-22 -> 2013-11-08 = 17d, and cancelled months stretch,
    e.g. 2025-09-05 -> 2025-11-20 = 76d). Any gap outside that band
    raises instead of returning a plausible-but-wrong calendar —
    silently-wrong event dates are worse than a failed run.
    """
    if event not in RELEASE_IDS:
        raise KeyError(f"unknown event {event!r}; known: {sorted(RELEASE_IDS)}")

    cache = _CACHE_DIR / f"{event}_{start}_{end}.json"
    if use_cache and cache.exists():
        age = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timestamp(cache.stat().st_mtime, unit="s")
        if age < _CACHE_TTL:
            raw = json.loads(cache.read_text())
        else:
            raw = None
    else:
        raw = None

    if raw is None:
        raw = _fetch(RELEASE_IDS[event], start, end)
        if use_cache:
            # use_cache=False must bypass the cache ENTIRELY — the old code
            # skipped only the read and still wrote, which leaked canonical
            # writes out of hermetic tests (CI repo-state guard, 2026-07-19).
            from volpred.canonical_write import guard_canonical_write

            guard_canonical_write(cache)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(raw) + "\n")

    dates = pd.to_datetime(raw)
    if len(dates) == 0:
        raise RuntimeError(f"no {event} release dates returned for {start}..{end}")
    s = pd.Series(dates, index=dates)
    monthly = s.groupby([dates.year, dates.month]).min()
    selected = pd.DatetimeIndex(sorted(monthly.values))
    # Lower bound 13d catches mispicked entries (collapse patterns run <=12d)
    # while passing real shutdown catch-ups (2013-10-22 -> 2013-11-08 = 17d).
    # Upper bound 110d allows cancelled months (76d real) but trips on 3+ gaps.
    gaps = pd.Series(selected).diff().dropna().dt.days
    bad = gaps[(gaps < 13) | (gaps > 110)]
    if len(bad) > 0:
        offenders = [
            f"{selected[i - 1].date()} -> {selected[i].date()} ({int(g)}d)"
            for i, g in zip(bad.index, bad.values)
        ]
        raise RuntimeError(
            f"{event} release calendar failed monthly-cadence validation "
            f"(gaps outside 13-110 days): {offenders}. Off-cycle entries or "
            f"missing months need manual disambiguation — refusing to return "
            f"a plausible-but-wrong calendar."
        )
    return selected


def cpi_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
    return release_dates("CPI_US", start, end, **kw)


def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
    return release_dates("NFP_US", start, end, **kw)
{
  "sample": {
    "total_nfp_events": 253,
    "date_range": "2005-02-04 to 2026-03-06",
    "non_nfp_trading_days": 5086,
    "friday_baseline_days": 834,
    "nfp_days_on_friday": 237,
    "nfp_releases_dated_friday": 243,
    "event_mapping_audit": {
      "n_official_releases": 254,
      "n_mapped_to_sessions": 254,
      "n_shifted_to_next_session": 6,
      "n_outside_price_sample": 0,
      "outside_price_sample_dates": [],
      "n_excluded_for_window_buffer": 1,
      "window_excluded_dates": [
        "2005-01-07"
      ],
      "n_valid_events": 253
    },
    "calendar_completeness": {
      "n_months_in_span": 255,
      "n_raw_entries": 260,
      "months_with_multiple_raw_entries": [
        "2006-05",
        "2012-12",
        "2013-05",
        "2020-05",
        "2024-01",
        "2024-08"
      ],
      "reviewed_multi_entry_months": {
        "2006-05": {
          "raw": [
            "2006-05-05",
            "2006-05-08"
          ],
          "report": "2006-05-05"
        },
        "2012-12": {
          "raw": [
            "2012-12-07",
            "2012-12-12"
          ],
          "report": "2012-12-07"
        },
        "2013-05": {
          "raw": [
            "2013-05-03",
            "2013-05-06"
          ],
          "report": "2013-05-03"
        },
        "2020-05": {
          "raw": [
            "2020-05-08",
            "2020-05-11"
          ],
          "report": "2020-05-08"
        },
        "2024-01": {
          "raw": [
            "2024-01-05",
            "2024-01-10"
          ],
          "report": "2024-01-05"
        },
        "2024-08": {
          "raw": [
            "2024-08-02",
            "2024-08-21"
          ],
          "report": "2024-08-02"
        }
      },
      "ambiguity_gap_threshold_days": 3,
      "known_missing_months": {
        "2025-10": "Federal government shutdown. ALFRED shows no release id 50 entry between 2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed September report landed on 11-20. Same shutdown that cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py. The first-Friday proxy INVENTED an event here -- that phantom is one of the reasons for this rerun."
      },
      "window_coverage": {
        "requested": "2005-01-01..2026-03-27",
        "observed": "2005-01-07..2026-03-06",
        "head_shortfall_days": 6,
        "tail_shortfall_days": 21,
        "tolerance_days": 70
      },
      "endpoint_expectation": {
        "derived_from": "requested window only -- never from the feed",
        "latest_observed_release_day_of_month": 22,
        "n_required_months": 255,
        "required_first_month": "2005-01",
        "required_last_month": "2026-03",
        "excused_by_known_missing": [
          "2025-10"
        ],
        "why": "Codex round-5 B2: deleting an endpoint month from the raw feed and the selection together left every feed-relative check self-consistent (259 raw / 253 selected, shortfall inside the 70d tolerance) and the sample silently shortened. The requested window is the one fact a truncated feed cannot edit."
      },
      "residual_limitation": "Two heuristics remain. (1) Same-month selection uses 'earliest wins', which cannot distinguish an off-cycle item filed BEFORE the report from the report itself, so every multi-entry month must additionally appear in REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A new multi-entry month fails the run rather than being assumed. (2) The endpoint expectation can still be silenced by adding a required month to KNOWN_MISSING_MONTHS. That is deliberate -- 2025-10 really was cancelled -- and it is bounded by check 4, which verifies against the RAW feed that a claimed hole is a real hole. What remains uncovered is a month deleted from the raw feed AND declared missing in writing: a documented false claim, not a silent truncation. This gate is fail-closed against the latter, not the former."
    },
    "price_coverage": {
      "SPY": {
        "ticker": "SPY",
        "n_rows": 5341,
        "observed": "2005-01-03..2026-03-26",
        "head_shortfall_days": 2,
        "tail_shortfall_days": 1,
        "tolerance_days": 10
      },
      "^VIX": {
        "ticker": "^VIX",
        "n_rows": 5341,
        "observed": "2005-01-03..2026-03-26",
        "head_shortfall_days": 2,
        "tail_shortfall_days": 1,
        "tolerance_days": 10
      },
      "vix_forward_fill": {
        "n_sessions_without_native_vix": 0,
        "max_consecutive_ffill_trading_days": 0,
        "limit_trading_days": 3
      }
    },
    "friday_estimand": {
      "filter": "session weekday == Friday",
      "estimand": "Among trading sessions falling on a Friday, do the sessions that absorb an NFP release show larger |return| than those that do not? This is a claim about the session that trades the news, NOT about releases dated a Friday.",
      "n_events_total": 253,
      "n_release_date_on_friday": 243,
      "n_traded_in_friday_session": 237,
      "friday_releases_absorbed_by_a_later_session": {
        "n": 6,
        "dates": [
          {
            "release_date": "2007-04-06",
            "session_date": "2007-04-09",
            "session_weekday": 0,
            "event_abs_return": 0.0013864117187798453
          },
          {
            "release_date": "2010-04-02",
            "session_date": "2010-04-05",
            "session_weekday": 0,
            "event_abs_return": 0.008149637494278661
          },
          {
            "release_date": "2012-04-06",
            "session_date": "2012-04-09",
            "session_weekday": 0,
            "event_abs_return": 0.01123175066081461
          },
          {
            "release_date": "2015-04-03",
            "session_date": "2015-04-06",
            "session_weekday": 0,
            "event_abs_return": 0.0067330498943227735
          },
          {
            "release_date": "2021-04-02",
            "session_date": "2021-04-05",
            "session_weekday": 0,
            "event_abs_return": 0.01435326530305181
          },
          {
            "release_date": "2023-04-07",
            "session_date": "2023-04-10",
            "session_weekday": 0,
            "event_abs_return": 0.0010262812061787585
          }
        ],
        "mean_abs_return": 0.007146732712904409,
        "why_excluded": "Every one is a Good Friday: BLS published, the market was shut, the news is absorbed by the following Monday. Their returns are Monday returns and cannot enter a comparison whose control group is pure Friday without reintroducing the weekday confound the restriction exists to remove."
      },
      "why_session_and_not_release_weekday": "The measured quantity is a session return and the confound held fixed is the day-of-week effect of that session. Filtering on release weekday would place these Monday returns against a Friday-only control group.",
      "what_this_does_not_identify": "Not 'NFP in general' (the sample is conditioned on Friday sessions) and not 'releases dated a Friday' (six such releases are traded on a Monday and excluded)."
    },
    "total_trading_days": 5340,
    "control_group_excludes_all_nfp_sessions": true
  },
  "event_date_source": {
    "source": "official BLS release calendar via ALFRED (FRED release id 50)",
    "accessor": "volpred.data.event_dates.nfp_release_dates",
    "fallback": "none - the run raises if the calendar is unreachable",
    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
  },
  "main_results": {
    "nfp_avg_abs_return": 0.008453064404674977,
    "nfp_avg_abs_return_pct": "0.845%",
    "non_nfp_avg_abs_return": 0.007630637836355491,
    "non_nfp_avg_abs_return_pct": "0.763%",
    "friday_baseline_abs_return": 0.007183325954343319,
    "vol_ratio_vs_all": 1.107779531142352,
    "vol_ratio_vs_friday": 1.188994637894018
  },
  "regime_analysis": {
    "vix_median_split": 16.690000534057617,
    "high_vix_nfp_abs_return": 0.011276193504303303,
    "low_vix_nfp_abs_return": 0.005562180206655571,
    "n_high": 128,
    "n_low": 125,
    "t_stat": 6.169072114785661,
    "p_value": 4.551849137823982E-9,
    "multiplicity": {
      "family": "confirmatory",
      "p_nominal": 4.551849137823982E-9,
      "p_holm_all_outputs_family": 9.558883189430362E-8,
      "p_holm_confirmatory_family": 2.275924568911991E-8,
      "how_to_report": "Nominal, then Holm within the declared confirmatory family."
    }
  },
  "statistical_tests": {
    "A_nfp_vs_all": {
      "test": "Welch t-test",
      "t_stat": 1.5938775781634782,
      "p_value": 0.11206360938619585,
      "significant_5pct": false,
      "multiplicity": {
        "family": "confirmatory",
        "p_nominal": 0.11206360938619585,
        "p_holm_all_outputs_family": 1.0,
        "p_holm_confirmatory_family": 0.11206360938619585,
        "how_to_report": "Nominal, then Holm within the declared confirmatory family."
      }
    },
    "B_nfp_vs_friday": {
      "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
      "estimand": "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event group is restricted to NFP releases that trade on a Friday, and the 16 non-Friday events are excluded rather than compared against a pure-Friday control group.",
      "claim_scope": "This identifies the effect of an NFP release ABSORBED BY A FRIDAY SESSION. It does not license a statement about NFP releases in general -- the excluded events are quieter, so the restriction raises the ratio relative to the mixed-weekday spec -- and it is NOT a statement about releases DATED a Friday, six of which are Good Fridays traded the following Monday and therefore excluded. Any prose quoting this number must say 'NFP traded in a Friday session', not 'NFP' and not 'NFP released on a Friday'.",
      "restriction_is_not_neutral": {
        "excluded_mean_abs_return": 0.007151465777403401,
        "friday_mean_abs_return": 0.008540936041959135,
        "excluded_are_quieter_by_pct": 16.268360490345206
      },
      "n_event": 237,
      "n_control": 834,
      "vol_ratio": 1.188994637894018,
      "t_stat": 2.320508726692989,
      "p_value": 0.020854283650821093,
      "significant_5pct": true,
      "excluded_non_friday_events": {
        "n": 16,
        "mean_abs_return": 0.007151465777403401
      },
      "multiplicity": {
        "family": "confirmatory",
        "p_nominal": 0.020854283650821093,
        "p_holm_all_outputs_family": 0.37537710571477967,
        "p_holm_confirmatory_family": 0.041708567301642185,
        "how_to_report": "Nominal, then Holm within the declared confirmatory family."
      }
    },
    "B_diagnostic_mixed_weekday": {
      "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
      "status": "DIAGNOSTIC ONLY - do not quote",
      "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
      "vol_ratio": 1.176761914801308,
      "t_stat": 2.2390202914235586,
      "p_value": 0.025692059659997518,
      "significant_5pct": true
    },
    "C_wilcoxon": {
      "test": "Mann-Whitney U (one-sided)",
      "u_stat": 712488.0,
      "p_value": 0.0019382600522027216,
      "significant_5pct": true,
      "multiplicity": {
        "family": "confirmatory",
        "p_nominal": 0.0019382600522027216,
        "p_holm_all_outputs_family": 0.03682694099185171,
        "p_holm_confirmatory_family": 0.005814780156608164,
        "how_to_report": "Nominal, then Holm within the declared confirmatory family."
      }
    },
    "D_vol_crush": {
      "test": "One-sample t-test (post-pre diff)",
      "pre_avg": 0.0077870216597641945,
      "post_avg": 0.007687356861391357,
      "diff": -0.00009966479837283827,
      "t_stat": -0.3106840360357029,
      "p_value": 0.7562976513767368,
      "vol_crush_present": false,
      "multiplicity": {
        "family": "exploratory",
        "p_nominal": 0.7562976513767368,
        "p_holm_all_outputs_family": 1.0,
        "p_holm_confirmatory_family": null,
        "how_to_report": "EXPLORATORY -- nominal p reported for description only; not quotable as a 5% finding."
      }
    },
    "E_vix_predictive": {
      "test": "Pearson + Spearman correlation",
      "pearson_r": 0.44043638429674903,
      "pearson_p": 1.9817089060479586E-13,
      "spearman_rho": 0.3455048873701663,
      "spearman_p": 1.6699985504624933E-8,
      "slope": 0.0004256184186836176,
      "interpretation": "1pt VIX → 0.0426% more |return|",
      "multiplicity": {
        "family": "confirmatory",
        "pearson": {
          "p_nominal": 1.9817089060479586E-13,
          "p_holm_confirmatory_family": 1.1890253436287752E-12,
          "p_holm_all_outputs_family": 4.359759593305509E-12
        },
        "spearman": {
          "p_nominal": 1.6699985504624933E-8,
          "p_holm_confirmatory_family": 6.679994201849973E-8,
          "p_holm_all_outputs_family": 3.3399971009249865E-7
        }
      }
    },
    "F_vix_buildup": {
      "test": "One-sample t-test (T-5 to T-1 VIX change)",
      "mean_change": 0.08312253989721004,
      "t_stat": 0.44978438962865197,
      "p_value": 0.653252559944604,
      "anticipatory_buildup": false,
      "multiplicity": {
        "family": "exploratory",
        "p_nominal": 0.653252559944604,
        "p_holm_all_outputs_family": 1.0,
        "p_holm_confirmatory_family": null,
        "how_to_report": "EXPLORATORY -- nominal p reported for description only; not quotable as a 5% finding."
      }
    }
  },
  "multiplicity": {
    "method": "Holm step-down (FWER, valid under arbitrary dependence)",
    "why_not_romano_wolf": "The family mixes Welch t, Mann-Whitney U and two correlation statistics on overlapping samples; no single resampling scheme is jointly valid for all four, and manufacturing one to buy power is the wrong trade in a correction about overstatement.",
    "pre_registered": false,
    "pre_registration_note": "Not pre-registered. The confirmatory endpoints predate the date correction and this rerun, but were not lodged before the data were seen. Both families are therefore reported and the narrow one is not presented as the only defensible reading.",
    "confirmatory_family": {
      "n": 6,
      "members": [
        {
          "test": "A_nfp_vs_all_welch",
          "p_nominal": 0.11206360938619585,
          "p_holm": 0.11206360938619585,
          "survives_5pct": false
        },
        {
          "test": "B_nfp_vs_friday_welch",
          "p_nominal": 0.020854283650821093,
          "p_holm": 0.041708567301642185,
          "survives_5pct": true
        },
        {
          "test": "C_mannwhitney_one_sided",
          "p_nominal": 0.0019382600522027216,
          "p_holm": 0.005814780156608164,
          "survives_5pct": true
        },
        {
          "test": "E_vix_pearson",
          "p_nominal": 1.9817089060479586E-13,
          "p_holm": 1.1890253436287752E-12,
          "survives_5pct": true
        },
        {
          "test": "E_vix_spearman",
          "p_nominal": 1.6699985504624933E-8,
          "p_holm": 6.679994201849973E-8,
          "survives_5pct": true
        },
        {
          "test": "H_vix_regime_welch",
          "p_nominal": 4.551849137823982E-9,
          "p_holm": 2.275924568911991E-8,
          "survives_5pct": true
        }
      ]
    },
    "all_outputs_family": {
      "n": 22,
      "members": [
        {
          "test": "A_nfp_vs_all_welch",
          "p_nominal": 0.11206360938619585,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "B_nfp_vs_friday_welch",
          "p_nominal": 0.020854283650821093,
          "p_holm": 0.37537710571477967,
          "survives_5pct": false
        },
        {
          "test": "C_mannwhitney_one_sided",
          "p_nominal": 0.0019382600522027216,
          "p_holm": 0.03682694099185171,
          "survives_5pct": true
        },
        {
          "test": "E_vix_pearson",
          "p_nominal": 1.9817089060479586E-13,
          "p_holm": 4.359759593305509E-12,
          "survives_5pct": true
        },
        {
          "test": "E_vix_spearman",
          "p_nominal": 1.6699985504624933E-8,
          "p_holm": 3.3399971009249865E-7,
          "survives_5pct": true
        },
        {
          "test": "H_vix_regime_welch",
          "p_nominal": 4.551849137823982E-9,
          "p_holm": 9.558883189430362E-8,
          "survives_5pct": true
        },
        {
          "test": "D_vol_crush",
          "p_nominal": 0.7562976513767368,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "F_vix_buildup",
          "p_nominal": 0.653252559944604,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "I_time_trend",
          "p_nominal": 0.6319845325106566,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "J_direction_binomial",
          "p_nominal": 0.0234272671035406,
          "p_holm": 0.3982635407601902,
          "survives_5pct": false
        },
        {
          "test": "G_month_1",
          "p_nominal": 0.3579354831240437,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_2",
          "p_nominal": 0.38519836697344384,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_3",
          "p_nominal": 0.49000996873064656,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_4",
          "p_nominal": 0.3873694241020666,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_5",
          "p_nominal": 0.10407351632556729,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_6",
          "p_nominal": 0.11758670035254098,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_7",
          "p_nominal": 0.7442154227850646,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_8",
          "p_nominal": 0.7642733155379181,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_9",
          "p_nominal": 0.761142647848102,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_10",
          "p_nominal": 0.7331920499556679,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_11",
          "p_nominal": 0.5671205974593735,
          "p_holm": 1.0,
          "survives_5pct": false
        },
        {
          "test": "G_month_12",
          "p_nominal": 0.6804136616573103,
          "p_holm": 1.0,
          "survives_5pct": false
        }
      ]
    },
    "headline_friday_test": {
      "p_nominal": 0.020854283650821093,
      "p_holm_confirmatory_family": 0.041708567301642185,
      "p_holm_all_outputs_family": 0.37537710571477967,
      "verdict": "Survives Holm within the six-test confirmatory family; does NOT survive Holm against all 22 inferential outputs. Report as nominally significant, Holm-robust only within the declared confirmatory family."
    },
    "exploratory_note": "Everything outside the confirmatory family -- the 12 monthly cells, vol crush, VIX buildup, time trend and direction binomial -- is EXPLORATORY. Nominal p-values are reported for description; none may be quoted as a 5% finding."
  },
  "conclusions": [
    "Welch mean-difference, NFP vs all non-NFP days: 1.11x, p=0.1121 (does not reject at 5%)",
    "Welch mean-difference, NFP traded in a Friday session vs Friday non-NFP (CONDITIONAL ON THE FRIDAY SESSION, weekday held fixed): 1.19x, nominal p=0.0209 (rejects at 5% BEFORE any multiplicity correction -- the family-adjusted values live in `multiplicity` and must be quoted alongside this one; n=237 vs 834). Scoped to the releases ABSORBED BY a Friday session, not to releases DATED a Friday: 243 are dated a Friday but only 237 trade in one, the 6 Good Friday releases in between being absorbed by the following Monday. The 16 excluded events are quieter, so this is not a statement about NFP releases in general.",
    "Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: p=0.00194 (rejects at 5%)",
    "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, so a rank test can detect a location shift the Welch mean test cannot. Report both; do not summarise them as a single verdict.",
    "No significant vol crush pattern (p=0.7563)",
    "Pre-event VIX is associated with event vol (r=0.440, p=0.0000; in-sample association, not a forecast)"
  ],
  "claim_scope_note": "Every significance statement in this artifact is scoped to its own test. The superseded run summarised these as 'insignificant across all tests', which contradicted the one-sided Mann-Whitney result in the same file (k528 Codex v2 finding 6). Every `significant_5pct` flag here is NOMINAL: see the top-level `multiplicity` block and the per-test `multiplicity` stamp for the family each was judged in and its Holm-adjusted value. The Friday result is Holm-robust within the six-test confirmatory family and is NOT Holm-robust against all 22 inferential outputs; neither the confirmatory family nor this study as a whole was pre-registered."
}
{
  "event_date_source": {
    "source": "official BLS release calendar via ALFRED (FRED release id 50)",
    "accessor": "volpred.data.event_dates.nfp_release_dates",
    "fallback": "none - the run raises if the calendar is unreachable",
    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
  },
  "calendar_diff": {
    "proxy_only_dates": [
      "2005-07-01",
      "2006-03-03",
      "2006-12-01",
      "2007-03-02",
      "2008-07-07",
      "2009-01-02",
      "2009-05-01",
      "2009-07-06",
      "2010-01-04",
      "2010-10-01",
      "2011-07-01",
      "2012-03-02",
      "2013-03-01",
      "2013-10-04",
      "2013-11-01",
      "2014-01-03",
      "2014-07-07",
      "2015-01-02",
      "2015-05-01",
      "2015-07-06",
      "2016-01-04",
      "2016-07-01",
      "2017-03-03",
      "2017-12-01",
      "2018-03-02",
      "2019-03-01",
      "2020-01-03",
      "2020-05-01",
      "2020-07-06",
      "2021-01-04",
      "2021-10-01",
      "2022-07-01",
      "2023-03-03",
      "2023-12-01",
      "2024-03-01",
      "2025-01-03",
      "2025-07-07",
      "2025-10-03",
      "2025-11-07",
      "2025-12-05",
      "2026-01-02",
      "2026-02-06"
    ],
    "official_only_dates": [
      "2005-07-08",
      "2006-03-10",
      "2006-12-08",
      "2007-03-09",
      "2008-07-03",
      "2009-01-09",
      "2009-05-08",
      "2009-07-02",
      "2010-01-08",
      "2010-10-08",
      "2011-07-08",
      "2012-03-09",
      "2013-03-08",
      "2013-10-22",
      "2013-11-08",
      "2014-01-10",
      "2014-07-03",
      "2015-01-09",
      "2015-05-08",
      "2015-07-02",
      "2016-01-08",
      "2016-07-08",
      "2017-03-10",
      "2017-12-08",
      "2018-03-09",
      "2019-03-08",
      "2020-01-10",
      "2020-05-08",
      "2020-07-02",
      "2021-01-08",
      "2021-10-08",
      "2022-07-08",
      "2023-03-10",
      "2023-12-08",
      "2024-03-08",
      "2025-01-10",
      "2025-07-03",
      "2025-11-20",
      "2025-12-16",
      "2026-01-09",
      "2026-02-11"
    ],
    "dates_in_common": 212,
    "n_proxy": 254,
    "n_official": 253,
    "nfp_days_on_friday_official": 237
  },
  "n_claims_audited": 6,
  "n_claims_flipped": 0,
  "article_correction": {
    "article_id": "mile_35eef830",
    "status": "pending - filled in by the correction step",
    "replacements": null
  },
  "items": {
    "vol_ratio_vs_all": {
      "label": "NFP vs all non-NFP days (article: 1.10x)",
      "before": {
        "mean_ratio": 1.1033586198711247,
        "nfp_mean": 0.008420922409653335,
        "baseline_mean": 0.007632081045994748,
        "p_value": 0.1289636505345802,
        "significant_5pct": false,
        "n": 254,
        "n_control": 5085,
        "median_ratio": 1.1882969817027025,
        "win_rate": 0.5551181102362205,
        "as_published": {
          "mean_ratio": 1.1035360772013734,
          "baseline_mean": 0.0076308537469923455,
          "p_value": 0.1283682008960355,
          "significant_5pct": false,
          "n_control": 5086,
          "note": "what the proxy run published. Its control group still contained the proxy's own window-dropped NFP session, so it is kept for the record but is not the like-for-like comparison."
        }
      },
      "after": {
        "mean_ratio": 1.107779531142352,
        "nfp_mean": 0.008453064404674977,
        "baseline_mean": 0.007630637836355491,
        "p_value": 0.11206360938619585,
        "significant_5pct": false,
        "n": 253,
        "median_ratio": 1.1915894654774213,
        "win_rate": 0.5612648221343873
      },
      "note": "proxy-side median_ratio / win_rate are reconstructed from the archived per-event data, not from the proxy run's own output (it only reported means).",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "vol_ratio_vs_friday": {
      "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
      "before": {
        "mean_ratio": 1.166705572077902,
        "p_value": 0.042139992029859054,
        "significant_5pct": true,
        "n": 239,
        "nfp_days_on_friday": 239,
        "median_ratio": 1.1979005289191478,
        "win_rate": 0.5564853556485355,
        "n_control_friday": 832,
        "control_derivation": {
          "n_fridays_in_sample": 1072,
          "n_friday_proxy_events": 239,
          "reconstructed_sessions_excluded": [
            "2005-01-07"
          ],
          "n_reconstructed_friday_sessions": 1,
          "excluded_session_is_absent_from_controls": true
        },
        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
        "as_published_mixed_weekday": {
          "mean_ratio": 1.168212716801256,
          "p_value": 0.03354366521379227,
          "significant_5pct": true,
          "n": 254,
          "note": "what the proxy run actually published: all 254 events (239 Friday, 15 Monday) against non-NFP Fridays. This is the number the article quoted, so it is kept, but it is NOT the like-for-like comparison against the corrected column."
        }
      },
      "after": {
        "mean_ratio": 1.188994637894018,
        "p_value": 0.020854283650821093,
        "significant_5pct": true,
        "n": 237,
        "nfp_days_on_friday": 237,
        "median_ratio": 1.218410782735008,
        "win_rate": 0.569620253164557,
        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
        "diagnostic_mixed_weekday": {
          "mean_ratio": 1.176761914801308,
          "p_value": 0.025692059659997518,
          "significant_5pct": true,
          "n": 253,
          "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
        }
      },
      "note": "Two things changed here and they are separated rather than conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: the event group is a weekday mixture while the control group is pure Friday, so the test now restricts the event group to the releases that are absorbed by a Friday SESSION (237 of the 243 releases dated a Friday; the other six are Good Fridays traded the following Monday). Defect (2) was NOT created by (1) -- the proxy run was already mixed (239/254 Friday, the other 15 being holiday-shifted Mondays), it was simply never noticed. Both columns above therefore use the SAME restricted estimand so the delta is attributable to the dates alone; `as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` (after) hold the old estimand on each side for reference.",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "regime_ratio": {
      "label": "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
      "before": {
        "mean_ratio": 2.1670599373202153,
        "high_mean": 0.011524027931522324,
        "low_mean": 0.005317816887784345,
        "n_high": 127,
        "n_low": 127,
        "p_value": 2.8361186837189765E-10,
        "significant_5pct": true,
        "median_ratio": 2.2653573776192792,
        "win_rate": 0.7165354330708661
      },
      "after": {
        "mean_ratio": 2.0272974059363413,
        "high_mean": 0.011276193504303303,
        "low_mean": 0.005562180206655571,
        "n_high": 128,
        "n_low": 125,
        "p_value": 4.551849137823982E-9,
        "significant_5pct": true,
        "median_ratio": 2.073377788061646,
        "win_rate": 0.6953125
      },
      "note": "",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "vix_correlation": {
      "label": "Pre-event VIX vs event-day |return| (article: r=0.45)",
      "before": {
        "pearson_r": 0.45116558631194703,
        "pearson_p": 3.854493703611817E-14,
        "spearman_rho": 0.3766062270606868,
        "spearman_p": 5.561878132730772E-10,
        "slope_pct_per_vix_pt": 0.04387491083793095,
        "n": 254,
        "significant_5pct": true
      },
      "after": {
        "pearson_r": 0.44043638429674903,
        "pearson_p": 1.9817089060479586E-13,
        "spearman_rho": 0.3455048873701663,
        "spearman_p": 1.6699985504624933E-8,
        "slope_pct_per_vix_pt": 0.04256184186836176,
        "n": 253,
        "significant_5pct": true
      },
      "note": "",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "vix_median_threshold": {
      "label": "VIX median split (article: 16.71)",
      "before": {
        "threshold": 16.710000038146973,
        "n": 254,
        "places_20260701_vix_1659_in": "low"
      },
      "after": {
        "threshold": 16.690000534057617,
        "n": 253,
        "places_20260701_vix_1659_in": "low"
      },
      "note": "",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "sample": {
      "label": "NFP event sample (article: 254 events)",
      "before": {
        "n": 254,
        "date_range": "2005-02-04 to 2026-03-06",
        "non_nfp_trading_days": 5086
      },
      "after": {
        "n": 253,
        "date_range": "2005-02-04 to 2026-03-06",
        "non_nfp_trading_days": 5086,
        "dates_in_common": 212,
        "proxy_only_dates": [
          "2005-07-01",
          "2006-03-03",
          "2006-12-01",
          "2007-03-02",
          "2008-07-07",
          "2009-01-02",
          "2009-05-01",
          "2009-07-06",
          "2010-01-04",
          "2010-10-01",
          "2011-07-01",
          "2012-03-02",
          "2013-03-01",
          "2013-10-04",
          "2013-11-01",
          "2014-01-03",
          "2014-07-07",
          "2015-01-02",
          "2015-05-01",
          "2015-07-06",
          "2016-01-04",
          "2016-07-01",
          "2017-03-03",
          "2017-12-01",
          "2018-03-02",
          "2019-03-01",
          "2020-01-03",
          "2020-05-01",
          "2020-07-06",
          "2021-01-04",
          "2021-10-01",
          "2022-07-01",
          "2023-03-03",
          "2023-12-01",
          "2024-03-01",
          "2025-01-03",
          "2025-07-07",
          "2025-10-03",
          "2025-11-07",
          "2025-12-05",
          "2026-01-02",
          "2026-02-06"
        ],
        "official_only_dates": [
          "2005-07-08",
          "2006-03-10",
          "2006-12-08",
          "2007-03-09",
          "2008-07-03",
          "2009-01-09",
          "2009-05-08",
          "2009-07-02",
          "2010-01-08",
          "2010-10-08",
          "2011-07-08",
          "2012-03-09",
          "2013-03-08",
          "2013-10-22",
          "2013-11-08",
          "2014-01-10",
          "2014-07-03",
          "2015-01-09",
          "2015-05-08",
          "2015-07-02",
          "2016-01-08",
          "2016-07-08",
          "2017-03-10",
          "2017-12-08",
          "2018-03-09",
          "2019-03-08",
          "2020-01-10",
          "2020-05-08",
          "2020-07-02",
          "2021-01-08",
          "2021-10-08",
          "2022-07-08",
          "2023-03-10",
          "2023-12-08",
          "2024-03-08",
          "2025-01-10",
          "2025-07-03",
          "2025-11-20",
          "2025-12-16",
          "2026-01-09",
          "2026-02-11"
        ]
      },
      "note": "Equal counts do not mean equal samples -- check dates_in_common.",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    }
  }
}

2026-07-27T00:30:00.469281Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
codex
初步數字與敘述互相一致；接下來我正集中驗證最可能造成認證失敗的結構點：calendar 六道 gate 是否真的彼此獨立、端點是否由 request 推導，以及 round-7 測試是否測語義結構而非換一組字串。
exec
/bin/zsh -lc "nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '180,470p'
nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '469,590p'
nl -ba src/volpred/data/event_dates.py | sed -n '1,164p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
   180	            os.unlink(tmp)
   181	        except FileNotFoundError:
   182	            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
   183	        raise
   184	
   185	
   186	# ============================================================
   187	# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
   188	# ============================================================
   189	def check_calendar_is_complete(selected, raw, start, end):
   190	    """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.
   191	
   192	    "Did the call succeed?" is the wrong question. A monthly release calendar
   193	    that silently lost 2019 still returns a non-empty list, still produces
   194	    event windows, still renders.
   195	
   196	    This validates the RAW feed as well as the accessor's per-month selection.
   197	    Validating only the selection cannot work: the accessor collapses each month
   198	    to one date before this function ever sees it, so a same-month ambiguity is
   199	    already resolved -- silently, and possibly wrongly -- by the time a check on
   200	    the output could look for it. That is precisely how the k528 v2 BLOCKER got
   201	    through (Codex v3 finding 3).
   202	
   203	    Four ways the input can be wrong without being empty, all of which raise:
   204	      1. a month has two entries too close together to tell report from revision
   205	      2. the selection is not the earliest entry of its month
   206	      3. a month is missing from the observed span
   207	      4. a month is claimed as a known hole but the raw feed actually has data
   208	    """
   209	    sel = [pd.Timestamp(d) for d in selected]
   210	    sel_months = [d.strftime("%Y-%m") for d in sel]
   211	
   212	    raw_by_month: dict[str, list[pd.Timestamp]] = {}
   213	    for d in raw:
   214	        ts = pd.Timestamp(d)
   215	        raw_by_month.setdefault(ts.strftime("%Y-%m"), []).append(ts)
   216	    for v in raw_by_month.values():
   217	        v.sort()
   218	
   219	    # 0: the selection itself must be well-formed before anything is inferred
   220	    # from it. Building a month->date dict first would silently keep only the
   221	    # last of a duplicated month and hide exactly what we are looking for.
   222	    sel_month_counts: dict[str, int] = {}
   223	    for m in sel_months:
   224	        sel_month_counts[m] = sel_month_counts.get(m, 0) + 1
   225	    sel_dupes = sorted(m for m, c in sel_month_counts.items() if c > 1)
   226	    if sel_dupes:
   227	        raise RuntimeError(
   228	            f"selected calendar has more than one entry for {sel_dupes}. The Employment "
   229	            "Situation is monthly; a duplicated month means the accessor stopped collapsing."
   230	        )
   231	    invented = sorted(set(sel_months) - set(raw_by_month))
   232	    if invented:
   233	        raise RuntimeError(
   234	            f"selected calendar contains month(s) absent from the raw feed: {invented}. "
   235	            "The selection must be a subset of what the source actually published."
   236	        )
   237	    off_feed = sorted(str(d.date()) for d in sel if d not in raw_by_month.get(d.strftime("%Y-%m"), []))
   238	    if off_feed:
   239	        raise RuntimeError(
   240	            f"selected dates that do not appear in the raw feed at all: {off_feed}."
   241	        )
   242	
   243	    # 1: the accessor's per-month choice must be the earliest entry, and any
   244	    # same-month pair must be far enough apart to tell report from revision.
   245	    ambiguous, mis_selected = [], []
   246	    sel_by_month = dict(zip(sel_months, sel))
   247	    for month, entries in raw_by_month.items():
   248	        if len(entries) > 1:
   249	            gap = (entries[1] - entries[0]).days
   250	            if gap < AMBIGUOUS_SAME_MONTH_GAP_DAYS:
   251	                ambiguous.append(
   252	                    f"{month}: {entries[0].date()} vs {entries[1].date()} ({gap}d apart)"
   253	                )
   254	        if month in sel_by_month and sel_by_month[month] != entries[0]:
   255	            mis_selected.append(
   256	                f"{month}: selected {sel_by_month[month].date()}, earliest is {entries[0].date()}"
   257	            )
   258	    if ambiguous:
   259	        raise RuntimeError(
   260	            f"{len(ambiguous)} month(s) carry two release entries too close together to "
   261	            f"identify the Employment Situation report by date order: {ambiguous}. "
   262	            "Refusing to guess which one is the monthly report."
   263	        )
   264	    if mis_selected:
   265	        raise RuntimeError(
   266	            f"accessor did not select the earliest entry in {len(mis_selected)} month(s): "
   267	            f"{mis_selected}. The later same-month entry is an off-cycle revision, not the "
   268	            "monthly report -- selecting it is the k528 v2 BLOCKER."
   269	        )
   270	
   271	    # "Earliest wins" is a heuristic and cannot survive an off-cycle item filed
   272	    # BEFORE the report. Every multi-entry month therefore has to be one a human
   273	    # checked against the BLS archive, and the checked answer has to match.
   274	    multi = {m: v for m, v in raw_by_month.items() if len(v) > 1}
   275	    unreviewed = sorted(set(multi) - set(REVIEWED_MULTI_ENTRY_MONTHS))
   276	    if unreviewed:
   277	        raise RuntimeError(
   278	            f"{len(unreviewed)} month(s) carry multiple release entries but have never been "
   279	            f"checked against the BLS archive: "
   280	            f"{ {m: [str(d.date()) for d in multi[m]] for m in unreviewed} }. "
   281	            "Selecting the earliest is only a heuristic; verify which entry is the Employment "
   282	            "Situation report at bls.gov/news.release/archives/ and add it to "
   283	            "REVIEWED_MULTI_ENTRY_MONTHS."
   284	        )
   285	    # Approve the SHAPE, not the month. A reviewed month whose feed later gains
   286	    # or loses an entry is a shape nobody reviewed, so it goes back for review.
   287	    reshaped = {
   288	        m: {"now": [str(d.date()) for d in multi[m]], "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]}
   289	        for m in multi
   290	        if [str(d.date()) for d in multi[m]] != REVIEWED_MULTI_ENTRY_MONTHS[m]["raw"]
   291	    }
   292	    if reshaped:
   293	        raise RuntimeError(
   294	            f"the raw feed for reviewed month(s) no longer matches what was reviewed: {reshaped}. "
   295	            "The approval covers the entry set someone actually checked, not the month name. "
   296	            "Re-verify against bls.gov/news.release/archives/ before proceeding."
   297	        )
   298	    contradicted = {
   299	        m: {"selected": str(sel_by_month[m].date()),
   300	            "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]}
   301	        for m in multi
   302	        if m in sel_by_month and str(sel_by_month[m].date()) != REVIEWED_MULTI_ENTRY_MONTHS[m]["report"]
   303	    }
   304	    if contradicted:
   305	        raise RuntimeError(
   306	            f"selection contradicts the human-verified release date in {contradicted}. "
   307	            "Either the feed changed or the accessor regressed; do not proceed on the guess."
   308	        )
   309	
   310	    # Every month the source published must survive into the selection. Without
   311	    # this, a month can vanish between raw and selected (stale accessor cache vs
   312	    # a live raw fetch is exactly that shape) and neither the gap check nor the
   313	    # window-coverage check sees it -- the observed span just ends one month
   314	    # earlier and still looks continuous.
   315	    # UNCONDITIONAL: no KNOWN_MISSING_MONTHS subtraction here. If the raw feed has
   316	    # entries for a month, that month is not missing -- whatever a list says. The
   317	    # earlier version subtracted the allowlist, which let a tail month be dropped
   318	    # from the selection and then excused by declaring it "known missing", while
   319	    # the counter-check that would have caught the lie only looked inside the
   320	    # selected span (Codex v3 round-4 BLOCKER).
   321	    dropped = sorted(set(raw_by_month) - set(sel_months))
   322	    if dropped:
   323	        raise RuntimeError(
   324	            f"the raw feed has {len(dropped)} month(s) that the selected calendar does not: "
   325	            f"{dropped}. A month present at the source and absent from the analysis is a "
   326	            "silently shortened sample. This is not excusable via KNOWN_MISSING_MONTHS: "
   327	            "that list is for months the source never published."
   328	        )
   329	
   330	    # The two allowlists must not overlap. "This month published nothing" and
   331	    # "this month published several entries I reviewed" cannot both be true, and
   332	    # allowing both is what turned two independently-reasonable lists into a
   333	    # bypass when combined.
   334	    both = sorted(set(KNOWN_MISSING_MONTHS) & set(REVIEWED_MULTI_ENTRY_MONTHS))
   335	    if both:
   336	        raise RuntimeError(
   337	            f"month(s) {both} appear in both KNOWN_MISSING_MONTHS and "
   338	            "REVIEWED_MULTI_ENTRY_MONTHS. A month cannot both have published nothing and "
   339	            "have a reviewed multi-entry shape."
   340	        )
   341	
   342	    # 3a: the observed span must actually cover what was asked for. Checking only
   343	    # for gaps INSIDE the observed span cannot catch truncation -- if the feed
   344	    # stops early, the span shrinks with it and nothing looks missing. Found by
   345	    # self-audit while Codex v3 round-2 was running.
   346	    want_start, want_end = pd.Timestamp(start), pd.Timestamp(end)
   347	    head_short = (min(sel) - want_start).days
   348	    tail_short = (want_end - max(sel)).days
   349	    if head_short > MAX_WINDOW_SHORTFALL_DAYS or tail_short > MAX_WINDOW_SHORTFALL_DAYS:
   350	        raise RuntimeError(
   351	            f"official NFP calendar does not cover the requested window "
   352	            f"{start}..{end}: first release {min(sel).date()} ({head_short}d in), "
   353	            f"last release {max(sel).date()} ({tail_short}d short of the end). "
   354	            f"Tolerance is {MAX_WINDOW_SHORTFALL_DAYS}d. A truncated feed silently "
   355	            "shortens the sample while every printed count still agrees with itself."
   356	        )
   357	
   358	    # 3a-bis: THE ENDPOINT EXPECTATION. Every check above (and 3a) reasons about
   359	    # the feed using the feed, so deleting an endpoint month from raw and selected
   360	    # at the same time moves every yardstick with it and nothing looks wrong. This
   361	    # check derives what MUST be there from the requested window alone.
   362	    #
   363	    # A month is required when the window contains the whole interval in which its
   364	    # report could have been published: day 1 (earliest possible) through
   365	    # LATEST_OBSERVED_RELEASE_DAY_OF_MONTH (shutdown-delayed worst case). Anything
   366	    # narrower would demand a release the window may legitimately cut off.
   367	    #
   368	    # The constant is self-policing: if the feed ever carries a release later in
   369	    # its month than the constant allows, the premise of this rule has expired and
   370	    # the run says so instead of quietly under-requiring.
   371	    latest_day_seen = max((d.day for d in sel), default=0)
   372	    if latest_day_seen > LATEST_OBSERVED_RELEASE_DAY_OF_MONTH:
   373	        offenders = sorted(str(d.date()) for d in sel if d.day > LATEST_OBSERVED_RELEASE_DAY_OF_MONTH)
   374	        raise RuntimeError(
   375	            f"release(s) {offenders} fall later in their month than "
   376	            f"LATEST_OBSERVED_RELEASE_DAY_OF_MONTH={LATEST_OBSERVED_RELEASE_DAY_OF_MONTH}. "
   377	            "That constant is the premise of the required-month endpoint check; a later "
   378	            "release means the premise is stale and the endpoint expectation would silently "
   379	            "under-require. Re-derive the constant against the BLS archive before proceeding."
   380	        )
   381	
   382	    required_months = sorted(
   383	        p.strftime("%Y-%m")
   384	        for p in pd.period_range(start=want_start, end=want_end, freq="M")
   385	        if p.to_timestamp() >= want_start
   386	        and p.to_timestamp().replace(day=LATEST_OBSERVED_RELEASE_DAY_OF_MONTH) <= want_end
   387	    )
   388	    absent_required = sorted(set(required_months) - set(sel_months) - set(KNOWN_MISSING_MONTHS))
   389	    if absent_required:
   390	        raise RuntimeError(
   391	            f"the requested window {start}..{end} fully contains the publication window of "
   392	            f"{len(absent_required)} month(s) that the calendar has no release for: "
   393	            f"{absent_required}. This is derived from the REQUESTED WINDOW, not from the feed, "
   394	            "so it still fires when a month is deleted from the raw feed and the selection at "
   395	            "the same time -- the case the observed-span checks structurally cannot see."
   396	        )
   397	
   398	    # 3b: no month may vanish from inside the observed span.
   399	    span = {
   400	        p.strftime("%Y-%m")
   401	        for p in pd.period_range(start=min(sel), end=max(sel), freq="M")
   402	    }
   403	    missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
   404	    if missing:
   405	        raise RuntimeError(
   406	            f"official NFP calendar is missing {len(missing)} month(s) inside the observed "
   407	            f"span: {missing}. A partial calendar dumps real event days into the control "
   408	            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
   409	            "reason (e.g. a cancelled release), never to make this check pass."
   410	        )
   411	
   412	    # 4: a claimed hole must actually be a hole in the RAW feed. Without this the
   413	    # allowlist is a bypass: any month could be declared 'known missing' and the
   414	    # check would stop looking at it.
   415	    # Scan the WHOLE allowlist, not just the part inside the observed span: a
   416	    # claim about a month outside the span is exactly the one nobody re-checks.
   417	    bogus = sorted(m for m in KNOWN_MISSING_MONTHS if raw_by_month.get(m))
   418	    if bogus:
   419	        raise RuntimeError(
   420	            f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
   421	            f"entries for them: { {m: [str(d.date()) for d in raw_by_month[m]] for m in bogus} }. "
   422	            "The allowlist is for real cancellations, not for silencing a selection bug."
   423	        )
   424	
   425	    return {
   426	        "n_months_in_span": len(span),
   427	        "n_raw_entries": len(raw),
   428	        "months_with_multiple_raw_entries": sorted(multi),
   429	        "reviewed_multi_entry_months": dict(sorted(REVIEWED_MULTI_ENTRY_MONTHS.items())),
   430	        "ambiguity_gap_threshold_days": AMBIGUOUS_SAME_MONTH_GAP_DAYS,
   431	        "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
   432	        "window_coverage": {
   433	            "requested": f"{start}..{end}",
   434	            "observed": f"{min(sel).date()}..{max(sel).date()}",
   435	            "head_shortfall_days": int(head_short),
   436	            "tail_shortfall_days": int(tail_short),
   437	            "tolerance_days": MAX_WINDOW_SHORTFALL_DAYS,
   438	        },
   439	        "endpoint_expectation": {
   440	            "derived_from": "requested window only -- never from the feed",
   441	            "latest_observed_release_day_of_month": LATEST_OBSERVED_RELEASE_DAY_OF_MONTH,
   442	            "n_required_months": len(required_months),
   443	            "required_first_month": required_months[0] if required_months else None,
   444	            "required_last_month": required_months[-1] if required_months else None,
   445	            "excused_by_known_missing": sorted(set(required_months) & set(KNOWN_MISSING_MONTHS)),
   446	            "why": (
   447	                "Codex round-5 B2: deleting an endpoint month from the raw feed and the "
   448	                "selection together left every feed-relative check self-consistent (259 raw / "
   449	                "253 selected, shortfall inside the 70d tolerance) and the sample silently "
   450	                "shortened. The requested window is the one fact a truncated feed cannot edit."
   451	            ),
   452	        },
   453	        "residual_limitation": (
   454	            "Two heuristics remain. (1) Same-month selection uses 'earliest wins', which "
   455	            "cannot distinguish an off-cycle item filed BEFORE the report from the report "
   456	            "itself, so every multi-entry month must additionally appear in "
   457	            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A new "
   458	            "multi-entry month fails the run rather than being assumed. (2) The endpoint "
   459	            "expectation can still be silenced by adding a required month to "
   460	            "KNOWN_MISSING_MONTHS. That is deliberate -- 2025-10 really was cancelled -- and "
   461	            "it is bounded by check 4, which verifies against the RAW feed that a claimed "
   462	            "hole is a real hole. What remains uncovered is a month deleted from the raw feed "
   463	            "AND declared missing in writing: a documented false claim, not a silent "
   464	            "truncation. This gate is fail-closed against the latter, not the former."
   465	        ),
   466	    }
   467	
   468	
   469	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
   470	    """Official NFP (Employment Situation) release dates.
   469	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
   470	    """Official NFP (Employment Situation) release dates.
   471	
   472	    Deliberately has no except branch. If the release calendar cannot be
   473	    reached, this run must die -- a proxy calendar produces plausible numbers
   474	    from non-events, which is worse than no numbers at all. See the CORRECTION
   475	    note in the module docstring.
   476	    """
   477	    dates = nfp_release_dates(start, end)
   478	    if len(dates) == 0:
   479	        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
   480	    # Pull the unselected feed as well: the accessor collapses each month to one
   481	    # date, so the only place a same-month ambiguity is still visible is here.
   482	    raw = _fetch(RELEASE_IDS["NFP_US"], start, end)
   483	    completeness = check_calendar_is_complete(dates, raw, start, end)
   484	    return list(dates), completeness
   485	
   486	
   487	# ============================================================
   488	# 2. Download data
   489	# ============================================================
   490	print("=" * 60)
   491	print("K528: NFP Event Study on SPY Volatility")
   492	print("=" * 60)
   493	
   494	print("\n[1/6] Downloading SPY and VIX data...")
   495	spy = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END, progress=False)
   496	vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END, progress=False)
   497	
   498	# Handle multi-level columns from yfinance
   499	if isinstance(spy.columns, pd.MultiIndex):
   500	    spy.columns = spy.columns.get_level_values(0)
   501	if isinstance(vix.columns, pd.MultiIndex):
   502	    vix.columns = vix.columns.get_level_values(0)
   503	
   504	
   505	def check_price_coverage(frame, ticker, start, end):
   506	    """Fail closed on a price series that does not reach both ends of the window.
   507	
   508	    Codex round-5 B3: there was no coverage check here at all. A SPY download
   509	    ending a month early does not raise and does not produce NaNs -- the releases
   510	    past the end simply get filed under `n_outside_price_sample` and the run
   511	    reports a conclusion on a quietly shorter sample. A short ^VIX tail is worse
   512	    still, because the ffill below turns it into stale-but-present numbers.
   513	
   514	    Same principle as the calendar gate: the requested window is the yardstick,
   515	    because it is the one thing a truncated download cannot move.
   516	    """
   517	    if len(frame) == 0:
   518	        raise RuntimeError(f"{ticker}: download returned no rows for {start}..{end}")
   519	    head_short = (frame.index[0] - pd.Timestamp(start)).days
   520	    tail_short = (pd.Timestamp(end) - frame.index[-1]).days
   521	    if head_short > MAX_PRICE_COVERAGE_SHORTFALL_DAYS or tail_short > MAX_PRICE_COVERAGE_SHORTFALL_DAYS:
   522	        raise RuntimeError(
   523	            f"{ticker} does not cover the requested window {start}..{end}: first bar "
   524	            f"{frame.index[0].date()} ({head_short}d in), last bar {frame.index[-1].date()} "
   525	            f"({tail_short}d short of the end). Tolerance is "
   526	            f"{MAX_PRICE_COVERAGE_SHORTFALL_DAYS}d (long holiday weekend). A truncated price "
   527	            "series shortens this fixed historical sample without shortening any count that "
   528	            "gets printed."
   529	        )
   530	    return {
   531	        "ticker": ticker,
   532	        "n_rows": int(len(frame)),
   533	        "observed": f"{frame.index[0].date()}..{frame.index[-1].date()}",
   534	        "head_shortfall_days": int(head_short),
   535	        "tail_shortfall_days": int(tail_short),
   536	        "tolerance_days": MAX_PRICE_COVERAGE_SHORTFALL_DAYS,
   537	    }
   538	
   539	
   540	price_coverage = {
   541	    "SPY": check_price_coverage(spy, "SPY", SAMPLE_START, SAMPLE_END),
   542	    "^VIX": check_price_coverage(vix, "^VIX", SAMPLE_START, SAMPLE_END),
   543	}
   544	
   545	# Calculate returns
   546	spy["Return"] = spy["Close"].pct_change()
   547	spy["AbsReturn"] = spy["Return"].abs()
   548	spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
   549	spy.dropna(subset=["Return"], inplace=True)
   550	
   551	# Merge VIX
   552	vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
   553	spy = spy.join(vix_close, how="left")
   554	
   555	def check_vix_forward_fill_age(vix_series):
   556	    """Bound how long a forward-filled VIX may be carried, BEFORE filling.
   557	
   558	    `ffill()` is silent by construction: a ^VIX series that stops a month early
   559	    leaves the last real quote stamped on every session after it, and the regime
   560	    split and the correlation then run on a constant that looks like data.
   561	    Holidays justify carrying a quote for a session or two; they do not justify
   562	    carrying one for a month.
   563	
   564	    A function rather than inline code so it can be attacked by a test. An
   565	    unexercised guard and an absent guard fail the same way.
   566	    """
   567	    missing = vix_series.isna()
   568	    run = max_run = 0
   569	    for m in missing:
   570	        run = run + 1 if m else 0
   571	        max_run = max(max_run, run)
   572	    if max_run > MAX_VIX_FFILL_TRADING_DAYS:
   573	        raise RuntimeError(
   574	            f"^VIX is missing for up to {max_run} consecutive SPY sessions; the limit is "
   575	            f"{MAX_VIX_FFILL_TRADING_DAYS}. Forward-filling across a gap that long would carry "
   576	            "a stale VIX into the regime split and the correlation as if it were an "
   577	            "observation. A run this long is a truncated or partial ^VIX download, not a holiday."
   578	        )
   579	    filled = vix_series.ffill()
   580	    if filled.isna().any():
   581	        raise RuntimeError(
   582	            f"{int(filled.isna().sum())} session(s) still have no VIX after forward fill. The "
   583	            "gap is at the START of the sample, where there is nothing to carry forward."
   584	        )
   585	    return filled, {
   586	        "n_sessions_without_native_vix": int(missing.sum()),
   587	        "max_consecutive_ffill_trading_days": int(max_run),
   588	        "limit_trading_days": MAX_VIX_FFILL_TRADING_DAYS,
   589	    }
   590	
     1	"""Official macro-event release dates.
     2	
     3	Event studies treat the event date as a constant. It is not — it is data, and it
     4	needs a primary source like any other input. A calendar proxy ("CPI comes out
     5	around the 13th") silently does two things at once: it counts non-event days as
     6	event days, and it dumps real event days into the control group. Nothing throws,
     7	nothing is NaN, the figures still render.
     8	
     9	That is not hypothetical. Until 2026-07-12 our CPI event studies hard-coded the
    10	release dates from a 13th-of-month proxy. Against the official calendar 7 of 13
    11	dates were wrong, one of them a day on which BLS published no CPI at all (the
    12	Oct-2025 release was cancelled during the shutdown). Recomputing the CPI-day VIX
    13	reaction on the real dates flipped the mean from +2.18% to -0.85%.
    14	
    15	So: get the dates from the release calendar. `ALFRED` (FRED's real-time archive)
    16	publishes the actual news-release dates per statistical release, which is exactly
    17	the ground truth an event study needs.
    18	
    19	Usage:
    20	    from volpred.data.event_dates import cpi_release_dates
    21	    dates = cpi_release_dates("2024-01-01", "2026-12-31")   # DatetimeIndex
    22	
    23	See docs/error_log.md 2026-07-12 for the incident this module exists to prevent.
    24	"""
    25	
    26	from __future__ import annotations
    27	
    28	import json
    29	import logging
    30	import os
    31	from datetime import timedelta
    32	from pathlib import Path
    33	
    34	import pandas as pd
    35	import requests
    36	
    37	logger = logging.getLogger(__name__)
    38	
    39	# FRED release ids for the macro releases we run event studies on.
    40	# https://fred.stlouisfed.org/releases
    41	RELEASE_IDS = {
    42	    "CPI_US": 10,      # Consumer Price Index
    43	    "NFP_US": 50,      # Employment Situation
    44	    "FOMC": 101,       # H.4.1 is not the FOMC; FOMC statements are not a FRED release
    45	}
    46	
    47	_CACHE_DIR = Path(__file__).resolve().parents[3] / "storage" / "data" / "event_dates_cache"
    48	_CACHE_TTL = timedelta(days=7)
    49	
    50	
    51	def _api_key() -> str:
    52	    key = os.environ.get("FRED_API_KEY")
    53	    if key:
    54	        return key
    55	    root = Path(__file__).resolve().parents[3]
    56	    for cand in (".env.local", ".env"):
    57	        p = root / cand
    58	        if not p.exists():
    59	            continue
    60	        for line in p.read_text().splitlines():
    61	            if line.startswith("FRED_API_KEY"):
    62	                return line.split("=", 1)[1].strip().strip("\"'")
    63	    raise RuntimeError(
    64	        "FRED_API_KEY not found. Event dates must come from the official release "
    65	        "calendar — do not fall back to a hard-coded list or a calendar proxy."
    66	    )
    67	
    68	
    69	def _fetch(release_id: int, start: str, end: str) -> list[str]:
    70	    r = requests.get(
    71	        "https://api.stlouisfed.org/fred/release/dates",
    72	        params={
    73	            "release_id": release_id,
    74	            "api_key": _api_key(),
    75	            "file_type": "json",
    76	            "realtime_start": start,
    77	            "realtime_end": end,
    78	            # Without this, ALFRED only returns releases that already carry data, so
    79	            # scheduled-but-not-yet-published dates (the ones an upcoming-event
    80	            # populator actually needs) are missing. Verified 2026-07-12 that it does
    81	            # NOT resurrect cancelled releases: the Oct-2025 CPI, scrapped during the
    82	            # shutdown, stays absent either way.
    83	            "include_release_dates_with_no_data": "true",
    84	            "limit": 1000,
    85	            "sort_order": "asc",
    86	        },
    87	        timeout=30,
    88	    )
    89	    r.raise_for_status()
    90	    return [d["date"] for d in r.json()["release_dates"]]
    91	
    92	
    93	def release_dates(event: str, start: str, end: str, *, use_cache: bool = True) -> pd.DatetimeIndex:
    94	    """Official news-release dates for `event` within [start, end].
    95	
    96	    Monthly releases can carry off-cycle entries (annual seasonal-factor and
    97	    benchmark revisions are filed against the same release id, LATER in the
    98	    month than the regular report). We therefore keep the EARLIEST entry in
    99	    each month — 2026-07-19 k528 Codex review proved the previous `max()` rule
   100	    picked 6 off-cycle dates as NFP events and flipped a significance result.
   101	
   102	    Fail-closed on ambiguity: the selected sequence must look like a monthly
   103	    release calendar (consecutive gaps 13–110 days; shutdown catch-ups compress for real,
   104	    e.g. 2013-10-22 -> 2013-11-08 = 17d, and cancelled months stretch,
   105	    e.g. 2025-09-05 -> 2025-11-20 = 76d). Any gap outside that band
   106	    raises instead of returning a plausible-but-wrong calendar —
   107	    silently-wrong event dates are worse than a failed run.
   108	    """
   109	    if event not in RELEASE_IDS:
   110	        raise KeyError(f"unknown event {event!r}; known: {sorted(RELEASE_IDS)}")
   111	
   112	    cache = _CACHE_DIR / f"{event}_{start}_{end}.json"
   113	    if use_cache and cache.exists():
   114	        age = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timestamp(cache.stat().st_mtime, unit="s")
   115	        if age < _CACHE_TTL:
   116	            raw = json.loads(cache.read_text())
   117	        else:
   118	            raw = None
   119	    else:
   120	        raw = None
   121	
   122	    if raw is None:
   123	        raw = _fetch(RELEASE_IDS[event], start, end)
   124	        if use_cache:
   125	            # use_cache=False must bypass the cache ENTIRELY — the old code
   126	            # skipped only the read and still wrote, which leaked canonical
   127	            # writes out of hermetic tests (CI repo-state guard, 2026-07-19).
   128	            from volpred.canonical_write import guard_canonical_write
   129	
   130	            guard_canonical_write(cache)
   131	            cache.parent.mkdir(parents=True, exist_ok=True)
   132	            cache.write_text(json.dumps(raw) + "\n")
   133	
   134	    dates = pd.to_datetime(raw)
   135	    if len(dates) == 0:
   136	        raise RuntimeError(f"no {event} release dates returned for {start}..{end}")
   137	    s = pd.Series(dates, index=dates)
   138	    monthly = s.groupby([dates.year, dates.month]).min()
   139	    selected = pd.DatetimeIndex(sorted(monthly.values))
   140	    # Lower bound 13d catches mispicked entries (collapse patterns run <=12d)
   141	    # while passing real shutdown catch-ups (2013-10-22 -> 2013-11-08 = 17d).
   142	    # Upper bound 110d allows cancelled months (76d real) but trips on 3+ gaps.
   143	    gaps = pd.Series(selected).diff().dropna().dt.days
   144	    bad = gaps[(gaps < 13) | (gaps > 110)]
   145	    if len(bad) > 0:
   146	        offenders = [
   147	            f"{selected[i - 1].date()} -> {selected[i].date()} ({int(g)}d)"
   148	            for i, g in zip(bad.index, bad.values)
   149	        ]
   150	        raise RuntimeError(
   151	            f"{event} release calendar failed monthly-cadence validation "
   152	            f"(gaps outside 13-110 days): {offenders}. Off-cycle entries or "
   153	            f"missing months need manual disambiguation — refusing to return "
   154	            f"a plausible-but-wrong calendar."
   155	        )
   156	    return selected
   157	
   158	
   159	def cpi_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   160	    return release_dates("CPI_US", start, end, **kw)
   161	
   162	
   163	def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   164	    return release_dates("NFP_US", start, end, **kw)

2026-07-27T00:30:09.071066Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "nl -ba tests/test_nfp_official_release_dates.py | sed -n '760,1292p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
   760	        mod = _k528_module()
   761	        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
   762	        with pytest.raises(RuntimeError, match="does not"):
   763	            mod.check_calendar_is_complete(
   764	                pd.to_datetime(["2024-01-05", "2024-02-02"]),
   765	                ["2024-01-05", "2024-02-02", "2024-03-08"],
   766	                "2024-01-01", "2024-03-31",
   767	            )
   768	
   769	    def test_allowlists_cannot_combine_even_with_a_reviewed_shape(self):
   770	        mod = _k528_module()
   771	        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
   772	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-03"] = {
   773	            "raw": ["2024-03-08", "2024-03-15"], "report": "2024-03-08",
   774	        }
   775	        with pytest.raises(RuntimeError, match="does not"):
   776	            mod.check_calendar_is_complete(
   777	                pd.to_datetime(["2024-01-05", "2024-02-02"]),
   778	                ["2024-01-05", "2024-02-02", "2024-03-08", "2024-03-15"],
   779	                "2024-01-01", "2024-03-31",
   780	            )
   781	
   782	    def test_a_month_cannot_be_in_both_allowlists(self):
   783	        mod = _k528_module()
   784	        mod.KNOWN_MISSING_MONTHS["2024-02"] = "fabricated"
   785	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
   786	            "raw": ["2024-02-02", "2024-02-09"], "report": "2024-02-02",
   787	        }
   788	        with pytest.raises(RuntimeError, match="both KNOWN_MISSING_MONTHS"):
   789	            mod.check_calendar_is_complete(
   790	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
   791	                ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
   792	                "2024-01-01", "2024-03-31",
   793	            )
   794	
   795	    def test_known_missing_claim_is_checked_outside_the_selected_span_too(self):
   796	        """A claim about a month beyond the observed span is exactly the one
   797	        nobody re-checks."""
   798	        mod = _k528_module()
   799	        mod.KNOWN_MISSING_MONTHS["2024-04"] = "fabricated"
   800	        with pytest.raises(RuntimeError, match="does not|claims"):
   801	            mod.check_calendar_is_complete(
   802	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
   803	                ["2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05"],
   804	                "2024-01-01", "2024-04-30",
   805	            )
   806	
   807	    def test_truncated_feed_cannot_hide_behind_its_own_shrunken_span(self, check):
   808	        """Anchoring the gap check on the OBSERVED span cannot catch truncation:
   809	        if the feed stops early the span shrinks with it and nothing looks
   810	        missing. Found by self-audit, not by a reviewer."""
   811	        dates = ["2024-01-05", "2024-02-02", "2024-03-08"]
   812	        with pytest.raises(RuntimeError, match="does not cover"):
   813	            check(pd.to_datetime(dates), dates, "2024-01-01", "2024-12-31")
   814	
   815	    def test_unreviewed_multi_entry_month_is_refused_not_guessed(self, check):
   816	        """'Earliest wins' cannot distinguish an off-cycle item filed BEFORE the
   817	        report from the report. A new multi-entry month must stop the run."""
   818	        with pytest.raises(RuntimeError, match="never been"):
   819	            check(
   820	                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
   821	                ["2024-01-05", "2024-02-01", "2024-02-06", "2024-03-08"],
   822	                "2024-01-01", "2024-03-31",
   823	            )
   824	
   825	    def test_selection_contradicting_the_human_verified_date_fails(self):
   826	        mod = _k528_module()
   827	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
   828	            "raw": ["2024-02-01", "2024-02-06"], "report": "2024-02-06",
   829	        }
   830	        with pytest.raises(RuntimeError, match="contradicts"):
   831	            mod.check_calendar_is_complete(
   832	                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
   833	                ["2024-01-05", "2024-02-01", "2024-02-06", "2024-03-08"],
   834	                "2024-01-01", "2024-03-31",
   835	            )
   836	
   837	    def test_a_reviewed_month_with_a_normal_revision_still_passes(self):
   838	        """The other half: a guard that rejects everything is as useless as one
   839	        that rejects nothing. A revision filed a week later, in a month someone
   840	        has checked against the BLS archive, must go through."""
   841	        mod = _k528_module()
   842	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
   843	            "raw": ["2024-02-02", "2024-02-09"], "report": "2024-02-02",
   844	        }
   845	        out = mod.check_calendar_is_complete(
   846	            pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
   847	            ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
   848	            "2024-01-01", "2024-03-31",
   849	        )
   850	        assert out["months_with_multiple_raw_entries"] == ["2024-02"]
   851	
   852	    def test_the_six_real_multi_entry_months_pass_on_the_real_feed(self):
   853	        """The strongest negative control available: the actual 264-entry ALFRED
   854	        feed, whose six duplicate months are exactly the reviewed ones."""
   855	        import json
   856	
   857	        mod = _k528_module()
   858	        raw = json.loads(
   859	            (REPO_ROOT / "tests" / "fixtures" / "fred_release_50_nfp_raw_20260719.json")
   860	            .read_text(encoding="utf-8")
   861	        )["release_dates"]
   862	        by_month = {}
   863	        for d in raw:
   864	            by_month.setdefault(d[:7], []).append(d)
   865	        sel = sorted(min(v) for v in by_month.values())
   866	        out = mod.check_calendar_is_complete(
   867	            pd.to_datetime(sel), raw, "2005-01-01", "2026-07-19"
   868	        )
   869	        assert out["months_with_multiple_raw_entries"] == sorted(
   870	            mod.REVIEWED_MULTI_ENTRY_MONTHS
   871	        )
   872	
   873	
   874	# ---------------------------------------------------------------------------
   875	# Round-7 N1: a STRUCTURAL detector for the 237-as-a-release-count misbinding.
   876	#
   877	# 237 is the count of official NFP releases that TRADED in a Friday session; 243
   878	# is the count DATED a Friday. Round 6 shipped a guard advertised as a
   879	# "structural invariant" that was really a 5-phrase blocklist with two
   880	# unconditional line-level exemptions (any 243 on the line, or any denial token
   881	# on the line). The round-6 collection verdict proved four synonym rephrasings
   882	# and two exemption hijacks walked straight past it. This replaces the wordlist
   883	# with a compositional, proximity-aware check:
   884	#
   885	#   * "release-dated language" is NOT a fixed phrase. It is a Friday token whose
   886	#     nearest governing verb (within a small window) is a release/publication
   887	#     verb -- so 'released on a Friday', 'published on a Friday', '週五發布',
   888	#     '發布日在週五' all trip it, but '237 releases traded in a Friday session'
   889	#     (where 'releases' is the subject noun and Friday governs 'session') does
   890	#     not. That noun-vs-predicate distinction is the reason the check is
   891	#     proximity-based rather than clause-wide.
   892	#   * a Friday token bound to a SESSION verb marks the correct estimand, so a
   893	#     clause that binds Friday to a session (or draws the 243/237 distinction)
   894	#     is exempt -- but an unrelated '243 trading weeks' no longer buys a pass,
   895	#     because the session word has to sit NEXT TO the Friday, not merely on the
   896	#     same line.
   897	#   * the denial escape is CLAUSE-LOCAL: a correction marker only exempts the
   898	#     clause it lives in, so a denial in a neighbouring clause can no longer
   899	#     launder an offending one.
   900	# ---------------------------------------------------------------------------
   901	
   902	_FRIDAY_TOKENS = ("friday", "週五", "周五", "星期五", "禮拜五")
   903	_RELEASE_VERBS = (
   904	    "releas", "publish", "publicat", "announce",
   905	    "公布", "公佈", "發布", "發佈", "發表", "公告",
   906	)
   907	_SESSION_VERBS = ("session", "trade", "trading", "交易", "盤")
   908	# Markers that a clause is QUOTING the wrong wording in order to retire it.
   909	_DENIAL_MARKERS = (
   910	    "wrong", "typo", "erratum", "errata", "correction", "misbind",
   911	    "must not", "should read", "retire", "supersed",
   912	    "錯", "誤植", "更正", "勘誤", "此前", "既不是", "不是", "應為", "應改",
   913	)
   914	_CLAUSE_DELIM = re.compile(r"(?:;|；|。|--|——|—|\||\t|\r?\n)")
   915	_RE_237 = re.compile(r"(?<!\d)237(?!\d)")
   916	_FRIDAY_RE = re.compile("|".join(re.escape(t) for t in _FRIDAY_TOKENS))
   917	# A phrase inside quotation marks is a MENTION, not a use: an errata note quotes
   918	# the wrong wording ('Friday releases', 「Friday releases」) in order to retire
   919	# it. Verbs inside such spans do not bind their Friday.
   920	_QUOTED_SPAN = re.compile(
   921	    r"'[^'\n]*'|\"[^\"\n]*\"|「[^」\n]*」|『[^』\n]*』|“[^”\n]*”|‘[^’\n]*’"
   922	)
   923	# The farthest a verb may sit from a Friday token and still be taken to govern
   924	# it. Beyond this the Friday is treated as governed by neither.
   925	_MAX_BIND_GAP = 24
   926	
   927	
   928	def _contains_any(text, tokens):
   929	    low = text.lower()
   930	    return any(tok in low for tok in tokens)
   931	
   932	
   933	def _quoted_regions(low):
   934	    return [(m.start(), m.end()) for m in _QUOTED_SPAN.finditer(low)]
   935	
   936	
   937	def _verb_spans(low, verbs, quoted):
   938	    spans = []
   939	    for v in verbs:
   940	        start = low.find(v)
   941	        while start != -1:
   942	            s, e = start, start + len(v)
   943	            if not any(qs <= s and e <= qe for qs, qe in quoted):
   944	                spans.append((s, e))
   945	            start = low.find(v, start + 1)
   946	    return spans
   947	
   948	
   949	def _nearest_gap(friday_span, verb_spans):
   950	    """Smallest character gap between a Friday token and any of ``verb_spans``
   951	    (0 if they overlap), or None if the nearest is beyond ``_MAX_BIND_GAP``."""
   952	    fs, fe = friday_span
   953	    best = None
   954	    for vs, ve in verb_spans:
   955	        if ve <= fs:
   956	            gap = fs - ve
   957	        elif vs >= fe:
   958	            gap = vs - fe
   959	        else:
   960	            gap = 0
   961	        if gap <= _MAX_BIND_GAP and (best is None or gap < best):
   962	            best = gap
   963	    return best
   964	
   965	
   966	def _friday_bindings(text):
   967	    """For every Friday token, decide by NEAREST GOVERNOR whether it is bound to
   968	    a release/publication verb or to a session verb, then OR the verdicts over
   969	    the clause. Returns ``(release_bound, session_bound)``.
   970	
   971	    Nearest-governor rather than a fixed window because the two readings sit at
   972	    different distances: 'publication day was a Friday' puts the release verb 11
   973	    characters out, while 'a Friday session' puts the session word right against
   974	    it. A symmetric window wide enough for the former would also swallow an
   975	    unrelated '243 trading weeks'; comparing which governor is CLOSER does not.
   976	    Ties go to release (the misbinding), so appending a distant session word
   977	    cannot launder a tight 'Friday releases'."""
   978	    low = text.lower()
   979	    friday_spans = [(m.start(), m.end()) for m in _FRIDAY_RE.finditer(low)]
   980	    if not friday_spans:
   981	        return False, False
   982	    quoted = _quoted_regions(low)
   983	    release_spans = _verb_spans(low, _RELEASE_VERBS, quoted)
   984	    session_spans = _verb_spans(low, _SESSION_VERBS, quoted)
   985	    release_bound = session_bound = False
   986	    for span in friday_spans:
   987	        rd = _nearest_gap(span, release_spans)
   988	        sd = _nearest_gap(span, session_spans)
   989	        if rd is not None and (sd is None or rd <= sd):
   990	            release_bound = True
   991	        elif sd is not None:
   992	            session_bound = True
   993	    return release_bound, session_bound
   994	
   995	
   996	def _clause_misbinds_237(clause):
   997	    """Does this clause present 237 (a SESSION count) as a Friday-RELEASE count
   998	    without correcting or reconciling it? Returns ``(bool, reason)``."""
   999	    if not _RE_237.search(clause):
  1000	        return False, ""
  1001	    release_bound, session_bound = _friday_bindings(clause)
  1002	    if not release_bound:
  1003	        # 237 is here, but no Friday token governs a release act, e.g.
  1004	        # '237 traded in a Friday session' -- the correct estimand.
  1005	        return False, ""
  1006	    if session_bound:
  1007	        # A Friday also governs a session in this clause: either the session
  1008	        # estimand itself or the 243/237 distinction being drawn. Both honest.
  1009	        return False, "Friday bound to a session (correct estimand / distinction drawn)"
  1010	    if _contains_any(clause, _DENIAL_MARKERS):
  1011	        return False, "correction context (clause quotes the wrong wording to retire it)"
  1012	    return True, "237 sits in Friday-release language with no Friday-session reading"
  1013	
  1014	
  1015	def _release_misbinding_offenders(text):
  1016	    """Split `text` into clauses and return ``(clause, reason)`` for any that
  1017	    misbind 237. `text` is normally one logical unit (a Markdown/JSON physical
  1018	    line, or a whole Python string literal); the splitter also breaks embedded
  1019	    newlines so a multi-line docstring is judged line by line."""
  1020	    hits = []
  1021	    for clause in _CLAUSE_DELIM.split(text):
  1022	        bad, reason = _clause_misbinds_237(clause)
  1023	        if bad:
  1024	            hits.append((clause.strip()[:120], reason))
  1025	    return hits
  1026	
  1027	
  1028	def _k528_text_units(path):
  1029	    """Yield ``(lineno, text)`` logical units for the misbinding scan.
  1030	
  1031	    Python files are parsed with ``ast`` so an implicitly-concatenated string
  1032	    ('a' 'b' across physical lines) is ONE unit -- that is the exact shape that
  1033	    would otherwise wrap a 'Friday' away from its 'session' onto the next
  1034	    physical line and manufacture a false positive. Comment lines, which ast
  1035	    drops, are yielded verbatim. JSON and Markdown are scanned per physical
  1036	    line."""
  1037	    text = path.read_text(encoding="utf-8")
  1038	    if path.suffix == ".py":
  1039	        import ast
  1040	
  1041	        try:
  1042	            tree = ast.parse(text)
  1043	        except SyntaxError:  # silent-ok: fall back to the STRICTER physical-line scan (every line, not just string literals) so an unparseable .py is scanned more, never skipped; this is a test-side gate, not a production path that could hide data
  1044	            for i, line in enumerate(text.splitlines(), 1):
  1045	                yield i, line
  1046	            return
  1047	        for node in ast.walk(tree):
  1048	            if isinstance(node, ast.Constant) and isinstance(node.value, str):
  1049	                yield node.lineno, node.value
  1050	        for i, line in enumerate(text.splitlines(), 1):
  1051	            if line.lstrip().startswith("#"):
  1052	                yield i, line
  1053	    else:
  1054	        for i, line in enumerate(text.splitlines(), 1):
  1055	            yield i, line
  1056	
  1057	
  1058	class TestFridayEstimandIsScopedHonestly:
  1059	    """Codex v3 finding 4: restricting to Friday is a legitimate conditional
  1060	    estimand, but it stops supporting statements about NFP releases in general,
  1061	    and the restriction is not a neutral sample deletion."""
  1062	
  1063	    def test_results_scope_the_claim_to_friday_and_disclose_the_non_neutrality(self):
  1064	        b = _load_k528(K528_RESULTS)["statistical_tests"]["B_nfp_vs_friday"]
  1065	        assert "CONDITIONAL ON FRIDAY" in b["estimand"]
  1066	        # Round-5 B1 tightened this. The old assertion pinned "Friday NFP", which
  1067	        # is exactly the ambiguity Codex flagged: it reads equally as "dated a
  1068	        # Friday" (243) and "traded in a Friday session" (237). Pinning the
  1069	        # session phrasing alone would still let a writer say "released on a
  1070	        # Friday" elsewhere, so the scope must ALSO rule that reading out.
  1071	        assert "ABSORBED BY A FRIDAY SESSION" in b["claim_scope"]
  1072	        assert "NFP traded in a Friday session" in b["claim_scope"]
  1073	        assert "not 'NFP released on a Friday'" in b["claim_scope"], (
  1074	            "the claim scope must explicitly retire the release-dated reading, "
  1075	            "not merely assert the session-dated one"
  1076	        )
  1077	        nn = b["restriction_is_not_neutral"]
  1078	        assert nn["excluded_are_quieter_by_pct"] > 0, (
  1079	            "if the excluded events are quieter, the restriction RAISES the ratio "
  1080	            "and that must be stated, not discovered by a reviewer"
  1081	        )
  1082	
  1083	    def test_friday_estimand_pins_release_vs_session_and_names_the_good_fridays(self):
  1084	        """Round-5 B1. The defect was that two different counts were fused into
  1085	        one word: 243 releases are DATED a Friday, 237 TRADE in a Friday session.
  1086	        The artifact must carry both numbers and reconcile them, and the six
  1087	        releases that differ must be named individually -- an aggregate count is
  1088	        re-derivable from a bug, a name list is not.
  1089	        """
  1090	        est = _load_k528(K528_RESULTS)["sample"]["friday_estimand"]
  1091	        assert est["n_release_date_on_friday"] == 243
  1092	        assert est["n_traded_in_friday_session"] == 237
  1093	
  1094	        gf = est["friday_releases_absorbed_by_a_later_session"]
  1095	        assert gf["n"] == 6
  1096	        assert len(gf["dates"]) == gf["n"], "the count and the name list must agree"
  1097	        assert (
  1098	            est["n_release_date_on_friday"] - est["n_traded_in_friday_session"] == gf["n"]
  1099	        ), "the 243/237 gap must be fully accounted for by the named releases"
  1100	
  1101	        for case in gf["dates"]:
  1102	            release = pd.Timestamp(case["release_date"])
  1103	            session = pd.Timestamp(case["session_date"])
  1104	            assert release.weekday() == 4, f"{release} is not a Friday release"
  1105	            assert session.weekday() == 0, f"{session} is not a Monday session"
  1106	            assert case["session_weekday"] == 0
  1107	            assert session > release, "the absorbing session must come after the release"
  1108	
  1109	    def test_no_live_artifact_describes_the_237_as_a_release_count(self):
  1110	        """Round-5 B1 residual, rebuilt in round 7 (N1) from a 5-phrase blocklist
  1111	        into a compositional, proximity-aware structural check.
  1112	
  1113	        The defect is not a phrase, it is a MISBINDING: 237 is the count of
  1114	        releases ABSORBED BY a Friday session; 243 is the count of releases
  1115	        DATED a Friday. Saying '237 Friday releases' fuses them, and that is the
  1116	        sentence B1 exists to retire.
  1117	
  1118	        The round-6 guard keyed on five fixed phrases with two blanket
  1119	        exemptions, and the round-6 collection verdict proved four synonym
  1120	        rephrasings and two exemption hijacks walked past it. The detector this
  1121	        now delegates to (``_release_misbinding_offenders``) reads release-dated
  1122	        language as a Friday token GOVERNING a release verb, exempts a Friday
  1123	        that governs a session (the correct estimand / the drawn distinction),
  1124	        and keeps the denial escape clause-local. Its evasion suite -- the six
  1125	        round-6 injections plus legitimate distinction/errata lines -- lives in
  1126	        ``TestReleaseMisbindingGateIsStructural`` so the guard itself has a
  1127	        guard.
  1128	
  1129	        Scope is every LIVE artifact under experiments/k528, not a hand-listed
  1130	        few. Review RECORDS are exempt by filename: a verdict that quotes the
  1131	        defect verbatim as its evidence is doing its job.
  1132	        """
  1133	        review_records = (
  1134	            "codex_review_",
  1135	            "k528_round5_collection_verdict",
  1136	            "k528_round6_collection_verdict",
  1137	            "k528_round5_remediation",
  1138	            "k528_completeness_gate_fix",
  1139	            "round7_gate_hardening_summary",
  1140	            "review_verdict",
  1141	        )
  1142	        offenders = []
  1143	        for path in sorted(K528_DIR.rglob("*")):
  1144	            if not path.is_file() or path.suffix not in (".py", ".md", ".json"):
  1145	                continue
  1146	            if any(marker in path.name for marker in review_records):
  1147	                continue
  1148	            for lineno, unit in _k528_text_units(path):
  1149	                if "237" not in unit:
  1150	                    continue
  1151	                for clause, reason in _release_misbinding_offenders(unit):
  1152	                    offenders.append(
  1153	                        f"{path.relative_to(K528_DIR)}:{lineno} [{reason}] {clause}"
  1154	                    )
  1155	
  1156	        assert not offenders, (
  1157	            "237 is a SESSION count, not a release count. These clauses bind it "
  1158	            "to Friday-release language with no Friday-session reading and no "
  1159	            "correction context:\n  " + "\n  ".join(offenders)
  1160	        )
  1161	
  1162	    def test_readme_does_not_sanction_a_pre_registration_claim(self):
  1163	        """Round-5 B4 residual. The multiplicity family was defined after the
  1164	        data were seen, and the artifact says so. The README's 'what you may
  1165	        write' line is the sentence a publishing agent copies, so if it licenses
  1166	        '事先聲明' (declared in advance) the contradiction propagates outward
  1167	        even though every number is correct.
  1168	        """
  1169	        multiplicity = _load_k528(K528_RESULTS)["multiplicity"]
  1170	        assert multiplicity["pre_registered"] is False, (
  1171	            "if this ever becomes True the claim must be backed by a real "
  1172	            "pre-registration, not by editing the flag"
  1173	        )
  1174	        readme = K528_README.read_text(encoding="utf-8")
  1175	        assert "事先聲明" not in readme, (
  1176	            "README must not sanction a pre-specification claim while "
  1177	            "multiplicity.pre_registered is False"
  1178	        )
  1179	
  1180	    def test_excluded_count_matches_the_weekday_breakdown(self):
  1181	        """The results file once said 11 in prose and 16 in data."""
  1182	        results = _load_k528(K528_RESULTS)
  1183	        b = results["statistical_tests"]["B_nfp_vs_friday"]
  1184	        non_friday = sum(1 for e in results["event_data"] if e["weekday"] != 4)
  1185	        assert b["excluded_non_friday_events"]["n"] == non_friday == 16
  1186	        assert str(non_friday) in b["estimand"]
  1187	
  1188	
  1189	class TestReleaseMisbindingGateIsStructural:
  1190	    """Round-7 N1. The round-6 guard was a 5-phrase blocklist and the round-6
  1191	    collection verdict (k528_round6_collection_verdict.json, anti_vacuity_tests)
  1192	    proved four synonym rephrasings and two exemption hijacks walked past it.
  1193	
  1194	    These are those exact six evasions -- now pinned as MUST-CATCH -- plus the
  1195	    verbatim defect, and legitimate distinction/errata lines pinned as
  1196	    MUST-PASS. The point of N1 is a stricter gate, not a blunter one, so the
  1197	    false-positive side is tested as hard as the false-negative side. This
  1198	    class is the guard on the guard: if someone re-softens
  1199	    ``_clause_misbinds_237`` back into a wordlist, the synonym cases go red.
  1200	    """
  1201	
  1202	    # The verbatim defect plus the six round-6 evasions. Every one must be seen.
  1203	    MISBINDINGS = [
  1204	        pytest.param(
  1205	            "restricting the event group to Friday releases (237)",
  1206	            id="verbatim_round6_defect",
  1207	        ),
  1208	        # -- four synonym rephrasings that the 5-phrase blocklist missed --
  1209	        pytest.param("237 場 NFP 是週五發布的", id="synonym_zh_published"),
  1210	        pytest.param(
  1211	            "the 237 NFP announcements published on a Friday",
  1212	            id="synonym_en_published",
  1213	        ),
  1214	        pytest.param(
  1215	            "237 releases whose publication day was a Friday",
  1216	            id="synonym_en_publication_day",
  1217	        ),
  1218	        pytest.param("限定週五發布的 237 場 NFP 事件", id="synonym_zh_restricted"),
  1219	        # -- two exemption hijacks --
  1220	        pytest.param(
  1221	            "restricting the event group to Friday releases (237); "
  1222	            "sample spans 243 trading weeks",
  1223	            id="hijack_unrelated_243_on_line",
  1224	        ),
  1225	        pytest.param(
  1226	            "既不是 proxy 的問題 -- 237 Friday releases were used",
  1227	            id="hijack_denial_in_other_clause",
  1228	        ),
  1229	    ]
  1230	
  1231	    # Lines that DRAW the distinction correctly, or correct the wording. None
  1232	    # may be flagged; two are synthetic and two are copied from live artifacts.
  1233	    LEGITIMATE = [
  1234	        pytest.param(
  1235	            "243 releases were dated a Friday; "
  1236	            "237 of them traded in a Friday session",
  1237	            id="distinction_two_clauses",
  1238	        ),
  1239	        pytest.param(
  1240	            "更正：此前寫的是「237 Friday releases」是錯的 — "
  1241	            "237 是週五 session 交易數，243 才是週五發布的 release 數",
  1242	            id="errata_quotes_then_reconciles",
  1243	        ),
  1244	        pytest.param(
  1245	            "253 場有效發布中，243 場發布日在週五，但只有 237 場在週五開盤",
  1246	            id="live_readme_distinction_line",
  1247	        ),
  1248	        pytest.param(
  1249	            "event group to the 237 releases ABSORBED BY a Friday session.",
  1250	            id="live_session_estimand_releases_is_a_noun",
  1251	        ),
  1252	    ]
  1253	
  1254	    @pytest.mark.parametrize("text", MISBINDINGS)
  1255	    def test_misbindings_are_caught(self, text):
  1256	        assert _release_misbinding_offenders(text), (
  1257	            "the hardened gate let a 237-as-a-release-count misbinding through: "
  1258	            f"{text!r}. A synonym or an exemption hijack must not evade it."
  1259	        )
  1260	
  1261	    @pytest.mark.parametrize("text", LEGITIMATE)
  1262	    def test_legitimate_lines_are_not_flagged(self, text):
  1263	        hits = _release_misbinding_offenders(text)
  1264	        assert not hits, (
  1265	            f"the gate false-flagged a legitimate line: {text!r} -> {hits}. "
  1266	            "The goal is a stricter gate, not a blunter one."
  1267	        )
  1268	
  1269	    def test_the_243_exemption_is_conditional_not_blanket(self):
  1270	        """Round-6 weakness: any 243 on the line bought a free pass. A 243 that
  1271	        is not itself bound to Friday-release language must NOT launder 237."""
  1272	        # 243 present, and a session word ('sessions') present, so the old
  1273	        # blanket rule would have exempted -- but Friday governs 'released'.
  1274	        assert _release_misbinding_offenders(
  1275	            "237 released on a Friday across 243 sessions"
  1276	        )
  1277	
  1278	    def test_the_denial_exemption_is_clause_local_not_line_wide(self):
  1279	        """Round-6 weakness: any denial token on the line bought a free pass. A
  1280	        denial that lives in a different clause must NOT launder the offender."""
  1281	        assert _release_misbinding_offenders(
  1282	            "更正了其他行；237 released on a Friday"
  1283	        )
  1284	
  1285	    def test_the_gate_is_not_vacuous_on_the_live_tree(self):
  1286	        """A guard nobody has ever seen fire is not a guard. Inject the verbatim
  1287	        defect into a throwaway string and confirm the detector bites, then
  1288	        confirm a corrected version of the same clause does not."""
  1289	        assert _release_misbinding_offenders("event group of 237 Friday releases")
  1290	        assert not _release_misbinding_offenders(
  1291	            "237 releases traded in a Friday session; 243 were dated a Friday"
  1292	        )

2026-07-27T00:30:19.982956Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "rg -n '"'^class |''^    def test_'"' tests/test_nfp_official_release_dates.py
nl -ba tests/test_nfp_official_release_dates.py | sed -n '520,875p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
105:class TestProxyMismatches:
107:    def test_proxy_date_is_not_an_official_release(
118:    def test_mismatch_really_is_what_the_proxy_would_have_produced(
129:    def test_october_2025_release_does_not_exist(self, official):
139:    def test_proxy_dates_that_were_already_correct_stay_correct(
144:    def test_seven_of_thirteen_were_wrong(self, official):
161:class TestExperimentUsesOfficialCalendar:
162:    def test_release_date_is_july_2_not_july_3(self, experiment):
167:    def test_build_nfp_dates_returns_the_official_trailing_thirteen(
184:    def test_release_date_itself_is_excluded(self, experiment, monkeypatch):
199:    def test_fails_closed_when_calendar_is_short(self, experiment, monkeypatch):
210:    def test_fails_closed_when_calendar_is_unreachable(
222:class TestNoLookahead:
263:    def test_every_series_is_downloaded(self, experiment, monkeypatch):
268:    def test_download_window_ends_before_the_release(self, experiment, monkeypatch):
279:    def test_download_window_starts_before_the_earliest_event(
289:class _StopEarly(Exception):
293:class _Tripwire:
307:class TestNoProxyResidue:
311:    def test_experiment_defines_no_first_friday_helper(self):
316:    def test_experiment_imports_the_official_calendar(self):
320:    def test_results_json_declares_its_event_date_source(self):
402:class TestK528UsesOfficialCalendar:
403:    def test_defines_no_first_friday_helper(self):
409:    def test_imports_the_official_calendar(self):
417:    def test_results_declare_the_official_source_and_no_fallback(self):
422:    def test_event_dates_carry_no_proxy_signature(self):
425:    def test_sample_is_not_uniformly_friday(self):
433:    def test_audit_records_the_dates_that_changed(self):
443:    def test_no_off_cycle_revision_date_is_treated_as_an_event(self):
470:class TestProxyMutationIsCaught:
484:    def test_the_proxy_calendar_is_rejected(self):
488:    def test_phantom_october_2025_alone_is_enough_to_fail(self):
496:    def test_the_guard_accepts_the_official_calendar(self, official):
547:class TestControlGroupHasNoNfpDays:
553:    def test_every_mapped_nfp_session_is_excluded_from_the_control_group(self):
572:    def test_proxy_side_control_group_is_also_clean(self):
610:    def test_proxy_before_column_uses_one_control_definition_throughout(self):
621:    def test_window_excluded_event_is_not_silently_analysed_or_kept_as_control(self):
628:class TestCalendarFailClosedCannotBeBypassed:
637:    def test_off_cycle_entry_earlier_in_the_month_is_refused_not_silently_picked(self, check):
651:    def test_real_multi_entry_gaps_are_too_small_for_a_gap_rule(self):
671:    def test_selection_that_is_not_the_earliest_entry_fails(self, check):
679:    def test_missing_month_inside_the_observed_span_fails(self, check):
696:    def test_span_gap_check_still_fires_where_the_endpoint_expectation_cannot(self, check):
713:    def test_allowlist_cannot_silence_a_month_that_has_data(self, check):
729:    def test_reviewed_month_whose_raw_shape_changed_goes_back_for_review(self):
744:    def test_month_present_in_raw_but_missing_from_selection_fails(self, check):
755:    def test_allowlists_cannot_combine_to_excuse_a_dropped_month(self):
769:    def test_allowlists_cannot_combine_even_with_a_reviewed_shape(self):
782:    def test_a_month_cannot_be_in_both_allowlists(self):
795:    def test_known_missing_claim_is_checked_outside_the_selected_span_too(self):
807:    def test_truncated_feed_cannot_hide_behind_its_own_shrunken_span(self, check):
815:    def test_unreviewed_multi_entry_month_is_refused_not_guessed(self, check):
825:    def test_selection_contradicting_the_human_verified_date_fails(self):
837:    def test_a_reviewed_month_with_a_normal_revision_still_passes(self):
852:    def test_the_six_real_multi_entry_months_pass_on_the_real_feed(self):
1058:class TestFridayEstimandIsScopedHonestly:
1063:    def test_results_scope_the_claim_to_friday_and_disclose_the_non_neutrality(self):
1083:    def test_friday_estimand_pins_release_vs_session_and_names_the_good_fridays(self):
1109:    def test_no_live_artifact_describes_the_237_as_a_release_count(self):
1162:    def test_readme_does_not_sanction_a_pre_registration_claim(self):
1180:    def test_excluded_count_matches_the_weekday_breakdown(self):
1189:class TestReleaseMisbindingGateIsStructural:
1255:    def test_misbindings_are_caught(self, text):
1262:    def test_legitimate_lines_are_not_flagged(self, text):
1269:    def test_the_243_exemption_is_conditional_not_blanket(self):
1278:    def test_the_denial_exemption_is_clause_local_not_line_wide(self):
1285:    def test_the_gate_is_not_vacuous_on_the_live_tree(self):
   520	
   521	    def _is_literal_assignment(node):
   522	        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
   523	            return False
   524	        try:
   525	            ast.literal_eval(node.value)
   526	        except (ValueError, SyntaxError):
   527	            return False  # silent-ok: "is this a literal?" probe; a non-literal is the expected answer, not a failure
   528	        return True
   529	
   530	    src = K528_PY.read_text(encoding="utf-8")
   531	    tree = ast.parse(src)
   532	    keep = [
   533	        n for n in tree.body
   534	        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
   535	        or _is_literal_assignment(n)
   536	    ]
   537	    mod = types.ModuleType("k528_helpers")
   538	    exec(compile(ast.Module(body=keep, type_ignores=[]), "k528", "exec"), mod.__dict__)
   539	    # Guard the loader: if this ever silently stops loading what the tests need,
   540	    # the tests below would pass vacuously or error confusingly.
   541	    for required in ("check_calendar_is_complete", "KNOWN_MISSING_MONTHS",
   542	                     "REVIEWED_MULTI_ENTRY_MONTHS", "MAX_WINDOW_SHORTFALL_DAYS"):
   543	        assert hasattr(mod, required), f"_k528_module failed to load {required}"
   544	    return mod
   545	
   546	
   547	class TestControlGroupHasNoNfpDays:
   548	    """A real NFP session sitting in the control group is the exact failure this
   549	    experiment exists to document -- it just happened at 1/253 scale instead of
   550	    46/254, via an event dropped for lacking a pre-window but never removed from
   551	    the baseline."""
   552	
   553	    def test_every_mapped_nfp_session_is_excluded_from_the_control_group(self):
   554	        """Assert against an INDEPENDENTLY recorded total.
   555	
   556	        The first version of this test defined total = controls + mapped and
   557	        then asserted controls == total - mapped, which is an algebraic identity
   558	        that passes for any value of controls -- including the leaking 5087 it
   559	        was written to catch. A test that cannot fail is worse than no test: it
   560	        reads as coverage. (Codex v3 round-2 finding 3.)
   561	        """
   562	        sample = _load_k528(K528_RESULTS)["sample"]
   563	        audit = sample["event_mapping_audit"]
   564	        total = sample["total_trading_days"]
   565	        assert total == 5340, "pinned SPY session count for this sample window"
   566	        assert sample["non_nfp_trading_days"] == total - audit["n_mapped_to_sessions"] == 5086, (
   567	            "control group must exclude ALL mapped NFP sessions, not just the ones "
   568	            "that survived the event-window filter (5087 was the leaking value)"
   569	        )
   570	        assert sample["control_group_excludes_all_nfp_sessions"] is True
   571	
   572	    def test_proxy_side_control_group_is_also_clean(self):
   573	        """The same leak existed on the proxy side of the before/after audit:
   574	        the archive holds the proxy's ANALYSED events, not its NFP sessions.
   575	
   576	        Asserting `n_control_friday == 832` alone would not catch a regression
   577	        that re-leaks 2005-01-07 while dropping some other Friday -- the count
   578	        would still be 832. So reconstruct the property from the archived event
   579	        dates instead of restating a scalar. (Codex v3 round-3 finding 4.)
   580	        """
   581	        proxy = _load_k528(K528_DIR / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json")
   582	        archived = {e["date"] for e in proxy["event_data"]}
   583	
   584	        # 2005-01-07 is the proxy's January-2005 event: it is the first Friday of
   585	        # that month AND it is absent from the archive, because the proxy's own
   586	        # window buffer dropped it. That combination is what made it a leak.
   587	        assert "2005-01-07" not in archived
   588	        assert _first_friday(2005, 1).isoformat() == "2005-01-07"
   589	
   590	        before = _load_k528(K528_AUDIT)["items"]["vol_ratio_vs_friday"]["before"]
   591	        n_friday_events_archived = sum(
   592	            1 for d in archived if pd.Timestamp(d).weekday() == 4
   593	        )
   594	        assert before["n"] == n_friday_events_archived == 239
   595	
   596	        # DERIVE the control count from independently recorded inputs. Asserting
   597	        # 832 alone passes for a regression that re-leaks 2005-01-07 while
   598	        # wrongly excluding some other Friday.
   599	        der = before["control_derivation"]
   600	        assert der["n_fridays_in_sample"] == 1072, "pinned Friday count for this sample"
   601	        expected = (
   602	            der["n_fridays_in_sample"]
   603	            - der["n_friday_proxy_events"]
   604	            - der["n_reconstructed_friday_sessions"]
   605	        )
   606	        assert before["n_control_friday"] == expected == 832
   607	        assert der["reconstructed_sessions_excluded"] == ["2005-01-07"]
   608	        assert der["excluded_session_is_absent_from_controls"] is True
   609	
   610	    def test_proxy_before_column_uses_one_control_definition_throughout(self):
   611	        """A `before` object whose mean comes from the leaky archive while its
   612	        median comes from the leak-free rebuild is not any single estimand."""
   613	        before = _load_k528(K528_AUDIT)["items"]["vol_ratio_vs_all"]["before"]
   614	        assert "as_published" in before, "the leaky published values must be nested, not inlined"
   615	        assert before["p_value"] != before["as_published"]["p_value"], (
   616	            "if these match, the top-level fields are still the archive's leaky values"
   617	        )
   618	        assert before["n_control"] == 5085
   619	        assert before["as_published"]["n_control"] == 5086
   620	
   621	    def test_window_excluded_event_is_not_silently_analysed_or_kept_as_control(self):
   622	        audit = _load_k528(K528_RESULTS)["sample"]["event_mapping_audit"]
   623	        assert audit["n_valid_events"] + audit["n_excluded_for_window_buffer"] == \
   624	            audit["n_mapped_to_sessions"]
   625	        assert audit["window_excluded_dates"], "the partition must name what it dropped"
   626	
   627	
   628	class TestCalendarFailClosedCannotBeBypassed:
   629	    """Codex v3 finding 3: validating only the accessor's OUTPUT cannot work,
   630	    because the accessor collapses each month to one date before any check on
   631	    the output can look for an ambiguity."""
   632	
   633	    @pytest.fixture
   634	    def check(self):
   635	        return _k528_module().check_calendar_is_complete
   636	
   637	    def test_off_cycle_entry_earlier_in_the_month_is_refused_not_silently_picked(self, check):
   638	        """The bypass: an off-cycle entry filed EARLIER than the report. A
   639	        per-month min() takes it without complaint and the cadence still passes.
   640	        Only the reviewed-month allowlist catches this -- a day-gap threshold
   641	        cannot, because three of the six real cases are 3 days apart."""
   642	        # 5 days apart, so the gap gate lets it through: only the reviewed-month
   643	        # allowlist can catch an off-cycle item filed BEFORE the report.
   644	        with pytest.raises(RuntimeError, match="never been"):
   645	            check(
   646	                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
   647	                ["2024-01-05", "2024-02-01", "2024-02-06", "2024-03-08"],
   648	                "2024-01-01", "2024-03-31",
   649	            )
   650	
   651	    def test_real_multi_entry_gaps_are_too_small_for_a_gap_rule(self):
   652	        """Pin the fact that killed the gap heuristic: 2006-05, 2013-05 and
   653	        2020-05 have the revision exactly 3 days after the report. Any future
   654	        'revisions are filed weeks later' rule is wrong on the real feed."""
   655	        import json
   656	
   657	        raw = json.loads(
   658	            (REPO_ROOT / "tests" / "fixtures" / "fred_release_50_nfp_raw_20260719.json")
   659	            .read_text(encoding="utf-8")
   660	        )["release_dates"]
   661	        by_month = {}
   662	        for d in raw:
   663	            by_month.setdefault(d[:7], []).append(d)
   664	        gaps = {
   665	            m: (pd.Timestamp(sorted(v)[1]) - pd.Timestamp(sorted(v)[0])).days
   666	            for m, v in by_month.items() if len(v) > 1
   667	        }
   668	        assert min(gaps.values()) == 3, gaps
   669	        assert sorted(m for m, g in gaps.items() if g == 3) == ["2006-05", "2013-05", "2020-05"]
   670	
   671	    def test_selection_that_is_not_the_earliest_entry_fails(self, check):
   672	        with pytest.raises(RuntimeError, match="did not select the earliest"):
   673	            check(
   674	                pd.to_datetime(["2024-01-05", "2024-02-09", "2024-03-08"]),
   675	                ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
   676	                "2024-01-01", "2024-03-31",
   677	            )
   678	
   679	    def test_missing_month_inside_the_observed_span_fails(self, check):
   680	        """The old check exempted the first and last month unconditionally, so a
   681	        genuinely complete endpoint month could vanish for free.
   682	
   683	        Since the round-5 endpoint expectation landed, this scenario is caught by
   684	        that check first (2024-03's whole publication window sits inside the
   685	        requested window, so it is REQUIRED). Match either layer -- same reasoning
   686	        as test_allowlist_cannot_silence_a_month_that_has_data below: the point is
   687	        that it is caught, not which guard gets there first.
   688	        """
   689	        with pytest.raises(RuntimeError, match="missing 1 month|has no release for"):
   690	            check(
   691	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
   692	                ["2024-01-05", "2024-02-02", "2024-04-05"],
   693	                "2024-01-01", "2024-04-30",
   694	            )
   695	
   696	    def test_span_gap_check_still_fires_where_the_endpoint_expectation_cannot(self, check):
   697	        """Keep the span check under its own coverage rather than letting the new
   698	        layer silently inherit it.
   699	
   700	        The requested window here stops on 2024-03-10, so 2024-03's publication
   701	        window is NOT fully contained and the endpoint expectation correctly does
   702	        not require it. The month is still a hole inside the OBSERVED span
   703	        (2024-01..2024-04), and that is what this guard is for. If the span check
   704	        were ever deleted as redundant, this test goes red.
   705	        """
   706	        with pytest.raises(RuntimeError, match="missing 1 month"):
   707	            check(
   708	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
   709	                ["2024-01-05", "2024-02-02", "2024-04-05"],
   710	                "2024-01-01", "2024-03-10",
   711	            )
   712	
   713	    def test_allowlist_cannot_silence_a_month_that_has_data(self, check):
   714	        """KNOWN_MISSING_MONTHS is for real cancellations. If it is taken on
   715	        faith it is just a way to make a failing check pass."""
   716	        mod = _k528_module()
   717	        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
   718	        # Either guard is a correct refusal: the raw->selected check now fires
   719	        # first (2024-03 is in raw but not selected), and the `claims` check
   720	        # backs it up. Matching only one would make this test brittle about
   721	        # which layer catches it rather than about it being caught.
   722	        with pytest.raises(RuntimeError, match="does not|claims"):
   723	            mod.check_calendar_is_complete(
   724	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
   725	                ["2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05"],
   726	                "2024-01-01", "2024-04-30",
   727	            )
   728	
   729	    def test_reviewed_month_whose_raw_shape_changed_goes_back_for_review(self):
   730	        """The allowlist authorises the entry SET someone checked, not the month
   731	        name. A reviewed month that later gains an entry is a shape nobody
   732	        reviewed. (Codex v3 round-3 finding 2.)"""
   733	        mod = _k528_module()
   734	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
   735	            "raw": ["2024-02-02", "2024-02-09"], "report": "2024-02-02",
   736	        }
   737	        with pytest.raises(RuntimeError, match="no longer matches"):
   738	            mod.check_calendar_is_complete(
   739	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
   740	                ["2024-01-05", "2024-02-02", "2024-02-06", "2024-02-09", "2024-03-08"],
   741	                "2024-01-01", "2024-03-31",
   742	            )
   743	
   744	    def test_month_present_in_raw_but_missing_from_selection_fails(self, check):
   745	        """The near-boundary truncation the 70-day tolerance alone lets through:
   746	        raw has the month, the selection does not, and the observed span just
   747	        ends one month earlier while still looking continuous."""
   748	        with pytest.raises(RuntimeError, match="does not"):
   749	            check(
   750	                pd.to_datetime(["2024-01-05", "2024-02-02"]),
   751	                ["2024-01-05", "2024-02-02", "2024-03-08"],
   752	                "2024-01-01", "2024-03-31",
   753	            )
   754	
   755	    def test_allowlists_cannot_combine_to_excuse_a_dropped_month(self):
   756	        """Two independently reasonable lists that became a bypass together:
   757	        declare a tail month 'known missing' so the raw->selected check skips it,
   758	        and the counter-check that would catch the lie only looked inside the
   759	        selected span. (Codex v3 round-4 BLOCKER.)"""
   760	        mod = _k528_module()
   761	        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
   762	        with pytest.raises(RuntimeError, match="does not"):
   763	            mod.check_calendar_is_complete(
   764	                pd.to_datetime(["2024-01-05", "2024-02-02"]),
   765	                ["2024-01-05", "2024-02-02", "2024-03-08"],
   766	                "2024-01-01", "2024-03-31",
   767	            )
   768	
   769	    def test_allowlists_cannot_combine_even_with_a_reviewed_shape(self):
   770	        mod = _k528_module()
   771	        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
   772	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-03"] = {
   773	            "raw": ["2024-03-08", "2024-03-15"], "report": "2024-03-08",
   774	        }
   775	        with pytest.raises(RuntimeError, match="does not"):
   776	            mod.check_calendar_is_complete(
   777	                pd.to_datetime(["2024-01-05", "2024-02-02"]),
   778	                ["2024-01-05", "2024-02-02", "2024-03-08", "2024-03-15"],
   779	                "2024-01-01", "2024-03-31",
   780	            )
   781	
   782	    def test_a_month_cannot_be_in_both_allowlists(self):
   783	        mod = _k528_module()
   784	        mod.KNOWN_MISSING_MONTHS["2024-02"] = "fabricated"
   785	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
   786	            "raw": ["2024-02-02", "2024-02-09"], "report": "2024-02-02",
   787	        }
   788	        with pytest.raises(RuntimeError, match="both KNOWN_MISSING_MONTHS"):
   789	            mod.check_calendar_is_complete(
   790	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
   791	                ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
   792	                "2024-01-01", "2024-03-31",
   793	            )
   794	
   795	    def test_known_missing_claim_is_checked_outside_the_selected_span_too(self):
   796	        """A claim about a month beyond the observed span is exactly the one
   797	        nobody re-checks."""
   798	        mod = _k528_module()
   799	        mod.KNOWN_MISSING_MONTHS["2024-04"] = "fabricated"
   800	        with pytest.raises(RuntimeError, match="does not|claims"):
   801	            mod.check_calendar_is_complete(
   802	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
   803	                ["2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05"],
   804	                "2024-01-01", "2024-04-30",
   805	            )
   806	
   807	    def test_truncated_feed_cannot_hide_behind_its_own_shrunken_span(self, check):
   808	        """Anchoring the gap check on the OBSERVED span cannot catch truncation:
   809	        if the feed stops early the span shrinks with it and nothing looks
   810	        missing. Found by self-audit, not by a reviewer."""
   811	        dates = ["2024-01-05", "2024-02-02", "2024-03-08"]
   812	        with pytest.raises(RuntimeError, match="does not cover"):
   813	            check(pd.to_datetime(dates), dates, "2024-01-01", "2024-12-31")
   814	
   815	    def test_unreviewed_multi_entry_month_is_refused_not_guessed(self, check):
   816	        """'Earliest wins' cannot distinguish an off-cycle item filed BEFORE the
   817	        report from the report. A new multi-entry month must stop the run."""
   818	        with pytest.raises(RuntimeError, match="never been"):
   819	            check(
   820	                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
   821	                ["2024-01-05", "2024-02-01", "2024-02-06", "2024-03-08"],
   822	                "2024-01-01", "2024-03-31",
   823	            )
   824	
   825	    def test_selection_contradicting_the_human_verified_date_fails(self):
   826	        mod = _k528_module()
   827	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
   828	            "raw": ["2024-02-01", "2024-02-06"], "report": "2024-02-06",
   829	        }
   830	        with pytest.raises(RuntimeError, match="contradicts"):
   831	            mod.check_calendar_is_complete(
   832	                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
   833	                ["2024-01-05", "2024-02-01", "2024-02-06", "2024-03-08"],
   834	                "2024-01-01", "2024-03-31",
   835	            )
   836	
   837	    def test_a_reviewed_month_with_a_normal_revision_still_passes(self):
   838	        """The other half: a guard that rejects everything is as useless as one
   839	        that rejects nothing. A revision filed a week later, in a month someone
   840	        has checked against the BLS archive, must go through."""
   841	        mod = _k528_module()
   842	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = {
   843	            "raw": ["2024-02-02", "2024-02-09"], "report": "2024-02-02",
   844	        }
   845	        out = mod.check_calendar_is_complete(
   846	            pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
   847	            ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
   848	            "2024-01-01", "2024-03-31",
   849	        )
   850	        assert out["months_with_multiple_raw_entries"] == ["2024-02"]
   851	
   852	    def test_the_six_real_multi_entry_months_pass_on_the_real_feed(self):
   853	        """The strongest negative control available: the actual 264-entry ALFRED
   854	        feed, whose six duplicate months are exactly the reviewed ones."""
   855	        import json
   856	
   857	        mod = _k528_module()
   858	        raw = json.loads(
   859	            (REPO_ROOT / "tests" / "fixtures" / "fred_release_50_nfp_raw_20260719.json")
   860	            .read_text(encoding="utf-8")
   861	        )["release_dates"]
   862	        by_month = {}
   863	        for d in raw:
   864	            by_month.setdefault(d[:7], []).append(d)
   865	        sel = sorted(min(v) for v in by_month.values())
   866	        out = mod.check_calendar_is_complete(
   867	            pd.to_datetime(sel), raw, "2005-01-01", "2026-07-19"
   868	        )
   869	        assert out["months_with_multiple_raw_entries"] == sorted(
   870	            mod.REVIEWED_MULTI_ENTRY_MONTHS
   871	        )
   872	
   873	
   874	# ---------------------------------------------------------------------------
   875	# Round-7 N1: a STRUCTURAL detector for the 237-as-a-release-count misbinding.

2026-07-27T00:30:26.171121Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "nl -ba tests/test_nfp_official_release_dates.py | sed -n '1,105p'
nl -ba tests/test_nfp_official_release_dates.py | sed -n '400,520p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
     1	"""Pin the NFP event dates that a first-Friday proxy gets wrong.
     2	
     3	`experiments/event_article_nfp_2026_07_03_t1` used to derive its NFP release
     4	dates from a "first Friday of the month" rule. Against the official BLS
     5	Employment Situation calendar, 7 of its 13 historical events were on the wrong
     6	day, and correcting them flipped the headline direction: the SPY up-day rate
     7	went from 53.8% to 46.2% and both medians changed sign.
     8	
     9	The proxy never raised and never produced a NaN. It produced a complete,
    10	plausible, wrong table. These tests exist so that failure mode cannot come
    11	back silently. See experiments/k1442/related_event_date_audit.md.
    12	
    13	Network is mocked throughout: the point is to pin the calendar semantics, not
    14	to re-verify FRED's uptime. The fixture dates below are the real values
    15	returned by FRED release id 50 (Employment Situation), fetched 2026-07-19.
    16	"""
    17	
    18	from __future__ import annotations
    19	
    20	import importlib.util
    21	import re
    22	from datetime import date, timedelta
    23	from pathlib import Path
    24	
    25	import pandas as pd
    26	import pytest
    27	
    28	from volpred.data import event_dates
    29	
    30	REPO_ROOT = Path(__file__).resolve().parents[1]
    31	EXPERIMENT_DIR = REPO_ROOT / "experiments" / "event_article_nfp_2026_07_03_t1"
    32	EXPERIMENT_PY = EXPERIMENT_DIR / "event_article_nfp_2026_07_03_t1.py"
    33	
    34	# Official Employment Situation release dates, FRED release id 50.
    35	OFFICIAL_2024_2026 = [
    36	    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03",
    37	    "2024-06-07", "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04",
    38	    "2024-11-01", "2024-12-06",
    39	    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-02",
    40	    "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05",
    41	    # No October 2025 release: the shutdown cancelled it and pushed the
    42	    # September report to 2025-11-20.
    43	    "2025-11-20", "2025-12-16",
    44	    "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08",
    45	    "2026-06-05", "2026-07-02",
    46	]
    47	
    48	# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
    49	# `None` means the proxy invented an event that does not exist.
    50	PROXY_MISMATCHES = [
    51	    ("2025-07-04", "2025-07-03"),  # proxy landed on the closed July 4 holiday
    52	    ("2025-10-03", None),          # phantom: no Employment Situation in Oct 2025
    53	    ("2025-11-07", "2025-11-20"),  # shutdown backlog
    54	    ("2025-12-05", "2025-12-16"),
    55	    ("2026-01-02", "2026-01-09"),
    56	    ("2026-02-06", "2026-02-11"),
    57	    ("2026-05-01", "2026-05-08"),
    58	]
    59	
    60	# The 6 the proxy happened to get right. Pinned so a "fix" that shifts every
    61	# date is caught too -- the proxy is not wrong everywhere, it is wrong at the
    62	# holiday and shutdown boundaries.
    63	PROXY_CORRECT = [
    64	    "2025-06-06", "2025-08-01", "2025-09-05",
    65	    "2026-03-06", "2026-04-03", "2026-06-05",
    66	]
    67	
    68	# What the experiment must use: trailing 13 official releases before 2026-07-02.
    69	EXPECTED_TRAILING_13 = [
    70	    "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05",
    71	    "2025-11-20", "2025-12-16", "2026-01-09", "2026-02-11", "2026-03-06",
    72	    "2026-04-03", "2026-05-08", "2026-06-05",
    73	]
    74	
    75	
    76	def _first_friday(year: int, month: int) -> date:
    77	    """The proxy this module exists to keep out of the codebase."""
    78	    d = date(year, month, 1)
    79	    return d + timedelta(days=(4 - d.weekday()) % 7)
    80	
    81	
    82	@pytest.fixture(autouse=True)
    83	def isolate_event_date_cache(monkeypatch, tmp_path):
    84	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
    85	
    86	
    87	@pytest.fixture
    88	def official(monkeypatch):
    89	    monkeypatch.setattr(
    90	        event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
    91	    )
    92	    return event_dates.nfp_release_dates("2024-01-01", "2026-07-02", use_cache=False)
    93	
    94	
    95	@pytest.fixture(scope="module")
    96	def experiment():
    97	    spec = importlib.util.spec_from_file_location(
    98	        "nfp_t1_experiment", EXPERIMENT_PY
    99	    )
   100	    module = importlib.util.module_from_spec(spec)
   101	    spec.loader.exec_module(module)
   102	    return module
   103	
   104	
   105	class TestProxyMismatches:
   400	
   401	
   402	class TestK528UsesOfficialCalendar:
   403	    def test_defines_no_first_friday_helper(self):
   404	        src = K528_PY.read_text(encoding="utf-8")
   405	        assert "def get_first_friday" not in src
   406	        assert "def generate_nfp_dates" not in src
   407	        assert "(4 - first_day.weekday()) % 7" not in src
   408	
   409	    def test_imports_the_official_calendar(self):
   410	        """Match the import target, not the whole line: the script also imports
   411	        _fetch/RELEASE_IDS to validate the unselected feed, and pinning the exact
   412	        line text would fail on that without anything being wrong."""
   413	        src = K528_PY.read_text(encoding="utf-8")
   414	        assert "from volpred.data.event_dates import" in src
   415	        assert "nfp_release_dates" in src
   416	
   417	    def test_results_declare_the_official_source_and_no_fallback(self):
   418	        source = _load_k528(K528_RESULTS)["event_date_source"]
   419	        assert "nfp_release_dates" in source["accessor"]
   420	        assert source["fallback"] == "none - the run raises if the calendar is unreachable"
   421	
   422	    def test_event_dates_carry_no_proxy_signature(self):
   423	        assert_not_first_friday_proxy(_k528_event_dates())
   424	
   425	    def test_sample_is_not_uniformly_friday(self):
   426	        """237 of 253, not 253 of 253. The gap is the corrected dates."""
   427	        results = _load_k528(K528_RESULTS)
   428	        n, on_friday = results["sample"]["total_nfp_events"], results["sample"]["nfp_days_on_friday"]
   429	        assert n == 253
   430	        assert on_friday == 237
   431	        assert on_friday < n
   432	
   433	    def test_audit_records_the_dates_that_changed(self):
   434	        diff = _load_k528(K528_AUDIT)["calendar_diff"]
   435	        assert diff["dates_in_common"] == 212
   436	        # The near-equal sample sizes hide a date swap; assert the swap, not the
   437	        # count, or a silent revert reads as unchanged.
   438	        assert len(diff["proxy_only_dates"]) == 42
   439	        assert len(diff["official_only_dates"]) == 41
   440	        assert "2025-10-03" in diff["proxy_only_dates"]
   441	        assert "2025-11-20" in diff["official_only_dates"]
   442	
   443	    def test_no_off_cycle_revision_date_is_treated_as_an_event(self):
   444	        """Direct pin on the k528 Codex v2 BLOCKER.
   445	
   446	        For six months ALFRED returns two release-id-50 entries; the later one
   447	        is a seasonal-factor/benchmark revision, not the Employment Situation.
   448	        An earlier rerun selected those six and moved the NFP-vs-Friday test
   449	        across the 5% line. Assert on the ARTIFACT, not just on the accessor:
   450	        the accessor being right does not prove the shipped results used it.
   451	        """
   452	        event_dates = {str(d.date()) for d in _k528_event_dates()}
   453	        off_cycle = {
   454	            "2006-05-08", "2012-12-12", "2013-05-06",
   455	            "2020-05-11", "2024-01-10", "2024-08-21",
   456	        }
   457	        regular = {
   458	            "2006-05-05", "2012-12-07", "2013-05-03",
   459	            "2020-05-08", "2024-01-05", "2024-08-02",
   460	        }
   461	        assert not (event_dates & off_cycle), (
   462	            f"off-cycle revision dates present in k528 event set: "
   463	            f"{sorted(event_dates & off_cycle)}"
   464	        )
   465	        assert regular <= event_dates, (
   466	            f"regular releases missing from k528 event set: {sorted(regular - event_dates)}"
   467	        )
   468	
   469	
   470	class TestProxyMutationIsCaught:
   471	    """Mutation test. Reverting to the proxy must turn the suite red, and the
   472	    only way to know that is to build the proxy calendar and watch the guard
   473	    reject it."""
   474	
   475	    @staticmethod
   476	    def _proxy_calendar(start_year=2005, end_year=2026, end_month=3):
   477	        out = []
   478	        for year in range(start_year, end_year + 1):
   479	            last = 12 if year < end_year else end_month
   480	            for month in range(1, last + 1):
   481	                out.append(pd.Timestamp(_first_friday(year, month)))
   482	        return pd.DatetimeIndex(out)
   483	
   484	    def test_the_proxy_calendar_is_rejected(self):
   485	        with pytest.raises(AssertionError, match="Friday"):
   486	            assert_not_first_friday_proxy(self._proxy_calendar())
   487	
   488	    def test_phantom_october_2025_alone_is_enough_to_fail(self):
   489	        """A partial revert that keeps some real dates still gets caught."""
   490	        mixed = pd.DatetimeIndex(
   491	            _k528_event_dates() + [pd.Timestamp("2025-10-03")]
   492	        )
   493	        with pytest.raises(AssertionError, match="October 2025"):
   494	            assert_not_first_friday_proxy(mixed)
   495	
   496	    def test_the_guard_accepts_the_official_calendar(self, official):
   497	        """The other half of the mutation test: the guard must not reject
   498	        everything. A guard that always fails is as useless as one that never
   499	        does."""
   500	        assert_not_first_friday_proxy(official)
   501	
   502	
   503	# ---------------------------------------------------------------------------
   504	# Holes found by Codex v3 against commit 6fd281901. Each of these shipped once
   505	# with a green suite, so each gets an assertion rather than a comment.
   506	# ---------------------------------------------------------------------------
   507	
   508	
   509	def _k528_module():
   510	    """Load the k528 script's functions and literal constants without running
   511	    the analysis body (which downloads data and would need a live API key).
   512	
   513	    Constants are selected by "is it a literal?", not by a hand-maintained name
   514	    list. The name-list version silently dropped every constant added after it
   515	    was written, and a helper that quietly omits what it is supposed to load
   516	    makes the tests exercise something other than the production code path.
   517	    """
   518	    import ast
   519	    import types
   520	

2026-07-27T00:30:34.132276Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "jq '{sample, main_results, regime_analysis, statistical_tests: {A_nfp_vs_all_welch:.statistical_tests.A_nfp_vs_all_welch,B_nfp_vs_friday:.statistical_tests.B_nfp_vs_friday,E_vix_pearson:.statistical_tests.E_vix_pearson,E_vix_spearman:.statistical_tests.E_vix_spearman,H_vix_regime_welch:.statistical_tests.H_vix_regime_welch}, event0:.event_data[0]}' experiments/k528/k528_nfp_event_study_results.json
jq '[.event_data[] | keys] | unique' experiments/k528/k528_nfp_event_study_results.json" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
{
  "sample": {
    "total_nfp_events": 253,
    "date_range": "2005-02-04 to 2026-03-06",
    "non_nfp_trading_days": 5086,
    "friday_baseline_days": 834,
    "nfp_days_on_friday": 237,
    "nfp_releases_dated_friday": 243,
    "event_mapping_audit": {
      "n_official_releases": 254,
      "n_mapped_to_sessions": 254,
      "n_shifted_to_next_session": 6,
      "n_outside_price_sample": 0,
      "outside_price_sample_dates": [],
      "n_excluded_for_window_buffer": 1,
      "window_excluded_dates": [
        "2005-01-07"
      ],
      "n_valid_events": 253
    },
    "calendar_completeness": {
      "n_months_in_span": 255,
      "n_raw_entries": 260,
      "months_with_multiple_raw_entries": [
        "2006-05",
        "2012-12",
        "2013-05",
        "2020-05",
        "2024-01",
        "2024-08"
      ],
      "reviewed_multi_entry_months": {
        "2006-05": {
          "raw": [
            "2006-05-05",
            "2006-05-08"
          ],
          "report": "2006-05-05"
        },
        "2012-12": {
          "raw": [
            "2012-12-07",
            "2012-12-12"
          ],
          "report": "2012-12-07"
        },
        "2013-05": {
          "raw": [
            "2013-05-03",
            "2013-05-06"
          ],
          "report": "2013-05-03"
        },
        "2020-05": {
          "raw": [
            "2020-05-08",
            "2020-05-11"
          ],
          "report": "2020-05-08"
        },
        "2024-01": {
          "raw": [
            "2024-01-05",
            "2024-01-10"
          ],
          "report": "2024-01-05"
        },
        "2024-08": {
          "raw": [
            "2024-08-02",
            "2024-08-21"
          ],
          "report": "2024-08-02"
        }
      },
      "ambiguity_gap_threshold_days": 3,
      "known_missing_months": {
        "2025-10": "Federal government shutdown. ALFRED shows no release id 50 entry between 2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed September report landed on 11-20. Same shutdown that cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py. The first-Friday proxy INVENTED an event here -- that phantom is one of the reasons for this rerun."
      },
      "window_coverage": {
        "requested": "2005-01-01..2026-03-27",
        "observed": "2005-01-07..2026-03-06",
        "head_shortfall_days": 6,
        "tail_shortfall_days": 21,
        "tolerance_days": 70
      },
      "endpoint_expectation": {
        "derived_from": "requested window only -- never from the feed",
        "latest_observed_release_day_of_month": 22,
        "n_required_months": 255,
        "required_first_month": "2005-01",
        "required_last_month": "2026-03",
        "excused_by_known_missing": [
          "2025-10"
        ],
        "why": "Codex round-5 B2: deleting an endpoint month from the raw feed and the selection together left every feed-relative check self-consistent (259 raw / 253 selected, shortfall inside the 70d tolerance) and the sample silently shortened. The requested window is the one fact a truncated feed cannot edit."
      },
      "residual_limitation": "Two heuristics remain. (1) Same-month selection uses 'earliest wins', which cannot distinguish an off-cycle item filed BEFORE the report from the report itself, so every multi-entry month must additionally appear in REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A new multi-entry month fails the run rather than being assumed. (2) The endpoint expectation can still be silenced by adding a required month to KNOWN_MISSING_MONTHS. That is deliberate -- 2025-10 really was cancelled -- and it is bounded by check 4, which verifies against the RAW feed that a claimed hole is a real hole. What remains uncovered is a month deleted from the raw feed AND declared missing in writing: a documented false claim, not a silent truncation. This gate is fail-closed against the latter, not the former."
    },
    "price_coverage": {
      "SPY": {
        "ticker": "SPY",
        "n_rows": 5341,
        "observed": "2005-01-03..2026-03-26",
        "head_shortfall_days": 2,
        "tail_shortfall_days": 1,
        "tolerance_days": 10
      },
      "^VIX": {
        "ticker": "^VIX",
        "n_rows": 5341,
        "observed": "2005-01-03..2026-03-26",
        "head_shortfall_days": 2,
        "tail_shortfall_days": 1,
        "tolerance_days": 10
      },
      "vix_forward_fill": {
        "n_sessions_without_native_vix": 0,
        "max_consecutive_ffill_trading_days": 0,
        "limit_trading_days": 3
      }
    },
    "friday_estimand": {
      "filter": "session weekday == Friday",
      "estimand": "Among trading sessions falling on a Friday, do the sessions that absorb an NFP release show larger |return| than those that do not? This is a claim about the session that trades the news, NOT about releases dated a Friday.",
      "n_events_total": 253,
      "n_release_date_on_friday": 243,
      "n_traded_in_friday_session": 237,
      "friday_releases_absorbed_by_a_later_session": {
        "n": 6,
        "dates": [
          {
            "release_date": "2007-04-06",
            "session_date": "2007-04-09",
            "session_weekday": 0,
            "event_abs_return": 0.0013864117187798453
          },
          {
            "release_date": "2010-04-02",
            "session_date": "2010-04-05",
            "session_weekday": 0,
            "event_abs_return": 0.008149637494278661
          },
          {
            "release_date": "2012-04-06",
            "session_date": "2012-04-09",
            "session_weekday": 0,
            "event_abs_return": 0.01123175066081461
          },
          {
            "release_date": "2015-04-03",
            "session_date": "2015-04-06",
            "session_weekday": 0,
            "event_abs_return": 0.0067330498943227735
          },
          {
            "release_date": "2021-04-02",
            "session_date": "2021-04-05",
            "session_weekday": 0,
            "event_abs_return": 0.01435326530305181
          },
          {
            "release_date": "2023-04-07",
            "session_date": "2023-04-10",
            "session_weekday": 0,
            "event_abs_return": 0.0010262812061787585
          }
        ],
        "mean_abs_return": 0.007146732712904409,
        "why_excluded": "Every one is a Good Friday: BLS published, the market was shut, the news is absorbed by the following Monday. Their returns are Monday returns and cannot enter a comparison whose control group is pure Friday without reintroducing the weekday confound the restriction exists to remove."
      },
      "why_session_and_not_release_weekday": "The measured quantity is a session return and the confound held fixed is the day-of-week effect of that session. Filtering on release weekday would place these Monday returns against a Friday-only control group.",
      "what_this_does_not_identify": "Not 'NFP in general' (the sample is conditioned on Friday sessions) and not 'releases dated a Friday' (six such releases are traded on a Monday and excluded)."
    },
    "total_trading_days": 5340,
    "control_group_excludes_all_nfp_sessions": true
  },
  "main_results": {
    "nfp_avg_abs_return": 0.008453064404674977,
    "nfp_avg_abs_return_pct": "0.845%",
    "non_nfp_avg_abs_return": 0.007630637836355491,
    "non_nfp_avg_abs_return_pct": "0.763%",
    "friday_baseline_abs_return": 0.007183325954343319,
    "vol_ratio_vs_all": 1.107779531142352,
    "vol_ratio_vs_friday": 1.188994637894018
  },
  "regime_analysis": {
    "vix_median_split": 16.690000534057617,
    "high_vix_nfp_abs_return": 0.011276193504303303,
    "low_vix_nfp_abs_return": 0.005562180206655571,
    "n_high": 128,
    "n_low": 125,
    "t_stat": 6.169072114785661,
    "p_value": 4.551849137823982E-9,
    "multiplicity": {
      "family": "confirmatory",
      "p_nominal": 4.551849137823982E-9,
      "p_holm_all_outputs_family": 9.558883189430362E-8,
      "p_holm_confirmatory_family": 2.275924568911991E-8,
      "how_to_report": "Nominal, then Holm within the declared confirmatory family."
    }
  },
  "statistical_tests": {
    "A_nfp_vs_all_welch": null,
    "B_nfp_vs_friday": {
      "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
      "estimand": "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event group is restricted to NFP releases that trade on a Friday, and the 16 non-Friday events are excluded rather than compared against a pure-Friday control group.",
      "claim_scope": "This identifies the effect of an NFP release ABSORBED BY A FRIDAY SESSION. It does not license a statement about NFP releases in general -- the excluded events are quieter, so the restriction raises the ratio relative to the mixed-weekday spec -- and it is NOT a statement about releases DATED a Friday, six of which are Good Fridays traded the following Monday and therefore excluded. Any prose quoting this number must say 'NFP traded in a Friday session', not 'NFP' and not 'NFP released on a Friday'.",
      "restriction_is_not_neutral": {
        "excluded_mean_abs_return": 0.007151465777403401,
        "friday_mean_abs_return": 0.008540936041959135,
        "excluded_are_quieter_by_pct": 16.268360490345206
      },
      "n_event": 237,
      "n_control": 834,
      "vol_ratio": 1.188994637894018,
      "t_stat": 2.320508726692989,
      "p_value": 0.020854283650821093,
      "significant_5pct": true,
      "excluded_non_friday_events": {
        "n": 16,
        "mean_abs_return": 0.007151465777403401
      },
      "multiplicity": {
        "family": "confirmatory",
        "p_nominal": 0.020854283650821093,
        "p_holm_all_outputs_family": 0.37537710571477967,
        "p_holm_confirmatory_family": 0.041708567301642185,
        "how_to_report": "Nominal, then Holm within the declared confirmatory family."
      }
    },
    "E_vix_pearson": null,
    "E_vix_spearman": null,
    "H_vix_regime_welch": null
  },
  "event0": {
    "date": "2005-02-04",
    "session_date": "2005-02-04",
    "release_date": "2005-02-04",
    "year": 2005,
    "month": 2,
    "weekday": 4,
    "session_weekday": 4,
    "release_weekday": 4,
    "session_shifted_from_release": false,
    "event_return": 0.010675868401005317,
    "event_abs_return": 0.010675868401005317,
    "pre_avg_abs_return": 0.003637957704953454,
    "post_avg_abs_return": 0.004438186201365446,
    "pre_vix": 11.789999961853027,
    "event_vix": 11.210000038146973,
    "post_vix_1d": 11.729999542236328,
    "vix_change_event": -0.5799999237060547,
    "high_low_range": 0.012060192196264896,
    "volume_ratio": 0.9459350091597117
  }
}
[
  [
    "date",
    "event_abs_return",
    "event_return",
    "event_vix",
    "high_low_range",
    "month",
    "post_avg_abs_return",
    "post_vix_1d",
    "pre_avg_abs_return",
    "pre_vix",
    "release_date",
    "release_weekday",
    "session_date",
    "session_shifted_from_release",
    "session_weekday",
    "vix_change_event",
    "volume_ratio",
    "weekday",
    "year"
  ]
]

2026-07-27T00:30:43.825194Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "jq '.statistical_tests | keys' experiments/k528/k528_nfp_event_study_results.json
jq '.statistical_tests' experiments/k528/k528_nfp_event_study_results.json" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
[
  "A_nfp_vs_all",
  "B_diagnostic_mixed_weekday",
  "B_nfp_vs_friday",
  "C_wilcoxon",
  "D_vol_crush",
  "E_vix_predictive",
  "F_vix_buildup"
]
{
  "A_nfp_vs_all": {
    "test": "Welch t-test",
    "t_stat": 1.5938775781634782,
    "p_value": 0.11206360938619585,
    "significant_5pct": false,
    "multiplicity": {
      "family": "confirmatory",
      "p_nominal": 0.11206360938619585,
      "p_holm_all_outputs_family": 1.0,
      "p_holm_confirmatory_family": 0.11206360938619585,
      "how_to_report": "Nominal, then Holm within the declared confirmatory family."
    }
  },
  "B_nfp_vs_friday": {
    "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
    "estimand": "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event group is restricted to NFP releases that trade on a Friday, and the 16 non-Friday events are excluded rather than compared against a pure-Friday control group.",
    "claim_scope": "This identifies the effect of an NFP release ABSORBED BY A FRIDAY SESSION. It does not license a statement about NFP releases in general -- the excluded events are quieter, so the restriction raises the ratio relative to the mixed-weekday spec -- and it is NOT a statement about releases DATED a Friday, six of which are Good Fridays traded the following Monday and therefore excluded. Any prose quoting this number must say 'NFP traded in a Friday session', not 'NFP' and not 'NFP released on a Friday'.",
    "restriction_is_not_neutral": {
      "excluded_mean_abs_return": 0.007151465777403401,
      "friday_mean_abs_return": 0.008540936041959135,
      "excluded_are_quieter_by_pct": 16.268360490345206
    },
    "n_event": 237,
    "n_control": 834,
    "vol_ratio": 1.188994637894018,
    "t_stat": 2.320508726692989,
    "p_value": 0.020854283650821093,
    "significant_5pct": true,
    "excluded_non_friday_events": {
      "n": 16,
      "mean_abs_return": 0.007151465777403401
    },
    "multiplicity": {
      "family": "confirmatory",
      "p_nominal": 0.020854283650821093,
      "p_holm_all_outputs_family": 0.37537710571477967,
      "p_holm_confirmatory_family": 0.041708567301642185,
      "how_to_report": "Nominal, then Holm within the declared confirmatory family."
    }
  },
  "B_diagnostic_mixed_weekday": {
    "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
    "status": "DIAGNOSTIC ONLY - do not quote",
    "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
    "vol_ratio": 1.176761914801308,
    "t_stat": 2.2390202914235586,
    "p_value": 0.025692059659997518,
    "significant_5pct": true
  },
  "C_wilcoxon": {
    "test": "Mann-Whitney U (one-sided)",
    "u_stat": 712488.0,
    "p_value": 0.0019382600522027216,
    "significant_5pct": true,
    "multiplicity": {
      "family": "confirmatory",
      "p_nominal": 0.0019382600522027216,
      "p_holm_all_outputs_family": 0.03682694099185171,
      "p_holm_confirmatory_family": 0.005814780156608164,
      "how_to_report": "Nominal, then Holm within the declared confirmatory family."
    }
  },
  "D_vol_crush": {
    "test": "One-sample t-test (post-pre diff)",
    "pre_avg": 0.0077870216597641945,
    "post_avg": 0.007687356861391357,
    "diff": -0.00009966479837283827,
    "t_stat": -0.3106840360357029,
    "p_value": 0.7562976513767368,
    "vol_crush_present": false,
    "multiplicity": {
      "family": "exploratory",
      "p_nominal": 0.7562976513767368,
      "p_holm_all_outputs_family": 1.0,
      "p_holm_confirmatory_family": null,
      "how_to_report": "EXPLORATORY -- nominal p reported for description only; not quotable as a 5% finding."
    }
  },
  "E_vix_predictive": {
    "test": "Pearson + Spearman correlation",
    "pearson_r": 0.44043638429674903,
    "pearson_p": 1.9817089060479586E-13,
    "spearman_rho": 0.3455048873701663,
    "spearman_p": 1.6699985504624933E-8,
    "slope": 0.0004256184186836176,
    "interpretation": "1pt VIX → 0.0426% more |return|",
    "multiplicity": {
      "family": "confirmatory",
      "pearson": {
        "p_nominal": 1.9817089060479586E-13,
        "p_holm_confirmatory_family": 1.1890253436287752E-12,
        "p_holm_all_outputs_family": 4.359759593305509E-12
      },
      "spearman": {
        "p_nominal": 1.6699985504624933E-8,
        "p_holm_confirmatory_family": 6.679994201849973E-8,
        "p_holm_all_outputs_family": 3.3399971009249865E-7
      }
    }
  },
  "F_vix_buildup": {
    "test": "One-sample t-test (T-5 to T-1 VIX change)",
    "mean_change": 0.08312253989721004,
    "t_stat": 0.44978438962865197,
    "p_value": 0.653252559944604,
    "anticipatory_buildup": false,
    "multiplicity": {
      "family": "exploratory",
      "p_nominal": 0.653252559944604,
      "p_holm_all_outputs_family": 1.0,
      "p_holm_confirmatory_family": null,
      "how_to_report": "EXPLORATORY -- nominal p reported for description only; not quotable as a 5% finding."
    }
  }
}

2026-07-27T00:30:48.289496Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "rg -n 'nfp_dates|release_date|session_date|all_nfp|non_nfp|friday|ttest|pearson|spearman|vix_median|default_rng|np.random|random_state|seed|bootstrap|event_data|multiplicity|n_claims' experiments/k528/k528_nfp_event_study.py | sed -n '1,260p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
32:if that calendar is unreachable -- `get_first_friday` is gone, not deprecated.
61:from volpred.data.event_dates import RELEASE_IDS, _fetch, nfp_release_dates
469:def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
477:    dates = nfp_release_dates(start, end)
605:nfp_calendar, calendar_completeness = load_nfp_dates()
610:n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
612:      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
705:friday_release_nonfriday_session = sorted(
769:        # still lines up. `release_date` is when BLS published. They differ for the
770:        # six Good Friday releases; see friday_estimand in the results JSON.
772:        "session_date": nfp_date.strftime("%Y-%m-%d"),
773:        "release_date": release_ts.strftime("%Y-%m-%d"),
815:non_nfp_mask = ~spy.index.isin(nfp_set)
816:non_nfp = spy[non_nfp_mask]
817:n_leaked = len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask]))
821:baseline_abs_return = float(non_nfp["AbsReturn"].mean())
822:baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
823:baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
837:friday_mask = non_nfp.index.weekday == 4
838:friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
839:friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
843:print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
851:non_nfp_abs_returns = non_nfp["AbsReturn"].values
852:friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
855:t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
856:vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
894:nfp_friday_mask = (df["weekday"] == 4).values
895:nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
896:nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
898:t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
899:vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())
905:t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
906:    nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
907:vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
911:_n_release_friday = int((df["release_weekday"] == 4).sum())
912:_n_session_friday = int((df["session_weekday"] == 4).sum())
914:friday_estimand = {
922:    "n_release_date_on_friday": _n_release_friday,
923:    "n_traded_in_friday_session": _n_session_friday,
924:    "friday_releases_absorbed_by_a_later_session": {
928:                "release_date": r["release_date"],
929:                "session_date": r["session_date"],
953:if _n_release_friday - _n_session_friday != len(_gf):
960:u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
964:t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
974:    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
975:    # also spearman
976:    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
990:t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)
1001:            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
1002:            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
1006:vix_median = df["pre_vix"].median()
1007:high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
1008:low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
1009:t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)
1016:t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)
1060:    ("B_nfp_vs_friday_welch", float(p_val_fri)),
1062:    ("E_vix_pearson", float(p_vix)),
1063:    ("E_vix_spearman", float(p_rho_vix)),
1085:_b_idx = [n for n, _ in confirmatory].index("B_nfp_vs_friday_welch")
1086:_b_all_idx = [n for n, _ in all_outputs].index("B_nfp_vs_friday_welch")
1088:multiplicity = {
1115:    "headline_friday_test": {
1151:print(f"  Friday NFP |return|:  {nfp_friday_abs.mean():.6f} (n={len(nfp_friday_abs)})")
1152:print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
1157:print(f"  [excluded] non-Friday NFP events: n={len(nfp_nonfriday_abs)}, "
1158:      f"mean |ret|={nfp_nonfriday_abs.mean():.6f}" if len(nfp_nonfriday_abs) else "  [excluded] none")
1200:print(f"  VIX median split:     {vix_median:.1f}")
1222:non_nfp_range = float(((spy["High"] - spy["Low"]) / spy["Close"])[non_nfp_mask].mean())
1223:range_ratio = nfp_range / non_nfp_range
1225:print(f"  Non-NFP range:        {non_nfp_range:.6f} ({non_nfp_range*100:.3f}%)")
1272:    f"multiplicity correction -- the family-adjusted values live in `multiplicity` and "
1274:    f"n={len(nfp_friday_abs)} vs {len(friday_non_nfp_abs)}). Scoped to the releases "
1276:    f"{_n_release_friday} are dated a Friday but only {_n_session_friday} trade in one, "
1278:    f"Monday. The {len(nfp_nonfriday_abs)} excluded events are quieter, so this "
1351:proxy_events = proxy["event_data"]
1386:proxy_non_nfp = spy[~spy.index.isin(proxy_all_sessions)]
1387:proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
1388:proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
1398:proxy_non_nfp_archive = spy[~spy.index.isin(set(proxy_event_dates))]
1399:proxy_non_nfp_abs_archive = proxy_non_nfp_archive["AbsReturn"].values
1401:if len(proxy_non_nfp_archive) - len(proxy_non_nfp) != len(_proxy_extra_sessions):
1411:proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
1412:_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
1413:proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
1417:_p_t_all, _p_p_all = stats.ttest_ind(proxy_nfp_abs, proxy_non_nfp_abs, equal_var=False)
1418:proxy_ratio_all_clean = float(proxy_nfp_abs.mean() / proxy_non_nfp_abs.mean())
1422:_p_thr = proxy["regime_analysis"]["vix_median_split"]
1433:    ("baseline mean", proxy_non_nfp_abs_archive.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
1464:        "baseline_mean": float(proxy_non_nfp_abs.mean()),
1468:        "n_control": int(len(proxy_non_nfp_abs)),
1469:        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
1470:        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
1473:            "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
1476:            "n_control": int(len(proxy_non_nfp_abs_archive)),
1491:        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
1492:        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
1500:    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
1506:        "n": int(len(proxy_nfp_friday_abs)),
1507:        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
1508:        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
1509:        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
1510:        "n_control_friday": int(len(proxy_fri_abs)),
1515:            "n_fridays_in_sample": int((spy.index.weekday == 4).sum()),
1516:            "n_friday_proxy_events": int((_p_weekday == 4).sum()),
1518:            "n_reconstructed_friday_sessions": int(
1522:                not set(_proxy_extra_sessions) & set(proxy_non_nfp.index)
1527:            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
1528:            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
1529:            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
1543:        "n": int(len(nfp_friday_abs)),
1544:        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
1545:        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
1546:        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
1603:        "pearson_r": proxy_e["pearson_r"],
1604:        "pearson_p": proxy_e["pearson_p"],
1605:        "spearman_rho": proxy_e["spearman_rho"],
1606:        "spearman_p": proxy_e["spearman_p"],
1609:        "significant_5pct": proxy_e["pearson_p"] < 0.05,
1612:        "pearson_r": float(r_vix),
1613:        "pearson_p": float(p_vix),
1614:        "spearman_rho": float(rho_vix),
1615:        "spearman_p": float(p_rho_vix),
1626:proxy_thr = proxy_reg["vix_median_split"]
1628:    "vix_median_threshold", "VIX median split (article: 16.71)",
1635:        "threshold": float(vix_median),
1637:        "places_20260701_vix_1659_in": "low" if 16.59 < float(vix_median) else "high",
1642:proxy_dates = {r["date"] for r in proxy["event_data"]}
1649:        "non_nfp_trading_days": proxy["sample"]["non_nfp_trading_days"],
1654:        "non_nfp_trading_days": int(non_nfp_mask.sum()),
1677:    for field in ("mean_ratio", "median_ratio", "pearson_r", "threshold", "n"):
1687:    if key == "vix_median_threshold" and b["places_20260701_vix_1659_in"] != a["places_20260701_vix_1659_in"]:
1696:    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
1720:        "accessor": "volpred.data.event_dates.nfp_release_dates",
1727:        "non_nfp_trading_days": int(non_nfp_mask.sum()),
1728:        "friday_baseline_days": int(friday_mask.sum()),
1729:        "nfp_days_on_friday": int((df["session_weekday"] == 4).sum()),
1730:        "nfp_releases_dated_friday": int((df["release_weekday"] == 4).sum()),
1734:        "friday_estimand": friday_estimand,
1739:        "control_group_excludes_all_nfp_sessions": bool(
1740:            len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask])) == 0
1746:        "non_nfp_avg_abs_return": baseline_abs_return,
1747:        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
1748:        "friday_baseline_abs_return": friday_baseline,
1750:        "vol_ratio_vs_friday": vol_ratio_fri,
1759:        "B_nfp_vs_friday": {
1764:                f"{int(len(nfp_nonfriday_abs))} non-Friday events are excluded rather "
1778:                "excluded_mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
1779:                "friday_mean_abs_return": float(nfp_friday_abs.mean()),
1781:                    float((nfp_friday_abs.mean() - nfp_nonfriday_abs.mean()) / nfp_friday_abs.mean() * 100)
1782:                    if len(nfp_nonfriday_abs) else None
1785:            "n_event": int(len(nfp_friday_abs)),
1786:            "n_control": int(len(friday_non_nfp_abs)),
1791:            "excluded_non_friday_events": {
1792:                "n": int(len(nfp_nonfriday_abs)),
1793:                "mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
1828:            "pearson_r": float(r_vix) if r_vix else None,
1829:            "pearson_p": float(p_vix) if p_vix else None,
1830:            "spearman_rho": float(rho_vix) if rho_vix else None,
1831:            "spearman_p": float(p_rho_vix) if p_rho_vix else None,
1845:        "vix_median_split": float(vix_median),
1868:        "non_nfp_avg_range": float(non_nfp_range),
1882:    "multiplicity": multiplicity,
1903:        "the top-level `multiplicity` block and the per-test `multiplicity` stamp for the "
1914:    "event_data": results,  # full per-event data
1921:_holm = {m["test"]: m for m in multiplicity["all_outputs_family"]["members"]}
1925:    ("statistical_tests", "B_nfp_vs_friday"): "B_nfp_vs_friday_welch",
1940:    entry["multiplicity"] = {
1970:    _e["multiplicity"] = {
1972:        "pearson": {
1975:                dict(zip([n for n, _ in confirmatory], confirmatory_adj))["E_vix_pearson"]),
1976:            "p_holm_all_outputs_family": float(_holm["E_vix_pearson"]["p_holm"]),
1978:        "spearman": {
1981:                dict(zip([n for n, _ in confirmatory], confirmatory_adj))["E_vix_spearman"]),
1982:            "p_holm_all_outputs_family": float(_holm["E_vix_spearman"]["p_holm"]),
1988:    if isinstance(v, dict) and "multiplicity" not in v and k != "B_diagnostic_mixed_weekday"
1992:        f"statistical_tests entries {_unstamped} carry a p-value but no multiplicity stamp. "
2018:        "nfp_days_on_friday_official": int((df["weekday"] == 4).sum()),
2025:    "n_claims_flipped": n_flipped,
2026:    "n_claims_audited": len(audit_items),

2026-07-27T00:31:07.338015Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '590,1030p'
nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '1030,1135p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
   590	
   591	
   592	spy["VIX"], vix_ffill_audit = check_vix_forward_fill_age(spy["VIX"])
   593	price_coverage["vix_forward_fill"] = vix_ffill_audit
   594	
   595	print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
   596	print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data "
   597	      f"({vix_ffill_audit['n_sessions_without_native_vix']} forward-filled, "
   598	      f"longest run {vix_ffill_audit['max_consecutive_ffill_trading_days']}d)")
   599	
   600	# ============================================================
   601	# 3. Map NFP dates to trading days
   602	# ============================================================
   603	print("\n[2/6] Mapping NFP dates to trading days...")
   604	
   605	nfp_calendar, calendar_completeness = load_nfp_dates()
   606	trading_dates = spy.index
   607	
   608	# The proxy forced every event onto a Friday. The official calendar does not,
   609	# and that is load-bearing for the Friday-baseline test below.
   610	n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
   611	print(f"  Official releases: {len(nfp_calendar)} "
   612	      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
   613	
   614	# Map each NFP date to the session that trades the news. The report drops at
   615	# 08:30 ET, before the open, so a release on a closed day is traded at the next
   616	# open -- hence "next trading day", not "nearest". Every release must land on
   617	# exactly one session and no two releases may share one: both failures shrink
   618	# the event set without shrinking any count that gets printed.
   619	release_to_session = {}
   620	unmapped = []
   621	for nfp_date in nfp_calendar:
   622	    nfp_ts = pd.Timestamp(nfp_date)
   623	    if nfp_ts in trading_dates:
   624	        release_to_session[nfp_ts] = nfp_ts
   625	        continue
   626	    mask = (trading_dates > nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
   627	    candidates = trading_dates[mask]
   628	    if len(candidates) > 0:
   629	        release_to_session[nfp_ts] = candidates[0]
   630	    else:
   631	        unmapped.append(nfp_ts.date().isoformat())
   632	
   633	# In-sample releases must map. Releases outside the price series (the calendar
   634	# window can overhang the SPY history on either end) are excluded by design,
   635	# not by failure, so they are separated before the assertion.
   636	in_sample_unmapped = [
   637	    d for d in unmapped
   638	    if trading_dates[0] <= pd.Timestamp(d) <= trading_dates[-1]
   639	]
   640	if in_sample_unmapped:
   641	    raise RuntimeError(
   642	        f"{len(in_sample_unmapped)} official NFP release(s) inside the price sample found no "
   643	        f"trading session within 3 days: {in_sample_unmapped}. Silently skipping them would "
   644	        "drop real event days into the control group."
   645	    )
   646	
   647	# Codex round-5 B3, second half. The clause above forgives a release that falls
   648	# OUTSIDE the price series, on the reasoning that the calendar window may overhang
   649	# the price history. For this sample that reasoning does not apply: the calendar
   650	# and the price download were asked for the same fixed, fully-elapsed window, and
   651	# check_price_coverage has already confirmed both series reach both ends of it. So
   652	# an overhang here is not a design boundary, it is a short download that the
   653	# coverage tolerance was too coarse to catch -- and `n_outside_price_sample` is
   654	# precisely where such a release would go to be counted and then ignored.
   655	if unmapped:
   656	    raise RuntimeError(
   657	        f"{len(unmapped)} official NFP release(s) fall outside the price sample: "
   658	        f"{sorted(unmapped)}. SPY covers {price_coverage['SPY']['observed']} and the calendar "
   659	        f"was requested for {SAMPLE_START}..{SAMPLE_END}; with both endpoints verified, every "
   660	        "release must land on a session. Counting these as 'outside the sample' and carrying "
   661	        "on is how a truncated price series produces a conclusion on a shorter sample."
   662	    )
   663	
   664	collisions = {}
   665	for rel, sess in release_to_session.items():
   666	    collisions.setdefault(sess, []).append(rel.date().isoformat())
   667	colliding = {str(s.date()): sorted(v) for s, v in collisions.items() if len(v) > 1}
   668	if colliding:
   669	    raise RuntimeError(
   670	        f"two or more NFP releases mapped to the same trading session: {colliding}. "
   671	        "The de-duplication that used to hide this also silently reduced the event count."
   672	    )
   673	
   674	nfp_trading_dates = sorted(release_to_session.values())
   675	n_shifted = sum(1 for r, s in release_to_session.items() if r != s)
   676	
   677	# Both dates travel together from here on. Codex round-5 B1: the run kept only the
   678	# session date, so `weekday` below meant SESSION weekday while the README read it
   679	# as RELEASE weekday. The two differ on exactly the releases that fall on a market
   680	# holiday, and every one of those in this sample is a Good Friday -- so the
   681	# "Friday" event group was 237 sessions, not the 243 Friday releases the prose
   682	# described. The collision check above makes this inverse well-defined.
   683	session_to_release = {s: r for r, s in release_to_session.items()}
   684	assert len(session_to_release) == len(release_to_session)
   685	
   686	# A release whose weekday and session weekday disagree must be a release on a
   687	# non-trading day -- that is the only mechanism that can shift one. Stating it as
   688	# an invariant rather than a comment means a future change to the mapping rule
   689	# (say, "nearest session" instead of "next session") cannot quietly redefine the
   690	# event group while the prose keeps describing the old one.
   691	weekday_shifted = sorted(
   692	    r for r, s in release_to_session.items() if r.weekday() != s.weekday()
   693	)
   694	misattributed = [r for r in weekday_shifted if r in set(trading_dates)]
   695	if misattributed:
   696	    raise RuntimeError(
   697	        f"release(s) {[str(d.date()) for d in misattributed]} changed weekday despite being "
   698	        "trading days themselves. The release-to-session mapping is no longer 'same day, else "
   699	        "next open' and the weekday-matched estimand below is not what it claims to be."
   700	    )
   701	
   702	# The Friday releases that are absorbed by a non-Friday session, named rather than
   703	# counted. These are the six the README used to fold silently into "NFP released
   704	# on a Friday".
   705	friday_release_nonfriday_session = sorted(
   706	    r for r, s in release_to_session.items() if r.weekday() == 4 and s.weekday() != 4
   707	)
   708	
   709	# Window buffer: an event needs 5 sessions before and 5 after to have a window
   710	# at all. Excluding the edges is correct; doing it without saying so is not.
   711	window_excluded = [d for d in nfp_trading_dates
   712	                   if d < trading_dates[10] or d > trading_dates[-6]]
   713	valid_nfp = [d for d in nfp_trading_dates
   714	             if d >= trading_dates[10] and d <= trading_dates[-6]]
   715	
   716	if len(valid_nfp) + len(window_excluded) != len(nfp_trading_dates):
   717	    raise RuntimeError("event-window partition lost events; refusing to continue")
   718	
   719	mapping_audit = {
   720	    "n_official_releases": len(nfp_calendar),
   721	    "n_mapped_to_sessions": len(nfp_trading_dates),
   722	    "n_shifted_to_next_session": n_shifted,
   723	    "n_outside_price_sample": len(unmapped),
   724	    "outside_price_sample_dates": sorted(unmapped),
   725	    "n_excluded_for_window_buffer": len(window_excluded),
   726	    "window_excluded_dates": [str(d.date()) for d in window_excluded],
   727	    "n_valid_events": len(valid_nfp),
   728	}
   729	
   730	print(f"  Total official releases: {len(nfp_calendar)}")
   731	print(f"  Mapped to trading sessions: {len(nfp_trading_dates)} ({n_shifted} shifted to next open)")
   732	print(f"  Outside price sample: {len(unmapped)}")
   733	print(f"  Excluded for window buffer: {len(window_excluded)}")
   734	print(f"  Valid (with pre/post window): {len(valid_nfp)}")
   735	
   736	# ============================================================
   737	# 4. Calculate event windows
   738	# ============================================================
   739	print("\n[3/6] Calculating event window statistics...")
   740	
   741	results = []
   742	idx_list = list(trading_dates)
   743	
   744	for nfp_date in valid_nfp:
   745	    pos = idx_list.index(nfp_date)
   746	
   747	    # Pre-event: T-5 to T-1
   748	    pre_window = spy.iloc[pos-5:pos]
   749	    # Event day: T
   750	    event_day = spy.iloc[pos]
   751	    # Post-event: T+1 to T+5
   752	    post_window = spy.iloc[pos+1:pos+6]
   753	
   754	    # Unreachable given the window-buffer partition above. Kept as an assertion
   755	    # rather than a `continue`: if the partition ever stops holding, the run
   756	    # must stop, not quietly analyse a smaller sample than it reports.
   757	    if len(pre_window) < 5 or len(post_window) < 5:
   758	        raise RuntimeError(
   759	            f"event {nfp_date.date()} has an incomplete window "
   760	            f"(pre={len(pre_window)}, post={len(post_window)}) despite passing the "
   761	            "window-buffer filter -- the partition and the window logic disagree"
   762	        )
   763	
   764	    release_ts = session_to_release[nfp_date]
   765	
   766	    row = {
   767	        # `date` is the SESSION -- the day whose return is measured. Kept under the
   768	        # original key so the before/after audit against the archived proxy run
   769	        # still lines up. `release_date` is when BLS published. They differ for the
   770	        # six Good Friday releases; see friday_estimand in the results JSON.
   771	        "date": nfp_date.strftime("%Y-%m-%d"),
   772	        "session_date": nfp_date.strftime("%Y-%m-%d"),
   773	        "release_date": release_ts.strftime("%Y-%m-%d"),
   774	        "year": nfp_date.year,
   775	        "month": nfp_date.month,
   776	        # SESSION weekday. This is the one the Friday test filters on, and it is
   777	        # the correct one: the quantity being compared is a session return, and the
   778	        # confound being held fixed is the day-of-week effect of that session.
   779	        "weekday": nfp_date.weekday(),
   780	        "session_weekday": nfp_date.weekday(),
   781	        "release_weekday": release_ts.weekday(),
   782	        "session_shifted_from_release": bool(release_ts != nfp_date),
   783	        "event_return": float(event_day["Return"]),
   784	        "event_abs_return": float(event_day["AbsReturn"]),
   785	        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
   786	        "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
   787	        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
   788	        "event_vix": float(event_day["VIX"]) if pd.notna(event_day["VIX"]) else None,
   789	        "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
   790	        "vix_change_event": None,
   791	        "high_low_range": float((event_day["High"] - event_day["Low"]) / event_day["Close"]),
   792	        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
   793	    }
   794	
   795	    if row["pre_vix"] is not None and row["event_vix"] is not None:
   796	        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]
   797	
   798	    results.append(row)
   799	
   800	df = pd.DataFrame(results)
   801	print(f"  Events with complete data: {len(df)}")
   802	print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
   803	
   804	# ============================================================
   805	# 5. Non-NFP baseline calculation
   806	# ============================================================
   807	print("\n[4/6] Computing non-NFP baseline...")
   808	
   809	# Exclude EVERY NFP session from the control group, not just the ones that
   810	# survived the event-window filter. An event dropped for lacking a pre-window
   811	# is still an NFP day; leaving it in the control group is the exact failure this
   812	# experiment exists to fix ("dump real event days into the control group"), just
   813	# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
   814	nfp_set = set(nfp_trading_dates)
   815	non_nfp_mask = ~spy.index.isin(nfp_set)
   816	non_nfp = spy[non_nfp_mask]
   817	n_leaked = len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask]))
   818	if n_leaked:
   819	    raise RuntimeError(f"{n_leaked} NFP session(s) remained in the control group")
   820	
   821	baseline_abs_return = float(non_nfp["AbsReturn"].mean())
   822	baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
   823	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
   824	
   825	# Friday-only baseline. The event group is a weekday MIXTURE while the control
   826	# group is pure Friday, so any Friday-vs-other-weekday volatility difference
   827	# loads straight onto the estimate. The test below holds weekday fixed on BOTH
   828	# sides.
   829	#
   830	# Note against the obvious story: this defect is NOT introduced by the date
   831	# correction. The proxy calendar was all-Friday by construction, but mapping
   832	# holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
   833	# -- 239/254 = 94.1% Friday, against 237/253 = 93.7% here. The mixture was
   834	# always there and is essentially unchanged; the old spec was already comparing
   835	# a mixed group against a pure-Friday control. Correcting the dates is what made
   836	# it visible, not what caused it.
   837	friday_mask = non_nfp.index.weekday == 4
   838	friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
   839	friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
   840	
   841	print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   842	print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
   843	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   844	
   845	# ============================================================
   846	# 6. Statistical tests
   847	# ============================================================
   848	print("\n[5/6] Running statistical tests...")
   849	
   850	nfp_abs_returns = df["event_abs_return"].values
   851	non_nfp_abs_returns = non_nfp["AbsReturn"].values
   852	friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
   853	
   854	# --- Test A: NFP vs all non-NFP days ---
   855	t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
   856	vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
   857	
   858	# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
   859	#
   860	# Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
   861	#   (i)  restrict the event group to the releases traded in a Friday session, or
   862	#   (ii) keep all events and use weekday-matched controls.
   863	# This run takes (i). The non-Friday events are a handful of thin weekday cells
   864	# out of 253 -- cells that thin make (ii) a weighted average dominated by a few
   865	# single-digit strata, with standard errors driven by the smallest of them.
   866	# That is a noisier estimator of a harder-to-state quantity.
   867	#
   868	# WHICH "FRIDAY" (Codex round-5 B1). The filter is SESSION weekday, so the
   869	# estimand is:
   870	#
   871	#     among trading sessions that fall on a Friday, do those that absorb an NFP
   872	#     release show larger |return| than those that do not
   873	#
   874	# NOT "among NFP releases dated a Friday". The two differ by six Good Fridays
   875	# (2007-04-06, 2010-04-02, 2012-04-06, 2015-04-03, 2021-04-02, 2023-04-07) --
   876	# published on a Friday, but the market was shut, so the news is absorbed by the
   877	# following Monday. 243 of the 253 releases are dated a Friday; 237 are traded on
   878	# one. Earlier drafts of the README described the filter as the former while the
   879	# code did the latter.
   880	#
   881	# Session weekday is the right filter, and not merely the convenient one. The
   882	# measured quantity is a SESSION return and the confound being held fixed is the
   883	# day-of-week effect OF THAT SESSION. Filtering on release weekday would put six
   884	# Monday returns into a comparison against a pure-Friday control group, which
   885	# reintroduces exactly the weekday contamination this restriction exists to
   886	# remove. Option (ii) -- release weekday plus weekday-matched controls -- is
   887	# internally coherent but answers a different question with a noisier estimator.
   888	#
   889	# The exclusion is not neutral and should not be sold as such: the excluded
   890	# events are quieter than the Friday ones, so restricting RAISES the ratio
   891	# relative to the mixed spec. That is a property of the estimand, not evidence
   892	# of a stronger effect. Both numbers are reported, and the six Good Friday events
   893	# are reported separately below rather than dropped in silence.
   894	nfp_friday_mask = (df["weekday"] == 4).values
   895	nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
   896	nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
   897	
   898	t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
   899	vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())
   900	
   901	# Diagnostic ONLY -- the pre-correction specification, kept so the correction
   902	# audit can show what the contaminated estimand was worth. Not a headline
   903	# number and not eligible to be quoted: its p-value mixes in weekday
   904	# composition, which is exactly the defect being repaired.
   905	t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
   906	    nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
   907	vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
   908	
   909	# The estimand, stated in machine-readable form so the prose cannot drift from it
   910	# again. Everything here is recomputed from `df`, not copied from the narrative.
   911	_n_release_friday = int((df["release_weekday"] == 4).sum())
   912	_n_session_friday = int((df["session_weekday"] == 4).sum())
   913	_gf = df[(df["release_weekday"] == 4) & (df["session_weekday"] != 4)]
   914	friday_estimand = {
   915	    "filter": "session weekday == Friday",
   916	    "estimand": (
   917	        "Among trading sessions falling on a Friday, do the sessions that absorb an NFP "
   918	        "release show larger |return| than those that do not? This is a claim about the "
   919	        "session that trades the news, NOT about releases dated a Friday."
   920	    ),
   921	    "n_events_total": int(len(df)),
   922	    "n_release_date_on_friday": _n_release_friday,
   923	    "n_traded_in_friday_session": _n_session_friday,
   924	    "friday_releases_absorbed_by_a_later_session": {
   925	        "n": int(len(_gf)),
   926	        "dates": [
   927	            {
   928	                "release_date": r["release_date"],
   929	                "session_date": r["session_date"],
   930	                "session_weekday": int(r["session_weekday"]),
   931	                "event_abs_return": float(r["event_abs_return"]),
   932	            }
   933	            for _, r in _gf.iterrows()
   934	        ],
   935	        "mean_abs_return": float(_gf["event_abs_return"].mean()) if len(_gf) else None,
   936	        "why_excluded": (
   937	            "Every one is a Good Friday: BLS published, the market was shut, the news is "
   938	            "absorbed by the following Monday. Their returns are Monday returns and cannot "
   939	            "enter a comparison whose control group is pure Friday without reintroducing the "
   940	            "weekday confound the restriction exists to remove."
   941	        ),
   942	    },
   943	    "why_session_and_not_release_weekday": (
   944	        "The measured quantity is a session return and the confound held fixed is the "
   945	        "day-of-week effect of that session. Filtering on release weekday would place these "
   946	        "Monday returns against a Friday-only control group."
   947	    ),
   948	    "what_this_does_not_identify": (
   949	        "Not 'NFP in general' (the sample is conditioned on Friday sessions) and not "
   950	        "'releases dated a Friday' (six such releases are traded on a Monday and excluded)."
   951	    ),
   952	}
   953	if _n_release_friday - _n_session_friday != len(_gf):
   954	    raise RuntimeError(
   955	        "release-Friday / session-Friday counts do not reconcile with the shifted set; the "
   956	        "estimand description would be wrong."
   957	    )
   958	
   959	# --- Test C: Wilcoxon rank-sum (non-parametric) ---
   960	u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
   961	
   962	# --- Test D: Vol crush pattern (post vs pre) ---
   963	vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
   964	t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
   965	
   966	# --- Test E: VIX predictive regression ---
   967	vix_valid = df.dropna(subset=["pre_vix"])
   968	if len(vix_valid) > 10:
   969	    from numpy.polynomial.polynomial import polyfit
   970	    X_vix = vix_valid["pre_vix"].values
   971	    Y_abs = vix_valid["event_abs_return"].values
   972	    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
   973	    # correlation and p-value
   974	    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
   975	    # also spearman
   976	    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
   977	else:
   978	    slope, intercept, r_vix, p_vix, rho_vix, p_rho_vix = [None]*6
   979	
   980	# --- Test F: Pre-event VIX change (buildup) ---
   981	# Compare VIX at T-5 vs T-1 (is there anticipatory VIX increase?)
   982	vix_buildup = []
   983	for nfp_date in valid_nfp:
   984	    pos = idx_list.index(nfp_date)
   985	    pre5 = spy.iloc[pos-5]
   986	    pre1 = spy.iloc[pos-1]
   987	    if pd.notna(pre5["VIX"]) and pd.notna(pre1["VIX"]):
   988	        vix_buildup.append(float(pre1["VIX"] - pre5["VIX"]))
   989	
   990	t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)
   991	
   992	# --- Test G: Seasonal analysis (by month) ---
   993	monthly_stats = {}
   994	for month in range(1, 13):
   995	    month_data = df[df["month"] == month]["event_abs_return"]
   996	    if len(month_data) >= 5:
   997	        monthly_stats[str(month)] = {
   998	            "n": int(len(month_data)),
   999	            "mean_abs_return": float(month_data.mean()),
  1000	            "vol_ratio": float(month_data.mean() / baseline_abs_return),
  1001	            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
  1002	            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
  1003	        }
  1004	
  1005	# --- Test H: Regime analysis (high VIX vs low VIX) ---
  1006	vix_median = df["pre_vix"].median()
  1007	high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
  1008	low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
  1009	t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)
  1010	
  1011	# --- Test I: Time trend (has NFP impact changed over time?) ---
  1012	# Split into halves
  1013	midpoint = len(df) // 2
  1014	first_half = df.iloc[:midpoint]["event_abs_return"]
  1015	second_half = df.iloc[midpoint:]["event_abs_return"]
  1016	t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)
  1017	
  1018	# --- Test J: Event-day return direction ---
  1019	pos_returns = (df["event_return"] > 0).sum()
  1020	neg_returns = (df["event_return"] < 0).sum()
  1021	# Binomial test: is there a directional bias?
  1022	binom_p = float(stats.binomtest(pos_returns, pos_returns + neg_returns, 0.5).pvalue)
  1023	
  1024	
  1025	# ============================================================
  1026	# 6b. Multiplicity (Codex round-5 B4)
  1027	# ============================================================
  1028	# The script emits 22 p-values and used to call one of them "significant at 5%"
  1029	# with no family declared. That is not a defensible 5% claim, it is a nominal one.
  1030	#
  1030	#
  1031	# Holm rather than Romano-Wolf: Holm controls FWER under ARBITRARY dependence,
  1032	# which is what this family needs -- it mixes Welch t, Mann-Whitney U and two
  1033	# correlation tests on overlapping samples, and there is no single resampling
  1034	# scheme that is jointly valid for all four. Romano-Wolf would be more powerful
  1035	# if such a scheme existed; inventing one to gain power would be the wrong trade
  1036	# in a review that is specifically about not overstating.
  1037	def holm_adjust(pvals):
  1038	    """Holm step-down adjusted p-values, monotone and capped at 1."""
  1039	    m = len(pvals)
  1040	    order = sorted(range(m), key=lambda i: pvals[i])
  1041	    adj, running = [0.0] * m, 0.0
  1042	    for rank, i in enumerate(order):
  1043	        running = max(running, (m - rank) * pvals[i])
  1044	        adj[i] = min(1.0, running)
  1045	    return adj
  1046	
  1047	
  1048	# The confirmatory family: the six tests README's "方法 / 檢定" line has named as
  1049	# the study's tests since before this rerun, and the only ones the published
  1050	# article makes directional claims from. Naming them is what makes the correction
  1051	# auditable -- an unnamed family is a family chosen after seeing the p-values.
  1052	#
  1053	# Honest caveat, stated here and in the README: this study was never
  1054	# pre-registered. "Pre-specified" means these endpoints predate the date
  1055	# correction and the rerun, not that they were lodged before the data were seen.
  1056	# The all-outputs family below is reported alongside precisely so that the narrow
  1057	# family cannot be mistaken for a result that survives any choice of family.
  1058	confirmatory = [
  1059	    ("A_nfp_vs_all_welch", float(p_val_all)),
  1060	    ("B_nfp_vs_friday_welch", float(p_val_fri)),
  1061	    ("C_mannwhitney_one_sided", float(p_val_wilcox)),
  1062	    ("E_vix_pearson", float(p_vix)),
  1063	    ("E_vix_spearman", float(p_rho_vix)),
  1064	    ("H_vix_regime_welch", float(p_regime)),
  1065	]
  1066	confirmatory_adj = holm_adjust([p for _, p in confirmatory])
  1067	
  1068	# Every inferential output the script produces, so the sensitivity below cannot
  1069	# be accused of a convenient boundary. B_diagnostic_mixed_weekday is deliberately
  1070	# NOT here: it is the superseded pre-correction specification, retained so the
  1071	# correction audit can show what the contaminated estimand was worth, and it is
  1072	# marked ineligible to quote wherever it appears. Including a number nobody may
  1073	# cite would inflate the penalty on the numbers people do cite.
  1074	exploratory = [
  1075	    ("D_vol_crush", float(p_crush)),
  1076	    ("F_vix_buildup", float(p_buildup)) if p_buildup is not None else None,
  1077	    ("I_time_trend", float(p_trend)),
  1078	    ("J_direction_binomial", float(binom_p)),
  1079	] + [(f"G_month_{m}", float(v["p_val"])) for m, v in sorted(monthly_stats.items(), key=lambda kv: int(kv[0]))]
  1080	exploratory = [e for e in exploratory if e is not None]
  1081	
  1082	all_outputs = confirmatory + exploratory
  1083	all_adj = holm_adjust([p for _, p in all_outputs])
  1084	
  1085	_b_idx = [n for n, _ in confirmatory].index("B_nfp_vs_friday_welch")
  1086	_b_all_idx = [n for n, _ in all_outputs].index("B_nfp_vs_friday_welch")
  1087	
  1088	multiplicity = {
  1089	    "method": "Holm step-down (FWER, valid under arbitrary dependence)",
  1090	    "why_not_romano_wolf": (
  1091	        "The family mixes Welch t, Mann-Whitney U and two correlation statistics on "
  1092	        "overlapping samples; no single resampling scheme is jointly valid for all four, and "
  1093	        "manufacturing one to buy power is the wrong trade in a correction about overstatement."
  1094	    ),
  1095	    "pre_registered": False,
  1096	    "pre_registration_note": (
  1097	        "Not pre-registered. The confirmatory endpoints predate the date correction and this "
  1098	        "rerun, but were not lodged before the data were seen. Both families are therefore "
  1099	        "reported and the narrow one is not presented as the only defensible reading."
  1100	    ),
  1101	    "confirmatory_family": {
  1102	        "n": len(confirmatory),
  1103	        "members": [
  1104	            {"test": n, "p_nominal": p, "p_holm": a, "survives_5pct": bool(a < 0.05)}
  1105	            for (n, p), a in zip(confirmatory, confirmatory_adj)
  1106	        ],
  1107	    },
  1108	    "all_outputs_family": {
  1109	        "n": len(all_outputs),
  1110	        "members": [
  1111	            {"test": n, "p_nominal": p, "p_holm": a, "survives_5pct": bool(a < 0.05)}
  1112	            for (n, p), a in zip(all_outputs, all_adj)
  1113	        ],
  1114	    },
  1115	    "headline_friday_test": {
  1116	        "p_nominal": float(p_val_fri),
  1117	        "p_holm_confirmatory_family": float(confirmatory_adj[_b_idx]),
  1118	        "p_holm_all_outputs_family": float(all_adj[_b_all_idx]),
  1119	        "verdict": (
  1120	            "Survives Holm within the six-test confirmatory family; does NOT survive Holm "
  1121	            "against all 22 inferential outputs. Report as nominally significant, "
  1122	            "Holm-robust only within the declared confirmatory family."
  1123	        ),
  1124	    },
  1125	    "exploratory_note": (
  1126	        "Everything outside the confirmatory family -- the 12 monthly cells, vol crush, VIX "
  1127	        "buildup, time trend and direction binomial -- is EXPLORATORY. Nominal p-values are "
  1128	        "reported for description; none may be quoted as a 5% finding."
  1129	    ),
  1130	}
  1131	
  1132	print("\n--- Multiplicity (Holm) ---")
  1133	print(f"  Confirmatory family: {len(confirmatory)} tests")
  1134	for (n, p), a in zip(confirmatory, confirmatory_adj):
  1135	    print(f"    {n:28s} p={p:.4g}  Holm={a:.4g}  {'PASS' if a < 0.05 else 'fail'}")

2026-07-27T00:31:14.737576Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "nl -ba experiments/k528/build_article_correction.py | sed -n '1,348p'
nl -ba experiments/k528/README.md | sed -n '1,330p'
nl -ba experiments/k528/README.md | sed -n '330,434p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
     1	"""Build and validate the in-place correction to mile_35eef830.
     2	
     3	The article was published 2026-07-01 with headline numbers taken from K528,
     4	which dated every NFP to the first Friday of the month. On the official BLS
     5	calendar that proxy is wrong for ~20% of the sample, so every number moved a
     6	little. This script restates them.
     7	
     8	WHAT CHANGED SINCE THE VOIDED 2026-07-19 CORRECTION LIST
     9	--------------------------------------------------------
    10	An earlier 18-item list was built against a contaminated rerun and has been
    11	VOIDED IN FULL. That rerun used an event-date accessor which, for the six
    12	months where ALFRED returns two entries, picked the LATER one -- an off-cycle
    13	seasonal-factor revision rather than the Employment Situation report. Six event
    14	dates were therefore wrong (2006-05-08, 2012-12-12, 2013-05-06, 2020-05-11,
    15	2024-01-10, 2024-08-21).
    16	
    17	That mattered far more than six dates out of 253 suggests, because it moved the
    18	NFP-vs-Friday test across the 5% line. The voided list told readers that a
    19	result the article reported as significant was in fact not significant
    20	(1.17x p=0.0335 -> "1.15x p=0.057, 差一點過線但沒過"). On correct dates the
    21	comparison is 1.19x at p=0.020 -- significant, exactly as the article
    22	originally said. Applying that list would have published a retraction of a
    23	correct finding.
    24	
    25	So: no claim in this article reverses direction. Every replacement below is a
    26	numeric restatement, plus one estimand refinement that is disclosed in the note.
    27	
    28	THE ONE ESTIMAND CHANGE
    29	-----------------------
    30	The event group is a weekday mixture while the control group is pure Friday, so
    31	the Friday effect leaks into the estimate. The corrected test restricts the
    32	event group to the 237 releases ABSORBED BY a Friday session.
    33	
    34	WHICH "FRIDAY" (Codex round-5 B1). The filter is SESSION weekday, not release
    35	weekday, and the two do not agree. Of the 253 releases, 243 are DATED a Friday
    36	but only 237 TRADE in one: the six Good Fridays (2007-04-06, 2010-04-02,
    37	2012-04-06, 2015-04-03, 2021-04-02, 2023-04-07) were published while the market
    38	was shut, so the news is absorbed by the following Monday. Their returns are
    39	Monday returns and cannot enter a comparison whose control group is pure Friday
    40	without putting back the weekday confound the restriction exists to remove.
    41	"237 Friday releases" is therefore the wrong phrase for this number in either
    42	direction -- 237 is a session count, 243 is the release count.
    43	
    44	Note against the tempting story: this defect was NOT introduced by the date
    45	correction. The proxy CALENDAR was all-Friday by construction, but mapping
    46	holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
    47	(239/254 = 94.1% Friday SESSIONS, against 237/253 = 93.7% now). The old spec was
    48	already comparing a mixed group against a pure-Friday control; correcting the
    49	dates is what made it visible, not what caused it.
    50	
    51	Two consequences the article text must respect:
    52	  1. The test identifies the effect of an NFP release ABSORBED BY A FRIDAY
    53	     SESSION. Prose quoting it says 「消息落在週五交易日的 NFP」, not "NFP" and
    54	     not 「在週五公布的 NFP」 -- the latter would be the 243, not the 237.
    55	  2. The restriction is not a neutral deletion — the excluded events are 16.3%
    56	     quieter, so restricting RAISES the ratio (1.177x -> 1.189x). Both numbers
    57	     are disclosed in the correction note rather than only the flattering one.
    58	
    59	WHY THIS SCRIPT DOES NOT WRITE BY DEFAULT
    60	-----------------------------------------
    61	`storage/reports/feed.json` is shared canonical state. `.claude/rules/worktree.md`
    62	forbids a worktree agent from touching it, and the reason is mechanical rather
    63	than ceremonial: this worktree carries its own 15MB checkout of feed.json, so a
    64	write here lands on a branch copy that is already stale the moment any other
    65	article is published, and merging it would silently revert them.
    66	
    67	So the split is: this script (run from the worktree) resolves and VALIDATES
    68	every replacement against the canonical article, proving each matches exactly
    69	once before anything is written. The main thread then runs it with --apply from
    70	the repo root, where the write is legitimate.
    71	
    72	    uv run python experiments/k528/build_article_correction.py            # validate, writes nothing
    73	    uv run python experiments/k528/build_article_correction.py --apply    # write + sync
    74	
    75	Validation uses `article_correction._splice`, the same resolver the writer
    76	uses, so a plan that validates here cannot fail differently there.
    77	"""
    78	
    79	from __future__ import annotations
    80	
    81	import argparse
    82	import json
    83	import os
    84	import tempfile
    85	from pathlib import Path
    86	
    87	REPO_ROOT = Path(__file__).resolve().parents[2]
    88	ARTICLE_ID = "mile_35eef830"
    89	AUDIT_PATH = Path(__file__).parent / "k528_nfp_official_dates_results.json"
    90	
    91	# The 18-item list built on 2026-07-19 against the contaminated rerun. Kept as a
    92	# record of what must NOT be applied, not as a fallback -- see the module
    93	# docstring. Anything that resurrects these strings is reintroducing a
    94	# retraction of a correct finding.
    95	VOIDED_20260719_LIST_SIZE = 18
    96	
    97	# (old, new). Each `old` must occur exactly once in the article body; the
    98	# resolver rejects the whole batch otherwise. Ordered as they appear.
    99	REPLACEMENTS: list[tuple[str, str]] = [
   100	    # --- sample size: 254 -> 253 ---
   101	    (
   102	        "總共 254 次 NFP 公布日的資料算過一遍",
   103	        "總共 253 次 NFP 公布日的資料算過一遍",
   104	    ),
   105	    # --- 1.10x -> 1.11x vs all non-NFP days (direction unchanged: NOT significant) ---
   106	    (
   107	        "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
   108	        "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
   109	    ),
   110	    (
   111	        "換句話說，這 1.10 倍的差距",
   112	        "換句話說，這 1.11 倍的差距",
   113	    ),
   114	    # --- Friday baseline: 1.17x -> 1.19x, STILL significant; estimand made explicit ---
   115	    (
   116	        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，"
   117	        "用 Welch t 檢定算下來，這個差距達到顯著水準。"
   118	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
   119	        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。253 場 NFP 裡，有 243 場的公布日是週五，"
   120	        "但其中 6 場碰上 Good Friday 休市（BLS 照常發布，市場沒開），行情要等下週一才反應；"
   121	        "真正在週五盤被消化掉的是 237 場。這個比較只取那 237 場，讓兩邊的星期別一致："
   122	        "這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準"
   123	        "（p=0.021，這是未經多重比較校正的 nominal 值）。"
   124	        "要注意這個數字講的是「**消息落在週五交易日的** NFP」，既不是「公布日在週五的 NFP」"
   125	        "（那是 243 場），也不是 NFP 一般而言；被排掉的那 16 場本身比較平靜，"
   126	        "所以限定週五會把倍數墊高一些（不限定的話是 1.18 倍）。"
   127	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
   128	    ),
   129	    (
   130	        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；"
   131	        "但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
   132	        "所以精確的講法是：消息落在週五交易日的 NFP 確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；"
   133	        "但如果拿全部交易日當對照，這個放大效果（1.11 倍）在 Welch 平均差檢定下未達顯著"
   134	        "（p=0.11）—— 要注意同一組對照下，只看排序的無母數檢定反而是顯著的（p=0.002），"
   135	        "兩種檢定不一致，不能合併成一句「沒有效果」。",
   136	    ),
   137	    # --- regime split: threshold, group sizes, means, ratio ---
   138	    (
   139	        "那 254 次 NFP 日裡",
   140	        "那 253 次 NFP 日裡",
   141	    ),
   142	    (
   143	        "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
   144	        "分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；"
   145	        "VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
   146	        "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
   147	        "分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；"
   148	        "VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
   149	    ),
   150	    # --- VIX correlation ---
   151	    (
   152	        "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
   153	        "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
   154	    ),
   155	    (
   156	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
   157	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
   158	    ),
   159	    # --- figure caption ---
   160	    (
   161	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
   162	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
   163	    ),
   164	    # --- the worked example: 2026-07-01 VIX 16.59 vs the threshold (still low regime) ---
   165	    (
   166	        "貼在歷史分界線 16.71 的下緣",
   167	        "貼在歷史分界線 16.69 的下緣",
   168	    ),
   169	    (
   170	        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
   171	        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
   172	    ),
   173	    (
   174	        "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
   175	        "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
   176	    ),
   177	    # --- conclusions section (direction unchanged on both baselines) ---
   178	    (
   179	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，"
   180	        "對週五基準是 1.17 倍、達到顯著水準。",
   181	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準；"
   182	        "若只看消息落在週五交易日的那 237 場、拿非 NFP 的週五當基準，是 1.19 倍、達到顯著水準。",
   183	    ),
   184	    (
   185	        "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
   186	        "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
   187	    ),
   188	    (
   189	        "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
   190	        "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
   191	    ),
   192	    (
   193	        "254 場歷史樣本加上 7/2 這場實測",
   194	        "253 場歷史樣本加上 7/2 這場實測",
   195	    ),
   196	    # --- methodology section + reader-facing errata ---
   197	    (
   198	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，"
   199	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
   200	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，"
   201	        "NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），"
   202	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n"
   203	        "**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。"
   204	        "與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，"
   205	        "遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，"
   206	        "但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n"
   207	        "**方向性結論全部維持不變**：對全體交易日基準在 Welch 平均差檢定下未達顯著"
   208	        "（同組對照的無母數檢定則顯著，兩者不一致）、對週五基準達到顯著、"
   209	        "進場 VIX 高低兩組之間的差距是本研究中最大的數字——這三點在官方日期下都成立，"
   210	        "只有數值小幅調整（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。"
   211	        "要說明的是，本文並沒有正式檢定「2.03 倍顯著大於 1.19 倍」——兩者的樣本與對照組都不同，"
   212	        "而且 VIX 分組用的是事後中位數切點。兩個數字是並排比較量級，不是排名，也不是因果宣稱。\n\n"
   213	        "另有一項口徑調整：週五基準的比較，事件組原本是全部樣本（星期別混合）、對照組卻只有週五，"
   214	        "兩邊不對等。現改為只取消息在週五交易日被消化的 237 場，維持兩邊星期別一致，"
   215	        "所以該數字講的是「消息落在週五交易日的 NFP」——"
   216	        "既不是「公布日在週五的 NFP」（公布日在週五的其實有 243 場，其中 6 場遇 Good Friday 休市、"
   217	        "行情落在下週一，因此不算在內），也不是 NFP 一般而言。"
   218	        "被排掉的 16 場本身比較平靜，因此限定週五會把倍數墊高一些（不限定為 1.18 倍、限定為 1.19 倍），"
   219	        "兩個數字都列出以免只揭露比較好看的那個。\n\n"
   220	        "**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。"
   221	        "逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
   222	    ),
   223	    (
   224	        "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
   225	        "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
   226	    ),
   227	]
   228	
   229	
   230	def load_article_content(storage_dir: Path) -> str:
   231	    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
   232	    art = next((a for a in feed if isinstance(a, dict) and a.get("id") == ARTICLE_ID), None)
   233	    if art is None:
   234	        raise KeyError(f"{ARTICLE_ID} not found in {storage_dir}/reports/feed.json")
   235	    return art.get("content") or ""
   236	
   237	
   238	def validate(storage_dir: Path) -> list[dict]:
   239	    """Resolve every replacement against the live article. Raises if any does
   240	    not match exactly once, before a single byte is written."""
   241	    from volpred.publisher.article_correction import _splice
   242	
   243	    content = load_article_content(storage_dir)
   244	    spans = _splice(content, REPLACEMENTS)
   245	    return [
   246	        {"index": i, "hits": 1, "from": s["from"], "to": s["to"], "offset": s["start"]}
   247	        for i, s in enumerate(sorted(spans, key=lambda x: x["start"]))
   248	    ]
   249	
   250	
   251	def _write_json_atomic(path: Path, payload) -> None:
   252	    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
   253	    try:
   254	        with os.fdopen(fd, "w", encoding="utf-8") as f:
   255	            json.dump(payload, f, indent=2, ensure_ascii=False)
   256	            f.write("\n")
   257	            f.flush()
   258	            os.fsync(f.fileno())
   259	        os.replace(tmp, path)
   260	    except BaseException:
   261	        try:
   262	            os.unlink(tmp)
   263	        except FileNotFoundError:
   264	            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
   265	        raise
   266	
   267	
   268	def record_plan(validated: list[dict], applied: dict | None) -> None:
   269	    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
   270	    audit["article_correction"] = {
   271	        "article_id": ARTICLE_ID,
   272	        "status": "applied" if applied else "validated_not_applied",
   273	        "n_replacements": len(REPLACEMENTS),
   274	        "all_matched_exactly_once": True,
   275	        "supersedes": {
   276	            "voided_list_size": VOIDED_20260719_LIST_SIZE,
   277	            "voided_at": "2026-07-19",
   278	            "reason": (
   279	                "the 18-item list was built against a rerun whose accessor picked "
   280	                "off-cycle ALFRED entries for six months, which pushed the "
   281	                "NFP-vs-Friday test across the 5% line. It would have retracted a "
   282	                "finding that is in fact correct."
   283	            ),
   284	        },
   285	        "directional_claims_changed": 0,
   286	        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
   287	        "apply_result": applied,
   288	        "residual_gap": (
   289	            "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) "
   290	            "and the two lazypack images still render proxy-era numbers. Text and images "
   291	            "now disagree; the article carries a visible note saying so. Regenerating and "
   292	            "re-uploading them is follow-up work outside this worktree's scope."
   293	        ),
   294	    }
   295	    _write_json_atomic(AUDIT_PATH, audit)
   296	
   297	
   298	def main() -> int:
   299	    ap = argparse.ArgumentParser(description=__doc__)
   300	    ap.add_argument("--apply", action="store_true",
   301	                    help="write the correction (main thread, repo root only)")
   302	    ap.add_argument("--record-plan", action="store_true",
   303	                    help="record the validated plan into the audit JSON without applying it")
   304	    ap.add_argument("--storage-dir", default=str(REPO_ROOT / "storage"))
   305	    args = ap.parse_args()
   306	
   307	    storage_dir = Path(args.storage_dir)
   308	    validated = validate(storage_dir)
   309	    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
   310	    for v in validated:
   311	        head = v["from"].splitlines()[0][:64]
   312	        print(f"  @{v['offset']:>6}  {head}...")
   313	
   314	    applied = None
   315	    if args.apply:
   316	        from volpred.publisher.article_correction import apply_article_correction
   317	
   318	        applied = apply_article_correction(
   319	            ARTICLE_ID,
   320	            content_replacements=REPLACEMENTS,
   321	            summary=(
   322	                "K528 event dates corrected from a first-Friday proxy to the official BLS "
   323	                "release calendar. Sample 254 -> 253 events; headline numbers restated "
   324	                "(1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, "
   325	                "r 0.45->0.44). No directional conclusion changes. The Friday comparison "
   326	                "now restricts the event group to the 237 releases absorbed by a Friday "
   327	                "SESSION so weekday is held fixed on both sides -- 243 releases are dated "
   328	                "a Friday, but six of those are Good Fridays traded the following Monday."
   329	            ),
   330	            action="content_correction",
   331	            storage_dir=str(storage_dir),
   332	        )
   333	        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
   334	              f"synced={applied['synced']}")
   335	
   336	    # A dry run that rewrites the audit file is not a dry run (k528 Codex v2
   337	    # finding 7). Recording is opt-in and never implicit.
   338	    if args.apply or args.record_plan:
   339	        record_plan(validated, applied)
   340	        print(f"plan recorded in {AUDIT_PATH.name}")
   341	    else:
   342	        print("\ndry run -- nothing written. Re-run with --apply from the repo root, "
   343	              "or --record-plan to persist the validated plan only.")
   344	    return 0
   345	
   346	
   347	if __name__ == "__main__":
   348	    raise SystemExit(main())
     1	# k528 — NFP 事件研究（SPY 波動率）
     2	
     3	- Experiment ID: `k528`
     4	- Created At: 2026-04-16T09:39:52.904348+00:00
     5	- Corrected At: 2026-07-19（事件日期來源修正，全樣本重跑；同日第二次修正見下）
     6	- Status: 已重跑，**方向性結論全部不變**，僅數值微調 + 一項口徑澄清
     7	
     8	## 問題描述
     9	
    10	NFP（非農就業）公布日，SPY 的波動是否會系統性放大？如果會，放大的來源是「NFP 這個
    11	事件本身」，還是「進場當下的市場狀態」？
    12	
    13	## 兩次修正，不要混為一談
    14	
    15	本實驗在 2026-07-19 被修正了**兩次**，第二次是修第一次修壞的地方。
    16	
    17	### 修正 1：事件日期從 proxy 換成官方日曆
    18	
    19	原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 錯得有結構、不是隨機噪音：
    20	
    21	- BLS 在參考週較晚的月份會改到**第二個週五**發布
    22	- 遇到聯邦假期會**提前**
    23	- **2025-10 根本沒有發布**（政府關門取消），proxy 卻憑空生出一場
    24	- proxy 把每一場都放在**週五**；官方日曆的 253 場有 243 場**發布日**在週五，
    25	  其中 237 場**在週五的交易 session 被吸收**（差額是六個 Good Friday，見下）
    26	
    27	錯的事件日期不會拋錯、不會出現 NaN，圖照樣畫得出來 —— 它只是把安靜的日子算成事件日、
    28	同時把真的事件日丟進對照組。這是修正存在的理由。
    29	
    30	`get_first_friday()` 已**整條移除**（不是標 deprecated），日期改由
    31	`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
    32	release id 50），且**取不到就 raise，不回退 proxy**。
    33	
    34	### 修正 2（本輪）：accessor 的同月多筆選擇錯誤
    35	
    36	第一次修正的 accessor 對「同月多筆 release 條目」取 `max()`。ALFRED 的 release id 50
    37	在**六個月份**會回兩筆：前一筆是 Employment Situation 正式報告，後一筆是年度季節調整
    38	因子／benchmark 修訂。`max()` 選到了後者 —— 也就是**把修訂當成了就業報告**：
    39	
    40	| 月份 | 正確（正式發布） | `max()` 誤選（off-cycle 修訂） |
    41	|---|---|---|
    42	| 2006-05 | 2006-05-05 | 2006-05-08 |
    43	| 2012-12 | 2012-12-07 | 2012-12-12 |
    44	| 2013-05 | 2013-05-03 | 2013-05-06 |
    45	| 2020-05 | 2020-05-08 | 2020-05-11 |
    46	| 2024-01 | 2024-01-05 | 2024-01-10 |
    47	| 2024-08 | 2024-08-02 | 2024-08-21 |
    48	
    49	六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
    50	**第一次修正因此得出了一個錯誤的「顯著→不顯著」翻轉，並據此準備了 18 條文章更正 ——
    51	那 18 條會把一個本來正確的結論撤回。** Codex 二審判 FAIL 擋下，未套用。
    52	
    53	根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
    54	fail-closed 驗證，commit `305d118a3`）。
    55	
    56	**為什麼原本 42 個測試全綠卻沒抓到**：fixture 是手寫的，同月第二筆事先就被刪掉了 ——
    57	測試餵進去的輸入根本表達不出這個 bug。修法不是加更好的斷言，是餵真實輸入：
    58	`tests/test_event_dates_real_raw_response.py` 直接釘住 ALFRED 的 264 筆原始回應
    59	（fixture `tests/fixtures/fred_release_50_nfp_raw_20260719.json`，**禁止去重**，
    60	那六對重複就是迴歸面），並附 mutation 檢查證明舊 `max()` 規則會在這份輸入上失敗。
    61	
    62	## 方法
    63	
    64	- 資料：SPY / ^VIX 日頻（yfinance），2005-01 至 2026-03
    65	- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
    66	- 事件窗：T-5 ~ T-1（前）、T（當日）、T+1 ~ T+5（後）
    67	- 檢定（**這六個就是 confirmatory family**，見下方「多重比較」）：Welch t（vs 全體非 NFP
    68	  日 / vs 非 NFP 週五 session）、Mann-Whitney U、VIX 中位數分組 regime 檢定、
    69	  Pearson / Spearman 相關
    70	- 其餘一切（12 個月份格、vol crush、VIX buildup、時間趨勢、方向 binomial）一律
    71	  **exploratory**，只作描述，**不得**當成 5% 發現引用
    72	
    73	### 週五基準的口徑（estimand）調整
    74	
    75	> **口徑更正（2026-07-20，Codex 五審 B1）**：本節此前寫的是「**在週五公布**的 NFP」。
    76	> 程式篩的其實是**在週五交易 session 被吸收**的 NFP —— 兩者差六場。
    77	> 253 場有效發布中，**243 場發布日在週五**，但只有 **237 場在週五開盤**：
    78	> 2007-04-06、2010-04-02、2012-04-06、2015-04-03、2021-04-02、2023-04-07
    79	> 全是 **Good Friday**，BLS 照常公布、市場休市，消息由**下週一**吸收。
    80	>
    81	> **1.189× / p=0.0209 識別的是「週五 session 是否因吸收 NFP 而波動更大」，
    82	> 不是「發布日落在週五的 NFP」。** 全文已改用前者措辭。
    83	>
    84	> **為什麼是 session weekday 而不是 release weekday**（這不是圖方便，是唯一正確的那個）：
    85	> 被比較的量是**一個 session 的報酬**，要被固定住的干擾是**那個 session 的星期效應**。
    86	> 若改用發布日 weekday 篩 243 場，等於把六筆**週一報酬**放進一個對照組是純週五的比較裡
    87	> —— 那正好把這個限制存在的理由（星期別污染）重新放回來。
    88	> 審查給的另一條路（release weekday + weekday-matched controls）內部自洽，
    89	> 但它回答的是另一個問題，且估計更吵（見下方薄格數的討論）。
    90	
    91	事件組是**星期別混合**、對照組是**純週五**，週五本身的波動特性會直接混進 p 值。
    92	
    93	**這個缺陷不是日期修正造成的 —— 修正只是讓它被看見。** proxy 的*日曆*確實每場都是週五，
    94	但遇休市會映射到下一個 session，所以它實際的 254 場事件裡有 **15 場是週一**（239/254 =
    95	94.1% 在週五）；官方日曆是 237/253 = 93.7%。混合程度幾乎沒變，舊版一直都在拿混合事件組
    96	比純週五對照組，只是從來沒人注意到。
    97	
    98	本輪把事件組**限定為在週五 session 交易的 237 場**，兩邊星期別一致。另一個選項是保留全部
    99	253 場改用 weekday-matched controls，未採用的理由：被排除的 16 場按 **session** 星期別是
   100	週一 6、週二 2、週三 1、週四 7，用這種格數做加權平均，標準誤會被 1 筆的週三格主導
   101	—— 那是對一個更難陳述的量做更吵的估計。
   102	
   103	（那 6 筆週一 session 就是上面的六個 Good Friday；其餘 10 筆是發布日本身就不在週五
   104	—— 週二 2、週三 1、週四 7。兩種來源合起來 16 筆，與 253 − 237 一致。）
   105	
   106	**限定週五不是中性的樣本刪除，這點必須明講**：被排除的 16 場平均 |ret| 是 0.715%，比週五
   107	NFP 的 0.854% **低 16.3%**，所以限定之後 ratio 會被墊高（1.177× → 1.189×）。那是口徑的
   108	性質，不是效果變強的證據。（六個 Good Friday 子集平均 |ret| = 0.715%，與 16 場整體幾乎
   109	相同 —— 巧合，不是同一個數字，兩者都由 `sample.friday_estimand` 與 `event_data` 算得出。）
   110	
   111	**因此這個檢定識別的是「在週五 session 被吸收的 NFP」**，既不是「NFP 一般而言」，
   112	也不是「發布日在週五的 NFP」。引用這個數字的文字必須寫「在週五交易 session 的 NFP」。
   113	
   114	兩種口徑在 audit 中**兩邊平行呈現**（修正前後各自都算了兩種），不拿不同口徑硬比：
   115	
   116	| | 限定週五（主口徑） | 混合星期別（舊口徑） |
   117	|---|---|---|
   118	| 修正前（proxy） | 1.167× / p=0.0421 / n=239 | 1.168× / p=0.0335 / n=254（文章當初引用的） |
   119	| 修正後（官方） | **1.189× / p=0.0209 / n=237** | 1.177× / p=0.0257 / n=253（DIAGNOSTIC ONLY） |
   120	
   121	（proxy 側的兩格對照組定義不同：限定週五那格用的是**去洩漏**的對照組 832 筆，
   122	「文章當初引用的」那格保留當年含洩漏的原值 —— 前者才是與修正後同口徑的比較。）
   123	
   124	**兩種口徑、修正前後，四格全部達到 nominal 顯著** —— 「顯著→不顯著」的翻轉在任何一種
   125	讀法下都不成立。（「nominal」不是修辭上的客氣：四格都沒有做多重比較校正，校正後的說法見
   126	下方「多重比較」。翻轉與否的判斷不受影響 —— 前後兩欄用同一個口徑、同一組檢定。）
   127	
   128	## 結果：逐項前後對照
   129	
   130	每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
   131	而中位數與勝率在底下已經移位。
   132	
   133	兩欄使用**相同口徑**，所以差異可歸因於日期本身，不是口徑改動。
   134	
   135	| 指標 | 修正前（proxy） | 修正後（官方，本輪） | 判定 |
   136	|---|---|---|---|
   137	| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
   138	| NFP vs 全體非 NFP（平均） | 1.103× (p=0.129, NS) | 1.108× (p=0.112, NS) | 數值微調 |
   139	| ↳ 中位數比 / 勝率 | 1.188× / 0.555 | 1.192× / 0.561 | 數值微調 |
   140	| 週五 session NFP vs 非 NFP 週五（平均） | 1.167× (p=0.0421, nominal 顯著, n=239) | 1.189× (p=0.0209, **仍 nominal 顯著**；Holm=0.0417, n=237) | 數值微調 |
   141	| ↳ 中位數比 / 勝率 | 1.198× / 0.557 | 1.218× / 0.570 | 數值微調 |
   142	| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
   143	| ↳ 中位數比 / 勝率 | 2.265× / 0.717 | 2.073× / 0.695 | 數值微調 |
   144	| 事前 VIX 相關（Pearson） | 0.451 | 0.440 | 數值微調 |
   145	| ↳ Spearman | 0.377 | 0.346 | 數值微調 |
   146	| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |
   147	
   148	**6 項受稽核宣稱中，0 項結論翻轉。**
   149	
   150	**方向性主結論不變**：以進場 VIX 中位數分組，兩組 NFP 日的波動差距（2.03 倍、p≈4.6e-9）
   151	在數值上遠大於 NFP 對基準的差距（1.11 / 1.19 倍）。
   152	
   153	**這句話的邊界（不要讀過頭）**：這是**條件關聯**，不是因果識別。本實驗**沒有**正式檢定
   154	「2.03 倍顯著大於 1.19 倍」—— 兩者的樣本與對照組都不同，並排只是量級對照，不是統計比較。
   155	也不能反推「所以不是 NFP 本身」：平均差檢定沒拒絕不是零效果的證據，而排序檢定其實拒絕了
   156	（見上）。VIX 分組同時也是**事後**中位數分割，本身帶有樣本內成分。
   157	
   158	### 關於「不顯著」的措辭
   159	
   160	修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
   161	Mann-Whitney 的 p=0.0088 明確顯著 —— 那句總結**與它自己的數字矛盾**。本輪起每個顯著性
   162	陳述都綁定它自己的檢定：
   163	
   164	- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112（Holm 0.112），**未拒絕**
   165	- Welch 平均差（**在週五 session 交易的 NFP** 對非 NFP 週五）：1.189×，p=0.0209，
   166	  **nominal 拒絕**；confirmatory family 內 Holm=0.0417，**仍拒絕**；對全部 22 個
   167	  inferential outputs 校正則 Holm=0.375，**不拒絕**
   168	  —— 條件於週五 session，不是關於 NFP 一般而言，也不是關於「發布日在週五」
   169	- Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019（Holm 0.0058），**拒絕**
   170	
   171	平均差檢定沒拒絕，**不等於**分佈相同，更不是效果為零的證據。|return| 厚尾，
   172	排序檢定抓得到平均檢定抓不到的位移。兩個都報，不合併成單一裁決。
   173	
   174	## 多重比較（Codex 五審 B4）
   175	
   176	這支腳本產出 **22 個 p 值**，先前卻在沒有宣告 family 的情況下，就對其中一個寫「顯著（5%）」。
   177	那不是一個站得住的 5% 宣稱，只是一個 **nominal** 的。
   178	
   179	**Confirmatory family（6 個）** = 上方「方法 § 檢定」那一行列出的六個檢定，也是線上文章唯一
   180	據以做方向性判讀的那些。其餘全部標 **exploratory**。
   181	
   182	| 檢定 | p (nominal) | Holm（family=6） | 5% 存活 |
   183	|---|---|---|---|
   184	| E VIX Pearson | 1.98e-13 | 1.19e-12 | ✓ |
   185	| H VIX regime Welch | 4.55e-09 | 2.28e-08 | ✓ |
   186	| E VIX Spearman | 1.67e-08 | 6.68e-08 | ✓ |
   187	| C Mann-Whitney 單尾 | 0.00194 | 0.00582 | ✓ |
   188	| **B 週五 session Welch** | **0.0209** | **0.0417** | **✓** |
   189	| A vs 全體非 NFP Welch | 0.1121 | 0.1121 | ✗ |
   190	
   191	**週五結果的三種讀法，全部照實報**：
   192	
   193	| 口徑 | 值 | 判定 |
   194	|---|---|---|
   195	| Nominal | p=0.0209 | 拒絕 |
   196	| Holm，confirmatory family（6） | p=0.0417 | 拒絕 |
   197	| Holm，全部 inferential outputs（22） | p=0.375 | **不拒絕** |
   198	
   199	**這個 family 不是預先登記的，必須講清楚。** 六個 endpoint 早於日期修正與本輪重跑就存在
   200	（可由修正前的腳本版本查證），但**沒有**在看到資料之前被登記下來。所以：
   201	
   202	- 兩種 family 的結果**並列呈現**，不挑對自己有利的那個講
   203	- 可以寫的：「nominal 顯著；在六項 confirmatory family 內通過 Holm 校正（**該 family 非預先登記**，
   204	  且對全部 22 個 inferential outputs 校正後不拒絕 —— 見上方三種讀法）」
   205	- **不可以寫的**：不加限定的「顯著」、或宣稱它對任何 family 選擇都穩健
   206	
   207	**為什麼用 Holm 不用 Romano-Wolf**：這個 family 混了 Welch t、Mann-Whitney U 與兩個相關檢定，
   208	且樣本互相重疊；沒有單一 resampling 方案對四者同時有效。Holm 在**任意相依**下都控制 FWER。
   209	Romano-Wolf 在存在合適聯合重抽方案時更有檢定力 —— 但為了換檢定力而自行發明一個方案，
   210	在一份專門處理「過度宣稱」的更正裡是錯的取捨。
   211	
   212	機器可讀版本在結果檔的 `multiplicity`，且每個檢定條目都被**機械蓋章**（`_stamp`）標上它所屬
   213	的 family 與校正值；新增檢定卻沒歸入 family 會讓 run 失敗，避免「未宣告 family」被重新蓋回來。
   214	
   215	## 產出檔案
   216	
   217	| 檔案 | 內容 |
   218	|---|---|
   219	| `k528_nfp_event_study.py` | 主腳本（官方日曆版，含前後對照 audit 段） |
   220	| `k528_nfp_event_study_results.json` | 修正後結果（現行 canonical） |
   221	| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
   222	| `k528_nfp_official_dates_results.json` | 逐項前後對照 + 換掉的日期 + 文章更正替換清單 |
   223	| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
   224	| `k528_rerun_v3_summary.json` | 本輪修正的機器可讀摘要 |
   225	| `review_verdict_v3.json` / `codex_review_v3.md` | Codex 三審裁決與全文 |
   226	| `test_k528_completeness_gate.py` | 日曆完整性 gate 的對抗測試（14 passed，含端點截斷與反空洞） |
   227	| `test_k528_price_coverage_gate.py` | 價格覆蓋 / VIX 新鮮度 gate 的對抗測試（10 passed） |
   228	| `k528_round5_remediation.json` | 五審四個 blocker 的處置紀錄（before/after、證據、測試、Holm 表） |
   229	
   230	## 線上文章更正（`mile_35eef830`）
   231	
   232	### ⚠️ 原 18 條更正清單已全數作廢
   233	
   234	原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
   235	改寫成「p=0.057，差一點過線但沒過」）。文章原本寫的是對的；套用那 18 條等於發佈一則
   236	撤回正確結論的更正。作廢原因已寫入 `k528_nfp_official_dates_results.json` 的
   237	`article_correction.supersedes`。
   238	
   239	### 新清單：19 條，全部是數值重述，0 條方向翻轉
   240	
   241	文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、進場 VIX
   242	高低兩組的差距是本研究中最大的數字 —— 在官方日期下**全部成立**（第三點的邊界見上文
   243	「這句話的邊界」：是量級並排，不是排名，也未做正式比較）。新清單只改數字
   244	（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
   245	外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。
   246	
   247	19 條已對線上 canonical 文章驗證，全部恰好命中一次。
   248	
   249	```bash
   250	# 主線程在 repo root 執行
   251	uv run python experiments/k528/build_article_correction.py            # 驗證（不寫任何檔）
   252	uv run python experiments/k528/build_article_correction.py --apply    # 寫入 + sync
   253	```
   254	
   255	**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
   256	`.claude/rules/worktree.md` 明文禁止 worktree agent 觸碰。這不是形式規定 —— 本 worktree
   257	自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
   258	合併回去會把期間發佈的文章靜默蓋掉。因此拆成：worktree 負責解析與驗證，主線程負責寫入。
   259	
   260	**未解決的缺口**：文中兩張圖表（`nfp_20260703_regime.png`、`nfp_20260703_baseline.png`）
   261	與文末兩張懶人包圖仍是修正前的數據，圖片內容無法用文字替換修正。更正後正文與圖片會不一致，
   262	因此更正說明中已明寫「圖表仍是初版數據，正在重新產製」。重新產圖 + 上傳 Supabase 屬後續工作。
   263	
   264	## 防迴歸
   265	
   266	事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：
   267	
   268	- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、其中 237 筆在週五
   269	  session 交易（對照官方 BLS 日曆的 243 筆發布日在週五，兩者差額為六個順延到下週一
   270	  session 的 Good Friday 發布，見上文 §估計量）、212 個日期共通、結果檔宣告 fail-closed
   271	- `test_no_off_cycle_revision_date_is_treated_as_an_event` — **直接釘住 v2 BLOCKER**：
   272	  對 artifact 斷言六個 off-cycle 日期不在事件集合、六個正式發布日在。對 artifact 而非
   273	  只對 accessor 斷言，因為「accessor 是對的」不能證明「出貨的結果用了它」
   274	- `TestControlGroupHasNoNfpDays` — 釘住控制組不含任何已映射 NFP session
   275	- `TestCalendarFailClosedCannotBeBypassed` — 逐條釘住三審找到的繞過路徑：較早的
   276	  off-cycle、選擇非最早、跨度內缺月、allowlist 濫用；外加一個**必須通過**的乾淨日曆
   277	  （只會拒絕的 guard 和永不拒絕的一樣沒用）
   278	- `TestFridayEstimandIsScopedHonestly` — 釘住 conditional estimand 有標示、
   279	  非中性排除有揭露、排除筆數與 weekday 分解一致（結果檔曾經散文寫 11、資料寫 16）
   280	- `TestProxyMutationIsCaught` — mutation test：proxy 日曆餵給 guard 必須被拒；
   281	  只塞回幻影的 2025-10-03 也必須被抓；同時驗證 guard 不會誤殺官方日曆
   282	- `test_no_live_artifact_describes_the_237_as_a_release_count` + `TestReleaseMisbindingGateIsStructural`
   283	  — 釘住「237 不是 Friday-release 數，而是 Friday-session 數」的措辭不變量。
   284	  **宣稱 vs 實際的落差（round-7 N1 修）**：round-6 裁決把這個 gate 描述成「結構性不變量」，
   285	  但它當時其實只是**5 詞字面 blocklist + 兩個無條件行豁免**（同行出現 `243` 就整行放行、
   286	  同行出現否定詞就整行放行）。round-6 收件審查用注入證明它**擋不住**：4 個同義改寫
   287	  （「237 場 NFP 是週五發布的」「published on a Friday」「publication day was a Friday」
   288	  「限定週五發布的 237 場」）全部溜過，行內無關 `243`（如「243 trading weeks」）與鄰句的
   289	  否定詞都能挾持豁免。round-7 把它換成**組合式、就近支配（nearest-governor）**的結構檢查：
   290	  release-dated 語意 = Friday token 的最近支配動詞是 release/發布 類（而非 session/交易 類），
   291	  引號內的片語視為「提及」不計入綁定，否定詞豁免收緊為 clause-local。6 個注入 + 2 個
   292	  legitimate 反例（正確對照 / 正確 errata）全部進 `TestReleaseMisbindingGateIsStructural`，
   293	  硬化後 6 擋 2 放，已用真實檔案注入探針端到端驗證。
   294	
   295	accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
   296	`tests/test_event_dates_real_raw_response.py`（未經編輯的 ALFRED 日期清單 + mutation 檢查）。
   297	後者的 scope 有明寫：它釘的是 `_fetch` 的**回傳值**（原樣、未去重），不是完整 HTTP
   298	response body，所以 `_fetch` 自身的 schema 破壞不在覆蓋範圍內。
   299	
   300	Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
   301	由綠轉紅（`2006-05-08 != 2006-05-05`），還原後 99 passed。沒被實際觸發過的 gate 不算 gate。
   302	
   303	## 主腳本的 fail-closed 面
   304	
   305	**這一節的宣稱範圍（2026-07-20 收緊）**：以下關卡對「**無聲的**資料短少」fail-closed
   306	—— 取不到日曆、選錯同月條目、跨度內缺月、raw 與 selected 不一致、端點月被截掉、
   307	價格序列覆蓋不足、VIX 陳舊。它們**不**涵蓋「有人寫下一則假的 `KNOWN_MISSING_MONTHS`
   308	理由、同時把該月從 raw feed 移除」這種**有文件的假宣稱**。
   309	先前這一節寫得像是後者也涵蓋在內；那是溢出的宣稱，已撤回。
   310	
   311	**日曆完整性**（`check_calendar_is_complete`）**同時驗證 raw feed 與 accessor 的選擇**。
   312	只驗證 accessor 的**輸出**是行不通的：accessor 在把資料交出來之前就已經把每個月收斂成一個
   313	日期，等到能檢查輸出的時候，同月歧義早就被（可能錯誤地）默默解決掉了。四道關卡：
   314	
   315	0. 選擇本身要 well-formed：同一個月被選了兩次 → raise；選出來的月份/日期不存在於 raw
   316	   feed → raise（否則後面用 `dict` 建 month→date 對照時，重複的月份會被靜默蓋掉，
   317	   剛好蓋掉我們要找的東西）
   318	1. 選到的不是該月最早一筆 → raise（這正是 v2 BLOCKER 的形狀）
   319	2. 任何同月多筆的月份**必須列在 `REVIEWED_MULTI_ENTRY_MONTHS`**，且選到的日期要與人工
   320	   核對過的答案一致 → 否則 raise（理由見下方「殘留限制」）
   321	3. 觀測跨度**沒有覆蓋到請求視窗**（頭尾任一端短少 > 70 天）→ raise。只檢查跨度「內部」
   322	   的缺口抓不到截斷：feed 提早結束的話，跨度會跟著縮短，於是看起來什麼都不缺
   323	4. 觀測跨度內缺月 → raise。錨定在實際觀測跨度而非 `[start, end]`，移除了舊版
   324	   「首尾月無條件豁免」的漏洞（完整的首月照樣可以無聲消失）
   325	5. `KNOWN_MISSING_MONTHS` 宣稱的缺口，會回頭去 raw feed **驗證它真的是缺口** → 有資料就
   326	   raise。沒有這一關，allowlist 就只是「讓失敗的檢查通過」的另一個名字
   327	6. **端點期望**（本輪新增，見下）：由**請求視窗**推導出「哪些月份非有不可」，
   328	   raw 與 selected 同時被截掉一個端點月時仍會 raise
   329	
   330	### 端點期望 —— 修掉「同刪首/尾月仍通過」（Codex 五審 B2）
   330	### 端點期望 —— 修掉「同刪首/尾月仍通過」（Codex 五審 B2）
   331	
   332	**上面第 1–5 關全都是拿 feed 檢查 feed**：比對 raw 與 selected、或看觀測跨度內部。
   333	把一個端點月**從 raw 和 selected 同時刪掉**，這些關卡全部依然自洽 —— raw 與 selected 仍然
   334	一致、跨度仍然沒有內部缺口、70 天容忍度剛好容得下整整一個月。Codex 獨立重現：
   335	
   336	| 攻擊 | raw/selected | head 短少 | tail 短少 | 舊版判定 |
   337	|---|---|---|---|---|
   338	| 刪 `2005-01` | 259 / 253 | 34d | 21d | **通過** |
   339	| 刪 `2026-03` | 259 / 253 | 6d | 44d | **通過** |
   340	
   341	修法是引進一個 feed 動不到的量尺：**請求視窗本身**。若視窗完整包含某月的可能發布區間
   342	（該月 1 日 ~ `LATEST_OBSERVED_RELEASE_DAY_OF_MONTH`），該月就**必須**有一筆發布。
   343	截短 feed 不會改變請求視窗，所以期望不會跟著縮水。
   344	
   345	那個常數（=22，來自 2013-10-22，2013 年關門延後的最晚一筆）**會自我巡查**：
   346	feed 裡若出現比它更晚的發布，代表這條規則的前提過期了，run 直接 raise 要求重新推導，
   347	而不是默默地少要求幾個月。
   348	
   349	**這一關是實測過會響的，不是宣稱**（`test_k528_completeness_gate.py`，14 passed）：
   350	
   351	- `test_endpoint_month_deleted_from_raw_and_selected_is_rejected[head|tail]` —— 攻擊被擋
   352	- `test_endpoint_truncation_is_invisible_without_the_new_check[head|tail]` —— **反空洞**：
   353	  只把這一關關掉、其餘防線全留，同樣的攻擊就**被接受**。這是修復前的行為，
   354	  它證明上面那條測試測的不是一個本來就已經work的東西
   355	- `test_endpoint_expectation_is_derived_from_the_window_not_the_feed` —— 釘住「縮小請求視窗
   356	  會改變要求、截短 feed 不會」這個性質本身
   357	- `test_release_later_than_the_constant_invalidates_the_expectation` —— 釘住常數自我巡查
   358	
   359	直接的前後對照（同一支攻擊分別餵給 HEAD `73dca01d0` 與修復後）：
   360	
   361	```
   362	--- PRE-FIX  (HEAD 73dca01d0) ---
   363	  delete head month 2005-01: ACCEPTED  (259 raw / 253 selected, head_short=34d tail_short=21d)
   364	  delete tail month 2026-03: ACCEPTED  (259 raw / 253 selected, head_short=6d  tail_short=44d)
   365	--- POST-FIX (working tree) ---
   366	  delete head month 2005-01: RAISED    the requested window ... fully contains the publication window of 1 month(s)...
   367	  delete tail month 2026-03: RAISED    the requested window ... fully contains the publication window of 1 month(s)...
   368	```
   369	
   370	**殘留限制（明講）**：端點期望仍可被「把該月加進 `KNOWN_MISSING_MONTHS`」壓掉。
   371	那是刻意的 —— 2025-10 確實被取消 —— 並且由第 5 關（回頭驗 raw feed）限制住。
   372	沒被涵蓋的情形是：**同時把該月從 raw feed 刪掉、又書面宣告它不存在**。
   373	那是一則**有文件的假宣稱**，不是無聲截斷。**本 gate 對後者 fail-closed，對前者不是。**
   374	
   375	### 價格資料的覆蓋與新鮮度（Codex 五審 B3）
   376	
   377	日曆有五道完整性關卡，被它 join 的**價格序列先前一道都沒有**。SPY 尾端少一個月不會拋錯、
   378	也不會產生 NaN —— 超出範圍的發布會被靜靜歸類成 `outside_price_sample`，計數、然後跳過。
   379	^VIX 尾端短缺更糟：`ffill()` 會把最後一筆真實報價蓋到之後每一個 session 上，
   380	於是 regime 分組與相關檢定跑在一個看起來像資料的常數上。
   381	
   382	本輪新增（`check_price_coverage` / `check_vix_forward_fill_age`，都寫成**函式**以便被測試
   383	攻擊 —— 沒被實際觸發過的 guard 與不存在的 guard 失效方式相同）：
   384	
   385	- SPY 與 ^VIX 都必須覆蓋到請求視窗兩端（容忍 10 天，涵蓋最長的假日連休）
   386	- `n_outside_price_sample` 必須為 **0**。此固定歷史樣本的日曆與價格用同一個視窗請求、
   387	  且兩端都已驗證，所以「發布落在價格樣本外」不再是設計邊界，而是下載短少
   388	- forward-fill 的 VIX 最多只能連續攜帶 **3 個 session**（本樣本實測最大值 = 0）
   389	
   390	`test_k528_price_coverage_gate.py`（10 passed）逐項攻擊：頭/尾各刪一個月、空下載、
   391	VIX 尾端截短一個月、VIX 開頭缺值；外加正面控制（完整覆蓋要通過、單日假日缺口要允許
   392	forward-fill）與一個反空洞測試（證明 `ffill` 自己**不會**抗議，所以擋下它的是這道 gate）。
   393	
   394	**一次我自己搞砸又修回來的紀錄**（留著，因為它是這份文件最有用的部分）：
   395	
   396	我一度宣稱「同月兩筆間隔 < 3 天視為無法辨識」這一關被真實資料推翻 —— 理由是六個真實
   397	同月多筆月份裡有三個（2006-05、2013-05、2020-05）剛好間隔 **3 天**，看起來資料橫跨在
   398	門檻上。**那是我讀錯了自己寫的條件**：判斷式是 `gap < 3`，而 3 天是**通過**的。真實資料
   399	從頭到尾沒有推翻這一關；是我先把 `<` 改成 `<=`（於是它開始誤報三個合法月份），再拿這個
   400	自己造成的誤報當證據，把整關刪掉。
   401	
   402	Codex 第四輪指出這件事，該關已還原為 `< 3`（六個真實案例全部通過）。
   403	`tests/...::test_real_multi_entry_gaps_are_too_small_for_a_gap_rule` 釘住「最小 gap = 3」
   404	這個事實，讓下一個想動這個門檻的人先看到真實分佈。
   405	
   406	教訓不是「別碰啟發式」，而是：**在拿資料推翻一條規則之前，先確認你測的是那條規則本身，
   407	而不是你剛剛改壞的版本。**
   408	
   409	已知的真實缺口只有 2025-10（政府關門），每筆都要附理由字串。
   410	
   411	**殘留限制（明講，不假裝已完全關上）**：同月選擇用的「取最早一筆」是**啟發式**。它對目前
   412	查過的每一個案例都對，但它無法區分「比正式報告**更早**歸檔的 off-cycle 項目」與報告本身
   413	—— 單靠日期不可能分辨。因此規則照跑，但**額外**要求每個同月多筆的月份都出現在
   414	`REVIEWED_MULTI_ENTRY_MONTHS`（六個月份逐一對照 BLS news-release archive 驗證過）。
   415	新出現的同月多筆月份會**讓整個 run 失敗**，而不是被這支腳本自行假設掉。
   416	第 4、第 3 兩關是三審 round-2 進行期間自查補上的。
   417	
   418	**事件日→交易日對映**：一對一完整性斷言。樣本內發布日找不到三日內交易日 → raise；
   419	兩個發布日映射到同一個 session → raise（原本的 `set()` 去重會把這件事藏起來並靜默減少
   420	事件數）。窗口邊界排除改為明確記錄在 `sample.event_mapping_audit`，不再靜默 `continue`。
   421	
   422	**控制組不含任何 NFP session**：對照組排除**全部 254 個**已映射 NFP session，不只是通過
   423	事件窗篩選的 253 個。因窗口不足被排除的 `2005-01-07` 仍然是真實的 NFP 日，把它留在對照組
   424	就是本實驗存在的理由（「把真的事件日丟進對照組」）的 1/253 版本。三審 Codex 與本輪自查
   425	獨立發現同一件事。
   426	
   427	**原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`。
   428	
   429	## 參考
   430	
   431	- K1442 事件日期稽核（發現 proxy bug）；`event_article_nfp_2026_07_03_t1` 修正報告 §7
   432	- `docs/error_log.md` 2026-07-12 CPI 事件研究發布日條目（同一 bug class 的前例）
   433	- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
   434	- K513：先前的 FOMC/NFP/CPI 事件研究

2026-07-27T00:31:30.255373Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "nl -ba experiments/k528/build_article_correction.py | sed -n '298,348p'
nl -ba experiments/k528/README.md | sed -n '1,215p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
   298	def main() -> int:
   299	    ap = argparse.ArgumentParser(description=__doc__)
   300	    ap.add_argument("--apply", action="store_true",
   301	                    help="write the correction (main thread, repo root only)")
   302	    ap.add_argument("--record-plan", action="store_true",
   303	                    help="record the validated plan into the audit JSON without applying it")
   304	    ap.add_argument("--storage-dir", default=str(REPO_ROOT / "storage"))
   305	    args = ap.parse_args()
   306	
   307	    storage_dir = Path(args.storage_dir)
   308	    validated = validate(storage_dir)
   309	    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
   310	    for v in validated:
   311	        head = v["from"].splitlines()[0][:64]
   312	        print(f"  @{v['offset']:>6}  {head}...")
   313	
   314	    applied = None
   315	    if args.apply:
   316	        from volpred.publisher.article_correction import apply_article_correction
   317	
   318	        applied = apply_article_correction(
   319	            ARTICLE_ID,
   320	            content_replacements=REPLACEMENTS,
   321	            summary=(
   322	                "K528 event dates corrected from a first-Friday proxy to the official BLS "
   323	                "release calendar. Sample 254 -> 253 events; headline numbers restated "
   324	                "(1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, "
   325	                "r 0.45->0.44). No directional conclusion changes. The Friday comparison "
   326	                "now restricts the event group to the 237 releases absorbed by a Friday "
   327	                "SESSION so weekday is held fixed on both sides -- 243 releases are dated "
   328	                "a Friday, but six of those are Good Fridays traded the following Monday."
   329	            ),
   330	            action="content_correction",
   331	            storage_dir=str(storage_dir),
   332	        )
   333	        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
   334	              f"synced={applied['synced']}")
   335	
   336	    # A dry run that rewrites the audit file is not a dry run (k528 Codex v2
   337	    # finding 7). Recording is opt-in and never implicit.
   338	    if args.apply or args.record_plan:
   339	        record_plan(validated, applied)
   340	        print(f"plan recorded in {AUDIT_PATH.name}")
   341	    else:
   342	        print("\ndry run -- nothing written. Re-run with --apply from the repo root, "
   343	              "or --record-plan to persist the validated plan only.")
   344	    return 0
   345	
   346	
   347	if __name__ == "__main__":
   348	    raise SystemExit(main())
     1	# k528 — NFP 事件研究（SPY 波動率）
     2	
     3	- Experiment ID: `k528`
     4	- Created At: 2026-04-16T09:39:52.904348+00:00
     5	- Corrected At: 2026-07-19（事件日期來源修正，全樣本重跑；同日第二次修正見下）
     6	- Status: 已重跑，**方向性結論全部不變**，僅數值微調 + 一項口徑澄清
     7	
     8	## 問題描述
     9	
    10	NFP（非農就業）公布日，SPY 的波動是否會系統性放大？如果會，放大的來源是「NFP 這個
    11	事件本身」，還是「進場當下的市場狀態」？
    12	
    13	## 兩次修正，不要混為一談
    14	
    15	本實驗在 2026-07-19 被修正了**兩次**，第二次是修第一次修壞的地方。
    16	
    17	### 修正 1：事件日期從 proxy 換成官方日曆
    18	
    19	原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 錯得有結構、不是隨機噪音：
    20	
    21	- BLS 在參考週較晚的月份會改到**第二個週五**發布
    22	- 遇到聯邦假期會**提前**
    23	- **2025-10 根本沒有發布**（政府關門取消），proxy 卻憑空生出一場
    24	- proxy 把每一場都放在**週五**；官方日曆的 253 場有 243 場**發布日**在週五，
    25	  其中 237 場**在週五的交易 session 被吸收**（差額是六個 Good Friday，見下）
    26	
    27	錯的事件日期不會拋錯、不會出現 NaN，圖照樣畫得出來 —— 它只是把安靜的日子算成事件日、
    28	同時把真的事件日丟進對照組。這是修正存在的理由。
    29	
    30	`get_first_friday()` 已**整條移除**（不是標 deprecated），日期改由
    31	`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
    32	release id 50），且**取不到就 raise，不回退 proxy**。
    33	
    34	### 修正 2（本輪）：accessor 的同月多筆選擇錯誤
    35	
    36	第一次修正的 accessor 對「同月多筆 release 條目」取 `max()`。ALFRED 的 release id 50
    37	在**六個月份**會回兩筆：前一筆是 Employment Situation 正式報告，後一筆是年度季節調整
    38	因子／benchmark 修訂。`max()` 選到了後者 —— 也就是**把修訂當成了就業報告**：
    39	
    40	| 月份 | 正確（正式發布） | `max()` 誤選（off-cycle 修訂） |
    41	|---|---|---|
    42	| 2006-05 | 2006-05-05 | 2006-05-08 |
    43	| 2012-12 | 2012-12-07 | 2012-12-12 |
    44	| 2013-05 | 2013-05-03 | 2013-05-06 |
    45	| 2020-05 | 2020-05-08 | 2020-05-11 |
    46	| 2024-01 | 2024-01-05 | 2024-01-10 |
    47	| 2024-08 | 2024-08-02 | 2024-08-21 |
    48	
    49	六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
    50	**第一次修正因此得出了一個錯誤的「顯著→不顯著」翻轉，並據此準備了 18 條文章更正 ——
    51	那 18 條會把一個本來正確的結論撤回。** Codex 二審判 FAIL 擋下，未套用。
    52	
    53	根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
    54	fail-closed 驗證，commit `305d118a3`）。
    55	
    56	**為什麼原本 42 個測試全綠卻沒抓到**：fixture 是手寫的，同月第二筆事先就被刪掉了 ——
    57	測試餵進去的輸入根本表達不出這個 bug。修法不是加更好的斷言，是餵真實輸入：
    58	`tests/test_event_dates_real_raw_response.py` 直接釘住 ALFRED 的 264 筆原始回應
    59	（fixture `tests/fixtures/fred_release_50_nfp_raw_20260719.json`，**禁止去重**，
    60	那六對重複就是迴歸面），並附 mutation 檢查證明舊 `max()` 規則會在這份輸入上失敗。
    61	
    62	## 方法
    63	
    64	- 資料：SPY / ^VIX 日頻（yfinance），2005-01 至 2026-03
    65	- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
    66	- 事件窗：T-5 ~ T-1（前）、T（當日）、T+1 ~ T+5（後）
    67	- 檢定（**這六個就是 confirmatory family**，見下方「多重比較」）：Welch t（vs 全體非 NFP
    68	  日 / vs 非 NFP 週五 session）、Mann-Whitney U、VIX 中位數分組 regime 檢定、
    69	  Pearson / Spearman 相關
    70	- 其餘一切（12 個月份格、vol crush、VIX buildup、時間趨勢、方向 binomial）一律
    71	  **exploratory**，只作描述，**不得**當成 5% 發現引用
    72	
    73	### 週五基準的口徑（estimand）調整
    74	
    75	> **口徑更正（2026-07-20，Codex 五審 B1）**：本節此前寫的是「**在週五公布**的 NFP」。
    76	> 程式篩的其實是**在週五交易 session 被吸收**的 NFP —— 兩者差六場。
    77	> 253 場有效發布中，**243 場發布日在週五**，但只有 **237 場在週五開盤**：
    78	> 2007-04-06、2010-04-02、2012-04-06、2015-04-03、2021-04-02、2023-04-07
    79	> 全是 **Good Friday**，BLS 照常公布、市場休市，消息由**下週一**吸收。
    80	>
    81	> **1.189× / p=0.0209 識別的是「週五 session 是否因吸收 NFP 而波動更大」，
    82	> 不是「發布日落在週五的 NFP」。** 全文已改用前者措辭。
    83	>
    84	> **為什麼是 session weekday 而不是 release weekday**（這不是圖方便，是唯一正確的那個）：
    85	> 被比較的量是**一個 session 的報酬**，要被固定住的干擾是**那個 session 的星期效應**。
    86	> 若改用發布日 weekday 篩 243 場，等於把六筆**週一報酬**放進一個對照組是純週五的比較裡
    87	> —— 那正好把這個限制存在的理由（星期別污染）重新放回來。
    88	> 審查給的另一條路（release weekday + weekday-matched controls）內部自洽，
    89	> 但它回答的是另一個問題，且估計更吵（見下方薄格數的討論）。
    90	
    91	事件組是**星期別混合**、對照組是**純週五**，週五本身的波動特性會直接混進 p 值。
    92	
    93	**這個缺陷不是日期修正造成的 —— 修正只是讓它被看見。** proxy 的*日曆*確實每場都是週五，
    94	但遇休市會映射到下一個 session，所以它實際的 254 場事件裡有 **15 場是週一**（239/254 =
    95	94.1% 在週五）；官方日曆是 237/253 = 93.7%。混合程度幾乎沒變，舊版一直都在拿混合事件組
    96	比純週五對照組，只是從來沒人注意到。
    97	
    98	本輪把事件組**限定為在週五 session 交易的 237 場**，兩邊星期別一致。另一個選項是保留全部
    99	253 場改用 weekday-matched controls，未採用的理由：被排除的 16 場按 **session** 星期別是
   100	週一 6、週二 2、週三 1、週四 7，用這種格數做加權平均，標準誤會被 1 筆的週三格主導
   101	—— 那是對一個更難陳述的量做更吵的估計。
   102	
   103	（那 6 筆週一 session 就是上面的六個 Good Friday；其餘 10 筆是發布日本身就不在週五
   104	—— 週二 2、週三 1、週四 7。兩種來源合起來 16 筆，與 253 − 237 一致。）
   105	
   106	**限定週五不是中性的樣本刪除，這點必須明講**：被排除的 16 場平均 |ret| 是 0.715%，比週五
   107	NFP 的 0.854% **低 16.3%**，所以限定之後 ratio 會被墊高（1.177× → 1.189×）。那是口徑的
   108	性質，不是效果變強的證據。（六個 Good Friday 子集平均 |ret| = 0.715%，與 16 場整體幾乎
   109	相同 —— 巧合，不是同一個數字，兩者都由 `sample.friday_estimand` 與 `event_data` 算得出。）
   110	
   111	**因此這個檢定識別的是「在週五 session 被吸收的 NFP」**，既不是「NFP 一般而言」，
   112	也不是「發布日在週五的 NFP」。引用這個數字的文字必須寫「在週五交易 session 的 NFP」。
   113	
   114	兩種口徑在 audit 中**兩邊平行呈現**（修正前後各自都算了兩種），不拿不同口徑硬比：
   115	
   116	| | 限定週五（主口徑） | 混合星期別（舊口徑） |
   117	|---|---|---|
   118	| 修正前（proxy） | 1.167× / p=0.0421 / n=239 | 1.168× / p=0.0335 / n=254（文章當初引用的） |
   119	| 修正後（官方） | **1.189× / p=0.0209 / n=237** | 1.177× / p=0.0257 / n=253（DIAGNOSTIC ONLY） |
   120	
   121	（proxy 側的兩格對照組定義不同：限定週五那格用的是**去洩漏**的對照組 832 筆，
   122	「文章當初引用的」那格保留當年含洩漏的原值 —— 前者才是與修正後同口徑的比較。）
   123	
   124	**兩種口徑、修正前後，四格全部達到 nominal 顯著** —— 「顯著→不顯著」的翻轉在任何一種
   125	讀法下都不成立。（「nominal」不是修辭上的客氣：四格都沒有做多重比較校正，校正後的說法見
   126	下方「多重比較」。翻轉與否的判斷不受影響 —— 前後兩欄用同一個口徑、同一組檢定。）
   127	
   128	## 結果：逐項前後對照
   129	
   130	每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
   131	而中位數與勝率在底下已經移位。
   132	
   133	兩欄使用**相同口徑**，所以差異可歸因於日期本身，不是口徑改動。
   134	
   135	| 指標 | 修正前（proxy） | 修正後（官方，本輪） | 判定 |
   136	|---|---|---|---|
   137	| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
   138	| NFP vs 全體非 NFP（平均） | 1.103× (p=0.129, NS) | 1.108× (p=0.112, NS) | 數值微調 |
   139	| ↳ 中位數比 / 勝率 | 1.188× / 0.555 | 1.192× / 0.561 | 數值微調 |
   140	| 週五 session NFP vs 非 NFP 週五（平均） | 1.167× (p=0.0421, nominal 顯著, n=239) | 1.189× (p=0.0209, **仍 nominal 顯著**；Holm=0.0417, n=237) | 數值微調 |
   141	| ↳ 中位數比 / 勝率 | 1.198× / 0.557 | 1.218× / 0.570 | 數值微調 |
   142	| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
   143	| ↳ 中位數比 / 勝率 | 2.265× / 0.717 | 2.073× / 0.695 | 數值微調 |
   144	| 事前 VIX 相關（Pearson） | 0.451 | 0.440 | 數值微調 |
   145	| ↳ Spearman | 0.377 | 0.346 | 數值微調 |
   146	| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |
   147	
   148	**6 項受稽核宣稱中，0 項結論翻轉。**
   149	
   150	**方向性主結論不變**：以進場 VIX 中位數分組，兩組 NFP 日的波動差距（2.03 倍、p≈4.6e-9）
   151	在數值上遠大於 NFP 對基準的差距（1.11 / 1.19 倍）。
   152	
   153	**這句話的邊界（不要讀過頭）**：這是**條件關聯**，不是因果識別。本實驗**沒有**正式檢定
   154	「2.03 倍顯著大於 1.19 倍」—— 兩者的樣本與對照組都不同，並排只是量級對照，不是統計比較。
   155	也不能反推「所以不是 NFP 本身」：平均差檢定沒拒絕不是零效果的證據，而排序檢定其實拒絕了
   156	（見上）。VIX 分組同時也是**事後**中位數分割，本身帶有樣本內成分。
   157	
   158	### 關於「不顯著」的措辭
   159	
   160	修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
   161	Mann-Whitney 的 p=0.0088 明確顯著 —— 那句總結**與它自己的數字矛盾**。本輪起每個顯著性
   162	陳述都綁定它自己的檢定：
   163	
   164	- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112（Holm 0.112），**未拒絕**
   165	- Welch 平均差（**在週五 session 交易的 NFP** 對非 NFP 週五）：1.189×，p=0.0209，
   166	  **nominal 拒絕**；confirmatory family 內 Holm=0.0417，**仍拒絕**；對全部 22 個
   167	  inferential outputs 校正則 Holm=0.375，**不拒絕**
   168	  —— 條件於週五 session，不是關於 NFP 一般而言，也不是關於「發布日在週五」
   169	- Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019（Holm 0.0058），**拒絕**
   170	
   171	平均差檢定沒拒絕，**不等於**分佈相同，更不是效果為零的證據。|return| 厚尾，
   172	排序檢定抓得到平均檢定抓不到的位移。兩個都報，不合併成單一裁決。
   173	
   174	## 多重比較（Codex 五審 B4）
   175	
   176	這支腳本產出 **22 個 p 值**，先前卻在沒有宣告 family 的情況下，就對其中一個寫「顯著（5%）」。
   177	那不是一個站得住的 5% 宣稱，只是一個 **nominal** 的。
   178	
   179	**Confirmatory family（6 個）** = 上方「方法 § 檢定」那一行列出的六個檢定，也是線上文章唯一
   180	據以做方向性判讀的那些。其餘全部標 **exploratory**。
   181	
   182	| 檢定 | p (nominal) | Holm（family=6） | 5% 存活 |
   183	|---|---|---|---|
   184	| E VIX Pearson | 1.98e-13 | 1.19e-12 | ✓ |
   185	| H VIX regime Welch | 4.55e-09 | 2.28e-08 | ✓ |
   186	| E VIX Spearman | 1.67e-08 | 6.68e-08 | ✓ |
   187	| C Mann-Whitney 單尾 | 0.00194 | 0.00582 | ✓ |
   188	| **B 週五 session Welch** | **0.0209** | **0.0417** | **✓** |
   189	| A vs 全體非 NFP Welch | 0.1121 | 0.1121 | ✗ |
   190	
   191	**週五結果的三種讀法，全部照實報**：
   192	
   193	| 口徑 | 值 | 判定 |
   194	|---|---|---|
   195	| Nominal | p=0.0209 | 拒絕 |
   196	| Holm，confirmatory family（6） | p=0.0417 | 拒絕 |
   197	| Holm，全部 inferential outputs（22） | p=0.375 | **不拒絕** |
   198	
   199	**這個 family 不是預先登記的，必須講清楚。** 六個 endpoint 早於日期修正與本輪重跑就存在
   200	（可由修正前的腳本版本查證），但**沒有**在看到資料之前被登記下來。所以：
   201	
   202	- 兩種 family 的結果**並列呈現**，不挑對自己有利的那個講
   203	- 可以寫的：「nominal 顯著；在六項 confirmatory family 內通過 Holm 校正（**該 family 非預先登記**，
   204	  且對全部 22 個 inferential outputs 校正後不拒絕 —— 見上方三種讀法）」
   205	- **不可以寫的**：不加限定的「顯著」、或宣稱它對任何 family 選擇都穩健
   206	
   207	**為什麼用 Holm 不用 Romano-Wolf**：這個 family 混了 Welch t、Mann-Whitney U 與兩個相關檢定，
   208	且樣本互相重疊；沒有單一 resampling 方案對四者同時有效。Holm 在**任意相依**下都控制 FWER。
   209	Romano-Wolf 在存在合適聯合重抽方案時更有檢定力 —— 但為了換檢定力而自行發明一個方案，
   210	在一份專門處理「過度宣稱」的更正裡是錯的取捨。
   211	
   212	機器可讀版本在結果檔的 `multiplicity`，且每個檢定條目都被**機械蓋章**（`_stamp`）標上它所屬
   213	的 family 與校正值；新增檢定卻沒歸入 family 會讓 run 失敗，避免「未宣告 family」被重新蓋回來。
   214	
   215	## 產出檔案

2026-07-27T00:31:35.662935Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "jq '.. | objects | with_entries(select(.key|test(\"std|variance|var"'$";"i"))) | select(length>0)'"' experiments/k528/k528_nfp_event_study_results.json" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
2026-07-27T00:31:51.050201Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c \"
import json, math
from pathlib import Path
import numpy as np
from scipy import stats
r=json.loads(Path('experiments/k528/k528_nfp_event_study_results.json').read_text())
au=json.loads(Path('experiments/k528/k528_nfp_official_dates_results.json').read_text())
e=r['event_data']; absret=np.array([x['event_abs_return'] for x in e],float); pre=np.array([x['pre_vix'] for x in e],float)
fr=np.array([x['session_weekday']==4 for x in e]); relfr=np.array([x['release_weekday']==4 for x in e]); high=absret[pre>=np.median(pre)]; low=absret[pre<np.median(pre)]
rr=stats.pearsonr(pre,absret); sr=stats.spearmanr(pre,absret); tw=stats.ttest_ind(high,low,equal_var=False)
def holm(ps):
 order=np.argsort(ps); out=np.empty(len(ps)); run=0.0
 for rank,i in enumerate(order):
  run=max(run,(len(ps)-rank)*ps[i]); out[i]=min(run,1)
 return out
def welch(xs,cm,cn,t):
 m=xs.mean(); v=xs.var(ddof=1); se2=((m-cm)/t)**2; cv=(se2-v/len(xs))*cn; df=se2**2/((v/len(xs))**2/(len(xs)-1)+(cv/cn)**2/(cn-1)); return {'event_mean':m,'control_mean':cm,'control_sd_implied':math.sqrt(cv),'df_implied':df,'p_from_t_df':2*stats.t.sf(abs(t),df)}
cf=r['multiplicity']['confirmatory_family']['members']; af=r['multiplicity']['all_outputs_family']['members']; bix=[x['test'] for x in cf].index('B_nfp_vs_friday_welch'); baix=[x['test'] for x in af].index('B_nfp_vs_friday_welch')
off={'2006-05-08','2012-12-12','2013-05-06','2020-05-11','2024-01-10','2024-08-21'}; reg={'2006-05-05','2012-12-07','2013-05-03','2020-05-08','2024-01-05','2024-08-02'}; dates={x['release_date'] for x in e}; gf=[x for x in e if x['release_weekday']==4 and x['session_weekday']"'!=4]
B=r['"'statistical_tests']['B_nfp_vs_friday']; A=r['statistical_tests']['A_nfp_vs_all']; wcB=welch(absret[fr],r['main_results']['friday_baseline_abs_return'],B['n_control'],B['t_stat']); wcA=welch(absret,r['main_results']['non_nfp_avg_abs_return'],r['sample']['non_nfp_trading_days'],A['t_stat'])
out={'counts_recomputed':{'event_n':len(e),'release_friday':int(relfr.sum()),'session_friday':int(fr.sum()),'good_friday_n':len(gf),'good_friday_dates':[x['release_date'] for x in gf],'shifted_n':sum(x['session_shifted_from_release'] for x in e)},'date_gate_recomputed':{'offcycle_present':sorted(dates&off),'official_missing':sorted(reg-dates),'official_present':sorted(dates&reg)},'headline_recomputed':{'ratio':float(absret[fr].mean()/r['main_results']['friday_baseline_abs_return']),**wcB},'vs_all_recomputed':{'ratio':float(absret.mean()/r['main_results']['non_nfp_avg_abs_return']),**wcA},'vix_recomputed':{'median':float(np.median(pre)),'n_high':len(high),'n_low':len(low),'ratio':float(high.mean()/low.mean()),'welch_p':float(tw.pvalue),'pearson_r':float(rr.statistic),'pearson_p':float(rr.pvalue),'spearman_rho':float(sr.statistic),'spearman_p':float(sr.pvalue)},'holm_recomputed':{'confirmatory_B':float(holm([x['p_nominal'] for x in cf])[bix]),'all22_B':float(holm([x['p_nominal'] for x in af])[baix])},'calendar_diff_recomputed':{'n_proxy':au['calendar_diff']['dates_in_common']+len(au['calendar_diff']['proxy_only_dates']),'n_official':au['calendar_diff']['dates_in_common']+len(au['calendar_diff']['official_only_dates']),'dates_in_common':au['calendar_diff']['dates_in_common']},'claims_recomputed':{'n':len(au['items']),'flips_from_p':sum((v['before'].get('p_value',1)<.05)"'!=(v['"'after'].get('p_value',1)<.05) for v in au['items'].values() if 'p_value' in v['before'] and 'p_value' in v['after']),'reported_audited':au['n_claims_audited'],'reported_flipped':au['n_claims_flipped']}}
print(json.dumps(out,indent=2))
\"" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
2026-07-27T00:33:01.180987Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
 succeeded in 627ms:
{
  "counts_recomputed": {
    "event_n": 253,
    "release_friday": 243,
    "session_friday": 237,
    "good_friday_n": 6,
    "good_friday_dates": [
      "2007-04-06",
      "2010-04-02",
      "2012-04-06",
      "2015-04-03",
      "2021-04-02",
      "2023-04-07"
    ],
    "shifted_n": 6
  },
  "date_gate_recomputed": {
    "offcycle_present": [],
    "official_missing": [],
    "official_present": [
      "2006-05-05",
      "2012-12-07",
      "2013-05-03",
      "2020-05-08",
      "2024-01-05",
      "2024-08-02"
    ]
  },
  "headline_recomputed": {
    "ratio": 1.188994637894018,
    "event_mean": 0.008540936041959135,
    "control_mean": 0.007183325954343319,
    "control_sd_implied": 0.007759701610352623,
    "df_implied": 371.5159850909699,
    "p_from_t_df": 0.020854283650821093
  },
  "vs_all_recomputed": {
    "ratio": 1.107779531142352,
    "event_mean": 0.008453064404674977,
    "control_mean": 0.007630637836355491,
    "control_sd_implied": 0.00925661279464265,
    "df_implied": 287.13071450394403,
    "p_from_t_df": 0.11206360938619585
  },
  "vix_recomputed": {
    "median": 16.690000534057617,
    "n_high": 128,
    "n_low": 125,
    "ratio": 2.0272974059363413,
    "welch_p": 4.551849137823982e-09,
    "pearson_r": 0.44043638429674903,
    "pearson_p": 1.9817089060479586e-13,
    "spearman_rho": 0.3455048873701663,
    "spearman_p": 1.6699985504624933e-08
  },
  "holm_recomputed": {
    "confirmatory_B": 0.041708567301642185,
    "all22_B": 0.37537710571477967
  },
  "calendar_diff_recomputed": {
    "n_proxy": 254,
    "n_official": 253,
    "dates_in_common": 212
  },
  "claims_recomputed": {
    "n": 6,
    "flips_from_p": 0,
    "reported_audited": 6,
    "reported_flipped": 0
  }
}

codex
重算已對上：253/243/237、六筆 Good Friday、六個正式日/零個修訂日、headline 1.1889946、兩套 Holm、VIX regime 與兩種相關都精確一致。現在只剩把對抗 gate 與 dry-run 控制流跑/判完。
exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider tests/test_nfp_official_release_dates.py::TestReleaseMisbindingGateIsStructural tests/test_nfp_official_release_dates.py::TestK528UsesOfficialCalendar tests/test_nfp_official_release_dates.py::TestCalendarFailClosedCannotBeBypassed tests/test_nfp_official_release_dates.py::TestFridayEstimandIsScopedHonestly::test_results_scope_the_claim_to_friday_and_disclose_the_non_neutrality tests/test_nfp_official_release_dates.py::TestFridayEstimandIsScopedHonestly::test_friday_estimand_pins_release_vs_session_and_names_the_good_fridays tests/test_nfp_official_release_dates.py::TestFridayEstimandIsScopedHonestly::test_readme_does_not_sanction_a_pre_registration_claim tests/test_nfp_official_release_dates.py::TestFridayEstimandIsScopedHonestly::test_excluded_count_matches_the_weekday_breakdown -k 'not test_the_six_real_multi_entry_months_pass_on_the_real_feed and not test_real_multi_entry_gaps_are_too_small_for_a_gap_rule'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
2026-07-27T00:33:20.315296Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
 exited 1 in 128ms:
Traceback (most recent call last):
  File "/Users/yhlai0911/volpred-research/.venv/bin/pytest", line 10, in <module>
    sys.exit(console_main())
             ^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/config/__init__.py", line 223, in console_main
    code = main()
           ^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/config/__init__.py", line 193, in main
    config = _prepareconfig(new_args, plugins)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/config/__init__.py", line 361, in _prepareconfig
    config: Config = pluginmanager.hook.pytest_cmdline_parse(
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 167, in _multicall
    raise exception
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 139, in _multicall
    teardown.throw(exception)
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/helpconfig.py", line 124, in pytest_cmdline_parse
    config = yield
             ^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 121, in _multicall
    res = hook_impl.function(*args)
          ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/config/__init__.py", line 1192, in pytest_cmdline_parse
    self.parse(args)
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/config/__init__.py", line 1562, in parse
    self.hook.pytest_load_initial_conftests(
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 167, in _multicall
    raise exception
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 139, in _multicall
    teardown.throw(exception)
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/warnings.py", line 128, in pytest_load_initial_conftests
    return (yield)
            ^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 116, in _multicall
    next(function_gen)  # first yield
    ^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/capture.py", line 170, in pytest_load_initial_conftests
    capman.start_global_capturing()
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/capture.py", line 773, in start_global_capturing
    self._global_capturing = _get_multicapture(self._method)
                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/capture.py", line 714, in _get_multicapture
    return MultiCapture(in_=FDCapture(0), out=FDCapture(1), err=FDCapture(2))
                                              ^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/_pytest/capture.py", line 493, in __init__
    TemporaryFile(buffering=0),
    ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/.local/share/uv/python/cpython-3.12.10-macos-aarch64-none/lib/python3.12/tempfile.py", line 631, in TemporaryFile
    prefix, suffix, dir, output_type = _sanitize_params(prefix, suffix, dir)
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/.local/share/uv/python/cpython-3.12.10-macos-aarch64-none/lib/python3.12/tempfile.py", line 126, in _sanitize_params
    dir = gettempdir()
          ^^^^^^^^^^^^
  File "/Users/yhlai0911/.local/share/uv/python/cpython-3.12.10-macos-aarch64-none/lib/python3.12/tempfile.py", line 315, in gettempdir
    return _os.fsdecode(_gettempdir())
                        ^^^^^^^^^^^^^
  File "/Users/yhlai0911/.local/share/uv/python/cpython-3.12.10-macos-aarch64-none/lib/python3.12/tempfile.py", line 308, in _gettempdir
    tempdir = _get_default_tempdir()
              ^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/.local/share/uv/python/cpython-3.12.10-macos-aarch64-none/lib/python3.12/tempfile.py", line 223, in _get_default_tempdir
    raise FileNotFoundError(_errno.ENOENT,
FileNotFoundError: [Errno 2] No usable temporary directory found in ['/var/folders/f1/g41vrs0n20v7cx66qzcsd1nc0000gn/T/', '/tmp', '/var/tmp', '/usr/tmp', '/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b']

exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c \"
import importlib.util
from pathlib import Path
path=Path('tests/test_nfp_official_release_dates.py')
spec=importlib.util.spec_from_file_location('k528_tests_review',path); t=importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
passed=[]
# Artifact/source tests confined to the listed files.
k=t.TestK528UsesOfficialCalendar()
for name in ['test_defines_no_first_friday_helper','test_imports_the_official_calendar','test_results_declare_the_official_source_and_no_fallback','test_event_dates_carry_no_proxy_signature','test_sample_is_not_uniformly_friday','test_audit_records_the_dates_that_changed','test_no_off_cycle_revision_date_is_treated_as_an_event']:
 getattr(k,name)(); passed.append(name)
# C adversarial tests, excluding only two methods that read an out-of-scope fixture.
c=t.TestCalendarFailClosedCannotBeBypassed()
withcheck=['test_off_cycle_entry_earlier_in_the_month_is_refused_not_silently_picked','test_selection_that_is_not_the_earliest_entry_fails','test_missing_month_inside_the_observed_span_fails','test_span_gap_check_still_fires_where_the_endpoint_expectation_cannot','test_allowlist_cannot_silence_a_month_that_has_data','test_month_present_in_raw_but_missing_from_selection_fails','test_truncated_feed_cannot_hide_behind_its_own_shrunken_span','test_unreviewed_multi_entry_month_is_refused_not_guessed']
for name in withcheck:
 getattr(c,name)(t._k528_module().check_calendar_is_complete); passed.append(name)
for name in ['test_reviewed_month_whose_raw_shape_changed_goes_back_for_review','test_allowlists_cannot_combine_to_excuse_a_dropped_month','test_allowlists_cannot_combine_even_with_a_reviewed_shape','test_a_month_cannot_be_in_both_allowlists','test_known_missing_claim_is_checked_outside_the_selected_span_too','test_selection_contradicting_the_human_verified_date_fails','test_a_reviewed_month_with_a_normal_revision_still_passes']:
 getattr(c,name)(); passed.append(name)
# Friday scope tests that stay within the listed artifacts.
f=t.TestFridayEstimandIsScopedHonestly()
for name in ['test_results_scope_the_claim_to_friday_and_disclose_the_non_neutrality','test_friday_estimand_pins_release_vs_session_and_names_the_good_fridays','test_readme_does_not_sanction_a_pre_registration_claim','test_excluded_count_matches_the_weekday_breakdown']:
 getattr(f,name)(); passed.append(name)
# Round-7 nearest-governor anti-evasion / legitimate controls.
s=t.TestReleaseMisbindingGateIsStructural()
for item in s.MISBINDINGS:
 s.test_misbindings_are_caught(item.values[0]); passed.append('misbinding:'+item.id)
for item in s.LEGITIMATE:
 s.test_legitimate_lines_are_not_flagged(item.values[0]); passed.append('legitimate:'+item.id)
for name in ['test_the_243_exemption_is_conditional_not_blanket','test_the_denial_exemption_is_clause_local_not_line_wide','test_the_gate_is_not_vacuous_on_the_live_tree']:
 getattr(s,name)(); passed.append(name)
print('manual confined test invocation: '+str(len(passed))+' passed')
print('calendar adversarial methods: 15 passed; structural nearest-governor cases/methods: 14 passed')
\"" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
2026-07-27T00:33:56.808992Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
 succeeded in 1433ms:
manual confined test invocation: 40 passed
calendar adversarial methods: 15 passed; structural nearest-governor cases/methods: 14 passed

exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c \"
import importlib.util,sys
from pathlib import Path
p=Path('experiments/k528/build_article_correction.py'); spec=importlib.util.spec_from_file_location('corr_review',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
called=[]
m.validate=lambda storage_dir:[{'from':'probe','to':'probe2','hits':1,'offset':0}]
def trip(*a,**k): called.append('writer'); raise AssertionError('default dry-run reached writer')
m.record_plan=trip
old=sys.argv; sys.argv=[str(p)]
try: rc=m.main()
finally: sys.argv=old
assert rc==0 and not called
print('replacements='+str(len(m.REPLACEMENTS))+'; default dry-run writer calls=0')
\"" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
validated 1/19 replacements, each matched exactly once
  @     0  probe...

dry run -- nothing written. Re-run with --apply from the repo root, or --record-plan to persist the validated plan only.
replacements=19; default dry-run writer calls=0

2026-07-27T00:34:11.887457Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '1660,1710p'
nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '1710,1805p'
nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '1910,2035p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
  1660	)
  1661	
  1662	
  1663	def verdict_for(key):
  1664	    """Flip test: significance change, sign change, or a >10% move in the headline."""
  1665	    b, a = audit_items[key]["before"], audit_items[key]["after"]
  1666	    reasons = []
  1667	    if b.get("significant_5pct") is not None and a.get("significant_5pct") is not None:
  1668	        if bool(b["significant_5pct"]) != bool(a["significant_5pct"]):
  1669	            reasons.append(
  1670	                "significance flipped "
  1671	                f"({'sig' if b['significant_5pct'] else 'NS'} -> "
  1672	                f"{'sig' if a['significant_5pct'] else 'NS'})"
  1673	            )
  1674	    # The mean is not trusted on its own: the median and the win rate are
  1675	    # checked independently, because the failure mode this audit exists to
  1676	    # catch is a stable mean sitting on top of a moved distribution.
  1677	    for field in ("mean_ratio", "median_ratio", "pearson_r", "threshold", "n"):
  1678	        if field in b and field in a and b[field] and a[field]:
  1679	            rel = abs(a[field] - b[field]) / abs(b[field])
  1680	            if rel > 0.10:
  1681	                reasons.append(f"{field} moved {rel * 100:.1f}%")
  1682	    if b.get("win_rate") and a.get("win_rate"):
  1683	        if abs(a["win_rate"] - b["win_rate"]) > 0.05:
  1684	            reasons.append(
  1685	                f"win_rate moved {b['win_rate']:.3f} -> {a['win_rate']:.3f}"
  1686	            )
  1687	    if key == "vix_median_threshold" and b["places_20260701_vix_1659_in"] != a["places_20260701_vix_1659_in"]:
  1688	        reasons.append("the article's worked example changes regime")
  1689	    return ("CONCLUSION_FLIPPED" if reasons else "NUMERIC_ADJUSTMENT"), reasons
  1690	
  1691	
  1692	print(f"\n  {'Claim':<46} {'Before':>12} {'After':>12}  Verdict")
  1693	for key, item in audit_items.items():
  1694	    v, reasons = verdict_for(key)
  1695	    item["verdict"], item["verdict_reasons"] = v, reasons
  1696	    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
  1697	                     if f in item["before"]), None)
  1698	    bf = item["before"].get(headline)
  1699	    af = item["after"].get(headline)
  1700	    fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
  1701	    print(f"  {item['label']:<46} {fmt(bf):>12} {fmt(af):>12}  {v}")
  1702	    for r in reasons:
  1703	        print(f"      - {r}")
  1704	
  1705	n_flipped = sum(1 for i in audit_items.values() if i["verdict"] == "CONCLUSION_FLIPPED")
  1706	print(f"\n  {n_flipped} of {len(audit_items)} audited claims changed materially.")
  1707	
  1708	# ============================================================
  1709	# 10. Save results
  1710	# ============================================================
  1710	# ============================================================
  1711	print("\n[6/6] Saving results...")
  1712	
  1713	output = {
  1714	    "experiment_id": "K528",
  1715	    "title": "NFP Event Study on SPY Volatility",
  1716	    "date": datetime.now(timezone.utc).isoformat(),
  1717	    "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
  1718	    "event_date_source": {
  1719	        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
  1720	        "accessor": "volpred.data.event_dates.nfp_release_dates",
  1721	        "fallback": "none - the run raises if the calendar is unreachable",
  1722	        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
  1723	    },
  1724	    "sample": {
  1725	        "total_nfp_events": len(df),
  1726	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
  1727	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
  1728	        "friday_baseline_days": int(friday_mask.sum()),
  1729	        "nfp_days_on_friday": int((df["session_weekday"] == 4).sum()),
  1730	        "nfp_releases_dated_friday": int((df["release_weekday"] == 4).sum()),
  1731	        "event_mapping_audit": mapping_audit,
  1732	        "calendar_completeness": calendar_completeness,
  1733	        "price_coverage": price_coverage,
  1734	        "friday_estimand": friday_estimand,
  1735	        # Recorded independently so the control-group invariant
  1736	        # (controls == total - mapped NFP sessions) is checkable rather than an
  1737	        # algebraic identity between two numbers derived from each other.
  1738	        "total_trading_days": int(len(spy)),
  1739	        "control_group_excludes_all_nfp_sessions": bool(
  1740	            len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask])) == 0
  1741	        ),
  1742	    },
  1743	    "main_results": {
  1744	        "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
  1745	        "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
  1746	        "non_nfp_avg_abs_return": baseline_abs_return,
  1747	        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
  1748	        "friday_baseline_abs_return": friday_baseline,
  1749	        "vol_ratio_vs_all": vol_ratio_all,
  1750	        "vol_ratio_vs_friday": vol_ratio_fri,
  1751	    },
  1752	    "statistical_tests": {
  1753	        "A_nfp_vs_all": {
  1754	            "test": "Welch t-test",
  1755	            "t_stat": float(t_stat_all),
  1756	            "p_value": float(p_val_all),
  1757	            "significant_5pct": bool(p_val_all < 0.05),
  1758	        },
  1759	        "B_nfp_vs_friday": {
  1760	            "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
  1761	            "estimand": (
  1762	                "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event "
  1763	                "group is restricted to NFP releases that trade on a Friday, and the "
  1764	                f"{int(len(nfp_nonfriday_abs))} non-Friday events are excluded rather "
  1765	                "than compared against a pure-Friday control group."
  1766	            ),
  1767	            "claim_scope": (
  1768	                "This identifies the effect of an NFP release ABSORBED BY A FRIDAY "
  1769	                "SESSION. It does not license a statement about NFP releases in general "
  1770	                "-- the excluded events are quieter, so the restriction raises the ratio "
  1771	                "relative to the mixed-weekday spec -- and it is NOT a statement about "
  1772	                "releases DATED a Friday, six of which are Good Fridays traded the "
  1773	                "following Monday and therefore excluded. Any prose quoting this number "
  1774	                "must say 'NFP traded in a Friday session', not 'NFP' and not "
  1775	                "'NFP released on a Friday'."
  1776	            ),
  1777	            "restriction_is_not_neutral": {
  1778	                "excluded_mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
  1779	                "friday_mean_abs_return": float(nfp_friday_abs.mean()),
  1780	                "excluded_are_quieter_by_pct": (
  1781	                    float((nfp_friday_abs.mean() - nfp_nonfriday_abs.mean()) / nfp_friday_abs.mean() * 100)
  1782	                    if len(nfp_nonfriday_abs) else None
  1783	                ),
  1784	            },
  1785	            "n_event": int(len(nfp_friday_abs)),
  1786	            "n_control": int(len(friday_non_nfp_abs)),
  1787	            "vol_ratio": vol_ratio_fri,
  1788	            "t_stat": float(t_stat_fri),
  1789	            "p_value": float(p_val_fri),
  1790	            "significant_5pct": bool(p_val_fri < 0.05),
  1791	            "excluded_non_friday_events": {
  1792	                "n": int(len(nfp_nonfriday_abs)),
  1793	                "mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
  1794	            },
  1795	        },
  1796	        "B_diagnostic_mixed_weekday": {
  1797	            "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
  1798	            "status": "DIAGNOSTIC ONLY - do not quote",
  1799	            "why_not_a_headline": (
  1800	                "this is the pre-correction specification: a weekday-mixed event "
  1801	                "group against a pure-Friday control group, so the p-value absorbs "
  1802	                "any Friday-vs-other-weekday volatility difference. Retained solely "
  1803	                "so the correction audit can show what the contaminated estimand was "
  1804	                "worth (k528 Codex v2 finding 5)."
  1805	            ),
  1910	        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
  1911	        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
  1912	        "Lucca & Moench (2015) JFE — pre-FOMC announcement drift",
  1913	    ],
  1914	    "event_data": results,  # full per-event data
  1915	}
  1916	
  1917	# Codex round-5 B4: a bare `significant_5pct: true` sitting next to 21 other
  1918	# p-values is an unqualified 5% claim. Stamp every flag with the family it was
  1919	# judged in, mechanically -- a hand-written note on six entries would drift the
  1920	# first time a test is added.
  1921	_holm = {m["test"]: m for m in multiplicity["all_outputs_family"]["members"]}
  1922	_confirmatory_names = {n for n, _ in confirmatory}
  1923	_JSON_KEY_TO_FAMILY_NAME = {
  1924	    ("statistical_tests", "A_nfp_vs_all"): "A_nfp_vs_all_welch",
  1925	    ("statistical_tests", "B_nfp_vs_friday"): "B_nfp_vs_friday_welch",
  1926	    ("statistical_tests", "C_wilcoxon"): "C_mannwhitney_one_sided",
  1927	    ("statistical_tests", "D_vol_crush"): "D_vol_crush",
  1928	    ("statistical_tests", "F_vix_buildup"): "F_vix_buildup",
  1929	    ("regime_analysis", None): "H_vix_regime_welch",
  1930	    ("time_trend", None): "I_time_trend",
  1931	    ("directional_bias", None): "J_direction_binomial",
  1932	}
  1933	
  1934	
  1935	def _stamp(entry, family_name):
  1936	    rec = _holm.get(family_name)
  1937	    if rec is None:
  1938	        return
  1939	    confirmatory_member = family_name in _confirmatory_names
  1940	    entry["multiplicity"] = {
  1941	        "family": "confirmatory" if confirmatory_member else "exploratory",
  1942	        "p_nominal": rec["p_nominal"],
  1943	        "p_holm_all_outputs_family": rec["p_holm"],
  1944	        "p_holm_confirmatory_family": (
  1945	            dict(zip([n for n, _ in confirmatory], confirmatory_adj))[family_name]
  1946	            if confirmatory_member else None
  1947	        ),
  1948	        "how_to_report": (
  1949	            "Nominal, then Holm within the declared confirmatory family."
  1950	            if confirmatory_member else
  1951	            "EXPLORATORY -- nominal p reported for description only; not quotable as a 5% finding."
  1952	        ),
  1953	    }
  1954	
  1955	
  1956	for (section, key), fam in _JSON_KEY_TO_FAMILY_NAME.items():
  1957	    target = output.get(section)
  1958	    if target is None:
  1959	        continue
  1960	    if key is not None:
  1961	        target = target.get(key)
  1962	    if isinstance(target, dict):
  1963	        _stamp(target, fam)
  1964	
  1965	for _mk, _mv in output.get("seasonal_analysis", {}).items():
  1966	    _stamp(_mv, f"G_month_{_mk}")
  1967	
  1968	if "E_vix_predictive" in output["statistical_tests"]:
  1969	    _e = output["statistical_tests"]["E_vix_predictive"]
  1970	    _e["multiplicity"] = {
  1971	        "family": "confirmatory",
  1972	        "pearson": {
  1973	            "p_nominal": float(p_vix),
  1974	            "p_holm_confirmatory_family": float(
  1975	                dict(zip([n for n, _ in confirmatory], confirmatory_adj))["E_vix_pearson"]),
  1976	            "p_holm_all_outputs_family": float(_holm["E_vix_pearson"]["p_holm"]),
  1977	        },
  1978	        "spearman": {
  1979	            "p_nominal": float(p_rho_vix),
  1980	            "p_holm_confirmatory_family": float(
  1981	                dict(zip([n for n, _ in confirmatory], confirmatory_adj))["E_vix_spearman"]),
  1982	            "p_holm_all_outputs_family": float(_holm["E_vix_spearman"]["p_holm"]),
  1983	        },
  1984	    }
  1985	
  1986	_unstamped = [
  1987	    k for k, v in output["statistical_tests"].items()
  1988	    if isinstance(v, dict) and "multiplicity" not in v and k != "B_diagnostic_mixed_weekday"
  1989	]
  1990	if _unstamped:
  1991	    raise RuntimeError(
  1992	        f"statistical_tests entries {_unstamped} carry a p-value but no multiplicity stamp. "
  1993	        "A new test was added without being placed in a family -- which is how an undeclared "
  1994	        "family gets rebuilt after being fixed."
  1995	    )
  1996	
  1997	out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
  1998	write_json_atomic(out_path, output)
  1999	
  2000	print(f"  Saved to: {out_path}")
  2001	
  2002	# The correction audit is written separately: it is the artifact the article
  2003	# correction is justified against, and it must stay readable without wading
  2004	# through 254 events of per-day data.
  2005	audit_out = {
  2006	    "experiment_id": "K528",
  2007	    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
  2008	    "generated_at": datetime.now(timezone.utc).isoformat(),
  2009	    "before_source": PROXY_PATH.name,
  2010	    "after_source": out_path.name,
  2011	    "event_date_source": output["event_date_source"],
  2012	    "calendar_diff": {
  2013	        "proxy_only_dates": sorted(proxy_dates - new_dates),
  2014	        "official_only_dates": sorted(new_dates - proxy_dates),
  2015	        "dates_in_common": len(proxy_dates & new_dates),
  2016	        "n_proxy": len(proxy_dates),
  2017	        "n_official": len(new_dates),
  2018	        "nfp_days_on_friday_official": int((df["weekday"] == 4).sum()),
  2019	    },
  2020	    "win_rate_definition": (
  2021	        "share of the sample exceeding the MEDIAN of its comparison group; "
  2022	        "0.5 under the null"
  2023	    ),
  2024	    "items": audit_items,
  2025	    "n_claims_flipped": n_flipped,
  2026	    "n_claims_audited": len(audit_items),
  2027	    "article_correction": {
  2028	        "article_id": "mile_35eef830",
  2029	        "status": "pending - filled in by the correction step",
  2030	        "replacements": None,
  2031	    },
  2032	}
  2033	audit_path = Path(__file__).parent / "k528_nfp_official_dates_results.json"
  2034	write_json_atomic(audit_path, audit_out)
  2035	print(f"  Saved to: {audit_path}")

2026-07-27T00:34:24.936768Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "rg -n 'random|rng|seed|bootstrap|permut|Monte|sample\\(' experiments/k528/k528_nfp_event_study.py experiments/k528/build_article_correction.py
rg -n 'shift\\(|pre_vix|pre_window|post_window|signal|future|lookahead' experiments/k528/k528_nfp_event_study.py | sed -n '1,180p'
rg -n '顯著|significant|Holm|nominal|22' experiments/k528/build_article_correction.py | sed -n '1,180p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
experiments/k528/k528_nfp_event_study.py:22:wrong for ~20% of the sample and it is wrong SYSTEMATICALLY, not randomly: BLS
548:spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
688:# an invariant rather than a comment means a future change to the mapping rule
748:    pre_window = spy.iloc[pos-5:pos]
752:    post_window = spy.iloc[pos+1:pos+6]
757:    if len(pre_window) < 5 or len(post_window) < 5:
760:            f"(pre={len(pre_window)}, post={len(post_window)}) despite passing the "
785:        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
786:        "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
787:        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
789:        "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
792:        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
795:    if row["pre_vix"] is not None and row["event_vix"] is not None:
796:        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]
967:vix_valid = df.dropna(subset=["pre_vix"])
970:    X_vix = vix_valid["pre_vix"].values
1006:vix_median = df["pre_vix"].median()
1007:high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
1008:low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
1420:_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
1423:proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
1424:proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
1636:        "n": int(df["pre_vix"].notna().sum()),
19:result the article reported as significant was in fact not significant
21:comparison is 1.19x at p=0.020 -- significant, exactly as the article
105:    # --- 1.10x -> 1.11x vs all non-NFP days (direction unchanged: NOT significant) ---
114:    # --- Friday baseline: 1.17x -> 1.19x, STILL significant; estimand made explicit ---
117:        "用 Welch t 檢定算下來，這個差距達到顯著水準。"
122:        "這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準"
123:        "（p=0.021，這是未經多重比較校正的 nominal 值）。"
130:        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；"
131:        "但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
132:        "所以精確的講法是：消息落在週五交易日的 NFP 確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；"
133:        "但如果拿全部交易日當對照，這個放大效果（1.11 倍）在 Welch 平均差檢定下未達顯著"
134:        "（p=0.11）—— 要注意同一組對照下，只看排序的無母數檢定反而是顯著的（p=0.002），"
179:        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，"
180:        "對週五基準是 1.17 倍、達到顯著水準。",
181:        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準；"
182:        "若只看消息落在週五交易日的那 237 場、拿非 NFP 的週五當基準，是 1.19 倍、達到顯著水準。",
207:        "**方向性結論全部維持不變**：對全體交易日基準在 Welch 平均差檢定下未達顯著"
208:        "（同組對照的無母數檢定則顯著，兩者不一致）、對週五基準達到顯著、"
211:        "要說明的是，本文並沒有正式檢定「2.03 倍顯著大於 1.19 倍」——兩者的樣本與對照組都不同，"

2026-07-27T00:35:15.684714Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "rg -n '\"release_date\": \"(2006-05-05|2012-12-07|2013-05-03|2020-05-08|2024-01-05|2024-08-02|2007-04-06|2010-04-02|2012-04-06|2015-04-03|2021-04-02|2023-04-07)\"|\"nfp_releases_dated_friday\"|\"n_traded_in_friday_session\"|\"n_release_date_on_friday\"|\"total_nfp_events\"|\"p_value\": 0.020854|\"vol_ratio\": 1.188994|\"pearson_r\": 0.440436|\"spearman_rho\": 0.345504|\"p_holm_confirmatory_family\": 0.041708|\"p_holm_all_outputs_family\": 0.375377' experiments/k528/k528_nfp_event_study_results.json
rg -n '\"dates_in_common\"|\"n_proxy\"|\"n_official\"|\"n_claims_audited\"|\"n_claims_flipped\"|\"mean_ratio\": 1.107779|\"mean_ratio\": 1.188994|\"mean_ratio\": 2.027297|\"pearson_r\": 0.440436|\"spearman_rho\": 0.345504' experiments/k528/k528_nfp_official_dates_results.json
rg -n '不涵蓋|有文件的假宣稱|端點期望|check_price_coverage|check_vix_forward_fill_age|六個 Good Friday|243|237|253|0 項結論翻轉|Holm.*22|n_claims' experiments/k528/README.md | sed -n '1,180p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
 succeeded in 0ms:
13:    "total_nfp_events": 253,
18:    "nfp_releases_dated_friday": 243,
137:      "n_release_date_on_friday": 243,
138:      "n_traded_in_friday_session": 237,
143:            "release_date": "2007-04-06",
149:            "release_date": "2010-04-02",
155:            "release_date": "2012-04-06",
161:            "release_date": "2015-04-03",
167:            "release_date": "2021-04-02",
173:            "release_date": "2023-04-07",
222:      "vol_ratio": 1.188994637894018,
224:      "p_value": 0.020854283650821093,
233:        "p_holm_all_outputs_family": 0.37537710571477967,
234:        "p_holm_confirmatory_family": 0.041708567301642185,
278:      "pearson_r": 0.44043638429674903,
280:      "spearman_rho": 0.3455048873701663,
727:      "p_holm_confirmatory_family": 0.041708567301642185,
728:      "p_holm_all_outputs_family": 0.37537710571477967,
1067:      "release_date": "2006-05-05",
1298:      "release_date": "2007-04-06",
2054:      "release_date": "2010-04-02",
2558:      "release_date": "2012-04-06",
2726:      "release_date": "2012-12-07",
2831:      "release_date": "2013-05-03",
3314:      "release_date": "2015-04-03",
4595:      "release_date": "2020-05-08",
4826:      "release_date": "2021-04-02",
5330:      "release_date": "2023-04-07",
5519:      "release_date": "2024-01-05",
5666:      "release_date": "2024-08-02",
101:    "dates_in_common": 212,
102:    "n_proxy": 254,
103:    "n_official": 253,
130:        "mean_ratio": 1.107779531142352,
173:        "mean_ratio": 1.188994637894018,
207:        "mean_ratio": 2.0272974059363413,
233:        "pearson_r": 0.44043638429674903,
235:        "spearman_rho": 0.3455048873701663,
272:        "dates_in_common": 212,
366:  "n_claims_flipped": 0,
367:  "n_claims_audited": 6,
24:- proxy 把每一場都放在**週五**；官方日曆的 253 場有 243 場**發布日**在週五，
25:  其中 237 場**在週五的交易 session 被吸收**（差額是六個 Good Friday，見下）
49:六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
77:> 253 場有效發布中，**243 場發布日在週五**，但只有 **237 場在週五開盤**：
86:> 若改用發布日 weekday 篩 243 場，等於把六筆**週一報酬**放進一個對照組是純週五的比較裡
95:94.1% 在週五）；官方日曆是 237/253 = 93.7%。混合程度幾乎沒變，舊版一直都在拿混合事件組
98:本輪把事件組**限定為在週五 session 交易的 237 場**，兩邊星期別一致。另一個選項是保留全部
99:253 場改用 weekday-matched controls，未採用的理由：被排除的 16 場按 **session** 星期別是
103:（那 6 筆週一 session 就是上面的六個 Good Friday；其餘 10 筆是發布日本身就不在週五
104:—— 週二 2、週三 1、週四 7。兩種來源合起來 16 筆，與 253 − 237 一致。）
108:性質，不是效果變強的證據。（六個 Good Friday 子集平均 |ret| = 0.715%，與 16 場整體幾乎
119:| 修正後（官方） | **1.189× / p=0.0209 / n=237** | 1.177× / p=0.0257 / n=253（DIAGNOSTIC ONLY） |
137:| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
140:| 週五 session NFP vs 非 NFP 週五（平均） | 1.167× (p=0.0421, nominal 顯著, n=239) | 1.189× (p=0.0209, **仍 nominal 顯著**；Holm=0.0417, n=237) | 數值微調 |
148:**6 項受稽核宣稱中，0 項結論翻轉。**
166:  **nominal 拒絕**；confirmatory family 內 Holm=0.0417，**仍拒絕**；對全部 22 個
197:| Holm，全部 inferential outputs（22） | p=0.375 | **不拒絕** |
244:（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
268:- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、其中 237 筆在週五
269:  session 交易（對照官方 BLS 日曆的 243 筆發布日在週五，兩者差額為六個順延到下週一
282:- `test_no_live_artifact_describes_the_237_as_a_release_count` + `TestReleaseMisbindingGateIsStructural`
283:  — 釘住「237 不是 Friday-release 數，而是 Friday-session 數」的措辭不變量。
285:  但它當時其實只是**5 詞字面 blocklist + 兩個無條件行豁免**（同行出現 `243` 就整行放行、
287:  （「237 場 NFP 是週五發布的」「published on a Friday」「publication day was a Friday」
288:  「限定週五發布的 237 場」）全部溜過，行內無關 `243`（如「243 trading weeks」）與鄰句的
308:理由、同時把該月從 raw feed 移除」這種**有文件的假宣稱**。
327:6. **端點期望**（本輪新增，見下）：由**請求視窗**推導出「哪些月份非有不可」，
330:### 端點期望 —— 修掉「同刪首/尾月仍通過」（Codex 五審 B2）
338:| 刪 `2005-01` | 259 / 253 | 34d | 21d | **通過** |
339:| 刪 `2026-03` | 259 / 253 | 6d | 44d | **通過** |
363:  delete head month 2005-01: ACCEPTED  (259 raw / 253 selected, head_short=34d tail_short=21d)
364:  delete tail month 2026-03: ACCEPTED  (259 raw / 253 selected, head_short=6d  tail_short=44d)
370:**殘留限制（明講）**：端點期望仍可被「把該月加進 `KNOWN_MISSING_MONTHS`」壓掉。
373:那是一則**有文件的假宣稱**，不是無聲截斷。**本 gate 對後者 fail-closed，對前者不是。**
382:本輪新增（`check_price_coverage` / `check_vix_forward_fill_age`，都寫成**函式**以便被測試
423:事件窗篩選的 253 個。因窗口不足被排除的 `2005-01-07` 仍然是真實的 NFP 日，把它留在對照組
424:就是本實驗存在的理由（「把真的事件日丟進對照組」）的 1/253 版本。三審 Codex 與本輪自查

2026-07-27T00:35:59.054997Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c \"
import importlib.util
from pathlib import Path
import pandas as pd, numpy as np
# Load only literal constants/functions from the listed main script, same strategy as its test owner.
spec=importlib.util.spec_from_file_location('k528_test_owner',Path('tests/test_nfp_official_release_dates.py')); t=importlib.util.module_from_spec(spec); spec.loader.exec_module(t); m=t._k528_module()
full=pd.DataFrame(index=pd.to_datetime(['2024-01-02','2024-03-29'])); m.check_price_coverage(full,'SPY','2024-01-01','2024-03-31')
def must_raise(fn,label):
 try: fn()
 except RuntimeError: return
 raise AssertionError(label+' did not fail closed')
must_raise(lambda:m.check_price_coverage(pd.DataFrame(index=pd.to_datetime(['2024-01-02','2024-02-28'])),'SPY','2024-01-01','2024-03-31'),'tail truncation')
must_raise(lambda:m.check_price_coverage(pd.DataFrame(),'SPY','2024-01-01','2024-03-31'),'empty prices')
filled,audit=m.check_vix_forward_fill_age(pd.Series([10.0,np.nan,11.0])); assert filled.tolist()==[10.0,10.0,11.0]
must_raise(lambda:m.check_vix_forward_fill_age(pd.Series([10.0,np.nan,np.nan,np.nan,np.nan,11.0])),'stale VIX')
must_raise(lambda:m.check_vix_forward_fill_age(pd.Series([np.nan,10.0])),'leading VIX hole')
print('price/VIX adversarial probes: 6 passed')
\"" in /Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b
2026-07-27T00:36:33.970852Z ERROR codex_models_manager::manager: failed to renew cache TTL: missing field `supports_reasoning_summaries` at line 88 column 5
 succeeded in 1161ms:
price/VIX adversarial probes: 6 passed

codex
- **A — CLOSED：**重算事件集合確認六個正式發布日全在、六個 off-cycle 修訂日全不在；accessor 採 per-month `min()` 並做 13–110 日 cadence gate，[主腳本](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/experiments/k528/k528_nfp_event_study.py:243)另驗證 raw shape、人工覆核日期及 raw→selected 完整性，[event_dates.py](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/src/volpred/data/event_dates.py:134)。

- **B — CLOSED：**重算 headline 為 1.1889946、p=0.0208543、n=237，audit 確認 6 claims、0 flips；[README](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/experiments/k528/README.md:73)清楚區分 253/243/237、揭露非中性排除及兩套 Holm，而 [build_article_correction.py](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/experiments/k528/build_article_correction.py:314)預設路徑 writer tripwire 實測為 0 次，只有 `--apply`/`--record-plan` 才寫。

- **C — CLOSED：**calendar gate 已包含無條件 raw→selected、allowlist 互斥、由 request window 推導的端點期望及全 allowlist counter-check，[價格/VIX gate](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/experiments/k528/k528_nfp_event_study.py:505)亦能拒絕截短與陳舊值；15 個 calendar 對抗案例與 6 個價格/VIX probe 全通過，README 也如實揭露「raw 同刪＋書面假宣稱」不在涵蓋範圍，[round-7 gate](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/tests/test_nfp_official_release_dates.py:966)確為 nearest-governor 組合檢查而非字面 blocklist。

重算結果：

- vs 全體非 NFP：1.1077795，p=0.1120636。
- VIX regime：2.0272974，p=4.55185e-9；Pearson 0.4404364 / 1.98171e-13；Spearman 0.3455049 / 1.67000e-8。
- Holm：family=6 為 0.0417086；all 22 為 0.3753771。
- 樣本：253、243、237、212、254；六筆 Good Friday 全數逐筆對上。
- 無隨機程序；VIX 使用 T−1 值，事件報酬使用 T，控制組排除全部已映射 NFP session，未見 same-day/lookahead。
- 受限檔案未內嵌 control vector，因此兩個 Welch p 是以 event vector、control aggregate 與 t-stat 重建自由度核對；VIX、樣本、日期與 Holm 則由明細完整重算。

非 blocking：README 對 gate 數量的「四道／五道／0–6」及 round-7「6 擋 2 放」計數文字略舊，與實際更多的防線及測試案例不一致，但不影響實作。

**VERDICT: PASS**
tokens used
174,937
- **A — CLOSED：**重算事件集合確認六個正式發布日全在、六個 off-cycle 修訂日全不在；accessor 採 per-month `min()` 並做 13–110 日 cadence gate，[主腳本](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/experiments/k528/k528_nfp_event_study.py:243)另驗證 raw shape、人工覆核日期及 raw→selected 完整性，[event_dates.py](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/src/volpred/data/event_dates.py:134)。

- **B — CLOSED：**重算 headline 為 1.1889946、p=0.0208543、n=237，audit 確認 6 claims、0 flips；[README](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/experiments/k528/README.md:73)清楚區分 253/243/237、揭露非中性排除及兩套 Holm，而 [build_article_correction.py](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/experiments/k528/build_article_correction.py:314)預設路徑 writer tripwire 實測為 0 次，只有 `--apply`/`--record-plan` 才寫。

- **C — CLOSED：**calendar gate 已包含無條件 raw→selected、allowlist 互斥、由 request window 推導的端點期望及全 allowlist counter-check，[價格/VIX gate](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/experiments/k528/k528_nfp_event_study.py:505)亦能拒絕截短與陳舊值；15 個 calendar 對抗案例與 6 個價格/VIX probe 全通過，README 也如實揭露「raw 同刪＋書面假宣稱」不在涵蓋範圍，[round-7 gate](/Users/yhlai0911/volpred-research/.claude/worktrees/k528-round7-204d556b/tests/test_nfp_official_release_dates.py:966)確為 nearest-governor 組合檢查而非字面 blocklist。

重算結果：

- vs 全體非 NFP：1.1077795，p=0.1120636。
- VIX regime：2.0272974，p=4.55185e-9；Pearson 0.4404364 / 1.98171e-13；Spearman 0.3455049 / 1.67000e-8。
- Holm：family=6 為 0.0417086；all 22 為 0.3753771。
- 樣本：253、243、237、212、254；六筆 Good Friday 全數逐筆對上。
- 無隨機程序；VIX 使用 T−1 值，事件報酬使用 T，控制組排除全部已映射 NFP session，未見 same-day/lookahead。
- 受限檔案未內嵌 control vector，因此兩個 Welch p 是以 event vector、control aggregate 與 t-stat 重建自由度核對；VIX、樣本、日期與 Holm 則由明細完整重算。

非 blocking：README 對 gate 數量的「四道／五道／0–6」及 round-7「6 擋 2 放」計數文字略舊，與實際更多的防線及測試案例不一致，但不影響實作。

**VERDICT: PASS**
