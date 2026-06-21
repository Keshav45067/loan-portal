# Must be built from the 'services' directory: docker build -f llm-service/Dockerfile .
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY llm-service/requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

FROM python:3.11-slim

WORKDIR /app



COPY --from=builder /app/wheels /wheels
COPY llm-service/requirements.txt .
RUN pip install --no-cache /wheels/*

COPY shared/ ./shared/
COPY proto/ ./proto/
COPY llm-service/ ./llm-service/

ENV PYTHONPATH=/app
WORKDIR /app/llm-service

EXPOSE 50051
CMD ["python", "server.py"]
