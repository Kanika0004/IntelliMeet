# Hosted demo image for IntelliMeet (used by Render; see render.yaml).
# Stage 1: build the React frontend
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend serving the API and the built frontend
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install ".[gemini]"
COPY --from=web /web/dist ./frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist \
    DEMO_MODE=true \
    HOST=0.0.0.0 \
    DATA_DIR=/app/data \
    TRANSCRIBER=local \
    ANALYZER=gemini
EXPOSE 8000
CMD ["intellimeet", "serve"]
