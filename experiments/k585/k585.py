"""
K585: Session Meta-Analysis — Quantifying K526-K583 Contributions to Three Papers

READ-ONLY research synthesis. No computation — cross-references 50 knowledge
entries (K526-K583) against current paper content to identify which findings
should be incorporated into the three papers.

Method: Manual cross-referencing of knowledge base entries against paper LaTeX files.
Data source: storage/memory/knowledge.json + paper/*/body.tex or main.tex
"""

import json
from pathlib import Path

def main():
    results_path = Path(__file__).parent / "k585_paper_contribution_analysis.json"

    if results_path.exists():
        with open(results_path) as f:
            results = json.load(f)

        print("=" * 70)
        print("K585: Session Meta-Analysis — Paper Contribution Mapping")
        print("=" * 70)

        s = results["summary"]
        print(f"\nTotal findings relevant to papers: {s['total_findings_relevant_to_papers']}")
        print(f"  Strengthening existing claims: {s['findings_strengthening_existing']}")
        print(f"  Adding new content: {s['findings_adding_new_content']}")
        print(f"  Requiring caveats: {s['findings_requiring_caveats']}")
        print(f"  Null results confirming claims: {s['null_results_confirming_claims']}")

        print(f"\nMost impactful for Paper 1 (Leverage Direction):")
        print(f"  {s['most_impactful_for_paper_1']}")
        print(f"\nMost impactful for Paper 2 (Taiwan VT):")
        print(f"  {s['most_impactful_for_paper_2']}")
        print(f"\nMost impactful for Paper 3 (VT ≠ Trend):")
        print(f"  {s['most_impactful_for_paper_3']}")

        print("\n" + "=" * 70)
        print("HIGHEST PRIORITY ADDITIONS")
        print("=" * 70)
        for item in results["priority_ranking"]["highest_priority_additions"]:
            print(f"  • {item}")

        print("\nMEDIUM PRIORITY ADDITIONS")
        for item in results["priority_ranking"]["medium_priority_additions"]:
            print(f"  • {item}")

        print("\n" + "=" * 70)
        print("CROSS-PAPER THEMES")
        print("=" * 70)
        for key, theme in results["cross_paper_themes"].items():
            print(f"\n{key}: {theme['description'][:100]}...")
            print(f"  Papers: {', '.join(theme['papers_affected'])}")
    else:
        print("Results file not found. Run the analysis first.")

if __name__ == "__main__":
    main()
