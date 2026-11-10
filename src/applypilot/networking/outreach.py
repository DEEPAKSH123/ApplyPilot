"""LinkedIn Networking & Referral Outreach Generator.

Generates targeted LinkedIn search URLs (1st-degree connections, 2nd-degree mutual connections,
RVCE alumni, hiring managers, recruiters) and personalized referral messages for each opportunity.
"""

import urllib.parse
from typing import Any


def clean_company_name(company: str) -> str:
    """Extract clean company name from raw text."""
    if not company:
        return ""
    comp_clean = company.replace("WhatsApp (", "").replace(")", "").replace("Recruiter", "").strip()
    if comp_clean.lower() in ("linkedin", "indeed", "unknown", "tech company", "tech firm"):
        return ""
    return comp_clean


def generate_linkedin_searches(company: str, role_title: str) -> dict[str, str]:
    """Generate targeted LinkedIn search URLs with official degree and alumni filters."""
    comp_clean = clean_company_name(company)
    comp_encoded = urllib.parse.quote(f'"{comp_clean}"' if comp_clean else "")

    # 1. First-Degree Connections at target company (People Deepak is ALREADY connected with!)
    first_deg_url = f"https://www.linkedin.com/search/results/people/?keywords={comp_encoded}&network=%5B%22F%22%5D"

    # 2. Second-Degree Connections at target company (Mutual connections who can introduce Deepak!)
    second_deg_url = f"https://www.linkedin.com/search/results/people/?keywords={comp_encoded}&network=%5B%22S%22%5D"

    # 3. RVCE Alumni at target company (highest referral acceptance rate)
    alumni_kw = f"RVCE {comp_clean} software engineer".strip()
    alumni_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(alumni_kw)}"

    # 4. Tech Recruiters / Talent Acquisition
    recruiter_kw = f"{comp_clean} technical recruiter backend".strip()
    recruiter_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(recruiter_kw)}"

    # 5. Engineering Managers / Leads
    lead_kw = f"{comp_clean} engineering manager backend".strip()
    lead_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(lead_kw)}"

    return {
        "first_degree_url": first_deg_url,
        "second_degree_url": second_deg_url,
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

    # Candidate details from Deepak's profile
    full_name = "Deepak S H"
    phone = "8431433659"
    linkedin_url = "https://www.linkedin.com/in/deepak-s-h-82b772254"
    github_url = "https://github.com/Deepak-S-H"

    if candidate_profile:
        personal = candidate_profile.get("personal", {})
        full_name = personal.get("full_name", full_name)
        phone = personal.get("phone", phone)
        linkedin_url = personal.get("linkedin_url", linkedin_url)

    job_ref = ""
    if apply_url and not str(apply_url).lower().startswith("none") and str(apply_url).startswith("http"):
        job_ref = f" ({apply_url})"

    # Template 1: 1st-Degree Connection / Warm Referral Note (For active connections)
    first_deg_msg = (
        f"Hey [Name],\n\n"
        f"Hope you are doing well! Saw that {comp} is currently expanding its backend engineering team and hiring for {role_title}{job_ref}.\n\n"
        f"As you might know, I'm currently working as an SDE-I Backend Engineer at Meesho building distributed reconciliation platforms "
        f"and high-scale microservices using Java, Go, Kafka, Redis, and MySQL (graduated from RVCE '25, CGPA 8.92).\n\n"
        f"Given my background in high-throughput backend systems, I'd love to explore this role. "
        f"Would you be open to putting in a quick internal referral for me? Happy to share my tailored resume.\n\n"
        f"Thanks a lot, [Name]! Really appreciate your help.\n\n"
        f"Best,\n"
        f"{full_name}\n"
        f"Phone: {phone}"
    )

    # Template 2: 2nd-Degree (Mutual Connection) Referral Request
    second_deg_msg = (
        f"Hi [Name],\n\n"
        f"I noticed we share mutual connections in the Bengaluru tech community. Hope you're having a great week!\n\n"
        f"I saw that you are working at {comp} and that your team has an opening for {role_title}{job_ref}. "
        f"I'm an SDE-I Backend Engineer at Meesho (RVCE '25, CGPA 8.92) specializing in Java, Go, Kafka event-streaming, and distributed systems.\n\n"
        f"I would be deeply grateful if you'd be open to referring me internally. "
        f"I'd be glad to send across my tailored resume and brief project highlights for your review.\n\n"
        f"Thanks so much for considering my request!\n\n"
        f"Best regards,\n"
        f"{full_name}\n"
        f"LinkedIn: {linkedin_url}"
    )

    # Template 3: RVCE Alumni Referral Request
    alumni_msg = (
        f"Hi [Name],\n\n"
        f"Hope you are doing well! I noticed you are at {comp} and an RVCE alumnus. "
        f"I graduated from RVCE (CSE '25, CGPA 8.92) and am currently working as an SDE-I Backend Engineer at Meesho "
        f"on distributed reconciliation and financial platforms (Java, Go, Kafka, Redis, MySQL, GCP).\n\n"
        f"I came across the {role_title} opening{job_ref} and would be deeply grateful if you would be open to referring a fellow RVCE alumnus. "
        f"I would be glad to share my tailored resume and brief project highlights.\n\n"
        f"Thanks so much for your time and guidance!\n\n"
        f"Best regards,\n"
        f"{full_name}\n"
        f"Phone: {phone}\n"
        f"LinkedIn: {linkedin_url}"
    )

    # Template 4: Recruiter / Talent Acquisition Direct Message
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

    return {
        "first_deg_message": first_deg_msg,
        "second_deg_message": second_deg_msg,
        "alumni_message": alumni_msg,
        "recruiter_message": recruiter_msg,
        "first_degree_url": searches["first_degree_url"],
        "second_degree_url": searches["second_degree_url"],
        "alumni_search_url": searches["alumni_search_url"],
        "recruiter_search_url": searches["recruiter_search_url"],
        "lead_search_url": searches["lead_search_url"],
        "company_clean": comp,
    }
