"""Explanation builder for narratives.

Stage F of the pipeline: build evidence cards, "why now" explanations,
and confidence assessments for each narrative.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Optional

from pipeline.models import (
    NarrativeCandidate,
    ScoreBreakdown,
    EvidenceCard,
    SignalEvent,
    SourceType,
)
from pipeline.logging import get_logger

logger = get_logger(__name__)


class NarrativeExplainer:
    """Builds human-readable explanations for detected narratives."""

    def __init__(self, config: dict):
        self.config = config
        self.max_evidence_cards = 8

    def build_explanation(
        self,
        candidate: NarrativeCandidate,
        score: ScoreBreakdown,
    ) -> str:
        """Generate a concise explanation of what the narrative is and why it matters."""
        entities = candidate.entities[:5]
        event_count = len(candidate.events)
        source_types = Counter(e.source_subtype.value for e in candidate.events)

        entity_str = ", ".join(e.replace("-", " ").title() for e in entities)
        source_str = ", ".join(
            f"{st.replace('_', ' ')} ({c})" for st, c in source_types.most_common(3)
        )

        explanation = (
            f"**{candidate.label}** is an emerging narrative in the Solana ecosystem "
            f"centered around {entity_str}. "
            f"Over the analysis window, {event_count} signal events were detected "
            f"across {source_str}. "
        )

        # Add score-driven insights
        if score.cross_domain > 0.5:
            explanation += (
                "This narrative shows strong cross-domain corroboration, "
                "appearing in both onchain activity and offchain discourse. "
            )
        if score.velocity > 0.6:
            explanation += (
                "The signal velocity is high, indicating rapid acceleration "
                "compared to the baseline period. "
            )
        if score.novelty > 0.7:
            explanation += (
                "This is a relatively novel cluster, suggesting an emerging "
                "rather than established trend. "
            )

        return explanation

    def build_why_now(
        self,
        candidate: NarrativeCandidate,
        score: ScoreBreakdown,
        window_start: datetime,
        window_end: datetime,
    ) -> str:
        """Generate a 'why now' section explaining acceleration."""
        parts = []

        # Velocity-driven
        if score.velocity > 0.5:
            parts.append(
                f"Signal velocity is {score.velocity:.0%} of maximum, "
                f"indicating significant acceleration in the {(window_end - window_start).days}-day window."
            )

        # Cross-domain signal
        onchain = sum(1 for e in candidate.events if e.source_type == SourceType.ONCHAIN)
        offchain = sum(1 for e in candidate.events if e.source_type == SourceType.OFFCHAIN)
        if onchain > 0 and offchain > 0:
            parts.append(
                f"Cross-domain corroboration: {onchain} onchain signals and "
                f"{offchain} offchain signals align on this narrative."
            )

        # Specific triggers
        recent_events = sorted(candidate.events, key=lambda e: e.timestamp, reverse=True)
        if recent_events:
            latest = recent_events[0]
            parts.append(
                f"Most recent trigger: {latest.text[:150]}..."
                + (f" ({latest.url})" if latest.url else "")
            )

        # New entities
        if score.novelty > 0.6:
            parts.append(
                "New entities or projects have entered this cluster recently, "
                "suggesting the narrative is still forming rather than mature."
            )

        # Unique contributors
        unique_authors = set(e.author for e in candidate.events if e.author)
        if len(unique_authors) > 3:
            parts.append(
                f"{len(unique_authors)} distinct contributors are driving this signal, "
                "suggesting organic growth rather than a single promoter."
            )

        if not parts:
            parts.append(
                "This narrative shows steady signals across the analysis window."
            )

        return " ".join(parts)

    def build_evidence_cards(
        self,
        candidate: NarrativeCandidate,
        score: ScoreBreakdown,
    ) -> list[EvidenceCard]:
        """Build ranked evidence cards for the narrative."""
        cards = []

        for event in candidate.events:
            relevance = self._score_event_relevance(event, candidate, score)
            summary = self._summarize_event(event)
            metric_highlight = self._highlight_metric(event)

            cards.append(
                EvidenceCard(
                    event=event,
                    relevance_score=relevance,
                    summary=summary,
                    metric_highlight=metric_highlight,
                )
            )

        # Sort by relevance and take top N
        cards.sort(key=lambda c: c.relevance_score, reverse=True)
        return cards[: self.max_evidence_cards]

    def _score_event_relevance(
        self,
        event: SignalEvent,
        candidate: NarrativeCandidate,
        score: ScoreBreakdown,
    ) -> float:
        """Score how relevant an event is to the narrative."""
        relevance = 0.5

        # Entity overlap
        event_entities = set(event.entities)
        candidate_entities = set(candidate.entities)
        if candidate_entities:
            overlap = len(event_entities & candidate_entities) / len(candidate_entities)
            relevance += overlap * 0.2

        # Source diversity bonus
        if event.source_type == SourceType.ONCHAIN:
            relevance += 0.1  # Onchain evidence is stronger

        # Recency bonus
        relevance += 0.05

        # Credibility indicators
        if event.url:
            relevance += 0.05
        if event.author_followers > 5000:
            relevance += 0.05
        if event.metrics.get("stars", 0) > 50:
            relevance += 0.05

        return min(1.0, relevance)

    def _summarize_event(self, event: SignalEvent) -> str:
        """Create a concise summary of an event."""
        source_label = {
            "github": "GitHub",
            "twitter": "X/Twitter",
            "rss_blog": "Blog",
            "program_deploy": "Onchain",
            "tx_activity": "Onchain Metrics",
            "token_activity": "Token Data",
        }.get(event.source_subtype.value, event.source_subtype.value)

        text = event.text[:200]
        if len(event.text) > 200:
            text += "..."

        return f"[{source_label}] {text}"

    def _highlight_metric(self, event: SignalEvent) -> Optional[str]:
        """Extract the most notable metric from an event."""
        metrics = event.metrics
        if not metrics:
            return None

        highlights = []
        if "stars" in metrics and metrics["stars"] > 0:
            highlights.append(f"{metrics['stars']} stars")
        if "forks" in metrics and metrics["forks"] > 0:
            highlights.append(f"{metrics['forks']} forks")
        if "likes" in metrics and metrics["likes"] > 0:
            highlights.append(f"{metrics['likes']} likes")
        if "retweets" in metrics and metrics["retweets"] > 0:
            highlights.append(f"{metrics['retweets']} RTs")
        if "avg_tps" in metrics:
            highlights.append(f"{metrics['avg_tps']:.0f} TPS")
        if "total_txs_sample" in metrics:
            highlights.append(f"{metrics['total_txs_sample']:,} txs")
        if "balance_sol" in metrics and metrics["balance_sol"] > 0:
            highlights.append(f"{metrics['balance_sol']:.2f} SOL")
        if "is_release" in metrics and metrics["is_release"]:
            highlights.append(f"Release: {metrics.get('tag', '')}")
        if "is_new" in metrics and metrics["is_new"]:
            highlights.append("Newly created")

        return " | ".join(highlights[:3]) if highlights else None

    def compute_confidence(
        self,
        candidate: NarrativeCandidate,
        score: ScoreBreakdown,
    ) -> tuple[float, str]:
        """Compute confidence level with reasoning."""
        factors = []
        confidence = 0.5  # base

        # Event count
        n_events = len(candidate.events)
        if n_events >= 10:
            confidence += 0.15
            factors.append(f"Strong evidence base ({n_events} events)")
        elif n_events >= 5:
            confidence += 0.08
            factors.append(f"Moderate evidence base ({n_events} events)")
        else:
            confidence -= 0.1
            factors.append(f"Limited evidence ({n_events} events)")

        # Cross-domain corroboration
        if score.cross_domain > 0.5:
            confidence += 0.15
            factors.append("Cross-domain corroboration (onchain + offchain)")
        elif score.cross_domain > 0:
            confidence += 0.05
            factors.append("Some cross-domain signal")
        else:
            confidence -= 0.05
            factors.append("Single-domain only (lower confidence)")

        # Source diversity
        source_types = set(e.source_subtype.value for e in candidate.events)
        if len(source_types) >= 3:
            confidence += 0.1
            factors.append(f"Diverse sources ({len(source_types)} types)")

        # Spam penalty impact
        if score.spam_penalty > 0.3:
            confidence -= 0.15
            factors.append("Spam patterns detected (reducing confidence)")

        # Single source penalty
        if score.single_source_penalty > 0.3:
            confidence -= 0.1
            factors.append("Single source dominance detected")

        confidence = max(0.1, min(0.95, confidence))
        reasoning = "; ".join(factors) + f". Overall confidence: {confidence:.0%}."

        return round(confidence, 2), reasoning
