"""Seed the database with synthetic LLM request records and prompt templates.

Generates:
  - 3 named prompt templates, each with 2–3 versions
  - 500 LLM request records; ~60% linked to a template version
  - Realistic distributions of latency, token counts, errors, feedback

Usage:
    python scripts/seed_data.py
    # or
    make seed
"""

import asyncio
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_observability.core.pricing import calculate_cost
from llm_observability.db.database import AsyncSessionLocal, init_db
from llm_observability.db.models import LLMRequest, PromptTemplate

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
]

MODEL_LATENCY_PARAMS = {
    "claude-haiku-4-5-20251001": (6.5, 0.35),
    "claude-sonnet-4-6":         (7.0, 0.40),
    "claude-opus-4-6":           (7.5, 0.45),
}

# ---------------------------------------------------------------------------
# Prompt template definitions  (name, version, content, system, description)
# Later versions intentionally produce slightly better quality metrics.
# ---------------------------------------------------------------------------

TEMPLATES = [
    # ---- summarizer ----
    {
        "name": "summarizer",
        "version": 1,
        "content": "Summarize the following text:\n\n{text}",
        "system_prompt": "You are a helpful assistant.",
        "description": "Initial version — basic summarization",
    },
    {
        "name": "summarizer",
        "version": 2,
        "content": (
            "Please provide a concise summary of the following text in 2-3 sentences, "
            "focusing on the key points:\n\n{text}"
        ),
        "system_prompt": "You are an expert summarizer. Be concise and accurate.",
        "description": "v2 — added length constraint and focus instruction",
    },
    {
        "name": "summarizer",
        "version": 3,
        "content": (
            "Summarize the text below in exactly 3 bullet points. "
            "Each bullet should be one sentence.\n\nText:\n{text}"
        ),
        "system_prompt": "You are an expert summarizer. Return only the bullet points, no preamble.",
        "description": "v3 — structured bullet output for better parseability",
    },
    # ---- code-reviewer ----
    {
        "name": "code-reviewer",
        "version": 1,
        "content": "Review this {language} code:\n\n{code}",
        "system_prompt": "You are a code reviewer.",
        "description": "Initial version",
    },
    {
        "name": "code-reviewer",
        "version": 2,
        "content": (
            "Review the following {language} code for correctness, readability, and performance. "
            "List issues as: [SEVERITY] description\n\n```{language}\n{code}\n```"
        ),
        "system_prompt": (
            "You are a senior software engineer performing a code review. "
            "Be specific, actionable, and concise."
        ),
        "description": "v2 — added severity labels and code block formatting",
    },
    # ---- qa-assistant ----
    {
        "name": "qa-assistant",
        "version": 1,
        "content": "Answer this question: {question}",
        "system_prompt": None,
        "description": "Initial version — minimal prompt",
    },
    {
        "name": "qa-assistant",
        "version": 2,
        "content": (
            "Answer the following question clearly and concisely. "
            "If you are unsure, say so.\n\nQuestion: {question}"
        ),
        "system_prompt": "You are a knowledgeable and honest assistant.",
        "description": "v2 — added uncertainty acknowledgement instruction",
    },
]

SAMPLE_PROMPTS = [
    "What is the capital of France?",
    "Explain quantum entanglement in simple terms.",
    "Write a Python function to compute Fibonacci numbers efficiently.",
    "What are the key benefits of async programming in Python?",
    "Summarize the history of machine learning in 3 sentences.",
    "How does the Transformer architecture work?",
    "What is the difference between RAG and fine-tuning an LLM?",
    "Explain the SOLID principles with examples.",
    "What is LangChain used for?",
    "How do you optimise a slow SQL query?",
    "What is the CAP theorem?",
    "Describe the difference between precision and recall.",
    "What is gradient descent?",
    "How does HTTPS work?",
    "What is a vector database and when would you use one?",
]

SAMPLE_RESPONSES = [
    "Paris is the capital of France.",
    "Quantum entanglement is a phenomenon where two particles become correlated "
    "such that measuring one instantly influences the other, regardless of distance.",
    "def fib(n, memo={}):\n    if n <= 1: return n\n    if n in memo: return memo[n]\n"
    "    memo[n] = fib(n-1, memo) + fib(n-2, memo)\n    return memo[n]",
    "Async programming allows multiple tasks to run concurrently without blocking "
    "the main thread, improving throughput for I/O-bound workloads.",
    "Machine learning has evolved from early perceptrons in the 1950s through the "
    "deep learning revolution of the 2010s to today's large language models.",
    "The Transformer uses self-attention to weigh token relationships in parallel, "
    "enabling efficient training on long sequences without recurrent connections.",
    "RAG retrieves relevant documents at inference time; fine-tuning bakes new "
    "knowledge into model weights during training.",
    "SOLID stands for Single Responsibility, Open/Closed, Liskov Substitution, "
    "Interface Segregation, and Dependency Inversion.",
    "LangChain is a framework for building LLM-powered applications by chaining "
    "prompts, tools, memory, and retrieval components.",
    "Optimise slow SQL queries by adding indexes on filter columns, avoiding "
    "SELECT *, using EXPLAIN to inspect query plans, and batching writes.",
]

ERROR_MESSAGES = [
    "anthropic.RateLimitError: Rate limit exceeded. Please retry after 60 seconds.",
    "anthropic.APITimeoutError: Request timed out after 30 seconds.",
    "anthropic.APIConnectionError: Failed to connect to the Anthropic API.",
    "anthropic.BadRequestError: Invalid model specified.",
]

