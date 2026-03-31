FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .

# Install safe-pysha3 first (drop-in for pysha3 on Python 3.11+),
# then install requirements skipping the broken pysha3 line.
# eip712-structs depends on pysha3 but safe-pysha3 provides the same module.
RUN pip install --no-cache-dir safe-pysha3==1.0.4 && \
    grep -iv '^pysha3\|^eip712-structs' requirements.txt | pip install --no-cache-dir -r /dev/stdin && \
    pip install --no-cache-dir --no-deps eip712-structs==1.1.0

COPY . .

ENV PYTHONPATH=.
ENV PYTHONUNBUFFERED=1

EXPOSE ${PORT:-8080}

CMD ["python", "scripts/python/inspect_market.py"]
