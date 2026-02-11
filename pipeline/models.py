"""Core data models for the narrative detection pipeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SourceType(str, Enum):
    ONCHAIN = "onchain"
    OFFCHAIN = "offchain"


class SourceSubtype(str, Enum):
    # Onchain
    PROGRAM_DEPLOY = "program_deploy"
    TX_ACTIVITY = "tx_activity"
    TOKEN_ACTIVITY = "token_activity"
    # Offchain
    GITHUB = "github"
    TWITTER = "twitter"
    RSS_BLOG = "rss_blog"
    FORUM = "forum"


@dataclass
class SignalEvent:
    """A normalized event from any data source."""

    timestamp: datetime
    source_type: SourceType
    source_subtype: SourceSubtype
    entities: list[str]  # canonical entity names
    text: str  # description or snippet
    url: Optional[str] = None
    metrics: dict = field(default_factory=dict)  # quantitative data
    raw_source: str = ""  # original source identifier
    author: str = ""
    author_followers: int = 0
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        content = f"{self.source_subtype}:{self.text[:200]}:{','.join(sorted(self.entities))}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        d["source_type"] = self.source_type.value
        d["source_subtype"] = self.source_subtype.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> SignalEvent:
        d = d.copy()
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        d["source_type"] = SourceType(d["source_type"])
        d["source_subtype"] = SourceSubtype(d["source_subtype"])
        return cls(**d)


@dataclass
class NarrativeCandidate:
    """A candidate narrative detected from clustering."""

    id: str
    label: str
    description: str
    events: list[SignalEvent] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    cluster_keywords: list[str] = field(default_factory=list)


@dataclass
class EvidenceCard:
    """A piece of evidence supporting a narrative."""

    event: SignalEvent
    relevance_score: float
    summary: str
    metric_highlight: Optional[str] = None


@dataclass
class BuildIdea:
    """A concrete product/build idea tied to a narrative."""

    title: str
    problem_statement: str
    target_user: str
    why_solana: str
    mvp_scope: str
    risks_unknowns: str
    validation_approach: str
    category: str  # infra, devtool, analytics, consumer, protocol
    evidence_links: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of a narrative's composite score."""

    velocity: float = 0.0
    breadth: float = 0.0
    cross_domain: float = 0.0
    novelty: float = 0.0
    credibility: float = 0.0
    spam_penalty: float = 0.0
    single_source_penalty: float = 0.0
    composite: float = 0.0
    feature_contributions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RankedNarrative:
    """A fully scored and ranked narrative with all artifacts."""

    rank: int
    narrative_id: str
    label: str
    explanation: str
    why_now: str
    score: ScoreBreakdown
    confidence: float  # 0-1
    confidence_reasoning: str
    evidence_cards: list[EvidenceCard] = field(default_factory=list)
    build_ideas: list[BuildIdea] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    timeline_data: list[dict] = field(default_factory=list)  # for charts

    def to_dict(self) -> dict:
        d = {
            "rank": self.rank,
            "narrative_id": self.narrative_id,
            "label": self.label,
            "explanation": self.explanation,
            "why_now": self.why_now,
            "score": self.score.to_dict(),
            "confidence": self.confidence,
            "confidence_reasoning": self.confidence_reasoning,
            "evidence_cards": [
                {
                    "summary": ec.summary,
                    "relevance_score": ec.relevance_score,
                    "metric_highlight": ec.metric_highlight,
                    "event": ec.event.to_dict(),
                }
                for ec in self.evidence_cards
            ],
            "build_ideas": [bi.to_dict() for bi in self.build_ideas],
            "entities": self.entities,
            "timeline_data": self.timeline_data,
        }
        return d


@dataclass
class FortnightlyReport:
    """Complete output of a fortnightly analysis run."""

    run_id: str
    window_start: datetime
    window_end: datetime
    baseline_start: datetime
    generated_at: datetime
    narratives: list[RankedNarrative] = field(default_factory=list)
    methodology: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "baseline_start": self.baseline_start.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "narratives": [n.to_dict() for n in self.narratives],
            "methodology": self.methodology,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)
