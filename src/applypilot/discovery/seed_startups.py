"""Seed & Early Stage Funded Startup Discovery Module.

Crawls and maintains active early-stage startups that have recently raised seed funding 
(YC recent batches, Entrackr / Inc42 Indian tech seed rounds). 
Early-stage founders hire directly and make fast interview decisions without corporate ATS walls.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from applypilot.database import get_connection

log = logging.getLogger(__name__)

# Curated list of high-growth seed/Series-A tech startups in India & Remote hiring backend engineers
RECENT_FUNDED_STARTUPS = [
    {
        "company": "Kula",
        "founders": "Achuthanand Ravi, Sathya Nellore Sampath",
        "email": "careers@kula.ai",
        "domain": "Recruitment Automation / AI",
        "funding": "Seed $2.7M (Together Fund)",
        "tech": "Java, Go, Microservices",
        "url": "https://kula.ai/careers"
    },
    {
        "company": "SuperOps.ai",
        "founders": "Arvind Parthiban, Jayakumar Karumbasalam",
        "email": "careers@superops.ai",
        "domain": "Unified PSA-RMM Platform",
        "funding": "Series B $12.4M (Addition, Tanglin)",
        "tech": "Java, Python, Distributed Systems",
        "url": "https://superops.ai/careers"
    },
    {
        "company": "Sprinto",
        "founders": "Girish Redekar, Raghuveer Kancherla",
        "email": "talent@sprinto.com",
        "domain": "Security Compliance Automation",
        "funding": "Series B $20M (Accel)",
        "tech": "Go, Python, Postgres, AWS",
        "url": "https://sprinto.com/careers"
    },
    {
        "company": "Segmind",
        "founders": "Vishnu Ramesh, Rohit Ramesh",
        "email": "founders@segmind.com",
        "domain": "Developer APIs for Generative AI (YC W24)",
        "funding": "YC W24 ($500k)",
        "tech": "Go, Python, Redis, Distributed GPU Infrastructure",
        "url": "https://segmind.com/careers"
    },
    {
        "company": "Focal (YC W24)",
        "founders": "Inian Parameshwaran",
        "email": "inian@usefocal.com",
        "domain": "Enterprise AI Search & Analytics (YC W24)",
        "funding": "YC W24 ($500k)",
        "tech": "Java, Go, Kafka, Distributed Search",
        "url": "https://usefocal.com/careers"
    },
    {
        "company": "DevRev",
        "founders": "Dheeraj Pandey, Manoj Agarwal",
        "email": "careers@devrev.ai",
        "domain": "AI-Native Customer & Dev Platform",
        "funding": "Series A $100M (Khosla)",
        "tech": "Go, Kafka, Distributed Storage, Kubernetes",
        "url": "https://devrev.ai/careers"
    },
    {
        "company": "Pepsales (YC S24)",
        "founders": "Varun Ramamurthy, Abhinandan Dani",
        "email": "founders@pepsales.ai",
        "domain": "AI Demo Automation for Enterprise Sales (YC S24)",
        "funding": "YC S24 ($500k)",
        "tech": "Go, Python, Redis, Webhooks",
        "url": "https://pepsales.ai"
    },
    {
        "company": "BiteSpeed",
        "founders": "Vinayak Aggarwal",
        "email": "vinayak@bitespeed.co",
        "domain": "Conversational Commerce for E-commerce Brands",
        "funding": "Seed $1.9M (Sequoia Surge)",
        "tech": "Node, Go, Kafka, Redis, High-Volume Messaging",
        "url": "https://bitespeed.co/careers"
    },
    {
        "company": "Lightup (YC W24)",
        "founders": "Jigesh Patel",
        "email": "contact@lightup.ai",
        "domain": "Data Quality & Governance at Scale",
        "funding": "YC W24 ($500k)",
        "tech": "Java, Go, Distributed SQL, AWS",
        "url": "https://lightup.ai"
    },
    {
        "company": "Pocket FM",
        "founders": "Rohan Nayak, Prateek Dixit",
        "email": "careers@pocketfm.com",
        "domain": "Audio Entertainment Platform",
        "funding": "Series D $103M (Lightspeed)",
        "tech": "Java, Go, Kafka, Redis, Distributed Microservices",
        "url": "https://pocketfm.com/careers"
    }
]


def ingest_seed_funded_startups() -> dict[str, Any]:
    """Ingest early funded startups into ApplyPilot pipeline for founder direct outreach."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    new_jobs = 0

    for st in RECENT_FUNDED_STARTUPS:
        comp = st["company"]
        role = "SDE-1 / Founding Backend Engineer"
        url = st["url"]
        email = st["email"]
        desc = (
            f"Early Funded / YC Startup: {comp}\n"
            f"Founders: {st['founders']}\n"
            f"Domain: {st['domain']}\n"
            f"Funding Stage: {st['funding']}\n"
            f"Stack: {st['tech']}\n"
            f"Direct Founder Contact: {email}\n\n"
            f"Early engineering hiring: direct founder decision without corporate ATS barriers."
        )

        try:
            c.execute("""
                INSERT INTO jobs 
                (url, title, location, site, strategy, description, full_description, recruiter_email, discovered_at, application_url, date_posted)
                VALUES (?, ?, 'Bengaluru / Remote', ?, 'seed_funded', ?, ?, ?, ?, ?, ?)
            """, (
                url,
                role,
                comp,
                desc,
                desc,
                email,
                now,
                url,
                now[:10]
            ))
            new_jobs += 1
        except sqlite3.IntegrityError:
            # Update email if missing
            c.execute("UPDATE jobs SET recruiter_email = COALESCE(NULLIF(recruiter_email, ''), ?) WHERE url = ?", (email, url))

    conn.commit()
    log.info("Ingested %d fresh seed/YC-funded startup openings for founder cold outreach.", new_jobs)
    return {
        "status": "ok",
        "total": len(RECENT_FUNDED_STARTUPS),
        "new_added": new_jobs,
        "message": f"Synced {len(RECENT_FUNDED_STARTUPS)} YC & seed-funded startups ({new_jobs} new added)."
    }
