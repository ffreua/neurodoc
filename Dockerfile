ARG PYTHON_IMAGE=python:3.14.7-slim-bookworm
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PATH=/app/.venv/bin:$PATH
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 libpq5 clamav clamav-freshclam tesseract-ocr tesseract-ocr-por \
    poppler-utils fonts-dejavu-core ca-certificates tar \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app \
    && python -m venv /app/.venv
COPY requirements.txt /app/requirements.txt
RUN pip install --require-hashes -r requirements.txt && pip check
COPY . /app
RUN mkdocs build --strict \
    && chmod +x /app/ops/entrypoint.sh \
    && chown -R 10001:10001 /app \
    && mkdir -p /data/media /data/staticfiles /data/signing /data/beat /data/clamav \
    && chown -R 10001:10001 /data
ARG RELEASE_ID
ENV RELEASE_ID=${RELEASE_ID}
LABEL org.opencontainers.image.revision=${RELEASE_ID}
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
    CMD python /app/ops/http_health.py
ENTRYPOINT ["/app/ops/entrypoint.sh"]
CMD ["app"]
