"""Pydantic models for everything the ingestion pipeline emits.

`IngestionResult` is the public envelope the rest of the application
(Step 2 LLM analysis, Step 3 vector storage) will consume.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

# Hard ceiling on how much aggregated text we send to the LLM. Anything past
# this is dropped before the prompt is built so small local models don't OOM
# or hallucinate from being saturated with low-signal OCR noise.
MAX_LLM_INPUT_CHARS_DEFAULT = 12_000


class SourceType(str, Enum):
    ARTICLE = "article"
    VIDEO = "video"
    UNKNOWN = "unknown"


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ArticleResult(_Base):
    url: str
    source_type: SourceType = SourceType.ARTICLE
    title: str | None = None
    author: str | None = None
    publish_date: str | None = None      # ISO string when available
    site_name: str | None = None
    text: str = ""
    word_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class OcrSegment(_Base):
    timestamp_sec: float
    text: str
    confidence: float


class VideoResult(_Base):
    url: str
    source_type: SourceType = SourceType.VIDEO
    title: str | None = None
    uploader: str | None = None
    description: str | None = None       # caption / video description
    duration_sec: float | None = None
    transcript: str = ""
    detected_language: str | None = None
    ocr_text: str = ""                   # flat, deduped, joined with \n
    ocr_segments: list[OcrSegment] = Field(default_factory=list)
    frames_sampled: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedEntities(_Base):
    """Domain-specific fields the LLM should attempt to pull out of the
    aggregated text. All fields are optional — most items will only populate
    one or two. The model is `extra="allow"` so the LLM is free to add
    ad-hoc keys (e.g. `brand`, `release_date`, `author_handle`) when it
    spots something useful that doesn't fit the named slots.
    """

    model_config = ConfigDict(extra="allow")

    price: str | None = Field(
        default=None,
        description="Any price, fee, or monetary figure mentioned (keep the original currency symbol).",
    )
    location: str | None = Field(
        default=None,
        description="City, neighborhood, country, or address most central to the content.",
    )
    technologies: list[str] = Field(
        default_factory=list,
        description="Concrete tools, frameworks, languages, products, or APIs referenced.",
    )


class AnalysisResult(_Base):
    """Structured LLM output for one ingested item.

    Categories are *dynamic*: the LLM is encouraged to reuse one of the
    `existing_categories` it is shown, but is free to invent a new one when
    nothing fits. When it cannot confidently pick a single category, it
    must set `is_uncertain=True` and populate `alternative_categories` so
    the iOS app can prompt the user to disambiguate.
    """

    suggested_category: str = Field(
        ...,
        description="The single best category for this item. May be an existing label or a newly invented one.",
    )
    is_uncertain: bool = Field(
        default=False,
        description="True when the LLM was torn between multiple categories or had low overall confidence.",
    )
    alternative_categories: list[str] = Field(
        default_factory=list,
        description="Other plausible categories. Only populated when is_uncertain is true.",
    )
    summary_one_liner: str = Field(
        ...,
        description="One crisp sentence (≤ 30 words) capturing what this item is about.",
    )
    key_insights: list[str] = Field(
        default_factory=list,
        description="3–7 short bullets capturing the core value, action items, or takeaways.",
    )
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)


class SearchHit(_Base):
    """One result returned by `VectorStoreManager.search_items`."""

    url: str
    distance: float | None = None    # smaller is closer (cosine distance)
    document: str = ""               # the indexed aggregated_text (may be truncated for display)
    category: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionResult(_Base):
    """Top-level envelope returned by the orchestrator.

    `status` reflects async-pipeline progress (Step 6):
      - "processing": placeholder row written, background pipeline still running
      - "completed":  full extract → analyze → store cycle finished
      - "failed":     background pipeline raised; see `error` for the reason
    The default is "completed" so synchronous call sites
    (CLI, smoke tests) don't need to set it.
    """

    url: str
    source_type: SourceType
    article: ArticleResult | None = None
    video: VideoResult | None = None
    analysis: AnalysisResult | None = None
    error: str | None = None
    status: str = "completed"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def aggregated_text(self) -> str:
        """LLM-ready concatenation of every text source we extracted.

        Order is deliberate — title first so the model anchors on topic,
        then human-authored copy, then ASR/OCR which are noisier.
        """
        parts: list[str] = []

        if self.article is not None:
            if self.article.title:
                parts.append(f"# {self.article.title}")
            if self.article.author:
                parts.append(f"By {self.article.author}")
            if self.article.text:
                parts.append(self.article.text)

        if self.video is not None:
            if self.video.title:
                parts.append(f"# {self.video.title}")
            if self.video.uploader:
                parts.append(f"By {self.video.uploader}")
            if self.video.description:
                parts.append("## Description / Caption\n" + self.video.description)
            if self.video.transcript:
                parts.append("## Transcript\n" + self.video.transcript)
            if self.video.ocr_text:
                parts.append("## On-screen text\n" + self.video.ocr_text)

        return "\n\n".join(p for p in parts if p).strip()
