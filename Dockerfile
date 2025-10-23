# Use Python ARM64 image for Raspberry Pi compatibility
FROM --platform=linux/arm64 python:3.11

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    unzip \
    nginx \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY . .

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_ENV=production

# Expose Flask port
EXPOSE 5000

# Start Flask directly
CMD ["python", "app.py"]

# Copy entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Unified entrypoint for Flask + Nginx + Ngrok
ENTRYPOINT ["/app/entrypoint.sh"]
