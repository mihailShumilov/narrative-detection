"""Tests for narrative scoring logic.

Verifies the scoring model properties:
- Cross-domain corroboration outranks same velocity single-domain
- Spam bursts are penalized
- Single-source dominance is penalized
- Novelty increases score when cluster is new
"""

import pytest
from datetime import datetime, timezone, timedelta

from pipeline.models import (
    SignalEvent,
    NarrativeCandidate,
    ScoreBreakdown,
    SourceType,
    SourceSubtype,
)
from pipeline.scoring import NarrativeScorer
from pipeline.config import load_config


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def scorer(config):
    return NarrativeScorer(config)


@pytest.fixture
def window():
    end = datetime(2026, 2, 10, tzinfo=timezone.utc)
    start = end - timedelta(days=14)
    return start, end


def _make_event(
    source_type=SourceType.OFFCHAIN,
    source_subtype=SourceSubtype.GITHUB,
    entities=None,
    text="Test event",
    author="user1",
    author_followers=100,
    timestamp=None,
    metrics=None,
):
    """Helper to create test events."""
    return SignalEvent(
        timestamp=timestamp or datetime(2026, 2, 5, tzinfo=timezone.utc),
        source_type=source_type,
        source_subtype=source_subtype,
        entities=entities or ["test-entity"],
        text=text,
        author=author,
        author_followers=author_followers,
        metrics=metrics or {},
    )


def _make_candidate(events, entities=None):
    """Helper to create test candidates."""
    all_entities = set()
    for e in events:
        all_entities.update(e.entities)
    return NarrativeCandidate(
        id="test",
        label="Test Narrative",
        description="Test",
        events=events,
        entities=entities or sorted(all_entities),
    )


class TestCrossDomainCorroboration:
    """Test that cross-domain narratives outrank single-domain."""

    def test_cross_domain_beats_single_domain(self, scorer, window):
        """A narrative with both onchain + offchain signals should score higher
        than one with the same number of events from a single domain."""
        start, end = window

        # Single-domain: all GitHub events
        single_domain_events = [
            _make_event(
                source_type=SourceType.OFFCHAIN,
                source_subtype=SourceSubtype.GITHUB,
                entities=["jupiter"],
                text=f"GitHub event {i}",
                author=f"dev{i}",
            )
            for i in range(8)
        ]

        # Cross-domain: mix of onchain + offchain
        cross_domain_events = [
            _make_event(
                source_type=SourceType.ONCHAIN,
                source_subtype=SourceSubtype.TX_ACTIVITY,
                entities=["jupiter"],
                text=f"Onchain event {i}",
                author=f"onchain{i}",
            )
            for i in range(4)
        ] + [
            _make_event(
                source_type=SourceType.OFFCHAIN,
                source_subtype=SourceSubtype.GITHUB,
                entities=["jupiter"],
                text=f"GitHub event {i}",
                author=f"dev{i}",
            )
            for i in range(2)
        ] + [
            _make_event(
                source_type=SourceType.OFFCHAIN,
                source_subtype=SourceSubtype.TWITTER,
                entities=["jupiter"],
                text=f"Twitter event {i}",
                author=f"kol{i}",
            )
            for i in range(2)
        ]

        single_candidate = _make_candidate(single_domain_events)
        cross_candidate = _make_candidate(cross_domain_events)

        single_score = scorer.score_narrative(single_candidate, start, end)
        cross_score = scorer.score_narrative(cross_candidate, start, end)

        assert cross_score.cross_domain > single_score.cross_domain
        assert cross_score.composite > single_score.composite

    def test_cross_domain_score_zero_for_single_domain(self, scorer, window):
        """Cross-domain should be 0 when only one domain present."""
        start, end = window
        events = [
            _make_event(source_type=SourceType.OFFCHAIN, source_subtype=SourceSubtype.GITHUB)
            for _ in range(5)
        ]
        candidate = _make_candidate(events)
        score = scorer.score_narrative(candidate, start, end)
        assert score.cross_domain == 0.0


