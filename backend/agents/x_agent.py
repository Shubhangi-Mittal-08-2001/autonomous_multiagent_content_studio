"""X-specific content generation."""

import logging
from typing import Any

from agents.common_implementation import generate_platform_draft

logger = logging.getLogger(__name__)


X_GUIDANCE = """\
Write a concise, conversational post that makes its core point immediately. Keep
each individual post within X's 280-character limit, including spaces and
punctuation; if the manager's plan calls for a thread, make the sequence coherent,
number it only when helpful, and keep each post within the limit. Use a direct
call to action only when appropriate. Avoid engagement bait, excessive hashtags,
and context-free claims. Follow any more specific format requirements in the plan;
do not mention the plan or content-production process in the posts.
"""


def x_agent(state: dict[str, Any], llm: Any = None) -> dict[str, Any]:
    """Generate or refine the X draft assigned by the manager."""
    plan = state.get("current_plan")
    refining = bool(plan.get("is_refinement")) if isinstance(plan, dict) else False
    iteration = state.get("iteration_count", 0)
    logger.info("X agent started; refinement=%s iteration=%s", refining, iteration)
    try:
        result = generate_platform_draft(state, "x", X_GUIDANCE, llm)
    except Exception:
        logger.exception("X agent failed")
        raise
    logger.info("X agent completed draft generation")
    return result
