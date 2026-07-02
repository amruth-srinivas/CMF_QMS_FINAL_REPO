# Python 3.10.11 base image
FROM python:3.11-slim-bookworm

# Prevent Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Force logs to stdout
ENV PYTHONUNBUFFERED=1

# PaddleOCR related settings
ENV FLAGS_use_mkldnn=0
ENV FLAGS_enable_mkldnn=0

# Working directory
WORKDIR /app

# Install Linux dependencies
# Install system dependencies
RUN apt-get update && \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    gcc \
    g++ \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first
COPY requirements.txt .

# Upgrade pip
RUN pip install --upgrade pip

RUN pip install --no-cache-dir \
    torch==2.5.1+cpu \
    torchvision==0.20.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose FastAPI port
EXPOSE 8989

# Start application
CMD ["python", "main.py"]