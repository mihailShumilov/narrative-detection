"""Streamlit dashboard for Solana Narrative Detection.

Provides interactive visualization of fortnightly narrative reports.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.runner import run_pipeline
from pipeline.models import FortnightlyReport, RankedNarrative


st.set_page_config(
    page_title="Solana Narrative Detector",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_or_run_report() -> FortnightlyReport | None:
    """Load existing report or run pipeline."""
    reports_dir = Path("reports")

    # Check for existing reports
    existing_reports = sorted(reports_dir.glob("report_*.json"), reverse=True) if reports_dir.exists() else []

    if existing_reports:
        latest = existing_reports[0]
        try:
            data = json.loads(latest.read_text())
            return _reconstruct_report(data)
        except Exception as e:
            st.warning(f"Failed to load report: {e}")

    return None


def _reconstruct_report(data: dict) -> FortnightlyReport:
    """Reconstruct FortnightlyReport from JSON data."""
    from pipeline.models import (
        FortnightlyReport, RankedNarrative, ScoreBreakdown,
        EvidenceCard, BuildIdea, SignalEvent, SourceType, SourceSubtype,
    )

    narratives = []
    for n_data in data.get("narratives", []):
        score_data = n_data.get("score", {})
        score = ScoreBreakdown(
            velocity=score_data.get("velocity", 0),
            breadth=score_data.get("breadth", 0),
            cross_domain=score_data.get("cross_domain", 0),
            novelty=score_data.get("novelty", 0),
            credibility=score_data.get("credibility", 0),
            spam_penalty=score_data.get("spam_penalty", 0),
            single_source_penalty=score_data.get("single_source_penalty", 0),
            composite=score_data.get("composite", 0),
            feature_contributions=score_data.get("feature_contributions", {}),
        )

        evidence_cards = []
        for ec_data in n_data.get("evidence_cards", []):
            event_data = ec_data.get("event", {})
            event = SignalEvent(
                timestamp=datetime.fromisoformat(event_data.get("timestamp", "2026-01-01T00:00:00+00:00")),
                source_type=SourceType(event_data.get("source_type", "offchain")),
                source_subtype=SourceSubtype(event_data.get("source_subtype", "github")),
                entities=event_data.get("entities", []),
                text=event_data.get("text", ""),
                url=event_data.get("url", ""),
                metrics=event_data.get("metrics", {}),
                raw_source=event_data.get("raw_source", ""),
                author=event_data.get("author", ""),
                author_followers=event_data.get("author_followers", 0),
                content_hash=event_data.get("content_hash", ""),
            )
            evidence_cards.append(EvidenceCard(
                event=event,
                relevance_score=ec_data.get("relevance_score", 0),
                summary=ec_data.get("summary", ""),
                metric_highlight=ec_data.get("metric_highlight"),
            ))

        build_ideas = []
        for bi_data in n_data.get("build_ideas", []):
            build_ideas.append(BuildIdea(
                title=bi_data.get("title", ""),
                problem_statement=bi_data.get("problem_statement", ""),
                target_user=bi_data.get("target_user", ""),
                why_solana=bi_data.get("why_solana", ""),
                mvp_scope=bi_data.get("mvp_scope", ""),
                risks_unknowns=bi_data.get("risks_unknowns", ""),
                validation_approach=bi_data.get("validation_approach", ""),
                category=bi_data.get("category", ""),
                evidence_links=bi_data.get("evidence_links", []),
            ))

        narratives.append(RankedNarrative(
            rank=n_data.get("rank", 0),
            narrative_id=n_data.get("narrative_id", ""),
            label=n_data.get("label", ""),
            explanation=n_data.get("explanation", ""),
            why_now=n_data.get("why_now", ""),
            score=score,
            confidence=n_data.get("confidence", 0),
            confidence_reasoning=n_data.get("confidence_reasoning", ""),
            evidence_cards=evidence_cards,
            build_ideas=build_ideas,
            entities=n_data.get("entities", []),
            timeline_data=n_data.get("timeline_data", []),
        ))

    return FortnightlyReport(
        run_id=data.get("run_id", ""),
        window_start=datetime.fromisoformat(data.get("window_start", "2026-01-01")),
        window_end=datetime.fromisoformat(data.get("window_end", "2026-02-01")),
        baseline_start=datetime.fromisoformat(data.get("baseline_start", "2025-12-01")),
        generated_at=datetime.fromisoformat(data.get("generated_at", "2026-02-01")),
        narratives=narratives,
        methodology=data.get("methodology", ""),
        metadata=data.get("metadata", {}),
    )


def render_header(report: FortnightlyReport):
    """Render dashboard header."""
    st.markdown("""
    <style>
    .main-header {
        background: linear-gradient(135deg, #14F195 0%, #9945FF 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.5rem;
        font-weight: 800;
        margin-bottom: 0;
    }
    .sub-header {
        color: #888;
        font-size: 1.1rem;
        margin-top: -10px;
    }
    .metric-card {
        background: #1a1a2e;
        border-radius: 12px;
        padding: 20px;
        border: 1px solid #333;
    }
    .narrative-card {
        background: #16213e;
        border-radius: 12px;
        padding: 24px;
        margin: 16px 0;
        border-left: 4px solid #14F195;
    }
    .evidence-card {
        background: #0f3460;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
        border: 1px solid #1a1a4e;
    }
    .idea-card {
        background: #1a1a2e;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
        border: 1px solid #9945FF44;
    }
    .score-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.9rem;
    }
    </style>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown('<p class="main-header">Solana Narrative Detector</p>', unsafe_allow_html=True)
        st.markdown(
            f'<p class="sub-header">Fortnightly Analysis: '
            f'{report.window_start.strftime("%b %d")} — {report.window_end.strftime("%b %d, %Y")}</p>',
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(f"**Run ID**: `{report.run_id[:16]}`")
        st.markdown(f"**Generated**: {report.generated_at.strftime('%Y-%m-%d %H:%M')}")


def render_metrics(report: FortnightlyReport):
    """Render summary metrics row."""
    meta = report.metadata
    cols = st.columns(5)

    with cols[0]:
        st.metric("Narratives Detected", len(report.narratives))
    with cols[1]:
        st.metric("Total Signals", meta.get("total_events", 0))
    with cols[2]:
        st.metric("After Dedup", meta.get("deduped_events", 0))
    with cols[3]:
        st.metric("Sources Used", len(meta.get("sources_used", [])))
    with cols[4]:
        avg_confidence = sum(n.confidence for n in report.narratives) / max(1, len(report.narratives))
        st.metric("Avg Confidence", f"{avg_confidence:.0%}")


def render_narrative_overview(report: FortnightlyReport):
    """Render narrative ranking overview chart."""
    if not report.narratives:
        st.info("No narratives detected in this window.")
        return

    # Horizontal bar chart of scores
    labels = [f"#{n.rank} {n.label}" for n in report.narratives]
    scores = [n.score.composite for n in report.narratives]
    confidences = [n.confidence for n in report.narratives]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=labels[::-1],
        x=scores[::-1],
        orientation="h",
        marker=dict(
            color=scores[::-1],
            colorscale=[[0, "#9945FF"], [0.5, "#14F195"], [1, "#00FFA3"]],
        ),
        text=[f"{s:.2f}" for s in scores[::-1]],
        textposition="auto",
        hovertemplate="<b>%{y}</b><br>Score: %{x:.3f}<extra></extra>",
    ))

    fig.update_layout(
        title="Narrative Rankings by Composite Score",
        xaxis_title="Composite Score",
        height=max(300, len(labels) * 50),
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_score_radar(narrative: RankedNarrative):
    """Render radar chart for score breakdown."""
    categories = ["Velocity", "Breadth", "Cross-Domain", "Novelty", "Credibility"]
    values = [
        narrative.score.velocity,
        narrative.score.breadth,
        narrative.score.cross_domain,
        narrative.score.novelty,
        narrative.score.credibility,
    ]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        fill="toself",
        fillcolor="rgba(20, 241, 149, 0.2)",
        line=dict(color="#14F195", width=2),
        name=narrative.label,
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 1], gridcolor="#333"),
            bgcolor="rgba(0,0,0,0)",
            angularaxis=dict(gridcolor="#333"),
        ),
        showlegend=False,
        height=300,
        margin=dict(l=60, r=60, t=30, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc", size=11),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_timeline(narrative: RankedNarrative):
    """Render event timeline chart."""
    if not narrative.timeline_data:
        return

    df = pd.DataFrame(narrative.timeline_data)
    if df.empty:
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["count"],
        mode="lines+markers",
        fill="tozeroy",
        fillcolor="rgba(153, 69, 255, 0.2)",
        line=dict(color="#9945FF", width=2),
        marker=dict(size=6, color="#14F195"),
    ))

    fig.update_layout(
        title="Signal Timeline",
        xaxis_title="Date",
        yaxis_title="Events",
        height=250,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_narrative_detail(narrative: RankedNarrative):
    """Render full narrative detail section."""
    # Header
    confidence_color = "#14F195" if narrative.confidence > 0.6 else "#FFD700" if narrative.confidence > 0.4 else "#FF6B6B"
    st.markdown(f"### #{narrative.rank}: {narrative.label}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Composite Score", f"{narrative.score.composite:.3f}")
    with col2:
        st.metric("Confidence", f"{narrative.confidence:.0%}")
    with col3:
        st.metric("Evidence Signals", len(narrative.evidence_cards))

    # Tabs for different views
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Explanation", "Evidence", "Score Analysis", "Build Ideas", "Timeline"])

    with tab1:
        st.markdown("#### What & Why")
        st.markdown(narrative.explanation)
        st.markdown("#### Why Now")
        st.markdown(narrative.why_now)
        st.markdown("#### Confidence Assessment")
        st.info(narrative.confidence_reasoning)
        st.markdown("**Entities**: " + ", ".join(f"`{e}`" for e in narrative.entities))

    with tab2:
        st.markdown(f"#### Top Evidence ({len(narrative.evidence_cards)} signals)")
        for i, ec in enumerate(narrative.evidence_cards, 1):
            with st.expander(f"{i}. {ec.summary[:100]}...", expanded=i <= 3):
                st.markdown(f"**Source**: {ec.event.source_subtype.value} | **Relevance**: {ec.relevance_score:.2f}")
                st.markdown(f"**Time**: {ec.event.timestamp.strftime('%Y-%m-%d %H:%M')}")
                if ec.metric_highlight:
                    st.markdown(f"**Metrics**: {ec.metric_highlight}")
                if ec.event.url:
                    st.markdown(f"[View Source]({ec.event.url})")
                if ec.event.author:
                    st.markdown(f"**Author**: {ec.event.author}")

    with tab3:
        col1, col2 = st.columns(2)
        with col1:
            render_score_radar(narrative)
        with col2:
            st.markdown("#### Feature Contributions")
            for feature, contrib in narrative.score.feature_contributions.items():
                bar_width = abs(contrib) * 200
                color = "#14F195" if contrib > 0 else "#FF6B6B"
                label = feature.replace("_", " ").title()
                st.markdown(
                    f"**{label}**: {contrib:+.3f}"
                )
            st.markdown("---")
            st.markdown(f"**Spam Penalty**: {narrative.score.spam_penalty:.3f}")
            st.markdown(f"**Single Source Penalty**: {narrative.score.single_source_penalty:.3f}")

    with tab4:
        st.markdown(f"#### Build Ideas ({len(narrative.build_ideas)} ideas)")
        for i, idea in enumerate(narrative.build_ideas, 1):
            with st.expander(f"{i}. {idea.title} [{idea.category}]", expanded=i <= 2):
                st.markdown(f"**Problem**: {idea.problem_statement}")
                st.markdown(f"**Target User**: {idea.target_user}")
                st.markdown(f"**Why Solana**: {idea.why_solana}")
                st.markdown(f"**MVP Scope (1-2 weeks)**: {idea.mvp_scope}")
                st.markdown(f"**Risks & Unknowns**: {idea.risks_unknowns}")
                st.markdown(f"**Validation**: {idea.validation_approach}")
                if idea.evidence_links:
                    st.markdown("**Evidence Links**: " + " | ".join(
                        f"[Link {j}]({link})" for j, link in enumerate(idea.evidence_links, 1)
                    ))

    with tab5:
        render_timeline(narrative)


def render_methodology(report: FortnightlyReport):
    """Render methodology section."""
    st.markdown(report.methodology)


def render_export(report: FortnightlyReport):
    """Render export options."""
    col1, col2 = st.columns(2)

    with col1:
        reports_dir = Path("reports")
        md_files = sorted(reports_dir.glob("report_*.md"), reverse=True) if reports_dir.exists() else []
        if md_files:
            content = md_files[0].read_text()
            st.download_button(
                "Download Markdown Report",
                content,
                file_name=md_files[0].name,
                mime="text/markdown",
            )

    with col2:
        json_str = report.to_json()
        st.download_button(
            "Download JSON Bundle",
            json_str,
            file_name=f"report_{report.run_id}.json",
            mime="application/json",
        )


def main():
    """Main dashboard entry point."""
    # Sidebar
    with st.sidebar:
        st.markdown("## Controls")

        action = st.radio(
            "Action",
            ["View Latest Report", "Run New Analysis"],
            index=0,
        )

        if action == "Run New Analysis":
            st.warning("This will fetch live data from configured sources.")
            if st.button("Run Pipeline", type="primary"):
                with st.spinner("Running narrative detection pipeline..."):
                    try:
                        report = run_pipeline()
                        st.session_state["report"] = report
                        st.success(f"Pipeline complete! {len(report.narratives)} narratives detected.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Pipeline failed: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        st.markdown("---")
        st.markdown("### About")
        st.markdown(
            "**Solana Narrative Detector** identifies emerging narratives "
            "in the Solana ecosystem by analyzing onchain and offchain signals, "
            "then generates actionable build ideas for founders and investors."
        )
        st.markdown("---")
        st.markdown("**Data Sources**")
        st.markdown("- Solana RPC (onchain)")
        st.markdown("- GitHub (developer activity)")
        st.markdown("- Twitter/X (social signals)")
        st.markdown("- RSS/Blogs (ecosystem content)")
        st.markdown("---")
        st.markdown(
            "[GitHub Repo](https://github.com/example/narrative-detection) | "
            "Built for Solana Hackathon 2026"
        )

    # Main content
    report = st.session_state.get("report")
    if report is None:
        report = load_or_run_report()
        if report:
            st.session_state["report"] = report

    if report is None:
        st.markdown("# Solana Narrative Detector")
        st.info(
            "No report found. Click **Run New Analysis** in the sidebar to generate a report, "
            "or run `python -m pipeline.runner` from the command line first."
        )
        return

    # Render dashboard
    render_header(report)
    st.markdown("---")
    render_metrics(report)
    st.markdown("---")

    # Overview section
    st.markdown("## Narrative Rankings")
    render_narrative_overview(report)

    # Detailed narratives
    st.markdown("---")
    st.markdown("## Narrative Details")

    for narrative in report.narratives:
        with st.container():
            render_narrative_detail(narrative)
            st.markdown("---")

    # Methodology & Export
    with st.expander("Methodology", expanded=False):
        render_methodology(report)

    st.markdown("---")
    st.markdown("### Export")
    render_export(report)


if __name__ == "__main__":
    main()
