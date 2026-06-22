"""Tests for `scripts/scan_arxiv_topics.py` — arXiv 前沿主題掃描器.

聚焦 RSS parser（PRIMARY source）+ 研究軸關鍵詞比對 + XXE guard.
RSS 是本機可靠路徑（export API query 端點持續 429）；parser 正確性是
研究誠實底線（論文 ID/標題必須 byte-accurate，不可 hallucinate）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scan_arxiv_topics as s  # noqa: E402


_RSS_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:arxiv="http://arxiv.org/schemas/atom">
<channel>
<item>
  <title>Change-point estimation with copula-based Markov models</title>
  <link>https://arxiv.org/abs/2605.29541</link>
  <description>arXiv:2605.29541v1 Announce Type: new Abstract: We study copula-based Markov chains for nonlinear serial dependence.</description>
  <category>stat.ME</category>
  <category>q-fin.ST</category>
  <pubDate>Fri, 29 May 2026 00:00:00 -0400</pubDate>
  <arxiv:announce_type>new</arxiv:announce_type>
</item>
<item>
  <title>A deep learning GARCH realized volatility forecast</title>
  <link>https://arxiv.org/abs/2605.10000</link>
  <description>arXiv:2605.10000v1 Announce Type: cross Abstract: Autoencoder enhanced realized volatility.</description>
  <category>q-fin.ST</category>
  <pubDate>Fri, 29 May 2026 00:00:00 -0400</pubDate>
  <arxiv:announce_type>cross</arxiv:announce_type>
</item>
<item>
  <title>Some pure topology paper with no finance keywords</title>
  <link>https://arxiv.org/abs/2605.20000</link>
  <description>arXiv:2605.20000v1 Announce Type: new Abstract: Cohomology of fiber bundles.</description>
  <category>math.AT</category>
  <pubDate>Fri, 29 May 2026 00:00:00 -0400</pubDate>
  <arxiv:announce_type>new</arxiv:announce_type>
</item>
<item>
  <title>An updated GARCH paper replace</title>
  <link>https://arxiv.org/abs/2601.00001</link>
  <description>arXiv:2601.00001v3 Announce Type: replace Abstract: realized volatility update.</description>
  <category>q-fin.ST</category>
  <pubDate>Fri, 29 May 2026 00:00:00 -0400</pubDate>
  <arxiv:announce_type>replace</arxiv:announce_type>
</item>
</channel>
</rss>"""


def test_rss_parse_extracts_and_filters():
    out = s._parse_rss(_RSS_SAMPLE)
    ids = {c["arxiv_id"] for c in out}
    # copula(new) + GARCH(cross) 命中研究軸；topology 不命中；replace 預設略過
    assert "2605.29541" in ids
    assert "2605.10000" in ids
    assert "2605.20000" not in ids   # no axis keyword
    assert "2601.00001" not in ids   # replace skipped by default


def test_rss_id_strips_version():
    out = s._parse_rss(_RSS_SAMPLE)
    by_id = {c["arxiv_id"]: c for c in out}
    # link had v1 → must be stripped, pdf url uses bare id
    assert by_id["2605.29541"]["pdf_url"] == "https://arxiv.org/pdf/2605.29541"


def test_rss_abstract_stripped_of_prefix():
    out = s._parse_rss(_RSS_SAMPLE)
    copula = next(c for c in out if c["arxiv_id"] == "2605.29541")
    # "arXiv:... Announce Type: new Abstract:" prefix must be removed
    assert copula["abstract_snippet"].startswith("We study copula-based")
    assert "Announce Type" not in copula["abstract_snippet"]


def test_rss_include_replace_flag():
    out = s._parse_rss(_RSS_SAMPLE, include_replace=True)
    assert "2601.00001" in {c["arxiv_id"] for c in out}


def test_match_axis_keywords():
    assert s._match_axis("copula dependence", "") == "面向_copula"
    assert s._match_axis("realized volatility forecast", "") == "面向A_波動率預測"
    assert s._match_axis("random topology", "no finance here") is None


