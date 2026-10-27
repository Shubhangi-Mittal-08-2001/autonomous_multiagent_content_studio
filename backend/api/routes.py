# Purpose: Defines the intended API route responsibilities.

import logging
import re

from fastapi import APIRouter, HTTPException

from config.complexity import assess_complexity
from config.guardrails import (
    check_generated_content,
    check_user_content,
    generate_refusal_message,
)
from config.llm import COMPLEX_MODEL_ALIAS, SIMPLE_MODEL_ALIAS
from graph.routing import PLATFORM_NODES
from schemas.content import ContentRequest, ContentResponse
from observability import observe

router = APIRouter()
logger = logging.getLogger(__name__)

# Allow one review-led refinement after the initial draft pass.
MAX_REFINEMENT_ITERATIONS = 1
MODEL_MAP = {
    "simple": SIMPLE_MODEL_ALIAS,
    "complex": COMPLEX_MODEL_ALIAS,
}
PLATFORM_LABELS = {
    "linkedin": "LinkedIn",
    "x": "X",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "facebook": "Facebook",
}


def _brief_audience(content: str) -> str | None:
    """Read a plainly labeled audience from the source brief, when present."""
    match = re.search(r"(?im)^\s*(?:target\s+)?audience\s*:\s*(.+?)\s*$", content)
    return match.group(1).strip() if match else None


def _brief_platforms(content: str) -> list[str]:
    """Find platform scope explicitly requested in the source brief."""
    keys = list(PLATFORM_LABELS)
    normalized = content.casefold()
    names = [key for key in keys if re.search(rf"(?<![\w]){re.escape(key)}(?![\w])", normalized)]
    asks_all = bool(re.search(
        r"\b(?:all\s+(?:five\s+)?(?:social\s+media\s+)?platforms|all\s+five\s+outputs|"
        r"for\s+each\s+(?:platform|agent)|instructions\s+for\s+each\s+agent|"
        r"each\s+of\s+the\s+five\s+(?:platforms|agents)|all\s+five\s+agents)\b", normalized
    ))
    if asks_all:
        return keys
    explicit_multi_request = bool(re.search(
        r"\b(?:create|write|draft|generate|prepare|produce)\b.{0,80}"
        r"\b(?:posts?|content|drafts?)\b.{0,80}\b(?:for|on|across)\b", normalized
    ))
    return names if explicit_multi_request and len(names) > 1 else []


def _natural_join(items: list[str]) -> str:
    """Join short user-facing labels without exposing internal plan terminology."""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _build_manager_message(
    final_state: dict,
    *,
    content: str = "",
    selected_platforms: list[str] | None = None,
    selected_audience: str | None = None,
    audience_was_selected: bool = False,
) -> str:
    """Summarize completed drafts using manager findings and final platform results."""
    plan = final_state.get("current_plan", {})
    if not isinstance(plan, dict):
        plan = {}
    if plan.get("request_status") == "clarification_required":
        clarification = plan.get("clarification_message")
        return clarification.strip() if isinstance(clarification, str) else ""

    processed_content = final_state.get("processed_content", [])
    platform_names = [
        PLATFORM_LABELS.get(item["platform"].strip().lower(), item["platform"].strip())
        for item in processed_content
        if isinstance(item, dict)
        and isinstance(item.get("platform"), str)
        and item["platform"].strip()
    ]
    if platform_names:
        quantity = "drafts are" if len(platform_names) != 1 else "draft is"
        opening = f"Your {_natural_join(platform_names)} {quantity} ready."
    else:
        opening = "Your drafts are ready."

    missing_details = plan.get("missing_details", [])
    unavailable_details = plan.get("unavailable_details", [])
    if not isinstance(missing_details, list):
        missing_details = []
    if not isinstance(unavailable_details, list):
        unavailable_details = []
    missing_details = [
        item.strip() for item in missing_details if isinstance(item, str) and item.strip()
    ]
    unavailable_details = [
        item.strip() for item in unavailable_details if isinstance(item, str) and item.strip()
    ]
    notes: list[str] = []
    if missing_details:
        notes.append(f"I left out the {_natural_join(missing_details)} because those details weren't provided. Share them and regenerate for a more specific draft.")
    if unavailable_details:
        notes.append(f"I left out the {_natural_join(unavailable_details)} because they aren't available yet. You can add them when available and regenerate.")
    selected_platforms = selected_platforms or [
        item["platform"] for item in processed_content
        if isinstance(item, dict) and isinstance(item.get("platform"), str)
    ]
    requested_platforms = _brief_platforms(content)
    selected_keys = {name.strip().lower() for name in selected_platforms}
    platform_mismatch = plan.get("platform_scope_mismatch") is True or bool(
        requested_platforms and set(requested_platforms) - selected_keys
    )
    if platform_mismatch:
        if requested_platforms:
            requested_labels = [PLATFORM_LABELS[name] for name in requested_platforms]
            selected_labels = [PLATFORM_LABELS.get(name.lower(), name) for name in selected_platforms]
            notes.append(
                f"Your brief asks for {_natural_join(requested_labels)}, but you selected "
                f"{_natural_join(selected_labels)}. I created drafts only for the selected platform(s). "
                "Select the other platforms to create their drafts too."
            )
        else:
            notes.append(
                "Your request mentions additional platforms, but only the selected ones were processed. "
                "Select the others to generate drafts for them."
            )

    brief_audience = _brief_audience(content)
    if audience_was_selected and brief_audience and selected_audience:
        if " ".join(brief_audience.casefold().split()) != " ".join(selected_audience.casefold().split()):
            notes.append(
                f'The audience you selected is "{selected_audience}", while the brief says "{brief_audience}". '
                "I used your selected audience for this draft; align the audience details and regenerate if needed."
            )
    if not notes:
        return f"{opening} You can refine the details and regenerate anytime."
    return f"{opening} {' '.join(notes)}"


