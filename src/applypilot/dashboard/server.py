"""ApplyPilot Phase 2 Interactive Review & Approval Dashboard.

High-energy, cyber-sleek UI with:
- Glassmorphism, energetic gradients, and micro-interactions.
- On-Demand (JIT) Resume Tailoring & Tectonic PDF Compilation in 4 seconds.
- Direct Live browser integration (opens in existing default browser with resume copied to clipboard).
- LinkedIn Referral & Connection Outreach generator with 1-click searches.
- Approved Shortlist Queue for focused daily applications.
- Celebratory confetti on application submit.
"""

import json
import logging
import mimetypes
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone

from applypilot.config import APP_DIR, DB_PATH, TAILORED_DIR, COVER_LETTER_DIR, load_profile, load_env
from applypilot.database import get_connection
from applypilot.export.csv_export import export_opportunities_csv

load_env()
from applypilot.networking.outreach import generate_outreach_messages
from applypilot.scoring.jit_tailor import tailor_single_job

log = logging.getLogger(__name__)

PORT = 8765


def launch_url_in_browser(url: str, incognito: bool = False) -> bool:
    """Launch URL in standard default browser without CDP attachments or process injection."""
    if not url or not (str(url).startswith("http://") or str(url).startswith("https://")):
        return False
    try:
        if hasattr(os, "startfile") and not incognito:
            os.startfile(url)
            return True
        else:
            webbrowser.open(url)
            return True
    except Exception as e:
        log.warning("Could not launch URL via system default browser: %s", e)
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False


STATIC_DIR = Path(__file__).parent / "static"

def _get_static_file(filename: str) -> bytes:
    p = STATIC_DIR / filename
    if p.exists():
        return p.read_bytes()
    return b""



