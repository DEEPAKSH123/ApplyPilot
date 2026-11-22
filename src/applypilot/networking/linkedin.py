"""LinkedIn Session Manager, Post Scraper & Alumni Network Engine.

Supports:
- Authenticating to LinkedIn using persistent browser sessions and session cookies (`li_at`).
- Searching hiring posts for backend engineering roles with automatic recruiter email discovery.
- Discovering RVCE alumni, engineering managers, and 1st/2nd-degree connections at target companies.
- Exporting findings to SQLite database and providing MCP tools for Antigravity.
"""

import json
import logging
import os
import re
import sqlite3
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from applypilot import config
from applypilot.apply.chrome import (
    acquire_browser_lock,
    launch_isolated_playwright_context,
)
from applypilot.config import APP_DIR, load_profile
from applypilot.database import get_connection

log = logging.getLogger(__name__)

SESSION_FILE = APP_DIR / "linkedin_session.json"
STORAGE_STATE_FILE = APP_DIR / "storage_state.json"
COOLDOWN_FILE = config.LINKEDIN_COOLDOWN_FILE
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")

# Circuit breaker constants
AUTH_EXPIRED_OR_CHALLENGED = "AUTH_EXPIRED_OR_CHALLENGED"
COOLDOWN_DURATION_HOURS = 24


def is_linkedin_cooldown_active() -> tuple[bool, str]:
    """Check if LinkedIn automation is paused by the circuit breaker."""
    cooldown_file = getattr(config, "LINKEDIN_COOLDOWN_FILE", Path.home() / ".applypilot" / "linkedin_cooldown.json")
    if not cooldown_file.exists():
        return False, ""
    try:
        data = json.loads(cooldown_file.read_text(encoding="utf-8"))
        cooldown_until_str = data.get("cooldown_until")
        if not cooldown_until_str:
            return False, ""
        cooldown_until = datetime.fromisoformat(cooldown_until_str)
        now = datetime.now(timezone.utc)
        if now < cooldown_until:
            reason = data.get("reason", "LinkedIn circuit breaker active")
            remaining = (cooldown_until - now).total_seconds() / 3600
            return True, f"{reason} (cooldown remaining: {remaining:.1f}h)"
    except Exception as e:
        log.warning("Could not read LinkedIn cooldown file: %s", e)
    return False, ""


def trigger_linkedin_circuit_breaker(reason: str, trigger_url: str = "") -> dict[str, Any]:
    """Immediately trigger 24-hour circuit breaker and write cooldown file."""
    now = datetime.now(timezone.utc)
    cooldown_until = now + timedelta(hours=COOLDOWN_DURATION_HOURS)
    payload = {
        "triggered_at": now.isoformat(),
        "cooldown_until": cooldown_until.isoformat(),
        "reason": reason,
        "trigger_url": trigger_url,
        "status": AUTH_EXPIRED_OR_CHALLENGED,
    }
    cooldown_file = getattr(config, "LINKEDIN_COOLDOWN_FILE", Path.home() / ".applypilot" / "linkedin_cooldown.json")
    try:
        cooldown_file.parent.mkdir(parents=True, exist_ok=True)
        cooldown_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("Failed to write LinkedIn cooldown file: %s", e)

    log.error(
        "CRITICAL: %s triggered for LinkedIn automation! Cooldown activated for %d hours until %s. Reason: %s (URL: %s)",
        AUTH_EXPIRED_OR_CHALLENGED,
        COOLDOWN_DURATION_HOURS,
        cooldown_until.isoformat(),
        reason,
        trigger_url,
    )
    return payload


def check_page_for_challenges_or_auth(page_or_url: Any, status_code: int | None = None) -> tuple[bool, str]:
    """Check if response or page hit login, challenge, or auth errors."""
    if status_code in (401, 403, 429):
        return True, f"HTTP {status_code} Auth/Rate-limit error"

    url_str = ""
    if hasattr(page_or_url, "url"):
        url_str = str(page_or_url.url).lower()
    elif isinstance(page_or_url, str):
        url_str = page_or_url.lower()

    if "/checkpoint/challenge" in url_str or "checkpoint/challenge" in url_str:
        return True, "Encountered checkpoint challenge verification"
    if "/login" in url_str or "/uas/login" in url_str:
        return True, "Redirected to login page"

    if hasattr(page_or_url, "title"):
        try:
            title = page_or_url.title().lower()
            if "security verification" in title or "checkpoint" in title or "sign in" in title:
                return True, f"Challenge title detected: {title}"
        except Exception:
            pass

    return False, ""

# Regex patterns to detect years of experience required
EXP_PATTERNS = [
    re.compile(r'(\d+)\+?\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)(?:\s*of)?\s*(?:relevant|hands-on|industry|software|backend|work)?\s*experience', re.IGNORECASE),
    re.compile(r'(\d+)\+?\s*(?:to|-)\s*(\d+)\s*(?:years?|yrs?)', re.IGNORECASE),
    re.compile(r'(\d+)\+?\s*(?:years?|yrs?)(?:\s*of)?\s*(?:relevant|hands-on|industry|software|backend|work)?\s*experience', re.IGNORECASE),
    re.compile(r'(\d+)\+\s*(?:years?|yrs?)', re.IGNORECASE),
    re.compile(r'experience(?:\s*of)?\s*:?\s*(\d+)\+?\s*(?:to|-)?\s*(\d+)?\s*(?:years?|yrs?)', re.IGNORECASE),
    re.compile(r'(?:minimum|min|at least)\s*(\d+)\+?\s*(?:years?|yrs?)', re.IGNORECASE),
    re.compile(r'(\d+)\+?\s*yoe\b', re.IGNORECASE),
    re.compile(r'yoe\s*:?\s*(\d+)\+?', re.IGNORECASE),
]

# Companies to always exclude across all discovery and incognito modes
EXCLUDED_COMPANIES = ["accenture", "infosys", "capgemini", "flexiple"]


def is_company_excluded(company_name: str | None) -> tuple[bool, str]:
    """Check if company should always be skipped."""
    if not company_name:
        return False, ""
    c_lower = company_name.lower().strip()
    for exc in EXCLUDED_COMPANIES:
        if exc in c_lower:
            return True, f"Excluded company ({exc})"
    return False, ""


def check_experience_exceeds(text: str, max_years: int = 3) -> tuple[bool, str]:
    """Check if the post text or description specifies experience exceeding candidate level.
    For Deepak (0-3 YOE target):
    - Any minimum experience > 3 years (e.g. 4+, 5+, 6+) is rejected.
    - Any range with upper bound >= 5 years (e.g. 3-5, 4-8, 6-10) is rejected.
    - If upper bound exceeds max_years (e.g. 4-6 yrs), it is rejected.
    """
    if not text:
        return False, ""
    for pat in EXP_PATTERNS:
        for m in pat.finditer(text):
            groups = [int(g) for g in m.groups() if g and g.isdigit()]
            if groups:
                min_exp = groups[0]
                max_exp = groups[1] if len(groups) > 1 else min_exp
                if min_exp > max_years or max_exp >= 5 or (len(groups) > 1 and max_exp > max_years):
                    return True, f"{m.group(0)} (exceeds {max_years} years target)"
    return False, ""


def is_linkedin_authenticated() -> bool:
    """Check if LinkedIn session cookies or profile exists."""
    if not SESSION_FILE.exists():
        return False
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
        return any(c.get("name") == "li_at" for c in cookies)
    except Exception:
        return False


