# Use a slim Python base image for ARM compatibility
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Playwright and other requirements
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    wget \
    fonts-liberation \
    libnss3 \
    libxss1 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers with dependencies
RUN python -m playwright install --with-deps chromium firefox

# Copy the rest of the project files
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Set environment variable to ensure Python output is not buffered
ENV PYTHONUNBUFFERED=1

# Default command (will be overridden in docker-compose)
CMD ["python", "-m", "cli", "--city-scan", "--cities", "utrecht", "--sources", "funda,pararius"]