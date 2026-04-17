#!/usr/bin/env python3
"""
K320: Website Content Quality Audit — Are Our Published Articles Accurate?

Background: 530+ articles published. After 9 self-corrections across research,
articles written before corrections may contain outdated or misleading claims.

Key corrections to check against:
  - K255: TSMOM fails Harvey on full 21yr sample (t=2.34, was t=4.37 on subset)
  - K266: Amihud illiquidity was look-ahead artifact (K265 result invalidated)
  - K281: Monthly wins NET Sharpe over Daily (K279 daily dominates gross, but TX kills it)
  - K222: 50/50+VT HELPS retirees (REVERSES K36 SPY-only VT hurts retirement)
  - K53:  VT alpha only 5.2% reduced by TSMOM (not 91% as K46 claimed)

Methodology:
  1. Parse all published articles from feed.json
  2. Flag articles containing claims that may conflict with corrections
  3. Read full content and classify each flagged claim
  4. Output structured JSON audit report

[提出: 用戶, 執行: Claude]
"""

import json
import re
import os
from datetime import datetime

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage")
FEED_PATH = os.path.join(STORAGE_DIR, "reports", "feed.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "k320_content_audit_results.json")


def load_articles():
    with open(FEED_PATH) as f:
        articles = json.load(f)
    return [a for a in articles if a.get("status") == "published"]


def check_claim(article_id, title, content, full_text):
    """Check a single article for potentially outdated claims. Returns list of findings."""
    findings = []

    # =====================================================================
    # ISSUE 1: TSMOM "passes Harvey" or "only strategy that works"
    # Correction: K255 showed TSMOM FAILS Harvey on full 21yr (t=2.34 < 3.0)
    # =====================================================================
    if re.search(r"TSMOM.*通過|TSMOM.*passes|TSMOM.*Harvey|TSMOM.*有效|時間序列動量.*通過|時間序列動量.*有效", full_text, re.IGNORECASE):
        # Check if the article already acknowledges the correction
        has_correction = bool(re.search(r"已修正|修正|FAIL|fail|t=2\.34|不通過|未通過", full_text, re.IGNORECASE))

        if "只有 1 個策略通過" in full_text and "TSMOM" in full_text:
            findings.append({
                "issue": "TSMOM_passes_Harvey",
                "claim_in_article": "Claims TSMOM is 'the only strategy that passes Harvey t>3.0'",
                "correction": "K255: TSMOM FAILS Harvey on full 21yr sample (t=2.34). Only passed on 2005-2024 subset (t=4.37). BTC was dominant driver.",
                "severity": "MISLEADING",
                "has_disclaimer": has_correction,
                "recommendation": "Update to clarify TSMOM failed full-sample Harvey. The '1 strategy passes' claim is incorrect after K255."
            })
        elif "TSMOM" in full_text and re.search(r"t=3\.07|t=4\.37|Sharpe.*0\.979", full_text):
            findings.append({
                "issue": "TSMOM_passes_Harvey",
                "claim_in_article": "References TSMOM passing Harvey with specific t-statistics from pre-correction analysis",
                "correction": "K255: Full 21yr sample t=2.34 (FAILS). K241 t=4.37 was on subset only. BTC-driven.",
                "severity": "OUTDATED" if has_correction else "MISLEADING",
                "has_disclaimer": has_correction,
                "recommendation": "Add note that these results were superseded by K255 full-sample validation."
            })

    # =====================================================================
    # ISSUE 2: VT alpha "91% is trend following" (K46 claim)
    # Correction: K53 showed only 5.2% alpha reduction (N=15 cross-asset)
    # =====================================================================
    if re.search(r"91%.*trend|91%.*趨勢|91%.*動量|alpha.*91|91%.*TSMOM", full_text, re.IGNORECASE):
        has_correction = bool(re.search(r"K53|修正|5\.2%|32%|方法論修正|配角", full_text, re.IGNORECASE))

        if "91%" in full_text and not has_correction:
            findings.append({
                "issue": "VT_91pct_trend_following",
                "claim_in_article": "Claims VT alpha is 91% explained by trend following (K46 result)",
                "correction": "K53 (N=15 cross-asset, Newey-West HAC): Equity alpha reduction only 5.2%, not 91%. The 91% was from flawed 4-asset analysis.",
                "severity": "MISLEADING",
                "has_disclaimer": False,
                "recommendation": "Must update: 91% figure is methodologically flawed. Correct figure is 5.2% (K53) or 32% for Sharpe contribution (K49)."
            })
        elif "91%" in full_text and has_correction:
            # Article mentions 91% but also has correction context
            findings.append({
                "issue": "VT_91pct_trend_following",
                "claim_in_article": "Mentions 91% figure but includes correction/context (K53 or 'only 5.2%')",
                "correction": "K53: alpha reduction only 5.2%. Article provides correction context.",
                "severity": "STILL_VALID",
                "has_disclaimer": True,
                "recommendation": "Already corrected in-article. No action needed."
            })

    # =====================================================================
    # ISSUE 3: Withdrawal rate "doubles from 4% to 8%"
    # Correction: K222 reversed K36, but the doubling claim (K85) was
    # corrected by K87 — VT provides MORE STABLE 4%, not higher 8%
    # =====================================================================
    if re.search(r"提領率.*翻倍|翻倍.*提領|8%.*安全提領|安全提領.*8|withdrawal.*double|double.*withdrawal|提領.*8%|4%.*翻倍.*8%|max.*safe.*8%", full_text, re.IGNORECASE):
        has_correction = bool(re.search(r"已修正|修正|K87|不會翻倍|仍為 4%|壓力測試|25-28%|更穩定的 4%", full_text, re.IGNORECASE))

        if not has_correction:
            findings.append({
                "issue": "withdrawal_rate_doubles",
                "claim_in_article": "Claims VT doubles safe withdrawal rate from 4% to 8%",
                "correction": "K87 cross-validation: 8% survival only 25-28% under stress. VT value = more stable 4%, NOT higher 8%.",
                "severity": "MISLEADING",
                "has_disclaimer": False,
                "recommendation": "Must add correction: 8% claim was overturned by K87. True value = more stable 4%."
            })
        else:
            findings.append({
                "issue": "withdrawal_rate_doubles",
                "claim_in_article": "Mentions 4%→8% but includes correction/disclaimer",
                "correction": "Article acknowledges the correction. K87 showed 8% fails stress test.",
                "severity": "STILL_VALID",
                "has_disclaimer": True,
                "recommendation": "Already corrected. Consider removing the 8% claim entirely for clarity."
            })

    # =====================================================================
    # ISSUE 4: "VT doubles withdrawal rate" — K36 original (SPY-only VT hurts)
    # Correction: K222 showed 50/50+VT HELPS (reverses K36)
    # =====================================================================
    if re.search(r"VT.*有害|VT.*hurt|VT.*對退休.*不利|VT.*不適合退休", full_text, re.IGNORECASE):
        has_correction = bool(re.search(r"K222|50/50|修正|翻轉|REVERSES", full_text, re.IGNORECASE))
        if not has_correction:
            findings.append({
                "issue": "VT_hurts_retirement_K36",
                "claim_in_article": "Claims VT hurts retirement without mentioning 50/50 reversal (K222)",
                "correction": "K222: 50/50+VT REVERSES K36. SPY-only VT hurts, but 50/50+VT helps retirees significantly.",
                "severity": "OUTDATED",
                "has_disclaimer": False,
                "recommendation": "Must add K222 correction: the 'VT hurts' conclusion was for SPY-only; 50/50 reverses this."
            })

    # =====================================================================
    # ISSUE 5: Amihud illiquidity "passes Harvey" or "predicts volatility"
    # Correction: K266 showed K265 was look-ahead artifact
    # =====================================================================
    if re.search(r"Amihud.*有效|Amihud.*預測|Amihud.*passes|Amihud.*Harvey|流動性溢酬.*有效|illiquidity.*predict", full_text, re.IGNORECASE):
        has_correction = bool(re.search(r"K266|artifact|look-ahead|已修正|FAIL", full_text, re.IGNORECASE))
        if not has_correction:
            findings.append({
                "issue": "Amihud_look_ahead_artifact",
                "claim_in_article": "Claims Amihud illiquidity predicts volatility / passes Harvey",
                "correction": "K266: K265 result was look-ahead artifact from full-sample GARCH. Pure rolling: QQQ significantly WORSE (0-1/3 wins).",
                "severity": "MISLEADING",
                "has_disclaimer": False,
                "recommendation": "Must retract Amihud predictive claim. It was a methodological artifact."
            })

    # =====================================================================
    # ISSUE 6: Daily rebalancing "best" without net-of-TX context
    # Correction: K279/K281 — Daily dominates GROSS but Monthly wins NET
    # =====================================================================
    if re.search(r"每日.*最佳|daily.*best|日頻.*最優|每天調整.*更好", full_text, re.IGNORECASE):
        # This is a nuanced check — many articles correctly discuss this
        has_tx_context = bool(re.search(r"交易成本|transaction cost|TX|net.*Sharpe|淨.*Sharpe|月度.*勝|monthly.*win|net", full_text, re.IGNORECASE))
        if not has_tx_context and "VT" in full_text:
            findings.append({
                "issue": "daily_rebalancing_best",
                "claim_in_article": "Claims daily rebalancing is best without transaction cost context",
                "correction": "K279/K281: Daily Sharpe 0.787 GROSS but Monthly wins NET (0.239 vs 0.192). TX drag 225 trades/yr kills daily.",
                "severity": "OUTDATED",
                "has_disclaimer": False,
                "recommendation": "Add TX context: daily only best at zero cost; monthly wins net of realistic TX."
            })

    # =====================================================================
    # ISSUE 7: Sharpe 1.62 Taiwan momentum (may be from pre-validation)
    # Check if this was validated or if it's from early optimistic results
    # =====================================================================
    if re.search(r"Sharpe.*1\.62|1\.62.*Sharpe", full_text, re.IGNORECASE):
        has_context = bool(re.search(r"Harvey|OOS|out-of-sample|驗證|validation|淨|net", full_text, re.IGNORECASE))
        # Check if content is substantive (not just a stub)
        content_len = len(content)
        if content_len < 100:
            findings.append({
                "issue": "taiwan_sharpe_stub",
                "claim_in_article": f"Claims Sharpe 1.62 but article is a stub ({content_len} chars, no full content)",
                "correction": "Article has no substantive content to support the claim. Reader cannot verify.",
                "severity": "OUTDATED",
                "has_disclaimer": False,
                "recommendation": "Either expand with full methodology/caveats or mark as superseded."
            })

    # =====================================================================
    # ISSUE 8: Hybrid VT Sharpe ~2.0 / $1M→$17.4M
    # This is likely from daily rebalancing without NET context
    # =====================================================================
    if re.search(r"Sharpe.*2\.0|Sharpe.*~2|17.*M|\$17\.4M|\$1M.*\$17", full_text, re.IGNORECASE):
        has_context = bool(re.search(r"交易成本|transaction|CI|信賴區間|SE|bootstrap|net|淨", full_text, re.IGNORECASE))
        if "Hybrid VT" in full_text or "Hybrid Volatility" in full_text:
            findings.append({
                "issue": "hybrid_vt_sharpe_2",
                "claim_in_article": "Claims Hybrid VT Sharpe ~2.0, $1M→$17.4M",
                "correction": "K281: Gross Sharpe inflated by daily rebalancing. Monthly wins net. CI [1.2, 2.8] is wide. Position as ceiling, not expected.",
                "severity": "OUTDATED",
                "has_disclaimer": has_context,
                "recommendation": "Add prominent caveats: (1) this is GROSS of TX costs, (2) daily rebalancing, (3) CI is wide. Monthly VT is recommended path."
            })

    # =====================================================================
    # ISSUE 9: Empty/stub content — cannot verify any claims
    # =====================================================================
    if len(content) < 100 and len(content) > 0:
        # Already flagged by K262, but still problematic
        findings.append({
            "issue": "stub_content",
            "claim_in_article": f"Article has only {len(content)} chars of content — reader cannot verify any claim from title",
            "correction": "K262 identified 388 empty articles. Some were fixed but this one still has minimal content.",
            "severity": "OUTDATED",
            "has_disclaimer": False,
            "recommendation": "Expand content or add link to full research article."
        })

    return findings


def run_audit():
    articles = load_articles()
    print(f"Auditing {len(articles)} published articles...")

    all_findings = []
    articles_with_issues = 0

    for article in articles:
        aid = article["id"]
        title = article.get("title", "")
        content = article.get("description", "") or ""
        full_text = title + " " + content

        findings = check_claim(aid, title, content, full_text)

        if findings:
            articles_with_issues += 1
            for f in findings:
                all_findings.append({
                    "article_id": aid,
                    "article_title": title,
                    "article_created": article.get("created_at", ""),
                    "article_content_length": len(content),
                    **f
                })

    # Classify severity counts
    severity_counts = {}
    issue_counts = {}
    for f in all_findings:
        sev = f["severity"]
        iss = f["issue"]
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
        issue_counts[iss] = issue_counts.get(iss, 0) + 1

    # Build the MISLEADING list (highest priority)
    misleading = [f for f in all_findings if f["severity"] == "MISLEADING"]
    outdated = [f for f in all_findings if f["severity"] == "OUTDATED"]
    still_valid = [f for f in all_findings if f["severity"] == "STILL_VALID"]

    # =====================================================================
    # MANUAL AUDIT RESULTS — articles checked by reading full content
    # =====================================================================
    manual_audit = [
        {
            "article_id": "mile_d368b4da",
            "article_title": "我們測試了 12 個交易策略，只有 1 個通過嚴格檢驗",
            "issue": "TSMOM_passes_Harvey",
            "severity": "MISLEADING",
            "detail": "Claims 'only TSMOM passed Harvey t>3.0 among 12 strategies'. K255 showed TSMOM FAILS on full 21yr (t=2.34). Article has NO disclaimer.",
            "recommendation": "URGENT: Update to say '0 out of 12 passed full-sample Harvey' or add K255 correction note.",
            "content_accurate_at_time": True,
            "now_incorrect": True
        },
        {
            "article_id": "mile_281af193",
            "article_title": "你以為你在做風控，其實你在做趨勢交易——而且做對了",
            "severity": "MISLEADING",
            "issue": "VT_91pct_trend_following",
            "detail": "Says '91% of VT excess return explained by trend factor'. K53 showed only 5.2% alpha reduction (N=15). Article has NO K53 correction, still cites K46/K49.",
            "recommendation": "URGENT: Replace 91% with corrected K53 figure (5.2% equity alpha reduction, 32% Sharpe contribution).",
            "content_accurate_at_time": True,
            "now_incorrect": True
        },
        {
            "article_id": "mile_e8aefbf1",
            "article_title": "【已修正】VT 退休模擬：提供更穩定的存活率，但 max safe WR 仍為 4%",
            "severity": "MISLEADING",
            "issue": "withdrawal_rate_doubles",
            "detail": "Title says '已修正' but content STILL claims '12/VIX VT 將最大安全提領率從 4% 提升至 8%' in headline and conclusion. The '已修正' title contradicts the body which fully argues for 8%.",
            "recommendation": "URGENT: Body text still actively argues for 8% doubling. Must rewrite body to match the corrected title.",
            "content_accurate_at_time": False,
            "now_incorrect": True
        },
        {
            "article_id": "mile_5302df53",
            "article_title": "【已修正】退休金策略：VT 提供更穩定的 4% 存活率，但不會翻倍",
            "severity": "MISLEADING",
            "issue": "withdrawal_rate_doubles",
            "detail": "Title says '不會翻倍' but FIRST LINE of body says '波動率目標（VT）策略把退休安全提領率從 4% 翻倍到 8%'. Title and body directly contradict each other.",
            "recommendation": "URGENT: First paragraph must be rewritten to match the corrected title. Currently the opening line says the opposite of the title.",
            "content_accurate_at_time": False,
            "now_incorrect": True
        },
        {
            "article_id": "mile_ee473d5a",
            "article_title": "波動率擇時（VT）完全指南：15 個問題，48 個研究發現，一次講清楚",
            "severity": "STILL_VALID",
            "issue": "withdrawal_and_tsmom_corrected",
            "detail": "This comprehensive FAQ correctly handles both corrections: (1) Mentions K85 8% claim then explicitly says K87 overturned it — 'VT 不能把安全提領率翻倍到 8%'; (2) Says VT alpha 32% from TSMOM (K49 figure, not K46's 91%). Properly cites corrections.",
            "recommendation": "No action needed. This is the gold standard for self-correcting articles.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
        {
            "article_id": "mile_ea84b5cf",
            "article_title": "【已修正】VT 與 Trend Following 的初步發現（完整修正見 K53 文章）",
            "severity": "STILL_VALID",
            "issue": "VT_91pct_trend_following",
            "detail": "Title clearly says '已修正' and '完整修正見 K53 文章'. Reader is directed to K53.",
            "recommendation": "Adequate disclaimer. Consider adding a one-line summary of K53 correction in the body.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
        {
            "article_id": "mile_c738dd9d",
            "article_title": "VT 的雙重機制：Trend Following 只是配角，VIX 風控才是主角",
            "severity": "STILL_VALID",
            "issue": "VT_91pct_trend_following",
            "detail": "Title frames TF as '配角' and VIX as '主角'. Content correctly says 32% Sharpe from TF, 96% MDD from VIX. Consistent with K49/K53.",
            "recommendation": "No action needed. Conclusions align with corrected findings.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
        {
            "article_id": "mile_9071e562",
            "article_title": "K46->K53 方法論修正：VT 不是純 Trend Following，但 Leverage Effect 驅動 TSMOM 暴露（N=15 驗證）",
            "severity": "STILL_VALID",
            "issue": "VT_91pct_trend_following",
            "detail": "This IS the correction article itself. Properly documents K46→K53 evolution with N=15 cross-asset validation.",
            "recommendation": "No action needed. This is the authoritative correction.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
        {
            "article_id": "mile_a777ed5b",
            "article_title": "退休族的好消息：50/50+VT 讓你安心提領 5%",
            "severity": "STILL_VALID",
            "issue": "withdrawal_rate",
            "detail": "Claims 5% withdrawal with 50/50+VT based on K222 (which correctly reverses K36). Uses 50/50 not SPY-only. Does NOT claim 8% doubling. Consistent with corrected findings.",
            "recommendation": "No action needed. Correctly reflects K222 correction.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
        {
            "article_id": "mile_b232cdec",
            "article_title": "台灣投資人的懶人策略：每天花 10 秒看美股，年化多賺 18%",
            "severity": "OUTDATED",
            "issue": "taiwan_sharpe_stub",
            "detail": "Only 41 chars of content. Claims Sharpe 1.62 and '年化多賺 18%' in title but provides no methodology, caveats, or data source. Reader has no way to verify.",
            "recommendation": "Expand with full methodology or mark as superseded by comprehensive Taiwan article.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
        {
            "article_id": "mile_505a4c62",
            "article_title": "台股隔夜信號策略：美股 5 天動量如何創造 Sharpe 1.62",
            "severity": "OUTDATED",
            "issue": "taiwan_sharpe_stub",
            "detail": "Only 60 chars of content. Claims Sharpe 1.62 but no substantive article body.",
            "recommendation": "Expand or merge into comprehensive Taiwan strategy article.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
        {
            "article_id": "mile_20632f25",
            "article_title": "Hybrid VT 策略操作手冊：$1M → $17.4M，Sharpe ~2.0",
            "severity": "OUTDATED",
            "issue": "hybrid_vt_sharpe_2",
            "detail": "Claims Sharpe ~2.0 and $1M→$17.4M from daily Hybrid VT. K281 showed monthly wins net. CI [1.2, 2.8] is wide. Article mentions CI but headlines are misleading.",
            "recommendation": "Add prominent note: this is GROSS of TX. Monthly VT is the recommended approach (K281). Sharpe 2.0 is ceiling not expectation.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
        {
            "article_id": "mile_5823d219",
            "article_title": "我花了兩年研究投資策略，結論只有一行公式",
            "severity": "STILL_VALID",
            "issue": "daily_vs_monthly",
            "detail": "Actually correctly recommends monthly rebalancing and explicitly states '每月調整一次比每天調整賺更多'. Monthly net Sharpe 0.792 > Daily 0.679.",
            "recommendation": "No action needed. Correctly recommends monthly.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
        {
            "article_id": "mile_02592b29",
            "article_title": "我們花了 60 個實驗推薦波動率擇時，然後發現大多數人不該用",
            "severity": "STILL_VALID",
            "issue": "vt_self_correction",
            "detail": "Excellent self-correction article. Honestly states VT is NOT for most retail investors (DCA beats VT for young investors). Consistent with K78/K222.",
            "recommendation": "No action needed. Model self-correction article.",
            "content_accurate_at_time": True,
            "now_incorrect": False
        },
    ]

    # =====================================================================
    # Summary statistics
    # =====================================================================
    total_published = len(articles)
    total_flagged_auto = len(all_findings)
    total_manual = len(manual_audit)

    # Count articles with stub or empty content
    stub_articles = [a for a in articles if 0 < len(a.get("description", "") or "") < 100]
    empty_articles = [a for a in articles if len(a.get("description", "") or "") == 0]

    # Combine auto and manual for final counts
    all_misleading = [f for f in all_findings if f["severity"] == "MISLEADING"] + \
                     [f for f in manual_audit if f["severity"] == "MISLEADING"]
    all_outdated = [f for f in all_findings if f["severity"] == "OUTDATED"] + \
                   [f for f in manual_audit if f["severity"] == "OUTDATED"]
    all_valid = [f for f in all_findings if f["severity"] == "STILL_VALID"] + \
                [f for f in manual_audit if f["severity"] == "STILL_VALID"]

    # Deduplicate by article_id + issue
    seen = set()
    deduped_misleading = []
    for f in all_misleading:
        key = (f["article_id"], f["issue"])
        if key not in seen:
            seen.add(key)
            deduped_misleading.append(f)

    seen_outdated = set()
    deduped_outdated = []
    for f in all_outdated:
        key = (f["article_id"], f["issue"])
        if key not in seen_outdated:
            seen_outdated.add(key)
            deduped_outdated.append(f)

    summary = {
        "experiment": "K320",
        "title": "Website Content Quality Audit — Are Our Published Articles Accurate?",
        "date": datetime.now().isoformat(),
        "total_published_articles": total_published,
        "total_empty_articles_0_chars": len(empty_articles),
        "total_stub_articles_lt100_chars": len(stub_articles),
        "total_content_deficient": len(empty_articles) + len(stub_articles),
        "total_findings": len(deduped_misleading) + len(deduped_outdated) + len(all_valid),
        "severity_breakdown": {
            "MISLEADING": len(deduped_misleading),
            "OUTDATED": len(deduped_outdated),
            "STILL_VALID": len(all_valid),
        },
        "issue_breakdown": {
            "TSMOM_passes_Harvey": {
                "description": "Articles claiming TSMOM passes Harvey t>3.0 (K255 showed it FAILS on full sample)",
                "count": len([f for f in deduped_misleading + deduped_outdated if f.get("issue") == "TSMOM_passes_Harvey"]),
                "correction_knowledge": "K255",
            },
            "VT_91pct_trend_following": {
                "description": "Articles claiming 91% of VT alpha is trend following (K53 showed only 5.2%)",
                "count": len([f for f in deduped_misleading + deduped_outdated if f.get("issue") == "VT_91pct_trend_following"]),
                "correction_knowledge": "K53",
            },
            "withdrawal_rate_doubles": {
                "description": "Articles claiming VT doubles safe withdrawal rate from 4% to 8% (K87 showed 8% fails stress test)",
                "count": len([f for f in deduped_misleading + deduped_outdated if f.get("issue") == "withdrawal_rate_doubles"]),
                "correction_knowledge": "K87/K222",
            },
            "Amihud_look_ahead_artifact": {
                "description": "Articles claiming Amihud illiquidity predicts vol (K266: was look-ahead artifact)",
                "count": len([f for f in deduped_misleading + deduped_outdated if f.get("issue") == "Amihud_look_ahead_artifact"]),
                "correction_knowledge": "K266",
            },
            "daily_rebalancing_best": {
                "description": "Articles claiming daily rebalancing best without TX context (K281: monthly wins net)",
                "count": len([f for f in deduped_misleading + deduped_outdated if f.get("issue") == "daily_rebalancing_best"]),
                "correction_knowledge": "K279/K281",
            },
            "stub_content": {
                "description": "Articles with <100 chars that cannot support their title claims",
                "count": len(stub_articles),
                "correction_knowledge": "K262",
            },
            "hybrid_vt_sharpe_2": {
                "description": "Articles claiming Hybrid VT Sharpe ~2.0 without net-of-TX context",
                "count": len([f for f in deduped_misleading + deduped_outdated if f.get("issue") == "hybrid_vt_sharpe_2"]),
                "correction_knowledge": "K281",
            },
        },
        "urgent_corrections_needed": [
            {
                "article_id": "mile_d368b4da",
                "title": "我們測試了 12 個交易策略，只有 1 個通過嚴格檢驗",
                "issue": "TSMOM doesn't actually pass Harvey on full sample",
                "action": "Change to '0 passed full-sample' or add K255 correction note"
            },
            {
                "article_id": "mile_281af193",
                "title": "你以為你在做風控，其實你在做趨勢交易",
                "issue": "91% figure is methodologically flawed (K53: 5.2%)",
                "action": "Replace 91% with 32% (Sharpe) or 5.2% (alpha reduction)"
            },
            {
                "article_id": "mile_e8aefbf1",
                "title": "【已修正】VT 退休模擬",
                "issue": "Body contradicts '已修正' title — still argues for 8% doubling",
                "action": "Rewrite body to match corrected title"
            },
            {
                "article_id": "mile_5302df53",
                "title": "【已修正】退休金策略",
                "issue": "Opening line says '翻倍到 8%' but title says '不會翻倍'",
                "action": "Rewrite opening paragraph to match corrected title"
            },
        ],
        "positive_findings": [
            "mile_ee473d5a (VT Complete Guide): Correctly handles ALL corrections — model article",
            "mile_9071e562 (K46→K53): IS the correction article, properly documents evolution",
            "mile_c738dd9d (VT Dual Mechanism): Correctly uses 32% figure, not 91%",
            "mile_a777ed5b (Retirement 5%): Correctly uses K222 correction, claims 5% not 8%",
            "mile_5823d219 (12/VIX Formula): Correctly recommends monthly over daily",
            "mile_02592b29 (VT Self-Correction): Honest about VT not being for most people",
        ],
        "methodology_notes": [
            "Automated regex scan of 525 published articles for 7 claim patterns",
            "Manual deep-read of 14 most-flagged articles",
            "Cross-referenced against knowledge.json corrections (K255, K266, K281, K222, K53)",
            "Severity: MISLEADING = active misinformation; OUTDATED = stale data/context; STILL_VALID = correctly handles corrections",
        ],
        "conclusion": (
            f"Of {total_published} published articles, 4 contain MISLEADING content that directly contradicts "
            "corrected findings (TSMOM passes, 91% trend, withdrawal doubling). "
            f"{len(empty_articles)} articles have completely empty content, "
            f"{len(stub_articles)} have stub content (<100 chars) — total {len(empty_articles) + len(stub_articles)} "
            "content-deficient articles that cannot support their title claims. "
            "6 articles are positively identified as correctly handling self-corrections. "
            "The '已修正' title prefix is inconsistently applied — some articles have it in the title "
            "but the body still contains the original uncorrected claims."
        ),
    }

    # Auto-detected findings detail
    results = {
        "summary": summary,
        "misleading_articles": deduped_misleading,
        "outdated_articles": deduped_outdated,
        "valid_articles": [f for f in manual_audit if f["severity"] == "STILL_VALID"],
        "manual_audit_detail": manual_audit,
    }

    # Save results
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Print summary
    print("\n" + "=" * 70)
    print("K320: CONTENT QUALITY AUDIT RESULTS")
    print("=" * 70)
    print(f"\nTotal published articles: {total_published}")
    print(f"Articles with empty content (0 chars): {len(empty_articles)}")
    print(f"Articles with stub content (1-99 chars): {len(stub_articles)}")
    print(f"Total content-deficient: {len(empty_articles) + len(stub_articles)}")
    print(f"\nSeverity breakdown:")
    print(f"  MISLEADING (active misinformation):  {len(deduped_misleading)}")
    print(f"  OUTDATED (stale but not dangerous):   {len(deduped_outdated)}")
    print(f"  STILL_VALID (correctly corrected):    {len(all_valid)}")

    print(f"\n{'='*70}")
    print("URGENT CORRECTIONS NEEDED (4 articles):")
    print(f"{'='*70}")
    for item in summary["urgent_corrections_needed"]:
        print(f"\n  [{item['article_id']}]")
        print(f"  Title: {item['title']}")
        print(f"  Issue: {item['issue']}")
        print(f"  Action: {item['action']}")

    print(f"\n{'='*70}")
    print("POSITIVE FINDINGS (6 articles correctly handle corrections):")
    print(f"{'='*70}")
    for note in summary["positive_findings"]:
        print(f"  + {note}")

    print(f"\nResults saved to: {OUTPUT_PATH}")
    return results


if __name__ == "__main__":
    run_audit()
