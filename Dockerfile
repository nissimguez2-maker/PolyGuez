FROM python:3.11-slim

# curl is needed for the HEALTHCHECK line below.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Dependency notes:
#   * pysha3 is broken on Python 3.11; safe-pysha3 is a drop-in replacement
#     that exposes the same `pysha3` module. It's installed first so anything
#     importing `pysha3` resolves to the safe build.
#   * eip712-structs pins pysha3 as a transitive dep, so we install it with
#     --no-deps to avoid pulling the broken pysha3 wheel. It is intentionally
#     *not* listed in requirements.txt for this reason.
RUN pip install --no-cache-dir safe-pysha3==1.0.4 && \
    pip install --no-cache-dir --no-deps eip712-structs==1.1.0 && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=.
ENV PYTHONUNBUFFERED=1

EXPOSE ${PORT:-8080}

# Real health signal: /health returns 503 if the event loop is stalled, the
# BTC feed is down, or the runner is killed — so Railway restarts a dead bot
# instead of happily routing traffic to a zombie FastAPI thread.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8080}/health" || exit 1

CMD python scripts/python/cli.py run-polyguez --dashboard-port ${PORT:-8080}
