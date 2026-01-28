FROM python:3.12-slim

# Install system dependencies for Cursor CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    ca-certificates \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Cursor CLI
RUN curl https://cursor.com/install -fsS | bash

# Set working directory
WORKDIR /app

# Create venv to avoid PEP 668 system package limits
RUN python -m venv /opt/venv
# Include venv and Cursor CLI binaries in PATH
ENV PATH="/opt/venv/bin:/root/.local/bin:$PATH"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY models.json ./models.json

# Run the application
CMD ["python", "-m", "src.main"]