def test_xxe_guard_refuses_dtd():
    bad = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "boom">]><rss/>'
    assert s._parse_rss(bad) == []


def test_axis_label_attached():
    out = s._parse_rss(_RSS_SAMPLE)
    copula = next(c for c in out if c["arxiv_id"] == "2605.29541")
    assert copula["matched_axis"] == "面向_copula"
    assert copula["announce_type"] == "new"


def test_write_staging_dedup_and_first_seen(tmp_path, monkeypatch):
    """staging 池：dedup by arxiv_id + 保留 first_seen + status=new。"""
    staging = tmp_path / "arxiv_candidates.json"
    monkeypatch.setattr(s, "STAGING", staging)

    r1 = {"scanned_at": "2026-05-29T06:00:00+00:00",
          "candidates": [{"arxiv_id": "2605.00001", "title": "A", "matched_axis": "面向_copula"},
                         {"arxiv_id": "2605.00002", "title": "B", "matched_axis": "前沿_rough_vol"}]}
    out1 = s.write_staging(r1)
    assert out1 == {"added": 2, "total": 2}

    # 第二次：1 篇重複（不應改 first_seen）+ 1 篇新
    r2 = {"scanned_at": "2026-06-05T06:00:00+00:00",
          "candidates": [{"arxiv_id": "2605.00001", "title": "A", "matched_axis": "面向_copula"},
                         {"arxiv_id": "2606.00003", "title": "C", "matched_axis": "面向A_波動率預測"}]}
    out2 = s.write_staging(r2)
    assert out2 == {"added": 1, "total": 3}

    import json as _json
    pool = _json.loads(staging.read_text(encoding="utf-8"))
    by_id = {c["arxiv_id"]: c for c in pool["candidates"]}
    assert by_id["2605.00001"]["first_seen"] == "2026-05-29T06:00:00+00:00"  # 保留首見
    assert by_id["2606.00003"]["first_seen"] == "2026-06-05T06:00:00+00:00"
    assert all(c["status"] == "new" for c in pool["candidates"])


def test_write_staging_warns_on_bad_existing_json(tmp_path, monkeypatch, capsys):
    staging = tmp_path / "arxiv_candidates.json"
    staging.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(s, "STAGING", staging)

    result = {
        "scanned_at": "2026-06-23T00:00:00+00:00",
        "candidates": [{"arxiv_id": "2606.10000", "title": "New", "matched_axis": "面向_copula"}],
    }

    assert s.write_staging(result) == {"added": 1, "total": 1}

    captured = capsys.readouterr()
    assert "[scan_arxiv] WARN staging read failed; treating as empty" in captured.err
    assert "JSONDecodeError" in captured.err


def test_write_staging_skips_bad_existing_candidates_but_keeps_valid(tmp_path, monkeypatch, capsys):
    staging = tmp_path / "arxiv_candidates.json"
    staging.write_text(
        json.dumps(
            {
                "candidates": [
                    {"title": "missing id"},
                    "not a candidate",
                    {
                        "arxiv_id": "2605.00001",
                        "title": "Old",
                        "matched_axis": "面向_copula",
                        "first_seen": "2026-05-29T06:00:00+00:00",
                        "status": "new",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(s, "STAGING", staging)

    result = {
        "scanned_at": "2026-06-23T00:00:00+00:00",
        "candidates": [{"arxiv_id": "2606.10000", "title": "New", "matched_axis": "面向A_波動率預測"}],
    }

    assert s.write_staging(result) == {"added": 1, "total": 2}

    captured = capsys.readouterr()
    assert "staging candidate missing arxiv_id; skipping" in captured.err
    assert "invalid staging candidate; skipping" in captured.err
    pool = json.loads(staging.read_text(encoding="utf-8"))
    by_id = {c["arxiv_id"]: c for c in pool["candidates"]}
    assert set(by_id) == {"2605.00001", "2606.10000"}
    assert by_id["2605.00001"]["first_seen"] == "2026-05-29T06:00:00+00:00"
