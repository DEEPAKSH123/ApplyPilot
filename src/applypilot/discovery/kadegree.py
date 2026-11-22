"""KaDegree (Kannada Referral Community) Job Ingestion Pipeline.

Connects to KaDegree's referral platform (https://referral-community.kadegree.in)
using the candidate's authenticated session from Brave browser, discovers internal
referral openings and shared walk-in/portal jobs posted by Kannadiga tech professionals,
and ingests high-match SDE-I / Backend roles directly into ApplyPilot.
"""

import glob
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from applypilot.config import APP_DIR, load_search_config
from applypilot.database import get_connection, store_jobs_deduped
from applypilot.export.csv_export import export_opportunities_csv

log = logging.getLogger(__name__)

TOKEN_FILE = APP_DIR / "kadegree_token.json"
BASE_URL = "https://referral-community.kadegree.in/api"


def get_krc_token() -> str | None:
    """Retrieve KaDegree auth token from token cache or Brave browser local storage."""
    # 1. Check cached token file
    if TOKEN_FILE.exists():
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                token = data.get("token")
                if token and len(token) > 50:
                    return token.strip()
        except Exception as e:
            log.debug("Could not read token from %s: %s", TOKEN_FILE, e)

    # 2. Extract dynamically from Brave's Local Storage leveldb
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    brave_ls = os.path.join(
        local_app_data,
        "BraveSoftware",
        "Brave-Browser",
        "User Data",
        "Default",
        "Local Storage",
        "leveldb",
    )

    if os.path.exists(brave_ls):
        for fpath in glob.glob(os.path.join(brave_ls, "*")):
            if fpath.endswith(".log") or fpath.endswith(".ldb"):
                try:
                    with open(fpath, "rb") as f:
                        data = f.read()
                    idx = 0
                    while True:
                        idx = data.find(b"krc_token", idx)
                        if idx == -1:
                            break
                        raw = data[idx : idx + 450]
                        m = re.search(
                            rb"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
                            raw,
                        )
                        if m:
                            tok = m.group(0).decode("ascii")
                            # Verify valid length
                            if len(tok) >= 150:
                                try:
                                    with open(TOKEN_FILE, "w", encoding="utf-8") as tf:
                                        json.dump({"token": tok}, tf)
                                except Exception:
                                    pass
                                return tok
                        idx += 1
                except Exception:
                    continue
    return None


def fetch_kadegree_api(path: str, token: str) -> list | dict | None:
    """Make authenticated request to KaDegree REST API."""
    url = f"{BASE_URL}{path}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            log.warning("KaDegree session token expired or invalid (HTTP 401).")
        else:
            log.warning("HTTP error fetching %s: %s", path, e)
        return None
    except Exception as e:
        log.warning("Error fetching %s from KaDegree: %s", path, e)
        return None


def fetch_all_community_openings(token: str) -> list[dict]:
    """Fetch all open referral openings across tech/IT categories."""
    search_queries = [
        "",
        "backend",
        "software",
        "engineer",
        "developer",
        "sde",
        "java",
        "golang",
        "python",
        "cloud",
        "data",
        "full stack",
        "distributed",
        "api",
        "platform",
        "infrastructure",
        "spring",
        "microservices",
        "bengaluru",
        "bangalore",
        "remote",
        "pune",
        "hyderabad",
    ]

    all_openings = {}
    for term in search_queries:
        endpoint = (
            f"/openings?field=it&q={urllib.parse.quote(term)}"
            if term
            else "/openings?field=it"
        )
        res = fetch_kadegree_api(endpoint, token)
        if isinstance(res, list):
            for item in res:
                if item.get("id"):
                    all_openings[item["id"]] = item

    log.info("Discovered %d unique raw openings from KaDegree community.", len(all_openings))
    return list(all_openings.values())


