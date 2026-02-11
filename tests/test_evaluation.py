"""Evaluation harness for narrative detection quality.

Sanity checks:
- Remove single source dominance
- Detect spammy bursts
- Regression tests on fixed snapshot dataset
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from pipeline.models import SignalEvent, NarrativeCandidate, SourceType, SourceSubtype
from pipeline.scoring import NarrativeScorer
from pipeline.normalizer import EventNormalizer
from pipeline.clustering import NarrativeClusterer
from pipeline.config import load_config


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def scorer(config):
    return NarrativeScorer(config)


@pytest.fixture
def normalizer(config):
    return EventNormalizer(config)


def _make_event(
    entities, text,
    source_type=SourceType.OFFCHAIN,
    source_subtype=SourceSubtype.GITHUB,
    author="user1",
    timestamp=None,
):
    return SignalEvent(
        timestamp=timestamp or datetime(2026, 2, 5, tzinfo=timezone.utc),
        source_type=source_type,
        source_subtype=source_subtype,
        entities=entities,
        text=text,
        author=author,
    )


class TestSanityChecks:
    """Sanity checks to ensure output quality."""

    def test_no_single_source_dominance_in_top_narratives(self, config, scorer):
        """Top narratives should not be dominated by a single source type."""
        window_start = datetime(2026, 1, 27, tzinfo=timezone.utc)
        window_end = datetime(2026, 2, 10, tzinfo=timezone.utc)

        # Create a narrative with diverse sources
        diverse_events = [
            _make_event(["jupiter"], f"GitHub: Jupiter {i}", source_subtype=SourceSubtype.GITHUB, author=f"dev{i}")
            for i in range(3)
        ] + [
            _make_event(["jupiter"], f"Twitter: Jupiter {i}", source_subtype=SourceSubtype.TWITTER, author=f"kol{i}")
            for i in range(3)
        ] + [
            _make_event(["jupiter"], f"Blog: Jupiter {i}", source_subtype=SourceSubtype.RSS_BLOG, author=f"blog{i}")
            for i in range(3)
        ]

        # Create a single-source narrative
        single_source_events = [
            _make_event(["tensor"], f"GitHub: Tensor {i}", source_subtype=SourceSubtype.GITHUB, author=f"dev{i}")
            for i in range(9)
        ]

        candidates = [
            NarrativeCandidate(id="diverse", label="Diverse", description="", events=diverse_events, entities=["jupiter"]),
            NarrativeCandidate(id="single", label="Single", description="", events=single_source_events, entities=["tensor"]),
        ]

        ranked = scorer.rank_narratives(candidates, window_start, window_end)

        # Diverse should rank higher
        assert ranked[0][0].id == "diverse"

    def test_spam_burst_detection(self, normalizer, scorer):
        """Spammy bursts should be detected and penalized."""
        window_start = datetime(2026, 1, 27, tzinfo=timezone.utc)
        window_end = datetime(2026, 2, 10, tzinfo=timezone.utc)
        base_time = datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc)

        # Create burst events (all within 30 minutes)
        burst_events = [
            _make_event(
                ["spam-project"],
                f"Amazing spam project event {i}!",
                timestamp=base_time + timedelta(minutes=i * 2),
                author=f"user{i}",
            )
            for i in range(10)
        ]

        candidate = NarrativeCandidate(
            id="spam", label="Spam", description="",
            events=burst_events, entities=["spam-project"],
        )

        score = scorer.score_narrative(candidate, window_start, window_end)
        assert score.spam_penalty > 0.3

    def test_dedup_removes_near_duplicates(self, normalizer):
        """Near-duplicate events should be removed."""
        events = [
            _make_event(["project-x"], "Project X launches innovative new feature for Solana DeFi users"),
            _make_event(["project-x"], "Project X launches innovative new feature for Solana DeFi users today"),
            _make_event(["project-x"], "Project X launches innovative new feature for Solana DeFi users!"),
            _make_event(["project-y"], "Completely different event about Project Y"),
        ]

        deduped = normalizer.deduplicate(events)
        assert len(deduped) <= 3  # Should remove at least 1 near-duplicate

    def test_minimum_source_diversity(self, config, scorer):
        """Narratives with <2 source categories should be penalized
        (unless very strong onchain signal)."""
        window_start = datetime(2026, 1, 27, tzinfo=timezone.utc)
        window_end = datetime(2026, 2, 10, tzinfo=timezone.utc)

        # Single source type
        single_events = [
            _make_event(["test"], f"Event {i}", source_subtype=SourceSubtype.TWITTER, author=f"u{i}")
            for i in range(5)
        ]

        candidate = NarrativeCandidate(
            id="test", label="Test", description="",
            events=single_events, entities=["test"],
        )

        score = scorer.score_narrative(candidate, window_start, window_end)

        # Cross-domain should be zero
        assert score.cross_domain == 0.0
        # Should have some single source penalty since all twitter
        assert score.single_source_penalty > 0


class TestSnapshotRegression:
    """Regression tests using bundled snapshot data."""

    def _load_snapshot_events(self) -> list[SignalEvent]:
        """Load all snapshot events."""
        events = []
        snapshot_dir = Path("data/snapshots")
        if not snapshot_dir.exists():
            pytest.skip("Snapshot data not available")

        for path in snapshot_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                for item in data:
                    events.append(SignalEvent.from_dict(item))
            except Exception:
                continue

        if not events:
            pytest.skip("No snapshot events found")
        return events

    def test_snapshot_produces_narratives(self, config):
        """Snapshot data should produce at least 3 narratives."""
        events = self._load_snapshot_events()

        normalizer = EventNormalizer(config)
        events = normalizer.process(events)

        clusterer = NarrativeClusterer(config)
        candidates = clusterer.generate_candidates(events)

        assert len(candidates) >= 3, f"Expected >= 3 candidates, got {len(candidates)}"

    def test_snapshot_scoring_produces_valid_scores(self, config):
        """All scores from snapshot should be valid."""
        events = self._load_snapshot_events()

        normalizer = EventNormalizer(config)
        events = normalizer.process(events)

        clusterer = NarrativeClusterer(config)
        candidates = clusterer.generate_candidates(events)

        scorer = NarrativeScorer(config)
        window_start = datetime(2026, 1, 27, tzinfo=timezone.utc)
        window_end = datetime(2026, 2, 10, tzinfo=timezone.utc)

        ranked = scorer.rank_narratives(candidates, window_start, window_end)

        for candidate, score in ranked:
            assert 0.0 <= score.composite <= 1.0
            assert 0.0 <= score.velocity <= 1.0
            assert 0.0 <= score.breadth <= 1.0
            assert 0.0 <= score.cross_domain <= 1.0
            assert 0.0 <= score.novelty <= 1.0
            assert 0.0 <= score.credibility <= 1.0

    def test_snapshot_no_empty_narratives(self, config):
        """No narrative should have zero events after processing."""
        events = self._load_snapshot_events()

        normalizer = EventNormalizer(config)
        events = normalizer.process(events)

        clusterer = NarrativeClusterer(config)
        candidates = clusterer.generate_candidates(events)

        for candidate in candidates:
            assert len(candidate.events) > 0, f"Candidate {candidate.id} has no events"
