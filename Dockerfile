# =====================================================================
# MTR Music Server
# =====================================================================
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    MUSIC_DIR=/music \
    DATA_DIR=/data \
    MTR_LOG_LEVEL=INFO

# ffmpeg нужен аудиоядру (этап 2). Один слой с очисткой apt-списков.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости копируются отдельно: слой pip переиспользуется, пока
# не изменился requirements.txt.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --chown копирует сразу с нужным владельцем, без отдельного chown -R
# (он бы создал лишний слой, дублирующий весь код в образе).
COPY --chown=1000:1000 app ./app

# Каталог состояния: обе БД, ключ шифрования, кэш обложек.
RUN mkdir -p /data/covers /music \
 && useradd --create-home --uid 1000 --user-group mtr \
 && chown -R mtr:mtr /data

USER mtr

EXPOSE 4533
VOLUME ["/music", "/data"]

# HEALTHCHECK в exec-форме одной строкой: точка с запятой внутри CMD
# превращала предыдущую версию в нерабочую конструкцию.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:4533/healthz', timeout=3).status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4533"]