def get_stored_cookies() -> list[dict]:
    """Retrieve stored LinkedIn cookies from session files, prioritizing ~/.applypilot/linkedin_cookies.json."""
    cookie_file = getattr(config, "LINKEDIN_COOKIES_FILE", Path.home() / ".applypilot" / "linkedin_cookies.json")
    if cookie_file.exists():
        try:
            data = json.loads(cookie_file.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
            if isinstance(data, dict) and "cookies" in data:
                return data["cookies"]
        except Exception:
            pass

    if STORAGE_STATE_FILE.exists():
        try:
            data = json.loads(STORAGE_STATE_FILE.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            if cookies:
                return cookies
        except Exception:
            pass

    if not SESSION_FILE.exists():
        return []
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data.get("cookies", [])
    except Exception:
        return []


def save_stored_cookies(cookies: list[dict], user_info: dict | None = None) -> None:
    """Save LinkedIn cookies and metadata to disk and sync with linkedin_cookies.json."""
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "user_info": user_info or {},
        "cookies": cookies
    }
    SESSION_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("Saved %d LinkedIn cookies to %s", len(cookies), SESSION_FILE)
    try:
        # Also maintain standard Playwright storage_state.json format
        playwright_state = {
            "cookies": cookies,
            "origins": []
        }
        STORAGE_STATE_FILE.write_text(json.dumps(playwright_state, indent=2), encoding="utf-8")
    except Exception as se:
        log.warning("Could not sync storage_state.json: %s", se)

    try:
        cookie_file = getattr(config, "LINKEDIN_COOKIES_FILE", Path.home() / ".applypilot" / "linkedin_cookies.json")
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        cookie_file.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    except Exception as ce:
        log.warning("Could not sync linkedin_cookies.json: %s", ce)


def set_li_at_cookie(li_at_token: str) -> bool:
    """Manually set or update the li_at session cookie."""
    token = li_at_token.strip().strip('"').strip("'")
    if not token or len(token) < 10:
        return False
    cookie_entry = {
        "name": "li_at",
        "value": token,
        "domain": ".linkedin.com",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "None"
    }
    cookies = [cookie_entry]
    existing = get_stored_cookies()
    for c in existing:
        if c.get("name") != "li_at":
            cookies.append(c)
    save_stored_cookies(cookies)
    return True


def login_to_linkedin(timeout_sec: int = 75, headed: bool = True) -> dict[str, Any]:
    """Launch isolated Playwright profile for user to log in to LinkedIn or verify active session."""
    from playwright.sync_api import sync_playwright

    log.info("Launching isolated Playwright browser for LinkedIn authentication (headed=%s)...", headed)

    with acquire_browser_lock():
        with sync_playwright() as p:
            context = launch_isolated_playwright_context(
                p,
                headless=not headed,
                color_scheme="dark",
                viewport={"width": 1280, "height": 850},
            )

            page = context.pages[0] if context.pages else context.new_page()

            # Inject existing cookies if available
            existing_cookies = get_stored_cookies()
            if existing_cookies:
                try:
                    context.add_cookies(existing_cookies)
                except Exception as ce:
                    log.warning("Could not pre-load cookies: %s", ce)

            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            time.sleep(2)

            # Check if actually logged in by inspecting cookies for 'li_at'
            initial_cookies = context.cookies()
            if any(c.get("name") == "li_at" for c in initial_cookies):
                log.info("Already logged in to LinkedIn with valid session cookie!")
                save_stored_cookies(initial_cookies)
                context.close()
                return {
                    "status": "authenticated",
                    "message": "Already logged in to LinkedIn successfully!",
                    "session_saved": True
                }

            # Otherwise navigate to login page so Deepak can enter credentials
            log.info("Navigating to LinkedIn login page for user authentication...")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

            # Wait for user to complete login (cookies will contain 'li_at')
            start_time = time.time()
            authenticated = False

            while time.time() - start_time < timeout_sec:
                current_cookies = context.cookies()
                if any(c.get("name") == "li_at" for c in current_cookies):
                    authenticated = True
                    break
                time.sleep(1.5)

            if authenticated:
                time.sleep(1)
                final_cookies = context.cookies()
                save_stored_cookies(final_cookies)
                context.close()
                return {
                    "status": "authenticated",
                    "message": "Successfully logged in and saved LinkedIn session!",
                    "session_saved": True
                }
            else:
                context.close()
                return {
                    "status": "timeout",
                    "message": f"Login timed out after {timeout_sec}s. Please try again.",
                    "session_saved": False
                }


def search_linkedin_posts(
    keywords: str = 'backend engineer AND ("hiring" OR "requirement")',
    max_results: int = 10,
    save_to_db: bool = True
) -> list[dict[str, Any]]:
    """Search LinkedIn for recent hiring posts matching keywords and extract leads."""
    from playwright.sync_api import sync_playwright

    # Safety check: Circuit breaker
    is_cooling, cool_reason = is_linkedin_cooldown_active()
    if is_cooling:
        log.warning("LinkedIn search_linkedin_posts aborted: %s", cool_reason)
        return [{"error": f"Circuit breaker active: {cool_reason}", "status": AUTH_EXPIRED_OR_CHALLENGED}]

    encoded_kw = urllib.parse.quote(keywords)
    search_url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_kw}&sortBy=%22date_posted%22"

    results = []

    with acquire_browser_lock():
        with sync_playwright() as p:
            context = launch_isolated_playwright_context(
                p,
                headless=True,
                color_scheme="dark",
            )

            existing_cookies = get_stored_cookies()
            if existing_cookies:
                try:
                    context.add_cookies(existing_cookies)
                except Exception:
                    pass

            page = context.pages[0] if context.pages else context.new_page()
            response = page.goto(search_url, wait_until="domcontentloaded")
            time.sleep(4)

            status_code = response.status if response else None
            is_challenged, ch_reason = check_page_for_challenges_or_auth(page, status_code=status_code)
            if is_challenged:
                trigger_linkedin_circuit_breaker(f"search_linkedin_posts: {ch_reason}", trigger_url=page.url)
                context.close()
                return [{"error": ch_reason, "status": AUTH_EXPIRED_OR_CHALLENGED}]

            # Scroll down to load posts
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 1000);")
            time.sleep(1.5)

        # Parse posts
        post_elements = page.query_selector_all("div.feed-shared-update-v2, div[data-urn*='urn:li:activity']")

        for post_el in post_elements[:max_results]:
            try:
                text_content = post_el.inner_text()
                if not text_content or len(text_content) < 40:
                    continue

                # Extract author name & headline
                author_el = post_el.query_selector("span.update-components-actor__name, .feed-shared-actor__name")
                author_name = author_el.inner_text().strip() if author_el else "LinkedIn Member"

                headline_el = post_el.query_selector("span.update-components-actor__description, .feed-shared-actor__description")
                headline = headline_el.inner_text().strip() if headline_el else ""

                # Extract post URL & posted time text if available
                link_el = post_el.query_selector("a[href*='/feed/update/'], a[href*='urn:li:activity']")
                post_url = link_el.get_attribute("href") if link_el else ""
                if post_url and not post_url.startswith("http"):
                    post_url = f"https://www.linkedin.com{post_url}"

                # Calculate estimated posted time if relative time indicator is found (e.g. 1h, 2h, 30m, 1d)
                post_posted_at = datetime.now(timezone.utc)
                time_el = post_el.query_selector(".update-components-actor__sub-description, time, span.visually-hidden")
                time_text = time_el.inner_text().strip().lower() if time_el else ""
                d_match = re.search(r"(\d+)\s*d(?:ay)?s?", time_text)
                h_match = re.search(r"(\d+)\s*h(?:our)?s?", time_text)
                m_match = re.search(r"(\d+)\s*m(?:in)?s?", time_text)
                w_match = re.search(r"(\d+)\s*w(?:eek)?s?", time_text)
                if m_match:
                    post_posted_at -= timedelta(minutes=int(m_match.group(1)))
                elif h_match:
                    post_posted_at -= timedelta(hours=int(h_match.group(1)))
                elif d_match:
                    post_posted_at -= timedelta(days=int(d_match.group(1)))
                elif w_match:
                    post_posted_at -= timedelta(days=int(w_match.group(1)) * 7)

                # Extract emails
                emails = EMAIL_REGEX.findall(text_content)
                recruiter_email = emails[0] if emails else ""

                # Infer company from headline or text
                company = "Tech Company"
                comp_match = re.search(r"(?:at|@|join|hiring\s+for)\s+([A-Z][A-Za-z0-9]{2,20})\b", text_content)
                if comp_match:
                    company = comp_match.group(1)

                # Skip blacklisted companies (Accenture, Infosys, Capgemini, Flexiple)
                is_excluded, exc_reason = is_company_excluded(company)
                if not is_excluded:
                    is_excluded, exc_reason = is_company_excluded(text_content)
                if is_excluded:
                    log.info("Skipping post from excluded company (%s): %s", exc_reason, company)
                    continue

                # Check experience requirement: must strictly match candidate level (0-3 years)
                is_over_exp, exp_reason = check_experience_exceeds(text_content, max_years=3)
                if is_over_exp:
                    log.info("Skipping post requiring > 3 years experience (%s): %s", exp_reason, text_content[:120].replace('\n', ' '))
                    continue

                item = {
                    "author": author_name,
                    "headline": headline,
                    "company": company,
                    "post_text": text_content[:400] + ("..." if len(text_content) > 400 else ""),
                    "full_text": text_content,
                    "post_url": post_url or search_url,
                    "recruiter_email": recruiter_email,
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "date_posted": post_posted_at.strftime("%Y-%m-%d")
                }
                results.append(item)

                # Save to database if legitimate hiring or requirement post
                lower_text = text_content.lower()
                is_hiring_post = any(k in lower_text for k in ("hiring", "requirement", "requirements", "opening", "opportunity", "referral"))
                if save_to_db and (recruiter_email or is_hiring_post):
                    _save_lead_to_db(item)

            except Exception as pe:
                log.debug("Error parsing post: %s", pe)

        context.close()

    log.info("Extracted %d LinkedIn posts for query '%s'", len(results), keywords)
    return results


