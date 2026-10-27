# Purpose: Coordinates platform agents and delegates content tasks.

"""Manager planning node for multi-platform content generation."""

import json
import logging
from typing import Any

from agents.common_implementation import parse_json_object
from config.llm import COMPLEX_MODEL_ALIAS, SIMPLE_MODEL_ALIAS, invoke_llm
from observability import get_client
from state.content_state import ContentCreationState

logger = logging.getLogger(__name__)


PLATFORM_GUIDANCE = {
    "linkedin": "Deliver a professional, insight-led post with a clear takeaway; include relevant restrained hashtags and a visual brief with alt text when useful. Bold each deliverable heading.",
    "x": "Use concise, conversational wording suited to a short post or coherent thread.",
    "instagram": "Deliver a visual brief (single image/carousel/video as suited), caption with relevant hashtags, and accessibility alt text. Bold each deliverable heading.",
    "youtube": "Deliver an accurate title, description, relevant tags, and a spoken script/outline or thumbnail brief when suited to the source. Bold each deliverable heading.",
    "facebook": "Deliver a conversational post, relevant hashtags, and a visual brief with alt text when a visual suits the source. Bold each deliverable heading.",
}


def _platform_lookup(mapping: Any) -> dict[str, Any]:
    """Make platform names comparable even if their capitalization differs."""
    if not isinstance(mapping, dict):
        return {}
    return {str(key).strip().lower(): value for key, value in mapping.items()}


def _decode_plan(response: Any, expected_platforms: list[str]) -> dict[str, Any]:
    """Validate the manager's JSON plan and normalize it to requested platforms.

    Every requested platform must have exactly one usable task with the required
    fields. Tasks for platforms the caller did not request are discarded.
    """
    plan = parse_json_object(
        response,
        description="Manager plan",
        required_key="platform_tasks",
    )
    request_status = plan.get("request_status")
    if not isinstance(request_status, str) or request_status not in {
        "processable",
        "clarification_required",
    }:
        raise ValueError("The Manager plan must set request_status to processable or clarification_required.")
    missing_details = plan.get("missing_details")
    if not isinstance(missing_details, list) or any(
        not isinstance(item, str) or not item.strip() for item in missing_details
    ):
        raise ValueError("The Manager plan must include missing_details as a list of non-empty strings.")
    unavailable_details = plan.get("unavailable_details")
    if not isinstance(unavailable_details, list) or any(
        not isinstance(item, str) or not item.strip() for item in unavailable_details
    ):
        raise ValueError("The Manager plan must include unavailable_details as a list of non-empty strings.")
    platform_scope_mismatch = plan.get("platform_scope_mismatch")
    if not isinstance(platform_scope_mismatch, bool):
        raise ValueError("The Manager plan must include platform_scope_mismatch as a boolean.")
    clarification_message = plan.get("clarification_message", "")
    if not isinstance(clarification_message, str):
        raise ValueError("The Manager plan clarification_message must be a string.")
    plan["missing_details"] = [item.strip() for item in missing_details]
    plan["unavailable_details"] = [item.strip() for item in unavailable_details]
    plan["clarification_message"] = clarification_message.strip()
    quality_requirements = plan.get("quality_requirements", [])
    if not isinstance(quality_requirements, list) or any(
        not isinstance(item, str) or not item.strip() for item in quality_requirements
    ):
        logger.warning("Ignoring malformed optional Manager quality_requirements")
        plan["quality_requirements"] = []
    tasks = plan.get("platform_tasks")
    if not isinstance(tasks, list):
        raise ValueError("The Manager plan must include a platform_tasks list.")
    if request_status == "clarification_required":
        if tasks:
            raise ValueError("A clarification-required Manager plan must not include platform tasks.")
        if not plan["clarification_message"]:
            raise ValueError("A clarification-required Manager plan must include clarification_message.")
        plan["platform_tasks"] = []
        return plan
    if not tasks:
        raise ValueError("A processable Manager plan must include platform tasks.")
    if plan["clarification_message"]:
        raise ValueError("A processable Manager plan must not include clarification_message.")
    required_task_fields = {"platform", "task", "tone", "format_requirements", "key_points"}
    expected_by_key = {platform.lower(): platform for platform in expected_platforms}
    tasks_by_platform: dict[str, dict[str, Any]] = {}
    unexpected_platforms: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        platform = task.get("platform")
        if not isinstance(platform, str) or not platform.strip():
            continue
        platform_key = platform.strip().lower()
        matched_key = next(
            (
                expected_key
                for expected_key in expected_by_key
                if platform_key == expected_key
                or platform_key.startswith((expected_key + " ", expected_key + ":"))
            ),
            None,
        )
        if matched_key is None:
            unexpected_platforms.append(platform.strip())
            continue
        if matched_key not in tasks_by_platform:
            tasks_by_platform[matched_key] = task

    missing_platforms = [
        platform
        for platform in expected_platforms
        if platform.lower() not in tasks_by_platform
    ]
    if missing_platforms:
        logger.warning(
            "Manager plan platform mismatch missing=%s unexpected=%s",
            missing_platforms,
            unexpected_platforms,
        )
        raise ValueError(
            "Manager plan omitted requested platform task(s): "
            + ", ".join(missing_platforms)
            + "."
        )

    normalized_tasks: list[dict[str, Any]] = []
    for platform in expected_platforms:
        task = tasks_by_platform[platform.lower()]
        missing_fields = required_task_fields.difference(task)
        if missing_fields:
            raise ValueError(
                f"Manager task for {platform} is missing required fields: "
                + ", ".join(sorted(missing_fields))
                + "."
            )
        task["platform"] = platform
        normalized_tasks.append(task)
    if unexpected_platforms:
        logger.warning(
            "Ignoring Manager tasks for unrequested platforms=%s",
            unexpected_platforms,
        )
    plan["platform_tasks"] = normalized_tasks
    return plan


