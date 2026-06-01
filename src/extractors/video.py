"""Video extractor: yt-dlp metadata + audio download → faster-whisper ASR,
plus low-res video download → opencv frame sampling → easyocr.

Heavy ML libraries (`faster_whisper`, `easyocr`) are imported lazily inside
the relevant methods so an article-only run never pays the start-up cost.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

import yt_dlp

from src.config import settings
from src.extractors.base import BaseExtractor
from src.logger import get_logger
from src.schemas import OcrSegment, VideoResult

logger = get_logger(__name__)


class VideoExtractor(BaseExtractor[VideoResult]):
    def __init__(self, frame_interval_sec: float | None = None) -> None:
        self.frame_interval_sec = (
            frame_interval_sec
            if frame_interval_sec is not None
            else settings.frame_sample_interval_sec
        )

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
                logger.warning("No audio file found in %s — skipping ASR.", work_dir)

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
                # Extract a clean mp3 from the (now-guaranteed) mp4 for Whisper.
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "5",
                    "when": "post_process",
                },
            ],
            # `keepvideo=True` keeps the merged mp4 alongside the extracted mp3.
            "keepvideo": True,
            # The audio postprocessor writes to the same template basename,
            # so the mp3 ends up at video.mp3. We rename it below.
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
        """Find `<prefix>.<ext>` in `directory`, optionally restricted to a
        whitelist of extensions.

        The whitelist matters because yt-dlp can leave intermediate stream
        files behind (e.g. `video.f251.webm`) that share the same prefix as
        the merged output but are unreadable by OpenCV.
        """
        candidates = sorted(directory.glob(f"{prefix}.*"))
        if allowed_extensions:
            allowed = {ext.lower() for ext in allowed_extensions}
            candidates = [c for c in candidates if c.suffix.lower() in allowed]
        return candidates[0] if candidates else None

    # ----------------------------------------------------------------- whisper
    def _transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        try:
            from faster_whisper import WhisperModel  # heavy import, lazy
        except ImportError:
            logger.exception("faster-whisper is not installed")
            return "", None

        logger.info(
            "Loading Whisper model=%s device=%s compute_type=%s",
            settings.whisper_model, settings.whisper_device, settings.whisper_compute_type,
        )
        try:
            model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )
        except Exception:
            logger.exception("Failed to load Whisper model")
            return "", None

        try:
            # vad_filter=False: VAD was aggressively stripping audio with
            # heavy music/beats and quiet speech sections, leaving an empty
            # transcript. The extra ASR cost on silent segments is negligible.
            segments, info = model.transcribe(
                str(audio_path),
                language=settings.whisper_language,
                vad_filter=False,
            )
            text_parts = [seg.text.strip() for seg in segments if seg.text]
            transcript = " ".join(text_parts).strip()
            return transcript, getattr(info, "language", None)
        except Exception:
            logger.exception("Whisper transcription failed for %s", audio_path)
            return "", None

    # --------------------------------------------------------------------- ocr
    def _ocr_frames(self, video_path: Path) -> tuple[list[OcrSegment], int]:
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError:
            logger.exception("opencv-python is not installed")
            return [], 0

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.error("OpenCV could not open %s", video_path)
            return [], 0

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_step = max(1, int(round(fps * self.frame_interval_sec)))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        planned = (total_frames // frame_step) if total_frames else settings.ocr_max_frames
        cap_count = min(planned, settings.ocr_max_frames)
        logger.info(
            "OCR plan: fps=%.2f step=%d planned=%d cap=%d",
            fps, frame_step, planned, cap_count,
        )

        reader = self._load_easyocr_reader()
        if reader is None:
            cap.release()
            return [], 0

        segments: list[OcrSegment] = []
        frames_done = 0
        frame_idx = 0
        try:
            while frames_done < cap_count:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ok, frame = cap.read()
                if not ok or frame is None:
                    break

                timestamp = frame_idx / fps if fps else 0.0
                try:
                    detections = reader.readtext(frame)
                except Exception:
                    logger.exception("easyocr failed on frame %d", frame_idx)
                    detections = []

                for _bbox, text, conf in detections:
                    text_clean = (text or "").strip()
                    if not text_clean or conf < settings.ocr_min_confidence:
                        continue
                    segments.append(
                        OcrSegment(
                            timestamp_sec=round(timestamp, 2),
                            text=text_clean,
                            confidence=float(conf),
                        )
                    )

                frames_done += 1
                frame_idx += frame_step
        finally:
            cap.release()

        return segments, frames_done

    @staticmethod
    def _resolve_ocr_device(setting: str) -> "bool | str":
        """Translate `settings.ocr_device` into the value `easyocr.Reader(gpu=...)`
        expects.

        easyocr 1.7+ accepts either a bool (legacy CUDA-only) or a torch-style
        device string ("mps" / "cuda" / "cpu"). We return `False` for CPU
        because that's easyocr's idiomatic "disable GPU" sentinel and avoids
        a warning at construction time.
        """
        choice = (setting or "auto").lower()

        if choice == "cpu":
            return False
        if choice in ("mps", "cuda"):
            return choice

        # auto — pick the strongest backend torch can actually drive.
        try:
            import torch  # heavy import, lazy
            if torch.cuda.is_available():
                return "cuda"
            if torch.backends.mps.is_available():
                return "mps"
        except Exception:
            logger.exception("torch availability probe failed — defaulting to CPU")
        return False

    @staticmethod
    def _load_easyocr_reader() -> Any | None:
        try:
            import easyocr  # heavy import, lazy
        except ImportError:
            logger.exception("easyocr is not installed")
            return None

        device = VideoExtractor._resolve_ocr_device(settings.ocr_device)
        logger.info("Loading easyocr.Reader(langs=%s, device=%s)",
                    settings.ocr_languages, device or "cpu")
        try:
            return easyocr.Reader(settings.ocr_languages, gpu=device)
        except Exception:
            logger.exception(
                "Failed to initialise easyocr.Reader(langs=%s, device=%s)",
                settings.ocr_languages, device,
            )
            # If MPS / CUDA init crashes (e.g. broken torch wheel), retry on CPU
            # rather than letting OCR fail entirely.
            if device is not False:
                logger.warning("Falling back to CPU for easyocr")
                try:
                    return easyocr.Reader(settings.ocr_languages, gpu=False)
                except Exception:
                    logger.exception("CPU fallback also failed")
            return None

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
