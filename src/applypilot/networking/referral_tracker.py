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
import time
from datetime import datetime, timezone
from typing import Any

from applypilot.database import get_connection

log = logging.getLogger(__name__)


def init_referral_connection_tables(conn: sqlite3.Connection | None = None) -> None:
    """Ensure referral_connection_requests table exists and has all required columns."""
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
    # Ensure tailored message and resume columns exist for seamless followups
    cursor = c.cursor()
    cols = [col[1] for col in cursor.execute("PRAGMA table_info(referral_connection_requests)").fetchall()]
    if "tailored_msg" not in cols:
        try:
            cursor.execute("ALTER TABLE referral_connection_requests ADD COLUMN tailored_msg TEXT")
        except Exception:
            pass
    if "resume_path" not in cols:
        try:
            cursor.execute("ALTER TABLE referral_connection_requests ADD COLUMN resume_path TEXT")
        except Exception:
            pass
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
    job_rowid: int | None = None,
    tailored_msg: str = "",
    resume_path: str = ""
) -> dict[str, Any]:
    """Record a newly sent connection request for a company (with deduplication)."""
    conn = get_connection()
    init_referral_connection_tables(conn)

    now_iso = datetime.now(timezone.utc).isoformat()
    company_clean = company.strip()
    name_clean = person_name.strip()
    clean_url = profile_url.strip()

    if not company_clean or not name_clean:
        return {"status": "error", "message": "Company and Person Name are required."}

    cur = conn.cursor()
    # Check if already recorded to avoid duplicate entries
    existing = None
    if clean_url:
        existing = cur.execute(
            "SELECT id FROM referral_connection_requests WHERE profile_url = ?",
            (clean_url,)
        ).fetchone()
    if not existing:
        existing = cur.execute(
            "SELECT id FROM referral_connection_requests WHERE LOWER(company) = LOWER(?) AND LOWER(person_name) = LOWER(?)",
            (company_clean, name_clean)
        ).fetchone()

    if existing:
        req_id = existing[0]
        cur.execute("""
            UPDATE referral_connection_requests 
            SET headline = COALESCE(NULLIF(?, ''), headline),
                job_rowid = COALESCE(?, job_rowid),
                tailored_msg = COALESCE(NULLIF(?, ''), tailored_msg),
                resume_path = COALESCE(NULLIF(?, ''), resume_path)
            WHERE id = ?
        """, (headline.strip(), job_rowid, tailored_msg, resume_path, req_id))
        conn.commit()
        return {"status": "ok", "id": req_id, "company": company_clean, "person_name": name_clean, "existing": True}

    cur.execute("""
        INSERT INTO referral_connection_requests (
            company, person_name, profile_url, headline, is_alumni, degree,
            role_type, status, requested_at, referral_status, notes, job_rowid,
            tailored_msg, resume_path, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'requested', ?, 'pending', ?, ?, ?, ?, ?)
    """, (
        company_clean, name_clean, clean_url, headline.strip(),
        1 if is_alumni else 0, degree, role_type, now_iso, notes.strip(),
        job_rowid, tailored_msg, resume_path, now_iso
    ))
    conn.commit()
    return {"status": "ok", "id": cur.lastrowid, "company": company_clean, "person_name": name_clean, "existing": False}


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
            "notes": r["notes"],
            "tailored_msg": r.get("tailored_msg") or "",
            "resume_path": r.get("resume_path") or "",
            "job_rowid": r.get("job_rowid")
        })

    # Sort companies by most requested
    companies_summary = sorted(company_map.values(), key=lambda x: (x["accepted_count"], x["requested_count"]), reverse=True)

    # Calculate pending follow-ups (accepted but referral_status still pending)
    pending_followups = [
        r for r in requests_list
        if r["status"] in ("accepted", "replied_referral") and r["referral_status"] == "pending"
    ]

    return {
        "metrics": {
            "total_requested": total_requested,
            "total_accepted": total_accepted,
            "acceptance_rate": acceptance_rate,
            "total_referrals": total_referrals,
            "pending_acceptance": pending_acceptance,
            "pending_followups": len(pending_followups),
            "companies_count": len(companies_summary)
        },
        "companies": companies_summary,
        "pending_followups": pending_followups[:20],
        "recent_requests": requests_list[:50]
    }


