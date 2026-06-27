#!/usr/bin/env python3
"""Publish the 2026-06-27 blog fact-check as a reader-facing article."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from volpred.charts import upload_chart
from volpred.publisher.publisher import Publisher, _audit_general_content, _make_excerpt
from volpred.publisher.prepublish_audit import audit_content_provenance, audit_image_urls


ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments" / "blog_factcheck_20260627"
RESULTS_PATH = EXP_DIR / "blog_factcheck_20260627_results.json"
ARTICLE_TITLE = "數字成立，因果還沒成立：費半暴漲後的台股敘事查核"
ARTICLE_TAGS = ["市場查核", "費半", "台股", "外資", "台指期", "風險教育"]


def _tw_hundred_million(ntd: float) -> float:
    return ntd / 1e8


def make_chart(results: dict) -> tuple[Path, str]:
    sox = results["market_context"]["sox"]["2026-03-27"]["pct_change_to_2026_06_26"]
    taiex = results["market_context"]["taiex"]["2026-03-27"]["pct_change_to_2026_06_26"]
    claims = {c["claim_id"]: c for c in results["claim_results"]}
    flow = claims["C4_foreign_cash_no_net_buy_since_late_march"]["evidence"]
    components = flow["components_ntd"]
    txf = claims["C3_taiwan_txf_foreign_70k_short"]["evidence"]

    monthly_labels = ["3/27-3/31", "4月", "5月", "6/1-6/26"]
    monthly_values = [
        _tw_hundred_million(
            components["2026-03-27"]
            + components["2026-03-30"]
            + components["2026-03-31"]
        ),
        _tw_hundred_million(
            components["115年04月01日至115年04月30日 三大法人買賣金額統計表"]
        ),
        _tw_hundred_million(
            components["115年05月01日至115年05月29日 三大法人買賣金額統計表"]
        ),
        _tw_hundred_million(
            components["115年06月01日至115年06月26日 三大法人買賣金額統計表"]
        ),
    ]

    plt.rcParams["font.sans-serif"] = [
        "PingFang HK",
        "Heiti TC",
        "STHeiti",
        "Arial Unicode MS",
        "sans-serif",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    fig.suptitle("市場數字成立，但操縱結論還缺證據", fontsize=16, fontweight="bold")

    ax = axes[0]
    bars = ax.bar(["SOX", "TAIEX"], [sox, taiex], color=["#2563eb", "#059669"])
    ax.set_title("3/27 到 6/26 指數漲幅")
    ax.set_ylabel("%")
    ax.axhline(0, color="#222", linewidth=0.8)
    for bar, val in zip(bars, [sox, taiex]):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 2, f"+{val:.1f}%", ha="center")

    ax = axes[1]
    colors = ["#dc2626" if v < 0 else "#16a34a" for v in monthly_values]
    bars = ax.bar(monthly_labels, monthly_values, color=colors)
    ax.set_title("外資現貨買賣超")
    ax.set_ylabel("新台幣億元")
    ax.axhline(0, color="#222", linewidth=0.8)
    for bar, val in zip(bars, monthly_values):
        label = f"{val:,.0f}"
        va = "bottom" if val >= 0 else "top"
        offset = 80 if val >= 0 else -80
        ax.text(bar.get_x() + bar.get_width() / 2, val + offset, label, ha="center", va=va, fontsize=9)

    ax = axes[2]
    futures_labels = ["多方未平倉", "空方未平倉", "淨部位"]
    futures_values = [
        txf["long_open_interest_contracts"],
        -txf["short_open_interest_contracts"],
        txf["net_open_interest_contracts"],
    ]
    bars = ax.bar(futures_labels, futures_values, color=["#16a34a", "#dc2626", "#7c3aed"])
    ax.set_title("6/26 外資 TXF 未平倉")
    ax.set_ylabel("contracts")
    ax.set_ylim(min(futures_values) * 1.18, max(futures_values) * 1.5)
    ax.axhline(0, color="#222", linewidth=0.8)
    ax.tick_params(axis="x", rotation=15)
    for bar, val in zip(bars, futures_values):
        va = "bottom" if val >= 0 else "top"
        offset = 2500 if val >= 0 else -2500
        ax.text(bar.get_x() + bar.get_width() / 2, val + offset, f"{val:,.0f}", ha="center", va=va, fontsize=9)

    fig.text(
        0.01,
        0.01,
        "資料來源：FRED NASDAQSOX、TWSE、TAIFEX；計算：experiments/blog_factcheck_20260627",
        fontsize=9,
        color="#555",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.93])
    out = EXP_DIR / "blog_factcheck_market_snapshot.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out, upload_chart(str(out))


def build_content(results: dict, chart_url: str) -> str:
    return f"""# {ARTICLE_TITLE}

