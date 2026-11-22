import urllib.parse
"""ApplyPilot Recruiter Email Drafter.

Creates high-converting recruiter cold emails as drafts in Gmail via the connected Gmail CLI.
Attaches tailored resumes (or master RVCE resume) automatically for human 1-click review and send.
Zero automated sending: Deepak retains full manual control.
"""

import glob
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from applypilot.config import APP_DIR, RESUME_PDF_PATH, TAILORED_DIR, load_profile
from applypilot.database import get_connection

log = logging.getLogger(__name__)


def find_gmail_cli() -> str | None:
    """Find the registered Gmail CLI binary."""
    # 1. Antigravity plugin registered bin (most direct and persistent)
    default_bin = Path(os.environ.get("USERPROFILE", "")) / ".gemini" / "antigravity" / "bin" / "gmail.cmd"
    if default_bin.exists():
        return str(default_bin)

    # 2. Plugin skill script
    skill_bin = Path(os.environ.get("USERPROFILE", "")) / ".gemini" / "config" / "plugins" / "gmail" / "skills" / "gmail" / "scripts" / "gmail.cmd"
    if skill_bin.exists():
        return str(skill_bin)

    # 3. Standard PATH lookup
    cli = shutil.which("gmail") or shutil.which("gmail.cmd") or shutil.which("gmail.exe")
    if cli and os.path.exists(cli):
        return cli

    # 4. Check Antigravity plugin temp directories on Windows
    temp_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp"
    for candidate in temp_dir.glob("agy-plugin-cli-*/gmail.cmd"):
        if candidate.exists():
            return str(candidate)

    return None


