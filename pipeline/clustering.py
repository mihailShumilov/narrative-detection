"""Narrative candidate generation via entity co-occurrence and text clustering.

Stage D of the pipeline: identify candidate narratives from signal events.
Uses entity co-occurrence graphs and TF-IDF text clustering.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from itertools import combinations
from typing import Optional

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from pipeline.models import SignalEvent, NarrativeCandidate
from pipeline.logging import get_logger

logger = get_logger(__name__)

# Stop words for Solana narrative context
NARRATIVE_STOP_WORDS = {
    "solana", "sol", "crypto", "blockchain", "web3", "the", "and", "for",
    "with", "that", "this", "from", "https", "http", "com", "www",
    "just", "like", "new", "now", "get", "use", "make", "will", "can",
    "one", "also", "more", "been", "have", "has", "had", "about", "into",
    "than", "its", "out", "over", "all", "are", "but", "not", "you",
    "was", "they", "their", "what", "which", "when", "would", "there",
}


class NarrativeClusterer:
    """Identifies candidate narratives from signal events."""

    def __init__(self, config: dict):
        self.config = config
        self.min_cluster_size = 3
        self.max_clusters = config.get("analysis", {}).get("max_narratives", 10) + 5

    def generate_candidates(self, events: list[SignalEvent]) -> list[NarrativeCandidate]:
        """Main entry: generate narrative candidates from events."""
        if len(events) < 3:
            logger.warning("too_few_events", count=len(events))
            return self._single_cluster_fallback(events)

        # Step 1: Entity co-occurrence analysis
        entity_clusters = self._entity_cooccurrence_clusters(events)

        # Step 2: Text-based clustering
        text_clusters = self._text_clusters(events)

        # Step 3: Merge clusters
        candidates = self._merge_clusters(entity_clusters, text_clusters, events)

        # Step 4: Generate labels and descriptions
        candidates = self._enrich_candidates(candidates)

        logger.info("candidates_generated", count=len(candidates))
        return candidates

    def _entity_cooccurrence_clusters(
        self, events: list[SignalEvent]
    ) -> list[set[str]]:
        """Build entity co-occurrence graph and extract clusters."""
        # Count co-occurrences
        cooccurrence = Counter()
        entity_counts = Counter()

        for event in events:
            entities = [e for e in event.entities if e != "solana-ecosystem"]
            for entity in entities:
                entity_counts[entity] += 1
            for pair in combinations(sorted(set(entities)), 2):
                cooccurrence[pair] += 1

        # Build adjacency with min threshold
        min_cooccurrence = 2
        adjacency = defaultdict(set)
        for (a, b), count in cooccurrence.items():
            if count >= min_cooccurrence:
                adjacency[a].add(b)
                adjacency[b].add(a)

        # Connected components via BFS
        visited = set()
        clusters = []
        for entity in adjacency:
            if entity in visited:
                continue
            cluster = set()
            queue = [entity]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                cluster.add(node)
                for neighbor in adjacency[node]:
                    if neighbor not in visited:
                        queue.append(neighbor)
            if len(cluster) >= 1:
                clusters.append(cluster)

        # Add standalone entities with enough mentions
        min_standalone_mentions = 3
        for entity, count in entity_counts.items():
            if entity not in visited and count >= min_standalone_mentions:
                clusters.append({entity})

        logger.info(
            "entity_clusters",
            cluster_count=len(clusters),
            total_entities=len(entity_counts),
        )
        return clusters

    def _text_clusters(self, events: list[SignalEvent]) -> list[list[int]]:
        """Cluster events by text similarity using TF-IDF."""
        texts = [self._preprocess_text(e.text) for e in events]

        if len(texts) < 3:
            return [list(range(len(texts)))]

        # TF-IDF vectorization
        vectorizer = TfidfVectorizer(
            max_features=500,
            stop_words=list(NARRATIVE_STOP_WORDS),
            min_df=2,
            max_df=0.8,
            ngram_range=(1, 2),
        )

        try:
            tfidf_matrix = vectorizer.fit_transform(texts)
        except ValueError:
            # Not enough terms after filtering
            return [list(range(len(texts)))]

        # Compute similarity matrix
        sim_matrix = cosine_similarity(tfidf_matrix)
        distance_matrix = 1 - np.clip(sim_matrix, 0, 1)
        np.fill_diagonal(distance_matrix, 0)

        # Agglomerative clustering
        n_clusters = min(self.max_clusters, max(2, len(events) // 5))
        try:
            clustering = AgglomerativeClustering(
                n_clusters=n_clusters,
                metric="precomputed",
                linkage="average",
            )
            labels = clustering.fit_predict(distance_matrix)
        except Exception as e:
            logger.warning("clustering_failed", error=str(e))
            return [list(range(len(events)))]

        # Group by cluster label
        cluster_indices = defaultdict(list)
        for idx, label in enumerate(labels):
            cluster_indices[label].append(idx)

        result = [indices for indices in cluster_indices.values() if len(indices) >= 2]
        logger.info("text_clusters", cluster_count=len(result))
        return result

    def _preprocess_text(self, text: str) -> str:
        """Preprocess text for clustering."""
        text = text.lower()
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"@\w+", "", text)
        text = re.sub(r"[^a-z0-9\s\-]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _merge_clusters(
        self,
        entity_clusters: list[set[str]],
        text_cluster_indices: list[list[int]],
        events: list[SignalEvent],
    ) -> list[NarrativeCandidate]:
        """Merge entity-based and text-based clusters into narrative candidates."""
        candidates = []
        used_event_indices = set()

        # Priority 1: Entity-based clusters (stronger signal)
        for i, entity_set in enumerate(entity_clusters):
            matching_events = []
            for idx, event in enumerate(events):
                if entity_set.intersection(set(event.entities)):
                    matching_events.append(event)
                    used_event_indices.add(idx)

            if len(matching_events) >= self.min_cluster_size:
                candidate = NarrativeCandidate(
                    id=f"entity_{i}",
                    label="",
                    description="",
                    events=matching_events,
                    entities=sorted(entity_set),
                )
                candidates.append(candidate)

        # Priority 2: Text clusters for uncovered events
        for i, indices in enumerate(text_cluster_indices):
            remaining_indices = [idx for idx in indices if idx not in used_event_indices]
            if len(remaining_indices) >= self.min_cluster_size:
                cluster_events = [events[idx] for idx in remaining_indices]
                all_entities = set()
                for event in cluster_events:
                    all_entities.update(event.entities)

                # Check if this overlaps significantly with an existing candidate
                merged = False
                for candidate in candidates:
                    overlap = all_entities.intersection(set(candidate.entities))
                    if len(overlap) >= len(all_entities) * 0.5:
                        candidate.events.extend(cluster_events)
                        candidate.entities = sorted(
                            set(candidate.entities) | all_entities
                        )
                        merged = True
                        break

                if not merged:
                    candidate = NarrativeCandidate(
                        id=f"text_{i}",
                        label="",
                        description="",
                        events=cluster_events,
                        entities=sorted(all_entities - {"solana-ecosystem"}),
                    )
                    candidates.append(candidate)

        # Sort by event count
        candidates.sort(key=lambda c: len(c.events), reverse=True)
        return candidates[: self.max_clusters]

    def _enrich_candidates(
        self, candidates: list[NarrativeCandidate]
    ) -> list[NarrativeCandidate]:
        """Generate labels and descriptions for candidates."""
        for candidate in candidates:
            # Extract keywords from event texts
            keywords = self._extract_keywords(candidate.events)
            candidate.cluster_keywords = keywords[:10]

            # Generate label from top entities and keywords
            if candidate.entities:
                primary_entities = candidate.entities[:3]
                candidate.label = self._generate_label(primary_entities, keywords)
            else:
                candidate.label = " + ".join(keywords[:3]).title()

            # Generate description
            candidate.description = self._generate_description(candidate)

        return candidates

    def _extract_keywords(self, events: list[SignalEvent]) -> list[str]:
        """Extract top keywords from event texts."""
        texts = [self._preprocess_text(e.text) for e in events]
        combined = " ".join(texts)
        words = combined.split()

        # Filter stop words and short words
        filtered = [
            w for w in words
            if w not in NARRATIVE_STOP_WORDS and len(w) > 2
        ]

        # Count and rank
        counter = Counter(filtered)
        return [word for word, _ in counter.most_common(20)]

    def _generate_label(self, entities: list[str], keywords: list[str]) -> str:
        """Generate a human-readable narrative label."""
        label_parts = []

        # Category mapping for better labels
        category_labels = {
            "defi": "DeFi",
            "nft": "NFT",
            "depin": "DePIN",
            "ai-agents": "AI Agents",
            "mev": "MEV",
            "svm": "SVM Expansion",
            "firedancer": "Firedancer",
            "compressed-nft": "Compressed NFTs",
            "token-extensions": "Token Extensions",
            "blinks": "Blinks & Actions",
            "solana-mobile": "Solana Mobile",
            "gaming": "Gaming",
            "dao": "DAOs & Governance",
            "validator": "Validator Infrastructure",
            "payments": "Payments",
            "grpc": "Data Infrastructure",
        }

        for entity in entities[:2]:
            label_parts.append(category_labels.get(entity, entity.replace("-", " ").title()))

        if not label_parts:
            label_parts = [kw.title() for kw in keywords[:2]]

        return " & ".join(label_parts) if label_parts else "Emerging Signal"

    def _generate_description(self, candidate: NarrativeCandidate) -> str:
        """Generate narrative description from events."""
        source_types = Counter(e.source_subtype.value for e in candidate.events)
        entity_mentions = Counter()
        for e in candidate.events:
            for ent in e.entities:
                entity_mentions[ent] += 1

        top_entities = [e for e, _ in entity_mentions.most_common(5)]
        source_summary = ", ".join(f"{st}({c})" for st, c in source_types.most_common())

        desc = (
            f"Narrative cluster around {', '.join(top_entities[:3])} "
            f"with {len(candidate.events)} signal events "
            f"from sources: {source_summary}."
        )
        return desc

    def _single_cluster_fallback(self, events: list[SignalEvent]) -> list[NarrativeCandidate]:
        """Fallback when too few events for clustering."""
        if not events:
            return []
        all_entities = set()
        for e in events:
            all_entities.update(e.entities)
        return [
            NarrativeCandidate(
                id="fallback_0",
                label="Solana Ecosystem Activity",
                description=f"General ecosystem signals ({len(events)} events)",
                events=events,
                entities=sorted(all_entities),
            )
        ]
