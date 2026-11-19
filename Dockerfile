# Stage 1: Build React + Vite frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/packages/frontend
COPY packages/frontend/package*.json ./
RUN npm ci
COPY packages/frontend/ ./
RUN npm run build

# Stage 2: Python FastAPI runtime with uv
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MUSE2API_DATA_DIR=/app/data

COPY packages/backend/pyproject.toml packages/backend/uv.lock ./packages/backend/
RUN cd /app/packages/backend && uv sync --frozen --no-dev

COPY packages/backend/ ./packages/backend/
COPY extension/ ./extension/
COPY .env.example ./.env.example
COPY --from=frontend-builder /app/packages/frontend/dist ./packages/frontend/dist

RUN mkdir -p /app/data/media /app/db

WORKDIR /app/packages/backend
EXPOSE 8000

CMD ["uv", "run", "--no-dev", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
