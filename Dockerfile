# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS node-runtime

FROM python:3.13-slim-bookworm AS python-builder
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM node-runtime AS mcp-builder
ARG FILESYSTEM_MCP_VERSION=1.0.0
RUN npm install --global --omit=dev @modelcontextprotocol/server-filesystem@${FILESYSTEM_MCP_VERSION}

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:/usr/local/bin:${PATH}" \
    PORT=8080
COPY --from=mcp-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=mcp-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s ../lib/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js /usr/local/bin/mcp-server-filesystem \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app
COPY --from=python-builder /opt/venv /opt/venv
WORKDIR /app
COPY agent.py ./
COPY app/ ./app/
COPY integrations/ ./integrations/
RUN mkdir -p workspace/files/inputs workspace/files/outputs \
    && chown -R app:app workspace
USER 10001:10001
EXPOSE 8080
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1"]