class TestSpamPenalty:
    """Test that spam patterns are penalized."""

    def test_burst_events_penalized(self, scorer, window):
        """Events clustered in a very short timeframe should incur spam penalty."""
        start, end = window
        base_time = datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc)

        # All events within 30 minutes (burst)
        burst_events = [
            _make_event(
                timestamp=base_time + timedelta(minutes=i * 3),
                text=f"Burst event {i}",
                author=f"user{i}",
            )
            for i in range(10)
        ]

        # Events spread over 14 days (organic)
        spread_events = [
            _make_event(
                timestamp=start + timedelta(days=i),
                text=f"Spread event {i}",
                author=f"user{i}",
            )
            for i in range(10)
        ]

        burst_candidate = _make_candidate(burst_events)
        spread_candidate = _make_candidate(spread_events)

        burst_score = scorer.score_narrative(burst_candidate, start, end)
        spread_score = scorer.score_narrative(spread_candidate, start, end)

        assert burst_score.spam_penalty > spread_score.spam_penalty

    def test_repetitive_author_penalized(self, scorer, window):
        """Events dominated by a single author should incur spam penalty."""
        start, end = window

        # Single author dominance
        single_author_events = [
            _make_event(
                author="spammer",
                text=f"Event from spammer {i}",
                timestamp=start + timedelta(days=i),
            )
            for i in range(8)
        ]

        # Diverse authors
        diverse_events = [
            _make_event(
                author=f"user{i}",
                text=f"Event from user {i}",
                timestamp=start + timedelta(days=i),
            )
            for i in range(8)
        ]

        single_candidate = _make_candidate(single_author_events)
        diverse_candidate = _make_candidate(diverse_events)

        single_score = scorer.score_narrative(single_candidate, start, end)
        diverse_score = scorer.score_narrative(diverse_candidate, start, end)

        assert single_score.spam_penalty > diverse_score.spam_penalty


class TestSingleSourcePenalty:
    """Test that single-source dominance is penalized."""

    def test_single_source_dominance(self, scorer, window):
        """Narratives with >70% events from one source type should be penalized."""
        start, end = window

        # 90% GitHub (single source dominant)
        dominant_events = [
            _make_event(source_subtype=SourceSubtype.GITHUB, text=f"GH {i}", author=f"u{i}")
            for i in range(9)
        ] + [
            _make_event(source_subtype=SourceSubtype.TWITTER, text="Tweet", author="kol1")
        ]

        # Balanced sources
        balanced_events = [
            _make_event(source_subtype=SourceSubtype.GITHUB, text=f"GH {i}", author=f"u{i}")
            for i in range(4)
        ] + [
            _make_event(source_subtype=SourceSubtype.TWITTER, text=f"Tweet {i}", author=f"kol{i}")
            for i in range(3)
        ] + [
            _make_event(source_subtype=SourceSubtype.RSS_BLOG, text=f"Blog {i}", author=f"blog{i}")
            for i in range(3)
        ]

        dominant_candidate = _make_candidate(dominant_events)
        balanced_candidate = _make_candidate(balanced_events)

        dominant_score = scorer.score_narrative(dominant_candidate, start, end)
        balanced_score = scorer.score_narrative(balanced_candidate, start, end)

        assert dominant_score.single_source_penalty > balanced_score.single_source_penalty

    def test_balanced_sources_no_penalty(self, scorer, window):
        """Well-balanced sources should have no single source penalty."""
        start, end = window
        events = [
            _make_event(source_subtype=SourceSubtype.GITHUB, author="u1"),
            _make_event(source_subtype=SourceSubtype.GITHUB, author="u2"),
            _make_event(source_subtype=SourceSubtype.TWITTER, author="u3"),
            _make_event(source_subtype=SourceSubtype.TWITTER, author="u4"),
            _make_event(source_subtype=SourceSubtype.RSS_BLOG, author="u5"),
            _make_event(source_subtype=SourceSubtype.RSS_BLOG, author="u6"),
        ]
        candidate = _make_candidate(events)
        score = scorer.score_narrative(candidate, start, end)
        assert score.single_source_penalty == 0.0


