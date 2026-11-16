"""LinkedIn Networking & Referral Outreach Generator.

Generates targeted LinkedIn search URLs (1st-degree connections, 2nd-degree mutual connections,
RVCE alumni, hiring managers, recruiters) and personalized referral messages for each opportunity.
"""

import re
import urllib.parse
from typing import Any


def clean_company_name(company: str) -> str:
    """Extract clean company name from raw text."""
    if not company:
        return ""
    comp_clean = str(company).replace("WhatsApp (", "").replace("Telegram (", "").replace(")", "").replace("Recruiter", "").strip()
    
    # Strip common prefixes like 'Hiring for Swiggy', 'Jobs at Google', 'Careers at Microsoft'
    comp_clean = re.sub(r'^(?:hiring\s+(?:for|at)|jobs?\s+(?:at|for|in)|careers?\s+(?:at|for)|urgently\s+hiring\s+(?:for|at))\s+', '', comp_clean, flags=re.IGNORECASE).strip()
    # Strip common suffixes like 'is hiring', 'offcampusjobs4u', etc.
    comp_clean = re.sub(r'\s+(?:is\s+hiring|careers|jobs|team|offcampus.*)$', '', comp_clean, flags=re.IGNORECASE).strip()
    
    if comp_clean.lower().startswith("whatsapp") or comp_clean.lower().startswith("telegram") or comp_clean.lower() in ("linkedin", "indeed", "glassdoor", "unknown", "tech company", "tech firm", "rvce_tech_referrals"):
        return ""
    return comp_clean


