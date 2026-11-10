"""Company-Specific Technical & Recruiter Interview Cheat-Sheet Engine for Deepak S H.

Tailored for:
- Candidate: Deepak S H (SDE-1 Backend @ Meesho, ~1.3 YOE, RVCE CSE '25)
- Tech Stack: Java, Go (Golang), Kafka, Redis, Spring Boot, MySQL, GCP, High-Throughput Microservices
- Target Roles: SDE-1 / SDE-2 Backend Engineer

Provides:
1. Company Architecture & Scale Snapshot (Payment Switch, OMS, Distributed Ledgers, Cache Layers)
2. High-Probability System Design & Concurrency Questions
3. Deepak's Meesho "Silver Bullet" Stories (Kafka partitioning, Redis Redlock, Idempotency keys, MySQL lock contention)
4. HR & Screening Negotiation Playbook (Why leaving Meesho, CTC expectations, 30-day notice negotiation)
5. Sharp Reverse-Interview Questions to ask the engineering team
"""

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Pre-compiled high-fidelity cheat sheets for top Indian and global tech employers
CURATED_COMPANY_CHEATSHEETS: dict[str, dict[str, Any]] = {
    "phonepe": {
        "company": "PhonePe",
        "domain": "Payments, UPI Switch, Financial High-Throughput Infrastructure",
        "primary_stack": "Java, Go, Kafka, Aerospike / HBase / Cassandra, Redis, MySQL",
        "engineering_challenges": [
            "UPI Switch latency constraints (< 150ms roundtrip) under 100,000+ peak TPS.",
            "Distributed transaction isolation across banks, NPCI, and merchant wallets.",
            "Zero double-spend guarantees using distributed idempotency keys."
        ],
        "must_know_topics": [
            "2-Phase Commit (2PC) vs SAGA pattern for distributed transaction rollbacks.",
            "Idempotency Key design using Redis + DB unique constraints with atomic TTL.",
            "Kafka Consumer Group rebalancing under backpressure and partition skew.",
            "Database Connection Pooling & Deadlock elimination under high concurrency."
        ],
        "meesho_story_alignment": (
            "Highlight your work at Meesho on high-volume order/checkout transaction flows. "
            "Discuss how you handled burst traffic during seasonal sales using Kafka async event ingestion "
            "and Redis sliding-window rate limiting to shield downstream database replicas."
        ),
        "hr_tactics": {
            "why_leaving": "Meesho was a fantastic fast-paced scale ground; now eager to work on deep financial transaction engines and mission-critical UPI rail systems at PhonePe.",
            "target_ctc": "Standard SDE-1/SDE-2 benchmark (28–36 LPA total comp).",
            "notice_period": "30 days at Meesho (fully negotiable/buyout available)."
        },
        "questions_to_ask": [
            "How does your team handle partition rebalances during massive peak traffic spikes like Big Billion Days?",
            "What is PhonePe's architecture for cross-datacenter active-active state replication?"
        ]
    },
    "razorpay": {
        "company": "Razorpay",
        "domain": "Payment Gateway, Neo-Banking, Merchant Payouts & Webhooks",
        "primary_stack": "Golang, Kafka, Redis, MySQL (Aurora), Microservices, Kubernetes",
        "engineering_challenges": [
            "Guaranteed at-least-once webhook delivery with exponential backoff and jitter.",
            "High-availability payment routing across 50+ banking gateway switches.",
            "PCI-DSS compliant tokenization and distributed ledger accounting."
        ],
        "must_know_topics": [
            "Transactional Outbox Pattern for atomic database writes and Kafka event publishing.",
            "Distributed Locks with Redis (Redlock) and handling clock drift / GC pause edge cases.",
            "Circuit Breaker pattern (Resilience4j / Hystrix principles) when bank APIs time out.",
            "MySQL InnoDB B+ Tree indexing, composite index ordering, and query explain plans."
        ],
        "meesho_story_alignment": (
            "Deepak's Golang and Kafka microservice experience at Meesho matches Razorpay's core gateway stack 1:1. "
            "Highlight idempotent webhook callbacks, resilient event retry queues, and distributed tracing."
        ),
        "hr_tactics": {
            "why_leaving": "Razorpay is the benchmark in fintech developer engineering. Excited to leverage my Go & Kafka experience on payments infrastructure.",
            "target_ctc": "28–35 LPA base + ESOPs.",
            "notice_period": "30 days standard."
        },
        "questions_to_ask": [
            "How does Razorpay handle third-party gateway degradation without cascading failure to merchant checkout?",
            "How is the team adopting Go microservices vs legacy PHP monolith services?"
        ]
    },
    "target": {
        "company": "Target (Target India)",
        "domain": "Retail Supply Chain, Inventory Concurrency & Global Logistics",
        "primary_stack": "Java (Spring Boot), Kotlin, Kafka, Redis, Spinnaker, Cassandra",
        "engineering_challenges": [
            "High-concurrency inventory reservation during Black Friday sales.",
            "Distributed cache synchronization across brick-and-mortar stores and web apps.",
            "Multi-region data consistency."
        ],
        "must_know_topics": [
            "Pessimistic vs Optimistic Locking in relational databases for inventory balance.",
            "Cache stampede prevention (mutex locks, probabilistic early expiration).",
            "Kafka dead letter queues (DLQ) and poison pill message recovery.",
            "Event sourcing principles for order state progression."
        ],
        "meesho_story_alignment": (
            "Relate your Meesho e-commerce order management experience directly to Target's retail supply chain challenges. "
            "Emphasize inventory concurrency, idempotent checkout, and async order state progression."
        ),
        "hr_tactics": {
            "why_leaving": "Looking to work on global enterprise-scale retail systems and distributed supply chains.",
            "target_ctc": "25–32 LPA.",
            "notice_period": "30 days."
        },
        "questions_to_ask": [
            "What does the target architecture look like for real-time in-store vs online inventory syncing?"
        ]
    },
    "stripe": {
        "company": "Stripe",
        "domain": "Global Payments, Developer APIs & Distributed Ledgers",
        "primary_stack": "Ruby, Java, Go, Sorbet, FoundationDB, Kafka, AWS",
        "engineering_challenges": [
            "Strict 99.999% uptime and zero-data-loss double-entry financial bookkeeping.",
            "Extremely rigorous API design with backward compatibility guarantees.",
            "Idempotency keys across multi-region API clusters."
        ],
        "must_know_topics": [
            "Idempotency-Key HTTP headers and request-response caching in distributed stores.",
            "Double-entry bookkeeping math: every debit must equal a credit.",
            "Rate limiting algorithms (Token Bucket, Leaky Bucket, Sliding Log).",
            "Consistency models (Linearizability vs Serializability)."
        ],
        "meesho_story_alignment": (
            "Focus on clean REST API contract design, strict backward compatibility, and idempotency key handling."
        ),
        "hr_tactics": {
            "why_leaving": "Aiming for the highest tier of developer infrastructure and distributed systems engineering.",
            "target_ctc": "40–55 LPA (Global pay scale).",
            "notice_period": "30 days."
        },
        "questions_to_ask": [
            "How does Stripe verify zero drift between distributed ledgers and bank partner clearing reports?"
        ]
    }
}


