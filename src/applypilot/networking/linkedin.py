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
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.apply.assistant import BRAVE_PROFILE_DIR, get_browser_executable
from applypilot.config import APP_DIR, load_profile
from applypilot.database import get_connection

log = logging.getLogger(__name__)

SESSION_FILE = APP_DIR / "linkedin_session.json"
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")


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
    """Retrieve stored LinkedIn cookies."""
    if not SESSION_FILE.exists():
        return []
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data.get("cookies", [])
    except Exception:
        return []


def save_stored_cookies(cookies: list[dict], user_info: dict | None = None) -> None:
    """Save LinkedIn cookies and metadata to disk."""
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "user_info": user_info or {},
        "cookies": cookies
    }
    SESSION_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("Saved %d LinkedIn cookies to %s", len(cookies), SESSION_FILE)


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
    """Launch Brave browser for Deepak to log in to LinkedIn or verify active session."""
    from playwright.sync_api import sync_playwright

    exe_path, browser_type = get_browser_executable()
    BRAVE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Launching browser (%s) for LinkedIn authentication...", browser_type)

    with sync_playwright() as p:
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BRAVE_PROFILE_DIR.resolve()),
            executable_path=exe_path if exe_path else None,
            headless=not headed,
            args=launch_args,
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

    exe_path, _ = get_browser_executable()
    BRAVE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    encoded_kw = urllib.parse.quote(keywords)
    search_url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_kw}&sortBy=%22date_posted%22"

    results = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BRAVE_PROFILE_DIR.resolve()),
            executable_path=exe_path if exe_path else None,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

        existing_cookies = get_stored_cookies()
        if existing_cookies:
            try:
                context.add_cookies(existing_cookies)
            except Exception:
                pass

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(search_url, wait_until="domcontentloaded")
        time.sleep(4)

        # Check if redirected to login
        if "login" in page.url:
            log.warning("LinkedIn session expired or not authenticated.")
            context.close()
            return [{"error": "Not authenticated. Run 'applypilot linkedin login' first."}]

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

                # Extract post URL
                link_el = post_el.query_selector("a[href*='/feed/update/'], a[href*='urn:li:activity']")
                post_url = link_el.get_attribute("href") if link_el else ""
                if post_url and not post_url.startswith("http"):
                    post_url = f"https://www.linkedin.com{post_url}"

                # Extract emails
                emails = EMAIL_REGEX.findall(text_content)
                recruiter_email = emails[0] if emails else ""

                # Infer company from headline or text
                company = "Tech Company"
                comp_match = re.search(r"(?:at|@|join|hiring\s+for)\s+([A-Z][A-Za-z0-9]{2,20})\b", text_content)
                if comp_match:
                    company = comp_match.group(1)

                item = {
                    "author": author_name,
                    "headline": headline,
                    "company": company,
                    "post_text": text_content[:400] + ("..." if len(text_content) > 400 else ""),
                    "full_text": text_content,
                    "post_url": post_url or search_url,
                    "recruiter_email": recruiter_email,
                    "discovered_at": datetime.now(timezone.utc).isoformat()
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
    """Search LinkedIn for RVCE alumni or engineering connections at a target company."""
    from playwright.sync_api import sync_playwright

    exe_path, _ = get_browser_executable()
    BRAVE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    query = f"{company} {role} {school}".strip()
    encoded_query = urllib.parse.quote(query)
    search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_query}"

    results = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BRAVE_PROFILE_DIR.resolve()),
            executable_path=exe_path if exe_path else None,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

        existing_cookies = get_stored_cookies()
        if existing_cookies:
            try:
                context.add_cookies(existing_cookies)
            except Exception:
                pass

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(search_url, wait_until="domcontentloaded")
        time.sleep(4)

        if "login" in page.url:
            context.close()
            return [{"error": "Not authenticated. Run 'applypilot linkedin login' first."}]

        # Extract people cards
        people_elements = page.query_selector_all("li.reusable-search__result-container, div.entity-result")

        for el in people_elements[:max_results]:
            try:
                name_el = el.query_selector("span.entity-result__title-text a, a.app-aware-link")
                name = name_el.inner_text().strip() if name_el else "LinkedIn Member"
                profile_url = name_el.get_attribute("href") if name_el else ""

                if profile_url and "?" in profile_url:
                    profile_url = profile_url.split("?")[0]

                headline_el = el.query_selector("div.entity-result__primary-subtitle")
                headline = headline_el.inner_text().strip() if headline_el else ""

                location_el = el.query_selector("div.entity-result__secondary-subtitle")
                location = location_el.inner_text().strip() if location_el else "India"

                results.append({
                    "name": name,
                    "headline": headline,
                    "location": location,
                    "profile_url": profile_url,
                    "company": company,
                    "school": school,
                    "search_url": search_url
                })
            except Exception as ee:
                log.debug("Error parsing person card: %s", ee)

        context.close()

    return results