def sync_sent_invitations_from_linkedin(max_check: int = 50, headless: bool = True) -> dict[str, Any]:
    """Scrapes LinkedIn Sent Invitations page to automatically discover & track requests sent by Deepak.
    
    Navigates to https://www.linkedin.com/mynetwork/invitation-manager/sent/
    and imports every person Deepak has invited into referral_connection_requests.
    This eliminates ANY manual typing or logging!
    """
    from playwright.sync_api import sync_playwright
    from applypilot.apply.chrome import launch_isolated_playwright_context, acquire_browser_lock
    from applypilot.networking.linkedin import (
        get_stored_cookies,
        is_linkedin_cooldown_active,
        trigger_linkedin_circuit_breaker,
        check_page_for_challenges_or_auth,
        AUTH_EXPIRED_OR_CHALLENGED,
    )

    # Safety check: Circuit breaker
    is_cooling, cool_reason = is_linkedin_cooldown_active()
    if is_cooling:
        log.warning("LinkedIn sync_sent_invitations_from_linkedin aborted: %s", cool_reason)
        return {"status": "error", "message": f"Circuit breaker active: {cool_reason}", "synced": 0}

    conn = get_connection()
    init_referral_connection_tables(conn)

    sent_invites = []
    try:
        with acquire_browser_lock():
            with sync_playwright() as p:
                context = launch_isolated_playwright_context(
                    p,
                    headless=headless,
                    color_scheme="dark",
                    viewport={"width": 1280, "height": 850},
                )

                existing_cookies = get_stored_cookies()
                if existing_cookies:
                    try:
                        context.add_cookies(existing_cookies)
                    except Exception:
                        pass

                page = context.pages[0] if context.pages else context.new_page()
                url = "https://www.linkedin.com/mynetwork/invitation-manager/sent/"
                response = page.goto(url, wait_until="domcontentloaded")
                time.sleep(5)

                status_code = response.status if response else None
                is_challenged, ch_reason = check_page_for_challenges_or_auth(page, status_code=status_code)
                if is_challenged:
                    trigger_linkedin_circuit_breaker(f"sync_sent_invitations: {ch_reason}", trigger_url=page.url)
                    context.close()
                    return {"status": "error", "message": ch_reason, "synced": 0}

                sent_invites = page.evaluate("""() => {
                    const results = [];
                    const links = Array.from(document.querySelectorAll('a[href*="/in/"]'));
                    const seen = new Set();
                    for (const a of links) {
                        const href = a.href.split('?')[0].replace(/\\/+$/, '');
                        if (!href || href.includes('mini-profile') || seen.has(href)) continue;
                        seen.add(href);

                        let el = a;
                        let candidateContainer = null;
                        for (let i = 0; i < 6 && el && el.tagName !== 'BODY'; i++) {
                            if (el.innerText && el.innerText.includes('Withdraw')) {
                                candidateContainer = el;
                                break;
                            }
                            el = el.parentElement;
                        }

                        if (candidateContainer) {
                            const text = candidateContainer.innerText;
                            const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                            const name = lines[0] || '';
                            const headline = lines[1] || '';
                            let sentTime = '';
                            for (const l of lines) {
                                if (l.toLowerCase().includes('sent ')) {
                                    sentTime = l;
                                    break;
                                }
                            }
                            results.push({ name, href, headline, sentTime });
                        }
                    }
                    return results;
                }""")
                context.close()
    except Exception as e:
        log.error("Failed to scrape sent invitations: %s", e)
        return {"status": "error", "message": str(e), "synced": 0}

    new_recorded = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for inv in sent_invites:
        name = inv.get("name", "").strip()
        p_url = inv.get("href", "").strip()
        headline = inv.get("headline", "").strip()
        sent_time = inv.get("sentTime", "")

        if not name or name.lower().startswith("people"):
            continue

        # Extract company heuristic from headline
        comp = "LinkedIn Network"
        if " at " in headline or " @ " in headline:
            part = headline.split(" at ")[-1] if " at " in headline else headline.split(" @ ")[-1]
            comp = part.split("|")[0].split("·")[0].split("•")[0].strip()
        elif "Building " in headline:
            comp = headline.split("Building ")[1].split("|")[0].strip()

        is_alumni = "rvce" in headline.lower() or "rv college" in headline.lower()

        # Record into referral CRM
        res = record_connection_request(
            company=comp,
            person_name=name,
            profile_url=p_url,
            headline=headline,
            is_alumni=is_alumni,
            degree="2nd",
            role_type="Engineer",
            notes=f"Auto-imported from LinkedIn Sent Manager ({sent_time})",
            tailored_msg="",
            resume_path=""
        )
        if not res.get("existing"):
            new_recorded += 1

    return {
        "status": "ok",
        "total_sent_found": len(sent_invites),
        "new_recorded": new_recorded
    }


