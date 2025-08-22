FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# Set uv configuration
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /build

# Copy dependency files for caching
COPY pyproject.toml ./
COPY src/ ./src/
COPY uv.lock ./

# Create virtual environment and install dependencies
RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python .

# Runtime stage - use Python image with same version as builder
FROM python:3.13-slim AS runtime
#
# Author: dev@charmhealthtech.com
#
# Accept build arguments for labels
ARG GIT_COMMIT_HASH="unknown"
ARG BUILD_DATE="unknown"

# Add metadata labels
LABEL org.opencontainers.image.revision="${GIT_COMMIT_HASH}" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    org.opencontainers.image.title="MCP Server Charmhealth" \
    org.opencontainers.image.description="Model Context Protocol server for charmhealth" \
    org.opencontainers.image.source="https://github.com/CharmHealth/charm-mcp-server"

# Create non-root user
RUN useradd --system --uid 1001 chrmuser

WORKDIR /app

# Copy virtual environment and application from builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src/ ./src/

# Set up Python environment
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Change ownership to non-root user
RUN chown -R chrmuser:chrmuser /app /opt/venv
USER chrmuser

EXPOSE 8080

ENTRYPOINT [ "python3", "src/mcp_server.py" ]