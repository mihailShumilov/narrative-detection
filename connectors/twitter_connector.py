"""Twitter/X connector for social signals.

Monitors KOL accounts and keyword queries for Solana narrative signals.
Falls back to Nitter RSS or bundled data if API key unavailable.
"""

from __future__ import annotations

import json
import os
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

# Nitter instances for RSS fallback
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.woodland.cafe",
]


class TwitterConnector(BaseConnector):
    """Connector for Twitter/X social signals."""

    name = "twitter"
    rate_limit_rps = 1.0

    def __init__(self, config: dict, cache_enabled: bool = True):
        super().__init__(config, cache_enabled)
        tw_config = config.get("sources", {}).get("offchain", {}).get("twitter", {})
        self.bearer_token = os.getenv("TWITTER_BEARER_TOKEN", "")
        self.kol_handles = tw_config.get("kol_handles", [])
        self.keyword_queries = tw_config.get("keyword_queries", ["solana"])
        self._nitter_base = None

    def _find_working_nitter(self) -> Optional[str]:
        """Find a working Nitter instance."""
        if self._nitter_base:
            return self._nitter_base
        for instance in NITTER_INSTANCES:
            try:
                resp = self._client.get(f"{instance}/", timeout=5.0)
                if resp.status_code < 400:
                    self._nitter_base = instance
                    return instance
            except Exception:
                continue
        return None

    def _fetch_via_api(self, window_start: datetime) -> list[SignalEvent]:
        """Fetch tweets via official Twitter API v2."""
        events = []
        headers = {"Authorization": f"Bearer {self.bearer_token}"}

        # Search recent tweets for keywords
        for query in self.keyword_queries[:3]:
            try:
                self._rate_limit()
                params = {
                    "query": f"{query} -is:retweet lang:en",
                    "max_results": 20,
                    "tweet.fields": "created_at,public_metrics,author_id,entities",
                    "expansions": "author_id",
                    "user.fields": "username,public_metrics",
                    "start_time": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                response = self._client.get(
                    "https://api.twitter.com/2/tweets/search/recent",
                    headers=headers,
                    params=params,
                )
                if response.status_code == 200:
                    data = response.json()
                    tweets = data.get("data", [])
                    users = {
                        u["id"]: u
                        for u in data.get("includes", {}).get("users", [])
                    }

                    for tweet in tweets:
                        author = users.get(tweet.get("author_id"), {})
                        username = author.get("username", "unknown")
                        followers = author.get("public_metrics", {}).get("followers_count", 0)
                        metrics = tweet.get("public_metrics", {})

                        pub_date = datetime.fromisoformat(
                            tweet["created_at"].replace("Z", "+00:00")
                        )

                        text = tweet.get("text", "")
                        entities = self._extract_entities(text)

                        events.append(
                            SignalEvent(
                                timestamp=pub_date,
                                source_type=SourceType.OFFCHAIN,
                                source_subtype=SourceSubtype.TWITTER,
                                entities=entities,
                                text=f"@{username}: {text}",
                                url=f"https://x.com/{username}/status/{tweet['id']}",
                                metrics={
                                    "likes": metrics.get("like_count", 0),
                                    "retweets": metrics.get("retweet_count", 0),
                                    "replies": metrics.get("reply_count", 0),
                                    "impressions": metrics.get("impression_count", 0),
                                    "followers": followers,
                                },
                                raw_source=f"twitter:search:{query}",
                                author=username,
                                author_followers=followers,
                            )
                        )
                else:
                    logger.warning(
                        "twitter_api_error",
                        status=response.status_code,
                        query=query,
                    )
            except Exception as e:
                logger.warning("twitter_api_failed", query=query, error=str(e))

        return events

    def _fetch_via_nitter(self, window_start: datetime) -> list[SignalEvent]:
        """Fetch tweets via Nitter RSS as fallback."""
        events = []
        nitter_base = self._find_working_nitter()

        if not nitter_base:
            logger.warning("no_nitter_available", reason="All Nitter instances down")
            return []

        # Fetch KOL account feeds
        for handle in self.kol_handles[:15]:
            try:
                self._rate_limit()
                feed_url = f"{nitter_base}/{handle}/rss"
                feed = feedparser.parse(feed_url)

                for entry in feed.entries[:5]:
                    pub_date = self._parse_date(entry)
                    if not pub_date:
                        continue
                    if pub_date.replace(tzinfo=None) < window_start.replace(tzinfo=None):
                        continue

                    title = entry.get("title", "")
                    text = self._clean_html(entry.get("description", title))
                    link = entry.get("link", "")
                    entities = self._extract_entities(text)

                    events.append(
                        SignalEvent(
                            timestamp=pub_date,
                            source_type=SourceType.OFFCHAIN,
                            source_subtype=SourceSubtype.TWITTER,
                            entities=entities,
                            text=f"@{handle}: {text[:500]}",
                            url=link,
                            metrics={"source": "nitter", "handle": handle},
                            raw_source=f"nitter:{handle}",
                            author=handle,
                        )
                    )
            except Exception as e:
                logger.debug("nitter_feed_error", handle=handle, error=str(e))

        return events

    def _parse_date(self, entry) -> Optional[datetime]:
        """Parse date from feed entry."""
        for field in ["published_parsed", "updated_parsed"]:
            if hasattr(entry, field) and getattr(entry, field):
                import time
                ts = time.mktime(getattr(entry, field))
                return datetime.fromtimestamp(ts, tz=timezone.utc)
        for field in ["published", "updated"]:
            if field in entry:
                try:
                    return dateparser.parse(entry[field])
                except Exception:
                    continue
        return None

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags."""
        clean = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", clean).strip()

    def _extract_entities(self, text: str) -> list[str]:
        """Extract entities from tweet text."""
        entities = []
        text_lower = text.lower()

        entity_keywords = {
            "jupiter": ["jupiter", "@jupiterexchange", "jup"],
            "marinade": ["marinade", "msol", "mnde"],
            "jito": ["jito", "jitosol", "@jito_sol"],
            "drift": ["drift", "@driftprotocol"],
            "tensor": ["tensor", "@tensor_hq"],
            "helius": ["helius", "@heaboronin"],
            "orca": ["orca", "@orca_so"],
            "raydium": ["raydium"],
            "metaplex": ["metaplex"],
            "phantom": ["phantom", "@phantom"],
            "compressed-nft": ["cnft", "compressed nft", "state compression"],
            "token-extensions": ["token-2022", "token extensions"],
            "blinks": ["blinks", "solana actions"],
            "depin": ["depin"],
            "solana-mobile": ["solana mobile", "saga"],
            "ai-agents": ["ai agent", "solana ai", "ai x crypto", "deai"],
            "mev": ["mev", "jito tips"],
            "firedancer": ["firedancer", "frankendancer"],
            "grpc": ["grpc", "geyser"],
            "defi": ["defi"],
            "nft": ["nft"],
            "payments": ["solana pay", "payments"],
            "gaming": ["gaming", "gamefi"],
            "dao": ["dao", "governance"],
            "svm": ["svm", "solana virtual machine", "eclipse", "neon"],
            "validator": ["validator", "staking"],
        }

        for entity, keywords in entity_keywords.items():
            for kw in keywords:
                if kw in text_lower:
                    entities.append(entity)
                    break

        return list(set(entities)) if entities else ["solana-ecosystem"]

    def fetch(self, window_start: datetime, window_end: datetime) -> list[SignalEvent]:
        """Fetch Twitter/X signals."""
        cache_key = f"twitter_{window_start.date()}_{window_end.date()}"
        cached = self._get_cached(cache_key)
        if cached:
            return [SignalEvent.from_dict(e) for e in cached]

        events = []
        logger.info("fetching_twitter_data")

        # Try official API first
        if self.bearer_token:
            events = self._fetch_via_api(window_start)
            logger.info("twitter_api_fetch", event_count=len(events))

        # Fall back to Nitter
        if not events:
            events = self._fetch_via_nitter(window_start)
            logger.info("twitter_nitter_fetch", event_count=len(events))

        # Final fallback to snapshot
        if not events:
            logger.warning("twitter_fetch_empty", reason="Loading snapshot fallback")
            events = self._load_snapshot_fallback()

        if events:
            self._set_cached(cache_key, [e.to_dict() for e in events])

        logger.info("twitter_fetch_complete", event_count=len(events))
        return events

    def _load_snapshot_fallback(self) -> list[SignalEvent]:
        """Load bundled snapshot."""
        snapshot_path = Path("data/snapshots/twitter_snapshot.json")
        if snapshot_path.exists():
            data = json.loads(snapshot_path.read_text())
            return [SignalEvent.from_dict(e) for e in data]
        return []