class DashboardHandler(SimpleHTTPRequestHandler):
    """Custom request handler for ApplyPilot Phase 2 Dashboard & Phase 3 Assistant."""

    def log_message(self, format, *args):
        # Silence default terminal request spam
        return

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_GET(self):
        try:
            self._handle_do_GET()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            log.exception(f"Unhandled error in do_GET: {e}")
            try:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            except Exception:
                pass

    def _handle_do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        from applypilot.database import get_connection

        if path in ("/", "/index.html", "/dashboard"):
            content = _get_static_file("index.html")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return

        elif path == "/static/styles.css":
            content = _get_static_file("styles.css")
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return

        elif path == "/static/app.js":
            content = _get_static_file("app.js")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return

        elif path == "/static/lucide.min.js":
            content = _get_static_file("lucide.min.js")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return

        elif path == "/api/funding-leads":
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT id, company, source, headline, article_url, round_amount, product_focus, ats_provider, ats_slug, status, discovered_at FROM funding_leads ORDER BY id DESC LIMIT 50")
            rows = [dict(r) for r in c.fetchall()]
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(rows).encode("utf-8"))
            return

        elif path == "/api/skills/demand":
            from applypilot.dashboard.analytics import get_skills_demand
            demand = get_skills_demand()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(demand).encode("utf-8"))
            return

        elif path == "/api/linkedin/status":
            from applypilot.networking.linkedin import is_linkedin_authenticated
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"authenticated": is_linkedin_authenticated()}).encode("utf-8"))
            return

        elif path == "/api/naukri/status":
            from applypilot.automation.naukri_updater import get_windows_task_status, get_last_update_status
            data = {
                "task": get_windows_task_status(),
                "last_update": get_last_update_status(),
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        elif path == "/api/auto_apply_status":
            from applypilot.apply.assistant import AUTO_APPLY_STATE
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(AUTO_APPLY_STATE).encode("utf-8"))
            return

        elif path == "/api/stats":
            from applypilot.database import get_stats
            conn = get_connection()
            stats = get_stats(conn)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode("utf-8"))
            return

        elif path == "/api/followups/due":
            try:
                from applypilot.networking.followup_engine import ReferralFollowUpEngine
                engine = ReferralFollowUpEngine()
                actions = engine.collect_due_actions()
                data = [
                    {
                        "job_id": a.job_id,
                        "stage": a.stage,
                        "company": a.company,
                        "title": a.title,
                        "job_url": a.job_url,
                        "email_to_use": a.email_to_use,
                        "contact_name": a.contact_name,
                        "contact_handle": a.contact_handle,
                        "due_at": a.due_at,
                        "template_text": a.template_text,
                    }
                    for a in actions
                ]
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "actions": data}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        elif path == "/api/jobs":
            from applypilot.config import load_search_config
            cfg = load_search_config()
            reject_patterns = [rp.lower() for rp in cfg.get("location", {}).get("reject_patterns", [])]

            conn = get_connection()
            c = conn.cursor()
            query = """
                SELECT 
                    rowid,
                    COALESCE(site, 'Unknown') AS company,
                    COALESCE(title, 'N/A') AS title,
                    COALESCE(location, 'N/A') AS location,
                    COALESCE(recruiter_email, '') AS recruiter_email,
                    fit_score,
                    score_reasoning,
                    COALESCE(application_url, url) AS apply_url,
                    url,
                    tailored_resume_path,
                    cover_letter_path,
                    apply_status,
                    applied_at,
                    COALESCE(full_description, '') AS full_desc,
                    COALESCE(description, '') AS desc,
                    COALESCE(strategy, '') AS strategy,
                    COALESCE(salary, '') AS salary,
                    COALESCE(discovered_at, '') AS discovered_at,
                    COALESCE(referral_contacted_at, '') AS referral_contacted_at,
                    COALESCE(referral_contact_name, '') AS referral_contact_name,
                    COALESCE(referral_contact_platform, '') AS referral_contact_platform,
                    COALESCE(is_easy_apply, 0) AS is_easy_apply,
                    COALESCE(date_posted, '') AS date_posted,
                    num_applicants,
                    COALESCE(ignore_reason, '') AS ignore_reason
                FROM jobs
                ORDER BY fit_score DESC NULLS LAST, discovered_at DESC
            """
            rows = c.execute(query).fetchall()
            cols = [d[0] for d in c.description]
            all_raw = [dict(zip(cols, r)) for r in rows]

            import re
            seniority_cfg = cfg.get("seniority", {})
            reject_titles = [t.lower() for t in seniority_cfg.get("reject_titles", [
                "senior", "sr.", "sr ", "lead", "tech lead", "staff", "principal", "manager", "mgr", "director", "architect", "head"
            ])]
            exp_patterns = [
                re.compile(r'(\d+)\+?\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)(?:\s*of)?\s*(?:relevant|hands-on|industry|software|backend|work)?\s*experience', re.IGNORECASE),
                re.compile(r'(\d+)\+?\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)', re.IGNORECASE),
                re.compile(r'(\d+)\+?\s*(?:years?|yrs?)(?:\s*of)?\s*(?:relevant|hands-on|industry|software|backend|work)?\s*experience', re.IGNORECASE),
                re.compile(r'experience(?:\s*of)?\s*:?\s*(\d+)\+?\s*(?:to|-)?\s*(\d+)?\s*(?:years?|yrs?)', re.IGNORECASE),
                re.compile(r'(?:minimum|min|at least)\s*(\d+)\+?\s*(?:years?|yrs?)', re.IGNORECASE),
                re.compile(r'(\d+)\+?\s*yoe\b', re.IGNORECASE),
                re.compile(r'yoe\s*:?\s*(\d+)\+?', re.IGNORECASE),
            ]

            jobs = []
            for j in all_raw:
                loc = (j.get("location") or "").lower()
                tit = (j.get("title") or "").lower()

                # 1. Location rejection (e.g. US-only, Canada, UK)
                if any(rp in loc for rp in reject_patterns):
                    continue

                # 2. Senior / Lead / Staff / Manager title rejection (Deepak has ~1.3-2 yrs experience)
                if any(st in tit for st in reject_titles):
                    continue

                # 2b. Domain rejection: No Frontend, UI/UX, Android, iOS, Mobile, Flutter, QA, DevOps, Data Eng
                domain_rejects = [
                    r'\bfront[- ]?end\b', r'\bui\b', r'\bux\b', r'\bweb designer\b',
                    r'\bandroid\b', r'\bios\b', r'\bmobile\b', r'\bflutter\b', r'\breact native\b',
                    r'\bdata engineer\b', r'\bdata scientist\b', r'\bmachine learning\b', r'\bml engineer\b',
                    r'\bai engineer\b', r'\bai/ml\b', r'\baiml\b', r'\bqa\b', r'\bquality\b', r'\bsdet\b',
                    r'\btest\b', r'\btesting\b', r'\bdevops\b', r'\bsre\b', r'\binfrastructure\b', r'\bsupport\b',
                    r'\bsalesforce\b', r'\bsap\b', r'\bservicenow\b', r'\bcyber\b', r'\bsecurity\b',
                    r'\bintern\b', r'\binternship\b', r'\btrainee\b', r'\bembedded\b', r'\bfirmware\b',
                    r'\bhardware\b'
                ]
                if any(re.search(dr, tit) for dr in domain_rejects):
                    continue

                # 2c. Target Role / Stack requirement: must be Backend, Spring Boot, Java, Golang/Go, Full Stack, SDE
                target_roles = [
                    r'\bbackend\b', r'\bback[- ]end\b',
                    r'\bspring\b', r'\bspring\s*boot\b',
                    r'\bjava\b',
                    r'\bgolang\b', r'\bgo\s*(?:developer|engineer|backend)\b', r'\bgo\b',
                    r'\bfull[- ]?stack\b',
                    r'\bsde\b', r'\bsde[- ]?[12iI]+\b',
                    r'\bsoftware engineer\b', r'\bsoftware development engineer\b', r'\bsoftware developer\b',
                    r'\bapi\b', r'\bmicroservices\b', r'\bdistributed systems\b', r'\bcloud backend\b',
                    r'\bserver side\b'
                ]
                if not any(re.search(tr, tit) for tr in target_roles):
                    continue

                # 3. Explicit experience rejection: Deepak is 0-3 YOE.
                # Strictly reject:
                # - Minimum required experience >= 4 years (e.g. 4+ yrs, 5+ yrs, 6-10 yrs)
                # - Upper bound of range >= 5 years (e.g. 3-5, 4-7, 4-8, 6-10 years)
                text = f"{tit} {j.get('full_desc', '')} {j.get('desc', '')}"
                is_over_exp = False
                for pat in exp_patterns:
                    for m in pat.finditer(text):
                        groups = [int(g) for g in m.groups() if g and g.isdigit()]
                        if groups:
                            min_exp = groups[0]
                            max_exp = groups[1] if len(groups) > 1 else min_exp
                            if min_exp >= 4 or max_exp >= 5:
                                is_over_exp = True
                                break
                    if is_over_exp:
                        break
                if is_over_exp:
                    continue

                # Derive Source & Job Related Info
                c_raw = (j.get("company") or "").strip()
                if c_raw.lower() in ("linkedin", "indeed", "jobspy", "unknown", "company direct", ""):
                    t_full = (j.get("desc") or "") + "\n" + (j.get("full_desc") or "")
                    inferred_comp = None
                    m_url = re.search(r'-at-([a-zA-Z0-9\-]+)-\d+', j.get("url") or "")
                    if m_url:
                        cand = m_url.group(1).replace('-', ' ').strip().title()
                        if cand.lower() not in ('jobs', 'careers', 'hiring', 'linkedin', 'indeed'):
                            inferred_comp = cand
                    if not inferred_comp and t_full:
                        m_txt = re.search(r'^\s*([A-Z][a-zA-Z0-9\.\s&]{2,25}?)\s+is\s+(?:the|a|an|one|rapidly|seeking|building|leading)\b', t_full.strip())
                        if m_txt:
                            cand = m_txt.group(1).strip()
                            if cand.lower() not in ('this', 'the role', 'the company', 'the position', 'our client', 'summary', 'about the job'):
                                inferred_comp = cand
                    if inferred_comp:
                        j["company"] = inferred_comp
                        c_raw = inferred_comp

                strat = (j.get("strategy") or "").lower()
                u_str = (j.get("url") or j.get("apply_url") or "").lower()
                c_str = c_raw.lower()

                if "kadegree" in strat or "kadegree" in u_str or "kannada" in c_str:
                    j["source"] = "KaDegree Community"
                    j["source_category"] = "kadegree"
                    j["source_icon"] = "fa-solid fa-users-rays"
                    j["is_kadegree"] = True
                    ref_m = re.search(r"Referrer:\s*([^\n|]+)", j.get("full_desc") or "")
                    slots_m = re.search(r"Referral Slots Left:\s*([^\n|]+)", j.get("full_desc") or "")
                    j["referrer_info"] = ref_m.group(1).strip() if ref_m else "Kannada Community Referrer"
                    j["slots_info"] = slots_m.group(1).strip() if slots_m else ""
                    j["kadegree_url"] = j.get("url") if "kadegree.in" in j.get("url", "") else "https://referral-community.kadegree.in/get"
                elif "whatsapp" in strat or "whatsapp" in c_str or "whatsapp" in u_str:
                    j["source"] = "WhatsApp Community"
                    j["source_category"] = "whatsapp"
                    j["source_icon"] = "fa-brands fa-whatsapp"
                    j["is_kadegree"] = False
                elif "linkedin" in strat or "linkedin" in c_str or "linkedin" in u_str:
                    j["source"] = "LinkedIn"
                    j["source_category"] = "linkedin"
                    j["source_icon"] = "fa-brands fa-linkedin"
                    j["is_kadegree"] = False
                elif "greenhouse" in strat or "greenhouse.io" in u_str:
                    j["source"] = "Greenhouse ATS"
                    j["source_category"] = "ats"
                    j["source_icon"] = "fa-solid fa-seedling"
                    j["is_kadegree"] = False
                elif "workday" in strat or "myworkdayjobs" in u_str:
                    j["source"] = "Workday ATS"
                    j["source_category"] = "ats"
                    j["source_icon"] = "fa-solid fa-building"
                    j["is_kadegree"] = False
                elif "smartrecruiters" in strat or "smartrecruiters.com" in u_str:
                    j["source"] = "SmartRecruiters"
                    j["source_category"] = "ats"
                    j["source_icon"] = "fa-solid fa-briefcase"
                    j["is_kadegree"] = False
                elif "indeed" in strat or "indeed.com" in u_str:
                    j["source"] = "Indeed (Incognito)"
                    j["source_category"] = "indeed"
                    j["source_icon"] = "fa-solid fa-info"
                    j["is_kadegree"] = False
                elif "jobspy" in strat:
                    if "indeed" in c_str or "indeed" in u_str:
                        j["source"] = "Indeed"
                        j["source_icon"] = "fa-solid fa-info"
                    else:
                        j["source"] = "JobSpy Aggregator"
                        j["source_icon"] = "fa-solid fa-radar"
                    j["source_category"] = "jobspy"
                    j["is_kadegree"] = False
                else:
                    j["source"] = j.get("company") or "Company Direct"
                    j["source_category"] = "ats"
                    j["source_icon"] = "fa-solid fa-building-circle-check"
                    j["is_kadegree"] = False

                # Clean internal fields
                j.pop('full_desc', None)
                j.pop('desc', None)
                jobs.append(j)

            # Attach LinkedIn referral outreach data to each job
            for j in jobs:
                # Sanitize apply_url against 'None' or empty
                app_u = j.get("apply_url")
                if not app_u or str(app_u).strip().lower() in ("none", "null", "", "http://none/", "http://none", "none/"):
                    j["apply_url"] = j.get("url") or "#"
                u_str = (j.get("apply_url") or "").lower()
                c_str = (j.get("company") or "").lower()
                if "razorpay" in u_str or "razorpay" in c_str:
                    if "greenhouse.io" not in u_str:
                        j["apply_url"] = "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited"
                elif "phonepe" in u_str or "phonepe" in c_str:
                    if "sde1" in u_str or u_str.rstrip("/").endswith("/careers"):
                        j["apply_url"] = "https://jobs.smartrecruiters.com/PhonePeLimited/1000000000003895"

                j["outreach"] = generate_outreach_messages(
                    company=j.get("company", ""),
                    role_title=j.get("title", ""),
                    apply_url=j.get("apply_url", ""),
                    recruiter_email=j.get("recruiter_email", "")
                )

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(jobs).encode("utf-8"))
            return

        elif path == "/api/responses":
            from applypilot.enrichment.email_tracker import get_cached_responses
            responses = get_cached_responses()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(responses).encode("utf-8"))
            return

        # /api/cold_crm/summary (Cold email sales funnel summary, due follow-ups, leads)
        elif path == "/api/cold_crm/summary":
            from applypilot.networking.cold_email_tracker import get_cold_email_funnel_summary
            summary = get_cold_email_funnel_summary()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(summary).encode("utf-8"))
            return

        # /api/referral_crm/summary (Referral connection requests, company breakdown, acceptance metrics)
        elif path == "/api/referral_crm/summary":
            from applypilot.networking.referral_tracker import get_referral_network_summary
            summary = get_referral_network_summary()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(summary).encode("utf-8"))
            return

        # /api/funnel (Everyday time spent, full vs half applied, 30-day conversion stats)
        elif path == "/api/funnel":
            from applypilot.analytics.activity import get_funnel_and_activity_metrics
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(get_funnel_and_activity_metrics()).encode("utf-8"))
            return

        # /api/gemini/diagnostics (Get cached or fresh Gemini strategic analysis)
        elif path == "/api/gemini/diagnostics":
            from applypilot.analytics.gemini_advisor import run_gemini_strategic_analysis
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(run_gemini_strategic_analysis(force_refresh=False)).encode("utf-8"))
            return

        # /api/calls (Retrieve logged recruiter phone screens and calls)
        elif path == "/api/calls":
            from applypilot.enrichment.call_logger import get_logged_calls
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(get_logged_calls()).encode("utf-8"))
            return

        # /api/cheatsheet (Generate technical & HR interview cheat sheet)
        elif path == "/api/cheatsheet":
            query_params = urllib.parse.parse_qs(parsed.query)
            comp_param = query_params.get("company", ["PhonePe"])[0]
            role_param = query_params.get("role", ["SDE Backend Engineer"])[0]
            from applypilot.enrichment.interview_cheatsheet import generate_company_cheatsheet
            sheet = generate_company_cheatsheet(comp_param, role_param)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(sheet).encode("utf-8"))
            return

        # /api/gsheet/status
        elif path == "/api/gsheet/status":
            from applypilot.export.gsheets_sync import get_sheet_config
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(get_sheet_config()).encode("utf-8"))
            return

        # /api/analytics (Full application lifecycle, sources, and audit metrics)
        elif path == "/api/analytics":
            from applypilot.dashboard.analytics import get_application_analytics
            data = get_application_analytics()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        # /api/analytics/export_csv (Download full application audit trail as CSV)
        elif path == "/api/analytics/export_csv":
            from applypilot.dashboard.analytics import get_application_analytics
            data = get_application_analytics()
            csv_bytes = data.get("csv_data", "").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="ApplyPilot_Application_Audit_Ledger.csv"')
            self.end_headers()
            self.wfile.write(csv_bytes)
            return

        elif path.startswith("/api/linkedin/scan"):
            query_params = urllib.parse.parse_qs(parsed.query)
            comp_param = query_params.get("company", [""])[0].strip()

            from applypilot.networking.linkedin import search_linkedin_connections, is_linkedin_authenticated
            from applypilot.database import get_connection

            # Check database for existing connections at this company first
            existing_conns = []
            try:
                conn_db = get_connection()
                c_db = conn_db.cursor()
                if comp_param:
                    c_db.execute(
                        "SELECT id, company, person_name, profile_url, headline, is_alumni, degree, status, requested_at, accepted_at "
                        "FROM referral_connection_requests "
                        "WHERE LOWER(company) LIKE LOWER(?)",
                        (f"%{comp_param}%",)
                    )
                    existing_conns = [dict(r) for r in c_db.fetchall()]
            except Exception as dbe:
                log.warning("Could not fetch existing company connections from db: %s", dbe)

            # Check online live connections
            live_results = []
            auth_warning = ""
            if comp_param:
                try:
                    live_results = search_linkedin_connections(company=comp_param, role="backend", school="RV College of Engineering", max_results=8)
                    for r in live_results:
                        if r.get("error"):
                            auth_warning = r.get("error")
                            break
                    live_results = [r for r in live_results if not r.get("error")]
                except Exception as se:
                    log.debug("Live connection search info: %s", se)

            # Combine existing DB records and live scanned results without duplicates
            combined = []
            seen_profiles = set()

            for ec in existing_conns:
                p_url = ec.get("profile_url") or ""
                p_key = p_url.lower().rstrip("/") if p_url else ec.get("person_name", "").lower()
                seen_profiles.add(p_key)
                combined.append({
                    "name": ec.get("person_name") or "Connection",
                    "company": ec.get("company") or comp_param,
                    "profile_url": p_url,
                    "headline": ec.get("headline") or "Engineer",
                    "degree": ec.get("degree") or "1st",
                    "is_alumni": bool(ec.get("is_alumni")),
                    "status": ec.get("status") or "connected",
                    "is_existing": True
                })

            for lr in live_results:
                p_url = lr.get("profile_url") or ""
                p_key = p_url.lower().rstrip("/") if p_url else lr.get("name", "").lower()
                if p_key not in seen_profiles:
                    seen_profiles.add(p_key)
                    deg = lr.get("degree") or "2nd"
                    is_existing = (deg == "1st")
                    combined.append({
                        "name": lr.get("name") or "Contact",
                        "company": lr.get("company") or comp_param,
                        "profile_url": p_url,
                        "headline": lr.get("headline") or lr.get("current_role") or "Engineer",
                        "degree": deg,
                        "is_alumni": bool(lr.get("is_alumni")),
                        "status": "connected" if is_existing else "not_connected",
                        "is_existing": is_existing
                    })

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "company": comp_param,
                "existing_count": len([c for c in combined if c.get("is_existing")]),
                "new_count": len([c for c in combined if not c.get("is_existing")]),
                "connections": combined,
                "auth_warning": auth_warning
            }).encode("utf-8"))
            return

        elif path.startswith("/api/jobs/") and (path.endswith("/resume") or path.endswith("/cover_letter")):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[2].isdigit():
                rowid = int(parts[2])
                doc_type = parts[3]
                conn = get_connection()
                c = conn.cursor()
                row = c.execute("SELECT site, title, tailored_resume_path, cover_letter_path FROM jobs WHERE rowid = ?", (rowid,)).fetchone()
                if not row:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Job not found")
                    return

                site, title, tailored_path, cover_path = row
                target_file = None

                if doc_type == "resume":
                    if tailored_path and Path(tailored_path).is_file():
                        target_file = Path(tailored_path)
                    elif tailored_path and (APP_DIR / tailored_path).is_file():
                        target_file = APP_DIR / tailored_path
                    elif (APP_DIR / "resume.pdf").is_file():
                        target_file = APP_DIR / "resume.pdf"
                elif doc_type == "cover_letter":
                    if cover_path and Path(cover_path).is_file():
                        target_file = Path(cover_path)
                    elif cover_path and (APP_DIR / cover_path).is_file():
                        target_file = APP_DIR / cover_path

                if target_file and target_file.is_file():
                    pdf_bytes = target_file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Length", str(len(pdf_bytes)))
                    self.send_header("Content-Disposition", f'inline; filename="{target_file.name}"')
                    self.end_headers()
                    self.wfile.write(pdf_bytes)
                    return
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"Document not found")
                    return

        elif path.startswith("/files/"):
            # Stream PDF file
            subpath = urllib.parse.unquote(path[len("/files/"):])
            if subpath.startswith("resumes/"):
                fname = subpath[len("resumes/"):]
                target = TAILORED_DIR / fname
            elif subpath.startswith("covers/"):
                fname = subpath[len("covers/"):]
                target = COVER_LETTER_DIR / fname
            else:
                target = APP_DIR / subpath

            if target.exists() and target.is_file():
                pdf_bytes = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(pdf_bytes)))
                self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
                self.end_headers()
                self.wfile.write(pdf_bytes)
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        super().do_GET()

    def do_POST(self):
        try:
            self._handle_do_POST()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            log.exception(f"Unhandled error in do_POST: {e}")
            try:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            except Exception:
                pass

    def _handle_do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/funding-leads/") and path.endswith("/status"):
            parts = path.strip("/").split("/")
            lead_id = parts[2]
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length)) if length > 0 else {}
            new_status = body.get("status", "SKIPPED")
            conn = get_connection()
            conn.execute("UPDATE funding_leads SET status = ? WHERE id = ?", (new_status, lead_id))
            conn.commit()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "id": lead_id, "new_status": new_status}).encode("utf-8"))
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        from applypilot.database import get_connection

        # /api/jobs/process_link (Instant Job Link Intake -> JD extraction + tailored resume + referral messages)
        if path.startswith("/api/followups/") and path.endswith("/ack"):
            parts = path.strip("/").split("/")
            # ["api", "followups", "<job_id>", "ack"]
            if len(parts) >= 4 and parts[1] == "followups" and parts[-1] == "ack":
                job_id = urllib.parse.unquote("/".join(parts[2:-1]))
                try:
                    from applypilot.networking.followup_engine import ReferralFollowUpEngine
                    engine = ReferralFollowUpEngine()
                    engine.acknowledge_action(job_id)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "job_id": job_id, "message": "Action acknowledged"}).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
                return

        if path == "/api/jobs/process_link":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body_data)
                url = payload.get("url", "").strip()
                manual_jd = payload.get("jd", "").strip()
                from applypilot.apply.quick_tailor import process_job_link
                result = process_job_link(url, manual_jd=manual_jd)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # /api/linkedin/process_post (Dedicated LinkedIn Post Intake -> Recruiter Mail / Form Link + Tailored Resume)
        if path == "/api/linkedin/process_post":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body_data)
                url = payload.get("url", "").strip()
                text = payload.get("text", "").strip()
                from applypilot.networking.linkedin_post_intake import process_linkedin_post
                result = process_linkedin_post(url, manual_text=text)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # /api/activity/heartbeat (Track active search time)
        if path == "/api/activity/heartbeat":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body_data)
                sec = payload.get("duration_seconds", 30)
                act = payload.get("action", "dashboard_browsing")
                from applypilot.analytics.activity import record_activity_heartbeat
                record_activity_heartbeat(action=act, duration_seconds=sec)
            except Exception:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            return

        # /api/ats/sync (Sync direct ATS: Greenhouse, Lever, SmartRecruiters, Workday)
        elif path == "/api/ats/sync":
            def _bg_ats_sync():
                try:
                    from applypilot.discovery.ats import run_ats_discovery
                    from applypilot.discovery.workday import run_workday_discovery
                    from applypilot.export.csv_export import export_opportunities_csv
                    print("[ATS Sync] Scraping Greenhouse, Lever, SmartRecruiters & Workday...")
                    ats_res = run_ats_discovery(workers=4)
                    wd_res = run_workday_discovery(workers=4)
                    print(f"[ATS Sync] Complete: ATS={ats_res}, Workday={wd_res}")
                    try:
                        export_opportunities_csv()
                    except Exception:
                        pass
                except Exception as ex:
                    print(f"[ATS Sync Error] {ex}")

            threading.Thread(target=_bg_ats_sync, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "message": "Direct ATS & Workday background sync initiated! Fresh corporate postings will load into your pipeline."
            }).encode("utf-8"))
            return

        # /api/seed_startups/sync (Sync YC & Seed Funded Startups)
        elif path == "/api/seed_startups/sync":
            try:
                from applypilot.discovery.seed_startups import ingest_seed_funded_startups
                res = ingest_seed_funded_startups()
            except Exception as e:
                res = {"status": "error", "message": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/kadegree/sync (Sync latest openings from KaDegree Kannada Referral Community)
        elif path == "/api/kadegree/sync":
            from applypilot.discovery.kadegree import sync_kadegree_jobs
            try:
                res = sync_kadegree_jobs()
            except Exception as e:
                res = {"status": "error", "message": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/linkedin/easy_apply_scan (Scan LinkedIn specifically for Easy Apply jobs)
        elif path == "/api/linkedin/easy_apply_scan":
            def _bg_easy_apply_scan():
                try:
                    from applypilot.networking.linkedin import scan_linkedin_easy_apply_jobs
                    scan_linkedin_easy_apply_jobs()
                except Exception as ex:
                    print(f"LinkedIn easy apply scan error: {ex}")
            threading.Thread(target=_bg_easy_apply_scan, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "Scanning LinkedIn specifically for Easy Apply openings..."}).encode("utf-8"))
            return

        # /api/linkedin/incognito_scan (Scrape multi-source fresh jobs in incognito mode: LinkedIn, Indeed, and Direct ATS)
        elif path == "/api/linkedin/incognito_scan":
            def _bg_incognito_scan():
                try:
                    from applypilot.discovery.multi_incognito import run_fresh_incognito_multisource_scan
                    run_fresh_incognito_multisource_scan(linkedin_hours=4, indeed_days=1, run_ats=True)
                except Exception as ex:
                    print(f"Multi-source incognito scan error: {ex}")
            threading.Thread(target=_bg_incognito_scan, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "Multi-Source Incognito Scan running across LinkedIn, Indeed & Direct ATS (Greenhouse, Lever, SmartRecruiters)..."}).encode("utf-8"))
            return

        # /api/linkedin/posts_poll (Scan LinkedIn for fresh hiring posts in real-time)
        elif path == "/api/linkedin/posts_poll":
            def _bg_linkedin_posts():
                try:
                    from applypilot.networking.linkedin import search_linkedin_posts
                    search_linkedin_posts(max_results=12, save_to_db=True)
                except Exception as ex:
                    print(f"LinkedIn posts poll error: {ex}")
            threading.Thread(target=_bg_linkedin_posts, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "LinkedIn hiring post scan active in background."}).encode("utf-8"))
            return

        # /api/channels/poll (Trigger community & inbound polling cycle)
        elif path == "/api/channels/poll":
            try:
                from applypilot.automation.poller import execute_polling_cycle
                def _bg_poll():
                    execute_polling_cycle(headless=True)
                threading.Thread(target=_bg_poll, daemon=True).start()
                res = {"status": "ok", "message": "Community polling cycle started in background (WhatsApp + Telegram + Gmail)."}
            except Exception as e:
                res = {"status": "error", "message": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/calls/log (Log recruiter call or offline interview)
        elif path == "/api/calls/log":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                payload = json.loads(body_data)
                from applypilot.enrichment.call_logger import log_recruiter_call
                res = log_recruiter_call(payload)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/gemini/diagnostics (Force re-run Gemini analysis)
        elif path == "/api/gemini/diagnostics":
            from applypilot.analytics.gemini_advisor import run_gemini_strategic_analysis
            res = run_gemini_strategic_analysis(force_refresh=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/calendar/block_oas (Block pending OA deadlines on calendar)
        elif path == "/api/calendar/block_oas":
            from applypilot.calendar.scheduler import block_all_pending_oas
            res = block_all_pending_oas()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/gsheet/sync (Sync pipeline to Google Sheets / CSV)
        elif path == "/api/gsheet/sync":
            from applypilot.export.gsheets_sync import sync_to_google_sheets
            res = sync_to_google_sheets()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/alerts/test (Send test alert to phone via Telegram/WhatsApp and Desktop Toast)
        elif path == "/api/alerts/test":
            from applypilot.notifications.alerts import dispatch_alert
            res = dispatch_alert(
                title="ApplyPilot Mobile Alert Test",
                body="Real-time mobile notification pipeline operational! You will be alerted the second an OA arrives or interview is scheduled.",
                url="http://localhost:8765"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "details": res}).encode("utf-8"))
            return

        # 1. /api/jobs/{rowid}/tailor (On-Demand JIT Tailoring)
        elif path.startswith("/api/jobs/") and path.endswith("/tailor"):
            parts = path.split("/")
            rowid = int(parts[3])
            res = tailor_single_job(rowid)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 2. /api/jobs/{rowid}/open_browser (Direct Open in default browser + Copy PDF path)
        elif path.startswith("/api/jobs/") and (path.endswith("/open_browser") or path.endswith("/open_portal")):
            parts = path.split("/")
            rowid = int(parts[3])
            conn = get_connection()
            c = conn.cursor()
            row = c.execute("SELECT application_url, url, tailored_resume_path, site FROM jobs WHERE rowid = ?", (rowid,)).fetchone()
            if not row:
                self.send_response(404)
                self.end_headers()
                return

            app_url = row[0]
            job_url = row[1]
            apply_url = None
            for u in (app_url, job_url):
                if u and str(u).strip().lower() not in ("none", "null", "", "http://none/", "http://none", "none/"):
                    u_str = str(u).strip()
                    if u_str.startswith("http://") or u_str.startswith("https://"):
                        apply_url = u_str
                        break

            if apply_url:
                u_lower = apply_url.lower()
                site_lower = (row[3] or "").lower()
                if ("razorpay" in u_lower or "razorpay" in site_lower) and "greenhouse.io" not in u_lower:
                    apply_url = "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited"
                elif ("phonepe" in u_lower or "phonepe" in site_lower) and ("sde1" in u_lower or u_lower.rstrip("/").endswith("/careers")):
                    apply_url = "https://jobs.smartrecruiters.com/PhonePeLimited/1000000000003895"

            if not apply_url:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": "No direct application URL found for this position."
                }).encode("utf-8"))
                return

            tailored_path = row[2]

            # Copy PDF path to clipboard if available
            msg_clip = ""
            if tailored_path:
                abs_pdf = (APP_DIR / tailored_path).resolve()
                if abs_pdf.exists():
                    try:
                        subprocess.run(["powershell", "-Command", f"Set-Clipboard -Value '{str(abs_pdf)}'"], capture_output=True)
                        msg_clip = " Tailored Resume PDF path copied to clipboard — press Ctrl+V to attach!"
                    except Exception:
                        pass

            # Open directly in default browser
            launch_url_in_browser(apply_url)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "apply_url": apply_url,
                "tailored_path": tailored_path,
                "message": f"Opened portal in your browser!{msg_clip}"
            }).encode("utf-8"))
            return

        # 3. /api/jobs/{rowid}/approve
        elif path.startswith("/api/jobs/") and path.endswith("/approve"):
            parts = path.split("/")
            rowid = int(parts[3])
            conn = get_connection()
            conn.execute("UPDATE jobs SET apply_status = 'approved' WHERE rowid = ?", (rowid,))
            conn.commit()
            export_opportunities_csv()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid}).encode("utf-8"))
            return

        # 3b. /api/jobs/{rowid}/ignore (with structured reasoning feedback logged for analytics)
        elif path.startswith("/api/jobs/") and path.endswith("/ignore"):
            parts = path.split("/")
            rowid = int(parts[3])

            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            reason = "unspecified"
            try:
                payload = json.loads(body_data)
                reason = payload.get("reason", "unspecified")
            except Exception:
                pass

            conn = get_connection()
            # Fetch job details for rich audit log
            job_row = conn.execute("SELECT site, title, location, url, salary, strategy FROM jobs WHERE rowid = ?", (rowid,)).fetchone()
            company = job_row["site"] if job_row and "site" in job_row.keys() else ""
            title = job_row["title"] if job_row and "title" in job_row.keys() else ""
            location = job_row["location"] if job_row and "location" in job_row.keys() else ""
            url = job_row["url"] if job_row and "url" in job_row.keys() else ""

            conn.execute("UPDATE jobs SET apply_status = 'ignored', ignore_reason = ? WHERE rowid = ?", (reason, rowid))
            conn.commit()

            # Append structured feedback record to data/ignored_jobs_feedback.jsonl
            try:
                feedback_file = APP_DIR / "ignored_jobs_feedback.jsonl"
                feedback_entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "rowid": rowid,
                    "company": company,
                    "title": title,
                    "location": location,
                    "url": url,
                    "reason": reason
                }
                with open(feedback_file, "a", encoding="utf-8") as ff:
                    ff.write(json.dumps(feedback_entry) + "\n")
            except Exception as fe:
                log.warning(f"Could not write to ignored_jobs_feedback.jsonl: {fe}")

            export_opportunities_csv()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid, "reason": reason}).encode("utf-8"))
            return

        # 3c. /api/jobs/{rowid}/unignore
        elif path.startswith("/api/jobs/") and path.endswith("/unignore"):
            parts = path.split("/")
            rowid = int(parts[3])
            conn = get_connection()
            conn.execute("UPDATE jobs SET apply_status = NULL WHERE rowid = ?", (rowid,))
            conn.commit()
            export_opportunities_csv()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid}).encode("utf-8"))
            return

        # 4. /api/jobs/{rowid}/applied
        elif path.startswith("/api/jobs/") and path.endswith("/applied"):
            parts = path.split("/")
            rowid = int(parts[3])
            from applypilot.apply.assistant import mark_job_applied
            res = mark_job_applied(rowid)
            if isinstance(res, dict) and res.get("status") == "applied":
                res["status"] = "ok"

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 4b. /api/jobs/{rowid}/asked_referral
        elif path.startswith("/api/jobs/") and path.endswith("/asked_referral"):
            parts = path.split("/")
            rowid = int(parts[3])
            length = int(self.headers.get("Content-Length", 0))
            payload = {}
            if length > 0:
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception:
                    pass
            from applypilot.apply.assistant import mark_job_referral_asked
            contact_name = payload.get("contact_name", "")
            platform = payload.get("platform", "LinkedIn")
            res = mark_job_referral_asked(rowid, contact_name=contact_name, platform=platform)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 5a. /api/jobs/{rowid}/auto_apply (100% Autonomous Auto-Apply - Kanistus Workflow)
        elif path.startswith("/api/jobs/") and path.endswith("/auto_apply"):
            parts = path.split("/")
            rowid = int(parts[3])
            from applypilot.apply.assistant import launch_application_assistant
            from applypilot.analytics.activity import mark_job_half_applied
            mark_job_half_applied(rowid, action="autonomous_apply")

            t = threading.Thread(target=launch_application_assistant, kwargs={"identifier": rowid, "headed": True, "auto_submit": True}, daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "launched", "mode": "autonomous", "rowid": rowid}).encode("utf-8"))
            return

        # 5b. /api/auto_apply_batch (Batch Autonomous Execution)
        elif path == "/api/auto_apply_batch":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            req_data = json.loads(body_data) if body_data else {}
            limit = int(req_data.get("limit", 5))
            min_score = int(req_data.get("min_score", 7))
            auto_submit = bool(req_data.get("auto_submit", True))

            from applypilot.apply.assistant import auto_apply_batch
            t = threading.Thread(target=auto_apply_batch, kwargs={"limit": limit, "min_score": min_score, "headed": True, "auto_submit": auto_submit}, daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "batch_launched", "limit": limit, "min_score": min_score}).encode("utf-8"))
            return

        # 5c. /api/jobs/{rowid}/launch (Playwright Assistant - Review Mode)
        elif path.startswith("/api/jobs/") and path.endswith("/launch"):
            parts = path.split("/")
            rowid = int(parts[3])
            from applypilot.apply.assistant import launch_application_assistant
            from applypilot.analytics.activity import mark_job_half_applied
            mark_job_half_applied(rowid, action="autofill_launch")

            t = threading.Thread(target=launch_application_assistant, kwargs={"identifier": rowid, "headed": True, "auto_submit": False}, daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "rowid": rowid}).encode("utf-8"))
            return

        # 5c. /api/remote_boards/sync (Sync Remotive & Working Nomads APIs)
        elif path == "/api/remote_boards/sync":
            from applypilot.discovery.remote_boards import run_remote_boards_discovery
            try:
                res = run_remote_boards_discovery()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # 6. /api/open_url (Directly open URL in default browser)
        elif path == "/api/open_url":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                target_url = data.get("url", "")
                incognito = bool(data.get("incognito", False))
                if target_url:
                    launch_url_in_browser(target_url, incognito=incognito)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "url": target_url, "incognito": incognito}).encode("utf-8"))
                    return
            except Exception as e:
                log.error("Failed to open URL in browser: %s", e)

            self.send_response(400)
            self.end_headers()
            return

        # 7. /api/gmail/sync (Scan Gmail inbox for new employer updates)
        elif path == "/api/gmail/sync":
            from applypilot.enrichment.email_tracker import sync_gmail_job_responses
            try:
                synced = sync_gmail_job_responses(max_results=15)
                res = {"status": "ok", "synced_count": len(synced)}
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 7c. /api/responses/{message_id}/request_extension (Draft polite 24h extension in Gmail)
        elif path.startswith("/api/responses/") and path.endswith("/request_extension"):
            parts = path.split("/")
            msg_id = parts[3]
            from applypilot.database import get_connection
            conn = get_connection()
            row = conn.execute("SELECT sender, company, role_title, subject FROM application_responses WHERE message_id = ?", (msg_id,)).fetchone()
            
            to_email = "moheek@chausar.co.in"
            comp_name = "Chausar"
            role_name = "Founding Engineer"
            if row:
                sender_hdr = row[0] or ""
                m_email = re.search(r"[\w\.-]+@[\w\.-]+", sender_hdr)
                if m_email:
                    to_email = m_email.group(0)
                comp_name = row[1] or comp_name
                role_name = row[2] or role_name

            subject = f"Re: Next step for {role_name} - Extension Request - Deepak S H"
            body = (
                f"Hi {comp_name} Hiring Team,\n\n"
                f"Thank you for the opportunity and the assessment invitation for the {role_name} role.\n\n"
                f"Due to critical production deployment duties at Meesho yesterday, I was unable to complete "
                f"the engineering assessment before the Monday 11:59 PM IST window closed.\n\n"
                f"Would it be possible to grant a brief 24-hour extension so I can complete and submit the challenge today? "
                f"I am deeply excited about {comp_name}'s mission and engineering bar, and I am ready to start the assessment right away.\n\n"
                f"I have also attached my resume for your reference. Thank you so much for your consideration and understanding!\n\n"
                f"Best regards,\n\n"
                f"**Deepak S H**\n"
                f"SDE-I Backend Engineer, Meesho\n"
                f"RVCE CSE '25 | +91 8431433659\n"
            )

            from applypilot.networking.gmail_drafter import create_gmail_draft
            res = create_gmail_draft(
                to_email=to_email,
                subject=subject,
                body_markdown=body
            )

            # Generate guaranteed 1-click web compose fallback URL for default browser
            web_compose = (
                f"https://mail.google.com/mail/?view=cm&fs=1"
                f"&to={urllib.parse.quote(to_email)}"
                f"&su={urllib.parse.quote(subject)}"
                f"&body={urllib.parse.quote(body)}"
            )
            res["web_compose_url"] = web_compose
            if res.get("status") != "ok":
              res["message"] = "Opening pre-filled Gmail compose tab in your browser..."

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 7b. /api/responses/{message_id}/toggle_completed (Mark OA as completed / pending)
        elif path.startswith("/api/responses/") and path.endswith("/toggle_completed"):
            parts = path.split("/")
            msg_id = parts[3]
            from applypilot.enrichment.email_tracker import toggle_response_completed
            success = toggle_response_completed(msg_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message_id": msg_id, "success": success}).encode("utf-8"))
            return

        # /api/jobs/{rowid}/draft_email (Draft cold email in Gmail with attached resume)
        elif path.startswith("/api/jobs/") and path.endswith("/draft_email"):
            parts = path.split("/")
            rowid = int(parts[3])
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            custom_email = ""
            try:
                payload = json.loads(body_data)
                custom_email = payload.get("custom_email", "").strip()
            except Exception:
                pass

            from applypilot.networking.gmail_drafter import draft_for_job
            pitch_style = payload.get("pitch_style", "quick_pitch") if isinstance(body_data, str) and "pitch_style" in body_data else "quick_pitch"
            res = draft_for_job(rowid, custom_recipient=custom_email or None, pitch_style=pitch_style)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/jobs/{rowid}/send_email (Send cold email directly via Gmail with attached resume)
        elif path.startswith("/api/jobs/") and path.endswith("/send_email"):
            parts = path.split("/")
            rowid = int(parts[3])
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            custom_email = ""
            try:
                payload = json.loads(body_data)
                custom_email = payload.get("custom_email", "").strip()
            except Exception:
                pass

            from applypilot.networking.gmail_drafter import send_for_job
            res = send_for_job(rowid, custom_recipient=custom_email or None)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/email/custom_draft (Draft arbitrary cold email in Gmail)
        elif path == "/api/email/custom_draft":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                to_email = data.get("to_email", "").strip()
                company = data.get("company", "").strip()
                role_str = data.get("role", "").strip()
                job_url = data.get("job_url", "").strip()

                action_mode = data.get("action", "draft").strip().lower()
                from applypilot.networking.gmail_drafter import generate_recruiter_email, create_gmail_draft, send_gmail_email
                from applypilot.config import load_profile
                email_content = generate_recruiter_email(
                    company=company,
                    role_title=role_str,
                    job_url=job_url,
                    candidate_profile=load_profile()
                )
                if action_mode == "send":
                    res = send_gmail_email(
                        to_email=to_email,
                        subject=email_content["subject"],
                        body_markdown=email_content["body_markdown"]
                    )
                else:
                    res = create_gmail_draft(
                        to_email=to_email,
                        subject=email_content["subject"],
                        body_markdown=email_content["body_markdown"]
                    )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/copilot/answer (Gemini Application & Screening Copilot)
        elif path == "/api/copilot/answer":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                question = data.get("question", "").strip()
                company = data.get("company", "").strip()
                role_title = data.get("role_title", "").strip()
                job_desc = data.get("job_description", "").strip()

                from applypilot.apply.screening_copilot import answer_screening_question
                res = answer_screening_question(
                    question=question,
                    company=company,
                    role_title=role_title,
                    job_description=job_desc
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/cold_crm/record (Record new cold email outreach)
        elif path == "/api/cold_crm/record":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                from applypilot.networking.cold_email_tracker import record_cold_outreach
                res = record_cold_outreach(
                    recipient_email=data.get("recipient_email", ""),
                    company=data.get("company", ""),
                    role_title=data.get("role_title", "Backend Engineer"),
                    recipient_name=data.get("recipient_name", ""),
                    recipient_role=data.get("recipient_role", "recruiter"),
                    subject=data.get("subject", ""),
                    body=data.get("body", ""),
                    template_id=data.get("template_id", "quick_pitch_v1"),
                    pitch_style=data.get("pitch_style", "quick_pitch"),
                    open_count=int(data.get("open_count", 0)),
                    job_rowid=data.get("job_rowid")
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/record (Record new connection request sent for referral)
        elif path == "/api/referral_crm/record":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                from applypilot.networking.referral_tracker import record_connection_request
                res = record_connection_request(
                    company=data.get("company", ""),
                    person_name=data.get("person_name", ""),
                    profile_url=data.get("profile_url", ""),
                    headline=data.get("headline", ""),
                    is_alumni=bool(data.get("is_alumni", False)),
                    degree=data.get("degree", "2nd"),
                    role_type=data.get("role_type", "Engineer"),
                    notes=data.get("notes", ""),
                    job_rowid=data.get("job_rowid")
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/update (Update connection acceptance, referral pitch status, notes)
        elif path == "/api/referral_crm/update":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                req_id = int(data.get("request_id", 0))
                from applypilot.networking.referral_tracker import update_connection_status
                res = update_connection_status(
                    request_id=req_id,
                    status=data.get("status", "accepted"),
                    referral_status=data.get("referral_status"),
                    notes=data.get("notes")
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/sync_accepted (Auto-detect accepted connection requests and sent invites from LinkedIn)
        elif path == "/api/referral_crm/sync_accepted":
            try:
                from applypilot.networking.referral_tracker import sync_accepted_connections_from_linkedin, sync_sent_invitations_from_linkedin
                # 1. First sync sent invites so nothing manual is required!
                sent_res = sync_sent_invitations_from_linkedin(max_check=50, headless=True)
                # 2. Sync accepted connections
                res = sync_accepted_connections_from_linkedin(max_check=50, headless=True)
                res["new_sent_discovered"] = sent_res.get("new_recorded", 0)
                res["total_sent_found"] = sent_res.get("total_sent_found", 0)
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/pitch_generate (Generate tailored referral pitch message and resume for accepted connection)
        elif path == "/api/referral_crm/pitch_generate":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                req_id = int(data.get("request_id", 0))
                from applypilot.networking.referral_tracker import generate_tailored_pitch_for_request
                res = generate_tailored_pitch_for_request(req_id)
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/referral_crm/auto_connect (Auto-discover connections at a company from job URL and optionally send)
        elif path == "/api/referral_crm/auto_connect":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                job_url = data.get("job_url", "").strip()
                max_people = int(data.get("max_people", 5))
                send_connection = bool(data.get("send_connection", False))
                single_profile_url = data.get("single_profile_url", "").strip()

                # Handle single-person connect request (from "Send Request" button per row)
                if single_profile_url:
                    from applypilot.networking.linkedin import connect_in_background
                    from applypilot.networking.referral_tracker import record_connection_request
                    sname = data.get("single_name", "")
                    scomp = data.get("single_company", "")
                    srole = data.get("single_role", "Backend Engineer")
                    is_alum = "rvce" in sname.lower()
                    if is_alum:
                        note = f"Hi {sname.split()[0] if sname else 'there'}, RVCE CSE '25 junior, SDE-1 @ Meesho (Java/Go/Kafka). Interested in {srole} at {scomp} — would you be open to a referral?"[:200]
                    else:
                        note = f"Hi {sname.split()[0] if sname else 'there'}, I'm an SDE-1 Backend Engineer at Meesho (RVCE '25, Java/Go/Kafka/Redis). Interested in the {srole} role at {scomp}. Would love to connect!"[:200]

                    conn_res = connect_in_background(single_profile_url, note=note)
                    if conn_res.get("ok"):
                        rec_res = record_connection_request(
                            company=scomp,
                            person_name=sname or "LinkedIn Connection",
                            profile_url=single_profile_url,
                            headline=srole,
                            is_alumni=is_alum,
                            degree="2nd",
                            role_type="Engineer",
                            notes=f"Auto-connect sent in background via {conn_res.get('method')}",
                            tailored_msg=note
                        )
                        res = {
                            "status": "ok",
                            "message": f"Connection request sent in background to {sname} via {conn_res.get('method')}! Tracked in CRM.",
                            "method": conn_res.get("method"),
                            "db_id": rec_res.get("id")
                        }
                    else:
                        err_msg = conn_res.get("error", "Unknown error")
                        record_connection_request(
                            company=scomp,
                            person_name=sname or "LinkedIn Connection",
                            profile_url=single_profile_url,
                            headline=srole,
                            degree="2nd",
                            role_type="Engineer",
                            notes=f"CONNECT_FAILED: {err_msg}"
                        )
                        res = {
                            "status": "error",
                            "message": f"Failed sending connection request to {sname}: {err_msg}",
                            "error": err_msg
                        }
                else:
                    from applypilot.networking.referral_tracker import auto_connect_referral_from_job_url
                    res = auto_connect_referral_from_job_url(
                        job_url=job_url,
                        max_people=max_people,
                        headless=True,
                        send_connection=send_connection,
                    )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/jobs/prune (Delete stale jobs older than N days that are not in active pipeline state)
        elif path == "/api/jobs/prune":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                days = int(data.get("days", 15))
                from applypilot.database import prune_old_jobs
                res = prune_old_jobs(days=days)
                res["status"] = "ok"
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/cold_crm/update (Update interaction, open count, reply, follow-up, notes)
        elif path == "/api/cold_crm/update":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                outreach_id = int(data.get("outreach_id", 0))
                from applypilot.networking.cold_email_tracker import log_interaction_update
                res = log_interaction_update(
                    outreach_id=outreach_id,
                    open_count=data.get("open_count"),
                    reply_status=data.get("reply_status"),
                    reply_snippet=data.get("reply_snippet"),
                    led_to_call=data.get("led_to_call"),
                    interest_level=data.get("interest_level"),
                    notes=data.get("notes"),
                    increment_followup=bool(data.get("increment_followup", False))
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/cold_crm/generate_followup (Generate copy for follow-up based on open signals)
        elif path == "/api/cold_crm/generate_followup":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                from applypilot.networking.cold_email_tracker import generate_followup_message
                res = generate_followup_message(
                    company=data.get("company", ""),
                    role=data.get("role_title", "Backend Engineer"),
                    recipient_name=data.get("recipient_name", ""),
                    original_subject=data.get("subject", "Application"),
                    followup_number=int(data.get("followup_number", 1)),
                    open_count=int(data.get("open_count", 0))
                )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # /api/linkedin/set_cookie (Save li_at cookie and activate LinkedIn AI agent)
        elif path == "/api/linkedin/set_cookie":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                token = data.get("token", "").strip()
                from applypilot.networking.linkedin import set_li_at_cookie
                ok = set_li_at_cookie(token)
                res = {"status": "ok" if ok else "error", "message": "LinkedIn session saved successfully!" if ok else "Invalid cookie value"}
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 8. /api/linkedin/login
        elif path == "/api/linkedin/login":
            from applypilot.networking.linkedin import login_to_linkedin
            t = threading.Thread(target=login_to_linkedin, kwargs={"timeout_sec": 75, "headed": True}, daemon=True)
            t.start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "launched"}).encode("utf-8"))
            return

        # /api/linkedin/compose_dm (Assisted 1-Click Referral DM auto-composer in isolated browser)
        elif path == "/api/linkedin/compose_dm":
            length = int(self.headers.get("Content-Length", 0))
            body_data = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body_data)
                profile_url = data.get("profile_url", "").strip()
                company = data.get("company", "").strip()
                role_str = data.get("role", "Backend Engineer").strip()
                name_str = data.get("name", "").strip()
                custom_msg = data.get("message", "").strip()
                template = data.get("template", "referral").strip()
                action_type = data.get("action_type", "auto").strip()

                from applypilot.networking.linkedin import compose_referral_dm, connect_in_background, send_linkedin_direct_message
                from applypilot.networking.referral_tracker import record_connection_request

                if action_type in ("connect", "connect_only"):
                    # Send directly in background (Voyager API -> Headless Playwright fallback)
                    note_to_send = custom_msg if action_type == "connect" else None
                    conn_res = connect_in_background(profile_url, note=note_to_send)

                    if conn_res.get("ok"):
                        is_alum = "rvce" in template.lower() or "rvce" in name_str.lower()
                        rec_res = record_connection_request(
                            company=company,
                            person_name=name_str or "LinkedIn Connection",
                            profile_url=profile_url,
                            headline=role_str,
                            is_alumni=is_alum,
                            degree="2nd",
                            role_type="Engineer",
                            notes=f"Sent via background {conn_res.get('method', 'api')}",
                            tailored_msg=custom_msg if action_type == "connect" else ""
                        )
                        # Also sync referral followup engine if job exists
                        try:
                            from applypilot.networking.followup_engine import ReferralFollowUpEngine
                            conn_db = get_connection()
                            job_match = conn_db.execute(
                                "SELECT rowid FROM jobs WHERE LOWER(site) = LOWER(?) OR LOWER(company) = LOWER(?) LIMIT 1",
                                (company, company)
                            ).fetchone()
                            if job_match:
                                engine = ReferralFollowUpEngine(db_path=DB_PATH)
                                engine.mark_referral_requested(
                                    job_id=str(job_match[0]),
                                    contact_name=name_str,
                                    contact_handle=profile_url
                                )
                        except Exception as fe_err:
                            log.debug("Followup engine sync note: %s", fe_err)

                        res = {
                            "status": "ok",
                            "message": f"Connection request sent in background to {name_str or 'connection'} via {conn_res.get('method')}! Tracked in CRM.",
                            "method": conn_res.get("method"),
                            "db_id": rec_res.get("id")
                        }
                    else:
                        err_msg = conn_res.get("error", "Unknown connect error")
                        # Record failed attempt
                        record_connection_request(
                            company=company,
                            person_name=name_str or "LinkedIn Connection",
                            profile_url=profile_url,
                            headline=role_str,
                            degree="2nd",
                            role_type="Engineer",
                            notes=f"CONNECT_FAILED: {err_msg}"
                        )
                        try:
                            from applypilot.networking.followup_engine import ReferralFollowUpEngine
                            conn_db = get_connection()
                            job_match = conn_db.execute(
                                "SELECT rowid FROM jobs WHERE LOWER(site) = LOWER(?) OR LOWER(company) = LOWER(?) LIMIT 1",
                                (company, company)
                            ).fetchone()
                            if job_match:
                                engine = ReferralFollowUpEngine(db_path=DB_PATH)
                                engine.mark_connect_failed(
                                    job_id=str(job_match[0]),
                                    contact_name=name_str,
                                    contact_handle=profile_url,
                                    error_message=err_msg
                                )
                        except Exception:
                            pass
                        res = {
                            "status": "error",
                            "message": f"Could not send connection request: {err_msg}",
                            "error": err_msg
                        }
                elif action_type == "message":
                    # Fully send the message automatically in the background without opening a browser window
                    msg_res = send_linkedin_direct_message(profile_url, custom_msg)
                    if msg_res.get("ok"):
                        is_alum = "rvce" in template.lower() or "rvce" in name_str.lower()
                        rec_res = record_connection_request(
                            company=company,
                            person_name=name_str or "LinkedIn Connection",
                            profile_url=profile_url,
                            headline=role_str,
                            is_alumni=is_alum,
                            degree="1st",
                            role_type="Engineer",
                            notes=f"Message sent directly via background {msg_res.get('method')}",
                            tailored_msg=custom_msg
                        )
                        res = {
                            "status": "ok",
                            "message": f"✓ Message sent directly to {name_str or 'connection'} in the background!",
                            "method": msg_res.get("method"),
                            "db_id": rec_res.get("id")
                        }
                    else:
                        err_msg = msg_res.get("error", "Failed to send message")
                        res = {
                            "status": "error",
                            "message": f"Could not send message: {err_msg}",
                            "error": err_msg
                        }
                else:
                    res = compose_referral_dm(
                        profile_url=profile_url,
                        company=company,
                        role_title=role_str,
                        name=name_str,
                        custom_message=custom_msg,
                        template_type=template,
                        action_type=action_type,
                        headed=True
                    )
            except Exception as e:
                res = {"status": "error", "message": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        # 9. /api/naukri/refresh
        elif path == "/api/naukri/refresh":
            from applypilot.automation.naukri_updater import update_naukri_resume
            t = threading.Thread(target=update_naukri_resume, kwargs={"headed": False}, daemon=True)
            t.start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "initiated", "message": "Naukri resume refresh initiated in background."}).encode("utf-8"))
            return

        # 10. /api/naukri/login
        elif path == "/api/naukri/login":
            from applypilot.automation.naukri_updater import login_interactive
            t = threading.Thread(target=login_interactive, kwargs={"timeout_seconds": 90}, daemon=True)
            t.start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "launched", "message": "Opening browser for Naukri login..."}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


