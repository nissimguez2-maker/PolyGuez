FROM node:20-slim

# Install system deps
RUN apt-get update && apt-get install -y \
    git curl python3 python3-pip \
    --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install claude CLI and make sure it's on PATH
RUN npm install -g @anthropic-ai/claude-code && \
    ln -sf $(npm root -g)/.bin/claude-code /usr/local/bin/claude && \
    claude --version

WORKDIR /app

COPY package.json ./
RUN npm install --production

COPY server.js ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 3333

CMD ["./entrypoint.sh"]
