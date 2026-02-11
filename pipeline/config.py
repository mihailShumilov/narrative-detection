"""Configuration loader with environment variable support."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


load_dotenv()

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "default.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration from YAML file, with env var overrides."""
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Override with environment variables
    if os.getenv("SOLANA_RPC_URL"):
        config["sources"]["onchain"]["solana_rpc"]["endpoint"] = os.getenv(
            "SOLANA_RPC_URL"
        )

    if os.getenv("HELIUS_API_KEY"):
        config["sources"]["onchain"]["helius"]["enabled"] = True

    if os.getenv("GITHUB_TOKEN"):
        config["sources"]["offchain"]["github"]["enabled"] = True

    if os.getenv("TWITTER_BEARER_TOKEN"):
        config["sources"]["offchain"]["twitter"]["enabled"] = True

    return config


def get_scoring_weights(config: dict) -> dict[str, float]:
    """Extract scoring weights from config."""
    return config["scoring"]["weights"]


def get_scoring_penalties(config: dict) -> dict[str, float]:
    """Extract scoring penalties from config."""
    return config["scoring"]["penalties"]


def get_entity_aliases(config: dict) -> dict[str, list[str]]:
    """Get entity alias mapping."""
    return config.get("entity_aliases", {})
