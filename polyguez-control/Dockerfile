FROM node:20-slim

# Install system deps: git, python3, curl
RUN apt-get update && apt-get install -y \
    git curl python3 python3-pip python3-venv \
    --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Set working dir for the control panel
WORKDIR /app

# Copy and install control panel deps
COPY package.json ./
RUN npm install --production

# Copy server
COPY server.js ./

# Clone the PolyGuez repo at startup (via entrypoint script)
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 3333

CMD ["./entrypoint.sh"]
