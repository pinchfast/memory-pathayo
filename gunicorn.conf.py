# Gunicorn configuration file
# https://docs.gunicorn.org/en/stable/configure.html#configuration-file
# https://docs.gunicorn.org/en/stable/settings.html
import multiprocessing
import os

max_requests = 1000
max_requests_jitter = 50

log_file = "-"

# Cloud Run provides PORT env var (default 8080); fall back to 80 for local
port = os.environ.get("PORT", "80")
bind = f"0.0.0.0:{port}"
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
timeout = 300