class TestNovelty:
    """Test that novelty scoring works correctly."""

    def test_new_cluster_has_high_novelty(self, scorer, window):
        """A narrative with entities not seen in baseline should have high novelty."""
        start, end = window

        # Current events with new entities
        current_events = [
            _make_event(entities=["new-project-x"], text=f"New project {i}", author=f"u{i}")
            for i in range(5)
        ]

        # Baseline with completely different entities
        baseline_events = [
            _make_event(entities=["old-project"], text=f"Old project {i}", author=f"old{i}")
            for i in range(10)
        ]

        candidate = _make_candidate(current_events)
        score = scorer.score_narrative(candidate, start, end, baseline_events)

        assert score.novelty > 0.7

    def test_established_cluster_lower_novelty(self, scorer, window):
        """A narrative with entities already in baseline should have lower novelty."""
        start, end = window

        # Current events with same entities as baseline
        current_events = [
            _make_event(entities=["established-project"], text=f"Established {i}", author=f"u{i}")
            for i in range(5)
        ]

        # Baseline with SAME entities
        baseline_events = [
            _make_event(entities=["established-project"], text=f"Baseline {i}", author=f"b{i}")
            for i in range(10)
        ]

        candidate = _make_candidate(current_events)
        score = scorer.score_narrative(candidate, start, end, baseline_events)

        assert score.novelty < 0.5


class TestVelocity:
    """Test velocity scoring."""

    def test_more_events_higher_velocity(self, scorer, window):
        """More events in the window should increase velocity."""
        start, end = window

        few_events = [
            _make_event(text=f"Event {i}", author=f"u{i}")
            for i in range(3)
        ]
        many_events = [
            _make_event(text=f"Event {i}", author=f"u{i}")
            for i in range(15)
        ]

        few_candidate = _make_candidate(few_events)
        many_candidate = _make_candidate(many_events)

        few_score = scorer.score_narrative(few_candidate, start, end)
        many_score = scorer.score_narrative(many_candidate, start, end)

        assert many_score.velocity > few_score.velocity


class TestCompositeScore:
    """Test overall composite score properties."""

    def test_score_in_valid_range(self, scorer, window):
        """Composite score should always be in [0, 1]."""
        start, end = window
        events = [
            _make_event(text=f"Event {i}", author=f"u{i}")
            for i in range(5)
        ]
        candidate = _make_candidate(events)
        score = scorer.score_narrative(candidate, start, end)
        assert 0.0 <= score.composite <= 1.0

    def test_empty_events_zero_score(self, scorer, window):
        """Empty events should produce zero score."""
        start, end = window
        candidate = _make_candidate([])
        score = scorer.score_narrative(candidate, start, end)
        assert score.composite == 0.0

    def test_feature_contributions_sum(self, scorer, window):
        """Feature contributions should approximately sum to composite."""
        start, end = window
        events = [
            _make_event(
                source_type=SourceType.ONCHAIN if i < 3 else SourceType.OFFCHAIN,
                source_subtype=SourceSubtype.TX_ACTIVITY if i < 3 else SourceSubtype.GITHUB,
                text=f"Event {i}",
                author=f"u{i}",
            )
            for i in range(8)
        ]
        candidate = _make_candidate(events)
        score = scorer.score_narrative(candidate, start, end)

        contrib_sum = sum(score.feature_contributions.values())
        # Should be close (clamped to [0,1] may cause small differences)
        assert abs(contrib_sum - score.composite) < 0.1 or score.composite in (0.0, 1.0)
