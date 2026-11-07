FROM python:3.12-slim

COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY core ./core
COPY worker ./worker

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/tmp /app/cookies \
    && touch /app/cookies/cookies.txt \
    && chown -R app:app /opt/venv /app /data

USER app
CMD ["python", "-m", "bot.main"]
