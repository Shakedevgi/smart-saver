FROM python:3.12-slim

WORKDIR /app

# ffmpeg is required by yt-dlp for audio extraction (FFmpegExtractAudio postprocessor)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY src/ ./src/

# Cloud Run sets PORT at runtime (always 8080); default covers local docker run
CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
