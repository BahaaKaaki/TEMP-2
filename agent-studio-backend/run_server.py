#!/usr/bin/env python3
"""
Convenience script to run the Agent Builder API server.
"""
import uvicorn
import os
import sys
import multiprocessing
from pathlib import Path

app_dir = Path(__file__).parent / "app"
sys.path.insert(0, str(app_dir))


def _default_workers() -> int:
    """One worker per core — appropriate for async (Uvicorn) workloads."""
    return max(multiprocessing.cpu_count(), 1)


if __name__ == "__main__":
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"
    workers_env = os.getenv("API_WORKERS")
    workers = int(workers_env) if workers_env else _default_workers()
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    # Uvicorn requires single-worker mode when reload is active
    effective_workers = 1 if reload else workers

    print(f"Starting Agent Builder API on {host}:{port}")
    print(f"  Workers: {effective_workers}  (reload={reload})")
    print(f"  Docs:    http://localhost:{port}/docs")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["app"] if reload else None,
        reload_excludes=[".venv", "__pycache__", "*.pyc", ".git", "logs", "uploads"] if reload else None,
        workers=effective_workers,
        log_level=log_level,
        access_log=True,
    )

