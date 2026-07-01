#!/usr/bin/env python3
"""Submission-compliance gate for paper LaTeX sources.

Boss directives (2026-07-01): a manuscript headed for arXiv / a journal must read
as a standalone, *unpublished*, single-author academic work:
  - author solely "Yi-Hao Lai" (no co-authors, no "\\and ... Research System")
  - zero platform / tooling disclosure (VolPred, OpenAI, Codex, Claude, Anthropic, GPT, LLM)
  - zero internal experiment-registry identifiers (K123 / K1234 tags)
  - no fabricated acknowledgments (seminar participants / anonymous reviewers — neither
    happened for an unpublished manuscript; claiming them is fabrication)
  - no self-referential "our research program" platform phrasing

Scope boundary (this is the whole point of the gate):
  - We scan ONLY the *submission set*: main.tex, every file it \\input/\\include's
    (the compile closure), plus cover_letter.tex and supplementary*.tex.
  - Internal provenance is intentionally EXCLUDED and must NOT be scrubbed: version
    archives (main_v*, body_v*, *_backup, *_predecessor) and revision-diff documents
    (*_diff.tex, review_history/, reviews/). Those honestly record that the AI system
    did the work; falsifying them would be dishonest. They simply must not ship in the
    replication package.

Usage:
  python scripts/check_paper_compliance.py                 # all papers, summary
  python scripts/check_paper_compliance.py leverage-direction   # one paper, verbose
  python scripts/check_paper_compliance.py --json          # machine-readable
Exit code: 0 = all scanned submission files clean; 1 = at least one violation.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

PAPER_ROOT = Path(__file__).resolve().parent.parent / "paper"

# (label, compiled regex, explanation)
RULES = [
    ("platform_or_ai", re.compile(r"\bVolPred\b|\bOpenAI\b|\bCodex\b|\bClaude\b|\bAnthropic\b|\bGPT-?\d|\bLLM\b|language model|AI assistant|code-reviewer", re.I),
     "platform/AI-tool disclosure"),
    ("co_author", re.compile(r"\\and\s"),
     "possible co-author (\\and) — author must be Yi-Hao Lai alone"),
    ("fabricated_ack", re.compile(r"anonymous reviewer|anonymous referee|seminar participant|conference participant|workshop participant", re.I),
     "fabricated acknowledgment (no seminar/review occurred for an unpublished MS)"),
    ("self_ref_program", re.compile(r"our (own )?research program", re.I),
     "self-referential internal-platform phrasing"),
    ("k_id", re.compile(r"\bK\d{3,4}[a-z]?\b"),
     "internal experiment-registry identifier (K-id)"),
]

# files that are internal provenance / archives — never part of the submission set
EXCLUDE_RE = re.compile(
    r"(_v\d|_backup|_predecessor|_diff|_pre_|_pre[_.]|review_report|review_v)", re.I)
EXCLUDE_DIRS = {"review_history", "reviews", "reproducibility_audit", "experiments", "data"}


# An entry-point candidate is a *clearly-old* version we must NOT treat as the
# current submission manuscript. NOTE: _v3+ are kept as candidate entries because
# papers diverge in convention (leverage-direction → main.tex is canonical;
# vt-trend-following / vix-sufficiency → main_v3 / main_v4 \input the live body).
# 2026-07-01 bug: the old gate hard-scanned only main.tex and excluded `_v\d`, so
# vt-trend-following's real manuscript (main_v3 → body_v3, 72 visible K-ids) was
# never scanned and returned a false CLEAN. Over-report across entries beats a
# false CLEAN; a human confirms which entry actually ships.
_OLD_ENTRY_RE = re.compile(r"(_v1|_v2|_backup|_predecessor|_pre[_.]|_diff|review_)", re.I)


def submission_files(paper_dir: Path) -> list[Path]:
    r"""Resolve the compile closure of every current manuscript entry point
    (main.tex + main_vN.tex for N>=3) plus standalone cover/supplement files.
    \input'd files are ALWAYS scanned regardless of name — they are part of the
    manuscript even when named body_v3.tex."""
    files: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path):
        if p.exists() and p not in seen:
            seen.add(p)
            files.append(p)

    # current manuscript entry points
    entries = []
    for cand in sorted(paper_dir.glob("main*.tex")):
        if _OLD_ENTRY_RE.search(cand.name):
            continue
        try:
            head = cand.read_text(encoding="utf-8", errors="replace")[:3000]
        except OSError as e:
            from sys import stderr
            print(f"warn: cannot read {cand}: {e}", file=stderr)  # silent-ok would hide a real read failure
            continue
        if "\\documentclass" in head:
            entries.append(cand)

    # 2026-07-01 fix: some papers compile directly from a bare body.tex with no
    # main.tex at all (e.g. eav-universal-magnitude). The main*.tex glob above
    # then finds zero entries, so the paper was silently never scanned by the
    # default all-papers run — a compliance-scrub commit could fix the text and
    # no CI gate would ever re-verify it afterwards (exactly how a stale
    # "VolPred Research System" acknowledgment survived in the live PDF after
    # the source .tex had already been scrubbed). Treat a bare body.tex (not
    # body_vN.tex — those are archives, already excluded by _OLD_ENTRY_RE the
    # same way main_vN.tex is) as an entry point when it is itself a
    # \documentclass root and no main*.tex claimed the role.
    if not entries:
        body_entry = paper_dir / "body.tex"
        if body_entry.exists() and not _OLD_ENTRY_RE.search(body_entry.name):
            try:
                head = body_entry.read_text(encoding="utf-8", errors="replace")[:3000]
            except OSError as e:
                from sys import stderr
                print(f"warn: cannot read {body_entry}: {e}", file=stderr)  # silent-ok would hide a real read failure
                head = ""
            if "\\documentclass" in head:
                entries.append(body_entry)

    for entry in entries:
        add(entry)
        txt = entry.read_text(encoding="utf-8", errors="replace")
        # strip comment lines before resolving \input so commented-out inputs are ignored
        for m in re.finditer(r"^[^%\n]*\\(?:input|include)\{([^}]+)\}", txt, re.M):
            name = m.group(1).strip()
            cand = paper_dir / (name if name.endswith(".tex") else name + ".tex")
            add(cand)  # always scan \input'd body, even body_v3.tex

    # standalone submission documents not \input by a main file
    for pat in ("cover_letter.tex", "supplementary.tex", "supplementary_content.tex"):
        add(paper_dir / pat)
    return files


def scan_file(path: Path) -> list[dict]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        # ignore pure-comment lines (won't render) for non-co-author rules,
        # but still flag platform/AI even in comments inside submission files
        stripped = line.lstrip()
        is_comment = stripped.startswith("%")
        for label, rx, why in RULES:
            for mm in rx.finditer(line):
                # co_author / k_id / fabricated / self_ref in a comment line are not shipped
                if is_comment and label != "platform_or_ai":
                    continue
                out.append({"line": i, "rule": label, "why": why,
                            "match": mm.group(0), "text": line.strip()[:140]})
    return out


def check_paper(paper_dir: Path) -> dict:
    files = submission_files(paper_dir)
    findings = {}
    for f in files:
        hits = scan_file(f)
        if hits:
            findings[f.name] = hits
    return {"paper": paper_dir.name,
            "scanned": [f.name for f in files],
            "clean": not findings,
            "findings": findings}


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    args = [a for a in argv if not a.startswith("--")]
    if args:
        dirs = [PAPER_ROOT / args[0]]
    else:
        # 2026-07-01 fix: also pick up body.tex-only papers (no main.tex at all,
        # e.g. eav-universal-magnitude) — see submission_files() for why the old
        # main.tex-only filter silently dropped these from the default scan.
        dirs = sorted(d for d in PAPER_ROOT.iterdir()
                      if d.is_dir() and d.name not in EXCLUDE_DIRS
                      and ((d / "main.tex").exists() or (d / "body.tex").exists()))

    results = [check_paper(d) for d in dirs if d.exists()]
    any_dirty = any(not r["clean"] for r in results)

    if as_json:
        print(json.dumps({"clean": not any_dirty, "papers": results}, ensure_ascii=False, indent=2))
        return 1 if any_dirty else 0

    for r in results:
        status = "✓ CLEAN" if r["clean"] else "✗ VIOLATIONS"
        print(f"\n[{status}] {r['paper']}  (scanned: {', '.join(r['scanned']) or 'none'})")
        for fname, hits in r["findings"].items():
            print(f"  {fname}:")
            for h in hits:
                print(f"    L{h['line']} [{h['rule']}] '{h['match']}'  — {h['text']}")
    total_v = sum(len(h) for r in results for h in r["findings"].values())
    print(f"\n{'='*60}")
    print(f"Papers scanned: {len(results)}  |  clean: {sum(r['clean'] for r in results)}  |  "
          f"with violations: {sum(not r['clean'] for r in results)}  |  total findings: {total_v}")
    return 1 if any_dirty else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
