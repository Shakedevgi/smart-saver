"""Article / blog post extractor.

Strategy (tried in order):
  1. Fetch HTML via `requests` with a modern-Chrome UA + Accept-Language.
  2. Hand the HTML to `trafilatura` for boilerplate-free body extraction
     and metadata (title, author, date, sitename).
  3. BeautifulSoup paragraph-join — last-ditch when trafilatura returns
     nothing.

A previous version included an og-tag fallback specifically to work
around Facebook's "Redirecting…" interstitial. That path was removed
in Step 11 along with the rest of the FB-specific scraping — anonymous
FB scraping was unreliable and is now expected to surface as a clean
"Failed" row in the iOS UI.
"""

from __future__ import annotations

import json
from typing import Any

import requests
import trafilatura
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.extractors.base import BaseExtractor
from src.logger import get_logger
from src.schemas import ArticleResult

logger = get_logger(__name__)


class ArticleExtractor(BaseExtractor[ArticleResult]):
    def extract(self, url: str) -> ArticleResult:
        logger.info("Extracting article: %s", url)
        result = ArticleResult(url=url)

        html = self._fetch_html(url)
        if html is None:
            result.metadata["error"] = "fetch_failed"
            return result

        # 1) Trafilatura — best for real long-form articles.
        parsed = self._parse_with_trafilatura(html, url)
        if parsed["text"]:
            result.title = parsed["title"]
            result.author = parsed["author"]
            result.publish_date = parsed["date"]
            result.site_name = parsed["sitename"]
            result.text = parsed["text"]
            result.metadata = parsed["extra"]
        else:
            # 2) BeautifulSoup paragraph join — last-ditch.
            logger.info("Trafilatura empty; falling back to BS4 paragraphs.")
            fallback_title, fallback_text = self._fallback_bs4(html)
            result.title = fallback_title
            result.text = fallback_text
            result.metadata["extractor"] = "beautifulsoup_fallback"

        result.word_count = len(result.text.split())
        logger.info(
            "Article done: title=%r, words=%d, extractor=%s",
            result.title, result.word_count, result.metadata.get("extractor"),
        )
        return result

    # ------------------------------------------------------------------ helpers
    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=False,
    )
    def _fetch_html_with_retry(self, url: str, headers: dict) -> requests.Response:
        """Inner fetch that Tenacity will retry on transient network errors.

        Only `ConnectionError` and `Timeout` are retried — those are the
        errors that go away on their own (flaky DNS, brief server hiccup).
        HTTP errors (4xx/5xx) are NOT retried because they won't change.
        """
        response = requests.get(
            url,
            headers=headers,
            timeout=settings.http_timeout_sec,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response

    def _fetch_html(self, url: str) -> str | None:
        headers = {
            "User-Agent": settings.http_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": settings.http_accept_language,
        }
        try:
            response = self._fetch_html_with_retry(url, headers)
            return response.text
        except requests.RequestException:
            logger.exception("HTTP fetch failed for %s (all retries exhausted)", url)
            return None
        except Exception:
            logger.exception("Unexpected error fetching %s", url)
            return None

    def _parse_with_trafilatura(self, html: str, url: str) -> dict[str, Any]:
        empty: dict[str, Any] = {
            "title": None, "author": None, "date": None,
            "sitename": None, "text": "", "extra": {},
        }
        try:
            raw = trafilatura.extract(
                html,
                url=url,
                output_format="json",
                include_comments=False,
                include_tables=False,
                with_metadata=True,
                favor_precision=True,
            )
        except Exception:
            logger.exception("Trafilatura raised on %s", url)
            return empty

        if not raw:
            return empty

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.exception("Trafilatura returned non-JSON for %s", url)
            return empty

        text = (data.get("text") or "").strip()
        return {
            "title": data.get("title"),
            "author": data.get("author"),
            "date": data.get("date"),
            "sitename": data.get("sitename") or data.get("hostname"),
            "text": text,
            "extra": {
                "language": data.get("language"),
                "categories": data.get("categories"),
                "tags": data.get("tags"),
                "extractor": "trafilatura",
            },
        }

    def _fallback_bs4(self, html: str) -> tuple[str | None, str]:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        title = (soup.title.string.strip() if soup.title and soup.title.string else None)

        for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            tag.decompose()

        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = "\n\n".join(p for p in paragraphs if len(p) > 40)
        return title, text
