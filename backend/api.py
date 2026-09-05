"""Composition-root shim: kept at backend/api.py (unchanged path) so
`uvicorn api:app` / `python -m uvicorn api:app` and the docker-compose `web`
service keep working unmodified after the DDD rewrite. All logic lives in
interfaces.http.api; see docs/context.md.
"""
from interfaces.http.api import app  # noqa: F401
