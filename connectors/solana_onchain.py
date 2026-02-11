"""Solana onchain data connector.

Fetches program deployment activity and transaction metrics from Solana RPC.
Falls back to bundled snapshot data if RPC is unavailable.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from connectors.base import BaseConnector
from pipeline.models import SignalEvent, SourceType, SourceSubtype
from pipeline.logging import get_logger

logger = get_logger(__name__)

# Well-known Solana programs to track for activity spikes
TRACKED_PROGRAMS = {
    "JUP6LkMUJnQhGRh4JMkxkE1V4GtgiueRCnpKk2FNDYQ": "Jupiter v6",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpool",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium AMM",
    "dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH": "Drift Protocol",
    "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA": "Marginfi",
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY": "Phoenix",
    "TCMPhJdwDryooaGtiocG1u3xcYbRpiJzb283XfCZsDp": "Tensor",
    "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "Jito Tip Router",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb": "Token-2022",
    "cmtDvXumGCrqC1Age74AVPhSRVXJMd8PJS91L8KbNCK": "State Compression",
    "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s": "Metaplex Token Metadata",
    "BGUMAp9Gq7iTEuizy4pqaxsTyUCBK68MDfK752saRPUY": "Bubblegum (cNFTs)",
    "11111111111111111111111111111111": "System Program",
    "Vote111111111111111111111111111111111111111": "Vote Program",
}


class SolanaOnchainConnector(BaseConnector):
    """Connector for Solana onchain data via RPC."""

    name = "solana_onchain"
    rate_limit_rps = 3.0

    def __init__(self, config: dict, cache_enabled: bool = True):
        super().__init__(config, cache_enabled)
        rpc_config = config.get("sources", {}).get("onchain", {}).get("solana_rpc", {})
        self.rpc_url = os.getenv("SOLANA_RPC_URL", rpc_config.get("endpoint", "https://api.mainnet-beta.solana.com"))
        self.rate_limit_rps = rpc_config.get("rate_limit_rps", 3.0)

    def _rpc_call(self, method: str, params: list = None) -> dict:
        """Make a Solana RPC call."""
        self._rate_limit()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        try:
            response = self._client.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
            if "error" in result:
                logger.warning("rpc_error", method=method, error=result["error"])
                return {}
            return result.get("result", {})
        except Exception as e:
            logger.warning("rpc_call_failed", method=method, error=str(e))
            return {}

    def _fetch_recent_performance(self) -> list[dict]:
        """Get recent performance samples for tx activity."""
        result = self._rpc_call("getRecentPerformanceSamples", [10])
        return result if isinstance(result, list) else []

    def _fetch_epoch_info(self) -> dict:
        """Get current epoch info."""
        return self._rpc_call("getEpochInfo")

    def _fetch_supply(self) -> dict:
        """Get current SOL supply info."""
        return self._rpc_call("getSupply")

    def _fetch_program_accounts_count(self, program_id: str) -> int:
        """Get number of accounts for a program (proxy for usage)."""
        try:
            result = self._rpc_call(
                "getProgramAccounts",
                [program_id, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}],
            )
            if isinstance(result, list):
                return len(result)
        except Exception:
            pass
        return 0

    def _fetch_slot_leaders(self) -> list[str]:
        """Get recent slot leaders for validator activity."""
        try:
            epoch = self._fetch_epoch_info()
            current_slot = epoch.get("absoluteSlot", 0)
            if current_slot > 0:
                result = self._rpc_call("getSlotLeaders", [current_slot - 10, 10])
                return result if isinstance(result, list) else []
        except Exception:
            pass
        return []

    def fetch(self, window_start: datetime, window_end: datetime) -> list[SignalEvent]:
        """Fetch onchain signals from Solana."""
        cache_key = f"onchain_{window_start.date()}_{window_end.date()}"
        cached = self._get_cached(cache_key)
        if cached:
            return [SignalEvent.from_dict(e) for e in cached]

        events = []
        logger.info("fetching_onchain_data", window_start=window_start.isoformat(), window_end=window_end.isoformat())

        # 1. Get performance metrics
        perf_samples = self._fetch_recent_performance()
        if perf_samples:
            total_txs = sum(s.get("numTransactions", 0) for s in perf_samples)
            avg_tps = total_txs / max(1, sum(s.get("samplePeriodSecs", 60) for s in perf_samples))
            events.append(
                SignalEvent(
                    timestamp=window_end,
                    source_type=SourceType.ONCHAIN,
                    source_subtype=SourceSubtype.TX_ACTIVITY,
                    entities=["solana-network"],
                    text=f"Solana network processing ~{avg_tps:.0f} TPS across recent samples. Total transactions in sample: {total_txs:,}",
                    metrics={
                        "avg_tps": round(avg_tps, 2),
                        "total_txs_sample": total_txs,
                        "sample_count": len(perf_samples),
                    },
                    raw_source="solana_rpc:getRecentPerformanceSamples",
                )
            )

        # 2. Get epoch info
        epoch_info = self._fetch_epoch_info()
        if epoch_info:
            epoch = epoch_info.get("epoch", 0)
            slot_index = epoch_info.get("slotIndex", 0)
            slots_in_epoch = epoch_info.get("slotsInEpoch", 0)
            progress = (slot_index / max(1, slots_in_epoch)) * 100
            events.append(
                SignalEvent(
                    timestamp=window_end,
                    source_type=SourceType.ONCHAIN,
                    source_subtype=SourceSubtype.TX_ACTIVITY,
                    entities=["solana-network", "validators"],
                    text=f"Solana epoch {epoch} is {progress:.1f}% complete. Slot {epoch_info.get('absoluteSlot', 0):,}.",
                    metrics={
                        "epoch": epoch,
                        "epoch_progress_pct": round(progress, 1),
                        "absolute_slot": epoch_info.get("absoluteSlot", 0),
                    },
                    raw_source="solana_rpc:getEpochInfo",
                )
            )

        # 3. Probe known programs for activity signals
        for program_id, program_name in list(TRACKED_PROGRAMS.items())[:8]:
            # We use a lightweight heuristic: getBalance on the program address
            # to see if it exists and is active, combined with known ecosystem info
            try:
                result = self._rpc_call("getBalance", [program_id])
                if result and isinstance(result, dict):
                    balance = result.get("value", 0)
                    events.append(
                        SignalEvent(
                            timestamp=window_end,
                            source_type=SourceType.ONCHAIN,
                            source_subtype=SourceSubtype.PROGRAM_DEPLOY,
                            entities=[program_name.lower().replace(" ", "-")],
                            text=f"Program '{program_name}' ({program_id[:8]}...) is active on mainnet with balance {balance / 1e9:.4f} SOL.",
                            metrics={"balance_lamports": balance, "balance_sol": balance / 1e9},
                            url=f"https://solscan.io/account/{program_id}",
                            raw_source=f"solana_rpc:getBalance:{program_id[:8]}",
                        )
                    )
            except Exception as e:
                logger.debug("program_probe_failed", program=program_name, error=str(e))

        # 4. Supply metrics
        supply = self._fetch_supply()
        if supply and isinstance(supply, dict) and "value" in supply:
            val = supply["value"]
            total = val.get("total", 0) / 1e9
            circulating = val.get("circulating", 0) / 1e9
            events.append(
                SignalEvent(
                    timestamp=window_end,
                    source_type=SourceType.ONCHAIN,
                    source_subtype=SourceSubtype.TOKEN_ACTIVITY,
                    entities=["sol", "solana-network"],
                    text=f"SOL supply: {total:,.0f} total, {circulating:,.0f} circulating ({circulating/max(1,total)*100:.1f}% circulating).",
                    metrics={
                        "total_supply_sol": round(total, 2),
                        "circulating_supply_sol": round(circulating, 2),
                        "circulating_pct": round(circulating / max(1, total) * 100, 2),
                    },
                    raw_source="solana_rpc:getSupply",
                )
            )

        if events:
            self._set_cached(cache_key, [e.to_dict() for e in events])
            logger.info("onchain_fetch_complete", event_count=len(events))
        else:
            logger.warning("onchain_fetch_empty", reason="No data from RPC, will use snapshot fallback")
            events = self._load_snapshot_fallback(window_start, window_end)

        return events

    def _load_snapshot_fallback(self, window_start: datetime, window_end: datetime) -> list[SignalEvent]:
        """Load bundled snapshot data as fallback."""
        snapshot_path = Path("data/snapshots/onchain_snapshot.json")
        if snapshot_path.exists():
            data = json.loads(snapshot_path.read_text())
            logger.info("loaded_snapshot_fallback", source="onchain", count=len(data))
            return [SignalEvent.from_dict(e) for e in data]
        return []
