"""Gemini Application & Screening Copilot for Deepak S H.

Answers questions asked in job application forms, screening questionnaires,
behavioral prompts, and technical/culture-fit assessments.

Grounding sources:
1. Candidate profile (data/profile.json) - contact, compensation, legal authorization, availability
2. Master resume (data/resume.txt) - Meesho metrics, 50K+ orders/day, 95% latency reduction, BNPL
3. Curated company cheatsheets (interview_cheatsheet.py) - architectural patterns, Kafka/Redis/MySQL stories
4. Interview learnings & preferences (MEMORY.md) - strict 0-3 YOE targeting, no US/UK visa dependence

Tone:
- Human, personal, and authentic (first-person 'I')
- Concrete metrics & real scale challenges rather than generic buzzwords
- Respects constraints: concise form inputs, paragraph answers, or bulleted breakdown as requested
"""

import json
import logging
import os
import re
from typing import Any

from applypilot.config import APP_DIR, PROFILE_PATH, RESUME_PATH, load_profile
from applypilot.enrichment.interview_cheatsheet import CURATED_COMPANY_CHEATSHEETS
from applypilot.llm import LLMClient

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the personal AI Application & Screening Copilot for Deepak S H.
Your purpose is to answer job application screening questions, written assessments, and behavioral/culture-fit prompts.
You speak in Deepak's authentic, first-person voice ('I', 'my').

==================== CANDIDATE GROUND TRUTH ====================
• Name: Deepak S H
• Current Role: Software Development Engineer I (Backend) at Meesho (~1.3 years full-time + 6 months internship = ~2 yrs total professional backend experience).
• Education: RV College of Engineering (RVCE), Bengaluru — B.E. Computer Science and Engineering (Class of 2025, CGPA: 8.92 / 10).
• Location: Bengaluru, Karnataka, India (residing in Kadubeesanahalli / Panathur Road). Open to Bengaluru, Pune, Hyderabad, or Remote.
• Primary Tech Stack: Java (Java 17, Spring Boot), Go (Golang), Apache Kafka, Redis, MySQL, GCP (Google Cloud Platform), Docker, Linux, REST Microservices.
• Current CTC & Expectation: Current ~20 LPA, Expected: 24–32 LPA (Negotiable based on role & equity).
• Notice Period & Availability: 30 days standard at Meesho, but fully negotiable / buyout available, early release possible.
• Work Authorization: Indian Citizen, legally authorized to work in India. Do NOT require visa sponsorship for India/Remote roles.

==================== REAL MEESHO PRODUCTION METRICS & STORIES ====================
1. Financial Reconciliation Platform (Scale & Idempotency):
   - Re-architected financial reconciliation workflows with adaptive requests-per-second (RPS) control.
   - Reduced end-to-end processing time from 50–60 hours down to 2–3 hours (~95% reduction) while preventing downstream rate limits with payment gateways and lending partners.
   - Built fault-tolerant Kafka event pipelines with idempotent consumers (using Redis unique locks + MySQL unique constraints) to eliminate duplicate settlement records.
   - Developed BigQuery and Metabase dashboards for real-time monitoring and transaction anomaly detection.

2. Pay Later (BNPL) & Lending Onboarding Platform (High Throughput & Low Latency):
   - Built backend services supporting 50K+ daily orders across multiple lending partners.
   - Optimized onboarding and checkout APIs using Redis multi-layer caching and database query tuning, reducing DB lookups by 40% while maintaining a strict 300 ms response-time SLA.
   - Implemented streaming APIs and Kafka file processing pipelines for lender whitelisting and automated dunning-letter delivery.

3. System Design & Concurrency Philosophy:
   - High-throughput transaction consistency: Idempotency keys, transactional outbox pattern, and distributed locks (Redis Redlock with TTL safety).
   - Kafka partitioning & consumer lag: Mitigating rebalance storms with cooperative sticky assignors and dead-letter queues (DLQ).
   - MySQL tuning: Composite indexing, preventing table-scan locking during high-concurrency writes, and proper isolation levels (Read Committed).

4. Non-Technical / Personal Dimension:
   - Passionate about music production, playing piano, Carnatic vocal music, and playing badminton.
   - Highly collaborative, values extreme ownership, clear asynchronous documentation, and pragmatic engineering over over-engineering.

==================== CRITICAL RESPONSE INSTRUCTIONS ====================
1. Write in FIRST-PERSON ("I", "my work at Meesho", "my team").
2. Sound HUMAN, grounded, and engaging — never robotic, corporate fluff, or sycophantic.
3. Tailor specifically to the question type:
   - If asked for YOE / Numbers: State clearly and concisely (e.g., "1.3 years full-time at Meesho, ~2 years total including backend internship").
   - If asked "Why our company?": Combine what the company does with Deepak's exact relevant experience (e.g. for payments: "At Meesho I worked on financial reconciliation and BNPL, so building high-throughput payment rails at [Company] matches my day-to-day focus").
   - If asked behavioral (STAR method): Describe the Situation at Meesho, the Task, the Action (technical choices made), and the Result (real metrics: 95% time reduction, 50K+ orders/day, 40% DB load reduction).
   - If asked technical questions: Detail the architectural trade-offs, concurrency considerations, and failure modes based on Deepak's real stack (Java, Go, Kafka, Redis).
