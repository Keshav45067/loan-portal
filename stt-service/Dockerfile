# Must be built from the 'services' directory: docker build -f stt-service/Dockerfile .
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY stt-service/requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

FROM python:3.11-slim

WORKDIR /app



COPY --from=builder /app/wheels /wheels
COPY stt-service/requirements.txt .
RUN pip install --no-cache /wheels/*

COPY shared/ ./shared/
COPY proto/ ./proto/
COPY stt-service/ ./stt-service/

ENV PYTHONPATH=/app
WORKDIR /app/stt-service

EXPOSE 50051
CMD ["python", "server.py"]
