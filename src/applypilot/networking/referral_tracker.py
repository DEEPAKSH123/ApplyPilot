"""Referral Connection Requests Tracker & CRM Engine for ApplyPilot.

Tracks:
1. Connection requests sent to employees/alumni per company for referral purposes.
2. Acceptance status ('requested', 'accepted', 'replied_referral', 'declined', 'withdrawn').
3. Company-wise rollup: Total Requested vs Accepted vs Referrals Secured.
4. Auto-reminders after 24-48 hours when requests are accepted to send the referral pitch with tailored resume.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from applypilot.database import get_connection

log = logging.getLogger(__name__)


def init_referral_connection_tables(conn: sqlite3.Connection | None = None) -> None:
    """Ensure referral_connection_requests table exists."""
    c = conn or get_connection()
    c.execute("""
        CREATE TABLE IF NOT EXISTS referral_connection_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            person_name TEXT NOT NULL,
            profile_url TEXT,
            headline TEXT,
            is_alumni INTEGER DEFAULT 0,
            degree TEXT DEFAULT '2nd',
            role_type TEXT DEFAULT 'Engineer',
            status TEXT DEFAULT 'requested', -- 'requested', 'accepted', 'replied_referral', 'declined'
            requested_at TEXT,
            accepted_at TEXT,
            referral_status TEXT DEFAULT 'pending', -- 'pending', 'pitched', 'referred', 'closed'
            notes TEXT,
            job_rowid INTEGER,
            created_at TEXT
        )
    """)
    c.commit()


def record_connection_request(
    company: str,
    person_name: str,
    profile_url: str = "",
    headline: str = "",
    is_alumni: bool = False,
    degree: str = "2nd",
    role_type: str = "Engineer",
    notes: str = "",
    job_rowid: int | None = None
) -> dict[str, Any]:
    """Record a newly sent connection request for a company."""
    conn = get_connection()
    init_referral_connection_tables(conn)

    now_iso = datetime.now(timezone.utc).isoformat()
    company_clean = company.strip()
    name_clean = person_name.strip()

    if not company_clean or not name_clean:
        return {"status": "error", "message": "Company and Person Name are required."}

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO referral_connection_requests (
            company, person_name, profile_url, headline, is_alumni, degree,
            role_type, status, requested_at, referral_status, notes, job_rowid, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'requested', ?, 'pending', ?, ?, ?)
    """, (
        company_clean, name_clean, profile_url.strip(), headline.strip(),
        1 if is_alumni else 0, degree, role_type, now_iso, notes.strip(),
        job_rowid, now_iso
    ))
    conn.commit()
    return {"status": "ok", "id": cur.lastrowid, "company": company_clean, "person_name": name_clean}


def update_connection_status(
    request_id: int,
    status: str,
    referral_status: str | None = None,
    notes: str | None = None
) -> dict[str, Any]:
    """Update status of a connection request (e.g. accepted, pitched, referred)."""
    conn = get_connection()
    init_referral_connection_tables(conn)

    now_iso = datetime.now(timezone.utc).isoformat()
    updates = ["status = ?"]
    params: list[Any] = [status]

    if status == "accepted":
        updates.append("accepted_at = COALESCE(accepted_at, ?)")
        params.append(now_iso)

    if referral_status:
        updates.append("referral_status = ?")
        params.append(referral_status)

    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)

    params.append(request_id)
    conn.execute(f"UPDATE referral_connection_requests SET {', '.join(updates)} WHERE id = ?", tuple(params))
    conn.commit()
    return {"status": "ok", "id": request_id, "status_value": status}


def get_referral_network_summary() -> dict[str, Any]:
    """Get full breakdown: company-level aggregation, overall totals, and individual requests."""
    conn = get_connection()
    init_referral_connection_tables(conn)

    # 1. Total counts
    rows = conn.execute("""
        SELECT * FROM referral_connection_requests ORDER BY requested_at DESC
    """).fetchall()

    requests_list = [dict(r) for r in rows]

    total_requested = len(requests_list)
    total_accepted = sum(1 for r in requests_list if r["status"] in ("accepted", "replied_referral"))
    total_referrals = sum(1 for r in requests_list if r["referral_status"] in ("referred", "pitched"))
    pending_acceptance = sum(1 for r in requests_list if r["status"] == "requested")

    acceptance_rate = round((total_accepted / total_requested * 100), 1) if total_requested > 0 else 0.0

    # 2. Company-wise breakdown
    company_map: dict[str, dict[str, Any]] = {}
    for r in requests_list:
        comp = r["company"]
        if comp not in company_map:
            company_map[comp] = {
                "company": comp,
                "requested_count": 0,
                "accepted_count": 0,
                "referral_count": 0,
                "people": []
            }
        company_map[comp]["requested_count"] += 1
        if r["status"] in ("accepted", "replied_referral"):
            company_map[comp]["accepted_count"] += 1
        if r["referral_status"] in ("referred", "pitched"):
            company_map[comp]["referral_count"] += 1
        company_map[comp]["people"].append({
            "id": r["id"],
            "person_name": r["person_name"],
            "profile_url": r["profile_url"],
            "headline": r["headline"],
            "is_alumni": bool(r["is_alumni"]),
            "status": r["status"],
            "requested_at": r["requested_at"],
            "accepted_at": r["accepted_at"],
            "referral_status": r["referral_status"],
            "notes": r["notes"]
        })

    # Sort companies by most requested
    companies_summary = sorted(company_map.values(), key=lambda x: (x["accepted_count"], x["requested_count"]), reverse=True)

    return {
        "metrics": {
            "total_requested": total_requested,
            "total_accepted": total_accepted,
            "acceptance_rate": acceptance_rate,
            "total_referrals": total_referrals,
            "pending_acceptance": pending_acceptance,
            "companies_count": len(companies_summary)
        },
        "companies": companies_summary,
        "recent_requests": requests_list[:50]
    }
