"""Public API request and response schemas."""
from pydantic import BaseModel, Field


class ContentRequest(BaseModel):
    """Input for generating platform drafts from source content and an audience."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=12000,
        description="Idea or source text to adapt (up to 12,000 characters).",
    )
    platforms: list[str] = Field(default_factory=lambda: ["linkedin", "x", "instagram"])
    audience: str = Field(
        default="general",
        max_length=180,
        description="Target audience for the content (up to 180 characters).",
    )


class ProcessedContentResponse(BaseModel):
    """One generated draft paired with the platform it targets."""

    processed_content: str
    platform: str


class ContentResponse(BaseModel):
    """API response containing generated drafts or an explanatory message."""

    processed_content: list[ProcessedContentResponse] = Field(default_factory=list)
    message: str | None = None