def manager_node(state: ContentCreationState) -> dict[str, Any]:
    """Plan work for the platform agents, or return saved drafts at the limit."""
    content = state.get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Manager planning requires non-empty source content.")

    raw_platforms = state.get("platforms", [])
    platforms: list[str] = []
    if isinstance(raw_platforms, list):
        platforms = [
            platform.strip()
            for platform in raw_platforms
            if isinstance(platform, str) and platform.strip()
        ]
    if not platforms:
        raise ValueError("Manager planning requires at least one requested platform.")

    audience = state.get("audience") or "general"
    iteration = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 0)
    is_refinement = bool(state.get("replan_required", False))
    logger.info(
        "Planning for %d platform(s); refinement=%s, iteration=%d/%d",
        len(platforms),
        is_refinement,
        iteration,
        max_iterations,
    )

    if is_refinement and iteration >= max_iterations:
        results_by_platform = _platform_lookup(state.get("latest_results", {}))
        processed_content: list[dict[str, str]] = []

        # No more refinements are allowed, so send the latest saved drafts to the user.
        for platform in platforms:
            result = results_by_platform.get(platform.lower())
            if isinstance(result, dict):
                draft = (
                    result.get("processed_content")
                    or result.get("content")
                    or result.get("draft")
                )
                result_platform = result.get("platform", platform)
            else:
                draft = result
                result_platform = platform

            if isinstance(draft, str) and draft.strip():
                processed_content.append(
                    {
                        "platform": result_platform if isinstance(result_platform, str) else platform,
                        "processed_content": draft,
                    }
                )
            else:
                logger.warning(
                    "No usable latest draft found for platform=%s at refinement limit",
                    platform,
                )

        logger.warning(
            "Refinement limit reached at iteration=%d (max_iterations=%d); "
            "returning %d latest draft(s) without another planning call",
            iteration,
            max_iterations,
            len(processed_content),
        )
        return {
            "processed_content": processed_content,
            "manager_note": state.get("manager_note", "Your requested drafts are ready. You can refine the details and regenerate if needed."),
            "current_step": "completed",
            "replan_required": False,
            "task_completed": True,
            "task_failed": False,
            "error_message": "",
        }

    status_by_platform = _platform_lookup(state.get("platform_status", {}))
    feedback_by_platform = _platform_lookup(state.get("review_feedback", {}))
    if is_refinement:
        # Refine only platforms that are not approved and have a review status or feedback.
        targets = [
            platform
            for platform in platforms
            if status_by_platform.get(platform.lower()) != "approved"
            and (
                status_by_platform.get(platform.lower()) == "needs_refinement"
                or feedback_by_platform.get(platform.lower())
            )
        ]
        if not targets:
            raise ValueError("Refinement was requested, but no unapproved platform needs a new plan.")
    else:
        targets = platforms

    # Give the planner only the platforms that need work and their latest review context.
    tasks_context: list[dict[str, Any]] = []
    results_by_platform = _platform_lookup(state.get("latest_results", {}))
    for platform in targets:
        task = {
            "platform": platform,
            "guidance": PLATFORM_GUIDANCE.get(
                platform.lower(),
                f"Adapt the source into a native format and tone for {platform}.",
            ),
        }
        if is_refinement:
            task["review_feedback"] = feedback_by_platform.get(platform.lower(), "")
            task["existing_draft"] = results_by_platform.get(platform.lower())
        tasks_context.append(task)

    # The manager must assess ambiguity and conflicts for every request, including
    # requests whose platform agents use the simple tier.
    model = COMPLEX_MODEL_ALIAS
    if model == SIMPLE_MODEL_ALIAS:
        # The small local model repeatedly confuses platform labels in structured
        # manager JSON. For its single-platform workflow, construct the same
        # delegated task from trusted request state and static platform guidance.
        logger.info("Building deterministic simple-tier plan for platforms=%s", targets)
        plan = {
            "request_status": "processable",
            "clarification_message": "",
            "missing_details": [],
            "unavailable_details": [],
            "platform_scope_mismatch": False,
            "platform_tasks": [
                {
                    "platform": platform,
                    "task": (
                        f"Create a platform-native draft for {platform} from the supplied source."
                        if not is_refinement
                        else f"Refine the existing {platform} draft using the supplied review feedback."
                    ),
                    "tone": f"Use a voice suited to {platform} and the requested audience.",
                    "format_requirements": task_context["guidance"],
                    "key_points": [],
                    **(
                        {
                            "review_feedback": task_context.get("review_feedback", ""),
                            "existing_draft": task_context.get("existing_draft"),
                        }
                        if is_refinement
                        else {}
                    ),
                }
                for platform, task_context in zip(targets, tasks_context)
            ],
            "quality_requirements": [],
        }
    else:
        # Prompt content includes the user's source and review details; log metadata only.
        manager_prompt = get_client().get_prompt(
            "manager_prompt",
            type="text",
            label="production",
        )
        logger.info("Successfully fetched prompt from Langfuse name=manager_prompt")
        prompt = manager_prompt.compile(
            content=content,
            audience=audience,
            iteration=iteration,
            is_refinement=str(is_refinement),
            selected_platforms=json.dumps(platforms, ensure_ascii=False),
            platform_tasks=json.dumps(tasks_context, ensure_ascii=False, default=str),
        )
        logger.info("Manager planning model call starting platforms=%s", targets)
        try:
            response = invoke_llm(
                model,
                prompt,
                json_mode=True,
                max_completion_tokens=1800,
            )
            logger.info("Manager planning model call returned; validating plan for platforms=%s", targets)
            try:
                plan = _decode_plan(response, targets)
            except ValueError as first_error:
                # Repair only malformed/missing-JSON responses; do not retry service errors.
                logger.warning("Manager response missed its JSON contract; retrying once: %s", first_error)
                retry_prompt = (
                    prompt
                    + "\nCorrection: the previous response did not satisfy the JSON contract. "
                    + "Regenerate the object with request_status, clarification_message, "
                    + "missing_details, unavailable_details, platform_scope_mismatch, and the required platform_tasks "
                    + "array and fields. For clarification_required, return no platform tasks and a non-empty "
                    + "clarification_message. Return JSON only."
                )
                plan = _decode_plan(
                    invoke_llm(
                        model,
                        retry_prompt,
                        json_mode=True,
                        max_completion_tokens=3600,
                    ),
                    targets,
                )
        except Exception:
            logger.exception("Manager planning model call or response parsing failed")
            raise

    planned_tasks = plan.get("platform_tasks")
    if not isinstance(planned_tasks, list):
        raise ValueError("The Manager plan must include a platform_tasks list.")
    if not planned_tasks:
        clarification_message = plan.get("clarification_message")
        if (
            plan.get("request_status") != "clarification_required"
            or not isinstance(clarification_message, str)
            or not clarification_message.strip()
        ):
            raise ValueError(
                "A Manager plan without platform tasks must require clarification and include a message."
            )
        plan["quality_requirements"] = plan.get("quality_requirements", [])
        plan["audience"] = audience
        plan["is_refinement"] = is_refinement
        plan["iteration"] = iteration
        logger.info("Manager stopped without drafts and returned a clarification note")
        update = {
            "current_plan": plan,
            "node_plans": [],
            "manager_note": plan["clarification_message"].strip(),
            "processed_content": [],
            "current_step": "completed",
            "task_completed": True,
            "task_failed": False,
            "replan_required": False,
            "error_message": "",
        }
        if is_refinement:
            update["replan_count"] = state.get("replan_count", 0) + 1
        return update
    planned_by_platform = {
        str(item.get("platform", "")).strip().lower(): item
        for item in planned_tasks
        if isinstance(item, dict)
    }
    missing = [platform for platform in targets if platform.lower() not in planned_by_platform]
    if missing:
        raise ValueError(f"The Manager plan omitted requested platforms: {', '.join(missing)}.")
    plan["platform_tasks"] = [planned_by_platform[platform.lower()] for platform in targets]
    required_task_fields = {"platform", "task", "tone", "format_requirements", "key_points"}
    for platform_task in plan["platform_tasks"]:
        missing_fields = required_task_fields.difference(platform_task)
        if missing_fields:
            raise ValueError(
                "The Manager plan is missing task fields for "
                f"{platform_task.get('platform', 'a platform')}: {', '.join(sorted(missing_fields))}."
            )
        if is_refinement and "review_feedback" not in platform_task:
            platform_task["review_feedback"] = feedback_by_platform.get(
                str(platform_task["platform"]).lower(), ""
            )
        if is_refinement and "existing_draft" not in platform_task:
            platform_task["existing_draft"] = results_by_platform.get(
                str(platform_task["platform"]).lower()
            )
    # These values are authoritative workflow state, so never rely on the model
    # to echo them correctly (or include them at all).
    plan["quality_requirements"] = plan.get("quality_requirements", [])
    plan["audience"] = audience
    plan["is_refinement"] = is_refinement
    plan["iteration"] = iteration

    logger.info("Manager created %d platform task(s)", len(plan["platform_tasks"]))
    update: dict[str, Any] = {
        "current_plan": plan,
        "node_plans": plan["platform_tasks"],
        "current_step": "manager_planning",
    }
    if is_refinement:
        update["replan_count"] = state.get("replan_count", 0) + 1
    return update
