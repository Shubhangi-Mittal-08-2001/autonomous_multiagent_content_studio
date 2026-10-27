import os
import logging
from time import perf_counter

from dotenv import load_dotenv
from openai import APITimeoutError, OpenAI
from observability import observe

load_dotenv()

# These are LiteLLM proxy model aliases, not provider/model identifiers. Changing
# a provider only requires updating the proxy config; aliases can also be replaced
# through environment variables without changing workflow nodes.
SIMPLE_MODEL_ALIAS = os.getenv("LITELLM_SIMPLE_MODEL_ALIAS", "simple-tier")
COMPLEX_MODEL_ALIAS = os.getenv("LITELLM_COMPLEX_MODEL_ALIAS", "complex-tier")
# Quality review uses the stronger tier by default, independently of the tier
# selected for draft generation. Deployments may override it explicitly.
REVIEW_MODEL_ALIAS = os.getenv("LITELLM_REVIEW_MODEL_ALIAS", COMPLEX_MODEL_ALIAS)
LLM_CALL_TIMEOUT_SECONDS = float(os.getenv("LLM_CALL_TIMEOUT_SECONDS", "60"))
if LLM_CALL_TIMEOUT_SECONDS <= 0:
    raise ValueError("LLM_CALL_TIMEOUT_SECONDS must be greater than zero.")

logger = logging.getLogger(__name__)

client = OpenAI(
    base_url="http://localhost:4000/v1",
    api_key="dummy-key",
    timeout=LLM_CALL_TIMEOUT_SECONDS,
    max_retries=0,
)


@observe(name="llm.chat.completions", as_type="generation")
def invoke_llm(
    model: str,
    prompt: str,
    *,
    json_mode: bool = False,
    max_completion_tokens: int | None = None,
) -> str:
    """Send a prompt through LiteLLM, optionally requesting JSON output."""
    started_at = perf_counter()
    logger.info(
        "LLM call started model=%s json_mode=%s timeout_seconds=%s prompt_chars=%d",
        model,
        json_mode,
        LLM_CALL_TIMEOUT_SECONDS,
        len(prompt),
    )
    request: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if json_mode:
        request["response_format"] = {"type": "json_object"}
    budget_parameter = (
        "max_tokens" if model == SIMPLE_MODEL_ALIAS else "max_completion_tokens"
    )
    if max_completion_tokens is not None:
        if max_completion_tokens < 1:
            raise ValueError("max_completion_tokens must be a positive integer.")
        request[budget_parameter] = max_completion_tokens
    try:
        response = client.chat.completions.create(**request)
    except APITimeoutError as exc:
        elapsed = perf_counter() - started_at
        logger.exception(
            "LLM call timed out model=%s elapsed_seconds=%.2f",
            model,
            elapsed,
        )
        raise TimeoutError(
            f"LLM call for model '{model}' timed out after {elapsed:.1f} seconds."
        ) from exc
    except Exception:
        logger.exception(
            "LLM call failed model=%s elapsed_seconds=%.2f",
            model,
            perf_counter() - started_at,
        )
        raise

    # A request-specific output budget limits unnecessary verbosity. If a valid
    # completion reaches the cap, retry with a larger budget (up to 8,192 tokens)
    # to avoid returning truncated JSON or a partial platform draft.
    choice = response.choices[0]
    retry_budget = max_completion_tokens or 0
    while (
        retry_budget > 0
        and choice.finish_reason == "length"
        and retry_budget < 8192
    ):
        retry_budget = min(retry_budget * 2, 8192)
        logger.warning(
            "LLM output reached token budget model=%s retry_budget=%d",
            model,
            retry_budget,
        )
        request[budget_parameter] = retry_budget
        try:
            response = client.chat.completions.create(**request)
        except APITimeoutError as exc:
            elapsed = perf_counter() - started_at
            logger.exception(
                "LLM retry timed out model=%s elapsed_seconds=%.2f",
                model,
                elapsed,
            )
            raise TimeoutError(
                f"LLM call for model '{model}' timed out after {elapsed:.1f} seconds."
            ) from exc
        choice = response.choices[0]

    result = choice.message.content or ""
    logger.info(
        "LLM call completed model=%s elapsed_seconds=%.2f response_chars=%d",
        model,
        perf_counter() - started_at,
        len(result),
    )
    return result
