FROM python:3.12-slim

WORKDIR /app

# INSTALL_ML=true adds the local AI models (the `ml` extra) with CPU-only PyTorch; the
# default leaves them out, since they don't fit a 512 MB free instance and default to stubs.
ARG INSTALL_ML=false

# asyncpg and pgvector ship manylinux wheels, so no compiler or libpq is needed.
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations

RUN if [ "$INSTALL_ML" = "true" ]; then \
      pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
      && pip install --no-cache-dir ".[ml]"; \
    else \
      pip install --no-cache-dir .; \
    fi

EXPOSE 8000

# Render (and most hosts) set $PORT; 8000 locally. --proxy-headers so the client IP and
# scheme come from the host's proxy.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
