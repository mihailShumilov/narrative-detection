"""Event normalization and deduplication.

Stage B+C of the pipeline: normalize entities, deduplicate near-identical events.
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from typing import Optional

from pipeline.models import SignalEvent
from pipeline.config import get_entity_aliases
from pipeline.logging import get_logger

logger = get_logger(__name__)


class EventNormalizer:
    """Normalizes and deduplicates signal events."""

    def __init__(self, config: dict):
        self.config = config
        self.alias_map = self._build_alias_map(get_entity_aliases(config))
        self.similarity_threshold = (
            config.get("scoring", {})
            .get("thresholds", {})
            .get("spam_similarity", 0.85)
        )

    def _build_alias_map(self, aliases: dict[str, list[str]]) -> dict[str, str]:
        """Build reverse mapping from alias -> canonical name."""
        mapping = {}
        for canonical, alias_list in aliases.items():
            mapping[canonical.lower()] = canonical.lower()
            for alias in alias_list:
                mapping[alias.lower()] = canonical.lower()
        return mapping

    def normalize_entity(self, entity: str) -> str:
        """Resolve entity to canonical name."""
        normalized = entity.lower().strip()
        return self.alias_map.get(normalized, normalized)

    def normalize_events(self, events: list[SignalEvent]) -> list[SignalEvent]:
        """Normalize all entity references across events."""
        for event in events:
            event.entities = list(set(
                self.normalize_entity(e) for e in event.entities
            ))
        logger.info("events_normalized", count=len(events))
        return events

    def deduplicate(self, events: list[SignalEvent]) -> list[SignalEvent]:
        """Remove near-duplicate events using content hashing and similarity."""
        if not events:
            return []

        # Phase 1: Exact hash dedup
        seen_hashes = set()
        phase1_events = []
        for event in events:
            if event.content_hash not in seen_hashes:
                seen_hashes.add(event.content_hash)
                phase1_events.append(event)

        removed_exact = len(events) - len(phase1_events)

        # Phase 2: Fuzzy dedup on text similarity (within same source subtype)
        by_subtype: dict[str, list[SignalEvent]] = {}
        for event in phase1_events:
            key = event.source_subtype.value
            by_subtype.setdefault(key, []).append(event)

        deduped = []
        removed_fuzzy = 0
        for subtype, group in by_subtype.items():
            kept = []
            for event in group:
                is_dup = False
                for existing in kept:
                    sim = self._text_similarity(event.text[:200], existing.text[:200])
                    if sim >= self.similarity_threshold:
                        is_dup = True
                        removed_fuzzy += 1
                        break
                if not is_dup:
                    kept.append(event)
            deduped.extend(kept)

        # Sort by timestamp
        deduped.sort(key=lambda e: e.timestamp)

        logger.info(
            "deduplication_complete",
            original=len(events),
            after_exact=len(phase1_events),
            after_fuzzy=len(deduped),
            removed_exact=removed_exact,
            removed_fuzzy=removed_fuzzy,
        )
        return deduped

    def _text_similarity(self, a: str, b: str) -> float:
        """Compute text similarity ratio."""
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def process(self, events: list[SignalEvent]) -> list[SignalEvent]:
        """Full normalization pipeline: normalize + dedup."""
        normalized = self.normalize_events(events)
        deduped = self.deduplicate(normalized)
        return deduped