def sync_accepted_connections_from_linkedin(max_check: int = 50, headless: bool = True) -> dict[str, Any]:
    """Scrapes LinkedIn recent connections list to detect accepted connection requests.
    
    Navigates to https://www.linkedin.com/mynetwork/invite-connect/connections/
    and matches recent connections against pending `requested` entries in the DB.
    When matched, auto-promotes status to `accepted`, generates/attaches tailored pitch message,
    and dispatches an alert (Telegram / WhatsApp).
    """
    from playwright.sync_api import sync_playwright
    from applypilot.apply.chrome import launch_isolated_playwright_context, acquire_browser_lock
    from applypilot.networking.linkedin import (
        get_stored_cookies,
        is_linkedin_cooldown_active,
        trigger_linkedin_circuit_breaker,
        check_page_for_challenges_or_auth,
        AUTH_EXPIRED_OR_CHALLENGED,
    )

    # Safety check: Circuit breaker
    is_cooling, cool_reason = is_linkedin_cooldown_active()
    if is_cooling:
        log.warning("LinkedIn sync_accepted_connections_from_linkedin aborted: %s", cool_reason)
        return {"status": "error", "message": f"Circuit breaker active: {cool_reason}", "matched_count": 0, "connections_scraped": 0}

    conn = get_connection()
    init_referral_connection_tables(conn)

    pending_rows = conn.execute(
        "SELECT id, company, person_name, profile_url, headline, job_rowid, tailored_msg, resume_path FROM referral_connection_requests WHERE status = 'requested'"
    ).fetchall()

    if not pending_rows:
        return {"status": "ok", "message": "No pending connection requests awaiting acceptance.", "matched_count": 0, "connections_scraped": 0}

    pending_requests = [dict(r) for r in pending_rows]

    recent_connections = []
    matched = []

    try:
        with acquire_browser_lock():
            with sync_playwright() as p:
                context = launch_isolated_playwright_context(
                    p,
                    headless=headless,
                    color_scheme="dark",
                    viewport={"width": 1280, "height": 850},
                )

                existing_cookies = get_stored_cookies()
                if existing_cookies:
                    try:
                        context.add_cookies(existing_cookies)
                    except Exception:
                        pass

                page = context.pages[0] if context.pages else context.new_page()
                url = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
                response = page.goto(url, wait_until="domcontentloaded")
                time_waited = 0
                while time_waited < 6:
                    page.wait_for_timeout(1000)
                    time_waited += 1

                status_code = response.status if response else None
                is_challenged, ch_reason = check_page_for_challenges_or_auth(page, status_code=status_code)
                if is_challenged:
                    trigger_linkedin_circuit_breaker(f"sync_accepted_connections: {ch_reason}", trigger_url=page.url)
                    context.close()
                    return {"status": "error", "message": ch_reason, "matched_count": 0, "connections_scraped": 0}
                context.close()
                return {"status": "error", "message": "LinkedIn authentication expired. Please run applypilot linkedin-login.", "matched_count": 0}

            # Extract recent connections list from page
            extracted = page.evaluate("""() => {
                const results = [];
                // Find connection card items
                const cards = document.querySelectorAll('li.mn-connection-card, div.mn-connection-card');
                for (const card of cards) {
                    const nameEl = card.querySelector('.mn-connection-card__name, span.mn-connection-card__name');
                    const linkEl = card.querySelector('a.mn-connection-card__link, a[href*="/in/"]');
                    const occupEl = card.querySelector('.mn-connection-card__occupation, div.mn-connection-card__occupation');
                    const timeEl = card.querySelector('time, span.time-badge');
                    
                    const name = nameEl ? nameEl.innerText.trim() : (linkEl ? linkEl.innerText.trim() : '');
                    const href = linkEl ? linkEl.href.split('?')[0].replace(/\\/+$/, '') : '';
                    const occupation = occupEl ? occupEl.innerText.trim() : '';
                    const connectedTime = timeEl ? timeEl.innerText.trim() : '';

                    if (name || href) {
                        results.push({ name, href, occupation, connectedTime });
                    }
                }
                return results;
            }""")

            recent_connections = extracted or []
            context.close()
    except Exception as e:
        log.error("Error during LinkedIn connections sync: %s", e)
        return {"status": "error", "message": str(e), "matched_count": 0}

    # Match extracted recent connections against pending referral requests
    now_iso = datetime.now(timezone.utc).isoformat()
    for conn_item in recent_connections:
        c_name = conn_item.get("name", "").strip().lower()
        c_href = conn_item.get("href", "").strip().rstrip("/").lower()

        for req in pending_requests:
            req_id = req["id"]
            req_name = req["person_name"].strip().lower()
            req_url = (req["profile_url"] or "").strip().rstrip("/").lower()

            is_match = False
            if req_url and c_href and (req_url in c_href or c_href in req_url):
                is_match = True
            elif req_name and c_name:
                # First name + last name or substring match
                req_parts = [p for p in req_name.split() if len(p) > 2]
                if req_name in c_name or c_name in req_name:
                    is_match = True
                elif req_parts and all(p in c_name for p in req_parts):
                    is_match = True

            if is_match:
                # Update status to accepted
                conn.execute(
                    "UPDATE referral_connection_requests SET status = 'accepted', accepted_at = COALESCE(accepted_at, ?) WHERE id = ?",
                    (now_iso, req_id)
                )
                conn.commit()
                matched.append({
                    "id": req_id,
                    "person_name": req["person_name"],
                    "company": req["company"],
                    "profile_url": req["profile_url"] or conn_item.get("href", "")
                })

                # Send automatic alert (Telegram / WhatsApp)
                try:
                    from applypilot.automation.telegram_notifier import send_telegram_alert
                    msg = (
                        f"🎉 *LinkedIn Connection Accepted!*\n\n"
                        f"👤 *{req['person_name']}* at *{req['company']}* accepted your connection request.\n"
                        f"⚡ *Action:* Tailored referral pitch and resume are ready to send in 1 click!\n"
                        f"🔗 [Open Dashboard](http://localhost:8765)"
                    )
                    send_telegram_alert(msg)
                except Exception as te:
                    log.debug("Telegram alert error on referral acceptance: %s", te)

    return {
        "status": "ok",
        "connections_scraped": len(recent_connections),
        "matched_count": len(matched),
        "matched": matched
    }


