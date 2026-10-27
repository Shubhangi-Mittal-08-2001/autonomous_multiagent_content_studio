"""LLM-based request complexity assessment through the LiteLLM proxy."""

import logging

from config.llm import COMPLEX_MODEL_ALIAS, SIMPLE_MODEL_ALIAS, invoke_llm
from observability import get_client

logger = logging.getLogger(__name__)

def assess_complexity(query: str) -> str:
    """Ask the local model to classify query content as simple or complex."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Complexity assessment requires non-empty request content.")

    complexity_prompt = get_client().get_prompt(
        "complexity_prompt",
        type="text",
        label="production",
    )
    logger.info("Successfully fetched prompt from Langfuse name=complexity_prompt")
    prompt = complexity_prompt.compile(content=query.strip())
    try:
        classification = invoke_llm(
            SIMPLE_MODEL_ALIAS,
            prompt,
            max_completion_tokens=8,
        ).strip().lower()
        if classification not in {"simple", "complex"}:
            raise ValueError("Simple-tier classifier returned an invalid label.")
    except Exception as simple_error:
        logger.warning(
            "Simple-tier classification failed (%s); retrying with complex-tier",
            type(simple_error).__name__,
        )
        classification = invoke_llm(
            COMPLEX_MODEL_ALIAS,
            prompt,
            max_completion_tokens=8,
        ).strip().lower()
        if classification not in {"simple", "complex"}:
            logger.error("Complex-tier fallback returned an invalid classification label")
            raise ValueError(
                "Complexity classifier must return exactly 'simple' or 'complex'."
            ) from simple_error
    logger.info("Request complexity classified as %s", classification)
    return classification