def generate_linkedin_searches(company: str, role_title: str) -> dict[str, str]:
    """Generate targeted LinkedIn search URLs with official degree and alumni filters."""
    comp_clean = clean_company_name(company)
    if not comp_clean:
        return {
            "first_degree_url": "https://www.linkedin.com/search/results/people/?network=%5B%22F%22%5D",
            "second_degree_url": "https://www.linkedin.com/search/results/people/?network=%5B%22S%22%5D",
            "alumni_search_url": "https://www.linkedin.com/search/results/people/?keywords=RVCE",
            "recruiter_search_url": "https://www.linkedin.com/search/results/people/?keywords=technical%20recruiter%20backend%20bangalore",
            "lead_search_url": "https://www.linkedin.com/search/results/people/?keywords=engineering%20manager%20backend%20bangalore",
            "hiring_posts_url": 'https://www.linkedin.com/search/results/content/?keywords=backend%20engineer%20AND%20(%22hiring%22%20OR%20%22requirement%22)&sortBy=%22date_posted%22',
            "company_clean": "",
        }

    comp_encoded = urllib.parse.quote(f'"{comp_clean}"')

    # 1. First-Degree Connections at target company (People Deepak is ALREADY connected with!)
    first_deg_url = f"https://www.linkedin.com/search/results/people/?keywords={comp_encoded}&network=%5B%22F%22%5D"

    # 2. Second-Degree Connections at target company (Mutual connections who can introduce Deepak!)
    second_deg_url = f"https://www.linkedin.com/search/results/people/?keywords={comp_encoded}&network=%5B%22S%22%5D"

    # 3. RVCE Alumni at target company (highest referral acceptance rate)
    alumni_kw = f"RVCE {comp_clean}".strip()
    alumni_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(alumni_kw)}"

    # 4. Tech Recruiters / Talent Acquisition
    recruiter_kw = f'"{comp_clean}" technical recruiter backend'.strip()
    recruiter_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(recruiter_kw)}"

    # 5. Engineering Managers / Leads
    lead_kw = f'"{comp_clean}" engineering manager backend'.strip()
    lead_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(lead_kw)}"

    # 6. Recruiter Hiring & Requirement Posts
    query_str = f'"{comp_clean}" backend engineer AND ("hiring" OR "requirement")'
    hiring_posts_url = f"https://www.linkedin.com/search/results/content/?keywords={urllib.parse.quote(query_str)}&sortBy=%22date_posted%22"

    return {
        "first_degree_url": first_deg_url,
        "second_degree_url": second_deg_url,
        "alumni_search_url": alumni_url,
        "recruiter_search_url": recruiter_url,
        "lead_search_url": lead_url,
        "hiring_posts_url": hiring_posts_url,
        "company_clean": comp_clean,
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
    email = "deepakshkarkala@gmail.com"
    linkedin_url = "https://www.linkedin.com/in/deepak-s-h-82b772254"

    if candidate_profile:
        personal = candidate_profile.get("personal", {})
        full_name = personal.get("full_name", full_name)
        phone = personal.get("phone", phone)
        email = personal.get("email", email)
        linkedin_url = personal.get("linkedin_url", linkedin_url)

    job_ref = ""
    if apply_url and not str(apply_url).lower().startswith("none") and str(apply_url).startswith("http"):
        job_ref = f" ({apply_url})"

    # Template 1: 1st-Degree Connection / Colleague (Direct & casual)
    first_deg_msg = (
        f"Hey [Name],\n\n"
        f"Saw that {comp} has an opening for {role_title}{job_ref}.\n\n"
        f"I'm currently working as an SDE-I Backend Engineer at Meesho, mainly with Java, Go, Kafka, and Redis on our financial reconciliation services.\n\n"
        f"Would you be able to refer me internally for this role? Happy to send my resume over.\n\n"
        f"Thanks,\n"
        f"{full_name}"
    )

    # Template 2: Stranger / Peer who posted asking for resumes
    second_deg_msg = (
        f"Hi [Name],\n\n"
        f"Saw your post about the {role_title} opening at {comp}{job_ref} and that you are helping with referrals / collecting profiles.\n\n"
        f"I'm an SDE-I Backend Engineer at Meesho (RVCE '25, CGPA 8.92). My background is in backend systems using Java, Go, Kafka, and Redis.\n\n"
        f"I've attached my resume. Could you please share it with the hiring team or submit a referral?\n\n"
        f"Quick details:\n"
        f"• Role: {role_title}\n"
        f"• Current: SDE-I Backend @ Meesho\n"
        f"• Experience: 2 years (Full-time Backend @ Meesho + Active Internship Engagements)\n"
        f"• Notice: Immediate / 0 days\n"
        f"• Email: {email} | Phone: {phone}\n"
        f"• LinkedIn: {linkedin_url}\n\n"
        f"Thanks for your help,\n"
        f"{full_name}"
    )

    # Template 3: RVCE Alumni
    alumni_msg = (
        f"Hi [Name],\n\n"
        f"Saw that you're at {comp}. I graduated from RVCE in CSE (2025) and am currently an SDE-I Backend Engineer at Meesho.\n\n"
        f"I came across the {role_title} opening{job_ref} and wanted to check if you'd be comfortable referring a junior from RVCE. I work primarily with Java, Go, Kafka, and distributed backend services.\n\n"
        f"Happy to share my resume if you're open to it.\n\n"
        f"Thanks,\n"
        f"{full_name}\n"
        f"LinkedIn: {linkedin_url}"
    )

    # Template 4: HR / Recruiter Direct Message
    recruiter_msg = (
        f"Hi [Name],\n\n"
        f"I noticed the {role_title} role at {comp}{job_ref} and wanted to reach out directly.\n\n"
        f"I am an SDE-I Backend Engineer at Meesho working on distributed reconciliation pipelines and high-volume services using Java, Go, Kafka, Redis, and Spring Boot (RVCE CSE '25, CGPA 8.92).\n\n"
        f"My day-to-day work closely matches your backend stack, and I can join immediately. Could I share my resume with you for consideration?\n\n"
        f"Best,\n"
        f"{full_name}\n"
        f"Phone: {phone} | Email: {email}\n"
        f"LinkedIn: {linkedin_url}"
    )

    # Template 5: Kannada Referral Community (KaDegree) Note
    kadegree_msg = (
        f"ನಮಸ್ಕಾರ [Name],\n\n"
        f"Hope you are doing well!\n\n"
        f"I saw the {role_title} opening at {comp} posted on KaDegree{job_ref}.\n\n"
        f"I'm an SDE-I Backend Engineer at Meesho (RVCE CSE '25). I work on distributed systems and payment pipelines using Java, Go, Kafka, and Redis.\n\n"
        f"My resume is attached. Could you please refer my profile for this opening?\n\n"
        f"Details:\n"
        f"• Role: {role_title} @ {comp}\n"
        f"• Current: SDE-I Backend @ Meesho\n"
        f"• Phone: {phone} | Email: {email}\n"
        f"• LinkedIn: {linkedin_url}\n\n"
        f"ಧನ್ಯವಾದಗಳು!\n"
        f"{full_name}"
    )

    return {
        "first_deg_message": first_deg_msg,
        "second_deg_message": second_deg_msg,
        "alumni_message": alumni_msg,
        "recruiter_message": recruiter_msg,
        "kadegree_message": kadegree_msg,
        "first_degree_url": searches["first_degree_url"],
        "second_degree_url": searches["second_degree_url"],
        "alumni_search_url": searches["alumni_search_url"],
        "recruiter_search_url": searches["recruiter_search_url"],
        "lead_search_url": searches["lead_search_url"],
        "hiring_posts_url": searches.get("hiring_posts_url", ""),
        "kadegree_url": "https://referral-community.kadegree.in/get",
        "company_clean": comp,
    }
