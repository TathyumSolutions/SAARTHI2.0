FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libpq-dev \
    libaio-dev \
    python3-dev \
    python3-setuptools \
    python3-pkg-resources \
    libmagic-dev \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and wheel; pin setuptools below the release that dropped the
# pkg_resources shim, since cx_Oracle's legacy setup.py still imports it
# (this constraint also applies inside pip's build-isolation subprocess).
COPY build-constraints.txt .
ENV PIP_CONSTRAINT=/app/build-constraints.txt
RUN pip install --upgrade pip wheel "setuptools<81"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install premsql==0.1.0 --no-deps

# Copy application code
COPY . .

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "run:app"]