def search_linkedin_connections(
    company: str,
    role: str = "backend",
    school: str = "RV College of Engineering",
    max_results: int = 10
) -> list[dict[str, Any]]:
    """Search LinkedIn for 1st-degree and 2nd-degree connections or RVCE alumni at a target company."""
    from playwright.sync_api import sync_playwright
    from applypilot.networking.outreach import clean_company_name

    # Safety check: Circuit breaker
    is_cooling, cool_reason = is_linkedin_cooldown_active()
    if is_cooling:
        log.warning("LinkedIn search_linkedin_connections aborted: %s", cool_reason)
        return [{"error": f"Circuit breaker active: {cool_reason}", "status": AUTH_EXPIRED_OR_CHALLENGED}]

    comp_clean = clean_company_name(company)
    if not comp_clean:
        comp_clean = company.strip()

    if comp_clean:
        comp_enc = urllib.parse.quote(f'"{comp_clean}"')
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={comp_enc}&network=%5B%22F%22%2C%22S%22%5D"
    else:
        search_url = "https://www.linkedin.com/search/results/people/?network=%5B%22F%22%2C%22S%22%5D"

    results = []

    try:
        from applypilot.apply.chrome import open_isolated_context
        with open_isolated_context(headless=True) as context:
            page = context.new_page()
            response = page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)

            status_code = response.status if response else None
            is_challenged, ch_reason = check_page_for_challenges_or_auth(page, status_code=status_code)
            if is_challenged:
                trigger_linkedin_circuit_breaker(f"search_linkedin_connections: {ch_reason}", trigger_url=page.url)
                return [{"error": ch_reason, "status": AUTH_EXPIRED_OR_CHALLENGED}]

            # Robust extraction supporting modern LinkedIn DOM
            raw_cards = page.evaluate("""
            () => {
                const results = [];
                const candidateLinks = Array.from(document.querySelectorAll('a[href*="/in/"]'));
                const seenUrls = new Set();
                
                for (const a of candidateLinks) {
                    const href = a.href ? a.href.split('?')[0].replace(/\\/+$/, '') : '';
                    if (!href || href.includes('/in/mini-profile') || seenUrls.has(href)) continue;
                    
                    const text = a.innerText.trim();
                    if (!text || text.includes('mutual connection') || text.includes('View ') || text.length < 2) continue;
                    
                    // The entity text is reliably at 2 levels above the link
                    let lockup = a.parentElement ? (a.parentElement.parentElement || a.parentElement) : a;
                    let lockupText = lockup.innerText || '';
                    
                    // Also check broader card container for Current/Past roles and message buttons
                    let container = a.closest('li') || a.closest('div.scaffold-layout__list-item');
                    if (!container) {
                        let parent = a.parentElement;
                        for (let depth = 0; depth < 5 && parent && parent.tagName !== 'LI'; depth++) {
                            parent = parent.parentElement;
                        }
                        container = parent || lockup;
                    }
                    const fullCardText = container ? container.innerText : lockupText;
                    
                    // Only the primary person on the card has '1st' or '2nd' in their own entity lockup (excludes mutuals)
                    if (!lockupText.includes('1st') && !lockupText.includes('2nd') && !lockupText.includes('3rd')) {
                        continue;
                    }
                    
                    seenUrls.add(href);
                    
                    const lockupLines = lockupText.split('\\n').map(l => l.trim()).filter(Boolean);
                    const fullLines = fullCardText.split('\\n').map(l => l.trim()).filter(Boolean);
                    
                    let name = text.split('\\n')[0].replace(/•.*/, '').trim();
                    let degree = '1st';
                    if (lockupText.includes('2nd') || fullCardText.includes('2nd')) degree = '2nd';
                    else if (lockupText.includes('3rd') || fullCardText.includes('3rd')) degree = '3rd';
                    
                    let headline = '';
                    let location = 'Bengaluru, India';
                    let currentRole = '';
                    let pastRole = '';
                    
                    for (let i = 0; i < lockupLines.length; i++) {
                        const l = lockupLines[i];
                        if (l.includes('1st') || l.includes('2nd') || l.includes('3rd')) {
                            if (i + 1 < lockupLines.length) {
                                headline = lockupLines[i+1];
                            }
                            if (i + 2 < lockupLines.length) {
                                location = lockupLines[i+2];
                            }
                            break;
                        }
                    }
                    
                    for (const l of fullLines) {
                        if (l.startsWith('Current:')) currentRole = l.replace('Current:', '').trim();
                        if (l.startsWith('Past:')) pastRole = l.replace('Past:', '').trim();
                    }
                    
                    const isAlumni = fullCardText.toLowerCase().includes('rvce') || fullCardText.toLowerCase().includes('rv college') || headline.toLowerCase().includes('rvce');
                    
                    results.push({
                        name: name,
                        headline: headline,
                        location: location,
                        current_role: currentRole,
                        past_role: pastRole,
                        profile_url: href,
                        degree: degree,
                        is_alumni: isAlumni
                    });
                }
                return results;
            }
        """)

            for c in raw_cards:
                c["company"] = comp_clean
                c["school"] = school
                c["search_url"] = search_url
                results.append(c)
    except Exception as le:
        log.warning("Could not run isolated browser for connection scan: %s", le)
        return [{"error": f"Browser launch error: {le}"}]

    # ── CRITICAL FIX: Filter to only people CURRENTLY at target company ──
    # LinkedIn keyword search matches anyone who ever mentioned the company
    # (including past roles). We must verify the person currently works there.
    comp_lower = comp_clean.lower().strip()
    filtered_results = []
    for c in results:
        headline = (c.get("headline") or "").lower()
        current_role = (c.get("current_role") or "").lower()
        past_role = (c.get("past_role") or "").lower()

        # Case 1: current_role explicitly mentions the company → definitely current
        if comp_lower and comp_lower in current_role:
            c["_match_type"] = "current_role"
            filtered_results.append(c)
            continue

        # Case 2: headline mentions the company (headline = current position)
        if comp_lower and comp_lower in headline:
            # But exclude if headline only mentions it in a "Past:" or "Former" context
            if "past:" not in headline and "former" not in headline and "ex-" not in headline and "previously" not in headline:
                c["_match_type"] = "headline"
                filtered_results.append(c)
                continue

        # Case 3: No current_role detected but company is ONLY in past_role → SKIP
        if comp_lower and comp_lower in past_role and not current_role:
            log.info("Skipping %s — '%s' appears only in PAST role, not current company.", c.get("name"), comp_clean)
            continue

        # Case 4: 1st-degree connection (already connected) — keep as likely current
        # since LinkedIn keyword search with F filter usually matches current
        if c.get("degree") == "1st":
            # Extra check: if past_role mentions company but headline doesn't, still skip
            if comp_lower and comp_lower in past_role and comp_lower not in headline:
                log.info("Skipping 1st-degree %s — '%s' in past role only.", c.get("name"), comp_clean)
                continue
            c["_match_type"] = "1st_degree"
            filtered_results.append(c)
            continue

        # Case 5: If neither current nor past explicitly mention company,
        # it may be in their overall card text (LinkedIn search matched it somewhere)
        # Only include if there's NO past_role mentioning it
        if comp_lower and comp_lower not in past_role:
            c["_match_type"] = "keyword_match"
            filtered_results.append(c)
            continue

        # Default: skip (company only appears in past context)
        log.info("Skipping %s — could not confirm '%s' as current employer.", c.get("name"), comp_clean)

    results = filtered_results
    log.info("After current-company filter: %d of %d connections for '%s'", len(results), len(raw_cards), comp_clean)

    # Sort: 1st-degree first, RVCE alumni first, current employee first
    def sort_score(c):
        score = 0
        if c.get("degree") == "1st":
            score += 10
        if c.get("is_alumni"):
            score += 8
        if c.get("current_role"):
            score += 5
        # Boost people confirmed via current_role or headline match
        if c.get("_match_type") == "current_role":
            score += 15
        elif c.get("_match_type") == "headline":
            score += 12
        return score

    results.sort(key=sort_score, reverse=True)
    log.info("Extracted %d connections for company '%s'", len(results), comp_clean)
    return results[:max_results]


