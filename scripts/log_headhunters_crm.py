import os
import urllib.parse
from applypilot.networking.cold_email_tracker import record_cold_outreach

targets = [
    {
        'agency': 'Purple Quarter',
        'email': 'interact@purplequarter.com',
        'focus': 'tech leadership and tier-1 VC-funded startups (Unicorns / Series B-C)'
    },
    {
        'agency': 'SutraHR',
        'email': 'buzz@sutrahr.com',
        'focus': 'leading tech startups, SaaS & Fintech mandates'
    },
    {
        'agency': 'TalentStack',
        'email': 'hello@talentstack.in',
        'focus': 'Series A/B product startups, SaaS & high-growth tech'
    },
    {
        'agency': 'Talhive',
        'email': 'search@talhive.com',
        'focus': 'product & engineering hiring across Bengaluru & NCR'
    },
    {
        'agency': 'PeopleCap',
        'email': 'engage@peoplecap.in',
        'focus': 'fintech & high-scale BFSI technology searches'
    }
]

subject = 'Deepak S H | SDE-1 Backend (Meesho, 2 YOE) | Java, Go, Distributed Systems | Exploring Tier-1 Startups'

for t in targets:
    agency = t['agency']
    to_email = t['email']
    focus = t['focus']
    
    body = (
        f"Hi {agency} Team,\n\n"
        f"I hope you are doing well.\n\n"
        f"I am an SDE-1 (Backend) at Meesho with 2 years of experience designing and scaling high-throughput distributed systems in Java, Go, and Spring Boot.\n\n"
        f"I am reaching out to your team given your strong track record in {focus}. I am actively exploring backend engineering opportunities (SDE-1 / SDE-2) across high-growth product startups and tech unicorns in Bengaluru or Remote.\n\n"
        f"Quick Overview:\n"
        f"• Current Role: Software Development Engineer I (Backend) at Meesho\n"
        f"• Core Expertise: Distributed microservices, Kafka event streaming, Redis caching, high-concurrency order/catalog systems, MySQL, GCP/AWS\n"
        f"• Education: B.E. Computer Science, RVCE ('25 batch)\n"
        f"• Tech Stack: Java, Go (Golang), Spring Boot, Kafka, Distributed Systems, Docker, Kubernetes\n"
        f"• Notice Period: Serving notice / Immediate to 30 days\n\n"
        f"I have attached my tailored resume for your review. If you have active tech mandates or confidential client searches matching my background, I would be glad to connect.\n\n"
        f"Looking forward to hearing from you.\n\n"
        f"Best regards,\n"
        f"Deepak S H\n"
        f"Bengaluru, India | +91 8431433659\n"
        f"LinkedIn: https://www.linkedin.com/in/deepak-s-h-82b772254\n"
        f"GitHub: https://github.com/Deepak-S-H\n"
    )
    
    res = record_cold_outreach(
        recipient_email=to_email,
        company=agency,
        role_title='SDE-1 / SDE-2 Backend',
        recipient_role='headhunter_agency',
        subject=subject,
        body=body,
        template_id='headhunter_tier1_v1'
    )
    print(f"Logged outreach for {agency}: ID {res.get('id')}")

print("All headhunters registered in ApplyPilot CRM tracking.")