@router.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return a simple status response indicating that the API is running."""
    return {
        "status": "healthy",
        "message": "The API is running and healthy."
        }


@router.post("/content/generate", response_model=ContentResponse, tags=["content"])
@observe(name="content.generate")
def generate_content(request: ContentRequest) -> ContentResponse:
    """Run the manager-led graph and return its final platform drafts."""
    if not request.content.strip():
        raise HTTPException(status_code=422, detail="Content must not be empty.")
    safety = check_user_content(request.content)
    if not safety.allowed:
        logger.info("Rejected content request by safety guardrail: %s", safety.reason)
        refusal = generate_refusal_message(
            content=request.content,
            direction="input",
            reason=safety.reason,
        )
        return ContentResponse(message=refusal)
    platforms = [platform.strip() for platform in request.platforms]
    if not platforms or any(not platform for platform in platforms):
        raise HTTPException(status_code=422, detail="At least one platform must be requested.")
    unsupported = [
        platform for platform in platforms if platform.lower() not in PLATFORM_NODES
    ]
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported platform(s): {', '.join(unsupported)}.",
        )

    if len(platforms) > 1:
        # Multi-platform requests always use the complex tier. Skip the classifier,
        # whose result would otherwise be upgraded from simple to complex anyway.
        complexity = "complex"
        logger.info(
            "Skipping complexity classification for multi-platform workflow platform_count=%d",
            len(platforms),
        )
    else:
        try:
            complexity = assess_complexity(request.content)
        except TimeoutError as exc:
            logger.exception("Request complexity assessment timed out")
            raise HTTPException(
                status_code=504,
                detail="We couldn’t understand your request in time. Please try again.",
            ) from exc
        except Exception as exc:
            logger.exception("Request complexity assessment failed")
            raise HTTPException(
                status_code=503,
                detail="We’re having trouble preparing your request right now. Please try again shortly.",
            ) from exc
    model_name = MODEL_MAP[complexity]
    logger.info("Selected model tier=%s complexity=%s", model_name, complexity)

    # Initialize every workflow channel so each node starts with a predictable state.
    initial_state = {
        "content": request.content,
        "platforms": platforms,
        "audience": (
            request.audience
            if "audience" in request.model_fields_set
            else (_brief_audience(request.content) or request.audience)
        ),
        "llm_model": model_name,
        "current_plan": {},
        "manager_note": "",
        "node_plans": [],
        "current_step": "manager",
        "execution_history": [],
        "latest_results": {},
        "quality_score": 0.0,
        "quality_threshold": 0.8,
        "review_history": [],
        "review_feedback": {},
        "platform_status": {},
        "replan_required": False,
        "replan_count": 0,
        "max_iterations": MAX_REFINEMENT_ITERATIONS,
        "iteration_count": 0,
        "processed_content": [],
        "task_completed": False,
        "task_failed": False,
        "error_message": "",
    }

    logger.info("Starting content workflow for platforms=%s", platforms)
    try:
        # The graph is compiled during application startup and is cached by Python.
        from graph.builder import app_graph

        final_state = app_graph.invoke(initial_state)
    except TimeoutError as exc:
        logger.exception("Content workflow LLM call timed out for platforms=%s", platforms)
        raise HTTPException(
            status_code=504,
            detail="We couldn’t finish creating your content in time. Please try again.",
        ) from exc
    except Exception as exc:
        logger.exception("Content workflow failed for platforms=%s", platforms)
        raise HTTPException(
            status_code=500,
            detail="We couldn’t create your content right now. Please try again shortly.",
        ) from exc

    processed_content = final_state.get("processed_content", [])
    plan = final_state.get("current_plan", {})
    request_status = plan.get("request_status") if isinstance(plan, dict) else None
    if (
        final_state.get("task_completed")
        and not processed_content
        and request_status == "clarification_required"
    ):
        clarification = plan.get("clarification_message", "")
        if isinstance(clarification, str) and clarification.strip():
            return ContentResponse(message=clarification.strip())
    if not final_state.get("task_completed") or not processed_content:
        logger.error("Content workflow ended without a completed result")
        raise HTTPException(
            status_code=500,
            detail="We couldn’t create your content right now. Please try again shortly.",
        )

    for item in processed_content:
        draft = item.get("processed_content", "") if isinstance(item, dict) else ""
        safety = check_generated_content(draft) if isinstance(draft, str) else None
        if safety is None or not safety.allowed:
            reason = safety.reason if safety else "invalid generated content"
            logger.warning("Blocked unsafe generated content before API response: %s", reason)
            refusal = generate_refusal_message(
                content=draft if isinstance(draft, str) else "",
                direction="output",
                reason=reason,
            )
            return ContentResponse(message=refusal)

    logger.info("Content workflow completed with %d platform result(s)", len(processed_content))
    return ContentResponse(
        processed_content=processed_content,
        message=_build_manager_message(
            final_state,
            content=request.content,
            selected_platforms=platforms,
            selected_audience=request.audience,
            audience_was_selected="audience" in request.model_fields_set,
        ),
    )
