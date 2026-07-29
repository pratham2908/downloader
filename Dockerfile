# Reel — YouTube downloader, container image for hosted deployment.
FROM python:3.12-slim

# ffmpeg: required to merge video+audio and to extract audio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Install deps, then force the very latest yt-dlp. YouTube changes constantly,
# so a version frozen by Docker layer caching quickly breaks with
# "Requested format is not available"; this keeps the build current.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --upgrade yt-dlp

COPY app ./app
COPY web ./web
COPY run.py ./

# Hosted defaults — override any of these in the platform's env settings.
#   MONGODB_URI            shared channels + history (recommended when hosted)
#   REEL_PASSWORD          require a login
#   REEL_COOKIES_FILE      e.g. /data/cookies.txt to get past YouTube bot checks
ENV REEL_HOSTED=1 \
    REEL_DOWNLOAD_DIR=/data/downloads \
    PORT=8787

# Mount a persistent disk at /data to keep files/cookies across restarts.
RUN mkdir -p /data/downloads

EXPOSE 8787

# Honour the platform-provided $PORT (Render/Railway/Fly set this).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8787}"]
