# Solana Narrative Detector

**Detect emerging narratives and early signals in the Solana ecosystem. Refreshes every 14 days.**

> **[Live Demo](https://solana-narrative-detection.streamlit.app/)** — try it now, no setup required.

A signal-driven system that ingests onchain and offchain data, extracts candidate narratives, scores and ranks them by strength/novelty, explains WHY each narrative is detected, and generates 3-5 concrete build ideas per narrative.

Built for **founders, investors, and ecosystem teams** who need to translate signals into actionable opportunities.

---

## Quick Start

### Live demo

**https://solana-narrative-detection.streamlit.app/**

### One-command local run

```bash
# Clone and install
git clone https://github.com/mihailShumilov/narrative-detection.git && cd narrative-detection
pip install -r requirements.txt

# Run the pipeline (fetches live data + merges bundled snapshot)
python main.py --date 2026-02-10

# Launch the dashboard
python main.py --dashboard
# or: make dev
```

### Docker

```bash
docker compose up --build
# Dashboard at http://localhost:8501
```

### Hosted Demo

Deploy to **Streamlit Community Cloud**:
1. Push repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Point to `app/streamlit_app.py`
4. Add secrets (optional): `GITHUB_TOKEN`, `TWITTER_BEARER_TOKEN`, `SOLANA_RPC_URL`

Or deploy to **Railway/Render**:
```bash
# Dockerfile serves the Streamlit app on port 8501
railway up  # or render deploy
```

---

## What It Does

Every 14 days (configurable), the system:

1. **Ingests** data from 4+ sources (Solana RPC, GitHub, Twitter/X, RSS/Blogs)
2. **Normalizes** events with entity resolution and deduplication
3. **Clusters** events into narrative candidates via entity co-occurrence + TF-IDF text similarity
4. **Scores** narratives on velocity, breadth, cross-domain corroboration, novelty, credibility (with spam penalties)
5. **Explains** each narrative with evidence cards, "why now" analysis, and confidence reasoning
6. **Generates** 3-5 grounded build ideas per narrative with MVP scopes
7. **Exports** a markdown report + JSON artifact bundle + interactive dashboard

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                     │
│              Streamlit Dashboard + MD/JSON Export          │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────┐
│                    IDEA GENERATOR (G)                      │
│         Template library + evidence grounding              │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────┐
│                 EXPLANATION BUILDER (F)                    │
│    Evidence cards + "why now" + confidence assessment      │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────┐
│                 SCORING & RANKING (E)                      │
│  NarrativeScore = Σ(weights * features) - penalties       │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────┐
│              NARRATIVE CLUSTERING (D)                      │
│    Entity co-occurrence + TF-IDF + Agglomerative          │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────┐
│            NORMALIZATION + DEDUP (B+C)                     │
│      Entity aliases + hash dedup + fuzzy dedup            │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────┐
│                   INGESTION (A)                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │  Solana   │ │  GitHub  │ │ Twitter/ │ │   RSS/   │   │
│  │   RPC     │ │   API    │ │  Nitter  │ │  Blogs   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Pipeline Stages

| Stage | Module | Description |
|-------|--------|-------------|
| A | `connectors/` | 4 connectors: Solana RPC, GitHub, Twitter/X, RSS/Blogs |
| B+C | `pipeline/normalizer.py` | Entity alias resolution + hash dedup + fuzzy dedup |
| D | `pipeline/clustering.py` | Entity co-occurrence graph + TF-IDF text clustering |
| E | `pipeline/scoring.py` | Weighted composite scoring with spam/single-source penalties |
| F | `pipeline/explainer.py` | Evidence cards, "why now", confidence assessment |
| G | `pipeline/idea_generator.py` | Template-based build idea generation, grounded in evidence |
| H | `pipeline/report_exporter.py` + `app/` | Markdown + JSON export + Streamlit dashboard |

---

## Data Sources

### Onchain (Solana Mainnet)
- **Solana RPC**: Transaction activity (`getRecentPerformanceSamples`), epoch info, program balance probes, supply metrics
- **Tracked programs**: Jupiter, Orca Whirlpool, Drift, Marginfi, Phoenix, Tensor, Jito, Token-2022, State Compression, Metaplex, Bubblegum

### Offchain
- **GitHub API**: Repository search (6 Solana-related queries), 13 org feeds, release tracking, star/fork metrics
- **Twitter/X**: 30+ KOL handles + 12 keyword queries. Uses official API if `TWITTER_BEARER_TOKEN` set; falls back to Nitter RSS; final fallback to bundled snapshot
- **RSS/Blogs**: Solana Foundation, Helius, Orca, Marginfi, Drift, Jito blogs

### Fallback
If no API keys are configured, the system runs using **bundled snapshot data** (`data/snapshots/`) containing ~65 realistic events across all 7 narrative themes. The demo always works.

---

## Scoring Model

```
NarrativeScore = 0.25 * Velocity
               + 0.20 * Breadth
               + 0.20 * CrossDomain
               + 0.20 * Novelty
               + 0.15 * Credibility
               - 0.10 * SpamPenalty
               - 0.15 * SingleSourcePenalty
```

### Feature Definitions

| Feature | Description | Range |
|---------|-------------|-------|
| **Velocity** | Event rate in window vs baseline. Acceleration = window_rate / baseline_rate | [0, 1] |
| **Breadth** | Unique entities (40%), source types (30%), authors (30%) involved | [0, 1] |
| **CrossDomain** | Balance between onchain/offchain evidence + offchain subtype diversity | [0, 1] |
| **Novelty** | Ratio of new entities not seen in baseline period | [0, 1] |
| **Credibility** | Source quality: onchain=0.9, high-follower KOL=0.85, official blog=0.75, verified URL=+0.05 | [0, 1] |
| **SpamPenalty** | Detects burst patterns (>50% events in 1 hour) and repetitive authors (>60% single author) | [0, 1] |
| **SingleSourcePenalty** | Activates when >70% of evidence comes from one source subtype | [0, 1] |

### Weights (configurable in `config/default.yaml`)

All weights and thresholds are overridable via config. Tests verify:
- Cross-domain corroboration outranks same-velocity single-domain
- Spam bursts are penalized
- Single-source dominance is penalized
- Novelty increases score for new clusters

---

## Detected Narratives (Sample Run: Jan 27 - Feb 10, 2026)

| Rank | Narrative | Score | Confidence | Key Signal |
|------|-----------|-------|------------|------------|
| 1 | **AI Agents & DeFi** | 0.761 | 80% | Agent frameworks (Rig, Eliza, Olas) + agent MEV activity on Jito |
| 2 | **DePIN Growth** | 0.697 | 73% | Helium 1.24M hotspots, Render H100 support, Hivemapper AI detection |
| 3 | **Compressed NFTs / State Compression** | 0.622 | 73% | DRiP 2.4M cNFTs/week, Light Protocol ZK compression, Bubblegum v2 |
| 4 | **Firedancer Validator Client** | 0.619 | 73% | 480 nodes, 22.8% stake, Trail of Bits audit, 42K TPS benchmarks |
| 5 | **SVM Expansion** | 0.615 | 73% | Eclipse v2.3, Nitro SVM rollups, IBC for SVM chains |

---

## Build Ideas (Examples)

### For "AI Agents on Solana"
1. **Solana AI Agent Framework SDK** - TypeScript SDK with pre-built Solana tools that plug into LangChain/AutoGPT
2. **Onchain Agent Registry & Reputation** - Solana program for registering agents with metadata + activity explorer
3. **AI-Powered Transaction Explainer** - API that parses Solana transactions and returns natural language explanations

### For "DePIN Growth"
1. **DePIN Device Onboarding SDK** - SDK for device attestation via cNFTs with reference firmware
2. **DePIN Network Revenue Tracker** - Dashboard aggregating real revenue from top 5 Solana DePIN networks

### For "Firedancer"
1. **Firedancer Validator Performance Monitor** - Monitoring agent tracking Firedancer-specific metrics with Grafana dashboards

---

## Project Structure

```
narrative_detection/
├── app/
│   └── streamlit_app.py        # Streamlit dashboard
├── connectors/
│   ├── base.py                 # Base connector with caching, rate limiting
│   ├── solana_onchain.py       # Solana RPC connector
│   ├── github_connector.py     # GitHub API connector
│   ├── twitter_connector.py    # Twitter/X + Nitter fallback
│   └── rss_connector.py        # RSS/blog feed connector
├── pipeline/
│   ├── models.py               # Core data models (SignalEvent, RankedNarrative, etc.)
│   ├── config.py               # YAML config loader with env var overrides
│   ├── logging.py              # Structured logging setup
│   ├── normalizer.py           # Entity normalization + deduplication
│   ├── clustering.py           # Narrative candidate generation
│   ├── scoring.py              # Composite scoring model
│   ├── explainer.py            # Evidence cards + "why now" + confidence
│   ├── idea_generator.py       # Build idea generation
│   ├── report_exporter.py      # Markdown + JSON export
│   └── runner.py               # Pipeline orchestrator
├── config/
│   └── default.yaml            # Configuration (weights, sources, entities)
├── data/
│   ├── cache/                  # Deterministic caching per run
│   └── snapshots/              # Bundled sample data (65 events)
├── reports/                    # Generated reports (gitignored except samples)
├── tests/
│   ├── test_scoring.py         # 13 scoring model tests
│   ├── test_normalizer.py      # 7 normalization/dedup tests
│   ├── test_clustering.py      # 6 clustering tests
│   └── test_evaluation.py      # 7 evaluation harness tests (sanity + regression)
├── main.py                     # CLI entry point
├── Dockerfile                  # Container definition
├── docker-compose.yml          # Docker Compose config
├── Makefile                    # Common commands
├── requirements.txt            # Python dependencies
├── pytest.ini                  # Test configuration
├── .env.example                # Environment variable template
└── .gitignore
```

---

## Running Tests

```bash
# All tests (34 tests)
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ -v --cov=pipeline --cov=connectors --cov-report=term-missing

# Just scoring tests
python -m pytest tests/test_scoring.py -v

# Just evaluation harness
python -m pytest tests/test_evaluation.py -v
```

### Test Coverage

- **Scoring model** (13 tests): Cross-domain > single-domain, spam penalty, single-source penalty, novelty, velocity, score range, feature contributions
- **Normalization** (7 tests): Alias resolution, dedup (exact + fuzzy), full pipeline
- **Clustering** (6 tests): Entity co-occurrence, text clustering, label generation
- **Evaluation harness** (7 tests): Sanity checks (no single-source dominance in top results, spam detection), regression tests on snapshot data

---

## Configuration

All configuration is in `config/default.yaml`:

- **Analysis window**: 14 days (configurable)
- **Scoring weights**: Adjustable per-feature weights and penalty factors
- **KOL list**: 30+ Solana KOL handles (configurable)
- **Keywords**: 12 Solana-related search queries (configurable)
- **Entity aliases**: Canonical mapping for 25+ Solana projects
- **RSS feeds**: 5+ Solana ecosystem blogs

### Environment Variables

```bash
# Optional - system works without any keys
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
GITHUB_TOKEN=ghp_xxxx          # Higher rate limits
TWITTER_BEARER_TOKEN=xxxx      # Full Twitter API access
HELIUS_API_KEY=xxxx            # Enriched onchain data
```

---

## Stack Choice: Python + Streamlit (Option B)

**Why**: Fastest path to a credible hosted demo. Streamlit provides:
- Interactive dashboard with zero frontend code
- One-click deployment to Streamlit Community Cloud
- Built-in charting (via Plotly integration)
- Session state management for pipeline runs

Python ecosystem provides:
- scikit-learn for TF-IDF + agglomerative clustering
- feedparser for RSS ingestion
- httpx for async-ready HTTP with retries
- structlog for structured JSON logging

---

## Limitations

- **Twitter coverage** depends on API access. Falls back to Nitter RSS (unreliable) then bundled snapshot
- **Onchain data** via public RPC is limited to recent epochs. Historical analysis needs archival nodes
- **Entity extraction** uses keyword matching, not NER - may miss novel projects without known keywords
- **Narrative clustering** may merge related but distinct trends when entity overlap is high
- **Build ideas** are generated from templates - may not capture all nuances of rapidly evolving narratives
- **No real-time streaming** - designed for fortnightly batch analysis

---

## Reproducibility

- **Deterministic caching**: All fetched data is cached in `data/cache/` with TTL. Same run window produces same results from cache
- **Bundled snapshots**: `data/snapshots/` contains 65 events that make the demo work without any API keys
- **Config-driven**: All parameters (weights, thresholds, sources) are in `config/default.yaml`
- **Structured logs**: Every pipeline stage logs structured JSON with event counts, timing, and errors

---

## License

MIT
