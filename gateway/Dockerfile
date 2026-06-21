# Must be built from the 'services' directory: docker build -f gateway/Dockerfile .
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY gateway/requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

FROM python:3.11-slim

WORKDIR /app



COPY --from=builder /app/wheels /wheels
COPY gateway/requirements.txt .
RUN pip install --no-cache /wheels/*

COPY shared/ ./shared/
COPY proto/ ./proto/
COPY gateway/ ./gateway/

ENV PYTHONPATH=/app
WORKDIR /app/gateway

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
