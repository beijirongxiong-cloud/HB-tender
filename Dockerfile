FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN playwright install chromium \
    && playwright install-deps chromium || true

COPY . .

RUN mkdir -p /app/data

CMD ["python", "-m", "src.main"]
