#!/usr/bin/env python3
"""
validate_citation_format.py
============================
Validate citation accuracy and formatting in academic finance papers.

Key checks:
- Hawkes (1971) vs Hamilton (1989) confusion
- GMM terminology (two-stage vs two-step)
- Jump-diffusion model citations
- Journal formatting compliance

Usage:
    python validate_citation_format.py --file paper.md
    python validate_citation_format.py --text "Some text with citations"

Author: Academic Finance Reviewer Skill
"""

import re
import warnings
from typing import List, Dict, Tuple
from dataclasses import dataclass


@dataclass
class CitationIssue:
    """Represents a citation issue found in text."""
    severity: str  # 'critical', 'warning', 'info'
    line_num: int
    context: str
    issue: str
    recommendation: str


class CitationValidator:
    """Validate citations in financial econometrics papers."""

    # Critical citation errors (these are factually wrong)
    CRITICAL_ERRORS = {
        'hawkes_hamilton_confusion': {
            'pattern': r'Hamilton\s*\(1989\).*(?:Hawkes|filter|intensity|self-exciting)',
            'issue': 'Hamilton (1989) is about Markov regime-switching, NOT Hawkes processes',
            'recommendation': 'Replace with: Hawkes (1971) or Daley & Vere-Jones (2003) for Hawkes filtering'
        },
        'hamilton_hawkes_reverse': {
            'pattern': r'Hawkes.*Hamilton\s*\(1989\)',
            'issue': 'Hamilton (1989) incorrectly cited for Hawkes process',
            'recommendation': 'Remove Hamilton (1989) reference in Hawkes context'
        }
    }

    # Correct citations for common topics
    CORRECT_CITATIONS = {
        'hawkes_original': {
            'patterns': [r'Hawkes\s+process', r'self-exciting', r'point process'],
            'required_citations': ['Hawkes (1971)', 'Hawkes and Oakes (1974)'],
            'optional_citations': ['Daley and Vere-Jones (2003)', 'Bowsher (2007)']
        },
        'hawkes_finance': {
            'patterns': [r'jump.*contagion', r'credit.*contagion', r'systemic.*risk'],
            'required_citations': ['Aït-Sahalia et al. (2015)', 'Aït-Sahalia, Cacho-Diaz, and Laeven (2015)'],
            'optional_citations': ['Errais et al. (2010)', 'Azizpour et al. (2018)']
        },
        'gmm_estimation': {
            'patterns': [r'GMM', r'generalized method of moments', r'moment conditions'],
            'required_citations': ['Hansen (1982)'],
            'optional_citations': ['Newey and West (1987)', 'Hall (2005)']
        },
        'newey_west': {
            'patterns': [r'Newey.*West', r'HAC', r'heteroskedasticity.*autocorrelation.*consistent'],
            'required_citations': ['Newey and West (1987)'],
            'optional_citations': []
        },
        'high_freq_data': {
            'patterns': [r'high.*frequency', r'intraday', r'microstructure.*noise'],
            'required_citations': [],
            'optional_citations': ['Aït-Sahalia and Jacod (2014)', 'Barndorff-Nielsen and Shephard (2004)']
        },
        'jump_detection': {
            'patterns': [r'jump.*detection', r'Lee.*Mykland', r'bipower.*variation'],
            'required_citations': [],
            'optional_citations': ['Lee and Mykland (2008)', 'Barndorff-Nielsen and Shephard (2006)']
        },
        'regime_switching': {
            'patterns': [r'regime.*switching', r'Markov.*switching', r'Hamilton.*filter'],
            'required_citations': ['Hamilton (1989)'],
            'optional_citations': ['Hamilton (1994)']
        }
    }

    # GMM terminology standards
    GMM_TERMINOLOGY = {
        'two_stage_gmm': {
            'correct': ['two-stage GMM', 'two stage GMM'],
            'means': 'Stage 1: diffusion params, Stage 2: jump params (different parameter sets)',
            'typical_usage': 'Hawkes jump-diffusion models'
        },
        'two_step_gmm': {
            'correct': ['two-step GMM', 'two step GMM'],
            'means': 'Step 1: identity weight, Step 2: optimal weight (same parameters)',
            'typical_usage': 'Standard GMM optimization'
        },
        'three_stage_gmm': {
            'correct': ['three-stage GMM', 'three stage GMM'],
            'means': 'Stage 1: diffusion, Stage 2: jump (identity W), Stage 3: jump (optimal W)',
            'typical_usage': 'Advanced Hawkes estimation with optimal weighting'
        }
    }

    def __init__(self):
        """Initialize citation validator."""
        self.issues = []

    def check_critical_errors(self, text: str, line_num: int = 0) -> List[CitationIssue]:
        """
        Check for critical citation errors.

        Parameters:
        -----------
        text : str
            Text to check
        line_num : int
            Line number in document

        Returns:
        --------
        issues : list of CitationIssue
        """
        issues = []

        for error_type, error_info in self.CRITICAL_ERRORS.items():
            pattern = error_info['pattern']
            matches = re.finditer(pattern, text, re.IGNORECASE)

            for match in matches:
                context = text[max(0, match.start()-50):min(len(text), match.end()+50)]
                issues.append(CitationIssue(
                    severity='critical',
                    line_num=line_num,
                    context=context,
                    issue=error_info['issue'],
                    recommendation=error_info['recommendation']
                ))

        return issues

    def check_missing_citations(self, text: str, line_num: int = 0) -> List[CitationIssue]:
        """
        Check for missing required citations.

        Parameters:
        -----------
        text : str
            Text to check
        line_num : int
            Line number in document

        Returns:
        --------
        issues : list of CitationIssue
        """
        issues = []

        for topic, citation_info in self.CORRECT_CITATIONS.items():
            # Check if topic is mentioned
            topic_mentioned = False
            for pattern in citation_info['patterns']:
                if re.search(pattern, text, re.IGNORECASE):
                    topic_mentioned = True
                    break

            if not topic_mentioned:
                continue

            # Check if required citations are present
            for required_cit in citation_info['required_citations']:
                # Flexible citation matching (handles various formats)
                cit_pattern = re.escape(required_cit).replace(r'\ ', r'\s*')

                if not re.search(cit_pattern, text, re.IGNORECASE):
                    issues.append(CitationIssue(
                        severity='warning',
                        line_num=line_num,
                        context=text[:100],
                        issue=f'Topic "{topic}" mentioned but missing required citation: {required_cit}',
                        recommendation=f'Add citation: {required_cit}'
                    ))

        return issues

    def check_gmm_terminology(self, text: str, line_num: int = 0) -> List[CitationIssue]:
        """
        Check GMM terminology usage.

        Parameters:
        -----------
        text : str
            Text to check
        line_num : int
            Line number

        Returns:
        --------
        issues : list of CitationIssue
        """
        issues = []

        # Check for ambiguous usage
        if re.search(r'two[- ]stage.*two[- ]step|two[- ]step.*two[- ]stage', text, re.IGNORECASE):
            issues.append(CitationIssue(
                severity='warning',
                line_num=line_num,
                context=text[:100],
                issue='Mixing "two-stage" and "two-step" terminology - these have different meanings',
                recommendation='Use "two-stage" for different parameter sets, "two-step" for weight matrix updates'
            ))

        # Check if terminology matches context
        if re.search(r'diffusion.*jump', text, re.IGNORECASE):
            if re.search(r'two[- ]step\s+GMM', text, re.IGNORECASE) and not re.search(r'two[- ]stage', text, re.IGNORECASE):
                issues.append(CitationIssue(
                    severity='warning',
                    line_num=line_num,
                    context=text[:100],
                    issue='Using "two-step GMM" for diffusion+jump estimation - should be "two-stage"',
                    recommendation='Use "two-stage GMM" when estimating diffusion and jump parameters separately'
                ))

        return issues

    def validate_file(self, file_path: str) -> Dict:
        """
        Validate citations in entire file.

        Parameters:
        -----------
        file_path : str
            Path to file

        Returns:
        --------
        report : dict
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            return {'error': f'Failed to read file: {str(e)}'}

        all_issues = []

        for i, line in enumerate(lines):
            # Check critical errors
            all_issues.extend(self.check_critical_errors(line, i+1))

            # Check missing citations
            all_issues.extend(self.check_missing_citations(line, i+1))

            # Check GMM terminology
            all_issues.extend(self.check_gmm_terminology(line, i+1))

        # Categorize issues
        critical = [iss for iss in all_issues if iss.severity == 'critical']
        warnings_list = [iss for iss in all_issues if iss.severity == 'warning']
        info = [iss for iss in all_issues if iss.severity == 'info']

        report = {
            'file': file_path,
            'total_issues': len(all_issues),
            'critical': critical,
            'warnings': warnings_list,
            'info': info,
            'is_valid': len(critical) == 0
        }

        return report

    def validate_text(self, text: str) -> Dict:
        """
        Validate citations in text string.

        Parameters:
        -----------
        text : str
            Text to validate

        Returns:
        --------
        report : dict
        """
        all_issues = []

        # Split into lines for better reporting
        lines = text.split('\n')
        for i, line in enumerate(lines):
            all_issues.extend(self.check_critical_errors(line, i+1))
            all_issues.extend(self.check_missing_citations(line, i+1))
            all_issues.extend(self.check_gmm_terminology(line, i+1))

        critical = [iss for iss in all_issues if iss.severity == 'critical']
        warnings_list = [iss for iss in all_issues if iss.severity == 'warning']
        info = [iss for iss in all_issues if iss.severity == 'info']

        report = {
            'total_issues': len(all_issues),
            'critical': critical,
            'warnings': warnings_list,
            'info': info,
            'is_valid': len(critical) == 0
        }

        return report

    @staticmethod
    def print_report(report: Dict):
        """Print validation report."""

        print("\n" + "="*70)
        print("CITATION VALIDATION REPORT")
        print("="*70)

        if 'error' in report:
            print(f"\n❌ ERROR: {report['error']}")
            return

        if 'file' in report:
            print(f"\nFile: {report['file']}")

        print(f"\nTotal issues found: {report['total_issues']}")
        print(f"  Critical: {len(report['critical'])}")
        print(f"  Warnings: {len(report['warnings'])}")
        print(f"  Info: {len(report['info'])}")

        # Critical issues
        if report['critical']:
            print("\n" + "="*70)
            print("❌ CRITICAL ISSUES (Must Fix)")
            print("="*70)

            for i, issue in enumerate(report['critical'], 1):
                print(f"\n{i}. Line {issue.line_num}")
                print(f"   Context: ...{issue.context}...")
                print(f"   Issue: {issue.issue}")
                print(f"   Fix: {issue.recommendation}")

        # Warnings
        if report['warnings']:
            print("\n" + "="*70)
            print("⚠️  WARNINGS (Strongly Recommended)")
            print("="*70)

            for i, issue in enumerate(report['warnings'], 1):
                print(f"\n{i}. Line {issue.line_num}")
                print(f"   Issue: {issue.issue}")
                print(f"   Recommendation: {issue.recommendation}")

        # Overall
        print("\n" + "="*70)
        if report['is_valid']:
            if report['total_issues'] == 0:
                print("✅ NO ISSUES FOUND - Citations appear correct")
            else:
                print("✅ NO CRITICAL ERRORS - Only warnings/suggestions")
        else:
            print(f"❌ FOUND {len(report['critical'])} CRITICAL ERROR(S) - Must fix before submission")
        print("="*70 + "\n")


def example_usage():
    """Example usage with problematic text."""

    validator = CitationValidator()

    # Example 1: Hamilton/Hawkes confusion (CRITICAL)
    text1 = """
    We use the Hamilton (1989) filter to compute the jump intensity in the Hawkes process.
    The self-exciting property follows from Hamilton's framework.
    """

    print("="*70)
    print("EXAMPLE 1: Hamilton/Hawkes Confusion (Should detect CRITICAL error)")
    print("="*70)
    report1 = validator.validate_text(text1)
    validator.print_report(report1)

    # Example 2: Missing required citations
    text2 = """
    We employ GMM estimation to estimate the parameters of our model.
    The Hawkes process captures jump clustering in financial markets.
    """

    print("\n" + "="*70)
    print("EXAMPLE 2: Missing Required Citations")
    print("="*70)
    report2 = validator.validate_text(text2)
    validator.print_report(report2)

    # Example 3: GMM terminology confusion
    text3 = """
    We use a two-stage GMM procedure where the first step uses identity weight matrix
    and the second step uses optimal weight matrix. We also employ two-step GMM for robustness.
    """

    print("\n" + "="*70)
    print("EXAMPLE 3: GMM Terminology Issues")
    print("="*70)
    report3 = validator.validate_text(text3)
    validator.print_report(report3)

    # Example 4: Correct citations
    text4 = """
    We employ a two-stage GMM procedure following Aït-Sahalia et al. (2015).
    The Hawkes self-exciting process (Hawkes, 1971; Daley and Vere-Jones, 2003)
    captures jump contagion. We use the Newey and West (1987) HAC covariance matrix.
    """

    print("\n" + "="*70)
    print("EXAMPLE 4: Correct Citations (Should pass)")
    print("="*70)
    report4 = validator.validate_text(text4)
    validator.print_report(report4)


if __name__ == '__main__':
    example_usage()