def filter_and_format_kadegree_jobs(openings: list[dict]) -> list[dict]:
    """Filter openings against candidate profile & guardrails, format for ApplyPilot DB."""
    cfg = load_search_config()
    reject_patterns = [
        rp.lower() for rp in cfg.get("location", {}).get("reject_patterns", [])
    ]
    reject_patterns.extend(["us candidates only", "san francisco", "united states", "canada", "london", "uk only"])

    seniority_cfg = cfg.get("seniority", {})
    reject_titles = [
        t.lower()
        for t in seniority_cfg.get(
            "reject_titles",
            [
                "director",
                "head",
                "architect",
                "principal",
                "manager",
                "tech lead",
                "staff",
            ],
        )
    ]
    reject_titles.extend([
        "network engineer", "wireless", "ios", "android", "frontend developer",
        "frontend engineer", "ui/ux", "tutor", "trainer", "tableau", "power bi",
        "bi developer", "sap", "abap", "salesforce", "functional consultant",
        "asic", "fpga", "hardware", "silicon", "verification", "support",
        "manual qa", "tester", "test engineer", "data entry", "scrum master",
        "business analyst", "graphic designer", "content writer", "telecaller",
        "talent acquisition", "hr", "recruiter", "sales", "marketing",
        "operations", "consultant", "intern"
    ])

    tech_keywords = [
        "sde",
        "software",
        "backend",
        "developer",
        "engineer",
        "java",
        "golang",
        "microservices",
        "distributed",
        "full stack",
        "cloud",
        "aws",
        "python",
        "api",
    ]

    formatted_jobs = []

    for op in openings:
        role = op.get("role") or ""
        role_lower = role.lower()
        company = op.get("company") or op.get("referrer_company") or "Tech Company"
        city = op.get("city") or "Bengaluru"
        city_lower = city.lower()
        exp = op.get("experience") or ""
        exp_lower = exp.lower()
        desc = op.get("description") or ""
        skills = op.get("skills") or ""
        referrer_name = op.get("referrer_name") or "Community Member"
        slots_left = op.get("slots_left", 0)
        apply_mode = op.get("apply_mode") or "referral"
        resume_email = op.get("resume_email")
        job_link = op.get("job_link")

        # 1. Seniority reject check
        if any(st in role_lower for st in reject_titles):
            continue

        # 2. Location reject check
        text_for_loc = f"{city_lower} {desc.lower()}"
        if any(rp in text_for_loc for rp in reject_patterns):
            continue

        # 3. Core Software / Developer / SDE role requirement
        core_role_patterns = [
            "sde", "software", "backend", "developer", "engineer", "java", "golang",
            "full stack", "cloud", "platform", "infrastructure", "distributed", "api"
        ]
        if not any(p in role_lower for p in core_role_patterns):
            continue

        # 4. Experience check (Deepak S H has 1.3 YOE, sweet spot 0-4 yrs)
        exp_m = re.search(r'(\d+)\+?\s*(?:-\s*(\d+))?\s*(?:years?|yrs?)', exp_lower)
        if exp_m and int(exp_m.group(1)) >= 5:
            continue

        # 5. Relevance for backend/SDE
        text_for_tech = f"{role_lower} {skills.lower()} {desc.lower()}"
        if not any(k in text_for_tech for k in tech_keywords):
            continue

        kadegree_url = f"https://referral-community.kadegree.in/openings/{op['id']}"
        app_url = job_link if (job_link and str(job_link).startswith("http")) else kadegree_url

        full_desc = (
            f"=== KaDegree Kannada Referral Community Opening ===\n"
            f"Company: {company}\n"
            f"Role: {role}\n"
            f"Experience: {exp}\n"
            f"Location: {city} ({op.get('work_mode') or 'Flexible'})\n"
            f"Referrer: {referrer_name} ({op.get('referrer_company') or company}) {'[VERIFIED REFERRER]' if op.get('referrer_verified') else ''}\n"
            f"Referral Slots Left: {slots_left} of {op.get('slots', 0)}\n"
            f"Apply Mode: {apply_mode}\n"
            f"Required Skills: {skills}\n"
            f"KaDegree Link: {kadegree_url}\n\n"
            f"Description:\n{desc}\n"
        )

        # Candidate fit score calculation
        score = 7  # Baseline for vetted community referral
        reasoning = []
        if any(b in role_lower for b in ["backend", "sde", "software dev engineer", "software engineer", "java", "golang"]):
            score += 1
            reasoning.append("Direct match for SDE/Backend role.")
        if any(ts in text_for_tech for ts in ["java", "kafka", "redis", "spring", "golang", "distributed", "microservices"]):
            score += 1
            reasoning.append("Tech stack overlap with candidate profile (Java/Go/Kafka/Redis).")
        if any(yr in exp_lower for yr in ["fresher", "1–3", "0-2", "1-2"]):
            reasoning.append(f"Ideal candidate experience bracket ({exp}).")
        elif "6+" in exp_lower:
            score -= 1
            reasoning.append(f"Lists higher experience ({exp}), but Kannada community referral available.")

        score = max(5, min(10, score))

        job_dict = {
            "url": kadegree_url,
            "title": role,
            "site": company,
            "location": f"{city}, India" if "india" not in city_lower else city,
            "strategy": "kadegree_community",
            "application_url": app_url,
            "recruiter_email": resume_email,
            "salary": f"{slots_left} slots left" if slots_left else None,
            "description": f"KaDegree Referral by {referrer_name} ({company}). {slots_left} slots left. Skills: {skills}",
            "full_description": full_desc,
            "fit_score": score,
            "score_reasoning": f"KaDegree Community Referral Fit: {score}/10. " + " ".join(reasoning),
        }
        formatted_jobs.append(job_dict)

    return formatted_jobs