NUM_RECORDS = 500
WINDOW_HOURS = 24
ERROR_RATE = 0.03
SPIKE_RATE = 0.02
FEEDBACK_RATE = 0.30
# Fraction of requests that reference a template
TEMPLATE_RATE = 0.60

# Later template versions get slightly better feedback scores (simulate improvement)
VERSION_FEEDBACK_BOOST = {1: 0.0, 2: 0.05, 3: 0.10}


async def seed() -> None:
    print("Initialising database …")
    await init_db()

    now = datetime.now(timezone.utc)

    # ---- 1. Upsert prompt templates ----------------------------------- #
    print("Seeding prompt templates …")
    template_map: dict[tuple, int] = {}  # (name, version) → id

    async with AsyncSessionLocal() as db:
        for tpl_def in TEMPLATES:
            # Check if this (name, version) already exists
            from sqlalchemy import select
            result = await db.execute(
                select(PromptTemplate).where(
                    PromptTemplate.name == tpl_def["name"],
                    PromptTemplate.version == tpl_def["version"],
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                template_map[(tpl_def["name"], tpl_def["version"])] = existing.id
                continue

            tpl = PromptTemplate(
                name=tpl_def["name"],
                version=tpl_def["version"],
                content=tpl_def["content"],
                system_prompt=tpl_def["system_prompt"],
                description=tpl_def["description"],
            )
            db.add(tpl)
            await db.flush()  # get id before commit
            template_map[(tpl_def["name"], tpl_def["version"])] = tpl.id

        await db.commit()

    print(f"  {len(TEMPLATES)} template versions ready.")

    # Build a list of (name, version, template_id) for random assignment
    template_choices = list(template_map.items())  # [(name,ver), id]
    # Weight toward later versions being more common (simulate adoption curve)
    template_weights = []
    for (name, ver), _ in template_choices:
        max_ver = max(v for (n, v) in template_map if n == name)
        template_weights.append(1 + ver / max_ver)

    # ---- 2. Generate request records ---------------------------------- #
    print("Seeding request records …")
    rows: list[LLMRequest] = []

    for i in range(NUM_RECORDS):
        hours_ago = random.uniform(0, WINDOW_HOURS)
        timestamp = now - timedelta(hours=hours_ago)

        model = random.choices(MODELS, weights=[0.55, 0.35, 0.10])[0]
        is_error = random.random() < ERROR_RATE

        # Latency
        if is_error:
            latency_ms = None
        else:
            mu, sigma = MODEL_LATENCY_PARAMS[model]
            latency_ms = math.exp(random.gauss(mu, sigma))
            if random.random() < SPIKE_RATE:
                latency_ms *= random.uniform(3.0, 8.0)

        # Tokens
        prompt_tokens = random.randint(30, 400)
        completion_tokens = 0 if is_error else random.randint(20, 600)
        total_tokens = prompt_tokens + completion_tokens
        estimated_cost = calculate_cost(model, prompt_tokens, completion_tokens)

        # Template assignment
        tpl_id = tpl_name = tpl_version = None
        if random.random() < TEMPLATE_RATE and template_choices:
            (tpl_name, tpl_version), tpl_id = random.choices(
                template_choices, weights=template_weights
            )[0], template_map[
                random.choices(template_choices, weights=template_weights)[0][0]
            ]
            # Re-draw consistently
            choice_idx = random.choices(
                range(len(template_choices)), weights=template_weights
            )[0]
            (tpl_name, tpl_version), tpl_id = (
                template_choices[choice_idx][0],
                template_choices[choice_idx][1],
            )

        # Feedback — later versions score slightly higher
        has_feedback = not is_error and random.random() < FEEDBACK_RATE
        if has_feedback:
            base_score = random.choice([0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0])
            boost = VERSION_FEEDBACK_BOOST.get(tpl_version or 0, 0.0)
            feedback_score: float | None = min(1.0, base_score + boost)
        else:
            feedback_score = None

        response = None if is_error else random.choice(SAMPLE_RESPONSES)
        rows.append(
            LLMRequest(
                timestamp=timestamp,
                prompt=random.choice(SAMPLE_PROMPTS),
                response=response,
                model_name=model,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost=estimated_cost,
                error=random.choice(ERROR_MESSAGES) if is_error else None,
                is_error=is_error,
                trace_id=None,
                feedback_score=feedback_score,
                response_length=len(response) if response else 0,
                prompt_template_id=tpl_id,
                prompt_template_name=tpl_name,
                prompt_template_version=tpl_version,
                prompt_variables=None,
            )
        )

    async with AsyncSessionLocal() as db:
        db.add_all(rows)
        await db.commit()

    errors = sum(1 for r in rows if r.is_error)
    with_template = sum(1 for r in rows if r.prompt_template_name)
    total_cost = sum(r.estimated_cost for r in rows if r.estimated_cost)

    print(f"[OK] Seeded {NUM_RECORDS} request records:")
    print(f"   With template : {with_template} ({with_template / NUM_RECORDS * 100:.0f}%)")
    print(f"   Errors        : {errors} ({errors / NUM_RECORDS * 100:.1f}%)")
    print(f"   Total cost    : ${total_cost:.4f}")
    print(f"\nStart the dashboard:")
    print(f"   streamlit run llm_observability/dashboard/app.py")
    print(f"\nCompare template versions:")
    print(f"   curl http://localhost:8000/api/v1/prompts/summarizer/compare")


if __name__ == "__main__":
    asyncio.run(seed())
