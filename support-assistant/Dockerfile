# Production Dockerfile for NovaRetail Customer Support Assistant
FROM python:3.11-slim AS base

WORKDIR /app

# Install system utilities and libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "services.assistant_api.gateway_app:app", "--host", "0.0.0.0", "--port", "8000"]
