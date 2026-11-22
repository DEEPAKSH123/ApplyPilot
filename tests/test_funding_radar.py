"""Unit tests for Pre-Post Startup Funding and YC Radar."""

import sqlite3
import pytest
from applypilot.database import get_connection, init_db
from applypilot.discovery.seed_startups import filter_funding_headline


def test_positive_and_negative_regex_filtering():
    """Verify positive funding verbs pass and negative exclusion keywords are filtered out."""
    # Positive matches
    assert filter_funding_headline("Bengaluru AI startup bags $5M in Seed funding") is True
    assert filter_funding_headline("Fintech player secures $12M Series A round") is True
    assert filter_funding_headline("SaaS company raises capital to expand engineering team") is True
    assert filter_funding_headline("Logistics platform nets $3M seed investment") is True

    # Negative exclusion matches
    assert filter_funding_headline("VC firm launches new $100M fund for India") is False
    assert filter_funding_headline("Tech giant posts Q3 revenue loss") is False
    assert filter_funding_headline("Startup looks to raise $10M next quarter") is False
    assert filter_funding_headline("Weekly funding digest: Indian startups raised $50M") is False
    assert filter_funding_headline("Fintech firm plans to file for IPO") is False


def test_funding_leads_persistence_and_deduplication(tmp_path):
    """Verify funding_leads table correctly persists leads and deduplicates repeated runs."""
    db_file = tmp_path / "test_funding.db"
    conn = init_db(db_file)

    # Insert lead
    lead_hash = "abc123hash"
    conn.execute(
        """
        INSERT OR IGNORE INTO funding_leads 
        (lead_hash, company, source, headline, article_url, round_amount, product_focus, status, discovered_at)
        VALUES (?, 'Kula', 'inc42', 'Kula raises $2.7M', 'https://inc42.com/kula', '$2.7M', 'Recruitment AI', 'NEW', '2026-11-20T10:00:00Z')
        """,
        (lead_hash,),
    )
    conn.commit()

    # Re-insert exact same lead_hash
    conn.execute(
        """
        INSERT OR IGNORE INTO funding_leads 
        (lead_hash, company, source, headline, article_url, round_amount, product_focus, status, discovered_at)
        VALUES (?, 'Kula', 'inc42', 'Kula raises $2.7M', 'https://inc42.com/kula', '$2.7M', 'Recruitment AI', 'NEW', '2026-11-20T10:00:00Z')
        """,
        (lead_hash,),
    )
    conn.commit()

    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM funding_leads WHERE lead_hash = ?", (lead_hash,))
    assert c.fetchone()[0] == 1