def _ensure_external_auto_applier_running():
    """Ensure Auto_job_applier_linkedIn control panel server is running on port 5000."""
    import sys
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:5000/", timeout=1.0) as resp:
            if resp.status == 200:
                return
    except Exception:
        pass

    tool_dir = Path("D:/ApplyPilot_Workspace/tools/Auto_job_applier_linkedIn")
    app_py = tool_dir / "app.py"
    if not app_py.exists():
        return

    import subprocess
    cmd = [sys.executable, str(app_py)]
    try:
        subprocess.Popen(
            cmd,
            cwd=str(tool_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        log.info("Started external Auto_job_applier_linkedIn server on http://127.0.0.1:5000")
    except Exception as e:
        log.warning("Could not auto-start external applier: %s", e)


def start_dashboard_server(port: int = PORT, open_browser: bool = True):
    from applypilot.database import init_db
    try:
        init_db()
    except Exception as e:
        log.warning(f"init_db warning on dashboard startup: {e}")
    """Start the interactive dashboard server and open it in Chrome/default browser."""
    # Auto-start the external LinkedIn applier control panel alongside ApplyPilot
    _ensure_external_auto_applier_running()

    ThreadingHTTPServer.allow_reuse_address = True
    server = None
    for attempt in range(5):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
            break
        except OSError as e:
            if attempt < 4:
                time.sleep(1)
            else:
                raise e

    url = f"http://127.0.0.1:{port}"
    print(f"\n🚀 ApplyPilot 2.0 Command Dashboard running at: {url}")
    print("   Press Ctrl+C to stop the dashboard server.\n")

    if open_browser:
        launch_url_in_browser(url)

    while True:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping dashboard server...")
            try:
                server.shutdown()
            except Exception:
                pass
            break
        except Exception as e:
            print(f"\nServer error: {e}", file=sys.stderr)
            time.sleep(1)
