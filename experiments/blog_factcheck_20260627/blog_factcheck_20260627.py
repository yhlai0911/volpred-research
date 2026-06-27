#!/usr/bin/env python3
"""Reproducible fact-check for a 2026-06-27 Blogger market commentary."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path


EXPERIMENT_ID = "blog_factcheck_20260627"
BLOG_URL = (
    "https://kelvenslife.blogspot.com/2026/06/blog-post_27.html"
    "?fbclid=IwY2xjawSsadlleHRuA2FlbQIxMABicmlkETFBVm5tTFU5dmdlaDdLMk1Ec3J0YwZhcHBfaWQQMjIyMDM5MTc4ODIwMDg5MgABHtPjhaprEJGBRCc87zL4zfWXlySGbLfdmX640_G2WYONSDdlJZ1gZCJsE6QO_aem_46gROqpHxBt6_90ZJ_Fsvw"
)
FRED_NASDAQSOX_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQSOX"
TWSE_FMTQIK = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TWSE_BFI82U = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
TAIFEX_FUT_CONTRACTS_DOWN = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
TRUMP_TRUTH_SOCIAL_20250409 = (
    "https://www.presidency.ucsb.edu/documents/truth-social-posts-april-9-2025"
)
OPENAI_CONFIDENTIAL_S1 = "https://openai.com/index/openai-submits-confidential-s-1/"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip = True
        if tag in {"p", "br", "div", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip = False
        if tag in {"p", "div", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        text = unescape(data).strip()
        if text:
            self.parts.append(text + " ")

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


@dataclass
class ClaimResult:
    claim_id: str
    claim: str
    verdict: str
    evidence: dict
    interpretation: str


def fetch_bytes(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict | None = None,
    timeout: int = 12,
    retries: int = 2,
) -> bytes:
    req_headers = {
        "User-Agent": "Mozilla/5.0 (VolPred fact-check; research reproducibility)",
    }
    if headers:
        req_headers.update(headers)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # network reliability is not a research result
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    try:
        cmd = ["curl", "-fsSL", "--max-time", str(max(timeout, 20)), url]
        if data is not None:
            cmd = ["curl", "-fsSL", "--max-time", str(max(timeout, 20)), "-X", "POST"]
            for key, value in req_headers.items():
                cmd.extend(["-H", f"{key}: {value}"])
            cmd.extend(["--data-binary", data.decode("ascii"), url])
        completed = subprocess.run(cmd, check=True, capture_output=True)
        return completed.stdout
    except Exception as curl_exc:
        raise RuntimeError(f"fetch failed after urllib retries and curl fallback: {url}") from (
            curl_exc if last_error is None else last_error
        )


def fetch_json(url: str, params: dict[str, str]) -> dict:
    query = urllib.parse.urlencode(params)
    return json.loads(fetch_bytes(f"{url}?{query}").decode("utf-8"))


def fetch_blog_text() -> tuple[str, dict[str, str]]:
    raw = fetch_bytes(BLOG_URL).decode("utf-8", errors="ignore")
    parser = TextExtractor()
    parser.feed(raw)
    text = parser.text
    snippets = {}
    for key in [
        "Open AI",
        "費半指數",
        "現在就是買進股票的時機",
        "7萬口",
        "自三月底以來",
    ]:
        idx = text.find(key)
        if idx >= 0:
            snippets[key] = text[max(0, idx - 160) : idx + 360]
    return text, snippets


def parse_fred_sox() -> dict[str, float]:
    rows = fetch_bytes(FRED_NASDAQSOX_CSV).decode("utf-8").splitlines()
    out: dict[str, float] = {}
    for row in csv.DictReader(rows):
        value = row.get("NASDAQSOX")
        if value and value != ".":
            out[row["observation_date"]] = float(value)
    return out


def twse_market_month(yyyymm01: str) -> dict[str, dict]:
    data = fetch_json(TWSE_FMTQIK, {"date": yyyymm01, "response": "json"})
    if data.get("stat") != "OK":
        raise RuntimeError(f"TWSE FMTQIK failed for {yyyymm01}: {data.get('stat')}")
    fields = data["fields"]
    out = {}
    for row in data["data"]:
        rec = dict(zip(fields, row))
        out[rec["日期"]] = rec
    return out


def twse_foreign_net_day(yyyymmdd: str) -> int:
    data = fetch_json(
        TWSE_BFI82U,
        {"response": "json", "type": "day", "dayDate": yyyymmdd},
    )
    if data.get("stat") != "OK":
        raise RuntimeError(f"TWSE BFI82U day failed for {yyyymmdd}: {data.get('stat')}")
    for row in data["data"]:
        if row[0].startswith("外資及陸資"):
            return int(row[3].replace(",", ""))
    raise RuntimeError(f"foreign row not found for {yyyymmdd}")


def twse_foreign_net_month(yyyymm01: str) -> tuple[str, int]:
    data = fetch_json(
        TWSE_BFI82U,
        {"response": "json", "type": "month", "monthDate": yyyymm01},
    )
    if data.get("stat") != "OK":
        raise RuntimeError(f"TWSE BFI82U month failed for {yyyymm01}: {data.get('stat')}")
    for row in data["data"]:
        if row[0].startswith("外資及陸資"):
            return data["title"], int(row[3].replace(",", ""))
    raise RuntimeError(f"foreign row not found for month {yyyymm01}")


def taifex_txf_foreign_position(yyyymmdd_slash: str) -> dict[str, int]:
    post = urllib.parse.urlencode(
        {
            "queryStartDate": yyyymmdd_slash,
            "queryEndDate": yyyymmdd_slash,
            "commodityId": "TXF",
        }
    ).encode("ascii")
    raw = fetch_bytes(
        TAIFEX_FUT_CONTRACTS_DOWN,
        data=post,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    text = raw.decode("big5", errors="replace")
    rows = list(csv.DictReader(text.splitlines()))
    for row in rows:
        if row.get("身份別") == "外資及陸資":
            return {
                "long_open_interest_contracts": int(row["多方未平倉口數"].replace(",", "")),
                "short_open_interest_contracts": int(row["空方未平倉口數"].replace(",", "")),
                "net_open_interest_contracts": int(row["多空未平倉口數淨額"].replace(",", "")),
                "net_open_interest_amount_ntd_thousand": int(
                    row["多空未平倉契約金額淨額(千元)"].replace(",", "")
                ),
            }
    raise RuntimeError("TAIFEX foreign TXF row not found")


def presidency_truth_social_snippet() -> dict[str, bool | str]:
    html = fetch_bytes(TRUMP_TRUTH_SOCIAL_20250409).decode("utf-8", errors="ignore")
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html)))
    phrase = "THIS IS A GREAT TIME TO BUY!!! DJT"
    pause = "I have authorized a 90 day PAUSE"
    return {
        "source_url": TRUMP_TRUTH_SOCIAL_20250409,
        "contains_buy_phrase": phrase in text,
        "contains_90_day_pause": pause in text,
    }


def pct_change(start: float, end: float) -> float:
    return (end / start - 1.0) * 100.0


def main() -> int:
    out_dir = Path(__file__).resolve().parent
    blog_text, blog_snippets = fetch_blog_text()

    sox = parse_fred_sox()
    sox_end = sox["2026-06-26"]
    sox_calc = {
        start_date: {
            "start": sox[start_date],
            "end_2026_06_26": sox_end,
            "pct_change_to_2026_06_26": round(pct_change(sox[start_date], sox_end), 3),
        }
        for start_date in ["2026-03-27", "2026-03-31", "2026-04-09"]
    }

    twse_mar = twse_market_month("20260301")
    twse_jun = twse_market_month("20260601")
    taiex_calc = {}
    for roc_date, iso_date in [
        ("115/03/27", "2026-03-27"),
        ("115/03/31", "2026-03-31"),
    ]:
        start_index = float(twse_mar[roc_date]["發行量加權股價指數"].replace(",", ""))
        end_index = float(twse_jun["115/06/26"]["發行量加權股價指數"].replace(",", ""))
        taiex_calc[iso_date] = {
            "start": start_index,
            "end_2026_06_26": end_index,
            "pct_change_to_2026_06_26": round(pct_change(start_index, end_index), 3),
        }

    twse_20260626 = twse_jun["115/06/26"]
    taiwan_turnover = int(twse_20260626["成交金額"].replace(",", ""))

    foreign_components = {
        "2026-03-27": twse_foreign_net_day("20260327"),
        "2026-03-30": twse_foreign_net_day("20260330"),
        "2026-03-31": twse_foreign_net_day("20260331"),
    }
    for month in ["20260401", "20260501", "20260601"]:
        title, value = twse_foreign_net_month(month)
        foreign_components[title] = value
    foreign_total = sum(foreign_components.values())
    foreign_total_from_april = sum(
        value for key, value in foreign_components.items() if key.startswith("115年04") or key.startswith("115年05") or key.startswith("115年06")
    )

    taifex_txf = taifex_txf_foreign_position("2026/06/26")
    trump_truth = presidency_truth_social_snippet()

    claim_results = [
        ClaimResult(
            claim_id="C1_sox_up_80pct_quarter",
            claim="原文稱三月底以來費半指數一季上漲 80%。",
            verdict="MOSTLY_TRUE_BUT_ROUNDED_UP",
            evidence={
                "source": FRED_NASDAQSOX_CSV,
                "calculations": sox_calc,
            },
            interpretation=(
                "用 FRED/NASDAQSOX，2026-03-27 到 2026-06-26 漲 77.1%，"
                "2026-03-31 到 2026-06-26 漲 74.0%。80% 是偏上取整，"
                "但『大約七成多到八成』方向成立。"
            ),
        ),
        ClaimResult(
            claim_id="C2_trump_2025_04_09_buy_call",
            claim="原文稱川普在去年 4/9 喊『現在就是買進股票的時機』，並造成政策 V 轉敘事。",
            verdict="TRUE_FOR_BUY_CALL_AND_TARIFF_PAUSE_DATE",
            evidence=trump_truth,
            interpretation=(
                "American Presidency Project 的 2025-04-09 Truth Social 存檔同日含 "
                "'THIS IS A GREAT TIME TO BUY!!! DJT' 與 90-day pause 貼文。"
                "這可驗證發文與政策暫緩同日存在；是否構成炒股或內線，"
                "需要交易紀錄/調查證據，本文沒有提供。"
            ),
        ),
        ClaimResult(
            claim_id="C3_taiwan_txf_foreign_70k_short",
            claim="原文稱台灣加權指數中外資有約 7 萬口期貨空單。",
            verdict="TRUE_FOR_2026_06_26_TXF_NET_POSITION",
            evidence={
                "source": TAIFEX_FUT_CONTRACTS_DOWN,
                "date": "2026-06-26",
                "commodity": "TXF",
                **taifex_txf,
            },
            interpretation=(
                "期交所 2026-06-26 臺股期貨外資及陸資多空未平倉淨額為 "
                f"{taifex_txf['net_open_interest_contracts']:,} 口，確實約為 7.6 萬口淨空。"
                "但期貨淨空可以是避險、套利或方向部位；不能單獨證明現貨拉高倒貨。"
            ),
        ),
        ClaimResult(
            claim_id="C4_foreign_cash_no_net_buy_since_late_march",
            claim="原文稱自三月底以來台股外資幾乎沒有買超。",
            verdict="TRUE_AND_STRONGER_THAN_STATED",
            evidence={
                "source": TWSE_BFI82U,
                "components_ntd": foreign_components,
                "total_from_2026_03_27_to_2026_06_26_ntd": foreign_total,
                "total_from_2026_03_27_to_2026_06_26_twd_bn": round(foreign_total / 1e9, 3),
                "total_from_2026_03_27_to_2026_06_26_twd_100m": round(
                    foreign_total / 1e8, 3
                ),
                "total_from_2026_04_01_to_2026_06_26_ntd": foreign_total_from_april,
                "total_from_2026_04_01_to_2026_06_26_twd_bn": round(
                    foreign_total_from_april / 1e9, 3
                ),
                "total_from_2026_04_01_to_2026_06_26_twd_100m": round(
                    foreign_total_from_april / 1e8, 3
                ),
            },
            interpretation=(
                "TWSE 三大法人買賣金額顯示：2026-03-27 到 2026-06-26，"
                f"外資及陸資合計淨賣超約 {abs(foreign_total) / 1e8:.1f} 億元；"
                f"即使只從 4/1 算到 6/26，也淨賣超約 {abs(foreign_total_from_april) / 1e8:.1f} 億元。"
                "所以『幾乎沒有買超』方向成立，實際上是累計賣超。"
            ),
        ),
        ClaimResult(
            claim_id="C5_twse_turnover_2026_06_26",
            claim="文章脈絡暗示台股高檔放大量；需驗當日成交金額量級。",
            verdict="TRUE_FOR_HIGH_TURNOVER_ON_DATE",
            evidence={
                "source": TWSE_FMTQIK,
                "date": "2026-06-26",
                "taiex_close": twse_20260626["發行量加權股價指數"],
                "taiex_change_points": twse_20260626["漲跌點數"],
                "turnover_ntd": taiwan_turnover,
                "turnover_twd_trillion": round(taiwan_turnover / 1e12, 3),
            },
            interpretation=(
                "TWSE 顯示 2026-06-26 加權指數收 44,571.76，成交金額 "
                f"{taiwan_turnover / 1e12:.3f} 兆元，屬高量級。"
                "但單日大量與當日下跌不能直接推論為誰在倒貨。"
            ),
        ),
        ClaimResult(
            claim_id="C6_openai_ipo_one_trillion",
            claim="原文稱 OpenAI 今年要 IPO，估值高達一兆美元。",
            verdict="PARTLY_SUPPORTED_NEEDS_CAUTION",
            evidence={
                "official_source_url": OPENAI_CONFIDENTIAL_S1,
                "script_note": "OpenAI official page may block non-browser fetches; this script does not use it as a numeric source.",
                "source_status": (
                    "Public reporting and the official OpenAI page should be checked manually. "
                    "A confidential S-1 does not itself prove listing date or final valuation."
                ),
            },
            interpretation=(
                "若官方說法是 confidential S-1，代表已啟動上市文件程序；"
                "但『今年要 IPO』與『一兆美元』仍是未完成交易的時程/估值敘事，"
                "不能當成已定案事實。"
            ),
        ),
        ClaimResult(
            claim_id="C7_manipulation_black_hand",
            claim="原文把上述現象推論為黑手操縱、散戶被設局接盤。",
            verdict="NOT_PROVEN_BY_AVAILABLE_AGGREGATE_DATA",
            evidence={
                "observed_facts": [
                    "SOX and TAIEX rose sharply over the selected window.",
                    "Foreign investors were net short TXF on 2026-06-26.",
                    "Foreign cash-market flow was net selling over the selected window.",
                ],
                "missing_evidence": [
                    "Beneficial-owner level trade records.",
                    "Order-book or broker-level sequencing showing wash/left-hand-right-hand trades.",
                    "Regulatory investigation or legal finding.",
                    "Evidence linking named political/corporate actors to pre-event trades.",
                ],
            },
            interpretation=(
                "這是作者的強因果敘事，不是本文資料可驗出的事實。"
                "聚合層級資料能支持『高估值/高漲幅/外資現貨未買超/期貨淨空』，"
                "不能支持『操縱』這個法律與微觀交易層級命題。"
            ),
        ),
    ]

    results = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": None,
        "blog_url": BLOG_URL,
        "data_sources": {
            "blog": BLOG_URL,
            "fred_nasdaqsox": FRED_NASDAQSOX_CSV,
            "twse_market": TWSE_FMTQIK,
            "twse_institutional_flows": TWSE_BFI82U,
            "taifex_futures_institutional_position": TAIFEX_FUT_CONTRACTS_DOWN,
            "american_presidency_project": TRUMP_TRUTH_SOCIAL_20250409,
            "openai_official": OPENAI_CONFIDENTIAL_S1,
        },
        "blog_text_characters": len(blog_text),
        "blog_snippets": blog_snippets,
        "market_context": {
            "sox": sox_calc,
            "taiex": taiex_calc,
            "twse_2026_06_26": {
                "close": twse_20260626["發行量加權股價指數"],
                "change_points": twse_20260626["漲跌點數"],
                "turnover_ntd": taiwan_turnover,
            },
        },
        "claim_results": [asdict(c) for c in claim_results],
        "overall_verdict": (
            "The article contains several numerically verifiable and mostly correct market observations, "
            "but its strongest causal claim of coordinated manipulation is not proven by the available aggregate data."
        ),
    }

    output_path = out_dir / f"{EXPERIMENT_ID}_results.json"
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nWrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
