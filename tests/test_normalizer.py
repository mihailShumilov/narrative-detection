"""Tests for event normalization and deduplication."""

import pytest
from datetime import datetime, timezone

from pipeline.models import SignalEvent, SourceType, SourceSubtype
from pipeline.normalizer import EventNormalizer
from pipeline.config import load_config


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def normalizer(config):
    return EventNormalizer(config)


def _make_event(entities, text="Test", timestamp=None):
    return SignalEvent(
        timestamp=timestamp or datetime(2026, 2, 5, tzinfo=timezone.utc),
        source_type=SourceType.OFFCHAIN,
        source_subtype=SourceSubtype.GITHUB,
        entities=entities,
        text=text,
    )


class TestEntityNormalization:
    """Test entity alias resolution."""

    def test_alias_resolution(self, normalizer):
        """Known aliases should resolve to canonical name."""
        assert normalizer.normalize_entity("anchor-lang") == "anchor"
        assert normalizer.normalize_entity("coral-xyz/anchor") == "anchor"

    def test_canonical_passes_through(self, normalizer):
        """Canonical names should pass through unchanged."""
        assert normalizer.normalize_entity("anchor") == "anchor"
        assert normalizer.normalize_entity("jupiter") == "jupiter"

    def test_unknown_entity_passes_through(self, normalizer):
        """Unknown entities should pass through unchanged."""
        assert normalizer.normalize_entity("unknown-project") == "unknown-project"

    def test_normalize_events(self, normalizer):
        """Events should have entities normalized."""
        events = [
            _make_event(["anchor-lang", "metaplex-foundation"]),
            _make_event(["coral-xyz/anchor", "JUP"]),
        ]
        normalized = normalizer.normalize_events(events)
        assert "anchor" in normalized[0].entities
        assert "metaplex" in normalized[0].entities
        assert "anchor" in normalized[1].entities


class TestDeduplication:
    """Test event deduplication."""

    def test_exact_hash_dedup(self, normalizer):
        """Events with identical content should be deduped."""
        events = [
            _make_event(["jupiter"], "Jupiter launches new feature"),
            _make_event(["jupiter"], "Jupiter launches new feature"),
            _make_event(["jupiter"], "Jupiter launches new feature"),
        ]
        deduped = normalizer.deduplicate(events)
        assert len(deduped) == 1

    def test_fuzzy_dedup(self, normalizer):
        """Near-identical events should be deduped."""
        events = [
            _make_event(["jupiter"], "Jupiter Exchange launches new aggregation feature v2"),
            _make_event(["jupiter"], "Jupiter Exchange launches new aggregation feature v2.0"),
        ]
        deduped = normalizer.deduplicate(events)
        assert len(deduped) == 1

    def test_different_events_kept(self, normalizer):
        """Distinct events should be kept."""
        events = [
            _make_event(["jupiter"], "Jupiter launches new feature"),
            _make_event(["drift"], "Drift protocol reaches $1B TVL"),
            _make_event(["tensor"], "Tensor NFT marketplace update"),
        ]
        deduped = normalizer.deduplicate(events)
        assert len(deduped) == 3

    def test_empty_input(self, normalizer):
        """Empty input should return empty."""
        assert normalizer.deduplicate([]) == []

    def test_full_process_pipeline(self, normalizer):
        """Full process should normalize and dedup."""
        events = [
            _make_event(["anchor-lang"], "Anchor framework update"),
            _make_event(["coral-xyz/anchor"], "Anchor framework update"),
            _make_event(["drift"], "Drift new feature"),
        ]
        result = normalizer.process(events)
        assert len(result) == 2  # Two unique events after dedup
        # All entities should be normalized
        for event in result:
            for entity in event.entities:
                assert entity == entity.lower()
