FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=on

WORKDIR /app

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy source code
COPY app /app/app
COPY workers /app/workers
COPY core /app/core
COPY scripts /app/scripts
COPY db /app/db
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic

EXPOSE 8000

# Default command runs the FastAPI scheduler (Producer)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