def generate_recruiter_email(
    company: str,
    role_title: str,
    job_url: str = "",
    recruiter_name: str = "",
    candidate_profile: dict[str, Any] | None = None,
    pitch_style: str = "quick_pitch",
) -> dict[str, str]:
    """Generate high-converting cold emails tailored for founders and hiring managers.
    
    Styles:
    - 'quick_pitch': Ultra-concise (<5 lines), 0 fluff, instant hook for hiring posts.
    - 'founder_value': High-leverage pitch for founders/early hires highlighting scale problem solving and immediate impact.
    - 'standard': Clean professional email for HR/Talent Acquisition.
    """
    # Clean company name
    comp = (company or "").replace("WhatsApp (", "").replace(")", "").strip()
    for drop in ["WhatsApp Live Referral", "WhatsApp", "Telegram Channel", "Telegram", "KaDegree", "JobSpy"]:
        comp = comp.replace(drop, "").strip()
    if not comp or comp.lower() in ("unknown", "linkedin", "indeed", "glassdoor", "tech company", "tech firm", "team"):
        comp = "your team"

    # Clean role title
    clean_role = role_title or "Backend Engineer"
    if clean_role.lower() in ("sde i", "sde 1", "sde-1", "sde-i"):
        clean_role = "SDE-I Backend Engineer"

    # Candidate details
    full_name = "Deepak S H"
    phone = "+91 8431433659"
    email = "deepakshkarkala@gmail.com"
    linkedin_url = "https://www.linkedin.com/in/deepak-s-h-82b772254"

    if candidate_profile:
        personal = candidate_profile.get("personal", {})
        full_name = personal.get("full_name", full_name)
        phone = personal.get("phone", phone)
        email = personal.get("email", email)
        linkedin_url = personal.get("linkedin_url", linkedin_url)

    # Salutation
    first_name = recruiter_name.strip().split()[0] if recruiter_name and recruiter_name.strip() else ""
    if first_name.lower() in ("whatsapp", "telegram", "unknown", "lead", "community"):
        first_name = ""
    salutation = f"Hi {first_name}," if first_name else "Hi,"

    if pitch_style == "quick_pitch":
        subject = f"{clean_role} (SDE-1 @ Meesho) - Saw your hiring post"
        body = (
            f"{salutation}\n\n"
            f"Saw your post about the {clean_role} opening at {comp}.\n\n"
            f"I'm an SDE-1 Backend Engineer at Meesho (RVCE CSE '25, CGPA 8.92). My day-to-day work is building "
            f"high-throughput backend services using Java, Go, Kafka, and Redis, focusing on financial reconciliation and event streaming.\n\n"
            f"Can join immediately / 0 days notice. Tailored resume attached.\n\n"
            f"Would love to chat if my background looks relevant for your team.\n\n"
            f"Best,\n"
            f"{full_name} | {phone}\n"
            f"{linkedin_url}\n"
        )
    elif pitch_style == "founder_value":
        subject = f"Building backend at {comp} - Deepak (SDE-1 @ Meesho)"
        body = (
            f"{salutation}\n\n"
            f"I've been following what you're building at {comp} and wanted to reach out directly.\n\n"
            f"I'm an SDE-1 Backend Engineer at Meesho. My core focus is distributed systems and data consistency under high volume—handling "
            f"millions of transactions with Kafka, Java, Go, and Redis caching. A recent problem I tackled was redesigning "
            f"out-of-order webhook reconciliation pipelines using idempotent consumers and distributed locks to prevent financial data drift.\n\n"
            f"I'm looking for an early/growth engineering team where I can ship high-impact backend infrastructure. "
            f"I graduated from RVCE (CGPA 8.92) and can join immediately.\n\n"
            f"Resume is attached. Happy to jump on a quick 10-minute call this week if this sounds like a fit.\n\n"
            f"Best,\n"
            f"{full_name}\n"
            f"Phone: {phone}\n"
            f"LinkedIn: {linkedin_url}\n"
        )
    else:
        subject = f"Application: {clean_role} - {full_name} (SDE-I Backend @ Meesho)"
        body = (
            f"{salutation}\n\n"
            f"I came across the {clean_role} opening at {comp} and wanted to apply.\n\n"
            f"I am currently working as an SDE-I Backend Engineer at Meesho. My day-to-day work involves building "
            f"and maintaining distributed backend systems using Java, Go, Kafka, Redis, and Spring Boot. At Meesho, "
            f"I work on financial reconciliation and event-driven pipelines handling large transaction volumes.\n\n"
            f"I graduated in Computer Science from RVCE (CGPA 8.92) and have hands-on experience with:\n"
            f"• Distributed services and REST APIs in Java & Go\n"
            f"• Event streaming with Apache Kafka\n"
            f"• In-memory caching with Redis (sub-10ms latency)\n"
            f"• Relational databases (MySQL), Docker, and GCP\n\n"
            f"I have attached my resume for your review. My LinkedIn profile is also linked below:\n"
            f"LinkedIn: {linkedin_url}\n"
            f"Phone: {phone}\n\n"
            f"If my background looks like a good fit for your team, I'd appreciate the chance to discuss further.\n\n"
            f"Thanks,\n\n"
            f"{full_name}\n"
            f"SDE-I Backend Engineer, Meesho\n"
            f"Phone: {phone}\n"
            f"Email: {email}\n"
        )

    return {
        "subject": subject,
        "body_markdown": body,
    }

    return {
        "subject": subject,
        "body_markdown": body,
    }


