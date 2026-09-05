"""Composition-root shim: kept at backend/cli.py (unchanged path) so
`python cli.py <command>` and `docker compose run --rm mcp python cli.py ...`
keep working unmodified after the DDD rewrite. All logic lives in
interfaces.cli.cli; see docs/context.md.
"""
from interfaces.cli.cli import main

if __name__ == "__main__":
    main()
