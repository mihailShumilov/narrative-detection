"""Build idea generator for detected narratives.

Stage G of the pipeline: generate 3-5 concrete, grounded build ideas per narrative.
Each idea ties back to specific evidence and includes MVP scope.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from pipeline.models import (
    NarrativeCandidate,
    ScoreBreakdown,
    BuildIdea,
    EvidenceCard,
)
from pipeline.logging import get_logger

logger = get_logger(__name__)

# Template library of build idea patterns organized by narrative theme
IDEA_TEMPLATES = {
    "defi": [
        {
            "title": "Real-Time DeFi Risk Dashboard",
            "problem": "DeFi users lack real-time visibility into protocol risk factors (utilization, oracle health, liquidation risk) across Solana lending markets.",
            "target": "DeFi power users, risk managers, fund operators",
            "why_solana": "Solana's sub-second finality enables true real-time risk monitoring that's impractical on slower chains. High DeFi TVL makes risk tooling critical.",
            "mvp": "Dashboard pulling live data from top 3 Solana lending protocols (Marginfi, Drift, Kamino) showing utilization rates, health factors, and liquidation thresholds with alerts.",
            "risks": "Protocol API changes; data accuracy vs on-chain state lag. Validate by comparing dashboard data against protocol UIs for 48 hours.",
            "category": "analytics",
        },
        {
            "title": "Cross-Protocol Yield Optimizer",
            "problem": "Yield farmers manually compare rates across Solana DeFi protocols, missing optimal allocation strategies and rebalancing timing.",
            "target": "Yield farmers, treasury managers, DeFi protocols seeking TVL",
            "why_solana": "Solana's low tx costs make frequent rebalancing economically viable. Composability across Solana DeFi enables complex strategies.",
            "mvp": "Bot that monitors yields across top 5 Solana DeFi protocols, suggests optimal allocation, and executes rebalancing via Jupiter.",
            "risks": "Smart contract risk in composing protocols; impermanent loss. Validate with paper trading for 2 weeks before real funds.",
            "category": "protocol",
        },
        {
            "title": "DeFi Protocol Health Monitor SDK",
            "problem": "DeFi integrators and aggregators need programmatic access to protocol health metrics but each protocol has different interfaces.",
            "target": "DeFi developers, aggregator builders, analytics platforms",
            "why_solana": "Solana's account model allows efficient multi-protocol data reads. Growing DeFi ecosystem needs standardized health APIs.",
            "mvp": "Rust/TS SDK that provides unified health metrics (TVL, utilization, oracle freshness) for top 5 Solana DeFi protocols.",
            "risks": "Protocol-specific edge cases; maintenance burden. Validate by integrating with one aggregator and measuring developer adoption.",
            "category": "developer_tooling",
        },
    ],
    "ai-agents": [
        {
            "title": "Solana AI Agent Framework",
            "problem": "AI agents lack standardized tooling to interact with Solana programs, requiring custom integration for each protocol.",
            "target": "AI developers, autonomous agent builders, DeFi protocol teams",
            "why_solana": "Solana's fast finality and low fees make it the ideal execution layer for AI agents that need rapid onchain actions.",
            "mvp": "TypeScript SDK with pre-built Solana tools (swap, transfer, stake) that plug into LangChain/AutoGPT agent frameworks.",
            "risks": "Agent reliability for financial transactions; guardrail design. Validate with constrained test agent on devnet with spend limits.",
            "category": "developer_tooling",
        },
        {
            "title": "Onchain AI Agent Registry & Reputation",
            "problem": "No standard way to verify, track, or rate autonomous AI agents operating on Solana, creating trust issues.",
            "target": "Agent deployers, DeFi users interacting with agents, protocol DAOs",
            "why_solana": "Solana's state compression enables cost-effective onchain attestation. Agent activity is already growing on Solana DeFi.",
            "mvp": "Solana program for registering AI agents with metadata (owner, capabilities, limits) plus a simple explorer UI showing agent activity.",
            "risks": "Defining useful reputation metrics; gaming resistance. Validate by registering 10 known agents and gathering user feedback.",
            "category": "infrastructure",
        },
        {
            "title": "AI-Powered Solana Transaction Explainer",
            "problem": "Solana transactions are opaque to most users — complex program invocations, CPIs, and token movements are hard to understand.",
            "target": "Solana users, developers debugging transactions, compliance teams",
            "why_solana": "Solana's complex instruction model (inner instructions, CPIs) makes transaction interpretation especially challenging and valuable.",
            "mvp": "API that takes a Solana transaction signature, parses all instructions and token transfers, and returns a natural language explanation.",
            "risks": "Accuracy of explanations for novel programs; LLM hallucination. Validate against 100 hand-labeled transactions.",
            "category": "analytics",
        },
    ],
    "compressed-nft": [
        {
            "title": "cNFT Analytics & Indexer",
            "problem": "Compressed NFTs on Solana lack the analytics tooling that traditional NFTs have, making it hard to track collections and activity.",
            "target": "NFT creators, marketplaces, collectors, games using cNFTs",
            "why_solana": "Solana's state compression is unique — cNFTs can be 1000x cheaper to mint, but need specialized indexing infrastructure.",
            "mvp": "Indexer service tracking cNFT mints, transfers, and collection stats via Bubblegum program, with a simple API and dashboard.",
            "risks": "Merkle tree parsing complexity; keeping up with compression tree updates. Validate by indexing top 5 cNFT collections.",
            "category": "infrastructure",
        },
        {
            "title": "cNFT Loyalty & Membership Platform",
            "problem": "Brands want to issue loyalty/membership tokens cheaply at scale but traditional NFT minting costs are prohibitive for millions of users.",
            "target": "Consumer brands, loyalty programs, event organizers",
            "why_solana": "State compression reduces minting cost from ~$2 to $0.001 per NFT, making million-user loyalty programs economically viable.",
            "mvp": "No-code platform where brands create cNFT-based loyalty collections with a claim page, simple points/tier logic, and Shopify plugin.",
            "risks": "Wallet onboarding friction; brand education. Validate with one pilot brand and 1000 claimed tokens.",
            "category": "consumer_app",
        },
    ],
    "token-extensions": [
        {
            "title": "Token Extensions Compliance Toolkit",
            "problem": "Regulated token issuers need transfer hooks, confidential transfers, and metadata extensions but lack turnkey tooling.",
            "target": "Token issuers, compliance teams, RWA platforms",
            "why_solana": "Token-2022 extensions (transfer hooks, confidential transfers) are unique Solana primitives enabling compliant tokenization.",
            "mvp": "CLI + dashboard for creating Token-2022 tokens with transfer restrictions, KYC hooks, and confidential transfer support.",
            "risks": "Regulatory uncertainty on specific configurations; audit requirements. Validate by tokenizing a test RWA with a compliant partner.",
            "category": "developer_tooling",
        },
        {
            "title": "Token-2022 Migration Assistant",
            "problem": "Projects on legacy SPL Token want to migrate to Token-2022 for new features but the migration path is complex.",
            "target": "Token project teams, DAOs considering migration",
            "why_solana": "Token-2022 adoption is accelerating but migration tooling is scarce, creating a bottleneck for ecosystem-wide feature adoption.",
            "mvp": "Guided tool that analyzes a project's current SPL token setup, recommends Token-2022 extensions, and generates migration plan.",
            "risks": "Migration complexity varies by project; liquidity fragmentation during migration. Validate with 3 test migrations on devnet.",
            "category": "developer_tooling",
        },
    ],
    "blinks": [
        {
            "title": "Blinks Commerce Toolkit",
            "problem": "Merchants can't easily create Solana Actions/Blinks for payments, tipping, or product sales without custom development.",
            "target": "Online merchants, content creators, freelancers",
            "why_solana": "Blinks turn any URL into a transaction endpoint — unique to Solana. Low fees make micropayments viable.",
            "mvp": "No-code builder for creating payment Blinks: paste product info, set price, get a shareable URL that triggers Solana Pay.",
            "risks": "Wallet compatibility; user education on Blinks. Validate by creating 10 merchant Blinks and measuring conversion.",
            "category": "consumer_app",
        },
    ],
    "mev": [
        {
            "title": "MEV Protection Relay for Solana",
            "problem": "Solana users lose value to sandwich attacks and MEV extraction without awareness or protection options.",
            "target": "DeFi traders, protocol teams, wallet providers",
            "why_solana": "Solana's continuous block production model creates unique MEV dynamics. Jito's tip system needs better UX for protection.",
            "mvp": "Transaction relay service that routes user transactions through Jito bundles with configurable MEV protection, plus a browser extension.",
            "risks": "Latency tradeoff for MEV protection; validator adoption. Validate by measuring slippage reduction on 100 test trades.",
            "category": "infrastructure",
        },
        {
            "title": "MEV Analytics Dashboard",
            "problem": "No comprehensive real-time view of MEV activity on Solana — sandwich attacks, arbitrage, liquidations are opaque.",
            "target": "Researchers, protocol designers, traders, validators",
            "why_solana": "Solana's unique MEV landscape (Jito bundles, continuous blocks) is poorly understood and under-monitored.",
            "mvp": "Dashboard tracking Jito bundle activity, detected sandwich attacks, arb profits, and MEV trends over time with alerts.",
            "risks": "Transaction classification accuracy; data volume. Validate by cross-referencing with known MEV bot addresses.",
            "category": "analytics",
        },
    ],
    "firedancer": [
        {
            "title": "Firedancer Validator Performance Monitor",
            "problem": "As Firedancer validators come online, operators need specialized monitoring for the new client's unique metrics.",
            "target": "Validator operators, staking services, Solana Foundation",
            "why_solana": "Firedancer is the most significant validator client addition to Solana, requiring new operational tooling.",
            "mvp": "Monitoring agent that tracks Firedancer-specific metrics (QUIC performance, shred processing, memory usage) with Grafana dashboards.",
            "risks": "Firedancer API stability during development; client differences. Validate by running alongside 3 Firedancer testnet validators.",
            "category": "infrastructure",
        },
    ],
    "depin": [
        {
            "title": "DePIN Device Onboarding SDK",
            "problem": "DePIN projects each build custom device registration and proof submission systems, duplicating effort.",
            "target": "DePIN project builders, IoT hardware manufacturers",
            "why_solana": "Solana's state compression makes device registration cheap at scale. Multiple DePIN projects already on Solana.",
            "mvp": "SDK for device attestation, registration (via cNFTs), and proof-of-work submission on Solana with reference firmware.",
            "risks": "Hardware diversity; proof verification complexity. Validate with one DePIN partner and 100 test devices.",
            "category": "developer_tooling",
        },
        {
            "title": "DePIN Network Revenue Tracker",
            "problem": "DePIN token holders can't easily track real revenue generation across Solana DePIN networks to assess value.",
            "target": "DePIN investors, analysts, protocol teams",
            "why_solana": "Solana hosts major DePIN networks (Helium, Render, Hivemapper). Revenue data is onchain but fragmented.",
            "mvp": "Dashboard aggregating real revenue data from top 5 Solana DePIN networks with per-device economics and trend analysis.",
            "risks": "Revenue definition varies by network; data normalization. Validate by cross-checking with protocol team disclosures.",
            "category": "analytics",
        },
    ],
    "svm": [
        {
            "title": "SVM Compatibility Test Suite",
            "problem": "Projects building SVM-compatible chains/rollups lack standardized compatibility testing against Solana mainnet.",
            "target": "SVM chain builders (Eclipse, Neon), Solana core developers",
            "why_solana": "SVM is expanding beyond Solana mainnet. Compatibility testing prevents ecosystem fragmentation.",
            "mvp": "Test harness running 1000+ Solana program test cases against any SVM implementation, with compatibility report and diff analysis.",
            "risks": "Defining compatibility boundaries; keeping up with SVM changes. Validate by testing against Eclipse and Neon devnets.",
            "category": "developer_tooling",
        },
    ],
    "validator": [
        {
            "title": "Stake Pool Performance Comparator",
            "problem": "SOL stakers lack clear, real-time comparison of stake pool performance, fees, and risk across providers.",
            "target": "SOL holders, institutional stakers, stake pool operators",
            "why_solana": "Solana's stake pool ecosystem is large and growing. Better transparency benefits decentralization.",
            "mvp": "Dashboard comparing top 20 stake pools on APY, commission, uptime, decentralization score, with alert on commission changes.",
            "risks": "Performance calculation methodology; data freshness. Validate by comparing against known pool statistics for one epoch.",
            "category": "analytics",
        },
    ],
    "solana-mobile": [
        {
            "title": "Mobile-First dApp Template",
            "problem": "Building Solana mobile dApps requires deep knowledge of Mobile Wallet Adapter, transaction signing, and mobile UX patterns.",
            "target": "Mobile developers new to Solana, hackathon participants",
            "why_solana": "Solana Mobile Stack (SMS) and Chapter 2 are expanding mobile crypto UX but developer tooling is immature.",
            "mvp": "React Native template with pre-configured Mobile Wallet Adapter, transaction examples, and 3 common dApp patterns (swap, mint, vote).",
            "risks": "SMS SDK stability; Android vs iOS differences. Validate by building 3 demo apps and measuring time-to-first-transaction.",
            "category": "developer_tooling",
        },
    ],
    "gaming": [
        {
            "title": "Solana Game Item Standard",
            "problem": "Every Solana game creates custom item/asset schemas, making cross-game interoperability impossible.",
            "target": "Game developers, gaming guilds, marketplace operators",
            "why_solana": "Solana's speed and low cost make it ideal for gaming assets. Compressed NFTs can scale to millions of items.",
            "mvp": "Token metadata extension standard for game items (stats, rarity, game ID) with minting SDK and basic marketplace smart contract.",
            "risks": "Game developer buy-in; standard flexibility vs specificity. Validate by implementing in 2 games and testing marketplace listing.",
            "category": "protocol",
        },
    ],
    "grpc": [
        {
            "title": "Solana Data Streaming Platform",
            "problem": "Developers need real-time Solana data but setting up Geyser/gRPC infrastructure is complex and expensive.",
            "target": "dApp developers, analysts, bot builders",
            "why_solana": "Solana's data throughput (65k TPS) makes real-time streaming both challenging and uniquely valuable.",
            "mvp": "Managed gRPC/WebSocket service with filtered subscriptions (by program, account, token) and a generous free tier.",
            "risks": "Infrastructure cost at scale; competing with Helius/Triton. Validate with 50 beta users measuring data freshness.",
            "category": "infrastructure",
        },
    ],
    "nft": [
        {
            "title": "NFT Provenance Verification API",
            "problem": "NFT authenticity verification requires deep onchain analysis (creator verification, metadata integrity) that most apps don't implement.",
            "target": "NFT marketplaces, collectors, verification services",
            "why_solana": "Solana's Metaplex standard enables rich provenance tracking. Fraud in NFTs remains a key trust issue.",
            "mvp": "API that takes a mint address and returns provenance report: creator verified, metadata pinned, royalty status, collection verified.",
            "risks": "Edge cases in creator verification; keeping up with Metaplex updates. Validate against 1000 known authentic + 100 known fake NFTs.",
            "category": "infrastructure",
        },
    ],
    "payments": [
        {
            "title": "Solana Pay Invoice System",
            "problem": "Businesses can't easily generate and track Solana Pay invoices with proper accounting integration.",
            "target": "Small businesses, freelancers, accounting platforms",
            "why_solana": "Solana Pay's QR code standard + USDC on Solana provide near-instant, low-cost B2B payments.",
            "mvp": "Invoice creation tool with Solana Pay QR generation, payment tracking, and CSV export for accounting software.",
            "risks": "Stablecoin regulatory concerns; merchant education. Validate with 20 merchant test transactions.",
            "category": "consumer_app",
        },
    ],
    "dao": [
        {
            "title": "DAO Analytics & Governance Tracker",
            "problem": "Solana DAO participants can't easily compare governance activity, proposal outcomes, and voter participation across DAOs.",
            "target": "DAO contributors, governance delegates, token holders",
            "why_solana": "Solana's growing DAO ecosystem (Realms, Squads) needs governance transparency tooling.",
            "mvp": "Dashboard tracking proposal activity, voter turnout, treasury changes, and delegate performance across Realms-based DAOs.",
            "risks": "Governance program diversity; data normalization. Validate by indexing top 10 Solana DAOs.",
            "category": "analytics",
        },
    ],
}

# Default generic templates for narratives not in the library
DEFAULT_TEMPLATES = [
    {
        "title": "Real-Time {entity} Monitor",
        "problem": "Lack of real-time visibility into {entity} activity and metrics on Solana.",
        "target": "Developers, analysts, and protocol teams working with {entity}",
        "why_solana": "Solana's high throughput and fast finality make real-time monitoring both necessary and uniquely feasible.",
        "mvp": "Dashboard pulling live data for {entity} metrics with configurable alerts and historical charts.",
        "risks": "Data source reliability; metric definition. Validate by comparing with manual analysis for 1 week.",
        "category": "analytics",
    },
    {
        "title": "{entity} Developer SDK",
        "problem": "Developers integrating with {entity} lack standardized, well-documented tooling.",
        "target": "Solana developers building on or integrating {entity}",
        "why_solana": "Solana-native implementation ensures performance and composability with the broader ecosystem.",
        "mvp": "TypeScript + Rust SDK with typed interfaces, example programs, and integration tests.",
        "risks": "API stability; adoption. Validate by building 2 example apps and gathering developer feedback.",
        "category": "developer_tooling",
    },
    {
        "title": "{entity} Infrastructure Service",
        "problem": "Running {entity} infrastructure requires expertise and resources that most teams lack.",
        "target": "Protocol teams, dApp developers, enterprises entering {entity} space",
        "why_solana": "Solana's performance requirements make managed infrastructure especially valuable for {entity}.",
        "mvp": "Managed service providing {entity} infrastructure with API access, monitoring, and SLA guarantees.",
        "risks": "Operational complexity; pricing model. Validate with 5 beta customers measuring reliability.",
        "category": "infrastructure",
    },
]


class IdeaGenerator:
    """Generates build ideas for detected narratives."""

    def __init__(self, config: dict):
        self.config = config
        self.ideas_per_narrative = (
            config.get("idea_generation", {}).get("ideas_per_narrative", 5)
        )

    def generate_ideas(
        self,
        candidate: NarrativeCandidate,
        score: ScoreBreakdown,
        evidence_cards: list[EvidenceCard],
    ) -> list[BuildIdea]:
        """Generate build ideas for a narrative."""
        ideas = []
        entities = candidate.entities
        evidence_urls = [
            ec.event.url for ec in evidence_cards if ec.event.url
        ][:5]

        # 1. Try entity-specific templates
        for entity in entities:
            if entity in IDEA_TEMPLATES:
                for template in IDEA_TEMPLATES[entity]:
                    idea = BuildIdea(
                        title=template["title"],
                        problem_statement=template["problem"],
                        target_user=template["target"],
                        why_solana=template["why_solana"],
                        mvp_scope=template["mvp"],
                        risks_unknowns=template["risks"],
                        validation_approach=template["risks"].split("Validate ")[-1] if "Validate" in template["risks"] else "Run a 2-week pilot with early adopters.",
                        category=template["category"],
                        evidence_links=evidence_urls,
                    )
                    ideas.append(idea)

        # 2. Fill with default templates if needed
        if len(ideas) < self.ideas_per_narrative:
            primary_entity = entities[0] if entities else "this narrative"
            for template in DEFAULT_TEMPLATES:
                if len(ideas) >= self.ideas_per_narrative:
                    break
                idea = BuildIdea(
                    title=template["title"].format(entity=primary_entity.replace("-", " ").title()),
                    problem_statement=template["problem"].format(entity=primary_entity),
                    target_user=template["target"].format(entity=primary_entity),
                    why_solana=template["why_solana"].format(entity=primary_entity),
                    mvp_scope=template["mvp"].format(entity=primary_entity),
                    risks_unknowns=template["risks"].format(entity=primary_entity),
                    validation_approach="Run a 2-week pilot with early adopters and gather structured feedback.",
                    category=template["category"],
                    evidence_links=evidence_urls,
                )
                ideas.append(idea)

        # 3. Ensure at least one non-consumer idea
        categories = set(i.category for i in ideas)
        non_consumer = {"infrastructure", "developer_tooling", "analytics"}
        if not categories.intersection(non_consumer) and ideas:
            primary_entity = entities[0] if entities else "ecosystem"
            ideas.append(
                BuildIdea(
                    title=f"{primary_entity.replace('-', ' ').title()} DevTool Kit",
                    problem_statement=f"Developers building on {primary_entity} lack integrated tooling for testing, debugging, and monitoring.",
                    target_user=f"Solana developers working with {primary_entity}",
                    why_solana="Solana-native tooling provides deeper integration and better DX than chain-agnostic alternatives.",
                    mvp_scope="CLI tool with program testing, account inspection, and transaction simulation for the specific domain.",
                    risks_unknowns="Competing with general tools; narrow target audience. Validate by surveying 20 developers.",
                    validation_approach="Survey 20 active Solana developers and build features for top 3 pain points.",
                    category="developer_tooling",
                    evidence_links=evidence_urls,
                )
            )

        # Deduplicate by title
        seen_titles = set()
        unique_ideas = []
        for idea in ideas:
            if idea.title not in seen_titles:
                seen_titles.add(idea.title)
                unique_ideas.append(idea)

        return unique_ideas[: self.ideas_per_narrative]
