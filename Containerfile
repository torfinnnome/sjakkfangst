# Sjakkfangst Flask Application Container
# Multi-stage build for minimal runtime image

# --- Build Stage ---
FROM python:3.12-alpine AS builder

# Install build dependencies
RUN apk add --no-cache gcc musl-dev libffi-dev

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Runtime Stage ---
FROM python:3.12-alpine

# Install runtime dependencies (wget for healthcheck)
RUN apk add --no-cache wget

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Python environment settings for containerized operation
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

# Create non-root user
RUN adduser -D -u 1000 appuser

# Set working directory
WORKDIR /app

# Create cache directory with proper permissions
RUN mkdir -p /cache/tournaments /cache/players && \
    chown -R appuser:appuser /cache

# Environment variables for cache configuration
ENV CACHE_DIR=/cache \
    CACHE_TTL_HOURS=24

# Copy application code
COPY --chown=appuser:appuser app.py scraper.py pgn_processor.py cache.py ./
COPY --chown=appuser:appuser templates/ ./templates/

# Switch to non-root user
USER appuser

# Expose cache directory as volume for persistence
VOLUME ["/cache"]

# Expose Flask port
EXPOSE 5000

# Health check using Flask's built-in server
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:5000/ || exit 1

# Run Flask application
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"]