def generate_company_cheatsheet(company: str, role_title: str = "SDE Backend Engineer") -> dict[str, Any]:
    """Generate a high-yield technical and behavioral interview cheat sheet."""
    comp_clean = company.strip()
    comp_lower = comp_clean.lower()

    # 1. Check curated library
    for key, data in CURATED_COMPANY_CHEATSHEETS.items():
        if key in comp_lower or comp_lower in key:
            res = dict(data)
            res["source"] = "Curated ApplyPilot Intelligence"
            res["role_title"] = role_title
            return res

    # 2. Try LLM dynamic generation if Gemini API is available
    try:
        from applypilot.config import load_env
        load_env()
        from applypilot.llm import get_client
        client = get_client()

        prompt = f"""You are a Principal Backend Engineer and Technical Interview Strategist.
Generate a high-yield technical & HR interview cheat sheet for candidate Deepak S H.

CANDIDATE CONTEXT:
- Name: Deepak S H
- Current Role: SDE-1 Backend Engineer at Meesho (~1.3 years experience)
- Education: RV College of Engineering (RVCE), CSE Class of 2025 (CGPA: 8.92)
- Primary Tech Stack: Java, Go (Golang), Kafka, Redis, Spring Boot, MySQL, GCP, Distributed Microservices
- Target Company: {comp_clean}
- Target Role: {role_title}

Return ONLY valid JSON matching this schema:
{{
  "company": "{comp_clean}",
  "domain": "<Domain and core business model>",
  "primary_stack": "<Known or inferred tech stack>",
  "engineering_challenges": [
    "<Real-world scale problem 1>",
    "<Real-world scale problem 2>",
    "<Real-world scale problem 3>"
  ],
  "must_know_topics": [
    "<System design / concurrency topic 1>",
    "<System design / concurrency topic 2>",
    "<Database / caching topic 3>",
    "<Architecture topic 4>"
  ],
  "meesho_story_alignment": "<Exact Meesho Go/Java/Kafka/Redis story Deepak should highlight for this company>",
  "hr_tactics": {{
    "why_leaving": "<Polite, ambitious answer for why Deepak wants to join {comp_clean}>",
    "target_ctc": "<Market standard compensation range for 1-2 YOE backend engineer>",
    "notice_period": "30 days at Meesho (negotiable)"
  }},
  "questions_to_ask": [
    "<Sharp question to ask the interviewer about their architecture 1>",
    "<Sharp question 2>"
  ]
}}"""
        resp_text = client.chat(
            messages=[
                {"role": "system", "content": "You output only clean, valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        # Parse JSON
        clean_json = resp_text.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.startswith("```"):
            clean_json = clean_json[3:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        data = json.loads(clean_json.strip())
        data["source"] = "Gemini AI Customized Intelligence"
        data["role_title"] = role_title
        return data
    except Exception as e:
        log.warning("Could not dynamically generate cheatsheet via LLM: %s. Using robust fallback.", e)

    # 3. Dynamic Fallback Generation
    return {
        "company": comp_clean,
        "role_title": role_title,
        "source": "ApplyPilot Standard Framework",
        "domain": f"{comp_clean} High-Throughput Engineering",
        "primary_stack": "Java, Go, Kafka, Redis, Microservices, Relational & NoSQL Datastores",
        "engineering_challenges": [
            f"Scaling {comp_clean}'s core transaction and data ingestion microservices under peak loads.",
            "Ensuring sub-100ms P99 API latencies across distributed multi-region infrastructure.",
            "Guaranteeing data consistency and zero double-processing with distributed idempotency."
        ],
        "must_know_topics": [
            "Idempotent API design using unique idempotency keys + atomic Redis SETNX / TTL.",
            "Kafka Consumer Group partition assignment, lag monitoring, and rebalancing strategies.",
            "Distributed Caching with Redis (Cache-aside, write-through, stampede prevention).",
            "Relational DB indexing, ACID transaction boundaries, and row-level locking (SELECT FOR UPDATE)."
        ],
        "meesho_story_alignment": (
            f"Highlight your experience at Meesho building high-throughput Go and Java backend services. "
            f"Walk through how you decoupled synchronous checkout flows with Kafka events, "
            f"leveraged Redis distributed locks for concurrency control, and tuned MySQL query execution plans."
        ),
        "hr_tactics": {
            "why_leaving": f"Deeply admire {comp_clean}'s engineering standards; excited to apply my Meesho distributed systems experience to solve your core platform challenges.",
            "target_ctc": "25–34 LPA (standard top-tier SDE-1 / SDE-2 benchmark).",
            "notice_period": "30 days (standard Meesho policy, buyout flexible)."
        },
        "questions_to_ask": [
            f"What does the P99 latency SLA look like for {comp_clean}'s primary backend services?",
            "How does the team manage schema evolution and database migrations across distributed microservices?"
        ]
    }
