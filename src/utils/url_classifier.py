"""Classify a URL as `article` or `video` from the host alone.

Host-based heuristics are >95% accurate for the platforms Smart Saver cares
about and avoid the cost of probing the URL twice (once with yt-dlp, once
with the article extractor). A future revision can fall back to a yt-dlp
"can-extract?" probe when a known social host returns no body text.

Also exposes `sanitize_url(url)` which strips the share-sheet tracking
params iOS apps attach (`utm_*`, `igshid`, `si`, `share_app_id`, …).
Calling this once at the API boundary keeps the Chroma row keyed by
the canonical URL — so the same item shared twice from different
surfaces de-dupes onto a single id.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.logger import get_logger
from src.schemas import SourceType

logger = get_logger(__name__)


# Query parameters every host uses purely for share-attribution. Stripped
# before the URL is shown to yt-dlp / Chroma so we don't cache-miss on
# what is effectively the same link.
_TRACKING_PARAMS: set[str] = {
    # Universal "where did this click come from"
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name",
    # Google
    "gclid", "dclid", "gbraid", "wbraid",
    # Instagram
    "igshid", "igsh",
    # TikTok
    "share_type", "share_id", "share_app_id", "share_link_id",
    "is_from_webapp", "is_copy_url", "sender_device",
    # YouTube / generic shorteners
    "si", "feature", "source",
    # X / Twitter
    "s", "t",
}


def sanitize_url(url: str) -> str:
    """Return `url` with known tracking parameters removed AND with a
    bare `?` separator dropped when the resulting query is empty.

    The bare-`?` normalisation matters: Facebook's URL parser returns
    400 Bad Request for `https://www.facebook.com/share/<id>/?` (note
    the trailing `?` with no query). The FB iOS share-sheet emits URLs
    in exactly that shape after the share-sheet tracking gets stripped.
    Always reconstructing via `urlunparse` strips the orphan `?`.

    Preserves everything else — scheme, host, path, fragment, and any
    *meaningful* query parameter (e.g. YouTube's `v=`, FB Watch's `v=`).
    Idempotent: calling it twice yields the same string.
    """
    if not url:
        return url
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    if parsed.query:
        kept = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS
        ]
        parsed = parsed._replace(query=urlencode(kept))
    else:
        # Path through urlunparse anyway — that's what strips the bare `?`.
        parsed = parsed._replace(query="")

    return urlunparse(parsed)

# Hosts where every shared link is, in practice, a video / reel.
_VIDEO_HOSTS: set[str] = {
    "youtube.com",
    "youtu.be",
    "m.youtube.com",
    "music.youtube.com",
    # TikTok — all share-sheet shapes route here. `tiktok.com` covers
    # `www.tiktok.com/@user/video/<id>` after the `www.` is stripped by
    # `_normalize_host`. The two short-link hosts come straight from the
    # TikTok app's "Copy link" sheet.
    "tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
    "clips.twitch.tv",
    "streamable.com",
}

# Hosts that mix video and text — we treat specific path patterns as video.
# After normalization (see _normalize_host below) the keys here are the
# bare apex domain — `mobile.twitter.com` collapses to `twitter.com`
# before lookup.
#
# Facebook is intentionally NOT in this map. Anonymous FB scraping is
# unreliable (auth walls, frequent 400s, share-sheet URL shapes that
# change without notice). Shared FB links fall through to the article
# path, where they will usually fail with a clean "Failed" status —
# that's by design after the Step 11 cleanup.
_MIXED_HOST_VIDEO_PATTERNS: dict[str, re.Pattern[str]] = {
    "instagram.com": re.compile(r"^/(reel|reels|tv|p)/"),
    "twitter.com": re.compile(r"/status/"),
    "x.com": re.compile(r"/status/"),
}


def _normalize_host(host: str) -> str:
    """Strip the common mobile / canonical-www subdomain prefixes so a
    `m.facebook.com` URL classifies identically to `facebook.com`."""
    host = host.lower()
    for prefix in ("www.", "m.", "mobile.", "web."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    return host


def classify(url: str) -> SourceType:
    """Return `SourceType.VIDEO` for known video URLs, otherwise `ARTICLE`.

    Idempotent in `url` — tracking parameters are stripped via
    `sanitize_url` before pattern matching so URLs differing only in
    `?mibextid=…` / `?fbclid=…` / `?si=…` produce the same routing
    decision.
    """
    cleaned = sanitize_url(url)
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        logger.warning("Could not parse URL: %s", url)
        return SourceType.UNKNOWN

    if not parsed.scheme or not parsed.netloc:
        logger.warning("URL missing scheme or host: %s", url)
        return SourceType.UNKNOWN

    host = _normalize_host(parsed.netloc)
    path = parsed.path or "/"

    if host in _VIDEO_HOSTS or any(host.endswith("." + h) for h in _VIDEO_HOSTS):
        logger.debug("Classified %s as VIDEO via host match (%s)", url, host)
        return SourceType.VIDEO

    for mixed_host, pattern in _MIXED_HOST_VIDEO_PATTERNS.items():
        if host == mixed_host:
            if pattern.search(path):
                logger.debug(
                    "Classified %s as VIDEO via mixed-host pattern (%s%s)",
                    url, host, path,
                )
                return SourceType.VIDEO

    logger.debug("Classified %s as ARTICLE (default)", url)
    return SourceType.ARTICLE
