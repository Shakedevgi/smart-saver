"""Gemini-backed analysis layer.

Takes an `IngestionResult` already populated by Step 1 and returns a
strict `AnalysisResult`: a category (dynamic — reuse an existing one or
invent a new one), an uncertainty flag, alternative categories, a one-line
summary, key insights, and a flexible bag of extracted entities.

Implementation notes
--------------------
- We call **Gemini 2.5 Flash** via the `google-genai` SDK.
- Structured outputs are enforced by passing `response_schema=AnalysisResult`
  and `response_mime_type="application/json"` in `GenerateContentConfig`.
  The model is constrained to emit JSON that validates against the schema —
  we still call `model_validate_json` defensively.
- Existing categories (if provided) are injected into the system prompt so
  the model prefers reusing them over inventing near-duplicates.
"""

from __future__ import annotations

import json

from google import genai
from google.genai import types
from google.genai.errors import ServerError
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.logger import get_logger
from src.schemas import AnalysisResult, ExtractedEntities, IngestionResult

logger = get_logger(__name__)


def _gemini_schema(model_cls) -> dict:
    """Convert a Pydantic model to a JSON schema dict Gemini accepts.

    Gemini's structured-output API rejects `additionalProperties` (produced
    by Pydantic `extra="allow"` models).  Strip it recursively.
    """
    def _strip(node):
        if isinstance(node, dict):
            node.pop("additionalProperties", None)
            for v in node.values():
                _strip(v)
        elif isinstance(node, list):
            for item in node:
                _strip(item)

    schema = model_cls.model_json_schema()
    _strip(schema)
    return schema


SYSTEM_PROMPT = """\
You are the analysis brain of "Smart Saver", a personal second-brain
that ingests articles, videos, and social-media posts a user saves.
Your job is to read the aggregated text of ONE saved item and emit a
JSON object matching the schema you are given.

# CATEGORIZATION (most important — read this carefully)

The user provides an `existing_categories` list. It is a REFERENCE
LIST to help you avoid creating near-duplicate labels (e.g. "Tech Tool"
vs "Tech Tools"). It is NOT a menu of allowed answers and it is NOT a
constraint on your output. Most new items belong in a brand-new
specific category — that is the expected default behavior, not the
exception.

Decision procedure — follow IN THIS EXACT ORDER:

  Step A. Read the content. Decide the single most specific Title-Case
          label (1-3 words) that captures what this item is actually
          about. Do this WITHOUT looking at `existing_categories` yet.

  Step B. Now check `existing_categories`. Reuse an existing label
          VERBATIM only if it is an OBVIOUS SYNONYM of your Step-A label:
            • same underlying topic
            • same level of specificity
            • a user filing manually would treat them as interchangeable
          Loose thematic overlap is NOT a match. If your Step-A label
          was "Fitness" and the list contains "Travel" — that is NOT a
          match. Keep your new label.

  Step C. If Step B found no obvious-synonym match, emit your Step-A
          label as `suggested_category`. This is a brand-new category
          and that is fine — the user wants you to grow the taxonomy
          dynamically.

  Step D. If the content plausibly fits TWO OR MORE distinct categories,
          OR your best match feels generic / vague / forced, set
          `is_uncertain = true` and populate `alternative_categories`
          with 2-3 plausible labels (which themselves follow Steps A-C).
          When you are genuinely torn, prefer is_uncertain=true over
          forcing a confidently wrong answer.

# ANTI-BIAS RULES (do not violate)

- DO NOT reuse an existing category because it is conveniently on the
  list. The default action is to INVENT a new specific label; reuse
  is the exception, reserved for obvious-synonym matches.
- A reel about gym workouts goes in "Fitness", NOT in "Programming"
  or "Travel" just because those happen to be in `existing_categories`.
- A recipe video goes in "Recipes" or "Cooking", NOT in any unrelated
  existing category.
- Generic fallbacks are FORBIDDEN: never emit "Misc", "Other",
  "General", "Uncategorized", "Stuff", or "Random". If you genuinely
  cannot find a topic, set is_uncertain=true with real alternatives
  rather than picking a placeholder.
- Categories must be Title Case, 1-3 words, no quotes, no prefixes,
  no emoji.

# FEW-SHOT EXAMPLES (decision logic only)

Example 1 — INVENT a new category (don't lazy-match)
  existing_categories: ["Programming", "Travel"]
  content: "Quick 5-minute home workout for abs and core."
  → suggested_category: "Fitness"
  → is_uncertain: false
  (Wrong: "Travel" or "Programming" — gym workouts have no relation
  to either. Step-A says "Fitness"; nothing in the list is a synonym.)

Example 2 — REUSE (obvious synonym)
  existing_categories: ["Tech Tools", "Travel"]
  content: "FastAPI tutorial: building APIs with Pydantic."
  → suggested_category: "Tech Tools"
  → is_uncertain: false
  (Step-A says "Web Frameworks" or "Tech Tools" — "Tech Tools" is
  already in the list and is a natural fit, so reuse.)

Example 3 — FLAG UNCERTAIN (torn between two real options)
  existing_categories: ["Tech Tools", "Career Advice"]
  content: "Reel: how I quit my engineering job to start a startup."
  → suggested_category: "Entrepreneurship"
  → is_uncertain: true
  → alternative_categories: ["Career Advice", "Startups"]

# OTHER FIELDS

- `summary_one_liner`: one sentence, ≤ 30 words, no "This article…" /
  "This video…" filler — get straight to the substance.
- `key_insights`: 3-7 short bullets capturing the value / action items.
  No marketing speak, no filler.
- `extracted_entities`:
    - `price`: monetary figure mentioned, with its currency symbol, or null.
    - `location`: city / neighborhood / country most central, or null.
    - `technologies`: concrete tools / frameworks / products / APIs.
    - You MAY add ad-hoc keys (e.g. `brand`, `release_date`,
      `author_handle`) when you spot something useful that doesn't fit
      the named slots.

You will only emit valid JSON. No prose, no markdown fences, no
preamble.
"""