def _save_lead_to_db(lead: dict) -> None:
    """Store discovered LinkedIn post hiring lead in ApplyPilot DB."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    date_posted = lead.get("date_posted") or ""

    url = lead.get("post_url") or f"https://www.linkedin.com/feed/update/{int(time.time())}"
    title = f"Backend Engineer (via {lead.get('author', 'Recruiter')})"
    company = lead.get("company", "Tech Company")
    recruiter_email = lead.get("recruiter_email", "")

    c.execute("""
        INSERT OR IGNORE INTO jobs
        (url, title, location, site, strategy, description, full_description, recruiter_email, discovered_at, application_url, date_posted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        url,
        title,
        "Bengaluru / India (LinkedIn Post)",
        company,
        "linkedin_post",
        lead.get("post_text", ""),
        lead.get("full_text", ""),
        recruiter_email,
        now,
        url,
        date_posted
    ))
    conn.commit()


def compose_referral_dm(
    profile_url: str,
    company: str = "",
    role_title: str = "Backend Engineer",
    name: str = "",
    custom_message: str = "",
    template_type: str = "referral",
    action_type: str = "auto",  # 'auto', 'connect', 'message'
    headed: bool = True
) -> dict[str, Any]:
    """Launch isolated browser, open connection profile/chat, and auto-type personalized referral message or connection note.

    If action_type == 'connect', specifically clicks Connect, Add a note, fills custom note, and highlights Send!
    Human-in-the-Loop Safe: Pre-types the message and pauses for Deepak to click 'Send'.
    """
    from playwright.sync_api import sync_playwright

    clean_url = (profile_url or "").strip()
    if not clean_url:
        return {"status": "error", "message": "No profile URL provided."}
    if not clean_url.startswith("http"):
        if clean_url.startswith("in/"):
            clean_url = f"https://www.linkedin.com/{clean_url}"
        else:
            clean_url = f"https://www.linkedin.com/in/{clean_url}"

    first_name = name.split()[0] if name else ""
    first_name_salutation = f"Hi {first_name}," if first_name else "Hi,"
    comp_label = company or "your company"

    if custom_message:
        body_msg = custom_message
        short_note = custom_message[:295]
    elif template_type == "alumni":
        body_msg = (
            f"{first_name_salutation}\n\n"
            f"Saw that you're at {comp_label}. I graduated from RVCE in CSE ('25) and am currently working as an SDE-I at Meesho.\n\n"
            f"I came across the {role_title} opening and wanted to check if you'd be comfortable referring a junior from RVCE. I work mainly with Java, Go, Kafka, and Redis on backend services.\n\n"
            f"Happy to send my resume over if you're open to it.\n\n"
            f"Thanks,\nDeepak S H\nhttps://www.linkedin.com/in/deepak-s-h-82b772254"
        )
        short_note = f"Hi {first_name or 'there'}, RVCE CSE '25 junior here, currently SDE-1 @ Meesho (Java/Go/Kafka). Saw the {role_title} opening at {comp_label} and wanted to check if you could refer me!"[:295]
    elif template_type == "recruiter":
        body_msg = (
            f"{first_name_salutation}\n\n"
            f"I noticed the {role_title} role at {comp_label} and wanted to reach out directly.\n\n"
            f"I'm an SDE-I Backend Engineer at Meesho working on distributed reconciliation pipelines and microservices in Java, Go, Kafka, and Redis (RVCE CSE '25, CGPA 8.92).\n\n"
            f"My day-to-day work closely matches your backend stack, and I can join immediately. Could I share my resume with you for consideration?\n\n"
            f"Thanks,\nDeepak S H\nhttps://www.linkedin.com/in/deepak-s-h-82b772254"
        )
        short_note = f"Hi {first_name or 'there'}, SDE-1 Backend @ Meesho (Java/Go/Kafka). Saw the {role_title} role at {comp_label} and would love to share my resume for consideration!"[:295]
    else:
        body_msg = (
            f"{first_name_salutation}\n\n"
            f"Saw your post about the {role_title} opening at {comp_label} and that you're collecting profiles for referrals.\n\n"
            f"I'm an SDE-I Backend Engineer at Meesho (RVCE '25, CGPA 8.92). I work on backend services using Java, Go, Kafka, and Redis.\n\n"
            f"I've attached my resume. Could you please share it with the hiring team or submit a referral?\n\n"
            f"Quick details:\n"
            f"• Current: SDE-I Backend @ Meesho\n"
            f"• Experience: 2 years (Full-time Backend @ Meesho + Active Internship Engagements)\n"
            f"• Notice: Immediate\n"
            f"• LinkedIn: https://www.linkedin.com/in/deepak-s-h-82b772254\n\n"
            f"Thanks for your help,\nDeepak S H"
        )
        short_note = f"Hi {first_name or 'there'}, SDE-1 Backend @ Meesho (Java/Go/Kafka). Saw the {role_title} role at {comp_label} and wanted to share my profile for a referral!"[:295]

    # Also copy to clipboard so user has it immediately
    try:
        import subprocess
        subprocess.run(["powershell", "-Command", f"Set-Clipboard -Value @'\n{body_msg}\n'@"], check=False)
    except Exception:
        pass

    log.info("Composing LinkedIn referral DM for: %s", clean_url)

    def _worker():
        with acquire_browser_lock():
            with sync_playwright() as p:
                context = launch_isolated_playwright_context(
                    p,
                    headless=not headed,
                    color_scheme="dark",
                    viewport={"width": 1280, "height": 850},
                )

                # Pre-load cookies
                existing_cookies = get_stored_cookies()
                if existing_cookies:
                    try:
                        context.add_cookies(existing_cookies)
                    except Exception:
                        pass

                page = context.pages[0] if context.pages else context.new_page()
                page.goto(clean_url, wait_until="domcontentloaded")
                time.sleep(3)

            # Check if name and company are detectable on page
            nonlocal first_name, name, company
            full_detected_name = name
            headline_text = ""
            h1 = page.query_selector("h1")
            if h1:
                raw_title = h1.inner_text().strip()
                if raw_title:
                    full_detected_name = raw_title
                    first_name = raw_title.split()[0]

            # Try detecting current headline or company if not passed
            head_el = page.query_selector("div.text-body-medium, h2")
            if head_el:
                headline_text = head_el.inner_text().strip()

            if not company:
                # Check for company in experience or top section
                exp_comp_el = page.query_selector("div[data-view-name='profile-card'] :has-text('· Full-time'), button[aria-label*='Current company']")
                if exp_comp_el:
                    company = exp_comp_el.inner_text().split("\n")[0].strip()
                elif headline_text and (" at " in headline_text or " @ " in headline_text):
                    part = headline_text.split(" at ")[-1] if " at " in headline_text else headline_text.split(" @ ")[-1]
                    company = part.split("|")[0].split("·")[0].strip()
                if not company:
                    company = "Target Company"

            # Auto-log to Referral Network CRM immediately so user doesn't have to type anything manually!
            try:
                from applypilot.networking.referral_tracker import record_connection_request
                is_alumni_detected = "rvce" in headline_text.lower() or "rv college" in headline_text.lower() or template_type == "alumni"
                record_connection_request(
                    company=company,
                    person_name=full_detected_name or first_name or "LinkedIn Connection",
                    profile_url=clean_url,
                    headline=headline_text or role_title,
                    is_alumni=is_alumni_detected,
                    degree="2nd",
                    role_type="Engineer",
                    notes=f"Auto-logged via 1-Click {action_type} for {role_title}"
                )
                log.info("Auto-recorded connection request in Referral Network CRM for: %s @ %s", full_detected_name or first_name, company)
            except Exception as re_err:
                log.warning("Could not auto-log to Referral Network CRM: %s", re_err)

            typed = False

            # If action_type is explicitly 'connect' or 'connect_only', prioritize clicking Connect
            if action_type in ("connect", "connect_only"):
                try:
                    connect_btn = page.query_selector("button:has-text('Connect'), a:has-text('Connect')")
                    if not connect_btn:
                        more_btn = page.query_selector("button[aria-label*='More actions'], button:has-text('More')")
                        if more_btn:
                            more_btn.click()
                            time.sleep(1)
                            connect_btn = page.query_selector("div[role='button']:has-text('Connect'), button:has-text('Connect')")

                    if connect_btn:
                        connect_btn.click()
                        time.sleep(1.5)

                        if action_type == "connect_only":
                            # For pure Connect (no note), look for "Send without a note" or "Send now"
                            send_without_note_btn = page.query_selector(
                                "button[aria-label*='Send without a note'], button:has-text('Send without a note'), button:has-text('Send now')"
                            )
                            if send_without_note_btn:
                                page.evaluate("""() => {
                                    const btn = document.querySelector('button[aria-label*="Send without a note"], button:has-text("Send without a note"), button:has-text("Send now")');
                                    if (btn) {
                                        btn.style.outline = '3px solid #10b981';
                                        btn.style.boxShadow = '0 0 16px #10b981';
                                    }
                                }""")
                                typed = True
                                log.info("Opened Connect modal in 'Just Connect' mode (without note).")
                            else:
                                typed = True
                        else:
                            # Look for "Add a note"
                            add_note_btn = page.query_selector("button:has-text('Add a note'), button[aria-label*='Add a note']")
                            if add_note_btn:
                                add_note_btn.click()
                                time.sleep(1)

                            textarea = page.query_selector("textarea#custom-message, textarea[name='message']")
                            if textarea:
                                textarea.fill(short_note)
                                typed = True
                                log.info("Filled personalized note into connection request modal!")

                                # Highlight the Send invitation button in green
                                page.evaluate("""() => {
                                    const btn = document.querySelector('button[aria-label*="Send invitation"], button:has-text("Send"), button[aria-label*="Send now"]');
                                    if (btn) {
                                        btn.style.outline = '3px solid #10b981';
                                        btn.style.boxShadow = '0 0 16px #10b981';
                                    }
                                }""")
                except Exception as ce:
                    log.warning("Could not fill connection note: %s", ce)

            # Otherwise, try clicking Message button (for 1st-degree connections)
            if not typed and action_type not in ("connect", "connect_only"):
                msg_btn = page.query_selector("button:has-text('Message'), a:has-text('Message'), button[aria-label*='Message']")
                if msg_btn:
                    try:
                        msg_btn.click()
                        time.sleep(2)
                        # Locate chat box
                        chat_box = page.wait_for_selector(
                            "div.msg-form__contenteditable, div[role='textbox'][aria-label*='Write a message']",
                            timeout=6000
                        )
                        if chat_box:
                            chat_box.click()
                            time.sleep(0.5)
                            page.keyboard.insert_text(body_msg)
                            typed = True
                            log.info("Successfully typed message into LinkedIn chat box!")

                            # Highlight the send button
                            page.evaluate("""() => {
                                const btn = document.querySelector('button.msg-form__send-button, button[type="submit"].msg-form__send-btn');
                                if (btn) {
                                    btn.style.outline = '3px solid #10b981';
                                    btn.style.boxShadow = '0 0 16px #10b981';
                                }
                            }""")
                    except Exception as me:
                        log.warning("Could not auto-type in inline chat: %s", me)

            # If still not typed, try "Connect" -> "Add a note"
            if not typed:
                try:
                    connect_btn = page.query_selector("button:has-text('Connect'), a:has-text('Connect')")
                    if not connect_btn:
                        more_btn = page.query_selector("button[aria-label*='More actions'], button:has-text('More')")
                        if more_btn:
                            more_btn.click()
                            time.sleep(1)
                            connect_btn = page.query_selector("div[role='button']:has-text('Connect'), button:has-text('Connect')")

                    if connect_btn:
                        connect_btn.click()
                        time.sleep(1.5)

                        # Look for "Add a note"
                        add_note_btn = page.query_selector("button:has-text('Add a note'), button[aria-label*='Add a note']")
                        if add_note_btn:
                            add_note_btn.click()
                            time.sleep(1)

                        textarea = page.query_selector("textarea#custom-message, textarea[name='message']")
                        if textarea:
                            textarea.fill(short_note)
                            typed = True
                            log.info("Filled personalized note into connection request modal!")

                            page.evaluate("""() => {
                                const btn = document.querySelector('button[aria-label*="Send invitation"], button:has-text("Send"), button[aria-label*="Send now"]');
                                if (btn) {
                                    btn.style.outline = '3px solid #10b981';
                                    btn.style.boxShadow = '0 0 16px #10b981';
                                }
                            }""")
                except Exception as ce:
                    log.warning("Could not fill connection note: %s", ce)

            # Keep browser alive for human review and click
            log.info("Assisted DM composer active on screen. Pausing for Deepak's review...")
            time.sleep(180) # Keep browser open for 3 minutes for review
            try:
                context.close()
            except Exception:
                pass

    import threading
    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    return {
        "status": "ok",
        "message": f"Assisted DM composer active for {first_name or 'connection'}! Message pre-typed and ready to Send.",
        "copied_to_clipboard": True
    }


