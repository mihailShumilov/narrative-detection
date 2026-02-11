"""GitHub connector for developer activity signals.

Monitors Solana-related repositories for:
- New repo creation
- Star velocity
- Commit activity
- Release activity
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from connectors.base import BaseConnector
from pipeline.models import SignalEvent, SourceType, SourceSubtype
from pipeline.logging import get_logger

logger = get_logger(__name__)


class GitHubConnector(BaseConnector):
    """Connector for GitHub developer activity."""

    name = "github"
    rate_limit_rps = 8.0

    def __init__(self, config: dict, cache_enabled: bool = True):
        super().__init__(config, cache_enabled)
        gh_config = config.get("sources", {}).get("offchain", {}).get("github", {})
        self.token = os.getenv("GITHUB_TOKEN", "")
        self.search_queries = gh_config.get("search_queries", ["solana"])
        self.orgs = gh_config.get("orgs", ["solana-labs"])
        self.rate_limit_rps = gh_config.get("rate_limit_rps", 8.0)

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    def _search_repos(self, query: str, sort: str = "updated", per_page: int = 30) -> list[dict]:
        """Search GitHub repos."""
        try:
            response = self._fetch_url(
                "https://api.github.com/search/repositories",
                headers=self._headers(),
                params={"q": query, "sort": sort, "order": "desc", "per_page": per_page},
            )
            return response.json().get("items", [])
        except Exception as e:
            logger.warning("github_search_failed", query=query, error=str(e))
            return []

    def _get_org_repos(self, org: str, per_page: int = 30) -> list[dict]:
        """Get repos from an organization."""
        try:
            response = self._fetch_url(
                f"https://api.github.com/orgs/{org}/repos",
                headers=self._headers(),
                params={"sort": "updated", "direction": "desc", "per_page": per_page},
            )
            return response.json() if isinstance(response.json(), list) else []
        except Exception as e:
            logger.warning("github_org_fetch_failed", org=org, error=str(e))
            return []

    def _get_repo_commits(self, owner: str, repo: str, since: str, per_page: int = 30) -> list[dict]:
        """Get recent commits for a repo."""
        try:
            response = self._fetch_url(
                f"https://api.github.com/repos/{owner}/{repo}/commits",
                headers=self._headers(),
                params={"since": since, "per_page": per_page},
            )
            return response.json() if isinstance(response.json(), list) else []
        except Exception as e:
            logger.debug("github_commits_failed", repo=f"{owner}/{repo}", error=str(e))
            return []

    def _get_repo_releases(self, owner: str, repo: str, per_page: int = 10) -> list[dict]:
        """Get recent releases for a repo."""
        try:
            response = self._fetch_url(
                f"https://api.github.com/repos/{owner}/{repo}/releases",
                headers=self._headers(),
                params={"per_page": per_page},
            )
            return response.json() if isinstance(response.json(), list) else []
        except Exception as e:
            logger.debug("github_releases_failed", repo=f"{owner}/{repo}", error=str(e))
            return []

    def fetch(self, window_start: datetime, window_end: datetime) -> list[SignalEvent]:
        """Fetch GitHub activity signals."""
        cache_key = f"github_{window_start.date()}_{window_end.date()}"
        cached = self._get_cached(cache_key)
        if cached:
            return [SignalEvent.from_dict(e) for e in cached]

        events = []
        logger.info("fetching_github_data", window_start=window_start.isoformat())

        # 1. Search for recently updated/created Solana repos
        for query in self.search_queries[:4]:  # Limit queries to avoid rate limiting
            full_query = f"{query} pushed:>{window_start.strftime('%Y-%m-%d')}"
            repos = self._search_repos(full_query, per_page=15)

            for repo in repos:
                created_at = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
                updated_at = datetime.fromisoformat(repo["updated_at"].replace("Z", "+00:00"))
                stars = repo.get("stargazers_count", 0)
                forks = repo.get("forks_count", 0)
                name = repo.get("full_name", "")
                desc = repo.get("description", "") or ""
                language = repo.get("language", "unknown")

                # Extract entities from repo name and description
                entities = self._extract_entities(name, desc)

                # New repo creation signal
                if created_at >= window_start.replace(tzinfo=timezone.utc):
                    events.append(
                        SignalEvent(
                            timestamp=created_at,
                            source_type=SourceType.OFFCHAIN,
                            source_subtype=SourceSubtype.GITHUB,
                            entities=entities,
                            text=f"New Solana repo created: {name} - {desc[:200]}. Language: {language}.",
                            url=repo.get("html_url", ""),
                            metrics={
                                "stars": stars,
                                "forks": forks,
                                "language": language,
                                "is_new": True,
                            },
                            raw_source=f"github:search:{query}",
                            author=repo.get("owner", {}).get("login", ""),
                        )
                    )
                elif stars > 10:
                    events.append(
                        SignalEvent(
                            timestamp=updated_at,
                            source_type=SourceType.OFFCHAIN,
                            source_subtype=SourceSubtype.GITHUB,
                            entities=entities,
                            text=f"Active Solana repo: {name} ({stars} stars, {forks} forks) - {desc[:200]}. Language: {language}.",
                            url=repo.get("html_url", ""),
                            metrics={
                                "stars": stars,
                                "forks": forks,
                                "language": language,
                                "is_new": False,
                            },
                            raw_source=f"github:search:{query}",
                            author=repo.get("owner", {}).get("login", ""),
                        )
                    )

        # 2. Check key orgs for activity
        for org in self.orgs[:6]:  # Limit to avoid rate limiting
            repos = self._get_org_repos(org, per_page=10)
            for repo in repos:
                updated_at_str = repo.get("updated_at", "")
                if not updated_at_str:
                    continue
                updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                if updated_at < window_start.replace(tzinfo=timezone.utc):
                    continue

                name = repo.get("full_name", "")
                desc = repo.get("description", "") or ""
                stars = repo.get("stargazers_count", 0)

                # Check for releases
                owner_name = repo.get("owner", {}).get("login", org)
                repo_name = repo.get("name", "")
                releases = self._get_repo_releases(owner_name, repo_name, per_page=3)

                for release in releases:
                    pub_date_str = release.get("published_at", "")
                    if not pub_date_str:
                        continue
                    pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                    if pub_date >= window_start.replace(tzinfo=timezone.utc):
                        tag = release.get("tag_name", "")
                        release_name = release.get("name", tag)
                        body = (release.get("body", "") or "")[:300]
                        entities = self._extract_entities(name, f"{release_name} {body}")

                        events.append(
                            SignalEvent(
                                timestamp=pub_date,
                                source_type=SourceType.OFFCHAIN,
                                source_subtype=SourceSubtype.GITHUB,
                                entities=entities,
                                text=f"New release for {name}: {release_name} ({tag}). {body}",
                                url=release.get("html_url", ""),
                                metrics={
                                    "stars": stars,
                                    "is_release": True,
                                    "tag": tag,
                                },
                                raw_source=f"github:release:{name}",
                                author=release.get("author", {}).get("login", ""),
                            )
                        )

        if events:
            self._set_cached(cache_key, [e.to_dict() for e in events])
        else:
            logger.warning("github_fetch_empty", reason="No GitHub data, loading snapshot")
            events = self._load_snapshot_fallback()

        logger.info("github_fetch_complete", event_count=len(events))
        return events

    def _extract_entities(self, name: str, description: str) -> list[str]:
        """Extract entity names from repo info."""
        entities = []
        text = f"{name} {description}".lower()

        known_entities = {
            "anchor": ["anchor"],
            "metaplex": ["metaplex"],
            "jupiter": ["jupiter", "jup"],
            "marinade": ["marinade", "msol"],
            "jito": ["jito"],
            "drift": ["drift"],
            "tensor": ["tensor"],
            "helius": ["helius"],
            "orca": ["orca", "whirlpool"],
            "raydium": ["raydium"],
            "phantom": ["phantom"],
            "squads": ["squads"],
            "helium": ["helium", "hnt"],
            "compressed-nft": ["compressed nft", "cnft", "state compression", "bubblegum"],
            "token-extensions": ["token-2022", "token extensions", "token22"],
            "blinks": ["blinks", "solana actions"],
            "solana-mobile": ["solana mobile", "saga"],
            "solana-pay": ["solana pay"],
            "depin": ["depin", "decentralized physical"],
            "ai-agents": ["ai agent", "solana ai", "ai crypto"],
            "mev": ["mev", "sandwich", "jito tip"],
            "validator": ["validator", "stake pool"],
            "svm": ["svm", "solana virtual machine", "neon evm", "eclipse"],
        }

        for entity, keywords in known_entities.items():
            for kw in keywords:
                if kw in text:
                    entities.append(entity)
                    break

        # Also add the org/repo name
        if "/" in name:
            org = name.split("/")[0].lower()
            entities.append(org)

        return list(set(entities)) if entities else ["solana-ecosystem"]

    def _load_snapshot_fallback(self) -> list[SignalEvent]:
        """Load bundled snapshot."""
        snapshot_path = Path("data/snapshots/github_snapshot.json")
        if snapshot_path.exists():
            data = json.loads(snapshot_path.read_text())
            return [SignalEvent.from_dict(e) for e in data]
        return []
