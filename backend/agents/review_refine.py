"""Quality review and refinement-loop decisions for platform drafts."""

import json
import logging
from typing import Any

from agents.common_implementation import invoke_text, parse_json_object, platform_mapping
from agents.facebook_agent import FACEBOOK_GUIDANCE
from agents.instagram_agent import INSTAGRAM_GUIDANCE
from agents.linkedin_agent import LINKEDIN_GUIDANCE
from agents.x_agent import X_GUIDANCE
from agents.youtube_agent import YOUTUBE_GUIDANCE
from config.llm import REVIEW_MODEL_ALIAS
from observability import get_client

logger = logging.getLogger(__name__)

PLATFORM_GUIDANCE = {
    "facebook": FACEBOOK_GUIDANCE,
    "instagram": INSTAGRAM_GUIDANCE,
    "linkedin": LINKEDIN_GUIDANCE,
    "x": X_GUIDANCE,
    "youtube": YOUTUBE_GUIDANCE,
}


def _decode_reviews(response: Any) -> dict[str, Any]:
    """Parse reviewer output and require a list of per-platform reviews."""
    result = parse_json_object(
        response,
        description="reviewer",
        required_key="reviews",
    )
    if not isinstance(result.get("reviews"), list):
        raise ValueError("The reviewer response must include a reviews list.")
    return result


