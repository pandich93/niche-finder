"""Composition-root shim: kept at backend/worker.py (unchanged path) so
`python worker.py` / `command: ["python", "worker.py"]` in docker-compose
keeps working unmodified after the DDD rewrite. All logic lives in
application.worker_cycle; see docs/context.md.
"""
from application.worker_cycle import main

if __name__ == "__main__":
    main()