4. Do NOT hallucinate skills Deepak does not have (e.g., he does NOT claim to be a 10-year architect or a Mobile/iOS dev).
5. Output format: Return the direct answer ready to paste into an application form. If multiple styles help (e.g., a 1-line version and an expanded paragraph), provide both clearly labeled.
"""


def answer_screening_question(
    question: str,
    company: str = "",
    role_title: str = "",
    job_description: str = "",
    tone: str = "conversational_professional"
) -> dict[str, Any]:
    """Generate a highly personalized, human answer to any application form question using Gemini."""
    if not question or not question.strip():
        return {"status": "error", "message": "Question is required."}

    # Enrich with curated company cheat sheet if available
    company_context = ""
    comp_key = (company or "").lower().strip()
    for k, v in CURATED_COMPANY_CHEATSHEETS.items():
        if k in comp_key or comp_key in k:
            company_context = f"\nCompany Context ({v['company']}):\n- Domain: {v.get('domain')}\n- Stack: {v.get('primary_stack')}\n- Key Challenges: {', '.join(v.get('engineering_challenges', []))}\n- Meesho Alignment: {v.get('meesho_story_alignment', '')}"
            break

    user_prompt = f"""Target Company: {company or 'Tech Employer'}
Target Role: {role_title or 'Backend Engineer / SDE-I'}
{company_context}

Additional Job Context / Excerpt:
{job_description[:600] if job_description else 'N/A'}

==================================================
APPLICATION / SCREENING QUESTION TO ANSWER:
"{question.strip()}"
==================================================

Please provide an authentic, high-impact answer that Deepak can paste into the application form.
Include:
1. Quick/Direct Answer (1-3 sentences, ideal for short text fields or screening boxes)
2. Detailed/Expanded Answer (1-2 structured paragraphs, ideal for behavioral or 'Tell us why' essay questions)
"""

    try:
        from applypilot.config import load_env
        load_env()
        from applypilot.llm import LLMClient, _detect_provider
        base_url, model_name, api_key = _detect_provider()
        client = LLMClient(base_url, model_name, api_key)
        answer_text = client.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.4
        )
        return {
            "status": "ok",
            "question": question,
            "company": company,
            "role_title": role_title,
            "answer": answer_text
        }
    except Exception as e:
        log.exception("Error answering screening question via LLMClient")
        # Graceful fallback heuristic
        fallback = _heuristic_fallback_answer(question, company, role_title)
        return {
            "status": "fallback",
            "question": question,
            "company": company,
            "role_title": role_title,
            "answer": fallback,
            "error": str(e)
        }


def _heuristic_fallback_answer(question: str, company: str, role_title: str) -> str:
    """Smart offline rule-based fallback if LLM is unreachable."""
    q_lower = question.lower()
    comp = company or "your team"
    role = role_title or "Backend Engineer"

    if any(k in q_lower for k in ("why", "interest", "apply", "attracted")):
        return (
            f"**Quick Answer:**\n"
            f"I am an SDE-I Backend Engineer at Meesho with hands-on experience building high-throughput financial reconciliation and lending platforms using Java, Go, Kafka, and Redis. I'm excited about {comp} because the engineering challenges directly align with my background in event-driven architecture, distributed transaction consistency, and sub-second SLAs.\n\n"
            f"**Detailed Answer:**\n"
            f"At Meesho, I've focused on resilient microservices handling 50K+ daily transactions—most notably re-architecting reconciliation workflows to slash processing time from 50–60 hours down to 2–3 hours (~95% reduction). {comp}'s mission and engineering bar require robust backend systems that scale gracefully under load. With my background in Java 17, Go, Kafka consumer tuning, and low-latency Redis caching, I can hit the ground running with zero ramp-up time to build reliable systems for {comp}."
        )

    if any(k in q_lower for k in ("experience", "yoe", "years")):
        return (
            "**Quick Answer:**\n"
            "I have approximately 2 years of professional backend engineering experience: 1.3 years as a full-time SDE-I at Meesho and 6 months of backend internship experience, working primarily with Java, Go, Kafka, Redis, and MySQL."
        )

    if any(k in q_lower for k in ("notice", "available", "start")):
        return (
            "**Quick Answer:**\n"
            "My standard notice period at Meesho is 30 days, but I am available for immediate buyout or early release depending on business requirements."
        )

    if any(k in q_lower for k in ("salary", "ctc", "compensation")):
        return (
            "**Quick Answer:**\n"
            "My current total compensation is ~20 LPA. For my next role, I am targeting 24–32 LPA (base + components), but I am flexible and open to discussion based on the total compensation package and role scope."
        )

    if any(k in q_lower for k in ("work auth", "authorized", "visa", "sponsorship")):
        return (
            "**Quick Answer:**\n"
            "I am an Indian Citizen and legally authorized to work in India. I do not require visa sponsorship."
        )

    return (
        f"**Quick Answer:**\n"
        f"I'm an SDE-I Backend Engineer at Meesho (RVCE CSE '25, 8.92 CGPA) specializing in Java, Go, Kafka, and Redis distributed microservices. My work centers on high-volume financial reconciliation and low-latency lending platforms. I bring a strong ownership mindset, deep curiosity for scalable distributed systems, and a track record of driving measurable latency and throughput improvements."
    )