最近有一篇市場評論在流傳。文章的口氣很重：AI 泡沫、政客喊盤、外資台指期空單、散戶接盤，最後指向一個熟悉的結論：背後有人在控盤。

我先處理比較基本的問題。裡面的數字到底站不站得住？如果數字是真的，能不能直接推到「黑手操縱」？

我把原文拆成幾個可以驗的部分，用公開資料重算。結果很清楚：**很多數字是真的，但最重的因果結論還沒被證明。**

![費半、外資現貨與台指期部位查核圖]({chart_url})

## 先看成立的部分

第一，費半真的漲得很誇張。

用 FRED 的 NASDAQSOX 資料，2026-03-27 到 2026-06-26，費半從 7,457.67 漲到 13,203.57，漲幅是 **77.0%**。如果從 3/31 起算，漲幅是 **74.0%**。原文說「一季漲 80%」是偏上取整，但方向沒有錯。

第二，台股也不是小漲。

同一段時間，加權指數從 33,112.59 到 44,571.76，漲幅 **34.6%**。如果從 3/31 起算，漲幅 **40.5%**。這種速度本來就會讓市場敘事變得很極端。

第三，外資台指期空單這句話是真的。

期交所 2026-06-26 的資料顯示，外資及陸資在臺股期貨的多空未平倉淨額是 **-76,391 口**。原文說「7 萬口空單」，這一點可以驗。

第四，外資現貨沒有一路追買。

證交所三大法人買賣金額顯示，2026-03-27 到 2026-06-26，外資及陸資在台股現貨合計是 **淨賣超約 2,938.5 億元**。即使只從 4/1 算到 6/26，也還是 **淨賣超約 1,128.1 億元**。

所以「指數大漲，但外資現貨沒有一路買上去」這個觀察成立。

## 不能直接跳到操縱

問題出在下一步。

外資期貨淨空，不等於外資一定在做空台股。期貨部位可能是避險，可能是套利，也可能是方向交易。沒有更細的部位拆解，我們不能只看一個淨空數字就說它代表倒貨。

外資現貨賣超，也不等於散戶一定高檔接走所有籌碼。台股市場還有投信、自營、公司庫藏股、ETF 申贖、個股權重變化。外資賣超只能說明資金流向，不能單獨說明最後誰在替誰接盤。

成交金額也一樣。2026-06-26 台股成交金額是 **1.673 兆元**，量很大，當天加權也跌了 1,683.50 點。這能說明市場換手激烈，不能直接說明誰在「左手賣右手」。

要證明操縱，需要的是另一種資料：受益人交易紀錄、券商或 order book 層級的下單順序、關聯帳戶、監管調查，或法律認定。公開聚合資料做不到那一步。

## 比較好的讀法

原文有參考價值的地方，是提醒投資人：**市場上漲很快時，價格、部位、成交量會一起變得很戲劇化。**

戲劇化的數字，很容易被包成戲劇化的故事。

費半三個月漲七成多，台股一季漲三到四成，外資現貨沒有追買，期貨端又有七萬多口淨空。這些資料放在一起，足以說明市場已經進入高度緊繃的敘事環境。

但投資決策不能只停在「故事聽起來合理」。合理故事有三種：

| 觀察 | 可以說什麼 | 還不能說什麼 |
|---|---|---|
| 費半大漲 | AI / 半導體風險偏好很強 | 泡沫必然馬上破 |
| 外資現貨賣超 | 外資沒有一路買上去 | 外資必然在高檔倒貨 |
| TXF 淨空單 | 外資期貨端偏空或避險 | 單憑此證明操縱 |
| 成交金額放大 | 換手與波動壓力上升 | 誰在左手賣右手 |

市場風險很可能真的升高。可是「風險升高」和「操縱已被證明」是兩句不同的話。

## 投資人該拿走什麼

這次查核給一般投資人的提醒很簡單。

第一，看到很大的市場敘事，先把數字拆開驗。費半漲幅、外資賣超、期貨淨空，都可以從公開來源查到。

第二，數字成立後，再問它能支持到哪裡。外資賣超可以支持「外資沒有追買」，不能自動支持「散戶被設局」。

