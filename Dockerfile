# Starnet City, live paper trading. Works on Render, Fly.io, Railway or any Docker host.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY frontend frontend
COPY kits kits
ENV STARNET_MODE=live \
    STARNET_DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1
EXPOSE 8000
# one process only: the bots and the paper account live in memory
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
