from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
VECTOR_DIR = ROOT_DIR / "data" / "vector-library"
SAMPLES_DIR = VECTOR_DIR / "samples"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.gemini_service import embed_text


SEED_LIBRARY: dict[str, list[dict[str, Any]]] = {
    "it": [
        {
            "id": "it-backend-senior-01",
            "name": "Senior Backend Engineer",
            "role": "Backend Developer",
            "filename": "senior-backend-engineer.md",
            "metadata": {
                "industry": "it",
                "level": "senior",
                "focus": "backend",
                "source": "seed",
            },
            "content": """
# Senior Backend Engineer

- Builds backend services with Python, FastAPI, PostgreSQL, Redis, and Docker.
- Designs REST APIs, background jobs, and event-driven integrations.
- Works on authentication, caching, query optimization, and cloud deployment.
- Reviews architecture, observability, logging, and API performance under load.
- Comfortable with CI/CD, Git workflows, and mentoring junior developers.
""".strip(),
        },
        {
            "id": "it-frontend-react-01",
            "name": "Frontend React Engineer",
            "role": "Frontend Developer",
            "filename": "frontend-react-engineer.md",
            "metadata": {
                "industry": "it",
                "level": "mid",
                "focus": "frontend",
                "source": "seed",
            },
            "content": """
# Frontend React Engineer

- Builds responsive web apps with React, TypeScript, Vite, and Tailwind CSS.
- Works on Next.js style routing, state management, forms, and API integration.
- Improves UX, performance, lazy loading, and reusable component systems.
- Collaborates closely with design, product, and backend teams.
- Understands semantic search UIs, dashboards, and recruiter workflow tools.
""".strip(),
        },
        {
            "id": "it-data-analytics-01",
            "name": "Data Analytics Engineer",
            "role": "Data Analyst",
            "filename": "data-analytics-engineer.md",
            "metadata": {
                "industry": "it",
                "level": "mid",
                "focus": "data",
                "source": "seed",
            },
            "content": """
# Data Analytics Engineer

- Uses SQL, Python, dashboards, and BI tools to analyze product and business data.
- Builds data pipelines, reporting layers, and operational metrics for stakeholders.
- Works with experimentation, KPI design, and decision support for growth teams.
- Communicates insights clearly and turns messy datasets into useful stories.
- Familiar with spreadsheet workflows, automation, and cross-functional reporting.
""".strip(),
        },
    ],
    "sales": [
        {
            "id": "sales-account-exec-01",
            "name": "B2B Account Executive",
            "role": "Sales Executive",
            "filename": "b2b-account-executive.md",
            "metadata": {
                "industry": "sales",
                "level": "mid",
                "focus": "b2b",
                "source": "seed",
            },
            "content": """
# B2B Account Executive

- Owns outbound prospecting, qualification, demos, proposals, and closing.
- Handles pipeline management, CRM hygiene, forecast updates, and client follow-up.
- Strong in consultative selling, objection handling, and revenue target delivery.
- Works with SaaS or service products and coordinates with marketing and operations.
- Tracks conversion rate, deal cycle, account growth, and post-sale relationship quality.
""".strip(),
        },
        {
            "id": "sales-manager-01",
            "name": "Regional Sales Manager",
            "role": "Sales Manager",
            "filename": "regional-sales-manager.md",
            "metadata": {
                "industry": "sales",
                "level": "senior",
                "focus": "team-leadership",
                "source": "seed",
            },
            "content": """
# Regional Sales Manager

- Leads sales teams, sets territory plans, coaches reps, and improves win rate.
- Monitors pipeline health, quota attainment, channel performance, and reporting cadence.
- Builds client strategy, partner relationships, and negotiation plans for key accounts.
- Coordinates with finance, marketing, and operations to remove execution blockers.
- Strong in sales process discipline, forecasting accuracy, and team development.
""".strip(),
        },
        {
            "id": "sales-bdr-01",
            "name": "Business Development Representative",
            "role": "Business Development",
            "filename": "business-development-representative.md",
            "metadata": {
                "industry": "sales",
                "level": "junior",
                "focus": "lead-generation",
                "source": "seed",
            },
            "content": """
# Business Development Representative

- Generates leads through cold outreach, follow-up calls, and account research.
- Qualifies prospects, books meetings, and hands opportunities to account executives.
- Uses CRM tools, outreach cadences, and prospect segmentation.
- Strong in communication, persistence, and fast learning of product messaging.
- Measures booked meetings, response rate, and quality of pipeline creation.
""".strip(),
        },
    ],
    "marketing": [
        {
            "id": "marketing-performance-01",
            "name": "Performance Marketing Specialist",
            "role": "Performance Marketer",
            "filename": "performance-marketing-specialist.md",
            "metadata": {
                "industry": "marketing",
                "level": "mid",
                "focus": "performance",
                "source": "seed",
            },
            "content": """
# Performance Marketing Specialist

- Runs paid acquisition across Facebook Ads, Google Ads, TikTok Ads, and remarketing.
- Tracks CAC, ROAS, conversion funnels, landing page performance, and attribution.
- Coordinates with design and content teams to test creatives and messaging.
- Works with analytics, campaign reporting, and optimization based on data.
- Strong in experimentation, audience segmentation, and budget efficiency.
""".strip(),
        },
        {
            "id": "marketing-content-01",
            "name": "Content Marketing Lead",
            "role": "Content Marketer",
            "filename": "content-marketing-lead.md",
            "metadata": {
                "industry": "marketing",
                "level": "senior",
                "focus": "content",
                "source": "seed",
            },
            "content": """
# Content Marketing Lead

- Plans editorial calendars, thought leadership, SEO content, and campaign narratives.
- Writes and edits long-form content, social assets, email flows, and case studies.
- Aligns messaging with product launches, brand direction, and business goals.
- Uses analytics to improve engagement, traffic, and conversion across channels.
- Collaborates with designers, growth marketers, and subject matter experts.
""".strip(),
        },
        {
            "id": "marketing-brand-01",
            "name": "Brand Marketing Manager",
            "role": "Brand Manager",
            "filename": "brand-marketing-manager.md",
            "metadata": {
                "industry": "marketing",
                "level": "senior",
                "focus": "brand",
                "source": "seed",
            },
            "content": """
# Brand Marketing Manager

- Builds brand positioning, campaign strategy, audience insight, and go-to-market planning.
- Oversees creative consistency, launch messaging, partnerships, and event activation.
- Measures brand awareness, engagement, share of voice, and campaign resonance.
- Balances long-term brand equity with short-term performance demands.
- Works closely with leadership, sales, PR, and content teams.
""".strip(),
        },
    ],
    "design": [
        {
            "id": "design-product-01",
            "name": "Product Designer",
            "role": "Product Designer",
            "filename": "product-designer.md",
            "metadata": {
                "industry": "design",
                "level": "mid",
                "focus": "product",
                "source": "seed",
            },
            "content": """
# Product Designer

- Designs end-to-end user flows, wireframes, prototypes, and polished UI systems.
- Works in Figma, collaborates with PMs and engineers, and validates ideas with users.
- Strong in UX research, information architecture, interaction design, and usability.
- Contributes to design systems, product discovery, and experiment iteration.
- Understands dashboards, enterprise workflows, and data-heavy interfaces.
""".strip(),
        },
        {
            "id": "design-uiux-01",
            "name": "UI UX Designer",
            "role": "UI UX Designer",
            "filename": "ui-ux-designer.md",
            "metadata": {
                "industry": "design",
                "level": "mid",
                "focus": "ui-ux",
                "source": "seed",
            },
            "content": """
# UI UX Designer

- Creates user interfaces, design mockups, component libraries, and interactive flows.
- Improves accessibility, hierarchy, spacing, typography, and user clarity.
- Works across website pages, onboarding, forms, and cross-device experiences.
- Collaborates with developers on implementation details and visual QA.
- Comfortable with prototypes, stakeholder reviews, and iteration under constraints.
""".strip(),
        },
        {
            "id": "design-graphic-01",
            "name": "Graphic Designer",
            "role": "Graphic Designer",
            "filename": "graphic-designer.md",
            "metadata": {
                "industry": "design",
                "level": "junior",
                "focus": "visual",
                "source": "seed",
            },
            "content": """
# Graphic Designer

- Produces social creatives, campaign visuals, banners, decks, and print materials.
- Uses Adobe tools and brand guidelines to create consistent visual assets.
- Supports marketing launches, event materials, and sales collateral.
- Strong in layout, color, typography, and fast turnaround production work.
- Communicates design rationale clearly and adapts assets for multiple channels.
""".strip(),
        },
    ],
}


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _build_embedding_text(industry: str, record: dict[str, Any], content: str) -> str:
    metadata = record.get("metadata") or {}
    lines = [
        f"industry: {industry}",
        f"name: {record['name']}",
        f"role: {record['role']}",
        f"level: {metadata.get('level', '')}",
        f"focus: {metadata.get('focus', '')}",
        content,
    ]
    return "\n".join(line for line in lines if line.strip())


def main() -> None:
    settings = get_settings()
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating vector library with embedding model: {settings.gemini_embedding_model}")

    for industry, records in SEED_LIBRARY.items():
        output_records: list[dict[str, Any]] = []
        sample_dir = SAMPLES_DIR / industry
        sample_dir.mkdir(parents=True, exist_ok=True)

        for record in records:
            sample_path = sample_dir / record["filename"]
            content = str(record["content"]).strip()
            _write_text(sample_path, content)

            embedding_text = _build_embedding_text(industry, record, content)
            vector = embed_text(embedding_text, settings.gemini_embedding_model)

            output_records.append(
                {
                    "id": record["id"],
                    "name": record["name"],
                    "role": record["role"],
                    "relativePath": str(sample_path.relative_to(VECTOR_DIR)).replace("\\", "/"),
                    "metadata": record["metadata"],
                    "vector": vector,
                }
            )
            print(f"  - embedded {industry}/{record['id']} ({len(vector)} dims)")

        output_path = VECTOR_DIR / f"{industry}-embeddings.json"
        output_path.write_text(
            json.dumps({"records": output_records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"saved {output_path.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
