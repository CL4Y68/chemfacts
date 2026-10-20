# chemfacts MCP server — multi-client, shareable deployment
#
#   docker build -t chemfacts-mcp .
#   docker run -p 8000:8000 -v chemfacts-data:/data chemfacts-mcp
#
# The /data volume holds the shared retrieval database:
#   /data/facts.db        SQLite fact cache (provenance kept on reload)
#   /data/aliases.json    abbreviation -> CAS registry (edit + volume-share)
#
# Then point ANY MCP client at  http://<host>:8000/mcp
# (if the host uses a global HTTP proxy, NO_PROXY=127.0.0.1,localhost for local access).

FROM python:3.11-slim

WORKDIR /app

# installs from the local source tree (pip install .). Once chemfacts is
# published to PyPI, replace with: RUN pip install --no-cache-dir chemfacts
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

# shared, persistent retrieval DB
ENV CHEMFACTS_CACHE_DIR=/data \
    CHEMFACTS_ALIASES=/data/aliases.json
VOLUME ["/data"]

EXPOSE 8000

ENTRYPOINT ["python", "-m", "chemfacts.mcp_server"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
