"""Composition-root shim: kept at backend/server.py (unchanged path) so
`python server.py`, `CMD ["python", "server.py"]` in Dockerfile, and the
docker-compose `mcp`/`mcp-http` services keep working unmodified after the
DDD rewrite. All logic lives in interfaces.mcp.server; see docs/context.md.
"""
from interfaces.mcp.server import mcp, run  # noqa: F401  (mcp re-exported for tooling/tests)

if __name__ == "__main__":
    run()
