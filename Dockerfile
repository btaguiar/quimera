FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# outDir do Vite é ../src/quimera/api/static (relativo a /build) → /src/quimera/api/static
RUN npm run build && mkdir -p /out && cp -r /src/quimera/api/static /out/static

FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVAL_DIR=/app/eval

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
# O bundle entra antes do pip install: a instalação não editável só leva
# para o site-packages o que já está em src/ (package-data static/**/*).
COPY --from=frontend /out/static/ src/quimera/api/static/
RUN pip install --no-cache-dir ".[api,gcp]"

COPY eval/results/ eval/results/
COPY eval/thresholds.json eval/

RUN useradd --create-home quimera \
    && chown -R quimera:quimera /app
USER quimera

EXPOSE 8080
CMD ["python", "-m", "quimera.api"]
