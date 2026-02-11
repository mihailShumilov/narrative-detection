"""Main entry point for Solana Narrative Detection pipeline.

Usage:
    python main.py              # Run pipeline with default config
    python main.py --snapshot   # Run using bundled snapshot data
    python main.py --dashboard  # Launch Streamlit dashboard
"""

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline.runner import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Solana Narrative Detection - Fortnightly Signal Analysis"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config YAML (default: config/default.yaml)",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Use bundled snapshot data instead of live fetching",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch the Streamlit dashboard",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Analysis end date (YYYY-MM-DD). Defaults to today.",
    )

    args = parser.parse_args()

    if args.dashboard:
        print("Launching Streamlit dashboard...")
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py",
             "--server.port", "8501", "--server.address", "0.0.0.0"],
            cwd=str(Path(__file__).parent),
        )
        return

    # Parse end date
    window_end = None
    if args.date:
        window_end = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    print("=" * 60)
    print("  Solana Narrative Detection Pipeline")
    print("=" * 60)
    print()

    report = run_pipeline(
        config_path=args.config,
        window_end=window_end,
        use_snapshot=args.snapshot,
    )

    print()
    print("=" * 60)
    print(f"  Pipeline Complete - Run ID: {report.run_id}")
    print(f"  Window: {report.window_start.strftime('%Y-%m-%d')} to {report.window_end.strftime('%Y-%m-%d')}")
    print(f"  Narratives Detected: {len(report.narratives)}")
    print("=" * 60)
    print()

    for n in report.narratives:
        confidence_bar = "█" * int(n.confidence * 10) + "░" * (10 - int(n.confidence * 10))
        print(f"  #{n.rank}: {n.label}")
        print(f"       Score: {n.score.composite:.3f}  Confidence: [{confidence_bar}] {n.confidence:.0%}")
        print(f"       Entities: {', '.join(n.entities[:5])}")
        print(f"       Evidence: {len(n.evidence_cards)} signals | Ideas: {len(n.build_ideas)}")
        print()

    print(f"Reports exported to: reports/")
    print(f"  - Markdown: reports/report_{report.window_end.strftime('%Y%m%d')}.md")
    print(f"  - JSON:     reports/report_{report.window_end.strftime('%Y%m%d')}.json")


if __name__ == "__main__":
    main()