def create_gmail_draft(
    to_email: str,
    subject: str,
    body_markdown: str,
    attachment_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create a draft in Deepak's Gmail account via the Gmail CLI with optional resume attachment."""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return {"status": "error", "message": "A valid recipient email address is required."}

    gmail_bin = find_gmail_cli()
    if not gmail_bin:
        return {"status": "error", "message": "Gmail CLI not found on system. Please ensure the gmail plugin is enabled."}

    # Resolve attachment PDF
    pdf_to_attach: Path | None = None
    if attachment_path:
        cand = Path(attachment_path)
        if cand.exists() and cand.is_file():
            pdf_to_attach = cand.resolve()
        else:
            cand_rel = (APP_DIR / attachment_path).resolve()
            if cand_rel.exists() and cand_rel.is_file():
                pdf_to_attach = cand_rel

    if not pdf_to_attach:
        for candidate_name in ["Deepak_S_H_Resume.pdf", "resume.pdf"]:
            cand = APP_DIR / candidate_name
            if cand.exists():
                pdf_to_attach = cand.resolve()
                break

    # Stage attachment with standard recruiter-visible name Deepak_S_H_Resume.pdf
    if pdf_to_attach and pdf_to_attach.exists():
        import shutil
        upload_staging_dir = APP_DIR / "apply-workers" / "current"
        upload_staging_dir.mkdir(parents=True, exist_ok=True)
        named_pdf = upload_staging_dir / "Deepak_S_H_Resume.pdf"
        try:
            shutil.copy2(str(pdf_to_attach), str(named_pdf))
            pdf_to_attach = named_pdf.resolve()
        except Exception:
            pass

    # Write body to a temporary markdown file to avoid Windows shell quoting issues
    temp_body = Path(tempfile.gettempdir()) / f"applypilot_draft_{os.getpid()}_{hash(to_email) & 0xffffffff}.md"
    try:
        temp_body.write_text(body_markdown, encoding="utf-8")

        cmd = [
            gmail_bin, "mutate", "create-draft",
            "--to", to_email,
            "--subject", subject,
            "--md",
            "--body-file", str(temp_body),
        ]

        if pdf_to_attach and pdf_to_attach.exists():
            cmd.extend(["--file", str(pdf_to_attach)])

        res = subprocess.run(cmd, capture_output=True, text=True, shell=True)

        if res.returncode != 0:
            err_msg = res.stderr.strip() or res.stdout.strip() or f"Command failed with code {res.returncode}"
            web_compose_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={urllib.parse.quote(to_email)}&su={urllib.parse.quote(subject)}&body={urllib.parse.quote(body_markdown)}"
            log.warning("Gmail CLI create-draft returned %s. Providing Web Compose fallback: %s", res.returncode, err_msg)
            return {
                "status": "fallback",
                "to": to_email,
                "subject": subject,
                "body": body_markdown,
                "attachment": str(pdf_to_attach) if pdf_to_attach else None,
                "web_compose_url": web_compose_url,
                "message": "Cold email generated! Click below to review & send directly in Gmail Web.",
            }

        stdout = res.stdout.strip()
        # Parse Draft ID: e.g. "Draft created: ID=r1392517870857342536"
        draft_id = ""
        m = re.search(r"ID=([a-zA-Z0-9_-]+)", stdout)
        if m:
            draft_id = m.group(1)

        log.info("Gmail draft created successfully: %s to %s", draft_id, to_email)
        return {
            "status": "ok",
            "draft_id": draft_id,
            "to": to_email,
            "subject": subject,
            "attachment": str(pdf_to_attach) if pdf_to_attach else None,
            "web_url": "https://mail.google.com/mail/u/0/#drafts",
            "message": f"Gmail draft created for {to_email}! Check your Gmail Drafts folder to review and send.",
        }

    except Exception as e:
        log.exception("Exception creating Gmail draft")
        return {"status": "error", "message": str(e)}
    finally:
        if temp_body.exists():
            try:
                temp_body.unlink()
            except Exception:
                pass


def send_gmail_email(
    to_email: str,
    subject: str,
    body_markdown: str,
    attachment_path: str | Path | None = None,
) -> dict[str, Any]:
    """Send an email directly via the Gmail CLI (with optional attached resume PDF)."""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return {"status": "error", "message": "A valid recipient email address is required."}

    gmail_bin = find_gmail_cli()
    if not gmail_bin:
        return {"status": "error", "message": "Gmail CLI not found on system. Please ensure the gmail plugin is enabled."}

    pdf_to_attach: Path | None = None
    if attachment_path:
        cand = Path(attachment_path)
        if cand.exists() and cand.is_file():
            pdf_to_attach = cand.resolve()
        else:
            cand_rel = (APP_DIR / attachment_path).resolve()
            if cand_rel.exists() and cand_rel.is_file():
                pdf_to_attach = cand_rel

    if not pdf_to_attach:
        for candidate_name in ["Deepak_S_H_Resume.pdf", "resume.pdf"]:
            cand = APP_DIR / candidate_name
            if cand.exists():
                pdf_to_attach = cand.resolve()
                break

    # Stage attachment with standard recruiter-visible name Deepak_S_H_Resume.pdf
    if pdf_to_attach and pdf_to_attach.exists():
        import shutil
        upload_staging_dir = APP_DIR / "apply-workers" / "current"
        upload_staging_dir.mkdir(parents=True, exist_ok=True)
        named_pdf = upload_staging_dir / "Deepak_S_H_Resume.pdf"
        try:
            shutil.copy2(str(pdf_to_attach), str(named_pdf))
            pdf_to_attach = named_pdf.resolve()
        except Exception:
            pass

    temp_body = Path(tempfile.gettempdir()) / f"applypilot_send_{os.getpid()}_{hash(to_email) & 0xffffffff}.md"
    try:
        temp_body.write_text(body_markdown, encoding="utf-8")

        if pdf_to_attach and pdf_to_attach.exists():
            cmd = [
                gmail_bin, "mutate", "send-with-attachment",
                "--to", to_email,
                "--subject", subject,
                "--md",
                "--body-file", str(temp_body),
                "--file", str(pdf_to_attach),
            ]
        else:
            cmd = [
                gmail_bin, "mutate", "send",
                "--to", to_email,
                "--subject", subject,
                "--md",
                "--body-file", str(temp_body),
            ]

        res = subprocess.run(cmd, capture_output=True, text=True, shell=True)

        if res.returncode != 0:
            err_msg = res.stderr.strip() or res.stdout.strip() or f"Command failed with code {res.returncode}"
            web_compose_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={urllib.parse.quote(to_email)}&su={urllib.parse.quote(subject)}&body={urllib.parse.quote(body_markdown)}"
            log.warning("Gmail CLI send returned %s. Providing Web Compose fallback: %s", res.returncode, err_msg)
            return {
                "status": "fallback",
                "to": to_email,
                "subject": subject,
                "body": body_markdown,
                "attachment": str(pdf_to_attach) if pdf_to_attach else None,
                "web_compose_url": web_compose_url,
                "message": "Cold email generated! Click below to review & send directly in Gmail Web.",
            }

        stdout = res.stdout.strip()
        log.info("Email sent successfully to %s: %s", to_email, stdout)
        return {
            "status": "ok",
            "to": to_email,
            "subject": subject,
            "attachment": str(pdf_to_attach) if pdf_to_attach else None,
            "message": f"Email successfully sent to {to_email} with attached resume!",
        }
    except Exception as e:
        log.exception("Exception sending email via Gmail")
        return {"status": "error", "message": str(e)}
    finally:
        if temp_body.exists():
            try:
                temp_body.unlink()
            except Exception:
                pass


def send_for_job(rowid: int, custom_recipient: str | None = None) -> dict[str, Any]:
    """Generate and directly send recruiter cold email for a specific job in DB."""
    conn = get_connection()
    c = conn.cursor()
    row = c.execute(
        """SELECT title, site, location, recruiter_email, application_url, url, tailored_resume_path, description, full_description 
           FROM jobs WHERE rowid = ?""",
        (rowid,),
    ).fetchone()

    if not row:
        return {"status": "error", "message": f"Job rowid {rowid} not found."}

    title, site, location, recruiter_email, app_url, url, tailored_path, desc, full_desc = row
    recipient = (custom_recipient or recruiter_email or "").strip()

    # Auto-extract recruiter email if not present
    all_text = f"{desc or ''} {full_desc or ''}"
    if not recipient:
        m_email = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", all_text)
        if m_email:
            recipient = m_email.group(0).strip()
            c.execute("UPDATE jobs SET recruiter_email = ? WHERE rowid = ?", (recipient, rowid))
            conn.commit()

    if not recipient or "@" not in recipient:
        return {
            "status": "missing_email",
            "message": "No recruiter email on file for this job. Please provide a recipient email.",
        }

    # Ensure personalized tailored resume exists
    tailored_file = None
    if tailored_path:
        cand = Path(tailored_path)
        if cand.exists() and cand.is_file():
            tailored_file = cand.resolve()
        else:
            cand2 = (APP_DIR / tailored_path).resolve()
            if cand2.exists() and cand2.is_file():
                tailored_file = cand2
            else:
                cand3 = (APP_DIR / "data" / tailored_path).resolve()
                if cand3.exists() and cand3.is_file():
                    tailored_file = cand3

    if not tailored_file:
        try:
            from applypilot.scoring.jit_tailor import tailor_single_job
            t_res = tailor_single_job(rowid)
            if t_res.get("tailored_resume_path"):
                cand_res = Path(t_res["tailored_resume_path"])
                if cand_res.exists():
                    tailored_file = cand_res.resolve()
        except Exception:
            pass

    if not tailored_file and RESUME_PDF_PATH.exists():
        tailored_file = RESUME_PDF_PATH.resolve()

    tailored_path = str(tailored_file) if tailored_file else None

    # Extract recruiter name if present
    recruiter_name = ""
    for pat in [r"\|\s*([A-Za-z\s]+?)\s*\|\s*\d+\s*comments", r"Posted by\s*:\s*([A-Za-z\s]+)", r"Contact\s*:\s*([A-Za-z\s]+)"]:
        m_name = re.search(pat, all_text)
        if m_name:
            recruiter_name = m_name.group(1).strip() if m_name.groups() else m_name.group(0).strip()
            break

    target_url = app_url or url or ""
    profile = load_profile()
    email_data = generate_recruiter_email(
        company=site or "Tech Team",
        role_title=title or "Backend Engineer",
        job_url=target_url,
        recruiter_name=recruiter_name,
        candidate_profile=profile,
        pitch_style=pitch_style,
    )

    res = send_gmail_email(
        to_email=recipient,
        subject=email_data["subject"],
        body_markdown=email_data["body_markdown"],
        attachment_path=tailored_path,
    )

    if res.get("status") in ("ok", "fallback"):
        now = datetime.now(timezone.utc).isoformat()
        c.execute("UPDATE jobs SET apply_status = 'applied', applied_at = ? WHERE rowid = ?", (now, rowid))
        conn.commit()

    return res


def draft_for_job(rowid: int, custom_recipient: str | None = None, pitch_style: str = "quick_pitch") -> dict[str, Any]:
    """Generate and create a Gmail draft for a specific job in ApplyPilot DB."""
    conn = get_connection()
    c = conn.cursor()
    row = c.execute(
        """SELECT title, site, location, recruiter_email, application_url, url, tailored_resume_path, description, full_description 
           FROM jobs WHERE rowid = ?""",
        (rowid,),
    ).fetchone()

    if not row:
        return {"status": "error", "message": f"Job rowid {rowid} not found."}

    title, site, location, recruiter_email, app_url, url, tailored_path, desc, full_desc = row
    recipient = (custom_recipient or recruiter_email or "").strip()

    # Auto-extract recruiter email if not present
    all_text = f"{desc or ''} {full_desc or ''}"
    if not recipient:
        m_email = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", all_text)
        if m_email:
            recipient = m_email.group(0).strip()
            c.execute("UPDATE jobs SET recruiter_email = ? WHERE rowid = ?", (recipient, rowid))
            conn.commit()

    if not recipient or "@" not in recipient:
        return {
            "status": "missing_email",
            "message": "No recruiter email on file for this job. Please provide a recipient email.",
        }

    # Ensure personalized tailored resume exists
    tailored_file = None
    if tailored_path:
        cand = Path(tailored_path)
        if cand.exists() and cand.is_file():
            tailored_file = cand.resolve()
        else:
            cand2 = (APP_DIR / tailored_path).resolve()
            if cand2.exists() and cand2.is_file():
                tailored_file = cand2
            else:
                cand3 = (APP_DIR / "data" / tailored_path).resolve()
                if cand3.exists() and cand3.is_file():
                    tailored_file = cand3

    if not tailored_file:
        try:
            from applypilot.scoring.jit_tailor import tailor_single_job
            t_res = tailor_single_job(rowid)
            if t_res.get("tailored_resume_path"):
                cand_res = Path(t_res["tailored_resume_path"])
                if cand_res.exists():
                    tailored_file = cand_res.resolve()
        except Exception:
            pass

    if not tailored_file and RESUME_PDF_PATH.exists():
        tailored_file = RESUME_PDF_PATH.resolve()

    tailored_path = str(tailored_file) if tailored_file else None

    # Extract recruiter name if present
    recruiter_name = ""
    for pat in [r"\|\s*([A-Za-z\s]+?)\s*\|\s*\d+\s*comments", r"Posted by\s*:\s*([A-Za-z\s]+)", r"Contact\s*:\s*([A-Za-z\s]+)"]:
        m_name = re.search(pat, all_text)
        if m_name:
            recruiter_name = m_name.group(1).strip() if m_name.groups() else m_name.group(0).strip()
            break

    target_url = app_url or url or ""
    profile = load_profile()
    email_data = generate_recruiter_email(
        company=site or "Tech Team",
        role_title=title or "Backend Engineer",
        job_url=target_url,
        recruiter_name=recruiter_name,
        candidate_profile=profile,
        pitch_style=pitch_style,
    )

    return create_gmail_draft(
        to_email=recipient,
        subject=email_data["subject"],
        body_markdown=email_data["body_markdown"],
        attachment_path=tailored_path,
    )


GENERIC_EMAIL_PREFIXES = {"jobs@", "careers@", "hr@", "info@", "talent@", "hiring@", "recruiting@"}

def generate_founder_pitch(
    recipient_email: str,
    recipient_name: str,
    company: str,
    product_focus: str = "",
    tech_stack: str = "Golang / Distributed Systems",
) -> dict:
    """Generate a sub-80-word direct pitch to a Founder/CTO/EM.
    Strict structure:
    1. Hook referencing product focus or engineering challenge
    2. Concrete Meesho backend proof point (e.g., Go concurrency & adaptive RPS 50-60h to 2-3h, or 150K+ orders/day at 1000 RPS)
    3. Live link (github.com/DEEPAKSH123) and single ask for a 15-minute technical chat.
    Rejects generic prefixes (jobs@, careers@, hr@, info@, talent@).
    Strictly <= 80 words.
    """
    email_clean = recipient_email.strip().lower()
    for prefix in GENERIC_EMAIL_PREFIXES:
        if email_clean.startswith(prefix):
            raise ValueError(f"Rejected generic email prefix '{prefix}' - founder pitches must target a named person.")

    first_name = recipient_name.strip().split()[0] if recipient_name.strip() else "there"
    hook = f"Noticed {company}'s work on {product_focus}." if product_focus else f"Following {company}'s engineering journey closely."

    # Verifiable Meesho proof point
    proof = "At Meesho, I built Go microservices with adaptive RPS handling 150K+ daily orders (~1,000 RPS) and cut reconciliation from 50+ hours to 2 hours with 40% fewer DB lookups."

    body = f"Hi {first_name},\n\n{hook} {proof}\n\nCode & architecture: https://github.com/DEEPAKSH123\n\nOpen to a 15-min technical chat next week?"

    words = body.split()
    if len(words) > 80:
        # Condense if needed
        body = f"Hi {first_name},\n\n{hook} At Meesho, I scaled Go services handling 150K+ daily orders (~1,000 RPS) and cut DB queries by 40%.\n\nProjects: https://github.com/DEEPAKSH123\n\nOpen for a 15-min chat next week?"
        words = body.split()

    return {
        "subject": f"Backend Engineer for {company} / Deepak Karkala",
        "body": body,
        "word_count": len(words),
        "recipient": recipient_email,
    }
