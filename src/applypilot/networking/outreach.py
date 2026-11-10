"""LinkedIn Networking & Referral Outreach Generator.

Generates targeted LinkedIn search URLs (RVCE alumni, hiring managers, recruiters)
and personalized referral messages for each opportunity.
"""

import urllib.parse
from typing import Any


def generate_linkedin_searches(company: str, role_title: str) -> dict[str, str]:
    """Generate targeted LinkedIn search URLs for a company."""
    comp_clean = company.replace("WhatsApp (", "").replace(")", "").replace("Recruiter", "").strip()
    if comp_clean.lower() in ("linkedin", "indeed", "unknown", "tech company", "tech firm"):
        comp_clean = ""

    comp_query = f'"{comp_clean}"' if comp_clean else ""

    # 1. RVCE Alumni at target company (highest referral acceptance rate)
    alumni_kw = f"RVCE {comp_query} software engineer".strip()
    alumni_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(alumni_kw)}"

    # 2. Tech Recruiters / Talent Acquisition
    recruiter_kw = f"{comp_query} technical recruiter backend".strip()
    recruiter_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(recruiter_kw)}"

    # 3. Engineering Managers / Leads
    lead_kw = f"{comp_query} engineering manager backend".strip()
    lead_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(lead_kw)}"

    return {
        "alumni_search_url": alumni_url,
        "recruiter_search_url": recruiter_url,
        "lead_search_url": lead_url,
        "company_clean": comp_clean or company,
    }


def generate_outreach_messages(
    company: str,
    role_title: str,
    apply_url: str = "",
    recruiter_email: str = "",
    candidate_profile: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Generate high-converting personalized referral and outreach messages."""
    searches = generate_linkedin_searches(company, role_title)
    comp = searches["company_clean"]

    # Candidate details
    full_name = "Deepak S H"
    phone = "8431433659"
    linkedin_url = "https://www.linkedin.com/in/deepak-s-h-851a76201"
    github_url = "https://github.com/Deepak-S-H"

    if candidate_profile:
        personal = candidate_profile.get("personal", {})
        full_name = personal.get("full_name", full_name)
        phone = personal.get("phone", phone)
        linkedin_url = personal.get("linkedin_url", linkedin_url)

    job_ref = f" ({apply_url})" if (apply_url and not apply_url.startswith("None")) else ""

    # Template 1: RVCE Alumni Referral Request (Warm, respectful, high conversion)
    alumni_msg = (
        f"Hi [Name],\n\n"
        f"Hope you are doing well! I noticed you are at {comp} and an RVCE alumnus. "
        f"I graduated from RVCE (CSE '25, CGPA 8.92) and am currently working as an SDE-I Backend Engineer at Meesho "
        f"on distributed reconciliation and financial platforms (Java, Go, Kafka, Redis, MySQL, GCP).\n\n"
        f"I came across the {role_title} opening{job_ref} and would be deeply grateful if you would be open to referring me. "
        f"I would be glad to share my tailored resume and brief project highlights.\n\n"
        f"Thanks so much for your time and guidance!\n\n"
        f"Best regards,\n"
        f"{full_name}\n"
        f"Phone: {phone}\n"
        f"LinkedIn: {linkedin_url}"
    )

    # Template 2: Recruiter / Talent Acquisition Direct Message
    recruiter_msg = (
        f"Hi [Name],\n\n"
        f"I came across the {role_title} opening at {comp}{job_ref}. "
        f"I am currently an SDE-I Backend Engineer at Meesho with 1.3 years of experience building high-throughput distributed systems "
        f"using Java, Go, Kafka, Redis, and Spring Boot, and graduated from RVCE (CGPA 8.92).\n\n"
        f"My background in financial reconciliation, payment pipelines, and high-scale backend services aligns closely with {comp}'s stack. "
        f"I would love to connect and share my tailored resume if you have a brief moment.\n\n"
        f"Best regards,\n"
        f"{full_name}\n"
        f"Phone: {phone}\n"
        f"LinkedIn: {linkedin_url}"
    )

    # Template 3: Engineering Manager / Team Lead Cold Pitch
    lead_msg = (
        f"Hi [Name],\n\n"
        f"I have been following engineering at {comp} with great admiration. "
        f"I am an SDE-I Backend Engineer at Meesho (RVCE '25, CGPA 8.92) specializing in distributed systems, Kafka event streaming, "
        f"and Go/Java microservices (handling 10M+ daily transactions).\n\n"
        f"I saw your team is hiring for {role_title}{job_ref} and wanted to reach out directly to express my strong interest. "
        f"I would appreciate an opportunity to speak briefly or share my portfolio.\n\n"
        f"Best regards,\n"
        f"{full_name}\n"
        f"Phone: {phone} | {github_url}"
    )

    return {
        "alumni_message": alumni_msg,
        "recruiter_message": recruiter_msg,
        "lead_message": lead_msg,
        "alumni_search_url": searches["alumni_search_url"],
        "recruiter_search_url": searches["recruiter_search_url"],
        "lead_search_url": searches["lead_search_url"],
        "company_clean": comp,
    }
