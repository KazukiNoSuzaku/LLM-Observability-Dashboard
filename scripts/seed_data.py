"""Seed the database with 500 synthetic LLM request records.

Generates realistic distributions of:
  - Latency (log-normal, model-dependent)
  - Token counts
  - Cost
  - Error rate (~3 %)
  - Feedback scores (sparse)

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

# Make the project root importable when running as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_observability.core.pricing import calculate_cost
from llm_observability.db.database import AsyncSessionLocal, init_db
from llm_observability.db.models import LLMRequest

# ---------------------------------------------------------------------------
# Synthetic data configuration
# ---------------------------------------------------------------------------

MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
]

# (mu, sigma) for log-normal latency distribution in milliseconds
# log-normal: median ≈ exp(mu), so mu=6.5 → ~660ms, mu=7.0 → ~1100ms
MODEL_LATENCY_PARAMS = {
    "claude-haiku-4-5-20251001": (6.5, 0.35),   # fast ~660ms
    "claude-sonnet-4-6":         (7.0, 0.40),   # mid  ~1100ms
    "claude-opus-4-6":           (7.5, 0.45),   # slow ~1800ms
}

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
    "Explain the difference between a thread and a process.",
    "What is prompt injection?",
    "How do you prevent SQL injection?",
    "What is a microservices architecture?",
    "Describe the MapReduce programming model.",
]

SAMPLE_RESPONSES = [
    "Paris is the capital of France.",
    "Quantum entanglement is a phenomenon where two particles become correlated "
    "such that measuring one instantly influences the other, regardless of distance.",
    "def fib(n, memo={}):\n    if n <= 1: return n\n    if n in memo: return memo[n]\n"
    "    memo[n] = fib(n-1) + fib(n-2)\n    return memo[n]",
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
    "SELECT *, using query plan analysis (EXPLAIN), and batching writes.",
]

ERROR_MESSAGES = [
    "anthropic.RateLimitError: Rate limit exceeded. Please retry after 60 seconds.",
    "anthropic.APITimeoutError: Request timed out after 30 seconds.",
    "anthropic.APIConnectionError: Failed to connect to the Anthropic API.",
    "anthropic.BadRequestError: Invalid model specified.",
]

NUM_RECORDS = 500
WINDOW_HOURS = 24
ERROR_RATE = 0.03       # 3 % of requests error
SPIKE_RATE = 0.02       # 2 % of requests have anomalously high latency
FEEDBACK_RATE = 0.25    # 25 % of successful requests have a feedback score


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------


async def seed() -> None:
    print(f"Initialising database …")
    await init_db()

    now = datetime.now(timezone.utc)
    rows: list[LLMRequest] = []

    for i in range(NUM_RECORDS):
        hours_ago = random.uniform(0, WINDOW_HOURS)
        timestamp = now - timedelta(hours=hours_ago)

        model = random.choices(
            MODELS,
            weights=[0.55, 0.35, 0.10],  # haiku most common
        )[0]

        is_error = random.random() < ERROR_RATE

        # Latency
        if is_error:
            latency_ms = None
        else:
            mu, sigma = MODEL_LATENCY_PARAMS[model]
            latency_ms = math.exp(random.gauss(mu, sigma))
            # Occasional spike
            if random.random() < SPIKE_RATE:
                latency_ms *= random.uniform(3.0, 8.0)

        # Token counts
        prompt_tokens = random.randint(30, 400)
        completion_tokens = 0 if is_error else random.randint(20, 600)
        total_tokens = prompt_tokens + completion_tokens

        estimated_cost = calculate_cost(model, prompt_tokens, completion_tokens)

        # Quality signals
        response = None if is_error else random.choice(SAMPLE_RESPONSES)
        feedback_score = (
            random.choice([0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0])
            if (not is_error and random.random() < FEEDBACK_RATE)
            else None
        )

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
            )
        )

    async with AsyncSessionLocal() as db:
        db.add_all(rows)
        await db.commit()

    errors = sum(1 for r in rows if r.is_error)
    total_cost = sum(r.estimated_cost for r in rows if r.estimated_cost)
    print(f"✅  Seeded {NUM_RECORDS} records:")
    print(f"   Models   : {', '.join(MODELS)}")
    print(f"   Errors   : {errors} ({errors / NUM_RECORDS * 100:.1f} %)")
    print(f"   Total cost: ${total_cost:.4f}")
    print(f"\nOpen the dashboard:")
    print(f"   streamlit run llm_observability/dashboard/app.py")


if __name__ == "__main__":
    asyncio.run(seed())