def send_connect_via_api(profile_url: str, note: str | None = None) -> dict[str, Any]:
    """Send LinkedIn connection request directly via LinkedIn Voyager API in the background.

    Reads li_at and JSESSIONID from saved storage_state.json / session file.
    Resolves target member's urn:li:fsd_profile via Voyager profile API.
    Sends invitation POST to Voyager normInvitations endpoint.
    """
    import requests

    # Pre-flight cooldown check
    is_cooling, cool_reason = is_linkedin_cooldown_active()
    if is_cooling:
        log.warning("LinkedIn send_connect_via_api aborted: %s", cool_reason)
        return {"ok": False, "error": f"Circuit breaker active: {cool_reason}", "status": AUTH_EXPIRED_OR_CHALLENGED}

    cookies = get_stored_cookies()
    cookie_dict = {}
    for c in cookies:
        if isinstance(c, dict) and "name" in c and "value" in c:
            cookie_dict[c["name"]] = c["value"]

    li_at = cookie_dict.get("li_at")
    jsessionid = cookie_dict.get("JSESSIONID", "").strip('"').strip("'")

    if not li_at or not jsessionid:
        return {
            "ok": False,
            "error": "Missing li_at or JSESSIONID cookies. Please ensure LinkedIn session is active.",
            "method": "voyager_api",
        }

    clean_url = (profile_url or "").strip().rstrip("/")
    if not clean_url:
        return {"ok": False, "error": "No profile URL provided.", "method": "voyager_api"}

    # Extract member slug from profile_url (e.g. https://www.linkedin.com/in/username/ -> username)
    slug = clean_url.split("linkedin.com/in/")[-1].split("?")[0].split("/")[0].strip()
    if not slug:
        slug = clean_url.split("/")[-1].split("?")[0].strip()

    csrf_token = jsessionid

    headers = {
        "csrf-token": csrf_token,
        "x-restli-protocol-version": "2.0.0",
        "user-agent": config.APPLYPILOT_USER_AGENT,
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "x-li-lang": "en_US",
    }

    session = requests.Session()
    session.cookies.update(cookie_dict)

    # Step 1: Resolve target member's profile URN / entityUrn
    profile_api_url = f"https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={urllib.parse.quote(slug)}"
    try:
        resp = session.get(profile_api_url, headers=headers, timeout=12)
    except Exception as e:
        return {"ok": False, "error": f"Voyager profile lookup failed: {e}", "method": "voyager_api"}

    if resp.status_code != 200:
        if resp.status_code in (401, 403, 429):
            trigger_linkedin_circuit_breaker(f"Voyager profile lookup returned {resp.status_code}", trigger_url=profile_api_url)
            return {
                "ok": False,
                "error": f"Voyager profile lookup returned status {resp.status_code}: {resp.text[:200]}",
                "method": "voyager_api",
                "status": AUTH_EXPIRED_OR_CHALLENGED,
            }
        return {
            "ok": False,
            "error": f"Voyager profile lookup returned status {resp.status_code}: {resp.text[:200]}",
            "method": "voyager_api",
        }

    target_urn = ""
    try:
        prof_data = resp.json()
        # Look for urn:li:fsd_profile:... in entities or data
        if "elements" in prof_data and len(prof_data["elements"]) > 0:
            target_urn = prof_data["elements"][0].get("entityUrn", "")
        elif "*elements" in prof_data and len(prof_data["*elements"]) > 0:
            target_urn = prof_data["*elements"][0]
        else:
            # Recursive or text search for urn:li:fsd_profile
            raw_text = resp.text
            match = re.search(r'urn:li:fsd_profile:[a-zA-Z0-9_\-]+', raw_text)
            if match:
                target_urn = match.group(0)
    except Exception as e:
        return {"ok": False, "error": f"Failed parsing Voyager profile response: {e}", "method": "voyager_api"}

    if not target_urn:
        return {
            "ok": False,
            "error": f"Could not resolve urn:li:fsd_profile for slug '{slug}'",
            "method": "voyager_api",
        }

    # Step 2: Send connection invite
    invite_url = "https://www.linkedin.com/voyager/api/growth/normInvitations"
    payload: dict[str, Any] = {
        "invitee": {
            "inviteeUnion": {
                "memberProfile": target_urn
            }
        }
    }
    if note:
        payload["message"] = str(note)[:200]

    try:
        inv_resp = session.post(invite_url, json=payload, headers=headers, timeout=15)
    except Exception as e:
        return {"ok": False, "error": f"Voyager invite POST failed: {e}", "method": "voyager_api"}

    if inv_resp.status_code == 201:
        log.info("Successfully sent LinkedIn connection request via Voyager API to %s (%s)", slug, target_urn)
        return {"ok": True, "method": "voyager_api", "target_urn": target_urn}

    if inv_resp.status_code == 422 and "CANT_RESEND_YET" in inv_resp.text:
        log.info("Invitation to %s already pending or recently sent (CANT_RESEND_YET)", slug)
        return {"ok": True, "method": "voyager_api", "target_urn": target_urn, "note": "CANT_RESEND_YET"}

    if inv_resp.status_code in (401, 403, 429):
        trigger_linkedin_circuit_breaker(f"Voyager invite POST returned {inv_resp.status_code}", trigger_url=invite_url)
        return {
            "ok": False,
            "error": f"Voyager invitation POST returned {inv_resp.status_code}: {inv_resp.text[:250]}",
            "method": "voyager_api",
            "status_code": inv_resp.status_code,
            "status": AUTH_EXPIRED_OR_CHALLENGED,
        }

    return {
        "ok": False,
        "error": f"Voyager invitation POST returned {inv_resp.status_code}: {inv_resp.text[:250]}",
        "method": "voyager_api",
        "status_code": inv_resp.status_code
    }


