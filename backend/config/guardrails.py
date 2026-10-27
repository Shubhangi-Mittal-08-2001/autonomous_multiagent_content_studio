"""Deterministic safety checks for user requests and generated drafts.

These checks are a conservative first layer; they do not prove factual accuracy.
The generation and review prompts also require source fidelity and prohibit
unsupported factual claims.
"""

import re
from dataclasses import dataclass
import logging
logger = logging.getLogger(__name__)


REFUSAL_MESSAGE = (
    "Sorry, I can't help create harmful instructions, fabricated allegations, "
    "override safety instructions, or create other content intended to deceive "
    "or harm. Please provide a safe, fact-based topic instead."
)


def generate_refusal_message(*, content: str, direction: str, reason: str) -> str:
    """Return a fixed refusal without making another model call."""
    logger.info(
        "Returning fixed refusal after safety rejection direction=%s reason=%s",
        direction,
        reason,
    )
    return REFUSAL_MESSAGE


@dataclass(frozen=True)
class GuardrailDecision:
    """Result of a safety check; ``reason`` explains a rejection when present."""

    allowed: bool
    reason: str = ""


# Match requests seeking actionable explosive construction or an explicit
# defamation campaign. Educational and factual discussion remains possible.
_EXPLOSIVE_ACTION = re.compile(
    r"\b(?:make|build|create|construct|assemble|formulat\w*|instructions?\s+for)"
    r"\b.{0,100}\b(?:explosives?|bombs?| IEDs?|improvised\s+explosive\s+devices?)\b"
    r"|\b(?:explosives?|bombs?| IEDs?)\b.{0,100}\b(?:make|build|create|construct|assemble)\b",
    re.IGNORECASE | re.DOTALL,
)
_DECEPTIVE_ATTACK = re.compile(
    r"\b(?:defam\w*|demean|smear|discredit)\b.{0,160}\b(?:false|fabricat\w*|lie|untrue|made[- ]up)\b"
    r"|\b(?:false|fabricat\w*|lie|untrue|made[- ]up)\b.{0,160}\b"
    r"(?:defam\w*|demean|smear|discredit|story|stories|allegation\w*)\b",
    re.IGNORECASE | re.DOTALL,
)
_DEFAMATION_INTENT = re.compile(
    r"\b(?:defam\w*|slander\w*|libel\w*|smear\w*|discredit\w*)\b"
    r"|\b(?:damage|ruin|destroy)\s+(?:the\s+)?(?:their\s+|his\s+|her\s+)?"
    r"reputation\b",
    re.IGNORECASE,
)
_INSTRUCTION_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,80}\b"
    r"(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|system|developer|"
    r"safety|original|my)?\s*(?:system\s+|developer\s+|safety\s+)?instructions?\b"
    r"|\b(?:ignore|disregard|forget|override|bypass)\b.{0,50}\b"
    r"(?:system|developer)\s+prompts?\b"
    r"|\b(?:reveal|show|print|repeat|disclose)\b.{0,50}\b"
    r"(?:system|developer)\s+(?:prompts?|instructions?)\b",
    re.IGNORECASE | re.DOTALL,
)


def check_user_content(content: str) -> GuardrailDecision:
    """Reject instruction overrides, dangerous instructions, or defamation."""
    if _INSTRUCTION_OVERRIDE.search(content):
        return GuardrailDecision(False, "attempt to override or reveal system instructions")
    if _EXPLOSIVE_ACTION.search(content):
        return GuardrailDecision(False, "actionable explosive construction request")
    if _DECEPTIVE_ATTACK.search(content):
        return GuardrailDecision(False, "request for fabricated or harmful allegations")
    if _DEFAMATION_INTENT.search(content):
        return GuardrailDecision(False, "request to defame or damage someone's reputation")
    return GuardrailDecision(True)


def check_generated_content(content: str) -> GuardrailDecision:
    """Block generated explosive instructions and explicit defamation requests."""
    if _EXPLOSIVE_ACTION.search(content):
        return GuardrailDecision(False, "generated content contains explosive instructions")
    if _DECEPTIVE_ATTACK.search(content) or _DEFAMATION_INTENT.search(content):
        return GuardrailDecision(False, "generated content contains defamatory intent or allegations")
    return GuardrailDecision(True)
