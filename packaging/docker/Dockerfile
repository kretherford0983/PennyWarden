# Optional Docker server deployment (Docker is never required for native installs - BR-082/083).
# Build from the repo root:  docker build -f packaging/docker/Dockerfile -t pennywarden .
FROM node:22-slim AS ui
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json frontend/
RUN npm --prefix frontend ci
COPY frontend frontend
# 2.4.0 (#473): the user guide and the guides it links to are bundled into the UI
COPY docs/user-guide.md docs/check-printing.md docs/backup-restore.md docs/
RUN mkdir -p backend/fmpoc && npm --prefix frontend run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FM_DATA_DIR=/data FM_MODE=server FM_HOST=0.0.0.0 FM_PORT=8765
RUN useradd --system --uid 10001 --home-dir /data app && mkdir -p /data && chown app /data
WORKDIR /opt/pennywarden
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/fmpoc fmpoc
COPY LICENSE THIRD-PARTY-NOTICES.txt ./
COPY --from=ui /src/backend/fmpoc/static fmpoc/static
USER app
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/api/health')"
ENTRYPOINT ["python", "-m", "fmpoc", "--no-browser"]