_EMPTY_INPUT_FALLBACK = AnalysisResult(
    suggested_category="Uncategorized",
    is_uncertain=True,
    alternative_categories=[],
    summary_one_liner="No usable text could be extracted from this item.",
    key_insights=[],
    extracted_entities=ExtractedEntities(),
)


class LLMAnalyzer:
    """Runs the categorisation + summarisation + entity extraction prompt."""

    def __init__(
        self,
        model: str | None = None,
        temperature: float | None = None,
        max_input_chars: int | None = None,
    ) -> None:
        self.model_name = model or settings.gemini_model
        self.temperature = temperature if temperature is not None else 0.2
        self.max_input_chars = max_input_chars or settings.llm_max_input_chars
        self._client = genai.Client(api_key=settings.gemini_api_key)
        logger.info("LLMAnalyzer ready: model=%s", self.model_name)

    # ------------------------------------------------------------------ public
    def analyze(
        self,
        ingestion: IngestionResult,
        existing_categories: list[str] | None = None,
    ) -> AnalysisResult:
        text = ingestion.aggregated_text
        if not text.strip():
            logger.warning("No aggregated text — returning empty-input fallback.")
            return _EMPTY_INPUT_FALLBACK.model_copy(deep=True)

        if len(text) > self.max_input_chars:
            logger.info(
                "Truncating aggregated text from %d → %d chars",
                len(text), self.max_input_chars,
            )
            text = text[: self.max_input_chars]

        user_prompt = self._build_user_prompt(
            text=text,
            url=ingestion.url,
            source_type=ingestion.source_type.value,
            existing_categories=existing_categories or [],
        )

        logger.info("Calling Gemini model=%s …", self.model_name)

        try:
            response = self._chat_with_retry(user_prompt)
        except Exception as exc:
            logger.exception("Gemini call failed (all retries exhausted)")
            return self._error_fallback(f"gemini_error: {type(exc).__name__}: {exc}")

        return self._parse(response.text or "")

    # ----------------------------------------------------------------- helpers
    @retry(
        retry=retry_if_exception_type(ServerError),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _chat_with_retry(self, user_prompt: str):
        """Gemini call that Tenacity retries on transient server errors (5xx)."""
        return self._client.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=_gemini_schema(AnalysisResult),
                temperature=self.temperature,
            ),
        )

    def _build_user_prompt(
        self,
        *,
        text: str,
        url: str,
        source_type: str,
        existing_categories: list[str],
    ) -> str:
        """Order matters: content FIRST so the model commits to a Step-A
        label before being shown the existing-categories reference. That
        ordering — plus the reframing of the list as "reference only,
        not a constraint" — is what fixes the in-context-bias problem
        where small models were lazy-matching unrelated items into
        whatever happened to be on the list.
        """
        existing_block = (
            "\n".join(f"- {c}" for c in existing_categories)
            if existing_categories
            else "(none yet — invent a brand-new category for this item)"
        )
        return (
            f"URL: {url}\n"
            f"Source type: {source_type}\n"
            f"\n"
            f"=== CONTENT TO ANALYZE ===\n"
            f"{text}\n"
            f"=== END CONTENT ===\n"
            f"\n"
            f"existing_categories (REFERENCE LIST — for near-duplicate "
            f"avoidance only, NOT a constraint on your answer):\n"
            f"{existing_block}\n"
            f"\n"
            f"Reminder: pick or invent the most specific accurate category. "
            f"Only reuse one of the above if it is an obvious synonym of "
            f"the label you would have chosen on your own. Forbidden: "
            f"'Misc', 'Other', 'General', 'Uncategorized'."
        )

    def _parse(self, raw: str) -> AnalysisResult:
        if not raw.strip():
            return self._error_fallback("empty_response")
        try:
            return AnalysisResult.model_validate_json(raw)
        except ValidationError:
            logger.exception("Gemini JSON did not validate against AnalysisResult")
        # One forgiving retry: maybe the model wrapped the JSON in extra text.
        try:
            parsed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
            return AnalysisResult.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError):
            logger.exception("Fallback JSON parse also failed; raw=%r", raw[:500])
        return self._error_fallback("invalid_json_from_llm")

    @staticmethod
    def _error_fallback(reason: str) -> AnalysisResult:
        return AnalysisResult(
            suggested_category="Uncategorized",
            is_uncertain=True,
            alternative_categories=[],
            summary_one_liner=f"Analysis unavailable ({reason}).",
            key_insights=[],
            extracted_entities=ExtractedEntities(),
        )
