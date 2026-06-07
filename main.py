#!/usr/bin/env python3
"""
LegalPerigee — AI Fraud Investigation CLI

Usage:
    python main.py "find AI fraud cases involving financial advisors"
    python main.py --verbose "FTC enforcement actions against AI chatbot companies"
    python main.py --output report.json "SEC cases involving AI-generated investment advice"
    python main.py --format markdown "AI deepfake fraud cases"

Requires:
    ANTHROPIC_API_KEY environment variable
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic

from agents.orchestrator import run_investigation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="legalperigee",
        description="AI Fraud Investigation System — uncover documented AI-driven deceptive practices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "AI fraud cases involving financial advisors"
  python main.py --verbose "FTC enforcement actions against AI chatbot scams"
  python main.py --format markdown "SEC cases involving algorithmic trading fraud"
  python main.py --output report.json "CFPB AI lending discrimination cases"
        """,
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Research query (if omitted, enter interactively)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print agent progress to stderr",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "markdown", "both"],
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Write output to file instead of stdout (extension determines format)",
    )
    return parser


def print_banner() -> None:
    print("""
╔═══════════════════════════════════════════════════════════════╗
║          L E G A L P E R I G E E                             ║
║          AI Fraud Investigation System                        ║
║          Ethical · Analytical · Evidence-Based                ║
╚═══════════════════════════════════════════════════════════════╝
""", file=sys.stderr)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        print("Copy .env.example to .env and add your key.", file=sys.stderr)
        return 1

    print_banner()

    # Get query
    query = args.query
    if not query:
        print("Enter your research query (press Enter twice to submit):", file=sys.stderr)
        lines = []
        try:
            while True:
                line = input()
                if not line and lines:
                    break
                lines.append(line)
        except EOFError:
            pass
        query = " ".join(lines).strip()

    if not query:
        print("Error: No query provided.", file=sys.stderr)
        return 1

    print(f"\n🔍 Investigating: {query}\n", file=sys.stderr)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        report = run_investigation(query=query, verbose=args.verbose, client=client)
    except anthropic.AuthenticationError:
        print("Error: Invalid ANTHROPIC_API_KEY.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInvestigation interrupted.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error during investigation: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # Determine output destination
    output_file = args.output
    fmt = args.format

    # Auto-detect format from file extension
    if output_file:
        ext = Path(output_file).suffix.lower()
        if ext == ".json":
            fmt = "json"
        elif ext in (".md", ".markdown"):
            fmt = "markdown"

    def write_output(content: str, dest: str | None) -> None:
        if dest:
            Path(dest).write_text(content, encoding="utf-8")
            print(f"✅ Report written to: {dest}", file=sys.stderr)
        else:
            print(content)

    if fmt == "json":
        output = report.model_dump_json(indent=2)
        write_output(output, output_file)
    elif fmt == "markdown":
        output = report.to_markdown()
        write_output(output, output_file)
    else:
        # Both: if file output, write JSON; also print markdown to stdout
        if output_file:
            json_path = output_file
            md_path = str(Path(output_file).with_suffix(".md"))
            Path(json_path).write_text(report.model_dump_json(indent=2), encoding="utf-8")
            Path(md_path).write_text(report.to_markdown(), encoding="utf-8")
            print(f"✅ JSON report: {json_path}", file=sys.stderr)
            print(f"✅ Markdown report: {md_path}", file=sys.stderr)
        else:
            print(report.to_markdown())
            print("\n" + "─" * 60 + "\n")
            print("JSON output:")
            print(report.model_dump_json(indent=2))

    print(
        f"\n📊 Summary: {report.total_cases_found} cases found "
        f"({report.high_severity_count} high severity)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
