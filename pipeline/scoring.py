"""Narrative scoring and ranking.

Stage E of the pipeline: score narrative candidates using:
NarrativeScore = w1*Velocity + w2*Breadth + w3*CrossDomain + w4*Novelty + w5*Credibility
                 - w6*SpamPenalty - w7*SingleSourcePenalty

All features are normalized to [0, 1] range before weighting.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from pipeline.models import (
    NarrativeCandidate,
    ScoreBreakdown,
    SignalEvent,
    SourceType,
    SourceSubtype,
)
from pipeline.config import get_scoring_weights, get_scoring_penalties
from pipeline.logging import get_logger

logger = get_logger(__name__)


class NarrativeScorer:
    """Scores and ranks narrative candidates."""

    def __init__(self, config: dict):
        self.config = config
        self.weights = get_scoring_weights(config)
        self.penalties = get_scoring_penalties(config)
        thresholds = config.get("scoring", {}).get("thresholds", {})
        self.min_events = thresholds.get("min_events", 3)
        self.min_sources = thresholds.get("min_sources", 2)
        self.single_source_dominance_threshold = thresholds.get(
            "single_source_dominance", 0.70
        )

    def score_narrative(
        self,
        candidate: NarrativeCandidate,
        window_start: datetime,
        window_end: datetime,
        baseline_events: list[SignalEvent] | None = None,
    ) -> ScoreBreakdown:
        """Compute composite score for a narrative candidate."""
        events = candidate.events
        if not events:
            return ScoreBreakdown()

        velocity = self._compute_velocity(events, window_start, window_end, baseline_events)
        breadth = self._compute_breadth(events)
        cross_domain = self._compute_cross_domain(events)
        novelty = self._compute_novelty(candidate, baseline_events)
        credibility = self._compute_credibility(events)
        spam_penalty = self._compute_spam_penalty(events)
        single_source_penalty = self._compute_single_source_penalty(events)

        # Weighted composite
        composite = (
            self.weights["velocity"] * velocity
            + self.weights["breadth"] * breadth
            + self.weights["cross_domain"] * cross_domain
            + self.weights["novelty"] * novelty
            + self.weights["credibility"] * credibility
            - self.penalties["spam"] * spam_penalty
            - self.penalties["single_source"] * single_source_penalty
        )

        # Clamp to [0, 1]
        composite = max(0.0, min(1.0, composite))

        score = ScoreBreakdown(
            velocity=round(velocity, 4),
            breadth=round(breadth, 4),
            cross_domain=round(cross_domain, 4),
            novelty=round(novelty, 4),
            credibility=round(credibility, 4),
            spam_penalty=round(spam_penalty, 4),
            single_source_penalty=round(single_source_penalty, 4),
            composite=round(composite, 4),
            feature_contributions={
                "velocity": round(self.weights["velocity"] * velocity, 4),
                "breadth": round(self.weights["breadth"] * breadth, 4),
                "cross_domain": round(self.weights["cross_domain"] * cross_domain, 4),
                "novelty": round(self.weights["novelty"] * novelty, 4),
                "credibility": round(self.weights["credibility"] * credibility, 4),
                "spam_penalty": round(-self.penalties["spam"] * spam_penalty, 4),
                "single_source_penalty": round(
                    -self.penalties["single_source"] * single_source_penalty, 4
                ),
            },
        )

        return score

    def _compute_velocity(
        self,
        events: list[SignalEvent],
        window_start: datetime,
        window_end: datetime,
        baseline_events: list[SignalEvent] | None,
    ) -> float:
        """Compute event velocity: rate in window vs baseline."""
        window_count = len(events)
        window_days = max(1, (window_end - window_start).days)
        window_rate = window_count / window_days

        if baseline_events:
            baseline_count = len(baseline_events)
            # Baseline is longer, normalize to daily rate
            baseline_days = max(1, 56)  # default baseline window
            baseline_rate = baseline_count / baseline_days

            if baseline_rate > 0:
                acceleration = window_rate / baseline_rate
                # Normalize: 1x = 0.3, 2x = 0.6, 3x+ = 0.9+
                velocity = min(1.0, acceleration * 0.3)
            else:
                velocity = 1.0  # Completely new signal
        else:
            # No baseline: use event count as proxy
            velocity = min(1.0, window_count / 20.0)

        return velocity

    def _compute_breadth(self, events: list[SignalEvent]) -> float:
        """Compute breadth: unique entities and sources involved."""
        unique_entities = set()
        unique_sources = set()
        unique_authors = set()

        for event in events:
            unique_entities.update(event.entities)
            unique_sources.add(event.source_subtype.value)
            if event.author:
                unique_authors.add(event.author)

        # More entities = broader narrative
        entity_score = min(1.0, len(unique_entities) / 8.0)
        source_score = min(1.0, len(unique_sources) / 4.0)
        author_score = min(1.0, len(unique_authors) / 10.0)

        return (entity_score * 0.4 + source_score * 0.3 + author_score * 0.3)

    def _compute_cross_domain(self, events: list[SignalEvent]) -> float:
        """Compute cross-domain corroboration: onchain + offchain alignment."""
        onchain_count = sum(1 for e in events if e.source_type == SourceType.ONCHAIN)
        offchain_count = sum(1 for e in events if e.source_type == SourceType.OFFCHAIN)

        if onchain_count == 0 or offchain_count == 0:
            return 0.0

        # Balance between domains
        total = onchain_count + offchain_count
        balance = min(onchain_count, offchain_count) / max(onchain_count, offchain_count)

        # Count distinct offchain subtypes
        offchain_subtypes = set(
            e.source_subtype.value for e in events if e.source_type == SourceType.OFFCHAIN
        )
        subtype_bonus = min(1.0, len(offchain_subtypes) / 3.0)

        return balance * 0.5 + subtype_bonus * 0.5

    def _compute_novelty(
        self,
        candidate: NarrativeCandidate,
        baseline_events: list[SignalEvent] | None,
    ) -> float:
        """Compute novelty: new entities or significantly changed cluster."""
        if not baseline_events:
            return 0.8  # Assume somewhat novel without baseline

        baseline_entities = set()
        for event in baseline_events:
            baseline_entities.update(event.entities)

        current_entities = set(candidate.entities)
        if not current_entities:
            return 0.5

        # New entities not seen in baseline
        new_entities = current_entities - baseline_entities
        novelty_ratio = len(new_entities) / max(1, len(current_entities))

        return min(1.0, novelty_ratio * 1.5 + 0.2)

    def _compute_credibility(self, events: list[SignalEvent]) -> float:
        """Compute credibility based on source quality."""
        if not events:
            return 0.0

        credibility_scores = []
        for event in events:
            score = 0.5  # base

            # Onchain data is inherently credible
            if event.source_type == SourceType.ONCHAIN:
                score = 0.9

            # High-follower authors are more credible
            if event.author_followers > 10000:
                score = max(score, 0.85)
            elif event.author_followers > 1000:
                score = max(score, 0.7)

            # Official sources
            if event.source_subtype == SourceSubtype.RSS_BLOG:
                score = max(score, 0.75)

            # GitHub signals
            if event.source_subtype == SourceSubtype.GITHUB:
                stars = event.metrics.get("stars", 0)
                if stars > 100:
                    score = max(score, 0.8)
                elif stars > 10:
                    score = max(score, 0.65)

            # Has URL (verifiable)
            if event.url:
                score += 0.05

            credibility_scores.append(min(1.0, score))

        return np.mean(credibility_scores)

    def _compute_spam_penalty(self, events: list[SignalEvent]) -> float:
        """Detect and penalize spam patterns."""
        if len(events) < 3:
            return 0.0

        # Check for burst patterns (many events in very short time)
        timestamps = sorted(e.timestamp for e in events)
        if len(timestamps) >= 5:
            # Check if >50% of events occur within 1 hour
            min_window = timedelta(hours=1)
            for i in range(len(timestamps) - 4):
                window_events = sum(
                    1 for t in timestamps[i:]
                    if t - timestamps[i] <= min_window
                )
                if window_events > len(timestamps) * 0.5:
                    return 0.8  # Heavy burst penalty

        # Check for repetitive authors
        author_counts = Counter(e.author for e in events if e.author)
        if author_counts:
            max_author_pct = max(author_counts.values()) / len(events)
            if max_author_pct > 0.6:
                return 0.5

        return 0.0

    def _compute_single_source_penalty(self, events: list[SignalEvent]) -> float:
        """Penalize narratives dominated by a single source category."""
        source_counts = Counter(e.source_subtype.value for e in events)
        if not source_counts:
            return 0.0

        total = sum(source_counts.values())
        max_pct = max(source_counts.values()) / total

        if max_pct >= self.single_source_dominance_threshold:
            # Penalty proportional to dominance
            return (max_pct - self.single_source_dominance_threshold) / (
                1.0 - self.single_source_dominance_threshold
            )

        return 0.0

    def rank_narratives(
        self,
        candidates: list[NarrativeCandidate],
        window_start: datetime,
        window_end: datetime,
        baseline_events: list[SignalEvent] | None = None,
    ) -> list[tuple[NarrativeCandidate, ScoreBreakdown]]:
        """Score and rank all candidate narratives."""
        scored = []
        for candidate in candidates:
            # Get baseline events matching this candidate's entities
            candidate_baseline = None
            if baseline_events:
                candidate_entities = set(candidate.entities)
                candidate_baseline = [
                    e for e in baseline_events
                    if candidate_entities.intersection(set(e.entities))
                ]

            score = self.score_narrative(
                candidate, window_start, window_end, candidate_baseline
            )
            scored.append((candidate, score))

        # Sort by composite score descending
        scored.sort(key=lambda x: x[1].composite, reverse=True)

        # Filter out very low scores
        scored = [(c, s) for c, s in scored if s.composite > 0.05]

        logger.info(
            "narratives_ranked",
            total_candidates=len(candidates),
            ranked=len(scored),
            top_score=scored[0][1].composite if scored else 0,
        )

        return scored
