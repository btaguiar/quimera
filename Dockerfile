FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVAL_DIR=/app/eval

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir ".[api,gcp]"

COPY eval/results/ eval/results/
COPY eval/thresholds.json eval/

RUN useradd --create-home quimera \
    && chown -R quimera:quimera /app
USER quimera

EXPOSE 8080
CMD ["python", "-m", "quimera.api"]
