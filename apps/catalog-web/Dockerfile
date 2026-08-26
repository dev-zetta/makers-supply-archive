# syntax=docker/dockerfile:1.7
FROM node:22.18.0-alpine AS frontend
WORKDIR /build/frontend
COPY apps/catalog-web/frontend/package.json apps/catalog-web/frontend/package-lock.json ./
RUN npm ci
COPY apps/catalog-web/frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.8.14 AS uv
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
COPY apps/catalog-web/pyproject.toml ./apps/catalog-web/pyproject.toml
COPY apps/catalog-web/src/ ./apps/catalog-web/src/
COPY --from=frontend /build/src/makers_supply_web/static/ ./apps/catalog-web/src/makers_supply_web/static/
RUN uv sync --frozen --no-dev --all-packages && useradd --create-home --uid 10001 catalog
RUN mkdir /state && chown catalog:catalog /state
USER catalog
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["makers-supply-web", "serve", "--host", "0.0.0.0", "--port", "8000"]
