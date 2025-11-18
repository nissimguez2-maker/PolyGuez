FROM python:3.12-slim

# Install uv
RUN apt-get update && apt-get install -y curl && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.cargo/bin/uv /usr/local/bin/ && \
    apt-get remove -y curl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

COPY . /home
WORKDIR /home

# Install dependencies using uv and the package in editable mode
RUN uv pip install --system -e .
