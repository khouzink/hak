FROM node:22.16.0-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12.10-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/app/data/uno.sqlite3
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 app && mkdir /app/data && chown app:app /app/data
COPY --chown=app:app backend/ ./backend/
COPY --chown=app:app scripts/ ./scripts/
# Include precomputed, non-secret verified OSM/ORS matrix when present.
# Rebuild the image after generating a new snapshot.
COPY --from=frontend --chown=app:app /build/dist ./frontend/dist
USER app
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"
CMD ["uvicorn", "backend.presentation.main:app", "--host", "0.0.0.0", "--port", "8080"]
