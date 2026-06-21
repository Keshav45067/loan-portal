# Must be built from the 'services' directory: docker build -f doc-intelligence/Dockerfile .
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY doc-intelligence/requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/wheels /wheels
COPY doc-intelligence/requirements.txt .
RUN pip install --no-cache /wheels/*

COPY shared/ ./shared/
COPY proto/ ./proto/
COPY doc-intelligence/ ./doc-intelligence/

ENV PYTHONPATH=/app
WORKDIR /app/doc-intelligence

EXPOSE 50051
CMD ["python", "server.py"]
