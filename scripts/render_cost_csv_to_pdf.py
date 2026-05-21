from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd


ACCENT = "1F4E79"
ACCENT_LIGHT = "EAF2FB"
GRID = "D7E3F4"
TEXT_MUTED = "5B6573"


@dataclass
class Summary:
    start_date: str
    end_date: str
    total_rows: int
    billed_days: int
    zero_days: int
    total_amount: Decimal
    project_name: str
    organization_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a cost CSV as a styled PDF.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("pdf_path", type=Path)
    return parser.parse_args()


def format_decimal(value: Decimal) -> str:
    if not value.is_finite():
        return "0.00"
    if value == 0:
        return "0.00"
    if value >= Decimal("1"):
        return f"{value.quantize(Decimal('0.01')):,.2f}"
    if value >= Decimal("0.01"):
        return f"{value.quantize(Decimal('0.0001')):,.4f}"
    return f"{value.normalize():f}".rstrip("0").rstrip(".") or "0"


def parse_amount(raw: object) -> Decimal:
    if raw is None:
        return Decimal("0")
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return Decimal("0")
    try:
        value = Decimal(text)
        return value if value.is_finite() else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def escape_latex(value: object) -> str:
    text = "" if value is None else str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def build_dataframe(csv_path: Path) -> tuple[pd.DataFrame, Summary]:
    df = pd.read_csv(csv_path)
    df["display_date"] = pd.to_datetime(df["start_time_iso"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["amount_decimal"] = df["amount_value"].apply(parse_amount)
    original_rows = len(df)
    df = df[df["amount_decimal"] > 0].copy()
    df["amount_usd"] = df["amount_decimal"].apply(format_decimal)
    df["currency_display"] = df["amount_currency"].fillna("").str.upper().replace("", "USD")
    df["status"] = "Charged"
    df["project_name"] = df["project_name"].fillna("").replace("", "Default project")
    df["organization_name"] = df["organization_name"].fillna("").replace("", "N/A")

    display_df = df[[
        "display_date",
        "amount_usd",
        "currency_display",
        "status",
        "project_name",
        "organization_name",
    ]].copy()
    display_df.columns = ["Date", "Amount (USD)", "Currency", "Status", "Project", "Organization"]

    valid_dates = pd.to_datetime(df["start_time_iso"], errors="coerce").dropna()
    summary = Summary(
        start_date=valid_dates.min().strftime("%Y-%m-%d") if not valid_dates.empty else "",
        end_date=valid_dates.max().strftime("%Y-%m-%d") if not valid_dates.empty else "",
        total_rows=len(display_df),
        billed_days=int((df["amount_decimal"] > 0).sum()),
        zero_days=original_rows - len(df),
        total_amount=df["amount_decimal"].sum(),
        project_name=str(display_df["Project"].mode().iloc[0]) if not display_df.empty else "",
        organization_name=str(display_df["Organization"].mode().iloc[0]) if not display_df.empty else "",
    )
    return display_df, summary


def build_table_rows(display_df: pd.DataFrame) -> str:
    lines: list[str] = []
    for _, row in display_df.iterrows():
        status_color = ACCENT if row["Status"] == "Charged" else TEXT_MUTED
        line = (
            f"{escape_latex(row['Date'])} & "
            f"\\raggedleft\\arraybackslash {escape_latex(row['Amount (USD)'])} & "
            f"{escape_latex(row['Currency'])} & "
            f"\\textcolor[HTML]{{{status_color}}}{{{escape_latex(row['Status'])}}} & "
            f"{escape_latex(row['Project'])} & "
            f"{escape_latex(row['Organization'])} \\\\"
        )
        lines.append(line)
    return "\n".join(lines)


def build_tex(display_df: pd.DataFrame, summary: Summary, source_name: str) -> str:
    table_rows = build_table_rows(display_df)
    total_amount = format_decimal(summary.total_amount)
    return rf"""
\documentclass[11pt]{{article}}
\usepackage[margin=0.7in]{{geometry}}
\usepackage{{fontspec}}
\usepackage{{xeCJK}}
\usepackage[table]{{xcolor}}
\usepackage{{booktabs}}
\usepackage{{longtable}}
\usepackage{{array}}
\usepackage{{tabularx}}
\usepackage{{colortbl}}
\usepackage{{ragged2e}}
\usepackage{{fancyhdr}}
\usepackage{{lastpage}}
\usepackage{{titlesec}}
\setmainfont{{Arial Unicode MS}}
\setCJKmainfont{{Heiti TC}}
\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{\textcolor[HTML]{{{ACCENT}}}{{Cost Report}}}}
\fancyhead[R]{{\textcolor[HTML]{{{TEXT_MUTED}}}{{{escape_latex(summary.start_date)} to {escape_latex(summary.end_date)}}}}}
\fancyfoot[C]{{\textcolor[HTML]{{{TEXT_MUTED}}}{{Page \thepage\ of \pageref{{LastPage}}}}}}
\setlength{{\headheight}}{{15pt}}
\definecolor{{Accent}}{{HTML}}{{{ACCENT}}}
\definecolor{{AccentLight}}{{HTML}}{{{ACCENT_LIGHT}}}
\definecolor{{Grid}}{{HTML}}{{{GRID}}}
\definecolor{{Muted}}{{HTML}}{{{TEXT_MUTED}}}
\arrayrulecolor{{Grid}}
\renewcommand{{\arraystretch}}{{1.35}}
\begin{{document}}
\begin{{center}}
{{\fontsize{{22}}{{26}}\selectfont\bfseries\textcolor{{Accent}}{{OpenAI Usage Cost Report}}}}\\[6pt]
{{\large\textcolor{{Muted}}{{Styled PDF generated from CSV source}}}}\\[10pt]
{{\small\textcolor{{Muted}}{{Source file: {escape_latex(source_name)}}}}}
\end{{center}}

\vspace{{0.6em}}
\noindent
\colorbox{{AccentLight}}{{%
\parbox{{\dimexpr\textwidth-2\fboxsep}}{{%
\vspace{{0.6em}}
\begin{{tabularx}}{{\textwidth}}{{@{{}}X X X X@{{}}}}
\textbf{{Period}} & \textbf{{Total Cost}} & \textbf{{Charged Days}} & \textbf{{No-charge Days}} \\
{escape_latex(summary.start_date)} to {escape_latex(summary.end_date)} & USD {escape_latex(total_amount)} & {summary.billed_days} & {summary.zero_days}
\end{{tabularx}}
\vspace{{0.6em}}

\vspace{{0.3em}}
\begin{{tabularx}}{{\textwidth}}{{@{{}}X X@{{}}}}
\textbf{{Project}}: {escape_latex(summary.project_name)} & \textbf{{Organization}}: {escape_latex(summary.organization_name)}
\end{{tabularx}}
}}}}

\vspace{{1em}}
\rowcolors{{3}}{{white}}{{AccentLight!45}}
\begin{{longtable}}{{>{{\RaggedRight\arraybackslash}}p{{1.55cm}} >{{\RaggedLeft\arraybackslash}}p{{2.0cm}} >{{\centering\arraybackslash}}p{{1.6cm}} >{{\centering\arraybackslash}}p{{2.0cm}} >{{\RaggedRight\arraybackslash}}p{{3.2cm}} >{{\RaggedRight\arraybackslash}}p{{4.0cm}}}}
\rowcolor{{Accent}}
\color{{white}}\textbf{{Date}} &
\color{{white}}\textbf{{Amount}} &
\color{{white}}\textbf{{Curr.}} &
\color{{white}}\textbf{{Status}} &
\color{{white}}\textbf{{Project}} &
\color{{white}}\textbf{{Organization}} \\
\endfirsthead
\rowcolor{{Accent}}
\color{{white}}\textbf{{Date}} &
\color{{white}}\textbf{{Amount}} &
\color{{white}}\textbf{{Curr.}} &
\color{{white}}\textbf{{Status}} &
\color{{white}}\textbf{{Project}} &
\color{{white}}\textbf{{Organization}} \\
\endhead
{table_rows}
\end{{longtable}}
\end{{document}}
"""


def run_xelatex(tex_path: Path, output_dir: Path) -> Path:
    command = [
        "xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={output_dir}",
        str(tex_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    pdf_path = output_dir / f"{tex_path.stem}.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"Expected PDF not found: {pdf_path}")
    return pdf_path


def main() -> None:
    args = parse_args()
    csv_path = args.csv_path.expanduser().resolve()
    pdf_path = args.pdf_path.expanduser().resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    display_df, summary = build_dataframe(csv_path)
    tex = build_tex(display_df, summary, csv_path.name)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        tex_path = tmp_path / "cost_report.tex"
        tex_path.write_text(tex, encoding="utf-8")
        built_pdf = run_xelatex(tex_path, tmp_path)
        shutil.copy2(built_pdf, pdf_path)

    print(pdf_path)


if __name__ == "__main__":
    main()
