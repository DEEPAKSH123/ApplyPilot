import os
import subprocess
import shutil

gmail_bin = shutil.which('gmail') or shutil.which('gmail.cmd')
resume_pdf = r'D:\ApplyPilot_Workspace\data\Deepak_S_H_Resume.pdf'

targets = [
    {
        'agency': 'Purple Quarter',
        'key': 'purple_quarter',
        'to': 'interact@purplequarter.com',
        'focus': 'tech leadership and tier-1 VC-funded startups'
    },
    {
        'agency': 'SutraHR',
        'key': 'sutrahr',
        'to': 'buzz@sutrahr.com',
        'focus': 'leading tech startups, SaaS & Fintech mandates'
    },
    {
        'agency': 'TalentStack',
        'key': 'talentstack',
        'to': 'hello@talentstack.in',
        'focus': 'Series A/B product startups, SaaS & high-growth tech'
    },
    {
        'agency': 'Talhive',
        'key': 'talhive',
        'to': 'search@talhive.com',
        'focus': 'product & engineering hiring across Bengaluru & NCR'
    },
    {
        'agency': 'PeopleCap',
        'key': 'peoplecap',
        'to': 'engage@peoplecap.in',
        'focus': 'fintech & high-scale BFSI technology searches'
    }
]

created = []

for t in targets:
    agency = t['agency']
    key = t['key']
    to_email = t['to']
    focus = t['focus']
    
    subject = 'Deepak S H | SDE-1 Backend (Meesho, 2 YOE) | Java, Go, Distributed Systems | Exploring Tier-1 Startups'
    
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
    
    temp_dir = os.environ.get('TEMP', r'C:\Users\Admin\AppData\Local\Temp')
    body_file = os.path.join(temp_dir, f'pitch_{key}.txt')
    with open(body_file, 'w', encoding='utf-8') as f:
        f.write(body)
        
    cmd = [
        gmail_bin, 'create-draft',
        '--to', to_email,
        '--subject', subject,
        '--body-file', body_file,
        '--file', resume_pdf
    ]
    
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if p.returncode == 0:
        print(f"[SUCCESS] Draft created for {agency} ({to_email})")
        created.append(agency)
    else:
        print(f"[ERROR] Failed for {agency}: {p.stderr.strip()} | {p.stdout.strip()}")

print(f"\nFinished. Successfully created {len(created)}/{len(targets)} drafts in Gmail.")