def _threshold_as_percent(value: Any) -> float:
    """Normalize a quality threshold from either a fraction or percentage."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        value = 0.8
    threshold = float(value)
    if 0 <= threshold <= 1:
        threshold *= 100
    if not 0 <= threshold <= 100:
        raise ValueError("quality_threshold must be between 0 and 1, or between 0 and 100.")
    return threshold


def _draft_text(result: Any) -> str | None:
    """Extract non-empty draft text from a stored result or raw string."""
    if isinstance(result, dict):
        draft = (
            result.get("processed_content")
            or result.get("content")
            or result.get("draft")
        )
    else:
        draft = result
    return draft if isinstance(draft, str) and draft.strip() else None


def review_refine_node(
    state: dict[str, Any],
    llm: Any = None,
) -> dict[str, Any]:
    """Review current platform drafts and decide whether to request refinement."""
    platforms = state.get("platforms", [])
    if not isinstance(platforms, list) or not platforms:
        raise ValueError("Review requires at least one requested platform.")
    requested_platforms = [
        platform.strip()
        for platform in platforms
        if isinstance(platform, str) and platform.strip()
    ]
    if not requested_platforms:
        raise ValueError("Review requires at least one non-empty platform name.")

    current_plan = state.get("current_plan")
    current_plan = current_plan if isinstance(current_plan, dict) else {}
    task_list = current_plan.get("platform_tasks", [])
    if not isinstance(task_list, list):
        raise ValueError("The current manager plan must contain platform_tasks.")
    if not task_list:
        task_list = state.get("node_plans", [])

    target_platforms = [
        str(task["platform"]).strip()
        for task in task_list
        if isinstance(task, dict)
        and isinstance(task.get("platform"), str)
        and task["platform"].strip()
    ]
    if not target_platforms:
        raise ValueError("Review requires platform tasks from the current manager plan.")
    requested_keys = {platform.lower() for platform in requested_platforms}
    unexpected = [
        platform for platform in target_platforms if platform.lower() not in requested_keys
    ]
    if unexpected:
        raise ValueError(
            "The current manager plan includes unrequested platforms: "
            + ", ".join(unexpected)
            + "."
        )
    if not current_plan.get("is_refinement") and {
        platform.lower() for platform in target_platforms
    } != requested_keys:
        raise ValueError("The initial manager plan must include every requested platform.")

    results = platform_mapping(state.get("latest_results", {}))
    review_drafts: list[dict[str, Any]] = []
    for platform in target_platforms:
        result = results.get(platform.lower())
        draft = _draft_text(result)
        if draft is None:
            raise ValueError(f"No generated draft is available to review for {platform}.")
        # The full platform plan is already passed once as `plan` below; repeating
        # each task beside its draft needlessly inflates review input tokens.
        review_drafts.append(
            {
                "platform": platform,
                "platform_guidance": PLATFORM_GUIDANCE.get(platform.lower(), ""),
                "draft": draft,
            }
        )

    threshold = _threshold_as_percent(state.get("quality_threshold", 0.8))
    review_prompt = get_client().get_prompt(
        "review_refine_prompt",
        type="text",
        label="production",
    )
    logger.info("Successfully fetched prompt from Langfuse name=review_refine_prompt")
    prompt = review_prompt.compile(
        source=state.get("content", ""),
        audience=state.get("audience") or "general",
        threshold=threshold,
        plan=json.dumps(current_plan, ensure_ascii=False, default=str),
        drafts=json.dumps(review_drafts, ensure_ascii=False, default=str),
    )
    # Drafts and feedback may contain user data, so log counts and platform names only.
    logger.info(
        "Starting review with model=%s for %d platform draft(s): %s",
        REVIEW_MODEL_ALIAS,
        len(review_drafts),
        ", ".join(target_platforms),
    )
    verdict = _decode_reviews(
        invoke_text(
            prompt,
            llm,
            REVIEW_MODEL_ALIAS,
            json_mode=True,
            max_completion_tokens=1800,
        )
    )
    reviews_by_platform = {
        str(item.get("platform", "")).strip().lower(): item
        for item in verdict["reviews"]
        if isinstance(item, dict) and isinstance(item.get("platform"), str)
    }

    statuses = platform_mapping(state.get("platform_status", {}))
    feedback_by_platform = platform_mapping(state.get("review_feedback", {}))
    rejection_reasons_by_platform: dict[str, list[str]] = {}
    round_scores: list[float] = []
    for platform in target_platforms:
        key = platform.lower()
        review = reviews_by_platform.get(key)
        if review is None:
            raise ValueError(f"The reviewer omitted the {platform} draft.")
        score = review.get("quality_score")
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not 0 <= score <= 100
        ):
            raise ValueError(f"The reviewer returned an invalid quality score for {platform}.")
        rejection_reasons = review.get("rejection_reasons", [])
        if not isinstance(rejection_reasons, list) or any(
            not isinstance(reason, str) for reason in rejection_reasons
        ):
            raise ValueError(
                f"The reviewer returned invalid rejection reasons for {platform}."
            )
        rejection_reasons = [reason.strip() for reason in rejection_reasons if reason.strip()]

        reviewer_approved = review.get("approved") is True
        score_passes_threshold = score >= threshold
        feedback = review.get("feedback")
        if not isinstance(feedback, str) or not feedback.strip():
            if reviewer_approved and score_passes_threshold and not rejection_reasons:
                feedback = "No changes required."
            elif rejection_reasons:
                feedback = " ".join(rejection_reasons)
            elif reviewer_approved:
                feedback = "Improve the draft to meet the quality approval threshold."
            else:
                feedback = (
                    "The review did not include a specific reason. Recheck factual "
                    "claims, required deliverables, and platform guidance; correct "
                    "any gaps before approval."
                )
        if reviewer_approved and rejection_reasons:
            logger.warning(
                "Reviewer marked %s approved but also supplied rejection reasons; treating as unapproved",
                platform,
            )
        approved = (
            reviewer_approved
            and score_passes_threshold
            and not rejection_reasons
        )
        if not reviewer_approved and not rejection_reasons:
            rejection_reasons = [feedback.strip()]
        if reviewer_approved and not score_passes_threshold:
            rejection_reasons.append(
                f"Score {score:g} is below the approval threshold {threshold:g}."
            )

        statuses[key] = "approved" if approved else "needs_refinement"
        feedback_by_platform[key] = feedback.strip()
        rejection_reasons_by_platform[key] = rejection_reasons
        round_scores.append(float(score))
        logger.info(
            "Review decision platform=%s score=%.1f threshold=%.1f "
            "score_passes_threshold=%s reviewer_approved=%s final_status=%s "
            "rejection_reasons=%s",
            platform,
            score,
            threshold,
            score_passes_threshold,
            reviewer_approved,
            statuses[key],
            [reason[:200] for reason in rejection_reasons],
        )

    completed_iteration = int(state.get("iteration_count", 0) or 0)
    if current_plan.get("is_refinement"):
        completed_iteration += 1
    has_unapproved = any(status != "approved" for status in statuses.values())
    max_iterations = max(0, int(state.get("max_iterations", 0) or 0))
    replan_required = has_unapproved and completed_iteration < max_iterations
    terminal = not replan_required
    latest_results = platform_mapping(state.get("latest_results", {}))
    overall_score = sum(round_scores) / len(round_scores)

    update: dict[str, Any] = {
        "quality_score": overall_score,
        "review_history": [
            {
                "iteration": completed_iteration,
                "quality_score": overall_score,
                "platform_status": {
                    platform: statuses[platform.lower()] for platform in target_platforms
                },
                "review_feedback": {
                    platform: feedback_by_platform[platform.lower()]
                    for platform in target_platforms
                },
                "rejection_reasons": {
                    platform: rejection_reasons_by_platform[platform.lower()]
                    for platform in target_platforms
                },
                "replan_required": replan_required,
            }
        ],
        "review_feedback": feedback_by_platform,
        "platform_status": statuses,
        "iteration_count": completed_iteration,
        "replan_required": replan_required,
        "task_completed": terminal,
        "task_failed": False,
        "current_step": "manager_refinement" if replan_required else "completed",
    }
    logger.info(
        "Review cycle finished; score=%.1f iteration=%d replan_required=%s",
        overall_score,
        completed_iteration,
        replan_required,
    )
    if terminal:
        processed_content: list[dict[str, str]] = []
        for platform in requested_platforms:
            result = latest_results.get(platform.lower())
            draft = _draft_text(result)
            if draft is None:
                raise ValueError(
                    f"No final draft is available for requested platform {platform}."
                )
            result_platform = (
                result.get("platform", platform)
                if isinstance(result, dict)
                else platform
            )
            if not isinstance(result_platform, str) or not result_platform.strip():
                result_platform = platform
            processed_content.append(
                {"platform": result_platform, "processed_content": draft}
            )
        update["processed_content"] = processed_content
    return update


review_node = review_refine_node
