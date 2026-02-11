"""Main pipeline orchestrator.

Runs the full narrative detection pipeline from ingestion to report generation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pipeline.config import load_config
from pipeline.logging import setup_logging, get_logger
from pipeline.models import (
    FortnightlyReport,
    RankedNarrative,
)
from pipeline.normalizer import EventNormalizer
from pipeline.clustering import NarrativeClusterer
from pipeline.scoring import NarrativeScorer
from pipeline.explainer import NarrativeExplainer
from pipeline.idea_generator import IdeaGenerator
from pipeline.report_exporter import export_markdown, export_json, METHODOLOGY_TEXT

from connectors.solana_onchain import SolanaOnchainConnector
from connectors.github_connector import GitHubConnector
from connectors.rss_connector import RSSConnector
from connectors.twitter_connector import TwitterConnector

logger = None


def run_pipeline(
    config_path: str | Path | None = None,
    window_end: datetime | None = None,
    use_snapshot: bool = False,
) -> FortnightlyReport:
    """Run the full narrative detection pipeline.

    Args:
        config_path: Path to config YAML. Uses default if None.
        window_end: End of analysis window. Defaults to now.
        use_snapshot: If True, use bundled snapshot data instead of live fetch.

    Returns:
        FortnightlyReport with ranked narratives, evidence, and build ideas.
    """
    config = load_config(config_path)
    setup_logging(config.get("logging", {}).get("level", "INFO"))
    global logger
    logger = get_logger("pipeline.runner")

    # Define analysis windows
    if window_end is None:
        window_end = datetime.now(timezone.utc)
    window_days = config.get("analysis", {}).get("window_days", 14)
    baseline_days = config.get("analysis", {}).get("baseline_days", 56)
    window_start = window_end - timedelta(days=window_days)
    baseline_start = window_start - timedelta(days=baseline_days)

    run_id = f"run_{window_end.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    logger.info(
        "pipeline_start",
        run_id=run_id,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        baseline_start=baseline_start.isoformat(),
    )

    # ====== Stage A: Ingestion ======
    logger.info("stage_ingestion_start")
    all_events = []
    sources_used = []
    errors = []

    connectors = [
        ("solana_onchain", SolanaOnchainConnector(config, cache_enabled=True)),
        ("github", GitHubConnector(config, cache_enabled=True)),
        ("rss_blogs", RSSConnector(config, cache_enabled=True)),
        ("twitter", TwitterConnector(config, cache_enabled=True)),
    ]

    for name, connector in connectors:
        try:
            events = connector.fetch(window_start, window_end)
            all_events.extend(events)
            sources_used.append(name)
            logger.info("connector_complete", connector=name, events=len(events))
        except Exception as e:
            errors.append(f"{name}: {str(e)}")
            logger.error("connector_failed", connector=name, error=str(e))
        finally:
            connector.close()

    # Always merge snapshot data for richer narratives in demo mode
    snapshot_events = _load_all_snapshots(window_start, window_end)
    if snapshot_events:
        all_events.extend(snapshot_events)
        if "snapshot_data" not in sources_used:
            sources_used.append("snapshot_data")
        logger.info("snapshot_data_merged", snapshot_events=len(snapshot_events))

    total_events = len(all_events)
    logger.info("stage_ingestion_complete", total_events=total_events, sources=sources_used)

    if not all_events:
        logger.warning("no_events_fetched", reason="No data from any source")
        sources_used = ["none"]

    # ====== Stage B+C: Normalization + Dedup ======
    logger.info("stage_normalization_start")
    normalizer = EventNormalizer(config)
    events = normalizer.process(all_events)
    deduped_count = len(events)
    logger.info("stage_normalization_complete", original=total_events, deduped=deduped_count)

    # ====== Stage D: Narrative Clustering ======
    logger.info("stage_clustering_start")
    clusterer = NarrativeClusterer(config)
    candidates = clusterer.generate_candidates(events)
    logger.info("stage_clustering_complete", candidates=len(candidates))

    # ====== Stage E: Scoring & Ranking ======
    logger.info("stage_scoring_start")
    scorer = NarrativeScorer(config)
    ranked = scorer.rank_narratives(candidates, window_start, window_end)
    max_narratives = config.get("analysis", {}).get("max_narratives", 10)
    ranked = ranked[:max_narratives]
    logger.info("stage_scoring_complete", ranked=len(ranked))

    # ====== Stage F: Explainability ======
    logger.info("stage_explanation_start")
    explainer = NarrativeExplainer(config)
    ranked_narratives = []

    for rank, (candidate, score) in enumerate(ranked, 1):
        explanation = explainer.build_explanation(candidate, score)
        why_now = explainer.build_why_now(candidate, score, window_start, window_end)
        evidence_cards = explainer.build_evidence_cards(candidate, score)
        confidence, confidence_reasoning = explainer.compute_confidence(candidate, score)

        # ====== Stage G: Idea Generation ======
        idea_gen = IdeaGenerator(config)
        build_ideas = idea_gen.generate_ideas(candidate, score, evidence_cards)

        # Build timeline data for charts
        timeline_data = _build_timeline(candidate.events, window_start, window_end)

        ranked_narrative = RankedNarrative(
            rank=rank,
            narrative_id=candidate.id,
            label=candidate.label,
            explanation=explanation,
            why_now=why_now,
            score=score,
            confidence=confidence,
            confidence_reasoning=confidence_reasoning,
            evidence_cards=evidence_cards,
            build_ideas=build_ideas,
            entities=candidate.entities,
            timeline_data=timeline_data,
        )
        ranked_narratives.append(ranked_narrative)

    logger.info("stage_explanation_complete", narratives=len(ranked_narratives))

    # ====== Stage H: Report Assembly ======
    report = FortnightlyReport(
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        baseline_start=baseline_start,
        generated_at=datetime.now(timezone.utc),
        narratives=ranked_narratives,
        methodology=METHODOLOGY_TEXT,
        metadata={
            "total_events": total_events,
            "deduped_events": deduped_count,
            "candidate_count": len(candidates),
            "sources_used": sources_used,
            "errors": errors,
            "config_window_days": window_days,
            "config_baseline_days": baseline_days,
        },
    )

    # Export reports
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    date_str = window_end.strftime("%Y%m%d")
    md_path = export_markdown(report, reports_dir / f"report_{date_str}.md")
    json_path = export_json(report, reports_dir / f"report_{date_str}.json")
    logger.info("reports_exported", markdown=md_path, json=json_path)

    logger.info("pipeline_complete", run_id=run_id, narratives=len(ranked_narratives))
    return report


def _build_timeline(events, window_start, window_end):
    """Build daily event count timeline for chart data."""
    from collections import Counter
    daily = Counter()
    for event in events:
        day = event.timestamp.strftime("%Y-%m-%d")
        daily[day] += 1

    # Fill gaps
    current = window_start
    timeline = []
    while current <= window_end:
        day_str = current.strftime("%Y-%m-%d")
        timeline.append({"date": day_str, "count": daily.get(day_str, 0)})
        current += timedelta(days=1)

    return timeline


def _load_all_snapshots(window_start, window_end):
    """Load all available snapshot data as fallback."""
    from pipeline.models import SignalEvent
    import json

    events = []
    snapshot_dir = Path("data/snapshots")
    if snapshot_dir.exists():
        for path in snapshot_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                for item in data:
                    events.append(SignalEvent.from_dict(item))
            except Exception:
                continue
    return events


if __name__ == "__main__":
    report = run_pipeline()
    print(f"\nPipeline complete. Run ID: {report.run_id}")
    print(f"Narratives detected: {len(report.narratives)}")
    for n in report.narratives:
        print(f"  #{n.rank}: {n.label} (score={n.score.composite:.3f}, confidence={n.confidence:.0%})")
