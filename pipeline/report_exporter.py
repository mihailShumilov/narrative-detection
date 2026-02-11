"""Report exporter for generating markdown and JSON outputs.

Stage H (partial): exports the fortnightly report as markdown and JSON.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pipeline.models import FortnightlyReport, RankedNarrative
from pipeline.logging import get_logger

logger = get_logger(__name__)


METHODOLOGY_TEXT = """
## Methodology

### Data Sources
This report aggregates signals from multiple data sources:

**Onchain (Solana Mainnet)**
- Solana RPC: Transaction activity, program deployments, supply metrics
- Tracked programs: Jupiter, Orca, Drift, Marginfi, Phoenix, Tensor, Jito, Token-2022, State Compression, Metaplex

**Offchain**
- GitHub: Repository creation, star velocity, commits, releases for Solana-related projects
- Twitter/X: KOL accounts and keyword monitoring (via API or Nitter RSS fallback)
- RSS/Blogs: Solana Foundation blog, Helius, Orca, Marginfi, Drift, Jito and other ecosystem blogs

### Detection Pipeline
1. **Ingestion**: Connectors fetch data within the analysis window
2. **Normalization**: Entity names are resolved to canonical forms; near-duplicate events are removed
3. **Clustering**: Entity co-occurrence analysis + TF-IDF text clustering identifies candidate narratives
4. **Scoring**: Each narrative receives a composite score based on velocity, breadth, cross-domain corroboration, novelty, and credibility, with spam and single-source penalties
5. **Explanation**: Evidence cards, "why now" analysis, and confidence scores are generated
6. **Ideas**: Build ideas are generated from a curated template library, grounded in the specific evidence

### Scoring Model
```
NarrativeScore = 0.25*Velocity + 0.20*Breadth + 0.20*CrossDomain + 0.20*Novelty + 0.15*Credibility
                 - 0.10*SpamPenalty - 0.15*SingleSourcePenalty
```

### Limitations
- Social media coverage depends on API access (X API requires bearer token; falls back to Nitter RSS)
- Onchain data via public RPC is limited to recent epochs; historical analysis requires archival nodes
- Entity extraction uses keyword matching, not NER — may miss novel projects without known keywords
- Narrative clustering may merge related but distinct trends when entity overlap is high
- Build ideas are generated from templates and may not capture all nuances of rapidly evolving narratives
"""


def export_markdown(report: FortnightlyReport, output_path: str | Path) -> str:
    """Export report as markdown."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append(f"# Solana Narrative Detection Report")
    lines.append(f"## Fortnightly Analysis: {report.window_start.strftime('%B %d, %Y')} — {report.window_end.strftime('%B %d, %Y')}")
    lines.append(f"")
    lines.append(f"**Generated**: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Run ID**: `{report.run_id}`")
    lines.append(f"**Baseline Period**: {report.baseline_start.strftime('%B %d, %Y')} — {report.window_start.strftime('%B %d, %Y')}")
    lines.append(f"")

    # Summary stats
    meta = report.metadata
    lines.append(f"### Run Summary")
    lines.append(f"- Total events ingested: {meta.get('total_events', 'N/A')}")
    lines.append(f"- Events after dedup: {meta.get('deduped_events', 'N/A')}")
    lines.append(f"- Candidate narratives: {meta.get('candidate_count', 'N/A')}")
    lines.append(f"- Ranked narratives: {len(report.narratives)}")
    lines.append(f"- Sources: {', '.join(meta.get('sources_used', []))}")
    lines.append(f"")

    # Narrative rankings overview
    lines.append(f"---")
    lines.append(f"## Top Narratives at a Glance")
    lines.append(f"")
    lines.append(f"| Rank | Narrative | Score | Confidence | Events |")
    lines.append(f"|------|-----------|-------|------------|--------|")
    for n in report.narratives:
        lines.append(
            f"| {n.rank} | {n.label} | {n.score.composite:.2f} | {n.confidence:.0%} | {len(n.evidence_cards)} |"
        )
    lines.append(f"")

    # Detailed narratives
    for n in report.narratives:
        lines.append(f"---")
        lines.append(f"## #{n.rank}: {n.label}")
        lines.append(f"**Composite Score**: {n.score.composite:.3f} | **Confidence**: {n.confidence:.0%}")
        lines.append(f"")

        # Explanation
        lines.append(f"### What & Why")
        lines.append(n.explanation)
        lines.append(f"")

        # Why Now
        lines.append(f"### Why Now")
        lines.append(n.why_now)
        lines.append(f"")

        # Score breakdown
        lines.append(f"### Score Breakdown")
        lines.append(f"| Feature | Raw | Contribution |")
        lines.append(f"|---------|-----|-------------|")
        for feature, contribution in n.score.feature_contributions.items():
            raw = getattr(n.score, feature.replace("_penalty", "_penalty"), contribution)
            lines.append(f"| {feature.replace('_', ' ').title()} | {raw:.3f} | {contribution:+.3f} |")
        lines.append(f"")

        # Confidence
        lines.append(f"### Confidence Assessment")
        lines.append(f"{n.confidence_reasoning}")
        lines.append(f"")

        # Evidence cards
        lines.append(f"### Evidence ({len(n.evidence_cards)} signals)")
        for i, ec in enumerate(n.evidence_cards, 1):
            lines.append(f"")
            lines.append(f"**{i}. {ec.summary[:120]}**")
            if ec.metric_highlight:
                lines.append(f"   - Metrics: {ec.metric_highlight}")
            if ec.event.url:
                lines.append(f"   - Link: [{ec.event.url[:60]}...]({ec.event.url})")
            lines.append(f"   - Source: {ec.event.source_subtype.value} | Relevance: {ec.relevance_score:.2f}")
            lines.append(f"   - Time: {ec.event.timestamp.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"")

        # Build ideas
        lines.append(f"### Build Ideas")
        for i, idea in enumerate(n.build_ideas, 1):
            lines.append(f"")
            lines.append(f"#### {i}. {idea.title}")
            lines.append(f"- **Category**: {idea.category}")
            lines.append(f"- **Problem**: {idea.problem_statement}")
            lines.append(f"- **Target User**: {idea.target_user}")
            lines.append(f"- **Why Solana**: {idea.why_solana}")
            lines.append(f"- **MVP Scope (1-2 weeks)**: {idea.mvp_scope}")
            lines.append(f"- **Risks & Unknowns**: {idea.risks_unknowns}")
            lines.append(f"- **Validation**: {idea.validation_approach}")
        lines.append(f"")

    # Methodology
    lines.append(f"---")
    lines.append(METHODOLOGY_TEXT)

    content = "\n".join(lines)
    output_path.write_text(content)
    logger.info("markdown_report_exported", path=str(output_path), size=len(content))
    return str(output_path)


def export_json(report: FortnightlyReport, output_path: str | Path) -> str:
    """Export report as JSON."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.to_json())
    logger.info("json_report_exported", path=str(output_path))
    return str(output_path)
