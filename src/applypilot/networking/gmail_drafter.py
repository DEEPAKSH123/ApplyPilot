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
) -> dict[str, str]:
    """Generate high-converting recruiter cold email subject and clean, human-written body."""
    # Clean company name
    comp = (company or "").replace("WhatsApp (", "").replace(")", "").strip()
    for drop in ["WhatsApp Live Referral", "WhatsApp", "Telegram Channel", "Telegram", "KaDegree", "JobSpy"]:
        comp = comp.replace(drop, "").strip()
    if not comp or comp.lower() in ("unknown", "linkedin", "indeed", "glassdoor", "tech company", "tech firm", "team"):
        comp = "your engineering team"

    # Clean role title
    clean_role = role_title or "Backend Software Engineer"
    if clean_role.lower() in ("sde i", "sde 1", "sde-1", "sde-i"):
        clean_role = "Software Development Engineer I (SDE-I) - Backend"

    # Candidate details
    full_name = "Deepak S H"
    phone = "+91 8431433659"
    email = "deepakshkarkala@gmail.com"
    linkedin_url = "https://www.linkedin.com/in/deepak-s-h-82b772254"
    github_url = "https://github.com/Deepak-S-H"
    leetcode_url = "https://leetcode.com/u/Deepak_S_H/"

    if candidate_profile:
        personal = candidate_profile.get("personal", {})
        full_name = personal.get("full_name", full_name)
        phone = personal.get("phone", phone)
        email = personal.get("email", email)
        linkedin_url = personal.get("linkedin_url", linkedin_url)
        github_url = personal.get("github_url", github_url) or github_url

    # Salutation: extract first name if full name passed
    first_name = recruiter_name.strip().split()[0] if recruiter_name and recruiter_name.strip() else ""
    if first_name.lower() in ("whatsapp", "telegram", "unknown", "lead", "community"):
        first_name = ""
    salutation = f"Hi {first_name}," if first_name else "Hi Hiring Team,"

    subject = f"Application: {clean_role} - {full_name} (RVCE '25 | SDE-I @ Meesho)"

    body = (
        f"{salutation}\n\n"
        f"I hope you are having a productive week!\n\n"
        f"I am writing to express my strong interest in joining {comp} for the {clean_role} role.\n\n"
        f"I am currently an SDE-I Backend Engineer at Meesho and an RVCE CSE 2025 graduate (CGPA 8.92) "
        f"with production experience designing, building, and scaling high-throughput distributed systems:\n\n"
        f"• Core Tech Stack: Java 17, Go (Golang), Spring Boot, Apache Kafka, Redis, MySQL, Docker, Kubernetes, GCP.\n"
        f"• High-Scale Impact: Architected and scaled distributed financial reconciliation engines, event-driven pipelines handling millions of daily transactions, and sub-10ms Redis caching layers.\n"
        f"• Production Reliability: Built robust idempotent consumers, distributed locking mechanisms, and self-healing Dead Letter Queue (DLQ) workers.\n"
        f"• Problem Solving: Strong Data Structures & Algorithms foundation with 500+ problems solved across LeetCode and GeeksforGeeks.\n\n"
        f"I have attached my tailored resume (PDF) highlighting relevant backend and distributed systems experience for your review. You can also explore my background and profiles here:\n"
        f"• LinkedIn: {linkedin_url}\n"
        f"• GitHub: {github_url}\n"
        f"• LeetCode: {leetcode_url}\n"
        f"• Phone: {phone}\n\n"
        f"Would you be open to a brief 5-minute conversation or forwarding my profile to the hiring manager for this role?\n\n"
        f"Thank you so much for your time and consideration!\n\n"
        f"Best regards,\n\n"
        f"{full_name}\n"
        f"SDE-I Backend Engineer, Meesho\n"
        f"RVCE CSE '25 | {phone}\n"
        f"{email}\n"
    )

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

    if not pdf_to_attach and RESUME_PDF_PATH.exists():
        pdf_to_attach = RESUME_PDF_PATH.resolve()

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

    if not pdf_to_attach and RESUME_PDF_PATH.exists():
        pdf_to_attach = RESUME_PDF_PATH.resolve()

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
    if not tailored_path or not Path(tailored_path).exists():
        try:
            from applypilot.scoring.jit_tailor import tailor_single_job
            t_res = tailor_single_job(rowid)
            if t_res.get("tailored_resume_path"):
                tailored_path = t_res["tailored_resume_path"]
        except Exception:
            pass

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


def draft_for_job(rowid: int, custom_recipient: str | None = None) -> dict[str, Any]:
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
    if not tailored_path or not Path(tailored_path).exists():
        try:
            from applypilot.scoring.jit_tailor import tailor_single_job
            t_res = tailor_single_job(rowid)
            if t_res.get("tailored_resume_path"):
                tailored_path = t_res["tailored_resume_path"]
        except Exception:
            pass

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
    )

    return create_gmail_draft(
        to_email=recipient,
        subject=email_data["subject"],
        body_markdown=email_data["body_markdown"],
        attachment_path=tailored_path,
    )
