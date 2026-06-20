# Slim, production-ready image for the FastAPI DSSG web app.
FROM python:3.12-slim

# Avoid .pyc files and buffered stdout in containers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DSSG_DATA_DIR=/data

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY . .

# Run as a non-root user; /data holds the permanently stored uploads/reports.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /data /app
USER app

VOLUME ["/data"]
EXPOSE 8000

# 2 workers is plenty for a small box; bump for bigger instances.
CMD ["uvicorn", "dssg.web:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
