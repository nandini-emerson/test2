FROM python:3.11-slim

# Install OS dependencies for httpx, uvicorn, cryptography, and general Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Create app directory
WORKDIR /app

# Copy requirements file and install dependencies
COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose API port
EXPOSE 8000

# Default startup command
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8000"]