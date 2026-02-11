"""RSS/Blog feed connector for Solana ecosystem content.

Parses blog posts, news, and reports from key Solana sources.
This is the most reliable offchain connector as it doesn't require API keys.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import feedparser
from dateutil import parser as dateparser

from connectors.base import BaseConnector
from pipeline.models import SignalEvent, SourceType, SourceSubtype
from pipeline.logging import get_logger

logger = get_logger(__name__)

# Default feeds if config is missing
DEFAULT_FEEDS = [
    {"url": "https://solana.com/news/rss.xml", "name": "Solana Foundation", "category": "official"},
    {"url": "https://www.helius.dev/blog/rss.xml", "name": "Helius Blog", "category": "infra"},
    {"url": "https://medium.com/feed/@solana", "name": "Solana Medium", "category": "official"},
    {"url": "https://blog.orca.so/feed", "name": "Orca Blog", "category": "defi"},
    {"url": "https://medium.com/feed/marginfi", "name": "Marginfi Blog", "category": "defi"},
    {"url": "https://medium.com/feed/@drift_labs", "name": "Drift Blog", "category": "defi"},
    {"url": "https://www.jito.network/blog/rss.xml", "name": "Jito Blog", "category": "mev"},
]


class RSSConnector(BaseConnector):
    """Connector for RSS/blog feeds."""

    name = "rss_blogs"
    rate_limit_rps = 2.0

    def __init__(self, config: dict, cache_enabled: bool = True):
        super().__init__(config, cache_enabled)
        rss_config = config.get("sources", {}).get("offchain", {}).get("rss_blogs", {})
        self.feeds = rss_config.get("feeds", DEFAULT_FEEDS)

    def _parse_feed(self, feed_info: dict, window_start: datetime) -> list[SignalEvent]:
        """Parse a single RSS feed into signal events."""
        events = []
        url = feed_info["url"]
        feed_name = feed_info.get("name", url)
        category = feed_info.get("category", "blog")

        try:
            self._rate_limit()
            feed = feedparser.parse(url)

            if feed.bozo and not feed.entries:
                logger.warning("rss_parse_error", feed=feed_name, url=url)
                return []

            for entry in feed.entries[:20]:
                # Parse date
                pub_date = self._parse_entry_date(entry)
                if not pub_date:
                    continue

                # Filter by window
                if pub_date.replace(tzinfo=None) < window_start.replace(tzinfo=None):
                    continue

                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = self._clean_html(entry.get("summary", entry.get("description", "")))[:500]
                author = entry.get("author", feed_name)

                # Extract entities
                text = f"{title} {summary}"
                entities = self._extract_entities(text)

                events.append(
                    SignalEvent(
                        timestamp=pub_date,
                        source_type=SourceType.OFFCHAIN,
                        source_subtype=SourceSubtype.RSS_BLOG,
                        entities=entities,
                        text=f"[{feed_name}] {title}: {summary[:300]}",
                        url=link,
                        metrics={"category": category, "feed": feed_name},
                        raw_source=f"rss:{feed_name}",
                        author=author,
                    )
                )

        except Exception as e:
            logger.warning("rss_feed_error", feed=feed_name, error=str(e))

        return events

    def _parse_entry_date(self, entry: dict) -> Optional[datetime]:
        """Parse date from RSS entry."""
        for field in ["published_parsed", "updated_parsed"]:
            if hasattr(entry, field) and getattr(entry, field):
                import time
                ts = time.mktime(getattr(entry, field))
                return datetime.fromtimestamp(ts, tz=timezone.utc)

        for field in ["published", "updated", "date"]:
            if field in entry and entry[field]:
                try:
                    return dateparser.parse(entry[field])
                except Exception:
                    continue

        return None

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def _extract_entities(self, text: str) -> list[str]:
        """Extract known entities from text."""
        entities = []
        text_lower = text.lower()

        entity_keywords = {
            "jupiter": ["jupiter", "jup aggregator"],
            "marinade": ["marinade", "msol", "mnde"],
            "jito": ["jito", "jitosol", "mev on solana"],
            "drift": ["drift protocol", "drift exchange"],
            "tensor": ["tensor", "nft marketplace"],
            "helius": ["helius", "rpc provider"],
            "orca": ["orca", "whirlpool"],
            "raydium": ["raydium"],
            "metaplex": ["metaplex"],
            "compressed-nft": ["compressed nft", "cnft", "state compression"],
            "token-extensions": ["token-2022", "token extensions", "token22"],
            "blinks": ["blinks", "blockchain links", "solana actions"],
            "depin": ["depin", "decentralized physical infrastructure"],
            "solana-mobile": ["solana mobile", "saga phone", "chapter 2"],
            "ai-agents": ["ai agent", "artificial intelligence", "machine learning", "llm"],
            "mev": ["mev", "maximal extractable value", "sandwich attack"],
            "validator": ["validator", "stake pool", "staking"],
            "svm": ["svm", "solana virtual machine"],
            "firedancer": ["firedancer", "frankendancer", "jump crypto validator"],
            "grpc": ["grpc", "geyser", "yellowstone"],
            "solana-pay": ["solana pay"],
            "nft": ["nft", "digital collectible"],
            "defi": ["defi", "decentralized finance", "lending", "borrowing"],
            "payments": ["payments", "point of sale", "checkout"],
            "gaming": ["gaming", "game", "play to earn"],
            "dao": ["dao", "governance", "multisig"],
        }

        for entity, keywords in entity_keywords.items():
            for kw in keywords:
                if kw in text_lower:
                    entities.append(entity)
                    break

        return list(set(entities)) if entities else ["solana-ecosystem"]

    def fetch(self, window_start: datetime, window_end: datetime) -> list[SignalEvent]:
        """Fetch RSS/blog signals."""
        cache_key = f"rss_{window_start.date()}_{window_end.date()}"
        cached = self._get_cached(cache_key)
        if cached:
            return [SignalEvent.from_dict(e) for e in cached]

        events = []
        logger.info("fetching_rss_data", feed_count=len(self.feeds))

        for feed_info in self.feeds:
            feed_events = self._parse_feed(feed_info, window_start)
            events.extend(feed_events)
            logger.info("rss_feed_parsed", feed=feed_info.get("name", ""), events=len(feed_events))

        if events:
            self._set_cached(cache_key, [e.to_dict() for e in events])
        else:
            logger.warning("rss_fetch_empty", reason="No RSS data, loading snapshot")
            events = self._load_snapshot_fallback()

        logger.info("rss_fetch_complete", event_count=len(events))
        return events

    def _load_snapshot_fallback(self) -> list[SignalEvent]:
        """Load bundled snapshot."""
        snapshot_path = Path("data/snapshots/rss_snapshot.json")
        if snapshot_path.exists():
            data = json.loads(snapshot_path.read_text())
            return [SignalEvent.from_dict(e) for e in data]
        return []
