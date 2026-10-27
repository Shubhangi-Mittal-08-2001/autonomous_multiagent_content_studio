"""Shared helpers for platform content agents."""

import json
import logging
from typing import Any

from observability import get_client

logger = logging.getLogger(__name__)


def get_content_prompt(
    platform: str,
    platform_guidance: str,
    audience: str,
    source: str,
    task: str,
    is_refinement: bool = False,
    feedback: str | None = None,
    existing_draft: str | None = None,
) -> str:
    """Fetch and compile the platform content prompt managed in Langfuse."""
    prompt = get_client().get_prompt(
        "common_implementation",
        type="text",
        label="production",
    )
    return prompt.compile(
        platform=platform,
        platform_guidance=platform_guidance,
        audience=audience,
        source=source,
        task=task,
        is_refinement=str(is_refinement),
        feedback=feedback or "None; create the initial draft.",
        existing_draft=existing_draft or "None; create the initial draft.",
    )


def parse_json_object(
    response: Any,
    *,
    description: str,
    required_key: str | None = None,
) -> dict[str, Any]:
    """Decode a JSON object from model output, including fenced or prefaced JSON.

    Providers differ in how closely they follow JSON-only instructions. Extracting
    the first balanced object here keeps structured-output handling independent of
    the configured model/provider.
    """
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    if not isinstance(content, str):
        raise ValueError(f"The {description} response must contain a JSON object.")

    incomplete_object = False
    for start, char in enumerate(content):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(content)):
            char = content[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        result = json.loads(content[start : index + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(result, dict) and (
                        required_key is None or required_key in result
                    ):
                        return result
                    break
        else:
            incomplete_object = True

    if incomplete_object:
        raise ValueError(f"The {description} response contained an incomplete JSON object.")
    if required_key:
        raise ValueError(
            f"The {description} response did not contain a JSON object with '{required_key}'."
        )
    raise ValueError(f"The {description} response did not contain a valid JSON object.")


def invoke_text(
    prompt: str,
    llm: Any = None,
    model_name: str | None = None,
    json_mode: bool = False,
    max_completion_tokens: int | None = None,
) -> str:
    """Invoke the configured chat model and require a non-empty text response."""
    try:
        if llm is None:
            from config.llm import COMPLEX_MODEL_ALIAS, invoke_llm

            response = invoke_llm(
                model_name or COMPLEX_MODEL_ALIAS,
                prompt,
                json_mode=json_mode,
                max_completion_tokens=max_completion_tokens,
            )
        else:
            response = llm.invoke(prompt)
    except Exception:
        logger.exception("Content agent LLM invocation failed")
        raise

    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The content agent model response must contain non-empty text.")
    return content.strip()


def platform_mapping(value: Any) -> dict[str, Any]:
    """Normalize dictionary keys so platform lookups are case-insensitive."""
    if not isinstance(value, dict):
        return {}
    return {str(key).strip().lower(): item for key, item in value.items()}


def platform_task(state: dict[str, Any], platform: str) -> dict[str, Any]:
    """Find this platform's task in the manager's current plan."""
    plan = state.get("current_plan")
    tasks = plan.get("platform_tasks", []) if isinstance(plan, dict) else []
    if not tasks:
        tasks = state.get("node_plans", [])

    task = next(
        (
            item
            for item in tasks
            if isinstance(item, dict)
            and str(item.get("platform", "")).strip().lower() == platform.lower()
        ),
        None,
    )
    if task is None:
        raise ValueError(f"The manager plan does not include a task for {platform}.")
    return task


def latest_draft(state: dict[str, Any], platform: str) -> Any:
    """Return the saved result for a platform, if one exists."""
    result = platform_mapping(state.get("latest_results", {})).get(platform.lower())
    if isinstance(result, dict):
        return (
            result.get("processed_content")
            or result.get("content")
            or result.get("draft")
        )
    return result


def generate_platform_draft(
    state: dict[str, Any],
    platform: str,
    platform_guidance: str,
    llm: Any = None,
) -> dict[str, Any]:
    """Create or refine one platform draft using its delegated plan."""
    source = state.get("content")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Platform content generation requires non-empty source content.")

    task = platform_task(state, platform)
    plan = state.get("current_plan")
    plan = plan if isinstance(plan, dict) else {}
    feedback = task.get("review_feedback")
    if not isinstance(feedback, str) or not feedback.strip():
        feedback = platform_mapping(state.get("review_feedback", {})).get(platform.lower(), "")
    existing_draft = latest_draft(state, platform)
    is_refinement = bool(plan.get("is_refinement", state.get("replan_required", False)))
    audience = state.get("audience") or "general"

    # Log workflow metadata only; source text, prompts, feedback, and draft content stay private.
    logger.debug(
        "Preparing platform prompt platform=%s refinement=%s iteration=%s",
        platform,
        is_refinement,
        state.get("iteration_count", 0),
    )

    prompt = get_content_prompt(
        platform=platform,
        platform_guidance=platform_guidance,
        audience=audience,
        source=source,
        task=str(task),
        is_refinement=is_refinement,
        feedback=feedback,
        existing_draft=str(existing_draft) if existing_draft is not None else None,
    )
    logger.info("prompt successfully fetched from langfuse")
    logger.debug("Invoking content model platform=%s", platform)
    # Keep expected output sizes bounded by platform while allowing a larger
    # recovery budget inside invoke_llm if the provider reports truncation.
    completion_budgets = {
        "x": 700,
        "facebook": 1100,
        "linkedin": 1400,
        "instagram": 1800,
        "youtube": 2600,
    }
    draft = invoke_text(
        prompt,
        llm,
        state.get("llm_model"),
        max_completion_tokens=completion_budgets.get(platform.lower(), 1800),
    )
    logger.info("Content model returned a draft platform=%s characters=%d", platform, len(draft))
    iteration = state.get("iteration_count", 0)
    result = {
        "platform": platform,
        "processed_content": draft,
        "iteration": iteration,
        "is_refinement": is_refinement,
    }
    logger.debug("Prepared platform state update platform=%s iteration=%s", platform, iteration)
    return {
        "latest_results": {platform.lower(): result},
        "execution_history": [result],
        "current_step": f"{platform}_drafted",
    }