第三，當市場已經漲很快，持有部位的人要多看風險暴露，不要只看故事。現金比例、槓桿、停損規則、單一產業集中度，比猜誰在控盤更實用。

這篇評論的數字部分，值得看。它的操縱結論，要保留。

*資料來源：VolPred fact-check 實驗 `experiments/blog_factcheck_20260627/`。數據來源包含 FRED NASDAQSOX、TWSE 每日市場成交資訊、TWSE 三大法人買賣金額、TAIFEX 三大法人期貨契約資料、American Presidency Project。查核期間主要為 2026-03-27 至 2026-06-26。本文是市場資料查核與風險教育，不構成投資建議。*
"""


def article_details(chart_path: Path, chart_url: str) -> dict:
    return {
        "content_type": "general_article",
        "experiment_refs": ["blog_factcheck_20260627"],
        "source_artifact": str(RESULTS_PATH.relative_to(ROOT)),
        "chart_path": str(chart_path.relative_to(ROOT)),
        "chart_url": chart_url,
        "origin": "user_requested_blog_factcheck_publish",
        "cluster_waiver": (
            "User explicitly requested publication of a timely fact-check "
            "on a circulating market narrative; angle is evidence literacy, "
            "not another Taiwan directional call."
        ),
    }


def audit_article_content(content: str) -> None:
    issues = _audit_general_content("general", ["一般讀者", *ARTICLE_TAGS], content)
    if issues:
        raise ValueError("general audience audit failed: " + "; ".join(issues))

    prov = audit_content_provenance(
        content,
        ["BLOG_FACTCHECK_20260627"],
        root=ROOT,
    )
    if prov.get("tier1_findings") and not prov.get("skipped"):
        issue_text = "; ".join(
            f"{f.get('raw')!r} in {f.get('context', '')}" for f in prov["tier1_findings"]
        )
        raise ValueError("content provenance audit failed: " + issue_text)

    image_audit = audit_image_urls(content)
    if image_audit.get("broken"):
        issue_text = "; ".join(
            f"{b['url']} ({b['reason']})" for b in image_audit["broken"]
        )
        raise ValueError("image URL audit failed: " + issue_text)


def find_existing_by_title(pub: Publisher, title: str) -> dict | None:
    for item in pub._load_feed():
        if item.get("title") == title and item.get("status") != "retracted":
            return item
    return None


def update_existing_article(pub: Publisher, existing: dict, content: str, details: dict) -> str:
    item = dict(existing)
    item["content"] = content
    item["description"] = _make_excerpt(content)
    merged_details = dict(item.get("details") or {})
    merged_details.update(details)
    item["details"] = merged_details
    item["tags"] = ["一般讀者", *ARTICLE_TAGS]
    item["audience"] = "general"
    item["category"] = "general"
    pub_id = str(item["id"])

    if not pub._rewrite_feed_entry(pub_id, item):
        raise RuntimeError(f"failed to rewrite existing feed entry {pub_id}")

    sys.path.insert(0, str(ROOT / "scripts"))
    from supabase_sync import sync_article

    if not sync_article(item, storage_dir=pub.reports_dir.parent):
        pub._record_failed_supabase_sync(pub_id)
        raise RuntimeError(f"Supabase sync failed for {pub_id}")

    from volpred.publisher.live_verify import stamp_verified, verify_article_live

    live_ok = verify_article_live(pub_id)
    stamp_verified(item, verified=live_ok)
    pub._rewrite_feed_entry(pub_id, item)
    if not live_ok:
        raise RuntimeError(f"live verify failed for {pub_id}")
    return pub_id


def main() -> None:
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    chart_path, chart_url = make_chart(results)
    content = build_content(results, chart_url)
    details = article_details(chart_path, chart_url)
    audit_article_content(content)

    pub = Publisher()
    existing = find_existing_by_title(pub, ARTICLE_TITLE)
    if existing:
        pub_id = update_existing_article(pub, existing, content, details)
        action = "updated_existing"
    else:
        pub_id = pub.publish_milestone(
            title=ARTICLE_TITLE,
            description=content,
            phase="market_factcheck",
            category="general",
            audience="general",
            status="published",
            proposer="用戶",
            tags=ARTICLE_TAGS,
            details=details,
        )
        action = "published_new"
    print(
        json.dumps(
            {"action": action, "pub_id": pub_id, "chart_url": chart_url},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
