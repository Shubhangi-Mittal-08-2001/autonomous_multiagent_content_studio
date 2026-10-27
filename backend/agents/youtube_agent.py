"""YouTube-specific content generation."""

import logging
from typing import Any

from agents.common_implementation import generate_platform_draft

logger = logging.getLogger(__name__)


YOUTUBE_GUIDANCE = """\
Provide a compelling, accurate title and description, relevant tags, and a script
or outline suited to the source; add a thumbnail visual brief when useful. Script:
strong hook, natural spoken language, logical transitions, concise close, and no
unrequested production directions. Keep it viewer-facing. Avoid clickbait; preserve
facts and follow length/structure needs. Bold each deliverable heading.
"""


def youtube_agent(state: dict[str, Any], llm: Any = None) -> dict[str, Any]:
    """Generate or refine the YouTube draft assigned by the manager."""
    plan = state.get("current_plan")
    refining = bool(plan.get("is_refinement")) if isinstance(plan, dict) else False
    iteration = state.get("iteration_count", 0)
    logger.info("YouTube agent started; refinement=%s iteration=%s", refining, iteration)
    try:
        result = generate_platform_draft(state, "youtube", YOUTUBE_GUIDANCE, llm)
    except Exception:
        logger.exception("YouTube agent failed")
        raise
    logger.info("YouTube agent completed draft generation")
    return result
