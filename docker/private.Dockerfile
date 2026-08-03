# Single-service image for the private research app: builds the Next.js frontend
# to static files, then runs FastAPI (app.eai_asgi) serving BOTH that frontend
# and the API. One container, one URL, login-gated. Free-tier friendly.

# ---- stage 1: build the static frontend ----
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
ENV EAI_STATIC_EXPORT=1 NEXT_TELEMETRY_DISABLED=1
RUN npm run build          # → /fe/out

# ---- stage 2: python backend serving the API + static frontend ----
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 EAI_STATIC_DIR=/app/frontend/out

COPY requirements-eai.txt ./
RUN pip install -r requirements-eai.txt

COPY app/ ./app/
COPY eai_config.yaml ./
COPY --from=frontend /fe/out ./frontend/out

# Render (and most PaaS) inject $PORT. Shell form so it expands.
CMD uvicorn app.eai_asgi:app --host 0.0.0.0 --port ${PORT:-8000}