MAX_DAILY_CONNECTS = 15


def get_daily_connect_count() -> int:
    """Return count of connection requests sent in the last 24 hours."""
    try:
        conn = get_connection()
        c = conn.cursor()
        since_time = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        row = c.execute(
            "SELECT COUNT(*) FROM referral_connection_requests WHERE requested_at >= ?",
            (since_time,)
        ).fetchone()
        return row[0] if row else 0
    except Exception as e:
        log.warning("Could not query daily connection count: %s", e)
        return 0


def send_connect_via_headless_browser(profile_url: str, note: str | None = None) -> dict[str, Any]:
    """Send LinkedIn connection request in the background using Playwright in headless mode.

    Loads session from isolated playwright_profile, navigates to profile,
    clicks Connect (or More -> Connect), adds note if provided, submits, and verifies
    Pending state.
    """
    # Safety check: Circuit breaker
    is_cooling, cool_reason = is_linkedin_cooldown_active()
    if is_cooling:
        log.warning("LinkedIn send_connect_via_headless_browser aborted: %s", cool_reason)
        return {"ok": False, "error": f"Circuit breaker active: {cool_reason}", "status": AUTH_EXPIRED_OR_CHALLENGED, "method": "headless_playwright"}

    clean_url = (profile_url or "").strip()
    if not clean_url:
        return {"ok": False, "error": "No profile URL provided.", "method": "headless_playwright"}
    if not clean_url.startswith("http"):
        clean_url = f"https://www.linkedin.com/in/{clean_url.lstrip('/')}"

    try:
        from applypilot.apply.chrome import open_isolated_context
        with open_isolated_context(headless=True) as context:
            page = context.new_page()
            response = page.goto(clean_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            status_code = response.status if response else None
            is_challenged, ch_reason = check_page_for_challenges_or_auth(page, status_code=status_code)
            if is_challenged:
                trigger_linkedin_circuit_breaker(f"send_connect_via_headless_browser: {ch_reason}", trigger_url=page.url)
                return {"ok": False, "error": ch_reason, "status": AUTH_EXPIRED_OR_CHALLENGED, "method": "headless_playwright"}

            # Check if already pending or connected
            page_text = page.evaluate("() => document.body.innerText || ''")
            if "Pending" in page_text and ("Withdraw" in page_text or "Invitation sent" in page_text):
                return {"ok": True, "method": "headless_playwright", "already_pending": True}

            # Locate Connect button
            connect_btn = page.query_selector("main button:has-text('Connect'), main a:has-text('Connect')")
            if not connect_btn:
                # Check More actions button (often aria-label="More" or has-text('More'))
                more_btn = page.query_selector("main button[aria-label='More'], main button[aria-label*='More actions'], main button:has-text('More')")
                if more_btn:
                    more_btn.click()
                    time.sleep(1.2)
                    connect_btn = page.query_selector("a:has-text('Connect'), div[role='button']:has-text('Connect'), button:has-text('Connect')")

            if not connect_btn:
                # If still not found, check if already Pending
                if page.query_selector("button:has-text('Pending'), span:has-text('Pending')"):
                    return {"ok": True, "method": "headless_playwright", "already_pending": True}
                return {"ok": False, "error": "Connect button not found on profile page.", "method": "headless_playwright"}

            connect_btn.click()
            time.sleep(1.5)

            if note:
                # Click 'Add a note'
                add_note_btn = page.query_selector("button:has-text('Add a note'), button[aria-label*='Add a note']")
                if add_note_btn:
                    add_note_btn.click()
                    time.sleep(1)

                textarea = page.query_selector("textarea#custom-message, textarea[name='message'], textarea")
                if textarea:
                    textarea.fill(str(note)[:200])
                    time.sleep(0.5)

                send_btn = page.query_selector(
                    "button[aria-label*='Send invitation'], button:has-text('Send invitation'), button:has-text('Send now'), button:has-text('Send')"
                )
                if send_btn:
                    send_btn.click()
                    time.sleep(2)
            else:
                # Send without note
                send_without_note = page.query_selector(
                    "button[aria-label*='Send without a note'], button:has-text('Send without a note'), button:has-text('Send now'), button:has-text('Send')"
                )
                if send_without_note:
                    send_without_note.click()
                    time.sleep(2)
                else:
                    # In case a simple modal appears with Send
                    gen_send = page.query_selector("button:has-text('Send')")
                    if gen_send:
                        gen_send.click()
                        time.sleep(2)

            # Verification: check if 'Pending' appears on page
            time.sleep(2)
            verified_pending = page.evaluate("""() => {
                const text = document.body.innerText || '';
                if (text.includes('Pending')) return true;
                const btns = Array.from(document.querySelectorAll('button, span, a'));
                return btns.some(b => b.innerText && b.innerText.trim() === 'Pending');
            }""")

            if verified_pending:
                log.info("Headless Playwright verified 'Pending' invitation for %s", clean_url)
                return {"ok": True, "method": "headless_playwright"}
            else:
                log.info("Headless Playwright completed submission for %s", clean_url)
                return {"ok": True, "method": "headless_playwright", "verified": False}

    except Exception as e:
        log.warning("Headless Playwright connection error for %s: %s", clean_url, e)
        return {"ok": False, "error": str(e), "method": "headless_playwright"}


def connect_in_background(profile_url: str, note: str | None = None) -> dict[str, Any]:
    """Attempt background connection request via Voyager API first, falling back to headless Playwright.

    Enforces:
    - 24-hour circuit breaker check
    - Strict daily pacing: max 15 automated connects/day
    - 20-60s random jitter before action execution
    - Strictly sequential execution
    - Never opens a visible browser window.
    """
    import random

    clean_url = (profile_url or "").strip()
    truncated_note = str(note)[:200] if note else None

    # Step 0: Check Circuit Breaker & Daily Pacing
    is_cooling, cool_reason = is_linkedin_cooldown_active()
    if is_cooling:
        log.warning("LinkedIn connect_in_background aborted: %s", cool_reason)
        return {
            "ok": False,
            "error": f"Circuit breaker active: {cool_reason}",
            "status": AUTH_EXPIRED_OR_CHALLENGED,
        }

    daily_count = get_daily_connect_count()
    if daily_count >= MAX_DAILY_CONNECTS:
        msg = f"Daily LinkedIn automated connection limit reached ({daily_count}/{MAX_DAILY_CONNECTS} in last 24h). Safety shield active."
        log.warning(msg)
        return {
            "ok": False,
            "error": msg,
            "status": "DAILY_LIMIT_REACHED",
            "daily_count": daily_count,
        }

    # Step 0.5: Random safety jitter (20 to 60 seconds)
    jitter_sec = random.uniform(20.0, 60.0)
    log.info("Pacing safety shield: sleeping %.1fs jitter before connect action...", jitter_sec)
    time.sleep(jitter_sec)

    # Step 1: Try Voyager API
    api_res = send_connect_via_api(clean_url, truncated_note)
    if api_res.get("ok"):
        return api_res

    log.info("Voyager API failed (%s); falling back to headless Playwright...", api_res.get("error"))

    # Step 2: Fallback to headless Playwright
    headless_res = send_connect_via_headless_browser(clean_url, truncated_note)
    if headless_res.get("ok"):
        return headless_res

    return {
        "ok": False,
        "error": f"API error: {api_res.get('error')} | Headless error: {headless_res.get('error')}",
        "api_result": api_res,
        "headless_result": headless_res
    }


def scan_linkedin_easy_apply_jobs(
    search_terms: list[str] | None = None,
    location: str = "Bengaluru, India",
    results_wanted: int = 15,
    hours_old: int = 72
) -> dict[str, Any]:
    """Scan LinkedIn for high-relevance Easy Apply openings and store them in SQLite."""
    import jobspy
    from jobspy import scrape_jobs

    if not search_terms:
        search_terms = ["backend engineer", "java backend", "golang engineer"]

    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    total_found = 0
    new_jobs = 0

    for term in search_terms:
        try:
            log.info("Scanning LinkedIn Easy Apply for query: '%s' in %s...", term, location)
            df = scrape_jobs(
                site_name=["linkedin"],
                search_term=term,
                location=location,
                results_wanted=results_wanted,
                easy_apply=True,
                hours_old=hours_old,
                verbose=0
            )
            if df is None or len(df) == 0:
                continue

            for _, r in df.iterrows():
                job_url = str(r.get("job_url", "")).strip()
                if not job_url or job_url == "nan":
                    continue
                total_found += 1
                title = str(r.get("title", "Backend Engineer"))
                company = str(r.get("company", "LinkedIn Employer"))

                # Skip blacklisted companies (Accenture, Infosys, Capgemini, Flexiple)
                is_excluded, exc_reason = is_company_excluded(company)
                if not is_excluded:
                    is_excluded, exc_reason = is_company_excluded(title)
                if is_excluded:
                    log.debug("Skipping excluded company role '%s' at '%s': %s", title, company, exc_reason)
                    continue

                # Check experience requirement (must be <= 3 YOE)
                desc = str(r.get("description", ""))
                is_over_exp, exp_reason = check_experience_exceeds(f"{title} {desc}", max_years=3)
                if is_over_exp:
                    log.debug("Skipping job requiring > 3 years experience (%s): '%s'", exp_reason, title)
                    continue

                loc = str(r.get("location", location))
                date_posted = str(r.get("date_posted", ""))
                apply_direct = str(r.get("job_url_direct", ""))

                try:
                    c.execute("""
                        INSERT INTO jobs 
                        (url, title, location, site, strategy, description, full_description, is_easy_apply, discovered_at, application_url, date_posted)
                        VALUES (?, ?, ?, ?, 'linkedin_easy_apply', ?, ?, 1, ?, ?, ?)
                    """, (job_url, title, loc, company, desc, desc, now, apply_direct or job_url, date_posted))
                    new_jobs += 1
                except sqlite3.IntegrityError:
                    c.execute("""
                        UPDATE jobs 
                        SET is_easy_apply = 1,
                            application_url = COALESCE(NULLIF(application_url, ''), ?)
                        WHERE url = ?
                    """, (job_url, job_url))
            conn.commit()
        except Exception as e:
            log.warning("LinkedIn Easy Apply scan error for '%s': %s", term, e)

    conn.commit()
    return {
        "status": "success",
        "total_scanned": total_found,
        "new_jobs_added": new_jobs,
        "message": f"Scanned {total_found} LinkedIn Easy Apply openings ({new_jobs} new added to database)!"
    }


def is_role_relevant_for_backend(title: str) -> tuple[bool, str]:
    """Strictly filter roles for 0-3 YOE Backend / Spring Boot / Java / Golang / Full Stack.
    
    Rejects:
      - Senior / Lead / Staff / Architect / EM / Director / VP / Principal / LMTS / PMTS / III / IV / V
      - Non-target disciplines: Frontend, UI/UX, Web Designer, Mobile (Android, iOS, Flutter, React Native),
        QA, SDET, Testing, DevOps, SRE, Data Engineer, Data Science, AI/ML, Salesforce, SAP, ServiceNow,
        Cyber/Security, Embedded, Firmware, Hardware, Intern, Trainee.
    Accepts:
      - Backend, Spring Boot, Java, Golang/Go, Full Stack, SDE, SDE-1, SDE-2, Software Engineer/Developer.
    """
    if not title or not title.strip():
        return False, "Empty title"
    
    t = title.lower().strip()
    
    # 1. Seniority exclusions (Deepak is 0-3 YOE, Meesho SDE-1)
    seniority_rejects = [
        r'\bsenior\b', r'\bsr\.?\b', r'\blead\b', r'\btech lead\b', r'\bteam lead\b',
        r'\bstaff\b', r'\bprincipal\b', r'\bmanager\b', r'\bmgr\b', r'\bdirector\b',
        r'\barchitect\b', r'\bhead\b', r'\bvp\b', r'\bvice president\b', r'\bdistinguished\b',
        r'\biii\b', r'\biv\b', r'\bv\b', r'\bl3\b', r'\bl4\b', r'\bl5\b', r'\bl6\b',
        r'\blmts\b', r'\bpmts\b', r'\bexpert\b', r'\bengineering manager\b', r'\bem\b',
        r'\b5-7\s*yrs\b', r'\b5\+\s*years\b', r'\b6\+\s*years\b', r'\b7\+\s*years\b', r'\bphd\b'
    ]
    for sr in seniority_rejects:
        if re.search(sr, t):
            return False, f"Seniority ({sr})"

    # 2. Domain / non-target exclusions (Frontend, Android, iOS, mobile, QA, devops, data, etc.)
    domain_rejects = [
        r'\bfront[- ]?end\b', r'\bui\b', r'\bux\b', r'\bweb designer\b',
        r'\bandroid\b', r'\bios\b', r'\bmobile\b', r'\bflutter\b', r'\breact native\b',
        r'\bdata engineer\b', r'\bdata scientist\b', r'\bmachine learning\b', r'\bml engineer\b',
        r'\bai engineer\b', r'\bai/ml\b', r'\baiml\b', r'\bcomputer vision\b', r'\bnlp\b',
        r'\balgorithm developer\b', r'\bqa\b', r'\bquality\b', r'\bsdet\b', r'\btest automation\b',
        r'\btest\b', r'\btesting\b', r'\bdevops\b', r'\bsre\b', r'\binfrastructure\b', r'\bsupport\b',
        r'\bit engineer\b', r'\bit technical\b', r'\bsalesforce\b', r'\bsap\b', r'\bservicenow\b',
        r'\bcyber\b', r'\bsecurity\b', r'\bcrm\b', r'\bintern\b', r'\binternship\b', r'\btrainee\b',
        r'\bgraduate\b', r'\bcollege\b', r'\bapprentice\b', r'\bembedded\b', r'\bfirmware\b',
        r'\bhardware\b', r'\bdevice driver\b', r'\bbluetooth\b', r'\baudio engineer\b',
        r'\bcamera\b', r'\bautomotive\b', r'\bflight dynamics\b', r'\btelecom\b', r'\b5g\b',
        r'\bblockchain\b', r'\bcontrol system\b', r'\bplc\b'
    ]
    for dr in domain_rejects:
        if re.search(dr, t):
            return False, f"Non-target domain ({dr})"

    # 3. Core target roles check (Backend, Spring Boot, Java, Golang, Full Stack, SDE)
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
    if not any(re.search(tr, t) for tr in target_roles):
        return False, "Not in target stack (Backend, Spring Boot, Java, Go, Full Stack, SDE)"

    return True, "OK"


def scan_linkedin_incognito_recent_jobs(
    hours_old: int = 4,
    location_geoid: str = "105126231",  # Bengaluru default
    keywords_list: list[str] | None = None,
    max_pages: int = 2,
    max_applicants: int = 200
) -> dict[str, Any]:
    """Scrape fresh LinkedIn jobs in incognito / guest mode without logging in across multiple search strings.

    Filters strictly for:
    - Posted in the last 4 hours (hours_old <= 4).
    - Under 200 applicants (< 200 applicants).
    - Targeted tech stacks: Backend, Spring Boot, Java, Golang, or Full Stack.
    - Excludes Frontend, Android, iOS, Mobile, QA, DevOps, Data Eng, etc.
    Saves and updates all discovered jobs into the main ApplyPilot tracker database.
    """
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright

    # Load search strings from searches.yaml if not provided
    if not keywords_list:
        try:
            from applypilot.config import load_search_config
            cfg = load_search_config()
            cfg_queries = [q.get("query") for q in cfg.get("queries", []) if q.get("query")]
            if cfg_queries:
                keywords_list = cfg_queries
        except Exception:
            pass

    if not keywords_list:
        keywords_list = [
            '("Software Engineer" OR "Backend Engineer") NOT Senior NOT Lead',
            '("Java Developer" OR "Spring Boot" OR "Golang Developer") NOT Senior NOT Lead',
            '("Full Stack Engineer" OR "Full Stack Developer") NOT Senior NOT Lead',
            '("SDE-1" OR "SDE 1" OR "Junior Backend")'
        ]

    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    total_found = 0
    new_jobs = 0
    seen_urls = set()

    seconds = max(1, hours_old) * 3600
    log.info("Starting LinkedIn Incognito scan for %d query strings (%d hours, seconds=%d)...", len(keywords_list), hours_old, seconds)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=config.DEFAULT_STEALTH_ARGS + ["--incognito"],
            )
            context = browser.new_context(
                user_agent=config.DEFAULT_DESKTOP_USER_AGENT,
                color_scheme="dark",
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()

            for kw_idx, raw_query in enumerate(keywords_list):
                query = raw_query.strip()
                if not any(rj in query.lower() for rj in ("not senior", "not lead")):
                    query = f'({query}) NOT Senior NOT Lead NOT Staff NOT Manager NOT Director'

                encoded_kw = urllib.parse.quote(query)
                base_search_url = (
                    f"https://www.linkedin.com/jobs/search/?keywords={encoded_kw}"
                    f"&geoId={location_geoid}&f_TPR=r{seconds}&f_JT=F&sortBy=DD"
                )

                log.info("[%d/%d] Scanning LinkedIn incognito for query: %s", kw_idx + 1, len(keywords_list), query)

                for page_idx in range(max_pages):
                    start = page_idx * 25
                    target_url = f"{base_search_url}&start={start}" if start > 0 else base_search_url

                    try:
                        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(2000)
                        for _ in range(2):
                            page.evaluate("window.scrollBy(0, 1000);")
                            page.wait_for_timeout(600)
                    except Exception as ex:
                        log.warning("Failed loading page %d for '%s': %s", page_idx + 1, query, ex)
                        break

                    soup = BeautifulSoup(page.content(), "html.parser")
                    cards = soup.find_all(class_="base-search-card")
                    if not cards:
                        cards = soup.find_all("div", {"data-entity-urn": True})
                    if not cards:
                        break

                    for card in cards:
                        try:
                            title_el = card.find(class_="base-search-card__title")
                            company_el = card.find(class_="base-search-card__subtitle")
                            loc_el = card.find(class_="job-search-card__location")
                            link_el = card.find("a", class_="base-card__full-link")
                            time_el = card.find("time")

                            if not link_el or not link_el.has_attr("href"):
                                continue

                            job_url = link_el["href"].split("?")[0].strip()
                            if not job_url or job_url in seen_urls:
                                continue
                            seen_urls.add(job_url)

                            title = title_el.text.strip() if title_el else "Software Engineer"
                            company = company_el.text.strip() if company_el else "LinkedIn Employer"
                            loc = loc_el.text.strip() if loc_el else "Bengaluru, India"
                            time_str = time_el.text.strip() if time_el else (time_el.get("datetime") if time_el else "")

                            # Skip blacklisted companies (Accenture, Infosys, Capgemini, Flexiple)
                            is_excluded, exc_reason = is_company_excluded(company)
                            if not is_excluded:
                                is_excluded, exc_reason = is_company_excluded(title)
                            if is_excluded:
                                log.debug("Skipping excluded company role '%s' at '%s': %s", title, company, exc_reason)
                                continue

                            # Strict Candidate Experience & Tech Stack Guardrails (Backend, Spring Boot, Java, Go, Full Stack)
                            role_ok, role_reason = is_role_relevant_for_backend(title)
                            if not role_ok:
                                log.debug("Skipping non-matching incognito job '%s': %s", title, role_reason)
                                continue

                            # Inspect applicant count or benefits badges on the card
                            card_text = card.get_text(separator=" ", strip=True).lower()
                            num_apps = None
                            if "over 200 applicants" in card_text or ">200 applicants" in card_text:
                                num_apps = 201
                            elif "be an early applicant" in card_text:
                                num_apps = 10
                            else:
                                app_match = re.search(r'(\d+)\s+applicants?', card_text)
                                if app_match:
                                    num_apps = int(app_match.group(1))

                            # Filter out jobs with >= 200 applicants
                            if num_apps is not None and num_apps >= max_applicants:
                                log.debug("Skipping high applicant job '%s' (%d applicants >= %d)", title, num_apps, max_applicants)
                                continue

                            # Check experience requirement on card text if stated (must strictly be <= 3 years)
                            is_over_exp, exp_reason = check_experience_exceeds(card_text, max_years=3)
                            if is_over_exp:
                                log.debug("Skipping job requiring > 3 years experience (%s): '%s'", exp_reason, title)
                                continue

                            total_found += 1

                            # Calculate precise estimated date_posted using relative time_str if available
                            date_posted = ""
                            calc_dt = datetime.now(timezone.utc)
                            t_lower = (time_str or "").lower()
                            m_match = re.search(r"(\d+)\s*m(?:in)?s?", t_lower)
                            h_match = re.search(r"(\d+)\s*h(?:our)?s?", t_lower)
                            d_match = re.search(r"(\d+)\s*d(?:ay)?s?", t_lower)
                            if m_match:
                                calc_dt -= timedelta(minutes=int(m_match.group(1)))
                                date_posted = calc_dt.isoformat()
                            elif h_match:
                                calc_dt -= timedelta(hours=int(h_match.group(1)))
                                date_posted = calc_dt.isoformat()
                            elif d_match:
                                calc_dt -= timedelta(days=int(d_match.group(1)))
                                date_posted = calc_dt.isoformat()
                            elif time_el and time_el.has_attr("datetime"):
                                date_posted = str(time_el["datetime"])
                            else:
                                date_posted = now

                            desc = f"{title} at {company} in {loc}. Posted recently ({time_str})."

                            try:
                                c.execute("""
                                    INSERT INTO jobs 
                                    (url, title, location, site, strategy, description, full_description, discovered_at, application_url, date_posted, num_applicants)
                                    VALUES (?, ?, ?, ?, 'linkedin_1h_incognito', ?, ?, ?, ?, ?, ?)
                                """, (job_url, title, loc, company, desc, desc, now, job_url, date_posted, num_apps))
                                new_jobs += 1
                            except sqlite3.IntegrityError:
                                c.execute("""
                                    UPDATE jobs 
                                    SET strategy = COALESCE(strategy, 'linkedin_1h_incognito'),
                                        date_posted = COALESCE(date_posted, ?),
                                        num_applicants = COALESCE(?, num_applicants)
                                    WHERE url = ?
                                """, (date_posted, num_apps, job_url))
                        except Exception as card_err:
                            log.debug("Error processing card: %s", card_err)

                    conn.commit()

            browser.close()
    except Exception as e:
        log.error("LinkedIn Incognito scan failed: %s", e)
        return {
            "status": "error",
            "message": f"Scan error: {e}",
            "total_scanned": total_found,
            "new_jobs_added": new_jobs
        }

    conn.commit()
    return {
        "status": "success",
        "total_scanned": total_found,
        "new_jobs_added": new_jobs,
        "message": f"Scanned {total_found} recent LinkedIn incognito jobs across queries ({new_jobs} brand new added to tracker)!"
    }

