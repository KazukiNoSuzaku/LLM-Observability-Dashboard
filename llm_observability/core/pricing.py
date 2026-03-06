"""Token-based cost estimation for supported LLM models.

Pricing is in USD per 1,000,000 tokens (input, output).
Sources: Anthropic and OpenAI pricing pages (February 2026).
"""

from typing import Dict, Tuple

# (input_usd_per_1m_tokens, output_usd_per_1m_tokens)
MODEL_PRICING: Dict[str, Tuple[float, float]] = {
    # ------------------------------------------------------------------ #
    # Anthropic — Claude 4.x family
    # ------------------------------------------------------------------ #
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.25, 1.25),
    # ------------------------------------------------------------------ #
    # Anthropic — Claude 3.x family
    # ------------------------------------------------------------------ #
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    "claude-3-sonnet-20240229": (3.00, 15.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
    # ------------------------------------------------------------------ #
    # OpenAI — GPT-4o family
    # ------------------------------------------------------------------ #
    "gpt-4o": (5.00, 15.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o3-mini": (1.10, 4.40),
    # ------------------------------------------------------------------ #
    # Google — Gemini family
    # ------------------------------------------------------------------ #
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
}

# Fallback pricing when the model is not in the table
_DEFAULT_PRICING: Tuple[float, float] = (3.00, 15.00)


def calculate_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Return estimated cost in USD for a single LLM request.

    Args:
        model_name: Model identifier string (must match a key in MODEL_PRICING).
        prompt_tokens: Number of input/prompt tokens consumed.
        completion_tokens: Number of output/completion tokens generated.

    Returns:
        Estimated cost in USD, rounded to 8 decimal places.
    """
    input_price, output_price = MODEL_PRICING.get(model_name, _DEFAULT_PRICING)
    cost = (prompt_tokens * input_price / 1_000_000) + (
        completion_tokens * output_price / 1_000_000
    )
    return round(cost, 8)


def get_supported_models() -> list[str]:
    """Return a sorted list of all models with known pricing."""
    return sorted(MODEL_PRICING.keys())
