# Nexus City: trading city + AI operations station. Works on Render, Fly.io, Railway or any Docker host.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY frontend frontend
COPY kits kits
# legacy names on purpose: a NEXUS_* value here would override a STARNET_* value set on the host
# (docs/MIGRATION_FROM_STARNET.md)
ENV STARNET_MODE=live \
    STARNET_DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1
EXPOSE 8000
# one process only: the bots and the paper account live in memory
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
