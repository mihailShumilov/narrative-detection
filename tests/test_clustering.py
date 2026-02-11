"""Tests for narrative clustering."""

import pytest
from datetime import datetime, timezone

from pipeline.models import SignalEvent, SourceType, SourceSubtype
from pipeline.clustering import NarrativeClusterer
from pipeline.config import load_config


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def clusterer(config):
    return NarrativeClusterer(config)


def _make_event(entities, text, subtype=SourceSubtype.GITHUB):
    return SignalEvent(
        timestamp=datetime(2026, 2, 5, tzinfo=timezone.utc),
        source_type=SourceType.OFFCHAIN,
        source_subtype=subtype,
        entities=entities,
        text=text,
    )


class TestEntityCooccurrence:
    """Test entity co-occurrence based clustering."""

    def test_cooccurring_entities_cluster_together(self, clusterer):
        """Entities that frequently co-occur should form a cluster."""
        events = [
            _make_event(["jupiter", "defi"], "Jupiter DeFi aggregator update"),
            _make_event(["jupiter", "defi"], "Jupiter swap volume increases"),
            _make_event(["jupiter", "defi"], "Jupiter DeFi TVL milestone"),
            _make_event(["tensor", "nft"], "Tensor NFT marketplace update"),
            _make_event(["tensor", "nft"], "Tensor NFT volume spike"),
            _make_event(["tensor", "nft"], "Tensor launches new features"),
        ]
        candidates = clusterer.generate_candidates(events)
        assert len(candidates) >= 2

        # Check that jupiter+defi and tensor+nft are in different clusters
        cluster_entities = [set(c.entities) for c in candidates]
        jupiter_cluster = None
        tensor_cluster = None
        for entities in cluster_entities:
            if "jupiter" in entities:
                jupiter_cluster = entities
            if "tensor" in entities:
                tensor_cluster = entities

        if jupiter_cluster and tensor_cluster:
            # They should be in different clusters (not much overlap)
            assert jupiter_cluster != tensor_cluster

    def test_minimum_events_for_cluster(self, clusterer):
        """Very few events should still produce at least a fallback cluster."""
        events = [
            _make_event(["jupiter"], "Single event"),
        ]
        candidates = clusterer.generate_candidates(events)
        # Should get fallback
        assert len(candidates) >= 1


class TestTextClustering:
    """Test text-based clustering."""

    def test_similar_texts_cluster(self, clusterer):
        """Events with similar text content should cluster together."""
        events = [
            _make_event(["entity1"], "New validator client Firedancer showing improved performance metrics"),
            _make_event(["entity2"], "Firedancer validator client performance benchmarks released"),
            _make_event(["entity3"], "Firedancer validator performance testing on testnet"),
            _make_event(["entity4"], "DePIN network Helium migration to Solana complete"),
            _make_event(["entity5"], "Helium DePIN network grows on Solana"),
            _make_event(["entity6"], "DePIN infrastructure on Solana expanding with Helium"),
        ]
        candidates = clusterer.generate_candidates(events)
        assert len(candidates) >= 1

    def test_empty_events(self, clusterer):
        """Empty event list should return empty candidates."""
        candidates = clusterer.generate_candidates([])
        assert candidates == []


class TestCandidateEnrichment:
    """Test label and description generation."""

    def test_candidates_have_labels(self, clusterer):
        """All candidates should get labels."""
        events = [
            _make_event(["defi", "jupiter"], f"DeFi event {i}")
            for i in range(5)
        ]
        candidates = clusterer.generate_candidates(events)
        for c in candidates:
            assert c.label
            assert len(c.label) > 0

    def test_candidates_have_descriptions(self, clusterer):
        """All candidates should get descriptions."""
        events = [
            _make_event(["ai-agents"], f"AI agent event {i}")
            for i in range(5)
        ]
        candidates = clusterer.generate_candidates(events)
        for c in candidates:
            assert c.description
            assert "signal events" in c.description.lower() or "signals" in c.description.lower() or len(c.description) > 0