def generate_tailored_pitch_for_request(request_id: int) -> dict[str, Any]:
    """Generate or retrieve a customized referral pitch message and resume for an accepted connection.
    
    If job_rowid is associated, pulls the specific role title and job details.
    Uses Deepak's verified credentials (Meesho SDE-1, RVCE CSE '25, Java/Go/Kafka/Redis, 0 days notice).
    Also copies the message to system clipboard and ensures tailored resume exists.
    """
    import subprocess
    from applypilot.config import APP_DIR, RESUME_PATH
    from applypilot.networking.outreach import generate_outreach_messages

    conn = get_connection()
    init_referral_connection_tables(conn)

    row = conn.execute(
        "SELECT * FROM referral_connection_requests WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not row:
        return {"status": "error", "message": f"Connection request {request_id} not found."}

    req = dict(row)
    person_name = req.get("person_name", "there").strip()
    first_name = person_name.split()[0] if person_name else "there"
    company = req.get("company", "your company").strip()
    is_alumni = bool(req.get("is_alumni"))
    job_rowid = req.get("job_rowid")
    profile_url = req.get("profile_url") or ""

    role_title = "Backend Engineer"
    apply_url = ""
    resume_path = req.get("resume_path") or ""

    if job_rowid:
        job_row = conn.execute(
            "SELECT title, url, application_url, tailored_resume_path FROM jobs WHERE rowid = ?",
            (job_rowid,)
        ).fetchone()
        if job_row:
            role_title = job_row["title"] or role_title
            apply_url = job_row["application_url"] or job_row["url"] or ""
            if not resume_path and job_row["tailored_resume_path"]:
                resume_path = job_row["tailored_resume_path"]

    # If no resume attached yet, check default tailored or base resume
    if not resume_path:
        base_pdf = APP_DIR.parent / "all resumes"
        if base_pdf.exists():
            for f in base_pdf.glob("*.pdf"):
                resume_path = str(f)
                break

    # Build customized referral follow-up message
    if req.get("tailored_msg"):
        custom_message = req["tailored_msg"]
    elif is_alumni:
        custom_message = (
            f"Hi {first_name},\n\n"
            f"Thanks for connecting! I noticed you are at {company}.\n\n"
            f"I graduated from RVCE in CSE ('25) and am currently working as an SDE-1 Backend Engineer at Meesho.\n\n"
            f"I came across the {role_title} opening at {company} and would be really grateful if you could refer an RVCE junior or pass my profile to the hiring team. "
            f"I primarily work with Java, Go, Kafka, Redis, and distributed microservices, and I have immediate availability (0 days notice).\n\n"
            f"I've attached my resume for your review. Would you be open to putting in a referral?\n\n"
            f"Best regards,\nDeepak S H | +91 8431433659\nhttps://github.com/Deepak-S-H"
        )
    else:
        custom_message = (
            f"Hi {first_name},\n\n"
            f"Thanks for accepting my connection request!\n\n"
            f"I'm an SDE-1 Backend Engineer at Meesho (RVCE '25, CGPA 8.92). I build distributed transaction and reconciliation pipelines using Java, Go, Kafka, Spring Boot, and Redis.\n\n"
            f"I saw an active opening for {role_title} at {company} and would love to be considered. Could you kindly refer my profile to the team?\n\n"
            f"Quick details:\n"
            f"• Current: SDE-1 Backend @ Meesho\n"
            f"• Core Tech: Java, Go, Spring Boot, Kafka, Redis, Distributed Systems\n"
            f"• Notice Period: Immediate / 0 days\n"
            f"• Tailored resume is attached.\n\n"
            f"Thank you so much for your time and help!\n\n"
            f"Best regards,\nDeepak S H | +91 8431433659\nhttps://www.linkedin.com/in/deepak-s-h-82b772254"
        )

    # Save tailored message and resume path back to request
    conn.execute(
        "UPDATE referral_connection_requests SET tailored_msg = ?, resume_path = ? WHERE id = ?",
        (custom_message, resume_path, request_id)
    )
    conn.commit()

    # Copy message to clipboard automatically for zero-friction paste
    try:
        subprocess.run(["powershell", "-Command", f"Set-Clipboard -Value @'\n{custom_message}\n'@"], check=False)
    except Exception:
        pass

    return {
        "status": "ok",
        "request_id": request_id,
        "person_name": person_name,
        "company": company,
        "role_title": role_title,
        "profile_url": profile_url,
        "message": custom_message,
        "resume_path": resume_path
    }


def auto_connect_referral_from_job_url(
    job_url: str,
    max_people: int = 5,
    headless: bool = False,
    send_connection: bool = False,
) -> dict[str, Any]:
    """Given a LinkedIn job URL: extract company + role, find connections, optionally send requests.

    Workflow:
      1. Parse company name and role title from the LinkedIn job URL (via Playwright).
      2. Call search_linkedin_connections() to find 1st/2nd-degree engineers at that company.
      3. For each found person:
         a. Record them in referral_connection_requests (status='discovered').
         b. If send_connection=True → call compose_referral_dm(..., action_type='connect')
            to pre-fill the connection note, and let Deepak click Send.
      4. Return summary dict.

    Args:
        job_url:         LinkedIn job posting URL.
        max_people:      Max connections to surface (default 5).
        headless:        Whether to scrape job details headlessly (default True).
        send_connection: If True, sends connection request for each person.
                         If False (default), only discovers and records — no browser pop-ups.

    Returns:
        dict with keys: status, company, role_title, found (list of person dicts), sent_count
    """
    import urllib.parse

    conn = get_connection()
    init_referral_connection_tables(conn)

    job_url = job_url.strip()
    if not job_url.startswith("http"):
        return {"status": "error", "message": "Invalid job URL. Must start with http/https."}

    # --- Step 1: Extract company + role from job URL ---
    company = ""
    role_title = "Backend Engineer"
    job_rowid: int | None = None

    # First check if job is already in our DB
    try:
        row = conn.execute(
            "SELECT title, url, company FROM jobs WHERE url = ? OR application_url = ?",
            (job_url, job_url)
        ).fetchone()
        if row:
            role_title = row["title"] or role_title
            # Try to get company from title or use 'company' col if exists
            try:
                company = row["company"] or ""
            except Exception:
                company = ""
            job_rowid_row = conn.execute(
                "SELECT rowid FROM jobs WHERE url = ? OR application_url = ?",
                (job_url, job_url)
            ).fetchone()
            if job_rowid_row:
                job_rowid = job_rowid_row[0]
    except Exception:
        pass

    # If company not in DB, try to scrape it from LinkedIn job page
    if not company:
        try:
            from playwright.sync_api import sync_playwright
            from applypilot.apply.chrome import launch_isolated_playwright_context, acquire_browser_lock
            from applypilot.networking.linkedin import get_stored_cookies

            with acquire_browser_lock():
                with sync_playwright() as p:
                    ctx = launch_isolated_playwright_context(
                        p,
                        headless=True,
                        color_scheme="dark",
                        viewport={"width": 1280, "height": 850},
                    )
                    cookies = get_stored_cookies()
                    if cookies:
                        try:
                            ctx.add_cookies(cookies)
                        except Exception:
                            pass

                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    page.goto(job_url, wait_until="domcontentloaded")
                    time.sleep(4)

                extracted = page.evaluate("""() => {
                    const compEl = document.querySelector(
                        'a.topcard__org-name-link, span.topcard__flavor:first-child, '
                        + '.job-details-jobs-unified-top-card__company-name a, '
                        + 'a[data-tracking-control-name*="company"], '
                        + '.jobs-unified-top-card__company-name'
                    );
                    const titleEl = document.querySelector(
                        'h1.topcard__title, h1.jobs-unified-top-card__job-title, '
                        + 'h1[class*="job-title"]'
                    );
                    return {
                        company: compEl ? compEl.innerText.trim() : '',
                        role_title: titleEl ? titleEl.innerText.trim() : ''
                    };
                }""")
                ctx.close()

                company = extracted.get("company", "").strip()
                if extracted.get("role_title"):
                    role_title = extracted["role_title"].strip()

        except Exception as e:
            log.warning("Could not scrape company from job URL %s: %s", job_url, e)

    # Fallback: try to extract company from URL slug
    if not company:
        try:
            parsed = urllib.parse.urlparse(job_url)
            path_parts = [p for p in parsed.path.split("/") if p]
            # e.g. /jobs/view/1234567?refId=...  — sometimes has company in query
            q = urllib.parse.parse_qs(parsed.query)
            if "currentJobId" in q:
                pass  # can't determine company from ID alone
        except Exception:
            pass

    if not company:
        return {
            "status": "error",
            "message": "Could not determine company name from the job URL. Try pasting the company name manually.",
            "job_url": job_url
        }

    log.info("auto_connect_referral: company=%s, role=%s, url=%s", company, role_title, job_url)

    # --- Step 2: Search LinkedIn for connections at this company ---
    try:
        from applypilot.networking.linkedin import search_linkedin_connections
        connections = search_linkedin_connections(
            company=company,
            role="backend engineer sde",
            max_results=max_people
        )
    except Exception as e:
        log.error("search_linkedin_connections failed: %s", e)
        connections = []

    if not connections or (len(connections) == 1 and connections[0].get("error")):
        return {
            "status": "error",
            "message": f"LinkedIn not authenticated or no connections found at '{company}'. Run 'applypilot linkedin login' first.",
            "company": company,
            "role_title": role_title,
            "found": [],
            "sent_count": 0
        }

    # --- Step 3: Record & optionally connect ---
    sent_count = 0
    recorded = []

    for person in connections[:max_people]:
        pname = person.get("name", "").strip()
        purl = person.get("profile_url", "").strip()
        pheadline = person.get("headline", "").strip()
        pdegree = person.get("degree", "2nd")
        is_alumni = bool(person.get("is_alumni", False))

        if not pname:
            continue

        # Build a brief connection note (max 295 chars)
        is_alumni_flag = is_alumni or "rvce" in pheadline.lower() or "rv college" in pheadline.lower()
        if is_alumni_flag:
            short_note = (
                f"Hi {pname.split()[0]}, RVCE CSE '25 junior here, SDE-1 Backend @ Meesho (Java/Go/Kafka). "
                f"Saw the {role_title} role at {company} — would you be open to referring me?"
            )[:295]
        else:
            short_note = (
                f"Hi {pname.split()[0]}, I'm an SDE-1 Backend Engineer at Meesho (RVCE '25, Java/Go/Kafka/Redis). "
                f"Interested in the {role_title} opening at {company}. Would you be open to connecting?"
            )[:295]

        # Record in CRM
        rec_result = record_connection_request(
            company=company,
            person_name=pname,
            profile_url=purl,
            headline=pheadline,
            is_alumni=is_alumni_flag,
            degree=pdegree,
            role_type="Engineer",
            notes=f"Auto-discovered for {role_title} @ {company} | job_url={job_url}",
            job_rowid=job_rowid,
            tailored_msg=short_note,
        )

        p_record = {
            "id": rec_result.get("id"),
            "person_name": pname,
            "profile_url": purl,
            "headline": pheadline,
            "degree": pdegree,
            "is_alumni": is_alumni_flag,
            "existing": rec_result.get("existing", False),
            "short_note": short_note,
        }
        recorded.append(p_record)

        # Optionally send connection request in background
        if send_connection and purl:
            try:
                from applypilot.networking.linkedin import connect_in_background
                conn_res = connect_in_background(profile_url=purl, note=short_note)
                if conn_res.get("ok"):
                    sent_count += 1
                    # Update status in referral_connection_requests
                    cur.execute(
                        "UPDATE referral_connection_requests SET status = 'requested', notes = ? WHERE id = ?",
                        (f"Sent in background via {conn_res.get('method')}", rec_result.get("id"))
                    )
                    conn.commit()
                else:
                    cur.execute(
                        "UPDATE referral_connection_requests SET notes = ? WHERE id = ?",
                        (f"CONNECT_FAILED: {conn_res.get('error')}", rec_result.get("id"))
                    )
                    conn.commit()
                time.sleep(2)  # Brief pause between background requests
            except Exception as ce:
                log.warning("Could not send background connection for %s: %s", pname, ce)

    return {
        "status": "ok",
        "company": company,
        "role_title": role_title,
        "job_url": job_url,
        "found": recorded,
        "found_count": len(recorded),
        "sent_count": sent_count,
        "message": (
            f"Found {len(recorded)} connection(s) at {company} for '{role_title}'. "
            + (f"Sent {sent_count} background connection request(s) via API/Headless." if send_connection else
               "Recorded in CRM — click '🤝 Send Request' per person to connect.")
        )
    }

