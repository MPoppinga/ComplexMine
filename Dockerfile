FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Make the entrypoint script executable
RUN chmod +x docker-entrypoint.sh

# Create necessary directories
RUN mkdir -p data/complexmine_db/shelf/

# Expose the port the app runs on
EXPOSE 5000

# Set the entrypoint script
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Command to run the application
CMD ["python", "app.py", "--cachetype", "redis", "--dbtype", "postgresql"] 