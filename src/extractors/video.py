"""Video extractor: yt-dlp metadata + audio/video download → Gemini transcription + OCR.

yt-dlp downloads:
  - audio.mp3  → uploaded to Gemini File API for speech transcription
  - video.mp4  → uploaded to Gemini File API for on-screen text extraction

Both uploads are deleted from Gemini after the call completes.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import yt_dlp
from google import genai
from google.genai import types
from google.genai.errors import ServerError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings
from src.extractors.base import BaseExtractor
from src.logger import get_logger
from src.schemas import OcrSegment, VideoResult

logger = get_logger(__name__)

_AUDIO_MIME: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".opus": "audio/ogg",
}
_VIDEO_MIME: dict[str, str] = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
}


class VideoExtractor(BaseExtractor[VideoResult]):
    def __init__(self, frame_interval_sec: float | None = None) -> None:
        # frame_interval_sec kept for API compatibility — no longer used for
        # frame sampling since Gemini processes the full video natively.
        self._client: genai.Client | None = None  # lazy: avoid key validation at import time
        self._model_name = settings.gemini_model

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    def extract(self, url: str) -> VideoResult:
        logger.info("Extracting video: %s", url)
        result = VideoResult(url=url)

        work_dir = settings.tmp_dir / uuid.uuid4().hex
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            info = self._download(url, work_dir)
            if info is None:
                result.metadata["error"] = "yt_dlp_failed"
                return result

            result.title = info.get("title")
            result.uploader = info.get("uploader") or info.get("channel")
            result.description = info.get("description")
            result.duration_sec = info.get("duration")
            result.metadata = {
                "id": info.get("id"),
                "webpage_url": info.get("webpage_url"),
                "ext": info.get("ext"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "upload_date": info.get("upload_date"),
                "categories": info.get("categories"),
                "tags": info.get("tags"),
            }

            audio_path = self._find_file(
                work_dir, prefix="audio",
                allowed_extensions=(".mp3", ".m4a", ".wav", ".aac", ".opus"),
            )
            if audio_path is not None:
                transcript, language = self._transcribe(audio_path)
                result.transcript = transcript
                result.detected_language = language
            else:
                logger.warning("No audio file found in %s — skipping transcription.", work_dir)

            video_path = self._find_file(
                work_dir, prefix="video",
                allowed_extensions=(".mp4", ".m4v", ".mov", ".mkv", ".avi"),
            )
            if video_path is not None:
                segments, frames = self._ocr_frames(video_path)
                result.ocr_segments = segments
                result.frames_sampled = frames
                result.ocr_text = self._dedupe_ocr_lines(segments)
            else:
                logger.warning("No video file found in %s — skipping OCR.", work_dir)

            logger.info(
                "Video done: title=%r, transcript_chars=%d, ocr_lines=%d",
                result.title, len(result.transcript), len(result.ocr_segments),
            )
            return result

        except Exception as exc:
            logger.exception("Unexpected error in video extractor")
            result.metadata["error"] = f"{type(exc).__name__}: {exc}"
            return result
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ------------------------------------------------------------------ yt-dlp
    def _download(self, url: str, work_dir: Path) -> dict[str, Any] | None:
        """Download audio (mp3) + low-res mp4 in a single yt-dlp invocation.

        Audio goes to `audio.<ext>`, video goes to `video.<ext>` so we can
        locate them without parsing yt-dlp's return value.
        """
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "outtmpl": {
                "default": str(work_dir / "video.%(ext)s"),
            },
            # Prefer mp4 + m4a streams ≤480p so OpenCV can read the file
            # without a re-encode. Fall back through progressively looser
            # selectors; the FFmpegVideoConvertor below catches any leftover.
            "format": (
                "bv*[ext=mp4][height<=480]+ba[ext=m4a]/"
                "b[ext=mp4][height<=480]/"
                "b[ext=mp4]/"
                "bv*[height<=480]+ba/"
                "b[height<=480]/"
                "bv*+ba/b"
            ),
            "merge_output_format": "mp4",
            "postprocessors": [
                # Safety net: if format selection fell back to webm/mkv,
                # transcode the merged file to mp4 so OpenCV can read it.
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                },
                # Extract a clean mp3 from the (now-guaranteed) mp4 for Gemini.
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "5",
                    "when": "post_process",
                },
            ],
            # `keepvideo=True` keeps the merged mp4 alongside the extracted mp3.
            "keepvideo": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError:
            logger.exception("yt-dlp DownloadError for %s", url)
            return None
        except Exception:
            logger.exception("yt-dlp crashed for %s", url)
            return None

        # Normalise output names so `_find_file` can locate them deterministically.
        mp3 = work_dir / "video.mp3"
        if mp3.exists():
            mp3.rename(work_dir / "audio.mp3")

        return info

    @staticmethod
    def _find_file(
        directory: Path,
        prefix: str,
        allowed_extensions: tuple[str, ...] | None = None,
    ) -> Path | None:
        candidates = sorted(directory.glob(f"{prefix}.*"))
        if allowed_extensions:
            allowed = {ext.lower() for ext in allowed_extensions}
            candidates = [c for c in candidates if c.suffix.lower() in allowed]
        return candidates[0] if candidates else None

    # --------------------------------------------------------------- transcribe
    def _transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        mime_type = _AUDIO_MIME.get(audio_path.suffix.lower(), "audio/mpeg")
        logger.info("Uploading audio to Gemini: %s (%s)", audio_path.name, mime_type)

        file_ref = None
        try:
            file_ref = self._upload_and_wait(audio_path, mime_type)
            response = self._generate_with_retry(
                contents=[
                    file_ref,
                    "Transcribe all spoken audio. Return only the transcript text with no "
                    "timestamps, speaker labels, or formatting.",
                ],
            )
            transcript = (response.text or "").strip()
            logger.info("Transcription complete: %d chars", len(transcript))
            return transcript, None
        except Exception:
            logger.exception("Gemini transcription failed for %s", audio_path)
            return "", None
        finally:
            self._delete_file(file_ref)

    # --------------------------------------------------------------- ocr
    def _ocr_frames(self, video_path: Path) -> tuple[list[OcrSegment], int]:
        mime_type = _VIDEO_MIME.get(video_path.suffix.lower(), "video/mp4")
        logger.info("Uploading video to Gemini for OCR: %s (%s)", video_path.name, mime_type)

        file_ref = None
        try:
            file_ref = self._upload_and_wait(video_path, mime_type)
            response = self._generate_with_retry(
                contents=[
                    file_ref,
                    "List every distinct piece of on-screen text visible anywhere in this video. "
                    "Return one text item per line, no timestamps, no labels, no commentary.",
                ],
            )
            raw_lines = [ln.strip() for ln in (response.text or "").splitlines() if ln.strip()]
            segments = [
                OcrSegment(timestamp_sec=0.0, text=line, confidence=1.0)
                for line in raw_lines
            ]
            logger.info("OCR complete: %d lines", len(segments))
            return segments, 1
        except Exception:
            logger.exception("Gemini OCR failed for %s", video_path)
            return [], 0
        finally:
            self._delete_file(file_ref)

    # ---------------------------------------------------------- gemini helpers
    def _upload_and_wait(self, file_path: Path, mime_type: str):
        """Upload a file to Gemini File API and poll until it is ACTIVE."""
        file_ref = self._get_client().files.upload(
            file=file_path,
            config=types.UploadFileConfig(
                mime_type=mime_type,
                display_name=file_path.name,
            ),
        )
        while file_ref.state.name == "PROCESSING":
            time.sleep(2)
            file_ref = self._get_client().files.get(name=file_ref.name)
        if file_ref.state.name != "ACTIVE":
            raise RuntimeError(f"Gemini file processing failed: state={file_ref.state.name}")
        return file_ref

    def _delete_file(self, file_ref: Any) -> None:
        if file_ref is None:
            return
        try:
            self._get_client().files.delete(name=file_ref.name)
        except Exception:
            logger.warning("Could not delete Gemini file %s", file_ref.name)

    @retry(
        retry=retry_if_exception_type(ServerError),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _generate_with_retry(self, contents: list) -> Any:
        return self._get_client().models.generate_content(
            model=self._model_name,
            contents=contents,
        )

    # ------------------------------------------------------------------- utils
    @staticmethod
    def _dedupe_ocr_lines(segments: list[OcrSegment]) -> str:
        """Keep insertion order, drop duplicate lines (case-insensitive)."""
        seen: set[str] = set()
        unique: list[str] = []
        for seg in segments:
            key = seg.text.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(seg.text)
        return "\n".join(unique)
