# Stage 1: Build
# Pin to a specific hash for production: python:3.11-slim@sha256:<hash>
FROM python:3.11-slim AS builder
WORKDIR /app
COPY service/requirements.txt .
RUN pip install --no-cache-dir --target=/app/deps -r requirements.txt

# Stage 2: Runtime
# Pin to a specific hash for production: python:3.11-slim@sha256:<hash>
FROM python:3.11-slim
RUN useradd --create-home appuser
WORKDIR /app
COPY --from=builder /app/deps /usr/local/lib/python3.11/site-packages/
COPY service/ ./service/
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["python", "-m", "uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
