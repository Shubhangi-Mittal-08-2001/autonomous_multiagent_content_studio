"""Instagram-specific content generation."""

import logging
from typing import Any

from agents.common_implementation import generate_platform_draft

logger = logging.getLogger(__name__)


INSTAGRAM_GUIDANCE = """\
Return a brief for a suitable image, carousel (with slide-by-slide plan), or video;
an engaging caption
with relevant, restrained hashtags and a natural CTA when useful; and accessibility
alt text. Use an opening and scannable paragraphs. Visuals are suggestions, never
source facts. Follow audience/length requirements and bold each deliverable heading.
"""


def instagram_agent(state: dict[str, Any], llm: Any = None) -> dict[str, Any]:
    """Generate or refine the Instagram draft assigned by the manager."""
    plan = state.get("current_plan")
    refining = bool(plan.get("is_refinement")) if isinstance(plan, dict) else False
    iteration = state.get("iteration_count", 0)
    logger.info("Instagram agent started; refinement=%s iteration=%s", refining, iteration)
    try:
        result = generate_platform_draft(state, "instagram", INSTAGRAM_GUIDANCE, llm)
    except Exception:
        logger.exception("Instagram agent failed")
        raise
    logger.info("Instagram agent completed draft generation")
    return result
