# Dockerfile for LIVA Voice Assistant - Optimized for Raspberry Pi
# Uses Python 3.11 slim image for ARM architecture (ARMv7/ARMv8)

FROM python:3.11-slim

# Set metadata
LABEL maintainer="M&M Software GmbH"
LABEL description="LIVA Voice Assistant - Raspberry Pi Edition (Non-Thinking Model Only)"

# Set working directory
WORKDIR /app

# Install system dependencies required for Raspberry Pi
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libopenblas-dev \
    libatlas-base-dev \
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    zlib1g-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
# Using --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create data directories
RUN mkdir -p /app/data/voiceprints && \
    mkdir -p /app/models/faster-whisper && \
    mkdir -p /app/logs

# Expose port for API
EXPOSE 8000

# Environment variables for Raspberry Pi optimization
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV LIVA_NON_THINKING_MODEL=qwen2.5:1.5b-instruct
ENV LIVA_OLLAMA_URL=http://127.0.0.1:11434

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# Start the FastAPI application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