def _save_lead_to_db(lead: dict) -> None:
    """Store discovered LinkedIn post hiring lead in ApplyPilot DB."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    url = lead.get("post_url") or f"https://www.linkedin.com/feed/update/{int(time.time())}"
    title = f"Backend Engineer (via {lead.get('author', 'Recruiter')})"
    company = lead.get("company", "Tech Company")
    recruiter_email = lead.get("recruiter_email", "")

    c.execute("""
        INSERT OR IGNORE INTO jobs
        (url, title, location, site, strategy, description, full_description, recruiter_email, discovered_at, application_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        url
    ))
    conn.commit()


def compose_referral_dm(
    profile_url: str,
    company: str = "",
    role_title: str = "Backend Engineer",
    name: str = "",
    custom_message: str = "",
    template_type: str = "referral",
    headed: bool = True
) -> dict[str, Any]:
    """Launch Brave, open connection profile/chat, and auto-type personalized referral message.

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
            f"Hope you're doing well! I'm a fellow RVCE CSE graduate (Class of '25), currently working as an SDE-I at Meesho.\n\n"
            f"I saw that you're working at {comp_label} and noticed the {role_title} opening. Given my production experience building and scaling distributed backend systems with Go, Java 17, Apache Kafka, and Redis, I would be grateful for an employee referral.\n\n"
            f"Would you be open to referring me? Happy to share my tailored resume and requisition details!\n\n"
            f"Best regards,\nDeepak S H\nhttps://www.linkedin.com/in/deepak-s-h-82b772254"
        )
        short_note = f"Hi {first_name or 'there'}, fellow RVCE CSE '25 alum here! Currently SDE-1 at Meesho (Go/Java/Kafka). Saw the {role_title} opening at {comp_label} and would love to connect for a referral!"[:295]
    else:
        body_msg = (
            f"{first_name_salutation}\n\n"
            f"Hope you're having a great week! I'm an SDE-I Backend Engineer at Meesho (RVCE CSE '25) with production experience scaling high-throughput microservices in Go, Java 17, Apache Kafka, and Redis.\n\n"
            f"I noticed the {role_title} opening at {comp_label} and feel my background aligns well with the team's requirements. Could you kindly consider referring me for this position?\n\n"
            f"Happy to share my resume and requisition details. Thank you so much for your time!\n\n"
            f"Best regards,\nDeepak S H\nhttps://www.linkedin.com/in/deepak-s-h-82b772254"
        )
        short_note = f"Hi {first_name or 'there'}, I'm an SDE-1 Backend Engineer at Meesho (Go/Java/Kafka). Noticed the {role_title} role at {comp_label} and would love to connect to explore a referral!"[:295]

    # Also copy to clipboard so user has it immediately
    try:
        import subprocess
        subprocess.run(["powershell", "-Command", f"Set-Clipboard -Value @'\n{body_msg}\n'@"], check=False)
    except Exception:
        pass

    exe_path, _ = get_browser_executable()
    BRAVE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Composing LinkedIn referral DM for: %s", clean_url)

    def _worker():
        with sync_playwright() as p:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(BRAVE_PROFILE_DIR.resolve()),
                executable_path=exe_path if exe_path else None,
                headless=not headed,
                args=launch_args,
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

            # Check if name is detectable on page
            nonlocal first_name
            if not first_name:
                h1 = page.query_selector("h1")
                if h1:
                    raw_title = h1.inner_text().strip()
                    if raw_title:
                        first_name = raw_title.split()[0]

            # Try clicking Message button (for 1st-degree connections)
            msg_btn = page.query_selector("button:has-text('Message'), a:has-text('Message'), button[aria-label*='Message']")
            typed = False

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

            # If not typed via Message button, try "Connect" -> "Add a note"
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
        "message": f"Assisted DM composer active in Brave for {first_name or 'connection'}! Message pre-typed and ready to Send.",
        "copied_to_clipboard": True
    }
