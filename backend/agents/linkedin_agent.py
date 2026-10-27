"""LinkedIn-specific content generation."""

import logging
from typing import Any

from agents.common_implementation import generate_platform_draft

logger = logging.getLogger(__name__)


LINKEDIN_GUIDANCE = """\
Write a professional, insight-led post with a strong first line, concise paragraphs,
and practical takeaway. Keep it credible and human; avoid corporate filler and
unsupported expertise. Add a relevant question/CTA when useful, restrained hashtags,
and a visual brief with alt text when useful. Follow length/format needs and bold
each deliverable heading.
"""


def linkedin_agent(state: dict[str, Any], llm: Any = None) -> dict[str, Any]:
    """Generate or refine the LinkedIn draft assigned by the manager."""
    plan = state.get("current_plan")
    refining = bool(plan.get("is_refinement")) if isinstance(plan, dict) else False
    iteration = state.get("iteration_count", 0)
    logger.info("LinkedIn agent started; refinement=%s iteration=%s", refining, iteration)
    try:
        result = generate_platform_draft(state, "linkedin", LINKEDIN_GUIDANCE, llm)
    except Exception:
        logger.exception("LinkedIn agent failed")
        raise
    logger.info("LinkedIn agent completed draft generation")
    return result
