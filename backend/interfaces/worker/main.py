"""Entrypoint for the background worker. All the logic lives in
application.worker_cycle -- this module is a thin delegate."""
from application.worker_cycle import main

if __name__ == "__main__":
    main()
