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


# ── Dynamic Funding & YC Radar ───────────────────────────────────────────

import hashlib
import re
import xml.etree.ElementTree as ET
import httpx

POSITIVE_FUNDING_REGEX = re.compile(r"\b(raise|raises|raised|bags|secures|nets|funding)\b", re.IGNORECASE)
NEGATIVE_FUNDING_REGEX = re.compile(r"\b(fund|ipo|q[1-4]|loss|profit|revenue|in talks|looks to|plans to|weekly|digest|startups raised)\b", re.IGNORECASE)

RSS_FEEDS = [
    ("inc42", "https://inc42.com/feed/"),
    ("yourstory", "https://yourstory.com/feed"),
    ("isn", "https://indianstartupnews.com/rss"),
    ("ettech", "https://economictimes.indiatimes.com/tech/funding/rssfeeds/78570540.cms"),
    ("techcrunch", "https://techcrunch.com/category/startups/feed/"),
]

def filter_funding_headline(headline: str) -> bool:
    """Return True if headline matches positive funding regex and does not match negative exclusion regex."""
    if not headline:
        return False
    if not POSITIVE_FUNDING_REGEX.search(headline):
        return False
    if NEGATIVE_FUNDING_REGEX.search(headline):
        return False
    return True

def poll_funding_radar() -> dict[str, Any]:
    """Poll YC OSS, HN, and startup RSS feeds, extract funding leads, and store in SQLite."""
    from applypilot.discovery.ats import detect_ats_board
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    new_leads = 0

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    with httpx.Client(headers=headers, timeout=10.0, follow_redirects=True) as client:
        # 1. YC OSS Hiring API
        try:
            yc_res = client.get("https://yc-oss.github.io/api/companies/hiring.json")
            if yc_res.status_code == 200:
                companies = yc_res.json()
                for comp in companies[:30]:
                    name = comp.get("name", "")
                    if not name:
                        continue
                    lead_hash = hashlib.sha256(f"yc_oss:{name}".encode()).hexdigest()
                    desc = comp.get("one_liner", "")
                    ats_info = detect_ats_board(name.lower().replace(" ", ""))
                    ats_provider = ats_info.get("provider", "") if ats_info else ""
                    ats_slug = ats_info.get("slug", "") if ats_info else ""
                    
                    c.execute("""
                        INSERT OR IGNORE INTO funding_leads
                        (lead_hash, company, source, headline, article_url, round_amount, product_focus, ats_provider, ats_slug, status, discovered_at)
                        VALUES (?, ?, 'yc_oss', ?, ?, 'YC Batch', ?, ?, ?, 'NEW', ?)
                    """, (
                        lead_hash,
                        name,
                        f"{name} hiring on YC",
                        comp.get("url", f"https://www.ycombinator.com/companies/{comp.get('slug', '')}"),
                        desc,
                        ats_provider,
                        ats_slug,
                        now
                    ))
                    if c.rowcount > 0:
                        new_leads += 1
        except Exception as e:
            log.warning("YC OSS radar error: %s", e)

        # 2. Hacker News Launches
        try:
            hn_res = client.get("https://hnrss.org/launches")
            if hn_res.status_code == 200:
                root = ET.fromstring(hn_res.content)
                for item in root.findall(".//item")[:25]:
                    title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    lead_hash = hashlib.sha256(f"hn:{link or title}".encode()).hexdigest()
                    comp_name = title.replace("Launch HN: ", "").split(" - ")[0].split(" (")[0].strip()
                    c.execute("""
                        INSERT OR IGNORE INTO funding_leads
                        (lead_hash, company, source, headline, article_url, round_amount, product_focus, status, discovered_at)
                        VALUES (?, ?, 'hn_launch', ?, ?, 'Bootstrapped / Seed', ?, 'NEW', ?)
                    """, (
                        lead_hash,
                        comp_name,
                        title,
                        link,
                        title,
                        now
                    ))
                    if c.rowcount > 0:
                        new_leads += 1
        except Exception as e:
            log.warning("HN Launches radar error: %s", e)

        # 3. RSS Feeds
        for source_name, feed_url in RSS_FEEDS:
            try:
                r = client.get(feed_url)
                if r.status_code != 200:
                    continue
                root = ET.fromstring(r.content)
                for item in root.findall(".//item"):
                    title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    if not filter_funding_headline(title):
                        continue
                    lead_hash = hashlib.sha256(f"{source_name}:{link or title}".encode()).hexdigest()
                    # Extract crude company name from start of headline
                    comp_match = re.match(r"^([A-Z][a-zA-Z0-9\.\s]{1,25}?)\s+(?:raises|bags|secures|nets|in funding)", title, re.IGNORECASE)
                    comp_name = comp_match.group(1).strip() if comp_match else title[:30]

                    ats_info = detect_ats_board(comp_name.lower().replace(" ", ""))
                    ats_provider = ats_info.get("provider", "") if ats_info else ""
                    ats_slug = ats_info.get("slug", "") if ats_info else ""

                    c.execute("""
                        INSERT OR IGNORE INTO funding_leads
                        (lead_hash, company, source, headline, article_url, round_amount, product_focus, ats_provider, ats_slug, status, discovered_at)
                        VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, 'NEW', ?)
                    """, (
                        lead_hash,
                        comp_name,
                        source_name,
                        title,
                        link,
                        title,
                        ats_provider,
                        ats_slug,
                        now
                    ))
                    if c.rowcount > 0:
                        new_leads += 1
            except Exception as e:
                log.warning("RSS Feed radar error for %s (%s): %s", source_name, feed_url, e)

    conn.commit()
    return {
        "status": "ok",
        "new_leads": new_leads,
        "message": f"Funding radar synced successfully ({new_leads} new leads)."
    }