def sync_kadegree_jobs(conn=None) -> dict:
    """Sync openings from KaDegree, persist to SQLite DB and export opportunities.csv."""
    token = get_krc_token()
    if not token:
        log.error("Could not obtain KaDegree community auth token. Ensure Brave is logged in.")
        return {"status": "error", "message": "KaDegree token not found. Please log into KaDegree in Brave."}

    openings = fetch_all_community_openings(token)
    if not openings:
        return {"status": "error", "message": "Failed to fetch openings from KaDegree API."}

    formatted_jobs = filter_and_format_kadegree_jobs(openings)

    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    try:
        new_count, url_dupes, cross_dupes = store_jobs_deduped(
            conn, formatted_jobs, site="KaDegree Community", strategy="kadegree_community"
        )
        # Update fit_scores in DB for any newly stored jobs
        for job in formatted_jobs:
            conn.execute(
                "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ? AND fit_score IS NULL",
                (
                    job["fit_score"],
                    job["score_reasoning"],
                    datetime.now(timezone.utc).isoformat(),
                    job["url"],
                ),
            )
        conn.commit()

        # Sync candidate referral requests (/api/requests/mine)
        try:
            sync_my_referral_requests(token=token, conn=conn)
        except Exception as e:
            log.warning("Could not sync sent referral requests: %s", e)

        # Update opportunities.csv in place
        export_opportunities_csv()

        result = {
            "status": "ok",
            "total_fetched": len(openings),
            "relevant_matches": len(formatted_jobs),
            "new_stored": new_count,
            "duplicates": url_dupes + cross_dupes,
        }
        log.info("KaDegree sync complete: %s", result)
        return result
    finally:
        if close_conn:
            conn.close()


def sync_my_referral_requests(token: str | None = None, conn=None) -> dict:
    """Sync referral requests sent by candidate on KaDegree directly into ApplyPilot tracker."""
    if not token:
        token = get_krc_token()
    if not token:
        return {"status": "error", "message": "KaDegree token not found."}

    data = fetch_kadegree_api("/requests/mine", token)
    if not data or not isinstance(data, list):
        return {"status": "ok", "synced_requests": 0, "items": []}

    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    updated_count = 0
    try:
        cur = conn.cursor()
        for req in data:
            comp = req.get("company") or ""
            role = req.get("role") or ""
            req_status = req.get("status") or "requested"
            op_id = req.get("opening_id") or ""
            created_at = req.get("created_at") or datetime.now(timezone.utc).isoformat()

            # Map KaDegree referral request status:
            # requested -> asked_referral (waiting for referrer)
            # accepted  -> applied (referrer accepted referral request and submitted to internal portal)
            # declined  -> declined
            if req_status == "accepted":
                mapped_status = "applied"
            elif req_status == "requested":
                mapped_status = "asked_referral"
            else:
                mapped_status = req_status

            cur.execute(
                "SELECT rowid, apply_status FROM jobs WHERE (url LIKE ? OR (site LIKE ? AND title LIKE ?))",
                (f"%{op_id}%", f"%{comp}%", f"%{role}%")
            )
            row = cur.fetchone()
            if row:
                rowid, cur_status = row[0], row[1]
                if cur_status != mapped_status and cur_status not in ("interview", "oa", "rejected"):
                    cur.execute(
                        "UPDATE jobs SET apply_status = ?, application_stage = ?, applied_at = COALESCE(applied_at, ?) WHERE rowid = ?",
                        (mapped_status, mapped_status, created_at, rowid)
                    )
                    updated_count += 1
            else:
                job_url = f"https://referral-community.kadegree.in/openings/{op_id}" if op_id else f"https://referral-community.kadegree.in/get#{comp}"
                cur.execute(
                    """INSERT OR IGNORE INTO jobs (url, title, site, location, strategy, fit_score, apply_status, application_stage, applied_at, discovered_at)
                    VALUES (?, ?, ?, 'Bengaluru, India', 'kadegree_community', 9, ?, ?, ?, ?)""",
                    (job_url, role, comp, mapped_status, mapped_status, created_at, created_at)
                )
                updated_count += 1
        conn.commit()
        return {"status": "ok", "synced_requests": len(data), "updated": updated_count}
    finally:
        if close_conn:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = sync_kadegree_jobs()
    print("Sync Result:", json.dumps(res, indent=2))
