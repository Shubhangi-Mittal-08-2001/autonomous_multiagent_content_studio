"""Facebook-specific content generation."""

import logging
from typing import Any

from agents.common_implementation import generate_platform_draft

logger = logging.getLogger(__name__)

FACEBOOK_GUIDANCE = """\
Return a conversational post with an engaging opening, clear paragraphs, and useful
CTA; add restrained relevant hashtags and a visual brief with accessibility alt
text when a visual suits the source. Ground claims in the source, follow audience
and length needs, and bold each deliverable heading.
"""


def facebook_agent(state: dict[str, Any], llm: Any = None) -> dict[str, Any]:
    """Generate or refine the Facebook draft assigned by the manager."""
    plan = state.get("current_plan")
    refining = bool(plan.get("is_refinement")) if isinstance(plan, dict) else False
    iteration = state.get("iteration_count", 0)
    logger.info("Facebook agent started; refinement=%s iteration=%s", refining, iteration)
    result = generate_platform_draft(state, "facebook", FACEBOOK_GUIDANCE, llm)
    logger.info("Facebook agent completed draft generation")
    return result
