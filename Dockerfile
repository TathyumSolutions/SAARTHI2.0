FROM python:3.11-slim

WORKDIR /app

# Prefer CPU-only PyTorch wheels to avoid pulling large CUDA packages in Docker
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    libpq-dev \
    unixodbc-dev \
    libaio-dev \
    python3-dev \
    python3-setuptools \
    python3-pkg-resources \
    libmagic-dev \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip, setuptools, and wheel before installing requirements
RUN pip install --upgrade pip setuptools wheel

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install premsql==0.1.0 --no-deps || true

# Copy application code
COPY . .

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "run:app"]
