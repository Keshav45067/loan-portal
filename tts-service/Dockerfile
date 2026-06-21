# Must be built from the 'services' directory: docker build -f tts-service/Dockerfile .
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY tts-service/requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

FROM python:3.11-slim

WORKDIR /app



COPY --from=builder /app/wheels /wheels
COPY tts-service/requirements.txt .
RUN pip install --no-cache /wheels/*

COPY shared/ ./shared/
COPY proto/ ./proto/
COPY tts-service/ ./tts-service/

ENV PYTHONPATH=/app
WORKDIR /app/tts-service

EXPOSE 50051
CMD ["python", "server.py"]
